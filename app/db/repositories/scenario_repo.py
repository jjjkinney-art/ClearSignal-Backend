"""
Scenario repository — Phase 14 · Slice 1.

CRUD for scenario_snapshot, scenario_evidence, and scenario_run_log.
All functions accept an AsyncSession as the first positional argument.
Passing None is safe: every function returns an empty/falsy/None value
rather than raising. This mirrors the null-session contract used throughout
the loop, portfolio, account, billing, similarity, forecast, and decision repos.

No seed building, no evaluation, no explainability, no delivery logic.
Pure DB access. The scenario flags are not consulted here; flag checks belong
in the service layer (Phase 14 Slices 2+).

Safety invariants (Phase 14 spec §0 / SP-6):
  - This repo never writes to any source table (dossier, analogs, thesis,
    similarity, forecast, decision, portfolio, delivery, notifications). The
    Scenario Engine is a pure sink.
  - scenario_run_log has NO update or delete path in this repo. Every call
    that records a run or outcome uses add_run_log() which only INSERTs. This
    immutability is verified by the validation script via AST inspection of
    this module.
  - There is no buy/sell/hold, position_size, target_price, trade, or execution
    field on any table this repo touches. Rows here describe conditional analyses
    and must not be passed to any conviction/recommendation/order path.
"""

from __future__ import annotations

import logging
import uuid as _uuid_mod
from datetime import datetime, timedelta, timezone
from typing import List, Optional

logger = logging.getLogger(__name__)

# Default TTL (hours) used by upsert_scenario_snapshot when the caller does
# not supply an explicit expires_at.
DEFAULT_TTL_HOURS: int = 72


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _new_id() -> str:
    return str(_uuid_mod.uuid4())


# ---------------------------------------------------------------------------
# § SCENARIO SNAPSHOTS
# ---------------------------------------------------------------------------

async def upsert_scenario_snapshot(
    session,
    *,
    scenario_type: str,
    entity_type: str,
    entity_key: str,
    scenario_key: str = "",
    condition: str = "",
    transmission_path: Optional[list] = None,
    scenario_impact: str = "ambiguous",
    plausibility_band: str = "plausible",
    confidence_score: float = 0.0,
    uncertainty_score: float = 0.0,
    affected_entities: Optional[list] = None,
    affected_forecasts: Optional[list] = None,
    affected_decisions: Optional[list] = None,
    what_changed: str = "",
    why_it_matters: str = "",
    evidence_summary: Optional[list] = None,
    invalidators: Optional[list] = None,
    source_versions: Optional[dict] = None,
    scenario_schema: int = 1,
    user_id: Optional[str] = None,
    ttl_hours: Optional[int] = None,
    snapshot_id: Optional[str] = None,
) -> Optional[object]:
    """Insert or update a ScenarioSnapshot row.

    Upsert is keyed on
    (scenario_type, entity_type, entity_key, scenario_key, user_id).
    Returns the ORM row, or None when session is None.

    The caller (Slice 14.5 assembly orchestration) is responsible for ensuring
    the explainability invariants hold (non-empty what_changed / why_it_matters
    / transmission_path / invalidators; ≥1 evidence item). This repo performs
    no validation — it is pure persistence.
    """
    if session is None:
        return None
    try:
        from app.db.models import ScenarioSnapshot
        from sqlalchemy import select

        stmt = select(ScenarioSnapshot).where(
            ScenarioSnapshot.scenario_type == scenario_type,
            ScenarioSnapshot.entity_type   == entity_type,
            ScenarioSnapshot.entity_key    == entity_key,
            ScenarioSnapshot.scenario_key  == scenario_key,
            ScenarioSnapshot.user_id       == user_id,
        )
        existing = (await session.execute(stmt)).scalar_one_or_none()

        now = _now()
        expires = now + timedelta(hours=ttl_hours if ttl_hours is not None else DEFAULT_TTL_HOURS)

        if existing is None:
            row = ScenarioSnapshot(
                id                 = snapshot_id or _new_id(),
                scenario_type      = scenario_type,
                entity_type        = entity_type,
                entity_key         = entity_key,
                scenario_key       = scenario_key,
                condition          = condition,
                transmission_path  = transmission_path if transmission_path is not None else [],
                scenario_impact    = scenario_impact,
                plausibility_band  = plausibility_band,
                confidence_score   = confidence_score,
                uncertainty_score  = uncertainty_score,
                affected_entities  = affected_entities  if affected_entities  is not None else [],
                affected_forecasts = affected_forecasts if affected_forecasts is not None else [],
                affected_decisions = affected_decisions if affected_decisions is not None else [],
                what_changed       = what_changed,
                why_it_matters     = why_it_matters,
                evidence_summary   = evidence_summary   if evidence_summary   is not None else [],
                invalidators       = invalidators        if invalidators        is not None else [],
                source_versions    = source_versions     if source_versions     is not None else {},
                scenario_schema    = scenario_schema,
                user_id            = user_id,
                built_at           = now,
                expires_at         = expires,
            )
            session.add(row)
            await session.flush()
            return row

        # Update in place — keyed row already exists
        existing.condition          = condition
        existing.transmission_path  = transmission_path  if transmission_path  is not None else []
        existing.scenario_impact    = scenario_impact
        existing.plausibility_band  = plausibility_band
        existing.confidence_score   = confidence_score
        existing.uncertainty_score  = uncertainty_score
        existing.affected_entities  = affected_entities  if affected_entities  is not None else []
        existing.affected_forecasts = affected_forecasts if affected_forecasts is not None else []
        existing.affected_decisions = affected_decisions if affected_decisions is not None else []
        existing.what_changed       = what_changed
        existing.why_it_matters     = why_it_matters
        existing.evidence_summary   = evidence_summary   if evidence_summary   is not None else []
        existing.invalidators       = invalidators        if invalidators        is not None else []
        existing.source_versions    = source_versions     if source_versions     is not None else {}
        existing.scenario_schema    = scenario_schema
        existing.built_at           = now
        existing.expires_at         = expires
        await session.flush()
        return existing
    except Exception as exc:
        logger.debug("[scenario_repo] upsert_scenario_snapshot failed: %r", exc)
        return None


