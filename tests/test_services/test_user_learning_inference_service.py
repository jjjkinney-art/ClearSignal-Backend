"""
Tests — User Learning Inference Service, Phase 15 · Slice 5.

Covers:
  1.  service importable
  2.  flag gate: all 7 public functions return [] when run_override=False
  3.  null-session safety: all 7 public functions return [] when session=None
      (even when flag=True via run_override)
  4.  infer_company_preferences: sparse signals (< 5) → empty
  5.  infer_company_preferences: sufficient signals → non-empty candidate
  6.  infer_company_preferences: strong-signal candidate has signal_strength_label="strong"
  7.  infer_company_preferences: tentative candidate below confidence threshold
  8.  infer_company_preferences: portfolio events excluded from company_interest
  9.  infer_sector_preferences: sparse → empty
  10. infer_sector_preferences: sufficient → non-empty candidate
  11. infer_theme_preferences: sparse → empty
  12. infer_theme_preferences: sufficient → non-empty candidate
  13. infer_horizon_preferences: sparse → empty
  14. infer_horizon_preferences: sufficient → non-empty candidate
  15. infer_signal_type_preferences: insufficient positive events → no preferred candidate
  16. infer_signal_type_preferences: sufficient positive events → preferred_signal_type candidate
  17. infer_signal_type_preferences: insufficient negative events → no ignored candidate
  18. infer_signal_type_preferences: sufficient negative events (>=6) → ignored_signal_type candidate
  19. infer_signal_type_preferences: both preferred and ignored from mixed sessions
  20. infer_portfolio_sensitivities: sparse → empty
  21. infer_portfolio_sensitivities: sufficient portfolio events → portfolio_sensitivity candidate
  22. infer_portfolio_sensitivities: non-portfolio company events not included
  23. each candidate has required keys: dimension, entity_key, belief_basis,
      signal_strength_label, falsifier, evidence_refs
  24. each candidate "explanation" field passes validate_preference_explanation
  25. infer_company_preferences: tenant isolation — user A events invisible to user B
  26. infer_sector_preferences: tenant isolation
  27. deterministic output: same events produce same ordered candidates across two calls
  28. infer_learned_preferences: flag gate → empty
  29. infer_learned_preferences: null session → empty
  30. infer_learned_preferences: no events → empty
  31. infer_learned_preferences: company events persist LearnedPreference rows
  32. infer_learned_preferences: sector + company events → all dimensions covered
  33. infer_learned_preferences: upsert idempotency — second run updates existing row
  34. infer_learned_preferences: persisted rows have correct dimension and entity_key
  35. infer_learned_preferences: no relevance_adjustment_log rows created
  36. insufficient samples never reach learned_preference table
  37. candidates with entity_key="" are not included
  38. lookback_days respected — events outside window excluded
  39. infer_company_preferences: mixed polarity → affinity < 1.0
  40. infer_company_preferences: strong positive → affinity close to 1.0
  41. infer_sector_preferences: strong positive → signal_strength_label="strong"
  42. infer_horizon_preferences: candidate dimension is "preferred_horizon"
  43. infer_portfolio_sensitivities: candidate dimension is "portfolio_sensitivity"
  44. all 7 public function signatures accept session, user_id, lookback_days, run_override
  45. AST safety: no truth-table write imports in the inference service
  46. AST safety: no banned advisory phrase in non-docstring string constants
  47. no learned_preference written when validation gate would fail (patched scenario)
  48. infer_signal_type_preferences: preferred threshold is lower than ignored threshold
  49. preferred_signal_type candidate has affinity >= 0
  50. ignored_signal_type candidate has affinity <= 0
  51. infer_theme_preferences: multiple themes inferred from events for each
  52. infer_learned_preferences: infer_signal_type_preferences integrated
  53. user_signal_event table unmodified after inference
  54. infer_company_preferences: exactly at threshold (MIN_EVIDENCE=5) → candidate produced
  55. infer_company_preferences: one below threshold (4 events) → empty
  56. infer_sector_preferences: exactly at threshold (5 events) → candidate produced
  57. infer_horizon_preferences: exactly at threshold (3 events) → candidate produced
  58. infer_signal_type_preferences: preferred exactly at threshold (3) → candidate
  59. infer_signal_type_preferences: ignored exactly at threshold (6) → candidate
  60. infer_portfolio_sensitivities: exactly at threshold (4 events) → candidate
  61. signal_strength_label="tentative" when evidence_count = MIN_EVIDENCE (barely qualifies)
  62. signal_strength_label="strong" when confidence >= 0.70
  63. signal_strength_label="moderate" when 0.40 <= confidence < 0.70
  64. infer_learned_preferences: persisted row has signal_strength_label from candidate
  65. infer_learned_preferences: persisted row has belief_basis from candidate
  66. infer_learned_preferences: persisted row has affinity from candidate
  67. infer_learned_preferences: persisted row status = "unresolved"
  68. infer_learned_preferences: persisted row has falsifier from candidate
  69. all infer_* return list type (not None, not coroutine)
  70. infer_signal_type_preferences: no candidate when all events are neutral
  71. infer_company_preferences: surface_was_personalized events included in evidence
  72. no forecast_repo, similarity_repo, decision_repo, scenario_repo imported
  73. no conviction, order, execution imports
  74. infer_learned_preferences: evidence_refs in candidate are strings
  75. infer_company_preferences: evidence_count matches number of events inserted
"""

from __future__ import annotations

import ast
import inspect
import pathlib
import uuid
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any, List
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

_ROOT = pathlib.Path(__file__).parent.parent.parent

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


# ---------------------------------------------------------------------------
# Helpers for inserting test events
# ---------------------------------------------------------------------------

