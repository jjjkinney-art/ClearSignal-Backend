import json

import pytest

from app.schemas import (
    CompanyContext,
    InvestmentThesis,
    MacroSensitivity,
    MarketContext,
    QualityAssessment,
    QuestionRequest,
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


@pytest.mark.parametrize("authenticated", [False, True])
@pytest.mark.parametrize("with_disclosed_risk", [False, True])
@pytest.mark.parametrize("ticker,scope,cik,quote", [
    ("AAPL", "Services", "320193", "Competition for digital content may adversely affect the Company's Services business."),
    ("MSFT", "Cloud", "789019", "Cloud capacity constraints could adversely affect our revenue growth."),
    ("NVDA", "Data Center", "1045810", "Data center capacity constraints could adversely affect our revenue growth."),
    ("DOCU", "Subscription renewals", "1261333", "Subscription renewals may decline and adversely affect revenue growth."),
    ("AA", "smelter energy supply", "1675149", "Smelter energy shortages may harm production."),
    ("ACHC", "facility safety", "1520697", "Facility safety failures may adversely affect operations."),
    ("ACMR", "customer concentration", "1680062", "Customer concentration may adversely affect revenue growth."),
    ("MAN", "staffing demand", "871763", "Staffing demand declines may adversely affect revenue growth."),
])
def test_scoped_risk_boundary_covers_snapshot_and_emitted_thesis(monkeypatch, authenticated, with_disclosed_risk,
                                                               ticker, scope, cik, quote):
    from app.config import settings
    from app.services import live_issuer_kpi_service, session_context_service
    from app.services.issuer_risk_evidence import RISK_PROFILES
    reviewed = ticker in RISK_PROFILES

    for target, names in (
        (router_service._fmp_provider, ["fetch_company_evidence"]),
        (router_service._sec_provider, ["fetch_recent_filings"]),
        (router_service._news_provider, ["fetch_company_news", "fetch_macro_news"]),
        (router_service, ["retrieve_general_finance_evidence", "fetch_valuation_ratios", "fetch_analyst_estimates"]),
        (verified_sec_metric_service, ["fetch_verified_metric_evidence"]),
        (live_issuer_kpi_service, ["fetch_live_issuer_kpi_evidence"]),
    ):
        for name in names:
            monkeypatch.setattr(target, name, lambda *a, **k: [])
    if not reviewed:
        # A real producer-built, accession-bound financial observation is
        # admissible context, but cannot answer this unrelated operating risk.
        from app.providers.sec_client import SecFactRecord
        from app.integrity.sec_metric_evidence import comparable_metric_evidence
        def observation(year, value):
            accession = f"{int(cik):010d}-{str(year)[2:]}-000001"
            return SecFactRecord(cik, "us-gaap", "Revenues", "Revenue", "USD", value,
                f"{year}-01-01", f"{year}-03-31", f"{year}-05-01", "10-Q", accession,
                f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession.replace('-', '')}/{accession}-index.htm")
        metric = comparable_metric_evidence([observation(2025, 100), observation(2026, 112)],
            ticker=ticker, expected_cik=cik, concepts=("Revenues",), metric_name="revenue")
        assert metric is not None
        monkeypatch.setattr(verified_sec_metric_service, "fetch_verified_metric_evidence", lambda *a, **k: [metric])
    if with_disclosed_risk:
        from hashlib import sha256
        from app.services.public_document_ingestion import PublicDocument
        from app.services.issuer_risk_evidence import extract_issuer_risk_evidence
        url = f"https://www.sec.gov/Archives/edgar/data/{cik}/000032019325000079/report.htm"
        text = f"Item 1A. Risk Factors {quote} Item 1B. Unresolved Staff Comments"
        doc = PublicDocument(url, url, "text/html", sha256(text.encode()).hexdigest(), len(text),
                             "Synthetic risk fixture", text, (), (), (), "html", True, "2026-10-06",
                             publisher="SEC EDGAR", published_at="2025-10-31", document_type="10-K",
                             source_type="regulatory_filing", source_tier="primary")
        risk_evidence = extract_issuer_risk_evidence(doc, ticker=ticker, question=f"{scope} operating risks")
        monkeypatch.setattr(live_issuer_kpi_service, "fetch_live_issuer_kpi_evidence",
                            lambda *a, **k: risk_evidence)
    monkeypatch.setattr(router_service, "get_profile_for_company", lambda *a, **k: None)
    monkeypatch.setattr(router_service, "partition_evidence", lambda *a, **k:
                        EvidencePartition(valuation=[], macro=[], risk=[], market=[], quality=[]))
    for name, model in (
        ("run_valuation_agent", ValuationView), ("run_investment_macro_agent", MacroSensitivity),
        ("run_risk_agent", RiskProfile), ("run_market_agent", MarketContext),
        ("run_quality_agent", QualityAssessment),
    ):
        monkeypatch.setattr(router_service, name, lambda *a, _model=model, **k: _model())
    monkeypatch.setattr("app.investment_agents.question_answerer_agent.run_question_answerer",
                        lambda *a, **k: "Services margin is 72%.")
    monkeypatch.setattr(router_service, "synthesize_thesis", lambda *a, **k:
                        InvestmentThesis(ticker=ticker, company_name=ticker,
                                         direct_answer="Services margin is 72%.",
                                         one_sentence_thesis="Services margin is 72%.",
                                         bull_thesis="Services margin is 72%."))
    monkeypatch.setattr(settings, "auth_enabled", authenticated)
    monkeypatch.setattr(session_context_service, "record_active_ticker", lambda *a, **k: None)
    monkeypatch.setattr(router_service.watchlist_service, "get_latest_snapshot", lambda *a: None)
    captured = []

    def persist(thesis):
        captured.append(thesis.model_dump(mode="json"))
        # A downstream legacy processor must not restore an unbound headline.
        thesis.one_sentence_thesis = "Services margin is 72%."
        return None, None

    monkeypatch.setattr(router_service.watchlist_service, "process_new_thesis", persist)
    # Enter through the public router so an extractor profile without upstream
    # company registration cannot silently pass this integration regression.
    response = router_service.route_question(QuestionRequest(
        company_name=ticker, intent="company_analysis",
        question=f"What evidence supports {ticker}'s {scope} growth, and what operating risk could invalidate it?",
    ))
    assert response.answer["source_answer"]["status"] == (
        "attributed" if with_disclosed_risk and reviewed else "insufficient_claim_evidence")
    if not reviewed:
        assert len(response.answer["verified_sec_facts"]) == 2
        assert response.answer["evidence_integrity"]["admission"]["admitted_count"] >= 1
        assert response.answer["source_answer"]["claims"] == []
        assert response.answer["source_answer"]["unanswered_parts"] == ["operating risk"]
        assert response.answer["investment_thesis"]["bull_thesis"] == ""
    if with_disclosed_risk and reviewed:
        assert response.answer["source_answer"]["claims"][0]["claim_kind"] == "issuer_disclosed_risk"
        assert "does not independently verify" in response.answer["investment_thesis"]["direct_answer"]
    assert "72%" not in json.dumps(response.answer["investment_thesis"])
    if authenticated:
        assert captured == []  # Shared ticker memory remains guarded.
    else:
        assert len(captured) == 1
        assert "72%" not in json.dumps(captured[0])
        assert captured[0]["conclusion"] == response.answer["investment_thesis"]["conclusion"]
