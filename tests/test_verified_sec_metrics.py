from dataclasses import replace

from app.integrity.sec_metric_evidence import (
    comparable_instant_metric_evidence,
    comparable_metric_evidence,
)
from app.providers.sec_client import SecFactRecord
from app.services import verified_sec_metric_service as service


def _record(*, concept="Revenues", value=100, start="2024-01-01",
            end="2024-03-31", filed="2024-05-01",
            accession="0000320193-24-000001", cik="320193"):
    return SecFactRecord(
        cik=cik, taxonomy="us-gaap", concept=concept, label=concept,
        unit="USD", value=value, start=start, end=end, filed=filed,
        form="10-Q", accession=accession,
        filing_url=("https://www.sec.gov/Archives/edgar/data/320193/"
                    f"{accession.replace('-', '')}/{accession}-index.htm"),
    )


def test_builds_claim_level_yoy_evidence_bound_to_current_filing():
    prior = _record()
    current = _record(value=112, start="2025-01-01", end="2025-03-31",
                      filed="2025-05-01", accession="0000320193-25-000001")
    item = comparable_metric_evidence(
        [prior, current], ticker="AAPL", expected_cik="0000320193",
        concepts=("Revenues",), metric_name="revenue",
    )
    assert item is not None
    assert "increased 12.0%" in item.summary
    assert "to $112" in item.summary
    assert "from $100" in item.summary
    assert "period 2025-01-01 to 2025-03-31" in item.summary
    assert "prior-year period 2024-01-01 to 2024-03-31" in item.summary
    assert item.url == current.filing_url
    assert item.source == "SEC EDGAR — structured XBRL fact"
    assert item.source_type == "regulatory_filing"
    assert item.source_tier == "primary"
    assert item.claim_type == "reported_fact"
    assert item.document_type == "10-Q"
    assert item.reporting_period_start == "2025-01-01"
    assert item.reporting_period_end == "2025-03-31"
    assert item.extraction_method == "structured_xbrl"
    assert len(item.verified_claims) == 2
    current_claim, prior_claim = item.verified_claims
    assert current_claim["raw_value"] == 112
    assert current_claim["period"] == "quarter ended 2025-03-31"
    assert current_claim["scope"] == "consolidated"
    assert current_claim["currency"] == "USD"
    assert current_claim["document_ref"]["url"] == current.filing_url
    assert prior_claim["raw_value"] == 100
    assert prior_claim["document_ref"]["url"] == prior.filing_url


def test_structured_claim_flattening_deduplicates_and_rejects_unbound_claims():
    prior = _record(concept="NetCashProvidedByUsedInOperatingActivities", value=100)
    current = _record(
        concept=prior.concept, value=-25, start="2025-01-01",
        end="2025-03-31", filed="2025-05-01",
        accession="0000320193-25-000001",
    )
    item = comparable_metric_evidence(
        [prior, current], ticker="AAPL", expected_cik="320193",
        concepts=(prior.concept,), metric_name="operating cash flow",
    )
    assert item is not None
    from app.services.verified_sec_metric_service import structured_claims_from_evidence

    unbound = item.model_copy(deep=True)
    unbound.verified_claims = [{"metric": "us-gaap:Fake"}]
    claims = structured_claims_from_evidence([item, item, unbound])
    assert len(claims) == 2
    assert claims[0]["raw_value"] == -25
    assert claims[1]["raw_value"] == 100
    assert all(claim["document_ref"]["reference_id"] for claim in claims)


def test_prefers_quarter_over_ytd_for_same_period_end_and_filing():
    prior_quarter = _record()
    current_quarter = _record(
        value=112, start="2025-01-01", end="2025-03-31",
        filed="2025-05-01", accession="0000320193-25-000001",
    )
    current_ytd = replace(current_quarter, value=330, start="2024-07-01")
    item = comparable_metric_evidence(
        [prior_quarter, current_quarter, current_ytd],
        ticker="AAPL", expected_cik="320193",
        concepts=("Revenues",), metric_name="revenue",
    )
    assert item is not None
    assert "increased 12.0%" in item.summary
    assert "to $112" in item.summary
    assert "$330" not in item.summary


