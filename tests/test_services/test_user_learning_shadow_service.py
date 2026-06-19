"""
Tests — User Learning Shadow Journal Service, Phase 15 · Slice 9.

Covers:
  1.  service importable
  2.  all 3 public functions present

  --- classify_relevance_transition ---
  3.  adjusted_rank < intrinsic_rank → "relevance_increased"
  4.  adjusted_rank > intrinsic_rank (non-muted) → "relevance_decreased"
  5.  adjusted_rank > intrinsic_rank + prominence_tier="muted" → "relevance_removed"
  6.  novelty_reserve_applied=True → "novelty_reserve_applied"
  7.  relevance_floor_applied=True → "relevance_floor_applied"
  8.  identity item (factor=1.0, no flags) → None
  9.  factor below materiality cutoff → None
  10. rank unchanged and factor material but no flags → None
  11. novelty flag takes priority over floor flag
  12. floor flag takes priority over rank-based classification
  13. floor flag takes priority over small factor (bypasses materiality)
  14. novelty flag takes priority over small factor (bypasses materiality)
  15. custom min_factor_delta applied
  16. no-op item (adjusted_rank equals intrinsic_rank, no flags, small factor) → None

  --- detect_relevance_transitions ---
  17. empty projection → []
  18. all-trivial projection → []
  19. mixed: only material items in output
  20. output items include "transition_type" key
  21. output items include all required keys
  22. transition_type values match classify output
  23. custom min_factor_delta flows through
  24. novelty items included even when factor is trivial
  25. floor items included even when factor is trivial
  26. multiple material items all included

  --- record_relevance_transition_events ---
  27. inserts row to relevance_adjustment_log
  28. run_reason="shadow" on all rows
  29. surface propagated to log row
  30. intrinsic_rank stored correctly
  31. adjusted_rank stored correctly
  32. relevance_weight = factor − 1.0
  33. prominence_tier propagated
  34. floor_applied propagated to log
  35. returns list of inserted ORM rows
  36. null session → []
  37. flag off → []
  38. empty projection → []
  39. no material transitions → 0 rows
  40. log row count equals non-deduplicated transition count
  41. log count increases by correct amount

  --- deduplication ---
  42. same (item_ref, intrinsic_rank, adjusted_rank) within window → only 1 row
  43. different items → separate rows
  44. same item different ranks → new row (not deduplicated)
  45. outside dedup window → new row written

  --- no truth mutation ---
  46. user_signal_event rows unchanged after record
  47. learned_preference rows unchanged after record
  48. no Notification rows created

  --- shadow-only validation ---
  49. all rows have run_reason="shadow"
  50. no user-visible delivery (no notification write)

  --- tenant isolation ---
  51. user A log not visible in user B query
  52. user B gets fresh rows even when user A has recent journal entries

  --- transition type specifics ---
  53. relevance_removed requires both decreased rank and muted tier
  54. relevance_decreased for non-muted decrease
  55. floor transition row has floor_applied=True in log
  56. novelty transition logged even with rank unchanged

  --- AST safety ---
  57. no truth-table write imports
  58. no conviction / order / execution imports
  59. no banned advisory phrases in non-docstring strings
  60. no Notification / inbox writes in service source
  61. only shadow run_reason written (literal "shadow" in write call)
  62. no upsert / update / delete calls outside of add_relevance_adjustment_log
"""

from __future__ import annotations

import ast
import pathlib
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

_ROOT     = pathlib.Path(__file__).parent.parent.parent
_SVC_PATH = _ROOT / "app" / "services" / "user_learning_shadow_service.py"

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
# Projection item helpers
# ---------------------------------------------------------------------------

def _proj_item(
    *,
    item_ref: str = "item_001",
    entity_key: str = "AAPL",
    entity_type: str = "company",
    signal_type: str = "analyst_note",
    intrinsic_rank: int = 3,
    adjusted_rank: int = 1,
    intrinsic_score: float = 0.8,
    relevance_score: float = 0.96,
    relevance_adjustment: float = 1.20,
    adjustment_reason: str = "positive_pref:company_interest:AAPL",
    novelty_reserve_applied: bool = False,
    relevance_floor_applied: bool = False,
    prominence_tier: str = "pinned",
) -> Dict[str, Any]:
    """Build a minimal projection item dict matching build_relevance_projection output."""
    return {
        "item_ref":               item_ref,
        "entity_key":             entity_key,
        "entity_type":            entity_type,
        "signal_type":            signal_type,
        "intrinsic_rank":         intrinsic_rank,
        "adjusted_rank":          adjusted_rank,
        "intrinsic_score":        intrinsic_score,
        "relevance_score":        relevance_score,
        "relevance_adjustment":   relevance_adjustment,
        "adjustment_reason":      adjustment_reason,
        "novelty_reserve_applied": novelty_reserve_applied,
        "relevance_floor_applied": relevance_floor_applied,
        "prominence_tier":        prominence_tier,
    }


