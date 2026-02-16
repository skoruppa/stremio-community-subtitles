import os
import datetime
import json
import base64
import tempfile
import uuid
import gc
import asyncio
import aiohttp
from quart_babel import gettext as _
from quart import Blueprint, url_for, Response, request, current_app, flash, redirect, render_template, jsonify
from quart_auth import current_user, login_required
from sqlalchemy import select, delete as sql_delete, func
from sqlalchemy.orm import Session, joinedload
from iso639 import Lang

from ..forms import SubtitleUploadForm
from ..languages import LANGUAGES
from ..lib.metadata import get_metadata
from ..pagination import paginate_query

try:
    import cloudinary
    import cloudinary.uploader
    import cloudinary.api

    CLOUDINARY_AVAILABLE = True
except ImportError:
    CLOUDINARY_AVAILABLE = False
from ..extensions import async_session_maker
from ..models import User, Subtitle, UserActivity, UserSubtitleSelection, SubtitleVote  
from ..lib.subtitles import convert_to_vtt
from .utils import respond_with, get_active_subtitle_details, respond_with_no_cache, NoCacheResponse, no_cache_redirect, get_vtt_content, generate_vtt_message
from urllib.parse import parse_qs, unquote
import gzip
import io
import hashlib
import aiofiles

subtitles_bp = Blueprint('subtitles', __name__)


@subtitles_bp.route('/<manifest_token>/subtitles/<content_type>/<content_id>/<params>.json')
@subtitles_bp.route('/<manifest_token>/subtitles/<content_type>/<content_id>/<path:params>')
@subtitles_bp.route('/<manifest_token>/subtitles/<content_type>/<content_id>.json')
async def addon_stream(manifest_token: str, content_type: str, content_id: str, params: str = None):
    """
    Handles the subtitle request from Stremio using the user's manifest token.
    Generates an encoded identifier for the download URL.
    """
    # Find user by manifest token
    user = await User.get_by_manifest_token(manifest_token)
    if not user:
        current_app.logger.warning(f"Subtitle request with invalid token: {manifest_token}")
        return respond_with_no_cache({'subtitles': []})



    # --- Parameter Extraction ---
    content_id = unquote(content_id)


    try:
        param_string_to_parse = request.query_string.decode() if request.query_string else params
        parsed_params = {k: v[0] for k, v in parse_qs(param_string_to_parse).items() if v}
    except Exception as e:
        current_app.logger.error(f"Failed to parse params '{params}' or query string '{request.query_string}': {e}")
        parsed_params = {}

    video_hash = parsed_params.get('videoHash')
    video_size_str = parsed_params.get('videoSize')
    
    if video_size_str and video_size_str.endswith('.json'):
        video_size_str = video_size_str[:-5]
    
    video_filename = parsed_params.get('filename')

    if video_filename and video_filename.endswith(".docc"):
        current_app.logger.info(f"Ignoring as those are probably from the Docchi extension with hardcoded subs")
        return respond_with({'subtitles': []})

    video_size = None
    if video_size_str:
        try:
            video_size = int(video_size_str)
        except ValueError:
            current_app.logger.warning(f"Could not convert videoSize '{video_size_str}' to integer. URL: {request.url}")

    preferred_langs = user.preferred_languages
    current_app.logger.info(
        f"Subtitle request: User={user.username}, Lang={','.join(preferred_langs)}, Content={content_type}/{content_id}, Hash={video_hash}, Size={video_size}, Filename={video_filename}")

    # Log user activity
    async with async_session_maker() as session:
        try:
            activity_found_and_updated = False

            if video_hash is not None and video_size is not None:
                result = await session.execute(
                    select(UserActivity).filter_by(
                        user_id=user.id,
                        content_id=content_id,
                        video_hash=video_hash,
                        video_size=video_size
                    ).limit(1)
                )
                existing_activity = result.scalar_one_or_none()
                if existing_activity:
                    existing_activity.timestamp = datetime.datetime.utcnow()
                    if video_filename:
                        existing_activity.video_filename = video_filename
                    current_app.logger.info(
                        f"Updated existing UserActivity ID {existing_activity.id} (match by hash/size) for user {user.id}, hash {video_hash}, size {video_size}")
                    activity_found_and_updated = True

            elif video_hash is None:
                result = await session.execute(
                    select(UserActivity).filter_by(
                        user_id=user.id,
                        content_id=content_id,
                        video_hash=None,
                        video_size=video_size,
                        video_filename=video_filename
                    ).limit(1)
                )
                existing_activity = result.scalar_one_or_none()
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
                session.add(new_activity)
                current_app.logger.info(
                    f"Created new UserActivity for user {user.id}, content {content_id}, hash {video_hash}, size {video_size}, filename {video_filename}")

            max_activities = current_app.config.get('MAX_USER_ACTIVITIES', 15)+1

            count_result = await session.execute(
                select(func.count()).select_from(UserActivity).filter_by(user_id=user.id)
            )
            current_persisted_count = count_result.scalar()
            effective_count_after_commit = current_persisted_count
            if not activity_found_and_updated:
                effective_count_after_commit += 1

            if effective_count_after_commit > max_activities:
                num_to_delete = effective_count_after_commit - max_activities
                if num_to_delete > 0:
                    oldest_result = await session.execute(
                        select(UserActivity).filter_by(user_id=user.id).order_by(
                            UserActivity.timestamp.asc()).limit(num_to_delete)
                    )
                    oldest_activities = oldest_result.scalars().all()
                    for old_activity in oldest_activities:
                        await session.delete(old_activity)
                        current_app.logger.info(
                            f"Deleted oldest UserActivity ID {old_activity.id} for user {user.id} to maintain limit of {max_activities-1}.")

            await session.commit()
        except Exception as e:
            await session.rollback()
            current_app.logger.error(f"Failed to log or update user activity for user {user.id}: {e}", exc_info=True)

    # Parallel search for all languages
    async def process_language(preferred_lang):
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
            return None

        try:
            active_subtitle_info = await get_active_subtitle_details(user, content_id, video_hash, content_type, video_filename, preferred_lang)
            
            # Check if we should add subtitle entry
            has_subtitles = active_subtitle_info['type'] != 'none'
            if not has_subtitles and not user.show_no_subtitles:
                return []  # Skip this language if no subtitles and user doesn't want empty entries
            
            download_url = url_for('subtitles.unified_download',
                                   manifest_token=manifest_token,
                                   download_identifier=download_identifier,
                                   _external=True,
                                   _scheme=current_app.config['PREFERRED_URL_SCHEME'])
            stremio_sub_id = f"comm_{download_identifier}"
            
            vtt_entry = {
                'id': stremio_sub_id,
                'url': download_url,
                'lang': preferred_lang
            }
            
            entries = []
            add_ass_format = False
            
            if active_subtitle_info['type'] == 'local' and active_subtitle_info['subtitle']:
                active_sub = active_subtitle_info['subtitle']
                if active_sub.source_metadata and active_sub.source_metadata.get('original_format') in ['ass', 'ssa']:
                    add_ass_format = True
            else:
                # Provider subtitle - check if the active provider supports ASS
                provider_name = active_subtitle_info.get('provider_name')
                if provider_name:
                    try:
                        from ..providers.registry import ProviderRegistry
                        provider = ProviderRegistry.get(provider_name)
                        if provider and provider.can_return_ass:
                            provider_config = (user.provider_credentials or {}).get(provider_name, {})
                            if provider_config.get('try_provide_ass', False):
                                add_ass_format = True
                    except:
                        pass
            
            if add_ass_format:
                ass_download_url = download_url.replace('.vtt', '.ass')
                ass_entry = {
                    'id': f"{stremio_sub_id}_ass",
                    'url': ass_download_url,
                    'lang': preferred_lang
                }
                if user.prioritize_ass_subtitles:
                    entries.append(ass_entry)
                    entries.append(vtt_entry)
                else:
                    entries.append(vtt_entry)
                    entries.append(ass_entry)
                current_app.logger.info(f"Added ASS format subtitle for context: {download_context}")
            else:
                entries.append(vtt_entry)
            
            current_app.logger.info(f"Generated download URL for context: {download_context}")
            return entries
        except Exception as e:
            current_app.logger.error(f"Error generating download URL for identifier {download_identifier}: {e}")
            return []
    
    # Process all languages in parallel
    results = await asyncio.gather(*[process_language(lang) for lang in preferred_langs], return_exceptions=True)
    
    subtitles_list = []
    for result in results:
        if result and not isinstance(result, Exception):
            subtitles_list.extend(result)

    return respond_with_no_cache({'subtitles': subtitles_list})


