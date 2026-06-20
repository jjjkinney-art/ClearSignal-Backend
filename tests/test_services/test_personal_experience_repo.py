"""
Tests — Personal Experience Repositories, Phase 18 · Slice 2.

Covers:
  1.  repo module importable
  2.  all 11 functions present

  --- null-session safety ---
  3.  upsert_experience_cursor(None) → None
  4.  get_experience_cursor(None) → None
  5.  list_experience_cursors(None) → []
  6.  count_experience_cursors(None) → 0
  7.  add_experience_event(None) → None
  8.  list_experience_events(None) → []
  9.  count_experience_events(None) → 0
  10. add_brief_snapshot(None) → None
  11. get_brief_snapshot(None) → None
  12. list_brief_snapshots(None) → []
  13. count_brief_snapshots(None) → 0

  --- cursor CRUD ---
  14. upsert_experience_cursor inserts new row
  15. upsert_experience_cursor updates existing row (same key)
  16. upsert_experience_cursor increments view_count on re-upsert
  17. upsert_experience_cursor updates last_state_hash
  18. get_experience_cursor returns row by unique key
  19. get_experience_cursor returns None for missing key
  20. list_experience_cursors returns all cursors for user
  21. list_experience_cursors filters by entity_type
  22. count_experience_cursors returns correct count
  23. count_experience_cursors filters by entity_type

  --- event CRUD ---
  24. add_experience_event inserts row
  25. add_experience_event stores all 7 scoring dimensions
  26. add_experience_event stores explanation fields
  27. add_experience_event stores run_reason
  28. add_experience_event stores surface
  29. list_experience_events returns events for user
  30. list_experience_events filters by surface
  31. list_experience_events filters by run_reason
  32. list_experience_events filters by explanation_valid
  33. list_experience_events filters by surfaced_after
  34. count_experience_events returns correct count
  35. count_experience_events filters by run_reason
  36. two add calls create two distinct rows (append-only)

  --- brief CRUD ---
  37. add_brief_snapshot inserts row
  38. add_brief_snapshot stores all fields
  39. get_brief_snapshot returns row by (user_id, brief_date)
  40. get_brief_snapshot returns None for missing key
  41. list_brief_snapshots returns briefs for user
  42. list_brief_snapshots filters by run_reason
  43. count_brief_snapshots returns correct count
  44. count_brief_snapshots filters by run_reason

  --- tenant isolation ---
  45. user A cursors invisible to user B list
  46. user A events invisible to user B count
  47. user A briefs invisible to user B list

  --- append-only invariant ---
  48. event table: no update function in repo
  49. event table: no delete function in repo
  50. two event add calls → two distinct IDs (never overwrites)

  --- AST safety ---
  51. no truth-table write imports in repo
  52. no forecast/similarity/scenario/decision repo imports
  53. no banned advisory phrases in non-docstring strings
  54. no update/delete on PersonalExperienceEvent in repo source

  --- source table non-mutation ---
  55. forecast_vector unchanged after repo operations
  56. learned_preference unchanged after repo operations
"""

from __future__ import annotations

import ast
import inspect
import pathlib
import uuid
from datetime import date, datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

_ROOT     = pathlib.Path(__file__).parent.parent.parent
_REPO_PATH = _ROOT / "app" / "db" / "repositories" / "personal_experience_repo.py"


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
# 1–2: Import and presence
# ---------------------------------------------------------------------------

class TestImportAndPresence:

    def test_repo_importable(self):
        import app.db.repositories.personal_experience_repo  # noqa: F401

    def test_all_functions_present(self):
        import app.db.repositories.personal_experience_repo as repo
        for fn in (
            "upsert_experience_cursor",
            "get_experience_cursor",
            "list_experience_cursors",
            "count_experience_cursors",
            "add_experience_event",
            "list_experience_events",
            "count_experience_events",
            "add_brief_snapshot",
            "get_brief_snapshot",
            "list_brief_snapshots",
            "count_brief_snapshots",
        ):
            assert callable(getattr(repo, fn, None)), f"missing: {fn}"


