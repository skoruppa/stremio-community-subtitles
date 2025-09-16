import os
import datetime
import json
import base64
import tempfile
import uuid

import requests  # For fetching from Cloudinary URL
from flask import Blueprint, url_for, Response, request, current_app, flash, redirect, render_template  # Added redirect
from flask_login import current_user, login_required
from sqlalchemy.orm import Session
from iso639 import Lang

from ..forms import SubtitleUploadForm
from ..languages import LANGUAGES
from ..lib import opensubtitles_client
from ..lib.metadata import get_metadata
from ..lib.opensubtitles_client import make_request_with_retry

try:
    import cloudinary
    import cloudinary.uploader
    import cloudinary.api

    CLOUDINARY_AVAILABLE = True
except ImportError:
    CLOUDINARY_AVAILABLE = False
from ..extensions import db
from ..models import User, Subtitle, UserActivity, UserSubtitleSelection, SubtitleVote  
from ..lib.subtitles import convert_to_vtt
from .utils import respond_with, get_active_subtitle_details, respond_with_no_cache, NoCacheResponse, no_cache_redirect
from urllib.parse import parse_qs, unquote
import gzip
import io
import hashlib # Import hashlib for SHA256 hashing

subtitles_bp = Blueprint('subtitles', __name__)


def _get_vtt_content(subtitle):
    """
    Helper function to get VTT content for a given subtitle.
    Handles both Cloudinary and local storage.
    """
    if not subtitle.file_path:
        raise ValueError("Subtitle has no file_path")

    if current_app.config['STORAGE_BACKEND'] == 'cloudinary':
        if not CLOUDINARY_AVAILABLE or not cloudinary.config().api_key:
            raise Exception("Cloudinary not configured/available")
        
        generated_url_info = cloudinary.utils.cloudinary_url(subtitle.file_path, resource_type="raw", secure=True)
        cloudinary_url = generated_url_info[0] if isinstance(generated_url_info, tuple) else generated_url_info
        if not cloudinary_url: 
            raise Exception("Cloudinary URL generation failed")
        
        r = requests.get(cloudinary_url, timeout=10)
        r.raise_for_status()
        return r.text
    else:
        local_full_path = os.path.join(current_app.config['UPLOAD_FOLDER'], subtitle.file_path)
        if not os.path.exists(local_full_path):
            raise FileNotFoundError("Local subtitle file not found")
        
        with open(local_full_path, 'r', encoding='utf-8') as f:
            return f.read()


def generate_vtt_message(message: str) -> str:
    """Generates a simple VTT file content displaying a message."""
    return f"WEBVTT\n\n00:00:00.000 --> 00:05:00.000\n{message}"