@subtitles_bp.route('/<manifest_token>/download/<download_identifier>.ass')
@subtitles_bp.route('/<manifest_token>/download/<download_identifier>.vtt')
async def unified_download(manifest_token: str, download_identifier: str):
    user = await User.get_by_manifest_token(manifest_token)
    if not user:
        current_app.logger.warning(f"Download request with invalid token: {manifest_token}")
        return NoCacheResponse(generate_vtt_message("Invalid Access Token"), status=403, mimetype='text/vtt')

    # Check if ASS format is requested from request path
    is_ass_request = request.path.endswith('.ass')

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

        episode = None
        season = None

        if content_type == 'series' and ':' in content_id:
            parts = content_id.split(':')
            if content_id.startswith('kitsu:'):
                # Kitsu format: kitsu:11578:2 (episode only)
                try:
                    episode = int(parts[-1])
                except (ValueError, IndexError):
                    episode = None
            elif content_id.startswith('mal:'):
                # mal format: mal:59978:2 (episode only)
                try:
                    episode = int(parts[-1])
                except (ValueError, IndexError):
                    episode = None
            else:
                # IMDb format: tt0877057:2:1 (season:episode)
                try:
                    episode = int(parts[-1])
                except (ValueError, IndexError):
                    episode = None
                if len(parts) >= 3:
                    try:
                        season = int(parts[-2])
                    except ValueError:
                        season = None
        
        if not content_id:
            raise ValueError("Missing content_id in decoded context")
    except Exception as e:
        current_app.logger.error(f"Failed to decode download identifier '{download_identifier}': {e}")
        return NoCacheResponse(generate_vtt_message("Invalid download link."), status=400, mimetype='text/vtt')

    # Use the utility function to get active subtitle details (now with OpenSubtitles fallback)
    active_subtitle_info = await get_active_subtitle_details(user, content_id, video_hash, content_type, video_filename, lang, season, episode)

    local_subtitle_to_serve = None
    provider_subtitle_to_serve = None
    message_key = None
    failed_provider_name = None
    failed_provider_error = None
    vtt_content = None

    if active_subtitle_info['type'] == 'local':
        local_subtitle_to_serve = active_subtitle_info['subtitle']
        if local_subtitle_to_serve:
            current_app.logger.info(
                f"Serving active local subtitle ID {local_subtitle_to_serve.id}")
    elif active_subtitle_info['type'] and ('_selection' in active_subtitle_info['type'] or '_auto' in active_subtitle_info['type']):
        provider_name = active_subtitle_info.get('provider_name')
        subtitle_id = active_subtitle_info.get('provider_subtitle_id')
        
        if provider_name and subtitle_id:
            provider_subtitle_to_serve = {
                'provider': provider_name,
                'subtitle_id': subtitle_id,
                'metadata': active_subtitle_info.get('provider_metadata', {})
            }
            current_app.logger.info(
                f"Serving {provider_name} subtitle {subtitle_id} (type: {active_subtitle_info['type']})")
        else:
            current_app.logger.error(f"Provider subtitle missing provider_name or subtitle_id: {active_subtitle_info}")
            provider_subtitle_to_serve = None

    # Serve local subtitle
    if local_subtitle_to_serve:
        # Handle ASS format request
        if is_ass_request and local_subtitle_to_serve.source_metadata and local_subtitle_to_serve.source_metadata.get('original_format') in ['ass', 'ssa']:
            original_ass_path = local_subtitle_to_serve.source_metadata.get('original_file_path')
            if original_ass_path:
                current_app.logger.info(f"Serving original ASS/SSA file for subtitle ID {local_subtitle_to_serve.id}")
                try:
                    if current_app.config['STORAGE_BACKEND'] == 'cloudinary':
                        if not CLOUDINARY_AVAILABLE or not cloudinary.config().api_key:
                            raise Exception("Cloudinary not configured/available")
                        generated_url_info = cloudinary.utils.cloudinary_url(original_ass_path, resource_type="raw", secure=True)
                        cloudinary_url = generated_url_info[0] if isinstance(generated_url_info, tuple) else generated_url_info
                        if not cloudinary_url:
                            raise Exception("Cloudinary URL generation failed")
                        async with aiohttp.ClientSession() as session:
                            async with session.get(cloudinary_url, timeout=aiohttp.ClientTimeout(total=10)) as r:
                                r.raise_for_status()
                                ass_content = await r.text()
                    else:
                        local_full_path = os.path.join(current_app.config['UPLOAD_FOLDER'], original_ass_path)
                        if not os.path.exists(local_full_path):
                            raise FileNotFoundError("Local ASS file not found")
                        async with aiofiles.open(local_full_path, 'r', encoding='utf-8') as f:
                            ass_content = await f.read()
                    return NoCacheResponse(ass_content, mimetype='text/x-ssa')
                except Exception as e:
                    current_app.logger.error(f"Error reading ASS file for subtitle ID {local_subtitle_to_serve.id}: {e}", exc_info=True)
                    message_key = 'error'
            else:
                current_app.logger.error(f"ASS format requested but no original_file_path for subtitle ID {local_subtitle_to_serve.id}")
                message_key = 'error'
        # Handle provider community_link case
        elif local_subtitle_to_serve.source_type.endswith('_community_link') and \
                local_subtitle_to_serve.source_metadata and \
                local_subtitle_to_serve.source_metadata.get('provider_subtitle_id'):
            
            provider_name = local_subtitle_to_serve.source_metadata.get('provider')
            provider_subtitle_id = local_subtitle_to_serve.source_metadata.get('provider_subtitle_id')
            
            try:
                from ..providers.registry import ProviderRegistry
                provider = ProviderRegistry.get(provider_name)
                
                if provider and provider.is_authenticated(user):
                    provider_subtitle_to_serve = {
                        'provider': provider_name,
                        'subtitle_id': provider_subtitle_id,
                        'metadata': local_subtitle_to_serve.source_metadata
                    }
                    current_app.logger.info(
                        f"Identified linked {provider_name} subtitle (ID: {provider_subtitle_id}) via local Subtitle ID {local_subtitle_to_serve.id}")
                    local_subtitle_to_serve = None
                else:
                    current_app.logger.warning(
                        f"User has a linked {provider_name} subtitle but provider is not active")
                    message_key = 'provider_integration_inactive'
                    failed_provider_name = provider_name
                    local_subtitle_to_serve = None
            except Exception as e:
                current_app.logger.error(f"Error accessing provider {provider_name}: {e}")
                message_key = 'error'
                local_subtitle_to_serve = None

        elif local_subtitle_to_serve.file_path:  # Standard community-uploaded subtitle
            current_app.logger.info(f"Serving community subtitle ID {local_subtitle_to_serve.id}")
            try:
                vtt_content = await get_vtt_content(local_subtitle_to_serve)
            except Exception as e:
                current_app.logger.error(f"Error reading local subtitle ID {local_subtitle_to_serve.id}: {e}",
                                         exc_info=True)
                message_key = 'error'
        else:
            current_app.logger.error(
                f"Local subtitle ID {local_subtitle_to_serve.id} has no file_path")
            message_key = 'error'

    # Serve provider subtitle
    provider_subtitle_url = None
    if provider_subtitle_to_serve and not vtt_content:
        provider_name = provider_subtitle_to_serve.get('provider')
        subtitle_id = provider_subtitle_to_serve.get('subtitle_id')
        
        if subtitle_id:
            try:
                from ..providers.registry import ProviderRegistry
                from ..providers.base import ProviderDownloadError
                
                provider = ProviderRegistry.get(provider_name)
                if not provider or not provider.is_authenticated(user):
                    current_app.logger.warning(
                        f"Attempting to serve {provider_name} subtitle {subtitle_id}, but provider is not active")
                    message_key = 'provider_integration_inactive'
                    failed_provider_name = provider_name
                else:
                    current_app.logger.info(f"Attempting to serve {provider_name} subtitle: {subtitle_id}")
                    try:
                        provider_subtitle_url = await provider.get_download_url(user, subtitle_id)
                        
                        # If provider returns None, use download_subtitle() method directly
                        if provider_subtitle_url is None:
                            current_app.logger.info(f"{provider_name} requires direct download")
                            try:
                                zip_content = await provider.download_subtitle(user, subtitle_id)
                                from .utils import extract_subtitle_from_zip, process_subtitle_content
                                
                                subtitle_content, filename, extension = extract_subtitle_from_zip(zip_content, episode=episode)
                                del zip_content  # Free memory immediately
                                
                                processed = await process_subtitle_content(subtitle_content, extension)
                                del subtitle_content  # Free memory
                                
                                if is_ass_request and processed['original']:
                                    result = NoCacheResponse(processed['original'], mimetype='text/x-ssa')
                                    del processed
                                    gc.collect()
                                    return result
                                
                                vtt_content = processed['vtt']
                                del processed
                                gc.collect()
                            except ValueError as e:
                                if "No subtitle file found in" in str(e):
                                    current_app.logger.warning(f"{provider_name} archive contains no subtitle files (subtitle_id={subtitle_id}): {e}")
                                    message_key = 'provider_no_subtitle_in_archive'
                                    failed_provider_name = provider_name
                                else:
                                    current_app.logger.error(f"Error processing {provider_name} ZIP (subtitle_id={subtitle_id}): {e}", exc_info=True)
                                    message_key = 'error'
                                gc.collect()
                            except Exception as e:
                                current_app.logger.error(f"Error processing {provider_name} ZIP (subtitle_id={subtitle_id}): {e}", exc_info=True)
                                message_key = 'error'
                                gc.collect()
                        else:
                            current_app.logger.info(f"Got download URL from {provider_name}")
                    except ProviderDownloadError as e:
                        error_msg = str(e)
                        # Log as warning for client errors (4xx), error for server errors
                        if hasattr(e, 'status_code') and e.status_code and 400 <= e.status_code < 500:
                            current_app.logger.warning(f"{provider_name} API error: {error_msg}")
                        else:
                            current_app.logger.error(f"{provider_name} API error: {error_msg}")
                        
                        # Special handling for 401 Unauthorized
                        if hasattr(e, 'status_code') and e.status_code == 401:
                            message_key = 'provider_auth_expired'
                            failed_provider_name = provider_name
                        else:
                            message_key = 'provider_download_error'
                            failed_provider_name = provider_name
                            failed_provider_error = error_msg
                    except Exception as e:
                        error_msg = str(e)
                        current_app.logger.error(f"Unexpected error serving {provider_name} subtitle {subtitle_id}: {error_msg}",
                                                 exc_info=True)
                        message_key = 'provider_download_error'
                        failed_provider_name = provider_name
                        failed_provider_error = error_msg
            except Exception as e:
                current_app.logger.error(f"Error accessing provider registry: {e}", exc_info=True)
                message_key = 'error'

    if provider_subtitle_url:
        # Regular URL download
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(provider_subtitle_url, timeout=aiohttp.ClientTimeout(total=5)) as r:
                    r.raise_for_status()
                    
                    # Check if response is ZIP (SubDL returns ZIP files)
                    content_type = r.headers.get('Content-Type', '')
                    if 'zip' in content_type.lower() or provider_subtitle_url.endswith('.zip'):
                        from .utils import extract_subtitle_from_zip, process_subtitle_content
                        
                        try:
                            # Extract subtitle from ZIP
                            zip_data = await r.read()
                            current_app.logger.info(f"Downloaded ZIP from {provider_subtitle_url}, size={len(zip_data)}, first_bytes={zip_data[:20].hex() if len(zip_data) >= 20 else zip_data.hex()}")
                            subtitle_content, filename, extension = extract_subtitle_from_zip(zip_data, episode=episode)
                            del zip_data  # Free memory
                            
                            # Process subtitle (convert to VTT, handle ASS)
                            processed = await process_subtitle_content(subtitle_content, extension)
                            del subtitle_content  # Free memory
                            
                            # If ASS requested and available, serve original
                            if is_ass_request and processed['original']:
                                current_app.logger.info(f"Serving ASS format from provider ZIP")
                                result = NoCacheResponse(processed['original'], mimetype='text/x-ssa')
                                del processed
                                gc.collect()
                                return result
                            elif is_ass_request:
                                # ASS requested but not available - serve VTT instead
                                current_app.logger.info(f"ASS requested but not in ZIP, serving VTT")
                            
                            vtt_content = processed['vtt']
                            del processed
                            gc.collect()
                        except ValueError as e:
                            if "No subtitle file found in" in str(e):
                                current_app.logger.warning(f"Provider archive contains no subtitle files (url={provider_subtitle_url}): {e}")
                                message_key = 'provider_no_subtitle_in_archive'
                            else:
                                current_app.logger.error(f"Error processing ZIP subtitle (url={provider_subtitle_url}, content_type={content_type}, response_size={len(await r.read())}): {e}", exc_info=True)
                                message_key = 'error'
                            gc.collect()
                        except Exception as e:
                            current_app.logger.error(f"Error processing ZIP subtitle (url={provider_subtitle_url}, content_type={content_type}): {e}", exc_info=True)
                            message_key = 'error'
                            gc.collect()
                    else:
                        # Plain text subtitle (VTT/SRT)
                        if is_ass_request:
                            # ASS requested but provider returned plain text - serve as VTT
                            current_app.logger.info(f"ASS requested but provider returned plain text, serving as VTT")
                        vtt_content = await r.text()
        except asyncio.TimeoutError:
            current_app.logger.warning(f"Timeout fetching subtitle from {provider_subtitle_url}")
            message_key = 'provider_timeout'
        except aiohttp.ClientError as e:
            status_code = getattr(e, 'status', None)
            current_app.logger.warning(f"Error fetching subtitle from provider (url={provider_subtitle_url}, status={status_code}): {e}")
            message_key = 'provider_error'
        except Exception as e:
            current_app.logger.error(f"Unexpected error fetching subtitle: {e}")
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
        'provider_integration_inactive': f"SCS: {failed_provider_name or 'Provider'} is not connected. Please reconnect in account settings.",
        'provider_error': f"SCS: Error fetching from {failed_provider_name or 'provider'}. Please reconnect in account settings or try again later.",
        'provider_timeout': f"SCS: {failed_provider_name or 'Provider'} timeout. The service is slow or unavailable, try again later.",
        'provider_download_error': f"SCS: {failed_provider_name or 'Provider'} error: {failed_provider_error or 'Download failed'}.",
        'provider_no_subtitle_in_archive': f"SCS: {failed_provider_name or 'Provider'} archive does not contain any subtitle files.",
        'provider_auth_expired': f"SCS: {failed_provider_name or 'Provider'} authentication expired. Please log in again in account settings."
    }
    message_text = messages.get(message_key, "An error occurred or subtitles need selection.")
    current_app.logger.info(f"Serving placeholder message (key: '{message_key}', provider: '{failed_provider_name}') for context: {context}")
    return NoCacheResponse(generate_vtt_message(message_text), mimetype='text/vtt')


