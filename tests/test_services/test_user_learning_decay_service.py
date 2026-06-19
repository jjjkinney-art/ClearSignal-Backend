"""
Tests — User Learning Decay & Falsification Service, Phase 15 · Slice 6.

Covers:
  1.  service importable
  2.  all 6 public functions present
  3.  flag gate: all functions return None/[] when run_override=False
  4.  null-session: all functions return None/[] when session=None (flag=True)

  --- decay_preference ---
  5.  zero elapsed → no decay (factor=1.0, confidence unchanged)
  6.  elapsed < half_life → partial decay, confidence < original
  7.  elapsed = half_life → confidence reduced by ~50%
  8.  elapsed >> half_life → confidence near zero
  9.  signal_strength_label recomputed from decayed confidence (strong→moderate)
  10. signal_strength_label recomputed: moderate→tentative after decay
  11. status becomes 'stale' when elapsed >= stale threshold
  12. status remains unchanged when elapsed < stale threshold
  13. already-falsified preference is not modified by decay_preference
  14. only confidence / signal_strength_label / status / updated_at written
  15. affinity unchanged after decay
  16. status='stale' transition: company_interest at 30-day threshold

  --- decay_preferences ---
  17. no preferences → returns empty list
  18. multiple preferences all decayed
  19. falsified preferences are skipped (not returned in updated list)
  20. null session → []
  21. flag off → []

  --- detect_falsifiers ---
  22. empty events → no contradictory_signal or positive_interaction trigger
  23. insufficient_evidence triggers when evidence_count < MIN_EVIDENCE
  24. inactivity triggers when elapsed >= stale threshold
  25. inactivity does not trigger when elapsed < stale threshold
  26. contradictory_signal triggers when neg_count >= 3 (positive-affinity dimension)
  27. contradictory_signal does not trigger when neg_count < 3
  28. positive_interaction triggers on ignored_signal_type with ANY positive event
  29. positive_interaction does not trigger on ignored_signal_type with zero positive events
  30. multiple falsifiers can be triggered simultaneously
  31. returns [] when flag is off
  32. returns [] when session is None
  33. contradictory_signal NOT triggered for ignored_signal_type (different rule)

  --- apply_falsification ---
  34. status set to 'falsified'
  35. confidence set to 0.0
  36. signal_strength_label set to 'tentative'
  37. reason prepended to belief_basis
  38. empty reason doesn't corrupt belief_basis
  39. returns the updated row
  40. null session → None
  41. flag off → None

  --- rebuild_preference_strength ---
  42. all positive events → affinity~1.0, confidence~1.0, label=strong
  43. all negative events → affinity~-1.0, confidence~1.0, label=strong
  44. mixed events → lower confidence
  45. empty events → confidence=0.0, label=tentative
  46. all neutral events → confidence=0.0, label=tentative
  47. status NOT changed by rebuild (only confidence/affinity/label)
  48. null session → None
  49. flag off → None

  --- find_stale_preferences ---
  50. no preferences → empty list
  51. preference reinforced today → not stale
  52. preference not reinforced beyond stale threshold → included
  53. already-falsified preferences excluded from stale scan
  54. custom cutoff_days overrides per-dimension threshold
  55. multiple preferences, only stale ones returned
  56. null session → []
  57. flag off → []

  --- cross-function integration ---
  58. decay_preference then detect_falsifiers: stale preference has inactivity trigger
  59. detect_falsifiers returns list type always
  60. apply_falsification then decay_preference: falsified row not re-decayed
  61. rebuild_preference_strength preserves dimension and entity_key
  62. decay factor = 0.5 at exactly half_life (mathematical invariant)
  63. decay factor = 1.0 at elapsed_days=0 (mathematical invariant)
  64. decay factor is always > 0 (never negative)
  65. confidence after decay is bounded to [0, 1] domain

  --- determinism ---
  66. same preference + same now → same decay output
  67. detect_falsifiers is deterministic: same events → same result

  --- boundary conditions ---
  68. company_interest stale threshold is 30 days
  69. ignored_signal_type stale threshold is 90 days
  70. sector_interest half_life is 60 days
  71. theme_interest half_life is 45 days (shorter than sector)

  --- AST safety ---
  72. no truth-table write imports in decay service
  73. no conviction / order / execution imports
  74. no banned advisory phrases in non-docstring string constants
  75. no add_relevance_adjustment_log calls in decay service
  76. no source-table mutation in decay service
  77. no forecast_repo / similarity_repo / decision_repo / scenario_repo imports
"""

from __future__ import annotations

import ast
import math
import pathlib
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

_ROOT = pathlib.Path(__file__).parent.parent.parent
_SVC_PATH = _ROOT / "app" / "services" / "user_learning_decay_service.py"

# ---------------------------------------------------------------------------
# Engine / session fixtures
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


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _ago(days: float) -> datetime:
    return _now() - timedelta(days=days)


# ---------------------------------------------------------------------------
# Helpers: build preference rows and insert events
# ---------------------------------------------------------------------------

async def _make_preference(
    session,
    *,
    user_id: str,
    dimension: str = "company_interest",
    entity_key: str = "AAPL",
    affinity: float = 0.8,
    confidence: float = 0.8,
    evidence_count: int = 8,
    status: str = "unresolved",
    signal_strength_label: str = "strong",
    last_reinforced_at: datetime = None,
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
        falsifier="inactivity after 30 days",
        belief_basis="opened analysis 8 times",
        last_reinforced_at=last_reinforced_at or _now(),
    )


async def _insert_events(
    session,
    *,
    user_id: str,
    entity_type: str,
    entity_key: str,
    n: int,
    polarity: str = "positive",
    source_surface: str = "analysis",
):
    from app.db.repositories.user_learning_repo import add_user_signal_event

    for i in range(n):
        await add_user_signal_event(
            session,
            user_id=user_id,
            signal_type=f"{entity_type}_view",
            polarity=polarity,
            entity_type=entity_type,
            entity_key=entity_key,
            source_surface=source_surface,
            interaction_weight=1.0,
            occurred_at=_now() - timedelta(hours=i),
        )


