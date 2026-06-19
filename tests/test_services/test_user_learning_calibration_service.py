"""
Tests — User Learning Calibration Service, Phase 15 · Slice 10.

Covers:
  1.  service importable
  2.  all 6 public functions present

  --- record_preference_outcome ---
  3.  inserts row to relevance_adjustment_log
  4.  run_reason="calibration"
  5.  observed_engagement=True → relevance_weight=1.0
  6.  observed_engagement=False → relevance_weight=-1.0
  7.  surface propagated to log row
  8.  item_ref stored in log row
  9.  adjusted_rank stored in log row
  10. intrinsic_rank stored in log row
  11. null session → None
  12. flag off → None
  13. returns ORM row

  --- calculate_preference_accuracy ---
  14. no calibration rows → accuracy=None, sufficient_samples=False
  15. all engaged (5 rows) → accuracy=1.0
  16. all not engaged (5 rows) → accuracy=0.0
  17. mixed 3 engaged + 2 not engaged → accuracy=0.6
  18. below MIN_ACCURACY_SAMPLES (4 rows) → sufficient_samples=False
  19. at exactly MIN_ACCURACY_SAMPLES (5 rows) → sufficient_samples=True
  20. engaged_count present in result
  21. not_engaged_count present in result
  22. total_count present in result
  23. null session → empty accuracy dict
  24. flag off → empty accuracy dict

  --- calculate_preference_drift ---
  25. no preferences → drift_score=None, sufficient_samples=False
  26. high-confidence preferences → low drift_score
  27. low-confidence preferences → high drift_score
  28. falsified preferences excluded from drift
  29. preference_count present in result
  30. below MIN_DRIFT_SAMPLES (1 pref) → sufficient_samples=False
  31. null session → empty drift dict
  32. flag off → empty drift dict

  --- calculate_false_preference_rate ---
  33. no calibration rows → fpr=None, sufficient_samples=False
  34. all boosted + engaged → false_preference_rate=0.0
  35. all boosted + not engaged → false_preference_rate=1.0
  36. non-boosted rows excluded (adjusted_rank >= intrinsic_rank)
  37. mixed boosted: 1 not-engaged out of 3 boosted → fpr=0.3333
  38. below MIN_FPR_SAMPLES (2 boosted) → sufficient_samples=False
  39. null session → empty fpr dict
  40. flag off → empty fpr dict
  41. boosted_total and false_count present in result

  --- calculate_preference_stability ---
  42. no preferences → stability_score=None, sufficient_samples=False
  43. high-confidence preferences → high stability_score
  44. low-confidence preferences → low stability_score
  45. falsified preferences excluded from stability
  46. preference_count present in result
  47. below MIN_STABILITY_SAMPLES (1 pref) → sufficient_samples=False
  48. null session → empty stability dict
  49. flag off → empty stability dict

  --- summarize_preference_calibration ---
  50. result contains "accuracy" key
  51. result contains "drift" key
  52. result contains "false_preference_rate" key
  53. result contains "stability" key
  54. result contains "user_id" key
  55. result contains "generated_at" key
  56. calibration_schema=1
  57. null session → structurally complete empty summary
  58. flag off → structurally complete empty summary
  59. sub-dicts each contain "sufficient_samples" key

  --- no truth mutation ---
  60. learned_preference rows unchanged after record_preference_outcome
  61. user_signal_event rows unchanged after record_preference_outcome
  62. no Notification rows created

  --- append-only ---
  63. row count increases by 1 per record call
  64. two separate calls → two separate rows
  65. no update/delete operations in module source

  --- tenant isolation ---
  66. user A calibration rows not counted in user B accuracy
  67. user B gets independent stability score

  --- AST safety ---
  68. no truth-table write imports
  69. no conviction / order / execution imports
  70. no banned advisory phrases in non-docstring strings
  71. no Notification writes in service source
  72. only "calibration" run_reason in add_relevance_adjustment_log calls
"""

from __future__ import annotations

import ast
import pathlib
import uuid
from typing import Any, Dict, List

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

_ROOT     = pathlib.Path(__file__).parent.parent.parent
_SVC_PATH = _ROOT / "app" / "services" / "user_learning_calibration_service.py"

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


def _uid() -> str:
    return str(uuid.uuid4())


# Helpers -------------------------------------------------------------------

