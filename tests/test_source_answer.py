from types import SimpleNamespace

from app.schemas import RetrievedEvidence
from app.services.source_answer import apply_source_answer_gate, is_source_answer_request


def _evidence(title, source, summary):
    return RetrievedEvidence(
        title=title, source=source, summary=summary,
        timestamp="2026-09-27", relevance_score=0.9,
    )


def test_source_question_fails_closed_for_filing_metadata():
    thesis = SimpleNamespace(direct_answer="Unsupported 600M claim.")
    evidence = [_evidence(
        "Apple 10-Q", "SEC EDGAR",
        "Apple filed a Quarterly Report with the SEC. 10-Q filings contain quarterly financials.",
    ) for _ in range(5)]
    result = apply_source_answer_gate(
        thesis,
        "What are the three strongest pieces of evidence, and which source supports each one?",
        evidence,
    )
    assert result["status"] == "insufficient_claim_evidence"
    assert result["claims"] == []
    assert "600M" not in thesis.direct_answer
    assert "did not extract enough claim-level evidence" in thesis.direct_answer


def test_three_claims_are_bound_to_reference_ids():
    thesis = SimpleNamespace(direct_answer="")
    evidence = [
        _evidence("Revenue", "FMP", "Revenue grew 12% year over year in the latest reported period."),
        _evidence("Services", "FMP", "Services revenue reached a new high in the latest reported period."),
        _evidence("Demand", "Reuters", "Channel checks indicated stronger upgrade demand across major markets."),
    ]
    result = apply_source_answer_gate(
        thesis,
        "Give three pieces of evidence and which source supports each.",
        evidence,
    )
    assert result["status"] == "attributed"
    assert [row["reference_id"] for row in result["claims"]] == ["E1", "E2", "E3"]
    assert "[E1]" in thesis.direct_answer and "[E3]" in thesis.direct_answer


def test_non_source_question_is_unchanged():
    thesis = SimpleNamespace(direct_answer="Original answer")
    assert apply_source_answer_gate(thesis, "What is Apple's thesis?", []) is None
    assert thesis.direct_answer == "Original answer"


def test_structured_sec_fact_is_claim_level_evidence():
    thesis = SimpleNamespace(direct_answer="")
    evidence = [_evidence(
        "AAPL revenue", "SEC EDGAR — structured XBRL fact",
        "AAPL revenue increased 12.0% to $100B for the period ended 2025-03-31.",
    )]
    result = apply_source_answer_gate(
        thesis, "Which source supports Apple's revenue growth?", evidence,
    )
    assert result["status"] == "attributed"
    assert result["claims"][0]["reference_id"] == "E1"


def test_production_acceptance_question_requests_sources():
    assert is_source_answer_request(
        "What are the three strongest pieces of current evidence supporting "
        "Apple's long-term growth thesis, and which source supports each one?"
    )
