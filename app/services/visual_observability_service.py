"""
Visual Intelligence Observability Service — Phase 19 · Slice 12.

Provides a single production-ready observability snapshot covering:

  flags      — all 6 visual_* config flags with their current values
  metrics    — row counts for every Phase 19 table, shadow/calibration
               sub-counts, AI generation log counts
  safe_state — structured boolean sub-checks confirming the Phase 19
               shadow boundary is intact

This module is strictly read-only: it measures and reports.
It never writes to any table, never mutates config, and never triggers
a render, score, or delivery step.

safe_state sub-checks
---------------------
  shadow_only
    visual_shadow=True AND visual_json_enabled=False.

  no_live_visual_delivery
    visual_json_enabled=False AND visual_svg_enabled=False.

  no_truth_mutation
    Structural: SP-19c prohibits Phase 19 from writing to any upstream
    truth table.  Confirmed by flag combination.

  no_advisory_generation
    visual_ai_enabled=False AND visual_json_enabled=False.

  no_upstream_mutation
    visual_json_enabled=False AND visual_svg_enabled=False AND
    visual_ai_enabled=False.

  explainability_gate_active
    visual_shadow=True.

  overall
    True only when all six sub-checks pass.

SP-19 invariants
----------------
  SP-19a: no advisory language.
  SP-19b: visualization does not change truth.
  SP-19c: writes nothing.
  SP-19d: no upstream feedback.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

OBSERVABILITY_SCHEMA_VERSION: int = 1

_DISCLAIMER = (
    "Phase 19 Visual Intelligence is in shadow mode only. "
    "No visuals are delivered to end users. "
    "No investment guidance, conviction, or advice is produced. "
    "All output is observational."
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _count_rows(session, model_class, **filter_kwargs) -> int:
    if session is None:
        return 0
    try:
        from sqlalchemy import select, func
        stmt = select(func.count()).select_from(model_class)
        for col_name, value in filter_kwargs.items():
            col = getattr(model_class, col_name, None)
            if col is not None:
                stmt = stmt.where(col == value)
        result = await session.execute(stmt)
        return int(result.scalar() or 0)
    except Exception as exc:
        logger.debug("[visual_obs] _count_rows(%s): %r", model_class.__name__, exc)
        return 0


async def build_visual_snapshot(session) -> Dict[str, Any]:
    """Build a complete observability snapshot for Phase 19.

    DB-down-safe: degrades gracefully to zeros rather than raising.
    No secrets, no PII, no advisory language.
    """
    try:
        from app.config import settings
        flags = {
            "visual_json_enabled":        bool(getattr(settings, "visual_json_enabled", False)),
            "visual_svg_enabled":         bool(getattr(settings, "visual_svg_enabled", False)),
            "visual_ai_enabled":          bool(getattr(settings, "visual_ai_enabled", False)),
            "visual_cache_enabled":       bool(getattr(settings, "visual_cache_enabled", False)),
            "visual_shadow":              bool(getattr(settings, "visual_shadow", True)),
            "visual_calibration_enabled": bool(getattr(settings, "visual_calibration_enabled", False)),
        }
    except Exception:
        flags = {
            "visual_json_enabled": False, "visual_svg_enabled": False,
            "visual_ai_enabled": False, "visual_cache_enabled": False,
            "visual_shadow": True, "visual_calibration_enabled": False,
        }

    db_available = session is not None
    cache_count = 0
    event_count = 0
    ai_log_count = 0
    shadow_event_count = 0
    calibration_event_count = 0
    blocked_event_count = 0

    if db_available:
        try:
            from app.db.models import (
                VisualSpecCache, VisualExperienceEvent, AIVisualGenerationLog,
            )
            cache_count = await _count_rows(session, VisualSpecCache)
            event_count = await _count_rows(session, VisualExperienceEvent)
            ai_log_count = await _count_rows(session, AIVisualGenerationLog)
            shadow_event_count = await _count_rows(
                session, VisualExperienceEvent, run_reason="shadow")
            calibration_event_count = await _count_rows(
                session, VisualExperienceEvent, run_reason="calibration")
        except Exception as exc:
            logger.debug("[visual_obs] metric collection failed: %r", exc)
            db_available = False

    metrics = {
        "cache_count":              cache_count,
        "event_count":              event_count,
        "ai_log_count":             ai_log_count,
        "shadow_event_count":       shadow_event_count,
        "calibration_event_count":  calibration_event_count,
        "blocked_event_count":      blocked_event_count,
    }

    shadow_only = (
        flags["visual_shadow"] is True
        and flags["visual_json_enabled"] is False
    )
    no_live_visual_delivery = (
        flags["visual_json_enabled"] is False
        and flags["visual_svg_enabled"] is False
    )
    no_truth_mutation = (
        flags["visual_json_enabled"] is False
        and flags["visual_svg_enabled"] is False
        and flags["visual_ai_enabled"] is False
    )
    no_advisory_generation = (
        flags["visual_ai_enabled"] is False
        and flags["visual_json_enabled"] is False
    )
    no_upstream_mutation = (
        flags["visual_json_enabled"] is False
        and flags["visual_svg_enabled"] is False
        and flags["visual_ai_enabled"] is False
    )
    explainability_gate_active = flags["visual_shadow"] is True

    overall = all([
        shadow_only,
        no_live_visual_delivery,
        no_truth_mutation,
        no_advisory_generation,
        no_upstream_mutation,
        explainability_gate_active,
    ])

    safe_state = {
        "shadow_only":               shadow_only,
        "no_live_visual_delivery":   no_live_visual_delivery,
        "no_truth_mutation":         no_truth_mutation,
        "no_advisory_generation":    no_advisory_generation,
        "no_upstream_mutation":      no_upstream_mutation,
        "explainability_gate_active": explainability_gate_active,
        "overall":                   overall,
    }

    return {
        "flags":          flags,
        "metrics":        metrics,
        "safe_state":     safe_state,
        "db_available":   db_available,
        "schema_version": OBSERVABILITY_SCHEMA_VERSION,
        "generated_at":   _now().isoformat(),
        "disclaimer":     _DISCLAIMER,
    }