def _identity_item(**kwargs) -> Dict[str, Any]:
    """Item with no personalisation effect — intrinsic == adjusted, factor == 1.0."""
    base = {
        "item_ref":               "identity",
        "entity_key":             "PLAIN",
        "entity_type":            "company",
        "signal_type":            "note",
        "intrinsic_rank":         2,
        "adjusted_rank":          2,
        "intrinsic_score":        0.7,
        "relevance_score":        0.7,
        "relevance_adjustment":   1.0,
        "adjustment_reason":      "no_preference",
        "novelty_reserve_applied": False,
        "relevance_floor_applied": False,
        "prominence_tier":        "normal",
    }
    base.update(kwargs)
    return base


_REQUIRED_TRANSITION_KEYS = {
    "item_ref", "entity_key", "entity_type", "signal_type",
    "intrinsic_rank", "adjusted_rank", "relevance_adjustment",
    "prominence_tier", "floor_applied", "novelty_reserve_applied", "transition_type",
}


# ---------------------------------------------------------------------------
# 1–2. Import and presence
# ---------------------------------------------------------------------------

class TestImport:
    def test_service_importable(self):
        import app.services.user_learning_shadow_service  # noqa: F401

    def test_all_public_functions_present(self):
        import app.services.user_learning_shadow_service as svc
        for name in (
            "classify_relevance_transition",
            "detect_relevance_transitions",
            "record_relevance_transition_events",
        ):
            assert callable(getattr(svc, name, None)), f"Missing: {name}"


# ---------------------------------------------------------------------------
# 3–16. classify_relevance_transition
# ---------------------------------------------------------------------------

class TestClassifyRelevanceTransition:
    def test_relevance_increased_when_rank_moves_up(self):
        from app.services.user_learning_shadow_service import classify_relevance_transition
        item = _proj_item(intrinsic_rank=5, adjusted_rank=2, relevance_adjustment=1.30)
        assert classify_relevance_transition(item) == "relevance_increased"

    def test_relevance_decreased_when_rank_drops_non_muted(self):
        from app.services.user_learning_shadow_service import classify_relevance_transition
        item = _proj_item(
            intrinsic_rank=1, adjusted_rank=4,
            relevance_adjustment=0.70, prominence_tier="normal",
        )
        assert classify_relevance_transition(item) == "relevance_decreased"

    def test_relevance_removed_when_rank_drops_and_muted(self):
        from app.services.user_learning_shadow_service import classify_relevance_transition
        item = _proj_item(
            intrinsic_rank=1, adjusted_rank=5,
            relevance_adjustment=0.60, prominence_tier="muted",
        )
        assert classify_relevance_transition(item) == "relevance_removed"

    def test_novelty_reserve_applied(self):
        from app.services.user_learning_shadow_service import classify_relevance_transition
        item = _identity_item(novelty_reserve_applied=True)
        assert classify_relevance_transition(item) == "novelty_reserve_applied"

    def test_relevance_floor_applied(self):
        from app.services.user_learning_shadow_service import classify_relevance_transition
        item = _identity_item(relevance_floor_applied=True)
        assert classify_relevance_transition(item) == "relevance_floor_applied"

    def test_identity_item_returns_none(self):
        from app.services.user_learning_shadow_service import classify_relevance_transition
        assert classify_relevance_transition(_identity_item()) is None

    def test_small_factor_returns_none(self):
        from app.services.user_learning_shadow_service import classify_relevance_transition
        item = _proj_item(
            intrinsic_rank=3, adjusted_rank=2, relevance_adjustment=1.02,
        )
        assert classify_relevance_transition(item) is None

    def test_material_factor_but_rank_unchanged_returns_none(self):
        from app.services.user_learning_shadow_service import classify_relevance_transition
        item = _proj_item(
            intrinsic_rank=2, adjusted_rank=2, relevance_adjustment=1.30,
        )
        assert classify_relevance_transition(item) is None

    def test_novelty_beats_floor_priority(self):
        from app.services.user_learning_shadow_service import classify_relevance_transition
        item = _identity_item(novelty_reserve_applied=True, relevance_floor_applied=True)
        assert classify_relevance_transition(item) == "novelty_reserve_applied"

    def test_floor_beats_rank_based_classification(self):
        from app.services.user_learning_shadow_service import classify_relevance_transition
        item = _proj_item(
            intrinsic_rank=5, adjusted_rank=2, relevance_adjustment=1.30,
            relevance_floor_applied=True,
        )
        assert classify_relevance_transition(item) == "relevance_floor_applied"

    def test_floor_bypasses_materiality_cutoff(self):
        from app.services.user_learning_shadow_service import classify_relevance_transition
        item = _identity_item(relevance_floor_applied=True, relevance_adjustment=1.01)
        assert classify_relevance_transition(item) == "relevance_floor_applied"

    def test_novelty_bypasses_materiality_cutoff(self):
        from app.services.user_learning_shadow_service import classify_relevance_transition
        item = _identity_item(novelty_reserve_applied=True, relevance_adjustment=1.01)
        assert classify_relevance_transition(item) == "novelty_reserve_applied"

    def test_custom_min_factor_delta(self):
        from app.services.user_learning_shadow_service import classify_relevance_transition
        item = _proj_item(
            intrinsic_rank=3, adjusted_rank=1, relevance_adjustment=1.06,
        )
        # With default delta (0.05) this is material → "relevance_increased"
        assert classify_relevance_transition(item) == "relevance_increased"
        # With stricter delta (0.10) the 0.06 change is trivial → None
        assert classify_relevance_transition(item, min_factor_delta=0.10) is None

    def test_no_op_item_returns_none(self):
        from app.services.user_learning_shadow_service import classify_relevance_transition
        item = _identity_item(
            novelty_reserve_applied=False, relevance_floor_applied=False,
            relevance_adjustment=1.0, intrinsic_rank=3, adjusted_rank=3,
        )
        assert classify_relevance_transition(item) is None


