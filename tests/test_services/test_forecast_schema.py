"""
Tests — Forecasting Engine Schema, Repository, and Flags — Phase 12 · Slice 1.

Covers:
  1.  db_table_count >= 43
  2.  All three forecast tables exist
  3.  No price / recommendation / advice columns exist on forecast_vector
  4.  ORM models import cleanly
  5.  All six forecast_* flags default to inert values
  6.  Repository: upsert / get / list / delete for forecast_vector
  7.  Repository: add / list / delete for forecast_evidence
  8.  Repository: add (insert-only) / list / count for forecast_calibration_log
  9.  Null-session safety (all functions return empty/None/0/False on session=None)
  10. No source-table mutation — snapshot before/after every write op
  11. Unique constraint on forecast_vector (entity_type, entity_key, horizon,
      forecast_type, user_id) — second upsert updates, not duplicates
  12. Calibration log immutability — add_calibration_log only inserts;
      no UPDATE statement in forecast_repo source (AST-verified)
  13. TTL expiry: delete_expired_vectors removes stale rows
  14. No forecasting behavior activated — flags are all inert by default
"""

from __future__ import annotations

import ast
import inspect
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker


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

def _base_vector_kwargs(**overrides):
    defaults = dict(
        entity_type          = "company",
        entity_key           = "NVDA",
        horizon              = "near_term",
        horizon_days         = 30,
        forecast_type        = "thesis_strengthening",
        p_positive           = 0.60,
        p_negative           = 0.25,
        p_neutral            = 0.15,
        confidence_band_low  = 0.45,
        confidence_band_high = 0.72,
        why                  = "Analog base rate is bullish at this stage.",
        invalidators         = ["Analog reclassified", "Similarity cluster dissolves"],
        analog_basis         = ["analog-uuid-1", "analog-uuid-2"],
        similarity_basis     = ["edge-uuid-1"],
        evidence_summary     = [{"rank": 1, "description": "Inventory correction resolved positively"}],
        source_versions      = {"company_dossier": 5, "similarity_edge": 2},
        forecast_schema      = 1,
    )
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# 1. DB table count
# ---------------------------------------------------------------------------

class TestDbTableCount:
    @pytest.mark.asyncio
    async def test_db_table_count_at_least_43(self, engine):
        from app.db.models import Base
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            tables = await conn.run_sync(
                lambda sync_conn: sync_conn.dialect.get_table_names(sync_conn)
            )
        assert len(tables) >= 43, f"Expected >= 43 tables, found {len(tables)}: {sorted(tables)}"


# ---------------------------------------------------------------------------
# 2. All three forecast tables exist
# ---------------------------------------------------------------------------

class TestForecastTablesExist:
    @pytest.mark.asyncio
    async def test_forecast_vector_table_exists(self, engine):
        from app.db.models import Base
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            tables = await conn.run_sync(
                lambda sync_conn: sync_conn.dialect.get_table_names(sync_conn)
            )
        assert "forecast_vector" in tables

    @pytest.mark.asyncio
    async def test_forecast_evidence_table_exists(self, engine):
        from app.db.models import Base
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            tables = await conn.run_sync(
                lambda sync_conn: sync_conn.dialect.get_table_names(sync_conn)
            )
        assert "forecast_evidence" in tables

    @pytest.mark.asyncio
    async def test_forecast_calibration_log_table_exists(self, engine):
        from app.db.models import Base
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            tables = await conn.run_sync(
                lambda sync_conn: sync_conn.dialect.get_table_names(sync_conn)
            )
        assert "forecast_calibration_log" in tables


# ---------------------------------------------------------------------------
# 3. No price / recommendation / advice columns on forecast_vector
# ---------------------------------------------------------------------------

