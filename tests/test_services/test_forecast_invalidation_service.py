"""
Tests — Forecast Invalidation + Rebuild Orchestration, Phase 12 · Slice 5.

Covers:
  1.  Stale forecast detection (TTL / expires_at)
  2.  Fresh forecast not stale
  3.  find_stale_forecasts query
  4.  T1 company rebuild — end-to-end stored
  5.  T4 failure_mode rebuild — end-to-end stored
  6.  All forecast types × all horizons (6 × 3 = 18, parametrized)
  7.  Invalid distribution blocks storage
  8.  Invalid explanation blocks storage
  9.  Flags inert by default (no _build_override → blocked_flags)
  10. Explicit _build_override=True enables pipeline
  11. No source-table mutation (AST)
  12. No delivery_ledger or notifications rows written
  13. No conviction / notification / delivery imports (AST)
  14. Evidence rows written only when forecast stored
  15. Null-session safety
  16. rebuild_forecasts_for_ticker — all 18 results returned
  17. rebuild_forecast_batch — summary dict shape, limit honored
"""

from __future__ import annotations

import ast
import pathlib
import itertools
from datetime import datetime, timedelta, timezone
from typing import List
from unittest.mock import patch

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

# ---------------------------------------------------------------------------
# Fixtures
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
# Seed helpers
# ---------------------------------------------------------------------------

async def _seed_company(db, ticker: str = "AAPL") -> str:
    from app.db.repositories.dossier_repo import get_or_create_head, upsert_head
    await get_or_create_head(db, ticker, company_name="Test Corp")
    await upsert_head(db, ticker, stance="bullish", conviction=0.7)
    await db.flush()
    return ticker


async def _seed_failure_mode(db, ticker: str = "AAPL"):
    from app.db.repositories.dossier_repo import get_or_create_head, upsert_failure_mode
    from app.db.models import HistoricalAnalog
    analog = HistoricalAnalog(
        label="Test Analog", episode="test episode",
        mechanism="inventory_channel_correction",
        concern_tags=["risk"], sector="tech", business_model="hardware",
        disanalogy="n/a",
    )
    db.add(analog)
    await db.flush()
    await get_or_create_head(db, ticker, company_name="Test Corp")
    fm = await upsert_failure_mode(
        db, ticker, analog.id, sequence_stage=1, relevance_at_match=0.6
    )
    await db.flush()
    return fm


async def _seed_stale_vector(
    db,
    entity_type: str = "company",
    entity_key: str = "AAPL",
    forecast_type: str = "thesis_strengthening",
    horizon_days: int = 30,
    hours_overdue: int = 24,
):
    from app.db.models import ForecastVector
    now = datetime.now(timezone.utc)
    vec = ForecastVector(
        entity_type=entity_type,
        entity_key=entity_key,
        horizon="near_term",
        horizon_days=horizon_days,
        forecast_type=forecast_type,
        p_positive=0.5,
        p_negative=0.25,
        p_neutral=0.25,
        confidence_band_low=0.3,
        confidence_band_high=0.7,
        why="test why",
        invalidators=["test invalidator"],
        analog_basis=[],
        similarity_basis=[],
        evidence_summary=[],
        source_versions={},
        built_at=now - timedelta(hours=hours_overdue + 1),
        expires_at=now - timedelta(hours=hours_overdue),
    )
    db.add(vec)
    await db.flush()
    return vec


async def _seed_fresh_vector(db, entity_key: str = "MSFT"):
    from app.db.models import ForecastVector
    now = datetime.now(timezone.utc)
    vec = ForecastVector(
        entity_type="company",
        entity_key=entity_key,
        horizon="near_term",
        horizon_days=30,
        forecast_type="thesis_strengthening",
        p_positive=0.5,
        p_negative=0.25,
        p_neutral=0.25,
        confidence_band_low=0.3,
        confidence_band_high=0.7,
        why="test why",
        invalidators=["test invalidator"],
        analog_basis=[],
        similarity_basis=[],
        evidence_summary=[],
        source_versions={},
        built_at=now - timedelta(minutes=5),
        expires_at=now + timedelta(hours=23),
    )
    db.add(vec)
    await db.flush()
    return vec