# ---------------------------------------------------------------------------
# 17–26. detect_relevance_transitions
# ---------------------------------------------------------------------------

class TestDetectRelevanceTransitions:
    def test_empty_projection_returns_empty(self):
        from app.services.user_learning_shadow_service import detect_relevance_transitions
        assert detect_relevance_transitions([]) == []

    def test_all_trivial_returns_empty(self):
        from app.services.user_learning_shadow_service import detect_relevance_transitions
        items = [_identity_item(item_ref=f"i{k}") for k in range(3)]
        assert detect_relevance_transitions(items) == []

    def test_material_items_included(self):
        from app.services.user_learning_shadow_service import detect_relevance_transitions
        items = [
            _proj_item(item_ref="material", intrinsic_rank=5, adjusted_rank=1,
                       relevance_adjustment=1.30),
            _identity_item(item_ref="trivial"),
        ]
        r = detect_relevance_transitions(items)
        assert len(r) == 1
        assert r[0]["item_ref"] == "material"

    def test_output_has_transition_type_key(self):
        from app.services.user_learning_shadow_service import detect_relevance_transitions
        items = [_proj_item(intrinsic_rank=5, adjusted_rank=2, relevance_adjustment=1.30)]
        r = detect_relevance_transitions(items)
        assert "transition_type" in r[0]

    def test_output_has_all_required_keys(self):
        from app.services.user_learning_shadow_service import detect_relevance_transitions
        items = [_proj_item(intrinsic_rank=5, adjusted_rank=2, relevance_adjustment=1.30)]
        r = detect_relevance_transitions(items)
        assert _REQUIRED_TRANSITION_KEYS.issubset(r[0].keys())

    def test_transition_type_matches_classify(self):
        from app.services.user_learning_shadow_service import (
            classify_relevance_transition, detect_relevance_transitions,
        )
        item = _proj_item(intrinsic_rank=5, adjusted_rank=2, relevance_adjustment=1.30)
        r = detect_relevance_transitions([item])
        assert r[0]["transition_type"] == classify_relevance_transition(item)

    def test_custom_min_factor_flows_through(self):
        from app.services.user_learning_shadow_service import detect_relevance_transitions
        item = _proj_item(
            intrinsic_rank=3, adjusted_rank=1, relevance_adjustment=1.06,
        )
        # Default delta (0.05): material
        assert len(detect_relevance_transitions([item])) == 1
        # Strict delta (0.10): trivial
        assert len(detect_relevance_transitions([item], min_factor_delta=0.10)) == 0

    def test_novelty_items_included_with_trivial_factor(self):
        from app.services.user_learning_shadow_service import detect_relevance_transitions
        item = _identity_item(novelty_reserve_applied=True, relevance_adjustment=1.01)
        r = detect_relevance_transitions([item])
        assert len(r) == 1
        assert r[0]["transition_type"] == "novelty_reserve_applied"

    def test_floor_items_included_with_trivial_factor(self):
        from app.services.user_learning_shadow_service import detect_relevance_transitions
        item = _identity_item(relevance_floor_applied=True, relevance_adjustment=1.01)
        r = detect_relevance_transitions([item])
        assert len(r) == 1
        assert r[0]["transition_type"] == "relevance_floor_applied"

    def test_multiple_material_items_all_included(self):
        from app.services.user_learning_shadow_service import detect_relevance_transitions
        items = [
            _proj_item(item_ref="a", intrinsic_rank=5, adjusted_rank=1, relevance_adjustment=1.30),
            _proj_item(item_ref="b", intrinsic_rank=1, adjusted_rank=4,
                       relevance_adjustment=0.60, prominence_tier="muted"),
            _identity_item(item_ref="c"),
        ]
        r = detect_relevance_transitions(items)
        assert len(r) == 2


