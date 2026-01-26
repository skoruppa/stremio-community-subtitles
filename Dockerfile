FROM python:3.12-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    unrar \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gunicorn gevent

# Copy application code
COPY . .

# Create directories for data
RUN mkdir -p /app/data /app/logs /app/subtitles

# Expose port
EXPOSE 4949

# Run gunicorn
CMD ["gunicorn", "-c", "gunicorn_config.py", "wsgi:app"]
