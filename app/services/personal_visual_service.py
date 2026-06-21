"""
Personal Experience Visual Service — Phase 19 · Slice 8.

Generates personal-experience visual *specifications* (not rendered output).
Each function reads Phase 18 tables read-only, then delegates to the Slice
19.3 spec builder, which enforces the explainability gate, the label
no-advice scan, and the rendering-tier assignment.

This module produces specs only.  No SVG.  No images.  No rendering.

Personal visuals
----------------
  build_attention_timeline_spec  — what deserved attention over time (json)
  build_change_timeline_spec     — what changed across visits (json)
  build_resume_timeline_spec     — what work should be resumed (json)
  build_thesis_evolution_spec    — how the thesis evolved for an entity (svg)

Upstream reads are direct ORM selects (PersonalExperienceEvent,
PersonalExperienceCursor).  This module never imports
personal_experience_repo / forecast_repo / scenario_repo / similarity_repo /
user_learning_repo / any write path — it reads the Phase 18 derived tables,
it never mutates them.

Flag gate
---------
  attention_timeline, change_timeline, resume_timeline → json → visual_json_enabled
  thesis_evolution → svg → visual_svg_enabled
Functions return None when the tier is disabled or session is None.

A spec whose upstream evidence is missing is returned blocked
(explanation_valid=False, blocked_reason set) — never raised.

SP-19 invariants
----------------
  SP-19a: no advisory language (enforced by the spec builder label scan).
  SP-19b: visualization does not change truth — reads only.
  SP-19c: writes nothing.
  SP-19d: no upstream feedback.
"""

from __future__ import annotations

import logging
from datetime import timezone
from typing import Any, Dict, List, Optional

from app.services.visual_spec_builder_service import build_personal_visual_spec

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _tier_enabled(tier: str, override: Optional[bool] = None) -> bool:
    if override is not None:
        return bool(override)
    try:
        from app.config import settings
        if tier == "json":
            return bool(getattr(settings, "visual_json_enabled", False))
        if tier == "svg":
            return bool(getattr(settings, "visual_svg_enabled", False))
        return False
    except Exception:
        return False


def _attr(obj: Any, name: str, default: Any = None) -> Any:
    val = getattr(obj, name, None)
    return val if val is not None else default


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


