"""
Personal Experience Brief Builder — Phase 18 · Slice 7.

Generates a structured daily brief per user from the composer's ranked,
explained output and the memory service's session continuity context.

Core question: "What changed, why does it matter, what deserves
attention, and what can be ignored?"

Brief sections
--------------
  1. what_changed       — items with recency_score > 0.5 AND material change
  2. why_it_matters     — items with attention_priority > 0.5 AND valid explanation
  3. deserves_attention  — items with attention_priority > 0.7
  4. can_be_ignored      — items with composite_score < 0.2 and no material change
                          (only when user tracks > 20 entities)
  5. resume_previous_research — session continuity resume candidates

All text is deterministic and template-derived.  No LLM prose.

Flag gate
---------
All async functions are gated on experience_brief_enabled (default False).

Null-session contract
---------------------
All async functions return None / [] / {} when session=None.

SP-18 invariants
----------------
  SP-18a: no advisory language.  All text is templated.
  SP-18b: ordering does not change truth.
  SP-18c: writes only personal_brief_snapshot (via store_brief_metadata).
  SP-18d: no upstream feedback — reads only.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

_RECENCY_CUTOFF: float = 0.5
_ATTENTION_MATTERS_CUTOFF: float = 0.5
_ATTENTION_DESERVES_CUTOFF: float = 0.7
_IGNORE_SCORE_CEILING: float = 0.2
_IGNORE_ENTITY_FLOOR: int = 20


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _enabled(override: Optional[bool] = None) -> bool:
    if override is not None:
        return bool(override)
    try:
        from app.config import settings
        return bool(getattr(settings, "experience_brief_enabled", False))
    except Exception:
        return False


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _today() -> date:
    return _now().date()


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
# Section builders — pure functions over composed experience items
# ---------------------------------------------------------------------------

def build_what_changed(
    items: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Items with recency_score > 0.5 AND a material change detected.

    Returns a list of section entries, each with entity_key, change_type,
    what_changed, and recency_score.
    """
    result: List[Dict[str, Any]] = []
    for item in items:
        if not item.get("explanation_valid", False):
            continue
        recency = float(item.get("recency_score", 0.0))
        if recency <= _RECENCY_CUTOFF:
            continue
        change_type = item.get("change_type", "")
        if not change_type:
            continue
        result.append({
            "entity_key":    item.get("entity_key", ""),
            "entity_type":   item.get("entity_type", ""),
            "change_type":   change_type,
            "what_changed":  item.get("what_changed", ""),
            "recency_score": recency,
        })
    result.sort(key=lambda x: x["recency_score"], reverse=True)
    return result


