"""
Tests — Scenario Engine Schema + Repository + Flags, Phase 14 · Slice 1.

Covers:
  1.  db_table_count >= 49 after create_all
  2.  scenario_snapshot / scenario_evidence / scenario_run_log tables exist
  3.  Indexes exist on the three tables
  4.  No advice/size/price/trade/execution/prediction column on any table
  5.  ORM models importable; scenario_repo importable
  6.  All six scenario_* flags at inert defaults
  7.  scenario_snapshot repo CRUD (upsert/get/list/delete/count)
  8.  Upsert updates an existing keyed row in place (no duplicate)
  9.  scenario_evidence repo CRUD
  10. scenario_run_log append-only (each add_run_log creates a new row)
  11. Global (user_id NULL) and user-tier rows are independent
  12. Null-session safety on every repo function
  13. Unique constraint on scenario_snapshot key
  14. scenario_run_log immutability (AST: no update/delete in repo)
  15. No source-table mutation by repo operations
  16. No scenario behavior activated with default flags (no forbidden imports)
  17. Migration 014 idempotency markers (IF NOT EXISTS) + 46→49 contract
"""

from __future__ import annotations

import ast
import inspect
import pathlib

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

_ROOT      = pathlib.Path(__file__).parent.parent.parent
_MIGRATION = _ROOT / "app" / "db" / "migrations" / "014_scenario_engine.sql"

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

def _snapshot_kwargs(**overrides):
    defaults = dict(
        scenario_type      = "company",
        entity_type        = "company",
        entity_key         = "NVDA",
        scenario_key       = "thesis_break_q3",
        condition          = "If NVDA misses Q3 guidance by >10%",
        transmission_path  = [
            {"step": 1, "cause": "Guidance miss", "effect": "Sentiment revision"},
            {"step": 2, "cause": "Sentiment revision", "effect": "Re-rating of adjacent names"},
        ],
        scenario_impact    = "moderate_negative",
        plausibility_band  = "plausible",
        confidence_score   = 0.68,
        uncertainty_score  = 0.30,
        affected_entities  = [{"entity_key": "AMD", "pathway": "sector_peer"}],
        affected_forecasts = [{"forecast_id": "fc-001"}],
        affected_decisions = [{"priority_id": "dp-001"}],
        what_changed       = "Q3 guidance assumption shifts downward.",
        why_it_matters     = "NVDA drives 40% of AI-hardware thesis across the portfolio.",
        evidence_summary   = [{"source": "forecast_vector", "ref": "fc-001"}],
        invalidators       = ["Guidance beats consensus by >5%", "Macro re-accelerates"],
        source_versions    = {"forecast_vector": 5},
        scenario_schema    = 1,
    )
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# 1. DB table count
# ---------------------------------------------------------------------------

class TestDbTableCount:
    @pytest.mark.asyncio
    async def test_db_table_count_at_least_49(self, engine):
        from app.db.models import Base
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            tables = await conn.run_sync(
                lambda sync_conn: sync_conn.dialect.get_table_names(sync_conn)
            )
        assert len(tables) >= 49, (
            f"Expected >= 49 tables, found {len(tables)}: {sorted(tables)}"
        )


# ---------------------------------------------------------------------------
# 2. All three scenario tables exist
# ---------------------------------------------------------------------------

class TestScenarioTablesExist:
    async def _table_names(self, engine):
        from app.db.models import Base
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            return await conn.run_sync(
                lambda sync_conn: sync_conn.dialect.get_table_names(sync_conn)
            )

    @pytest.mark.asyncio
    async def test_scenario_snapshot_table_exists(self, engine):
        tables = await self._table_names(engine)
        assert "scenario_snapshot" in tables

    @pytest.mark.asyncio
    async def test_scenario_evidence_table_exists(self, engine):
        tables = await self._table_names(engine)
        assert "scenario_evidence" in tables

    @pytest.mark.asyncio
    async def test_scenario_run_log_table_exists(self, engine):
        tables = await self._table_names(engine)
        assert "scenario_run_log" in tables


