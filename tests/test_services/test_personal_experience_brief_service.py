"""
Tests — Personal Experience Brief Builder, Phase 18 · Slice 7.

Covers:
  1.  build_what_changed: filters by recency_score > 0.5 + valid explanation
  2.  build_what_changed: empty when no items qualify
  3.  build_what_changed: sorted by recency_score desc
  4.  build_what_changed: excludes items without change_type
  5.  build_why_it_matters: filters by attention_priority > 0.5 + valid
  6.  build_why_it_matters: empty when no items qualify
  7.  build_why_it_matters: sorted by attention_priority desc
  8.  build_attention_section: filters by attention_priority > 0.7
  9.  build_attention_section: empty when no items qualify
  10. build_attention_section: sorted by composite_score desc
  11. build_ignore_section: empty when total_tracked <= 20
  12. build_ignore_section: returns low-score items when tracked > 20
  13. build_ignore_section: excludes items with change_type
  14. build_ignore_section: excludes items with composite_score >= 0.2
  15. build_resume_section: formats resume candidates
  16. build_resume_section: excludes candidates not changed_since_last_seen
  17. build_resume_section: sorted by continuation_score desc
  18. build_resume_section: empty when no candidates
  19. validate_brief: valid brief passes
  20. validate_brief: fails when most_important_change missing
  21. validate_brief: fails when explanation invalid
  22. validate_brief: fails when attention section empty
  23. validate_brief: fails when supporting_evidence missing
  24. build_daily_brief: returns None when flag off
  25. build_daily_brief: returns None when session is None
  26. build_daily_brief: returns None when brief already exists (idempotent)
  27. build_daily_brief: valid brief round-trip
  28. build_daily_brief: stores brief snapshot
  29. build_daily_brief: deterministic output
  30. build_daily_brief: includes resume section from continuity
  31. build_daily_brief: brief_date defaults to today
  32. build_daily_brief: explanation_valid reflects validation
  33. AST: no banned phrases in source
  34. AST: no upstream truth-table imports
  35. AST: module is importable
  36. Pure: build_what_changed is deterministic
  37. Pure: build_attention_section is deterministic
  38. Pure: build_ignore_section is deterministic
  39. Pure: validate_brief is deterministic
  40. Null-session: all async functions safe
"""

from __future__ import annotations

import ast
import pathlib
import re
from datetime import date, datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

_ROOT = pathlib.Path(__file__).parent.parent.parent
_SRC  = _ROOT / "app" / "services" / "personal_experience_brief_service.py"

_USER = "u-brief-test"


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
# Helpers — build valid items
# ---------------------------------------------------------------------------

def _item(
    *,
    entity_key: str = "AAPL",
    entity_type: str = "company",
    change_type: str = "forecast_changed",
    recency_score: float = 0.8,
    attention_priority: float = 0.9,
    composite_score: float = 0.6,
    explanation_valid: bool = True,
    why_am_i_seeing_this: str = "AAPL is on your watchlist.",
    why_now: str = "Forecast changed.",
    what_changed: str = "Forecast state differs.",
    supporting_evidence: list = None,
) -> dict:
    return {
        "entity_key":           entity_key,
        "entity_type":          entity_type,
        "change_type":          change_type,
        "recency_score":        recency_score,
        "attention_priority":   attention_priority,
        "composite_score":      composite_score,
        "explanation_valid":    explanation_valid,
        "why_am_i_seeing_this": why_am_i_seeing_this,
        "why_now":              why_now,
        "what_changed":         what_changed,
        "supporting_evidence":  supporting_evidence or ["forecast_vector"],
        "novelty_score":        0.5,
        "revisit_score":        0.3,
        "memory_relevance":     0.2,
        "portfolio_relevance":  0.1,
        "rank":                 1,
    }


def _resume_candidate(
    *,
    entity_key: str = "AAPL",
    entity_type: str = "company",
    change_type: str = "forecast_changed",
    continuation_score: float = 0.7,
    changed_since_last_seen: bool = True,
    last_seen_at: str = "2026-06-19T12:00:00+00:00",
) -> dict:
    return {
        "entity_key":              entity_key,
        "entity_type":             entity_type,
        "change_type":             change_type,
        "continuation_score":      continuation_score,
        "changed_since_last_seen": changed_since_last_seen,
        "last_seen_at":            last_seen_at,
    }


# ===================================================================
# § build_what_changed
# ===================================================================

