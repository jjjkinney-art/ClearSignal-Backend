"""
Phase 10C · Slice 5 — Digest Batching tests.

Covers (no external sends, no notifications, no real delivery):

  § SERVICE       — period_bucket_for, add_to_digest, get_open_batch
  § DEDUP         — duplicate content_key is never added twice
  § SEPARATION    — period_bucket / user_id / channel isolation
  § ENQUEUE       — digest-class items are routed to digest batch at enqueue time
  § OVERFLOW      — daily_cap overflow is redirected to digest at flush time
  § SAFETY        — no Notification rows, no external sends
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

import pytest

from app.services.digest_batch_service import (
    DigestAddResult,
    BATCH_STATUS_OPEN,
    _ITEMS_KEY,
    period_bucket_for,
    add_to_digest,
    get_open_batch,
)
from app.services import loop_delivery_service as ds
from app.services.loop_delivery_service import (
    STATUS_SUPPRESSED_GUARDRAIL,
    STATUS_SUPPRESSED_DUPLICATE,
    REASON_DAILY_CAP,
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


def _bucket(dt: Optional[datetime] = None) -> str:
    return period_bucket_for(dt)


def _item(tag: Optional[str] = None, **extra) -> dict:
    t = tag or _uid()
    return {"message": f"digest-test-{t}", "severity": "medium", **extra}


def _payload(severity: str = "medium", tag: Optional[str] = None) -> dict:
    t = tag or _uid()
    return {
        "message": f"test-{t}",
        "severity": severity,
        "priority_score": 0.0,   # weak score → digest for high, digest for medium
        "materiality": 0.0,
        "relevance": 0.0,
        "created_at": _now().isoformat(),
    }


async def _enqueue(db_session, *, severity="medium", tag=None, user_id=None,
                   channel="in_app", target_key=None) -> ds.DeliveryResult:
    t = tag or _uid()
    return await enqueue(
        db_session,
        user_id=user_id or f"user-{t}",
        channel=channel,
        target_key=target_key or f"TICK-{t}",
        payload=_payload(severity=severity, tag=t),
        severity=severity,
    )


def _at_hour(h: int) -> datetime:
    return _now().replace(hour=h, minute=0, second=0, microsecond=0)


# ===========================================================================
# § SERVICE — direct unit tests of digest_batch_service
# ===========================================================================

class TestPeriodBucket:
    def test_returns_yyyy_mm_dd(self):
        bucket = period_bucket_for(datetime(2026, 6, 14, 12, 0, 0, tzinfo=timezone.utc))
        assert bucket == "2026-06-14"

    def test_midnight_boundary_correct(self):
        just_before = datetime(2026, 6, 14, 23, 59, 59, tzinfo=timezone.utc)
        just_after  = datetime(2026, 6, 15,  0,  0,  1, tzinfo=timezone.utc)
        assert period_bucket_for(just_before) == "2026-06-14"
        assert period_bucket_for(just_after)  == "2026-06-15"

    def test_naive_datetime_treated_as_utc(self):
        naive = datetime(2026, 6, 14, 12, 0, 0)
        assert period_bucket_for(naive) == "2026-06-14"

    def test_none_uses_today(self):
        bucket = period_bucket_for()
        today  = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        assert bucket == today


class TestAddToDigest:
    @pytest.mark.asyncio
    async def test_creates_new_batch_on_first_call(self, db_session):
        bucket = _bucket()
        result = await add_to_digest(
            db_session,
            user_id="u1",
            channel="in_app",
            period_bucket=bucket,
            item=_item(content_key="ck-1"),
            item_content_key="ck-1",
        )
        assert result is not None
        assert result.added is True
        assert result.item_count == 1
        assert result.content_key == "ck-1"
        assert result.period_bucket == bucket

    @pytest.mark.asyncio
    async def test_appends_item_to_existing_batch(self, db_session):
        bucket = _bucket()
        uid    = f"u-{_uid()}"

        r1 = await add_to_digest(db_session, user_id=uid, channel="in_app",
                                  period_bucket=bucket, item=_item(), item_content_key="ck-a")
        r2 = await add_to_digest(db_session, user_id=uid, channel="in_app",
                                  period_bucket=bucket, item=_item(), item_content_key="ck-b")

        assert r1.added is True
        assert r2.added is True
        assert r1.batch_id == r2.batch_id    # same batch
        assert r2.item_count == 2

    @pytest.mark.asyncio
    async def test_item_count_matches_distinct_items(self, db_session):
        bucket = _bucket()
        uid    = f"u-{_uid()}"

        for i in range(5):
            await add_to_digest(db_session, user_id=uid, channel="in_app",
                                 period_bucket=bucket,
                                 item=_item(), item_content_key=f"ck-{i}")

        batch = await get_open_batch(db_session, user_id=uid, channel="in_app",
                                      period_bucket=bucket)
        assert batch is not None
        assert batch.item_count == 5
        assert len(batch.payload_json[_ITEMS_KEY]) == 5

    @pytest.mark.asyncio
    async def test_null_session_returns_none(self):
        result = await add_to_digest(
            None, user_id="u", channel="in_app",
            period_bucket=_bucket(), item=_item(), item_content_key="ck-x",
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_payload_json_structure_stable(self, db_session):
        bucket = _bucket()
        uid    = f"u-{_uid()}"
        item   = {"content_key": "ck-q", "target_key": "AAPL", "severity": "medium"}

        await add_to_digest(db_session, user_id=uid, channel="in_app",
                             period_bucket=bucket, item=item, item_content_key="ck-q")

        batch = await get_open_batch(db_session, user_id=uid, channel="in_app",
                                      period_bucket=bucket)
        items = batch.payload_json[_ITEMS_KEY]
        assert len(items) == 1
        stored = items[0]
        assert stored["content_key"] == "ck-q"
        assert stored["target_key"]  == "AAPL"
        assert stored["severity"]    == "medium"

    @pytest.mark.asyncio
    async def test_batch_status_is_open(self, db_session):
        bucket = _bucket()
        uid    = f"u-{_uid()}"
        await add_to_digest(db_session, user_id=uid, channel="in_app",
                             period_bucket=bucket, item=_item(), item_content_key="ck-s")
        batch = await get_open_batch(db_session, user_id=uid, channel="in_app",
                                      period_bucket=bucket)
        assert batch.status == BATCH_STATUS_OPEN


# ===========================================================================
# § DEDUP — same content_key never added twice
# ===========================================================================

class TestDeduplication:
    @pytest.mark.asyncio
    async def test_duplicate_content_key_not_added(self, db_session):
        bucket = _bucket()
        uid    = f"u-{_uid()}"

        r1 = await add_to_digest(db_session, user_id=uid, channel="in_app",
                                  period_bucket=bucket, item=_item(), item_content_key="ck-dup")
        r2 = await add_to_digest(db_session, user_id=uid, channel="in_app",
                                  period_bucket=bucket, item=_item(), item_content_key="ck-dup")

        assert r1.added is True
        assert r2.added is False
        assert r2.item_count == 1  # count unchanged

    @pytest.mark.asyncio
    async def test_duplicate_preserves_batch_id(self, db_session):
        bucket = _bucket()
        uid    = f"u-{_uid()}"

        r1 = await add_to_digest(db_session, user_id=uid, channel="in_app",
                                  period_bucket=bucket, item=_item(), item_content_key="ck-x")
        r2 = await add_to_digest(db_session, user_id=uid, channel="in_app",
                                  period_bucket=bucket, item=_item(), item_content_key="ck-x")

        assert r1.batch_id == r2.batch_id

    @pytest.mark.asyncio
    async def test_non_duplicate_still_added(self, db_session):
        bucket = _bucket()
        uid    = f"u-{_uid()}"

        r1 = await add_to_digest(db_session, user_id=uid, channel="in_app",
                                  period_bucket=bucket, item=_item(), item_content_key="ck-1")
        r2 = await add_to_digest(db_session, user_id=uid, channel="in_app",
                                  period_bucket=bucket, item=_item(), item_content_key="ck-1")  # dup
        r3 = await add_to_digest(db_session, user_id=uid, channel="in_app",
                                  period_bucket=bucket, item=_item(), item_content_key="ck-2")  # new

        assert r1.added is True
        assert r2.added is False
        assert r3.added is True
        assert r3.item_count == 2


# ===========================================================================
# § SEPARATION — period_bucket / user_id / channel isolation
# ===========================================================================

class TestBatchSeparation:
    @pytest.mark.asyncio
    async def test_different_period_buckets_different_batches(self, db_session):
        uid = f"u-{_uid()}"
        r1 = await add_to_digest(db_session, user_id=uid, channel="in_app",
                                  period_bucket="2026-06-13", item=_item(), item_content_key="ck-a")
        r2 = await add_to_digest(db_session, user_id=uid, channel="in_app",
                                  period_bucket="2026-06-14", item=_item(), item_content_key="ck-a")
        assert r1.batch_id != r2.batch_id
        assert r1.item_count == 1
        assert r2.item_count == 1

    @pytest.mark.asyncio
    async def test_different_users_different_batches(self, db_session):
        bucket = _bucket()
        r1 = await add_to_digest(db_session, user_id="user-A", channel="in_app",
                                  period_bucket=bucket, item=_item(), item_content_key="ck-u1")
        r2 = await add_to_digest(db_session, user_id="user-B", channel="in_app",
                                  period_bucket=bucket, item=_item(), item_content_key="ck-u1")
        # same content_key is fine across different users (different batches)
        assert r1.batch_id != r2.batch_id
        assert r1.added is True
        assert r2.added is True

    @pytest.mark.asyncio
    async def test_different_channels_different_batches(self, db_session):
        bucket = _bucket()
        uid    = f"u-{_uid()}"
        r1 = await add_to_digest(db_session, user_id=uid, channel="in_app",
                                  period_bucket=bucket, item=_item(), item_content_key="ck-ch")
        r2 = await add_to_digest(db_session, user_id=uid, channel="email",
                                  period_bucket=bucket, item=_item(), item_content_key="ck-ch")
        assert r1.batch_id != r2.batch_id


# ===========================================================================
# § ENQUEUE — digest-class items routed to digest batch
# ===========================================================================

class TestDigestClassRouting:
    @pytest.mark.asyncio
    async def test_medium_severity_creates_digest_batch(self, db_session):
        """medium severity → delivery_class=digest → digest batch created."""
        bucket = _bucket()
        result = await _enqueue(db_session, severity="medium")
        assert result.status == "pending"

        # A digest batch must have been created for today's bucket
        batch = await get_open_batch(
            db_session,
            user_id=result.payload_json and
                    result.payload_json.get("ranking", {}).get("canonical_severity") and
                    None or None,   # user_id from enqueue call — check via item_count
            channel="in_app",
            period_bucket=bucket,
        )
        # batch may be under a specific user_id; verify via items
        # Check that at least one batch exists for today's bucket
        from app.db.models import DigestBatch
        from sqlalchemy import select, func
        count = (await db_session.execute(
            select(func.count()).select_from(DigestBatch)
            .where(DigestBatch.period_bucket == bucket)
            .where(DigestBatch.channel == "in_app")
        )).scalar()
        assert count >= 1

    @pytest.mark.asyncio
    async def test_medium_digest_item_in_batch(self, db_session):
        """Verify the enqueued item appears in the digest batch payload."""
        bucket = _bucket()
        uid    = f"user-{_uid()}"
        tag    = _uid()

        await enqueue(
            db_session,
            user_id=uid,
            channel="in_app",
            target_key=f"TICK-{tag}",
            payload=_payload(severity="medium", tag=tag),
            severity="medium",
        )

        batch = await get_open_batch(db_session, user_id=uid, channel="in_app",
                                      period_bucket=bucket)
        assert batch is not None
        assert batch.item_count >= 1
        items = batch.payload_json.get(_ITEMS_KEY, [])
        assert len(items) >= 1

    @pytest.mark.asyncio
    async def test_digest_also_keeps_ledger_row(self, db_session):
        """Digest routing preserves the ledger row as the dedup anchor."""
        result = await _enqueue(db_session, severity="medium")
        assert result.status == "pending"
        assert result.delivery_id is not None  # ledger row exists

    @pytest.mark.asyncio
    async def test_critical_push_now_does_not_create_digest_batch(self, db_session):
        """critical (push_now) must NOT create a digest batch entry."""
        bucket = _bucket()
        uid    = f"user-crit-{_uid()}"

        await enqueue(
            db_session,
            user_id=uid,
            channel="in_app",
            target_key="TICK-CRIT",
            payload=_payload(severity="critical"),
            severity="critical",
        )

        batch = await get_open_batch(db_session, user_id=uid, channel="in_app",
                                      period_bucket=bucket)
        # push_now should not create a digest batch
        assert batch is None

    @pytest.mark.asyncio
    async def test_duplicate_enqueue_does_not_add_second_digest_item(self, db_session):
        """Second enqueue of same content → duplicate ledger + digest dedup."""
        bucket = _bucket()
        uid    = f"user-dup-{_uid()}"
        tag    = _uid()

        payload = _payload(severity="medium", tag=tag)
        await enqueue(db_session, user_id=uid, channel="in_app",
                      target_key="TICK-DUP2", payload=payload, severity="medium")
        await enqueue(db_session, user_id=uid, channel="in_app",
                      target_key="TICK-DUP2", payload=payload, severity="medium")

        batch = await get_open_batch(db_session, user_id=uid, channel="in_app",
                                      period_bucket=bucket)
        # Only one distinct item (first write wins; second is deduped at both
        # delivery_ledger level and digest_batch level).
        assert batch is not None
        assert batch.item_count == 1


# ===========================================================================
# § OVERFLOW — daily_cap overflow redirected to digest
# ===========================================================================

class TestDailyCapOverflow:
    @pytest.mark.asyncio
    async def test_overflow_item_redirected_to_digest(self, db_session, monkeypatch):
        """Cap=2: the 3rd item (suppressed by cap) should appear in a digest batch."""
        monkeypatch.setattr(ds, "_cfg_quiet_hours_start", lambda: 22)
        monkeypatch.setattr(ds, "_cfg_quiet_hours_end",   lambda: 7)
        monkeypatch.setattr(ds, "_cfg_daily_cap",         lambda: 2)

        user_id    = f"user:{_uid()}"
        target_key = f"AAPL:{_uid()}"
        flush_now  = _at_hour(12)

        for i in range(3):
            await enqueue(db_session, user_id=user_id, channel="in_app",
                          target_key=target_key, payload={"i": i, "severity": "critical"})

        results = await flush_pending_shadow(db_session, now=flush_now, limit=50)

        # 2 delivered, 1 suppressed by daily_cap
        assert sum(1 for r in results if r.reason == REASON_DAILY_CAP) == 1

        # The overflow item must have landed in today's digest batch
        bucket = period_bucket_for(flush_now)
        from app.db.models import DigestBatch
        from sqlalchemy import select, func
        count = (await db_session.execute(
            select(func.count()).select_from(DigestBatch)
            .where(DigestBatch.channel == "in_app")
            .where(DigestBatch.period_bucket == bucket)
        )).scalar()
        assert count >= 1, "daily_cap overflow must create a digest batch"

    @pytest.mark.asyncio
    async def test_overflow_item_in_batch_payload(self, db_session, monkeypatch):
        """The overflow item's content_key must appear in digest_batches.payload_json."""
        monkeypatch.setattr(ds, "_cfg_quiet_hours_start", lambda: 22)
        monkeypatch.setattr(ds, "_cfg_quiet_hours_end",   lambda: 7)
        monkeypatch.setattr(ds, "_cfg_daily_cap",         lambda: 1)

        target_key = f"NVDA:{_uid()}"
        flush_now  = _at_hour(12)

        # First item will be delivered, second will overflow to digest
        r1 = await enqueue(db_session, user_id="global", channel="in_app",
                           target_key=target_key, payload={"msg": "first"})
        r2 = await enqueue(db_session, user_id="global", channel="in_app",
                           target_key=target_key, payload={"msg": "second"})

        await flush_pending_shadow(db_session, now=flush_now, limit=50)

        # The overflow item's content_key must be in a digest batch
        bucket = period_bucket_for(flush_now)
        batch  = await get_open_batch(db_session, user_id=None, channel="in_app",
                                       period_bucket=bucket)
        assert batch is not None
        items = batch.payload_json.get(_ITEMS_KEY, [])
        assert len(items) >= 1
        # Verify the overflow item's content_key appears in the batch
        stored_keys = {i.get("content_key") for i in items}
        assert r2.content_key in stored_keys

    @pytest.mark.asyncio
    async def test_overflow_batch_item_count_correct(self, db_session, monkeypatch):
        """Two distinct overflow items → digest batch item_count == 2."""
        monkeypatch.setattr(ds, "_cfg_quiet_hours_start", lambda: 22)
        monkeypatch.setattr(ds, "_cfg_quiet_hours_end",   lambda: 7)
        monkeypatch.setattr(ds, "_cfg_daily_cap",         lambda: 1)

        target_key = f"META:{_uid()}"
        flush_now  = _at_hour(12)

        await enqueue(db_session, user_id="global", channel="in_app",
                      target_key=target_key, payload={"msg": "item-1"})
        await enqueue(db_session, user_id="global", channel="in_app",
                      target_key=target_key, payload={"msg": "item-2"})
        await enqueue(db_session, user_id="global", channel="in_app",
                      target_key=target_key, payload={"msg": "item-3"})

        await flush_pending_shadow(db_session, now=flush_now, limit=50)

        bucket = period_bucket_for(flush_now)
        batch  = await get_open_batch(db_session, user_id=None, channel="in_app",
                                       period_bucket=bucket)
        assert batch is not None
        assert batch.item_count == 2   # 1 delivered, 2 overflow


