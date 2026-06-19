"""
Tests — User Learning Relevance Service, Phase 15 · Slice 8.

Covers:
  1.  service importable
  2.  all 5 public functions present
  3.  flag gate: all functions return empty when run_override=False
  4.  null-session: all functions return empty when session=None (flag=True)

  --- compute_relevance_adjustment ---
  5.  positive company_interest preference → factor > 1.0
  6.  ignored_signal_type preference → factor < 1.0
  7.  no preference → factor = 1.0, reason = "no_preference"
  8.  falsified preference treated as no preference
  9.  relevance_score = intrinsic_score × relevance_adjustment
  10. company_interest dimension active for entity_type="company"
  11. portfolio_sensitivity dimension active for entity_type="company"
  12. sector_interest dimension active for entity_type="sector"
  13. theme_interest dimension active for entity_type="theme"
  14. preferred_horizon dimension active for entity_type="horizon"
  15. preferred_signal_type dimension active for entity_type="signal_type"
  16. ignored_signal_type dimension active for entity_type="signal_type"
  17. adjustment_reason starts with "positive_pref:" when boosted
  18. adjustment_reason starts with "ignored_pref:" when penalised
  19. adjustment_reason = "no_preference" for unmatched item
  20. novelty_reserve_applied always False for single-item call
  21. adjusted_rank equals intrinsic_rank for single-item call
  22. company item with both company_interest and portfolio_sensitivity → max boost
  23. strong preference (affinity=1.0, confidence=1.0) → factor = 1 + MAX_BOOST
  24. strong ignored preference (affinity=-1.0, confidence=1.0) → factor = 1 - MAX_PENALTY
  25. factor never below _FACTOR_FLOOR even for very strong penalty
  26. relevance_floor_applied = False for non-critical signal_type
  27. prominence_tier = "pinned" when factor >= _PINNED_TIER_FACTOR
  28. prominence_tier = "muted" when factor < _MUTED_TIER_FACTOR
  29. prominence_tier = "normal" for middle-range factor

  --- compute_relevance_floor ---
  30. critical signal (earnings) with muted tier → floor_applied = True
  31. critical signal with muted tier → effective_prominence_tier = "normal"
  32. non-critical signal with muted tier → floor_applied = False
  33. critical signal not muted → floor_applied = False
  34. floor result contains item_ref, signal_type, floor_applied,
      original_prominence_tier, effective_prominence_tier
  35. flag off → floor_applied = False
  36. null session → floor_applied = False

  --- apply_relevance_adjustment ---
  37. returns same count as input
  38. items re-ranked by relevance_score descending
  39. highest-scoring item gets adjusted_rank = 1
  40. ties in relevance_score broken by item_ref ascending
  41. all items have 12 required projection fields
  42. intrinsic_rank preserved in output
  43. no-preference items factor = 1.0 throughout list
  44. flag off → identity adjustments sorted by intrinsic_rank
  45. null session → identity adjustments sorted by intrinsic_rank

  --- compute_novelty_reserve ---
  46. empty items → empty reserve summary
  47. all-novel list → reserve_applied = False (reserve naturally satisfied)
  48. no novel items → reserve_applied = False
  49. novel items buried by personalised items → reserve_applied = True
  50. promoted items appear in reserve_item_refs
  51. reserve_fraction_target matches parameter
  52. protected_count >= 0
  53. item count < _MIN_ITEMS_FOR_RESERVE → reserve_count = 0, reserve_applied = False
  54. flag off → empty reserve summary
  55. null session → empty reserve summary

  --- build_relevance_projection ---
  56. empty items list → []
  57. output count equals input count
  58. adjusted_ranks are sequential 1..N
  59. highest relevance_score has adjusted_rank = 1
  60. all projection items have 12 required fields
  61. boosted item outranks its original intrinsic position
  62. penalised item drops below its original intrinsic position
  63. novelty_reserve_applied = True on promoted novel items
  64. novelty_reserve_applied = False on items already in top-N
  65. relevance_floor_applied = True for critical signal with muted tier
  66. projection never contains "hidden" as prominence_tier
  67. deterministic: same inputs produce identical projection twice
  68. flag off → []
  69. null session → []

  --- no truth mutation ---
  70. learned_preference rows unchanged after build_relevance_projection
  71. user_signal_event rows unchanged after build_relevance_projection
  72. row counts stable before and after projection call

  --- tenant isolation ---
  73. user A preference does not affect user B projection
  74. user B gets identity adjustment when A has preferences

  --- AST safety ---
  75. no truth-table write imports in relevance service
  76. no conviction / order / execution imports
  77. no banned advisory phrases in non-docstring string constants
  78. no upsert / insert / delete calls in service source
  79. no add_relevance_adjustment_log calls (shadow-only)
  80. no truth module read imports (forecast/similarity/decision/scenario)
"""

from __future__ import annotations

import ast
import pathlib
import uuid
from typing import Any, Dict

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

_ROOT     = pathlib.Path(__file__).parent.parent.parent
_SVC_PATH = _ROOT / "app" / "services" / "user_learning_relevance_service.py"

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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _add_pref(
    session,
    *,
    user_id: str,
    dimension: str,
    entity_key: str,
    affinity: float = 0.8,
    confidence: float = 0.8,
    evidence_count: int = 8,
    status: str = "unresolved",
    signal_strength_label: str = "strong",
):
    from app.db.repositories.user_learning_repo import upsert_learned_preference
    return await upsert_learned_preference(
        session,
        user_id=user_id,
        dimension=dimension,
        entity_key=entity_key,
        affinity=affinity,
        confidence=confidence,
        evidence_count=evidence_count,
        status=status,
        signal_strength_label=signal_strength_label,
        belief_basis=f"test basis for {entity_key}",
        falsifier="",
    )


def _item(
    *,
    item_ref: str = "item_001",
    entity_key: str = "AAPL",
    entity_type: str = "company",
    signal_type: str = "analyst_note",
    intrinsic_rank: int = 1,
    intrinsic_score: float = 0.8,
) -> Dict[str, Any]:
    return {
        "item_ref":        item_ref,
        "entity_key":      entity_key,
        "entity_type":     entity_type,
        "signal_type":     signal_type,
        "intrinsic_rank":  intrinsic_rank,
        "intrinsic_score": intrinsic_score,
    }


_REQUIRED_FIELDS = {
    "item_ref", "entity_key", "entity_type", "signal_type",
    "intrinsic_rank", "adjusted_rank", "intrinsic_score",
    "relevance_score", "relevance_adjustment", "adjustment_reason",
    "novelty_reserve_applied", "relevance_floor_applied", "prominence_tier",
}


# ---------------------------------------------------------------------------
# 1–2. Import and presence
# ---------------------------------------------------------------------------

