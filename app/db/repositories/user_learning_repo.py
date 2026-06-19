"""
User Learning repository — Phase 15 · Slice 2.

CRUD for user_signal_event, learned_preference, preference_evidence,
and relevance_adjustment_log.

All functions accept an AsyncSession as the first positional argument.
Passing None is safe: every function returns an empty/falsy/None value
rather than raising. This mirrors the null-session contract used throughout
the loop, portfolio, account, billing, similarity, forecast, decision, and
scenario repos.

No signal capture, no inference, no explainability, no delivery logic.
Pure DB access. The learning_* flags are not consulted here; flag checks
belong in the service layer (Phase 15 Slices 3+).

Safety invariants (Phase 15 spec §1.2 / SP-7):
  - This repo never writes to any source table (dossier, analogs, thesis,
    similarity_edge, forecast_vector, scenario_snapshot, decision_priority,
    ticker_memory, or any upstream truth table). Phase 15 is a pure sink.
  - relevance_adjustment_log has NO update or delete path in this repo.
    Every call that records an adjustment uses add_relevance_adjustment_log()
    which only INSERTs. This append-only immutability is verified by AST
    inspection in the Slice 15.2 test suite and will be checked again by
    tests/validate_15_user_learning_shadow.py (Slice 15.11).
  - There is no buy/sell/hold, position_size, target_price, trade, execution,
    recommendation, forecast_override, similarity_override, scenario_override,
    or decision_override field on any table this repo touches. Rows here
    describe behavioral observations and relevance projections only.
  - The repo does not import any write path from forecast_repo, decision_repo,
    scenario_repo, similarity_repo, or any dossier/memory write module.
"""

from __future__ import annotations

import logging
import uuid as _uuid_mod
from datetime import datetime, timezone
from typing import List, Optional

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _new_id() -> str:
    return str(_uuid_mod.uuid4())


# ---------------------------------------------------------------------------
# § USER SIGNAL EVENTS  (append-only — INSERT / LIST / COUNT / EXPIRE)
# ---------------------------------------------------------------------------

async def add_user_signal_event(
    session,
    *,
    user_id: str,
    signal_type: str,
    polarity: str = "neutral",
    entity_type: str = "",
    entity_key: str = "",
    source_surface: str = "",
    surface_was_personalized: bool = False,
    pre_personalization_rank: Optional[int] = None,
    interaction_weight: float = 1.0,
    occurred_at: Optional[datetime] = None,
    event_id: Optional[str] = None,
) -> Optional[object]:
    """Insert one UserSignalEvent row. Returns the ORM row, or None.

    This function ONLY INSERTS — it never updates an existing event.
    The append-only property of user_signal_event is structural: behavioral
    history is immutable; corrections are recorded as new events.

    surface_was_personalized and pre_personalization_rank are the anti-
    feedback-loop fields (risk R2). The caller must always supply them so the
    learning pass can distinguish 'user chose this' from 'we put this on top'.
    """
    if session is None:
        return None
    try:
        from app.db.models import UserSignalEvent

        now = _now()
        row = UserSignalEvent(
            id                       = event_id or _new_id(),
            user_id                  = user_id,
            signal_type              = signal_type,
            polarity                 = polarity,
            entity_type              = entity_type,
            entity_key               = entity_key,
            source_surface           = source_surface,
            surface_was_personalized = surface_was_personalized,
            pre_personalization_rank = pre_personalization_rank,
            interaction_weight       = interaction_weight,
            occurred_at              = occurred_at or now,
            created_at               = now,
        )
        session.add(row)
        await session.flush()
        return row
    except Exception as exc:
        logger.debug("[user_learning_repo] add_user_signal_event failed: %r", exc)
        return None


