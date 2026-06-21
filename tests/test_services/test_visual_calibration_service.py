"""
Tests — Visual Calibration Service, Phase 19 · Slice 11.

Covers all 5 metrics, insufficient samples, summary aggregation,
null-session behavior, append-only, and AST safety.
"""

from __future__ import annotations

import ast
import pathlib

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

_ROOT = pathlib.Path(__file__).parent.parent.parent
_SRC  = _ROOT / "app" / "services" / "visual_calibration_service.py"

_USER = "u-vc-1"


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


async def _seed_shadow_events(db, user_id, count, *, valid_count=None, cache_hits=0,
                              blocked_count=0, generation_ms=100):
    from app.db.repositories.visual_intelligence_repo import add_visual_event
    if valid_count is None:
        valid_count = count
    for i in range(count):
        await add_visual_event(
            db, user_id=user_id, visual_type=f"v{i}",
            entity_key=f"E{i}", rendering_tier="json",
            explanation_valid=i < valid_count,
            generation_ms=generation_ms + i * 10,
            cache_hit=i < cache_hits,
            blocked_reason="blocked" if i >= (count - blocked_count) else "",
            run_reason="shadow",
        )
    await db.flush()


async def _seed_ai_logs(db, user_id, count, *, passed_count=None):
    from app.db.repositories.visual_intelligence_repo import add_ai_visual_log
    if passed_count is None:
        passed_count = count
    for i in range(count):
        await add_ai_visual_log(
            db, user_id=user_id, visual_type=f"ai{i}",
            entity_key=f"E{i}", prompt_hash=f"h{i}",
            validation_passed=i < passed_count,
        )
    await db.flush()


# ===================================================================
# § record_visual_outcome
# ===================================================================

class TestRecordVisualOutcome:
    @pytest.mark.asyncio
    async def test_records_row(self, db):
        from app.services.visual_calibration_service import record_visual_outcome
        row = await record_visual_outcome(
            db, user_id=_USER, visual_type="price_chart", entity_key="AAPL",
            explanation_valid=True, generation_ms=150, run_override=True,
        )
        assert row is not None
        assert row.run_reason == "calibration"

    @pytest.mark.asyncio
    async def test_flag_off(self, db):
        from app.services.visual_calibration_service import record_visual_outcome
        assert await record_visual_outcome(
            db, user_id=_USER, run_override=False,
        ) is None

    @pytest.mark.asyncio
    async def test_null_session(self):
        from app.services.visual_calibration_service import record_visual_outcome
        assert await record_visual_outcome(
            None, user_id=_USER, run_override=True,
        ) is None


# ===================================================================
# § calculate_explainability_coverage
# ===================================================================

class TestExplainabilityCoverage:
    @pytest.mark.asyncio
    async def test_computes_coverage(self, db):
        from app.services.visual_calibration_service import calculate_explainability_coverage
        await _seed_shadow_events(db, _USER, 20, valid_count=15)
        result = await calculate_explainability_coverage(db, user_id=_USER, run_override=True)
        assert result["sufficient_samples"] is True
        assert result["coverage"] == 0.75
        assert result["valid_count"] == 15
        assert result["blocked_count"] == 5

    @pytest.mark.asyncio
    async def test_insufficient_samples(self, db):
        from app.services.visual_calibration_service import calculate_explainability_coverage
        await _seed_shadow_events(db, "u-few", 5, valid_count=3)
        result = await calculate_explainability_coverage(db, user_id="u-few", run_override=True)
        assert result["sufficient_samples"] is False
        assert result["coverage"] is None

    @pytest.mark.asyncio
    async def test_flag_off(self, db):
        from app.services.visual_calibration_service import calculate_explainability_coverage
        result = await calculate_explainability_coverage(db, run_override=False)
        assert result["sufficient_samples"] is False


# ===================================================================
# § calculate_cache_hit_rate
# ===================================================================

class TestCacheHitRate:
    @pytest.mark.asyncio
    async def test_computes_rate(self, db):
        from app.services.visual_calibration_service import calculate_cache_hit_rate
        await _seed_shadow_events(db, _USER, 25, cache_hits=10)
        result = await calculate_cache_hit_rate(db, user_id=_USER, run_override=True)
        assert result["sufficient_samples"] is True
        assert result["hit_rate"] == 0.4
        assert result["cache_hits"] == 10

    @pytest.mark.asyncio
    async def test_insufficient_samples(self, db):
        from app.services.visual_calibration_service import calculate_cache_hit_rate
        await _seed_shadow_events(db, "u-few2", 10, cache_hits=5)
        result = await calculate_cache_hit_rate(db, user_id="u-few2", run_override=True)
        assert result["sufficient_samples"] is False
        assert result["hit_rate"] is None


# ===================================================================
# § calculate_ai_validation_pass_rate
# ===================================================================