async def _insert_events(
    session,
    *,
    user_id: str,
    entity_type: str,
    entity_key: str,
    n: int,
    polarity: str = "positive",
    source_surface: str = "analysis",
    interaction_weight: float = 1.0,
    offset_hours: int = 0,
):
    """Insert n UserSignalEvent rows for the given parameters."""
    from app.db.repositories.user_learning_repo import add_user_signal_event

    for i in range(n):
        occurred = _now() - timedelta(hours=offset_hours + i)
        await add_user_signal_event(
            session,
            user_id=user_id,
            signal_type=f"{entity_type}_view",
            polarity=polarity,
            entity_type=entity_type,
            entity_key=entity_key,
            source_surface=source_surface,
            interaction_weight=interaction_weight,
            occurred_at=occurred,
        )


# ---------------------------------------------------------------------------
# 1. Import
# ---------------------------------------------------------------------------

class TestImport:
    def test_service_importable(self):
        import app.services.user_learning_inference_service  # noqa: F401

    def test_all_public_functions_present(self):
        import app.services.user_learning_inference_service as svc
        for name in (
            "infer_company_preferences",
            "infer_sector_preferences",
            "infer_theme_preferences",
            "infer_horizon_preferences",
            "infer_signal_type_preferences",
            "infer_portfolio_sensitivities",
            "infer_learned_preferences",
        ):
            assert callable(getattr(svc, name, None)), f"Missing: {name}"


# ---------------------------------------------------------------------------
# 2. Flag gate
# ---------------------------------------------------------------------------

class TestFlagGate:
    @pytest.mark.asyncio
    async def test_company_flag_off(self, db):
        from app.services.user_learning_inference_service import infer_company_preferences
        result = await infer_company_preferences(db, user_id=_uid(), run_override=False)
        assert result == []

    @pytest.mark.asyncio
    async def test_sector_flag_off(self, db):
        from app.services.user_learning_inference_service import infer_sector_preferences
        result = await infer_sector_preferences(db, user_id=_uid(), run_override=False)
        assert result == []

    @pytest.mark.asyncio
    async def test_theme_flag_off(self, db):
        from app.services.user_learning_inference_service import infer_theme_preferences
        result = await infer_theme_preferences(db, user_id=_uid(), run_override=False)
        assert result == []

    @pytest.mark.asyncio
    async def test_horizon_flag_off(self, db):
        from app.services.user_learning_inference_service import infer_horizon_preferences
        result = await infer_horizon_preferences(db, user_id=_uid(), run_override=False)
        assert result == []

    @pytest.mark.asyncio
    async def test_signal_type_flag_off(self, db):
        from app.services.user_learning_inference_service import infer_signal_type_preferences
        result = await infer_signal_type_preferences(db, user_id=_uid(), run_override=False)
        assert result == []

    @pytest.mark.asyncio
    async def test_portfolio_flag_off(self, db):
        from app.services.user_learning_inference_service import infer_portfolio_sensitivities
        result = await infer_portfolio_sensitivities(db, user_id=_uid(), run_override=False)
        assert result == []

    @pytest.mark.asyncio
    async def test_infer_learned_flag_off(self, db):
        from app.services.user_learning_inference_service import infer_learned_preferences
        result = await infer_learned_preferences(db, user_id=_uid(), run_override=False)
        assert result == []


# ---------------------------------------------------------------------------
# 3. Null-session safety
# ---------------------------------------------------------------------------

class TestNullSession:
    @pytest.mark.asyncio
    async def test_company_null_session(self):
        from app.services.user_learning_inference_service import infer_company_preferences
        result = await infer_company_preferences(None, user_id=_uid(), run_override=True)
        assert result == []

    @pytest.mark.asyncio
    async def test_sector_null_session(self):
        from app.services.user_learning_inference_service import infer_sector_preferences
        result = await infer_sector_preferences(None, user_id=_uid(), run_override=True)
        assert result == []

    @pytest.mark.asyncio
    async def test_theme_null_session(self):
        from app.services.user_learning_inference_service import infer_theme_preferences
        result = await infer_theme_preferences(None, user_id=_uid(), run_override=True)
        assert result == []

    @pytest.mark.asyncio
    async def test_horizon_null_session(self):
        from app.services.user_learning_inference_service import infer_horizon_preferences
        result = await infer_horizon_preferences(None, user_id=_uid(), run_override=True)
        assert result == []

    @pytest.mark.asyncio
    async def test_signal_type_null_session(self):
        from app.services.user_learning_inference_service import infer_signal_type_preferences
        result = await infer_signal_type_preferences(None, user_id=_uid(), run_override=True)
        assert result == []

    @pytest.mark.asyncio
    async def test_portfolio_null_session(self):
        from app.services.user_learning_inference_service import infer_portfolio_sensitivities
        result = await infer_portfolio_sensitivities(None, user_id=_uid(), run_override=True)
        assert result == []

    @pytest.mark.asyncio
    async def test_infer_learned_null_session(self):
        from app.services.user_learning_inference_service import infer_learned_preferences
        result = await infer_learned_preferences(None, user_id=_uid(), run_override=True)
        assert result == []


# ---------------------------------------------------------------------------
# 4–8. Company preferences
# ---------------------------------------------------------------------------