@subtitles_bp.route('/<manifest_token>/subtitles/<content_type>/<content_id>/<params>.json')
@subtitles_bp.route('/<manifest_token>/subtitles/<content_type>/<content_id>/<path:params>')
@subtitles_bp.route('/<manifest_token>/subtitles/<content_type>/<content_id>.json')
def addon_stream(manifest_token: str, content_type: str, content_id: str, params: str = None):
    """
    Handles the subtitle request from Stremio using the user's manifest token.
    Generates an encoded identifier for the download URL.
    """
    # Find user by manifest token
    user = User.get_by_manifest_token(manifest_token)
    if not user:
        current_app.logger.warning(f"Subtitle request with invalid token: {manifest_token}")
        return respond_with({'subtitles': []})

    # Ensure user has a personal API key if OS integration is active
    # The _get_api_key function will now raise an error if no user key is present
    # We can rely on the OS client functions to handle the missing key error.
    # However, a check here provides a more immediate response to Stremio.
    if user.opensubtitles_active and not user.opensubtitles_token:
        current_app.logger.error(f"User {user.username} has OS integration active but no token.")
        # Respond with an empty list or an error message subtitle
        # Generating a VTT error message might be better for the user experience in Stremio
        return respond_with({'subtitles': [{'id': 'error',
                                            'url': url_for('subtitles.unified_download', manifest_token=manifest_token,
                                                           download_identifier=base64.urlsafe_b64encode(json.dumps({
                                                                                                                       'message': 'OpenSubtitles integration active but no API key configured.'}).encode(
                                                               'utf-8')).decode('utf-8').rstrip('=')), 'lang': 'eng'}]})

    # --- Parameter Extraction ---
    content_id = unquote(content_id)
    if content_id.startswith("mal:"):
        current_app.logger.info(f"Ignoring as those are probably from the Docchi extension with hardcoded subs")
        return respond_with({'subtitles': []})

    try:
        param_string_to_parse = request.query_string.decode() if request.query_string else params
        parsed_params = {k: v[0] for k, v in parse_qs(param_string_to_parse).items() if v}
    except Exception as e:
        current_app.logger.error(f"Failed to parse params '{params}' or query string '{request.query_string}': {e}")
        parsed_params = {}

    video_hash = parsed_params.get('videoHash')
    video_size_str = parsed_params.get('videoSize')
    video_filename = parsed_params.get('filename')

    video_size = None
    if video_size_str:
        try:
            video_size = int(video_size_str)
        except ValueError:
            current_app.logger.warning(f"Could not convert videoSize '{video_size_str}' to integer.")

    preferred_langs = user.preferred_languages
    current_app.logger.info(
        f"Subtitle request: User={user.username}, Lang={','.join(preferred_langs)}, Content={content_type}/{content_id}, Hash={video_hash}, Size={video_size}, Filename={video_filename}")

    # Log user activity
    try:
        activity_found_and_updated = False

        if video_hash is not None and video_size is not None:
            existing_activity = UserActivity.query.filter_by(
                user_id=user.id,
                content_id=content_id,
                video_hash=video_hash,
                video_size=video_size
            ).first()
            if existing_activity:
                existing_activity.timestamp = datetime.datetime.utcnow()
                if video_filename:  # Update filename if a new one is provided
                    existing_activity.video_filename = video_filename
                current_app.logger.info(
                    f"Updated existing UserActivity ID {existing_activity.id} (match by hash/size) for user {user.id}, hash {video_hash}, size {video_size}")
                activity_found_and_updated = True

        elif video_hash is None:
            existing_activity = UserActivity.query.filter_by(
                user_id=user.id,
                content_id=content_id,
                video_hash=None,
                video_size=video_size,
                video_filename=video_filename
            ).first()
            if existing_activity:
                existing_activity.timestamp = datetime.datetime.utcnow()
                current_app.logger.info(
                    f"Updated existing UserActivity ID {existing_activity.id} (match by filename, no hash/size) for user {user.id}, filename {video_filename}")
                activity_found_and_updated = True

        if not activity_found_and_updated:
            new_activity = UserActivity(
                user_id=user.id,
                content_id=content_id,
                content_type=content_type,
                video_hash=video_hash,
                video_size=video_size,
                video_filename=video_filename
            )
            db.session.add(new_activity)
            current_app.logger.info(
                f"Created new UserActivity for user {user.id}, content {content_id}, hash {video_hash}, size {video_size}, filename {video_filename}")

        max_activities = current_app.config.get('MAX_USER_ACTIVITIES', 15)+1

        current_persisted_count = UserActivity.query.filter_by(user_id=user.id).count()
        effective_count_after_commit = current_persisted_count
        if not activity_found_and_updated:
            effective_count_after_commit += 1

        if effective_count_after_commit > max_activities:
            num_to_delete = effective_count_after_commit - max_activities
            if num_to_delete > 0:  # Ensure we actually need to delete
                oldest_activities = UserActivity.query.filter_by(user_id=user.id).order_by(
                    UserActivity.timestamp.asc()).limit(num_to_delete).all()
                for old_activity in oldest_activities:
                    db.session.delete(old_activity)
                    current_app.logger.info(
                        f"Deleted oldest UserActivity ID {old_activity.id} for user {user.id} to maintain limit of {max_activities}.")

        db.session.commit()
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Failed to log or update user activity for user {user.id}: {e}", exc_info=True)

    for preferred_lang in preferred_langs:
        download_context = {
            'content_type': content_type,
            'content_id': content_id,
            'lang': preferred_lang,
            'v_hash': video_hash,
            'v_size': video_size,
            'v_fname': video_filename
        }
        try:
            context_json = json.dumps(download_context, separators=(',', ':'))
            download_identifier = base64.urlsafe_b64encode(context_json.encode('utf-8')).decode('utf-8').rstrip('=')
        except Exception as e:
            current_app.logger.error(f"Failed to encode download context: {e}")
            return respond_with({'subtitles': []})

        subtitles_list = []
        try:
            download_url = url_for('subtitles.unified_download',
                                   manifest_token=manifest_token,
                                   download_identifier=download_identifier,
                                   _external=True,
                                   _scheme=current_app.config['PREFERRED_URL_SCHEME'])
            stremio_sub_id = f"comm_{download_identifier}"
            subtitles_list.append({
                'id': stremio_sub_id,
                'url': download_url,
                'lang': preferred_lang
            })
            current_app.logger.info(f"Generated download URL for context: {download_context}")
        except Exception as e:
            current_app.logger.error(f"Error generating download URL for identifier {download_identifier}: {e}")
            return respond_with({'subtitles': []})

    return respond_with_no_cache({'subtitles': subtitles_list})


