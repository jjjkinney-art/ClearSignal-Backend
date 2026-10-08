"""Company scope follows owned server snapshots, never transcript guesses."""

import asyncio

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.models import Base
from app.services.research_conversations import (
    append_completed_turn, append_message, completed_response_ticker,
    create_conversation, get_conversation, list_conversations, recall_conversations,
    soft_delete_conversation,
)
from app.services.research_memory_context import load_selected_research_context


def response(ticker="AAPL", text="Apple Services historical concern", **routing):
    return {
        "answer": {"investment_thesis": {"direct_answer": text}},
        "routing": {"pipeline": "investment_thesis", "detected_ticker": ticker, **routing},
    }


@pytest.mark.parametrize("value", [
    {}, {"answer": "Apple"},
    response(None), response("AAPL", detected_tickers=["AAPL", "MSFT"]),
    response("AAPL", pipeline="comparative_ranking"),
    {**response(), "ticker": "MSFT"}, response("AAPL,MSFT"),
])
def test_ambiguous_or_unstructured_response_has_no_scope(value):
    assert completed_response_ticker(value) == ""


def test_structured_issuer_normalization():
    assert completed_response_ticker(response(" aapl ")) == "AAPL"
    assert completed_response_ticker(response("BRK.B")) == "BRK.B"


def test_automatic_scope_survives_reopen_recall_selection_and_owner_boundaries():
    async def scenario():
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with factory() as session:
                saved = await create_conversation(session, user_id="owner-a", title="Services concern")
                assert await append_completed_turn(
                    session, user_id="owner-a", conversation_id=saved["id"],
                    question="Apple Services risk?", response=response(), request_ref="one",
                )
                # A retry cannot change the saved issuer or thesis.
                await append_completed_turn(
                    session, user_id="owner-a", conversation_id=saved["id"],
                    question="Microsoft retry", response=response("MSFT"), request_ref="one",
                )
                await session.commit()
            async with factory() as session:
                loaded = await get_conversation(session, user_id="owner-a", conversation_id=saved["id"])
                assert loaded["scope"]["tickers"] == ["AAPL"]
                assert len(loaded["messages"]) == 2
                listed = await list_conversations(session, user_id="owner-a", ticker="AAPL")
                assert listed[0]["id"] == saved["id"]
                recalled = await recall_conversations(session, user_id="owner-a", query="Services concern", ticker="AAPL")
                assert recalled["candidates"][0]["conversation"]["scope"]["tickers"] == ["AAPL"]
                applied = await load_selected_research_context(
                    session, user_id="owner-a", conversation_id=saved["id"], target_ticker="AAPL",
                )
                assert applied["applied"] is True
                assert applied["historical_thesis"]["direct_answer"] == "Apple Services historical concern"
                assert not await append_completed_turn(
                    session, user_id="owner-b", conversation_id=saved["id"],
                    question="intrude", response=response("MSFT"),
                )
                assert (await load_selected_research_context(
                    session, user_id="owner-b", conversation_id=saved["id"], target_ticker="AAPL",
                ))["status"] == "unavailable"
                assert (await load_selected_research_context(
                    session, user_id="owner-a", conversation_id=saved["id"], target_ticker="MSFT",
                ))["status"] == "ticker_mismatch"
                await soft_delete_conversation(session, user_id="owner-a", conversation_id=saved["id"])
                assert not await append_completed_turn(
                    session, user_id="owner-a", conversation_id=saved["id"],
                    question="deleted", response=response(),
                )
        finally:
            await engine.dispose()
    asyncio.run(scenario())


def test_explicit_scope_ignores_other_issuer_and_unattributed_multi_scope_snapshots():
    async def scenario():
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with factory() as session:
                saved = await create_conversation(session, user_id="owner", tickers=["AAPL"])
                for ticker in ("AAPL", "MSFT"):
                    await append_completed_turn(
                        session, user_id="owner", conversation_id=saved["id"],
                        question="risk?", response=response(ticker, text=f"{ticker} prior"),
                    )
                loaded = await get_conversation(session, user_id="owner", conversation_id=saved["id"])
                assert loaded["scope"]["tickers"] == ["AAPL"]
                context = await load_selected_research_context(
                    session, user_id="owner", conversation_id=saved["id"], target_ticker="AAPL",
                )
                assert context["historical_thesis"]["direct_answer"] == "AAPL prior"
                multi = await create_conversation(session, user_id="owner", tickers=["AAPL", "MSFT"])
                await append_message(
                    session, user_id="owner", conversation_id=multi["id"], role="assistant",
                    text="ambiguous", displayed_snapshot={"response": response(None)},
                )
                context = await load_selected_research_context(
                    session, user_id="owner", conversation_id=multi["id"], target_ticker="AAPL",
                )
                assert context["status"] == "no_structured_snapshot"
                empty = await create_conversation(session, user_id="owner")
                await append_message(
                    session, user_id="owner", conversation_id=empty["id"], role="user",
                    text="Apple AAPL", displayed_snapshot={"response": response()},
                )
                assert (await get_conversation(
                    session, user_id="owner", conversation_id=empty["id"],
                ))["scope"]["tickers"] == []
        finally:
            await engine.dispose()
    asyncio.run(scenario())