# ---------------------------------------------------------------------------
# 3–13: Null-session safety
# ---------------------------------------------------------------------------

class TestNullSession:

    @pytest.mark.asyncio
    async def test_upsert_cursor_null_session(self):
        from app.db.repositories.personal_experience_repo import upsert_experience_cursor
        assert await upsert_experience_cursor(
            None, user_id="u", entity_type="ticker", entity_key="AAPL") is None

    @pytest.mark.asyncio
    async def test_get_cursor_null_session(self):
        from app.db.repositories.personal_experience_repo import get_experience_cursor
        assert await get_experience_cursor(
            None, user_id="u", entity_type="ticker", entity_key="AAPL") is None

    @pytest.mark.asyncio
    async def test_list_cursors_null_session(self):
        from app.db.repositories.personal_experience_repo import list_experience_cursors
        assert await list_experience_cursors(None) == []

    @pytest.mark.asyncio
    async def test_count_cursors_null_session(self):
        from app.db.repositories.personal_experience_repo import count_experience_cursors
        assert await count_experience_cursors(None) == 0

    @pytest.mark.asyncio
    async def test_add_event_null_session(self):
        from app.db.repositories.personal_experience_repo import add_experience_event
        assert await add_experience_event(None, user_id="u") is None

    @pytest.mark.asyncio
    async def test_list_events_null_session(self):
        from app.db.repositories.personal_experience_repo import list_experience_events
        assert await list_experience_events(None) == []

    @pytest.mark.asyncio
    async def test_count_events_null_session(self):
        from app.db.repositories.personal_experience_repo import count_experience_events
        assert await count_experience_events(None) == 0

    @pytest.mark.asyncio
    async def test_add_brief_null_session(self):
        from app.db.repositories.personal_experience_repo import add_brief_snapshot
        assert await add_brief_snapshot(
            None, user_id="u", brief_date=date.today()) is None

    @pytest.mark.asyncio
    async def test_get_brief_null_session(self):
        from app.db.repositories.personal_experience_repo import get_brief_snapshot
        assert await get_brief_snapshot(
            None, user_id="u", brief_date=date.today()) is None

    @pytest.mark.asyncio
    async def test_list_briefs_null_session(self):
        from app.db.repositories.personal_experience_repo import list_brief_snapshots
        assert await list_brief_snapshots(None) == []

    @pytest.mark.asyncio
    async def test_count_briefs_null_session(self):
        from app.db.repositories.personal_experience_repo import count_brief_snapshots
        assert await count_brief_snapshots(None) == 0


# ---------------------------------------------------------------------------
# 14–23: Cursor CRUD
# ---------------------------------------------------------------------------

