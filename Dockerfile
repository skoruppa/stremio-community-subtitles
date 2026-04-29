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

# Keep bundled anime-lists so volume mounts don't hide it
RUN cp -r /app/data/anime-lists /app/_bundled_anime_lists 2>/dev/null || true

# Expose port
EXPOSE 4949

# Entrypoint: seed anime-lists into data volume if missing
RUN printf '#!/bin/sh\n\
if [ -d /app/_bundled_anime_lists ] && [ ! -f /app/data/anime-lists/anime-list-full.json ]; then\n\
  echo "[entrypoint] Seeding anime-lists into data volume..."\n\
  mkdir -p /app/data/anime-lists\n\
  cp -r /app/_bundled_anime_lists/* /app/data/anime-lists/\n\
fi\n\
exec "$@"\n' > /app/entrypoint.sh && chmod +x /app/entrypoint.sh

ENTRYPOINT ["/app/entrypoint.sh"]

# Run with Hypercorn (workers = CPU cores)
CMD ["hypercorn", "run:app", "--bind", "0.0.0.0:4949", "--workers", "4", "--backlog", "256"]
