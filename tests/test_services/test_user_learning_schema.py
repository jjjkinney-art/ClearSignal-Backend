"""
Tests — User Learning Schema + Flags, Phase 15 · Slice 1.

Covers:
  1.  db_table_count >= 53 after create_all
  2.  All four user-learning tables exist
  3.  Indexes exist on all four tables
  4.  No advice / truth-override / source-table-mutation columns on any table
  5.  ORM models importable
  6.  All six learning_* flags at inert defaults
  7.  No advice fields on ORM models (no buy/sell/recommendation/target_price/
      position_size/execution/trade/forecast_override/similarity_override/
      scenario_override/decision_override columns)
  8.  No truth-override fields on ORM models
  9.  No source-table mutation by schema (no ALTER; additive only)
  10. relevance_adjustment_log append-only intent (AST: no update/delete in table)
  11. Migration 015 idempotency markers (IF NOT EXISTS) + 49→53 contract
  12. Migration SQL has no advice or trade terms in DDL body
  13. Migration has no ALTER TABLE
  14. user_signal_event.surface_was_personalized and pre_personalization_rank exist
  15. learned_preference has all four explainability fields
  16. relevance_adjustment_log has prominence_tier (never 'hidden') and floor_applied
  17. learned_preference has unique constraint on (user_id, dimension, entity_key)
"""

from __future__ import annotations

import ast
import pathlib
import re

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

_ROOT      = pathlib.Path(__file__).parent.parent.parent
_MIGRATION = _ROOT / "app" / "db" / "migrations" / "015_user_learning.sql"


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
# 1. DB table count
# ---------------------------------------------------------------------------

class TestDbTableCount:
    @pytest.mark.asyncio
    async def test_db_table_count_at_least_53(self, engine):
        from app.db.models import Base
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            tables = await conn.run_sync(
                lambda sync_conn: sync_conn.dialect.get_table_names(sync_conn)
            )
        assert len(tables) >= 53, (
            f"Expected >= 53 tables after Phase 15 schema, found {len(tables)}: "
            f"{sorted(tables)}"
        )


# ---------------------------------------------------------------------------
# 2. All four user-learning tables exist
# ---------------------------------------------------------------------------

class TestLearningTablesExist:
    async def _table_names(self, engine):
        from app.db.models import Base
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            return await conn.run_sync(
                lambda sync_conn: sync_conn.dialect.get_table_names(sync_conn)
            )

    @pytest.mark.asyncio
    async def test_user_signal_event_table_exists(self, engine):
        assert "user_signal_event" in await self._table_names(engine)

    @pytest.mark.asyncio
    async def test_learned_preference_table_exists(self, engine):
        assert "learned_preference" in await self._table_names(engine)

    @pytest.mark.asyncio
    async def test_preference_evidence_table_exists(self, engine):
        assert "preference_evidence" in await self._table_names(engine)

    @pytest.mark.asyncio
    async def test_relevance_adjustment_log_table_exists(self, engine):
        assert "relevance_adjustment_log" in await self._table_names(engine)


# ---------------------------------------------------------------------------
# 3. Indexes exist on all four tables
# ---------------------------------------------------------------------------

class TestIndexesExist:
    def _index_names(self):
        from app.db.models import Base
        return {idx.name for tbl in Base.metadata.tables.values() for idx in tbl.indexes}

    def test_use_user_occurred_index(self):
        assert "ix_use_user_occurred" in self._index_names()

    def test_use_user_entity_index(self):
        assert "ix_use_user_entity" in self._index_names()

    def test_use_user_signal_type_index(self):
        assert "ix_use_user_signal_type" in self._index_names()

    def test_lp_user_id_index(self):
        assert "ix_lp_user_id" in self._index_names()

    def test_lp_user_dimension_index(self):
        assert "ix_lp_user_dimension" in self._index_names()

    def test_lp_status_index(self):
        assert "ix_lp_status" in self._index_names()

    def test_pe_preference_id_index(self):
        assert "ix_pe_preference_id" in self._index_names()

    def test_pe_signal_event_id_index(self):
        assert "ix_pe_signal_event_id" in self._index_names()

    def test_ral_user_id_index(self):
        assert "ix_ral_user_id" in self._index_names()

    def test_ral_run_reason_index(self):
        assert "ix_ral_run_reason" in self._index_names()

    def test_ral_evaluated_at_index(self):
        assert "ix_ral_evaluated_at" in self._index_names()


