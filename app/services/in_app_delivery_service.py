"""
In-App Delivery Channel Activation — Phase 10C · Slice 9.

Extends the shadow flush pipeline to optionally create real Notification
rows for the in_app channel, gated by three independent feature flags:

    DELIVERY_IN_APP_ENABLED   (default False)  — master gate
    DELIVERY_SHADOW           (default True)   — shadow vs live mode
    DELIVERY_INTERNAL_ONLY    (default True)   — internal users only
    DELIVERY_CANARY_PCT       (default 0)      — canary rollout %

Safe defaults
-------------
With all defaults the flusher is behaviourally identical to
flush_pending_shadow(): rows are marked delivered_shadow and no Notification
rows are ever written.  Real Notification creation requires:
    DELIVERY_IN_APP_ENABLED=true
    DELIVERY_SHADOW=false
    (and either DELIVERY_INTERNAL_ONLY=true with configured internal users,
     or DELIVERY_CANARY_PCT > 0)

Channels
--------
Only channel="in_app" rows receive Notification rows.  Rows for any other
channel are silently skipped (they may be handled by future channel services).

Deduplication
-------------
Before writing a Notification, the service checks whether a Notification with
body_json["delivery_id"] == row.id already exists for the target user.  A
second flush of the same row never creates a duplicate.

Public API
----------
    flush_in_app(session, *, now, limit, user_id) -> List[DeliveryResult]

    DeliveryConfig   — read-only view of active feature flags (for tests)
    get_delivery_config() -> DeliveryConfig
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.db.repositories import loop_repo
from app.services.loop_delivery_service import (
    DeliveryResult,
    STATUS_DELIVERED_SHADOW,
    STATUS_SUPPRESSED_GUARDRAIL,
    REASON_SHADOW_DRAIN,
    _process_shadow_row,    # guardrail stack — reused as-is
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Status / reason constants (Slice 9 additions)
# ---------------------------------------------------------------------------

STATUS_DELIVERED         = "delivered"         # real Notification created
REASON_IN_APP_DISABLED   = "in_app_disabled"   # master gate off
REASON_NOT_IN_APP        = "not_in_app_channel"
REASON_COHORT_CONTROL    = "cohort_control"    # not in delivery cohort
REASON_SHADOW_MODE       = "shadow_mode"       # shadow=True


# ---------------------------------------------------------------------------
# Config snapshot
# ---------------------------------------------------------------------------

@dataclass
class DeliveryConfig:
    """Read-only snapshot of the in-app delivery feature flags."""
    in_app_enabled:   bool
    shadow:           bool
    internal_only:    bool
    canary_pct:       int
    internal_user_ids: frozenset


def get_delivery_config() -> DeliveryConfig:
    """Read current delivery flags from settings."""
    try:
        from app.config import settings
        raw_ids: str = getattr(settings, "loop_internal_user_ids", "") or ""
        ids = frozenset(u.strip() for u in raw_ids.split(",") if u.strip())
        return DeliveryConfig(
            in_app_enabled=bool(getattr(settings, "delivery_in_app_enabled", False)),
            shadow=bool(getattr(settings, "delivery_shadow", True)),
            internal_only=bool(getattr(settings, "delivery_internal_only", True)),
            canary_pct=int(getattr(settings, "delivery_canary_pct", 0)),
            internal_user_ids=ids,
        )
    except Exception:
        return DeliveryConfig(
            in_app_enabled=False,
            shadow=True,
            internal_only=True,
            canary_pct=0,
            internal_user_ids=frozenset(),
        )


# ---------------------------------------------------------------------------
# Cohort gate
# ---------------------------------------------------------------------------

def _is_eligible_for_live_delivery(user_id: Optional[str], cfg: DeliveryConfig) -> bool:
    """Return True when this user_id is allowed real (non-shadow) delivery.

    Internal users always pass.
    Non-internal users pass only when internal_only=False and the CRC32 bucket
    falls within the delivery_canary_pct window (reuses loop canary hash).
    """
    if not user_id:
        return False

    # Internal users bypass canary gate
    if user_id in cfg.internal_user_ids:
        return True

    if cfg.internal_only:
        return False

    if cfg.canary_pct <= 0:
        return False

    try:
        from app.services.loop_canary_cohort import decide_cohort, COHORT_INTERNAL, COHORT_CANARY
        cohort = decide_cohort(
            subject_id=user_id,
            canary_pct=cfg.canary_pct,
            enabled=True,
            shadow=False,
        )
        return cohort in (COHORT_INTERNAL, COHORT_CANARY)
    except Exception as exc:
        logger.warning("[in_app] cohort check failed (fail-closed): %r", exc)
        return False


# ---------------------------------------------------------------------------
# Deduplication helpers
# ---------------------------------------------------------------------------

async def _notification_exists(session, user_id: str, delivery_id: str) -> bool:
    """Return True if a Notification with body_json['delivery_id']==delivery_id exists."""
    try:
        from sqlalchemy import select
        from app.db.models import Notification

        result = await session.execute(
            select(Notification)
            .where(Notification.user_id == user_id)
            .where(Notification.body_json["delivery_id"].as_string() == delivery_id)
            .limit(1)
        )
        return result.scalar_one_or_none() is not None
    except Exception as exc:
        logger.warning("[in_app] dedup check failed (fail-safe, skip create): %r", exc)
        return True   # fail-safe: assume exists to avoid spurious duplicates


async def _mark_delivered(session, delivery_id: str, now: datetime) -> None:
    """Transition a ledger row from delivered_shadow → delivered."""
    try:
        from sqlalchemy import update
        from app.db.models import DeliveryLedger

        now_naive = now.replace(tzinfo=None) if now.tzinfo else now
        await session.execute(
            update(DeliveryLedger)
            .where(DeliveryLedger.id == delivery_id)
            .values(status=STATUS_DELIVERED, delivered_at=now_naive)
            .execution_options(synchronize_session=False)
        )
        await session.flush()
    except Exception as exc:
        logger.warning("[in_app] _mark_delivered failed for %r: %r", delivery_id, exc)


# ---------------------------------------------------------------------------
# Core flusher
# ---------------------------------------------------------------------------

async def flush_in_app(
    session,
    *,
    now: Optional[datetime] = None,
    limit: int = 50,
    user_id: Optional[str] = None,
) -> List[DeliveryResult]:
    """Drain pending in-app delivery ledger rows.

    Behaviour varies by config:

    delivery_in_app_enabled=False (default)
        → Identical to flush_pending_shadow(); marks delivered_shadow; no
          Notification rows created.

    delivery_in_app_enabled=True, delivery_shadow=True (default shadow)
        → Runs guardrails; marks delivered_shadow; no Notification rows.
          (shadow validation still active)

    delivery_in_app_enabled=True, delivery_shadow=False
        → Runs guardrails; for eligible in_app rows creates a Notification
          row of kind="delivery" and marks the ledger delivered.
          Non-in_app rows are skipped (returned as REASON_NOT_IN_APP).
          Non-eligible users (cohort gate) are suppressed with REASON_COHORT_CONTROL.

    Parameters
    ----------
    session  : AsyncSession or None.
    now      : Reference time; defaults to UTC now.
    limit    : Max rows to process per call.
    user_id  : User to receive Notifications.  Required for live delivery;
               when None the service falls back to shadow mode regardless of flags.
    """
    if session is None:
        return []

    now = now or datetime.now(timezone.utc)
    cfg = get_delivery_config()

    # ── Fast path: master gate off OR shadow mode → delegate to shadow flusher ─
    if not cfg.in_app_enabled or cfg.shadow or user_id is None:
        from app.services.loop_delivery_service import flush_pending_shadow
        return await flush_pending_shadow(session, now=now, limit=limit)

    # ── Live delivery path ────────────────────────────────────────────────────
    rows = await loop_repo.delivery_get_pending(session, now=now, limit=limit)
    results: List[DeliveryResult] = []

    for row in rows:
        result = await _process_live_row(session, row, now, cfg, user_id)
        results.append(result)

    delivered   = sum(1 for r in results if r.status == STATUS_DELIVERED)
    shadowed    = sum(1 for r in results if r.status == STATUS_DELIVERED_SHADOW)
    suppressed  = sum(1 for r in results if r.status == STATUS_SUPPRESSED_GUARDRAIL)
    logger.info(
        "[in_app] flush_in_app: processed=%d delivered=%d shadowed=%d suppressed=%d",
        len(results), delivered, shadowed, suppressed,
    )
    return results


async def _process_live_row(
    session,
    row: Any,
    now: datetime,
    cfg: DeliveryConfig,
    user_id: str,
) -> DeliveryResult:
    """Process one pending ledger row in live (non-shadow) mode."""

    def _fail(reason: str) -> DeliveryResult:
        return DeliveryResult(
            status=STATUS_SUPPRESSED_GUARDRAIL,
            content_key=row.content_key,
            channel=row.channel,
            target_key=row.target_key,
            reason=reason,
            delivery_id=row.id,
        )

    # ── Channel gate: only in_app ─────────────────────────────────────────────
    if row.channel != "in_app":
        logger.debug("[in_app] skipping non-in_app row %s channel=%s", row.id, row.channel)
        return _fail(REASON_NOT_IN_APP)

    # ── Cohort gate ───────────────────────────────────────────────────────────
    if not _is_eligible_for_live_delivery(user_id, cfg):
        await loop_repo.delivery_mark_suppressed(session, row.id)
        logger.debug("[in_app] cohort_control %s user=%s", row.id, user_id)
        return _fail(REASON_COHORT_CONTROL)

    # ── Full guardrail stack (quiet hours / daily cap / mute / recheck) ───────
    # _process_shadow_row runs all guards and marks delivered_shadow on success.
    # We then promote to delivered + write Notification.
    guard_result = await _process_shadow_row(session, row, now)

    if guard_result.status != STATUS_DELIVERED_SHADOW:
        # A guardrail suppressed the row; return the suppressed result as-is
        return guard_result

    # ── Notification dedup ───────────────────────────────────────────────────
    if await _notification_exists(session, user_id, row.id):
        logger.debug("[in_app] dedup: notification already exists for delivery=%s", row.id)
        # Row already marked delivered_shadow; promote to delivered silently
        await _mark_delivered(session, row.id, now)
        return DeliveryResult(
            status=STATUS_DELIVERED,
            content_key=row.content_key,
            channel=row.channel,
            target_key=row.target_key,
            reason="dedup_already_delivered",
            delivery_id=row.id,
        )

    # ── Write Notification row ────────────────────────────────────────────────
    body: Dict = {
        "delivery_id":        row.id,
        "content_key":        row.content_key,
        "target_key":         row.target_key,
        "channel":            row.channel,
        "canonical_severity": getattr(row, "canonical_severity", None),
        "severity_rank":      getattr(row, "severity_rank", None),
        "artifact_ref":       getattr(row, "artifact_ref", None),
    }
    notif = await loop_repo.notification_create(
        session,
        user_id=user_id,
        kind="delivery",
        body_json=body,
    )
    if notif is None:
        logger.warning("[in_app] notification_create returned None for delivery=%s", row.id)
        # Keep as delivered_shadow rather than failing
        return DeliveryResult(
            status=STATUS_DELIVERED_SHADOW,
            content_key=row.content_key,
            channel=row.channel,
            target_key=row.target_key,
            reason=REASON_SHADOW_DRAIN,
            delivery_id=row.id,
        )

    # ── Promote ledger row: delivered_shadow → delivered ──────────────────────
    await _mark_delivered(session, row.id, now)

    logger.info(
        "[in_app] delivered user=%s delivery=%s target=%s severity=%s",
        user_id, row.id, row.target_key,
        getattr(row, "canonical_severity", "?"),
    )
    return DeliveryResult(
        status=STATUS_DELIVERED,
        content_key=row.content_key,
        channel=row.channel,
        target_key=row.target_key,
        reason="in_app_delivered",
        delivery_id=row.id,
    )
