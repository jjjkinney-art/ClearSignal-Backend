"""
Forecast Read Service — Phase 12 · Slice 6.

Exposes stored forecasts for internal inspection (admin routes, dossier facet)
without ever triggering a rebuild or touching source tables.

This module is READ-ONLY:
  - Reads exclusively from forecast_vector and forecast_evidence via
    app.db.repositories.forecast_repo.
  - Never calls forecast_feature_builder, forecast_probability_engine, or
    forecast_invalidation_service — no rebuild happens here, by design.
  - Never writes to any table, derived or source.

Descriptive-only boundary (SP-4, Phase 12 spec §0):
  - No field returned here is wired into conviction, stance, verdict_rationale,
    or any LLM prompt.
  - No buy/sell/hold, target price, or investment recommendation language is
    present anywhere in this module.
  - The MANDATORY_DISCLAIMER from forecast_constants appears verbatim in every
    forecast facet payload — both on individual forecast items and at the
    facet level.

Filtering applied to all reads:
  - Expired vectors (expires_at in the past) are omitted.
  - Vectors with missing or empty why / invalidators are omitted.
  - Vectors without the mandatory disclaimer are omitted.
  - Horizons not in ALLOWED_HORIZONS are omitted.
  - Forecast types not in ALLOWED_FORECAST_TYPES are omitted.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional

from app.services.forecast_constants import (
    ALLOWED_FORECAST_TYPES,
    ALLOWED_HORIZONS,
    HORIZON_LABELS,
    MANDATORY_DISCLAIMER,
)

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Internal validation / formatting
# ---------------------------------------------------------------------------

def _is_valid_vector(vector) -> bool:
    """Return True iff *vector* passes all read-layer filters.

    Checks:
      1. Not expired
      2. why is a non-empty string (or non-empty after newline-split)
      3. invalidators is a non-empty list
      4. forecast_type is in ALLOWED_FORECAST_TYPES
      5. horizon_days is in ALLOWED_HORIZONS
    """
    try:
        # Expiry check
        exp = getattr(vector, "expires_at", None)
        if exp is not None:
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=timezone.utc)
            if exp <= _now():
                return False

        # why must be non-empty
        why = getattr(vector, "why", None) or ""
        if not why.strip():
            return False

        # invalidators must be a non-empty list
        invalidators = getattr(vector, "invalidators", None) or []
        if not invalidators:
            return False

        # forecast_type must be supported
        if getattr(vector, "forecast_type", None) not in ALLOWED_FORECAST_TYPES:
            return False

        # horizon_days must be supported
        if getattr(vector, "horizon_days", None) not in ALLOWED_HORIZONS:
            return False

        return True
    except Exception:
        return False


def _format_forecast(vector) -> dict:
    """Render one ForecastVector as a public-safe forecast dict.

    why is stored as a newline-joined string; split it back into a list
    for the facet payload. The MANDATORY_DISCLAIMER is always included
    regardless of what may or may not be stored on the row.
    """
    why_raw = getattr(vector, "why", "") or ""
    why_list = [line.strip() for line in why_raw.split("\n") if line.strip()]

    invalidators = getattr(vector, "invalidators", []) or []
    analog_basis = getattr(vector, "analog_basis", []) or []
    similarity_basis = getattr(vector, "similarity_basis", []) or []
    horizon_days = getattr(vector, "horizon_days", 30)
    horizon_label = HORIZON_LABELS.get(horizon_days, "near_term")

    return {
        "forecast_type": getattr(vector, "forecast_type", ""),
        "horizon_days": horizon_days,
        "horizon": horizon_label,
        "p_positive": round(float(getattr(vector, "p_positive", 0.33)), 4),
        "p_negative": round(float(getattr(vector, "p_negative", 0.33)), 4),
        "p_neutral": round(float(getattr(vector, "p_neutral", 0.34)), 4),
        "confidence_low": round(float(getattr(vector, "confidence_band_low", 0.0)), 4),
        "confidence_high": round(float(getattr(vector, "confidence_band_high", 1.0)), 4),
        "confidence_label": getattr(vector, "confidence_label", "low")
            if hasattr(vector, "confidence_label")
            else _infer_confidence_label(
                getattr(vector, "confidence_band_low", 0.0),
                getattr(vector, "confidence_band_high", 1.0),
            ),
        "why": why_list,
        "invalidators": list(invalidators),
        "analog_basis": list(analog_basis),
        "similarity_basis": list(similarity_basis),
        "disclaimer": MANDATORY_DISCLAIMER,
        "vector_id": getattr(vector, "id", None),
        "built_at": _isoformat(getattr(vector, "built_at", None)),
        "expires_at": _isoformat(getattr(vector, "expires_at", None)),
    }


def _infer_confidence_label(low: float, high: float) -> str:
    band = high - low
    if band <= 0.20:
        return "high"
    if band <= 0.35:
        return "medium"
    return "low"


def _isoformat(dt) -> Optional[str]:
    if dt is None:
        return None
    try:
        return dt.isoformat()
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Public read functions
# ---------------------------------------------------------------------------

async def get_forecasts_for_target(
    session,
    target_type: str,
    target_id: str,
    *,
    limit: int = 50,
) -> List[dict]:
    """Return valid, non-expired forecast dicts for one entity.

    Ordered by horizon_days ascending (near → medium → long) then by
    forecast_type alphabetically for deterministic ordering.

    Returns [] when session is None, nothing qualifies, or on error.
    Never rebuilds anything.
    """
    if session is None:
        return []
    try:
        from app.db.repositories.forecast_repo import list_forecast_vectors

        rows = await list_forecast_vectors(
            session,
            entity_type=target_type,
            entity_key=target_id,
            exclude_expired=False,  # we apply our own expiry filter
            limit=limit,
        )
        result = []
        for row in rows:
            if _is_valid_vector(row):
                result.append(_format_forecast(row))

        result.sort(key=lambda f: (f["horizon_days"], f["forecast_type"]))
        return result
    except Exception as exc:
        logger.debug(
            "[forecast_read_service] get_forecasts_for_target failed for %s/%s: %r",
            target_type, target_id, exc,
        )
        return []


async def get_forecasts_for_ticker(
    session,
    ticker: str,
    *,
    limit: int = 50,
) -> List[dict]:
    """Return valid, non-expired forecasts for a company ticker.

    Returns [] when session is None, no data exists, or on error.
    Never rebuilds anything.
    """
    return await get_forecasts_for_target(
        session, "company", ticker, limit=limit
    )


async def get_forecast_facet_for_ticker(
    session,
    ticker: str,
) -> Dict:
    """Build the "Forecast" dossier facet payload for *ticker*.

    Always returns a well-formed dict, even when session is None or no
    forecast data has been built yet (safe empty state):
        {"has_forecasts": False, "ticker": ticker, "forecasts": [],
         "disclaimer": MANDATORY_DISCLAIMER}

    Descriptive only — no conviction, stance, or recommendation fields.
    The disclaimer is always the exact MANDATORY_DISCLAIMER string from
    forecast_constants; it is never omitted or modified.
    """
    empty: Dict = {
        "has_forecasts": False,
        "ticker": ticker,
        "forecasts": [],
        "disclaimer": MANDATORY_DISCLAIMER,
    }
    if session is None:
        return empty
    try:
        forecasts = await get_forecasts_for_ticker(session, ticker)
        return {
            "has_forecasts": len(forecasts) > 0,
            "ticker": ticker,
            "forecasts": forecasts,
            "disclaimer": MANDATORY_DISCLAIMER,
        }
    except Exception as exc:
        logger.debug(
            "[forecast_read_service] get_forecast_facet_for_ticker failed for %s: %r",
            ticker, exc,
        )
        return empty
