"""
Phase 10C · Slice 6 — Delivery Relevance / Freshness Recheck tests.

Covers (no external sends, no notifications, no real delivery):

  § SERVICE     — relevance_recheck direct unit tests
  § STALE       — items older than STALE_THRESHOLD_HOURS are suppressed
  § DUP         — same content_hash already delivered → suppress
  § MIN_SEV     — canonical_severity below current prefs floor → suppress
  § SUPERSEDED  — artifact_ref signals supersession → suppress
  § FAIL_OPEN   — exceptions in checks do not suppress valid items
  § INTEGRATION — flush_pending_shadow now rechecks relevance
  § SAFETY      — no notifications, no external sends
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional
from unittest.mock import AsyncMock, patch

import pytest

from app.services.delivery_relevance_service import (
    RecheckResult,
    STALE_THRESHOLD_HOURS,
    REASON_RECHECK_STALE,
    REASON_RECHECK_DUP_DELIVERED,
    REASON_RECHECK_BELOW_MIN_SEV,
    REASON_RECHECK_SUPERSEDED,
    relevance_recheck,
    _age_hours,
    _freshness_score,
)
from app.services import loop_delivery_service as ds
from app.services.loop_delivery_service import (
    STATUS_DELIVERED_SHADOW,
    STATUS_SUPPRESSED_GUARDRAIL,
    REASON_RECHECK,
    enqueue,
    flush_pending_shadow,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _uid() -> str:
    return uuid.uuid4().hex[:10]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _at_hour(h: int) -> datetime:
    return _now().replace(hour=h, minute=0, second=0, microsecond=0)


def _payload(severity: str = "critical") -> dict:
    return {
        "message": f"test-{_uid()}",
        "severity": severity,
        "priority_score": 0.9,
        "materiality": 0.9,
        "created_at": _now().isoformat(),
    }


async def _enqueue_one(db_session, *, severity="critical", tag=None,
                       user_id=None, target_key=None) -> ds.DeliveryResult:
    tag = tag or _uid()
    return await enqueue(
        db_session,
        user_id=user_id or f"user-{tag}",
        channel="in_app",
        target_key=target_key or f"TICK-{tag}",
        payload=_payload(severity=severity),
        severity=severity,
    )


class _FakeRow:
    """Minimal duck-typed ledger row for unit testing the recheck service."""
    def __init__(self, *, id="row-1", content_hash="h1", created_at=None,
                 channel="in_app", canonical_severity="critical",
                 artifact_ref=None):
        self.id = id
        self.content_hash = content_hash
        self.created_at = created_at if created_at is not None else _now()
        self.channel = channel
        self.canonical_severity = canonical_severity
        self.artifact_ref = artifact_ref


# ===========================================================================
# § SERVICE — unit tests of helper functions + direct API
# ===========================================================================

class TestHelpers:
    def test_age_hours_fresh(self):
        now = _now()
        ts  = now - timedelta(hours=5)
        assert abs(_age_hours(ts, now) - 5.0) < 0.01

    def test_age_hours_none_returns_minus_one(self):
        assert _age_hours(None, _now()) == -1.0

    def test_age_hours_iso_string(self):
        now = _now()
        ts  = now - timedelta(hours=24)
        assert abs(_age_hours(ts.isoformat(), now) - 24.0) < 0.01

    def test_freshness_score_fresh(self):
        assert _freshness_score(0) == 1.0

    def test_freshness_score_one_halflife(self):
        from app.services.delivery_relevance_service import RECENCY_HALF_LIFE_HOURS
        score = _freshness_score(RECENCY_HALF_LIFE_HOURS)
        assert abs(score - 0.5) < 0.001

    def test_freshness_score_unknown_age(self):
        score = _freshness_score(-1)
        assert score == 0.5   # neutral for unknown age

    def test_freshness_score_bounded(self):
        for h in [0, 24, 48, 168, 720]:
            assert 0.0 <= _freshness_score(h) <= 1.0


class TestRecheckDirectUnit:
    @pytest.mark.asyncio
    async def test_null_session_fail_open(self):
        row = _FakeRow()
        result = await relevance_recheck(None, row)
        assert result.should_deliver is True

    @pytest.mark.asyncio
    async def test_null_row_fail_open(self):
        result = await relevance_recheck(object(), None)
        assert result.should_deliver is True

    @pytest.mark.asyncio
    async def test_fresh_item_all_clear(self, db_session):
        row = _FakeRow(created_at=_now())
        result = await relevance_recheck(db_session, row, now=_now())
        assert result.should_deliver is True
        assert result.suppress_reason == ""
        assert result.freshness_score > 0.9

    @pytest.mark.asyncio
    async def test_result_fields_present(self, db_session):
        row = _FakeRow()
        result = await relevance_recheck(db_session, row)
        assert isinstance(result.should_deliver, bool)
        assert 0.0 <= result.freshness_score <= 1.0
        assert 0.0 <= result.relevance_score <= 1.0
        assert isinstance(result.suppress_reason, str)
        assert isinstance(result.reason, str)


# ===========================================================================
# § STALE — items older than threshold are suppressed
# ===========================================================================

class TestStaleCheck:
    @pytest.mark.asyncio
    async def test_stale_item_suppressed(self, db_session):
        now = _now()
        old = now - timedelta(hours=STALE_THRESHOLD_HOURS + 1)
        row = _FakeRow(created_at=old)
        result = await relevance_recheck(db_session, row, now=now)
        assert result.should_deliver is False
        assert result.suppress_reason == REASON_RECHECK_STALE
        assert result.relevance_score == 0.0

    @pytest.mark.asyncio
    async def test_exactly_at_threshold_suppressed(self, db_session):
        now = _now()
        old = now - timedelta(hours=STALE_THRESHOLD_HOURS)
        row = _FakeRow(created_at=old)
        result = await relevance_recheck(db_session, row, now=now)
        assert result.should_deliver is False
        assert result.suppress_reason == REASON_RECHECK_STALE

    @pytest.mark.asyncio
    async def test_just_below_threshold_not_suppressed(self, db_session):
        now = _now()
        recent = now - timedelta(hours=STALE_THRESHOLD_HOURS - 0.5)
        row = _FakeRow(created_at=recent)
        result = await relevance_recheck(db_session, row, now=now)
        assert result.should_deliver is True

    @pytest.mark.asyncio
    async def test_unknown_age_not_stale(self, db_session):
        """created_at=None → unknown age → don't suppress."""
        row = _FakeRow(created_at=None)
        result = await relevance_recheck(db_session, row, now=_now())
        assert result.should_deliver is True

    @pytest.mark.asyncio
    async def test_stale_freshness_score_low(self, db_session):
        now = _now()
        old = now - timedelta(hours=STALE_THRESHOLD_HOURS + 24)
        row = _FakeRow(created_at=old)
        result = await relevance_recheck(db_session, row, now=now)
        assert result.freshness_score < 0.1   # very old → near-zero freshness