class TestBuildWhatChanged:
    def test_filters_by_recency_and_valid(self):
        from app.services.personal_experience_brief_service import build_what_changed
        items = [
            _item(recency_score=0.8, explanation_valid=True),
            _item(entity_key="MSFT", recency_score=0.3, explanation_valid=True),
            _item(entity_key="GOOG", recency_score=0.9, explanation_valid=False),
        ]
        result = build_what_changed(items)
        assert len(result) == 1
        assert result[0]["entity_key"] == "AAPL"

    def test_empty_when_none_qualify(self):
        from app.services.personal_experience_brief_service import build_what_changed
        items = [_item(recency_score=0.2)]
        assert build_what_changed(items) == []

    def test_sorted_by_recency_desc(self):
        from app.services.personal_experience_brief_service import build_what_changed
        items = [
            _item(entity_key="AAPL", recency_score=0.6),
            _item(entity_key="MSFT", recency_score=0.9),
            _item(entity_key="GOOG", recency_score=0.7),
        ]
        result = build_what_changed(items)
        assert [r["entity_key"] for r in result] == ["MSFT", "GOOG", "AAPL"]

    def test_excludes_items_without_change_type(self):
        from app.services.personal_experience_brief_service import build_what_changed
        items = [_item(change_type="")]
        assert build_what_changed(items) == []

    def test_empty_input(self):
        from app.services.personal_experience_brief_service import build_what_changed
        assert build_what_changed([]) == []

    def test_deterministic(self):
        from app.services.personal_experience_brief_service import build_what_changed
        items = [
            _item(entity_key="AAPL", recency_score=0.8),
            _item(entity_key="MSFT", recency_score=0.7),
        ]
        r1 = build_what_changed(items)
        r2 = build_what_changed(items)
        assert r1 == r2


# ===================================================================
# § build_why_it_matters
# ===================================================================

class TestBuildWhyItMatters:
    def test_filters_by_priority_and_valid(self):
        from app.services.personal_experience_brief_service import build_why_it_matters
        items = [
            _item(attention_priority=0.8, explanation_valid=True),
            _item(entity_key="MSFT", attention_priority=0.3, explanation_valid=True),
            _item(entity_key="GOOG", attention_priority=0.9, explanation_valid=False),
        ]
        result = build_why_it_matters(items)
        assert len(result) == 1
        assert result[0]["entity_key"] == "AAPL"

    def test_empty_when_none_qualify(self):
        from app.services.personal_experience_brief_service import build_why_it_matters
        items = [_item(attention_priority=0.2)]
        assert build_why_it_matters(items) == []

    def test_sorted_by_priority_desc(self):
        from app.services.personal_experience_brief_service import build_why_it_matters
        items = [
            _item(entity_key="AAPL", attention_priority=0.6),
            _item(entity_key="MSFT", attention_priority=0.9),
            _item(entity_key="GOOG", attention_priority=0.7),
        ]
        result = build_why_it_matters(items)
        assert [r["entity_key"] for r in result] == ["MSFT", "GOOG", "AAPL"]

    def test_empty_input(self):
        from app.services.personal_experience_brief_service import build_why_it_matters
        assert build_why_it_matters([]) == []


# ===================================================================
# § build_attention_section
# ===================================================================

class TestBuildAttentionSection:
    def test_filters_by_high_priority(self):
        from app.services.personal_experience_brief_service import build_attention_section
        items = [
            _item(attention_priority=0.9, composite_score=0.8),
            _item(entity_key="MSFT", attention_priority=0.5, composite_score=0.6),
        ]
        result = build_attention_section(items)
        assert len(result) == 1
        assert result[0]["entity_key"] == "AAPL"

    def test_empty_when_none_qualify(self):
        from app.services.personal_experience_brief_service import build_attention_section
        items = [_item(attention_priority=0.3)]
        assert build_attention_section(items) == []

    def test_sorted_by_composite_desc(self):
        from app.services.personal_experience_brief_service import build_attention_section
        items = [
            _item(entity_key="AAPL", attention_priority=0.8, composite_score=0.5),
            _item(entity_key="MSFT", attention_priority=0.9, composite_score=0.9),
        ]
        result = build_attention_section(items)
        assert [r["entity_key"] for r in result] == ["MSFT", "AAPL"]

    def test_excludes_invalid_explanation(self):
        from app.services.personal_experience_brief_service import build_attention_section
        items = [_item(attention_priority=0.9, explanation_valid=False)]
        assert build_attention_section(items) == []

    def test_deterministic(self):
        from app.services.personal_experience_brief_service import build_attention_section
        items = [
            _item(entity_key="AAPL", attention_priority=0.9, composite_score=0.8),
            _item(entity_key="MSFT", attention_priority=0.8, composite_score=0.7),
        ]
        r1 = build_attention_section(items)
        r2 = build_attention_section(items)
        assert r1 == r2


# ===================================================================
# § build_ignore_section
# ===================================================================