async def list_user_signal_events(
    session,
    *,
    user_id: Optional[str] = None,
    signal_type: Optional[str] = None,
    entity_type: Optional[str] = None,
    entity_key: Optional[str] = None,
    polarity: Optional[str] = None,
    occurred_after: Optional[datetime] = None,
    limit: int = 500,
) -> List[object]:
    """Return UserSignalEvent rows matching the given filters.

    All filters are optional. Returns [] when session is None or on error.
    Ordered by occurred_at descending (most-recent first).
    """
    if session is None:
        return []
    try:
        from app.db.models import UserSignalEvent
        from sqlalchemy import select

        stmt = select(UserSignalEvent)
        if user_id is not None:
            stmt = stmt.where(UserSignalEvent.user_id == user_id)
        if signal_type is not None:
            stmt = stmt.where(UserSignalEvent.signal_type == signal_type)
        if entity_type is not None:
            stmt = stmt.where(UserSignalEvent.entity_type == entity_type)
        if entity_key is not None:
            stmt = stmt.where(UserSignalEvent.entity_key == entity_key)
        if polarity is not None:
            stmt = stmt.where(UserSignalEvent.polarity == polarity)
        if occurred_after is not None:
            stmt = stmt.where(UserSignalEvent.occurred_at >= occurred_after)
        stmt = stmt.order_by(UserSignalEvent.occurred_at.desc()).limit(limit)

        result = await session.execute(stmt)
        return list(result.scalars().all())
    except Exception as exc:
        logger.debug("[user_learning_repo] list_user_signal_events failed: %r", exc)
        return []


async def count_user_signal_events(
    session,
    *,
    user_id: Optional[str] = None,
    signal_type: Optional[str] = None,
    polarity: Optional[str] = None,
    occurred_after: Optional[datetime] = None,
) -> int:
    """Return the count of UserSignalEvent rows matching optional filters.

    Returns 0 when session is None or on error.
    """
    if session is None:
        return 0
    try:
        from app.db.models import UserSignalEvent
        from sqlalchemy import select, func

        stmt = select(func.count()).select_from(UserSignalEvent)
        if user_id is not None:
            stmt = stmt.where(UserSignalEvent.user_id == user_id)
        if signal_type is not None:
            stmt = stmt.where(UserSignalEvent.signal_type == signal_type)
        if polarity is not None:
            stmt = stmt.where(UserSignalEvent.polarity == polarity)
        if occurred_after is not None:
            stmt = stmt.where(UserSignalEvent.occurred_at >= occurred_after)
        result = await session.execute(stmt)
        return int(result.scalar_one() or 0)
    except Exception as exc:
        logger.debug("[user_learning_repo] count_user_signal_events failed: %r", exc)
        return 0


async def delete_expired_user_signal_events(
    session,
    *,
    cutoff: datetime,
    batch_limit: int = 1000,
) -> int:
    """Delete UserSignalEvent rows with occurred_at < cutoff (retention sweep).

    Returns the number of rows deleted, 0 when session is None or on error.
    The cutoff is the oldest event timestamp to retain; everything before it
    is eligible for deletion. Explicit-preference events should be excluded by
    the caller via a separate retention window (spec §13.2 open question 3);
    this function deletes all rows before the cutoff without discrimination.
    """
    if session is None:
        return 0
    try:
        from app.db.models import UserSignalEvent
        from sqlalchemy import select, delete

        subq = (
            select(UserSignalEvent.id)
            .where(UserSignalEvent.occurred_at < cutoff)
            .limit(batch_limit)
            .scalar_subquery()
        )
        stmt = delete(UserSignalEvent).where(UserSignalEvent.id.in_(subq))
        result = await session.execute(stmt)
        await session.flush()
        return result.rowcount or 0
    except Exception as exc:
        logger.debug("[user_learning_repo] delete_expired_user_signal_events failed: %r", exc)
        return 0


# ---------------------------------------------------------------------------
# § LEARNED PREFERENCES  (upsert / get / list / count / delete)
# ---------------------------------------------------------------------------

