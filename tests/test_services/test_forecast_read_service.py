"""
Tests — Forecast Read Service, Phase 12 · Slice 6.

Covers:
  1.  Empty state — no forecasts built yet
  2.  Populated forecasts — valid vectors returned
  3.  Expired forecasts filtered
  4.  Invalid forecast (empty why / empty invalidators / unsupported type)
  5.  Unsupported horizon filtered
  6.  Disclaimer always included in every forecast and at facet level
  7.  No rebuild during reads (AST + runtime)
  8.  No conviction/recommendation imports (AST)
  9.  No source-table writes (AST)
  10. get_forecasts_for_target — target_type/id filtering
  11. get_forecasts_for_ticker — company shorthand
  12. get_forecast_facet_for_ticker — full facet shape + safe empty state
  13. Null-session safety
  14. why split from stored newline-joined string
  15. ordering (horizon_days asc then forecast_type asc)
"""

from __future__ import annotations

import ast
import pathlib
from datetime import datetime, timedelta, timezone

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

async def _seed_vector(
    db,
    entity_type: str = "company",
    entity_key: str = "AAPL",
    forecast_type: str = "thesis_strengthening",
    horizon_days: int = 30,
    p_positive: float = 0.55,
    p_negative: float = 0.25,
    p_neutral: float = 0.20,
    why: str = "Pattern frequency is driven by analog base rate.",
    invalidators: list = None,
    expired: bool = False,
):
    from app.db.models import ForecastVector
    now = datetime.now(timezone.utc)
    expires = now - timedelta(hours=1) if expired else now + timedelta(hours=23)

    vec = ForecastVector(
        entity_type=entity_type,
        entity_key=entity_key,
        horizon="near_term" if horizon_days == 30 else (
            "medium_term" if horizon_days == 90 else "long_term"
        ),
        horizon_days=horizon_days,
        forecast_type=forecast_type,
        p_positive=p_positive,
        p_negative=p_negative,
        p_neutral=p_neutral,
        confidence_band_low=0.35,
        confidence_band_high=0.75,
        why=why,
        invalidators=invalidators if invalidators is not None else ["Macro conditions shift."],
        analog_basis=[],
        similarity_basis=[],
        evidence_summary=[],
        source_versions={},
        built_at=now - timedelta(minutes=5),
        expires_at=expires,
    )
    db.add(vec)
    await db.flush()
    return vec


# ---------------------------------------------------------------------------
# 1. Empty state
# ---------------------------------------------------------------------------

class TestEmptyState:
    @pytest.mark.asyncio
    async def test_get_forecasts_for_target_empty(self, db):
        from app.services.forecast_read_service import get_forecasts_for_target
        result = await get_forecasts_for_target(db, "company", "NOEXIST")
        assert result == []

    @pytest.mark.asyncio
    async def test_get_forecasts_for_ticker_empty(self, db):
        from app.services.forecast_read_service import get_forecasts_for_ticker
        result = await get_forecasts_for_ticker(db, "NOEXIST")
        assert result == []

    @pytest.mark.asyncio
    async def test_facet_empty_state_shape(self, db):
        from app.services.forecast_read_service import get_forecast_facet_for_ticker
        result = await get_forecast_facet_for_ticker(db, "NOEXIST")
        assert result["has_forecasts"] is False
        assert result["forecasts"] == []
        assert "disclaimer" in result
        assert result["ticker"] == "NOEXIST"

    @pytest.mark.asyncio
    async def test_facet_empty_has_mandatory_disclaimer(self, db):
        from app.services.forecast_read_service import get_forecast_facet_for_ticker
        from app.services.forecast_constants import MANDATORY_DISCLAIMER
        result = await get_forecast_facet_for_ticker(db, "EMPTY99")
        assert result["disclaimer"] == MANDATORY_DISCLAIMER


# ---------------------------------------------------------------------------
# 2. Populated forecasts
# ---------------------------------------------------------------------------

