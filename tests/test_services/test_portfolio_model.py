"""
tests/test_services/test_portfolio_model.py

Phase 10D · Slice 1 — Portfolio model tests.

Coverage
--------
  Portfolio CRUD
    - create → get → list round-trip
    - create is idempotent on (user_id, name): re-calling returns the existing row
    - update name and description
    - delete removes the portfolio and its positions
    - list returns portfolios ordered by created_at

  Position CRUD
    - add position → get → list round-trip
    - add is idempotent on (portfolio_id, ticker): active row returned unchanged
    - re-adding a removed (inactive) position reactivates it
    - remove sets active=False (soft-delete)
    - update mutable fields (membership_class, weight, cost_basis, shares, notes)
    - list returns only active positions by default
    - list(include_inactive=True) returns all rows
    - position_list_by_ticker returns positions across portfolios

  Default portfolio
    - portfolio_create with is_default=True
    - portfolio_get_default returns the is_default row
    - portfolio_get_default returns None when none exists

  Multi-portfolio support
    - two portfolios for the same user coexist
    - portfolios for different users are isolated
    - position_list_by_ticker can span multiple portfolios

  Membership classes
    - owned, watchlist, on_radar all accepted
    - membership_class is preserved through get/update

  Insight schema (Slice 1 — inert)
    - insight_upsert inserts a new row
    - insight_upsert on same content_key updates mutable fields (no duplicate)
    - insight_list returns rows ordered by rank_score desc

  ORM / migration correctness
    - Portfolio, PortfolioPosition, PortfolioInsight appear in Base.metadata.tables
    - db_table_count is at least the current schema size (a growth floor, not an
      exact count — new tables are added routinely, so an exact assertion is a
      brittle canary; the specific-table checks above are the real guard)
    - null session → every function returns safe default (no exception)
"""

from __future__ import annotations

import uuid
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

def _uid() -> str:
    return str(uuid.uuid4())


async def _make_portfolio(session, name="Test Portfolio", user_id=None, is_default=False):
    from app.db.repositories.portfolio_repo import portfolio_create
    return await portfolio_create(session, name=name, user_id=user_id, is_default=is_default)


# ---------------------------------------------------------------------------
# ORM / migration correctness
# ---------------------------------------------------------------------------

class TestSchemaCorrectness:
    def test_new_tables_in_metadata(self):
        tables = Base.metadata.tables
        assert "portfolios" in tables
        assert "portfolio_positions" in tables
        assert "portfolio_insights" in tables

    def test_db_table_count_floor(self):
        # Growth floor rather than an exact count: the schema has expanded from
        # 31 (10D) → 35 (Phase 16 identity) → 38 (Phase 17 billing) → 59 (loop /
        # scenario / dossier / delivery tables).  An exact assertion broke on
        # every schema addition and carried no real guard value beyond the
        # specific-table presence/column checks above.  A floor still catches a
        # catastrophic schema loss (e.g. a migration dropping tables) without
        # failing on every legitimate addition.
        assert len(Base.metadata.tables) >= 59

    def test_portfolios_columns(self):
        col_names = {c.name for c in Base.metadata.tables["portfolios"].columns}
        assert {"id", "user_id", "name", "description", "is_default",
                "created_at", "updated_at"} <= col_names

    def test_portfolio_positions_columns(self):
        col_names = {c.name for c in Base.metadata.tables["portfolio_positions"].columns}
        assert {"id", "portfolio_id", "ticker", "membership_class",
                "weight", "cost_basis", "shares", "notes", "active",
                "added_at", "updated_at"} <= col_names

    def test_portfolio_insights_columns(self):
        col_names = {c.name for c in Base.metadata.tables["portfolio_insights"].columns}
        assert {"id", "portfolio_id", "insight_type", "cluster_label",
                "member_tickers", "cluster_weight", "severity", "severity_rank",
                "rank_score", "body_json", "cross_exposure_as_of", "stale_input",
                "content_key", "created_at", "updated_at",
                "last_delivered_at"} <= col_names

    def test_unique_constraint_portfolio_positions(self):
        table = Base.metadata.tables["portfolio_positions"]
        unique_cols = []
        for constraint in table.constraints:
            from sqlalchemy import UniqueConstraint
            if isinstance(constraint, UniqueConstraint):
                unique_cols.append({c.name for c in constraint.columns})
        assert {"portfolio_id", "ticker"} in unique_cols

    def test_unique_constraint_portfolios(self):
        table = Base.metadata.tables["portfolios"]
        unique_cols = []
        for constraint in table.constraints:
            from sqlalchemy import UniqueConstraint
            if isinstance(constraint, UniqueConstraint):
                unique_cols.append({c.name for c in constraint.columns})
        assert {"user_id", "name"} in unique_cols

    def test_unique_constraint_portfolio_insights(self):
        table = Base.metadata.tables["portfolio_insights"]
        unique_cols = []
        for constraint in table.constraints:
            from sqlalchemy import UniqueConstraint
            if isinstance(constraint, UniqueConstraint):
                unique_cols.append({c.name for c in constraint.columns})
        assert {"content_key"} in unique_cols


