"""
One-time import / claim service — Phase 16 · Slice 6.

Allows a newly authenticated user to adopt existing system-owned starter data
(watchlist, portfolios, positions, delivery preferences) into their own account.

Design invariants
-----------------
* Non-destructive: source system-owned rows are NEVER modified or deleted.
* Copy semantics: each imported resource receives a new UUID under the user's
  ownership; the original row is preserved intact.
* Idempotent: calling execute_import twice is safe — the second call is a no-op.
* Sentinel: presence of an 'import' audit_log entry (action='import',
  resource='import_run') is the authoritative "already imported" signal.
* Rollback: rollback_import reads the audit trail to find imported row IDs and
  deletes only those rows.  System-owned rows are never touched.
* Null-session safety: all public functions return safe defaults when session=None.
* No credentials: this module never reads, writes, or validates any credential.

Import sources
--------------
  watched_tickers      — active, system-owned (user_id = SYSTEM_DEFAULT_USER_ID)
  portfolios           — system-owned
  portfolio_positions  — via system-owned portfolios
  user_delivery_prefs  — system-owned, only when user has no prefs yet
"""

from __future__ import annotations

import logging
import uuid as _uuid_mod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SYSTEM_DEFAULT_USER_ID: str = "00000000-0000-0000-0000-000000000001"

# Audit action values written by this module.
_ACTION_IMPORT   = "import"
_ACTION_ROLLBACK = "rollback"

# Audit resource tags used to identify imported rows in rollback.
_RES_IMPORT_RUN  = "import_run"
_RES_TICKER      = "watched_ticker"
_RES_PORTFOLIO   = "portfolio"
_RES_POSITION    = "portfolio_position"
_RES_PREF        = "delivery_pref"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _new_id() -> str:
    return str(_uuid_mod.uuid4())


# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------

