# Docker Deployment Guide

## Quick Start

1. **Clone with submodules:**
   ```bash
   git clone --recurse-submodules https://github.com/skoruppa/stremio-community-subtitles.git
   cd stremio-community-subtitles
   ```

   > **Important:** The `--recurse-submodules` flag is required. It downloads the anime mapping database used for anime ID lookups. Without it, `init-anime-db` will fail.

   If already cloned without submodules:
   ```bash
   git submodule update --init --recursive
   ```

2. **Copy environment file:**
   ```bash
   cp .env.docker.example .env
   ```

3. **Edit `.env` file and set REQUIRED credentials:**
   - Secret key (`SECRET_KEY` — min 32 characters)

   **That's it!** Email verification is disabled by default for easy self-hosting.

   **Optional configurations:**
   - Email (set `DISABLE_EMAIL_VERIFICATION=false` and configure `MAIL_*`)
   - Database URL (SQLite by default, can use MySQL/PostgreSQL)
   - Cloudinary (for cloud storage instead of local files)
   - TMDB API (for better metadata)
   - MAL Client ID (for anime metadata)
   - Better Stack (for centralized logging)

4. **Build and start:**
   ```bash
   docker compose up -d
   ```

5. **Initialize database:**
   ```bash
   docker compose exec app python run.py init-db
   docker compose exec app python run.py create-roles
   docker compose exec app python run.py init-anime-db
   ```

   > If `init-anime-db` fails with "anime-list-full.json not found", make sure you cloned with `--recurse-submodules`. You can fix it by running `git submodule update --init --recursive` on the host, then retry the command.

6. **Create admin user (optional):**
   ```bash
   docker compose exec app python run.py create-admin admin@example.com admin yourpassword
   ```

7. **Access the application:**
   - Application: http://localhost:4949

## Storage

### Database (MariaDB — included)
- Runs as a Docker container alongside the app
- Data persisted in Docker volume `db_data`
- Default credentials: user `stremio`, database `stremio_subs`
- No additional setup needed — starts automatically with `docker compose up -d`
- For external database (MySQL/PostgreSQL), set `DATABASE_URL` in `.env` and remove the `db` service from docker-compose.yml

### Subtitles (Local by default)
- Stored in: `./subtitles/` directory
- For Cloudinary, set credentials in `.env`

### Logs
- Application logs: `./logs/`

## Minimal Configuration

Only 1 thing is required in `.env`:
```bash
SECRET_KEY=your-random-64-char-hex-string
```

That's it! The included MariaDB container handles the database automatically. Email verification is disabled by default.

**To enable email verification:**
```bash
DISABLE_EMAIL_VERIFICATION=false
MAIL_SERVER=smtp.gmail.com
MAIL_USERNAME=your-email@gmail.com
MAIL_PASSWORD=your-app-password
```

Everything else has sensible defaults!

## Commands

```bash
# View logs
docker compose logs -f app

# Stop containers
docker compose down

# Restart application
docker compose restart app

# Access application shell
docker compose exec app bash

# Update to latest version
git pull --recurse-submodules
docker compose up -d --build
```

## Updating Anime Mappings Without Restart

When the anime-lists submodule is updated, you can reload the mappings without restarting the container. This avoids downtime.

1. **Add `INTERNAL_API_TOKEN` to your `.env`:**
   ```bash
   # Generate a random token
   echo "INTERNAL_API_TOKEN=$(openssl rand -hex 32)" >> .env
   ```

2. **Restart the container once** (to pick up the new env var):
   ```bash
   docker compose up -d
   ```

3. **After pulling submodule updates, reload with:**
   ```bash
   git submodule update --remote data/anime-lists
   
   curl -X POST http://localhost:4949/internal/reload-anime \
        -H "X-Internal-Token: $(grep INTERNAL_API_TOKEN .env | cut -d= -f2)"
   ```

   If the response is `{"updated": true}`, the new data is live. No restart needed.

> **Note:** The `/internal/*` endpoints are meant for local use only. If you expose the app through a reverse proxy, block `/internal/*` from external access.

## Production Deployment

For production, use a reverse proxy (nginx/Caddy) in front of the application.

**Important:** If using nginx, set `client_max_body_size` to allow subtitle uploads (default app limit is 15 MB). Without this, nginx returns `413 Entity Too Large` for files over 1 MB.

Example `nginx.conf` should include:
```nginx
server {
    # ...
    client_max_body_size 20M;  # Must be >= MAX_UPLOAD_SIZE_MB (default 15M)
    # ...
}
```

## Environment Variables

See `.env.docker.example` for all available configuration options.

## Volumes

- `db_data` — MariaDB database files (Docker managed volume)
- `./data` — Application data (anime mappings)
- `./logs` — Application logs
- `./subtitles` — Uploaded subtitle files (if using local storage)

## Troubleshooting

**`init-anime-db` fails with "not found":**
```bash
# The anime-lists submodule wasn't cloned. Fix with:
git submodule update --init --recursive
# Then retry:
docker compose exec app python run.py init-anime-db
```

**Application errors:**
```bash
docker compose logs app
```

**Reset everything:**
```bash
docker compose down -v
docker compose up -d
```
