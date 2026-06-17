"""
Tests — Decision Intelligence Schema + Repository + Flags, Phase 13 · Slice 1.

Covers:
  1.  db_table_count >= 46 after create_all
  2.  decision_priority / decision_evidence / decision_ranking_log tables exist
  3.  Indexes exist on the three tables
  4.  No advice/size/price/trade/execution column on any of the three tables
  5.  ORM models importable; decision_repo importable
  6.  All six decision_* flags at inert defaults
  7.  decision_priority repo CRUD (upsert/get/list/delete/count)
  8.  Upsert updates an existing keyed row in place (no duplicate)
  9.  decision_evidence repo CRUD
  10. decision_ranking_log append-only (each add creates a new row)
  11. Global (user_id NULL) and user-tier rows are independent
  12. Null-session safety on every repo function
  13. Unique constraint on decision_priority key
  14. decision_ranking_log immutability (AST: no update/delete in repo)
  15. No source-table mutation by repo operations
  16. No decision behavior activated with default flags (no forbidden imports)
  17. Migration 013 idempotency markers (IF NOT EXISTS) + 43→46 contract
"""

from __future__ import annotations

import ast
import inspect
import pathlib

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

_ROOT = pathlib.Path(__file__).parent.parent.parent
_MIGRATION = _ROOT / "app" / "db" / "migrations" / "013_decision_intelligence.sql"

# ---------------------------------------------------------------------------
# Engine / session fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def engine():
    return create_async_engine("sqlite+aiosqlite:///:memory:", future=True)


@pytest_asyncio.fixture()
async def db(engine):
    from app.db.models import Base
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with AsyncSessionLocal() as session:
        yield session


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _priority_kwargs(**overrides):
    defaults = dict(
        candidate_type      = "forecast",
        entity_type         = "company",
        entity_key          = "NVDA",
        source_ref          = "forecast-uuid-1",
        decision_priority   = "high",
        decision_rank_score = 0.72,
        attention_score     = 0.65,
        urgency_score       = 0.55,
        impact_score        = 0.80,
        confidence_score    = 0.70,
        uncertainty_score   = 0.20,
        decision_reason     = "Forecast impact dominates; strengthening thesis.",
        why_now             = "Near-term horizon with an approaching catalyst.",
        deprioritizers      = ["Confidence band widens past 0.4", "Position is closed"],
        evidence_summary    = [{"rank": 1, "description": "Forecast p_positive shifted +0.12"}],
        source_versions     = {"forecast_vector": 3},
        decision_schema     = 1,
    )
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# 1. DB table count
# ---------------------------------------------------------------------------

class TestDbTableCount:
    @pytest.mark.asyncio
    async def test_db_table_count_at_least_46(self, engine):
        from app.db.models import Base
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            tables = await conn.run_sync(
                lambda sync_conn: sync_conn.dialect.get_table_names(sync_conn)
            )
        assert len(tables) >= 46, f"Expected >= 46 tables, found {len(tables)}: {sorted(tables)}"


# ---------------------------------------------------------------------------
# 2. All three decision tables exist
# ---------------------------------------------------------------------------

class TestDecisionTablesExist:
    @pytest.mark.asyncio
    async def _table_names(self, engine):
        from app.db.models import Base
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            return await conn.run_sync(
                lambda sync_conn: sync_conn.dialect.get_table_names(sync_conn)
            )

    @pytest.mark.asyncio
    async def test_decision_priority_table_exists(self, engine):
        tables = await self._table_names(engine)
        assert "decision_priority" in tables

    @pytest.mark.asyncio
    async def test_decision_evidence_table_exists(self, engine):
        tables = await self._table_names(engine)
        assert "decision_evidence" in tables

    @pytest.mark.asyncio
    async def test_decision_ranking_log_table_exists(self, engine):
        tables = await self._table_names(engine)
        assert "decision_ranking_log" in tables


# ---------------------------------------------------------------------------
# 3. Indexes exist
# ---------------------------------------------------------------------------

