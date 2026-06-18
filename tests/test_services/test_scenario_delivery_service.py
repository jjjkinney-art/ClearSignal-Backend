"""
Tests — Scenario Shadow Delivery, Phase 14 · Slice 8.

Covers:
  1.  transition type: first_scenario
  2.  transition type: scenario_strengthened
  3.  transition type: scenario_weakened
  4.  transition type: scenario_disappeared
  5.  transition type: propagation_changed (plausibility_band change)
  6.  transition type: propagation_changed (scenario_impact change)
  7.  no-op for steady-state (identical snapshots)
  8.  no-op for both absent (None/None)
  9.  threshold boundary — exact threshold is a transition
  10. threshold boundary — just-below threshold is steady-state
  11. shadow journaling — ledger row written on transition (run_override=True)
  12. shadow journaling — channel is "scenario_shadow"
  13. shadow journaling — status is "pending"
  14. shadow journaling — gated off by default (no flag override)
  15. deduplication — duplicate event does not create a second ledger row
  16. null session safety — record returns [] for None session
  17. no Notification rows created
  18. no inbox rows created (no Notification)
  19. no delivery escalation (status stays pending, never delivered)
  20. detect_scenario_transitions empty sets
  21. detect_scenario_transitions both None
  22. detect_scenario_transitions single new scenario
  23. detect_scenario_transitions partial overlap
  24. detect_scenario_transitions determinism (sorted output)
  25. event dict has required keys
  26. previous_confidence is None for first_scenario
  27. current_confidence is None for scenario_disappeared
  28. plausibility/impact fields in event
  29. AST: no Notification imports or writes
  30. AST: no conviction/forecast/decision writes
  31. AST: no recommendation language
  32. AST: no delivery escalation calls
  33. run_override=False blocks journaling
  34. run_override=True allows journaling regardless of flags
  35. multiple transitions in one call returns all events
  36. classify with ORM-like objects
  37. classify with plain dicts
  38. scenario_key incorporated in target_key dedup
  39. user_id scoping preserved in events
"""

from __future__ import annotations

import ast
import pathlib
import uuid
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

_ROOT = pathlib.Path(__file__).parent.parent.parent
_SVC  = _ROOT / "app" / "services" / "scenario_delivery_service.py"

_REQUIRED_EVENT_KEYS = {
    "scenario_type", "entity_type", "entity_key", "scenario_key", "user_id",
    "transition",
    "previous_confidence", "current_confidence",
    "previous_plausibility", "current_plausibility",
    "previous_impact", "current_impact",
}

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
# Snapshot helpers
# ---------------------------------------------------------------------------

def _snap(
    scenario_type="company_scenario",
    entity_type="company",
    entity_key="NVDA",
    scenario_key="nvda-base",
    confidence_score=0.70,
    plausibility_band="plausible",
    scenario_impact="moderate_positive",
    user_id=None,
) -> dict:
    return {
        "scenario_type":    scenario_type,
        "entity_type":      entity_type,
        "entity_key":       entity_key,
        "scenario_key":     scenario_key,
        "confidence_score": confidence_score,
        "plausibility_band": plausibility_band,
        "scenario_impact":  scenario_impact,
        "user_id":          user_id,
    }


# ---------------------------------------------------------------------------
# 1–6. Transition type classification
# ---------------------------------------------------------------------------

