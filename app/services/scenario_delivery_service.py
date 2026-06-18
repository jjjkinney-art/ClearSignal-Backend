"""
Scenario Shadow Delivery — Phase 14 · Slice 8.

Detects meaningful transitions in scenario snapshots and journals each as a
deduped, shadow-only entry in the existing delivery_ledger — reusing the Phase
10A idempotency machinery (guard_delivery / build_payload_hash) wholesale rather
than inventing a parallel dedup mechanism.

Scope boundaries (hard):
  - Steady-state scenarios (no material transition) are NEVER journaled.
    Re-running against an unchanged snapshot set produces zero ledger writes.
  - This module NEVER marks a ledger row "delivered" and NEVER creates a
    Notification row.  Rows land as channel="scenario_shadow", status "pending"
    and are never drained by any existing flush pipeline — there is no consumer
    registered for this channel.  That is what makes this genuinely inert and
    not user-visible.
  - Nothing here writes to any source table (scenario_snapshot, scenario_evidence,
    scenario_run_log, forecast_vector, conviction, decisions, dossier, portfolio).
    The only write target is delivery_ledger (existing table).
  - No conviction, stance, forecast, or decision field is read or written.
  - No buy/sell, target price, or investment advice language is present anywhere
    in this module.

Gating: this module is a no-op (returns [] without writing anything) unless
BOTH scenario_scoring_enabled AND scenario_shadow are True.  Default values are
False/True, so shadow journaling is off by default — matching the documented
inert default for Phase 14.

Input snapshots accepted by detect_scenario_transitions /
classify_scenario_transition can be either ORM ScenarioSnapshot rows or plain
dicts with at least {scenario_type, entity_type, entity_key, scenario_key,
confidence_score, plausibility_band, scenario_impact, user_id}.
This keeps the diff logic pure and testable without a live DB session.

Transition types
----------------
  first_scenario         — scenario/type/key combination appears for the first
                           time (no previous entry in the prior snapshot set)
  scenario_strengthened  — confidence_score increased by ≥ MATERIALITY_THRESHOLD
  scenario_weakened      — confidence_score decreased by ≥ MATERIALITY_THRESHOLD
  scenario_disappeared   — scenario present in prior snapshot but absent from
                           current (expired / rebuilt away)
  propagation_changed    — plausibility_band or scenario_impact changed without a
                           material confidence shift
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

SCENARIO_DELIVERY_CHANNEL: str = "scenario_shadow"

# Minimum |confidence_score delta| for a transition to count as strengthen/weaken
# rather than steady-state noise.  Mirrors the forecast service threshold.
DEFAULT_MATERIALITY_THRESHOLD: float = 0.08

TRANSITION_FIRST_SCENARIO    = "first_scenario"
TRANSITION_STRENGTHENED      = "scenario_strengthened"
TRANSITION_WEAKENED          = "scenario_weakened"
TRANSITION_DISAPPEARED       = "scenario_disappeared"
TRANSITION_PROPAGATION       = "propagation_changed"

_SUPPORTED_TRANSITIONS = frozenset({
    TRANSITION_FIRST_SCENARIO,
    TRANSITION_STRENGTHENED,
    TRANSITION_WEAKENED,
    TRANSITION_DISAPPEARED,
    TRANSITION_PROPAGATION,
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


def _snapshot_key(snapshot: Any) -> tuple:
    """Stable identity tuple for a scenario snapshot."""
    return (
        _field(snapshot, "scenario_type"),
        _field(snapshot, "entity_type"),
        _field(snapshot, "entity_key"),
        _field(snapshot, "scenario_key"),
        _field(snapshot, "user_id"),
    )


# ---------------------------------------------------------------------------
# Pure transition classifier
# ---------------------------------------------------------------------------

def classify_scenario_transition(
    previous: Optional[Any],
    current: Optional[Any],
    *,
    materiality_threshold: float = DEFAULT_MATERIALITY_THRESHOLD,
) -> Optional[str]:
    """Classify the transition between two scenario snapshot states.

    *previous* and *current* may be None (scenario did not exist / no longer
    exists), ORM ScenarioSnapshot rows, or plain dicts.

    Returns one of the TRANSITION_* constants, or None (steady-state — caller
    must not journal this).
    """
    has_prev = previous is not None
    has_curr = current is not None

    if not has_prev and has_curr:
        return TRANSITION_FIRST_SCENARIO

    if has_prev and not has_curr:
        return TRANSITION_DISAPPEARED

    if has_prev and has_curr:
        prev_conf = float(_field(previous, "confidence_score", 0.5) or 0.5)
        curr_conf = float(_field(current,  "confidence_score", 0.5) or 0.5)
        delta = curr_conf - prev_conf

        if delta >= materiality_threshold:
            return TRANSITION_STRENGTHENED
        if delta <= -materiality_threshold:
            return TRANSITION_WEAKENED

        # No material confidence shift — check structural propagation change
        prev_plaus  = _field(previous, "plausibility_band", "")
        curr_plaus  = _field(current,  "plausibility_band", "")
        prev_impact = _field(previous, "scenario_impact",   "")
        curr_impact = _field(current,  "scenario_impact",   "")

        if prev_plaus != curr_plaus or prev_impact != curr_impact:
            return TRANSITION_PROPAGATION

        return None  # steady-state

    return None  # both absent — nothing to report


# ---------------------------------------------------------------------------
# Pure transition detector (snapshot diff)
# ---------------------------------------------------------------------------

def detect_scenario_transitions(
    previous_set: Optional[List[Any]],
    current_set: Optional[List[Any]],
    *,
    materiality_threshold: float = DEFAULT_MATERIALITY_THRESHOLD,
) -> List[Dict]:
    """Pure diff of two scenario snapshot sets.

    Returns one event dict per transition-worthy key; steady-state pairs
    produce no entry.  Never raises on malformed input — unparseable entries
    are silently skipped.

    Each event dict contains:
      scenario_type, entity_type, entity_key, scenario_key, user_id,
      transition,
      previous_confidence, current_confidence,
      previous_plausibility, current_plausibility,
      previous_impact, current_impact
    """
    try:
        prev_by_key: Dict[tuple, Any] = {
            _snapshot_key(s): s for s in (previous_set or [])
        }
        curr_by_key: Dict[tuple, Any] = {
            _snapshot_key(s): s for s in (current_set or [])
        }
    except Exception as exc:
        logger.debug("[scenario_delivery_service] failed to index snapshots: %r", exc)
        return []

    events: List[Dict] = []
    all_keys = set(prev_by_key) | set(curr_by_key)

    for key in sorted(all_keys):  # sorted for determinism
        prev = prev_by_key.get(key)
        curr = curr_by_key.get(key)

        transition = classify_scenario_transition(
            prev, curr, materiality_threshold=materiality_threshold
        )
        if transition is None:
            continue

        scenario_type, entity_type, entity_key, scenario_key, user_id = key
        events.append({
            "scenario_type":          scenario_type,
            "entity_type":            entity_type,
            "entity_key":             entity_key,
            "scenario_key":           scenario_key,
            "user_id":                user_id,
            "transition":             transition,
            "previous_confidence":    float(_field(prev, "confidence_score", 0.5) or 0.5)
                                      if prev is not None else None,
            "current_confidence":     float(_field(curr, "confidence_score", 0.5) or 0.5)
                                      if curr is not None else None,
            "previous_plausibility":  _field(prev, "plausibility_band") if prev else None,
            "current_plausibility":   _field(curr, "plausibility_band") if curr else None,
            "previous_impact":        _field(prev, "scenario_impact")   if prev else None,
            "current_impact":         _field(curr, "scenario_impact")   if curr else None,
        })

    return events


# ---------------------------------------------------------------------------
# Flag gate
# ---------------------------------------------------------------------------

def _delivery_approved(run_override: Optional[bool] = None) -> bool:
    """Shadow journaling requires scenario_scoring_enabled AND scenario_shadow.

    ``run_override=True``  → always approved (test/admin seam).
    ``run_override=False`` → always blocked.
    ``run_override=None``  → consult settings flags.

    Default state (scoring=False, shadow=True) → False (inert default).
    scenario_delivery_enabled is NOT checked here — this module runs in shadow
    mode only and deliberately ignores the live-delivery gate.
    """
    if run_override is not None:
        return bool(run_override)
    try:
        from app.config import settings
        return bool(
            getattr(settings, "scenario_scoring_enabled", False)
            and getattr(settings, "scenario_shadow", True)
        )
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Shadow journal writer
# ---------------------------------------------------------------------------

async def record_scenario_transition_events(
    session,
    previous_set: Optional[List[Any]],
    current_set: Optional[List[Any]],
    *,
    materiality_threshold: float = DEFAULT_MATERIALITY_THRESHOLD,
    run_override: Optional[bool] = None,
) -> List[Dict]:
    """Detect scenario transitions and journal each as a shadow ledger row.

    Returns the list of detected transition-event dicts (whether or not a
    new ledger row was created for each — duplicate suppression via the
    existing content_key UNIQUE constraint is expected, not an error).

    Returns [] without writing anything when:
      - session is None
      - flag gates are not satisfied (default production state)
      - an unexpected error occurs (logged at debug, never raised)

    Channel written: "scenario_shadow" (no consumer registered — inert).
    Status on every row: "pending" (default; never updated by this module).
    No Notification rows, no inbox entries, no user-visible delivery.
    """
    if session is None:
        return []
    if not _delivery_approved(run_override):
        return []

    try:
        events = detect_scenario_transitions(
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
                f"{event['scenario_type']}:{event['entity_key']}"
                f":{event['scenario_key']}"
            )
            payload_hash = build_payload_hash(event)
            await guard_delivery(
                session,
                user_id=event.get("user_id") or "system",
                channel=SCENARIO_DELIVERY_CHANNEL,
                target_key=target_key,
                payload_hash=payload_hash,
            )

        return events
    except Exception as exc:
        logger.debug(
            "[scenario_delivery_service] record_scenario_transition_events error: %r",
            exc,
        )
        return []