async def get_scenario_snapshot(
    session,
    *,
    scenario_type: str,
    entity_type: str,
    entity_key: str,
    scenario_key: str = "",
    user_id: Optional[str] = None,
) -> Optional[object]:
    """Return one ScenarioSnapshot row by its unique key, or None."""
    if session is None:
        return None
    try:
        from app.db.models import ScenarioSnapshot
        from sqlalchemy import select

        stmt = select(ScenarioSnapshot).where(
            ScenarioSnapshot.scenario_type == scenario_type,
            ScenarioSnapshot.entity_type   == entity_type,
            ScenarioSnapshot.entity_key    == entity_key,
            ScenarioSnapshot.scenario_key  == scenario_key,
            ScenarioSnapshot.user_id       == user_id,
        )
        return (await session.execute(stmt)).scalar_one_or_none()
    except Exception as exc:
        logger.debug("[scenario_repo] get_scenario_snapshot failed: %r", exc)
        return None


async def list_scenario_snapshots(
    session,
    *,
    scenario_type: Optional[str] = None,
    entity_type: Optional[str] = None,
    entity_key: Optional[str] = None,
    plausibility_band: Optional[str] = None,
    user_id: Optional[str] = None,
    user_id_is_null: Optional[bool] = None,
    scenario_schema: Optional[int] = None,
    exclude_expired: bool = False,
    limit: int = 200,
) -> List[object]:
    """Return ScenarioSnapshot rows matching the given filters.

    All filters are optional. Returns [] when session is None or on error.
    Ordered by built_at descending.

    `user_id` filters to an exact user scope. `user_id_is_null=True` filters to
    the global tier (user_id IS NULL); `user_id_is_null=False` filters to the
    user tier (user_id IS NOT NULL). These are mutually exclusive with passing
    an explicit `user_id`.
    """
    if session is None:
        return []
    try:
        from app.db.models import ScenarioSnapshot
        from sqlalchemy import select

        stmt = select(ScenarioSnapshot)
        if scenario_type is not None:
            stmt = stmt.where(ScenarioSnapshot.scenario_type == scenario_type)
        if entity_type is not None:
            stmt = stmt.where(ScenarioSnapshot.entity_type == entity_type)
        if entity_key is not None:
            stmt = stmt.where(ScenarioSnapshot.entity_key == entity_key)
        if plausibility_band is not None:
            stmt = stmt.where(ScenarioSnapshot.plausibility_band == plausibility_band)
        if user_id is not None:
            stmt = stmt.where(ScenarioSnapshot.user_id == user_id)
        if user_id_is_null is True:
            stmt = stmt.where(ScenarioSnapshot.user_id.is_(None))
        elif user_id_is_null is False:
            stmt = stmt.where(ScenarioSnapshot.user_id.is_not(None))
        if scenario_schema is not None:
            stmt = stmt.where(ScenarioSnapshot.scenario_schema == scenario_schema)
        if exclude_expired:
            stmt = stmt.where(ScenarioSnapshot.expires_at > _now())
        stmt = stmt.order_by(ScenarioSnapshot.built_at.desc()).limit(limit)

        result = await session.execute(stmt)
        return list(result.scalars().all())
    except Exception as exc:
        logger.debug("[scenario_repo] list_scenario_snapshots failed: %r", exc)
        return []


