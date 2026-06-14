"""
Tests for app/services/account_import_service.py — Phase 16 · Slice 6.

Test matrix:
  1. TestNullSessionSafety       — all public functions return safe defaults when session=None
  2. TestSystemUserGuard         — ValueError when user_id == SYSTEM_DEFAULT_USER_ID
  3. TestPreviewImport           — preview_import counts without writes
  4. TestExecuteImportFirst      — first import copies all sources correctly
  5. TestExecuteImportIdempotent — second import is a no-op (already_imported=True)
  6. TestPartialExistingData     — user already has some rows; existing rows are skipped
  7. TestDuplicatePrevention     — duplicate tickers/portfolios/prefs within a single import
  8. TestAuditLogging            — audit rows written for each resource type
  9. TestRollback                — rollback deletes only imported rows, preserves system rows
 10. TestRollbackAfterRollback   — after rollback, re-import is possible (idempotency resets)
 11. TestDeliveryPrefImport      — prefs only imported when user has none
"""

from __future__ import annotations

import asyncio
import pytest
import pytest_asyncio
from typing import Any, Optional

SYSTEM_DEFAULT_USER_ID = "00000000-0000-0000-0000-000000000001"
USER_A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
USER_B = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"


# ---------------------------------------------------------------------------
# Shared SQLite fixture
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def session():
    """In-memory SQLite session seeded with system-owned starter data."""
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
    from sqlalchemy.orm import sessionmaker
    from app.db.models import Base, WatchedTicker, Portfolio, PortfolioPosition, UserDeliveryPref

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as s:
        # Seed system-owned watched tickers
        s.add(WatchedTicker(
            id="wt-sys-1", user_id=SYSTEM_DEFAULT_USER_ID,
            ticker="AAPL", company_name="Apple", active=True,
        ))
        s.add(WatchedTicker(
            id="wt-sys-2", user_id=SYSTEM_DEFAULT_USER_ID,
            ticker="MSFT", company_name="Microsoft", active=True,
        ))
        s.add(WatchedTicker(
            id="wt-sys-3", user_id=SYSTEM_DEFAULT_USER_ID,
            ticker="GOOG", company_name="Alphabet", active=False,  # inactive — not imported
        ))

        # Seed system-owned portfolio + positions
        s.add(Portfolio(
            id="po-sys-1", user_id=SYSTEM_DEFAULT_USER_ID,
            name="My Portfolio", is_default=True,
        ))
        s.add(PortfolioPosition(
            id="pos-sys-1", portfolio_id="po-sys-1",
            ticker="AAPL", membership_class="watchlist", active=True,
        ))
        s.add(PortfolioPosition(
            id="pos-sys-2", portfolio_id="po-sys-1",
            ticker="MSFT", membership_class="watchlist", active=True,
        ))
        s.add(PortfolioPosition(
            id="pos-sys-inactive", portfolio_id="po-sys-1",
            ticker="GOOG", membership_class="watchlist", active=False,  # not imported
        ))

        # Seed system-owned delivery pref
        s.add(UserDeliveryPref(
            id="pref-sys-1", user_id=SYSTEM_DEFAULT_USER_ID,
            channel="in_app", enabled=True, min_severity="info",
            quiet_hours_start=22, quiet_hours_end=7, timezone="UTC", daily_cap=20,
        ))

        await s.commit()
        yield s

    await engine.dispose()


# ---------------------------------------------------------------------------
# 1. TestNullSessionSafety
# ---------------------------------------------------------------------------

class TestNullSessionSafety:
    """All public functions return safe defaults when session is None."""

    def test_preview_returns_empty(self):
        from app.services.account_import_service import preview_import
        result = asyncio.get_event_loop().run_until_complete(
            preview_import(None, USER_A)
        )
        assert result.watchlist_count == 0
        assert result.portfolio_count == 0
        assert result.position_count == 0
        assert result.delivery_pref_count == 0
        assert result.already_imported is False

    def test_execute_returns_empty(self):
        from app.services.account_import_service import execute_import
        result = asyncio.get_event_loop().run_until_complete(
            execute_import(None, USER_A)
        )
        assert result.watchlist_copied == 0
        assert result.portfolio_copied == 0
        assert result.already_imported is False

    def test_rollback_returns_zeros(self):
        from app.services.account_import_service import rollback_import
        result = asyncio.get_event_loop().run_until_complete(
            rollback_import(None, USER_A)
        )
        assert result.total_deleted == 0


