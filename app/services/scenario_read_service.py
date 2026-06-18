"""
Scenario Read Service — Phase 14 · Slice 6.

Read-only access to stored ScenarioSnapshot rows.  Never rebuilds,
propagates, explains, or writes anything.

Core rule: this module calls only scenario_repo read functions. It does NOT
import scenario_seed_builder, scenario_propagation_engine,
scenario_explainability_service, or scenario_invalidation_service. Any call
that would trigger a rebuild, propagation, or write is forbidden here.

Safety invariants (SP-6)
------------------------
  - No write, add, update, delete path exists.
  - No import from rebuild/propagation/explanation/invalidation modules.
  - No import from delivery, notification, or conviction modules.
  - No buy/sell/hold/recommend/target-price/position-size language in any
    generated field.
  - The DISCLAIMER is appended verbatim to every scenario item and aggregate.

Read filters applied to all list operations
-------------------------------------------
  - exclude_expired=True  (expires_at > now)
  - what_changed non-empty  (explanation exists)
  - evidence_summary non-empty  (evidence exists)
  - transmission_path non-empty  (propagation path exists)
  - scenario_type in _SUPPORTED_TYPES
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DISCLAIMER = (
    "This information is generated from automated structural analysis and does not "
    "constitute financial advice, investment guidance, a prediction of future "
    "outcomes, or any suggestion to take action. "
    "All scenarios are conditional and carry inherent uncertainty."
)

_SUPPORTED_TYPES = frozenset({
    "company_scenario",
    "macro_scenario",
    "sector_scenario",
    "catalyst_scenario",
    "failure_mode_scenario",
    "portfolio_scenario",
})


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# JSON column safe reader
# ---------------------------------------------------------------------------

def _read_json(value: Any) -> list:
    """Safely read a JSON column that may be stored as str or already parsed."""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else []
        except Exception:
            return []
    return []


# ---------------------------------------------------------------------------
# Row validation
# ---------------------------------------------------------------------------

def _is_valid_snapshot(row) -> bool:
    """Return True iff *row* passes all read-layer filters."""
    try:
        # Expiry
        exp = getattr(row, "expires_at", None)
        if exp is None:
            return False
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        if exp <= _now():
            return False

        # Explanation must exist
        if not (getattr(row, "what_changed", None) or "").strip():
            return False

        # Evidence must exist
        if not _read_json(getattr(row, "evidence_summary", None)):
            return False

        # Transmission path must exist
        if not _read_json(getattr(row, "transmission_path", None)):
            return False

        # Supported type only
        if getattr(row, "scenario_type", "") not in _SUPPORTED_TYPES:
            return False

        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Row → output dict
# ---------------------------------------------------------------------------

def _format_snapshot(row) -> Dict[str, Any]:
    """Render one ScenarioSnapshot row as a public-safe scenario dict."""
    entity_key      = getattr(row, "entity_key", "") or ""
    scenario_type   = getattr(row, "scenario_type", "") or ""
    scenario_key    = getattr(row, "scenario_key", "") or ""
    condition       = getattr(row, "condition", "") or ""
    what_changed    = getattr(row, "what_changed", "") or ""
    why_it_matters  = getattr(row, "why_it_matters", "") or ""
    scenario_impact = getattr(row, "scenario_impact", "ambiguous") or "ambiguous"
    plausibility    = getattr(row, "plausibility_band", "plausible") or "plausible"
    confidence      = float(getattr(row, "confidence_score", 0.0) or 0.0)
    uncertainty     = float(getattr(row, "uncertainty_score", 0.0) or 0.0)

    transmission_path  = _read_json(getattr(row, "transmission_path",  None))
    evidence_summary   = _read_json(getattr(row, "evidence_summary",   None))
    invalidators       = _read_json(getattr(row, "invalidators",       None))
    affected_entities  = _read_json(getattr(row, "affected_entities",  None))

    # Derive affected_tickers: entity_key strings from affected_entities
    affected_tickers = [
        e.get("entity_key") or e if isinstance(e, str) else str(e)
        for e in affected_entities
        if e
    ]

    # affected_portfolios: from affected_entities with entity_type == "portfolio"
    affected_portfolios = [
        e.get("entity_key", "")
        for e in affected_entities
        if isinstance(e, dict) and e.get("entity_type") == "portfolio"
    ]

    # impact_summary: first sentence of what_changed + why_it_matters
    wc_first    = what_changed.split(".")[0].strip() if what_changed else ""
    wm_first    = why_it_matters.split(".")[0].strip() if why_it_matters else ""
    impact_summary = ". ".join(s for s in [wc_first, wm_first] if s)

    built_at   = getattr(row, "built_at",   None)
    expires_at = getattr(row, "expires_at", None)

    # why_it_matters as sentence list (for rich clients)
    why_matters_list = [
        s.strip() + "." for s in why_it_matters.split(". ") if s.strip()
    ]
    if why_matters_list and why_matters_list[-1].endswith(".."):
        why_matters_list[-1] = why_matters_list[-1][:-1]

    return {
        "ticker":              entity_key,
        "scenario_type":       scenario_type,
        "scenario_name":       scenario_key,
        "changed_assumption":  condition,
        "affected_tickers":    affected_tickers,
        "affected_portfolios": affected_portfolios,
        "impact_summary":      impact_summary,
        "scenario_impact":     scenario_impact,
        "plausibility_band":   plausibility,
        "transmission_path":   transmission_path,
        "evidence":            evidence_summary,
        "invalidators":        invalidators,
        "why_it_matters":      why_matters_list,
        "confidence":          round(confidence, 4),
        "uncertainty":         round(uncertainty, 4),
        "generated_at":        built_at.isoformat()   if built_at   else None,
        "expires_at":          expires_at.isoformat() if expires_at else None,
        "disclaimer":          _DISCLAIMER,
    }


# ---------------------------------------------------------------------------
# Empty-state helpers
# ---------------------------------------------------------------------------

def _empty_ticker_payload(ticker: str) -> Dict[str, Any]:
    return {
        "ticker":        ticker.upper() if ticker else "",
        "has_scenarios": False,
        "scenarios":     [],
        "count":         0,
        "disclaimer":    _DISCLAIMER,
    }


def _empty_user_payload(user_id: str) -> Dict[str, Any]:
    return {
        "user_id":       user_id,
        "has_scenarios": False,
        "scenarios":     [],
        "count":         0,
        "disclaimer":    _DISCLAIMER,
    }


def _empty_facet(ticker: str) -> Dict[str, Any]:
    return {
        "ticker":         ticker.upper() if ticker else "",
        "has_scenarios":  False,
        "top_plausibility": "none",
        "top_confidence": 0.0,
        "type_counts":    {},
        "scenarios":      [],
        "disclaimer":     _DISCLAIMER,
    }


# ---------------------------------------------------------------------------
# Public read functions
# ---------------------------------------------------------------------------

async def get_scenarios_for_ticker(
    session,
    ticker: str,
    *,
    limit: int = 10,
    user_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Return formatted scenarios for *ticker*.

    Returns all stored non-expired, valid scenario snapshots for the ticker,
    sorted by confidence_score descending, capped at *limit*.

    Returns the safe empty state when session is None or no rows exist.
    Never rebuilds or writes.
    """
    if session is None:
        return _empty_ticker_payload(ticker)
    try:
        from app.db.repositories.scenario_repo import list_scenario_snapshots

        rows = await list_scenario_snapshots(
            session,
            entity_key=ticker.upper(),
            user_id=user_id,
            exclude_expired=True,
            limit=limit * 3,
        )
        valid = [_format_snapshot(r) for r in rows if _is_valid_snapshot(r)]
        valid = sorted(valid, key=lambda x: x["confidence"], reverse=True)[:limit]

        return {
            "ticker":        ticker.upper(),
            "has_scenarios": bool(valid),
            "scenarios":     valid,
            "count":         len(valid),
            "disclaimer":    _DISCLAIMER,
        }
    except Exception as exc:
        logger.debug("[scenario_read] get_scenarios_for_ticker error: %r", exc)
        return _empty_ticker_payload(ticker)


