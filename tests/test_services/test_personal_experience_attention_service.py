"""
Tests — Personal Experience Attention Scoring, Phase 18 · Slice 4.

Covers:
  1.  service importable
  2.  all public functions present

  --- weight validation ---
  3.  default weights valid
  4.  weights missing dimension → invalid
  5.  weight below min → invalid
  6.  weight above max → invalid
  7.  weights not summing to 1.0 → invalid

  --- compute_attention_priority ---
  8.  no decision rows → 0.0
  9.  critical decision → 1.0
  10. high decision → 0.8
  11. medium decision → 0.5
  12. low decision → 0.3
  13. informational → 0.1
  14. null session → 0.0
  15. flag off → 0.0

  --- compute_personal_relevance ---
  16. no preferences → 0.0
  17. active preference → affinity * confidence
  18. non-active preference excluded
  19. null session → 0.0
  20. flag off → 0.0

  --- compute_memory_relevance ---
  21. no cursor → 0.0
  22. cursor with view_count=5 → 0.5
  23. cursor with view_count=10 → 1.0 (capped)
  24. null session → 0.0

  --- compute_portfolio_relevance ---
  25. no portfolio → 0.0
  26. position with weight → returns weight
  27. owned position without weight → 0.3
  28. watchlist position → 0.1
  29. null session → 0.0

  --- compute_revisit_score ---
  30. no cursor → 0.0
  31. cursor with engagement + change → score > 0
  32. cursor with no change → 0.0
  33. null session → 0.0

  --- composite scoring ---
  34. all zeros → 0.0
  35. all ones → 1.0
  36. default weights produce correct sum
  37. invalid weights fallback to defaults

  --- score_change_candidate ---
  38. returns all 7 dimensions
  39. returns composite_score
  40. flag off → all zeros
  41. null session → all zeros

  --- rank_change_candidates ---
  42. empty list → []
  43. sorted by composite desc
  44. deterministic: same input → same output
  45. flag off → []
  46. null session → []

  --- attention floor ---
  47. urgent items (>0.8) in top 5
  48. non-urgent items below urgent
  49. empty list → []

  --- novelty reserve ---
  50. novel items (personal_relevance=0) get reserved slots
  51. under min_items → no reserve applied
  52. novelty_reserve_applied flag set on reserved items

  --- AST safety ---
  53. no truth-table write imports
  54. no conviction/order/execution imports
  55. no banned advisory phrases
  56. no upstream mutation calls
  57. no Notification writes
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
_SVC_PATH = _ROOT / "app" / "services" / "personal_experience_attention_service.py"


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


# --- Seeding helpers ---

async def _seed_decision(db, entity_key, bucket="high", score=0.8):
    from app.db.models import DecisionPriority
    row = DecisionPriority(
        id=_uid(), candidate_type="forecast", entity_type="company",
        entity_key=entity_key, source_ref="src",
        decision_priority=bucket, decision_rank_score=score,
        decision_reason="test", why_now="test", decision_schema=1,
        built_at=_now(), expires_at=_now() + timedelta(hours=72),
    )
    db.add(row)
    await db.flush()
    return row


async def _seed_preference(db, entity_key, affinity=0.8, confidence=0.9, status="active"):
    from app.db.models import LearnedPreference
    row = LearnedPreference(
        id=_uid(), user_id=_uid(), dimension="company_interest",
        entity_key=entity_key, affinity=affinity, confidence=confidence,
        status=status,
    )
    db.add(row)
    await db.flush()
    return row


async def _seed_cursor(db, user_id, entity_key, view_count=1):
    from app.db.repositories.personal_experience_repo import upsert_experience_cursor
    row = await upsert_experience_cursor(
        db, user_id=user_id, entity_type="ticker",
        entity_key=entity_key, last_state_hash="h",
    )
    if view_count > 1:
        for _ in range(view_count - 1):
            await upsert_experience_cursor(
                db, user_id=user_id, entity_type="ticker",
                entity_key=entity_key, last_state_hash="h",
            )
    return row


async def _seed_portfolio_position(db, user_id, ticker, weight=None, membership="owned"):
    from app.db.models import Portfolio, PortfolioPosition
    port = Portfolio(id=_uid(), user_id=user_id, name="default", is_default=True)
    db.add(port)
    await db.flush()
    pos = PortfolioPosition(
        id=_uid(), portfolio_id=port.id, ticker=ticker,
        membership_class=membership, weight=weight, active=True,
    )
    db.add(pos)
    await db.flush()
    return pos


def _make_candidate(entity_key="AAPL", recency=0.7, novelty=0.5):
    return {
        "entity_key": entity_key, "entity_type": "company",
        "change_type": "forecast_changed", "changed_at": _now().isoformat(),
        "recency_score": recency, "novelty_score": novelty,
        "explanation_text": "test", "evidence_refs": [],
    }


# ---------------------------------------------------------------------------
# 1–2: Import and presence
# ---------------------------------------------------------------------------

class TestImportAndPresence:

    def test_importable(self):
        import app.services.personal_experience_attention_service  # noqa: F401

    def test_all_functions_present(self):
        import app.services.personal_experience_attention_service as svc
        for fn in (
            "compute_attention_priority", "compute_personal_relevance",
            "compute_memory_relevance", "compute_portfolio_relevance",
            "compute_revisit_score", "compute_composite_score",
            "validate_weights", "score_change_candidate",
            "rank_change_candidates", "apply_attention_floor",
            "apply_novelty_reserve",
        ):
            assert callable(getattr(svc, fn, None)), f"missing: {fn}"


# ---------------------------------------------------------------------------
# 3–7: Weight validation
# ---------------------------------------------------------------------------

class TestWeightValidation:

    def test_default_weights_valid(self):
        from app.services.personal_experience_attention_service import (
            validate_weights, DEFAULT_WEIGHTS,
        )
        ok, reason = validate_weights(DEFAULT_WEIGHTS)
        assert ok, reason

    def test_missing_dimension_invalid(self):
        from app.services.personal_experience_attention_service import validate_weights
        w = {"attention_priority": 1.0}
        ok, _ = validate_weights(w)
        assert not ok

    def test_below_min_invalid(self):
        from app.services.personal_experience_attention_service import (
            validate_weights, DEFAULT_WEIGHTS,
        )
        w = dict(DEFAULT_WEIGHTS)
        w["attention_priority"] = 0.01
        ok, _ = validate_weights(w)
        assert not ok

    def test_above_max_invalid(self):
        from app.services.personal_experience_attention_service import (
            validate_weights, DEFAULT_WEIGHTS,
        )
        w = dict(DEFAULT_WEIGHTS)
        w["attention_priority"] = 0.50
        ok, _ = validate_weights(w)
        assert not ok

    def test_bad_sum_invalid(self):
        from app.services.personal_experience_attention_service import (
            validate_weights, DEFAULT_WEIGHTS,
        )
        w = dict(DEFAULT_WEIGHTS)
        w["attention_priority"] = 0.30
        ok, _ = validate_weights(w)
        assert not ok


# ---------------------------------------------------------------------------
# 8–15: compute_attention_priority
# ---------------------------------------------------------------------------

class TestAttentionPriority:

    @pytest.mark.asyncio
    async def test_no_decisions_zero(self, db):
        from app.services.personal_experience_attention_service import compute_attention_priority
        s = await compute_attention_priority(
            db, entity_key="AAPL", run_override=True)
        assert s == 0.0

    @pytest.mark.asyncio
    async def test_critical_returns_one(self, db):
        from app.services.personal_experience_attention_service import compute_attention_priority
        await _seed_decision(db, "AAPL", bucket="critical")
        s = await compute_attention_priority(
            db, entity_key="AAPL", run_override=True)
        assert s == 1.0

    @pytest.mark.asyncio
    async def test_high_returns_0_8(self, db):
        from app.services.personal_experience_attention_service import compute_attention_priority
        await _seed_decision(db, "MSFT", bucket="high")
        s = await compute_attention_priority(
            db, entity_key="MSFT", run_override=True)
        assert s == 0.8

    @pytest.mark.asyncio
    async def test_medium_returns_0_5(self, db):
        from app.services.personal_experience_attention_service import compute_attention_priority
        await _seed_decision(db, "GOOG", bucket="medium")
        s = await compute_attention_priority(
            db, entity_key="GOOG", run_override=True)
        assert s == 0.5

    @pytest.mark.asyncio
    async def test_low_returns_0_3(self, db):
        from app.services.personal_experience_attention_service import compute_attention_priority
        await _seed_decision(db, "NVDA", bucket="low")
        s = await compute_attention_priority(
            db, entity_key="NVDA", run_override=True)
        assert s == 0.3

    @pytest.mark.asyncio
    async def test_informational_returns_0_1(self, db):
        from app.services.personal_experience_attention_service import compute_attention_priority
        await _seed_decision(db, "META", bucket="informational")
        s = await compute_attention_priority(
            db, entity_key="META", run_override=True)
        assert s == 0.1

    @pytest.mark.asyncio
    async def test_null_session_zero(self):
        from app.services.personal_experience_attention_service import compute_attention_priority
        assert await compute_attention_priority(
            None, entity_key="X", run_override=True) == 0.0

    @pytest.mark.asyncio
    async def test_flag_off_zero(self, db):
        from app.services.personal_experience_attention_service import compute_attention_priority
        assert await compute_attention_priority(
            db, entity_key="X", run_override=False) == 0.0


# ---------------------------------------------------------------------------
# 16–20: compute_personal_relevance
# ---------------------------------------------------------------------------

class TestPersonalRelevance:

    @pytest.mark.asyncio
    async def test_no_prefs_zero(self, db):
        from app.services.personal_experience_attention_service import compute_personal_relevance
        s = await compute_personal_relevance(
            db, entity_key="AAPL", run_override=True)
        assert s == 0.0

    @pytest.mark.asyncio
    async def test_active_pref_returns_product(self, db):
        from app.services.personal_experience_attention_service import compute_personal_relevance
        await _seed_preference(db, "AAPL", affinity=0.8, confidence=0.5)
        s = await compute_personal_relevance(
            db, entity_key="AAPL", run_override=True)
        assert s == pytest.approx(0.4, abs=0.01)

    @pytest.mark.asyncio
    async def test_non_active_excluded(self, db):
        from app.services.personal_experience_attention_service import compute_personal_relevance
        await _seed_preference(db, "MSFT", status="falsified")
        s = await compute_personal_relevance(
            db, entity_key="MSFT", run_override=True)
        assert s == 0.0

    @pytest.mark.asyncio
    async def test_null_session_zero(self):
        from app.services.personal_experience_attention_service import compute_personal_relevance
        assert await compute_personal_relevance(
            None, entity_key="X", run_override=True) == 0.0

    @pytest.mark.asyncio
    async def test_flag_off_zero(self, db):
        from app.services.personal_experience_attention_service import compute_personal_relevance
        assert await compute_personal_relevance(
            db, entity_key="X", run_override=False) == 0.0


# ---------------------------------------------------------------------------
# 21–24: compute_memory_relevance
# ---------------------------------------------------------------------------

class TestMemoryRelevance:

    @pytest.mark.asyncio
    async def test_no_cursor_zero(self, db):
        from app.services.personal_experience_attention_service import compute_memory_relevance
        s = await compute_memory_relevance(
            db, user_id=_uid(), entity_key="AAPL", run_override=True)
        assert s == 0.0

    @pytest.mark.asyncio
    async def test_view_count_5_returns_half(self, db):
        from app.services.personal_experience_attention_service import compute_memory_relevance
        uid = _uid()
        await _seed_cursor(db, uid, "AAPL", view_count=5)
        s = await compute_memory_relevance(
            db, user_id=uid, entity_key="AAPL", run_override=True)
        assert s == pytest.approx(0.5, abs=0.01)

    @pytest.mark.asyncio
    async def test_view_count_10_returns_one(self, db):
        from app.services.personal_experience_attention_service import compute_memory_relevance
        uid = _uid()
        await _seed_cursor(db, uid, "MSFT", view_count=10)
        s = await compute_memory_relevance(
            db, user_id=uid, entity_key="MSFT", run_override=True)
        assert s == pytest.approx(1.0, abs=0.01)

    @pytest.mark.asyncio
    async def test_null_session_zero(self):
        from app.services.personal_experience_attention_service import compute_memory_relevance
        assert await compute_memory_relevance(
            None, user_id=_uid(), entity_key="X", run_override=True) == 0.0


# ---------------------------------------------------------------------------
# 25–29: compute_portfolio_relevance
# ---------------------------------------------------------------------------

class TestPortfolioRelevance:

    @pytest.mark.asyncio
    async def test_no_portfolio_zero(self, db):
        from app.services.personal_experience_attention_service import compute_portfolio_relevance
        s = await compute_portfolio_relevance(
            db, user_id=_uid(), entity_key="AAPL", run_override=True)
        assert s == 0.0

    @pytest.mark.asyncio
    async def test_position_with_weight(self, db):
        from app.services.personal_experience_attention_service import compute_portfolio_relevance
        uid = _uid()
        await _seed_portfolio_position(db, uid, "AAPL", weight=0.35)
        s = await compute_portfolio_relevance(
            db, user_id=uid, entity_key="AAPL", run_override=True)
        assert s == pytest.approx(0.35, abs=0.01)

    @pytest.mark.asyncio
    async def test_owned_without_weight(self, db):
        from app.services.personal_experience_attention_service import compute_portfolio_relevance
        uid = _uid()
        await _seed_portfolio_position(db, uid, "MSFT", weight=None, membership="owned")
        s = await compute_portfolio_relevance(
            db, user_id=uid, entity_key="MSFT", run_override=True)
        assert s == pytest.approx(0.3, abs=0.01)

    @pytest.mark.asyncio
    async def test_watchlist_position(self, db):
        from app.services.personal_experience_attention_service import compute_portfolio_relevance
        uid = _uid()
        await _seed_portfolio_position(db, uid, "GOOG", weight=None, membership="watchlist")
        s = await compute_portfolio_relevance(
            db, user_id=uid, entity_key="GOOG", run_override=True)
        assert s == pytest.approx(0.1, abs=0.01)

    @pytest.mark.asyncio
    async def test_null_session_zero(self):
        from app.services.personal_experience_attention_service import compute_portfolio_relevance
        assert await compute_portfolio_relevance(
            None, user_id=_uid(), entity_key="X", run_override=True) == 0.0


# ---------------------------------------------------------------------------
# 30–33: compute_revisit_score
# ---------------------------------------------------------------------------

class TestRevisitScore:

    @pytest.mark.asyncio
    async def test_no_cursor_zero(self, db):
        from app.services.personal_experience_attention_service import compute_revisit_score
        s = await compute_revisit_score(
            db, user_id=_uid(), entity_key="AAPL",
            change_magnitude=0.5, run_override=True)
        assert s == 0.0

    @pytest.mark.asyncio
    async def test_cursor_with_change(self, db):
        from app.services.personal_experience_attention_service import compute_revisit_score
        uid = _uid()
        await _seed_cursor(db, uid, "AAPL", view_count=5)
        s = await compute_revisit_score(
            db, user_id=uid, entity_key="AAPL",
            change_magnitude=0.8, run_override=True)
        assert s > 0.0

    @pytest.mark.asyncio
    async def test_cursor_no_change(self, db):
        from app.services.personal_experience_attention_service import compute_revisit_score
        uid = _uid()
        await _seed_cursor(db, uid, "MSFT", view_count=5)
        s = await compute_revisit_score(
            db, user_id=uid, entity_key="MSFT",
            change_magnitude=0.0, run_override=True)
        assert s == 0.0

    @pytest.mark.asyncio
    async def test_null_session_zero(self):
        from app.services.personal_experience_attention_service import compute_revisit_score
        assert await compute_revisit_score(
            None, user_id=_uid(), entity_key="X",
            change_magnitude=0.5, run_override=True) == 0.0


# ---------------------------------------------------------------------------
# 34–37: Composite scoring
# ---------------------------------------------------------------------------

class TestCompositeScore:

    def test_all_zeros(self):
        from app.services.personal_experience_attention_service import compute_composite_score
        scores = {dim: 0.0 for dim in [
            "attention_priority", "personal_relevance", "recency_score",
            "novelty_score", "revisit_score", "memory_relevance",
            "portfolio_relevance",
        ]}
        assert compute_composite_score(scores) == 0.0

    def test_all_ones(self):
        from app.services.personal_experience_attention_service import compute_composite_score
        scores = {dim: 1.0 for dim in [
            "attention_priority", "personal_relevance", "recency_score",
            "novelty_score", "revisit_score", "memory_relevance",
            "portfolio_relevance",
        ]}
        assert compute_composite_score(scores) == pytest.approx(1.0, abs=0.01)

    def test_weighted_sum_correct(self):
        from app.services.personal_experience_attention_service import compute_composite_score
        scores = {
            "attention_priority": 1.0, "personal_relevance": 0.0,
            "recency_score": 0.0, "novelty_score": 0.0,
            "revisit_score": 0.0, "memory_relevance": 0.0,
            "portfolio_relevance": 0.0,
        }
        assert compute_composite_score(scores) == pytest.approx(0.25, abs=0.01)

    def test_invalid_weights_fallback(self):
        from app.services.personal_experience_attention_service import compute_composite_score
        scores = {dim: 1.0 for dim in [
            "attention_priority", "personal_relevance", "recency_score",
            "novelty_score", "revisit_score", "memory_relevance",
            "portfolio_relevance",
        ]}
        bad = {"attention_priority": 0.99}
        result = compute_composite_score(scores, bad)
        assert result == pytest.approx(1.0, abs=0.01)


# ---------------------------------------------------------------------------
# 38–41: score_change_candidate
# ---------------------------------------------------------------------------

class TestScoreCandidate:

    @pytest.mark.asyncio
    async def test_returns_all_dimensions(self, db):
        from app.services.personal_experience_attention_service import score_change_candidate
        uid = _uid()
        c = _make_candidate()
        result = await score_change_candidate(
            db, user_id=uid, candidate=c, run_override=True)
        for dim in ("attention_priority", "personal_relevance", "recency_score",
                     "novelty_score", "revisit_score", "memory_relevance",
                     "portfolio_relevance"):
            assert dim in result

    @pytest.mark.asyncio
    async def test_returns_composite(self, db):
        from app.services.personal_experience_attention_service import score_change_candidate
        result = await score_change_candidate(
            db, user_id=_uid(), candidate=_make_candidate(), run_override=True)
        assert "composite_score" in result

    @pytest.mark.asyncio
    async def test_flag_off_all_zeros(self, db):
        from app.services.personal_experience_attention_service import score_change_candidate
        result = await score_change_candidate(
            db, user_id=_uid(), candidate=_make_candidate(), run_override=False)
        assert result["composite_score"] == 0.0

    @pytest.mark.asyncio
    async def test_null_session_all_zeros(self):
        from app.services.personal_experience_attention_service import score_change_candidate
        result = await score_change_candidate(
            None, user_id=_uid(), candidate=_make_candidate(), run_override=True)
        assert result["composite_score"] == 0.0


# ---------------------------------------------------------------------------
# 42–46: rank_change_candidates
# ---------------------------------------------------------------------------

class TestRankCandidates:

    @pytest.mark.asyncio
    async def test_empty_list(self, db):
        from app.services.personal_experience_attention_service import rank_change_candidates
        result = await rank_change_candidates(
            db, user_id=_uid(), candidates=[], run_override=True)
        assert result == []

    @pytest.mark.asyncio
    async def test_sorted_by_composite_desc(self, db):
        from app.services.personal_experience_attention_service import rank_change_candidates
        uid = _uid()
        await _seed_decision(db, "AAPL", bucket="critical")
        await _seed_decision(db, "MSFT", bucket="low")
        candidates = [_make_candidate("AAPL"), _make_candidate("MSFT")]
        result = await rank_change_candidates(
            db, user_id=uid, candidates=candidates, run_override=True)
        if len(result) >= 2:
            assert result[0]["composite_score"] >= result[1]["composite_score"]

    @pytest.mark.asyncio
    async def test_deterministic(self, db):
        from app.services.personal_experience_attention_service import rank_change_candidates
        uid = _uid()
        candidates = [_make_candidate("A"), _make_candidate("B")]
        r1 = await rank_change_candidates(
            db, user_id=uid, candidates=candidates, run_override=True)
        r2 = await rank_change_candidates(
            db, user_id=uid, candidates=candidates, run_override=True)
        assert [x["entity_key"] for x in r1] == [x["entity_key"] for x in r2]

    @pytest.mark.asyncio
    async def test_flag_off_empty(self, db):
        from app.services.personal_experience_attention_service import rank_change_candidates
        result = await rank_change_candidates(
            db, user_id=_uid(), candidates=[_make_candidate()], run_override=False)
        assert result == []

    @pytest.mark.asyncio
    async def test_null_session_empty(self):
        from app.services.personal_experience_attention_service import rank_change_candidates
        result = await rank_change_candidates(
            None, user_id=_uid(), candidates=[_make_candidate()], run_override=True)
        assert result == []


# ---------------------------------------------------------------------------
# 47–49: Attention floor
# ---------------------------------------------------------------------------

class TestAttentionFloor:

    def test_urgent_items_in_top_5(self):
        from app.services.personal_experience_attention_service import apply_attention_floor
        items = []
        for i in range(10):
            items.append({
                "entity_key": f"item_{i}",
                "attention_priority": 0.9 if i == 7 else 0.1,
                "composite_score": 0.1 * i,
            })
        result = apply_attention_floor(items)
        urgent_positions = [idx for idx, r in enumerate(result)
                           if r["attention_priority"] > 0.8]
        assert all(pos < 5 for pos in urgent_positions)

    def test_non_urgent_below_urgent(self):
        from app.services.personal_experience_attention_service import apply_attention_floor
        items = [
            {"entity_key": "urgent", "attention_priority": 0.9, "composite_score": 0.3},
            {"entity_key": "normal", "attention_priority": 0.2, "composite_score": 0.9},
        ]
        result = apply_attention_floor(items)
        assert result[0]["entity_key"] == "urgent"

    def test_empty_list(self):
        from app.services.personal_experience_attention_service import apply_attention_floor
        assert apply_attention_floor([]) == []


# ---------------------------------------------------------------------------
# 50–52: Novelty reserve
# ---------------------------------------------------------------------------

class TestNoveltyReserve:

    def test_novel_items_get_reserved_slots(self):
        from app.services.personal_experience_attention_service import apply_novelty_reserve
        items = []
        for i in range(8):
            items.append({
                "entity_key": f"pref_{i}",
                "personal_relevance": 0.8,
                "composite_score": 0.5 + 0.01 * i,
            })
        items.append({
            "entity_key": "novel_1",
            "personal_relevance": 0.0,
            "composite_score": 0.1,
        })
        result = apply_novelty_reserve(items)
        reserved = [r for r in result if r.get("novelty_reserve_applied")]
        assert len(reserved) >= 1

    def test_under_min_items_no_reserve(self):
        from app.services.personal_experience_attention_service import apply_novelty_reserve
        items = [
            {"entity_key": "a", "personal_relevance": 0.8, "composite_score": 0.9},
            {"entity_key": "b", "personal_relevance": 0.0, "composite_score": 0.1},
        ]
        result = apply_novelty_reserve(items)
        reserved = [r for r in result if r.get("novelty_reserve_applied")]
        assert len(reserved) == 0

    def test_flag_set_on_reserved(self):
        from app.services.personal_experience_attention_service import apply_novelty_reserve
        items = []
        for i in range(6):
            items.append({
                "entity_key": f"p_{i}",
                "personal_relevance": 0.8,
                "composite_score": 0.5,
            })
        items.append({
            "entity_key": "novel",
            "personal_relevance": 0.0,
            "composite_score": 0.1,
        })
        result = apply_novelty_reserve(items)
        novel = [r for r in result if r["entity_key"] == "novel"]
        assert novel[0].get("novelty_reserve_applied") is True


# ---------------------------------------------------------------------------
# 53–57: AST safety
# ---------------------------------------------------------------------------

def _load_ast():
    return ast.parse(_SVC_PATH.read_text())


def _docstring_node_ids(tree):
    ids = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                             ast.AsyncFunctionDef)):
            if (node.body and isinstance(node.body[0], ast.Expr)
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


class TestAstSafety:

    def test_no_truth_table_write_imports(self):
        names = _import_names(_load_ast())
        for fn in ("add_forecast", "upsert_forecast", "add_decision",
                    "upsert_decision", "add_scenario", "upsert_scenario",
                    "add_similarity", "upsert_similarity",
                    "add_ticker_memory", "upsert_learned_preference"):
            assert fn not in names, f"forbidden import: {fn}"

    def test_no_conviction_imports(self):
        names = _import_names(_load_ast())
        for forbidden in ("conviction", "order_service", "execution_service"):
            for name in names:
                assert forbidden not in name.lower(), (
                    f"forbidden import: {name}")

    def test_no_banned_phrases(self):
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
                     "add_forecast", "add_decision"):
            assert bad not in call_attrs

    def test_no_notification_writes(self):
        names = _import_names(_load_ast())
        assert "Notification" not in names
        assert "add_notification" not in names
