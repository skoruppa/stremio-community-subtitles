"""Provider management routes"""
from flask import Blueprint, request, flash, redirect, url_for, render_template
from flask_login import login_required, current_user
from ..extensions import db
from ..providers.registry import ProviderRegistry
from ..providers.base import ProviderAuthError

providers_bp = Blueprint('providers', __name__, url_prefix='/providers')


@providers_bp.route('/<provider_name>/connect', methods=['POST'])
@login_required
def connect_provider(provider_name):
    """Connect to a provider or update settings"""
    provider = ProviderRegistry.get(provider_name)
    if not provider:
        flash(f'Provider {provider_name} not found', 'danger')
        return redirect(url_for('main.account_settings'))
    
    try:
        credentials = request.form.to_dict()
        credentials.pop('csrf_token', None)
        
        # Extract try_provide_ass preference (checkbox sends 'true' if checked, nothing if unchecked)
        try_provide_ass = credentials.pop('try_provide_ass', 'false') == 'true'
        
        # Check if already authenticated and only updating settings
        # (no credentials means only settings like try_provide_ass)
        if provider.is_authenticated(current_user) and not credentials:
            # Only update try_provide_ass setting
            if not current_user.provider_credentials:
                current_user.provider_credentials = {}
            if provider_name not in current_user.provider_credentials:
                current_user.provider_credentials[provider_name] = {}
            current_user.provider_credentials[provider_name]['try_provide_ass'] = try_provide_ass
            # Mark as modified for SQLAlchemy to detect changes in JSON field
            from sqlalchemy.orm.attributes import flag_modified
            flag_modified(current_user, 'provider_credentials')
            db.session.commit()
            flash(f'{provider.display_name} settings updated!', 'success')
        else:
            # Full authentication
            result = provider.authenticate(current_user, credentials)
            
            # Add try_provide_ass to result
            result['try_provide_ass'] = try_provide_ass
            
            provider.save_credentials(current_user, result)
            db.session.commit()
            
            flash(f'Successfully connected to {provider.display_name}!', 'success')
    except ProviderAuthError as e:
        flash(f'Authentication failed: {str(e)}', 'danger')
    except Exception as e:
        db.session.rollback()
        flash(f'Error connecting to {provider.display_name}: {str(e)}', 'danger')
    
    return redirect(url_for('main.account_settings'))


