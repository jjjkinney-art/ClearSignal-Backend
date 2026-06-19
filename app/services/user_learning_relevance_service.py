"""
User Learning Relevance Service — Phase 15 · Slice 8.

Converts learned preferences into relevance adjustments for feed and alert
ranking projections.  All output is shadow-only — no truth table is modified,
no ranking is applied directly.

Core rule
---------
Relevance may influence ordering.  It may not alter truth.

This module NEVER writes to, reads from, or imports any function from:
  forecast_repo, similarity_repo, decision_repo, scenario_repo,
  dossier, ticker_memory, conviction, order, or execution.

It reads ONLY from learned_preference (via user_learning_repo).
It NEVER writes to any table and NEVER calls upsert / insert / delete.

Flag gate
---------
All public functions are gated on learning_inference_enabled (default False).
When the flag is off every function returns an empty result immediately.

Null-session contract
---------------------
Every public function returns an empty result when session=None — never raises.

Item input shape
----------------
{
    "item_ref":        str,   # unique identifier for the item
    "entity_key":      str,   # ticker, sector_id, theme_key, etc.
    "entity_type":     str,   # "company" | "sector" | "theme" | "horizon" | "signal_type"
    "signal_type":     str,   # signal category (used for floor evaluation)
    "intrinsic_rank":  int,   # 1-based original rank before personalisation
    "intrinsic_score": float, # original relevance score, 0.0–1.0
}

Projection output shape (per item in build_relevance_projection)
----------------------------------------------------------------
{
    "item_ref":               str,
    "entity_key":             str,
    "entity_type":            str,
    "signal_type":            str,
    "intrinsic_rank":         int,
    "adjusted_rank":          int,
    "intrinsic_score":        float,
    "relevance_score":        float,   # intrinsic_score × relevance_adjustment
    "relevance_adjustment":   float,   # multiplicative factor; 1.0 = no change
    "adjustment_reason":      str,     # "positive_pref:…" | "ignored_pref:…" | "no_preference"
    "novelty_reserve_applied": bool,   # True when promoted by anti-filter-bubble reserve
    "relevance_floor_applied": bool,   # True when SP-7d floor raised prominence
    "prominence_tier":        str,     # "pinned" | "normal" | "muted"
}

SP-7 invariants
---------------
  SP-7a: no write to any truth table.
  SP-7b: no import of any write function from forecast / decision /
         scenario / similarity repos.
  SP-7c: user learning may influence ordering / prominence / feed ranking only.
  SP-7d: relevance floor enforced — critical signals may be demoted but not
         suppressed.  Minimum prominence for critical signal_types is "normal".
  SP-7f: no banned advisory phrases in any generated string.
  SP-7h: produces ranking projections only — no changes are applied here.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MAX_BOOST: float = 0.50
_MAX_PENALTY: float = 0.40
_PINNED_TIER_FACTOR: float = 1.20
_MUTED_TIER_FACTOR: float = 0.85
_FACTOR_FLOOR: float = 0.10
_DEFAULT_NOVELTY_RESERVE: float = 0.15
_MIN_ITEMS_FOR_RESERVE: int = 4

# Signal categories that activate the SP-7d relevance floor.
# Items carrying these signal categories may not be demoted below "normal".
_CRITICAL_SIGNAL_TYPES: frozenset = frozenset({
    "earnings",
    "earnings_beat",
    "earnings_miss",
    "credit_downgrade",
    "regulatory_action",
    "acquisition",
    "merger",
})

# For each entity_type, which preference dimensions indicate positive interest?
_POSITIVE_DIMENSIONS: Dict[str, List[str]] = {
    "company":     ["company_interest", "portfolio_sensitivity"],
    "sector":      ["sector_interest"],
    "theme":       ["theme_interest"],
    "horizon":     ["preferred_horizon"],
    "signal_type": ["preferred_signal_type"],
}

# For each entity_type, which preference dimensions indicate negative interest?
_NEGATIVE_DIMENSIONS: Dict[str, List[str]] = {
    "signal_type": ["ignored_signal_type"],
}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _relevance_enabled(override: Optional[bool] = None) -> bool:
    if override is not None:
        return bool(override)
    try:
        from app.config import settings
        return bool(getattr(settings, "learning_inference_enabled", False))
    except Exception:
        return False


def _attr(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _prominence_tier(factor: float) -> str:
    if factor >= _PINNED_TIER_FACTOR:
        return "pinned"
    if factor < _MUTED_TIER_FACTOR:
        return "muted"
    return "normal"


def _apply_floor(tier: str, signal_type: str) -> Tuple[str, bool]:
    """Apply SP-7d relevance floor for critical signal categories.

    Returns (effective_tier, floor_applied).
    """
    if signal_type in _CRITICAL_SIGNAL_TYPES and tier == "muted":
        return "normal", True
    return tier, False


def _compute_item_factor(
    pref_index: Dict[Tuple[str, str], Any],
    *,
    entity_key: str,
    entity_type: str,
) -> Tuple[float, str]:
    """Compute the relevance factor and reason for a single item.

    Returns (factor, reason_str).  Factor is clamped to [_FACTOR_FLOOR, ∞).
    """
    best_positive: float = 0.0
    pos_dimension: Optional[str] = None
    for dim in _POSITIVE_DIMENSIONS.get(entity_type, []):
        pref = pref_index.get((dim, entity_key))
        if pref is None:
            continue
        if _attr(pref, "status", "") == "falsified":
            continue
        affinity   = float(_attr(pref, "affinity", 0.0) or 0.0)
        confidence = float(_attr(pref, "confidence", 0.0) or 0.0)
        boost = affinity * confidence * _MAX_BOOST
        if boost > best_positive:
            best_positive = boost
            pos_dimension = dim

    best_negative: float = 0.0
    neg_dimension: Optional[str] = None
    for dim in _NEGATIVE_DIMENSIONS.get(entity_type, []):
        pref = pref_index.get((dim, entity_key))
        if pref is None:
            continue
        if _attr(pref, "status", "") == "falsified":
            continue
        affinity   = float(_attr(pref, "affinity", 0.0) or 0.0)
        confidence = float(_attr(pref, "confidence", 0.0) or 0.0)
        penalty = abs(affinity) * confidence * _MAX_PENALTY
        if penalty > best_negative:
            best_negative = penalty
            neg_dimension = dim

    net = best_positive - best_negative
    factor = max(_FACTOR_FLOOR, 1.0 + net)

    if pos_dimension is not None and neg_dimension is None:
        reason = f"positive_pref:{pos_dimension}:{entity_key}"
    elif neg_dimension is not None and pos_dimension is None:
        reason = f"ignored_pref:{neg_dimension}:{entity_key}"
    elif pos_dimension is not None and neg_dimension is not None:
        reason = f"mixed_pref:{pos_dimension}+{neg_dimension}:{entity_key}"
    else:
        reason = "no_preference"

    return factor, reason


def _compute_item_adjustment(
    item: Dict[str, Any],
    *,
    pref_index: Dict[Tuple[str, str], Any],
) -> Dict[str, Any]:
    """Build one projection dict from an item and preference index.

    adjusted_rank is set to 0; callers assign the final rank after sorting.
    """
    entity_key      = item.get("entity_key", "") or ""
    entity_type     = item.get("entity_type", "") or ""
    signal_type     = item.get("signal_type", "") or ""
    intrinsic_score = float(item.get("intrinsic_score") or 0.0)
    intrinsic_rank  = int(item.get("intrinsic_rank") or 0)

    factor, reason = _compute_item_factor(
        pref_index, entity_key=entity_key, entity_type=entity_type,
    )

    relevance_score = round(intrinsic_score * factor, 6)
    tier = _prominence_tier(factor)
    effective_tier, floor_applied = _apply_floor(tier, signal_type)

    return {
        "item_ref":               item.get("item_ref", "") or "",
        "entity_key":             entity_key,
        "entity_type":            entity_type,
        "signal_type":            signal_type,
        "intrinsic_rank":         intrinsic_rank,
        "adjusted_rank":          0,
        "intrinsic_score":        intrinsic_score,
        "relevance_score":        relevance_score,
        "relevance_adjustment":   round(factor, 6),
        "adjustment_reason":      reason,
        "novelty_reserve_applied": False,
        "relevance_floor_applied": floor_applied,
        "prominence_tier":        effective_tier,
    }


def _empty_adjustment(item: Dict[str, Any]) -> Dict[str, Any]:
    intrinsic_score = float(item.get("intrinsic_score") or 0.0)
    return {
        "item_ref":               item.get("item_ref", "") or "",
        "entity_key":             item.get("entity_key", "") or "",
        "entity_type":            item.get("entity_type", "") or "",
        "signal_type":            item.get("signal_type", "") or "",
        "intrinsic_rank":         int(item.get("intrinsic_rank") or 0),
        "adjusted_rank":          int(item.get("intrinsic_rank") or 0),
        "intrinsic_score":        intrinsic_score,
        "relevance_score":        intrinsic_score,
        "relevance_adjustment":   1.0,
        "adjustment_reason":      "no_preference",
        "novelty_reserve_applied": False,
        "relevance_floor_applied": False,
        "prominence_tier":        "normal",
    }


def _empty_reserve_summary(reserve_fraction: float) -> Dict[str, Any]:
    return {
        "reserve_fraction_target": round(reserve_fraction, 4),
        "reserve_fraction_actual": 0.0,
        "novel_item_count":        0,
        "protected_count":         0,
        "reserve_applied":         False,
        "reserve_item_refs":       [],
    }


def _empty_floor_result(item: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "item_ref":                  item.get("item_ref", "") or "",
        "signal_type":               item.get("signal_type", "") or "",
        "floor_applied":             False,
        "original_prominence_tier":  "normal",
        "effective_prominence_tier": "normal",
    }


async def _load_preference_index(
    session,
    *,
    user_id: str,
) -> Dict[Tuple[str, str], Any]:
    """Load all non-falsified preferences for user_id into a (dimension, entity_key) map."""
    try:
        from app.db.repositories.user_learning_repo import list_learned_preferences

        rows = await list_learned_preferences(session, user_id=user_id)
        return {
            (_attr(r, "dimension", ""), _attr(r, "entity_key", "")): r
            for r in rows
            if _attr(r, "status", "") != "falsified"
        }
    except Exception as exc:
        logger.debug("[relevance] _load_preference_index failed: %r", exc)
        return {}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def compute_relevance_adjustment(
    session,
    *,
    user_id: str,
    item: Dict[str, Any],
    run_override: Optional[bool] = None,
) -> Dict[str, Any]:
    """Compute relevance adjustment for a single item.

    Loads the user's learned preferences and returns a projection dict with
    relevance_score, relevance_adjustment, adjustment_reason, and prominence
    metadata.

    novelty_reserve_applied is always False for single-item calls — reserve
    analysis requires a full ranked list (see build_relevance_projection).

    Returns an identity adjustment (factor=1.0) when the flag is off,
    session is None, or no matching preference exists.
    """
    if not _relevance_enabled(run_override):
        return _empty_adjustment(item)
    if session is None:
        return _empty_adjustment(item)
    try:
        pref_index = await _load_preference_index(session, user_id=user_id)
        adj = _compute_item_adjustment(item, pref_index=pref_index)
        adj["adjusted_rank"] = int(item.get("intrinsic_rank") or 1)
        return adj
    except Exception as exc:
        logger.debug("[relevance] compute_relevance_adjustment failed: %r", exc)
        return _empty_adjustment(item)


async def apply_relevance_adjustment(
    session,
    *,
    user_id: str,
    items: List[Dict[str, Any]],
    run_override: Optional[bool] = None,
) -> List[Dict[str, Any]]:
    """Apply relevance adjustments to a list of items and re-rank by score.

    Returns the items sorted by relevance_score descending, with adjusted_rank
    assigned (1 = most relevant after personalisation).
    Tie-breaks on item_ref ascending for deterministic output.

    When the flag is off or session is None, returns items with identity
    adjustments sorted by intrinsic_rank.
    """
    if not _relevance_enabled(run_override) or session is None:
        result = [_empty_adjustment(item) for item in items]
        result.sort(key=lambda x: (x["intrinsic_rank"], x["item_ref"]))
        for i, r in enumerate(result, start=1):
            r["adjusted_rank"] = i
        return result
    try:
        pref_index = await _load_preference_index(session, user_id=user_id)
        adjusted = [_compute_item_adjustment(item, pref_index=pref_index) for item in items]
        adjusted.sort(key=lambda x: (-x["relevance_score"], x["item_ref"]))
        for i, item in enumerate(adjusted, start=1):
            item["adjusted_rank"] = i
        return adjusted
    except Exception as exc:
        logger.debug("[relevance] apply_relevance_adjustment failed: %r", exc)
        return [_empty_adjustment(item) for item in items]


async def compute_novelty_reserve(
    session,
    *,
    user_id: str,
    items: List[Dict[str, Any]],
    reserve_fraction: float = _DEFAULT_NOVELTY_RESERVE,
    run_override: Optional[bool] = None,
) -> Dict[str, Any]:
    """Compute novelty reserve statistics for an already-adjusted item list.

    A "novel" item has adjustment_reason="no_preference" — it has no matching
    learned preference and may be buried by personalisation.  The reserve
    ensures a minimum fraction of top-ranked items stays novel, preventing
    the personalisation layer from collapsing the feed into a filter bubble.

    Input items are expected to have adjusted_rank set (from
    apply_relevance_adjustment or build_relevance_projection).

    reserve_applied is True only when items had to be promoted to fill the
    reserve slots — False when the reserve was naturally met or when no novel
    items exist to promote.

    Returns a summary dict.  Does not modify the items list.
    """
    if not _relevance_enabled(run_override):
        return _empty_reserve_summary(reserve_fraction)
    if session is None:
        return _empty_reserve_summary(reserve_fraction)
    try:
        n = len(items)
        if n == 0:
            return _empty_reserve_summary(reserve_fraction)

        reserve_count = max(1, int(n * reserve_fraction)) if n >= _MIN_ITEMS_FOR_RESERVE else 0

        novel_items = [x for x in items if x.get("adjustment_reason") == "no_preference"]

        sorted_items = sorted(
            items,
            key=lambda x: (x.get("adjusted_rank", 99999), x.get("item_ref", "")),
        )
        top_n = sorted_items[:reserve_count]
        top_novel = [x for x in top_n if x.get("adjustment_reason") == "no_preference"]

        needed = min(reserve_count, len(novel_items))
        reserve_already_met = (len(top_novel) >= needed) or reserve_count == 0

        if not reserve_already_met:
            unpromoted = [x for x in novel_items if x not in top_novel]
            unpromoted.sort(key=lambda x: -x.get("intrinsic_score", 0.0))
            slots = min(reserve_count - len(top_novel), len(unpromoted))
            protected_refs = (
                [x["item_ref"] for x in top_novel]
                + [x["item_ref"] for x in unpromoted[:slots]]
            )
        else:
            protected_refs = [x["item_ref"] for x in top_novel]

        actual_fraction = len(protected_refs) / n if n > 0 else 0.0

        return {
            "reserve_fraction_target": round(reserve_fraction, 4),
            "reserve_fraction_actual": round(actual_fraction, 4),
            "novel_item_count":        len(novel_items),
            "protected_count":         len(protected_refs),
            "reserve_applied":         not reserve_already_met and len(novel_items) > 0,
            "reserve_item_refs":       protected_refs,
        }
    except Exception as exc:
        logger.debug("[relevance] compute_novelty_reserve failed: %r", exc)
        return _empty_reserve_summary(reserve_fraction)


async def compute_relevance_floor(
    session,
    *,
    user_id: str,
    item: Dict[str, Any],
    run_override: Optional[bool] = None,
) -> Dict[str, Any]:
    """Compute the SP-7d relevance floor for a single item.

    Critical signal categories (earnings, credit events, regulatory actions)
    cannot be demoted below "normal" prominence regardless of personalisation.
    This function determines whether the floor applies and what the effective
    prominence tier is.

    Returns a floor analysis dict.  Does not modify any table.
    """
    if not _relevance_enabled(run_override):
        return _empty_floor_result(item)
    if session is None:
        return _empty_floor_result(item)
    try:
        adj = await compute_relevance_adjustment(
            session, user_id=user_id, item=item, run_override=run_override,
        )
        pre_floor_tier = _prominence_tier(adj["relevance_adjustment"])
        effective_tier = adj["prominence_tier"]
        floor_applied  = adj["relevance_floor_applied"]
        return {
            "item_ref":                  item.get("item_ref", "") or "",
            "signal_type":               item.get("signal_type", "") or "",
            "floor_applied":             floor_applied,
            "original_prominence_tier":  pre_floor_tier,
            "effective_prominence_tier": effective_tier,
        }
    except Exception as exc:
        logger.debug("[relevance] compute_relevance_floor failed: %r", exc)
        return _empty_floor_result(item)


async def build_relevance_projection(
    session,
    *,
    user_id: str,
    items: List[Dict[str, Any]],
    run_override: Optional[bool] = None,
) -> List[Dict[str, Any]]:
    """Build a full relevance projection for a ranked list of items.

    Orchestrates:
      1. Preference index load (single DB round-trip).
      2. Per-item factor computation (boost / penalty / floor).
      3. Re-rank by relevance_score descending (tie-break: item_ref ascending).
      4. Novelty reserve: mark novel items promoted to fill the anti-filter-bubble
         reserve slots.
      5. SP-7d floor: ensure critical signal categories are not muted.

    Returns a list of projection dicts with all 12 fields set.  Length equals
    input items length.  Returns [] when the flag is off, session is None, or
    items is empty.  Never raises.
    """
    if not _relevance_enabled(run_override):
        return []
    if session is None:
        return []
    if not items:
        return []
    try:
        pref_index = await _load_preference_index(session, user_id=user_id)

        adjusted = [_compute_item_adjustment(item, pref_index=pref_index) for item in items]

        adjusted.sort(key=lambda x: (-x["relevance_score"], x["item_ref"]))
        for i, item in enumerate(adjusted, start=1):
            item["adjusted_rank"] = i

        n = len(adjusted)
        if n >= _MIN_ITEMS_FOR_RESERVE:
            reserve_count = max(1, int(n * _DEFAULT_NOVELTY_RESERVE))
            novel_all  = [x for x in adjusted if x["adjustment_reason"] == "no_preference"]
            top_novel  = [x for x in adjusted[:reserve_count]
                          if x["adjustment_reason"] == "no_preference"]

            needed = min(reserve_count, len(novel_all))
            if len(top_novel) < needed:
                unpromoted = [x for x in novel_all if x not in top_novel]
                unpromoted.sort(key=lambda x: -x["intrinsic_score"])
                slots = min(reserve_count - len(top_novel), len(unpromoted))
                for item in unpromoted[:slots]:
                    item["novelty_reserve_applied"] = True

        return adjusted
    except Exception as exc:
        logger.debug("[relevance] build_relevance_projection failed: %r", exc)
        return []