class TestPopulatedForecasts:
    @pytest.mark.asyncio
    async def test_valid_vector_returned(self, db):
        from app.services.forecast_read_service import get_forecasts_for_target
        await _seed_vector(db, entity_key="POP1")

        result = await get_forecasts_for_target(db, "company", "POP1")
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_forecast_dict_has_required_keys(self, db):
        from app.services.forecast_read_service import get_forecasts_for_target
        await _seed_vector(db, entity_key="KEYS1")

        result = await get_forecasts_for_target(db, "company", "KEYS1")
        assert len(result) == 1
        f = result[0]
        for key in ("forecast_type", "horizon_days", "horizon", "p_positive",
                    "p_negative", "p_neutral", "confidence_label", "why",
                    "invalidators", "disclaimer", "vector_id", "built_at"):
            assert key in f, f"Missing key: {key}"

    @pytest.mark.asyncio
    async def test_probabilities_correct(self, db):
        from app.services.forecast_read_service import get_forecasts_for_target
        await _seed_vector(db, entity_key="PROB1", p_positive=0.55, p_negative=0.25, p_neutral=0.20)

        result = await get_forecasts_for_target(db, "company", "PROB1")
        f = result[0]
        assert abs(f["p_positive"] - 0.55) < 0.001
        assert abs(f["p_negative"] - 0.25) < 0.001
        assert abs(f["p_neutral"] - 0.20) < 0.001

    @pytest.mark.asyncio
    async def test_multiple_vectors_all_returned(self, db):
        from app.services.forecast_read_service import get_forecasts_for_target
        await _seed_vector(db, entity_key="MULTI1", forecast_type="thesis_strengthening", horizon_days=30)
        await _seed_vector(db, entity_key="MULTI1", forecast_type="risk_emergence", horizon_days=90)
        await _seed_vector(db, entity_key="MULTI1", forecast_type="regime_transition", horizon_days=180)

        result = await get_forecasts_for_target(db, "company", "MULTI1")
        assert len(result) == 3

    @pytest.mark.asyncio
    async def test_facet_has_forecasts_true_when_populated(self, db):
        from app.services.forecast_read_service import get_forecast_facet_for_ticker
        await _seed_vector(db, entity_key="POP2")

        result = await get_forecast_facet_for_ticker(db, "POP2")
        assert result["has_forecasts"] is True
        assert len(result["forecasts"]) == 1


# ---------------------------------------------------------------------------
# 3. Expired forecasts filtered
# ---------------------------------------------------------------------------

class TestExpiredFiltered:
    @pytest.mark.asyncio
    async def test_expired_vector_not_returned(self, db):
        from app.services.forecast_read_service import get_forecasts_for_target
        await _seed_vector(db, entity_key="EXP1", expired=True)

        result = await get_forecasts_for_target(db, "company", "EXP1")
        assert result == []

    @pytest.mark.asyncio
    async def test_expired_excluded_fresh_included(self, db):
        from app.services.forecast_read_service import get_forecasts_for_target
        await _seed_vector(db, entity_key="EXPFRESH", forecast_type="thesis_strengthening",
                           horizon_days=30, expired=True)
        await _seed_vector(db, entity_key="EXPFRESH", forecast_type="risk_emergence",
                           horizon_days=90, expired=False)

        result = await get_forecasts_for_target(db, "company", "EXPFRESH")
        assert len(result) == 1
        assert result[0]["forecast_type"] == "risk_emergence"

    @pytest.mark.asyncio
    async def test_facet_has_forecasts_false_when_all_expired(self, db):
        from app.services.forecast_read_service import get_forecast_facet_for_ticker
        await _seed_vector(db, entity_key="ALLEXP", expired=True)

        result = await get_forecast_facet_for_ticker(db, "ALLEXP")
        assert result["has_forecasts"] is False


# ---------------------------------------------------------------------------
# 4. Invalid forecasts filtered (empty why / empty invalidators / bad type)
# ---------------------------------------------------------------------------

class TestInvalidFiltered:
    @pytest.mark.asyncio
    async def test_empty_why_filtered(self, db):
        from app.services.forecast_read_service import get_forecasts_for_target
        await _seed_vector(db, entity_key="EMPTYWHY", why="")

        result = await get_forecasts_for_target(db, "company", "EMPTYWHY")
        assert result == []

    @pytest.mark.asyncio
    async def test_whitespace_why_filtered(self, db):
        from app.services.forecast_read_service import get_forecasts_for_target
        await _seed_vector(db, entity_key="SPACEWHY", why="   \n  ")

        result = await get_forecasts_for_target(db, "company", "SPACEWHY")
        assert result == []

    @pytest.mark.asyncio
    async def test_empty_invalidators_filtered(self, db):
        from app.services.forecast_read_service import get_forecasts_for_target
        await _seed_vector(db, entity_key="NOINVAL", invalidators=[])

        result = await get_forecasts_for_target(db, "company", "NOINVAL")
        assert result == []

    @pytest.mark.asyncio
    async def test_unsupported_forecast_type_filtered(self, db):
        from app.services.forecast_read_service import get_forecasts_for_target
        await _seed_vector(db, entity_key="BADTYPE", forecast_type="not_a_real_type")

        result = await get_forecasts_for_target(db, "company", "BADTYPE")
        assert result == []

    @pytest.mark.asyncio
    async def test_unsupported_horizon_filtered(self, db):
        from app.services.forecast_read_service import get_forecasts_for_target
        await _seed_vector(db, entity_key="BADHORIZON", horizon_days=45)

        result = await get_forecasts_for_target(db, "company", "BADHORIZON")
        assert result == []


