"""
Forecast repository — Phase 12 · Slice 1.

CRUD for forecast_vector, forecast_evidence, and forecast_calibration_log.
All functions accept an AsyncSession as the first positional argument.
Passing None is safe: every function returns an empty/falsy/None value
rather than raising.  This mirrors the null-session contract used throughout
the loop, portfolio, account, billing, and similarity repos.

No probability computation, no scoring, no delivery logic.  Pure DB access.
The forecast flags are not consulted here; flag checks belong in the service
layer (Phase 12 Slices 2+).

Safety invariants (Phase 12 spec §0 / SP-4):
  - This repo never writes to any source table (dossier, analogs, thesis,
    similarity, portfolio, delivery, notifications).
  - forecast_calibration_log has NO update path in this repo. Every call
    that needs to record an outcome uses add_calibration_log() which only
    inserts. This immutability is verified by the validation script via AST
    inspection of this module.
  - Rows returned here are cache/analytics rows only and must not be passed
    to any conviction-scoring or recommendation path.
"""

from __future__ import annotations

import logging
import uuid as _uuid_mod
from datetime import datetime, timedelta, timezone
from typing import List, Optional

logger = logging.getLogger(__name__)

# Default TTL values per horizon (hours). Used by upsert_forecast_vector
# when the caller does not supply an explicit expires_at.
DEFAULT_TTL_BY_HORIZON: dict = {
    "near_term":   24,
    "medium_term": 72,
    "long_term":   168,
}
DEFAULT_TTL_HOURS: int = 24  # fallback for unknown horizon labels


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _new_id() -> str:
    return str(_uuid_mod.uuid4())


def _ttl_hours(horizon: str) -> int:
    return DEFAULT_TTL_BY_HORIZON.get(horizon, DEFAULT_TTL_HOURS)


# ---------------------------------------------------------------------------
# § FORECAST VECTORS
# ---------------------------------------------------------------------------

async def upsert_forecast_vector(
    session,
    *,
    entity_type: str,
    entity_key: str,
    horizon: str,
    horizon_days: int,
    forecast_type: str,
    p_positive: float,
    p_negative: float,
    p_neutral: float,
    confidence_band_low: float,
    confidence_band_high: float,
    why: str,
    invalidators: list,
    analog_basis: list,
    similarity_basis: list,
    evidence_summary: list,
    source_versions: dict,
    forecast_schema: int = 1,
    user_id: Optional[str] = None,
    ttl_hours: Optional[int] = None,
    vector_id: Optional[str] = None,
) -> Optional[object]:
    """Insert or update a ForecastVector row.

    Upsert is keyed on (entity_type, entity_key, horizon, forecast_type, user_id).
    Returns the ORM row, or None when session is None.

    The caller (Slice 12.5 builder) is responsible for ensuring:
      - p_positive + p_negative + p_neutral ≈ 1.0
      - why is non-empty
      - invalidators is non-empty
      - at least one of analog_basis / similarity_basis is non-empty
    This repo stores whatever the caller sends.
    """
    if session is None:
        return None
    try:
        from app.db.models import ForecastVector
        from sqlalchemy import select

        stmt = select(ForecastVector).where(
            ForecastVector.entity_type   == entity_type,
            ForecastVector.entity_key    == entity_key,
            ForecastVector.horizon       == horizon,
            ForecastVector.forecast_type == forecast_type,
            ForecastVector.user_id       == user_id,
        )
        result = await session.execute(stmt)
        row = result.scalar_one_or_none()

        now     = _now()
        ttl     = ttl_hours if ttl_hours is not None else _ttl_hours(horizon)
        expires = now + timedelta(hours=ttl)

        if row is None:
            row = ForecastVector(
                id                   = vector_id or _new_id(),
                entity_type          = entity_type,
                entity_key           = entity_key,
                horizon              = horizon,
                horizon_days         = horizon_days,
                forecast_type        = forecast_type,
                p_positive           = p_positive,
                p_negative           = p_negative,
                p_neutral            = p_neutral,
                confidence_band_low  = confidence_band_low,
                confidence_band_high = confidence_band_high,
                why                  = why,
                invalidators         = invalidators,
                analog_basis         = analog_basis,
                similarity_basis     = similarity_basis,
                evidence_summary     = evidence_summary,
                source_versions      = source_versions,
                forecast_schema      = forecast_schema,
                user_id              = user_id,
                built_at             = now,
                expires_at           = expires,
            )
            session.add(row)
        else:
            row.horizon_days         = horizon_days
            row.p_positive           = p_positive
            row.p_negative           = p_negative
            row.p_neutral            = p_neutral
            row.confidence_band_low  = confidence_band_low
            row.confidence_band_high = confidence_band_high
            row.why                  = why
            row.invalidators         = invalidators
            row.analog_basis         = analog_basis
            row.similarity_basis     = similarity_basis
            row.evidence_summary     = evidence_summary
            row.source_versions      = source_versions
            row.forecast_schema      = forecast_schema
            row.built_at             = now
            row.expires_at           = expires

        await session.flush()
        return row
    except Exception as exc:
        logger.debug("[forecast_repo] upsert_forecast_vector failed: %r", exc)
        return None


