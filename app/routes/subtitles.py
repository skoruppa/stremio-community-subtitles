import os
import datetime
import json
import base64
import tempfile
import requests  # For fetching from Cloudinary URL
from flask import Blueprint, url_for, Response, request, current_app
from flask_login import current_user, login_required
from sqlalchemy.orm import Session

try:
    import cloudinary
    import cloudinary.uploader
    import cloudinary.api

    CLOUDINARY_AVAILABLE = True
except ImportError:
    CLOUDINARY_AVAILABLE = False
from ..extensions import db
from ..models import User, Subtitle, UserActivity, UserSubtitleSelection
from .utils import respond_with
from urllib.parse import parse_qs, unquote

subtitles_bp = Blueprint('subtitles', __name__)


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

    # --- Parameter Extraction ---
    content_id = unquote(content_id)
    if "mal:" in content_id:
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

    preferred_lang = user.preferred_language
    current_app.logger.info(
        f"Subtitle request: User={user.username}, Lang={preferred_lang}, Content={content_type}/{content_id}, Hash={video_hash}, Size={video_size}, Filename={video_filename}")

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

        elif video_hash is None and video_size is None:
            existing_activity = UserActivity.query.filter_by(
                user_id=user.id,
                content_id=content_id,
                video_hash=None,
                video_size=None,
                video_filename=video_filename
            ).first()
            if existing_activity:
                existing_activity.timestamp = datetime.datetime.utcnow()
                # video_filename already matches, no need to update it
                current_app.logger.info(
                    f"Updated existing UserActivity ID {existing_activity.id} (match by filename, no hash/size) for user {user.id}, filename {video_filename}")
                activity_found_and_updated = True

        # If no existing activity was found and updated, create a new one
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

        # Limit UserActivity entries per user based on config
        max_activities = current_app.config.get('MAX_USER_ACTIVITIES', 15) # Fallback to 15 if not in config
        activity_count = UserActivity.query.filter_by(user_id=user.id).count()
        
        if activity_count > max_activities:
            num_to_delete = activity_count - max_activities
            # Ensure num_to_delete is at least 1 if we are over limit,

            current_persisted_count = UserActivity.query.filter_by(user_id=user.id).count()
            effective_count_after_commit = current_persisted_count
            if not activity_found_and_updated: # A new activity was added to the session
                effective_count_after_commit +=1
            
            if effective_count_after_commit > max_activities:
                num_to_delete = effective_count_after_commit - max_activities
                oldest_activities = UserActivity.query.filter_by(user_id=user.id).order_by(UserActivity.timestamp.asc()).limit(num_to_delete).all()
                for old_activity in oldest_activities:
                    db.session.delete(old_activity)
                    current_app.logger.info(f"Deleted oldest UserActivity ID {old_activity.id} for user {user.id} to maintain limit of {max_activities}.")
        
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Failed to log or update user activity for user {user.id}: {e}")

    # --- Generate Download Identifier (Encoded Context) ---
    download_context = {
        'content_type': content_type,
        'content_id': content_id,
        'lang': preferred_lang,  # Still include preferred lang for default lookup
        'v_hash': video_hash,
        'v_size': video_size,
        'v_fname': video_filename
    }
    try:
        context_json = json.dumps(download_context, separators=(',', ':'))
        # Ensure padding is handled correctly during encoding if needed by decoder later
        download_identifier = base64.urlsafe_b64encode(context_json.encode('utf-8')).decode('utf-8').rstrip(
            '=')  # Remove padding
    except Exception as e:
        current_app.logger.error(f"Failed to encode download context: {e}")
        return respond_with({'subtitles': []})

    # --- Build Response ---
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
            'lang': preferred_lang  # Display user's preferred lang in Stremio UI
        })
        current_app.logger.info(f"Generated download URL for context: {download_context}")
    except Exception as e:
        current_app.logger.error(f"Error generating download URL for identifier {download_identifier}: {e}")
        return respond_with({'subtitles': []})

    return respond_with({'subtitles': subtitles_list})