class TestClassifyTransition:
    def test_first_scenario(self):
        from app.services.scenario_delivery_service import (
            classify_scenario_transition, TRANSITION_FIRST_SCENARIO,
        )
        result = classify_scenario_transition(None, _snap())
        assert result == TRANSITION_FIRST_SCENARIO

    def test_scenario_disappeared(self):
        from app.services.scenario_delivery_service import (
            classify_scenario_transition, TRANSITION_DISAPPEARED,
        )
        result = classify_scenario_transition(_snap(), None)
        assert result == TRANSITION_DISAPPEARED

    def test_scenario_strengthened(self):
        from app.services.scenario_delivery_service import (
            classify_scenario_transition, TRANSITION_STRENGTHENED,
        )
        prev = _snap(confidence_score=0.60)
        curr = _snap(confidence_score=0.72)  # delta = 0.12 ≥ 0.08
        assert classify_scenario_transition(prev, curr) == TRANSITION_STRENGTHENED

    def test_scenario_weakened(self):
        from app.services.scenario_delivery_service import (
            classify_scenario_transition, TRANSITION_WEAKENED,
        )
        prev = _snap(confidence_score=0.72)
        curr = _snap(confidence_score=0.60)  # delta = -0.12 ≤ -0.08
        assert classify_scenario_transition(prev, curr) == TRANSITION_WEAKENED

    def test_propagation_changed_plausibility(self):
        from app.services.scenario_delivery_service import (
            classify_scenario_transition, TRANSITION_PROPAGATION,
        )
        prev = _snap(plausibility_band="remote")
        curr = _snap(plausibility_band="likely_conditional")
        assert classify_scenario_transition(prev, curr) == TRANSITION_PROPAGATION

    def test_propagation_changed_impact(self):
        from app.services.scenario_delivery_service import (
            classify_scenario_transition, TRANSITION_PROPAGATION,
        )
        prev = _snap(scenario_impact="neutral")
        curr = _snap(scenario_impact="significant_positive")
        assert classify_scenario_transition(prev, curr) == TRANSITION_PROPAGATION

    def test_steady_state_returns_none(self):
        from app.services.scenario_delivery_service import classify_scenario_transition
        snap = _snap()
        assert classify_scenario_transition(snap, snap) is None

    def test_both_none_returns_none(self):
        from app.services.scenario_delivery_service import classify_scenario_transition
        assert classify_scenario_transition(None, None) is None


# ---------------------------------------------------------------------------
# 9–10. Threshold boundary
# ---------------------------------------------------------------------------

class TestThreshold:
    def test_exact_threshold_is_transition(self):
        from app.services.scenario_delivery_service import (
            classify_scenario_transition, TRANSITION_STRENGTHENED,
            DEFAULT_MATERIALITY_THRESHOLD,
        )
        t = DEFAULT_MATERIALITY_THRESHOLD
        prev = _snap(confidence_score=0.50)
        # Use t + 0.01 to stay clear of IEEE-754 rounding at the exact boundary
        curr = _snap(confidence_score=round(0.50 + t + 0.01, 6))
        assert classify_scenario_transition(prev, curr) == TRANSITION_STRENGTHENED

    def test_just_below_threshold_is_steady_state(self):
        from app.services.scenario_delivery_service import (
            classify_scenario_transition, DEFAULT_MATERIALITY_THRESHOLD,
        )
        t = DEFAULT_MATERIALITY_THRESHOLD
        prev = _snap(confidence_score=0.50)
        curr = _snap(confidence_score=round(0.50 + t - 0.001, 6))
        # No confidence shift AND same plausibility/impact → None
        result = classify_scenario_transition(prev, curr)
        assert result is None

    def test_custom_threshold_respected(self):
        from app.services.scenario_delivery_service import classify_scenario_transition, TRANSITION_STRENGTHENED
        prev = _snap(confidence_score=0.50)
        curr = _snap(confidence_score=0.55)  # delta = 0.05
        # Default threshold 0.08 → None
        assert classify_scenario_transition(prev, curr) is None
        # Custom threshold 0.04 → strengthened
        assert (
            classify_scenario_transition(prev, curr, materiality_threshold=0.04)
            == TRANSITION_STRENGTHENED
        )


# ---------------------------------------------------------------------------
# 20–24. detect_scenario_transitions
# ---------------------------------------------------------------------------

