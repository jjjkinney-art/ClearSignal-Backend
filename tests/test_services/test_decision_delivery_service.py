"""
Tests — Decision Shadow Delivery, Phase 13 · Slice 8.

Covers:
  1.  classify_decision_transition — first_priority (no previous)
  2.  classify_decision_transition — priority_disappeared (no current)
  3.  classify_decision_transition — priority_strengthened (score up ≥ threshold)
  4.  classify_decision_transition — priority_weakened (score down ≥ threshold)
  5.  classify_decision_transition — bucket_changed (bucket differs, score delta < threshold)
  6.  classify_decision_transition — steady-state (no change, returns None)
  7.  classify_decision_transition — just below threshold → None
  8.  classify_decision_transition — exactly at threshold → transition
  9.  classify_decision_transition — both absent → None
  10. classify_decision_transition — accepts ORM-like objects
  11. detect_decision_transitions — empty sets produce []
  12. detect_decision_transitions — all five transition types in one call
  13. detect_decision_transitions — steady-state produces []
  14. detect_decision_transitions — same ticker different candidate_types → separate events
  15. detect_decision_transitions — user_id partitioning (different users separate keys)
  16. detect_decision_transitions — malformed entry skipped, others processed
  17. detect_decision_transitions — None inputs return []
  18. record_decision_transition_events — null session returns []
  19. record_decision_transition_events — run_override=False returns []
  20. record_decision_transition_events — run_override=True, no transitions returns []
  21. record_decision_transition_events — writes ledger rows (channel=decision_shadow)
  22. record_decision_transition_events — deduplication (second call writes 0 rows)
  23. record_decision_transition_events — ledger status always "pending"
  24. record_decision_transition_events — no Notification rows created
  25. record_decision_transition_events — no delivery escalation (status never "delivered")
  26. record_decision_transition_events — channel is always "decision_shadow"
  27. record_decision_transition_events — disappeared events journaled
  28. record_decision_transition_events — first_priority events journaled
  29. record_decision_transition_events — returns event list (not ledger rows)
  30. record_decision_transition_events — decision_delivery_enabled=False irrelevant
  31. AST: no Notification import
  32. AST: no inbox / notification write calls
  33. AST: no advice / trade language in string constants
  34. AST: no conviction / forecast write-back imports
"""

from __future__ import annotations

import ast
import pathlib
import uuid
from typing import Any, Optional

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

# ---------------------------------------------------------------------------
# Path
# ---------------------------------------------------------------------------

_ROOT = pathlib.Path(__file__).parent.parent.parent
_SVC  = _ROOT / "app" / "services" / "decision_delivery_service.py"

# ---------------------------------------------------------------------------
# DB fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def engine():
    return create_async_engine("sqlite+aiosqlite:///:memory:", future=True)


@pytest_asyncio.fixture()
async def db(engine):
    from app.db.models import Base
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with Session() as session:
        yield session


# ---------------------------------------------------------------------------
# Synthetic priority helpers
# ---------------------------------------------------------------------------

def _prio(
    candidate_type: str = "forecast_candidate",
    entity_type: str = "company",
    entity_key: str = "NVDA",
    score: float = 0.50,
    bucket: str = "medium",
    user_id: Optional[str] = None,
) -> dict:
    return {
        "candidate_type":    candidate_type,
        "entity_type":       entity_type,
        "entity_key":        entity_key,
        "decision_rank_score": score,
        "decision_priority": bucket,
        "user_id":           user_id,
    }


class _OrmLike:
    """Minimal ORM-row stand-in — uses attributes, not dict access."""
    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)


# ---------------------------------------------------------------------------
# 1–10. classify_decision_transition
# ---------------------------------------------------------------------------

