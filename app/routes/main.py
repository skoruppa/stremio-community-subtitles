import datetime  # Added for UserSubtitleSelection timestamp

from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app
from flask_login import login_required, current_user
from markupsafe import Markup
from sqlalchemy.orm import joinedload
from sqlalchemy import func

from ..lib import opensubtitles_client
from ..lib.opensubtitles_client import OpenSubtitlesError
from ..models import User, UserActivity, Subtitle, UserSubtitleSelection, SubtitleVote
from ..forms import LanguagePreferenceForm, OpenSubtitlesLoginForm
from ..lib.metadata import get_metadata
from ..extensions import db
from ..languages import LANGUAGES, LANGUAGE_DICT

main_bp = Blueprint('main', __name__)


@main_bp.route('/')
def index():
    """Main landing page: Shows login/register or dashboard if logged in."""
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))
    else:
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

    # Check if OpenSubtitles is not active and show info message
    if not current_user.opensubtitles_active:
        flash(Markup('You don\'t have an active OpenSubtitles connection. To fully utilize the addon features, <a href="{}" class="alert-link">activate it in your account settings</a>.'.format(url_for('main.account_settings'))), 'info')

    # Pass activities and their metadata to the template
    return render_template('main/dashboard.html',
                           activities=recent_activity,
                           metadata_map=activity_metadata,
                           max_activities=max_activities_to_display)


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


@main_bp.route('/<manifest_token>/configure')
@login_required
def configure_redirect(manifest_token):
    """Redirect to the addon "setting" - account settings."""
    return redirect(url_for('main.account_settings'))


@main_bp.route('/account', methods=['GET', 'POST'])
@login_required
def account_settings():
    """Allows user to change their preferred language and OpenSubtitles settings."""
    lang_form = LanguagePreferenceForm(prefix="lang_form")
    os_form = OpenSubtitlesLoginForm(prefix="os_form")

    lang_form.preferred_languages.choices = LANGUAGES

    if request.method == 'GET':
        lang_form.preferred_languages.data = current_user.preferred_languages
        os_form.use_opensubtitles.data = current_user.opensubtitles_active
        # We don't pre-fill username/password for security and simplicity.
        # If opensubtitles_active is true, template will show "logged in" state.

    if lang_form.submit_language.data and lang_form.validate():
        try:
            current_user.preferred_languages = lang_form.preferred_languages.data
            db.session.commit()
            flash('Preferred languages updated successfully!', 'success')
            return redirect(url_for('main.account_settings'))  # Redirect to avoid re-POST
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Failed to update language for user {current_user.id}: {e}")
            flash('Failed to update language.', 'danger')

    if os_form.submit_opensubtitles.data and os_form.validate():
        os_username = os_form.opensubtitles_username.data
        os_password = os_form.opensubtitles_password.data

        if os_form.use_opensubtitles.data:
            # User wants to enable or keep enabled
            if os_username and os_password:
                try:
                    current_app.logger.info(
                        f"User {current_user.username} attempting to login/re-login to OpenSubtitles with username {os_username}.")
                    # Pass the user object to login to use their personal API key
                    login_data = opensubtitles_client.login(os_username, os_password, user=current_user)

                    current_user.opensubtitles_token = login_data['token']
                    current_user.opensubtitles_base_url = login_data['base_url']
                    current_user.opensubtitles_active = True
                    flash('Successfully logged into OpenSubtitles and activated integration!', 'success')
                    current_app.logger.info(f"User {current_user.username} successfully logged into OpenSubtitles.")
                except OpenSubtitlesError as e:
                    db.session.rollback()
                    current_app.logger.error(
                        f"OpenSubtitles login failed for user {current_user.username} (OS username: {os_username}): {e}")
                    flash(f'OpenSubtitles login failed: {e}', 'danger')
                    # Ensure opensubtitles_active is false if login fails and there was no prior token
                    if not current_user.opensubtitles_token:
                        current_user.opensubtitles_active = False
                        db.session.commit()
                except Exception as e:
                    db.session.rollback()
                    current_app.logger.error(
                        f"Unexpected error during OpenSubtitles login for {current_user.username}: {e}", exc_info=True)
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
                flash(
                    'OpenSubtitles integration has been locally deactivated. Your OpenSubtitles session details and API key are kept if you wish to re-activate.',
                    'info')
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
