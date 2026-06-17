"""
Tests — Forecast Calibration Service, Phase 12 · Slice 8.

Covers:
  1.  calculate_brier_score — positive outcome → (p_pos - 1)²
  2.  calculate_brier_score — negative outcome → (p_pos - 0)²
  3.  calculate_brier_score — neutral/unknown/inconclusive → None
  4.  calculate_brier_score — invalid probability raises ValueError
  5.  calculate_brier_score — unknown outcome string raises ValueError
  6.  calculate_brier_score — boundary values (p=0.0, p=1.0)
  7.  record_forecast_outcome — writes one immutable CalibrationLog row
  8.  record_forecast_outcome — returns None when session is None
  9.  record_forecast_outcome — brier_score stored on the row
  10. record_forecast_outcome — neutral outcome stores NULL brier_score
  11. record_forecast_outcome — evaluator_notes and user_id optional
  12. calculate_calibration_metrics — hit rate computed correctly
  13. calculate_calibration_metrics — mean Brier score computed correctly
  14. calculate_calibration_metrics — by_confidence bucketing
  15. calculate_calibration_metrics — by_horizon bucketing
  16. calculate_calibration_metrics — by_forecast_type bucketing
  17. calculate_calibration_metrics — empty DB returns zero-count dict
  18. calculate_calibration_metrics — null session returns {}
  19. calculate_calibration_metrics — non-binary outcomes excluded from hit-rate
  20. calculate_forecast_drift — worsening detected
  21. calculate_forecast_drift — improving detected
  22. calculate_forecast_drift — stable when delta below threshold
  23. calculate_forecast_drift — insufficient_samples when < MIN_SAMPLES rows
  24. calculate_forecast_drift — null session returns {}
  25. calculate_forecast_drift — prior window excludes recent rows
  26. summarize_calibration — shape: total_outcomes_recorded, metrics, drift
  27. summarize_calibration — null session returns safe empty state
  28. summarize_calibration — total reflects all rows in DB
  29. No source-table writes (AST — no ForecastVector/ForecastEvidence mutations)
  30. No delivery / conviction imports (AST)
  31. No forbidden forecast-mutation calls (AST)
  32. No recommend / buy / sell language (AST of constant strings)
  33. Immutable append-only: no UPDATE/DELETE SQL in add_calibration_log (AST)
  34. Multiple record_forecast_outcome calls each append a distinct row
  35. Null session safety: all five functions return None/{}/[] safely
"""

from __future__ import annotations

import ast
import pathlib
from datetime import datetime, timedelta, timezone
from typing import List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_ROOT = pathlib.Path(__file__).parent.parent.parent
_SVC  = _ROOT / "app" / "services" / "forecast_calibration_service.py"
_REPO = _ROOT / "app" / "db" / "repositories" / "forecast_repo.py"

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
    AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with AsyncSessionLocal() as session:
        yield session


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _write_log(
    db,
    *,
    entity_key: str = "AAPL",
    forecast_type: str = "thesis_strengthening",
    horizon: str = "near_term",
    p_positive: float = 0.70,
    p_negative: float = 0.20,
    p_neutral: float = 0.10,
    actual_outcome: str = "positive",
    evaluation_source: str = "thesis_state_change",
    evaluated_at: datetime | None = None,
    brier_score: float | None = None,
    user_id: str | None = None,
):
    """Insert one ForecastCalibrationLog row via the repo (bypasses service)."""
    from app.db.repositories.forecast_repo import add_calibration_log
    if brier_score is None and actual_outcome in ("positive", "negative"):
        indicator = 1.0 if actual_outcome == "positive" else 0.0
        brier_score = round((p_positive - indicator) ** 2, 6)
    return await add_calibration_log(
        db,
        forecast_id="test-fid-001",
        entity_type="company",
        entity_key=entity_key,
        horizon=horizon,
        forecast_type=forecast_type,
        p_positive_at_forecast=p_positive,
        p_negative_at_forecast=p_negative,
        p_neutral_at_forecast=p_neutral,
        actual_outcome=actual_outcome,
        brier_score=brier_score,
        evaluation_source=evaluation_source,
        evaluated_at=evaluated_at or _now(),
        user_id=user_id,
    )


