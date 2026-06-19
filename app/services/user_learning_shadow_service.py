"""
User Learning Shadow Journal Service — Phase 15 · Slice 9.

Classifies and journals personalization effects in shadow mode only.
Uses the relevance_adjustment_log table (append-only, run_reason="shadow").

Core rule
---------
Observe relevance changes.  Do not expose relevance changes to users.

This module writes ONLY to relevance_adjustment_log (via
user_learning_repo.add_relevance_adjustment_log).  It never writes to
Notification, inbox, or any user-delivery table.  It never modifies
any truth table (forecast, similarity, scenario, decision, ticker_memory).

It never generates ranking changes — it only records what the
build_relevance_projection output shows about potential ranking effects.

Flag gate
---------
record_relevance_transition_events is gated on learning_inference_enabled
(default False).  When off it returns [] immediately.

Null-session contract
---------------------
record_relevance_transition_events returns [] when session=None.
classify_relevance_transition and detect_relevance_transitions are
pure functions — they do not accept a session.

Transition types
----------------
  relevance_increased    — item would move up under personalisation
  relevance_decreased    — item would move down under personalisation
  relevance_removed      — item would be muted (lowest non-hidden tier)
  novelty_reserve_applied — item was promoted by the anti-filter-bubble reserve
  relevance_floor_applied — item was protected by SP-7d floor

Materiality
-----------
Only transitions where abs(relevance_adjustment − 1.0) >= _MIN_FACTOR_DELTA
are recorded.  Below this cutoff the change is trivial and journaling is
skipped.  SP-7d flags (floor, novelty) are always journaled regardless of
factor magnitude.

Deduplication
-------------
Before writing, recent rows are fetched (within _DEDUP_WINDOW_SECONDS).
A transition keyed by (item_ref, intrinsic_rank, adjusted_rank) that already
appears in the recent window is skipped, preventing duplicate rows from
repeated projection runs.

SP-7 invariants
---------------
  SP-7a: no write to truth tables.
  SP-7b: no import of forecast / decision / scenario / similarity write fns.
  SP-7c: no ranking mutation.  All output is shadow observation only.
  SP-7d: prominence_tier "hidden" is never written — the log schema forbids it.
  SP-7f: no banned advisory phrases.
  SP-7h: no user-visible delivery.  No Notification rows.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Materiality cutoff: changes smaller than this factor delta are not journaled.
_MIN_FACTOR_DELTA: float = 0.05

# Deduplication window: transitions already journaled within this window are skipped.
_DEDUP_WINDOW_SECONDS: int = 3600

# Valid prominence tiers for the log.
_VALID_TIERS = frozenset({"pinned", "normal", "muted"})

# Transition type strings.
_TRANSITION_INCREASED = "relevance_increased"
_TRANSITION_DECREASED = "relevance_decreased"
_TRANSITION_REMOVED   = "relevance_removed"
_TRANSITION_NOVELTY   = "novelty_reserve_applied"
_TRANSITION_FLOOR     = "relevance_floor_applied"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _shadow_enabled(override: Optional[bool] = None) -> bool:
    if override is not None:
        return bool(override)
    try:
        from app.config import settings
        return bool(getattr(settings, "learning_inference_enabled", False))
    except Exception:
        return False


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Public API — pure functions (no session)
# ---------------------------------------------------------------------------

def classify_relevance_transition(
    projection_item: Dict[str, Any],
    *,
    min_factor_delta: float = _MIN_FACTOR_DELTA,
) -> Optional[str]:
    """Classify one projection item into a transition type string.

    Priority order:
      1. novelty_reserve_applied flag → "novelty_reserve_applied"
      2. relevance_floor_applied flag → "relevance_floor_applied"
      3. abs(factor − 1.0) < min_factor_delta → None (trivial, no-op)
      4. adjusted_rank < intrinsic_rank → "relevance_increased"
      5. adjusted_rank > intrinsic_rank and tier="muted" → "relevance_removed"
      6. adjusted_rank > intrinsic_rank → "relevance_decreased"
      7. factor material but rank unchanged → None

    Returns None for trivial/no-op changes.
    Pure function — no I/O.
    """
    novelty = bool(projection_item.get("novelty_reserve_applied", False))
    floor   = bool(projection_item.get("relevance_floor_applied", False))

    if novelty:
        return _TRANSITION_NOVELTY
    if floor:
        return _TRANSITION_FLOOR

    factor = float(projection_item.get("relevance_adjustment", 1.0) or 1.0)
    if abs(factor - 1.0) < min_factor_delta:
        return None

    intrinsic_rank = int(projection_item.get("intrinsic_rank", 0) or 0)
    adjusted_rank  = int(projection_item.get("adjusted_rank", 0) or 0)
    rank_delta     = intrinsic_rank - adjusted_rank   # positive = moved up
    tier           = str(projection_item.get("prominence_tier", "normal") or "normal")

    if rank_delta > 0:
        return _TRANSITION_INCREASED
    if rank_delta < 0:
        return _TRANSITION_REMOVED if tier == "muted" else _TRANSITION_DECREASED
    return None


def detect_relevance_transitions(
    projection: List[Dict[str, Any]],
    *,
    min_factor_delta: float = _MIN_FACTOR_DELTA,
) -> List[Dict[str, Any]]:
    """Filter a projection list to only material transition events.

    Each returned dict contains the fields needed to write a
    relevance_adjustment_log row plus a "transition_type" key.

    Transition event shape:
    {
        "item_ref":               str,
        "entity_key":             str,
        "entity_type":            str,
        "signal_type":            str,
        "intrinsic_rank":         int,
        "adjusted_rank":          int,
        "relevance_adjustment":   float,
        "prominence_tier":        str,
        "floor_applied":          bool,    # matches log column name
        "novelty_reserve_applied": bool,
        "transition_type":        str,
    }

    Returns [] for an empty projection.  Pure function — no I/O.
    """
    events: List[Dict[str, Any]] = []
    for item in projection:
        ttype = classify_relevance_transition(item, min_factor_delta=min_factor_delta)
        if ttype is None:
            continue
        events.append({
            "item_ref":               item.get("item_ref", "") or "",
            "entity_key":             item.get("entity_key", "") or "",
            "entity_type":            item.get("entity_type", "") or "",
            "signal_type":            item.get("signal_type", "") or "",
            "intrinsic_rank":         int(item.get("intrinsic_rank", 0) or 0),
            "adjusted_rank":          int(item.get("adjusted_rank", 0) or 0),
            "relevance_adjustment":   float(item.get("relevance_adjustment", 1.0) or 1.0),
            "prominence_tier":        str(item.get("prominence_tier", "normal") or "normal"),
            "floor_applied":          bool(item.get("relevance_floor_applied", False)),
            "novelty_reserve_applied": bool(item.get("novelty_reserve_applied", False)),
            "transition_type":        ttype,
        })
    return events


# ---------------------------------------------------------------------------
# Public API — async (requires session)
# ---------------------------------------------------------------------------

async def record_relevance_transition_events(
    session,
    *,
    user_id: str,
    surface: str,
    projection: List[Dict[str, Any]],
    run_override: Optional[bool] = None,
    dedup_window_seconds: int = _DEDUP_WINDOW_SECONDS,
) -> List[Any]:
    """Journal material relevance transitions to relevance_adjustment_log.

    Detects transitions from the projection, deduplicates against recent log
    entries (same user_id + item_ref + ranks within dedup_window_seconds),
    and inserts rows for new material changes.

    All rows are written with run_reason='shadow'.
    No Notification rows, no user-visible delivery.

    Returns the list of inserted ORM rows, or [] when the flag is off,
    session is None, the projection has no material transitions, or all
    transitions were already journaled within the dedup window.
    """
    if not _shadow_enabled(run_override):
        return []
    if session is None:
        return []
    if not projection:
        return []
    try:
        transitions = detect_relevance_transitions(projection)
        if not transitions:
            return []

        cutoff = _now() - timedelta(seconds=dedup_window_seconds)

        from app.db.repositories.user_learning_repo import (
            add_relevance_adjustment_log,
            list_relevance_adjustment_logs,
        )

        recent = await list_relevance_adjustment_logs(
            session,
            user_id=user_id,
            evaluated_after=cutoff,
            limit=5000,
        )
        seen: frozenset = frozenset(
            (
                getattr(r, "item_ref", ""),
                int(getattr(r, "intrinsic_rank", 0) or 0),
                int(getattr(r, "adjusted_rank", 0) or 0),
            )
            for r in recent
        )

        inserted: List[Any] = []
        for t in transitions:
            key = (t["item_ref"], t["intrinsic_rank"], t["adjusted_rank"])
            if key in seen:
                continue
            row = await add_relevance_adjustment_log(
                session,
                user_id         = user_id,
                surface         = surface,
                run_reason      = "shadow",
                item_ref        = t["item_ref"],
                intrinsic_rank  = t["intrinsic_rank"],
                adjusted_rank   = t["adjusted_rank"],
                relevance_weight = round(t["relevance_adjustment"] - 1.0, 6),
                prominence_tier = t["prominence_tier"],
                floor_applied   = t["floor_applied"],
            )
            if row is not None:
                inserted.append(row)

        return inserted
    except Exception as exc:
        logger.debug("[shadow] record_relevance_transition_events failed: %r", exc)
        return []