class TestIndexesExist:
    """ORM create_all materialises indexes only for `index=True` columns; the
    full production index set lives in 013_decision_intelligence.sql. We verify
    the ORM-created indexes against a live DB AND the full set against the SQL.
    """

    @pytest.mark.asyncio
    async def test_orm_index_on_decision_priority_user_id(self, engine):
        from app.db.models import Base
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            idx = await conn.run_sync(
                lambda sc: sc.dialect.get_indexes(sc, "decision_priority")
            )
        names = {i["name"] for i in idx}
        assert any("user_id" in n for n in names), names

    @pytest.mark.asyncio
    async def test_orm_index_on_decision_evidence_priority_id(self, engine):
        from app.db.models import Base
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            idx = await conn.run_sync(
                lambda sc: sc.dialect.get_indexes(sc, "decision_evidence")
            )
        names = {i["name"] for i in idx}
        assert any("priority_id" in n for n in names), names

    @pytest.mark.asyncio
    async def test_orm_index_on_decision_ranking_log_priority_id(self, engine):
        from app.db.models import Base
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            idx = await conn.run_sync(
                lambda sc: sc.dialect.get_indexes(sc, "decision_ranking_log")
            )
        names = {i["name"] for i in idx}
        assert any("priority_id" in n for n in names), names

    def test_migration_declares_full_index_set(self):
        src = _MIGRATION.read_text()
        expected = [
            "ix_dp_entity", "ix_dp_candidate_type", "ix_dp_priority",
            "ix_dp_user_id", "ix_dp_expires_at", "ix_dp_decision_schema",
            "ix_dp_rank_score",
            "ix_de_priority_id", "ix_de_source", "ix_de_entity", "ix_de_user_id",
            "ix_drl_priority_id", "ix_drl_entity", "ix_drl_user_id",
            "ix_drl_evaluated_at", "ix_drl_candidate_type",
        ]
        for ix in expected:
            assert f"CREATE INDEX IF NOT EXISTS {ix}" in src, f"missing index {ix} in migration"


# ---------------------------------------------------------------------------
# 4. No advice / size / price / trade / execution columns
# ---------------------------------------------------------------------------

class TestNoAdviceColumns:
    _FORBIDDEN = (
        "buy", "sell", "hold", "recommend", "recommendation",
        "target_price", "price_target", "position_size", "size",
        "trade", "execution", "order",
    )

    def _columns(self, model):
        return {c.name.lower() for c in model.__table__.columns}

    def test_decision_priority_no_advice_columns(self):
        from app.db.models import DecisionPriority
        cols = self._columns(DecisionPriority)
        for term in self._FORBIDDEN:
            assert not any(term == c or term in c.split("_") for c in cols), (
                f"decision_priority has a forbidden '{term}' column: {sorted(cols)}"
            )

    def test_decision_evidence_no_advice_columns(self):
        from app.db.models import DecisionEvidence
        cols = self._columns(DecisionEvidence)
        for term in self._FORBIDDEN:
            assert not any(term == c or term in c.split("_") for c in cols), (
                f"decision_evidence has a forbidden '{term}' column: {sorted(cols)}"
            )

    def test_decision_ranking_log_no_advice_columns(self):
        from app.db.models import DecisionRankingLog
        cols = self._columns(DecisionRankingLog)
        for term in self._FORBIDDEN:
            assert not any(term == c or term in c.split("_") for c in cols), (
                f"decision_ranking_log has a forbidden '{term}' column: {sorted(cols)}"
            )


# ---------------------------------------------------------------------------
# 5. ORM + repo imports
# ---------------------------------------------------------------------------

class TestOrmImports:
    def test_decision_priority_importable(self):
        from app.db.models import DecisionPriority
        assert DecisionPriority.__tablename__ == "decision_priority"

    def test_decision_evidence_importable(self):
        from app.db.models import DecisionEvidence
        assert DecisionEvidence.__tablename__ == "decision_evidence"

    def test_decision_ranking_log_importable(self):
        from app.db.models import DecisionRankingLog
        assert DecisionRankingLog.__tablename__ == "decision_ranking_log"

    def test_decision_repo_importable(self):
        import app.db.repositories.decision_repo as repo
        assert hasattr(repo, "upsert_decision_priority")
        assert hasattr(repo, "add_ranking_log")


