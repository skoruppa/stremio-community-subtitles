import os
import datetime
from dotenv import load_dotenv

# Load environment variables from .env file if it exists
load_dotenv()


class Config:
    """Base configuration."""
    SECRET_KEY = os.environ.get('SECRET_KEY')
    DEBUG = False
    TESTING = False

    # URL Scheme for external URLs
    PREFERRED_URL_SCHEME = os.environ.get('PREFERRED_URL_SCHEME', 'http')

    # Storage Backend ('local' or 'cloudinary')
    STORAGE_BACKEND = os.environ.get('STORAGE_BACKEND', 'local')

    # Cloudinary Configuration (only if STORAGE_BACKEND is 'cloudinary')
    CLOUDINARY_CLOUD_NAME = os.environ.get('CLOUDINARY_CLOUD_NAME')
    CLOUDINARY_API_KEY = os.environ.get('CLOUDINARY_API_KEY')
    CLOUDINARY_API_SECRET = os.environ.get('CLOUDINARY_API_SECRET')
    CLOUDINARY_SUBTITLES_FOLDER = os.environ.get('CLOUDINARY_SUBTITLES_FOLDER', 'community_subtitles')
    
    # Session configuration
    PERMANENT_SESSION_LIFETIME = datetime.timedelta(days=3650)  # 10 years
    SESSION_COOKIE_SECURE = False  # Set to True in production with HTTPS
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    
    # Quart-Auth configuration
    QUART_AUTH_COOKIE_NAME = 'remember_token'
    QUART_AUTH_COOKIE_SECURE = False
    QUART_AUTH_COOKIE_HTTPONLY = True
    QUART_AUTH_COOKIE_SAMESITE = 'Lax'
    QUART_AUTH_DURATION = 3650 * 24 * 60 * 60  # 10 years in seconds
    
    # Mail configuration
    EMAIL_METHOD = os.environ.get('EMAIL_METHOD', 'smtp')  # 'smtp', 'resend', or 'local_api'
    MAIL_DEFAULT_SENDER = os.environ.get('MAIL_DEFAULT_SENDER')
    
    # Email verification (can be disabled for self-hosting)
    DISABLE_EMAIL_VERIFICATION = os.environ.get('DISABLE_EMAIL_VERIFICATION', 'false').lower() in ['true', '1', 't', 'y', 'yes']
    
    # Resend API
    RESEND_API_KEY = os.environ.get('RESEND_API_KEY')
    
    # Local Mail API
    LOCAL_MAIL_API_URL = os.environ.get('LOCAL_MAIL_API_URL')
    LOCAL_MAIL_API_KEY = os.environ.get('LOCAL_MAIL_API_KEY')
    
    # SMTP Configuration
    MAIL_SERVER = os.environ.get('MAIL_SERVER')
    MAIL_PORT = int(os.environ.get('MAIL_PORT', 587))
    MAIL_USE_TLS = os.environ.get('MAIL_USE_TLS', 'true').lower() in ['true', '1', 't', 'y', 'yes']
    MAIL_USE_SSL = os.environ.get('MAIL_USE_SSL', 'false').lower() in ['true', '1', 't', 'y', 'yes']
    MAIL_USERNAME = os.environ.get('MAIL_USERNAME')
    MAIL_PASSWORD = os.environ.get('MAIL_PASSWORD')
    
    # Database configuration
    # Check if USE_SQLITE environment variable is set to a truthy value
    USE_SQLITE_ENV = os.environ.get('USE_SQLITE', 'false').lower()
    USE_SQLITE = USE_SQLITE_ENV in ['true', '1', 't', 'y', 'yes']

    if USE_SQLITE:
        # Ensure the instance folder exists for SQLite
        instance_path = os.path.join(os.path.abspath(os.path.dirname(__file__)), 'instance')
        if not os.path.exists(instance_path):
            os.makedirs(instance_path)
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{os.path.join(instance_path, 'local.db')}"
    else:
        # Example URI: postgresql://user:password@host:port/database
        SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or \
            'postgresql://stremio_community_subs:password@localhost:5436/stremio_community_subs?sslmode=disable'
    
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    
    TMDB_KEY = os.environ.get('TMDB_API_KEY')
    OPENSUBTITLES_API_KEY = os.environ.get('OPENSUBTITLES_API_KEY')
    KITSU_ADDON_URL = os.environ.get('KITSU_ADDON_URL', 'https://anime-kitsu.strem.fun')
    MAL_CLIENT_ID = os.environ.get('MAL_CLIENT_ID')
    
    # Better Stack (Logtail) configuration
    USE_BETTERSTACK = os.environ.get('USE_BETTERSTACK', 'false').lower() in ['true', '1', 't', 'y', 'yes']
    BETTERSTACK_SOURCE_TOKEN = os.environ.get('BETTERSTACK_SOURCE_TOKEN')
    BETTERSTACK_HOST = os.environ.get('BETTERSTACK_HOST', 'https://in.logs.betterstack.com')

    UPLOAD_FOLDER = os.path.join(os.path.abspath(os.path.dirname(__file__)), 'uploads')
    
    ALLOWED_EXTENSIONS = {'txt', 'srt', 'sub', 'ass', 'ssa'}
    
    CACHE_TYPE = 'SimpleCache'
    # CACHE_DIR = os.path.join(os.path.abspath(os.path.dirname(__file__)), 'instance/cache')
    CACHE_DEFAULT_TIMEOUT = 300
    
    # Database connection pool settings
    SQLALCHEMY_ENGINE_OPTIONS = {
        'pool_pre_ping': True,
        'pool_size': 10,
        'max_overflow': 20,
        'pool_recycle': 300,
        'pool_timeout': 30,
        'pool_reset_on_return': 'rollback',
        'connect_args': {
            'ssl': {'ssl': True}
        } if not USE_SQLITE and 'mysql' in os.environ.get('DATABASE_URL', '') else {}
    }

    MAX_USER_ACTIVITIES = int(os.environ.get('MAX_USER_ACTIVITIES') or '15')
    
    # Babel i18n
    BABEL_DEFAULT_LOCALE = 'en'
    BABEL_TRANSLATION_DIRECTORIES = os.path.join(os.path.abspath(os.path.dirname(__file__)), 'translations')
    LANGUAGES = ['en', 'pl', 'es', 'fr', 'de', 'it', 'pt', 'pt_BR', 'ru', 'ja', 'zh', 'tr', 'ar', 'he', 'vi']
    
    # Gevent support (disabled in development for debugger compatibility)
    USE_GEVENT = True
    
    # Flask server configuration (for app.run() and waitress)
    SERVER_NAME = None  # Flask will use FLASK_RUN_HOST:FLASK_RUN_PORT from .env


class DevelopmentConfig(Config):
    """Development configuration."""
    DEBUG = True
    USE_GEVENT = False  # Disable gevent in development for debugger compatibility


class ProductionConfig(Config):
    """Production configuration."""
    # Production specific settings
    SESSION_COOKIE_SECURE = True
    QUART_AUTH_COOKIE_SECURE = True


class TestingConfig(Config):
    """Testing configuration."""
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'


config_by_name = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'testing': TestingConfig,
    'default': DevelopmentConfig
}


def get_config():
    env = os.getenv('FLASK_ENV', 'development')
    return config_by_name.get(env, DevelopmentConfig)