# ===========================================================================
# § DUP — same content_hash already delivered → suppress
# ===========================================================================

class TestDupDeliveredCheck:
    @pytest.mark.asyncio
    async def test_dup_delivered_suppressed(self, db_session):
        """Same content_hash in a delivered_shadow row → suppress."""
        from sqlalchemy import update
        from app.db.models import DeliveryLedger

        # Enqueue the same payload for two different users → same content_hash
        tag = _uid()
        payload = _payload(severity="critical")
        payload["tag"] = tag   # make payload unique to this test

        r1 = await enqueue(db_session, user_id="u-dup-A", channel="in_app",
                           target_key="TICK-DUP", payload=payload, severity="critical")
        r2 = await enqueue(db_session, user_id="u-dup-B", channel="in_app",
                           target_key="TICK-DUP", payload=payload, severity="critical")

        # Mark r1 delivered_shadow to simulate a prior flush
        await db_session.execute(
            update(DeliveryLedger)
            .where(DeliveryLedger.id == r1.delivery_id)
            .values(status="delivered_shadow")
            .execution_options(synchronize_session=False)
        )
        await db_session.flush()

        # Recheck r2: content_hash already in delivered_shadow → suppress
        row_r2 = await _get_ledger_row(db_session, r2.delivery_id)
        result  = await relevance_recheck(db_session, row_r2, now=_now())
        assert result.should_deliver is False
        assert result.suppress_reason == REASON_RECHECK_DUP_DELIVERED

    @pytest.mark.asyncio
    async def test_first_delivery_not_suppressed(self, db_session):
        """First occurrence of a content_hash passes the dup check."""
        r = await _enqueue_one(db_session)
        row = await _get_ledger_row(db_session, r.delivery_id)
        result = await relevance_recheck(db_session, row, now=_now())
        # Only the stale/dup/min_sev/superseded checks run; none should trigger
        assert result.should_deliver is True


# ===========================================================================
# § MIN_SEV — below current global min_severity → suppress
# ===========================================================================