# ---------------------------------------------------------------------------
# 6. Flag defaults
# ---------------------------------------------------------------------------

class TestFlagDefaults:
    def test_decision_build_enabled_default_false(self):
        from app.config import settings
        assert settings.decision_build_enabled is False

    def test_decision_scoring_enabled_default_false(self):
        from app.config import settings
        assert settings.decision_scoring_enabled is False

    def test_decision_delivery_enabled_default_false(self):
        from app.config import settings
        assert settings.decision_delivery_enabled is False

    def test_decision_shadow_default_true(self):
        from app.config import settings
        assert settings.decision_shadow is True

    def test_decision_targets_enabled_default_empty(self):
        from app.config import settings
        assert settings.decision_targets_enabled == ""

    def test_decision_calibration_enabled_default_false(self):
        from app.config import settings
        assert settings.decision_calibration_enabled is False


# ---------------------------------------------------------------------------
# 7. decision_priority repo CRUD
# ---------------------------------------------------------------------------

class TestDecisionPriorityRepo:
    @pytest.mark.asyncio
    async def test_upsert_and_get(self, db):
        from app.db.repositories import decision_repo as repo
        row = await repo.upsert_decision_priority(db, **_priority_kwargs())
        assert row is not None
        got = await repo.get_decision_priority(
            db, candidate_type="forecast", entity_type="company",
            entity_key="NVDA", source_ref="forecast-uuid-1", user_id=None,
        )
        assert got is not None
        assert got.decision_priority == "high"
        assert abs(float(got.decision_rank_score) - 0.72) < 1e-6

    @pytest.mark.asyncio
    async def test_upsert_updates_existing_row(self, db):
        from app.db.repositories import decision_repo as repo
        from app.db.models import DecisionPriority
        from sqlalchemy import select, func

        await repo.upsert_decision_priority(db, **_priority_kwargs(decision_rank_score=0.50))
        await repo.upsert_decision_priority(db, **_priority_kwargs(decision_rank_score=0.91, decision_priority="critical"))

        count = (await db.execute(select(func.count()).select_from(DecisionPriority))).scalar_one()
        assert count == 1  # updated in place, not duplicated
        got = await repo.get_decision_priority(
            db, candidate_type="forecast", entity_type="company",
            entity_key="NVDA", source_ref="forecast-uuid-1", user_id=None,
        )
        assert got.decision_priority == "critical"
        assert abs(float(got.decision_rank_score) - 0.91) < 1e-6

    @pytest.mark.asyncio
    async def test_list_filters(self, db):
        from app.db.repositories import decision_repo as repo
        await repo.upsert_decision_priority(db, **_priority_kwargs(entity_key="NVDA", decision_rank_score=0.9))
        await repo.upsert_decision_priority(db, **_priority_kwargs(entity_key="AMD", source_ref="f2", decision_rank_score=0.4))
        await repo.upsert_decision_priority(db, **_priority_kwargs(candidate_type="risk", entity_key="MSFT", source_ref="r1", decision_rank_score=0.6))

        all_rows = await repo.list_decision_priorities(db)
        assert len(all_rows) == 3
        # ordered by rank_score desc
        assert all_rows[0].decision_rank_score >= all_rows[-1].decision_rank_score

        forecasts = await repo.list_decision_priorities(db, candidate_type="forecast")
        assert len(forecasts) == 2
        nvda = await repo.list_decision_priorities(db, entity_key="NVDA")
        assert len(nvda) == 1
        risks = await repo.list_decision_priorities(db, candidate_type="risk")
        assert len(risks) == 1

    @pytest.mark.asyncio
    async def test_delete(self, db):
        from app.db.repositories import decision_repo as repo
        await repo.upsert_decision_priority(db, **_priority_kwargs())
        deleted = await repo.delete_decision_priority(
            db, candidate_type="forecast", entity_type="company",
            entity_key="NVDA", source_ref="forecast-uuid-1", user_id=None,
        )
        assert deleted is True
        got = await repo.get_decision_priority(
            db, candidate_type="forecast", entity_type="company",
            entity_key="NVDA", source_ref="forecast-uuid-1", user_id=None,
        )
        assert got is None

    @pytest.mark.asyncio
    async def test_count(self, db):
        from app.db.repositories import decision_repo as repo
        await repo.upsert_decision_priority(db, **_priority_kwargs())
        await repo.upsert_decision_priority(db, **_priority_kwargs(candidate_type="risk", source_ref="r1"))
        assert await repo.count_decision_priorities(db) == 2
        assert await repo.count_decision_priorities(db, candidate_type="risk") == 1

    @pytest.mark.asyncio
    async def test_delete_expired(self, db):
        from app.db.repositories import decision_repo as repo
        await repo.upsert_decision_priority(db, **_priority_kwargs(ttl_hours=-1))  # already expired
        await repo.upsert_decision_priority(db, **_priority_kwargs(source_ref="fresh", ttl_hours=24))
        n = await repo.delete_expired_priorities(db)
        assert n == 1
        remaining = await repo.list_decision_priorities(db)
        assert len(remaining) == 1