def test_annual_filing_prefers_full_year_over_embedded_fourth_quarter():
    prior_annual = replace(
        _record(), start="2023-07-01", end="2024-06-30", form="10-K",
        value=1_000, filed="2024-08-15",
    )
    current_annual = replace(
        prior_annual, start="2024-07-01", end="2025-06-30", value=1_200,
        filed="2025-08-14", accession="0000320193-25-000001",
        filing_url=("https://www.sec.gov/Archives/edgar/data/320193/"
                    "000032019325000001/0000320193-25-000001-index.htm"),
    )
    embedded_quarter = replace(
        current_annual, start="2025-04-01", value=350,
    )

    item = comparable_metric_evidence(
        [prior_annual, current_annual, embedded_quarter],
        ticker="AAPL", expected_cik="320193",
        concepts=("Revenues",), metric_name="revenue",
    )

    assert item is not None
    assert "increased 20.0%" in item.summary
    assert "to $1,200" in item.summary
    assert "$350" not in item.summary
    assert item.reporting_period_start == "2024-07-01"
    assert item.verified_claims[0]["period"] == "FY2025"


def test_profitability_requests_operating_and_net_income_without_losing_other_metrics():
    question = "How have revenue, profitability and operating cash flow changed?"
    requested = service._requested_metrics(question, include_defaults=False)
    assert [metric[1] for metric in requested] == [
        "revenue", "operating income", "net income", "operating cash flow",
    ]
    assert service._requested_metrics("What supports the investment thesis?", include_defaults=False) == ()
    assert service._requested_metrics("What supports the investment thesis?") == service._METRICS


def test_accepts_53_week_non_calendar_year_comparison():
    prior = replace(
        _record(), start="2023-07-02", end="2024-06-29", form="10-K",
        value=1_000, filed="2024-08-15",
    )
    current = replace(
        prior, start="2024-06-30", end="2025-07-05", value=1_100,
        filed="2025-08-14", accession="0000320193-25-000001",
        filing_url=("https://www.sec.gov/Archives/edgar/data/320193/"
                    "000032019325000001/0000320193-25-000001-index.htm"),
    )

    item = comparable_metric_evidence(
        [prior, current], ticker="AAPL", expected_cik="320193",
        concepts=("Revenues",), metric_name="revenue",
    )

    assert item is not None
    assert "increased 10.0%" in item.summary
    assert item.reporting_period_end == "2025-07-05"


def test_rejects_duration_that_cannot_match_filing_form():
    prior = replace(
        _record(), start="2023-01-01", end="2023-12-31", form="10-K",
        value=1_000, filed="2024-02-15",
    )
    malformed_current = replace(
        prior, start="2025-12-01", end="2025-12-31", value=1_100,
        filed="2026-02-15", accession="0000320193-26-000001",
    )

    assert comparable_metric_evidence(
        [prior, malformed_current], ticker="AAPL", expected_cik="320193",
        concepts=("Revenues",), metric_name="revenue",
    ) is None


def test_latest_amendment_replaces_original_period_observation():
    prior = _record()
    original = _record(
        value=110, start="2025-01-01", end="2025-03-31",
        filed="2025-05-01", accession="0000320193-25-000001",
    )
    amended = replace(
        original, value=112, filed="2025-05-15", form="10-Q/A",
        accession="0000320193-25-000002",
        filing_url=("https://www.sec.gov/Archives/edgar/data/320193/"
                    "000032019325000002/0000320193-25-000002-index.htm"),
    )

    item = comparable_metric_evidence(
        [prior, original, amended], ticker="AAPL", expected_cik="320193",
        concepts=("Revenues",), metric_name="revenue",
    )

    assert item is not None
    assert "increased 12.0%" in item.summary
    assert item.document_type == "10-Q/A"
    assert item.url == amended.filing_url


def test_identical_duplicate_observations_choose_deterministic_accession():
    prior = _record()
    current = _record(
        value=112, start="2025-01-01", end="2025-03-31",
        filed="2025-05-01", accession="0000320193-25-000001",
    )
    repeated = replace(
        current, accession="0000320193-25-000002",
        filing_url=("https://www.sec.gov/Archives/edgar/data/320193/"
                    "000032019325000002/0000320193-25-000002-index.htm"),
    )

    item = comparable_metric_evidence(
        [prior, current, repeated], ticker="AAPL", expected_cik="320193",
        concepts=("Revenues",), metric_name="revenue",
    )

    assert item is not None
    assert item.url == repeated.filing_url
    assert item.verified_claims[0]["document_ref"]["url"] == repeated.filing_url


def test_same_day_amendment_supersedes_conflicting_original():
    prior = _record()
    original = _record(
        value=110, start="2025-01-01", end="2025-03-31",
        filed="2025-05-01", accession="0000320193-25-000001",
    )
    amended = replace(
        original, value=112, form="10-Q/A",
        accession="0000320193-25-000002",
        filing_url=("https://www.sec.gov/Archives/edgar/data/320193/"
                    "000032019325000002/0000320193-25-000002-index.htm"),
    )

    item = comparable_metric_evidence(
        [prior, original, amended], ticker="AAPL", expected_cik="320193",
        concepts=("Revenues",), metric_name="revenue",
    )

    assert item is not None
    assert "increased 12.0%" in item.summary
    assert item.document_type == "10-Q/A"
    assert item.url == amended.filing_url


