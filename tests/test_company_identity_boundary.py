"""Exact issuer scope, SEC discovery, unavailable identities and saved gaps."""
from types import SimpleNamespace

import pytest

from app.schemas import AgentAnswerResponse, AnalysisRequest, GeneralFinanceAnswer, QuestionRequest
from app.services import issuer_identity as identity, router_service
from app.services.company_detection import resolve_selected_company, resolve_entity
from app.services.entity_resolution_service import resolve_for_analysis
from app.services.research_conversations import assistant_text_from_response


@pytest.fixture
def directory(monkeypatch):
    data = {"0": {"ticker": "WDFC", "cik_str": 105132, "title": "WD-40 CO"},
            "1": {"ticker": "CLASS-A", "cik_str": 12345, "title": "Example Class Corp"},
            "2": {"ticker": "CLASS-B", "cik_str": 12345, "title": "Example Class Corp"}}
    parsed = identity.parse_directory(data)
    monkeypatch.setattr(identity, "_load_directory", lambda: parsed)
    return parsed


@pytest.mark.parametrize("name,ticker", [
    ("MAN", "MAN"), ("man", "MAN"), ("ManpowerGroup", "MAN"),
    ("AA", "AA"), ("Alcoa", "AA"), ("Acadia Healthcare", "ACHC"),
    ("ACM Research", "ACMR"), ("$MAN", "MAN"), ("BRK-B", "BRK.B")])
def test_benchmark_and_class_selections_resolve_exactly(name, ticker):
    assert resolve_selected_company(name).ticker == ticker


@pytest.mark.parametrize("ticker", ["MNA", "ZZZZZ", "MCSFT"])
def test_unknown_uppercase_security_is_not_fuzzy_substituted(ticker):
    assert resolve_entity(ticker).context is None
    assert resolve_selected_company(ticker) is None


@pytest.mark.parametrize("value", ["WDFC", "wdfc", "WD-40 CO", "WD-40"])
def test_official_directory_supports_exact_issuer_outside_static_registry(directory, value):
    assert identity.discover_company(value).ticker == "WDFC"


def test_official_directory_preserves_class_and_withholds_ambiguous_name(directory):
    assert identity.discover_company("class-a").ticker == "CLASS.A"
    assert identity.discover_company("Example Class Corp") is None


def test_official_directory_never_infers_historical_identity(directory):
    assert identity.discover_company("WDFC", as_of="2010-01-01") is None


def test_official_free_text_requires_unambiguous_exact_issuer(directory):
    assert identity.discover_company("What evidence identifies risks at WD-40?", question_text=True).ticker == "WDFC"
    assert identity.discover_company("WDFC versus CLASS-A", question_text=True) is None
    assert identity.discover_company("Example Class", question_text=True) is None


def test_directory_rejects_conflicting_symbols_and_malformed_ciks():
    directory = identity.parse_directory({
        "0": {"ticker": "XX-A", "cik_str": 123, "title": "First Corp"},
        "1": {"ticker": "XX.A", "cik_str": 456, "title": "Second Corp"},
        "2": {"ticker": "BAD", "cik_str": True, "title": "Bad Corp"},
        "3": {"ticker": "URL", "cik_str": "https://example.test", "title": "Bad Corp"}})
    assert directory.symbols == {}


def test_expired_directory_unavailable_does_not_reuse_stale_identity(monkeypatch):
    monkeypatch.setattr(identity, "_cache", identity.parse_directory({
        "0": {"ticker": "WDFC", "cik_str": 105132, "title": "WD-40 CO"}}))
    monkeypatch.setattr(identity, "_expires_at", 0)
    monkeypatch.setattr(identity, "_retry_at", 0)
    calls = []
    def unavailable():
        calls.append(1)
        raise TimeoutError()
    monkeypatch.setattr(identity, "_fetch_directory_json", unavailable)
    assert identity.discover_company("WDFC") is None
    assert identity.discover_company("WDFC") is None
    assert len(calls) == 1  # Retry backoff avoids stampeding an unavailable feed.