class TestImport:
    def test_service_importable(self):
        import app.services.user_learning_relevance_service  # noqa: F401

    def test_all_public_functions_present(self):
        import app.services.user_learning_relevance_service as svc
        for name in (
            "compute_relevance_adjustment",
            "apply_relevance_adjustment",
            "compute_novelty_reserve",
            "compute_relevance_floor",
            "build_relevance_projection",
        ):
            assert callable(getattr(svc, name, None)), f"Missing: {name}"


# ---------------------------------------------------------------------------
# 3–4. Flag gate and null-session
# ---------------------------------------------------------------------------

class TestFlagGate:
    @pytest.mark.asyncio
    async def test_compute_adjustment_flag_off(self, db):
        from app.services.user_learning_relevance_service import compute_relevance_adjustment
        r = await compute_relevance_adjustment(db, user_id=_uid(), item=_item(), run_override=False)
        assert r["relevance_adjustment"] == 1.0
        assert r["adjustment_reason"] == "no_preference"

    @pytest.mark.asyncio
    async def test_apply_adjustment_flag_off(self, db):
        from app.services.user_learning_relevance_service import apply_relevance_adjustment
        items = [_item(item_ref="a"), _item(item_ref="b")]
        r = await apply_relevance_adjustment(db, user_id=_uid(), items=items, run_override=False)
        assert all(x["relevance_adjustment"] == 1.0 for x in r)

    @pytest.mark.asyncio
    async def test_novelty_reserve_flag_off(self, db):
        from app.services.user_learning_relevance_service import compute_novelty_reserve
        items = [_item()]
        r = await compute_novelty_reserve(db, user_id=_uid(), items=items, run_override=False)
        assert r["reserve_applied"] is False
        assert r["novel_item_count"] == 0

    @pytest.mark.asyncio
    async def test_floor_flag_off(self, db):
        from app.services.user_learning_relevance_service import compute_relevance_floor
        r = await compute_relevance_floor(db, user_id=_uid(), item=_item(), run_override=False)
        assert r["floor_applied"] is False

    @pytest.mark.asyncio
    async def test_projection_flag_off(self, db):
        from app.services.user_learning_relevance_service import build_relevance_projection
        r = await build_relevance_projection(db, user_id=_uid(), items=[_item()], run_override=False)
        assert r == []

    @pytest.mark.asyncio
    async def test_compute_adjustment_null_session(self):
        from app.services.user_learning_relevance_service import compute_relevance_adjustment
        r = await compute_relevance_adjustment(None, user_id=_uid(), item=_item(), run_override=True)
        assert r["relevance_adjustment"] == 1.0

    @pytest.mark.asyncio
    async def test_apply_adjustment_null_session(self):
        from app.services.user_learning_relevance_service import apply_relevance_adjustment
        r = await apply_relevance_adjustment(None, user_id=_uid(), items=[_item()], run_override=True)
        assert len(r) == 1
        assert r[0]["relevance_adjustment"] == 1.0

    @pytest.mark.asyncio
    async def test_novelty_reserve_null_session(self):
        from app.services.user_learning_relevance_service import compute_novelty_reserve
        r = await compute_novelty_reserve(None, user_id=_uid(), items=[_item()], run_override=True)
        assert r["reserve_applied"] is False

    @pytest.mark.asyncio
    async def test_floor_null_session(self):
        from app.services.user_learning_relevance_service import compute_relevance_floor
        r = await compute_relevance_floor(None, user_id=_uid(), item=_item(), run_override=True)
        assert r["floor_applied"] is False

    @pytest.mark.asyncio
    async def test_projection_null_session(self):
        from app.services.user_learning_relevance_service import build_relevance_projection
        r = await build_relevance_projection(None, user_id=_uid(), items=[_item()], run_override=True)
        assert r == []


# ---------------------------------------------------------------------------
# 5–29. compute_relevance_adjustment
# ---------------------------------------------------------------------------