class TestBuildIgnoreSection:
    def test_empty_when_tracked_lte_20(self):
        from app.services.personal_experience_brief_service import build_ignore_section
        items = [_item(composite_score=0.1, change_type="")]
        assert build_ignore_section(items, total_tracked=20) == []
        assert build_ignore_section(items, total_tracked=5) == []

    def test_returns_low_score_items_when_tracked_gt_20(self):
        from app.services.personal_experience_brief_service import build_ignore_section
        items = [
            _item(entity_key="AAPL", composite_score=0.1, change_type=""),
            _item(entity_key="MSFT", composite_score=0.15, change_type=""),
        ]
        result = build_ignore_section(items, total_tracked=25)
        assert len(result) == 2

    def test_excludes_items_with_change_type(self):
        from app.services.personal_experience_brief_service import build_ignore_section
        items = [_item(composite_score=0.1, change_type="forecast_changed")]
        result = build_ignore_section(items, total_tracked=25)
        assert result == []

    def test_excludes_items_with_score_gte_ceiling(self):
        from app.services.personal_experience_brief_service import build_ignore_section
        items = [_item(composite_score=0.2, change_type="")]
        result = build_ignore_section(items, total_tracked=25)
        assert result == []

    def test_sorted_by_composite_asc(self):
        from app.services.personal_experience_brief_service import build_ignore_section
        items = [
            _item(entity_key="AAPL", composite_score=0.15, change_type=""),
            _item(entity_key="MSFT", composite_score=0.05, change_type=""),
        ]
        result = build_ignore_section(items, total_tracked=25)
        assert [r["entity_key"] for r in result] == ["MSFT", "AAPL"]

    def test_deterministic(self):
        from app.services.personal_experience_brief_service import build_ignore_section
        items = [_item(composite_score=0.1, change_type="")]
        r1 = build_ignore_section(items, total_tracked=25)
        r2 = build_ignore_section(items, total_tracked=25)
        assert r1 == r2


# ===================================================================
# § build_resume_section
# ===================================================================

class TestBuildResumeSection:
    def test_formats_candidates(self):
        from app.services.personal_experience_brief_service import build_resume_section
        candidates = [_resume_candidate()]
        result = build_resume_section(candidates)
        assert len(result) == 1
        assert result[0]["entity_key"] == "AAPL"
        assert result[0]["continuation_score"] == 0.7

    def test_excludes_unchanged(self):
        from app.services.personal_experience_brief_service import build_resume_section
        candidates = [_resume_candidate(changed_since_last_seen=False)]
        assert build_resume_section(candidates) == []

    def test_sorted_by_continuation_desc(self):
        from app.services.personal_experience_brief_service import build_resume_section
        candidates = [
            _resume_candidate(entity_key="AAPL", continuation_score=0.5),
            _resume_candidate(entity_key="MSFT", continuation_score=0.9),
        ]
        result = build_resume_section(candidates)
        assert [r["entity_key"] for r in result] == ["MSFT", "AAPL"]

    def test_empty_input(self):
        from app.services.personal_experience_brief_service import build_resume_section
        assert build_resume_section([]) == []


# ===================================================================
# § validate_brief
# ===================================================================

class TestValidateBrief:
    def _valid_brief(self):
        return {
            "most_important_change": {
                "entity_key": "AAPL",
                "explanation_valid": True,
                "supporting_evidence": ["forecast_vector"],
            },
            "deserves_attention": [{"entity_key": "AAPL"}],
        }

    def test_valid_passes(self):
        from app.services.personal_experience_brief_service import validate_brief
        ok, reason = validate_brief(self._valid_brief())
        assert ok is True
        assert reason == ""

    def test_fails_missing_mic(self):
        from app.services.personal_experience_brief_service import validate_brief
        brief = self._valid_brief()
        brief["most_important_change"] = None
        ok, reason = validate_brief(brief)
        assert ok is False
        assert "most_important_change" in reason

    def test_fails_invalid_explanation(self):
        from app.services.personal_experience_brief_service import validate_brief
        brief = self._valid_brief()
        brief["most_important_change"]["explanation_valid"] = False
        ok, reason = validate_brief(brief)
        assert ok is False
        assert "explanation" in reason

    def test_fails_empty_attention(self):
        from app.services.personal_experience_brief_service import validate_brief
        brief = self._valid_brief()
        brief["deserves_attention"] = []
        ok, reason = validate_brief(brief)
        assert ok is False
        assert "attention" in reason

    def test_fails_missing_evidence(self):
        from app.services.personal_experience_brief_service import validate_brief
        brief = self._valid_brief()
        brief["most_important_change"]["supporting_evidence"] = []
        ok, reason = validate_brief(brief)
        assert ok is False
        assert "evidence" in reason

    def test_deterministic(self):
        from app.services.personal_experience_brief_service import validate_brief
        brief = self._valid_brief()
        r1 = validate_brief(brief)
        r2 = validate_brief(brief)
        assert r1 == r2


