import pytest

from app.integrity.sec_metric_evidence import comparable_metric_evidence
from app.providers.sec_client import SecFactRecord
from app.schemas import InvestmentThesis
from app.services.financial_thesis_foundation import build_financial_foundation
from app.services.source_answer import apply_source_answer_gate
from app.services.verified_sec_metric_service import _requested_metrics


def evidence(concept, name, *, ticker="AAPL", cik="320193", current=120, prior=100, ytd=False):
    records = []
    for year, amount in ((2024, prior), (2025, current)):
        accession = f"{int(cik):010d}-{str(year)[-2:]}-000001"
        records.append(SecFactRecord(
            cik=cik, taxonomy="us-gaap", concept=concept, label=concept, unit="USD",
            value=amount, start=f"{year}-{'01' if ytd else '04'}-01", end=f"{year}-06-30",
            filed=f"{year}-08-01", form="10-Q", accession=accession,
            filing_url=f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession.replace('-', '')}/{accession}-index.htm",
        ))
    return comparable_metric_evidence(records, ticker=ticker, expected_cik=cik,
                                     concepts=(concept,), metric_name=name)


def pair(**kwargs):
    return [evidence("Revenues", "revenue", **kwargs),
            evidence("OperatingIncomeLoss", "operating income", **kwargs)]


def reference(item, identifier):
    return {"id": identifier, "title": item.title, "source": item.source,
            "url": item.url, "published_at": item.timestamp}


def test_mixed_trends_produce_cited_counter_evidence_and_conditional_tests():
    items = [evidence("Revenues", "revenue"),
             evidence("OperatingIncomeLoss", "operating income", current=40)]
    result = build_financial_foundation("AAPL", items, None, expected_cik="320193")
    assert "revenue [E1]" in result["answer"]
    assert "Counter-evidence" in result["answer"]
    assert result["inferences"][1]["signal"] == "counter_evidence"
    assert all("not a forecast" in row["conditional_test"] for row in result["inferences"])
    assert result["unanswered_parts"][:2] == ["net income", "operating cash flow"]
    assert "buy/sell recommendation" in result["answer"]


def test_loss_reduction_is_not_promoted_to_positive_profitability():
    items = [evidence("Revenues", "revenue"),
             evidence("NetIncomeLoss", "net income", current=-50, prior=-100)]
    result = build_financial_foundation("AAPL", items, None, expected_cik="320193")
    assert result["inferences"][1]["signal"] == "counter_evidence"
    assert "non-positive" in result["inferences"][1]["text"]


def test_quarter_and_ytd_are_not_combined_into_cash_conversion_or_causality():
    items = pair() + [evidence("NetCashProvidedByUsedInOperatingActivities", "operating cash flow", ytd=True)]
    result = build_financial_foundation("AAPL", items, None, expected_cik="320193")
    assert result["common_reporting_period"] is False
    assert "different reporting durations" in result["answer"]
    assert "2025-01-01 to 2025-06-30" in result["answer"]
    assert "do not establish a common-period" in result["answer"]
    assert items[-1].verified_claims[0]["period"] == "year-to-date period 2025-01-01 to 2025-06-30"


@pytest.mark.parametrize("mutation", [
    lambda item: setattr(item, "summary", "Invented strong financial support."),
    lambda item: setattr(item, "url", "https://example.com/unrelated.htm"),
    lambda item: setattr(item, "freshness_status", "conflicting"),
    lambda item: item.verified_claims[0].update(ticker="TSLA"),
    lambda item: item.verified_claims[0].update(scope="segment"),
    lambda item: item.verified_claims[0].update(raw_value=999),
    lambda item: item.verified_claims[0].update(raw_value=True),
    lambda item: item.verified_claims[0].update(provenance="estimated"),
    lambda item: item.verified_claims[0].update(period_start="2025-01-01"),
    lambda item: item.verified_claims[0]["document_ref"].update(reference_id="invented"),
    lambda item: item.verified_claims[0]["document_ref"].update(published_at="2099-01-01"),
    lambda item: item.verified_claims.pop(),
])
def test_tampered_or_unbound_comparison_cannot_form_financial_case(mutation):
    items = pair()
    mutation(items[0])
    assert build_financial_foundation("AAPL", items, None, expected_cik="320193") is None


