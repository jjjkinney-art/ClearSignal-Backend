"""
Tests — Forecast Shadow Delivery, Phase 12 · Slice 7.

Covers:
  1.  classify_forecast_transition — first_forecast
  2.  classify_forecast_transition — forecast_strengthened
  3.  classify_forecast_transition — forecast_weakened
  4.  classify_forecast_transition — forecast_disappeared
  5.  classify_forecast_transition — confidence_changed
  6.  classify_forecast_transition — steady-state returns None
  7.  detect_forecast_transitions — snapshot diff (pure function)
  8.  record_forecast_transition_events — flags inert by default
  9.  record_forecast_transition_events — run_override=True journals
  10. Dedup — duplicate event produces no second ledger row
  11. No Notification rows written
  12. No inbox / user-visible rows written
  13. No conviction / recommendation imports (AST)
  14. No source-table writes (AST)
  15. Null-session safety
  16. Materiality threshold respected (below threshold → steady-state)
  17. All five transition types exercise the journal path
"""

from __future__ import annotations

import ast
import pathlib
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

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
# Forecast snapshot helpers (plain dicts — no DB required for pure tests)
# ---------------------------------------------------------------------------

def _vec(
    entity_type: str = "company",
    entity_key: str = "AAPL",
    forecast_type: str = "thesis_strengthening",
    horizon_days: int = 30,
    p_positive: float = 0.55,
    p_negative: float = 0.25,
    p_neutral: float = 0.20,
    confidence_band_low: float = 0.35,
    confidence_band_high: float = 0.75,
    user_id: str = None,
) -> dict:
    return {
        "entity_type": entity_type,
        "entity_key": entity_key,
        "forecast_type": forecast_type,
        "horizon_days": horizon_days,
        "p_positive": p_positive,
        "p_negative": p_negative,
        "p_neutral": p_neutral,
        "confidence_band_low": confidence_band_low,
        "confidence_band_high": confidence_band_high,
        "user_id": user_id,
    }


async def _seed_ledger_row(db, content_key: str, channel: str = "forecast_shadow"):
    """Seed a delivery_ledger row directly for dedup tests."""
    from app.db.models import DeliveryLedger
    row = DeliveryLedger(
        content_key=content_key,
        target_key="test_target",
        channel=channel,
        content_hash=content_key[:64],
        status="pending",
    )
    db.add(row)
    await db.flush()
    return row


# ---------------------------------------------------------------------------
# 1–6: classify_forecast_transition (pure)
# ---------------------------------------------------------------------------

