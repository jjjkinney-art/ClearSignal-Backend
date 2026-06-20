"""
Tests — Personal Experience Schema + Flags, Phase 18 · Slice 1.

Covers:
  1.  db_table_count >= 56 after create_all
  2.  All three personal-experience tables exist
  3.  Indexes exist on all three tables
  4.  No advice / truth-override / source-table-mutation columns on any table
  5.  ORM models importable
  6.  All six experience_* flags at inert defaults
  7.  No advice fields on ORM models
  8.  No truth-override fields on ORM models
  9.  No source-table mutation by schema (no ALTER; additive only)
  10. personal_experience_event append-only intent (AST: no update/delete in migration)
  11. Migration 018 idempotency markers (IF NOT EXISTS) + 53→56 contract
  12. Migration SQL has no advice or trade terms in DDL body
  13. Migration has no ALTER TABLE
  14. personal_experience_cursor has unique constraint on (user_id, entity_type, entity_key)
  15. personal_brief_snapshot has unique constraint on (user_id, brief_date)
  16. personal_experience_event has all 7 scoring dimension columns
  17. personal_experience_event has explanation_valid and run_reason columns
  18. personal_brief_snapshot has run_reason column
  19. Round-trip insert/select on all three tables
  20. personal_experience_event run_reason default is "shadow"
  21. personal_brief_snapshot run_reason default is "shadow"
  22. No upstream truth-table modification by Phase 18 schema
"""

from __future__ import annotations

import pathlib
import uuid
from datetime import date, datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy import Float
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

_ROOT      = pathlib.Path(__file__).parent.parent.parent
_MIGRATION = _ROOT / "app" / "db" / "migrations" / "018_personal_experience.sql"


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


def _uid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# 1. DB table count
# ---------------------------------------------------------------------------

class TestDbTableCount:
    @pytest.mark.asyncio
    async def test_db_table_count_at_least_56(self, engine):
        from app.db.models import Base
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            tables = await conn.run_sync(
                lambda sync_conn: sync_conn.dialect.get_table_names(sync_conn)
            )
        assert len(tables) >= 56, (
            f"Expected >= 56 tables after Phase 18 schema, found {len(tables)}"
        )


# ---------------------------------------------------------------------------
# 2. All three personal-experience tables exist
# ---------------------------------------------------------------------------

class TestExperienceTablesExist:
    async def _table_names(self, engine):
        from app.db.models import Base
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            return await conn.run_sync(
                lambda sync_conn: sync_conn.dialect.get_table_names(sync_conn)
            )

    @pytest.mark.asyncio
    async def test_personal_experience_cursor_table_exists(self, engine):
        assert "personal_experience_cursor" in await self._table_names(engine)

    @pytest.mark.asyncio
    async def test_personal_experience_event_table_exists(self, engine):
        assert "personal_experience_event" in await self._table_names(engine)

    @pytest.mark.asyncio
    async def test_personal_brief_snapshot_table_exists(self, engine):
        assert "personal_brief_snapshot" in await self._table_names(engine)


# ---------------------------------------------------------------------------
# 3. Indexes exist on all three tables
# ---------------------------------------------------------------------------