# ---------------------------------------------------------------------------
# 8. decision_evidence repo CRUD
# ---------------------------------------------------------------------------

class TestDecisionEvidenceRepo:
    @pytest.mark.asyncio
    async def test_add_and_list(self, db):
        from app.db.repositories import decision_repo as repo
        prio = await repo.upsert_decision_priority(db, **_priority_kwargs())
        await repo.add_decision_evidence(
            db, priority_id=prio.id, source_type="forecast_vector",
            source_id="fv-1", dimension="impact", contribution=0.12,
            weight=0.8, description="Forecast p_positive shifted +0.12",
        )
        await repo.add_decision_evidence(
            db, priority_id=prio.id, source_type="similarity_edge",
            source_id="edge-1", dimension="attention", contribution=0.05,
            weight=0.4, description="Resembles a prior inventory-correction recovery",
        )
        rows = await repo.list_decision_evidence(db, priority_id=prio.id)
        assert len(rows) == 2
        assert rows[0].weight >= rows[1].weight  # ordered by weight desc

    @pytest.mark.asyncio
    async def test_delete_evidence_for_priority(self, db):
        from app.db.repositories import decision_repo as repo
        prio = await repo.upsert_decision_priority(db, **_priority_kwargs())
        await repo.add_decision_evidence(
            db, priority_id=prio.id, source_type="forecast_vector",
            source_id="fv-1", description="x",
        )
        n = await repo.delete_evidence_for_priority(db, priority_id=prio.id)
        assert n == 1
        assert await repo.list_decision_evidence(db, priority_id=prio.id) == []

    @pytest.mark.asyncio
    async def test_count_evidence(self, db):
        from app.db.repositories import decision_repo as repo
        prio = await repo.upsert_decision_priority(db, **_priority_kwargs())
        await repo.add_decision_evidence(db, priority_id=prio.id, source_type="forecast_vector", source_id="fv-1", description="x")
        assert await repo.count_decision_evidence(db) == 1


# ---------------------------------------------------------------------------
# 9. decision_ranking_log append-only
# ---------------------------------------------------------------------------

