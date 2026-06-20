"""
Personal Experience Composer + Explainability — Phase 18 · Slice 5.

Top-level orchestrator: assembles candidates, scores, explains, gates,
ranks, and returns the experience payload.

Core question: "Why is this being surfaced?"

Explainability gate
-------------------
Every surfaced item must answer four questions:
  1. why_am_i_seeing_this — reason this item was selected
  2. why_now — what changed to trigger surfacing
  3. what_changed — the specific delta from previous state
  4. supporting_evidence — at least one concrete evidence reference

If any field is empty or missing, the item is blocked from surfacing.
Blocked items are returned with explanation_valid=False for calibration.

Flag gate
---------
compose_experience is gated on experience_composer_enabled (default False).

Null-session contract
---------------------
All async functions return [] / {} / None when session=None.

SP-18 invariants
----------------
  SP-18a: no advisory language.  All text is templated.
  SP-18b: ordering does not change truth.
  SP-18c: writes nothing (journaling is Slice 18.8).
  SP-18d: no upstream feedback.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

_ATTENTION_QUEUE_MIN_PRIORITY: float = 0.5
_ATTENTION_QUEUE_MAX_ITEMS: int = 5


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _enabled(override: Optional[bool] = None) -> bool:
    if override is not None:
        return bool(override)
    try:
        from app.config import settings
        return bool(getattr(settings, "experience_composer_enabled", False))
    except Exception:
        return False


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Explainability — templated, no LLM prose
# ---------------------------------------------------------------------------

_TEMPLATES = {
    "forecast_changed": {
        "why_seeing": "{entity_key} is on your watchlist or in your portfolio.",
        "why_now":    "Forecast for {entity_key} changed since your last visit.",
        "changed":    "Forecast state differs from what you last saw.",
    },
    "decision_changed": {
        "why_seeing": "{entity_key} has a new attention level.",
        "why_now":    "Attention level for {entity_key} changed.",
        "changed":    "The attention level was re-evaluated.",
    },
    "scenario_changed": {
        "why_seeing": "{entity_key} has an updated scenario assessment.",
        "why_now":    "Scenario plausibility or impact changed for {entity_key}.",
        "changed":    "Scenario conditions were re-evaluated.",
    },
    "watchlist_drift": {
        "why_seeing": "{entity_key} is on your watchlist.",
        "why_now":    "Thesis for {entity_key} changed since your last visit.",
        "changed":    "The thesis state differs from what you last saw.",
    },
    "memory_revisit": {
        "why_seeing": "You previously researched {entity_key}.",
        "why_now":    "New analysis data available for {entity_key}.",
        "changed":    "Analysis was updated since your last visit.",
    },
}


def explain_experience_item(
    candidate: Dict[str, Any],
) -> Dict[str, Any]:
    """Generate a templated explanation for one experience item.

    Returns a dict with four fields + valid flag.  All text is deterministic
    and template-derived.  No LLM prose.

    Returns valid=False when the candidate lacks sufficient context to
    populate all four fields.
    """
    ek = candidate.get("entity_key", "")
    change_type = candidate.get("change_type", "")
    evidence = candidate.get("evidence_refs", [])
    candidate_explanation = candidate.get("explanation_text", "")

    template = _TEMPLATES.get(change_type, {})

    why_seeing = template.get("why_seeing", "").format(entity_key=ek) if template else ""
    why_now = template.get("why_now", "").format(entity_key=ek) if template else ""
    what_changed = candidate_explanation or (
        template.get("changed", "").format(entity_key=ek) if template else ""
    )

    valid = bool(why_seeing and why_now and what_changed and evidence)

    return {
        "why_am_i_seeing_this": why_seeing,
        "why_now":              why_now,
        "what_changed":         what_changed,
        "supporting_evidence":  evidence,
        "explanation_valid":    valid,
    }


def validate_experience_item(item: Dict[str, Any]) -> Tuple[bool, str]:
    """Validate that an experience item passes the explainability gate.

    Returns (ok, reason).
    """
    for field in ("why_am_i_seeing_this", "why_now", "what_changed"):
        val = item.get(field, "")
        if not val or not str(val).strip():
            return False, f"missing or empty: {field}"
    evidence = item.get("supporting_evidence", [])
    if not evidence:
        return False, "missing or empty: supporting_evidence"
    return True, ""


# ---------------------------------------------------------------------------
# Item building
# ---------------------------------------------------------------------------

def build_experience_item(
    scored_candidate: Dict[str, Any],
    explanation: Dict[str, Any],
) -> Dict[str, Any]:
    """Merge a scored candidate with its explanation into a full experience item.

    The item includes all scoring dimensions, composite_score, rank,
    explanation fields, and the explanation_valid flag.
    """
    return {
        "entity_key":            scored_candidate.get("entity_key", ""),
        "entity_type":           scored_candidate.get("entity_type", ""),
        "change_type":           scored_candidate.get("change_type", ""),
        "changed_at":            scored_candidate.get("changed_at"),
        "attention_priority":    scored_candidate.get("attention_priority", 0.0),
        "personal_relevance":    scored_candidate.get("personal_relevance", 0.0),
        "recency_score":         scored_candidate.get("recency_score", 0.0),
        "novelty_score":         scored_candidate.get("novelty_score", 0.0),
        "revisit_score":         scored_candidate.get("revisit_score", 0.0),
        "memory_relevance":      scored_candidate.get("memory_relevance", 0.0),
        "portfolio_relevance":   scored_candidate.get("portfolio_relevance", 0.0),
        "composite_score":       scored_candidate.get("composite_score", 0.0),
        "rank":                  scored_candidate.get("rank", 0),
        "novelty_reserve_applied": scored_candidate.get("novelty_reserve_applied", False),
        "why_am_i_seeing_this":  explanation.get("why_am_i_seeing_this", ""),
        "why_now":               explanation.get("why_now", ""),
        "what_changed":          explanation.get("what_changed", ""),
        "supporting_evidence":   explanation.get("supporting_evidence", []),
        "explanation_valid":     explanation.get("explanation_valid", False),
    }


# ---------------------------------------------------------------------------
# Section builders
# ---------------------------------------------------------------------------

def build_attention_queue(
    items: List[Dict[str, Any]],
    min_priority: float = _ATTENTION_QUEUE_MIN_PRIORITY,
    max_items: int = _ATTENTION_QUEUE_MAX_ITEMS,
) -> List[Dict[str, Any]]:
    """Filter items to those with attention_priority > min_priority.

    Returns at most max_items, sorted by composite_score desc.
    Only items that passed the explainability gate are included.
    """
    qualified = [
        i for i in items
        if i.get("explanation_valid", False)
        and float(i.get("attention_priority", 0.0)) > min_priority
    ]
    qualified.sort(key=lambda x: x.get("composite_score", 0.0), reverse=True)
    return qualified[:max_items]


def build_most_important_change(
    items: List[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Return the single highest-scored valid item, or None.

    Only items that passed the explainability gate are eligible.
    """
    valid = [i for i in items if i.get("explanation_valid", False)]
    if not valid:
        return None
    valid.sort(key=lambda x: x.get("composite_score", 0.0), reverse=True)
    return valid[0]


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

