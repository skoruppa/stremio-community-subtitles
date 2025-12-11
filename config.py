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
    PERMANENT_SESSION_LIFETIME = datetime.timedelta(days=7)
    SESSION_COOKIE_SECURE = False  # Set to True in production with HTTPS
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    
    # Mail configuration
    EMAIL_METHOD = os.environ.get('EMAIL_METHOD', 'smtp')  # 'smtp', 'resend', or 'local_api'
    MAIL_DEFAULT_SENDER = os.environ.get('MAIL_DEFAULT_SENDER')
    
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
        'pool_size': 5,
        'max_overflow': 10,
        'pool_recycle': 300,
        'pool_timeout': 30,
        'pool_reset_on_return': 'rollback'
    }

    MAX_USER_ACTIVITIES = int(os.environ.get('MAX_USER_ACTIVITIES') or '15')


class DevelopmentConfig(Config):
    """Development configuration."""
    DEBUG = True


class ProductionConfig(Config):
    """Production configuration."""
    # Production specific settings
    SESSION_COOKIE_SECURE = True


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
