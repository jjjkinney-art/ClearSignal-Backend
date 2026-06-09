"""
Async SQLAlchemy engine management with graceful degradation.

When ``database_url`` is empty the module operates in "disabled" mode:
- ``init_db()`` and ``close_db()`` are silent no-ops.
- ``get_session()`` is an async context manager that yields ``None``.

All repository callers check ``if session is None: return`` so the API
functions correctly with no database configured.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Optional

logger = logging.getLogger(__name__)

# Module-level singletons — populated by init_db(), cleared by close_db().
_engine = None  # type: Optional[Any]
_session_factory = None  # type: Optional[Any]
_db_enabled: bool = False


async def init_db(database_url: str) -> None:
    """Create the async engine and session factory; run table DDL.

    Parameters
    ----------
    database_url:
        SQLAlchemy URL string.  Examples:
            ``postgresql+asyncpg://user:pass@host/dbname``
            ``sqlite+aiosqlite:///./dev.db``
        Pass an empty string to skip initialisation (null-object mode).
    """
    global _engine, _session_factory, _db_enabled

    if not database_url:
        logger.info("[db] DATABASE_URL not set — persistence layer disabled (null-object mode)")
        return

    try:
        from sqlalchemy.ext.asyncio import (
            create_async_engine,
            async_sessionmaker,
            AsyncSession,
        )
        from .models import Base

        connect_args: dict = {}
        if database_url.startswith("sqlite"):
            # SQLite: allow shared access across threads used by asyncio executor
            connect_args["check_same_thread"] = False

        _engine = create_async_engine(
            database_url,
            echo=False,
            pool_pre_ping=True,
            connect_args=connect_args,
        )

        _session_factory = async_sessionmaker(
            bind=_engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
        )

        # Create all tables that don't yet exist (idempotent).
        async with _engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        _db_enabled = True
        logger.info("[db] persistence layer initialised — %s", database_url.split("@")[-1])

    except Exception as exc:  # pragma: no cover
        logger.error("[db] init_db failed — persistence disabled: %r", exc)
        _engine = None
        _session_factory = None
        _db_enabled = False


async def close_db() -> None:
    """Dispose the engine connection pool at application shutdown."""
    global _engine, _session_factory, _db_enabled
    if _engine is not None:
        await _engine.dispose()
        logger.info("[db] engine disposed")
    _engine = None
    _session_factory = None
    _db_enabled = False


@asynccontextmanager
async def get_session() -> AsyncGenerator:
    """Async context manager that yields an AsyncSession or None.

    Usage::

        async with get_session() as session:
            if session is None:
                return  # persistence disabled
            # use session normally

    Yields ``None`` when persistence is disabled so callers can guard
    with a single ``if session is None: return`` check.
    """
    if not _db_enabled or _session_factory is None:
        yield None
        return

    async with _session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


# Type alias for annotations in other modules
from typing import Any  # noqa: E402 — must be after function definitions
