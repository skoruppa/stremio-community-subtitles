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

# Entrypoint: seed/update anime-lists into data volume
RUN printf '#!/bin/sh\n\
if [ ! -f /app/data/anime-lists/anime-list-full.json ]; then\n\
  echo "[entrypoint] Seeding anime-lists into data volume..."\n\
  if [ -d /app/_bundled_anime_lists ]; then\n\
    mkdir -p /app/data/anime-lists\n\
    cp -r /app/_bundled_anime_lists/* /app/data/anime-lists/\n\
  fi\n\
elif [ -d /app/_bundled_anime_lists ]; then\n\
  BUNDLED_HASH=$(md5sum /app/_bundled_anime_lists/anime-list-full.json 2>/dev/null | cut -d" " -f1)\n\
  CURRENT_HASH=$(md5sum /app/data/anime-lists/anime-list-full.json 2>/dev/null | cut -d" " -f1)\n\
  if [ "$BUNDLED_HASH" != "$CURRENT_HASH" ]; then\n\
    echo "[entrypoint] Updating anime-lists (new version in image)..."\n\
    cp -r /app/_bundled_anime_lists/* /app/data/anime-lists/\n\
  fi\n\
fi\n\
exec "$@"\n' > /app/entrypoint.sh && chmod +x /app/entrypoint.sh

ENTRYPOINT ["/app/entrypoint.sh"]

# Run with Hypercorn (workers = CPU cores)
CMD ["hypercorn", "run:app", "--bind", "0.0.0.0:4949", "--workers", "4", "--backlog", "256"]
