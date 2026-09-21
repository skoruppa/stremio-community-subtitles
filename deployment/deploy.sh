#!/bin/bash
# =============================================================
# Skrypt deploymentu aplikacji
# Uruchamiany ręcznie lub przez webhook (jako user deploy)
# 
# Zabezpieczenie: flock zapobiega równoległym deployom.
# Jeśli jeden deploy trwa, następny czeka max 120s.
# =============================================================
set -e

APP_DIR="/opt/stremio-subs/app"
LOG_DIR="/opt/stremio-subs/logs"
INTERNAL_TOKEN_FILE="/opt/stremio-subs/.internal_token"
LOCK_FILE="/opt/stremio-subs/.deploy.lock"

# ---- Acquire exclusive lock (wait up to 120s) ----
exec 200>"$LOCK_FILE"
if ! flock -w 120 200; then
    echo "[$(date)] Inny deploy w trakcie — timeout po 120s, pomijam"
    exit 1
fi
# Lock acquired — will auto-release when script exits

cd "$APP_DIR"

echo "[$(date)] === Rozpoczynam deployment ==="

# Zapamiętaj aktualny commit żeby porównać co się zmieniło
OLD_HEAD=$(git rev-parse HEAD 2>/dev/null || echo "none")

# Pull najnowszych zmian
echo "[$(date)] Pobieranie zmian z git..."
git fetch origin
git reset --hard origin/main
git submodule update --init --recursive

NEW_HEAD=$(git rev-parse HEAD)

if [ "$OLD_HEAD" = "$NEW_HEAD" ]; then
    echo "[$(date)] Brak zmian — pomijam deployment"
    exit 0
fi

# Sprawdź co się zmieniło
CHANGED_FILES=$(git diff --name-only "$OLD_HEAD" "$NEW_HEAD" 2>/dev/null || echo "FULL")

# Jeśli zmienił się TYLKO pointer submodułu anime-lists — hot reload bez rebuildu
if [ "$CHANGED_FILES" = "data/anime-lists" ]; then
    ANIME_ONLY=true
else
    ANIME_ONLY=false
fi

if [ "$ANIME_ONLY" = true ]; then
    echo "[$(date)] Zmienił się tylko submoduł anime-lists — hot reload"

    INTERNAL_TOKEN=$(cat "$INTERNAL_TOKEN_FILE" 2>/dev/null || echo "")
    if [ -n "$INTERNAL_TOKEN" ]; then
        RESPONSE=$(curl -s -o /dev/null -w "%{http_code}" \
            -X POST http://localhost:4949/internal/reload-anime \
            -H "X-Internal-Token: $INTERNAL_TOKEN")

        if [ "$RESPONSE" = "200" ]; then
            echo "[$(date)] Anime DB przeładowana (hot reload)"
        else
            echo "[$(date)] Hot reload failed (HTTP $RESPONSE) — robię pełny rebuild"
            ANIME_ONLY=false
        fi
    else
        echo "[$(date)] Brak INTERNAL_TOKEN — robię pełny rebuild"
        ANIME_ONLY=false
    fi
fi

if [ "$ANIME_ONLY" = false ]; then
    echo "[$(date)] Pełny rebuild kontenerów..."
    docker compose down --remove-orphans
    docker compose build --no-cache
    docker compose up -d

    # Czyszczenie starych obrazów
    echo "[$(date)] Czyszczenie starych obrazów Docker..."
    docker image prune -f
fi

echo "[$(date)] === Deployment zakończony ==="