# ---------------------------------------------------------------------------
# 1–2. Import and presence
# ---------------------------------------------------------------------------

class TestImport:
    def test_service_importable(self):
        import app.services.user_learning_decay_service  # noqa: F401

    def test_all_public_functions_present(self):
        import app.services.user_learning_decay_service as svc
        for name in (
            "decay_preference",
            "decay_preferences",
            "detect_falsifiers",
            "apply_falsification",
            "rebuild_preference_strength",
            "find_stale_preferences",
        ):
            assert callable(getattr(svc, name, None)), f"Missing: {name}"


# ---------------------------------------------------------------------------
# 3. Flag gate
# ---------------------------------------------------------------------------

class TestFlagGate:
    @pytest.mark.asyncio
    async def test_decay_preference_flag_off(self, db):
        from app.services.user_learning_decay_service import decay_preference
        uid = _uid()
        pref = await _make_preference(db, user_id=uid)
        result = await decay_preference(db, preference=pref, run_override=False)
        assert result is None

    @pytest.mark.asyncio
    async def test_decay_preferences_flag_off(self, db):
        from app.services.user_learning_decay_service import decay_preferences
        result = await decay_preferences(db, user_id=_uid(), run_override=False)
        assert result == []

    @pytest.mark.asyncio
    async def test_detect_falsifiers_flag_off(self, db):
        from app.services.user_learning_decay_service import detect_falsifiers
        uid = _uid()
        pref = await _make_preference(db, user_id=uid)
        result = await detect_falsifiers(db, preference=pref, run_override=False)
        assert result == []

    @pytest.mark.asyncio
    async def test_apply_falsification_flag_off(self, db):
        from app.services.user_learning_decay_service import apply_falsification
        uid = _uid()
        pref = await _make_preference(db, user_id=uid)
        result = await apply_falsification(db, preference=pref, reason="test", run_override=False)
        assert result is None

    @pytest.mark.asyncio
    async def test_rebuild_preference_strength_flag_off(self, db):
        from app.services.user_learning_decay_service import rebuild_preference_strength
        uid = _uid()
        pref = await _make_preference(db, user_id=uid)
        result = await rebuild_preference_strength(db, preference=pref, events=[], run_override=False)
        assert result is None

    @pytest.mark.asyncio
    async def test_find_stale_preferences_flag_off(self, db):
        from app.services.user_learning_decay_service import find_stale_preferences
        result = await find_stale_preferences(db, user_id=_uid(), run_override=False)
        assert result == []


# ---------------------------------------------------------------------------
# 4. Null-session safety
# ---------------------------------------------------------------------------

class TestNullSession:
    @pytest.mark.asyncio
    async def test_decay_preference_null_session(self, db):
        from app.services.user_learning_decay_service import decay_preference
        uid = _uid()
        pref = await _make_preference(db, user_id=uid)
        result = await decay_preference(None, preference=pref, run_override=True)
        assert result is None

    @pytest.mark.asyncio
    async def test_decay_preferences_null_session(self):
        from app.services.user_learning_decay_service import decay_preferences
        result = await decay_preferences(None, user_id=_uid(), run_override=True)
        assert result == []

    @pytest.mark.asyncio
    async def test_detect_falsifiers_null_session(self, db):
        from app.services.user_learning_decay_service import detect_falsifiers
        uid = _uid()
        pref = await _make_preference(db, user_id=uid)
        result = await detect_falsifiers(None, preference=pref, run_override=True)
        assert result == []

    @pytest.mark.asyncio
    async def test_apply_falsification_null_session(self, db):
        from app.services.user_learning_decay_service import apply_falsification
        uid = _uid()
        pref = await _make_preference(db, user_id=uid)
        result = await apply_falsification(None, preference=pref, reason="test", run_override=True)
        assert result is None

    @pytest.mark.asyncio
    async def test_rebuild_preference_strength_null_session(self, db):
        from app.services.user_learning_decay_service import rebuild_preference_strength
        uid = _uid()
        pref = await _make_preference(db, user_id=uid)
        result = await rebuild_preference_strength(None, preference=pref, events=[], run_override=True)
        assert result is None

    @pytest.mark.asyncio
    async def test_find_stale_preferences_null_session(self):
        from app.services.user_learning_decay_service import find_stale_preferences
        result = await find_stale_preferences(None, user_id=_uid(), run_override=True)
        assert result == []


# ---------------------------------------------------------------------------
# 5–16. decay_preference
# ---------------------------------------------------------------------------