# ---------------------------------------------------------------------------
# 5. Disclaimer always present
# ---------------------------------------------------------------------------

class TestDisclaimerAlwaysPresent:
    @pytest.mark.asyncio
    async def test_disclaimer_on_every_forecast_item(self, db):
        from app.services.forecast_read_service import get_forecasts_for_target
        from app.services.forecast_constants import MANDATORY_DISCLAIMER
        await _seed_vector(db, entity_key="DISC1", forecast_type="thesis_strengthening", horizon_days=30)
        await _seed_vector(db, entity_key="DISC1", forecast_type="risk_emergence", horizon_days=90)

        result = await get_forecasts_for_target(db, "company", "DISC1")
        assert len(result) == 2
        for f in result:
            assert f["disclaimer"] == MANDATORY_DISCLAIMER

    @pytest.mark.asyncio
    async def test_facet_level_disclaimer_verbatim(self, db):
        from app.services.forecast_read_service import get_forecast_facet_for_ticker
        from app.services.forecast_constants import MANDATORY_DISCLAIMER
        await _seed_vector(db, entity_key="DISCF1")

        result = await get_forecast_facet_for_ticker(db, "DISCF1")
        assert result["disclaimer"] == MANDATORY_DISCLAIMER

    @pytest.mark.asyncio
    async def test_disclaimer_present_even_with_no_forecasts(self, db):
        from app.services.forecast_read_service import get_forecast_facet_for_ticker
        from app.services.forecast_constants import MANDATORY_DISCLAIMER
        result = await get_forecast_facet_for_ticker(db, "EMPTYDISC")
        assert result["disclaimer"] == MANDATORY_DISCLAIMER

    @pytest.mark.asyncio
    async def test_disclaimer_not_empty_string(self, db):
        from app.services.forecast_read_service import get_forecast_facet_for_ticker
        result = await get_forecast_facet_for_ticker(db, "DISCCHECK")
        assert result["disclaimer"]
        assert len(result["disclaimer"]) > 20


# ---------------------------------------------------------------------------
# 6. No rebuild during reads (AST + runtime)
# ---------------------------------------------------------------------------

_SVC_PATH = (
    pathlib.Path(__file__).parent.parent.parent
    / "app" / "services" / "forecast_read_service.py"
)


def _load_svc_ast() -> ast.Module:
    return ast.parse(_SVC_PATH.read_text())


class TestNoRebuildDuringRead:
    def test_no_feature_builder_import(self):
        tree = _load_svc_ast()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                assert "forecast_feature_builder" not in module, (
                    "forecast_feature_builder must not be imported by read service"
                )

    def test_no_probability_engine_import(self):
        tree = _load_svc_ast()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                assert "forecast_probability_engine" not in module, (
                    "forecast_probability_engine must not be imported by read service"
                )

    def test_no_invalidation_service_import(self):
        tree = _load_svc_ast()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                assert "forecast_invalidation_service" not in module, (
                    "forecast_invalidation_service must not be imported by read service"
                )

    @pytest.mark.asyncio
    async def test_read_does_not_write_new_rows(self, db):
        from app.services.forecast_read_service import get_forecast_facet_for_ticker
        from app.db.models import ForecastVector
        from sqlalchemy import select, func

        # No vectors seeded
        count_before_stmt = select(func.count()).select_from(ForecastVector)
        before = int((await db.execute(count_before_stmt)).scalar_one() or 0)

        await get_forecast_facet_for_ticker(db, "NOWRITE")

        count_after_stmt = select(func.count()).select_from(ForecastVector)
        after = int((await db.execute(count_after_stmt)).scalar_one() or 0)
        assert after == before


# ---------------------------------------------------------------------------
# 7. No conviction / recommendation imports (AST)
# ---------------------------------------------------------------------------