class TestAIValidationPassRate:
    @pytest.mark.asyncio
    async def test_computes_rate(self, db):
        from app.services.visual_calibration_service import calculate_ai_validation_pass_rate
        await _seed_ai_logs(db, _USER, 10, passed_count=8)
        result = await calculate_ai_validation_pass_rate(db, user_id=_USER, run_override=True)
        assert result["sufficient_samples"] is True
        assert result["pass_rate"] == 0.8
        assert result["passed"] == 8

    @pytest.mark.asyncio
    async def test_insufficient_samples(self, db):
        from app.services.visual_calibration_service import calculate_ai_validation_pass_rate
        await _seed_ai_logs(db, "u-few3", 3, passed_count=2)
        result = await calculate_ai_validation_pass_rate(db, user_id="u-few3", run_override=True)
        assert result["sufficient_samples"] is False
        assert result["pass_rate"] is None


# ===================================================================
# § calculate_generation_latency
# ===================================================================

class TestGenerationLatency:
    @pytest.mark.asyncio
    async def test_computes_p95(self, db):
        from app.services.visual_calibration_service import calculate_generation_latency
        await _seed_shadow_events(db, _USER, 25, generation_ms=100)
        result = await calculate_generation_latency(db, user_id=_USER, run_override=True)
        assert result["sufficient_samples"] is True
        assert result["p95_ms"] is not None
        assert result["p95_ms"] >= 100
        assert result["sample_count"] == 25

    @pytest.mark.asyncio
    async def test_insufficient_samples(self, db):
        from app.services.visual_calibration_service import calculate_generation_latency
        await _seed_shadow_events(db, "u-few4", 10, generation_ms=50)
        result = await calculate_generation_latency(db, user_id="u-few4", run_override=True)
        assert result["sufficient_samples"] is False
        assert result["p95_ms"] is None


# ===================================================================
# § calculate_blocked_visual_rate
# ===================================================================

class TestBlockedVisualRate:
    @pytest.mark.asyncio
    async def test_computes_rate(self, db):
        from app.services.visual_calibration_service import calculate_blocked_visual_rate
        await _seed_shadow_events(db, _USER, 20, blocked_count=4)
        result = await calculate_blocked_visual_rate(db, user_id=_USER, run_override=True)
        assert result["sufficient_samples"] is True
        assert result["blocked_rate"] == 0.2
        assert result["blocked_count"] == 4

    @pytest.mark.asyncio
    async def test_insufficient_samples(self, db):
        from app.services.visual_calibration_service import calculate_blocked_visual_rate
        await _seed_shadow_events(db, "u-few5", 5, blocked_count=2)
        result = await calculate_blocked_visual_rate(db, user_id="u-few5", run_override=True)
        assert result["sufficient_samples"] is False
        assert result["blocked_rate"] is None


# ===================================================================
# § summarize_visual_calibration
# ===================================================================

class TestSummarizeVisualCalibration:
    @pytest.mark.asyncio
    async def test_aggregates_all_metrics(self, db):
        from app.services.visual_calibration_service import summarize_visual_calibration
        await _seed_shadow_events(db, _USER, 25, valid_count=20, cache_hits=10, blocked_count=3)
        await _seed_ai_logs(db, _USER, 10, passed_count=8)
        result = await summarize_visual_calibration(db, user_id=_USER, run_override=True)
        assert "explainability_coverage" in result
        assert "cache_hit_rate" in result
        assert "ai_validation_pass_rate" in result
        assert "generation_latency" in result
        assert "blocked_visual_rate" in result
        assert result["calibration_schema"] == 1
        assert "generated_at" in result

    @pytest.mark.asyncio
    async def test_flag_off(self, db):
        from app.services.visual_calibration_service import summarize_visual_calibration
        result = await summarize_visual_calibration(db, run_override=False)
        assert result["explainability_coverage"]["sufficient_samples"] is False
        assert result["calibration_schema"] == 1

    @pytest.mark.asyncio
    async def test_null_session(self):
        from app.services.visual_calibration_service import summarize_visual_calibration
        result = await summarize_visual_calibration(None, run_override=True)
        assert result["explainability_coverage"]["sufficient_samples"] is False


# ===================================================================
# § Null session
# ===================================================================

class TestNullSession:
    @pytest.mark.asyncio
    async def test_all_metrics_null_session(self):
        from app.services import visual_calibration_service as svc
        fns = [
            svc.calculate_explainability_coverage,
            svc.calculate_cache_hit_rate,
            svc.calculate_ai_validation_pass_rate,
            svc.calculate_generation_latency,
            svc.calculate_blocked_visual_rate,
            svc.summarize_visual_calibration,
        ]
        for fn in fns:
            result = await fn(None, run_override=True)
            assert result.get("sufficient_samples", False) is False or \
                result.get("calibration_schema") == 1, f"{fn.__name__} not null-safe"


# ===================================================================
# § AST safety
# ===================================================================

class TestASTSafety:
    def _source(self) -> str:
        return _SRC.read_text()

    def _tree(self) -> ast.Module:
        return ast.parse(self._source())

    def test_module_importable(self):
        import app.services.visual_calibration_service  # noqa: F401

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
            "similarity_repo", "user_learning_repo", "portfolio_repo",
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

    def test_append_only_no_update_delete(self):
        source = self._source()
        for pattern in [".update(", ".delete(", "DELETE FROM", "UPDATE "]:
            assert pattern not in source, (
                f"Calibration must be append-only — found '{pattern}'"
            )