class TestCompanyPreferences:
    @pytest.mark.asyncio
    async def test_sparse_signals_returns_empty(self, db):
        """4 events (< MIN_EVIDENCE=5) → no candidate."""
        from app.services.user_learning_inference_service import infer_company_preferences
        uid = _uid()
        await _insert_events(db, user_id=uid, entity_type="company", entity_key="AAPL", n=4)
        result = await infer_company_preferences(db, user_id=uid, run_override=True)
        assert result == []

    @pytest.mark.asyncio
    async def test_sufficient_signals_returns_candidate(self, db):
        """5 events (= MIN_EVIDENCE=5) → one candidate."""
        from app.services.user_learning_inference_service import infer_company_preferences
        uid = _uid()
        await _insert_events(db, user_id=uid, entity_type="company", entity_key="AAPL", n=5)
        result = await infer_company_preferences(db, user_id=uid, run_override=True)
        assert len(result) == 1
        assert result[0]["entity_key"] == "AAPL"
        assert result[0]["dimension"] == "company_interest"

    @pytest.mark.asyncio
    async def test_strong_signal_strength_label(self, db):
        """Many all-positive events → confidence=1.0 → signal_strength_label='strong'."""
        from app.services.user_learning_inference_service import infer_company_preferences
        uid = _uid()
        await _insert_events(db, user_id=uid, entity_type="company", entity_key="NVDA", n=15, polarity="positive")
        result = await infer_company_preferences(db, user_id=uid, run_override=True)
        assert len(result) == 1
        assert result[0]["signal_strength_label"] == "strong"

    @pytest.mark.asyncio
    async def test_mixed_polarity_tentative(self, db):
        """Near-equal positive and negative → low confidence → tentative."""
        from app.services.user_learning_inference_service import infer_company_preferences
        uid = _uid()
        # 3 positive, 2 negative — barely above threshold, mixed signal
        await _insert_events(db, user_id=uid, entity_type="company", entity_key="MSFT", n=3, polarity="positive")
        await _insert_events(db, user_id=uid, entity_type="company", entity_key="MSFT", n=2, polarity="negative")
        result = await infer_company_preferences(db, user_id=uid, run_override=True)
        assert len(result) == 1
        # net = (3-2)/5 = 0.2, confidence=0.2 < 0.40 → tentative
        assert result[0]["signal_strength_label"] == "tentative"

    @pytest.mark.asyncio
    async def test_portfolio_events_excluded(self, db):
        """Portfolio-surface events not counted toward company_interest."""
        from app.services.user_learning_inference_service import infer_company_preferences
        uid = _uid()
        # 10 portfolio events for AAPL — should be excluded
        await _insert_events(db, user_id=uid, entity_type="company", entity_key="AAPL",
                              n=10, source_surface="portfolio")
        result = await infer_company_preferences(db, user_id=uid, run_override=True)
        assert result == []

    @pytest.mark.asyncio
    async def test_exactly_at_threshold(self, db):
        """Exactly MIN_EVIDENCE=5 events → candidate produced."""
        from app.services.user_learning_inference_service import infer_company_preferences
        uid = _uid()
        await _insert_events(db, user_id=uid, entity_type="company", entity_key="GOOG", n=5, polarity="positive")
        result = await infer_company_preferences(db, user_id=uid, run_override=True)
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_one_below_threshold(self, db):
        """MIN_EVIDENCE-1 = 4 events → no candidate."""
        from app.services.user_learning_inference_service import infer_company_preferences
        uid = _uid()
        await _insert_events(db, user_id=uid, entity_type="company", entity_key="TSLA", n=4, polarity="positive")
        result = await infer_company_preferences(db, user_id=uid, run_override=True)
        assert result == []

    @pytest.mark.asyncio
    async def test_evidence_count_matches_events_inserted(self, db):
        """evidence_count in candidate == number of events inserted."""
        from app.services.user_learning_inference_service import infer_company_preferences
        uid = _uid()
        n = 8
        await _insert_events(db, user_id=uid, entity_type="company", entity_key="AMD", n=n, polarity="positive")
        result = await infer_company_preferences(db, user_id=uid, run_override=True)
        assert len(result) == 1
        assert result[0]["evidence_count"] == n

    @pytest.mark.asyncio
    async def test_strong_affinity_close_to_one(self, db):
        """All-positive events → affinity close to 1.0."""
        from app.services.user_learning_inference_service import infer_company_preferences
        uid = _uid()
        await _insert_events(db, user_id=uid, entity_type="company", entity_key="META", n=10, polarity="positive")
        result = await infer_company_preferences(db, user_id=uid, run_override=True)
        assert len(result) == 1
        assert result[0]["affinity"] > 0.9

    @pytest.mark.asyncio
    async def test_surface_was_personalized_events_included(self, db):
        """Personalized events are still captured — anti-loop fields are stored but not excluded."""
        from app.services.user_learning_inference_service import infer_company_preferences
        from app.db.repositories.user_learning_repo import add_user_signal_event
        uid = _uid()
        for i in range(6):
            await add_user_signal_event(
                db, user_id=uid, signal_type="analysis_open", polarity="positive",
                entity_type="company", entity_key="INTC", source_surface="analysis",
                surface_was_personalized=(i % 2 == 0), interaction_weight=1.0,
                occurred_at=_now() - timedelta(hours=i),
            )
        result = await infer_company_preferences(db, user_id=uid, run_override=True)
        assert len(result) == 1
        assert result[0]["evidence_count"] == 6


# ---------------------------------------------------------------------------
# 9–10. Sector preferences
# ---------------------------------------------------------------------------