@subtitles_bp.route('/<manifest_token>/download/<download_identifier>.vtt')
def unified_download(manifest_token: str, download_identifier: str):
    user = User.get_by_manifest_token(manifest_token)
    if not user:
        current_app.logger.warning(f"Download request with invalid token: {manifest_token}")
        return NoCacheResponse(generate_vtt_message("Invalid Access Token"), status=403, mimetype='text/vtt')

    try:
        padding_needed = len(download_identifier) % 4
        if padding_needed:
            download_identifier += '=' * (4 - padding_needed)
        context_json = base64.urlsafe_b64decode(download_identifier.encode('utf-8')).decode('utf-8')
        context = json.loads(context_json)
        content_id = context.get('content_id')
        lang = context.get('lang')
        video_hash = context.get('v_hash')
        video_filename = context.get('v_fname')
        content_type = context.get('content_type', '')
        if not content_id:
            raise ValueError("Missing content_id in decoded context")
    except Exception as e:
        current_app.logger.error(f"Failed to decode download identifier '{download_identifier}': {e}")
        return NoCacheResponse(generate_vtt_message("Invalid download link."), status=400, mimetype='text/vtt')

    # Use the utility function to get active subtitle details (now with OpenSubtitles fallback)
    active_subtitle_info = get_active_subtitle_details(user, content_id, video_hash, content_type, video_filename, lang)

    local_subtitle_to_serve = None
    opensubtitle_to_serve_details = None
    message_key = None
    vtt_content = None

    if active_subtitle_info['type'] == 'local':
        local_subtitle_to_serve = active_subtitle_info['subtitle']
        if local_subtitle_to_serve:
            current_app.logger.info(
                f"Serving active local subtitle ID {local_subtitle_to_serve.id}")
    elif active_subtitle_info['type'] in ['opensubtitles_selection', 'opensubtitles_auto']:
        opensubtitle_to_serve_details = active_subtitle_info['details']
        # Handle community_link compatibility
        if 'file_id' not in opensubtitle_to_serve_details and 'original_file_id' in opensubtitle_to_serve_details:
            opensubtitle_to_serve_details['file_id'] = opensubtitle_to_serve_details['original_file_id']

        if opensubtitle_to_serve_details and 'file_id' in opensubtitle_to_serve_details:
            current_app.logger.info(
                f"Serving OpenSubtitle file_id {opensubtitle_to_serve_details['file_id']} (type: {active_subtitle_info['type']})")
        else:
            current_app.logger.error(f"OpenSubtitles details missing file_id: {opensubtitle_to_serve_details}")
            opensubtitle_to_serve_details = None

    # Serve local subtitle
    if local_subtitle_to_serve:
        # Handle community_link case
        if local_subtitle_to_serve.source_type == 'opensubtitles_community_link' and \
                local_subtitle_to_serve.source_metadata and \
                local_subtitle_to_serve.source_metadata.get('original_file_id'):

            if user.opensubtitles_active and user.opensubtitles_token and user.opensubtitles_base_url:
                os_file_id = local_subtitle_to_serve.source_metadata.get('original_file_id')
                opensubtitle_to_serve_details = {
                    'file_id': os_file_id,
                    'details': local_subtitle_to_serve.source_metadata
                }
                current_app.logger.info(
                    f"Identified linked OpenSubtitle (original OS file_id: {os_file_id}) via local Subtitle ID {local_subtitle_to_serve.id}")
                local_subtitle_to_serve = None  # Switch to OS serving
            else:
                current_app.logger.warning(
                    f"User has a linked OpenSubtitle selected but OS integration is not active")
                message_key = 'os_integration_inactive'
                local_subtitle_to_serve = None

        elif local_subtitle_to_serve.file_path:  # Standard community-uploaded subtitle
            current_app.logger.info(f"Serving community subtitle ID {local_subtitle_to_serve.id}")
            try:
                vtt_content = _get_vtt_content(local_subtitle_to_serve)
            except Exception as e:
                current_app.logger.error(f"Error reading local subtitle ID {local_subtitle_to_serve.id}: {e}",
                                         exc_info=True)
                message_key = 'error'
        else:
            current_app.logger.error(
                f"Local subtitle ID {local_subtitle_to_serve.id} has no file_path")
            message_key = 'error'

    # Serve OpenSubtitles subtitle
    os_subtitle_direct_url = None
    if opensubtitle_to_serve_details and opensubtitle_to_serve_details.get('file_id') and not vtt_content:
        os_file_id = opensubtitle_to_serve_details['file_id']

        if not user.opensubtitles_active or not user.opensubtitles_token or not user.opensubtitles_base_url:
            current_app.logger.warning(
                f"Attempting to serve OpenSubtitle file_id {os_file_id}, but user's OS integration is not active")
            message_key = 'os_integration_inactive'
        else:
            current_app.logger.info(f"Attempting to serve OpenSubtitle file_id: {os_file_id}")
            try:
                download_info = opensubtitles_client.request_download_link(
                    file_id=os_file_id,
                    user=user
                )
                if download_info and download_info.get('link'):
                    os_subtitle_direct_url = download_info['link']
                    remaining_downloads = download_info.get('remaining')
                    if remaining_downloads is not None and int(remaining_downloads) <= 10:
                        current_app.logger.warning(
                            f"OpenSubtitles API downloads remaining for user {user.username}: {remaining_downloads}")
                    current_app.logger.info(f"Serving OpenSubtitles direct url")

            except opensubtitles_client.OpenSubtitlesError as e:
                current_app.logger.error(f"OpenSubtitles API error while serving file_id {os_file_id}: {e}. "
                                         f"Try to relogin through the account's settings")
                message_key = 'os_error_contact_support'
            except Exception as e:
                current_app.logger.error(f"Unexpected error serving OpenSubtitle file_id {os_file_id}: {e}",
                                         exc_info=True)
                message_key = 'os_error_contact_support'

    if os_subtitle_direct_url:
        def make_request():
            return requests.get(os_subtitle_direct_url, timeout=10)

        try:
            vtt_content = make_request_with_retry(make_request).text
        except Exception as e:
            current_app.logger.error(f"Unexpected error forwarding OpenSubtitle file_id {os_subtitle_direct_url}: {e}",
                                     exc_info=True)
            message_key = 'error'

    if vtt_content:
        if not vtt_content.strip().upper().startswith("WEBVTT"):
            current_app.logger.warning("Content served is not VTT, serving as plain text")
            return NoCacheResponse(vtt_content, mimetype='text/plain')
        return NoCacheResponse(vtt_content, mimetype='text/vtt')

    # Fallback messages
    if not message_key:
        message_key = 'no_subs_found'

    messages = {
        'no_subs_found': "SCS: No Subtitles Found: Upload your own through the web interface.",
        'error': "SCS: An error occurred, please try again in a short period",
        'os_integration_inactive': "SCS: OpenSubtitles integration is inactive. Please activate it in account settings to use this feature.",
        'os_error_contact_support': "SCS: Error fetching from OpenSubtitles. Please try again later or check your account on OpenSubtitles.com."
    }
    message_text = messages.get(message_key, "An error occurred or subtitles need selection.")
    current_app.logger.info(f"Serving placeholder message (key: '{message_key}') for context: {context}")
    return NoCacheResponse(generate_vtt_message(message_text), mimetype='text/vtt')


