"""Integration tests for the notifications router (beta milestone 4).

Drives the real notification endpoint functions against the real persistence
layer (temp-file SQLite), exercising the full delegation chain:
notifications endpoint -> delivery_inbox / delivery_preferences ->
DeliveryLedger / Notification / UserDeliveryPref.

Seeds DeliveryLedger rows directly (the producer/scheduler that would create
them in production is orthogonal to the read/ack surface under test).

Runs on Python 3.9 (imports the routers module, not the full FastAPI app build).
"""

from __future__ import annotations

import asyncio
import os
import tempfile

import pytest

from app.routers import notifications as nr
from app.routers.delivery_preferences import DeliveryPrefsPatch


async def _with_db(fn):
    from app.db.connection import init_db, close_db
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        await init_db(f"sqlite+aiosqlite:///{path}")
        from conftest import create_test_schema
        await create_test_schema(f"sqlite+aiosqlite:///{path}")
        return await fn()
    finally:
        await close_db()
        try:
            os.unlink(path)
        except OSError:
            pass


def _run(fn):
    asyncio.run(_with_db(fn))


async def _seed_delivery(content_key: str, target_key: str = "NVDA",
                         severity: str = "high", rank: int = 4) -> str:
    """Insert one delivered_shadow DeliveryLedger row; return its id."""
    from app.db.connection import get_session
    from app.db.models import DeliveryLedger
    async with get_session() as db:
        row = DeliveryLedger(
            content_key=content_key,
            target_key=target_key,
            content_hash=f"hash-{content_key}",
            channel="in_app",
            status="delivered_shadow",
            canonical_severity=severity,
            severity_rank=rank,
        )
        db.add(row)
        await db.flush()
        return row.id


# ---------------------------------------------------------------------------
# Inbox list + unread count + mark read
# ---------------------------------------------------------------------------

def test_list_unread_mark_read_flow():
    async def scenario():
        did = await _seed_delivery("ck-1", "NVDA")

        # GET /notifications lists the seeded item.
        items = await nr.list_notifications(request=None)
        assert any(i["delivery_id"] == did for i in items)

        # unread count is 1 (nothing marked read yet).
        unread = await nr.unread_notifications(request=None)
        assert unread["count"] == 1
        assert any(i["delivery_id"] == did for i in unread["items"])

        # POST /notifications/read marks it.
        res = await nr.mark_notifications_read(nr.MarkReadRequest(delivery_ids=[did]), request=None)
        assert res["marked"] == 1
        assert res["delivery_ids"] == [did]

        # unread count drops to 0.
        unread2 = await nr.unread_notifications(request=None)
        assert unread2["count"] == 0

    _run(scenario)


def test_mark_read_idempotent():
    async def scenario():
        did = await _seed_delivery("ck-2", "MSFT")
        r1 = await nr.mark_notifications_read(nr.MarkReadRequest(delivery_id=did), request=None)
        r2 = await nr.mark_notifications_read(nr.MarkReadRequest(delivery_id=did), request=None)
        assert r1["marked"] == 1 and r2["marked"] == 1   # second call still succeeds, no error
        unread = await nr.unread_notifications(request=None)
        assert unread["count"] == 0
    _run(scenario)


def test_mark_read_unknown_id_reported_missing():
    async def scenario():
        res = await nr.mark_notifications_read(nr.MarkReadRequest(delivery_ids=["does-not-exist"]), request=None)
        assert res["marked"] == 0
        assert res["missing"] == ["does-not-exist"]
    _run(scenario)


def test_mark_read_requires_an_id():
    async def scenario():
        with pytest.raises(Exception):   # HTTPException 400
            await nr.mark_notifications_read(nr.MarkReadRequest(), request=None)
    _run(scenario)


def test_empty_inbox_returns_empty():
    async def scenario():
        items = await nr.list_notifications(request=None)
        assert items == []
        unread = await nr.unread_notifications(request=None)
        assert unread == {"count": 0, "items": []}
    _run(scenario)


# ---------------------------------------------------------------------------
# Preferences read + update
# ---------------------------------------------------------------------------

def test_preferences_get_defaults_then_patch():
    async def scenario():
        # GET returns safe defaults without creating a row.
        prefs = await nr.get_notification_preferences(request=None, channel="in_app")
        assert prefs["channel"] == "in_app"

        # PATCH persists a change.
        patched = await nr.patch_notification_preferences(
            DeliveryPrefsPatch(daily_cap=5, min_severity="high"),
            request=None, channel="in_app",
        )
        assert patched["daily_cap"] == 5

        # GET now reflects the persisted value.
        prefs2 = await nr.get_notification_preferences(request=None, channel="in_app")
        assert prefs2["daily_cap"] == 5
    _run(scenario)


def test_preference_update_is_idempotent():
    async def scenario():
        p1 = await nr.patch_notification_preferences(
            DeliveryPrefsPatch(daily_cap=7), request=None, channel="in_app")
        p2 = await nr.patch_notification_preferences(
            DeliveryPrefsPatch(daily_cap=7), request=None, channel="in_app")
        assert p1["daily_cap"] == 7 and p2["daily_cap"] == 7
    _run(scenario)


# ---------------------------------------------------------------------------
# Persistence-disabled degradation
# ---------------------------------------------------------------------------

def test_persistence_disabled_degradation():
    async def scenario():
        from app.db.connection import close_db
        await close_db()   # ensure disabled
        assert await nr.list_notifications(request=None) == []
        assert await nr.unread_notifications(request=None) == {"count": 0, "items": []}
        res = await nr.mark_notifications_read(nr.MarkReadRequest(delivery_id="x"), request=None)
        assert res == {"marked": 0, "delivery_ids": [], "persistence": "disabled"}
        # preferences still returns safe defaults (never raises)
        prefs = await nr.get_notification_preferences(request=None, channel="in_app")
        assert prefs["channel"] == "in_app"
    asyncio.run(scenario())