class TestComputeRelevanceAdjustment:
    @pytest.mark.asyncio
    async def test_positive_company_interest_boosts(self, db):
        from app.services.user_learning_relevance_service import compute_relevance_adjustment
        uid = _uid()
        await _add_pref(db, user_id=uid, dimension="company_interest", entity_key="AAPL")
        r = await compute_relevance_adjustment(db, user_id=uid, item=_item(entity_key="AAPL"), run_override=True)
        assert r["relevance_adjustment"] > 1.0

    @pytest.mark.asyncio
    async def test_ignored_signal_type_penalises(self, db):
        from app.services.user_learning_relevance_service import compute_relevance_adjustment
        uid = _uid()
        await _add_pref(db, user_id=uid, dimension="ignored_signal_type", entity_key="analyst_note",
                        affinity=-0.8, confidence=0.8)
        r = await compute_relevance_adjustment(
            db, user_id=uid,
            item=_item(entity_key="analyst_note", entity_type="signal_type"),
            run_override=True,
        )
        assert r["relevance_adjustment"] < 1.0

    @pytest.mark.asyncio
    async def test_no_preference_identity_factor(self, db):
        from app.services.user_learning_relevance_service import compute_relevance_adjustment
        r = await compute_relevance_adjustment(db, user_id=_uid(), item=_item(), run_override=True)
        assert r["relevance_adjustment"] == 1.0
        assert r["adjustment_reason"] == "no_preference"

    @pytest.mark.asyncio
    async def test_falsified_preference_treated_as_none(self, db):
        from app.services.user_learning_relevance_service import compute_relevance_adjustment
        uid = _uid()
        await _add_pref(db, user_id=uid, dimension="company_interest", entity_key="AAPL",
                        status="falsified")
        r = await compute_relevance_adjustment(db, user_id=uid, item=_item(entity_key="AAPL"), run_override=True)
        assert r["relevance_adjustment"] == 1.0
        assert r["adjustment_reason"] == "no_preference"

    @pytest.mark.asyncio
    async def test_relevance_score_equals_score_times_factor(self, db):
        from app.services.user_learning_relevance_service import compute_relevance_adjustment
        uid = _uid()
        await _add_pref(db, user_id=uid, dimension="company_interest", entity_key="AAPL",
                        affinity=0.6, confidence=0.6)
        it = _item(entity_key="AAPL", intrinsic_score=0.5)
        r = await compute_relevance_adjustment(db, user_id=uid, item=it, run_override=True)
        assert abs(r["relevance_score"] - r["intrinsic_score"] * r["relevance_adjustment"]) < 1e-5

    @pytest.mark.asyncio
    async def test_company_interest_active_for_company_type(self, db):
        from app.services.user_learning_relevance_service import compute_relevance_adjustment
        uid = _uid()
        await _add_pref(db, user_id=uid, dimension="company_interest", entity_key="MSFT")
        r = await compute_relevance_adjustment(
            db, user_id=uid,
            item=_item(entity_key="MSFT", entity_type="company"),
            run_override=True,
        )
        assert r["relevance_adjustment"] > 1.0

    @pytest.mark.asyncio
    async def test_portfolio_sensitivity_active_for_company_type(self, db):
        from app.services.user_learning_relevance_service import compute_relevance_adjustment
        uid = _uid()
        await _add_pref(db, user_id=uid, dimension="portfolio_sensitivity", entity_key="NVDA")
        r = await compute_relevance_adjustment(
            db, user_id=uid,
            item=_item(entity_key="NVDA", entity_type="company"),
            run_override=True,
        )
        assert r["relevance_adjustment"] > 1.0

    @pytest.mark.asyncio
    async def test_sector_interest_active_for_sector_type(self, db):
        from app.services.user_learning_relevance_service import compute_relevance_adjustment
        uid = _uid()
        await _add_pref(db, user_id=uid, dimension="sector_interest", entity_key="tech")
        r = await compute_relevance_adjustment(
            db, user_id=uid,
            item=_item(entity_key="tech", entity_type="sector"),
            run_override=True,
        )
        assert r["relevance_adjustment"] > 1.0

    @pytest.mark.asyncio
    async def test_theme_interest_active_for_theme_type(self, db):
        from app.services.user_learning_relevance_service import compute_relevance_adjustment
        uid = _uid()
        await _add_pref(db, user_id=uid, dimension="theme_interest", entity_key="ai_infra")
        r = await compute_relevance_adjustment(
            db, user_id=uid,
            item=_item(entity_key="ai_infra", entity_type="theme"),
            run_override=True,
        )
        assert r["relevance_adjustment"] > 1.0

    @pytest.mark.asyncio
    async def test_preferred_horizon_active_for_horizon_type(self, db):
        from app.services.user_learning_relevance_service import compute_relevance_adjustment
        uid = _uid()
        await _add_pref(db, user_id=uid, dimension="preferred_horizon", entity_key="short")
        r = await compute_relevance_adjustment(
            db, user_id=uid,
            item=_item(entity_key="short", entity_type="horizon"),
            run_override=True,
        )
        assert r["relevance_adjustment"] > 1.0

    @pytest.mark.asyncio
    async def test_preferred_signal_type_active_for_signal_type(self, db):
        from app.services.user_learning_relevance_service import compute_relevance_adjustment
        uid = _uid()
        await _add_pref(db, user_id=uid, dimension="preferred_signal_type", entity_key="earnings")
        r = await compute_relevance_adjustment(
            db, user_id=uid,
            item=_item(entity_key="earnings", entity_type="signal_type"),
            run_override=True,
        )
        assert r["relevance_adjustment"] > 1.0

    @pytest.mark.asyncio
    async def test_ignored_signal_type_active_for_signal_type(self, db):
        from app.services.user_learning_relevance_service import compute_relevance_adjustment
        uid = _uid()
        await _add_pref(db, user_id=uid, dimension="ignored_signal_type", entity_key="macro_note",
                        affinity=-0.7, confidence=0.7)
        r = await compute_relevance_adjustment(
            db, user_id=uid,
            item=_item(entity_key="macro_note", entity_type="signal_type"),
            run_override=True,
        )
        assert r["relevance_adjustment"] < 1.0

    @pytest.mark.asyncio
    async def test_reason_starts_with_positive_pref_when_boosted(self, db):
        from app.services.user_learning_relevance_service import compute_relevance_adjustment
        uid = _uid()
        await _add_pref(db, user_id=uid, dimension="sector_interest", entity_key="health")
        r = await compute_relevance_adjustment(
            db, user_id=uid,
            item=_item(entity_key="health", entity_type="sector"),
            run_override=True,
        )
        assert r["adjustment_reason"].startswith("positive_pref:")

    @pytest.mark.asyncio
    async def test_reason_starts_with_ignored_pref_when_penalised(self, db):
        from app.services.user_learning_relevance_service import compute_relevance_adjustment
        uid = _uid()
        await _add_pref(db, user_id=uid, dimension="ignored_signal_type", entity_key="macro",
                        affinity=-0.5, confidence=0.5)
        r = await compute_relevance_adjustment(
            db, user_id=uid,
            item=_item(entity_key="macro", entity_type="signal_type"),
            run_override=True,
        )
        assert r["adjustment_reason"].startswith("ignored_pref:")

    @pytest.mark.asyncio
    async def test_reason_no_preference_for_unmatched(self, db):
        from app.services.user_learning_relevance_service import compute_relevance_adjustment
        r = await compute_relevance_adjustment(
            db, user_id=_uid(),
            item=_item(entity_key="UNKNOWN_XYZ"),
            run_override=True,
        )
        assert r["adjustment_reason"] == "no_preference"

    @pytest.mark.asyncio
    async def test_novelty_reserve_applied_always_false_single_item(self, db):
        from app.services.user_learning_relevance_service import compute_relevance_adjustment
        uid = _uid()
        await _add_pref(db, user_id=uid, dimension="company_interest", entity_key="AAPL")
        r = await compute_relevance_adjustment(db, user_id=uid, item=_item(), run_override=True)
        assert r["novelty_reserve_applied"] is False

    @pytest.mark.asyncio
    async def test_adjusted_rank_equals_intrinsic_rank_single_item(self, db):
        from app.services.user_learning_relevance_service import compute_relevance_adjustment
        r = await compute_relevance_adjustment(
            db, user_id=_uid(), item=_item(intrinsic_rank=5), run_override=True,
        )
        assert r["adjusted_rank"] == 5

    @pytest.mark.asyncio
    async def test_both_dimensions_company_takes_max_boost(self, db):
        from app.services.user_learning_relevance_service import compute_relevance_adjustment
        uid = _uid()
        # Weaker boost via company_interest
        await _add_pref(db, user_id=uid, dimension="company_interest", entity_key="AAPL",
                        affinity=0.4, confidence=0.4)
        # Stronger boost via portfolio_sensitivity
        await _add_pref(db, user_id=uid, dimension="portfolio_sensitivity", entity_key="AAPL",
                        affinity=0.9, confidence=0.9)
        r = await compute_relevance_adjustment(db, user_id=uid, item=_item(entity_key="AAPL"), run_override=True)
        from app.services.user_learning_relevance_service import _MAX_BOOST
        expected_factor = 1.0 + 0.9 * 0.9 * _MAX_BOOST
        assert abs(r["relevance_adjustment"] - expected_factor) < 0.001
        assert "portfolio_sensitivity" in r["adjustment_reason"]

    @pytest.mark.asyncio
    async def test_strong_preference_factor_equals_one_plus_max_boost(self, db):
        from app.services.user_learning_relevance_service import (
            compute_relevance_adjustment, _MAX_BOOST,
        )
        uid = _uid()
        await _add_pref(db, user_id=uid, dimension="company_interest", entity_key="AAPL",
                        affinity=1.0, confidence=1.0)
        r = await compute_relevance_adjustment(db, user_id=uid, item=_item(), run_override=True)
        assert abs(r["relevance_adjustment"] - (1.0 + _MAX_BOOST)) < 0.001

    @pytest.mark.asyncio
    async def test_strong_ignored_preference_factor(self, db):
        from app.services.user_learning_relevance_service import (
            compute_relevance_adjustment, _MAX_PENALTY,
        )
        uid = _uid()
        await _add_pref(db, user_id=uid, dimension="ignored_signal_type", entity_key="macro",
                        affinity=-1.0, confidence=1.0)
        r = await compute_relevance_adjustment(
            db, user_id=uid,
            item=_item(entity_key="macro", entity_type="signal_type"),
            run_override=True,
        )
        assert abs(r["relevance_adjustment"] - (1.0 - _MAX_PENALTY)) < 0.001

    @pytest.mark.asyncio
    async def test_factor_never_below_factor_floor(self, db):
        from app.services.user_learning_relevance_service import (
            compute_relevance_adjustment, _FACTOR_FLOOR,
        )
        uid = _uid()
        # Very aggressive penalty — should still floor at _FACTOR_FLOOR
        await _add_pref(db, user_id=uid, dimension="ignored_signal_type", entity_key="macro",
                        affinity=-1.0, confidence=1.0)
        r = await compute_relevance_adjustment(
            db, user_id=uid,
            item=_item(entity_key="macro", entity_type="signal_type"),
            run_override=True,
        )
        assert r["relevance_adjustment"] >= _FACTOR_FLOOR

    @pytest.mark.asyncio
    async def test_floor_not_applied_for_non_critical_signal(self, db):
        from app.services.user_learning_relevance_service import compute_relevance_adjustment
        uid = _uid()
        await _add_pref(db, user_id=uid, dimension="ignored_signal_type", entity_key="macro_note",
                        affinity=-1.0, confidence=1.0)
        r = await compute_relevance_adjustment(
            db, user_id=uid,
            item=_item(entity_key="macro_note", entity_type="signal_type", signal_type="macro_note"),
            run_override=True,
        )
        assert r["relevance_floor_applied"] is False

    @pytest.mark.asyncio
    async def test_prominence_tier_pinned_high_factor(self, db):
        from app.services.user_learning_relevance_service import (
            compute_relevance_adjustment, _PINNED_TIER_FACTOR,
        )
        uid = _uid()
        await _add_pref(db, user_id=uid, dimension="company_interest", entity_key="AAPL",
                        affinity=1.0, confidence=1.0)
        r = await compute_relevance_adjustment(db, user_id=uid, item=_item(), run_override=True)
        assert r["relevance_adjustment"] >= _PINNED_TIER_FACTOR
        assert r["prominence_tier"] == "pinned"

    @pytest.mark.asyncio
    async def test_prominence_tier_muted_low_factor(self, db):
        from app.services.user_learning_relevance_service import (
            compute_relevance_adjustment, _MUTED_TIER_FACTOR,
        )
        uid = _uid()
        await _add_pref(db, user_id=uid, dimension="ignored_signal_type", entity_key="macro",
                        affinity=-1.0, confidence=0.9)
        r = await compute_relevance_adjustment(
            db, user_id=uid,
            item=_item(entity_key="macro", entity_type="signal_type", signal_type="macro"),
            run_override=True,
        )
        assert r["relevance_adjustment"] < _MUTED_TIER_FACTOR
        assert r["prominence_tier"] == "muted"

    @pytest.mark.asyncio
    async def test_prominence_tier_normal_for_middle_factor(self, db):
        from app.services.user_learning_relevance_service import compute_relevance_adjustment
        uid = _uid()
        # Small positive boost → stays in "normal" range
        await _add_pref(db, user_id=uid, dimension="company_interest", entity_key="AAPL",
                        affinity=0.2, confidence=0.2)
        r = await compute_relevance_adjustment(db, user_id=uid, item=_item(), run_override=True)
        assert r["prominence_tier"] == "normal"