class TestClassifyDecisionTransition:
    def test_first_priority(self):
        from app.services.decision_delivery_service import classify_decision_transition, TRANSITION_FIRST_PRIORITY
        result = classify_decision_transition(None, _prio(score=0.55))
        assert result == TRANSITION_FIRST_PRIORITY

    def test_priority_disappeared(self):
        from app.services.decision_delivery_service import classify_decision_transition, TRANSITION_DISAPPEARED
        result = classify_decision_transition(_prio(score=0.55), None)
        assert result == TRANSITION_DISAPPEARED

    def test_priority_strengthened(self):
        from app.services.decision_delivery_service import (
            classify_decision_transition, TRANSITION_STRENGTHENED,
            DEFAULT_MATERIALITY_THRESHOLD,
        )
        prev = _prio(score=0.40)
        curr = _prio(score=0.40 + DEFAULT_MATERIALITY_THRESHOLD + 0.01)
        assert classify_decision_transition(prev, curr) == TRANSITION_STRENGTHENED

    def test_priority_weakened(self):
        from app.services.decision_delivery_service import (
            classify_decision_transition, TRANSITION_WEAKENED,
            DEFAULT_MATERIALITY_THRESHOLD,
        )
        prev = _prio(score=0.60)
        curr = _prio(score=0.60 - DEFAULT_MATERIALITY_THRESHOLD - 0.01)
        assert classify_decision_transition(prev, curr) == TRANSITION_WEAKENED

    def test_bucket_changed(self):
        from app.services.decision_delivery_service import classify_decision_transition, TRANSITION_BUCKET_CHANGED
        # Score barely moved (< threshold) but bucket crossed boundary
        prev = _prio(score=0.61, bucket="high")
        curr = _prio(score=0.61 + 0.01, bucket="medium")  # delta = 0.01 < 0.08
        result = classify_decision_transition(prev, curr)
        assert result == TRANSITION_BUCKET_CHANGED

    def test_steady_state_returns_none(self):
        from app.services.decision_delivery_service import classify_decision_transition
        prev = _prio(score=0.50, bucket="medium")
        curr = _prio(score=0.51, bucket="medium")  # delta 0.01 < threshold
        assert classify_decision_transition(prev, curr) is None

    def test_just_below_threshold_is_none(self):
        from app.services.decision_delivery_service import (
            classify_decision_transition, DEFAULT_MATERIALITY_THRESHOLD,
        )
        prev = _prio(score=0.50, bucket="medium")
        curr = _prio(score=0.50 + DEFAULT_MATERIALITY_THRESHOLD - 0.001, bucket="medium")
        assert classify_decision_transition(prev, curr) is None

    def test_exactly_at_threshold_is_transition(self):
        from app.services.decision_delivery_service import (
            classify_decision_transition, TRANSITION_STRENGTHENED,
        )
        # Use 0.25 (exact in IEEE-754) as both the delta and the threshold to avoid
        # float-subtraction precision issues (e.g. 0.50-0.40 == 0.0999... in Python).
        prev = _prio(score=0.00, bucket="medium")
        curr = _prio(score=0.25, bucket="medium")   # delta = 0.25 exactly
        assert classify_decision_transition(prev, curr, materiality_threshold=0.25) == TRANSITION_STRENGTHENED

    def test_both_absent_returns_none(self):
        from app.services.decision_delivery_service import classify_decision_transition
        assert classify_decision_transition(None, None) is None

    def test_accepts_orm_like_objects(self):
        from app.services.decision_delivery_service import (
            classify_decision_transition, TRANSITION_STRENGTHENED,
            DEFAULT_MATERIALITY_THRESHOLD,
        )
        prev = _OrmLike(decision_rank_score=0.40, decision_priority="medium",
                        candidate_type="forecast_candidate", entity_type="company",
                        entity_key="AAPL", user_id=None)
        curr = _OrmLike(decision_rank_score=0.40 + DEFAULT_MATERIALITY_THRESHOLD + 0.01,
                        decision_priority="high",
                        candidate_type="forecast_candidate", entity_type="company",
                        entity_key="AAPL", user_id=None)
        assert classify_decision_transition(prev, curr) == TRANSITION_STRENGTHENED


# ---------------------------------------------------------------------------
# 11–17. detect_decision_transitions
# ---------------------------------------------------------------------------