async def _add_pref(db, user_id: str, confidence: float, status: str = "active") -> Any:
    from app.db.repositories.user_learning_repo import upsert_learned_preference
    return await upsert_learned_preference(
        db,
        user_id   = user_id,
        dimension = "sector_interest",
        entity_key = str(uuid.uuid4()),
        affinity   = 0.8 if confidence > 0.5 else -0.8,
        confidence = confidence,
        status     = status,
    )


async def _record_outcome(
    db,
    user_id: str,
    engaged: bool,
    adjusted_rank: int = 3,
    intrinsic_rank: int = 5,
    surface: str = "feed",
    item_ref: str = "item_001",
) -> Any:
    from app.services.user_learning_calibration_service import record_preference_outcome
    return await record_preference_outcome(
        db,
        user_id             = user_id,
        surface             = surface,
        item_ref            = item_ref,
        adjusted_rank       = adjusted_rank,
        intrinsic_rank      = intrinsic_rank,
        observed_engagement = engaged,
        run_override        = True,
    )


# ---------------------------------------------------------------------------
# 1–2: Import and presence
# ---------------------------------------------------------------------------

class TestImportAndPresence:

    def test_service_importable(self):
        import app.services.user_learning_calibration_service  # noqa: F401

    def test_all_functions_present(self):
        import app.services.user_learning_calibration_service as svc
        for fn in (
            "record_preference_outcome",
            "calculate_preference_accuracy",
            "calculate_preference_drift",
            "calculate_false_preference_rate",
            "calculate_preference_stability",
            "summarize_preference_calibration",
        ):
            assert callable(getattr(svc, fn, None)), f"missing: {fn}"


# ---------------------------------------------------------------------------
# 3–13: record_preference_outcome
# ---------------------------------------------------------------------------

