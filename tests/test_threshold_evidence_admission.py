"""Unsupported investment boundaries cannot escape in any thesis field."""
import pytest
from app.schemas import InvestmentThesis
from app.services.source_answer import apply_source_answer_gate


@pytest.mark.parametrize("ticker,boundary", [("ASML", 15), ("ACHC", 85), ("NPK", 10)])
def test_unbound_thresholds_and_prose_are_withheld(ticker, boundary):
    thesis = InvestmentThesis(ticker=ticker, company_name=ticker)
    thesis.direct_answer = f"Buy above {boundary}; EPS will rise 20%."
    thesis.bull_thesis = "Fair value is 30x earnings."
    thesis.bear_thesis = "EPS falls 15%."
    thesis.decision_thresholds = [{"metric": "growth", "bull_boundary": boundary,
                                  "provenance": "derived", "reference_ids": ["E1"]}]
    thesis.confidence_score = .8
    result = apply_source_answer_gate(thesis, "Explain decision thresholds", [],
                                    references=[{"id": "E1", "claim_type": "filing_metadata"}])
    assert result["status"] == "insufficient_claim_evidence"
    assert not thesis.decision_thresholds and not thesis.threshold_zones
    assert not thesis.bull_thesis and not thesis.bear_thesis
    assert not thesis.quantitative_claims
    assert thesis.confidence_score == 0
    assert "30x" not in str(thesis.model_dump())
    assert "20%" not in str(thesis.model_dump())
    assert "dated, company-specific inputs" in thesis.direct_answer
    # Reapplication before serialization is stable.
    before = thesis.model_dump()
    apply_source_answer_gate(thesis, "Explain decision thresholds", [], references=[])
    assert thesis.model_dump() == before


def test_generated_boundaries_are_gated_without_explicit_threshold_question():
    thesis = InvestmentThesis(ticker="INV", company_name="Invented")
    thesis.decision_thresholds = [{"bull_boundary": 20, "bear_boundary": 30}]
    assert apply_source_answer_gate(thesis, "Is it attractive?", []) is not None
    assert not thesis.decision_thresholds


def test_non_threshold_generated_answer_is_unchanged():
    thesis = InvestmentThesis(ticker="INV", company_name="Invented", direct_answer="Original")
    assert apply_source_answer_gate(thesis, "Describe the company", []) is None
    assert thesis.direct_answer == "Original"
