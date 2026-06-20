"""
Personal Experience Shadow Journal — Phase 18 · Slice 8.

Records what the Personal Experience layer *would* surface, without
actually showing it.  The shadow observation layer.

Core question: "What would the user have seen?"

Transition types
----------------
  - most_important_change_changed — MIC entity or score changed
  - attention_queue_changed       — attention queue membership changed
  - resume_candidate_changed      — resume candidate set changed
  - brief_changed                 — daily brief content changed
  - revisit_candidate_changed     — revisit candidate set changed

All events are written to personal_experience_event (append-only) with
run_reason="shadow".  No Notification rows, no user-visible delivery.

Deduplication
-------------
Recent events within _DEDUP_WINDOW_SECONDS (3600) with the same
(user_id, surface, item_ref, experience_score) are skipped.

Flag gate
---------
Gated on experience_shadow (True by default — shadow is always on).

Null-session contract
---------------------
All async functions return [] / None when session=None.

SP-18 invariants
----------------
  SP-18a: no advisory language.
  SP-18b: ordering does not change truth.
  SP-18c: writes only personal_experience_event (append-only).
  SP-18d: no upstream feedback.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_DEDUP_WINDOW_SECONDS: int = 3600

_TRANSITION_TYPES = frozenset({
    "most_important_change_changed",
    "attention_queue_changed",
    "resume_candidate_changed",
    "brief_changed",
    "revisit_candidate_changed",
})


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _shadow_enabled(override: Optional[bool] = None) -> bool:
    if override is not None:
        return bool(override)
    try:
        from app.config import settings
        return bool(getattr(settings, "experience_shadow", True))
    except Exception:
        return True


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _score(item: Dict[str, Any]) -> float:
    return float(item.get("composite_score", item.get("experience_score", 0.0)))


def _key(item: Dict[str, Any]) -> str:
    return str(item.get("entity_key", ""))


# ---------------------------------------------------------------------------
# Pure transition classification
# ---------------------------------------------------------------------------

def classify_experience_transition(
    current_event: Dict[str, Any],
    previous_event: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
    """Classify the transition between two experience snapshots.

    Returns one of the transition type strings, or None when there is
    no material change.

    Works on any dict with entity_key, composite_score, change_type,
    and surface fields.
    """
    if previous_event is None:
        ct = current_event.get("change_type", "")
        if not ct:
            return None
        return "most_important_change_changed"

    cur_key = _key(current_event)
    prev_key = _key(previous_event)
    cur_score = _score(current_event)
    prev_score = _score(previous_event)

    if cur_key != prev_key:
        return "most_important_change_changed"

    if abs(cur_score - prev_score) > 0.01:
        return "attention_queue_changed"

    cur_change = current_event.get("change_type", "")
    prev_change = previous_event.get("change_type", "")
    if cur_change != prev_change:
        return "most_important_change_changed"

    return None


def detect_experience_transitions(
    current_items: List[Dict[str, Any]],
    previous_items: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """Detect all material transitions between two experience snapshots.

    Compares current items against previous items by entity_key.
    Returns a list of transition dicts, each with:
      entity_key, entity_type, transition_type, composite_score,
      change_type, surface, explanation_text

    Items present in current but not previous → most_important_change_changed.
    Items in previous but not current → attention_queue_changed (item removed).
    Items in both → classified by classify_experience_transition.

    Returns [] when no material transitions exist.
    """
    if not current_items:
        if not previous_items:
            return []
        result: List[Dict[str, Any]] = []
        for prev in previous_items:
            result.append({
                "entity_key":      _key(prev),
                "entity_type":     prev.get("entity_type", ""),
                "transition_type": "attention_queue_changed",
                "composite_score": _score(prev),
                "change_type":     prev.get("change_type", ""),
                "surface":         prev.get("surface", ""),
                "explanation_text": f"{_key(prev)} removed from experience",
            })
        return result

    prev_by_key: Dict[str, Dict[str, Any]] = {}
    if previous_items:
        for item in previous_items:
            prev_by_key[_key(item)] = item

    transitions: List[Dict[str, Any]] = []

    for cur in current_items:
        ek = _key(cur)
        prev = prev_by_key.pop(ek, None)
        t_type = classify_experience_transition(cur, prev)
        if t_type is not None:
            transitions.append({
                "entity_key":       ek,
                "entity_type":      cur.get("entity_type", ""),
                "transition_type":  t_type,
                "composite_score":  _score(cur),
                "change_type":      cur.get("change_type", ""),
                "surface":          cur.get("surface", ""),
                "explanation_text": cur.get("explanation_text", cur.get("what_changed", "")),
            })

    for ek, prev in prev_by_key.items():
        transitions.append({
            "entity_key":       ek,
            "entity_type":      prev.get("entity_type", ""),
            "transition_type":  "attention_queue_changed",
            "composite_score":  _score(prev),
            "change_type":      prev.get("change_type", ""),
            "surface":          prev.get("surface", ""),
            "explanation_text":  f"{ek} removed from experience",
        })

    return transitions


# ---------------------------------------------------------------------------
# Async — journal events with deduplication
# ---------------------------------------------------------------------------

async def record_experience_events(
    session,
    *,
    user_id: str,
    surface: str = "shadow",
    transitions: List[Dict[str, Any]],
    run_override: Optional[bool] = None,
    dedup_window_seconds: int = _DEDUP_WINDOW_SECONDS,
) -> List[Any]:
    """Journal experience transitions to personal_experience_event.

    Deduplicates against recent events (same user_id + surface + item_ref +
    experience_score within dedup_window_seconds).

    All rows are written with run_reason="shadow".
    No Notification rows.  No user-visible delivery.

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
        from app.db.repositories.personal_experience_repo import (
            add_experience_event,
            list_experience_events,
        )

        cutoff = _now() - timedelta(seconds=dedup_window_seconds)

        recent = await list_experience_events(
            session,
            user_id=user_id,
            surface=surface,
            surfaced_after=cutoff,
            limit=5000,
        )

        seen: frozenset = frozenset(
            (
                getattr(r, "item_ref", ""),
                round(float(getattr(r, "experience_score", 0.0)), 4),
            )
            for r in recent
        )

        inserted: List[Any] = []
        for t in transitions:
            ek = t.get("entity_key", "")
            score = round(float(t.get("composite_score", 0.0)), 4)
            dedup_key = (ek, score)
            if dedup_key in seen:
                continue

            row = await add_experience_event(
                session,
                user_id=user_id,
                surface=surface,
                item_ref=ek,
                entity_type=t.get("entity_type", ""),
                entity_key=ek,
                experience_score=score,
                attention_priority=float(t.get("attention_priority", 0.0)),
                personal_relevance=float(t.get("personal_relevance", 0.0)),
                recency_score=float(t.get("recency_score", 0.0)),
                novelty_score=float(t.get("novelty_score", 0.0)),
                revisit_score=float(t.get("revisit_score", 0.0)),
                memory_relevance=float(t.get("memory_relevance", 0.0)),
                portfolio_relevance=float(t.get("portfolio_relevance", 0.0)),
                explanation_text=t.get("explanation_text", ""),
                explanation_valid=bool(t.get("explanation_valid", False)),
                run_reason="shadow",
            )
            if row is not None:
                inserted.append(row)

        return inserted
    except Exception as exc:
        logger.debug("[shadow] record_experience_events failed: %r", exc)
        return []