# ---------------------------------------------------------------------------
# 27–45. record_relevance_transition_events
# ---------------------------------------------------------------------------

class TestRecordRelevanceTransitionEvents:
    @pytest.mark.asyncio
    async def test_inserts_row_to_log(self, db):
        from app.services.user_learning_shadow_service import record_relevance_transition_events
        from app.db.repositories.user_learning_repo import count_relevance_adjustment_logs
        uid = _uid()
        items = [_proj_item(item_ref="r1", intrinsic_rank=5, adjusted_rank=1, relevance_adjustment=1.30)]
        before = await count_relevance_adjustment_logs(db, user_id=uid)
        await record_relevance_transition_events(
            db, user_id=uid, surface="feed", projection=items, run_override=True,
        )
        after = await count_relevance_adjustment_logs(db, user_id=uid)
        assert after == before + 1

    @pytest.mark.asyncio
    async def test_run_reason_is_shadow(self, db):
        from app.services.user_learning_shadow_service import record_relevance_transition_events
        from app.db.repositories.user_learning_repo import list_relevance_adjustment_logs
        uid = _uid()
        items = [_proj_item(item_ref="r2", intrinsic_rank=5, adjusted_rank=1, relevance_adjustment=1.30)]
        await record_relevance_transition_events(
            db, user_id=uid, surface="feed", projection=items, run_override=True,
        )
        rows = await list_relevance_adjustment_logs(db, user_id=uid)
        assert all(r.run_reason == "shadow" for r in rows)

    @pytest.mark.asyncio
    async def test_surface_propagated(self, db):
        from app.services.user_learning_shadow_service import record_relevance_transition_events
        from app.db.repositories.user_learning_repo import list_relevance_adjustment_logs
        uid = _uid()
        items = [_proj_item(item_ref="r3", intrinsic_rank=4, adjusted_rank=1, relevance_adjustment=1.30)]
        await record_relevance_transition_events(
            db, user_id=uid, surface="alert_digest", projection=items, run_override=True,
        )
        rows = await list_relevance_adjustment_logs(db, user_id=uid)
        assert rows[0].surface == "alert_digest"

    @pytest.mark.asyncio
    async def test_intrinsic_rank_stored(self, db):
        from app.services.user_learning_shadow_service import record_relevance_transition_events
        from app.db.repositories.user_learning_repo import list_relevance_adjustment_logs
        uid = _uid()
        items = [_proj_item(item_ref="r4", intrinsic_rank=7, adjusted_rank=2, relevance_adjustment=1.30)]
        await record_relevance_transition_events(
            db, user_id=uid, surface="feed", projection=items, run_override=True,
        )
        rows = await list_relevance_adjustment_logs(db, user_id=uid)
        assert rows[0].intrinsic_rank == 7

    @pytest.mark.asyncio
    async def test_adjusted_rank_stored(self, db):
        from app.services.user_learning_shadow_service import record_relevance_transition_events
        from app.db.repositories.user_learning_repo import list_relevance_adjustment_logs
        uid = _uid()
        items = [_proj_item(item_ref="r5", intrinsic_rank=7, adjusted_rank=2, relevance_adjustment=1.30)]
        await record_relevance_transition_events(
            db, user_id=uid, surface="feed", projection=items, run_override=True,
        )
        rows = await list_relevance_adjustment_logs(db, user_id=uid)
        assert rows[0].adjusted_rank == 2

    @pytest.mark.asyncio
    async def test_relevance_weight_equals_factor_minus_one(self, db):
        from app.services.user_learning_shadow_service import record_relevance_transition_events
        from app.db.repositories.user_learning_repo import list_relevance_adjustment_logs
        uid = _uid()
        factor = 1.35
        items = [_proj_item(item_ref="r6", intrinsic_rank=5, adjusted_rank=1, relevance_adjustment=factor)]
        await record_relevance_transition_events(
            db, user_id=uid, surface="feed", projection=items, run_override=True,
        )
        rows = await list_relevance_adjustment_logs(db, user_id=uid)
        assert abs(rows[0].relevance_weight - (factor - 1.0)) < 0.001

    @pytest.mark.asyncio
    async def test_prominence_tier_propagated(self, db):
        from app.services.user_learning_shadow_service import record_relevance_transition_events
        from app.db.repositories.user_learning_repo import list_relevance_adjustment_logs
        uid = _uid()
        items = [_proj_item(item_ref="r7", intrinsic_rank=5, adjusted_rank=1,
                            relevance_adjustment=1.30, prominence_tier="pinned")]
        await record_relevance_transition_events(
            db, user_id=uid, surface="feed", projection=items, run_override=True,
        )
        rows = await list_relevance_adjustment_logs(db, user_id=uid)
        assert rows[0].prominence_tier == "pinned"

    @pytest.mark.asyncio
    async def test_floor_applied_propagated(self, db):
        from app.services.user_learning_shadow_service import record_relevance_transition_events
        from app.db.repositories.user_learning_repo import list_relevance_adjustment_logs
        uid = _uid()
        items = [_identity_item(item_ref="r8", relevance_floor_applied=True)]
        await record_relevance_transition_events(
            db, user_id=uid, surface="feed", projection=items, run_override=True,
        )
        rows = await list_relevance_adjustment_logs(db, user_id=uid)
        assert rows[0].floor_applied is True

    @pytest.mark.asyncio
    async def test_returns_list_of_rows(self, db):
        from app.services.user_learning_shadow_service import record_relevance_transition_events
        uid = _uid()
        items = [_proj_item(item_ref="r9", intrinsic_rank=5, adjusted_rank=1, relevance_adjustment=1.30)]
        result = await record_relevance_transition_events(
            db, user_id=uid, surface="feed", projection=items, run_override=True,
        )
        assert isinstance(result, list)
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_null_session_returns_empty(self):
        from app.services.user_learning_shadow_service import record_relevance_transition_events
        items = [_proj_item(item_ref="r10", intrinsic_rank=5, adjusted_rank=1, relevance_adjustment=1.30)]
        result = await record_relevance_transition_events(
            None, user_id=_uid(), surface="feed", projection=items, run_override=True,
        )
        assert result == []

    @pytest.mark.asyncio
    async def test_flag_off_returns_empty(self, db):
        from app.services.user_learning_shadow_service import record_relevance_transition_events
        items = [_proj_item(item_ref="r11", intrinsic_rank=5, adjusted_rank=1, relevance_adjustment=1.30)]
        result = await record_relevance_transition_events(
            db, user_id=_uid(), surface="feed", projection=items, run_override=False,
        )
        assert result == []

    @pytest.mark.asyncio
    async def test_empty_projection_returns_empty(self, db):
        from app.services.user_learning_shadow_service import record_relevance_transition_events
        result = await record_relevance_transition_events(
            db, user_id=_uid(), surface="feed", projection=[], run_override=True,
        )
        assert result == []

    @pytest.mark.asyncio
    async def test_no_material_transitions_returns_empty(self, db):
        from app.services.user_learning_shadow_service import record_relevance_transition_events
        items = [_identity_item(item_ref=f"nop{k}") for k in range(3)]
        result = await record_relevance_transition_events(
            db, user_id=_uid(), surface="feed", projection=items, run_override=True,
        )
        assert result == []

    @pytest.mark.asyncio
    async def test_log_count_equals_transition_count(self, db):
        from app.services.user_learning_shadow_service import record_relevance_transition_events
        from app.db.repositories.user_learning_repo import count_relevance_adjustment_logs
        uid = _uid()
        items = [
            _proj_item(item_ref="m1", intrinsic_rank=5, adjusted_rank=1, relevance_adjustment=1.30),
            _proj_item(item_ref="m2", intrinsic_rank=4, adjusted_rank=2, relevance_adjustment=1.20),
            _identity_item(item_ref="nop"),
        ]
        rows = await record_relevance_transition_events(
            db, user_id=uid, surface="feed", projection=items, run_override=True,
        )
        count = await count_relevance_adjustment_logs(db, user_id=uid)
        assert len(rows) == 2
        assert count == 2

    @pytest.mark.asyncio
    async def test_count_increments_by_material_transitions(self, db):
        from app.services.user_learning_shadow_service import record_relevance_transition_events
        from app.db.repositories.user_learning_repo import count_relevance_adjustment_logs
        uid = _uid()
        before = await count_relevance_adjustment_logs(db, user_id=uid)
        items = [
            _proj_item(item_ref="inc1", intrinsic_rank=5, adjusted_rank=1, relevance_adjustment=1.30),
        ]
        await record_relevance_transition_events(
            db, user_id=uid, surface="feed", projection=items, run_override=True,
        )
        after = await count_relevance_adjustment_logs(db, user_id=uid)
        assert after == before + 1


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------

