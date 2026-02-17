from quart_babel import gettext as _
from quart import jsonify, Response, current_app
from rapidfuzz import fuzz
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from ..models import Subtitle, SubtitleVote, UserSubtitleSelection
from ..extensions import async_session_maker
import os
import re
import aiohttp
import time
import gc
import zipfile
import io
import rarfile
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





async def get_active_subtitle_details(user, content_id, video_hash=None, content_type=None, video_filename=None, lang=None, season=None, episode=None, cached_provider_results=None):
    """Provider-agnostic subtitle selection logic"""
    import time
    func_start = time.time()
    
    # Parse Kitsu/MAL content_id and extract IMDb ID if needed
    imdb_id = None
    if content_id.startswith('tt'):
        imdb_id = content_id.split(':')[0]
    elif content_id.startswith('kitsu:'):
        from ..lib.anime_mapping import get_imdb_from_kitsu
        kitsu_id = int(content_id.split(':')[1])
        result = get_imdb_from_kitsu(kitsu_id)
        if result:
            imdb_id = result['imdb_id']
            if result['season']:
                season = result['season']
    elif content_id.startswith('mal:'):
        from ..lib.anime_mapping import get_imdb_from_mal
        mal_id = int(content_id.split(':')[1])
        result = get_imdb_from_mal(mal_id)
        if result:
            imdb_id = result['imdb_id']
            if result['season']:
                season = result['season']
    
    # Extract season and episode from content_id if not provided
    if season is None and episode is None and content_type == 'series' and ':' in content_id:
        parts = content_id.split(':')
        try:
            episode = int(parts[-1])
        except (ValueError, IndexError):
            episode = None
        if len(parts) >= 2:
            try:
                season = int(parts[-2])
            except ValueError:
                season = None
    
    result = {
        'type': 'none',
        'subtitle': None,
        'provider_name': None,
        'provider_subtitle_id': None,
        'provider_metadata': None,
        'details': None,
        'auto': False,
        'user_vote_value': None,
        'user_selection_record': None
    }
    
    # 1. User Selection
    user_selection = await _get_user_selection(user, content_id, video_hash, lang)
    result['user_selection_record'] = user_selection
    
    if user_selection:
        if user_selection.selected_subtitle_id:
            result.update({
                'type': 'local',
                'subtitle': user_selection.selected_subtitle,
                'user_vote_value': await _get_user_vote(user, user_selection.selected_subtitle_id)
            })
            elapsed = time.time() - func_start
            current_app.logger.debug(f"[TIMING] get_active_subtitle_details: {elapsed:.3f}s (user selection local)")
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
                    'forced': details.get('forced', False),
                    'moviehash_match': details.get('hash_match', False),
                    'url': details.get('url', '')
                })
                elapsed = time.time() - func_start
                current_app.logger.debug(f"[TIMING] get_active_subtitle_details: {elapsed:.3f}s (user selection provider)")
                return result
    
    # 2. Local by hash
    if video_hash:
        local_sub = await _find_local_by_hash(content_id, video_hash, lang, user)
        if local_sub:
            result.update({
                'type': 'local',
                'subtitle': local_sub,
                'auto': True,
                'user_vote_value': await _get_user_vote(user, local_sub.id)
            })
            elapsed = time.time() - func_start
            current_app.logger.debug(f"[TIMING] get_active_subtitle_details: {elapsed:.3f}s (local by hash)")
            return result
    
    # 3. Providers by hash
    if video_hash:
        provider_result = await _search_providers_by_hash(user, imdb_id, video_hash, content_type, lang, season, episode, cached_provider_results)
        if provider_result:
            result.update(provider_result)
            result['auto'] = True
            elapsed = time.time() - func_start
            current_app.logger.debug(f"[TIMING] get_active_subtitle_details: {elapsed:.3f}s (provider by hash)")
            return result
    
    # 4. Best match by filename
    if video_filename:
        best_match = await _find_best_match_by_filename(user, content_id, imdb_id, video_filename, content_type, lang, season, episode, cached_provider_results)
        if best_match:
            result.update(best_match)
            result['auto'] = True
            elapsed = time.time() - func_start
            current_app.logger.debug(f"[TIMING] get_active_subtitle_details: {elapsed:.3f}s (best match by filename)")
            return result
    
    # 5. Fallback
    fallback = await _find_fallback_subtitle(user, content_id, imdb_id, content_type, lang, season, episode, cached_provider_results)
    if fallback:
        result.update(fallback)
        result['auto'] = True
        elapsed = time.time() - func_start
        current_app.logger.debug(f"[TIMING] get_active_subtitle_details: {elapsed:.3f}s (fallback)")
        return result
    
    elapsed = time.time() - func_start
    current_app.logger.debug(f"[TIMING] get_active_subtitle_details: {elapsed:.3f}s (no match)")
    return result