class TestClassifyForecastTransition:
    def test_first_forecast_when_previous_none(self):
        from app.services.forecast_delivery_service import (
            classify_forecast_transition, TRANSITION_FIRST_FORECAST,
        )
        result = classify_forecast_transition(None, _vec(p_positive=0.55))
        assert result == TRANSITION_FIRST_FORECAST

    def test_disappeared_when_current_none(self):
        from app.services.forecast_delivery_service import (
            classify_forecast_transition, TRANSITION_DISAPPEARED,
        )
        result = classify_forecast_transition(_vec(p_positive=0.55), None)
        assert result == TRANSITION_DISAPPEARED

    def test_strengthened_above_threshold(self):
        from app.services.forecast_delivery_service import (
            classify_forecast_transition, TRANSITION_STRENGTHENED,
        )
        prev = _vec(p_positive=0.40)
        curr = _vec(p_positive=0.55)  # delta = +0.15 > 0.08
        result = classify_forecast_transition(prev, curr)
        assert result == TRANSITION_STRENGTHENED

    def test_weakened_above_threshold(self):
        from app.services.forecast_delivery_service import (
            classify_forecast_transition, TRANSITION_WEAKENED,
        )
        prev = _vec(p_positive=0.60)
        curr = _vec(p_positive=0.45)  # delta = -0.15 < -0.08
        result = classify_forecast_transition(prev, curr)
        assert result == TRANSITION_WEAKENED

    def test_confidence_changed_without_p_positive_shift(self):
        from app.services.forecast_delivery_service import (
            classify_forecast_transition, TRANSITION_CONFIDENCE,
        )
        # Same p_positive, but confidence band narrows from "low" → "high"
        prev = _vec(p_positive=0.50, confidence_band_low=0.20, confidence_band_high=0.80)  # band=0.60 → low
        curr = _vec(p_positive=0.50, confidence_band_low=0.42, confidence_band_high=0.58)  # band=0.16 → high
        result = classify_forecast_transition(prev, curr)
        assert result == TRANSITION_CONFIDENCE

    def test_steady_state_returns_none(self):
        from app.services.forecast_delivery_service import classify_forecast_transition
        prev = _vec(p_positive=0.50, confidence_band_low=0.30, confidence_band_high=0.70)
        curr = _vec(p_positive=0.52, confidence_band_low=0.32, confidence_band_high=0.72)  # delta=0.02 < threshold
        result = classify_forecast_transition(prev, curr)
        assert result is None

    def test_both_none_returns_none(self):
        from app.services.forecast_delivery_service import classify_forecast_transition
        assert classify_forecast_transition(None, None) is None

    def test_below_threshold_strengthening_is_steady(self):
        from app.services.forecast_delivery_service import classify_forecast_transition
        prev = _vec(p_positive=0.50)
        curr = _vec(p_positive=0.55)  # delta=0.05 < default threshold 0.08
        result = classify_forecast_transition(prev, curr, materiality_threshold=0.08)
        # No p_positive shift above threshold and same confidence label → None
        assert result is None

    def test_custom_threshold_respected(self):
        from app.services.forecast_delivery_service import (
            classify_forecast_transition, TRANSITION_STRENGTHENED,
        )
        prev = _vec(p_positive=0.50)
        curr = _vec(p_positive=0.55)  # delta=0.05
        # With a lower threshold of 0.03, this should be strengthened
        result = classify_forecast_transition(prev, curr, materiality_threshold=0.03)
        assert result == TRANSITION_STRENGTHENED


# ---------------------------------------------------------------------------
# 7: detect_forecast_transitions (pure snapshot diff)
# ---------------------------------------------------------------------------