class TestDetectDecisionTransitions:
    def test_empty_sets_return_empty(self):
        from app.services.decision_delivery_service import detect_decision_transitions
        assert detect_decision_transitions([], []) == []

    def test_all_five_transition_types(self):
        from app.services.decision_delivery_service import (
            detect_decision_transitions,
            TRANSITION_FIRST_PRIORITY, TRANSITION_DISAPPEARED,
            TRANSITION_STRENGTHENED, TRANSITION_WEAKENED, TRANSITION_BUCKET_CHANGED,
            DEFAULT_MATERIALITY_THRESHOLD,
        )
        T = DEFAULT_MATERIALITY_THRESHOLD
        prev = [
            _prio(candidate_type="forecast_candidate",   entity_key="A", score=0.55, bucket="medium"),
            _prio(candidate_type="risk_candidate",       entity_key="B", score=0.65, bucket="high"),
            _prio(candidate_type="catalyst_candidate",   entity_key="C", score=0.55, bucket="medium"),
            _prio(candidate_type="watchlist_candidate",  entity_key="D", score=0.51, bucket="medium"),
            # E — absent in prev → first_priority in current
        ]
        curr = [
            # A disappeared
            _prio(candidate_type="risk_candidate",       entity_key="B", score=0.65 + T + 0.01, bucket="high"),   # strengthened
            _prio(candidate_type="catalyst_candidate",   entity_key="C", score=0.55 - T - 0.01, bucket="medium"), # weakened
            _prio(candidate_type="watchlist_candidate",  entity_key="D", score=0.52, bucket="high"),              # bucket_changed
            _prio(candidate_type="similarity_candidate", entity_key="E", score=0.45, bucket="medium"),            # first_priority
        ]
        events = detect_decision_transitions(prev, curr)
        transitions = {e["transition"] for e in events}
        assert TRANSITION_FIRST_PRIORITY   in transitions
        assert TRANSITION_DISAPPEARED      in transitions
        assert TRANSITION_STRENGTHENED     in transitions
        assert TRANSITION_WEAKENED         in transitions
        assert TRANSITION_BUCKET_CHANGED   in transitions

    def test_steady_state_produces_empty(self):
        from app.services.decision_delivery_service import detect_decision_transitions
        p = _prio(score=0.50, bucket="medium")
        c = _prio(score=0.51, bucket="medium")
        assert detect_decision_transitions([p], [c]) == []

    def test_different_candidate_types_same_ticker_separate_events(self):
        from app.services.decision_delivery_service import detect_decision_transitions
        prev = [
            _prio(candidate_type="forecast_candidate", entity_key="NVDA", score=0.50),
        ]
        curr = [
            # forecast_candidate for NVDA disappeared
            _prio(candidate_type="risk_candidate", entity_key="NVDA", score=0.55),  # first_priority
        ]
        events = detect_decision_transitions(prev, curr)
        c_types = {e["candidate_type"] for e in events}
        assert "forecast_candidate" in c_types  # disappeared
        assert "risk_candidate"     in c_types  # first_priority

    def test_user_id_partitioned_separately(self):
        from app.services.decision_delivery_service import (
            detect_decision_transitions, DEFAULT_MATERIALITY_THRESHOLD,
        )
        T = DEFAULT_MATERIALITY_THRESHOLD
        uid_a = str(uuid.uuid4())
        uid_b = str(uuid.uuid4())
        prev = [
            _prio(entity_key="NVDA", score=0.50, user_id=uid_a),
            _prio(entity_key="NVDA", score=0.50, user_id=uid_b),
        ]
        curr = [
            _prio(entity_key="NVDA", score=0.50 + T + 0.01, user_id=uid_a),  # strengthened
            _prio(entity_key="NVDA", score=0.50,             user_id=uid_b),  # steady-state
        ]
        events = detect_decision_transitions(prev, curr)
        assert len(events) == 1
        assert events[0]["user_id"] == uid_a

    def test_none_inputs_return_empty(self):
        from app.services.decision_delivery_service import detect_decision_transitions
        assert detect_decision_transitions(None, None) == []

    def test_malformed_entry_skipped(self):
        from app.services.decision_delivery_service import detect_decision_transitions
        # Valid entry and a None entry in the list
        prev = [None, _prio(entity_key="NVDA", score=0.50)]
        curr = [_prio(entity_key="NVDA", score=0.50)]  # no change → steady-state
        # Should not raise; returns [] (steady-state) or skips None safely
        result = detect_decision_transitions(prev, curr)
        assert isinstance(result, list)


# ---------------------------------------------------------------------------
# 18–30. record_decision_transition_events (requires DB)
# ---------------------------------------------------------------------------

