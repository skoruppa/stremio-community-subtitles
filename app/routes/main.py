import datetime # Added for UserSubtitleSelection timestamp

import pycountry
from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app
from flask_login import login_required, current_user
from sqlalchemy.orm import joinedload
from sqlalchemy import func
from ..models import User, UserActivity, Subtitle, UserSubtitleSelection, SubtitleVote # Added User
from ..forms import LanguagePreferenceForm, OpenSubtitlesLoginForm # Added OpenSubtitlesLoginForm
from ..extensions import db
from ..lib.metadata import get_metadata
from ..lib import opensubtitles_client
from ..lib.opensubtitles_client import OpenSubtitlesError
from ..languages import LANGUAGES, LANGUAGE_DICT
from .utils import get_active_subtitle_details # Import the new utility function

main_bp = Blueprint('main', __name__)


@main_bp.route('/')
def index():
    """Main landing page: Shows login/register or dashboard if logged in."""
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))
    else:
        return render_template('main/index.html')


@main_bp.route('/link_opensubtitle/<uuid:activity_id>/<int:opensub_file_id>', methods=['POST'])
@login_required
def link_opensubtitle(activity_id, opensub_file_id):
    """
    Creates a new community Subtitle entry linked to an OpenSubtitle,
    associating it with the current activity's video_hash.
    """
    activity = UserActivity.query.filter_by(id=activity_id, user_id=current_user.id).first_or_404()

    if not activity.video_hash:
        flash("Cannot link subtitle: the current video context does not have a hash.", "warning")
        return redirect(url_for('main.content_detail', activity_id=activity_id))

    # Retrieve details of the OpenSubtitle from the form
    os_language = request.form.get("os_language")
    os_release_name = request.form.get("os_release_name")
    os_uploader_name = request.form.get("os_uploader")
    os_ai_translated = request.form.get("os_ai_translated") == 'true'
    # os_hash_match_at_link_time = request.form.get("os_hash_match") == 'true' # This was for the source, not for the new link
    os_url = request.form.get("os_url")

    if not all([os_language, os_release_name]):  # Basic validation
        flash("Missing necessary OpenSubtitle details to create a link.", "danger")
        return redirect(url_for('main.content_detail', activity_id=activity_id))

    # Check if this exact OpenSubtitle (by original file_id) is already linked to this specific video_hash
    existing_link = Subtitle.query.filter_by(
        video_hash=activity.video_hash,
        source_type='opensubtitles_community_link',
        language=os_language
    ).filter(Subtitle.source_metadata['original_file_id'].astext == str(opensub_file_id)).first()
    # Note: JSON query depends on DB. Using .astext for PostgreSQL. For SQLite, it might be json_extract.

    if existing_link:
        flash("This OpenSubtitle is already linked to this video version.", "info")
        # Optionally, select this existing link for the user
        try:
            selection = UserSubtitleSelection.query.filter_by(
                user_id=current_user.id,
                content_id=activity.content_id,
                video_hash=activity.video_hash
            ).first()
            if selection:
                selection.selected_subtitle_id = existing_link.id
                selection.selected_external_file_id = None
                selection.external_details_json = None
            else:
                selection = UserSubtitleSelection(
                    user_id=current_user.id,
                    content_id=activity.content_id,
                    video_hash=activity.video_hash,
                    selected_subtitle_id=existing_link.id
                )
                db.session.add(selection)
            db.session.commit()
        except Exception as e_sel:
            db.session.rollback()
            current_app.logger.error(f"Error auto-selecting existing linked OS sub: {e_sel}", exc_info=True)
        return redirect(url_for('main.content_detail', activity_id=activity_id))

    try:
        new_linked_subtitle = Subtitle(
            content_id=activity.content_id,
            content_type=activity.content_type,
            video_hash=activity.video_hash,  # Crucially, assign current video_hash
            language=os_language,
            file_path=None,  # No local file path
            uploader_id=current_user.id,  # The user performing the linking action
            author=os_uploader_name if os_uploader_name != 'N/A' else "OpenSubtitles",  # Original uploader
            version_info=os_release_name,  # Original release name
            source_type='opensubtitles_community_link',
            source_metadata={
                "original_file_id": opensub_file_id,
                "original_uploader": os_uploader_name,
                "original_release_name": os_release_name,
                "original_url": os_url,
                "ai_translated": os_ai_translated,
                "linked_by_user_id": current_user.id
            },
            votes=1
        )
        db.session.add(new_linked_subtitle)

        # Add the initial vote
        initial_vote = SubtitleVote(
            user_id=current_user.id,
            subtitle_id=new_linked_subtitle.id,  # Will be set after flush if using UUID from Python
            vote_value=1
        )
        db.session.flush()

        initial_vote.subtitle_id = new_linked_subtitle.id
        db.session.add(initial_vote)

        # Update UserSubtitleSelection to point to this new local Subtitle record
        selection = UserSubtitleSelection.query.filter_by(
            user_id=current_user.id,
            content_id=activity.content_id,
            video_hash=activity.video_hash
        ).first()

        if selection:
            selection.selected_subtitle_id = new_linked_subtitle.id
            selection.selected_external_file_id = None  # Clear direct OS selection
            selection.external_details_json = None
            selection.timestamp = datetime.datetime.utcnow()
        else:
            new_user_selection = UserSubtitleSelection(
                user_id=current_user.id,
                content_id=activity.content_id,
                video_hash=activity.video_hash,
                selected_subtitle_id=new_linked_subtitle.id
            )
            db.session.add(new_user_selection)

        db.session.commit()
        flash('OpenSubtitle successfully linked to this video version and selected!', 'success')

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(
            f"Error linking OpenSubtitle file_id {opensub_file_id} for user {current_user.id}: {e}", exc_info=True)
        flash('Error linking OpenSubtitle. Please try again.', 'danger')

    return redirect(url_for('main.content_detail', activity_id=activity_id))
    return render_template('main/index.html')