# ---------------------------------------------------------------------------
# 30–36. compute_relevance_floor
# ---------------------------------------------------------------------------

class TestComputeRelevanceFloor:
    @pytest.mark.asyncio
    async def test_earnings_with_muted_tier_floor_applied(self, db):
        from app.services.user_learning_relevance_service import compute_relevance_floor
        uid = _uid()
        # Strong penalty drives tier to muted
        await _add_pref(db, user_id=uid, dimension="ignored_signal_type", entity_key="earnings",
                        affinity=-1.0, confidence=0.9)
        item = _item(entity_key="earnings", entity_type="signal_type", signal_type="earnings")
        r = await compute_relevance_floor(db, user_id=uid, item=item, run_override=True)
        assert r["floor_applied"] is True

    @pytest.mark.asyncio
    async def test_earnings_muted_promoted_to_normal(self, db):
        from app.services.user_learning_relevance_service import compute_relevance_floor
        uid = _uid()
        await _add_pref(db, user_id=uid, dimension="ignored_signal_type", entity_key="earnings",
                        affinity=-1.0, confidence=0.9)
        item = _item(entity_key="earnings", entity_type="signal_type", signal_type="earnings")
        r = await compute_relevance_floor(db, user_id=uid, item=item, run_override=True)
        assert r["effective_prominence_tier"] == "normal"

    @pytest.mark.asyncio
    async def test_non_critical_muted_stays_muted(self, db):
        from app.services.user_learning_relevance_service import compute_relevance_floor
        uid = _uid()
        await _add_pref(db, user_id=uid, dimension="ignored_signal_type", entity_key="analyst_note",
                        affinity=-1.0, confidence=0.9)
        item = _item(entity_key="analyst_note", entity_type="signal_type", signal_type="analyst_note")
        r = await compute_relevance_floor(db, user_id=uid, item=item, run_override=True)
        assert r["floor_applied"] is False

    @pytest.mark.asyncio
    async def test_critical_signal_not_muted_floor_not_applied(self, db):
        from app.services.user_learning_relevance_service import compute_relevance_floor
        uid = _uid()
        # No pref — tier is "normal" by default; floor doesn't need to act
        item = _item(entity_key="earnings", entity_type="signal_type", signal_type="earnings")
        r = await compute_relevance_floor(db, user_id=uid, item=item, run_override=True)
        assert r["floor_applied"] is False

    @pytest.mark.asyncio
    async def test_floor_result_has_required_keys(self, db):
        from app.services.user_learning_relevance_service import compute_relevance_floor
        item = _item(signal_type="earnings")
        r = await compute_relevance_floor(db, user_id=_uid(), item=item, run_override=True)
        for key in ("item_ref", "signal_type", "floor_applied",
                    "original_prominence_tier", "effective_prominence_tier"):
            assert key in r

    @pytest.mark.asyncio
    async def test_floor_flag_off(self, db):
        from app.services.user_learning_relevance_service import compute_relevance_floor
        r = await compute_relevance_floor(db, user_id=_uid(), item=_item(), run_override=False)
        assert r["floor_applied"] is False

    @pytest.mark.asyncio
    async def test_floor_null_session(self):
        from app.services.user_learning_relevance_service import compute_relevance_floor
        r = await compute_relevance_floor(None, user_id=_uid(), item=_item(), run_override=True)
        assert r["floor_applied"] is False


