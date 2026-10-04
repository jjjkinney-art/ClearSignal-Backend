"""Complete owner isolation and HTTP contract for research-memory export."""

import asyncio
import json
import os
import tempfile
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.models import Base
from app.services.research_conversations import (
    append_message,
    create_conversation,
    soft_delete_conversation,
)
from app.services.research_export import export_research_memory
from app.services.research_personalization import upsert_profile


def test_research_export_is_complete_and_owner_scoped():
    async def scenario():
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with factory() as session:
                owned = await create_conversation(
                    session,
                    user_id="owner-a",
                    title="Apple services",
                    tickers=["AAPL"],
                )
                foreign = await create_conversation(
                    session,
                    user_id="owner-b",
                    title="Private Microsoft work",
                    tickers=["MSFT"],
                )
                await append_message(
                    session,
                    user_id="owner-a",
                    conversation_id=owned["id"],
                    role="user",
                    text="What matters to my Apple thesis?",
                )
                await append_message(
                    session,
                    user_id="owner-b",
                    conversation_id=foreign["id"],
                    role="user",
                    text="Foreign secret",
                )
                await upsert_profile(
                    session,
                    user_id="owner-a",
                    enabled=True,
                    response_depth="deep",
                    time_horizon="multi_year",
                    analysis_emphasis="downside_first",
                    evidence_style="primary_sources",
                )
                assert await soft_delete_conversation(
                    session,
                    user_id="owner-a",
                    conversation_id=owned["id"],
                )
                await session.commit()

            async with factory() as session:
                result = await export_research_memory(session, user_id="owner-a")
                assert result["schema_version"] == 1
                assert result["owner_scope"] == "authenticated_account"
                assert result["includes_hidden_conversations"] is True
                assert result["conversation_count"] == 1
                assert result["message_count"] == 1
                assert result["conversations"][0]["id"] == owned["id"]
                assert result["conversations"][0]["deleted_at"] is not None
                assert result["conversations"][0]["messages"][0]["text"] == (
                    "What matters to my Apple thesis?"
                )
                serialized = json.dumps(result)
                assert "Private Microsoft work" not in serialized
                assert "Foreign secret" not in serialized
                assert result["personalization"]["enabled"] is True
                assert result["personalization"]["response_depth"] == "deep"
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def test_research_export_route_is_authenticated_and_downloadable():
    async def scenario():
        from app.db.connection import close_db, init_db
        from app.routers.research_export import export_research_memory as route

        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        url = f"sqlite+aiosqlite:///{path}"
        engine = create_async_engine(url)
        try:
            async with engine.begin() as connection:
                await connection.run_sync(Base.metadata.create_all)
            await engine.dispose()
            await init_db(url)

            response = await route(
                SimpleNamespace(state=SimpleNamespace(user_id="owner-a"))
            )
            assert response.status_code == 200
            assert response.headers["cache-control"] == "private, no-store"
            assert "attachment" in response.headers["content-disposition"]
            assert json.loads(response.body)["conversation_count"] == 0

            with pytest.raises(HTTPException) as denied:
                await route(SimpleNamespace(state=SimpleNamespace(user_id=None)))
            assert denied.value.status_code == 401
        finally:
            await close_db()
            await engine.dispose()
            os.unlink(path)

    asyncio.run(scenario())


def test_research_export_route_is_registered():
    from app.main import app

    methods_by_path = {
        route.path: route.methods
        for route in app.routes
        if route.path == "/research/export"
    }
    assert methods_by_path["/research/export"] == {"GET"}