# ---------------------------------------------------------------------------
# Null-session safety
# ---------------------------------------------------------------------------

class TestNullSession:
    async def test_portfolio_create_null(self):
        from app.db.repositories.portfolio_repo import portfolio_create
        result = await portfolio_create(None)
        assert result is None

    async def test_portfolio_get_null(self):
        from app.db.repositories.portfolio_repo import portfolio_get
        result = await portfolio_get(None, "any-id")
        assert result is None

    async def test_portfolio_get_default_null(self):
        from app.db.repositories.portfolio_repo import portfolio_get_default
        result = await portfolio_get_default(None)
        assert result is None

    async def test_portfolio_list_null(self):
        from app.db.repositories.portfolio_repo import portfolio_list
        result = await portfolio_list(None)
        assert result == []

    async def test_portfolio_update_null(self):
        from app.db.repositories.portfolio_repo import portfolio_update
        result = await portfolio_update(None, "any-id")
        assert result is None

    async def test_portfolio_delete_null(self):
        from app.db.repositories.portfolio_repo import portfolio_delete
        result = await portfolio_delete(None, "any-id")
        assert result is False

    async def test_position_add_null(self):
        from app.db.repositories.portfolio_repo import position_add
        result = await position_add(None, "p", "AAPL")
        assert result is None

    async def test_position_get_null(self):
        from app.db.repositories.portfolio_repo import position_get
        result = await position_get(None, "p", "AAPL")
        assert result is None

    async def test_position_update_null(self):
        from app.db.repositories.portfolio_repo import position_update
        result = await position_update(None, "p", "AAPL")
        assert result is None

    async def test_position_remove_null(self):
        from app.db.repositories.portfolio_repo import position_remove
        result = await position_remove(None, "p", "AAPL")
        assert result is False

    async def test_position_list_null(self):
        from app.db.repositories.portfolio_repo import position_list
        result = await position_list(None, "p")
        assert result == []

    async def test_position_list_by_ticker_null(self):
        from app.db.repositories.portfolio_repo import position_list_by_ticker
        result = await position_list_by_ticker(None, "AAPL")
        assert result == []

    async def test_insight_upsert_null(self):
        from app.db.repositories.portfolio_repo import insight_upsert
        result = await insight_upsert(None, "p", "concentration_breach", "AI", "ck")
        assert result is None

    async def test_insight_list_null(self):
        from app.db.repositories.portfolio_repo import insight_list
        result = await insight_list(None, "p")
        assert result == []


# ---------------------------------------------------------------------------
# Portfolio CRUD
# ---------------------------------------------------------------------------