@subtitles_bp.route('/content/<uuid:activity_id>/upload', methods=['GET', 'POST'])
@subtitles_bp.route('/content/upload', methods=['GET', 'POST'])
@login_required
async def upload_subtitle(activity_id=None):
    """Handle subtitle upload from the web interface."""
    # Get user from database
    async with async_session_maker() as session:
        result = await session.execute(select(User).filter_by(id=current_user.auth_id))
        user = result.scalar_one_or_none()
    activity = None
    is_advanced_upload = activity_id is None

    # For regular upload (with activity_id)
    if not is_advanced_upload:
        async with async_session_maker() as session:
            result = await session.execute(
                select(UserActivity).filter_by(id=activity_id, user_id=current_user.auth_id)
            )
            activity = result.scalar_one_or_none()
            if not activity:
                from quart import abort
                abort(404)

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
        metadata = await get_metadata(content_id, content_type)
    except Exception as e:
        current_app.logger.warning(f"Could not fetch metadata for {content_id}: {e}")
        metadata = None

    form = await SubtitleUploadForm.create_form()
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
        if is_advanced_upload:
            prefill_content_id = request.args.get('content_id')
            if prefill_content_id:
                form.content_id.data = prefill_content_id
        
        # Set default language based on browser preference or first preferred language
        selected_language = None
        if user and user.preferred_languages:
            browser_prefs = request.accept_languages.values()
            for browser_pref in browser_prefs:
                try:
                    lang_code_browser = browser_pref.split('-')[0].strip()
                    lang_obj_browser = Lang(lang_code_browser)
                    # Check if browser's 3-letter code is in user's preferred languages
                    if lang_obj_browser.pt3 in user.preferred_languages:
                        selected_language = lang_obj_browser.pt3
                        break
                except KeyError:
                    current_app.logger.warning(f"iso639-lang could not convert browser lang code {browser_pref} to ISO 639-3.")
            
            if selected_language:
                form.language.data = selected_language
            else:
                form.language.data = user.preferred_languages[0] # Fallback to first preferred language
        else:
            form.language.data = 'eng' # Default to English if no preferred languages set

        if activity and activity.video_filename:
            form.version_info.data = activity.video_filename.rsplit('.', 1)[0]

    if await form.validate_on_submit():
        try:
            # For advanced upload, construct content_id from form data
            if is_advanced_upload:
                base_content_id = form.content_id.data.strip() if form.content_id.data else None
                content_type = form.content_type.data

                # Validate content_id format
                if not (base_content_id.startswith('tt') or base_content_id.startswith('kitsu:') or base_content_id.startswith('mal:')):
                    await flash(_('Content ID must be either IMDB ID (starting with "tt") or Kitsu ID (format "kitsu:12345") or MAL ID (format "mal:12345")'), 'danger')
                    return await render_template('main/upload_subtitle.html', form=form, activity=activity,
                                           metadata=metadata, season=season, episode=episode,
                                           is_advanced_upload=is_advanced_upload)

                if content_type == 'series':
                    season_num = form.season_number.data or 1
                    episode_num = form.episode_number.data

                    if not episode_num:
                        await flash(_('Episode number is required for series'), 'danger')
                        return await render_template('main/upload_subtitle.html', form=form, activity=activity,
                                               metadata=metadata, season=season, episode=episode,
                                               is_advanced_upload=is_advanced_upload)

                    # Construct content_id for series
                    if base_content_id.startswith('tt'):
                        content_id = f"{base_content_id}:{season_num}:{episode_num}"
                    else:  # mal/kitsu format
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
                await subtitle_file.save(temp_file.name)
                temp_file_path = temp_file.name

            db_file_path = None
            original_ass_file_path = None
            is_ass_format = file_extension in ['ass', 'ssa']
            
            try:
                with open(temp_file_path, 'rb') as f:
                    file_data = f.read()
                try:
                    vtt_content_data = await convert_to_vtt(file_data, file_extension, encoding=encoding, fps=fps)
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
                async with async_session_maker() as check_session:
                    check_result = await check_session.execute(
                        select(Subtitle).filter_by(
                            hash=vtt_hash,
                            language=form.language.data
                        ).limit(1)
                    )
                    existing_subtitle_same_hash = check_result.scalar_one_or_none()

                db_file_path = None
                skip_file_upload = False

                if existing_subtitle_same_hash:
                    if existing_subtitle_same_hash.video_hash == video_hash:
                        # Exact duplicate: same content, same video hash
                        await flash(_('These subtitles already exist for this content and video version.'), 'info')
                        redirect_url = url_for('subtitles.upload_subtitle') if is_advanced_upload else url_for(
                            'content.content_detail', activity_id=activity_id)
                        return redirect(redirect_url)
                    else:
                        # Same content, different video hash - reuse file_path
                        db_file_path = existing_subtitle_same_hash.file_path
                        skip_file_upload = True
                        current_app.logger.info(f"Reusing existing subtitle file_path: {db_file_path} for new video_hash.")
                
                # Save original ASS/SSA file if applicable
                if is_ass_format and not skip_file_upload:
                    base_ass_filename = f"{uuid.uuid4()}.{file_extension}"
                    if current_app.config['STORAGE_BACKEND'] == 'cloudinary':
                        cloudinary_folder = current_app.config.get('CLOUDINARY_SUBTITLES_FOLDER', 'community_subtitles')
                        cloudinary_public_id_ass = f"{cloudinary_folder}/{content_id_safe_path}/{base_ass_filename.replace(f'.{file_extension}', '')}"
                        upload_result_ass = cloudinary.uploader.upload(file_data, public_id=cloudinary_public_id_ass, resource_type="raw", overwrite=True)
                        original_ass_file_path = upload_result_ass.get('public_id')
                        current_app.logger.info(f"Uploaded original ASS/SSA to Cloudinary: {original_ass_file_path}")
                    else:
                        local_content_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], content_id_safe_path)
                        os.makedirs(local_content_dir, exist_ok=True)
                        local_ass_file_path_full = os.path.join(local_content_dir, base_ass_filename)
                        with open(local_ass_file_path_full, 'wb') as f:
                            f.write(file_data)
                        original_ass_file_path = os.path.join(content_id_safe_path, base_ass_filename)
                        current_app.logger.info(f"Saved original ASS/SSA to local storage: {local_ass_file_path_full}")
                
                if not skip_file_upload:
                    if current_app.config['STORAGE_BACKEND'] == 'cloudinary':
                        if not CLOUDINARY_AVAILABLE or not cloudinary.config().api_key:
                            await flash(_('Server error: Cloudinary storage is not properly configured.'), 'danger')
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
                # No db.session.rollback() needed here - no session yet
                current_app.logger.error(f"Error processing/uploading subtitle '{original_filename}': {e}",
                                         exc_info=True)
                await flash(_('Error processing/uploading subtitle: %(error)s', error=str(e)), 'danger')
                redirect_url = url_for('subtitles.upload_subtitle') if is_advanced_upload else url_for(
                    'content.content_detail', activity_id=activity_id)
                return redirect(redirect_url)
            finally:
                if os.path.exists(temp_file_path):
                    os.unlink(temp_file_path)

            if not db_file_path:
                await flash(_('Internal error: Subtitle path not determined.'), 'danger')
                redirect_url = url_for('subtitles.upload_subtitle') if is_advanced_upload else url_for(
                    'content.content_detail', activity_id=activity_id)
                return redirect(redirect_url)

            source_metadata = None
            if is_ass_format and original_ass_file_path:
                source_metadata = {
                    'original_format': file_extension,
                    'original_file_path': original_ass_file_path
                }
            
            new_subtitle = Subtitle(
                id=uuid.uuid4(),
                content_id=content_id,
                content_type=content_type,
                language=form.language.data,
                uploader_id=(current_user.auth_id),
                video_hash=video_hash,
                file_path=db_file_path,
                hash=vtt_hash,
                source_type='community',
                source_metadata=source_metadata,
                version_info=form.version_info.data if hasattr(form,
                                                               'version_info') and form.version_info.data else None,
                author=form.author.data if hasattr(form, 'author') and form.author.data else None
            )
            
            async with async_session_maker() as session:
                try:
                    session.add(new_subtitle)
                    await session.commit()

                    # Auto-select subtitle
                    sel_result = await session.execute(
                        select(UserSubtitleSelection).filter_by(
                            user_id=(current_user.auth_id),
                            content_id=content_id,
                            video_hash=video_hash or '',
                            language=form.language.data
                        )
                    )
                    existing_selection = sel_result.scalar_one_or_none()
                    if existing_selection:
                        existing_selection.selected_subtitle_id = new_subtitle.id
                        existing_selection.selected_external_file_id = None
                        existing_selection.external_details_json = None
                        existing_selection.timestamp = datetime.datetime.utcnow()
                    else:
                        new_selection = UserSubtitleSelection(
                            user_id=(current_user.auth_id),
                            content_id=content_id,
                            video_hash=video_hash or '',
                            selected_subtitle_id=new_subtitle.id,
                            language=form.language.data
                        )
                        session.add(new_selection)
                    await session.commit()
                    await flash(_('Subtitle uploaded and selected successfully!'), 'success')
                except Exception as sel_e:
                    await session.rollback()
                    current_app.logger.error(f"Error auto-selecting uploaded subtitle: {sel_e}", exc_info=True)
                    await flash(_('Subtitle uploaded, but failed to auto-select.'), 'warning')

            # Redirect appropriately
            if is_advanced_upload:
                # Preserve content_id for next upload (JS will parse it)
                return redirect(url_for('subtitles.upload_subtitle', content_id=content_id))
            else:
                return redirect(url_for('content.content_detail', activity_id=activity_id))

        except Exception as e:
            # No db.session.rollback() needed - handled in inner try/except
            current_app.logger.error(f"Error in upload_subtitle route: {e}", exc_info=True)
            await flash(_('Error uploading subtitle. Please try again.'), 'danger')

    return await render_template('main/upload_subtitle.html', form=form, activity=activity, metadata=metadata,
                           season=season, episode=episode, is_advanced_upload=is_advanced_upload)