@subtitles_bp.route('/content/<uuid:activity_id>/upload', methods=['GET', 'POST'])
@subtitles_bp.route('/content/upload', methods=['GET', 'POST'])
@login_required
def upload_subtitle(activity_id=None):
    """Handle subtitle upload from the web interface."""
    activity = None
    is_advanced_upload = activity_id is None

    # For regular upload (with activity_id)
    if not is_advanced_upload:
        activity = UserActivity.query.filter_by(id=activity_id, user_id=current_user.id).first_or_404()

    season = None
    episode = None
    content_id = None
    content_type = None
    video_hash = None

    if activity:
        # Regular upload - get data from activity
        content_id = activity.content_id
        content_type = activity.content_type
        video_hash = activity.video_hash

        if activity.content_type == 'series':
            content_parts = activity.content_id.split(':')
            try:
                if len(content_parts) == 3:
                    season = int(content_parts[1])
                    episode = int(content_parts[2])
                elif len(content_parts) == 2:
                    season = 1
                    episode = int(content_parts[1])
            except ValueError:
                current_app.logger.warning(f"Could not parse season/episode from content_id: {activity.content_id}")

    # Get metadata for display
    try:
        metadata = get_metadata(content_id, content_type)
    except Exception as e:
        current_app.logger.warning(f"Could not fetch metadata for {content_id}: {e}")
        metadata = None

    form = SubtitleUploadForm()
    form.language.choices = LANGUAGES

    # Add fields for advanced upload
    if is_advanced_upload:
        # You'll need to add these fields to your SubtitleUploadForm class
        # Or create a new form class for advanced upload
        if not hasattr(form, 'content_id'):
            from wtforms import StringField, SelectField, IntegerField
            from wtforms.validators import DataRequired, Optional

            # Dynamically add fields if they don't exist
            form.content_id = StringField('Content ID', validators=[DataRequired()])
            form.content_type = SelectField('Content Type',
                                            choices=[('movie', 'Movie'), ('series', 'Series')],
                                            validators=[DataRequired()])
            form.season_number = IntegerField('Season Number', validators=[Optional()])
            form.episode_number = IntegerField('Episode Number', validators=[Optional()])

    if request.method == 'GET':
        # Set default language based on browser preference or first preferred language
        selected_language = None
        if current_user.preferred_languages:
            browser_prefs = request.accept_languages.values()
            for browser_pref in browser_prefs:
                try:
                    lang_code_browser = browser_pref.split('-')[0].strip()
                    lang_obj_browser = Lang(lang_code_browser)
                    # Check if browser's 3-letter code is in user's preferred languages
                    if lang_obj_browser.pt3 in current_user.preferred_languages:
                        selected_language = lang_obj_browser.pt3
                        break
                except KeyError:
                    current_app.logger.warning(f"iso639-lang could not convert browser lang code {browser_pref} to ISO 639-3.")
            
            if selected_language:
                form.language.data = selected_language
            else:
                form.language.data = current_user.preferred_languages[0] # Fallback to first preferred language
        else:
            form.language.data = 'eng' # Default to English if no preferred languages set

        if activity and activity.video_filename:
            form.version_info.data = activity.video_filename.rsplit('.', 1)[0]

    if form.validate_on_submit():
        try:
            # For advanced upload, construct content_id from form data
            if is_advanced_upload:
                base_content_id = form.content_id.data.strip()
                content_type = form.content_type.data

                # Validate content_id format
                if not (base_content_id.startswith('tt') or base_content_id.startswith('kitsu:')):
                    flash('Content ID must be either IMDB ID (starting with "tt") or Kitsu ID (format "kitsu:12345")',
                          'danger')
                    return render_template('main/upload_subtitle.html', form=form, activity=activity,
                                           metadata=metadata, season=season, episode=episode,
                                           is_advanced_upload=is_advanced_upload)

                if content_type == 'series':
                    season_num = form.season_number.data or 1
                    episode_num = form.episode_number.data

                    if not episode_num:
                        flash('Episode number is required for series', 'danger')
                        return render_template('main/upload_subtitle.html', form=form, activity=activity,
                                               metadata=metadata, season=season, episode=episode,
                                               is_advanced_upload=is_advanced_upload)

                    # Construct content_id for series
                    if base_content_id.startswith('tt'):
                        content_id = f"{base_content_id}:{season_num}:{episode_num}"
                    else:  # kitsu format
                        content_id = f"{base_content_id}:{episode_num}"

                    season = season_num
                    episode = episode_num
                else:
                    # For movies, use content_id as is
                    content_id = base_content_id

                # Set video_hash to None for advanced uploads (no specific video file)
                video_hash = None
            else:
                content_id = activity.content_id
                content_type = activity.content_type
                video_hash = activity.video_hash

            subtitle_file = form.subtitle_file.data
            original_filename = subtitle_file.filename
            file_extension = os.path.splitext(original_filename)[1].lower()[1:]
            encoding = form.encoding.data
            fps = form.fps.data
            if encoding.lower() == 'auto':
                encoding = None
            if not fps:
                fps = None
            else:
                try:
                    fps = float(fps)
                except ValueError:
                    fps = None

            base_vtt_filename = f"{uuid.uuid4()}.vtt"
            content_id_safe_path = content_id.replace(':', '_')

            with tempfile.NamedTemporaryFile(delete=False, suffix=file_extension) as temp_file:
                subtitle_file.save(temp_file.name)
                temp_file_path = temp_file.name

            db_file_path = None
            try:
                with open(temp_file_path, 'rb') as f:
                    file_data = f.read()
                try:
                    vtt_content_data = convert_to_vtt(file_data, file_extension, encoding=encoding, fps=fps)
                    current_app.logger.info(f"Successfully converted '{original_filename}' to VTT format in memory.")
                except UnicodeDecodeError as ude:
                    current_app.logger.warning(
                        f"UnicodeDecodeError processing subtitle '{original_filename}' with encoding '{encoding}': {ude}",
                        exc_info=True
                    )
                    flash(
                        "Failed to decode the uploaded subtitle file. This usually means it's not UTF-8 encoded or "
                        "the selected encoding is incorrect. If you are unsure about the encoding, "
                        "please try using the 'auto' option.",
                        'danger'
                    )
                    redirect_url = url_for('subtitles.upload_subtitle') if is_advanced_upload else url_for(
                        'content.content_detail', activity_id=activity_id)
                    return redirect(redirect_url)

                # Calculate SHA256 hash of the VTT content
                vtt_hash = hashlib.sha256(vtt_content_data.encode('utf-8')).hexdigest()
                current_app.logger.info(f"Calculated VTT hash: {vtt_hash}")

                # Check for existing subtitle with the same hash and language
                existing_subtitle_same_hash = Subtitle.query.filter_by(
                    hash=vtt_hash,
                    language=form.language.data
                ).first()

                db_file_path = None
                skip_file_upload = False

                if existing_subtitle_same_hash:
                    if existing_subtitle_same_hash.video_hash == video_hash:
                        # Exact duplicate: same content, same video hash
                        flash('These subtitles already exist for this content and video version.', 'info')
                        redirect_url = url_for('subtitles.upload_subtitle') if is_advanced_upload else url_for(
                            'content.content_detail', activity_id=activity_id)
                        return redirect(redirect_url)
                    else:
                        # Same content, different video hash - reuse file_path
                        db_file_path = existing_subtitle_same_hash.file_path
                        skip_file_upload = True
                        current_app.logger.info(f"Reusing existing subtitle file_path: {db_file_path} for new video_hash.")
                
                if not skip_file_upload:
                    if current_app.config['STORAGE_BACKEND'] == 'cloudinary':
                        if not CLOUDINARY_AVAILABLE or not cloudinary.config().api_key:
                            flash('Server error: Cloudinary storage is not properly configured.', 'danger')
                            redirect_url = url_for('subtitles.upload_subtitle') if is_advanced_upload else url_for(
                                'content.content_detail', activity_id=activity_id)
                            return redirect(redirect_url)

                        cloudinary_folder = current_app.config.get('CLOUDINARY_SUBTITLES_FOLDER', 'community_subtitles')
                        cloudinary_public_id = f"{cloudinary_folder}/{content_id_safe_path}/{base_vtt_filename.replace('.vtt', '')}"
                        upload_result = cloudinary.uploader.upload(vtt_content_data.encode('utf-8'),
                                                                    public_id=cloudinary_public_id, resource_type="raw",
                                                                    overwrite=True)
                        db_file_path = upload_result.get('public_id')
                        if not db_file_path:
                            raise Exception(f"Cloudinary upload failed: {upload_result}")
                        current_app.logger.info(f"Uploaded to Cloudinary. Public ID: {db_file_path}")
                    else:
                        local_content_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], content_id_safe_path)
                        os.makedirs(local_content_dir, exist_ok=True)
                        local_vtt_file_path_full = os.path.join(local_content_dir, base_vtt_filename)
                        with open(local_vtt_file_path_full, 'w', encoding='utf-8') as f:
                            f.write(vtt_content_data)
                        db_file_path = os.path.join(content_id_safe_path, base_vtt_filename)
                        current_app.logger.info(f"Saved to local storage: {local_vtt_file_path_full}")
            except Exception as e:
                db.session.rollback() # Rollback any changes made before the file upload
                current_app.logger.error(f"Error processing/uploading subtitle '{original_filename}': {e}",
                                         exc_info=True)
                flash(f'Error processing/uploading subtitle: {str(e)}', 'danger')
                redirect_url = url_for('subtitles.upload_subtitle') if is_advanced_upload else url_for(
                    'content.content_detail', activity_id=activity_id)
                return redirect(redirect_url)
            finally:
                if os.path.exists(temp_file_path):
                    os.unlink(temp_file_path)

            if not db_file_path:
                flash('Internal error: Subtitle path not determined.', 'danger')
                redirect_url = url_for('subtitles.upload_subtitle') if is_advanced_upload else url_for(
                    'content.content_detail', activity_id=activity_id)
                return redirect(redirect_url)

            new_subtitle = Subtitle(
                id=uuid.uuid4(),
                content_id=content_id,
                content_type=content_type,
                language=form.language.data,
                uploader_id=current_user.id,
                video_hash=video_hash,  # Will be None for advanced uploads
                file_path=db_file_path,
                hash=vtt_hash, # Store the calculated hash
                source_type='community',  # Explicitly set source type
                version_info=form.version_info.data if hasattr(form,
                                                               'version_info') and form.version_info.data else None,
                author=form.author.data if hasattr(form, 'author') and form.author.data else None
            )
            db.session.add(new_subtitle)
            db.session.commit()

            # Auto-select subtitle only for regular uploads (not advanced)
            if not is_advanced_upload:
                try:
                    existing_selection = UserSubtitleSelection.query.filter_by(user_id=current_user.id,
                                                                               content_id=content_id,
                                                                               video_hash=video_hash,
                                                                               language=form.language.data).first()
                    if existing_selection:
                        existing_selection.selected_subtitle_id = new_subtitle.id
                        existing_selection.selected_external_file_id = None
                        existing_selection.external_details_json = None
                        existing_selection.timestamp = datetime.datetime.utcnow()
                    else:
                        new_selection = UserSubtitleSelection(user_id=current_user.id, content_id=content_id,
                                                              video_hash=video_hash,
                                                              selected_subtitle_id=new_subtitle.id,
                                                              language=form.language.data)
                        db.session.add(new_selection)
                    db.session.commit()
                    flash('Subtitle uploaded and selected successfully!', 'success')
                except Exception as sel_e:
                    db.session.rollback()
                    current_app.logger.error(f"Error auto-selecting uploaded subtitle: {sel_e}", exc_info=True)
                    flash('Subtitle uploaded, but failed to auto-select.', 'warning')
            else:
                flash('Subtitle uploaded successfully!', 'success')

            # Redirect appropriately
            if is_advanced_upload:
                return redirect(url_for('subtitles.upload_subtitle'))
            else:
                return redirect(url_for('content.content_detail', activity_id=activity_id))

        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error in upload_subtitle route: {e}", exc_info=True)
            flash('Error uploading subtitle. Please try again.', 'danger')

    return render_template('main/upload_subtitle.html', form=form, activity=activity, metadata=metadata,
                           season=season, episode=episode, is_advanced_upload=is_advanced_upload)