def build_why_it_matters(
    items: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Items with attention_priority > 0.5 AND valid explanation.

    Returns a list of section entries, each with entity_key,
    why_am_i_seeing_this, why_now, and attention_priority.
    """
    result: List[Dict[str, Any]] = []
    for item in items:
        if not item.get("explanation_valid", False):
            continue
        priority = float(item.get("attention_priority", 0.0))
        if priority <= _ATTENTION_MATTERS_CUTOFF:
            continue
        result.append({
            "entity_key":           item.get("entity_key", ""),
            "entity_type":          item.get("entity_type", ""),
            "why_am_i_seeing_this": item.get("why_am_i_seeing_this", ""),
            "why_now":              item.get("why_now", ""),
            "attention_priority":   priority,
        })
    result.sort(key=lambda x: x["attention_priority"], reverse=True)
    return result


def build_attention_section(
    items: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Items with attention_priority > 0.7.

    Returns a list of section entries with entity_key, change_type,
    why_now, attention_priority, and composite_score.
    """
    result: List[Dict[str, Any]] = []
    for item in items:
        if not item.get("explanation_valid", False):
            continue
        priority = float(item.get("attention_priority", 0.0))
        if priority <= _ATTENTION_DESERVES_CUTOFF:
            continue
        result.append({
            "entity_key":         item.get("entity_key", ""),
            "entity_type":        item.get("entity_type", ""),
            "change_type":        item.get("change_type", ""),
            "why_now":            item.get("why_now", ""),
            "attention_priority": priority,
            "composite_score":    float(item.get("composite_score", 0.0)),
        })
    result.sort(key=lambda x: x["composite_score"], reverse=True)
    return result


def build_ignore_section(
    items: List[Dict[str, Any]],
    *,
    total_tracked: int = 0,
) -> List[Dict[str, Any]]:
    """Items with composite_score < 0.2 and no material change.

    Only populated when the user tracks > 20 entities.
    Returns [] when total_tracked <= 20.
    """
    if total_tracked <= _IGNORE_ENTITY_FLOOR:
        return []
    result: List[Dict[str, Any]] = []
    for item in items:
        score = float(item.get("composite_score", 0.0))
        if score >= _IGNORE_SCORE_CEILING:
            continue
        change_type = item.get("change_type", "")
        if change_type:
            continue
        result.append({
            "entity_key":      item.get("entity_key", ""),
            "entity_type":     item.get("entity_type", ""),
            "composite_score": score,
        })
    result.sort(key=lambda x: x["composite_score"])
    return result


def build_resume_section(
    resume_candidates: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Format session continuity resume candidates for the brief.

    Returns a list of section entries with entity_key, change_type,
    continuation_score, and last_seen_at.
    """
    result: List[Dict[str, Any]] = []
    for candidate in resume_candidates:
        if not candidate.get("changed_since_last_seen", False):
            continue
        result.append({
            "entity_key":         candidate.get("entity_key", ""),
            "entity_type":        candidate.get("entity_type", ""),
            "change_type":        candidate.get("change_type", ""),
            "continuation_score": float(candidate.get("continuation_score", 0.0)),
            "last_seen_at":       candidate.get("last_seen_at"),
        })
    result.sort(key=lambda x: x["continuation_score"], reverse=True)
    return result


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_brief(brief: Dict[str, Any]) -> Tuple[bool, str]:
    """Validate that a brief passes all quality gates.

    Returns (ok, reason).

    Block conditions:
      - most_important_change is None
      - most_important_change has invalid explanation
      - deserves_attention is empty
      - most_important_change has no supporting_evidence
    """
    mic = brief.get("most_important_change")
    if mic is None:
        return False, "most_important_change is missing"

    if not mic.get("explanation_valid", False):
        return False, "most_important_change has invalid explanation"

    attention = brief.get("deserves_attention", [])
    if not attention:
        return False, "deserves_attention section is empty"

    evidence = mic.get("supporting_evidence", [])
    if not evidence:
        return False, "most_important_change has no supporting_evidence"

    return True, ""


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

async def build_daily_brief(
    session,
    *,
    user_id: str,
    brief_date: Optional[date] = None,
    run_override: Optional[bool] = None,
) -> Optional[Dict[str, Any]]:
    """Generate a structured daily brief for one user.

    Calls compose_experience (surface="brief") and build_session_continuity,
    then structures the output into five sections. Stores a brief snapshot
    row on success.

    Returns None when the flag is off, session is None, or a brief already
    exists for this (user_id, brief_date).
    """
    if not _enabled(run_override):
        return None
    if session is None:
        return None

    target_date = brief_date or _today()

    try:
        from app.db.repositories.personal_experience_repo import (
            get_brief_snapshot,
            add_brief_snapshot,
            count_experience_cursors,
        )
        from app.services.personal_experience_composer_service import (
            compose_experience,
        )
        from app.services.personal_experience_memory_service import (
            build_session_continuity,
        )

        existing = await get_brief_snapshot(
            session, user_id=user_id, brief_date=target_date,
        )
        if existing is not None:
            return None

        composed = await compose_experience(
            session, user_id=user_id, surface="brief",
            run_override=run_override,
        )

        continuity = await build_session_continuity(
            session, user_id=user_id, run_override=run_override,
        )

        all_items = composed.get("items", [])
        valid_items = composed.get("valid_items", [])
        mic = composed.get("most_important")

        total_tracked = await count_experience_cursors(
            session, user_id=user_id,
        )

        what_changed = build_what_changed(valid_items)
        why_matters = build_why_it_matters(valid_items)
        attention = build_attention_section(valid_items)
        ignore = build_ignore_section(
            all_items, total_tracked=total_tracked,
        )
        resume = build_resume_section(
            continuity.get("resume_candidates", []),
        )

        brief: Dict[str, Any] = {
            "brief_date":                str(target_date),
            "most_important_change":     mic,
            "what_changed":              what_changed,
            "why_it_matters":            why_matters,
            "deserves_attention":        attention,
            "can_be_ignored":            ignore,
            "resume_previous_research":  resume,
            "items_count":               composed.get("items_count", 0),
            "valid_count":               composed.get("valid_count", 0),
            "blocked_count":             composed.get("blocked_count", 0),
            "generated_at":              _now().isoformat(),
            "explanation_valid":         False,
        }

        ok, reason = validate_brief(brief)
        brief["explanation_valid"] = ok
        brief["validation_reason"] = reason

        top_attention_key = ""
        if attention:
            top_attention_key = attention[0].get("entity_key", "")
        elif mic:
            top_attention_key = mic.get("entity_key", "")

        await add_brief_snapshot(
            session,
            user_id=user_id,
            brief_date=target_date,
            items_surfaced=composed.get("valid_count", 0),
            items_blocked=composed.get("blocked_count", 0),
            top_attention_item=top_attention_key,
            run_reason="shadow",
        )

        return brief
    except Exception as exc:
        logger.debug("[brief] build_daily_brief failed: %r", exc)
        return None