async def _events(
    session, user_id: str, *, entity_key: Optional[str] = None, limit: int = 200,
) -> List[Any]:
    from app.db.models import PersonalExperienceEvent
    from sqlalchemy import select
    stmt = select(PersonalExperienceEvent).where(
        PersonalExperienceEvent.user_id == user_id,
    )
    if entity_key is not None:
        stmt = stmt.where(PersonalExperienceEvent.entity_key == entity_key)
    stmt = stmt.order_by(PersonalExperienceEvent.surfaced_at.desc()).limit(limit)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def _cursors(session, user_id: str, limit: int = 200) -> List[Any]:
    from app.db.models import PersonalExperienceCursor
    from sqlalchemy import select
    stmt = (
        select(PersonalExperienceCursor)
        .where(PersonalExperienceCursor.user_id == user_id)
        .order_by(PersonalExperienceCursor.last_seen_at.desc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


# ===========================================================================
# § PERSONAL VISUALS
# ===========================================================================

async def build_attention_timeline_spec(
    session,
    *,
    user_id: str,
    run_override: Optional[bool] = None,
) -> Optional[Dict[str, Any]]:
    """What deserved attention over time, per user (json)."""
    if not _tier_enabled("json", run_override):
        return None
    if session is None:
        return None
    try:
        events = await _events(session, user_id)
        timeline = sorted(
            [
                {
                    "at":                 _iso(_attr(e, "surfaced_at", None)),
                    "entity_key":         _attr(e, "entity_key", ""),
                    "attention_priority": float(_attr(e, "attention_priority", 0.0)),
                }
                for e in events
            ],
            key=lambda x: x["at"] or "",
        )
        evidence = [f"experience_event:{_attr(e, 'id', '')}" for e in events]
        data = {"user_id": user_id, "timeline": timeline}
        return build_personal_visual_spec(
            visual_type="attention_timeline", entity_key="",
            data=data, evidence_refs=evidence,
        )
    except Exception as exc:
        logger.debug("[personal_visual] build_attention_timeline_spec failed: %r", exc)
        return None


async def build_change_timeline_spec(
    session,
    *,
    user_id: str,
    run_override: Optional[bool] = None,
) -> Optional[Dict[str, Any]]:
    """What changed across visits, per user (json)."""
    if not _tier_enabled("json", run_override):
        return None
    if session is None:
        return None
    try:
        cursors = await _cursors(session, user_id)
        timeline = sorted(
            [
                {
                    "entity_key":   _attr(c, "entity_key", ""),
                    "last_seen_at": _iso(_attr(c, "last_seen_at", None)),
                    "view_count":   int(_attr(c, "view_count", 0)),
                    "state_hash":   _attr(c, "last_state_hash", ""),
                }
                for c in cursors
            ],
            key=lambda x: x["last_seen_at"] or "",
        )
        evidence = [f"experience_cursor:{_attr(c, 'id', '')}" for c in cursors]
        data = {"user_id": user_id, "timeline": timeline}
        return build_personal_visual_spec(
            visual_type="change_timeline", entity_key="",
            data=data, evidence_refs=evidence,
        )
    except Exception as exc:
        logger.debug("[personal_visual] build_change_timeline_spec failed: %r", exc)
        return None


async def build_resume_timeline_spec(
    session,
    *,
    user_id: str,
    run_override: Optional[bool] = None,
) -> Optional[Dict[str, Any]]:
    """What research work should be resumed, ranked by engagement (json)."""
    if not _tier_enabled("json", run_override):
        return None
    if session is None:
        return None
    try:
        cursors = await _cursors(session, user_id)
        ranked = sorted(
            cursors, key=lambda c: int(_attr(c, "view_count", 0)), reverse=True,
        )
        items = [
            {
                "entity_key":   _attr(c, "entity_key", ""),
                "view_count":   int(_attr(c, "view_count", 0)),
                "last_seen_at": _iso(_attr(c, "last_seen_at", None)),
            }
            for c in ranked
        ]
        evidence = [f"experience_cursor:{_attr(c, 'id', '')}" for c in cursors]
        data = {"user_id": user_id, "resume_items": items}
        return build_personal_visual_spec(
            visual_type="resume_timeline", entity_key="",
            data=data, evidence_refs=evidence,
        )
    except Exception as exc:
        logger.debug("[personal_visual] build_resume_timeline_spec failed: %r", exc)
        return None


async def build_thesis_evolution_spec(
    session,
    *,
    user_id: str,
    entity_key: str,
    run_override: Optional[bool] = None,
) -> Optional[Dict[str, Any]]:
    """How the thesis for an entity evolved over the user's visits (svg)."""
    if not _tier_enabled("svg", run_override):
        return None
    if session is None:
        return None
    try:
        events = await _events(session, user_id, entity_key=entity_key)
        series = sorted(
            [
                {
                    "at":                 _iso(_attr(e, "surfaced_at", None)),
                    "attention_priority": float(_attr(e, "attention_priority", 0.0)),
                    "personal_relevance": float(_attr(e, "personal_relevance", 0.0)),
                    "memory_relevance":   float(_attr(e, "memory_relevance", 0.0)),
                }
                for e in events
            ],
            key=lambda x: x["at"] or "",
        )
        evidence = [f"experience_event:{_attr(e, 'id', '')}" for e in events]
        data = {"user_id": user_id, "entity_key": entity_key, "series": series}
        return build_personal_visual_spec(
            visual_type="thesis_evolution", entity_key=entity_key,
            data=data, evidence_refs=evidence,
            template_params={"entity_key": entity_key},
        )
    except Exception as exc:
        logger.debug("[personal_visual] build_thesis_evolution_spec failed: %r", exc)
        return None