async def get_scenarios_for_user(
    session,
    user_id: str,
    *,
    limit: int = 20,
) -> Dict[str, Any]:
    """Return formatted scenarios scoped to *user_id*.

    Returns the safe empty state when session is None or no rows exist.
    Never rebuilds or writes.
    """
    if session is None or not user_id:
        return _empty_user_payload(user_id or "")
    try:
        from app.db.repositories.scenario_repo import list_scenario_snapshots

        rows = await list_scenario_snapshots(
            session,
            user_id=user_id,
            exclude_expired=True,
            limit=limit * 3,
        )
        valid = [_format_snapshot(r) for r in rows if _is_valid_snapshot(r)]
        valid = sorted(valid, key=lambda x: x["confidence"], reverse=True)[:limit]

        return {
            "user_id":       user_id,
            "has_scenarios": bool(valid),
            "scenarios":     valid,
            "count":         len(valid),
            "disclaimer":    _DISCLAIMER,
        }
    except Exception as exc:
        logger.debug("[scenario_read] get_scenarios_for_user error: %r", exc)
        return _empty_user_payload(user_id)


async def get_top_scenarios(
    session,
    *,
    limit: int = 20,
    user_id: Optional[str] = None,
    scenario_type: Optional[str] = None,
) -> Dict[str, Any]:
    """Return the highest-confidence valid scenarios across all entities.

    When *user_id* is given, restricts to that user's scope.
    When *scenario_type* is given, restricts to that type.
    Returns the safe empty state when session is None.
    Never rebuilds or writes.
    """
    if session is None:
        return {"has_scenarios": False, "scenarios": [], "count": 0, "disclaimer": _DISCLAIMER}
    try:
        from app.db.repositories.scenario_repo import list_scenario_snapshots

        rows = await list_scenario_snapshots(
            session,
            scenario_type=scenario_type,
            user_id=user_id,
            exclude_expired=True,
            limit=limit * 3,
        )
        valid = [_format_snapshot(r) for r in rows if _is_valid_snapshot(r)]
        valid = sorted(valid, key=lambda x: x["confidence"], reverse=True)[:limit]

        return {
            "has_scenarios": bool(valid),
            "scenarios":     valid,
            "count":         len(valid),
            "disclaimer":    _DISCLAIMER,
        }
    except Exception as exc:
        logger.debug("[scenario_read] get_top_scenarios error: %r", exc)
        return {"has_scenarios": False, "scenarios": [], "count": 0, "disclaimer": _DISCLAIMER}