@subtitles_bp.route('/select_subtitle/<uuid:activity_id>/<uuid:subtitle_id>', methods=['POST'])
@login_required
async def select_subtitle(activity_id, subtitle_id):
    async with async_session_maker() as session:
        # Get activity
        act_result = await session.execute(
            select(UserActivity).filter_by(id=activity_id, user_id=current_user.auth_id)
        )
        activity = act_result.scalar_one_or_none()
        if not activity:
            from quart import abort
            abort(404)
        
        # Get subtitle
        sub_result = await session.execute(
            select(Subtitle).filter_by(id=subtitle_id)
        )
        subtitle_to_select = sub_result.scalar_one_or_none()
        if not subtitle_to_select:
            from quart import abort
            abort(404)

        try:
            sel_result = await session.execute(
                select(UserSubtitleSelection).filter_by(
                    user_id=(current_user.auth_id),
                    content_id=activity.content_id,
                    video_hash=activity.video_hash or '',
                    language=subtitle_to_select.language
                )
            )
            selection = sel_result.scalar_one_or_none()
            if selection:
                selection.selected_subtitle_id = subtitle_to_select.id
                selection.selected_external_file_id = None
                selection.external_details_json = None
                selection.timestamp = datetime.datetime.utcnow()
            else:
                selection = UserSubtitleSelection(
                    user_id=(current_user.auth_id),
                    content_id=activity.content_id,
                    video_hash=activity.video_hash or '',
                    selected_subtitle_id=subtitle_to_select.id,
                    language=subtitle_to_select.language
                )
                session.add(selection)
            await session.commit()
            await flash(_('Subtitle selection updated.'), 'success')
        except Exception as e:
            await session.rollback()
            current_app.logger.error(f"Error selecting subtitle: {e}", exc_info=True)
            await flash(_('Error updating subtitle selection.'), 'danger')
    return redirect(url_for('content.content_detail', activity_id=activity_id))