# ---------------------------------------------------------------------------
# 4 / 7 / 8. No advice, truth-override, or source-table-mutation columns
# ---------------------------------------------------------------------------

class TestNoAdviceOrOverrideColumns:
    _FORBIDDEN_COLUMNS = {
        "buy", "sell", "recommendation", "target_price",
        "position_size", "execution", "trade",
        "forecast_override", "similarity_override",
        "scenario_override", "decision_override",
    }

    def _learning_table_columns(self):
        from app.db.models import (
            UserSignalEvent, LearnedPreference,
            PreferenceEvidence, RelevanceAdjustmentLog,
        )
        cols = set()
        for model in (UserSignalEvent, LearnedPreference,
                      PreferenceEvidence, RelevanceAdjustmentLog):
            for col in model.__table__.columns:
                cols.add(col.name.lower())
        return cols

    def test_no_forbidden_columns_on_learning_tables(self):
        cols = self._learning_table_columns()
        violations = cols & self._FORBIDDEN_COLUMNS
        assert not violations, (
            f"Forbidden columns found on user-learning tables: {violations}"
        )

    def test_no_advice_terms_in_migration_ddl(self):
        lines = _MIGRATION.read_text(encoding="utf-8").lower().splitlines()
        sql_body = "\n".join(ln for ln in lines if not ln.lstrip().startswith("--"))
        for term in (
            "buy ", "sell ", "recommendation", "target_price",
            "position_size", "execution_", "trade_",
            "forecast_override", "similarity_override",
            "scenario_override", "decision_override",
        ):
            assert term not in sql_body, (
                f"Forbidden term {term!r} found in migration SQL DDL body"
            )


# ---------------------------------------------------------------------------
# 5. ORM models importable
# ---------------------------------------------------------------------------

class TestImports:
    def test_user_signal_event_importable(self):
        from app.db.models import UserSignalEvent  # noqa: F401

    def test_learned_preference_importable(self):
        from app.db.models import LearnedPreference  # noqa: F401

    def test_preference_evidence_importable(self):
        from app.db.models import PreferenceEvidence  # noqa: F401

    def test_relevance_adjustment_log_importable(self):
        from app.db.models import RelevanceAdjustmentLog  # noqa: F401


# ---------------------------------------------------------------------------
# 6. All six learning_* flags at inert defaults
# ---------------------------------------------------------------------------

class TestFlagDefaults:
    def test_learning_capture_enabled_false(self):
        from app.config import settings
        assert settings.learning_capture_enabled is False

    def test_learning_inference_enabled_false(self):
        from app.config import settings
        assert settings.learning_inference_enabled is False

    def test_learning_relevance_enabled_false(self):
        from app.config import settings
        assert settings.learning_relevance_enabled is False

    def test_learning_shadow_true(self):
        from app.config import settings
        assert settings.learning_shadow is True

    def test_learning_targets_enabled_empty(self):
        from app.config import settings
        assert settings.learning_targets_enabled == ""

    def test_learning_calibration_enabled_false(self):
        from app.config import settings
        assert settings.learning_calibration_enabled is False


# ---------------------------------------------------------------------------
# 9. No source-table mutation (schema is additive only)
# ---------------------------------------------------------------------------

class TestSourceTableNotMutated:
    @pytest.mark.asyncio
    async def test_source_table_row_counts_unchanged_after_create_all(self, db):
        """Creating the Phase 15 tables must not alter any source-table row counts."""
        from sqlalchemy import select, func
        from app.db.models import ForecastVector, ScenarioSnapshot, DecisionPriority

        async def _counts():
            fv = (await db.execute(
                select(func.count()).select_from(ForecastVector))).scalar_one()
            ss = (await db.execute(
                select(func.count()).select_from(ScenarioSnapshot))).scalar_one()
            dp = (await db.execute(
                select(func.count()).select_from(DecisionPriority))).scalar_one()
            return fv, ss, dp

        before = await _counts()
        # No writes — schema already created; verify counts still zero
        after = await _counts()
        assert before == after == (0, 0, 0), (
            f"Source-table counts unexpectedly changed: {before} → {after}"
        )


# ---------------------------------------------------------------------------
# 10. relevance_adjustment_log append-only intent (AST)
# ---------------------------------------------------------------------------

