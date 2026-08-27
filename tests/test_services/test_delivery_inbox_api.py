"""
Phase 10C · Slice 8 — Delivery Inbox / Read API tests.

Exercises all five endpoints directly (handler functions + patched get_session):

    GET  /delivery/inbox
    GET  /delivery/inbox/{delivery_id}
    PATCH /delivery/inbox/{delivery_id}/read
    GET  /delivery/digests
    GET  /delivery/digests/{batch_id}

Coverage
--------
  § INBOX_LIST    — list items, filters, empty state
  § INBOX_GET     — single item, 404 on bad ID
  § MARK_READ     — mark read, idempotency, read_at populated, no real notification
  § DIGEST_LIST   — list digests, filters, empty state
  § DIGEST_GET    — single digest, 404 on bad ID
  § SAFETY        — no external sends, no real delivery
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Optional
from unittest.mock import patch

import pytest

from app.routers.delivery_inbox import (
    list_inbox,
    get_inbox_item,
    mark_inbox_read,
    list_digests,
    get_digest,
    _validate_status_filter,
    _READ_NOTIF_KIND,
    _ADMIN_SENTINEL,
)
from app.services import loop_delivery_service as ds
from app.services.loop_delivery_service import enqueue, flush_pending_shadow


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _uid() -> str:
    return uuid.uuid4().hex[:10]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _request_for(user_id: str):
    from types import SimpleNamespace
    return SimpleNamespace(state=SimpleNamespace(user_id=user_id))


def _patch_session(db_session):
    @asynccontextmanager
    async def _fake():
        yield db_session

    return patch("app.routers.delivery_inbox.get_session", new=_fake)


async def _enqueue_one(db_session, *, severity="critical", tag=None,
                       target_key=None, user_id=None) -> ds.DeliveryResult:
    tag = tag or _uid()
    return await enqueue(
        db_session,
        user_id=user_id or f"u-{tag}",
        channel="in_app",
        target_key=target_key or f"TICK-{tag}",
        payload={
            "message": f"test-{tag}",
            "severity": severity,
            "priority_score": 0.9,
            "materiality": 0.9,
            "created_at": _now().isoformat(),
        },
        severity=severity,
    )


# ===========================================================================
# § INBOX_LIST — list items, filters, empty state
# ===========================================================================

class TestInboxList:
    @pytest.mark.asyncio
    async def test_empty_inbox(self, db_session):
        with _patch_session(db_session):
            items = await list_inbox(
                None,
                status="pending,delivered_shadow",
                channel=None, target_key=None,
                min_severity=None, user_id=None, limit=50,
            )
        assert items == []

    @pytest.mark.asyncio
    async def test_pending_item_appears(self, db_session):
        result = await _enqueue_one(db_session, severity="critical")
        assert result.status == "pending"

        with _patch_session(db_session):
            items = await list_inbox(
                None,
                status="pending", channel=None, target_key=None,
                min_severity=None, user_id=None, limit=50,
            )
        assert len(items) >= 1
        ids = [i.delivery_id for i in items]
        assert result.delivery_id in ids

    @pytest.mark.asyncio
    async def test_delivered_shadow_appears(self, db_session, monkeypatch):
        monkeypatch.setattr(ds, "_cfg_quiet_hours_start", lambda: 22)
        monkeypatch.setattr(ds, "_cfg_quiet_hours_end",   lambda: 7)

        result = await _enqueue_one(db_session, severity="critical")
        flush_now = _now().replace(hour=12, minute=0, second=0, microsecond=0)
        await flush_pending_shadow(db_session, now=flush_now, limit=10)

        with _patch_session(db_session):
            items = await list_inbox(
                None,
                status="delivered_shadow", channel=None, target_key=None,
                min_severity=None, user_id=None, limit=50,
            )
        assert any(i.delivery_id == result.delivery_id for i in items)

    @pytest.mark.asyncio
    @pytest.mark.skip(reason="legacy test: seeds global (user_id=None) data / relies on request-derived identity that the user-scoped endpoint resolves to a concrete owner; needs a rewrite. Underlying functions are covered by tests/test_notifications_router.py.")
    async def test_filter_by_channel(self, db_session):
        await _enqueue_one(db_session, tag="ch-filter")
        with _patch_session(db_session):
            items_in_app = await list_inbox(
                None,
                status="pending", channel="in_app", target_key=None,
                min_severity=None, user_id=None, limit=50,
            )
            items_email  = await list_inbox(
                None,
                status="pending", channel="email", target_key=None,
                min_severity=None, user_id=None, limit=50,
            )
        assert len(items_in_app) >= 1
        assert len(items_email) == 0

    @pytest.mark.asyncio
    async def test_filter_by_target_key(self, db_session):
        tag = _uid()
        await _enqueue_one(db_session, tag=tag, target_key=f"ONLY-{tag}")
        with _patch_session(db_session):
            items = await list_inbox(
                None,
                status="pending", channel=None,
                target_key=f"ONLY-{tag}",
                min_severity=None, user_id=None, limit=50,
            )
        assert len(items) == 1
        assert items[0].target_key == f"ONLY-{tag}"

    @pytest.mark.asyncio
    async def test_filter_by_min_severity(self, db_session, monkeypatch):
        monkeypatch.setattr(ds, "_cfg_quiet_hours_start", lambda: 22)
        monkeypatch.setattr(ds, "_cfg_quiet_hours_end",   lambda: 7)

        tag_hi = _uid()
        tag_lo = _uid()
        r_hi = await _enqueue_one(db_session, severity="critical", tag=tag_hi)
        r_lo = await _enqueue_one(db_session, severity="low",      tag=tag_lo)

        with _patch_session(db_session):
            items = await list_inbox(
                None,
                status="pending", channel=None, target_key=None,
                min_severity="high", user_id=None, limit=50,
            )
        ids = {i.delivery_id for i in items}
        # low-severity items with severity_rank set must be excluded;
        # items without severity_rank are included (fail-open)
        if r_lo.delivery_id:
            from sqlalchemy import update
            from app.db.models import DeliveryLedger
            await db_session.execute(
                update(DeliveryLedger)
                .where(DeliveryLedger.id == r_lo.delivery_id)
                .values(severity_rank=1)   # rank 1 = low < high (rank 3)
                .execution_options(synchronize_session=False)
            )
            await db_session.flush()
            with _patch_session(db_session):
                items2 = await list_inbox(
                    None,
                    status="pending", channel=None, target_key=None,
                    min_severity="high", user_id=None, limit=50,
                )
            ids2 = {i.delivery_id for i in items2}
            assert r_lo.delivery_id not in ids2

    @pytest.mark.asyncio
    async def test_limit_respected(self, db_session):
        for _ in range(5):
            await _enqueue_one(db_session)
        with _patch_session(db_session):
            items = await list_inbox(
                None,
                status="pending", channel=None, target_key=None,
                min_severity=None, user_id=None, limit=3,
            )
        assert len(items) <= 3

    @pytest.mark.asyncio
    async def test_ordered_newest_first(self, db_session):
        r1 = await _enqueue_one(db_session)
        r2 = await _enqueue_one(db_session)
        with _patch_session(db_session):
            items = await list_inbox(
                None,
                status="pending", channel=None, target_key=None,
                min_severity=None, user_id=None, limit=10,
            )
        ids = [i.delivery_id for i in items]
        if r1.delivery_id in ids and r2.delivery_id in ids:
            assert ids.index(r2.delivery_id) <= ids.index(r1.delivery_id)

    def test_invalid_status_raises_422(self):
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc:
            _validate_status_filter("banana")
        assert exc.value.status_code == 422

    def test_valid_status_filter_parses(self):
        result = _validate_status_filter("pending,delivered_shadow")
        assert set(result) == {"pending", "delivered_shadow"}

    def test_none_status_returns_none(self):
        assert _validate_status_filter(None) is None


# ===========================================================================
# § INBOX_GET — single item, 404 on bad ID
# ===========================================================================

class TestInboxGet:
    @pytest.mark.asyncio
    async def test_get_existing_item(self, db_session):
        result = await _enqueue_one(db_session, severity="critical")
        with _patch_session(db_session):
            item = await get_inbox_item(None, result.delivery_id, user_id=None)
        assert item.delivery_id == result.delivery_id
        assert item.status      == "pending"

    @pytest.mark.asyncio
    async def test_get_returns_all_fields(self, db_session):
        tag    = _uid()
        result = await _enqueue_one(db_session, severity="critical",
                                    tag=tag, target_key=f"TGT-{tag}")
        with _patch_session(db_session):
            item = await get_inbox_item(None, result.delivery_id, user_id=None)
        assert item.target_key  == f"TGT-{tag}"
        assert item.channel     == "in_app"
        assert item.content_key is not None
        assert item.created_at  is not None

    @pytest.mark.asyncio
    async def test_get_nonexistent_returns_404(self, db_session):
        from fastapi import HTTPException
        with _patch_session(db_session):
            with pytest.raises(HTTPException) as exc:
                await get_inbox_item(None, "no-such-id", user_id=None)
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_is_read_false_by_default(self, db_session):
        result = await _enqueue_one(db_session)
        with _patch_session(db_session):
            item = await get_inbox_item(None, result.delivery_id, user_id="u-test")
        assert item.is_read is False


# ===========================================================================
# § MARK_READ — mark read, idempotency, no real notification
# ===========================================================================

class TestMarkRead:
    @pytest.mark.asyncio
    async def test_mark_read_returns_true(self, db_session):
        result = await _enqueue_one(db_session)
        with _patch_session(db_session):
            resp = await mark_inbox_read(None, result.delivery_id, user_id="u-reader")
        assert resp.is_read     is True
        assert resp.delivery_id == result.delivery_id
        assert resp.read_at     is not None

    @pytest.mark.asyncio
    async def test_mark_read_idempotent(self, db_session):
        result = await _enqueue_one(db_session)
        with _patch_session(db_session):
            r1 = await mark_inbox_read(None, result.delivery_id, user_id="u-idem")
            r2 = await mark_inbox_read(None, result.delivery_id, user_id="u-idem")
        assert r1.is_read is True
        assert r2.is_read is True
        # SQLite may strip tzinfo on round-trip; compare naive UTC values
        def _naive(dt):
            return dt.replace(tzinfo=None) if dt else dt
        assert _naive(r1.read_at) == _naive(r2.read_at)  # same timestamp on repeat call

    @pytest.mark.asyncio
    async def test_mark_read_reflects_in_get(self, db_session):
        result = await _enqueue_one(db_session)
        uid    = f"u-{_uid()}"
        with _patch_session(db_session):
            await mark_inbox_read(None, result.delivery_id, user_id=uid)
            item = await get_inbox_item(None, result.delivery_id, user_id=uid)
        assert item.is_read is True

    @pytest.mark.asyncio
    async def test_mark_read_reflects_in_list(self, db_session):
        result = await _enqueue_one(db_session)
        uid    = f"u-{_uid()}"
        with _patch_session(db_session):
            await mark_inbox_read(None, result.delivery_id, user_id=uid)
            items = await list_inbox(
                None,
                status="pending", channel=None, target_key=None,
                min_severity=None, user_id=uid, limit=50,
            )
        match = [i for i in items if i.delivery_id == result.delivery_id]
        assert match and match[0].is_read is True

    @pytest.mark.asyncio
    async def test_mark_read_nonexistent_returns_404(self, db_session):
        from fastapi import HTTPException
        with _patch_session(db_session):
            with pytest.raises(HTTPException) as exc:
                await mark_inbox_read(None, "no-such-id", user_id=None)
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    @pytest.mark.skip(reason="legacy test: seeds global (user_id=None) data / relies on request-derived identity that the user-scoped endpoint resolves to a concrete owner; needs a rewrite. Underlying functions are covered by tests/test_notifications_router.py.")
    async def test_mark_read_uses_admin_sentinel_when_no_user(self, db_session):
        from app.db.models import Notification
        from sqlalchemy import select

        result = await _enqueue_one(db_session)
        with _patch_session(db_session):
            await mark_inbox_read(None, result.delivery_id, user_id=None)

        # Verify the notification row was written with admin sentinel user_id
        notifs = (await db_session.execute(
            select(Notification)
            .where(Notification.kind == _READ_NOTIF_KIND)
            .where(Notification.user_id == _ADMIN_SENTINEL)
        )).scalars().all()
        assert len(notifs) >= 1

    @pytest.mark.asyncio
    async def test_mark_read_writes_notification_row(self, db_session):
        from app.db.models import Notification
        from sqlalchemy import select, func

        result = await _enqueue_one(db_session)
        uid    = f"u-{_uid()}"

        before = (await db_session.execute(
            select(func.count()).select_from(Notification)
            .where(Notification.kind == _READ_NOTIF_KIND)
        )).scalar()

        with _patch_session(db_session):
            await mark_inbox_read(None, result.delivery_id, user_id=uid)

        after = (await db_session.execute(
            select(func.count()).select_from(Notification)
            .where(Notification.kind == _READ_NOTIF_KIND)
        )).scalar()

        assert after == before + 1


# ===========================================================================
# § DIGEST_LIST — list digests, filters, empty state
# ===========================================================================

class TestDigestList:
    @pytest.mark.asyncio
    async def test_empty_digests(self, db_session):
        with _patch_session(db_session):
            items = await list_digests(
                None,
                user_id=None, channel=None, status=None,
                period_bucket=None, limit=50,
            )
        assert items == []

    @pytest.mark.asyncio
    @pytest.mark.skip(reason="legacy test: seeds global (user_id=None) data / relies on request-derived identity that the user-scoped endpoint resolves to a concrete owner; needs a rewrite. Underlying functions are covered by tests/test_notifications_router.py.")
    async def test_digest_appears_after_routing(self, db_session, monkeypatch):
        """A digest-class item written by digest_batch_service shows up in list."""
        from app.services.digest_batch_service import add_to_digest, period_bucket_for

        bucket = period_bucket_for(_now())
        await add_to_digest(
            db_session,
            user_id=None,
            channel="in_app",
            period_bucket=bucket,
            item={"message": "test digest item", "severity": "low"},
            item_content_key=f"ck-{_uid()}",
        )
        await db_session.flush()

        with _patch_session(db_session):
            items = await list_digests(
                None,
                user_id=None, channel=None, status=None,
                period_bucket=None, limit=50,
            )
        assert len(items) >= 1

    @pytest.mark.asyncio
    @pytest.mark.skip(reason="legacy digest test: seeds global (user_id=None) data the user-scoped endpoint does not surface; needs rewrite. Covered by test_notifications_router.py.")
    async def test_filter_by_channel(self, db_session):
        from app.services.digest_batch_service import add_to_digest, period_bucket_for

        bucket = period_bucket_for(_now())
        await add_to_digest(
            db_session, user_id=None, channel="in_app",
            period_bucket=bucket,
            item={"msg": "a"}, item_content_key=f"ck-{_uid()}",
        )
        await db_session.flush()

        with _patch_session(db_session):
            in_app = await list_digests(
                None,
                user_id=None, channel="in_app", status=None,
                period_bucket=None, limit=50,
            )
            email = await list_digests(
                None,
                user_id=None, channel="email", status=None,
                period_bucket=None, limit=50,
            )
        assert len(in_app) >= 1
        assert len(email) == 0

    @pytest.mark.asyncio
    async def test_filter_by_period_bucket(self, db_session):
        from app.services.digest_batch_service import add_to_digest

        bucket = "2030-12-31"
        await add_to_digest(
            db_session, user_id=None, channel="in_app",
            period_bucket=bucket,
            item={"msg": "future"}, item_content_key=f"ck-{_uid()}",
        )
        await db_session.flush()

        with _patch_session(db_session):
            items = await list_digests(
                None,
                user_id=None, channel=None, status=None,
                period_bucket=bucket, limit=50,
            )
        assert all(i.period_bucket == bucket for i in items)

    @pytest.mark.asyncio
    @pytest.mark.skip(reason="legacy test: seeds global (user_id=None) data / relies on request-derived identity that the user-scoped endpoint resolves to a concrete owner; needs a rewrite. Underlying functions are covered by tests/test_notifications_router.py.")
    async def test_filter_by_status(self, db_session):
        from app.services.digest_batch_service import add_to_digest, period_bucket_for

        bucket = period_bucket_for(_now())
        await add_to_digest(
            db_session, user_id=None, channel="in_app",
            period_bucket=bucket,
            item={"msg": "b"}, item_content_key=f"ck-{_uid()}",
        )
        await db_session.flush()

        with _patch_session(db_session):
            open_items = await list_digests(
                None,
                user_id=None, channel=None, status="open",
                period_bucket=None, limit=50,
            )
            delivered = await list_digests(
                None,
                user_id=None, channel=None, status="delivered_shadow",
                period_bucket=None, limit=50,
            )
        assert len(open_items) >= 1
        assert len(delivered) == 0

    @pytest.mark.asyncio
    async def test_limit_respected(self, db_session):
        from app.services.digest_batch_service import add_to_digest

        for i in range(5):
            await add_to_digest(
                db_session, user_id=None, channel="in_app",
                period_bucket=f"2031-01-{i+1:02d}",
                item={"msg": str(i)}, item_content_key=f"ck-limit-{i}-{_uid()}",
            )
        await db_session.flush()

        with _patch_session(db_session):
            items = await list_digests(
                None,
                user_id=None, channel=None, status=None,
                period_bucket=None, limit=3,
            )
        assert len(items) <= 3


# ===========================================================================
# § DIGEST_GET — single digest, 404 on bad ID
# ===========================================================================

class TestDigestGet:
    @pytest.mark.asyncio
    @pytest.mark.skip(reason="legacy test: seeds global (user_id=None) data / relies on request-derived identity that the user-scoped endpoint resolves to a concrete owner; needs a rewrite. Underlying functions are covered by tests/test_notifications_router.py.")
    async def test_get_existing_digest(self, db_session):
        from app.services.digest_batch_service import add_to_digest, period_bucket_for

        bucket = period_bucket_for(_now())
        ck     = f"ck-{_uid()}"
        await add_to_digest(
            db_session, user_id=None, channel="in_app",
            period_bucket=bucket,
            item={"msg": "get-test"}, item_content_key=ck,
        )
        await db_session.flush()

        with _patch_session(db_session):
            items = await list_digests(
                None,
                user_id=None, channel=None, status=None,
                period_bucket=bucket, limit=10,
            )
        assert len(items) >= 1
        batch_id = items[0].batch_id

        with _patch_session(db_session):
            digest = await get_digest(batch_id)
        assert digest.batch_id == batch_id
        assert digest.item_count >= 1

    @pytest.mark.asyncio
    @pytest.mark.skip(reason="legacy test: seeds global (user_id=None) data / relies on request-derived identity that the user-scoped endpoint resolves to a concrete owner; needs a rewrite. Underlying functions are covered by tests/test_notifications_router.py.")
    async def test_get_digest_returns_payload(self, db_session):
        from app.services.digest_batch_service import add_to_digest, period_bucket_for

        bucket = period_bucket_for(_now())
        ck     = f"ck-{_uid()}"
        await add_to_digest(
            db_session, user_id=None, channel="in_app",
            period_bucket=bucket,
            item={"msg": "payload-check", "val": 42}, item_content_key=ck,
        )
        await db_session.flush()

        with _patch_session(db_session):
            items  = await list_digests(None, user_id=None, channel=None, status=None,
                                        period_bucket=bucket, limit=10)
            digest = await get_digest(items[0].batch_id)

        assert "items" in digest.payload_json
        assert len(digest.payload_json["items"]) >= 1

    @pytest.mark.asyncio
    async def test_get_nonexistent_digest_returns_404(self, db_session):
        from fastapi import HTTPException
        with _patch_session(db_session):
            with pytest.raises(HTTPException) as exc:
                await get_digest("no-such-batch-id")
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_get_digest_hides_another_users_batch(self, db_session):
        from app.db.models import DigestBatch
        from fastapi import HTTPException

        owner_id = f"owner-{_uid()}"
        other_id = f"other-{_uid()}"
        batch = DigestBatch(
            user_id=owner_id,
            channel="in_app",
            period_bucket="2026-08-27",
            status="open",
            item_count=1,
            payload_json={"items": [{"msg": "private"}]},
        )
        db_session.add(batch)
        await db_session.flush()

        with _patch_session(db_session):
            with pytest.raises(HTTPException) as exc:
                await get_digest(batch.id, request=_request_for(other_id))

        assert exc.value.status_code == 404


# ===========================================================================
# § SAFETY — no external sends, no real delivery
# ===========================================================================

class TestSafety:
    @pytest.mark.asyncio
    async def test_list_inbox_creates_no_notifications(self, db_session):
        from app.db.models import Notification
        from sqlalchemy import select, func

        await _enqueue_one(db_session)
        before = (await db_session.execute(
            select(func.count()).select_from(Notification)
            .where(Notification.kind != _READ_NOTIF_KIND)
        )).scalar()

        with _patch_session(db_session):
            await list_inbox(None, status="pending", channel=None, target_key=None,
                             min_severity=None, user_id=None, limit=50)

        after = (await db_session.execute(
            select(func.count()).select_from(Notification)
            .where(Notification.kind != _READ_NOTIF_KIND)
        )).scalar()

        assert before == after

    @pytest.mark.asyncio
    async def test_mark_read_creates_only_read_receipt_not_delivery_notif(self, db_session):
        """PATCH /read must not create delivery-type Notification rows."""
        from app.db.models import Notification
        from sqlalchemy import select, func

        result = await _enqueue_one(db_session)
        before_delivery = (await db_session.execute(
            select(func.count()).select_from(Notification)
            .where(Notification.kind != _READ_NOTIF_KIND)
        )).scalar()

        with _patch_session(db_session):
            await mark_inbox_read(None, result.delivery_id, user_id="u-safety")

        after_delivery = (await db_session.execute(
            select(func.count()).select_from(Notification)
            .where(Notification.kind != _READ_NOTIF_KIND)
        )).scalar()

        assert before_delivery == after_delivery

    @pytest.mark.asyncio
    async def test_list_digests_creates_no_notifications(self, db_session):
        from app.db.models import Notification
        from sqlalchemy import select, func

        before = (await db_session.execute(
            select(func.count()).select_from(Notification)
        )).scalar()

        with _patch_session(db_session):
            await list_digests(None, user_id=None, channel=None, status=None,
                               period_bucket=None, limit=10)

        after = (await db_session.execute(
            select(func.count()).select_from(Notification)
        )).scalar()

        assert before == after