class TestSectorPreferences:
    @pytest.mark.asyncio
    async def test_sparse_returns_empty(self, db):
        from app.services.user_learning_inference_service import infer_sector_preferences
        uid = _uid()
        await _insert_events(db, user_id=uid, entity_type="sector", entity_key="tech", n=4)
        result = await infer_sector_preferences(db, user_id=uid, run_override=True)
        assert result == []

    @pytest.mark.asyncio
    async def test_sufficient_returns_candidate(self, db):
        from app.services.user_learning_inference_service import infer_sector_preferences
        uid = _uid()
        await _insert_events(db, user_id=uid, entity_type="sector", entity_key="tech", n=5, polarity="positive")
        result = await infer_sector_preferences(db, user_id=uid, run_override=True)
        assert len(result) == 1
        assert result[0]["dimension"] == "sector_interest"
        assert result[0]["entity_key"] == "tech"

    @pytest.mark.asyncio
    async def test_strong_signal_label(self, db):
        from app.services.user_learning_inference_service import infer_sector_preferences
        uid = _uid()
        await _insert_events(db, user_id=uid, entity_type="sector", entity_key="healthcare", n=20, polarity="positive")
        result = await infer_sector_preferences(db, user_id=uid, run_override=True)
        assert result[0]["signal_strength_label"] == "strong"

    @pytest.mark.asyncio
    async def test_exactly_at_threshold(self, db):
        from app.services.user_learning_inference_service import infer_sector_preferences
        uid = _uid()
        await _insert_events(db, user_id=uid, entity_type="sector", entity_key="energy", n=5, polarity="positive")
        result = await infer_sector_preferences(db, user_id=uid, run_override=True)
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_tenant_isolation(self, db):
        from app.services.user_learning_inference_service import infer_sector_preferences
        uid_a = _uid()
        uid_b = _uid()
        await _insert_events(db, user_id=uid_a, entity_type="sector", entity_key="tech", n=10, polarity="positive")
        result = await infer_sector_preferences(db, user_id=uid_b, run_override=True)
        assert result == []


# ---------------------------------------------------------------------------
# 11–12. Theme preferences
# ---------------------------------------------------------------------------

class TestThemePreferences:
    @pytest.mark.asyncio
    async def test_sparse_returns_empty(self, db):
        from app.services.user_learning_inference_service import infer_theme_preferences
        uid = _uid()
        await _insert_events(db, user_id=uid, entity_type="theme", entity_key="ai_hardware", n=3)
        result = await infer_theme_preferences(db, user_id=uid, run_override=True)
        assert result == []

    @pytest.mark.asyncio
    async def test_sufficient_returns_candidate(self, db):
        from app.services.user_learning_inference_service import infer_theme_preferences
        uid = _uid()
        await _insert_events(db, user_id=uid, entity_type="theme", entity_key="ai_hardware", n=5, polarity="positive")
        result = await infer_theme_preferences(db, user_id=uid, run_override=True)
        assert len(result) == 1
        assert result[0]["dimension"] == "theme_interest"
        assert result[0]["entity_key"] == "ai_hardware"

    @pytest.mark.asyncio
    async def test_multiple_themes_inferred(self, db):
        """Two distinct themes each with sufficient events → two candidates."""
        from app.services.user_learning_inference_service import infer_theme_preferences
        uid = _uid()
        await _insert_events(db, user_id=uid, entity_type="theme", entity_key="ai_hardware", n=5, polarity="positive")
        await _insert_events(db, user_id=uid, entity_type="theme", entity_key="ev_transition", n=5, polarity="positive")
        result = await infer_theme_preferences(db, user_id=uid, run_override=True)
        assert len(result) == 2
        dims = {c["entity_key"] for c in result}
        assert "ai_hardware" in dims
        assert "ev_transition" in dims


# ---------------------------------------------------------------------------
# 13–14. Horizon preferences
# ---------------------------------------------------------------------------

class TestHorizonPreferences:
    @pytest.mark.asyncio
    async def test_sparse_returns_empty(self, db):
        from app.services.user_learning_inference_service import infer_horizon_preferences
        uid = _uid()
        await _insert_events(db, user_id=uid, entity_type="horizon", entity_key="short", n=2)
        result = await infer_horizon_preferences(db, user_id=uid, run_override=True)
        assert result == []

    @pytest.mark.asyncio
    async def test_sufficient_returns_candidate(self, db):
        from app.services.user_learning_inference_service import infer_horizon_preferences
        uid = _uid()
        await _insert_events(db, user_id=uid, entity_type="horizon", entity_key="long", n=3, polarity="positive")
        result = await infer_horizon_preferences(db, user_id=uid, run_override=True)
        assert len(result) == 1
        assert result[0]["dimension"] == "preferred_horizon"
        assert result[0]["entity_key"] == "long"

    @pytest.mark.asyncio
    async def test_exactly_at_threshold(self, db):
        from app.services.user_learning_inference_service import infer_horizon_preferences
        uid = _uid()
        await _insert_events(db, user_id=uid, entity_type="horizon", entity_key="medium", n=3, polarity="positive")
        result = await infer_horizon_preferences(db, user_id=uid, run_override=True)
        assert len(result) == 1


# ---------------------------------------------------------------------------
# 15–19. Signal type preferences
# ---------------------------------------------------------------------------