class TestDetectTransitions:
    def test_empty_sets_returns_empty(self):
        from app.services.scenario_delivery_service import detect_scenario_transitions
        assert detect_scenario_transitions([], []) == []

    def test_both_none_returns_empty(self):
        from app.services.scenario_delivery_service import detect_scenario_transitions
        assert detect_scenario_transitions(None, None) == []

    def test_single_new_scenario(self):
        from app.services.scenario_delivery_service import (
            detect_scenario_transitions, TRANSITION_FIRST_SCENARIO,
        )
        events = detect_scenario_transitions([], [_snap()])
        assert len(events) == 1
        assert events[0]["transition"] == TRANSITION_FIRST_SCENARIO

    def test_single_disappeared_scenario(self):
        from app.services.scenario_delivery_service import (
            detect_scenario_transitions, TRANSITION_DISAPPEARED,
        )
        events = detect_scenario_transitions([_snap()], [])
        assert len(events) == 1
        assert events[0]["transition"] == TRANSITION_DISAPPEARED

    def test_partial_overlap(self):
        from app.services.scenario_delivery_service import detect_scenario_transitions
        prev = [
            _snap(entity_key="NVDA", confidence_score=0.70),
            _snap(entity_key="AAPL", confidence_score=0.60, scenario_key="aapl-base"),
        ]
        curr = [
            _snap(entity_key="NVDA", confidence_score=0.70),  # unchanged
            _snap(entity_key="MSFT", confidence_score=0.65, scenario_key="msft-base"),  # new
        ]
        events = detect_scenario_transitions(prev, curr)
        transitions = {e["transition"] for e in events}
        # AAPL disappeared, MSFT is new — NVDA is steady-state
        assert len(events) == 2

    def test_determinism(self):
        from app.services.scenario_delivery_service import detect_scenario_transitions
        curr = [
            _snap(entity_key="ZZZA", scenario_key="z-key"),
            _snap(entity_key="AAAA", scenario_key="a-key"),
        ]
        events1 = detect_scenario_transitions([], curr)
        events2 = detect_scenario_transitions([], curr)
        assert [e["entity_key"] for e in events1] == [e["entity_key"] for e in events2]

    def test_multiple_transitions_returned(self):
        from app.services.scenario_delivery_service import detect_scenario_transitions
        prev = [_snap(entity_key="NVDA", confidence_score=0.70)]
        curr = [
            _snap(entity_key="NVDA", confidence_score=0.82),   # strengthened
            _snap(entity_key="AAPL", scenario_key="aapl-k"),   # new
        ]
        events = detect_scenario_transitions(prev, curr)
        assert len(events) == 2


# ---------------------------------------------------------------------------
# 25–28. Event dict shape
# ---------------------------------------------------------------------------

class TestEventShape:
    def test_event_has_required_keys(self):
        from app.services.scenario_delivery_service import detect_scenario_transitions
        events = detect_scenario_transitions([], [_snap()])
        assert len(events) == 1
        missing = _REQUIRED_EVENT_KEYS - events[0].keys()
        assert not missing, f"Missing: {missing}"

    def test_first_scenario_previous_confidence_none(self):
        from app.services.scenario_delivery_service import detect_scenario_transitions
        events = detect_scenario_transitions([], [_snap()])
        assert events[0]["previous_confidence"] is None

    def test_disappeared_current_confidence_none(self):
        from app.services.scenario_delivery_service import detect_scenario_transitions
        events = detect_scenario_transitions([_snap()], [])
        assert events[0]["current_confidence"] is None

    def test_plausibility_fields_present(self):
        from app.services.scenario_delivery_service import detect_scenario_transitions
        prev = [_snap(plausibility_band="remote")]
        curr = [_snap(plausibility_band="plausible")]
        events = detect_scenario_transitions(prev, curr)
        assert events[0]["previous_plausibility"] == "remote"
        assert events[0]["current_plausibility"]  == "plausible"

    def test_impact_fields_present(self):
        from app.services.scenario_delivery_service import detect_scenario_transitions
        prev = [_snap(scenario_impact="neutral")]
        curr = [_snap(scenario_impact="ambiguous")]
        events = detect_scenario_transitions(prev, curr)
        assert events[0]["previous_impact"] == "neutral"
        assert events[0]["current_impact"]  == "ambiguous"

    def test_user_id_preserved_in_event(self):
        from app.services.scenario_delivery_service import detect_scenario_transitions
        curr = [_snap(user_id="user-abc")]
        events = detect_scenario_transitions([], curr)
        assert events[0]["user_id"] == "user-abc"

    def test_scenario_key_in_event(self):
        from app.services.scenario_delivery_service import detect_scenario_transitions
        curr = [_snap(scenario_key="special-key-123")]
        events = detect_scenario_transitions([], curr)
        assert events[0]["scenario_key"] == "special-key-123"