# Unified download route handling dynamic subtitle lookup and user overrides
@subtitles_bp.route('/<manifest_token>/download/<download_identifier>.vtt')
def unified_download(manifest_token: str, download_identifier: str):
    """
    Decodes the download_identifier to get context, checks for user selection override,
    finds the best subtitle based on context/override, and serves the VTT file or a message.
    """
    # Validate token
    user = User.get_by_manifest_token(manifest_token)
    if not user:
        current_app.logger.warning(f"Download request with invalid token: {manifest_token}")
        return Response(generate_vtt_message("Invalid Access Token"), status=403, mimetype='text/vtt')

    # Decode the identifier to get the context
    try:
        # Add padding back if removed during encoding
        padding_needed = len(download_identifier) % 4
        if padding_needed:
            download_identifier += '=' * (4 - padding_needed)
        context_json = base64.urlsafe_b64decode(download_identifier.encode('utf-8')).decode('utf-8')
        context = json.loads(context_json)
        content_id = context.get('content_id')
        preferred_lang = context.get('lang')  # User's preferred lang from initial request
        video_hash = context.get('v_hash')

        if not content_id:  # Lang might be missing if user selected different one
            raise ValueError("Missing content_id in decoded context")

    except Exception as e:
        current_app.logger.error(f"Failed to decode download identifier '{download_identifier}': {e}")
        return Response(generate_vtt_message("Invalid download link."), status=400, mimetype='text/vtt')

    # --- Subtitle Selection Logic ---
    found_subtitle = None
    message_key = None
    found_subtitle = None  # Initialize

    # --- Subtitle Selection Logic ---
    # This logic determines which subtitle (if any) should be served.
    # Priority: User Selection (hash-specific > general) > Default Logic (hash > no hash)

    # 1. Check User Selections
    user_selection_specific = None
    user_selection_general = None

    if video_hash:
        # If hash exists, check for a specific selection matching the hash
        user_selection_specific = UserSubtitleSelection.query.filter_by(
            user_id=user.id, content_id=content_id, video_hash=video_hash
        ).join(UserSubtitleSelection.selected_subtitle).first()
        if user_selection_specific and user_selection_specific.selected_subtitle:
            found_subtitle = user_selection_specific.selected_subtitle
            current_app.logger.info(
                f"Using user selection (specific hash): Subtitle ID {found_subtitle.id} for content {content_id}, hash {video_hash}")

    # Only check for general selection if NO specific selection was found AND video_hash is NULL
    if not found_subtitle and not video_hash:
        user_selection_general = UserSubtitleSelection.query.filter_by(
            user_id=user.id, content_id=content_id, video_hash=None
        ).join(UserSubtitleSelection.selected_subtitle).first()
        if user_selection_general and user_selection_general.selected_subtitle:
            found_subtitle = user_selection_general.selected_subtitle
            current_app.logger.info(
                f"Using user selection (general content): Subtitle ID {found_subtitle.id} for content {content_id}")

    # 2. If NO applicable user selection was found, proceed to default lookup logic
    if not found_subtitle:
        current_app.logger.info(
            f"No applicable user selection found for content {content_id}, proceeding to default lookup.")
        # Default lookup logic starts here
        if preferred_lang:  # Proceed only if preferred language is known
            # Base query for default lookup (content_id and preferred_lang)
            base_query = Subtitle.query.filter_by(content_id=content_id, language=preferred_lang)

            if video_hash:
                # Try hash match first (within preferred lang)
                found_subtitle = base_query.filter_by(video_hash=video_hash).order_by(Subtitle.votes.desc()).first()
                if not found_subtitle:
                    # No hash match in preferred lang, check if *any* subs exist in preferred lang
                    subs_exist_count = base_query.count()
                    if subs_exist_count == 0:
                        message_key = 'no_subs_found'  # No subs for this lang at all
                    else:
                        # Subs exist for this lang, but not this hash. User must select via web.
                        message_key = 'select_web'
            else:
                # No video hash provided in context
                # Check for subs without hash in preferred lang
                subs_without_hash = base_query.filter(Subtitle.video_hash == None).order_by(
                    Subtitle.votes.desc()).first()
                if subs_without_hash:
                    # Found a hashless sub in preferred lang, but user needs to select it
                    message_key = 'no_hash_select_web'
                else:
                    # No hashless subs in preferred lang. Check if *any* subs exist in preferred lang.
                    subs_exist_count = base_query.count()
                    if subs_exist_count == 0:
                        message_key = 'no_subs_found'
                    else:
                        # Subs exist, but they have hashes. User needs to select.
                        message_key = 'no_hash_select_web'
        else:
            # Preferred language was missing in context - cannot perform default lookup reliably
            current_app.logger.warning(f"Cannot perform default lookup without preferred language for {content_id}")
            message_key = 'select_web'  # Fallback message

    # --- Serve Content ---
    if found_subtitle:
        # --- Serve Real Subtitle (Assume VTT) ---
        subtitle_id = found_subtitle.id
        db_file_path = found_subtitle.file_path
        current_app.logger.info(f"Serving subtitle ID {subtitle_id} (DB Path: {db_file_path})")

        if not db_file_path:
            current_app.logger.error(f"File path missing in DB for Subtitle ID: {subtitle_id}")
            return Response(generate_vtt_message(f"Subtitle file path error (ID: {subtitle_id})."), status=500,
                            mimetype='text/vtt')

        try:
            vtt_content = None
            if current_app.config['STORAGE_BACKEND'] == 'cloudinary':
                if not CLOUDINARY_AVAILABLE or not cloudinary.config().api_key:
                    current_app.logger.error(
                        f"Cloudinary not available/configured for serving subtitle ID {subtitle_id} (Public ID: {db_file_path})")
                    return Response(generate_vtt_message("Server error: Subtitle storage not configured."), status=500,
                                    mimetype='text/vtt')

                try:
                    # Get resource details to ensure it exists and get a secure URL
                    # For raw files, ensure resource_type="raw" and secure=True for https
                    generated_url_info = cloudinary.utils.cloudinary_url(
                        db_file_path,
                        resource_type="raw",
                        secure=True  # Ensure HTTPS
                    )
                    cloudinary_url = generated_url_info[0] if isinstance(generated_url_info,
                                                                         tuple) else generated_url_info

                    if not cloudinary_url:
                        current_app.logger.error(
                            f"Could not generate Cloudinary URL for public_id: {db_file_path} using cloudinary.utils.cloudinary_url")
                        raise Exception("Cloudinary URL generation failed")

                    current_app.logger.info(f"Fetching VTT from Cloudinary URL (generated by SDK): {cloudinary_url}")
                    r = requests.get(cloudinary_url, timeout=10)  # 10 second timeout
                    r.raise_for_status()  # Raises an HTTPError for bad responses (4XX or 5XX)
                    vtt_content = r.text  # Assuming UTF-8 encoding from Cloudinary for VTT
                except cloudinary.exceptions.NotFound:
                    current_app.logger.error(f"Cloudinary resource not found: {db_file_path}")
                    return Response(generate_vtt_message(f"Subtitle file missing (ID: {subtitle_id})."), status=404,
                                    mimetype='text/vtt')
                except requests.exceptions.RequestException as req_e:
                    current_app.logger.error(f"Error fetching subtitle from Cloudinary URL {cloudinary_url}: {req_e}")
                    return Response(generate_vtt_message(f"Error fetching subtitle (ID: {subtitle_id})."), status=500,
                                    mimetype='text/vtt')
                except Exception as e_cld:
                    current_app.logger.error(
                        f"General error with Cloudinary for subtitle ID {subtitle_id} (Public ID: {db_file_path}): {e_cld}")
                    return Response(generate_vtt_message(f"Error accessing subtitle (ID: {subtitle_id})."), status=500,
                                    mimetype='text/vtt')

            else:
                local_full_path = os.path.join(current_app.config['UPLOAD_FOLDER'], db_file_path)
                if not os.path.exists(local_full_path):
                    current_app.logger.error(f"Local subtitle file not found: {local_full_path} for ID: {subtitle_id}")
                    return Response(generate_vtt_message(f"Subtitle file missing (ID: {subtitle_id})."), status=404,
                                    mimetype='text/vtt')

                with open(local_full_path, 'r', encoding='utf-8') as f:
                    vtt_content = f.read()

            if not vtt_content:
                current_app.logger.error(
                    f"VTT content is empty after attempting to fetch for subtitle ID {subtitle_id}")
                return Response(generate_vtt_message(f"Error reading subtitle (ID: {subtitle_id})."), status=500,
                                mimetype='text/vtt')

            if not vtt_content.strip().startswith("WEBVTT"):
                current_app.logger.error(
                    f"File content does not look like VTT for subtitle ID {subtitle_id}. Path/ID: {db_file_path}")
                # Do not raise ValueError here, serve a message instead or allow it.
                # For now, let's serve it but log an error. A stricter validation might be needed.
                return Response(generate_vtt_message(f"Invalid VTT format (ID: {subtitle_id})."), status=500, mimetype='text/vtt')

            return Response(vtt_content, mimetype='text/vtt')

        except FileNotFoundError:
            current_app.logger.error(
                f"Local subtitle file disappeared after check: {db_file_path} for ID: {subtitle_id}")
            return Response(generate_vtt_message(f"Subtitle file missing (ID: {subtitle_id})."), status=404,
                            mimetype='text/vtt')
        except Exception as e:
            current_app.logger.error(
                f"Generic error reading/serving subtitle ID {subtitle_id} (Path/ID: {db_file_path}): {e}",
                exc_info=True)
            return Response(generate_vtt_message(f"Error reading subtitle file (ID: {subtitle_id})."), status=500,
                            mimetype='text/vtt')

    else:
        # --- Serve Placeholder Message ---
        # Determine final message key if not set by default logic (e.g., user selection failed)
        if not message_key:
            message_key = 'select_web'  # Default fallback message

        messages = {
            'no_subs_found': "No Subtitles Found: Upload them through the web interface.",
            'no_hash_select_web': "Video hash not present or mismatch: Please select subtitles from the web interface.",
            'select_web': "No automatic match found. Please select subtitles from the web interface.",
        }
        message_text = messages.get(message_key, "An error occurred or subtitles need selection.")
        current_app.logger.info(f"Serving message key '{message_key}' for decoded context.")
        vtt_content = generate_vtt_message(message_text)
        return Response(vtt_content, mimetype='text/vtt')