class TestRecordPreferenceOutcome:

    @pytest.mark.asyncio
    async def test_inserts_row(self, db):
        uid = _uid()
        from app.db.repositories.user_learning_repo import list_relevance_adjustment_logs
        before = await list_relevance_adjustment_logs(db, user_id=uid)
        await _record_outcome(db, uid, engaged=True)
        after = await list_relevance_adjustment_logs(db, user_id=uid)
        assert len(after) == len(before) + 1

    @pytest.mark.asyncio
    async def test_run_reason_calibration(self, db):
        uid = _uid()
        row = await _record_outcome(db, uid, engaged=True)
        assert row is not None
        assert row.run_reason == "calibration"

    @pytest.mark.asyncio
    async def test_engaged_weight_positive(self, db):
        uid = _uid()
        row = await _record_outcome(db, uid, engaged=True)
        assert float(row.relevance_weight) == 1.0

    @pytest.mark.asyncio
    async def test_not_engaged_weight_negative(self, db):
        uid = _uid()
        row = await _record_outcome(db, uid, engaged=False)
        assert float(row.relevance_weight) == -1.0

    @pytest.mark.asyncio
    async def test_surface_propagated(self, db):
        uid = _uid()
        row = await _record_outcome(db, uid, engaged=True, surface="alerts")
        assert row.surface == "alerts"

    @pytest.mark.asyncio
    async def test_item_ref_stored(self, db):
        uid = _uid()
        row = await _record_outcome(db, uid, engaged=True, item_ref="ref_xyz")
        assert row.item_ref == "ref_xyz"

    @pytest.mark.asyncio
    async def test_adjusted_rank_stored(self, db):
        uid = _uid()
        row = await _record_outcome(db, uid, engaged=True, adjusted_rank=2)
        assert int(row.adjusted_rank) == 2

    @pytest.mark.asyncio
    async def test_intrinsic_rank_stored(self, db):
        uid = _uid()
        row = await _record_outcome(db, uid, engaged=True, intrinsic_rank=7)
        assert int(row.intrinsic_rank) == 7

    @pytest.mark.asyncio
    async def test_null_session_returns_none(self):
        from app.services.user_learning_calibration_service import record_preference_outcome
        result = await record_preference_outcome(
            None,
            user_id             = _uid(),
            surface             = "feed",
            item_ref            = "x",
            adjusted_rank       = 1,
            intrinsic_rank      = 2,
            observed_engagement = True,
            run_override        = True,
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_flag_off_returns_none(self, db):
        from app.services.user_learning_calibration_service import record_preference_outcome
        result = await record_preference_outcome(
            db,
            user_id             = _uid(),
            surface             = "feed",
            item_ref            = "x",
            adjusted_rank       = 1,
            intrinsic_rank      = 2,
            observed_engagement = True,
            run_override        = False,
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_orm_row(self, db):
        uid = _uid()
        row = await _record_outcome(db, uid, engaged=True)
        assert row is not None
        assert hasattr(row, "id")
        assert hasattr(row, "relevance_weight")


# ---------------------------------------------------------------------------
# 14–24: calculate_preference_accuracy
# ---------------------------------------------------------------------------

class TestCalculatePreferenceAccuracy:

    @pytest.mark.asyncio
    async def test_no_rows_insufficient(self, db):
        from app.services.user_learning_calibration_service import calculate_preference_accuracy
        uid = _uid()
        result = await calculate_preference_accuracy(db, user_id=uid, run_override=True)
        assert result["accuracy"] is None
        assert result["sufficient_samples"] is False

    @pytest.mark.asyncio
    async def test_all_engaged_accuracy_one(self, db):
        from app.services.user_learning_calibration_service import calculate_preference_accuracy
        uid = _uid()
        for i in range(5):
            await _record_outcome(db, uid, engaged=True, item_ref=f"item_{i}")
        result = await calculate_preference_accuracy(db, user_id=uid, run_override=True)
        assert result["accuracy"] == 1.0

    @pytest.mark.asyncio
    async def test_all_not_engaged_accuracy_zero(self, db):
        from app.services.user_learning_calibration_service import calculate_preference_accuracy
        uid = _uid()
        for i in range(5):
            await _record_outcome(db, uid, engaged=False, item_ref=f"item_{i}")
        result = await calculate_preference_accuracy(db, user_id=uid, run_override=True)
        assert result["accuracy"] == 0.0

    @pytest.mark.asyncio
    async def test_mixed_accuracy(self, db):
        from app.services.user_learning_calibration_service import calculate_preference_accuracy
        uid = _uid()
        for i in range(3):
            await _record_outcome(db, uid, engaged=True, item_ref=f"eng_{i}")
        for i in range(2):
            await _record_outcome(db, uid, engaged=False, item_ref=f"ign_{i}")
        result = await calculate_preference_accuracy(db, user_id=uid, run_override=True)
        assert result["accuracy"] == pytest.approx(0.6, abs=0.0001)

    @pytest.mark.asyncio
    async def test_below_min_samples_insufficient(self, db):
        from app.services.user_learning_calibration_service import calculate_preference_accuracy
        uid = _uid()
        for i in range(4):
            await _record_outcome(db, uid, engaged=True, item_ref=f"item_{i}")
        result = await calculate_preference_accuracy(db, user_id=uid, run_override=True)
        assert result["sufficient_samples"] is False
        assert result["accuracy"] is None

    @pytest.mark.asyncio
    async def test_at_min_samples_sufficient(self, db):
        from app.services.user_learning_calibration_service import calculate_preference_accuracy
        uid = _uid()
        for i in range(5):
            await _record_outcome(db, uid, engaged=True, item_ref=f"item_{i}")
        result = await calculate_preference_accuracy(db, user_id=uid, run_override=True)
        assert result["sufficient_samples"] is True

    @pytest.mark.asyncio
    async def test_engaged_count_present(self, db):
        from app.services.user_learning_calibration_service import calculate_preference_accuracy
        uid = _uid()
        for i in range(5):
            await _record_outcome(db, uid, engaged=True, item_ref=f"item_{i}")
        result = await calculate_preference_accuracy(db, user_id=uid, run_override=True)
        assert "engaged_count" in result
        assert result["engaged_count"] == 5

    @pytest.mark.asyncio
    async def test_not_engaged_count_present(self, db):
        from app.services.user_learning_calibration_service import calculate_preference_accuracy
        uid = _uid()
        for i in range(3):
            await _record_outcome(db, uid, engaged=True, item_ref=f"eng_{i}")
        for i in range(2):
            await _record_outcome(db, uid, engaged=False, item_ref=f"ign_{i}")
        result = await calculate_preference_accuracy(db, user_id=uid, run_override=True)
        assert result["not_engaged_count"] == 2

    @pytest.mark.asyncio
    async def test_total_count_present(self, db):
        from app.services.user_learning_calibration_service import calculate_preference_accuracy
        uid = _uid()
        for i in range(5):
            await _record_outcome(db, uid, engaged=True, item_ref=f"item_{i}")
        result = await calculate_preference_accuracy(db, user_id=uid, run_override=True)
        assert result["total_count"] == 5

    @pytest.mark.asyncio
    async def test_null_session_empty_dict(self):
        from app.services.user_learning_calibration_service import calculate_preference_accuracy
        uid = _uid()
        result = await calculate_preference_accuracy(None, user_id=uid, run_override=True)
        assert isinstance(result, dict)
        assert result["accuracy"] is None
        assert result["sufficient_samples"] is False

    @pytest.mark.asyncio
    async def test_flag_off_empty_dict(self, db):
        from app.services.user_learning_calibration_service import calculate_preference_accuracy
        uid = _uid()
        result = await calculate_preference_accuracy(db, user_id=uid, run_override=False)
        assert isinstance(result, dict)
        assert result["accuracy"] is None


# ---------------------------------------------------------------------------
# 25–32: calculate_preference_drift
# ---------------------------------------------------------------------------

class TestCalculatePreferenceDrift:

    @pytest.mark.asyncio
    async def test_no_prefs_insufficient(self, db):
        from app.services.user_learning_calibration_service import calculate_preference_drift
        uid = _uid()
        result = await calculate_preference_drift(db, user_id=uid, run_override=True)
        assert result["drift_score"] is None
        assert result["sufficient_samples"] is False

    @pytest.mark.asyncio
    async def test_high_confidence_low_drift(self, db):
        from app.services.user_learning_calibration_service import calculate_preference_drift
        uid = _uid()
        for _ in range(3):
            await _add_pref(db, uid, confidence=0.9)
        result = await calculate_preference_drift(db, user_id=uid, run_override=True)
        assert result["drift_score"] is not None
        assert result["drift_score"] < 0.2

    @pytest.mark.asyncio
    async def test_low_confidence_high_drift(self, db):
        from app.services.user_learning_calibration_service import calculate_preference_drift
        uid = _uid()
        for _ in range(3):
            await _add_pref(db, uid, confidence=0.1)
        result = await calculate_preference_drift(db, user_id=uid, run_override=True)
        assert result["drift_score"] is not None
        assert result["drift_score"] > 0.8

    @pytest.mark.asyncio
    async def test_falsified_excluded(self, db):
        from app.services.user_learning_calibration_service import calculate_preference_drift
        uid = _uid()
        await _add_pref(db, uid, confidence=0.9, status="active")
        await _add_pref(db, uid, confidence=0.1, status="falsified")
        result = await calculate_preference_drift(db, user_id=uid, run_override=True)
        # Only 1 active row → insufficient samples
        assert result["sufficient_samples"] is False

    @pytest.mark.asyncio
    async def test_preference_count_present(self, db):
        from app.services.user_learning_calibration_service import calculate_preference_drift
        uid = _uid()
        await _add_pref(db, uid, confidence=0.7)
        await _add_pref(db, uid, confidence=0.7)
        result = await calculate_preference_drift(db, user_id=uid, run_override=True)
        assert "preference_count" in result
        assert result["preference_count"] == 2

    @pytest.mark.asyncio
    async def test_one_pref_insufficient(self, db):
        from app.services.user_learning_calibration_service import calculate_preference_drift
        uid = _uid()
        await _add_pref(db, uid, confidence=0.8)
        result = await calculate_preference_drift(db, user_id=uid, run_override=True)
        assert result["sufficient_samples"] is False

    @pytest.mark.asyncio
    async def test_null_session_empty(self):
        from app.services.user_learning_calibration_service import calculate_preference_drift
        result = await calculate_preference_drift(None, user_id=_uid(), run_override=True)
        assert result["drift_score"] is None

    @pytest.mark.asyncio
    async def test_flag_off_empty(self, db):
        from app.services.user_learning_calibration_service import calculate_preference_drift
        result = await calculate_preference_drift(db, user_id=_uid(), run_override=False)
        assert result["drift_score"] is None


# ---------------------------------------------------------------------------
# 33–41: calculate_false_preference_rate
# ---------------------------------------------------------------------------

class TestCalculateFalsePreferenceRate:

    @pytest.mark.asyncio
    async def test_no_rows_insufficient(self, db):
        from app.services.user_learning_calibration_service import calculate_false_preference_rate
        uid = _uid()
        result = await calculate_false_preference_rate(db, user_id=uid, run_override=True)
        assert result["false_preference_rate"] is None
        assert result["sufficient_samples"] is False

    @pytest.mark.asyncio
    async def test_all_boosted_engaged_fpr_zero(self, db):
        from app.services.user_learning_calibration_service import calculate_false_preference_rate
        uid = _uid()
        for i in range(3):
            await _record_outcome(
                db, uid, engaged=True,
                adjusted_rank=2, intrinsic_rank=5, item_ref=f"item_{i}",
            )
        result = await calculate_false_preference_rate(db, user_id=uid, run_override=True)
        assert result["false_preference_rate"] == 0.0

    @pytest.mark.asyncio
    async def test_all_boosted_not_engaged_fpr_one(self, db):
        from app.services.user_learning_calibration_service import calculate_false_preference_rate
        uid = _uid()
        for i in range(3):
            await _record_outcome(
                db, uid, engaged=False,
                adjusted_rank=1, intrinsic_rank=4, item_ref=f"item_{i}",
            )
        result = await calculate_false_preference_rate(db, user_id=uid, run_override=True)
        assert result["false_preference_rate"] == 1.0

    @pytest.mark.asyncio
    async def test_non_boosted_excluded(self, db):
        from app.services.user_learning_calibration_service import calculate_false_preference_rate
        uid = _uid()
        # 3 boosted + engaged
        for i in range(3):
            await _record_outcome(
                db, uid, engaged=True,
                adjusted_rank=2, intrinsic_rank=5, item_ref=f"boost_{i}",
            )
        # 5 not-boosted + not-engaged (adjusted >= intrinsic → not counted)
        for i in range(5):
            await _record_outcome(
                db, uid, engaged=False,
                adjusted_rank=5, intrinsic_rank=5, item_ref=f"flat_{i}",
            )
        result = await calculate_false_preference_rate(db, user_id=uid, run_override=True)
        # only 3 boosted rows count; 0 false
        assert result["false_preference_rate"] == 0.0
        assert result["boosted_total"] == 3

    @pytest.mark.asyncio
    async def test_mixed_fpr(self, db):
        from app.services.user_learning_calibration_service import calculate_false_preference_rate
        uid = _uid()
        # 2 boosted + engaged
        for i in range(2):
            await _record_outcome(
                db, uid, engaged=True,
                adjusted_rank=1, intrinsic_rank=5, item_ref=f"good_{i}",
            )
        # 1 boosted + not engaged
        await _record_outcome(
            db, uid, engaged=False,
            adjusted_rank=2, intrinsic_rank=6, item_ref="bad_0",
        )
        result = await calculate_false_preference_rate(db, user_id=uid, run_override=True)
        assert result["false_preference_rate"] == pytest.approx(1 / 3, abs=0.001)

    @pytest.mark.asyncio
    async def test_below_min_boosted_insufficient(self, db):
        from app.services.user_learning_calibration_service import calculate_false_preference_rate
        uid = _uid()
        for i in range(2):
            await _record_outcome(
                db, uid, engaged=True,
                adjusted_rank=1, intrinsic_rank=5, item_ref=f"item_{i}",
            )
        result = await calculate_false_preference_rate(db, user_id=uid, run_override=True)
        assert result["sufficient_samples"] is False

    @pytest.mark.asyncio
    async def test_null_session_empty(self):
        from app.services.user_learning_calibration_service import calculate_false_preference_rate
        result = await calculate_false_preference_rate(None, user_id=_uid(), run_override=True)
        assert result["false_preference_rate"] is None

    @pytest.mark.asyncio
    async def test_flag_off_empty(self, db):
        from app.services.user_learning_calibration_service import calculate_false_preference_rate
        result = await calculate_false_preference_rate(db, user_id=_uid(), run_override=False)
        assert result["false_preference_rate"] is None

    @pytest.mark.asyncio
    async def test_boosted_total_and_false_count_present(self, db):
        from app.services.user_learning_calibration_service import calculate_false_preference_rate
        uid = _uid()
        for i in range(3):
            await _record_outcome(
                db, uid, engaged=i < 2,
                adjusted_rank=1, intrinsic_rank=5, item_ref=f"item_{i}",
            )
        result = await calculate_false_preference_rate(db, user_id=uid, run_override=True)
        assert "boosted_total" in result
        assert "false_count" in result


# ---------------------------------------------------------------------------
# 42–49: calculate_preference_stability
# ---------------------------------------------------------------------------

class TestCalculatePreferenceStability:

    @pytest.mark.asyncio
    async def test_no_prefs_insufficient(self, db):
        from app.services.user_learning_calibration_service import calculate_preference_stability
        uid = _uid()
        result = await calculate_preference_stability(db, user_id=uid, run_override=True)
        assert result["stability_score"] is None
        assert result["sufficient_samples"] is False

    @pytest.mark.asyncio
    async def test_high_confidence_high_stability(self, db):
        from app.services.user_learning_calibration_service import calculate_preference_stability
        uid = _uid()
        for _ in range(3):
            await _add_pref(db, uid, confidence=0.9)
        result = await calculate_preference_stability(db, user_id=uid, run_override=True)
        assert result["stability_score"] is not None
        assert result["stability_score"] > 0.8

    @pytest.mark.asyncio
    async def test_low_confidence_low_stability(self, db):
        from app.services.user_learning_calibration_service import calculate_preference_stability
        uid = _uid()
        for _ in range(3):
            await _add_pref(db, uid, confidence=0.1)
        result = await calculate_preference_stability(db, user_id=uid, run_override=True)
        assert result["stability_score"] is not None
        assert result["stability_score"] < 0.2

    @pytest.mark.asyncio
    async def test_falsified_excluded(self, db):
        from app.services.user_learning_calibration_service import calculate_preference_stability
        uid = _uid()
        await _add_pref(db, uid, confidence=0.9, status="active")
        await _add_pref(db, uid, confidence=0.1, status="falsified")
        result = await calculate_preference_stability(db, user_id=uid, run_override=True)
        # Only 1 active row → insufficient
        assert result["sufficient_samples"] is False

    @pytest.mark.asyncio
    async def test_preference_count_present(self, db):
        from app.services.user_learning_calibration_service import calculate_preference_stability
        uid = _uid()
        await _add_pref(db, uid, confidence=0.7)
        await _add_pref(db, uid, confidence=0.7)
        result = await calculate_preference_stability(db, user_id=uid, run_override=True)
        assert "preference_count" in result
        assert result["preference_count"] == 2

    @pytest.mark.asyncio
    async def test_one_pref_insufficient(self, db):
        from app.services.user_learning_calibration_service import calculate_preference_stability
        uid = _uid()
        await _add_pref(db, uid, confidence=0.8)
        result = await calculate_preference_stability(db, user_id=uid, run_override=True)
        assert result["sufficient_samples"] is False

    @pytest.mark.asyncio
    async def test_null_session_empty(self):
        from app.services.user_learning_calibration_service import calculate_preference_stability
        result = await calculate_preference_stability(None, user_id=_uid(), run_override=True)
        assert result["stability_score"] is None

    @pytest.mark.asyncio
    async def test_flag_off_empty(self, db):
        from app.services.user_learning_calibration_service import calculate_preference_stability
        result = await calculate_preference_stability(db, user_id=_uid(), run_override=False)
        assert result["stability_score"] is None


# ---------------------------------------------------------------------------
# 50–59: summarize_preference_calibration
# ---------------------------------------------------------------------------

class TestSummarizePreferenceCalibration:

    @pytest.mark.asyncio
    async def test_contains_accuracy_key(self, db):
        from app.services.user_learning_calibration_service import summarize_preference_calibration
        result = await summarize_preference_calibration(db, user_id=_uid(), run_override=True)
        assert "accuracy" in result

    @pytest.mark.asyncio
    async def test_contains_drift_key(self, db):
        from app.services.user_learning_calibration_service import summarize_preference_calibration
        result = await summarize_preference_calibration(db, user_id=_uid(), run_override=True)
        assert "drift" in result

    @pytest.mark.asyncio
    async def test_contains_fpr_key(self, db):
        from app.services.user_learning_calibration_service import summarize_preference_calibration
        result = await summarize_preference_calibration(db, user_id=_uid(), run_override=True)
        assert "false_preference_rate" in result

    @pytest.mark.asyncio
    async def test_contains_stability_key(self, db):
        from app.services.user_learning_calibration_service import summarize_preference_calibration
        result = await summarize_preference_calibration(db, user_id=_uid(), run_override=True)
        assert "stability" in result

    @pytest.mark.asyncio
    async def test_contains_user_id(self, db):
        from app.services.user_learning_calibration_service import summarize_preference_calibration
        uid = _uid()
        result = await summarize_preference_calibration(db, user_id=uid, run_override=True)
        assert result["user_id"] == uid

    @pytest.mark.asyncio
    async def test_contains_generated_at(self, db):
        from app.services.user_learning_calibration_service import summarize_preference_calibration
        result = await summarize_preference_calibration(db, user_id=_uid(), run_override=True)
        assert "generated_at" in result
        assert isinstance(result["generated_at"], str)

    @pytest.mark.asyncio
    async def test_calibration_schema_value(self, db):
        from app.services.user_learning_calibration_service import summarize_preference_calibration
        result = await summarize_preference_calibration(db, user_id=_uid(), run_override=True)
        assert result["calibration_schema"] == 1

    @pytest.mark.asyncio
    async def test_null_session_structurally_complete(self):
        from app.services.user_learning_calibration_service import summarize_preference_calibration
        uid = _uid()
        result = await summarize_preference_calibration(None, user_id=uid, run_override=True)
        for key in ("accuracy", "drift", "false_preference_rate", "stability",
                    "user_id", "generated_at", "calibration_schema"):
            assert key in result, f"missing key: {key}"

    @pytest.mark.asyncio
    async def test_flag_off_structurally_complete(self, db):
        from app.services.user_learning_calibration_service import summarize_preference_calibration
        uid = _uid()
        result = await summarize_preference_calibration(db, user_id=uid, run_override=False)
        for key in ("accuracy", "drift", "false_preference_rate", "stability",
                    "user_id", "generated_at", "calibration_schema"):
            assert key in result, f"missing key: {key}"

    @pytest.mark.asyncio
    async def test_sub_dicts_have_sufficient_samples(self, db):
        from app.services.user_learning_calibration_service import summarize_preference_calibration
        result = await summarize_preference_calibration(db, user_id=_uid(), run_override=True)
        for sub_key in ("accuracy", "drift", "false_preference_rate", "stability"):
            sub = result[sub_key]
            assert "sufficient_samples" in sub, f"missing sufficient_samples in {sub_key}"


# ---------------------------------------------------------------------------
# 60–62: no truth mutation
# ---------------------------------------------------------------------------

class TestNoTruthMutation:

    @pytest.mark.asyncio
    async def test_learned_preference_unchanged(self, db):
        from app.db.repositories.user_learning_repo import list_learned_preferences
        uid = _uid()
        await _add_pref(db, uid, confidence=0.7)
        before = await list_learned_preferences(db, user_id=uid)
        before_conf = [float(p.confidence) for p in before]

        await _record_outcome(db, uid, engaged=True)

        after = await list_learned_preferences(db, user_id=uid)
        after_conf = [float(p.confidence) for p in after]
        assert before_conf == after_conf

    @pytest.mark.asyncio
    async def test_signal_event_unchanged(self, db):
        from app.db.repositories.user_learning_repo import (
            add_user_signal_event,
            list_user_signal_events,
        )
        uid = _uid()
        from datetime import datetime, timezone
        await add_user_signal_event(
            db,
            user_id        = uid,
            entity_key     = "AAPL",
            signal_type    = "mention",
            polarity       = "positive",
            source_surface = "test",
            occurred_at    = datetime.now(timezone.utc),
        )
        before = await list_user_signal_events(db, user_id=uid)
        before_count = len(before)

        await _record_outcome(db, uid, engaged=True)

        after = await list_user_signal_events(db, user_id=uid)
        assert len(after) == before_count

    @pytest.mark.asyncio
    async def test_no_notification_rows(self, db):
        uid = _uid()
        await _record_outcome(db, uid, engaged=True)
        from sqlalchemy import text
        try:
            result = await db.execute(
                text("SELECT COUNT(*) FROM notification WHERE user_id = :uid"),
                {"uid": uid},
            )
            count = result.scalar_one()
        except Exception:
            count = 0
        assert count == 0


# ---------------------------------------------------------------------------
# 63–65: append-only
# ---------------------------------------------------------------------------

class TestAppendOnly:

    @pytest.mark.asyncio
    async def test_row_count_increments(self, db):
        from app.db.repositories.user_learning_repo import count_relevance_adjustment_logs
        uid = _uid()
        c0 = await count_relevance_adjustment_logs(db, user_id=uid, run_reason="calibration")
        await _record_outcome(db, uid, engaged=True, item_ref="a")
        c1 = await count_relevance_adjustment_logs(db, user_id=uid, run_reason="calibration")
        await _record_outcome(db, uid, engaged=False, item_ref="b")
        c2 = await count_relevance_adjustment_logs(db, user_id=uid, run_reason="calibration")
        assert c1 == c0 + 1
        assert c2 == c0 + 2

    @pytest.mark.asyncio
    async def test_two_calls_two_rows(self, db):
        from app.db.repositories.user_learning_repo import list_relevance_adjustment_logs
        uid = _uid()
        r1 = await _record_outcome(db, uid, engaged=True, item_ref="item_A")
        r2 = await _record_outcome(db, uid, engaged=False, item_ref="item_B")
        rows = await list_relevance_adjustment_logs(db, user_id=uid, run_reason="calibration")
        ids = {getattr(r, "id", None) for r in rows}
        assert r1.id in ids
        assert r2.id in ids
        assert r1.id != r2.id

    def test_no_update_or_delete_in_source(self):
        src = _SVC_PATH.read_text()
        tree = ast.parse(src)
        call_names = {
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
        }
        assert "delete" not in call_names
        assert "update" not in call_names


# ---------------------------------------------------------------------------
# 66–67: tenant isolation
# ---------------------------------------------------------------------------

class TestTenantIsolation:

    @pytest.mark.asyncio
    async def test_user_a_rows_not_counted_for_user_b(self, db):
        from app.services.user_learning_calibration_service import calculate_preference_accuracy
        uid_a = _uid()
        uid_b = _uid()
        for i in range(5):
            await _record_outcome(db, uid_a, engaged=True, item_ref=f"item_{i}")
        result_b = await calculate_preference_accuracy(db, user_id=uid_b, run_override=True)
        assert result_b["sufficient_samples"] is False

    @pytest.mark.asyncio
    async def test_user_b_independent_stability(self, db):
        from app.services.user_learning_calibration_service import calculate_preference_stability
        uid_a = _uid()
        uid_b = _uid()
        for _ in range(3):
            await _add_pref(db, uid_a, confidence=0.9)
        result_b = await calculate_preference_stability(db, user_id=uid_b, run_override=True)
        assert result_b["sufficient_samples"] is False


# ---------------------------------------------------------------------------
# 68–72: AST safety
# ---------------------------------------------------------------------------

def _load_ast():
    return ast.parse(_SVC_PATH.read_text())


def _docstring_node_ids(tree: ast.AST):
    ids = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            if (
                node.body
                and isinstance(node.body[0], ast.Expr)
                and isinstance(node.body[0].value, ast.Constant)
            ):
                ids.add(id(node.body[0].value))
    return ids


def _import_names(tree: ast.AST):
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            names.add(node.module or "")
            for alias in node.names:
                names.add(alias.name)
    return names


_BANNED_PHRASES = (
    "buy", "sell", "hold", "overweight", "underweight",
    "recommend", "target price", "position size",
    "take a position", "enter a trade", "exit a trade",
    "place an order", "execute", "short", "long position",
    "go long", "go short", "open a position", "close a position",
)

_TRUTH_WRITE_FNS = (
    "add_forecast", "update_forecast", "add_decision", "update_decision",
    "add_scenario", "update_scenario", "add_ticker_memory", "update_ticker_memory",
    "add_similarity_score", "update_similarity_score",
)

_FORBIDDEN_IMPORTS = (
    "conviction", "order", "execution", "stance", "verdict",
)


class TestAstSafety:

    def test_no_truth_table_write_imports(self):
        names = _import_names(_load_ast())
        for fn in _TRUTH_WRITE_FNS:
            assert fn not in names, f"forbidden import: {fn}"

    def test_no_conviction_order_execution_imports(self):
        names = _import_names(_load_ast())
        for forbidden in _FORBIDDEN_IMPORTS:
            for name in names:
                assert forbidden not in name.lower(), f"forbidden import contains '{forbidden}': {name}"

    def test_no_banned_advisory_phrases(self):
        tree = _load_ast()
        docstring_ids = _docstring_node_ids(tree)
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and id(node) not in docstring_ids
            ):
                low = node.value.lower()
                for phrase in _BANNED_PHRASES:
                    assert phrase not in low, (
                        f"banned phrase '{phrase}' found in string: {node.value!r}"
                    )

    def test_no_notification_writes(self):
        src = _SVC_PATH.read_text()
        tree = ast.parse(src)
        import_names = _import_names(tree)
        call_names = {
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
        }
        assert "Notification" not in import_names
        assert "add_notification" not in call_names
        assert "add_notification" not in import_names

    def test_only_calibration_run_reason_in_writes(self):
        tree = _load_ast()
        docstring_ids = _docstring_node_ids(tree)
        # Collect all string literals passed as run_reason keyword arg
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                for kw in node.keywords:
                    if kw.arg == "run_reason" and isinstance(kw.value, ast.Constant):
                        val = kw.value.value
                        assert val == "calibration", (
                            f"unexpected run_reason value: {val!r}"
                        )
