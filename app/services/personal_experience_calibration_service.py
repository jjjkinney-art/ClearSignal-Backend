"""
Personal Experience Calibration — Phase 18 · Slice 9.

Measures whether the Personal Experience layer surfaces the right things.

Core questions
--------------
  - Did surfaced items receive engagement?   (attention_accuracy)
  - Did attention ranking remain stable?     (ranking_stability)
  - Did resume suggestions prove useful?     (resume_accuracy)
  - Did explainability remain complete?      (explainability_coverage)
  - Did novelty reserve add value?           (novelty_effectiveness)

Storage
-------
record_experience_outcome appends one row to personal_experience_event
(run_reason="calibration").  No other writes.

All metric functions are observational — they compute metrics from
evidence already in the personal_experience_event rows.  Nothing in
this module modifies upstream tables, preferences, forecasts, or any
truth table.

Insufficient-sample handling
----------------------------
All metric functions return a dict with a "sufficient_samples" key.
When the evidence count falls below the minimum required, the metric
value is None and sufficient_samples=False.

Flag gate
---------
All async functions are gated on experience_shadow (default True).

Null-session contract
---------------------
All async functions return None / {} when session=None.

SP-18 invariants
----------------
  SP-18a: no advisory language.
  SP-18b: ordering does not change truth.
  SP-18c: writes only personal_experience_event (append-only, run_reason="calibration").
  SP-18d: no upstream feedback.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MIN_ACCURACY_SAMPLES:     int = 5
_MIN_RESUME_SAMPLES:       int = 3
_MIN_COVERAGE_SAMPLES:     int = 5
_MIN_STABILITY_SAMPLES:    int = 4
_MIN_NOVELTY_SAMPLES:      int = 3
_CALIBRATION_RUN_REASON:   str = "calibration"
_CALIBRATION_SCHEMA:       int = 1
_ENGAGED_SCORE:          float = 1.0
_IGNORED_SCORE:          float = -1.0


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _enabled(override: Optional[bool] = None) -> bool:
    if override is not None:
        return bool(override)
    try:
        from app.config import settings
        return bool(getattr(settings, "experience_shadow", True))
    except Exception:
        return True


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _attr(obj: Any, name: str, default: Any = None) -> Any:
    val = getattr(obj, name, None)
    return val if val is not None else default


# ---------------------------------------------------------------------------
# Empty metric templates
# ---------------------------------------------------------------------------

def _empty_attention_accuracy(user_id: str) -> Dict[str, Any]:
    return {
        "user_id":            user_id,
        "accuracy":           None,
        "engaged_count":      0,
        "not_engaged_count":  0,
        "total_count":        0,
        "sufficient_samples": False,
        "min_samples":        _MIN_ACCURACY_SAMPLES,
    }


def _empty_resume_accuracy(user_id: str) -> Dict[str, Any]:
    return {
        "user_id":            user_id,
        "accuracy":           None,
        "engaged_count":      0,
        "total_count":        0,
        "sufficient_samples": False,
        "min_samples":        _MIN_RESUME_SAMPLES,
    }


def _empty_coverage(user_id: str) -> Dict[str, Any]:
    return {
        "user_id":            user_id,
        "coverage":           None,
        "valid_count":        0,
        "blocked_count":      0,
        "total_count":        0,
        "sufficient_samples": False,
        "min_samples":        _MIN_COVERAGE_SAMPLES,
    }


def _empty_stability(user_id: str) -> Dict[str, Any]:
    return {
        "user_id":            user_id,
        "stability":          None,
        "items_tracked":      0,
        "sufficient_samples": False,
        "min_samples":        _MIN_STABILITY_SAMPLES,
    }


def _empty_novelty(user_id: str) -> Dict[str, Any]:
    return {
        "user_id":             user_id,
        "effectiveness":       None,
        "engaged_novel_count": 0,
        "total_novel_count":   0,
        "sufficient_samples":  False,
        "min_samples":         _MIN_NOVELTY_SAMPLES,
    }


def _empty_summary(user_id: str) -> Dict[str, Any]:
    return {
        "user_id":                 user_id,
        "attention_accuracy":      _empty_attention_accuracy(user_id),
        "resume_accuracy":         _empty_resume_accuracy(user_id),
        "explainability_coverage": _empty_coverage(user_id),
        "ranking_stability":       _empty_stability(user_id),
        "novelty_effectiveness":   _empty_novelty(user_id),
        "calibration_schema":      _CALIBRATION_SCHEMA,
        "generated_at":            _now().isoformat(),
    }


# ---------------------------------------------------------------------------
# record_experience_outcome — append-only write
# ---------------------------------------------------------------------------

async def record_experience_outcome(
    session,
    *,
    user_id: str,
    surface: str,
    item_ref: str,
    entity_type: str = "",
    entity_key: str = "",
    experience_score: float = 0.0,
    observed_engagement: bool = False,
    run_override: Optional[bool] = None,
) -> Optional[Any]:
    """Append one calibration outcome observation to personal_experience_event.

    observed_engagement=True → experience_score stored as-is.
    observed_engagement=False → experience_score stored as negative.

    All rows are written with run_reason="calibration".
    Returns the ORM row, or None when the flag is off or session is None.
    """
    if not _enabled(run_override):
        return None
    if session is None:
        return None
    try:
        from app.db.repositories.personal_experience_repo import add_experience_event

        score = abs(experience_score) if observed_engagement else -abs(experience_score)
        return await add_experience_event(
            session,
            user_id=user_id,
            surface=surface,
            item_ref=item_ref,
            entity_type=entity_type,
            entity_key=entity_key,
            experience_score=round(score, 4),
            explanation_text="calibration_engaged" if observed_engagement else "calibration_ignored",
            explanation_valid=observed_engagement,
            run_reason=_CALIBRATION_RUN_REASON,
        )
    except Exception as exc:
        logger.debug("[calibration] record_experience_outcome failed: %r", exc)
        return None


# ---------------------------------------------------------------------------
# calculate_attention_accuracy
# ---------------------------------------------------------------------------

async def calculate_attention_accuracy(
    session,
    *,
    user_id: str,
    run_override: Optional[bool] = None,
) -> Dict[str, Any]:
    """Fraction of calibration observations that were engaged.

    Reads personal_experience_event rows with run_reason="calibration".
    Engaged rows have explanation_valid=True; non-engaged have False.
    """
    if not _enabled(run_override):
        return _empty_attention_accuracy(user_id)
    if session is None:
        return _empty_attention_accuracy(user_id)
    try:
        from app.db.repositories.personal_experience_repo import list_experience_events

        rows = await list_experience_events(
            session, user_id=user_id, run_reason=_CALIBRATION_RUN_REASON, limit=5000,
        )

        engaged = sum(1 for r in rows if bool(_attr(r, "explanation_valid", False)))
        total = len(rows)
        not_engaged = total - engaged

        if total < _MIN_ACCURACY_SAMPLES:
            return _empty_attention_accuracy(user_id)

        return {
            "user_id":            user_id,
            "accuracy":           round(engaged / total, 4),
            "engaged_count":      engaged,
            "not_engaged_count":  not_engaged,
            "total_count":        total,
            "sufficient_samples": True,
            "min_samples":        _MIN_ACCURACY_SAMPLES,
        }
    except Exception as exc:
        logger.debug("[calibration] calculate_attention_accuracy failed: %r", exc)
        return _empty_attention_accuracy(user_id)


# ---------------------------------------------------------------------------
# calculate_resume_accuracy
# ---------------------------------------------------------------------------

async def calculate_resume_accuracy(
    session,
    *,
    user_id: str,
    run_override: Optional[bool] = None,
) -> Dict[str, Any]:
    """Fraction of resume-surface calibration outcomes that were engaged.

    Filters calibration events to surface="resume".
    """
    if not _enabled(run_override):
        return _empty_resume_accuracy(user_id)
    if session is None:
        return _empty_resume_accuracy(user_id)
    try:
        from app.db.repositories.personal_experience_repo import list_experience_events

        rows = await list_experience_events(
            session, user_id=user_id, surface="resume",
            run_reason=_CALIBRATION_RUN_REASON, limit=5000,
        )

        engaged = sum(1 for r in rows if bool(_attr(r, "explanation_valid", False)))
        total = len(rows)

        if total < _MIN_RESUME_SAMPLES:
            return _empty_resume_accuracy(user_id)

        return {
            "user_id":            user_id,
            "accuracy":           round(engaged / total, 4),
            "engaged_count":      engaged,
            "total_count":        total,
            "sufficient_samples": True,
            "min_samples":        _MIN_RESUME_SAMPLES,
        }
    except Exception as exc:
        logger.debug("[calibration] calculate_resume_accuracy failed: %r", exc)
        return _empty_resume_accuracy(user_id)


# ---------------------------------------------------------------------------
# calculate_explainability_coverage
# ---------------------------------------------------------------------------

async def calculate_explainability_coverage(
    session,
    *,
    user_id: str,
    run_override: Optional[bool] = None,
) -> Dict[str, Any]:
    """Fraction of shadow events with valid explanations.

    Reads personal_experience_event rows with run_reason="shadow".
    coverage = valid_count / total_count.
    """
    if not _enabled(run_override):
        return _empty_coverage(user_id)
    if session is None:
        return _empty_coverage(user_id)
    try:
        from app.db.repositories.personal_experience_repo import list_experience_events

        rows = await list_experience_events(
            session, user_id=user_id, run_reason="shadow", limit=5000,
        )

        valid = sum(1 for r in rows if bool(_attr(r, "explanation_valid", False)))
        total = len(rows)
        blocked = total - valid

        if total < _MIN_COVERAGE_SAMPLES:
            return _empty_coverage(user_id)

        return {
            "user_id":            user_id,
            "coverage":           round(valid / total, 4),
            "valid_count":        valid,
            "blocked_count":      blocked,
            "total_count":        total,
            "sufficient_samples": True,
            "min_samples":        _MIN_COVERAGE_SAMPLES,
        }
    except Exception as exc:
        logger.debug("[calibration] calculate_explainability_coverage failed: %r", exc)
        return _empty_coverage(user_id)


# ---------------------------------------------------------------------------
# calculate_ranking_stability
# ---------------------------------------------------------------------------

async def calculate_ranking_stability(
    session,
    *,
    user_id: str,
    run_override: Optional[bool] = None,
) -> Dict[str, Any]:
    """Measures rank variance across consecutive shadow events for the same items.

    stability = 1 - mean_score_variance.
    Groups shadow events by entity_key, computes score variance per entity,
    then averages.  Higher is more stable.
    """
    if not _enabled(run_override):
        return _empty_stability(user_id)
    if session is None:
        return _empty_stability(user_id)
    try:
        from app.db.repositories.personal_experience_repo import list_experience_events

        rows = await list_experience_events(
            session, user_id=user_id, run_reason="shadow", limit=5000,
        )

        by_entity: Dict[str, List[float]] = {}
        for r in rows:
            ek = str(_attr(r, "entity_key", ""))
            if not ek:
                continue
            score = float(_attr(r, "experience_score", 0.0) or 0.0)
            by_entity.setdefault(ek, []).append(score)

        entities_with_multiple = {
            ek: scores for ek, scores in by_entity.items() if len(scores) >= 2
        }

        if len(entities_with_multiple) < _MIN_STABILITY_SAMPLES:
            return _empty_stability(user_id)

        variances: List[float] = []
        for scores in entities_with_multiple.values():
            mean = sum(scores) / len(scores)
            var = sum((s - mean) ** 2 for s in scores) / len(scores)
            variances.append(var)

        mean_var = sum(variances) / len(variances)
        stability = round(max(0.0, min(1.0, 1.0 - mean_var)), 4)

        return {
            "user_id":            user_id,
            "stability":          stability,
            "items_tracked":      len(entities_with_multiple),
            "sufficient_samples": True,
            "min_samples":        _MIN_STABILITY_SAMPLES,
        }
    except Exception as exc:
        logger.debug("[calibration] calculate_ranking_stability failed: %r", exc)
        return _empty_stability(user_id)


# ---------------------------------------------------------------------------
# calculate_novelty_effectiveness
# ---------------------------------------------------------------------------

async def calculate_novelty_effectiveness(
    session,
    *,
    user_id: str,
    run_override: Optional[bool] = None,
) -> Dict[str, Any]:
    """Fraction of novel items (personal_relevance == 0.0) that were engaged.

    Novel items are those surfaced via the novelty reserve — they have
    personal_relevance == 0.0 in their shadow event.  Engagement is
    measured by whether a calibration event exists for the same item_ref
    with explanation_valid=True.
    """
    if not _enabled(run_override):
        return _empty_novelty(user_id)
    if session is None:
        return _empty_novelty(user_id)
    try:
        from app.db.repositories.personal_experience_repo import list_experience_events

        shadow_rows = await list_experience_events(
            session, user_id=user_id, run_reason="shadow", limit=5000,
        )

        novel_refs: set = set()
        for r in shadow_rows:
            raw = _attr(r, "personal_relevance", None)
            pr = float(raw) if raw is not None else 1.0
            if pr == 0.0:
                ref = str(_attr(r, "item_ref", ""))
                if ref:
                    novel_refs.add(ref)

        if len(novel_refs) < _MIN_NOVELTY_SAMPLES:
            return _empty_novelty(user_id)

        calib_rows = await list_experience_events(
            session, user_id=user_id, run_reason=_CALIBRATION_RUN_REASON, limit=5000,
        )

        engaged_refs: set = set()
        for r in calib_rows:
            if bool(_attr(r, "explanation_valid", False)):
                ref = str(_attr(r, "item_ref", ""))
                if ref:
                    engaged_refs.add(ref)

        engaged_novel = novel_refs & engaged_refs
        total_novel = len(novel_refs)
        engaged_count = len(engaged_novel)

        return {
            "user_id":             user_id,
            "effectiveness":       round(engaged_count / total_novel, 4),
            "engaged_novel_count": engaged_count,
            "total_novel_count":   total_novel,
            "sufficient_samples":  True,
            "min_samples":         _MIN_NOVELTY_SAMPLES,
        }
    except Exception as exc:
        logger.debug("[calibration] calculate_novelty_effectiveness failed: %r", exc)
        return _empty_novelty(user_id)


# ---------------------------------------------------------------------------
# summarize_experience_calibration
# ---------------------------------------------------------------------------

async def summarize_experience_calibration(
    session,
    *,
    user_id: str,
    run_override: Optional[bool] = None,
) -> Dict[str, Any]:
    """Aggregate all calibration metrics for one user.

    Returns a dict with all five metrics, calibration_schema, and
    generated_at.
    """
    if not _enabled(run_override):
        return _empty_summary(user_id)
    if session is None:
        return _empty_summary(user_id)
    try:
        attention = await calculate_attention_accuracy(
            session, user_id=user_id, run_override=run_override,
        )
        resume = await calculate_resume_accuracy(
            session, user_id=user_id, run_override=run_override,
        )
        coverage = await calculate_explainability_coverage(
            session, user_id=user_id, run_override=run_override,
        )
        stability = await calculate_ranking_stability(
            session, user_id=user_id, run_override=run_override,
        )
        novelty = await calculate_novelty_effectiveness(
            session, user_id=user_id, run_override=run_override,
        )

        return {
            "user_id":                 user_id,
            "attention_accuracy":      attention,
            "resume_accuracy":         resume,
            "explainability_coverage": coverage,
            "ranking_stability":       stability,
            "novelty_effectiveness":   novelty,
            "calibration_schema":      _CALIBRATION_SCHEMA,
            "generated_at":            _now().isoformat(),
        }
    except Exception as exc:
        logger.debug("[calibration] summarize_experience_calibration failed: %r", exc)
        return _empty_summary(user_id)
