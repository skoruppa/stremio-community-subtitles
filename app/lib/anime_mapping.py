"""Anime ID mapping using local anime-lists database"""
import json
import hashlib
import sqlite3
import os
from pathlib import Path

ANIME_LISTS_JSON = Path(__file__).parent.parent.parent / 'data' / 'anime-lists' / 'anime-list-full.json'
ANIME_DB_PATH = Path(__file__).parent.parent.parent / 'instance' / 'anime_mapping.db'

# In-memory caches — populated on first lookup, invalidated on update_database()
_kitsu_cache = {}  # kitsu_id -> {'imdb_id': str, 'season': int|None}
_mal_cache = {}    # mal_id -> {'imdb_id': str, 'season': int|None}
_cache_loaded = False


def _get_json_hash():
    """Get MD5 hash of anime-list-full.json"""
    if not ANIME_LISTS_JSON.exists():
        return None
    with open(ANIME_LISTS_JSON, 'rb') as f:
        return hashlib.md5(f.read()).hexdigest()


def _init_db():
    """Initialize SQLite database from anime-list-full.json"""
    os.makedirs(ANIME_DB_PATH.parent, exist_ok=True)
    
    conn = sqlite3.connect(ANIME_DB_PATH)
    cursor = conn.cursor()

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS metadata (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    ''')

    columns = {row[1] for row in cursor.execute('PRAGMA table_info(anime_mapping)')}
    if columns and 'episode_offset' not in columns:
        cursor.execute('DROP TABLE anime_mapping')
        cursor.execute('DELETE FROM metadata WHERE key = ?', ('json_hash',))

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS anime_mapping (
            kitsu_id INTEGER,
            mal_id INTEGER,
            imdb_id TEXT,
            tvdb_season INTEGER,
            episode_offset INTEGER,
            PRIMARY KEY (kitsu_id, mal_id)
        )
    ''')

    cursor.execute('CREATE INDEX IF NOT EXISTS idx_kitsu ON anime_mapping(kitsu_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_mal ON anime_mapping(mal_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_imdb ON anime_mapping(imdb_id)')
    
    conn.commit()
    return conn


def _load_cache():
    """Load entire mapping into memory for fast lookups."""
    global _kitsu_cache, _mal_cache, _cache_loaded
    
    if not ANIME_DB_PATH.exists():
        update_database()
    if not ANIME_DB_PATH.exists():
        _cache_loaded = True
        return
    
    conn = sqlite3.connect(ANIME_DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT kitsu_id, mal_id, imdb_id, tvdb_season, episode_offset FROM anime_mapping')

    kitsu = {}
    mal = {}
    for row in cursor.fetchall():
        kitsu_id, mal_id, imdb_id, tvdb_season, episode_offset = row
        if imdb_id:
            entry = {'imdb_id': imdb_id, 'season': tvdb_season, 'episode_offset': episode_offset or 0}
            if kitsu_id:
                kitsu[kitsu_id] = entry
            if mal_id:
                mal[mal_id] = entry
    
    conn.close()
    _kitsu_cache = kitsu
    _mal_cache = mal
    _cache_loaded = True


def update_database():
    """Update database if JSON file changed"""
    global _cache_loaded
    
    if not ANIME_LISTS_JSON.exists():
        return False
    
    current_hash = _get_json_hash()
    if not current_hash:
        return False
    
    conn = _init_db()
    cursor = conn.cursor()
    
    cursor.execute('SELECT value FROM metadata WHERE key = ?', ('json_hash',))
    row = cursor.fetchone()
    stored_hash = row[0] if row else None
    
    if stored_hash == current_hash:
        conn.close()
        # Still load cache if not loaded yet
        if not _cache_loaded:
            _load_cache()
        return False
    
    # Clear and rebuild
    cursor.execute('DELETE FROM anime_mapping')
    
    with open(ANIME_LISTS_JSON, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    for entry in data:
        kitsu_id = entry.get('kitsu_id')
        mal_id = entry.get('mal_id')
        imdb_id = entry.get('imdb_id')
        tvdb_season = entry.get('season', {}).get('tvdb') if entry.get('season') else None
        episode_offset = entry.get('episode_offset', {}).get('tvdb') if entry.get('episode_offset') else None

        # These fields can be lists in the JSON — take first value
        if isinstance(kitsu_id, list):
            kitsu_id = kitsu_id[0] if kitsu_id else None
        if isinstance(mal_id, list):
            mal_id = mal_id[0] if mal_id else None
        if isinstance(imdb_id, list):
            imdb_id = imdb_id[0] if imdb_id else None
        if isinstance(tvdb_season, list):
            tvdb_season = tvdb_season[0] if tvdb_season else None
        if isinstance(episode_offset, list):
            episode_offset = episode_offset[0] if episode_offset else None

        if kitsu_id or mal_id:
            cursor.execute(
                'INSERT OR REPLACE INTO anime_mapping (kitsu_id, mal_id, imdb_id, tvdb_season, episode_offset) VALUES (?, ?, ?, ?, ?)',
                (kitsu_id, mal_id, imdb_id, tvdb_season, episode_offset)
            )
    
    cursor.execute('INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)', ('json_hash', current_hash))
    conn.commit()
    conn.close()
    
    # Invalidate and reload cache
    _cache_loaded = False
    _load_cache()
    return True


def get_imdb_from_kitsu(kitsu_id: int):
    """Get IMDb ID and season from Kitsu ID"""
    if not _cache_loaded:
        _load_cache()
    return _kitsu_cache.get(kitsu_id)


def get_imdb_from_mal(mal_id: int):
    """Get IMDb ID and season from MAL ID"""
    if not _cache_loaded:
        _load_cache()
    return _mal_cache.get(mal_id)


def mapping_for_content_id(content_id):
    prefix, _, rest = (content_id or '').partition(':')
    if prefix not in ('kitsu', 'mal'):
        return None
    try:
        anime_id = int(rest.split(':')[0])
    except ValueError:
        return None
    return get_imdb_from_kitsu(anime_id) if prefix == 'kitsu' else get_imdb_from_mal(anime_id)


def to_provider_episode(mapping, episode):
    if not mapping or episode is None:
        return episode
    shifted = episode + (mapping.get('episode_offset') or 0)
    return shifted if shifted >= 1 else episode