@subtitles_bp.route('/select_subtitle/<uuid:activity_id>/<uuid:subtitle_id>', methods=['POST'])
@login_required
def select_subtitle(activity_id, subtitle_id):
    activity = UserActivity.query.filter_by(id=activity_id, user_id=current_user.id).first_or_404()
    subtitle_to_select = Subtitle.query.get_or_404(subtitle_id)

    try:
        selection = UserSubtitleSelection.query.filter_by(user_id=current_user.id,
                                                          content_id=activity.content_id,
                                                          video_hash=activity.video_hash,
                                                          language=subtitle_to_select.language).first()
        if selection:
            selection.selected_subtitle_id = subtitle_to_select.id
            selection.selected_external_file_id = None
            selection.external_details_json = None
            selection.timestamp = datetime.datetime.utcnow()
        else:
            selection = UserSubtitleSelection(
                user_id=current_user.id,
                content_id=activity.content_id,
                video_hash=activity.video_hash,
                selected_subtitle_id=subtitle_to_select.id,
                language=subtitle_to_select.language
            )
            db.session.add(selection)
        db.session.commit()
        flash('Subtitle selection updated.', 'success')
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error selecting subtitle: {e}", exc_info=True)
        flash('Error updating subtitle selection.', 'danger')
    return redirect(url_for('content.content_detail', activity_id=activity_id))