@main_bp.route('/dashboard')
@login_required
def dashboard():
    """Displays the user's dashboard, showing recent activity."""
    # Fetch recent activity for the current user
    recent_activity = UserActivity.query.filter_by(user_id=current_user.id) \
        .order_by(UserActivity.timestamp.desc()) \
        .limit(current_app.config.get('MAX_USER_ACTIVITIES', 15)).all()

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

    max_activities_to_display = current_app.config.get('MAX_USER_ACTIVITIES', 15)

    # Pass activities and their metadata to the template
    return render_template('main/dashboard.html',
                           activities=recent_activity,
                           metadata_map=activity_metadata,
                           max_activities=max_activities_to_display)


@main_bp.route('/content/<uuid:activity_id>')
@login_required
def content_detail(activity_id):
    """Displays details for a specific content item based on user activity."""
    # Fetch the specific activity ensuring it belongs to the current user
    activity = UserActivity.query.filter_by(id=activity_id, user_id=current_user.id).first_or_404()

    # Parse season/episode if applicable
    season = None
    episode = None
    auto_selected = False

    # Determine Active Subtitle using the utility function
    active_subtitle_info = get_active_subtitle_details(current_user, activity.content_id, activity.video_hash)
    
    active_subtitle = None
    active_opensubtitle_details = None
    user_vote_value = None
    user_selection = active_subtitle_info.get('user_selection_record') # Get the raw selection record

    if active_subtitle_info:
        auto_selected = active_subtitle_info['auto']

    if active_subtitle_info['type'] == 'local':
        active_subtitle = active_subtitle_info['subtitle']
        user_vote_value = active_subtitle_info['user_vote_value']
    elif active_subtitle_info['type'] == 'opensubtitles_selection':
        active_opensubtitle_details = active_subtitle_info['details']
    
    # Fetch Available Subtitles (excluding the active one if it's local)
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
        'user_selection': user_selection,  # This now contains new fields
        'user_vote_value': user_vote_value,
        'user_votes': user_votes,
        'language_list': LANGUAGES,
        'LANGUAGE_DICT': LANGUAGE_DICT,
        'auto_selected': auto_selected,
        'metadata': metadata,
        'opensubtitles_results': [],  # Placeholder, will be populated next
        'active_opensubtitle_details': active_opensubtitle_details
    }

    # Fetch OpenSubtitles if API key is available and user has integration active
    if current_user.opensubtitles_active:
        if current_user.preferred_language == 'eng':
            os_language = 'en'
        elif current_user.preferred_language == 'msa':
            os_language = 'ar'
        else:
            os_language = pycountry.countries.get(alpha_3=current_user.preferred_language).alpha_2,
        try:
            search_params = {
                'languages': os_language,
                'moviehash': activity.video_hash if activity.video_hash else None,
                'user': current_user
            }
            # Extract IMDb ID if present in content_id (e.g., "tt123456" or "tt123456:1:2")
            imdb_id_part = activity.content_id.split(':')[0]
            if imdb_id_part.startswith("tt"):
                search_params['imdb_id'] = imdb_id_part
            else:  # Fallback to query if no IMDb ID and no hash
                if not activity.video_hash and metadata and metadata.get('title'):
                    search_params['query'] = metadata.get('title')

            if activity.content_type == 'series':
                search_params['type'] = 'episode'
                if season: search_params['season_number'] = season
                if episode: search_params['episode_number'] = episode
            elif activity.content_type == 'movie':
                search_params['type'] = 'movie'

            if search_params.get('imdb_id') or search_params.get('query') or search_params.get('moviehash'):
                current_app.logger.info(f"Querying OpenSubtitles with: {search_params}")
                os_results = opensubtitles_client.search_subtitles(**search_params)
                if os_results and os_results.get('data'):
                    # Convert 2-letter language codes to 3-letter codes for consistency
                    for item in os_results['data']:
                        if 'attributes' in item and 'language' in item['attributes']:
                            try:
                                # pycountry uses ISO 639-1 (2-letter) and ISO 639-2 (3-letter)
                                # OpenSubtitles API returns ISO 639-1 (2-letter)
                                lang_2letter = item['attributes']['language']
                                country = pycountry.languages.get(alpha_2=lang_2letter)
                                if country:
                                    item['attributes']['language_3letter'] = country.alpha_3
                                else:
                                    item['attributes']['language_3letter'] = lang_2letter # Fallback
                            except Exception as e:
                                current_app.logger.warning(f"Could not convert 2-letter language code {lang_2letter} to 3-letter: {e}")
                                item['attributes']['language_3letter'] = lang_2letter # Fallback

                    context['opensubtitles_results'] = os_results['data']
                    current_app.logger.info(f"Found {len(os_results['data'])} results from OpenSubtitles.")
            else:
                current_app.logger.info("Not enough parameters to search OpenSubtitles.")

        except opensubtitles_client.OpenSubtitlesError as e:
            current_app.logger.error(f"Error fetching from OpenSubtitles: {e}")
            flash(f"Could not fetch results from OpenSubtitles: {e}", "warning")
        except Exception as e:
            db.session.rollback() # Ensure rollback on unexpected errors
            current_app.logger.error(f"Unexpected error during OpenSubtitles search: {e}", exc_info=True)
            flash("An unexpected error occurred while searching OpenSubtitles.", "warning")

    return render_template('main/content_detail.html', **context) # Rely on **context to pass activity


