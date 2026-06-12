"""
Phase 10A · Slice 8 — Delivery service (shadow mode) tests.

Covers:
  § RESULT      — DeliveryResult shape and status/reason constants
  § ENQUEUE     — happy path, duplicate suppression, severity floor, null session
  § GUARDRAILS  — quiet hours, daily cap, mute_until (not_before_utc)
  § FLUSH       — shadow drain marks delivered_shadow, suppressed rows stay suppressed
  § IDEMPOTENCY — duplicate content_key across sessions never creates second row
  § SAFETY      — no notifications created, no external sends
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional
from unittest.mock import AsyncMock, patch

import pytest

from app.services import loop_delivery_service as ds
from app.services.loop_delivery_service import (
    DeliveryResult,
    STATUS_DELIVERED_SHADOW,
    STATUS_SUPPRESSED_DUPLICATE,
    STATUS_SUPPRESSED_GUARDRAIL,
    STATUS_FAILED,
    STATUS_SKIPPED,
    REASON_DUPLICATE,
    REASON_QUIET_HOURS,
    REASON_DAILY_CAP,
    REASON_MUTE_UNTIL,
    REASON_SEVERITY_FLOOR,
    REASON_NO_SESSION,
    REASON_SHADOW_DRAIN,
    enqueue,
    flush_pending_shadow,
)
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


def _future(s: int = 5) -> datetime:
    return _now() + timedelta(seconds=s)


def _naive(dt: datetime) -> datetime:
    return dt.replace(tzinfo=None)


def _payload(tag: Optional[str] = None) -> dict:
    return {"message": f"test-{tag or _uid()}", "shadow": True}


def _at_hour(h: int) -> datetime:
    """Return a datetime today at the given UTC hour."""
    return datetime.now(timezone.utc).replace(
        hour=h, minute=0, second=0, microsecond=0
    )


async def _enqueue_one(db_session, *, tag=None, channel="in_app",
                       target_key=None, user_id=None, **kwargs) -> DeliveryResult:
    return await enqueue(
        db_session,
        user_id=user_id or f"user:{_uid()}",
        channel=channel,
        target_key=target_key or f"AAPL:{_uid()}",
        payload=_payload(tag),
        **kwargs,
    )


# ===========================================================================
# § RESULT shape
# ===========================================================================

class TestDeliveryResultShape:
    def test_all_status_constants_are_strings(self):
        for s in [STATUS_DELIVERED_SHADOW, STATUS_SUPPRESSED_DUPLICATE,
                  STATUS_SUPPRESSED_GUARDRAIL, STATUS_FAILED, STATUS_SKIPPED]:
            assert isinstance(s, str) and s

    def test_all_reason_constants_are_strings(self):
        for r in [REASON_DUPLICATE, REASON_QUIET_HOURS, REASON_DAILY_CAP,
                  REASON_MUTE_UNTIL, REASON_SEVERITY_FLOOR, REASON_NO_SESSION,
                  REASON_SHADOW_DRAIN]:
            assert isinstance(r, str) and r

    def test_delivery_result_defaults(self):
        r = DeliveryResult(status="pending", content_key="abc", channel="in_app",
                           target_key="AAPL")
        assert r.reason == ""
        assert r.payload_json is None
        assert r.delivery_id is None

    def test_delivery_result_full(self):
        r = DeliveryResult(
            status=STATUS_DELIVERED_SHADOW,
            content_key="x" * 64,
            channel="in_app",
            target_key="NVDA",
            reason=REASON_SHADOW_DRAIN,
            payload_json={"a": 1},
            delivery_id="id-123",
        )
        assert r.content_key == "x" * 64
        assert r.delivery_id == "id-123"


# ===========================================================================
# § ENQUEUE
# ===========================================================================

class TestEnqueue:
    @pytest.mark.asyncio
    async def test_enqueue_creates_pending_row(self, db_session):
        result = await _enqueue_one(db_session)
        assert result.status == "pending"
        assert result.delivery_id is not None
        assert len(result.content_key) == 64

        # Verify row exists in DB
        row = await loop_repo.delivery_get_by_id(db_session, result.delivery_id)
        assert row is not None
        assert row.status == "pending"

    @pytest.mark.asyncio
    async def test_enqueue_returns_content_key(self, db_session):
        result = await _enqueue_one(db_session)
        assert result.content_key
        assert result.channel == "in_app"

    @pytest.mark.asyncio
    async def test_enqueue_duplicate_suppressed(self, db_session):
        user_id    = f"user:{_uid()}"
        target_key = f"MSFT:{_uid()}"
        payload    = _payload("dup")

        r1 = await enqueue(db_session, user_id=user_id, channel="in_app",
                           target_key=target_key, payload=payload)
        r2 = await enqueue(db_session, user_id=user_id, channel="in_app",
                           target_key=target_key, payload=payload)

        assert r1.status == "pending"
        assert r2.status == STATUS_SUPPRESSED_DUPLICATE
        assert r2.reason == REASON_DUPLICATE
        assert r2.content_key == r1.content_key

    @pytest.mark.asyncio
    async def test_enqueue_different_payloads_both_enqueued(self, db_session):
        user_id = f"user:{_uid()}"
        target  = f"TSLA:{_uid()}"

        r1 = await enqueue(db_session, user_id=user_id, channel="in_app",
                           target_key=target, payload={"v": 1})
        r2 = await enqueue(db_session, user_id=user_id, channel="in_app",
                           target_key=target, payload={"v": 2})

        assert r1.status == "pending"
        assert r2.status == "pending"
        assert r1.content_key != r2.content_key

    @pytest.mark.asyncio
    async def test_enqueue_no_session_returns_skipped(self):
        result = await enqueue(None, user_id="u1", channel="in_app",
                               target_key="AAPL", payload={"x": 1})
        assert result.status == STATUS_SKIPPED
        assert result.reason == REASON_NO_SESSION

    @pytest.mark.asyncio
    async def test_enqueue_severity_floor_suppresses(self, db_session, monkeypatch):
        """Severity 'info' below floor 'alert' should be suppressed at enqueue time."""
        monkeypatch.setattr(ds, "_cfg_severity_floor", lambda: "alert")
        result = await enqueue(
            db_session, user_id=f"user:{_uid()}", channel="in_app",
            target_key=f"GS:{_uid()}", payload={"v": 1}, severity="info",
        )
        assert result.status == STATUS_SUPPRESSED_GUARDRAIL
        assert result.reason == REASON_SEVERITY_FLOOR
        # No DB row created
        assert result.delivery_id is None

    @pytest.mark.asyncio
    async def test_enqueue_severity_meets_floor_passes(self, db_session, monkeypatch):
        monkeypatch.setattr(ds, "_cfg_severity_floor", lambda: "alert")
        result = await enqueue(
            db_session, user_id=f"user:{_uid()}", channel="in_app",
            target_key=f"GS:{_uid()}", payload={"v": 1}, severity="critical",
        )
        assert result.status == "pending"

    @pytest.mark.asyncio
    async def test_enqueue_no_severity_field_passes_any_floor(self, db_session, monkeypatch):
        """Payload without a severity field always passes the severity guardrail."""
        monkeypatch.setattr(ds, "_cfg_severity_floor", lambda: "critical")
        result = await enqueue(
            db_session, user_id=f"user:{_uid()}", channel="in_app",
            target_key=f"JPM:{_uid()}", payload={"no": "severity"},
        )
        assert result.status == "pending"

    @pytest.mark.asyncio
    async def test_enqueue_not_before_utc_stored(self, db_session):
        nbu = _future(3600)
        result = await enqueue(
            db_session, user_id=f"user:{_uid()}", channel="in_app",
            target_key=f"NVDA:{_uid()}", payload={"x": 1},
            not_before_utc=nbu,
        )
        assert result.status == "pending"
        row = await loop_repo.delivery_get_by_id(db_session, result.delivery_id)
        assert row.not_before_utc is not None

    @pytest.mark.asyncio
    async def test_enqueue_artifact_ref_stored(self, db_session):
        ref = f"session:{_uid()}"
        result = await enqueue(
            db_session, user_id=f"user:{_uid()}", channel="in_app",
            target_key=f"WMT:{_uid()}", payload={"x": 1},
            artifact_ref=ref,
        )
        row = await loop_repo.delivery_get_by_id(db_session, result.delivery_id)
        assert row.artifact_ref == ref


# ===========================================================================
# § GUARDRAILS (via flush)
# ===========================================================================

class TestGuardrailsQuietHours:
    @pytest.mark.asyncio
    async def test_quiet_hour_suppresses_row(self, db_session, monkeypatch):
        monkeypatch.setattr(ds, "_cfg_quiet_hours_start", lambda: 22)
        monkeypatch.setattr(ds, "_cfg_quiet_hours_end",   lambda: 7)

        result = await _enqueue_one(db_session)
        assert result.status == "pending"

        # Flush at 23:00 UTC (inside quiet window)
        results = await flush_pending_shadow(
            db_session, now=_at_hour(23), limit=50
        )
        assert len(results) == 1
        assert results[0].status == STATUS_SUPPRESSED_GUARDRAIL
        assert results[0].reason == REASON_QUIET_HOURS

        # Verify DB row is suppressed
        row = await loop_repo.delivery_get_by_id(db_session, result.delivery_id)
        assert row.status == "suppressed"

    @pytest.mark.asyncio
    async def test_outside_quiet_hours_delivers(self, db_session, monkeypatch):
        monkeypatch.setattr(ds, "_cfg_quiet_hours_start", lambda: 22)
        monkeypatch.setattr(ds, "_cfg_quiet_hours_end",   lambda: 7)

        result = await _enqueue_one(db_session)

        # Flush at 12:00 UTC (outside quiet window)
        results = await flush_pending_shadow(
            db_session, now=_at_hour(12), limit=50
        )
        assert len(results) == 1
        assert results[0].status == STATUS_DELIVERED_SHADOW

    @pytest.mark.asyncio
    async def test_quiet_hours_same_day_window(self, db_session, monkeypatch):
        """Same-day window e.g. 02:00–06:00 should suppress hour=3."""
        monkeypatch.setattr(ds, "_cfg_quiet_hours_start", lambda: 2)
        monkeypatch.setattr(ds, "_cfg_quiet_hours_end",   lambda: 6)

        result = await _enqueue_one(db_session)
        results = await flush_pending_shadow(
            db_session, now=_at_hour(3), limit=50
        )
        assert results[0].reason == REASON_QUIET_HOURS


class TestGuardrailsDailyCap:
    @pytest.mark.asyncio
    async def test_daily_cap_suppresses_when_reached(self, db_session, monkeypatch):
        """Cap=2: first two deliveries pass, third is suppressed."""
        monkeypatch.setattr(ds, "_cfg_quiet_hours_start", lambda: 22)
        monkeypatch.setattr(ds, "_cfg_quiet_hours_end",   lambda: 7)
        monkeypatch.setattr(ds, "_cfg_daily_cap", lambda: 2)

        user_id    = f"user:{_uid()}"
        target_key = f"AAPL:{_uid()}"
        flush_now  = _at_hour(12)

        # Enqueue three distinct payloads
        for i in range(3):
            await enqueue(
                db_session, user_id=user_id, channel="in_app",
                target_key=target_key, payload={"i": i},
            )

        results = await flush_pending_shadow(db_session, now=flush_now, limit=50)
        statuses = [r.status for r in results]

        delivered = statuses.count(STATUS_DELIVERED_SHADOW)
        suppressed = statuses.count(STATUS_SUPPRESSED_GUARDRAIL)
        assert delivered == 2
        assert suppressed == 1
        assert any(r.reason == REASON_DAILY_CAP for r in results
                   if r.status == STATUS_SUPPRESSED_GUARDRAIL)

    @pytest.mark.asyncio
    async def test_daily_cap_zero_means_no_cap(self, db_session, monkeypatch):
        monkeypatch.setattr(ds, "_cfg_quiet_hours_start", lambda: 22)
        monkeypatch.setattr(ds, "_cfg_quiet_hours_end",   lambda: 7)
        monkeypatch.setattr(ds, "_cfg_daily_cap", lambda: 0)

        user_id    = f"user:{_uid()}"
        target_key = f"BAC:{_uid()}"
        for i in range(5):
            await enqueue(db_session, user_id=user_id, channel="in_app",
                          target_key=target_key, payload={"i": i})

        results = await flush_pending_shadow(db_session, now=_at_hour(12), limit=50)
        assert all(r.status == STATUS_DELIVERED_SHADOW for r in results)


class TestGuardrailsMuteUntil:
    @pytest.mark.asyncio
    async def test_mute_until_future_defers_row(self, db_session, monkeypatch):
        """A future not_before_utc keeps the row pending — delivery_get_pending
        pre-filters it, so it never enters the flush pipeline at all."""
        monkeypatch.setattr(ds, "_cfg_quiet_hours_start", lambda: 22)
        monkeypatch.setattr(ds, "_cfg_quiet_hours_end",   lambda: 7)

        nbu = _future(3600)  # 1 hour in the future
        result = await enqueue(
            db_session, user_id=f"user:{_uid()}", channel="in_app",
            target_key=f"HON:{_uid()}", payload={"x": 1},
            not_before_utc=nbu,
        )
        assert result.status == "pending"

        # Flush at 12:00 — row has not_before_utc 1 hour ahead so repo skips it
        results = await flush_pending_shadow(db_session, now=_at_hour(12), limit=50)
        assert len(results) == 0  # Row deferred, not processed

        # Row must still be pending in DB (not suppressed)
        row = await loop_repo.delivery_get_by_id(db_session, result.delivery_id)
        assert row.status == "pending"

    @pytest.mark.asyncio
    async def test_mute_until_past_allows(self, db_session, monkeypatch):
        # Disable quiet hours entirely for this test — we only want to verify
        # that a past not_before_utc is not suppressed by the mute_until guard.
        monkeypatch.setattr(ds, "_is_quiet_hour", lambda dt: False)

        # nbu = 2 hours ago; flush_now = now → nbu is strictly before flush_now
        nbu = _past(7200)
        flush_now = _now()

        result = await enqueue(
            db_session, user_id=f"user:{_uid()}", channel="in_app",
            target_key=f"COST:{_uid()}", payload={"x": 1},
            not_before_utc=nbu,
        )

        results = await flush_pending_shadow(db_session, now=flush_now, limit=50)
        # delivery_get_pending lets past-nbu rows through → shadow delivered
        assert results[0].status == STATUS_DELIVERED_SHADOW

    @pytest.mark.asyncio
    async def test_mute_until_none_no_suppression(self, db_session, monkeypatch):
        monkeypatch.setattr(ds, "_cfg_quiet_hours_start", lambda: 22)
        monkeypatch.setattr(ds, "_cfg_quiet_hours_end",   lambda: 7)

        result = await enqueue(
            db_session, user_id=f"user:{_uid()}", channel="in_app",
            target_key=f"LLY:{_uid()}", payload={"x": 1},
        )

        results = await flush_pending_shadow(db_session, now=_at_hour(12), limit=50)
        assert results[0].status == STATUS_DELIVERED_SHADOW


# ===========================================================================
# § FLUSH — shadow drain
# ===========================================================================

class TestFlushPendingShadow:
    @pytest.mark.asyncio
    async def test_flush_marks_delivered_shadow(self, db_session, monkeypatch):
        monkeypatch.setattr(ds, "_cfg_quiet_hours_start", lambda: 22)
        monkeypatch.setattr(ds, "_cfg_quiet_hours_end",   lambda: 7)

        result = await _enqueue_one(db_session)
        assert result.status == "pending"

        flush_results = await flush_pending_shadow(
            db_session, now=_at_hour(12), limit=50
        )
        assert len(flush_results) == 1
        assert flush_results[0].status == STATUS_DELIVERED_SHADOW
        assert flush_results[0].reason == REASON_SHADOW_DRAIN

        # DB row updated
        row = await loop_repo.delivery_get_by_id(db_session, result.delivery_id)
        assert row.status == STATUS_DELIVERED_SHADOW
        assert row.delivered_at is not None

    @pytest.mark.asyncio
    async def test_flush_empty_returns_empty(self, db_session, monkeypatch):
        monkeypatch.setattr(ds, "_cfg_quiet_hours_start", lambda: 22)
        monkeypatch.setattr(ds, "_cfg_quiet_hours_end",   lambda: 7)

        results = await flush_pending_shadow(db_session, now=_at_hour(12), limit=50)
        assert results == []

    @pytest.mark.asyncio
    async def test_flush_no_session_returns_empty(self):
        results = await flush_pending_shadow(None)
        assert results == []

    @pytest.mark.asyncio
    async def test_flush_does_not_reprocess_delivered_rows(self, db_session, monkeypatch):
        monkeypatch.setattr(ds, "_cfg_quiet_hours_start", lambda: 22)
        monkeypatch.setattr(ds, "_cfg_quiet_hours_end",   lambda: 7)

        await _enqueue_one(db_session)

        r1 = await flush_pending_shadow(db_session, now=_at_hour(12), limit=50)
        assert len(r1) == 1
        assert r1[0].status == STATUS_DELIVERED_SHADOW

        # Second flush — same row is no longer pending
        r2 = await flush_pending_shadow(db_session, now=_at_hour(12), limit=50)
        assert len(r2) == 0

    @pytest.mark.asyncio
    async def test_flush_limit_respected(self, db_session, monkeypatch):
        monkeypatch.setattr(ds, "_cfg_quiet_hours_start", lambda: 22)
        monkeypatch.setattr(ds, "_cfg_quiet_hours_end",   lambda: 7)

        # Enqueue 5 items
        for _ in range(5):
            await _enqueue_one(db_session)

        results = await flush_pending_shadow(db_session, now=_at_hour(12), limit=3)
        assert len(results) == 3

    @pytest.mark.asyncio
    async def test_flush_result_has_delivery_id(self, db_session, monkeypatch):
        monkeypatch.setattr(ds, "_cfg_quiet_hours_start", lambda: 22)
        monkeypatch.setattr(ds, "_cfg_quiet_hours_end",   lambda: 7)

        r = await _enqueue_one(db_session)
        results = await flush_pending_shadow(db_session, now=_at_hour(12), limit=50)
        assert results[0].delivery_id == r.delivery_id

    @pytest.mark.asyncio
    async def test_flush_mixed_pass_and_suppress(self, db_session, monkeypatch):
        """Cap=1 on a shared target: first row passes, second is capped."""
        monkeypatch.setattr(ds, "_cfg_quiet_hours_start", lambda: 22)
        monkeypatch.setattr(ds, "_cfg_quiet_hours_end",   lambda: 7)
        monkeypatch.setattr(ds, "_cfg_daily_cap", lambda: 1)

        user_id    = f"user:{_uid()}"
        target_key = f"V:{_uid()}"

        r1 = await enqueue(db_session, user_id=user_id, channel="in_app",
                           target_key=target_key, payload={"seq": 1})
        r2 = await enqueue(db_session, user_id=user_id, channel="in_app",
                           target_key=target_key, payload={"seq": 2})

        results = await flush_pending_shadow(db_session, now=_at_hour(12), limit=50)

        by_id = {r.delivery_id: r for r in results}
        assert by_id[r1.delivery_id].status == STATUS_DELIVERED_SHADOW
        assert by_id[r2.delivery_id].status == STATUS_SUPPRESSED_GUARDRAIL
        assert by_id[r2.delivery_id].reason == REASON_DAILY_CAP


# ===========================================================================
# § IDEMPOTENCY — cross-session
# ===========================================================================

class TestIdempotency:
    @pytest.mark.asyncio
    async def test_same_content_key_two_calls_no_second_row(self, db_session):
        user_id    = f"user:{_uid()}"
        target_key = f"META:{_uid()}"
        payload    = {"val": "same-content"}

        r1 = await enqueue(db_session, user_id=user_id, channel="in_app",
                           target_key=target_key, payload=payload)
        r2 = await enqueue(db_session, user_id=user_id, channel="in_app",
                           target_key=target_key, payload=payload)

        assert r1.status == "pending"
        assert r2.status == STATUS_SUPPRESSED_DUPLICATE
        # Only one row in DB
        row = await loop_repo.delivery_get_by_content_key(db_session, r1.content_key)
        assert row is not None
        assert row.id == r1.delivery_id

    @pytest.mark.asyncio
    async def test_delivered_content_key_blocks_re_enqueue(self, db_session, monkeypatch):
        """After a row has been shadow-delivered, re-enqueuing the same content is blocked."""
        monkeypatch.setattr(ds, "_cfg_quiet_hours_start", lambda: 22)
        monkeypatch.setattr(ds, "_cfg_quiet_hours_end",   lambda: 7)

        user_id    = f"user:{_uid()}"
        target_key = f"AVGO:{_uid()}"
        payload    = {"val": "delivered-content"}

        r1 = await enqueue(db_session, user_id=user_id, channel="in_app",
                           target_key=target_key, payload=payload)
        await flush_pending_shadow(db_session, now=_at_hour(12), limit=50)

        # Re-enqueue the same payload — UNIQUE constraint should block it
        r2 = await enqueue(db_session, user_id=user_id, channel="in_app",
                           target_key=target_key, payload=payload)
        assert r2.status == STATUS_SUPPRESSED_DUPLICATE

    @pytest.mark.asyncio
    async def test_different_channels_different_keys(self, db_session):
        user_id    = f"user:{_uid()}"
        target_key = f"UNH:{_uid()}"
        payload    = {"val": "multi-channel"}

        r_in_app = await enqueue(db_session, user_id=user_id, channel="in_app",
                                 target_key=target_key, payload=payload)
        r_email  = await enqueue(db_session, user_id=user_id, channel="email",
                                 target_key=target_key, payload=payload)

        assert r_in_app.status == "pending"
        assert r_email.status == "pending"
        assert r_in_app.content_key != r_email.content_key


# ===========================================================================
# § SAFETY — no notifications, no external sends
# ===========================================================================

class TestSafetyNoSideEffects:
    @pytest.mark.asyncio
    async def test_no_notification_rows_created_on_enqueue(self, db_session):
        from sqlalchemy import select, func
        from app.db.models import Notification

        await _enqueue_one(db_session)

        count_result = await db_session.execute(
            select(func.count()).select_from(Notification)
        )
        assert (count_result.scalar() or 0) == 0

    @pytest.mark.asyncio
    async def test_no_notification_rows_created_on_flush(self, db_session, monkeypatch):
        monkeypatch.setattr(ds, "_cfg_quiet_hours_start", lambda: 22)
        monkeypatch.setattr(ds, "_cfg_quiet_hours_end",   lambda: 7)

        from sqlalchemy import select, func
        from app.db.models import Notification

        await _enqueue_one(db_session)
        await flush_pending_shadow(db_session, now=_at_hour(12), limit=50)

        count_result = await db_session.execute(
            select(func.count()).select_from(Notification)
        )
        assert (count_result.scalar() or 0) == 0

    @pytest.mark.asyncio
    async def test_notification_create_never_called(self, db_session, monkeypatch):
        """notification_create must never be called during the entire Slice 8 flow."""
        monkeypatch.setattr(ds, "_cfg_quiet_hours_start", lambda: 22)
        monkeypatch.setattr(ds, "_cfg_quiet_hours_end",   lambda: 7)

        call_count = [0]

        original_create = loop_repo.notification_create

        async def spy_notification_create(*args, **kwargs):
            call_count[0] += 1
            return await original_create(*args, **kwargs)

        with patch.object(loop_repo, "notification_create",
                          side_effect=spy_notification_create):
            await _enqueue_one(db_session)
            await flush_pending_shadow(db_session, now=_at_hour(12), limit=50)

        assert call_count[0] == 0

    @pytest.mark.asyncio
    async def test_suppressed_rows_also_create_no_notifications(self, db_session, monkeypatch):
        monkeypatch.setattr(ds, "_cfg_quiet_hours_start", lambda: 22)
        monkeypatch.setattr(ds, "_cfg_quiet_hours_end",   lambda: 7)

        from sqlalchemy import select, func
        from app.db.models import Notification

        await _enqueue_one(db_session)
        # Flush at quiet hour so rows get suppressed
        await flush_pending_shadow(db_session, now=_at_hour(23), limit=50)

        count_result = await db_session.execute(
            select(func.count()).select_from(Notification)
        )
        assert (count_result.scalar() or 0) == 0

    @pytest.mark.asyncio
    async def test_failed_delivery_recorded_correctly(self, db_session):
        """delivery_mark_failed increments attempts and sets status=failed."""
        result = await _enqueue_one(db_session)
        ok = await loop_repo.delivery_mark_failed(db_session, result.delivery_id,
                                                  increment_attempts=True)
        assert ok is True
        row = await loop_repo.delivery_get_by_id(db_session, result.delivery_id)
        assert row.status == "failed"
        assert row.attempts == 1