# ---------------------------------------------------------------------------
# 1. Stale detection — is_forecast_stale
# ---------------------------------------------------------------------------

class TestIsForcastStale:
    @pytest.mark.asyncio
    async def test_expired_expires_at_is_stale(self, db):
        from app.services.forecast_invalidation_service import is_forecast_stale
        vec = await _seed_stale_vector(db, hours_overdue=24)
        assert await is_forecast_stale(db, vec) is True

    @pytest.mark.asyncio
    async def test_future_expires_at_not_stale(self, db):
        from app.services.forecast_invalidation_service import is_forecast_stale
        vec = await _seed_fresh_vector(db)
        assert await is_forecast_stale(db, vec) is False

    @pytest.mark.asyncio
    async def test_ttl_override_short_marks_stale(self, db):
        from app.services.forecast_invalidation_service import is_forecast_stale
        vec = await _seed_fresh_vector(db, entity_key="GOOG")
        # Force built_at to 2 hours ago but expires_at still in future
        from app.db.models import ForecastVector
        vec.built_at = datetime.now(timezone.utc) - timedelta(hours=2)
        vec.expires_at = datetime.now(timezone.utc) + timedelta(hours=22)
        await db.flush()
        # With a 1-hour TTL override it should be stale
        assert await is_forecast_stale(db, vec, ttl_hours=1) is True

    @pytest.mark.asyncio
    async def test_null_session_returns_false(self, db):
        from app.services.forecast_invalidation_service import is_forecast_stale
        vec = await _seed_stale_vector(db, entity_key="NULL1")
        assert await is_forecast_stale(None, vec) is False

    @pytest.mark.asyncio
    async def test_null_vector_returns_false(self, db):
        from app.services.forecast_invalidation_service import is_forecast_stale
        assert await is_forecast_stale(db, None) is False


# ---------------------------------------------------------------------------
# 2. find_stale_forecasts query
# ---------------------------------------------------------------------------

class TestFindStaleForecasts:
    @pytest.mark.asyncio
    async def test_returns_stale_vectors(self, db):
        from app.services.forecast_invalidation_service import find_stale_forecasts
        await _seed_stale_vector(db, entity_key="STALE1")
        await _seed_stale_vector(db, entity_key="STALE2", forecast_type="risk_emergence")
        await _seed_fresh_vector(db, entity_key="FRESH1")

        stale = await find_stale_forecasts(db)
        keys = [v.entity_key for v in stale]
        assert "STALE1" in keys
        assert "STALE2" in keys
        assert "FRESH1" not in keys

    @pytest.mark.asyncio
    async def test_filters_by_target_type(self, db):
        from app.services.forecast_invalidation_service import find_stale_forecasts
        await _seed_stale_vector(db, entity_key="CO1", entity_type="company")
        await _seed_stale_vector(db, entity_key="FM1", entity_type="failure_mode")

        company_stale = await find_stale_forecasts(db, target_type="company")
        assert all(v.entity_type == "company" for v in company_stale)

        fm_stale = await find_stale_forecasts(db, target_type="failure_mode")
        assert all(v.entity_type == "failure_mode" for v in fm_stale)

    @pytest.mark.asyncio
    async def test_limit_honored(self, db):
        from app.services.forecast_invalidation_service import find_stale_forecasts
        for i in range(5):
            await _seed_stale_vector(db, entity_key=f"LIMIT{i}", forecast_type="risk_emergence")
        result = await find_stale_forecasts(db, limit=3)
        assert len(result) <= 3

    @pytest.mark.asyncio
    async def test_null_session_returns_empty(self, db):
        from app.services.forecast_invalidation_service import find_stale_forecasts
        assert await find_stale_forecasts(None) == []


# ---------------------------------------------------------------------------
# 3. T1 company rebuild
# ---------------------------------------------------------------------------

