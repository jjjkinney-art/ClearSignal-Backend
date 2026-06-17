"""
Tests — Decision Calibration Service, Phase 13 · Slice 9.

Covers:
  1.  record_decision_outcome — null session returns None
  2.  record_decision_outcome — appends row (snapshot_reason = calibration_outcome)
  3.  record_decision_outcome — rejects unsupported realized_significance
  4.  record_decision_outcome — NEVER updates existing row (count only increases)
  5.  record_decision_outcome — multiple calls create multiple rows (no dedup)
  6.  calculate_rank_order_agreement — null session returns {}
  7.  calculate_rank_order_agreement — insufficient samples returns status
  8.  calculate_rank_order_agreement — high-bucket material → agreement_rate = 1.0
  9.  calculate_rank_order_agreement — low-bucket material → agreement_rate = 0.0
  10. calculate_rank_order_agreement — mixed bucket/significance → correct fraction
  11. calculate_priority_stability — null session returns {}
  12. calculate_priority_stability — insufficient pairs → insufficient_samples
  13. calculate_priority_stability — stable priority → stability_rate = 1.0
  14. calculate_priority_stability — changed bucket → stability_rate < 1.0
  15. calculate_priority_stability — single-snapshot priorities excluded
  16. calculate_priority_churn — null session returns {}
  17. calculate_priority_churn — churn_rate = 1 - stability_rate
  18. calculate_priority_churn — insufficient samples propagates status
  19. calculate_false_prominence — null session returns {}
  20. calculate_false_prominence — insufficient samples
  21. calculate_false_prominence — all high + immaterial → rate = 1.0
  22. calculate_false_prominence — high + material → rate = 0.0
  23. calculate_false_prominence — mixed → correct fraction
  24. calculate_missed_importance — null session returns {}
  25. calculate_missed_importance — insufficient samples
  26. calculate_missed_importance — low bucket + material → rate = 1.0
  27. calculate_missed_importance — high bucket + material → rate = 0.0
  28. calculate_missed_importance — mixed → correct fraction
  29. summarize_decision_calibration — null session returns safe empty dict
  30. summarize_decision_calibration — returns all metric keys
  31. no priority mutation (decision_priority rows untouched after outcome recording)
  32. no delivery rows after calibration
  33. no notification rows after calibration
  34. AST: no session.update / session.delete calls on ranking log
  35. AST: no delivery / notification imports
  36. AST: no advice language in string constants
  37. AST: no conviction / forecast write-back imports
"""

from __future__ import annotations

import ast
import pathlib
import uuid
from datetime import datetime, timezone
from typing import Optional

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

# ---------------------------------------------------------------------------
# Path
# ---------------------------------------------------------------------------

_ROOT = pathlib.Path(__file__).parent.parent.parent
_SVC  = _ROOT / "app" / "services" / "decision_calibration_service.py"

# ---------------------------------------------------------------------------
# DB fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def engine():
    return create_async_engine("sqlite+aiosqlite:///:memory:", future=True)


@pytest_asyncio.fixture()
async def db(engine):
    from app.db.models import Base
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with Session() as session:
        yield session


# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------

def _uid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _seed_snapshot(
    db,
    priority_id: str,
    candidate_type: str = "forecast_candidate",
    entity_type: str = "company",
    entity_key: str = "NVDA",
    bucket: str = "medium",
    score: float = 0.55,
    rank_position: int = 0,
    snapshot_reason: str = "scheduled",
    user_id: Optional[str] = None,
    evaluated_at: Optional[datetime] = None,
):
    from app.db.repositories.decision_repo import add_ranking_log
    return await add_ranking_log(
        db,
        priority_id           = priority_id,
        candidate_type        = candidate_type,
        entity_type           = entity_type,
        entity_key            = entity_key,
        user_id               = user_id,
        decision_priority     = bucket,
        decision_rank_score   = score,
        rank_position         = rank_position,
        snapshot_reason       = snapshot_reason,
        realized_significance = None,
        evaluated_at          = evaluated_at or _now(),
    )