class TestBelowMinSeverityCheck:
    @pytest.mark.asyncio
    async def test_below_global_min_sev_suppressed(self, db_session):
        """low severity below global min_severity=critical → suppress."""
        from app.db.repositories.delivery_prefs_repo import update_prefs

        # Set global prefs to critical
        await update_prefs(db_session, user_id=None, channel="in_app",
                           min_severity="critical")

        row = _FakeRow(canonical_severity="low")
        result = await relevance_recheck(db_session, row, now=_now())
        assert result.should_deliver is False
        assert result.suppress_reason == REASON_RECHECK_BELOW_MIN_SEV

    @pytest.mark.asyncio
    async def test_at_min_sev_not_suppressed(self, db_session):
        from app.db.repositories.delivery_prefs_repo import update_prefs
        await update_prefs(db_session, user_id=None, channel="in_app",
                           min_severity="high")
        row = _FakeRow(canonical_severity="high")
        result = await relevance_recheck(db_session, row, now=_now())
        assert result.should_deliver is True

    @pytest.mark.asyncio
    async def test_critical_above_any_floor(self, db_session):
        from app.db.repositories.delivery_prefs_repo import update_prefs
        await update_prefs(db_session, user_id=None, channel="in_app",
                           min_severity="high")
        row = _FakeRow(canonical_severity="critical")
        result = await relevance_recheck(db_session, row, now=_now())
        assert result.should_deliver is True

    @pytest.mark.asyncio
    async def test_no_canonical_severity_not_suppressed(self, db_session):
        """No canonical_severity on row → skip min_sev check (fail open)."""
        from app.db.repositories.delivery_prefs_repo import update_prefs
        await update_prefs(db_session, user_id=None, channel="in_app",
                           min_severity="critical")
        row = _FakeRow(canonical_severity=None)
        result = await relevance_recheck(db_session, row, now=_now())
        # No severity info → don't suppress
        assert result.should_deliver is True


# ===========================================================================
# § SUPERSEDED — artifact_ref signals supersession → suppress
# ===========================================================================

class TestSupersededCheck:
    @pytest.mark.asyncio
    async def test_superseded_artifact_ref_suppressed(self, db_session):
        row = _FakeRow(artifact_ref="superseded_by:newer-123")
        result = await relevance_recheck(db_session, row, now=_now())
        assert result.should_deliver is False
        assert result.suppress_reason == REASON_RECHECK_SUPERSEDED

    @pytest.mark.asyncio
    async def test_invalidated_artifact_ref_suppressed(self, db_session):
        row = _FakeRow(artifact_ref="invalidated:2026-06-14")
        result = await relevance_recheck(db_session, row, now=_now())
        assert result.should_deliver is False
        assert result.suppress_reason == REASON_RECHECK_SUPERSEDED

    @pytest.mark.asyncio
    async def test_normal_artifact_ref_not_suppressed(self, db_session):
        row = _FakeRow(artifact_ref="briefing-session-abc123")
        result = await relevance_recheck(db_session, row, now=_now())
        assert result.should_deliver is True

    @pytest.mark.asyncio
    async def test_empty_artifact_ref_not_suppressed(self, db_session):
        row = _FakeRow(artifact_ref=None)
        result = await relevance_recheck(db_session, row, now=_now())
        assert result.should_deliver is True

    @pytest.mark.asyncio
    async def test_superseded_case_insensitive(self, db_session):
        row = _FakeRow(artifact_ref="SUPERSEDED_BY:X")
        result = await relevance_recheck(db_session, row, now=_now())
        assert result.should_deliver is False


# ===========================================================================
# § FAIL_OPEN — exceptions do not suppress valid items
# ===========================================================================

class TestFailOpen:
    @pytest.mark.asyncio
    async def test_stale_check_exception_fails_open(self, db_session, monkeypatch):
        import app.services.delivery_relevance_service as svc
        monkeypatch.setattr(svc, "_check_stale", lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("boom")))
        row = _FakeRow()
        result = await relevance_recheck(db_session, row, now=_now())
        assert result.should_deliver is True

    @pytest.mark.asyncio
    async def test_dup_check_exception_fails_open(self, db_session, monkeypatch):
        import app.services.delivery_relevance_service as svc
        async def _raise(*a, **kw):
            raise RuntimeError("dup check boom")
        monkeypatch.setattr(svc, "_check_dup_delivered", _raise)
        row = _FakeRow()
        result = await relevance_recheck(db_session, row, now=_now())
        assert result.should_deliver is True

    @pytest.mark.asyncio
    async def test_min_sev_check_exception_fails_open(self, db_session, monkeypatch):
        import app.services.delivery_relevance_service as svc
        async def _raise(*a, **kw):
            raise RuntimeError("min_sev boom")
        monkeypatch.setattr(svc, "_check_below_min_sev", _raise)
        row = _FakeRow()
        result = await relevance_recheck(db_session, row, now=_now())
        assert result.should_deliver is True


