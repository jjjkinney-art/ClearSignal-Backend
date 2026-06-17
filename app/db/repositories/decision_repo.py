"""
Decision repository — Phase 13 · Slice 1.

CRUD for decision_priority, decision_evidence, and decision_ranking_log.
All functions accept an AsyncSession as the first positional argument.
Passing None is safe: every function returns an empty/falsy/None value
rather than raising. This mirrors the null-session contract used throughout
the loop, portfolio, account, billing, similarity, and forecast repos.

No candidate assembly, no scoring, no explainability, no delivery logic.
Pure DB access. The decision flags are not consulted here; flag checks belong
in the service layer (Phase 13 Slices 2+).

Safety invariants (Phase 13 spec §0 / SP-5):
  - This repo never writes to any source table (dossier, analogs, thesis,
    similarity, forecast, portfolio, delivery, notifications). Decision
    Intelligence is a pure sink.
  - decision_ranking_log has NO update or delete path in this repo. Every call
    that records a snapshot or an outcome uses add_ranking_log() which only
    INSERTs. This immutability is verified by the validation script via AST
    inspection of this module.
  - There is no buy/sell/hold, position-size, target-price, trade, or execution
    field on any table this repo touches. Rows here PRIORITIZE information and
    must not be passed to any conviction/recommendation/order path.
"""

from __future__ import annotations

import logging
import uuid as _uuid_mod
from datetime import datetime, timedelta, timezone
from typing import List, Optional

logger = logging.getLogger(__name__)

# Default TTL (hours) used by upsert_decision_priority when the caller does
# not supply an explicit expires_at.
DEFAULT_TTL_HOURS: int = 24


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _new_id() -> str:
    return str(_uuid_mod.uuid4())


# ---------------------------------------------------------------------------
# § DECISION PRIORITIES
# ---------------------------------------------------------------------------

async def upsert_decision_priority(
    session,
    *,
    candidate_type: str,
    entity_type: str,
    entity_key: str,
    source_ref: str = "",
    decision_priority: str = "informational",
    decision_rank_score: float = 0.0,
    attention_score: float = 0.0,
    urgency_score: float = 0.0,
    impact_score: float = 0.0,
    confidence_score: float = 0.0,
    uncertainty_score: float = 0.0,
    decision_reason: str = "",
    why_now: str = "",
    deprioritizers: Optional[list] = None,
    evidence_summary: Optional[list] = None,
    source_versions: Optional[dict] = None,
    decision_schema: int = 1,
    user_id: Optional[str] = None,
    ttl_hours: Optional[int] = None,
    priority_id: Optional[str] = None,
) -> Optional[object]:
    """Insert or update a DecisionPriority row.

    Upsert is keyed on
    (candidate_type, entity_type, entity_key, source_ref, user_id).
    Returns the ORM row, or None when session is None.

    The caller (Slice 13.5 rebuild orchestration) is responsible for ensuring
    the score and explainability invariants hold (all scores ∈ [0,1]; non-empty
    decision_reason / why_now / deprioritizers; ≥1 evidence_summary item). This
    repo performs no validation — it is pure persistence.
    """
    if session is None:
        return None
    try:
        from app.db.models import DecisionPriority
        from sqlalchemy import select

        stmt = select(DecisionPriority).where(
            DecisionPriority.candidate_type == candidate_type,
            DecisionPriority.entity_type    == entity_type,
            DecisionPriority.entity_key     == entity_key,
            DecisionPriority.source_ref     == source_ref,
            DecisionPriority.user_id        == user_id,
        )
        existing = (await session.execute(stmt)).scalar_one_or_none()

        now = _now()
        expires = now + timedelta(hours=ttl_hours if ttl_hours is not None else DEFAULT_TTL_HOURS)

        if existing is None:
            row = DecisionPriority(
                id                  = priority_id or _new_id(),
                candidate_type      = candidate_type,
                entity_type         = entity_type,
                entity_key          = entity_key,
                source_ref          = source_ref,
                decision_priority   = decision_priority,
                decision_rank_score = decision_rank_score,
                attention_score     = attention_score,
                urgency_score       = urgency_score,
                impact_score        = impact_score,
                confidence_score    = confidence_score,
                uncertainty_score   = uncertainty_score,
                decision_reason     = decision_reason,
                why_now             = why_now,
                deprioritizers      = deprioritizers if deprioritizers is not None else [],
                evidence_summary    = evidence_summary if evidence_summary is not None else [],
                source_versions     = source_versions if source_versions is not None else {},
                decision_schema     = decision_schema,
                user_id             = user_id,
                built_at            = now,
                expires_at          = expires,
            )
            session.add(row)
            await session.flush()
            return row

        # Update in place — keyed row already exists
        existing.decision_priority   = decision_priority
        existing.decision_rank_score = decision_rank_score
        existing.attention_score     = attention_score
        existing.urgency_score       = urgency_score
        existing.impact_score        = impact_score
        existing.confidence_score    = confidence_score
        existing.uncertainty_score   = uncertainty_score
        existing.decision_reason     = decision_reason
        existing.why_now             = why_now
        existing.deprioritizers      = deprioritizers if deprioritizers is not None else []
        existing.evidence_summary    = evidence_summary if evidence_summary is not None else []
        existing.source_versions     = source_versions if source_versions is not None else {}
        existing.decision_schema     = decision_schema
        existing.built_at            = now
        existing.expires_at          = expires
        await session.flush()
        return existing
    except Exception as exc:
        logger.debug("[decision_repo] upsert_decision_priority failed: %r", exc)
        return None