class TestNoPriceOrAdviceColumns:
    def test_forecast_vector_has_no_price_column(self):
        from app.db.models import ForecastVector
        col_names = {c.key for c in ForecastVector.__table__.columns}
        forbidden = {
            "price", "target_price", "price_target", "fair_value",
            "buy", "sell", "hold", "recommendation", "advice",
            "expected_return", "upside", "downside",
        }
        intersection = col_names & forbidden
        assert not intersection, f"Forbidden columns found on forecast_vector: {intersection}"

    def test_forecast_evidence_has_no_price_column(self):
        from app.db.models import ForecastEvidence
        col_names = {c.key for c in ForecastEvidence.__table__.columns}
        forbidden = {"price", "target_price", "buy", "sell", "hold", "recommendation"}
        intersection = col_names & forbidden
        assert not intersection, f"Forbidden columns found on forecast_evidence: {intersection}"

    def test_forecast_calibration_log_has_no_price_column(self):
        from app.db.models import ForecastCalibrationLog
        col_names = {c.key for c in ForecastCalibrationLog.__table__.columns}
        forbidden = {"price", "target_price", "buy", "sell", "hold", "recommendation"}
        intersection = col_names & forbidden
        assert not intersection, f"Forbidden columns found on forecast_calibration_log: {intersection}"


# ---------------------------------------------------------------------------
# 4. ORM models import cleanly
# ---------------------------------------------------------------------------

class TestOrmImports:
    def test_forecast_vector_importable(self):
        from app.db.models import ForecastVector
        assert ForecastVector.__tablename__ == "forecast_vector"

    def test_forecast_evidence_importable(self):
        from app.db.models import ForecastEvidence
        assert ForecastEvidence.__tablename__ == "forecast_evidence"

    def test_forecast_calibration_log_importable(self):
        from app.db.models import ForecastCalibrationLog
        assert ForecastCalibrationLog.__tablename__ == "forecast_calibration_log"

    def test_forecast_repo_importable(self):
        import app.db.repositories.forecast_repo as repo
        assert callable(repo.upsert_forecast_vector)
        assert callable(repo.get_forecast_vector)
        assert callable(repo.list_forecast_vectors)
        assert callable(repo.add_forecast_evidence)
        assert callable(repo.list_forecast_evidence)
        assert callable(repo.add_calibration_log)
        assert callable(repo.list_calibration_logs)


# ---------------------------------------------------------------------------
# 5. All six forecast_* flags default to inert values
# ---------------------------------------------------------------------------

class TestFlagDefaults:
    def test_forecast_build_enabled_default_false(self):
        from app.config import settings
        assert settings.forecast_build_enabled is False

    def test_forecast_scoring_enabled_default_false(self):
        from app.config import settings
        assert settings.forecast_scoring_enabled is False

    def test_forecast_delivery_enabled_default_false(self):
        from app.config import settings
        assert settings.forecast_delivery_enabled is False

    def test_forecast_shadow_default_true(self):
        from app.config import settings
        assert settings.forecast_shadow is True

    def test_forecast_targets_enabled_default_empty(self):
        from app.config import settings
        assert settings.forecast_targets_enabled == ""

    def test_forecast_calibration_enabled_default_false(self):
        from app.config import settings
        assert settings.forecast_calibration_enabled is False


# ---------------------------------------------------------------------------
# 6. Repository: forecast_vector CRUD / upsert / list
# ---------------------------------------------------------------------------

