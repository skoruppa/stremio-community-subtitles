"""Async extensions for Quart application"""
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base
from quart_auth import QuartAuth
from quart_cors import cors as quart_cors
from quart_wtf import CSRFProtect

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
    
    async_engine = create_async_engine(
        database_url,
        echo=app.config.get('SQLALCHEMY_ECHO', False),
        pool_size=app.config.get('SQLALCHEMY_POOL_SIZE', 2),
        max_overflow=app.config.get('SQLALCHEMY_MAX_OVERFLOW', 3),
        pool_pre_ping=True,
        pool_recycle=3600,
    )
    
    async_session_maker = async_sessionmaker(
        async_engine,
        class_=AsyncSession,
        expire_on_commit=False
    )
    
    return async_engine, async_session_maker

auth_manager = QuartAuth()
csrf = CSRFProtect()

def init_cors(app):
    cors_origins = app.config.get('CORS_ORIGINS', '*')
    allow_credentials = cors_origins != '*'
    return quart_cors(
        app,
        allow_origin=cors_origins,
        allow_credentials=allow_credentials
    )

import functools
import hashlib
import json

class AsyncCache:
    def __init__(self):
        self._cache = {}
    
    async def get(self, key):
        return self._cache.get(key)
    
    async def set(self, key, value, timeout=None):
        self._cache[key] = value
    
    async def delete(self, key):
        self._cache.pop(key, None)
    
    def clear(self):
        self._cache.clear()
    
    def memoize(self, timeout=None):
        def decorator(func):
            @functools.wraps(func)
            async def wrapper(*args, **kwargs):
                cache_key = f"{func.__module__}.{func.__name__}:{hashlib.md5(json.dumps([args, kwargs], default=str).encode()).hexdigest()}"
                cached = await self.get(cache_key)
                if cached is not None:
                    return cached
                result = await func(*args, **kwargs)
                await self.set(cache_key, result, timeout)
                return result
            return wrapper
        return decorator

cache = AsyncCache()

# For Alembic migrations (sync)
from sqlalchemy import create_engine, pool

def get_sync_engine(database_url):
    return create_engine(database_url, poolclass=pool.NullPool)