# ---------------------------------------------------------------------------
# 2. TestSystemUserGuard
# ---------------------------------------------------------------------------

class TestSystemUserGuard:
    """ValueError raised when targeting the system user."""

    @pytest.mark.asyncio
    async def test_preview_raises(self, session):
        from app.services.account_import_service import preview_import
        with pytest.raises(ValueError, match="system user"):
            await preview_import(session, SYSTEM_DEFAULT_USER_ID)

    @pytest.mark.asyncio
    async def test_execute_raises(self, session):
        from app.services.account_import_service import execute_import
        with pytest.raises(ValueError, match="system user"):
            await execute_import(session, SYSTEM_DEFAULT_USER_ID)

    @pytest.mark.asyncio
    async def test_rollback_raises(self, session):
        from app.services.account_import_service import rollback_import
        with pytest.raises(ValueError, match="system user"):
            await rollback_import(session, SYSTEM_DEFAULT_USER_ID)


# ---------------------------------------------------------------------------
# 3. TestPreviewImport
# ---------------------------------------------------------------------------

class TestPreviewImport:
    """preview_import returns accurate counts without writing anything."""

    @pytest.mark.asyncio
    async def test_preview_counts_active_tickers(self, session):
        from app.services.account_import_service import preview_import
        preview = await preview_import(session, USER_A)
        # 2 active tickers (AAPL, MSFT); GOOG is inactive
        assert preview.watchlist_count == 2

    @pytest.mark.asyncio
    async def test_preview_counts_portfolios(self, session):
        from app.services.account_import_service import preview_import
        preview = await preview_import(session, USER_A)
        assert preview.portfolio_count == 1

    @pytest.mark.asyncio
    async def test_preview_counts_active_positions(self, session):
        from app.services.account_import_service import preview_import
        preview = await preview_import(session, USER_A)
        # 2 active positions; 1 inactive
        assert preview.position_count == 2

    @pytest.mark.asyncio
    async def test_preview_counts_delivery_prefs(self, session):
        from app.services.account_import_service import preview_import
        preview = await preview_import(session, USER_A)
        assert preview.delivery_pref_count == 1

    @pytest.mark.asyncio
    async def test_preview_already_imported_false(self, session):
        from app.services.account_import_service import preview_import
        preview = await preview_import(session, USER_A)
        assert preview.already_imported is False

    @pytest.mark.asyncio
    async def test_preview_writes_nothing(self, session):
        """After preview, the user still owns zero rows."""
        from app.services.account_import_service import preview_import
        from app.db.models import WatchedTicker
        from sqlalchemy import select

        await preview_import(session, USER_A)

        rows = (await session.execute(
            select(WatchedTicker).where(WatchedTicker.user_id == USER_A)
        )).scalars().all()
        assert len(rows) == 0

    @pytest.mark.asyncio
    async def test_preview_estimated_actions_populated(self, session):
        from app.services.account_import_service import preview_import
        preview = await preview_import(session, USER_A)
        assert preview.estimated_actions["watched_tickers"] == 2
        assert preview.estimated_actions["portfolios"] == 1
        assert preview.estimated_actions["portfolio_positions"] == 2
        assert preview.estimated_actions["delivery_prefs"] == 1


# ---------------------------------------------------------------------------
# 4. TestExecuteImportFirst
# ---------------------------------------------------------------------------

