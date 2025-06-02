from flask import Blueprint, render_template, flash, current_app
from flask_login import login_required, current_user
from sqlalchemy.orm import joinedload
from ..models import UserActivity, Subtitle, UserSubtitleSelection, SubtitleVote
from iso639 import Lang
from ..lib.metadata import get_metadata
from ..languages import LANGUAGES, LANGUAGE_DICT
from .utils import get_active_subtitle_details, search_opensubtitles

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
    auto_selected = False

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
            season = f"{metadata['season']}"
        if metadata.get('episode'):
            episode = f"{metadata['episode']}"
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

    # Determine Active Subtitle using the enhanced utility function
    active_subtitle_info = get_active_subtitle_details(
        current_user,
        activity.content_id,
        activity.video_hash,
        activity.content_type,
        activity.video_filename,
        metadata
    )

    active_subtitle = None
    active_opensubtitle_details = None
    user_vote_value = None
    user_selection = active_subtitle_info.get('user_selection_record')

    if active_subtitle_info:
        auto_selected = active_subtitle_info['auto']

    if active_subtitle_info['type'] == 'local':
        active_subtitle = active_subtitle_info['subtitle']
        user_vote_value = active_subtitle_info['user_vote_value']
    elif active_subtitle_info['type'] in ['opensubtitles_selection', 'opensubtitles_auto']:
        active_opensubtitle_details = active_subtitle_info['details']

    # Fetch Available Local Subtitles (excluding the active one if it's local)
    query_lang = current_user.preferred_language
    available_subs_query = Subtitle.query.filter_by(
        content_id=activity.content_id,
        language=query_lang
    ).options(joinedload(Subtitle.uploader))

    # Exclude the active subtitle from the "available" list
    if active_subtitle:
        available_subs_query = available_subs_query.filter(Subtitle.id != active_subtitle.id)

    all_available_subs_for_lang = available_subs_query.order_by(Subtitle.votes.desc()).all()

    # Separate subtitles by hash match
    subs_matching_hash = []
    subs_other_hash = []
    subs_no_hash = []

    if activity.video_hash:
        for sub in all_available_subs_for_lang:
            if sub.video_hash == activity.video_hash:
                subs_matching_hash.append(sub)
            elif sub.video_hash is None:
                subs_no_hash.append(sub)
            else:
                subs_other_hash.append(sub)
    else:
        for sub in all_available_subs_for_lang:
            if sub.video_hash is None:
                subs_no_hash.append(sub)
            else:
                subs_other_hash.append(sub)

    # Get all subtitle IDs for voting
    all_subtitle_ids = []
    if active_subtitle:
        all_subtitle_ids.append(active_subtitle.id)
    all_subtitle_ids.extend([sub.id for sub in subs_matching_hash])
    all_subtitle_ids.extend([sub.id for sub in subs_other_hash])
    all_subtitle_ids.extend([sub.id for sub in subs_no_hash])

    # Fetch all user votes for these subtitles
    user_votes = {}
    if all_subtitle_ids:
        votes = SubtitleVote.query.filter(
            SubtitleVote.user_id == current_user.id,
            SubtitleVote.subtitle_id.in_(all_subtitle_ids)
        ).all()
        for vote in votes:
            user_votes[vote.subtitle_id] = vote.vote_value

    # Get OpenSubtitles results using the new function
    opensubtitles_results = []
    if current_user.opensubtitles_active:
        try:
            os_results = search_opensubtitles(
                current_user,
                activity.content_id,
                activity.video_hash,
                activity.content_type,
                metadata
            )

            # Convert 2-letter language codes to 3-letter codes for consistency
            for item in os_results:
                if 'attributes' in item and 'language' in item['attributes']:
                    try:
                        lang_2letter = item['attributes']['language']
                        if lang_2letter.lower() == 'pt-pt':
                            item['attributes']['language_3letter'] = 'por'
                        elif lang_2letter.lower() == 'pt-br':
                            item['attributes']['language_3letter'] = 'pob'
                        else:
                            lang_obj = Lang(lang_2letter)
                            item['attributes']['language_3letter'] = lang_obj.pt3
                    except:
                        current_app.logger.warning(f"Could not convert language code {lang_2letter}")
                        item['attributes']['language_3letter'] = lang_2letter

            opensubtitles_results = os_results

        except Exception as e:
            current_app.logger.error(f"Error fetching OpenSubtitles results for display: {e}", exc_info=True)
            flash("An error occurred while searching OpenSubtitles.", "warning")

    # Pass context to the template
    context = {
        'activity': activity,
        'season': season,
        'episode': episode,
        'subs_matching_hash': subs_matching_hash,
        'subs_other_hash': subs_other_hash,
        'subs_no_hash': subs_no_hash,
        'active_subtitle': active_subtitle,
        'user_selection': user_selection,
        'user_vote_value': user_vote_value,
        'user_votes': user_votes,
        'language_list': LANGUAGES,
        'LANGUAGE_DICT': LANGUAGE_DICT,
        'auto_selected': auto_selected,
        'metadata': metadata,
        'opensubtitles_results': opensubtitles_results,
        'active_opensubtitle_details': active_opensubtitle_details
    }

    return render_template('main/content_detail.html', **context)