"""
Phase 9G Reliability Patch — Canary telemetry persistence tests.

Validates:
  1.  Decision event is written to audit_log.
  2.  Outcome event is written to audit_log.
  3.  Injected outcome is persisted (cohort="injected").
  4.  Wall-cap fallback correctly detected and flagged.
  5.  Persisted counts survive in-memory telemetry reset (process-restart sim).
  6.  No prompt / dossier / model output stored in audit_log rows.
  7.  canary_audit count helpers return correct values.
  8.  in-memory dossier_canary_telemetry still works after patch.
  9.  Null-session safety on all canary_audit functions.
  10. build_persisted_snapshot returns all required keys.

Uses in-memory SQLite — no Postgres instance needed.
"""

from __future__ import annotations

import json
import pytest
import pytest_asyncio
from datetime import datetime, timezone, timedelta
from typing import Optional


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _future(hours: int = 1) -> datetime:
    return _now() + timedelta(hours=hours)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def fresh_engine():
    try:
        from sqlalchemy.ext.asyncio import create_async_engine
        from app.db.models import Base

        engine = create_async_engine(
            "sqlite+aiosqlite:///:memory:",
            echo=False,
            connect_args={"check_same_thread": False},
        )
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        yield engine
        await engine.dispose()

    except ImportError:
        pytest.skip("aiosqlite or sqlalchemy not installed")