class TestExecuteImportFirst:
    """First execute_import copies all system-owned sources correctly."""

    @pytest.mark.asyncio
    async def test_copies_active_tickers(self, session):
        from app.services.account_import_service import execute_import
        from app.db.models import WatchedTicker
        from sqlalchemy import select

        result = await execute_import(session, USER_A)

        rows = (await session.execute(
            select(WatchedTicker).where(WatchedTicker.user_id == USER_A)
        )).scalars().all()
        assert len(rows) == 2
        tickers = {r.ticker for r in rows}
        assert tickers == {"AAPL", "MSFT"}

    @pytest.mark.asyncio
    async def test_does_not_copy_inactive_tickers(self, session):
        from app.services.account_import_service import execute_import
        from app.db.models import WatchedTicker
        from sqlalchemy import select

        await execute_import(session, USER_A)

        rows = (await session.execute(
            select(WatchedTicker).where(WatchedTicker.user_id == USER_A)
        )).scalars().all()
        assert all(r.active for r in rows)
        assert "GOOG" not in {r.ticker for r in rows}

    @pytest.mark.asyncio
    async def test_copies_portfolio(self, session):
        from app.services.account_import_service import execute_import
        from app.db.models import Portfolio
        from sqlalchemy import select

        await execute_import(session, USER_A)

        rows = (await session.execute(
            select(Portfolio).where(Portfolio.user_id == USER_A)
        )).scalars().all()
        assert len(rows) == 1
        assert rows[0].name == "My Portfolio"

    @pytest.mark.asyncio
    async def test_copies_active_positions(self, session):
        from app.services.account_import_service import execute_import
        from app.db.models import Portfolio, PortfolioPosition
        from sqlalchemy import select

        await execute_import(session, USER_A)

        user_po = (await session.execute(
            select(Portfolio).where(Portfolio.user_id == USER_A)
        )).scalar_one()
        positions = (await session.execute(
            select(PortfolioPosition)
            .where(PortfolioPosition.portfolio_id == user_po.id)
        )).scalars().all()
        assert len(positions) == 2
        assert {p.ticker for p in positions} == {"AAPL", "MSFT"}

    @pytest.mark.asyncio
    async def test_copies_delivery_prefs(self, session):
        from app.services.account_import_service import execute_import
        from app.db.models import UserDeliveryPref
        from sqlalchemy import select

        await execute_import(session, USER_A)

        prefs = (await session.execute(
            select(UserDeliveryPref).where(UserDeliveryPref.user_id == USER_A)
        )).scalars().all()
        assert len(prefs) == 1
        assert prefs[0].channel == "in_app"

    @pytest.mark.asyncio
    async def test_system_rows_preserved(self, session):
        """Source system-owned rows must be untouched after import."""
        from app.services.account_import_service import execute_import
        from app.db.models import WatchedTicker, Portfolio
        from sqlalchemy import select

        await execute_import(session, USER_A)

        sys_tickers = (await session.execute(
            select(WatchedTicker).where(WatchedTicker.user_id == SYSTEM_DEFAULT_USER_ID)
        )).scalars().all()
        assert len(sys_tickers) == 3  # all 3 original rows (including inactive)

        sys_portfolios = (await session.execute(
            select(Portfolio).where(Portfolio.user_id == SYSTEM_DEFAULT_USER_ID)
        )).scalars().all()
        assert len(sys_portfolios) == 1  # original still present

    @pytest.mark.asyncio
    async def test_new_rows_have_different_ids(self, session):
        """Imported rows have new UUIDs, not the system row UUIDs."""
        from app.services.account_import_service import execute_import
        from app.db.models import WatchedTicker
        from sqlalchemy import select

        await execute_import(session, USER_A)

        user_ids = {r.id for r in (await session.execute(
            select(WatchedTicker).where(WatchedTicker.user_id == USER_A)
        )).scalars().all()}

        assert "wt-sys-1" not in user_ids
        assert "wt-sys-2" not in user_ids

    @pytest.mark.asyncio
    async def test_result_counts_correct(self, session):
        from app.services.account_import_service import execute_import

        result = await execute_import(session, USER_A)

        assert result.watchlist_copied == 2
        assert result.portfolio_copied == 1
        assert result.position_copied == 2
        assert result.delivery_pref_copied == 1
        assert result.already_imported is False
        assert result.skipped == 0

    @pytest.mark.asyncio
    async def test_audit_run_id_present(self, session):
        from app.services.account_import_service import execute_import

        result = await execute_import(session, USER_A)
        assert result.audit_run_id is not None


# ---------------------------------------------------------------------------
# 5. TestExecuteImportIdempotent
# ---------------------------------------------------------------------------

class TestExecuteImportIdempotent:
    """Second import call is a no-op."""

    @pytest.mark.asyncio
    async def test_second_import_already_imported(self, session):
        from app.services.account_import_service import execute_import

        await execute_import(session, USER_A)
        result2 = await execute_import(session, USER_A)

        assert result2.already_imported is True
        assert result2.watchlist_copied == 0
        assert result2.portfolio_copied == 0
        assert result2.position_copied == 0
        assert result2.delivery_pref_copied == 0

    @pytest.mark.asyncio
    async def test_second_import_does_not_duplicate_rows(self, session):
        from app.services.account_import_service import execute_import
        from app.db.models import WatchedTicker
        from sqlalchemy import select

        await execute_import(session, USER_A)
        await execute_import(session, USER_A)

        rows = (await session.execute(
            select(WatchedTicker).where(WatchedTicker.user_id == USER_A)
        )).scalars().all()
        assert len(rows) == 2  # still 2, not 4

    @pytest.mark.asyncio
    async def test_preview_shows_already_imported_after_execute(self, session):
        from app.services.account_import_service import execute_import, preview_import

        await execute_import(session, USER_A)
        preview = await preview_import(session, USER_A)

        assert preview.already_imported is True
        assert preview.watchlist_count == 0