@subtitles_bp.route('/vote/<uuid:subtitle_id>/<vote_type>', methods=['POST'])
@login_required
async def vote_subtitle(subtitle_id, vote_type):
    activity_id = (await request.form).get('activity_id')
    vote_value = 1 if vote_type == 'up' else -1
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
    
    async with async_session_maker() as session:
        # Get subtitle
        sub_result = await session.execute(select(Subtitle).filter_by(id=subtitle_id))
        subtitle = sub_result.scalar_one_or_none()
        if not subtitle:
            from quart import abort
            abort(404)

        if not (subtitle.source_type == 'community' or subtitle.source_type.endswith('_community_link')):
            if is_ajax:
                return jsonify({'error': 'Voting not available'}), 400
            await flash(_('Voting is not available for this type of subtitle.'), 'warning')
            return redirect(request.referrer or url_for('main.dashboard'))

        vote_result = await session.execute(
            select(SubtitleVote).filter_by(user_id=(current_user.auth_id), subtitle_id=subtitle_id)
        )
        existing_vote = vote_result.scalar_one_or_none()
        removed = False
        try:
            if existing_vote:
                if existing_vote.vote_value == vote_value:
                    subtitle.votes -= existing_vote.vote_value
                    await session.delete(existing_vote)
                    removed = True
                    if not is_ajax:
                        await flash(_('Vote removed.'), 'info')
                else:
                    subtitle.votes = subtitle.votes - existing_vote.vote_value + vote_value
                    existing_vote.vote_value = vote_value
                    if not is_ajax:
                        await flash(_('Vote updated.'), 'success')
            else:
                new_vote = SubtitleVote(user_id=(current_user.auth_id), subtitle_id=subtitle_id, vote_value=vote_value)
                subtitle.votes += vote_value
                session.add(new_vote)
                if not is_ajax:
                    await flash(_('Vote recorded.'), 'success')
            await session.commit()
            
            if is_ajax:
                return jsonify({'removed': removed})
        except Exception as e:
            await session.rollback()
            current_app.logger.error(f"Error processing vote: {e}", exc_info=True)
            if is_ajax:
                return jsonify({'error': 'Error processing vote'}), 500
            if not is_ajax:
                await flash(_('Error processing vote.'), 'danger')

    if activity_id: 
        return redirect(url_for('content.content_detail', activity_id=activity_id))
    return redirect(url_for('subtitles.voted_subtitles'))


