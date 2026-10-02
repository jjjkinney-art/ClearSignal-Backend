"""Acceptance tests for owner-filtered thesis-memory artifact loading."""

import asyncio
import inspect

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.models import Base
from app.services.research_conversations import (
    append_completed_turn,
    append_message,
    create_conversation,
    soft_delete_conversation,
)
from app.services.thesis_memory_store import load_owned_thesis_memory_artifact


def _response(ticker: str = "AAPL") -> dict:
    return {
        "routing": {"detected_ticker": ticker},
        "answer": {
            "investment_thesis": {
                "direct_answer": "Services durability is the historical thesis.",
                "key_risks": ["Regulatory pressure"],
                "what_to_monitor": ["Services revenue growth"],
                "invalidation_conditions": ["Services growth materially decelerates"],
                "confidence_score": 61,
                "evidence": [{
                    "evidence_id": "E1",
                    "url": "https://www.sec.gov/example",
                    "freshness": "current",
                }],
            }
        },
    }


def test_loader_is_owner_scoped_ticker_scoped_and_deletion_aware():
    async def scenario():
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with factory() as session:
                conversation = await create_conversation(
                    session,
                    user_id="owner-a",
                    title="Apple thesis",
                    tickers=["AAPL"],
                )
                assert await append_completed_turn(
                    session,
                    user_id="owner-a",
                    conversation_id=conversation["id"],
                    question="What is the thesis?",
                    response=_response(),
                    request_ref="turn-1",
                )
                await session.commit()

            async with factory() as session:
                loaded = await load_owned_thesis_memory_artifact(
                    session,
                    user_id="owner-a",
                    conversation_id=conversation["id"],
                    target_ticker="AAPL",
                )
                assert loaded["applied"] is True
                assert loaded["artifact"]["ticker"] == "AAPL"
                assert loaded["artifact"]["historical_only"] is True
                assert loaded["artifact"]["requires_fresh_evidence"] is True
                assert loaded["artifact"]["thesis"]["key_risks"] == [
                    "Regulatory pressure"
                ]
                assert loaded["artifact"]["evidence_references"][0][
                    "evidence_id"
                ] == "E1"

                assert await load_owned_thesis_memory_artifact(
                    session,
                    user_id="owner-b",
                    conversation_id=conversation["id"],
                    target_ticker="AAPL",
                ) == {
                    "applied": False,
                    "status": "unavailable",
                    "historical_only": True,
                    "requires_fresh_evidence": True,
                }
                assert await load_owned_thesis_memory_artifact(
                    session,
                    user_id="owner-a",
                    conversation_id=conversation["id"],
                    target_ticker="MSFT",
                ) == {
                    "applied": False,
                    "status": "ticker_mismatch",
                    "historical_only": True,
                    "requires_fresh_evidence": True,
                }

                assert await soft_delete_conversation(
                    session,
                    user_id="owner-a",
                    conversation_id=conversation["id"],
                )
                await session.commit()
                after_delete = await load_owned_thesis_memory_artifact(
                    session,
                    user_id="owner-a",
                    conversation_id=conversation["id"],
                    target_ticker="AAPL",
                )
                assert after_delete["status"] == "unavailable"
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def test_loader_skips_legacy_messages_without_artifacts_and_mismatched_payloads():
    async def scenario():
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with factory() as session:
                conversation = await create_conversation(
                    session,
                    user_id="owner",
                    tickers=["AAPL"],
                )
                await append_message(
                    session,
                    user_id="owner",
                    conversation_id=conversation["id"],
                    role="assistant",
                    text="Legacy raw text must never become an artifact.",
                    displayed_snapshot={"response": _response()},
                )
                await append_message(
                    session,
                    user_id="owner",
                    conversation_id=conversation["id"],
                    role="assistant",
                    text="A mismatched artifact must fail closed.",
                    displayed_snapshot={
                        "response": _response("MSFT"),
                        "thesis_memory_artifact": {
                            "artifact_version": 1,
                            "status": "available",
                            "historical_only": True,
                            "requires_fresh_evidence": True,
                        },
                    },
                )
                await session.commit()

            async with factory() as session:
                result = await load_owned_thesis_memory_artifact(
                    session,
                    user_id="owner",
                    conversation_id=conversation["id"],
                    target_ticker="AAPL",
                )
                assert result == {
                    "applied": False,
                    "status": "no_artifact",
                    "historical_only": True,
                    "requires_fresh_evidence": True,
                }
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def test_loader_never_reads_raw_message_text():
    source = inspect.getsource(load_owned_thesis_memory_artifact)
    assert ".text" not in source
