"""Authenticated research cannot read shared, ticker-scoped legacy memory."""

import json
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from starlette.requests import Request


@pytest.mark.asyncio
async def test_history_routes_refuse_shared_store_when_authenticated(monkeypatch):
    from app.api import get_history, get_history_summary_endpoint
    from app.config import settings
    from app.services import history_service

    monkeypatch.setattr(settings, "auth_enabled", True)
    monkeypatch.setattr(history_service, "get_analysis_history", lambda **kw: pytest.fail("global history read"))
    monkeypatch.setattr(history_service, "get_history_summary", lambda: pytest.fail("global summary read"))
    for endpoint in (get_history, get_history_summary_endpoint):
        with pytest.raises(HTTPException) as exc:
            await endpoint()
        assert exc.value.status_code == 503


@pytest.mark.asyncio
async def test_authenticated_ask_ignores_client_memory_and_never_loads_legacy_memory(monkeypatch):
    from app import api
    from app.config import settings
    from app.schemas import AgentAnswerResponse, QuestionRequest
    from app.db.repositories import memory_retrieval
    from app.db import persistence
    from app.security import ask_guard

    monkeypatch.setattr(settings, "auth_enabled", True)
    monkeypatch.setattr(ask_guard, "enforce_ask_preflight", AsyncMock(return_value="user-a"))
    read = AsyncMock(side_effect=AssertionError("shared memory read"))
    write = AsyncMock(side_effect=AssertionError("unowned legacy write"))
    monkeypatch.setattr(memory_retrieval, "get_memory_context", read)
    monkeypatch.setattr(persistence, "persist_analysis_result", write)

    def answer(question):
        assert question.memory_context_block is None
        assert question.memory_context_data is None
        return AgentAnswerResponse(
            company="AAPL", request_id="boundary-test", agents_used=[],
            routing={"detected_ticker": "AAPL"},
            answer={"investment_thesis": {"ticker": "AAPL", "direct_answer": "No saved context."}},
        )

    monkeypatch.setattr(api, "route_question", answer)
    request = Request({
        "type": "http", "method": "POST", "path": "/ask", "query_string": b"",
        "headers": [], "client": ("127.0.0.1", 1234), "server": ("test", 80),
        "scheme": "http", "http_version": "1.1",
    })
    payload = QuestionRequest(
        company_name="AAPL", question="What changed?",
        memory_context_block="Another user's secret",
        memory_context_data={"ticker": "OTHER"},
    )
    response = await api.ask_question(payload, request)
    raw = b"".join([part async for part in response.body_iterator])
    assert json.loads(raw)["answer"]["investment_thesis"]["direct_answer"] == "No saved context."
    read.assert_not_awaited()
    write.assert_not_awaited()