@main_bp.route('/configure')
@login_required
def configure():
    """Displays the addon installation page."""
    # Generate manifest URL parts
    from urllib.parse import urlparse

    manifest_url = None
    stremio_manifest_url = None
    if current_user.manifest_token:
        manifest_path = url_for('manifest.addon_manifest',
                                manifest_token=current_user.manifest_token,
                                _scheme=current_app.config['PREFERRED_URL_SCHEME'])
        manifest_url = f"{manifest_path}"
        parsed = urlparse(manifest_path)
        stremio_manifest_url = f"stremio://{parsed.netloc}{parsed.path}"

    return render_template('main/configure.html',
                           manifest_url=manifest_url,
                           stremio_manifest_url=stremio_manifest_url)


@main_bp.route('/account', methods=['GET', 'POST'])
@login_required
def account_settings():
    """Allows user to change their preferred language and OpenSubtitles settings."""
    lang_form = LanguagePreferenceForm(prefix="lang_form")
    os_form = OpenSubtitlesLoginForm(prefix="os_form")

    lang_form.preferred_language.choices = LANGUAGES

    if request.method == 'GET':
        lang_form.preferred_language.data = current_user.preferred_language
        os_form.use_opensubtitles.data = current_user.opensubtitles_active
        # We don't pre-fill username/password for security and simplicity.
        # If opensubtitles_active is true, template will show "logged in" state.

    if lang_form.submit_language.data and lang_form.validate():
        try:
            current_user.preferred_language = lang_form.preferred_language.data
            db.session.commit()
            flash('Preferred language updated successfully!', 'success')
            return redirect(url_for('main.account_settings')) # Redirect to avoid re-POST
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Failed to update language for user {current_user.id}: {e}")
            flash('Failed to update language.', 'danger')

    if os_form.submit_opensubtitles.data and os_form.validate():
        os_username = os_form.opensubtitles_username.data
        os_password = os_form.opensubtitles_password.data
        os_api_key = os_form.opensubtitles_api_key.data 

        # Save the personal API key if provided (only editable when logged out)
        if not current_user.opensubtitles_token:
             current_user.opensubtitles_api_key = os_api_key
        elif os_api_key and os_api_key != current_user.opensubtitles_api_key:
             flash('Please log out from OpenSubtitles before changing your personal API key.', 'warning')

        if os_form.use_opensubtitles.data:
            # User wants to enable or keep enabled
            if os_username and os_password:
                try:
                    current_app.logger.info(f"User {current_user.username} attempting to login/re-login to OpenSubtitles with username {os_username}.")
                    # Pass the user object to login to use their personal API key
                    login_data = opensubtitles_client.login(os_username, os_password, user=current_user)
                    
                    current_user.opensubtitles_token = login_data['token']
                    current_user.opensubtitles_base_url = login_data['base_url']
                    current_user.opensubtitles_active = True
                    flash('Successfully logged into OpenSubtitles and activated integration!', 'success')
                    current_app.logger.info(f"User {current_user.username} successfully logged into OpenSubtitles.")
                except OpenSubtitlesError as e:
                    db.session.rollback()
                    current_app.logger.error(f"OpenSubtitles login failed for user {current_user.username} (OS username: {os_username}): {e}")
                    flash(f'OpenSubtitles login failed: {e}', 'danger')
                    # Ensure opensubtitles_active is false if login fails and there was no prior token
                    if not current_user.opensubtitles_token:
                        current_user.opensubtitles_active = False 
                        db.session.commit()
                except Exception as e:
                    db.session.rollback()
                    current_app.logger.error(f"Unexpected error during OpenSubtitles login for {current_user.username}: {e}", exc_info=True)
                    flash('An unexpected error occurred during OpenSubtitles login.', 'danger')
                    if not current_user.opensubtitles_token:
                        current_user.opensubtitles_active = False
                        db.session.commit()
            elif current_user.opensubtitles_token:
                 # If no username/password provided but a token exists, just ensure integration is active
                 if not current_user.opensubtitles_active:
                    current_user.opensubtitles_active = True
                    flash('OpenSubtitles integration (using existing session) has been activated.', 'info')
                 else:
                    flash('OpenSubtitles integration remains active.', 'info')

        else:
            # User wants to disable OpenSubtitles integration (use_opensubtitles is unchecked)
            if current_user.opensubtitles_active:
                current_user.opensubtitles_active = False
                flash('OpenSubtitles integration has been locally deactivated. Your OpenSubtitles session details and API key are kept if you wish to re-activate.', 'info')
            else:
                flash('OpenSubtitles integration is already inactive.', 'info') 
        
        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Failed to save OpenSubtitles settings for user {current_user.id}: {e}")
            flash('Failed to save OpenSubtitles settings.', 'danger')

        return redirect(url_for('main.account_settings'))

    opensubtitles_has_token = current_user.opensubtitles_token is not None
    return render_template('main/account_settings.html', 
                           lang_form=lang_form, 
                           os_form=os_form,
                           opensubtitles_active=current_user.opensubtitles_active,
                           opensubtitles_has_token=opensubtitles_has_token,
                           LANGUAGE_DICT=LANGUAGE_DICT)