@subtitles_bp.route('/vote/<uuid:subtitle_id>/<vote_type>', methods=['POST'])
@login_required
def vote_subtitle(subtitle_id, vote_type):
    activity_id = request.form.get('activity_id')
    vote_value = 1 if vote_type == 'up' else -1
    subtitle = Subtitle.query.get_or_404(subtitle_id)

    # Users can only vote on 'community' or 'opensubtitles_community_link' types
    if subtitle.source_type not in ['community', 'opensubtitles_community_link']:
        flash('Voting is not available for this type of subtitle.', 'warning')
        return redirect(request.referrer or url_for('main.dashboard'))

    existing_vote = SubtitleVote.query.filter_by(user_id=current_user.id, subtitle_id=subtitle_id).first()
    try:
        if existing_vote:
            if existing_vote.vote_value == vote_value:  # Undoing vote
                subtitle.votes -= existing_vote.vote_value
                db.session.delete(existing_vote)
                flash('Vote removed.', 'info')
            else:  # Changing vote
                subtitle.votes = subtitle.votes - existing_vote.vote_value + vote_value
                existing_vote.vote_value = vote_value
                flash('Vote updated.', 'success')
        else:  # New vote
            new_vote = SubtitleVote(user_id=current_user.id, subtitle_id=subtitle_id, vote_value=vote_value)
            subtitle.votes += vote_value
            db.session.add(new_vote)
            flash('Vote recorded.', 'success')
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error processing vote: {e}", exc_info=True)
        flash('Error processing vote.', 'danger')

    if activity_id: return redirect(url_for('content.content_detail', activity_id=activity_id))
    return redirect(url_for('main.dashboard'))


