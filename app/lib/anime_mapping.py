"""Anime ID mapping using local anime-lists database"""
import json
import hashlib
import sqlite3
import os
from pathlib import Path

ANIME_LISTS_JSON = Path(__file__).parent.parent.parent / 'data' / 'anime-lists' / 'anime-list-full.json'
ANIME_DB_PATH = Path(__file__).parent.parent.parent / 'instance' / 'anime_mapping.db'


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
        CREATE TABLE IF NOT EXISTS anime_mapping (
            kitsu_id INTEGER,
            mal_id INTEGER,
            imdb_id TEXT,
            tvdb_season INTEGER,
            PRIMARY KEY (kitsu_id, mal_id)
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS metadata (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    ''')
    
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_kitsu ON anime_mapping(kitsu_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_mal ON anime_mapping(mal_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_imdb ON anime_mapping(imdb_id)')
    
    conn.commit()
    return conn


def update_database():
    """Update database if JSON file changed"""
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
        
        if kitsu_id or mal_id:
            cursor.execute(
                'INSERT OR REPLACE INTO anime_mapping (kitsu_id, mal_id, imdb_id, tvdb_season) VALUES (?, ?, ?, ?)',
                (kitsu_id, mal_id, imdb_id, tvdb_season)
            )
    
    cursor.execute('INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)', ('json_hash', current_hash))
    conn.commit()
    conn.close()
    return True


def get_imdb_from_kitsu(kitsu_id: int):
    """Get IMDb ID and season from Kitsu ID"""
    if not ANIME_DB_PATH.exists():
        update_database()
    
    conn = sqlite3.connect(ANIME_DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT imdb_id, tvdb_season FROM anime_mapping WHERE kitsu_id = ?', (kitsu_id,))
    row = cursor.fetchone()
    conn.close()
    
    if row and row[0]:
        return {'imdb_id': row[0], 'season': row[1]}
    return None


def get_imdb_from_mal(mal_id: int):
    """Get IMDb ID and season from MAL ID"""
    if not ANIME_DB_PATH.exists():
        update_database()
    
    conn = sqlite3.connect(ANIME_DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT imdb_id, tvdb_season FROM anime_mapping WHERE mal_id = ?', (mal_id,))
    row = cursor.fetchone()
    conn.close()
    
    if row and row[0]:
        return {'imdb_id': row[0], 'season': row[1]}
    return None