class TestRebuildCompany:
    @pytest.mark.asyncio
    async def test_rebuild_stores_vector(self, db):
        from app.services.forecast_invalidation_service import rebuild_forecast_for_target
        await _seed_company(db, "STORE1")

        result = await rebuild_forecast_for_target(
            db, "company", "STORE1", "thesis_strengthening", 30,
            _build_override=True,
        )
        assert result is not None
        assert result["status"] == "stored"

    @pytest.mark.asyncio
    async def test_result_dict_has_required_keys(self, db):
        from app.services.forecast_invalidation_service import rebuild_forecast_for_target
        await _seed_company(db, "KEYS1")

        result = await rebuild_forecast_for_target(
            db, "company", "KEYS1", "risk_emergence", 90,
            _build_override=True,
        )
        assert result is not None
        for key in ("status", "entity_type", "entity_key", "forecast_type",
                    "horizon_days", "vector_id", "evidence_count"):
            assert key in result, f"Missing key: {key}"

    @pytest.mark.asyncio
    async def test_result_entity_fields_correct(self, db):
        from app.services.forecast_invalidation_service import rebuild_forecast_for_target
        await _seed_company(db, "FIELD1")

        result = await rebuild_forecast_for_target(
            db, "company", "FIELD1", "catalyst_realization", 180,
            _build_override=True,
        )
        assert result["entity_type"] == "company"
        assert result["entity_key"] == "FIELD1"
        assert result["forecast_type"] == "catalyst_realization"
        assert result["horizon_days"] == 180

    @pytest.mark.asyncio
    async def test_vector_written_to_db(self, db):
        from app.services.forecast_invalidation_service import rebuild_forecast_for_target
        from app.db.repositories.forecast_repo import get_forecast_vector
        await _seed_company(db, "DB1")

        result = await rebuild_forecast_for_target(
            db, "company", "DB1", "thesis_strengthening", 30,
            _build_override=True,
        )
        assert result["status"] == "stored"
        stored = await get_forecast_vector(
            db, entity_type="company", entity_key="DB1",
            horizon="near_term", forecast_type="thesis_strengthening",
        )
        assert stored is not None
        assert stored.p_positive > 0
        assert stored.p_positive + stored.p_negative + stored.p_neutral == pytest.approx(1.0, abs=0.01)

    @pytest.mark.asyncio
    async def test_missing_entity_returns_no_features(self, db):
        from app.services.forecast_invalidation_service import rebuild_forecast_for_target
        result = await rebuild_forecast_for_target(
            db, "company", "NOEXIST", "thesis_strengthening", 30,
            _build_override=True,
        )
        assert result is not None
        assert result["status"] == "no_features"
        assert result["vector_id"] is None


# ---------------------------------------------------------------------------
# 4. T4 failure_mode rebuild
# ---------------------------------------------------------------------------

class TestRebuildFailureMode:
    @pytest.mark.asyncio
    async def test_rebuild_failure_mode_stored(self, db):
        from app.services.forecast_invalidation_service import rebuild_forecast_for_target
        fm = await _seed_failure_mode(db, "FM_TICK")

        result = await rebuild_forecast_for_target(
            db, "failure_mode", fm.id, "risk_emergence", 90,
            _build_override=True,
        )
        assert result is not None
        assert result["status"] == "stored"
        assert result["entity_type"] == "failure_mode"
        assert result["entity_key"] == fm.id

    @pytest.mark.asyncio
    async def test_failure_mode_vector_written_to_db(self, db):
        from app.services.forecast_invalidation_service import rebuild_forecast_for_target
        from app.db.repositories.forecast_repo import get_forecast_vector
        fm = await _seed_failure_mode(db, "FM_DB2")

        result = await rebuild_forecast_for_target(
            db, "failure_mode", fm.id, "regime_transition", 180,
            _build_override=True,
        )
        assert result["status"] == "stored"
        stored = await get_forecast_vector(
            db, entity_type="failure_mode", entity_key=fm.id,
            horizon="long_term", forecast_type="regime_transition",
        )
        assert stored is not None

    @pytest.mark.asyncio
    async def test_missing_failure_mode_returns_no_features(self, db):
        from app.services.forecast_invalidation_service import rebuild_forecast_for_target
        fake_id = "00000000-0000-0000-0000-000000000001"
        result = await rebuild_forecast_for_target(
            db, "failure_mode", fake_id, "risk_emergence", 30,
            _build_override=True,
        )
        assert result is not None
        assert result["status"] == "no_features"