@subtitles_bp.route('/delete_selection/<int:selection_id>', methods=['POST'])
@login_required
async def delete_selection(selection_id):
    async with async_session_maker() as session:
        sel_result = await session.execute(select(UserSubtitleSelection).filter_by(id=selection_id))
        selection = sel_result.scalar_one_or_none()
        if not selection:
            from quart import abort
            abort(404)
        
        if selection.user_id != (current_user.auth_id):
            await flash(_('You do not have permission to delete this selection.'), 'danger')
            return redirect(url_for('subtitles.selected_subtitles'))
        
        try:
            await session.delete(selection)
            await session.commit()
            await flash(_('Selection deleted successfully.'), 'success')
        except Exception as e:
            await session.rollback()
            current_app.logger.error(f"Error deleting selection {selection_id}: {e}", exc_info=True)
            await flash(_('Error deleting selection.'), 'danger')
    
    return redirect(url_for('subtitles.selected_subtitles'))


@subtitles_bp.route('/reset_selection/<uuid:activity_id>', methods=['POST'])
@login_required
async def reset_selection(activity_id):
    async with async_session_maker() as session:
        # Get activity
        act_result = await session.execute(
            select(UserActivity).filter_by(id=activity_id, user_id=current_user.auth_id)
        )
        activity = act_result.scalar_one_or_none()
        if not activity:
            from quart import abort
            abort(404)
        
        # Find all selections for this user and activity
        sel_result = await session.execute(
            select(UserSubtitleSelection).filter_by(
                user_id=(current_user.auth_id),
                content_id=activity.content_id,
                video_hash=activity.video_hash
            )
        )
        selections_to_delete = sel_result.scalars().all()

        if selections_to_delete:
            try:
                for selection in selections_to_delete:
                    session.delete(selection)
                await session.commit()
                await flash(_('All subtitle selections for this content have been reset.'), 'success')
            except Exception as e:
                await session.rollback()
                current_app.logger.error(f"Error resetting selections: {e}", exc_info=True)
                await flash('Error resetting selections.', 'danger')
        else:
            await flash(_('No selections to reset for this content.'), 'info')
    return redirect(url_for('content.content_detail', activity_id=activity_id))


@subtitles_bp.route('/voted-subtitles')
@login_required
async def voted_subtitles():
    """Display user's voted subtitles with pagination."""
    from sqlalchemy.orm import joinedload
    page = request.args.get('page', 1, type=int)
    per_page = 10
    
    async with async_session_maker() as session:
        query = select(SubtitleVote).filter_by(user_id=current_user.auth_id).options(
            joinedload(SubtitleVote.subtitle).joinedload(Subtitle.uploader)
        ).order_by(
            SubtitleVote.timestamp.desc()
        )
        pagination = await paginate_query(session, query, page, per_page)
    
    # Batch collect unique content_ids first
    content_ids_to_fetch = {}
    for vote in pagination.items:
        if vote.subtitle:
            content_type = 'series' if ':' in vote.subtitle.content_id else 'movie'
            content_ids_to_fetch[vote.subtitle.content_id] = content_type
    
    # Fetch metadata in batch (cache will help)
    metadata_cache = {}
    for content_id, content_type in content_ids_to_fetch.items():
        meta = await get_metadata(content_id, content_type)
        if meta:
            metadata_cache[content_id] = meta
    
    # Build metadata_map using cached results
    metadata_map = {}
    for vote in pagination.items:
        if vote.subtitle and vote.subtitle.content_id in metadata_cache:
            meta = metadata_cache[vote.subtitle.content_id].copy()
            title = meta.get('title', vote.subtitle.content_id)
            if meta.get('season') is not None and meta.get('episode') is not None:
                title = f"{title} S{meta['season']:02d}E{meta['episode']:02d}"
            elif meta.get('season') is not None:
                title = f"{title} S{meta['season']:02d}"
            if meta.get('year'):
                title = f"{title} ({meta['year']})"
            meta['display_title'] = title
            metadata_map[vote.id] = meta
    
    del metadata_cache
    gc.collect()
    
    # Helper function to get provider
    from ..providers.registry import ProviderRegistry
    def get_provider(provider_name):
        try:
            return ProviderRegistry.get(provider_name)
        except:
            return None
    
    return await render_template('main/voted_subtitles.html', 
                         votes=pagination.items,
                         pagination=pagination,
                         metadata_map=metadata_map,
                         get_provider=get_provider)


@subtitles_bp.route('/selected-subtitles')
@login_required
async def selected_subtitles():
    """Display user's selected subtitles with pagination."""
    from sqlalchemy.orm import joinedload
    page = request.args.get('page', 1, type=int)
    per_page = 10
    
    async with async_session_maker() as session:
        query = select(UserSubtitleSelection).filter_by(user_id=current_user.auth_id).options(
            joinedload(UserSubtitleSelection.selected_subtitle).joinedload(Subtitle.uploader)
        ).order_by(
            UserSubtitleSelection.timestamp.desc()
        )
        pagination = await paginate_query(session, query, page, per_page)
        
        # Batch collect unique content_ids and subtitle_ids
        content_ids_to_fetch = {}
        subtitle_ids_to_check = []
        for selection in pagination.items:
            content_type = 'series' if ':' in selection.content_id else 'movie'
            content_ids_to_fetch[selection.content_id] = content_type
            if selection.selected_subtitle_id and selection.selected_subtitle:
                subtitle_ids_to_check.append(selection.selected_subtitle.id)
        
        # Batch fetch votes
        user_votes = {}
        if subtitle_ids_to_check:
            votes_result = await session.execute(
                select(SubtitleVote).filter(
                    SubtitleVote.user_id == (current_user.auth_id),
                    SubtitleVote.subtitle_id.in_(subtitle_ids_to_check)
                )
            )
            votes = votes_result.scalars().all()
            user_votes = {vote.subtitle_id: vote.vote_value for vote in votes}
    
    # Batch fetch metadata
    metadata_cache = {}
    for content_id, content_type in content_ids_to_fetch.items():
        meta = await get_metadata(content_id, content_type)
        if meta:
            metadata_cache[content_id] = meta
    
    # Build metadata_map
    metadata_map = {}
    for selection in pagination.items:
        if selection.content_id in metadata_cache:
            meta = metadata_cache[selection.content_id].copy()
            title = meta.get('title', selection.content_id)
            if meta.get('season') is not None and meta.get('episode') is not None:
                title = f"{title} S{meta['season']:02d}E{meta['episode']:02d}"
            elif meta.get('season') is not None:
                title = f"{title} S{meta['season']:02d}"
            if meta.get('year'):
                title = f"{title} ({meta['year']})"
            meta['display_title'] = title
            metadata_map[selection.id] = meta
    
    del metadata_cache
    gc.collect()
    
    # Helper function to get provider
    from ..providers.registry import ProviderRegistry
    def get_provider(provider_name):
        try:
            return ProviderRegistry.get(provider_name)
        except:
            return None
    
    return await render_template('main/selected_subtitles.html', 
                         selections=pagination.items,
                         pagination=pagination,
                         metadata_map=metadata_map,
                         user_votes=user_votes,
                         get_provider=get_provider)