# ---------------------------------------------------------------------------
# 37–45. apply_relevance_adjustment
# ---------------------------------------------------------------------------

class TestApplyRelevanceAdjustment:
    @pytest.mark.asyncio
    async def test_returns_same_count_as_input(self, db):
        from app.services.user_learning_relevance_service import apply_relevance_adjustment
        items = [_item(item_ref=f"i{k}", intrinsic_rank=k) for k in range(1, 6)]
        r = await apply_relevance_adjustment(db, user_id=_uid(), items=items, run_override=True)
        assert len(r) == 5

    @pytest.mark.asyncio
    async def test_re_ranked_by_relevance_score_desc(self, db):
        from app.services.user_learning_relevance_service import apply_relevance_adjustment
        uid = _uid()
        # Strong preference — factor = 1 + 1.0*1.0*0.5 = 1.5
        await _add_pref(db, user_id=uid, dimension="company_interest", entity_key="AAPL",
                        affinity=1.0, confidence=1.0)
        items = [
            # OTHER: intrinsic=0.80 → adjusted=0.80 (no pref)
            _item(item_ref="low",  entity_key="OTHER", intrinsic_rank=1, intrinsic_score=0.80),
            # AAPL: intrinsic=0.65 → adjusted=0.65*1.5=0.975 (wins)
            _item(item_ref="high", entity_key="AAPL",  intrinsic_rank=2, intrinsic_score=0.65),
        ]
        r = await apply_relevance_adjustment(db, user_id=uid, items=items, run_override=True)
        aapl  = next(x for x in r if x["entity_key"] == "AAPL")
        other = next(x for x in r if x["entity_key"] == "OTHER")
        assert aapl["adjusted_rank"] < other["adjusted_rank"]

    @pytest.mark.asyncio
    async def test_highest_score_gets_rank_1(self, db):
        from app.services.user_learning_relevance_service import apply_relevance_adjustment
        uid = _uid()
        await _add_pref(db, user_id=uid, dimension="company_interest", entity_key="AAPL",
                        affinity=1.0, confidence=1.0)
        # AAPL: 0.65 * 1.5 = 0.975; OTHER: 0.9 * 1.0 = 0.9 → AAPL wins
        items = [
            _item(item_ref="a", entity_key="AAPL",  intrinsic_rank=3, intrinsic_score=0.65),
            _item(item_ref="b", entity_key="OTHER", intrinsic_rank=1, intrinsic_score=0.90),
        ]
        r = await apply_relevance_adjustment(db, user_id=uid, items=items, run_override=True)
        aapl = next(x for x in r if x["entity_key"] == "AAPL")
        assert aapl["adjusted_rank"] == 1

    @pytest.mark.asyncio
    async def test_ties_broken_by_item_ref_asc(self, db):
        from app.services.user_learning_relevance_service import apply_relevance_adjustment
        uid = _uid()
        items = [
            _item(item_ref="z", intrinsic_rank=1, intrinsic_score=0.8),
            _item(item_ref="a", intrinsic_rank=2, intrinsic_score=0.8),
        ]
        r = await apply_relevance_adjustment(db, user_id=uid, items=items, run_override=True)
        assert r[0]["item_ref"] == "a"

    @pytest.mark.asyncio
    async def test_all_items_have_required_fields(self, db):
        from app.services.user_learning_relevance_service import apply_relevance_adjustment
        items = [_item(item_ref=f"i{k}", intrinsic_rank=k) for k in range(1, 4)]
        r = await apply_relevance_adjustment(db, user_id=_uid(), items=items, run_override=True)
        for row in r:
            assert _REQUIRED_FIELDS.issubset(row.keys())

    @pytest.mark.asyncio
    async def test_intrinsic_rank_preserved(self, db):
        from app.services.user_learning_relevance_service import apply_relevance_adjustment
        items = [_item(item_ref="a", intrinsic_rank=7)]
        r = await apply_relevance_adjustment(db, user_id=_uid(), items=items, run_override=True)
        assert r[0]["intrinsic_rank"] == 7

    @pytest.mark.asyncio
    async def test_no_pref_all_factors_one(self, db):
        from app.services.user_learning_relevance_service import apply_relevance_adjustment
        items = [_item(item_ref=f"i{k}", intrinsic_rank=k) for k in range(1, 4)]
        r = await apply_relevance_adjustment(db, user_id=_uid(), items=items, run_override=True)
        assert all(x["relevance_adjustment"] == 1.0 for x in r)

    @pytest.mark.asyncio
    async def test_flag_off_identity_sorted_by_intrinsic(self, db):
        from app.services.user_learning_relevance_service import apply_relevance_adjustment
        items = [_item(item_ref="b", intrinsic_rank=2), _item(item_ref="a", intrinsic_rank=1)]
        r = await apply_relevance_adjustment(db, user_id=_uid(), items=items, run_override=False)
        assert r[0]["adjusted_rank"] == 1
        assert all(x["relevance_adjustment"] == 1.0 for x in r)

    @pytest.mark.asyncio
    async def test_null_session_identity_sorted(self):
        from app.services.user_learning_relevance_service import apply_relevance_adjustment
        items = [_item(item_ref="b", intrinsic_rank=2), _item(item_ref="a", intrinsic_rank=1)]
        r = await apply_relevance_adjustment(None, user_id=_uid(), items=items, run_override=True)
        assert len(r) == 2
        assert all(x["relevance_adjustment"] == 1.0 for x in r)


# ---------------------------------------------------------------------------
# 46–55. compute_novelty_reserve
# ---------------------------------------------------------------------------