class TestPortfolioCRUD:
    async def test_create_and_get(self, db_session):
        from app.db.repositories.portfolio_repo import portfolio_create, portfolio_get

        p = await portfolio_create(db_session, name="Core Holdings")
        assert p is not None
        assert p.id is not None
        assert p.name == "Core Holdings"
        assert p.user_id is None
        assert p.is_default is False

        fetched = await portfolio_get(db_session, p.id)
        assert fetched is not None
        assert fetched.id == p.id

    async def test_create_idempotent_same_user_name(self, db_session):
        from app.db.repositories.portfolio_repo import portfolio_create

        p1 = await portfolio_create(db_session, name="Alpha")
        p2 = await portfolio_create(db_session, name="Alpha")
        assert p1.id == p2.id

    async def test_create_different_names_separate_rows(self, db_session):
        from app.db.repositories.portfolio_repo import portfolio_create

        p1 = await portfolio_create(db_session, name="Alpha")
        p2 = await portfolio_create(db_session, name="Beta")
        assert p1.id != p2.id

    async def test_list_ordered_by_created_at(self, db_session):
        from app.db.repositories.portfolio_repo import portfolio_create, portfolio_list

        p1 = await portfolio_create(db_session, name="First")
        p2 = await portfolio_create(db_session, name="Second")
        p3 = await portfolio_create(db_session, name="Third")

        rows = await portfolio_list(db_session)
        ids = [r.id for r in rows]
        assert ids.index(p1.id) < ids.index(p2.id) < ids.index(p3.id)

    async def test_update_name_and_description(self, db_session):
        from app.db.repositories.portfolio_repo import portfolio_create, portfolio_update

        p = await portfolio_create(db_session, name="Old Name")
        updated = await portfolio_update(
            db_session, p.id, name="New Name", description="Updated desc"
        )
        assert updated is not None
        assert updated.name == "New Name"
        assert updated.description == "Updated desc"

    async def test_update_nonexistent_returns_none(self, db_session):
        from app.db.repositories.portfolio_repo import portfolio_update
        result = await portfolio_update(db_session, "nonexistent-id")
        assert result is None

    async def test_delete_removes_portfolio(self, db_session):
        from app.db.repositories.portfolio_repo import (
            portfolio_create, portfolio_delete, portfolio_get
        )
        p = await portfolio_create(db_session, name="To Delete")
        deleted = await portfolio_delete(db_session, p.id)
        assert deleted is True
        assert await portfolio_get(db_session, p.id) is None

    async def test_delete_nonexistent_returns_false(self, db_session):
        from app.db.repositories.portfolio_repo import portfolio_delete
        result = await portfolio_delete(db_session, "ghost-id")
        assert result is False

    async def test_get_nonexistent_returns_none(self, db_session):
        from app.db.repositories.portfolio_repo import portfolio_get
        result = await portfolio_get(db_session, "ghost-id")
        assert result is None


# ---------------------------------------------------------------------------
# Default portfolio
# ---------------------------------------------------------------------------

class TestDefaultPortfolio:
    async def test_create_default(self, db_session):
        from app.db.repositories.portfolio_repo import portfolio_create, portfolio_get_default

        p = await portfolio_create(db_session, name="Default", is_default=True)
        assert p.is_default is True

        default = await portfolio_get_default(db_session)
        assert default is not None
        assert default.id == p.id

    async def test_get_default_returns_none_when_absent(self, db_session):
        from app.db.repositories.portfolio_repo import portfolio_get_default
        result = await portfolio_get_default(db_session)
        assert result is None

    async def test_non_default_not_returned_by_get_default(self, db_session):
        from app.db.repositories.portfolio_repo import portfolio_create, portfolio_get_default
        await portfolio_create(db_session, name="Regular", is_default=False)
        result = await portfolio_get_default(db_session)
        assert result is None

    async def test_default_and_non_default_coexist(self, db_session):
        from app.db.repositories.portfolio_repo import (
            portfolio_create, portfolio_get_default, portfolio_list
        )
        await portfolio_create(db_session, name="Regular", is_default=False)
        d = await portfolio_create(db_session, name="Default", is_default=True)

        default = await portfolio_get_default(db_session)
        assert default.id == d.id

        all_portfolios = await portfolio_list(db_session)
        assert len(all_portfolios) == 2


# ---------------------------------------------------------------------------
# Multi-portfolio support
# ---------------------------------------------------------------------------