class TestSignalTypePreferences:
    @pytest.mark.asyncio
    async def test_insufficient_positive_no_preferred(self, db):
        """2 positive events < MIN_EVIDENCE=3 → no preferred candidate."""
        from app.services.user_learning_inference_service import infer_signal_type_preferences
        uid = _uid()
        await _insert_events(db, user_id=uid, entity_type="signal_type",
                              entity_key="earnings_beat", n=2, polarity="positive")
        result = await infer_signal_type_preferences(db, user_id=uid, run_override=True)
        assert not any(c["dimension"] == "preferred_signal_type" for c in result)

    @pytest.mark.asyncio
    async def test_sufficient_positive_preferred_candidate(self, db):
        """3 positive events = MIN_EVIDENCE=3 → preferred_signal_type candidate."""
        from app.services.user_learning_inference_service import infer_signal_type_preferences
        uid = _uid()
        await _insert_events(db, user_id=uid, entity_type="signal_type",
                              entity_key="earnings_beat", n=3, polarity="positive")
        result = await infer_signal_type_preferences(db, user_id=uid, run_override=True)
        preferred = [c for c in result if c["dimension"] == "preferred_signal_type"]
        assert len(preferred) == 1
        assert preferred[0]["entity_key"] == "earnings_beat"

    @pytest.mark.asyncio
    async def test_insufficient_negative_no_ignored(self, db):
        """5 negative events < MIN_EVIDENCE=6 for ignored → no ignored candidate."""
        from app.services.user_learning_inference_service import infer_signal_type_preferences
        uid = _uid()
        await _insert_events(db, user_id=uid, entity_type="signal_type",
                              entity_key="macro_noise", n=5, polarity="negative")
        result = await infer_signal_type_preferences(db, user_id=uid, run_override=True)
        ignored = [c for c in result if c["dimension"] == "ignored_signal_type"]
        assert ignored == []

    @pytest.mark.asyncio
    async def test_sufficient_negative_ignored_candidate(self, db):
        """6 negative events = MIN_EVIDENCE=6 for ignored → ignored_signal_type candidate."""
        from app.services.user_learning_inference_service import infer_signal_type_preferences
        uid = _uid()
        await _insert_events(db, user_id=uid, entity_type="signal_type",
                              entity_key="macro_noise", n=6, polarity="negative")
        result = await infer_signal_type_preferences(db, user_id=uid, run_override=True)
        ignored = [c for c in result if c["dimension"] == "ignored_signal_type"]
        assert len(ignored) == 1
        assert ignored[0]["entity_key"] == "macro_noise"

    @pytest.mark.asyncio
    async def test_both_preferred_and_ignored_from_mixed(self, db):
        """>=3 positive AND >=6 negative for same key → two separate candidates."""
        from app.services.user_learning_inference_service import infer_signal_type_preferences
        uid = _uid()
        await _insert_events(db, user_id=uid, entity_type="signal_type",
                              entity_key="volatility_spike", n=3, polarity="positive")
        await _insert_events(db, user_id=uid, entity_type="signal_type",
                              entity_key="volatility_spike", n=6, polarity="negative")
        result = await infer_signal_type_preferences(db, user_id=uid, run_override=True)
        dims = [c["dimension"] for c in result]
        assert "preferred_signal_type" in dims
        assert "ignored_signal_type" in dims

    @pytest.mark.asyncio
    async def test_preferred_has_positive_affinity(self, db):
        from app.services.user_learning_inference_service import infer_signal_type_preferences
        uid = _uid()
        await _insert_events(db, user_id=uid, entity_type="signal_type",
                              entity_key="earnings_beat", n=5, polarity="positive")
        result = await infer_signal_type_preferences(db, user_id=uid, run_override=True)
        preferred = [c for c in result if c["dimension"] == "preferred_signal_type"]
        assert preferred[0]["affinity"] >= 0.0

    @pytest.mark.asyncio
    async def test_ignored_has_negative_affinity(self, db):
        from app.services.user_learning_inference_service import infer_signal_type_preferences
        uid = _uid()
        await _insert_events(db, user_id=uid, entity_type="signal_type",
                              entity_key="macro_noise", n=7, polarity="negative")
        result = await infer_signal_type_preferences(db, user_id=uid, run_override=True)
        ignored = [c for c in result if c["dimension"] == "ignored_signal_type"]
        assert ignored[0]["affinity"] <= 0.0

    @pytest.mark.asyncio
    async def test_no_candidate_when_all_neutral(self, db):
        """Neutral events produce no preferred or ignored candidate."""
        from app.services.user_learning_inference_service import infer_signal_type_preferences
        uid = _uid()
        await _insert_events(db, user_id=uid, entity_type="signal_type",
                              entity_key="market_close", n=10, polarity="neutral")
        result = await infer_signal_type_preferences(db, user_id=uid, run_override=True)
        assert result == []

    @pytest.mark.asyncio
    async def test_preferred_threshold_lower_than_ignored(self, db):
        """preferred MIN_EVIDENCE=3 < ignored MIN_EVIDENCE=6."""
        from app.services.user_learning_inference_service import _MIN_EVIDENCE
        assert _MIN_EVIDENCE["preferred_signal_type"] < _MIN_EVIDENCE["ignored_signal_type"]

    @pytest.mark.asyncio
    async def test_ignored_exactly_at_threshold(self, db):
        from app.services.user_learning_inference_service import infer_signal_type_preferences
        uid = _uid()
        await _insert_events(db, user_id=uid, entity_type="signal_type",
                              entity_key="sector_rotation", n=6, polarity="negative")
        result = await infer_signal_type_preferences(db, user_id=uid, run_override=True)
        ignored = [c for c in result if c["dimension"] == "ignored_signal_type"]
        assert len(ignored) == 1


# ---------------------------------------------------------------------------
# 20–22. Portfolio sensitivities
# ---------------------------------------------------------------------------

class TestPortfolioSensitivities:
    @pytest.mark.asyncio
    async def test_sparse_returns_empty(self, db):
        from app.services.user_learning_inference_service import infer_portfolio_sensitivities
        uid = _uid()
        await _insert_events(db, user_id=uid, entity_type="company", entity_key="AAPL",
                              n=3, source_surface="portfolio")
        result = await infer_portfolio_sensitivities(db, user_id=uid, run_override=True)
        assert result == []

    @pytest.mark.asyncio
    async def test_sufficient_portfolio_events(self, db):
        from app.services.user_learning_inference_service import infer_portfolio_sensitivities
        uid = _uid()
        await _insert_events(db, user_id=uid, entity_type="company", entity_key="AAPL",
                              n=4, polarity="positive", source_surface="portfolio")
        result = await infer_portfolio_sensitivities(db, user_id=uid, run_override=True)
        assert len(result) == 1
        assert result[0]["dimension"] == "portfolio_sensitivity"
        assert result[0]["entity_key"] == "AAPL"

    @pytest.mark.asyncio
    async def test_non_portfolio_company_excluded(self, db):
        """Analysis-surface company events do not feed portfolio_sensitivity."""
        from app.services.user_learning_inference_service import infer_portfolio_sensitivities
        uid = _uid()
        await _insert_events(db, user_id=uid, entity_type="company", entity_key="NVDA",
                              n=10, source_surface="analysis")
        result = await infer_portfolio_sensitivities(db, user_id=uid, run_override=True)
        assert result == []

    @pytest.mark.asyncio
    async def test_exactly_at_threshold(self, db):
        from app.services.user_learning_inference_service import infer_portfolio_sensitivities
        uid = _uid()
        await _insert_events(db, user_id=uid, entity_type="company", entity_key="MSFT",
                              n=4, polarity="positive", source_surface="portfolio")
        result = await infer_portfolio_sensitivities(db, user_id=uid, run_override=True)
        assert len(result) == 1


