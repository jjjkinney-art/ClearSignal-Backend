"""
Tests — Personal Experience Calibration, Phase 18 · Slice 9.

Covers:
  1.  record_experience_outcome: engaged outcome stored
  2.  record_experience_outcome: ignored outcome stored
  3.  record_experience_outcome: run_reason is always calibration
  4.  record_experience_outcome: returns None when flag off
  5.  record_experience_outcome: returns None when session None
  6.  calculate_attention_accuracy: computes accuracy
  7.  calculate_attention_accuracy: insufficient samples
  8.  calculate_attention_accuracy: returns empty when flag off
  9.  calculate_attention_accuracy: returns empty when session None
  10. calculate_resume_accuracy: computes accuracy for resume surface
  11. calculate_resume_accuracy: insufficient samples
  12. calculate_resume_accuracy: returns empty when flag off
  13. calculate_explainability_coverage: computes coverage
  14. calculate_explainability_coverage: insufficient samples
  15. calculate_explainability_coverage: returns empty when flag off
  16. calculate_ranking_stability: computes stability
  17. calculate_ranking_stability: insufficient entities
  18. calculate_ranking_stability: returns empty when flag off
  19. calculate_ranking_stability: perfect stability (identical scores)
  20. calculate_novelty_effectiveness: computes effectiveness
  21. calculate_novelty_effectiveness: insufficient novel items
  22. calculate_novelty_effectiveness: returns empty when flag off
  23. summarize_experience_calibration: aggregates all metrics
  24. summarize_experience_calibration: returns empty when flag off
  25. summarize_experience_calibration: returns empty when session None
  26. AST: no banned phrases in source
  27. AST: no upstream truth-table imports
  28. AST: module is importable
  29. AST: append-only (no .update/.delete)
  30. Null-session: all async functions safe
"""

from __future__ import annotations

import ast
import pathlib

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

_ROOT = pathlib.Path(__file__).parent.parent.parent
_SRC  = _ROOT / "app" / "services" / "personal_experience_calibration_service.py"

_USER = "u-calib-test"


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
# Helpers — seed calibration events
# ---------------------------------------------------------------------------

async def _seed_calibration_events(db, user_id, count, engaged_count):
    from app.db.repositories.personal_experience_repo import add_experience_event
    for i in range(count):
        engaged = i < engaged_count
        await add_experience_event(
            db,
            user_id=user_id,
            surface="shadow",
            item_ref=f"item-{i}",
            entity_type="company",
            entity_key=f"TICK{i}",
            experience_score=0.7 if engaged else -0.3,
            explanation_text="calibration_engaged" if engaged else "calibration_ignored",
            explanation_valid=engaged,
            run_reason="calibration",
        )
    await db.flush()


async def _seed_shadow_events(db, user_id, items, valid_count=None):
    from app.db.repositories.personal_experience_repo import add_experience_event
    if valid_count is None:
        valid_count = len(items)
    for i, item in enumerate(items):
        await add_experience_event(
            db,
            user_id=user_id,
            surface="shadow",
            item_ref=item.get("item_ref", f"item-{i}"),
            entity_type=item.get("entity_type", "company"),
            entity_key=item.get("entity_key", f"TICK{i}"),
            experience_score=item.get("experience_score", 0.5),
            personal_relevance=item.get("personal_relevance", 0.5),
            explanation_valid=i < valid_count,
            run_reason="shadow",
        )
    await db.flush()


async def _seed_resume_calibration(db, user_id, count, engaged_count):
    from app.db.repositories.personal_experience_repo import add_experience_event
    for i in range(count):
        engaged = i < engaged_count
        await add_experience_event(
            db,
            user_id=user_id,
            surface="resume",
            item_ref=f"resume-{i}",
            entity_type="company",
            entity_key=f"RES{i}",
            experience_score=0.5,
            explanation_valid=engaged,
            run_reason="calibration",
        )
    await db.flush()


