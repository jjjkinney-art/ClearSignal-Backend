"""
Forecast Observability Service — Phase 12 · Slice 9.

Produces a single consistent, null-safe, DB-down-safe snapshot of the
Phase 12 forecasting subsystem. Intended callers:

  - GET /admin/forecast-status            (production admin endpoint)
  - tests/validate_12_forecasting_shadow.py (deployment validation script)
  - integration tests

Design principles (mirrors similarity_observability_service.py /
billing_observability_service.py / delivery_observability_service.py)
------------------------------------------------------------------------
  - Never raises. All DB calls wrapped in try/except; degraded to 0/None.
  - No secrets — only booleans/strings/counts, never raw payloads.
  - Read-only. This module never builds, scores, rebuilds, or writes
    anything.  It only counts and reads timestamps from existing rows.
  - Deterministic schema. All keys always present; missing data → 0/None.

Snapshot structure
------------------
  flags                       — all 6 Phase 12 forecast_* settings
  db_available                — False if DB was unreachable this call
  vector_count                — total forecast_vector rows
  evidence_count              — total forecast_evidence rows
  calibration_count           — total forecast_calibration_log rows
  expired_vector_count        — forecast_vector rows with expires_at in the past
  vector_count_by_type        — {thesis_strengthening: n, …}
  vector_count_by_horizon     — {near_term: n, medium_term: n, long_term: n}
  shadow_delivery_count       — delivery_ledger rows with channel="forecast_shadow"
  shadow_escalated_count      — those rows that reached status="delivered" (must be 0)
  live_notification_count     — Notification rows with kind="forecast" (must be 0)
  latest_forecast_at          — max(forecast_vector.built_at) ISO-8601 or None
  latest_calibration_at       — max(forecast_calibration_log.evaluated_at) ISO-8601 or None
  safe_state                  — see below
  snapshot_utc                — ISO-8601 timestamp of this snapshot

safe_state is True when ALL of:
  - forecast_shadow == True
  - forecast_delivery_enabled == False      (no live delivery)
  - shadow_escalated_count == 0             (no shadow row ever promoted)
  - live_notification_count == 0            (no forecast Notification ever written)

"No conviction consumers" is a structural invariant verified statically
by tests/validate_12_forecasting_shadow.py via an import-graph check,
not recomputed at snapshot time.

SP-4 boundary
-------------
This module NEVER reads conviction, stance, verdict_rationale, or any
LLM-prompt field. It NEVER writes forecast_vector, forecast_evidence, or
any source table. It only reads COUNT / MAX aggregates from the forecast_*
tables and delivery_ledger / notifications.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# Channel name mirrors forecast_delivery_service.FORECAST_DELIVERY_CHANNEL.
# Duplicated as a literal (not imported) so this read-only observability
# module has zero dependency on the delivery module's import graph.
FORECAST_DELIVERY_CHANNEL = "forecast_shadow"

_FORECAST_TYPES = (
    "thesis_strengthening",
    "thesis_weakening",
    "risk_escalation",
    "risk_resolution",
    "catalyst_approaching",
    "catalyst_resolved",
)
_HORIZONS = ("near_term", "medium_term", "long_term")


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _iso_or_none(dt) -> Optional[str]:
    if dt is None:
        return None
    try:
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    except Exception:
        return None


def _flags_section() -> Dict[str, Any]:
    try:
        from app.config import settings
        return {
            "forecast_build_enabled":     bool(getattr(settings, "forecast_build_enabled",     False)),
            "forecast_scoring_enabled":   bool(getattr(settings, "forecast_scoring_enabled",   False)),
            "forecast_delivery_enabled":  bool(getattr(settings, "forecast_delivery_enabled",  False)),
            "forecast_shadow":            bool(getattr(settings, "forecast_shadow",             True)),
            "forecast_targets_enabled":   str( getattr(settings, "forecast_targets_enabled",   "") or ""),
            "forecast_calibration_enabled": bool(getattr(settings, "forecast_calibration_enabled", False)),
        }
    except Exception as exc:
        logger.debug("[forecast_observability] flags section failed: %r", exc)
        return {
            "forecast_build_enabled":     False,
            "forecast_scoring_enabled":   False,
            "forecast_delivery_enabled":  False,
            "forecast_shadow":            True,
            "forecast_targets_enabled":   "",
            "forecast_calibration_enabled": False,
        }


def _empty_by_type() -> Dict[str, int]:
    return {t: 0 for t in _FORECAST_TYPES}


def _empty_by_horizon() -> Dict[str, int]:
    return {h: 0 for h in _HORIZONS}


def _empty_snapshot(flags: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "flags":                    flags,
        "db_available":             False,
        "vector_count":             0,
        "evidence_count":           0,
        "calibration_count":        0,
        "expired_vector_count":     0,
        "vector_count_by_type":     _empty_by_type(),
        "vector_count_by_horizon":  _empty_by_horizon(),
        "shadow_delivery_count":    0,
        "shadow_escalated_count":   0,
        "live_notification_count":  0,
        "latest_forecast_at":       None,
        "latest_calibration_at":    None,
        "safe_state":               True,
        "snapshot_utc":             _now_iso(),
    }


async def build_forecast_observability_snapshot(session) -> Dict[str, Any]:
    """Build the full Phase 12 observability snapshot. Never raises."""
    flags = _flags_section()

    if session is None:
        return _empty_snapshot(flags)

    try:
        from sqlalchemy import select, func
        from app.db.models import (
            ForecastVector,
            ForecastEvidence,
            ForecastCalibrationLog,
            DeliveryLedger,
            Notification,
        )

        now = datetime.now(timezone.utc)

        # ── vector counts ─────────────────────────────────────────────────
        vector_count = int(
            (await session.execute(select(func.count()).select_from(ForecastVector))).scalar_one() or 0
        )

        expired_vector_count = int(
            (
                await session.execute(
                    select(func.count()).select_from(ForecastVector).where(
                        ForecastVector.expires_at <= now
                    )
                )
            ).scalar_one() or 0
        )

        vector_count_by_type = _empty_by_type()
        for ft in _FORECAST_TYPES:
            count = (
                await session.execute(
                    select(func.count()).select_from(ForecastVector).where(
                        ForecastVector.forecast_type == ft
                    )
                )
            ).scalar_one()
            vector_count_by_type[ft] = int(count or 0)

        vector_count_by_horizon = _empty_by_horizon()
        for hz in _HORIZONS:
            count = (
                await session.execute(
                    select(func.count()).select_from(ForecastVector).where(
                        ForecastVector.horizon == hz
                    )
                )
            ).scalar_one()
            vector_count_by_horizon[hz] = int(count or 0)

        latest_forecast_at = (
            await session.execute(select(func.max(ForecastVector.built_at)))
        ).scalar_one()

        # ── evidence ──────────────────────────────────────────────────────
        evidence_count = int(
            (await session.execute(select(func.count()).select_from(ForecastEvidence))).scalar_one() or 0
        )

        # ── calibration ───────────────────────────────────────────────────
        calibration_count = int(
            (await session.execute(select(func.count()).select_from(ForecastCalibrationLog))).scalar_one() or 0
        )
        latest_calibration_at = (
            await session.execute(select(func.max(ForecastCalibrationLog.evaluated_at)))
        ).scalar_one()

        # ── delivery ──────────────────────────────────────────────────────
        shadow_delivery_count = int(
            (
                await session.execute(
                    select(func.count()).select_from(DeliveryLedger).where(
                        DeliveryLedger.channel == FORECAST_DELIVERY_CHANNEL
                    )
                )
            ).scalar_one() or 0
        )
        shadow_escalated_count = int(
            (
                await session.execute(
                    select(func.count()).select_from(DeliveryLedger).where(
                        DeliveryLedger.channel == FORECAST_DELIVERY_CHANNEL,
                        DeliveryLedger.status == "delivered",
                    )
                )
            ).scalar_one() or 0
        )

        # ── notifications ─────────────────────────────────────────────────
        live_notification_count = int(
            (
                await session.execute(
                    select(func.count()).select_from(Notification).where(
                        Notification.kind == "forecast"
                    )
                )
            ).scalar_one() or 0
        )

        # ── safe_state ────────────────────────────────────────────────────
        safe_state = (
            flags["forecast_shadow"] is True
            and flags["forecast_delivery_enabled"] is False
            and shadow_escalated_count == 0
            and live_notification_count == 0
        )

        return {
            "flags":                    flags,
            "db_available":             True,
            "vector_count":             vector_count,
            "evidence_count":           evidence_count,
            "calibration_count":        calibration_count,
            "expired_vector_count":     expired_vector_count,
            "vector_count_by_type":     vector_count_by_type,
            "vector_count_by_horizon":  vector_count_by_horizon,
            "shadow_delivery_count":    shadow_delivery_count,
            "shadow_escalated_count":   shadow_escalated_count,
            "live_notification_count":  live_notification_count,
            "latest_forecast_at":       _iso_or_none(latest_forecast_at),
            "latest_calibration_at":    _iso_or_none(latest_calibration_at),
            "safe_state":               safe_state,
            "snapshot_utc":             _now_iso(),
        }
    except Exception as exc:
        logger.debug(
            "[forecast_observability] build_forecast_observability_snapshot failed: %r", exc
        )
        return _empty_snapshot(flags)