# ---------------------------------------------------------------------------
# 3. Indexes exist on the three tables
# ---------------------------------------------------------------------------

class TestIndexesExist:
    def _index_names(self):
        from app.db.models import Base
        return {idx.name for tbl in Base.metadata.tables.values() for idx in tbl.indexes}

    def test_snapshot_entity_index(self):
        assert "ix_ss_entity" in self._index_names()

    def test_snapshot_scenario_type_index(self):
        assert "ix_ss_scenario_type" in self._index_names()

    def test_snapshot_user_id_index(self):
        assert "ix_ss_user_id" in self._index_names()

    def test_snapshot_expires_at_index(self):
        assert "ix_ss_expires_at" in self._index_names()

    def test_evidence_scenario_id_index(self):
        assert "ix_se_scenario_id" in self._index_names()

    def test_run_log_entity_index(self):
        assert "ix_srl_entity" in self._index_names()

    def test_run_log_evaluated_at_index(self):
        assert "ix_srl_evaluated_at" in self._index_names()


# ---------------------------------------------------------------------------
# 4. No advice/size/price/trade/execution/prediction columns
# ---------------------------------------------------------------------------

class TestNoAdviceColumns:
    _FORBIDDEN = {
        "buy", "sell", "hold", "recommendation", "target_price",
        "position_size", "execution", "trade", "predicted_return",
        "price_target",
    }

    def _scenario_columns(self):
        from app.db.models import ScenarioSnapshot, ScenarioEvidence, ScenarioRunLog
        cols = set()
        for model in (ScenarioSnapshot, ScenarioEvidence, ScenarioRunLog):
            for col in model.__table__.columns:
                cols.add(col.name.lower())
        return cols

    def test_no_forbidden_columns_on_scenario_tables(self):
        cols = self._scenario_columns()
        violations = cols & self._FORBIDDEN
        assert not violations, f"Forbidden columns found on scenario tables: {violations}"

    def test_no_buy_sell_in_migration_sql(self):
        # Strip comment lines before checking — safety notes in comments name the
        # very terms they forbid (e.g. "NO buy / sell / target_price").
        lines = _MIGRATION.read_text(encoding="utf-8").lower().splitlines()
        sql_body = "\n".join(ln for ln in lines if not ln.lstrip().startswith("--"))
        for term in ("buy", "sell", "recommendation", "target_price", "position_size",
                     "execution_", "trade_"):
            assert term not in sql_body, (
                f"Forbidden term {term!r} found in migration SQL DDL body"
            )


# ---------------------------------------------------------------------------
# 5. ORM models and repo importable
# ---------------------------------------------------------------------------

class TestImports:
    def test_scenario_snapshot_importable(self):
        from app.db.models import ScenarioSnapshot  # noqa: F401

    def test_scenario_evidence_importable(self):
        from app.db.models import ScenarioEvidence  # noqa: F401

    def test_scenario_run_log_importable(self):
        from app.db.models import ScenarioRunLog  # noqa: F401

    def test_scenario_repo_importable(self):
        import app.db.repositories.scenario_repo  # noqa: F401


# ---------------------------------------------------------------------------
# 6. All six scenario_* flags at inert defaults
# ---------------------------------------------------------------------------

class TestFlagDefaults:
    def test_scenario_build_enabled_false(self):
        from app.config import settings
        assert settings.scenario_build_enabled is False

    def test_scenario_scoring_enabled_false(self):
        from app.config import settings
        assert settings.scenario_scoring_enabled is False

    def test_scenario_delivery_enabled_false(self):
        from app.config import settings
        assert settings.scenario_delivery_enabled is False

    def test_scenario_shadow_true(self):
        from app.config import settings
        assert settings.scenario_shadow is True

    def test_scenario_targets_enabled_empty(self):
        from app.config import settings
        assert settings.scenario_targets_enabled == ""

    def test_scenario_calibration_enabled_false(self):
        from app.config import settings
        assert settings.scenario_calibration_enabled is False


# ---------------------------------------------------------------------------
# 7. scenario_snapshot repo CRUD
# ---------------------------------------------------------------------------

