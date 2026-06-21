"""
Tests — Visual Intelligence Repository, Phase 19 · Slice 2.

Covers:
  1.  upsert_visual_spec: insert new row
  2.  upsert_visual_spec: update existing row (same unique key)
  3.  get_visual_spec: returns matching row
  4.  get_visual_spec: returns None when not found
  5.  list_visual_specs: returns matching rows
  6.  list_visual_specs: filters by user_id
  7.  list_visual_specs: filters by visual_type
  8.  list_visual_specs: filters by entity_key
  9.  list_visual_specs: ordered by generated_at desc
  10. count_visual_specs: returns correct count
  11. count_visual_specs: filters by user_id
  12. add_visual_event: inserts event row
  13. add_visual_event: run_reason defaults to shadow
  14. list_visual_events: returns matching rows
  15. list_visual_events: filters by user_id
  16. list_visual_events: filters by visual_type
  17. list_visual_events: filters by run_reason
  18. list_visual_events: filters by surfaced_after
  19. count_visual_events: returns correct count
  20. add_ai_visual_log: inserts log row
  21. add_ai_visual_log: stores prompt_hash not prompt_text
  22. add_ai_visual_log: run_reason defaults to shadow
  23. list_ai_visual_logs: returns matching rows
  24. list_ai_visual_logs: filters by user_id
  25. count_ai_visual_logs: returns correct count
  26. Null session: all functions safe
  27. Tenant isolation: user A data not visible to user B
  28. AST: append-only for events (no .update/.delete)
  29. AST: append-only for AI log (no .update/.delete)
  30. AST: no upstream truth-table imports
  31. AST: module importable
  32. AST: no banned phrases
"""

from __future__ import annotations

import ast
import pathlib
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

_ROOT = pathlib.Path(__file__).parent.parent.parent
_SRC  = _ROOT / "app" / "db" / "repositories" / "visual_intelligence_repo.py"

_USER_A = "u-vis-a"
_USER_B = "u-vis-b"


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


# ===================================================================
# § VisualSpecCache
# ===================================================================

class TestUpsertVisualSpec:
    @pytest.mark.asyncio
    async def test_insert_new_row(self, db):
        from app.db.repositories.visual_intelligence_repo import upsert_visual_spec
        row = await upsert_visual_spec(
            db, user_id=_USER_A, visual_type="forecast_distribution",
            entity_key="AAPL", data_hash="abc123", spec_json='{"test":1}',
        )
        assert row is not None
        assert row.visual_type == "forecast_distribution"
        assert row.entity_key == "AAPL"
        assert row.spec_json == '{"test":1}'
        assert row.run_reason == "shadow"

    @pytest.mark.asyncio
    async def test_update_existing_row(self, db):
        from app.db.repositories.visual_intelligence_repo import upsert_visual_spec
        r1 = await upsert_visual_spec(
            db, user_id=_USER_A, visual_type="test",
            entity_key="AAPL", data_hash="hash1", spec_json='{"v":1}',
        )
        r2 = await upsert_visual_spec(
            db, user_id=_USER_A, visual_type="test",
            entity_key="AAPL", data_hash="hash1", spec_json='{"v":2}',
        )
        assert r2 is not None
        assert r2.spec_json == '{"v":2}'
        assert r1.id == r2.id


class TestGetVisualSpec:
    @pytest.mark.asyncio
    async def test_returns_matching_row(self, db):
        from app.db.repositories.visual_intelligence_repo import (
            upsert_visual_spec, get_visual_spec,
        )
        await upsert_visual_spec(
            db, user_id=_USER_A, visual_type="test",
            entity_key="MSFT", data_hash="h1",
        )
        row = await get_visual_spec(
            db, user_id=_USER_A, visual_type="test",
            entity_key="MSFT", data_hash="h1",
        )
        assert row is not None
        assert row.entity_key == "MSFT"

    @pytest.mark.asyncio
    async def test_returns_none_when_not_found(self, db):
        from app.db.repositories.visual_intelligence_repo import get_visual_spec
        row = await get_visual_spec(
            db, user_id=_USER_A, visual_type="nope",
            entity_key="NONE", data_hash="x",
        )
        assert row is None


