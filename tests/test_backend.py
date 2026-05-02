"""
Improved tests for the AI analyst backend.

These tests verify core reliability behaviors of the backend, including
classification accuracy, structured output fallbacks, selective agent
execution, and correct assembly of analysis responses.  The tests
exercise the service layer directly rather than the HTTP API where
appropriate to avoid unnecessary FastAPI dependencies and to focus on
internal logic.

Test cases use monkeypatching to replace model calls and agent
execution with deterministic stubs.  This allows the tests to run
offline without hitting the OpenAI API and to simulate error cases
such as malformed model output.
"""

import os
import sys
import json
from typing import Any, Dict, List

import pytest

# Ensure that the project root is on the import path so that ``import app``
# resolves correctly when tests are run from within the ``tests`` folder or
# via ``pytest`` from the project root.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.schemas import (
    EquityAnalysis,
    MacroAnalysis,
    OpportunityAnalysis,
    ResearchAnalysis,
    EducationAnalysis,
    AccountingAnalysis,
    SynthesisOutput,
    AnalysisRequest,
)
from app.services.router_service import classify_question
from app.services.context_service import enrich_grounding_context
from app.services import analysis_service as asvc
from app.structured_output import get_structured_response


def test_classify_question_multiple() -> None:
    """Classification should return structured metadata with multiple agents in order."""
    text = "What are the macro environment and emerging opportunities for Tesla?"
    result = classify_question(text)
    # Macro appears first in the keyword map, followed by opportunity
    assert result["selected_agents"] == ["macro", "opportunity"]
    # Confidence should be greater than zero when at least one agent matches
    assert 0.0 < result["confidence"] <= 1.0
    # Reasons should include entries for both selected and skipped agents
    assert "macro" in result["reasons"]
    assert "opportunity" in result["reasons"]


def test_classify_question_default() -> None:
    """When no keywords match, the equity agent should be selected by default and metadata included."""
    text = "Tell me something general about Tesla"
    result = classify_question(text)
    assert result["selected_agents"] == ["equity"]
    assert "equity" in result["reasons"]
    assert 0.0 <= result["confidence"] <= 1.0


def test_structured_response_fallback() -> None:
    """The structured output utility should return a fallback instance when JSON is invalid."""

    class DummyModelClient:
        """A dummy model client that returns invalid JSON."""

        def call(self, prompt: str, **kwargs: Any) -> str:
            return "this is not valid JSON"

    dummy_client = DummyModelClient()
    # Force only one retry to speed up the test
    result = get_structured_response(
        prompt="irrelevant",
        schema=EquityAnalysis,
        model_client=dummy_client,
        max_retries=1,
        backoff_factor=0.0,
    )
    # Result should be an instance of EquityAnalysis with empty lists
    assert isinstance(result, EquityAnalysis)
    assert result.business_overview == []
    assert result.bull_case == []
    assert result.bear_case == []
    assert result.key_risks == []
    assert result.key_catalysts == []


def test_repair_string_to_list() -> None:
    """repair_data should convert newline and bullet‑separated strings into lists."""
    class DummyModelClient:
        def call(self, prompt: str, **kwargs: Any) -> str:
            # return JSON with string fields containing bullets and newlines
            return json.dumps({
                "business_overview": "Overview",  # valid scalar
                "bull_case": "Strong growth\n- High margin\n• Global expansion",
                "bear_case": "Slowing demand; Rising costs",
                # missing keys will be filled by defaults
            })

    client = DummyModelClient()
    result = get_structured_response(
        prompt="irrelevant",
        schema=EquityAnalysis,
        model_client=client,
        max_retries=1,
        backoff_factor=0.0,
    )
    # Ensure list fields were split correctly
    assert result.bull_case == ["Strong growth", "High margin", "Global expansion"]
    assert result.bear_case == ["Slowing demand", "Rising costs"]
    # Missing list fields default to empty lists
    assert result.key_risks == []