class TestCursorCrud:

    @pytest.mark.asyncio
    async def test_upsert_inserts_new(self, db):
        from app.db.repositories.personal_experience_repo import (
            upsert_experience_cursor, count_experience_cursors,
        )
        uid = _uid()
        row = await upsert_experience_cursor(
            db, user_id=uid, entity_type="ticker", entity_key="AAPL")
        assert row is not None
        assert row.view_count == 1
        assert await count_experience_cursors(db, user_id=uid) == 1

    @pytest.mark.asyncio
    async def test_upsert_updates_existing(self, db):
        from app.db.repositories.personal_experience_repo import (
            upsert_experience_cursor, count_experience_cursors,
        )
        uid = _uid()
        await upsert_experience_cursor(
            db, user_id=uid, entity_type="ticker", entity_key="AAPL",
            last_state_hash="hash_v1")
        await upsert_experience_cursor(
            db, user_id=uid, entity_type="ticker", entity_key="AAPL",
            last_state_hash="hash_v2")
        assert await count_experience_cursors(db, user_id=uid) == 1

    @pytest.mark.asyncio
    async def test_upsert_increments_view_count(self, db):
        from app.db.repositories.personal_experience_repo import (
            upsert_experience_cursor, get_experience_cursor,
        )
        uid = _uid()
        await upsert_experience_cursor(
            db, user_id=uid, entity_type="ticker", entity_key="MSFT")
        await upsert_experience_cursor(
            db, user_id=uid, entity_type="ticker", entity_key="MSFT")
        await upsert_experience_cursor(
            db, user_id=uid, entity_type="ticker", entity_key="MSFT")
        row = await get_experience_cursor(
            db, user_id=uid, entity_type="ticker", entity_key="MSFT")
        assert row is not None
        assert row.view_count == 3

    @pytest.mark.asyncio
    async def test_upsert_updates_state_hash(self, db):
        from app.db.repositories.personal_experience_repo import (
            upsert_experience_cursor, get_experience_cursor,
        )
        uid = _uid()
        await upsert_experience_cursor(
            db, user_id=uid, entity_type="ticker", entity_key="NVDA",
            last_state_hash="aaa")
        await upsert_experience_cursor(
            db, user_id=uid, entity_type="ticker", entity_key="NVDA",
            last_state_hash="bbb")
        row = await get_experience_cursor(
            db, user_id=uid, entity_type="ticker", entity_key="NVDA")
        assert row.last_state_hash == "bbb"

    @pytest.mark.asyncio
    async def test_get_returns_row(self, db):
        from app.db.repositories.personal_experience_repo import (
            upsert_experience_cursor, get_experience_cursor,
        )
        uid = _uid()
        await upsert_experience_cursor(
            db, user_id=uid, entity_type="scenario", entity_key="sc_001")
        row = await get_experience_cursor(
            db, user_id=uid, entity_type="scenario", entity_key="sc_001")
        assert row is not None
        assert row.entity_key == "sc_001"

    @pytest.mark.asyncio
    async def test_get_returns_none_for_missing(self, db):
        from app.db.repositories.personal_experience_repo import get_experience_cursor
        row = await get_experience_cursor(
            db, user_id=_uid(), entity_type="ticker", entity_key="MISSING")
        assert row is None

    @pytest.mark.asyncio
    async def test_list_returns_cursors_for_user(self, db):
        from app.db.repositories.personal_experience_repo import (
            upsert_experience_cursor, list_experience_cursors,
        )
        uid = _uid()
        await upsert_experience_cursor(
            db, user_id=uid, entity_type="ticker", entity_key="A")
        await upsert_experience_cursor(
            db, user_id=uid, entity_type="ticker", entity_key="B")
        rows = await list_experience_cursors(db, user_id=uid)
        assert len(rows) == 2

    @pytest.mark.asyncio
    async def test_list_filters_by_entity_type(self, db):
        from app.db.repositories.personal_experience_repo import (
            upsert_experience_cursor, list_experience_cursors,
        )
        uid = _uid()
        await upsert_experience_cursor(
            db, user_id=uid, entity_type="ticker", entity_key="AAPL")
        await upsert_experience_cursor(
            db, user_id=uid, entity_type="scenario", entity_key="sc_1")
        rows = await list_experience_cursors(
            db, user_id=uid, entity_type="scenario")
        assert len(rows) == 1
        assert rows[0].entity_type == "scenario"

    @pytest.mark.asyncio
    async def test_count_returns_correct(self, db):
        from app.db.repositories.personal_experience_repo import (
            upsert_experience_cursor, count_experience_cursors,
        )
        uid = _uid()
        await upsert_experience_cursor(
            db, user_id=uid, entity_type="ticker", entity_key="X")
        await upsert_experience_cursor(
            db, user_id=uid, entity_type="ticker", entity_key="Y")
        assert await count_experience_cursors(db, user_id=uid) == 2

    @pytest.mark.asyncio
    async def test_count_filters_by_entity_type(self, db):
        from app.db.repositories.personal_experience_repo import (
            upsert_experience_cursor, count_experience_cursors,
        )
        uid = _uid()
        await upsert_experience_cursor(
            db, user_id=uid, entity_type="ticker", entity_key="A")
        await upsert_experience_cursor(
            db, user_id=uid, entity_type="forecast", entity_key="B")
        assert await count_experience_cursors(
            db, user_id=uid, entity_type="forecast") == 1


