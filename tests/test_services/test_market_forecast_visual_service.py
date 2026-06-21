"""
Tests — Market + Forecast Visual Service, Phase 19 · Slice 4.

Covers all 8 visual types: valid spec, blocked (no data), gate-off, null-session,
tier assignment, explainability enforcement, and AST safety.
"""

from __future__ import annotations

import ast
import pathlib
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

_ROOT = pathlib.Path(__file__).parent.parent.parent
_SRC  = _ROOT / "app" / "services" / "market_forecast_visual_service.py"

_ENTITY = "AAPL"


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


async def _seed_memory(db, ticker=_ENTITY, count=3):
    from app.db.models import MemoryEntry
    base = datetime.now(timezone.utc)
    for i in range(count):
        db.add(MemoryEntry(
            id=str(uuid.uuid4()), ticker=ticker,
            entry_type="analysis", content=f"event {i}",
            created_at=base - timedelta(days=i),
        ))
    await db.flush()


async def _seed_forecast(db, entity_key=_ENTITY, count=3, forecast_type="thesis_strengthening"):
    from app.db.models import ForecastVector
    base = datetime.now(timezone.utc)
    for i in range(count):
        db.add(ForecastVector(
            id=str(uuid.uuid4()), entity_type="company", entity_key=entity_key,
            horizon="near_term", horizon_days=30, forecast_type=forecast_type,
            p_positive=0.5, p_negative=0.3, p_neutral=0.2,
            confidence_band_low=0.4, confidence_band_high=0.6,
            built_at=base - timedelta(days=i),
            expires_at=base + timedelta(days=30),
        ))
    await db.flush()


# ===================================================================
# § Market visuals — valid
# ===================================================================

class TestMarketVisualsValid:
    @pytest.mark.asyncio
    async def test_price_chart_valid(self, db):
        from app.services.market_forecast_visual_service import build_price_chart_spec
        await _seed_memory(db)
        spec = await build_price_chart_spec(db, entity_key=_ENTITY, run_override=True)
        assert spec is not None
        assert spec["visual_type"] == "price_chart"
        assert spec["rendering_tier"] == "json"
        assert spec["explanation_valid"] is True

    @pytest.mark.asyncio
    async def test_performance_chart_valid(self, db):
        from app.services.market_forecast_visual_service import build_performance_chart_spec
        await _seed_memory(db)
        spec = await build_performance_chart_spec(db, entity_key=_ENTITY, run_override=True)
        assert spec is not None
        assert spec["visual_type"] == "performance_chart"
        assert spec["explanation_valid"] is True

    @pytest.mark.asyncio
    async def test_volatility_chart_valid(self, db):
        from app.services.market_forecast_visual_service import build_volatility_chart_spec
        await _seed_forecast(db)
        spec = await build_volatility_chart_spec(db, entity_key=_ENTITY, run_override=True)
        assert spec is not None
        assert spec["visual_type"] == "volatility_overlay"
        assert spec["explanation_valid"] is True
        assert "band_width" in spec["data"]

    @pytest.mark.asyncio
    async def test_evidence_timeline_valid(self, db):
        from app.services.market_forecast_visual_service import build_evidence_timeline_spec
        await _seed_memory(db)
        spec = await build_evidence_timeline_spec(db, entity_key=_ENTITY, run_override=True)
        assert spec is not None
        assert spec["visual_type"] == "evidence_timeline"
        assert spec["rendering_tier"] == "svg"
        assert spec["explanation_valid"] is True


# ===================================================================
# § Forecast visuals — valid
# ===================================================================