class TestMultiPortfolio:
    async def test_two_portfolios_same_user(self, db_session):
        from app.db.repositories.portfolio_repo import portfolio_create, portfolio_list

        uid = "user-abc"
        await portfolio_create(db_session, name="Core", user_id=uid)
        await portfolio_create(db_session, name="Speculative", user_id=uid)

        rows = await portfolio_list(db_session, user_id=uid)
        assert len(rows) == 2

    async def test_portfolios_isolated_by_user(self, db_session):
        from app.db.repositories.portfolio_repo import portfolio_create, portfolio_list

        await portfolio_create(db_session, name="Alpha", user_id="user-1")
        await portfolio_create(db_session, name="Beta",  user_id="user-2")

        rows_1 = await portfolio_list(db_session, user_id="user-1")
        rows_2 = await portfolio_list(db_session, user_id="user-2")
        assert len(rows_1) == 1
        assert len(rows_2) == 1
        assert rows_1[0].name == "Alpha"
        assert rows_2[0].name == "Beta"

    async def test_global_user_id_none_isolated(self, db_session):
        from app.db.repositories.portfolio_repo import portfolio_create, portfolio_list

        await portfolio_create(db_session, name="Global", user_id=None)
        await portfolio_create(db_session, name="Named",  user_id="user-xyz")

        global_rows = await portfolio_list(db_session, user_id=None)
        named_rows  = await portfolio_list(db_session, user_id="user-xyz")
        assert len(global_rows) == 1
        assert len(named_rows)  == 1

    async def test_same_name_different_users_allowed(self, db_session):
        from app.db.repositories.portfolio_repo import portfolio_create

        p1 = await portfolio_create(db_session, name="My Portfolio", user_id="user-1")
        p2 = await portfolio_create(db_session, name="My Portfolio", user_id="user-2")
        assert p1.id != p2.id


# ---------------------------------------------------------------------------
# Position CRUD
# ---------------------------------------------------------------------------