def test_wrong_trusted_identity_cannot_authorize_producer_claims():
    assert build_financial_foundation("AAPL", pair(), None, expected_cik="1318605") is None


def test_canonical_response_reference_ids_survive_unrelated_and_missing_references():
    items = pair()
    refs = [reference(items[0], "E4"), reference(items[1], "E9")]
    result = build_financial_foundation("AAPL", items, refs, expected_cik="320193")
    assert [row["reference_id"] for row in result["claims"]] == ["E4", "E9"]
    assert build_financial_foundation("AAPL", items, refs[:1], expected_cik="320193") is None


def test_conflicting_comparisons_are_withheld_rather_than_first_row_winning():
    items = pair() + [evidence("Revenues", "revenue", current=180)]
    assert build_financial_foundation("AAPL", items, None, expected_cik="320193") is None


@pytest.mark.parametrize("ticker,cik", [("AAPL", "320193"), ("AA", "1675149"), ("ACHC", "1520697"), ("TSLA", "1318605")])
def test_source_gate_uses_financial_foundation_across_sizes_without_inventing_conviction(monkeypatch, ticker, cik):
    monkeypatch.setattr("app.services.providers.sec_provider._load_ticker_cik_map", lambda: {ticker: cik})
    thesis = InvestmentThesis(ticker=ticker, company_name=ticker, confidence_score=0,
                              score_source="not_assessed_evidence_view")
    result = apply_source_answer_gate(thesis,
        f"What is the investment thesis for {ticker}, what supports it, and what could invalidate it? Cite material claims.",
        pair(ticker=ticker, cik=cik))
    assert result["status"] == "partial"
    assert len(result["claims"]) == 2
    assert "Financial thesis foundation" in thesis.direct_answer
    assert "issuer-disclosed operating-risk mechanisms" in result["unanswered_parts"]
    assert thesis.confidence_score == 0
    assert thesis.directional_stance == ""
    assert thesis.score_source == "not_assessed_evidence_view"


def test_broad_thesis_retrieval_is_bounded_to_core_financial_metrics():
    question = "What is the investment thesis for Acadia Healthcare? Cite material claims."
    assert [metric[1] for metric in _requested_metrics(question)] == [
        "revenue", "operating income", "net income", "operating cash flow",
    ]
    assert _requested_metrics(question, include_defaults=False) == ()


@pytest.mark.parametrize("question", [
    "What is the investment thesis for Apple's Services, and what could invalidate it? Cite material claims.",
    "What is the investment thesis for Apple's supply chain, and what risks could invalidate it? Cite material claims.",
])
def test_company_wide_foundation_cannot_substitute_for_named_segment_or_risk(question, monkeypatch):
    monkeypatch.setattr("app.services.providers.sec_provider._load_ticker_cik_map", lambda: {"AAPL": "320193"})
    thesis = InvestmentThesis(ticker="AAPL", company_name="Apple")
    result = apply_source_answer_gate(thesis, question, pair())
    assert result["status"] == "insufficient_claim_evidence"
    assert "Financial thesis foundation (partial)" not in thesis.direct_answer


def test_named_cloud_thesis_without_risk_wording_cannot_receive_company_wide_foundation(monkeypatch):
    monkeypatch.setattr("app.services.providers.sec_provider._load_ticker_cik_map", lambda: {"AAPL": "320193"})
    thesis = InvestmentThesis(ticker="AAPL", company_name="Apple")
    result = apply_source_answer_gate(thesis, "What is the investment thesis for Apple's cloud operations? Cite material claims.", pair())
    assert result["status"] == "partial"
    assert "Financial thesis foundation (partial)" not in thesis.direct_answer
    assert "investment thesis and its supporting/invalidation mechanisms" in result["unanswered_parts"]