class TestSnapshotCRUD:
    @pytest.mark.asyncio
    async def test_upsert_creates_row(self, db):
        from app.db.repositories.scenario_repo import upsert_scenario_snapshot
        row = await upsert_scenario_snapshot(db, **_snapshot_kwargs())
        await db.commit()
        assert row is not None
        assert row.entity_key == "NVDA"
        assert row.scenario_type == "company"

    @pytest.mark.asyncio
    async def test_get_returns_row(self, db):
        from app.db.repositories.scenario_repo import (
            upsert_scenario_snapshot, get_scenario_snapshot,
        )
        await upsert_scenario_snapshot(db, **_snapshot_kwargs())
        await db.commit()
        fetched = await get_scenario_snapshot(
            db,
            scenario_type = "company",
            entity_type   = "company",
            entity_key    = "NVDA",
            scenario_key  = "thesis_break_q3",
        )
        assert fetched is not None
        assert fetched.scenario_impact == "moderate_negative"

    @pytest.mark.asyncio
    async def test_list_returns_rows(self, db):
        from app.db.repositories.scenario_repo import (
            upsert_scenario_snapshot, list_scenario_snapshots,
        )
        await upsert_scenario_snapshot(db, **_snapshot_kwargs(entity_key="NVDA", scenario_key="a"))
        await upsert_scenario_snapshot(db, **_snapshot_kwargs(entity_key="AAPL", scenario_key="b"))
        await db.commit()
        rows = await list_scenario_snapshots(db)
        assert len(rows) >= 2

    @pytest.mark.asyncio
    async def test_delete_removes_row(self, db):
        from app.db.repositories.scenario_repo import (
            upsert_scenario_snapshot, delete_scenario_snapshot, get_scenario_snapshot,
        )
        await upsert_scenario_snapshot(db, **_snapshot_kwargs())
        await db.commit()
        deleted = await delete_scenario_snapshot(
            db,
            scenario_type = "company",
            entity_type   = "company",
            entity_key    = "NVDA",
            scenario_key  = "thesis_break_q3",
        )
        await db.commit()
        assert deleted is True
        gone = await get_scenario_snapshot(
            db,
            scenario_type = "company",
            entity_type   = "company",
            entity_key    = "NVDA",
            scenario_key  = "thesis_break_q3",
        )
        assert gone is None

    @pytest.mark.asyncio
    async def test_count_returns_correct_number(self, db):
        from app.db.repositories.scenario_repo import (
            upsert_scenario_snapshot, count_scenario_snapshots,
        )
        await upsert_scenario_snapshot(db, **_snapshot_kwargs(entity_key="NVDA", scenario_key="a"))
        await upsert_scenario_snapshot(db, **_snapshot_kwargs(entity_key="AAPL", scenario_key="b"))
        await db.commit()
        n = await count_scenario_snapshots(db)
        assert n >= 2


# ---------------------------------------------------------------------------
# 8. Upsert updates existing row in place (no duplicate)
# ---------------------------------------------------------------------------

class TestUpsertIdempotency:
    @pytest.mark.asyncio
    async def test_upsert_updates_in_place(self, db):
        from app.db.repositories.scenario_repo import (
            upsert_scenario_snapshot, count_scenario_snapshots,
        )
        await upsert_scenario_snapshot(
            db, **_snapshot_kwargs(scenario_impact="moderate_negative"),
        )
        await db.commit()
        await upsert_scenario_snapshot(
            db, **_snapshot_kwargs(scenario_impact="significant_negative"),
        )
        await db.commit()
        # Same unique key → should still be one row
        n = await count_scenario_snapshots(db, entity_type="company")
        assert n == 1

    @pytest.mark.asyncio
    async def test_upsert_field_updated(self, db):
        from app.db.repositories.scenario_repo import (
            upsert_scenario_snapshot, get_scenario_snapshot,
        )
        await upsert_scenario_snapshot(
            db, **_snapshot_kwargs(scenario_impact="moderate_negative"),
        )
        await db.commit()
        await upsert_scenario_snapshot(
            db, **_snapshot_kwargs(scenario_impact="significant_negative"),
        )
        await db.commit()
        row = await get_scenario_snapshot(
            db,
            scenario_type = "company",
            entity_type   = "company",
            entity_key    = "NVDA",
            scenario_key  = "thesis_break_q3",
        )
        assert row.scenario_impact == "significant_negative"