class TestPositionCRUD:
    async def test_add_and_get(self, db_session):
        from app.db.repositories.portfolio_repo import (
            portfolio_create, position_add, position_get
        )
        p = await portfolio_create(db_session, name="P")
        pos = await position_add(db_session, p.id, "AAPL", membership_class="owned")

        assert pos is not None
        assert pos.ticker == "AAPL"
        assert pos.membership_class == "owned"
        assert pos.active is True

        fetched = await position_get(db_session, p.id, "AAPL")
        assert fetched is not None
        assert fetched.id == pos.id

    async def test_ticker_uppercased(self, db_session):
        from app.db.repositories.portfolio_repo import portfolio_create, position_add

        p = await portfolio_create(db_session, name="P")
        pos = await position_add(db_session, p.id, "aapl")
        assert pos.ticker == "AAPL"

    async def test_add_idempotent_active_row(self, db_session):
        from app.db.repositories.portfolio_repo import portfolio_create, position_add

        p = await portfolio_create(db_session, name="P")
        pos1 = await position_add(db_session, p.id, "MSFT")
        pos2 = await position_add(db_session, p.id, "MSFT")
        assert pos1.id == pos2.id

    async def test_readd_reactivates_inactive(self, db_session):
        from app.db.repositories.portfolio_repo import (
            portfolio_create, position_add, position_remove
        )
        p = await portfolio_create(db_session, name="P")
        await position_add(db_session, p.id, "GOOGL")
        await position_remove(db_session, p.id, "GOOGL")

        # Re-adding should reactivate.
        pos = await position_add(
            db_session, p.id, "GOOGL",
            membership_class="owned", weight=0.10
        )
        assert pos.active is True
        assert pos.membership_class == "owned"
        assert pos.weight == pytest.approx(0.10)

    async def test_remove_soft_deletes(self, db_session):
        from app.db.repositories.portfolio_repo import (
            portfolio_create, position_add, position_remove,
            position_get, position_list
        )
        p = await portfolio_create(db_session, name="P")
        await position_add(db_session, p.id, "NVDA")

        removed = await position_remove(db_session, p.id, "NVDA")
        assert removed is True

        # Still in DB but inactive.
        row = await position_get(db_session, p.id, "NVDA")
        assert row is not None
        assert row.active is False

        # Not in default (active-only) list.
        active = await position_list(db_session, p.id)
        assert all(r.ticker != "NVDA" for r in active)

    async def test_remove_already_inactive_returns_false(self, db_session):
        from app.db.repositories.portfolio_repo import (
            portfolio_create, position_add, position_remove
        )
        p = await portfolio_create(db_session, name="P")
        await position_add(db_session, p.id, "TSLA")
        await position_remove(db_session, p.id, "TSLA")

        result = await position_remove(db_session, p.id, "TSLA")
        assert result is False

    async def test_remove_nonexistent_returns_false(self, db_session):
        from app.db.repositories.portfolio_repo import portfolio_create, position_remove
        p = await portfolio_create(db_session, name="P")
        result = await position_remove(db_session, p.id, "GHOST")
        assert result is False

    async def test_update_mutable_fields(self, db_session):
        from app.db.repositories.portfolio_repo import (
            portfolio_create, position_add, position_update
        )
        p = await portfolio_create(db_session, name="P")
        await position_add(db_session, p.id, "AMZN", weight=0.05)

        updated = await position_update(
            db_session, p.id, "AMZN",
            membership_class="owned",
            weight=0.15,
            cost_basis=180.50,
            shares=100.0,
            notes="Core position",
        )
        assert updated is not None
        assert updated.membership_class == "owned"
        assert updated.weight    == pytest.approx(0.15)
        assert updated.cost_basis == pytest.approx(180.50)
        assert updated.shares    == pytest.approx(100.0)
        assert updated.notes     == "Core position"

    async def test_update_inactive_returns_none(self, db_session):
        from app.db.repositories.portfolio_repo import (
            portfolio_create, position_add, position_remove, position_update
        )
        p = await portfolio_create(db_session, name="P")
        await position_add(db_session, p.id, "META")
        await position_remove(db_session, p.id, "META")

        result = await position_update(db_session, p.id, "META", weight=0.1)
        assert result is None

    async def test_list_active_only_by_default(self, db_session):
        from app.db.repositories.portfolio_repo import (
            portfolio_create, position_add, position_remove, position_list
        )
        p = await portfolio_create(db_session, name="P")
        await position_add(db_session, p.id, "AAPL")
        await position_add(db_session, p.id, "MSFT")
        await position_remove(db_session, p.id, "MSFT")

        rows = await position_list(db_session, p.id)
        assert len(rows) == 1
        assert rows[0].ticker == "AAPL"

    async def test_list_include_inactive(self, db_session):
        from app.db.repositories.portfolio_repo import (
            portfolio_create, position_add, position_remove, position_list
        )
        p = await portfolio_create(db_session, name="P")
        await position_add(db_session, p.id, "AAPL")
        await position_add(db_session, p.id, "MSFT")
        await position_remove(db_session, p.id, "MSFT")

        rows = await position_list(db_session, p.id, include_inactive=True)
        assert len(rows) == 2

    async def test_delete_portfolio_removes_positions(self, db_session):
        from app.db.repositories.portfolio_repo import (
            portfolio_create, position_add, portfolio_delete, position_list
        )
        p = await portfolio_create(db_session, name="P")
        await position_add(db_session, p.id, "AAPL")
        await position_add(db_session, p.id, "MSFT")

        await portfolio_delete(db_session, p.id)

        # positions should be gone (hard-deleted with the portfolio)
        rows = await position_list(db_session, p.id, include_inactive=True)
        assert len(rows) == 0


# ---------------------------------------------------------------------------
# Membership classes
# ---------------------------------------------------------------------------

