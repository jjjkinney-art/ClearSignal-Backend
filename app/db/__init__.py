"""
Phase 9A persistence layer.

Public surface
--------------
    from app.db import init_db, close_db, get_session

``init_db(url)``  — call once at startup (lifespan).  No-op when url is empty.
``close_db()``    — call once at shutdown.  No-op when db is disabled.
``get_session``   — async context manager yielding an AsyncSession.

When DATABASE_URL is empty the entire layer is disabled: ``get_session``
yields ``None`` and all repositories / persistence calls are silent no-ops.
"""

from .connection import init_db, close_db, get_session

__all__ = ["init_db", "close_db", "get_session"]
