from flask import jsonify, Response, current_app
from rapidfuzz import fuzz
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
    name = name.lower()
    name = re.sub(r'\.[a-zA-Z0-9]+$', '', name)
    name = re.sub(r'[\.\_\-\s]+', ' ', name)
    common_tags = ['web-dl', 'webrip', 'bluray', 'hdrip', 'hdtv', 'x264', 'h264', 'x265', 'hevc',
                   'aac', 'ac3', 'dts', '1080p', '720p', '2160p', '4k', 'hdr', 'dv']
    for tag in common_tags:
        name = name.replace(tag, '')
    return name.strip()


def extract_release_components(name):
    """Extract key components from release name for weighted comparison."""
    if not name:
        return {'title': '', 'season_episode': '', 'group': '', 'quality': ''}
    
    name_lower = name.lower()
    # Remove file extension first (e.g., .mkv, .mp4, .avi)
    name_lower = re.sub(r'\.[a-zA-Z0-9]+$', '', name_lower)
    name_normalized = re.sub(r'[\.\_\-]+', ' ', name_lower)
    
    # Extract season/episode (S03E07, S03_07, 3x07, etc.)
    season_episode = ''
    se_patterns = [
        r's(\d+)\s*e(\d+)',  # S03E07
        r's(\d+)\s*(\d+)',   # S03_07
        r'(\d+)x(\d+)',      # 3x07
    ]
    for pattern in se_patterns:
        match = re.search(pattern, name_normalized)
        if match:
            season_episode = f"s{int(match.group(1)):02d}e{int(match.group(2)):02d}"
            break
    
    # Extract quality: source type + resolution
    source_types = ['web-dl', 'webdl', 'webrip', 'bluray', 'blu-ray', 'brrip', 'hdrip', 'hdtv', 'dvdrip']
    resolution_tags = ['2160p', '1080p', '720p', '480p', '4k', 'uhd', 'hd']
    
    quality_parts = []
    for source in source_types:
        if source in name_normalized:
            quality_parts.append(source.replace('-', ''))
            break
    for res in resolution_tags:
        if res in name_normalized:
            quality_parts.append(res)
            break
    
    quality = ' '.join(quality_parts)
    
    # Extract release group (priority: dash before bracket > bracket at start/end)
    group = ''
    # Priority 1: Group after dash, before bracket at end (e.g., -BiOMA[EZTVx.to])
    dash_before_bracket = re.search(r'-([a-z0-9]+)\[', name_lower)
    if dash_before_bracket:
        group = dash_before_bracket.group(1)
    else:
        # Priority 2: Brackets at start or end (allow dots for trackers like EZTVx.to)
        bracket_match = re.search(r'^\[([a-z0-9.]+)\]|\[([a-z0-9.]+)\]$', name_lower)
        if bracket_match:
            group = bracket_match.group(1) or bracket_match.group(2)
        else:
            # Priority 3: After dash at end
            dash_match = re.search(r'[-\s]([a-z0-9]+)$', name_normalized)
            if dash_match:
                group = dash_match.group(1)
    
    # Title is what remains after removing S/E, quality, and common tags
    title = name_normalized
    if season_episode:
        title = re.sub(r's\d+\s*e?\d+', '', title)
    for tag in source_types + resolution_tags + ['x264', 'h264', 'x265', 'hevc']:
        title = title.replace(tag, '')
    title = re.sub(r'\s+', ' ', title).strip()
    
    return {
        'title': title,
        'season_episode': season_episode,
        'group': group,
        'quality': quality
    }