def test_conflicting_amendments_for_same_period_fail_closed():
    prior = _record()
    amendment = _record(
        value=110, start="2025-01-01", end="2025-03-31",
        filed="2025-05-15", accession="0000320193-25-000002",
    )
    amendment = replace(amendment, form="10-Q/A")
    conflict = replace(
        amendment, value=112, accession="0000320193-25-000003",
        filing_url=("https://www.sec.gov/Archives/edgar/data/320193/"
                    "000032019325000003/0000320193-25-000003-index.htm"),
    )

    assert comparable_metric_evidence(
        [prior, amendment, conflict], ticker="AAPL", expected_cik="320193",
        concepts=("Revenues",), metric_name="revenue",
    ) is None


def test_mixed_annual_and_quarterly_filing_families_fail_closed():
    prior = _record()
    current_quarter = _record(
        value=112, start="2025-01-01", end="2025-03-31",
        filed="2025-05-01", accession="0000320193-25-000001",
    )
    annual = replace(
        current_quarter, form="10-K", start="2024-04-01", value=450,
        accession="0000320193-25-000002",
        filing_url=("https://www.sec.gov/Archives/edgar/data/320193/"
                    "000032019325000002/0000320193-25-000002-index.htm"),
    )

    assert comparable_metric_evidence(
        [prior, current_quarter, annual], ticker="AAPL", expected_cik="320193",
        concepts=("Revenues",), metric_name="revenue",
    ) is None


def test_rejects_wrong_entity_missing_comparable_and_ambiguous_concepts():
    prior = _record()
    current = _record(value=112, start="2025-01-01", end="2025-03-31",
                      filed="2025-05-01", accession="0000320193-25-000001")
    args = dict(
        ticker="AAPL", expected_cik="320193",
        concepts=("Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax"),
        metric_name="revenue",
    )
    assert comparable_metric_evidence([current], **args) is None
    assert comparable_metric_evidence([prior, replace(current, cik="1318605")], **args) is None
    alternate = replace(current, concept="RevenueFromContractWithCustomerExcludingAssessedTax")
    assert comparable_metric_evidence([prior, current, alternate], **args) is None


def test_service_fetches_once_and_returns_supported_metrics(monkeypatch):
    prior_revenue = _record()
    current_revenue = _record(value=110, start="2025-01-01", end="2025-03-31",
                              filed="2025-05-01", accession="0000320193-25-000001")
    prior_cash = replace(prior_revenue, concept="NetCashProvidedByUsedInOperatingActivities")
    current_cash = replace(current_revenue, concept=prior_cash.concept, value=120)
    calls = []
    monkeypatch.setattr(service, "_load_ticker_cik_map", lambda: {"AAPL": "0000320193"})
    monkeypatch.setattr(
        service, "get_company_fact_records_for_concept_units",
        lambda *args, **kwargs: calls.append((args, kwargs)) or
        [prior_revenue, current_revenue, prior_cash, current_cash],
    )
    evidence = service.fetch_verified_metric_evidence("AAPL")
    assert len(calls) == 1
    assert [item.title.split(":")[0] for item in evidence] == [
        "AAPL revenue", "AAPL operating cash flow"]
    assert service.fetch_verified_metric_evidence("AAPL/../") == []


def test_service_supports_general_company_metric_family(monkeypatch):
    prior = _record()
    current = _record(value=110, start="2025-01-01", end="2025-03-31",
                      filed="2025-05-01", accession="0000320193-25-000001")
    concepts = {
        "GrossProfit": (80, 88),
        "NetIncomeLoss": (50, 55),
        "ResearchAndDevelopmentExpense": (20, 24),
        "PaymentsToAcquirePropertyPlantAndEquipment": (10, 12),
        "ShareBasedCompensation": (5, 6),
        "PaymentsForRepurchaseOfCommonStock": (15, 18),
        "PaymentsOfDividendsCommonStock": (4, 5),
    }
    records = []
    for concept, (prior_value, current_value) in concepts.items():
        records.extend([
            replace(prior, concept=concept, value=prior_value),
            replace(current, concept=concept, value=current_value),
        ])
    requested = []
    monkeypatch.setattr(service, "_load_ticker_cik_map", lambda: {"AAPL": "320193"})
    monkeypatch.setattr(
        service, "get_company_fact_records_for_concept_units",
        lambda *args, **kwargs: requested.append(kwargs["concept_units"]) or records,
    )

    evidence = service.fetch_verified_metric_evidence("AAPL")

    titles = [item.title.split(":")[0] for item in evidence]
    assert titles == [
        "AAPL gross profit", "AAPL net income",
        "AAPL research and development", "AAPL capital expenditure",
        "AAPL stock-based compensation", "AAPL share repurchases",
        "AAPL dividends paid",
    ]
    assert {(concept, "USD") for concept in concepts}.issubset(set(requested[0]))