async def get_scenario_facet_for_ticker(
    session,
    ticker: str,
    *,
    user_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Return a condensed scenario facet for *ticker* for dossier/UI integration.

    Returns only the top-3 valid scenarios, with a facet-level summary:
      - has_scenarios
      - top_plausibility  (highest plausibility band seen, or "none")
      - top_confidence    (highest confidence_score, or 0.0)
      - type_counts       ({scenario_type: count})
      - scenarios         (top-3, formatted)

    Returns the safe empty facet when session is None or no rows exist.
    Never rebuilds or writes.
    """
    if session is None:
        return _empty_facet(ticker)
    try:
        from app.db.repositories.scenario_repo import list_scenario_snapshots

        rows = await list_scenario_snapshots(
            session,
            entity_key=ticker.upper(),
            user_id=user_id,
            exclude_expired=True,
            limit=50,
        )
        valid = [r for r in rows if _is_valid_snapshot(r)]

        type_counts: Dict[str, int] = {}
        for r in valid:
            st = getattr(r, "scenario_type", "unknown")
            type_counts[st] = type_counts.get(st, 0) + 1

        _band_rank = {"likely_conditional": 2, "plausible": 1, "remote": 0, "none": -1}
        top_plausibility = "none"
        for r in valid:
            pb = getattr(r, "plausibility_band", "remote") or "remote"
            if _band_rank.get(pb, -1) > _band_rank.get(top_plausibility, -1):
                top_plausibility = pb

        top_confidence = max(
            (float(getattr(r, "confidence_score", 0.0) or 0.0) for r in valid),
            default=0.0,
        )

        top3 = [_format_snapshot(r) for r in valid[:3]]

        return {
            "ticker":           ticker.upper(),
            "has_scenarios":    bool(valid),
            "top_plausibility": top_plausibility,
            "top_confidence":   round(top_confidence, 4),
            "type_counts":      type_counts,
            "scenarios":        top3,
            "disclaimer":       _DISCLAIMER,
        }
    except Exception as exc:
        logger.debug("[scenario_read] get_scenario_facet_for_ticker error: %r", exc)
        return _empty_facet(ticker)


async def build_scenario_status_snapshot(session) -> Dict[str, Any]:
    """Return a read-only admin observability snapshot of the scenario layer.

    Covers:
      - All 6 scenario_* config flags
      - Row counts (total, valid, expired, by type, by plausibility)
      - Latest built_at timestamp
      - safe_state: True when scenario_shadow=True and delivery_enabled=False
      - db_available

    Returns a degraded-but-valid snapshot when session is None.
    Never rebuilds or writes.
    """
    from app.config import settings

    flags = {
        "scenario_build_enabled":       settings.scenario_build_enabled,
        "scenario_scoring_enabled":     settings.scenario_scoring_enabled,
        "scenario_delivery_enabled":    settings.scenario_delivery_enabled,
        "scenario_shadow":              settings.scenario_shadow,
        "scenario_targets_enabled":     settings.scenario_targets_enabled,
        "scenario_calibration_enabled": settings.scenario_calibration_enabled,
    }

    empty_counts: Dict[str, Any] = {
        "total":              0,
        "valid":              0,
        "expired":            0,
        "by_type":            {},
        "by_plausibility":    {},
        "latest_built_at":    None,
    }

    if session is None:
        return {
            "flags":        flags,
            "counts":       empty_counts,
            "db_available": False,
            "safe_state":   settings.scenario_shadow and not settings.scenario_delivery_enabled,
            "disclaimer":   _DISCLAIMER,
        }

    try:
        from app.db.repositories.scenario_repo import (
            list_scenario_snapshots,
            count_scenario_snapshots,
        )

        total_count = await count_scenario_snapshots(session)
        all_rows    = await list_scenario_snapshots(session, limit=2000)
        now = _now()

        by_type:        Dict[str, int] = {}
        by_plausibility: Dict[str, int] = {}
        valid_count   = 0
        expired_count = 0
        latest_ts: Optional[datetime] = None

        for r in all_rows:
            st = getattr(r, "scenario_type", "unknown")
            pb = getattr(r, "plausibility_band", "plausible") or "plausible"
            by_type[st]        = by_type.get(st, 0) + 1
            by_plausibility[pb] = by_plausibility.get(pb, 0) + 1

            exp = getattr(r, "expires_at", None)
            if exp is not None:
                if exp.tzinfo is None:
                    exp = exp.replace(tzinfo=timezone.utc)
                if exp <= now:
                    expired_count += 1
                elif _is_valid_snapshot(r):
                    valid_count += 1

            bat = getattr(r, "built_at", None)
            if bat is not None:
                if latest_ts is None or bat > latest_ts:
                    latest_ts = bat

        counts: Dict[str, Any] = {
            "total":           total_count,
            "valid":           valid_count,
            "expired":         expired_count,
            "by_type":         by_type,
            "by_plausibility": by_plausibility,
            "latest_built_at": latest_ts.isoformat() if latest_ts else None,
        }

        safe_state = (
            settings.scenario_shadow
            and not settings.scenario_delivery_enabled
        )

        return {
            "flags":        flags,
            "counts":       counts,
            "db_available": True,
            "safe_state":   safe_state,
            "disclaimer":   _DISCLAIMER,
        }

    except Exception as exc:
        logger.debug("[scenario_read] build_scenario_status_snapshot error: %r", exc)
        return {
            "flags":        flags,
            "counts":       empty_counts,
            "db_available": False,
            "safe_state":   False,
            "disclaimer":   _DISCLAIMER,
        }