class TestListVisualSpecs:
    @pytest.mark.asyncio
    async def test_returns_matching_rows(self, db):
        from app.db.repositories.visual_intelligence_repo import (
            upsert_visual_spec, list_visual_specs,
        )
        await upsert_visual_spec(
            db, user_id=_USER_A, visual_type="t1",
            entity_key="AAPL", data_hash="h1",
        )
        await upsert_visual_spec(
            db, user_id=_USER_A, visual_type="t2",
            entity_key="MSFT", data_hash="h2",
        )
        rows = await list_visual_specs(db, user_id=_USER_A)
        assert len(rows) == 2

    @pytest.mark.asyncio
    async def test_filters_by_user_id(self, db):
        from app.db.repositories.visual_intelligence_repo import (
            upsert_visual_spec, list_visual_specs,
        )
        await upsert_visual_spec(
            db, user_id=_USER_A, visual_type="t1",
            entity_key="AAPL", data_hash="h1",
        )
        await upsert_visual_spec(
            db, user_id=_USER_B, visual_type="t1",
            entity_key="AAPL", data_hash="h1",
        )
        rows = await list_visual_specs(db, user_id=_USER_A)
        assert len(rows) == 1

    @pytest.mark.asyncio
    async def test_filters_by_visual_type(self, db):
        from app.db.repositories.visual_intelligence_repo import (
            upsert_visual_spec, list_visual_specs,
        )
        await upsert_visual_spec(
            db, user_id=_USER_A, visual_type="forecast",
            entity_key="AAPL", data_hash="h1",
        )
        await upsert_visual_spec(
            db, user_id=_USER_A, visual_type="scenario",
            entity_key="MSFT", data_hash="h2",
        )
        rows = await list_visual_specs(db, user_id=_USER_A, visual_type="forecast")
        assert len(rows) == 1
        assert rows[0].visual_type == "forecast"

    @pytest.mark.asyncio
    async def test_filters_by_entity_key(self, db):
        from app.db.repositories.visual_intelligence_repo import (
            upsert_visual_spec, list_visual_specs,
        )
        await upsert_visual_spec(
            db, user_id=_USER_A, visual_type="t1",
            entity_key="AAPL", data_hash="h1",
        )
        await upsert_visual_spec(
            db, user_id=_USER_A, visual_type="t1",
            entity_key="MSFT", data_hash="h2",
        )
        rows = await list_visual_specs(db, user_id=_USER_A, entity_key="AAPL")
        assert len(rows) == 1


class TestCountVisualSpecs:
    @pytest.mark.asyncio
    async def test_returns_correct_count(self, db):
        from app.db.repositories.visual_intelligence_repo import (
            upsert_visual_spec, count_visual_specs,
        )
        await upsert_visual_spec(
            db, user_id=_USER_A, visual_type="t1",
            entity_key="AAPL", data_hash="h1",
        )
        await upsert_visual_spec(
            db, user_id=_USER_A, visual_type="t2",
            entity_key="MSFT", data_hash="h2",
        )
        count = await count_visual_specs(db, user_id=_USER_A)
        assert count == 2

    @pytest.mark.asyncio
    async def test_filters_by_user_id(self, db):
        from app.db.repositories.visual_intelligence_repo import (
            upsert_visual_spec, count_visual_specs,
        )
        await upsert_visual_spec(
            db, user_id=_USER_A, visual_type="t1",
            entity_key="AAPL", data_hash="h1",
        )
        await upsert_visual_spec(
            db, user_id=_USER_B, visual_type="t1",
            entity_key="AAPL", data_hash="h1",
        )
        assert await count_visual_specs(db, user_id=_USER_A) == 1
        assert await count_visual_specs(db, user_id=_USER_B) == 1


# ===================================================================
# § VisualExperienceEvent
# ===================================================================

class TestAddVisualEvent:
    @pytest.mark.asyncio
    async def test_inserts_event_row(self, db):
        from app.db.repositories.visual_intelligence_repo import add_visual_event
        row = await add_visual_event(
            db, user_id=_USER_A, visual_type="forecast_distribution",
            entity_key="AAPL", rendering_tier="json", generation_ms=50,
        )
        assert row is not None
        assert row.visual_type == "forecast_distribution"
        assert row.generation_ms == 50

    @pytest.mark.asyncio
    async def test_run_reason_defaults_shadow(self, db):
        from app.db.repositories.visual_intelligence_repo import add_visual_event
        row = await add_visual_event(
            db, user_id=_USER_A, visual_type="test",
        )
        assert row.run_reason == "shadow"


