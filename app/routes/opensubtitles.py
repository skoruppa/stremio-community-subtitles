from flask import Blueprint, flash, redirect, url_for, request, current_app
from flask_login import login_required, current_user
from sqlalchemy.orm import joinedload
from sqlalchemy import func
from sqlalchemy.orm import Session
from ..models import User, UserActivity, Subtitle, UserSubtitleSelection, SubtitleVote
from iso639 import Lang
from ..forms import LanguagePreferenceForm, OpenSubtitlesLoginForm
from ..extensions import db
from ..lib import opensubtitles_client
from ..lib.opensubtitles_client import OpenSubtitlesError
from ..languages import LANGUAGES, LANGUAGE_DICT
from .utils import get_active_subtitle_details
import datetime

opensubtitles_bp = Blueprint('opensubtitles', __name__)


def get_original_file_id_filter(opensub_file_id, dialect_name):
    if dialect_name == 'postgresql':
        return Subtitle.source_metadata['original_file_id'].astext == str(opensub_file_id)
    else:
        return func.json_unquote(func.json_extract(Subtitle.source_metadata, '$.original_file_id')) == str(opensub_file_id)


@opensubtitles_bp.route('/opensubtitles_logout', methods=['POST'])
@login_required
def opensubtitles_logout():
    """Logs the user out from OpenSubtitles and deactivates the integration."""
    if not current_user.opensubtitles_active or not current_user.opensubtitles_token or not current_user.opensubtitles_base_url:
        flash('OpenSubtitles integration is not active or session details are missing.', 'warning')
        return redirect(url_for('main.account_settings'))

    try:
        current_app.logger.info(f"User {current_user.username} attempting to logout from OpenSubtitles.")
        opensubtitles_client.logout(current_user.opensubtitles_token, user=current_user)

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
        current_app.logger.error(f"Unexpected error during OpenSubtitles logout for {current_user.username}: {e}",
                                 exc_info=True)
        flash('An unexpected error occurred during OpenSubtitles logout.', 'danger')

    return redirect(url_for('main.account_settings'))


@opensubtitles_bp.route('/link_opensubtitle/<uuid:activity_id>/<int:opensub_file_id>', methods=['POST'])
@login_required
def link_opensubtitle(activity_id, opensub_file_id):
    """
    Creates a new community Subtitle entry linked to an OpenSubtitle,
    associating it with the current activity's video_hash.
    """
    activity = UserActivity.query.filter_by(id=str(activity_id), user_id=current_user.id).first_or_404()

    if not activity.video_hash:
        flash("Cannot link subtitle: the current video context does not have a hash.", "warning")
        return redirect(url_for('content.content_detail', activity_id=activity_id))

    # Retrieve details of the OpenSubtitle from the form
    os_language = request.form.get("os_language")
    os_release_name = request.form.get("os_release_name")
    os_uploader_name = request.form.get("os_uploader")
    os_ai_translated = request.form.get("os_ai_translated") == 'true'
    os_url = request.form.get("os_url")

    if not all([os_language, os_release_name]):  # Basic validation
        flash("Missing necessary OpenSubtitle details to create a link.", "danger")
        return redirect(url_for('content.content_detail', activity_id=activity_id))
    dialect_name = db.engine.dialect.name

    # Check if this exact OpenSubtitle (by original file_id) is already linked to this specific video_hash
    existing_link = Subtitle.query.filter_by(
        video_hash=activity.video_hash,
        source_type='opensubtitles_community_link',
        language=os_language
    ).filter(get_original_file_id_filter(opensub_file_id, dialect_name)).first()
    # Note: JSON query depends on DB. Using .astext for PostgreSQL. For SQLite, it might be json_extract.

    if existing_link:
        flash("This OpenSubtitle is already linked to this video version.", "info")
        # Optionally, select this existing link for the user
        try:
            selection = UserSubtitleSelection.query.filter_by(
                user_id=current_user.id,
                content_id=activity.content_id,
                video_hash=activity.video_hash,
                language=os_language
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
                    selected_subtitle_id=existing_link.id,
                    language=os_language
                )
                db.session.add(selection)
            db.session.commit()
        except Exception as e_sel:
            db.session.rollback()
            current_app.logger.error(f"Error auto-selecting existing linked OS sub: {e_sel}", exc_info=True)
        return redirect(url_for('content.content_detail', activity_id=activity_id))

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
            video_hash=activity.video_hash,
            language=os_language
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
                selected_subtitle_id=new_linked_subtitle.id,
                language=os_language
            )
            db.session.add(new_user_selection)

        db.session.commit()
        flash('OpenSubtitle successfully linked to this video version and selected!', 'success')

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(
            f"Error linking OpenSubtitle file_id {opensub_file_id} for user {current_user.id}: {e}", exc_info=True)
        flash('Error linking OpenSubtitle. Please try again.', 'danger')

    return redirect(url_for('content.content_detail', activity_id=activity_id))


@opensubtitles_bp.route('/select_opensubtitle/<uuid:activity_id>/<int:opensub_file_id>', methods=['POST'])
@login_required
def select_opensubtitle(activity_id, opensub_file_id):
    """Handles the selection of an OpenSubtitle for a given activity."""
    activity = UserActivity.query.filter_by(id=activity_id, user_id=current_user.id).first_or_404()
    language = request.form.get("os_language")

    opensub_details = {
        "file_id": opensub_file_id,
        "language": language,
        "release_name": request.form.get("os_release_name", "N/A"),
        "uploader": request.form.get("os_uploader", "N/A"),
        "ai_translated": request.form.get("os_ai_translated") == 'true',
        "moviehash_match": request.form.get("os_hash_match") == 'true',
        "url": request.form.get("os_url", None)
    }

    try:
        selection = UserSubtitleSelection.query.filter_by(
            user_id=current_user.id,
            content_id=activity.content_id,
            video_hash=activity.video_hash,
            language=language
        ).first()

        if selection:
            selection.selected_subtitle_id = None
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
                selected_subtitle_id=None,
                language=language
            )
            db.session.add(new_selection)
            flash('OpenSubtitle selected successfully.', 'success')

        db.session.commit()
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(
            f"Error selecting OpenSubtitle file_id {opensub_file_id} for user {current_user.id}: {e}", exc_info=True)
        flash('Error selecting OpenSubtitle. Please try again.', 'danger')

    return redirect(url_for('content.content_detail', activity_id=activity_id))
