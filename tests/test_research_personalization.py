"""Explicit Intelligence profile ownership, lifecycle, and prompt boundary."""

import asyncio
import inspect
import os
import tempfile
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import ValidationError


def test_personalization_profile_is_explicit_owner_scoped_and_deletable():
    async def scenario():
        from app.db.connection import close_db, init_db
        from app.db.models import Base
        from app.routers.research_personalization import (
            PersonalizationProfileRequest,
            delete_research_personalization,
            get_research_personalization,
            put_research_personalization,
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

            default = await get_research_personalization(owner_a)
            assert default == {
                "enabled": False,
                "response_depth": "balanced",
                "time_horizon": "mixed",
                "analysis_emphasis": "balanced",
                "evidence_style": "primary_sources",
                "persisted": False,
                "origin": None,
                "created_at": None,
                "updated_at": None,
            }

            saved_a = await put_research_personalization(
                PersonalizationProfileRequest(
                    enabled=True,
                    response_depth="deep",
                    time_horizon="multi_year",
                    analysis_emphasis="downside_first",
                    evidence_style="primary_sources",
                ),
                owner_a,
            )
            assert saved_a["enabled"] is True
            assert saved_a["persisted"] is True
            assert saved_a["origin"] == "explicit_user_setting"
            assert saved_a["created_at"]
            assert saved_a["updated_at"]

            assert (await get_research_personalization(owner_b))["persisted"] is False
            await put_research_personalization(
                PersonalizationProfileRequest(
                    enabled=True,
                    response_depth="concise",
                    time_horizon="near_term",
                    analysis_emphasis="opportunity_first",
                    evidence_style="balanced_sources",
                ),
                owner_b,
            )
            assert (await get_research_personalization(owner_a))["response_depth"] == "deep"

            assert (await delete_research_personalization(owner_a)) == {"deleted": True}
            assert (await get_research_personalization(owner_a))["persisted"] is False
            assert (await get_research_personalization(owner_b))["persisted"] is True
            assert (await delete_research_personalization(owner_a)) == {"deleted": False}
        finally:
            await close_db()
            await engine.dispose()
            os.unlink(path)

    asyncio.run(scenario())


def test_personalization_validation_auth_and_registration():
    from app.main import app
    from app.routers.research_personalization import (
        PersonalizationProfileRequest,
        get_research_personalization,
    )

    with pytest.raises(ValidationError):
        PersonalizationProfileRequest(response_depth="unbounded")
    with pytest.raises(ValidationError):
        PersonalizationProfileRequest(time_horizon="forever")
    with pytest.raises(ValidationError):
        PersonalizationProfileRequest(analysis_emphasis="guaranteed_returns")

    async def unauthenticated():
        request = SimpleNamespace(state=SimpleNamespace(user_id=None))
        with pytest.raises(HTTPException) as denied:
            await get_research_personalization(request)
        assert denied.value.status_code == 401

    asyncio.run(unauthenticated())

    methods = set()
    for route in app.routes:
        if route.path == "/research/personalization":
            methods.update(route.methods)
    assert methods >= {"GET", "PUT", "DELETE"}


def test_personalization_service_does_not_read_transcripts_or_build_prompts():
    from app.services import research_personalization

    source = inspect.getsource(research_personalization)
    assert "ResearchMessage" not in source
    assert "ResearchConversation" not in source
    assert "route_question" not in source
    assert "prompt" not in source.lower().replace("model prompt context", "")
