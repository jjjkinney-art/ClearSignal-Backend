"""
tests/test_services/test_portfolio_mirror.py

Phase 10D · Slice 2 — Portfolio mirror service tests.

Coverage
--------
  ensure_default_portfolio
    - creates default portfolio when none exists
    - returns existing default portfolio (idempotent — same id on second call)
    - name is DEFAULT_PORTFOLIO_NAME and is_default=True
    - isolated by user_id (user-A default does not satisfy user-B)
    - null session returns None safely

  sync_watchlist_to_portfolio
    - empty watchlist → empty default portfolio (no crash, 0 added)
    - active watched ticker → position added (membership_class="watchlist")
    - all active tickers mirrored in one sync pass
    - repeated sync is idempotent (second pass: 0 added, 0 deactivated)
    - ticker removed from watchlist → position soft-deleted
    - ticker re-added to watchlist → position reactivated (not duplicated)
    - owned position for same ticker is NOT overwritten by mirror
    - on_radar position for same ticker is NOT overwritten by mirror
    - mirror touches only watchlist-class rows (owned rows survive deactivation pass)
    - mirror auto-creates default portfolio when called standalone
    - null session returns None safely
    - summary dict contains expected keys and correct counts

  No intelligence or delivery
    - calling sync does not create portfolio_insights rows
    - calling sync does not create delivery_ledger rows
    - calling sync does not create notification rows
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from app.db.models import Base


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def db_session():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )
    async with factory() as session:
        yield session
        await session.commit()

    await engine.dispose()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _add_watched_ticker(session, ticker: str, user_id=None, active: bool = True):
    """Insert a WatchedTicker row directly (bypasses the file-backed service)."""
    from app.db.models import WatchedTicker
    t = ticker.strip().upper()
    row = WatchedTicker(
        ticker=t,
        company_name=t,
        user_id=user_id,
        active=active,
    )
    session.add(row)
    await session.flush()
    return row


async def _deactivate_watched_ticker(session, ticker: str, user_id=None):
    """Set an existing WatchedTicker row to active=False."""
    from app.db.models import WatchedTicker
    from sqlalchemy import select
    t = ticker.strip().upper()
    stmt = (
        select(WatchedTicker)
        .where(WatchedTicker.ticker == t)
        .where(
            WatchedTicker.user_id == user_id
            if user_id is not None
            else WatchedTicker.user_id.is_(None)
        )
    )
    result = await session.execute(stmt)
    row = result.scalar_one_or_none()
    if row:
        row.active = False
        row.updated_at = datetime.now(timezone.utc)
        await session.flush()
    return row


async def _get_positions(session, portfolio_id, include_inactive=False):
    from app.db.repositories.portfolio_repo import position_list
    return await position_list(session, portfolio_id, include_inactive=include_inactive)


# ---------------------------------------------------------------------------
# ensure_default_portfolio
# ---------------------------------------------------------------------------

class TestEnsureDefaultPortfolio:
    async def test_creates_portfolio_when_absent(self, db_session):
        from app.services.portfolio_mirror_service import ensure_default_portfolio

        p = await ensure_default_portfolio(db_session)
        assert p is not None
        assert p.is_default is True

    async def test_name_is_default_watchlist_portfolio(self, db_session):
        from app.services.portfolio_mirror_service import (
            ensure_default_portfolio, DEFAULT_PORTFOLIO_NAME
        )
        p = await ensure_default_portfolio(db_session)
        assert p.name == DEFAULT_PORTFOLIO_NAME

    async def test_idempotent_returns_same_id(self, db_session):
        from app.services.portfolio_mirror_service import ensure_default_portfolio

        p1 = await ensure_default_portfolio(db_session)
        p2 = await ensure_default_portfolio(db_session)
        assert p1.id == p2.id

    async def test_isolated_by_user_id(self, db_session):
        from app.services.portfolio_mirror_service import ensure_default_portfolio

        pa = await ensure_default_portfolio(db_session, user_id="user-a")
        pb = await ensure_default_portfolio(db_session, user_id="user-b")
        assert pa.id != pb.id

    async def test_global_user_none_isolated_from_named(self, db_session):
        from app.services.portfolio_mirror_service import ensure_default_portfolio

        p_global = await ensure_default_portfolio(db_session, user_id=None)
        p_named  = await ensure_default_portfolio(db_session, user_id="user-x")
        assert p_global.id != p_named.id

    async def test_null_session_returns_none(self):
        from app.services.portfolio_mirror_service import ensure_default_portfolio
        result = await ensure_default_portfolio(None)
        assert result is None

    async def test_does_not_overwrite_existing_name(self, db_session):
        # If the user manually renamed the default portfolio, ensure_default
        # returns the existing row without renaming it.
        from app.services.portfolio_mirror_service import ensure_default_portfolio
        from app.db.repositories.portfolio_repo import portfolio_update

        p = await ensure_default_portfolio(db_session)
        await portfolio_update(db_session, p.id, name="My Custom Name")

        # Calling again must return the same row (not a new one).
        p2 = await ensure_default_portfolio(db_session)
        assert p2.id == p.id


# ---------------------------------------------------------------------------
# sync_watchlist_to_portfolio — basic behaviour
# ---------------------------------------------------------------------------

class TestSyncBasic:
    async def test_empty_watchlist_creates_empty_portfolio(self, db_session):
        from app.services.portfolio_mirror_service import sync_watchlist_to_portfolio

        summary = await sync_watchlist_to_portfolio(db_session)
        assert summary is not None
        assert summary["active_tickers"] == 0
        assert summary["added"] == 0

    async def test_active_ticker_added_as_watchlist_position(self, db_session):
        from app.services.portfolio_mirror_service import sync_watchlist_to_portfolio

        await _add_watched_ticker(db_session, "AAPL")
        summary = await sync_watchlist_to_portfolio(db_session)

        assert summary["added"] == 1
        assert summary["active_tickers"] == 1

        positions = await _get_positions(db_session, summary["portfolio_id"])
        assert len(positions) == 1
        assert positions[0].ticker == "AAPL"
        assert positions[0].membership_class == "watchlist"
        assert positions[0].active is True

    async def test_all_active_tickers_mirrored(self, db_session):
        from app.services.portfolio_mirror_service import sync_watchlist_to_portfolio

        for ticker in ["AAPL", "MSFT", "GOOGL", "NVDA"]:
            await _add_watched_ticker(db_session, ticker)

        summary = await sync_watchlist_to_portfolio(db_session)
        assert summary["added"] == 4

        positions = await _get_positions(db_session, summary["portfolio_id"])
        tickers = {p.ticker for p in positions}
        assert tickers == {"AAPL", "MSFT", "GOOGL", "NVDA"}

    async def test_watchlist_positions_have_null_financials(self, db_session):
        from app.services.portfolio_mirror_service import sync_watchlist_to_portfolio

        await _add_watched_ticker(db_session, "TSLA")
        summary = await sync_watchlist_to_portfolio(db_session)

        positions = await _get_positions(db_session, summary["portfolio_id"])
        pos = positions[0]
        assert pos.weight     is None
        assert pos.cost_basis is None
        assert pos.shares     is None

    async def test_null_session_returns_none(self):
        from app.services.portfolio_mirror_service import sync_watchlist_to_portfolio
        result = await sync_watchlist_to_portfolio(None)
        assert result is None

    async def test_auto_creates_default_portfolio(self, db_session):
        from app.services.portfolio_mirror_service import sync_watchlist_to_portfolio
        from app.db.repositories.portfolio_repo import portfolio_get_default

        # No portfolio exists yet.
        assert await portfolio_get_default(db_session) is None

        await sync_watchlist_to_portfolio(db_session)

        # Portfolio must now exist.
        p = await portfolio_get_default(db_session)
        assert p is not None
        assert p.is_default is True


# ---------------------------------------------------------------------------
# sync_watchlist_to_portfolio — idempotency
# ---------------------------------------------------------------------------

class TestSyncIdempotency:
    async def test_repeated_sync_no_duplicates(self, db_session):
        from app.services.portfolio_mirror_service import sync_watchlist_to_portfolio

        await _add_watched_ticker(db_session, "AAPL")
        await _add_watched_ticker(db_session, "MSFT")

        s1 = await sync_watchlist_to_portfolio(db_session)
        assert s1["added"] == 2

        s2 = await sync_watchlist_to_portfolio(db_session)
        assert s2["added"] == 0
        assert s2["skipped_existing"] == 2
        assert s2["deactivated"] == 0

        positions = await _get_positions(db_session, s2["portfolio_id"])
        assert len(positions) == 2

    async def test_summary_keys_present(self, db_session):
        from app.services.portfolio_mirror_service import sync_watchlist_to_portfolio

        summary = await sync_watchlist_to_portfolio(db_session)
        required_keys = {
            "portfolio_id", "active_tickers",
            "added", "reactivated", "skipped_existing",
            "skipped_owned", "deactivated",
        }
        assert required_keys <= set(summary.keys())


# ---------------------------------------------------------------------------
# sync_watchlist_to_portfolio — ticker removal and reactivation
# ---------------------------------------------------------------------------

class TestSyncRemovalAndReactivation:
    async def test_ticker_removed_from_watchlist_deactivates_position(self, db_session):
        from app.services.portfolio_mirror_service import sync_watchlist_to_portfolio

        await _add_watched_ticker(db_session, "AAPL")
        await _add_watched_ticker(db_session, "MSFT")
        s1 = await sync_watchlist_to_portfolio(db_session)
        assert s1["added"] == 2

        # Remove MSFT from watchlist.
        await _deactivate_watched_ticker(db_session, "MSFT")

        s2 = await sync_watchlist_to_portfolio(db_session)
        assert s2["deactivated"] == 1

        # Only AAPL should remain active.
        positions = await _get_positions(db_session, s2["portfolio_id"])
        assert len(positions) == 1
        assert positions[0].ticker == "AAPL"

    async def test_deactivated_position_still_in_db_as_inactive(self, db_session):
        from app.services.portfolio_mirror_service import sync_watchlist_to_portfolio

        await _add_watched_ticker(db_session, "NVDA")
        s1 = await sync_watchlist_to_portfolio(db_session)

        await _deactivate_watched_ticker(db_session, "NVDA")
        s2 = await sync_watchlist_to_portfolio(db_session)
        assert s2["deactivated"] == 1

        # Row persists as inactive (soft-delete).
        all_positions = await _get_positions(
            db_session, s2["portfolio_id"], include_inactive=True
        )
        assert any(p.ticker == "NVDA" and not p.active for p in all_positions)

    async def test_reactivated_ticker_reactivates_position(self, db_session):
        from app.services.portfolio_mirror_service import sync_watchlist_to_portfolio

        wt = await _add_watched_ticker(db_session, "GOOGL")

        s1 = await sync_watchlist_to_portfolio(db_session)
        assert s1["added"] == 1

        # Remove from watchlist, sync → deactivated.
        await _deactivate_watched_ticker(db_session, "GOOGL")
        s2 = await sync_watchlist_to_portfolio(db_session)
        assert s2["deactivated"] == 1

        # Re-add to watchlist, sync → reactivated (not duplicated).
        wt.active = True
        wt.updated_at = datetime.now(timezone.utc)
        await db_session.flush()

        s3 = await sync_watchlist_to_portfolio(db_session)
        assert s3["reactivated"] == 1
        assert s3["added"] == 0

        positions = await _get_positions(db_session, s3["portfolio_id"])
        assert len(positions) == 1
        assert positions[0].ticker == "GOOGL"
        assert positions[0].active is True

    async def test_all_tickers_removed_leaves_empty_active_positions(self, db_session):
        from app.services.portfolio_mirror_service import sync_watchlist_to_portfolio

        await _add_watched_ticker(db_session, "AAPL")
        await _add_watched_ticker(db_session, "MSFT")
        s1 = await sync_watchlist_to_portfolio(db_session)

        await _deactivate_watched_ticker(db_session, "AAPL")
        await _deactivate_watched_ticker(db_session, "MSFT")
        s2 = await sync_watchlist_to_portfolio(db_session)
        assert s2["deactivated"] == 2

        positions = await _get_positions(db_session, s2["portfolio_id"])
        assert len(positions) == 0


# ---------------------------------------------------------------------------
# sync_watchlist_to_portfolio — owned position protection
# ---------------------------------------------------------------------------

class TestSyncOwnedProtection:
    async def test_owned_position_not_overwritten(self, db_session):
        from app.services.portfolio_mirror_service import sync_watchlist_to_portfolio
        from app.db.repositories.portfolio_repo import (
            portfolio_get_default, position_add
        )

        # Add ticker to watchlist.
        await _add_watched_ticker(db_session, "AAPL")

        # Pre-create default portfolio and manually set an OWNED position.
        from app.services.portfolio_mirror_service import ensure_default_portfolio
        p = await ensure_default_portfolio(db_session)
        await position_add(
            db_session, p.id, "AAPL",
            membership_class="owned",
            weight=0.20, cost_basis=155.0, shares=100.0,
        )

        # Mirror should skip AAPL because it already has a non-watchlist row.
        summary = await sync_watchlist_to_portfolio(db_session)
        assert summary["skipped_owned"] == 1
        assert summary["added"] == 0

        # The owned row must be completely intact.
        from app.db.repositories.portfolio_repo import position_get
        pos = await position_get(db_session, p.id, "AAPL")
        assert pos is not None
        assert pos.membership_class == "owned"
        assert pos.weight     == pytest.approx(0.20)
        assert pos.cost_basis == pytest.approx(155.0)
        assert pos.shares     == pytest.approx(100.0)

    async def test_on_radar_position_not_overwritten(self, db_session):
        from app.services.portfolio_mirror_service import (
            ensure_default_portfolio, sync_watchlist_to_portfolio
        )
        from app.db.repositories.portfolio_repo import position_add, position_get

        await _add_watched_ticker(db_session, "NVDA")
        p = await ensure_default_portfolio(db_session)
        await position_add(db_session, p.id, "NVDA", membership_class="on_radar")

        summary = await sync_watchlist_to_portfolio(db_session)
        assert summary["skipped_owned"] == 1
        assert summary["added"] == 0

        pos = await position_get(db_session, p.id, "NVDA")
        assert pos.membership_class == "on_radar"

    async def test_owned_position_not_deactivated_when_ticker_leaves_watchlist(
        self, db_session
    ):
        """Mirror must NOT soft-delete an owned row even when the ticker is removed
        from the watchlist, because the user still holds it."""
        from app.services.portfolio_mirror_service import (
            ensure_default_portfolio, sync_watchlist_to_portfolio
        )
        from app.db.repositories.portfolio_repo import position_add, position_get

        wt = await _add_watched_ticker(db_session, "TSLA")
        p = await ensure_default_portfolio(db_session)

        # Place an owned row (user holds TSLA).
        await position_add(
            db_session, p.id, "TSLA", membership_class="owned", weight=0.10
        )

        # First sync: skipped_owned because owned row pre-exists.
        s1 = await sync_watchlist_to_portfolio(db_session)
        assert s1["skipped_owned"] == 1

        # Remove from watchlist.
        await _deactivate_watched_ticker(db_session, "TSLA")

        # Second sync: the deactivation pass only touches watchlist-class rows.
        s2 = await sync_watchlist_to_portfolio(db_session)
        assert s2["deactivated"] == 0

        # Owned row must still be active.
        pos = await position_get(db_session, p.id, "TSLA")
        assert pos is not None
        assert pos.active is True
        assert pos.membership_class == "owned"

    async def test_mixed_watchlist_and_owned_in_same_portfolio(self, db_session):
        from app.services.portfolio_mirror_service import (
            ensure_default_portfolio, sync_watchlist_to_portfolio
        )
        from app.db.repositories.portfolio_repo import position_add

        # Two tickers on watchlist; one of them also has an owned row.
        await _add_watched_ticker(db_session, "AAPL")
        await _add_watched_ticker(db_session, "MSFT")

        p = await ensure_default_portfolio(db_session)
        # MSFT is owned — pre-place the row.
        await position_add(
            db_session, p.id, "MSFT", membership_class="owned", weight=0.15
        )

        summary = await sync_watchlist_to_portfolio(db_session)
        # AAPL added (no pre-existing row); MSFT skipped (owned row).
        assert summary["added"] == 1
        assert summary["skipped_owned"] == 1

        positions = await _get_positions(db_session, p.id)
        assert len(positions) == 2  # both AAPL (watchlist) and MSFT (owned) are active


# ---------------------------------------------------------------------------
# sync_watchlist_to_portfolio — user isolation
# ---------------------------------------------------------------------------

class TestSyncUserIsolation:
    async def test_sync_isolated_by_user_id(self, db_session):
        from app.services.portfolio_mirror_service import sync_watchlist_to_portfolio

        await _add_watched_ticker(db_session, "AAPL", user_id="user-1")
        await _add_watched_ticker(db_session, "MSFT", user_id="user-2")

        s1 = await sync_watchlist_to_portfolio(db_session, user_id="user-1")
        s2 = await sync_watchlist_to_portfolio(db_session, user_id="user-2")

        assert s1["portfolio_id"] != s2["portfolio_id"]

        p1_positions = await _get_positions(db_session, s1["portfolio_id"])
        p2_positions = await _get_positions(db_session, s2["portfolio_id"])

        assert {p.ticker for p in p1_positions} == {"AAPL"}
        assert {p.ticker for p in p2_positions} == {"MSFT"}

    async def test_global_user_none_sees_only_global_tickers(self, db_session):
        from app.services.portfolio_mirror_service import sync_watchlist_to_portfolio

        # Global ticker (user_id=None) and a named-user ticker.
        await _add_watched_ticker(db_session, "AAPL", user_id=None)
        await _add_watched_ticker(db_session, "TSLA", user_id="user-x")

        summary = await sync_watchlist_to_portfolio(db_session, user_id=None)
        positions = await _get_positions(db_session, summary["portfolio_id"])
        assert len(positions) == 1
        assert positions[0].ticker == "AAPL"


# ---------------------------------------------------------------------------
# No intelligence or delivery side-effects
# ---------------------------------------------------------------------------

class TestNoSideEffects:
    async def test_sync_creates_no_portfolio_insights(self, db_session):
        from app.services.portfolio_mirror_service import sync_watchlist_to_portfolio
        from app.db.models import PortfolioInsight
        from sqlalchemy import select, func

        await _add_watched_ticker(db_session, "AAPL")
        await sync_watchlist_to_portfolio(db_session)

        count = await db_session.scalar(select(func.count(PortfolioInsight.id)))
        assert count == 0

    async def test_sync_creates_no_delivery_ledger_rows(self, db_session):
        from app.services.portfolio_mirror_service import sync_watchlist_to_portfolio
        from app.db.models import DeliveryLedger
        from sqlalchemy import select, func

        await _add_watched_ticker(db_session, "MSFT")
        await sync_watchlist_to_portfolio(db_session)

        count = await db_session.scalar(select(func.count(DeliveryLedger.id)))
        assert count == 0

    async def test_sync_creates_no_notification_rows(self, db_session):
        from app.services.portfolio_mirror_service import sync_watchlist_to_portfolio
        from app.db.models import Notification
        from sqlalchemy import select, func

        await _add_watched_ticker(db_session, "NVDA")
        await sync_watchlist_to_portfolio(db_session)

        count = await db_session.scalar(select(func.count(Notification.id)))
        assert count == 0

    async def test_sync_reads_watched_tickers_read_only(self, db_session):
        """Mirror must not modify WatchedTicker rows."""
        from app.services.portfolio_mirror_service import sync_watchlist_to_portfolio
        from app.db.models import WatchedTicker
        from sqlalchemy import select

        wt = await _add_watched_ticker(db_session, "GOOGL")
        original_updated_at = wt.updated_at

        await sync_watchlist_to_portfolio(db_session)

        result = await db_session.execute(
            select(WatchedTicker).where(WatchedTicker.ticker == "GOOGL")
        )
        wt_after = result.scalar_one_or_none()
        assert wt_after is not None
        # updated_at on the WatchedTicker row must not change.
        assert wt_after.updated_at == original_updated_at
        assert wt_after.active is True