def test_free_cash_flow_preserves_formula_and_exact_input_references(monkeypatch):
    prior_ocf = _record(
        concept="NetCashProvidedByUsedInOperatingActivities", value=500,
    )
    current_ocf = _record(
        concept=prior_ocf.concept, value=620, start="2025-01-01",
        end="2025-03-31", filed="2025-05-01",
        accession="0000320193-25-000001",
    )
    prior_capex = _record(
        concept="PaymentsToAcquirePropertyPlantAndEquipment", value=120,
    )
    current_capex = _record(
        concept=prior_capex.concept, value=150, start="2025-01-01",
        end="2025-03-31", filed="2025-05-01",
        accession="0000320193-25-000001",
    )
    records = [prior_ocf, current_ocf, prior_capex, current_capex]
    monkeypatch.setattr(service, "_load_ticker_cik_map", lambda: {"AAPL": "320193"})
    monkeypatch.setattr(
        service, "get_company_fact_records_for_concept_units",
        lambda *args, **kwargs: records,
    )

    evidence = service.fetch_verified_metric_evidence(
        "AAPL", question="What is Apple's latest free cash flow trend?",
    )
    calculations = service.structured_calculations_from_evidence(evidence)

    assert len(evidence) == 2
    assert len(calculations) == 2
    current = next(item for item in calculations if item["period"] == "quarter ended 2025-03-31")
    assert current["provenance"] == "derived"
    assert current["raw_value"] == "470"
    assert current["formula"] == "operating_cash_flow - capital_expenditure"
    assert [item["role"] for item in current["inputs"]] == [
        "operating_cash_flow", "capital_expenditure",
    ]
    assert all(item["unit"] == "USD" for item in current["inputs"])
    assert all(item["reference_id"].startswith("sec:320193:") for item in current["inputs"])
    assert all("document_ref" not in item for item in calculations)


def test_free_cash_flow_calculates_only_exactly_compatible_periods(monkeypatch):
    prior_ocf = _record(
        concept="NetCashProvidedByUsedInOperatingActivities", value=500,
    )
    current_ocf = _record(
        concept=prior_ocf.concept, value=620, start="2025-01-01",
        end="2025-03-31", filed="2025-05-01",
        accession="0000320193-25-000001",
    )
    prior_capex = _record(
        concept="PaymentsToAcquirePropertyPlantAndEquipment", value=120,
        start="2023-01-01", end="2023-03-31", filed="2023-05-01",
        accession="0000320193-23-000001",
    )
    current_capex = _record(
        concept=prior_capex.concept, value=150, start="2024-01-01",
        end="2024-03-31", filed="2024-05-01",
        accession="0000320193-24-000001",
    )
    monkeypatch.setattr(service, "_load_ticker_cik_map", lambda: {"AAPL": "320193"})
    monkeypatch.setattr(
        service, "get_company_fact_records_for_concept_units",
        lambda *args, **kwargs: [prior_ocf, current_ocf, prior_capex, current_capex],
    )

    evidence = service.fetch_verified_metric_evidence(
        "AAPL", question="What is Apple's free cash flow?",
    )

    calculations = service.structured_calculations_from_evidence(evidence)
    assert [item["period"] for item in calculations] == [
        "quarter ended 2024-03-31",
    ]
    assert all(item["period"] != "quarter ended 2025-03-31" for item in calculations)


def test_service_narrows_explicit_metric_question_before_sec_fetch(monkeypatch):
    prior = replace(_record(), concept="ResearchAndDevelopmentExpense", value=20)
    current = replace(
        prior, value=24, start="2025-01-01", end="2025-03-31",
        filed="2025-05-01", accession="0000320193-25-000001",
    )
    requested = []
    monkeypatch.setattr(service, "_load_ticker_cik_map", lambda: {"AAPL": "320193"})
    monkeypatch.setattr(
        service, "get_company_fact_records_for_concept_units",
        lambda *args, **kwargs: requested.append(kwargs["concept_units"]) or [prior, current],
    )

    evidence = service.fetch_verified_metric_evidence(
        "AAPL", question="Which source supports Apple's latest R&D growth?",
    )

    assert requested == [(('ResearchAndDevelopmentExpense', 'USD'), ('Assets', 'USD'))]
    assert len(evidence) == 1
    assert evidence[0].title.startswith("AAPL research and development:")