async def upsert_learned_preference(
    session,
    *,
    user_id: str,
    dimension: str,
    entity_key: str,
    affinity: float = 0.0,
    confidence: float = 0.0,
    evidence_count: int = 0,
    status: str = "unresolved",
    belief_basis: str = "",
    signal_strength_label: str = "tentative",
    falsifier: str = "",
    last_reinforced_at: Optional[datetime] = None,
    preference_schema: int = 1,
    preference_id: Optional[str] = None,
) -> Optional[object]:
    """Insert or update one LearnedPreference row.

    Upsert is keyed on (user_id, dimension, entity_key). Returns the ORM row,
    or None when session is None.

    The caller (inference service, Slice 15.5) is responsible for ensuring
    the four explainability fields are well-formed before calling upsert. This
    repo performs no validation — it is pure persistence.

    SP-7g: a preference written here with status='active' must have passed
    the explainability gate upstream (Slice 15.4). This repo does not enforce
    that gate; it trusts the caller.
    """
    if session is None:
        return None
    try:
        from app.db.models import LearnedPreference
        from sqlalchemy import select

        stmt = select(LearnedPreference).where(
            LearnedPreference.user_id     == user_id,
            LearnedPreference.dimension   == dimension,
            LearnedPreference.entity_key  == entity_key,
        )
        existing = (await session.execute(stmt)).scalar_one_or_none()

        now = _now()
        reinforced = last_reinforced_at or now

        if existing is None:
            row = LearnedPreference(
                id                    = preference_id or _new_id(),
                user_id               = user_id,
                dimension             = dimension,
                entity_key            = entity_key,
                affinity              = affinity,
                confidence            = confidence,
                evidence_count        = evidence_count,
                status                = status,
                belief_basis          = belief_basis,
                signal_strength_label = signal_strength_label,
                falsifier             = falsifier,
                first_observed_at     = now,
                last_reinforced_at    = reinforced,
                preference_schema     = preference_schema,
                updated_at            = now,
            )
            session.add(row)
            await session.flush()
            return row

        # Update in place — keyed row already exists
        existing.affinity              = affinity
        existing.confidence            = confidence
        existing.evidence_count        = evidence_count
        existing.status                = status
        existing.belief_basis          = belief_basis
        existing.signal_strength_label = signal_strength_label
        existing.falsifier             = falsifier
        existing.last_reinforced_at    = reinforced
        existing.preference_schema     = preference_schema
        existing.updated_at            = now
        await session.flush()
        return existing
    except Exception as exc:
        logger.debug("[user_learning_repo] upsert_learned_preference failed: %r", exc)
        return None


async def get_learned_preference(
    session,
    *,
    user_id: str,
    dimension: str,
    entity_key: str,
) -> Optional[object]:
    """Return one LearnedPreference row by its unique key, or None."""
    if session is None:
        return None
    try:
        from app.db.models import LearnedPreference
        from sqlalchemy import select

        stmt = select(LearnedPreference).where(
            LearnedPreference.user_id    == user_id,
            LearnedPreference.dimension  == dimension,
            LearnedPreference.entity_key == entity_key,
        )
        return (await session.execute(stmt)).scalar_one_or_none()
    except Exception as exc:
        logger.debug("[user_learning_repo] get_learned_preference failed: %r", exc)
        return None


async def list_learned_preferences(
    session,
    *,
    user_id: Optional[str] = None,
    dimension: Optional[str] = None,
    status: Optional[str] = None,
    preference_schema: Optional[int] = None,
    limit: int = 500,
) -> List[object]:
    """Return LearnedPreference rows matching the given filters.

    All filters are optional. Returns [] when session is None or on error.
    Ordered by last_reinforced_at descending (most-recent signal first).
    """
    if session is None:
        return []
    try:
        from app.db.models import LearnedPreference
        from sqlalchemy import select

        stmt = select(LearnedPreference)
        if user_id is not None:
            stmt = stmt.where(LearnedPreference.user_id == user_id)
        if dimension is not None:
            stmt = stmt.where(LearnedPreference.dimension == dimension)
        if status is not None:
            stmt = stmt.where(LearnedPreference.status == status)
        if preference_schema is not None:
            stmt = stmt.where(LearnedPreference.preference_schema == preference_schema)
        stmt = stmt.order_by(LearnedPreference.last_reinforced_at.desc()).limit(limit)

        result = await session.execute(stmt)
        return list(result.scalars().all())
    except Exception as exc:
        logger.debug("[user_learning_repo] list_learned_preferences failed: %r", exc)
        return []