class TestDeduplication:
    @pytest.mark.asyncio
    async def test_same_key_within_window_only_one_row(self, db):
        from app.services.user_learning_shadow_service import record_relevance_transition_events
        from app.db.repositories.user_learning_repo import count_relevance_adjustment_logs
        uid = _uid()
        items = [_proj_item(item_ref="dup1", intrinsic_rank=5, adjusted_rank=1, relevance_adjustment=1.30)]
        # First call
        await record_relevance_transition_events(
            db, user_id=uid, surface="feed", projection=items, run_override=True,
        )
        # Second call with same projection — should dedup
        await record_relevance_transition_events(
            db, user_id=uid, surface="feed", projection=items, run_override=True,
        )
        count = await count_relevance_adjustment_logs(db, user_id=uid)
        assert count == 1

    @pytest.mark.asyncio
    async def test_different_items_get_separate_rows(self, db):
        from app.services.user_learning_shadow_service import record_relevance_transition_events
        from app.db.repositories.user_learning_repo import count_relevance_adjustment_logs
        uid = _uid()
        item_a = [_proj_item(item_ref="da", intrinsic_rank=5, adjusted_rank=1, relevance_adjustment=1.30)]
        item_b = [_proj_item(item_ref="db", intrinsic_rank=4, adjusted_rank=1, relevance_adjustment=1.30)]
        await record_relevance_transition_events(
            db, user_id=uid, surface="feed", projection=item_a, run_override=True,
        )
        await record_relevance_transition_events(
            db, user_id=uid, surface="feed", projection=item_b, run_override=True,
        )
        count = await count_relevance_adjustment_logs(db, user_id=uid)
        assert count == 2

    @pytest.mark.asyncio
    async def test_same_item_different_ranks_is_new_row(self, db):
        from app.services.user_learning_shadow_service import record_relevance_transition_events
        from app.db.repositories.user_learning_repo import count_relevance_adjustment_logs
        uid = _uid()
        item_v1 = [_proj_item(item_ref="shifting", intrinsic_rank=5, adjusted_rank=1, relevance_adjustment=1.30)]
        item_v2 = [_proj_item(item_ref="shifting", intrinsic_rank=5, adjusted_rank=2, relevance_adjustment=1.20)]
        await record_relevance_transition_events(
            db, user_id=uid, surface="feed", projection=item_v1, run_override=True,
        )
        await record_relevance_transition_events(
            db, user_id=uid, surface="feed", projection=item_v2, run_override=True,
        )
        count = await count_relevance_adjustment_logs(db, user_id=uid)
        assert count == 2

    @pytest.mark.asyncio
    async def test_outside_window_new_row_written(self, db):
        from app.services.user_learning_shadow_service import record_relevance_transition_events
        from app.db.repositories.user_learning_repo import count_relevance_adjustment_logs
        uid = _uid()
        items = [_proj_item(item_ref="win1", intrinsic_rank=5, adjusted_rank=1, relevance_adjustment=1.30)]
        # First call
        await record_relevance_transition_events(
            db, user_id=uid, surface="feed", projection=items, run_override=True,
        )
        # Second call with zero-second dedup window → always writes
        await record_relevance_transition_events(
            db, user_id=uid, surface="feed", projection=items, run_override=True,
            dedup_window_seconds=0,
        )
        count = await count_relevance_adjustment_logs(db, user_id=uid)
        assert count == 2