# ===================================================================
# § record_experience_outcome
# ===================================================================

class TestRecordExperienceOutcome:
    @pytest.mark.asyncio
    async def test_engaged_outcome(self, db):
        from app.services.personal_experience_calibration_service import record_experience_outcome
        row = await record_experience_outcome(
            db, user_id=_USER, surface="shadow", item_ref="AAPL",
            experience_score=0.7, observed_engagement=True, run_override=True,
        )
        assert row is not None
        assert row.run_reason == "calibration"
        assert row.explanation_valid is True
        assert row.experience_score > 0

    @pytest.mark.asyncio
    async def test_ignored_outcome(self, db):
        from app.services.personal_experience_calibration_service import record_experience_outcome
        row = await record_experience_outcome(
            db, user_id=_USER, surface="shadow", item_ref="MSFT",
            experience_score=0.5, observed_engagement=False, run_override=True,
        )
        assert row is not None
        assert row.run_reason == "calibration"
        assert row.explanation_valid is False
        assert row.experience_score < 0

    @pytest.mark.asyncio
    async def test_run_reason_always_calibration(self, db):
        from app.services.personal_experience_calibration_service import record_experience_outcome
        row = await record_experience_outcome(
            db, user_id=_USER, surface="brief", item_ref="GOOG",
            experience_score=0.8, observed_engagement=True, run_override=True,
        )
        assert row.run_reason == "calibration"

    @pytest.mark.asyncio
    async def test_returns_none_flag_off(self, db):
        from app.services.personal_experience_calibration_service import record_experience_outcome
        result = await record_experience_outcome(
            db, user_id=_USER, surface="shadow", item_ref="AAPL",
            run_override=False,
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_session_none(self):
        from app.services.personal_experience_calibration_service import record_experience_outcome
        result = await record_experience_outcome(
            None, user_id=_USER, surface="shadow", item_ref="AAPL",
            run_override=True,
        )
        assert result is None


# ===================================================================
# § calculate_attention_accuracy
# ===================================================================

class TestCalculateAttentionAccuracy:
    @pytest.mark.asyncio
    async def test_computes_accuracy(self, db):
        from app.services.personal_experience_calibration_service import calculate_attention_accuracy
        await _seed_calibration_events(db, _USER, count=10, engaged_count=7)
        result = await calculate_attention_accuracy(db, user_id=_USER, run_override=True)
        assert result["sufficient_samples"] is True
        assert result["accuracy"] == 0.7
        assert result["engaged_count"] == 7
        assert result["not_engaged_count"] == 3
        assert result["total_count"] == 10

    @pytest.mark.asyncio
    async def test_insufficient_samples(self, db):
        from app.services.personal_experience_calibration_service import calculate_attention_accuracy
        await _seed_calibration_events(db, "u-few", count=3, engaged_count=2)
        result = await calculate_attention_accuracy(db, user_id="u-few", run_override=True)
        assert result["sufficient_samples"] is False
        assert result["accuracy"] is None

    @pytest.mark.asyncio
    async def test_returns_empty_flag_off(self, db):
        from app.services.personal_experience_calibration_service import calculate_attention_accuracy
        result = await calculate_attention_accuracy(db, user_id=_USER, run_override=False)
        assert result["sufficient_samples"] is False

    @pytest.mark.asyncio
    async def test_returns_empty_session_none(self):
        from app.services.personal_experience_calibration_service import calculate_attention_accuracy
        result = await calculate_attention_accuracy(None, user_id=_USER, run_override=True)
        assert result["sufficient_samples"] is False


# ===================================================================
# § calculate_resume_accuracy
# ===================================================================

class TestCalculateResumeAccuracy:
    @pytest.mark.asyncio
    async def test_computes_resume_accuracy(self, db):
        from app.services.personal_experience_calibration_service import calculate_resume_accuracy
        await _seed_resume_calibration(db, _USER, count=6, engaged_count=4)
        result = await calculate_resume_accuracy(db, user_id=_USER, run_override=True)
        assert result["sufficient_samples"] is True
        assert abs(result["accuracy"] - 4 / 6) < 0.001
        assert result["engaged_count"] == 4

    @pytest.mark.asyncio
    async def test_insufficient_samples(self, db):
        from app.services.personal_experience_calibration_service import calculate_resume_accuracy
        await _seed_resume_calibration(db, "u-few-r", count=2, engaged_count=1)
        result = await calculate_resume_accuracy(db, user_id="u-few-r", run_override=True)
        assert result["sufficient_samples"] is False
        assert result["accuracy"] is None

    @pytest.mark.asyncio
    async def test_returns_empty_flag_off(self, db):
        from app.services.personal_experience_calibration_service import calculate_resume_accuracy
        result = await calculate_resume_accuracy(db, user_id=_USER, run_override=False)
        assert result["sufficient_samples"] is False


# ===================================================================
# § calculate_explainability_coverage
# ===================================================================

class TestCalculateExplainabilityCoverage:
    @pytest.mark.asyncio
    async def test_computes_coverage(self, db):
        from app.services.personal_experience_calibration_service import calculate_explainability_coverage
        items = [{"entity_key": f"T{i}"} for i in range(8)]
        await _seed_shadow_events(db, _USER, items, valid_count=6)
        result = await calculate_explainability_coverage(db, user_id=_USER, run_override=True)
        assert result["sufficient_samples"] is True
        assert result["coverage"] == 0.75
        assert result["valid_count"] == 6
        assert result["blocked_count"] == 2

    @pytest.mark.asyncio
    async def test_insufficient_samples(self, db):
        from app.services.personal_experience_calibration_service import calculate_explainability_coverage
        items = [{"entity_key": f"T{i}"} for i in range(3)]
        await _seed_shadow_events(db, "u-few-c", items, valid_count=2)
        result = await calculate_explainability_coverage(db, user_id="u-few-c", run_override=True)
        assert result["sufficient_samples"] is False
        assert result["coverage"] is None

    @pytest.mark.asyncio
    async def test_returns_empty_flag_off(self, db):
        from app.services.personal_experience_calibration_service import calculate_explainability_coverage
        result = await calculate_explainability_coverage(db, user_id=_USER, run_override=False)
        assert result["sufficient_samples"] is False


# ===================================================================
# § calculate_ranking_stability
# ===================================================================

class TestCalculateRankingStability:
    @pytest.mark.asyncio
    async def test_computes_stability(self, db):
        from app.services.personal_experience_calibration_service import calculate_ranking_stability
        from app.db.repositories.personal_experience_repo import add_experience_event
        for i in range(5):
            for score in [0.7, 0.8]:
                await add_experience_event(
                    db, user_id=_USER, surface="shadow",
                    item_ref=f"stab-{i}", entity_key=f"STAB{i}",
                    experience_score=score, run_reason="shadow",
                )
        await db.flush()
        result = await calculate_ranking_stability(db, user_id=_USER, run_override=True)
        assert result["sufficient_samples"] is True
        assert result["stability"] is not None
        assert 0.0 <= result["stability"] <= 1.0
        assert result["items_tracked"] == 5

    @pytest.mark.asyncio
    async def test_insufficient_entities(self, db):
        from app.services.personal_experience_calibration_service import calculate_ranking_stability
        from app.db.repositories.personal_experience_repo import add_experience_event
        for score in [0.5, 0.6]:
            await add_experience_event(
                db, user_id="u-few-s", surface="shadow",
                item_ref="single", entity_key="ONLY",
                experience_score=score, run_reason="shadow",
            )
        await db.flush()
        result = await calculate_ranking_stability(db, user_id="u-few-s", run_override=True)
        assert result["sufficient_samples"] is False
        assert result["stability"] is None

    @pytest.mark.asyncio
    async def test_returns_empty_flag_off(self, db):
        from app.services.personal_experience_calibration_service import calculate_ranking_stability
        result = await calculate_ranking_stability(db, user_id=_USER, run_override=False)
        assert result["sufficient_samples"] is False

    @pytest.mark.asyncio
    async def test_perfect_stability(self, db):
        from app.services.personal_experience_calibration_service import calculate_ranking_stability
        from app.db.repositories.personal_experience_repo import add_experience_event
        for i in range(5):
            for _ in range(3):
                await add_experience_event(
                    db, user_id="u-perfect", surface="shadow",
                    item_ref=f"perf-{i}", entity_key=f"PERF{i}",
                    experience_score=0.5, run_reason="shadow",
                )
        await db.flush()
        result = await calculate_ranking_stability(db, user_id="u-perfect", run_override=True)
        assert result["sufficient_samples"] is True
        assert result["stability"] == 1.0


# ===================================================================
# § calculate_novelty_effectiveness
# ===================================================================

class TestCalculateNoveltyEffectiveness:
    @pytest.mark.asyncio
    async def test_computes_effectiveness(self, db):
        from app.services.personal_experience_calibration_service import calculate_novelty_effectiveness
        from app.db.repositories.personal_experience_repo import add_experience_event
        uid = "u-novelty-eff"
        for i in range(4):
            await add_experience_event(
                db, user_id=uid, surface="shadow",
                item_ref=f"novel-{i}", entity_key=f"NOV{i}",
                personal_relevance=0.0,
                run_reason="shadow",
            )
        for i in range(2):
            await add_experience_event(
                db, user_id=uid, surface="shadow",
                item_ref=f"novel-{i}", entity_key=f"NOV{i}",
                explanation_valid=True,
                run_reason="calibration",
            )
        await db.flush()
        result = await calculate_novelty_effectiveness(db, user_id=uid, run_override=True)
        assert result["sufficient_samples"] is True
        assert result["effectiveness"] == 0.5
        assert result["engaged_novel_count"] == 2
        assert result["total_novel_count"] == 4

    @pytest.mark.asyncio
    async def test_insufficient_novel_items(self, db):
        from app.services.personal_experience_calibration_service import calculate_novelty_effectiveness
        from app.db.repositories.personal_experience_repo import add_experience_event
        await add_experience_event(
            db, user_id="u-few-n", surface="shadow",
            item_ref="n1", entity_key="N1",
            personal_relevance=0.0, run_reason="shadow",
        )
        await db.flush()
        result = await calculate_novelty_effectiveness(db, user_id="u-few-n", run_override=True)
        assert result["sufficient_samples"] is False
        assert result["effectiveness"] is None

    @pytest.mark.asyncio
    async def test_returns_empty_flag_off(self, db):
        from app.services.personal_experience_calibration_service import calculate_novelty_effectiveness
        result = await calculate_novelty_effectiveness(db, user_id=_USER, run_override=False)
        assert result["sufficient_samples"] is False


# ===================================================================
# § summarize_experience_calibration
# ===================================================================

class TestSummarizeExperienceCalibration:
    @pytest.mark.asyncio
    async def test_aggregates_all_metrics(self, db):
        from app.services.personal_experience_calibration_service import summarize_experience_calibration
        await _seed_calibration_events(db, _USER, count=10, engaged_count=7)
        result = await summarize_experience_calibration(db, user_id=_USER, run_override=True)
        assert "attention_accuracy" in result
        assert "resume_accuracy" in result
        assert "explainability_coverage" in result
        assert "ranking_stability" in result
        assert "novelty_effectiveness" in result
        assert result["calibration_schema"] == 1
        assert "generated_at" in result

    @pytest.mark.asyncio
    async def test_returns_empty_flag_off(self, db):
        from app.services.personal_experience_calibration_service import summarize_experience_calibration
        result = await summarize_experience_calibration(db, user_id=_USER, run_override=False)
        assert result["attention_accuracy"]["sufficient_samples"] is False
        assert result["calibration_schema"] == 1

    @pytest.mark.asyncio
    async def test_returns_empty_session_none(self):
        from app.services.personal_experience_calibration_service import summarize_experience_calibration
        result = await summarize_experience_calibration(None, user_id=_USER, run_override=True)
        assert result["attention_accuracy"]["sufficient_samples"] is False


# ===================================================================
# § Null-session contract
# ===================================================================

class TestNullSession:
    @pytest.mark.asyncio
    async def test_record_outcome_none(self):
        from app.services.personal_experience_calibration_service import record_experience_outcome
        result = await record_experience_outcome(
            None, user_id=_USER, surface="shadow", item_ref="X", run_override=True,
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_attention_accuracy_none(self):
        from app.services.personal_experience_calibration_service import calculate_attention_accuracy
        result = await calculate_attention_accuracy(None, user_id=_USER, run_override=True)
        assert result["sufficient_samples"] is False

    @pytest.mark.asyncio
    async def test_resume_accuracy_none(self):
        from app.services.personal_experience_calibration_service import calculate_resume_accuracy
        result = await calculate_resume_accuracy(None, user_id=_USER, run_override=True)
        assert result["sufficient_samples"] is False

    @pytest.mark.asyncio
    async def test_coverage_none(self):
        from app.services.personal_experience_calibration_service import calculate_explainability_coverage
        result = await calculate_explainability_coverage(None, user_id=_USER, run_override=True)
        assert result["sufficient_samples"] is False

    @pytest.mark.asyncio
    async def test_stability_none(self):
        from app.services.personal_experience_calibration_service import calculate_ranking_stability
        result = await calculate_ranking_stability(None, user_id=_USER, run_override=True)
        assert result["sufficient_samples"] is False

    @pytest.mark.asyncio
    async def test_novelty_none(self):
        from app.services.personal_experience_calibration_service import calculate_novelty_effectiveness
        result = await calculate_novelty_effectiveness(None, user_id=_USER, run_override=True)
        assert result["sufficient_samples"] is False

    @pytest.mark.asyncio
    async def test_summary_none(self):
        from app.services.personal_experience_calibration_service import summarize_experience_calibration
        result = await summarize_experience_calibration(None, user_id=_USER, run_override=True)
        assert result["attention_accuracy"]["sufficient_samples"] is False


# ===================================================================
# § AST safety
# ===================================================================

class TestASTSafety:
    def _source(self) -> str:
        return _SRC.read_text()

    def _tree(self) -> ast.Module:
        return ast.parse(self._source())

    def test_module_importable(self):
        import app.services.personal_experience_calibration_service  # noqa: F401

    def test_no_banned_phrases(self):
        tree = self._tree()

        docstring_node_ids: set = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Module)):
                body = getattr(node, "body", [])
                if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                    docstring_node_ids.add(id(body[0].value))

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
                if id(node) in docstring_node_ids:
                    continue
                val_lower = node.value.lower()
                for phrase in banned:
                    if phrase in val_lower:
                        violations.append(
                            f"Line ~{getattr(node, 'lineno', '?')}: "
                            f"banned phrase '{phrase}' in: {node.value[:80]!r}"
                        )
        assert not violations, "\n".join(violations)

    def test_no_upstream_truth_imports(self):
        tree = self._tree()
        banned_modules = [
            "forecast_repo", "decision_repo", "scenario_repo",
            "similarity_repo", "conviction", "order", "execution",
            "stance", "user_learning_repo",
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
            occurrences = [
                i for i in range(len(source))
                if source[i:i + len(pattern)] == pattern
            ]
            assert not occurrences, (
                f"Found '{pattern}' in source — calibration must be append-only"
            )
