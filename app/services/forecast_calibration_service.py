"""
Forecast Calibration Service — Phase 12 · Slice 8.

Measures forecast quality over time by recording observed outcomes against
stored forecasts, computing Brier scores and accuracy metrics, and detecting
calibration drift.

Core rule: calibration OBSERVES forecasts and outcomes; it never modifies
any forecast_vector row, conviction field, stance field, or source table.

Immutability invariant
-----------------------
  - record_forecast_outcome() only ever calls add_calibration_log() — an
    insert-only function. No update or delete path exists anywhere in this
    module. This is verified by AST inspection in the validation tests.

Metrics supported
-----------------
  Brier score
    (p_positive_at_forecast - outcome_indicator)²
    where outcome_indicator = 1.0 if positive, 0.0 if negative.
    NULL/skipped when actual_outcome ∈ {neutral, unknown, inconclusive}.

  Hit rate
    Fraction of binary outcomes where the majority-direction forecast
    (p_positive > 0.5) matched the actual outcome.

  Confidence-bucket accuracy
    Outcomes grouped by the confidence_label (low / medium / high) of the
    forecast at evaluation time; hit-rate per bucket.

  Horizon accuracy
    Hit-rate and mean Brier score grouped by horizon_days
    (30 / 90 / 180 = near_term / medium_term / long_term).

  Forecast-type accuracy
    Hit-rate and mean Brier score grouped by forecast_type.

Drift detection
---------------
  Compares mean Brier score in the most-recent window against the prior
  window of the same length. Reports:
    improving   — Brier fell by > DRIFT_THRESHOLD
    worsening   — Brier rose by > DRIFT_THRESHOLD
    stable      — change within ±DRIFT_THRESHOLD
    insufficient_samples — fewer than MIN_SAMPLES in either window

Safety invariants (Phase 12 spec §0 / SP-4)
--------------------------------------------
  - No forecast_vector row is read for mutation or passed to any scoring
    function — only calibration_log rows are read/written.
  - No delivery_ledger, Notification, conviction, stance, or LLM-prompt
    field is read or written.
  - No buy/sell/hold, target price, or recommendation language is present.
  - Null-session safety: every function returns None / {} / [] when session
    is None.
"""

from __future__ import annotations

import logging
import math
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SUPPORTED_OUTCOMES = frozenset({
    "positive", "negative", "neutral", "unknown", "inconclusive",
})
BINARY_OUTCOMES = frozenset({"positive", "negative"})

SUPPORTED_EVALUATION_SOURCES = frozenset({
    "thesis_state_change", "risk_event_observed",
    "watchlist_resolved", "manual_review",
})

# Minimum rows in a window for drift detection to be meaningful
MIN_SAMPLES: int = 5

# Brier score change required to call drift "improving" or "worsening"
DRIFT_THRESHOLD: float = 0.05

# Default rolling window for drift comparison (days)
DEFAULT_DRIFT_WINDOW_DAYS: int = 30

CALIBRATION_SCHEMA_VERSION: int = 1


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Brier score calculation
# ---------------------------------------------------------------------------

def calculate_brier_score(
    p_positive_at_forecast: float,
    actual_outcome: str,
) -> Optional[float]:
    """Compute the Brier score for one forecast/outcome pair.

    Returns (p_positive - indicator)² where indicator = 1.0 for "positive",
    0.0 for "negative".  Returns None for neutral / unknown / inconclusive
    outcomes (no binary indicator available).

    Raises ValueError for unknown outcome strings or invalid probabilities.
    """
    if actual_outcome not in SUPPORTED_OUTCOMES:
        raise ValueError(
            f"Unknown actual_outcome {actual_outcome!r}. "
            f"Supported: {sorted(SUPPORTED_OUTCOMES)}"
        )
    if not (0.0 <= p_positive_at_forecast <= 1.0):
        raise ValueError(
            f"p_positive_at_forecast must be in [0, 1], got {p_positive_at_forecast}"
        )
    if actual_outcome not in BINARY_OUTCOMES:
        return None
    indicator = 1.0 if actual_outcome == "positive" else 0.0
    return round((p_positive_at_forecast - indicator) ** 2, 6)


# ---------------------------------------------------------------------------
# Outcome recording (append-only)
# ---------------------------------------------------------------------------

