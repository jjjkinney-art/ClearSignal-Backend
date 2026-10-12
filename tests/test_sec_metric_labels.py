"""Frozen concept semantics and signed cash-flow rendering; no live inputs."""
from dataclasses import replace

import pytest

from app.integrity.sec_metric_evidence import comparable_metric_evidence
from app.integrity.sec_metric_labels import metric_label
from tests.test_verified_sec_metrics import _record


def evidence(concept, current, prior):
    rows = [
        _record(concept=concept, value=prior),
        _record(concept=concept, value=current, start="2025-01-01", end="2025-03-31",
                filed="2025-05-01", accession="0000320193-25-000001"),
    ]
    # An arbitrary issuer/source label must not redefine the standard concept.
    rows = [replace(row, label="Issuer source label") for row in rows]
    return comparable_metric_evidence(rows, ticker="AAPL", expected_cik="320193",
                                      concepts=(concept,), metric_name={
                                          "NetIncomeLoss": "net income", "ProfitLoss": "net income",
                                          "NetCashProvidedByUsedInOperatingActivities": "operating cash flow",
                                      }.get(concept, "revenue"))


@pytest.mark.parametrize("concept,current,prior,label,percentage,attribution", [
    ("NetIncomeLoss", 10928000, 30127000, "net income attributable to parent", "63.7%", "attributable_to_parent"),
    ("ProfitLoss", 12260000, 37936000, "net income including noncontrolling interests", "67.7%", "including_noncontrolling_interests"),
    ("NetIncomeLoss", 14525000000, 7082000000, "net income attributable to parent", "105.1%", "attributable_to_parent"),
])
def test_income_attribution_and_amounts(concept, current, prior, label, percentage, attribution):
    item = evidence(concept, current, prior)
    assert label in item.summary and percentage in item.summary
    assert [claim["raw_value"] for claim in item.verified_claims] == [current, prior]
    assert all(claim["income_attribution"] == attribution for claim in item.verified_claims)
    assert all(claim["scope"] == "consolidated" for claim in item.verified_claims)
    assert all(claim["label"] == "Issuer source label" for claim in item.verified_claims)


def test_broad_revenue_does_not_assert_xom_specific_composition():
    item = evidence("Revenues", 116017000000, 81506000000)
    assert "revenue (as reported) increased 42.3%" in item.summary
    assert "other income" not in item.summary and "operating revenue" not in item.summary
    assert metric_label("revenue", "RevenueFromContractWithCustomerExcludingAssessedTax") == "revenue from contracts with customers excluding assessed taxes"
    assert metric_label("revenue", "RevenuesNetOfInterestExpense") == "revenue net of interest expense"


@pytest.mark.parametrize("current,prior,phrase,percentage", [
    (-237044000000, -222292000000, "cash used in operating activities increased", "6.6%"),
    (-50, -100, "cash used in operating activities decreased", "50.0%"),
    (-100, -100, "cash used in operating activities was unchanged", None),
    (50, -100, "moved from cash used to cash provided", None),
    (-50, 100, "moved from cash provided to cash used", None),
    (50, 0, "moved from zero net cash flow to cash provided", None),
    (-50, 0, "moved from zero net cash flow to cash used", None),
    (0, -100, "moved from cash used to zero net cash flow", None),
    (0, 100, "moved from cash provided to zero net cash flow", None),
    (0, 0, "moved from zero net cash flow to zero net cash flow", None),
])
def test_cash_flow_signs(current, prior, phrase, percentage):
    item = evidence("NetCashProvidedByUsedInOperatingActivities", current, prior)
    if prior == 0:
        assert item is None  # Preserve the existing zero-baseline admission gate.
        return
    assert item and phrase in item.summary
    assert [claim["raw_value"] for claim in item.verified_claims] == [current, prior]
    if percentage:
        assert percentage in item.summary
    else:
        assert "%" not in item.summary
    assert not any(word in item.summary for word in ["improved", "stronger", "weaker"])


def test_zero_non_cash_baseline_remains_withheld():
    assert evidence("NetIncomeLoss", 10, 0) is None


def test_attribution_survives_reconstruction_and_tampering_is_withheld():
    from app.services.financial_thesis_foundation import build_financial_foundation
    revenue = evidence("Revenues", 120, 100)
    income = evidence("NetIncomeLoss", 10928000, 30127000)
    result = build_financial_foundation("AAPL", [revenue, income], None, expected_cik="320193")
    assert result and "net income attributable to parent" in result["answer"]
    assert "63.7%" in result["answer"]
    tampered = income.model_copy(deep=True)
    tampered.verified_claims[0]["income_attribution"] = "including_noncontrolling_interests"
    assert build_financial_foundation("AAPL", [revenue, tampered], None, expected_cik="320193") is None


def test_attribution_concepts_cannot_be_joined_into_one_comparison():
    prior = _record(concept="ProfitLoss", value=37936000)
    current = _record(concept="NetIncomeLoss", value=10928000, start="2025-01-01",
                      end="2025-03-31", filed="2025-05-01", accession="0000320193-25-000001")
    assert comparable_metric_evidence([prior, current], ticker="AAPL", expected_cik="320193",
        concepts=("NetIncomeLoss", "ProfitLoss"), metric_name="net income") is None


def test_income_definition_survives_source_answer_and_preserves_input(monkeypatch):
    from copy import deepcopy
    from app.schemas import InvestmentThesis
    from app.services.source_answer import apply_source_answer_gate
    monkeypatch.setattr('app.services.providers.sec_provider._load_ticker_cik_map', lambda: {'AAPL': '320193'})
    income = evidence('ProfitLoss', 12260000, 37936000)
    before = deepcopy(income.model_dump())
    thesis = InvestmentThesis(ticker='AAPL', company_name='Apple')
    result = apply_source_answer_gate(thesis, 'Which source supports net income?', [income])
    assert result['status'] == 'attributed'
    assert 'net income including noncontrolling interests' in thesis.direct_answer
    assert income.model_dump() == before
    assert all(c['income_attribution'] == 'including_noncontrolling_interests' for c in thesis.quantitative_claims)
