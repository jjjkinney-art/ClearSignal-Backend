"""
Phase 10B · Slice 5 — Watchlist shadow delivery tests.

Covers:
  § ENQUEUE    — material change creates delivery_ledger row; ticker, severity, source correct
  § DEDUP      — duplicate scan run suppresses second delivery (suppressed_duplicate)
  § SAFETY     — no Notification rows; no external send; scan payload fields present
  § ITEMS      — items_emitted = ticker count; deliveries_enqueued in payload_json
  § ERRORS     — enqueue failure does not crash producer; payload records error count
  § GUARDRAILS — shadow delivery respects quiet-hours guardrail
  § TICK       — scheduler tick with watchlist_scan creates delivery_ledger rows
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services import loop_producers as producers
from app.services.loop_scheduler_service import (
    ProducerResult,
    register_producer,
    unregister_producer,
    list_registered_producers,
    tick,
)
from app.services import loop_delivery_service as ds
from app.db.repositories import loop_repo


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


def _make_change(
    ticker: str = "AAPL",
    change_type: str = "confidence_collapse",
    severity: str = "high",
    materiality_score: float = 0.75,
    event_id: Optional[str] = None,
) -> Any:
    """Return a minimal MaterialChangeEvent-like object."""
    from app.schemas import MaterialChangeEvent
    return MaterialChangeEvent(
        ticker=ticker,
        severity=severity,
        summary=f"Material change on {ticker}",
        timestamp=datetime.now(timezone.utc).isoformat(),
        change_type=change_type,
        event_id=event_id or str(uuid.uuid4()),
        materiality_score=materiality_score,
    )


# ---------------------------------------------------------------------------
# Minimal watchlist stubs (re-used from test_loop_producers pattern)
# ---------------------------------------------------------------------------

class _StubEntry:
    def __init__(self, ticker, thesis_stability="stable"):
        self.ticker = ticker
        self.thesis_stability = thesis_stability
        self.latest_thesis_trend = "stable"
        self.drift_state = ""
        self.has_material_change = False
        self.what_changed_summary = ""
        self.latest_one_sentence = ""
        self.latest_confidence = None
        self.company_name = ticker
        self.added_at = "2026-06-13T00:00:00Z"
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


def _patch_wl(monkeypatch, svc):
    monkeypatch.setattr(producers, "_get_watchlist_service", lambda: svc)


def _patch_enrich(monkeypatch, fn=None):
    if fn is None:
        def fn(entries): return entries
    monkeypatch.setattr(producers, "_get_enrich_fn", lambda: fn)


async def _make_due_job(db_session, job_type="watchlist_scan",
                        target="AAPL", bucket=None, max_attempts=3):
    bucket = bucket or f"2026-06-13-{_uid()[:6]}"
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
    yield
    for jt in list(list_registered_producers()):
        unregister_producer(jt)


@pytest.fixture
def loop_on(monkeypatch):
    from app.services import loop_scheduler_service as sched
    monkeypatch.setattr(sched, "_is_loop_enabled", lambda: True)


# ===========================================================================
# § ENQUEUE — material change creates delivery ledger row
# ===========================================================================

class TestShadowEnqueue:
    @pytest.mark.asyncio
    async def test_material_change_creates_delivery_row(self, monkeypatch, db_session):
        from sqlalchemy import select, func
        from app.db.models import DeliveryLedger

        change = _make_change("AAPL")
        entries = [_StubEntry("AAPL")]
        _patch_wl(monkeypatch, _StubWatchlistService(entries=entries, changes=[change]))
        _patch_enrich(monkeypatch)

        await producers.produce_watchlist_scan(db_session, MagicMock(), "r1", "h", 1)

        count = (await db_session.execute(
            select(func.count()).select_from(DeliveryLedger)
        )).scalar()
        assert count == 1

    @pytest.mark.asyncio
    async def test_multiple_changes_create_multiple_rows(self, monkeypatch, db_session):
        from sqlalchemy import select, func
        from app.db.models import DeliveryLedger

        changes = [_make_change("AAPL"), _make_change("NVDA"), _make_change("MSFT")]
        entries = [_StubEntry(c.ticker) for c in changes]
        _patch_wl(monkeypatch, _StubWatchlistService(entries=entries, changes=changes))
        _patch_enrich(monkeypatch)

        await producers.produce_watchlist_scan(db_session, MagicMock(), "r1", "h", 1)

        count = (await db_session.execute(
            select(func.count()).select_from(DeliveryLedger)
        )).scalar()
        assert count == 3

    @pytest.mark.asyncio
    async def test_delivery_row_channel_is_in_app(self, monkeypatch, db_session):
        from sqlalchemy import select
        from app.db.models import DeliveryLedger

        change = _make_change("AAPL")
        _patch_wl(monkeypatch, _StubWatchlistService(
            entries=[_StubEntry("AAPL")], changes=[change]
        ))
        _patch_enrich(monkeypatch)

        await producers.produce_watchlist_scan(db_session, MagicMock(), "r1", "h", 1)

        row = (await db_session.execute(select(DeliveryLedger))).scalars().first()
        assert row is not None
        assert row.channel == "in_app"

    @pytest.mark.asyncio
    async def test_delivery_row_target_key_is_ticker(self, monkeypatch, db_session):
        from sqlalchemy import select
        from app.db.models import DeliveryLedger

        change = _make_change("NVDA")
        _patch_wl(monkeypatch, _StubWatchlistService(
            entries=[_StubEntry("NVDA")], changes=[change]
        ))
        _patch_enrich(monkeypatch)

        await producers.produce_watchlist_scan(db_session, MagicMock(), "r1", "h", 1)

        row = (await db_session.execute(select(DeliveryLedger))).scalars().first()
        assert row is not None
        assert row.target_key == "NVDA"

    @pytest.mark.asyncio
    async def test_delivery_row_status_pending(self, monkeypatch, db_session):
        from sqlalchemy import select
        from app.db.models import DeliveryLedger

        change = _make_change("AAPL")
        _patch_wl(monkeypatch, _StubWatchlistService(
            entries=[_StubEntry("AAPL")], changes=[change]
        ))
        _patch_enrich(monkeypatch)

        await producers.produce_watchlist_scan(db_session, MagicMock(), "r1", "h", 1)

        row = (await db_session.execute(select(DeliveryLedger))).scalars().first()
        assert row is not None
        assert row.status == "pending"


# ===========================================================================
# § DEDUP — duplicate scan suppresses second delivery
# ===========================================================================

class TestShadowDedup:
    @pytest.mark.asyncio
    async def test_same_event_twice_one_row(self, monkeypatch, db_session):
        from sqlalchemy import select, func
        from app.db.models import DeliveryLedger

        event_id = str(uuid.uuid4())
        change = _make_change("AAPL", event_id=event_id)
        entries = [_StubEntry("AAPL")]
        svc = _StubWatchlistService(entries=entries, changes=[change])
        _patch_wl(monkeypatch, svc)
        _patch_enrich(monkeypatch)

        await producers.produce_watchlist_scan(db_session, MagicMock(), "r1", "h", 1)
        await producers.produce_watchlist_scan(db_session, MagicMock(), "r2", "h", 2)

        count = (await db_session.execute(
            select(func.count()).select_from(DeliveryLedger)
        )).scalar()
        assert count == 1

    @pytest.mark.asyncio
    async def test_duplicate_run_deliveries_enqueued_is_zero(self, monkeypatch, db_session):
        event_id = str(uuid.uuid4())
        change = _make_change("AAPL", event_id=event_id)
        entries = [_StubEntry("AAPL")]
        svc = _StubWatchlistService(entries=entries, changes=[change])
        _patch_wl(monkeypatch, svc)
        _patch_enrich(monkeypatch)

        await producers.produce_watchlist_scan(db_session, MagicMock(), "r1", "h", 1)
        result2 = await producers.produce_watchlist_scan(db_session, MagicMock(), "r2", "h", 2)

        assert result2.payload_json["deliveries_enqueued"] == 0
        assert result2.payload_json["deliveries_duplicate"] == 1

    @pytest.mark.asyncio
    async def test_different_events_create_separate_rows(self, monkeypatch, db_session):
        from sqlalchemy import select, func
        from app.db.models import DeliveryLedger

        change1 = _make_change("AAPL", event_id=str(uuid.uuid4()))
        change2 = _make_change("AAPL", event_id=str(uuid.uuid4()))
        entries = [_StubEntry("AAPL")]
        svc = _StubWatchlistService(entries=entries, changes=[change1])
        _patch_wl(monkeypatch, svc)
        _patch_enrich(monkeypatch)

        await producers.produce_watchlist_scan(db_session, MagicMock(), "r1", "h", 1)

        # Now swap to change2
        svc2 = _StubWatchlistService(entries=entries, changes=[change2])
        monkeypatch.setattr(producers, "_get_watchlist_service", lambda: svc2)
        await producers.produce_watchlist_scan(db_session, MagicMock(), "r2", "h", 2)

        count = (await db_session.execute(
            select(func.count()).select_from(DeliveryLedger)
        )).scalar()
        assert count == 2


# ===========================================================================
# § SAFETY — no Notification rows; no external send
# ===========================================================================

class TestShadowSafety:
    @pytest.mark.asyncio
    async def test_no_notification_rows_created(self, monkeypatch, db_session):
        from sqlalchemy import select, func
        from app.db.models import Notification

        change = _make_change("AAPL")
        _patch_wl(monkeypatch, _StubWatchlistService(
            entries=[_StubEntry("AAPL")], changes=[change]
        ))
        _patch_enrich(monkeypatch)

        await producers.produce_watchlist_scan(db_session, MagicMock(), "r1", "h", 1)

        count = (await db_session.execute(
            select(func.count()).select_from(Notification)
        )).scalar()
        assert count == 0

    @pytest.mark.asyncio
    async def test_no_delivery_rows_when_no_changes(self, monkeypatch, db_session):
        from sqlalchemy import select, func
        from app.db.models import DeliveryLedger

        _patch_wl(monkeypatch, _StubWatchlistService(
            entries=[_StubEntry("AAPL"), _StubEntry("NVDA")], changes=[]
        ))
        _patch_enrich(monkeypatch)

        await producers.produce_watchlist_scan(db_session, MagicMock(), "r1", "h", 1)

        count = (await db_session.execute(
            select(func.count()).select_from(DeliveryLedger)
        )).scalar()
        assert count == 0

    @pytest.mark.asyncio
    async def test_outcome_succeeded_with_changes(self, monkeypatch, db_session):
        change = _make_change("AAPL")
        _patch_wl(monkeypatch, _StubWatchlistService(
            entries=[_StubEntry("AAPL")], changes=[change]
        ))
        _patch_enrich(monkeypatch)

        result = await producers.produce_watchlist_scan(db_session, MagicMock(), "r1", "h", 1)
        assert result.outcome == "succeeded"

    @pytest.mark.asyncio
    async def test_no_delivery_rows_when_session_none(self, monkeypatch):
        change = _make_change("AAPL")
        _patch_wl(monkeypatch, _StubWatchlistService(
            entries=[_StubEntry("AAPL")], changes=[change]
        ))
        _patch_enrich(monkeypatch)
        # session=None: enqueue returns STATUS_SKIPPED, no DB writes possible
        result = await producers.produce_watchlist_scan(None, MagicMock(), "r1", "h", 1)
        assert result.outcome == "succeeded"
        assert result.payload_json["deliveries_enqueued"] == 0


# ===========================================================================
# § ITEMS — items_emitted and payload_json counters
# ===========================================================================

class TestItemsEmitted:
    @pytest.mark.asyncio
    async def test_items_emitted_equals_ticker_count(self, monkeypatch, db_session):
        entries = [_StubEntry("AAPL"), _StubEntry("NVDA"), _StubEntry("MSFT")]
        changes = [_make_change(e.ticker) for e in entries]
        _patch_wl(monkeypatch, _StubWatchlistService(entries=entries, changes=changes))
        _patch_enrich(monkeypatch)

        result = await producers.produce_watchlist_scan(db_session, MagicMock(), "r1", "h", 1)
        assert result.items_emitted == 3

    @pytest.mark.asyncio
    async def test_deliveries_enqueued_in_payload_json(self, monkeypatch, db_session):
        change = _make_change("AAPL")
        _patch_wl(monkeypatch, _StubWatchlistService(
            entries=[_StubEntry("AAPL")], changes=[change]
        ))
        _patch_enrich(monkeypatch)

        result = await producers.produce_watchlist_scan(db_session, MagicMock(), "r1", "h", 1)
        assert "deliveries_enqueued" in result.payload_json
        assert result.payload_json["deliveries_enqueued"] == 1

    @pytest.mark.asyncio
    async def test_material_changes_found_in_payload_json(self, monkeypatch, db_session):
        changes = [_make_change("AAPL"), _make_change("NVDA")]
        entries = [_StubEntry(c.ticker) for c in changes]
        _patch_wl(monkeypatch, _StubWatchlistService(entries=entries, changes=changes))
        _patch_enrich(monkeypatch)

        result = await producers.produce_watchlist_scan(db_session, MagicMock(), "r1", "h", 1)
        assert result.payload_json["material_changes_found"] == 2

    @pytest.mark.asyncio
    async def test_content_key_candidates_populated(self, monkeypatch, db_session):
        changes = [_make_change("AAPL"), _make_change("NVDA")]
        entries = [_StubEntry(c.ticker) for c in changes]
        _patch_wl(monkeypatch, _StubWatchlistService(entries=entries, changes=changes))
        _patch_enrich(monkeypatch)

        result = await producers.produce_watchlist_scan(db_session, MagicMock(), "r1", "h", 1)
        assert len(result.content_key_candidates) == 2
        for ck in result.content_key_candidates:
            assert isinstance(ck, str) and len(ck) > 0

    @pytest.mark.asyncio
    async def test_payload_json_shadow_flag_true(self, monkeypatch, db_session):
        _patch_wl(monkeypatch, _StubWatchlistService(
            entries=[_StubEntry("AAPL")], changes=[]
        ))
        _patch_enrich(monkeypatch)

        result = await producers.produce_watchlist_scan(db_session, MagicMock(), "r1", "h", 1)
        assert result.payload_json["shadow"] is True


# ===========================================================================
# § ERRORS — enqueue failure / converter failure
# ===========================================================================

class TestDeliveryErrors:
    @pytest.mark.asyncio
    async def test_converter_exception_logs_error_does_not_crash(self, monkeypatch, db_session):
        """If from_material_change raises, producer continues and returns succeeded."""
        change = _make_change("AAPL")
        _patch_wl(monkeypatch, _StubWatchlistService(
            entries=[_StubEntry("AAPL")], changes=[change]
        ))
        _patch_enrich(monkeypatch)

        def bad_converter(event):
            raise RuntimeError("converter blew up")
        monkeypatch.setattr(producers, "_get_payload_converter", lambda: bad_converter)

        result = await producers.produce_watchlist_scan(db_session, MagicMock(), "r1", "h", 1)
        assert result.outcome == "succeeded"
        assert result.payload_json["delivery_errors"] == 1

    @pytest.mark.asyncio
    async def test_error_count_in_payload_json(self, monkeypatch, db_session):
        changes = [_make_change("AAPL"), _make_change("NVDA")]
        entries = [_StubEntry(c.ticker) for c in changes]
        _patch_wl(monkeypatch, _StubWatchlistService(entries=entries, changes=changes))
        _patch_enrich(monkeypatch)

        call_count = [0]
        def flaky_converter(event):
            call_count[0] += 1
            if call_count[0] == 1:
                raise RuntimeError("first call fails")
            from app.services.watchlist_alert_payload import from_material_change
            return from_material_change(event)
        monkeypatch.setattr(producers, "_get_payload_converter", lambda: flaky_converter)

        result = await producers.produce_watchlist_scan(db_session, MagicMock(), "r1", "h", 1)
        assert result.outcome == "succeeded"
        assert result.payload_json["delivery_errors"] == 1
        assert result.payload_json["deliveries_enqueued"] == 1

    @pytest.mark.asyncio
    async def test_producer_still_succeeds_on_partial_failure(self, monkeypatch, db_session):
        """All deliveries failing does not flip outcome to 'failed' (scan itself succeeded)."""
        change = _make_change("AAPL")
        _patch_wl(monkeypatch, _StubWatchlistService(
            entries=[_StubEntry("AAPL")], changes=[change]
        ))
        _patch_enrich(monkeypatch)

        def always_error(event):
            raise ValueError("always bad")
        monkeypatch.setattr(producers, "_get_payload_converter", lambda: always_error)

        result = await producers.produce_watchlist_scan(db_session, MagicMock(), "r1", "h", 1)
        assert result.outcome == "succeeded"


# ===========================================================================
# § GUARDRAILS — shadow delivery respects guardrails at flush time
# ===========================================================================

class TestShadowGuardrails:
    @pytest.mark.asyncio
    async def test_enqueued_row_is_pending_before_flush(self, monkeypatch, db_session):
        from sqlalchemy import select
        from app.db.models import DeliveryLedger

        change = _make_change("AAPL")
        _patch_wl(monkeypatch, _StubWatchlistService(
            entries=[_StubEntry("AAPL")], changes=[change]
        ))
        _patch_enrich(monkeypatch)

        await producers.produce_watchlist_scan(db_session, MagicMock(), "r1", "h", 1)

        row = (await db_session.execute(select(DeliveryLedger))).scalars().first()
        assert row.status == "pending"

    @pytest.mark.asyncio
    async def test_flush_delivers_pending_row_in_shadow(self, monkeypatch, db_session):
        from sqlalchemy import select
        from app.db.models import DeliveryLedger

        change = _make_change("AAPL")
        _patch_wl(monkeypatch, _StubWatchlistService(
            entries=[_StubEntry("AAPL")], changes=[change]
        ))
        _patch_enrich(monkeypatch)

        # Enqueue
        await producers.produce_watchlist_scan(db_session, MagicMock(), "r1", "h", 1)

        # Flush at a non-quiet hour (noon UTC)
        noon = _now().replace(hour=12, minute=0, second=0, microsecond=0)
        monkeypatch.setattr(ds, "_is_quiet_hour", lambda dt: False)
        results = await ds.flush_pending_shadow(db_session, now=noon)

        assert len(results) == 1
        assert results[0].status == ds.STATUS_DELIVERED_SHADOW

    @pytest.mark.asyncio
    async def test_flush_suppresses_row_during_quiet_hours(self, monkeypatch, db_session):
        from sqlalchemy import select
        from app.db.models import DeliveryLedger

        change = _make_change("AAPL")
        _patch_wl(monkeypatch, _StubWatchlistService(
            entries=[_StubEntry("AAPL")], changes=[change]
        ))
        _patch_enrich(monkeypatch)

        await producers.produce_watchlist_scan(db_session, MagicMock(), "r1", "h", 1)

        # Force quiet hours during flush
        monkeypatch.setattr(ds, "_is_quiet_hour", lambda dt: True)
        midnight = _now().replace(hour=0, minute=0, second=0, microsecond=0)
        results = await ds.flush_pending_shadow(db_session, now=midnight)

        assert len(results) == 1
        assert results[0].status == ds.STATUS_SUPPRESSED_GUARDRAIL
        assert results[0].reason == ds.REASON_QUIET_HOURS


# ===========================================================================
# § TICK — scheduler tick creates delivery_ledger rows
# ===========================================================================

class TestTickIntegration:
    @pytest.mark.asyncio
    async def test_tick_with_watchlist_scan_creates_delivery_rows(
        self, monkeypatch, db_session, loop_on
    ):
        from sqlalchemy import select, func
        from app.db.models import DeliveryLedger

        change = _make_change("AAPL")
        entries = [_StubEntry("AAPL")]
        _patch_wl(monkeypatch, _StubWatchlistService(entries=entries, changes=[change]))
        _patch_enrich(monkeypatch)

        producers.register_all_shadow_producers()

        # Seed a due job
        job = await _make_due_job(db_session, job_type="watchlist_scan", target="AAPL")
        assert job is not None

        holder = _holder()
        result = await tick(db_session, holder)

        assert result.jobs_claimed >= 1

        count = (await db_session.execute(
            select(func.count()).select_from(DeliveryLedger)
        )).scalar()
        assert count >= 1

    @pytest.mark.asyncio
    async def test_tick_second_run_deduplicates_delivery(
        self, monkeypatch, db_session, loop_on
    ):
        from sqlalchemy import select, func
        from app.db.models import DeliveryLedger

        event_id = str(uuid.uuid4())
        change = _make_change("AAPL", event_id=event_id)
        entries = [_StubEntry("AAPL")]
        _patch_wl(monkeypatch, _StubWatchlistService(entries=entries, changes=[change]))
        _patch_enrich(monkeypatch)

        producers.register_all_shadow_producers()

        # Two jobs with different period_buckets — simulate two ticks
        job1 = await _make_due_job(db_session, job_type="watchlist_scan",
                                   target="AAPL", bucket=f"2026-06-13-{_uid()[:6]}")
        job2 = await _make_due_job(db_session, job_type="watchlist_scan",
                                   target="AAPL", bucket=f"2026-06-13-{_uid()[:6]}")

        holder = _holder()
        await tick(db_session, holder)
        await tick(db_session, holder)

        count = (await db_session.execute(
            select(func.count()).select_from(DeliveryLedger)
        )).scalar()
        # Same event_id → same payload hash → same content_key → only 1 row
        assert count == 1

    @pytest.mark.asyncio
    async def test_tick_no_notifications_created(
        self, monkeypatch, db_session, loop_on
    ):
        from sqlalchemy import select, func
        from app.db.models import Notification

        change = _make_change("AAPL")
        entries = [_StubEntry("AAPL")]
        _patch_wl(monkeypatch, _StubWatchlistService(entries=entries, changes=[change]))
        _patch_enrich(monkeypatch)

        producers.register_all_shadow_producers()
        await _make_due_job(db_session, job_type="watchlist_scan", target="AAPL")
        await tick(db_session, _holder())

        count = (await db_session.execute(
            select(func.count()).select_from(Notification)
        )).scalar()
        assert count == 0
