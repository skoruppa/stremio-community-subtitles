import datetime

from quart import Blueprint, render_template, redirect, url_for, flash, request, current_app
from quart_auth import login_required, current_user, logout_user
from markupsafe import Markup
from sqlalchemy.orm import joinedload
from sqlalchemy import func, select

from ..models import User, UserActivity, Subtitle, UserSubtitleSelection, SubtitleVote
from ..forms import LanguagePreferenceForm
from ..providers.registry import ProviderRegistry
from ..lib.metadata import get_metadata
from ..extensions import async_session_maker
from ..languages import LANGUAGES, LANGUAGE_DICT

main_bp = Blueprint('main', __name__)


@main_bp.route('/')
async def index():
    """Main landing page: Shows login/register or dashboard if logged in."""
    if await current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))
    else:
        return await render_template('main/index.html')


@main_bp.route('/dashboard')
@login_required
async def dashboard():
    """Displays the user's dashboard, showing recent activity."""
    user_id = (current_user.auth_id)
    
    # Fetch recent activity for the current user
    async with async_session_maker() as session:
        result = await session.execute(
            select(UserActivity)
            .filter_by(user_id=user_id)
            .order_by(UserActivity.timestamp.desc())
            .limit(current_app.config.get('MAX_USER_ACTIVITIES', 15))
        )
        recent_activity = result.scalars().all()

    # Fetch metadata for each activity item
    activity_metadata = {}
    for activity in recent_activity:
        meta = await get_metadata(activity.content_id, activity.content_type)
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
    return await render_template('main/dashboard.html',
                           activities=recent_activity,
                           metadata_map=activity_metadata,
                           max_activities=max_activities_to_display)


@main_bp.route('/configure')
async def configure():
    """Displays the addon installation page or login form."""
    if not await current_user.is_authenticated:
        from ..forms import LoginForm
        form = await LoginForm.create_form()
        await flash('Please log in to access this page.', 'info')
        return await render_template('auth/login.html', form=form, embedded=True)
    
    # Generate manifest URL parts
    from urllib.parse import urlparse

    manifest_url = None
    stremio_manifest_url = None
    
    user_id = (current_user.auth_id)
    async with async_session_maker() as session:
        result = await session.execute(select(User).filter_by(id=user_id))
        user = result.scalar_one_or_none()
        
        if user and user.manifest_token:
            manifest_path = url_for('manifest.addon_manifest',
                                    manifest_token=user.manifest_token,
                                    _scheme=current_app.config['PREFERRED_URL_SCHEME'])
            manifest_url = f"{manifest_path}"
            parsed = urlparse(manifest_path)
            stremio_manifest_url = f"stremio://{parsed.netloc}{parsed.path}"

    return await render_template('main/configure.html',
                           manifest_url=manifest_url,
                           stremio_manifest_url=stremio_manifest_url)


@main_bp.route('/<manifest_token>/configure')
@login_required
async def configure_redirect(manifest_token):
    """Redirect to the addon "setting" - account settings."""
    return redirect(url_for('main.account_settings'))


