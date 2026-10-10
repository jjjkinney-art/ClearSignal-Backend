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
        filing_metric_evidence, issuer_release_evidence, live_issuer_kpi_service, session_context_service, thesis_disclosures,
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
        (thesis_disclosures, ["fetch_thesis_disclosures"]),
        (filing_metric_evidence, ["fetch_latest_filing_metrics"]),
        (verified_sec_metric_service, ["fetch_verified_metric_evidence"]),
    ):
        for name in names:
            monkeypatch.setattr(target, name, lambda *a, **k: [])
    monkeypatch.setattr(verified_sec_fact_service, "fetch_verified_revenue_claim",
                        lambda *a, **k: None)
    monkeypatch.setattr(router._sec_provider, '_load_ticker_cik_map', lambda: {})
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


@pytest.mark.parametrize("ticker,cik", [("AAPL", "320193"), ("ACHC", "1520697")])
def test_broad_cited_thesis_returns_partial_financial_foundation_without_models(isolated_pipeline, monkeypatch, ticker, cik):
    from app.integrity.sec_metric_evidence import comparable_metric_evidence
    from app.providers.sec_client import SecFactRecord
    from app.services import verified_sec_metric_service

    items = []
    for concept, name in (("Revenues", "revenue"), ("NetIncomeLoss", "net income")):
        records = []
        for year, value in ((2025, 100), (2026, 120)):
            accession = f"{int(cik):010d}-{str(year)[-2:]}-000001"
            records.append(SecFactRecord(cik=cik, taxonomy="us-gaap", concept=concept,
                label=concept, unit="USD", value=value, start=f"{year}-04-01", end=f"{year}-06-30",
                filed=f"{year}-08-01", form="10-Q", accession=accession,
                filing_url=f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession.replace('-', '')}/{accession}-index.htm"))
        items.append(comparable_metric_evidence(records, ticker=ticker, expected_cik=cik,
                                               concepts=(concept,), metric_name=name))
    monkeypatch.setattr(verified_sec_metric_service, "fetch_verified_metric_evidence", lambda *a, **k: items)
    monkeypatch.setattr("app.services.providers.sec_provider._load_ticker_cik_map", lambda: {ticker: cik})
    response = router._run_investment_pipeline(
        CompanyContext(ticker=ticker, company_name=ticker),
        f"What is the investment thesis for {ticker}, what supports it, and what could invalidate it? Cite material claims.",
        "financial-thesis-foundation", side_effects_enabled=False,
    )
    assert isolated_pipeline == []
    assert response.routing["response_mode"] == "source_evidence"
    assert response.answer["source_answer"]["status"] == "partial"
    assert len(response.answer["source_answer"]["inferences"]) == 2
    assert "Financial thesis foundation (partial)" in response.answer["investment_thesis"]["direct_answer"]
    reference_ids = {ref["id"] for ref in response.answer["evidence_references"]}
    assert all(row["reference_id"] in reference_ids for row in response.answer["source_answer"]["claims"])
    assert response.answer["investment_thesis"]["confidence_score"] == 0


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


def test_broad_thesis_fetches_disclosures_inside_source_pipeline(isolated_pipeline, monkeypatch):
    from app.services import thesis_disclosures, verified_sec_metric_service
    from test_financial_thesis_foundation import pair
    from test_thesis_disclosures import business_item, risk_item, QUESTION
    monkeypatch.setattr(verified_sec_metric_service, "fetch_verified_metric_evidence", lambda *a, **k: pair())
    monkeypatch.setattr("app.services.providers.sec_provider._load_ticker_cik_map", lambda: {"AAPL": "0000320193"})
    calls = []
    def fetch(*a, **k):
        calls.append(k)
        return [business_item(), risk_item()]
    monkeypatch.setattr(thesis_disclosures, "fetch_thesis_disclosures", fetch)
    response = router._run_investment_pipeline(CompanyContext(ticker="AAPL", company_name="Apple"),
        QUESTION, "business-risk-thesis", side_effects_enabled=False)
    assert len(calls) == 1
    source = response.answer["source_answer"]
    assert source["status"] == "partial" and isolated_pipeline == []
    assert any(row["claim_kind"] == "issuer_business_description" for row in source["claims"])
    assert any(row["claim_kind"] == "issuer_disclosed_risk" for row in source["claims"])
    assert response.answer["investment_thesis"]["confidence_score"] == 0


def test_historical_broad_thesis_does_not_fetch_current_disclosures(isolated_pipeline, monkeypatch):
    from app.services import thesis_disclosures
    def unexpected(*a, **k):
        pytest.fail("current filing retrieval must not run during historical replay")
    monkeypatch.setattr(thesis_disclosures, "fetch_thesis_disclosures", unexpected)
    router._run_investment_pipeline(CompanyContext(ticker="AAPL", company_name="Apple"),
        "What is the investment thesis for Apple? Cite material claims.",
        "historical-thesis", as_of="2026-09-26", side_effects_enabled=False)