async def count_learned_preferences(
    session,
    *,
    user_id: Optional[str] = None,
    dimension: Optional[str] = None,
    status: Optional[str] = None,
) -> int:
    """Return the count of LearnedPreference rows matching optional filters.

    Returns 0 when session is None or on error.
    """
    if session is None:
        return 0
    try:
        from app.db.models import LearnedPreference
        from sqlalchemy import select, func

        stmt = select(func.count()).select_from(LearnedPreference)
        if user_id is not None:
            stmt = stmt.where(LearnedPreference.user_id == user_id)
        if dimension is not None:
            stmt = stmt.where(LearnedPreference.dimension == dimension)
        if status is not None:
            stmt = stmt.where(LearnedPreference.status == status)
        result = await session.execute(stmt)
        return int(result.scalar_one() or 0)
    except Exception as exc:
        logger.debug("[user_learning_repo] count_learned_preferences failed: %r", exc)
        return 0


async def delete_learned_preference(
    session,
    *,
    user_id: str,
    dimension: str,
    entity_key: str,
) -> bool:
    """Delete one LearnedPreference row by its unique key.

    Returns True if a row was deleted, False if the row did not exist.
    Returns False when session is None or on error.
    """
    if session is None:
        return False
    try:
        from app.db.models import LearnedPreference
        from sqlalchemy import select

        stmt = select(LearnedPreference).where(
            LearnedPreference.user_id    == user_id,
            LearnedPreference.dimension  == dimension,
            LearnedPreference.entity_key == entity_key,
        )
        row = (await session.execute(stmt)).scalar_one_or_none()
        if row is None:
            return False
        await session.delete(row)
        await session.flush()
        return True
    except Exception as exc:
        logger.debug("[user_learning_repo] delete_learned_preference failed: %r", exc)
        return False


# ---------------------------------------------------------------------------
# § PREFERENCE EVIDENCE  (append-only — INSERT / LIST / DELETE / COUNT)
# ---------------------------------------------------------------------------

async def add_preference_evidence(
    session,
    *,
    preference_id: str,
    signal_event_id: str,
    contribution: float = 0.0,
    source: str = "",
    observed_at: Optional[datetime] = None,
    evidence_id: Optional[str] = None,
) -> Optional[object]:
    """Insert one PreferenceEvidence row. Returns the ORM row, or None.

    This function ONLY INSERTS — it never updates an existing evidence row.
    Evidence rows are immutable once written; corrections are handled by the
    inference pass inserting a corrected row in the next pass.

    preference_id and signal_event_id are soft FKs (no CASCADE). The
    explainability gate (Slice 15.4) validates that signal_event_id resolves
    to a real UserSignalEvent before calling this function.
    """
    if session is None:
        return None
    try:
        from app.db.models import PreferenceEvidence

        row = PreferenceEvidence(
            id              = evidence_id or _new_id(),
            preference_id   = preference_id,
            signal_event_id = signal_event_id,
            contribution    = contribution,
            source          = source,
            observed_at     = observed_at or _now(),
        )
        session.add(row)
        await session.flush()
        return row
    except Exception as exc:
        logger.debug("[user_learning_repo] add_preference_evidence failed: %r", exc)
        return None


