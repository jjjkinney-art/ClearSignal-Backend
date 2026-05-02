"""
Basic tests for the AI analyst backend.

Tests are written with pytest and use FastAPI's TestClient. The
OpenAI API calls are patched to return predictable JSON so that
tests can run without external dependencies or costs.
"""

import pytest  # type: ignore

# Skip this obsolete test module in favour of the new reliability tests.
pytest.skip("Obsolete test module superseded by test_backend", allow_module_level=True)

# Ensure that the parent directory (project root) is on the import path.
# This allows ``import app`` to resolve correctly when tests are run from within
# the ``tests`` directory or via ``pytest`` from the project root.
import os
import sys  # isort: skip

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.main import app  # type: ignore  # noqa: E402


@pytest.fixture
def client() -> TestClient:
    """Provide a TestClient instance for the FastAPI app."""
    return TestClient(app)


def fake_call_agent(prompt: str) -> Dict[str, Any]:
    """A fake replacement for the call_agent function used in tests.

    The output varies depending on keywords in the prompt to simulate
    different agent outputs. It returns deterministic JSON
    appropriate for the Equity Analyst, Macro Analyst, or
    Synthesizer.
    """
    if "Macro Analyst" in prompt:
        return {"macro_overlay": "Macro factors summary."}
    elif "Head Analyst" in prompt:
        # Synthesizer returns the final combined structure.
        return {
            "business_overview": "Overview from equity.",
            "bull_case": "Bull case from equity.",
            "bear_case": "Bear case from equity.",
            "key_risks": "Risks from equity.",
            "key_catalysts": "Catalysts from equity.",
            "macro_overlay": "Macro factors summary.",
            "final_verdict": "neutral",
            "verdict_reasoning": "Reasoning based on inputs.",
            "what_to_monitor": "Items to monitor."
        }
    else:
        # Equity Analyst output
        return {
            "business_overview": "Overview from equity.",
            "bull_case": "Bull case from equity.",
            "bear_case": "Bear case from equity.",
            "key_risks": "Risks from equity.",
            "key_catalysts": "Catalysts from equity."
        }


def test_analyze_endpoint(monkeypatch: pytest.MonkeyPatch, client: TestClient) -> None:
    """Test the /analyze endpoint with patched agent calls."""
    # Patch the high‑level agent functions referenced in the service layer.  This
    # avoids dealing with import paths across modules and ensures that no
    # OpenAI API calls are made during the test.

    # Stub for equity analysis
    def fake_run_equity_agent(company_name: str, user_question=None, analysis_depth="standard"):
        return {
            "business_overview": "Overview from equity.",
            "bull_case": "Bull case from equity.",
            "bear_case": "Bear case from equity.",
            "key_risks": "Risks from equity.",
            "key_catalysts": "Catalysts from equity."
        }

    # Stub for macro analysis
    def fake_run_macro_agent(company_name: str):
        return {"macro_overlay": "Macro factors summary."}

    # Stub for synthesizer
    def fake_run_synthesizer_agent(
        company_name: str,
        equity_data: Dict[str, Any],
        macro_data: Dict[str, Any],
        opportunity_data: Dict[str, Any],
        research_data: Dict[str, Any],
        education_data: Dict[str, Any],
        accounting_data: Dict[str, Any],
    ):
        return {
            "business_overview": equity_data["business_overview"],
            "bull_case": equity_data["bull_case"],
            "bear_case": equity_data["bear_case"],
            "key_risks": equity_data["key_risks"],
            "key_catalysts": equity_data["key_catalysts"],
            "macro_overlay": macro_data["macro_overlay"],
            "opportunity_summary": opportunity_data["opportunity_summary"],
            "research_summary": research_data["research_summary"],
            "education_summary": education_data["education_summary"],
            "accounting_summary": accounting_data["accounting_summary"],
            "final_verdict": "neutral",
            "verdict_reasoning": "Reasoning based on inputs.",
            "what_to_monitor": "Items to monitor."
        }

    # Apply patches on the service layer functions.
    monkeypatch.setattr(
        "app.services.analysis_service.run_equity_agent",
        fake_run_equity_agent,
    )
    monkeypatch.setattr(
        "app.services.analysis_service.run_macro_agent",
        fake_run_macro_agent,
    )
    # Patch newly added agents
    def fake_run_opportunity_agent(company_name: str):
        return {"opportunity_summary": "Opportunity summary."}

    def fake_run_research_agent(company_name: str):
        return {"research_summary": "Research summary."}

    def fake_run_education_agent(company_name: str):
        return {"education_summary": "Education summary."}

    def fake_run_accounting_agent(company_name: str):
        return {"accounting_summary": "Accounting summary."}

    monkeypatch.setattr(
        "app.services.analysis_service.run_opportunity_agent",
        fake_run_opportunity_agent,
    )
    monkeypatch.setattr(
        "app.services.analysis_service.run_research_agent",
        fake_run_research_agent,
    )
    monkeypatch.setattr(
        "app.services.analysis_service.run_education_agent",
        fake_run_education_agent,
    )
    monkeypatch.setattr(
        "app.services.analysis_service.run_accounting_agent",
        fake_run_accounting_agent,
    )
    monkeypatch.setattr(
        "app.services.analysis_service.run_synthesizer_agent",
        fake_run_synthesizer_agent,
    )

    response = client.post("/analyze", json={"company_name": "Tesla"})
    assert response.status_code == 200, response.text
    data = response.json()
    # The company field should echo the input.
    assert data["company"] == "Tesla"
    # Verify that the synthesizer output fields are present.
    assert data["final_verdict"] == "neutral"
    assert "macro_overlay" in data
    assert "opportunity_summary" in data
    assert "research_summary" in data
    assert "education_summary" in data
    assert "accounting_summary" in data
    assert "what_to_monitor" in data