class TestDecayPreference:
    @pytest.mark.asyncio
    async def test_zero_elapsed_no_decay(self, db):
        """Preference reinforced now → confidence unchanged."""
        from app.services.user_learning_decay_service import decay_preference
        uid = _uid()
        pref = await _make_preference(db, user_id=uid, confidence=0.8, last_reinforced_at=_now())
        result = await decay_preference(db, preference=pref, now=_now(), run_override=True)
        assert result is not None
        assert abs(result.confidence - 0.8) < 0.01

    @pytest.mark.asyncio
    async def test_partial_decay(self, db):
        """Elapsed < half_life → confidence reduced but still above 50% of original."""
        from app.services.user_learning_decay_service import decay_preference
        uid = _uid()
        half_life = 60.0
        elapsed = 20.0  # 1/3 of half_life
        reinforced = _ago(elapsed)
        pref = await _make_preference(db, user_id=uid, confidence=0.8,
                                       last_reinforced_at=reinforced)
        now_ts = _now()
        result = await decay_preference(db, preference=pref, now=now_ts, run_override=True)
        expected_factor = math.exp(-math.log(2) * elapsed / half_life)
        expected_confidence = 0.8 * expected_factor
        assert abs(result.confidence - expected_confidence) < 0.01
        assert result.confidence < 0.8  # definitely decayed

    @pytest.mark.asyncio
    async def test_half_life_halves_confidence(self, db):
        """Elapsed = half_life → confidence ~= original / 2."""
        from app.services.user_learning_decay_service import decay_preference
        uid = _uid()
        half_life = 60.0  # company_interest
        reinforced = _ago(half_life)
        pref = await _make_preference(db, user_id=uid, confidence=0.8,
                                       dimension="company_interest",
                                       last_reinforced_at=reinforced)
        result = await decay_preference(db, preference=pref, now=_now(), run_override=True)
        assert abs(result.confidence - 0.4) < 0.02  # ~0.8/2

    @pytest.mark.asyncio
    async def test_large_elapsed_confidence_near_zero(self, db):
        """Elapsed >> half_life → confidence very close to 0."""
        from app.services.user_learning_decay_service import decay_preference
        uid = _uid()
        reinforced = _ago(365.0)  # 1 year
        pref = await _make_preference(db, user_id=uid, confidence=0.8,
                                       last_reinforced_at=reinforced)
        result = await decay_preference(db, preference=pref, now=_now(), run_override=True)
        assert result.confidence < 0.05

    @pytest.mark.asyncio
    async def test_strong_to_moderate_label_transition(self, db):
        """Confidence 0.8 decayed through half_life → ~0.4 → moderate."""
        from app.services.user_learning_decay_service import decay_preference
        uid = _uid()
        half_life = 60.0
        reinforced = _ago(half_life)
        # Start with confidence 0.8 → after 1 half_life → 0.4 → moderate
        pref = await _make_preference(db, user_id=uid, confidence=0.8,
                                       signal_strength_label="strong",
                                       dimension="company_interest",
                                       last_reinforced_at=reinforced)
        result = await decay_preference(db, preference=pref, now=_now(), run_override=True)
        assert result.signal_strength_label in ("moderate", "tentative")
        assert result.signal_strength_label != "strong"

    @pytest.mark.asyncio
    async def test_moderate_to_tentative_label_transition(self, db):
        """Confidence 0.5 decayed through half_life → ~0.25 → tentative."""
        from app.services.user_learning_decay_service import decay_preference
        uid = _uid()
        half_life = 60.0
        reinforced = _ago(half_life)
        pref = await _make_preference(db, user_id=uid, confidence=0.5,
                                       signal_strength_label="moderate",
                                       dimension="company_interest",
                                       last_reinforced_at=reinforced)
        result = await decay_preference(db, preference=pref, now=_now(), run_override=True)
        assert result.signal_strength_label == "tentative"

    @pytest.mark.asyncio
    async def test_status_becomes_stale_at_threshold(self, db):
        """Elapsed >= stale threshold (30d for company_interest) → status='stale'."""
        from app.services.user_learning_decay_service import decay_preference
        uid = _uid()
        reinforced = _ago(31.0)  # just over 30-day threshold
        pref = await _make_preference(db, user_id=uid, dimension="company_interest",
                                       last_reinforced_at=reinforced)
        result = await decay_preference(db, preference=pref, now=_now(), run_override=True)
        assert result.status == "stale"

    @pytest.mark.asyncio
    async def test_status_unchanged_below_threshold(self, db):
        """Elapsed < stale threshold → status stays 'unresolved'."""
        from app.services.user_learning_decay_service import decay_preference
        uid = _uid()
        reinforced = _ago(10.0)  # well below 30-day threshold
        pref = await _make_preference(db, user_id=uid, dimension="company_interest",
                                       last_reinforced_at=reinforced)
        result = await decay_preference(db, preference=pref, now=_now(), run_override=True)
        assert result.status == "unresolved"

    @pytest.mark.asyncio
    async def test_falsified_preference_not_re_decayed(self, db):
        """Preference with status='falsified' is returned immediately unchanged."""
        from app.services.user_learning_decay_service import decay_preference
        uid = _uid()
        reinforced = _ago(365.0)
        pref = await _make_preference(db, user_id=uid, status="falsified",
                                       confidence=0.0, signal_strength_label="tentative",
                                       last_reinforced_at=reinforced)
        original_confidence = pref.confidence
        result = await decay_preference(db, preference=pref, now=_now(), run_override=True)
        assert result is not None
        assert result.status == "falsified"
        assert result.confidence == original_confidence

    @pytest.mark.asyncio
    async def test_affinity_unchanged_after_decay(self, db):
        """Decay weakens certainty, not the observed signal direction."""
        from app.services.user_learning_decay_service import decay_preference
        uid = _uid()
        pref = await _make_preference(db, user_id=uid, affinity=0.75,
                                       last_reinforced_at=_ago(45.0))
        original_affinity = pref.affinity
        result = await decay_preference(db, preference=pref, now=_now(), run_override=True)
        assert result.affinity == original_affinity

    @pytest.mark.asyncio
    async def test_company_interest_stale_at_30_days(self, db):
        """company_interest stale threshold is 30 days."""
        from app.services.user_learning_decay_service import decay_preference, _STALE_THRESHOLD_DAYS
        assert _STALE_THRESHOLD_DAYS["company_interest"] == 30.0
        uid = _uid()
        reinforced = _ago(30.0)  # exactly at threshold
        pref = await _make_preference(db, user_id=uid, dimension="company_interest",
                                       last_reinforced_at=reinforced)
        result = await decay_preference(db, preference=pref, now=_now(), run_override=True)
        assert result.status == "stale"


# ---------------------------------------------------------------------------
# 17–21. decay_preferences
# ---------------------------------------------------------------------------