async def list_preference_evidence(
    session,
    *,
    preference_id: Optional[str] = None,
    signal_event_id: Optional[str] = None,
    source: Optional[str] = None,
    limit: int = 500,
) -> List[object]:
    """Return PreferenceEvidence rows matching the given filters.

    All filters are optional. Returns [] when session is None or on error.
    Ordered by observed_at descending.
    """
    if session is None:
        return []
    try:
        from app.db.models import PreferenceEvidence
        from sqlalchemy import select

        stmt = select(PreferenceEvidence)
        if preference_id is not None:
            stmt = stmt.where(PreferenceEvidence.preference_id == preference_id)
        if signal_event_id is not None:
            stmt = stmt.where(PreferenceEvidence.signal_event_id == signal_event_id)
        if source is not None:
            stmt = stmt.where(PreferenceEvidence.source == source)
        stmt = stmt.order_by(PreferenceEvidence.observed_at.desc()).limit(limit)

        result = await session.execute(stmt)
        return list(result.scalars().all())
    except Exception as exc:
        logger.debug("[user_learning_repo] list_preference_evidence failed: %r", exc)
        return []


async def delete_evidence_for_preference(
    session,
    *,
    preference_id: str,
) -> int:
    """Delete all PreferenceEvidence rows for a preference. Returns rows deleted.

    Called when a preference is deleted or when the inference pass rebuilds
    its evidence set from scratch (e.g. after a preference_schema bump).
    Returns 0 when session is None or on error.
    """
    if session is None:
        return 0
    try:
        from app.db.models import PreferenceEvidence
        from sqlalchemy import delete

        stmt = delete(PreferenceEvidence).where(
            PreferenceEvidence.preference_id == preference_id
        )
        result = await session.execute(stmt)
        await session.flush()
        return result.rowcount or 0
    except Exception as exc:
        logger.debug("[user_learning_repo] delete_evidence_for_preference failed: %r", exc)
        return 0


async def count_preference_evidence(
    session,
    *,
    preference_id: Optional[str] = None,
) -> int:
    """Return the count of PreferenceEvidence rows.

    Optionally filtered by preference_id.
    Returns 0 when session is None or on error.
    """
    if session is None:
        return 0
    try:
        from app.db.models import PreferenceEvidence
        from sqlalchemy import select, func

        stmt = select(func.count()).select_from(PreferenceEvidence)
        if preference_id is not None:
            stmt = stmt.where(PreferenceEvidence.preference_id == preference_id)
        result = await session.execute(stmt)
        return int(result.scalar_one() or 0)
    except Exception as exc:
        logger.debug("[user_learning_repo] count_preference_evidence failed: %r", exc)
        return 0


# ---------------------------------------------------------------------------
# § RELEVANCE ADJUSTMENT LOG  (append-only — INSERT ONLY)
# ---------------------------------------------------------------------------

async def add_relevance_adjustment_log(
    session,
    *,
    user_id: str,
    surface: str,
    run_reason: str = "shadow",
    item_ref: str = "",
    intrinsic_rank: int = 0,
    adjusted_rank: int = 0,
    relevance_weight: float = 0.0,
    prominence_tier: str = "normal",
    floor_applied: bool = False,
    evaluated_at: Optional[datetime] = None,
    log_id: Optional[str] = None,
) -> Optional[object]:
    """Insert one RelevanceAdjustmentLog row.

    THIS FUNCTION ONLY INSERTS — it never updates or deletes an existing row.
    The append-only immutability is enforced here (no SELECT-then-update pattern)
    and is verified by AST inspection in the test suite and by
    tests/validate_15_user_learning_shadow.py (Slice 15.11).

    prominence_tier must be 'pinned', 'normal', or 'muted'. The value 'hidden'
    is forbidden by SP-7d (demote-never-hide). The caller is responsible for
    enforcing this; this repo does not validate the value.

    run_reason must be 'shadow' until Stage 5 sign-off. The caller (relevance
    shadow service, Slice 15.9) is responsible for enforcing the gate.

    Returns the ORM row, or None when session is None.
    """
    if session is None:
        return None
    try:
        from app.db.models import RelevanceAdjustmentLog

        now = _now()
        row = RelevanceAdjustmentLog(
            id               = log_id or _new_id(),
            user_id          = user_id,
            surface          = surface,
            run_reason       = run_reason,
            item_ref         = item_ref,
            intrinsic_rank   = intrinsic_rank,
            adjusted_rank    = adjusted_rank,
            relevance_weight = relevance_weight,
            prominence_tier  = prominence_tier,
            floor_applied    = floor_applied,
            evaluated_at     = evaluated_at or now,
            created_at       = now,
        )
        session.add(row)
        await session.flush()
        return row
    except Exception as exc:
        logger.debug("[user_learning_repo] add_relevance_adjustment_log failed: %r", exc)
        return None