class TestComputeNoveltyReserve:
    @pytest.mark.asyncio
    async def test_empty_items_empty_summary(self, db):
        from app.services.user_learning_relevance_service import compute_novelty_reserve
        r = await compute_novelty_reserve(db, user_id=_uid(), items=[], run_override=True)
        assert r["novel_item_count"] == 0
        assert r["reserve_applied"] is False

    @pytest.mark.asyncio
    async def test_all_novel_reserve_not_applied(self, db):
        from app.services.user_learning_relevance_service import (
            compute_novelty_reserve, apply_relevance_adjustment,
        )
        uid = _uid()
        items = [_item(item_ref=f"i{k}", intrinsic_rank=k) for k in range(1, 8)]
        adjusted = await apply_relevance_adjustment(db, user_id=uid, items=items, run_override=True)
        r = await compute_novelty_reserve(db, user_id=uid, items=adjusted, run_override=True)
        # All items are novel → reserve was naturally satisfied
        assert r["reserve_applied"] is False
        assert r["novel_item_count"] == len(items)

    @pytest.mark.asyncio
    async def test_no_novel_items_reserve_not_applied(self, db):
        from app.services.user_learning_relevance_service import compute_novelty_reserve
        uid = _uid()
        # All items have a matching preference
        personalised = [
            {
                "item_ref": f"i{k}", "entity_key": f"key{k}", "intrinsic_rank": k,
                "intrinsic_score": 0.8, "adjusted_rank": k,
                "adjustment_reason": f"positive_pref:company_interest:key{k}",
                "relevance_adjustment": 1.3, "relevance_score": 1.04,
            }
            for k in range(1, 8)
        ]
        r = await compute_novelty_reserve(db, user_id=uid, items=personalised, run_override=True)
        assert r["reserve_applied"] is False
        assert r["novel_item_count"] == 0

    @pytest.mark.asyncio
    async def test_novel_items_buried_reserve_applied(self, db):
        from app.services.user_learning_relevance_service import compute_novelty_reserve
        uid = _uid()
        # One novel item at rank 10, many personalised items at ranks 1–9
        personalised = [
            {
                "item_ref": f"p{k}", "entity_key": f"key{k}", "intrinsic_rank": k,
                "intrinsic_score": 0.9, "adjusted_rank": k,
                "adjustment_reason": f"positive_pref:company_interest:key{k}",
                "relevance_adjustment": 1.5, "relevance_score": 1.35,
            }
            for k in range(1, 10)
        ]
        novel = {
            "item_ref": "novel_1", "entity_key": "NEW", "intrinsic_rank": 10,
            "intrinsic_score": 0.7, "adjusted_rank": 10,
            "adjustment_reason": "no_preference",
            "relevance_adjustment": 1.0, "relevance_score": 0.7,
        }
        all_items = personalised + [novel]
        r = await compute_novelty_reserve(db, user_id=uid, items=all_items, run_override=True)
        assert r["reserve_applied"] is True
        assert "novel_1" in r["reserve_item_refs"]

    @pytest.mark.asyncio
    async def test_reserve_fraction_target_matches_param(self, db):
        from app.services.user_learning_relevance_service import compute_novelty_reserve
        items = [
            {"item_ref": f"i{k}", "adjusted_rank": k, "intrinsic_score": 0.5,
             "adjustment_reason": "no_preference"}
            for k in range(1, 8)
        ]
        r = await compute_novelty_reserve(db, user_id=_uid(), items=items,
                                          reserve_fraction=0.20, run_override=True)
        assert abs(r["reserve_fraction_target"] - 0.20) < 0.001

    @pytest.mark.asyncio
    async def test_protected_count_non_negative(self, db):
        from app.services.user_learning_relevance_service import compute_novelty_reserve
        items = [{"item_ref": "a", "adjusted_rank": 1, "intrinsic_score": 0.5,
                  "adjustment_reason": "no_preference"}]
        r = await compute_novelty_reserve(db, user_id=_uid(), items=items, run_override=True)
        assert r["protected_count"] >= 0

    @pytest.mark.asyncio
    async def test_fewer_than_min_items_no_reserve(self, db):
        from app.services.user_learning_relevance_service import (
            compute_novelty_reserve, _MIN_ITEMS_FOR_RESERVE,
        )
        # Fewer items than the minimum
        items = [
            {"item_ref": f"i{k}", "adjusted_rank": k, "intrinsic_score": 0.5,
             "adjustment_reason": "no_preference"}
            for k in range(1, _MIN_ITEMS_FOR_RESERVE)
        ]
        r = await compute_novelty_reserve(db, user_id=_uid(), items=items, run_override=True)
        assert r["reserve_applied"] is False

    @pytest.mark.asyncio
    async def test_flag_off_empty_reserve(self, db):
        from app.services.user_learning_relevance_service import compute_novelty_reserve
        r = await compute_novelty_reserve(db, user_id=_uid(), items=[_item()], run_override=False)
        assert r["reserve_applied"] is False
        assert r["novel_item_count"] == 0

    @pytest.mark.asyncio
    async def test_null_session_empty_reserve(self):
        from app.services.user_learning_relevance_service import compute_novelty_reserve
        r = await compute_novelty_reserve(None, user_id=_uid(), items=[_item()], run_override=True)
        assert r["reserve_applied"] is False


# ---------------------------------------------------------------------------
# 56–69. build_relevance_projection
# ---------------------------------------------------------------------------