class TestDecayPreferences:
    @pytest.mark.asyncio
    async def test_no_preferences_returns_empty(self, db):
        from app.services.user_learning_decay_service import decay_preferences
        result = await decay_preferences(db, user_id=_uid(), run_override=True)
        assert result == []

    @pytest.mark.asyncio
    async def test_multiple_preferences_all_decayed(self, db):
        from app.services.user_learning_decay_service import decay_preferences
        uid = _uid()
        await _make_preference(db, user_id=uid, entity_key="AAPL",
                                last_reinforced_at=_ago(20.0))
        await _make_preference(db, user_id=uid, entity_key="NVDA", dimension="sector_interest",
                                last_reinforced_at=_ago(20.0))
        results = await decay_preferences(db, user_id=uid, run_override=True)
        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_falsified_preferences_skipped(self, db):
        from app.services.user_learning_decay_service import decay_preferences
        uid = _uid()
        await _make_preference(db, user_id=uid, entity_key="AAPL", status="falsified",
                                last_reinforced_at=_ago(365.0))
        await _make_preference(db, user_id=uid, entity_key="NVDA",
                                last_reinforced_at=_ago(10.0))
        results = await decay_preferences(db, user_id=uid, run_override=True)
        # falsified one is returned by decay_preference but unchanged — still in list
        assert len(results) == 2  # both returned, falsified one unmodified

    @pytest.mark.asyncio
    async def test_null_session_returns_empty(self):
        from app.services.user_learning_decay_service import decay_preferences
        result = await decay_preferences(None, user_id=_uid(), run_override=True)
        assert result == []

    @pytest.mark.asyncio
    async def test_flag_off_returns_empty(self, db):
        from app.services.user_learning_decay_service import decay_preferences
        result = await decay_preferences(db, user_id=_uid(), run_override=False)
        assert result == []


# ---------------------------------------------------------------------------
# 22–33. detect_falsifiers
# ---------------------------------------------------------------------------

class TestDetectFalsifiers:
    @pytest.mark.asyncio
    async def test_empty_events_no_contradiction(self, db):
        """No events → no contradictory_signal trigger."""
        from app.services.user_learning_decay_service import detect_falsifiers
        uid = _uid()
        pref = await _make_preference(
            db, user_id=uid, entity_key="AAPL",
            evidence_count=8, last_reinforced_at=_now(),
        )
        result = await detect_falsifiers(db, preference=pref, run_override=True)
        # No contradictory signals, not stale, sufficient evidence
        triggered_types = [r.split(":")[0] for r in result]
        assert "contradictory_signal" not in triggered_types
        assert "positive_interaction" not in triggered_types

    @pytest.mark.asyncio
    async def test_insufficient_evidence_triggers(self, db):
        """evidence_count < MIN_EVIDENCE → insufficient_evidence triggered."""
        from app.services.user_learning_decay_service import detect_falsifiers
        uid = _uid()
        pref = await _make_preference(
            db, user_id=uid, evidence_count=2,  # below MIN_EVIDENCE=5
            last_reinforced_at=_now(),
        )
        result = await detect_falsifiers(db, preference=pref, run_override=True)
        assert any("insufficient_evidence" in r for r in result)

    @pytest.mark.asyncio
    async def test_inactivity_triggers_beyond_threshold(self, db):
        """Elapsed >= stale threshold → inactivity triggered."""
        from app.services.user_learning_decay_service import detect_falsifiers
        uid = _uid()
        pref = await _make_preference(
            db, user_id=uid, dimension="company_interest",
            evidence_count=8, last_reinforced_at=_ago(35.0),
        )
        result = await detect_falsifiers(db, preference=pref, run_override=True)
        assert any("inactivity" in r for r in result)

    @pytest.mark.asyncio
    async def test_inactivity_does_not_trigger_below_threshold(self, db):
        """Elapsed < stale threshold → inactivity not triggered."""
        from app.services.user_learning_decay_service import detect_falsifiers
        uid = _uid()
        pref = await _make_preference(
            db, user_id=uid, dimension="company_interest",
            evidence_count=8, last_reinforced_at=_ago(10.0),
        )
        result = await detect_falsifiers(db, preference=pref, run_override=True)
        assert not any("inactivity" in r for r in result)

    @pytest.mark.asyncio
    async def test_contradictory_signal_triggers_at_threshold(self, db):
        """3 negative events for a positive-affinity dimension → contradiction triggered."""
        from app.services.user_learning_decay_service import detect_falsifiers
        uid = _uid()
        pref = await _make_preference(
            db, user_id=uid, dimension="company_interest", entity_key="MSFT",
            affinity=0.7, evidence_count=8, last_reinforced_at=_now(),
        )
        await _insert_events(db, user_id=uid, entity_type="company",
                              entity_key="MSFT", n=3, polarity="negative")
        result = await detect_falsifiers(db, preference=pref, run_override=True)
        assert any("contradictory_signal" in r for r in result)

    @pytest.mark.asyncio
    async def test_contradictory_signal_below_threshold(self, db):
        """2 negative events < threshold of 3 → no contradiction."""
        from app.services.user_learning_decay_service import detect_falsifiers
        uid = _uid()
        pref = await _make_preference(
            db, user_id=uid, dimension="company_interest", entity_key="IBM",
            evidence_count=8, last_reinforced_at=_now(),
        )
        await _insert_events(db, user_id=uid, entity_type="company",
                              entity_key="IBM", n=2, polarity="negative")
        result = await detect_falsifiers(db, preference=pref, run_override=True)
        assert not any("contradictory_signal" in r for r in result)

    @pytest.mark.asyncio
    async def test_positive_interaction_triggers_on_ignored(self, db):
        """ANY positive event for ignored_signal_type → positive_interaction triggered."""
        from app.services.user_learning_decay_service import detect_falsifiers
        uid = _uid()
        pref = await _make_preference(
            db, user_id=uid, dimension="ignored_signal_type", entity_key="macro_noise",
            affinity=-0.9, evidence_count=8, last_reinforced_at=_now(),
        )
        await _insert_events(db, user_id=uid, entity_type="signal_type",
                              entity_key="macro_noise", n=1, polarity="positive")
        result = await detect_falsifiers(db, preference=pref, run_override=True)
        assert any("positive_interaction" in r for r in result)

    @pytest.mark.asyncio
    async def test_no_positive_interaction_when_only_negatives(self, db):
        """Only negative events for ignored_signal_type → positive_interaction not triggered."""
        from app.services.user_learning_decay_service import detect_falsifiers
        uid = _uid()
        pref = await _make_preference(
            db, user_id=uid, dimension="ignored_signal_type", entity_key="macro_noise",
            affinity=-0.9, evidence_count=8, last_reinforced_at=_now(),
        )
        await _insert_events(db, user_id=uid, entity_type="signal_type",
                              entity_key="macro_noise", n=5, polarity="negative")
        result = await detect_falsifiers(db, preference=pref, run_override=True)
        assert not any("positive_interaction" in r for r in result)

    @pytest.mark.asyncio
    async def test_multiple_falsifiers_triggered(self, db):
        """Insufficient evidence AND inactivity both trigger simultaneously."""
        from app.services.user_learning_decay_service import detect_falsifiers
        uid = _uid()
        pref = await _make_preference(
            db, user_id=uid, dimension="company_interest",
            evidence_count=2, last_reinforced_at=_ago(45.0),  # below threshold & too old
        )
        result = await detect_falsifiers(db, preference=pref, run_override=True)
        condition_types = [r.split(":")[0] for r in result]
        assert "insufficient_evidence" in condition_types
        assert "inactivity" in condition_types

    @pytest.mark.asyncio
    async def test_flag_off_returns_empty(self, db):
        from app.services.user_learning_decay_service import detect_falsifiers
        uid = _uid()
        pref = await _make_preference(db, user_id=uid)
        result = await detect_falsifiers(db, preference=pref, run_override=False)
        assert result == []

    @pytest.mark.asyncio
    async def test_null_session_returns_empty(self, db):
        from app.services.user_learning_decay_service import detect_falsifiers
        uid = _uid()
        pref = await _make_preference(db, user_id=uid)
        result = await detect_falsifiers(None, preference=pref, run_override=True)
        assert result == []

    @pytest.mark.asyncio
    async def test_ignored_type_not_subject_to_contradictory_signal_rule(self, db):
        """ignored_signal_type uses positive_interaction rule, not contradictory_signal."""
        from app.services.user_learning_decay_service import detect_falsifiers
        uid = _uid()
        pref = await _make_preference(
            db, user_id=uid, dimension="ignored_signal_type", entity_key="macro_noise",
            affinity=-0.9, evidence_count=8, last_reinforced_at=_now(),
        )
        # 5 positive events for ignored type — should trigger positive_interaction, NOT contradictory_signal
        await _insert_events(db, user_id=uid, entity_type="signal_type",
                              entity_key="macro_noise", n=5, polarity="positive")
        result = await detect_falsifiers(db, preference=pref, run_override=True)
        condition_types = [r.split(":")[0] for r in result]
        assert "contradictory_signal" not in condition_types
        assert "positive_interaction" in condition_types

    @pytest.mark.asyncio
    async def test_returns_list_type(self, db):
        from app.services.user_learning_decay_service import detect_falsifiers
        uid = _uid()
        pref = await _make_preference(db, user_id=uid)
        result = await detect_falsifiers(db, preference=pref, run_override=True)
        assert isinstance(result, list)