class TestForecastVisualsValid:
    @pytest.mark.asyncio
    async def test_distribution_valid(self, db):
        from app.services.market_forecast_visual_service import build_distribution_spec
        await _seed_forecast(db)
        spec = await build_distribution_spec(db, entity_key=_ENTITY, run_override=True)
        assert spec is not None
        assert spec["visual_type"] == "forecast_distribution"
        assert spec["rendering_tier"] == "json"
        assert spec["explanation_valid"] is True
        assert spec["data"]["p_positive"] == 0.5

    @pytest.mark.asyncio
    async def test_outcome_tree_valid(self, db):
        from app.services.market_forecast_visual_service import build_outcome_tree_spec
        await _seed_forecast(db)
        spec = await build_outcome_tree_spec(db, entity_key=_ENTITY, run_override=True)
        assert spec is not None
        assert spec["visual_type"] == "outcome_tree"
        assert spec["rendering_tier"] == "svg"
        assert spec["explanation_valid"] is True
        assert len(spec["data"]["branches"]) == 3

    @pytest.mark.asyncio
    async def test_confidence_band_valid(self, db):
        from app.services.market_forecast_visual_service import build_confidence_band_spec
        await _seed_forecast(db)
        spec = await build_confidence_band_spec(db, entity_key=_ENTITY, run_override=True)
        assert spec is not None
        assert spec["visual_type"] == "confidence_band"
        assert spec["explanation_valid"] is True

    @pytest.mark.asyncio
    async def test_forecast_evolution_valid(self, db):
        from app.services.market_forecast_visual_service import build_forecast_evolution_spec
        await _seed_forecast(db)
        spec = await build_forecast_evolution_spec(db, entity_key=_ENTITY, run_override=True)
        assert spec is not None
        assert spec["visual_type"] == "forecast_evolution"
        assert spec["explanation_valid"] is True
        assert len(spec["data"]["series"]) == 3


# ===================================================================
# § Blocked specs (no upstream data → blocked, not None)
# ===================================================================

class TestBlockedSpecs:
    @pytest.mark.asyncio
    async def test_distribution_no_data_blocked(self, db):
        from app.services.market_forecast_visual_service import build_distribution_spec
        spec = await build_distribution_spec(db, entity_key="NODATA", run_override=True)
        assert spec is not None
        assert spec["explanation_valid"] is False
        assert "supporting_evidence" in spec["blocked_reason"]

    @pytest.mark.asyncio
    async def test_price_chart_no_data_blocked(self, db):
        from app.services.market_forecast_visual_service import build_price_chart_spec
        spec = await build_price_chart_spec(db, entity_key="NODATA", run_override=True)
        assert spec is not None
        assert spec["explanation_valid"] is False

    @pytest.mark.asyncio
    async def test_outcome_tree_no_data_blocked(self, db):
        from app.services.market_forecast_visual_service import build_outcome_tree_spec
        spec = await build_outcome_tree_spec(db, entity_key="NODATA", run_override=True)
        assert spec is not None
        assert spec["explanation_valid"] is False


# ===================================================================
# § Gate off → None
# ===================================================================

class TestGateOff:
    @pytest.mark.asyncio
    async def test_price_chart_gate_off(self, db):
        from app.services.market_forecast_visual_service import build_price_chart_spec
        await _seed_memory(db)
        spec = await build_price_chart_spec(db, entity_key=_ENTITY, run_override=False)
        assert spec is None

    @pytest.mark.asyncio
    async def test_distribution_gate_off(self, db):
        from app.services.market_forecast_visual_service import build_distribution_spec
        await _seed_forecast(db)
        spec = await build_distribution_spec(db, entity_key=_ENTITY, run_override=False)
        assert spec is None

    @pytest.mark.asyncio
    async def test_evidence_timeline_gate_off(self, db):
        from app.services.market_forecast_visual_service import build_evidence_timeline_spec
        await _seed_memory(db)
        spec = await build_evidence_timeline_spec(db, entity_key=_ENTITY, run_override=False)
        assert spec is None


# ===================================================================
# § Null session → None
# ===================================================================

class TestNullSession:
    @pytest.mark.asyncio
    async def test_all_functions_null_session(self):
        from app.services import market_forecast_visual_service as svc
        fns = [
            svc.build_price_chart_spec,
            svc.build_performance_chart_spec,
            svc.build_volatility_chart_spec,
            svc.build_evidence_timeline_spec,
            svc.build_distribution_spec,
            svc.build_outcome_tree_spec,
            svc.build_confidence_band_spec,
            svc.build_forecast_evolution_spec,
        ]
        for fn in fns:
            result = await fn(None, entity_key=_ENTITY, run_override=True)
            assert result is None, f"{fn.__name__} not null-session safe"


