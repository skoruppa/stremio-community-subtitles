import os
import logging
from flask import Flask
from flask_talisman import Talisman
from .extensions import db, migrate, login_manager, csrf, compress, cache, cors
from config import get_config
from . import models


def create_app():
    """Create and configure the Flask application using the factory pattern."""
    app = Flask(__name__,
                instance_relative_config=True,
                template_folder='../templates',
                static_folder='../static')
    Talisman(app, content_security_policy=None)

    app.config.from_object(get_config())

    # Ensure the instance folder exists
    os.makedirs(app.instance_path, exist_ok=True)

    # Initialize Cloudinary if configured
    if app.config.get('STORAGE_BACKEND') == 'cloudinary':
        import cloudinary
        if (app.config.get('CLOUDINARY_CLOUD_NAME') and
                app.config.get('CLOUDINARY_API_KEY') and
                app.config.get('CLOUDINARY_API_SECRET')):
            cloudinary.config(
                cloud_name=app.config['CLOUDINARY_CLOUD_NAME'],
                api_key=app.config['CLOUDINARY_API_KEY'],
                api_secret=app.config['CLOUDINARY_API_SECRET'],
                secure=True  # Use HTTPS for Cloudinary URLs
            )
            app.logger.info("Cloudinary configured for subtitle storage.")
        else:
            app.logger.warning("STORAGE_BACKEND is 'cloudinary' but Cloudinary credentials are not fully set. Falling back to local storage behavior might be unexpected.")
            # Optionally, force STORAGE_BACKEND to 'local' or raise an error
            # For now, it will proceed, and parts of the app might fail if they expect Cloudinary.

    if app.config['DEBUG']:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.INFO)

    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    csrf.init_app(app)
    compress.init_app(app)
    cache.init_app(app)
    cors.init_app(app)

    # Initialize subtitle providers
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

    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(manifest_bp)
    app.register_blueprint(subtitles_bp)
    app.register_blueprint(content_bp)
    app.register_blueprint(providers_bp)

    # Create upload directory if it doesn't exist
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

    # Create cache directory if it doesn't exist
    # os.makedirs(app.config['CACHE_DIR'], exist_ok=True)

    @app.shell_context_processor
    def make_shell_context():
        return {'db': db, 'app': app}
    
    @app.context_processor
    def inject_providers():
        """Make provider registry available in templates"""
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

    return app