# ---------------------------------------------------------------------------
# 24–36: Event CRUD
# ---------------------------------------------------------------------------

class TestEventCrud:

    @pytest.mark.asyncio
    async def test_add_inserts_row(self, db):
        from app.db.repositories.personal_experience_repo import (
            add_experience_event, count_experience_events,
        )
        uid = _uid()
        row = await add_experience_event(db, user_id=uid, surface="home")
        assert row is not None
        assert await count_experience_events(db, user_id=uid) == 1

    @pytest.mark.asyncio
    async def test_add_stores_all_dimensions(self, db):
        from app.db.repositories.personal_experience_repo import add_experience_event
        uid = _uid()
        row = await add_experience_event(
            db, user_id=uid,
            experience_score=0.9, attention_priority=0.8,
            personal_relevance=0.7, recency_score=0.6,
            novelty_score=0.5, revisit_score=0.4,
            memory_relevance=0.3, portfolio_relevance=0.2,
        )
        assert float(row.experience_score) == 0.9
        assert float(row.attention_priority) == 0.8
        assert float(row.personal_relevance) == 0.7
        assert float(row.recency_score) == 0.6
        assert float(row.novelty_score) == 0.5
        assert float(row.revisit_score) == 0.4
        assert float(row.memory_relevance) == 0.3
        assert float(row.portfolio_relevance) == 0.2

    @pytest.mark.asyncio
    async def test_add_stores_explanation(self, db):
        from app.db.repositories.personal_experience_repo import add_experience_event
        uid = _uid()
        row = await add_experience_event(
            db, user_id=uid,
            explanation_text="test reason",
            explanation_valid=True,
        )
        assert row.explanation_text == "test reason"
        assert row.explanation_valid is True

    @pytest.mark.asyncio
    async def test_add_stores_run_reason(self, db):
        from app.db.repositories.personal_experience_repo import add_experience_event
        row = await add_experience_event(
            db, user_id=_uid(), run_reason="shadow")
        assert row.run_reason == "shadow"

    @pytest.mark.asyncio
    async def test_add_stores_surface(self, db):
        from app.db.repositories.personal_experience_repo import add_experience_event
        row = await add_experience_event(
            db, user_id=_uid(), surface="brief")
        assert row.surface == "brief"

    @pytest.mark.asyncio
    async def test_list_returns_events(self, db):
        from app.db.repositories.personal_experience_repo import (
            add_experience_event, list_experience_events,
        )
        uid = _uid()
        await add_experience_event(db, user_id=uid, surface="home")
        await add_experience_event(db, user_id=uid, surface="brief")
        rows = await list_experience_events(db, user_id=uid)
        assert len(rows) == 2

    @pytest.mark.asyncio
    async def test_list_filters_by_surface(self, db):
        from app.db.repositories.personal_experience_repo import (
            add_experience_event, list_experience_events,
        )
        uid = _uid()
        await add_experience_event(db, user_id=uid, surface="home")
        await add_experience_event(db, user_id=uid, surface="brief")
        rows = await list_experience_events(db, user_id=uid, surface="brief")
        assert len(rows) == 1

    @pytest.mark.asyncio
    async def test_list_filters_by_run_reason(self, db):
        from app.db.repositories.personal_experience_repo import (
            add_experience_event, list_experience_events,
        )
        uid = _uid()
        await add_experience_event(db, user_id=uid, run_reason="shadow")
        rows = await list_experience_events(
            db, user_id=uid, run_reason="shadow")
        assert len(rows) == 1

    @pytest.mark.asyncio
    async def test_list_filters_by_explanation_valid(self, db):
        from app.db.repositories.personal_experience_repo import (
            add_experience_event, list_experience_events,
        )
        uid = _uid()
        await add_experience_event(
            db, user_id=uid, explanation_valid=True)
        await add_experience_event(
            db, user_id=uid, explanation_valid=False)
        rows = await list_experience_events(
            db, user_id=uid, explanation_valid=True)
        assert len(rows) == 1

    @pytest.mark.asyncio
    async def test_list_filters_by_surfaced_after(self, db):
        from app.db.repositories.personal_experience_repo import (
            add_experience_event, list_experience_events,
        )
        uid = _uid()
        old = _now() - timedelta(hours=2)
        recent = _now()
        await add_experience_event(db, user_id=uid, surfaced_at=old)
        await add_experience_event(db, user_id=uid, surfaced_at=recent)
        cutoff = _now() - timedelta(hours=1)
        rows = await list_experience_events(
            db, user_id=uid, surfaced_after=cutoff)
        assert len(rows) == 1

    @pytest.mark.asyncio
    async def test_count_returns_correct(self, db):
        from app.db.repositories.personal_experience_repo import (
            add_experience_event, count_experience_events,
        )
        uid = _uid()
        await add_experience_event(db, user_id=uid)
        await add_experience_event(db, user_id=uid)
        await add_experience_event(db, user_id=uid)
        assert await count_experience_events(db, user_id=uid) == 3

    @pytest.mark.asyncio
    async def test_count_filters_by_run_reason(self, db):
        from app.db.repositories.personal_experience_repo import (
            add_experience_event, count_experience_events,
        )
        uid = _uid()
        await add_experience_event(db, user_id=uid, run_reason="shadow")
        await add_experience_event(db, user_id=uid, run_reason="shadow")
        assert await count_experience_events(
            db, user_id=uid, run_reason="shadow") == 2

    @pytest.mark.asyncio
    async def test_two_adds_create_distinct_rows(self, db):
        from app.db.repositories.personal_experience_repo import add_experience_event
        uid = _uid()
        r1 = await add_experience_event(db, user_id=uid, item_ref="a")
        r2 = await add_experience_event(db, user_id=uid, item_ref="b")
        assert r1.id != r2.id


