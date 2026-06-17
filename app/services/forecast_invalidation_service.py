"""
Forecast Invalidation + Rebuild Orchestration — Phase 12 · Slice 5.

Composes the Phase 12 pipeline end-to-end for T1 (company) and T4
(failure_mode) targets:

  feature_builder → probability_engine → explainability_service → forecast_repo

A forecast vector is only written when ALL of the following hold:
  1. Flag gates pass (forecast_build_enabled + forecast_scoring_enabled)
  2. Feature builder returns non-None features
  3. Probability distribution validates (sum ≈ 1.0, each ∈ [0.01, 0.99])
  4. Explanation validates (non-empty why/evidence/invalidators, verbatim
     disclaimer, no banned advice language)

T2 (thesis) and portfolio forecasts remain deferred to Phase 13 per spec §16.

Flags (from app.config.Settings)
---------------------------------
  forecast_build_enabled    — master gate; False (default) → all rebuilds no-op
  forecast_scoring_enabled  — secondary gate; False → pipeline blocked
  forecast_targets_enabled  — comma-separated entity_type allowlist used by the
                              batch function; empty → no type auto-scheduled

All public rebuild functions accept a ``_build_override`` keyword argument that
bypasses all config flag checks. This is the test-seam: tests pass
``_build_override=True`` to exercise the full pipeline without touching real
config. ``_build_override=False`` forces inert even if config is enabled.

Safety invariants (Phase 12 spec §0 / SP-4)
--------------------------------------------
  - No delivery_ledger row, Notification row, or audit_log row is written.
  - No conviction, stance, verdict_rationale, or LLM-prompt field is read or
    written anywhere in this module.
  - No source table (company_dossier, dossier_*, thesis_versions,
    historical_analogs, similarity_edge) is mutated — this module only writes
    forecast_vector and forecast_evidence rows.
  - Null-session safety: every function returns None / [] / {} / 0 / False
    when session is None.
  - Forecast output (p_positive, p_negative, p_neutral) is stored only;
    it must not flow into conviction, stance, or any LLM prompt (SP-4).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

DEFAULT_FORECAST_TTL_HOURS: int = 24
_SUPPORTED_TARGET_TYPES: tuple = ("company", "failure_mode")


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Flag resolution (test-seam aware)
# ---------------------------------------------------------------------------

def _pipeline_approved(build_override: Optional[bool]) -> bool:
    """Return True iff both build and scoring flags are enabled (or overridden).

    ``build_override=True``  → always approved (test seam).
    ``build_override=False`` → always blocked (force-inert seam).
    ``build_override=None``  → consult settings.forecast_build_enabled AND
                               settings.forecast_scoring_enabled; both must
                               be True for the pipeline to run.
    """
    if build_override is not None:
        return bool(build_override)
    try:
        from app.config import settings
        build = bool(getattr(settings, "forecast_build_enabled", False))
        score = bool(getattr(settings, "forecast_scoring_enabled", False))
        return build and score
    except Exception:
        return False


def _batch_target_approved(target_type: str, build_override: Optional[bool]) -> bool:
    """Return True iff *target_type* is in the forecast_targets_enabled allowlist.

    When ``build_override`` is non-None the allowlist check is bypassed.
    Default (empty allowlist) → all types blocked for automatic batch runs.
    """
    if build_override is not None:
        return True
    try:
        from app.config import settings
        enabled = getattr(settings, "forecast_targets_enabled", "") or ""
        if not enabled.strip():
            return False
        return target_type in [t.strip() for t in enabled.split(",")]
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Feature builder dispatch
# ---------------------------------------------------------------------------

async def _build_features(session, target_type: str, target_id: str) -> Optional[dict]:
    try:
        if target_type == "company":
            from app.services.forecast_feature_builder import build_company_forecast_features
            return await build_company_forecast_features(session, target_id)
        elif target_type == "failure_mode":
            from app.services.forecast_feature_builder import (
                build_failure_mode_forecast_features,
            )
            return await build_failure_mode_forecast_features(session, target_id)
        else:
            logger.debug(
                "[forecast_invalidation] unsupported target_type: %r", target_type
            )
            return None
    except Exception as exc:
        logger.debug("[forecast_invalidation] _build_features error: %r", exc)
        return None


def _score_features(
    features: dict,
    target_type: str,
    forecast_type: str,
    horizon_days: int,
) -> dict:
    if target_type == "company":
        from app.services.forecast_probability_engine import score_company_forecast
        return score_company_forecast(features, forecast_type, horizon_days)
    else:  # failure_mode
        from app.services.forecast_probability_engine import score_failure_mode_forecast
        return score_failure_mode_forecast(features, forecast_type, horizon_days)


# ---------------------------------------------------------------------------
# Staleness detection
# ---------------------------------------------------------------------------

async def is_forecast_stale(
    session,
    forecast_vector,
    *,
    ttl_hours: int = DEFAULT_FORECAST_TTL_HOURS,
) -> bool:
    """Return True if *forecast_vector* should be rebuilt.

    A vector is stale when:
      - expires_at <= now()                    (TTL expired as stored at upsert)
      - built_at + ttl_hours <= now()          (explicit caller TTL override)

    Either condition alone is sufficient.  Returns False when session is None
    or forecast_vector is None.
    """
    if session is None or forecast_vector is None:
        return False
    try:
        now = _now()

        # Check stored expires_at
        exp = getattr(forecast_vector, "expires_at", None)
        if exp is not None:
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=timezone.utc)
            if exp <= now:
                return True

        # Check explicit TTL override against built_at
        built = getattr(forecast_vector, "built_at", None)
        if built is not None:
            if built.tzinfo is None:
                built = built.replace(tzinfo=timezone.utc)
            if built + timedelta(hours=ttl_hours) <= now:
                return True

        return False
    except Exception as exc:
        logger.debug("[forecast_invalidation] is_forecast_stale error: %r", exc)
        return False


async def find_stale_forecasts(
    session,
    *,
    target_type: Optional[str] = None,
    limit: int = 200,
) -> List[object]:
    """Return ForecastVector rows whose expires_at <= now().

    Optionally filtered by entity_type.  Ordered by expires_at ascending
    (oldest first) so the most overdue vectors are rebuilt first.
    Returns [] when session is None or on error.
    """
    if session is None:
        return []
    try:
        from app.db.models import ForecastVector
        from sqlalchemy import select

        now = _now()
        stmt = select(ForecastVector).where(ForecastVector.expires_at <= now)
        if target_type is not None:
            stmt = stmt.where(ForecastVector.entity_type == target_type)
        stmt = stmt.order_by(ForecastVector.expires_at.asc()).limit(limit)
        result = await session.execute(stmt)
        return list(result.scalars().all())
    except Exception as exc:
        logger.debug("[forecast_invalidation] find_stale_forecasts error: %r", exc)
        return []


# ---------------------------------------------------------------------------
# Core rebuild pipeline
# ---------------------------------------------------------------------------

async def rebuild_forecast_for_target(
    session,
    target_type: str,
    target_id: str,
    forecast_type: str,
    horizon_days: int,
    *,
    _build_override: Optional[bool] = None,
) -> Optional[Dict]:
    """Build, score, validate, and store one forecast vector.

    Pipeline:
      1. Check flag gates
      2. Build features (forecast_feature_builder)
      3. Score (forecast_probability_engine)
      4. Validate distribution
      5. Build explanation (forecast_explainability_service)
      6. Validate explanation
      7. Upsert forecast_vector (forecast_repo)
      8. Refresh forecast_evidence rows

    Returns a result dict:
      {status, entity_type, entity_key, forecast_type, horizon_days,
       vector_id, evidence_count}

    status ∈ {
      "stored"               — pipeline succeeded; vector and evidence written
      "blocked_flags"        — flag gates prevent execution
      "blocked_distribution" — probability distribution failed validation
      "blocked_explanation"  — explanation failed validation
      "no_features"          — feature builder returned None (entity not found)
      "error"                — unexpected exception; nothing written
    }

    Returns None when session is None.
    """
    if session is None:
        return None

    if not _pipeline_approved(_build_override):
        return _result("blocked_flags", target_type, target_id, forecast_type, horizon_days)

    try:
        # Step 1: Build features
        features = await _build_features(session, target_type, target_id)
        if features is None:
            return _result("no_features", target_type, target_id, forecast_type, horizon_days)

        # Step 2: Score
        probability_output = _score_features(features, target_type, forecast_type, horizon_days)

        # Step 3: Validate distribution
        from app.services.forecast_probability_engine import validate_forecast_distribution
        if not validate_forecast_distribution(probability_output):
            return _result(
                "blocked_distribution", target_type, target_id, forecast_type, horizon_days
            )

        # Step 4: Build explanation
        from app.services.forecast_explainability_service import (
            build_forecast_explanation,
            validate_forecast_explanation,
        )
        explanation = build_forecast_explanation(features, probability_output)

        # Step 5: Validate explanation (gate before any write)
        if not validate_forecast_explanation(explanation):
            return _result(
                "blocked_explanation", target_type, target_id, forecast_type, horizon_days
            )

        # Step 6: Upsert forecast_vector
        from app.services.forecast_constants import HORIZON_LABELS
        from app.db.repositories.forecast_repo import (
            upsert_forecast_vector,
            delete_evidence_for_forecast,
            add_forecast_evidence,
        )

        horizon_label = HORIZON_LABELS.get(horizon_days, "near_term")
        why_str = "\n".join(explanation.get("why", [])) or "No explanation available."

        vector = await upsert_forecast_vector(
            session,
            entity_type=target_type,
            entity_key=target_id,
            horizon=horizon_label,
            horizon_days=horizon_days,
            forecast_type=forecast_type,
            p_positive=probability_output["p_positive"],
            p_negative=probability_output["p_negative"],
            p_neutral=probability_output["p_neutral"],
            confidence_band_low=probability_output["confidence_low"],
            confidence_band_high=probability_output["confidence_high"],
            why=why_str,
            invalidators=explanation.get("invalidators", []),
            analog_basis=explanation.get("analog_basis", []),
            similarity_basis=explanation.get("similarity_basis", []),
            evidence_summary=explanation.get("evidence", []),
            source_versions=features.get("source_versions", {}),
        )

        if vector is None:
            return _result("error", target_type, target_id, forecast_type, horizon_days)

        vector_id = vector.id

        # Step 7: Refresh evidence rows — delete old, insert new
        await delete_evidence_for_forecast(session, forecast_id=vector_id)

        evidence_rows = explanation.get("evidence", [])
        evidence_count = 0
        for ev in evidence_rows:
            row = await add_forecast_evidence(
                session,
                forecast_id=vector_id,
                source_type=str(ev.get("source_type", "unknown")),
                source_id=str(ev.get("source_id", "")),
                direction=str(ev.get("direction", "neutral")),
                contribution=float(ev.get("contribution", 0.0)),
                weight=float(ev.get("weight", 0.0)),
                description=str(ev.get("description", "")),
                entity_type=target_type,
                entity_key=target_id,
            )
            if row is not None:
                evidence_count += 1

        return {
            "status": "stored",
            "entity_type": target_type,
            "entity_key": target_id,
            "forecast_type": forecast_type,
            "horizon_days": horizon_days,
            "vector_id": vector_id,
            "evidence_count": evidence_count,
        }

    except Exception as exc:
        logger.debug(
            "[forecast_invalidation] rebuild_forecast_for_target error: %r", exc
        )
        return _result("error", target_type, target_id, forecast_type, horizon_days)


def _result(
    status: str,
    entity_type: str,
    entity_key: str,
    forecast_type: str,
    horizon_days: int,
) -> Dict:
    return {
        "status": status,
        "entity_type": entity_type,
        "entity_key": entity_key,
        "forecast_type": forecast_type,
        "horizon_days": horizon_days,
        "vector_id": None,
        "evidence_count": 0,
    }


# ---------------------------------------------------------------------------
# Ticker-level rebuild
# ---------------------------------------------------------------------------

async def rebuild_forecasts_for_ticker(
    session,
    ticker: str,
    *,
    forecast_types: Optional[List[str]] = None,
    horizons: Optional[List[int]] = None,
    _build_override: Optional[bool] = None,
) -> List[Dict]:
    """Rebuild all (or a subset of) forecast vectors for a company ticker.

    Iterates over the Cartesian product of forecast_types × horizons.
    Defaults: all 6 types × all 3 horizons = 18 forecasts.

    Returns a list of result dicts (one per forecast attempted).
    Returns [] when session is None.
    """
    if session is None:
        return []

    from app.services.forecast_constants import ALLOWED_FORECAST_TYPES, ALLOWED_HORIZONS

    types_to_run = list(forecast_types or sorted(ALLOWED_FORECAST_TYPES))
    horizons_to_run = list(horizons or sorted(ALLOWED_HORIZONS))

    results: List[Dict] = []
    for ft in types_to_run:
        for h in horizons_to_run:
            result = await rebuild_forecast_for_target(
                session, "company", ticker, ft, h,
                _build_override=_build_override,
            )
            if result is not None:
                results.append(result)
    return results


# ---------------------------------------------------------------------------
# Batch rebuild
# ---------------------------------------------------------------------------

async def rebuild_forecast_batch(
    session,
    *,
    limit: Optional[int] = None,
    _build_override: Optional[bool] = None,
) -> Dict:
    """Find expired forecast vectors and rebuild each one.

    Only rebuilds vectors whose entity_type appears in
    forecast_targets_enabled (or all types when _build_override is set).

    Returns a summary dict:
      {total_stale, stored, blocked_distribution, blocked_explanation,
       blocked_flags, no_features, errors}

    Returns {} when session is None.
    """
    if session is None:
        return {}

    batch_limit = limit if limit is not None else 200
    stale = await find_stale_forecasts(session, limit=batch_limit)

    summary: Dict[str, int] = {
        "total_stale": len(stale),
        "stored": 0,
        "blocked_distribution": 0,
        "blocked_explanation": 0,
        "blocked_flags": 0,
        "no_features": 0,
        "errors": 0,
    }

    for vector in stale:
        entity_type = getattr(vector, "entity_type", "")
        entity_key = getattr(vector, "entity_key", "")
        forecast_type = getattr(vector, "forecast_type", "")
        horizon_days = getattr(vector, "horizon_days", 30)

        if not _batch_target_approved(entity_type, _build_override):
            summary["blocked_flags"] += 1
            continue

        result = await rebuild_forecast_for_target(
            session,
            entity_type,
            entity_key,
            forecast_type,
            horizon_days,
            _build_override=_build_override,
        )
        if result is None:
            summary["errors"] += 1
        else:
            status = result.get("status", "error")
            if status in summary:
                summary[status] += 1
            else:
                summary["errors"] += 1

    return summary