@subtitles_bp.route('/content/<uuid:activity_id>/upload', methods=['GET', 'POST'])
@login_required
def upload_subtitle(activity_id):
    """Handle subtitle upload from the web interface."""
    from flask import render_template, redirect, url_for, flash
    from ..forms import SubtitleUploadForm
    from ..languages import LANGUAGES
    from ..lib.metadata import get_metadata
    import uuid

    # Fetch the activity
    activity = UserActivity.query.filter_by(id=activity_id, user_id=current_user.id).first_or_404()

    # Parse season/episode if applicable
    season = None
    episode = None
    if activity.content_type == 'series':
        content_parts = activity.content_id.split(':')
        try:
            if len(content_parts) == 3:  # Format ttID:S:E
                season = int(content_parts[1])
                episode = int(content_parts[2])
            elif len(content_parts) == 2:  # Format ttID:E (assume Season 1)
                season = 1
                episode = int(content_parts[1])
        except ValueError:
            current_app.logger.warning(f"Could not parse season/episode from content_id: {activity.content_id}")

    # Get metadata
    metadata = get_metadata(activity.content_id, activity.content_type)

    # Create form
    form = SubtitleUploadForm()
    form.language.choices = LANGUAGES

    # Set default language to user's preferred language
    if request.method == 'GET':
        form.language.data = current_user.preferred_language

    # Handle form submission
    if form.validate_on_submit():
        try:
            # Process the uploaded file
            subtitle_file = form.subtitle_file.data
            original_filename = subtitle_file.filename
            file_extension = os.path.splitext(original_filename)[1].lower()

            # Get encoding and fps from form
            encoding = form.encoding.data
            fps = form.fps.data

            # If encoding is 'auto', set to None to use auto-detection
            if encoding.lower() == 'auto':
                encoding = None

            # Convert empty fps to None
            if not fps:
                fps = None
            else:
                try:
                    fps = float(fps)
                except ValueError:
                    fps = None

            # Generate unique filename for the VTT file
            base_vtt_filename = f"{uuid.uuid4()}.vtt"  # Used for both local and Cloudinary base name
            content_id_safe_path = activity.content_id.replace(':', '_')  # Used for local folder and Cloudinary folder

            # Save the original file to a temporary location
            with tempfile.NamedTemporaryFile(delete=False, suffix=file_extension) as temp_file:
                subtitle_file.save(temp_file.name)
                temp_file_path = temp_file.name

            db_file_path = None  # This will store the local relative path or Cloudinary public_id

            try:
                # Read the file data
                with open(temp_file_path, 'rb') as f:
                    file_data = f.read()

                # Convert to VTT format
                from ..lib.subtitles import convert_to_vtt
                vtt_content = convert_to_vtt(file_data, file_extension, encoding=encoding, fps=fps)
                current_app.logger.info(f"Successfully converted '{original_filename}' to VTT format in memory.")

                if current_app.config['STORAGE_BACKEND'] == 'cloudinary':
                    if not CLOUDINARY_AVAILABLE:
                        current_app.logger.error(
                            "Cloudinary storage configured but library not available or not configured.")
                        flash('Server error: Cloudinary storage is not properly configured.', 'danger')
                        return redirect(url_for('main.content_detail', activity_id=activity_id))
                    if not cloudinary.config().api_key:  # Check if cloudinary is configured
                        current_app.logger.error("Cloudinary SDK not configured (missing credentials).")
                        flash('Server error: Cloudinary storage is not properly configured.', 'danger')
                        return redirect(url_for('main.content_detail', activity_id=activity_id))

                    # Construct a unique public_id for Cloudinary
                    # Format: <CLOUDINARY_SUBTITLES_FOLDER>/<content_id_safe_path>/<base_vtt_filename_without_ext>
                    cloudinary_folder = current_app.config.get('CLOUDINARY_SUBTITLES_FOLDER', 'community_subtitles')
                    cloudinary_public_id = f"{cloudinary_folder}/{content_id_safe_path}/{base_vtt_filename.replace('.vtt', '')}"

                    current_app.logger.info(
                        f"Attempting to upload to Cloudinary with public_id: {cloudinary_public_id}")
                    upload_result = cloudinary.uploader.upload(
                        vtt_content.encode('utf-8'),  # Cloudinary expects bytes or a file path for raw uploads
                        public_id=cloudinary_public_id,
                        resource_type="raw",  # For VTT files, 'raw' is appropriate
                        overwrite=True  # Overwrite if a file with the same public_id exists
                    )
                    db_file_path = upload_result.get('public_id')  # Store public_id
                    if not db_file_path:
                        raise Exception(f"Cloudinary upload failed, no public_id returned. Result: {upload_result}")
                    current_app.logger.info(
                        f"Uploaded '{original_filename}' to Cloudinary. Public ID: {db_file_path}, URL: {upload_result.get('secure_url')}")

                else:  # Local storage (default)
                    # Create directory if it doesn't exist
                    local_content_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], content_id_safe_path)
                    os.makedirs(local_content_dir, exist_ok=True)

                    local_vtt_file_path_full = os.path.join(local_content_dir, base_vtt_filename)

                    # Save the VTT content to the final local location
                    with open(local_vtt_file_path_full, 'w', encoding='utf-8') as f:
                        f.write(vtt_content)
                    # Store relative path for DB: <content_id_safe_path>/<base_vtt_filename>
                    db_file_path = os.path.join(content_id_safe_path, base_vtt_filename)
                    current_app.logger.info(f"Saved '{original_filename}' to local storage: {local_vtt_file_path_full}")

            except Exception as e:
                current_app.logger.error(f"Error processing or uploading subtitle file '{original_filename}': {e}",
                                         exc_info=True)
                flash(f'Error processing or uploading subtitle file: {str(e)}', 'danger')
                return redirect(url_for('main.content_detail', activity_id=activity_id))
            finally:
                # Clean up the temporary file
                if os.path.exists(temp_file_path):
                    os.unlink(temp_file_path)

            if not db_file_path:
                current_app.logger.error("db_file_path was not set after storage attempt. This should not happen.")
                flash('Internal server error: Subtitle storage path could not be determined.', 'danger')
                return redirect(url_for('main.content_detail', activity_id=activity_id))

            # Create subtitle record in database
            subtitle = Subtitle(
                id=uuid.uuid4(),
                content_id=activity.content_id,
                content_type=activity.content_type,
                language=form.language.data,
                uploader_id=current_user.id,
                video_hash=activity.video_hash,
                file_path=db_file_path,  # This is now either local relative path or Cloudinary public_id
                version_info=form.version_info.data if hasattr(form,
                                                               'version_info') and form.version_info.data else None,
                author=form.author.data if hasattr(form, 'author') and form.author.data else None
            )

            db.session.add(subtitle)
            db.session.commit()  # Commit the subtitle first

            # Now, automatically select this subtitle for the user
            try:
                existing_selection = UserSubtitleSelection.query.filter_by(
                    user_id=current_user.id,
                    content_id=activity.content_id,
                    video_hash=activity.video_hash  # Use the hash from the activity context
                ).first()

                if existing_selection:
                    # Update existing selection
                    existing_selection.selected_subtitle_id = subtitle.id
                    current_app.logger.info(
                        f"Updated UserSubtitleSelection for user {current_user.id}, content {activity.content_id}, hash {activity.video_hash} to subtitle {subtitle.id}")
                else:
                    # Create new selection
                    new_selection = UserSubtitleSelection(
                        user_id=current_user.id,
                        content_id=activity.content_id,
                        video_hash=activity.video_hash,  # Use the hash from the activity context
                        selected_subtitle_id=subtitle.id
                    )
                    db.session.add(new_selection)
                    current_app.logger.info(
                        f"Created UserSubtitleSelection for user {current_user.id}, content {activity.content_id}, hash {activity.video_hash} for subtitle {subtitle.id}")

                db.session.commit()  # Commit the selection change
                flash('Subtitle uploaded and selected successfully!', 'success')

            except Exception as sel_e:
                db.session.rollback()
                current_app.logger.error(f"Error setting UserSubtitleSelection after upload: {sel_e}")
                # Subtitle was uploaded, but selection failed. Inform user.
                flash('Subtitle uploaded, but failed to automatically select it.', 'warning')

            return redirect(url_for('main.content_detail', activity_id=activity_id))

        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error uploading subtitle: {e}")
            flash('Error uploading subtitle. Please try again.', 'danger')

    return render_template('main/upload_subtitle.html',
                           form=form,
                           activity=activity,
                           metadata=metadata,
                           season=season,
                           episode=episode)