@dataclass
class ImportPreview:
    """Read-only snapshot of what execute_import would do.  No writes."""
    user_id:             str
    already_imported:    bool
    watchlist_count:     int
    portfolio_count:     int
    position_count:      int
    delivery_pref_count: int
    estimated_actions:   Dict[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.estimated_actions:
            self.estimated_actions = {
                "watched_tickers":    self.watchlist_count,
                "portfolios":         self.portfolio_count,
                "portfolio_positions": self.position_count,
                "delivery_prefs":     self.delivery_pref_count,
            }


@dataclass
class ImportResult:
    """Outcome of execute_import."""
    user_id:              str
    already_imported:     bool
    watchlist_copied:     int
    portfolio_copied:     int
    position_copied:      int
    delivery_pref_copied: int
    skipped:              int
    audit_run_id:         Optional[str] = None


@dataclass
class RollbackResult:
    """Outcome of rollback_import."""
    user_id:               str
    watchlist_deleted:     int
    portfolio_deleted:     int
    position_deleted:      int
    delivery_pref_deleted: int

    @property
    def total_deleted(self) -> int:
        return (
            self.watchlist_deleted
            + self.portfolio_deleted
            + self.position_deleted
            + self.delivery_pref_deleted
        )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

async def _audit(session, *, user_id: str, resource: str, resource_id: Optional[str],
                 action: str, meta: Optional[str] = None) -> Optional[str]:
    """Append one audit_log row.  Returns the new row's id, or None on failure.

    Non-fatal per spec §6.6: exceptions are logged and swallowed so audit
    failures never block the underlying user action.
    """
    try:
        from app.db.models import AuditLog
        row = AuditLog(
            id=_new_id(),
            user_id=user_id,
            resource=resource,
            resource_id=resource_id,
            action=action,
        )
        session.add(row)
        await session.flush()
        return row.id
    except Exception as exc:
        logger.warning("[import] audit write failed (non-fatal): %r", exc)
        return None


async def _is_already_imported(session, user_id: str) -> bool:
    """Return True if an import_run audit entry already exists for this user."""
    from app.db.models import AuditLog
    from sqlalchemy import select

    result = await session.execute(
        select(AuditLog.id)
        .where(AuditLog.user_id == user_id)
        .where(AuditLog.resource == _RES_IMPORT_RUN)
        .where(AuditLog.action == _ACTION_IMPORT)
        .limit(1)
    )
    return result.scalar_one_or_none() is not None


async def _count_system_tickers(session) -> int:
    """Distinct active starter tickers an import can actually create.

    Counts DISTINCT ticker, not rows. execute_import skips any ticker the
    user already owns, so N duplicate system rows for one ticker still
    produce exactly one row for the importing user. Counting rows here
    overstated the preview by the duplicate factor — with duplicated system
    starter data that is a large, user-visible overstatement on the
    onboarding screen.

    Distinct-counted in the database; rows are never materialised.
    """
    from app.db.models import WatchedTicker
    from sqlalchemy import select, func

    result = await session.execute(
        select(func.count(func.distinct(WatchedTicker.ticker)))
        .where(WatchedTicker.user_id == SYSTEM_DEFAULT_USER_ID)
        .where(WatchedTicker.active.is_(True))
    )
    return result.scalar() or 0


async def _count_system_portfolios(session) -> int:
    from app.db.models import Portfolio
    from sqlalchemy import select, func

    result = await session.execute(
        select(func.count(Portfolio.id))
        .where(Portfolio.user_id == SYSTEM_DEFAULT_USER_ID)
    )
    return result.scalar_one() or 0


async def _count_system_positions(session) -> int:
    from app.db.models import Portfolio, PortfolioPosition
    from sqlalchemy import select, func

    sub = select(Portfolio.id).where(Portfolio.user_id == SYSTEM_DEFAULT_USER_ID)
    result = await session.execute(
        select(func.count(PortfolioPosition.id))
        .where(PortfolioPosition.portfolio_id.in_(sub))
        .where(PortfolioPosition.active.is_(True))
    )
    return result.scalar_one() or 0


async def _count_system_prefs(session, user_id: str) -> int:
    """Count system prefs that would be copied — 0 if user already has any prefs."""
    from app.db.models import UserDeliveryPref
    from sqlalchemy import select, func

    # If user already has any prefs, we won't import.
    user_pref_count_result = await session.execute(
        select(func.count(UserDeliveryPref.id))
        .where(UserDeliveryPref.user_id == user_id)
    )
    if (user_pref_count_result.scalar_one() or 0) > 0:
        return 0

    result = await session.execute(
        select(func.count(UserDeliveryPref.id))
        .where(UserDeliveryPref.user_id == SYSTEM_DEFAULT_USER_ID)
    )
    return result.scalar_one() or 0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def preview_import(session, user_id: str) -> ImportPreview:
    """Return a read-only preview of what execute_import would do.

    No rows are written.  Returns an empty preview with already_imported=True
    if the import has already run for this user.
    Returns a zero-count preview when session is None.
    """
    if session is None:
        return ImportPreview(
            user_id=user_id,
            already_imported=False,
            watchlist_count=0,
            portfolio_count=0,
            position_count=0,
            delivery_pref_count=0,
        )

    if user_id == SYSTEM_DEFAULT_USER_ID:
        raise ValueError("cannot import into the system user account")

    already = await _is_already_imported(session, user_id)
    if already:
        return ImportPreview(
            user_id=user_id,
            already_imported=True,
            watchlist_count=0,
            portfolio_count=0,
            position_count=0,
            delivery_pref_count=0,
        )

    wl  = await _count_system_tickers(session)
    po  = await _count_system_portfolios(session)
    pos = await _count_system_positions(session)
    dp  = await _count_system_prefs(session, user_id)

    return ImportPreview(
        user_id=user_id,
        already_imported=False,
        watchlist_count=wl,
        portfolio_count=po,
        position_count=pos,
        delivery_pref_count=dp,
    )


async def execute_import(session, user_id: str) -> ImportResult:
    """Copy system-owned starter data into user's account.

    Idempotent: a second call returns ImportResult(already_imported=True) with
    all counts 0.  The system-owned source rows are never modified.

    Returns an empty result when session is None.
    """
    if session is None:
        return ImportResult(
            user_id=user_id,
            already_imported=False,
            watchlist_copied=0,
            portfolio_copied=0,
            position_copied=0,
            delivery_pref_copied=0,
            skipped=0,
        )

    if user_id == SYSTEM_DEFAULT_USER_ID:
        raise ValueError("cannot import into the system user account")

    if await _is_already_imported(session, user_id):
        return ImportResult(
            user_id=user_id,
            already_imported=True,
            watchlist_copied=0,
            portfolio_copied=0,
            position_copied=0,
            delivery_pref_copied=0,
            skipped=0,
        )

    wl_copied  = 0
    po_copied  = 0
    pos_copied = 0
    dp_copied  = 0
    skipped    = 0

    # -- watched_tickers -------------------------------------------------------
    from app.db.models import (
        WatchedTicker, Portfolio, PortfolioPosition, UserDeliveryPref
    )
    from sqlalchemy import select

    sys_tickers = (await session.execute(
        select(WatchedTicker)
        .where(WatchedTicker.user_id == SYSTEM_DEFAULT_USER_ID)
        .where(WatchedTicker.active.is_(True))
    )).scalars().all()

    # Collect tickers the user already owns to skip duplicates.
    existing_tickers_result = await session.execute(
        select(WatchedTicker.ticker)
        .where(WatchedTicker.user_id == user_id)
    )
    user_tickers: set = {r for (r,) in existing_tickers_result.all()}

    for src in sys_tickers:
        if src.ticker in user_tickers:
            skipped += 1
            continue
        new_row = WatchedTicker(
            id=_new_id(),
            user_id=user_id,
            ticker=src.ticker,
            company_name=src.company_name,
            active=True,
            added_at=_now(),
            updated_at=_now(),
        )
        session.add(new_row)
        await session.flush()
        user_tickers.add(src.ticker)
        await _audit(session, user_id=user_id, resource=_RES_TICKER,
                     resource_id=new_row.id, action=_ACTION_IMPORT)
        wl_copied += 1

    # -- portfolios + positions ------------------------------------------------
    sys_portfolios = (await session.execute(
        select(Portfolio)
        .where(Portfolio.user_id == SYSTEM_DEFAULT_USER_ID)
    )).scalars().all()

    existing_names_result = await session.execute(
        select(Portfolio.name)
        .where(Portfolio.user_id == user_id)
    )
    user_portfolio_names: set = {r for (r,) in existing_names_result.all()}

    for src_po in sys_portfolios:
        if src_po.name in user_portfolio_names:
            skipped += 1
            # Count the positions that would have been copied as skipped.
            skipped_pos = (await session.execute(
                select(PortfolioPosition)
                .where(PortfolioPosition.portfolio_id == src_po.id)
                .where(PortfolioPosition.active.is_(True))
            )).scalars().all()
            skipped += len(skipped_pos)
            continue

        new_po = Portfolio(
            id=_new_id(),
            user_id=user_id,
            name=src_po.name,
            description=src_po.description,
            is_default=src_po.is_default,
            created_at=_now(),
            updated_at=_now(),
            org_id=None,
        )
        session.add(new_po)
        await session.flush()
        user_portfolio_names.add(src_po.name)
        await _audit(session, user_id=user_id, resource=_RES_PORTFOLIO,
                     resource_id=new_po.id, action=_ACTION_IMPORT)
        po_copied += 1

        # Copy positions into the new portfolio.
        src_positions = (await session.execute(
            select(PortfolioPosition)
            .where(PortfolioPosition.portfolio_id == src_po.id)
            .where(PortfolioPosition.active.is_(True))
        )).scalars().all()

        for src_pos in src_positions:
            new_pos = PortfolioPosition(
                id=_new_id(),
                portfolio_id=new_po.id,
                ticker=src_pos.ticker,
                membership_class=src_pos.membership_class,
                weight=src_pos.weight,
                cost_basis=src_pos.cost_basis,
                shares=src_pos.shares,
                notes=src_pos.notes,
                active=True,
                added_at=_now(),
                updated_at=_now(),
            )
            session.add(new_pos)
            await session.flush()
            await _audit(session, user_id=user_id, resource=_RES_POSITION,
                         resource_id=new_pos.id, action=_ACTION_IMPORT)
            pos_copied += 1

    # -- delivery_prefs --------------------------------------------------------
    # Only import if the user has no prefs yet (fail-safe: don't clobber custom prefs).
    user_pref_count = (await session.execute(
        select(UserDeliveryPref)
        .where(UserDeliveryPref.user_id == user_id)
        .limit(1)
    )).scalar_one_or_none()

    if user_pref_count is None:
        sys_prefs = (await session.execute(
            select(UserDeliveryPref)
            .where(UserDeliveryPref.user_id == SYSTEM_DEFAULT_USER_ID)
        )).scalars().all()

        for src_pref in sys_prefs:
            new_pref = UserDeliveryPref(
                id=_new_id(),
                user_id=user_id,
                channel=src_pref.channel,
                enabled=src_pref.enabled,
                min_severity=src_pref.min_severity,
                quiet_hours_start=src_pref.quiet_hours_start,
                quiet_hours_end=src_pref.quiet_hours_end,
                timezone=src_pref.timezone,
                daily_cap=src_pref.daily_cap,
                mute_until=src_pref.mute_until,
                created_at=_now(),
                updated_at=_now(),
            )
            session.add(new_pref)
            await session.flush()
            await _audit(session, user_id=user_id, resource=_RES_PREF,
                         resource_id=new_pref.id, action=_ACTION_IMPORT)
            dp_copied += 1

    # -- Sentinel audit entry --------------------------------------------------
    run_id = await _audit(
        session,
        user_id=user_id,
        resource=_RES_IMPORT_RUN,
        resource_id=None,
        action=_ACTION_IMPORT,
    )

    # -- Onboarding hook -------------------------------------------------------
    try:
        from app.services.onboarding_service import mark_import_completed as _mark
        await _mark(session, user_id)
    except Exception as _ob_exc:
        logger.warning("[import] onboarding step update failed (non-fatal): %r", _ob_exc)

    await session.commit()

    return ImportResult(
        user_id=user_id,
        already_imported=False,
        watchlist_copied=wl_copied,
        portfolio_copied=po_copied,
        position_copied=pos_copied,
        delivery_pref_copied=dp_copied,
        skipped=skipped,
        audit_run_id=run_id,
    )


async def rollback_import(session, user_id: str) -> RollbackResult:
    """Delete rows that were created by execute_import for this user.

    Reads the audit_log to identify imported row IDs by resource type, then
    deletes only those rows.  System-owned rows (user_id=SYSTEM_DEFAULT_USER_ID)
    are never touched.  Returns zero counts if no import audit trail exists.

    Returns an empty result when session is None.
    """
    if session is None:
        return RollbackResult(
            user_id=user_id,
            watchlist_deleted=0,
            portfolio_deleted=0,
            position_deleted=0,
            delivery_pref_deleted=0,
        )

    if user_id == SYSTEM_DEFAULT_USER_ID:
        raise ValueError("cannot rollback the system user account")

    from app.db.models import (
        AuditLog, WatchedTicker, Portfolio, PortfolioPosition, UserDeliveryPref
    )
    from sqlalchemy import select, delete

    # Collect all import audit entries for this user.
    audit_rows = (await session.execute(
        select(AuditLog)
        .where(AuditLog.user_id == user_id)
        .where(AuditLog.action == _ACTION_IMPORT)
        .where(AuditLog.resource != _RES_IMPORT_RUN)
    )).scalars().all()

    ticker_ids:   List[str] = []
    portfolio_ids: List[str] = []
    position_ids:  List[str] = []
    pref_ids:      List[str] = []

    for entry in audit_rows:
        if entry.resource_id is None:
            continue
        if entry.resource == _RES_TICKER:
            ticker_ids.append(entry.resource_id)
        elif entry.resource == _RES_PORTFOLIO:
            portfolio_ids.append(entry.resource_id)
        elif entry.resource == _RES_POSITION:
            position_ids.append(entry.resource_id)
        elif entry.resource == _RES_PREF:
            pref_ids.append(entry.resource_id)

    wl_del = po_del = pos_del = dp_del = 0

    if ticker_ids:
        result = await session.execute(
            delete(WatchedTicker)
            .where(WatchedTicker.id.in_(ticker_ids))
            .where(WatchedTicker.user_id == user_id)  # safety: never touch system rows
        )
        wl_del = result.rowcount or 0

    if position_ids:
        result = await session.execute(
            delete(PortfolioPosition)
            .where(PortfolioPosition.id.in_(position_ids))
        )
        pos_del = result.rowcount or 0

    if portfolio_ids:
        result = await session.execute(
            delete(Portfolio)
            .where(Portfolio.id.in_(portfolio_ids))
            .where(Portfolio.user_id == user_id)  # safety: never touch system rows
        )
        po_del = result.rowcount or 0

    if pref_ids:
        result = await session.execute(
            delete(UserDeliveryPref)
            .where(UserDeliveryPref.id.in_(pref_ids))
            .where(UserDeliveryPref.user_id == user_id)  # safety: never touch system rows
        )
        dp_del = result.rowcount or 0

    # Write a rollback sentinel so a subsequent execute_import can run again.
    # Remove the old import_run sentinel entry so the idempotency check passes.
    await session.execute(
        delete(AuditLog)
        .where(AuditLog.user_id == user_id)
        .where(AuditLog.action == _ACTION_IMPORT)
    )

    await _audit(
        session,
        user_id=user_id,
        resource=_RES_IMPORT_RUN,
        resource_id=None,
        action=_ACTION_ROLLBACK,
    )

    await session.commit()

    logger.info(
        "[import] rollback complete for user=%s: tickers=%d portfolios=%d "
        "positions=%d prefs=%d",
        user_id, wl_del, po_del, pos_del, dp_del,
    )

    return RollbackResult(
        user_id=user_id,
        watchlist_deleted=wl_del,
        portfolio_deleted=po_del,
        position_deleted=pos_del,
        delivery_pref_deleted=dp_del,
    )