async def delete_scenario_snapshot(
    session,
    *,
    scenario_type: str,
    entity_type: str,
    entity_key: str,
    scenario_key: str = "",
    user_id: Optional[str] = None,
) -> bool:
    """Delete a ScenarioSnapshot row. Returns True if a row was deleted."""
    if session is None:
        return False
    try:
        from app.db.models import ScenarioSnapshot
        from sqlalchemy import select

        stmt = select(ScenarioSnapshot).where(
            ScenarioSnapshot.scenario_type == scenario_type,
            ScenarioSnapshot.entity_type   == entity_type,
            ScenarioSnapshot.entity_key    == entity_key,
            ScenarioSnapshot.scenario_key  == scenario_key,
            ScenarioSnapshot.user_id       == user_id,
        )
        row = (await session.execute(stmt)).scalar_one_or_none()
        if row is None:
            return False
        await session.delete(row)
        await session.flush()
        return True
    except Exception as exc:
        logger.debug("[scenario_repo] delete_scenario_snapshot failed: %r", exc)
        return False


async def delete_expired_snapshots(
    session,
    *,
    batch_limit: int = 500,
) -> int:
    """Delete ScenarioSnapshot rows whose expires_at <= now().

    Returns the number of rows deleted. Returns 0 when session is None.
    Called by the assembly service TTL sweep (Phase 14 Slice 5).
    """
    if session is None:
        return 0
    try:
        from app.db.models import ScenarioSnapshot
        from sqlalchemy import select, delete

        subq = (
            select(ScenarioSnapshot.id)
            .where(ScenarioSnapshot.expires_at <= _now())
            .limit(batch_limit)
            .scalar_subquery()
        )
        stmt = delete(ScenarioSnapshot).where(ScenarioSnapshot.id.in_(subq))
        result = await session.execute(stmt)
        await session.flush()
        return result.rowcount or 0
    except Exception as exc:
        logger.debug("[scenario_repo] delete_expired_snapshots failed: %r", exc)
        return 0


async def count_scenario_snapshots(
    session,
    *,
    scenario_type: Optional[str] = None,
    entity_type: Optional[str] = None,
    user_id_is_null: Optional[bool] = None,
) -> int:
    """Return the count of ScenarioSnapshot rows matching optional filters.

    Used by the observability service (Phase 14 Slice 10).
    Returns 0 when session is None or on error.
    """
    if session is None:
        return 0
    try:
        from app.db.models import ScenarioSnapshot
        from sqlalchemy import select, func

        stmt = select(func.count()).select_from(ScenarioSnapshot)
        if scenario_type is not None:
            stmt = stmt.where(ScenarioSnapshot.scenario_type == scenario_type)
        if entity_type is not None:
            stmt = stmt.where(ScenarioSnapshot.entity_type == entity_type)
        if user_id_is_null is True:
            stmt = stmt.where(ScenarioSnapshot.user_id.is_(None))
        elif user_id_is_null is False:
            stmt = stmt.where(ScenarioSnapshot.user_id.is_not(None))
        result = await session.execute(stmt)
        return int(result.scalar_one() or 0)
    except Exception as exc:
        logger.debug("[scenario_repo] count_scenario_snapshots failed: %r", exc)
        return 0