# ---------------------------------------------------------------------------
# 9. scenario_evidence repo CRUD
# ---------------------------------------------------------------------------

class TestEvidenceCRUD:
    @pytest.mark.asyncio
    async def test_add_evidence_creates_row(self, db):
        from app.db.repositories.scenario_repo import (
            upsert_scenario_snapshot, add_scenario_evidence,
        )
        snap = await upsert_scenario_snapshot(db, **_snapshot_kwargs())
        await db.commit()
        ev = await add_scenario_evidence(
            db,
            scenario_id    = snap.id,
            source_phase   = "forecast",
            source_ref     = "fc-001",
            captured_value = {"p_positive": 0.62},
            entity_type    = "company",
            entity_key     = "NVDA",
        )
        await db.commit()
        assert ev is not None
        assert ev.source_phase == "forecast"

    @pytest.mark.asyncio
    async def test_list_evidence_by_scenario_id(self, db):
        from app.db.repositories.scenario_repo import (
            upsert_scenario_snapshot, add_scenario_evidence, list_scenario_evidence,
        )
        snap = await upsert_scenario_snapshot(db, **_snapshot_kwargs())
        await db.commit()
        await add_scenario_evidence(db, scenario_id=snap.id, source_phase="forecast",
                                    source_ref="fc-001")
        await add_scenario_evidence(db, scenario_id=snap.id, source_phase="decision",
                                    source_ref="dp-001")
        await db.commit()
        rows = await list_scenario_evidence(db, scenario_id=snap.id)
        assert len(rows) == 2

    @pytest.mark.asyncio
    async def test_delete_evidence_for_snapshot(self, db):
        from app.db.repositories.scenario_repo import (
            upsert_scenario_snapshot, add_scenario_evidence,
            delete_evidence_for_snapshot, list_scenario_evidence,
        )
        snap = await upsert_scenario_snapshot(db, **_snapshot_kwargs())
        await db.commit()
        await add_scenario_evidence(db, scenario_id=snap.id, source_phase="forecast",
                                    source_ref="fc-001")
        await db.commit()
        deleted = await delete_evidence_for_snapshot(db, scenario_id=snap.id)
        await db.commit()
        assert deleted >= 1
        rows = await list_scenario_evidence(db, scenario_id=snap.id)
        assert rows == []

    @pytest.mark.asyncio
    async def test_count_evidence(self, db):
        from app.db.repositories.scenario_repo import (
            upsert_scenario_snapshot, add_scenario_evidence, count_scenario_evidence,
        )
        snap = await upsert_scenario_snapshot(db, **_snapshot_kwargs())
        await db.commit()
        await add_scenario_evidence(db, scenario_id=snap.id, source_phase="forecast",
                                    source_ref="fc-001")
        await add_scenario_evidence(db, scenario_id=snap.id, source_phase="similarity",
                                    source_ref="se-002")
        await db.commit()
        n = await count_scenario_evidence(db)
        assert n >= 2


# ---------------------------------------------------------------------------
# 10. scenario_run_log append-only
# ---------------------------------------------------------------------------

class TestRunLogAppendOnly:
    @pytest.mark.asyncio
    async def test_each_add_run_log_creates_new_row(self, db):
        from app.db.repositories.scenario_repo import add_run_log, count_run_logs
        await add_run_log(db, scenario_type="company", entity_key="NVDA",
                          run_reason="assembly")
        await add_run_log(db, scenario_type="company", entity_key="NVDA",
                          run_reason="shadow")
        await db.commit()
        n = await count_run_logs(db, entity_type="")
        # Both rows must exist — no dedup/merge
        n2 = await count_run_logs(db)
        assert n2 >= 2

    @pytest.mark.asyncio
    async def test_list_run_logs_by_run_reason(self, db):
        from app.db.repositories.scenario_repo import add_run_log, list_run_logs
        await add_run_log(db, run_reason="assembly", entity_key="NVDA")
        await add_run_log(db, run_reason="shadow",   entity_key="NVDA")
        await add_run_log(db, run_reason="shadow",   entity_key="AAPL")
        await db.commit()
        shadow_rows = await list_run_logs(db, run_reason="shadow")
        assert len(shadow_rows) >= 2
        assembly_rows = await list_run_logs(db, run_reason="assembly")
        assert len(assembly_rows) >= 1