class TestDetectForecastTransitions:
    def test_new_vector_is_first_forecast(self):
        from app.services.forecast_delivery_service import (
            detect_forecast_transitions, TRANSITION_FIRST_FORECAST,
        )
        prev_set = []
        curr_set = [_vec(entity_key="AAPL", forecast_type="thesis_strengthening")]
        events = detect_forecast_transitions(prev_set, curr_set)
        assert len(events) == 1
        assert events[0]["transition"] == TRANSITION_FIRST_FORECAST

    def test_removed_vector_is_disappeared(self):
        from app.services.forecast_delivery_service import (
            detect_forecast_transitions, TRANSITION_DISAPPEARED,
        )
        prev_set = [_vec(entity_key="GONE")]
        curr_set = []
        events = detect_forecast_transitions(prev_set, curr_set)
        assert len(events) == 1
        assert events[0]["transition"] == TRANSITION_DISAPPEARED

    def test_material_increase_is_strengthened(self):
        from app.services.forecast_delivery_service import (
            detect_forecast_transitions, TRANSITION_STRENGTHENED,
        )
        prev_set = [_vec(entity_key="TICK", p_positive=0.40)]
        curr_set = [_vec(entity_key="TICK", p_positive=0.60)]
        events = detect_forecast_transitions(prev_set, curr_set)
        assert len(events) == 1
        assert events[0]["transition"] == TRANSITION_STRENGTHENED

    def test_material_decrease_is_weakened(self):
        from app.services.forecast_delivery_service import (
            detect_forecast_transitions, TRANSITION_WEAKENED,
        )
        prev_set = [_vec(entity_key="TICK2", p_positive=0.70)]
        curr_set = [_vec(entity_key="TICK2", p_positive=0.50)]
        events = detect_forecast_transitions(prev_set, curr_set)
        assert len(events) == 1
        assert events[0]["transition"] == TRANSITION_WEAKENED

    def test_steady_state_produces_no_event(self):
        from app.services.forecast_delivery_service import detect_forecast_transitions
        prev_set = [_vec(entity_key="STEADY", p_positive=0.50)]
        curr_set = [_vec(entity_key="STEADY", p_positive=0.51)]
        events = detect_forecast_transitions(prev_set, curr_set)
        assert events == []

    def test_multiple_vectors_multiple_events(self):
        from app.services.forecast_delivery_service import detect_forecast_transitions
        prev_set = [
            _vec(entity_key="A", forecast_type="thesis_strengthening", p_positive=0.40),
            _vec(entity_key="B", forecast_type="risk_emergence", p_positive=0.60),
        ]
        curr_set = [
            _vec(entity_key="A", forecast_type="thesis_strengthening", p_positive=0.60),  # +0.20
            # B disappeared
        ]
        events = detect_forecast_transitions(prev_set, curr_set)
        transitions = {e["transition"] for e in events}
        assert "forecast_strengthened" in transitions
        assert "forecast_disappeared" in transitions

    def test_empty_both_returns_empty(self):
        from app.services.forecast_delivery_service import detect_forecast_transitions
        assert detect_forecast_transitions([], []) == []

    def test_none_both_returns_empty(self):
        from app.services.forecast_delivery_service import detect_forecast_transitions
        assert detect_forecast_transitions(None, None) == []

    def test_event_dict_has_required_keys(self):
        from app.services.forecast_delivery_service import detect_forecast_transitions
        prev_set = []
        curr_set = [_vec(entity_key="EVT")]
        events = detect_forecast_transitions(prev_set, curr_set)
        assert len(events) == 1
        ev = events[0]
        for key in ("entity_type", "entity_key", "forecast_type", "horizon_days",
                    "transition", "previous_p_positive", "current_p_positive",
                    "previous_confidence", "current_confidence"):
            assert key in ev, f"Missing event key: {key}"

    def test_previous_p_positive_none_for_first_forecast(self):
        from app.services.forecast_delivery_service import detect_forecast_transitions
        events = detect_forecast_transitions([], [_vec(entity_key="FIRST")])
        assert events[0]["previous_p_positive"] is None

    def test_current_p_positive_none_for_disappeared(self):
        from app.services.forecast_delivery_service import detect_forecast_transitions
        events = detect_forecast_transitions([_vec(entity_key="GONE2")], [])
        assert events[0]["current_p_positive"] is None


# ---------------------------------------------------------------------------
# 8: Flags inert by default
# ---------------------------------------------------------------------------

class TestFlagsInert:
    @pytest.mark.asyncio
    async def test_no_ledger_rows_without_override(self, db):
        from app.services.forecast_delivery_service import record_forecast_transition_events
        from app.db.models import DeliveryLedger
        from sqlalchemy import select, func

        prev_set = []
        curr_set = [_vec(entity_key="INERT1")]

        # No run_override → flags default to False → inert
        result = await record_forecast_transition_events(db, prev_set, curr_set)
        assert result == []

        count_stmt = select(func.count()).select_from(DeliveryLedger)
        count = int((await db.execute(count_stmt)).scalar_one() or 0)
        assert count == 0

    @pytest.mark.asyncio
    async def test_returns_empty_list_without_override(self, db):
        from app.services.forecast_delivery_service import record_forecast_transition_events
        result = await record_forecast_transition_events(
            db,
            [_vec(entity_key="INERT2")],
            [],
        )
        assert result == []

    @pytest.mark.asyncio
    async def test_force_off_override_is_inert(self, db):
        from app.services.forecast_delivery_service import record_forecast_transition_events
        result = await record_forecast_transition_events(
            db,
            [],
            [_vec(entity_key="FORCEOFF")],
            run_override=False,
        )
        assert result == []


# ---------------------------------------------------------------------------
# 9–10: run_override=True journals and deduplicates
# ---------------------------------------------------------------------------

