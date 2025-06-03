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


def search_opensubtitles(user, content_id, video_hash=None, content_type=None, metadata=None):
    """
    Searches for subtitles on OpenSubtitles based on provided parameters.

    Args:
        user (User): The current user object with OpenSubtitles credentials
        content_id (str): The content ID (e.g., IMDB ID, or IMDB_ID:S:E)
        video_hash (str, optional): The hash of the video file
        content_type (str, optional): 'movie', 'series', or 'episode'
        metadata (dict, optional): Additional metadata with title, season, episode info

    Returns:
        list: List of OpenSubtitles search results, or empty list if no results/error
    """
    from ..lib import opensubtitles_client
    from iso639 import Lang

    # Check if user has OpenSubtitles integration active
    if not (user.opensubtitles_active and user.opensubtitles_token and user.opensubtitles_base_url):
        current_app.logger.info(f"User {user.username} doesn't have active OpenSubtitles integration")
        return []

    # Convert user language to OpenSubtitles format
    if user.preferred_language == 'pob':
        os_language = 'pt-br'
    elif user.preferred_language == 'por':
        os_language = 'pt-pt'
    else:
        os_language = Lang(user.preferred_language).pt1

    try:
        # Build search parameters
        os_search_params = {
            'languages': os_language
        }
        if video_hash:
            os_search_params['moviehash'] = video_hash

        # Add IMDB ID if available
        imdb_id_part = content_id.split(':')[0]
        if imdb_id_part.startswith("tt"):
            os_search_params['imdb_id'] = imdb_id_part

        # Determine content type and add season/episode info
        if ':' in content_id and (content_type == 'series' or 'episode' in str(content_type)):
            parts = content_id.split(':')
            os_search_params['type'] = 'episode'
            if len(parts) >= 2:
                try:
                    os_search_params['season_number'] = int(parts[1])
                except ValueError:
                    pass
            if len(parts) >= 3:
                try:
                    os_search_params['episode_number'] = int(parts[2])
                except ValueError:
                    pass
        elif content_type == 'movie':
            os_search_params['type'] = 'movie'

        # Add query as fallback if no IMDB ID and no hash
        if not os_search_params.get('imdb_id') and not video_hash and metadata and metadata.get('title'):
            os_search_params['query'] = metadata.get('title')

        # Ensure we have enough parameters for a meaningful search
        if not (os_search_params.get('imdb_id') or os_search_params.get('moviehash') or os_search_params.get('query')):
            current_app.logger.info("Not enough parameters for OpenSubtitles search")
            return []

        current_app.logger.info(f"Searching OpenSubtitles with params: {os_search_params}")

        # Execute search
        os_results = opensubtitles_client.search_subtitles(**os_search_params, user=user)

        if os_results and os_results.get('data'):
            current_app.logger.info(f"Found {len(os_results['data'])} OpenSubtitles results")
            return os_results['data']
        else:
            current_app.logger.info("No OpenSubtitles results found")
            return []

    except opensubtitles_client.OpenSubtitlesError as e:
        current_app.logger.error(f"OpenSubtitles API error during search: {e}")
        return []
    except Exception as e:
        current_app.logger.error(f"Unexpected error during OpenSubtitles search: {e}", exc_info=True)
        return []