# ===================================================================
# § Tier assignment
# ===================================================================

class TestTierAssignment:
    @pytest.mark.asyncio
    async def test_json_tier_visuals(self, db):
        from app.services.market_forecast_visual_service import (
            build_price_chart_spec, build_performance_chart_spec,
            build_volatility_chart_spec, build_distribution_spec,
            build_confidence_band_spec, build_forecast_evolution_spec,
        )
        await _seed_memory(db)
        await _seed_forecast(db)
        for fn in (build_price_chart_spec, build_performance_chart_spec,
                   build_volatility_chart_spec, build_distribution_spec,
                   build_confidence_band_spec, build_forecast_evolution_spec):
            spec = await fn(db, entity_key=_ENTITY, run_override=True)
            assert spec["rendering_tier"] == "json", f"{fn.__name__} wrong tier"

    @pytest.mark.asyncio
    async def test_svg_tier_visuals(self, db):
        from app.services.market_forecast_visual_service import (
            build_evidence_timeline_spec, build_outcome_tree_spec,
        )
        await _seed_memory(db)
        await _seed_forecast(db)
        for fn in (build_evidence_timeline_spec, build_outcome_tree_spec):
            spec = await fn(db, entity_key=_ENTITY, run_override=True)
            assert spec["rendering_tier"] == "svg", f"{fn.__name__} wrong tier"


# ===================================================================
# § Explainability enforced
# ===================================================================

class TestExplainabilityEnforced:
    @pytest.mark.asyncio
    async def test_valid_spec_has_all_three_fields(self, db):
        from app.services.market_forecast_visual_service import build_distribution_spec
        await _seed_forecast(db)
        spec = await build_distribution_spec(db, entity_key=_ENTITY, run_override=True)
        exp = spec["explanation"]
        assert exp["what_am_i_looking_at"]
        assert exp["why_does_it_matter"]
        assert exp["supporting_evidence"]


# ===================================================================
# § AST safety
# ===================================================================

class TestASTSafety:
    def _source(self) -> str:
        return _SRC.read_text()

    def _tree(self) -> ast.Module:
        return ast.parse(self._source())

    def test_module_importable(self):
        import app.services.market_forecast_visual_service  # noqa: F401

    def test_no_banned_phrases(self):
        tree = self._tree()
        exempt_ids: set = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                                 ast.ClassDef, ast.Module)):
                body = getattr(node, "body", [])
                if (body and isinstance(body[0], ast.Expr)
                        and isinstance(body[0].value, ast.Constant)):
                    exempt_ids.add(id(body[0].value))

        banned = [
            "buy", "sell",
            "overweight", "underweight", "recommend",
            "target price", "position size",
            "take a position", "enter a trade", "exit a trade",
            "place an order", "execute",
            "short", "long position",
            "go long", "go short",
            "open a position", "close a position",
        ]
        violations: list = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if id(node) in exempt_ids:
                    continue
                low = node.value.lower()
                for phrase in banned:
                    if phrase in low:
                        violations.append(
                            f"Line ~{getattr(node, 'lineno', '?')}: "
                            f"'{phrase}' in: {node.value[:80]!r}"
                        )
        assert not violations, "\n".join(violations)

    def test_no_upstream_truth_imports(self):
        tree = self._tree()
        banned_modules = [
            "forecast_repo", "decision_repo", "scenario_repo",
            "similarity_repo", "user_learning_repo",
            "personal_experience_repo", "conviction", "order",
            "execution", "stance",
        ]
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                mod = node.module
                for banned in banned_modules:
                    assert banned not in mod, (
                        f"Banned import from {mod} (contains '{banned}')"
                    )

    def test_no_mutation_patterns(self):
        source = self._source()
        for pattern in [".update(", ".delete(", "session.add", "DELETE FROM", "UPDATE "]:
            assert pattern not in source, (
                f"Visual service must be read-only — found '{pattern}'"
            )