# ---------------------------------------------------------------------------
# 37–44: Brief CRUD
# ---------------------------------------------------------------------------

class TestBriefCrud:

    @pytest.mark.asyncio
    async def test_add_inserts_row(self, db):
        from app.db.repositories.personal_experience_repo import (
            add_brief_snapshot, count_brief_snapshots,
        )
        uid = _uid()
        row = await add_brief_snapshot(
            db, user_id=uid, brief_date=date(2026, 6, 20))
        assert row is not None
        assert await count_brief_snapshots(db, user_id=uid) == 1

    @pytest.mark.asyncio
    async def test_add_stores_all_fields(self, db):
        from app.db.repositories.personal_experience_repo import add_brief_snapshot
        uid = _uid()
        row = await add_brief_snapshot(
            db, user_id=uid, brief_date=date(2026, 6, 20),
            brief_schema=1, items_surfaced=5, items_blocked=2,
            top_attention_item="AAPL_forecast", run_reason="shadow",
        )
        assert row.items_surfaced == 5
        assert row.items_blocked == 2
        assert row.top_attention_item == "AAPL_forecast"
        assert row.run_reason == "shadow"

    @pytest.mark.asyncio
    async def test_get_returns_row(self, db):
        from app.db.repositories.personal_experience_repo import (
            add_brief_snapshot, get_brief_snapshot,
        )
        uid = _uid()
        d = date(2026, 6, 21)
        await add_brief_snapshot(db, user_id=uid, brief_date=d)
        row = await get_brief_snapshot(db, user_id=uid, brief_date=d)
        assert row is not None

    @pytest.mark.asyncio
    async def test_get_returns_none_for_missing(self, db):
        from app.db.repositories.personal_experience_repo import get_brief_snapshot
        row = await get_brief_snapshot(
            db, user_id=_uid(), brief_date=date(2026, 1, 1))
        assert row is None

    @pytest.mark.asyncio
    async def test_list_returns_briefs(self, db):
        from app.db.repositories.personal_experience_repo import (
            add_brief_snapshot, list_brief_snapshots,
        )
        uid = _uid()
        await add_brief_snapshot(db, user_id=uid, brief_date=date(2026, 6, 1))
        await add_brief_snapshot(db, user_id=uid, brief_date=date(2026, 6, 2))
        rows = await list_brief_snapshots(db, user_id=uid)
        assert len(rows) == 2

    @pytest.mark.asyncio
    async def test_list_filters_by_run_reason(self, db):
        from app.db.repositories.personal_experience_repo import (
            add_brief_snapshot, list_brief_snapshots,
        )
        uid = _uid()
        await add_brief_snapshot(
            db, user_id=uid, brief_date=date(2026, 6, 1), run_reason="shadow")
        rows = await list_brief_snapshots(db, user_id=uid, run_reason="shadow")
        assert len(rows) == 1

    @pytest.mark.asyncio
    async def test_count_returns_correct(self, db):
        from app.db.repositories.personal_experience_repo import (
            add_brief_snapshot, count_brief_snapshots,
        )
        uid = _uid()
        await add_brief_snapshot(db, user_id=uid, brief_date=date(2026, 7, 1))
        await add_brief_snapshot(db, user_id=uid, brief_date=date(2026, 7, 2))
        assert await count_brief_snapshots(db, user_id=uid) == 2

    @pytest.mark.asyncio
    async def test_count_filters_by_run_reason(self, db):
        from app.db.repositories.personal_experience_repo import (
            add_brief_snapshot, count_brief_snapshots,
        )
        uid = _uid()
        await add_brief_snapshot(
            db, user_id=uid, brief_date=date(2026, 7, 3), run_reason="shadow")
        assert await count_brief_snapshots(
            db, user_id=uid, run_reason="shadow") == 1