def test_metric_selection_does_not_expand_gross_profit_to_net_income():
    selected = service._requested_metrics(
        "Which source supports the latest gross profit comparison?",
    )
    assert [(metric_name, concepts) for concepts, metric_name, _, _, _ in selected] == [
        ("gross profit", ("GrossProfit",)),
    ]


def test_duration_comparison_formats_shares_and_per_share_units():
    prior_eps = replace(_record(), concept="EarningsPerShareDiluted", unit="USD/shares", value=1.5)
    current_eps = replace(
        prior_eps, value=1.8, start="2025-01-01", end="2025-03-31",
        filed="2025-05-01", accession="0000320193-25-000001",
        filing_url=("https://www.sec.gov/Archives/edgar/data/320193/"
                    "000032019325000001/0000320193-25-000001-index.htm"),
    )
    eps = comparable_metric_evidence(
        [prior_eps, current_eps], ticker="AAPL", expected_cik="320193",
        concepts=("EarningsPerShareDiluted",), metric_name="diluted EPS",
        unit="USD/shares",
    )
    assert eps is not None
    assert "$1.80 per share" in eps.summary
    assert "$1.50 per share" in eps.summary
    assert len(eps.verified_claims) == 2
    assert eps.verified_claims[0]["value_text"] == "$1.8 per share"
    assert eps.verified_claims[0]["unit"] == "USD/shares"
    assert eps.verified_claims[0]["currency"] == "USD"
    assert eps.verified_claims[0]["document_ref"]["reference_id"].endswith(
        ":us-gaap:EarningsPerShareDiluted"
    )

    prior_shares = replace(
        _record(), concept="WeightedAverageNumberOfDilutedSharesOutstanding",
        unit="shares", value=1_000_000_000,
    )
    current_shares = replace(
        prior_shares, value=900_000_000, start="2025-01-01", end="2025-03-31",
        filed="2025-05-01", accession="0000320193-25-000001",
        filing_url=("https://www.sec.gov/Archives/edgar/data/320193/"
                    "000032019325000001/0000320193-25-000001-index.htm"),
    )
    shares = comparable_metric_evidence(
        [prior_shares, current_shares], ticker="AAPL", expected_cik="320193",
        concepts=("WeightedAverageNumberOfDilutedSharesOutstanding",),
        metric_name="diluted share count", unit="shares",
    )
    assert shares is not None
    assert "900M shares" in shares.summary


def test_instant_comparison_uses_point_in_time_semantics_and_filing_url():
    prior = replace(_record(), concept="CashAndCashEquivalentsAtCarryingValue",
                    start=None, value=20_000_000_000)
    current = replace(
        prior, value=25_000_000_000, end="2025-03-31", filed="2025-05-01",
        accession="0000320193-25-000001",
    )
    item = comparable_instant_metric_evidence(
        [prior, current], ticker="AAPL", expected_cik="0000320193",
        concepts=("CashAndCashEquivalentsAtCarryingValue",),
        metric_name="cash and cash equivalents",
    )
    assert item is not None
    assert "increased 25.0% to $25B as of 2025-03-31" in item.summary
    assert "from $20B as of the comparable prior-year date" in item.summary
    assert item.url == current.filing_url
    assert item.reporting_period_start is None
    assert item.reporting_period_end == "2025-03-31"
    assert item.filed_at == "2025-05-01"


def test_instant_comparison_rejects_duration_wrong_unit_and_ambiguity():
    prior = replace(_record(), concept="LongTermDebt", start=None, value=100)
    current = replace(
        prior, value=90, end="2025-03-31", filed="2025-05-01",
        accession="0000320193-25-000001",
    )
    args = dict(
        ticker="AAPL", expected_cik="320193", concepts=("LongTermDebt",),
        metric_name="total debt",
    )
    assert comparable_instant_metric_evidence([prior, replace(current, start="2025-01-01")], **args) is None
    assert comparable_instant_metric_evidence([prior, replace(current, unit="shares")], **args) is None
    alternate = replace(current, value=91, accession="0000320193-25-000002")
    assert comparable_instant_metric_evidence([prior, current, alternate], **args) is None


