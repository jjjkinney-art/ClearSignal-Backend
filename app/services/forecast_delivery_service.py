"""
Forecast Shadow Delivery — Phase 12 · Slice 7.

Detects transitions in forecast vectors (probability shifts, new forecasts,
disappeared forecasts) and journals each as a deduped, shadow-only entry in
the existing delivery_ledger — reusing the Phase 10A idempotency machinery
wholesale rather than inventing a parallel dedup mechanism.

Scope boundaries (hard):
  - Steady-state forecasts (no material transition) are NEVER journaled.
    Re-running against an unchanged set of vectors produces zero ledger writes.
  - This module NEVER marks a ledger row "delivered" and NEVER creates a
    Notification row.  Rows land as channel="forecast_shadow", status "pending"
    (delivery_create's default) and are never drained by any existing flush
    pipeline — there is no consumer registered for this channel.  That is what
    makes this genuinely inert / not user-visible.
  - Nothing here writes to any source table (company_dossier, dossier_*,
    thesis_versions, historical_analogs, similarity_edge, forecast_vector,
    forecast_evidence) — it only WRITES to delivery_ledger (existing table).
  - No conviction, stance, verdict_rationale, or LLM-prompt field is read
    or written anywhere in this module.
  - No buy/sell/hold, target price, or investment recommendation language is
    present anywhere in this module.

Gating: this module is a no-op (returns [] without writing anything) unless
ALL FOUR of forecast_build_enabled, forecast_scoring_enabled,
forecast_delivery_enabled, and forecast_shadow are True. Since the first
three default to False, the default production behavior is fully inert.

Forecast "snapshot" inputs accepted by detect_forecast_transitions /
classify_forecast_transition can be either ORM ForecastVector rows or plain
dicts with at least {entity_type, entity_key, forecast_type, horizon_days,
p_positive, p_negative, p_neutral}.  This keeps the diff logic pure and
testable without requiring a live DB session.

Transition types
----------------
  first_forecast       — entity/type/horizon combination has a forecast for
                         the first time (no previous entry in prior snapshot)
  forecast_strengthened — p_positive increased by ≥ MATERIALITY_THRESHOLD
  forecast_weakened     — p_positive decreased by ≥ MATERIALITY_THRESHOLD
  forecast_disappeared  — forecast was present in previous snapshot but is
                         absent from current (expired / deleted)
  confidence_changed    — confidence_label changed (low→medium, medium→high,
                         or any direction) without a material p_positive shift
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

FORECAST_DELIVERY_CHANNEL: str = "forecast_shadow"

# Minimum |p_positive delta| for a transition to count as strengthen/weaken
# rather than steady-state noise.
DEFAULT_MATERIALITY_THRESHOLD: float = 0.08

TRANSITION_FIRST_FORECAST   = "first_forecast"
TRANSITION_STRENGTHENED     = "forecast_strengthened"
TRANSITION_WEAKENED         = "forecast_weakened"
TRANSITION_DISAPPEARED      = "forecast_disappeared"
TRANSITION_CONFIDENCE       = "confidence_changed"

_SUPPORTED_TRANSITIONS = frozenset({
    TRANSITION_FIRST_FORECAST,
    TRANSITION_STRENGTHENED,
    TRANSITION_WEAKENED,
    TRANSITION_DISAPPEARED,
    TRANSITION_CONFIDENCE,
})


# ---------------------------------------------------------------------------
# ORM/dict accessor
# ---------------------------------------------------------------------------

def _field(obj: Any, name: str, default=None):
    """Read *name* from an object that may be an ORM row or a plain dict."""
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _vector_key(vector: Any) -> tuple:
    """Stable identity tuple for a forecast vector."""
    return (
        _field(vector, "entity_type"),
        _field(vector, "entity_key"),
        _field(vector, "forecast_type"),
        _field(vector, "horizon_days"),
        _field(vector, "user_id"),
    )


def _confidence_label(vector: Any) -> str:
    # confidence_label may or may not be a column; infer from band if absent
    label = _field(vector, "confidence_label", None)
    if label:
        return str(label)
    low  = float(_field(vector, "confidence_band_low",  0.0) or 0.0)
    high = float(_field(vector, "confidence_band_high", 1.0) or 1.0)
    band = high - low
    if band <= 0.20:
        return "high"
    if band <= 0.35:
        return "medium"
    return "low"


# ---------------------------------------------------------------------------
# Pure transition classifier
# ---------------------------------------------------------------------------

def classify_forecast_transition(
    previous: Optional[Any],
    current: Optional[Any],
    *,
    materiality_threshold: float = DEFAULT_MATERIALITY_THRESHOLD,
) -> Optional[str]:
    """Classify the transition between two forecast states.

    *previous* and *current* may be None (no forecast existed / no longer
    exists), ORM ForecastVector rows, or plain dicts with at least the fields
    needed for comparison.

    Returns one of the TRANSITION_* constants, or None (steady-state — caller
    must not journal this).
    """
    has_prev = previous is not None
    has_curr = current is not None

    if not has_prev and has_curr:
        return TRANSITION_FIRST_FORECAST

    if has_prev and not has_curr:
        return TRANSITION_DISAPPEARED

    if has_prev and has_curr:
        prev_p = float(_field(previous, "p_positive", 0.33) or 0.33)
        curr_p = float(_field(current,  "p_positive", 0.33) or 0.33)
        delta = curr_p - prev_p

        if delta >= materiality_threshold:
            return TRANSITION_STRENGTHENED
        if delta <= -materiality_threshold:
            return TRANSITION_WEAKENED

        # No material p_positive shift — check confidence label change
        prev_conf = _confidence_label(previous)
        curr_conf = _confidence_label(current)
        if prev_conf != curr_conf:
            return TRANSITION_CONFIDENCE

        return None  # steady-state

    return None  # both absent — nothing to report


# ---------------------------------------------------------------------------
# Pure transition detector (snapshot diff)
# ---------------------------------------------------------------------------

def detect_forecast_transitions(
    previous_set: Optional[List[Any]],
    current_set: Optional[List[Any]],
    *,
    materiality_threshold: float = DEFAULT_MATERIALITY_THRESHOLD,
) -> List[Dict]:
    """Pure diff of two forecast-vector snapshots.

    Returns one event dict per transition-worthy key; steady-state pairs
    produce no entry.  Never raises on malformed input — unparseable entries
    are silently skipped.

    Each event dict contains:
      entity_type, entity_key, forecast_type, horizon_days, user_id,
      transition, previous_p_positive, current_p_positive,
      previous_confidence, current_confidence
    """
    try:
        prev_by_key: Dict[tuple, Any] = {
            _vector_key(v): v for v in (previous_set or [])
        }
        curr_by_key: Dict[tuple, Any] = {
            _vector_key(v): v for v in (current_set or [])
        }
    except Exception as exc:
        logger.debug(
            "[forecast_delivery_service] failed to index snapshots: %r", exc
        )
        return []

    events: List[Dict] = []
    all_keys = set(prev_by_key) | set(curr_by_key)

    for key in all_keys:
        prev = prev_by_key.get(key)
        curr = curr_by_key.get(key)

        transition = classify_forecast_transition(
            prev, curr, materiality_threshold=materiality_threshold
        )
        if transition is None:
            continue

        entity_type, entity_key, forecast_type, horizon_days, user_id = key
        events.append({
            "entity_type":          entity_type,
            "entity_key":           entity_key,
            "forecast_type":        forecast_type,
            "horizon_days":         horizon_days,
            "user_id":              user_id,
            "transition":           transition,
            "previous_p_positive":  float(_field(prev, "p_positive", 0.33) or 0.33)
                                    if prev is not None else None,
            "current_p_positive":   float(_field(curr, "p_positive", 0.33) or 0.33)
                                    if curr is not None else None,
            "previous_confidence":  _confidence_label(prev) if prev is not None else None,
            "current_confidence":   _confidence_label(curr) if curr is not None else None,
        })

    return events


# ---------------------------------------------------------------------------
# Flag gate
# ---------------------------------------------------------------------------

def _delivery_approved(run_override: Optional[bool] = None) -> bool:
    """All four forecast flags must be True for shadow journaling to run.

    Defaults (build=False, scoring=False, delivery=False, shadow=True)
    mean this is False out of the box — the documented inert default.

    ``run_override=True``  → always approved (test/admin seam).
    ``run_override=False`` → always blocked.
    ``run_override=None``  → consult settings flags.
    """
    if run_override is not None:
        return bool(run_override)
    try:
        from app.config import settings
        return bool(
            getattr(settings, "forecast_build_enabled",    False)
            and getattr(settings, "forecast_scoring_enabled",  False)
            and getattr(settings, "forecast_delivery_enabled", False)
            and getattr(settings, "forecast_shadow",            True)
        )
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Shadow journal writer
# ---------------------------------------------------------------------------

async def record_forecast_transition_events(
    session,
    previous_set: Optional[List[Any]],
    current_set: Optional[List[Any]],
    *,
    materiality_threshold: float = DEFAULT_MATERIALITY_THRESHOLD,
    run_override: Optional[bool] = None,
) -> List[Dict]:
    """Detect forecast transitions and journal each as a shadow ledger row.

    Returns the list of detected transition-event dicts (whether or not a
    new ledger row was created for each — duplicate suppression via the
    existing content_key UNIQUE constraint is expected, not an error).

    Returns [] without writing anything when:
      - session is None
      - the flag gates are not all True (default production state)
      - an unexpected error occurs (logged at debug level, never raised)

    Channel written: "forecast_shadow" (no consumer registered — inert).
    Status on every row: "pending" (default; never updated by this module).
    No Notification rows, no inbox entries, no user-visible delivery.
    """
    if session is None:
        return []
    if not _delivery_approved(run_override):
        return []

    try:
        events = detect_forecast_transitions(
            previous_set, current_set,
            materiality_threshold=materiality_threshold,
        )
        if not events:
            return events

        from app.services.loop_idempotency_service import (
            build_payload_hash,
            guard_delivery,
        )

        for event in events:
            target_key = (
                f"{event['entity_type']}:{event['entity_key']}"
                f":{event['forecast_type']}:{event['horizon_days']}"
            )
            payload_hash = build_payload_hash(event)
            await guard_delivery(
                session,
                user_id=event.get("user_id") or "system",
                channel=FORECAST_DELIVERY_CHANNEL,
                target_key=target_key,
                payload_hash=payload_hash,
            )

        return events
    except Exception as exc:
        logger.debug(
            "[forecast_delivery_service] record_forecast_transition_events "
            "failed: %r", exc,
        )
        return []