class TestMembershipClasses:
    async def test_owned(self, db_session):
        from app.db.repositories.portfolio_repo import portfolio_create, position_add
        p = await portfolio_create(db_session, name="P")
        pos = await position_add(db_session, p.id, "AAPL", membership_class="owned")
        assert pos.membership_class == "owned"

    async def test_watchlist(self, db_session):
        from app.db.repositories.portfolio_repo import portfolio_create, position_add
        p = await portfolio_create(db_session, name="P")
        pos = await position_add(db_session, p.id, "TSLA", membership_class="watchlist")
        assert pos.membership_class == "watchlist"

    async def test_on_radar(self, db_session):
        from app.db.repositories.portfolio_repo import portfolio_create, position_add
        p = await portfolio_create(db_session, name="P")
        pos = await position_add(db_session, p.id, "BABA", membership_class="on_radar")
        assert pos.membership_class == "on_radar"

    async def test_membership_class_preserved_through_update(self, db_session):
        from app.db.repositories.portfolio_repo import (
            portfolio_create, position_add, position_update
        )
        p = await portfolio_create(db_session, name="P")
        await position_add(db_session, p.id, "NVDA", membership_class="watchlist")
        pos = await position_update(
            db_session, p.id, "NVDA", membership_class="owned"
        )
        assert pos.membership_class == "owned"

    async def test_financial_fields_nullable(self, db_session):
        from app.db.repositories.portfolio_repo import portfolio_create, position_add
        p = await portfolio_create(db_session, name="P")
        pos = await position_add(db_session, p.id, "AMD")
        assert pos.weight    is None
        assert pos.cost_basis is None
        assert pos.shares    is None

    async def test_financial_fields_stored(self, db_session):
        from app.db.repositories.portfolio_repo import portfolio_create, position_add
        p = await portfolio_create(db_session, name="P")
        pos = await position_add(
            db_session, p.id, "AMD",
            weight=0.08, cost_basis=120.0, shares=50.0
        )
        assert pos.weight    == pytest.approx(0.08)
        assert pos.cost_basis == pytest.approx(120.0)
        assert pos.shares    == pytest.approx(50.0)


# ---------------------------------------------------------------------------
# Cross-portfolio ticker lookup
# ---------------------------------------------------------------------------

class TestPositionListByTicker:
    async def test_returns_positions_across_portfolios(self, db_session):
        from app.db.repositories.portfolio_repo import (
            portfolio_create, position_add, position_list_by_ticker
        )
        p1 = await portfolio_create(db_session, name="P1")
        p2 = await portfolio_create(db_session, name="P2")
        await position_add(db_session, p1.id, "NVDA")
        await position_add(db_session, p2.id, "NVDA")

        rows = await position_list_by_ticker(db_session, "NVDA")
        portfolio_ids = {r.portfolio_id for r in rows}
        assert p1.id in portfolio_ids
        assert p2.id in portfolio_ids

    async def test_excludes_inactive_by_default(self, db_session):
        from app.db.repositories.portfolio_repo import (
            portfolio_create, position_add, position_remove,
            position_list_by_ticker
        )
        p = await portfolio_create(db_session, name="P")
        await position_add(db_session, p.id, "AAPL")
        await position_remove(db_session, p.id, "AAPL")

        rows = await position_list_by_ticker(db_session, "AAPL")
        assert len(rows) == 0

    async def test_includes_inactive_when_requested(self, db_session):
        from app.db.repositories.portfolio_repo import (
            portfolio_create, position_add, position_remove,
            position_list_by_ticker
        )
        p = await portfolio_create(db_session, name="P")
        await position_add(db_session, p.id, "AAPL")
        await position_remove(db_session, p.id, "AAPL")

        rows = await position_list_by_ticker(db_session, "AAPL", active_only=False)
        assert len(rows) == 1

    async def test_ticker_normalized_to_uppercase(self, db_session):
        from app.db.repositories.portfolio_repo import (
            portfolio_create, position_add, position_list_by_ticker
        )
        p = await portfolio_create(db_session, name="P")
        await position_add(db_session, p.id, "msft")

        rows = await position_list_by_ticker(db_session, "msft")
        assert len(rows) == 1

    async def test_returns_empty_for_unknown_ticker(self, db_session):
        from app.db.repositories.portfolio_repo import position_list_by_ticker
        rows = await position_list_by_ticker(db_session, "GHOST")
        assert rows == []


