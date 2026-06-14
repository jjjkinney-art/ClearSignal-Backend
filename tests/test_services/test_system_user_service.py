"""
Tests for system_user_service — Phase 16 · Slice 2.

Covers: null-session safety, ensure_system_user idempotency,
claim_null_ownership (first claim, repeated claim, per-table counts),
restore_null_ownership (exact inverse), no-real-user-overwrite guarantee,
mixed ownership rows, count_orphan_rows, and claimable_tables.

All tests that need DB access use the in-memory SQLite db_session fixture
from conftest.py.  Tests that only need representative tables (not all 17)
use watched_tickers, portfolios, and thesis_versions as the test surface —
the claim/restore logic is identical across all tables.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio

from app.services.system_user_service import (
    SYSTEM_DEFAULT_USER_ID,
    SYSTEM_DEFAULT_EMAIL,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _uid() -> str:
    return str(uuid.uuid4())


async def _seed_watched_ticker(session, *, user_id=None, ticker: str = "AAPL"):
    """Insert a WatchedTicker row and return it."""
    from app.db.models import WatchedTicker
    from datetime import datetime, timezone
    row = WatchedTicker(
        id=_uid(),
        ticker=ticker,
        company_name="Apple Inc.",
        user_id=user_id,
        active=True,
        added_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    session.add(row)
    await session.flush()
    return row


async def _seed_portfolio(session, *, user_id=None, name: str = "Test Portfolio"):
    """Insert a Portfolio row and return it."""
    from app.db.models import Portfolio
    row = Portfolio(id=_uid(), user_id=user_id, name=name)
    session.add(row)
    await session.flush()
    return row


async def _seed_thesis_version(session, *, user_id=None, ticker: str = "AAPL"):
    """Insert a minimal ThesisVersion row and return it."""
    from app.db.models import ThesisVersion
    row = ThesisVersion(
        id=_uid(),
        ticker=ticker,
        company_name="Apple Inc.",
        session_id="test-session",
        user_id=user_id,
    )
    session.add(row)
    await session.flush()
    return row


async def _count_null(session, table: str) -> int:
    """Count rows with user_id IS NULL in the given table."""
    from sqlalchemy import text
    result = await session.execute(
        text(f"SELECT COUNT(*) FROM {table} WHERE user_id IS NULL")
    )
    return int(result.one()[0])


async def _count_system_owned(session, table: str) -> int:
    """Count rows with user_id = SYSTEM_DEFAULT_USER_ID."""
    from sqlalchemy import text
    result = await session.execute(
        text(
            f"SELECT COUNT(*) FROM {table} WHERE user_id = :sys_id"
        ),
        {"sys_id": SYSTEM_DEFAULT_USER_ID},
    )
    return int(result.one()[0])


# ---------------------------------------------------------------------------
# § NULL-SESSION SAFETY
# ---------------------------------------------------------------------------

class TestNullSessionSafety:
    """All functions return safe defaults when session is None."""

    @pytest.mark.asyncio
    async def test_ensure_system_user_none_session(self):
        from app.services.system_user_service import ensure_system_user
        assert await ensure_system_user(None) is None

    @pytest.mark.asyncio
    async def test_claim_null_ownership_none_session(self):
        from app.services.system_user_service import claim_null_ownership, ClaimResult
        result = await claim_null_ownership(None)
        assert isinstance(result, ClaimResult)
        assert result.total == 0
        assert result.claimed == {}

    @pytest.mark.asyncio
    async def test_restore_null_ownership_none_session(self):
        from app.services.system_user_service import restore_null_ownership, RestoreResult
        result = await restore_null_ownership(None)
        assert isinstance(result, RestoreResult)
        assert result.total == 0
        assert result.restored == {}

    @pytest.mark.asyncio
    async def test_count_orphan_rows_none_session(self):
        from app.services.system_user_service import count_orphan_rows
        assert await count_orphan_rows(None) == {}


# ---------------------------------------------------------------------------
# § ENSURE SYSTEM USER — idempotency
# ---------------------------------------------------------------------------

class TestEnsureSystemUser:
    """ensure_system_user creates the system row on first call; is idempotent."""

    @pytest.mark.asyncio
    async def test_creates_system_user_on_first_call(self, db_session):
        from app.services.system_user_service import ensure_system_user
        from app.db.repositories.account_repo import get_user

        user = await ensure_system_user(db_session)
        assert user is not None
        assert user.id == SYSTEM_DEFAULT_USER_ID
        assert user.email == SYSTEM_DEFAULT_EMAIL
        assert user.account_type == "system"

        # Confirm it exists in the DB
        fetched = await get_user(db_session, SYSTEM_DEFAULT_USER_ID)
        assert fetched is not None
        assert fetched.id == SYSTEM_DEFAULT_USER_ID

    @pytest.mark.asyncio
    async def test_second_call_returns_same_row(self, db_session):
        from app.services.system_user_service import ensure_system_user

        u1 = await ensure_system_user(db_session)
        u2 = await ensure_system_user(db_session)
        assert u1 is not None and u2 is not None
        assert u1.id == u2.id == SYSTEM_DEFAULT_USER_ID

    @pytest.mark.asyncio
    async def test_ten_calls_produce_one_row(self, db_session):
        from app.services.system_user_service import ensure_system_user
        from app.db.repositories.account_repo import list_users

        for _ in range(10):
            await ensure_system_user(db_session)

        system_users = await list_users(db_session, account_type="system")
        assert len(system_users) == 1
        assert system_users[0].id == SYSTEM_DEFAULT_USER_ID

    @pytest.mark.asyncio
    async def test_system_user_account_type_is_system(self, db_session):
        from app.services.system_user_service import ensure_system_user
        user = await ensure_system_user(db_session)
        assert user.account_type == "system"

    @pytest.mark.asyncio
    async def test_system_user_is_active(self, db_session):
        from app.services.system_user_service import ensure_system_user
        user = await ensure_system_user(db_session)
        assert user.is_active is True


# ---------------------------------------------------------------------------
# § CLAIM NULL OWNERSHIP — first claim
# ---------------------------------------------------------------------------

class TestClaimNullOwnership:
    """claim_null_ownership converts NULL-owned rows to system-owned."""

    @pytest.mark.asyncio
    async def test_claim_watched_ticker_null_row(self, db_session):
        from app.services.system_user_service import ensure_system_user, claim_null_ownership

        await ensure_system_user(db_session)
        wt = await _seed_watched_ticker(db_session, user_id=None)
        assert wt.user_id is None

        result = await claim_null_ownership(db_session)

        # watched_tickers row should now be system-owned
        assert result.claimed.get("watched_tickers", 0) >= 1
        assert result.total >= 1

        n = await _count_null(db_session, "watched_tickers")
        assert n == 0

        n_sys = await _count_system_owned(db_session, "watched_tickers")
        assert n_sys >= 1

    @pytest.mark.asyncio
    async def test_claim_portfolio_null_row(self, db_session):
        from app.services.system_user_service import ensure_system_user, claim_null_ownership

        await ensure_system_user(db_session)
        await _seed_portfolio(db_session, user_id=None)

        result = await claim_null_ownership(db_session)

        assert result.claimed.get("portfolios", 0) >= 1
        assert await _count_null(db_session, "portfolios") == 0

    @pytest.mark.asyncio
    async def test_claim_thesis_version_null_row(self, db_session):
        from app.services.system_user_service import ensure_system_user, claim_null_ownership

        await ensure_system_user(db_session)
        await _seed_thesis_version(db_session, user_id=None)

        result = await claim_null_ownership(db_session)

        assert result.claimed.get("thesis_versions", 0) >= 1
        assert await _count_null(db_session, "thesis_versions") == 0

    @pytest.mark.asyncio
    async def test_result_contains_per_table_counts(self, db_session):
        from app.services.system_user_service import (
            ensure_system_user, claim_null_ownership, claimable_tables
        )

        await ensure_system_user(db_session)
        await _seed_watched_ticker(db_session, user_id=None)
        await _seed_portfolio(db_session, user_id=None)

        result = await claim_null_ownership(db_session)

        # Every claimable table should have an entry in claimed (even if 0)
        for table in claimable_tables():
            assert table in result.claimed, f"Table '{table}' missing from claim result"

    @pytest.mark.asyncio
    async def test_total_equals_sum_of_per_table_counts(self, db_session):
        from app.services.system_user_service import ensure_system_user, claim_null_ownership

        await ensure_system_user(db_session)
        await _seed_watched_ticker(db_session, user_id=None)
        await _seed_portfolio(db_session, user_id=None)
        await _seed_thesis_version(db_session, user_id=None)

        result = await claim_null_ownership(db_session)

        assert result.total == sum(result.claimed.values())

    @pytest.mark.asyncio
    async def test_system_user_id_in_result(self, db_session):
        from app.services.system_user_service import ensure_system_user, claim_null_ownership

        await ensure_system_user(db_session)
        result = await claim_null_ownership(db_session)
        assert result.system_user_id == SYSTEM_DEFAULT_USER_ID

    @pytest.mark.asyncio
    async def test_multiple_null_rows_same_table(self, db_session):
        from app.services.system_user_service import ensure_system_user, claim_null_ownership

        await ensure_system_user(db_session)
        await _seed_watched_ticker(db_session, user_id=None, ticker="AAPL")
        await _seed_watched_ticker(db_session, user_id=None, ticker="MSFT")
        await _seed_watched_ticker(db_session, user_id=None, ticker="GOOG")

        result = await claim_null_ownership(db_session)

        assert result.claimed.get("watched_tickers", 0) >= 3
        assert await _count_null(db_session, "watched_tickers") == 0


# ---------------------------------------------------------------------------
# § CLAIM IDEMPOTENCY — second claim claims 0 rows
# ---------------------------------------------------------------------------

class TestClaimIdempotency:
    """A second pass of claim_null_ownership claims 0 additional rows."""

    @pytest.mark.asyncio
    async def test_second_claim_returns_zero_total(self, db_session):
        from app.services.system_user_service import ensure_system_user, claim_null_ownership

        await ensure_system_user(db_session)
        await _seed_watched_ticker(db_session, user_id=None)
        await _seed_portfolio(db_session, user_id=None)

        # First pass
        first = await claim_null_ownership(db_session)
        assert first.total >= 2

        # Second pass — must claim nothing
        second = await claim_null_ownership(db_session)
        assert second.total == 0

    @pytest.mark.asyncio
    async def test_second_claim_per_table_all_zero(self, db_session):
        from app.services.system_user_service import (
            ensure_system_user, claim_null_ownership, claimable_tables
        )

        await ensure_system_user(db_session)
        await _seed_watched_ticker(db_session, user_id=None)

        await claim_null_ownership(db_session)
        second = await claim_null_ownership(db_session)

        for table in claimable_tables():
            assert second.claimed.get(table, 0) == 0, (
                f"Table '{table}' claimed {second.claimed.get(table)} rows on second pass"
            )

    @pytest.mark.asyncio
    async def test_ten_calls_same_result_after_first(self, db_session):
        from app.services.system_user_service import ensure_system_user, claim_null_ownership

        await ensure_system_user(db_session)
        await _seed_watched_ticker(db_session, user_id=None)

        await claim_null_ownership(db_session)

        for _ in range(9):
            extra = await claim_null_ownership(db_session)
            assert extra.total == 0


# ---------------------------------------------------------------------------
# § NO REAL-USER OVERWRITE
# ---------------------------------------------------------------------------

class TestNoRealUserOverwrite:
    """claim_null_ownership must not touch rows already owned by a real user."""

    @pytest.mark.asyncio
    async def test_real_user_watched_ticker_not_claimed(self, db_session):
        from app.services.system_user_service import ensure_system_user, claim_null_ownership
        from sqlalchemy import text

        await ensure_system_user(db_session)
        real_user_id = _uid()
        wt = await _seed_watched_ticker(db_session, user_id=real_user_id)

        await claim_null_ownership(db_session)

        # Verify the row still belongs to the real user
        result = await db_session.execute(
            text("SELECT user_id FROM watched_tickers WHERE id = :id"),
            {"id": wt.id},
        )
        row = result.one()
        assert row[0] == real_user_id, (
            f"Real-user row was overwritten: expected {real_user_id}, got {row[0]}"
        )

    @pytest.mark.asyncio
    async def test_real_user_portfolio_not_claimed(self, db_session):
        from app.services.system_user_service import ensure_system_user, claim_null_ownership
        from sqlalchemy import text

        await ensure_system_user(db_session)
        real_user_id = _uid()
        portfolio = await _seed_portfolio(db_session, user_id=real_user_id)

        await claim_null_ownership(db_session)

        result = await db_session.execute(
            text("SELECT user_id FROM portfolios WHERE id = :id"),
            {"id": portfolio.id},
        )
        assert result.one()[0] == real_user_id

    @pytest.mark.asyncio
    async def test_real_user_thesis_version_not_claimed(self, db_session):
        from app.services.system_user_service import ensure_system_user, claim_null_ownership
        from sqlalchemy import text

        await ensure_system_user(db_session)
        real_user_id = _uid()
        tv = await _seed_thesis_version(db_session, user_id=real_user_id)

        await claim_null_ownership(db_session)

        result = await db_session.execute(
            text("SELECT user_id FROM thesis_versions WHERE id = :id"),
            {"id": tv.id},
        )
        assert result.one()[0] == real_user_id

    @pytest.mark.asyncio
    async def test_claim_count_only_reflects_null_rows(self, db_session):
        """Only NULL rows are counted; real-user rows are invisible to claim."""
        from app.services.system_user_service import ensure_system_user, claim_null_ownership

        await ensure_system_user(db_session)
        real_user_id = _uid()

        # 2 NULL rows + 1 real-user row
        await _seed_watched_ticker(db_session, user_id=None, ticker="AAPL")
        await _seed_watched_ticker(db_session, user_id=None, ticker="MSFT")
        await _seed_watched_ticker(db_session, user_id=real_user_id, ticker="GOOG")

        result = await claim_null_ownership(db_session)
        assert result.claimed["watched_tickers"] == 2


# ---------------------------------------------------------------------------
# § MIXED OWNERSHIP
# ---------------------------------------------------------------------------

class TestMixedOwnership:
    """Tables with a mix of NULL, real-user, and already-system-owned rows."""

    @pytest.mark.asyncio
    async def test_mixed_ownership_claim_only_null(self, db_session):
        from app.services.system_user_service import ensure_system_user, claim_null_ownership

        await ensure_system_user(db_session)
        real_uid = _uid()

        await _seed_watched_ticker(db_session, user_id=None, ticker="NULL1")
        await _seed_watched_ticker(db_session, user_id=None, ticker="NULL2")
        await _seed_watched_ticker(db_session, user_id=real_uid, ticker="REAL1")
        await _seed_watched_ticker(
            db_session, user_id=SYSTEM_DEFAULT_USER_ID, ticker="SYS1"
        )

        result = await claim_null_ownership(db_session)

        # Only the 2 NULL rows should be claimed
        assert result.claimed["watched_tickers"] == 2
        # 0 NULL rows remain
        assert await _count_null(db_session, "watched_tickers") == 0
        # 3 system-owned rows total (2 newly claimed + 1 pre-existing)
        assert await _count_system_owned(db_session, "watched_tickers") == 3

    @pytest.mark.asyncio
    async def test_mixed_ownership_claim_across_two_tables(self, db_session):
        from app.services.system_user_service import ensure_system_user, claim_null_ownership

        await ensure_system_user(db_session)
        real_uid = _uid()

        await _seed_watched_ticker(db_session, user_id=None)
        await _seed_portfolio(db_session, user_id=None)
        await _seed_portfolio(db_session, user_id=real_uid, name="Real User Portfolio")

        result = await claim_null_ownership(db_session)

        assert result.claimed["watched_tickers"] >= 1
        assert result.claimed["portfolios"] >= 1
        assert result.total >= 2


# ---------------------------------------------------------------------------
# § RESTORE NULL OWNERSHIP — exact inverse
# ---------------------------------------------------------------------------

class TestRestoreNullOwnership:
    """restore_null_ownership is the exact inverse of claim_null_ownership."""

    @pytest.mark.asyncio
    async def test_restore_returns_null_after_claim(self, db_session):
        from app.services.system_user_service import (
            ensure_system_user, claim_null_ownership, restore_null_ownership
        )

        await ensure_system_user(db_session)
        await _seed_watched_ticker(db_session, user_id=None)
        await _seed_portfolio(db_session, user_id=None)

        claim_result = await claim_null_ownership(db_session)
        claimed_total = claim_result.total

        restore_result = await restore_null_ownership(db_session)

        assert restore_result.total == claimed_total
        # All system-owned rows removed
        assert await _count_system_owned(db_session, "watched_tickers") == 0
        assert await _count_system_owned(db_session, "portfolios") == 0
        # Rows are back to NULL
        assert await _count_null(db_session, "watched_tickers") >= 1
        assert await _count_null(db_session, "portfolios") >= 1

    @pytest.mark.asyncio
    async def test_restore_does_not_touch_real_user_rows(self, db_session):
        from app.services.system_user_service import (
            ensure_system_user, claim_null_ownership, restore_null_ownership
        )
        from sqlalchemy import text

        await ensure_system_user(db_session)
        real_uid = _uid()

        wt_null = await _seed_watched_ticker(db_session, user_id=None, ticker="NULL1")
        wt_real = await _seed_watched_ticker(db_session, user_id=real_uid, ticker="REAL1")

        await claim_null_ownership(db_session)
        await restore_null_ownership(db_session)

        # Real-user row untouched
        result = await db_session.execute(
            text("SELECT user_id FROM watched_tickers WHERE id = :id"),
            {"id": wt_real.id},
        )
        assert result.one()[0] == real_uid

        # Previously-NULL row is NULL again
        result = await db_session.execute(
            text("SELECT user_id FROM watched_tickers WHERE id = :id"),
            {"id": wt_null.id},
        )
        assert result.one()[0] is None

    @pytest.mark.asyncio
    async def test_restore_after_restore_claims_zero(self, db_session):
        """Double-restore should be idempotent (no rows to restore on second call)."""
        from app.services.system_user_service import (
            ensure_system_user, claim_null_ownership, restore_null_ownership
        )

        await ensure_system_user(db_session)
        await _seed_watched_ticker(db_session, user_id=None)

        await claim_null_ownership(db_session)
        await restore_null_ownership(db_session)

        # Second restore: system-owned rows are gone; nothing to restore
        second_restore = await restore_null_ownership(db_session)
        assert second_restore.total == 0

    @pytest.mark.asyncio
    async def test_claim_restore_claim_cycle(self, db_session):
        """claim → restore → claim should work identically to the first claim."""
        from app.services.system_user_service import (
            ensure_system_user, claim_null_ownership, restore_null_ownership
        )

        await ensure_system_user(db_session)
        await _seed_watched_ticker(db_session, user_id=None)

        first_claim = await claim_null_ownership(db_session)
        await restore_null_ownership(db_session)
        second_claim = await claim_null_ownership(db_session)

        assert second_claim.claimed["watched_tickers"] == first_claim.claimed["watched_tickers"]

    @pytest.mark.asyncio
    async def test_restore_result_has_correct_table_counts(self, db_session):
        from app.services.system_user_service import (
            ensure_system_user, claim_null_ownership, restore_null_ownership,
            claimable_tables,
        )

        await ensure_system_user(db_session)
        await _seed_watched_ticker(db_session, user_id=None)
        await _seed_portfolio(db_session, user_id=None)

        await claim_null_ownership(db_session)
        restore = await restore_null_ownership(db_session)

        # Every claimable table has an entry in restored
        for table in claimable_tables():
            assert table in restore.restored

    @pytest.mark.asyncio
    async def test_restore_total_equals_sum_of_per_table_counts(self, db_session):
        from app.services.system_user_service import (
            ensure_system_user, claim_null_ownership, restore_null_ownership
        )

        await ensure_system_user(db_session)
        await _seed_watched_ticker(db_session, user_id=None)

        await claim_null_ownership(db_session)
        restore = await restore_null_ownership(db_session)

        assert restore.total == sum(restore.restored.values())


# ---------------------------------------------------------------------------
# § COUNT ORPHAN ROWS
# ---------------------------------------------------------------------------

class TestCountOrphanRows:
    """count_orphan_rows returns per-table NULL user_id counts."""

    @pytest.mark.asyncio
    async def test_counts_zero_after_claim(self, db_session):
        from app.services.system_user_service import (
            ensure_system_user, claim_null_ownership, count_orphan_rows
        )

        await ensure_system_user(db_session)
        await _seed_watched_ticker(db_session, user_id=None)

        await claim_null_ownership(db_session)

        orphans = await count_orphan_rows(db_session)
        for table, count in orphans.items():
            assert count == 0, f"Table '{table}' has {count} orphan rows after claim"

    @pytest.mark.asyncio
    async def test_counts_null_rows_before_claim(self, db_session):
        from app.services.system_user_service import ensure_system_user, count_orphan_rows

        await ensure_system_user(db_session)
        await _seed_watched_ticker(db_session, user_id=None)
        await _seed_portfolio(db_session, user_id=None)

        orphans = await count_orphan_rows(db_session)

        assert orphans.get("watched_tickers", 0) >= 1
        assert orphans.get("portfolios", 0) >= 1

    @pytest.mark.asyncio
    async def test_returns_all_claimable_tables(self, db_session):
        from app.services.system_user_service import (
            ensure_system_user, count_orphan_rows, claimable_tables
        )

        await ensure_system_user(db_session)
        orphans = await count_orphan_rows(db_session)

        for table in claimable_tables():
            assert table in orphans, f"Table '{table}' missing from orphan count"


# ---------------------------------------------------------------------------
# § CLAIMABLE_TABLES
# ---------------------------------------------------------------------------

class TestClaimableTables:
    """claimable_tables() returns the expected table set."""

    def test_returns_tuple(self):
        from app.services.system_user_service import claimable_tables
        assert isinstance(claimable_tables(), tuple)

    def test_contains_watched_tickers(self):
        from app.services.system_user_service import claimable_tables
        assert "watched_tickers" in claimable_tables()

    def test_contains_portfolios(self):
        from app.services.system_user_service import claimable_tables
        assert "portfolios" in claimable_tables()

    def test_contains_thesis_versions(self):
        from app.services.system_user_service import claimable_tables
        assert "thesis_versions" in claimable_tables()

    def test_does_not_contain_notifications(self):
        """notifications.user_id is NOT NULL — not claimable."""
        from app.services.system_user_service import claimable_tables
        assert "notifications" not in claimable_tables()

    def test_does_not_contain_users(self):
        """users is the identity table — not claimed against itself."""
        from app.services.system_user_service import claimable_tables
        assert "users" not in claimable_tables()

    def test_does_not_contain_audit_log(self):
        """audit_log.user_id is an actor field, not ownership."""
        from app.services.system_user_service import claimable_tables
        assert "audit_log" not in claimable_tables()

    def test_contains_17_tables(self):
        from app.services.system_user_service import claimable_tables
        assert len(claimable_tables()) == 17