def test_retry_exhaustion() -> None:
    """When all retries fail to produce valid JSON, fallback object should be returned."""
    class FailingClient:
        def __init__(self):
            self.calls = 0
        def call(self, prompt: str, **kwargs: Any) -> str:
            self.calls += 1
            return "{not a json}"

    client = FailingClient()
    result = get_structured_response(
        prompt="irrelevant",
        schema=EquityAnalysis,
        model_client=client,
        max_retries=2,
        backoff_factor=0.0,
    )
    # Should fallback to default instance after retries
    assert isinstance(result, EquityAnalysis)
    assert result.business_overview == []
    assert client.calls == 2


def test_context_enrichment() -> None:
    """enrich_grounding_context should fill missing fields with placeholders."""
    ctx = enrich_grounding_context("Tesla", "What is Tesla?", None)
    assert ctx.known_facts
    assert ctx.recent_events
    assert ctx.macro_context
    assert ctx.source_notes
    # Provided user_question should be preserved
    assert ctx.user_question == "What is Tesla?"


def test_structured_response_repair() -> None:
    """String fields should be converted to lists during repair."""
    from app.structured_output import get_structured_response
    import json as _json

    class Dummy:
        def call(self, prompt: str, **kwargs: Any) -> str:
            # Return a JSON string where list fields are single strings separated by newlines and bullets
            obj = {
                "business_overview": "Overview line 1\n- Overview line 2",
                "bull_case": "Bull case point 1\nBull case point 2",
                "bear_case": "Bear case one",
                "key_risks": "Risk A\n• Risk B",
                "key_catalysts": "Catalyst",
            }
            return _json.dumps(obj)

    dummy_client = Dummy()
    result = get_structured_response(
        prompt="repair test",
        schema=EquityAnalysis,
        model_client=dummy_client,
        max_retries=1,
        backoff_factor=0.0,
    )
    # Each string should be split into a list of trimmed items
    assert result.business_overview == ["Overview line 1", "Overview line 2"]
    assert result.bull_case == ["Bull case point 1", "Bull case point 2"]
    assert result.bear_case == ["Bear case one"]
    assert result.key_risks == ["Risk A", "Risk B"]
    assert result.key_catalysts == ["Catalyst"]


def test_analyze_selective_agents(monkeypatch: pytest.MonkeyPatch) -> None:
    """Only relevant agents should run based on question classification."""
    # Track how many times each specialized agent is invoked
    calls = {"macro": 0, "opportunity": 0, "research": 0, "education": 0, "accounting": 0, "synth": 0}

    # Provide deterministic stub outputs for each agent
    def fake_equity(company: str, context: Any = None, user_question: Any = None, request_id: Any = None) -> EquityAnalysis:
        return EquityAnalysis(
            business_overview=["overview"],
            bull_case=["bull"],
            bear_case=["bear"],
            key_risks=["risk"],
            key_catalysts=["catalyst"],
        )

    def fake_macro(company: str, context: Any = None, request_id: Any = None) -> MacroAnalysis:
        calls["macro"] += 1
        return MacroAnalysis(macro_overlay=["macro factor"])

    def fake_opportunity(company: str, context: Any = None, request_id: Any = None) -> OpportunityAnalysis:
        calls["opportunity"] += 1
        return OpportunityAnalysis(opportunity_summary=["opp"])

    def fake_research(company: str, context: Any = None, request_id: Any = None) -> ResearchAnalysis:
        calls["research"] += 1
        return ResearchAnalysis(research_summary=["res"])

    def fake_education(company: str, context: Any = None, request_id: Any = None) -> EducationAnalysis:
        calls["education"] += 1
        return EducationAnalysis(education_summary=["edu"])

    def fake_accounting(company: str, context: Any = None, request_id: Any = None) -> AccountingAnalysis:
        calls["accounting"] += 1
        return AccountingAnalysis(accounting_summary=["acc"])

    # Synthesizer returns a minimal valid synthesis using the provided specialist outputs
    def fake_synth(
        company: str,
        equity: EquityAnalysis,
        macro: MacroAnalysis,
        opportunity: OpportunityAnalysis,
        research: ResearchAnalysis,
        education: EducationAnalysis,
        accounting: AccountingAnalysis,
        context: Any = None,
        request_id: Any = None,
    ) -> Any:
        calls["synth"] += 1
        # Construct a synthesis output with required fields populated from inputs
        return SynthesisOutput(
            business_overview=equity.business_overview,
            bull_case=equity.bull_case,
            bear_case=equity.bear_case,
            key_risks=equity.key_risks,
            key_catalysts=equity.key_catalysts,
            macro_overlay=macro.macro_overlay,
            opportunity_summary=opportunity.opportunity_summary,
            research_summary=research.research_summary,
            education_summary=education.education_summary,
            accounting_summary=accounting.accounting_summary,
            final_verdict="neutral",
            verdict_reasoning="",
            confidence_score=0.5,
            confidence_reasoning="",
            thesis_fragility="",
        )

    # Patch the service-layer agent functions
    monkeypatch.setattr(asvc, "run_equity_agent", fake_equity)
    monkeypatch.setattr(asvc, "run_macro_agent", fake_macro)
    monkeypatch.setattr(asvc, "run_opportunity_agent", fake_opportunity)
    monkeypatch.setattr(asvc, "run_research_agent", fake_research)
    monkeypatch.setattr(asvc, "run_education_agent", fake_education)
    monkeypatch.setattr(asvc, "run_accounting_agent", fake_accounting)
    monkeypatch.setattr(asvc, "run_synthesizer_agent", fake_synth)

    # Compose a request that should trigger only the macro agent (inflation keyword)
    request = AnalysisRequest(company_name="Tesla", user_question="How does inflation impact Tesla?")
    response = asvc.analyze_company(request)
    # Verify that only the macro agent ran once and other specialized agents were not invoked
    assert calls["macro"] == 1
    assert calls["opportunity"] == 0
    assert calls["research"] == 0
    assert calls["education"] == 0
    assert calls["accounting"] == 0
    # Synthesizer should still run exactly once to combine results
    assert calls["synth"] == 1
    # Response should include nested structures for equity, macro, and synthesis
    assert isinstance(response.equity.business_overview, list)
    assert isinstance(response.macro.macro_overlay, list)
    assert isinstance(response.synthesis.bull_case, list)