# ---------------------------------------------------------------------------
# Insight schema (inert in Slice 1)
# ---------------------------------------------------------------------------

class TestInsightSchema:
    def _make_content_key(self) -> str:
        return f"ck-{_uid()}"

    async def test_insert_and_list(self, db_session):
        from app.db.repositories.portfolio_repo import (
            portfolio_create, insight_upsert, insight_list
        )
        p = await portfolio_create(db_session, name="P")
        ck = self._make_content_key()

        row = await insight_upsert(
            db_session,
            portfolio_id=p.id,
            insight_type="concentration_breach",
            cluster_label="NVDA",
            content_key=ck,
            severity="high",
            severity_rank=3,
            rank_score=2.4,
        )
        assert row is not None
        assert row.insight_type == "concentration_breach"
        assert row.severity == "high"
        assert row.severity_rank == 3

        rows = await insight_list(db_session, p.id)
        assert len(rows) == 1
        assert rows[0].content_key == ck

    async def test_upsert_updates_existing_row(self, db_session):
        from app.db.repositories.portfolio_repo import (
            portfolio_create, insight_upsert, insight_list
        )
        p = await portfolio_create(db_session, name="P")
        ck = self._make_content_key()

        await insight_upsert(
            db_session, p.id, "concentration_breach", "NVDA", ck,
            severity="medium", severity_rank=2, rank_score=1.0,
        )
        await insight_upsert(
            db_session, p.id, "concentration_breach", "NVDA", ck,
            severity="high", severity_rank=3, rank_score=2.5,
        )

        rows = await insight_list(db_session, p.id)
        assert len(rows) == 1   # no duplicate
        assert rows[0].severity == "high"
        assert rows[0].rank_score == pytest.approx(2.5)

    async def test_list_ordered_by_rank_score_desc(self, db_session):
        from app.db.repositories.portfolio_repo import (
            portfolio_create, insight_upsert, insight_list
        )
        p = await portfolio_create(db_session, name="P")

        await insight_upsert(
            db_session, p.id, "coverage_gap", "A", self._make_content_key(),
            severity="info", severity_rank=0, rank_score=0.2,
        )
        await insight_upsert(
            db_session, p.id, "concentration_breach", "B", self._make_content_key(),
            severity="high", severity_rank=3, rank_score=3.5,
        )
        await insight_upsert(
            db_session, p.id, "cluster_concentration", "C", self._make_content_key(),
            severity="medium", severity_rank=2, rank_score=1.8,
        )

        rows = await insight_list(db_session, p.id)
        scores = [r.rank_score for r in rows]
        assert scores == sorted(scores, reverse=True)

    async def test_stale_input_flag(self, db_session):
        from app.db.repositories.portfolio_repo import portfolio_create, insight_upsert
        p = await portfolio_create(db_session, name="P")
        row = await insight_upsert(
            db_session, p.id, "cluster_concentration", "AI capex",
            self._make_content_key(),
            severity="medium",   # capped because stale_input=True
            stale_input=True,
        )
        assert row.stale_input is True

    async def test_insight_list_empty_for_unknown_portfolio(self, db_session):
        from app.db.repositories.portfolio_repo import insight_list
        rows = await insight_list(db_session, "ghost-portfolio-id")
        assert rows == []

    async def test_no_delivery_tables_modified(self, db_session):
        # Verify that insight creation touches only portfolio_insights,
        # not delivery_ledger or notifications (Slice 1 is inert).
        from app.db.repositories.portfolio_repo import (
            portfolio_create, insight_upsert
        )
        from app.db.models import DeliveryLedger, Notification
        from sqlalchemy import select, func

        p = await portfolio_create(db_session, name="P")
        await insight_upsert(
            db_session, p.id, "coverage_gap", "X", self._make_content_key()
        )

        ledger_count = await db_session.scalar(select(func.count(DeliveryLedger.id)))
        notif_count  = await db_session.scalar(select(func.count(Notification.id)))
        assert ledger_count == 0
        assert notif_count  == 0