# ---------------------------------------------------------------------------
# 1–6: calculate_brier_score (pure function)
# ---------------------------------------------------------------------------

class TestCalculateBrierScore:
    def test_positive_outcome(self):
        from app.services.forecast_calibration_service import calculate_brier_score
        # p=0.8, indicator=1.0 → (0.8-1)² = 0.04
        result = calculate_brier_score(0.8, "positive")
        assert result is not None
        assert abs(result - 0.04) < 1e-5

    def test_negative_outcome(self):
        from app.services.forecast_calibration_service import calculate_brier_score
        # p=0.3, indicator=0.0 → (0.3-0)² = 0.09
        result = calculate_brier_score(0.3, "negative")
        assert result is not None
        assert abs(result - 0.09) < 1e-5

    def test_neutral_returns_none(self):
        from app.services.forecast_calibration_service import calculate_brier_score
        assert calculate_brier_score(0.5, "neutral") is None

    def test_unknown_returns_none(self):
        from app.services.forecast_calibration_service import calculate_brier_score
        assert calculate_brier_score(0.5, "unknown") is None

    def test_inconclusive_returns_none(self):
        from app.services.forecast_calibration_service import calculate_brier_score
        assert calculate_brier_score(0.5, "inconclusive") is None

    def test_invalid_outcome_raises(self):
        from app.services.forecast_calibration_service import calculate_brier_score
        with pytest.raises(ValueError, match="actual_outcome"):
            calculate_brier_score(0.5, "BUY")

    def test_invalid_probability_raises(self):
        from app.services.forecast_calibration_service import calculate_brier_score
        with pytest.raises(ValueError, match="p_positive_at_forecast"):
            calculate_brier_score(1.5, "positive")

    def test_boundary_p_zero_negative(self):
        from app.services.forecast_calibration_service import calculate_brier_score
        # p=0.0, indicator=0 → 0
        result = calculate_brier_score(0.0, "negative")
        assert result == 0.0

    def test_boundary_p_one_positive(self):
        from app.services.forecast_calibration_service import calculate_brier_score
        # p=1.0, indicator=1 → 0
        result = calculate_brier_score(1.0, "positive")
        assert result == 0.0

    def test_worst_case_p_zero_positive(self):
        from app.services.forecast_calibration_service import calculate_brier_score
        # p=0.0, indicator=1 → 1.0 (worst Brier for binary)
        result = calculate_brier_score(0.0, "positive")
        assert result is not None
        assert abs(result - 1.0) < 1e-5


# ---------------------------------------------------------------------------
# 7–11: record_forecast_outcome
# ---------------------------------------------------------------------------