@subtitles_bp.route('/select_subtitle/<uuid:activity_id>/<uuid:subtitle_id>', methods=['POST'])
@login_required
def select_subtitle(activity_id, subtitle_id):
    """Handle subtitle selection from the web interface."""
    from flask import redirect, url_for, flash
    from ..models import UserSubtitleSelection, Subtitle, UserActivity
    import uuid

    try:
        # Check if subtitle exists
        subtitle = Subtitle.query.get_or_404(subtitle_id)

        # Get user selection for this subtitle's content
        user_selection = UserSubtitleSelection.query.filter_by(
            user_id=current_user.id,
            content_id=subtitle.content_id,
            selected_subtitle_id=subtitle_id
        ).first()

        # Check if this is an active subtitle (either user selected or auto selected)
        active_subtitle = None
        if activity_id:
            activity = UserActivity.query.get(activity_id)
            if activity:
                # Get the active subtitle for this activity
                active_selection = UserSubtitleSelection.query.filter_by(
                    user_id=current_user.id,
                    content_id=activity.content_id,
                    video_hash=activity.video_hash
                ).first()
                if active_selection:
                    active_subtitle = active_selection.selected_subtitle

        # Check if user has permission to vote on this subtitle
        if not current_user.has_role('Admin') and not user_selection and not (
                active_subtitle and active_subtitle.id == subtitle_id):
            flash('You can only vote on active subtitles.', 'warning')
            if activity_id:
                return redirect(url_for('main.content_detail', activity_id=activity_id))
            else:
                return redirect(url_for('main.dashboard'))

        # Get the activity
        activity = UserActivity.query.get_or_404(activity_id)

        # Check if user already has a selection for this content and hash
        existing_selection = UserSubtitleSelection.query.filter_by(
            user_id=current_user.id,
            content_id=activity.content_id,
            video_hash=activity.video_hash
        ).first()

        if existing_selection:
            # Update existing selection
            existing_selection.selected_subtitle_id = subtitle_id
            flash('Your subtitle selection has been updated.', 'success')
        else:
            # Create new selection
            new_selection = UserSubtitleSelection(
                user_id=current_user.id,
                content_id=activity.content_id,
                video_hash=activity.video_hash,
                selected_subtitle_id=subtitle_id
            )
            db.session.add(new_selection)
            flash('Your subtitle selection has been saved.', 'success')

        db.session.commit()
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error selecting subtitle: {e}")
        flash('Error selecting subtitle. Please try again.', 'danger')

    return redirect(url_for('main.content_detail', activity_id=activity_id))


