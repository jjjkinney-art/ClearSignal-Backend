"""
Personal Experience repository — Phase 18 · Slice 2.

CRUD for personal_experience_cursor, personal_experience_event,
and personal_brief_snapshot.

All functions accept an AsyncSession as the first positional argument.
Passing None is safe: every function returns an empty/falsy/None value
rather than raising. This mirrors the null-session contract used throughout
every prior phase repo.

No change detection, no scoring, no composition, no delivery logic.
Pure DB access. The experience_* flags are not consulted here; flag checks
belong in the service layer (Phase 18 Slices 3+).

Safety invariants (Phase 18 spec / SP-18):
  - This repo never writes to any source table (forecast_vector,
    similarity_edge, scenario_snapshot, decision_priority, ticker_memory,
    learned_preference, user_signal_event, or any upstream truth table).
    Phase 18 is a pure orchestration sink.
  - personal_experience_event has NO update or delete path in this repo.
    Every call that records an event uses add_experience_event() which
    only INSERTs. This append-only immutability is verified by AST
    inspection in the Slice 18.2 test suite.
  - There is no buy/sell/hold, position_size, target_price, trade,
    execution, recommendation, or any truth-override field on any table
    this repo touches. Rows here describe experience observations only.
  - The repo does not import any write path from forecast_repo,
    decision_repo, scenario_repo, similarity_repo, user_learning_repo,
    or any dossier/memory write module.
"""

from __future__ import annotations

import logging
import uuid as _uuid_mod
from datetime import date, datetime, timezone
from typing import List, Optional

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _new_id() -> str:
    return str(_uuid_mod.uuid4())


# ---------------------------------------------------------------------------
# § PERSONAL EXPERIENCE CURSOR  (upsert / get / list / count)
# ---------------------------------------------------------------------------


async def upsert_experience_cursor(
    session,
    *,
    user_id: str,
    entity_type: str,
    entity_key: str,
    last_seen_at: Optional[datetime] = None,
    last_state_hash: str = "",
    cursor_id: Optional[str] = None,
) -> Optional[object]:
    """Insert or update one PersonalExperienceCursor row.

    Upsert is keyed on (user_id, entity_type, entity_key). On update:
    last_seen_at, last_state_hash, view_count (incremented), and updated_at
    are refreshed. Returns the ORM row, or None when session is None.
    """
    if session is None:
        return None
    try:
        from app.db.models import PersonalExperienceCursor
        from sqlalchemy import select

        stmt = select(PersonalExperienceCursor).where(
            PersonalExperienceCursor.user_id     == user_id,
            PersonalExperienceCursor.entity_type == entity_type,
            PersonalExperienceCursor.entity_key  == entity_key,
        )
        existing = (await session.execute(stmt)).scalar_one_or_none()

        now = _now()
        seen = last_seen_at or now

        if existing is None:
            row = PersonalExperienceCursor(
                id              = cursor_id or _new_id(),
                user_id         = user_id,
                entity_type     = entity_type,
                entity_key      = entity_key,
                last_seen_at    = seen,
                last_state_hash = last_state_hash,
                view_count      = 1,
                created_at      = now,
                updated_at      = now,
            )
            session.add(row)
            await session.flush()
            return row

        existing.last_seen_at    = seen
        existing.last_state_hash = last_state_hash
        existing.view_count      = (existing.view_count or 0) + 1
        existing.updated_at      = now
        await session.flush()
        return existing
    except Exception as exc:
        logger.debug("[personal_experience_repo] upsert_experience_cursor failed: %r", exc)
        return None