class TestRankingLogRepo:
    @pytest.mark.asyncio
    async def test_add_and_list(self, db):
        from app.db.repositories import decision_repo as repo
        prio = await repo.upsert_decision_priority(db, **_priority_kwargs())
        await repo.add_ranking_log(
            db, priority_id=prio.id, candidate_type="forecast",
            entity_type="company", entity_key="NVDA",
            decision_priority="high", decision_rank_score=0.72,
            rank_position=1, snapshot_reason="scheduled",
        )
        logs = await repo.list_ranking_logs(db, priority_id=prio.id)
        assert len(logs) == 1
        assert logs[0].rank_position == 1

    @pytest.mark.asyncio
    async def test_each_add_creates_new_row(self, db):
        from app.db.repositories import decision_repo as repo
        prio = await repo.upsert_decision_priority(db, **_priority_kwargs())
        # Two snapshots + one outcome attribution = three rows, same priority_id
        await repo.add_ranking_log(db, priority_id=prio.id, snapshot_reason="scheduled", rank_position=1)
        await repo.add_ranking_log(db, priority_id=prio.id, snapshot_reason="rebuild", rank_position=2)
        await repo.add_ranking_log(db, priority_id=prio.id, snapshot_reason="manual_review", realized_significance="material")
        logs = await repo.list_ranking_logs(db, priority_id=prio.id)
        assert len(logs) == 3
        assert await repo.count_ranking_logs(db) == 3

    @pytest.mark.asyncio
    async def test_count_filters(self, db):
        from app.db.repositories import decision_repo as repo
        prio = await repo.upsert_decision_priority(db, **_priority_kwargs())
        await repo.add_ranking_log(db, priority_id=prio.id, candidate_type="forecast", snapshot_reason="scheduled")
        await repo.add_ranking_log(db, priority_id=prio.id, candidate_type="risk", snapshot_reason="transition")
        assert await repo.count_ranking_logs(db, candidate_type="forecast") == 1
        assert await repo.count_ranking_logs(db, snapshot_reason="transition") == 1


# ---------------------------------------------------------------------------
# 11. Global vs user-tier independence
# ---------------------------------------------------------------------------

class TestTierIndependence:
    @pytest.mark.asyncio
    async def test_global_and_user_rows_independent(self, db):
        from app.db.repositories import decision_repo as repo
        # Same candidate key, different user scope → two distinct rows
        await repo.upsert_decision_priority(db, **_priority_kwargs(user_id=None, decision_rank_score=0.50))
        await repo.upsert_decision_priority(db, **_priority_kwargs(user_id="user-abc", decision_rank_score=0.85))

        global_rows = await repo.list_decision_priorities(db, user_id_is_null=True)
        user_rows   = await repo.list_decision_priorities(db, user_id_is_null=False)
        assert len(global_rows) == 1
        assert len(user_rows) == 1
        assert global_rows[0].user_id is None
        assert user_rows[0].user_id == "user-abc"
        # tenant scoping: a different user does not see user-abc's row
        other = await repo.list_decision_priorities(db, user_id="user-xyz")
        assert other == []

    @pytest.mark.asyncio
    async def test_count_by_tier(self, db):
        from app.db.repositories import decision_repo as repo
        await repo.upsert_decision_priority(db, **_priority_kwargs(user_id=None))
        await repo.upsert_decision_priority(db, **_priority_kwargs(user_id="u1"))
        await repo.upsert_decision_priority(db, **_priority_kwargs(user_id="u2"))
        assert await repo.count_decision_priorities(db, user_id_is_null=True) == 1
        assert await repo.count_decision_priorities(db, user_id_is_null=False) == 2


# ---------------------------------------------------------------------------
# 12. Null-session safety
# ---------------------------------------------------------------------------