async def record_forecast_outcome(
    session,
    *,
    forecast_id: str,
    entity_type: str,
    entity_key: str,
    horizon: str,
    forecast_type: str,
    p_positive_at_forecast: float,
    p_negative_at_forecast: float,
    p_neutral_at_forecast: float,
    actual_outcome: str,
    evaluation_source: str,
    evaluated_at: Optional[datetime] = None,
    evaluator_notes: Optional[str] = None,
    user_id: Optional[str] = None,
) -> Optional[object]:
    """Append one immutable calibration log row.

    The Brier score is computed here and stored alongside the raw probabilities
    so downstream aggregation never needs to re-derive it.

    Returns the new ForecastCalibrationLog ORM row, or None when session is
    None or an error occurs.  Never updates an existing row.
    """
    if session is None:
        return None
    try:
        brier = calculate_brier_score(p_positive_at_forecast, actual_outcome)
        from app.db.repositories.forecast_repo import add_calibration_log
        return await add_calibration_log(
            session,
            forecast_id=forecast_id,
            entity_type=entity_type,
            entity_key=entity_key,
            horizon=horizon,
            forecast_type=forecast_type,
            p_positive_at_forecast=p_positive_at_forecast,
            p_negative_at_forecast=p_negative_at_forecast,
            p_neutral_at_forecast=p_neutral_at_forecast,
            actual_outcome=actual_outcome,
            brier_score=brier,
            evaluation_source=evaluation_source,
            evaluated_at=evaluated_at,
            evaluator_notes=evaluator_notes,
            user_id=user_id,
        )
    except Exception as exc:
        logger.debug("[forecast_calibration_service] record_forecast_outcome error: %r", exc)
        return None


# ---------------------------------------------------------------------------
# Core metric helpers (pure)
# ---------------------------------------------------------------------------

def _mean(values: List[float]) -> Optional[float]:
    if not values:
        return None
    return round(sum(values) / len(values), 6)


def _hit_rate(logs: List[object]) -> Optional[float]:
    """Fraction of binary-outcome rows where the majority direction matched."""
    hits = 0
    total = 0
    for row in logs:
        outcome = getattr(row, "actual_outcome", None)
        if outcome not in BINARY_OUTCOMES:
            continue
        p_pos = float(getattr(row, "p_positive_at_forecast", 0.33))
        predicted_positive = p_pos >= 0.5
        actual_positive = outcome == "positive"
        if predicted_positive == actual_positive:
            hits += 1
        total += 1
    if total == 0:
        return None
    return round(hits / total, 6)


def _infer_confidence_label(row) -> str:
    """Infer a confidence label from brier_score / p_positive as a proxy.

    In the absence of a stored confidence_label column on
    forecast_calibration_log, we use the brier_score as a proxy:
      brier < 0.10 → high
      brier < 0.20 → medium
      else         → low
    When brier_score is None (non-binary outcome) we fall back to "unknown".
    """
    brier = getattr(row, "brier_score", None)
    if brier is None:
        return "unknown"
    if brier < 0.10:
        return "high"
    if brier < 0.20:
        return "medium"
    return "low"


# ---------------------------------------------------------------------------
# Calibration metrics
# ---------------------------------------------------------------------------