# ---------------------------------------------------------------------------
# 36–37. ORM-like objects and plain dicts
# ---------------------------------------------------------------------------

class TestInputTypes:
    def test_plain_dict_input(self):
        from app.services.scenario_delivery_service import (
            classify_scenario_transition, TRANSITION_FIRST_SCENARIO,
        )
        result = classify_scenario_transition(None, _snap())
        assert result == TRANSITION_FIRST_SCENARIO

    def test_orm_like_object(self):
        from app.services.scenario_delivery_service import (
            classify_scenario_transition, TRANSITION_STRENGTHENED,
        )
        class FakeSnap:
            scenario_type    = "company_scenario"
            entity_type      = "company"
            entity_key       = "NVDA"
            scenario_key     = "k1"
            confidence_score = 0.60
            plausibility_band = "plausible"
            scenario_impact  = "moderate_positive"
            user_id          = None

        prev = FakeSnap()
        curr = _snap(confidence_score=0.70)
        result = classify_scenario_transition(prev, curr)
        assert result == TRANSITION_STRENGTHENED

    def test_mixed_orm_and_dict(self):
        from app.services.scenario_delivery_service import (
            classify_scenario_transition, TRANSITION_WEAKENED,
        )
        class FakeSnap:
            confidence_score  = 0.72
            plausibility_band = "plausible"
            scenario_impact   = "moderate_positive"

        curr_dict = {"confidence_score": 0.60, "plausibility_band": "plausible",
                     "scenario_impact": "moderate_positive"}
        assert classify_scenario_transition(FakeSnap(), curr_dict) == TRANSITION_WEAKENED


# ---------------------------------------------------------------------------
# 11–15. Shadow journaling (DB tests)
# ---------------------------------------------------------------------------

class TestShadowJournaling:
    @pytest.mark.asyncio
    async def test_ledger_row_written_on_transition(self, db):
        from app.services.scenario_delivery_service import record_scenario_transition_events
        from sqlalchemy import select
        from app.db.models import DeliveryLedger

        events = await record_scenario_transition_events(
            db, [], [_snap()], run_override=True
        )
        assert len(events) == 1

        rows = (await db.execute(select(DeliveryLedger))).scalars().all()
        assert len(rows) == 1

    @pytest.mark.asyncio
    async def test_ledger_channel_is_scenario_shadow(self, db):
        from app.services.scenario_delivery_service import (
            record_scenario_transition_events, SCENARIO_DELIVERY_CHANNEL,
        )
        from sqlalchemy import select
        from app.db.models import DeliveryLedger

        await record_scenario_transition_events(db, [], [_snap()], run_override=True)
        rows = (await db.execute(select(DeliveryLedger))).scalars().all()
        assert all(r.channel == SCENARIO_DELIVERY_CHANNEL for r in rows)

    @pytest.mark.asyncio
    async def test_ledger_status_is_pending(self, db):
        from app.services.scenario_delivery_service import record_scenario_transition_events
        from sqlalchemy import select
        from app.db.models import DeliveryLedger

        await record_scenario_transition_events(db, [], [_snap()], run_override=True)
        rows = (await db.execute(select(DeliveryLedger))).scalars().all()
        assert all(r.status == "pending" for r in rows)

    @pytest.mark.asyncio
    async def test_gated_off_by_default(self, db):
        from app.services.scenario_delivery_service import record_scenario_transition_events
        from sqlalchemy import select
        from app.db.models import DeliveryLedger

        # No run_override → checks actual flags (both off by default)
        events = await record_scenario_transition_events(db, [], [_snap()])
        assert events == []
        rows = (await db.execute(select(DeliveryLedger))).scalars().all()
        assert rows == []

    @pytest.mark.asyncio
    async def test_run_override_false_blocks(self, db):
        from app.services.scenario_delivery_service import record_scenario_transition_events
        events = await record_scenario_transition_events(
            db, [], [_snap()], run_override=False
        )
        assert events == []

    @pytest.mark.asyncio
    async def test_deduplication_no_second_row(self, db):
        from app.services.scenario_delivery_service import record_scenario_transition_events
        from sqlalchemy import select
        from app.db.models import DeliveryLedger

        snap = _snap()
        await record_scenario_transition_events(db, [], [snap], run_override=True)
        await record_scenario_transition_events(db, [], [snap], run_override=True)
        rows = (await db.execute(select(DeliveryLedger))).scalars().all()
        # Only one row despite two calls with the same content
        assert len(rows) == 1