async def get_experience_cursor(
    session,
    *,
    user_id: str,
    entity_type: str,
    entity_key: str,
) -> Optional[object]:
    """Return one PersonalExperienceCursor row by its unique key, or None."""
    if session is None:
        return None
    try:
        from app.db.models import PersonalExperienceCursor
        from sqlalchemy import select

        stmt = select(PersonalExperienceCursor).where(
            PersonalExperienceCursor.user_id     == user_id,
            PersonalExperienceCursor.entity_type == entity_type,
            PersonalExperienceCursor.entity_key  == entity_key,
        )
        return (await session.execute(stmt)).scalar_one_or_none()
    except Exception as exc:
        logger.debug("[personal_experience_repo] get_experience_cursor failed: %r", exc)
        return None


async def list_experience_cursors(
    session,
    *,
    user_id: Optional[str] = None,
    entity_type: Optional[str] = None,
    limit: int = 500,
) -> List[object]:
    """Return PersonalExperienceCursor rows matching the given filters.

    All filters are optional. Returns [] when session is None or on error.
    Ordered by last_seen_at descending.
    """
    if session is None:
        return []
    try:
        from app.db.models import PersonalExperienceCursor
        from sqlalchemy import select

        stmt = select(PersonalExperienceCursor)
        if user_id is not None:
            stmt = stmt.where(PersonalExperienceCursor.user_id == user_id)
        if entity_type is not None:
            stmt = stmt.where(PersonalExperienceCursor.entity_type == entity_type)
        stmt = stmt.order_by(PersonalExperienceCursor.last_seen_at.desc()).limit(limit)

        result = await session.execute(stmt)
        return list(result.scalars().all())
    except Exception as exc:
        logger.debug("[personal_experience_repo] list_experience_cursors failed: %r", exc)
        return []


async def count_experience_cursors(
    session,
    *,
    user_id: Optional[str] = None,
    entity_type: Optional[str] = None,
) -> int:
    """Return the count of PersonalExperienceCursor rows matching filters.

    Returns 0 when session is None or on error.
    """
    if session is None:
        return 0
    try:
        from app.db.models import PersonalExperienceCursor
        from sqlalchemy import select, func

        stmt = select(func.count()).select_from(PersonalExperienceCursor)
        if user_id is not None:
            stmt = stmt.where(PersonalExperienceCursor.user_id == user_id)
        if entity_type is not None:
            stmt = stmt.where(PersonalExperienceCursor.entity_type == entity_type)
        result = await session.execute(stmt)
        return int(result.scalar_one() or 0)
    except Exception as exc:
        logger.debug("[personal_experience_repo] count_experience_cursors failed: %r", exc)
        return 0


# ---------------------------------------------------------------------------
# § PERSONAL EXPERIENCE EVENT  (append-only — INSERT / LIST / COUNT)
# ---------------------------------------------------------------------------


async def add_experience_event(
    session,
    *,
    user_id: str,
    surface: str = "",
    item_ref: str = "",
    entity_type: str = "",
    entity_key: str = "",
    experience_score: float = 0.0,
    attention_priority: float = 0.0,
    personal_relevance: float = 0.0,
    recency_score: float = 0.0,
    novelty_score: float = 0.0,
    revisit_score: float = 0.0,
    memory_relevance: float = 0.0,
    portfolio_relevance: float = 0.0,
    explanation_text: str = "",
    explanation_valid: bool = False,
    run_reason: str = "shadow",
    surfaced_at: Optional[datetime] = None,
    event_id: Optional[str] = None,
) -> Optional[object]:
    """Insert one PersonalExperienceEvent row.

    THIS FUNCTION ONLY INSERTS — it never updates or deletes an existing row.
    The append-only immutability is enforced here and verified by AST
    inspection in the test suite.

    Returns the ORM row, or None when session is None.
    """
    if session is None:
        return None
    try:
        from app.db.models import PersonalExperienceEvent

        now = _now()
        row = PersonalExperienceEvent(
            id                  = event_id or _new_id(),
            user_id             = user_id,
            surface             = surface,
            item_ref            = item_ref,
            entity_type         = entity_type,
            entity_key          = entity_key,
            experience_score    = experience_score,
            attention_priority  = attention_priority,
            personal_relevance  = personal_relevance,
            recency_score       = recency_score,
            novelty_score       = novelty_score,
            revisit_score       = revisit_score,
            memory_relevance    = memory_relevance,
            portfolio_relevance = portfolio_relevance,
            explanation_text    = explanation_text,
            explanation_valid   = explanation_valid,
            run_reason          = run_reason,
            surfaced_at         = surfaced_at or now,
            created_at          = now,
        )
        session.add(row)
        await session.flush()
        return row
    except Exception as exc:
        logger.debug("[personal_experience_repo] add_experience_event failed: %r", exc)
        return None