class TestBuildRelevanceProjection:
    @pytest.mark.asyncio
    async def test_empty_items_returns_empty_list(self, db):
        from app.services.user_learning_relevance_service import build_relevance_projection
        r = await build_relevance_projection(db, user_id=_uid(), items=[], run_override=True)
        assert r == []

    @pytest.mark.asyncio
    async def test_output_count_equals_input_count(self, db):
        from app.services.user_learning_relevance_service import build_relevance_projection
        items = [_item(item_ref=f"i{k}", intrinsic_rank=k) for k in range(1, 6)]
        r = await build_relevance_projection(db, user_id=_uid(), items=items, run_override=True)
        assert len(r) == 5

    @pytest.mark.asyncio
    async def test_adjusted_ranks_sequential(self, db):
        from app.services.user_learning_relevance_service import build_relevance_projection
        items = [_item(item_ref=f"i{k}", intrinsic_rank=k) for k in range(1, 6)]
        r = await build_relevance_projection(db, user_id=_uid(), items=items, run_override=True)
        ranks = sorted(x["adjusted_rank"] for x in r)
        assert ranks == list(range(1, 6))

    @pytest.mark.asyncio
    async def test_highest_score_gets_rank_1(self, db):
        from app.services.user_learning_relevance_service import build_relevance_projection
        uid = _uid()
        await _add_pref(db, user_id=uid, dimension="company_interest", entity_key="AAPL",
                        affinity=1.0, confidence=1.0)
        # AAPL: 0.65 * 1.5 = 0.975; OTHER: 0.90 * 1.0 = 0.90 → AAPL wins
        items = [
            _item(item_ref="low",  entity_key="OTHER", intrinsic_rank=1, intrinsic_score=0.90),
            _item(item_ref="high", entity_key="AAPL",  intrinsic_rank=2, intrinsic_score=0.65),
        ]
        r = await build_relevance_projection(db, user_id=uid, items=items, run_override=True)
        aapl = next(x for x in r if x["entity_key"] == "AAPL")
        assert aapl["adjusted_rank"] == 1

    @pytest.mark.asyncio
    async def test_all_projection_items_have_required_fields(self, db):
        from app.services.user_learning_relevance_service import build_relevance_projection
        items = [_item(item_ref=f"i{k}", intrinsic_rank=k) for k in range(1, 4)]
        r = await build_relevance_projection(db, user_id=_uid(), items=items, run_override=True)
        for row in r:
            assert _REQUIRED_FIELDS.issubset(row.keys())

    @pytest.mark.asyncio
    async def test_boosted_item_outranks_original_position(self, db):
        from app.services.user_learning_relevance_service import build_relevance_projection
        uid = _uid()
        await _add_pref(db, user_id=uid, dimension="company_interest", entity_key="AAPL",
                        affinity=1.0, confidence=1.0)
        items = [
            _item(item_ref="a", entity_key="OTHER", intrinsic_rank=1, intrinsic_score=0.8),
            _item(item_ref="b", entity_key="AAPL",  intrinsic_rank=5, intrinsic_score=0.6),
        ]
        r = await build_relevance_projection(db, user_id=uid, items=items, run_override=True)
        aapl = next(x for x in r if x["entity_key"] == "AAPL")
        assert aapl["adjusted_rank"] < aapl["intrinsic_rank"]

    @pytest.mark.asyncio
    async def test_penalised_item_drops_below_original_position(self, db):
        from app.services.user_learning_relevance_service import build_relevance_projection
        uid = _uid()
        # penalty = 1.0*0.9*0.4 = 0.36 → factor = 0.64
        # analyst_note: 0.9 * 0.64 = 0.576; OTHER: 0.70 * 1.0 = 0.70 → OTHER wins
        await _add_pref(db, user_id=uid, dimension="ignored_signal_type", entity_key="analyst_note",
                        affinity=-1.0, confidence=0.9)
        items = [
            _item(item_ref="top",    entity_key="analyst_note", entity_type="signal_type",
                  intrinsic_rank=1, intrinsic_score=0.90),
            _item(item_ref="bottom", entity_key="OTHER",        intrinsic_rank=2, intrinsic_score=0.70),
        ]
        r = await build_relevance_projection(db, user_id=uid, items=items, run_override=True)
        penalised = next(x for x in r if x["item_ref"] == "top")
        assert penalised["adjusted_rank"] > penalised["intrinsic_rank"]

    @pytest.mark.asyncio
    async def test_novelty_reserve_marks_promoted_novel_items(self, db):
        from app.services.user_learning_relevance_service import build_relevance_projection
        uid = _uid()
        # Add preferences for all but the last item
        for k in range(1, 9):
            await _add_pref(db, user_id=uid, dimension="company_interest",
                            entity_key=f"KEY{k}", affinity=1.0, confidence=1.0)
        items = [
            _item(item_ref=f"p{k}", entity_key=f"KEY{k}", intrinsic_rank=k, intrinsic_score=0.9)
            for k in range(1, 9)
        ] + [
            _item(item_ref="novel", entity_key="NOVEL_KEY", intrinsic_rank=9, intrinsic_score=0.8),
        ]
        r = await build_relevance_projection(db, user_id=uid, items=items, run_override=True)
        novel_item = next(x for x in r if x["item_ref"] == "novel")
        assert novel_item["novelty_reserve_applied"] is True

    @pytest.mark.asyncio
    async def test_non_promoted_item_novelty_reserve_false(self, db):
        from app.services.user_learning_relevance_service import build_relevance_projection
        uid = _uid()
        items = [_item(item_ref=f"i{k}", intrinsic_rank=k, intrinsic_score=0.8) for k in range(1, 4)]
        r = await build_relevance_projection(db, user_id=uid, items=items, run_override=True)
        # All are novel (no prefs) but naturally at top — no promotion needed
        assert all(x["novelty_reserve_applied"] is False for x in r)

    @pytest.mark.asyncio
    async def test_critical_signal_floor_applied_in_projection(self, db):
        from app.services.user_learning_relevance_service import build_relevance_projection
        uid = _uid()
        await _add_pref(db, user_id=uid, dimension="ignored_signal_type", entity_key="earnings",
                        affinity=-1.0, confidence=0.9)
        items = [
            _item(item_ref="crit", entity_key="earnings", entity_type="signal_type",
                  signal_type="earnings", intrinsic_rank=1, intrinsic_score=0.8),
        ]
        r = await build_relevance_projection(db, user_id=uid, items=items, run_override=True)
        assert r[0]["relevance_floor_applied"] is True
        assert r[0]["prominence_tier"] == "normal"

    @pytest.mark.asyncio
    async def test_no_hidden_prominence_tier_in_projection(self, db):
        from app.services.user_learning_relevance_service import build_relevance_projection
        uid = _uid()
        items = [_item(item_ref=f"i{k}", intrinsic_rank=k) for k in range(1, 5)]
        r = await build_relevance_projection(db, user_id=uid, items=items, run_override=True)
        for row in r:
            assert row["prominence_tier"] != "hidden"

    @pytest.mark.asyncio
    async def test_deterministic_output(self, db):
        from app.services.user_learning_relevance_service import build_relevance_projection
        uid = _uid()
        await _add_pref(db, user_id=uid, dimension="company_interest", entity_key="AAPL")
        items = [
            _item(item_ref="a", entity_key="AAPL",  intrinsic_rank=1, intrinsic_score=0.7),
            _item(item_ref="b", entity_key="OTHER", intrinsic_rank=2, intrinsic_score=0.8),
        ]
        r1 = await build_relevance_projection(db, user_id=uid, items=items, run_override=True)
        r2 = await build_relevance_projection(db, user_id=uid, items=items, run_override=True)
        for i in range(len(r1)):
            assert r1[i]["item_ref"] == r2[i]["item_ref"]
            assert r1[i]["adjusted_rank"] == r2[i]["adjusted_rank"]
            assert r1[i]["relevance_adjustment"] == r2[i]["relevance_adjustment"]

    @pytest.mark.asyncio
    async def test_flag_off_returns_empty(self, db):
        from app.services.user_learning_relevance_service import build_relevance_projection
        r = await build_relevance_projection(
            db, user_id=_uid(), items=[_item()], run_override=False,
        )
        assert r == []

    @pytest.mark.asyncio
    async def test_null_session_returns_empty(self):
        from app.services.user_learning_relevance_service import build_relevance_projection
        r = await build_relevance_projection(
            None, user_id=_uid(), items=[_item()], run_override=True,
        )
        assert r == []


