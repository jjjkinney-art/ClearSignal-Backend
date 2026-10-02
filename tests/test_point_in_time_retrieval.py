from app.providers.sec_client import SecFactRecord
from app.schemas import AgentAnswerResponse, GroundingContext, QuestionRequest
from app.services import (
    context_service,
    data_providers,
    router_service,
    verified_sec_fact_service,
    verified_sec_metric_service,
)
from app.services.providers import sec_provider


def test_sec_cik_lookup_excludes_filings_after_as_of(monkeypatch):
    sec_provider._ticker_cik_cache = None
    submissions = {
        "name": "Acme Inc.",
        "filings": {"recent": {
            "form": ["10-Q", "10-Q", "10-K"],
            "filingDate": ["2024-09-01", "2024-08-01", "2024-02-01"],
            "reportDate": ["2024-06-30", "2024-06-30", "2023-12-31"],
        }},
    }

    def fetch(url, timeout=10):
        if "company_tickers" in url:
            return {"0": {"ticker": "ACME", "cik_str": 1}}
        return submissions

    monkeypatch.setattr(sec_provider, "_fetch_json", fetch)
    results = sec_provider.fetch_recent_filings(
        "ACME", as_of="2024-08-15T23:59:59Z", years_back=2,
    )

    assert [item.timestamp for item in results] == ["2024-08-01", "2024-02-01"]
    assert all(item.timestamp <= "2024-08-15" for item in results)


def test_sec_entity_search_sends_and_enforces_end_boundary(monkeypatch):
    sec_provider._ticker_cik_cache = None
    seen_urls = []

    def fetch(url, timeout=10):
        seen_urls.append(url)
        return {"hits": {"hits": [
            {"_source": {
                "form_type": "10-Q", "file_date": "2024-09-01",
                "period_of_report": "2024-06-30", "entity_name": "Acme Corp",
            }},
            {"_source": {
                "form_type": "10-Q", "file_date": "2024-08-01",
                "period_of_report": "2024-03-31", "entity_name": "Acme Corp",
            }},
        ]}}

    monkeypatch.setattr(sec_provider, "_fetch_json", fetch)
    results = sec_provider.fetch_recent_filings(
        "Acme Corp", as_of="2024-08-15", years_back=2,
    )

    assert [item.timestamp for item in results] == ["2024-08-01"]
    assert any("enddt=2024-08-15" in url for url in seen_urls)
    assert any("startdt=2022-08-16" in url for url in seen_urls)


def test_historical_context_suppresses_latest_only_fmp(monkeypatch):
    monkeypatch.setattr(context_service.settings, "enable_data_retrieval", True)
    called = {"fmp": 0, "as_of": None}

    def fmp(*args, **kwargs):
        called["fmp"] += 1
        return {"revenue": 999}

    def sec(company, ticker, user_agent, count=1, as_of=None):
        called["as_of"] = as_of
        return {
            "recent_events": ["10-K on 2020-02-01"],
            "known_facts": [],
            "source_notes": ["SEC EDGAR point-in-time filings"],
        }

    monkeypatch.setattr(context_service.data_providers, "fetch_fmp_financials", fmp)
    monkeypatch.setattr(context_service.data_providers, "fetch_sec_filings", sec)
    context = GroundingContext(company="Acme", ticker="ACME")

    result = context_service.enrich_grounding_context(
        "Acme", "Historical performance", context,
        as_of="2020-12-31T23:59:59Z",
    )

    assert called == {"fmp": 0, "as_of": "2020-12-31T23:59:59Z"}
    assert result.financials == {}
    assert result.recent_events == ["10-K on 2020-02-01"]


def test_legacy_sec_feed_uses_dateb_and_filters_future_rows():
    text = """
        <feed><title>Feed</title>
        <title>Future filing</title><updated>2021-02-01</updated>
        <title>Boundary filing</title><updated>2020-12-31</updated>
        </feed>
        """

    url = data_providers._sec_feed_url("ACME", 1, "2020-12-31")
    events = data_providers._parse_sec_feed_events(
        text, count=1, boundary="2020-12-31",
    )

    assert "dateb=20201231" in url
    assert "count=100" in url
    assert events == ["Boundary filing on 2020-12-31"]


def _fact(*, value, end, filed, accession, start="2024-04-01"):
    return SecFactRecord(
        cik="320193", taxonomy="us-gaap", concept="Revenues",
        label="Revenue", unit="USD", value=value, start=start, end=end,
        filed=filed, form="10-Q", accession=accession,
        filing_url=(
            "https://www.sec.gov/Archives/edgar/data/320193/"
            f"{accession.replace('-', '')}/{accession}-index.htm"
        ),
    )