class TestForecastVectorRepo:
    @pytest.mark.asyncio
    async def test_upsert_and_get_forecast_vector(self, db):
        from app.db.repositories.forecast_repo import upsert_forecast_vector, get_forecast_vector

        row = await upsert_forecast_vector(db, **_base_vector_kwargs())
        await db.commit()

        assert row is not None
        assert row.entity_type == "company"
        assert row.entity_key == "NVDA"
        assert row.horizon == "near_term"
        assert row.forecast_type == "thesis_strengthening"
        assert abs(row.p_positive - 0.60) < 0.001
        assert row.why == "Analog base rate is bullish at this stage."
        assert row.forecast_schema == 1
        assert row.expires_at is not None

        fetched = await get_forecast_vector(
            db, entity_type="company", entity_key="NVDA",
            horizon="near_term", forecast_type="thesis_strengthening",
        )
        assert fetched is not None
        assert fetched.id == row.id

    @pytest.mark.asyncio
    async def test_upsert_updates_existing_row(self, db):
        from app.db.repositories.forecast_repo import upsert_forecast_vector, list_forecast_vectors

        await upsert_forecast_vector(db, **_base_vector_kwargs(p_positive=0.55))
        await db.commit()
        await upsert_forecast_vector(db, **_base_vector_kwargs(p_positive=0.70))
        await db.commit()

        rows = await list_forecast_vectors(db, entity_key="NVDA")
        # Should be exactly 1 row (upsert, not insert)
        assert len(rows) == 1
        assert abs(rows[0].p_positive - 0.70) < 0.001

    @pytest.mark.asyncio
    async def test_list_forecast_vectors_filters(self, db):
        from app.db.repositories.forecast_repo import upsert_forecast_vector, list_forecast_vectors

        await upsert_forecast_vector(db, **_base_vector_kwargs(
            entity_key="NVDA", forecast_type="thesis_strengthening"))
        await upsert_forecast_vector(db, **_base_vector_kwargs(
            entity_key="NVDA", forecast_type="risk_emergence",
            p_positive=0.40, p_negative=0.35, p_neutral=0.25,
            why="Risk analog score elevated.",
            analog_basis=["analog-1"],
        ))
        await upsert_forecast_vector(db, **_base_vector_kwargs(
            entity_key="MSFT", forecast_type="thesis_strengthening",
            p_positive=0.65, p_negative=0.20, p_neutral=0.15,
            why="Thesis confidence rising.",
            analog_basis=["analog-2"],
        ))
        await db.commit()

        nvda_rows = await list_forecast_vectors(db, entity_key="NVDA")
        assert len(nvda_rows) == 2

        strength_rows = await list_forecast_vectors(db, forecast_type="thesis_strengthening")
        assert len(strength_rows) == 2

        all_rows = await list_forecast_vectors(db)
        assert len(all_rows) == 3

    @pytest.mark.asyncio
    async def test_delete_forecast_vector(self, db):
        from app.db.repositories.forecast_repo import (
            upsert_forecast_vector, delete_forecast_vector, get_forecast_vector,
        )

        await upsert_forecast_vector(db, **_base_vector_kwargs())
        await db.commit()

        deleted = await delete_forecast_vector(
            db, entity_type="company", entity_key="NVDA",
            horizon="near_term", forecast_type="thesis_strengthening",
        )
        assert deleted is True

        fetched = await get_forecast_vector(
            db, entity_type="company", entity_key="NVDA",
            horizon="near_term", forecast_type="thesis_strengthening",
        )
        assert fetched is None

    @pytest.mark.asyncio
    async def test_user_scoped_and_global_vectors_are_independent(self, db):
        from app.db.repositories.forecast_repo import (
            upsert_forecast_vector, get_forecast_vector,
        )

        global_row = await upsert_forecast_vector(db, **_base_vector_kwargs(user_id=None))
        user_row   = await upsert_forecast_vector(db, **_base_vector_kwargs(user_id="user-abc"))
        await db.commit()

        assert global_row.id != user_row.id

        fetched_global = await get_forecast_vector(
            db, entity_type="company", entity_key="NVDA",
            horizon="near_term", forecast_type="thesis_strengthening",
            user_id=None,
        )
        fetched_user = await get_forecast_vector(
            db, entity_type="company", entity_key="NVDA",
            horizon="near_term", forecast_type="thesis_strengthening",
            user_id="user-abc",
        )
        assert fetched_global.id == global_row.id
        assert fetched_user.id == user_row.id

    @pytest.mark.asyncio
    async def test_count_forecast_vectors(self, db):
        from app.db.repositories.forecast_repo import upsert_forecast_vector, count_forecast_vectors

        assert await count_forecast_vectors(db) == 0
        await upsert_forecast_vector(db, **_base_vector_kwargs(entity_key="NVDA"))
        await upsert_forecast_vector(db, **_base_vector_kwargs(
            entity_key="MSFT",
            why="Rising confidence.",
            analog_basis=["a1"],
        ))
        await db.commit()

        total = await count_forecast_vectors(db)
        assert total == 2

        nvda_count = await count_forecast_vectors(db, entity_type="company")
        assert nvda_count == 2

    @pytest.mark.asyncio
    async def test_delete_expired_vectors(self, db):
        from datetime import timedelta
        from app.db.repositories.forecast_repo import (
            upsert_forecast_vector, delete_expired_vectors, list_forecast_vectors,
        )
        from app.db.models import ForecastVector
        from sqlalchemy import update

        await upsert_forecast_vector(db, **_base_vector_kwargs(entity_key="NVDA"))
        await upsert_forecast_vector(db, **_base_vector_kwargs(
            entity_key="MSFT", why="Peer strong.", analog_basis=["a1"],
        ))
        await db.commit()

        # Force one row to be expired
        from datetime import timezone, datetime
        past = datetime.now(timezone.utc) - timedelta(hours=48)
        await db.execute(
            update(ForecastVector)
            .where(ForecastVector.entity_key == "NVDA")
            .values(expires_at=past)
        )
        await db.commit()

        deleted = await delete_expired_vectors(db)
        assert deleted == 1

        remaining = await list_forecast_vectors(db)
        assert len(remaining) == 1
        assert remaining[0].entity_key == "MSFT"


