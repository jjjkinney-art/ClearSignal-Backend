"""Protected HTTP contract for the account-owned thesis notice inbox."""

import asyncio
import os
import tempfile
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import create_async_engine


def test_notice_routes_are_registered_and_do_not_expose_a_create_endpoint():
    from app.main import app

    methods = {}
    for route in app.routes:
        if route.path.startswith("/research/notices"):
            methods.setdefault(route.path, set()).update(route.methods)
    assert methods["/research/notices"] == {"GET"}
    assert methods["/research/notices/{notice_id}"] == {"GET", "PATCH", "DELETE"}


def test_notice_routes_enforce_owner_lifecycle():
    async def scenario():
        from app.db.connection import close_db, init_db
        from app.db.models import Base, ResearchConversation, ResearchMessage
        from app.routers.research_thesis_notices import (
            NoticeStatusRequest,
            delete_research_thesis_notice,
            get_research_thesis_notice,
            list_research_thesis_notices,
            update_research_thesis_notice,
        )
        from app.services.research_thesis_notices import persist_notice_preview
        from app.db.connection import get_session_factory

        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        url = f"sqlite+aiosqlite:///{path}"
        engine = create_async_engine(url)
        try:
            async with engine.begin() as connection:
                await connection.run_sync(Base.metadata.create_all)
            await engine.dispose()
            await init_db(url)
            now = datetime.now(timezone.utc)
            factory = get_session_factory()
            async with factory() as session:
                session.add(ResearchConversation(
                    id="conversation-a", user_id="owner-a", title="Apple",
                    scope_tickers=["AAPL"], created_at=now, updated_at=now,
                ))
                session.add(ResearchMessage(
                    id="message-a", conversation_id="conversation-a",
                    user_id="owner-a", ordinal=1, role="assistant", text="Thesis",
                    displayed_snapshot={}, created_at=now,
                ))
                await session.commit()
                saved = await persist_notice_preview(session, user_id="owner-a", preview={
                    "preview_version": 1, "available": True,
                    "delivery_enabled": False, "status": "candidate_found",
                    "selection": {"conversation_id": "conversation-a",
                                  "message_id": "message-a", "ticker": "AAPL",
                                  "recorded_at": "2026-09-27T00:00:00Z"},
                    "candidates": [{"candidate_version": 1, "eligible": True,
                                    "delivery_enabled": False, "ticker": "AAPL",
                                    "reason": "new_admitted_related_evidence",
                                    "evidence_id": "E1", "matched_terms": ["margin"],
                                    "evidence": {"title": "Margin filing",
                                                 "source": "SEC EDGAR",
                                                 "published_at": "2026-10-01"}}],
                })
                await session.commit()

            owner = SimpleNamespace(state=SimpleNamespace(user_id="owner-a"))
            stranger = SimpleNamespace(state=SimpleNamespace(user_id="owner-b"))
            listed = await list_research_thesis_notices(
                owner, status=None, ticker=None, limit=50,
            )
            assert [item["id"] for item in listed] == [saved[0]["id"]]
            detail = await get_research_thesis_notice(saved[0]["id"], owner)
            assert detail["trigger"]["title"] == "Margin filing"
            with pytest.raises(HTTPException) as hidden_detail:
                await get_research_thesis_notice(saved[0]["id"], stranger)
            assert hidden_detail.value.status_code == 404
            assert await list_research_thesis_notices(
                stranger, status=None, ticker=None, limit=50,
            ) == []
            with pytest.raises(HTTPException) as hidden:
                await update_research_thesis_notice(
                    saved[0]["id"], NoticeStatusRequest(status="read"), stranger,
                )
            assert hidden.value.status_code == 404
            changed = await update_research_thesis_notice(
                saved[0]["id"], NoticeStatusRequest(status="dismissed"), owner,
            )
            assert changed["status"] == "dismissed"
            with pytest.raises(HTTPException) as hidden_delete:
                await delete_research_thesis_notice(saved[0]["id"], stranger)
            assert hidden_delete.value.status_code == 404
            assert (await delete_research_thesis_notice(
                saved[0]["id"], owner
            ))["deleted"] is True
        finally:
            await close_db()
            await engine.dispose()
            os.unlink(path)

    asyncio.run(scenario())