async def _get_user_selection(user, content_id, video_hash, lang):
    async with async_session_maker() as session:
        # Normalize video_hash: None -> ''
        video_hash = video_hash or ''
        
        stmt = select(UserSubtitleSelection).filter_by(
            user_id=user.id,
            content_id=content_id,
            video_hash=video_hash,
            language=lang
        ).options(selectinload(UserSubtitleSelection.selected_subtitle).selectinload(Subtitle.uploader)).limit(1)
        
        result = await session.execute(stmt)
        selection = result.scalar_one_or_none()
        if selection:
            return selection
        
        # Fallback: try with empty hash if we searched with a specific hash
        if video_hash:
            stmt_fallback = select(UserSubtitleSelection).filter_by(
                user_id=user.id,
                content_id=content_id,
                video_hash='',
                language=lang
            ).options(selectinload(UserSubtitleSelection.selected_subtitle).selectinload(Subtitle.uploader)).limit(1)
            result = await session.execute(stmt_fallback)
            return result.scalar_one_or_none()
        
        return None


async def _get_user_vote(user, subtitle_id):
    async with async_session_maker() as session:
        result = await session.execute(
            select(SubtitleVote).filter_by(user_id=user.id, subtitle_id=subtitle_id)
        )
        vote = result.scalar_one_or_none()
        return vote.vote_value if vote else None


async def _find_local_by_hash(content_id, video_hash, lang, user):
    async with async_session_maker() as session:
        result = await session.execute(
            select(Subtitle).options(selectinload(Subtitle.uploader)).filter_by(
                content_id=content_id,
                language=lang,
                video_hash=video_hash
            ).order_by(Subtitle.votes.desc())
        )
        subs = result.scalars().all()
        if not subs:
            return None
        if user.prioritize_forced_subtitles:
            forced = [s for s in subs if s.forced]
            return forced[0] if forced else subs[0]
        return subs[0]


async def _search_providers_by_hash(user, imdb_id, video_hash, content_type, lang, season=None, episode=None, cached_results=None):
    """Search for hash match from cache or live search"""
    if cached_results:
        # Collect all hash matches
        hash_matches = []
        for provider_name, results in cached_results.items():
            for result in results:
                if result.language == lang and result.metadata and result.metadata.get('hash_match'):
                    hash_matches.append((provider_name, result))
        
        # Prioritize forced if user setting enabled
        if hash_matches:
            if user.prioritize_forced_subtitles:
                # Sort: forced first, then by rating/downloads
                hash_matches.sort(key=lambda x: (
                    not x[1].forced,  # False (forced) comes before True (not forced)
                    -(x[1].rating or 0),
                    -(x[1].download_count or 0)
                ))
            
            provider_name, result = hash_matches[0]
            return {
                'type': f'{provider_name}_auto',
                'provider_name': provider_name,
                'provider_subtitle_id': result.subtitle_id,
                'provider_metadata': {'release_name': result.release_name, 'uploader': result.uploader, 'hash_match': True},
                'details': {'file_id': result.subtitle_id, 'release_name': result.release_name},
                'release_name': result.release_name,
                'uploader': result.uploader,
                'rating': result.rating,
                'download_count': result.download_count,
                'hearing_impaired': result.hearing_impaired,
                'ai_translated': result.ai_translated,
                'forced': result.forced,
                'moviehash_match': True,
                'url': result.metadata.get('url', '') if result.metadata else ''
            }
        # If we have cached results but no hash match, don't do another search
        return None
    
    if not imdb_id:
        return None
    
    try:
        from ..providers.registry import ProviderRegistry
        from ..lib.provider_async import search_providers_parallel
        active_providers = await ProviderRegistry.get_active_for_user(user)
        active_providers = [p for p in active_providers if p.supports_hash_matching]
        
        if not active_providers:
            return None
        
        search_params = {
            'imdb_id': imdb_id,
            'video_hash': video_hash,
            'languages': [lang],
            'season': season,
            'episode': episode,
            'content_type': content_type
        }
        
        results_by_provider = await search_providers_parallel(user, active_providers, search_params, timeout=8)
        
        # Collect all hash matches
        hash_matches = []
        for provider_name, results in results_by_provider.items():
            for result in results:
                if result.metadata and result.metadata.get('hash_match'):
                    hash_matches.append((provider_name, result))
        
        # Prioritize forced if user setting enabled
        if hash_matches:
            if user.prioritize_forced_subtitles:
                hash_matches.sort(key=lambda x: (
                    not x[1].forced,
                    -(x[1].rating or 0),
                    -(x[1].download_count or 0)
                ))
            
            provider_name, result = hash_matches[0]
            return {
                'type': f'{provider_name}_auto',
                'provider_name': provider_name,
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
                'forced': result.forced,
                'moviehash_match': result.metadata.get('hash_match', False),
                'url': result.metadata.get('url', '') if result.metadata else ''
            }
    except Exception as e:
        current_app.logger.warning(f"Error in provider hash search: {e}")
    return None


