"""
Portfolio mirror service — Phase 10D · Slice 2.

Responsibilities
----------------
  ensure_default_portfolio(session, user_id=None)
    Create the is_default=True portfolio for the given user if it does not
    already exist.  Idempotent — calling it twice returns the same row.

  sync_watchlist_to_portfolio(session, user_id=None)
    Mirror the active ``watched_tickers`` rows into the default portfolio's
    positions, then soft-delete any positions whose ticker has left the
    watchlist.

    Mapping rules (spec §1.1 / §1.2):
      * active WatchedTicker → active PortfolioPosition (membership_class="watchlist")
      * inactive / missing WatchedTicker → position soft-deleted (active=False)
      * weight / cost_basis / shares left NULL — the mirror never guesses financials
      * Only ``watchlist``-class positions are managed by the mirror.
        ``owned`` / ``on_radar`` positions set by the user are NEVER touched.

Idempotency guarantee
---------------------
  * Repeated calls produce no duplicate portfolios and no duplicate positions.
  * Re-adding a ticker to the watchlist reactivates its portfolio position.
  * Removing a ticker from the watchlist soft-deletes the mirrored position.
  * ``owned`` / ``on_radar`` positions for the same ticker coexist safely —
    the mirror only manages rows where membership_class == "watchlist".

Integration note
----------------
  These functions are pure async callables with a session argument.  They
  are NOT wired to any scheduler or startup path in Slice 2; that hookup
  arrives in the plan-approved startup block (Slice 2 of the plan says
  "Add safe callable function only.  Do not auto-run unless approved.").
  The caller (startup, a job, a test) passes a live AsyncSession.
"""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Name used for the auto-created default portfolio (mirrors the spec §1.2 label).
DEFAULT_PORTFOLIO_NAME = "Default Watchlist Portfolio"


async def ensure_default_portfolio(session, user_id: Optional[str] = None):
    """Return (or create) the is_default=True portfolio for user_id.

    Idempotent: if a default portfolio already exists for this user it is
    returned unchanged.  If none exists a new one is created.

    Returns the Portfolio row, or None when session is None.
    """
    if session is None:
        return None

    from app.db.repositories.portfolio_repo import (
        portfolio_get_default,
        portfolio_create,
        portfolio_list,
    )

    existing = await portfolio_get_default(session, user_id=user_id)
    if existing is not None:
        return existing

    # Phase 17 · Slice 6 — portfolio limit check (no-op when ENTITLEMENTS_ENFORCED=false)
    try:
        from app.services.entitlement_enforcement import (
            check_portfolio_limit,
            EntitlementViolation,
        )
        from app.services.entitlement_service import resolve_entitlements

        _ent = await resolve_entitlements(session, user_id or "")
        _existing_portfolios = await portfolio_list(session, user_id=user_id)
        check_portfolio_limit(_ent, len(_existing_portfolios))
    except EntitlementViolation:
        logger.info(
            "[portfolio_mirror] portfolio_limit reached for user_id=%s — not creating default",
            user_id,
        )
        return None
    except Exception:
        pass  # enforcement is failure-open

    portfolio = await portfolio_create(
        session,
        name=DEFAULT_PORTFOLIO_NAME,
        user_id=user_id,
        is_default=True,
    )
    logger.info(
        "[portfolio_mirror] created default portfolio id=%s user_id=%s",
        portfolio.id,
        user_id,
    )
    return portfolio