@subtitles_bp.route('/my-subtitles')
@login_required
async def my_subtitles():
    """Display user's uploaded subtitles with pagination."""
    page = request.args.get('page', 1, type=int)
    per_page = 10
    
    async with async_session_maker() as session:
        # Get paginated subtitles
        query = select(Subtitle).filter_by(uploader_id=current_user.auth_id).order_by(
            Subtitle.upload_timestamp.desc()
        )
        pagination = await paginate_query(session, query, page, per_page)
        
        # Batch collect unique content_ids and subtitle_ids
        content_ids_to_fetch = {}
        subtitle_ids = []
        for subtitle in pagination.items:
            content_ids_to_fetch[subtitle.content_id] = subtitle.content_type
            subtitle_ids.append(subtitle.id)
        
        # Batch fetch votes
        user_votes = {}
        if subtitle_ids:
            votes_result = await session.execute(
                select(SubtitleVote).filter(
                    SubtitleVote.user_id == (current_user.auth_id),
                    SubtitleVote.subtitle_id.in_(subtitle_ids)
                )
            )
            votes = votes_result.scalars().all()
            user_votes = {vote.subtitle_id: vote.vote_value for vote in votes}
    
    # Batch fetch metadata
    metadata_cache = {}
    for content_id, content_type in content_ids_to_fetch.items():
        meta = await get_metadata(content_id, content_type)
        if meta:
            metadata_cache[content_id] = meta
    
    # Build metadata_map
    metadata_map = {}
    for subtitle in pagination.items:
        if subtitle.content_id in metadata_cache:
            meta = metadata_cache[subtitle.content_id].copy()
            title = meta.get('title', subtitle.content_id)
            if meta.get('season') is not None and meta.get('episode') is not None:
                title = f"{title} S{meta['season']:02d}E{meta['episode']:02d}"
            elif meta.get('season') is not None:
                title = f"{title} S{meta['season']:02d}"
            if meta.get('year'):
                title = f"{title} ({meta['year']})"
            meta['display_title'] = title
            metadata_map[subtitle.id] = meta
    
    del metadata_cache
    gc.collect()
    
    # Helper function to get provider
    from ..providers.registry import ProviderRegistry
    def get_provider(provider_name):
        try:
            return ProviderRegistry.get(provider_name)
        except:
            return None
    
    return await render_template('main/my_subtitles.html', 
                         subtitles=pagination.items,
                         pagination=pagination,
                         metadata_map=metadata_map,
                         user_votes=user_votes,
                         get_provider=get_provider)


@subtitles_bp.route('/delete_subtitle/<uuid:subtitle_id>', methods=['POST'])
@login_required
async def delete_subtitle(subtitle_id):
    activity_id = (await request.form).get('activity_id')
    
    async with async_session_maker() as session:
        # Get subtitle
        sub_result = await session.execute(select(Subtitle).filter_by(id=subtitle_id))
        subtitle = sub_result.scalar_one_or_none()
        if not subtitle:
            from quart import abort
            abort(404)

        # Get user to check role
        user_result = await session.execute(select(User).filter_by(id=int(current_user.auth_id)))
        user = user_result.scalar_one_or_none()
        
        if subtitle.uploader_id != int(current_user.auth_id) and not (user and user.has_role('Admin')):
            await flash(_('You do not have permission to delete this subtitle.'), 'danger')
            return redirect(request.referrer or url_for('main.dashboard'))

        try:
            # Delete associated selections
            await session.execute(
                sql_delete(UserSubtitleSelection).where(UserSubtitleSelection.selected_subtitle_id == subtitle.id)
            )
            # Delete associated votes
            await session.execute(
                sql_delete(SubtitleVote).where(SubtitleVote.subtitle_id == subtitle.id)
            )

            # Check if file can be deleted
            if subtitle.source_type == 'community' and subtitle.file_path:
                other_result = await session.execute(
                    select(Subtitle).filter(
                        Subtitle.file_path == subtitle.file_path,
                        Subtitle.id != subtitle.id
                    )
                )
                other_subtitles_using_file = other_result.scalar_one_or_none()

                if not other_subtitles_using_file:
                    # Delete files from storage
                    if current_app.config['STORAGE_BACKEND'] == 'cloudinary':
                        if CLOUDINARY_AVAILABLE and cloudinary.config().api_key:
                            try:
                                cloudinary.uploader.destroy(subtitle.file_path, resource_type="raw")
                                current_app.logger.info(f"Deleted Cloudinary resource: {subtitle.file_path}")
                            except Exception as e:
                                current_app.logger.error(f"Error deleting Cloudinary resource {subtitle.file_path}: {e}")
                    else:
                        local_file_full_path = os.path.join(current_app.config['UPLOAD_FOLDER'], subtitle.file_path)
                        if os.path.exists(local_file_full_path):
                            try:
                                os.remove(local_file_full_path)
                                current_app.logger.info(f"Deleted local file: {local_file_full_path}")
                            except Exception as e:
                                current_app.logger.error(f"Error deleting local file {local_file_full_path}: {e}")
                    
                    # Delete original ASS/SSA file
                    if subtitle.source_metadata and subtitle.source_metadata.get('original_file_path'):
                        original_ass_path = subtitle.source_metadata.get('original_file_path')
                        if current_app.config['STORAGE_BACKEND'] == 'cloudinary':
                            if CLOUDINARY_AVAILABLE and cloudinary.config().api_key:
                                try:
                                    cloudinary.uploader.destroy(original_ass_path, resource_type="raw")
                                    current_app.logger.info(f"Deleted Cloudinary ASS resource: {original_ass_path}")
                                except Exception as e:
                                    current_app.logger.error(f"Error deleting Cloudinary ASS resource {original_ass_path}: {e}")
                        else:
                            local_ass_full_path = os.path.join(current_app.config['UPLOAD_FOLDER'], original_ass_path)
                            if os.path.exists(local_ass_full_path):
                                try:
                                    os.remove(local_ass_full_path)
                                    current_app.logger.info(f"Deleted local ASS file: {local_ass_full_path}")
                                except Exception as e:
                                    current_app.logger.error(f"Error deleting local ASS file {local_ass_full_path}: {e}")
                else:
                    current_app.logger.info(f"File {subtitle.file_path} not deleted as it's still used by other subtitles.")

            await session.delete(subtitle)
            await session.commit()
            await flash(_('Subtitle deleted successfully.'), 'success')
        except Exception as e:
            await session.rollback()
            current_app.logger.error(f"Error deleting subtitle {subtitle_id}: {e}", exc_info=True)
            await flash(_('Error deleting subtitle.'), 'danger')

    if activity_id: 
        return redirect(url_for('content.content_detail', activity_id=activity_id))
    return redirect(url_for('subtitles.my_subtitles'))


