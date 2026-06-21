"""
Visual Calibration Service — Phase 19 · Slice 11.

Measures visual system quality by computing metrics over the shadow journal
(visual_experience_event) and AI audit log (ai_visual_generation_log).

Metrics
-------
  explainability_coverage   — fraction of shadow events with valid explanations
  cache_hit_rate            — fraction of events that were cache hits
  ai_validation_pass_rate   — fraction of AI generations that passed validation
  generation_latency        — 95th-percentile generation time in ms
  blocked_visual_rate       — fraction of events that were blocked

All metric functions are observational — they compute metrics from evidence
already in the Phase 19 event/log tables.  Nothing in this module modifies
upstream tables, forecasts, or any truth table.

Insufficient-sample handling
----------------------------
All metric functions return a dict with a "sufficient_samples" key.
When the evidence count falls below the minimum required, the metric
value is None and sufficient_samples=False.

Flag gate
---------
All async functions are gated on visual_calibration_enabled (default False).

Null-session contract
---------------------
All async functions return None / {} when session=None.

SP-19 invariants
----------------
  SP-19a: no advisory language.
  SP-19b: ordering does not change truth.
  SP-19c: writes only visual_experience_event (append-only, run_reason="calibration").
  SP-19d: no upstream feedback.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_MIN_COVERAGE_SAMPLES:   int = 10
_MIN_CACHE_SAMPLES:      int = 20
_MIN_AI_SAMPLES:         int = 5
_MIN_LATENCY_SAMPLES:    int = 20
_MIN_BLOCKED_SAMPLES:    int = 10
_CALIBRATION_RUN_REASON: str = "calibration"
_CALIBRATION_SCHEMA:     int = 1


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _enabled(override: Optional[bool] = None) -> bool:
    if override is not None:
        return bool(override)
    try:
        from app.config import settings
        return bool(getattr(settings, "visual_calibration_enabled", False))
    except Exception:
        return False


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _attr(obj: Any, name: str, default: Any = None) -> Any:
    val = getattr(obj, name, None)
    return val if val is not None else default


# ---------------------------------------------------------------------------
# Empty metric templates
# ---------------------------------------------------------------------------

def _empty_coverage() -> Dict[str, Any]:
    return {"coverage": None, "valid_count": 0, "blocked_count": 0,
            "total_count": 0, "sufficient_samples": False, "min_samples": _MIN_COVERAGE_SAMPLES}

def _empty_cache() -> Dict[str, Any]:
    return {"hit_rate": None, "cache_hits": 0, "total_count": 0,
            "sufficient_samples": False, "min_samples": _MIN_CACHE_SAMPLES}

def _empty_ai() -> Dict[str, Any]:
    return {"pass_rate": None, "passed": 0, "total_count": 0,
            "sufficient_samples": False, "min_samples": _MIN_AI_SAMPLES}

def _empty_latency() -> Dict[str, Any]:
    return {"p95_ms": None, "sample_count": 0,
            "sufficient_samples": False, "min_samples": _MIN_LATENCY_SAMPLES}

def _empty_blocked() -> Dict[str, Any]:
    return {"blocked_rate": None, "blocked_count": 0, "total_count": 0,
            "sufficient_samples": False, "min_samples": _MIN_BLOCKED_SAMPLES}

def _empty_summary() -> Dict[str, Any]:
    return {
        "explainability_coverage": _empty_coverage(),
        "cache_hit_rate":          _empty_cache(),
        "ai_validation_pass_rate": _empty_ai(),
        "generation_latency":      _empty_latency(),
        "blocked_visual_rate":     _empty_blocked(),
        "calibration_schema":      _CALIBRATION_SCHEMA,
        "generated_at":            _now().isoformat(),
    }


# ---------------------------------------------------------------------------
# record_visual_outcome — append-only write
# ---------------------------------------------------------------------------

async def record_visual_outcome(
    session,
    *,
    user_id: str,
    visual_type: str = "",
    entity_key: str = "",
    rendering_tier: str = "json",
    explanation_valid: bool = False,
    generation_ms: int = 0,
    cache_hit: bool = False,
    blocked_reason: str = "",
    run_override: Optional[bool] = None,
) -> Optional[Any]:
    """Append one calibration outcome to visual_experience_event.

    All rows are written with run_reason="calibration".
    Returns the ORM row, or None when the flag is off or session is None.
    """
    if not _enabled(run_override):
        return None
    if session is None:
        return None
    try:
        from app.db.repositories.visual_intelligence_repo import add_visual_event
        return await add_visual_event(
            session,
            user_id=user_id,
            visual_type=visual_type,
            entity_key=entity_key,
            rendering_tier=rendering_tier,
            explanation_valid=explanation_valid,
            generation_ms=generation_ms,
            cache_hit=cache_hit,
            blocked_reason=blocked_reason,
            run_reason=_CALIBRATION_RUN_REASON,
        )
    except Exception as exc:
        logger.debug("[visual_calibration] record_visual_outcome failed: %r", exc)
        return None


# ---------------------------------------------------------------------------
# calculate_explainability_coverage
# ---------------------------------------------------------------------------

async def calculate_explainability_coverage(
    session,
    *,
    user_id: Optional[str] = None,
    run_override: Optional[bool] = None,
) -> Dict[str, Any]:
    """Fraction of shadow events with valid explanations."""
    if not _enabled(run_override):
        return _empty_coverage()
    if session is None:
        return _empty_coverage()
    try:
        from app.db.repositories.visual_intelligence_repo import list_visual_events
        rows = await list_visual_events(
            session, user_id=user_id, run_reason="shadow", limit=5000,
        )
        total = len(rows)
        if total < _MIN_COVERAGE_SAMPLES:
            return _empty_coverage()
        valid = sum(1 for r in rows if bool(_attr(r, "explanation_valid", False)))
        blocked = total - valid
        return {
            "coverage":           round(valid / total, 4),
            "valid_count":        valid,
            "blocked_count":      blocked,
            "total_count":        total,
            "sufficient_samples": True,
            "min_samples":        _MIN_COVERAGE_SAMPLES,
        }
    except Exception as exc:
        logger.debug("[visual_calibration] calculate_explainability_coverage failed: %r", exc)
        return _empty_coverage()


# ---------------------------------------------------------------------------
# calculate_cache_hit_rate
# ---------------------------------------------------------------------------

async def calculate_cache_hit_rate(
    session,
    *,
    user_id: Optional[str] = None,
    run_override: Optional[bool] = None,
) -> Dict[str, Any]:
    """Fraction of shadow events that were cache hits."""
    if not _enabled(run_override):
        return _empty_cache()
    if session is None:
        return _empty_cache()
    try:
        from app.db.repositories.visual_intelligence_repo import list_visual_events
        rows = await list_visual_events(
            session, user_id=user_id, run_reason="shadow", limit=5000,
        )
        total = len(rows)
        if total < _MIN_CACHE_SAMPLES:
            return _empty_cache()
        hits = sum(1 for r in rows if bool(_attr(r, "cache_hit", False)))
        return {
            "hit_rate":           round(hits / total, 4),
            "cache_hits":         hits,
            "total_count":        total,
            "sufficient_samples": True,
            "min_samples":        _MIN_CACHE_SAMPLES,
        }
    except Exception as exc:
        logger.debug("[visual_calibration] calculate_cache_hit_rate failed: %r", exc)
        return _empty_cache()


# ---------------------------------------------------------------------------
# calculate_ai_validation_pass_rate
# ---------------------------------------------------------------------------

async def calculate_ai_validation_pass_rate(
    session,
    *,
    user_id: Optional[str] = None,
    run_override: Optional[bool] = None,
) -> Dict[str, Any]:
    """Fraction of AI generations that passed validation."""
    if not _enabled(run_override):
        return _empty_ai()
    if session is None:
        return _empty_ai()
    try:
        from app.db.repositories.visual_intelligence_repo import list_ai_visual_logs
        rows = await list_ai_visual_logs(
            session, user_id=user_id, limit=5000,
        )
        total = len(rows)
        if total < _MIN_AI_SAMPLES:
            return _empty_ai()
        passed = sum(1 for r in rows if bool(_attr(r, "validation_passed", False)))
        return {
            "pass_rate":          round(passed / total, 4),
            "passed":             passed,
            "total_count":        total,
            "sufficient_samples": True,
            "min_samples":        _MIN_AI_SAMPLES,
        }
    except Exception as exc:
        logger.debug("[visual_calibration] calculate_ai_validation_pass_rate failed: %r", exc)
        return _empty_ai()


# ---------------------------------------------------------------------------
# calculate_generation_latency
# ---------------------------------------------------------------------------

async def calculate_generation_latency(
    session,
    *,
    user_id: Optional[str] = None,
    run_override: Optional[bool] = None,
) -> Dict[str, Any]:
    """95th-percentile generation time in ms from shadow events."""
    if not _enabled(run_override):
        return _empty_latency()
    if session is None:
        return _empty_latency()
    try:
        from app.db.repositories.visual_intelligence_repo import list_visual_events
        rows = await list_visual_events(
            session, user_id=user_id, run_reason="shadow", limit=5000,
        )
        latencies = sorted(
            int(_attr(r, "generation_ms", 0) or 0) for r in rows
        )
        total = len(latencies)
        if total < _MIN_LATENCY_SAMPLES:
            return _empty_latency()
        idx = int(total * 0.95)
        idx = min(idx, total - 1)
        p95 = latencies[idx]
        return {
            "p95_ms":             p95,
            "sample_count":       total,
            "sufficient_samples": True,
            "min_samples":        _MIN_LATENCY_SAMPLES,
        }
    except Exception as exc:
        logger.debug("[visual_calibration] calculate_generation_latency failed: %r", exc)
        return _empty_latency()


# ---------------------------------------------------------------------------
# calculate_blocked_visual_rate
# ---------------------------------------------------------------------------

async def calculate_blocked_visual_rate(
    session,
    *,
    user_id: Optional[str] = None,
    run_override: Optional[bool] = None,
) -> Dict[str, Any]:
    """Fraction of shadow events that were blocked."""
    if not _enabled(run_override):
        return _empty_blocked()
    if session is None:
        return _empty_blocked()
    try:
        from app.db.repositories.visual_intelligence_repo import list_visual_events
        rows = await list_visual_events(
            session, user_id=user_id, run_reason="shadow", limit=5000,
        )
        total = len(rows)
        if total < _MIN_BLOCKED_SAMPLES:
            return _empty_blocked()
        blocked = sum(
            1 for r in rows
            if str(_attr(r, "blocked_reason", "") or "").strip()
        )
        return {
            "blocked_rate":       round(blocked / total, 4),
            "blocked_count":      blocked,
            "total_count":        total,
            "sufficient_samples": True,
            "min_samples":        _MIN_BLOCKED_SAMPLES,
        }
    except Exception as exc:
        logger.debug("[visual_calibration] calculate_blocked_visual_rate failed: %r", exc)
        return _empty_blocked()


# ---------------------------------------------------------------------------
# summarize_visual_calibration
# ---------------------------------------------------------------------------

async def summarize_visual_calibration(
    session,
    *,
    user_id: Optional[str] = None,
    run_override: Optional[bool] = None,
) -> Dict[str, Any]:
    """Aggregate all calibration metrics."""
    if not _enabled(run_override):
        return _empty_summary()
    if session is None:
        return _empty_summary()
    try:
        coverage = await calculate_explainability_coverage(
            session, user_id=user_id, run_override=run_override)
        cache = await calculate_cache_hit_rate(
            session, user_id=user_id, run_override=run_override)
        ai = await calculate_ai_validation_pass_rate(
            session, user_id=user_id, run_override=run_override)
        latency = await calculate_generation_latency(
            session, user_id=user_id, run_override=run_override)
        blocked = await calculate_blocked_visual_rate(
            session, user_id=user_id, run_override=run_override)
        return {
            "explainability_coverage": coverage,
            "cache_hit_rate":          cache,
            "ai_validation_pass_rate": ai,
            "generation_latency":      latency,
            "blocked_visual_rate":     blocked,
            "calibration_schema":      _CALIBRATION_SCHEMA,
            "generated_at":            _now().isoformat(),
        }
    except Exception as exc:
        logger.debug("[visual_calibration] summarize_visual_calibration failed: %r", exc)
        return _empty_summary()
