FROM python:3.12-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    unrar-free \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Compile translations
RUN pybabel compile -d translations

# Create directories for data
RUN mkdir -p /app/data /app/logs /app/subtitles

# Expose port
EXPOSE 4949

# Run with Hypercorn (4 workers for production)
CMD ["hypercorn", "run:app", "--bind", "0.0.0.0:4949", "--workers", "4"]