# ---------------------------------------------------------------------------
# 6. TestPartialExistingData
# ---------------------------------------------------------------------------

class TestPartialExistingData:
    """User already has some rows; those are skipped, system rows not duplicated."""

    @pytest.mark.asyncio
    async def test_existing_ticker_skipped(self, session):
        """If user already has AAPL, only MSFT is imported."""
        from app.services.account_import_service import execute_import
        from app.db.models import WatchedTicker
        from sqlalchemy import select

        # Pre-seed user with AAPL
        session.add(WatchedTicker(
            id="wt-user-aapl", user_id=USER_A, ticker="AAPL",
            company_name="Apple (existing)", active=True,
        ))
        await session.flush()

        result = await execute_import(session, USER_A)

        user_tickers = (await session.execute(
            select(WatchedTicker).where(WatchedTicker.user_id == USER_A)
        )).scalars().all()

        assert len(user_tickers) == 2  # existing AAPL + imported MSFT
        assert {r.ticker for r in user_tickers} == {"AAPL", "MSFT"}
        assert result.watchlist_copied == 1  # only MSFT imported
        assert result.skipped >= 1

    @pytest.mark.asyncio
    async def test_existing_portfolio_name_skipped(self, session):
        """If user already has 'My Portfolio', the system one is skipped."""
        from app.services.account_import_service import execute_import
        from app.db.models import Portfolio
        from sqlalchemy import select

        session.add(Portfolio(
            id="po-user-existing", user_id=USER_A,
            name="My Portfolio", is_default=False,
        ))
        await session.flush()

        result = await execute_import(session, USER_A)

        user_portfolios = (await session.execute(
            select(Portfolio).where(Portfolio.user_id == USER_A)
        )).scalars().all()
        assert len(user_portfolios) == 1  # the pre-existing one only
        assert result.portfolio_copied == 0


# ---------------------------------------------------------------------------
# 7. TestDuplicatePrevention
# ---------------------------------------------------------------------------

class TestDuplicatePrevention:
    """No duplicates are created even with unusual DB state."""

    @pytest.mark.asyncio
    async def test_no_duplicate_tickers_on_first_import(self, session):
        """Each system ticker produces exactly one user row."""
        from app.services.account_import_service import execute_import
        from app.db.models import WatchedTicker
        from sqlalchemy import select

        await execute_import(session, USER_A)

        rows = (await session.execute(
            select(WatchedTicker).where(WatchedTicker.user_id == USER_A)
        )).scalars().all()
        tickers = [r.ticker for r in rows]
        assert len(tickers) == len(set(tickers))  # no duplicates

    @pytest.mark.asyncio
    async def test_no_duplicate_portfolios_on_first_import(self, session):
        from app.services.account_import_service import execute_import
        from app.db.models import Portfolio
        from sqlalchemy import select

        await execute_import(session, USER_A)

        rows = (await session.execute(
            select(Portfolio).where(Portfolio.user_id == USER_A)
        )).scalars().all()
        names = [r.name for r in rows]
        assert len(names) == len(set(names))

    @pytest.mark.asyncio
    async def test_delivery_prefs_not_imported_twice(self, session):
        """Prefs already present skip the import path."""
        from app.services.account_import_service import execute_import
        from app.db.models import UserDeliveryPref
        from sqlalchemy import select

        # Pre-seed user with a pref
        session.add(UserDeliveryPref(
            id="pref-user-existing", user_id=USER_A,
            channel="in_app", enabled=True, min_severity="medium",
            quiet_hours_start=21, quiet_hours_end=8, timezone="US/Eastern", daily_cap=10,
        ))
        await session.flush()

        result = await execute_import(session, USER_A)

        prefs = (await session.execute(
            select(UserDeliveryPref).where(UserDeliveryPref.user_id == USER_A)
        )).scalars().all()
        assert len(prefs) == 1  # still just the existing one
        assert result.delivery_pref_copied == 0