@main_bp.route('/opensubtitles_logout', methods=['POST'])
@login_required
def opensubtitles_logout():
    """Logs the user out from OpenSubtitles and deactivates the integration."""
    if not current_user.opensubtitles_active or not current_user.opensubtitles_token or not current_user.opensubtitles_base_url:
        flash('OpenSubtitles integration is not active or session details are missing.', 'warning')
        return redirect(url_for('main.account_settings'))

    try:
        current_app.logger.info(f"User {current_user.username} attempting to logout from OpenSubtitles.")
        opensubtitles_client.logout(current_user.opensubtitles_token, user=current_user) # Pass user object
        
        # Clear OS-related fields from User model
        current_user.opensubtitles_token = None
        current_user.opensubtitles_base_url = None
        current_user.opensubtitles_active = False
        db.session.commit()
        
        flash('Successfully logged out from OpenSubtitles.', 'success')
        current_app.logger.info(f"User {current_user.username} successfully logged out from OpenSubtitles.")
    except OpenSubtitlesError as e:
        db.session.rollback()
        current_app.logger.error(f"OpenSubtitles logout API call failed for user {current_user.username}: {e}")
        flash(f'OpenSubtitles logout failed: {e}. Your local integration status may be unchanged.', 'danger')
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Unexpected error during OpenSubtitles logout for {current_user.username}: {e}", exc_info=True)
        flash('An unexpected error occurred during OpenSubtitles logout.', 'danger')
        
    return redirect(url_for('main.account_settings'))


