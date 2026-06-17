"""
Similarity Delivery Wiring — Phase 11 · Slice 7.

Detects *transitions* in T4 similarity edges (a match first crossing the
relevance floor, materially strengthening, materially weakening, or
disappearing) and journals each as a deduped, shadow-only entry in the
existing delivery_ledger — reusing the Phase 10A idempotency machinery
wholesale rather than inventing a parallel dedup mechanism.

Scope boundaries (hard):
  - Steady-state matches (no transition) are NEVER journaled. Re-running
    this module against an unchanged edge produces zero ledger writes.
  - This module never marks a ledger row "delivered" and never creates a
    Notification row. Rows land as channel="similarity_shadow", status
    "pending" (delivery_create's default) and are never drained by any
    existing flush pipeline — there is no consumer registered for this
    channel. That is what makes this genuinely inert / not user-visible.
  - Nothing here writes to similarity_feature_vector, similarity_edge, or
    any dossier_*/thesis_*/company_dossier source table. It only READS the
    two edge snapshots passed in by the caller and WRITES to delivery_ledger
    (an existing, already-shipped table — no new schema).
  - No forecasting, conviction, stance, or recommendation logic is touched
    or imported.

Gating: this module is a no-op (returns [] without writing anything) unless
ALL THREE of similarity_build_enabled, similarity_scoring_enabled, and
similarity_shadow are True. Since the first two default to False, the
default production behavior is fully inert. similarity_shadow defaulting
to True (once the other two are flipped on) means transitions are journaled
in shadow only — there is no live-delivery code path in this module at all;
that remains out of scope for a future slice.

Edge "snapshot" inputs accepted by detect_similarity_transitions /
classify_transition can be either ORM SimilarityEdge rows or plain dicts
with at least {target_type, query_key, candidate_key, score, floor_passed,
user_id}. This keeps the diff logic pure and testable without requiring a
live DB session, and lets callers source "previous" from wherever makes
sense (e.g. a snapshot taken just before a Slice 5 rebuild overwrites it).
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

SIMILARITY_DELIVERY_CHANNEL = "similarity_shadow"

# Minimum |score delta| for a still-above-floor match to count as a material
# strengthen/weaken transition rather than steady-state noise.
DEFAULT_MATERIALITY_THRESHOLD = 0.10

TRANSITION_FIRST_CROSSING = "first_crossing"
TRANSITION_STRENGTHENED = "strengthened"
TRANSITION_WEAKENED = "weakened"
TRANSITION_DISAPPEARED = "disappeared"


def _field(edge: Any, name: str, default=None):
    """Read *name* from an edge that may be an ORM row or a plain dict."""
    if edge is None:
        return default
    if isinstance(edge, dict):
        return edge.get(name, default)
    return getattr(edge, name, default)


def _edge_key(edge: Any) -> tuple:
    return (
        _field(edge, "target_type"),
        _field(edge, "query_key"),
        _field(edge, "candidate_key"),
        _field(edge, "user_id"),
    )


def classify_transition(
    previous: Optional[dict],
    current: Optional[dict],
    *,
    materiality_threshold: float = DEFAULT_MATERIALITY_THRESHOLD,
) -> Optional[str]:
    """Classify the transition between two {"score", "floor_passed"} states.

    previous/current may be None (no edge existed / no longer exists in
    that snapshot). Returns one of TRANSITION_FIRST_CROSSING,
    TRANSITION_STRENGTHENED, TRANSITION_WEAKENED, TRANSITION_DISAPPEARED,
    or None when there is no event-worthy transition (steady-state, or
    never crossed the floor in either snapshot).
    """
    prev_passed = bool(previous and previous.get("floor_passed"))
    curr_passed = bool(current and current.get("floor_passed"))

    if not prev_passed and curr_passed:
        return TRANSITION_FIRST_CROSSING
    if prev_passed and not curr_passed:
        return TRANSITION_DISAPPEARED
    if prev_passed and curr_passed:
        delta = float(current.get("score", 0.0)) - float(previous.get("score", 0.0))
        if delta >= materiality_threshold:
            return TRANSITION_STRENGTHENED
        if delta <= -materiality_threshold:
            return TRANSITION_WEAKENED
        return None
    return None  # never passed the floor in either snapshot — nothing to report


def detect_similarity_transitions(
    previous_edges: Optional[List[Any]],
    current_edges: Optional[List[Any]],
    *,
    materiality_threshold: float = DEFAULT_MATERIALITY_THRESHOLD,
) -> List[Dict]:
    """Pure diff of two edge snapshots. Returns one event dict per
    transition-worthy (target_type, query_key, candidate_key, user_id) key;
    steady-state pairs produce no entry at all. Never raises on malformed
    input — unparseable entries are skipped.
    """
    try:
        prev_by_key = {_edge_key(e): e for e in (previous_edges or [])}
        curr_by_key = {_edge_key(e): e for e in (current_edges or [])}
    except Exception as exc:
        logger.debug("[similarity_delivery_service] failed to index edge snapshots: %r", exc)
        return []

    events: List[Dict] = []
    for key in set(prev_by_key) | set(curr_by_key):
        prev = prev_by_key.get(key)
        curr = curr_by_key.get(key)

        prev_state = (
            {"score": float(_field(prev, "score", 0.0)), "floor_passed": bool(_field(prev, "floor_passed", False))}
            if prev is not None else None
        )
        curr_state = (
            {"score": float(_field(curr, "score", 0.0)), "floor_passed": bool(_field(curr, "floor_passed", False))}
            if curr is not None else None
        )

        transition = classify_transition(prev_state, curr_state, materiality_threshold=materiality_threshold)
        if transition is None:
            continue

        target_type, query_key, candidate_key, user_id = key
        events.append({
            "target_type": target_type,
            "query_key": query_key,
            "candidate_key": candidate_key,
            "user_id": user_id,
            "transition": transition,
            "previous_score": prev_state["score"] if prev_state else None,
            "current_score": curr_state["score"] if curr_state else None,
        })
    return events


def _delivery_approved(run_override: Optional[bool] = None) -> bool:
    """All three similarity flags must be True for shadow journaling to run.

    Defaults (build=False, scoring=False, shadow=True) mean this is False
    out of the box — the documented inert default.
    """
    if run_override is not None:
        return run_override
    try:
        from app.config import settings

        return bool(
            getattr(settings, "similarity_build_enabled", False)
            and getattr(settings, "similarity_scoring_enabled", False)
            and getattr(settings, "similarity_shadow", True)
        )
    except Exception:
        return False


async def record_similarity_transition_events(
    session,
    previous_edges: Optional[List[Any]],
    current_edges: Optional[List[Any]],
    *,
    materiality_threshold: float = DEFAULT_MATERIALITY_THRESHOLD,
    run_override: Optional[bool] = None,
) -> List[Dict]:
    """Detect transitions and journal each as a deduped shadow ledger row.

    Returns the list of detected transition-event dicts (whether or not a
    new ledger row was created for each — duplicate suppression via the
    existing content_key UNIQUE constraint is expected, not an error).

    Returns [] without writing anything when:
      - session is None
      - the gating flags are not all True (default production state)
      - an unexpected error occurs (logged at debug level, never raised)
    """
    if session is None:
        return []
    if not _delivery_approved(run_override):
        return []
    try:
        events = detect_similarity_transitions(
            previous_edges, current_edges, materiality_threshold=materiality_threshold,
        )
        if not events:
            return events

        from app.services.loop_idempotency_service import build_payload_hash, guard_delivery

        for event in events:
            target_key = f"{event['target_type']}:{event['query_key']}:{event['candidate_key']}"
            payload_hash = build_payload_hash(event)
            await guard_delivery(
                session,
                user_id=event.get("user_id") or "system",
                channel=SIMILARITY_DELIVERY_CHANNEL,
                target_key=target_key,
                payload_hash=payload_hash,
            )
        return events
    except Exception as exc:
        logger.debug(
            "[similarity_delivery_service] record_similarity_transition_events failed: %r", exc,
        )
        return []
