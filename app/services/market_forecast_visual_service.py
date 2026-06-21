"""
Market + Forecast Visual Service — Phase 19 · Slice 4.

Generates market and forecast visual *specifications* (not rendered output).
Each function reads upstream intelligence read-only, then delegates to the
Slice 19.3 spec builder, which enforces the explainability gate, the label
no-advice scan, and the rendering-tier assignment.

This module produces specs only.  No SVG.  No images.  No rendering.

Market visuals
--------------
  build_price_chart_spec         — price history with annotated events (json)
  build_performance_chart_spec   — performance vs benchmark window (json)
  build_volatility_chart_spec    — price with volatility bands (json)
  build_evidence_timeline_spec   — chronological evidence markers (svg)

Forecast visuals
----------------
  build_distribution_spec        — probability distribution (json)
  build_outcome_tree_spec        — branching forecast outcomes (svg)
  build_confidence_band_spec     — confidence envelope over time (json)
  build_forecast_evolution_spec  — how the forecast shifted over time (json)

Upstream reads are direct ORM selects (MemoryEntry, ForecastVector).  This
module never imports forecast_repo / decision_repo / scenario_repo /
similarity_repo / any write path — it reads truth, it never mutates it.

Flag gate
---------
Each spec is gated on its rendering tier:
  json  → visual_json_enabled
  svg   → visual_svg_enabled
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
from datetime import datetime, timezone
from typing import Any, List, Optional, Dict

from app.services.visual_spec_builder_service import (
    build_market_visual_spec,
    build_forecast_visual_spec,
)

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
        if tier == "ai_image":
            return bool(getattr(settings, "visual_ai_enabled", False))
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


def _date_str(ts: Any) -> str:
    if ts is None:
        return ""
    try:
        if hasattr(ts, "date"):
            return ts.date().isoformat()
        return str(ts)[:10]
    except Exception:
        return ""


async def _memory_entries(session, ticker: str, limit: int = 20) -> List[Any]:
    from app.db.models import MemoryEntry
    from sqlalchemy import select
    stmt = (
        select(MemoryEntry)
        .where(MemoryEntry.ticker == ticker)
        .order_by(MemoryEntry.created_at.desc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def _forecast_vectors(
    session, entity_key: str, *, forecast_type: Optional[str] = None, limit: int = 20,
) -> List[Any]:
    from app.db.models import ForecastVector
    from sqlalchemy import select
    stmt = select(ForecastVector).where(ForecastVector.entity_key == entity_key)
    if forecast_type is not None:
        stmt = stmt.where(ForecastVector.forecast_type == forecast_type)
    stmt = stmt.order_by(ForecastVector.built_at.desc()).limit(limit)
    result = await session.execute(stmt)
    return list(result.scalars().all())


# ===========================================================================
# § MARKET VISUALS
# ===========================================================================

async def build_price_chart_spec(
    session,
    *,
    entity_key: str,
    run_override: Optional[bool] = None,
) -> Optional[Dict[str, Any]]:
    """Price history for an entity with annotated analysis events (json)."""
    if not _tier_enabled("json", run_override):
        return None
    if session is None:
        return None
    try:
        entries = await _memory_entries(session, entity_key)
        markers = [
            {
                "at":         _iso(_attr(e, "created_at", None)),
                "entry_type": _attr(e, "entry_type", ""),
            }
            for e in entries
        ]
        evidence = [f"memory_entry:{_attr(e, 'id', '')}" for e in entries]
        data = {"entity_key": entity_key, "event_markers": markers}
        return build_market_visual_spec(
            visual_type="price_chart", entity_key=entity_key,
            data=data, evidence_refs=evidence,
        )
    except Exception as exc:
        logger.debug("[market_forecast_visual] build_price_chart_spec failed: %r", exc)
        return None


async def build_performance_chart_spec(
    session,
    *,
    entity_key: str,
    run_override: Optional[bool] = None,
) -> Optional[Dict[str, Any]]:
    """Performance of an entity over the tracked window (json)."""
    if not _tier_enabled("json", run_override):
        return None
    if session is None:
        return None
    try:
        entries = await _memory_entries(session, entity_key)
        evidence = [f"memory_entry:{_attr(e, 'id', '')}" for e in entries]
        data = {
            "entity_key":  entity_key,
            "event_count": len(entries),
        }
        return build_market_visual_spec(
            visual_type="performance_chart", entity_key=entity_key,
            data=data, evidence_refs=evidence,
        )
    except Exception as exc:
        logger.debug("[market_forecast_visual] build_performance_chart_spec failed: %r", exc)
        return None


async def build_volatility_chart_spec(
    session,
    *,
    entity_key: str,
    run_override: Optional[bool] = None,
) -> Optional[Dict[str, Any]]:
    """Price with volatility bands derived from forecast confidence width (json)."""
    if not _tier_enabled("json", run_override):
        return None
    if session is None:
        return None
    try:
        vectors = await _forecast_vectors(session, entity_key, limit=1)
        if not vectors:
            return build_market_visual_spec(
                visual_type="volatility_overlay", entity_key=entity_key,
                data={"entity_key": entity_key}, evidence_refs=[],
            )
        fv = vectors[0]
        low = float(_attr(fv, "confidence_band_low", 0.0))
        high = float(_attr(fv, "confidence_band_high", 1.0))
        data = {
            "entity_key":     entity_key,
            "band_low":       low,
            "band_high":      high,
            "band_width":     round(max(0.0, high - low), 4),
        }
        evidence = [f"forecast_vector:{_attr(fv, 'id', '')}"]
        return build_market_visual_spec(
            visual_type="volatility_overlay", entity_key=entity_key,
            data=data, evidence_refs=evidence,
        )
    except Exception as exc:
        logger.debug("[market_forecast_visual] build_volatility_chart_spec failed: %r", exc)
        return None


async def build_evidence_timeline_spec(
    session,
    *,
    entity_key: str,
    run_override: Optional[bool] = None,
) -> Optional[Dict[str, Any]]:
    """Chronological evidence markers for an entity (svg)."""
    if not _tier_enabled("svg", run_override):
        return None
    if session is None:
        return None
    try:
        entries = await _memory_entries(session, entity_key, limit=50)
        timeline = sorted(
            [
                {
                    "at":         _iso(_attr(e, "created_at", None)),
                    "entry_type": _attr(e, "entry_type", ""),
                }
                for e in entries
            ],
            key=lambda x: x["at"] or "",
        )
        evidence = [f"memory_entry:{_attr(e, 'id', '')}" for e in entries]
        data = {"entity_key": entity_key, "timeline": timeline}
        return build_market_visual_spec(
            visual_type="evidence_timeline", entity_key=entity_key,
            data=data, evidence_refs=evidence,
        )
    except Exception as exc:
        logger.debug("[market_forecast_visual] build_evidence_timeline_spec failed: %r", exc)
        return None


# ===========================================================================
# § FORECAST VISUALS
# ===========================================================================

async def build_distribution_spec(
    session,
    *,
    entity_key: str,
    run_override: Optional[bool] = None,
) -> Optional[Dict[str, Any]]:
    """Forecast probability distribution across scenarios (json)."""
    if not _tier_enabled("json", run_override):
        return None
    if session is None:
        return None
    try:
        vectors = await _forecast_vectors(session, entity_key, limit=1)
        if not vectors:
            return build_forecast_visual_spec(
                visual_type="forecast_distribution", entity_key=entity_key,
                data={"entity_key": entity_key}, evidence_refs=[],
                template_params={"as_of_date": ""},
            )
        fv = vectors[0]
        built_at = _attr(fv, "built_at", None)
        data = {
            "entity_key":  entity_key,
            "p_positive":  float(_attr(fv, "p_positive", 0.0)),
            "p_negative":  float(_attr(fv, "p_negative", 0.0)),
            "p_neutral":   float(_attr(fv, "p_neutral", 0.0)),
            "as_of":       _iso(built_at),
        }
        evidence = [f"forecast_vector:{_attr(fv, 'id', '')}"]
        return build_forecast_visual_spec(
            visual_type="forecast_distribution", entity_key=entity_key,
            data=data, evidence_refs=evidence,
            template_params={"as_of_date": _date_str(built_at)},
        )
    except Exception as exc:
        logger.debug("[market_forecast_visual] build_distribution_spec failed: %r", exc)
        return None


async def build_outcome_tree_spec(
    session,
    *,
    entity_key: str,
    run_override: Optional[bool] = None,
) -> Optional[Dict[str, Any]]:
    """Branching forecast outcomes across forecast types (svg)."""
    if not _tier_enabled("svg", run_override):
        return None
    if session is None:
        return None
    try:
        vectors = await _forecast_vectors(session, entity_key, limit=20)
        branches = [
            {
                "forecast_type": _attr(v, "forecast_type", ""),
                "horizon":       _attr(v, "horizon", ""),
                "p_positive":    float(_attr(v, "p_positive", 0.0)),
                "p_negative":    float(_attr(v, "p_negative", 0.0)),
            }
            for v in vectors
        ]
        evidence = [f"forecast_vector:{_attr(v, 'id', '')}" for v in vectors]
        data = {"entity_key": entity_key, "branches": branches}
        return build_forecast_visual_spec(
            visual_type="outcome_tree", entity_key=entity_key,
            data=data, evidence_refs=evidence,
        )
    except Exception as exc:
        logger.debug("[market_forecast_visual] build_outcome_tree_spec failed: %r", exc)
        return None


async def build_confidence_band_spec(
    session,
    *,
    entity_key: str,
    run_override: Optional[bool] = None,
) -> Optional[Dict[str, Any]]:
    """Forecast confidence envelope over time (json)."""
    if not _tier_enabled("json", run_override):
        return None
    if session is None:
        return None
    try:
        vectors = await _forecast_vectors(session, entity_key, limit=20)
        if not vectors:
            return build_forecast_visual_spec(
                visual_type="confidence_band", entity_key=entity_key,
                data={"entity_key": entity_key}, evidence_refs=[],
            )
        series = [
            {
                "at":        _iso(_attr(v, "built_at", None)),
                "band_low":  float(_attr(v, "confidence_band_low", 0.0)),
                "band_high": float(_attr(v, "confidence_band_high", 1.0)),
            }
            for v in vectors
        ]
        evidence = [f"forecast_vector:{_attr(v, 'id', '')}" for v in vectors]
        data = {"entity_key": entity_key, "series": series}
        return build_forecast_visual_spec(
            visual_type="confidence_band", entity_key=entity_key,
            data=data, evidence_refs=evidence,
        )
    except Exception as exc:
        logger.debug("[market_forecast_visual] build_confidence_band_spec failed: %r", exc)
        return None


async def build_forecast_evolution_spec(
    session,
    *,
    entity_key: str,
    forecast_type: Optional[str] = None,
    run_override: Optional[bool] = None,
) -> Optional[Dict[str, Any]]:
    """How the forecast for an entity shifted over time (json)."""
    if not _tier_enabled("json", run_override):
        return None
    if session is None:
        return None
    try:
        vectors = await _forecast_vectors(
            session, entity_key, forecast_type=forecast_type, limit=50,
        )
        if not vectors:
            return build_forecast_visual_spec(
                visual_type="forecast_evolution", entity_key=entity_key,
                data={"entity_key": entity_key}, evidence_refs=[],
            )
        ordered = sorted(
            vectors, key=lambda v: _iso(_attr(v, "built_at", None)) or "",
        )
        series = [
            {
                "at":         _iso(_attr(v, "built_at", None)),
                "p_positive": float(_attr(v, "p_positive", 0.0)),
                "p_negative": float(_attr(v, "p_negative", 0.0)),
                "p_neutral":  float(_attr(v, "p_neutral", 0.0)),
            }
            for v in ordered
        ]
        evidence = [f"forecast_vector:{_attr(v, 'id', '')}" for v in vectors]
        data = {"entity_key": entity_key, "series": series}
        return build_forecast_visual_spec(
            visual_type="forecast_evolution", entity_key=entity_key,
            data=data, evidence_refs=evidence,
        )
    except Exception as exc:
        logger.debug("[market_forecast_visual] build_forecast_evolution_spec failed: %r", exc)
        return None