def test_analyze_evidence_integration(monkeypatch: pytest.MonkeyPatch) -> None:
    """analyze_company should invoke evidence selection and building for context enrichment."""
    calls: Dict[str, int] = {"select": 0, "build": 0}

    # Stub the evidence selector to record its invocation and return a dummy decision
    def fake_select(question: Any) -> Dict[str, Any]:
        calls["select"] += 1
        return {"selected_sources": ["fmp"], "skipped_sources": [], "reasons": {}, "confidence": 1.0}

    # Stub the evidence builder to record its invocation and simply return the context unchanged
    def fake_build(company: str, ticker: Any, question: Any, sources: List[str], context: Any) -> Any:
        calls["build"] += 1
        return context

    # Patch analysis_service to use our fake evidence functions
    monkeypatch.setattr(asvc, "select_evidence_sources", fake_select)
    monkeypatch.setattr(asvc, "build_evidence", fake_build)

    # Stub agents to avoid calling the real OpenAI API
    monkeypatch.setattr(asvc, "run_equity_agent", lambda *args, **kwargs: EquityAnalysis())
    monkeypatch.setattr(asvc, "run_macro_agent", lambda *args, **kwargs: MacroAnalysis())
    monkeypatch.setattr(asvc, "run_opportunity_agent", lambda *args, **kwargs: OpportunityAnalysis())
    monkeypatch.setattr(asvc, "run_research_agent", lambda *args, **kwargs: ResearchAnalysis())
    monkeypatch.setattr(asvc, "run_education_agent", lambda *args, **kwargs: EducationAnalysis())
    monkeypatch.setattr(asvc, "run_accounting_agent", lambda *args, **kwargs: AccountingAnalysis())
    # Synthesize returns an empty synthesis to avoid complexity
    monkeypatch.setattr(asvc, "run_synthesizer_agent", lambda *args, **kwargs: SynthesisOutput())

    # Use a simple request that triggers no specialized agents
    req = AnalysisRequest(company_name="Tesla", user_question="Tell me about Tesla.")
    _ = asvc.analyze_company(req)
    # Evidence selector and builder should each be called exactly once
    assert calls["select"] == 1
    assert calls["build"] == 1


