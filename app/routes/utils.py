import difflib
from flask import jsonify, Response, current_app
from sqlalchemy.orm import joinedload
from ..models import Subtitle, SubtitleVote, UserSubtitleSelection
import os
import re
import requests
import time
from datetime import datetime

try:
    import cloudinary
    import cloudinary.uploader
    import cloudinary.api
    CLOUDINARY_AVAILABLE = True
except ImportError:
    CLOUDINARY_AVAILABLE = False


def respond_with(data) -> Response:
    """Create a JSON response with CORS headers."""
    resp = jsonify(data)
    resp.headers['Access-Control-Allow-Origin'] = "*"
    resp.headers['Access-Control-Allow-Headers'] = '*'
    return resp


def respond_with_no_cache(data) -> Response:
    """Create a JSON response with CORS headers."""
    resp = jsonify(data)
    resp.headers['Access-Control-Allow-Origin'] = "*"
    resp.headers['Access-Control-Allow-Headers'] = '*'
    resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate, private'
    resp.headers['Pragma'] = 'no-cache'
    resp.headers['Expires'] = '0'

    resp.headers['CF-Cache-Status'] = 'BYPASS'
    resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate, private, max-age=0'

    return resp


class NoCacheResponse(Response):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.add_no_cache_headers()

    def add_no_cache_headers(self):
        """Dodaje kompletny zestaw no-cache headers dla przeglądarek, Cloudflare i innych CDN"""

        self.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate, private, max-age=0, s-maxage=0'
        self.headers['Pragma'] = 'no-cache'
        self.headers['Expires'] = '0'

        self.headers['CF-Cache-Status'] = 'BYPASS'
        self.headers['Surrogate-Control'] = 'no-store'
        self.headers['Vary'] = '*'

        self.headers['ETag'] = f'"{int(time.time() * 1000000)}"'

        self.headers['Last-Modified'] = datetime.utcnow().strftime('%a, %d %b %Y %H:%M:%S GMT')


def no_cache_redirect(location, code=302):
    """Tworzy redirect z no-cache headers"""
    response = NoCacheResponse('', status=code)
    response.headers['Location'] = location
    return response


def normalize_release_name(name):
    """Normalizes a release name for comparison."""
    if not name:
        return ""
    # Lowercase
    name = name.lower()
    # Remove file extension if present (e.g., .mp4, .mkv, .srt)
    name = re.sub(r'\.[a-zA-Z0-9]+$', '', name)
    # Replace common delimiters with space
    name = re.sub(r'[\.\_\-\s]+', ' ', name)

    # Remove content within brackets (often uploader tags or irrelevant info)
    # name = re.sub(r'\[.*?\]', '', name)
    # name = re.sub(r'\(.*?\)', '', name)

    # Remove common tags that might differ but don't define the core release
    common_tags = ['web-dl', 'webrip', 'bluray', 'hdrip', 'hdtv', 'x264', 'h264', 'x265', 'hevc',
                   'aac', 'ac3', 'dts', '1080p', '720p', '2160p', '4k', 'hdr', 'dv']
    for tag in common_tags:
        name = name.replace(tag, '')
    # Strip extra spaces
    return name.strip()


def calculate_filename_similarity(video_filename, subtitle_release_name):
    """
    Calculates the similarity ratio between a video filename and a subtitle release name.
    Returns a float between 0.0 and 1.0.
    """
    if not video_filename or not subtitle_release_name:
        return 0.0

    norm_video_filename = normalize_release_name(video_filename)
    norm_subtitle_release_name = normalize_release_name(subtitle_release_name)

    if not norm_video_filename or not norm_subtitle_release_name:
        return 0.0

    return difflib.SequenceMatcher(None, norm_video_filename, norm_subtitle_release_name).ratio()