@subtitles_bp.route('/reset_selection/<uuid:activity_id>', methods=['POST'])
@login_required
def reset_selection(activity_id):
    activity = UserActivity.query.filter_by(id=activity_id, user_id=current_user.id).first_or_404()
    # Find all selections for this user and activity
    selections_to_delete = UserSubtitleSelection.query.filter_by(
        user_id=current_user.id,
        content_id=activity.content_id,
        video_hash=activity.video_hash
    ).all() # Use .all() to get all matching records

    if selections_to_delete:
        try:
            for selection in selections_to_delete:
                db.session.delete(selection)
            db.session.commit()
            flash('All subtitle selections for this content have been reset.', 'success')
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error resetting selections: {e}", exc_info=True)
            flash('Error resetting selections.', 'danger')
    else:
        flash('No selections to reset for this content.', 'info')
    return redirect(url_for('content.content_detail', activity_id=activity_id))


@subtitles_bp.route('/delete_subtitle/<uuid:subtitle_id>', methods=['POST'])
@login_required
def delete_subtitle(subtitle_id):
    activity_id = request.form.get('activity_id')  # For redirect
    subtitle = Subtitle.query.get_or_404(subtitle_id)

    if subtitle.uploader_id != current_user.id and not current_user.has_role('Admin'):
        flash('You do not have permission to delete this subtitle.', 'danger')
        return redirect(request.referrer or url_for('main.dashboard'))

    try:
        # Delete associated selections that point to this specific subtitle ID
        UserSubtitleSelection.query.filter_by(selected_subtitle_id=subtitle.id).delete()
        # Delete associated votes
        SubtitleVote.query.filter_by(subtitle_id=subtitle.id).delete()

        # Delete file from storage if it's a community upload with a file_path
        # AND no other subtitles are using the same file_path
        if subtitle.source_type == 'community' and subtitle.file_path:
            # Check if any other subtitle uses this file_path
            other_subtitles_using_file = Subtitle.query.filter(
                Subtitle.file_path == subtitle.file_path,
                Subtitle.id != subtitle.id  # Exclude the current subtitle being deleted
            ).first()

            if not other_subtitles_using_file:
                # No other subtitles use this file_path, safe to delete the file
                if current_app.config['STORAGE_BACKEND'] == 'cloudinary':
                    if CLOUDINARY_AVAILABLE and cloudinary.config().api_key:
                        try:
                            cloudinary.uploader.destroy(subtitle.file_path, resource_type="raw")
                            current_app.logger.info(f"Deleted Cloudinary resource: {subtitle.file_path}")
                        except Exception as e:
                            current_app.logger.error(f"Error deleting Cloudinary resource {subtitle.file_path}: {e}")
                else:  # Local storage
                    local_file_full_path = os.path.join(current_app.config['UPLOAD_FOLDER'], subtitle.file_path)
                    if os.path.exists(local_file_full_path):
                        try:
                            os.remove(local_file_full_path)
                            current_app.logger.info(f"Deleted local file: {local_file_full_path}")
                        except Exception as e:
                            current_app.logger.error(f"Error deleting local file {local_file_full_path}: {e}")
            else:
                current_app.logger.info(f"File {subtitle.file_path} not deleted as it's still used by other subtitles.")

        db.session.delete(subtitle)
        db.session.commit()
        flash('Subtitle deleted successfully.', 'success')
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error deleting subtitle {subtitle_id}: {e}", exc_info=True)
        flash('Error deleting subtitle.', 'danger')

    if activity_id: return redirect(url_for('content.content_detail', activity_id=activity_id))
    return redirect(url_for('main.dashboard'))


@subtitles_bp.route('/download_subtitle/<uuid:subtitle_id>')
@login_required
def download_subtitle(subtitle_id):
    from flask import send_file, abort
    if not current_user.has_role('Admin'):
        flash('You do not have permission to download subtitles.', 'danger')
        return redirect(url_for('main.dashboard'))

    subtitle = Subtitle.query.get_or_404(subtitle_id)
    content_id_display = subtitle.content_id.replace(':', '_')
    download_filename = f"{content_id_display}_{subtitle.language}_{str(subtitle.id)[:8]}.vtt"

    if subtitle.source_type == 'opensubtitles_community_link' and subtitle.source_metadata:
        os_file_id = subtitle.source_metadata.get('original_file_id')
        if not os_file_id:
            current_app.logger.error(f"Linked OS subtitle {subtitle.id} missing original_file_id for download.")
            abort(404)
        try:
            if not current_user.opensubtitles_active or not current_user.opensubtitles_token or not current_user.opensubtitles_base_url:
                flash(
                    "Admin's OpenSubtitles account is not configured/active; cannot download this OS-linked subtitle.",
                    "warning")
                return redirect(request.referrer or url_for('main.dashboard'))

            download_info = opensubtitles_client.request_download_link(
                file_id=os_file_id,
                user=current_user
            )
            if download_info and download_info.get('link'):
                os_subtitle_direct_url = download_info['link']
                remaining_downloads = download_info.get('remaining')
                if remaining_downloads is not None and int(remaining_downloads) <= 10:
                    current_app.logger.warning(
                        f"OpenSubtitles API downloads remaining for user {current_user.username}: {remaining_downloads}")

                current_app.logger.info(f"Serving OpenSubtitles direct url to omit 503 errors")

                return no_cache_redirect(os_subtitle_direct_url, code=302)
            else:
                flash("Could not retrieve download link from OpenSubtitles.", "danger")
                abort(500)
        except Exception as e:
            current_app.logger.error(f"Error downloading linked OpenSubtitle {os_file_id}: {e}", exc_info=True)
            abort(500)

    elif subtitle.file_path:  # Community subtitle (local or cloudinary)
        try:
            vtt_content = _get_vtt_content(subtitle)
            return Response(vtt_content, mimetype='text/vtt',
                            headers={"Content-Disposition": f"attachment;filename={download_filename}"})
        except Exception as e:
            current_app.logger.error(f"Error downloading subtitle file {subtitle.file_path}: {e}", exc_info=True)
            abort(500)
    else:
        current_app.logger.error(f"Subtitle {subtitle.id} has no file_path and is not a valid OS link.")
        abort(404)


