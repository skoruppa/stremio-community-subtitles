#!/bin/bash
# Start the Stremio Community Subtitles Addon

# Check if .env exists
if [ ! -f .env ]; then
    echo "Creating .env file..."
    cat > .env <<EOF
SECRET_KEY=$(openssl rand -hex 32)
USE_SQLITE=True
FLASK_APP=run.py
DISABLE_EMAIL_VERIFICATION=True
EOF
fi

# Activate virtual environment if it exists (optional check)
# source venv/bin/activate

# Initialize DB if needed (check if instance/local.db exists)
if [ ! -f instance/local.db ]; then
    echo "Initializing database..."
    python run.py init-db
    python run.py create-roles
    python run.py init-anime-db
    echo "Creating default admin user (admin@example.com / admin)"
    python run.py create-admin admin@example.com admin admin
fi

# Run the application
echo "Starting application..."
python run.py
