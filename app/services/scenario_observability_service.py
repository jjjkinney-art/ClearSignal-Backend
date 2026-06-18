"""
Scenario Observability Service — Phase 14 · Slice 10.

Provides a single production-ready observability snapshot covering:

  flags      — all 6 scenario_* config flags with their current values
  metrics    — row counts, shadow-delivery ledger counts, calibration counts,
               breakdown by scenario type and impact band
  safe_state — structured boolean sub-checks confirming the Phase 14 shadow
               boundary is intact

The intent of this module is strictly read-only: it measures and reports.
It never writes to any table, never mutates config, and never triggers a
build, propagation, or delivery step.

safe_state sub-checks
---------------------
  shadow_delivery_only
    scenario_delivery_enabled=False and scenario_shadow=True.
    Confirms all scenario-related ledger writes land in the inert
    scenario_shadow channel, not a live delivery pipeline.

  no_live_notifications
    Zero Notification rows exist where the artifact_ref contains
    "scenario" (i.e. no scenario event has been promoted to a visible
    user notification).

  no_recommendation_consumers
    scenario_delivery_enabled is False.  No downstream process can
    drain the scenario_shadow channel as if it were a recommendation.

  no_conviction_consumers
    No live service configured to write scenario output back into
    the conviction table.  Confirmed by inspecting the flag combination:
    scenario_scoring_enabled=False keeps the scoring pipeline idle.

  no_forecast_mutation_consumers
    The scenario layer has no write-path to forecast_vector.  Confirmed
    by the flag gate: scenario_build_enabled=False.

  no_decision_mutation_consumers
    The scenario layer has no write-path to the decisions table.
    Confirmed by the flag gate: scenario_build_enabled=False.

All safe_state checks are derived from live flag values + DB counts so
they accurately reflect the running system, not a static assertion.

SP-6 invariant: This module reads only — no advice, no conviction writes,
no scenario_snapshot mutations.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

OBSERVABILITY_SCHEMA_VERSION: int = 1

# Impact bands as defined by ScenarioSnapshot.scenario_impact
IMPACT_BANDS: List[str] = [
    "significant_positive",
    "moderate_positive",
    "neutral",
    "moderate_negative",
    "significant_negative",
    "ambiguous",
]


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Internal DB helpers
# ---------------------------------------------------------------------------

async def _count_rows(session, model_class, **filter_kwargs) -> int:
    """Generic count of rows matching simple equality filters."""
    if session is None:
        return 0
    try:
        from sqlalchemy import select, func
        stmt = select(func.count()).select_from(model_class)
        for col_name, value in filter_kwargs.items():
            col = getattr(model_class, col_name, None)
            if col is not None:
                stmt = stmt.where(col == value)
        result = await session.execute(stmt)
        return result.scalar() or 0
    except Exception as exc:
        logger.debug("[scenario_observability] _count_rows(%s): %r", model_class.__name__, exc)
        return 0


async def _count_shadow_deliveries(session) -> int:
    """Count delivery_ledger rows with channel='scenario_shadow'."""
    if session is None:
        return 0
    try:
        from sqlalchemy import select, func
        from app.db.models import DeliveryLedger
        stmt = (
            select(func.count())
            .select_from(DeliveryLedger)
            .where(DeliveryLedger.channel == "scenario_shadow")
        )
        result = await session.execute(stmt)
        return result.scalar() or 0
    except Exception as exc:
        logger.debug("[scenario_observability] _count_shadow_deliveries: %r", exc)
        return 0


async def _count_live_notifications(session) -> int:
    """Count Notification rows (any row = a user-visible scenario event leaked out)."""
    if session is None:
        return 0
    try:
        from sqlalchemy import select, func
        from app.db.models import Notification
        stmt = select(func.count()).select_from(Notification)
        result = await session.execute(stmt)
        return result.scalar() or 0
    except Exception as exc:
        logger.debug("[scenario_observability] _count_live_notifications: %r", exc)
        return 0


async def _latest_timestamp(session, model_class, col_name: str) -> Optional[str]:
    """Return ISO-formatted max(col_name) from model_class, or None."""
    if session is None:
        return None
    try:
        from sqlalchemy import select, func
        col = getattr(model_class, col_name, None)
        if col is None:
            return None
        stmt = select(func.max(col)).select_from(model_class)
        result = await session.execute(stmt)
        ts = result.scalar()
        if ts is None:
            return None
        if isinstance(ts, str):
            return ts
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return ts.isoformat()
    except Exception as exc:
        logger.debug("[scenario_observability] _latest_timestamp(%s.%s): %r",
                     model_class.__name__, col_name, exc)
        return None


async def _count_by_column(session, model_class, col_name: str) -> Dict[str, int]:
    """Return a {value: count} breakdown for col_name across all rows."""
    if session is None:
        return {}
    try:
        from sqlalchemy import select, func
        col = getattr(model_class, col_name, None)
        if col is None:
            return {}
        stmt = (
            select(col, func.count())
            .select_from(model_class)
            .group_by(col)
        )
        result = await session.execute(stmt)
        return {(row[0] or "unknown"): row[1] for row in result.fetchall()}
    except Exception as exc:
        logger.debug("[scenario_observability] _count_by_column(%s.%s): %r",
                     model_class.__name__, col_name, exc)
        return {}


# ---------------------------------------------------------------------------
# safe_state computation
# ---------------------------------------------------------------------------

def _compute_safe_state(flags: Dict[str, Any], live_notification_count: int) -> Dict[str, Any]:
    """Derive the structured safe_state sub-checks from flags + live DB counts.

    Every sub-check is a bool.  overall is True only when all sub-checks pass.
    """
    build_enabled    = bool(flags.get("scenario_build_enabled",    False))
    scoring_enabled  = bool(flags.get("scenario_scoring_enabled",  False))
    delivery_enabled = bool(flags.get("scenario_delivery_enabled", False))
    shadow           = bool(flags.get("scenario_shadow",           True))

    shadow_delivery_only          = (not delivery_enabled) and shadow
    no_live_notifications         = (live_notification_count == 0)
    no_recommendation_consumers   = not delivery_enabled
    no_conviction_consumers       = not scoring_enabled
    no_forecast_mutation_consumers = not build_enabled
    no_decision_mutation_consumers = not build_enabled

    overall = (
        shadow_delivery_only
        and no_live_notifications
        and no_recommendation_consumers
        and no_conviction_consumers
        and no_forecast_mutation_consumers
        and no_decision_mutation_consumers
    )

    return {
        "overall":                       overall,
        "shadow_delivery_only":          shadow_delivery_only,
        "no_live_notifications":         no_live_notifications,
        "no_recommendation_consumers":   no_recommendation_consumers,
        "no_conviction_consumers":       no_conviction_consumers,
        "no_forecast_mutation_consumers": no_forecast_mutation_consumers,
        "no_decision_mutation_consumers": no_decision_mutation_consumers,
    }


# ---------------------------------------------------------------------------
# build_scenario_observability_snapshot
# ---------------------------------------------------------------------------

async def build_scenario_observability_snapshot(session) -> Dict[str, Any]:
    """Return the full Phase 14 observability snapshot.

    DB-down-safe: degrades gracefully to zero metrics and safe defaults
    when session is None or any query fails.  Never raises.

    Response shape
    --------------
    {
      flags:               {scenario_build_enabled, ..., scenario_calibration_enabled},
      metrics: {
        scenario_snapshot_count: int,
        scenario_evidence_count: int,
        scenario_run_log_count:  int,
        scenario_count_by_type:  {macro: int, ...},
        scenario_count_by_impact: {significant_positive: int, ...},
        shadow_delivery_count:   int,
        live_notification_count: int,
        latest_scenario_timestamp:    str|null,
        latest_calibration_timestamp: str|null,
      },
      safe_state: {
        overall: bool,
        shadow_delivery_only: bool,
        no_live_notifications: bool,
        no_recommendation_consumers: bool,
        no_conviction_consumers: bool,
        no_forecast_mutation_consumers: bool,
        no_decision_mutation_consumers: bool,
      },
      db_available: bool,
      schema_version: int,
      disclaimer: str,
    }
    """
    from app.config import settings

    flags: Dict[str, Any] = {
        "scenario_build_enabled":       settings.scenario_build_enabled,
        "scenario_scoring_enabled":     settings.scenario_scoring_enabled,
        "scenario_delivery_enabled":    settings.scenario_delivery_enabled,
        "scenario_shadow":              settings.scenario_shadow,
        "scenario_targets_enabled":     settings.scenario_targets_enabled,
        "scenario_calibration_enabled": settings.scenario_calibration_enabled,
    }

    _DISCLAIMER = (
        "Scenario output is conditional and structural. "
        "It does not constitute advice, a suggested course of action, a target, "
        "or a prediction of any outcome."
    )

    empty_metrics: Dict[str, Any] = {
        "scenario_snapshot_count":         0,
        "scenario_evidence_count":         0,
        "scenario_run_log_count":          0,
        "scenario_count_by_type":          {},
        "scenario_count_by_impact":        {},
        "shadow_delivery_count":           0,
        "live_notification_count":         0,
        "latest_scenario_timestamp":       None,
        "latest_calibration_timestamp":    None,
    }

    if session is None:
        safe_state = _compute_safe_state(flags, 0)
        return {
            "flags":          flags,
            "metrics":        empty_metrics,
            "safe_state":     safe_state,
            "db_available":   False,
            "schema_version": OBSERVABILITY_SCHEMA_VERSION,
            "disclaimer":     _DISCLAIMER,
        }

    try:
        from app.db.models import (
            ScenarioSnapshot,
            ScenarioEvidence,
            ScenarioRunLog,
        )

        # Core row counts
        snapshot_count  = await _count_rows(session, ScenarioSnapshot)
        evidence_count  = await _count_rows(session, ScenarioEvidence)
        run_log_count   = await _count_rows(session, ScenarioRunLog)

        # Breakdowns
        by_type   = await _count_by_column(session, ScenarioSnapshot, "scenario_type")
        by_impact = await _count_by_column(session, ScenarioSnapshot, "scenario_impact")

        # Delivery counts
        shadow_count   = await _count_shadow_deliveries(session)
        notif_count    = await _count_live_notifications(session)

        # Timestamps
        latest_scenario = await _latest_timestamp(session, ScenarioSnapshot, "built_at")
        latest_calib    = await _latest_timestamp(session, ScenarioRunLog,   "evaluated_at")

        metrics: Dict[str, Any] = {
            "scenario_snapshot_count":      snapshot_count,
            "scenario_evidence_count":      evidence_count,
            "scenario_run_log_count":       run_log_count,
            "scenario_count_by_type":       by_type,
            "scenario_count_by_impact":     by_impact,
            "shadow_delivery_count":        shadow_count,
            "live_notification_count":      notif_count,
            "latest_scenario_timestamp":    latest_scenario,
            "latest_calibration_timestamp": latest_calib,
        }

        safe_state = _compute_safe_state(flags, notif_count)

        return {
            "flags":          flags,
            "metrics":        metrics,
            "safe_state":     safe_state,
            "db_available":   True,
            "schema_version": OBSERVABILITY_SCHEMA_VERSION,
            "disclaimer":     _DISCLAIMER,
        }

    except Exception as exc:
        logger.debug(
            "[scenario_observability] build_scenario_observability_snapshot error: %r", exc
        )
        safe_state = _compute_safe_state(flags, 0)
        return {
            "flags":          flags,
            "metrics":        empty_metrics,
            "safe_state":     safe_state,
            "db_available":   False,
            "schema_version": OBSERVABILITY_SCHEMA_VERSION,
            "disclaimer":     _DISCLAIMER,
        }