@subtitles_bp.route('/mark_compatible_hash/<uuid:subtitle_id>', methods=['POST'])
@login_required
def mark_compatible_hash(subtitle_id):
    target_video_hash = request.form.get('target_video_hash')
    activity_id_str = request.form.get('activity_id')

    if not target_video_hash:
        flash('Target video hash is missing.', 'danger')
        return redirect(request.referrer or url_for('main.dashboard'))
    if not activity_id_str:
        flash('Activity ID is missing.', 'danger')
        return redirect(request.referrer or url_for('main.dashboard'))

    try:
        activity_id_uuid = uuid.UUID(activity_id_str)
    except ValueError:
        flash('Invalid Activity ID format.', 'danger')
        return redirect(request.referrer or url_for('main.dashboard'))

    original_subtitle = Subtitle.query.get_or_404(subtitle_id)
    activity = UserActivity.query.get_or_404(activity_id_uuid)

    if activity.content_id != original_subtitle.content_id:
        flash('Content ID mismatch between subtitle and activity.', 'danger')
        return redirect(url_for('content.content_detail', activity_id=activity.id))

    # Cannot mark an OpenSubtitles-linked entry as compatible for a *different* hash this way
    # This feature is for community uploads primarily.
    if original_subtitle.source_type == 'opensubtitles_community_link':
        flash('This operation is not applicable to OpenSubtitles-linked entries in this manner.', 'warning')
        return redirect(url_for('content.content_detail', activity_id=activity.id))
    if not original_subtitle.file_path:  # Should not happen for community subs
        flash('Original subtitle does not have a file path, cannot mark as compatible.', 'danger')
        return redirect(url_for('content.content_detail', activity_id=activity.id))

    existing_compatible_sub = Subtitle.query.filter_by(
        content_id=original_subtitle.content_id,
        language=original_subtitle.language,
        video_hash=target_video_hash,
        file_path=original_subtitle.file_path,  # Key: ensure it's the same underlying file
        source_type=original_subtitle.source_type  # And same source type
    ).first()

    newly_created_sub = None
    if existing_compatible_sub:
        newly_created_sub = existing_compatible_sub
        flash('A compatible subtitle entry for this hash already exists. Selecting it.', 'info')
    else:
        new_compatible_subtitle_entry = Subtitle(
            id=uuid.uuid4(),
            content_id=original_subtitle.content_id,
            content_type=original_subtitle.content_type,
            video_hash=target_video_hash,
            language=original_subtitle.language,
            file_path=original_subtitle.file_path,
            uploader_id=original_subtitle.uploader_id,
            upload_timestamp=datetime.datetime.utcnow(),
            votes=1,
            author=original_subtitle.author,
            version_info=original_subtitle.version_info,
            source_type=original_subtitle.source_type,  # Preserve source type
            source_metadata=original_subtitle.source_metadata  # Preserve metadata if any
        )
        db.session.add(new_compatible_subtitle_entry)
        newly_created_sub = new_compatible_subtitle_entry
        flash('Subtitle marked as compatible with the current video version.', 'success')

        # Add the initial vote
        initial_vote = SubtitleVote(
            user_id=current_user.id,
            subtitle_id=new_compatible_subtitle_entry.id,  # Will be set after flush if using UUID from Python
            vote_value=1
        )
        db.session.flush()

        initial_vote.subtitle_id = new_compatible_subtitle_entry.id
        db.session.add(initial_vote)

    # Update UserSubtitleSelection
    user_sel = UserSubtitleSelection.query.filter_by(user_id=current_user.id, content_id=activity.content_id,
                                                     video_hash=target_video_hash).first()
    if user_sel:
        user_sel.selected_subtitle_id = newly_created_sub.id
        user_sel.selected_external_file_id = None
        user_sel.external_details_json = None
        user_sel.timestamp = datetime.datetime.utcnow()
    else:
        user_sel = UserSubtitleSelection(user_id=current_user.id, content_id=activity.content_id,
                                         video_hash=target_video_hash, selected_subtitle_id=newly_created_sub.id)
        db.session.add(user_sel)

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error in mark_compatible_hash: {e}", exc_info=True)
        flash('An error occurred.', 'danger')

    return redirect(url_for('content.content_detail', activity_id=activity.id))