async def list_experience_events(
    session,
    *,
    user_id: Optional[str] = None,
    surface: Optional[str] = None,
    run_reason: Optional[str] = None,
    item_ref: Optional[str] = None,
    explanation_valid: Optional[bool] = None,
    surfaced_after: Optional[datetime] = None,
    limit: int = 500,
) -> List[object]:
    """Return PersonalExperienceEvent rows matching the given filters.

    All filters are optional. Returns [] when session is None or on error.
    Ordered by surfaced_at descending.
    """
    if session is None:
        return []
    try:
        from app.db.models import PersonalExperienceEvent
        from sqlalchemy import select

        stmt = select(PersonalExperienceEvent)
        if user_id is not None:
            stmt = stmt.where(PersonalExperienceEvent.user_id == user_id)
        if surface is not None:
            stmt = stmt.where(PersonalExperienceEvent.surface == surface)
        if run_reason is not None:
            stmt = stmt.where(PersonalExperienceEvent.run_reason == run_reason)
        if item_ref is not None:
            stmt = stmt.where(PersonalExperienceEvent.item_ref == item_ref)
        if explanation_valid is not None:
            stmt = stmt.where(PersonalExperienceEvent.explanation_valid == explanation_valid)
        if surfaced_after is not None:
            stmt = stmt.where(PersonalExperienceEvent.surfaced_at >= surfaced_after)
        stmt = stmt.order_by(PersonalExperienceEvent.surfaced_at.desc()).limit(limit)

        result = await session.execute(stmt)
        return list(result.scalars().all())
    except Exception as exc:
        logger.debug("[personal_experience_repo] list_experience_events failed: %r", exc)
        return []


async def count_experience_events(
    session,
    *,
    user_id: Optional[str] = None,
    surface: Optional[str] = None,
    run_reason: Optional[str] = None,
    explanation_valid: Optional[bool] = None,
    surfaced_after: Optional[datetime] = None,
) -> int:
    """Return the count of PersonalExperienceEvent rows matching filters.

    Returns 0 when session is None or on error.
    """
    if session is None:
        return 0
    try:
        from app.db.models import PersonalExperienceEvent
        from sqlalchemy import select, func

        stmt = select(func.count()).select_from(PersonalExperienceEvent)
        if user_id is not None:
            stmt = stmt.where(PersonalExperienceEvent.user_id == user_id)
        if surface is not None:
            stmt = stmt.where(PersonalExperienceEvent.surface == surface)
        if run_reason is not None:
            stmt = stmt.where(PersonalExperienceEvent.run_reason == run_reason)
        if explanation_valid is not None:
            stmt = stmt.where(PersonalExperienceEvent.explanation_valid == explanation_valid)
        if surfaced_after is not None:
            stmt = stmt.where(PersonalExperienceEvent.surfaced_at >= surfaced_after)
        result = await session.execute(stmt)
        return int(result.scalar_one() or 0)
    except Exception as exc:
        logger.debug("[personal_experience_repo] count_experience_events failed: %r", exc)
        return 0


# ---------------------------------------------------------------------------
# § PERSONAL BRIEF SNAPSHOT  (upsert / get / list / count)
# ---------------------------------------------------------------------------


