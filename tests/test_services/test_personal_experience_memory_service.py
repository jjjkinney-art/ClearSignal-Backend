"""
Tests — Personal Experience Memory Context + Session Continuity, Phase 18 · Slice 6.

Covers:
  1.  service importable
  2.  all public functions present

  --- compute_continuation_score (pure) ---
  3.  zero view_count → 0.0
  4.  high engagement + high change → high score
  5.  high engagement + no change → low score
  6.  always in [0, 1]
  7.  recency bonus increases score

  --- get_last_research_context ---
  8.  no history → None
  9.  one cursor → returns that entity
  10. multiple cursors → returns most recent
  11. context has required fields
  12. flag off → None
  13. null session → None

  --- get_recent_research_contexts ---
  14. no history → []
  15. multiple cursors → ordered newest first
  16. respects limit
  17. flag off → []
  18. null session → []

  --- build_resume_candidates ---
  19. no cursors → []
  20. cursor with change → changed_since_last_seen True
  21. cursor without change → changed_since_last_seen False
  22. has continuation_score
  23. sorted by continuation_score desc
  24. respects limit
  25. flag off → []
  26. null session → []

  --- build_revisit_candidates ---
  27. no memory changes → []
  28. updated memory → revisit candidate
  29. candidate has continuation_score
  30. flag off → []
  31. null session → []

  --- build_session_continuity ---
  32. empty → structurally complete
  33. populated → last_research present
  34. populated → resume_candidates present
  35. has generated_at
  36. flag off → empty structure
  37. null session → empty structure

  --- build_welcome_back_context ---
  38. no history → last_researched_entity None
  39. with history → last_researched_entity set
  40. changed_items_count reflects changes
  41. top_resume_candidate set when changes exist
  42. revisit_candidates present
  43. flag off → empty structure
  44. null session → empty structure

  --- AST safety ---
  45. no truth-table write imports
  46. no conviction/order/execution imports
  47. no banned advisory phrases
  48. no upstream mutation calls
  49. no Notification writes
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
_SVC_PATH = _ROOT / "app" / "services" / "personal_experience_memory_service.py"


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

async def _seed_cursor(db, user_id, entity_key, entity_type="ticker",
                        state_hash="h", last_seen_at=None, view_count=1):
    from app.db.repositories.personal_experience_repo import upsert_experience_cursor
    seen = last_seen_at or _now()
    row = await upsert_experience_cursor(
        db, user_id=user_id, entity_type=entity_type,
        entity_key=entity_key, last_state_hash=state_hash,
        last_seen_at=seen,
    )
    for _ in range(view_count - 1):
        await upsert_experience_cursor(
            db, user_id=user_id, entity_type=entity_type,
            entity_key=entity_key, last_state_hash=state_hash,
            last_seen_at=seen,
        )
    return row


async def _seed_forecast(db, entity_key):
    from app.db.models import ForecastVector
    row = ForecastVector(
        id=_uid(), entity_type="company", entity_key=entity_key,
        horizon="near_term", horizon_days=30,
        forecast_type="thesis_strengthening",
        p_positive=0.6, p_negative=0.2, p_neutral=0.2,
        why="test", forecast_schema=1,
        built_at=_now(), expires_at=_now() + timedelta(hours=72),
    )
    db.add(row)
    await db.flush()
    return row


async def _seed_ticker_memory(db, ticker, updated_at=None):
    from app.db.models import TickerMemory
    row = TickerMemory(
        id=_uid(), ticker=ticker, company_name=f"{ticker} Inc",
        total_queries=5, version_count=3,
        last_stance="cautious", last_confidence=0.6,
        dominant_concern="valuation",
        updated_at=updated_at or _now(),
    )
    db.add(row)
    await db.flush()
    return row


# ---------------------------------------------------------------------------
# 1–2: Import and presence
# ---------------------------------------------------------------------------

class TestImportAndPresence:

    def test_importable(self):
        import app.services.personal_experience_memory_service  # noqa: F401

    def test_all_functions_present(self):
        import app.services.personal_experience_memory_service as svc
        for fn in (
            "get_last_research_context",
            "get_recent_research_contexts",
            "build_resume_candidates",
            "build_revisit_candidates",
            "compute_continuation_score",
            "build_session_continuity",
            "build_welcome_back_context",
        ):
            assert callable(getattr(svc, fn, None)), f"missing: {fn}"


# ---------------------------------------------------------------------------
# 3–7: compute_continuation_score
# ---------------------------------------------------------------------------

class TestContinuationScore:

    def test_zero_view_count(self):
        from app.services.personal_experience_memory_service import compute_continuation_score
        s = compute_continuation_score(view_count=0, change_magnitude=1.0)
        assert s == 0.0

    def test_high_engagement_high_change(self):
        from app.services.personal_experience_memory_service import compute_continuation_score
        s = compute_continuation_score(view_count=10, change_magnitude=1.0, recency_score=1.0)
        assert s > 0.8

    def test_high_engagement_no_change(self):
        from app.services.personal_experience_memory_service import compute_continuation_score
        s = compute_continuation_score(view_count=10, change_magnitude=0.0, recency_score=0.0)
        assert s == 0.0

    def test_always_in_range(self):
        from app.services.personal_experience_memory_service import compute_continuation_score
        for vc in [0, 1, 5, 10, 100]:
            for mag in [0.0, 0.5, 1.0]:
                for rec in [0.0, 0.5, 1.0]:
                    s = compute_continuation_score(
                        view_count=vc, change_magnitude=mag, recency_score=rec)
                    assert 0.0 <= s <= 1.0

    def test_recency_bonus(self):
        from app.services.personal_experience_memory_service import compute_continuation_score
        low = compute_continuation_score(view_count=5, change_magnitude=0.5, recency_score=0.0)
        high = compute_continuation_score(view_count=5, change_magnitude=0.5, recency_score=1.0)
        assert high > low


# ---------------------------------------------------------------------------
# 8–13: get_last_research_context
# ---------------------------------------------------------------------------

class TestLastResearchContext:

    @pytest.mark.asyncio
    async def test_no_history_none(self, db):
        from app.services.personal_experience_memory_service import get_last_research_context
        result = await get_last_research_context(db, user_id=_uid(), run_override=True)
        assert result is None

    @pytest.mark.asyncio
    async def test_one_cursor_returns_entity(self, db):
        from app.services.personal_experience_memory_service import get_last_research_context
        uid = _uid()
        await _seed_cursor(db, uid, "AAPL")
        result = await get_last_research_context(db, user_id=uid, run_override=True)
        assert result is not None
        assert result["entity_key"] == "AAPL"

    @pytest.mark.asyncio
    async def test_multiple_returns_most_recent(self, db):
        from app.services.personal_experience_memory_service import get_last_research_context
        uid = _uid()
        await _seed_cursor(db, uid, "OLD", last_seen_at=_now() - timedelta(hours=48))
        await _seed_cursor(db, uid, "NEW", last_seen_at=_now())
        result = await get_last_research_context(db, user_id=uid, run_override=True)
        assert result["entity_key"] == "NEW"

    @pytest.mark.asyncio
    async def test_context_has_required_fields(self, db):
        from app.services.personal_experience_memory_service import get_last_research_context
        uid = _uid()
        await _seed_cursor(db, uid, "MSFT")
        result = await get_last_research_context(db, user_id=uid, run_override=True)
        for key in ("entity_key", "entity_type", "last_seen_at",
                     "last_state_hash", "view_count", "surface"):
            assert key in result

    @pytest.mark.asyncio
    async def test_flag_off_none(self, db):
        from app.services.personal_experience_memory_service import get_last_research_context
        uid = _uid()
        await _seed_cursor(db, uid, "X")
        result = await get_last_research_context(db, user_id=uid, run_override=False)
        assert result is None

    @pytest.mark.asyncio
    async def test_null_session_none(self):
        from app.services.personal_experience_memory_service import get_last_research_context
        result = await get_last_research_context(None, user_id=_uid(), run_override=True)
        assert result is None


# ---------------------------------------------------------------------------
# 14–18: get_recent_research_contexts
# ---------------------------------------------------------------------------

class TestRecentResearchContexts:

    @pytest.mark.asyncio
    async def test_no_history_empty(self, db):
        from app.services.personal_experience_memory_service import get_recent_research_contexts
        result = await get_recent_research_contexts(db, user_id=_uid(), run_override=True)
        assert result == []

    @pytest.mark.asyncio
    async def test_ordered_newest_first(self, db):
        from app.services.personal_experience_memory_service import get_recent_research_contexts
        uid = _uid()
        await _seed_cursor(db, uid, "OLD", last_seen_at=_now() - timedelta(hours=48))
        await _seed_cursor(db, uid, "NEW", last_seen_at=_now())
        result = await get_recent_research_contexts(db, user_id=uid, run_override=True)
        assert result[0]["entity_key"] == "NEW"

    @pytest.mark.asyncio
    async def test_respects_limit(self, db):
        from app.services.personal_experience_memory_service import get_recent_research_contexts
        uid = _uid()
        for i in range(5):
            await _seed_cursor(db, uid, f"T{i}",
                                last_seen_at=_now() - timedelta(hours=i))
        result = await get_recent_research_contexts(
            db, user_id=uid, limit=2, run_override=True)
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_flag_off_empty(self, db):
        from app.services.personal_experience_memory_service import get_recent_research_contexts
        uid = _uid()
        await _seed_cursor(db, uid, "X")
        result = await get_recent_research_contexts(db, user_id=uid, run_override=False)
        assert result == []

    @pytest.mark.asyncio
    async def test_null_session_empty(self):
        from app.services.personal_experience_memory_service import get_recent_research_contexts
        result = await get_recent_research_contexts(None, user_id=_uid(), run_override=True)
        assert result == []


# ---------------------------------------------------------------------------
# 19–26: build_resume_candidates
# ---------------------------------------------------------------------------

class TestResumeCandidates:

    @pytest.mark.asyncio
    async def test_no_cursors_empty(self, db):
        from app.services.personal_experience_memory_service import build_resume_candidates
        result = await build_resume_candidates(db, user_id=_uid(), run_override=True)
        assert result == []

    @pytest.mark.asyncio
    async def test_cursor_with_change_flagged(self, db):
        from app.services.personal_experience_memory_service import build_resume_candidates
        uid = _uid()
        # research history for AAPL + a forecast change (no forecast cursor)
        await _seed_cursor(db, uid, "AAPL", entity_type="ticker", view_count=3)
        await _seed_forecast(db, "AAPL")
        result = await build_resume_candidates(db, user_id=uid, run_override=True)
        aapl = [r for r in result if r["entity_key"] == "AAPL"]
        assert len(aapl) == 1
        assert aapl[0]["changed_since_last_seen"] is True

    @pytest.mark.asyncio
    async def test_cursor_without_change_not_flagged(self, db):
        from app.services.personal_experience_memory_service import build_resume_candidates
        uid = _uid()
        # research history but no upstream change of any kind
        await _seed_cursor(db, uid, "QUIET", entity_type="ticker",
                            last_seen_at=_now() + timedelta(hours=1))
        result = await build_resume_candidates(db, user_id=uid, run_override=True)
        quiet = [r for r in result if r["entity_key"] == "QUIET"]
        assert len(quiet) == 1
        assert quiet[0]["changed_since_last_seen"] is False

    @pytest.mark.asyncio
    async def test_has_continuation_score(self, db):
        from app.services.personal_experience_memory_service import build_resume_candidates
        uid = _uid()
        await _seed_cursor(db, uid, "AAPL", view_count=3)
        await _seed_forecast(db, "AAPL")
        result = await build_resume_candidates(db, user_id=uid, run_override=True)
        assert "continuation_score" in result[0]
        assert 0.0 <= result[0]["continuation_score"] <= 1.0

    @pytest.mark.asyncio
    async def test_sorted_by_continuation_desc(self, db):
        from app.services.personal_experience_memory_service import build_resume_candidates
        uid = _uid()
        # changed + engaged entity should outrank quiet entity
        await _seed_cursor(db, uid, "HOT", entity_type="ticker", view_count=5)
        await _seed_forecast(db, "HOT")
        await _seed_cursor(db, uid, "COLD", entity_type="ticker", view_count=1,
                            last_seen_at=_now() + timedelta(hours=1))
        result = await build_resume_candidates(db, user_id=uid, run_override=True)
        if len(result) >= 2:
            assert result[0]["continuation_score"] >= result[-1]["continuation_score"]

    @pytest.mark.asyncio
    async def test_respects_limit(self, db):
        from app.services.personal_experience_memory_service import build_resume_candidates
        uid = _uid()
        for i in range(6):
            await _seed_cursor(db, uid, f"T{i}", entity_type="ticker")
        result = await build_resume_candidates(
            db, user_id=uid, limit=3, run_override=True)
        assert len(result) <= 3

    @pytest.mark.asyncio
    async def test_flag_off_empty(self, db):
        from app.services.personal_experience_memory_service import build_resume_candidates
        uid = _uid()
        await _seed_cursor(db, uid, "X")
        result = await build_resume_candidates(db, user_id=uid, run_override=False)
        assert result == []

    @pytest.mark.asyncio
    async def test_null_session_empty(self):
        from app.services.personal_experience_memory_service import build_resume_candidates
        result = await build_resume_candidates(None, user_id=_uid(), run_override=True)
        assert result == []


# ---------------------------------------------------------------------------
# 27–31: build_revisit_candidates
# ---------------------------------------------------------------------------

class TestRevisitCandidates:

    @pytest.mark.asyncio
    async def test_no_memory_changes_empty(self, db):
        from app.services.personal_experience_memory_service import build_revisit_candidates
        result = await build_revisit_candidates(db, user_id=_uid(), run_override=True)
        assert result == []

    @pytest.mark.asyncio
    async def test_updated_memory_returns_candidate(self, db):
        from app.services.personal_experience_memory_service import build_revisit_candidates
        uid = _uid()
        await _seed_cursor(db, uid, "AAPL", entity_type="ticker",
                            last_seen_at=_now() - timedelta(hours=48), view_count=3)
        await _seed_ticker_memory(db, "AAPL", updated_at=_now())
        result = await build_revisit_candidates(db, user_id=uid, run_override=True)
        assert len(result) >= 1
        assert result[0]["entity_key"] == "AAPL"

    @pytest.mark.asyncio
    async def test_candidate_has_continuation_score(self, db):
        from app.services.personal_experience_memory_service import build_revisit_candidates
        uid = _uid()
        await _seed_cursor(db, uid, "MSFT", entity_type="ticker",
                            last_seen_at=_now() - timedelta(hours=48), view_count=3)
        await _seed_ticker_memory(db, "MSFT", updated_at=_now())
        result = await build_revisit_candidates(db, user_id=uid, run_override=True)
        assert "continuation_score" in result[0]

    @pytest.mark.asyncio
    async def test_flag_off_empty(self, db):
        from app.services.personal_experience_memory_service import build_revisit_candidates
        result = await build_revisit_candidates(db, user_id=_uid(), run_override=False)
        assert result == []

    @pytest.mark.asyncio
    async def test_null_session_empty(self):
        from app.services.personal_experience_memory_service import build_revisit_candidates
        result = await build_revisit_candidates(None, user_id=_uid(), run_override=True)
        assert result == []


# ---------------------------------------------------------------------------
# 32–37: build_session_continuity
# ---------------------------------------------------------------------------

class TestSessionContinuity:

    @pytest.mark.asyncio
    async def test_empty_structurally_complete(self, db):
        from app.services.personal_experience_memory_service import build_session_continuity
        result = await build_session_continuity(db, user_id=_uid(), run_override=True)
        for key in ("last_research", "recent_research", "resume_candidates",
                     "revisit_candidates", "generated_at"):
            assert key in result

    @pytest.mark.asyncio
    async def test_populated_last_research(self, db):
        from app.services.personal_experience_memory_service import build_session_continuity
        uid = _uid()
        await _seed_cursor(db, uid, "AAPL")
        result = await build_session_continuity(db, user_id=uid, run_override=True)
        assert result["last_research"] is not None
        assert result["last_research"]["entity_key"] == "AAPL"

    @pytest.mark.asyncio
    async def test_populated_resume_candidates(self, db):
        from app.services.personal_experience_memory_service import build_session_continuity
        uid = _uid()
        await _seed_cursor(db, uid, "AAPL", view_count=3)
        await _seed_forecast(db, "AAPL")
        result = await build_session_continuity(db, user_id=uid, run_override=True)
        assert len(result["resume_candidates"]) >= 1

    @pytest.mark.asyncio
    async def test_has_generated_at(self, db):
        from app.services.personal_experience_memory_service import build_session_continuity
        result = await build_session_continuity(db, user_id=_uid(), run_override=True)
        assert isinstance(result["generated_at"], str)

    @pytest.mark.asyncio
    async def test_flag_off_empty(self, db):
        from app.services.personal_experience_memory_service import build_session_continuity
        uid = _uid()
        await _seed_cursor(db, uid, "X")
        result = await build_session_continuity(db, user_id=uid, run_override=False)
        assert result["last_research"] is None
        assert result["resume_candidates"] == []

    @pytest.mark.asyncio
    async def test_null_session_empty(self):
        from app.services.personal_experience_memory_service import build_session_continuity
        result = await build_session_continuity(None, user_id=_uid(), run_override=True)
        assert result["last_research"] is None


# ---------------------------------------------------------------------------
# 38–44: build_welcome_back_context
# ---------------------------------------------------------------------------

class TestWelcomeBackContext:

    @pytest.mark.asyncio
    async def test_no_history_none_entity(self, db):
        from app.services.personal_experience_memory_service import build_welcome_back_context
        result = await build_welcome_back_context(db, user_id=_uid(), run_override=True)
        assert result["last_researched_entity"] is None

    @pytest.mark.asyncio
    async def test_with_history_entity_set(self, db):
        from app.services.personal_experience_memory_service import build_welcome_back_context
        uid = _uid()
        await _seed_cursor(db, uid, "AAPL")
        result = await build_welcome_back_context(db, user_id=uid, run_override=True)
        assert result["last_researched_entity"] == "AAPL"

    @pytest.mark.asyncio
    async def test_changed_items_count(self, db):
        from app.services.personal_experience_memory_service import build_welcome_back_context
        uid = _uid()
        await _seed_cursor(db, uid, "AAPL", view_count=3)
        await _seed_forecast(db, "AAPL")
        result = await build_welcome_back_context(db, user_id=uid, run_override=True)
        assert result["changed_items_count"] >= 1

    @pytest.mark.asyncio
    async def test_top_resume_candidate_set(self, db):
        from app.services.personal_experience_memory_service import build_welcome_back_context
        uid = _uid()
        await _seed_cursor(db, uid, "AAPL", view_count=3)
        await _seed_forecast(db, "AAPL")
        result = await build_welcome_back_context(db, user_id=uid, run_override=True)
        assert result["top_resume_candidate"] is not None
        assert result["top_resume_candidate"]["entity_key"] == "AAPL"

    @pytest.mark.asyncio
    async def test_revisit_candidates_present(self, db):
        from app.services.personal_experience_memory_service import build_welcome_back_context
        result = await build_welcome_back_context(db, user_id=_uid(), run_override=True)
        assert isinstance(result["revisit_candidates"], list)

    @pytest.mark.asyncio
    async def test_flag_off_empty(self, db):
        from app.services.personal_experience_memory_service import build_welcome_back_context
        uid = _uid()
        await _seed_cursor(db, uid, "X")
        result = await build_welcome_back_context(db, user_id=uid, run_override=False)
        assert result["last_researched_entity"] is None

    @pytest.mark.asyncio
    async def test_null_session_empty(self):
        from app.services.personal_experience_memory_service import build_welcome_back_context
        result = await build_welcome_back_context(None, user_id=_uid(), run_override=True)
        assert result["last_researched_entity"] is None


# ---------------------------------------------------------------------------
# 45–49: AST safety
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
                assert forbidden not in name.lower(), f"forbidden: {name}"

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
