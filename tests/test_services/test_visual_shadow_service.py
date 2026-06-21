"""
Tests — Visual Shadow Journal, Phase 19 · Slice 10.

Covers all 5 transition types, blocked/fallback paths, deduplication,
null-session safety, append-only behavior, and AST safety.
"""

from __future__ import annotations

import ast
import pathlib

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

_ROOT = pathlib.Path(__file__).parent.parent.parent
_SRC  = _ROOT / "app" / "services" / "visual_shadow_service.py"

_USER = "u-vs-1"


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


def _spec(
    *, visual_type="forecast_distribution", entity_key="AAPL",
    rendering_tier="json", explanation_valid=True, evidence_refs=None,
    title="AAPL Forecast", blocked_reason="", is_fallback=False,
    fallback_reason="",
):
    s = {
        "visual_type":       visual_type,
        "entity_key":        entity_key,
        "rendering_tier":    rendering_tier,
        "explanation_valid": explanation_valid,
        "evidence_refs":     evidence_refs if evidence_refs is not None else ["e:1"],
        "title":             title,
        "blocked_reason":    blocked_reason,
    }
    if is_fallback:
        s["is_fallback"] = True
        s["fallback_reason"] = fallback_reason
    return s


# ===================================================================
# § classify_visual_transition
# ===================================================================

class TestClassify:
    def test_created(self):
        from app.services.visual_shadow_service import classify_visual_transition
        assert classify_visual_transition(_spec()) == "visual_created"

    def test_updated(self):
        from app.services.visual_shadow_service import classify_visual_transition
        cur = _spec(evidence_refs=["e:1", "e:2"])
        prev = _spec(evidence_refs=["e:1"])
        assert classify_visual_transition(cur, prev) == "visual_updated"

    def test_removed(self):
        from app.services.visual_shadow_service import classify_visual_transition
        assert classify_visual_transition(None, _spec()) == "visual_removed"

    def test_blocked(self):
        from app.services.visual_shadow_service import classify_visual_transition
        cur = _spec(explanation_valid=False, blocked_reason="no evidence")
        assert classify_visual_transition(cur) == "visual_blocked"

    def test_fallback_used(self):
        from app.services.visual_shadow_service import classify_visual_transition
        cur = _spec(is_fallback=True, fallback_reason="ai_disabled")
        assert classify_visual_transition(cur) == "visual_fallback_used"

    def test_no_change(self):
        from app.services.visual_shadow_service import classify_visual_transition
        s = _spec()
        assert classify_visual_transition(s, s) is None

    def test_fallback_priority_over_blocked(self):
        from app.services.visual_shadow_service import classify_visual_transition
        cur = _spec(explanation_valid=False, is_fallback=True, fallback_reason="x")
        assert classify_visual_transition(cur) == "visual_fallback_used"


# ===================================================================
# § detect_visual_transitions
# ===================================================================