# ---------------------------------------------------------------------------
# 11. Global tier and user-tier rows are independent
# ---------------------------------------------------------------------------

class TestTierIsolation:
    @pytest.mark.asyncio
    async def test_global_and_user_tier_coexist(self, db):
        from app.db.repositories.scenario_repo import (
            upsert_scenario_snapshot, count_scenario_snapshots,
        )
        uid = "user-abc"
        await upsert_scenario_snapshot(db, **_snapshot_kwargs(user_id=None))
        await upsert_scenario_snapshot(db, **_snapshot_kwargs(user_id=uid))
        await db.commit()
        total   = await count_scenario_snapshots(db)
        global_ = await count_scenario_snapshots(db, user_id_is_null=True)
        user_   = await count_scenario_snapshots(db, user_id_is_null=False)
        assert total   >= 2
        assert global_ >= 1
        assert user_   >= 1

    @pytest.mark.asyncio
    async def test_user_tier_not_visible_to_other_user(self, db):
        from app.db.repositories.scenario_repo import (
            upsert_scenario_snapshot, list_scenario_snapshots,
        )
        await upsert_scenario_snapshot(db, **_snapshot_kwargs(user_id="user-A"))
        await db.commit()
        rows_for_B = await list_scenario_snapshots(db, user_id="user-B")
        assert rows_for_B == []


# ---------------------------------------------------------------------------
# 12. Null-session safety
# ---------------------------------------------------------------------------

class TestNullSession:
    @pytest.mark.asyncio
    async def test_upsert_returns_none_on_null_session(self):
        from app.db.repositories.scenario_repo import upsert_scenario_snapshot
        assert await upsert_scenario_snapshot(None, **_snapshot_kwargs()) is None

    @pytest.mark.asyncio
    async def test_get_returns_none_on_null_session(self):
        from app.db.repositories.scenario_repo import get_scenario_snapshot
        assert await get_scenario_snapshot(
            None, scenario_type="company", entity_type="company",
            entity_key="NVDA",
        ) is None

    @pytest.mark.asyncio
    async def test_list_returns_empty_on_null_session(self):
        from app.db.repositories.scenario_repo import list_scenario_snapshots
        assert await list_scenario_snapshots(None) == []

    @pytest.mark.asyncio
    async def test_delete_returns_false_on_null_session(self):
        from app.db.repositories.scenario_repo import delete_scenario_snapshot
        assert await delete_scenario_snapshot(
            None, scenario_type="company", entity_type="company",
            entity_key="NVDA",
        ) is False

    @pytest.mark.asyncio
    async def test_count_returns_zero_on_null_session(self):
        from app.db.repositories.scenario_repo import count_scenario_snapshots
        assert await count_scenario_snapshots(None) == 0

    @pytest.mark.asyncio
    async def test_add_evidence_returns_none_on_null_session(self):
        from app.db.repositories.scenario_repo import add_scenario_evidence
        assert await add_scenario_evidence(
            None, scenario_id="x", source_phase="forecast", source_ref="fc-1",
        ) is None

    @pytest.mark.asyncio
    async def test_list_evidence_returns_empty_on_null_session(self):
        from app.db.repositories.scenario_repo import list_scenario_evidence
        assert await list_scenario_evidence(None) == []

    @pytest.mark.asyncio
    async def test_add_run_log_returns_none_on_null_session(self):
        from app.db.repositories.scenario_repo import add_run_log
        assert await add_run_log(None) is None

    @pytest.mark.asyncio
    async def test_list_run_logs_returns_empty_on_null_session(self):
        from app.db.repositories.scenario_repo import list_run_logs
        assert await list_run_logs(None) == []

    @pytest.mark.asyncio
    async def test_count_run_logs_returns_zero_on_null_session(self):
        from app.db.repositories.scenario_repo import count_run_logs
        assert await count_run_logs(None) == 0