class TestNullSessionSafety:
    @pytest.mark.asyncio
    async def test_upsert_priority_none(self):
        from app.db.repositories import decision_repo as repo
        assert await repo.upsert_decision_priority(None, **_priority_kwargs()) is None

    @pytest.mark.asyncio
    async def test_get_priority_none(self):
        from app.db.repositories import decision_repo as repo
        assert await repo.get_decision_priority(
            None, candidate_type="forecast", entity_type="company", entity_key="X",
        ) is None

    @pytest.mark.asyncio
    async def test_list_priorities_none(self):
        from app.db.repositories import decision_repo as repo
        assert await repo.list_decision_priorities(None) == []

    @pytest.mark.asyncio
    async def test_delete_priority_none(self):
        from app.db.repositories import decision_repo as repo
        assert await repo.delete_decision_priority(
            None, candidate_type="forecast", entity_type="company", entity_key="X",
        ) is False

    @pytest.mark.asyncio
    async def test_delete_expired_none(self):
        from app.db.repositories import decision_repo as repo
        assert await repo.delete_expired_priorities(None) == 0

    @pytest.mark.asyncio
    async def test_count_priorities_none(self):
        from app.db.repositories import decision_repo as repo
        assert await repo.count_decision_priorities(None) == 0

    @pytest.mark.asyncio
    async def test_add_evidence_none(self):
        from app.db.repositories import decision_repo as repo
        assert await repo.add_decision_evidence(
            None, priority_id="p", source_type="forecast_vector", source_id="x",
        ) is None

    @pytest.mark.asyncio
    async def test_list_evidence_none(self):
        from app.db.repositories import decision_repo as repo
        assert await repo.list_decision_evidence(None) == []

    @pytest.mark.asyncio
    async def test_delete_evidence_none(self):
        from app.db.repositories import decision_repo as repo
        assert await repo.delete_evidence_for_priority(None, priority_id="p") == 0

    @pytest.mark.asyncio
    async def test_count_evidence_none(self):
        from app.db.repositories import decision_repo as repo
        assert await repo.count_decision_evidence(None) == 0

    @pytest.mark.asyncio
    async def test_add_ranking_log_none(self):
        from app.db.repositories import decision_repo as repo
        assert await repo.add_ranking_log(None, priority_id="p") is None

    @pytest.mark.asyncio
    async def test_list_ranking_logs_none(self):
        from app.db.repositories import decision_repo as repo
        assert await repo.list_ranking_logs(None) == []

    @pytest.mark.asyncio
    async def test_count_ranking_logs_none(self):
        from app.db.repositories import decision_repo as repo
        assert await repo.count_ranking_logs(None) == 0


# ---------------------------------------------------------------------------
# 13. Unique constraint
# ---------------------------------------------------------------------------

class TestUniqueConstraint:
    @pytest.mark.asyncio
    async def test_unique_key_enforced_via_upsert(self, db):
        from app.db.repositories import decision_repo as repo
        from app.db.models import DecisionPriority
        from sqlalchemy import select, func
        # Two upserts on the same key → one row
        await repo.upsert_decision_priority(db, **_priority_kwargs())
        await repo.upsert_decision_priority(db, **_priority_kwargs())
        count = (await db.execute(select(func.count()).select_from(DecisionPriority))).scalar_one()
        assert count == 1

    def test_unique_constraint_declared(self):
        from app.db.models import DecisionPriority
        uniques = [
            c for c in DecisionPriority.__table__.constraints
            if c.__class__.__name__ == "UniqueConstraint"
        ]
        assert uniques, "decision_priority must declare a UniqueConstraint"
        cols = {c.name for u in uniques for c in u.columns}
        assert {"candidate_type", "entity_type", "entity_key", "source_ref", "user_id"} <= cols


# ---------------------------------------------------------------------------
# 14. Ranking-log immutability (AST)
# ---------------------------------------------------------------------------

class TestRankingLogImmutability:
    def test_decision_repo_has_no_update_call(self):
        import app.db.repositories.decision_repo as repo_module
        source = inspect.getsource(repo_module)
        tree = ast.parse(source)
        update_calls = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Name) and func.id == "update":
                    update_calls.append("update()")
                elif isinstance(func, ast.Attribute) and func.attr == "update":
                    update_calls.append(".update()")
        assert not update_calls, (
            "decision_repo contains update() call(s) — decision_ranking_log "
            "must be append-only: " + str(update_calls)
        )

    def test_add_ranking_log_only_inserts(self):
        import app.db.repositories.decision_repo as repo_module
        source = inspect.getsource(repo_module.add_ranking_log)
        tree = ast.parse(source)
        call_names = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Name):
                    call_names.append(func.id)
                elif isinstance(func, ast.Attribute):
                    call_names.append(func.attr)
        assert "update" not in call_names
        assert "delete" not in call_names
        assert "add" in call_names

    def test_no_delete_call_on_ranking_log_path(self):
        """add_ranking_log / list_ranking_logs / count_ranking_logs never delete."""
        import app.db.repositories.decision_repo as repo_module
        for fn_name in ("add_ranking_log", "list_ranking_logs", "count_ranking_logs"):
            fn = getattr(repo_module, fn_name)
            src = inspect.getsource(fn)
            assert "session.delete" not in src, f"{fn_name} must not delete ranking-log rows"