class TestDetect:
    def test_new_specs_created(self):
        from app.services.visual_shadow_service import detect_visual_transitions
        result = detect_visual_transitions([_spec(entity_key="AAPL"), _spec(entity_key="MSFT")])
        assert len(result) == 2
        assert all(t["transition_type"] == "visual_created" for t in result)

    def test_removed_detected(self):
        from app.services.visual_shadow_service import detect_visual_transitions
        prev = [_spec(entity_key="AAPL")]
        result = detect_visual_transitions([], prev)
        assert len(result) == 1
        assert result[0]["transition_type"] == "visual_removed"

    def test_updated_detected(self):
        from app.services.visual_shadow_service import detect_visual_transitions
        cur = [_spec(entity_key="AAPL", evidence_refs=["e:1", "e:2"])]
        prev = [_spec(entity_key="AAPL", evidence_refs=["e:1"])]
        result = detect_visual_transitions(cur, prev)
        assert len(result) == 1
        assert result[0]["transition_type"] == "visual_updated"

    def test_blocked_detected(self):
        from app.services.visual_shadow_service import detect_visual_transitions
        cur = [_spec(explanation_valid=False, blocked_reason="no evidence")]
        result = detect_visual_transitions(cur)
        assert result[0]["transition_type"] == "visual_blocked"
        assert result[0]["explanation_valid"] is False

    def test_fallback_detected(self):
        from app.services.visual_shadow_service import detect_visual_transitions
        cur = [_spec(is_fallback=True, fallback_reason="ai_disabled")]
        result = detect_visual_transitions(cur)
        assert result[0]["transition_type"] == "visual_fallback_used"
        assert "fallback_used" in result[0]["blocked_reason"]

    def test_no_change_no_transition(self):
        from app.services.visual_shadow_service import detect_visual_transitions
        s = _spec()
        assert detect_visual_transitions([s], [s]) == []

    def test_mixed(self):
        from app.services.visual_shadow_service import detect_visual_transitions
        cur = [
            _spec(entity_key="AAPL", evidence_refs=["e:1", "e:2"]),  # updated
            _spec(entity_key="GOOG"),                                # created
        ]
        prev = [
            _spec(entity_key="AAPL", evidence_refs=["e:1"]),
            _spec(entity_key="MSFT"),                                # removed
        ]
        result = detect_visual_transitions(cur, prev)
        by_key = {t["entity_key"]: t["transition_type"] for t in result}
        assert by_key["AAPL"] == "visual_updated"
        assert by_key["GOOG"] == "visual_created"
        assert by_key["MSFT"] == "visual_removed"


# ===================================================================
# § record_visual_events
# ===================================================================

class TestRecord:
    @pytest.mark.asyncio
    async def test_journals_rows(self, db):
        from app.services.visual_shadow_service import record_visual_events
        from app.db.repositories.visual_intelligence_repo import count_visual_events
        transitions = [
            {"visual_type": "forecast_distribution", "entity_key": "AAPL",
             "rendering_tier": "json", "transition_type": "visual_created",
             "explanation_valid": True, "blocked_reason": ""},
            {"visual_type": "similarity_network", "entity_key": "MSFT",
             "rendering_tier": "svg", "transition_type": "visual_created",
             "explanation_valid": True, "blocked_reason": ""},
        ]
        rows = await record_visual_events(db, user_id=_USER, transitions=transitions, run_override=True)
        assert len(rows) == 2
        await db.commit()
        assert await count_visual_events(db, user_id=_USER) == 2

    @pytest.mark.asyncio
    async def test_blocked_row_has_reason(self, db):
        from app.services.visual_shadow_service import record_visual_events
        transitions = [
            {"visual_type": "price_chart", "entity_key": "AAPL",
             "rendering_tier": "json", "transition_type": "visual_blocked",
             "explanation_valid": False, "blocked_reason": "missing evidence"},
        ]
        rows = await record_visual_events(db, user_id=_USER, transitions=transitions, run_override=True)
        assert len(rows) == 1
        assert rows[0].explanation_valid is False
        assert rows[0].blocked_reason == "missing evidence"

    @pytest.mark.asyncio
    async def test_fallback_row(self, db):
        from app.services.visual_shadow_service import record_visual_events
        transitions = [
            {"visual_type": "ecosystem_map", "entity_key": "NVDA",
             "rendering_tier": "json", "transition_type": "visual_fallback_used",
             "explanation_valid": False, "blocked_reason": "fallback_used:ai_disabled"},
        ]
        rows = await record_visual_events(db, user_id=_USER, transitions=transitions, run_override=True)
        assert "fallback_used" in rows[0].blocked_reason

    @pytest.mark.asyncio
    async def test_dedup_within_window(self, db):
        from app.services.visual_shadow_service import record_visual_events
        t = [{"visual_type": "forecast_distribution", "entity_key": "AAPL",
              "rendering_tier": "json", "transition_type": "visual_created",
              "explanation_valid": True, "blocked_reason": ""}]
        r1 = await record_visual_events(db, user_id=_USER, transitions=t, run_override=True)
        assert len(r1) == 1
        r2 = await record_visual_events(db, user_id=_USER, transitions=t, run_override=True)
        assert len(r2) == 0

    @pytest.mark.asyncio
    async def test_dedup_within_batch(self, db):
        from app.services.visual_shadow_service import record_visual_events
        t = [
            {"visual_type": "v", "entity_key": "AAPL", "rendering_tier": "json",
             "transition_type": "visual_created", "explanation_valid": True, "blocked_reason": ""},
            {"visual_type": "v", "entity_key": "AAPL", "rendering_tier": "json",
             "transition_type": "visual_created", "explanation_valid": True, "blocked_reason": ""},
        ]
        rows = await record_visual_events(db, user_id=_USER, transitions=t, run_override=True)
        assert len(rows) == 1

    @pytest.mark.asyncio
    async def test_run_reason_shadow(self, db):
        from app.services.visual_shadow_service import record_visual_events
        t = [{"visual_type": "v", "entity_key": "AAPL", "rendering_tier": "json",
              "transition_type": "visual_created", "explanation_valid": True, "blocked_reason": ""}]
        rows = await record_visual_events(db, user_id=_USER, transitions=t, run_override=True)
        assert rows[0].run_reason == "shadow"

    @pytest.mark.asyncio
    async def test_flag_off_returns_empty(self, db):
        from app.services.visual_shadow_service import record_visual_events
        t = [{"visual_type": "v", "entity_key": "AAPL", "rendering_tier": "json",
              "transition_type": "visual_created", "explanation_valid": True, "blocked_reason": ""}]
        rows = await record_visual_events(db, user_id=_USER, transitions=t, run_override=False)
        assert rows == []

    @pytest.mark.asyncio
    async def test_no_transitions_returns_empty(self, db):
        from app.services.visual_shadow_service import record_visual_events
        rows = await record_visual_events(db, user_id=_USER, transitions=[], run_override=True)
        assert rows == []

    @pytest.mark.asyncio
    async def test_null_session(self):
        from app.services.visual_shadow_service import record_visual_events
        t = [{"visual_type": "v", "entity_key": "AAPL", "rendering_tier": "json",
              "transition_type": "visual_created", "explanation_valid": True, "blocked_reason": ""}]
        rows = await record_visual_events(None, user_id=_USER, transitions=t, run_override=True)
        assert rows == []


