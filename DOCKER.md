# Docker Deployment Guide

## Quick Start

1. **Clone with submodules:**
   ```bash
   git clone --recurse-submodules https://github.com/skoruppa/stremio-community-subtitles.git
   cd stremio-community-subtitles
   ```
   
   Or if already cloned:
   ```bash
   git submodule update --init --recursive
   ```

2. **Copy environment file:**
   ```bash
   cp .env.docker.example .env
   ```

3. **Edit `.env` file and set REQUIRED credentials:**
   - Secret key (SECRET_KEY - min 32 characters)
   
   **That's it!** Email verification is disabled by default for easy self-hosting.
   
   **Optional configurations:**
   - Email (set DISABLE_EMAIL_VERIFICATION=false and configure MAIL_*)
   - Database URL (SQLite by default, can use MySQL/PostgreSQL)
   - Cloudinary (for cloud storage instead of local files)
   - TMDB API (for better metadata)
   - MAL Client ID (for anime metadata)
   - Better Stack (for centralized logging)

3. **Build and start:**
   ```bash
   docker-compose up -d
   ```

4. **Initialize database:**
   ```bash
   docker-compose exec app python run.py init-db
   docker-compose exec app python run.py create-roles
   docker-compose exec app python run.py init-anime-db
   ```

5. **Create admin user (optional):**
   ```bash
   docker-compose exec app python run.py create-admin admin@example.com admin yourpassword
   ```

6. **Access the application:**
   - Application: http://localhost:4949

## Storage

### Database (SQLite by default)
- Database file: `./data/stremio_subtitles.db`
- No additional setup needed
- For MySQL/PostgreSQL, set `DATABASE_URL` in `.env`

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

That's it! Email verification is disabled by default.

**To enable email verification:**
```bash
DISABLE_EMAIL_VERIFICATION=false
MAIL_SERVER=smtp.gmail.com
MAIL_USERNAME=your-email@gmail.com
MAIL_PASSWORD=your-app-password
```

Everything else has sensible defaults!

## Commands

**View logs:**
```bash
docker-compose logs -f app
```

**Stop containers:**
```bash
docker-compose down
```

**Restart application:**
```bash
docker-compose restart app
```

**Access application shell:**
```bash
docker-compose exec app bash
```

**Database backup:**
```bash
docker-compose exec db mysqldump -u stremio -p stremio_subtitles > backup.sql
```

## Production Deployment

For production, use a reverse proxy (nginx/Caddy) in front of the application:

```yaml
# Add to docker-compose.yml
  nginx:
    image: nginx:alpine
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./nginx.conf:/etc/nginx/nginx.conf
      - ./certs:/etc/nginx/certs
    depends_on:
      - app
```

## Environment Variables

See `.env.docker.example` for all available configuration options.

## Volumes

- `db_data` - MariaDB database files (persistent)
- `./logs` - Application logs (mounted from host)

## Troubleshooting

**Database connection issues:**
```bash
docker-compose logs db
docker-compose exec db mysql -u root -p
```

**Application errors:**
```bash
docker-compose logs app
```

**Reset everything:**
```bash
docker-compose down -v
docker-compose up -d
```