async def get_decision_priority(
    session,
    *,
    candidate_type: str,
    entity_type: str,
    entity_key: str,
    source_ref: str = "",
    user_id: Optional[str] = None,
) -> Optional[object]:
    """Return one DecisionPriority row by its unique key, or None."""
    if session is None:
        return None
    try:
        from app.db.models import DecisionPriority
        from sqlalchemy import select

        stmt = select(DecisionPriority).where(
            DecisionPriority.candidate_type == candidate_type,
            DecisionPriority.entity_type    == entity_type,
            DecisionPriority.entity_key     == entity_key,
            DecisionPriority.source_ref     == source_ref,
            DecisionPriority.user_id        == user_id,
        )
        return (await session.execute(stmt)).scalar_one_or_none()
    except Exception as exc:
        logger.debug("[decision_repo] get_decision_priority failed: %r", exc)
        return None


async def list_decision_priorities(
    session,
    *,
    candidate_type: Optional[str] = None,
    entity_type: Optional[str] = None,
    entity_key: Optional[str] = None,
    decision_priority: Optional[str] = None,
    user_id: Optional[str] = None,
    user_id_is_null: Optional[bool] = None,
    decision_schema: Optional[int] = None,
    exclude_expired: bool = False,
    limit: int = 200,
) -> List[object]:
    """Return DecisionPriority rows matching the given filters.

    All filters are optional. Returns [] when session is None or on error.
    Ordered by decision_rank_score descending.

    `user_id` filters to an exact user scope. `user_id_is_null=True` filters to
    the global tier (user_id IS NULL); `user_id_is_null=False` filters to the
    user tier (user_id IS NOT NULL). These are mutually exclusive with passing
    an explicit `user_id`.
    """
    if session is None:
        return []
    try:
        from app.db.models import DecisionPriority
        from sqlalchemy import select

        stmt = select(DecisionPriority)
        if candidate_type is not None:
            stmt = stmt.where(DecisionPriority.candidate_type == candidate_type)
        if entity_type is not None:
            stmt = stmt.where(DecisionPriority.entity_type == entity_type)
        if entity_key is not None:
            stmt = stmt.where(DecisionPriority.entity_key == entity_key)
        if decision_priority is not None:
            stmt = stmt.where(DecisionPriority.decision_priority == decision_priority)
        if user_id is not None:
            stmt = stmt.where(DecisionPriority.user_id == user_id)
        if user_id_is_null is True:
            stmt = stmt.where(DecisionPriority.user_id.is_(None))
        elif user_id_is_null is False:
            stmt = stmt.where(DecisionPriority.user_id.is_not(None))
        if decision_schema is not None:
            stmt = stmt.where(DecisionPriority.decision_schema == decision_schema)
        if exclude_expired:
            stmt = stmt.where(DecisionPriority.expires_at > _now())
        stmt = stmt.order_by(DecisionPriority.decision_rank_score.desc()).limit(limit)

        result = await session.execute(stmt)
        return list(result.scalars().all())
    except Exception as exc:
        logger.debug("[decision_repo] list_decision_priorities failed: %r", exc)
        return []