async def _find_best_match_by_filename(user, content_id, imdb_id, video_filename, content_type, lang, season=None, episode=None, cached_results=None):
    """Find best match by filename from cache or live search"""
    candidates = []
    
    # Local
    async with async_session_maker() as session:
        result = await session.execute(
            select(Subtitle).options(selectinload(Subtitle.uploader)).filter_by(content_id=content_id, language=lang)
        )
        local_subs = result.scalars().all()
        
    for sub in local_subs:
        score = calculate_filename_similarity(video_filename, sub.version_info)
        if score > 0:
            candidates.append({'type': 'local', 'subtitle': sub, 'score': score})
    
    # Providers (cached or live)
    if cached_results:
        for provider_name, results in cached_results.items():
            for result in results:
                if result.language == lang:
                    score = calculate_filename_similarity(video_filename, result.release_name)
                    if result.ai_translated:
                        score -= 0.05
                    if score > 0:
                        candidates.append({
                            'type': 'provider',
                            'provider_name': provider_name,
                            'provider_subtitle_id': result.subtitle_id,
                            'provider_metadata': {'release_name': result.release_name},
                            'score': score,
                            'release_name': result.release_name,
                            'uploader': result.uploader,
                            'rating': result.rating,
                            'download_count': result.download_count,
                            'hearing_impaired': result.hearing_impaired,
                            'ai_translated': result.ai_translated,
                            'forced': result.forced,
                            'moviehash_match': result.metadata.get('hash_match', False) if result.metadata else False,
                            'url': result.metadata.get('url', '') if result.metadata else ''
                        })
    elif imdb_id:
        try:
            from ..providers.registry import ProviderRegistry
            from ..lib.provider_async import search_providers_parallel
            active_providers = await ProviderRegistry.get_active_for_user(user)
            
            search_params = {
                'imdb_id': imdb_id,
                'languages': [lang],
                'season': season,
                'episode': episode,
                'content_type': content_type,
                'video_filename': video_filename
            }
            
            results_by_provider = await search_providers_parallel(user, active_providers, search_params, timeout=8)
            
            for provider_name, results in results_by_provider.items():
                for result in results:
                    score = calculate_filename_similarity(video_filename, result.release_name)
                    if result.ai_translated:
                        score -= 0.05
                    if score > 0:
                        candidates.append({
                            'type': 'provider',
                            'provider_name': provider_name,
                            'provider_subtitle_id': result.subtitle_id,
                            'provider_metadata': {'release_name': result.release_name},
                            'score': score,
                            'release_name': result.release_name,
                            'uploader': result.uploader,
                            'rating': result.rating,
                            'download_count': result.download_count,
                            'hearing_impaired': result.hearing_impaired,
                            'ai_translated': result.ai_translated,
                            'forced': result.forced,
                            'moviehash_match': result.metadata.get('hash_match', False) if result.metadata else False,
                            'url': result.metadata.get('url', '') if result.metadata else ''
                        })
            gc.collect()
        except:
            pass
    
    if not candidates:
        return None
    
    if user.prioritize_forced_subtitles:
        candidates.sort(key=lambda c: (not c.get('forced', False), -c['score']))
    else:
        candidates.sort(key=lambda c: c['score'], reverse=True)
    
    best = candidates[0]
    
    if best['type'] == 'local':
        return {
            'type': 'local',
            'subtitle': best['subtitle'],
            'user_vote_value': await _get_user_vote(user, best['subtitle'].id)
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
            'forced': best.get('forced', False),
            'moviehash_match': best.get('moviehash_match', False),
            'url': best.get('url', '')
        }