async def calculate_calibration_metrics(
    session,
    *,
    entity_type: Optional[str] = None,
    entity_key: Optional[str] = None,
    forecast_type: Optional[str] = None,
    horizon: Optional[str] = None,
    evaluated_after: Optional[datetime] = None,
    limit: int = 1000,
) -> Dict:
    """Compute calibration metrics over matching calibration log rows.

    Returns a dict:
      {
        "sample_count":       int,
        "binary_count":       int,    # rows with positive/negative outcome
        "mean_brier_score":   float | None,
        "hit_rate":           float | None,
        "by_confidence":      {"high": {...}, "medium": {...}, "low": {...}},
        "by_horizon":         {"near_term": {...}, "medium_term": {...}, "long_term": {...}},
        "by_forecast_type":   {type: {...}},
        "calibration_schema": int,
      }

    Returns {} when session is None or on error.
    """
    if session is None:
        return {}
    try:
        from app.db.repositories.forecast_repo import list_calibration_logs

        logs = await list_calibration_logs(
            session,
            entity_type=entity_type,
            entity_key=entity_key,
            forecast_type=forecast_type,
            horizon=horizon,
            evaluated_after=evaluated_after,
            limit=limit,
        )

        binary_logs = [r for r in logs if getattr(r, "actual_outcome", None) in BINARY_OUTCOMES]
        brier_values = [
            float(getattr(r, "brier_score", 0.0))
            for r in binary_logs
            if getattr(r, "brier_score", None) is not None
        ]

        by_confidence: Dict[str, Dict] = {}
        for row in binary_logs:
            label = _infer_confidence_label(row)
            bucket = by_confidence.setdefault(label, {"hits": 0, "total": 0, "brier_sum": 0.0})
            outcome = getattr(row, "actual_outcome", None)
            p_pos = float(getattr(row, "p_positive_at_forecast", 0.33))
            predicted_pos = p_pos >= 0.5
            actual_pos = outcome == "positive"
            if predicted_pos == actual_pos:
                bucket["hits"] += 1
            bucket["total"] += 1
            bs = getattr(row, "brier_score", None)
            if bs is not None:
                bucket["brier_sum"] += float(bs)
        confidence_summary = {
            label: {
                "hit_rate": round(b["hits"] / b["total"], 6) if b["total"] else None,
                "mean_brier_score": round(b["brier_sum"] / b["total"], 6) if b["total"] else None,
                "count": b["total"],
            }
            for label, b in by_confidence.items()
        }

        by_horizon: Dict[str, Dict] = {}
        for row in binary_logs:
            hz = getattr(row, "horizon", "unknown") or "unknown"
            bucket = by_horizon.setdefault(hz, {"hits": 0, "total": 0, "brier_sum": 0.0})
            outcome = getattr(row, "actual_outcome", None)
            p_pos = float(getattr(row, "p_positive_at_forecast", 0.33))
            if (p_pos >= 0.5) == (outcome == "positive"):
                bucket["hits"] += 1
            bucket["total"] += 1
            bs = getattr(row, "brier_score", None)
            if bs is not None:
                bucket["brier_sum"] += float(bs)
        horizon_summary = {
            hz: {
                "hit_rate": round(b["hits"] / b["total"], 6) if b["total"] else None,
                "mean_brier_score": round(b["brier_sum"] / b["total"], 6) if b["total"] else None,
                "count": b["total"],
            }
            for hz, b in by_horizon.items()
        }

        by_type: Dict[str, Dict] = {}
        for row in binary_logs:
            ft = getattr(row, "forecast_type", "unknown") or "unknown"
            bucket = by_type.setdefault(ft, {"hits": 0, "total": 0, "brier_sum": 0.0})
            outcome = getattr(row, "actual_outcome", None)
            p_pos = float(getattr(row, "p_positive_at_forecast", 0.33))
            if (p_pos >= 0.5) == (outcome == "positive"):
                bucket["hits"] += 1
            bucket["total"] += 1
            bs = getattr(row, "brier_score", None)
            if bs is not None:
                bucket["brier_sum"] += float(bs)
        type_summary = {
            ft: {
                "hit_rate": round(b["hits"] / b["total"], 6) if b["total"] else None,
                "mean_brier_score": round(b["brier_sum"] / b["total"], 6) if b["total"] else None,
                "count": b["total"],
            }
            for ft, b in by_type.items()
        }

        return {
            "sample_count": len(logs),
            "binary_count": len(binary_logs),
            "mean_brier_score": _mean(brier_values),
            "hit_rate": _hit_rate(binary_logs),
            "by_confidence": confidence_summary,
            "by_horizon": horizon_summary,
            "by_forecast_type": type_summary,
            "calibration_schema": CALIBRATION_SCHEMA_VERSION,
        }
    except Exception as exc:
        logger.debug(
            "[forecast_calibration_service] calculate_calibration_metrics error: %r", exc
        )
        return {}


# ---------------------------------------------------------------------------
# Drift detection
# ---------------------------------------------------------------------------

