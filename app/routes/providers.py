"""Provider management routes"""
from quart_babel import gettext as _
from quart import Blueprint, request, flash, redirect, url_for, render_template, current_app
from quart_auth import login_required, current_user
from sqlalchemy import select, func, delete as sql_delete
from sqlalchemy.orm.attributes import flag_modified
from ..extensions import async_session_maker
from ..models import User, UserActivity, Subtitle, UserSubtitleSelection, SubtitleVote
from ..providers.registry import ProviderRegistry
from ..providers.base import ProviderAuthError
import datetime

providers_bp = Blueprint('providers', __name__, url_prefix='/providers')


@providers_bp.route('/<provider_name>/connect', methods=['POST'])
@login_required
async def connect_provider(provider_name):
    """Connect to a provider or update settings"""
    provider = ProviderRegistry.get(provider_name)
    if not provider:
        await flash(_('Provider %(name)s not found', name=provider_name), 'danger')
        return redirect(url_for('main.account_settings'))
    
    user_id = (current_user.auth_id)
    
    try:
        form_data = await request.form
        credentials = dict(form_data)
        credentials.pop('csrf_token', None)
        
        # Extract try_provide_ass preference
        try_provide_ass = credentials.pop('try_provide_ass', 'false') == 'true'
        
        async with async_session_maker() as session:
            result = await session.execute(select(User).filter_by(id=user_id))
            user = result.scalar_one_or_none()
            
            # Check if already authenticated and only updating settings
            if await provider.is_authenticated(user) and not credentials:
                # Only update try_provide_ass setting
                if not user.provider_credentials:
                    user.provider_credentials = {}
                if provider_name not in user.provider_credentials:
                    user.provider_credentials[provider_name] = {}
                user.provider_credentials[provider_name]['try_provide_ass'] = try_provide_ass
                flag_modified(user, 'provider_credentials')
                await session.commit()
                await flash(_('%(name)s settings updated!', name=provider.display_name), 'success')
            else:
                # Full authentication
                auth_result = await provider.authenticate(user, credentials)
                
                # Add try_provide_ass to result
                auth_result['try_provide_ass'] = try_provide_ass
                
                await provider.save_credentials(user, auth_result)
                await session.commit()
                
                await flash(_('Successfully connected to %(name)s!', name=provider.display_name), 'success')
    except ProviderAuthError as e:
        await flash(_('Authentication failed: %(error)s', error=str(e)), 'danger')
    except Exception as e:
        await flash(_('Error connecting to %(name)s: %(error)s', name=provider.display_name, error=str(e)), 'danger')
    
    return redirect(url_for('main.account_settings'))


@providers_bp.route('/<provider_name>/disconnect', methods=['POST'])
@login_required
async def disconnect_provider(provider_name):
    """Disconnect from a provider"""
    provider = ProviderRegistry.get(provider_name)
    if not provider:
        await flash(_('Provider %(name)s not found', name=provider_name), 'danger')
        return redirect(url_for('main.account_settings'))
    
    user_id = (current_user.auth_id)
    
    try:
        async with async_session_maker() as session:
            result = await session.execute(select(User).filter_by(id=user_id))
            user = result.scalar_one_or_none()
            
            await provider.logout(user)
            
            if hasattr(user, 'provider_credentials') and user.provider_credentials:
                user.provider_credentials.pop(provider_name, None)
                await session.commit()
            
            await flash(_('Disconnected from %(name)s', name=provider.display_name), 'success')
    except Exception as e:
        await flash(_('Error disconnecting: %(error)s', error=str(e)), 'danger')
    
    return redirect(url_for('main.account_settings'))


@providers_bp.route('/<uuid:activity_id>/select', methods=['POST'])
@login_required
async def select_provider_subtitle(activity_id):
    """Select a subtitle from a provider"""
    user_id = (current_user.auth_id)
    
    async with async_session_maker() as session:
        result = await session.execute(
            select(UserActivity).filter_by(id=activity_id, user_id=user_id)
        )
        activity = result.scalar_one_or_none()
        if not activity:
            from quart import abort
            abort(404)
        
        form_data = await request.form
        provider_name = form_data.get('provider_name')
        subtitle_id = form_data.get('subtitle_id')
        language = form_data.get('language')
        
        if not all([provider_name, subtitle_id, language]):
            await flash(_('Missing required parameters'), 'danger')
            return redirect(url_for('content.content_detail', activity_id=activity_id))
        
        try:
            # Build metadata from form
            metadata = {
                'release_name': form_data.get('release_name'),
                'uploader': form_data.get('uploader'),
                'ai_translated': form_data.get('ai_translated') == 'true',
                'hash_match': form_data.get('hash_match') == 'true'
            }
            
            # Find or create selection
            result = await session.execute(
                select(UserSubtitleSelection).filter_by(
                    user_id=user_id,
                    content_id=activity.content_id,
                    video_hash=activity.video_hash or '',
                    language=language
                )
            )
            selection = result.scalar_one_or_none()
            
            if selection:
                selection.selected_subtitle_id = None
                selection.selected_external_file_id = None
                selection.external_details_json = None
                selection.timestamp = datetime.datetime.utcnow()
            else:
                selection = UserSubtitleSelection(
                    user_id=user_id,
                    content_id=activity.content_id,
                    video_hash=activity.video_hash or '',
                    language=language
                )
                session.add(selection)
            
            # Store provider subtitle
            selection.external_details_json = {
                'provider': provider_name,
                'file_id': subtitle_id,
                **metadata
            }
            
            await session.commit()
            await flash(_('Subtitle selected successfully!'), 'success')
        except Exception as e:
            await session.rollback()
            await flash(_('Error selecting subtitle: %(error)s', error=str(e)), 'danger')
    
    return redirect(url_for('content.content_detail', activity_id=activity_id))


