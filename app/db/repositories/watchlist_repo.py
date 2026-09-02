"""
Watchlist membership repository — Phase 10B · Slice 2.

All functions accept an AsyncSession as the first positional argument.
Passing None is safe: every function returns an empty/falsy value instead
of raising.  This mirrors the ``session is None → return safe default``
contract used throughout the loop repos.

Deduplication is application-level: ``ticker_add`` checks for an existing
(user_id, ticker) row before inserting.  There is no DB-level unique index
on the nullable user_id column because NULL != NULL in most SQL dialects,
which makes such an index unreliable for the global-watchlist (user_id=NULL)
use case.

Because that check-then-insert is not atomic, two concurrent adds for the
same (user_id, ticker) can both observe "no row" and both insert.  Nothing
in the schema prevents the resulting pair.  These helpers therefore select
DEFENSIVELY: they resolve the oldest matching row rather than asserting that
exactly one exists, so a duplicate degrades to a warning instead of raising
MultipleResultsFound and permanently breaking add/remove for that ticker.

Tolerance is not a fix for the race — only a unique index can close it, and
that requires a migration.  It bounds the blast radius until one exists.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _owner_clause(model, user_id: Optional[str]):
    """Ownership predicate. NULL user_id is the global/legacy watchlist."""
    return (
        model.user_id == user_id
        if user_id is not None
        else model.user_id.is_(None)
    )


def _membership_stmt(model, ticker: str, user_id: Optional[str]):
    """Deterministically ordered membership query for one (user_id, ticker).

    Ordered oldest-first so that, if duplicates exist, every call site agrees
    on which row is authoritative.
    """
    from sqlalchemy import select

    return (
        select(model)
        .where(model.ticker == ticker)
        .where(_owner_clause(model, user_id))
        .order_by(model.added_at.asc(), model.id.asc())
    )


def _resolve_one(rows: List, ticker: str, user_id: Optional[str]):
    """Return the authoritative row, warning (not raising) on duplicates.

    Deliberately replaces ``scalar_one_or_none()``. With no unique index the
    duplicate case is reachable, and raising there would make the ticker
    impossible to add or remove through the API — a permanent, unrecoverable
    state for that user. Logs an opaque count; never logs account contents.
    """
    if not rows:
        return None
    if len(rows) > 1:
        logger.warning(
            "[watchlist] %d duplicate rows for ticker=%s (scoped=%s); "
            "using oldest. A unique index is required to prevent this.",
            len(rows), ticker, user_id is not None,
        )
    return rows[0]


def _to_naive_utc(dt: Optional[datetime]) -> Optional[datetime]:
    """Strip timezone info for SQLite-safe comparisons."""
    if dt is None:
        return None
    if dt.tzinfo is not None:
        return dt.replace(tzinfo=None)
    return dt


# ---------------------------------------------------------------------------
# § MEMBERSHIP
# ---------------------------------------------------------------------------

async def ticker_add(
    session,
    ticker: str,
    company_name: str = "",
    user_id: Optional[str] = None,
):
    """Add a ticker to the watchlist.  Idempotent.

    - If an active row already exists: returns it unchanged.
    - If an inactive row exists: reactivates it and returns the updated row.
    - Otherwise: inserts a new row.

    Returns the WatchedTicker row, or None when session is None.
    """
    if session is None:
        return None

    from app.db.models import WatchedTicker
    from sqlalchemy import select

    t = ticker.strip().upper()

    stmt = _membership_stmt(WatchedTicker, t, user_id).execution_options(
        populate_existing=True
    )
    result = await session.execute(stmt)
    row = _resolve_one(list(result.scalars().all()), t, user_id)

    if row is not None:
        if not row.active:
            row.active = True
            row.company_name = company_name or row.company_name
            row.updated_at = _now()
            await session.flush()
            await session.execute(
                select(WatchedTicker)
                .where(WatchedTicker.id == row.id)
                .execution_options(populate_existing=True)
            )
        return row

    row = WatchedTicker(
        ticker=t,
        company_name=company_name or t,
        user_id=user_id,
        active=True,
    )
    session.add(row)
    await session.flush()
    return row


async def ticker_deactivate(
    session,
    ticker: str,
    user_id: Optional[str] = None,
) -> bool:
    """Soft-delete: set active=False.

    Returns True if a row was found and deactivated, False otherwise.

    Deactivates EVERY row for this (user_id, ticker). With no unique index a
    duplicate pair is reachable; deactivating only one would leave the ticker
    still on the watchlist after the user removed it, which is the wrong
    observable behaviour. With no duplicates this is identical to before.
    """
    if session is None:
        return False

    from app.db.models import WatchedTicker

    t = ticker.strip().upper()
    result = await session.execute(_membership_stmt(WatchedTicker, t, user_id))
    rows = list(result.scalars().all())

    if not rows:
        return False
    if len(rows) > 1:
        logger.warning(
            "[watchlist] deactivating %d duplicate rows for ticker=%s "
            "(scoped=%s)", len(rows), t, user_id is not None,
        )

    now = _now()
    for row in rows:
        row.active = False
        row.updated_at = now
    await session.flush()
    return True


async def ticker_get(
    session,
    ticker: str,
    user_id: Optional[str] = None,
):
    """Return the WatchedTicker row (active or inactive) or None.

    Resolves the oldest row when duplicates exist rather than raising.
    """
    if session is None:
        return None

    from app.db.models import WatchedTicker

    t = ticker.strip().upper()
    stmt = _membership_stmt(WatchedTicker, t, user_id).execution_options(
        populate_existing=True
    )
    result = await session.execute(stmt)
    return _resolve_one(list(result.scalars().all()), t, user_id)


async def ticker_list_active(
    session,
    user_id: Optional[str] = None,
) -> List:
    """Return all active WatchedTicker rows ordered by added_at ascending."""
    if session is None:
        return []

    from app.db.models import WatchedTicker
    from sqlalchemy import select

    stmt = (
        select(WatchedTicker)
        .where(WatchedTicker.active.is_(True))
        .where(
            WatchedTicker.user_id == user_id
            if user_id is not None
            else WatchedTicker.user_id.is_(None)
        )
        .order_by(WatchedTicker.added_at)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def ticker_is_active(
    session,
    ticker: str,
    user_id: Optional[str] = None,
) -> bool:
    """Return True if the ticker exists with active=True."""
    row = await ticker_get(session, ticker, user_id)
    return row is not None and bool(row.active)


# ---------------------------------------------------------------------------
# § BACKFILL
# ---------------------------------------------------------------------------

async def backfill_from_index(
    session,
    index_path: str,
    user_id: Optional[str] = None,
) -> int:
    """Backfill watched_tickers from a flat-file index.json.

    Idempotent: skips tickers that already have a row (active or inactive).
    Preserves added_at from the file when present.

    Returns the count of new rows inserted.
    """
    if session is None:
        return 0

    path = Path(index_path)
    if not path.exists():
        logger.warning("backfill_from_index: %s not found", index_path)
        return 0

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("backfill_from_index: could not read %s: %s", index_path, exc)
        return 0

    if not isinstance(data, dict):
        return 0

    from app.db.models import WatchedTicker
    from sqlalchemy import select

    inserted = 0
    for raw_ticker, entry in data.items():
        t = raw_ticker.strip().upper()
        if not t:
            continue

        result = await session.execute(_membership_stmt(WatchedTicker, t, user_id))
        existing = _resolve_one(list(result.scalars().all()), t, user_id)
        if existing is not None:
            continue

        added_at: Optional[datetime] = None
        company_name = t
        if isinstance(entry, dict):
            company_name = entry.get("company_name") or t
            raw_ts = entry.get("added_at", "")
            if raw_ts:
                try:
                    added_at = datetime.fromisoformat(raw_ts.replace("Z", "+00:00"))
                except Exception:
                    pass

        row = WatchedTicker(
            ticker=t,
            company_name=company_name,
            user_id=user_id,
            active=True,
        )
        if added_at is not None:
            row.added_at = added_at

        session.add(row)
        inserted += 1

    if inserted:
        await session.flush()

    logger.info("backfill_from_index: inserted %d rows from %s", inserted, index_path)
    return inserted