# ===========================================================================
# § INTEGRATION — flush_pending_shadow now rechecks relevance
# ===========================================================================

class TestFlushIntegration:
    @pytest.mark.asyncio
    async def test_fresh_item_delivered_shadow(self, db_session, monkeypatch):
        """A fresh, valid item passes all guardrails AND recheck → delivered_shadow."""
        monkeypatch.setattr(ds, "_cfg_quiet_hours_start", lambda: 22)
        monkeypatch.setattr(ds, "_cfg_quiet_hours_end",   lambda: 7)

        result = await _enqueue_one(db_session, severity="critical")
        assert result.status == "pending"

        flush = await flush_pending_shadow(db_session, now=_at_hour(12), limit=10)
        assert any(r.status == STATUS_DELIVERED_SHADOW for r in flush)

    @pytest.mark.asyncio
    async def test_stale_item_suppressed_at_flush(self, db_session, monkeypatch):
        """Item with created_at > STALE_THRESHOLD_HOURS ago → suppressed by recheck."""
        monkeypatch.setattr(ds, "_cfg_quiet_hours_start", lambda: 22)
        monkeypatch.setattr(ds, "_cfg_quiet_hours_end",   lambda: 7)

        from sqlalchemy import update
        from app.db.models import DeliveryLedger

        result = await _enqueue_one(db_session, severity="critical")
        assert result.delivery_id is not None

        # Back-date the row to beyond the stale threshold relative to flush_now
        flush_now = _at_hour(12)
        old_ts = flush_now - timedelta(hours=STALE_THRESHOLD_HOURS + 1)
        await db_session.execute(
            update(DeliveryLedger)
            .where(DeliveryLedger.id == result.delivery_id)
            .values(created_at=old_ts)
            .execution_options(synchronize_session=False)
        )
        await db_session.flush()

        flush = await flush_pending_shadow(db_session, now=flush_now, limit=10)
        stale_suppressed = [r for r in flush if r.reason == REASON_RECHECK_STALE]
        assert len(stale_suppressed) >= 1

    @pytest.mark.asyncio
    async def test_dup_content_hash_suppressed_at_flush(self, db_session, monkeypatch):
        """Same content_hash already delivered → second delivery suppressed by recheck."""
        monkeypatch.setattr(ds, "_cfg_quiet_hours_start", lambda: 22)
        monkeypatch.setattr(ds, "_cfg_quiet_hours_end",   lambda: 7)

        from sqlalchemy import update
        from app.db.models import DeliveryLedger

        tag     = _uid()
        payload = _payload(severity="critical")
        payload["unique_tag"] = tag

        # Enqueue same payload for two users → same content_hash, different content_keys
        r1 = await enqueue(db_session, user_id="flush-A", channel="in_app",
                           target_key="TICK-FDUP", payload=payload, severity="critical")
        r2 = await enqueue(db_session, user_id="flush-B", channel="in_app",
                           target_key="TICK-FDUP", payload=payload, severity="critical")

        # Mark r1 delivered manually so the recheck for r2 sees it
        await db_session.execute(
            update(DeliveryLedger)
            .where(DeliveryLedger.id == r1.delivery_id)
            .values(status="delivered_shadow")
            .execution_options(synchronize_session=False)
        )
        await db_session.flush()

        # r2 is still pending; flush processes it
        flush = await flush_pending_shadow(db_session, now=_at_hour(12), limit=10)
        dup_suppressed = [r for r in flush if r.reason == REASON_RECHECK_DUP_DELIVERED]
        assert len(dup_suppressed) >= 1, "duplicate content_hash must be suppressed at flush"

    @pytest.mark.asyncio
    async def test_superseded_artifact_ref_suppressed_at_flush(self, db_session, monkeypatch):
        """artifact_ref='superseded_by:X' → suppressed by recheck at flush."""
        monkeypatch.setattr(ds, "_cfg_quiet_hours_start", lambda: 22)
        monkeypatch.setattr(ds, "_cfg_quiet_hours_end",   lambda: 7)

        from sqlalchemy import update
        from app.db.models import DeliveryLedger

        result = await _enqueue_one(db_session, severity="critical")
        assert result.delivery_id is not None

        # Mark artifact_ref to signal supersession
        await db_session.execute(
            update(DeliveryLedger)
            .where(DeliveryLedger.id == result.delivery_id)
            .values(artifact_ref="superseded_by:newer-version")
            .execution_options(synchronize_session=False)
        )
        await db_session.flush()

        flush = await flush_pending_shadow(db_session, now=_at_hour(12), limit=10)
        superseded = [r for r in flush if r.reason == REASON_RECHECK_SUPERSEDED]
        assert len(superseded) >= 1

    @pytest.mark.asyncio
    async def test_below_min_sev_suppressed_at_flush_after_prefs_change(
        self, db_session, monkeypatch
    ):
        """Prefs changed to critical after enqueue → medium suppressed at flush."""
        monkeypatch.setattr(ds, "_cfg_quiet_hours_start", lambda: 22)
        monkeypatch.setattr(ds, "_cfg_quiet_hours_end",   lambda: 7)

        from app.db.repositories.delivery_prefs_repo import update_prefs

        uid = f"user-minsev-{_uid()}"

        # Enqueue medium item (default prefs: min_severity=info → enqueue passes)
        result = await enqueue(
            db_session, user_id=uid, channel="in_app", target_key="TICK-MS",
            payload=_payload(severity="medium"), severity="medium",
        )
        assert result.status == "pending"

        # Change global prefs to critical AFTER enqueue
        await update_prefs(db_session, user_id=None, channel="in_app",
                           min_severity="critical")

        flush = await flush_pending_shadow(db_session, now=_at_hour(12), limit=10)
        min_sev_suppressed = [r for r in flush
                               if r.reason == REASON_RECHECK_BELOW_MIN_SEV]
        assert len(min_sev_suppressed) >= 1

    @pytest.mark.asyncio
    async def test_existing_quiet_hours_guardrail_still_works(self, db_session, monkeypatch):
        """Slice 6 must not break Slice 8 quiet_hours guardrail."""
        monkeypatch.setattr(ds, "_cfg_quiet_hours_start", lambda: 22)
        monkeypatch.setattr(ds, "_cfg_quiet_hours_end",   lambda: 7)

        result = await _enqueue_one(db_session, severity="critical")
        assert result.status == "pending"

        flush = await flush_pending_shadow(db_session, now=_at_hour(23), limit=10)
        quiet_suppressed = [r for r in flush if r.reason == "quiet_hours"]
        assert len(quiet_suppressed) >= 1