@pytest_asyncio.fixture
async def session(fresh_engine):
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    factory = async_sessionmaker(fresh_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as s:
        yield s


# ---------------------------------------------------------------------------
# 1. Decision event written to audit_log
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_decision_event_written(session):
    from app.services.canary_audit import append_canary_decision, count_decisions

    row_id = await append_canary_decision(
        session,
        session_id="sess-aaa-001",
        cohort="injected",
        ticker="NVDA",
        token_count=245,
        block_tokens=245,
    )
    await session.commit()

    assert row_id is not None

    count = await count_decisions(session)
    assert count == 1


@pytest.mark.asyncio
async def test_decision_event_fields(session):
    """Decision row must have correct resource/action and non-sensitive payload."""
    from app.services.canary_audit import append_canary_decision
    from app.db.models import AuditLog
    from sqlalchemy import select

    await append_canary_decision(
        session,
        session_id="sess-bbb-002",
        cohort="control",
        ticker="AAPL",
        token_count=180,
        block_tokens=180,
    )
    await session.commit()

    result = await session.execute(
        select(AuditLog).where(AuditLog.action == "canary_decision")
    )
    row = result.scalar_one()

    assert row.resource == "dossier_injection"
    assert row.action   == "canary_decision"
    assert row.user_id  is None
    assert row.resource_id == "sess-bbb-002"

    payload = json.loads(row.user_agent)
    assert payload["session_id"] == "sess-bbb-002"
    assert payload["cohort"]     == "control"
    assert payload["ticker"]     == "AAPL"
    assert payload["token_count"] == 180


# ---------------------------------------------------------------------------
# 2. Outcome event written to audit_log
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_outcome_event_written(session):
    from app.services.canary_audit import append_canary_outcome, count_outcomes

    row_id = await append_canary_outcome(
        session,
        session_id="sess-ccc-003",
        cohort="injected",
        ticker="NVDA",
        injected=True,
        fallback=False,
        wall_cap_fallback=False,
        conviction=0.72,
        specificity=4.0,
        cve=0.12,
        latency_ms=3210,
    )
    await session.commit()

    assert row_id is not None
    count = await count_outcomes(session)
    assert count == 1


@pytest.mark.asyncio
async def test_outcome_event_fields(session):
    """Outcome row must have correct resource/action and expected payload keys."""
    from app.services.canary_audit import append_canary_outcome
    from app.db.models import AuditLog
    from sqlalchemy import select

    await append_canary_outcome(
        session,
        session_id="sess-ddd-004",
        cohort="injected",
        ticker="MSFT",
        injected=True,
        fallback=False,
        wall_cap_fallback=False,
        conviction=0.68,
        specificity=5.0,
        cve=0.09,
        latency_ms=2800,
    )
    await session.commit()

    result = await session.execute(
        select(AuditLog).where(AuditLog.action == "canary_outcome")
    )
    row = result.scalar_one()

    assert row.resource == "dossier_injection"
    assert row.action   == "canary_outcome"
    assert row.user_id  is None

    payload = json.loads(row.user_agent)
    assert payload["session_id"] == "sess-ddd-004"
    assert payload["cohort"]     == "injected"
    assert payload["ticker"]     == "MSFT"
    assert payload["injected"]   is True
    assert payload["fallback"]   is False
    assert payload["wall_cap_fallback"] is False
    assert payload["conviction"] == pytest.approx(0.68)
    assert payload["latency_ms"] == 2800


# ---------------------------------------------------------------------------
# 3. Injected outcome persisted on fallback
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_injected_outcome_persisted_on_fallback(session):
    """An injected cohort outcome with fallback=True must still be written."""
    from app.services.canary_audit import (
        append_canary_outcome,
        count_outcomes,
        count_injected_outcomes,
    )

    await append_canary_outcome(
        session,
        session_id="sess-eee-005",
        cohort="injected",
        ticker="NVDA",
        injected=True,
        fallback=True,
        wall_cap_fallback=True,
        conviction=0.0,
        specificity=0.0,
        cve=None,
        latency_ms=57000,
    )
    await session.commit()

    assert await count_outcomes(session) == 1
    assert await count_injected_outcomes(session) == 1


# ---------------------------------------------------------------------------
# 4. Wall-cap fallback detection
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_wall_cap_fallback_counted(session):
    """wall_cap_fallback=True must be visible in count_wall_cap_fallbacks."""
    from app.services.canary_audit import (
        append_canary_outcome,
        count_wall_cap_fallbacks,
    )

    # One wall-cap fallback
    await append_canary_outcome(
        session,
        session_id="sess-fff-006",
        cohort="injected",
        ticker="NVDA",
        injected=True,
        fallback=True,
        wall_cap_fallback=True,
        conviction=0.0,
        specificity=0.0,
        cve=None,
        latency_ms=57000,
    )
    # One normal outcome (no wall-cap)
    await append_canary_outcome(
        session,
        session_id="sess-fff-007",
        cohort="control",
        ticker="AAPL",
        injected=False,
        fallback=False,
        wall_cap_fallback=False,
        conviction=0.65,
        specificity=3.0,
        cve=0.08,
        latency_ms=2200,
    )
    await session.commit()

    assert await count_wall_cap_fallbacks(session) == 1


def test_wall_cap_fallback_detection_logic():
    """The fallback detection expression must catch both fallback shapes."""
    def _is_fallback(conclusion: str, score: Optional[float]) -> tuple:
        score_zero = isinstance(score, float) and score == 0.0
        conc_lower = conclusion.lower()
        wall_cap   = score_zero and "wall cap exceeded" in conc_lower
        fallback   = score_zero and (
            "unavailable" in conc_lower or wall_cap
        )
        return fallback, wall_cap

    # Generic synthesis fallback
    fb, wc = _is_fallback("Synthesis unavailable — httpx timeout.", 0.0)
    assert fb is True
    assert wc is False

    # Wall-cap fallback (exact production conclusion string)
    fb, wc = _is_fallback("Could not synthesize — wall cap exceeded.", 0.0)
    assert fb is True
    assert wc is True

    # Normal result — should not be flagged
    fb, wc = _is_fallback("NVDA has strong AI tailwinds at 28x EV/EBITDA.", 0.72)
    assert fb is False
    assert wc is False

    # score_zero but conclusion has no fallback keywords
    fb, wc = _is_fallback("Neutral outlook with limited upside.", 0.0)
    assert fb is False
    assert wc is False


# ---------------------------------------------------------------------------
# 5. Persisted counts survive in-memory telemetry reset
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_persisted_counts_survive_reset(session):
    """Audit_log counts must be unaffected by dossier_canary_telemetry.reset()."""
    from app.services.canary_audit import (
        append_canary_decision,
        append_canary_outcome,
        count_decisions,
        count_outcomes,
    )
    from app.services import dossier_canary_telemetry as _tel

    # Write events to audit_log.
    await append_canary_decision(
        session,
        session_id="sess-reset-001",
        cohort="injected",
        ticker="NVDA",
        token_count=245,
        block_tokens=245,
    )
    await append_canary_outcome(
        session,
        session_id="sess-reset-001",
        cohort="injected",
        ticker="NVDA",
        injected=True,
        fallback=False,
        wall_cap_fallback=False,
        conviction=0.71,
        specificity=3.5,
        cve=0.10,
        latency_ms=3000,
    )
    await session.commit()

    # Also record in-memory so we have something to reset.
    _tel.record_decision(
        session_id="sess-reset-001",
        cohort="injected",
        ticker="NVDA",
        canary_pct=1,
        token_count=245,
        facets=[],
        staleness="fresh",
        dossier_age_days=None,
        prior_stance=None,
    )

    assert _tel.snapshot()["canary"]["decision_total"] == 1

    # Simulate process restart by clearing in-memory state.
    _tel.reset()
    assert _tel.snapshot()["canary"]["decision_total"] == 0

    # Audit_log counts must still reflect the persisted events.
    assert await count_decisions(session) == 1
    assert await count_outcomes(session)  == 1


# ---------------------------------------------------------------------------
# 6. No prompt / dossier / model output stored
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_no_sensitive_data_in_audit_rows(session):
    """Audit rows must contain ONLY the approved non-sensitive telemetry keys."""
    from app.services.canary_audit import append_canary_decision, append_canary_outcome
    from app.db.models import AuditLog
    from sqlalchemy import select

    ALLOWED_DECISION_KEYS = {
        "session_id", "cohort", "ticker", "token_count", "block_tokens"
    }
    ALLOWED_OUTCOME_KEYS = {
        "session_id", "cohort", "ticker", "injected", "fallback",
        "wall_cap_fallback", "conviction", "specificity", "cve", "latency_ms"
    }
    FORBIDDEN_KEYS = {
        "prompt", "dossier", "model_output", "raw_output", "payload",
        "question", "block_str", "context_block", "bear_thesis", "bull_thesis",
        "conclusion", "answer", "direct_answer",
    }

    await append_canary_decision(
        session,
        session_id="sess-safe-dec",
        cohort="injected",
        ticker="TSLA",
        token_count=200,
        block_tokens=200,
    )
    await append_canary_outcome(
        session,
        session_id="sess-safe-out",
        cohort="control",
        ticker="TSLA",
        injected=False,
        fallback=False,
        wall_cap_fallback=False,
        conviction=0.55,
        specificity=2.0,
        cve=0.05,
        latency_ms=1800,
    )
    await session.commit()

    result = await session.execute(select(AuditLog).where(AuditLog.resource == "dossier_injection"))
    rows = result.scalars().all()

    for row in rows:
        payload = json.loads(row.user_agent)
        keys = set(payload.keys())

        # No forbidden keys
        assert not keys & FORBIDDEN_KEYS, (
            f"Row {row.action} contains forbidden keys: {keys & FORBIDDEN_KEYS}"
        )

        # Only allowed keys
        if row.action == "canary_decision":
            assert keys <= ALLOWED_DECISION_KEYS, (
                f"Unexpected keys in decision payload: {keys - ALLOWED_DECISION_KEYS}"
            )
        elif row.action == "canary_outcome":
            assert keys <= ALLOWED_OUTCOME_KEYS, (
                f"Unexpected keys in outcome payload: {keys - ALLOWED_OUTCOME_KEYS}"
            )


# ---------------------------------------------------------------------------
# 7. Count helper correctness
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_count_helpers_are_correct(session):
    """count_injected_outcomes and count_control_outcomes must be accurate."""
    from app.services.canary_audit import (
        append_canary_outcome,
        count_outcomes,
        count_injected_outcomes,
        count_control_outcomes,
        count_wall_cap_fallbacks,
    )

    rows = [
        dict(session_id="s1", cohort="injected", ticker="NVDA", injected=True,
             fallback=False, wall_cap_fallback=False, conviction=0.7,
             specificity=3.0, cve=0.1, latency_ms=2000),
        dict(session_id="s2", cohort="injected", ticker="AAPL", injected=True,
             fallback=True, wall_cap_fallback=True, conviction=0.0,
             specificity=0.0, cve=None, latency_ms=57000),
        dict(session_id="s3", cohort="control", ticker="MSFT", injected=False,
             fallback=False, wall_cap_fallback=False, conviction=0.65,
             specificity=2.5, cve=0.08, latency_ms=2100),
        dict(session_id="s4", cohort="control", ticker="GOOG", injected=False,
             fallback=False, wall_cap_fallback=False, conviction=0.60,
             specificity=2.0, cve=0.07, latency_ms=1900),
    ]
    for r in rows:
        await append_canary_outcome(session, **r)
    await session.commit()

    assert await count_outcomes(session)          == 4
    assert await count_injected_outcomes(session) == 2
    assert await count_control_outcomes(session)  == 2
    assert await count_wall_cap_fallbacks(session) == 1


# ---------------------------------------------------------------------------
# 8. In-memory telemetry still works after patch
# ---------------------------------------------------------------------------

def test_in_memory_telemetry_still_works():
    """dossier_canary_telemetry in-memory recording must be unaffected."""
    from app.services import dossier_canary_telemetry as _tel

    _tel.reset()

    _tel.record_decision(
        session_id="mem-sess-001",
        cohort="injected",
        ticker="NVDA",
        canary_pct=1,
        token_count=245,
        facets=["momentum", "earnings"],
        staleness="fresh",
        dossier_age_days=2.5,
        prior_stance="bullish",
    )
    _tel.record_outcome(
        session_id="mem-sess-001",
        cohort="injected",
        ticker="NVDA",
        stance="bullish",
        conviction=0.72,
        change_vector_len=80,
        conclusion_len=200,
        specificity=4.0,
        fallback_used=False,
        latency_s=3.21,
        prior_challenged=False,
    )

    snap = _tel.snapshot()
    assert snap["canary"]["decision_total"] == 1
    assert snap["canary"]["outcome_total"]  == 1
    assert snap["conviction"]["injected_n"] == 1
    assert snap["conviction"]["injected_mean"] == pytest.approx(0.72)

    _tel.reset()


def test_wall_cap_counter_in_memory():
    """record_wall_cap_fallback must increment the in-memory counter."""
    from app.services import dossier_canary_telemetry as _tel

    _tel.reset()
    assert _tel.snapshot()["canary"]["wall_cap_fallback_count"] == 0

    _tel.record_wall_cap_fallback()
    _tel.record_wall_cap_fallback()

    assert _tel.snapshot()["canary"]["wall_cap_fallback_count"] == 2

    _tel.reset()
    assert _tel.snapshot()["canary"]["wall_cap_fallback_count"] == 0


# ---------------------------------------------------------------------------
# 9. Null-session safety
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_null_session_safety():
    """All canary_audit functions return falsy and never raise on None session."""
    from app.services.canary_audit import (
        append_canary_decision,
        append_canary_outcome,
        count_decisions,
        count_outcomes,
        count_injected_outcomes,
        count_control_outcomes,
        count_wall_cap_fallbacks,
        latest_event_at,
        build_persisted_snapshot,
    )

    assert await append_canary_decision(
        None, session_id="x", cohort="injected", ticker="X",
        token_count=0, block_tokens=0
    ) is None

    assert await append_canary_outcome(
        None, session_id="x", cohort="injected", ticker="X",
        injected=True, fallback=False, wall_cap_fallback=False,
        conviction=None, specificity=None, cve=None, latency_ms=None
    ) is None

    assert await count_decisions(None) == 0
    assert await count_outcomes(None)  == 0
    assert await count_injected_outcomes(None) == 0
    assert await count_control_outcomes(None)  == 0
    assert await count_wall_cap_fallbacks(None) == 0
    assert await latest_event_at(None) is None

    snap = await build_persisted_snapshot(None)
    assert snap["decision_count"]          == 0
    assert snap["outcome_count"]           == 0
    assert snap["injected_outcome_count"]  == 0
    assert snap["control_outcome_count"]   == 0
    assert snap["wall_cap_fallback_count"] == 0
    assert snap["latest_event_at"]         is None


# ---------------------------------------------------------------------------
# 10. build_persisted_snapshot returns all required keys
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_build_persisted_snapshot_keys(session):
    """build_persisted_snapshot must include all spec-required keys."""
    from app.services.canary_audit import (
        append_canary_decision,
        append_canary_outcome,
        build_persisted_snapshot,
    )

    await append_canary_decision(
        session,
        session_id="snap-dec-001",
        cohort="injected",
        ticker="NVDA",
        token_count=200,
        block_tokens=200,
    )
    await append_canary_outcome(
        session,
        session_id="snap-out-001",
        cohort="injected",
        ticker="NVDA",
        injected=True,
        fallback=False,
        wall_cap_fallback=False,
        conviction=0.70,
        specificity=3.5,
        cve=0.09,
        latency_ms=2900,
    )
    await session.commit()

    snap = await build_persisted_snapshot(session)

    required_keys = {
        "decision_count",
        "outcome_count",
        "injected_outcome_count",
        "control_outcome_count",
        "wall_cap_fallback_count",
        "latest_event_at",
    }
    assert required_keys <= set(snap.keys()), (
        f"Missing keys: {required_keys - set(snap.keys())}"
    )
    assert snap["decision_count"]         == 1
    assert snap["outcome_count"]          == 1
    assert snap["injected_outcome_count"] == 1
    assert snap["control_outcome_count"]  == 0
    assert snap["latest_event_at"] is not None


# ---------------------------------------------------------------------------
# 11. latest_event_at returns the most recent timestamp
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_latest_event_at(session):
    """latest_event_at must return the created_at of the most recent event."""
    from app.services.canary_audit import (
        append_canary_decision,
        append_canary_outcome,
        latest_event_at,
    )

    assert await latest_event_at(session) is None

    await append_canary_decision(
        session,
        session_id="lat-sess-1",
        cohort="control",
        ticker="AAPL",
        token_count=0,
        block_tokens=0,
    )
    await session.commit()

    ts = await latest_event_at(session)
    assert ts is not None
    # Should be within the last 10 seconds.
    delta = abs((datetime.now(timezone.utc) - ts.replace(tzinfo=timezone.utc)).total_seconds())
    assert delta < 10, f"latest_event_at is too old: {delta}s ago"
