"""
User Learning Calibration Service — Phase 15 · Slice 10.

Measures preference quality by comparing learned preferences against
observed engagement outcomes.  All functions are observational only —
they compute metrics from evidence already in the log and in
learned_preference rows.  Nothing in this module modifies preferences,
signal events, forecasts, or any truth table.

Storage
-------
record_preference_outcome appends one row to relevance_adjustment_log
(run_reason="calibration").  No other writes.

Metrics
-------
  accuracy             — fraction of calibration outcomes that were engaged
  drift                — mean(1 − confidence) across active preferences
  false_preference_rate — fraction of boosted outcomes that were not engaged
  stability            — mean(confidence) across active preferences

All metric functions return a dict with a "sufficient_samples" key.
When the evidence count falls below the minimum required, the metric
value is None and sufficient_samples=False.

Flag gate
---------
All async public functions are gated on learning_inference_enabled
(default False).  When off they return None or {}.

Null-session contract
---------------------
All async public functions return None / {} when session=None.

SP-7 invariants
---------------
  SP-7a: no write to truth tables.
  SP-7b: no import of forecast / decision / scenario / similarity write fns.
  SP-7c: no preference mutation — learned_preference rows are never touched.
  SP-7f: no banned advisory phrases.
  SP-7h: no user-visible delivery.  No Notification rows.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MIN_ACCURACY_SAMPLES:  int   = 5
_MIN_DRIFT_SAMPLES:     int   = 2
_MIN_FPR_SAMPLES:       int   = 3
_MIN_STABILITY_SAMPLES: int   = 2
_CALIBRATION_RUN_REASON: str  = "calibration"
_CALIBRATION_SCHEMA:    int   = 1
_ENGAGED_WEIGHT:        float = 1.0
_IGNORED_WEIGHT:        float = -1.0


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _calib_enabled(override: Optional[bool] = None) -> bool:
    if override is not None:
        return bool(override)
    try:
        from app.config import settings
        return bool(getattr(settings, "learning_inference_enabled", False))
    except Exception:
        return False


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _attr(obj: Any, name: str, default: Any = None) -> Any:
    val = getattr(obj, name, None)
    return val if val is not None else default


def _empty_accuracy(user_id: str, dimension: Any, entity_key: Any) -> Dict[str, Any]:
    return {
        "user_id":            user_id,
        "dimension":          dimension,
        "entity_key":         entity_key,
        "accuracy":           None,
        "engaged_count":      0,
        "not_engaged_count":  0,
        "total_count":        0,
        "sufficient_samples": False,
        "min_samples":        _MIN_ACCURACY_SAMPLES,
    }


def _empty_drift(user_id: str, dimension: Any) -> Dict[str, Any]:
    return {
        "user_id":            user_id,
        "dimension":          dimension,
        "drift_score":        None,
        "preference_count":   0,
        "sufficient_samples": False,
    }


def _empty_fpr(user_id: str, dimension: Any) -> Dict[str, Any]:
    return {
        "user_id":               user_id,
        "dimension":             dimension,
        "false_preference_rate": None,
        "false_count":           0,
        "boosted_total":         0,
        "sufficient_samples":    False,
        "min_samples":           _MIN_FPR_SAMPLES,
    }


def _empty_stability(user_id: str, dimension: Any) -> Dict[str, Any]:
    return {
        "user_id":            user_id,
        "dimension":          dimension,
        "stability_score":    None,
        "preference_count":   0,
        "sufficient_samples": False,
    }


def _empty_summary(user_id: str) -> Dict[str, Any]:
    return {
        "user_id":               user_id,
        "accuracy":              _empty_accuracy(user_id, None, None),
        "drift":                 _empty_drift(user_id, None),
        "false_preference_rate": _empty_fpr(user_id, None),
        "stability":             _empty_stability(user_id, None),
        "calibration_schema":    _CALIBRATION_SCHEMA,
        "generated_at":          _now().isoformat(),
    }


# ---------------------------------------------------------------------------
# Public async functions
# ---------------------------------------------------------------------------

async def record_preference_outcome(
    session,
    *,
    user_id: str,
    surface: str,
    item_ref: str,
    adjusted_rank: int,
    intrinsic_rank: int,
    observed_engagement: bool,
    run_override: Optional[bool] = None,
) -> Optional[Any]:
    """Append one calibration outcome observation to relevance_adjustment_log.

    observed_engagement=True records a positive outcome (relevance_weight=1.0).
    observed_engagement=False records a negative outcome (relevance_weight=-1.0).

    All rows are written with run_reason="calibration".
    Returns the ORM row, or None when the flag is off or session is None.
    """
    if not _calib_enabled(run_override):
        return None
    if session is None:
        return None
    try:
        from app.db.repositories.user_learning_repo import add_relevance_adjustment_log

        weight = _ENGAGED_WEIGHT if observed_engagement else _IGNORED_WEIGHT
        return await add_relevance_adjustment_log(
            session,
            user_id          = user_id,
            surface          = surface,
            run_reason       = _CALIBRATION_RUN_REASON,
            item_ref         = item_ref,
            intrinsic_rank   = intrinsic_rank,
            adjusted_rank    = adjusted_rank,
            relevance_weight = weight,
            prominence_tier  = "normal",
            floor_applied    = False,
        )
    except Exception as exc:
        logger.debug("[calibration] record_preference_outcome failed: %r", exc)
        return None


async def calculate_preference_accuracy(
    session,
    *,
    user_id: str,
    dimension: Optional[str] = None,
    entity_key: Optional[str] = None,
    run_override: Optional[bool] = None,
) -> Dict[str, Any]:
    """Compute accuracy: fraction of calibration observations that were engaged.

    Reads relevance_adjustment_log rows with run_reason="calibration".
    Engaged rows have relevance_weight > 0; non-engaged rows have weight <= 0.

    Returns a dict with accuracy (None if insufficient evidence),
    engaged_count, not_engaged_count, total_count, sufficient_samples,
    and min_samples.
    """
    if not _calib_enabled(run_override):
        return _empty_accuracy(user_id, dimension, entity_key)
    if session is None:
        return _empty_accuracy(user_id, dimension, entity_key)
    try:
        from app.db.repositories.user_learning_repo import list_relevance_adjustment_logs

        rows = await list_relevance_adjustment_logs(
            session,
            user_id    = user_id,
            run_reason = _CALIBRATION_RUN_REASON,
            limit      = 5000,
        )

        engaged_count     = sum(1 for r in rows if float(_attr(r, "relevance_weight", 0) or 0) > 0)
        not_engaged_count = len(rows) - engaged_count
        total_count       = len(rows)

        if total_count < _MIN_ACCURACY_SAMPLES:
            return _empty_accuracy(user_id, dimension, entity_key)

        return {
            "user_id":            user_id,
            "dimension":          dimension,
            "entity_key":         entity_key,
            "accuracy":           round(engaged_count / total_count, 4),
            "engaged_count":      engaged_count,
            "not_engaged_count":  not_engaged_count,
            "total_count":        total_count,
            "sufficient_samples": True,
            "min_samples":        _MIN_ACCURACY_SAMPLES,
        }
    except Exception as exc:
        logger.debug("[calibration] calculate_preference_accuracy failed: %r", exc)
        return _empty_accuracy(user_id, dimension, entity_key)


async def calculate_preference_drift(
    session,
    *,
    user_id: str,
    dimension: Optional[str] = None,
    run_override: Optional[bool] = None,
) -> Dict[str, Any]:
    """Compute drift: mean(1 − confidence) across active learned preferences.

    Higher drift means preferences are based on mixed or weak evidence.
    Range: 0 (all confidence=1.0, no drift) to 1 (all confidence=0.0, full drift).

    Falsified preferences are excluded.  Returns a dict with drift_score
    (None if insufficient), preference_count, and sufficient_samples.
    """
    if not _calib_enabled(run_override):
        return _empty_drift(user_id, dimension)
    if session is None:
        return _empty_drift(user_id, dimension)
    try:
        from app.db.repositories.user_learning_repo import list_learned_preferences

        all_prefs = await list_learned_preferences(
            session,
            user_id   = user_id,
            dimension = dimension,
            limit     = 1000,
        )
        active = [p for p in all_prefs if _attr(p, "status", "") != "falsified"]

        if len(active) < _MIN_DRIFT_SAMPLES:
            return _empty_drift(user_id, dimension)

        drift_score = sum(
            1.0 - float(_attr(p, "confidence", 0.0) or 0.0)
            for p in active
        ) / len(active)

        return {
            "user_id":            user_id,
            "dimension":          dimension,
            "drift_score":        round(drift_score, 4),
            "preference_count":   len(active),
            "sufficient_samples": True,
        }
    except Exception as exc:
        logger.debug("[calibration] calculate_preference_drift failed: %r", exc)
        return _empty_drift(user_id, dimension)


async def calculate_false_preference_rate(
    session,
    *,
    user_id: str,
    dimension: Optional[str] = None,
    run_override: Optional[bool] = None,
) -> Dict[str, Any]:
    """Compute false preference rate: fraction of boosted outcomes not engaged.

    A "boosted" outcome is one where adjusted_rank < intrinsic_rank
    (personalization moved the item up in the feed).  A false positive is
    a boosted outcome where the user did not engage (relevance_weight <= 0).

    Returns a dict with false_preference_rate (None if insufficient boosted
    samples), false_count, boosted_total, sufficient_samples, and min_samples.
    """
    if not _calib_enabled(run_override):
        return _empty_fpr(user_id, dimension)
    if session is None:
        return _empty_fpr(user_id, dimension)
    try:
        from app.db.repositories.user_learning_repo import list_relevance_adjustment_logs

        rows = await list_relevance_adjustment_logs(
            session,
            user_id    = user_id,
            run_reason = _CALIBRATION_RUN_REASON,
            limit      = 5000,
        )

        boosted = [
            r for r in rows
            if int(_attr(r, "adjusted_rank", 0) or 0) < int(_attr(r, "intrinsic_rank", 0) or 0)
        ]

        if len(boosted) < _MIN_FPR_SAMPLES:
            return _empty_fpr(user_id, dimension)

        false_count = sum(
            1 for r in boosted
            if float(_attr(r, "relevance_weight", 0) or 0) <= 0
        )

        return {
            "user_id":               user_id,
            "dimension":             dimension,
            "false_preference_rate": round(false_count / len(boosted), 4),
            "false_count":           false_count,
            "boosted_total":         len(boosted),
            "sufficient_samples":    True,
            "min_samples":           _MIN_FPR_SAMPLES,
        }
    except Exception as exc:
        logger.debug("[calibration] calculate_false_preference_rate failed: %r", exc)
        return _empty_fpr(user_id, dimension)


async def calculate_preference_stability(
    session,
    *,
    user_id: str,
    dimension: Optional[str] = None,
    run_override: Optional[bool] = None,
) -> Dict[str, Any]:
    """Compute stability: mean confidence across active learned preferences.

    Higher stability means preferences are based on consistent, strong evidence.
    Range: 0 (all confidence=0.0, unstable) to 1 (all confidence=1.0, fully stable).

    Falsified preferences are excluded.  Returns a dict with stability_score
    (None if insufficient), preference_count, and sufficient_samples.
    """
    if not _calib_enabled(run_override):
        return _empty_stability(user_id, dimension)
    if session is None:
        return _empty_stability(user_id, dimension)
    try:
        from app.db.repositories.user_learning_repo import list_learned_preferences

        all_prefs = await list_learned_preferences(
            session,
            user_id   = user_id,
            dimension = dimension,
            limit     = 1000,
        )
        active = [p for p in all_prefs if _attr(p, "status", "") != "falsified"]

        if len(active) < _MIN_STABILITY_SAMPLES:
            return _empty_stability(user_id, dimension)

        stability = sum(
            float(_attr(p, "confidence", 0.0) or 0.0)
            for p in active
        ) / len(active)

        return {
            "user_id":            user_id,
            "dimension":          dimension,
            "stability_score":    round(stability, 4),
            "preference_count":   len(active),
            "sufficient_samples": True,
        }
    except Exception as exc:
        logger.debug("[calibration] calculate_preference_stability failed: %r", exc)
        return _empty_stability(user_id, dimension)


async def summarize_preference_calibration(
    session,
    *,
    user_id: str,
    run_override: Optional[bool] = None,
) -> Dict[str, Any]:
    """Return a full calibration summary for one user.

    Calls all four metric functions and bundles the results.  The summary is
    always structurally complete even when evidence is insufficient or the
    flag is off.

    Returns a dict with keys: user_id, accuracy, drift, false_preference_rate,
    stability, calibration_schema, generated_at.
    """
    if not _calib_enabled(run_override):
        return _empty_summary(user_id)
    if session is None:
        return _empty_summary(user_id)
    try:
        accuracy  = await calculate_preference_accuracy(
            session, user_id=user_id, run_override=run_override,
        )
        drift     = await calculate_preference_drift(
            session, user_id=user_id, run_override=run_override,
        )
        fpr       = await calculate_false_preference_rate(
            session, user_id=user_id, run_override=run_override,
        )
        stability = await calculate_preference_stability(
            session, user_id=user_id, run_override=run_override,
        )
        return {
            "user_id":               user_id,
            "accuracy":              accuracy,
            "drift":                 drift,
            "false_preference_rate": fpr,
            "stability":             stability,
            "calibration_schema":    _CALIBRATION_SCHEMA,
            "generated_at":          _now().isoformat(),
        }
    except Exception as exc:
        logger.debug("[calibration] summarize_preference_calibration failed: %r", exc)
        return _empty_summary(user_id)