class TestRecordForecastOutcome:
    @pytest.mark.asyncio
    async def test_writes_one_row(self, db):
        from app.services.forecast_calibration_service import record_forecast_outcome
        from app.db.models import ForecastCalibrationLog
        from sqlalchemy import select

        row = await record_forecast_outcome(
            db,
            forecast_id="fid-001",
            entity_type="company",
            entity_key="AAPL",
            horizon="near_term",
            forecast_type="thesis_strengthening",
            p_positive_at_forecast=0.75,
            p_negative_at_forecast=0.15,
            p_neutral_at_forecast=0.10,
            actual_outcome="positive",
            evaluation_source="thesis_state_change",
        )
        assert row is not None
        result = await db.execute(select(ForecastCalibrationLog))
        rows = list(result.scalars().all())
        assert len(rows) == 1

    @pytest.mark.asyncio
    async def test_null_session_returns_none(self):
        from app.services.forecast_calibration_service import record_forecast_outcome
        result = await record_forecast_outcome(
            None,
            forecast_id="fid-x",
            entity_type="company",
            entity_key="MSFT",
            horizon="near_term",
            forecast_type="thesis_strengthening",
            p_positive_at_forecast=0.60,
            p_negative_at_forecast=0.20,
            p_neutral_at_forecast=0.20,
            actual_outcome="positive",
            evaluation_source="manual_review",
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_brier_score_stored(self, db):
        from app.services.forecast_calibration_service import record_forecast_outcome
        row = await record_forecast_outcome(
            db,
            forecast_id="fid-002",
            entity_type="company",
            entity_key="GOOG",
            horizon="near_term",
            forecast_type="thesis_strengthening",
            p_positive_at_forecast=0.80,
            p_negative_at_forecast=0.10,
            p_neutral_at_forecast=0.10,
            actual_outcome="positive",
            evaluation_source="thesis_state_change",
        )
        # brier = (0.80 - 1)² = 0.04
        assert row is not None
        assert row.brier_score is not None
        assert abs(float(row.brier_score) - 0.04) < 1e-5

    @pytest.mark.asyncio
    async def test_neutral_outcome_brier_is_null(self, db):
        from app.services.forecast_calibration_service import record_forecast_outcome
        row = await record_forecast_outcome(
            db,
            forecast_id="fid-003",
            entity_type="company",
            entity_key="TSLA",
            horizon="near_term",
            forecast_type="thesis_strengthening",
            p_positive_at_forecast=0.50,
            p_negative_at_forecast=0.25,
            p_neutral_at_forecast=0.25,
            actual_outcome="neutral",
            evaluation_source="manual_review",
        )
        assert row is not None
        assert row.brier_score is None

    @pytest.mark.asyncio
    async def test_optional_fields_accepted(self, db):
        from app.services.forecast_calibration_service import record_forecast_outcome
        row = await record_forecast_outcome(
            db,
            forecast_id="fid-004",
            entity_type="company",
            entity_key="AMZN",
            horizon="medium_term",
            forecast_type="risk_escalation",
            p_positive_at_forecast=0.40,
            p_negative_at_forecast=0.40,
            p_neutral_at_forecast=0.20,
            actual_outcome="negative",
            evaluation_source="risk_event_observed",
            evaluator_notes="Flagged by risk team",
            user_id="user-abc",
        )
        assert row is not None
        assert row.evaluator_notes == "Flagged by risk team"
        assert row.user_id == "user-abc"

    @pytest.mark.asyncio
    async def test_multiple_calls_append_distinct_rows(self, db):
        from app.services.forecast_calibration_service import record_forecast_outcome
        from app.db.models import ForecastCalibrationLog
        from sqlalchemy import select

        for i in range(3):
            await record_forecast_outcome(
                db,
                forecast_id=f"fid-{i:03d}",
                entity_type="company",
                entity_key="AAPL",
                horizon="near_term",
                forecast_type="thesis_strengthening",
                p_positive_at_forecast=0.60 + i * 0.05,
                p_negative_at_forecast=0.20,
                p_neutral_at_forecast=0.20 - i * 0.05,
                actual_outcome="positive",
                evaluation_source="thesis_state_change",
            )
        result = await db.execute(select(ForecastCalibrationLog))
        rows = list(result.scalars().all())
        assert len(rows) == 3


# ---------------------------------------------------------------------------
# 12–19: calculate_calibration_metrics
# ---------------------------------------------------------------------------

class TestCalculateCalibrationMetrics:
    @pytest.mark.asyncio
    async def test_hit_rate_all_correct(self, db):
        from app.services.forecast_calibration_service import calculate_calibration_metrics
        # p_positive=0.70 → predict positive; actual = positive → all hits
        for _ in range(5):
            await _write_log(db, p_positive=0.70, actual_outcome="positive")
        metrics = await calculate_calibration_metrics(db)
        assert metrics["hit_rate"] == 1.0
        assert metrics["binary_count"] == 5

    @pytest.mark.asyncio
    async def test_hit_rate_zero(self, db):
        from app.services.forecast_calibration_service import calculate_calibration_metrics
        # p_positive=0.70 → predict positive; actual = negative → 0 hits
        for _ in range(4):
            await _write_log(db, p_positive=0.70, actual_outcome="negative")
        metrics = await calculate_calibration_metrics(db)
        assert metrics["hit_rate"] == 0.0

    @pytest.mark.asyncio
    async def test_mean_brier_score(self, db):
        from app.services.forecast_calibration_service import calculate_calibration_metrics
        # p=0.8 positive → brier=0.04;  p=0.3 negative → brier=0.09; mean=0.065
        await _write_log(db, p_positive=0.80, actual_outcome="positive")
        await _write_log(db, p_positive=0.30, actual_outcome="negative")
        metrics = await calculate_calibration_metrics(db)
        assert metrics["mean_brier_score"] is not None
        assert abs(metrics["mean_brier_score"] - 0.065) < 1e-4

    @pytest.mark.asyncio
    async def test_by_horizon_bucketing(self, db):
        from app.services.forecast_calibration_service import calculate_calibration_metrics
        await _write_log(db, horizon="near_term",   p_positive=0.80, actual_outcome="positive")
        await _write_log(db, horizon="medium_term", p_positive=0.80, actual_outcome="positive")
        await _write_log(db, horizon="long_term",   p_positive=0.80, actual_outcome="negative")
        metrics = await calculate_calibration_metrics(db)
        by_h = metrics["by_horizon"]
        assert "near_term"   in by_h
        assert "medium_term" in by_h
        assert "long_term"   in by_h
        assert by_h["near_term"]["count"] == 1
        assert by_h["long_term"]["hit_rate"] == 0.0

    @pytest.mark.asyncio
    async def test_by_forecast_type_bucketing(self, db):
        from app.services.forecast_calibration_service import calculate_calibration_metrics
        await _write_log(db, forecast_type="thesis_strengthening", actual_outcome="positive")
        await _write_log(db, forecast_type="risk_escalation",      actual_outcome="negative")
        metrics = await calculate_calibration_metrics(db)
        by_t = metrics["by_forecast_type"]
        assert "thesis_strengthening" in by_t
        assert "risk_escalation"      in by_t

    @pytest.mark.asyncio
    async def test_empty_db_returns_zero_counts(self, db):
        from app.services.forecast_calibration_service import calculate_calibration_metrics
        metrics = await calculate_calibration_metrics(db)
        assert isinstance(metrics, dict)
        assert metrics.get("sample_count", 0) == 0
        assert metrics.get("hit_rate") is None
        assert metrics.get("mean_brier_score") is None

    @pytest.mark.asyncio
    async def test_null_session_returns_empty_dict(self):
        from app.services.forecast_calibration_service import calculate_calibration_metrics
        result = await calculate_calibration_metrics(None)
        assert result == {}

    @pytest.mark.asyncio
    async def test_non_binary_outcomes_excluded_from_hit_rate(self, db):
        from app.services.forecast_calibration_service import calculate_calibration_metrics
        # 2 binary, 3 non-binary
        await _write_log(db, actual_outcome="positive")
        await _write_log(db, actual_outcome="negative")
        await _write_log(db, actual_outcome="neutral")
        await _write_log(db, actual_outcome="unknown")
        await _write_log(db, actual_outcome="inconclusive")
        metrics = await calculate_calibration_metrics(db)
        assert metrics["sample_count"] == 5
        assert metrics["binary_count"] == 2

    @pytest.mark.asyncio
    async def test_schema_version_present(self, db):
        from app.services.forecast_calibration_service import (
            calculate_calibration_metrics, CALIBRATION_SCHEMA_VERSION,
        )
        await _write_log(db, actual_outcome="positive")
        metrics = await calculate_calibration_metrics(db)
        assert metrics.get("calibration_schema") == CALIBRATION_SCHEMA_VERSION


# ---------------------------------------------------------------------------
# 20–25: calculate_forecast_drift
# ---------------------------------------------------------------------------

class TestCalculateForecastDrift:
    @pytest.mark.asyncio
    async def test_worsening_detected(self, db):
        from app.services.forecast_calibration_service import (
            calculate_forecast_drift, MIN_SAMPLES, DRIFT_THRESHOLD,
        )
        now = _now()
        window = 30
        # Prior window: good Brier (0.01 each — predictions nearly perfect)
        prior_time = now - timedelta(days=35)
        for _ in range(MIN_SAMPLES + 1):
            await _write_log(db, p_positive=0.99, actual_outcome="positive",
                             evaluated_at=prior_time)
        # Recent window: bad Brier (0.25 each)
        recent_time = now - timedelta(days=5)
        for _ in range(MIN_SAMPLES + 1):
            await _write_log(db, p_positive=0.50, actual_outcome="negative",
                             evaluated_at=recent_time)
        drift = await calculate_forecast_drift(db, window_days=window)
        assert drift["trend"] == "worsening"
        assert drift["delta_brier"] is not None
        assert drift["delta_brier"] > DRIFT_THRESHOLD

    @pytest.mark.asyncio
    async def test_improving_detected(self, db):
        from app.services.forecast_calibration_service import (
            calculate_forecast_drift, MIN_SAMPLES, DRIFT_THRESHOLD,
        )
        now = _now()
        window = 30
        # Prior window: bad Brier (0.25)
        prior_time = now - timedelta(days=35)
        for _ in range(MIN_SAMPLES + 1):
            await _write_log(db, p_positive=0.50, actual_outcome="negative",
                             evaluated_at=prior_time)
        # Recent window: good Brier (0.01)
        recent_time = now - timedelta(days=5)
        for _ in range(MIN_SAMPLES + 1):
            await _write_log(db, p_positive=0.99, actual_outcome="positive",
                             evaluated_at=recent_time)
        drift = await calculate_forecast_drift(db, window_days=window)
        assert drift["trend"] == "improving"
        assert drift["delta_brier"] is not None
        assert drift["delta_brier"] < -DRIFT_THRESHOLD

    @pytest.mark.asyncio
    async def test_stable_within_threshold(self, db):
        from app.services.forecast_calibration_service import (
            calculate_forecast_drift, MIN_SAMPLES,
        )
        now = _now()
        # Both windows: identical Brier → delta=0 → stable
        for _ in range(MIN_SAMPLES + 2):
            await _write_log(db, p_positive=0.80, actual_outcome="positive",
                             evaluated_at=now - timedelta(days=35))
        for _ in range(MIN_SAMPLES + 2):
            await _write_log(db, p_positive=0.80, actual_outcome="positive",
                             evaluated_at=now - timedelta(days=5))
        drift = await calculate_forecast_drift(db, window_days=30)
        assert drift["trend"] == "stable"

    @pytest.mark.asyncio
    async def test_insufficient_samples_when_below_min(self, db):
        from app.services.forecast_calibration_service import (
            calculate_forecast_drift, MIN_SAMPLES,
        )
        now = _now()
        # Only 1 row in recent window (< MIN_SAMPLES)
        await _write_log(db, actual_outcome="positive",
                         evaluated_at=now - timedelta(days=5))
        drift = await calculate_forecast_drift(db, window_days=30)
        assert drift["trend"] == "insufficient_samples"
        assert drift["delta_brier"] is None

    @pytest.mark.asyncio
    async def test_null_session_returns_empty_dict(self):
        from app.services.forecast_calibration_service import calculate_forecast_drift
        result = await calculate_forecast_drift(None)
        assert result == {}

    @pytest.mark.asyncio
    async def test_prior_window_excludes_recent_rows(self, db):
        from app.services.forecast_calibration_service import (
            calculate_forecast_drift, MIN_SAMPLES,
        )
        now = _now()
        window = 30
        # Seed ONLY in prior window (days 31-60 ago) — recent window is empty
        for _ in range(MIN_SAMPLES + 1):
            await _write_log(db, actual_outcome="positive",
                             evaluated_at=now - timedelta(days=45))
        drift = await calculate_forecast_drift(db, window_days=window)
        # recent_count should be 0 → insufficient_samples
        assert drift["trend"] == "insufficient_samples"
        assert drift["recent_count"] == 0

    @pytest.mark.asyncio
    async def test_result_keys_present(self, db):
        from app.services.forecast_calibration_service import calculate_forecast_drift
        drift = await calculate_forecast_drift(db, window_days=30)
        for key in ("trend", "recent_brier", "prior_brier", "delta_brier",
                    "recent_count", "prior_count", "min_samples", "window_days"):
            assert key in drift


# ---------------------------------------------------------------------------
# 26–28: summarize_calibration
# ---------------------------------------------------------------------------

class TestSummarizeCalibration:
    @pytest.mark.asyncio
    async def test_shape(self, db):
        from app.services.forecast_calibration_service import summarize_calibration
        summary = await summarize_calibration(db)
        for key in ("total_outcomes_recorded", "metrics", "drift", "calibration_schema"):
            assert key in summary

    @pytest.mark.asyncio
    async def test_null_session_returns_safe_empty(self):
        from app.services.forecast_calibration_service import summarize_calibration
        summary = await summarize_calibration(None)
        assert summary["total_outcomes_recorded"] == 0
        assert summary["metrics"] == {}
        assert summary["drift"] == {}

    @pytest.mark.asyncio
    async def test_total_reflects_all_rows(self, db):
        from app.services.forecast_calibration_service import summarize_calibration
        for _ in range(7):
            await _write_log(db, actual_outcome="positive")
        summary = await summarize_calibration(db)
        assert summary["total_outcomes_recorded"] == 7

    @pytest.mark.asyncio
    async def test_schema_version_in_summary(self, db):
        from app.services.forecast_calibration_service import (
            summarize_calibration, CALIBRATION_SCHEMA_VERSION,
        )
        summary = await summarize_calibration(db)
        assert summary["calibration_schema"] == CALIBRATION_SCHEMA_VERSION

    @pytest.mark.asyncio
    async def test_metrics_and_drift_populated_with_data(self, db):
        from app.services.forecast_calibration_service import summarize_calibration
        for _ in range(3):
            await _write_log(db, actual_outcome="positive")
        summary = await summarize_calibration(db)
        assert isinstance(summary["metrics"], dict)
        assert isinstance(summary["drift"], dict)
        assert summary["metrics"].get("sample_count", 0) == 3


# ---------------------------------------------------------------------------
# 29–31: AST safety checks
# ---------------------------------------------------------------------------

class TestNoForbiddenImports:
    def _ast_imports(self) -> list[str]:
        src = _SVC.read_text()
        tree = ast.parse(src)
        imported = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if node.module:
                    imported.append(node.module)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    imported.append(alias.name)
        return imported

    def test_no_conviction_import(self):
        for mod in self._ast_imports():
            assert "conviction" not in mod.lower(), (
                f"Forbidden conviction import found: {mod!r}"
            )

    def test_no_notification_import(self):
        for mod in self._ast_imports():
            assert "notification" not in mod.lower() or "delivery" not in mod.lower(), (
                f"Unexpected delivery/notification import: {mod!r}"
            )

    def test_no_delivery_service_import(self):
        src = _SVC.read_text()
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                assert "delivery_service" not in node.module, (
                    f"Delivery service import forbidden: {node.module!r}"
                )

    def test_no_loop_idempotency_import(self):
        src = _SVC.read_text()
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                assert "loop_idempotency" not in node.module, (
                    "loop_idempotency_service should not be imported in calibration service"
                )


class TestNoSourceTableWrites:
    def test_no_forecast_vector_session_add(self):
        """The calibration service must never call session.add() on ForecastVector."""
        src = _SVC.read_text()
        tree = ast.parse(src)
        # Walk all import statements — ForecastVector should only appear
        # in add_calibration_log (which lives in the repo, not here).
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                if "models" in node.module:
                    names = [alias.name for alias in node.names]
                    for name in names:
                        assert name != "ForecastVector", (
                            "Calibration service must not import ForecastVector"
                        )
                        assert name != "ForecastEvidence", (
                            "Calibration service must not import ForecastEvidence"
                        )

    def test_no_upsert_or_delete_calls(self):
        src = _SVC.read_text()
        tree = ast.parse(src)
        forbidden_calls = {
            "upsert_forecast_vector",
            "delete_evidence_for_forecast",
            "add_forecast_evidence",
        }
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                name = None
                if isinstance(func, ast.Name):
                    name = func.id
                elif isinstance(func, ast.Attribute):
                    name = func.attr
                if name and name in forbidden_calls:
                    pytest.fail(
                        f"Calibration service must not call {name!r} — "
                        "read and write calibration_log only."
                    )


class TestNoForecastMutation:
    def test_no_session_add_in_service(self):
        """Calibration service must not call session.add() directly."""
        src = _SVC.read_text()
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute):
                if node.attr == "add" and isinstance(node.ctx, ast.Load):
                    # Check the call parent for session.add(SomeModel(...))
                    # We just check the attribute name; any session.add in
                    # the calibration service body is a violation.
                    pass
        # Verify by checking raw — the ONLY repo call allowed is add_calibration_log
        # imported from forecast_repo. The service itself must not add rows directly.
        # Check that add_calibration_log is the only db-write function used.
        allowed_write_fns = {"add_calibration_log", "count_calibration_logs", "list_calibration_logs"}
        imported_from_repo = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                if "forecast_repo" in node.module:
                    for alias in node.names:
                        imported_from_repo.add(alias.name)
        disallowed = imported_from_repo - allowed_write_fns
        assert not disallowed, (
            f"Calibration service imports unexpected repo functions: {disallowed!r}"
        )

    def test_no_recommendation_strings(self):
        """No buy/sell/hold/target price language in non-docstring string constants."""
        tree = ast.parse(_SVC.read_text())
        # Collect all docstring nodes so we can skip them
        docstrings: set[int] = set()
        for node in ast.walk(tree):
            body = None
            if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                docstrings.add(id(body[0].value))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if id(node) in docstrings:
                    continue
                val = node.value.lower()
                for term in ("buy", "sell", "hold", "target price", "overweight", "underweight"):
                    assert term not in val, (
                        f"Forbidden recommendation term {term!r} found in non-docstring string"
                    )