class TestJournaling:
    @pytest.mark.asyncio
    async def test_first_forecast_creates_ledger_row(self, db):
        from app.services.forecast_delivery_service import record_forecast_transition_events
        from app.db.models import DeliveryLedger
        from sqlalchemy import select

        result = await record_forecast_transition_events(
            db, [], [_vec(entity_key="JOUR1")], run_override=True,
        )
        assert len(result) == 1
        assert result[0]["transition"] == "first_forecast"

        rows = (await db.execute(select(DeliveryLedger))).scalars().all()
        assert len(rows) == 1
        assert rows[0].channel == "forecast_shadow"
        assert rows[0].status == "pending"

    @pytest.mark.asyncio
    async def test_strengthened_creates_ledger_row(self, db):
        from app.services.forecast_delivery_service import record_forecast_transition_events
        from app.db.models import DeliveryLedger
        from sqlalchemy import select

        prev = [_vec(entity_key="JOUR2", p_positive=0.40)]
        curr = [_vec(entity_key="JOUR2", p_positive=0.60)]
        result = await record_forecast_transition_events(db, prev, curr, run_override=True)
        assert len(result) == 1
        assert result[0]["transition"] == "forecast_strengthened"

        rows = (await db.execute(select(DeliveryLedger))).scalars().all()
        assert any(r.channel == "forecast_shadow" for r in rows)

    @pytest.mark.asyncio
    async def test_disappeared_creates_ledger_row(self, db):
        from app.services.forecast_delivery_service import record_forecast_transition_events
        result = await record_forecast_transition_events(
            db, [_vec(entity_key="JOUR3")], [], run_override=True,
        )
        assert len(result) == 1
        assert result[0]["transition"] == "forecast_disappeared"

    @pytest.mark.asyncio
    async def test_dedup_second_call_no_new_row(self, db):
        from app.services.forecast_delivery_service import record_forecast_transition_events
        from app.db.models import DeliveryLedger
        from sqlalchemy import select, func

        prev = []
        curr = [_vec(entity_key="DEDUP1")]

        # First call — creates one row
        await record_forecast_transition_events(db, prev, curr, run_override=True)
        await db.flush()

        count1_stmt = select(func.count()).select_from(DeliveryLedger)
        count1 = int((await db.execute(count1_stmt)).scalar_one() or 0)

        # Second identical call — dedup blocks
        await record_forecast_transition_events(db, prev, curr, run_override=True)
        await db.flush()

        count2_stmt = select(func.count()).select_from(DeliveryLedger)
        count2 = int((await db.execute(count2_stmt)).scalar_one() or 0)

        assert count1 == count2 == 1

    @pytest.mark.asyncio
    async def test_steady_state_writes_no_row(self, db):
        from app.services.forecast_delivery_service import record_forecast_transition_events
        from app.db.models import DeliveryLedger
        from sqlalchemy import select, func

        prev = [_vec(entity_key="STEADY2", p_positive=0.50)]
        curr = [_vec(entity_key="STEADY2", p_positive=0.51)]

        result = await record_forecast_transition_events(db, prev, curr, run_override=True)
        assert result == []

        count_stmt = select(func.count()).select_from(DeliveryLedger)
        count = int((await db.execute(count_stmt)).scalar_one() or 0)
        assert count == 0

    @pytest.mark.asyncio
    async def test_channel_is_forecast_shadow(self, db):
        from app.services.forecast_delivery_service import (
            record_forecast_transition_events, FORECAST_DELIVERY_CHANNEL,
        )
        from app.db.models import DeliveryLedger
        from sqlalchemy import select

        await record_forecast_transition_events(
            db, [], [_vec(entity_key="CHAN1")], run_override=True,
        )
        rows = (await db.execute(select(DeliveryLedger))).scalars().all()
        assert all(r.channel == FORECAST_DELIVERY_CHANNEL for r in rows)

    @pytest.mark.asyncio
    async def test_all_five_transition_types_journal(self, db):
        from app.services.forecast_delivery_service import (
            record_forecast_transition_events,
            TRANSITION_FIRST_FORECAST, TRANSITION_STRENGTHENED, TRANSITION_WEAKENED,
            TRANSITION_DISAPPEARED, TRANSITION_CONFIDENCE,
        )
        from app.db.models import DeliveryLedger
        from sqlalchemy import select

        # first_forecast: A new
        # strengthened:   B p_positive +0.25
        # weakened:       C p_positive -0.25
        # disappeared:    D gone
        # confidence_changed: E same p_positive, narrower band
        prev_set = [
            _vec(entity_key="B", forecast_type="thesis_strengthening", p_positive=0.35),
            _vec(entity_key="C", forecast_type="risk_emergence", p_positive=0.65),
            _vec(entity_key="D", forecast_type="catalyst_realization"),
            _vec(entity_key="E", forecast_type="regime_transition",
                 p_positive=0.50, confidence_band_low=0.20, confidence_band_high=0.80),
        ]
        curr_set = [
            _vec(entity_key="A", forecast_type="thesis_weakening"),   # first
            _vec(entity_key="B", forecast_type="thesis_strengthening", p_positive=0.60),  # +0.25
            _vec(entity_key="C", forecast_type="risk_emergence", p_positive=0.40),         # -0.25
            # D absent → disappeared
            _vec(entity_key="E", forecast_type="regime_transition",
                 p_positive=0.50, confidence_band_low=0.42, confidence_band_high=0.58),   # confidence_changed
        ]

        result = await record_forecast_transition_events(
            db, prev_set, curr_set, run_override=True,
        )
        transitions_found = {ev["transition"] for ev in result}
        assert TRANSITION_FIRST_FORECAST in transitions_found
        assert TRANSITION_STRENGTHENED   in transitions_found
        assert TRANSITION_WEAKENED       in transitions_found
        assert TRANSITION_DISAPPEARED    in transitions_found
        assert TRANSITION_CONFIDENCE     in transitions_found

        rows = (await db.execute(select(DeliveryLedger))).scalars().all()
        assert len(rows) == 5