@subtitles_bp.route('/vote/<uuid:subtitle_id>/<vote_type>', methods=['POST'])
@login_required
def vote_subtitle(subtitle_id, vote_type):
    """Handle subtitle voting from the web interface."""
    from flask import redirect, url_for, request, flash
    from ..models import SubtitleVote, Subtitle

    # Get activity_id from form data for redirect
    activity_id = request.form.get('activity_id')

    # Validate vote_type
    if vote_type not in ['up', 'down']:
        flash('Invalid vote type.', 'danger')
        if activity_id:
            return redirect(url_for('main.content_detail', activity_id=activity_id))
        else:
            return redirect(url_for('main.dashboard'))

    # Convert vote_type to value
    vote_value = 1 if vote_type == 'up' else -1

    try:
        # Check if subtitle exists
        subtitle = Subtitle.query.get_or_404(subtitle_id)

        # Check if user has already voted on this subtitle
        existing_vote = SubtitleVote.query.filter_by(
            user_id=current_user.id,
            subtitle_id=subtitle_id
        ).first()

        if existing_vote:
            # If user is trying to vote the same way again, remove the vote
            if existing_vote.vote_value == vote_value:
                # Update subtitle votes count
                subtitle.votes -= existing_vote.vote_value
                # Delete the vote
                db.session.delete(existing_vote)
                flash('Your vote has been removed.', 'info')
            else:
                # User is changing their vote
                # Update subtitle votes count
                subtitle.votes = subtitle.votes - existing_vote.vote_value + vote_value
                # Update the vote
                existing_vote.vote_value = vote_value
                flash('Your vote has been updated.', 'success')
        else:
            # Create new vote
            new_vote = SubtitleVote(
                user_id=current_user.id,
                subtitle_id=subtitle_id,
                vote_value=vote_value
            )
            db.session.add(new_vote)

            # Update subtitle votes count
            subtitle.votes += vote_value

            flash('Your vote has been recorded.', 'success')

        db.session.commit()
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error processing vote: {e}")
        flash('Error processing your vote. Please try again.', 'danger')

    # Redirect back to content detail page or dashboard
    if activity_id:
        return redirect(url_for('main.content_detail', activity_id=activity_id))
    else:
        return redirect(url_for('main.dashboard'))