@providers_bp.route('/<provider_name>/disconnect', methods=['POST'])
@login_required
def disconnect_provider(provider_name):
    """Disconnect from a provider"""
    provider = ProviderRegistry.get(provider_name)
    if not provider:
        flash(f'Provider {provider_name} not found', 'danger')
        return redirect(url_for('main.account_settings'))
    
    try:
        provider.logout(current_user)
        
        if hasattr(current_user, 'provider_credentials') and current_user.provider_credentials:
            current_user.provider_credentials.pop(provider_name, None)
            db.session.commit()
        
        flash(f'Disconnected from {provider.display_name}', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error disconnecting: {str(e)}', 'danger')
    
    return redirect(url_for('main.account_settings'))


@providers_bp.route('/<uuid:activity_id>/select', methods=['POST'])
@login_required
def select_provider_subtitle(activity_id):
    """Select a subtitle from a provider"""
    from ..models import UserActivity, UserSubtitleSelection
    import datetime
    
    activity = UserActivity.query.filter_by(id=activity_id, user_id=current_user.id).first_or_404()
    
    provider_name = request.form.get('provider_name')
    subtitle_id = request.form.get('subtitle_id')
    language = request.form.get('language')
    
    if not all([provider_name, subtitle_id, language]):
        flash('Missing required parameters', 'danger')
        return redirect(url_for('content.content_detail', activity_id=activity_id))
    
    try:
        # Build metadata from form
        metadata = {
            'release_name': request.form.get('release_name'),
            'uploader': request.form.get('uploader'),
            'ai_translated': request.form.get('ai_translated') == 'true',
            'hash_match': request.form.get('hash_match') == 'true'
        }
        
        # Find or create selection
        selection = UserSubtitleSelection.query.filter_by(
            user_id=current_user.id,
            content_id=activity.content_id,
            video_hash=activity.video_hash,
            language=language
        ).first()
        
        if selection:
            selection.selected_subtitle_id = None
            selection.selected_external_file_id = None
            selection.external_details_json = None
            selection.timestamp = datetime.datetime.utcnow()
        else:
            selection = UserSubtitleSelection(
                user_id=current_user.id,
                content_id=activity.content_id,
                video_hash=activity.video_hash,
                language=language
            )
            db.session.add(selection)
        
        # Store provider subtitle
        selection.external_details_json = {
            'provider': provider_name,
            'file_id': subtitle_id,
            **metadata
        }
        
        db.session.commit()
        flash('Subtitle selected successfully!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error selecting subtitle: {str(e)}', 'danger')
    
    return redirect(url_for('content.content_detail', activity_id=activity_id))


@providers_bp.route('/<uuid:activity_id>/link', methods=['POST'])
@login_required
def link_provider_subtitle(activity_id):
    """Link a provider subtitle to video hash as community preferred version"""
    from ..models import UserActivity, Subtitle, UserSubtitleSelection, SubtitleVote
    from sqlalchemy import func
    import datetime
    
    activity = UserActivity.query.filter_by(id=activity_id, user_id=current_user.id).first_or_404()
    
    if not activity.video_hash:
        flash('Cannot link subtitle: video has no hash', 'warning')
        return redirect(url_for('content.content_detail', activity_id=activity_id))
    
    provider_name = request.form.get('provider_name')
    subtitle_id = request.form.get('subtitle_id')
    language = request.form.get('language')
    release_name = request.form.get('release_name')
    uploader = request.form.get('uploader')
    ai_translated = request.form.get('ai_translated') == 'true'
    url = request.form.get('url')
    
    if not all([provider_name, subtitle_id, language, release_name]):
        flash('Missing required parameters', 'danger')
        return redirect(url_for('content.content_detail', activity_id=activity_id))
    
    dialect_name = db.engine.dialect.name
    
    # Check if already linked
    if dialect_name == 'postgresql':
        filter_cond = Subtitle.source_metadata['provider_subtitle_id'].astext == str(subtitle_id)
    else:
        filter_cond = func.json_unquote(func.json_extract(Subtitle.source_metadata, '$.provider_subtitle_id')) == str(subtitle_id)
    
    existing = Subtitle.query.filter_by(
        video_hash=activity.video_hash,
        source_type=f'{provider_name}_community_link',
        language=language
    ).filter(filter_cond).first()
    
    if existing:
        flash('This subtitle is already linked to this video version', 'info')
        # Auto-select existing
        selection = UserSubtitleSelection.query.filter_by(
            user_id=current_user.id,
            content_id=activity.content_id,
            video_hash=activity.video_hash,
            language=language
        ).first()
        if selection:
            selection.selected_subtitle_id = existing.id
            selection.selected_external_file_id = None
            selection.external_details_json = None
        else:
            selection = UserSubtitleSelection(
                user_id=current_user.id,
                content_id=activity.content_id,
                video_hash=activity.video_hash,
                selected_subtitle_id=existing.id,
                language=language
            )
            db.session.add(selection)
        db.session.commit()
        return redirect(url_for('content.content_detail', activity_id=activity_id))
    
    try:
        linked_subtitle = Subtitle(
            content_id=activity.content_id,
            content_type=activity.content_type,
            video_hash=activity.video_hash,
            language=language,
            file_path=None,
            uploader_id=current_user.id,
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
                'linked_by_user_id': current_user.id
            },
            votes=1
        )
        db.session.add(linked_subtitle)
        db.session.flush()
        
        # Add initial vote
        vote = SubtitleVote(
            user_id=current_user.id,
            subtitle_id=linked_subtitle.id,
            vote_value=1
        )
        db.session.add(vote)
        
        # Update selection
        selection = UserSubtitleSelection.query.filter_by(
            user_id=current_user.id,
            content_id=activity.content_id,
            video_hash=activity.video_hash,
            language=language
        ).first()
        
        if selection:
            selection.selected_subtitle_id = linked_subtitle.id
            selection.selected_external_file_id = None
            selection.external_details_json = None
            selection.timestamp = datetime.datetime.utcnow()
        else:
            selection = UserSubtitleSelection(
                user_id=current_user.id,
                content_id=activity.content_id,
                video_hash=activity.video_hash,
                selected_subtitle_id=linked_subtitle.id,
                language=language
            )
            db.session.add(selection)
        
        db.session.commit()
        flash('Subtitle successfully linked to this video version!', 'success')
    except Exception as e:
        db.session.rollback()
        from flask import current_app
        current_app.logger.error(f'Error linking subtitle: {e}', exc_info=True)
        flash('Error linking subtitle', 'danger')
    
    return redirect(url_for('content.content_detail', activity_id=activity_id))
