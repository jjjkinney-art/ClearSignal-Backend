"""Isolation and lifecycle tests for dark cross-conversation memory storage."""

import asyncio

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.models import Base, ResearchConversation, ResearchMessage
from app.services.research_conversations import (
    append_completed_turn,
    append_message,
    assistant_text_from_response,
    create_conversation,
    get_conversation,
    hard_delete_conversation,
    list_conversations,
    soft_delete_conversation,
)


def test_owned_conversation_crud_search_and_deletion():
    async def scenario():
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with factory() as session:
                a = await create_conversation(
                    session, user_id="owner-a", title="Apple services concern",
                    tickers=["aapl"],
                )
                b = await create_conversation(
                    session, user_id="owner-b", title="Apple services concern",
                    tickers=["AAPL"],
                )
                first = await append_message(
                    session, user_id="owner-a", conversation_id=a["id"], role="user",
                    text="What was the App Store regulation concern?", request_ref="request-1",
                )
                duplicate = await append_message(
                    session, user_id="owner-a", conversation_id=a["id"], role="user",
                    text="Retry text must not replace the original", request_ref="request-1",
                )
                assert duplicate["id"] == first["id"]
                await append_message(
                    session, user_id="owner-a", conversation_id=a["id"], role="assistant",
                    text="The concern was regulatory pressure on App Store economics.",
                    request_ref="request-1", displayed_snapshot={
                        "claims": [{"text": "App Store pressure", "kind": "interpretation"}],
                        "evidence": [], "freshness": "historical", "uncertainty": "material",
                    },
                )
                await append_message(
                    session, user_id="owner-b", conversation_id=b["id"], role="user",
                    text="What was the App Store regulation concern?", request_ref="request-1",
                )
                await session.commit()

            async with factory() as session:
                loaded = await get_conversation(session, user_id="owner-a", conversation_id=a["id"])
                assert loaded and [m["role"] for m in loaded["messages"]] == ["user", "assistant"]
                assert loaded["messages"][1]["snapshot_version"] == 1
                assert await get_conversation(session, user_id="owner-b", conversation_id=a["id"]) is None
                assert await append_message(
                    session, user_id="owner-b", conversation_id=a["id"], role="user", text="intrude",
                ) is None
                assert [item["id"] for item in await list_conversations(
                    session, user_id="owner-a", query="regulatory pressure",
                )] == [a["id"]]
                assert await list_conversations(session, user_id="owner-b", query="regulatory pressure") == []
                assert [item["id"] for item in await list_conversations(
                    session, user_id="owner-a", ticker="AAPL",
                )] == [a["id"]]

                assert not await soft_delete_conversation(
                    session, user_id="owner-b", conversation_id=a["id"],
                )
                assert await soft_delete_conversation(
                    session, user_id="owner-a", conversation_id=a["id"],
                )
                await session.commit()
                assert await get_conversation(session, user_id="owner-a", conversation_id=a["id"]) is None
                assert await list_conversations(session, user_id="owner-a") == []

                assert await hard_delete_conversation(
                    session, user_id="owner-a", conversation_id=a["id"],
                )
                await session.commit()
                assert await session.scalar(select(func.count()).select_from(
                    ResearchConversation).where(ResearchConversation.id == a["id"])) == 0
                assert await session.scalar(select(func.count()).select_from(
                    ResearchMessage).where(ResearchMessage.conversation_id == a["id"])) == 0
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def test_conversation_validation_fails_closed():
    async def scenario():
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with factory() as session:
                with pytest.raises(ValueError):
                    await create_conversation(session, user_id="")
                conversation = await create_conversation(session, user_id="owner")
                with pytest.raises(ValueError):
                    await append_message(
                        session, user_id="owner", conversation_id=conversation["id"],
                        role="tool", text="not allowed",
                    )
                with pytest.raises(ValueError):
                    await append_message(
                        session, user_id="owner", conversation_id=conversation["id"],
                        role="user", text=" ",
                    )
                with pytest.raises(ValueError):
                    await append_message(
                        session, user_id="owner", conversation_id=conversation["id"],
                        role="assistant", text="answer", displayed_snapshot=["not", "an", "object"],
                    )
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def test_completed_turn_uses_exact_emitted_response_and_is_idempotent():
    async def scenario():
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        response = {
            "company": "AAPL",
            "request_id": "request-7",
            "answer": {"investment_thesis": {
                "direct_answer": "Services regulation remains the central concern.",
                "evidence": [{"source": "example", "available": False}],
            }},
            "routing": {"detected_ticker": "AAPL"},
        }
        try:
            async with factory() as session:
                conversation = await create_conversation(
                    session, user_id="owner-a", title="Apple", tickers=["AAPL"]
                )
                assert await append_completed_turn(
                    session, user_id="owner-a", conversation_id=conversation["id"],
                    question="What is the concern?", response=response,
                    request_ref="turn-7",
                )
                assert await append_completed_turn(
                    session, user_id="owner-a", conversation_id=conversation["id"],
                    question="Retry must deduplicate", response=response,
                    request_ref="turn-7",
                )
                await session.commit()

            async with factory() as session:
                loaded = await get_conversation(
                    session, user_id="owner-a", conversation_id=conversation["id"]
                )
                assert [message["role"] for message in loaded["messages"]] == [
                    "user", "assistant"
                ]
                assert loaded["messages"][0]["text"] == "What is the concern?"
                assert loaded["messages"][1]["text"] == (
                    "Services regulation remains the central concern."
                )
                assert loaded["messages"][1]["displayed_snapshot"] == {
                    "response_version": 1,
                    "response": response,
                }
                assert not await append_completed_turn(
                    session, user_id="owner-b", conversation_id=conversation["id"],
                    question="Intrude", response=response, request_ref="foreign",
                )
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def test_assistant_text_falls_back_to_exact_structured_answer():
    assert assistant_text_from_response({"answer": {"bullets": ["One", "Two"]}}) == (
        '{"bullets": ["One", "Two"]}'
    )


def test_question_request_research_references_are_bounded_and_trimmed():
    from pydantic import ValidationError
    from app.schemas import QuestionRequest

    request = QuestionRequest(
        company_name="Apple",
        question="What changed?",
        research_conversation_id="  conversation-1  ",
        research_request_ref="  turn-1  ",
    )
    assert request.research_conversation_id == "conversation-1"
    assert request.research_request_ref == "turn-1"
    with pytest.raises(ValidationError):
        QuestionRequest(
            company_name="Apple", question="What changed?",
            research_conversation_id="   ",
        )