@subtitles_bp.route('/reset_selection/<uuid:activity_id>', methods=['POST'])
@login_required
def reset_selection(activity_id):
    """Handle subtitle selection reset from the web interface."""
    from flask import redirect, url_for, flash
    from ..models import UserSubtitleSelection, UserActivity

    try:
        # Get the activity
        activity = UserActivity.query.get_or_404(activity_id)

        # Find user's selection for this content and hash
        selection = UserSubtitleSelection.query.filter_by(
            user_id=current_user.id,
            content_id=activity.content_id,
            video_hash=activity.video_hash
        ).first()

        if selection:
            # Delete the selection
            db.session.delete(selection)
            db.session.commit()
            flash('Your subtitle selection has been reset.', 'success')
        else:
            flash('No subtitle selection found to reset.', 'info')

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error resetting subtitle selection: {e}")
        flash('Error resetting subtitle selection. Please try again.', 'danger')

    return redirect(url_for('main.content_detail', activity_id=activity_id))


@subtitles_bp.route('/delete_subtitle/<uuid:subtitle_id>', methods=['POST'])
@login_required
def delete_subtitle(subtitle_id):
    """Handle subtitle deletion from the web interface."""
    from flask import redirect, url_for, request, flash, abort
    from ..models import Subtitle, UserSubtitleSelection, SubtitleVote
    import os

    # Get activity_id from form data for redirect
    activity_id = request.form.get('activity_id')

    try:
        # Find the subtitle
        subtitle = Subtitle.query.get_or_404(subtitle_id)

        # Check if user is the uploader or has admin role
        if subtitle.uploader_id != current_user.id and not current_user.has_role('Admin'):
            flash('You do not have permission to delete this subtitle.', 'danger')
            if activity_id:
                return redirect(url_for('main.content_detail', activity_id=activity_id))
            else:
                return redirect(url_for('main.dashboard'))

        # Delete associated selections
        selections = UserSubtitleSelection.query.filter_by(selected_subtitle_id=subtitle_id).all()
        for selection in selections:
            db.session.delete(selection)

        # Delete associated votes
        votes = SubtitleVote.query.filter_by(subtitle_id=subtitle_id).all()
        for vote in votes:
            db.session.delete(vote)

        # Delete the file from storage
        if subtitle.file_path:
            if current_app.config['STORAGE_BACKEND'] == 'cloudinary':
                if CLOUDINARY_AVAILABLE and cloudinary.config().api_key:
                    try:
                        # subtitle.file_path is the public_id
                        current_app.logger.info(
                            f"Attempting to delete Cloudinary resource: {subtitle.file_path} with resource_type='raw'")
                        cloudinary.uploader.destroy(subtitle.file_path, resource_type="raw")
                        current_app.logger.info(f"Successfully deleted Cloudinary resource: {subtitle.file_path}")
                    except cloudinary.exceptions.NotFound:
                        current_app.logger.warning(f"Cloudinary resource not found during delete: {subtitle.file_path}")
                    except Exception as e:
                        current_app.logger.error(f"Error deleting Cloudinary resource {subtitle.file_path}: {e}")
                        # Optionally, decide if this error should prevent DB deletion
                        # flash('Error deleting subtitle from cloud storage. Record kept for review.', 'warning')
                        # return redirect(request.referrer or url_for('main.dashboard'))
                else:
                    current_app.logger.error(
                        f"Cloudinary backend configured, but SDK not available/configured for deleting {subtitle.file_path}.")
            else:  # Local storage
                local_file_full_path = os.path.join(current_app.config['UPLOAD_FOLDER'], subtitle.file_path)
                if os.path.exists(local_file_full_path):
                    try:
                        os.remove(local_file_full_path)
                        current_app.logger.info(f"Successfully deleted local file: {local_file_full_path}")
                    except Exception as e:
                        current_app.logger.error(f"Error deleting local subtitle file {local_file_full_path}: {e}")
                else:
                    current_app.logger.warning(f"Local subtitle file not found for deletion: {local_file_full_path}")

        # Delete the subtitle record
        db.session.delete(subtitle)
        db.session.commit()

        flash('Subtitle has been deleted successfully.', 'success')
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error deleting subtitle: {e}")
        flash('Error deleting subtitle. Please try again.', 'danger')

    # Redirect back to content detail page or dashboard
    if activity_id:
        return redirect(url_for('main.content_detail', activity_id=activity_id))
    else:
        return redirect(url_for('main.dashboard'))