def calculate_filename_similarity(video_filename, subtitle_release_name):
    """
    Calculates weighted similarity between video filename and subtitle release name.
    For series: S/E (40%) > group (40%) > quality (15%) > title (5%)
    For movies: group (50%) > quality (20%) > title (30%)
    Returns a float between 0.0 and 1.0.
    """
    if not video_filename or not subtitle_release_name:
        return 0.0

    video_parts = extract_release_components(video_filename)
    subtitle_parts = extract_release_components(subtitle_release_name)
    
    if not video_parts['title'] or not subtitle_parts['title']:
        return 0.0
    
    # Season/Episode exact match - critical for series
    se_sim = 1.0 if (video_parts['season_episode'] and 
                    video_parts['season_episode'] == subtitle_parts['season_episode']) else 0.0
    
    # Release group similarity - important for sync
    group_sim = 0.0
    if video_parts['group'] and subtitle_parts['group']:
        group_sim = fuzz.ratio(video_parts['group'], subtitle_parts['group']) / 100.0
    
    # Quality similarity - same source type often compatible
    quality_sim = 0.0
    if video_parts['quality'] and subtitle_parts['quality']:
        quality_sim = fuzz.token_set_ratio(video_parts['quality'], subtitle_parts['quality']) / 100.0
    
    # Title similarity - less important since filtered by content_id
    title_sim = fuzz.token_sort_ratio(video_parts['title'], subtitle_parts['title']) / 100.0
    
    # Dynamic weights based on content type
    if video_parts['season_episode']:
        # Series: prioritize S/E match
        score = (se_sim * 0.4) + (group_sim * 0.4) + (quality_sim * 0.15) + (title_sim * 0.05)
    else:
        # Movies: no S/E, redistribute weight to group and quality
        score = (group_sim * 0.5) + (quality_sim * 0.2) + (title_sim * 0.3)
    
    return score





def get_active_subtitle_details(user, content_id, video_hash=None, content_type=None, video_filename=None, lang=None, season=None, episode=None):
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
        
        # Provider selection
        if user_selection.external_details_json:
            details = user_selection.external_details_json
            provider_name = details.get('provider')
            subtitle_id = details.get('subtitle_id') or details.get('file_id')
            
            if provider_name and subtitle_id:
                result.update({
                    'type': f'{provider_name}_selection',
                    'provider_name': provider_name,
                    'provider_subtitle_id': str(subtitle_id),
                    'provider_metadata': details,
                    'details': details,
                    'release_name': details.get('release_name'),
                    'uploader': details.get('uploader'),
                    'rating': details.get('rating'),
                    'download_count': details.get('download_count'),
                    'hearing_impaired': details.get('hearing_impaired', False),
                    'ai_translated': details.get('ai_translated', False),
                    'moviehash_match': details.get('hash_match', False),
                    'url': details.get('url', '')
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
        provider_result = _search_providers_by_hash(user, content_id, video_hash, content_type, lang, season, episode)
        if provider_result:
            result.update(provider_result)
            result['auto'] = True
            return result
    
    # 4. Best match by filename
    if video_filename:
        best_match = _find_best_match_by_filename(user, content_id, video_filename, content_type, lang, season, episode)
        if best_match:
            result.update(best_match)
            result['auto'] = True
            return result
    
    # 5. Fallback
    fallback = _find_fallback_subtitle(user, content_id, content_type, lang, season, episode)
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


def _search_providers_by_hash(user, content_id, video_hash, content_type, lang, season=None, episode=None):
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
                season=season,
                episode=episode,
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
                        'details': {'file_id': result.subtitle_id, 'release_name': result.release_name},
                        'release_name': result.release_name,
                        'uploader': result.uploader,
                        'rating': result.rating,
                        'download_count': result.download_count,
                        'hearing_impaired': result.hearing_impaired,
                        'ai_translated': result.ai_translated,
                        'moviehash_match': result.metadata.get('hash_match', False),
                        'url': result.metadata.get('url', '') if result.metadata else ''
                    }
        except Exception as e:
            current_app.logger.error(f"Provider {provider.name} search failed: {e}")
    return None


def _find_best_match_by_filename(user, content_id, video_filename, content_type, lang, season=None, episode=None):
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
                    season=season,
                    episode=episode,
                    content_type=content_type,
                    video_filename=video_filename
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
                            'score': score,
                            'release_name': result.release_name,
                            'uploader': result.uploader,
                            'rating': result.rating,
                            'download_count': result.download_count,
                            'hearing_impaired': result.hearing_impaired,
                            'ai_translated': result.ai_translated,
                            'moviehash_match': result.metadata.get('hash_match', False) if result.metadata else False,
                            'url': result.metadata.get('url', '') if result.metadata else ''
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
            'details': {'file_id': best['provider_subtitle_id']},
            'release_name': best.get('release_name'),
            'uploader': best.get('uploader'),
            'rating': best.get('rating'),
            'download_count': best.get('download_count'),
            'hearing_impaired': best.get('hearing_impaired'),
            'ai_translated': best.get('ai_translated'),
            'moviehash_match': best.get('moviehash_match', False),
            'url': best.get('url', '')
        }