@main_bp.route('/select_opensubtitle/<uuid:activity_id>/<int:opensub_file_id>', methods=['POST'])
@login_required
def select_opensubtitle(activity_id, opensub_file_id):
    """Handles the selection of an OpenSubtitle for a given activity."""
    activity = UserActivity.query.filter_by(id=activity_id, user_id=current_user.id).first_or_404()

    opensub_details = {
        "file_id": opensub_file_id,
        "language": request.form.get("os_language", current_user.preferred_language),
        "release_name": request.form.get("os_release_name", "N/A"),
        "uploader": request.form.get("os_uploader", "N/A"),
        "ai_translated": request.form.get("os_ai_translated") == 'true',
        "moviehash_match": request.form.get("os_hash_match") == 'true',
        "url": request.form.get("os_url", None) # Capture URL if provided
    }

    try:
        selection = UserSubtitleSelection.query.filter_by(
            user_id=current_user.id,
            content_id=activity.content_id,
            video_hash=activity.video_hash
        ).first()

        if selection:
            selection.selected_subtitle_id = None  # Clear local selection
            selection.selected_external_file_id = opensub_file_id
            selection.external_details_json = opensub_details
            selection.timestamp = datetime.datetime.utcnow()
            flash('OpenSubtitle selected successfully.', 'success')
        else:
            new_selection = UserSubtitleSelection(
                user_id=current_user.id,
                content_id=activity.content_id,
                video_hash=activity.video_hash,
                selected_external_file_id=opensub_file_id,
                external_details_json=opensub_details,
                selected_subtitle_id=None
            )
            db.session.add(new_selection)
            flash('OpenSubtitle selected successfully.', 'success')

        db.session.commit()
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(
            f"Error selecting OpenSubtitle file_id {opensub_file_id} for user {current_user.id}: {e}", exc_info=True)
        flash('Error selecting OpenSubtitle. Please try again.', 'danger')

    return redirect(url_for('main.content_detail', activity_id=activity_id))


@main_bp.route('/delete_activity/<uuid:activity_id>', methods=['POST'])
@login_required
def delete_activity(activity_id):
    """Deletes a specific user activity item, ensuring ownership."""
    activity_to_delete = UserActivity.query.get(activity_id)  # Efficiently get by primary key

    if not activity_to_delete:
        flash('Activity record not found.', 'warning')
        return redirect(url_for('main.dashboard'))

    if activity_to_delete.user_id != current_user.id:
        # Log this attempt, as it might be malicious or a bug
        current_app.logger.warning(
            f"User {current_user.id} ({current_user.username}) "
            f"attempted to delete activity {activity_id} "
            f"belonging to user {activity_to_delete.user_id}."
        )
        flash('You do not have permission to delete this activity record.', 'danger')
        return redirect(url_for('main.dashboard'))

    try:
        db.session.delete(activity_to_delete)
        db.session.commit()
        flash('Activity record deleted successfully.', 'success')
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error deleting activity {activity_id} for user {current_user.id}: {e}")
        flash('Error deleting activity record. Please try again.', 'danger')

    return redirect(url_for('main.dashboard'))
