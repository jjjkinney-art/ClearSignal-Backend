from app.schemas import (
    CompanyContext,
    InvestmentThesis,
    MacroSensitivity,
    MarketContext,
    QualityAssessment,
    RetrievedEvidence,
    RiskProfile,
    ValuationView,
)
from app.services import (
    router_service,
    verified_sec_fact_service,
    verified_sec_metric_service,
)
from app.services.evidence_partitioner import EvidencePartition


def _claim(value, reference_id):
    return {
        "ticker": "AAPL", "metric": "us-gaap:Revenues",
        "period_end": "2026-06-30", "period": "quarter ended 2026-06-30",
        "scope": "consolidated", "unit": "USD", "raw_value": value,
        "document_ref": {"reference_id": reference_id},
    }


def _conflict(title, value, filed_at):
    return RetrievedEvidence(
        title=title, source="SEC EDGAR — structured XBRL fact",
        summary=f"Apple reported revenue of {value}.", timestamp=filed_at,
        url="https://www.sec.gov/Archives/edgar/data/320193/example-index.htm",
        source_type="regulatory_filing", source_tier="primary",
        claim_type="reported_fact", document_type="10-Q", filed_at=filed_at,
        extraction_method="structured_xbrl",
        verified_claims=[_claim(value, title)],
    )


def test_conflicting_evidence_is_blocked_before_agents_and_source_answer(monkeypatch):
    conflicts = [
        _conflict("Filing A", 100, "2026-08-01"),
        _conflict("Filing B", 110, "2026-08-02"),
    ]
    captured = {}

    monkeypatch.setattr(router_service._fmp_provider, "fetch_company_evidence", lambda *a, **k: [])
    monkeypatch.setattr(router_service._sec_provider, "fetch_recent_filings", lambda *a, **k: [])
    monkeypatch.setattr(router_service._news_provider, "fetch_company_news", lambda *a, **k: [])
    monkeypatch.setattr(router_service._news_provider, "fetch_macro_news", lambda *a, **k: [])
    monkeypatch.setattr(router_service, "retrieve_general_finance_evidence", lambda *a, **k: [])
    monkeypatch.setattr(router_service, "fetch_valuation_ratios", lambda *a, **k: [])
    monkeypatch.setattr(router_service, "fetch_analyst_estimates", lambda *a, **k: [])
    monkeypatch.setattr(
        verified_sec_metric_service, "fetch_verified_metric_evidence",
        lambda *a, **k: conflicts,
    )
    monkeypatch.setattr(
        verified_sec_fact_service, "fetch_verified_revenue_claim",
        lambda *a, **k: None,
    )
    monkeypatch.setattr(router_service, "get_profile_for_company", lambda *a, **k: None)

    def partition(evidence, company):
        captured["partition_evidence"] = list(evidence)
        return EvidencePartition(valuation=[], macro=[], risk=[], market=[], quality=[])

    monkeypatch.setattr(router_service, "partition_evidence", partition)
    monkeypatch.setattr(router_service, "run_valuation_agent", lambda *a, **k: ValuationView(overall="."))
    monkeypatch.setattr(router_service, "run_investment_macro_agent", lambda *a, **k: MacroSensitivity(overall="."))
    monkeypatch.setattr(router_service, "run_risk_agent", lambda *a, **k: RiskProfile(overall="."))
    monkeypatch.setattr(router_service, "run_market_agent", lambda *a, **k: MarketContext(overall="."))
    monkeypatch.setattr(router_service, "run_quality_agent", lambda *a, **k: QualityAssessment(overall="."))
    monkeypatch.setattr(
        "app.investment_agents.question_answerer_agent.run_question_answerer",
        lambda *a, **k: captured.setdefault("question_evidence", list(k["evidence"])) or "",
    )
    monkeypatch.setattr(
        router_service, "synthesize_thesis",
        lambda *a, **k: (
            captured.setdefault("synthesis_evidence", list(k["evidence"])),
            InvestmentThesis(ticker="AAPL", company_name="Apple", bull_thesis="Safe"),
        )[1],
    )

    response = router_service._run_investment_pipeline(
        CompanyContext(ticker="AAPL", company_name="Apple"),
        "What source supports Apple's revenue?", "conflict-gate",
        side_effects_enabled=False,
    )

    assert captured["partition_evidence"] == []
    assert captured["question_evidence"] == []
    assert captured["synthesis_evidence"] == []
    assert response.answer["verified_sec_facts"] == []
    assert response.answer["source_answer"]["status"] == "insufficient_claim_evidence"
    assert response.answer["evidence_integrity"]["overall_status"] == "conflicting"
    assert response.answer["evidence_integrity"]["admission"]["blocked_count"] == 2
    assert {ref["freshness_status"] for ref in response.answer["evidence_references"]} == {
        "conflicting"
    }