PRETAX = "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest"


def profitability_items():
    return [evidence("Revenues", "revenue"), evidence("NetIncomeLoss", "net income"),
            evidence("NetCashProvidedByUsedInOperatingActivities", "operating cash flow"),
            evidence(PRETAX, "pretax income", current=60, prior=100)]


def test_pretax_is_cited_supplement_without_closing_operating_income_or_changing_inferences():
    items = profitability_items()
    result = build_financial_foundation("AAPL", items, [reference(x, f"E{i+7}") for i, x in enumerate(items)], expected_cik="320193")
    baseline = build_financial_foundation("AAPL", items[:-1], None, expected_cik="320193")
    assert len(result["claims"]) == 4
    assert result["claims"][-1]["claim_kind"] == "supplementary_profitability_comparison"
    assert result["claims"][-1]["reference_id"] == "E10"
    assert "operating income" in result["unanswered_parts"]
    assert [x["metric"] for x in result["inferences"]] == [x["metric"] for x in baseline["inferences"]]
    assert "Operating income remains unverified" in result["answer"]
    assert "does not establish operating income or an operating margin" in result["answer"]


def test_pretax_does_not_satisfy_minimum_core_evidence_or_replace_available_operating_income():
    supplemental = evidence(PRETAX, "pretax income")
    assert build_financial_foundation("AAPL", [pair()[0], supplemental], None, expected_cik="320193") is None
    result = build_financial_foundation("AAPL", pair() + [supplemental], None, expected_cik="320193")
    assert len(result["claims"]) == 2
    assert supplemental not in result["selected_items"]


@pytest.mark.parametrize("problem", ["tampered", "conflicting", "missing_reference"])
def test_unqualified_pretax_cannot_enter_foundation(problem):
    items = profitability_items()
    refs = [reference(x, f"E{i+1}") for i, x in enumerate(items)]
    if problem == "tampered":
        items[-1].verified_claims[0]["raw_value"] = 999
    elif problem == "conflicting":
        items.append(evidence(PRETAX, "pretax income", current=180))
        refs.append(reference(items[-1], "E5"))
    else:
        refs.pop()
    result = build_financial_foundation("AAPL", items, refs, expected_cik="320193")
    assert len(result["claims"]) == 3
    assert "operating income" in result["unanswered_parts"]
    assert "supplementary profitability context" not in result["answer"]


@pytest.mark.parametrize("problem", [None, "tampered", "conflicting"])
def test_financial_view_keeps_operating_gap_with_validated_pretax(monkeypatch, problem):
    monkeypatch.setattr("app.services.providers.sec_provider._load_ticker_cik_map", lambda: {"AAPL": "320193"})
    items = profitability_items()
    if problem == "tampered":
        items[-1].summary = "Invented pretax result."
    elif problem == "conflicting":
        items.append(evidence(PRETAX, "pretax income", current=180))
    thesis = InvestmentThesis(ticker="AAPL", company_name="Apple")
    result = apply_source_answer_gate(thesis, "How have revenue, profitability and operating cash flow changed? Cite sources.", items)
    assert result["status"] == "partial"
    assert "operating income" in result["unanswered_parts"]
    assert len(result["claims"]) == (4 if problem is None else 3)
    assert ("Operating income remains unverified" in thesis.direct_answer) == (problem is None)
    if problem is None:
        assert result["claims"][-1]["claim_kind"] == "supplementary_profitability_comparison"


def test_explicit_pretax_query_keeps_distinct_metric_identity(monkeypatch):
    monkeypatch.setattr("app.services.providers.sec_provider._load_ticker_cik_map", lambda: {"AAPL": "320193"})
    thesis = InvestmentThesis(ticker="AAPL", company_name="Apple")
    result = apply_source_answer_gate(thesis, "How has pretax income changed? Cite sources.", [evidence(PRETAX, "pretax income")])
    assert result["status"] == "attributed"
    assert "pretax income" in result["claims"][0]["claim"]
    assert "operating income" not in result["unanswered_parts"]