class TestRecordDecisionTransitionEvents:
    @pytest.mark.asyncio
    async def test_null_session_returns_empty(self):
        from app.services.decision_delivery_service import record_decision_transition_events
        result = await record_decision_transition_events(
            None, [_prio()], [], run_override=True,
        )
        assert result == []

    @pytest.mark.asyncio
    async def test_run_override_false_returns_empty(self, db):
        from app.services.decision_delivery_service import record_decision_transition_events
        result = await record_decision_transition_events(
            db, [_prio()], [], run_override=False,
        )
        assert result == []

    @pytest.mark.asyncio
    async def test_run_override_true_no_transitions(self, db):
        from app.services.decision_delivery_service import record_decision_transition_events
        prev = [_prio(score=0.50, bucket="medium")]
        curr = [_prio(score=0.51, bucket="medium")]  # steady-state
        result = await record_decision_transition_events(
            db, prev, curr, run_override=True,
        )
        assert result == []

    @pytest.mark.asyncio
    async def test_writes_ledger_rows(self, db):
        from app.services.decision_delivery_service import record_decision_transition_events
        from app.db.models import DeliveryLedger
        from sqlalchemy import select, func

        prev_count = (await db.execute(
            select(func.count()).select_from(DeliveryLedger)
        )).scalar_one()

        result = await record_decision_transition_events(
            db, [], [_prio(entity_key="NVDA", score=0.55)], run_override=True,
        )
        await db.commit()

        assert len(result) == 1  # one transition event (first_priority)
        new_count = (await db.execute(
            select(func.count()).select_from(DeliveryLedger)
        )).scalar_one()
        assert new_count > prev_count

    @pytest.mark.asyncio
    async def test_deduplication_second_call_writes_zero(self, db):
        from app.services.decision_delivery_service import record_decision_transition_events
        from app.db.models import DeliveryLedger
        from sqlalchemy import select, func

        prev = []
        curr = [_prio(entity_key="NVDA", score=0.55)]

        await record_decision_transition_events(db, prev, curr, run_override=True)
        await db.commit()

        count_after_first = (await db.execute(
            select(func.count()).select_from(DeliveryLedger)
        )).scalar_one()

        # Same transition again — should be deduped
        await record_decision_transition_events(db, prev, curr, run_override=True)
        await db.commit()

        count_after_second = (await db.execute(
            select(func.count()).select_from(DeliveryLedger)
        )).scalar_one()
        assert count_after_first == count_after_second

    @pytest.mark.asyncio
    async def test_ledger_status_always_pending(self, db):
        from app.services.decision_delivery_service import record_decision_transition_events
        from app.db.models import DeliveryLedger
        from sqlalchemy import select

        await record_decision_transition_events(
            db, [], [_prio(entity_key="TSLA", score=0.60)], run_override=True,
        )
        await db.commit()

        rows = (await db.execute(select(DeliveryLedger))).scalars().all()
        for row in rows:
            assert row.status == "pending"

    @pytest.mark.asyncio
    async def test_no_notification_rows_created(self, db):
        from app.services.decision_delivery_service import record_decision_transition_events
        from app.db.models import Notification
        from sqlalchemy import select, func

        await record_decision_transition_events(
            db, [], [_prio(entity_key="AAPL", score=0.65)], run_override=True,
        )
        await db.commit()

        n_count = (await db.execute(
            select(func.count()).select_from(Notification)
        )).scalar_one()
        assert n_count == 0

    @pytest.mark.asyncio
    async def test_no_delivery_escalation(self, db):
        """Status must never be 'delivered' after shadow journaling."""
        from app.services.decision_delivery_service import record_decision_transition_events
        from app.db.models import DeliveryLedger
        from sqlalchemy import select

        await record_decision_transition_events(
            db, [], [_prio(entity_key="MSFT", score=0.70)], run_override=True,
        )
        await db.commit()

        rows = (await db.execute(select(DeliveryLedger))).scalars().all()
        for row in rows:
            assert row.status != "delivered"

    @pytest.mark.asyncio
    async def test_channel_is_decision_shadow(self, db):
        from app.services.decision_delivery_service import (
            record_decision_transition_events, DECISION_DELIVERY_CHANNEL,
        )
        from app.db.models import DeliveryLedger
        from sqlalchemy import select

        await record_decision_transition_events(
            db, [], [_prio(entity_key="GOOG", score=0.55)], run_override=True,
        )
        await db.commit()

        rows = (await db.execute(select(DeliveryLedger))).scalars().all()
        for row in rows:
            assert row.channel == DECISION_DELIVERY_CHANNEL

    @pytest.mark.asyncio
    async def test_disappeared_events_journaled(self, db):
        from app.services.decision_delivery_service import (
            record_decision_transition_events, TRANSITION_DISAPPEARED,
        )
        from app.db.models import DeliveryLedger
        from sqlalchemy import select, func

        prev = [_prio(entity_key="NVDA", score=0.60)]
        curr: list = []

        events = await record_decision_transition_events(
            db, prev, curr, run_override=True,
        )
        await db.commit()

        assert any(e["transition"] == TRANSITION_DISAPPEARED for e in events)
        count = (await db.execute(
            select(func.count()).select_from(DeliveryLedger)
        )).scalar_one()
        assert count >= 1

    @pytest.mark.asyncio
    async def test_first_priority_events_journaled(self, db):
        from app.services.decision_delivery_service import (
            record_decision_transition_events, TRANSITION_FIRST_PRIORITY,
        )
        from app.db.models import DeliveryLedger
        from sqlalchemy import select, func

        events = await record_decision_transition_events(
            db, [], [_prio(entity_key="AMD", score=0.55)], run_override=True,
        )
        await db.commit()

        assert any(e["transition"] == TRANSITION_FIRST_PRIORITY for e in events)
        count = (await db.execute(
            select(func.count()).select_from(DeliveryLedger)
        )).scalar_one()
        assert count >= 1

    @pytest.mark.asyncio
    async def test_returns_event_list_not_ledger_rows(self, db):
        from app.services.decision_delivery_service import record_decision_transition_events
        result = await record_decision_transition_events(
            db, [], [_prio(entity_key="META", score=0.55)], run_override=True,
        )
        assert isinstance(result, list)
        assert all(isinstance(e, dict) for e in result)
        assert all("transition" in e for e in result)

    @pytest.mark.asyncio
    async def test_decision_delivery_enabled_false_has_no_effect(self, db):
        """Shadow journaling must work regardless of decision_delivery_enabled."""
        from app.services.decision_delivery_service import record_decision_transition_events
        from app.db.models import DeliveryLedger
        from sqlalchemy import select, func

        # run_override=True bypasses flag check; delivery_enabled is irrelevant
        events = await record_decision_transition_events(
            db, [], [_prio(entity_key="NVDA", score=0.55)], run_override=True,
        )
        await db.commit()

        assert len(events) >= 1
        count = (await db.execute(
            select(func.count()).select_from(DeliveryLedger)
        )).scalar_one()
        assert count >= 1


