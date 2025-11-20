from flask import Blueprint, render_template, flash, current_app, url_for
from flask_login import login_required, current_user
from markupsafe import Markup
from sqlalchemy.orm import joinedload
from ..models import UserActivity, Subtitle, UserSubtitleSelection, SubtitleVote
from iso639 import Lang
from ..lib.metadata import get_metadata
from ..languages import LANGUAGES, LANGUAGE_DICT
from .utils import get_active_subtitle_details

content_bp = Blueprint('content', __name__)


@content_bp.route('/content/<uuid:activity_id>')
@login_required
def content_detail(activity_id):
    """Displays details for a specific content item based on user activity."""
    # Fetch the specific activity ensuring it belongs to the current user
    activity = UserActivity.query.filter_by(id=activity_id, user_id=current_user.id).first_or_404()

    # Parse season/episode if applicable
    season = None
    episode = None

    # Fetch metadata using the helper
    metadata = get_metadata(activity.content_id, activity.content_type)

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
            season = metadata['season']  # Keep as int
        if metadata.get('episode'):
            episode = metadata['episode']  # Keep as int
        metadata['display_title'] = title
    else:
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
                season = None
                episode = None

    active_details_by_lang = {}
    all_subs_matching_hash = []
    all_subs_other_hash = []
    all_subs_no_hash = []
    provider_results_by_lang = {lang: [] for lang in current_user.preferred_languages}
    all_subtitle_ids_for_voting = set() # Use a set to avoid duplicate IDs

    # Fetch all available local subtitles for all preferred languages in one query
    all_local_subs = Subtitle.query.filter(
        Subtitle.content_id == activity.content_id,
        Subtitle.language.in_(current_user.preferred_languages)
    ).options(joinedload(Subtitle.uploader)).all()

    # Group local subtitles by language and hash, and also create aggregated lists
    temp_grouped_local_subs = {lang: {'matching_hash': [], 'other_hash': [], 'no_hash': []} for lang in current_user.preferred_languages}
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

    for lang_code in current_user.preferred_languages:
        # Determine Active Subtitle for each language
        active_subtitle_info = get_active_subtitle_details(
            current_user,
            activity.content_id,
            activity.video_hash,
            activity.content_type,
            activity.video_filename,
            lang=lang_code,
            season=season,
            episode=episode
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
    
    # Calculate has_any_user_selection
    has_any_user_selection = any(details.get('user_selection') is not None for details in active_details_by_lang.values())

    # Get provider results for all preferred languages
    if current_user.preferred_languages:
        try:
            from ..providers.registry import ProviderRegistry
            from ..providers.base import SubtitleResult
            
            active_providers = ProviderRegistry.get_active_for_user(current_user)
            
            for provider in active_providers:
                try:
                    # Search for all preferred languages
                    results = provider.search(
                        user=current_user,
                        imdb_id=activity.content_id.split(':')[0] if activity.content_id.startswith('tt') else None,
                        video_hash=activity.video_hash,
                        languages=current_user.preferred_languages,
                        season=season,
                        episode=episode,
                        content_type=activity.content_type
                    )
                    
                    # Group results by language (convert SubtitleResult to old format for template compatibility)
                    for result in results:
                        if result.language.lower() in provider_results_by_lang:
                            # Convert SubtitleResult to old API format for template
                            item = {
                                'provider_name': provider.name,
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
                                    'url': result.metadata.get('url', '') if result.metadata else ''
                                }
                            }
                            provider_results_by_lang[result.language].append(item)
                except Exception as e:
                    current_app.logger.error(f"Provider {provider.name} search failed: {e}", exc_info=True)
        except Exception as e:
            current_app.logger.error(f"Error fetching provider results for display: {e}", exc_info=True)
            flash("An error occurred while searching for subtitles.", "warning")

    # Fetch all user votes for all collected subtitle IDs
    user_votes = {}
    if all_subtitle_ids_for_voting:
        votes = SubtitleVote.query.filter(
            SubtitleVote.user_id == current_user.id,
            SubtitleVote.subtitle_id.in_(list(all_subtitle_ids_for_voting))
        ).all()
        for vote in votes:
            user_votes[vote.subtitle_id] = vote.vote_value

    # Calculate has_provider_results
    has_provider_results = any(results for results in provider_results_by_lang.values())

    # Prepare preferred languages for display
    preferred_languages_display = ", ".join([LANGUAGE_DICT.get(lang_code, lang_code) for lang_code in current_user.preferred_languages])

    # Check if no providers are active and show info message
    try:
        from ..providers.registry import ProviderRegistry
        active_providers = ProviderRegistry.get_active_for_user(current_user)
        if not active_providers:
            flash(Markup('You don\'t have any active provider connections. To fully utilize the addon features, <a href="{}" class="alert-link">activate providers in your account settings</a>.'.format(url_for('main.account_settings'))), 'info')
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
        'language_list': LANGUAGES, # All available languages
        'LANGUAGE_DICT': LANGUAGE_DICT, # Dictionary for language names
        'metadata': metadata,
        'provider_results_by_lang': provider_results_by_lang,
        'preferred_languages': current_user.preferred_languages, # User's selected preferred languages
        'has_any_user_selection': has_any_user_selection,
        'has_provider_results': has_provider_results,
        'preferred_languages_display': preferred_languages_display
    }

    return render_template('main/content_detail.html', **context)
