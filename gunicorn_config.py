"""Gunicorn configuration for production deployment"""
import multiprocessing
import os

# Gevent monkey patching MUST be done before any imports
from gevent import monkey
monkey.patch_all()

# Server socket
bind = f"{os.getenv('FLASK_RUN_HOST', '0.0.0.0')}:{os.getenv('FLASK_RUN_PORT', '5000')}"
backlog = 2048

# Worker processes
workers = int(os.getenv('GUNICORN_WORKERS', multiprocessing.cpu_count() * 2 + 1))
worker_class = 'gevent'
worker_connections = 1000
max_requests = 1000
max_requests_jitter = 50

# Timeouts
timeout = 30  # Worker timeout - critical for preventing hangs
graceful_timeout = 30
keepalive = 2

# Post-fork hook to ensure clean DB connections per worker
def post_fork(server, worker):
    from app import create_app
    from app.extensions import db
    app = create_app()
    with app.app_context():
        db.engine.dispose()  # Close all connections inherited from parent

# Logging
accesslog = '-'
errorlog = '-'
loglevel = 'info'
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" %(D)s'

# Process naming
proc_name = 'stremio-community-subtitles'

# Server mechanics
daemon = False
pidfile = None
umask = 0
user = None
group = None
tmp_upload_dir = None

# Preload app for better performance
preload_app = False  # Must be False with gevent to avoid monkey-patch issues
