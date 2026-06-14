"""
Portfolio repository — Phase 10D · Slice 1.

All functions accept an AsyncSession as the first positional argument.
Passing None is safe: every function returns an empty/falsy value instead
of raising.  This mirrors the ``session is None → return safe default``
contract used throughout the loop repos.

Deduplication follows the watched_tickers pattern:
  - ``position_add`` checks for an existing (portfolio_id, ticker) row before
    inserting; re-adding a removed ticker reactivates the existing row.
  - ``portfolio_create`` checks for an existing (user_id, name) row before
    inserting to prevent duplicates on retried startup calls.

No analytical logic lives here — this is pure CRUD.  Exposure projection,
insight generation, and health metrics arrive in later 10D slices.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import List, Optional

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# § PORTFOLIOS
# ---------------------------------------------------------------------------

async def portfolio_create(
    session,
    name: str = "My Portfolio",
    user_id: Optional[str] = None,
    description: Optional[str] = None,
    is_default: bool = False,
):
    """Create a portfolio.  Idempotent on (user_id, name).

    - If a portfolio with the same (user_id, name) already exists: returns it
      unchanged (same insert-or-return discipline as ticker_add).
    - Otherwise: inserts a new row.

    Returns the Portfolio row, or None when session is None.
    """
    if session is None:
        return None

    from app.db.models import Portfolio
    from sqlalchemy import select

    stmt = (
        select(Portfolio)
        .where(Portfolio.name == name)
        .where(
            Portfolio.user_id == user_id
            if user_id is not None
            else Portfolio.user_id.is_(None)
        )
    )
    result = await session.execute(stmt)
    existing = result.scalar_one_or_none()
    if existing is not None:
        return existing

    row = Portfolio(
        name=name,
        user_id=user_id,
        description=description,
        is_default=is_default,
    )
    session.add(row)
    await session.flush()
    return row


async def portfolio_get(
    session,
    portfolio_id: str,
) -> Optional[object]:
    """Return the Portfolio row by id, or None."""
    if session is None:
        return None

    from app.db.models import Portfolio
    from sqlalchemy import select

    result = await session.execute(
        select(Portfolio).where(Portfolio.id == portfolio_id)
    )
    return result.scalar_one_or_none()


async def portfolio_get_default(
    session,
    user_id: Optional[str] = None,
) -> Optional[object]:
    """Return the is_default=True portfolio for the given user, or None."""
    if session is None:
        return None

    from app.db.models import Portfolio
    from sqlalchemy import select

    stmt = (
        select(Portfolio)
        .where(Portfolio.is_default.is_(True))
        .where(
            Portfolio.user_id == user_id
            if user_id is not None
            else Portfolio.user_id.is_(None)
        )
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def portfolio_list(
    session,
    user_id: Optional[str] = None,
) -> List:
    """Return all portfolios for the given user, ordered by created_at."""
    if session is None:
        return []

    from app.db.models import Portfolio
    from sqlalchemy import select

    stmt = (
        select(Portfolio)
        .where(
            Portfolio.user_id == user_id
            if user_id is not None
            else Portfolio.user_id.is_(None)
        )
        .order_by(Portfolio.created_at)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def portfolio_update(
    session,
    portfolio_id: str,
    name: Optional[str] = None,
    description: Optional[str] = None,
) -> Optional[object]:
    """Update portfolio name and/or description.

    Returns the updated row, or None if not found or session is None.
    """
    if session is None:
        return None

    row = await portfolio_get(session, portfolio_id)
    if row is None:
        return None

    if name is not None:
        row.name = name
    if description is not None:
        row.description = description
    row.updated_at = _now()
    await session.flush()
    return row


async def portfolio_delete(
    session,
    portfolio_id: str,
) -> bool:
    """Hard-delete a portfolio row (and its positions by cascade convention).

    Returns True if found and deleted, False otherwise.

    Note: soft-delete is not applied to portfolios themselves (only to
    positions within them) — a deleted portfolio is gone.  Positions are
    deleted explicitly to avoid orphans since there is no DDL cascade.
    """
    if session is None:
        return False

    from app.db.models import Portfolio, PortfolioPosition
    from sqlalchemy import select, delete

    # Remove all positions first (no DDL cascade in SQLite).
    await session.execute(
        delete(PortfolioPosition).where(
            PortfolioPosition.portfolio_id == portfolio_id
        )
    )

    result = await session.execute(
        select(Portfolio).where(Portfolio.id == portfolio_id)
    )
    row = result.scalar_one_or_none()
    if row is None:
        return False

    await session.delete(row)
    await session.flush()
    return True


# ---------------------------------------------------------------------------
# § POSITIONS
# ---------------------------------------------------------------------------

async def position_add(
    session,
    portfolio_id: str,
    ticker: str,
    membership_class: str = "watchlist",
    weight: Optional[float] = None,
    cost_basis: Optional[float] = None,
    shares: Optional[float] = None,
    notes: Optional[str] = None,
):
    """Add a position to a portfolio.  Idempotent on (portfolio_id, ticker).

    - If an active row already exists: returns it unchanged.
    - If an inactive row exists: reactivates it and updates mutable fields.
    - Otherwise: inserts a new row.

    Returns the PortfolioPosition row, or None when session is None.
    """
    if session is None:
        return None

    from app.db.models import PortfolioPosition
    from sqlalchemy import select

    t = ticker.strip().upper()

    stmt = (
        select(PortfolioPosition)
        .where(PortfolioPosition.portfolio_id == portfolio_id)
        .where(PortfolioPosition.ticker == t)
    )
    result = await session.execute(stmt)
    row = result.scalar_one_or_none()

    if row is not None:
        if not row.active:
            row.active = True
            row.membership_class = membership_class
            if weight is not None:
                row.weight = weight
            if cost_basis is not None:
                row.cost_basis = cost_basis
            if shares is not None:
                row.shares = shares
            if notes is not None:
                row.notes = notes
            row.updated_at = _now()
            await session.flush()
        return row

    row = PortfolioPosition(
        portfolio_id=portfolio_id,
        ticker=t,
        membership_class=membership_class,
        weight=weight,
        cost_basis=cost_basis,
        shares=shares,
        notes=notes,
        active=True,
    )
    session.add(row)
    await session.flush()
    return row


async def position_get(
    session,
    portfolio_id: str,
    ticker: str,
) -> Optional[object]:
    """Return the PortfolioPosition row (active or inactive), or None."""
    if session is None:
        return None

    from app.db.models import PortfolioPosition
    from sqlalchemy import select

    t = ticker.strip().upper()
    result = await session.execute(
        select(PortfolioPosition)
        .where(PortfolioPosition.portfolio_id == portfolio_id)
        .where(PortfolioPosition.ticker == t)
    )
    return result.scalar_one_or_none()


async def position_update(
    session,
    portfolio_id: str,
    ticker: str,
    membership_class: Optional[str] = None,
    weight: Optional[float] = None,
    cost_basis: Optional[float] = None,
    shares: Optional[float] = None,
    notes: Optional[str] = None,
) -> Optional[object]:
    """Update mutable fields on an active position.

    Returns the updated row, or None if not found/inactive or session is None.
    """
    if session is None:
        return None

    row = await position_get(session, portfolio_id, ticker)
    if row is None or not row.active:
        return None

    if membership_class is not None:
        row.membership_class = membership_class
    if weight is not None:
        row.weight = weight
    if cost_basis is not None:
        row.cost_basis = cost_basis
    if shares is not None:
        row.shares = shares
    if notes is not None:
        row.notes = notes
    row.updated_at = _now()
    await session.flush()
    return row


async def position_remove(
    session,
    portfolio_id: str,
    ticker: str,
) -> bool:
    """Soft-delete a position (set active=False).

    Returns True if found and deactivated, False otherwise.
    """
    if session is None:
        return False

    row = await position_get(session, portfolio_id, ticker)
    if row is None or not row.active:
        return False

    row.active = False
    row.updated_at = _now()
    await session.flush()
    return True


async def position_list(
    session,
    portfolio_id: str,
    include_inactive: bool = False,
) -> List:
    """Return positions in a portfolio, ordered by added_at ascending.

    By default returns only active positions.  Pass include_inactive=True
    to return all rows (active and soft-deleted).
    """
    if session is None:
        return []

    from app.db.models import PortfolioPosition
    from sqlalchemy import select

    stmt = select(PortfolioPosition).where(
        PortfolioPosition.portfolio_id == portfolio_id
    )
    if not include_inactive:
        stmt = stmt.where(PortfolioPosition.active.is_(True))
    stmt = stmt.order_by(PortfolioPosition.added_at)

    result = await session.execute(stmt)
    return list(result.scalars().all())


async def position_list_by_ticker(
    session,
    ticker: str,
    active_only: bool = True,
) -> List:
    """Return all positions across all portfolios for a given ticker.

    Used by the Slice 5 loop-tick re-evaluation: when a dossier update fires
    for ticker T, find all portfolios containing T and re-evaluate insights.
    """
    if session is None:
        return []

    from app.db.models import PortfolioPosition
    from sqlalchemy import select

    t = ticker.strip().upper()
    stmt = select(PortfolioPosition).where(PortfolioPosition.ticker == t)
    if active_only:
        stmt = stmt.where(PortfolioPosition.active.is_(True))
    stmt = stmt.order_by(PortfolioPosition.added_at)

    result = await session.execute(stmt)
    return list(result.scalars().all())


# ---------------------------------------------------------------------------
# § INSIGHTS  (schema only in Slice 1 — generation wired in Slice 5)
# ---------------------------------------------------------------------------

async def insight_upsert(
    session,
    portfolio_id: str,
    insight_type: str,
    cluster_label: str,
    content_key: str,
    severity: str = "info",
    severity_rank: int = 0,
    member_tickers: str = "[]",
    cluster_weight: Optional[float] = None,
    rank_score: float = 0.0,
    body_json: str = "{}",
    cross_exposure_as_of: Optional[datetime] = None,
    stale_input: bool = False,
):
    """Insert or update a portfolio insight keyed on content_key.

    - If a row with the same content_key exists: updates mutable fields.
    - Otherwise: inserts a new row.

    Returns the PortfolioInsight row, or None when session is None.
    This is a write helper for Slice 5 (generation) and later; schema-only
    in Slice 1.
    """
    if session is None:
        return None

    from app.db.models import PortfolioInsight
    from sqlalchemy import select

    result = await session.execute(
        select(PortfolioInsight).where(PortfolioInsight.content_key == content_key)
    )
    row = result.scalar_one_or_none()

    if row is not None:
        row.severity        = severity
        row.severity_rank   = severity_rank
        row.cluster_weight  = cluster_weight
        row.rank_score      = rank_score
        row.body_json       = body_json
        row.stale_input     = stale_input
        row.cross_exposure_as_of = cross_exposure_as_of
        row.updated_at      = _now()
        await session.flush()
        return row

    row = PortfolioInsight(
        portfolio_id=portfolio_id,
        insight_type=insight_type,
        cluster_label=cluster_label,
        content_key=content_key,
        severity=severity,
        severity_rank=severity_rank,
        member_tickers=member_tickers,
        cluster_weight=cluster_weight,
        rank_score=rank_score,
        body_json=body_json,
        cross_exposure_as_of=cross_exposure_as_of,
        stale_input=stale_input,
    )
    session.add(row)
    await session.flush()
    return row


async def insight_list(
    session,
    portfolio_id: str,
    limit: int = 50,
) -> List:
    """Return insights for a portfolio ordered by rank_score desc, created_at desc."""
    if session is None:
        return []

    from app.db.models import PortfolioInsight
    from sqlalchemy import select

    result = await session.execute(
        select(PortfolioInsight)
        .where(PortfolioInsight.portfolio_id == portfolio_id)
        .order_by(PortfolioInsight.rank_score.desc(), PortfolioInsight.created_at.desc())
        .limit(limit)
    )
    return list(result.scalars().all())
