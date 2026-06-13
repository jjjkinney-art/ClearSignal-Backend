"""
Phase 10C · Slice 4 — Delivery Triage Integration tests.

Validates that ranking is wired into loop_delivery_service.enqueue() in
shadow mode.  No external sends, no notifications, no delivery behaviour
changes beyond ledger row creation/suppression and metadata persistence.

Covers:
  § ROUTING        — critical→pending, medium→digest, low/info→pull_only
  § SUPPRESSION    — below min_severity, enabled=False, ranking suppress
  § PERSISTENCE    — canonical_severity, severity_rank, ranking metadata persisted
  § DEDUP          — duplicate content_key still suppressed
  § SAFETY         — no Notification rows created, no external sends
  § GUARDRAILS     — existing quiet_hours / daily_cap guardrails still respected
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

import pytest

from app.services.loop_delivery_service import (
    DeliveryResult,
    STATUS_SUPPRESSED_DUPLICATE,
    STATUS_SUPPRESSED_GUARDRAIL,
    REASON_DELIVERY_DISABLED,
    REASON_RANKING_SUPPRESS,
    REASON_QUIET_HOURS,
    REASON_DAILY_CAP,
    enqueue,
    flush_pending_shadow,
)
from app.services.intelligence_ranking_service import RankingDecision


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _uid() -> str:
    return uuid.uuid4().hex[:10]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _payload(severity: str = "high", tag: Optional[str] = None) -> dict:
    """Minimal payload that carries a severity for the ranking engine."""
    return {
        "message": f"triage-test-{tag or _uid()}",
        "severity": severity,
        "priority_score": 0.8,
        "materiality": 0.8,
        "relevance": 0.9,
        "created_at": _now().isoformat(),
    }


async def _enqueue(
    db_session,
    *,
    severity: str = "high",
    channel: str = "in_app",
    target_key: Optional[str] = None,
    user_id: Optional[str] = None,
    tag: Optional[str] = None,
    payload_override: Optional[dict] = None,
) -> DeliveryResult:
    tag = tag or _uid()
    payload = payload_override if payload_override is not None else _payload(severity=severity, tag=tag)
    return await enqueue(
        db_session,
        user_id=user_id or f"user-{tag}",
        channel=channel,
        target_key=target_key or f"TICK-{tag}",
        payload=payload,
        severity=severity,
    )


# ---------------------------------------------------------------------------
# § ROUTING — delivery_class drives what gets created
# ---------------------------------------------------------------------------

class TestRoutingDecisions:
    @pytest.mark.asyncio
    async def test_critical_creates_pending_row(self, db_session):
        result = await _enqueue(db_session, severity="critical")
        assert result.status == "pending"
        assert result.delivery_id is not None
        # ranking embedded in payload
        ranking = result.payload_json.get("ranking", {})
        assert ranking.get("canonical_severity") == "critical"
        assert ranking.get("delivery_class") == RankingDecision.PUSH_NOW

    @pytest.mark.asyncio
    async def test_high_creates_pending_row(self, db_session):
        result = await _enqueue(db_session, severity="high")
        assert result.status == "pending"
        assert result.delivery_id is not None

    @pytest.mark.asyncio
    async def test_medium_creates_pending_row_with_digest_class(self, db_session):
        result = await _enqueue(db_session, severity="medium")
        assert result.status == "pending"
        assert result.delivery_id is not None
        ranking = result.payload_json.get("ranking", {})
        assert ranking.get("delivery_class") == RankingDecision.DIGEST

    @pytest.mark.asyncio
    async def test_low_creates_pending_row_with_pull_only_class(self, db_session):
        result = await _enqueue(db_session, severity="low")
        assert result.status == "pending"
        assert result.delivery_id is not None
        ranking = result.payload_json.get("ranking", {})
        assert ranking.get("delivery_class") == RankingDecision.PULL_ONLY

    @pytest.mark.asyncio
    async def test_info_creates_pending_row_with_pull_only_class(self, db_session):
        result = await _enqueue(db_session, severity="info")
        assert result.status == "pending"
        assert result.delivery_id is not None
        ranking = result.payload_json.get("ranking", {})
        assert ranking.get("delivery_class") == RankingDecision.PULL_ONLY


# ---------------------------------------------------------------------------
# § SUPPRESSION — ranking-driven and prefs-driven suppression
# ---------------------------------------------------------------------------

class TestSuppressionPaths:
    @pytest.mark.asyncio
    async def test_below_min_severity_suppressed(self, db_session):
        """A medium payload with high min_severity pref → suppress."""
        from app.db.repositories.delivery_prefs_repo import update_prefs
        uid = f"user-min-{_uid()}"
        await update_prefs(db_session, user_id=uid, channel="in_app", min_severity="high")

        payload = _payload(severity="medium")
        result = await enqueue(
            db_session,
            user_id=uid,
            channel="in_app",
            target_key="TICK-MIN",
            payload=payload,
            severity="medium",
        )
        assert result.status == STATUS_SUPPRESSED_GUARDRAIL
        assert result.reason == REASON_RANKING_SUPPRESS
        assert result.delivery_id is None

    @pytest.mark.asyncio
    async def test_enabled_false_suppresses(self, db_session):
        """Prefs.enabled=False → DELIVERY_DISABLED suppress before ranking."""
        from app.db.repositories.delivery_prefs_repo import update_prefs
        uid = f"user-off-{_uid()}"
        await update_prefs(db_session, user_id=uid, channel="in_app", enabled=False)

        payload = _payload(severity="critical")  # even critical is suppressed
        result = await enqueue(
            db_session,
            user_id=uid,
            channel="in_app",
            target_key="TICK-OFF",
            payload=payload,
            severity="critical",
        )
        assert result.status == STATUS_SUPPRESSED_GUARDRAIL
        assert result.reason == REASON_DELIVERY_DISABLED
        assert result.delivery_id is None

    @pytest.mark.asyncio
    async def test_explicit_duplicate_flag_suppresses(self, db_session):
        """is_duplicate=True in payload → ranking suppress."""
        payload = _payload(severity="critical")
        payload["is_duplicate"] = True

        result = await enqueue(
            db_session,
            user_id=f"user-{_uid()}",
            channel="in_app",
            target_key="TICK-DUP",
            payload=payload,
            severity="critical",
        )
        assert result.status == STATUS_SUPPRESSED_GUARDRAIL
        assert result.reason == REASON_RANKING_SUPPRESS

    @pytest.mark.asyncio
    async def test_low_novelty_suppresses(self, db_session):
        """novelty < NOVELTY_SUPPRESS_THRESHOLD → suppress."""
        from app.services.intelligence_ranking_service import NOVELTY_SUPPRESS_THRESHOLD
        payload = _payload(severity="high")
        payload["novelty"] = NOVELTY_SUPPRESS_THRESHOLD * 0.5  # well below threshold

        result = await enqueue(
            db_session,
            user_id=f"user-{_uid()}",
            channel="in_app",
            target_key="TICK-NOVELTY",
            payload=payload,
            severity="high",
        )
        assert result.status == STATUS_SUPPRESSED_GUARDRAIL
        assert result.reason == REASON_RANKING_SUPPRESS

    @pytest.mark.asyncio
    async def test_critical_survives_high_min_severity_floor(self, db_session):
        """critical ≥ high floor → not suppressed by min_severity."""
        from app.db.repositories.delivery_prefs_repo import update_prefs
        uid = f"user-crit-{_uid()}"
        await update_prefs(db_session, user_id=uid, channel="in_app", min_severity="high")

        result = await enqueue(
            db_session,
            user_id=uid,
            channel="in_app",
            target_key="TICK-CRIT",
            payload=_payload(severity="critical"),
            severity="critical",
        )
        assert result.status == "pending"
        assert result.delivery_id is not None


# ---------------------------------------------------------------------------
# § PERSISTENCE — ranking metadata written to ledger row and payload
# ---------------------------------------------------------------------------

class TestPersistence:
    @pytest.mark.asyncio
    async def test_canonical_severity_persisted_on_row(self, db_session):
        from sqlalchemy import select
        from app.db.models import DeliveryLedger

        result = await _enqueue(db_session, severity="critical")
        assert result.delivery_id is not None

        row = (await db_session.execute(
            select(DeliveryLedger).where(DeliveryLedger.id == result.delivery_id)
        )).scalar_one()
        assert row.canonical_severity == "critical"

    @pytest.mark.asyncio
    async def test_severity_rank_persisted_on_row(self, db_session):
        from sqlalchemy import select
        from app.db.models import DeliveryLedger

        result = await _enqueue(db_session, severity="high")
        assert result.delivery_id is not None

        row = (await db_session.execute(
            select(DeliveryLedger).where(DeliveryLedger.id == result.delivery_id)
        )).scalar_one()
        assert row.severity_rank == 3  # HIGH → rank 3

    @pytest.mark.asyncio
    async def test_medium_severity_rank(self, db_session):
        from sqlalchemy import select
        from app.db.models import DeliveryLedger

        result = await _enqueue(db_session, severity="medium")
        row = (await db_session.execute(
            select(DeliveryLedger).where(DeliveryLedger.id == result.delivery_id)
        )).scalar_one()
        assert row.canonical_severity == "medium"
        assert row.severity_rank == 2

    @pytest.mark.asyncio
    async def test_ranking_score_in_payload_json(self, db_session):
        result = await _enqueue(db_session, severity="high")
        ranking = result.payload_json.get("ranking", {})
        score = ranking.get("priority_score")
        assert score is not None
        assert 0.0 <= score <= 1.0

    @pytest.mark.asyncio
    async def test_reason_codes_in_payload_json(self, db_session):
        result = await _enqueue(db_session, severity="critical")
        ranking = result.payload_json.get("ranking", {})
        codes = ranking.get("reason_codes", [])
        assert isinstance(codes, list)
        assert len(codes) > 0

    @pytest.mark.asyncio
    async def test_delivery_class_in_payload_json(self, db_session):
        result = await _enqueue(db_session, severity="medium")
        ranking = result.payload_json.get("ranking", {})
        assert ranking.get("delivery_class") in RankingDecision.ALL

    @pytest.mark.asyncio
    async def test_legacy_alert_token_translates_to_high(self, db_session):
        """Old delivery vocab 'alert' → HIGH canonical severity."""
        from sqlalchemy import select
        from app.db.models import DeliveryLedger

        result = await _enqueue(db_session, severity="alert")
        row = (await db_session.execute(
            select(DeliveryLedger).where(DeliveryLedger.id == result.delivery_id)
        )).scalar_one()
        assert row.canonical_severity == "high"
        assert row.severity_rank == 3

    @pytest.mark.asyncio
    async def test_legacy_warning_token_translates_to_medium(self, db_session):
        """Old delivery vocab 'warning' → MEDIUM canonical severity."""
        from sqlalchemy import select
        from app.db.models import DeliveryLedger

        result = await _enqueue(db_session, severity="warning")
        row = (await db_session.execute(
            select(DeliveryLedger).where(DeliveryLedger.id == result.delivery_id)
        )).scalar_one()
        assert row.canonical_severity == "medium"
        assert row.severity_rank == 2


# ---------------------------------------------------------------------------
# § DEDUP — duplicate content_key still hard-stops
# ---------------------------------------------------------------------------

class TestDeduplication:
    @pytest.mark.asyncio
    async def test_second_enqueue_same_content_suppressed(self, db_session):
        tag = _uid()
        payload = _payload(severity="critical", tag=tag)
        uid = f"user-{tag}"

        r1 = await enqueue(db_session, user_id=uid, channel="in_app",
                           target_key="TICK-DEDUP", payload=payload, severity="critical")
        r2 = await enqueue(db_session, user_id=uid, channel="in_app",
                           target_key="TICK-DEDUP", payload=payload, severity="critical")

        assert r1.status == "pending"
        assert r2.status == STATUS_SUPPRESSED_DUPLICATE

    @pytest.mark.asyncio
    async def test_different_users_different_content_keys(self, db_session):
        """Same payload, different users → different content_keys → two rows."""
        tag = _uid()
        payload = _payload(severity="high", tag=tag)

        r1 = await enqueue(db_session, user_id="u1", channel="in_app",
                           target_key="TICK-X", payload=payload, severity="high")
        r2 = await enqueue(db_session, user_id="u2", channel="in_app",
                           target_key="TICK-X", payload=payload, severity="high")

        # Both should create rows (different content_key per user)
        assert r1.status == "pending"
        assert r2.status == "pending"
        assert r1.delivery_id != r2.delivery_id


# ---------------------------------------------------------------------------
# § SAFETY — no notifications, no external sends
# ---------------------------------------------------------------------------

class TestSafety:
    @pytest.mark.asyncio
    async def test_no_notification_rows_created_on_enqueue(self, db_session):
        from sqlalchemy import select, func
        from app.db.models import Notification

        before = (await db_session.execute(
            select(func.count()).select_from(Notification)
        )).scalar()

        await _enqueue(db_session, severity="critical")
        await _enqueue(db_session, severity="high")
        await _enqueue(db_session, severity="medium")

        after = (await db_session.execute(
            select(func.count()).select_from(Notification)
        )).scalar()

        assert before == after, "enqueue must not create Notification rows (Slice 4 shadow only)"

    @pytest.mark.asyncio
    async def test_no_notification_rows_on_suppression(self, db_session):
        from sqlalchemy import select, func
        from app.db.models import Notification
        from app.db.repositories.delivery_prefs_repo import update_prefs

        uid = f"user-sup-{_uid()}"
        await update_prefs(db_session, user_id=uid, channel="in_app", min_severity="critical")

        before = (await db_session.execute(
            select(func.count()).select_from(Notification)
        )).scalar()

        # low severity — will be suppressed
        await enqueue(db_session, user_id=uid, channel="in_app",
                      target_key="TICK-SUP", payload=_payload(severity="low"),
                      severity="low")

        after = (await db_session.execute(
            select(func.count()).select_from(Notification)
        )).scalar()

        assert before == after

    @pytest.mark.asyncio
    async def test_null_session_returns_skipped(self):
        result = await enqueue(None, user_id="u", channel="in_app",
                               target_key="T", payload={"msg": "x"})
        assert result.status == "skipped"


# ---------------------------------------------------------------------------
# § GUARDRAILS — existing flush_pending_shadow guardrails still respected
# ---------------------------------------------------------------------------

class TestExistingGuardrails:
    @pytest.mark.asyncio
    async def test_quiet_hours_suppresses_during_flush(self, db_session):
        result = await _enqueue(db_session, severity="critical")
        assert result.status == "pending"

        # Flush during the quiet window (hour=23)
        quiet_now = _now().replace(hour=23, minute=0, second=0, microsecond=0)
        flush_results = await flush_pending_shadow(db_session, now=quiet_now)
        suppressed = [r for r in flush_results if r.reason == REASON_QUIET_HOURS]
        assert len(suppressed) >= 1

    @pytest.mark.asyncio
    async def test_ranking_metadata_survives_flush(self, db_session):
        """Rows created with canonical_severity are still present after a flush."""
        from sqlalchemy import select
        from app.db.models import DeliveryLedger

        result = await _enqueue(db_session, severity="critical")
        assert result.delivery_id is not None

        active_now = _now().replace(hour=12, minute=0, second=0, microsecond=0)
        await flush_pending_shadow(db_session, now=active_now)

        row = (await db_session.execute(
            select(DeliveryLedger).where(DeliveryLedger.id == result.delivery_id)
        )).scalar_one()
        # canonical_severity set at insert time; survives the status update
        assert row.canonical_severity == "critical"
        assert row.severity_rank == 4

    @pytest.mark.asyncio
    async def test_suppressed_row_has_no_delivery_id_in_result(self, db_session):
        """Suppressed results never carry a delivery_id (no row created)."""
        from app.db.repositories.delivery_prefs_repo import update_prefs
        uid = f"user-norow-{_uid()}"
        await update_prefs(db_session, user_id=uid, channel="in_app", enabled=False)

        result = await enqueue(db_session, user_id=uid, channel="in_app",
                               target_key="TICK-NOROW",
                               payload=_payload(severity="critical"),
                               severity="critical")
        assert result.delivery_id is None
