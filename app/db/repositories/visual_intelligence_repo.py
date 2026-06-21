"""
Visual Intelligence repository — Phase 19 · Slice 2.

CRUD for visual_spec_cache, visual_experience_event,
and ai_visual_generation_log.

All functions accept an AsyncSession as the first positional argument.
Passing None is safe: every function returns an empty/falsy/None value
rather than raising. This mirrors the null-session contract used throughout
every prior phase repo.

No visual building, no rendering, no AI generation, no delivery logic.
Pure DB access. The visual_* flags are not consulted here; flag checks
belong in the service layer (Phase 19 Slices 3+).

Safety invariants (Phase 19 spec / SP-19):
  - This repo never writes to any source table (forecast_vector,
    similarity_edge, scenario_snapshot, decision_priority, ticker_memory,
    learned_preference, user_signal_event, personal_experience_cursor,
    personal_experience_event, or any upstream truth table).
    Phase 19 is a pure visualization sink.
  - visual_experience_event has NO update or delete path in this repo.
    Every call that records an event uses add_visual_event() which
    only INSERTs. This append-only immutability is verified by AST
    inspection in the Slice 19.2 test suite.
  - ai_visual_generation_log has NO update or delete path in this repo.
    Every call uses add_ai_visual_log() which only INSERTs.
  - No raw prompt text is stored anywhere. ai_visual_generation_log
    records prompt_hash (SHA-256) only.
  - The repo does not import any write path from forecast_repo,
    decision_repo, scenario_repo, similarity_repo, user_learning_repo,
    personal_experience_repo, or any dossier/memory write module.
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
# § VISUAL SPEC CACHE  (upsert / get / list / count)
# ---------------------------------------------------------------------------


async def upsert_visual_spec(
    session,
    *,
    user_id: str,
    visual_type: str,
    entity_key: str,
    data_hash: str,
    spec_json: str = "",
    rendering_tier: str = "json",
    explanation_valid: bool = False,
    run_reason: str = "shadow",
    expires_at: Optional[datetime] = None,
    spec_id: Optional[str] = None,
) -> Optional[object]:
    """Insert or update one VisualSpecCache row.

    Upsert is keyed on (user_id, visual_type, entity_key, data_hash).
    On update: spec_json, rendering_tier, explanation_valid, run_reason,
    expires_at, and generated_at are refreshed.
    Returns the ORM row, or None when session is None.
    """
    if session is None:
        return None
    try:
        from app.db.models import VisualSpecCache
        from sqlalchemy import select

        stmt = select(VisualSpecCache).where(
            VisualSpecCache.user_id      == user_id,
            VisualSpecCache.visual_type  == visual_type,
            VisualSpecCache.entity_key   == entity_key,
            VisualSpecCache.data_hash    == data_hash,
        )
        existing = (await session.execute(stmt)).scalar_one_or_none()

        now = _now()

        if existing is None:
            row = VisualSpecCache(
                id                = spec_id or _new_id(),
                user_id           = user_id,
                visual_type       = visual_type,
                entity_key        = entity_key,
                data_hash         = data_hash,
                spec_json         = spec_json,
                rendering_tier    = rendering_tier,
                explanation_valid = explanation_valid,
                run_reason        = run_reason,
                generated_at      = now,
                expires_at        = expires_at,
                created_at        = now,
            )
            session.add(row)
            await session.flush()
            return row

        existing.spec_json         = spec_json
        existing.rendering_tier    = rendering_tier
        existing.explanation_valid = explanation_valid
        existing.run_reason        = run_reason
        existing.expires_at        = expires_at
        existing.generated_at      = now
        await session.flush()
        return existing
    except Exception as exc:
        logger.debug("[visual_repo] upsert_visual_spec failed: %r", exc)
        return None


async def get_visual_spec(
    session,
    *,
    user_id: str,
    visual_type: str,
    entity_key: str,
    data_hash: str,
) -> Optional[object]:
    """Return one VisualSpecCache row by its unique key, or None."""
    if session is None:
        return None
    try:
        from app.db.models import VisualSpecCache
        from sqlalchemy import select

        stmt = select(VisualSpecCache).where(
            VisualSpecCache.user_id      == user_id,
            VisualSpecCache.visual_type  == visual_type,
            VisualSpecCache.entity_key   == entity_key,
            VisualSpecCache.data_hash    == data_hash,
        )
        return (await session.execute(stmt)).scalar_one_or_none()
    except Exception as exc:
        logger.debug("[visual_repo] get_visual_spec failed: %r", exc)
        return None


async def list_visual_specs(
    session,
    *,
    user_id: Optional[str] = None,
    visual_type: Optional[str] = None,
    entity_key: Optional[str] = None,
    limit: int = 500,
) -> List[object]:
    """Return VisualSpecCache rows matching filters.

    Ordered by generated_at descending. Returns [] when session is None.
    """
    if session is None:
        return []
    try:
        from app.db.models import VisualSpecCache
        from sqlalchemy import select

        stmt = select(VisualSpecCache)
        if user_id is not None:
            stmt = stmt.where(VisualSpecCache.user_id == user_id)
        if visual_type is not None:
            stmt = stmt.where(VisualSpecCache.visual_type == visual_type)
        if entity_key is not None:
            stmt = stmt.where(VisualSpecCache.entity_key == entity_key)
        stmt = stmt.order_by(VisualSpecCache.generated_at.desc()).limit(limit)

        result = await session.execute(stmt)
        return list(result.scalars().all())
    except Exception as exc:
        logger.debug("[visual_repo] list_visual_specs failed: %r", exc)
        return []


async def count_visual_specs(
    session,
    *,
    user_id: Optional[str] = None,
    visual_type: Optional[str] = None,
) -> int:
    """Return count of VisualSpecCache rows matching filters."""
    if session is None:
        return 0
    try:
        from app.db.models import VisualSpecCache
        from sqlalchemy import select, func

        stmt = select(func.count()).select_from(VisualSpecCache)
        if user_id is not None:
            stmt = stmt.where(VisualSpecCache.user_id == user_id)
        if visual_type is not None:
            stmt = stmt.where(VisualSpecCache.visual_type == visual_type)
        result = await session.execute(stmt)
        return int(result.scalar_one() or 0)
    except Exception as exc:
        logger.debug("[visual_repo] count_visual_specs failed: %r", exc)
        return 0


# ---------------------------------------------------------------------------
# § VISUAL EXPERIENCE EVENT  (append-only — INSERT / LIST / COUNT)
# ---------------------------------------------------------------------------


async def add_visual_event(
    session,
    *,
    user_id: str,
    visual_type: str = "",
    entity_key: str = "",
    rendering_tier: str = "json",
    explanation_valid: bool = False,
    generation_ms: int = 0,
    cache_hit: bool = False,
    blocked_reason: str = "",
    run_reason: str = "shadow",
    surfaced_at: Optional[datetime] = None,
    event_id: Optional[str] = None,
) -> Optional[object]:
    """Insert one VisualExperienceEvent row.

    THIS FUNCTION ONLY INSERTS — it never updates or deletes an existing row.
    The append-only immutability is enforced here and verified by AST
    inspection in the test suite.

    Returns the ORM row, or None when session is None.
    """
    if session is None:
        return None
    try:
        from app.db.models import VisualExperienceEvent

        now = _now()
        row = VisualExperienceEvent(
            id                = event_id or _new_id(),
            user_id           = user_id,
            visual_type       = visual_type,
            entity_key        = entity_key,
            rendering_tier    = rendering_tier,
            explanation_valid = explanation_valid,
            generation_ms     = generation_ms,
            cache_hit         = cache_hit,
            blocked_reason    = blocked_reason,
            run_reason        = run_reason,
            surfaced_at       = surfaced_at or now,
            created_at        = now,
        )
        session.add(row)
        await session.flush()
        return row
    except Exception as exc:
        logger.debug("[visual_repo] add_visual_event failed: %r", exc)
        return None


async def list_visual_events(
    session,
    *,
    user_id: Optional[str] = None,
    visual_type: Optional[str] = None,
    run_reason: Optional[str] = None,
    surfaced_after: Optional[datetime] = None,
    limit: int = 500,
) -> List[object]:
    """Return VisualExperienceEvent rows matching filters.

    Ordered by surfaced_at descending. Returns [] when session is None.
    """
    if session is None:
        return []
    try:
        from app.db.models import VisualExperienceEvent
        from sqlalchemy import select

        stmt = select(VisualExperienceEvent)
        if user_id is not None:
            stmt = stmt.where(VisualExperienceEvent.user_id == user_id)
        if visual_type is not None:
            stmt = stmt.where(VisualExperienceEvent.visual_type == visual_type)
        if run_reason is not None:
            stmt = stmt.where(VisualExperienceEvent.run_reason == run_reason)
        if surfaced_after is not None:
            stmt = stmt.where(VisualExperienceEvent.surfaced_at >= surfaced_after)
        stmt = stmt.order_by(VisualExperienceEvent.surfaced_at.desc()).limit(limit)

        result = await session.execute(stmt)
        return list(result.scalars().all())
    except Exception as exc:
        logger.debug("[visual_repo] list_visual_events failed: %r", exc)
        return []


async def count_visual_events(
    session,
    *,
    user_id: Optional[str] = None,
    visual_type: Optional[str] = None,
    run_reason: Optional[str] = None,
) -> int:
    """Return count of VisualExperienceEvent rows matching filters."""
    if session is None:
        return 0
    try:
        from app.db.models import VisualExperienceEvent
        from sqlalchemy import select, func

        stmt = select(func.count()).select_from(VisualExperienceEvent)
        if user_id is not None:
            stmt = stmt.where(VisualExperienceEvent.user_id == user_id)
        if visual_type is not None:
            stmt = stmt.where(VisualExperienceEvent.visual_type == visual_type)
        if run_reason is not None:
            stmt = stmt.where(VisualExperienceEvent.run_reason == run_reason)
        result = await session.execute(stmt)
        return int(result.scalar_one() or 0)
    except Exception as exc:
        logger.debug("[visual_repo] count_visual_events failed: %r", exc)
        return 0


# ---------------------------------------------------------------------------
# § AI VISUAL GENERATION LOG  (append-only — INSERT / LIST / COUNT)
# ---------------------------------------------------------------------------


async def add_ai_visual_log(
    session,
    *,
    user_id: str,
    visual_type: str = "",
    entity_key: str = "",
    prompt_hash: str = "",
    generation_model: str = "",
    generation_ms: int = 0,
    validation_passed: bool = False,
    validation_reason: str = "",
    banned_phrases_found: str = "",
    run_reason: str = "shadow",
    log_id: Optional[str] = None,
) -> Optional[object]:
    """Insert one AIVisualGenerationLog row.

    THIS FUNCTION ONLY INSERTS — it never updates or deletes an existing row.
    No raw prompt text is stored — only prompt_hash (SHA-256).

    Returns the ORM row, or None when session is None.
    """
    if session is None:
        return None
    try:
        from app.db.models import AIVisualGenerationLog

        now = _now()
        row = AIVisualGenerationLog(
            id                   = log_id or _new_id(),
            user_id              = user_id,
            visual_type          = visual_type,
            entity_key           = entity_key,
            prompt_hash          = prompt_hash,
            generation_model     = generation_model,
            generation_ms        = generation_ms,
            validation_passed    = validation_passed,
            validation_reason    = validation_reason,
            banned_phrases_found = banned_phrases_found,
            run_reason           = run_reason,
            created_at           = now,
        )
        session.add(row)
        await session.flush()
        return row
    except Exception as exc:
        logger.debug("[visual_repo] add_ai_visual_log failed: %r", exc)
        return None


async def list_ai_visual_logs(
    session,
    *,
    user_id: Optional[str] = None,
    visual_type: Optional[str] = None,
    run_reason: Optional[str] = None,
    limit: int = 500,
) -> List[object]:
    """Return AIVisualGenerationLog rows matching filters.

    Ordered by created_at descending. Returns [] when session is None.
    """
    if session is None:
        return []
    try:
        from app.db.models import AIVisualGenerationLog
        from sqlalchemy import select

        stmt = select(AIVisualGenerationLog)
        if user_id is not None:
            stmt = stmt.where(AIVisualGenerationLog.user_id == user_id)
        if visual_type is not None:
            stmt = stmt.where(AIVisualGenerationLog.visual_type == visual_type)
        if run_reason is not None:
            stmt = stmt.where(AIVisualGenerationLog.run_reason == run_reason)
        stmt = stmt.order_by(AIVisualGenerationLog.created_at.desc()).limit(limit)

        result = await session.execute(stmt)
        return list(result.scalars().all())
    except Exception as exc:
        logger.debug("[visual_repo] list_ai_visual_logs failed: %r", exc)
        return []


async def count_ai_visual_logs(
    session,
    *,
    user_id: Optional[str] = None,
    visual_type: Optional[str] = None,
) -> int:
    """Return count of AIVisualGenerationLog rows matching filters."""
    if session is None:
        return 0
    try:
        from app.db.models import AIVisualGenerationLog
        from sqlalchemy import select, func

        stmt = select(func.count()).select_from(AIVisualGenerationLog)
        if user_id is not None:
            stmt = stmt.where(AIVisualGenerationLog.user_id == user_id)
        if visual_type is not None:
            stmt = stmt.where(AIVisualGenerationLog.visual_type == visual_type)
        result = await session.execute(stmt)
        return int(result.scalar_one() or 0)
    except Exception as exc:
        logger.debug("[visual_repo] count_ai_visual_logs failed: %r", exc)
        return 0
