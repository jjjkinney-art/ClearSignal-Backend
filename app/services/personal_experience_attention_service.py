"""
Personal Experience Attention Scoring Service — Phase 18 · Slice 4.

Scores change candidates on 7 dimensions and produces a composite
experience_score for ranking.  Pure computation over upstream data —
no writes except returning scored dicts.

Core question: "Of all detected changes, what deserves attention first?"

Scoring dimensions
------------------
  attention_priority   — urgency from decision intelligence (Phase 13)
  personal_relevance   — alignment with learned preferences (Phase 15)
  recency_score        — how recently the change occurred (from 18.3)
  novelty_score        — how new this is to this user (from 18.3)
  revisit_score        — prior engagement × magnitude of change
  memory_relevance     — depth of user's research history with this entity
  portfolio_relevance  — position weight in the user's portfolio

Composite
---------
  experience_score = weighted sum of 7 dimensions.
  Default weights from spec: attention=0.25, relevance=0.20, recency=0.15,
  novelty=0.10, revisit=0.10, memory=0.10, portfolio=0.10.
  Weight bounds: 0.05 <= w <= 0.40, sum == 1.0.

Structural rules
----------------
  Attention floor: items with attention_priority > 0.8 are never ranked
  below position 5.
  Novelty reserve: 15% of top slots reserved for items with no matching
  preference (anti-filter-bubble).

Flag gate
---------
All async functions gated on experience_attention_enabled (default False).

Null-session contract
---------------------
All async functions return [] / {} when session=None.

SP-18 invariants
----------------
  SP-18a: no advisory language.
  SP-18b: scores do not change truth — ordering is presentation.
  SP-18c: writes nothing.
  SP-18d: no upstream feedback.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Default weights (spec §Scoring Dimensions)
# ---------------------------------------------------------------------------

DEFAULT_WEIGHTS: Dict[str, float] = {
    "attention_priority":  0.25,
    "personal_relevance":  0.20,
    "recency_score":       0.15,
    "novelty_score":       0.10,
    "revisit_score":       0.10,
    "memory_relevance":    0.10,
    "portfolio_relevance": 0.10,
}

_WEIGHT_MIN: float = 0.05
_WEIGHT_MAX: float = 0.40
_WEIGHT_SUM_TOL: float = 0.001

_ATTENTION_FLOOR_CUTOFF: float = 0.80
_ATTENTION_FLOOR_RANK: int = 5

_NOVELTY_RESERVE_FRACTION: float = 0.15
_MIN_ITEMS_FOR_RESERVE: int = 4


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _enabled(override: Optional[bool] = None) -> bool:
    if override is not None:
        return bool(override)
    try:
        from app.config import settings
        return bool(getattr(settings, "experience_attention_enabled", False))
    except Exception:
        return False


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _attr(obj: Any, name: str, default: Any = None) -> Any:
    val = getattr(obj, name, None)
    return val if val is not None else default


def _clamp(val: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, val))


# ---------------------------------------------------------------------------
# Weight validation
# ---------------------------------------------------------------------------

def validate_weights(weights: Dict[str, float]) -> Tuple[bool, str]:
    """Validate weight dict.  Returns (ok, reason).

    Requirements: all 7 dimensions present, each in [0.05, 0.40], sum == 1.0.
    """
    for key in DEFAULT_WEIGHTS:
        if key not in weights:
            return False, f"missing dimension: {key}"
    for key, val in weights.items():
        if key not in DEFAULT_WEIGHTS:
            return False, f"unknown dimension: {key}"
        if val < _WEIGHT_MIN - _WEIGHT_SUM_TOL:
            return False, f"{key}={val} below minimum {_WEIGHT_MIN}"
        if val > _WEIGHT_MAX + _WEIGHT_SUM_TOL:
            return False, f"{key}={val} above maximum {_WEIGHT_MAX}"
    total = sum(weights.values())
    if abs(total - 1.0) > _WEIGHT_SUM_TOL:
        return False, f"weights sum to {total}, not 1.0"
    return True, ""


# ---------------------------------------------------------------------------
# Individual dimension scoring (pure functions)
# ---------------------------------------------------------------------------

async def compute_attention_priority(
    session,
    *,
    entity_key: str,
    entity_type: str = "company",
    run_override: Optional[bool] = None,
) -> float:
    """Attention priority from decision intelligence (Phase 13).

    Maps decision_priority bucket to a [0, 1] score:
      critical=1.0, high=0.8, medium=0.5, low=0.3, informational=0.1
    Returns 0.0 when no decision_priority row exists.
    """
    if not _enabled(run_override):
        return 0.0
    if session is None:
        return 0.0
    try:
        from app.db.models import DecisionPriority
        from sqlalchemy import select

        stmt = (
            select(DecisionPriority)
            .where(
                DecisionPriority.entity_key == entity_key,
                DecisionPriority.entity_type == entity_type,
            )
            .order_by(DecisionPriority.decision_rank_score.desc())
            .limit(1)
        )
        result = await session.execute(stmt)
        dp = result.scalar_one_or_none()
        if dp is None:
            return 0.0
        bucket_map = {
            "critical": 1.0, "high": 0.8, "medium": 0.5,
            "low": 0.3, "informational": 0.1,
        }
        bucket = _attr(dp, "decision_priority", "informational")
        return bucket_map.get(bucket, 0.1)
    except Exception as exc:
        logger.debug("[attention] compute_attention_priority failed: %r", exc)
        return 0.0


async def compute_personal_relevance(
    session,
    *,
    entity_key: str,
    run_override: Optional[bool] = None,
) -> float:
    """Personal relevance from learned preferences (Phase 15).

    Returns affinity * confidence for the strongest matching active preference.
    Range [0, 1].  Returns 0.0 when no matching preference exists.
    """
    if not _enabled(run_override):
        return 0.0
    if session is None:
        return 0.0
    try:
        from app.db.models import LearnedPreference
        from sqlalchemy import select

        stmt = (
            select(LearnedPreference)
            .where(
                LearnedPreference.entity_key == entity_key,
                LearnedPreference.status == "active",
            )
            .order_by(LearnedPreference.confidence.desc())
            .limit(1)
        )
        result = await session.execute(stmt)
        pref = result.scalar_one_or_none()
        if pref is None:
            return 0.0
        affinity = float(_attr(pref, "affinity", 0.0))
        confidence = float(_attr(pref, "confidence", 0.0))
        return _clamp(abs(affinity) * confidence)
    except Exception as exc:
        logger.debug("[attention] compute_personal_relevance failed: %r", exc)
        return 0.0


async def compute_memory_relevance(
    session,
    *,
    user_id: str,
    entity_key: str,
    run_override: Optional[bool] = None,
) -> float:
    """Memory relevance from cursor view history.

    Higher when the user has viewed this entity more times.
    Score = min(1.0, view_count / 10).  Returns 0.0 when no cursor exists.
    """
    if not _enabled(run_override):
        return 0.0
    if session is None:
        return 0.0
    try:
        from app.db.repositories.personal_experience_repo import get_experience_cursor
        cursor = await get_experience_cursor(
            session, user_id=user_id,
            entity_type="ticker", entity_key=entity_key,
        )
        if cursor is None:
            return 0.0
        vc = int(_attr(cursor, "view_count", 0))
        return _clamp(vc / 10.0)
    except Exception as exc:
        logger.debug("[attention] compute_memory_relevance failed: %r", exc)
        return 0.0


async def compute_portfolio_relevance(
    session,
    *,
    user_id: str,
    entity_key: str,
    run_override: Optional[bool] = None,
) -> float:
    """Portfolio relevance from portfolio positions (Phase 10D).

    Returns position weight if available, otherwise 0.3 for owned positions,
    0.1 for watchlist positions.  Range [0, 1].
    """
    if not _enabled(run_override):
        return 0.0
    if session is None:
        return 0.0
    try:
        from app.db.models import Portfolio, PortfolioPosition
        from sqlalchemy import select

        port_stmt = select(Portfolio.id).where(
            (Portfolio.user_id == user_id) | (Portfolio.user_id == None)  # noqa: E711
        )
        port_result = await session.execute(port_stmt)
        port_ids = [row[0] for row in port_result.fetchall()]
        if not port_ids:
            return 0.0

        pos_stmt = (
            select(PortfolioPosition)
            .where(
                PortfolioPosition.portfolio_id.in_(port_ids),
                PortfolioPosition.ticker == entity_key,
                PortfolioPosition.active == True,  # noqa: E712
            )
            .limit(1)
        )
        pos_result = await session.execute(pos_stmt)
        pos = pos_result.scalar_one_or_none()
        if pos is None:
            return 0.0
        weight = _attr(pos, "weight", None)
        if weight is not None:
            return _clamp(float(weight))
        membership = _attr(pos, "membership_class", "watchlist")
        if membership == "owned":
            return 0.3
        return 0.1
    except Exception as exc:
        logger.debug("[attention] compute_portfolio_relevance failed: %r", exc)
        return 0.0


async def compute_revisit_score(
    session,
    *,
    user_id: str,
    entity_key: str,
    change_magnitude: float = 0.0,
    run_override: Optional[bool] = None,
) -> float:
    """Revisit score: prior engagement strength × change magnitude.

    Higher when a previously-researched entity has changed significantly.
    engagement_strength = min(1.0, view_count / 5).
    revisit = engagement_strength * change_magnitude.
    """
    if not _enabled(run_override):
        return 0.0
    if session is None:
        return 0.0
    try:
        from app.db.repositories.personal_experience_repo import get_experience_cursor
        cursor = await get_experience_cursor(
            session, user_id=user_id,
            entity_type="ticker", entity_key=entity_key,
        )
        if cursor is None:
            return 0.0
        vc = int(_attr(cursor, "view_count", 0))
        engagement = min(1.0, vc / 5.0)
        return _clamp(engagement * change_magnitude)
    except Exception as exc:
        logger.debug("[attention] compute_revisit_score failed: %r", exc)
        return 0.0


# ---------------------------------------------------------------------------
# Composite scoring
# ---------------------------------------------------------------------------

def compute_composite_score(
    dimension_scores: Dict[str, float],
    weights: Optional[Dict[str, float]] = None,
) -> float:
    """Weighted sum of 7 dimensions.  Returns float in [0, 1].

    Uses DEFAULT_WEIGHTS when weights is None.  Validates bounds.
    """
    w = weights or DEFAULT_WEIGHTS
    ok, reason = validate_weights(w)
    if not ok:
        w = DEFAULT_WEIGHTS
    total = sum(
        w.get(dim, 0.0) * dimension_scores.get(dim, 0.0)
        for dim in DEFAULT_WEIGHTS
    )
    return round(_clamp(total), 4)


async def score_change_candidate(
    session,
    *,
    user_id: str,
    candidate: Dict[str, Any],
    weights: Optional[Dict[str, float]] = None,
    run_override: Optional[bool] = None,
) -> Dict[str, Any]:
    """Score one change candidate on all 7 dimensions + composite.

    Returns a new dict with the original candidate fields plus all scores.
    """
    if not _enabled(run_override):
        return {**candidate, **{dim: 0.0 for dim in DEFAULT_WEIGHTS},
                "composite_score": 0.0}
    if session is None:
        return {**candidate, **{dim: 0.0 for dim in DEFAULT_WEIGHTS},
                "composite_score": 0.0}

    ek = candidate.get("entity_key", "")
    et = candidate.get("entity_type", "company")

    attn = await compute_attention_priority(
        session, entity_key=ek, entity_type=et, run_override=run_override)
    relevance = await compute_personal_relevance(
        session, entity_key=ek, run_override=run_override)
    recency = float(candidate.get("recency_score", 0.0))
    novelty = float(candidate.get("novelty_score", 0.0))

    change_mag = max(recency, novelty)
    revisit = await compute_revisit_score(
        session, user_id=user_id, entity_key=ek,
        change_magnitude=change_mag, run_override=run_override)
    memory = await compute_memory_relevance(
        session, user_id=user_id, entity_key=ek, run_override=run_override)
    portfolio = await compute_portfolio_relevance(
        session, user_id=user_id, entity_key=ek, run_override=run_override)

    scores = {
        "attention_priority":  round(attn, 4),
        "personal_relevance":  round(relevance, 4),
        "recency_score":       round(recency, 4),
        "novelty_score":       round(novelty, 4),
        "revisit_score":       round(revisit, 4),
        "memory_relevance":    round(memory, 4),
        "portfolio_relevance": round(portfolio, 4),
    }
    composite = compute_composite_score(scores, weights)

    return {**candidate, **scores, "composite_score": composite}


# ---------------------------------------------------------------------------
# Structural rules (attention floor + novelty reserve)
# ---------------------------------------------------------------------------

def apply_attention_floor(
    scored_items: List[Dict[str, Any]],
    floor_cutoff: float = _ATTENTION_FLOOR_CUTOFF,
    floor_rank: int = _ATTENTION_FLOOR_RANK,
) -> List[Dict[str, Any]]:
    """Ensure items with attention_priority > floor_cutoff are in top floor_rank.

    Mutates rank positions only — never changes scores or truth.
    Returns a new list.
    """
    if not scored_items:
        return []
    items = list(scored_items)
    urgent = [i for i in items if i.get("attention_priority", 0.0) > floor_cutoff]
    non_urgent = [i for i in items if i.get("attention_priority", 0.0) <= floor_cutoff]

    urgent.sort(key=lambda x: x.get("composite_score", 0.0), reverse=True)
    non_urgent.sort(key=lambda x: x.get("composite_score", 0.0), reverse=True)

    result = urgent[:floor_rank]
    remaining = non_urgent + urgent[floor_rank:]
    remaining.sort(key=lambda x: x.get("composite_score", 0.0), reverse=True)
    result.extend(remaining)
    return result


def apply_novelty_reserve(
    scored_items: List[Dict[str, Any]],
    reserve_fraction: float = _NOVELTY_RESERVE_FRACTION,
    min_items: int = _MIN_ITEMS_FOR_RESERVE,
) -> List[Dict[str, Any]]:
    """Ensure reserve_fraction of top slots go to items with no matching preference.

    An item has "no matching preference" when personal_relevance == 0.0.
    Only applies when len(scored_items) >= min_items.
    Returns a new list with novelty_reserve_applied flag set.
    """
    if not scored_items or len(scored_items) < min_items:
        return [dict(item, novelty_reserve_applied=False) for item in scored_items]

    top_n = max(1, len(scored_items))
    reserve_count = max(1, int(top_n * reserve_fraction))

    preference_items = [i for i in scored_items if i.get("personal_relevance", 0.0) > 0.0]
    novel_items = [i for i in scored_items if i.get("personal_relevance", 0.0) == 0.0]

    novel_items.sort(key=lambda x: x.get("composite_score", 0.0), reverse=True)
    preference_items.sort(key=lambda x: x.get("composite_score", 0.0), reverse=True)

    reserved = novel_items[:reserve_count]
    remaining_novel = novel_items[reserve_count:]

    all_remaining = preference_items + remaining_novel
    all_remaining.sort(key=lambda x: x.get("composite_score", 0.0), reverse=True)

    result = []
    for item in reserved:
        result.append(dict(item, novelty_reserve_applied=True))
    for item in all_remaining:
        result.append(dict(item, novelty_reserve_applied=False))
    return result


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

async def rank_change_candidates(
    session,
    *,
    user_id: str,
    candidates: List[Dict[str, Any]],
    weights: Optional[Dict[str, float]] = None,
    run_override: Optional[bool] = None,
) -> List[Dict[str, Any]]:
    """Score and rank a list of change candidates.

    Pipeline:
      1. Score each candidate on all 7 dimensions + composite
      2. Sort by composite_score desc
      3. Apply attention floor
      4. Apply novelty reserve
      5. Assign final ranks (1-based)

    Returns [] when the flag is off or session is None.
    """
    if not _enabled(run_override):
        return []
    if session is None:
        return []

    try:
        scored = []
        for c in candidates:
            s = await score_change_candidate(
                session, user_id=user_id, candidate=c,
                weights=weights, run_override=run_override)
            scored.append(s)

        scored.sort(key=lambda x: x.get("composite_score", 0.0), reverse=True)

        floored = apply_attention_floor(scored)

        reserved = apply_novelty_reserve(floored)

        for idx, item in enumerate(reserved):
            item["rank"] = idx + 1

        return reserved
    except Exception as exc:
        logger.debug("[attention] rank_change_candidates failed: %r", exc)
        return []