async def delete_decision_priority(
    session,
    *,
    candidate_type: str,
    entity_type: str,
    entity_key: str,
    source_ref: str = "",
    user_id: Optional[str] = None,
) -> bool:
    """Delete a DecisionPriority row. Returns True if a row was deleted."""
    if session is None:
        return False
    try:
        from app.db.models import DecisionPriority
        from sqlalchemy import select

        stmt = select(DecisionPriority).where(
            DecisionPriority.candidate_type == candidate_type,
            DecisionPriority.entity_type    == entity_type,
            DecisionPriority.entity_key     == entity_key,
            DecisionPriority.source_ref     == source_ref,
            DecisionPriority.user_id        == user_id,
        )
        row = (await session.execute(stmt)).scalar_one_or_none()
        if row is None:
            return False
        await session.delete(row)
        await session.flush()
        return True
    except Exception as exc:
        logger.debug("[decision_repo] delete_decision_priority failed: %r", exc)
        return False


async def delete_expired_priorities(
    session,
    *,
    batch_limit: int = 500,
) -> int:
    """Delete DecisionPriority rows whose expires_at <= now().

    Returns the number of rows deleted. Returns 0 when session is None.
    Called by the invalidation service TTL sweep (Phase 13 Slice 5).
    """
    if session is None:
        return 0
    try:
        from app.db.models import DecisionPriority
        from sqlalchemy import select, delete

        subq = (
            select(DecisionPriority.id)
            .where(DecisionPriority.expires_at <= _now())
            .limit(batch_limit)
            .scalar_subquery()
        )
        stmt = delete(DecisionPriority).where(DecisionPriority.id.in_(subq))
        result = await session.execute(stmt)
        await session.flush()
        return result.rowcount or 0
    except Exception as exc:
        logger.debug("[decision_repo] delete_expired_priorities failed: %r", exc)
        return 0


async def count_decision_priorities(
    session,
    *,
    candidate_type: Optional[str] = None,
    entity_type: Optional[str] = None,
    user_id_is_null: Optional[bool] = None,
) -> int:
    """Return the count of DecisionPriority rows matching optional filters.

    Used by the observability service (Phase 13 Slice 10).
    Returns 0 when session is None or on error.
    """
    if session is None:
        return 0
    try:
        from app.db.models import DecisionPriority
        from sqlalchemy import select, func

        stmt = select(func.count()).select_from(DecisionPriority)
        if candidate_type is not None:
            stmt = stmt.where(DecisionPriority.candidate_type == candidate_type)
        if entity_type is not None:
            stmt = stmt.where(DecisionPriority.entity_type == entity_type)
        if user_id_is_null is True:
            stmt = stmt.where(DecisionPriority.user_id.is_(None))
        elif user_id_is_null is False:
            stmt = stmt.where(DecisionPriority.user_id.is_not(None))
        result = await session.execute(stmt)
        return int(result.scalar_one() or 0)
    except Exception as exc:
        logger.debug("[decision_repo] count_decision_priorities failed: %r", exc)
        return 0