async def _find_fallback_subtitle(user, content_id, imdb_id, content_type, lang, season=None, episode=None, cached_results=None):
    """Find fallback subtitle from cache or live search"""
    # Local first
    async with async_session_maker() as session:
        result = await session.execute(
            select(Subtitle).options(selectinload(Subtitle.uploader)).filter_by(content_id=content_id, language=lang).order_by(Subtitle.votes.desc()).limit(1)
        )
        local_sub = result.scalar_one_or_none()
        
    if local_sub:
        return {
            'type': 'local',
            'subtitle': local_sub,
            'user_vote_value': await _get_user_vote(user, local_sub.id)
        }
    
    if not imdb_id and not cached_results:
        return None
    
    # Get results (cached or live)
    if cached_results:
        results_by_provider = {k: [r for r in v if r.language == lang] for k, v in cached_results.items()}
    else:
        try:
            from ..providers.registry import ProviderRegistry
            from ..lib.provider_async import search_providers_parallel
            active_providers = await ProviderRegistry.get_active_for_user(user)
            
            search_params = {
                'imdb_id': imdb_id,
                'languages': [lang],
                'season': season,
                'episode': episode,
                'content_type': content_type
            }
            
            results_by_provider = await search_providers_parallel(user, active_providers, search_params, timeout=8)
            results_by_provider = {k: [r for r in v if r.language == lang] for k, v in results_by_provider.items()}
        except:
            return None
    
    # Process results
    for provider_name, lang_results in results_by_provider.items():
        if not lang_results:
            continue
        
        if episode:
            matching = []
            matching_ep_only = []
            
            for r in lang_results:
                parts = extract_release_components(r.release_name)
                if season and parts['season_episode'] == f"s{season:02d}e{episode:02d}":
                    matching.append(r)
                else:
                    ep_patterns = [f' {episode:03d}', f'-{episode:03d}', f' {episode:02d} ', f'-{episode:02d}-']
                    if any(pattern in r.release_name.lower() for pattern in ep_patterns):
                        matching_ep_only.append(r)
            
            candidates = matching if matching else matching_ep_only
            if candidates:
                if user.prioritize_forced_subtitles:
                    forced = [r for r in candidates if r.forced]
                    if forced:
                        non_ai = [r for r in forced if not r.ai_translated]
                        chosen = non_ai[0] if non_ai else forced[0]
                    else:
                        non_ai = [r for r in candidates if not r.ai_translated]
                        chosen = non_ai[0] if non_ai else candidates[0]
                else:
                    non_ai = [r for r in candidates if not r.ai_translated]
                    chosen = non_ai[0] if non_ai else candidates[0]
            else:
                if user.prioritize_forced_subtitles:
                    forced = [r for r in lang_results if r.forced]
                    if forced:
                        non_ai = [r for r in forced if not r.ai_translated]
                        chosen = non_ai[0] if non_ai else forced[0]
                    else:
                        non_ai = [r for r in lang_results if not r.ai_translated]
                        chosen = non_ai[0] if non_ai else (lang_results[0] if lang_results else None)
                else:
                    non_ai = [r for r in lang_results if not r.ai_translated]
                    chosen = non_ai[0] if non_ai else (lang_results[0] if lang_results else None)
        else:
            if user.prioritize_forced_subtitles:
                forced = [r for r in lang_results if r.forced]
                if forced:
                    non_ai = [r for r in forced if not r.ai_translated]
                    chosen = non_ai[0] if non_ai else forced[0]
                else:
                    non_ai = [r for r in lang_results if not r.ai_translated]
                    chosen = non_ai[0] if non_ai else (lang_results[0] if lang_results else None)
            else:
                non_ai = [r for r in lang_results if not r.ai_translated]
                chosen = non_ai[0] if non_ai else (lang_results[0] if lang_results else None)
        
        if chosen:
            result = {
                'type': f'{provider_name}_auto',
                'provider_name': provider_name,
                'provider_subtitle_id': chosen.subtitle_id,
                'provider_metadata': {'release_name': chosen.release_name},
                'details': {'file_id': chosen.subtitle_id},
                'release_name': chosen.release_name,
                'uploader': chosen.uploader,
                'rating': chosen.rating,
                'download_count': chosen.download_count,
                'hearing_impaired': chosen.hearing_impaired,
                'ai_translated': chosen.ai_translated,
                'forced': chosen.forced,
                'moviehash_match': chosen.metadata.get('hash_match', False) if chosen.metadata else False,
                'url': chosen.metadata.get('url', '') if chosen.metadata else ''
            }
            if not cached_results:
                gc.collect()
            return result
    
    if not cached_results:
        gc.collect()
    return None


async def get_vtt_content(subtitle):
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
        
        async with aiohttp.ClientSession() as session:
            async with session.get(cloudinary_url, timeout=aiohttp.ClientTimeout(total=10)) as r:
                r.raise_for_status()
                return await r.text()
    else:
        import aiofiles
        local_full_path = os.path.join(current_app.config['UPLOAD_FOLDER'], subtitle.file_path)
        if not os.path.exists(local_full_path):
            raise FileNotFoundError("Local subtitle file not found")
        
        async with aiofiles.open(local_full_path, 'r', encoding='utf-8') as f:
            return await f.read()