# ---------------------------------------------------------------------------
# 15. No source-table mutation
# ---------------------------------------------------------------------------

class TestNoSourceTableMutation:
    @pytest.mark.asyncio
    async def test_repo_does_not_touch_forecast_vector(self, db):
        from app.db.repositories import decision_repo as repo
        from app.db.models import ForecastVector
        from sqlalchemy import select, func

        before = (await db.execute(select(func.count()).select_from(ForecastVector))).scalar_one()
        await repo.upsert_decision_priority(db, **_priority_kwargs())
        prio = await repo.get_decision_priority(
            db, candidate_type="forecast", entity_type="company",
            entity_key="NVDA", source_ref="forecast-uuid-1", user_id=None,
        )
        await repo.add_decision_evidence(db, priority_id=prio.id, source_type="forecast_vector", source_id="x", description="y")
        await repo.add_ranking_log(db, priority_id=prio.id)
        after = (await db.execute(select(func.count()).select_from(ForecastVector))).scalar_one()
        assert before == after == 0

    def test_repo_imports_no_source_writer(self):
        import app.db.repositories.decision_repo as repo_module
        source = inspect.getsource(repo_module)
        tree = ast.parse(source)
        imported = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.extend(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imported.append(node.module)
                imported.extend(a.name for a in node.names)
        forbidden = [
            "conviction_engine", "recommendation", "notification_service",
            "order", "execution", "stance_engine", "forecast_delivery",
        ]
        offenders = [n for n in imported if any(t in n.lower() for t in forbidden)]
        assert not offenders, f"decision_repo has forbidden imports: {offenders}"


# ---------------------------------------------------------------------------
# 16. No behavior activated with default flags
# ---------------------------------------------------------------------------

class TestNoDecisionBehaviorActivated:
    def test_all_decision_flags_inert(self):
        from app.config import settings
        assert settings.decision_build_enabled is False
        assert settings.decision_scoring_enabled is False
        assert settings.decision_delivery_enabled is False
        assert settings.decision_shadow is True
        assert settings.decision_targets_enabled == ""
        assert settings.decision_calibration_enabled is False


# ---------------------------------------------------------------------------
# 17. Migration idempotency markers + table-count contract
# ---------------------------------------------------------------------------

class TestMigrationFile:
    def test_migration_exists(self):
        assert _MIGRATION.exists(), "013_decision_intelligence.sql is missing"

    def test_migration_uses_if_not_exists(self):
        src = _MIGRATION.read_text()
        # Every CREATE TABLE / CREATE INDEX must be IF NOT EXISTS (idempotent)
        import re
        creates = re.findall(r"CREATE\s+(TABLE|INDEX)\s+(IF NOT EXISTS)?", src, re.IGNORECASE)
        assert creates, "no CREATE statements found"
        for kind, guard in creates:
            assert guard, f"CREATE {kind} without IF NOT EXISTS — migration not idempotent"

    def test_migration_no_alter_on_source_tables(self):
        src = _MIGRATION.read_text().upper()
        assert "ALTER TABLE" not in src, "migration must not ALTER any existing table"

    def test_migration_declares_three_tables(self):
        src = _MIGRATION.read_text()
        for t in ("decision_priority", "decision_evidence", "decision_ranking_log"):
            assert f"CREATE TABLE IF NOT EXISTS {t}" in src

    def test_migration_documents_table_count_contract(self):
        src = _MIGRATION.read_text()
        assert "43" in src and "46" in src, "migration should document the 43 → 46 contract"