# ---------------------------------------------------------------------------
# 11–12: No Notification rows, no inbox
# ---------------------------------------------------------------------------

class TestNoNotificationRows:
    @pytest.mark.asyncio
    async def test_no_notification_rows_after_journal(self, db):
        from app.services.forecast_delivery_service import record_forecast_transition_events
        from app.db.models import Notification
        from sqlalchemy import select, func

        await record_forecast_transition_events(
            db, [], [_vec(entity_key="NONOTIF")], run_override=True,
        )

        count_stmt = select(func.count()).select_from(Notification)
        count = int((await db.execute(count_stmt)).scalar_one() or 0)
        assert count == 0

    @pytest.mark.asyncio
    async def test_channel_is_not_in_app(self, db):
        from app.services.forecast_delivery_service import (
            record_forecast_transition_events, FORECAST_DELIVERY_CHANNEL,
        )
        from app.db.models import DeliveryLedger
        from sqlalchemy import select

        await record_forecast_transition_events(
            db, [], [_vec(entity_key="CHANCHECK")], run_override=True,
        )
        rows = (await db.execute(select(DeliveryLedger))).scalars().all()
        assert all(r.channel != "in_app" for r in rows)
        assert all(r.channel == FORECAST_DELIVERY_CHANNEL for r in rows)

    @pytest.mark.asyncio
    async def test_ledger_rows_never_marked_delivered(self, db):
        from app.services.forecast_delivery_service import record_forecast_transition_events
        from app.db.models import DeliveryLedger
        from sqlalchemy import select

        await record_forecast_transition_events(
            db, [], [_vec(entity_key="NODELIV")], run_override=True,
        )
        rows = (await db.execute(select(DeliveryLedger))).scalars().all()
        assert all(r.status == "pending" for r in rows)


# ---------------------------------------------------------------------------
# 13–14: AST safety checks
# ---------------------------------------------------------------------------

_SVC_PATH = (
    pathlib.Path(__file__).parent.parent.parent
    / "app" / "services" / "forecast_delivery_service.py"
)


def _load_svc_ast() -> ast.Module:
    return ast.parse(_SVC_PATH.read_text())


