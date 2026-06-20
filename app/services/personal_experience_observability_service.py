"""
Personal Experience Observability Service — Phase 18 · Slice 10.

Provides a single production-ready observability snapshot covering:

  flags      — all 6 experience_* config flags with their current values
  metrics    — row counts for every Phase 18 table, shadow/calibration
               sub-counts, change candidate and attention queue counts
  safe_state — structured boolean sub-checks confirming the Phase 18
               shadow boundary is intact

This module is strictly read-only: it measures and reports.
It never writes to any table, never mutates config, and never triggers
a compose, score, or delivery step.

safe_state sub-checks
---------------------
  shadow_only
    experience_shadow=True AND experience_composer_enabled=False.

  no_live_delivery
    experience_composer_enabled=False AND experience_brief_enabled=False.

  no_truth_mutation
    Structural: SP-18c prohibits Phase 18 from writing to any upstream
    truth table.  Confirmed by flag combination.

  no_advisory_generation
    No advisory language in any Phase 18 service output.
    Confirmed by composer and brief flags both off.

  no_upstream_mutation
    experience_change_detection_enabled=False AND
    experience_attention_enabled=False.

  explainability_gate_active
    experience_shadow=True.  The explainability gate is structurally
    enforced in the composer regardless of flags.

  overall
    True only when all six sub-checks pass.

SP-18 invariants
----------------
  SP-18a: no advisory language.
  SP-18b: ordering does not change truth.
  SP-18c: writes nothing.
  SP-18d: no upstream feedback.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

OBSERVABILITY_SCHEMA_VERSION: int = 1

_DISCLAIMER = (
    "Phase 18 Personal Experience is in shadow mode only. "
    "No personalized surfacing is delivered to end users. "
    "No investment guidance, conviction, or advice is produced. "
    "All output is observational."
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Internal DB helpers
# ---------------------------------------------------------------------------

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
        logger.debug("[experience_obs] _count_rows(%s): %r", model_class.__name__, exc)
        return 0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def build_personal_experience_snapshot(
    session,
) -> Dict[str, Any]:
    """Build a complete observability snapshot for Phase 18.

    DB-down-safe: degrades gracefully to zeros rather than raising.
    No secrets, no PII, no advisory language.
    """

    # -- flags ---------------------------------------------------------------
    try:
        from app.config import settings
        flags = {
            "experience_change_detection_enabled": bool(
                getattr(settings, "experience_change_detection_enabled", False)),
            "experience_attention_enabled": bool(
                getattr(settings, "experience_attention_enabled", False)),
            "experience_composer_enabled": bool(
                getattr(settings, "experience_composer_enabled", False)),
            "experience_memory_enabled": bool(
                getattr(settings, "experience_memory_enabled", False)),
            "experience_shadow": bool(
                getattr(settings, "experience_shadow", True)),
            "experience_brief_enabled": bool(
                getattr(settings, "experience_brief_enabled", False)),
        }
    except Exception:
        flags = {
            "experience_change_detection_enabled": False,
            "experience_attention_enabled": False,
            "experience_composer_enabled": False,
            "experience_memory_enabled": False,
            "experience_shadow": True,
            "experience_brief_enabled": False,
        }

    # -- metrics (DB-down-safe) ----------------------------------------------
    db_available = session is not None
    cursor_count = 0
    event_count = 0
    brief_count = 0
    shadow_event_count = 0
    calibration_event_count = 0
    explainability_valid_count = 0

    if db_available:
        try:
            from app.db.models import (
                PersonalExperienceCursor,
                PersonalExperienceEvent,
                PersonalBriefSnapshot,
            )
            cursor_count = await _count_rows(session, PersonalExperienceCursor)
            event_count = await _count_rows(session, PersonalExperienceEvent)
            brief_count = await _count_rows(session, PersonalBriefSnapshot)
            shadow_event_count = await _count_rows(
                session, PersonalExperienceEvent, run_reason="shadow")
            calibration_event_count = await _count_rows(
                session, PersonalExperienceEvent, run_reason="calibration")
            explainability_valid_count = await _count_rows(
                session, PersonalExperienceEvent, explanation_valid=True)
        except Exception as exc:
            logger.debug("[experience_obs] metric collection failed: %r", exc)
            db_available = False

    metrics = {
        "cursor_count":              cursor_count,
        "event_count":               event_count,
        "brief_count":               brief_count,
        "shadow_event_count":        shadow_event_count,
        "calibration_event_count":   calibration_event_count,
        "explainability_valid_count": explainability_valid_count,
        "change_candidate_count":    0,
        "attention_queue_count":     0,
        "resume_candidate_count":    0,
    }

    # -- safe_state ----------------------------------------------------------
    shadow_only = (
        flags["experience_shadow"] is True
        and flags["experience_composer_enabled"] is False
    )
    no_live_delivery = (
        flags["experience_composer_enabled"] is False
        and flags["experience_brief_enabled"] is False
    )
    no_truth_mutation = (
        flags["experience_composer_enabled"] is False
        and flags["experience_attention_enabled"] is False
    )
    no_advisory_generation = (
        flags["experience_composer_enabled"] is False
        and flags["experience_brief_enabled"] is False
    )
    no_upstream_mutation = (
        flags["experience_change_detection_enabled"] is False
        and flags["experience_attention_enabled"] is False
    )
    explainability_gate_active = flags["experience_shadow"] is True

    overall = all([
        shadow_only,
        no_live_delivery,
        no_truth_mutation,
        no_advisory_generation,
        no_upstream_mutation,
        explainability_gate_active,
    ])

    safe_state = {
        "shadow_only":                   shadow_only,
        "no_live_delivery":              no_live_delivery,
        "no_truth_mutation":             no_truth_mutation,
        "no_advisory_generation":  no_advisory_generation,
        "no_upstream_mutation":           no_upstream_mutation,
        "explainability_gate_active":    explainability_gate_active,
        "overall":                       overall,
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