# ---------------------------------------------------------------------------
# § SCENARIO EVIDENCE
# ---------------------------------------------------------------------------

async def add_scenario_evidence(
    session,
    *,
    scenario_id: str,
    source_phase: str,
    source_ref: str,
    captured_value: Optional[dict] = None,
    entity_type: str = "",
    entity_key: str = "",
    user_id: Optional[str] = None,
    evidence_id: Optional[str] = None,
) -> Optional[object]:
    """Insert one ScenarioEvidence row. Returns the ORM row, or None."""
    if session is None:
        return None
    try:
        from app.db.models import ScenarioEvidence

        row = ScenarioEvidence(
            id             = evidence_id or _new_id(),
            scenario_id    = scenario_id,
            source_phase   = source_phase,
            source_ref     = source_ref,
            captured_value = captured_value if captured_value is not None else {},
            entity_type    = entity_type,
            entity_key     = entity_key,
            user_id        = user_id,
            captured_at    = _now(),
        )
        session.add(row)
        await session.flush()
        return row
    except Exception as exc:
        logger.debug("[scenario_repo] add_scenario_evidence failed: %r", exc)
        return None


async def list_scenario_evidence(
    session,
    *,
    scenario_id: Optional[str] = None,
    source_phase: Optional[str] = None,
    limit: int = 200,
) -> List[object]:
    """Return ScenarioEvidence rows for a snapshot. Ordered by captured_at desc."""
    if session is None:
        return []
    try:
        from app.db.models import ScenarioEvidence
        from sqlalchemy import select

        stmt = select(ScenarioEvidence)
        if scenario_id is not None:
            stmt = stmt.where(ScenarioEvidence.scenario_id == scenario_id)
        if source_phase is not None:
            stmt = stmt.where(ScenarioEvidence.source_phase == source_phase)
        stmt = stmt.order_by(ScenarioEvidence.captured_at.desc()).limit(limit)

        result = await session.execute(stmt)
        return list(result.scalars().all())
    except Exception as exc:
        logger.debug("[scenario_repo] list_scenario_evidence failed: %r", exc)
        return []


async def delete_evidence_for_snapshot(
    session,
    *,
    scenario_id: str,
) -> int:
    """Delete all ScenarioEvidence rows for a snapshot. Returns rows deleted.

    Called before a rebuild (Phase 14 Slice 5) to clear stale evidence.
    """
    if session is None:
        return 0
    try:
        from app.db.models import ScenarioEvidence
        from sqlalchemy import delete

        stmt = delete(ScenarioEvidence).where(ScenarioEvidence.scenario_id == scenario_id)
        result = await session.execute(stmt)
        await session.flush()
        return result.rowcount or 0
    except Exception as exc:
        logger.debug("[scenario_repo] delete_evidence_for_snapshot failed: %r", exc)
        return 0


async def count_scenario_evidence(session) -> int:
    """Return the total count of ScenarioEvidence rows. 0 when session is None."""
    if session is None:
        return 0
    try:
        from app.db.models import ScenarioEvidence
        from sqlalchemy import select, func

        result = await session.execute(select(func.count()).select_from(ScenarioEvidence))
        return int(result.scalar_one() or 0)
    except Exception as exc:
        logger.debug("[scenario_repo] count_scenario_evidence failed: %r", exc)
        return 0


# ---------------------------------------------------------------------------
# § SCENARIO RUN LOG  (append-only — INSERT ONLY)
# ---------------------------------------------------------------------------

