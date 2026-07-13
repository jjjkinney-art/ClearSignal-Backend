"""Alembic migration environment (async, Sprint 1A).

Resolves the database URL from settings.database_url (env / .env) first, then the
alembic.ini fallback, then a per-invocation override on the Config
(`sqlalchemy.url`, used by the test-suite).  Uses an async engine so the same
pinned drivers as the app (asyncpg / aiosqlite) are used for migrations.

target_metadata = app.db.models.Base.metadata so `alembic revision --autogenerate`
diffs future migrations against the models.
"""
from __future__ import annotations

import asyncio
import os
import sys
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import create_async_engine

# Repo root on sys.path so `import app.*` works when alembic is invoked from anywhere.
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from app.db.models import Base  # noqa: E402

config = context.config
if config.config_file_name is not None:
    try:
        fileConfig(config.config_file_name)
    except Exception:
        pass

target_metadata = Base.metadata


def _resolve_url() -> str:
    # Priority: explicit Config override (tests) → settings.database_url → ini.
    override = config.get_main_option("sqlalchemy.url")
    if override:
        return override
    try:
        from app.config import settings
        if settings.database_url:
            return settings.database_url
    except Exception:
        pass
    return ""


def run_migrations_offline() -> None:
    url = _resolve_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def _do_run_migrations(connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        # SQLite cannot ALTER in place; batch mode rebuilds the table safely.
        render_as_batch=connection.dialect.name == "sqlite",
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    url = _resolve_url()
    if not url:
        raise RuntimeError(
            "No database URL. Set DATABASE_URL (env/.env) before running migrations."
        )
    connectable = create_async_engine(url, poolclass=pool.NullPool)
    async with connectable.connect() as connection:
        await connection.run_sync(_do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