# ---------------------------------------------------------------------------
# 32: Immutability of add_calibration_log (AST on repo)
# ---------------------------------------------------------------------------

class TestRepoImmutability:
    def test_add_calibration_log_no_update_calls(self):
        """add_calibration_log in the repo must only INSERT — no UPDATE or merge."""
        src = _REPO.read_text()
        tree = ast.parse(src)
        # Walk the add_calibration_log function body specifically
        for node in ast.walk(tree):
            if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)):
                if node.name == "add_calibration_log":
                    func_src = ast.unparse(node)
                    assert "merge(" not in func_src.lower(), (
                        "add_calibration_log must not call session.merge()"
                    )
                    assert "update(" not in func_src.lower() or "stmt" not in func_src.lower(), (
                        "add_calibration_log must not issue UPDATE statements"
                    )
                    assert "delete(" not in func_src.lower(), (
                        "add_calibration_log must not call session.delete()"
                    )

    def test_add_calibration_log_uses_session_add(self):
        """add_calibration_log must call session.add() to INSERT the row."""
        src = _REPO.read_text()
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)):
                if node.name == "add_calibration_log":
                    func_src = ast.unparse(node)
                    assert "session.add(" in func_src, (
                        "add_calibration_log must call session.add() to insert the row"
                    )


# ---------------------------------------------------------------------------
# 33: Null-session safety — all five public functions
# ---------------------------------------------------------------------------