# ---------------------------------------------------------------------------
# 5. All forecast types × all horizons (6 × 3 = 18 combinations)
# ---------------------------------------------------------------------------

_ALL_TYPES = [
    "thesis_strengthening", "thesis_weakening", "risk_emergence",
    "catalyst_realization", "similarity_outcome", "regime_transition",
]
_ALL_HORIZONS = [30, 90, 180]
_ALL_COMBINATIONS = list(itertools.product(_ALL_TYPES, _ALL_HORIZONS))


class TestAllForecastTypesHorizons:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("forecast_type,horizon_days", _ALL_COMBINATIONS)
    async def test_all_type_horizon_combinations_store(
        self, db, forecast_type, horizon_days
    ):
        from app.services.forecast_invalidation_service import rebuild_forecast_for_target
        ticker = f"ALL{forecast_type[:3].upper()}{horizon_days}"
        await _seed_company(db, ticker)

        result = await rebuild_forecast_for_target(
            db, "company", ticker, forecast_type, horizon_days,
            _build_override=True,
        )
        assert result is not None, (
            f"Got None for {forecast_type}/{horizon_days}"
        )
        assert result["status"] == "stored", (
            f"Expected 'stored', got '{result['status']}' for {forecast_type}/{horizon_days}"
        )
        assert result["vector_id"] is not None


# ---------------------------------------------------------------------------
# 6. Blocking gates
# ---------------------------------------------------------------------------

# A probability output dict where p_pos + p_neg + p_neu != 1.0.
# Used to trigger validate_forecast_distribution → False without touching
# the engine's internal assert (which fires before this dict is returned).
_INVALID_DIST_OUTPUT = {
    "p_positive": 0.60,
    "p_negative": 0.60,   # sum = 1.80 → fails validate_forecast_distribution
    "p_neutral": 0.60,
    "confidence_low": 0.3,
    "confidence_high": 0.7,
    "confidence_label": "low",
    "horizon_days": 30,
    "forecast_type": "thesis_strengthening",
    "components": {},
    "evidence_strength": 0.0,
    "staleness_penalty_applied": False,
    "engine_schema": 1,
}


class TestInvalidationBlocking:
    @pytest.mark.asyncio
    async def test_invalid_distribution_blocks_storage(self, db):
        from app.services.forecast_invalidation_service import rebuild_forecast_for_target
        await _seed_company(db, "DISTBLK")

        # Patch the scorer to return an invalid distribution directly; this
        # bypasses the engine's internal assert so the service's own
        # validate_forecast_distribution call sees the bad distribution.
        with patch(
            "app.services.forecast_probability_engine.score_company_forecast",
            return_value=_INVALID_DIST_OUTPUT,
        ):
            result = await rebuild_forecast_for_target(
                db, "company", "DISTBLK", "thesis_strengthening", 30,
                _build_override=True,
            )
        assert result is not None
        assert result["status"] == "blocked_distribution"
        assert result["vector_id"] is None

    @pytest.mark.asyncio
    async def test_invalid_explanation_blocks_storage(self, db):
        from app.services.forecast_invalidation_service import rebuild_forecast_for_target
        await _seed_company(db, "EXPBLK")

        with patch(
            "app.services.forecast_explainability_service.validate_forecast_explanation",
            return_value=False,
        ):
            result = await rebuild_forecast_for_target(
                db, "company", "EXPBLK", "thesis_strengthening", 30,
                _build_override=True,
            )
        assert result is not None
        assert result["status"] == "blocked_explanation"
        assert result["vector_id"] is None

    @pytest.mark.asyncio
    async def test_invalid_distribution_writes_no_vector(self, db):
        from app.services.forecast_invalidation_service import rebuild_forecast_for_target
        from app.db.repositories.forecast_repo import get_forecast_vector
        await _seed_company(db, "NODISTV")

        with patch(
            "app.services.forecast_probability_engine.score_company_forecast",
            return_value=_INVALID_DIST_OUTPUT,
        ):
            await rebuild_forecast_for_target(
                db, "company", "NODISTV", "thesis_strengthening", 30,
                _build_override=True,
            )
        stored = await get_forecast_vector(
            db, entity_type="company", entity_key="NODISTV",
            horizon="near_term", forecast_type="thesis_strengthening",
        )
        assert stored is None

    @pytest.mark.asyncio
    async def test_invalid_explanation_writes_no_evidence(self, db):
        from app.services.forecast_invalidation_service import rebuild_forecast_for_target
        from app.db.repositories.forecast_repo import count_forecast_evidence
        await _seed_company(db, "NOEXPEV")

        with patch(
            "app.services.forecast_explainability_service.validate_forecast_explanation",
            return_value=False,
        ):
            await rebuild_forecast_for_target(
                db, "company", "NOEXPEV", "thesis_strengthening", 30,
                _build_override=True,
            )
        count = await count_forecast_evidence(db)
        assert count == 0