class TestListVisualEvents:
    @pytest.mark.asyncio
    async def test_returns_matching_rows(self, db):
        from app.db.repositories.visual_intelligence_repo import (
            add_visual_event, list_visual_events,
        )
        await add_visual_event(db, user_id=_USER_A, visual_type="t1")
        await add_visual_event(db, user_id=_USER_A, visual_type="t2")
        rows = await list_visual_events(db, user_id=_USER_A)
        assert len(rows) == 2

    @pytest.mark.asyncio
    async def test_filters_by_user_id(self, db):
        from app.db.repositories.visual_intelligence_repo import (
            add_visual_event, list_visual_events,
        )
        await add_visual_event(db, user_id=_USER_A, visual_type="t1")
        await add_visual_event(db, user_id=_USER_B, visual_type="t1")
        rows = await list_visual_events(db, user_id=_USER_A)
        assert len(rows) == 1

    @pytest.mark.asyncio
    async def test_filters_by_visual_type(self, db):
        from app.db.repositories.visual_intelligence_repo import (
            add_visual_event, list_visual_events,
        )
        await add_visual_event(db, user_id=_USER_A, visual_type="forecast")
        await add_visual_event(db, user_id=_USER_A, visual_type="scenario")
        rows = await list_visual_events(db, user_id=_USER_A, visual_type="forecast")
        assert len(rows) == 1

    @pytest.mark.asyncio
    async def test_filters_by_run_reason(self, db):
        from app.db.repositories.visual_intelligence_repo import (
            add_visual_event, list_visual_events,
        )
        await add_visual_event(db, user_id=_USER_A, run_reason="shadow")
        await add_visual_event(db, user_id=_USER_A, run_reason="calibration")
        rows = await list_visual_events(db, user_id=_USER_A, run_reason="shadow")
        assert len(rows) == 1

    @pytest.mark.asyncio
    async def test_filters_by_surfaced_after(self, db):
        from app.db.repositories.visual_intelligence_repo import (
            add_visual_event, list_visual_events,
        )
        old = datetime.now(timezone.utc) - timedelta(hours=2)
        await add_visual_event(db, user_id=_USER_A, surfaced_at=old)
        await add_visual_event(db, user_id=_USER_A)
        cutoff = datetime.now(timezone.utc) - timedelta(hours=1)
        rows = await list_visual_events(db, user_id=_USER_A, surfaced_after=cutoff)
        assert len(rows) == 1


class TestCountVisualEvents:
    @pytest.mark.asyncio
    async def test_returns_correct_count(self, db):
        from app.db.repositories.visual_intelligence_repo import (
            add_visual_event, count_visual_events,
        )
        await add_visual_event(db, user_id=_USER_A, visual_type="t1")
        await add_visual_event(db, user_id=_USER_A, visual_type="t2")
        count = await count_visual_events(db, user_id=_USER_A)
        assert count == 2


# ===================================================================
# § AIVisualGenerationLog
# ===================================================================

class TestAddAIVisualLog:
    @pytest.mark.asyncio
    async def test_inserts_log_row(self, db):
        from app.db.repositories.visual_intelligence_repo import add_ai_visual_log
        row = await add_ai_visual_log(
            db, user_id=_USER_A, visual_type="ecosystem_map",
            entity_key="NVDA", prompt_hash="sha256abc",
            generation_model="test-model", generation_ms=3000,
            validation_passed=True,
        )
        assert row is not None
        assert row.prompt_hash == "sha256abc"
        assert row.generation_model == "test-model"

    @pytest.mark.asyncio
    async def test_stores_prompt_hash_not_text(self, db):
        from app.db.repositories.visual_intelligence_repo import add_ai_visual_log
        row = await add_ai_visual_log(
            db, user_id=_USER_A, prompt_hash="deadbeef",
        )
        assert row.prompt_hash == "deadbeef"
        assert not hasattr(row, "prompt_text")

    @pytest.mark.asyncio
    async def test_run_reason_defaults_shadow(self, db):
        from app.db.repositories.visual_intelligence_repo import add_ai_visual_log
        row = await add_ai_visual_log(db, user_id=_USER_A)
        assert row.run_reason == "shadow"

    @pytest.mark.asyncio
    async def test_banned_phrases_stored(self, db):
        from app.db.repositories.visual_intelligence_repo import add_ai_visual_log
        row = await add_ai_visual_log(
            db, user_id=_USER_A, validation_passed=False,
            validation_reason="banned phrase detected",
            banned_phrases_found="target price",
        )
        assert row.banned_phrases_found == "target price"
        assert row.validation_passed is False