async def calculate_forecast_drift(
    session,
    *,
    window_days: int = DEFAULT_DRIFT_WINDOW_DAYS,
    entity_type: Optional[str] = None,
    forecast_type: Optional[str] = None,
) -> Dict:
    """Detect calibration drift by comparing two consecutive time windows.

    Splits the calibration log into:
      - recent window:  evaluated_at ∈ (now - window_days, now]
      - prior window:   evaluated_at ∈ (now - 2×window_days, now - window_days]

    Returns:
      {
        "trend":           "improving" | "worsening" | "stable" | "insufficient_samples",
        "recent_brier":    float | None,
        "prior_brier":     float | None,
        "delta_brier":     float | None,   # recent - prior (negative = improving)
        "recent_count":    int,
        "prior_count":     int,
        "min_samples":     int,
        "window_days":     int,
      }

    Returns {} when session is None or on error.
    """
    if session is None:
        return {}
    try:
        from app.db.repositories.forecast_repo import list_calibration_logs

        now = _now()
        recent_after = now - timedelta(days=window_days)
        prior_after  = now - timedelta(days=2 * window_days)

        recent_logs = await list_calibration_logs(
            session,
            entity_type=entity_type,
            forecast_type=forecast_type,
            evaluated_after=recent_after,
            limit=2000,
        )
        all_prior_logs = await list_calibration_logs(
            session,
            entity_type=entity_type,
            forecast_type=forecast_type,
            evaluated_after=prior_after,
            limit=2000,
        )
        # prior window = rows in all_prior_logs whose evaluated_at < recent_after
        prior_logs = [
            r for r in all_prior_logs
            if _row_evaluated_before(r, recent_after)
        ]

        recent_brier_vals = _brier_values(recent_logs)
        prior_brier_vals  = _brier_values(prior_logs)

        recent_brier = _mean(recent_brier_vals)
        prior_brier  = _mean(prior_brier_vals)

        recent_count = len(recent_logs)
        prior_count  = len(prior_logs)

        if recent_count < MIN_SAMPLES or prior_count < MIN_SAMPLES:
            trend = "insufficient_samples"
            delta = None
        else:
            assert recent_brier is not None and prior_brier is not None
            delta = round(recent_brier - prior_brier, 6)
            if delta <= -DRIFT_THRESHOLD:
                trend = "improving"
            elif delta >= DRIFT_THRESHOLD:
                trend = "worsening"
            else:
                trend = "stable"

        return {
            "trend":         trend,
            "recent_brier":  recent_brier,
            "prior_brier":   prior_brier,
            "delta_brier":   delta,
            "recent_count":  recent_count,
            "prior_count":   prior_count,
            "min_samples":   MIN_SAMPLES,
            "window_days":   window_days,
        }
    except Exception as exc:
        logger.debug(
            "[forecast_calibration_service] calculate_forecast_drift error: %r", exc
        )
        return {}


def _row_evaluated_before(row, cutoff: datetime) -> bool:
    ev = getattr(row, "evaluated_at", None)
    if ev is None:
        return False
    if ev.tzinfo is None:
        ev = ev.replace(tzinfo=timezone.utc)
    if cutoff.tzinfo is None:
        cutoff = cutoff.replace(tzinfo=timezone.utc)
    return ev < cutoff


def _brier_values(logs: List[object]) -> List[float]:
    return [
        float(getattr(r, "brier_score", 0.0))
        for r in logs
        if getattr(r, "brier_score", None) is not None
        and getattr(r, "actual_outcome", None) in BINARY_OUTCOMES
    ]


# ---------------------------------------------------------------------------
# Calibration summary
# ---------------------------------------------------------------------------

async def summarize_calibration(
    session,
    *,
    window_days: int = DEFAULT_DRIFT_WINDOW_DAYS,
) -> Dict:
    """Build a top-level calibration summary combining metrics and drift.

    Always returns a well-formed dict, even when session is None or no
    calibration data exists yet (safe empty state).

    Shape:
      {
        "total_outcomes_recorded": int,
        "metrics":   <calculate_calibration_metrics output>,
        "drift":     <calculate_forecast_drift output>,
        "calibration_schema": int,
      }
    """
    empty = {
        "total_outcomes_recorded": 0,
        "metrics": {},
        "drift": {},
        "calibration_schema": CALIBRATION_SCHEMA_VERSION,
    }
    if session is None:
        return empty
    try:
        from app.db.repositories.forecast_repo import count_calibration_logs

        total = await count_calibration_logs(session)
        metrics = await calculate_calibration_metrics(session)
        drift   = await calculate_forecast_drift(session, window_days=window_days)
        return {
            "total_outcomes_recorded": total,
            "metrics":  metrics,
            "drift":    drift,
            "calibration_schema": CALIBRATION_SCHEMA_VERSION,
        }
    except Exception as exc:
        logger.debug(
            "[forecast_calibration_service] summarize_calibration error: %r", exc
        )
        return empty
