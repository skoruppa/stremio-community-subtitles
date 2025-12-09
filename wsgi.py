"""WSGI entry point with gevent monkey patching"""

# CRITICAL: Monkey patch BEFORE any other imports
from gevent import monkey
monkey.patch_all()

# Now safe to import everything else
from app import create_app

app = create_app()

if __name__ == "__main__":
    app.run()