# ===================================================================
# § AST safety
# ===================================================================

class TestASTSafety:
    def _source(self) -> str:
        return _SRC.read_text()

    def _tree(self) -> ast.Module:
        return ast.parse(self._source())

    def test_module_importable(self):
        import app.services.visual_shadow_service  # noqa: F401

    def test_no_banned_phrases(self):
        tree = self._tree()
        exempt_ids: set = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                                 ast.ClassDef, ast.Module)):
                body = getattr(node, "body", [])
                if (body and isinstance(body[0], ast.Expr)
                        and isinstance(body[0].value, ast.Constant)):
                    exempt_ids.add(id(body[0].value))

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
                if id(node) in exempt_ids:
                    continue
                low = node.value.lower()
                for phrase in banned:
                    if phrase in low:
                        violations.append(
                            f"Line ~{getattr(node, 'lineno', '?')}: "
                            f"'{phrase}' in: {node.value[:80]!r}"
                        )
        assert not violations, "\n".join(violations)

    def test_no_upstream_truth_imports(self):
        tree = self._tree()
        banned_modules = [
            "forecast_repo", "decision_repo", "scenario_repo",
            "similarity_repo", "user_learning_repo", "portfolio_repo",
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

    def test_append_only_no_update_delete(self):
        source = self._source()
        for pattern in [".update(", ".delete(", "DELETE FROM", "UPDATE "]:
            assert pattern not in source, (
                f"Shadow journal must be append-only — found '{pattern}'"
            )

    def test_no_notification_imports(self):
        tree = self._tree()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                assert "notification" not in node.module.lower()
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert "notification" not in alias.name.lower()
