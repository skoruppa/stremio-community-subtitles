"""Async Quart application factory"""
import os
import logging
from quart import Quart, request
from .extensions import init_async_db, auth_manager, init_cors, cache, csrf, babel
from config import get_config


def create_app():
    """Create and configure the Quart application."""
    app = Quart(
        __name__,
        instance_relative_config=True,
        template_folder='../templates',
        static_folder='../static'
    )

    app.config.from_object(get_config())
    os.makedirs(app.instance_path, exist_ok=True)

    # Cloudinary
    if app.config.get('STORAGE_BACKEND') == 'cloudinary':
        import cloudinary
        if (app.config.get('CLOUDINARY_CLOUD_NAME') and
                app.config.get('CLOUDINARY_API_KEY') and
                app.config.get('CLOUDINARY_API_SECRET')):
            cloudinary.config(
                cloud_name=app.config['CLOUDINARY_CLOUD_NAME'],
                api_key=app.config['CLOUDINARY_API_KEY'],
                api_secret=app.config['CLOUDINARY_API_SECRET'],
                secure=True
            )
            app.logger.info("Cloudinary configured.")

    logging.basicConfig(level=logging.DEBUG if app.config['DEBUG'] else logging.WARNING)
    app.logger.setLevel(logging.DEBUG if app.config['DEBUG'] else logging.WARNING)

    # Better Stack
    if app.config.get('USE_BETTERSTACK') and app.config.get('BETTERSTACK_SOURCE_TOKEN'):
        try:
            from logtail import LogtailHandler
            handler = LogtailHandler(
                source_token=app.config['BETTERSTACK_SOURCE_TOKEN'],
                host=app.config.get('BETTERSTACK_HOST', 'https://in.logs.betterstack.com')
            )
            app.logger.addHandler(handler)
            app.logger.info("Better Stack logging enabled")
        except Exception as e:
            app.logger.warning(f"Failed to setup Better Stack: {e}")
    
    init_async_db(app)
    auth_manager.init_app(app)
    csrf.init_app(app)
    init_cors(app)
    
    # Locale selector for babel
    def get_locale():
        lang = request.cookies.get('lang')
        if lang:
            return lang
        return request.accept_languages.best_match(app.config['LANGUAGES'])
    
    babel.init_app(app, locale_selector=get_locale)

    # Initialize anime mapping database
    try:
        from .lib.anime_mapping import update_database
        update_database()
    except Exception as e:
        app.logger.warning(f"Could not initialize anime mapping database: {e}")

    try:
        from .providers import init_providers
        init_providers(app)
    except Exception as e:
        app.logger.warning(f"Could not initialize providers: {e}")

    from .routes.auth import auth_bp
    from .routes.main import main_bp
    from .routes.manifest import manifest_bp
    from .routes.subtitles import subtitles_bp
    from .routes.content import content_bp
    from .routes.providers import providers_bp
    from .routes.language import language_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(manifest_bp)
    app.register_blueprint(subtitles_bp)
    app.register_blueprint(content_bp)
    app.register_blueprint(providers_bp)
    app.register_blueprint(language_bp)

    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

    @app.context_processor
    def inject_providers():
        try:
            from .providers.registry import ProviderRegistry
            return {
                'get_all_providers': ProviderRegistry.get_all,
                'get_provider': ProviderRegistry.get
            }
        except:
            return {
                'get_all_providers': lambda: [],
                'get_provider': lambda x: None
            }
    
    @app.context_processor
    async def inject_user():
        from quart_auth import current_user
        try:
            is_auth = await current_user.is_authenticated
        except:
            is_auth = False
        
        if is_auth:
            from .models import User
            from sqlalchemy import select
            from sqlalchemy.orm import selectinload
            from .extensions import async_session_maker
            async with async_session_maker() as session:
                result = await session.execute(
                    select(User)
                    .filter_by(id=current_user.auth_id)
                    .options(
                        selectinload(User.uploaded_subtitles),
                        selectinload(User.selections),
                        selectinload(User.votes)
                    )
                )
                user = result.scalar_one_or_none()
                return {'user': user}
        return {'user': None}
    
    @app.context_processor
    def inject_language_info():
        lang_map = {
            'en': {'flag': '🇬🇧', 'name': 'English'},
            'pl': {'flag': '🇵🇱', 'name': 'Polski'},
            'es': {'flag': '🇪🇸', 'name': 'Español'},
            'fr': {'flag': '🇫🇷', 'name': 'Français'},
            'de': {'flag': '🇩🇪', 'name': 'Deutsch'},
            'it': {'flag': '🇮🇹', 'name': 'Italiano'},
            'pt': {'flag': '🇵🇹', 'name': 'Português'},
            'pt_BR': {'flag': '🇧🇷', 'name': 'Português (BR)'},
            'ru': {'flag': '🇷🇺', 'name': 'Русский'},
            'ja': {'flag': '🇯🇵', 'name': '日本語'},
            'zh': {'flag': '🇨🇳', 'name': '中文'},
            'tr': {'flag': '🇹🇷', 'name': 'Türkçe'}
        }
        # Use same logic as get_locale()
        current_lang = request.cookies.get('lang')
        if not current_lang:
            current_lang = request.accept_languages.best_match(app.config.get('LANGUAGES', ['en'])) or 'en'
        supported_langs = app.config.get('LANGUAGES', ['en'])
        return {
            'language_map': lang_map,
            'current_language': current_lang,
            'supported_languages': supported_langs
        }

    return app
