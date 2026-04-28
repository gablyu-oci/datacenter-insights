"""
Alembic env.py — async-aware configuration for SQLModel + asyncpg.

Reads DATABASE_URL from backend/.env via our Settings class, swaps the
asyncpg driver for psycopg2 (sync) when Alembic CLI runs migrations
(Alembic's CLI is synchronous).  For autogenerate, imports all models
so SQLModel.metadata contains every table.
"""
import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool
from sqlmodel import SQLModel

# ── Import ALL models so SQLModel.metadata picks them up ────────────────
import sys
from pathlib import Path

# Ensure backend/ is on sys.path so `db.models`, `config` are importable
_backend_dir = str(Path(__file__).resolve().parent.parent)
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

from db.models import *  # noqa: F401,F403  — side-effect: registers tables
from config import Settings

# ── Alembic Config object ──────────────────────────────────────────────
config = context.config

# Interpret the config file for Python logging.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Target metadata for autogenerate
target_metadata = SQLModel.metadata

# ── Build sync database URL from settings ──────────────────────────────
_settings = Settings()
_sync_url = _settings.database_url.replace(
    "postgresql+asyncpg://", "postgresql+psycopg2://"
).replace(
    "postgresql+aiopg://", "postgresql+psycopg2://"
)
config.set_main_option("sqlalchemy.url", _sync_url)

# Exclude PostGIS system tables from autogenerate diffs
_EXCLUDE_TABLES = {"spatial_ref_sys"}


def include_object(object, name, type_, reflected, compare_to):
    if type_ == "table" and name in _EXCLUDE_TABLES:
        return False
    return True


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode — emit SQL to stdout."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_object=include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode — connect to DB."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_object=include_object,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