async def add_brief_snapshot(
    session,
    *,
    user_id: str,
    brief_date: date,
    brief_schema: int = 1,
    items_surfaced: int = 0,
    items_blocked: int = 0,
    top_attention_item: str = "",
    run_reason: str = "shadow",
    generated_at: Optional[datetime] = None,
    snapshot_id: Optional[str] = None,
) -> Optional[object]:
    """Insert one PersonalBriefSnapshot row.

    Does NOT upsert — a second call for the same (user_id, brief_date) will
    fail on the unique constraint. Callers should check with
    get_brief_snapshot first. Returns the ORM row, or None.
    """
    if session is None:
        return None
    try:
        from app.db.models import PersonalBriefSnapshot

        now = _now()
        row = PersonalBriefSnapshot(
            id                 = snapshot_id or _new_id(),
            user_id            = user_id,
            brief_date         = brief_date,
            brief_schema       = brief_schema,
            items_surfaced     = items_surfaced,
            items_blocked      = items_blocked,
            top_attention_item = top_attention_item,
            run_reason         = run_reason,
            generated_at       = generated_at or now,
            created_at         = now,
        )
        session.add(row)
        await session.flush()
        return row
    except Exception as exc:
        logger.debug("[personal_experience_repo] add_brief_snapshot failed: %r", exc)
        return None


async def get_brief_snapshot(
    session,
    *,
    user_id: str,
    brief_date: date,
) -> Optional[object]:
    """Return one PersonalBriefSnapshot row by (user_id, brief_date), or None."""
    if session is None:
        return None
    try:
        from app.db.models import PersonalBriefSnapshot
        from sqlalchemy import select

        stmt = select(PersonalBriefSnapshot).where(
            PersonalBriefSnapshot.user_id    == user_id,
            PersonalBriefSnapshot.brief_date == brief_date,
        )
        return (await session.execute(stmt)).scalar_one_or_none()
    except Exception as exc:
        logger.debug("[personal_experience_repo] get_brief_snapshot failed: %r", exc)
        return None


async def list_brief_snapshots(
    session,
    *,
    user_id: Optional[str] = None,
    run_reason: Optional[str] = None,
    limit: int = 30,
) -> List[object]:
    """Return PersonalBriefSnapshot rows matching the given filters.

    All filters are optional. Returns [] when session is None or on error.
    Ordered by brief_date descending.
    """
    if session is None:
        return []
    try:
        from app.db.models import PersonalBriefSnapshot
        from sqlalchemy import select

        stmt = select(PersonalBriefSnapshot)
        if user_id is not None:
            stmt = stmt.where(PersonalBriefSnapshot.user_id == user_id)
        if run_reason is not None:
            stmt = stmt.where(PersonalBriefSnapshot.run_reason == run_reason)
        stmt = stmt.order_by(PersonalBriefSnapshot.brief_date.desc()).limit(limit)

        result = await session.execute(stmt)
        return list(result.scalars().all())
    except Exception as exc:
        logger.debug("[personal_experience_repo] list_brief_snapshots failed: %r", exc)
        return []


async def count_brief_snapshots(
    session,
    *,
    user_id: Optional[str] = None,
    run_reason: Optional[str] = None,
) -> int:
    """Return the count of PersonalBriefSnapshot rows matching filters.

    Returns 0 when session is None or on error.
    """
    if session is None:
        return 0
    try:
        from app.db.models import PersonalBriefSnapshot
        from sqlalchemy import select, func

        stmt = select(func.count()).select_from(PersonalBriefSnapshot)
        if user_id is not None:
            stmt = stmt.where(PersonalBriefSnapshot.user_id == user_id)
        if run_reason is not None:
            stmt = stmt.where(PersonalBriefSnapshot.run_reason == run_reason)
        result = await session.execute(stmt)
        return int(result.scalar_one() or 0)
    except Exception as exc:
        logger.debug("[personal_experience_repo] count_brief_snapshots failed: %r", exc)
        return 0