@providers_bp.route('/<uuid:activity_id>/link', methods=['POST'])
@login_required
async def link_provider_subtitle(activity_id):
    """Link a provider subtitle to video hash as community preferred version"""
    user_id = (current_user.auth_id)
    
    async with async_session_maker() as session:
        result = await session.execute(
            select(UserActivity).filter_by(id=activity_id, user_id=user_id)
        )
        activity = result.scalar_one_or_none()
        if not activity:
            from quart import abort
            abort(404)
            abort(404)
        
        if not activity.video_hash:
            await flash(_('Cannot link subtitle: video has no hash'), 'warning')
            return redirect(url_for('content.content_detail', activity_id=activity_id))
        
        form_data = await request.form
        provider_name = form_data.get('provider_name')
        subtitle_id = form_data.get('subtitle_id')
        language = form_data.get('language')
        release_name = form_data.get('release_name')
        uploader = form_data.get('uploader')
        ai_translated = form_data.get('ai_translated') == 'true'
        url = form_data.get('url')
        
        if not all([provider_name, subtitle_id, language, release_name]):
            await flash(_('Missing required parameters'), 'danger')
            return redirect(url_for('content.content_detail', activity_id=activity_id))
        
        # Check if already linked
        dialect_name = session.bind.dialect.name
        
        if dialect_name == 'postgresql':
            filter_cond = Subtitle.source_metadata['provider_subtitle_id'].astext == str(subtitle_id)
        else:
            filter_cond = func.json_unquote(func.json_extract(Subtitle.source_metadata, '$.provider_subtitle_id')) == str(subtitle_id)
        
        result = await session.execute(
            select(Subtitle)
            .filter_by(
                video_hash=activity.video_hash,
                source_type=f'{provider_name}_community_link',
                language=language
            )
            .filter(filter_cond)
        )
        existing = result.scalar_one_or_none()
        
        if existing:
            await flash(_('This subtitle is already linked to this video version'), 'info')
            # Auto-select existing
            result = await session.execute(
                select(UserSubtitleSelection).filter_by(
                    user_id=user_id,
                    content_id=activity.content_id,
                    video_hash=activity.video_hash or '',
                    language=language
                )
            )
            selection = result.scalar_one_or_none()
            if selection:
                selection.selected_subtitle_id = existing.id
                selection.selected_external_file_id = None
                selection.external_details_json = None
            else:
                selection = UserSubtitleSelection(
                    user_id=user_id,
                    content_id=activity.content_id,
                    video_hash=activity.video_hash or '',
                    selected_subtitle_id=existing.id,
                    language=language
                )
                session.add(selection)
            await session.commit()
            return redirect(url_for('content.content_detail', activity_id=activity_id))
        
        try:
            linked_subtitle = Subtitle(
                content_id=activity.content_id,
                content_type=activity.content_type,
                video_hash=activity.video_hash,
                language=language,
                file_path=None,
                uploader_id=user_id,
                author=uploader if uploader and uploader != 'N/A' else provider_name.title(),
                version_info=release_name,
                source_type=f'{provider_name}_community_link',
                source_metadata={
                    'provider': provider_name,
                    'provider_subtitle_id': subtitle_id,
                    'original_uploader': uploader,
                    'original_release_name': release_name,
                    'original_url': url,
                    'ai_translated': ai_translated,
                    'linked_by_user_id': user_id
                },
                votes=1
            )
            session.add(linked_subtitle)
            await session.flush()
            
            # Add initial vote
            vote = SubtitleVote(
                user_id=user_id,
                subtitle_id=linked_subtitle.id,
                vote_value=1
            )
            session.add(vote)
            
            # Update selection
            result = await session.execute(
                select(UserSubtitleSelection).filter_by(
                    user_id=user_id,
                    content_id=activity.content_id,
                    video_hash=activity.video_hash,
                    language=language
                )
            )
            selection = result.scalar_one_or_none()
            
            if selection:
                selection.selected_subtitle_id = linked_subtitle.id
                selection.selected_external_file_id = None
                selection.external_details_json = None
                selection.timestamp = datetime.datetime.utcnow()
            else:
                selection = UserSubtitleSelection(
                    user_id=user_id,
                    content_id=activity.content_id,
                    video_hash=activity.video_hash,
                    selected_subtitle_id=linked_subtitle.id,
                    language=language
                )
                session.add(selection)
            
            await session.commit()
            await flash(_('Subtitle successfully linked to this video version!'), 'success')
        except Exception as e:
            await session.rollback()
            current_app.logger.error(f'Error linking subtitle: {e}', exc_info=True)
            await flash(_('Error linking subtitle'), 'danger')
    
    return redirect(url_for('content.content_detail', activity_id=activity_id))