# ---------------------------------------------------------------------------
# 7. Flags inert by default
# ---------------------------------------------------------------------------

class TestFlagsInertByDefault:
    @pytest.mark.asyncio
    async def test_rebuild_blocked_without_override(self, db):
        from app.services.forecast_invalidation_service import rebuild_forecast_for_target
        await _seed_company(db, "FLAGCO")

        # No _build_override → defaults to settings (both False) → blocked
        result = await rebuild_forecast_for_target(
            db, "company", "FLAGCO", "thesis_strengthening", 30,
        )
        assert result is not None
        assert result["status"] == "blocked_flags"
        assert result["vector_id"] is None

    @pytest.mark.asyncio
    async def test_ticker_rebuild_blocked_without_override(self, db):
        from app.services.forecast_invalidation_service import rebuild_forecasts_for_ticker
        await _seed_company(db, "FLAGTK")

        results = await rebuild_forecasts_for_ticker(db, "FLAGTK")
        assert all(r["status"] == "blocked_flags" for r in results)

    @pytest.mark.asyncio
    async def test_batch_blocked_without_override(self, db):
        from app.services.forecast_invalidation_service import rebuild_forecast_batch
        await _seed_stale_vector(db, entity_key="FLAGBATCH")

        summary = await rebuild_forecast_batch(db)
        assert summary["stored"] == 0
        assert summary["blocked_flags"] == summary["total_stale"]

    @pytest.mark.asyncio
    async def test_explicit_override_false_forces_inert(self, db):
        from app.services.forecast_invalidation_service import rebuild_forecast_for_target
        await _seed_company(db, "FORCEOFF")

        result = await rebuild_forecast_for_target(
            db, "company", "FORCEOFF", "thesis_strengthening", 30,
            _build_override=False,
        )
        assert result["status"] == "blocked_flags"


# ---------------------------------------------------------------------------
# 8. Null-session safety
# ---------------------------------------------------------------------------