_FORBIDDEN_MODULE_FRAGMENTS = (
    "conviction",
    "recommendation",
    "notifications",
    "notification_service",
    "audit_log",
    "forecast_feature_builder",
    "forecast_probability_engine",
    "forecast_read_service",
    "forecast_invalidation_service",
)

_FORBIDDEN_CLASS_IMPORTS = (
    "Notification",
    "AuditLog",
)

_SOURCE_TABLE_CLASS_NAMES = (
    "ForecastVector",
    "ForecastEvidence",
    "CompanyDossier",
    "DossierFailureMode",
    "HistoricalAnalog",
    "ThesisVersion",
    "SimilarityEdge",
)


class TestNoForbiddenImports:
    def test_no_conviction_or_notification_module_imports(self):
        tree = _load_svc_ast()
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                module = (getattr(node, "module", "") or "").lower()
                for frag in _FORBIDDEN_MODULE_FRAGMENTS:
                    assert frag not in module, (
                        f"Forbidden module fragment {frag!r} in {module!r}"
                    )

    def test_no_forbidden_class_direct_imports(self):
        tree = _load_svc_ast()
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                for alias in getattr(node, "names", []):
                    name = alias.name or ""
                    for cls in _FORBIDDEN_CLASS_IMPORTS:
                        assert cls not in name, (
                            f"Forbidden class import {cls!r}"
                        )

    def test_no_source_table_class_imports(self):
        tree = _load_svc_ast()
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                for alias in getattr(node, "names", []):
                    name = alias.name or ""
                    for cls in _SOURCE_TABLE_CLASS_NAMES:
                        assert cls not in name, (
                            f"Source table class {cls!r} imported in delivery service"
                        )

    def test_no_session_add_of_non_ledger_rows(self):
        src = _SVC_PATH.read_text()
        # session.add() must not be called directly in this module —
        # all writes go through guard_delivery → loop_idempotency_service
        assert "session.add(" not in src, (
            "session.add() must not appear directly in delivery service"
        )


# ---------------------------------------------------------------------------
# 15: Null-session safety
# ---------------------------------------------------------------------------

class TestNullSessionSafety:
    @pytest.mark.asyncio
    async def test_record_with_null_session_returns_empty(self):
        from app.services.forecast_delivery_service import record_forecast_transition_events
        result = await record_forecast_transition_events(
            None, [], [_vec(entity_key="NULLS")], run_override=True,
        )
        assert result == []

    @pytest.mark.asyncio
    async def test_record_with_null_session_no_exception(self):
        from app.services.forecast_delivery_service import record_forecast_transition_events
        # Must not raise
        result = await record_forecast_transition_events(None, None, None, run_override=True)
        assert result == []


# ---------------------------------------------------------------------------
# 16: Materiality threshold respected
# ---------------------------------------------------------------------------

class TestMaterialityThreshold:
    def test_below_threshold_strengthening_is_none(self):
        from app.services.forecast_delivery_service import classify_forecast_transition
        prev = _vec(p_positive=0.50)
        curr = _vec(p_positive=0.55)
        # Default threshold is 0.08; delta=0.05 → not material
        result = classify_forecast_transition(prev, curr)
        # Could be confidence_changed if labels differ, but same band → None
        assert result is None

    def test_at_or_above_threshold_is_strengthened(self):
        from app.services.forecast_delivery_service import (
            classify_forecast_transition, TRANSITION_STRENGTHENED,
        )
        # Use values where delta clearly meets or exceeds the threshold
        # (avoids binary floating-point representation edge cases)
        prev = _vec(p_positive=0.40)
        curr = _vec(p_positive=0.50)   # delta = 0.10 > 0.08
        result = classify_forecast_transition(prev, curr, materiality_threshold=0.08)
        assert result == TRANSITION_STRENGTHENED

    def test_custom_zero_threshold_any_change_is_event(self):
        from app.services.forecast_delivery_service import (
            classify_forecast_transition, TRANSITION_STRENGTHENED,
        )
        prev = _vec(p_positive=0.50)
        curr = _vec(p_positive=0.501)
        result = classify_forecast_transition(prev, curr, materiality_threshold=0.0)
        assert result == TRANSITION_STRENGTHENED