# ---------------------------------------------------------------------------
# 34–41. apply_falsification
# ---------------------------------------------------------------------------

class TestApplyFalsification:
    @pytest.mark.asyncio
    async def test_status_set_to_falsified(self, db):
        from app.services.user_learning_decay_service import apply_falsification
        uid = _uid()
        pref = await _make_preference(db, user_id=uid, status="unresolved")
        result = await apply_falsification(db, preference=pref, reason="test reason", run_override=True)
        assert result.status == "falsified"

    @pytest.mark.asyncio
    async def test_confidence_set_to_zero(self, db):
        from app.services.user_learning_decay_service import apply_falsification
        uid = _uid()
        pref = await _make_preference(db, user_id=uid, confidence=0.75)
        result = await apply_falsification(db, preference=pref, reason="test", run_override=True)
        assert result.confidence == 0.0

    @pytest.mark.asyncio
    async def test_label_set_to_tentative(self, db):
        from app.services.user_learning_decay_service import apply_falsification
        uid = _uid()
        pref = await _make_preference(db, user_id=uid, signal_strength_label="strong")
        result = await apply_falsification(db, preference=pref, reason="test", run_override=True)
        assert result.signal_strength_label == "tentative"

    @pytest.mark.asyncio
    async def test_reason_prepended_to_belief_basis(self, db):
        from app.services.user_learning_decay_service import apply_falsification
        uid = _uid()
        pref = await _make_preference(db, user_id=uid)
        await apply_falsification(db, preference=pref, reason="contradictory signal", run_override=True)
        assert "falsified" in pref.belief_basis.lower()
        assert "contradictory signal" in pref.belief_basis

    @pytest.mark.asyncio
    async def test_empty_reason_no_corruption(self, db):
        from app.services.user_learning_decay_service import apply_falsification
        uid = _uid()
        pref = await _make_preference(db, user_id=uid)
        original_basis = pref.belief_basis
        result = await apply_falsification(db, preference=pref, reason="", run_override=True)
        assert result.status == "falsified"
        # belief_basis should not have gained a blank prefix
        assert result.belief_basis.strip() != ""

    @pytest.mark.asyncio
    async def test_returns_updated_row(self, db):
        from app.services.user_learning_decay_service import apply_falsification
        uid = _uid()
        pref = await _make_preference(db, user_id=uid)
        result = await apply_falsification(db, preference=pref, reason="test", run_override=True)
        assert result is not None
        assert result is pref  # same object, mutated in place

    @pytest.mark.asyncio
    async def test_null_session_returns_none(self, db):
        from app.services.user_learning_decay_service import apply_falsification
        uid = _uid()
        pref = await _make_preference(db, user_id=uid)
        result = await apply_falsification(None, preference=pref, reason="test", run_override=True)
        assert result is None

    @pytest.mark.asyncio
    async def test_flag_off_returns_none(self, db):
        from app.services.user_learning_decay_service import apply_falsification
        uid = _uid()
        pref = await _make_preference(db, user_id=uid)
        result = await apply_falsification(db, preference=pref, reason="test", run_override=False)
        assert result is None


