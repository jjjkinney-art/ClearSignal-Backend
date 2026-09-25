"""Authenticated research cannot read shared, ticker-scoped legacy memory."""

import json
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from starlette.requests import Request


def _request(path, user_id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", method="GET"):
    request = Request({
        "type": "http", "method": method, "path": path, "query_string": b"",
        "headers": [], "client": ("127.0.0.1", 1234), "server": ("test", 80),
        "scheme": "http", "http_version": "1.1",
    })
    request.state.user_id = user_id
    return request


@pytest.mark.parametrize("path", [
    "/history", "/history/summary", "/ticker/AAPL/evolution",
    "/ticker/AAPL/evolution/some-id", "/ticker/AAPL/latest", "/material-changes",
    "/watchlist/AAPL/snapshots", "/watchlist/AAPL/diff",
    "/watchlist/AAPL/changes", "/watchlist/changes/material",
    "/watchlist/themes", "/watchlist/drift", "/watchlist/status",
    "/alerts", "/timeline-events/AAPL", "/alert-priority/AAPL",
    "/events/impact/AAPL", "/events/freshness/AAPL", "/morning-brief/v2",
])
def test_authenticated_shared_research_routes_stop_before_handler(monkeypatch, path):
    from app.config import settings
    from app.security.route_access import enforce_route_access

    monkeypatch.setattr(settings, "auth_enabled", True)
    with pytest.raises(HTTPException) as exc:
        enforce_route_access(_request(path))
    assert exc.value.status_code == 503


def test_shared_acknowledgement_mutation_blocked_but_owned_watchlist_available(monkeypatch):
    from app.config import settings
    from app.security.route_access import enforce_route_access

    monkeypatch.setattr(settings, "auth_enabled", True)
    with pytest.raises(HTTPException) as exc:
        enforce_route_access(_request("/watchlist/AAPL/acknowledge", method="POST"))
    assert exc.value.status_code == 503
    for path in ("/watchlist", "/watchlist/AAPL", "/analyze", "/market/resolve"):
        assert enforce_route_access(_request(path))


def test_legacy_routes_remain_available_in_single_tenant_bypass(monkeypatch):
    from app.config import settings
    from app.security.route_access import enforce_route_access

    monkeypatch.setattr(settings, "auth_enabled", False)
    assert enforce_route_access(_request("/history"))
    assert enforce_route_access(_request("/ticker/AAPL/evolution"))


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


def test_authenticated_pipeline_never_reads_or_writes_global_thesis_history(monkeypatch):
    from app.config import settings
    from app.schemas import (
        CompanyContext, InvestmentThesis, ValuationView, MacroSensitivity,
        RiskProfile, MarketContext, QualityAssessment,
    )
    from app.services.evidence_partitioner import EvidencePartition
    from app.services.router_service import _run_investment_pipeline

    monkeypatch.setattr(settings, "auth_enabled", True)
    thesis = InvestmentThesis(ticker="AAPL", company_name="Apple", bull_thesis="Fresh analysis")
    with patch("app.services.router_service._fmp_provider.fetch_company_evidence", return_value=[]), \
         patch("app.services.router_service._sec_provider.fetch_recent_filings", return_value=[]), \
         patch("app.services.router_service._news_provider.fetch_company_news", return_value=[]), \
         patch("app.services.router_service._news_provider.fetch_macro_news", return_value=[]), \
         patch("app.services.router_service.retrieve_general_finance_evidence", return_value=[]), \
         patch("app.services.router_service.fetch_valuation_ratios", return_value=[]), \
         patch("app.services.router_service.fetch_analyst_estimates", return_value=[]), \
         patch("app.services.router_service.get_profile_for_company", return_value=None), \
         patch("app.services.router_service.partition_evidence", return_value=EvidencePartition(
             valuation=[], macro=[], risk=[], market=[], quality=[])), \
         patch("app.services.router_service.run_valuation_agent", return_value=ValuationView(overall=".")), \
         patch("app.services.router_service.run_investment_macro_agent", return_value=MacroSensitivity(overall=".")), \
         patch("app.services.router_service.run_risk_agent", return_value=RiskProfile(overall=".")), \
         patch("app.services.router_service.run_market_agent", return_value=MarketContext(overall=".")), \
         patch("app.services.router_service.run_quality_agent", return_value=QualityAssessment(overall=".")), \
         patch("app.investment_agents.question_answerer_agent.run_question_answerer", return_value=""), \
         patch("app.services.router_service.synthesize_thesis", return_value=thesis) as synthesis, \
         patch("app.services.router_service.watchlist_service") as shared_store:
        response = _run_investment_pipeline(CompanyContext(ticker="AAPL", company_name="Apple"),
                                            "Tell me about Apple", "scope-test")

    shared_store.get_latest_snapshot.assert_not_called()
    shared_store.process_new_thesis.assert_not_called()
    assert synthesis.call_args.kwargs["prior_snapshot"] is None
    assert response.answer["investment_thesis"]["bull_thesis"] == "Fresh analysis"
