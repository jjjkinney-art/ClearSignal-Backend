"""
Memory repository — CRUD for ticker_memory and memory_entries.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


async def get_or_create_memory(
    session,
    ticker: str,
    company_name: str = "",
) -> Optional[Any]:
    """Return the TickerMemory row for a ticker, creating it if it doesn't exist.

    Returns None when session is None.
    """
    if session is None:
        return None

    try:
        from sqlalchemy import select
        from ..models import TickerMemory

        stmt = select(TickerMemory).where(TickerMemory.ticker == ticker)
        result = await session.execute(stmt)
        row = result.scalar_one_or_none()

        if row is None:
            row = TickerMemory(
                id=str(uuid.uuid4()),
                ticker=ticker,
                company_name=company_name or ticker,
                total_queries=0,
                version_count=0,
                last_stance="",
                last_confidence=0.0,
                dominant_concern="",
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
            session.add(row)
            await session.flush()
            logger.debug("[memory_repo] created ticker_memory for %s", ticker)

        return row

    except Exception as exc:
        logger.warning("[memory_repo] get_or_create_memory failed for %s: %r", ticker, exc)
        return None


async def update_memory(
    session,
    ticker: str,
    stance: str = "",
    confidence: float = 0.0,
    dominant_concern: str = "",
    increment_queries: bool = True,
    increment_versions: bool = False,
) -> None:
    """Update TickerMemory aggregate fields after a new analysis.

    No-op when session is None.
    """
    if session is None:
        return

    try:
        from sqlalchemy import select
        from ..models import TickerMemory

        stmt = select(TickerMemory).where(TickerMemory.ticker == ticker)
        result = await session.execute(stmt)
        row = result.scalar_one_or_none()
        if row is None:
            return

        now = datetime.now(timezone.utc)
        row.last_query_at = now
        row.updated_at = now
        if stance:
            row.last_stance = stance
        if confidence:
            row.last_confidence = confidence
        if dominant_concern:
            row.dominant_concern = dominant_concern
        if increment_queries:
            row.total_queries = (row.total_queries or 0) + 1
        if increment_versions:
            row.version_count = (row.version_count or 0) + 1

        await session.flush()

    except Exception as exc:
        logger.warning("[memory_repo] update_memory failed for %s: %r", ticker, exc)


async def append_entry(
    session,
    ticker: str,
    session_id: str,
    entry_type: str,
    content: str,
    metadata: Optional[Dict[str, Any]] = None,
) -> Optional[Any]:
    """Insert a MemoryEntry row.

    Returns the new row, or None on failure / disabled session.
    """
    if session is None:
        return None

    try:
        from ..models import MemoryEntry

        row = MemoryEntry(
            id=str(uuid.uuid4()),
            ticker=ticker,
            session_id=session_id,
            entry_type=entry_type,
            content=content,
            metadata_json=json.dumps(metadata or {}),
            created_at=datetime.now(timezone.utc),
        )
        session.add(row)
        await session.flush()
        return row

    except Exception as exc:
        logger.warning("[memory_repo] append_entry failed for %s: %r", ticker, exc)
        return None


async def get_history(
    session,
    ticker: str,
    limit: int = 20,
    entry_type: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Return the N most-recent MemoryEntry rows for a ticker.

    Returns an empty list when persistence is disabled or on error.
    """
    if session is None:
        return []

    try:
        from sqlalchemy import select
        from ..models import MemoryEntry

        stmt = select(MemoryEntry).where(MemoryEntry.ticker == ticker)
        if entry_type:
            stmt = stmt.where(MemoryEntry.entry_type == entry_type)
        stmt = stmt.order_by(MemoryEntry.created_at.desc()).limit(limit)

        result = await session.execute(stmt)
        rows = result.scalars().all()
        return [
            {
                "id": r.id,
                "ticker": r.ticker,
                "session_id": r.session_id,
                "entry_type": r.entry_type,
                "content": r.content,
                "metadata": json.loads(r.metadata_json or "{}"),
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]

    except Exception as exc:
        logger.warning("[memory_repo] get_history failed for %s: %r", ticker, exc)
        return []