def test_service_fetches_mixed_units_once_and_routes_period_semantics(monkeypatch):
    prior_cash = replace(_record(), concept="CashAndCashEquivalentsAtCarryingValue",
                         start=None, value=20_000_000_000)
    current_cash = replace(
        prior_cash, value=25_000_000_000, end="2025-03-31", filed="2025-05-01",
        accession="0000320193-25-000001",
    )
    calls = []
    monkeypatch.setattr(service, "_load_ticker_cik_map", lambda: {"AAPL": "320193"})
    monkeypatch.setattr(
        service, "get_company_fact_records_for_concept_units",
        lambda *args, **kwargs: calls.append(kwargs["concept_units"]) or [prior_cash, current_cash],
    )
    evidence = service.fetch_verified_metric_evidence(
        "AAPL", question="Which source supports Apple's cash balance?",
    )
    assert calls == [(('CashAndCashEquivalentsAtCarryingValue', 'USD'), ('Assets', 'USD'))]
    assert len(evidence) == 1
    assert evidence[0].title.startswith("AAPL cash and cash equivalents:")


def test_service_uses_ordered_concept_fallback_without_mixing_aliases(monkeypatch):
    prior = replace(_record(), concept="LongTermDebt", start=None, value=100)
    current = replace(
        prior, value=90, end="2025-03-31", filed="2025-05-01",
        accession="0000320193-25-000001",
    )
    broader_current_only = replace(
        current, concept="LongTermDebtAndFinanceLeaseObligations", value=95,
    )
    monkeypatch.setattr(service, "_load_ticker_cik_map", lambda: {"AAPL": "320193"})
    monkeypatch.setattr(
        service, "get_company_fact_records_for_concept_units",
        lambda *args, **kwargs: [prior, current, broader_current_only],
    )
    evidence = service.fetch_verified_metric_evidence(
        "AAPL", question="Which source supports Apple's total debt comparison?",
    )
    assert len(evidence) == 1
    assert "decreased 10.0%" in evidence[0].summary


def test_bank_metric_pack_uses_correct_period_semantics(monkeypatch):
    prior_flow = _record(concept="InterestIncomeExpenseNet", value=10_000_000_000)
    current_flow = replace(
        prior_flow, value=11_000_000_000, start="2025-01-01", end="2025-03-31",
        filed="2025-05-01", accession="0000320193-25-000001",
    )
    prior_deposits = replace(_record(), concept="Deposits", start=None,
                             value=1_000_000_000_000)
    current_deposits = replace(
        prior_deposits, value=1_100_000_000_000, end="2025-03-31",
        filed="2025-05-01", accession="0000320193-25-000001",
    )
    monkeypatch.setattr(service, "_load_ticker_cik_map", lambda: {"JPM": "320193"})
    monkeypatch.setattr(
        service, "get_company_fact_records_for_concept_units",
        lambda *args, **kwargs: [prior_flow, current_flow, prior_deposits, current_deposits],
    )

    interest = service.fetch_verified_metric_evidence(
        "JPM", question="Which source supports JPM's net interest income growth?",
    )
    deposits = service.fetch_verified_metric_evidence(
        "JPM", question="Which source supports JPM's total deposits?",
    )

    assert len(interest) == 1
    assert "for the period 2025-01-01 to 2025-03-31" in interest[0].summary
    assert interest[0].title.startswith("JPM net interest income:")
    assert len(deposits) == 1
    assert "as of 2025-03-31" in deposits[0].summary
    assert deposits[0].title.startswith("JPM deposits:")


def test_bank_metric_pack_has_question_aware_concept_and_unit_mapping():
    cases = {
        "net interest income": ("InterestIncomeExpenseNet", "USD", "duration"),
        "total deposits": ("Deposits", "USD", "instant"),
        "net loans": (
            "FinancingReceivableExcludingAccruedInterestAfterAllowanceForCreditLoss",
            "USD", "instant",
        ),
        "allowance for credit losses": (
            "FinancingReceivableAllowanceForCreditLossExcludingAccruedInterest",
            "USD", "instant",
        ),
        "credit loss provision": (
            "FinancingReceivableExcludingAccruedInterestCreditLossExpenseReversal",
            "USD", "duration",
        ),
        "gross charge-offs": (
            "FinancingReceivableExcludingAccruedInterestAllowanceForCreditLossWriteoff",
            "USD", "duration",
        ),
        "net charge-offs": (
            "FinancingReceivableExcludingAccruedInterestAllowanceForCreditLossWriteoffAfterRecovery",
            "USD", "duration",
        ),
    }
    for phrase, expected in cases.items():
        selected = service._requested_metrics(f"Which source supports the latest {phrase}?")
        assert len(selected) == 1
        concepts, _, _, unit, period_kind = selected[0]
        assert (concepts[0], unit, period_kind) == expected