def get_active_subtitle_details(user, content_id, video_hash=None, content_type=None, video_filename=None, lang=None):
    """Provider-agnostic subtitle selection logic"""
    result = {
        'type': 'none',
        'subtitle': None,
        'provider_name': None,
        'provider_subtitle_id': None,
        'provider_metadata': None,
        'details': None,  # Backward compat
        'auto': False,
        'user_vote_value': None,
        'user_selection_record': None
    }
    
    # 1. User Selection
    user_selection = _get_user_selection(user, content_id, video_hash, lang)
    result['user_selection_record'] = user_selection
    
    if user_selection:
        if user_selection.selected_subtitle_id:
            result.update({
                'type': 'local',
                'subtitle': user_selection.selected_subtitle,
                'user_vote_value': _get_user_vote(user, user_selection.selected_subtitle_id)
            })
            return result
        
        # Backward compat: old OpenSubtitles selection
        if user_selection.selected_external_file_id:
            result.update({
                'type': 'opensubtitles_selection',
                'provider_name': 'opensubtitles',
                'provider_subtitle_id': str(user_selection.selected_external_file_id),
                'provider_metadata': user_selection.external_details_json,
                'details': user_selection.external_details_json
            })
            return result
    
    # 2. Local by hash
    if video_hash:
        local_sub = _find_local_by_hash(content_id, video_hash, lang)
        if local_sub:
            result.update({
                'type': 'local',
                'subtitle': local_sub,
                'auto': True,
                'user_vote_value': _get_user_vote(user, local_sub.id)
            })
            return result
    
    # 3. Providers by hash
    if video_hash:
        provider_result = _search_providers_by_hash(user, content_id, video_hash, content_type, lang)
        if provider_result:
            result.update(provider_result)
            result['auto'] = True
            return result
    
    # 4. Best match by filename
    if video_filename:
        best_match = _find_best_match_by_filename(user, content_id, video_filename, content_type, lang)
        if best_match:
            result.update(best_match)
            result['auto'] = True
            return result
    
    # 5. Fallback
    fallback = _find_fallback_subtitle(user, content_id, content_type, lang)
    if fallback:
        result.update(fallback)
        result['auto'] = True
        return result
    
    return result


def _get_user_selection(user, content_id, video_hash, lang):
    query = UserSubtitleSelection.query.filter_by(
        user_id=user.id,
        content_id=content_id,
        language=lang
    )
    if video_hash:
        query = query.filter_by(video_hash=video_hash)
    else:
        query = query.filter(UserSubtitleSelection.video_hash.is_(None))
    return query.options(joinedload(UserSubtitleSelection.selected_subtitle)).first()


def _get_user_vote(user, subtitle_id):
    vote = SubtitleVote.query.filter_by(user_id=user.id, subtitle_id=subtitle_id).first()
    return vote.vote_value if vote else None


def _find_local_by_hash(content_id, video_hash, lang):
    return Subtitle.query.filter_by(
        content_id=content_id,
        language=lang,
        video_hash=video_hash
    ).order_by(Subtitle.votes.desc()).first()


def _search_providers_by_hash(user, content_id, video_hash, content_type, lang):
    try:
        from ..providers.registry import ProviderRegistry
        active_providers = ProviderRegistry.get_active_for_user(user)
    except Exception as e:
        current_app.logger.error(f"Error accessing ProviderRegistry: {e}")
        return None
    
    for provider in active_providers:
        if not provider.supports_hash_matching:
            continue
        try:
            results = provider.search(
                user=user,
                imdb_id=content_id.split(':')[0] if content_id.startswith('tt') else None,
                video_hash=video_hash,
                languages=[lang],
                content_type=content_type
            )
            for result in results:
                if result.metadata and result.metadata.get('hash_match'):
                    return {
                        'type': f'{provider.name}_auto',
                        'provider_name': provider.name,
                        'provider_subtitle_id': result.subtitle_id,
                        'provider_metadata': {
                            'release_name': result.release_name,
                            'uploader': result.uploader,
                            'hash_match': True
                        },
                        'details': {'file_id': result.subtitle_id, 'release_name': result.release_name}
                    }
        except Exception as e:
            current_app.logger.error(f"Provider {provider.name} search failed: {e}")
    return None