class TestListAIVisualLogs:
    @pytest.mark.asyncio
    async def test_returns_matching_rows(self, db):
        from app.db.repositories.visual_intelligence_repo import (
            add_ai_visual_log, list_ai_visual_logs,
        )
        await add_ai_visual_log(db, user_id=_USER_A, visual_type="t1")
        await add_ai_visual_log(db, user_id=_USER_A, visual_type="t2")
        rows = await list_ai_visual_logs(db, user_id=_USER_A)
        assert len(rows) == 2

    @pytest.mark.asyncio
    async def test_filters_by_user_id(self, db):
        from app.db.repositories.visual_intelligence_repo import (
            add_ai_visual_log, list_ai_visual_logs,
        )
        await add_ai_visual_log(db, user_id=_USER_A)
        await add_ai_visual_log(db, user_id=_USER_B)
        rows = await list_ai_visual_logs(db, user_id=_USER_A)
        assert len(rows) == 1


class TestCountAIVisualLogs:
    @pytest.mark.asyncio
    async def test_returns_correct_count(self, db):
        from app.db.repositories.visual_intelligence_repo import (
            add_ai_visual_log, count_ai_visual_logs,
        )
        await add_ai_visual_log(db, user_id=_USER_A)
        await add_ai_visual_log(db, user_id=_USER_A)
        count = await count_ai_visual_logs(db, user_id=_USER_A)
        assert count == 2


# ===================================================================
# § Null session
# ===================================================================

class TestNullSession:
    @pytest.mark.asyncio
    async def test_upsert_visual_spec_none(self):
        from app.db.repositories.visual_intelligence_repo import upsert_visual_spec
        assert await upsert_visual_spec(
            None, user_id="x", visual_type="t", entity_key="k", data_hash="h",
        ) is None

    @pytest.mark.asyncio
    async def test_get_visual_spec_none(self):
        from app.db.repositories.visual_intelligence_repo import get_visual_spec
        assert await get_visual_spec(
            None, user_id="x", visual_type="t", entity_key="k", data_hash="h",
        ) is None

    @pytest.mark.asyncio
    async def test_list_visual_specs_none(self):
        from app.db.repositories.visual_intelligence_repo import list_visual_specs
        assert await list_visual_specs(None) == []

    @pytest.mark.asyncio
    async def test_count_visual_specs_none(self):
        from app.db.repositories.visual_intelligence_repo import count_visual_specs
        assert await count_visual_specs(None) == 0

    @pytest.mark.asyncio
    async def test_add_visual_event_none(self):
        from app.db.repositories.visual_intelligence_repo import add_visual_event
        assert await add_visual_event(None, user_id="x") is None

    @pytest.mark.asyncio
    async def test_list_visual_events_none(self):
        from app.db.repositories.visual_intelligence_repo import list_visual_events
        assert await list_visual_events(None) == []

    @pytest.mark.asyncio
    async def test_count_visual_events_none(self):
        from app.db.repositories.visual_intelligence_repo import count_visual_events
        assert await count_visual_events(None) == 0

    @pytest.mark.asyncio
    async def test_add_ai_visual_log_none(self):
        from app.db.repositories.visual_intelligence_repo import add_ai_visual_log
        assert await add_ai_visual_log(None, user_id="x") is None

    @pytest.mark.asyncio
    async def test_list_ai_visual_logs_none(self):
        from app.db.repositories.visual_intelligence_repo import list_ai_visual_logs
        assert await list_ai_visual_logs(None) == []

    @pytest.mark.asyncio
    async def test_count_ai_visual_logs_none(self):
        from app.db.repositories.visual_intelligence_repo import count_ai_visual_logs
        assert await count_ai_visual_logs(None) == 0


# ===================================================================
# § Tenant isolation
# ===================================================================