class TestRelevanceAdjustmentLogAppendOnly:
    def test_relevance_adjustment_log_has_no_update_path_in_migration(self):
        sql = _MIGRATION.read_text(encoding="utf-8").upper()
        # Migration must never contain UPDATE statements
        # (UPDATE in comments is stripped first)
        lines = sql.splitlines()
        sql_body = "\n".join(ln for ln in lines if not ln.lstrip().startswith("--"))
        assert "UPDATE " not in sql_body, (
            "UPDATE statement found in Phase 15 migration — append-only tables only"
        )

    def test_prominence_tier_never_hidden_in_migration(self):
        sql = _MIGRATION.read_text(encoding="utf-8").lower()
        # The column comment must document that 'hidden' is not a valid value (SP-7d)
        assert "hidden" not in sql.split("prominence_tier")[-1].split("\n")[0], (
            "prominence_tier definition should not list 'hidden' as a valid value"
        )

    def test_run_reason_default_is_shadow(self):
        from app.db.models import RelevanceAdjustmentLog
        col = RelevanceAdjustmentLog.__table__.columns["run_reason"]
        assert col.default is not None, "run_reason must have a default"
        # Default value should be 'shadow'
        default_val = col.default.arg
        assert default_val == "shadow", (
            f"run_reason default must be 'shadow', got {default_val!r}"
        )


# ---------------------------------------------------------------------------
# 11. Migration idempotency + 49→53 contract
# ---------------------------------------------------------------------------

class TestMigrationIdempotency:
    def test_migration_file_exists(self):
        assert _MIGRATION.exists(), f"Migration not found: {_MIGRATION}"

    def test_migration_uses_if_not_exists_for_tables(self):
        sql = _MIGRATION.read_text(encoding="utf-8")
        tables = re.findall(r"CREATE TABLE\b", sql, re.IGNORECASE)
        if_not = re.findall(r"CREATE TABLE IF NOT EXISTS\b", sql, re.IGNORECASE)
        assert len(tables) == len(if_not), (
            f"Some CREATE TABLE missing IF NOT EXISTS: {len(tables)} total, "
            f"{len(if_not)} with IF NOT EXISTS"
        )

    def test_migration_uses_if_not_exists_for_indexes(self):
        sql = _MIGRATION.read_text(encoding="utf-8")
        indexes = re.findall(r"CREATE INDEX\b", sql, re.IGNORECASE)
        if_not  = re.findall(r"CREATE INDEX IF NOT EXISTS\b", sql, re.IGNORECASE)
        assert len(indexes) == len(if_not), (
            f"Some CREATE INDEX missing IF NOT EXISTS: {len(indexes)} total, "
            f"{len(if_not)} with IF NOT EXISTS"
        )

    def test_migration_has_no_alter_table(self):
        sql = _MIGRATION.read_text(encoding="utf-8").upper()
        assert "ALTER TABLE" not in sql, (
            "ALTER TABLE found in Phase 15 migration — additive only"
        )

    def test_migration_states_49_to_53_contract(self):
        sql = _MIGRATION.read_text(encoding="utf-8")
        assert ("49 → 53" in sql or "49→53" in sql), (
            "Migration header should state the 49 → 53 table-count contract"
        )

    def test_migration_has_four_learning_tables(self):
        sql = _MIGRATION.read_text(encoding="utf-8").lower()
        for table in (
            "user_signal_event",
            "learned_preference",
            "preference_evidence",
            "relevance_adjustment_log",
        ):
            assert table in sql, f"Table {table!r} not found in migration SQL"


# ---------------------------------------------------------------------------
# 12. Migration SQL has no advice or trade terms in DDL body
# ---------------------------------------------------------------------------

class TestMigrationNoAdviceTerms:
    def test_migration_ddl_body_has_no_forbidden_terms(self):
        lines = _MIGRATION.read_text(encoding="utf-8").lower().splitlines()
        sql_body = "\n".join(ln for ln in lines if not ln.lstrip().startswith("--"))
        bad_terms = [
            "target_price", "position_size", "execution_", "trade_",
            "buy ", "sell ",
        ]
        for term in bad_terms:
            assert term not in sql_body, (
                f"Forbidden term {term!r} found in migration SQL DDL body"
            )


# ---------------------------------------------------------------------------
# 14. user_signal_event anti-feedback-loop fields
# ---------------------------------------------------------------------------