# ---------------------------------------------------------------------------
# 13. Unique constraint on scenario_snapshot key
# ---------------------------------------------------------------------------

class TestUniqueConstraint:
    @pytest.mark.asyncio
    async def test_duplicate_key_raises_or_updates(self, db):
        """Inserting the same unique key twice must either raise (raw SQL) or
        update via upsert — never create two rows with the same key."""
        from app.db.repositories.scenario_repo import (
            upsert_scenario_snapshot, count_scenario_snapshots,
        )
        await upsert_scenario_snapshot(db, **_snapshot_kwargs())
        await db.commit()
        await upsert_scenario_snapshot(db, **_snapshot_kwargs())
        await db.commit()
        n = await count_scenario_snapshots(db)
        assert n == 1, f"Expected 1 row after two upserts on same key, found {n}"


# ---------------------------------------------------------------------------
# 14. scenario_run_log immutability (AST)
# ---------------------------------------------------------------------------

class TestRunLogImmutabilityAST:
    def test_add_run_log_has_no_update_or_delete(self):
        import app.db.repositories.scenario_repo as mod
        src  = inspect.getsource(mod)
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)):
                if node.name == "add_run_log":
                    fn_src = ast.unparse(node)
                    assert "session.merge(" not in fn_src,  "merge() found in add_run_log"
                    assert "session.delete(" not in fn_src, "delete() found in add_run_log"
                    # No UPDATE statement pattern
                    for child in ast.walk(node):
                        if isinstance(child, ast.Attribute) and child.attr == "update":
                            stmt_src = ast.unparse(child)
                            assert False, f"update() found in add_run_log: {stmt_src}"
                    return
        pytest.fail("add_run_log not found in scenario_repo")

    def test_no_delete_on_run_log_model_in_repo(self):
        """scenario_run_log rows must never be deleted anywhere in the repo."""
        import app.db.repositories.scenario_repo as mod
        src = inspect.getsource(mod)
        # The only delete operations should target scenario_snapshot and
        # scenario_evidence — never ScenarioRunLog.
        assert "ScenarioRunLog" not in src.split("delete(")[-1].split(")")[0] \
            if "delete(" in src else True, \
            "delete() call on ScenarioRunLog found in scenario_repo"


# ---------------------------------------------------------------------------
# 15. No source-table mutation
# ---------------------------------------------------------------------------

class TestNoSourceTableMutation:
    @pytest.mark.asyncio
    async def test_repo_operations_do_not_mutate_source_tables(self, db):
        from sqlalchemy import select, func
        from app.db.models import (
            ForecastVector, DecisionPriority, WatchedTicker,
        )
        from app.db.repositories.scenario_repo import (
            upsert_scenario_snapshot, add_scenario_evidence, add_run_log,
        )

        async def _counts():
            fc = (await db.execute(select(func.count()).select_from(ForecastVector))).scalar_one()
            dp = (await db.execute(select(func.count()).select_from(DecisionPriority))).scalar_one()
            wt = (await db.execute(select(func.count()).select_from(WatchedTicker))).scalar_one()
            return fc, dp, wt

        before = await _counts()

        snap = await upsert_scenario_snapshot(db, **_snapshot_kwargs())
        await db.commit()
        await add_scenario_evidence(db, scenario_id=snap.id, source_phase="forecast",
                                    source_ref="fc-001")
        await add_run_log(db, scenario_id=snap.id, run_reason="assembly")
        await db.commit()

        after = await _counts()
        assert before == after, (
            f"Source-table row counts changed after scenario repo operations: "
            f"{before} → {after}"
        )


# ---------------------------------------------------------------------------
# 16. No scenario behavior with default flags
# ---------------------------------------------------------------------------

