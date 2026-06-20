"""
Tests — Personal Experience Shadow Journal, Phase 18 · Slice 8.

Covers:
  1.  classify_experience_transition: new item (no previous)
  2.  classify_experience_transition: entity_key changed
  3.  classify_experience_transition: score changed
  4.  classify_experience_transition: change_type changed
  5.  classify_experience_transition: no material change → None
  6.  classify_experience_transition: new item without change_type → None
  7.  detect_experience_transitions: new items detected
  8.  detect_experience_transitions: removed items detected
  9.  detect_experience_transitions: mixed new + removed + changed
  10. detect_experience_transitions: no transitions when identical
  11. detect_experience_transitions: empty current + empty previous
  12. detect_experience_transitions: empty current + populated previous
  13. detect_experience_transitions: populated current + empty previous
  14. record_experience_events: inserts event rows
  15. record_experience_events: deduplicates within window
  16. record_experience_events: different scores not deduped
  17. record_experience_events: returns [] when flag off
  18. record_experience_events: returns [] when session None
  19. record_experience_events: returns [] when no transitions
  20. record_experience_events: run_reason is always shadow
  21. record_experience_events: all 7 scoring dimensions stored
  22. AST: no banned phrases in source
  23. AST: no upstream truth-table imports
  24. AST: module is importable
  25. AST: append-only (no .update/.delete in module)
  26. AST: no notification imports
  27. Null-session: all async functions safe
"""

from __future__ import annotations

import ast
import pathlib
from datetime import date, datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

_ROOT = pathlib.Path(__file__).parent.parent.parent
_SRC  = _ROOT / "app" / "services" / "personal_experience_shadow_service.py"

_USER = "u-shadow-test"


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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _item(
    *,
    entity_key: str = "AAPL",
    entity_type: str = "company",
    change_type: str = "forecast_changed",
    composite_score: float = 0.7,
    surface: str = "shadow",
    explanation_text: str = "Forecast changed.",
    explanation_valid: bool = True,
    attention_priority: float = 0.8,
    personal_relevance: float = 0.5,
    recency_score: float = 0.6,
    novelty_score: float = 0.4,
    revisit_score: float = 0.3,
    memory_relevance: float = 0.2,
    portfolio_relevance: float = 0.1,
) -> dict:
    return {
        "entity_key":         entity_key,
        "entity_type":        entity_type,
        "change_type":        change_type,
        "composite_score":    composite_score,
        "surface":            surface,
        "explanation_text":   explanation_text,
        "explanation_valid":  explanation_valid,
        "attention_priority": attention_priority,
        "personal_relevance": personal_relevance,
        "recency_score":      recency_score,
        "novelty_score":      novelty_score,
        "revisit_score":      revisit_score,
        "memory_relevance":   memory_relevance,
        "portfolio_relevance": portfolio_relevance,
    }


def _transition(
    *,
    entity_key: str = "AAPL",
    entity_type: str = "company",
    transition_type: str = "most_important_change_changed",
    composite_score: float = 0.7,
    change_type: str = "forecast_changed",
    surface: str = "shadow",
    explanation_text: str = "Forecast changed.",
    explanation_valid: bool = True,
    attention_priority: float = 0.8,
    personal_relevance: float = 0.5,
    recency_score: float = 0.6,
    novelty_score: float = 0.4,
    revisit_score: float = 0.3,
    memory_relevance: float = 0.2,
    portfolio_relevance: float = 0.1,
) -> dict:
    return {
        "entity_key":         entity_key,
        "entity_type":        entity_type,
        "transition_type":    transition_type,
        "composite_score":    composite_score,
        "change_type":        change_type,
        "surface":            surface,
        "explanation_text":   explanation_text,
        "explanation_valid":  explanation_valid,
        "attention_priority": attention_priority,
        "personal_relevance": personal_relevance,
        "recency_score":      recency_score,
        "novelty_score":      novelty_score,
        "revisit_score":      revisit_score,
        "memory_relevance":   memory_relevance,
        "portfolio_relevance": portfolio_relevance,
    }


# ===================================================================
# § classify_experience_transition
# ===================================================================