@main_bp.route('/account', methods=['GET', 'POST'])
@login_required
async def account_settings():
    """Allows user to change their preferred language and other settings."""
    user_id = (current_user.auth_id)
    
    current_app.logger.info(f"Account settings request: method={request.method}, is_json={request.is_json}")
    
    # Handle AJAX requests for settings
    if request.is_json:
        try:
            data = await request.get_json()
            async with async_session_maker() as session:
                result = await session.execute(select(User).filter_by(id=user_id))
                user = result.scalar_one_or_none()
                
                if 'show_no_subtitles' in data:
                    user.show_no_subtitles = data.get('show_no_subtitles', False)
                    await session.commit()
                    return {'success': True}
                if 'prioritize_ass_subtitles' in data:
                    user.prioritize_ass_subtitles = data.get('prioritize_ass_subtitles', False)
                    await session.commit()
                    return {'success': True}
        except Exception as e:
            current_app.logger.error(f"Error updating settings for user {user_id}: {e}")
            return {'success': False, 'error': str(e)}, 500
    
    async with async_session_maker() as session:
        result = await session.execute(select(User).filter_by(id=user_id))
        user = result.scalar_one_or_none()
        
        current_app.logger.info(f"Creating form for user {user_id}")
        lang_form = await LanguagePreferenceForm.create_form(prefix="lang_form")
        lang_form.preferred_languages.choices = LANGUAGES
        current_app.logger.info(f"Form created, method={request.method}")
        
        if request.method == 'GET':
            lang_form.preferred_languages.data = user.preferred_languages
            current_app.logger.info(f"GET: Set form data to {user.preferred_languages}")

        if await lang_form.validate_on_submit():
            current_app.logger.info(f"Form validated, data: {lang_form.preferred_languages.data}")
            try:
                user.preferred_languages = lang_form.preferred_languages.data
                await session.commit()
                await flash('Preferred languages updated successfully!', 'success')
                return redirect(url_for('main.account_settings'))
            except Exception as e:
                await session.rollback()
                current_app.logger.error(f"Failed to update language for user {user_id}: {e}")
                await flash('Failed to update language.', 'danger')
        elif request.method == 'POST':
            current_app.logger.error(f"Form validation failed: {lang_form.errors}")
            current_app.logger.error(f"Form data: {await request.form}")
        
        all_providers = ProviderRegistry.get_all(user, filter_by_language=True)
        
        # Evaluate is_authenticated for each provider
        provider_status = []
        for p in all_providers:
            is_auth = await p.is_authenticated(user)
            provider_status.append((p, is_auth))
        
        current_app.logger.info(f"Providers for user {user_id}: {[(p.name, is_auth) for p, is_auth in provider_status]}")

    return await render_template('main/account_settings.html',
                           lang_form=lang_form,
                           all_providers=provider_status,
                           LANGUAGE_DICT=LANGUAGE_DICT)


@main_bp.route('/delete_activity/<uuid:activity_id>', methods=['POST'])
@login_required
async def delete_activity(activity_id):
    """Deletes a specific user activity item, ensuring ownership."""
    user_id = (current_user.auth_id)
    
    async with async_session_maker() as session:
        result = await session.execute(select(UserActivity).filter_by(id=activity_id))
        activity_to_delete = result.scalar_one_or_none()

        if not activity_to_delete:
            await flash('Activity record not found.', 'warning')
            return redirect(url_for('main.dashboard'))

        if activity_to_delete.user_id != user_id:
            # Log this attempt, as it might be malicious or a bug
            current_app.logger.warning(
                f"User {user_id} "
                f"attempted to delete activity {activity_id} "
                f"belonging to user {activity_to_delete.user_id}."
            )
            await flash('You do not have permission to delete this activity record.', 'danger')
            return redirect(url_for('main.dashboard'))

        try:
            await session.delete(activity_to_delete)
            await session.commit()
            await flash('Activity record deleted successfully.', 'success')
        except Exception as e:
            await session.rollback()
            current_app.logger.error(f"Error deleting activity {activity_id} for user {user_id}: {e}")
            await flash('Error deleting activity record. Please try again.', 'danger')

    return redirect(url_for('main.dashboard'))


@main_bp.route('/delete_account', methods=['POST'])
@login_required
async def delete_account():
    """Permanently deletes user account and all associated data."""
    form_data = await request.form
    confirm_username = form_data.get('confirm_username', '').strip()
    user_id = (current_user.auth_id)
    
    async with async_session_maker() as session:
        result = await session.execute(select(User).filter_by(id=user_id))
        user = result.scalar_one_or_none()
        
        if confirm_username != user.username:
            await flash('Username confirmation does not match. Account not deleted.', 'danger')
            return redirect(url_for('main.account_settings'))
        
        username = user.username
        
        try:
            # Delete all user data
            from sqlalchemy import delete
            await session.execute(delete(UserActivity).where(UserActivity.user_id == user_id))
            await session.execute(delete(SubtitleVote).where(SubtitleVote.user_id == user_id))
            await session.execute(delete(UserSubtitleSelection).where(UserSubtitleSelection.user_id == user_id))
            await session.execute(delete(Subtitle).where(Subtitle.uploader_id == user_id))
            
            # Delete user account
            await session.delete(user)
            await session.commit()
            
            # Logout user
            logout_user()
            
            current_app.logger.info(f"User account deleted: {username} (ID: {user_id})")
            await flash('Your account has been permanently deleted.', 'info')
            return redirect(url_for('main.index'))
            
        except Exception as e:
            await session.rollback()
            current_app.logger.error(f"Error deleting account for user {user_id}: {e}")
            await flash('Error deleting account. Please try again or contact support.', 'danger')
            return redirect(url_for('main.account_settings'))
