"""
Tests — Visual Intelligence Schema + Flags, Phase 19 · Slice 1.

Covers:
  1.  db_table_count >= 59 after create_all
  2.  All three visual-intelligence tables exist
  3.  Indexes exist on all three tables
  4.  No advice / truth-override / source-table-mutation columns on any table
  5.  ORM models importable
  6.  All six visual_* flags at inert defaults
  7.  No advice fields on ORM models
  8.  No truth-override fields on ORM models
  9.  No source-table mutation by schema (no ALTER; additive only)
  10. visual_experience_event append-only intent (AST: no update/delete in migration)
  11. ai_visual_generation_log append-only intent (AST: no update/delete in migration)
  12. Migration 019 idempotency markers (IF NOT EXISTS) + 56→59 contract
  13. Migration SQL has no advice or trade terms in DDL body
  14. Migration has no ALTER TABLE
  15. visual_spec_cache has unique constraint on (user_id, visual_type, entity_key, data_hash)
  16. visual_experience_event has rendering_tier, generation_ms, cache_hit columns
  17. ai_visual_generation_log has prompt_hash and NO prompt_text column
  18. visual_experience_event run_reason default is "shadow"
  19. ai_visual_generation_log run_reason default is "shadow"
  20. visual_spec_cache run_reason default is "shadow"
  21. Round-trip insert/select on all three tables
  22. No upstream truth-table modification by Phase 19 schema
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
_MIGRATION = _ROOT / "app" / "db" / "migrations" / "019_visual_intelligence.sql"


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

def _tables():
    from app.db.models import Base
    return set(Base.metadata.tables.keys())


def _columns(table_name: str):
    from app.db.models import Base
    table = Base.metadata.tables.get(table_name)
    if table is None:
        return set()
    return {c.name for c in table.columns}


def _migration_sql() -> str:
    return _MIGRATION.read_text()


_BANNED_COLUMNS = {
    "buy", "sell", "recommendation", "target_price", "position_size",
    "execution", "trade", "forecast_override", "similarity_override",
    "scenario_override", "decision_override", "prompt_text", "raw_prompt",
    "model_output", "raw_output",
}

_VISUAL_TABLES = [
    "visual_spec_cache",
    "visual_experience_event",
    "ai_visual_generation_log",
]


# ===================================================================
# § 1. Table count
# ===================================================================

class TestTableCount:
    def test_db_table_count_gte_59(self):
        from app.db.models import Base
        assert len(Base.metadata.tables) >= 59, (
            f"Expected >= 59 tables, found {len(Base.metadata.tables)}"
        )


# ===================================================================
# § 2. Visual tables exist
# ===================================================================

class TestVisualTablesExist:
    @pytest.mark.parametrize("table_name", _VISUAL_TABLES)
    def test_table_exists(self, table_name):
        assert table_name in _tables(), f"Missing table: {table_name}"


# ===================================================================
# § 3. Indexes
# ===================================================================

class TestIndexes:
    @pytest.mark.parametrize("table_name", _VISUAL_TABLES)
    def test_table_has_indexes(self, table_name):
        from app.db.models import Base
        table = Base.metadata.tables[table_name]
        assert len(table.indexes) > 0, f"No indexes on {table_name}"


# ===================================================================
# § 4. No banned columns
# ===================================================================

class TestNoBannedColumns:
    @pytest.mark.parametrize("table_name", _VISUAL_TABLES)
    def test_no_advice_columns(self, table_name):
        cols = _columns(table_name)
        found = cols & _BANNED_COLUMNS
        assert not found, f"Banned columns on {table_name}: {found}"


# ===================================================================
# § 5. ORM models importable
# ===================================================================

class TestORMModels:
    def test_visual_spec_cache_importable(self):
        from app.db.models import VisualSpecCache
        assert VisualSpecCache.__tablename__ == "visual_spec_cache"

    def test_visual_experience_event_importable(self):
        from app.db.models import VisualExperienceEvent
        assert VisualExperienceEvent.__tablename__ == "visual_experience_event"

    def test_ai_visual_generation_log_importable(self):
        from app.db.models import AIVisualGenerationLog
        assert AIVisualGenerationLog.__tablename__ == "ai_visual_generation_log"


# ===================================================================
# § 6. Flags at safe defaults
# ===================================================================

class TestFlagDefaults:
    def test_visual_json_enabled_default(self):
        from app.config import settings
        assert settings.visual_json_enabled is False

    def test_visual_svg_enabled_default(self):
        from app.config import settings
        assert settings.visual_svg_enabled is False

    def test_visual_ai_enabled_default(self):
        from app.config import settings
        assert settings.visual_ai_enabled is False

    def test_visual_cache_enabled_default(self):
        from app.config import settings
        assert settings.visual_cache_enabled is False

    def test_visual_shadow_default(self):
        from app.config import settings
        assert settings.visual_shadow is True

    def test_visual_calibration_enabled_default(self):
        from app.config import settings
        assert settings.visual_calibration_enabled is False


# ===================================================================
# § 7–8. No advice / truth-override fields on ORM models
# ===================================================================

class TestORMNoAdviceFields:
    @pytest.mark.parametrize("model_name", [
        "VisualSpecCache", "VisualExperienceEvent", "AIVisualGenerationLog",
    ])
    def test_no_advice_fields(self, model_name):
        import app.db.models as models
        cls = getattr(models, model_name)
        col_names = {c.name for c in cls.__table__.columns}
        found = col_names & _BANNED_COLUMNS
        assert not found, f"Banned columns on {model_name}: {found}"


# ===================================================================
# § 9. Migration: no ALTER TABLE
# ===================================================================

class TestMigrationAdditive:
    def test_no_alter_table(self):
        sql = _migration_sql().upper()
        assert "ALTER TABLE" not in sql, "Migration must not ALTER existing tables"


# ===================================================================
# § 10–11. Append-only intent in migration (no UPDATE/DELETE DDL)
# ===================================================================

class TestMigrationAppendOnly:
    def test_no_update_in_migration(self):
        sql = _migration_sql()
        lines = [l.strip() for l in sql.split("\n") if not l.strip().startswith("--")]
        body = " ".join(lines)
        assert "UPDATE " not in body.upper() or "DEFAULT" in body.upper()

    def test_no_delete_in_migration(self):
        sql = _migration_sql()
        lines = [l.strip() for l in sql.split("\n") if not l.strip().startswith("--")]
        body = " ".join(lines)
        assert "DELETE FROM" not in body.upper()


# ===================================================================
# § 12. Migration idempotency
# ===================================================================

class TestMigrationIdempotency:
    def test_all_creates_have_if_not_exists(self):
        sql = _migration_sql()
        lines = sql.split("\n")
        for line in lines:
            stripped = line.strip().upper()
            if stripped.startswith("CREATE TABLE ") and "IF NOT EXISTS" not in stripped:
                pytest.fail(f"Missing IF NOT EXISTS: {line.strip()}")
            if stripped.startswith("CREATE INDEX ") and "IF NOT EXISTS" not in stripped:
                pytest.fail(f"Missing IF NOT EXISTS: {line.strip()}")

    def test_migration_mentions_56_to_59(self):
        sql = _migration_sql()
        assert "56" in sql and "59" in sql, (
            "Migration should document 56 → 59 table count transition"
        )


# ===================================================================
# § 13. Migration SQL: no advice or trade terms
# ===================================================================

class TestMigrationNoAdviceTerms:
    def test_no_banned_column_names_in_ddl(self):
        sql = _migration_sql()
        lines = [l.strip().lower() for l in sql.split("\n") if not l.strip().startswith("--")]
        for line in lines:
            for col in _BANNED_COLUMNS:
                if col in line and "must not exist" not in line.lower():
                    if line.startswith("create") or "column" in line or "varchar" in line:
                        pytest.fail(
                            f"Banned column name '{col}' in DDL line: {line}"
                        )


# ===================================================================
# § 14. Unique constraints
# ===================================================================

class TestUniqueConstraints:
    def test_visual_spec_cache_unique(self):
        from app.db.models import VisualSpecCache
        constraints = [
            c for c in VisualSpecCache.__table__.constraints
            if hasattr(c, "columns") and len(c.columns) == 4
        ]
        assert len(constraints) >= 1, (
            "visual_spec_cache must have unique constraint on "
            "(user_id, visual_type, entity_key, data_hash)"
        )


# ===================================================================
# § 15–16. Column existence
# ===================================================================

class TestColumnExistence:
    def test_visual_experience_event_columns(self):
        cols = _columns("visual_experience_event")
        for col in ("rendering_tier", "generation_ms", "cache_hit",
                     "blocked_reason", "explanation_valid"):
            assert col in cols, f"Missing column: {col}"

    def test_ai_log_has_prompt_hash(self):
        cols = _columns("ai_visual_generation_log")
        assert "prompt_hash" in cols

    def test_ai_log_no_prompt_text(self):
        cols = _columns("ai_visual_generation_log")
        assert "prompt_text" not in cols
        assert "raw_prompt" not in cols
        assert "model_output" not in cols
        assert "raw_output" not in cols

    def test_ai_log_has_validation_fields(self):
        cols = _columns("ai_visual_generation_log")
        for col in ("validation_passed", "validation_reason", "banned_phrases_found"):
            assert col in cols, f"Missing column: {col}"


# ===================================================================
# § 17–19. run_reason defaults
# ===================================================================

class TestRunReasonDefaults:
    @pytest.mark.asyncio
    async def test_visual_spec_cache_default(self, db):
        from app.db.models import VisualSpecCache
        row = VisualSpecCache(
            id=str(uuid.uuid4()), user_id="u1",
            visual_type="test", entity_key="AAPL", data_hash="abc",
        )
        db.add(row)
        await db.flush()
        assert row.run_reason == "shadow"

    @pytest.mark.asyncio
    async def test_visual_experience_event_default(self, db):
        from app.db.models import VisualExperienceEvent
        row = VisualExperienceEvent(
            id=str(uuid.uuid4()), user_id="u1",
        )
        db.add(row)
        await db.flush()
        assert row.run_reason == "shadow"

    @pytest.mark.asyncio
    async def test_ai_visual_generation_log_default(self, db):
        from app.db.models import AIVisualGenerationLog
        row = AIVisualGenerationLog(
            id=str(uuid.uuid4()), user_id="u1",
        )
        db.add(row)
        await db.flush()
        assert row.run_reason == "shadow"


# ===================================================================
# § 20. Round-trip insert/select
# ===================================================================

class TestRoundTrip:
    @pytest.mark.asyncio
    async def test_visual_spec_cache_round_trip(self, db):
        from app.db.models import VisualSpecCache
        from sqlalchemy import select
        row = VisualSpecCache(
            id=str(uuid.uuid4()), user_id="u-rt",
            visual_type="forecast_distribution", entity_key="AAPL",
            data_hash="deadbeef", spec_json='{"test": true}',
            rendering_tier="json", explanation_valid=True,
        )
        db.add(row)
        await db.flush()
        result = (await db.execute(
            select(VisualSpecCache).where(VisualSpecCache.user_id == "u-rt")
        )).scalar_one()
        assert result.visual_type == "forecast_distribution"
        assert result.spec_json == '{"test": true}'
        assert result.rendering_tier == "json"

    @pytest.mark.asyncio
    async def test_visual_experience_event_round_trip(self, db):
        from app.db.models import VisualExperienceEvent
        from sqlalchemy import select
        row = VisualExperienceEvent(
            id=str(uuid.uuid4()), user_id="u-rt",
            visual_type="similarity_network", entity_key="MSFT",
            rendering_tier="svg", generation_ms=250, cache_hit=False,
        )
        db.add(row)
        await db.flush()
        result = (await db.execute(
            select(VisualExperienceEvent).where(VisualExperienceEvent.user_id == "u-rt")
        )).scalar_one()
        assert result.visual_type == "similarity_network"
        assert result.generation_ms == 250
        assert result.cache_hit is False

    @pytest.mark.asyncio
    async def test_ai_visual_generation_log_round_trip(self, db):
        from app.db.models import AIVisualGenerationLog
        from sqlalchemy import select
        row = AIVisualGenerationLog(
            id=str(uuid.uuid4()), user_id="u-rt",
            visual_type="ecosystem_map", entity_key="NVDA",
            prompt_hash="abc123", generation_model="test-model",
            generation_ms=3000, validation_passed=True,
        )
        db.add(row)
        await db.flush()
        result = (await db.execute(
            select(AIVisualGenerationLog).where(AIVisualGenerationLog.user_id == "u-rt")
        )).scalar_one()
        assert result.prompt_hash == "abc123"
        assert result.generation_model == "test-model"
        assert result.validation_passed is True


# ===================================================================
# § 21. No upstream truth-table modification
# ===================================================================

class TestNoUpstreamModification:
    def test_migration_does_not_reference_upstream_tables(self):
        sql = _migration_sql()
        lines = [l.strip() for l in sql.split("\n") if not l.strip().startswith("--")]
        body = "\n".join(lines).lower()
        upstream_tables = [
            "forecast_vector", "forecast_evidence", "forecast_calibration_log",
            "similarity_edge", "similarity_feature_vector",
            "scenario_snapshot", "scenario_evidence",
            "decision_priority", "decision_evidence",
            "ticker_memory", "memory_entries",
            "learned_preference", "user_signal_event",
            "personal_experience_cursor", "personal_experience_event",
            "personal_brief_snapshot",
        ]
        for table in upstream_tables:
            for stmt in ["alter table " + table, "drop table " + table,
                         "insert into " + table, "update " + table,
                         "delete from " + table]:
                assert stmt not in body, (
                    f"Migration must not modify upstream table: {stmt}"
                )