# ---------------------------------------------------------------------------
# 8. TestAuditLogging
# ---------------------------------------------------------------------------

class TestAuditLogging:
    """Audit entries are written for each imported resource type."""

    @pytest.mark.asyncio
    async def test_audit_entries_written(self, session):
        from app.services.account_import_service import execute_import
        from app.db.models import AuditLog
        from sqlalchemy import select

        await execute_import(session, USER_A)

        entries = (await session.execute(
            select(AuditLog)
            .where(AuditLog.user_id == USER_A)
            .where(AuditLog.action == "import")
        )).scalars().all()

        # Expect: 2 ticker + 1 portfolio + 2 position + 1 pref + 1 run = 7
        assert len(entries) == 7

    @pytest.mark.asyncio
    async def test_audit_resource_types_correct(self, session):
        from app.services.account_import_service import execute_import
        from app.db.models import AuditLog
        from sqlalchemy import select

        await execute_import(session, USER_A)

        entries = (await session.execute(
            select(AuditLog)
            .where(AuditLog.user_id == USER_A)
            .where(AuditLog.action == "import")
        )).scalars().all()

        resource_types = {e.resource for e in entries}
        assert "watched_ticker" in resource_types
        assert "portfolio" in resource_types
        assert "portfolio_position" in resource_types
        assert "delivery_pref" in resource_types
        assert "import_run" in resource_types

    @pytest.mark.asyncio
    async def test_audit_entries_reference_new_row_ids(self, session):
        """Each non-run audit entry's resource_id matches a user-owned row."""
        from app.services.account_import_service import execute_import
        from app.db.models import AuditLog, WatchedTicker
        from sqlalchemy import select

        await execute_import(session, USER_A)

        ticker_audit = (await session.execute(
            select(AuditLog)
            .where(AuditLog.user_id == USER_A)
            .where(AuditLog.action == "import")
            .where(AuditLog.resource == "watched_ticker")
        )).scalars().all()

        user_ticker_ids = {r.id for r in (await session.execute(
            select(WatchedTicker).where(WatchedTicker.user_id == USER_A)
        )).scalars().all()}

        for entry in ticker_audit:
            assert entry.resource_id in user_ticker_ids


# ---------------------------------------------------------------------------
# 9. TestRollback
# ---------------------------------------------------------------------------

class TestRollback:
    """rollback_import deletes only imported rows; system rows untouched."""

    @pytest.mark.asyncio
    async def test_rollback_removes_user_tickers(self, session):
        from app.services.account_import_service import execute_import, rollback_import
        from app.db.models import WatchedTicker
        from sqlalchemy import select

        await execute_import(session, USER_A)
        result = await rollback_import(session, USER_A)

        user_tickers = (await session.execute(
            select(WatchedTicker).where(WatchedTicker.user_id == USER_A)
        )).scalars().all()
        assert len(user_tickers) == 0
        assert result.watchlist_deleted == 2

    @pytest.mark.asyncio
    async def test_rollback_removes_user_portfolios(self, session):
        from app.services.account_import_service import execute_import, rollback_import
        from app.db.models import Portfolio
        from sqlalchemy import select

        await execute_import(session, USER_A)
        result = await rollback_import(session, USER_A)

        user_portfolios = (await session.execute(
            select(Portfolio).where(Portfolio.user_id == USER_A)
        )).scalars().all()
        assert len(user_portfolios) == 0
        assert result.portfolio_deleted == 1

    @pytest.mark.asyncio
    async def test_rollback_removes_imported_positions(self, session):
        from app.services.account_import_service import execute_import, rollback_import
        from app.db.models import Portfolio, PortfolioPosition
        from sqlalchemy import select

        await execute_import(session, USER_A)
        result = await rollback_import(session, USER_A)

        # User portfolio is deleted; no positions should remain
        user_portfolios = (await session.execute(
            select(Portfolio).where(Portfolio.user_id == USER_A)
        )).scalars().all()
        assert len(user_portfolios) == 0
        assert result.position_deleted == 2

    @pytest.mark.asyncio
    async def test_rollback_preserves_system_tickers(self, session):
        """System-owned rows must survive rollback."""
        from app.services.account_import_service import execute_import, rollback_import
        from app.db.models import WatchedTicker
        from sqlalchemy import select

        await execute_import(session, USER_A)
        await rollback_import(session, USER_A)

        sys_tickers = (await session.execute(
            select(WatchedTicker).where(WatchedTicker.user_id == SYSTEM_DEFAULT_USER_ID)
        )).scalars().all()
        assert len(sys_tickers) == 3  # all 3 system rows intact

    @pytest.mark.asyncio
    async def test_rollback_preserves_system_portfolios(self, session):
        from app.services.account_import_service import execute_import, rollback_import
        from app.db.models import Portfolio, PortfolioPosition
        from sqlalchemy import select

        await execute_import(session, USER_A)
        await rollback_import(session, USER_A)

        sys_portfolios = (await session.execute(
            select(Portfolio).where(Portfolio.user_id == SYSTEM_DEFAULT_USER_ID)
        )).scalars().all()
        assert len(sys_portfolios) == 1

        sys_positions = (await session.execute(
            select(PortfolioPosition).where(PortfolioPosition.portfolio_id == "po-sys-1")
        )).scalars().all()
        assert len(sys_positions) == 3  # all 3 original positions intact

    @pytest.mark.asyncio
    async def test_rollback_result_total(self, session):
        from app.services.account_import_service import execute_import, rollback_import

        await execute_import(session, USER_A)
        result = await rollback_import(session, USER_A)

        assert result.total_deleted == (
            result.watchlist_deleted
            + result.portfolio_deleted
            + result.position_deleted
            + result.delivery_pref_deleted
        )