def test_structured_revenue_rejects_facts_filed_after_boundary(monkeypatch):
    prior = _fact(
        value=90, start="2023-04-01", end="2023-06-30",
        filed="2023-08-01", accession="0000320193-23-000001",
    )
    available = _fact(
        value=100, end="2024-06-30", filed="2024-08-01",
        accession="0000320193-24-000001",
    )
    future = _fact(
        value=999, end="2024-09-30", filed="2024-11-01",
        accession="0000320193-24-000002", start="2024-07-01",
    )
    monkeypatch.setattr(
        verified_sec_fact_service, "_load_ticker_cik_map",
        lambda: {"AAPL": "320193"},
    )
    monkeypatch.setattr(
        verified_sec_fact_service, "get_company_fact_records_for_concepts",
        lambda *args, **kwargs: [prior, available, future],
    )

    claim = verified_sec_fact_service.fetch_verified_revenue_claim(
        "AAPL", as_of="2024-08-15T23:59:59Z",
    )

    assert claim["raw_value"] == 100
    assert claim["document_ref"]["published_at"] == "2024-08-01"


def test_structured_metric_selection_rejects_late_filing(monkeypatch):
    prior = _fact(
        value=90, start="2023-04-01", end="2023-06-30",
        filed="2023-08-01", accession="0000320193-23-000001",
    )
    available = _fact(
        value=100, end="2024-06-30", filed="2024-08-01",
        accession="0000320193-24-000001",
    )
    late_amendment = _fact(
        value=110, end="2024-06-30", filed="2024-09-01",
        accession="0000320193-24-000002",
    )
    monkeypatch.setattr(
        verified_sec_metric_service, "_load_ticker_cik_map",
        lambda: {"AAPL": "320193"},
    )
    monkeypatch.setattr(
        verified_sec_metric_service,
        "get_company_fact_records_for_concept_units",
        lambda *args, **kwargs: [prior, available, late_amendment],
    )

    evidence = verified_sec_metric_service.fetch_verified_metric_evidence(
        "AAPL", question="revenue", as_of="2024-08-15",
    )

    assert len(evidence) == 1
    assert evidence[0].verified_claims[0]["raw_value"] == 100
    assert evidence[0].filed_at == "2024-08-01"


def test_invalid_structured_fact_boundary_fails_closed(monkeypatch):
    monkeypatch.setattr(
        verified_sec_fact_service, "_load_ticker_cik_map",
        lambda: {"AAPL": "320193"},
    )
    monkeypatch.setattr(
        verified_sec_fact_service, "get_company_fact_records_for_concepts",
        lambda *args, **kwargs: [],
    )
    monkeypatch.setattr(
        verified_sec_metric_service, "_load_ticker_cik_map",
        lambda: {"AAPL": "320193"},
    )
    monkeypatch.setattr(
        verified_sec_metric_service,
        "get_company_fact_records_for_concept_units",
        lambda *args, **kwargs: [],
    )

    assert verified_sec_fact_service.fetch_verified_revenue_claim(
        "AAPL", as_of="not-a-date",
    ) is None
    assert verified_sec_metric_service.fetch_verified_metric_evidence(
        "AAPL", question="revenue", as_of="not-a-date",
    ) == []


def test_question_route_propagates_point_in_time_boundary(monkeypatch):
    captured = {}

    def run_pipeline(**kwargs):
        captured.update(kwargs)
        return AgentAnswerResponse(
            company="Apple", request_id="point-in-time", agents_used=[],
            answer={}, routing={"pipeline": "investment_thesis"},
        )

    monkeypatch.setattr(router_service, "_run_investment_pipeline", run_pipeline)
    request = QuestionRequest(
        company_name="AAPL", question="Analyze Apple's revenue",
        intent="company_analysis", as_of="2024-08-15T23:59:59Z",
    )

    response = router_service.route_question(request)

    assert response.request_id == "point-in-time"
    assert captured["as_of"] == "2024-08-15T23:59:59Z"


