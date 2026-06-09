"""
Concern repository — CRUD for concern_tags.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Set

logger = logging.getLogger(__name__)


async def upsert_tag(
    session,
    ticker: str,
    tag_name: str,
) -> Optional[Any]:
    """Increment the mention count for (ticker, tag_name), inserting if absent.

    Returns the ConcernTag row, or None on failure / disabled session.
    """
    if session is None:
        return None

    try:
        from sqlalchemy import select
        from ..models import ConcernTag

        now = datetime.now(timezone.utc)

        stmt = (
            select(ConcernTag)
            .where(ConcernTag.ticker == ticker)
            .where(ConcernTag.tag_name == tag_name)
        )
        result = await session.execute(stmt)
        row = result.scalar_one_or_none()

        if row is None:
            row = ConcernTag(
                id=str(uuid.uuid4()),
                ticker=ticker,
                tag_name=tag_name,
                mention_count=1,
                first_seen_at=now,
                last_seen_at=now,
                created_at=now,
            )
            session.add(row)
        else:
            row.mention_count = (row.mention_count or 0) + 1
            row.last_seen_at = now

        await session.flush()
        return row

    except Exception as exc:
        logger.warning("[concern_repo] upsert_tag failed for %s/%s: %r", ticker, tag_name, exc)
        return None


async def upsert_tags(
    session,
    ticker: str,
    tag_names: Set[str],
) -> Dict[str, Any]:
    """Upsert multiple tags at once.  Returns dict of tag_name → row (or empty on error)."""
    results: Dict[str, Any] = {}
    for tag_name in tag_names:
        row = await upsert_tag(session, ticker, tag_name)
        if row is not None:
            results[tag_name] = row
    return results


async def get_tags_for_ticker(
    session,
    ticker: str,
) -> Dict[str, int]:
    """Return a mapping of tag_name → mention_count for a ticker.

    Returns empty dict when persistence is disabled or on error.
    """
    if session is None:
        return {}

    try:
        from sqlalchemy import select
        from ..models import ConcernTag

        stmt = (
            select(ConcernTag)
            .where(ConcernTag.ticker == ticker)
            .order_by(ConcernTag.mention_count.desc())
        )
        result = await session.execute(stmt)
        rows = result.scalars().all()
        return {r.tag_name: (r.mention_count or 0) for r in rows}

    except Exception as exc:
        logger.warning("[concern_repo] get_tags_for_ticker failed for %s: %r", ticker, exc)
        return {}