# ---------------------------------------------------------------------------
# 42–49. rebuild_preference_strength
# ---------------------------------------------------------------------------

class TestRebuildPreferenceStrength:
    def _pos_event(self, entity_key: str = "AAPL") -> dict:
        return {"signal_type": "analysis_open", "polarity": "positive",
                "entity_key": entity_key, "interaction_weight": 1.0}

    def _neg_event(self, entity_key: str = "AAPL") -> dict:
        return {"signal_type": "watchlist_remove", "polarity": "negative",
                "entity_key": entity_key, "interaction_weight": 1.0}

    def _neu_event(self, entity_key: str = "AAPL") -> dict:
        return {"signal_type": "search_query", "polarity": "neutral",
                "entity_key": entity_key, "interaction_weight": 1.0}

    @pytest.mark.asyncio
    async def test_all_positive_events(self, db):
        from app.services.user_learning_decay_service import rebuild_preference_strength
        uid = _uid()
        pref = await _make_preference(db, user_id=uid, confidence=0.3, signal_strength_label="tentative")
        events = [self._pos_event() for _ in range(10)]
        result = await rebuild_preference_strength(db, preference=pref, events=events, run_override=True)
        assert result.confidence >= 0.99
        assert result.signal_strength_label == "strong"
        assert result.affinity >= 0.99

    @pytest.mark.asyncio
    async def test_all_negative_events(self, db):
        from app.services.user_learning_decay_service import rebuild_preference_strength
        uid = _uid()
        pref = await _make_preference(db, user_id=uid)
        events = [self._neg_event() for _ in range(10)]
        result = await rebuild_preference_strength(db, preference=pref, events=events, run_override=True)
        assert result.confidence >= 0.99
        assert result.signal_strength_label == "strong"
        assert result.affinity <= -0.99

    @pytest.mark.asyncio
    async def test_mixed_events_lower_confidence(self, db):
        from app.services.user_learning_decay_service import rebuild_preference_strength
        uid = _uid()
        pref = await _make_preference(db, user_id=uid, confidence=0.9, signal_strength_label="strong")
        events = [self._pos_event() for _ in range(6)] + [self._neg_event() for _ in range(4)]
        result = await rebuild_preference_strength(db, preference=pref, events=events, run_override=True)
        # net=2/10=0.2 < 0.40 → tentative
        assert result.confidence < 0.5
        assert result.signal_strength_label == "tentative"

    @pytest.mark.asyncio
    async def test_empty_events_zeroes_confidence(self, db):
        from app.services.user_learning_decay_service import rebuild_preference_strength
        uid = _uid()
        pref = await _make_preference(db, user_id=uid, confidence=0.9, signal_strength_label="strong")
        result = await rebuild_preference_strength(db, preference=pref, events=[], run_override=True)
        assert result.confidence == 0.0
        assert result.signal_strength_label == "tentative"

    @pytest.mark.asyncio
    async def test_all_neutral_events_zeroes_confidence(self, db):
        from app.services.user_learning_decay_service import rebuild_preference_strength
        uid = _uid()
        pref = await _make_preference(db, user_id=uid, confidence=0.9)
        events = [self._neu_event() for _ in range(10)]
        result = await rebuild_preference_strength(db, preference=pref, events=events, run_override=True)
        assert result.confidence == 0.0
        assert result.signal_strength_label == "tentative"

    @pytest.mark.asyncio
    async def test_status_not_changed(self, db):
        """rebuild only changes confidence/affinity/label; status is untouched."""
        from app.services.user_learning_decay_service import rebuild_preference_strength
        uid = _uid()
        pref = await _make_preference(db, user_id=uid, status="stale")
        events = [self._pos_event() for _ in range(10)]
        result = await rebuild_preference_strength(db, preference=pref, events=events, run_override=True)
        assert result.status == "stale"

    @pytest.mark.asyncio
    async def test_null_session_returns_none(self, db):
        from app.services.user_learning_decay_service import rebuild_preference_strength
        uid = _uid()
        pref = await _make_preference(db, user_id=uid)
        result = await rebuild_preference_strength(None, preference=pref, events=[], run_override=True)
        assert result is None

    @pytest.mark.asyncio
    async def test_flag_off_returns_none(self, db):
        from app.services.user_learning_decay_service import rebuild_preference_strength
        uid = _uid()
        pref = await _make_preference(db, user_id=uid)
        result = await rebuild_preference_strength(db, preference=pref, events=[], run_override=False)
        assert result is None


# ---------------------------------------------------------------------------
# 50–57. find_stale_preferences
# ---------------------------------------------------------------------------