async def get_forecast_vector(
    session,
    *,
    entity_type: str,
    entity_key: str,
    horizon: str,
    forecast_type: str,
    user_id: Optional[str] = None,
) -> Optional[object]:
    """Return the ForecastVector for the exact (entity_type, entity_key, horizon,
    forecast_type, user_id) tuple.

    Returns None when session is None or no row found.
    """
    if session is None:
        return None
    try:
        from app.db.models import ForecastVector
        from sqlalchemy import select

        stmt = select(ForecastVector).where(
            ForecastVector.entity_type   == entity_type,
            ForecastVector.entity_key    == entity_key,
            ForecastVector.horizon       == horizon,
            ForecastVector.forecast_type == forecast_type,
            ForecastVector.user_id       == user_id,
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()
    except Exception as exc:
        logger.debug("[forecast_repo] get_forecast_vector failed: %r", exc)
        return None


async def list_forecast_vectors(
    session,
    *,
    entity_type: Optional[str] = None,
    entity_key: Optional[str] = None,
    horizon: Optional[str] = None,
    forecast_type: Optional[str] = None,
    user_id: Optional[str] = None,
    forecast_schema: Optional[int] = None,
    exclude_expired: bool = False,
    limit: int = 200,
) -> List[object]:
    """Return ForecastVector rows matching the given filters.

    All filters are optional.  Returns [] when session is None or on error.
    Ordered by built_at descending.
    """
    if session is None:
        return []
    try:
        from app.db.models import ForecastVector
        from sqlalchemy import select

        stmt = select(ForecastVector)
        if entity_type is not None:
            stmt = stmt.where(ForecastVector.entity_type == entity_type)
        if entity_key is not None:
            stmt = stmt.where(ForecastVector.entity_key == entity_key)
        if horizon is not None:
            stmt = stmt.where(ForecastVector.horizon == horizon)
        if forecast_type is not None:
            stmt = stmt.where(ForecastVector.forecast_type == forecast_type)
        if user_id is not None:
            stmt = stmt.where(ForecastVector.user_id == user_id)
        if forecast_schema is not None:
            stmt = stmt.where(ForecastVector.forecast_schema == forecast_schema)
        if exclude_expired:
            stmt = stmt.where(ForecastVector.expires_at > _now())
        stmt = stmt.order_by(ForecastVector.built_at.desc()).limit(limit)

        result = await session.execute(stmt)
        return list(result.scalars().all())
    except Exception as exc:
        logger.debug("[forecast_repo] list_forecast_vectors failed: %r", exc)
        return []


async def delete_forecast_vector(
    session,
    *,
    entity_type: str,
    entity_key: str,
    horizon: str,
    forecast_type: str,
    user_id: Optional[str] = None,
) -> bool:
    """Delete a ForecastVector row.  Returns True if a row was deleted."""
    if session is None:
        return False
    try:
        from app.db.models import ForecastVector
        from sqlalchemy import select

        stmt = select(ForecastVector).where(
            ForecastVector.entity_type   == entity_type,
            ForecastVector.entity_key    == entity_key,
            ForecastVector.horizon       == horizon,
            ForecastVector.forecast_type == forecast_type,
            ForecastVector.user_id       == user_id,
        )
        result = await session.execute(stmt)
        row = result.scalar_one_or_none()
        if row is None:
            return False
        await session.delete(row)
        await session.flush()
        return True
    except Exception as exc:
        logger.debug("[forecast_repo] delete_forecast_vector failed: %r", exc)
        return False


async def delete_expired_vectors(
    session,
    *,
    batch_limit: int = 500,
) -> int:
    """Delete ForecastVector rows whose expires_at <= now().

    Returns the number of rows deleted.  Returns 0 when session is None.
    Called by the invalidation service TTL sweep (Phase 12 Slice 5).
    """
    if session is None:
        return 0
    try:
        from app.db.models import ForecastVector
        from sqlalchemy import select, delete

        subq = (
            select(ForecastVector.id)
            .where(ForecastVector.expires_at <= _now())
            .limit(batch_limit)
            .scalar_subquery()
        )
        stmt = delete(ForecastVector).where(ForecastVector.id.in_(subq))
        result = await session.execute(stmt)
        await session.flush()
        return result.rowcount or 0
    except Exception as exc:
        logger.debug("[forecast_repo] delete_expired_vectors failed: %r", exc)
        return 0


async def count_forecast_vectors(
    session,
    *,
    entity_type: Optional[str] = None,
    user_id: Optional[str] = None,
) -> int:
    """Return the count of ForecastVector rows matching optional filters.

    Used by the observability service (Phase 12 Slice 9).
    Returns 0 when session is None or on error.
    """
    if session is None:
        return 0
    try:
        from app.db.models import ForecastVector
        from sqlalchemy import select, func

        stmt = select(func.count()).select_from(ForecastVector)
        if entity_type is not None:
            stmt = stmt.where(ForecastVector.entity_type == entity_type)
        if user_id is not None:
            stmt = stmt.where(ForecastVector.user_id == user_id)
        result = await session.execute(stmt)
        return int(result.scalar_one() or 0)
    except Exception as exc:
        logger.debug("[forecast_repo] count_forecast_vectors failed: %r", exc)
        return 0


# ---------------------------------------------------------------------------
# § FORECAST EVIDENCE
# ---------------------------------------------------------------------------

async def add_forecast_evidence(
    session,
    *,
    forecast_id: str,
    source_type: str,
    source_id: str,
    direction: str,
    contribution: float,
    weight: float,
    description: str,
    entity_type: str = "",
    entity_key: str = "",
    user_id: Optional[str] = None,
    evidence_id: Optional[str] = None,
) -> Optional[object]:
    """Insert one ForecastEvidence row.

    No unique constraint — one forecast_vector may have many evidence rows.
    Returns the ORM row, or None when session is None.
    """
    if session is None:
        return None
    try:
        from app.db.models import ForecastEvidence

        row = ForecastEvidence(
            id           = evidence_id or _new_id(),
            forecast_id  = forecast_id,
            source_type  = source_type,
            source_id    = source_id,
            direction    = direction,
            contribution = contribution,
            weight       = weight,
            description  = description,
            entity_type  = entity_type,
            entity_key   = entity_key,
            user_id      = user_id,
            built_at     = _now(),
        )
        session.add(row)
        await session.flush()
        return row
    except Exception as exc:
        logger.debug("[forecast_repo] add_forecast_evidence failed: %r", exc)
        return None


async def list_forecast_evidence(
    session,
    *,
    forecast_id: Optional[str] = None,
    entity_type: Optional[str] = None,
    entity_key: Optional[str] = None,
    source_type: Optional[str] = None,
    user_id: Optional[str] = None,
    limit: int = 200,
) -> List[object]:
    """Return ForecastEvidence rows matching the given filters.

    All filters are optional.  Returns [] when session is None or on error.
    Ordered by |contribution| descending (strongest evidence first).
    """
    if session is None:
        return []
    try:
        from app.db.models import ForecastEvidence
        from sqlalchemy import select, func

        stmt = select(ForecastEvidence)
        if forecast_id is not None:
            stmt = stmt.where(ForecastEvidence.forecast_id == forecast_id)
        if entity_type is not None:
            stmt = stmt.where(ForecastEvidence.entity_type == entity_type)
        if entity_key is not None:
            stmt = stmt.where(ForecastEvidence.entity_key == entity_key)
        if source_type is not None:
            stmt = stmt.where(ForecastEvidence.source_type == source_type)
        if user_id is not None:
            stmt = stmt.where(ForecastEvidence.user_id == user_id)
        # Order by absolute contribution magnitude descending
        stmt = stmt.order_by(func.abs(ForecastEvidence.contribution).desc()).limit(limit)

        result = await session.execute(stmt)
        return list(result.scalars().all())
    except Exception as exc:
        logger.debug("[forecast_repo] list_forecast_evidence failed: %r", exc)
        return []


async def delete_evidence_for_forecast(
    session,
    *,
    forecast_id: str,
) -> int:
    """Delete all ForecastEvidence rows for a given forecast_id.

    Called by the invalidation service before rebuilding a forecast.
    Returns row count; 0 on error/no-op.
    """
    if session is None:
        return 0
    try:
        from app.db.models import ForecastEvidence
        from sqlalchemy import delete

        stmt = delete(ForecastEvidence).where(ForecastEvidence.forecast_id == forecast_id)
        result = await session.execute(stmt)
        await session.flush()
        return result.rowcount or 0
    except Exception as exc:
        logger.debug("[forecast_repo] delete_evidence_for_forecast failed: %r", exc)
        return 0


async def count_forecast_evidence(
    session,
    *,
    forecast_id: Optional[str] = None,
) -> int:
    """Return the count of ForecastEvidence rows for a forecast (or total).

    Used by the observability service (Phase 12 Slice 9).
    Returns 0 when session is None or on error.
    """
    if session is None:
        return 0
    try:
        from app.db.models import ForecastEvidence
        from sqlalchemy import select, func

        stmt = select(func.count()).select_from(ForecastEvidence)
        if forecast_id is not None:
            stmt = stmt.where(ForecastEvidence.forecast_id == forecast_id)
        result = await session.execute(stmt)
        return int(result.scalar_one() or 0)
    except Exception as exc:
        logger.debug("[forecast_repo] count_forecast_evidence failed: %r", exc)
        return 0


# ---------------------------------------------------------------------------
# § FORECAST CALIBRATION LOG (append-only — NO UPDATE PATH)
# ---------------------------------------------------------------------------

async def add_calibration_log(
    session,
    *,
    forecast_id: str,
    entity_type: str,
    entity_key: str,
    horizon: str,
    forecast_type: str,
    p_positive_at_forecast: float,
    p_negative_at_forecast: float,
    p_neutral_at_forecast: float,
    actual_outcome: str,
    brier_score: Optional[float],
    evaluation_source: str,
    evaluated_at: Optional[datetime] = None,
    evaluator_notes: Optional[str] = None,
    user_id: Optional[str] = None,
    log_id: Optional[str] = None,
) -> Optional[object]:
    """Insert one ForecastCalibrationLog row.

    THIS FUNCTION ONLY INSERTS — it never updates an existing row.
    The immutability invariant is enforced here (no SELECT-then-update pattern)
    and verified by AST inspection in the validation script.

    Returns the ORM row, or None when session is None.
    """
    if session is None:
        return None
    try:
        from app.db.models import ForecastCalibrationLog

        now = _now()
        row = ForecastCalibrationLog(
            id                     = log_id or _new_id(),
            forecast_id            = forecast_id,
            entity_type            = entity_type,
            entity_key             = entity_key,
            horizon                = horizon,
            forecast_type          = forecast_type,
            p_positive_at_forecast = p_positive_at_forecast,
            p_negative_at_forecast = p_negative_at_forecast,
            p_neutral_at_forecast  = p_neutral_at_forecast,
            actual_outcome         = actual_outcome,
            brier_score            = brier_score,
            evaluation_source      = evaluation_source,
            evaluated_at           = evaluated_at or now,
            evaluator_notes        = evaluator_notes,
            user_id                = user_id,
            created_at             = now,
        )
        session.add(row)
        await session.flush()
        return row
    except Exception as exc:
        logger.debug("[forecast_repo] add_calibration_log failed: %r", exc)
        return None


async def list_calibration_logs(
    session,
    *,
    forecast_id: Optional[str] = None,
    entity_type: Optional[str] = None,
    entity_key: Optional[str] = None,
    forecast_type: Optional[str] = None,
    horizon: Optional[str] = None,
    user_id: Optional[str] = None,
    evaluated_after: Optional[datetime] = None,
    limit: int = 500,
) -> List[object]:
    """Return ForecastCalibrationLog rows matching the given filters.

    All filters are optional.  Returns [] when session is None or on error.
    Ordered by evaluated_at descending.
    """
    if session is None:
        return []
    try:
        from app.db.models import ForecastCalibrationLog
        from sqlalchemy import select

        stmt = select(ForecastCalibrationLog)
        if forecast_id is not None:
            stmt = stmt.where(ForecastCalibrationLog.forecast_id == forecast_id)
        if entity_type is not None:
            stmt = stmt.where(ForecastCalibrationLog.entity_type == entity_type)
        if entity_key is not None:
            stmt = stmt.where(ForecastCalibrationLog.entity_key == entity_key)
        if forecast_type is not None:
            stmt = stmt.where(ForecastCalibrationLog.forecast_type == forecast_type)
        if horizon is not None:
            stmt = stmt.where(ForecastCalibrationLog.horizon == horizon)
        if user_id is not None:
            stmt = stmt.where(ForecastCalibrationLog.user_id == user_id)
        if evaluated_after is not None:
            stmt = stmt.where(ForecastCalibrationLog.evaluated_at >= evaluated_after)
        stmt = stmt.order_by(ForecastCalibrationLog.evaluated_at.desc()).limit(limit)

        result = await session.execute(stmt)
        return list(result.scalars().all())
    except Exception as exc:
        logger.debug("[forecast_repo] list_calibration_logs failed: %r", exc)
        return []


async def count_calibration_logs(
    session,
    *,
    entity_type: Optional[str] = None,
    forecast_type: Optional[str] = None,
    evaluated_after: Optional[datetime] = None,
) -> int:
    """Return the count of ForecastCalibrationLog rows matching optional filters.

    Used by the calibration and observability services (Phase 12 Slices 8–9).
    Returns 0 when session is None or on error.
    """
    if session is None:
        return 0
    try:
        from app.db.models import ForecastCalibrationLog
        from sqlalchemy import select, func

        stmt = select(func.count()).select_from(ForecastCalibrationLog)
        if entity_type is not None:
            stmt = stmt.where(ForecastCalibrationLog.entity_type == entity_type)
        if forecast_type is not None:
            stmt = stmt.where(ForecastCalibrationLog.forecast_type == forecast_type)
        if evaluated_after is not None:
            stmt = stmt.where(ForecastCalibrationLog.evaluated_at >= evaluated_after)
        result = await session.execute(stmt)
        return int(result.scalar_one() or 0)
    except Exception as exc:
        logger.debug("[forecast_repo] count_calibration_logs failed: %r", exc)
        return 0