# ---------------------------------------------------------------------------
# 45–47: Tenant isolation
# ---------------------------------------------------------------------------

class TestTenantIsolation:

    @pytest.mark.asyncio
    async def test_cursor_isolation(self, db):
        from app.db.repositories.personal_experience_repo import (
            upsert_experience_cursor, list_experience_cursors,
        )
        uid_a, uid_b = _uid(), _uid()
        await upsert_experience_cursor(
            db, user_id=uid_a, entity_type="ticker", entity_key="AAPL")
        rows = await list_experience_cursors(db, user_id=uid_b)
        assert len(rows) == 0

    @pytest.mark.asyncio
    async def test_event_isolation(self, db):
        from app.db.repositories.personal_experience_repo import (
            add_experience_event, count_experience_events,
        )
        uid_a, uid_b = _uid(), _uid()
        await add_experience_event(db, user_id=uid_a, surface="home")
        assert await count_experience_events(db, user_id=uid_b) == 0

    @pytest.mark.asyncio
    async def test_brief_isolation(self, db):
        from app.db.repositories.personal_experience_repo import (
            add_brief_snapshot, list_brief_snapshots,
        )
        uid_a, uid_b = _uid(), _uid()
        await add_brief_snapshot(
            db, user_id=uid_a, brief_date=date(2026, 6, 20))
        rows = await list_brief_snapshots(db, user_id=uid_b)
        assert len(rows) == 0


# ---------------------------------------------------------------------------
# 48–50: Append-only invariant
# ---------------------------------------------------------------------------