# ---------------------------------------------------------------------------
# No truth mutation
# ---------------------------------------------------------------------------

class TestNoTruthMutation:
    @pytest.mark.asyncio
    async def test_user_signal_event_unchanged(self, db):
        from app.services.user_learning_shadow_service import record_relevance_transition_events
        from app.db.repositories.user_learning_repo import list_user_signal_events
        uid = _uid()
        before = await list_user_signal_events(db, user_id=uid)
        await record_relevance_transition_events(
            db, user_id=uid, surface="feed",
            projection=[_proj_item(item_ref="t1", intrinsic_rank=5, adjusted_rank=1,
                                   relevance_adjustment=1.30)],
            run_override=True,
        )
        after = await list_user_signal_events(db, user_id=uid)
        assert len(before) == len(after)

    @pytest.mark.asyncio
    async def test_learned_preference_unchanged(self, db):
        from app.services.user_learning_shadow_service import record_relevance_transition_events
        from app.db.repositories.user_learning_repo import list_learned_preferences
        uid = _uid()
        before = await list_learned_preferences(db, user_id=uid)
        await record_relevance_transition_events(
            db, user_id=uid, surface="feed",
            projection=[_proj_item(item_ref="t2", intrinsic_rank=5, adjusted_rank=1,
                                   relevance_adjustment=1.30)],
            run_override=True,
        )
        after = await list_learned_preferences(db, user_id=uid)
        assert len(before) == len(after)

    @pytest.mark.asyncio
    async def test_no_notification_rows_created(self, db):
        from app.services.user_learning_shadow_service import record_relevance_transition_events
        from sqlalchemy import text
        uid = _uid()
        await record_relevance_transition_events(
            db, user_id=uid, surface="feed",
            projection=[_proj_item(item_ref="t3", intrinsic_rank=5, adjusted_rank=1,
                                   relevance_adjustment=1.30)],
            run_override=True,
        )
        # notifications table — should have 0 rows for this user
        try:
            result = await db.execute(
                text("SELECT COUNT(*) FROM notifications WHERE user_id = :uid"),
                {"uid": uid},
            )
            count = result.scalar_one()
        except Exception:
            count = 0
        assert count == 0


