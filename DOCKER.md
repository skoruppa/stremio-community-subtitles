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
   - Database URL (MariaDB included, can use external MySQL/PostgreSQL)
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

Generate one with:
```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
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

**To enable OpenSubtitles integration:**

Generate your API key at [opensubtitles.com/consumers](https://www.opensubtitles.com/consumers) and add to `.env`:
```bash
OPENSUBTITLES_API_KEY=your-api-key-here
```

Without this, users won't be able to connect their OpenSubtitles accounts.

**To enable movie/series metadata (posters, titles):**

Get a free API key at [themoviedb.org/settings/api](https://www.themoviedb.org/settings/api) and add to `.env`:
```bash
TMDB_API_KEY=your-tmdb-api-key
```

Without this, the app works but won't show posters or episode titles in the dashboard.

**To enable MyAnimeList metadata (optional):**

Create an API client at [myanimelist.net/apiconfig](https://myanimelist.net/apiconfig) and add to `.env`:
```bash
MAL_CLIENT_ID=your-mal-client-id
```

Without this, anime metadata falls back to Kitsu or TMDB via ID mapping. Only needed for direct MAL ID lookups.

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

## Updating Anime Mappings

Anime mappings are updated automatically when you update the app. Just run:

```bash
git pull --recurse-submodules
docker compose up -d --build
```

The container detects new anime data and reloads it on startup.

## Advanced: Hot-Reload Anime Mappings (Zero Downtime)

If you run your own deployment pipeline and want to update anime mappings without restarting:

1. Add `INTERNAL_API_TOKEN` to `.env`:
   ```bash
   echo "INTERNAL_API_TOKEN=$(openssl rand -hex 32)" >> .env
   docker compose restart app
   ```

2. After updating anime-lists data, trigger reload:
   ```bash
   curl -X POST http://localhost:4949/internal/reload-anime \
        -H "X-Internal-Token: $(grep INTERNAL_API_TOKEN .env | cut -d= -f2)"
   ```

> Block `/internal/*` from external access in your reverse proxy.

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
