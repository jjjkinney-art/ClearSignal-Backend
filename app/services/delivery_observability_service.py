"""
Phase 10C · Slice 10 — Delivery observability snapshot.

Produces a single consistent, null-safe, DB-down-safe snapshot of the Phase 10C
delivery subsystem.  Intended callers:

  - GET /admin/delivery-status  (production admin endpoint)
  - tests/validate_10c_delivery_shadow.py  (deployment validation script)
  - integration tests

Design principles (mirrors loop_observability.py)
--------------------------------------------------
  - Never raises.  All DB calls are wrapped in try/except; missing data
    degrades gracefully to zero/null rather than failing the request.
  - No secrets.  API keys, database URLs, and user tokens never appear.
  - Fast.  Queries are lightweight aggregates (GROUP BY, COUNT); no full scans.
  - Deterministic schema.  All keys are always present; absent data represented
    by 0 / null / {} rather than omitted keys.

Snapshot structure (all top-level keys always present)
-------------------------------------------------------
  delivery_flags   — 4 Phase 10C feature flags from settings
  ledger           — delivery_ledger counts by status + severity distribution
  notifications    — notification counts by kind (delivery / inbox_read_receipt)
  digests          — digest_batch counts by status + channel
  preferences      — user_delivery_prefs row count
  recent_decisions — last N delivery ledger rows with status/severity/channel
  guardrails       — quiet hours, daily cap, severity floor
  duplicate_count  — in-process telemetry counter
  db_available     — bool, False if DB was unreachable
  snapshot_utc     — ISO-8601 timestamp
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_RECENT_ROWS_LIMIT = 10


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _safe_bool(val: Any, default: bool = False) -> bool:
    try:
        return bool(val)
    except Exception:
        return default


def _safe_int(val: Any, default: int = 0) -> int:
    try:
        return int(val)
    except Exception:
        return default


def _safe_str(val: Any, default: str = "") -> str:
    try:
        return str(val) if val is not None else default
    except Exception:
        return default


# ---------------------------------------------------------------------------
# Config section — delivery flags only, no secrets
# ---------------------------------------------------------------------------

def _delivery_flags_section() -> Dict[str, Any]:
    try:
        from app.config import settings as _s
        return {
            "delivery_in_app_enabled": _safe_bool(getattr(_s, "delivery_in_app_enabled", False)),
            "delivery_shadow":         _safe_bool(getattr(_s, "delivery_shadow", True)),
            "delivery_internal_only":  _safe_bool(getattr(_s, "delivery_internal_only", True)),
            "delivery_canary_pct":     _safe_int(getattr(_s, "delivery_canary_pct", 0)),
        }
    except Exception:
        return {
            "delivery_in_app_enabled": False,
            "delivery_shadow":         True,
            "delivery_internal_only":  True,
            "delivery_canary_pct":     0,
        }


# ---------------------------------------------------------------------------
# Guardrails section
# ---------------------------------------------------------------------------

def _guardrails_section() -> Dict[str, Any]:
    try:
        from app.config import settings as _s
        return {
            "quiet_hours_start_utc": _safe_int(getattr(_s, "delivery_quiet_hours_start", 22)),
            "quiet_hours_end_utc":   _safe_int(getattr(_s, "delivery_quiet_hours_end", 7)),
            "daily_cap":             _safe_int(getattr(_s, "delivery_daily_cap", 20)),
            "severity_floor":        _safe_str(getattr(_s, "delivery_severity_floor", "info")),
            "stale_threshold_hours": 72,
        }
    except Exception:
        return {
            "quiet_hours_start_utc": 22,
            "quiet_hours_end_utc":   7,
            "daily_cap":             20,
            "severity_floor":        "info",
            "stale_threshold_hours": 72,
        }


# ---------------------------------------------------------------------------
# DB sections
# ---------------------------------------------------------------------------

async def _ledger_section(session) -> Dict[str, Any]:
    try:
        from sqlalchemy import select, func
        from app.db.models import DeliveryLedger

        status_r = await session.execute(
            select(DeliveryLedger.status, func.count())
            .group_by(DeliveryLedger.status)
        )
        by_status = {row[0]: row[1] for row in status_r.all()}

        sev_r = await session.execute(
            select(DeliveryLedger.canonical_severity, func.count())
            .group_by(DeliveryLedger.canonical_severity)
        )
        by_severity = {(row[0] or "unknown"): row[1] for row in sev_r.all()}

        return {
            "total":        sum(by_status.values()),
            "by_status":    by_status,
            "shadow_count": by_status.get("delivered_shadow", 0),
            "pending_count": by_status.get("pending", 0),
            "delivered_count": by_status.get("delivered", 0),
            "suppressed_count": by_status.get("suppressed", 0),
            "by_severity":  by_severity,
        }
    except Exception as exc:
        logger.debug("[delivery_obs] ledger_section failed: %r", exc)
        return {
            "total": 0, "by_status": {}, "shadow_count": 0,
            "pending_count": 0, "delivered_count": 0, "suppressed_count": 0,
            "by_severity": {}, "db_error": str(exc),
        }


async def _notification_section(session) -> Dict[str, Any]:
    try:
        from sqlalchemy import select, func
        from app.db.models import Notification

        kind_r = await session.execute(
            select(Notification.kind, func.count())
            .group_by(Notification.kind)
        )
        by_kind = {row[0]: row[1] for row in kind_r.all()}

        return {
            "total":    sum(by_kind.values()),
            "by_kind":  by_kind,
            "delivery_notifications": by_kind.get("delivery", 0),
            "read_receipts":          by_kind.get("inbox_read_receipt", 0),
        }
    except Exception as exc:
        logger.debug("[delivery_obs] notification_section failed: %r", exc)
        return {
            "total": 0, "by_kind": {}, "delivery_notifications": 0,
            "read_receipts": 0, "db_error": str(exc),
        }


async def _digest_section(session) -> Dict[str, Any]:
    try:
        from sqlalchemy import select, func
        from app.db.models import DigestBatch

        status_r = await session.execute(
            select(DigestBatch.status, func.count())
            .group_by(DigestBatch.status)
        )
        by_status = {row[0]: row[1] for row in status_r.all()}

        channel_r = await session.execute(
            select(DigestBatch.channel, func.count())
            .group_by(DigestBatch.channel)
        )
        by_channel = {row[0]: row[1] for row in channel_r.all()}

        return {
            "total":      sum(by_status.values()),
            "by_status":  by_status,
            "by_channel": by_channel,
        }
    except Exception as exc:
        logger.debug("[delivery_obs] digest_section failed: %r", exc)
        return {
            "total": 0, "by_status": {}, "by_channel": {},
            "db_error": str(exc),
        }


async def _preferences_section(session) -> Dict[str, Any]:
    try:
        from sqlalchemy import select, func
        from app.db.models import UserDeliveryPref

        count_r = await session.execute(
            select(func.count()).select_from(UserDeliveryPref)
        )
        total = count_r.scalar() or 0

        return {"total_rows": total}
    except Exception as exc:
        logger.debug("[delivery_obs] preferences_section failed: %r", exc)
        return {"total_rows": 0, "db_error": str(exc)}


async def _recent_decisions_section(session, limit: int = _RECENT_ROWS_LIMIT) -> List[Dict]:
    try:
        from sqlalchemy import select
        from app.db.models import DeliveryLedger

        rows_r = await session.execute(
            select(DeliveryLedger)
            .order_by(DeliveryLedger.created_at.desc())
            .limit(limit)
        )
        rows = rows_r.scalars().all()
        return [
            {
                "delivery_id":        r.id,
                "content_key":        r.content_key,
                "target_key":         r.target_key,
                "channel":            r.channel,
                "status":             r.status,
                "canonical_severity": r.canonical_severity,
                "severity_rank":      r.severity_rank,
                "artifact_ref":       r.artifact_ref,
                "attempts":           r.attempts,
                "created_at":         r.created_at.isoformat() if r.created_at else None,
                "delivered_at":       r.delivered_at.isoformat() if r.delivered_at else None,
            }
            for r in rows
        ]
    except Exception as exc:
        logger.debug("[delivery_obs] recent_decisions_section failed: %r", exc)
        return []


async def _duplicate_count_section() -> int:
    try:
        from app.services import loop_canary_telemetry as _tel
        snap = _tel.snapshot()
        return snap.get("counters", {}).get("duplicate_delivery_count", 0)
    except Exception:
        return 0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def build_delivery_snapshot(session=None) -> Dict[str, Any]:
    """Build a complete, null-safe Phase 10C delivery observability snapshot.

    Parameters
    ----------
    session : AsyncSession or None.  When None, DB sections return zeros.

    Returns
    -------
    Dict — always succeeds; never raises.
    """
    snapshot_utc = _now_iso()
    db_available: Any = session is not None

    delivery_flags = _delivery_flags_section()
    guardrails     = _guardrails_section()
    duplicate_count = await _duplicate_count_section()

    if session is not None:
        ledger_sec   = await _ledger_section(session)
        notif_sec    = await _notification_section(session)
        digest_sec   = await _digest_section(session)
        prefs_sec    = await _preferences_section(session)
        recent       = await _recent_decisions_section(session)

        if any("db_error" in s for s in [ledger_sec, notif_sec, digest_sec, prefs_sec]):
            db_available = "partial"
    else:
        ledger_sec = {
            "total": 0, "by_status": {}, "shadow_count": 0,
            "pending_count": 0, "delivered_count": 0, "suppressed_count": 0,
            "by_severity": {},
        }
        notif_sec  = {"total": 0, "by_kind": {}, "delivery_notifications": 0, "read_receipts": 0}
        digest_sec = {"total": 0, "by_status": {}, "by_channel": {}}
        prefs_sec  = {"total_rows": 0}
        recent     = []

    # Derive safe_state: all defaults → True; any live delivery → False
    flags = delivery_flags
    safe_state = (
        not flags["delivery_in_app_enabled"]
        or flags["delivery_shadow"]
    )

    return {
        "status":          "ok",
        "snapshot_utc":    snapshot_utc,
        "db_available":    db_available,
        "safe_state":      safe_state,
        "delivery_flags":  delivery_flags,
        "ledger":          ledger_sec,
        "notifications":   notif_sec,
        "digests":         digest_sec,
        "preferences":     prefs_sec,
        "recent_decisions": recent,
        "duplicate_count": duplicate_count,
        "guardrails":      guardrails,
    }


def build_delivery_snapshot_sync() -> Dict[str, Any]:
    """Synchronous wrapper — returns config-only snapshot without DB sections.

    Useful for validation scripts that don't have an asyncio event loop.
    """
    snapshot_utc   = _now_iso()
    delivery_flags = _delivery_flags_section()
    guardrails     = _guardrails_section()

    flags = delivery_flags
    safe_state = not flags["delivery_in_app_enabled"] or flags["delivery_shadow"]

    return {
        "status":          "ok",
        "snapshot_utc":    snapshot_utc,
        "db_available":    False,
        "safe_state":      safe_state,
        "delivery_flags":  delivery_flags,
        "ledger":          {
            "total": 0, "by_status": {}, "shadow_count": 0,
            "pending_count": 0, "delivered_count": 0, "suppressed_count": 0,
            "by_severity": {},
        },
        "notifications":   {"total": 0, "by_kind": {}, "delivery_notifications": 0, "read_receipts": 0},
        "digests":         {"total": 0, "by_status": {}, "by_channel": {}},
        "preferences":     {"total_rows": 0},
        "recent_decisions": [],
        "duplicate_count": 0,
        "guardrails":      guardrails,
    }