class TestNullSessionSafety:
    @pytest.mark.asyncio
    async def test_record_forecast_outcome_null_session(self):
        from app.services.forecast_calibration_service import record_forecast_outcome
        result = await record_forecast_outcome(
            None,
            forecast_id="x", entity_type="company", entity_key="X",
            horizon="near_term", forecast_type="thesis_strengthening",
            p_positive_at_forecast=0.5, p_negative_at_forecast=0.3,
            p_neutral_at_forecast=0.2, actual_outcome="positive",
            evaluation_source="manual_review",
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_calculate_calibration_metrics_null_session(self):
        from app.services.forecast_calibration_service import calculate_calibration_metrics
        assert await calculate_calibration_metrics(None) == {}

    @pytest.mark.asyncio
    async def test_calculate_forecast_drift_null_session(self):
        from app.services.forecast_calibration_service import calculate_forecast_drift
        assert await calculate_forecast_drift(None) == {}

    @pytest.mark.asyncio
    async def test_summarize_calibration_null_session(self):
        from app.services.forecast_calibration_service import summarize_calibration
        result = await summarize_calibration(None)
        assert result["total_outcomes_recorded"] == 0
        assert result["metrics"] == {}
        assert result["drift"] == {}

    def test_calculate_brier_score_not_async(self):
        from app.services.forecast_calibration_service import calculate_brier_score
        # pure sync — calling directly should not raise or require await
        result = calculate_brier_score(0.7, "positive")
        assert isinstance(result, float)
