"""
Scenario + Transmission Visual Service — Phase 19 · Slice 5.

Generates scenario visual *specifications* (not rendered output).  Each
function reads ScenarioSnapshot / ScenarioEvidence read-only, then delegates
to the Slice 19.3 spec builder, which enforces the explainability gate, the
label no-advice scan, and the rendering-tier assignment.

This module produces specs only.  No SVG.  No images.  No rendering.

Scenario visuals (all svg tier)
-------------------------------
  build_what_changed_map_spec    — before/after scenario state comparison
  build_transmission_path_spec   — trigger → intermediate → impact graph
  build_scenario_tree_spec       — active scenarios with plausibility branches
  build_impact_map_spec          — impact propagation across affected entities

Upstream reads are direct ORM selects (ScenarioSnapshot, ScenarioEvidence).
This module never imports scenario_repo / forecast_repo / decision_repo /
similarity_repo / any write path — it reads truth, it never mutates it.

SP-19e: transmission and impact edges represent data relationships
(cause→effect, affected-entity links) — never implied trading direction.

Flag gate
---------
All scenario visuals are svg tier → gated on visual_svg_enabled.
Functions return None when the tier is disabled or session is None.

A spec whose upstream evidence is missing is returned blocked
(explanation_valid=False, blocked_reason set) — never raised.

SP-19 invariants
----------------
  SP-19a: no advisory language (enforced by the spec builder label scan).
  SP-19b: visualization does not change truth — reads only.
  SP-19c: writes nothing.
  SP-19d: no upstream feedback.
  SP-19e: edges are data relationships, not action directives.
"""

from __future__ import annotations

import logging
from datetime import timezone
from typing import Any, Dict, List, Optional

from app.services.visual_spec_builder_service import build_scenario_visual_spec

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _svg_enabled(override: Optional[bool] = None) -> bool:
    if override is not None:
        return bool(override)
    try:
        from app.config import settings
        return bool(getattr(settings, "visual_svg_enabled", False))
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


def _as_list(val: Any) -> List[Any]:
    if val is None:
        return []
    if isinstance(val, list):
        return val
    return [val]


async def _scenarios(
    session, entity_key: str, *, scenario_id: Optional[str] = None, limit: int = 20,
) -> List[Any]:
    from app.db.models import ScenarioSnapshot
    from sqlalchemy import select
    stmt = select(ScenarioSnapshot)
    if scenario_id is not None:
        stmt = stmt.where(ScenarioSnapshot.id == scenario_id)
    else:
        stmt = stmt.where(ScenarioSnapshot.entity_key == entity_key)
    stmt = stmt.order_by(ScenarioSnapshot.built_at.desc()).limit(limit)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def _scenario_evidence_refs(session, scenario_id: str, limit: int = 20) -> List[str]:
    from app.db.models import ScenarioEvidence
    from sqlalchemy import select
    stmt = (
        select(ScenarioEvidence)
        .where(ScenarioEvidence.scenario_id == scenario_id)
        .limit(limit)
    )
    result = await session.execute(stmt)
    rows = list(result.scalars().all())
    return [f"scenario_evidence:{_attr(r, 'id', '')}" for r in rows]


# ===========================================================================
# § SCENARIO VISUALS
# ===========================================================================

async def build_what_changed_map_spec(
    session,
    *,
    entity_key: str,
    run_override: Optional[bool] = None,
) -> Optional[Dict[str, Any]]:
    """Before/after comparison of scenario state for an entity (svg)."""
    if not _svg_enabled(run_override):
        return None
    if session is None:
        return None
    try:
        snaps = await _scenarios(session, entity_key, limit=2)
        if not snaps:
            return build_scenario_visual_spec(
                visual_type="what_changed_map", entity_key=entity_key,
                data={"entity_key": entity_key}, evidence_refs=[],
            )
        current = snaps[0]
        prior = snaps[1] if len(snaps) > 1 else None

        def _state(s):
            return {
                "condition":    _attr(s, "condition", ""),
                "impact":       _attr(s, "scenario_impact", ""),
                "plausibility": _attr(s, "plausibility_band", ""),
                "at":           _iso(_attr(s, "built_at", None)),
            }

        data = {
            "entity_key":   entity_key,
            "after":        _state(current),
            "before":       _state(prior) if prior else None,
            "what_changed": _attr(current, "what_changed", ""),
        }
        evidence = [f"scenario_snapshot:{_attr(current, 'id', '')}"]
        if prior:
            evidence.append(f"scenario_snapshot:{_attr(prior, 'id', '')}")
        return build_scenario_visual_spec(
            visual_type="what_changed_map", entity_key=entity_key,
            data=data, evidence_refs=evidence,
        )
    except Exception as exc:
        logger.debug("[scenario_visual] build_what_changed_map_spec failed: %r", exc)
        return None


