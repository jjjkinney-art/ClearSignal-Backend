"""
Decision Shadow Delivery — Phase 13 · Slice 8.

Detects meaningful transitions in decision priority scores/buckets and
journals each as a deduped, shadow-only entry in the existing
delivery_ledger — reusing the Phase 10A idempotency machinery exactly as
forecast_delivery_service.py does.

Scope boundaries (hard)
-----------------------
  - Steady-state decisions (no material transition) are NEVER journaled.
    Re-running against an unchanged set of priorities produces zero ledger
    writes.
  - This module NEVER marks a ledger row "delivered" and NEVER creates a
    Notification row.  Rows land as channel="decision_shadow", status="pending"
    and are never drained by any existing flush pipeline — there is no
    consumer registered for this channel.  That is what makes this inert /
    not user-visible.
  - Nothing here writes to any source table (decision_priority rows are only
    READ as inputs, never written by this module).
  - No conviction, stance, verdict_rationale, or LLM-prompt field is read
    or written.
  - No buy/sell/hold, target price, position sizing, or investment
    recommendation language is present anywhere in this module.

Gating: shadow journaling runs only when ALL THREE of
    decision_build_enabled, decision_scoring_enabled, decision_shadow
are True.  decision_delivery_enabled MUST remain False throughout Phase 13;
this module never reads it as a positive gate, and any code path that would
require decision_delivery_enabled=True for delivery is forbidden here.

Since the defaults are decision_build_enabled=False, decision_scoring_enabled=False,
decision_shadow=True, the default production behavior is fully inert.

Transition types
----------------
  first_priority        — decision exists for the first time (no previous entry)
  priority_strengthened — decision_score increased by ≥ MATERIALITY_THRESHOLD
  priority_weakened     — decision_score decreased by ≥ MATERIALITY_THRESHOLD
  priority_disappeared  — decision was in previous snapshot but absent in current
  bucket_changed        — decision_priority bucket changed without a material
                          score shift (e.g., score moved from 0.81→0.79, crossing
                          the critical/high boundary)

Inputs accepted by detect_decision_transitions / classify_decision_transition
may be either ORM DecisionPriority rows or plain dicts with at least the
fields needed for comparison.  Keeping the diff logic pure and dict-safe
makes it fully testable without a live DB session.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DECISION_DELIVERY_CHANNEL: str = "decision_shadow"

DEFAULT_MATERIALITY_THRESHOLD: float = 0.08

TRANSITION_FIRST_PRIORITY    = "first_priority"
TRANSITION_STRENGTHENED      = "priority_strengthened"
TRANSITION_WEAKENED          = "priority_weakened"
TRANSITION_DISAPPEARED       = "priority_disappeared"
TRANSITION_BUCKET_CHANGED    = "bucket_changed"

_SUPPORTED_TRANSITIONS = frozenset({
    TRANSITION_FIRST_PRIORITY,
    TRANSITION_STRENGTHENED,
    TRANSITION_WEAKENED,
    TRANSITION_DISAPPEARED,
    TRANSITION_BUCKET_CHANGED,
})

_BUCKET_RANK: Dict[str, int] = {
    "critical":     4,
    "high":         3,
    "medium":       2,
    "low":          1,
    "informational": 0,
}


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


def _priority_key(priority: Any) -> tuple:
    """Stable identity tuple for a decision priority."""
    return (
        _field(priority, "candidate_type"),
        _field(priority, "entity_type"),
        _field(priority, "entity_key"),
        _field(priority, "user_id"),
    )


def _score(priority: Any) -> float:
    val = _field(priority, "decision_rank_score", None)
    if val is None:
        val = _field(priority, "decision_score", 0.0)
    return float(val or 0.0)


def _bucket(priority: Any) -> str:
    return str(_field(priority, "decision_priority", "informational") or "informational")


# ---------------------------------------------------------------------------
# Pure transition classifier
# ---------------------------------------------------------------------------

def classify_decision_transition(
    previous: Optional[Any],
    current: Optional[Any],
    *,
    materiality_threshold: float = DEFAULT_MATERIALITY_THRESHOLD,
) -> Optional[str]:
    """Classify the transition between two decision-priority states.

    *previous* and *current* may be None (no decision existed / no longer
    exists), ORM DecisionPriority rows, or plain dicts with at least the
    fields needed for comparison.

    Returns one of the TRANSITION_* constants, or None (steady-state — caller
    must not journal this).
    """
    has_prev = previous is not None
    has_curr = current is not None

    if not has_prev and has_curr:
        return TRANSITION_FIRST_PRIORITY

    if has_prev and not has_curr:
        return TRANSITION_DISAPPEARED

    if has_prev and has_curr:
        prev_score = _score(previous)
        curr_score = _score(current)
        delta = curr_score - prev_score

        if delta >= materiality_threshold:
            return TRANSITION_STRENGTHENED
        if delta <= -materiality_threshold:
            return TRANSITION_WEAKENED

        # No material score shift — check bucket change
        prev_bkt = _bucket(previous)
        curr_bkt = _bucket(current)
        if prev_bkt != curr_bkt:
            return TRANSITION_BUCKET_CHANGED

        return None  # steady-state

    return None  # both absent — nothing to report


# ---------------------------------------------------------------------------
# Pure transition detector (snapshot diff)
# ---------------------------------------------------------------------------

def detect_decision_transitions(
    previous_set: Optional[List[Any]],
    current_set: Optional[List[Any]],
    *,
    materiality_threshold: float = DEFAULT_MATERIALITY_THRESHOLD,
) -> List[Dict]:
    """Pure diff of two decision-priority snapshots.

    Returns one event dict per transition-worthy key; steady-state pairs
    produce no entry.  Never raises on malformed input — unparseable entries
    are silently skipped.

    Each event dict contains:
      candidate_type, entity_type, entity_key, user_id,
      transition, previous_score, current_score,
      previous_bucket, current_bucket
    """
    try:
        prev_by_key: Dict[tuple, Any] = {
            _priority_key(p): p for p in (previous_set or [])
        }
        curr_by_key: Dict[tuple, Any] = {
            _priority_key(p): p for p in (current_set or [])
        }
    except Exception as exc:
        logger.debug(
            "[decision_delivery_service] failed to index snapshots: %r", exc
        )
        return []

    events: List[Dict] = []
    all_keys = set(prev_by_key) | set(curr_by_key)

    for key in all_keys:
        prev = prev_by_key.get(key)
        curr = curr_by_key.get(key)

        transition = classify_decision_transition(
            prev, curr, materiality_threshold=materiality_threshold
        )
        if transition is None:
            continue

        candidate_type, entity_type, entity_key, user_id = key
        events.append({
            "candidate_type":   candidate_type,
            "entity_type":      entity_type,
            "entity_key":       entity_key,
            "user_id":          user_id,
            "transition":       transition,
            "previous_score":   _score(prev)   if prev is not None else None,
            "current_score":    _score(curr)   if curr is not None else None,
            "previous_bucket":  _bucket(prev)  if prev is not None else None,
            "current_bucket":   _bucket(curr)  if curr is not None else None,
        })

    return events


# ---------------------------------------------------------------------------
# Flag gate
# ---------------------------------------------------------------------------

def _delivery_approved(run_override: Optional[bool] = None) -> bool:
    """Return True only when shadow journaling should run.

    Requires decision_build_enabled=True, decision_scoring_enabled=True,
    and decision_shadow=True.

    decision_delivery_enabled is intentionally NOT consulted here — that flag
    controls live user-visible delivery and must remain False throughout
    Phase 13.

    ``run_override=True``  → always approved (test/admin seam).
    ``run_override=False`` → always blocked.
    ``run_override=None``  → consult settings flags.
    """
    if run_override is not None:
        return bool(run_override)
    try:
        from app.config import settings
        return bool(
            getattr(settings, "decision_build_enabled",    False)
            and getattr(settings, "decision_scoring_enabled",  False)
            and getattr(settings, "decision_shadow",            True)
        )
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Shadow journal writer
# ---------------------------------------------------------------------------

async def record_decision_transition_events(
    session,
    previous_set: Optional[List[Any]],
    current_set: Optional[List[Any]],
    *,
    materiality_threshold: float = DEFAULT_MATERIALITY_THRESHOLD,
    run_override: Optional[bool] = None,
) -> List[Dict]:
    """Detect decision-priority transitions and journal each as a shadow ledger row.

    Returns the list of detected transition-event dicts (whether or not a new
    ledger row was created for each — duplicate suppression via the existing
    content_key UNIQUE constraint is expected and not an error).

    Returns [] without writing anything when:
      - session is None
      - the flag gates are not all set (default production state)
      - an unexpected error occurs (logged at debug level, never raised)

    Channel written: "decision_shadow" (no consumer registered — inert).
    Status on every row: "pending" (default; never updated by this module).
    No Notification rows, no inbox entries, no user-visible delivery.
    """
    if session is None:
        return []
    if not _delivery_approved(run_override):
        return []

    try:
        events = detect_decision_transitions(
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
                f":{event['candidate_type']}"
            )
            payload_hash = build_payload_hash(event)
            await guard_delivery(
                session,
                user_id=event.get("user_id") or "system",
                channel=DECISION_DELIVERY_CHANNEL,
                target_key=target_key,
                payload_hash=payload_hash,
            )

        return events
    except Exception as exc:
        logger.debug(
            "[decision_delivery_service] record_decision_transition_events "
            "failed: %r", exc,
        )
        return []