# ===========================================================================
# § SAFETY — no notifications, no external sends
# ===========================================================================

class TestSafety:
    @pytest.mark.asyncio
    async def test_no_notifications_created_by_digest_service(self, db_session):
        from app.db.models import Notification
        from sqlalchemy import select, func

        before = (await db_session.execute(
            select(func.count()).select_from(Notification)
        )).scalar()

        bucket = _bucket()
        for i in range(3):
            await add_to_digest(
                db_session, user_id=f"u-{_uid()}", channel="in_app",
                period_bucket=bucket, item=_item(), item_content_key=f"ck-n-{i}",
            )

        after = (await db_session.execute(
            select(func.count()).select_from(Notification)
        )).scalar()

        assert before == after, "add_to_digest must not create Notification rows"

    @pytest.mark.asyncio
    async def test_no_notifications_created_by_digest_routing(self, db_session):
        from app.db.models import Notification
        from sqlalchemy import select, func

        before = (await db_session.execute(
            select(func.count()).select_from(Notification)
        )).scalar()

        await _enqueue(db_session, severity="medium")
        await _enqueue(db_session, severity="low")

        after = (await db_session.execute(
            select(func.count()).select_from(Notification)
        )).scalar()

        assert before == after

    @pytest.mark.asyncio
    async def test_no_notifications_created_by_overflow(self, db_session, monkeypatch):
        from app.db.models import Notification
        from sqlalchemy import select, func

        monkeypatch.setattr(ds, "_cfg_quiet_hours_start", lambda: 22)
        monkeypatch.setattr(ds, "_cfg_quiet_hours_end",   lambda: 7)
        monkeypatch.setattr(ds, "_cfg_daily_cap",         lambda: 1)

        target_key = f"GS:{_uid()}"
        for i in range(3):
            await enqueue(db_session, user_id="global", channel="in_app",
                          target_key=target_key, payload={"i": i})

        before = (await db_session.execute(
            select(func.count()).select_from(Notification)
        )).scalar()

        await flush_pending_shadow(db_session, now=_at_hour(12), limit=50)

        after = (await db_session.execute(
            select(func.count()).select_from(Notification)
        )).scalar()

        assert before == after