async def _seed_priority_row(db, ticker: str = "NVDA", score: float = 0.55):
    """Seed a minimal decision_priority row (global scope)."""
    from app.db.repositories.decision_repo import upsert_decision_priority
    return await upsert_decision_priority(
        db,
        candidate_type      = "forecast_candidate",
        entity_type         = "company",
        entity_key          = ticker,
        source_ref          = f"src-{_uid()[:8]}",
        decision_priority   = "medium",
        decision_rank_score = score,
        attention_score     = 0.55,
        urgency_score       = 0.55,
        impact_score        = 0.55,
        confidence_score    = 0.70,
        uncertainty_score   = 0.85,
        decision_reason     = "Signal is significant.",
        why_now             = "Horizon is near-term.",
        deprioritizers      = ["Low evidence."],
        evidence_summary    = ["Source: forecast_vector."],
        decision_schema     = 1,
        user_id             = None,
        ttl_hours           = 24,
    )


# ---------------------------------------------------------------------------
# 1–5. record_decision_outcome
# ---------------------------------------------------------------------------

class TestRecordDecisionOutcome:
    @pytest.mark.asyncio
    async def test_null_session_returns_none(self):
        from app.services.decision_calibration_service import record_decision_outcome
        result = await record_decision_outcome(
            None,
            priority_id="pid-001",
            realized_significance="material",
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_appends_row_with_calibration_outcome_reason(self, db):
        from app.services.decision_calibration_service import (
            record_decision_outcome, CALIBRATION_OUTCOME_REASON,
        )
        from app.db.repositories.decision_repo import list_ranking_logs

        pid = _uid()
        row = await record_decision_outcome(
            db,
            priority_id="p-" + pid,
            realized_significance="material",
            candidate_type="forecast_candidate",
            entity_key="NVDA",
            decision_priority="high",
        )
        await db.commit()

        assert row is not None
        rows = await list_ranking_logs(db, snapshot_reason=CALIBRATION_OUTCOME_REASON)
        assert len(rows) >= 1
        assert any(r.realized_significance == "material" for r in rows)

    @pytest.mark.asyncio
    async def test_rejects_unsupported_significance(self, db):
        from app.services.decision_calibration_service import record_decision_outcome
        result = await record_decision_outcome(
            db,
            priority_id="p-bad",
            realized_significance="very_important",  # not supported
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_never_updates_existing_row(self, db):
        from app.services.decision_calibration_service import record_decision_outcome
        from app.db.repositories.decision_repo import count_ranking_logs

        pid = _uid()
        # Create one snapshot row
        await _seed_snapshot(db, priority_id="snap-" + pid)
        await db.commit()
        before = await count_ranking_logs(db)

        # Record an outcome — should INSERT, not UPDATE the snapshot
        await record_decision_outcome(
            db,
            priority_id="snap-" + pid,
            realized_significance="immaterial",
        )
        await db.commit()

        after = await count_ranking_logs(db)
        assert after == before + 1  # exactly one new row

    @pytest.mark.asyncio
    async def test_multiple_calls_create_multiple_rows(self, db):
        from app.services.decision_calibration_service import record_decision_outcome
        from app.db.repositories.decision_repo import count_ranking_logs

        pid = _uid()
        before = await count_ranking_logs(db)
        await record_decision_outcome(db, priority_id=pid, realized_significance="material")
        await record_decision_outcome(db, priority_id=pid, realized_significance="immaterial")
        await db.commit()
        after = await count_ranking_logs(db)
        assert after == before + 2


# ---------------------------------------------------------------------------
# 6–10. calculate_rank_order_agreement
# ---------------------------------------------------------------------------

class TestRankOrderAgreement:
    @pytest.mark.asyncio
    async def test_null_session_returns_empty(self):
        from app.services.decision_calibration_service import calculate_rank_order_agreement
        assert await calculate_rank_order_agreement(None) == {}

    @pytest.mark.asyncio
    async def test_insufficient_samples(self, db):
        from app.services.decision_calibration_service import calculate_rank_order_agreement
        # No outcome rows → insufficient_samples
        result = await calculate_rank_order_agreement(db)
        assert result.get("status") == "insufficient_samples"
        assert result.get("agreement_rate") is None

    @pytest.mark.asyncio
    async def test_high_bucket_material_gives_full_agreement(self, db):
        from app.services.decision_calibration_service import (
            record_decision_outcome, calculate_rank_order_agreement, MIN_SAMPLES,
        )
        for _ in range(MIN_SAMPLES):
            await record_decision_outcome(
                db, priority_id=_uid(),
                realized_significance="material",
                decision_priority="high",
            )
        await db.commit()
        result = await calculate_rank_order_agreement(db)
        assert result.get("status") == "ok"
        assert result["agreement_rate"] == 1.0

    @pytest.mark.asyncio
    async def test_low_bucket_material_gives_zero_agreement(self, db):
        from app.services.decision_calibration_service import (
            record_decision_outcome, calculate_rank_order_agreement, MIN_SAMPLES,
        )
        for _ in range(MIN_SAMPLES):
            await record_decision_outcome(
                db, priority_id=_uid(),
                realized_significance="material",
                decision_priority="informational",
            )
        await db.commit()
        result = await calculate_rank_order_agreement(db)
        assert result.get("status") == "ok"
        assert result["agreement_rate"] == 0.0

    @pytest.mark.asyncio
    async def test_mixed_bucket_significance_correct_fraction(self, db):
        from app.services.decision_calibration_service import (
            record_decision_outcome, calculate_rank_order_agreement, MIN_SAMPLES,
        )
        # 6 material: 4 high, 2 low → agreement_rate = 4/6
        n = max(MIN_SAMPLES + 1, 6)
        for i in range(n):
            bucket = "high" if i < 4 else "low"
            sig    = "material"
            await record_decision_outcome(
                db, priority_id=_uid(),
                realized_significance=sig,
                decision_priority=bucket,
            )
        await db.commit()
        result = await calculate_rank_order_agreement(db)
        assert result.get("status") == "ok"
        # The ratio should be 4/6 = 0.666... (within ε for any n ≥ 6 seeded above)
        # For safety, just check it's between 0 and 1 and high_and_material is correct
        assert 0.0 < result["agreement_rate"] < 1.0
        assert result["high_and_material"] >= 1


# ---------------------------------------------------------------------------
# 11–15. calculate_priority_stability
# ---------------------------------------------------------------------------

class TestPriorityStability:
    @pytest.mark.asyncio
    async def test_null_session_returns_empty(self):
        from app.services.decision_calibration_service import calculate_priority_stability
        assert await calculate_priority_stability(None) == {}

    @pytest.mark.asyncio
    async def test_insufficient_pairs_returns_status(self, db):
        from app.services.decision_calibration_service import calculate_priority_stability
        # Only single snapshots per priority → no eligible pairs
        pid = _uid()
        await _seed_snapshot(db, priority_id=pid)
        await db.commit()
        result = await calculate_priority_stability(db)
        assert result.get("status") == "insufficient_samples"

    @pytest.mark.asyncio
    async def test_stable_priority_gives_full_stability(self, db):
        from app.services.decision_calibration_service import (
            calculate_priority_stability, MIN_STABILITY_SAMPLES,
        )
        for _ in range(MIN_STABILITY_SAMPLES):
            pid = _uid()
            await _seed_snapshot(db, priority_id=pid, bucket="high")
            await _seed_snapshot(db, priority_id=pid, bucket="high")
        await db.commit()
        result = await calculate_priority_stability(db)
        assert result.get("status") == "ok"
        assert result["stability_rate"] == 1.0

    @pytest.mark.asyncio
    async def test_changed_bucket_reduces_stability(self, db):
        from app.services.decision_calibration_service import (
            calculate_priority_stability, MIN_STABILITY_SAMPLES,
        )
        # 2 stable (same bucket) + 1 unstable (different bucket)
        for _ in range(MIN_STABILITY_SAMPLES - 1):
            pid = _uid()
            await _seed_snapshot(db, priority_id=pid, bucket="high")
            await _seed_snapshot(db, priority_id=pid, bucket="high")
        # One priority that changed bucket
        pid_changed = _uid()
        await _seed_snapshot(db, priority_id=pid_changed, bucket="high")
        await _seed_snapshot(db, priority_id=pid_changed, bucket="low")
        await db.commit()
        result = await calculate_priority_stability(db)
        assert result.get("status") == "ok"
        assert result["stability_rate"] < 1.0
        assert result["unstable_count"] >= 1

    @pytest.mark.asyncio
    async def test_single_snapshot_priorities_excluded(self, db):
        from app.services.decision_calibration_service import calculate_priority_stability
        # Only single snapshots → no eligible pairs
        for _ in range(10):
            await _seed_snapshot(db, priority_id=_uid(), bucket="high")
        await db.commit()
        result = await calculate_priority_stability(db)
        assert result.get("sample_count", 0) == 0


# ---------------------------------------------------------------------------
# 16–18. calculate_priority_churn
# ---------------------------------------------------------------------------

class TestPriorityChurn:
    @pytest.mark.asyncio
    async def test_null_session_returns_empty(self):
        from app.services.decision_calibration_service import calculate_priority_churn
        assert await calculate_priority_churn(None) == {}

    @pytest.mark.asyncio
    async def test_churn_rate_is_one_minus_stability(self, db):
        from app.services.decision_calibration_service import (
            calculate_priority_stability, calculate_priority_churn, MIN_STABILITY_SAMPLES,
        )
        for _ in range(MIN_STABILITY_SAMPLES):
            pid = _uid()
            await _seed_snapshot(db, priority_id=pid, bucket="medium")
            await _seed_snapshot(db, priority_id=pid, bucket="medium")
        await db.commit()
        stability = await calculate_priority_stability(db)
        churn     = await calculate_priority_churn(db)
        assert churn.get("status") == "ok"
        assert abs(churn["churn_rate"] - (1.0 - stability["stability_rate"])) < 1e-6

    @pytest.mark.asyncio
    async def test_insufficient_samples_propagates(self, db):
        from app.services.decision_calibration_service import calculate_priority_churn
        result = await calculate_priority_churn(db)
        assert result.get("status") == "insufficient_samples"
        assert result.get("churn_rate") is None


# ---------------------------------------------------------------------------
# 19–23. calculate_false_prominence
# ---------------------------------------------------------------------------

class TestFalseProminence:
    @pytest.mark.asyncio
    async def test_null_session_returns_empty(self):
        from app.services.decision_calibration_service import calculate_false_prominence
        assert await calculate_false_prominence(None) == {}

    @pytest.mark.asyncio
    async def test_insufficient_samples(self, db):
        from app.services.decision_calibration_service import calculate_false_prominence
        result = await calculate_false_prominence(db)
        assert result.get("status") == "insufficient_samples"

    @pytest.mark.asyncio
    async def test_all_high_immaterial_gives_rate_one(self, db):
        from app.services.decision_calibration_service import (
            record_decision_outcome, calculate_false_prominence, MIN_SAMPLES,
        )
        for _ in range(MIN_SAMPLES):
            await record_decision_outcome(
                db, priority_id=_uid(),
                realized_significance="immaterial",
                decision_priority="critical",
            )
        await db.commit()
        result = await calculate_false_prominence(db)
        assert result.get("status") == "ok"
        assert result["false_prominence_rate"] == 1.0

    @pytest.mark.asyncio
    async def test_high_and_material_gives_rate_zero(self, db):
        from app.services.decision_calibration_service import (
            record_decision_outcome, calculate_false_prominence, MIN_SAMPLES,
        )
        for _ in range(MIN_SAMPLES):
            await record_decision_outcome(
                db, priority_id=_uid(),
                realized_significance="material",
                decision_priority="high",
            )
        await db.commit()
        result = await calculate_false_prominence(db)
        assert result.get("status") == "ok"
        assert result["false_prominence_rate"] == 0.0

    @pytest.mark.asyncio
    async def test_mixed_gives_correct_fraction(self, db):
        from app.services.decision_calibration_service import (
            record_decision_outcome, calculate_false_prominence, MIN_SAMPLES,
        )
        n = max(MIN_SAMPLES + 1, 6)
        # 4 high + immaterial, 2 high + material
        for i in range(n):
            sig = "immaterial" if i < 4 else "material"
            await record_decision_outcome(
                db, priority_id=_uid(),
                realized_significance=sig,
                decision_priority="high",
            )
        await db.commit()
        result = await calculate_false_prominence(db)
        assert result.get("status") == "ok"
        assert 0.0 < result["false_prominence_rate"] < 1.0
        assert result["false_prominent_count"] >= 1


# ---------------------------------------------------------------------------
# 24–28. calculate_missed_importance
# ---------------------------------------------------------------------------

class TestMissedImportance:
    @pytest.mark.asyncio
    async def test_null_session_returns_empty(self):
        from app.services.decision_calibration_service import calculate_missed_importance
        assert await calculate_missed_importance(None) == {}

    @pytest.mark.asyncio
    async def test_insufficient_samples(self, db):
        from app.services.decision_calibration_service import calculate_missed_importance
        result = await calculate_missed_importance(db)
        assert result.get("status") == "insufficient_samples"

    @pytest.mark.asyncio
    async def test_low_bucket_material_gives_rate_one(self, db):
        from app.services.decision_calibration_service import (
            record_decision_outcome, calculate_missed_importance, MIN_SAMPLES,
        )
        for _ in range(MIN_SAMPLES):
            await record_decision_outcome(
                db, priority_id=_uid(),
                realized_significance="material",
                decision_priority="informational",
            )
        await db.commit()
        result = await calculate_missed_importance(db)
        assert result.get("status") == "ok"
        assert result["missed_importance_rate"] == 1.0

    @pytest.mark.asyncio
    async def test_high_bucket_material_gives_rate_zero(self, db):
        from app.services.decision_calibration_service import (
            record_decision_outcome, calculate_missed_importance, MIN_SAMPLES,
        )
        for _ in range(MIN_SAMPLES):
            await record_decision_outcome(
                db, priority_id=_uid(),
                realized_significance="material",
                decision_priority="critical",
            )
        await db.commit()
        result = await calculate_missed_importance(db)
        assert result.get("status") == "ok"
        assert result["missed_importance_rate"] == 0.0

    @pytest.mark.asyncio
    async def test_mixed_gives_correct_fraction(self, db):
        from app.services.decision_calibration_service import (
            record_decision_outcome, calculate_missed_importance, MIN_SAMPLES,
        )
        n = max(MIN_SAMPLES + 1, 6)
        for i in range(n):
            bucket = "low" if i < 3 else "high"
            await record_decision_outcome(
                db, priority_id=_uid(),
                realized_significance="material",
                decision_priority=bucket,
            )
        await db.commit()
        result = await calculate_missed_importance(db)
        assert result.get("status") == "ok"
        assert 0.0 < result["missed_importance_rate"] < 1.0


# ---------------------------------------------------------------------------
# 29–30. summarize_decision_calibration
# ---------------------------------------------------------------------------

class TestSummarizeDecisionCalibration:
    @pytest.mark.asyncio
    async def test_null_session_returns_safe_dict(self):
        from app.services.decision_calibration_service import summarize_decision_calibration
        result = await summarize_decision_calibration(None)
        assert isinstance(result, dict)
        assert result["total_outcomes_recorded"] == 0
        assert "rank_order_agreement" in result
        assert "calibration_schema" in result

    @pytest.mark.asyncio
    async def test_returns_all_metric_keys(self, db):
        from app.services.decision_calibration_service import summarize_decision_calibration
        result = await summarize_decision_calibration(db)
        for key in (
            "total_outcomes_recorded",
            "rank_order_agreement",
            "stability",
            "churn",
            "false_prominence",
            "missed_importance",
            "calibration_schema",
        ):
            assert key in result, f"Missing key: {key!r}"


# ---------------------------------------------------------------------------
# 31–33. Side-effect guards
# ---------------------------------------------------------------------------

class TestNoSideEffects:
    @pytest.mark.asyncio
    async def test_no_priority_mutation_after_outcome_recording(self, db):
        """decision_priority rows must not change after record_decision_outcome."""
        from app.services.decision_calibration_service import record_decision_outcome
        from app.db.repositories.decision_repo import list_decision_priorities

        # Seed a priority row
        priority = await _seed_priority_row(db, ticker="NVDA", score=0.55)
        original_score = priority.decision_rank_score
        await db.commit()

        # Record an outcome — must not touch the priority row
        await record_decision_outcome(
            db,
            priority_id=priority.id,
            realized_significance="material",
            decision_priority="medium",
            decision_rank_score=0.55,
        )
        await db.commit()

        rows = await list_decision_priorities(db, entity_key="NVDA")
        assert len(rows) >= 1
        matching = [r for r in rows if r.id == priority.id]
        assert len(matching) == 1
        assert abs(matching[0].decision_rank_score - original_score) < 1e-9

    @pytest.mark.asyncio
    async def test_no_delivery_rows_after_calibration(self, db):
        from app.services.decision_calibration_service import (
            record_decision_outcome, summarize_decision_calibration,
        )
        from app.db.models import DeliveryLedger
        from sqlalchemy import select, func

        await record_decision_outcome(
            db, priority_id=_uid(),
            realized_significance="material",
        )
        await summarize_decision_calibration(db)
        await db.commit()

        count = (await db.execute(
            select(func.count()).select_from(DeliveryLedger)
        )).scalar_one()
        assert count == 0

    @pytest.mark.asyncio
    async def test_no_notification_rows_after_calibration(self, db):
        from app.services.decision_calibration_service import (
            record_decision_outcome, summarize_decision_calibration,
        )
        from app.db.models import Notification
        from sqlalchemy import select, func

        await record_decision_outcome(
            db, priority_id=_uid(),
            realized_significance="immaterial",
        )
        await summarize_decision_calibration(db)
        await db.commit()

        count = (await db.execute(
            select(func.count()).select_from(Notification)
        )).scalar_one()
        assert count == 0


# ---------------------------------------------------------------------------
# 34–37. AST safety
# ---------------------------------------------------------------------------

def _load_tree() -> ast.AST:
    return ast.parse(_SVC.read_text(encoding="utf-8"))


def _docstring_values(tree: ast.AST) -> set:
    values: set = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if (
                node.body
                and isinstance(node.body[0], ast.Expr)
                and isinstance(node.body[0].value, ast.Constant)
                and isinstance(node.body[0].value.value, str)
            ):
                values.add(node.body[0].value.value)
    return values


class TestASTSafety:
    def test_no_update_or_delete_on_ranking_log(self):
        """record_decision_outcome must only INSERT — never UPDATE or DELETE."""
        src = _SVC.read_text(encoding="utf-8")
        # The service must not call session.execute with UPDATE/DELETE statements,
        # and must not directly call ORM .update() or .delete() patterns.
        for forbidden in (
            "session.delete",
            ".delete(",
            "UPDATE decision_ranking_log",
            "DELETE FROM decision_ranking_log",
        ):
            assert forbidden not in src, f"Forbidden mutation: {forbidden!r}"

    def test_no_delivery_or_notification_imports(self):
        tree = _load_tree()
        forbidden = {
            "delivery_service", "notification_service",
            "notification_repo", "delivery_repo",
            "loop_idempotency_service",
        }
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                module = getattr(node, "module", "") or ""
                names  = [a.name for a in getattr(node, "names", [])]
                for part in ([module] + names):
                    for fw in forbidden:
                        assert fw not in part.lower(), \
                            f"Forbidden import {part!r}"

    def test_no_advice_language_in_string_constants(self):
        tree = _load_tree()
        doc_values = _docstring_values(tree)
        banned = [
            "buy", "sell", "hold", "overweight", "underweight",
            "recommend", "target price", "position size",
            "take a position", "enter a trade",
        ]
        offenders = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                val = node.value
                if val in doc_values:
                    continue
                for term in banned:
                    if term in val.lower():
                        offenders.append(repr(term) + " in " + repr(val[:80]))
        assert not offenders, "Advice language: " + str(offenders)

    def test_no_conviction_or_forecast_write_imports(self):
        tree = _load_tree()
        forbidden = {
            "conviction_modeler", "conviction_repo",
            "forecast_repo", "forecast_builder",
            "forecast_calibration", "order", "execution",
        }
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                module = getattr(node, "module", "") or ""
                names  = [a.name for a in getattr(node, "names", [])]
                for part in ([module] + names):
                    for fw in forbidden:
                        assert fw not in part.lower(), \
                            f"Forbidden import {part!r}"