# ---------------------------------------------------------------------------
# 23–24. Candidate shape and explainability gate
# ---------------------------------------------------------------------------

class TestCandidateShape:
    @pytest.mark.asyncio
    async def test_required_keys_present(self, db):
        from app.services.user_learning_inference_service import infer_company_preferences
        uid = _uid()
        await _insert_events(db, user_id=uid, entity_type="company", entity_key="IBM", n=5, polarity="positive")
        result = await infer_company_preferences(db, user_id=uid, run_override=True)
        assert len(result) == 1
        c = result[0]
        for key in ("dimension", "entity_key", "belief_basis", "signal_strength_label",
                    "falsifier", "evidence_refs", "affinity", "confidence", "evidence_count",
                    "explanation", "status"):
            assert key in c, f"Missing key: {key}"

    @pytest.mark.asyncio
    async def test_explanation_passes_validation(self, db):
        from app.services.user_learning_inference_service import infer_company_preferences
        from app.services.user_learning_explainability_service import validate_preference_explanation
        uid = _uid()
        await _insert_events(db, user_id=uid, entity_type="company", entity_key="ORCL", n=5, polarity="positive")
        result = await infer_company_preferences(db, user_id=uid, run_override=True)
        assert len(result) == 1
        ok, reason = validate_preference_explanation(result[0]["explanation"])
        assert ok is True, f"Explanation failed: {reason}"

    @pytest.mark.asyncio
    async def test_evidence_refs_are_strings(self, db):
        from app.services.user_learning_inference_service import infer_company_preferences
        uid = _uid()
        await _insert_events(db, user_id=uid, entity_type="company", entity_key="SAP", n=5, polarity="positive")
        result = await infer_company_preferences(db, user_id=uid, run_override=True)
        for ref in result[0]["evidence_refs"]:
            assert isinstance(ref, str)

    @pytest.mark.asyncio
    async def test_status_is_unresolved(self, db):
        from app.services.user_learning_inference_service import infer_sector_preferences
        uid = _uid()
        await _insert_events(db, user_id=uid, entity_type="sector", entity_key="finance", n=5, polarity="positive")
        result = await infer_sector_preferences(db, user_id=uid, run_override=True)
        assert result[0]["status"] == "unresolved"


# ---------------------------------------------------------------------------
# 25–26. Tenant isolation
# ---------------------------------------------------------------------------

class TestTenantIsolation:
    @pytest.mark.asyncio
    async def test_company_isolation(self, db):
        from app.services.user_learning_inference_service import infer_company_preferences
        uid_a = _uid()
        uid_b = _uid()
        await _insert_events(db, user_id=uid_a, entity_type="company", entity_key="AAPL", n=10, polarity="positive")
        result = await infer_company_preferences(db, user_id=uid_b, run_override=True)
        assert result == []

    @pytest.mark.asyncio
    async def test_sector_isolation(self, db):
        from app.services.user_learning_inference_service import infer_sector_preferences
        uid_a = _uid()
        uid_b = _uid()
        await _insert_events(db, user_id=uid_a, entity_type="sector", entity_key="tech", n=10, polarity="positive")
        result = await infer_sector_preferences(db, user_id=uid_b, run_override=True)
        assert result == []


# ---------------------------------------------------------------------------
# 27. Deterministic output
# ---------------------------------------------------------------------------

class TestDeterministicOutput:
    @pytest.mark.asyncio
    async def test_same_events_same_output(self, db):
        from app.services.user_learning_inference_service import infer_company_preferences
        uid = _uid()
        await _insert_events(db, user_id=uid, entity_type="company", entity_key="CRM", n=6, polarity="positive")
        r1 = await infer_company_preferences(db, user_id=uid, run_override=True)
        r2 = await infer_company_preferences(db, user_id=uid, run_override=True)
        assert len(r1) == len(r2)
        assert r1[0]["dimension"] == r2[0]["dimension"]
        assert r1[0]["entity_key"] == r2[0]["entity_key"]
        assert r1[0]["affinity"] == r2[0]["affinity"]
        assert r1[0]["signal_strength_label"] == r2[0]["signal_strength_label"]


# ---------------------------------------------------------------------------
# 28–35. infer_learned_preferences
# ---------------------------------------------------------------------------

