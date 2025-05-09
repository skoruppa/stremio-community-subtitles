from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app
from flask_login import login_required, current_user
from sqlalchemy.orm import joinedload
from sqlalchemy import func
from ..models import UserActivity, Subtitle, UserSubtitleSelection, SubtitleVote
from ..forms import LanguagePreferenceForm
from ..extensions import db
from ..lib.metadata import get_metadata  # Changed to absolute import
from ..languages import LANGUAGES, LANGUAGE_DICT

main_bp = Blueprint('main', __name__)


@main_bp.route('/')
def index():
    """Main landing page: Shows login/register or dashboard if logged in."""
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))
    return render_template('main/index.html')


@main_bp.route('/dashboard')
@login_required
def dashboard():
    """Displays the user's dashboard, showing recent activity."""
    # Fetch recent activity for the current user
    recent_activity = UserActivity.query.filter_by(user_id=current_user.id) \
        .order_by(UserActivity.timestamp.desc()) \
        .limit(20).all()

    # Fetch metadata for each activity item
    activity_metadata = {}
    for activity in recent_activity:
        meta = get_metadata(activity.content_id, activity.content_type)
        if meta:
            activity_metadata[activity.id] = meta
            # Simple title construction for display
            title = meta.get('title', activity.content_id)
            if meta.get('season') is not None and meta.get('episode') is not None:
                title = f"{title} S{meta['season']:02d}E{meta['episode']:02d}"
            elif meta.get('season') is not None:
                title = f"{title} S{meta['season']:02d}"
            if meta.get('year'):
                title = f"{title} ({meta['year']})"
            meta['display_title'] = title  # Add a pre-formatted title for the template

    # Pass activities and their metadata to the template
    return render_template('main/dashboard.html',
                           activities=recent_activity,
                           metadata_map=activity_metadata)


@main_bp.route('/content/<uuid:activity_id>')
@login_required
def content_detail(activity_id):
    """Displays details for a specific content item based on user activity."""
    # Fetch the specific activity ensuring it belongs to the current user
    activity = UserActivity.query.filter_by(id=activity_id, user_id=current_user.id).first_or_404()

    # Parse season/episode if applicable
    season = None
    episode = None

    # Determine Active Subtitle and User's Vote on it
    active_subtitle = None
    user_selection = None
    user_vote_value = None  # Store user's vote on the active subtitle (None, 1, or -1)

    # 1. Check User Selection (hash specific)
    if activity.video_hash:
        user_selection_specific = UserSubtitleSelection.query.filter_by(
            user_id=current_user.id, content_id=activity.content_id, video_hash=activity.video_hash
        ).options(joinedload(UserSubtitleSelection.selected_subtitle).joinedload(Subtitle.uploader)).first()

        if user_selection_specific and user_selection_specific.selected_subtitle:
            user_selection = user_selection_specific
            active_subtitle = user_selection.selected_subtitle

    # 2. Check User Selection (general) only if no specific found and no hash from activity
    if not active_subtitle and not activity.video_hash:
        user_selection_general = UserSubtitleSelection.query.filter_by(
            user_id=current_user.id, content_id=activity.content_id, video_hash=None
        ).options(joinedload(UserSubtitleSelection.selected_subtitle).joinedload(Subtitle.uploader)).first()

        if user_selection_general and user_selection_general.selected_subtitle:
            user_selection = user_selection_general
            active_subtitle = user_selection.selected_subtitle

    # 3. If no user selection, perform default lookup
    if not active_subtitle:
        if activity.video_hash:
            # Find best match by hash in user's preferred language
            active_subtitle = Subtitle.query.filter_by(
                content_id=activity.content_id,
                language=current_user.preferred_language,
                video_hash=activity.video_hash
            ).order_by(Subtitle.votes.desc()).options(joinedload(Subtitle.uploader)).first()

    # If an active subtitle was determined, get the user's vote on it
    if active_subtitle:
        user_vote = SubtitleVote.query.filter_by(
            user_id=current_user.id,
            subtitle_id=active_subtitle.id
        ).first()
        if user_vote:
            user_vote_value = user_vote.vote_value

    # Fetch Available Subtitles
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
    else:  # No hash provided by activity context
        for sub in all_available_subs_for_lang:
            if sub.video_hash is None:
                subs_no_hash.append(sub)
            else:
                subs_other_hash.append(sub)  # Treat all subs with any hash as 'other' if context has no hash

    # Fetch metadata using the helper
    metadata = get_metadata(activity.content_id, activity.content_type)

    # Add display_title to metadata
    if metadata:
        # Simple title construction for display
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
        metadata['display_title'] = title  # Add a pre-formatted title for the template
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
                # If len is 1 (just ttID), season/episode remain None
            except ValueError:
                current_app.logger.warning(f"Could not parse season/episode from content_id: {activity.content_id}")
                season = None  # Reset on error
                episode = None

    # Get all subtitle IDs for this content
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
        'user_votes': user_votes,  # Add user votes dictionary
        'language_list': LANGUAGES,
        'LANGUAGE_DICT': LANGUAGE_DICT,
        'metadata': metadata
    }
    return render_template('main/content_detail.html', **context)


@main_bp.route('/configure')
@login_required
def configure():
    """Displays the addon installation page."""
    # Generate manifest URL parts
    manifest_url = None
    stremio_manifest_url = None
    if current_user.manifest_token:
        base_url = request.host_url  # Use http or https as served
        manifest_path = url_for('manifest.addon_manifest', manifest_token=current_user.manifest_token)
        manifest_url = f"{base_url.strip('/')}{manifest_path}"
        stremio_manifest_url = f"stremio://{request.host}{manifest_path}"

    return render_template('main/configure.html',
                           manifest_url=manifest_url,
                           stremio_manifest_url=stremio_manifest_url)


@main_bp.route('/account', methods=['GET', 'POST'])
@login_required
def account_settings():
    """Allows user to change their preferred language."""
    form = LanguagePreferenceForm()
    form.preferred_language.choices = LANGUAGES

    if request.method == 'GET':
        form.preferred_language.data = current_user.preferred_language

    if form.validate_on_submit():
        try:
            current_user.preferred_language = form.preferred_language.data
            db.session.commit()
            flash('Preferred language updated successfully!', 'success')
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Failed to update language for user {current_user.id}: {e}")
            flash('Failed to update language.', 'danger')

    return render_template('main/account_settings.html', form=form)
