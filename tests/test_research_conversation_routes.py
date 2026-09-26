"""HTTP contract and owner isolation for private research conversations."""

import asyncio
import os
import tempfile
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import ValidationError


def test_research_conversation_routes_are_owner_scoped():
    async def scenario():
        from app.db.connection import close_db, init_db
        from app.db.models import Base
        from app.routers.research_conversations import (
            ConversationCreateRequest,
            UserMessageCreateRequest,
            append_research_user_message,
            create_research_conversation,
            delete_research_conversation,
            get_research_conversation,
            list_research_conversations,
        )
        from sqlalchemy.ext.asyncio import create_async_engine

        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        url = f"sqlite+aiosqlite:///{path}"
        engine = create_async_engine(url)
        try:
            async with engine.begin() as connection:
                await connection.run_sync(Base.metadata.create_all)
            await engine.dispose()
            await init_db(url)

            owner_a = SimpleNamespace(state=SimpleNamespace(user_id="owner-a"))
            owner_b = SimpleNamespace(state=SimpleNamespace(user_id="owner-b"))
            created = await create_research_conversation(
                ConversationCreateRequest(title="Apple regulation", tickers=["aapl", "AAPL"]),
                owner_a,
            )
            assert created["scope"]["tickers"] == ["AAPL"]

            message = await append_research_user_message(
                created["id"],
                UserMessageCreateRequest(
                    text="What was the App Store concern?", request_ref="turn-1"
                ),
                owner_a,
            )
            duplicate = await append_research_user_message(
                created["id"],
                UserMessageCreateRequest(text="Retry", request_ref="turn-1"),
                owner_a,
            )
            assert duplicate["id"] == message["id"]

            listed = await list_research_conversations(
                owner_a, q="App Store", ticker="aapl", created_after=None,
                created_before=None, limit=30,
            )
            assert [item["id"] for item in listed] == [created["id"]]
            assert await list_research_conversations(
                owner_b, q=None, ticker=None, created_after=None,
                created_before=None, limit=30,
            ) == []

            loaded = await get_research_conversation(created["id"], owner_a)
            assert loaded["messages"][0]["role"] == "user"
            with pytest.raises(HTTPException) as hidden:
                await get_research_conversation(created["id"], owner_b)
            assert hidden.value.status_code == 404
            with pytest.raises(HTTPException) as blocked_append:
                await append_research_user_message(
                    created["id"], UserMessageCreateRequest(text="intrude"), owner_b
                )
            assert blocked_append.value.status_code == 404
            with pytest.raises(HTTPException) as blocked_delete:
                await delete_research_conversation(created["id"], owner_b)
            assert blocked_delete.value.status_code == 404

            assert (await delete_research_conversation(created["id"], owner_a))["deleted"]
            with pytest.raises(HTTPException) as gone:
                await get_research_conversation(created["id"], owner_a)
            assert gone.value.status_code == 404
        finally:
            await close_db()
            await engine.dispose()
            os.unlink(path)

    asyncio.run(scenario())


def test_research_conversation_route_validation_and_auth():
    from app.routers.research_conversations import (
        ConversationCreateRequest,
        UserMessageCreateRequest,
        list_research_conversations,
    )

    with pytest.raises(ValidationError):
        ConversationCreateRequest(tickers=["bad ticker"])
    with pytest.raises(ValidationError):
        ConversationCreateRequest(
            scope_started_at="2026-09-26T00:00:00Z",
            scope_ended_at="2026-09-25T00:00:00Z",
        )
    with pytest.raises(ValidationError):
        ConversationCreateRequest(scope_started_at="2026-09-26T00:00:00")
    with pytest.raises(ValidationError):
        UserMessageCreateRequest(text="   ")

    async def unauthenticated():
        request = SimpleNamespace(state=SimpleNamespace(user_id=None))
        with pytest.raises(HTTPException) as denied:
            await list_research_conversations(
                request, q=None, ticker=None, created_after=None,
                created_before=None, limit=30,
            )
        assert denied.value.status_code == 401

    asyncio.run(unauthenticated())


def test_research_conversation_routes_registered():
    from app.main import app

    methods_by_path = {}
    for route in app.routes:
        if route.path.startswith("/research/conversations"):
            methods_by_path.setdefault(route.path, set()).update(route.methods)
    assert methods_by_path["/research/conversations"] >= {"GET", "POST"}
    assert methods_by_path["/research/conversations/{conversation_id}"] >= {"GET", "DELETE"}
    assert methods_by_path["/research/conversations/{conversation_id}/messages"] == {"POST"}