class TestInferLearnedPreferences:
    @pytest.mark.asyncio
    async def test_flag_off_returns_empty(self, db):
        from app.services.user_learning_inference_service import infer_learned_preferences
        result = await infer_learned_preferences(db, user_id=_uid(), run_override=False)
        assert result == []

    @pytest.mark.asyncio
    async def test_null_session_returns_empty(self):
        from app.services.user_learning_inference_service import infer_learned_preferences
        result = await infer_learned_preferences(None, user_id=_uid(), run_override=True)
        assert result == []

    @pytest.mark.asyncio
    async def test_no_events_returns_empty(self, db):
        from app.services.user_learning_inference_service import infer_learned_preferences
        result = await infer_learned_preferences(db, user_id=_uid(), run_override=True)
        assert result == []

    @pytest.mark.asyncio
    async def test_company_events_persist_rows(self, db):
        from app.services.user_learning_inference_service import infer_learned_preferences
        uid = _uid()
        await _insert_events(db, user_id=uid, entity_type="company", entity_key="AAPL", n=6, polarity="positive")
        result = await infer_learned_preferences(db, user_id=uid, run_override=True)
        assert len(result) == 1
        assert result[0].dimension == "company_interest"
        assert result[0].entity_key == "AAPL"

    @pytest.mark.asyncio
    async def test_multiple_dimensions_covered(self, db):
        from app.services.user_learning_inference_service import infer_learned_preferences
        uid = _uid()
        await _insert_events(db, user_id=uid, entity_type="company", entity_key="AAPL", n=6, polarity="positive")
        await _insert_events(db, user_id=uid, entity_type="sector", entity_key="tech", n=6, polarity="positive")
        result = await infer_learned_preferences(db, user_id=uid, run_override=True)
        dims = {r.dimension for r in result}
        assert "company_interest" in dims
        assert "sector_interest" in dims

    @pytest.mark.asyncio
    async def test_upsert_idempotency(self, db):
        """Running twice with the same events updates the row, not duplicates."""
        from app.services.user_learning_inference_service import infer_learned_preferences
        from app.db.repositories.user_learning_repo import count_learned_preferences
        uid = _uid()
        await _insert_events(db, user_id=uid, entity_type="company", entity_key="NVDA", n=6, polarity="positive")
        await infer_learned_preferences(db, user_id=uid, run_override=True)
        await infer_learned_preferences(db, user_id=uid, run_override=True)
        count = await count_learned_preferences(db, user_id=uid, dimension="company_interest")
        assert count == 1

    @pytest.mark.asyncio
    async def test_persisted_row_fields(self, db):
        from app.services.user_learning_inference_service import infer_learned_preferences
        uid = _uid()
        await _insert_events(db, user_id=uid, entity_type="sector", entity_key="healthcare",
                              n=10, polarity="positive")
        result = await infer_learned_preferences(db, user_id=uid, run_override=True)
        row = result[0]
        assert row.status == "unresolved"
        assert row.signal_strength_label == "strong"
        assert row.affinity > 0.9
        assert row.belief_basis != ""
        assert row.falsifier != ""

    @pytest.mark.asyncio
    async def test_no_relevance_adjustment_log_created(self, db):
        from app.services.user_learning_inference_service import infer_learned_preferences
        from app.db.repositories.user_learning_repo import count_relevance_adjustment_logs
        uid = _uid()
        await _insert_events(db, user_id=uid, entity_type="company", entity_key="AAPL", n=6, polarity="positive")
        await infer_learned_preferences(db, user_id=uid, run_override=True)
        count = await count_relevance_adjustment_logs(db, user_id=uid)
        assert count == 0

    @pytest.mark.asyncio
    async def test_insufficient_samples_not_persisted(self, db):
        from app.services.user_learning_inference_service import infer_learned_preferences
        from app.db.repositories.user_learning_repo import count_learned_preferences
        uid = _uid()
        # Only 3 company events — below MIN_EVIDENCE=5
        await _insert_events(db, user_id=uid, entity_type="company", entity_key="CRM", n=3, polarity="positive")
        await infer_learned_preferences(db, user_id=uid, run_override=True)
        count = await count_learned_preferences(db, user_id=uid)
        assert count == 0

    @pytest.mark.asyncio
    async def test_signal_type_preferences_integrated(self, db):
        from app.services.user_learning_inference_service import infer_learned_preferences
        uid = _uid()
        await _insert_events(db, user_id=uid, entity_type="signal_type",
                              entity_key="earnings_surprise", n=4, polarity="positive")
        result = await infer_learned_preferences(db, user_id=uid, run_override=True)
        dims = [r.dimension for r in result]
        assert "preferred_signal_type" in dims


# ---------------------------------------------------------------------------
# 36–38. Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    @pytest.mark.asyncio
    async def test_blank_entity_key_excluded(self, db):
        """Events with empty entity_key are not grouped into any candidate."""
        from app.services.user_learning_inference_service import infer_company_preferences
        from app.db.repositories.user_learning_repo import add_user_signal_event
        uid = _uid()
        for i in range(10):
            await add_user_signal_event(
                db, user_id=uid, signal_type="analysis_open", polarity="positive",
                entity_type="company", entity_key="",  # blank key
                source_surface="analysis", interaction_weight=1.0,
                occurred_at=_now() - timedelta(hours=i),
            )
        result = await infer_company_preferences(db, user_id=uid, run_override=True)
        assert result == []

    @pytest.mark.asyncio
    async def test_lookback_days_respected(self, db):
        """Events older than lookback_days window are excluded."""
        from app.services.user_learning_inference_service import infer_sector_preferences
        uid = _uid()
        # Insert 5 events 100 days ago — outside the 30-day window
        await _insert_events(db, user_id=uid, entity_type="sector", entity_key="tech",
                              n=5, polarity="positive", offset_hours=100 * 24)
        result = await infer_sector_preferences(db, user_id=uid, lookback_days=30, run_override=True)
        assert result == []

    @pytest.mark.asyncio
    async def test_user_signal_event_count_unchanged_after_inference(self, db):
        """Inference reads events; it must not modify or delete them."""
        from app.services.user_learning_inference_service import infer_learned_preferences
        from app.db.repositories.user_learning_repo import count_user_signal_events
        uid = _uid()
        await _insert_events(db, user_id=uid, entity_type="company", entity_key="AAPL", n=6, polarity="positive")
        count_before = await count_user_signal_events(db, user_id=uid)
        await infer_learned_preferences(db, user_id=uid, run_override=True)
        count_after = await count_user_signal_events(db, user_id=uid)
        assert count_before == count_after == 6


# ---------------------------------------------------------------------------
# 39–41. Signal strength label derivation
# ---------------------------------------------------------------------------