class TestAppendOnly:

    def test_no_update_function_for_events(self):
        import app.db.repositories.personal_experience_repo as repo
        for name in dir(repo):
            if "event" in name.lower():
                assert "update" not in name.lower(), (
                    f"event update function found: {name}")

    def test_no_delete_function_for_events(self):
        import app.db.repositories.personal_experience_repo as repo
        for name in dir(repo):
            if "event" in name.lower():
                assert "delete" not in name.lower(), (
                    f"event delete function found: {name}")

    @pytest.mark.asyncio
    async def test_two_adds_create_two_rows(self, db):
        from app.db.repositories.personal_experience_repo import (
            add_experience_event, count_experience_events,
        )
        uid = _uid()
        await add_experience_event(db, user_id=uid, item_ref="x")
        await add_experience_event(db, user_id=uid, item_ref="x")
        assert await count_experience_events(db, user_id=uid) == 2


# ---------------------------------------------------------------------------
# 51–54: AST safety
# ---------------------------------------------------------------------------

def _load_repo_ast():
    return ast.parse(_REPO_PATH.read_text())


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

_FORBIDDEN_REPO_IMPORTS = (
    "forecast_repo", "decision_repo", "scenario_repo",
    "similarity_repo", "user_learning_repo",
)


class TestAstSafety:

    def test_no_truth_table_write_imports(self):
        names = _import_names(_load_repo_ast())
        for fn in _TRUTH_WRITE_FNS:
            assert fn not in names, f"forbidden import: {fn}"

    def test_no_forbidden_repo_imports(self):
        names = _import_names(_load_repo_ast())
        for forbidden in _FORBIDDEN_REPO_IMPORTS:
            for name in names:
                assert forbidden not in name.lower(), (
                    f"forbidden repo import contains '{forbidden}': {name}")

    def test_no_banned_advisory_phrases(self):
        tree = _load_repo_ast()
        doc_ids = _docstring_node_ids(tree)
        for node in ast.walk(tree):
            if (isinstance(node, ast.Constant)
                    and isinstance(node.value, str)
                    and id(node) not in doc_ids):
                low = node.value.lower()
                for phrase in _BANNED_PHRASES:
                    assert phrase not in low, (
                        f"banned phrase '{phrase}' in: {node.value!r}")

    def test_no_update_delete_on_event_table(self):
        src = _REPO_PATH.read_text()
        tree = ast.parse(src)
        call_attrs = set()
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)):
                call_attrs.add(node.func.attr)
        for bad in ("update", "delete"):
            if bad in call_attrs:
                for node in ast.walk(tree):
                    if (isinstance(node, ast.Call)
                            and isinstance(node.func, ast.Attribute)
                            and node.func.attr == bad):
                        context = ast.unparse(node)
                        assert "ExperienceEvent" not in context, (
                            f"{bad} on ExperienceEvent found")


# ---------------------------------------------------------------------------
# 55–56: Source table non-mutation
# ---------------------------------------------------------------------------

class TestSourceTableNonMutation:

    @pytest.mark.asyncio
    async def test_forecast_vector_unchanged(self, db):
        from app.db.repositories.personal_experience_repo import (
            add_experience_event, upsert_experience_cursor,
        )
        from sqlalchemy import select, func
        from app.db.models import ForecastVector

        before = (await db.execute(
            select(func.count()).select_from(ForecastVector))).scalar_one()

        uid = _uid()
        await upsert_experience_cursor(
            db, user_id=uid, entity_type="ticker", entity_key="X")
        await add_experience_event(db, user_id=uid, surface="home")

        after = (await db.execute(
            select(func.count()).select_from(ForecastVector))).scalar_one()
        assert before == after == 0

    @pytest.mark.asyncio
    async def test_learned_preference_unchanged(self, db):
        from app.db.repositories.personal_experience_repo import (
            add_experience_event, upsert_experience_cursor,
        )
        from sqlalchemy import select, func
        from app.db.models import LearnedPreference

        before = (await db.execute(
            select(func.count()).select_from(LearnedPreference))).scalar_one()

        uid = _uid()
        await upsert_experience_cursor(
            db, user_id=uid, entity_type="ticker", entity_key="Y")
        await add_experience_event(db, user_id=uid, surface="brief")

        after = (await db.execute(
            select(func.count()).select_from(LearnedPreference))).scalar_one()
        assert before == after == 0
