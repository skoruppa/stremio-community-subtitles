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
        if not lang:
            lang = request.accept_languages.best_match(app.config['LANGUAGES'])
        # Normalize: browser may send 'pl-pl', we need 'pl'
        if lang and '-' in lang:
            lang = lang.split('-')[0]
        return lang
    
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

    # Pre-compute available languages and static file versions (once at startup)
    _available_languages = ['en']
    translations_dir = os.path.join(os.path.dirname(__file__), '..', 'translations')
    for lang_code in app.config.get('LANGUAGES', []):
        if lang_code == 'en':
            continue
        mo_file = os.path.join(translations_dir, lang_code, 'LC_MESSAGES', 'messages.mo')
        if os.path.exists(mo_file) and os.path.getsize(mo_file) > 700:
            _available_languages.append(lang_code)

    _static_versions = {}
    css_path = os.path.join(app.static_folder, 'css', 'style.css')
    _static_versions['css'] = int(os.path.getmtime(css_path)) if os.path.exists(css_path) else 0
    js_files = ['utils.js', 'account_settings.js', 'voting.js']
    _static_versions['js'] = {}
    for js_file in js_files:
        js_path = os.path.join(app.static_folder, 'js', js_file)
        _static_versions['js'][js_file] = int(os.path.getmtime(js_path)) if os.path.exists(js_path) else 0

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
            from .models import User, Subtitle, UserSubtitleSelection, SubtitleVote
            from sqlalchemy import select, func
            from .extensions import async_session_maker
            async with async_session_maker() as session:
                # Single query: fetch user + all three counts via scalar subqueries
                uid = current_user.auth_id
                stmt = select(
                    User,
                    select(func.count()).where(Subtitle.uploader_id == uid).correlate(None).scalar_subquery().label('uploaded_count'),
                    select(func.count()).where(UserSubtitleSelection.user_id == uid).correlate(None).scalar_subquery().label('selections_count'),
                    select(func.count()).where(SubtitleVote.user_id == uid).correlate(None).scalar_subquery().label('votes_count'),
                ).filter(User.id == uid)
                
                row = (await session.execute(stmt)).first()
                if row:
                    return {
                        'user': row[0],
                        'uploaded_count': row[1] or 0,
                        'selections_count': row[2] or 0,
                        'votes_count': row[3] or 0,
                    }
        return {'user': None, 'uploaded_count': 0, 'selections_count': 0, 'votes_count': 0}
    
    @app.context_processor
    def inject_language_info():
        import os
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
            'tr': {'flag': '🇹🇷', 'name': 'Türkçe'},
            'ar': {'flag': '🇸🇦', 'name': 'العربية'},
            'he': {'flag': '🇮🇱', 'name': 'עברית'},
            'vi': {'flag': '🇻🇳', 'name': 'Tiếng Việt'}
        }
        
        # Use same logic as get_locale()
        current_lang = request.cookies.get('lang')
        if not current_lang:
            current_lang = request.accept_languages.best_match(_available_languages) or 'en'
        
        return {
            'language_map': lang_map,
            'current_language': current_lang,
            'supported_languages': _available_languages,
            'css_version': _static_versions.get('css', 0),
            'js_versions': _static_versions.get('js', {}),
        }

    return app