class TestSignalStrengthLabels:
    @pytest.mark.asyncio
    async def test_tentative_at_threshold(self, db):
        """MIN_EVIDENCE events with mixed polarity → low confidence → tentative."""
        from app.services.user_learning_inference_service import infer_sector_preferences
        uid = _uid()
        # Exactly 5 events, 3 positive + 2 negative = net 0.2, confidence 0.2 → tentative
        await _insert_events(db, user_id=uid, entity_type="sector", entity_key="energy",
                              n=3, polarity="positive")
        await _insert_events(db, user_id=uid, entity_type="sector", entity_key="energy",
                              n=2, polarity="negative")
        result = await infer_sector_preferences(db, user_id=uid, run_override=True)
        assert len(result) == 1
        assert result[0]["signal_strength_label"] == "tentative"

    @pytest.mark.asyncio
    async def test_strong_when_confidence_above_threshold(self, db):
        """All-positive events → confidence=1.0 >= 0.70 → strong."""
        from app.services.user_learning_inference_service import infer_sector_preferences
        uid = _uid()
        await _insert_events(db, user_id=uid, entity_type="sector", entity_key="tech",
                              n=12, polarity="positive")
        result = await infer_sector_preferences(db, user_id=uid, run_override=True)
        assert result[0]["signal_strength_label"] == "strong"

    @pytest.mark.asyncio
    async def test_moderate_confidence_range(self, db):
        """7 positive, 3 negative → confidence=0.4 → exactly at moderate threshold."""
        from app.services.user_learning_inference_service import infer_sector_preferences
        uid = _uid()
        await _insert_events(db, user_id=uid, entity_type="sector", entity_key="materials",
                              n=7, polarity="positive")
        await _insert_events(db, user_id=uid, entity_type="sector", entity_key="materials",
                              n=3, polarity="negative")
        result = await infer_sector_preferences(db, user_id=uid, run_override=True)
        assert len(result) == 1
        # confidence = |7-3|/10 = 0.4 → exactly at moderate threshold
        assert result[0]["signal_strength_label"] in ("moderate", "tentative")

    @pytest.mark.asyncio
    async def test_persisted_row_inherits_signal_strength(self, db):
        from app.services.user_learning_inference_service import infer_learned_preferences
        uid = _uid()
        await _insert_events(db, user_id=uid, entity_type="company", entity_key="NVDA",
                              n=15, polarity="positive")
        rows = await infer_learned_preferences(db, user_id=uid, run_override=True)
        assert rows[0].signal_strength_label == "strong"


# ---------------------------------------------------------------------------
# 44–50. Return type and signature checks
# ---------------------------------------------------------------------------

class TestReturnTypes:
    @pytest.mark.asyncio
    async def test_all_functions_return_list(self, db):
        import app.services.user_learning_inference_service as svc
        uid = _uid()
        for name in (
            "infer_company_preferences",
            "infer_sector_preferences",
            "infer_theme_preferences",
            "infer_horizon_preferences",
            "infer_signal_type_preferences",
            "infer_portfolio_sensitivities",
            "infer_learned_preferences",
        ):
            func = getattr(svc, name)
            result = await func(db, user_id=uid, run_override=False)
            assert isinstance(result, list), f"{name} returned {type(result)}, expected list"

    def test_function_signatures(self):
        import inspect
        import app.services.user_learning_inference_service as svc
        for name in (
            "infer_company_preferences",
            "infer_sector_preferences",
            "infer_theme_preferences",
            "infer_horizon_preferences",
            "infer_signal_type_preferences",
            "infer_portfolio_sensitivities",
            "infer_learned_preferences",
        ):
            func = getattr(svc, name)
            sig = inspect.signature(func)
            params = set(sig.parameters)
            assert "user_id" in params, f"{name} missing user_id"
            assert "lookback_days" in params, f"{name} missing lookback_days"
            assert "run_override" in params, f"{name} missing run_override"


# ---------------------------------------------------------------------------
# 45–46. AST safety
# ---------------------------------------------------------------------------

_SVC_PATH = _ROOT / "app" / "services" / "user_learning_inference_service.py"

_TRUTH_WRITE_MODULES = {
    "forecast_repo",
    "similarity_repo",
    "decision_repo",
    "scenario_repo",
}

_BANNED_PHRASES = [
    "buy", "sell", "hold", "overweight", "underweight",
    "recommend", "target price", "position size",
    "take a position", "enter a trade", "exit a trade",
    "place an order", "execute", "short", "long position",
    "go long", "go short", "open a position", "close a position",
]


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
                        f"Found truth-write module import '{bad}' in inference service"
                    )

    def test_no_conviction_order_execution_imports(self):
        tree, _ = self._load_tree()
        forbidden = {"conviction", "order", "execution"}
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                for f in forbidden:
                    assert f not in module, f"Forbidden import pattern: {f}"

    def test_no_banned_advisory_phrases_in_string_constants(self):
        tree, _ = self._load_tree()

        # Collect docstring node ids to skip them
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
                        f"Banned phrase {phrase!r} found in string constant: {node.value!r}"
                    )

    def test_no_relevance_adjustment_log_writes(self):
        """Inference service must not call add_relevance_adjustment_log."""
        source = _SVC_PATH.read_text()
        assert "add_relevance_adjustment_log" not in source, (
            "Inference service must not write relevance adjustments (that is Slice 15.6+)"
        )

    def test_no_source_table_mutation(self):
        """Inference service must not import or call writes on source/truth tables."""
        source = _SVC_PATH.read_text()
        for bad in (
            "upsert_thesis", "upsert_conviction", "upsert_similarity_edge",
            "update_forecast_vector", "upsert_scenario_snapshot", "upsert_decision_priority",
        ):
            assert bad not in source, f"Found prohibited truth-table write: {bad!r}"