@subtitles_bp.route('/download_subtitle/<uuid:subtitle_id>')
@login_required
def download_subtitle(subtitle_id):
    """Download a subtitle file."""
    from flask import send_file, abort, flash, redirect, url_for, request
    from flask_login import login_required
    import uuid  # For new subtitle ID

    # Check if user has Admin role
    if not current_user.has_role('Admin'):
        flash('You do not have permission to download subtitles.', 'danger')
        return redirect(url_for('main.dashboard'))

    # Find the subtitle
    subtitle = Subtitle.query.get_or_404(subtitle_id)
    db_file_path = subtitle.file_path

    if not db_file_path:
        current_app.logger.error(f"File path missing in DB for Subtitle ID: {subtitle_id} (Admin Download)")
        flash('File path for subtitle is missing in the database.', 'danger')
        return redirect(request.referrer or url_for('main.dashboard'))

    content_id_display = subtitle.content_id.replace(':', '_')
    download_filename = f"{content_id_display}_{subtitle.language}_{subtitle_id}.vtt"

    current_app.logger.info(
        f"Admin {current_user.username} attempting to download subtitle ID {subtitle_id} (Path/ID: {db_file_path})")

    if current_app.config['STORAGE_BACKEND'] == 'cloudinary':
        if not CLOUDINARY_AVAILABLE or not cloudinary.config().api_key:
            current_app.logger.error(
                f"Cloudinary not available/configured for admin download of subtitle ID {subtitle_id}")
            flash('Cloudinary storage is not properly configured.', 'danger')
            return redirect(request.referrer or url_for('main.dashboard'))
        try:
            # db_file_path is the public_id
            generated_url_info = cloudinary.utils.cloudinary_url(
                db_file_path,
                resource_type="raw",
                secure=True
            )
            cloudinary_url = generated_url_info[0] if isinstance(generated_url_info, tuple) else generated_url_info

            if not cloudinary_url:
                current_app.logger.error(
                    f"Admin download: Could not generate Cloudinary URL for public_id: {db_file_path}")
                raise Exception("Cloudinary URL generation failed for admin download")

            current_app.logger.info(
                f"Admin download: Fetching VTT from Cloudinary URL (generated by SDK): {cloudinary_url}")
            r = requests.get(cloudinary_url, timeout=10, stream=True)
            r.raise_for_status()

            # Create a temporary file to stream the download
            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".vtt")
            for chunk in r.iter_content(chunk_size=8192):
                temp_file.write(chunk)
            temp_file.close()

            return send_file(
                temp_file.name,
                as_attachment=True,
                download_name=download_filename,
                mimetype='text/vtt'
            )
        except cloudinary.exceptions.NotFound:
            current_app.logger.error(f"Cloudinary resource not found for admin download: {db_file_path}")
            flash(f"Subtitle file not found in Cloudinary (ID: {subtitle_id}).", 'danger')
            return redirect(request.referrer or url_for('main.dashboard'))
        except requests.exceptions.RequestException as req_e:
            current_app.logger.error(
                f"Error fetching subtitle from Cloudinary for admin download (URL {cloudinary_url}): {req_e}")
            flash(f"Error fetching subtitle from Cloudinary (ID: {subtitle_id}).", 'danger')
            return redirect(request.referrer or url_for('main.dashboard'))
        except Exception as e:
            current_app.logger.error(
                f"General error during Cloudinary admin download for subtitle ID {subtitle_id}: {e}", exc_info=True)
            flash('An unexpected error occurred while trying to download the subtitle from cloud storage.', 'danger')
            return redirect(request.referrer or url_for('main.dashboard'))
        finally:
            if 'temp_file' in locals() and os.path.exists(temp_file.name):
                os.unlink(temp_file.name)  # Ensure temp file is cleaned up

    else:  # Local storage
        local_full_path = os.path.join(current_app.config['UPLOAD_FOLDER'], db_file_path)
        if not os.path.exists(local_full_path):
            current_app.logger.error(
                f"Local subtitle file not found for admin download: {local_full_path} (ID: {subtitle_id})")
            flash(f"Subtitle file not found locally (ID: {subtitle_id}).", 'danger')
            return redirect(request.referrer or url_for('main.dashboard'))

        current_app.logger.info(
            f"Admin {current_user.username} downloading local subtitle ID {subtitle_id} from {local_full_path}")
        return send_file(
            local_full_path,
            as_attachment=True,
            download_name=download_filename,
            mimetype='text/vtt'
        )