def generate_vtt_message(message: str) -> str:
    """Generates a simple VTT file content displaying a message."""
    return f"WEBVTT\n\n00:00:00.000 --> 00:00:08.000\n{message}"


def extract_subtitle_from_zip(zip_content: bytes, episode: int = None):
    """
    Extracts subtitle file from ZIP or RAR archive.
    If episode is provided, tries to find file matching episode number.
    Returns tuple: (subtitle_content: bytes, filename: str, extension: str)
    """
    subtitle_extensions = ['.srt', '.vtt', '.ass', '.ssa', '.sub', '.smi']
    episode_patterns = [
        f'e{episode:02d}',
        f' {episode:02d} ',
        f'-{episode:02d}-',
        f'.{episode:02d}.'
    ] if episode is not None else []
    
    def find_and_extract(archive_files, read_func, archive_type):
        """Common logic for finding and extracting subtitle from archive"""
        subtitle_files = [f for f in archive_files if os.path.splitext(f if isinstance(f, str) else f.filename)[1].lower() in subtitle_extensions]
        
        if not subtitle_files:
            all_names = [f if isinstance(f, str) else f.filename for f in archive_files]
            raise ValueError(f"No subtitle file found in {archive_type} archive. Files in archive: {all_names}. Episode filter: {episode}")
        
        if len(subtitle_files) == 1:
            chosen = subtitle_files[0]
            fname = chosen if isinstance(chosen, str) else chosen.filename
            return (read_func(chosen), fname, os.path.splitext(fname)[1].lower())
        
        if episode_patterns:
            for f in subtitle_files:
                fname = f if isinstance(f, str) else f.filename
                if any(pattern in fname.lower() for pattern in episode_patterns):
                    return (read_func(f), fname, os.path.splitext(fname)[1].lower())
        
        chosen = subtitle_files[0]
        fname = chosen if isinstance(chosen, str) else chosen.filename
        return (read_func(chosen), fname, os.path.splitext(fname)[1].lower())
    
    # Check if RAR
    if zip_content[:4] == b'Rar!':
        try:
            rar_buffer = io.BytesIO(zip_content)
            with rarfile.RarFile(rar_buffer) as rf:
                result = find_and_extract(rf.namelist(), rf.read, 'RAR')
                del rar_buffer
                return result
        except rarfile.Error as e:
            raise ValueError(f"Invalid RAR file: {e}")
        finally:
            gc.collect()
    
    # Handle ZIP
    try:
        zip_buffer = io.BytesIO(zip_content)
        with zipfile.ZipFile(zip_buffer) as zf:
            result = find_and_extract(zf.filelist, lambda f: zf.read(f), 'ZIP')
            del zip_buffer
            return result
    except zipfile.BadZipFile:
        raise ValueError(f"Invalid ZIP file. First 20 bytes: {zip_content[:20].hex() if len(zip_content) >= 20 else zip_content.hex()}")
    finally:
        gc.collect()


async def process_subtitle_content(content: bytes, extension: str, encoding=None):
    """
    Processes subtitle content and returns both VTT and original (if ASS/SSA).
    Returns dict: {'vtt': str, 'original': str or None, 'original_format': str or None}
    """
    from ..lib.subtitles import convert_to_vtt
    
    # Convert to VTT
    vtt_content = await convert_to_vtt(content, extension.lstrip('.'), encoding=encoding)
    
    # If ASS/SSA, also keep original
    if extension.lower() in ['.ass', '.ssa']:
        original_content = None
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
        
        result = {
            'vtt': vtt_content,
            'original': original_content,
            'original_format': extension.lstrip('.')
        }
        del content
        gc.collect()
        return result
    
    del content
    return {
        'vtt': vtt_content,
        'original': None,
        'original_format': None
    }



async def check_opensubtitles_token(user):
    """Check if OpenSubtitles token is valid, flash warning if expired."""
    from quart import flash
    from quart_babel import gettext as _
    try:
        from ..providers.registry import ProviderRegistry
        provider = ProviderRegistry.get('opensubtitles')
        if provider and await provider.is_authenticated(user):
            is_valid = await provider.check_token_validity(user)
            if not is_valid:
                await flash(_('OpenSubtitles authentication expired. Please log in again in account settings.'), 'warning')
    except Exception as e:
        current_app.logger.debug(f"OpenSubtitles token check error: {e}")