def test_partial_agent_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """If a specialized agent fails, analysis should still succeed using fallback values."""
    calls = {"macro": 0, "opportunity": 0, "synth": 0}

    # Fake equity agent always succeeds
    def fake_equity(company: str, context: Any = None, user_question: Any = None, request_id: Any = None) -> EquityAnalysis:
        return EquityAnalysis(business_overview=["overview"], bull_case=["bull"], bear_case=["bear"], key_risks=["risk"], key_catalysts=["catalyst"])

    # Fake macro agent increments call count
    def fake_macro(company: str, context: Any = None, request_id: Any = None) -> MacroAnalysis:
        calls["macro"] += 1
        return MacroAnalysis(macro_overlay=["macro factor"])

    # Fake opportunity agent raises an exception to simulate failure
    def fake_opportunity(company: str, context: Any = None, request_id: Any = None) -> OpportunityAnalysis:
        calls["opportunity"] += 1
        raise RuntimeError("agent failure")

    # Fake synthesizer uses provided inputs and records calls
    def fake_synth(
        company: str,
        equity: EquityAnalysis,
        macro: MacroAnalysis,
        opportunity: OpportunityAnalysis,
        research: ResearchAnalysis,
        education: EducationAnalysis,
        accounting: AccountingAnalysis,
        context: Any = None,
        request_id: Any = None,
    ) -> SynthesisOutput:
        calls["synth"] += 1
        return SynthesisOutput(
            business_overview=equity.business_overview,
            bull_case=equity.bull_case,
            bear_case=equity.bear_case,
            key_risks=equity.key_risks,
            key_catalysts=equity.key_catalysts,
            macro_overlay=macro.macro_overlay,
            opportunity_summary=opportunity.opportunity_summary,
            research_summary=[],
            education_summary=[],
            accounting_summary=[],
            final_verdict="neutral",
            verdict_reasoning="",
            confidence_score=0.5,
            confidence_reasoning="",
            thesis_fragility="",
        )

    # Patch analysis service agents
    monkeypatch.setattr(asvc, "run_equity_agent", fake_equity)
    monkeypatch.setattr(asvc, "run_macro_agent", fake_macro)
    monkeypatch.setattr(asvc, "run_opportunity_agent", fake_opportunity)
    monkeypatch.setattr(asvc, "run_research_agent", lambda *args, **kwargs: ResearchAnalysis())
    monkeypatch.setattr(asvc, "run_education_agent", lambda *args, **kwargs: EducationAnalysis())
    monkeypatch.setattr(asvc, "run_accounting_agent", lambda *args, **kwargs: AccountingAnalysis())
    monkeypatch.setattr(asvc, "run_synthesizer_agent", fake_synth)

    # Patch classify_question to route to macro and opportunity
    monkeypatch.setattr(asvc, "classify_question", lambda q: {
        "selected_agents": ["macro", "opportunity"],
        "skipped_agents": [],
        "reasons": {"macro": "test", "opportunity": "test"},
        "confidence": 0.5,
    })

    # Compose a request that should trigger macro and opportunity
    request = AnalysisRequest(company_name="Tesla", user_question="opportunity and inflation")
    response = asvc.analyze_company(request)
    # Macro agent should have run once
    assert calls["macro"] == 1
    # Opportunity agent attempted to run but failed; fallback should produce empty list
    assert calls["opportunity"] == 1
    assert response.opportunity.opportunity_summary == []
    # Synthesizer should still run
    assert calls["synth"] == 1


def test_enrich_with_retrieval(monkeypatch: pytest.MonkeyPatch) -> None:
    """Context enrichment should incorporate data from external providers when enabled."""
    from app.services.context_service import enrich_grounding_context
    import app.services.data_providers as providers
    from app.config import settings
    # Enable data retrieval and set dummy credentials
    monkeypatch.setattr(settings, "enable_data_retrieval", True)
    monkeypatch.setattr(settings, "fmp_api_key", "testkey")
    monkeypatch.setattr(settings, "sec_user_agent", "unit-test/0.1")
    # Patch provider functions to return deterministic values
    monkeypatch.setattr(providers, "fetch_fmp_financials", lambda ticker, api_key="", limit=1: {"revenue": 100.0, "net_income": 50.0})
    monkeypatch.setattr(providers, "fetch_sec_filings", lambda company, ticker, user_agent, count=1: {
        "recent_events": ["10-K filed"],
        "known_facts": ["Company filed its annual report"],
        "source_notes": ["SEC EDGAR"],
    })
    ctx = enrich_grounding_context("Tesla", "What is the outlook?", None)
    # Financial metrics should be populated
    assert ctx.financials.get("revenue") == 100.0
    assert ctx.financials.get("net_income") == 50.0
    # Known facts and recent events should include provider data
    assert "Company filed its annual report" in ctx.known_facts
    assert "10-K filed" in ctx.recent_events
    # Source notes should include the EDGAR note
    assert "SEC EDGAR" in ctx.source_notes