def get_active_subtitle_details(user, content_id, video_hash=None, content_type=None, video_filename=None,
                                metadata=None):
    active_details = {'type': 'none', 'subtitle': None, 'details': None, 'user_vote_value': None,
                      'user_selection_record': None, 'auto': False}

    current_app.logger.debug(
        f"get_active_subtitle_details called for user {user.id}, content_id: {content_id}, "
        f"video_hash: {video_hash}, video_filename: {video_filename}"
    )

    # 1. User selection
    user_selection_query = UserSubtitleSelection.query.filter_by(
        user_id=user.id,
        content_id=content_id
    )
    if video_hash:
        user_selection_query = user_selection_query.filter_by(video_hash=video_hash)
    else:
        user_selection_query = user_selection_query.filter(UserSubtitleSelection.video_hash.is_(None))

    user_selection = user_selection_query.options(
        joinedload(UserSubtitleSelection.selected_subtitle).joinedload(Subtitle.uploader)
    ).first()
    active_details['user_selection_record'] = user_selection

    if user_selection:
        if user_selection.selected_subtitle_id and user_selection.selected_subtitle:
            active_details['type'] = 'local'
            active_details['subtitle'] = user_selection.selected_subtitle
            user_vote = SubtitleVote.query.filter_by(
                user_id=user.id,
                subtitle_id=active_details['subtitle'].id
            ).first()
            if user_vote: active_details['user_vote_value'] = user_vote.vote_value
            current_app.logger.info(
                f"User selection (local): {active_details['subtitle'].id} for {content_id}, hash context: {video_hash}")
            return active_details

        if user.opensubtitles_active and user_selection.selected_external_file_id and user_selection.external_details_json:
            active_details['type'] = 'opensubtitles_selection'
            active_details['details'] = user_selection.external_details_json
            current_app.logger.info(
                f"User selection (OS): {user_selection.selected_external_file_id} for {content_id}, hash context: {video_hash}")
            return active_details

    os_search_results = None  # Store OS search results to avoid multiple calls

    # 2. Local subtitles with matching video_hash
    if video_hash:
        current_app.logger.debug(f"Step 2: Checking local by hash: {video_hash} for {content_id}")
        local_sub_by_hash = Subtitle.query.filter_by(
            content_id=content_id,
            language=user.preferred_language,
            video_hash=video_hash
        ).order_by(Subtitle.votes.desc()).options(joinedload(Subtitle.uploader)).first()

        if local_sub_by_hash:
            active_details.update({'type': 'local', 'auto': True, 'subtitle': local_sub_by_hash})
            user_vote = SubtitleVote.query.filter_by(user_id=user.id, subtitle_id=local_sub_by_hash.id).first()
            if user_vote: active_details['user_vote_value'] = user_vote.vote_value
            current_app.logger.info(f"Auto-selected local (hash match): {local_sub_by_hash.id} for {content_id}")
            return active_details

    # 3. OpenSubtitles with matching video_hash
    if video_hash and user.opensubtitles_active:
        current_app.logger.debug(f"Step 3: Checking OS by hash: {video_hash} for {content_id}")
        os_search_results = search_opensubtitles(user, content_id, video_hash, content_type, metadata)
        for item in os_search_results:
            attrs = item.get('attributes', {})
            files = attrs.get('files', [])
            if attrs.get('moviehash_match') and files and files[0].get('file_id'):
                active_details.update({
                    'type': 'opensubtitles_auto', 'auto': True,
                    'details': {
                        'file_id': files[0].get('file_id'), 'release_name': files[0].get('file_name'),
                        'language': attrs.get('language'), 'moviehash_match': True,
                        'ai_translated': attrs.get('ai_translated') or attrs.get('machine_translated'),
                        'uploader': attrs.get('uploader', {}).get('name'), 'url': attrs.get('url')
                    }
                })
                current_app.logger.info(f"Auto-selected OS (hash match): {files[0].get('file_id')} for {content_id}")
                return active_details

    # 4. Best Match (if `video_filename` is available)
    if video_filename:
        current_app.logger.debug(f"Step 4: Checking by filename: {video_filename} for {content_id}")
        candidates = []
        min_similarity_threshold = 0.3

        # A. Local
        all_local_subs = Subtitle.query.filter_by(
            content_id=content_id, language=user.preferred_language
        ).options(joinedload(Subtitle.uploader)).all()

        for sub in all_local_subs:
            score = calculate_filename_similarity(video_filename, sub.version_info)
            if score >= min_similarity_threshold:
                candidates.append({'type': 'local', 'data': sub, 'score': score, 'name': sub.version_info or ""})

        # B. OpenSubtitles
        if user.opensubtitles_active:
            if os_search_results is None:
                current_app.logger.debug("Step 4: Performing general OS search for filename matching.")
                os_search_results = search_opensubtitles(user, content_id, None, content_type, metadata)

            for item in os_search_results:
                attrs = item.get('attributes', {})
                files = attrs.get('files', [])
                if not (files and files[0].get('file_id')): continue

                release_name = files[0].get('file_name')
                score = calculate_filename_similarity(video_filename, release_name)
                if attrs.get('ai_translated') or attrs.get('machine_translated'): score -= 0.05

                if score >= min_similarity_threshold:
                    candidates.append(
                        {'type': 'opensubtitles_auto', 'data': item, 'score': score, 'name': release_name or ""})

        if candidates:
            candidates.sort(key=lambda c: c['score'], reverse=True)
            best_match = candidates[0]
            current_app.logger.info(
                f"Auto-selected by filename similarity (score: {best_match['score']:.2f}): {best_match['name']} ({best_match['type']}) for {content_id}")

            active_details['auto'] = True
            if best_match['type'] == 'local':
                active_details.update({'type': 'local', 'subtitle': best_match['data']})
                user_vote = SubtitleVote.query.filter_by(user_id=user.id, subtitle_id=best_match['data'].id).first()
                if user_vote: active_details['user_vote_value'] = user_vote.vote_value
            else:  # opensubtitles_auto
                attrs = best_match['data'].get('attributes', {})
                files = attrs.get('files', [])
                active_details.update({
                    'type': 'opensubtitles_auto',
                    'details': {
                        'file_id': files[0].get('file_id'), 'release_name': files[0].get('file_name'),
                        'language': user.preferred_language, 'moviehash_match': attrs.get('moviehash_match', False),
                        'ai_translated': attrs.get('ai_translated') or attrs.get('machine_translated'),
                        'uploader': attrs.get('uploader', {}).get('name'), 'url': attrs.get('url')
                    }
                })
            return active_details

    # 5. Fallback: when no video_hash
    if not video_hash:
        current_app.logger.debug(f"Step 5: Fallback (no hash) for {content_id}")
        # 5a. Local subtitles without video_hash
        local_no_hash_subs = (Subtitle.query.filter_by(content_id=content_id, language=user.preferred_language)
                              .filter(Subtitle.video_hash.is_(None)).order_by(Subtitle.votes.desc())
                              .options(joinedload(Subtitle.uploader)).all())

        if local_no_hash_subs:
            chosen_local_sub = local_no_hash_subs[0]
            active_details.update({'type': 'local', 'auto': True, 'subtitle': chosen_local_sub})
            user_vote = SubtitleVote.query.filter_by(user_id=user.id, subtitle_id=chosen_local_sub.id).first()
            if user_vote: active_details['user_vote_value'] = user_vote.vote_value
            current_app.logger.info(
                f"Auto-selected local (fallback, no hash assigned): {chosen_local_sub.id} for {content_id}")
            return active_details

        # 5b. Any other local subtitles
        all_local_subs_fallback = (Subtitle.query.filter_by(content_id=content_id, language=user.preferred_language)
                                   .order_by(Subtitle.votes.desc()).options(joinedload(Subtitle.uploader)).first())

        if all_local_subs_fallback:
            active_details.update({'type': 'local', 'auto': True, 'subtitle': all_local_subs_fallback})
            user_vote = SubtitleVote.query.filter_by(user_id=user.id, subtitle_id=all_local_subs_fallback.id).first()
            if user_vote: active_details['user_vote_value'] = user_vote.vote_value
            current_app.logger.info(
                f"Auto-selected local (fallback, highest votes/first): {all_local_subs_fallback.id} for {content_id}")
            return active_details

    # 6. Fallback OpenSubtitles
    if user.opensubtitles_active:
        current_app.logger.debug(f"Step 6: General OpenSubtitles fallback for {content_id}")
        if os_search_results is None:
            current_app.logger.debug("Step 6: Performing general OS search for final fallback.")
            os_search_results = search_opensubtitles(user, content_id, None, content_type, metadata)

        not_ai = []
        ai = []
        for item in os_search_results:
            attrs = item.get('attributes', {})
            files = attrs.get('files', [])
            if not (files and files[0].get('file_id')): continue
            detail = {
                'file_id': files[0].get('file_id'), 'release_name': files[0].get('file_name'),
                'language': user.preferred_language, 'moviehash_match': attrs.get('moviehash_match', False),
                'ai_translated': attrs.get('ai_translated') or attrs.get('machine_translated'),
                'uploader': attrs.get('uploader', {}).get('name'), 'url': attrs.get('url')
            }
            if detail['ai_translated']:
                ai.append(detail)
            else:
                not_ai.append(detail)

        chosen_fallback_details = None
        if not_ai:
            chosen_fallback_details = not_ai[0]
        elif ai:
            chosen_fallback_details = ai[0]

        if chosen_fallback_details:
            active_details.update({'type': 'opensubtitles_auto', 'auto': True, 'details': chosen_fallback_details})
            current_app.logger.info(
                f"Auto-selected OS (general fallback, type: {'AI' if chosen_fallback_details['ai_translated'] else 'Not AI'}): {chosen_fallback_details['file_id']} for {content_id}")
            return active_details

    current_app.logger.info(f"No suitable subtitle found for {content_id} after all steps.")
    return active_details


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