class TestNullSessionSafety:
    @pytest.mark.asyncio
    async def test_is_forecast_stale_null_session(self, db):
        from app.services.forecast_invalidation_service import is_forecast_stale
        vec = await _seed_stale_vector(db, entity_key="NULLS1")
        result = await is_forecast_stale(None, vec)
        assert result is False

    @pytest.mark.asyncio
    async def test_find_stale_forecasts_null_session(self):
        from app.services.forecast_invalidation_service import find_stale_forecasts
        result = await find_stale_forecasts(None)
        assert result == []

    @pytest.mark.asyncio
    async def test_rebuild_for_target_null_session(self):
        from app.services.forecast_invalidation_service import rebuild_forecast_for_target
        result = await rebuild_forecast_for_target(
            None, "company", "NULLS2", "thesis_strengthening", 30,
            _build_override=True,
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_rebuild_for_ticker_null_session(self):
        from app.services.forecast_invalidation_service import rebuild_forecasts_for_ticker
        result = await rebuild_forecasts_for_ticker(None, "NULLS3", _build_override=True)
        assert result == []

    @pytest.mark.asyncio
    async def test_rebuild_batch_null_session(self):
        from app.services.forecast_invalidation_service import rebuild_forecast_batch
        result = await rebuild_forecast_batch(None, _build_override=True)
        assert result == {}


# ---------------------------------------------------------------------------
# 9. No source-table mutation (AST)
# ---------------------------------------------------------------------------

_SVC_PATH = (
    pathlib.Path(__file__).parent.parent.parent
    / "app" / "services" / "forecast_invalidation_service.py"
)


def _load_svc_ast() -> ast.Module:
    return ast.parse(_SVC_PATH.read_text())


_SOURCE_TABLES = (
    "company_dossier", "dossier_core_debate", "dossier_moat_dimension",
    "dossier_catalyst", "dossier_durability", "dossier_failure_mode",
    "dossier_revision", "dossier_evidence_ref",
    "historical_analogs", "HistoricalAnalog",
    "thesis_versions", "ThesisVersion",
    "similarity_edge", "SimilarityEdge", "similarity_feature_vector",
    "portfolio", "portfolios",
)


class TestNoSourceTableMutation:
    def test_no_direct_source_table_import(self):
        tree = _load_svc_ast()
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                module = getattr(node, "module", "") or ""
                for alias in getattr(node, "names", []):
                    name = alias.name or ""
                    for tbl in _SOURCE_TABLES:
                        assert tbl not in module, (
                            f"Service imports source table module: {tbl}"
                        )
                        assert tbl not in name, (
                            f"Service imports source table name: {tbl}"
                        )

    def test_no_session_add_of_source_rows(self):
        src = _SVC_PATH.read_text()
        tree = ast.parse(src)
        # session.add() calls must only add forecast_vector/forecast_evidence
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                # Look for calls that look like session.add(SomeName(...))
                func = node.func
                if isinstance(func, ast.Attribute) and func.attr == "add":
                    for arg in node.args:
                        if isinstance(arg, ast.Call) and isinstance(arg.func, ast.Name):
                            class_name = arg.func.id
                            for tbl in _SOURCE_TABLES:
                                assert tbl not in class_name, (
                                    f"session.add() of source table row: {class_name}"
                                )


# ---------------------------------------------------------------------------
# 10. No delivery / notification rows written
# ---------------------------------------------------------------------------

class TestNoDeliveryNotification:
    @pytest.mark.asyncio
    async def test_no_delivery_ledger_rows_after_rebuild(self, db):
        from app.services.forecast_invalidation_service import rebuild_forecast_for_target
        from app.db.models import DeliveryLedger
        from sqlalchemy import select, func
        await _seed_company(db, "NODELIV")

        await rebuild_forecast_for_target(
            db, "company", "NODELIV", "thesis_strengthening", 30,
            _build_override=True,
        )

        count_stmt = select(func.count()).select_from(DeliveryLedger)
        result = await db.execute(count_stmt)
        assert int(result.scalar_one() or 0) == 0

    @pytest.mark.asyncio
    async def test_no_notification_rows_after_rebuild(self, db):
        from app.services.forecast_invalidation_service import rebuild_forecast_for_target
        from app.db.models import Notification
        from sqlalchemy import select, func
        await _seed_company(db, "NONOTIF")

        await rebuild_forecast_for_target(
            db, "company", "NONOTIF", "thesis_strengthening", 30,
            _build_override=True,
        )

        count_stmt = select(func.count()).select_from(Notification)
        result = await db.execute(count_stmt)
        assert int(result.scalar_one() or 0) == 0

    @pytest.mark.asyncio
    async def test_batch_no_delivery_rows(self, db):
        from app.services.forecast_invalidation_service import rebuild_forecast_batch
        from app.db.models import DeliveryLedger
        from sqlalchemy import select, func
        await _seed_company(db, "BATCHDEL")
        await _seed_stale_vector(db, entity_key="BATCHDEL")

        await rebuild_forecast_batch(db, _build_override=True)

        count_stmt = select(func.count()).select_from(DeliveryLedger)
        result = await db.execute(count_stmt)
        assert int(result.scalar_one() or 0) == 0


# ---------------------------------------------------------------------------
# 11. No conviction / notification / delivery imports (AST)
# ---------------------------------------------------------------------------

_FORBIDDEN_MODULE_FRAGMENTS = (
    "conviction",
    "recommendation",
    "delivery_ledger",
    "notifications",
    "notification_service",
    "audit_log",
)

_FORBIDDEN_CLASS_NAMES = (
    "Notification",
    "DeliveryLedger",
    "AuditLog",
)


class TestNoForbiddenImports:
    def test_no_conviction_or_delivery_module_imports(self):
        tree = _load_svc_ast()
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                module = (getattr(node, "module", "") or "").lower()
                for fragment in _FORBIDDEN_MODULE_FRAGMENTS:
                    assert fragment not in module, (
                        f"Forbidden import in service: {fragment!r} found in {module!r}"
                    )

    def test_no_forbidden_class_direct_imports(self):
        tree = _load_svc_ast()
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                for alias in getattr(node, "names", []):
                    name = alias.name or ""
                    for cls in _FORBIDDEN_CLASS_NAMES:
                        assert cls not in name, (
                            f"Forbidden class import: {cls!r} found in {name!r}"
                        )

    def test_no_delivery_forecast_import_in_service(self):
        tree = _load_svc_ast()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                module = (node.module or "").lower()
                assert "forecast_delivery" not in module, (
                    f"forecast_delivery imported in invalidation service"
                )


# ---------------------------------------------------------------------------
# 12. Evidence rows written only when forecast stored
# ---------------------------------------------------------------------------

class TestEvidenceRows:
    @pytest.mark.asyncio
    async def test_evidence_rows_created_on_store(self, db):
        from app.services.forecast_invalidation_service import rebuild_forecast_for_target
        from app.db.repositories.forecast_repo import count_forecast_evidence
        await _seed_company(db, "EVROW1")

        result = await rebuild_forecast_for_target(
            db, "company", "EVROW1", "thesis_strengthening", 30,
            _build_override=True,
        )
        assert result["status"] == "stored"
        # Evidence rows should exist for the stored vector
        count = await count_forecast_evidence(db, forecast_id=result["vector_id"])
        assert count > 0

    @pytest.mark.asyncio
    async def test_evidence_count_in_result_matches_db(self, db):
        from app.services.forecast_invalidation_service import rebuild_forecast_for_target
        from app.db.repositories.forecast_repo import count_forecast_evidence
        await _seed_company(db, "EVCOUNT")

        result = await rebuild_forecast_for_target(
            db, "company", "EVCOUNT", "risk_emergence", 90,
            _build_override=True,
        )
        assert result["status"] == "stored"
        db_count = await count_forecast_evidence(db, forecast_id=result["vector_id"])
        assert result["evidence_count"] == db_count

    @pytest.mark.asyncio
    async def test_no_evidence_rows_when_blocked(self, db):
        from app.services.forecast_invalidation_service import rebuild_forecast_for_target
        from app.db.repositories.forecast_repo import count_forecast_evidence
        await _seed_company(db, "EVBLK")

        with patch(
            "app.services.forecast_probability_engine.score_company_forecast",
            return_value=_INVALID_DIST_OUTPUT,
        ):
            result = await rebuild_forecast_for_target(
                db, "company", "EVBLK", "thesis_strengthening", 30,
                _build_override=True,
            )
        assert result["status"] == "blocked_distribution"
        total = await count_forecast_evidence(db)
        assert total == 0

    @pytest.mark.asyncio
    async def test_evidence_tied_to_vector_id(self, db):
        from app.services.forecast_invalidation_service import rebuild_forecast_for_target
        from app.db.repositories.forecast_repo import list_forecast_evidence
        await _seed_company(db, "EVTIED")

        result = await rebuild_forecast_for_target(
            db, "company", "EVTIED", "catalyst_realization", 180,
            _build_override=True,
        )
        assert result["status"] == "stored"
        evidence = await list_forecast_evidence(db, forecast_id=result["vector_id"])
        assert all(ev.forecast_id == result["vector_id"] for ev in evidence)


# ---------------------------------------------------------------------------
# 13. rebuild_forecasts_for_ticker — all 18 results
# ---------------------------------------------------------------------------

class TestRebuildForecastsForTicker:
    @pytest.mark.asyncio
    async def test_returns_18_results_for_default_params(self, db):
        from app.services.forecast_invalidation_service import rebuild_forecasts_for_ticker
        await _seed_company(db, "TK18")

        results = await rebuild_forecasts_for_ticker(db, "TK18", _build_override=True)
        assert len(results) == 18  # 6 types × 3 horizons

    @pytest.mark.asyncio
    async def test_all_stored_for_seeded_company(self, db):
        from app.services.forecast_invalidation_service import rebuild_forecasts_for_ticker
        await _seed_company(db, "TKALL")

        results = await rebuild_forecasts_for_ticker(db, "TKALL", _build_override=True)
        statuses = [r["status"] for r in results]
        assert all(s == "stored" for s in statuses), (
            f"Non-stored statuses: {[s for s in statuses if s != 'stored']}"
        )

    @pytest.mark.asyncio
    async def test_subset_types_honored(self, db):
        from app.services.forecast_invalidation_service import rebuild_forecasts_for_ticker
        await _seed_company(db, "TKSUB")

        results = await rebuild_forecasts_for_ticker(
            db, "TKSUB",
            forecast_types=["thesis_strengthening"],
            horizons=[30, 90],
            _build_override=True,
        )
        assert len(results) == 2
        assert all(r["forecast_type"] == "thesis_strengthening" for r in results)
        assert {r["horizon_days"] for r in results} == {30, 90}

    @pytest.mark.asyncio
    async def test_null_session_returns_empty_list(self):
        from app.services.forecast_invalidation_service import rebuild_forecasts_for_ticker
        result = await rebuild_forecasts_for_ticker(None, "TKNULL", _build_override=True)
        assert result == []


# ---------------------------------------------------------------------------
# 14. rebuild_forecast_batch — summary dict and limit
# ---------------------------------------------------------------------------

class TestRebuildForecastBatch:
    @pytest.mark.asyncio
    async def test_batch_summary_shape(self, db):
        from app.services.forecast_invalidation_service import rebuild_forecast_batch

        summary = await rebuild_forecast_batch(db, _build_override=True)
        for key in ("total_stale", "stored", "blocked_distribution",
                    "blocked_explanation", "blocked_flags", "no_features", "errors"):
            assert key in summary, f"Missing summary key: {key}"

    @pytest.mark.asyncio
    async def test_batch_stores_stale_vector_for_seeded_company(self, db):
        from app.services.forecast_invalidation_service import rebuild_forecast_batch
        await _seed_company(db, "BATCHCO")
        await _seed_stale_vector(
            db, entity_key="BATCHCO", forecast_type="thesis_strengthening",
        )

        summary = await rebuild_forecast_batch(db, _build_override=True)
        assert summary["total_stale"] >= 1
        assert summary["stored"] >= 1

    @pytest.mark.asyncio
    async def test_batch_limit_caps_processing(self, db):
        from app.services.forecast_invalidation_service import rebuild_forecast_batch
        for i in range(5):
            await _seed_company(db, f"BLIM{i}")
            await _seed_stale_vector(
                db, entity_key=f"BLIM{i}", forecast_type="regime_transition",
            )

        summary = await rebuild_forecast_batch(db, limit=2, _build_override=True)
        assert summary["total_stale"] <= 2

    @pytest.mark.asyncio
    async def test_batch_blocked_when_target_not_in_allowlist(self, db):
        from app.services.forecast_invalidation_service import rebuild_forecast_batch
        await _seed_company(db, "BATCHBLK")
        await _seed_stale_vector(db, entity_key="BATCHBLK", entity_type="company")

        # No _build_override → _batch_target_approved uses settings.forecast_targets_enabled=""
        summary = await rebuild_forecast_batch(db)
        assert summary["stored"] == 0
        assert summary["blocked_flags"] == summary["total_stale"]

    @pytest.mark.asyncio
    async def test_batch_null_session_returns_empty_dict(self):
        from app.services.forecast_invalidation_service import rebuild_forecast_batch
        result = await rebuild_forecast_batch(None)
        assert result == {}

    @pytest.mark.asyncio
    async def test_fresh_vectors_not_in_batch(self, db):
        from app.services.forecast_invalidation_service import rebuild_forecast_batch
        await _seed_fresh_vector(db, entity_key="FRESH_SKIP")

        summary = await rebuild_forecast_batch(db, _build_override=True)
        assert summary["total_stale"] == 0