# ---------------------------------------------------------------------------
# 70–72. No truth mutation
# ---------------------------------------------------------------------------

class TestNoTruthMutation:
    @pytest.mark.asyncio
    async def test_learned_preference_rows_unchanged(self, db):
        from app.services.user_learning_relevance_service import build_relevance_projection
        from app.db.repositories.user_learning_repo import list_learned_preferences
        uid = _uid()
        await _add_pref(db, user_id=uid, dimension="company_interest", entity_key="AAPL")
        before = await list_learned_preferences(db, user_id=uid)
        items = [_item(entity_key="AAPL")]
        await build_relevance_projection(db, user_id=uid, items=items, run_override=True)
        after = await list_learned_preferences(db, user_id=uid)
        assert len(before) == len(after)

    @pytest.mark.asyncio
    async def test_user_signal_event_rows_unchanged(self, db):
        from app.services.user_learning_relevance_service import build_relevance_projection
        from app.db.repositories.user_learning_repo import list_user_signal_events
        uid = _uid()
        before = await list_user_signal_events(db, user_id=uid)
        await build_relevance_projection(db, user_id=uid, items=[_item()], run_override=True)
        after = await list_user_signal_events(db, user_id=uid)
        assert len(before) == len(after)

    @pytest.mark.asyncio
    async def test_row_counts_stable_across_multiple_calls(self, db):
        from app.services.user_learning_relevance_service import build_relevance_projection
        from app.db.repositories.user_learning_repo import list_learned_preferences
        uid = _uid()
        await _add_pref(db, user_id=uid, dimension="sector_interest", entity_key="tech")
        count_before = len(await list_learned_preferences(db, user_id=uid))
        for _ in range(3):
            await build_relevance_projection(db, user_id=uid, items=[_item()], run_override=True)
        count_after = len(await list_learned_preferences(db, user_id=uid))
        assert count_before == count_after


# ---------------------------------------------------------------------------
# 73–74. Tenant isolation
# ---------------------------------------------------------------------------

class TestTenantIsolation:
    @pytest.mark.asyncio
    async def test_user_a_pref_does_not_affect_user_b(self, db):
        from app.services.user_learning_relevance_service import compute_relevance_adjustment
        uid_a, uid_b = _uid(), _uid()
        await _add_pref(db, user_id=uid_a, dimension="company_interest", entity_key="AAPL",
                        affinity=1.0, confidence=1.0)
        r = await compute_relevance_adjustment(
            db, user_id=uid_b, item=_item(entity_key="AAPL"), run_override=True,
        )
        assert r["relevance_adjustment"] == 1.0

    @pytest.mark.asyncio
    async def test_user_b_identity_when_a_has_prefs(self, db):
        from app.services.user_learning_relevance_service import build_relevance_projection
        uid_a, uid_b = _uid(), _uid()
        await _add_pref(db, user_id=uid_a, dimension="company_interest", entity_key="AAPL")
        items = [_item(entity_key="AAPL")]
        r = await build_relevance_projection(db, user_id=uid_b, items=items, run_override=True)
        assert r[0]["relevance_adjustment"] == 1.0
        assert r[0]["adjustment_reason"] == "no_preference"


# ---------------------------------------------------------------------------
# 75–80. AST safety
# ---------------------------------------------------------------------------

def _parse_service() -> ast.Module:
    src = _SVC_PATH.read_text()
    return ast.parse(src)


def _docstring_node_ids(tree: ast.Module) -> set:
    ids = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            if (node.body and isinstance(node.body[0], ast.Expr) and
                    isinstance(node.body[0].value, (ast.Constant, ast.Str))):
                ids.add(id(node.body[0].value))
    return ids


def _non_docstring_strings(tree: ast.Module):
    ds_ids = _docstring_node_ids(tree)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Constant, ast.Str)):
            if id(node) in ds_ids:
                continue
            val = node.s if isinstance(node, ast.Str) else node.value
            if isinstance(val, str):
                yield val


def _import_names(tree: ast.Module):
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            names.add(node.module or "")
    return names


def _call_names(tree: ast.Module):
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            fn = node.func
            if isinstance(fn, ast.Name):
                names.add(fn.id)
            elif isinstance(fn, ast.Attribute):
                names.add(fn.attr)
    return names


class TestAstSafety:
    def test_no_truth_write_imports(self):
        tree = _parse_service()
        forbidden = {
            "forecast_repo", "similarity_repo", "decision_repo",
            "scenario_repo", "ticker_memory",
        }
        for src in _import_names(tree):
            for bad in forbidden:
                assert bad not in src, f"Forbidden import: {src!r}"

    def test_no_conviction_order_execution_imports(self):
        tree = _parse_service()
        for src in _import_names(tree):
            for bad in ("conviction", "order", "execution"):
                assert bad not in src, f"Forbidden import: {src!r}"

    def test_no_banned_advisory_phrases_in_strings(self):
        _BANNED = frozenset({
            "buy", "sell", "hold", "overweight", "underweight", "recommend",
            "target price", "position size", "take a position", "enter a trade",
            "exit a trade", "place an order", "execute", "short", "long position",
            "go long", "go short", "open a position", "close a position",
        })
        tree = _parse_service()
        for s in _non_docstring_strings(tree):
            low = s.lower()
            for phrase in _BANNED:
                assert phrase not in low, (
                    f"Banned phrase {phrase!r} found in non-docstring string: {s!r}"
                )

    def test_no_upsert_insert_delete_calls(self):
        tree = _parse_service()
        calls = _call_names(tree)
        for bad in ("upsert_learned_preference", "add_user_signal_event",
                    "insert", "delete", "upsert"):
            assert bad not in calls, f"Write-path call found: {bad!r}"

    def test_no_add_relevance_adjustment_log_call(self):
        src = _SVC_PATH.read_text()
        assert "add_relevance_adjustment_log" not in src, (
            "Slice 15.8 is shadow-only — relevance_adjustment_log writes belong to a later slice"
        )

    def test_no_truth_read_imports(self):
        tree = _parse_service()
        forbidden_read = {"forecast_repo", "similarity_repo", "decision_repo", "scenario_repo"}
        for src in _import_names(tree):
            for bad in forbidden_read:
                assert bad not in src, f"Forbidden read import: {src!r}"
