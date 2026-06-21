"""
Portfolio + Exposure Visual Service — Phase 19 · Slice 7.

Generates portfolio visual *specifications* (not rendered output).  Each
function reads PortfolioPosition / SimilarityEdge / ScenarioSnapshot
read-only, then delegates to the Slice 19.3 spec builder, which enforces the
explainability gate, the label no-advice scan, and the rendering-tier
assignment.

This module produces specs only.  No SVG.  No images.  No rendering.

Portfolio visuals
-----------------
  build_exposure_map_spec       — exposure broken down by dimension (json)
  build_concentration_map_spec  — concentration heat map (json)
  build_dependency_map_spec     — similarity links between holdings (svg)
  build_scenario_exposure_spec  — portfolio sensitivity to scenarios (svg)

Position weight only — never dollars
------------------------------------
SP-19a forbids dollar amounts and position-sizing language in visuals.
This module reads PortfolioPosition.weight ONLY.  It NEVER reads, surfaces,
or derives cost_basis, shares, or any dollar value.  Visuals show relative
weight, not capital.

Upstream reads are direct ORM selects (PortfolioPosition, SimilarityEdge,
ScenarioSnapshot).  This module never imports portfolio_repo / similarity_repo
/ scenario_repo / any write path — it reads truth, it never mutates it.

Flag gate
---------
  exposure_map, concentration_map → json tier → visual_json_enabled
  dependency_map, scenario_exposure → svg tier → visual_svg_enabled
Functions return None when the tier is disabled or session is None.

A spec whose upstream evidence is missing is returned blocked
(explanation_valid=False, blocked_reason set) — never raised.

SP-19 invariants
----------------
  SP-19a: no advisory language, no position-sizing, no dollar amounts.
  SP-19b: visualization does not change truth — reads only.
  SP-19c: writes nothing.
  SP-19d: no upstream feedback.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from app.services.visual_spec_builder_service import build_portfolio_visual_spec

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


async def _positions(session, portfolio_id: str, *, limit: int = 200) -> List[Any]:
    from app.db.models import PortfolioPosition
    from sqlalchemy import select
    stmt = (
        select(PortfolioPosition)
        .where(PortfolioPosition.portfolio_id == portfolio_id)
        .where(PortfolioPosition.active.is_(True))
        .limit(limit)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def _edges_among(session, tickers: List[str], limit: int = 200) -> List[Any]:
    if not tickers:
        return []
    from app.db.models import SimilarityEdge
    from sqlalchemy import select
    stmt = (
        select(SimilarityEdge)
        .where(SimilarityEdge.query_key.in_(tickers))
        .where(SimilarityEdge.candidate_key.in_(tickers))
        .where(SimilarityEdge.floor_passed.is_(True))
        .limit(limit)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def _scenarios_for(session, tickers: List[str], limit: int = 200) -> List[Any]:
    if not tickers:
        return []
    from app.db.models import ScenarioSnapshot
    from sqlalchemy import select
    stmt = (
        select(ScenarioSnapshot)
        .where(ScenarioSnapshot.entity_key.in_(tickers))
        .limit(limit)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


# ===========================================================================
# § PORTFOLIO VISUALS
# ===========================================================================

async def build_exposure_map_spec(
    session,
    *,
    portfolio_id: str,
    run_override: Optional[bool] = None,
) -> Optional[Dict[str, Any]]:
    """Portfolio exposure broken down by dimension — relative weight only (json)."""
    if not _tier_enabled("json", run_override):
        return None
    if session is None:
        return None
    try:
        positions = await _positions(session, portfolio_id)
        breakdown = [
            {
                "ticker":           _attr(p, "ticker", ""),
                "membership_class": _attr(p, "membership_class", ""),
                "weight":           float(_attr(p, "weight", 0.0) or 0.0),
            }
            for p in positions
        ]
        evidence = [f"portfolio_position:{_attr(p, 'id', '')}" for p in positions]
        data = {"portfolio_id": portfolio_id, "exposure": breakdown}
        return build_portfolio_visual_spec(
            visual_type="exposure_map", entity_key=portfolio_id,
            data=data, evidence_refs=evidence,
        )
    except Exception as exc:
        logger.debug("[portfolio_visual] build_exposure_map_spec failed: %r", exc)
        return None


async def build_concentration_map_spec(
    session,
    *,
    portfolio_id: str,
    run_override: Optional[bool] = None,
) -> Optional[Dict[str, Any]]:
    """Portfolio concentration heat map — relative weight only (json)."""
    if not _tier_enabled("json", run_override):
        return None
    if session is None:
        return None
    try:
        positions = await _positions(session, portfolio_id)
        weights = [
            {
                "ticker": _attr(p, "ticker", ""),
                "weight": float(_attr(p, "weight", 0.0) or 0.0),
            }
            for p in positions
        ]
        max_weight = max((w["weight"] for w in weights), default=0.0)
        evidence = [f"portfolio_position:{_attr(p, 'id', '')}" for p in positions]
        data = {
            "portfolio_id": portfolio_id,
            "weights":      weights,
            "max_weight":   round(max_weight, 4),
        }
        return build_portfolio_visual_spec(
            visual_type="concentration_map", entity_key=portfolio_id,
            data=data, evidence_refs=evidence,
        )
    except Exception as exc:
        logger.debug("[portfolio_visual] build_concentration_map_spec failed: %r", exc)
        return None


async def build_dependency_map_spec(
    session,
    *,
    portfolio_id: str,
    run_override: Optional[bool] = None,
) -> Optional[Dict[str, Any]]:
    """Similarity links between portfolio holdings (svg)."""
    if not _tier_enabled("svg", run_override):
        return None
    if session is None:
        return None
    try:
        positions = await _positions(session, portfolio_id)
        tickers = [_attr(p, "ticker", "") for p in positions]
        edges = await _edges_among(session, tickers)
        nodes = [{"id": t} for t in tickers]
        graph_edges = [
            {
                "from":   _attr(e, "query_key", ""),
                "to":     _attr(e, "candidate_key", ""),
                "weight": float(_attr(e, "score", 0.0)),
            }
            for e in edges
        ]
        evidence = [f"portfolio_position:{_attr(p, 'id', '')}" for p in positions]
        evidence.extend(f"similarity_edge:{_attr(e, 'id', '')}" for e in edges)
        data = {"portfolio_id": portfolio_id, "nodes": nodes, "edges": graph_edges}
        return build_portfolio_visual_spec(
            visual_type="dependency_map", entity_key=portfolio_id,
            data=data, evidence_refs=evidence,
        )
    except Exception as exc:
        logger.debug("[portfolio_visual] build_dependency_map_spec failed: %r", exc)
        return None


async def build_scenario_exposure_spec(
    session,
    *,
    portfolio_id: str,
    run_override: Optional[bool] = None,
) -> Optional[Dict[str, Any]]:
    """Portfolio sensitivity to active scenarios — impact matrix (svg)."""
    if not _tier_enabled("svg", run_override):
        return None
    if session is None:
        return None
    try:
        positions = await _positions(session, portfolio_id)
        tickers = [_attr(p, "ticker", "") for p in positions]
        scenarios = await _scenarios_for(session, tickers)
        matrix = [
            {
                "ticker":       _attr(s, "entity_key", ""),
                "scenario_key": _attr(s, "scenario_key", ""),
                "impact":       _attr(s, "scenario_impact", ""),
                "plausibility": _attr(s, "plausibility_band", ""),
            }
            for s in scenarios
        ]
        evidence = [f"portfolio_position:{_attr(p, 'id', '')}" for p in positions]
        evidence.extend(f"scenario_snapshot:{_attr(s, 'id', '')}" for s in scenarios)
        data = {"portfolio_id": portfolio_id, "matrix": matrix}
        return build_portfolio_visual_spec(
            visual_type="scenario_exposure", entity_key=portfolio_id,
            data=data, evidence_refs=evidence,
        )
    except Exception as exc:
        logger.debug("[portfolio_visual] build_scenario_exposure_spec failed: %r", exc)
        return None