async def sync_watchlist_to_portfolio(
    session,
    user_id: Optional[str] = None,
) -> dict:
    """Mirror active watched_tickers into the default portfolio's positions.

    Steps
    -----
    1. Ensure the default portfolio exists (calls ensure_default_portfolio).
    2. Read all active WatchedTicker rows for user_id from the DB.
    3. For each active ticker:
         - If a ``watchlist``-class position exists and is active → no-op.
         - If a ``watchlist``-class position exists and is inactive → reactivate.
         - If no position exists → add with membership_class="watchlist".
         - If an ``owned`` / ``on_radar`` position exists for the same ticker
           → leave it completely untouched; still add a watchlist-class row
           (UNIQUE(portfolio_id, ticker) means we skip if any row exists —
           see note below).
    4. For each ``watchlist``-class position whose ticker is NOT in the active
       watchlist → soft-delete (set active=False).
    5. Return a summary dict with counts.

    UNIQUE constraint note
    ----------------------
    ``portfolio_positions`` has UNIQUE(portfolio_id, ticker).  This means a
    portfolio can hold exactly one position row per ticker, regardless of
    membership_class.  The mirror therefore:
      * Skips adding a watchlist-class row when the ticker already has an
        ``owned`` or ``on_radar`` row (the user-authored row takes precedence).
      * Never overwrites the existing row's membership_class or financial fields.
    This is the "owned position not overwritten" guarantee in the spec.

    Returns a dict:
      {
        "portfolio_id": str,
        "active_tickers": int,       # tickers in watchlist
        "added": int,                # new positions inserted
        "reactivated": int,          # inactive watchlist positions reactivated
        "skipped_existing": int,     # already-active positions, no change
        "skipped_owned": int,        # non-watchlist positions left untouched
        "deactivated": int,          # watchlist positions soft-deleted
      }

    Returns None when session is None.
    """
    if session is None:
        return None

    from app.db.models import WatchedTicker, PortfolioPosition
    from app.db.repositories.portfolio_repo import (
        portfolio_get_default,
        position_add,
        position_list,
    )
    from sqlalchemy import select

    # Step 1 — ensure default portfolio.
    portfolio = await ensure_default_portfolio(session, user_id=user_id)

    # Step 2 — read active watchlist tickers from DB.
    wt_stmt = (
        select(WatchedTicker)
        .where(WatchedTicker.active.is_(True))
        .where(
            WatchedTicker.user_id == user_id
            if user_id is not None
            else WatchedTicker.user_id.is_(None)
        )
    )
    wt_result = await session.execute(wt_stmt)
    active_tickers: set[str] = {
        row.ticker for row in wt_result.scalars().all()
    }

    # Step 3 — mirror each active ticker into the portfolio.
    added = reactivated = skipped_existing = skipped_owned = 0

    for ticker in active_tickers:
        # Check for any existing position row (active or inactive).
        pos_stmt = (
            select(PortfolioPosition)
            .where(PortfolioPosition.portfolio_id == portfolio.id)
            .where(PortfolioPosition.ticker == ticker)
        )
        pos_result = await session.execute(pos_stmt)
        existing_pos = pos_result.scalar_one_or_none()

        if existing_pos is None:
            # No position at all — insert a watchlist-class row.
            await position_add(
                session,
                portfolio_id=portfolio.id,
                ticker=ticker,
                membership_class="watchlist",
            )
            added += 1

        elif existing_pos.membership_class != "watchlist":
            # owned / on_radar row — leave completely untouched.
            skipped_owned += 1

        elif existing_pos.active:
            # Already-active watchlist position — nothing to do.
            skipped_existing += 1

        else:
            # Inactive watchlist position — reactivate it.
            existing_pos.active = True
            from datetime import datetime, timezone
            existing_pos.updated_at = datetime.now(timezone.utc)
            await session.flush()
            reactivated += 1

    # Step 4 — soft-delete watchlist positions for tickers no longer active.
    all_positions = await position_list(
        session, portfolio.id, include_inactive=False
    )
    deactivated = 0
    from datetime import datetime, timezone

    for pos in all_positions:
        if pos.membership_class == "watchlist" and pos.ticker not in active_tickers:
            pos.active = False
            pos.updated_at = datetime.now(timezone.utc)
            await session.flush()
            deactivated += 1

    summary = {
        "portfolio_id": portfolio.id,
        "active_tickers": len(active_tickers),
        "added": added,
        "reactivated": reactivated,
        "skipped_existing": skipped_existing,
        "skipped_owned": skipped_owned,
        "deactivated": deactivated,
    }
    logger.info("[portfolio_mirror] sync complete: %s", summary)
    return summary