def test_historical_question_pipeline_suppresses_latest_only_sources(monkeypatch):
    from app.schemas import (
        CompanyContext, InvestmentThesis, MacroSensitivity, MarketContext,
        QualityAssessment, RiskProfile, ValuationView,
    )
    from app.services.evidence_partitioner import EvidencePartition

    boundary = "2024-08-15T23:59:59Z"
    captured = {"sec": None, "revenue": None, "metrics": None}

    def forbidden(*args, **kwargs):
        raise AssertionError("latest-only provider must not run historically")

    def sec(*args, **kwargs):
        captured["sec"] = kwargs.get("as_of")
        return []

    def revenue(*args, **kwargs):
        captured["revenue"] = kwargs.get("as_of")
        return None

    def metrics(*args, **kwargs):
        captured["metrics"] = kwargs.get("as_of")
        return []

    monkeypatch.setattr(router_service._fmp_provider, "fetch_company_evidence", forbidden)
    monkeypatch.setattr(router_service._sec_provider, "fetch_recent_filings", sec)
    monkeypatch.setattr(router_service._news_provider, "fetch_company_news", forbidden)
    monkeypatch.setattr(router_service._news_provider, "fetch_macro_news", forbidden)
    monkeypatch.setattr(router_service, "retrieve_general_finance_evidence", forbidden)
    monkeypatch.setattr(router_service, "fetch_valuation_ratios", forbidden)
    monkeypatch.setattr(router_service, "fetch_analyst_estimates", forbidden)
    monkeypatch.setattr(verified_sec_fact_service, "fetch_verified_revenue_claim", revenue)
    monkeypatch.setattr(verified_sec_metric_service, "fetch_verified_metric_evidence", metrics)
    monkeypatch.setattr(router_service, "get_profile_for_company", lambda *a, **k: None)
    monkeypatch.setattr(
        router_service, "partition_evidence",
        lambda *a, **k: EvidencePartition(
            valuation=[], macro=[], risk=[], market=[], quality=[],
        ),
    )
    monkeypatch.setattr(
        router_service, "run_valuation_agent",
        lambda *a, **k: ValuationView(overall="."),
    )
    monkeypatch.setattr(
        router_service, "run_investment_macro_agent",
        lambda *a, **k: MacroSensitivity(overall="."),
    )
    monkeypatch.setattr(
        router_service, "run_risk_agent",
        lambda *a, **k: RiskProfile(overall="."),
    )
    monkeypatch.setattr(
        router_service, "run_market_agent",
        lambda *a, **k: MarketContext(overall="."),
    )
    monkeypatch.setattr(
        router_service, "run_quality_agent",
        lambda *a, **k: QualityAssessment(overall="."),
    )
    monkeypatch.setattr(
        "app.investment_agents.question_answerer_agent.run_question_answerer",
        lambda *a, **k: "",
    )
    monkeypatch.setattr(
        router_service, "synthesize_thesis",
        lambda *a, **k: InvestmentThesis(
            ticker="AAPL", company_name="Apple", bull_thesis="Historical",
        ),
    )

    router_service._run_investment_pipeline(
        CompanyContext(ticker="AAPL", company_name="Apple"),
        "What source supports Apple's revenue?", "historical",
        as_of=boundary, side_effects_enabled=False,
    )

    assert captured == {"sec": boundary, "revenue": boundary, "metrics": boundary}


def test_historical_question_route_preserves_former_ticker_identity(monkeypatch):
    captured = {}

    def run_pipeline(**kwargs):
        captured.update(kwargs)
        return AgentAnswerResponse(
            company=kwargs["company"].company_name,
            request_id="historical-fb", agents_used=[], answer={},
            routing={"pipeline": "investment_thesis"},
        )

    monkeypatch.setattr(router_service, "_run_investment_pipeline", run_pipeline)

    response = router_service.route_question(QuestionRequest(
        company_name="", question="FB", as_of="2021-12-31T23:59:59Z",
    ))

    assert response.request_id == "historical-fb"
    assert captured["company"].ticker == "META"
    assert captured["as_of"] == "2021-12-31T23:59:59Z"


def test_pre_acquisition_question_fails_closed_before_pipeline(monkeypatch):
    monkeypatch.setattr(
        router_service, "_run_investment_pipeline",
        lambda **kwargs: (_ for _ in ()).throw(
            AssertionError("pipeline must not run for temporal mismatch")
        ),
    )

    response = router_service.route_question(QuestionRequest(
        company_name="LinkedIn", question="Analyze LinkedIn revenue",
        intent="company_analysis", as_of="2015-12-31T23:59:59Z",
    ))

    assert response.routing["pipeline"] == "temporal_identity_clarification"
    assert response.routing["relationship_status"] == "not_yet_owned"
    assert response.routing["historical_ticker"] == "LNKD"
    assert "LNKD" in response.answer["general"]["caveats"][0]


def test_pre_separation_question_names_predecessor_and_does_not_route(monkeypatch):
    monkeypatch.setattr(
        router_service, "_run_investment_pipeline",
        lambda **kwargs: (_ for _ in ()).throw(
            AssertionError("pipeline must not run for pre-separation entity")
        ),
    )

    response = router_service.route_question(QuestionRequest(
        company_name="PayPal", question="Analyze PayPal revenue",
        intent="company_analysis", as_of="2014-12-31",
    ))

    assert response.routing["pipeline"] == "temporal_identity_clarification"
    assert response.routing["relationship_status"] == "pre_separation"
    assert response.routing["predecessor_tickers"] == ["EBAY"]
    assert "EBAY" in response.answer["general"]["answer"]


def test_post_separation_question_routes_current_standalone_issuer(monkeypatch):
    captured = {}

    def run_pipeline(**kwargs):
        captured.update(kwargs)
        return AgentAnswerResponse(
            company=kwargs["company"].company_name,
            request_id="paypal-after-separation", agents_used=[], answer={},
            routing={"pipeline": "investment_thesis"},
        )

    monkeypatch.setattr(router_service, "_run_investment_pipeline", run_pipeline)

    response = router_service.route_question(QuestionRequest(
        company_name="PayPal", question="Analyze PayPal revenue",
        intent="company_analysis", as_of="2016-12-31",
    ))

    assert response.request_id == "paypal-after-separation"
    assert captured["company"].ticker == "PYPL"
    assert captured["as_of"] == "2016-12-31"
