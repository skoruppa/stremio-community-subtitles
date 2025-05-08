import os
import logging
from flask import Flask
from .extensions import db, migrate, login_manager, csrf, compress, cache, cors, mail
from config import get_config
from . import models


def create_app():
    """Create and configure the Flask application using the factory pattern."""
    app = Flask(__name__,
                instance_relative_config=True,
                template_folder='../templates',
                static_folder='../static')

    app.config.from_object(get_config())

    # Ensure the instance folder exists
    os.makedirs(app.instance_path, exist_ok=True)

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
    mail.init_app(app)

    from .routes.auth import auth_bp
    from .routes.main import main_bp
    from .routes.manifest import manifest_bp
    from .routes.subtitles import subtitles_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(manifest_bp)
    app.register_blueprint(subtitles_bp)

    # Create upload directory if it doesn't exist
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

    # Create cache directory if it doesn't exist
    # os.makedirs(scs.config['CACHE_DIR'], exist_ok=True)

    @app.shell_context_processor
    def make_shell_context():
        return {'db': db, 'scs': app}

    return app