class TestTenantIsolation:
    @pytest.mark.asyncio
    async def test_spec_cache_isolated(self, db):
        from app.db.repositories.visual_intelligence_repo import (
            upsert_visual_spec, list_visual_specs,
        )
        await upsert_visual_spec(
            db, user_id=_USER_A, visual_type="t", entity_key="X", data_hash="h",
        )
        await upsert_visual_spec(
            db, user_id=_USER_B, visual_type="t", entity_key="Y", data_hash="h",
        )
        a_rows = await list_visual_specs(db, user_id=_USER_A)
        b_rows = await list_visual_specs(db, user_id=_USER_B)
        assert len(a_rows) == 1
        assert len(b_rows) == 1
        assert a_rows[0].entity_key == "X"
        assert b_rows[0].entity_key == "Y"

    @pytest.mark.asyncio
    async def test_events_isolated(self, db):
        from app.db.repositories.visual_intelligence_repo import (
            add_visual_event, list_visual_events,
        )
        await add_visual_event(db, user_id=_USER_A, visual_type="t1")
        await add_visual_event(db, user_id=_USER_B, visual_type="t2")
        a_rows = await list_visual_events(db, user_id=_USER_A)
        b_rows = await list_visual_events(db, user_id=_USER_B)
        assert len(a_rows) == 1
        assert len(b_rows) == 1

    @pytest.mark.asyncio
    async def test_ai_logs_isolated(self, db):
        from app.db.repositories.visual_intelligence_repo import (
            add_ai_visual_log, list_ai_visual_logs,
        )
        await add_ai_visual_log(db, user_id=_USER_A)
        await add_ai_visual_log(db, user_id=_USER_B)
        a_rows = await list_ai_visual_logs(db, user_id=_USER_A)
        b_rows = await list_ai_visual_logs(db, user_id=_USER_B)
        assert len(a_rows) == 1
        assert len(b_rows) == 1


# ===================================================================
# § AST safety
# ===================================================================

class TestASTSafety:
    def _source(self) -> str:
        return _SRC.read_text()

    def _tree(self) -> ast.Module:
        return ast.parse(self._source())

    def test_module_importable(self):
        import app.db.repositories.visual_intelligence_repo  # noqa: F401

    def test_append_only_events_no_update_delete(self):
        source = self._source()
        lines = source.split("\n")
        in_event_section = False
        for line in lines:
            if "VISUAL EXPERIENCE EVENT" in line:
                in_event_section = True
            if "AI VISUAL GENERATION LOG" in line:
                in_event_section = False
            if in_event_section:
                for pattern in [".update(", ".delete("]:
                    assert pattern not in line, (
                        f"Event section must be append-only: {pattern} in {line.strip()}"
                    )

    def test_append_only_ai_log_no_update_delete(self):
        source = self._source()
        lines = source.split("\n")
        in_ai_section = False
        for line in lines:
            if "AI VISUAL GENERATION LOG" in line:
                in_ai_section = True
            if in_ai_section:
                for pattern in [".update(", ".delete("]:
                    assert pattern not in line, (
                        f"AI log section must be append-only: {pattern} in {line.strip()}"
                    )

    def test_no_upstream_truth_imports(self):
        tree = self._tree()
        banned_modules = [
            "forecast_repo", "decision_repo", "scenario_repo",
            "similarity_repo", "user_learning_repo",
            "personal_experience_repo", "conviction", "order",
            "execution", "stance",
        ]
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                mod = node.module
                for banned in banned_modules:
                    assert banned not in mod, (
                        f"Banned import from {mod} (contains '{banned}')"
                    )

    def test_no_banned_phrases(self):
        tree = self._tree()

        docstring_node_ids: set = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                                 ast.ClassDef, ast.Module)):
                body = getattr(node, "body", [])
                if (body and isinstance(body[0], ast.Expr)
                        and isinstance(body[0].value, ast.Constant)):
                    docstring_node_ids.add(id(body[0].value))

        banned = [
            "buy", "sell",
            "overweight", "underweight", "recommend",
            "target price", "position size",
            "take a position", "enter a trade", "exit a trade",
            "place an order", "execute",
            "short", "long position",
            "go long", "go short",
            "open a position", "close a position",
        ]
        violations: list = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if id(node) in docstring_node_ids:
                    continue
                val_lower = node.value.lower()
                for phrase in banned:
                    if phrase in val_lower:
                        violations.append(
                            f"Line ~{getattr(node, 'lineno', '?')}: "
                            f"'{phrase}' in: {node.value[:80]!r}"
                        )
        assert not violations, "\n".join(violations)