async def list_relevance_adjustment_logs(
    session,
    *,
    user_id: Optional[str] = None,
    surface: Optional[str] = None,
    run_reason: Optional[str] = None,
    item_ref: Optional[str] = None,
    floor_applied: Optional[bool] = None,
    evaluated_after: Optional[datetime] = None,
    limit: int = 500,
) -> List[object]:
    """Return RelevanceAdjustmentLog rows matching the given filters.

    All filters are optional. Returns [] when session is None or on error.
    Ordered by evaluated_at descending (most-recent adjustment first).
    """
    if session is None:
        return []
    try:
        from app.db.models import RelevanceAdjustmentLog
        from sqlalchemy import select

        stmt = select(RelevanceAdjustmentLog)
        if user_id is not None:
            stmt = stmt.where(RelevanceAdjustmentLog.user_id == user_id)
        if surface is not None:
            stmt = stmt.where(RelevanceAdjustmentLog.surface == surface)
        if run_reason is not None:
            stmt = stmt.where(RelevanceAdjustmentLog.run_reason == run_reason)
        if item_ref is not None:
            stmt = stmt.where(RelevanceAdjustmentLog.item_ref == item_ref)
        if floor_applied is not None:
            stmt = stmt.where(RelevanceAdjustmentLog.floor_applied == floor_applied)
        if evaluated_after is not None:
            stmt = stmt.where(RelevanceAdjustmentLog.evaluated_at >= evaluated_after)
        stmt = stmt.order_by(RelevanceAdjustmentLog.evaluated_at.desc()).limit(limit)

        result = await session.execute(stmt)
        return list(result.scalars().all())
    except Exception as exc:
        logger.debug("[user_learning_repo] list_relevance_adjustment_logs failed: %r", exc)
        return []


async def count_relevance_adjustment_logs(
    session,
    *,
    user_id: Optional[str] = None,
    surface: Optional[str] = None,
    run_reason: Optional[str] = None,
    floor_applied: Optional[bool] = None,
    evaluated_after: Optional[datetime] = None,
) -> int:
    """Return the count of RelevanceAdjustmentLog rows matching optional filters.

    Returns 0 when session is None or on error.
    """
    if session is None:
        return 0
    try:
        from app.db.models import RelevanceAdjustmentLog
        from sqlalchemy import select, func

        stmt = select(func.count()).select_from(RelevanceAdjustmentLog)
        if user_id is not None:
            stmt = stmt.where(RelevanceAdjustmentLog.user_id == user_id)
        if surface is not None:
            stmt = stmt.where(RelevanceAdjustmentLog.surface == surface)
        if run_reason is not None:
            stmt = stmt.where(RelevanceAdjustmentLog.run_reason == run_reason)
        if floor_applied is not None:
            stmt = stmt.where(RelevanceAdjustmentLog.floor_applied == floor_applied)
        if evaluated_after is not None:
            stmt = stmt.where(RelevanceAdjustmentLog.evaluated_at >= evaluated_after)
        result = await session.execute(stmt)
        return int(result.scalar_one() or 0)
    except Exception as exc:
        logger.debug("[user_learning_repo] count_relevance_adjustment_logs failed: %r", exc)
        return 0
