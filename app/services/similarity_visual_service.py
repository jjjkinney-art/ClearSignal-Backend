"""
Similarity + Precedent Visual Service — Phase 19 · Slice 6.

Generates similarity visual *specifications* (not rendered output).  Each
function reads SimilarityEdge / HistoricalAnalog read-only, then delegates to
the Slice 19.3 spec builder, which enforces the explainability gate, the
label no-advice scan, and the rendering-tier assignment.

This module produces specs only.  No SVG.  No images.  No rendering.

Similarity visuals (all svg tier)
---------------------------------
  build_similarity_network_spec  — force-directed graph of related entities
  build_analog_cluster_spec      — historical analogs grouped by mechanism
  build_precedent_map_spec       — historical precedent timeline
  build_relationship_graph_spec  — multi-dimensional relationship graph

Upstream reads are direct ORM selects (SimilarityEdge, HistoricalAnalog).
This module never imports similarity_repo / forecast_repo / scenario_repo /
decision_repo / any write path — it reads truth, it never mutates it.

Flag gate
---------
All similarity visuals are svg tier → gated on visual_svg_enabled.
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

from app.services.visual_spec_builder_service import build_similarity_visual_spec

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
        try:
            return ts.isoformat()
        except Exception:
            return None


def _as_list(val: Any) -> List[Any]:
    if val is None:
        return []
    if isinstance(val, list):
        return val
    return [val]


async def _similarity_edges(
    session, query_key: str, *, floor_only: bool = True, limit: int = 50,
) -> List[Any]:
    from app.db.models import SimilarityEdge
    from sqlalchemy import select
    stmt = select(SimilarityEdge).where(SimilarityEdge.query_key == query_key)
    if floor_only:
        stmt = stmt.where(SimilarityEdge.floor_passed.is_(True))
    stmt = stmt.order_by(SimilarityEdge.score.desc()).limit(limit)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def _analogs(
    session, *, entity_ticker: Optional[str] = None, limit: int = 50,
) -> List[Any]:
    from app.db.models import HistoricalAnalog
    from sqlalchemy import select
    stmt = select(HistoricalAnalog)
    if entity_ticker is not None:
        stmt = stmt.where(HistoricalAnalog.entity_ticker == entity_ticker)
    stmt = stmt.limit(limit)
    result = await session.execute(stmt)
    return list(result.scalars().all())


# ===========================================================================
# § SIMILARITY VISUALS
# ===========================================================================

async def build_similarity_network_spec(
    session,
    *,
    entity_key: str,
    run_override: Optional[bool] = None,
) -> Optional[Dict[str, Any]]:
    """Force-directed graph of entities related to the query entity (svg)."""
    if not _svg_enabled(run_override):
        return None
    if session is None:
        return None
    try:
        edges = await _similarity_edges(session, entity_key)
        nodes = [{"id": entity_key, "root": True}]
        nodes.extend(
            {"id": _attr(e, "candidate_key", ""), "score": float(_attr(e, "score", 0.0))}
            for e in edges
        )
        graph_edges = [
            {
                "from":   entity_key,
                "to":     _attr(e, "candidate_key", ""),
                "weight": float(_attr(e, "score", 0.0)),
            }
            for e in edges
        ]
        evidence = [f"similarity_edge:{_attr(e, 'id', '')}" for e in edges]
        data = {"entity_key": entity_key, "nodes": nodes, "edges": graph_edges}
        return build_similarity_visual_spec(
            visual_type="similarity_network", entity_key=entity_key,
            data=data, evidence_refs=evidence,
            template_params={"edge_count": len(edges)},
        )
    except Exception as exc:
        logger.debug("[similarity_visual] build_similarity_network_spec failed: %r", exc)
        return None


async def build_analog_cluster_spec(
    session,
    *,
    entity_key: str,
    run_override: Optional[bool] = None,
) -> Optional[Dict[str, Any]]:
    """Historical analogs for an entity grouped by mechanism (svg)."""
    if not _svg_enabled(run_override):
        return None
    if session is None:
        return None
    try:
        analogs = await _analogs(session, entity_ticker=entity_key)
        clusters: Dict[str, List[Dict[str, Any]]] = {}
        for a in analogs:
            mechanism = _attr(a, "mechanism", "")
            clusters.setdefault(mechanism, []).append({
                "label":   _attr(a, "label", ""),
                "quality": _attr(a, "quality_rating", ""),
            })
        cluster_list = [
            {"mechanism": k, "members": v} for k, v in clusters.items()
        ]
        evidence = [f"historical_analog:{_attr(a, 'id', '')}" for a in analogs]
        data = {"entity_key": entity_key, "clusters": cluster_list}
        return build_similarity_visual_spec(
            visual_type="analog_cluster", entity_key=entity_key,
            data=data, evidence_refs=evidence,
        )
    except Exception as exc:
        logger.debug("[similarity_visual] build_analog_cluster_spec failed: %r", exc)
        return None


async def build_precedent_map_spec(
    session,
    *,
    entity_key: str,
    run_override: Optional[bool] = None,
) -> Optional[Dict[str, Any]]:
    """Historical precedent timeline for an entity (svg)."""
    if not _svg_enabled(run_override):
        return None
    if session is None:
        return None
    try:
        analogs = await _analogs(session, entity_ticker=entity_key)
        timeline = sorted(
            [
                {
                    "label":       _attr(a, "label", ""),
                    "event_start": _iso(_attr(a, "event_start", None)),
                    "outcome":     _attr(a, "outcome_summary", ""),
                }
                for a in analogs
            ],
            key=lambda x: x["event_start"] or "",
        )
        evidence = [f"historical_analog:{_attr(a, 'id', '')}" for a in analogs]
        data = {"entity_key": entity_key, "timeline": timeline}
        return build_similarity_visual_spec(
            visual_type="precedent_map", entity_key=entity_key,
            data=data, evidence_refs=evidence,
        )
    except Exception as exc:
        logger.debug("[similarity_visual] build_precedent_map_spec failed: %r", exc)
        return None


async def build_relationship_graph_spec(
    session,
    *,
    entity_key: str,
    run_override: Optional[bool] = None,
) -> Optional[Dict[str, Any]]:
    """Multi-dimensional relationship graph for an entity (svg)."""
    if not _svg_enabled(run_override):
        return None
    if session is None:
        return None
    try:
        edges = await _similarity_edges(session, entity_key)
        graph_edges = []
        for e in edges:
            contribs = _as_list(_attr(e, "contributions", []))
            dimensions = [
                c.get("feature") for c in contribs
                if isinstance(c, dict) and c.get("feature")
            ]
            graph_edges.append({
                "from":       entity_key,
                "to":         _attr(e, "candidate_key", ""),
                "weight":     float(_attr(e, "score", 0.0)),
                "dimensions": dimensions,
            })
        evidence = [f"similarity_edge:{_attr(e, 'id', '')}" for e in edges]
        data = {"entity_key": entity_key, "edges": graph_edges}
        return build_similarity_visual_spec(
            visual_type="relationship_graph", entity_key=entity_key,
            data=data, evidence_refs=evidence,
            template_params={"edge_count": len(edges)},
        )
    except Exception as exc:
        logger.debug("[similarity_visual] build_relationship_graph_spec failed: %r", exc)
        return None