class TestNoActiveBehaviorByDefault:
    def test_scenario_repo_has_no_forbidden_imports(self):
        """scenario_repo must not import conviction/order/execution/stance modules."""
        import app.db.repositories.scenario_repo as mod
        src  = inspect.getsource(mod)
        tree = ast.parse(src)
        imported: list = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                imported.append(node.module)
                imported.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.Import):
                imported.extend(alias.name for alias in node.names)
        forbidden = [
            "conviction_engine", "conviction_modeler", "recommendation",
            "notification_service", "stance_engine", "order_engine",
            "execution_engine",
        ]
        violations = [n for n in imported if any(f in n.lower() for f in forbidden)]
        assert not violations, f"Forbidden imports in scenario_repo: {violations}"

    def test_scenario_repo_has_no_source_table_imports(self):
        """scenario_repo must not write to or import forecast/decision write paths."""
        import app.db.repositories.scenario_repo as mod
        src  = inspect.getsource(mod)
        write_paths = ["forecast_repo", "decision_repo", "forecast_builder"]
        tree = ast.parse(src)
        imported = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                imported.append(node.module)
            elif isinstance(node, ast.Import):
                imported.extend(alias.name for alias in node.names)
        violations = [n for n in imported if any(wp in n.lower() for wp in write_paths)]
        assert not violations, f"Write-path imports in scenario_repo: {violations}"


# ---------------------------------------------------------------------------
# 17. Migration idempotency + 46→49 contract
# ---------------------------------------------------------------------------

class TestMigrationIdempotency:
    def test_migration_file_exists(self):
        assert _MIGRATION.exists(), f"Migration not found: {_MIGRATION}"

    def test_migration_uses_if_not_exists(self):
        sql = _MIGRATION.read_text(encoding="utf-8")
        # Every CREATE TABLE must be IF NOT EXISTS
        import re
        tables = re.findall(r"CREATE TABLE\b", sql, re.IGNORECASE)
        if_not = re.findall(r"CREATE TABLE IF NOT EXISTS\b", sql, re.IGNORECASE)
        assert len(tables) == len(if_not), (
            f"Some CREATE TABLE missing IF NOT EXISTS: found {len(tables)} "
            f"CREATE TABLE but only {len(if_not)} with IF NOT EXISTS"
        )

    def test_migration_uses_create_index_if_not_exists(self):
        sql = _MIGRATION.read_text(encoding="utf-8")
        import re
        indexes = re.findall(r"CREATE INDEX\b", sql, re.IGNORECASE)
        if_not  = re.findall(r"CREATE INDEX IF NOT EXISTS\b", sql, re.IGNORECASE)
        assert len(indexes) == len(if_not), (
            f"Some CREATE INDEX missing IF NOT EXISTS: {len(indexes)} vs {len(if_not)}"
        )

    def test_migration_has_no_alter_table(self):
        sql = _MIGRATION.read_text(encoding="utf-8").upper()
        assert "ALTER TABLE" not in sql, "ALTER TABLE found in migration — additive only"

    def test_migration_states_46_to_49_contract(self):
        sql = _MIGRATION.read_text(encoding="utf-8")
        assert "46 → 49" in sql or "46→49" in sql, (
            "Migration header should state the 46 → 49 table-count contract"
        )

    def test_migration_has_three_scenario_tables(self):
        sql = _MIGRATION.read_text(encoding="utf-8").lower()
        for table in ("scenario_snapshot", "scenario_evidence", "scenario_run_log"):
            assert table in sql, f"Table {table!r} not found in migration SQL"

    def test_migration_has_no_advice_or_trade_terms(self):
        lines = _MIGRATION.read_text(encoding="utf-8").lower().splitlines()
        sql_body = "\n".join(ln for ln in lines if not ln.lstrip().startswith("--"))
        bad_terms = [
            "target_price", "position_size", "execution_", "trade_",
            "recommendation", "buy ", "sell ",
        ]
        for term in bad_terms:
            assert term not in sql_body, (
                f"Forbidden term {term!r} found in migration SQL DDL body"
            )