class TestClassifyExperienceTransition:
    def test_new_item_no_previous(self):
        from app.services.personal_experience_shadow_service import classify_experience_transition
        result = classify_experience_transition(_item())
        assert result == "most_important_change_changed"

    def test_entity_key_changed(self):
        from app.services.personal_experience_shadow_service import classify_experience_transition
        cur = _item(entity_key="AAPL")
        prev = _item(entity_key="MSFT")
        result = classify_experience_transition(cur, prev)
        assert result == "most_important_change_changed"

    def test_score_changed(self):
        from app.services.personal_experience_shadow_service import classify_experience_transition
        cur = _item(composite_score=0.8)
        prev = _item(composite_score=0.5)
        result = classify_experience_transition(cur, prev)
        assert result == "attention_queue_changed"

    def test_change_type_changed(self):
        from app.services.personal_experience_shadow_service import classify_experience_transition
        cur = _item(change_type="decision_changed")
        prev = _item(change_type="forecast_changed")
        result = classify_experience_transition(cur, prev)
        assert result == "most_important_change_changed"

    def test_no_material_change(self):
        from app.services.personal_experience_shadow_service import classify_experience_transition
        item = _item()
        result = classify_experience_transition(item, item)
        assert result is None

    def test_new_item_without_change_type(self):
        from app.services.personal_experience_shadow_service import classify_experience_transition
        result = classify_experience_transition(_item(change_type=""))
        assert result is None

    def test_small_score_diff_ignored(self):
        from app.services.personal_experience_shadow_service import classify_experience_transition
        cur = _item(composite_score=0.705)
        prev = _item(composite_score=0.700)
        result = classify_experience_transition(cur, prev)
        assert result is None


# ===================================================================
# § detect_experience_transitions
# ===================================================================

class TestDetectExperienceTransitions:
    def test_new_items_detected(self):
        from app.services.personal_experience_shadow_service import detect_experience_transitions
        current = [_item(entity_key="AAPL"), _item(entity_key="MSFT")]
        result = detect_experience_transitions(current, None)
        assert len(result) == 2
        keys = {t["entity_key"] for t in result}
        assert keys == {"AAPL", "MSFT"}

    def test_removed_items_detected(self):
        from app.services.personal_experience_shadow_service import detect_experience_transitions
        previous = [_item(entity_key="AAPL")]
        result = detect_experience_transitions([], previous)
        assert len(result) == 1
        assert result[0]["transition_type"] == "attention_queue_changed"
        assert "removed" in result[0]["explanation_text"]

    def test_mixed_transitions(self):
        from app.services.personal_experience_shadow_service import detect_experience_transitions
        current = [
            _item(entity_key="AAPL", composite_score=0.9),
            _item(entity_key="GOOG"),
        ]
        previous = [
            _item(entity_key="AAPL", composite_score=0.5),
            _item(entity_key="MSFT"),
        ]
        result = detect_experience_transitions(current, previous)
        types = {t["entity_key"]: t["transition_type"] for t in result}
        assert types["AAPL"] == "attention_queue_changed"
        assert types["GOOG"] == "most_important_change_changed"
        assert types["MSFT"] == "attention_queue_changed"

    def test_no_transitions_when_identical(self):
        from app.services.personal_experience_shadow_service import detect_experience_transitions
        items = [_item()]
        result = detect_experience_transitions(items, items)
        assert result == []

    def test_empty_both(self):
        from app.services.personal_experience_shadow_service import detect_experience_transitions
        assert detect_experience_transitions([], []) == []
        assert detect_experience_transitions([], None) == []

    def test_empty_current_populated_previous(self):
        from app.services.personal_experience_shadow_service import detect_experience_transitions
        previous = [_item(entity_key="AAPL"), _item(entity_key="MSFT")]
        result = detect_experience_transitions([], previous)
        assert len(result) == 2

    def test_populated_current_empty_previous(self):
        from app.services.personal_experience_shadow_service import detect_experience_transitions
        current = [_item(entity_key="AAPL")]
        result = detect_experience_transitions(current, [])
        assert len(result) == 1
        assert result[0]["transition_type"] == "most_important_change_changed"


# ===================================================================
# § record_experience_events — async
# ===================================================================

