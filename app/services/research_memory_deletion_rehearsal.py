"""Synthetic, zero-production-write rehearsal for research-memory deletion."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.models import (
    Base,
    ResearchConversation,
    ResearchMessage,
    ResearchPersonalizationProfile,
    ResearchThesisNotice,
)
from app.services.research_conversations import recall_conversations
from app.services.research_export import export_research_memory
from app.services.research_memory_lifecycle import delete_owner_research_memory
from app.services.research_thesis_notices import list_notices


REHEARSAL_SCHEMA_VERSION = 1
_TARGET = "synthetic-deletion-target"
_CONTROL = "synthetic-deletion-control"


def _rows(owner: str, suffix: str, now: datetime):
    conversation = ResearchConversation(
        id=f"synthetic-conversation-{suffix}",
        user_id=owner,
        title="Synthetic Apple services thesis",
        scope_tickers=["AAPL"],
        created_at=now,
        updated_at=now,
    )
    message = ResearchMessage(
        id=f"synthetic-message-{suffix}",
        conversation_id=conversation.id,
        user_id=owner,
        ordinal=1,
        role="assistant",
        text="Synthetic Apple services retention thesis.",
        displayed_snapshot={},
        created_at=now,
    )
    profile = ResearchPersonalizationProfile(
        id=f"synthetic-profile-{suffix}",
        user_id=owner,
        enabled=True,
        response_depth="deep",
        time_horizon="multi_year",
        analysis_emphasis="downside_first",
        evidence_style="primary_sources",
        origin="explicit_user_setting",
        created_at=now,
        updated_at=now,
    )
    notice = ResearchThesisNotice(
        id=f"synthetic-notice-{suffix}",
        user_id=owner,
        conversation_id=conversation.id,
        message_id=message.id,
        ticker="AAPL",
        evidence_id="synthetic-evidence",
        evidence_snapshot={"title": "Synthetic filing"},
        fingerprint=(suffix * 64)[:64],
        matched_terms=["services", "retention"],
        status="unread",
        candidate_version=1,
        preview_version=1,
        delivery_enabled=False,
        detected_at=now,
        updated_at=now,
    )
    return conversation, message, profile, notice


async def _count(session, model, owner: str) -> int:
    return int(await session.scalar(
        select(func.count()).select_from(model).where(model.user_id == owner)
    ) or 0)


async def _owner_counts(session, owner: str) -> dict[str, int]:
    return {
        "conversations": await _count(session, ResearchConversation, owner),
        "messages": await _count(session, ResearchMessage, owner),
        "personalization_profiles": await _count(
            session, ResearchPersonalizationProfile, owner
        ),
        "thesis_notices": await _count(session, ResearchThesisNotice, owner),
    }


async def run_research_memory_deletion_rehearsal() -> dict:
    """Prove scoped purge, retrieval invalidation, and isolation without live writes."""

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    checks: dict[str, bool] = {}
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        async with factory() as session:
            session.add_all(_rows(_TARGET, "a", now))
            session.add_all(_rows(_CONTROL, "b", now))
            await session.commit()

            before = await _owner_counts(session, _TARGET)
            control_before = await _owner_counts(session, _CONTROL)
            export_before = await export_research_memory(session, user_id=_TARGET)

            deleted = await delete_owner_research_memory(session, user_id=_TARGET)
            await session.commit()

            after = await _owner_counts(session, _TARGET)
            control_after = await _owner_counts(session, _CONTROL)
            export_after = await export_research_memory(session, user_id=_TARGET)
            recall_after = await recall_conversations(
                session,
                user_id=_TARGET,
                query="Apple services retention",
            )
            notices_after = await list_notices(session, user_id=_TARGET)
            control_notices = await list_notices(session, user_id=_CONTROL)

            checks = {
                "synthetic_target_seeded": all(value == 1 for value in before.values()),
                "complete_private_research_export_existed": (
                    export_before["conversation_count"] == 1
                    and export_before["message_count"] == 1
                    and export_before["personalization"]["persisted"] is True
                ),
                "all_research_memory_rows_deleted": all(
                    value == 0 for value in after.values()
                ),
                "deleted_counts_match_preview": deleted == before,
                "recall_invalidated": (
                    recall_after["status"] == "unavailable"
                    and recall_after["candidates"] == []
                ),
                "notice_inbox_invalidated": notices_after == [],
                "post_deletion_export_empty": (
                    export_after["conversation_count"] == 0
                    and export_after["message_count"] == 0
                    and export_after["personalization"]["persisted"] is False
                ),
                "foreign_owner_preserved": (
                    control_before == control_after
                    and all(value == 1 for value in control_after.values())
                    and len(control_notices) == 1
                ),
                "production_database_untouched": True,
                "zero_external_side_effects": True,
            }

        return {
            "schema_version": REHEARSAL_SCHEMA_VERSION,
            "passed": all(checks.values()),
            "database_scope": "ephemeral_in_memory",
            "synthetic": True,
            "checks": checks,
            "preview_counts": before,
            "deleted_counts": deleted,
            "remaining_target_counts": after,
            "foreign_owner_preserved": checks["foreign_owner_preserved"],
            "production_database_untouched": True,
        }
    finally:
        await engine.dispose()
