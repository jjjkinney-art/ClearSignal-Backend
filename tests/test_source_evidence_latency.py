"""Source views must not pay for discarded model stages or invent confidence."""

import json
from pathlib import Path

import pytest

from app.schemas import (
    CompanyContext, InvestmentThesis, MacroSensitivity, MarketContext,
    QualityAssessment, RiskProfile, ValuationView,
)
from app.services import router_service as router


@pytest.fixture
def isolated_pipeline(monkeypatch):
    from app.services import (
        issuer_release_evidence, live_issuer_kpi_service, session_context_service,
        verified_sec_fact_service, verified_sec_metric_service,
    )

    for target, names in (
        (router._fmp_provider, ["fetch_company_evidence"]),
        (router._sec_provider, ["fetch_recent_filings"]),
        (router._news_provider, ["fetch_company_news", "fetch_macro_news"]),
        (router, ["retrieve_general_finance_evidence", "fetch_valuation_ratios",
                  "fetch_analyst_estimates"]),
        (live_issuer_kpi_service, ["fetch_live_issuer_kpi_evidence"]),
        (issuer_release_evidence, ["fetch_issuer_release_evidence"]),
        (verified_sec_metric_service, ["fetch_verified_metric_evidence"]),
    ):
        for name in names:
            monkeypatch.setattr(target, name, lambda *a, **k: [])
    monkeypatch.setattr(verified_sec_fact_service, "fetch_verified_revenue_claim",
                        lambda *a, **k: None)
    monkeypatch.setattr(router, "get_profile_for_company", lambda *a, **k: None)
    monkeypatch.setattr(session_context_service, "record_active_ticker", lambda *a, **k: None)
    calls = []
    for name, model in (
        ("run_valuation_agent", ValuationView),
        ("run_investment_macro_agent", MacroSensitivity),
        ("run_risk_agent", RiskProfile),
        ("run_market_agent", MarketContext),
        ("run_quality_agent", QualityAssessment),
    ):
        def run(*args, _name=name, _model=model, **kwargs):
            calls.append(_name)
            return _model()
        monkeypatch.setattr(router, name, run)

    def answer(*args, **kwargs):
        calls.append("question_answerer")
        return "Model answer"

    def synthesize(*args, **kwargs):
        calls.append("synthesize")
        return InvestmentThesis(ticker="AAPL", company_name="Apple",
                               direct_answer="Model answer", confidence_score=0.65)

    monkeypatch.setattr("app.investment_agents.question_answerer_agent.run_question_answerer", answer)
    monkeypatch.setattr(router, "synthesize_thesis", synthesize)
    return calls


CASES = json.loads((Path(__file__).parents[1] /
                    "validation/company_evidence_coverage.v1.json").read_text())["cases"]


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["ticker"])
def test_every_cohort_question_skips_models_and_returns_honest_gap(isolated_pipeline, case):
    response = router._run_investment_pipeline(
        CompanyContext(ticker=case["ticker"], company_name=case["company"]),
        case["question"], "source-no-model", side_effects_enabled=False,
    )
    assert isolated_pipeline == []
    assert response.agents_used == ["source_answer"]
    assert response.answer["source_answer"]["status"] == "insufficient_claim_evidence"
    thesis = response.answer["investment_thesis"]
    assert thesis["ticker"] == case["ticker"]
    assert thesis["confidence_score"] == 0
    assert thesis["score_source"] == "not_assessed_evidence_view"
    assert thesis["conviction_dimensions"] == {}
    assert thesis["generated_at"]
    assert thesis["direct_answer"] != "Model answer"
    assert response.routing["response_mode"] == "source_evidence"


@pytest.mark.parametrize("question", [
    "What is Apple's investment thesis?",
    "Is Apple fairly valued?",
    "Compared with this selected Apple investigation, has any attributable evidence "
    "published since that record strengthened or weakened the thesis?",
])
def test_broader_analysis_still_runs_all_models(isolated_pipeline, question):
    response = router._run_investment_pipeline(
        CompanyContext(ticker="AAPL", company_name="Apple"),
        question, "ordinary-analysis", side_effects_enabled=False,
    )
    assert len(isolated_pipeline) == 7
    assert "question_answerer" in isolated_pipeline and "synthesize" in isolated_pipeline
    assert response.answer["source_answer"] is None
    assert response.answer["investment_thesis"]["direct_answer"] == "Model answer"
    assert response.answer["investment_thesis"]["confidence_score"] == 0.65
    assert response.routing["response_mode"] == "generated_analysis"
    assert "thesis_synthesizer" in response.agents_used


@pytest.mark.parametrize("question,models", [
    ("What public evidence reports Tesla vehicle deliveries?", False),
    ("Have Tesla vehicle deliveries strengthened its execution?", True),
])
def test_official_release_enters_shared_admission_and_source_view(isolated_pipeline, monkeypatch, question, models):
    from app.schemas import RetrievedEvidence
    from app.services import issuer_release_evidence
    calls = []
    item = RetrievedEvidence(
        title="TSLA Q3 2026 vehicle deliveries: 486,532",
        source="Tesla Investor Relations", summary="Tesla reported vehicle deliveries of 486,532.",
        timestamp="2026-10-02", source_type="issuer_release", source_tier="primary",
        claim_type="reported_fact", document_type="press_release", extraction_method="html",
        url="https://ir.tesla.com/press-release/tesla-third-quarter-2026-production-deliveries-and-deployments",
        verified_claims=[{"ticker": "TSLA", "metric": "issuer:vehicle deliveries"}],
    )
    def fetch(ticker, **kwargs):
        calls.append(ticker)
        return [item]
    monkeypatch.setattr(issuer_release_evidence, "fetch_issuer_release_evidence", fetch)
    prompt_citations = []
    original_synthesis = router.synthesize_thesis
    def synthesize(**kwargs):
        prompt_citations.extend(e.citation_id for e in kwargs["evidence"])
        return original_synthesis(**kwargs)
    monkeypatch.setattr(router, "synthesize_thesis", synthesize)
    response = router._run_investment_pipeline(
        CompanyContext(ticker="TSLA", company_name="Tesla"),
        question, "official-release", side_effects_enabled=False,
    )
    assert calls == ["TSLA"]
    assert len(isolated_pipeline) == (7 if models else 0)
    refs = response.answer["evidence_references"]
    assert refs[0]["id"] == "E1" and refs[0]["source_type"] == "issuer_release"
    if models:
        assert response.answer["source_answer"] is None
        assert prompt_citations == ["E1"]
    else:
        assert response.answer["source_answer"]["status"] == "attributed"
    # Official releases must not be mislabeled as verified SEC facts.
    assert response.answer["verified_sec_facts"] == []


def test_historical_replay_does_not_fetch_current_release(isolated_pipeline, monkeypatch):
    from app.services import issuer_release_evidence
    def forbidden(*args, **kwargs):
        pytest.fail("historical replay must not fetch current official releases")
    monkeypatch.setattr(issuer_release_evidence, "fetch_issuer_release_evidence", forbidden)
    response = router._run_investment_pipeline(
        CompanyContext(ticker="TSLA", company_name="Tesla"),
        "What public evidence reports Tesla vehicle deliveries?", "historical-release", side_effects_enabled=False,
        as_of="2026-09-26",
    )
    assert response.answer["evidence_references"] == []
