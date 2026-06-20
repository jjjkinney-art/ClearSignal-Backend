"""
Tests — Personal Experience Composer + Explainability, Phase 18 · Slice 5.

Covers:
  1.  service importable
  2.  all public functions present

  --- explain_experience_item ---
  3.  forecast_changed → valid explanation with 4 fields
  4.  decision_changed → valid explanation
  5.  scenario_changed → valid explanation
  6.  watchlist_drift → valid explanation
  7.  memory_revisit → valid explanation
  8.  unknown change_type → valid=False (no template)
  9.  empty evidence_refs → valid=False
  10. entity_key appears in explanation text

  --- validate_experience_item ---
  11. all fields present → (True, "")
  12. missing why_am_i_seeing_this → (False, reason)
  13. missing why_now → (False, reason)
  14. missing what_changed → (False, reason)
  15. missing supporting_evidence → (False, reason)
  16. empty string why_now → (False, reason)

  --- build_experience_item ---
  17. merges scores + explanation
  18. includes all 7 dimensions
  19. includes composite_score
  20. includes explanation_valid
  21. includes change_type and entity_key

  --- build_attention_queue ---
  22. filters by attention_priority > 0.5
  23. max 5 items
  24. sorted by composite_score desc
  25. excludes invalid items
  26. empty list → []

  --- build_most_important_change ---
  27. returns highest-scored valid item
  28. returns None when no valid items
  29. excludes blocked items

  --- compose_experience ---
  30. empty DB → empty structure
  31. seeded forecast → valid_items populated
  32. blocked items tracked separately
  33. most_important populated for valid items
  34. attention_queue populated
  35. items_count correct
  36. valid_count + blocked_count = items_count
  37. surface propagated
  38. composed_at present
  39. deterministic: same inputs → same output
  40. flag off → empty
  41. null session → empty

  --- AST safety ---
  42. no truth-table write imports
  43. no conviction/order/execution imports
  44. no banned advisory phrases in non-docstring strings
  45. no upstream mutation calls
  46. no Notification writes
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
_SVC_PATH = _ROOT / "app" / "services" / "personal_experience_composer_service.py"


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


def _scored_candidate(entity_key="AAPL", change_type="forecast_changed",
                       composite=0.7, attn=0.6, evidence=None):
    return {
        "entity_key": entity_key, "entity_type": "company",
        "change_type": change_type,
        "changed_at": _now().isoformat(),
        "attention_priority": attn,
        "personal_relevance": 0.5,
        "recency_score": 0.8,
        "novelty_score": 0.6,
        "revisit_score": 0.3,
        "memory_relevance": 0.2,
        "portfolio_relevance": 0.4,
        "composite_score": composite,
        "rank": 1,
        "novelty_reserve_applied": False,
        "explanation_text": f"{entity_key} changed.",
        "evidence_refs": evidence if evidence is not None else [
            {"type": "forecast_vector", "id": "fv_001"}
        ],
    }


# ---------------------------------------------------------------------------
# Seeding helpers for compose_experience integration tests
# ---------------------------------------------------------------------------

async def _seed_forecast(db, entity_key="AAPL"):
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


# ---------------------------------------------------------------------------
# 1–2: Import and presence
# ---------------------------------------------------------------------------

class TestImportAndPresence:

    def test_importable(self):
        import app.services.personal_experience_composer_service  # noqa: F401

    def test_all_functions_present(self):
        import app.services.personal_experience_composer_service as svc
        for fn in (
            "explain_experience_item",
            "validate_experience_item",
            "build_experience_item",
            "build_attention_queue",
            "build_most_important_change",
            "compose_experience",
        ):
            assert callable(getattr(svc, fn, None)), f"missing: {fn}"


# ---------------------------------------------------------------------------
# 3–10: explain_experience_item
# ---------------------------------------------------------------------------

class TestExplainExperienceItem:

    def test_forecast_changed_valid(self):
        from app.services.personal_experience_composer_service import explain_experience_item
        c = _scored_candidate(change_type="forecast_changed")
        expl = explain_experience_item(c)
        assert expl["explanation_valid"] is True
        assert expl["why_am_i_seeing_this"]
        assert expl["why_now"]
        assert expl["what_changed"]
        assert expl["supporting_evidence"]

    def test_decision_changed_valid(self):
        from app.services.personal_experience_composer_service import explain_experience_item
        c = _scored_candidate(change_type="decision_changed")
        expl = explain_experience_item(c)
        assert expl["explanation_valid"] is True

    def test_scenario_changed_valid(self):
        from app.services.personal_experience_composer_service import explain_experience_item
        c = _scored_candidate(change_type="scenario_changed")
        expl = explain_experience_item(c)
        assert expl["explanation_valid"] is True

    def test_watchlist_drift_valid(self):
        from app.services.personal_experience_composer_service import explain_experience_item
        c = _scored_candidate(change_type="watchlist_drift")
        expl = explain_experience_item(c)
        assert expl["explanation_valid"] is True

    def test_memory_revisit_valid(self):
        from app.services.personal_experience_composer_service import explain_experience_item
        c = _scored_candidate(change_type="memory_revisit")
        expl = explain_experience_item(c)
        assert expl["explanation_valid"] is True

    def test_unknown_type_invalid(self):
        from app.services.personal_experience_composer_service import explain_experience_item
        c = _scored_candidate(change_type="unknown_type")
        expl = explain_experience_item(c)
        assert expl["explanation_valid"] is False

    def test_empty_evidence_invalid(self):
        from app.services.personal_experience_composer_service import explain_experience_item
        c = _scored_candidate(evidence=[])
        expl = explain_experience_item(c)
        assert expl["explanation_valid"] is False

    def test_entity_key_in_explanation(self):
        from app.services.personal_experience_composer_service import explain_experience_item
        c = _scored_candidate(entity_key="NVDA", change_type="forecast_changed")
        expl = explain_experience_item(c)
        assert "NVDA" in expl["why_am_i_seeing_this"]


# ---------------------------------------------------------------------------
# 11–16: validate_experience_item
# ---------------------------------------------------------------------------

class TestValidateExperienceItem:

    def test_all_fields_valid(self):
        from app.services.personal_experience_composer_service import validate_experience_item
        item = {
            "why_am_i_seeing_this": "reason",
            "why_now": "changed",
            "what_changed": "delta",
            "supporting_evidence": [{"type": "x", "id": "1"}],
        }
        ok, reason = validate_experience_item(item)
        assert ok
        assert reason == ""

    def test_missing_why_seeing(self):
        from app.services.personal_experience_composer_service import validate_experience_item
        item = {"why_now": "y", "what_changed": "z", "supporting_evidence": [{"id": "1"}]}
        ok, reason = validate_experience_item(item)
        assert not ok
        assert "why_am_i_seeing_this" in reason

    def test_missing_why_now(self):
        from app.services.personal_experience_composer_service import validate_experience_item
        item = {"why_am_i_seeing_this": "x", "what_changed": "z",
                "supporting_evidence": [{"id": "1"}]}
        ok, reason = validate_experience_item(item)
        assert not ok
        assert "why_now" in reason

    def test_missing_what_changed(self):
        from app.services.personal_experience_composer_service import validate_experience_item
        item = {"why_am_i_seeing_this": "x", "why_now": "y",
                "supporting_evidence": [{"id": "1"}]}
        ok, reason = validate_experience_item(item)
        assert not ok
        assert "what_changed" in reason

    def test_missing_evidence(self):
        from app.services.personal_experience_composer_service import validate_experience_item
        item = {"why_am_i_seeing_this": "x", "why_now": "y",
                "what_changed": "z", "supporting_evidence": []}
        ok, reason = validate_experience_item(item)
        assert not ok
        assert "supporting_evidence" in reason

    def test_empty_string_why_now(self):
        from app.services.personal_experience_composer_service import validate_experience_item
        item = {"why_am_i_seeing_this": "x", "why_now": "",
                "what_changed": "z", "supporting_evidence": [{"id": "1"}]}
        ok, _ = validate_experience_item(item)
        assert not ok


# ---------------------------------------------------------------------------
# 17–21: build_experience_item
# ---------------------------------------------------------------------------

class TestBuildExperienceItem:

    def test_merges_scores_and_explanation(self):
        from app.services.personal_experience_composer_service import (
            build_experience_item, explain_experience_item,
        )
        c = _scored_candidate()
        expl = explain_experience_item(c)
        item = build_experience_item(c, expl)
        assert item["composite_score"] == c["composite_score"]
        assert item["why_am_i_seeing_this"] == expl["why_am_i_seeing_this"]

    def test_includes_all_dimensions(self):
        from app.services.personal_experience_composer_service import (
            build_experience_item, explain_experience_item,
        )
        c = _scored_candidate()
        item = build_experience_item(c, explain_experience_item(c))
        for dim in ("attention_priority", "personal_relevance", "recency_score",
                     "novelty_score", "revisit_score", "memory_relevance",
                     "portfolio_relevance"):
            assert dim in item

    def test_includes_composite(self):
        from app.services.personal_experience_composer_service import (
            build_experience_item, explain_experience_item,
        )
        c = _scored_candidate(composite=0.85)
        item = build_experience_item(c, explain_experience_item(c))
        assert item["composite_score"] == 0.85

    def test_includes_explanation_valid(self):
        from app.services.personal_experience_composer_service import (
            build_experience_item, explain_experience_item,
        )
        c = _scored_candidate()
        expl = explain_experience_item(c)
        item = build_experience_item(c, expl)
        assert "explanation_valid" in item

    def test_includes_entity_and_change_type(self):
        from app.services.personal_experience_composer_service import (
            build_experience_item, explain_experience_item,
        )
        c = _scored_candidate(entity_key="TSLA", change_type="watchlist_drift")
        item = build_experience_item(c, explain_experience_item(c))
        assert item["entity_key"] == "TSLA"
        assert item["change_type"] == "watchlist_drift"


# ---------------------------------------------------------------------------
# 22–26: build_attention_queue
# ---------------------------------------------------------------------------

class TestBuildAttentionQueue:

    def test_filters_by_priority(self):
        from app.services.personal_experience_composer_service import build_attention_queue
        items = [
            {**_scored_candidate(attn=0.9, composite=0.8),
             "explanation_valid": True, "why_am_i_seeing_this": "x",
             "why_now": "y", "what_changed": "z", "supporting_evidence": [{"id": "1"}]},
            {**_scored_candidate(attn=0.2, composite=0.9),
             "explanation_valid": True, "why_am_i_seeing_this": "x",
             "why_now": "y", "what_changed": "z", "supporting_evidence": [{"id": "1"}]},
        ]
        queue = build_attention_queue(items)
        assert len(queue) == 1
        assert queue[0]["attention_priority"] == 0.9

    def test_max_items(self):
        from app.services.personal_experience_composer_service import build_attention_queue
        items = []
        for i in range(10):
            items.append({
                **_scored_candidate(attn=0.6 + 0.01 * i, composite=0.5),
                "explanation_valid": True, "why_am_i_seeing_this": "x",
                "why_now": "y", "what_changed": "z",
                "supporting_evidence": [{"id": "1"}],
            })
        queue = build_attention_queue(items)
        assert len(queue) <= 5

    def test_sorted_by_composite(self):
        from app.services.personal_experience_composer_service import build_attention_queue
        items = [
            {**_scored_candidate(attn=0.7, composite=0.9),
             "explanation_valid": True, "why_am_i_seeing_this": "x",
             "why_now": "y", "what_changed": "z", "supporting_evidence": [{"id": "1"}]},
            {**_scored_candidate(attn=0.6, composite=0.3),
             "explanation_valid": True, "why_am_i_seeing_this": "x",
             "why_now": "y", "what_changed": "z", "supporting_evidence": [{"id": "1"}]},
        ]
        queue = build_attention_queue(items)
        assert queue[0]["composite_score"] >= queue[-1]["composite_score"]

    def test_excludes_invalid(self):
        from app.services.personal_experience_composer_service import build_attention_queue
        items = [
            {**_scored_candidate(attn=0.9, composite=0.9), "explanation_valid": False},
        ]
        queue = build_attention_queue(items)
        assert len(queue) == 0

    def test_empty_list(self):
        from app.services.personal_experience_composer_service import build_attention_queue
        assert build_attention_queue([]) == []


# ---------------------------------------------------------------------------
# 27–29: build_most_important_change
# ---------------------------------------------------------------------------

class TestMostImportantChange:

    def test_returns_highest_scored_valid(self):
        from app.services.personal_experience_composer_service import build_most_important_change
        items = [
            {**_scored_candidate(composite=0.9), "explanation_valid": True},
            {**_scored_candidate(composite=0.3), "explanation_valid": True},
        ]
        mic = build_most_important_change(items)
        assert mic is not None
        assert mic["composite_score"] == 0.9

    def test_none_when_no_valid(self):
        from app.services.personal_experience_composer_service import build_most_important_change
        items = [
            {**_scored_candidate(composite=0.9), "explanation_valid": False},
        ]
        assert build_most_important_change(items) is None

    def test_excludes_blocked(self):
        from app.services.personal_experience_composer_service import build_most_important_change
        items = [
            {**_scored_candidate(composite=0.95), "explanation_valid": False},
            {**_scored_candidate(composite=0.5), "explanation_valid": True},
        ]
        mic = build_most_important_change(items)
        assert mic["composite_score"] == 0.5


# ---------------------------------------------------------------------------
# 30–41: compose_experience
# ---------------------------------------------------------------------------

class TestComposeExperience:

    @pytest.mark.asyncio
    async def test_empty_db(self, db):
        from app.services.personal_experience_composer_service import compose_experience
        result = await compose_experience(db, user_id=_uid(), run_override=True)
        assert result["items_count"] == 0
        assert result["valid_count"] == 0

    @pytest.mark.asyncio
    async def test_seeded_forecast_produces_valid_items(self, db):
        from app.services.personal_experience_composer_service import compose_experience
        uid = _uid()
        await _seed_forecast(db, entity_key="AAPL")
        result = await compose_experience(
            db, user_id=uid, entity_keys=["AAPL"], run_override=True)
        assert result["items_count"] >= 1
        assert result["valid_count"] >= 1

    @pytest.mark.asyncio
    async def test_blocked_tracked_separately(self, db):
        from app.services.personal_experience_composer_service import compose_experience
        uid = _uid()
        await _seed_forecast(db, entity_key="MSFT")
        result = await compose_experience(
            db, user_id=uid, entity_keys=["MSFT"], run_override=True)
        assert result["valid_count"] + result["blocked_count"] == result["items_count"]

    @pytest.mark.asyncio
    async def test_most_important_populated(self, db):
        from app.services.personal_experience_composer_service import compose_experience
        uid = _uid()
        await _seed_forecast(db, entity_key="GOOG")
        result = await compose_experience(
            db, user_id=uid, entity_keys=["GOOG"], run_override=True)
        if result["valid_count"] > 0:
            assert result["most_important"] is not None

    @pytest.mark.asyncio
    async def test_attention_queue_populated(self, db):
        from app.services.personal_experience_composer_service import compose_experience
        from app.db.models import DecisionPriority
        uid = _uid()
        await _seed_forecast(db, entity_key="NVDA")
        dp = DecisionPriority(
            id=_uid(), candidate_type="forecast", entity_type="company",
            entity_key="NVDA", source_ref="s",
            decision_priority="critical", decision_rank_score=0.95,
            decision_reason="test", why_now="test", decision_schema=1,
            built_at=_now(), expires_at=_now() + timedelta(hours=72),
        )
        db.add(dp)
        await db.flush()
        result = await compose_experience(
            db, user_id=uid, entity_keys=["NVDA"], run_override=True)
        if result["valid_count"] > 0:
            assert isinstance(result["attention_queue"], list)

    @pytest.mark.asyncio
    async def test_items_count_correct(self, db):
        from app.services.personal_experience_composer_service import compose_experience
        uid = _uid()
        await _seed_forecast(db, entity_key="META")
        result = await compose_experience(
            db, user_id=uid, entity_keys=["META"], run_override=True)
        assert result["items_count"] == len(result["items"])

    @pytest.mark.asyncio
    async def test_valid_plus_blocked_equals_total(self, db):
        from app.services.personal_experience_composer_service import compose_experience
        uid = _uid()
        await _seed_forecast(db, entity_key="AMZN")
        result = await compose_experience(
            db, user_id=uid, entity_keys=["AMZN"], run_override=True)
        assert (result["valid_count"] + result["blocked_count"]
                == result["items_count"])

    @pytest.mark.asyncio
    async def test_surface_propagated(self, db):
        from app.services.personal_experience_composer_service import compose_experience
        result = await compose_experience(
            db, user_id=_uid(), surface="brief", run_override=True)
        assert result["surface"] == "brief"

    @pytest.mark.asyncio
    async def test_composed_at_present(self, db):
        from app.services.personal_experience_composer_service import compose_experience
        result = await compose_experience(db, user_id=_uid(), run_override=True)
        assert "composed_at" in result
        assert isinstance(result["composed_at"], str)

    @pytest.mark.asyncio
    async def test_deterministic(self, db):
        from app.services.personal_experience_composer_service import compose_experience
        uid = _uid()
        await _seed_forecast(db, entity_key="DET")
        r1 = await compose_experience(
            db, user_id=uid, entity_keys=["DET"], run_override=True)
        r2 = await compose_experience(
            db, user_id=uid, entity_keys=["DET"], run_override=True)
        keys1 = [i["entity_key"] for i in r1["items"]]
        keys2 = [i["entity_key"] for i in r2["items"]]
        assert keys1 == keys2

    @pytest.mark.asyncio
    async def test_flag_off_empty(self, db):
        from app.services.personal_experience_composer_service import compose_experience
        result = await compose_experience(
            db, user_id=_uid(), run_override=False)
        assert result["items_count"] == 0

    @pytest.mark.asyncio
    async def test_null_session_empty(self):
        from app.services.personal_experience_composer_service import compose_experience
        result = await compose_experience(None, user_id=_uid(), run_override=True)
        assert result["items_count"] == 0


# ---------------------------------------------------------------------------
# 42–46: AST safety
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
                    "upsert_learned_preference", "add_user_signal_event"):
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
        for bad in ("upsert_forecast", "upsert_decision", "upsert_scenario"):
            assert bad not in call_attrs

    def test_no_notification_writes(self):
        names = _import_names(_load_ast())
        assert "Notification" not in names
        assert "add_notification" not in names