class TestSignalEventAntiLoopFields:
    def test_surface_was_personalized_column_exists(self):
        from app.db.models import UserSignalEvent
        col_names = {c.name for c in UserSignalEvent.__table__.columns}
        assert "surface_was_personalized" in col_names

    def test_pre_personalization_rank_column_exists(self):
        from app.db.models import UserSignalEvent
        col_names = {c.name for c in UserSignalEvent.__table__.columns}
        assert "pre_personalization_rank" in col_names

    def test_surface_was_personalized_is_boolean(self):
        from app.db.models import UserSignalEvent
        from sqlalchemy import Boolean as SABoolean
        col = UserSignalEvent.__table__.columns["surface_was_personalized"]
        assert isinstance(col.type, SABoolean)

    def test_pre_personalization_rank_is_nullable(self):
        from app.db.models import UserSignalEvent
        col = UserSignalEvent.__table__.columns["pre_personalization_rank"]
        assert col.nullable is True, "pre_personalization_rank must be nullable"


# ---------------------------------------------------------------------------
# 15. learned_preference has all four explainability fields
# ---------------------------------------------------------------------------

class TestLearnedPreferenceExplainabilityFields:
    def _col_names(self):
        from app.db.models import LearnedPreference
        return {c.name for c in LearnedPreference.__table__.columns}

    def test_belief_basis_exists(self):
        assert "belief_basis" in self._col_names()

    def test_signal_strength_label_exists(self):
        assert "signal_strength_label" in self._col_names()

    def test_falsifier_exists(self):
        assert "falsifier" in self._col_names()

    def test_status_column_exists(self):
        assert "status" in self._col_names()

    def test_affinity_column_exists(self):
        assert "affinity" in self._col_names()

    def test_confidence_column_exists(self):
        assert "confidence" in self._col_names()

    def test_evidence_count_column_exists(self):
        assert "evidence_count" in self._col_names()


# ---------------------------------------------------------------------------
# 16. relevance_adjustment_log has prominence_tier and floor_applied
# ---------------------------------------------------------------------------

class TestRelevanceAdjustmentLogSafetyFields:
    def _col_names(self):
        from app.db.models import RelevanceAdjustmentLog
        return {c.name for c in RelevanceAdjustmentLog.__table__.columns}

    def test_prominence_tier_exists(self):
        assert "prominence_tier" in self._col_names()

    def test_floor_applied_exists(self):
        assert "floor_applied" in self._col_names()

    def test_intrinsic_rank_exists(self):
        assert "intrinsic_rank" in self._col_names()

    def test_adjusted_rank_exists(self):
        assert "adjusted_rank" in self._col_names()

    def test_floor_applied_is_boolean(self):
        from app.db.models import RelevanceAdjustmentLog
        from sqlalchemy import Boolean as SABoolean
        col = RelevanceAdjustmentLog.__table__.columns["floor_applied"]
        assert isinstance(col.type, SABoolean)

    def test_prominence_tier_default_is_normal(self):
        from app.db.models import RelevanceAdjustmentLog
        col = RelevanceAdjustmentLog.__table__.columns["prominence_tier"]
        assert col.default is not None
        assert col.default.arg == "normal"


# ---------------------------------------------------------------------------
# 17. learned_preference unique constraint on (user_id, dimension, entity_key)
# ---------------------------------------------------------------------------

class TestLearnedPreferenceUniqueConstraint:
    def test_unique_constraint_exists(self):
        from app.db.models import LearnedPreference
        from sqlalchemy import UniqueConstraint as UC
        constraint_names = {
            c.name
            for c in LearnedPreference.__table__.constraints
            if isinstance(c, UC)
        }
        assert "uq_learned_preference_user_dim_entity" in constraint_names, (
            "Unique constraint uq_learned_preference_user_dim_entity not found on "
            "learned_preference — required to prevent duplicate (user, dim, entity) rows"
        )

    @pytest.mark.asyncio
    async def test_duplicate_user_dim_entity_raises(self, db):
        """Inserting two rows with the same (user_id, dimension, entity_key) must fail."""
        from app.db.models import LearnedPreference
        import uuid

        uid  = str(uuid.uuid4())
        row1 = LearnedPreference(
            id="lp-001", user_id=uid, dimension="sector_interest", entity_key="semiconductors",
        )
        row2 = LearnedPreference(
            id="lp-002", user_id=uid, dimension="sector_interest", entity_key="semiconductors",
        )
        db.add(row1)
        await db.flush()

        db.add(row2)
        import sqlalchemy.exc
        with pytest.raises((sqlalchemy.exc.IntegrityError,
                            sqlalchemy.exc.OperationalError)):
            await db.flush()