async def build_transmission_path_spec(
    session,
    *,
    entity_key: str,
    scenario_id: Optional[str] = None,
    run_override: Optional[bool] = None,
) -> Optional[Dict[str, Any]]:
    """Transmission path from trigger to impact for an entity (svg)."""
    if not _svg_enabled(run_override):
        return None
    if session is None:
        return None
    try:
        snaps = await _scenarios(session, entity_key, scenario_id=scenario_id, limit=1)
        if not snaps:
            return build_scenario_visual_spec(
                visual_type="transmission_path", entity_key=entity_key,
                data={"entity_key": entity_key}, evidence_refs=[],
            )
        snap = snaps[0]
        steps = _as_list(_attr(snap, "transmission_path", []))
        nodes = [{"id": i, "label": str(step)} for i, step in enumerate(steps)]
        edges = [{"from": i, "to": i + 1} for i in range(len(steps) - 1)]
        evidence = [f"scenario_snapshot:{_attr(snap, 'id', '')}"]
        evidence.extend(await _scenario_evidence_refs(session, _attr(snap, "id", "")))
        data = {"entity_key": entity_key, "nodes": nodes, "edges": edges}
        return build_scenario_visual_spec(
            visual_type="transmission_path", entity_key=entity_key,
            data=data, evidence_refs=evidence,
        )
    except Exception as exc:
        logger.debug("[scenario_visual] build_transmission_path_spec failed: %r", exc)
        return None


async def build_scenario_tree_spec(
    session,
    *,
    entity_key: str,
    run_override: Optional[bool] = None,
) -> Optional[Dict[str, Any]]:
    """Active scenarios for an entity with plausibility on each branch (svg)."""
    if not _svg_enabled(run_override):
        return None
    if session is None:
        return None
    try:
        snaps = await _scenarios(session, entity_key, limit=20)
        branches = [
            {
                "scenario_key": _attr(s, "scenario_key", ""),
                "scenario_type": _attr(s, "scenario_type", ""),
                "plausibility": _attr(s, "plausibility_band", ""),
                "impact":       _attr(s, "scenario_impact", ""),
            }
            for s in snaps
        ]
        evidence = [f"scenario_snapshot:{_attr(s, 'id', '')}" for s in snaps]
        data = {"entity_key": entity_key, "branches": branches}
        return build_scenario_visual_spec(
            visual_type="scenario_tree", entity_key=entity_key,
            data=data, evidence_refs=evidence,
        )
    except Exception as exc:
        logger.debug("[scenario_visual] build_scenario_tree_spec failed: %r", exc)
        return None


async def build_impact_map_spec(
    session,
    *,
    entity_key: str,
    scenario_id: Optional[str] = None,
    run_override: Optional[bool] = None,
) -> Optional[Dict[str, Any]]:
    """Impact propagation across entities related to a scenario (svg)."""
    if not _svg_enabled(run_override):
        return None
    if session is None:
        return None
    try:
        snaps = await _scenarios(session, entity_key, scenario_id=scenario_id, limit=1)
        if not snaps:
            return build_scenario_visual_spec(
                visual_type="impact_map", entity_key=entity_key,
                data={"entity_key": entity_key}, evidence_refs=[],
            )
        snap = snaps[0]
        affected = _as_list(_attr(snap, "affected_entities", []))
        nodes = [{"id": entity_key, "root": True}]
        nodes.extend({"id": str(a), "root": False} for a in affected)
        edges = [{"from": entity_key, "to": str(a)} for a in affected]
        data = {
            "entity_key":         entity_key,
            "nodes":              nodes,
            "edges":              edges,
            "affected_forecasts": _as_list(_attr(snap, "affected_forecasts", [])),
            "affected_decisions": _as_list(_attr(snap, "affected_decisions", [])),
        }
        evidence = [f"scenario_snapshot:{_attr(snap, 'id', '')}"]
        return build_scenario_visual_spec(
            visual_type="impact_map", entity_key=entity_key,
            data=data, evidence_refs=evidence,
        )
    except Exception as exc:
        logger.debug("[scenario_visual] build_impact_map_spec failed: %r", exc)
        return None