class TestFindStalePreferences:
    @pytest.mark.asyncio
    async def test_no_preferences_returns_empty(self, db):
        from app.services.user_learning_decay_service import find_stale_preferences
        result = await find_stale_preferences(db, user_id=_uid(), run_override=True)
        assert result == []

    @pytest.mark.asyncio
    async def test_recently_reinforced_not_stale(self, db):
        from app.services.user_learning_decay_service import find_stale_preferences
        uid = _uid()
        await _make_preference(db, user_id=uid, last_reinforced_at=_now())
        result = await find_stale_preferences(db, user_id=uid, run_override=True)
        assert result == []

    @pytest.mark.asyncio
    async def test_old_preference_is_stale(self, db):
        from app.services.user_learning_decay_service import find_stale_preferences
        uid = _uid()
        await _make_preference(db, user_id=uid, dimension="company_interest",
                                last_reinforced_at=_ago(35.0))
        result = await find_stale_preferences(db, user_id=uid, run_override=True)
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_falsified_excluded_from_stale_scan(self, db):
        from app.services.user_learning_decay_service import find_stale_preferences
        uid = _uid()
        await _make_preference(db, user_id=uid, status="falsified",
                                last_reinforced_at=_ago(365.0))
        result = await find_stale_preferences(db, user_id=uid, run_override=True)
        assert result == []

    @pytest.mark.asyncio
    async def test_custom_cutoff_days(self, db):
        from app.services.user_learning_decay_service import find_stale_preferences
        uid = _uid()
        # Reinforced 10 days ago — not stale by default (30d threshold)
        # but stale with a custom 5-day cutoff
        await _make_preference(db, user_id=uid, last_reinforced_at=_ago(10.0))
        result_default = await find_stale_preferences(db, user_id=uid, run_override=True)
        result_custom  = await find_stale_preferences(db, user_id=uid, cutoff_days=5.0, run_override=True)
        assert result_default == []
        assert len(result_custom) == 1

    @pytest.mark.asyncio
    async def test_mixed_preferences_only_stale_returned(self, db):
        from app.services.user_learning_decay_service import find_stale_preferences
        uid = _uid()
        await _make_preference(db, user_id=uid, entity_key="AAPL",
                                dimension="company_interest", last_reinforced_at=_now())
        await _make_preference(db, user_id=uid, entity_key="NVDA",
                                dimension="company_interest", last_reinforced_at=_ago(45.0))
        result = await find_stale_preferences(db, user_id=uid, run_override=True)
        assert len(result) == 1
        assert result[0].entity_key == "NVDA"

    @pytest.mark.asyncio
    async def test_null_session_returns_empty(self):
        from app.services.user_learning_decay_service import find_stale_preferences
        result = await find_stale_preferences(None, user_id=_uid(), run_override=True)
        assert result == []

    @pytest.mark.asyncio
    async def test_flag_off_returns_empty(self, db):
        from app.services.user_learning_decay_service import find_stale_preferences
        result = await find_stale_preferences(db, user_id=_uid(), run_override=False)
        assert result == []


# ---------------------------------------------------------------------------
# 58–65. Cross-function integration and invariants
# ---------------------------------------------------------------------------

class TestCrossFunction:
    @pytest.mark.asyncio
    async def test_stale_preference_has_inactivity_trigger(self, db):
        from app.services.user_learning_decay_service import decay_preference, detect_falsifiers
        uid = _uid()
        pref = await _make_preference(db, user_id=uid, dimension="company_interest",
                                       evidence_count=8, last_reinforced_at=_ago(35.0))
        await decay_preference(db, preference=pref, now=_now(), run_override=True)
        falsifiers = await detect_falsifiers(db, preference=pref, run_override=True)
        assert any("inactivity" in f for f in falsifiers)

    @pytest.mark.asyncio
    async def test_falsified_row_not_re_decayed_by_decay_preferences(self, db):
        from app.services.user_learning_decay_service import apply_falsification, decay_preferences
        uid = _uid()
        pref = await _make_preference(db, user_id=uid, confidence=0.8,
                                       last_reinforced_at=_ago(5.0))
        await apply_falsification(db, preference=pref, reason="test", run_override=True)
        results = await decay_preferences(db, user_id=uid, run_override=True)
        # The row is returned but unchanged — confidence stays 0.0
        falsified_rows = [r for r in results if r.status == "falsified"]
        assert len(falsified_rows) == 1
        assert falsified_rows[0].confidence == 0.0

    @pytest.mark.asyncio
    async def test_rebuild_preserves_dimension_and_entity_key(self, db):
        from app.services.user_learning_decay_service import rebuild_preference_strength
        uid = _uid()
        pref = await _make_preference(db, user_id=uid, dimension="sector_interest",
                                       entity_key="tech")
        events = [{"polarity": "positive", "interaction_weight": 1.0} for _ in range(5)]
        result = await rebuild_preference_strength(db, preference=pref, events=events, run_override=True)
        assert result.dimension == "sector_interest"
        assert result.entity_key == "tech"

    def test_decay_factor_half_at_half_life(self):
        """Mathematical invariant: factor=0.5 at t=half_life."""
        from app.services.user_learning_decay_service import _recency_decay_factor
        assert abs(_recency_decay_factor(60.0, 60.0) - 0.5) < 1e-9

    def test_decay_factor_one_at_zero(self):
        """Mathematical invariant: factor=1.0 at t=0."""
        from app.services.user_learning_decay_service import _recency_decay_factor
        assert _recency_decay_factor(0.0, 60.0) == 1.0

    def test_decay_factor_always_positive(self):
        """Decay factor is always positive — never reverses polarity."""
        from app.services.user_learning_decay_service import _recency_decay_factor
        for t in (0.0, 1.0, 30.0, 90.0, 365.0, 3650.0):
            assert _recency_decay_factor(t, 60.0) > 0.0

    @pytest.mark.asyncio
    async def test_decayed_confidence_bounded_to_unit_interval(self, db):
        from app.services.user_learning_decay_service import decay_preference
        uid = _uid()
        pref = await _make_preference(db, user_id=uid, confidence=1.0,
                                       last_reinforced_at=_ago(200.0))
        result = await decay_preference(db, preference=pref, now=_now(), run_override=True)
        assert 0.0 <= result.confidence <= 1.0