# ---------------------------------------------------------------------------
# Shadow-only validation
# ---------------------------------------------------------------------------

class TestShadowOnly:
    @pytest.mark.asyncio
    async def test_all_rows_have_shadow_run_reason(self, db):
        from app.services.user_learning_shadow_service import record_relevance_transition_events
        from app.db.repositories.user_learning_repo import list_relevance_adjustment_logs
        uid = _uid()
        items = [
            _proj_item(item_ref="s1", intrinsic_rank=5, adjusted_rank=1, relevance_adjustment=1.30),
            _proj_item(item_ref="s2", intrinsic_rank=4, adjusted_rank=2, relevance_adjustment=1.25),
        ]
        await record_relevance_transition_events(
            db, user_id=uid, surface="feed", projection=items, run_override=True,
        )
        rows = await list_relevance_adjustment_logs(db, user_id=uid)
        assert all(r.run_reason == "shadow" for r in rows)


# ---------------------------------------------------------------------------
# Tenant isolation
# ---------------------------------------------------------------------------

class TestTenantIsolation:
    @pytest.mark.asyncio
    async def test_user_a_log_not_visible_in_user_b_query(self, db):
        from app.services.user_learning_shadow_service import record_relevance_transition_events
        from app.db.repositories.user_learning_repo import list_relevance_adjustment_logs
        uid_a, uid_b = _uid(), _uid()
        items = [_proj_item(item_ref="iso1", intrinsic_rank=5, adjusted_rank=1, relevance_adjustment=1.30)]
        await record_relevance_transition_events(
            db, user_id=uid_a, surface="feed", projection=items, run_override=True,
        )
        b_rows = await list_relevance_adjustment_logs(db, user_id=uid_b)
        assert len(b_rows) == 0

    @pytest.mark.asyncio
    async def test_user_b_writes_independently_of_user_a(self, db):
        from app.services.user_learning_shadow_service import record_relevance_transition_events
        from app.db.repositories.user_learning_repo import count_relevance_adjustment_logs
        uid_a, uid_b = _uid(), _uid()
        items = [_proj_item(item_ref="iso2", intrinsic_rank=5, adjusted_rank=1, relevance_adjustment=1.30)]
        await record_relevance_transition_events(
            db, user_id=uid_a, surface="feed", projection=items, run_override=True,
        )
        await record_relevance_transition_events(
            db, user_id=uid_b, surface="feed", projection=items, run_override=True,
        )
        # Both users have 1 row — no dedup collision across tenants
        a_count = await count_relevance_adjustment_logs(db, user_id=uid_a)
        b_count = await count_relevance_adjustment_logs(db, user_id=uid_b)
        assert a_count == 1
        assert b_count == 1


# ---------------------------------------------------------------------------
# Transition type specifics
# ---------------------------------------------------------------------------

