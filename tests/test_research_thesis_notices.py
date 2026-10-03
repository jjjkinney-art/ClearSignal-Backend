"""Account ownership and lifecycle tests for thesis notice records."""

import asyncio
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.models import Base, ResearchConversation, ResearchMessage
from app.services.research_thesis_notices import (
    delete_notice,
    list_notices,
    persist_notice_preview,
    set_notice_status,
)


def _preview(conversation_id: str, message_id: str, **changes):
    value = {
        "preview_version": 1,
        "available": True,
        "delivery_enabled": False,
        "status": "candidate_found",
        "selection": {
            "conversation_id": conversation_id,
            "message_id": message_id,
            "ticker": "AAPL",
            "recorded_at": "2026-09-27T00:00:00Z",
            "historical_only": True,
        },
        "candidates": [{
            "candidate_version": 1,
            "eligible": True,
            "delivery_enabled": False,
            "reason": "new_admitted_related_evidence",
            "ticker": "AAPL",
            "evidence_id": "E1",
            "matched_terms": ["services", "retention"],
        }],
    }
    value.update(changes)
    return value


def test_notice_lifecycle_is_owner_scoped_deduplicated_and_zero_delivery():
    async def scenario():
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        now = datetime.now(timezone.utc)
        async with factory() as session:
            conversation = ResearchConversation(
                id="conversation-a", user_id="owner-a", title="Apple thesis",
                scope_tickers=["AAPL"], created_at=now, updated_at=now,
            )
            message = ResearchMessage(
                id="message-a", conversation_id=conversation.id,
                user_id="owner-a", ordinal=1, role="assistant",
                text="Services retention matters.", displayed_snapshot={},
                created_at=now,
            )
            session.add_all([conversation, message])
            await session.commit()

            first = await persist_notice_preview(
                session, user_id="owner-a",
                preview=_preview(conversation.id, message.id),
            )
            second = await persist_notice_preview(
                session, user_id="owner-a",
                preview=_preview(conversation.id, message.id),
            )
            await session.commit()
            assert first[0]["id"] == second[0]["id"]
            assert first[0]["delivery_enabled"] is False
            assert first[0]["status"] == "unread"
            assert len(await list_notices(session, user_id="owner-a")) == 1
            assert await list_notices(session, user_id="owner-b") == []

            assert await set_notice_status(
                session, user_id="owner-b", notice_id=first[0]["id"], status="read"
            ) is None
            read = await set_notice_status(
                session, user_id="owner-a", notice_id=first[0]["id"], status="read"
            )
            assert read["status"] == "read"
            assert await delete_notice(
                session, user_id="owner-b", notice_id=first[0]["id"]
            ) is False
            assert await delete_notice(
                session, user_id="owner-a", notice_id=first[0]["id"]
            ) is True
            await session.commit()
            assert await list_notices(session, user_id="owner-a") == []
        await engine.dispose()

    asyncio.run(scenario())


def test_notice_persistence_fails_closed_for_unsafe_or_foreign_inputs():
    async def scenario():
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        now = datetime.now(timezone.utc)
        async with factory() as session:
            session.add(ResearchConversation(
                id="conversation-a", user_id="owner-a", title="Apple thesis",
                scope_tickers=["AAPL"], created_at=now, updated_at=now,
            ))
            session.add(ResearchMessage(
                id="message-a", conversation_id="conversation-a",
                user_id="owner-a", ordinal=1, role="assistant", text="Thesis",
                displayed_snapshot={}, created_at=now,
            ))
            await session.commit()

            valid = _preview("conversation-a", "message-a")
            assert await persist_notice_preview(
                session, user_id="owner-b", preview=valid
            ) == []
            assert await persist_notice_preview(
                session, user_id="owner-a",
                preview={**valid, "delivery_enabled": True},
            ) == []
            invalid_candidate = _preview("conversation-a", "message-a")
            invalid_candidate["candidates"][0]["eligible"] = False
            assert await persist_notice_preview(
                session, user_id="owner-a", preview=invalid_candidate
            ) == []

            conversation = await session.get(ResearchConversation, "conversation-a")
            conversation.deleted_at = now
            await session.commit()
            assert await persist_notice_preview(
                session, user_id="owner-a", preview=valid
            ) == []
        await engine.dispose()

    asyncio.run(scenario())
