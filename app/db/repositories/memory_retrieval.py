"""
Investment Memory retrieval — reads prior thesis history for a ticker
and produces a MemoryContext used for prompt injection and API response.

All functions follow the null-object pattern: session=None returns None/[].
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Minimum prior queries before memory context is injected.
# First-time and single-query tickers get no memory block.
_MIN_QUERIES_FOR_MEMORY = 2

# Number of recent thesis versions to include in trend data.
_VERSIONS_LOOKBACK = 5

# Number of recent deltas to surface in the context.
_DELTAS_LOOKBACK = 3


# ---------------------------------------------------------------------------
# Raw data reads
# ---------------------------------------------------------------------------

async def _get_recent_versions(session, ticker: str, limit: int) -> List[Any]:
    """Return the N most-recent ThesisVersion rows for a ticker, newest first."""
    try:
        from sqlalchemy import select
        from ..models import ThesisVersion

        stmt = (
            select(ThesisVersion)
            .where(ThesisVersion.ticker == ticker)
            .order_by(ThesisVersion.created_at.desc())
            .limit(limit)
        )
        result = await session.execute(stmt)
        return result.scalars().all()
    except Exception as exc:
        logger.warning("[memory_retrieval] _get_recent_versions failed for %s: %r", ticker, exc)
        return []


async def _get_recent_deltas(session, ticker: str, limit: int) -> List[Any]:
    """Return the N most-recent ThesisDelta rows for a ticker, newest first."""
    try:
        from sqlalchemy import select
        from ..models import ThesisDelta

        stmt = (
            select(ThesisDelta)
            .where(ThesisDelta.ticker == ticker)
            .order_by(ThesisDelta.created_at.desc())
            .limit(limit)
        )
        result = await session.execute(stmt)
        return result.scalars().all()
    except Exception as exc:
        logger.warning("[memory_retrieval] _get_recent_deltas failed for %s: %r", ticker, exc)
        return []


async def _get_ticker_memory(session, ticker: str) -> Optional[Any]:
    """Return TickerMemory row, or None if not found."""
    try:
        from sqlalchemy import select
        from ..models import TickerMemory

        result = await session.execute(
            select(TickerMemory).where(TickerMemory.ticker == ticker)
        )
        return result.scalar_one_or_none()
    except Exception as exc:
        logger.warning("[memory_retrieval] _get_ticker_memory failed for %s: %r", ticker, exc)
        return None


async def _get_concern_tags(session, ticker: str) -> Dict[str, int]:
    """Return {tag_name: mention_count} sorted by frequency."""
    try:
        from sqlalchemy import select
        from ..models import ConcernTag

        result = await session.execute(
            select(ConcernTag)
            .where(ConcernTag.ticker == ticker)
            .order_by(ConcernTag.mention_count.desc())
        )
        return {r.tag_name: (r.mention_count or 0) for r in result.scalars().all()}
    except Exception as exc:
        logger.warning("[memory_retrieval] _get_concern_tags failed for %s: %r", ticker, exc)
        return {}


# ---------------------------------------------------------------------------
# Derived helpers
# ---------------------------------------------------------------------------

def _days_ago(dt: Optional[datetime]) -> Optional[int]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    delta = datetime.now(timezone.utc) - dt
    return max(0, delta.days)


def _conviction_direction(trend: List[float]) -> str:
    """Classify the direction of a conviction series (newest first)."""
    if len(trend) < 2:
        return "stable"
    # Compare newest to oldest in the window
    newest, oldest = trend[0], trend[-1]
    diff = newest - oldest
    if abs(diff) < 0.04:
        return "stable"
    # Check monotonicity for "volatile"
    diffs = [trend[i] - trend[i + 1] for i in range(len(trend) - 1)]
    signs = [1 if d > 0.01 else (-1 if d < -0.01 else 0) for d in diffs]
    non_zero = [s for s in signs if s != 0]
    if len(non_zero) >= 2 and len(set(non_zero)) > 1:
        return "volatile"
    return "rising" if diff > 0 else "falling"


def _notable_events(deltas: List[Any], versions: List[Any]) -> List[str]:
    """Surface the most notable historical events as human-readable strings."""
    events: List[str] = []

    for d in deltas:
        if getattr(d, "stance_changed", False):
            from_s = ""
            to_s = ""
            # Try to look up from/to stances from versions
            for v in versions:
                if v.id == getattr(d, "from_version_id", None):
                    from_s = v.directional_stance
                elif v.id == getattr(d, "to_version_id", None):
                    to_s = v.directional_stance
            stance_note = f"{from_s} → {to_s}" if from_s and to_s else "stance shift"
            days = _days_ago(getattr(d, "created_at", None))
            events.append(
                f"Stance changed ({stance_note})"
                + (f" — {days} days ago" if days is not None else "")
            )

        elif getattr(d, "magnitude", "") == "material":
            delta_pp = round(abs(getattr(d, "conviction_delta", 0)) * 100, 1)
            days = _days_ago(getattr(d, "created_at", None))
            events.append(
                f"Material conviction shift ({delta_pp:+.0f}pp)"
                + (f" — {days} days ago" if days is not None else "")
            )

    return events


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def get_memory_context(
    session,
    ticker: str,
) -> Optional[Dict[str, Any]]:
    """Build and return an investment memory context dict for a ticker.

    Returns None when:
    - session is None (persistence disabled)
    - ticker has fewer than _MIN_QUERIES_FOR_MEMORY prior analyses
    - any retrieval error occurs

    The returned dict is the canonical shape consumed by:
    - ``format_memory_for_prompt()`` → synthesis prompt injection
    - ``MemoryContextSummary`` schema → API response field
    """
    if session is None:
        return None

    try:
        # 1. Aggregate state
        mem = await _get_ticker_memory(session, ticker)
        if mem is None or (mem.total_queries or 0) < _MIN_QUERIES_FOR_MEMORY:
            return None

        # 2. Recent versions (newest first)
        versions = await _get_recent_versions(session, ticker, _VERSIONS_LOOKBACK)
        if not versions:
            return None

        # 3. Recent deltas
        deltas = await _get_recent_deltas(session, ticker, _DELTAS_LOOKBACK)

        # 4. Concern distribution
        concern_dist = await _get_concern_tags(session, ticker)

        # ── Derived fields ──────────────────────────────────────────────────
        stance_history = [v.directional_stance for v in versions]
        conviction_trend = [round(float(v.confidence_score), 4) for v in versions]
        conviction_direction = _conviction_direction(conviction_trend)

        # Coverage window: now → oldest loaded version
        oldest_version = versions[-1]
        first_seen_at = getattr(oldest_version, "created_at", None)
        days_in_coverage = _days_ago(first_seen_at) or 0

        # Count all historical stance changes
        stance_changes_total = sum(
            1 for d in deltas if getattr(d, "stance_changed", False)
        )
        # If we have fewer deltas than loaded, trust ticker_memory for total
        # (deltas loaded is a sample; a more accurate count would need a COUNT query)

        # Last delta summary
        last_delta_magnitude: Optional[str] = None
        last_delta_days_ago: Optional[int] = None
        if deltas:
            last_delta = deltas[0]
            last_delta_magnitude = getattr(last_delta, "magnitude", None)
            last_delta_days_ago = _days_ago(getattr(last_delta, "created_at", None))

        notable = _notable_events(deltas, list(versions))

        # Version IDs for potential future deep-link
        version_ids = [v.id for v in versions]

        return {
            "ticker": ticker,
            "total_queries": int(mem.total_queries or 0),
            "days_in_coverage": days_in_coverage,
            "stance_history": stance_history,
            "conviction_trend": conviction_trend,
            "conviction_direction": conviction_direction,
            "dominant_concern": str(mem.dominant_concern or ""),
            "concern_distribution": concern_dist,
            "last_delta_magnitude": last_delta_magnitude,
            "last_delta_days_ago": last_delta_days_ago,
            "stance_changes_total": stance_changes_total,
            "notable_events": notable,
            "version_ids": version_ids,
        }

    except Exception as exc:
        logger.warning("[memory_retrieval] get_memory_context failed for %s: %r", ticker, exc)
        return None