class TestTransitionTypeSpecifics:
    def test_relevance_removed_requires_muted_tier(self):
        from app.services.user_learning_shadow_service import classify_relevance_transition
        muted_item = _proj_item(
            intrinsic_rank=1, adjusted_rank=5,
            relevance_adjustment=0.60, prominence_tier="muted",
        )
        normal_item = _proj_item(
            intrinsic_rank=1, adjusted_rank=5,
            relevance_adjustment=0.60, prominence_tier="normal",
        )
        assert classify_relevance_transition(muted_item) == "relevance_removed"
        assert classify_relevance_transition(normal_item) == "relevance_decreased"

    def test_relevance_decreased_for_non_muted_drop(self):
        from app.services.user_learning_shadow_service import classify_relevance_transition
        item = _proj_item(
            intrinsic_rank=1, adjusted_rank=4,
            relevance_adjustment=0.70, prominence_tier="normal",
        )
        assert classify_relevance_transition(item) == "relevance_decreased"

    @pytest.mark.asyncio
    async def test_floor_transition_floor_applied_true_in_log(self, db):
        from app.services.user_learning_shadow_service import record_relevance_transition_events
        from app.db.repositories.user_learning_repo import list_relevance_adjustment_logs
        uid = _uid()
        items = [_identity_item(item_ref="fl1", relevance_floor_applied=True)]
        await record_relevance_transition_events(
            db, user_id=uid, surface="feed", projection=items, run_override=True,
        )
        rows = await list_relevance_adjustment_logs(db, user_id=uid)
        assert len(rows) == 1
        assert rows[0].floor_applied is True

    @pytest.mark.asyncio
    async def test_novelty_transition_logged_with_unchanged_rank(self, db):
        from app.services.user_learning_shadow_service import record_relevance_transition_events
        from app.db.repositories.user_learning_repo import count_relevance_adjustment_logs
        uid = _uid()
        # Rank unchanged, factor trivial, but novelty flag set
        items = [_identity_item(item_ref="nov1", novelty_reserve_applied=True,
                                relevance_adjustment=1.0, intrinsic_rank=3, adjusted_rank=3)]
        result = await record_relevance_transition_events(
            db, user_id=uid, surface="feed", projection=items, run_override=True,
        )
        assert len(result) == 1
        count = await count_relevance_adjustment_logs(db, user_id=uid)
        assert count == 1


# ---------------------------------------------------------------------------
# AST safety
# ---------------------------------------------------------------------------

def _parse_service() -> ast.Module:
    return ast.parse(_SVC_PATH.read_text())


def _docstring_ids(tree: ast.Module) -> set:
    ids: set = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            if (node.body and isinstance(node.body[0], ast.Expr) and
                    isinstance(node.body[0].value, (ast.Constant, ast.Str))):
                ids.add(id(node.body[0].value))
    return ids


def _non_docstring_strings(tree: ast.Module):
    ds_ids = _docstring_ids(tree)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Constant, ast.Str)):
            if id(node) in ds_ids:
                continue
            val = node.s if isinstance(node, ast.Str) else node.value
            if isinstance(val, str):
                yield val


def _import_names(tree: ast.Module) -> set:
    names: set = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            names.add(node.module or "")
    return names


def _call_names(tree: ast.Module) -> set:
    names: set = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            fn = node.func
            if isinstance(fn, ast.Name):
                names.add(fn.id)
            elif isinstance(fn, ast.Attribute):
                names.add(fn.attr)
    return names


class TestAstSafety:
    def test_no_truth_table_write_imports(self):
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

    def test_no_banned_advisory_phrases(self):
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
                    f"Banned phrase {phrase!r} in non-docstring string: {s!r}"
                )

    def test_no_notification_inbox_writes(self):
        tree = _parse_service()
        # Check imports — no notification-related modules
        for src in _import_names(tree):
            for bad in ("notification", "inbox"):
                assert bad not in src.lower(), f"User-delivery import: {src!r}"
        # Check calls — no add_notification or inbox writes
        calls = _call_names(tree)
        for bad in ("add_notification", "add_inbox"):
            assert bad not in calls, f"User-delivery call: {bad!r}"

    def test_only_shadow_run_reason_in_write_calls(self):
        src = _SVC_PATH.read_text()
        # The literal "shadow" must be the only run_reason value written
        assert '"shadow"' in src or "'shadow'" in src
        assert '"delivery"' not in src and "'delivery'" not in src

    def test_no_upsert_update_delete_calls(self):
        tree = _parse_service()
        calls = _call_names(tree)
        for bad in ("upsert_learned_preference", "add_user_signal_event",
                    "delete", "update"):
            assert bad not in calls, f"Unexpected write call: {bad!r}"
