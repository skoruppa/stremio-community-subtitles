"""
Auto-migration for schema changes.

Runs at app startup with a synchronous connection (before async engine is used).
Each migration checks if a column/table already exists before altering,
so it's safe to run repeatedly.

Add new migrations to MIGRATIONS list below.
"""
import logging
from sqlalchemy import create_engine, text, inspect, pool

logger = logging.getLogger(__name__)


def _sync_url(database_url: str) -> str:
    """Convert async driver URL to sync driver for startup migrations."""
    url = database_url
    url = url.replace('mysql+aiomysql://', 'mysql+pymysql://')
    url = url.replace('postgresql+asyncpg://', 'postgresql+psycopg2://')
    url = url.replace('sqlite+aiosqlite://', 'sqlite:///')
    return url


def _add_column_if_missing(conn, inspector, table: str, column: str, col_type: str, default=None):
    """Add a column to a table if it doesn't exist yet."""
    existing = [c['name'] for c in inspector.get_columns(table)]
    if column in existing:
        return False
    
    default_clause = ''
    if default is not None:
        default_clause = f' DEFAULT {default}'
    
    conn.execute(text(f'ALTER TABLE {table} ADD COLUMN {column} {col_type}{default_clause}'))
    logger.info(f"Auto-migration: added column {table}.{column}")
    return True


# ------------------------------------------------------------------
# List of migrations — append new ones at the bottom
# ------------------------------------------------------------------

def _migrate_return_all_results(conn, inspector):
    """v2024.09: Add return_all_results boolean to users."""
    _add_column_if_missing(conn, inspector, 'users', 'return_all_results', 'BOOLEAN', default='0')


# Ordered list — each entry is called once per startup
MIGRATIONS = [
    _migrate_return_all_results,
]


def run_auto_migrations(database_url: str):
    """Execute all pending schema migrations."""
    sync_url = _sync_url(database_url)
    engine = create_engine(sync_url, poolclass=pool.NullPool)
    
    try:
        with engine.connect() as conn:
            inspector = inspect(engine)
            
            # Only run if users table exists (fresh installs use init-db instead)
            if 'users' not in inspector.get_table_names():
                return
            
            for migration_fn in MIGRATIONS:
                try:
                    migration_fn(conn, inspector)
                except Exception as e:
                    logger.warning(f"Migration {migration_fn.__name__} failed: {e}")
            
            conn.commit()
    finally:
        engine.dispose()