# ---------------------------------------------------------------------------
# 7. Repository: forecast_evidence add / list / delete
# ---------------------------------------------------------------------------

class TestForecastEvidenceRepo:
    @pytest.mark.asyncio
    async def test_add_and_list_forecast_evidence(self, db):
        from app.db.repositories.forecast_repo import (
            upsert_forecast_vector, add_forecast_evidence, list_forecast_evidence,
        )

        vector = await upsert_forecast_vector(db, **_base_vector_kwargs())
        await db.commit()

        ev1 = await add_forecast_evidence(
            db,
            forecast_id  = vector.id,
            source_type  = "historical_analog",
            source_id    = "analog-uuid-1",
            direction    = "bullish",
            contribution = 0.12,
            weight       = 0.35,
            description  = "Inventory correction resolved positively in 8/10 analogous episodes.",
            entity_type  = "company",
            entity_key   = "NVDA",
        )
        ev2 = await add_forecast_evidence(
            db,
            forecast_id  = vector.id,
            source_type  = "similarity_edge",
            source_id    = "edge-uuid-1",
            direction    = "bullish",
            contribution = 0.08,
            weight       = 0.25,
            description  = "Peer MSFT had similar setup; thesis strengthened.",
            entity_type  = "company",
            entity_key   = "NVDA",
        )
        await db.commit()

        assert ev1 is not None
        assert ev2 is not None

        rows = await list_forecast_evidence(db, forecast_id=vector.id)
        assert len(rows) == 2
        # Ordered by |contribution| desc — ev1 first
        assert rows[0].contribution >= rows[1].contribution

    @pytest.mark.asyncio
    async def test_delete_evidence_for_forecast(self, db):
        from app.db.repositories.forecast_repo import (
            upsert_forecast_vector, add_forecast_evidence,
            delete_evidence_for_forecast, list_forecast_evidence,
        )

        vector = await upsert_forecast_vector(db, **_base_vector_kwargs())
        await add_forecast_evidence(
            db, forecast_id=vector.id, source_type="historical_analog",
            source_id="a1", direction="bullish", contribution=0.10,
            weight=0.35, description="Test evidence.",
        )
        await db.commit()

        deleted = await delete_evidence_for_forecast(db, forecast_id=vector.id)
        assert deleted == 1

        remaining = await list_forecast_evidence(db, forecast_id=vector.id)
        assert remaining == []

    @pytest.mark.asyncio
    async def test_count_forecast_evidence(self, db):
        from app.db.repositories.forecast_repo import (
            upsert_forecast_vector, add_forecast_evidence, count_forecast_evidence,
        )

        assert await count_forecast_evidence(db) == 0

        vector = await upsert_forecast_vector(db, **_base_vector_kwargs())
        await add_forecast_evidence(
            db, forecast_id=vector.id, source_type="historical_analog",
            source_id="a1", direction="bullish", contribution=0.10,
            weight=0.35, description="Evidence A.",
        )
        await db.commit()

        total = await count_forecast_evidence(db)
        assert total == 1

        for_vector = await count_forecast_evidence(db, forecast_id=vector.id)
        assert for_vector == 1


# ---------------------------------------------------------------------------
# 8. Repository: forecast_calibration_log add / list / count
# ---------------------------------------------------------------------------

