"""
Visual Shadow Journal — Phase 19 · Slice 10.

Records what the visual layer *would* generate, without serving it.  The
shadow observation layer (modeled on Phase 18 Slice 18.8).

Core question: "What visuals would the user have seen?"

Transition types
----------------
  visual_created        — a new visual spec appeared
  visual_updated        — an existing visual's data/tier/labels changed
  visual_removed        — a previously-present visual is gone
  visual_blocked        — a spec failed the explainability gate
  visual_fallback_used  — an AI visual fell back to a deterministic spec

All events are written to visual_experience_event (append-only) with
run_reason="shadow".  No Notification rows, no user-visible delivery.

Deduplication
-------------
Recent events within _DEDUP_WINDOW_SECONDS (3600) with the same
(visual_type, entity_key, rendering_tier) are skipped.

Flag gate
---------
Gated on visual_shadow (True by default — shadow is always on).
Returns [] when the gate is off or session is None.

SP-19 invariants
----------------
  SP-19a: no advisory language.
  SP-19b: visualization does not change truth.
  SP-19c: writes only visual_experience_event (append-only).
  SP-19d: no upstream feedback.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_DEDUP_WINDOW_SECONDS: int = 3600

_TRANSITION_TYPES = frozenset({
    "visual_created",
    "visual_updated",
    "visual_removed",
    "visual_blocked",
    "visual_fallback_used",
})


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _shadow_enabled(override: Optional[bool] = None) -> bool:
    if override is not None:
        return bool(override)
    try:
        from app.config import settings
        return bool(getattr(settings, "visual_shadow", True))
    except Exception:
        return True


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _key(spec: Dict[str, Any]):
    return (
        spec.get("visual_type", ""),
        spec.get("entity_key", ""),
        spec.get("rendering_tier", ""),
    )


def _signature(spec: Dict[str, Any]):
    """Change-detection signature for an unchanged-vs-updated comparison."""
    return (
        spec.get("rendering_tier", ""),
        bool(spec.get("explanation_valid", False)),
        len(spec.get("evidence_refs", []) or []),
        spec.get("title", ""),
        spec.get("blocked_reason", ""),
    )


# ---------------------------------------------------------------------------
# Pure transition classification
# ---------------------------------------------------------------------------

def classify_visual_transition(
    current: Optional[Dict[str, Any]],
    previous: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
    """Classify the transition between two visual snapshots.

    Returns one of the transition type strings, or None when there is no
    material change.

    Priority: removed → fallback → blocked → created/updated.
    """
    if current is None:
        return "visual_removed" if previous is not None else None

    if current.get("is_fallback"):
        return "visual_fallback_used"

    if not current.get("explanation_valid", False):
        return "visual_blocked"

    if previous is None:
        return "visual_created"

    if _signature(current) != _signature(previous):
        return "visual_updated"

    return None


def _transition_dict(spec: Dict[str, Any], t_type: str) -> Dict[str, Any]:
    if t_type == "visual_blocked":
        valid = False
        reason = spec.get("blocked_reason", "") or "blocked"
    elif t_type == "visual_fallback_used":
        valid = False
        detail = spec.get("fallback_reason", "") or spec.get("blocked_reason", "")
        reason = f"fallback_used:{detail}" if detail else "fallback_used"
    elif t_type == "visual_removed":
        valid = False
        reason = "removed"
    else:  # visual_created | visual_updated
        valid = bool(spec.get("explanation_valid", True))
        reason = ""
    return {
        "visual_type":       spec.get("visual_type", ""),
        "entity_key":        spec.get("entity_key", ""),
        "rendering_tier":    spec.get("rendering_tier", "json"),
        "transition_type":   t_type,
        "explanation_valid": valid,
        "blocked_reason":    str(reason)[:100],
    }


def detect_visual_transitions(
    current_specs: List[Dict[str, Any]],
    previous_specs: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """Detect all material transitions between two visual snapshots.

    Compares current specs against previous specs by
    (visual_type, entity_key, rendering_tier).  Returns a list of transition
    dicts.  Specs present in previous but absent from current produce a
    visual_removed transition.

    Returns [] when there are no material transitions.
    """
    prev_by_key: Dict[Any, Dict[str, Any]] = {}
    if previous_specs:
        for s in previous_specs:
            prev_by_key[_key(s)] = s

    transitions: List[Dict[str, Any]] = []
    seen_keys = set()

    for cur in (current_specs or []):
        if cur is None:
            continue
        k = _key(cur)
        seen_keys.add(k)
        prev = prev_by_key.get(k)
        t_type = classify_visual_transition(cur, prev)
        if t_type is not None:
            transitions.append(_transition_dict(cur, t_type))

    for k, prev in prev_by_key.items():
        if k not in seen_keys:
            transitions.append(_transition_dict(prev, "visual_removed"))

    return transitions


# ---------------------------------------------------------------------------
# Async — journal events with deduplication
# ---------------------------------------------------------------------------

async def record_visual_events(
    session,
    *,
    user_id: str,
    transitions: List[Dict[str, Any]],
    run_override: Optional[bool] = None,
    dedup_window_seconds: int = _DEDUP_WINDOW_SECONDS,
) -> List[Any]:
    """Journal visual transitions to visual_experience_event.

    Deduplicates against recent events (same visual_type + entity_key +
    rendering_tier within dedup_window_seconds).

    All rows are written with run_reason="shadow".  No Notification rows.
    No user-visible delivery.

    Returns the list of inserted ORM rows, or [] when the flag is off,
    session is None, or all transitions were already journaled.
    """
    if not _shadow_enabled(run_override):
        return []
    if session is None:
        return []
    if not transitions:
        return []

    try:
        from app.db.repositories.visual_intelligence_repo import (
            add_visual_event,
            list_visual_events,
        )

        cutoff = _now() - timedelta(seconds=dedup_window_seconds)
        recent = await list_visual_events(
            session, user_id=user_id, surfaced_after=cutoff, limit=5000,
        )
        seen = {
            (
                getattr(r, "visual_type", ""),
                getattr(r, "entity_key", ""),
                getattr(r, "rendering_tier", ""),
            )
            for r in recent
        }

        inserted: List[Any] = []
        for t in transitions:
            key = (
                t.get("visual_type", ""),
                t.get("entity_key", ""),
                t.get("rendering_tier", ""),
            )
            if key in seen:
                continue
            row = await add_visual_event(
                session,
                user_id=user_id,
                visual_type=t.get("visual_type", ""),
                entity_key=t.get("entity_key", ""),
                rendering_tier=t.get("rendering_tier", "json"),
                explanation_valid=bool(t.get("explanation_valid", False)),
                blocked_reason=str(t.get("blocked_reason", ""))[:100],
                run_reason="shadow",
            )
            if row is not None:
                inserted.append(row)
                seen.add(key)

        return inserted
    except Exception as exc:
        logger.debug("[visual_shadow] record_visual_events failed: %r", exc)
        return []