def _find_fallback_subtitle(user, content_id, content_type, lang, season=None, episode=None):
    # Local first (already filtered by content_id which includes season/episode)
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
    
    # Providers - filter by episode number in release_name
    try:
        from ..providers.registry import ProviderRegistry
        active_providers = ProviderRegistry.get_active_for_user(user)
        
        for provider in active_providers:
            try:
                results = provider.search(
                    user=user,
                    imdb_id=content_id.split(':')[0] if content_id.startswith('tt') else None,
                    languages=[lang],
                    season=season,
                    episode=episode,
                    content_type=content_type
                )
                
                # Filter by episode if available (series/anime)
                if episode and results:
                    matching = []
                    matching_ep_only = []  # Fallback for anime with season but no S/E in name
                    
                    for r in results:
                        parts = extract_release_components(r.release_name)
                        
                        # Priority 1: Match by S/E format (e.g., s01e05)
                        if season and parts['season_episode'] == f"s{season:02d}e{episode:02d}":
                            matching.append(r)
                        # Priority 2: Match by episode only (for anime)
                        else:
                            ep_patterns = [
                                f' {episode:03d}',  # " 101"
                                f'-{episode:03d}',  # "-101"
                                f' {episode:02d} ', # " 01 "
                                f'-{episode:02d}-', # "-01-"
                            ]
                            if any(pattern in r.release_name.lower() for pattern in ep_patterns):
                                matching_ep_only.append(r)
                    
                    # Use S/E match if found, otherwise episode-only match
                    candidates = matching if matching else matching_ep_only
                    
                    if candidates:
                        # Prefer non-AI translated
                        non_ai = [r for r in candidates if not r.ai_translated]
                        chosen = non_ai[0] if non_ai else candidates[0]
                    else:
                        # No episode match - use first result
                        non_ai = [r for r in results if not r.ai_translated]
                        chosen = non_ai[0] if non_ai else (results[0] if results else None)
                else:
                    # No episode filtering needed (movies)
                    non_ai = [r for r in results if not r.ai_translated]
                    chosen = non_ai[0] if non_ai else (results[0] if results else None)
                
                if chosen:
                    return {
                        'type': f'{provider.name}_auto',
                        'provider_name': provider.name,
                        'provider_subtitle_id': chosen.subtitle_id,
                        'provider_metadata': {'release_name': chosen.release_name},
                        'details': {'file_id': chosen.subtitle_id},
                        'release_name': chosen.release_name,
                        'uploader': chosen.uploader,
                        'rating': chosen.rating,
                        'download_count': chosen.download_count,
                        'hearing_impaired': chosen.hearing_impaired,
                        'ai_translated': chosen.ai_translated,
                        'moviehash_match': chosen.metadata.get('hash_match', False) if chosen.metadata else False,
                        'url': chosen.metadata.get('url', '') if chosen.metadata else ''
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
    return f"WEBVTT\n\n00:00:00.000 --> 00:00:08.000\n{message}"


def extract_subtitle_from_zip(zip_content: bytes, episode: int = None):
    """
    Extracts subtitle file from ZIP archive.
    If episode is provided, tries to find file matching episode number.
    Returns tuple: (subtitle_content: bytes, filename: str, extension: str)
    """
    import zipfile
    import io
    
    subtitle_extensions = ['.srt', '.vtt', '.ass', '.ssa', '.sub']
    
    try:
        with zipfile.ZipFile(io.BytesIO(zip_content)) as zf:
            subtitle_files = []
            
            # Collect all subtitle files
            for file_info in zf.filelist:
                filename = file_info.filename
                ext = os.path.splitext(filename)[1].lower()
                
                if ext in subtitle_extensions:
                    subtitle_files.append(file_info)
            
            if not subtitle_files:
                raise ValueError("No subtitle file found in ZIP archive")
            
            # If episode number provided, try to find matching file
            if episode is not None:
                episode_patterns = [
                    f'e{episode:02d}',  # e01, e02, etc.
                    f' {episode:02d} ', # " 01 ", " 02 ", etc.
                    f'-{episode:02d}-', # -01-, -02-, etc.
                    f'.{episode:02d}.'  # .01., .02., etc.
                ]
                
                for file_info in subtitle_files:
                    filename_lower = file_info.filename.lower()
                    if any(pattern in filename_lower for pattern in episode_patterns):
                        content = zf.read(file_info)
                        return content, file_info.filename, os.path.splitext(file_info.filename)[1].lower()
            
            # Fallback: return first subtitle file
            file_info = subtitle_files[0]
            content = zf.read(file_info)
            return content, file_info.filename, os.path.splitext(file_info.filename)[1].lower()
            
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