# ---------------------------------------------------------------------------
# 10. TestRollbackAfterRollback
# ---------------------------------------------------------------------------

class TestRollbackAfterRollback:
    """After rollback the import sentinel is cleared; re-import is possible."""

    @pytest.mark.asyncio
    async def test_reimport_after_rollback_works(self, session):
        from app.services.account_import_service import execute_import, rollback_import
        from app.db.models import WatchedTicker
        from sqlalchemy import select

        r1 = await execute_import(session, USER_A)
        assert r1.already_imported is False

        await rollback_import(session, USER_A)

        r2 = await execute_import(session, USER_A)
        assert r2.already_imported is False
        assert r2.watchlist_copied == 2

        user_tickers = (await session.execute(
            select(WatchedTicker).where(WatchedTicker.user_id == USER_A)
        )).scalars().all()
        assert len(user_tickers) == 2

    @pytest.mark.asyncio
    async def test_rollback_no_op_when_nothing_imported(self, session):
        """Rollback with no prior import returns zero counts gracefully."""
        from app.services.account_import_service import rollback_import

        result = await rollback_import(session, USER_A)
        assert result.total_deleted == 0


# ---------------------------------------------------------------------------
# 11. TestDeliveryPrefImport
# ---------------------------------------------------------------------------

class TestDeliveryPrefImport:
    """Delivery prefs only imported when user has none."""

    @pytest.mark.asyncio
    async def test_prefs_imported_when_user_has_none(self, session):
        from app.services.account_import_service import execute_import, preview_import

        preview = await preview_import(session, USER_A)
        assert preview.delivery_pref_count == 1

        result = await execute_import(session, USER_A)
        assert result.delivery_pref_copied == 1

    @pytest.mark.asyncio
    async def test_prefs_not_imported_when_user_has_existing(self, session):
        from app.services.account_import_service import execute_import, preview_import
        from app.db.models import UserDeliveryPref

        session.add(UserDeliveryPref(
            id="pref-pre", user_id=USER_A,
            channel="email", enabled=False, min_severity="high",
            quiet_hours_start=23, quiet_hours_end=6, timezone="US/Pacific", daily_cap=5,
        ))
        await session.flush()

        preview = await preview_import(session, USER_A)
        assert preview.delivery_pref_count == 0

        result = await execute_import(session, USER_A)
        assert result.delivery_pref_copied == 0

    @pytest.mark.asyncio
    async def test_pref_values_copied_correctly(self, session):
        """Imported pref mirrors the system pref values."""
        from app.services.account_import_service import execute_import
        from app.db.models import UserDeliveryPref
        from sqlalchemy import select

        await execute_import(session, USER_A)

        pref = (await session.execute(
            select(UserDeliveryPref).where(UserDeliveryPref.user_id == USER_A)
        )).scalar_one()

        assert pref.channel == "in_app"
        assert pref.enabled is True
        assert pref.min_severity == "info"
        assert pref.quiet_hours_start == 22
        assert pref.daily_cap == 20
