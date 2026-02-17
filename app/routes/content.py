from quart_babel import gettext as _
from quart import Blueprint, render_template, flash, current_app, url_for
from quart_auth import login_required, current_user
from markupsafe import Markup
from sqlalchemy.orm import joinedload
from sqlalchemy import select
from ..models import UserActivity, Subtitle, UserSubtitleSelection, SubtitleVote, User
from iso639 import Lang
from ..lib.metadata import get_metadata
from ..languages import LANGUAGES, LANGUAGE_DICT
from ..extensions import async_session_maker
from .utils import get_active_subtitle_details, check_opensubtitles_token

content_bp = Blueprint('content', __name__)


@content_bp.route('/content/<uuid:activity_id>')
@login_required
async def content_detail(activity_id):
    """Displays details for a specific content item based on user activity."""
    import time
    start_time = time.time()
    user_id = (current_user.auth_id)
    
    # Fetch user and check OpenSubtitles token
    async with async_session_maker() as session:
        result = await session.execute(select(User).filter_by(id=user_id))
        user = result.scalar_one_or_none()
        if user:
            await check_opensubtitles_token(user)
    
    # Fetch the specific activity ensuring it belongs to the current user
    async with async_session_maker() as session:
        result = await session.execute(
            select(UserActivity).filter_by(id=activity_id, user_id=user_id)
        )
        activity = result.scalar_one_or_none()
        if not activity:
            from quart import abort
            abort(404)

    # Parse season/episode if applicable
    season = None
    episode = None

    # Fetch metadata using the helper
    current_app.logger.debug(f"[TIMING] Activity fetched in {time.time() - start_time:.2f}s")
    metadata = await get_metadata(activity.content_id, activity.content_type)

    # Add display_title to metadata and extract season/episode
    if metadata:
        title = metadata.get('title', activity.content_id)
        if metadata.get('season') is not None and metadata.get('episode') is not None:
            title = f"{title} S{metadata['season']:02d}E{metadata['episode']:02d}"
        elif metadata.get('season') is not None:
            title = f"{title} S{metadata['season']:02d}"
        if metadata.get('year'):
            title = f"{title} ({metadata['year']})"
        if metadata.get('season'):
            season = metadata['season']
        if metadata.get('episode'):
            episode = metadata['episode']
        metadata['display_title'] = title
    else:
        if activity.content_type == 'series':
            content_parts = activity.content_id.split(':')
            try:
                if activity.content_id.startswith('kitsu:'):
                    if len(content_parts) == 3:
                        episode = int(content_parts[2])
                elif len(content_parts) == 3:
                    season = int(content_parts[1])
                    episode = int(content_parts[2])
                elif len(content_parts) == 2:
                    season = 1
                    episode = int(content_parts[1])
            except ValueError:
                current_app.logger.warning(f"Could not parse season/episode from content_id: {activity.content_id}")
                season = None
                episode = None

    active_details_by_lang = {}
    all_subs_matching_hash = []
    all_subs_other_hash = []
    all_subs_no_hash = []
    
    async with async_session_maker() as session:
        result = await session.execute(select(User).filter_by(id=user_id))
        user = result.scalar_one_or_none()
        preferred_languages = user.preferred_languages if user else []
    
    provider_results_by_lang = {lang: [] for lang in preferred_languages}
    all_subtitle_ids_for_voting = set()

    # Fetch all available local subtitles for all preferred languages in one query
    async with async_session_maker() as session:
        result = await session.execute(
            select(Subtitle)
            .filter(
                Subtitle.content_id == activity.content_id,
                Subtitle.language.in_(preferred_languages)
            )
            .options(joinedload(Subtitle.uploader))
        )
        all_local_subs = result.scalars().all()

    # Group local subtitles by language and hash
    temp_grouped_local_subs = {lang: {'matching_hash': [], 'other_hash': [], 'no_hash': []} for lang in preferred_languages}
    for sub in all_local_subs:
        if sub.language in temp_grouped_local_subs:
            if activity.video_hash and sub.video_hash == activity.video_hash:
                temp_grouped_local_subs[sub.language]['matching_hash'].append(sub)
                all_subs_matching_hash.append(sub)
            elif sub.video_hash is None:
                temp_grouped_local_subs[sub.language]['no_hash'].append(sub)
                all_subs_no_hash.append(sub)
            else:
                temp_grouped_local_subs[sub.language]['other_hash'].append(sub)
                all_subs_other_hash.append(sub)
        all_subtitle_ids_for_voting.add(sub.id)

    # Determine imdb_id for provider search
    imdb_id = None
    search_query = None
    if activity.content_id.startswith('tt'):
        imdb_id = activity.content_id.split(':')[0]
    elif activity.content_id.startswith('kitsu:'):
        from ..lib.anime_mapping import get_imdb_from_kitsu
        kitsu_id = int(activity.content_id.split(':')[1])
        result = get_imdb_from_kitsu(kitsu_id)
        if result:
            imdb_id = result['imdb_id']
            if result['season']:
                season = result['season']
    elif activity.content_id.startswith('mal:'):
        from ..lib.anime_mapping import get_imdb_from_mal
        mal_id = int(activity.content_id.split(':')[1])
        result = get_imdb_from_mal(mal_id)
        if result:
            imdb_id = result['imdb_id']
            if result['season']:
                season = result['season']
    
    # Fallback to title search if no IMDb ID
    if not imdb_id and metadata and metadata.get('title'):
        import re
        search_query = metadata['title']
        search_query = re.split(r'\s+S\d+E\d+', search_query, flags=re.IGNORECASE)[0].strip()
        search_query = re.split(r'\s+-\s+Ep(?:isode)?\s+\d+', search_query, flags=re.IGNORECASE)[0].strip()
    
    # Single provider search for both active selection and display
    current_app.logger.debug(f"[TIMING] Metadata and prep done in {time.time() - start_time:.2f}s")
    provider_results_raw = {}
    if preferred_languages and (imdb_id or search_query):
        try:
            from ..providers.registry import ProviderRegistry
            from ..lib.provider_async import search_providers_parallel
            
            async with async_session_maker() as session:
                result = await session.execute(select(User).filter_by(id=user_id))
                user = result.scalar_one_or_none()
                active_providers = await ProviderRegistry.get_active_for_user(user)
            
            search_params = {
                'imdb_id': imdb_id,
                'query': search_query,
                'video_hash': activity.video_hash,
                'languages': preferred_languages,
                'season': season,
                'episode': episode,
                'content_type': activity.content_type,
                'video_filename': activity.video_filename
            }
            
            provider_results_raw = await search_providers_parallel(user, active_providers, search_params, timeout=10)
            current_app.logger.debug(f"[TIMING] Provider search done in {time.time() - start_time:.2f}s")
            
            # Process for display
            for provider_name, results in provider_results_raw.items():
                for result in results:
                    if result.language.lower() in provider_results_by_lang:
                        item = {
                            'provider_name': provider_name,
                            'attributes': {
                                'language': result.language,
                                'language_3letter': result.language,
                                'files': [{
                                    'file_id': result.subtitle_id,
                                    'file_name': result.release_name
                                }],
                                'uploader': {'name': result.uploader} if result.uploader else None,
                                'moviehash_match': result.metadata.get('hash_match', False) if result.metadata else False,
                                'ai_translated': result.ai_translated,
                                'machine_translated': False,
                                'ratings': result.rating,
                                'votes': None,
                                'download_count': result.download_count,
                                'hearing_impaired': result.hearing_impaired,
                                'forced': result.forced,
                                'url': result.metadata.get('url', '') if result.metadata else ''
                            }
                        }
                        provider_results_by_lang[result.language].append(item)
        except Exception as e:
            current_app.logger.error(f"Error fetching provider results: {e}", exc_info=True)
            await flash(_("An error occurred while searching for subtitles."), "warning")
    
    # Determine active subtitle for each language using cached provider results
    current_app.logger.debug(f"[TIMING] Before get_active_subtitle_details in {time.time() - start_time:.2f}s")
    async with async_session_maker() as session:
        result = await session.execute(select(User).filter_by(id=user_id))
        user = result.scalar_one_or_none()
        
        for lang_code in preferred_languages:
            active_subtitle_info = await get_active_subtitle_details(
                user,
                activity.content_id,
                activity.video_hash,
                activity.content_type,
                activity.video_filename,
                lang=lang_code,
                season=season,
                episode=episode,
                cached_provider_results=provider_results_raw
            )

            active_subtitle = None
            active_provider_details = None
            user_vote_value = None
            user_selection = active_subtitle_info.get('user_selection_record')
            auto_selected = False

            if active_subtitle_info:
                auto_selected = active_subtitle_info['auto']

            if active_subtitle_info['type'] == 'local':
                active_subtitle = active_subtitle_info['subtitle']
                user_vote_value = active_subtitle_info['user_vote_value']
                if active_subtitle:
                    all_subtitle_ids_for_voting.add(active_subtitle.id)
            elif active_subtitle_info['type'] and ('_selection' in active_subtitle_info['type'] or '_auto' in active_subtitle_info['type']):
                active_provider_details = active_subtitle_info

            active_details_by_lang[lang_code] = {
                'active_subtitle': active_subtitle,
                'active_provider_details': active_provider_details,
                'user_selection': user_selection,
                'user_vote_value': user_vote_value,
                'auto_selected': auto_selected
            }
    
    current_app.logger.debug(f"[TIMING] After get_active_subtitle_details in {time.time() - start_time:.2f}s")
    # Calculate has_any_user_selection
    has_any_user_selection = any(details.get('user_selection') is not None for details in active_details_by_lang.values())

    # Fetch all user votes for all collected subtitle IDs
    user_votes = {}
    if all_subtitle_ids_for_voting:
        async with async_session_maker() as session:
            result = await session.execute(
                select(SubtitleVote).filter(
                    SubtitleVote.user_id == user_id,
                    SubtitleVote.subtitle_id.in_(list(all_subtitle_ids_for_voting))
                )
            )
            votes = result.scalars().all()
            for vote in votes:
                user_votes[vote.subtitle_id] = vote.vote_value

    # Calculate has_provider_results
    has_provider_results = any(results for results in provider_results_by_lang.values())

    # Prepare preferred languages for display
    preferred_languages_display = ", ".join([LANGUAGE_DICT.get(lang_code, lang_code) for lang_code in preferred_languages])

    # Check if no providers are active and show info message
    try:
        from ..providers.registry import ProviderRegistry
        async with async_session_maker() as session:
            result = await session.execute(select(User).filter_by(id=user_id))
            user = result.scalar_one_or_none()
            active_providers = await ProviderRegistry.get_active_for_user(user)
            if not active_providers:
                await flash(Markup('You don\'t have any active provider connections. To fully utilize the addon features, <a href="{}" class="alert-link">activate providers in your account settings</a>.'.format(url_for('main.account_settings'))), 'info')
    except:
        pass

    # Pass context to the template
    context = {
        'activity': activity,
        'season': season,
        'episode': episode,
        'active_details_by_lang': active_details_by_lang,
        'all_subs_matching_hash': all_subs_matching_hash,
        'all_subs_other_hash': all_subs_other_hash,
        'all_subs_no_hash': all_subs_no_hash,
        'user_votes': user_votes,
        'language_list': LANGUAGES,
        'LANGUAGE_DICT': LANGUAGE_DICT,
        'metadata': metadata,
        'provider_results_by_lang': provider_results_by_lang,
        'preferred_languages': preferred_languages,
        'has_any_user_selection': has_any_user_selection,
        'has_provider_results': has_provider_results,
        'preferred_languages_display': preferred_languages_display
    }

    return await render_template('main/content_detail.html', **context)


