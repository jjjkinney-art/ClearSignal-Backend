import pytest

from app.schemas import InvestmentThesis
from app.services.source_answer import apply_source_answer_gate
from tests.test_financial_thesis_foundation import evidence, PRETAX

QUESTION = "How have revenue, profitability and operating cash flow changed? Cite exact figures and identify missing data."


@pytest.fixture(autouse=True)
def identity(monkeypatch):
    monkeypatch.setattr("app.services.providers.sec_provider._load_ticker_cik_map", lambda: {"AAPL": "320193"})
    monkeypatch.setattr("app.services.profitability_coverage._load_ticker_cik_map", lambda: {"AAPL": "320193"})


def items(profit_concept="NetIncomeLoss", profit_name="net income"):
    return [evidence("Revenues", "revenue"), evidence(profit_concept, profit_name),
            evidence("NetCashProvidedByUsedInOperatingActivities", "operating cash flow")]


def answer(material, question=QUESTION, references=None):
    thesis = InvestmentThesis(ticker="AAPL", company_name="Apple")
    result = apply_source_answer_gate(thesis, question, material, references=references)
    return thesis, result


@pytest.mark.parametrize("concept,name,missing", [
    ("NetIncomeLoss", "net income", "operating income"),
    ("ProfitLoss", "net income", "operating income"),
    ("OperatingIncomeLoss", "operating income", "net income"),
])
def test_general_profitability_uses_one_rebuilt_core_measure_without_hiding_missing_data(concept, name, missing):
    thesis, result = answer(items(concept, name))
    assert result["status"] == "attributed"
    assert result["unanswered_parts"] == []
    coverage = {row["metric"]: row for row in result["profitability_coverage"]}
    assert coverage[name] == {"metric": name, "status": "verified_comparison", "reference_ids": ["E2"]}
    assert coverage[missing]["status"] == "not_verified"
    assert missing in thesis.direct_answer.lower()
    assert "not profit margins" in thesis.direct_answer


@pytest.mark.parametrize("explicit", ["operating income", "operating profit", "operating margin", "net income", "net profit", "earnings"])
def test_explicit_profit_measure_stays_required(explicit):
    net_requested = explicit in {"net income", "net profit", "earnings"}
    material = items("OperatingIncomeLoss", "operating income") if net_requested else items()
    _, result = answer(material, QUESTION + " Also cite " + explicit + ".")
    assert result["status"] == "partial"
    assert ("net income" if net_requested else "operating income") in result["unanswered_parts"]


def test_pretax_alone_does_not_satisfy_core_profitability():
    material = items()
    material[1] = evidence(PRETAX, "pretax income")
    _, result = answer(material)
    assert result["status"] == "partial"
    assert "operating income" in result["unanswered_parts"]
    assert "net income" in result["unanswered_parts"]


@pytest.mark.parametrize("problem", ["tampered", "wrong_issuer", "conflicting", "unknown_identity", "missing_reference"])
def test_unqualified_profit_comparison_cannot_relax_requirements(problem, monkeypatch):
    material = items()
    references = None
    if problem == "tampered":
        material[1].summary = "Invented net income result."
    elif problem == "wrong_issuer":
        material[1] = evidence("NetIncomeLoss", "net income", ticker="TSLA", cik="1318605")
    elif problem == "conflicting":
        material.append(evidence("NetIncomeLoss", "net income", current=180))
    elif problem == "unknown_identity":
        monkeypatch.setattr("app.services.profitability_coverage._load_ticker_cik_map", lambda: {})
    else:
        references = [{"id": f"E{i}", "title": item.title, "source": item.source,
                       "url": item.url, "published_at": item.timestamp}
                      for i, item in enumerate(material, 1) if i != 2]
    _, result = answer(material, references=references)
    assert result["status"] == "partial"
    assert "operating income" in result["unanswered_parts"]
    assert "net income" in result["unanswered_parts"]


def test_supplementary_pretax_stays_distinct_with_generic_profitability():
    material = items() + [evidence(PRETAX, "pretax income")]
    thesis, result = answer(material)
    assert result["status"] == "attributed"
    assert result["claims"][-1]["claim_kind"] == "supplementary_profitability_comparison"
    assert "does not establish operating income" in thesis.direct_answer
    assert "does not establish that the issuer did not report it" in thesis.direct_answer


def test_broad_thesis_stays_partial_with_operating_gap():
    _, result = answer(items(), "What is the investment thesis for Apple? Cite material claims.")
    assert result["status"] == "partial"
    assert "operating income" in result["unanswered_parts"]
    assert "valuation and expected returns" in result["unanswered_parts"]