# ===========================================================================
# § SAFETY — no notifications, no external sends
# ===========================================================================

class TestSafety:
    @pytest.mark.asyncio
    async def test_no_notifications_from_recheck_suppression(self, db_session, monkeypatch):
        monkeypatch.setattr(ds, "_cfg_quiet_hours_start", lambda: 22)
        monkeypatch.setattr(ds, "_cfg_quiet_hours_end",   lambda: 7)

        from app.db.models import Notification
        from sqlalchemy import select, func, update
        from app.db.models import DeliveryLedger

        result = await _enqueue_one(db_session, severity="critical")

        # Force stale relative to flush reference time
        flush_now = _at_hour(12)
        old_ts = flush_now - timedelta(hours=STALE_THRESHOLD_HOURS + 1)
        await db_session.execute(
            update(DeliveryLedger)
            .where(DeliveryLedger.id == result.delivery_id)
            .values(created_at=old_ts)
            .execution_options(synchronize_session=False)
        )
        await db_session.flush()

        before = (await db_session.execute(
            select(func.count()).select_from(Notification)
        )).scalar()

        await flush_pending_shadow(db_session, now=_at_hour(12), limit=10)

        after = (await db_session.execute(
            select(func.count()).select_from(Notification)
        )).scalar()

        assert before == after, "recheck suppression must not create Notification rows"

    @pytest.mark.asyncio
    async def test_no_notifications_from_normal_recheck_pass(self, db_session, monkeypatch):
        monkeypatch.setattr(ds, "_cfg_quiet_hours_start", lambda: 22)
        monkeypatch.setattr(ds, "_cfg_quiet_hours_end",   lambda: 7)

        from app.db.models import Notification
        from sqlalchemy import select, func

        await _enqueue_one(db_session, severity="critical")

        before = (await db_session.execute(
            select(func.count()).select_from(Notification)
        )).scalar()

        await flush_pending_shadow(db_session, now=_at_hour(12), limit=10)

        after = (await db_session.execute(
            select(func.count()).select_from(Notification)
        )).scalar()

        assert before == after


# ---------------------------------------------------------------------------
# Fixture helper
# ---------------------------------------------------------------------------

async def _get_ledger_row(db_session, delivery_id: str):
    from sqlalchemy import select
    from app.db.models import DeliveryLedger
    return (await db_session.execute(
        select(DeliveryLedger)
        .where(DeliveryLedger.id == delivery_id)
        .execution_options(populate_existing=True)
    )).scalar_one()