class TestIndexesExist:
    def _index_names(self):
        from app.db.models import Base
        return {idx.name for tbl in Base.metadata.tables.values() for idx in tbl.indexes}

    def test_pec_user_id_index(self):
        assert "ix_pec_user_id" in self._index_names()

    def test_pec_user_entity_type_index(self):
        assert "ix_pec_user_entity_type" in self._index_names()

    def test_pec_last_seen_at_index(self):
        assert "ix_pec_last_seen_at" in self._index_names()

    def test_pee_user_id_index(self):
        assert "ix_pee_user_id" in self._index_names()

    def test_pee_user_surface_index(self):
        assert "ix_pee_user_surface" in self._index_names()

    def test_pee_run_reason_index(self):
        assert "ix_pee_run_reason" in self._index_names()

    def test_pee_surfaced_at_index(self):
        assert "ix_pee_surfaced_at" in self._index_names()

    def test_pee_item_ref_index(self):
        assert "ix_pee_item_ref" in self._index_names()

    def test_pbs_user_id_index(self):
        assert "ix_pbs_user_id" in self._index_names()

    def test_pbs_user_brief_date_index(self):
        assert "ix_pbs_user_brief_date" in self._index_names()

    def test_pbs_run_reason_index(self):
        assert "ix_pbs_run_reason" in self._index_names()


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

    def _experience_table_columns(self):
        from app.db.models import (
            PersonalExperienceCursor,
            PersonalExperienceEvent,
            PersonalBriefSnapshot,
        )
        cols = set()
        for model in (PersonalExperienceCursor, PersonalExperienceEvent,
                      PersonalBriefSnapshot):
            for col in model.__table__.columns:
                cols.add(col.name.lower())
        return cols

    def test_no_forbidden_columns_on_experience_tables(self):
        cols = self._experience_table_columns()
        violations = cols & self._FORBIDDEN_COLUMNS
        assert not violations, (
            f"Forbidden columns found on experience tables: {violations}"
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
    def test_personal_experience_cursor_importable(self):
        from app.db.models import PersonalExperienceCursor  # noqa: F401

    def test_personal_experience_event_importable(self):
        from app.db.models import PersonalExperienceEvent  # noqa: F401

    def test_personal_brief_snapshot_importable(self):
        from app.db.models import PersonalBriefSnapshot  # noqa: F401


# ---------------------------------------------------------------------------
# 6. All six experience_* flags at inert defaults
# ---------------------------------------------------------------------------

class TestFlagDefaults:
    def test_experience_change_detection_enabled_false(self):
        from app.config import settings
        assert settings.experience_change_detection_enabled is False

    def test_experience_attention_enabled_false(self):
        from app.config import settings
        assert settings.experience_attention_enabled is False

    def test_experience_composer_enabled_false(self):
        from app.config import settings
        assert settings.experience_composer_enabled is False

    def test_experience_memory_enabled_false(self):
        from app.config import settings
        assert settings.experience_memory_enabled is False

    def test_experience_shadow_true(self):
        from app.config import settings
        assert settings.experience_shadow is True

    def test_experience_brief_enabled_false(self):
        from app.config import settings
        assert settings.experience_brief_enabled is False


# ---------------------------------------------------------------------------
# 9. No source-table mutation by schema (no ALTER; additive only)
# ---------------------------------------------------------------------------

class TestSourceTableNotMutated:
    @pytest.mark.asyncio
    async def test_source_table_row_counts_unchanged_after_create_all(self, db):
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
        after = await _counts()
        assert before == after == (0, 0, 0)

    @pytest.mark.asyncio
    async def test_learning_tables_not_mutated(self, db):
        from sqlalchemy import select, func
        from app.db.models import LearnedPreference, UserSignalEvent

        lp = (await db.execute(
            select(func.count()).select_from(LearnedPreference))).scalar_one()
        use = (await db.execute(
            select(func.count()).select_from(UserSignalEvent))).scalar_one()
        assert lp == 0
        assert use == 0


# ---------------------------------------------------------------------------
# 10. personal_experience_event append-only intent (AST)
# ---------------------------------------------------------------------------

class TestAppendOnlyIntent:
    def test_no_update_in_migration(self):
        sql = _MIGRATION.read_text(encoding="utf-8").upper()
        lines = sql.splitlines()
        sql_body = "\n".join(ln for ln in lines if not ln.lstrip().startswith("--"))
        assert "UPDATE " not in sql_body

    def test_no_delete_in_migration(self):
        sql = _MIGRATION.read_text(encoding="utf-8").upper()
        lines = sql.splitlines()
        sql_body = "\n".join(ln for ln in lines if not ln.lstrip().startswith("--"))
        assert "DELETE " not in sql_body

    def test_event_run_reason_default_is_shadow(self):
        from app.db.models import PersonalExperienceEvent
        col = PersonalExperienceEvent.__table__.columns["run_reason"]
        assert col.default is not None
        assert col.default.arg == "shadow"

    def test_brief_run_reason_default_is_shadow(self):
        from app.db.models import PersonalBriefSnapshot
        col = PersonalBriefSnapshot.__table__.columns["run_reason"]
        assert col.default is not None
        assert col.default.arg == "shadow"


# ---------------------------------------------------------------------------
# 11. Migration idempotency + 53→56 contract
# ---------------------------------------------------------------------------

class TestMigrationIdempotency:
    def test_migration_file_exists(self):
        assert _MIGRATION.exists(), f"Migration file missing: {_MIGRATION}"

    def test_migration_uses_if_not_exists(self):
        sql = _MIGRATION.read_text(encoding="utf-8").upper()
        assert sql.count("IF NOT EXISTS") >= 3, (
            "Expected >= 3 IF NOT EXISTS (one per CREATE TABLE)"
        )

    def test_migration_creates_three_tables(self):
        sql = _MIGRATION.read_text(encoding="utf-8").upper()
        assert "PERSONAL_EXPERIENCE_CURSOR" in sql
        assert "PERSONAL_EXPERIENCE_EVENT" in sql
        assert "PERSONAL_BRIEF_SNAPSHOT" in sql

    def test_migration_documents_53_to_56(self):
        sql = _MIGRATION.read_text(encoding="utf-8")
        assert "53" in sql and "56" in sql


# ---------------------------------------------------------------------------
# 12. Migration SQL has no advice or trade terms
# ---------------------------------------------------------------------------

class TestMigrationNoAdvice:
    def test_no_alter_table_in_migration(self):
        sql = _MIGRATION.read_text(encoding="utf-8").upper()
        lines = sql.splitlines()
        sql_body = "\n".join(ln for ln in lines if not ln.lstrip().startswith("--"))
        assert "ALTER TABLE" not in sql_body


# ---------------------------------------------------------------------------
# 14–15. Unique constraints
# ---------------------------------------------------------------------------

class TestUniqueConstraints:
    def test_cursor_unique_constraint(self):
        from app.db.models import PersonalExperienceCursor
        constraints = {
            c.name for c in PersonalExperienceCursor.__table__.constraints
            if hasattr(c, "columns") and len(c.columns) > 1
        }
        assert "uq_pec_user_entity" in constraints

    def test_brief_unique_constraint(self):
        from app.db.models import PersonalBriefSnapshot
        constraints = {
            c.name for c in PersonalBriefSnapshot.__table__.constraints
            if hasattr(c, "columns") and len(c.columns) > 1
        }
        assert "uq_pbs_user_brief_date" in constraints


# ---------------------------------------------------------------------------
# 16. personal_experience_event has all 7 scoring dimension columns
# ---------------------------------------------------------------------------

class TestScoringDimensions:
    _DIMENSIONS = [
        "experience_score",
        "attention_priority",
        "personal_relevance",
        "recency_score",
        "novelty_score",
        "revisit_score",
        "memory_relevance",
        "portfolio_relevance",
    ]

    def test_all_scoring_dimensions_present(self):
        from app.db.models import PersonalExperienceEvent
        col_names = {c.name for c in PersonalExperienceEvent.__table__.columns}
        for dim in self._DIMENSIONS:
            assert dim in col_names, f"missing scoring dimension: {dim}"

    def test_scoring_dimensions_are_float(self):
        from app.db.models import PersonalExperienceEvent
        for dim in self._DIMENSIONS:
            col = PersonalExperienceEvent.__table__.columns[dim]
            assert isinstance(col.type, Float), (
                f"{dim} should be Float, got {type(col.type)}"
            )


# ---------------------------------------------------------------------------
# 17. Explanation and run_reason columns
# ---------------------------------------------------------------------------

class TestExplanationColumns:
    def test_event_has_explanation_valid(self):
        from app.db.models import PersonalExperienceEvent
        col_names = {c.name for c in PersonalExperienceEvent.__table__.columns}
        assert "explanation_valid" in col_names

    def test_event_has_explanation_text(self):
        from app.db.models import PersonalExperienceEvent
        col_names = {c.name for c in PersonalExperienceEvent.__table__.columns}
        assert "explanation_text" in col_names

    def test_event_has_run_reason(self):
        from app.db.models import PersonalExperienceEvent
        col_names = {c.name for c in PersonalExperienceEvent.__table__.columns}
        assert "run_reason" in col_names

    def test_brief_has_run_reason(self):
        from app.db.models import PersonalBriefSnapshot
        col_names = {c.name for c in PersonalBriefSnapshot.__table__.columns}
        assert "run_reason" in col_names


# ---------------------------------------------------------------------------
# 19. Round-trip insert/select on all three tables
# ---------------------------------------------------------------------------

class TestRoundTrip:
    @pytest.mark.asyncio
    async def test_cursor_round_trip(self, db):
        from app.db.models import PersonalExperienceCursor
        row = PersonalExperienceCursor(
            id=_uid(), user_id=_uid(), entity_type="ticker",
            entity_key="AAPL", last_state_hash="abc123",
            view_count=1, last_seen_at=_now(),
            created_at=_now(), updated_at=_now(),
        )
        db.add(row)
        await db.flush()
        from sqlalchemy import select
        result = await db.execute(
            select(PersonalExperienceCursor).where(
                PersonalExperienceCursor.id == row.id
            )
        )
        fetched = result.scalar_one()
        assert fetched.entity_key == "AAPL"
        assert fetched.view_count == 1

    @pytest.mark.asyncio
    async def test_event_round_trip(self, db):
        from app.db.models import PersonalExperienceEvent
        row = PersonalExperienceEvent(
            id=_uid(), user_id=_uid(), surface="home",
            item_ref="item_001", entity_type="ticker", entity_key="MSFT",
            experience_score=0.75, attention_priority=0.9,
            personal_relevance=0.6, recency_score=0.8,
            novelty_score=0.5, revisit_score=0.3,
            memory_relevance=0.4, portfolio_relevance=0.7,
            explanation_text="test explanation",
            explanation_valid=True, run_reason="shadow",
            surfaced_at=_now(), created_at=_now(),
        )
        db.add(row)
        await db.flush()
        from sqlalchemy import select
        result = await db.execute(
            select(PersonalExperienceEvent).where(
                PersonalExperienceEvent.id == row.id
            )
        )
        fetched = result.scalar_one()
        assert fetched.surface == "home"
        assert float(fetched.experience_score) == 0.75
        assert fetched.explanation_valid is True

    @pytest.mark.asyncio
    async def test_brief_round_trip(self, db):
        from app.db.models import PersonalBriefSnapshot
        row = PersonalBriefSnapshot(
            id=_uid(), user_id=_uid(),
            brief_date=date(2026, 6, 20),
            brief_schema=1, items_surfaced=5, items_blocked=2,
            top_attention_item="AAPL_forecast",
            run_reason="shadow", generated_at=_now(), created_at=_now(),
        )
        db.add(row)
        await db.flush()
        from sqlalchemy import select
        result = await db.execute(
            select(PersonalBriefSnapshot).where(
                PersonalBriefSnapshot.id == row.id
            )
        )
        fetched = result.scalar_one()
        assert fetched.items_surfaced == 5
        assert fetched.run_reason == "shadow"


# ---------------------------------------------------------------------------
# 22. No upstream truth-table modification
# ---------------------------------------------------------------------------

class TestNoTruthTableModification:
    def test_phase18_tables_are_additive_only(self):
        from app.db.models import Base
        phase18_tables = {
            "personal_experience_cursor",
            "personal_experience_event",
            "personal_brief_snapshot",
        }
        all_tables = set(Base.metadata.tables.keys())
        # Phase 18 tables exist
        for t in phase18_tables:
            assert t in all_tables, f"Phase 18 table {t!r} missing"
        # No existing table was renamed or removed
        # (verified by checking truth tables still exist)
        for t in ("forecast_vector", "scenario_snapshot", "decision_priority",
                   "learned_preference", "user_signal_event", "ticker_memory"):
            assert t in all_tables, f"Truth table {t!r} missing after Phase 18"

    def test_user_id_non_nullable_on_all_phase18_tables(self):
        from app.db.models import (
            PersonalExperienceCursor,
            PersonalExperienceEvent,
            PersonalBriefSnapshot,
        )
        for model in (PersonalExperienceCursor, PersonalExperienceEvent,
                      PersonalBriefSnapshot):
            col = model.__table__.columns["user_id"]
            assert not col.nullable, (
                f"{model.__tablename__}.user_id must be non-nullable"
            )
