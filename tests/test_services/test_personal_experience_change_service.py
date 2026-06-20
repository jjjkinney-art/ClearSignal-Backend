"""
Tests — Personal Experience Change Detection, Phase 18 · Slice 3.

Covers:
  1.  service importable
  2.  all 7 public functions present

  --- pure scoring ---
  3.  compute_recency_score at t=0 → 1.0
  4.  compute_recency_score at ~48h → ~0.5
  5.  compute_recency_score with None → 0.0
  6.  compute_recency_score always in [0, 1]
  7.  compute_novelty_score with None last_seen → 1.0
  8.  compute_novelty_score just seen → ~0.0
  9.  compute_novelty_score 48h ago → ~0.5
  10. compute_novelty_score always in [0, 1]

  --- detect_forecast_changes ---
  11. no forecasts → []
  12. forecast present, no cursor → candidate returned (new item)
  13. forecast present, cursor matches → no candidate (unchanged)
  14. forecast present, cursor differs → candidate returned
  15. candidate has correct change_type
  16. candidate has recency_score
  17. candidate has explanation_text
  18. candidate has evidence_refs
  19. flag off → []
  20. null session → []

  --- detect_decision_changes ---
  21. no decisions → []
  22. decision present, no cursor → candidate returned
  23. decision present, cursor matches → no candidate
  24. decision present, cursor differs → candidate returned
  25. candidate has correct change_type
  26. flag off → []
  27. null session → []

  --- detect_scenario_changes ---
  28. no scenarios → []
  29. scenario present, no cursor → candidate returned
  30. scenario present, cursor matches → no candidate
  31. scenario present, cursor differs → candidate returned
  32. candidate has correct change_type
  33. flag off → []
  34. null session → []

  --- detect_watchlist_changes ---
  35. no watched tickers → []
  36. watched ticker with changed memory → candidate returned
  37. watched ticker with matching cursor → no candidate
  38. candidate has correct change_type
  39. flag off → []
  40. null session → []

  --- detect_memory_changes ---
  41. no cursors → []
  42. cursor present, memory updated after last_seen → candidate returned
  43. cursor present, memory not updated → no candidate
  44. candidate has correct change_type
  45. flag off → []
  46. null session → []

  --- build_change_candidates ---
  47. empty DB → []
  48. merges candidates from multiple detect functions
  49. deduplicates by (entity_key, change_type)
  50. sorted by recency_score descending
  51. flag off → []
  52. null session → []

  --- candidate shape ---
  53. all required keys present
  54. recency_score in [0, 1]
  55. novelty_score in [0, 1]

  --- AST safety ---
  56. no truth-table write imports
  57. no conviction/order/execution imports
  58. no banned advisory phrases
  59. no upstream mutation calls
  60. no Notification writes
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

_ROOT     = pathlib.Path(__file__).parent.parent.parent
_SVC_PATH = _ROOT / "app" / "services" / "personal_experience_change_service.py"


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


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Seeding helpers
# ---------------------------------------------------------------------------

async def _seed_forecast(db, entity_key="AAPL", p_positive=0.5, p_negative=0.3):
    from app.db.models import ForecastVector
    row = ForecastVector(
        id=_uid(), entity_type="company", entity_key=entity_key,
        horizon="near_term", horizon_days=30,
        forecast_type="thesis_strengthening",
        p_positive=p_positive, p_negative=p_negative, p_neutral=1.0-p_positive-p_negative,
        confidence_band_low=0.1, confidence_band_high=0.8,
        why="test", forecast_schema=1,
        built_at=_now(), expires_at=_now() + timedelta(hours=72),
    )
    db.add(row)
    await db.flush()
    return row


async def _seed_decision(db, entity_key="AAPL", bucket="high", score=0.8):
    from app.db.models import DecisionPriority
    row = DecisionPriority(
        id=_uid(), candidate_type="forecast", entity_type="company",
        entity_key=entity_key, source_ref="src_001",
        decision_priority=bucket, decision_rank_score=score,
        decision_reason="test", why_now="test",
        decision_schema=1,
        built_at=_now(), expires_at=_now() + timedelta(hours=72),
    )
    db.add(row)
    await db.flush()
    return row


async def _seed_scenario(db, entity_key="AAPL", plausibility="plausible",
                          impact="moderate_negative"):
    from app.db.models import ScenarioSnapshot
    row = ScenarioSnapshot(
        id=_uid(), scenario_type="company", entity_type="company",
        entity_key=entity_key, scenario_key="base_case",
        condition="test condition",
        transmission_path=[{"step": 1}],
        scenario_impact=impact, plausibility_band=plausibility,
        confidence_score=0.7, uncertainty_score=0.2,
        what_changed="test", why_it_matters="test",
        scenario_schema=1,
        built_at=_now(), expires_at=_now() + timedelta(hours=72),
    )
    db.add(row)
    await db.flush()
    return row


async def _seed_watchlist_and_memory(db, ticker="AAPL", user_id=None):
    from app.db.models import WatchedTicker, TickerMemory
    wt = WatchedTicker(
        id=_uid(), user_id=user_id, ticker=ticker,
        company_name=f"{ticker} Inc", active=True,
    )
    db.add(wt)
    tm = TickerMemory(
        id=_uid(), ticker=ticker, company_name=f"{ticker} Inc",
        total_queries=5, version_count=3,
        last_stance="cautious", last_confidence=0.6,
        dominant_concern="valuation",
        updated_at=_now(),
    )
    db.add(tm)
    await db.flush()
    return wt, tm


async def _seed_cursor(db, user_id, entity_type, entity_key, state_hash="old_hash",
                        last_seen_at=None):
    from app.db.repositories.personal_experience_repo import upsert_experience_cursor
    seen = last_seen_at or (_now() - timedelta(hours=24))
    return await upsert_experience_cursor(
        db, user_id=user_id, entity_type=entity_type,
        entity_key=entity_key, last_state_hash=state_hash,
        last_seen_at=seen,
    )


# ---------------------------------------------------------------------------
# 1–2: Import and presence
# ---------------------------------------------------------------------------

class TestImportAndPresence:

    def test_service_importable(self):
        import app.services.personal_experience_change_service  # noqa: F401

    def test_all_functions_present(self):
        import app.services.personal_experience_change_service as svc
        for fn in (
            "compute_recency_score",
            "compute_novelty_score",
            "detect_forecast_changes",
            "detect_decision_changes",
            "detect_scenario_changes",
            "detect_watchlist_changes",
            "detect_memory_changes",
            "build_change_candidates",
        ):
            assert callable(getattr(svc, fn, None)), f"missing: {fn}"


# ---------------------------------------------------------------------------
# 3–10: Pure scoring
# ---------------------------------------------------------------------------

class TestRecencyScore:

    def test_at_now_returns_one(self):
        from app.services.personal_experience_change_service import compute_recency_score
        now = _now()
        assert compute_recency_score(now, now) == pytest.approx(1.0, abs=0.01)

    def test_at_half_life_returns_about_half(self):
        from app.services.personal_experience_change_service import compute_recency_score
        now = _now()
        past = now - timedelta(hours=48)
        score = compute_recency_score(past, now)
        assert 0.4 <= score <= 0.6

    def test_none_returns_zero(self):
        from app.services.personal_experience_change_service import compute_recency_score
        assert compute_recency_score(None) == 0.0

    def test_always_in_range(self):
        from app.services.personal_experience_change_service import compute_recency_score
        now = _now()
        for hours in [0, 1, 12, 24, 48, 96, 168, 720]:
            s = compute_recency_score(now - timedelta(hours=hours), now)
            assert 0.0 <= s <= 1.0


class TestNoveltyScore:

    def test_never_seen_returns_one(self):
        from app.services.personal_experience_change_service import compute_novelty_score
        assert compute_novelty_score(None) == 1.0

    def test_just_seen_returns_near_zero(self):
        from app.services.personal_experience_change_service import compute_novelty_score
        now = _now()
        score = compute_novelty_score(now, now)
        assert score < 0.01

    def test_at_half_life_returns_about_half(self):
        from app.services.personal_experience_change_service import compute_novelty_score
        now = _now()
        past = now - timedelta(hours=48)
        score = compute_novelty_score(past, now)
        assert 0.4 <= score <= 0.6

    def test_always_in_range(self):
        from app.services.personal_experience_change_service import compute_novelty_score
        now = _now()
        for hours in [0, 1, 12, 24, 48, 96, 168, 720]:
            s = compute_novelty_score(now - timedelta(hours=hours), now)
            assert 0.0 <= s <= 1.0


# ---------------------------------------------------------------------------
# 11–20: detect_forecast_changes
# ---------------------------------------------------------------------------

class TestDetectForecastChanges:

    @pytest.mark.asyncio
    async def test_no_forecasts_empty(self, db):
        from app.services.personal_experience_change_service import detect_forecast_changes
        result = await detect_forecast_changes(db, user_id=_uid(), run_override=True)
        assert result == []

    @pytest.mark.asyncio
    async def test_forecast_no_cursor_returns_candidate(self, db):
        from app.services.personal_experience_change_service import detect_forecast_changes
        uid = _uid()
        await _seed_forecast(db, entity_key="AAPL")
        result = await detect_forecast_changes(
            db, user_id=uid, entity_keys=["AAPL"], run_override=True)
        assert len(result) == 1
        assert result[0]["entity_key"] == "AAPL"

    @pytest.mark.asyncio
    async def test_forecast_matching_cursor_no_candidate(self, db):
        from app.services.personal_experience_change_service import (
            detect_forecast_changes, _hash_fields,
        )
        uid = _uid()
        fv = await _seed_forecast(db, entity_key="MSFT", p_positive=0.5, p_negative=0.3)
        current_hash = _hash_fields(0.5, 0.3, 0.1, 0.8, "thesis_strengthening", "near_term")
        await _seed_cursor(db, uid, "forecast", "MSFT", state_hash=current_hash)
        result = await detect_forecast_changes(
            db, user_id=uid, entity_keys=["MSFT"], run_override=True)
        assert len(result) == 0

    @pytest.mark.asyncio
    async def test_forecast_different_cursor_returns_candidate(self, db):
        from app.services.personal_experience_change_service import detect_forecast_changes
        uid = _uid()
        await _seed_forecast(db, entity_key="GOOG")
        await _seed_cursor(db, uid, "forecast", "GOOG", state_hash="stale_hash")
        result = await detect_forecast_changes(
            db, user_id=uid, entity_keys=["GOOG"], run_override=True)
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_candidate_change_type(self, db):
        from app.services.personal_experience_change_service import detect_forecast_changes
        uid = _uid()
        await _seed_forecast(db, entity_key="TSLA")
        result = await detect_forecast_changes(
            db, user_id=uid, entity_keys=["TSLA"], run_override=True)
        assert result[0]["change_type"] == "forecast_changed"

    @pytest.mark.asyncio
    async def test_candidate_has_recency_score(self, db):
        from app.services.personal_experience_change_service import detect_forecast_changes
        uid = _uid()
        await _seed_forecast(db, entity_key="META")
        result = await detect_forecast_changes(
            db, user_id=uid, entity_keys=["META"], run_override=True)
        assert "recency_score" in result[0]
        assert 0.0 <= result[0]["recency_score"] <= 1.0

    @pytest.mark.asyncio
    async def test_candidate_has_explanation(self, db):
        from app.services.personal_experience_change_service import detect_forecast_changes
        uid = _uid()
        await _seed_forecast(db, entity_key="AMZN")
        result = await detect_forecast_changes(
            db, user_id=uid, entity_keys=["AMZN"], run_override=True)
        assert result[0]["explanation_text"]
        assert "AMZN" in result[0]["explanation_text"]

    @pytest.mark.asyncio
    async def test_candidate_has_evidence_refs(self, db):
        from app.services.personal_experience_change_service import detect_forecast_changes
        uid = _uid()
        await _seed_forecast(db, entity_key="NFLX")
        result = await detect_forecast_changes(
            db, user_id=uid, entity_keys=["NFLX"], run_override=True)
        assert len(result[0]["evidence_refs"]) >= 1
        assert result[0]["evidence_refs"][0]["type"] == "forecast_vector"

    @pytest.mark.asyncio
    async def test_flag_off_empty(self, db):
        from app.services.personal_experience_change_service import detect_forecast_changes
        await _seed_forecast(db, entity_key="X")
        result = await detect_forecast_changes(
            db, user_id=_uid(), entity_keys=["X"], run_override=False)
        assert result == []

    @pytest.mark.asyncio
    async def test_null_session_empty(self):
        from app.services.personal_experience_change_service import detect_forecast_changes
        result = await detect_forecast_changes(None, user_id=_uid(), run_override=True)
        assert result == []


# ---------------------------------------------------------------------------
# 21–27: detect_decision_changes
# ---------------------------------------------------------------------------

class TestDetectDecisionChanges:

    @pytest.mark.asyncio
    async def test_no_decisions_empty(self, db):
        from app.services.personal_experience_change_service import detect_decision_changes
        result = await detect_decision_changes(db, user_id=_uid(), run_override=True)
        assert result == []

    @pytest.mark.asyncio
    async def test_decision_no_cursor_returns_candidate(self, db):
        from app.services.personal_experience_change_service import detect_decision_changes
        uid = _uid()
        await _seed_decision(db, entity_key="AAPL")
        result = await detect_decision_changes(
            db, user_id=uid, entity_keys=["AAPL"], run_override=True)
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_decision_matching_cursor_no_candidate(self, db):
        from app.services.personal_experience_change_service import (
            detect_decision_changes, _hash_fields,
        )
        uid = _uid()
        await _seed_decision(db, entity_key="MSFT", bucket="high", score=0.8)
        current_hash = _hash_fields("high", 0.8, "forecast")
        await _seed_cursor(db, uid, "decision", "MSFT", state_hash=current_hash)
        result = await detect_decision_changes(
            db, user_id=uid, entity_keys=["MSFT"], run_override=True)
        assert len(result) == 0

    @pytest.mark.asyncio
    async def test_decision_different_cursor_returns_candidate(self, db):
        from app.services.personal_experience_change_service import detect_decision_changes
        uid = _uid()
        await _seed_decision(db, entity_key="GOOG")
        await _seed_cursor(db, uid, "decision", "GOOG", state_hash="stale")
        result = await detect_decision_changes(
            db, user_id=uid, entity_keys=["GOOG"], run_override=True)
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_candidate_change_type(self, db):
        from app.services.personal_experience_change_service import detect_decision_changes
        uid = _uid()
        await _seed_decision(db, entity_key="TSLA")
        result = await detect_decision_changes(
            db, user_id=uid, entity_keys=["TSLA"], run_override=True)
        assert result[0]["change_type"] == "decision_changed"

    @pytest.mark.asyncio
    async def test_flag_off_empty(self, db):
        from app.services.personal_experience_change_service import detect_decision_changes
        result = await detect_decision_changes(
            db, user_id=_uid(), run_override=False)
        assert result == []

    @pytest.mark.asyncio
    async def test_null_session_empty(self):
        from app.services.personal_experience_change_service import detect_decision_changes
        result = await detect_decision_changes(None, user_id=_uid(), run_override=True)
        assert result == []


# ---------------------------------------------------------------------------
# 28–34: detect_scenario_changes
# ---------------------------------------------------------------------------

class TestDetectScenarioChanges:

    @pytest.mark.asyncio
    async def test_no_scenarios_empty(self, db):
        from app.services.personal_experience_change_service import detect_scenario_changes
        result = await detect_scenario_changes(db, user_id=_uid(), run_override=True)
        assert result == []

    @pytest.mark.asyncio
    async def test_scenario_no_cursor_returns_candidate(self, db):
        from app.services.personal_experience_change_service import detect_scenario_changes
        uid = _uid()
        await _seed_scenario(db, entity_key="AAPL")
        result = await detect_scenario_changes(
            db, user_id=uid, entity_keys=["AAPL"], run_override=True)
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_scenario_matching_cursor_no_candidate(self, db):
        from app.services.personal_experience_change_service import (
            detect_scenario_changes, _hash_fields,
        )
        uid = _uid()
        await _seed_scenario(db, entity_key="MSFT", plausibility="plausible",
                              impact="moderate_negative")
        current_hash = _hash_fields("plausible", "moderate_negative", 0.7, "base_case")
        await _seed_cursor(db, uid, "scenario", "MSFT:base_case", state_hash=current_hash)
        result = await detect_scenario_changes(
            db, user_id=uid, entity_keys=["MSFT"], run_override=True)
        assert len(result) == 0

    @pytest.mark.asyncio
    async def test_scenario_different_cursor_returns_candidate(self, db):
        from app.services.personal_experience_change_service import detect_scenario_changes
        uid = _uid()
        await _seed_scenario(db, entity_key="GOOG")
        await _seed_cursor(db, uid, "scenario", "GOOG:base_case", state_hash="stale")
        result = await detect_scenario_changes(
            db, user_id=uid, entity_keys=["GOOG"], run_override=True)
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_candidate_change_type(self, db):
        from app.services.personal_experience_change_service import detect_scenario_changes
        uid = _uid()
        await _seed_scenario(db, entity_key="NVDA")
        result = await detect_scenario_changes(
            db, user_id=uid, entity_keys=["NVDA"], run_override=True)
        assert result[0]["change_type"] == "scenario_changed"

    @pytest.mark.asyncio
    async def test_flag_off_empty(self, db):
        from app.services.personal_experience_change_service import detect_scenario_changes
        result = await detect_scenario_changes(
            db, user_id=_uid(), run_override=False)
        assert result == []

    @pytest.mark.asyncio
    async def test_null_session_empty(self):
        from app.services.personal_experience_change_service import detect_scenario_changes
        result = await detect_scenario_changes(None, user_id=_uid(), run_override=True)
        assert result == []


# ---------------------------------------------------------------------------
# 35–40: detect_watchlist_changes
# ---------------------------------------------------------------------------

class TestDetectWatchlistChanges:

    @pytest.mark.asyncio
    async def test_no_watched_empty(self, db):
        from app.services.personal_experience_change_service import detect_watchlist_changes
        result = await detect_watchlist_changes(db, user_id=_uid(), run_override=True)
        assert result == []

    @pytest.mark.asyncio
    async def test_watched_changed_memory_returns_candidate(self, db):
        from app.services.personal_experience_change_service import detect_watchlist_changes
        uid = _uid()
        await _seed_watchlist_and_memory(db, ticker="AAPL", user_id=None)
        result = await detect_watchlist_changes(db, user_id=uid, run_override=True)
        assert len(result) >= 1
        assert result[0]["entity_key"] == "AAPL"

    @pytest.mark.asyncio
    async def test_watched_matching_cursor_no_candidate(self, db):
        from app.services.personal_experience_change_service import (
            detect_watchlist_changes, _hash_fields,
        )
        uid = _uid()
        _, tm = await _seed_watchlist_and_memory(db, ticker="MSFT", user_id=None)
        current_hash = _hash_fields("cautious", 0.6, "valuation", 3)
        await _seed_cursor(db, uid, "ticker", "MSFT", state_hash=current_hash)
        result = await detect_watchlist_changes(db, user_id=uid, run_override=True)
        msft_results = [r for r in result if r["entity_key"] == "MSFT"]
        assert len(msft_results) == 0

    @pytest.mark.asyncio
    async def test_candidate_change_type(self, db):
        from app.services.personal_experience_change_service import detect_watchlist_changes
        uid = _uid()
        await _seed_watchlist_and_memory(db, ticker="NVDA", user_id=None)
        result = await detect_watchlist_changes(db, user_id=uid, run_override=True)
        nvda = [r for r in result if r["entity_key"] == "NVDA"]
        assert nvda[0]["change_type"] == "watchlist_drift"

    @pytest.mark.asyncio
    async def test_flag_off_empty(self, db):
        from app.services.personal_experience_change_service import detect_watchlist_changes
        result = await detect_watchlist_changes(
            db, user_id=_uid(), run_override=False)
        assert result == []

    @pytest.mark.asyncio
    async def test_null_session_empty(self):
        from app.services.personal_experience_change_service import detect_watchlist_changes
        result = await detect_watchlist_changes(None, user_id=_uid(), run_override=True)
        assert result == []


# ---------------------------------------------------------------------------
# 41–46: detect_memory_changes
# ---------------------------------------------------------------------------

class TestDetectMemoryChanges:

    @pytest.mark.asyncio
    async def test_no_cursors_empty(self, db):
        from app.services.personal_experience_change_service import detect_memory_changes
        result = await detect_memory_changes(db, user_id=_uid(), run_override=True)
        assert result == []

    @pytest.mark.asyncio
    async def test_memory_updated_after_cursor_returns_candidate(self, db):
        from app.services.personal_experience_change_service import detect_memory_changes
        uid = _uid()
        await _seed_watchlist_and_memory(db, ticker="AAPL")
        await _seed_cursor(
            db, uid, "ticker", "AAPL",
            last_seen_at=_now() - timedelta(hours=48),
        )
        result = await detect_memory_changes(
            db, user_id=uid, entity_keys=["AAPL"], run_override=True)
        assert len(result) == 1
        assert result[0]["change_type"] == "memory_revisit"

    @pytest.mark.asyncio
    async def test_memory_not_updated_no_candidate(self, db):
        from app.services.personal_experience_change_service import detect_memory_changes
        uid = _uid()
        await _seed_watchlist_and_memory(db, ticker="MSFT")
        await _seed_cursor(
            db, uid, "ticker", "MSFT",
            last_seen_at=_now() + timedelta(hours=1),
        )
        result = await detect_memory_changes(
            db, user_id=uid, entity_keys=["MSFT"], run_override=True)
        assert len(result) == 0

    @pytest.mark.asyncio
    async def test_candidate_change_type(self, db):
        from app.services.personal_experience_change_service import detect_memory_changes
        uid = _uid()
        await _seed_watchlist_and_memory(db, ticker="GOOG")
        await _seed_cursor(
            db, uid, "ticker", "GOOG",
            last_seen_at=_now() - timedelta(hours=72),
        )
        result = await detect_memory_changes(
            db, user_id=uid, entity_keys=["GOOG"], run_override=True)
        assert result[0]["change_type"] == "memory_revisit"

    @pytest.mark.asyncio
    async def test_flag_off_empty(self, db):
        from app.services.personal_experience_change_service import detect_memory_changes
        result = await detect_memory_changes(
            db, user_id=_uid(), run_override=False)
        assert result == []

    @pytest.mark.asyncio
    async def test_null_session_empty(self):
        from app.services.personal_experience_change_service import detect_memory_changes
        result = await detect_memory_changes(None, user_id=_uid(), run_override=True)
        assert result == []


# ---------------------------------------------------------------------------
# 47–52: build_change_candidates
# ---------------------------------------------------------------------------

class TestBuildChangeCandidates:

    @pytest.mark.asyncio
    async def test_empty_db_returns_empty(self, db):
        from app.services.personal_experience_change_service import build_change_candidates
        result = await build_change_candidates(db, user_id=_uid(), run_override=True)
        assert result == []

    @pytest.mark.asyncio
    async def test_merges_multiple_sources(self, db):
        from app.services.personal_experience_change_service import build_change_candidates
        uid = _uid()
        await _seed_forecast(db, entity_key="AAPL")
        await _seed_decision(db, entity_key="MSFT")
        result = await build_change_candidates(
            db, user_id=uid, entity_keys=["AAPL", "MSFT"], run_override=True)
        types = {r["change_type"] for r in result}
        assert "forecast_changed" in types
        assert "decision_changed" in types

    @pytest.mark.asyncio
    async def test_deduplicates_by_key_and_type(self, db):
        from app.services.personal_experience_change_service import build_change_candidates
        uid = _uid()
        await _seed_forecast(db, entity_key="AAPL")
        result = await build_change_candidates(
            db, user_id=uid, entity_keys=["AAPL"], run_override=True)
        aapl_forecast = [r for r in result
                         if r["entity_key"] == "AAPL"
                         and r["change_type"] == "forecast_changed"]
        assert len(aapl_forecast) <= 1

    @pytest.mark.asyncio
    async def test_sorted_by_recency_desc(self, db):
        from app.services.personal_experience_change_service import build_change_candidates
        uid = _uid()
        await _seed_forecast(db, entity_key="OLD")
        await _seed_forecast(db, entity_key="NEW")
        result = await build_change_candidates(
            db, user_id=uid, entity_keys=["OLD", "NEW"], run_override=True)
        if len(result) >= 2:
            assert result[0]["recency_score"] >= result[-1]["recency_score"]

    @pytest.mark.asyncio
    async def test_flag_off_empty(self, db):
        from app.services.personal_experience_change_service import build_change_candidates
        result = await build_change_candidates(
            db, user_id=_uid(), run_override=False)
        assert result == []

    @pytest.mark.asyncio
    async def test_null_session_empty(self):
        from app.services.personal_experience_change_service import build_change_candidates
        result = await build_change_candidates(None, user_id=_uid(), run_override=True)
        assert result == []


# ---------------------------------------------------------------------------
# 53–55: Candidate shape
# ---------------------------------------------------------------------------

class TestCandidateShape:

    _REQUIRED_KEYS = {
        "entity_key", "entity_type", "change_type", "changed_at",
        "recency_score", "novelty_score", "explanation_text", "evidence_refs",
    }

    @pytest.mark.asyncio
    async def test_all_required_keys_present(self, db):
        from app.services.personal_experience_change_service import detect_forecast_changes
        uid = _uid()
        await _seed_forecast(db, entity_key="AAPL")
        result = await detect_forecast_changes(
            db, user_id=uid, entity_keys=["AAPL"], run_override=True)
        assert len(result) >= 1
        for key in self._REQUIRED_KEYS:
            assert key in result[0], f"missing key: {key}"

    @pytest.mark.asyncio
    async def test_recency_score_in_range(self, db):
        from app.services.personal_experience_change_service import detect_forecast_changes
        uid = _uid()
        await _seed_forecast(db, entity_key="MSFT")
        result = await detect_forecast_changes(
            db, user_id=uid, entity_keys=["MSFT"], run_override=True)
        assert 0.0 <= result[0]["recency_score"] <= 1.0

    @pytest.mark.asyncio
    async def test_novelty_score_in_range(self, db):
        from app.services.personal_experience_change_service import detect_forecast_changes
        uid = _uid()
        await _seed_forecast(db, entity_key="GOOG")
        result = await detect_forecast_changes(
            db, user_id=uid, entity_keys=["GOOG"], run_override=True)
        assert 0.0 <= result[0]["novelty_score"] <= 1.0


# ---------------------------------------------------------------------------
# 56–60: AST safety
# ---------------------------------------------------------------------------

def _load_ast():
    return ast.parse(_SVC_PATH.read_text())


def _docstring_node_ids(tree):
    ids = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                             ast.AsyncFunctionDef)):
            if (node.body
                    and isinstance(node.body[0], ast.Expr)
                    and isinstance(node.body[0].value, ast.Constant)):
                ids.add(id(node.body[0].value))
    return ids


def _import_names(tree):
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
    "add_forecast", "upsert_forecast", "add_decision", "upsert_decision",
    "add_scenario", "upsert_scenario", "add_similarity",
    "upsert_similarity", "add_ticker_memory", "upsert_learned_preference",
    "add_user_signal_event",
)


class TestAstSafety:

    def test_no_truth_table_write_imports(self):
        names = _import_names(_load_ast())
        for fn in _TRUTH_WRITE_FNS:
            assert fn not in names, f"forbidden import: {fn}"

    def test_no_conviction_order_execution_imports(self):
        names = _import_names(_load_ast())
        for forbidden in ("conviction", "order_service", "execution_service", "stance"):
            for name in names:
                assert forbidden not in name.lower(), (
                    f"forbidden import contains '{forbidden}': {name}")

    def test_no_banned_advisory_phrases(self):
        tree = _load_ast()
        doc_ids = _docstring_node_ids(tree)
        for node in ast.walk(tree):
            if (isinstance(node, ast.Constant)
                    and isinstance(node.value, str)
                    and id(node) not in doc_ids):
                low = node.value.lower()
                for phrase in _BANNED_PHRASES:
                    assert phrase not in low, (
                        f"banned phrase '{phrase}' in: {node.value!r}")

    def test_no_upstream_mutation_calls(self):
        tree = _load_ast()
        call_attrs = set()
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)):
                call_attrs.add(node.func.attr)
        for bad in ("upsert_forecast", "upsert_decision", "upsert_scenario",
                     "add_forecast", "add_decision", "add_scenario_snapshot"):
            assert bad not in call_attrs, f"upstream mutation call: {bad}"

    def test_no_notification_writes(self):
        names = _import_names(_load_ast())
        assert "Notification" not in names
        assert "add_notification" not in names