class TestRecordExperienceEvents:
    @pytest.mark.asyncio
    async def test_inserts_event_rows(self, db):
        from app.services.personal_experience_shadow_service import record_experience_events
        from app.db.repositories.personal_experience_repo import count_experience_events
        transitions = [_transition(entity_key="AAPL"), _transition(entity_key="MSFT")]
        result = await record_experience_events(
            db, user_id=_USER, transitions=transitions, run_override=True,
        )
        assert len(result) == 2
        await db.commit()
        count = await count_experience_events(db, user_id=_USER)
        assert count == 2

    @pytest.mark.asyncio
    async def test_deduplicates_within_window(self, db):
        from app.services.personal_experience_shadow_service import record_experience_events
        transitions = [_transition(entity_key="AAPL")]
        r1 = await record_experience_events(
            db, user_id=_USER, transitions=transitions, run_override=True,
        )
        assert len(r1) == 1
        r2 = await record_experience_events(
            db, user_id=_USER, transitions=transitions, run_override=True,
        )
        assert len(r2) == 0

    @pytest.mark.asyncio
    async def test_different_scores_not_deduped(self, db):
        from app.services.personal_experience_shadow_service import record_experience_events
        t1 = [_transition(entity_key="AAPL", composite_score=0.5)]
        t2 = [_transition(entity_key="AAPL", composite_score=0.9)]
        await record_experience_events(
            db, user_id=_USER, transitions=t1, run_override=True,
        )
        r2 = await record_experience_events(
            db, user_id=_USER, transitions=t2, run_override=True,
        )
        assert len(r2) == 1

    @pytest.mark.asyncio
    async def test_returns_empty_when_flag_off(self, db):
        from app.services.personal_experience_shadow_service import record_experience_events
        result = await record_experience_events(
            db, user_id=_USER, transitions=[_transition()], run_override=False,
        )
        assert result == []

    @pytest.mark.asyncio
    async def test_returns_empty_when_session_none(self):
        from app.services.personal_experience_shadow_service import record_experience_events
        result = await record_experience_events(
            None, user_id=_USER, transitions=[_transition()], run_override=True,
        )
        assert result == []

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_transitions(self, db):
        from app.services.personal_experience_shadow_service import record_experience_events
        result = await record_experience_events(
            db, user_id=_USER, transitions=[], run_override=True,
        )
        assert result == []

    @pytest.mark.asyncio
    async def test_run_reason_is_shadow(self, db):
        from app.services.personal_experience_shadow_service import record_experience_events
        result = await record_experience_events(
            db, user_id=_USER, transitions=[_transition()], run_override=True,
        )
        assert len(result) == 1
        assert result[0].run_reason == "shadow"

    @pytest.mark.asyncio
    async def test_all_scoring_dimensions_stored(self, db):
        from app.services.personal_experience_shadow_service import record_experience_events
        t = _transition(
            attention_priority=0.8, personal_relevance=0.5,
            recency_score=0.6, novelty_score=0.4,
            revisit_score=0.3, memory_relevance=0.2,
            portfolio_relevance=0.1,
        )
        result = await record_experience_events(
            db, user_id=_USER, transitions=[t], run_override=True,
        )
        assert len(result) == 1
        row = result[0]
        assert row.attention_priority == 0.8
        assert row.personal_relevance == 0.5
        assert row.recency_score == 0.6
        assert row.novelty_score == 0.4
        assert row.revisit_score == 0.3
        assert row.memory_relevance == 0.2
        assert row.portfolio_relevance == 0.1


# ===================================================================
# § Null-session contract
# ===================================================================

class TestNullSession:
    @pytest.mark.asyncio
    async def test_record_experience_events_none_session(self):
        from app.services.personal_experience_shadow_service import record_experience_events
        result = await record_experience_events(
            None, user_id=_USER, transitions=[_transition()], run_override=True,
        )
        assert result == []


# ===================================================================
# § AST safety
# ===================================================================

class TestASTSafety:
    def _source(self) -> str:
        return _SRC.read_text()

    def _tree(self) -> ast.Module:
        return ast.parse(self._source())

    def test_module_importable(self):
        import app.services.personal_experience_shadow_service  # noqa: F401

    def test_no_banned_phrases(self):
        tree = self._tree()

        docstring_node_ids: set = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Module)):
                body = getattr(node, "body", [])
                if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
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
                            f"banned phrase '{phrase}' in: {node.value[:80]!r}"
                        )
        assert not violations, "\n".join(violations)

    def test_no_upstream_truth_imports(self):
        tree = self._tree()
        banned_modules = [
            "forecast_repo", "decision_repo", "scenario_repo",
            "similarity_repo", "conviction", "order", "execution",
            "stance",
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
            occurrences = [
                i for i in range(len(source))
                if source[i:i + len(pattern)] == pattern
            ]
            assert not occurrences, (
                f"Found '{pattern}' in source — Phase 18 shadow journal must be append-only"
            )

    def test_no_notification_imports(self):
        tree = self._tree()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                assert "notification" not in node.module.lower(), (
                    f"Shadow journal must not import notification modules: {node.module}"
                )
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert "notification" not in alias.name.lower(), (
                        f"Shadow journal must not import notification modules: {alias.name}"
                    )
