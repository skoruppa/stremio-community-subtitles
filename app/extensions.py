"""Async extensions for Quart application"""
import os
import functools
import hashlib
import json
import time as _time
import logging

try:
    import orjson as _json

    def _dumps(obj):
        return _json.dumps(obj, default=str).decode()

    def _loads(raw):
        return _json.loads(raw)
except ImportError:
    import json as _json_stdlib

    def _dumps(obj):
        return _json_stdlib.dumps(obj, default=str)

    def _loads(raw):
        return _json_stdlib.loads(raw)

import json  # used for stable cache key hashing in memoize

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base
from quart_auth import QuartAuth
from quart_cors import cors as quart_cors
from quart_wtf import CSRFProtect
from quart_babel import Babel

logger = logging.getLogger(__name__)

# SQLAlchemy async
Base = declarative_base()
async_engine = None
async_session_maker = None

def init_async_db(app):
    global async_engine, async_session_maker
    
    database_url = app.config['SQLALCHEMY_DATABASE_URI']
    
    if database_url.startswith('postgresql://'):
        database_url = database_url.replace('postgresql://', 'postgresql+asyncpg://')
    elif database_url.startswith('mysql://'):
        database_url = database_url.replace('mysql://', 'mysql+aiomysql://')
    elif database_url.startswith('sqlite:///'):
        database_url = database_url.replace('sqlite:///', 'sqlite+aiosqlite:///')
    
    connect_args = {}
    if database_url.startswith('mysql+aiomysql://'):
        connect_args = {
            'connect_timeout': 10,
        }
    
    async_engine = create_async_engine(
        database_url,
        echo=app.config.get('SQLALCHEMY_ECHO', False),
        pool_size=app.config.get('SQLALCHEMY_POOL_SIZE', 5),
        max_overflow=app.config.get('SQLALCHEMY_MAX_OVERFLOW', 10),
        pool_pre_ping=app.config.get('SQLALCHEMY_POOL_PRE_PING', False),
        pool_recycle=app.config.get('SQLALCHEMY_POOL_RECYCLE', 150),
        pool_timeout=app.config.get('SQLALCHEMY_POOL_TIMEOUT', 30),
        pool_reset_on_return='rollback',
        connect_args=connect_args,
    )
    
    async_session_maker = async_sessionmaker(
        async_engine,
        class_=AsyncSession,
        expire_on_commit=False
    )
    
    return async_engine, async_session_maker

auth_manager = QuartAuth()
csrf = CSRFProtect()
babel = Babel()

def init_cors(app):
    cors_origins = app.config.get('CORS_ORIGINS', '*')
    allow_credentials = cors_origins != '*'
    return quart_cors(
        app,
        allow_origin=cors_origins,
        allow_credentials=allow_credentials
    )


class AsyncCache:
    """Two-tier cache: L1 in-process dict + L2 Redis (shared across workers).
    
    Falls back gracefully to L1-only when Redis is unavailable.
    Designed for multiprocessing Hypercorn workers where each process
    needs fast local access but also benefits from shared state.
    """

    # L1 in-process TTL (seconds). Kept short so workers converge quickly.
    L1_DEFAULT_TTL = 30
    # Max L1 entries before forced eviction of oldest
    L1_MAX_SIZE = 2000
    # How often to run passive cleanup (every N set() calls)
    _CLEANUP_INTERVAL = 100

    def __init__(self):
        self._local = {}          # key -> (value, expires_at)
        self._redis = None        # set by init_redis()
        self._redis_available = False
        self._set_counter = 0

    # ------------------------------------------------------------------
    # Redis bootstrap
    # ------------------------------------------------------------------
    def init_redis(self, redis_url: str):
        """Connect to Redis. Safe to call multiple times."""
        try:
            import redis as _redis
            self._redis = _redis.Redis.from_url(
                redis_url,
                decode_responses=True,
                socket_connect_timeout=2,
                socket_timeout=1,
                retry_on_timeout=True,
            )
            self._redis.ping()
            self._redis_available = True
            logger.info("Redis cache connected: %s", redis_url)
        except Exception as exc:
            logger.warning("Redis unavailable (%s) — falling back to local cache", exc)
            self._redis = None
            self._redis_available = False

    # ------------------------------------------------------------------
    # Core API
    # ------------------------------------------------------------------
    async def get(self, key: str):
        # L1 check
        entry = self._local.get(key)
        if entry is not None:
            value, expires_at = entry
            if expires_at and _time.monotonic() > expires_at:
                del self._local[key]
            else:
                return value

        # L2 check
        if self._redis_available:
            try:
                raw = self._redis.get(key)
                if raw is not None:
                    value = _loads(raw)
                    # Populate L1
                    l1_exp = _time.monotonic() + self.L1_DEFAULT_TTL
                    self._local[key] = (value, l1_exp)
                    return value
            except Exception:
                pass

        return None

    async def set(self, key: str, value, timeout=None):
        # Periodic L1 cleanup to prevent memory leaks
        self._set_counter += 1
        if self._set_counter >= self._CLEANUP_INTERVAL:
            self._set_counter = 0
            self._evict_expired()

        # L1
        l1_ttl = min(timeout, self.L1_DEFAULT_TTL) if timeout else self.L1_DEFAULT_TTL
        expires_at = _time.monotonic() + l1_ttl
        self._local[key] = (value, expires_at)

        # Enforce max size — drop oldest entries if over limit
        if len(self._local) > self.L1_MAX_SIZE:
            self._evict_oldest(len(self._local) - self.L1_MAX_SIZE)

        # L2
        if self._redis_available:
            try:
                raw = _dumps(value)
                if timeout:
                    self._redis.setex(key, int(timeout), raw)
                else:
                    self._redis.set(key, raw)
            except Exception:
                pass

    async def delete(self, key: str):
        self._local.pop(key, None)
        if self._redis_available:
            try:
                self._redis.delete(key)
            except Exception:
                pass

    def _evict_expired(self):
        """Remove all expired entries from L1."""
        now = _time.monotonic()
        expired = [k for k, (_, exp) in self._local.items() if exp and now > exp]
        for k in expired:
            del self._local[k]

    def _evict_oldest(self, count):
        """Remove the `count` entries with the earliest expiry from L1."""
        if count <= 0:
            return
        sorted_keys = sorted(
            self._local.keys(),
            key=lambda k: self._local[k][1] or 0
        )
        for k in sorted_keys[:count]:
            del self._local[k]

    def clear(self):
        self._local.clear()
        if self._redis_available:
            try:
                self._redis.flushdb()
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Decorator
    # ------------------------------------------------------------------
    def memoize(self, timeout=None):
        def decorator(func):
            @functools.wraps(func)
            async def wrapper(*args, **kwargs):
                cache_key = f"{func.__module__}.{func.__name__}:{hashlib.md5(json.dumps([args, kwargs], default=str).encode()).hexdigest()}"
                cached = await self.get(cache_key)
                if cached is not None:
                    return cached
                result = await func(*args, **kwargs)
                if result is not None:
                    await self.set(cache_key, result, timeout)
                return result
            return wrapper
        return decorator


cache = AsyncCache()


def init_cache(app):
    """Initialize cache with Redis if available. Call from app factory."""
    redis_url = os.environ.get('REDIS_URL') or app.config.get('REDIS_URL')
    if redis_url:
        cache.init_redis(redis_url)
    else:
        logger.info("No REDIS_URL configured — using local-only cache")


# For Alembic migrations (sync)
from sqlalchemy import create_engine, pool

def get_sync_engine(database_url):
    return create_engine(database_url, poolclass=pool.NullPool)