async def compose_experience(
    session,
    *,
    user_id: str,
    surface: str = "home",
    entity_keys: Optional[List[str]] = None,
    run_override: Optional[bool] = None,
) -> Dict[str, Any]:
    """Compose a full experience payload for one user.

    Pipeline:
      1. build_change_candidates → raw change candidates
      2. rank_change_candidates → scored + ranked candidates
      3. explain_experience_item → templated explanations
      4. validate → gate: block items failing explainability
      5. build sections (most_important_change, attention_queue)

    Returns a dict with:
      items             — all experience items (valid + blocked)
      valid_items       — only items that passed explainability
      blocked_items     — items that failed explainability
      most_important    — single highest-scored valid item (or None)
      attention_queue   — top attention items (valid only)
      items_count       — total candidate count
      valid_count       — count of items that passed explainability
      blocked_count     — count of items that failed explainability
      surface           — the surface this was composed for
      composed_at       — ISO timestamp

    Returns empty structure when the flag is off or session is None.
    """
    empty = {
        "items": [], "valid_items": [], "blocked_items": [],
        "most_important": None, "attention_queue": [],
        "items_count": 0, "valid_count": 0, "blocked_count": 0,
        "surface": surface, "composed_at": _now().isoformat(),
    }
    if not _enabled(run_override):
        return empty
    if session is None:
        return empty
    try:
        from app.services.personal_experience_change_service import (
            build_change_candidates,
        )
        from app.services.personal_experience_attention_service import (
            rank_change_candidates,
        )

        candidates = await build_change_candidates(
            session, user_id=user_id, entity_keys=entity_keys,
            run_override=run_override,
        )

        ranked = await rank_change_candidates(
            session, user_id=user_id, candidates=candidates,
            run_override=run_override,
        )

        all_items: List[Dict[str, Any]] = []
        valid_items: List[Dict[str, Any]] = []
        blocked_items: List[Dict[str, Any]] = []

        for scored in ranked:
            explanation = explain_experience_item(scored)
            item = build_experience_item(scored, explanation)

            ok, _ = validate_experience_item(item)
            item["explanation_valid"] = ok
            all_items.append(item)

            if ok:
                valid_items.append(item)
            else:
                blocked_items.append(item)

        mic = build_most_important_change(all_items)
        queue = build_attention_queue(all_items)

        return {
            "items":            all_items,
            "valid_items":      valid_items,
            "blocked_items":    blocked_items,
            "most_important":   mic,
            "attention_queue":  queue,
            "items_count":      len(all_items),
            "valid_count":      len(valid_items),
            "blocked_count":    len(blocked_items),
            "surface":          surface,
            "composed_at":      _now().isoformat(),
        }
    except Exception as exc:
        logger.debug("[composer] compose_experience failed: %r", exc)
        return empty