@subtitles_bp.route('/download_subtitle/<uuid:subtitle_id>')
@login_required
async def download_subtitle(subtitle_id):
    from quart import send_file, abort
    from sqlalchemy.orm import selectinload
    
    # Get full user object with roles to check permission
    async with async_session_maker() as session:
        user_result = await session.execute(
            select(User).options(selectinload(User.roles)).filter_by(id=int(current_user.auth_id))
        )
        user = user_result.scalar_one_or_none()
        
        if not user or not user.has_role('Admin'):
            await flash(_('You do not have permission to download subtitles.'), 'danger')
            return redirect(url_for('main.dashboard'))

    async with async_session_maker() as session:
        sub_result = await session.execute(select(Subtitle).filter_by(id=subtitle_id))
        subtitle = sub_result.scalar_one_or_none()
        if not subtitle:
            abort(404)
    
    content_id_display = subtitle.content_id.replace(':', '_')
    download_filename = f"{content_id_display}_{subtitle.language}_{str(subtitle.id)[:8]}.vtt"

    if subtitle.source_type.endswith('_community_link') and subtitle.source_metadata:
        provider_name = subtitle.source_metadata.get('provider')
        provider_subtitle_id = subtitle.source_metadata.get('provider_subtitle_id')
        
        if not provider_subtitle_id:
            current_app.logger.error(f"Linked provider subtitle {subtitle.id} missing provider_subtitle_id for download.")
            abort(404)
        
        try:
            from ..providers.registry import ProviderRegistry
            from ..providers.base import ProviderDownloadError
            
            # Get full user object for provider authentication
            async with async_session_maker() as session:
                user_result = await session.execute(select(User).filter_by(id=int(current_user.auth_id)))
                admin_user = user_result.scalar_one_or_none()
            
            provider = ProviderRegistry.get(provider_name)
            if not provider or not await provider.is_authenticated(admin_user):
                await flash(_("Admin's %(provider)s account is not configured/active; cannot download this linked subtitle.", provider=provider_name), "warning")
                return redirect(request.referrer or url_for('main.dashboard'))
            
            try:
                provider_url = await provider.get_download_url(admin_user, provider_subtitle_id)
                if provider_url:
                    current_app.logger.info(f"Serving {provider_name} direct url")
                    return no_cache_redirect(provider_url, code=302)
                else:
                    current_app.logger.info(f"{provider_name} requires direct download")
                    try:
                        zip_content = await provider.download_subtitle(admin_user, provider_subtitle_id)
                        return Response(zip_content, mimetype='application/zip', headers={"Content-Disposition": f"attachment;filename={content_id_display}_{subtitle.language}.zip"})
                    except Exception as e:
                        current_app.logger.error(f"Error processing {provider_name} download: {e}", exc_info=True)
                        await flash(_("Error downloading from %(provider)s: %(error)s", provider=provider_name, error=str(e)), "danger")
                        return redirect(request.referrer or url_for('main.dashboard'))
            except ProviderDownloadError as e:
                error_msg = str(e)
                # Special handling for 401 Unauthorized
                if hasattr(e, 'status_code') and e.status_code == 401:
                    current_app.logger.warning(f"{provider_name} authentication expired: {error_msg}")
                    await flash(_("%(provider)s authentication expired. Please log in again in account settings.", provider=provider_name), "warning")
                else:
                    current_app.logger.error(f"{provider_name} download error: {error_msg}", exc_info=True)
                    await flash(_("Error downloading from %(provider)s: %(error)s", provider=provider_name, error=error_msg), "danger")
                return redirect(request.referrer or url_for('main.dashboard'))
        except Exception as e:
            current_app.logger.error(f"Error downloading linked provider subtitle {provider_subtitle_id}: {e}", exc_info=True)
            abort(500)

    elif subtitle.file_path:  # Community subtitle (local or cloudinary)
        try:
            vtt_content = await get_vtt_content(subtitle)
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
async def mark_compatible_hash(subtitle_id):
    target_video_hash = (await request.form).get('target_video_hash')
    activity_id_str = (await request.form).get('activity_id')

    if not target_video_hash:
        await flash(_('Target video hash is missing.'), 'danger')
        return redirect(request.referrer or url_for('main.dashboard'))
    if not activity_id_str:
        await flash(_('Activity ID is missing.'), 'danger')
        return redirect(request.referrer or url_for('main.dashboard'))

    try:
        activity_id_uuid = uuid.UUID(activity_id_str)
    except ValueError:
        await flash(_('Invalid Activity ID format.'), 'danger')
        return redirect(request.referrer or url_for('main.dashboard'))

    async with async_session_maker() as session:
        # Get original subtitle
        sub_result = await session.execute(select(Subtitle).filter_by(id=subtitle_id))
        original_subtitle = sub_result.scalar_one_or_none()
        if not original_subtitle:
            from quart import abort
            abort(404)
        
        # Get activity
        act_result = await session.execute(select(UserActivity).filter_by(id=activity_id_uuid))
        activity = act_result.scalar_one_or_none()
        if not activity:
            from quart import abort
            abort(404)

        if activity.content_id != original_subtitle.content_id:
            await flash(_('Content ID mismatch between subtitle and activity.'), 'danger')
            return redirect(url_for('content.content_detail', activity_id=activity.id))

        if original_subtitle.source_type.endswith('_community_link'):
            await flash(_('This operation is not applicable to provider-linked entries in this manner.'), 'warning')
            return redirect(url_for('content.content_detail', activity_id=activity.id))
        if not original_subtitle.file_path:
            await flash(_('Original subtitle does not have a file path, cannot mark as compatible.'), 'danger')
            return redirect(url_for('content.content_detail', activity_id=activity.id))

        # Check for existing compatible subtitle
        compat_result = await session.execute(
            select(Subtitle).filter_by(
                content_id=original_subtitle.content_id,
                language=original_subtitle.language,
                video_hash=target_video_hash,
                file_path=original_subtitle.file_path,
                source_type=original_subtitle.source_type
            )
        )
        existing_compatible_sub = compat_result.scalar_one_or_none()

        newly_created_sub = None
        if existing_compatible_sub:
            newly_created_sub = existing_compatible_sub
            await flash(_('A compatible subtitle entry for this hash already exists. Selecting it.'), 'info')
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
                source_type=original_subtitle.source_type,
                source_metadata=original_subtitle.source_metadata
            )
            session.add(new_compatible_subtitle_entry)
            newly_created_sub = new_compatible_subtitle_entry
            await flash(_('Subtitle marked as compatible with the current video version.'), 'success')

            # Add the initial vote
            await session.flush()
            initial_vote = SubtitleVote(
                user_id=(current_user.auth_id),
                subtitle_id=new_compatible_subtitle_entry.id,
                vote_value=1
            )
            session.add(initial_vote)

        # Update UserSubtitleSelection
        sel_result = await session.execute(
            select(UserSubtitleSelection).filter_by(
                user_id=(current_user.auth_id),
                content_id=activity.content_id,
                video_hash=target_video_hash or '',
                language=original_subtitle.language
            )
        )
        user_sel = sel_result.scalar_one_or_none()
        if user_sel:
            user_sel.selected_subtitle_id = newly_created_sub.id
            user_sel.selected_external_file_id = None
            user_sel.external_details_json = None
            user_sel.timestamp = datetime.datetime.utcnow()
        else:
            user_sel = UserSubtitleSelection(
                user_id=(current_user.auth_id),
                content_id=activity.content_id,
                video_hash=target_video_hash or '',
                selected_subtitle_id=newly_created_sub.id,
                language=original_subtitle.language
            )
            session.add(user_sel)

        try:
            await session.commit()
        except Exception as e:
            await session.rollback()
            current_app.logger.error(f"Error in mark_compatible_hash: {e}", exc_info=True)
            await flash(_('An error occurred.'), 'danger')

    return redirect(url_for('content.content_detail', activity_id=activity.id))