# ---------------------------------------------------------------------------
# § DECISION EVIDENCE
# ---------------------------------------------------------------------------

async def add_decision_evidence(
    session,
    *,
    priority_id: str,
    source_type: str,
    source_id: str,
    dimension: str = "attention",
    contribution: float = 0.0,
    weight: float = 0.0,
    description: str = "",
    entity_type: str = "",
    entity_key: str = "",
    user_id: Optional[str] = None,
    evidence_id: Optional[str] = None,
) -> Optional[object]:
    """Insert one DecisionEvidence row. Returns the ORM row, or None."""
    if session is None:
        return None
    try:
        from app.db.models import DecisionEvidence

        row = DecisionEvidence(
            id           = evidence_id or _new_id(),
            priority_id  = priority_id,
            source_type  = source_type,
            source_id    = source_id,
            dimension    = dimension,
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
        logger.debug("[decision_repo] add_decision_evidence failed: %r", exc)
        return None


async def list_decision_evidence(
    session,
    *,
    priority_id: Optional[str] = None,
    dimension: Optional[str] = None,
    limit: int = 200,
) -> List[object]:
    """Return DecisionEvidence rows for a priority. Ordered by weight desc."""
    if session is None:
        return []
    try:
        from app.db.models import DecisionEvidence
        from sqlalchemy import select

        stmt = select(DecisionEvidence)
        if priority_id is not None:
            stmt = stmt.where(DecisionEvidence.priority_id == priority_id)
        if dimension is not None:
            stmt = stmt.where(DecisionEvidence.dimension == dimension)
        stmt = stmt.order_by(DecisionEvidence.weight.desc()).limit(limit)

        result = await session.execute(stmt)
        return list(result.scalars().all())
    except Exception as exc:
        logger.debug("[decision_repo] list_decision_evidence failed: %r", exc)
        return []


async def delete_evidence_for_priority(
    session,
    *,
    priority_id: str,
) -> int:
    """Delete all DecisionEvidence rows for a priority. Returns rows deleted.

    Called before a rebuild (Phase 13 Slice 5) to clear stale evidence.
    """
    if session is None:
        return 0
    try:
        from app.db.models import DecisionEvidence
        from sqlalchemy import delete

        stmt = delete(DecisionEvidence).where(DecisionEvidence.priority_id == priority_id)
        result = await session.execute(stmt)
        await session.flush()
        return result.rowcount or 0
    except Exception as exc:
        logger.debug("[decision_repo] delete_evidence_for_priority failed: %r", exc)
        return 0


async def count_decision_evidence(session) -> int:
    """Return the total count of DecisionEvidence rows. 0 when session is None."""
    if session is None:
        return 0
    try:
        from app.db.models import DecisionEvidence
        from sqlalchemy import select, func

        result = await session.execute(select(func.count()).select_from(DecisionEvidence))
        return int(result.scalar_one() or 0)
    except Exception as exc:
        logger.debug("[decision_repo] count_decision_evidence failed: %r", exc)
        return 0


# ---------------------------------------------------------------------------
# § DECISION RANKING LOG  (append-only — INSERT ONLY)
# ---------------------------------------------------------------------------

async def add_ranking_log(
    session,
    *,
    priority_id: str,
    candidate_type: str = "",
    entity_type: str = "",
    entity_key: str = "",
    user_id: Optional[str] = None,
    decision_priority: str = "informational",
    decision_rank_score: float = 0.0,
    rank_position: int = 0,
    snapshot_reason: str = "scheduled",
    realized_significance: Optional[str] = None,
    evaluated_at: Optional[datetime] = None,
    log_id: Optional[str] = None,
) -> Optional[object]:
    """Insert one DecisionRankingLog row.

    THIS FUNCTION ONLY INSERTS — it never updates or deletes an existing row.
    The immutability invariant is enforced here (no SELECT-then-update pattern)
    and verified by AST inspection in the validation script. Outcome attribution
    (realized_significance) is recorded by appending a NEW row keyed to the same
    priority_id, never by mutating a prior snapshot.

    Returns the ORM row, or None when session is None.
    """
    if session is None:
        return None
    try:
        from app.db.models import DecisionRankingLog

        now = _now()
        row = DecisionRankingLog(
            id                    = log_id or _new_id(),
            priority_id           = priority_id,
            candidate_type        = candidate_type,
            entity_type           = entity_type,
            entity_key            = entity_key,
            user_id               = user_id,
            decision_priority     = decision_priority,
            decision_rank_score   = decision_rank_score,
            rank_position         = rank_position,
            snapshot_reason       = snapshot_reason,
            realized_significance = realized_significance,
            evaluated_at          = evaluated_at or now,
            created_at            = now,
        )
        session.add(row)
        await session.flush()
        return row
    except Exception as exc:
        logger.debug("[decision_repo] add_ranking_log failed: %r", exc)
        return None


async def list_ranking_logs(
    session,
    *,
    priority_id: Optional[str] = None,
    candidate_type: Optional[str] = None,
    entity_type: Optional[str] = None,
    user_id: Optional[str] = None,
    snapshot_reason: Optional[str] = None,
    evaluated_after: Optional[datetime] = None,
    limit: int = 500,
) -> List[object]:
    """Return DecisionRankingLog rows matching filters. Ordered evaluated_at desc."""
    if session is None:
        return []
    try:
        from app.db.models import DecisionRankingLog
        from sqlalchemy import select

        stmt = select(DecisionRankingLog)
        if priority_id is not None:
            stmt = stmt.where(DecisionRankingLog.priority_id == priority_id)
        if candidate_type is not None:
            stmt = stmt.where(DecisionRankingLog.candidate_type == candidate_type)
        if entity_type is not None:
            stmt = stmt.where(DecisionRankingLog.entity_type == entity_type)
        if user_id is not None:
            stmt = stmt.where(DecisionRankingLog.user_id == user_id)
        if snapshot_reason is not None:
            stmt = stmt.where(DecisionRankingLog.snapshot_reason == snapshot_reason)
        if evaluated_after is not None:
            stmt = stmt.where(DecisionRankingLog.evaluated_at >= evaluated_after)
        stmt = stmt.order_by(DecisionRankingLog.evaluated_at.desc()).limit(limit)

        result = await session.execute(stmt)
        return list(result.scalars().all())
    except Exception as exc:
        logger.debug("[decision_repo] list_ranking_logs failed: %r", exc)
        return []


async def count_ranking_logs(
    session,
    *,
    candidate_type: Optional[str] = None,
    entity_type: Optional[str] = None,
    snapshot_reason: Optional[str] = None,
    evaluated_after: Optional[datetime] = None,
) -> int:
    """Return the count of DecisionRankingLog rows matching optional filters.

    Used by the calibration and observability services (Phase 13 Slices 9–10).
    Returns 0 when session is None or on error.
    """
    if session is None:
        return 0
    try:
        from app.db.models import DecisionRankingLog
        from sqlalchemy import select, func

        stmt = select(func.count()).select_from(DecisionRankingLog)
        if candidate_type is not None:
            stmt = stmt.where(DecisionRankingLog.candidate_type == candidate_type)
        if entity_type is not None:
            stmt = stmt.where(DecisionRankingLog.entity_type == entity_type)
        if snapshot_reason is not None:
            stmt = stmt.where(DecisionRankingLog.snapshot_reason == snapshot_reason)
        if evaluated_after is not None:
            stmt = stmt.where(DecisionRankingLog.evaluated_at >= evaluated_after)
        result = await session.execute(stmt)
        return int(result.scalar_one() or 0)
    except Exception as exc:
        logger.debug("[decision_repo] count_ranking_logs failed: %r", exc)
        return 0
