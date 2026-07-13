"""Read-only Alembic migration-status check for startup (Sprint 1A).

Startup NO LONGER mutates the schema.  It only *reports* whether the connected
database is at the Alembic head so operators see a loud warning if migrations
were not run as the deploy step.  Nothing here issues DDL.
"""
from __future__ import annotations

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _alembic_config():
    from alembic.config import Config
    cfg = Config(os.path.join(_ROOT, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(_ROOT, "alembic"))
    return cfg


def head_revision() -> Optional[str]:
    """Resolve the head revision from the migration scripts (no DB access)."""
    try:
        from alembic.script import ScriptDirectory
        return ScriptDirectory.from_config(_alembic_config()).get_current_head()
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("[db] could not resolve Alembic head: %r", exc)
        return None


async def current_db_revision(engine) -> Optional[str]:
    """Read alembic_version.version_num from the DB, or None if not stamped."""
    from sqlalchemy import text
    try:
        async with engine.connect() as conn:
            res = await conn.execute(text("SELECT version_num FROM alembic_version"))
            row = res.fetchone()
            return row[0] if row else None
    except Exception:
        # Table absent → the DB is not under Alembic control yet.
        return None


async def log_migration_status(engine) -> str:
    """Compare the DB revision to head and log the result.  Returns one of
    'up_to_date' | 'behind' | 'unmanaged' | 'unknown'.  Never mutates schema."""
    head = head_revision()
    current = await current_db_revision(engine)

    if head is None:
        logger.warning("[db] could not resolve Alembic head revision")
        return "unknown"
    if current is None:
        logger.warning(
            "[db] database is NOT under Alembic control (no alembic_version). "
            "Run `alembic upgrade head` on a fresh DB, or `alembic stamp head` if "
            "the schema already matches, BEFORE serving traffic."
        )
        return "unmanaged"
    if current != head:
        logger.warning(
            "[db] schema is BEHIND head (db=%s head=%s). Run `alembic upgrade head` "
            "as an explicit deploy step.", current, head,
        )
        return "behind"
    logger.info("[db] schema up-to-date at Alembic head %s", head)
    return "up_to_date"