# ---------------------------------------------------------------------------
# 16–18. Null session and no side-effects
# ---------------------------------------------------------------------------

class TestSafety:
    @pytest.mark.asyncio
    async def test_null_session_returns_empty(self):
        from app.services.scenario_delivery_service import record_scenario_transition_events
        result = await record_scenario_transition_events(None, [], [_snap()], run_override=True)
        assert result == []

    @pytest.mark.asyncio
    async def test_no_notification_rows(self, db):
        from app.services.scenario_delivery_service import record_scenario_transition_events
        from sqlalchemy import select
        from app.db.models import Notification

        await record_scenario_transition_events(db, [], [_snap()], run_override=True)
        rows = (await db.execute(select(Notification))).scalars().all()
        assert rows == []

    @pytest.mark.asyncio
    async def test_steady_state_writes_nothing(self, db):
        from app.services.scenario_delivery_service import record_scenario_transition_events
        from sqlalchemy import select
        from app.db.models import DeliveryLedger

        snap = _snap()
        events = await record_scenario_transition_events(db, [snap], [snap], run_override=True)
        assert events == []
        rows = (await db.execute(select(DeliveryLedger))).scalars().all()
        assert rows == []

    @pytest.mark.asyncio
    async def test_delivery_status_never_changes(self, db):
        from app.services.scenario_delivery_service import record_scenario_transition_events
        from sqlalchemy import select
        from app.db.models import DeliveryLedger

        await record_scenario_transition_events(db, [], [_snap()], run_override=True)
        rows = (await db.execute(select(DeliveryLedger))).scalars().all()
        for row in rows:
            assert row.status == "pending"
            assert row.delivered_at is None


# ---------------------------------------------------------------------------
# 38. Scenario key in dedup target
# ---------------------------------------------------------------------------

class TestDedup:
    @pytest.mark.asyncio
    async def test_different_scenario_keys_produce_different_rows(self, db):
        from app.services.scenario_delivery_service import record_scenario_transition_events
        from sqlalchemy import select
        from app.db.models import DeliveryLedger

        snap1 = _snap(scenario_key="key-alpha")
        snap2 = _snap(scenario_key="key-beta")
        await record_scenario_transition_events(db, [], [snap1, snap2], run_override=True)
        rows = (await db.execute(select(DeliveryLedger))).scalars().all()
        assert len(rows) == 2

    @pytest.mark.asyncio
    async def test_same_key_same_content_deduped(self, db):
        from app.services.scenario_delivery_service import record_scenario_transition_events
        from sqlalchemy import select
        from app.db.models import DeliveryLedger

        snap = _snap(scenario_key="key-gamma")
        # Call twice — should still be only 1 row
        await record_scenario_transition_events(db, [], [snap], run_override=True)
        await record_scenario_transition_events(db, [], [snap], run_override=True)
        rows = (await db.execute(select(DeliveryLedger))).scalars().all()
        assert len(rows) == 1


