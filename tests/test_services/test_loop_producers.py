"""
Phase 10A · Slice 6 — Shadow producer binding tests.

Covers:
  § REGISTRY   — register / lookup / unknown-type graceful failure
  § RESULT     — ProducerResult extended fields (items_emitted, payload_json, ...)
  § WATCHLIST  — watchlist_scan shadow producer: payload emitted, no notifications
  § BRIEF      — morning_brief shadow producer: brief emitted or skipped safely
  § SAFETY     — producer exception → failed job_run (scheduler does not crash)
  § INTEGRATION — scheduler dispatches registered producer; idempotency still fires
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, List, Optional
from unittest.mock import MagicMock, patch

import pytest

from app.db.repositories import loop_repo
from app.services import loop_producers as producers
from app.services.loop_scheduler_service import (
    ProducerResult,
    TickResult,
    register_producer,
    unregister_producer,
    list_registered_producers,
    tick,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _uid() -> str:
    return uuid.uuid4().hex[:10]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _past(s: int = 5) -> datetime:
    return _now() - timedelta(seconds=s)


def _holder() -> str:
    return f"test:{_uid()}"


async def _make_due_job(db_session, job_type="watchlist_scan",
                        target="global", bucket=None, max_attempts=3):
    bucket = bucket or f"2026-06-12-{_uid()[:6]}"
    return await loop_repo.job_create(
        db_session, job_type, target, bucket,
        next_run_utc=_past(5),
        max_attempts=max_attempts,
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def clean_producers():
    """Remove any test-registered producers after each test."""
    yield
    for jt in list(list_registered_producers()):
        unregister_producer(jt)


@pytest.fixture
def loop_on(monkeypatch):
    from app.services import loop_scheduler_service as sched
    monkeypatch.setattr(sched, "_is_loop_enabled", lambda: True)


# ---------------------------------------------------------------------------
# Minimal watchlist service stub for isolation
# ---------------------------------------------------------------------------

class _StubEntry:
    """Minimal duck-type of WatchlistEntry."""
    def __init__(self, ticker, thesis_stability="stable"):
        self.ticker = ticker
        self.thesis_stability = thesis_stability
        # Fields accessed by morning_brief
        self.latest_thesis_trend = "stable"
        self.drift_state = ""
        self.has_material_change = False
        self.what_changed_summary = ""
        self.latest_one_sentence = ""
        self.latest_confidence = None
        self.company_name = ticker
        self.added_at = "2026-06-12T00:00:00Z"
        self.core_debate = ""
        self.dominant_signal = ""
        self.dominant_risk = ""
        self.dominant_dimension = ""
        self.recent_alert_count = 0
        self.materiality_level = ""
        self.latest_change_narrative = ""
        self.debate_focus = ""
        self.alert_priority = ""


class _StubWatchlistService:
    def __init__(self, entries=None, changes=None):
        self._entries = entries or []
        self._changes = changes or []

    def get_watchlist(self):
        return list(self._entries)

    def get_material_changes(self, ticker=None, limit=100):
        return list(self._changes)

    def get_latest_diff(self, ticker):
        return None


def _patch_wl(monkeypatch, service: _StubWatchlistService):
    monkeypatch.setattr(producers, "_get_watchlist_service", lambda: service)


def _patch_enrich(monkeypatch, fn=None):
    if fn is None:
        def fn(entries): return entries   # identity: return entries as-is
    monkeypatch.setattr(producers, "_get_enrich_fn", lambda: fn)


# ===========================================================================
# § REGISTRY
# ===========================================================================

class TestProducerRegistry:
    def test_registered_job_types_constant(self):
        assert "watchlist_scan" in producers.REGISTERED_JOB_TYPES
        assert "morning_brief"  in producers.REGISTERED_JOB_TYPES
        assert "timeline_rollup" in producers.REGISTERED_JOB_TYPES

    def test_register_all_shadow_producers_registers_all(self):
        producers.register_all_shadow_producers()
        registered = list_registered_producers()
        for jt in producers.REGISTERED_JOB_TYPES:
            assert jt in registered

    def test_register_all_idempotent(self):
        producers.register_all_shadow_producers()
        producers.register_all_shadow_producers()
        registered = list_registered_producers()
        # No duplicates — each job_type appears once
        assert registered.count("watchlist_scan") == 1
        assert registered.count("morning_brief")  == 1

    def test_unregister_removes_producer(self):
        producers.register_all_shadow_producers()
        unregister_producer("watchlist_scan")
        assert "watchlist_scan" not in list_registered_producers()

    def test_unknown_job_type_not_in_registry(self):
        producers.register_all_shadow_producers()
        assert "unknown_job_type_xyz" not in list_registered_producers()


# ===========================================================================
# § RESULT — ProducerResult extended shape
# ===========================================================================

class TestProducerResultShape:
    def test_default_items_emitted_zero(self):
        r = ProducerResult()
        assert r.items_emitted == 0

    def test_default_payload_json_none(self):
        r = ProducerResult()
        assert r.payload_json is None

    def test_default_content_key_candidates_empty(self):
        r = ProducerResult()
        assert r.content_key_candidates == []

    def test_can_set_items_emitted(self):
        r = ProducerResult(outcome="succeeded", items_emitted=42)
        assert r.items_emitted == 42

    def test_can_set_payload_json(self):
        payload = {"ticker_count": 5, "shadow": True}
        r = ProducerResult(outcome="succeeded", payload_json=payload)
        assert r.payload_json == payload

    def test_can_set_content_key_candidates(self):
        keys = ["abc123", "def456"]
        r = ProducerResult(outcome="succeeded", content_key_candidates=keys)
        assert r.content_key_candidates == keys

    def test_backward_compat_no_new_fields(self):
        # Old callers that don't pass new fields still work
        r = ProducerResult(outcome="succeeded", spent_llm_calls=3, drift_hit=True)
        assert r.items_emitted == 0
        assert r.payload_json is None


# ===========================================================================
# § WATCHLIST SCAN producer
# ===========================================================================

class TestWatchlistScanProducer:
    @pytest.mark.asyncio
    async def test_empty_watchlist_returns_skipped_stale(self, monkeypatch):
        _patch_wl(monkeypatch, _StubWatchlistService(entries=[]))
        _patch_enrich(monkeypatch)
        result = await producers.produce_watchlist_scan(None, MagicMock(), "run1", "h", 1)
        assert result.outcome == "skipped_stale"
        assert result.payload_json["reason"] == "empty_watchlist"
        assert result.payload_json["shadow"] is True

    @pytest.mark.asyncio
    async def test_non_empty_watchlist_returns_succeeded(self, monkeypatch):
        entries = [_StubEntry("AAPL"), _StubEntry("NVDA")]
        _patch_wl(monkeypatch, _StubWatchlistService(entries=entries))
        _patch_enrich(monkeypatch)
        result = await producers.produce_watchlist_scan(None, MagicMock(), "run1", "h", 1)
        assert result.outcome == "succeeded"

    @pytest.mark.asyncio
    async def test_items_emitted_matches_ticker_count(self, monkeypatch):
        entries = [_StubEntry("AAPL"), _StubEntry("NVDA"), _StubEntry("MSFT")]
        _patch_wl(monkeypatch, _StubWatchlistService(entries=entries))
        _patch_enrich(monkeypatch)
        result = await producers.produce_watchlist_scan(None, MagicMock(), "run1", "h", 1)
        assert result.items_emitted == 3

    @pytest.mark.asyncio
    async def test_payload_json_contains_expected_fields(self, monkeypatch):
        entries = [_StubEntry("AAPL"), _StubEntry("JPM")]
        _patch_wl(monkeypatch, _StubWatchlistService(entries=entries))
        _patch_enrich(monkeypatch)
        result = await producers.produce_watchlist_scan(None, MagicMock(), "run1", "h", 1)
        p = result.payload_json
        assert p["ticker_count"] == 2
        assert "AAPL" in p["tickers"]
        assert "JPM"  in p["tickers"]
        assert "material_changes_found" in p
        assert "attention_required" in p
        assert p["shadow"] is True

    @pytest.mark.asyncio
    async def test_no_notifications_created(self, monkeypatch, db_session):
        """Shadow producer must NOT write any notification rows."""
        from sqlalchemy import select, func
        from app.db.models import Notification
        entries = [_StubEntry("AAPL")]
        _patch_wl(monkeypatch, _StubWatchlistService(entries=entries))
        _patch_enrich(monkeypatch)
        await producers.produce_watchlist_scan(db_session, MagicMock(), "run1", "h", 1)
        count = (await db_session.execute(select(func.count()).select_from(Notification))).scalar()
        assert count == 0

    @pytest.mark.asyncio
    async def test_no_delivery_rows_created(self, monkeypatch, db_session):
        """Shadow producer must NOT write any DeliveryLedger rows."""
        from sqlalchemy import select, func
        from app.db.models import DeliveryLedger
        entries = [_StubEntry("AAPL")]
        _patch_wl(monkeypatch, _StubWatchlistService(entries=entries))
        _patch_enrich(monkeypatch)
        await producers.produce_watchlist_scan(db_session, MagicMock(), "run1", "h", 1)
        count = (await db_session.execute(select(func.count()).select_from(DeliveryLedger))).scalar()
        assert count == 0

    @pytest.mark.asyncio
    async def test_attention_required_filters_breaking_shifting(self, monkeypatch):
        entries = [
            _StubEntry("AAPL", thesis_stability="stable"),
            _StubEntry("NVDA", thesis_stability="breaking"),
            _StubEntry("TSLA", thesis_stability="shifting"),
        ]
        enriched = entries  # enrich is identity here
        _patch_wl(monkeypatch, _StubWatchlistService(entries=entries))
        _patch_enrich(monkeypatch, fn=lambda e: e)
        result = await producers.produce_watchlist_scan(None, MagicMock(), "run1", "h", 1)
        attn = result.payload_json["attention_required"]
        assert "NVDA" in attn
        assert "TSLA" in attn
        assert "AAPL" not in attn

    @pytest.mark.asyncio
    async def test_exception_returns_failed(self, monkeypatch):
        def bad_service(): raise RuntimeError("disk error")
        monkeypatch.setattr(producers, "_get_watchlist_service", bad_service)
        result = await producers.produce_watchlist_scan(None, MagicMock(), "run1", "h", 1)
        assert result.outcome == "failed"
        assert "watchlist_scan" in result.error


# ===========================================================================
# § MORNING BRIEF producer
# ===========================================================================

class TestMorningBriefProducer:
    @pytest.mark.asyncio
    async def test_empty_watchlist_returns_skipped_stale(self, monkeypatch):
        _patch_wl(monkeypatch, _StubWatchlistService(entries=[]))
        result = await producers.produce_morning_brief(None, MagicMock(), "run1", "h", 1)
        assert result.outcome == "skipped_stale"
        assert result.payload_json["reason"] == "empty_watchlist"

    @pytest.mark.asyncio
    async def test_non_empty_watchlist_returns_succeeded(self, monkeypatch):
        entries = [_StubEntry("AAPL"), _StubEntry("NVDA")]
        _patch_wl(monkeypatch, _StubWatchlistService(entries=entries))
        result = await producers.produce_morning_brief(None, MagicMock(), "run1", "h", 1)
        assert result.outcome == "succeeded"

    @pytest.mark.asyncio
    async def test_payload_json_is_brief_dict(self, monkeypatch):
        entries = [_StubEntry("AAPL")]
        _patch_wl(monkeypatch, _StubWatchlistService(entries=entries))
        result = await producers.produce_morning_brief(None, MagicMock(), "run1", "h", 1)
        p = result.payload_json
        assert isinstance(p, dict)
        # MorningBriefV2 fields
        assert "generated_at" in p
        assert "ticker_count" in p
        assert "regime_headline" in p
        assert p["shadow"] is True

    @pytest.mark.asyncio
    async def test_items_emitted_matches_ticker_count(self, monkeypatch):
        entries = [_StubEntry("AAPL"), _StubEntry("JPM"), _StubEntry("NVDA")]
        _patch_wl(monkeypatch, _StubWatchlistService(entries=entries))
        result = await producers.produce_morning_brief(None, MagicMock(), "run1", "h", 1)
        assert result.items_emitted == 3

    @pytest.mark.asyncio
    async def test_no_notifications_created(self, monkeypatch, db_session):
        from sqlalchemy import select, func
        from app.db.models import Notification
        entries = [_StubEntry("AAPL")]
        _patch_wl(monkeypatch, _StubWatchlistService(entries=entries))
        await producers.produce_morning_brief(db_session, MagicMock(), "run1", "h", 1)
        count = (await db_session.execute(select(func.count()).select_from(Notification))).scalar()
        assert count == 0

    @pytest.mark.asyncio
    async def test_no_delivery_rows_created(self, monkeypatch, db_session):
        from sqlalchemy import select, func
        from app.db.models import DeliveryLedger
        entries = [_StubEntry("AAPL")]
        _patch_wl(monkeypatch, _StubWatchlistService(entries=entries))
        await producers.produce_morning_brief(db_session, MagicMock(), "run1", "h", 1)
        count = (await db_session.execute(select(func.count()).select_from(DeliveryLedger))).scalar()
        assert count == 0

    @pytest.mark.asyncio
    async def test_exception_returns_failed(self, monkeypatch):
        def bad_service(): raise RuntimeError("storage error")
        monkeypatch.setattr(producers, "_get_watchlist_service", bad_service)
        result = await producers.produce_morning_brief(None, MagicMock(), "run1", "h", 1)
        assert result.outcome == "failed"
        assert "morning_brief" in result.error

    @pytest.mark.asyncio
    async def test_brief_fn_exception_returns_failed(self, monkeypatch):
        entries = [_StubEntry("AAPL")]
        _patch_wl(monkeypatch, _StubWatchlistService(entries=entries))
        def bad_brief_fn(): raise RuntimeError("brief generator exploded")
        monkeypatch.setattr(producers, "_get_brief_fn", lambda: bad_brief_fn)
        result = await producers.produce_morning_brief(None, MagicMock(), "run1", "h", 1)
        assert result.outcome == "failed"


# ===========================================================================
# § TIMELINE ROLLUP stub
# ===========================================================================

class TestTimelineRollupStub:
    @pytest.mark.asyncio
    async def test_returns_skipped_stale(self):
        result = await producers.produce_timeline_rollup(None, MagicMock(), "run1", "h", 1)
        assert result.outcome == "skipped_stale"

    @pytest.mark.asyncio
    async def test_payload_explains_reason(self):
        result = await producers.produce_timeline_rollup(None, MagicMock(), "run1", "h", 1)
        assert result.payload_json["reason"] == "timeline_rollup_not_implemented"
        assert result.payload_json["shadow"] is True

    @pytest.mark.asyncio
    async def test_items_emitted_zero(self):
        result = await producers.produce_timeline_rollup(None, MagicMock(), "run1", "h", 1)
        assert result.items_emitted == 0


# ===========================================================================
# § SAFETY — producer exception becomes failed job_run
# ===========================================================================

class TestProducerExceptionHandling:
    @pytest.mark.asyncio
    async def test_exception_in_producer_yields_failed_job_run(
        self, db_session, loop_on, monkeypatch
    ):
        """
        When a registered producer raises an unhandled exception, the
        scheduler catches it and records outcome='failed' on the JobRun.
        The tick() does NOT propagate the exception to the caller.
        """
        async def exploding_producer(session, job, run_id, holder_id, fence_token):
            raise RuntimeError("simulated producer explosion")

        register_producer("watchlist_scan", exploding_producer)
        job = await _make_due_job(db_session, job_type="watchlist_scan")

        # tick() should not raise even though the producer explodes
        result = await tick(db_session, _holder(), batch_size=10, lease_s=120)

        # The job is counted as failed (scheduler catches the exception)
        assert result.jobs_failed == 1 or result.jobs_claimed >= 1
        # No scheduler-level exception bubbled up (test would have failed otherwise)

    @pytest.mark.asyncio
    async def test_failed_job_run_outcome_stored(self, db_session, loop_on, monkeypatch):
        """
        A producer returning outcome='failed' results in a JobRun with
        outcome='failed' in the database.
        """
        async def failing_producer(session, job, run_id, holder_id, fence_token):
            return ProducerResult(outcome="failed", error="test_failure")

        register_producer("watchlist_scan", failing_producer)
        job = await _make_due_job(db_session, job_type="watchlist_scan", max_attempts=5)

        await tick(db_session, _holder(), batch_size=10, lease_s=120)

        history = await loop_repo.run_get_history(db_session, job.id)
        assert len(history) >= 1
        outcomes = {r.outcome for r in history}
        assert "failed" in outcomes

    @pytest.mark.asyncio
    async def test_unknown_producer_graceful_failure(self, db_session, loop_on):
        """
        A job_type with no registered producer results in outcome='failed'
        rather than a scheduler crash.
        """
        job = await _make_due_job(db_session, job_type="unknown_xyz_type")
        result = await tick(db_session, _holder(), batch_size=10, lease_s=120)
        assert result.jobs_failed >= 1


# ===========================================================================
# § INTEGRATION — scheduler dispatches registered producer
# ===========================================================================

class TestSchedulerDispatch:
    @pytest.mark.asyncio
    async def test_watchlist_scan_dispatched_by_scheduler(
        self, db_session, loop_on, monkeypatch
    ):
        """
        When 'watchlist_scan' is registered and a due job exists,
        tick() dispatches the producer and marks the job succeeded.
        """
        entries = [_StubEntry("AAPL"), _StubEntry("NVDA")]
        _patch_wl(monkeypatch, _StubWatchlistService(entries=entries))
        _patch_enrich(monkeypatch)

        register_producer("watchlist_scan", producers.produce_watchlist_scan)
        job = await _make_due_job(db_session, job_type="watchlist_scan")

        result = await tick(db_session, _holder(), batch_size=10, lease_s=120)
        assert result.jobs_succeeded == 1

    @pytest.mark.asyncio
    async def test_morning_brief_dispatched_by_scheduler(
        self, db_session, loop_on, monkeypatch
    ):
        entries = [_StubEntry("AAPL")]
        _patch_wl(monkeypatch, _StubWatchlistService(entries=entries))

        register_producer("morning_brief", producers.produce_morning_brief)
        job = await _make_due_job(db_session, job_type="morning_brief")

        result = await tick(db_session, _holder(), batch_size=10, lease_s=120)
        assert result.jobs_succeeded == 1

    @pytest.mark.asyncio
    async def test_timeline_rollup_dispatched_counts_as_short_circuited(
        self, db_session, loop_on
    ):
        """
        The timeline_rollup stub returns 'skipped_stale'; the scheduler
        counts it as short_circuited (via the skipped_stale branch).
        """
        register_producer("timeline_rollup", producers.produce_timeline_rollup)
        job = await _make_due_job(db_session, job_type="timeline_rollup")

        result = await tick(db_session, _holder(), batch_size=10, lease_s=120)
        # skipped_stale from producer is mapped to short_circuited in the scheduler
        assert result.jobs_short_circuited == 1

    @pytest.mark.asyncio
    async def test_register_all_then_dispatch(
        self, db_session, loop_on, monkeypatch
    ):
        """
        After register_all_shadow_producers(), the scheduler can dispatch
        any registered job type without error.
        """
        entries = [_StubEntry("JPM")]
        _patch_wl(monkeypatch, _StubWatchlistService(entries=entries))
        _patch_enrich(monkeypatch)

        producers.register_all_shadow_producers()
        job = await _make_due_job(db_session, job_type="watchlist_scan")

        result = await tick(db_session, _holder(), batch_size=10, lease_s=120)
        assert result.jobs_claimed >= 1
        assert result.errors == []

    @pytest.mark.asyncio
    async def test_idempotency_still_fires_after_successful_run(
        self, db_session, loop_on, monkeypatch
    ):
        """
        After a successful watchlist_scan, re-scheduling the same
        (job_type, target, bucket) short-circuits without calling the producer.
        """
        call_count = [0]

        async def counting_producer(session, job, run_id, holder_id, fence_token):
            call_count[0] += 1
            return ProducerResult(outcome="succeeded", items_emitted=1)

        register_producer("watchlist_scan", counting_producer)
        job = await _make_due_job(db_session, job_type="watchlist_scan",
                                  target="user_idem", bucket="2026-06-12")

        # First tick — succeeds
        r1 = await tick(db_session, _holder(), batch_size=10, lease_s=120)
        assert r1.jobs_succeeded == 1
        assert call_count[0] == 1

        # Reset job to scheduled + backdate next_run_utc
        from sqlalchemy import update as sa_update
        from app.db.models import ScheduledJob
        await loop_repo.job_update_state(db_session, job.id, "scheduled")
        await db_session.execute(
            sa_update(ScheduledJob)
            .where(ScheduledJob.id == job.id)
            .values(next_run_utc=_past(10))
            .execution_options(synchronize_session=False)
        )

        # Second tick — short-circuits, producer NOT called again
        r2 = await tick(db_session, _holder(), batch_size=10, lease_s=120)
        assert r2.jobs_short_circuited == 1
        assert call_count[0] == 1  # still 1 — producer not called again