async def add_run_log(
    session,
    *,
    scenario_id: Optional[str] = None,
    scenario_type: str = "",
    entity_type: str = "",
    entity_key: str = "",
    user_id: Optional[str] = None,
    run_reason: str = "assembly",
    snapshot_reason: str = "",
    realized_state: Optional[str] = None,
    rank_position: Optional[int] = None,
    evaluated_at: Optional[datetime] = None,
    log_id: Optional[str] = None,
) -> Optional[object]:
    """Insert one ScenarioRunLog row.

    THIS FUNCTION ONLY INSERTS — it never updates or deletes an existing row.
    The immutability invariant is enforced here (no SELECT-then-update pattern)
    and verified by AST inspection in the validation script. Calibration outcomes
    (realized_state) are recorded by appending a NEW row keyed to the same
    scenario_id, never by mutating a prior run or shadow row.

    Returns the ORM row, or None when session is None.
    """
    if session is None:
        return None
    try:
        from app.db.models import ScenarioRunLog

        now = _now()
        row = ScenarioRunLog(
            id              = log_id or _new_id(),
            scenario_id     = scenario_id,
            scenario_type   = scenario_type,
            entity_type     = entity_type,
            entity_key      = entity_key,
            user_id         = user_id,
            run_reason      = run_reason,
            snapshot_reason = snapshot_reason,
            realized_state  = realized_state,
            rank_position   = rank_position,
            evaluated_at    = evaluated_at or now,
            created_at      = now,
        )
        session.add(row)
        await session.flush()
        return row
    except Exception as exc:
        logger.debug("[scenario_repo] add_run_log failed: %r", exc)
        return None


async def list_run_logs(
    session,
    *,
    scenario_id: Optional[str] = None,
    scenario_type: Optional[str] = None,
    entity_type: Optional[str] = None,
    user_id: Optional[str] = None,
    run_reason: Optional[str] = None,
    snapshot_reason: Optional[str] = None,
    evaluated_after: Optional[datetime] = None,
    limit: int = 500,
) -> List[object]:
    """Return ScenarioRunLog rows matching filters. Ordered evaluated_at desc."""
    if session is None:
        return []
    try:
        from app.db.models import ScenarioRunLog
        from sqlalchemy import select

        stmt = select(ScenarioRunLog)
        if scenario_id is not None:
            stmt = stmt.where(ScenarioRunLog.scenario_id == scenario_id)
        if scenario_type is not None:
            stmt = stmt.where(ScenarioRunLog.scenario_type == scenario_type)
        if entity_type is not None:
            stmt = stmt.where(ScenarioRunLog.entity_type == entity_type)
        if user_id is not None:
            stmt = stmt.where(ScenarioRunLog.user_id == user_id)
        if run_reason is not None:
            stmt = stmt.where(ScenarioRunLog.run_reason == run_reason)
        if snapshot_reason is not None:
            stmt = stmt.where(ScenarioRunLog.snapshot_reason == snapshot_reason)
        if evaluated_after is not None:
            stmt = stmt.where(ScenarioRunLog.evaluated_at >= evaluated_after)
        stmt = stmt.order_by(ScenarioRunLog.evaluated_at.desc()).limit(limit)

        result = await session.execute(stmt)
        return list(result.scalars().all())
    except Exception as exc:
        logger.debug("[scenario_repo] list_run_logs failed: %r", exc)
        return []


async def count_run_logs(
    session,
    *,
    scenario_type: Optional[str] = None,
    entity_type: Optional[str] = None,
    run_reason: Optional[str] = None,
    snapshot_reason: Optional[str] = None,
    evaluated_after: Optional[datetime] = None,
) -> int:
    """Return the count of ScenarioRunLog rows matching optional filters.

    Used by the calibration and observability services (Phase 14 Slices 9–10).
    Returns 0 when session is None or on error.
    """
    if session is None:
        return 0
    try:
        from app.db.models import ScenarioRunLog
        from sqlalchemy import select, func

        stmt = select(func.count()).select_from(ScenarioRunLog)
        if scenario_type is not None:
            stmt = stmt.where(ScenarioRunLog.scenario_type == scenario_type)
        if entity_type is not None:
            stmt = stmt.where(ScenarioRunLog.entity_type == entity_type)
        if run_reason is not None:
            stmt = stmt.where(ScenarioRunLog.run_reason == run_reason)
        if snapshot_reason is not None:
            stmt = stmt.where(ScenarioRunLog.snapshot_reason == snapshot_reason)
        if evaluated_after is not None:
            stmt = stmt.where(ScenarioRunLog.evaluated_at >= evaluated_after)
        result = await session.execute(stmt)
        return int(result.scalar_one() or 0)
    except Exception as exc:
        logger.debug("[scenario_repo] count_run_logs failed: %r", exc)
        return 0