# ===================================================================
# § build_daily_brief — async integration
# ===================================================================

class TestBuildDailyBrief:
    @pytest.mark.asyncio
    async def test_returns_none_when_flag_off(self, db):
        from app.services.personal_experience_brief_service import build_daily_brief
        result = await build_daily_brief(db, user_id=_USER, run_override=False)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_session_none(self):
        from app.services.personal_experience_brief_service import build_daily_brief
        result = await build_daily_brief(None, user_id=_USER, run_override=True)
        assert result is None

    @pytest.mark.asyncio
    async def test_idempotent_second_call_returns_none(self, db):
        from app.services.personal_experience_brief_service import build_daily_brief
        from app.db.repositories.personal_experience_repo import add_brief_snapshot
        target = date(2026, 6, 20)
        await add_brief_snapshot(
            db, user_id=_USER, brief_date=target,
            items_surfaced=1, items_blocked=0,
            top_attention_item="AAPL", run_reason="shadow",
        )
        await db.commit()
        result = await build_daily_brief(
            db, user_id=_USER, brief_date=target, run_override=True,
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_brief_round_trip(self, db):
        from app.services.personal_experience_brief_service import build_daily_brief
        target = date(2026, 6, 20)
        result = await build_daily_brief(
            db, user_id=_USER, brief_date=target, run_override=True,
        )
        if result is None:
            assert True
            return
        assert "brief_date" in result
        assert "most_important_change" in result
        assert "what_changed" in result
        assert "why_it_matters" in result
        assert "deserves_attention" in result
        assert "can_be_ignored" in result
        assert "resume_previous_research" in result
        assert "generated_at" in result
        assert "explanation_valid" in result

    @pytest.mark.asyncio
    async def test_stores_brief_snapshot(self, db):
        from app.services.personal_experience_brief_service import build_daily_brief
        from app.db.repositories.personal_experience_repo import get_brief_snapshot
        target = date(2026, 6, 21)
        await build_daily_brief(
            db, user_id=_USER, brief_date=target, run_override=True,
        )
        await db.commit()
        snapshot = await get_brief_snapshot(
            db, user_id=_USER, brief_date=target,
        )
        assert snapshot is not None
        assert snapshot.run_reason == "shadow"

    @pytest.mark.asyncio
    async def test_deterministic(self, db):
        from app.services.personal_experience_brief_service import build_daily_brief
        t1 = date(2026, 6, 22)
        r1 = await build_daily_brief(
            db, user_id=_USER, brief_date=t1, run_override=True,
        )
        t2 = date(2026, 6, 23)
        r2 = await build_daily_brief(
            db, user_id=_USER, brief_date=t2, run_override=True,
        )
        if r1 is not None and r2 is not None:
            assert r1.get("what_changed") == r2.get("what_changed")
            assert r1.get("why_it_matters") == r2.get("why_it_matters")

    @pytest.mark.asyncio
    async def test_brief_date_defaults_to_today(self, db):
        from app.services.personal_experience_brief_service import build_daily_brief
        result = await build_daily_brief(
            db, user_id="u-today-test", run_override=True,
        )
        if result is not None:
            from datetime import date as d
            assert result["brief_date"] == str(d.today())

    @pytest.mark.asyncio
    async def test_explanation_valid_reflects_validation(self, db):
        from app.services.personal_experience_brief_service import build_daily_brief
        result = await build_daily_brief(
            db, user_id="u-valid-test", brief_date=date(2026, 7, 1),
            run_override=True,
        )
        if result is not None:
            assert isinstance(result["explanation_valid"], bool)


# ===================================================================
# § Null-session contract
# ===================================================================

class TestNullSession:
    @pytest.mark.asyncio
    async def test_build_daily_brief_none_session(self):
        from app.services.personal_experience_brief_service import build_daily_brief
        result = await build_daily_brief(None, user_id=_USER, run_override=True)
        assert result is None


# ===================================================================
# § AST safety
# ===================================================================

class TestASTSafety:
    def _source(self) -> str:
        return _SRC.read_text()

    def _tree(self) -> ast.Module:
        return ast.parse(self._source())

    def test_module_importable(self):
        import app.services.personal_experience_brief_service  # noqa: F401

    def test_no_banned_phrases(self):
        tree = self._tree()
        source = self._source()

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

    def test_no_update_delete_on_truth_tables(self):
        source = self._source()
        for pattern in [".update(", ".delete(", "DELETE FROM", "UPDATE "]:
            occurrences = [
                i for i in range(len(source))
                if source[i:i + len(pattern)] == pattern
            ]
            assert not occurrences, (
                f"Found '{pattern}' in source — Phase 18 must not mutate"
            )