@subtitles_bp.route('/mark_compatible_hash/<uuid:subtitle_id>', methods=['POST'])
@login_required
def mark_compatible_hash(subtitle_id):
    """
    Marks an existing subtitle as compatible with a new video hash.
    This creates a new Subtitle entry pointing to the same file but with the new hash.
    """
    from flask import redirect, url_for, request, flash
    from ..models import Subtitle, UserSubtitleSelection
    import uuid

    target_video_hash = request.form.get('target_video_hash')
    activity_id_str = request.form.get('activity_id')  # This is UUID as string

    if not target_video_hash:
        flash('Target video hash is missing.', 'danger')
        return redirect(request.referrer or url_for('main.dashboard'))

    if not activity_id_str:
        flash('Activity ID is missing.', 'danger')
        return redirect(request.referrer or url_for('main.dashboard'))

    try:
        activity_id = uuid.UUID(activity_id_str)  # Convert string to UUID
    except ValueError:
        flash('Invalid Activity ID format.', 'danger')
        return redirect(request.referrer or url_for('main.dashboard'))

    original_subtitle = Subtitle.query.get_or_404(subtitle_id)
    activity = UserActivity.query.get_or_404(activity_id)

    # Ensure the activity's content_id matches the subtitle's content_id
    if activity.content_id != original_subtitle.content_id:
        flash('Content ID mismatch between subtitle and activity.', 'danger')
        return redirect(url_for('main.content_detail', activity_id=activity.id))

    # Check if a subtitle with this exact content_id, language, and target_video_hash already exists
    # and points to the same file_path. If so, just select it.
    existing_compatible_sub = Subtitle.query.filter_by(
        content_id=original_subtitle.content_id,
        language=original_subtitle.language,
        video_hash=target_video_hash,
        file_path=original_subtitle.file_path
    ).first()

    if existing_compatible_sub:
        new_subtitle_to_select = existing_compatible_sub
        flash('A compatible subtitle entry for this hash already exists. Selecting it.', 'info')
    else:
        # Create a new Subtitle entry for the target_video_hash
        new_compatible_subtitle = Subtitle(
            id=uuid.uuid4(),
            content_id=original_subtitle.content_id,
            content_type=original_subtitle.content_type,
            video_hash=target_video_hash,  # The new hash
            language=original_subtitle.language,
            file_path=original_subtitle.file_path,  # Points to the same physical file
            uploader_id=original_subtitle.uploader_id,  # Keep original uploader
            upload_timestamp=datetime.datetime.utcnow(),  # New timestamp for this "compatibility entry"
            votes=0,  # Starts with 0 votes, or 1 if we want to auto-upvote
            author=original_subtitle.author,
            version_info=original_subtitle.version_info
        )
        db.session.add(new_compatible_subtitle)
        new_subtitle_to_select = new_compatible_subtitle
        flash('Subtitle marked as compatible with the current video version.', 'success')

    # Update UserSubtitleSelection for the current user, content_id, and target_video_hash
    user_selection = UserSubtitleSelection.query.filter_by(
        user_id=current_user.id,
        content_id=activity.content_id,
        video_hash=target_video_hash  # Selection is for the new hash
    ).first()

    if user_selection:
        user_selection.selected_subtitle_id = new_subtitle_to_select.id
        user_selection.timestamp = datetime.datetime.utcnow()
    else:
        user_selection = UserSubtitleSelection(
            user_id=current_user.id,
            content_id=activity.content_id,
            video_hash=target_video_hash,
            selected_subtitle_id=new_subtitle_to_select.id
        )
        db.session.add(user_selection)

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error in mark_compatible_hash: {e}")
        flash('An error occurred while marking subtitle as compatible.', 'danger')

    return redirect(url_for('main.content_detail', activity_id=activity.id))