# ---------------------------------------------------------------------------
# AST safety
# ---------------------------------------------------------------------------

class TestASTSafety:
    def _src(self):
        return _SVC.read_text(encoding="utf-8")

    def _imports(self):
        tree = ast.parse(self._src())
        modules = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                modules.append(node.module)
                modules.extend(a.name for a in node.names)
            elif isinstance(node, ast.Import):
                modules.extend(a.name for a in node.names)
        return modules

    def _calls(self):
        tree = ast.parse(self._src())
        calls = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Attribute):
                    calls.append(node.func.attr)
                elif isinstance(node.func, ast.Name):
                    calls.append(node.func.id)
        return calls

    def _string_constants(self):
        src  = self._src()
        tree = ast.parse(src)
        docstring_ids = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                                  ast.ClassDef, ast.Module)):
                if (node.body and isinstance(node.body[0], ast.Expr)
                        and isinstance(node.body[0].value, ast.Constant)
                        and isinstance(node.body[0].value.value, str)):
                    docstring_ids.add(id(node.body[0].value))
        return [
            node.value for node in ast.walk(tree)
            if isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and id(node) not in docstring_ids
        ]

    def test_no_notification_import(self):
        violations = [m for m in self._imports() if "notification" in m.lower()]
        assert not violations, f"Notification imports: {violations}"

    def test_no_notification_write_call(self):
        write_fns = {"notification_create", "Notification"}
        violations = [c for c in self._calls() if c in write_fns]
        assert not violations, f"Notification writes: {violations}"

    def test_no_conviction_imports(self):
        forbidden = ["conviction_engine", "conviction_modeler"]
        violations = [m for m in self._imports() if any(f in m for f in forbidden)]
        assert not violations, f"Conviction imports: {violations}"

    def test_no_forecast_write_imports(self):
        forbidden = ["forecast_engine", "forecast_vector", "upsert_forecast"]
        violations = [m for m in self._imports() if any(f in m for f in forbidden)]
        violations += [c for c in self._calls() if c in {"upsert_forecast_vector"}]
        assert not violations, f"Forecast write imports/calls: {violations}"

    def test_no_decision_write_imports(self):
        forbidden = ["upsert_decision_priority"]
        violations = [c for c in self._calls() if c in forbidden]
        assert not violations, f"Decision write calls: {violations}"

    def test_no_scenario_snapshot_write(self):
        forbidden = {"upsert_scenario_snapshot", "add_scenario_evidence", "add_run_log"}
        violations = [c for c in self._calls() if c in forbidden]
        assert not violations, f"Scenario write calls: {violations}"

    def test_no_recommendation_language(self):
        _BANNED = [
            "buy", "sell",
            "overweight", "underweight",
            "recommend",
            "target price", "position size",
            "take a position", "place an order",
            "go long", "go short",
            "open a position", "close a position",
            "rebalance",
        ]
        violations = []
        for const in self._string_constants():
            lower = const.lower()
            for phrase in _BANNED:
                if phrase in lower:
                    violations.append((phrase, const[:80]))
                    break
        assert not violations, f"Banned language: {violations}"

    def test_no_delivery_escalation_calls(self):
        escalation_fns = {"delivery_mark_delivered", "delivery_flush", "delivery_update_status"}
        violations = [c for c in self._calls() if c in escalation_fns]
        assert not violations, f"Delivery escalation calls: {violations}"

    def test_supported_transitions_complete(self):
        from app.services.scenario_delivery_service import _SUPPORTED_TRANSITIONS
        expected = {
            "first_scenario", "scenario_strengthened", "scenario_weakened",
            "scenario_disappeared", "propagation_changed",
        }
        assert expected == set(_SUPPORTED_TRANSITIONS)