def test_insurer_metric_pack_uses_correct_period_semantics(monkeypatch):
    prior_premiums = _record(concept="PremiumsEarnedNet", value=10_000_000_000)
    current_premiums = replace(
        prior_premiums, value=11_000_000_000, start="2025-01-01", end="2025-03-31",
        filed="2025-05-01", accession="0000320193-25-000001",
    )
    prior_reserve = replace(_record(), concept="UnearnedPremiums", start=None,
                            value=20_000_000_000)
    current_reserve = replace(
        prior_reserve, value=22_000_000_000, end="2025-03-31",
        filed="2025-05-01", accession="0000320193-25-000001",
    )
    monkeypatch.setattr(service, "_load_ticker_cik_map", lambda: {"CB": "320193"})
    monkeypatch.setattr(
        service, "get_company_fact_records_for_concept_units",
        lambda *args, **kwargs: [
            prior_premiums, current_premiums, prior_reserve, current_reserve,
        ],
    )

    premiums = service.fetch_verified_metric_evidence(
        "CB", question="Which source supports Chubb's net premiums earned?",
    )
    reserves = service.fetch_verified_metric_evidence(
        "CB", question="Which source supports Chubb's unearned premium reserve?",
    )

    assert len(premiums) == 1
    assert "for the period 2025-01-01 to 2025-03-31" in premiums[0].summary
    assert premiums[0].title.startswith("CB net premiums earned:")
    assert len(reserves) == 1
    assert "as of 2025-03-31" in reserves[0].summary
    assert reserves[0].title.startswith("CB unearned premium reserve:")


def test_insurer_metric_pack_has_question_aware_concept_mapping():
    cases = {
        "net premiums earned": ("PremiumsEarnedNet", "duration"),
        "net premiums written": ("PremiumsWrittenNet", "duration"),
        "claims incurred": ("PolicyholderBenefitsAndClaimsIncurredNet", "duration"),
        "net investment income": ("NetInvestmentIncome", "duration"),
        "unearned premium reserve": ("UnearnedPremiums", "instant"),
        "loss reserves": (
            "SupplementalInformationForPropertyCasualtyInsuranceUnderwritersReservesForUnpaidClaimsAndClaimsAdjustmentExpense",
            "instant",
        ),
    }
    for phrase, expected in cases.items():
        selected = service._requested_metrics(f"Which source supports the latest {phrase}?")
        assert len(selected) == 1
        concepts, _, _, unit, period_kind = selected[0]
        assert unit == "USD"
        assert (concepts[0], period_kind) == expected


def test_saas_metric_pack_uses_correct_period_semantics(monkeypatch):
    prior_rpo = replace(_record(), concept="RevenueRemainingPerformanceObligation",
                        start=None, value=100_000_000_000)
    current_rpo = replace(
        prior_rpo, value=120_000_000_000, end="2025-03-31", filed="2025-05-01",
        accession="0000320193-25-000001",
    )
    prior_recognized = replace(
        _record(), concept="ContractWithCustomerLiabilityRevenueRecognized",
        value=10_000_000_000,
    )
    current_recognized = replace(
        prior_recognized, value=11_000_000_000, start="2025-01-01",
        end="2025-03-31", filed="2025-05-01",
        accession="0000320193-25-000001",
    )
    monkeypatch.setattr(service, "_load_ticker_cik_map", lambda: {"MSFT": "320193"})
    monkeypatch.setattr(
        service, "get_company_fact_records_for_concept_units",
        lambda *args, **kwargs: [
            prior_rpo, current_rpo, prior_recognized, current_recognized,
        ],
    )

    rpo = service.fetch_verified_metric_evidence(
        "MSFT", question="Which source supports Microsoft's RPO growth?",
    )
    recognized = service.fetch_verified_metric_evidence(
        "MSFT", question="Which source supports contract liability revenue recognition?",
    )

    assert len(rpo) == 1
    assert "as of 2025-03-31" in rpo[0].summary
    assert rpo[0].title.startswith("MSFT remaining performance obligations:")
    assert len(recognized) == 1
    assert "for the period 2025-01-01 to 2025-03-31" in recognized[0].summary


def test_saas_metric_pack_has_question_aware_concept_mapping():
    cases = {
        "rpo": ("RevenueRemainingPerformanceObligation", "instant"),
        "total deferred revenue": ("ContractWithCustomerLiability", "instant"),
        "deferred revenue": ("ContractWithCustomerLiabilityCurrent", "instant"),
        "noncurrent contract liabilities": (
            "ContractWithCustomerLiabilityNoncurrent", "instant",
        ),
        "revenue recognized from contract liabilities": (
            "ContractWithCustomerLiabilityRevenueRecognized", "duration",
        ),
    }
    for phrase, expected in cases.items():
        selected = service._requested_metrics(f"Which source supports the latest {phrase}?")
        assert len(selected) == 1
        concepts, _, _, unit, period_kind = selected[0]
        assert unit == "USD"
        assert (concepts[0], period_kind) == expected