def test_enrich_retrieval_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """Context enrichment should fall back to placeholders when providers raise exceptions."""
    from app.services.context_service import enrich_grounding_context
    import app.services.data_providers as providers
    from app.config import settings
    # Enable retrieval
    monkeypatch.setattr(settings, "enable_data_retrieval", True)
    # Patch providers to raise exceptions
    def raise_fmp(*args, **kwargs):
        raise RuntimeError("FMP failure")
    def raise_sec(*args, **kwargs):
        raise RuntimeError("SEC failure")
    monkeypatch.setattr(providers, "fetch_fmp_financials", raise_fmp)
    monkeypatch.setattr(providers, "fetch_sec_filings", raise_sec)
    ctx = enrich_grounding_context("Tesla", "Show me Tesla.", None)
    # Should use placeholders as retrieval failed
    assert ctx.financials == {}
    assert ctx.known_facts  # placeholder message present
    assert ctx.recent_events  # placeholder message present
    assert ctx.source_notes  # placeholder message present


def test_route_question_evidence_integration(monkeypatch: pytest.MonkeyPatch) -> None:
    """route_question should invoke evidence selection and building before agent execution."""
    import app.services.router_service as rsvc
    # Counters for evidence functions
    calls: Dict[str, int] = {"select": 0, "build": 0}

    # Patch evidence selector to increment counter and return dummy decision
    def fake_select(question: Any) -> Dict[str, Any]:
        calls["select"] += 1
        return {"selected_sources": ["fmp"], "skipped_sources": [], "reasons": {}, "confidence": 1.0}

    # Patch evidence builder to increment counter and return the context unchanged
    def fake_build(company: str, ticker: Any, question: Any, sources: List[str], context: Any) -> Any:
        calls["build"] += 1
        return context

    # Patch evidence selection/building on the router service
    monkeypatch.setattr(rsvc, "select_evidence_sources", fake_select)
    monkeypatch.setattr(rsvc, "build_evidence", fake_build)
    # Patch context enrichment to return a bare context without hitting providers
    from app.schemas import GroundingContext
    monkeypatch.setattr(rsvc, "enrich_grounding_context", lambda c, q, ctx: ctx or GroundingContext(company=c, user_question=q))
    # Patch agents to return default instances without side effects
    monkeypatch.setattr(rsvc, "run_equity_agent", lambda *args, **kwargs: EquityAnalysis())
    monkeypatch.setattr(rsvc, "run_macro_agent", lambda *args, **kwargs: MacroAnalysis())
    monkeypatch.setattr(rsvc, "run_opportunity_agent", lambda *args, **kwargs: OpportunityAnalysis())
    monkeypatch.setattr(rsvc, "run_research_agent", lambda *args, **kwargs: ResearchAnalysis())
    monkeypatch.setattr(rsvc, "run_education_agent", lambda *args, **kwargs: EducationAnalysis())
    monkeypatch.setattr(rsvc, "run_accounting_agent", lambda *args, **kwargs: AccountingAnalysis())
    # Patch synthesizer to return empty synthesis
    monkeypatch.setattr(rsvc, "run_synthesizer_agent", lambda *args, **kwargs: SynthesisOutput())
    # Compose a question request
    from app.schemas import QuestionRequest
    req = QuestionRequest(company_name="Tesla", question="General question about Tesla")
    _ = rsvc.route_question(req)
    # Evidence selector and builder should each be called exactly once
    assert calls["select"] == 1
    assert calls["build"] == 1