_FORBIDDEN_FRAGMENTS = (
    "conviction",
    "recommendation",
    "delivery_ledger",
    "notifications",
    "notification_service",
    "audit_log",
    "forecast_invalidation",
    "forecast_feature_builder",
    "forecast_probability_engine",
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
                for fragment in _FORBIDDEN_FRAGMENTS:
                    assert fragment not in module, (
                        f"Forbidden import fragment {fragment!r} found in module {module!r}"
                    )

    def test_no_forbidden_class_imports(self):
        tree = _load_svc_ast()
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                for alias in getattr(node, "names", []):
                    name = alias.name or ""
                    for cls in _FORBIDDEN_CLASS_NAMES:
                        assert cls not in name, (
                            f"Forbidden class import {cls!r} found"
                        )


# ---------------------------------------------------------------------------
# 8. No source-table writes (AST)
# ---------------------------------------------------------------------------

_SOURCE_TABLE_NAMES = (
    "company_dossier", "CompanyDossier",
    "dossier_core_debate", "DossierCoreDebate",
    "dossier_failure_mode", "DossierFailureMode",
    "historical_analogs", "HistoricalAnalog",
    "thesis_versions", "ThesisVersion",
    "similarity_edge", "SimilarityEdge",
)


class TestNoSourceTableWrites:
    def test_no_source_table_imports(self):
        tree = _load_svc_ast()
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                module = (getattr(node, "module", "") or "")
                for name in getattr(node, "names", []):
                    full = f"{module}.{name.name}"
                    for tbl in _SOURCE_TABLE_NAMES:
                        assert tbl not in full, (
                            f"Source table reference {tbl!r} found in import"
                        )

    def test_no_session_add_in_read_service(self):
        src = _SVC_PATH.read_text()
        assert "session.add(" not in src, (
            "session.add() must not appear in the read service"
        )

    def test_no_session_delete_in_read_service(self):
        src = _SVC_PATH.read_text()
        assert "session.delete(" not in src, (
            "session.delete() must not appear in the read service"
        )


# ---------------------------------------------------------------------------
# 9. get_forecasts_for_target entity filtering
# ---------------------------------------------------------------------------

class TestEntityFiltering:
    @pytest.mark.asyncio
    async def test_only_returns_matching_entity_type(self, db):
        from app.services.forecast_read_service import get_forecasts_for_target
        await _seed_vector(db, entity_type="company", entity_key="CO1")
        await _seed_vector(db, entity_type="failure_mode", entity_key="FM1")

        company_results = await get_forecasts_for_target(db, "company", "CO1")
        fm_results = await get_forecasts_for_target(db, "failure_mode", "FM1")

        assert all(f["vector_id"] is not None for f in company_results)
        assert len(company_results) == 1
        assert len(fm_results) == 1

    @pytest.mark.asyncio
    async def test_only_returns_matching_entity_key(self, db):
        from app.services.forecast_read_service import get_forecasts_for_target
        await _seed_vector(db, entity_key="TICK1")
        await _seed_vector(db, entity_key="TICK2", forecast_type="risk_emergence")

        result = await get_forecasts_for_target(db, "company", "TICK1")
        assert len(result) == 1
        assert result[0]["vector_id"] is not None

    @pytest.mark.asyncio
    async def test_get_forecasts_for_ticker_is_company_shorthand(self, db):
        from app.services.forecast_read_service import (
            get_forecasts_for_target,
            get_forecasts_for_ticker,
        )
        await _seed_vector(db, entity_type="company", entity_key="SHORT1")

        via_target = await get_forecasts_for_target(db, "company", "SHORT1")
        via_ticker = await get_forecasts_for_ticker(db, "SHORT1")
        assert len(via_target) == len(via_ticker)
        assert via_target[0]["vector_id"] == via_ticker[0]["vector_id"]


# ---------------------------------------------------------------------------
# 10. why field — newline-joined string split back to list
# ---------------------------------------------------------------------------

class TestWhySplitting:
    @pytest.mark.asyncio
    async def test_why_is_list_in_output(self, db):
        from app.services.forecast_read_service import get_forecasts_for_target
        multiline_why = "First reason.\nSecond reason.\nThird reason."
        await _seed_vector(db, entity_key="SPLIT1", why=multiline_why)

        result = await get_forecasts_for_target(db, "company", "SPLIT1")
        assert len(result) == 1
        why = result[0]["why"]
        assert isinstance(why, list)
        assert len(why) == 3

    @pytest.mark.asyncio
    async def test_single_line_why_is_list_with_one_element(self, db):
        from app.services.forecast_read_service import get_forecasts_for_target
        await _seed_vector(db, entity_key="SPLIT2", why="Single line reason.")

        result = await get_forecasts_for_target(db, "company", "SPLIT2")
        why = result[0]["why"]
        assert isinstance(why, list)
        assert len(why) == 1
        assert why[0] == "Single line reason."


# ---------------------------------------------------------------------------
# 11. Ordering
# ---------------------------------------------------------------------------

class TestOrdering:
    @pytest.mark.asyncio
    async def test_ordered_by_horizon_days_ascending(self, db):
        from app.services.forecast_read_service import get_forecasts_for_target
        await _seed_vector(db, entity_key="ORD1", forecast_type="thesis_strengthening", horizon_days=180)
        await _seed_vector(db, entity_key="ORD1", forecast_type="risk_emergence", horizon_days=30)
        await _seed_vector(db, entity_key="ORD1", forecast_type="catalyst_realization", horizon_days=90)

        result = await get_forecasts_for_target(db, "company", "ORD1")
        horizons = [f["horizon_days"] for f in result]
        assert horizons == sorted(horizons)

    @pytest.mark.asyncio
    async def test_same_horizon_ordered_by_forecast_type(self, db):
        from app.services.forecast_read_service import get_forecasts_for_target
        await _seed_vector(db, entity_key="ORD2", forecast_type="thesis_weakening", horizon_days=30)
        await _seed_vector(db, entity_key="ORD2", forecast_type="catalyst_realization", horizon_days=30)
        await _seed_vector(db, entity_key="ORD2", forecast_type="risk_emergence", horizon_days=30)

        result = await get_forecasts_for_target(db, "company", "ORD2")
        types = [f["forecast_type"] for f in result]
        assert types == sorted(types)


# ---------------------------------------------------------------------------
# 12. Null-session safety
# ---------------------------------------------------------------------------

class TestNullSessionSafety:
    @pytest.mark.asyncio
    async def test_get_forecasts_for_target_null(self):
        from app.services.forecast_read_service import get_forecasts_for_target
        result = await get_forecasts_for_target(None, "company", "NULLS")
        assert result == []

    @pytest.mark.asyncio
    async def test_get_forecasts_for_ticker_null(self):
        from app.services.forecast_read_service import get_forecasts_for_ticker
        result = await get_forecasts_for_ticker(None, "NULLS")
        assert result == []

    @pytest.mark.asyncio
    async def test_get_forecast_facet_null_session(self):
        from app.services.forecast_read_service import get_forecast_facet_for_ticker
        from app.services.forecast_constants import MANDATORY_DISCLAIMER
        result = await get_forecast_facet_for_ticker(None, "NULLTK")
        assert result["has_forecasts"] is False
        assert result["forecasts"] == []
        assert result["disclaimer"] == MANDATORY_DISCLAIMER
        assert result["ticker"] == "NULLTK"

    @pytest.mark.asyncio
    async def test_facet_null_session_always_has_disclaimer(self):
        from app.services.forecast_read_service import get_forecast_facet_for_ticker
        from app.services.forecast_constants import MANDATORY_DISCLAIMER
        result = await get_forecast_facet_for_ticker(None, "NULLDISC")
        assert result["disclaimer"] == MANDATORY_DISCLAIMER


# ---------------------------------------------------------------------------
# 13. Facet shape completeness
# ---------------------------------------------------------------------------

class TestFacetShape:
    @pytest.mark.asyncio
    async def test_facet_has_all_top_level_keys(self, db):
        from app.services.forecast_read_service import get_forecast_facet_for_ticker
        result = await get_forecast_facet_for_ticker(db, "SHAPE1")
        for key in ("has_forecasts", "ticker", "forecasts", "disclaimer"):
            assert key in result, f"Missing facet key: {key}"

    @pytest.mark.asyncio
    async def test_facet_ticker_preserved(self, db):
        from app.services.forecast_read_service import get_forecast_facet_for_ticker
        result = await get_forecast_facet_for_ticker(db, "MYTICK")
        assert result["ticker"] == "MYTICK"

    @pytest.mark.asyncio
    async def test_facet_forecasts_is_list(self, db):
        from app.services.forecast_read_service import get_forecast_facet_for_ticker
        result = await get_forecast_facet_for_ticker(db, "LISTCK")
        assert isinstance(result["forecasts"], list)

    @pytest.mark.asyncio
    async def test_forecast_item_matches_spec_shape(self, db):
        from app.services.forecast_read_service import get_forecast_facet_for_ticker
        await _seed_vector(db, entity_key="SPEC1")
        result = await get_forecast_facet_for_ticker(db, "SPEC1")
        assert result["has_forecasts"] is True
        f = result["forecasts"][0]
        # Spec-required fields
        assert "forecast_type" in f
        assert "horizon_days" in f
        assert "p_positive" in f
        assert "p_negative" in f
        assert "p_neutral" in f
        assert "confidence_label" in f
        assert "why" in f and isinstance(f["why"], list)
        assert "invalidators" in f and isinstance(f["invalidators"], list)
        assert "disclaimer" in f