def test_ask_question_routing(monkeypatch: pytest.MonkeyPatch, client: TestClient) -> None:
    """Test the /ask endpoint routing and responses."""
    # Patch equity and specialized agents similarly to the previous test
    monkeypatch.setattr(
        "app.services.analysis_service.run_equity_agent",
        lambda company_name, user_question=None, analysis_depth="standard": {
            "business_overview": "Overview",
            "bull_case": "Bull",
            "bear_case": "Bear",
            "key_risks": "Risks",
            "key_catalysts": "Catalysts",
        },
    )
    monkeypatch.setattr(
        "app.services.router_service.run_equity_agent",
        lambda company_name, user_question=None, analysis_depth="standard": {
            "business_overview": "Overview",
            "bull_case": "Bull",
            "bear_case": "Bear",
            "key_risks": "Risks",
            "key_catalysts": "Catalysts",
        },
    )
    monkeypatch.setattr(
        "app.services.router_service.run_macro_agent",
        lambda company_name: {"macro_overlay": "Macro info"},
    )
    monkeypatch.setattr(
        "app.services.router_service.run_opportunity_agent",
        lambda company_name: {"opportunity_summary": "Opportunities"},
    )
    monkeypatch.setattr(
        "app.services.router_service.run_research_agent",
        lambda company_name: {"research_summary": "Research"},
    )
    monkeypatch.setattr(
        "app.services.router_service.run_education_agent",
        lambda company_name: {"education_summary": "Education"},
    )
    monkeypatch.setattr(
        "app.services.router_service.run_accounting_agent",
        lambda company_name: {"accounting_summary": "Accounting"},
    )
    monkeypatch.setattr(
        "app.services.router_service.run_synthesizer_agent",
        lambda company_name, e, m, o, r, ed, acc: {
            "business_overview": e["business_overview"],
            "bull_case": e["bull_case"],
            "bear_case": e["bear_case"],
            "key_risks": e["key_risks"],
            "key_catalysts": e["key_catalysts"],
            "macro_overlay": m.get("macro_overlay", ""),
            "opportunity_summary": o.get("opportunity_summary", ""),
            "research_summary": r.get("research_summary", ""),
            "education_summary": ed.get("education_summary", ""),
            "accounting_summary": acc.get("accounting_summary", ""),
            "final_verdict": "neutral",
            "verdict_reasoning": "Reasoning",
            "what_to_monitor": "Monitor",
        },
    )

    # Case 1: question triggers macro agent only
    response = client.post("/ask", json={"company_name": "Apple", "question": "How does inflation impact Apple?"})
    assert response.status_code == 200, response.text
    data = response.json()
    assert "macro_overlay" in data["answer"]
    assert data["agents_used"] == ["equity", "macro"]

    # Case 2: question triggers multiple agents (opportunity and research)
    response = client.post(
        "/ask",
        json={"company_name": "Apple", "question": "Identify emerging opportunities and summarize research for Apple"},
    )
    assert response.status_code == 200, response.text
    data = response.json()
    # Should include synthesizer output fields
    assert "opportunity_summary" in data["answer"]
    assert "research_summary" in data["answer"]
    assert "final_verdict" in data["answer"]