def test_metric_selection_prefers_specific_phrases_and_keeps_multi_metric_queries():
    selected = service._requested_metrics(
        "Which source supports total deferred revenue?",
    )
    assert [metric_name for _, metric_name, _, _, _ in selected] == [
        "total contract liabilities",
    ]

    selected = service._requested_metrics(
        "Which sources support revenue and net income?",
    )
    assert [metric_name for _, metric_name, _, _, _ in selected] == [
        "revenue", "net income",
    ]

    selected = service._requested_metrics(
        "Compare current contract liabilities with noncurrent contract liabilities.",
    )
    assert [metric_name for _, metric_name, _, _, _ in selected] == [
        "current contract liabilities", "noncurrent contract liabilities",
    ]


def test_service_rejects_metric_far_older_than_latest_issuer_period(monkeypatch):
    prior = replace(
        _record(), concept="ContractWithCustomerLiabilityRevenueRecognized",
        value=10_000_000_000, start="2019-01-01", end="2019-03-31",
        filed="2019-05-01", accession="0000320193-19-000001",
    )
    stale_current = replace(
        prior, value=11_000_000_000, start="2020-01-01", end="2020-03-31",
        filed="2020-05-01", accession="0000320193-20-000001",
    )
    latest_assets = replace(
        _record(), concept="Assets", start=None, value=100_000_000_000,
        end="2026-03-31", filed="2026-05-01",
        accession="0000320193-26-000001",
    )
    monkeypatch.setattr(service, "_load_ticker_cik_map", lambda: {"MSFT": "320193"})
    monkeypatch.setattr(
        service, "get_company_fact_records_for_concept_units",
        lambda *args, **kwargs: [prior, stale_current, latest_assets],
    )
    assert service.fetch_verified_metric_evidence(
        "MSFT", question="Which source supports contract liability revenue recognition?",
    ) == []


def test_reit_metric_pack_uses_correct_period_semantics(monkeypatch):
    prior_income = _record(concept="LeaseIncome", value=1_000_000_000)
    current_income = replace(
        prior_income, value=1_100_000_000, start="2025-01-01", end="2025-03-31",
        filed="2025-05-01", accession="0000320193-25-000001",
    )
    prior_property = replace(_record(), concept="RealEstateInvestmentPropertyNet",
                             start=None, value=20_000_000_000)
    current_property = replace(
        prior_property, value=22_000_000_000, end="2025-03-31",
        filed="2025-05-01", accession="0000320193-25-000001",
    )
    monkeypatch.setattr(service, "_load_ticker_cik_map", lambda: {"O": "320193"})
    monkeypatch.setattr(
        service, "get_company_fact_records_for_concept_units",
        lambda *args, **kwargs: [
            prior_income, current_income, prior_property, current_property,
        ],
    )

    income = service.fetch_verified_metric_evidence(
        "O", question="Which source supports Realty Income's lease income?",
    )
    property_value = service.fetch_verified_metric_evidence(
        "O", question="Which source supports Realty Income's net investment property?",
    )

    assert len(income) == 1
    assert "for the period 2025-01-01 to 2025-03-31" in income[0].summary
    assert len(property_value) == 1
    assert "as of 2025-03-31" in property_value[0].summary


def test_reit_metric_pack_has_question_aware_concept_mapping():
    cases = {
        "lease income": ("LeaseIncome", "duration"),
        "net investment property": ("RealEstateInvestmentPropertyNet", "instant"),
        "investment property at cost": ("RealEstateInvestmentPropertyAtCost", "instant"),
        "real estate accumulated depreciation": (
            "RealEstateInvestmentPropertyAccumulatedDepreciation", "instant",
        ),
        "real estate acquisitions": ("PaymentsToAcquireCommercialRealEstate", "duration"),
        "real estate disposition proceeds": (
            "ProceedsFromRealEstateAndRealEstateJointVentures", "duration",
        ),
        "secured debt": ("SecuredDebt", "instant"),
        "real estate impairment": ("ImpairmentOfRealEstate", "duration"),
    }
    for phrase, expected in cases.items():
        selected = service._requested_metrics(f"Which source supports the latest {phrase}?")
        assert len(selected) == 1
        concepts, _, _, unit, period_kind = selected[0]
        assert unit == "USD"
        assert (concepts[0], period_kind) == expected