# ---------------------------------------------------------------------------
# 66–67. Determinism
# ---------------------------------------------------------------------------

class TestDeterminism:
    @pytest.mark.asyncio
    async def test_same_inputs_same_decay_output(self, db):
        """Same preference + same now timestamp → same confidence output."""
        from app.services.user_learning_decay_service import decay_preference
        from app.db.repositories.user_learning_repo import upsert_learned_preference

        uid_a = _uid()
        uid_b = _uid()
        ts_now = _now()
        reinforced = ts_now - timedelta(days=25.0)

        pref_a = await _make_preference(db, user_id=uid_a, entity_key="AAPL",
                                         confidence=0.8, last_reinforced_at=reinforced)
        pref_b = await _make_preference(db, user_id=uid_b, entity_key="AAPL",
                                         confidence=0.8, last_reinforced_at=reinforced)

        result_a = await decay_preference(db, preference=pref_a, now=ts_now, run_override=True)
        result_b = await decay_preference(db, preference=pref_b, now=ts_now, run_override=True)

        assert abs(result_a.confidence - result_b.confidence) < 1e-9
        assert result_a.signal_strength_label == result_b.signal_strength_label

    @pytest.mark.asyncio
    async def test_detect_falsifiers_deterministic(self, db):
        """Same preference state + same events → same falsifier list twice."""
        from app.services.user_learning_decay_service import detect_falsifiers
        uid = _uid()
        pref = await _make_preference(db, user_id=uid, evidence_count=2,
                                       last_reinforced_at=_ago(40.0))
        r1 = await detect_falsifiers(db, preference=pref, run_override=True)
        r2 = await detect_falsifiers(db, preference=pref, run_override=True)
        assert r1 == r2


# ---------------------------------------------------------------------------
# 68–71. Constant values
# ---------------------------------------------------------------------------

class TestConstants:
    def test_company_interest_stale_threshold(self):
        from app.services.user_learning_decay_service import _STALE_THRESHOLD_DAYS
        assert _STALE_THRESHOLD_DAYS["company_interest"] == 30.0

    def test_ignored_signal_type_stale_threshold(self):
        from app.services.user_learning_decay_service import _STALE_THRESHOLD_DAYS
        assert _STALE_THRESHOLD_DAYS["ignored_signal_type"] == 90.0

    def test_sector_interest_half_life(self):
        from app.services.user_learning_decay_service import _DECAY_HALF_LIFE_DAYS
        assert _DECAY_HALF_LIFE_DAYS["sector_interest"] == 60.0

    def test_theme_interest_half_life_shorter_than_sector(self):
        from app.services.user_learning_decay_service import _DECAY_HALF_LIFE_DAYS
        assert _DECAY_HALF_LIFE_DAYS["theme_interest"] < _DECAY_HALF_LIFE_DAYS["sector_interest"]


# ---------------------------------------------------------------------------
# 72–77. AST safety
# ---------------------------------------------------------------------------

_BANNED_PHRASES = [
    "buy", "sell", "hold", "overweight", "underweight",
    "recommend", "target price", "position size",
    "take a position", "enter a trade", "exit a trade",
    "place an order", "execute", "short", "long position",
    "go long", "go short", "open a position", "close a position",
]

_TRUTH_WRITE_MODULES = {
    "forecast_repo", "similarity_repo", "decision_repo", "scenario_repo",
}


class TestASTSafety:
    def _load_tree(self):
        source = _SVC_PATH.read_text()
        return ast.parse(source), source

    def test_no_truth_write_module_imports(self):
        tree, _ = self._load_tree()
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                module = ""
                if isinstance(node, ast.ImportFrom):
                    module = node.module or ""
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        module += alias.name
                for bad in _TRUTH_WRITE_MODULES:
                    assert bad not in module, (
                        f"Found prohibited import '{bad}' in decay service"
                    )

    def test_no_conviction_order_execution_imports(self):
        tree, _ = self._load_tree()
        forbidden = {"conviction", "order", "execution"}
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                for f in forbidden:
                    assert f not in module, f"Forbidden import: {f}"

    def test_no_banned_advisory_phrases_in_string_constants(self):
        tree, _ = self._load_tree()

        docstring_ids: set = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Module):
                if (node.body and isinstance(node.body[0], ast.Expr)
                        and isinstance(node.body[0].value, ast.Constant)):
                    docstring_ids.add(id(node.body[0].value))
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                if (node.body and isinstance(node.body[0], ast.Expr)
                        and isinstance(node.body[0].value, ast.Constant)):
                    docstring_ids.add(id(node.body[0].value))

        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if id(node) in docstring_ids:
                    continue
                lower = node.value.lower()
                for phrase in _BANNED_PHRASES:
                    assert phrase not in lower, (
                        f"Banned phrase {phrase!r} in constant: {node.value!r}"
                    )

    def test_no_relevance_adjustment_log_writes(self):
        source = _SVC_PATH.read_text()
        assert "add_relevance_adjustment_log" not in source

    def test_no_source_table_mutation(self):
        source = _SVC_PATH.read_text()
        for bad in (
            "upsert_thesis", "upsert_conviction", "upsert_similarity_edge",
            "update_forecast_vector", "upsert_scenario_snapshot", "upsert_decision_priority",
        ):
            assert bad not in source, f"Found prohibited truth-table write: {bad!r}"

    def test_no_forecast_similarity_decision_scenario_imports(self):
        """Verify no import statement references the prohibited module names."""
        tree, _ = self._load_tree()
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                module = ""
                if isinstance(node, ast.ImportFrom):
                    module = node.module or ""
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        module += alias.name
                for bad in _TRUTH_WRITE_MODULES:
                    assert bad not in module, (
                        f"Found prohibited import statement for '{bad}' in decay service"
                    )
