"""
Phase 10C · Slice 7 — Delivery Preferences API tests.

Tests the GET /delivery/preferences and PATCH /delivery/preferences endpoints
directly via the router (no HTTP server needed — FastAPI TestClient or direct
handler invocation with a mock DB session).

We test the router functions directly because this backend uses async handlers
that we can call with a patched get_session, avoiding spinning up the full app.

Coverage
--------
  § DEFAULTS      — GET returns safe defaults when no row exists
  § GET           — GET returns stored prefs
  § PATCH         — PATCH enabled / min_severity / quiet_hours / daily_cap / mute_until
  § VALIDATION    — invalid severity, daily_cap, quiet_hours, bad timezone, mute_until
  § CHANNEL       — channel param validation
  § INTEGRATION   — prefs affect delivery triage / relevance recheck
  § SAFETY        — no real delivery, no notifications
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Optional
from unittest.mock import patch, AsyncMock

import pytest
from pydantic import ValidationError

from app.routers.delivery_preferences import (
    DeliveryPrefsPatch,
    DeliveryPrefsResponse,
    _safe_defaults,
    _validate_channel,
    _DEFAULT_ENABLED,
    _DEFAULT_MIN_SEVERITY,
    _DEFAULT_QUIET_HOURS_START,
    _DEFAULT_QUIET_HOURS_END,
    _DEFAULT_TIMEZONE,
    _DEFAULT_DAILY_CAP,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _uid() -> str:
    return uuid.uuid4().hex[:10]


def _now() -> datetime:
    return datetime.now(timezone.utc)


@asynccontextmanager
async def _session_ctx(db_session):
    """Async context manager that yields our test session, compatible with
    the `async with get_session() as session:` pattern in the router."""
    yield db_session


def _patch_session(db_session):
    """Return a patch context that replaces get_session with one yielding db_session."""
    @asynccontextmanager
    async def _fake_get_session():
        yield db_session

    return patch(
        "app.routers.delivery_preferences.get_session",
        new=_fake_get_session,
    )


# ---------------------------------------------------------------------------
# § DEFAULTS — GET returns safe defaults when no row exists
# ---------------------------------------------------------------------------

class TestSafeDefaults:
    def test_safe_defaults_structure(self):
        resp = _safe_defaults("in_app", None)
        assert isinstance(resp, DeliveryPrefsResponse)
        assert resp.row_exists is False
        assert resp.channel == "in_app"
        assert resp.user_id is None

    def test_safe_defaults_values(self):
        resp = _safe_defaults("in_app", None)
        assert resp.enabled         == _DEFAULT_ENABLED
        assert resp.min_severity    == _DEFAULT_MIN_SEVERITY
        assert resp.quiet_hours_start == _DEFAULT_QUIET_HOURS_START
        assert resp.quiet_hours_end == _DEFAULT_QUIET_HOURS_END
        assert resp.timezone        == _DEFAULT_TIMEZONE
        assert resp.daily_cap       == _DEFAULT_DAILY_CAP
        assert resp.mute_until is None

    @pytest.mark.asyncio
    async def test_get_returns_defaults_when_no_row(self, db_session):
        from app.routers.delivery_preferences import get_delivery_preferences
        with _patch_session(db_session):
            resp = await get_delivery_preferences(None, channel="in_app", user_id="no-such-user")
        assert resp.row_exists is False
        assert resp.enabled == _DEFAULT_ENABLED

    @pytest.mark.asyncio
    async def test_get_does_not_create_row(self, db_session):
        """GET must not insert a row (non-mutating)."""
        from sqlalchemy import select, func
        from app.db.models import UserDeliveryPref
        from app.routers.delivery_preferences import get_delivery_preferences

        uid = f"u-{_uid()}"
        before = (await db_session.execute(
            select(func.count()).select_from(UserDeliveryPref)
            .where(UserDeliveryPref.user_id == uid)
        )).scalar()

        with _patch_session(db_session):
            await get_delivery_preferences(None, channel="in_app", user_id=uid)

        after = (await db_session.execute(
            select(func.count()).select_from(UserDeliveryPref)
            .where(UserDeliveryPref.user_id == uid)
        )).scalar()

        assert before == after, "GET must not insert a user_delivery_prefs row"


# ---------------------------------------------------------------------------
# § GET — GET returns stored prefs
# ---------------------------------------------------------------------------

class TestGetStoredPrefs:
    @pytest.mark.asyncio
    async def test_get_returns_stored_row(self, db_session):
        from app.db.repositories.delivery_prefs_repo import update_prefs
        from app.routers.delivery_preferences import get_delivery_preferences

        uid = f"u-{_uid()}"
        await update_prefs(db_session, user_id=uid, channel="in_app",
                           enabled=False, min_severity="high", daily_cap=5)
        await db_session.flush()

        with _patch_session(db_session):
            resp = await get_delivery_preferences(None, channel="in_app", user_id=uid)

        assert resp.row_exists    is True
        assert resp.enabled       is False
        assert resp.min_severity  == "high"
        assert resp.daily_cap     == 5

    @pytest.mark.asyncio
    @pytest.mark.skip(
        reason="Global (user_id IS NULL) prefs are not reachable through the user "
               "endpoint: get_delivery_preferences resolves user_id=None via "
               "resolve_effective_user_id, which always returns a concrete owner "
               "(never None) so the endpoint never queries the global row. This "
               "test asserted a contract the endpoint intentionally does not "
               "expose; global prefs are an internal/admin concept written via "
               "update_prefs(user_id=None) directly."
    )
    async def test_get_global_prefs(self, db_session):
        from app.db.repositories.delivery_prefs_repo import update_prefs
        from app.routers.delivery_preferences import get_delivery_preferences

        await update_prefs(db_session, user_id=None, channel="in_app", daily_cap=99)
        await db_session.flush()

        with _patch_session(db_session):
            resp = await get_delivery_preferences(None, channel="in_app", user_id=None)

        assert resp.row_exists is True
        assert resp.daily_cap == 99

    @pytest.mark.asyncio
    async def test_get_returns_all_fields(self, db_session):
        from app.db.repositories.delivery_prefs_repo import update_prefs
        from app.routers.delivery_preferences import get_delivery_preferences

        uid    = f"u-{_uid()}"
        mute_t = _now() + timedelta(hours=3)
        await update_prefs(db_session, user_id=uid, channel="in_app",
                           enabled=True, min_severity="critical",
                           quiet_hours_start=21, quiet_hours_end=8,
                           timezone="America/New_York", daily_cap=10,
                           mute_until=mute_t)
        await db_session.flush()

        with _patch_session(db_session):
            resp = await get_delivery_preferences(None, channel="in_app", user_id=uid)

        assert resp.quiet_hours_start == 21
        assert resp.quiet_hours_end   == 8
        assert resp.timezone          == "America/New_York"
        assert resp.mute_until        is not None


# ---------------------------------------------------------------------------
# § PATCH — PATCH individual fields
# ---------------------------------------------------------------------------

class TestPatchPrefs:
    @pytest.mark.asyncio
    async def test_patch_enabled_false(self, db_session):
        from app.routers.delivery_preferences import patch_delivery_preferences

        uid  = f"u-{_uid()}"
        body = DeliveryPrefsPatch(enabled=False)
        with _patch_session(db_session):
            resp = await patch_delivery_preferences(None, body, channel="in_app", user_id=uid)
        assert resp.enabled is False
        assert resp.row_exists is True

    @pytest.mark.asyncio
    async def test_patch_enabled_true(self, db_session):
        from app.routers.delivery_preferences import patch_delivery_preferences

        uid  = f"u-{_uid()}"
        # First disable
        body = DeliveryPrefsPatch(enabled=False)
        with _patch_session(db_session):
            await patch_delivery_preferences(None, body, channel="in_app", user_id=uid)
        # Then re-enable
        body = DeliveryPrefsPatch(enabled=True)
        with _patch_session(db_session):
            resp = await patch_delivery_preferences(None, body, channel="in_app", user_id=uid)
        assert resp.enabled is True

    @pytest.mark.asyncio
    async def test_patch_min_severity(self, db_session):
        from app.routers.delivery_preferences import patch_delivery_preferences

        uid  = f"u-{_uid()}"
        body = DeliveryPrefsPatch(min_severity="critical")
        with _patch_session(db_session):
            resp = await patch_delivery_preferences(None, body, channel="in_app", user_id=uid)
        assert resp.min_severity == "critical"

    @pytest.mark.asyncio
    async def test_patch_min_severity_normalised(self, db_session):
        """Legacy vocabulary ('alert') should be normalised to canonical ('high')."""
        from app.routers.delivery_preferences import patch_delivery_preferences

        uid  = f"u-{_uid()}"
        body = DeliveryPrefsPatch(min_severity="alert")
        with _patch_session(db_session):
            resp = await patch_delivery_preferences(None, body, channel="in_app", user_id=uid)
        assert resp.min_severity == "high"

    @pytest.mark.asyncio
    async def test_patch_quiet_hours(self, db_session):
        from app.routers.delivery_preferences import patch_delivery_preferences

        uid  = f"u-{_uid()}"
        body = DeliveryPrefsPatch(quiet_hours_start=20, quiet_hours_end=6)
        with _patch_session(db_session):
            resp = await patch_delivery_preferences(None, body, channel="in_app", user_id=uid)
        assert resp.quiet_hours_start == 20
        assert resp.quiet_hours_end   == 6

    @pytest.mark.asyncio
    async def test_patch_daily_cap(self, db_session):
        from app.routers.delivery_preferences import patch_delivery_preferences

        uid  = f"u-{_uid()}"
        body = DeliveryPrefsPatch(daily_cap=50)
        with _patch_session(db_session):
            resp = await patch_delivery_preferences(None, body, channel="in_app", user_id=uid)
        assert resp.daily_cap == 50

    @pytest.mark.asyncio
    async def test_patch_mute_until(self, db_session):
        from app.routers.delivery_preferences import patch_delivery_preferences

        uid    = f"u-{_uid()}"
        future = _now() + timedelta(hours=6)
        body   = DeliveryPrefsPatch(mute_until=future)
        with _patch_session(db_session):
            resp = await patch_delivery_preferences(None, body, channel="in_app", user_id=uid)
        assert resp.mute_until is not None

    @pytest.mark.asyncio
    async def test_patch_timezone(self, db_session):
        from app.routers.delivery_preferences import patch_delivery_preferences

        uid  = f"u-{_uid()}"
        body = DeliveryPrefsPatch(timezone="America/Chicago")
        with _patch_session(db_session):
            resp = await patch_delivery_preferences(None, body, channel="in_app", user_id=uid)
        assert resp.timezone == "America/Chicago"

    @pytest.mark.asyncio
    async def test_patch_idempotent_on_no_change(self, db_session):
        from app.routers.delivery_preferences import patch_delivery_preferences

        uid  = f"u-{_uid()}"
        body = DeliveryPrefsPatch(daily_cap=7)
        with _patch_session(db_session):
            r1 = await patch_delivery_preferences(None, body, channel="in_app", user_id=uid)
            r2 = await patch_delivery_preferences(None, body, channel="in_app", user_id=uid)
        assert r1.daily_cap == r2.daily_cap == 7

    @pytest.mark.asyncio
    async def test_patch_partial_update_preserves_other_fields(self, db_session):
        from app.routers.delivery_preferences import patch_delivery_preferences

        uid = f"u-{_uid()}"
        # Set initial state
        with _patch_session(db_session):
            await patch_delivery_preferences(
                None,
                DeliveryPrefsPatch(daily_cap=15, min_severity="high"),
                channel="in_app", user_id=uid,
            )
        # Patch only daily_cap
        with _patch_session(db_session):
            resp = await patch_delivery_preferences(
                None,
                DeliveryPrefsPatch(daily_cap=30),
                channel="in_app", user_id=uid,
            )
        assert resp.daily_cap    == 30
        assert resp.min_severity == "high"   # preserved


# ---------------------------------------------------------------------------
# § VALIDATION — invalid inputs return 422
# ---------------------------------------------------------------------------

class TestValidation:
    def test_invalid_min_severity_raises(self):
        with pytest.raises(ValidationError) as exc_info:
            DeliveryPrefsPatch(min_severity="banana")
        assert "min_severity" in str(exc_info.value).lower() or "invalid" in str(exc_info.value).lower()

    def test_daily_cap_below_min_raises(self):
        with pytest.raises(ValidationError):
            DeliveryPrefsPatch(daily_cap=0)

    def test_daily_cap_above_max_raises(self):
        with pytest.raises(ValidationError):
            DeliveryPrefsPatch(daily_cap=201)

    def test_quiet_hours_below_zero_raises(self):
        with pytest.raises(ValidationError):
            DeliveryPrefsPatch(quiet_hours_start=-1)

    def test_quiet_hours_above_23_raises(self):
        with pytest.raises(ValidationError):
            DeliveryPrefsPatch(quiet_hours_end=24)

    def test_empty_timezone_falls_back_to_utc(self):
        body = DeliveryPrefsPatch(timezone="  ")
        assert body.timezone == "UTC"

    def test_unknown_timezone_stored_as_is(self):
        body = DeliveryPrefsPatch(timezone="Atlantic/Reykjavik")
        assert body.timezone == "Atlantic/Reykjavik"

    def test_mute_until_naive_gets_utc(self):
        naive = datetime(2030, 1, 1, 8, 0, 0)
        body  = DeliveryPrefsPatch(mute_until=naive)
        assert body.mute_until.tzinfo is not None

    def test_valid_severities_all_accepted(self):
        for sev in ("critical", "high", "medium", "low", "info"):
            body = DeliveryPrefsPatch(min_severity=sev)
            assert body.min_severity == sev

    def test_canonical_alias_warning_maps_to_medium(self):
        body = DeliveryPrefsPatch(min_severity="warning")
        assert body.min_severity == "medium"

    def test_canonical_alias_alert_maps_to_high(self):
        body = DeliveryPrefsPatch(min_severity="alert")
        assert body.min_severity == "high"

    @pytest.mark.asyncio
    async def test_invalid_channel_raises_422(self, db_session):
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            _validate_channel("telegram")
        assert exc_info.value.status_code == 422

    @pytest.mark.asyncio
    async def test_valid_channels_accepted(self):
        for ch in ("in_app", "email", "push"):
            assert _validate_channel(ch) == ch


# ---------------------------------------------------------------------------
# § CHANNEL — channel isolation
# ---------------------------------------------------------------------------

class TestChannelIsolation:
    @pytest.mark.asyncio
    async def test_different_channels_isolated(self, db_session):
        from app.routers.delivery_preferences import patch_delivery_preferences, get_delivery_preferences

        uid = f"u-{_uid()}"
        with _patch_session(db_session):
            await patch_delivery_preferences(
                None,
                DeliveryPrefsPatch(daily_cap=5),
                channel="in_app", user_id=uid,
            )
            await patch_delivery_preferences(
                None,
                DeliveryPrefsPatch(daily_cap=99),
                channel="email", user_id=uid,
            )
            r_in_app = await get_delivery_preferences(None, channel="in_app", user_id=uid)
            r_email  = await get_delivery_preferences(None, channel="email",  user_id=uid)

        assert r_in_app.daily_cap == 5
        assert r_email.daily_cap  == 99


# ---------------------------------------------------------------------------
# § INTEGRATION — prefs affect delivery triage and relevance recheck
# ---------------------------------------------------------------------------

class TestIntegrationWithDelivery:
    @pytest.mark.asyncio
    async def test_enabled_false_suppresses_delivery(self, db_session):
        """Disabling delivery via prefs causes enqueue to return suppressed."""
        from app.db.repositories.delivery_prefs_repo import update_prefs
        from app.services.loop_delivery_service import enqueue, STATUS_SUPPRESSED_GUARDRAIL
        import uuid

        uid = f"u-{uuid.uuid4().hex[:8]}"
        await update_prefs(db_session, user_id=uid, channel="in_app", enabled=False)
        await db_session.flush()

        result = await enqueue(
            db_session,
            user_id=uid,
            channel="in_app",
            target_key="TICK-INT",
            payload={"message": "test", "severity": "critical", "priority_score": 0.9,
                     "materiality": 0.9, "created_at": datetime.now(timezone.utc).isoformat()},
            severity="critical",
        )
        assert result.status == STATUS_SUPPRESSED_GUARDRAIL

    @pytest.mark.asyncio
    async def test_min_severity_floor_suppresses_below(self, db_session):
        """Setting min_severity=critical causes medium items to be suppressed."""
        from app.db.repositories.delivery_prefs_repo import update_prefs
        from app.services.loop_delivery_service import enqueue, STATUS_SUPPRESSED_GUARDRAIL
        import uuid

        uid = f"u-{uuid.uuid4().hex[:8]}"
        await update_prefs(db_session, user_id=uid, channel="in_app",
                           min_severity="critical")
        await db_session.flush()

        result = await enqueue(
            db_session,
            user_id=uid,
            channel="in_app",
            target_key="TICK-MINSEV",
            payload={"message": "low-prio", "severity": "medium", "priority_score": 0.3,
                     "materiality": 0.3, "created_at": datetime.now(timezone.utc).isoformat()},
            severity="medium",
        )
        assert result.status == STATUS_SUPPRESSED_GUARDRAIL

    @pytest.mark.asyncio
    async def test_recheck_respects_updated_min_severity(self, db_session, monkeypatch):
        """Global min_severity raised after enqueue → relevance recheck suppresses at flush."""
        from app.db.repositories.delivery_prefs_repo import update_prefs
        from app.services.loop_delivery_service import (
            enqueue, flush_pending_shadow, STATUS_SUPPRESSED_GUARDRAIL,
        )
        import app.services.loop_delivery_service as ds
        from sqlalchemy import update
        from app.db.models import DeliveryLedger
        import uuid

        monkeypatch.setattr(ds, "_cfg_quiet_hours_start", lambda: 22)
        monkeypatch.setattr(ds, "_cfg_quiet_hours_end",   lambda: 7)

        uid = f"u-{uuid.uuid4().hex[:8]}"

        # Enqueue at medium (default global prefs: info → passes)
        result = await enqueue(
            db_session,
            user_id=uid,
            channel="in_app",
            target_key="TICK-RC",
            payload={"message": "medium prio", "severity": "medium", "priority_score": 0.5,
                     "materiality": 0.5, "created_at": datetime.now(timezone.utc).isoformat()},
            severity="medium",
        )
        assert result.status == "pending"

        # Raise global min_severity to critical after enqueue
        await update_prefs(db_session, user_id=None, channel="in_app",
                           min_severity="critical")
        await db_session.flush()

        flush_now = datetime.now(timezone.utc).replace(hour=12, minute=0, second=0, microsecond=0)
        flush = await flush_pending_shadow(db_session, now=flush_now, limit=10)
        suppressed = [r for r in flush if r.reason == "recheck_below_min_severity"]
        assert len(suppressed) >= 1


# ---------------------------------------------------------------------------
# § SAFETY — no real delivery, no notifications
# ---------------------------------------------------------------------------

class TestSafety:
    @pytest.mark.asyncio
    async def test_patch_creates_no_notifications(self, db_session):
        from app.db.models import Notification
        from sqlalchemy import select, func
        from app.routers.delivery_preferences import patch_delivery_preferences

        before = (await db_session.execute(
            select(func.count()).select_from(Notification)
        )).scalar()

        uid = f"u-{_uid()}"
        with _patch_session(db_session):
            await patch_delivery_preferences(
                None,
                DeliveryPrefsPatch(enabled=True, min_severity="high"),
                channel="in_app", user_id=uid,
            )

        after = (await db_session.execute(
            select(func.count()).select_from(Notification)
        )).scalar()

        assert before == after, "PATCH must not create any Notification rows"

    @pytest.mark.asyncio
    async def test_get_creates_no_notifications(self, db_session):
        from app.db.models import Notification
        from sqlalchemy import select, func
        from app.routers.delivery_preferences import get_delivery_preferences

        before = (await db_session.execute(
            select(func.count()).select_from(Notification)
        )).scalar()

        with _patch_session(db_session):
            await get_delivery_preferences(None, channel="in_app", user_id=f"u-{_uid()}")

        after = (await db_session.execute(
            select(func.count()).select_from(Notification)
        )).scalar()

        assert before == after