def _find_best_match_by_filename(user, content_id, video_filename, content_type, lang):
    candidates = []
    
    # Local
    local_subs = Subtitle.query.filter_by(content_id=content_id, language=lang).all()
    for sub in local_subs:
        score = calculate_filename_similarity(video_filename, sub.version_info)
        if score > 0:
            candidates.append({'type': 'local', 'subtitle': sub, 'score': score})
    
    # Providers
    try:
        from ..providers.registry import ProviderRegistry
        active_providers = ProviderRegistry.get_active_for_user(user)
        for provider in active_providers:
            try:
                results = provider.search(
                    user=user,
                    imdb_id=content_id.split(':')[0] if content_id.startswith('tt') else None,
                    languages=[lang],
                    content_type=content_type
                )
                for result in results:
                    score = calculate_filename_similarity(video_filename, result.release_name)
                    if result.ai_translated:
                        score -= 0.05
                    if score > 0:
                        candidates.append({
                            'type': 'provider',
                            'provider_name': provider.name,
                            'provider_subtitle_id': result.subtitle_id,
                            'provider_metadata': {'release_name': result.release_name},
                            'score': score
                        })
            except Exception as e:
                current_app.logger.error(f"Provider {provider.name} search failed: {e}")
    except:
        pass
    
    if not candidates:
        return None
    
    candidates.sort(key=lambda c: c['score'], reverse=True)
    best = candidates[0]
    
    if best['type'] == 'local':
        return {
            'type': 'local',
            'subtitle': best['subtitle'],
            'user_vote_value': _get_user_vote(user, best['subtitle'].id)
        }
    else:
        return {
            'type': f"{best['provider_name']}_auto",
            'provider_name': best['provider_name'],
            'provider_subtitle_id': best['provider_subtitle_id'],
            'provider_metadata': best['provider_metadata'],
            'details': {'file_id': best['provider_subtitle_id']}
        }


def _find_fallback_subtitle(user, content_id, content_type, lang):
    # Local first
    local_sub = Subtitle.query.filter_by(
        content_id=content_id,
        language=lang
    ).order_by(Subtitle.votes.desc()).first()
    
    if local_sub:
        return {
            'type': 'local',
            'subtitle': local_sub,
            'user_vote_value': _get_user_vote(user, local_sub.id)
        }
    
    # Providers
    try:
        from ..providers.registry import ProviderRegistry
        active_providers = ProviderRegistry.get_active_for_user(user)
        for provider in active_providers:
            try:
                results = provider.search(
                    user=user,
                    imdb_id=content_id.split(':')[0] if content_id.startswith('tt') else None,
                    languages=[lang],
                    content_type=content_type
                )
                non_ai = [r for r in results if not r.ai_translated]
                chosen = non_ai[0] if non_ai else (results[0] if results else None)
                if chosen:
                    return {
                        'type': f'{provider.name}_auto',
                        'provider_name': provider.name,
                        'provider_subtitle_id': chosen.subtitle_id,
                        'provider_metadata': {'release_name': chosen.release_name},
                        'details': {'file_id': chosen.subtitle_id}
                    }
            except Exception as e:
                current_app.logger.error(f"Provider {provider.name} search failed: {e}")
    except:
        pass
    
    return None


def get_vtt_content(subtitle):
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


def extract_subtitle_from_zip(zip_content: bytes):
    """
    Extracts subtitle file from ZIP archive.
    Returns tuple: (subtitle_content: bytes, filename: str, extension: str)
    """
    import zipfile
    import io
    
    subtitle_extensions = ['.srt', '.vtt', '.ass', '.ssa', '.sub']
    
    try:
        with zipfile.ZipFile(io.BytesIO(zip_content)) as zf:
            for file_info in zf.filelist:
                filename = file_info.filename
                ext = os.path.splitext(filename)[1].lower()
                
                if ext in subtitle_extensions:
                    content = zf.read(file_info)
                    return content, filename, ext
            
            raise ValueError("No subtitle file found in ZIP archive")
    except zipfile.BadZipFile:
        raise ValueError("Invalid ZIP file")


def process_subtitle_content(content: bytes, extension: str, encoding=None):
    """
    Processes subtitle content and returns both VTT and original (if ASS/SSA).
    Returns dict: {'vtt': str, 'original': str or None, 'original_format': str or None}
    """
    from ..lib.subtitles import convert_to_vtt
    
    # Convert to VTT
    vtt_content = convert_to_vtt(content, extension.lstrip('.'), encoding=encoding)
    
    # If ASS/SSA, also keep original
    if extension.lower() in ['.ass', '.ssa']:
        try:
            original_content = content.decode('utf-8')
        except UnicodeDecodeError:
            # Try other encodings
            for enc in ['latin-1', 'cp1252', 'iso-8859-1']:
                try:
                    original_content = content.decode(enc)
                    break
                except:
                    continue
            else:
                original_content = None
        
        return {
            'vtt': vtt_content,
            'original': original_content,
            'original_format': extension.lstrip('.')
        }
    
    return {
        'vtt': vtt_content,
        'original': None,
        'original_format': None
    }