# ---------------------------------------------------------------------------
# 31–34. AST safety
# ---------------------------------------------------------------------------

def _load_tree() -> ast.AST:
    return ast.parse(_SVC.read_text(encoding="utf-8"))


def _docstring_values(tree: ast.AST) -> set:
    values: set = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if (
                node.body
                and isinstance(node.body[0], ast.Expr)
                and isinstance(node.body[0].value, ast.Constant)
                and isinstance(node.body[0].value.value, str)
            ):
                values.add(node.body[0].value.value)
    return values


class TestASTSafety:
    def test_no_notification_import(self):
        tree = _load_tree()
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                module = getattr(node, "module", "") or ""
                names  = [a.name for a in getattr(node, "names", [])]
                for part in ([module] + names):
                    assert "notification" not in part.lower(), \
                        f"Notification import found: {part!r}"

    def test_no_inbox_or_notification_write_calls(self):
        src = _SVC.read_text(encoding="utf-8")
        for forbidden in (
            "notification_create", "notification_add", "session.add(Notification",
            "inbox_create", "inbox_add", "mark_delivered",
        ):
            assert forbidden not in src, f"Forbidden call {forbidden!r} found"

    def test_no_advice_language_in_string_constants(self):
        tree = _load_tree()
        doc_values = _docstring_values(tree)
        banned_terms = ["buy", "sell", "hold", "overweight", "underweight",
                        "recommend", "target price", "position size",
                        "take a position", "enter a trade", "exit a trade"]
        offenders = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                val = node.value
                if val in doc_values:
                    continue
                for term in banned_terms:
                    if term in val.lower():
                        offenders.append(repr(term) + " in " + repr(val[:80]))
        assert not offenders, "Advice language found: " + str(offenders)

    def test_no_conviction_or_forecast_write_imports(self):
        tree = _load_tree()
        forbidden = {
            "conviction_modeler", "conviction_repo",
            "forecast_repo", "forecast_builder",
            "order", "execution",
        }
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                module = getattr(node, "module", "") or ""
                names  = [a.name for a in getattr(node, "names", [])]
                for part in ([module] + names):
                    for fw in forbidden:
                        assert fw not in part.lower(), \
                            f"Forbidden import {part!r}"