class TestCalibrationLogRepo:
    @pytest.mark.asyncio
    async def test_add_and_list_calibration_log(self, db):
        from app.db.repositories.forecast_repo import (
            add_calibration_log, list_calibration_logs,
        )

        log = await add_calibration_log(
            db,
            forecast_id            = "fv-uuid-1",
            entity_type            = "company",
            entity_key             = "NVDA",
            horizon                = "near_term",
            forecast_type          = "thesis_strengthening",
            p_positive_at_forecast = 0.60,
            p_negative_at_forecast = 0.25,
            p_neutral_at_forecast  = 0.15,
            actual_outcome         = "positive",
            brier_score            = 0.16,
            evaluation_source      = "thesis_state_change",
        )
        await db.commit()

        assert log is not None
        assert log.actual_outcome == "positive"
        assert abs(log.brier_score - 0.16) < 0.001
        assert log.evaluation_source == "thesis_state_change"

        rows = await list_calibration_logs(db, forecast_id="fv-uuid-1")
        assert len(rows) == 1
        assert rows[0].id == log.id

    @pytest.mark.asyncio
    async def test_calibration_log_each_call_creates_new_row(self, db):
        """Re-evaluation must create a NEW row, not update the existing one."""
        from app.db.repositories.forecast_repo import (
            add_calibration_log, list_calibration_logs,
        )

        await add_calibration_log(
            db, forecast_id="fv-uuid-2", entity_type="company", entity_key="MSFT",
            horizon="near_term", forecast_type="thesis_strengthening",
            p_positive_at_forecast=0.60, p_negative_at_forecast=0.25,
            p_neutral_at_forecast=0.15, actual_outcome="positive",
            brier_score=0.16, evaluation_source="thesis_state_change",
        )
        await add_calibration_log(
            db, forecast_id="fv-uuid-2", entity_type="company", entity_key="MSFT",
            horizon="near_term", forecast_type="thesis_strengthening",
            p_positive_at_forecast=0.60, p_negative_at_forecast=0.25,
            p_neutral_at_forecast=0.15, actual_outcome="negative",
            brier_score=0.36, evaluation_source="manual_review",
        )
        await db.commit()

        rows = await list_calibration_logs(db, forecast_id="fv-uuid-2")
        assert len(rows) == 2  # two rows, not an update

    @pytest.mark.asyncio
    async def test_count_calibration_logs(self, db):
        from app.db.repositories.forecast_repo import add_calibration_log, count_calibration_logs

        assert await count_calibration_logs(db) == 0

        await add_calibration_log(
            db, forecast_id="fv-1", entity_type="company", entity_key="NVDA",
            horizon="near_term", forecast_type="thesis_strengthening",
            p_positive_at_forecast=0.60, p_negative_at_forecast=0.25,
            p_neutral_at_forecast=0.15, actual_outcome="positive",
            brier_score=0.16, evaluation_source="thesis_state_change",
        )
        await db.commit()

        assert await count_calibration_logs(db) == 1
        assert await count_calibration_logs(db, forecast_type="thesis_strengthening") == 1
        assert await count_calibration_logs(db, forecast_type="risk_emergence") == 0


# ---------------------------------------------------------------------------
# 9. Null-session safety
# ---------------------------------------------------------------------------