@pytest.mark.parametrize("question", ["What source supports Microsoft?", "Compare Microsoft vs Apple", "What is its outlook?"])
def test_unknown_selection_cannot_be_overridden_by_peer_or_legacy(monkeypatch, question):
    monkeypatch.setattr(identity, "_load_directory", lambda: identity.Directory({}, {}))
    def forbidden(*a, **k):
        pytest.fail("Unresolved selection must stop before research or other-issuer analysis")
    monkeypatch.setattr(router_service, "_run_investment_pipeline", forbidden)
    monkeypatch.setattr(router_service, "enrich_grounding_context", forbidden)
    response = router_service.route_question(QuestionRequest(company_name="MNA", question=question))
    assert response.routing["pipeline"] == "company_identity_clarification"
    assert response.company == "MNA"
    assert response.answer["source_answer"]["claims"] == []
    assert not assistant_text_from_response(response.model_dump()).startswith("{")


@pytest.mark.parametrize("selected", ["WDFC", "WD-40 CO", ""])
def test_official_directory_handoff_reaches_public_router(monkeypatch, directory, selected):
    monkeypatch.setattr(router_service, "_run_investment_pipeline", lambda **k:
        AgentAnswerResponse(company=k["company"].ticker, request_id="test", agents_used=[], answer={}))
    response = router_service.route_question(QuestionRequest(company_name=selected,
        question="What current public evidence identifies risks at WD-40?", intent="company_analysis"))
    assert response.company == "WDFC"


def test_non_company_intent_keeps_general_route_and_skips_discovery(monkeypatch):
    monkeypatch.setattr(identity, "_load_directory", lambda: pytest.fail("No issuer lookup for general intent"))
    monkeypatch.setattr(router_service, "run_general_finance_agent", lambda **k:
        GeneralFinanceAnswer(answer="Interest rates influence financing costs, discount rates, and broad asset valuations."))
    response = router_service.route_question(QuestionRequest(company_name="ZZZZZ",
        question="How do interest rates affect markets?", intent="market_question"))
    assert response.routing["pipeline"] == "general_finance"


def test_analysis_selection_does_not_fall_back_to_a_peer(monkeypatch):
    monkeypatch.setattr(identity, "_load_directory", lambda: identity.Directory({}, {}))
    result = resolve_for_analysis(user_question="What is Microsoft's outlook?", company_hint="ZZZZZ")
    assert result.needs_clarification and not result.canonical_ticker


def test_analyze_service_stops_before_agents_for_unknown_company(monkeypatch):
    from app.services import analysis_service
    monkeypatch.setattr(identity, "_load_directory", lambda: identity.Directory({}, {}))
    monkeypatch.setattr(analysis_service, "enrich_grounding_context", lambda *a, **k:
                        pytest.fail("No grounding for unresolved company"))
    with pytest.raises(identity.CompanyIdentityError):
        analysis_service.analyze_company(AnalysisRequest(company_name="ZZZZZ", user_question="Microsoft risks?"))


def test_saved_general_gap_uses_exact_visible_answer():
    response = {"answer": {"general": {"answer": "Please select an exact company.", "bullets": ["MAN"]}}}
    assert assistant_text_from_response(response) == "Please select an exact company."


@pytest.mark.parametrize("value", ["What is Apple outlook?", "Research Microsoft", "ManpowerGroup risks"])
def test_structured_selection_does_not_strip_question_words(value):
    assert resolve_selected_company(value) is None


def test_analyze_api_returns_identity_clarification_without_server_error(monkeypatch):
    import asyncio
    from fastapi import HTTPException
    from app import api
    from starlette.requests import Request
    monkeypatch.setattr(api, "_extract_scope", lambda request: None)
    def unavailable(*args, **kwargs):
        raise identity.CompanyIdentityError("Enter an exact ticker; no analysis was run.")
    monkeypatch.setattr(api, "analyze_company", unavailable)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(api.analyze(AnalysisRequest(company_name="ZZZZZ"), Request({"type": "http"})))
    assert exc.value.status_code == 422
    assert "no analysis was run" in exc.value.detail


def test_official_legal_name_does_not_select_ticker_embedded_in_name(monkeypatch):
    parsed = identity.parse_directory({
        "0": {"ticker": "WDFC", "cik_str": 105132, "title": "WD 40 CO"},
        "1": {"ticker": "WD", "cik_str": 1497770, "title": "Walker & Dunlop, Inc."}})
    monkeypatch.setattr(identity, "_load_directory", lambda: parsed)
    assert identity.discover_company("What public evidence identifies risks at WD 40 CO?", question_text=True).ticker == "WDFC"
    assert identity.discover_company("Compare WD 40 CO with WD", question_text=True) is None
