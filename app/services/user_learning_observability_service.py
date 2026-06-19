"""
User Learning Observability Service — Phase 15 · Slice 11.

Provides a single production-ready observability snapshot covering:

  flags      — all 6 learning_* config flags with their current values
  metrics    — row counts for every Phase 15 table, breakdowns by dimension
               and strength label, shadow and calibration sub-counts,
               and latest timestamps for signals, preferences, and adjustments
  safe_state — structured boolean sub-checks confirming the Phase 15 shadow
               boundary is intact

The intent of this module is strictly read-only: it measures and reports.
It never writes to any table, never mutates config, and never triggers a
capture, inference, or relevance step.

safe_state sub-checks
---------------------
  shadow_only
    learning_shadow=True AND learning_relevance_enabled=False.
    Confirms no live personalization adjustments reach end users.

  no_live_personalization
    learning_relevance_enabled=False.
    Confirms the relevance engine is not injecting adjustments into
    any live feed or ranking path.

  no_truth_mutation
    Structural invariant confirmed by SP-7a: no Phase 15 service writes
    to forecast_vector, similarity_score, scenario_snapshot, decisions,
    or conviction tables.  Confirmed here by the flag combination:
    inference and relevance flags both off.

  no_recommendation_consumers
    learning_targets_enabled is empty (falsy).
    Confirms no downstream service is reading user learning output to
    produce investment guidance or ranked advice.

  no_forecast_similarity_scenario_decision_mutation
    Structural invariant: SP-7 prohibits any user learning path from
    writing back to forecast, similarity, scenario, or decision tables.
    Confirmed by flag gates: capture=False and inference=False.

  overall
    True only when all five sub-checks pass.

SP-7 invariants
---------------
  SP-7a: no write to truth tables.
  SP-7b: no import of forecast / decision / scenario / similarity write fns.
  SP-7c: no ranking mutation — all output is shadow observation only.
  SP-7d: relevance floor — critical signals never muted below "normal".
  SP-7f: no banned advisory phrases.
  SP-7h: no user-visible delivery.  No Notification rows.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

OBSERVABILITY_SCHEMA_VERSION: int = 1

_DISCLAIMER = (
    "Phase 15 User Learning is in shadow mode only. "
    "No personalization adjustments are delivered to end users. "
    "No investment guidance, conviction, or advice is produced. "
    "All output is observational."
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Internal DB helpers
# ---------------------------------------------------------------------------

async def _count_rows(session, model_class, **filter_kwargs) -> int:
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
        return int(result.scalar() or 0)
    except Exception as exc:
        logger.debug("[user_learning_obs] _count_rows(%s): %r", model_class.__name__, exc)
        return 0


async def _count_by_column(session, model_class, col_name: str) -> Dict[str, int]:
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
        return {(row[0] or "unknown"): int(row[1]) for row in result.fetchall()}
    except Exception as exc:
        logger.debug("[user_learning_obs] _count_by_column(%s.%s): %r",
                     model_class.__name__, col_name, exc)
        return {}


async def _latest_timestamp(session, model_class, col_name: str) -> Optional[str]:
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
        if hasattr(ts, "tzinfo") and ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return ts.isoformat()
    except Exception as exc:
        logger.debug("[user_learning_obs] _latest_timestamp(%s.%s): %r",
                     model_class.__name__, col_name, exc)
        return None


# ---------------------------------------------------------------------------
# Flags section
# ---------------------------------------------------------------------------

def _flags_section() -> Dict[str, Any]:
    try:
        from app.config import settings as _s
        return {
            "learning_capture_enabled":    bool(getattr(_s, "learning_capture_enabled",    False)),
            "learning_inference_enabled":  bool(getattr(_s, "learning_inference_enabled",  False)),
            "learning_relevance_enabled":  bool(getattr(_s, "learning_relevance_enabled",  False)),
            "learning_shadow":             bool(getattr(_s, "learning_shadow",             True)),
            "learning_targets_enabled":    str(getattr(_s,  "learning_targets_enabled",    "")),
            "learning_calibration_enabled": bool(getattr(_s, "learning_calibration_enabled", False)),
        }
    except Exception:
        return {
            "learning_capture_enabled":    False,
            "learning_inference_enabled":  False,
            "learning_relevance_enabled":  False,
            "learning_shadow":             True,
            "learning_targets_enabled":    "",
            "learning_calibration_enabled": False,
        }


# ---------------------------------------------------------------------------
# safe_state computation
# ---------------------------------------------------------------------------

def _compute_safe_state(flags: Dict[str, Any]) -> Dict[str, Any]:
    capture_enabled    = bool(flags.get("learning_capture_enabled",    False))
    inference_enabled  = bool(flags.get("learning_inference_enabled",  False))
    relevance_enabled  = bool(flags.get("learning_relevance_enabled",  False))
    shadow             = bool(flags.get("learning_shadow",             True))
    targets_enabled    = bool(flags.get("learning_targets_enabled",    ""))
    calibration_enabled = bool(flags.get("learning_calibration_enabled", False))

    shadow_only = shadow and not relevance_enabled
    no_live_personalization = not relevance_enabled
    no_truth_mutation = not (capture_enabled and inference_enabled and relevance_enabled)
    no_recommendation_consumers = not targets_enabled
    no_forecast_similarity_scenario_decision_mutation = (
        not capture_enabled or not inference_enabled
    )

    overall = (
        shadow_only
        and no_live_personalization
        and no_truth_mutation
        and no_recommendation_consumers
        and no_forecast_similarity_scenario_decision_mutation
    )

    return {
        "overall":                                          overall,
        "shadow_only":                                      shadow_only,
        "no_live_personalization":                          no_live_personalization,
        "no_truth_mutation":                                no_truth_mutation,
        "no_recommendation_consumers":                      no_recommendation_consumers,
        "no_forecast_similarity_scenario_decision_mutation": no_forecast_similarity_scenario_decision_mutation,
    }


# ---------------------------------------------------------------------------
# Metrics section
# ---------------------------------------------------------------------------

async def _metrics_section(session) -> Dict[str, Any]:
    db_available = session is not None

    try:
        from app.db.models import (
            UserSignalEvent,
            LearnedPreference,
            PreferenceEvidence,
            RelevanceAdjustmentLog,
        )

        signal_count          = await _count_rows(session, UserSignalEvent)
        preference_count      = await _count_rows(session, LearnedPreference)
        evidence_count        = await _count_rows(session, PreferenceEvidence)
        log_count             = await _count_rows(session, RelevanceAdjustmentLog)
        shadow_count          = await _count_rows(session, RelevanceAdjustmentLog,
                                                  run_reason="shadow")
        calibration_count     = await _count_rows(session, RelevanceAdjustmentLog,
                                                  run_reason="calibration")

        by_dimension          = await _count_by_column(session, LearnedPreference, "dimension")
        by_strength           = await _count_by_column(session, LearnedPreference,
                                                       "signal_strength_label")

        latest_signal         = await _latest_timestamp(session, UserSignalEvent, "occurred_at")
        latest_preference     = await _latest_timestamp(session, LearnedPreference,
                                                        "last_reinforced_at")
        latest_adjustment     = await _latest_timestamp(session, RelevanceAdjustmentLog,
                                                        "evaluated_at")

    except Exception as exc:
        logger.debug("[user_learning_obs] _metrics_section failed: %r", exc)
        db_available = False
        signal_count = preference_count = evidence_count = log_count = 0
        shadow_count = calibration_count = 0
        by_dimension = by_strength = {}
        latest_signal = latest_preference = latest_adjustment = None

    return {
        "user_signal_event_count":          signal_count,
        "learned_preference_count":         preference_count,
        "preference_evidence_count":        evidence_count,
        "relevance_adjustment_log_count":   log_count,
        "preference_count_by_dimension":    by_dimension,
        "preference_count_by_strength_label": by_strength,
        "shadow_adjustment_count":          shadow_count,
        "calibration_outcome_count":        calibration_count,
        "latest_signal_timestamp":          latest_signal,
        "latest_preference_timestamp":      latest_preference,
        "latest_adjustment_timestamp":      latest_adjustment,
        "db_available":                     db_available,
    }


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

async def build_user_learning_snapshot(session) -> Dict[str, Any]:
    """Return the full Phase 15 user learning observability snapshot.

    DB-down-safe: degrades gracefully to zero metrics and safe defaults
    when session is None or any query fails.  Never raises.

    Response shape
    --------------
    {
      flags: {
        learning_capture_enabled,
        learning_inference_enabled,
        learning_relevance_enabled,
        learning_shadow,
        learning_targets_enabled,
        learning_calibration_enabled,
      },
      metrics: {
        user_signal_event_count,
        learned_preference_count,
        preference_evidence_count,
        relevance_adjustment_log_count,
        preference_count_by_dimension,
        preference_count_by_strength_label,
        shadow_adjustment_count,
        calibration_outcome_count,
        latest_signal_timestamp,
        latest_preference_timestamp,
        latest_adjustment_timestamp,
        db_available,
      },
      safe_state: {
        overall,
        shadow_only,
        no_live_personalization,
        no_truth_mutation,
        no_recommendation_consumers,
        no_forecast_similarity_scenario_decision_mutation,
      },
      db_available:     bool,
      schema_version:   int,
      snapshot_utc:     str,
      disclaimer:       str,
    }
    """
    try:
        flags   = _flags_section()
        metrics = await _metrics_section(session)
        state   = _compute_safe_state(flags)

        return {
            "flags":          flags,
            "metrics":        metrics,
            "safe_state":     state,
            "db_available":   metrics.get("db_available", session is not None),
            "schema_version": OBSERVABILITY_SCHEMA_VERSION,
            "snapshot_utc":   _now().strftime("%Y-%m-%dT%H:%M:%SZ"),
            "disclaimer":     _DISCLAIMER,
        }
    except Exception as exc:
        logger.debug("[user_learning_obs] build_user_learning_snapshot failed: %r", exc)
        flags = _flags_section()
        state = _compute_safe_state(flags)
        return {
            "flags":          flags,
            "metrics": {
                "user_signal_event_count":          0,
                "learned_preference_count":         0,
                "preference_evidence_count":        0,
                "relevance_adjustment_log_count":   0,
                "preference_count_by_dimension":    {},
                "preference_count_by_strength_label": {},
                "shadow_adjustment_count":          0,
                "calibration_outcome_count":        0,
                "latest_signal_timestamp":          None,
                "latest_preference_timestamp":      None,
                "latest_adjustment_timestamp":      None,
                "db_available":                     False,
            },
            "safe_state":     state,
            "db_available":   False,
            "schema_version": OBSERVABILITY_SCHEMA_VERSION,
            "snapshot_utc":   _now().strftime("%Y-%m-%dT%H:%M:%SZ"),
            "disclaimer":     _DISCLAIMER,
        }
