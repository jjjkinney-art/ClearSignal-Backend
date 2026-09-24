"""Only an exact SEC revenue observation may reach the supplemental answer."""

from dataclasses import replace
from unittest.mock import patch

from app.integrity.sec_revenue_claim import latest_sec_revenue_claim
from app.providers.sec_client import parse_company_fact_records
from app.services import verified_sec_fact_service as service


def _observation(*, value=1000000, start="2025-01-01", end="2025-03-31",
                 filed="2025-05-01", accession="0000320193-25-000001"):
    payload = {"cik": 320193, "facts": {"us-gaap": {"Revenues": {
        "label": "Revenue", "units": {"USD": [{
            "val": value, "start": start, "end": end, "filed": filed,
            "form": "10-Q", "accn": accession,
        }]},
    }}}}
    return parse_company_fact_records(payload, concept="Revenues", unit="USD")[0]


def test_latest_period_links_its_own_filing_and_preserves_duration():
    prior = _observation()
    current = _observation(value=2000000, start="2025-04-01", end="2025-06-30",
                           filed="2025-08-01", accession="0000320193-25-000002")
    claim = latest_sec_revenue_claim([prior, current], ticker="AAPL", expected_cik="320193")
    assert claim["value_text"] == "$2,000,000"
    assert claim["period_start"] == "2025-04-01"
    assert claim["period_end"] == "2025-06-30"
    assert claim["document_ref"]["url"] == current.filing_url
    assert prior.filing_url != current.filing_url


def test_decimal_revenue_display_matches_the_exact_record():
    claim = latest_sec_revenue_claim([_observation(value=1000000.5)], ticker="AAPL", expected_cik="320193")
    assert claim["value_text"] == "$1,000,000.5"
    assert claim["document_ref"] is not None


def test_ytd_and_conflicting_concepts_are_not_chosen():
    quarter = _observation()
    ytd = replace(quarter, start="2024-10-01")
    assert latest_sec_revenue_claim([ytd], ticker="AAPL", expected_cik="320193") is None
    other_concept = replace(quarter, concept="RevenueFromContractWithCustomerExcludingAssessedTax")
    assert latest_sec_revenue_claim([quarter, other_concept], ticker="AAPL", expected_cik="320193") is None


def test_ticker_identity_from_sec_mapping_not_user_input(monkeypatch):
    monkeypatch.setattr(service, "_load_ticker_cik_map", lambda: {"AAPL": "0000320193"})
    monkeypatch.setattr(service, "get_company_fact_records_for_concepts", lambda *a, **kw: [_observation()])
    assert service.fetch_verified_revenue_claim("AAPL")["document_ref"]["provider"] == "SEC EDGAR"
    assert service.fetch_verified_revenue_claim("TSLA") is None
    assert service.fetch_verified_revenue_claim("AAPL/../") is None


def test_mismatched_entity_and_broken_observation_never_get_a_link(monkeypatch):
    monkeypatch.setattr(service, "_load_ticker_cik_map", lambda: {"AAPL": "0000320193"})
    monkeypatch.setattr(service, "get_company_fact_records_for_concepts", lambda *a, **kw: [replace(_observation(), cik="1318605")])
    assert service.fetch_verified_revenue_claim("AAPL") is None


def test_revenue_question_returns_separate_verified_fact_without_rewriting_thesis():
    from app.schemas import (
        CompanyContext, InvestmentThesis, ValuationView, MacroSensitivity,
        RiskProfile, MarketContext, QualityAssessment,
    )
    from app.services.evidence_partitioner import EvidencePartition
    from app.services.router_service import _run_investment_pipeline

    company = CompanyContext(ticker="AAPL", company_name="Apple")
    thesis = InvestmentThesis(ticker="AAPL", company_name="Apple", bull_thesis="Original analysis")
    verified = latest_sec_revenue_claim([_observation()], ticker="AAPL", expected_cik="320193")
    with patch("app.services.router_service._fmp_provider.fetch_company_evidence", return_value=[]), \
         patch("app.services.router_service._sec_provider.fetch_recent_filings", return_value=[]), \
         patch("app.services.router_service._news_provider.fetch_company_news", return_value=[]), \
         patch("app.services.router_service._news_provider.fetch_macro_news", return_value=[]), \
         patch("app.services.router_service.retrieve_general_finance_evidence", return_value=[]), \
         patch("app.services.router_service.fetch_valuation_ratios", return_value=[]), \
         patch("app.services.router_service.fetch_analyst_estimates", return_value=[]), \
         patch("app.services.verified_sec_fact_service.fetch_verified_revenue_claim", return_value=verified), \
         patch("app.services.router_service.get_profile_for_company", return_value=None), \
         patch("app.services.router_service.partition_evidence", return_value=EvidencePartition(
             valuation=[], macro=[], risk=[], market=[], quality=[])), \
         patch("app.services.router_service.run_valuation_agent", return_value=ValuationView(overall=".")), \
         patch("app.services.router_service.run_investment_macro_agent", return_value=MacroSensitivity(overall=".")), \
         patch("app.services.router_service.run_risk_agent", return_value=RiskProfile(overall=".")), \
         patch("app.services.router_service.run_market_agent", return_value=MarketContext(overall=".")), \
         patch("app.services.router_service.run_quality_agent", return_value=QualityAssessment(overall=".")), \
         patch("app.investment_agents.question_answerer_agent.run_question_answerer", return_value=""), \
         patch("app.services.router_service.synthesize_thesis", return_value=thesis), \
         patch("app.services.router_service.watchlist_service"):
        response = _run_investment_pipeline(company, "What was Apple's revenue?", "test-sec-fact")

    assert response.answer["verified_sec_facts"] == [verified]
    assert response.answer["investment_thesis"]["bull_thesis"] == "Original analysis"
    assert not response.answer["investment_thesis"]["quantitative_claims"]
