"""WSGI entry point with gevent monkey patching"""

# CRITICAL: Monkey patch BEFORE any other imports
from gevent import monkey
monkey.patch_all()

# Now safe to import everything else
import os
from app import create_app

app = create_app()

if __name__ == "__main__":
    # For direct execution (PyCharm debug), read port from environment
    host = os.environ.get('FLASK_RUN_HOST', '0.0.0.0')
    port = int(os.environ.get('FLASK_RUN_PORT', '5000'))
    use_gevent = app.config.get('USE_GEVENT', True)
    app.logger.info(f"Starting server on {host}:{port}")
    app.logger.info(f"Provider async mode: {'gevent' if use_gevent else 'threads'}")
    app.run(host=host, port=port, debug=True)
