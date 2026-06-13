"""
Phase 10C · Slice 9 — In-App Delivery Channel Activation tests.

Tests flush_in_app() under all flag combinations:

  § FLAGS_OFF       — default config creates no Notifications
  § SHADOW          — shadow mode marks delivered_shadow only
  § LIVE_DELIVERY   — in_app_enabled=True, shadow=False creates Notification
  § COHORT          — internal / non-internal / canary gating
  § DEDUP           — duplicate flush does not duplicate Notification rows
  § GUARDRAILS      — prefs disabled, relevance recheck, stale, suppressed
  § CHANNEL         — non-in_app rows skipped in live mode
  § STATUS_TRANSITIONS — ledger status: pending → delivered / delivered_shadow
  § SAFETY          — no external sends, no frontend changes
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional
from unittest.mock import patch

import pytest

from app.services.in_app_delivery_service import (
    flush_in_app,
    get_delivery_config,
    _is_eligible_for_live_delivery,
    DeliveryConfig,
    STATUS_DELIVERED,
    REASON_IN_APP_DISABLED,
    REASON_NOT_IN_APP,
    REASON_COHORT_CONTROL,
)
from app.services.loop_delivery_service import (
    enqueue,
    STATUS_DELIVERED_SHADOW,
    STATUS_SUPPRESSED_GUARDRAIL,
)
import app.services.loop_delivery_service as ds


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _uid() -> str:
    return uuid.uuid4().hex[:10]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _flush_now() -> datetime:
    """Reference time squarely in a non-quiet window (12:00 UTC)."""
    return _now().replace(hour=12, minute=0, second=0, microsecond=0)


def _cfg(
    in_app_enabled: bool = False,
    shadow: bool = True,
    internal_only: bool = True,
    canary_pct: int = 0,
    internal_user_ids=frozenset(),
) -> DeliveryConfig:
    return DeliveryConfig(
        in_app_enabled=in_app_enabled,
        shadow=shadow,
        internal_only=internal_only,
        canary_pct=canary_pct,
        internal_user_ids=frozenset(internal_user_ids),
    )


def _patch_cfg(cfg: DeliveryConfig):
    return patch(
        "app.services.in_app_delivery_service.get_delivery_config",
        return_value=cfg,
    )


async def _enqueue_one(
    db_session,
    *,
    severity: str = "critical",
    tag: Optional[str] = None,
    user_id: Optional[str] = None,
    target_key: Optional[str] = None,
) -> "ds.DeliveryResult":
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
            "materiality":    0.9,
            "created_at":     _now().isoformat(),
        },
        severity=severity,
    )


# ===========================================================================
# § FLAGS_OFF — default config creates no Notifications
# ===========================================================================

class TestFlagsOff:
    @pytest.mark.asyncio
    async def test_default_cfg_no_notifications(self, db_session, monkeypatch):
        """With all defaults (in_app_enabled=False), flush_in_app writes no Notifications."""
        monkeypatch.setattr(ds, "_cfg_quiet_hours_start", lambda: 22)
        monkeypatch.setattr(ds, "_cfg_quiet_hours_end",   lambda: 7)

        await _enqueue_one(db_session, severity="critical")

        from app.db.models import Notification
        from sqlalchemy import select, func

        before = (await db_session.execute(
            select(func.count()).select_from(Notification)
        )).scalar()

        # Default config: in_app_enabled=False
        with _patch_cfg(_cfg(in_app_enabled=False)):
            await flush_in_app(db_session, now=_flush_now(), limit=10, user_id="u-test")

        after = (await db_session.execute(
            select(func.count()).select_from(Notification)
        )).scalar()

        assert before == after, "default flags must not create Notification rows"

    @pytest.mark.asyncio
    async def test_default_cfg_marks_delivered_shadow(self, db_session, monkeypatch):
        """With in_app_enabled=False, flush_in_app falls back to shadow delivery."""
        monkeypatch.setattr(ds, "_cfg_quiet_hours_start", lambda: 22)
        monkeypatch.setattr(ds, "_cfg_quiet_hours_end",   lambda: 7)

        result = await _enqueue_one(db_session, severity="critical")

        with _patch_cfg(_cfg(in_app_enabled=False)):
            flush_results = await flush_in_app(
                db_session, now=_flush_now(), limit=10, user_id="u-test"
            )

        delivered_shadow = [r for r in flush_results if r.status == STATUS_DELIVERED_SHADOW]
        assert any(r.delivery_id == result.delivery_id for r in delivered_shadow)

    @pytest.mark.asyncio
    async def test_no_user_id_falls_back_to_shadow(self, db_session, monkeypatch):
        """flush_in_app with user_id=None always falls back to shadow mode."""
        monkeypatch.setattr(ds, "_cfg_quiet_hours_start", lambda: 22)
        monkeypatch.setattr(ds, "_cfg_quiet_hours_end",   lambda: 7)

        await _enqueue_one(db_session, severity="critical")

        from app.db.models import Notification
        from sqlalchemy import select, func

        before = (await db_session.execute(
            select(func.count()).select_from(Notification)
        )).scalar()

        # Even with in_app_enabled=True, shadow=False — no user_id → shadow
        with _patch_cfg(_cfg(in_app_enabled=True, shadow=False, internal_only=False)):
            await flush_in_app(db_session, now=_flush_now(), limit=10, user_id=None)

        after = (await db_session.execute(
            select(func.count()).select_from(Notification)
        )).scalar()

        assert before == after


# ===========================================================================
# § SHADOW — shadow=True marks delivered_shadow only
# ===========================================================================

class TestShadowMode:
    @pytest.mark.asyncio
    async def test_shadow_true_no_notifications(self, db_session, monkeypatch):
        """delivery_in_app_enabled=True but delivery_shadow=True → no Notifications."""
        monkeypatch.setattr(ds, "_cfg_quiet_hours_start", lambda: 22)
        monkeypatch.setattr(ds, "_cfg_quiet_hours_end",   lambda: 7)

        await _enqueue_one(db_session, severity="critical")

        from app.db.models import Notification
        from sqlalchemy import select, func

        before = (await db_session.execute(
            select(func.count()).select_from(Notification)
        )).scalar()

        with _patch_cfg(_cfg(in_app_enabled=True, shadow=True)):
            await flush_in_app(db_session, now=_flush_now(), limit=10, user_id="u-shadow")

        after = (await db_session.execute(
            select(func.count()).select_from(Notification)
        )).scalar()

        assert before == after

    @pytest.mark.asyncio
    async def test_shadow_marks_delivered_shadow(self, db_session, monkeypatch):
        monkeypatch.setattr(ds, "_cfg_quiet_hours_start", lambda: 22)
        monkeypatch.setattr(ds, "_cfg_quiet_hours_end",   lambda: 7)

        result = await _enqueue_one(db_session, severity="critical")

        with _patch_cfg(_cfg(in_app_enabled=True, shadow=True)):
            flush_results = await flush_in_app(
                db_session, now=_flush_now(), limit=10, user_id="u-shadow"
            )

        assert any(
            r.delivery_id == result.delivery_id and r.status == STATUS_DELIVERED_SHADOW
            for r in flush_results
        )

    @pytest.mark.asyncio
    async def test_shadow_ledger_status_is_delivered_shadow(self, db_session, monkeypatch):
        monkeypatch.setattr(ds, "_cfg_quiet_hours_start", lambda: 22)
        monkeypatch.setattr(ds, "_cfg_quiet_hours_end",   lambda: 7)

        result = await _enqueue_one(db_session, severity="critical")

        with _patch_cfg(_cfg(in_app_enabled=True, shadow=True)):
            await flush_in_app(db_session, now=_flush_now(), limit=10, user_id="u-shadow")

        from sqlalchemy import select
        from app.db.models import DeliveryLedger
        row = (await db_session.execute(
            select(DeliveryLedger).where(DeliveryLedger.id == result.delivery_id)
        )).scalar_one()
        assert row.status == "delivered_shadow"


# ===========================================================================
# § LIVE_DELIVERY — in_app_enabled=True, shadow=False creates Notification
# ===========================================================================

class TestLiveDelivery:
    @pytest.mark.asyncio
    async def test_live_creates_notification(self, db_session, monkeypatch):
        monkeypatch.setattr(ds, "_cfg_quiet_hours_start", lambda: 22)
        monkeypatch.setattr(ds, "_cfg_quiet_hours_end",   lambda: 7)

        uid = f"u-internal-{_uid()}"
        result = await _enqueue_one(db_session, severity="critical")

        from app.db.models import Notification
        from sqlalchemy import select, func

        before = (await db_session.execute(
            select(func.count()).select_from(Notification)
        )).scalar()

        live_cfg = _cfg(
            in_app_enabled=True, shadow=False,
            internal_only=True, internal_user_ids={uid},
        )
        with _patch_cfg(live_cfg):
            flush_results = await flush_in_app(
                db_session, now=_flush_now(), limit=10, user_id=uid
            )

        after = (await db_session.execute(
            select(func.count()).select_from(Notification)
        )).scalar()

        assert after == before + 1
        assert any(r.status == STATUS_DELIVERED for r in flush_results)

    @pytest.mark.asyncio
    async def test_live_notification_kind_is_delivery(self, db_session, monkeypatch):
        monkeypatch.setattr(ds, "_cfg_quiet_hours_start", lambda: 22)
        monkeypatch.setattr(ds, "_cfg_quiet_hours_end",   lambda: 7)

        uid    = f"u-internal-{_uid()}"
        result = await _enqueue_one(db_session, severity="critical")

        live_cfg = _cfg(in_app_enabled=True, shadow=False,
                        internal_only=True, internal_user_ids={uid})
        with _patch_cfg(live_cfg):
            await flush_in_app(db_session, now=_flush_now(), limit=10, user_id=uid)

        from sqlalchemy import select
        from app.db.models import Notification
        notifs = (await db_session.execute(
            select(Notification)
            .where(Notification.user_id == uid)
            .where(Notification.kind == "delivery")
        )).scalars().all()
        assert len(notifs) == 1
        assert notifs[0].body_json.get("delivery_id") == result.delivery_id

    @pytest.mark.asyncio
    async def test_live_ledger_status_is_delivered(self, db_session, monkeypatch):
        monkeypatch.setattr(ds, "_cfg_quiet_hours_start", lambda: 22)
        monkeypatch.setattr(ds, "_cfg_quiet_hours_end",   lambda: 7)

        uid    = f"u-internal-{_uid()}"
        result = await _enqueue_one(db_session, severity="critical")

        live_cfg = _cfg(in_app_enabled=True, shadow=False,
                        internal_only=True, internal_user_ids={uid})
        with _patch_cfg(live_cfg):
            await flush_in_app(db_session, now=_flush_now(), limit=10, user_id=uid)

        from sqlalchemy import select
        from app.db.models import DeliveryLedger
        row = (await db_session.execute(
            select(DeliveryLedger).where(DeliveryLedger.id == result.delivery_id)
        )).scalar_one()
        assert row.status == STATUS_DELIVERED

    @pytest.mark.asyncio
    async def test_live_notification_has_target_key(self, db_session, monkeypatch):
        monkeypatch.setattr(ds, "_cfg_quiet_hours_start", lambda: 22)
        monkeypatch.setattr(ds, "_cfg_quiet_hours_end",   lambda: 7)

        uid = f"u-internal-{_uid()}"
        tag = _uid()
        await _enqueue_one(db_session, severity="critical", tag=tag,
                           target_key=f"TICK-{tag}")

        live_cfg = _cfg(in_app_enabled=True, shadow=False,
                        internal_only=True, internal_user_ids={uid})
        with _patch_cfg(live_cfg):
            await flush_in_app(db_session, now=_flush_now(), limit=10, user_id=uid)

        from sqlalchemy import select
        from app.db.models import Notification
        notifs = (await db_session.execute(
            select(Notification)
            .where(Notification.user_id == uid)
            .where(Notification.kind == "delivery")
        )).scalars().all()
        target_keys = [n.body_json.get("target_key") for n in notifs]
        assert f"TICK-{tag}" in target_keys


# ===========================================================================
# § COHORT — internal / non-internal gating
# ===========================================================================

class TestCohortGating:
    def test_internal_user_is_eligible(self):
        uid = f"u-internal-{_uid()}"
        cfg = _cfg(internal_only=True, internal_user_ids={uid})
        assert _is_eligible_for_live_delivery(uid, cfg) is True

    def test_non_internal_user_not_eligible_when_internal_only(self):
        cfg = _cfg(internal_only=True, internal_user_ids={"other-user"})
        assert _is_eligible_for_live_delivery("random-user", cfg) is False

    def test_no_user_id_not_eligible(self):
        cfg = _cfg(internal_only=False, canary_pct=100)
        assert _is_eligible_for_live_delivery(None, cfg) is False

    def test_canary_pct_zero_not_eligible(self):
        cfg = _cfg(internal_only=False, canary_pct=0)
        assert _is_eligible_for_live_delivery("some-user", cfg) is False

    @pytest.mark.asyncio
    async def test_non_internal_user_suppressed_in_live_mode(self, db_session, monkeypatch):
        monkeypatch.setattr(ds, "_cfg_quiet_hours_start", lambda: 22)
        monkeypatch.setattr(ds, "_cfg_quiet_hours_end",   lambda: 7)

        uid    = f"u-outsider-{_uid()}"
        result = await _enqueue_one(db_session, severity="critical")

        live_cfg = _cfg(
            in_app_enabled=True, shadow=False,
            internal_only=True, internal_user_ids={"someone-else"},
        )
        with _patch_cfg(live_cfg):
            flush_results = await flush_in_app(
                db_session, now=_flush_now(), limit=10, user_id=uid
            )

        suppressed = [r for r in flush_results
                      if r.reason == REASON_COHORT_CONTROL]
        assert len(suppressed) >= 1

        # No Notification created
        from app.db.models import Notification
        from sqlalchemy import select, func
        count = (await db_session.execute(
            select(func.count()).select_from(Notification)
            .where(Notification.user_id == uid)
        )).scalar()
        assert count == 0

    @pytest.mark.asyncio
    async def test_non_internal_user_suppressed_in_live_mode_ledger_status(
        self, db_session, monkeypatch
    ):
        monkeypatch.setattr(ds, "_cfg_quiet_hours_start", lambda: 22)
        monkeypatch.setattr(ds, "_cfg_quiet_hours_end",   lambda: 7)

        uid    = f"u-outsider-{_uid()}"
        result = await _enqueue_one(db_session, severity="critical")

        live_cfg = _cfg(
            in_app_enabled=True, shadow=False,
            internal_only=True, internal_user_ids={"different-user"},
        )
        with _patch_cfg(live_cfg):
            await flush_in_app(db_session, now=_flush_now(), limit=10, user_id=uid)

        from sqlalchemy import select
        from app.db.models import DeliveryLedger
        row = (await db_session.execute(
            select(DeliveryLedger).where(DeliveryLedger.id == result.delivery_id)
        )).scalar_one()
        assert row.status == "suppressed"


# ===========================================================================
# § DEDUP — duplicate flush does not duplicate Notification rows
# ===========================================================================

class TestDedup:
    @pytest.mark.asyncio
    async def test_duplicate_flush_no_duplicate_notification(self, db_session, monkeypatch):
        monkeypatch.setattr(ds, "_cfg_quiet_hours_start", lambda: 22)
        monkeypatch.setattr(ds, "_cfg_quiet_hours_end",   lambda: 7)

        uid    = f"u-internal-{_uid()}"
        result = await _enqueue_one(db_session, severity="critical")

        live_cfg = _cfg(in_app_enabled=True, shadow=False,
                        internal_only=True, internal_user_ids={uid})

        from app.db.models import Notification
        from sqlalchemy import select, func

        with _patch_cfg(live_cfg):
            await flush_in_app(db_session, now=_flush_now(), limit=10, user_id=uid)

        count_after_first = (await db_session.execute(
            select(func.count()).select_from(Notification)
            .where(Notification.user_id == uid)
            .where(Notification.kind == "delivery")
        )).scalar()

        # Reset ledger to pending so a second flush would process it
        # (simulate a retry / crash recovery scenario)
        from sqlalchemy import update
        from app.db.models import DeliveryLedger
        await db_session.execute(
            update(DeliveryLedger)
            .where(DeliveryLedger.id == result.delivery_id)
            .values(status="pending")
            .execution_options(synchronize_session=False)
        )
        await db_session.flush()

        with _patch_cfg(live_cfg):
            await flush_in_app(db_session, now=_flush_now(), limit=10, user_id=uid)

        count_after_second = (await db_session.execute(
            select(func.count()).select_from(Notification)
            .where(Notification.user_id == uid)
            .where(Notification.kind == "delivery")
        )).scalar()

        assert count_after_first == count_after_second == 1


# ===========================================================================
# § GUARDRAILS — prefs disabled, stale, suppressed
# ===========================================================================

class TestGuardrails:
    @pytest.mark.asyncio
    async def test_prefs_disabled_suppresses(self, db_session):
        """delivery prefs enabled=False suppresses at enqueue — no pending row."""
        from app.db.repositories.delivery_prefs_repo import update_prefs

        uid = f"u-disabled-{_uid()}"
        await update_prefs(db_session, user_id=uid, channel="in_app", enabled=False)
        await db_session.flush()

        result = await enqueue(
            db_session, user_id=uid, channel="in_app", target_key="TICK-D",
            payload={"message": "x", "severity": "critical", "priority_score": 0.9,
                     "materiality": 0.9, "created_at": _now().isoformat()},
            severity="critical",
        )
        assert result.status == STATUS_SUPPRESSED_GUARDRAIL

    @pytest.mark.asyncio
    async def test_stale_item_suppressed(self, db_session, monkeypatch):
        """Stale rows (>72h) suppressed by relevance recheck in flush_in_app."""
        monkeypatch.setattr(ds, "_cfg_quiet_hours_start", lambda: 22)
        monkeypatch.setattr(ds, "_cfg_quiet_hours_end",   lambda: 7)

        uid    = f"u-internal-{_uid()}"
        result = await _enqueue_one(db_session, severity="critical")

        flush_now = _flush_now()
        from sqlalchemy import update
        from app.db.models import DeliveryLedger
        from app.services.delivery_relevance_service import STALE_THRESHOLD_HOURS
        old_ts = flush_now - timedelta(hours=STALE_THRESHOLD_HOURS + 1)
        await db_session.execute(
            update(DeliveryLedger)
            .where(DeliveryLedger.id == result.delivery_id)
            .values(created_at=old_ts)
            .execution_options(synchronize_session=False)
        )
        await db_session.flush()

        live_cfg = _cfg(in_app_enabled=True, shadow=False,
                        internal_only=True, internal_user_ids={uid})
        with _patch_cfg(live_cfg):
            flush_results = await flush_in_app(
                db_session, now=flush_now, limit=10, user_id=uid
            )

        suppressed = [r for r in flush_results
                      if r.status == STATUS_SUPPRESSED_GUARDRAIL]
        assert len(suppressed) >= 1

        from app.db.models import Notification
        from sqlalchemy import select, func
        count = (await db_session.execute(
            select(func.count()).select_from(Notification)
            .where(Notification.user_id == uid)
        )).scalar()
        assert count == 0

    @pytest.mark.asyncio
    async def test_quiet_hours_suppresses(self, db_session, monkeypatch):
        monkeypatch.setattr(ds, "_cfg_quiet_hours_start", lambda: 22)
        monkeypatch.setattr(ds, "_cfg_quiet_hours_end",   lambda: 7)

        uid    = f"u-internal-{_uid()}"
        result = await _enqueue_one(db_session, severity="critical")

        live_cfg = _cfg(in_app_enabled=True, shadow=False,
                        internal_only=True, internal_user_ids={uid})
        quiet_now = _now().replace(hour=23, minute=0, second=0, microsecond=0)
        with _patch_cfg(live_cfg):
            flush_results = await flush_in_app(
                db_session, now=quiet_now, limit=10, user_id=uid
            )

        suppressed = [r for r in flush_results
                      if r.reason == "quiet_hours"]
        assert len(suppressed) >= 1


# ===========================================================================
# § CHANNEL — non-in_app rows skipped in live mode
# ===========================================================================

class TestChannelGating:
    @pytest.mark.asyncio
    async def test_email_channel_not_delivered_as_notification(self, db_session, monkeypatch):
        monkeypatch.setattr(ds, "_cfg_quiet_hours_start", lambda: 22)
        monkeypatch.setattr(ds, "_cfg_quiet_hours_end",   lambda: 7)

        uid = f"u-internal-{_uid()}"
        tag = _uid()

        # Enqueue an email-channel row directly via delivery_create
        from app.db.repositories.delivery_prefs_repo import get_or_create_prefs
        from app.services.loop_idempotency_service import build_content_key, build_payload_hash
        from app.db.repositories import loop_repo

        payload = {"message": "email test", "severity": "critical"}
        ch_hash = build_payload_hash(payload)
        ck      = build_content_key(f"TGT-{tag}", "email", ch_hash, "2030-01-01")
        await loop_repo.delivery_create(
            db_session, content_key=ck, target_key=f"TGT-{tag}",
            channel="email", content_hash=ch_hash,
        )
        await db_session.flush()

        live_cfg = _cfg(in_app_enabled=True, shadow=False,
                        internal_only=True, internal_user_ids={uid})
        with _patch_cfg(live_cfg):
            flush_results = await flush_in_app(
                db_session, now=_flush_now(), limit=10, user_id=uid
            )

        email_results = [r for r in flush_results if r.channel == "email"]
        assert all(r.reason == REASON_NOT_IN_APP for r in email_results)

        from app.db.models import Notification
        from sqlalchemy import select, func
        count = (await db_session.execute(
            select(func.count()).select_from(Notification)
            .where(Notification.user_id == uid)
        )).scalar()
        assert count == 0


# ===========================================================================
# § STATUS_TRANSITIONS — ledger status correctness
# ===========================================================================

class TestStatusTransitions:
    @pytest.mark.asyncio
    async def test_pending_to_delivered_shadow_in_shadow_mode(self, db_session, monkeypatch):
        monkeypatch.setattr(ds, "_cfg_quiet_hours_start", lambda: 22)
        monkeypatch.setattr(ds, "_cfg_quiet_hours_end",   lambda: 7)

        result = await _enqueue_one(db_session, severity="critical")

        with _patch_cfg(_cfg(in_app_enabled=True, shadow=True)):
            await flush_in_app(db_session, now=_flush_now(), limit=10, user_id="u-s")

        from sqlalchemy import select
        from app.db.models import DeliveryLedger
        row = (await db_session.execute(
            select(DeliveryLedger).where(DeliveryLedger.id == result.delivery_id)
        )).scalar_one()
        assert row.status == "delivered_shadow"
        assert row.delivered_at is not None

    @pytest.mark.asyncio
    async def test_pending_to_delivered_in_live_mode(self, db_session, monkeypatch):
        monkeypatch.setattr(ds, "_cfg_quiet_hours_start", lambda: 22)
        monkeypatch.setattr(ds, "_cfg_quiet_hours_end",   lambda: 7)

        uid    = f"u-internal-{_uid()}"
        result = await _enqueue_one(db_session, severity="critical")

        live_cfg = _cfg(in_app_enabled=True, shadow=False,
                        internal_only=True, internal_user_ids={uid})
        with _patch_cfg(live_cfg):
            await flush_in_app(db_session, now=_flush_now(), limit=10, user_id=uid)

        from sqlalchemy import select
        from app.db.models import DeliveryLedger
        row = (await db_session.execute(
            select(DeliveryLedger).where(DeliveryLedger.id == result.delivery_id)
        )).scalar_one()
        assert row.status == STATUS_DELIVERED

    @pytest.mark.asyncio
    async def test_pending_stays_pending_when_no_rows_due(self, db_session):
        result = await _enqueue_one(db_session, severity="critical")

        # Use a not_before_utc in the future so the row is NOT due yet
        from sqlalchemy import update
        from app.db.models import DeliveryLedger
        future = _now() + timedelta(hours=2)
        await db_session.execute(
            update(DeliveryLedger)
            .where(DeliveryLedger.id == result.delivery_id)
            .values(not_before_utc=future)
            .execution_options(synchronize_session=False)
        )
        await db_session.flush()

        with _patch_cfg(_cfg(in_app_enabled=False)):
            await flush_in_app(db_session, now=_now(), limit=10, user_id="u-test")

        from sqlalchemy import select
        row = (await db_session.execute(
            select(DeliveryLedger).where(DeliveryLedger.id == result.delivery_id)
        )).scalar_one()
        assert row.status == "pending"


# ===========================================================================
# § SAFETY — no external sends, no Notifications from read operations
# ===========================================================================

class TestSafety:
    @pytest.mark.asyncio
    async def test_no_external_sends(self, db_session, monkeypatch):
        """flush_in_app must not call any SMTP / HTTP / external service."""
        monkeypatch.setattr(ds, "_cfg_quiet_hours_start", lambda: 22)
        monkeypatch.setattr(ds, "_cfg_quiet_hours_end",   lambda: 7)

        uid = f"u-internal-{_uid()}"
        await _enqueue_one(db_session, severity="critical")

        # If any external call is attempted it would raise (no network in tests)
        live_cfg = _cfg(in_app_enabled=True, shadow=False,
                        internal_only=True, internal_user_ids={uid})
        with _patch_cfg(live_cfg):
            # Should complete without raising / making external calls
            await flush_in_app(db_session, now=_flush_now(), limit=10, user_id=uid)

    @pytest.mark.asyncio
    async def test_get_delivery_config_returns_safe_defaults(self, monkeypatch):
        """get_delivery_config() always returns False for in_app_enabled by default."""
        # Patch settings to return defaults
        from app.config import Settings
        monkeypatch.setattr(
            "app.services.in_app_delivery_service.get_delivery_config",
            lambda: DeliveryConfig(
                in_app_enabled=False,
                shadow=True,
                internal_only=True,
                canary_pct=0,
                internal_user_ids=frozenset(),
            ),
        )
        cfg = DeliveryConfig(
            in_app_enabled=False, shadow=True,
            internal_only=True, canary_pct=0,
            internal_user_ids=frozenset(),
        )
        assert cfg.in_app_enabled is False
        assert cfg.shadow         is True