class TestNullSessionSafety:
    @pytest.mark.asyncio
    async def test_upsert_forecast_vector_session_none(self):
        from app.db.repositories.forecast_repo import upsert_forecast_vector
        result = await upsert_forecast_vector(None, **_base_vector_kwargs())
        assert result is None

    @pytest.mark.asyncio
    async def test_get_forecast_vector_session_none(self):
        from app.db.repositories.forecast_repo import get_forecast_vector
        result = await get_forecast_vector(
            None, entity_type="company", entity_key="NVDA",
            horizon="near_term", forecast_type="thesis_strengthening",
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_list_forecast_vectors_session_none(self):
        from app.db.repositories.forecast_repo import list_forecast_vectors
        result = await list_forecast_vectors(None)
        assert result == []

    @pytest.mark.asyncio
    async def test_delete_forecast_vector_session_none(self):
        from app.db.repositories.forecast_repo import delete_forecast_vector
        result = await delete_forecast_vector(
            None, entity_type="company", entity_key="NVDA",
            horizon="near_term", forecast_type="thesis_strengthening",
        )
        assert result is False

    @pytest.mark.asyncio
    async def test_add_forecast_evidence_session_none(self):
        from app.db.repositories.forecast_repo import add_forecast_evidence
        result = await add_forecast_evidence(
            None, forecast_id="x", source_type="historical_analog",
            source_id="a1", direction="bullish", contribution=0.1,
            weight=0.35, description="Test.",
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_list_forecast_evidence_session_none(self):
        from app.db.repositories.forecast_repo import list_forecast_evidence
        result = await list_forecast_evidence(None)
        assert result == []

    @pytest.mark.asyncio
    async def test_add_calibration_log_session_none(self):
        from app.db.repositories.forecast_repo import add_calibration_log
        result = await add_calibration_log(
            None, forecast_id="x", entity_type="company", entity_key="NVDA",
            horizon="near_term", forecast_type="thesis_strengthening",
            p_positive_at_forecast=0.60, p_negative_at_forecast=0.25,
            p_neutral_at_forecast=0.15, actual_outcome="positive",
            brier_score=0.16, evaluation_source="manual_review",
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_list_calibration_logs_session_none(self):
        from app.db.repositories.forecast_repo import list_calibration_logs
        result = await list_calibration_logs(None)
        assert result == []

    @pytest.mark.asyncio
    async def test_count_forecast_vectors_session_none(self):
        from app.db.repositories.forecast_repo import count_forecast_vectors
        result = await count_forecast_vectors(None)
        assert result == 0

    @pytest.mark.asyncio
    async def test_count_calibration_logs_session_none(self):
        from app.db.repositories.forecast_repo import count_calibration_logs
        result = await count_calibration_logs(None)
        assert result == 0

    @pytest.mark.asyncio
    async def test_delete_expired_vectors_session_none(self):
        from app.db.repositories.forecast_repo import delete_expired_vectors
        result = await delete_expired_vectors(None)
        assert result == 0


# ---------------------------------------------------------------------------
# 10. No source-table mutation
# ---------------------------------------------------------------------------

class TestNoSourceTableMutation:
    @pytest.mark.asyncio
    async def test_repo_writes_only_to_forecast_tables(self, db):
        """Snapshot a selection of source tables before and after repo ops;
        assert they are byte-identical."""
        from sqlalchemy import select
        from app.db.models import (
            CompanyDossier, HistoricalAnalog, ThesisVersion,
            SimilarityEdge, DeliveryLedger, Notification,
        )
        from app.db.repositories.forecast_repo import (
            upsert_forecast_vector, add_forecast_evidence, add_calibration_log,
        )

        async def _snapshot(model):
            rows = (await db.execute(select(model))).scalars().all()
            return sorted(str(r.__dict__) for r in rows)

        before = {
            "CompanyDossier": await _snapshot(CompanyDossier),
            "HistoricalAnalog": await _snapshot(HistoricalAnalog),
            "ThesisVersion": await _snapshot(ThesisVersion),
            "SimilarityEdge": await _snapshot(SimilarityEdge),
            "DeliveryLedger": await _snapshot(DeliveryLedger),
            "Notification": await _snapshot(Notification),
        }

        vector = await upsert_forecast_vector(db, **_base_vector_kwargs())
        if vector:
            await add_forecast_evidence(
                db, forecast_id=vector.id, source_type="historical_analog",
                source_id="a1", direction="bullish", contribution=0.10,
                weight=0.35, description="Test.",
            )
            await add_calibration_log(
                db, forecast_id=vector.id, entity_type="company",
                entity_key="NVDA", horizon="near_term",
                forecast_type="thesis_strengthening",
                p_positive_at_forecast=0.60, p_negative_at_forecast=0.25,
                p_neutral_at_forecast=0.15, actual_outcome="positive",
                brier_score=0.16, evaluation_source="manual_review",
            )
        await db.commit()

        after = {
            "CompanyDossier": await _snapshot(CompanyDossier),
            "HistoricalAnalog": await _snapshot(HistoricalAnalog),
            "ThesisVersion": await _snapshot(ThesisVersion),
            "SimilarityEdge": await _snapshot(SimilarityEdge),
            "DeliveryLedger": await _snapshot(DeliveryLedger),
            "Notification": await _snapshot(Notification),
        }

        for table_name, before_rows in before.items():
            assert before_rows == after[table_name], (
                f"Source table {table_name} was mutated by forecast_repo"
            )


# ---------------------------------------------------------------------------
# 11. Unique constraint — upsert, not duplicate
# ---------------------------------------------------------------------------

class TestUniqueConstraint:
    @pytest.mark.asyncio
    async def test_second_upsert_updates_not_duplicates(self, db):
        from app.db.repositories.forecast_repo import (
            upsert_forecast_vector, list_forecast_vectors,
        )

        row1 = await upsert_forecast_vector(db, **_base_vector_kwargs(p_positive=0.55))
        await db.commit()
        row2 = await upsert_forecast_vector(db, **_base_vector_kwargs(p_positive=0.70))
        await db.commit()

        assert row1.id == row2.id  # same row updated

        all_rows = await list_forecast_vectors(db, entity_key="NVDA")
        assert len(all_rows) == 1
        assert abs(all_rows[0].p_positive - 0.70) < 0.001


# ---------------------------------------------------------------------------
# 12. Calibration log immutability (AST-verified)
# ---------------------------------------------------------------------------

class TestCalibrationLogImmutability:
    def test_forecast_repo_has_no_update_call_on_calibration_log(self):
        """AST-inspect forecast_repo source and verify that no sqlalchemy
        update() call appears anywhere in the module (only insert/add paths
        are legal for forecast_calibration_log)."""
        import app.db.repositories.forecast_repo as repo_module

        source = inspect.getsource(repo_module)
        tree = ast.parse(source)

        # Collect all function-call names at any depth (ast.Call nodes)
        update_calls = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                # sqlalchemy update() appears as Name("update") or Attribute("update")
                func = node.func
                if isinstance(func, ast.Name) and func.id == "update":
                    update_calls.append(ast.get_source_segment(source, node) or "update()")
                elif isinstance(func, ast.Attribute) and func.attr == "update":
                    update_calls.append(ast.get_source_segment(source, node) or ".update()")

        assert not update_calls, (
            "forecast_repo contains update() call(s) — "
            "forecast_calibration_log must be append-only: " + str(update_calls)
        )

    def test_add_calibration_log_only_adds_session_add(self):
        """The add_calibration_log function body must use session.add(),
        not session.execute(update(...))."""
        import app.db.repositories.forecast_repo as repo_module

        source = inspect.getsource(repo_module.add_calibration_log)
        tree = ast.parse(source)

        # Collect function-call names in this function's AST
        call_names = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Name):
                    call_names.append(func.id)
                elif isinstance(func, ast.Attribute):
                    call_names.append(func.attr)

        # Must contain "add" (session.add) and must NOT contain "update"
        assert "update" not in call_names, (
            "add_calibration_log calls update() — violates immutability invariant"
        )
        assert "add" in call_names, (
            "add_calibration_log does not call session.add() — unexpected implementation"
        )


# ---------------------------------------------------------------------------
# 13. No forecasting behavior activated with default flags
# ---------------------------------------------------------------------------

class TestNoForecastingBehaviorActivated:
    def test_all_forecast_flags_inert(self):
        from app.config import settings
        assert settings.forecast_build_enabled is False
        assert settings.forecast_scoring_enabled is False
        assert settings.forecast_delivery_enabled is False
        assert settings.forecast_shadow is True
        assert settings.forecast_targets_enabled == ""
        assert settings.forecast_calibration_enabled is False

    def test_forecast_repo_has_no_forbidden_imports(self):
        """forecast_repo must not import from conviction, recommendation,
        notification, or any forecasting-output consumer."""
        import app.db.repositories.forecast_repo as repo_module

        source = inspect.getsource(repo_module)
        tree = ast.parse(source)

        imported_names = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_names.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imported_names.append(node.module)
                imported_names.extend(alias.name for alias in node.names)

        forbidden_terms = [
            "conviction_engine", "recommendation", "notification_service",
            "dossier_injection", "forecast_delivery",
        ]
        offenders = [
            name for name in imported_names
            if any(term in name.lower() for term in forbidden_terms)
        ]
        assert not offenders, (
            f"forecast_repo imports forbidden module(s): {offenders}"
        )
