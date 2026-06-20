"""
Personal Experience Memory Context + Session Continuity — Phase 18 · Slice 6.

The session continuity layer.  Answers, per user:

  - What was I researching?         (get_last_research_context)
  - What changed since my visit?    (build_resume_candidates)
  - What should I resume?           (build_resume_candidates, ranked)
  - What prior thesis work to        (build_revisit_candidates)
    continue?

This module reads PersonalExperienceCursor (the user's view history),
PersonalExperienceEvent (the surfacing log), and the Slice 18.3 change
candidates.  It produces structured continuity context only — it never
delivers, ranks for the feed, or surfaces anything to a user.

Core idea
---------
A cursor row records that the user *looked at* an entity (last_seen_at,
last_state_hash, view_count).  A change candidate records that the entity
*changed*.  The intersection — entities the user engaged with that have
since changed — is the resume set.  continuation_score orders it.

Flag gate
---------
All async functions are gated on experience_memory_enabled (default False).

Null-session contract
---------------------
All async functions return None / [] / {} when session=None.

SP-18 invariants
----------------
  SP-18a: no advisory language.
  SP-18b: ordering does not change truth.
  SP-18c: writes nothing.
  SP-18d: no upstream feedback — reads only.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_DEFAULT_RESUME_LIMIT: int = 5
_DEFAULT_REVISIT_LIMIT: int = 5
_DEFAULT_RECENT_LIMIT: int = 10
_ENGAGEMENT_SATURATION: float = 5.0  # view_count at which engagement == 1.0


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _enabled(override: Optional[bool] = None) -> bool:
    if override is not None:
        return bool(override)
    try:
        from app.config import settings
        return bool(getattr(settings, "experience_memory_enabled", False))
    except Exception:
        return False


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _attr(obj: Any, name: str, default: Any = None) -> Any:
    val = getattr(obj, name, None)
    return val if val is not None else default


def _clamp(val: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, val))


def _iso(ts: Any) -> Optional[str]:
    if ts is None:
        return None
    if isinstance(ts, str):
        return ts
    try:
        if hasattr(ts, "tzinfo") and ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return ts.isoformat()
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Pure scoring
# ---------------------------------------------------------------------------

def compute_continuation_score(
    *,
    view_count: int,
    change_magnitude: float,
    recency_score: float = 0.0,
) -> float:
    """How much value there is in resuming work on an entity.

    High when the user engaged with it (view_count) AND it has changed
    materially since (change_magnitude), with a recency bonus.

    engagement = min(1.0, view_count / 5)
    score = engagement * (0.6 * change_magnitude + 0.4 * recency_score)

    Always in [0.0, 1.0].  Returns 0.0 for an unengaged entity.
    """
    engagement = min(1.0, max(0, view_count) / _ENGAGEMENT_SATURATION)
    raw = engagement * (0.6 * _clamp(change_magnitude) + 0.4 * _clamp(recency_score))
    return round(_clamp(raw), 4)


# ---------------------------------------------------------------------------
# Last / recent research context
# ---------------------------------------------------------------------------

def _cursor_to_context(cursor: Any, *, surface: str = "") -> Dict[str, Any]:
    return {
        "entity_key":      _attr(cursor, "entity_key", ""),
        "entity_type":     _attr(cursor, "entity_type", ""),
        "last_seen_at":    _iso(_attr(cursor, "last_seen_at", None)),
        "last_state_hash": _attr(cursor, "last_state_hash", ""),
        "view_count":      int(_attr(cursor, "view_count", 0)),
        "surface":         surface,
    }


async def _latest_surface_for(session, *, user_id: str, item_ref: str) -> str:
    """Best-effort lookup of the surface from the most recent event row.

    Returns "" when no event exists (events arrive in Slice 18.8).
    """
    try:
        from app.db.repositories.personal_experience_repo import list_experience_events
        events = await list_experience_events(
            session, user_id=user_id, item_ref=item_ref, limit=1,
        )
        if events:
            return _attr(events[0], "surface", "")
        return ""
    except Exception:
        return ""


async def get_last_research_context(
    session,
    *,
    user_id: str,
    run_override: Optional[bool] = None,
) -> Optional[Dict[str, Any]]:
    """Return the single most-recently-viewed entity for this user, or None.

    Reads the most recent PersonalExperienceCursor (ordered last_seen_at desc).
    The returned dict carries entity, timestamp, surface, and last_state_hash.
    Returns None when the user has no prior research history.
    """
    if not _enabled(run_override):
        return None
    if session is None:
        return None
    try:
        from app.db.repositories.personal_experience_repo import list_experience_cursors
        cursors = await list_experience_cursors(session, user_id=user_id, limit=1)
        if not cursors:
            return None
        cursor = cursors[0]
        ek = _attr(cursor, "entity_key", "")
        surface = await _latest_surface_for(session, user_id=user_id, item_ref=ek)
        return _cursor_to_context(cursor, surface=surface)
    except Exception as exc:
        logger.debug("[memory] get_last_research_context failed: %r", exc)
        return None


async def get_recent_research_contexts(
    session,
    *,
    user_id: str,
    limit: int = _DEFAULT_RECENT_LIMIT,
    run_override: Optional[bool] = None,
) -> List[Dict[str, Any]]:
    """Return the user's recently-viewed entities, newest first.

    Returns [] when the flag is off, session is None, or no history exists.
    """
    if not _enabled(run_override):
        return []
    if session is None:
        return []
    try:
        from app.db.repositories.personal_experience_repo import list_experience_cursors
        cursors = await list_experience_cursors(session, user_id=user_id, limit=limit)
        return [_cursor_to_context(c) for c in cursors]
    except Exception as exc:
        logger.debug("[memory] get_recent_research_contexts failed: %r", exc)
        return []


# ---------------------------------------------------------------------------
# Resume / revisit candidates
# ---------------------------------------------------------------------------

async def _changes_by_entity(
    session, *, user_id: str, run_override: Optional[bool],
) -> Dict[str, Dict[str, Any]]:
    """Run change detection and index candidates by entity_key.

    When multiple change types exist for one entity, keeps the one with the
    higher recency_score.
    """
    from app.services.personal_experience_change_service import build_change_candidates
    candidates = await build_change_candidates(
        session, user_id=user_id, run_override=run_override,
    )
    by_entity: Dict[str, Dict[str, Any]] = {}
    for c in candidates:
        ek = c.get("entity_key", "")
        existing = by_entity.get(ek)
        if existing is None or c.get("recency_score", 0.0) > existing.get("recency_score", 0.0):
            by_entity[ek] = c
    return by_entity


async def build_resume_candidates(
    session,
    *,
    user_id: str,
    limit: int = _DEFAULT_RESUME_LIMIT,
    run_override: Optional[bool] = None,
) -> List[Dict[str, Any]]:
    """Entities the user researched that have changed since their last visit.

    For each cursor (researched entity), check whether a change candidate
    exists (changed since last seen).  Build a resume candidate with
    continuation_score.  Sorted by continuation_score desc.

    Returns [] when the flag is off or session is None.
    """
    if not _enabled(run_override):
        return []
    if session is None:
        return []
    try:
        from app.db.repositories.personal_experience_repo import list_experience_cursors

        cursors = await list_experience_cursors(session, user_id=user_id, limit=200)
        if not cursors:
            return []

        changes = await _changes_by_entity(
            session, user_id=user_id, run_override=run_override,
        )

        resume: List[Dict[str, Any]] = []
        for cursor in cursors:
            ek = _attr(cursor, "entity_key", "")
            change = changes.get(ek)
            changed = change is not None
            recency = float(change.get("recency_score", 0.0)) if change else 0.0
            novelty = float(change.get("novelty_score", 0.0)) if change else 0.0
            magnitude = max(recency, novelty)
            score = compute_continuation_score(
                view_count=int(_attr(cursor, "view_count", 0)),
                change_magnitude=magnitude,
                recency_score=recency,
            )
            resume.append({
                "entity_key":               ek,
                "entity_type":              _attr(cursor, "entity_type", ""),
                "changed_since_last_seen":  changed,
                "change_type":              change.get("change_type", "") if change else "",
                "last_seen_at":             _iso(_attr(cursor, "last_seen_at", None)),
                "continuation_score":       score,
            })

        resume.sort(key=lambda r: r["continuation_score"], reverse=True)
        return resume[:limit]
    except Exception as exc:
        logger.debug("[memory] build_resume_candidates failed: %r", exc)
        return []


async def build_revisit_candidates(
    session,
    *,
    user_id: str,
    limit: int = _DEFAULT_REVISIT_LIMIT,
    run_override: Optional[bool] = None,
) -> List[Dict[str, Any]]:
    """Previously-researched entities whose analysis was updated.

    Uses detect_memory_changes (Slice 18.3) — entities with a cursor whose
    ticker_memory was updated after the user last looked.  Each carries a
    continuation_score.  Sorted by continuation_score desc.

    Returns [] when the flag is off or session is None.
    """
    if not _enabled(run_override):
        return []
    if session is None:
        return []
    try:
        from app.services.personal_experience_change_service import detect_memory_changes
        from app.db.repositories.personal_experience_repo import get_experience_cursor

        memory_changes = await detect_memory_changes(
            session, user_id=user_id, run_override=run_override,
        )

        revisit: List[Dict[str, Any]] = []
        for change in memory_changes:
            ek = change.get("entity_key", "")
            cursor = await get_experience_cursor(
                session, user_id=user_id, entity_type="ticker", entity_key=ek,
            )
            view_count = int(_attr(cursor, "view_count", 0)) if cursor else 0
            recency = float(change.get("recency_score", 0.0))
            novelty = float(change.get("novelty_score", 0.0))
            score = compute_continuation_score(
                view_count=view_count,
                change_magnitude=max(recency, novelty),
                recency_score=recency,
            )
            revisit.append({
                "entity_key":         ek,
                "entity_type":        change.get("entity_type", "company"),
                "change_type":        change.get("change_type", "memory_revisit"),
                "last_seen_at":       _iso(_attr(cursor, "last_seen_at", None)) if cursor else None,
                "continuation_score": score,
                "explanation_text":   change.get("explanation_text", ""),
            })

        revisit.sort(key=lambda r: r["continuation_score"], reverse=True)
        return revisit[:limit]
    except Exception as exc:
        logger.debug("[memory] build_revisit_candidates failed: %r", exc)
        return []


# ---------------------------------------------------------------------------
# Aggregate continuity context
# ---------------------------------------------------------------------------

async def build_session_continuity(
    session,
    *,
    user_id: str,
    run_override: Optional[bool] = None,
) -> Dict[str, Any]:
    """Full session continuity context for one user.

    Returns a dict with:
      last_research        — most recent research context (or None)
      recent_research      — list of recent research contexts
      resume_candidates    — entities to resume (changed since last seen)
      revisit_candidates   — entities with updated analysis
      generated_at         — ISO timestamp

    Returns an empty (but structurally complete) dict when the flag is off
    or session is None.
    """
    empty = {
        "last_research":      None,
        "recent_research":    [],
        "resume_candidates":  [],
        "revisit_candidates": [],
        "generated_at":       _now().isoformat(),
    }
    if not _enabled(run_override):
        return empty
    if session is None:
        return empty
    try:
        last_research = await get_last_research_context(
            session, user_id=user_id, run_override=run_override)
        recent = await get_recent_research_contexts(
            session, user_id=user_id, run_override=run_override)
        resume = await build_resume_candidates(
            session, user_id=user_id, run_override=run_override)
        revisit = await build_revisit_candidates(
            session, user_id=user_id, run_override=run_override)
        return {
            "last_research":      last_research,
            "recent_research":    recent,
            "resume_candidates":  resume,
            "revisit_candidates": revisit,
            "generated_at":       _now().isoformat(),
        }
    except Exception as exc:
        logger.debug("[memory] build_session_continuity failed: %r", exc)
        return empty


async def build_welcome_back_context(
    session,
    *,
    user_id: str,
    run_override: Optional[bool] = None,
) -> Dict[str, Any]:
    """Compact 'welcome back' summary for one user.

    Returns a dict with:
      last_researched_entity — entity_key of the most recent research (or None)
      changed_items_count    — number of resume candidates that changed
      top_resume_candidate   — highest continuation_score resume candidate (or None)
      revisit_candidates     — list of revisit candidates
      generated_at           — ISO timestamp

    Returns an empty (but structurally complete) dict when the flag is off
    or session is None.
    """
    empty = {
        "last_researched_entity": None,
        "changed_items_count":    0,
        "top_resume_candidate":   None,
        "revisit_candidates":     [],
        "generated_at":           _now().isoformat(),
    }
    if not _enabled(run_override):
        return empty
    if session is None:
        return empty
    try:
        last_research = await get_last_research_context(
            session, user_id=user_id, run_override=run_override)
        resume = await build_resume_candidates(
            session, user_id=user_id, run_override=run_override)
        revisit = await build_revisit_candidates(
            session, user_id=user_id, run_override=run_override)

        changed = [r for r in resume if r.get("changed_since_last_seen")]
        top_resume = changed[0] if changed else None

        return {
            "last_researched_entity": (
                last_research.get("entity_key") if last_research else None
            ),
            "changed_items_count":    len(changed),
            "top_resume_candidate":   top_resume,
            "revisit_candidates":     revisit,
            "generated_at":           _now().isoformat(),
        }
    except Exception as exc:
        logger.debug("[memory] build_welcome_back_context failed: %r", exc)
        return empty
