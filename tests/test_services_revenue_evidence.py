from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services.public_document_ingestion import (
    DocumentTable, PublicDocument, _HTMLTableExtractor,
)
from app.services.services_revenue_evidence import (
    extract_services_revenue_evidence, requests_services_revenue,
)
from app.services.source_answer import apply_source_answer_gate


URL = "https://www.sec.gov/Archives/edgar/data/320193/000032019325000073/aapl-20250628.htm"


def _table(*, change=True, rows=None, context="Net sales by category (dollars in millions):"):
    headers = ("June 28, 2025", "June 29, 2024", "Change",
               "June 28, 2025", "June 29, 2024", "Change") if change else (
        "June 28, 2025", "June 29, 2024", "June 28, 2025", "June 29, 2024",
    )
    return DocumentTable(1, context, rows or (
        ("Three Months Ended", "Nine Months Ended"), headers,
        ("Products", "$", "66,613", "61,564", "8", "%", "233,287", "224,908", "4", "%")
        if change else ("Products", "$", "66,613", "61,564", "233,287", "224,908"),
        ("Services", "27,423", "24,213", "13", "%", "80,408", "71,197", "13", "%")
        if change else ("Services", "27,423", "24,213", "80,408", "71,197"),
    ))


def _document(tables=None, **overrides):
    document = PublicDocument(
        requested_url=URL, final_url=URL, content_type="text/html",
        content_hash="a" * 64, byte_count=100, title="Apple Q3 2025",
        text="Apple quarterly filing", sections=(), pages=(), links=(),
        extraction_method="html", text_ready=True, accessed_at="2026-10-05",
        publisher="SEC EDGAR", published_at="2025-08-01", document_type="10-Q",
        source_type="regulatory_filing", source_tier="primary",
        tables=tuple(tables or [_table()]),
    )
    return replace(document, **overrides)


def test_real_apple_table_preserves_quarter_and_reported_change():
    raw = (Path(__file__).parent / "fixtures/apple_services_q3_2025.html").read_bytes()
    parser = _HTMLTableExtractor()
    parser.feed(raw.decode())
    evidence = extract_services_revenue_evidence(
        _document(parser.result(), content_hash=sha256(raw).hexdigest()), ticker="AAPL",
    )
    assert len(evidence) == 2
    amounts, growth = evidence
    assert [claim["raw_value"] for claim in amounts.verified_claims] == [27_423_000_000, 24_213_000_000]
    assert [claim["as_of"] for claim in amounts.verified_claims] == ["2025-06-28", "2024-06-29"]
    assert growth.verified_claims[0]["raw_value"] == 13
    assert growth.verified_claims[0]["provenance"] == "reported"
    assert all(claim["duration_months"] == 3 for item in evidence for claim in item.verified_claims)
    assert "$80,408" not in amounts.summary
    for item in evidence:
        assert item.claim_type == "reported_fact"
        assert item.reporting_period_end == "2025-06-28"
        for claim in item.verified_claims:
            reference = claim["document_ref"]
            assert reference["url"] == URL
            assert reference["content_hash"] == sha256(raw).hexdigest()
            assert reference["section"].startswith("HTML table ")
            assert "Services 27,423 24,213 13 %" in reference["quote"]


def test_amount_only_table_does_not_invent_reported_growth():
    evidence = extract_services_revenue_evidence(_document([_table(change=False)]), ticker="AAPL")
    assert len(evidence) == 1
    assert len(evidence[0].verified_claims) == 2
    assert evidence[0].calculated_claims == []


@pytest.mark.parametrize("overrides", [
    {"published_at": None}, {"published_at": "2025-06-01"},
    {"content_hash": "bad"}, {"source_tier": "unverified"},
    {"document_type": "8-K"}, {"text_ready": False},
    {"final_url": "https://www.sec.gov/Archives/edgar/data/123/456/other.htm"},
    {"final_url": "https://example.com/Archives/edgar/data/320193/456/other.htm"},
])
def test_missing_provenance_or_wrong_issuer_is_rejected(overrides):
    assert extract_services_revenue_evidence(_document(**overrides), ticker="AAPL") == []


@pytest.mark.parametrize("context", [
    "Net sales (in thousands):", "Net sales (in billions):", "Net sales:",
    "Net sales (in millions, except amounts shown in thousands):",
    "Cost of sales (dollars in millions):",
    "Forecast net sales (dollars in millions):",
])
def test_units_and_revenue_scope_must_be_unambiguous(context):
    assert extract_services_revenue_evidence(_document([_table(context=context)]), ticker="AAPL") == []


def test_cost_of_sales_services_row_cannot_become_revenue():
    table = _table(change=False)
    table = replace(table, rows=table.rows[:2] + (("Cost of sales:",),) + table.rows[2:])
    assert extract_services_revenue_evidence(_document([table]), ticker="AAPL") == []


@pytest.mark.parametrize("header", [
    ("June 28, 2025", "June 28, 2025", "Change", "June 28, 2025", "June 29, 2024", "Change"),
    ("June 28, 2025", "March 29, 2025", "Change", "June 28, 2025", "June 29, 2024", "Change"),
    ("2025", "2024", "Change", "2025", "2024", "Change"),
    ("Change", "June 28, 2025", "June 29, 2024", "June 28, 2025", "June 29, 2024", "Change"),
])
def test_ambiguous_period_headers_are_rejected(header):
    table = _table()
    table = replace(table, rows=(table.rows[0], header, *table.rows[2:]))
    assert extract_services_revenue_evidence(_document([table]), ticker="AAPL") == []


def test_repeated_rows_collapse_but_conflicting_amounts_fail_closed():
    first = _table()
    second = replace(first, table_number=2)
    assert len(extract_services_revenue_evidence(_document([first, second]), ticker="AAPL")) == 2
    conflicting = replace(second, rows=(*second.rows[:-1],
        ("Services", "29,000", "24,213", "13", "%", "80,408", "71,197", "13", "%")))
    assert extract_services_revenue_evidence(_document([first, conflicting]), ticker="AAPL") == []


def test_bad_growth_column_is_not_promoted():
    table = _table()
    table = replace(table, rows=(*table.rows[:-1],
        ("Services", "27,423", "24,213", "99", "%", "80,408", "71,197", "13", "%")))
    evidence = extract_services_revenue_evidence(_document([table]), ticker="AAPL")
    assert len(evidence) == 1
    assert "99%" not in evidence[0].summary


def test_company_wide_and_other_issuer_rows_are_not_promoted():
    table = _table()
    table = replace(table, rows=table.rows[:-1])
    assert extract_services_revenue_evidence(_document([table]), ticker="AAPL") == []
    assert extract_services_revenue_evidence(_document(), ticker="MSFT") == []


def test_services_evidence_source_answer_is_dated_and_scope_limited():
    evidence = extract_services_revenue_evidence(_document(), ticker="AAPL")
    thesis = SimpleNamespace(direct_answer="Services margin is 72%.")
    result = apply_source_answer_gate(thesis,
        "What is the strongest current public evidence for Apple's services-growth thesis?",
        iter(evidence))
    assert result["status"] == "attributed"
    assert "[E1]" in thesis.direct_answer and "[E2]" in thesis.direct_answer
    assert "72%" not in thesis.direct_answer
    assert "2025-06-28" in thesis.direct_answer
    assert "do not, by themselves, verify future Services growth" in thesis.direct_answer


def test_request_gate_does_not_substitute_revenue_for_margin_only_question():
    assert requests_services_revenue("What evidence supports Apple's services-growth thesis?")
    assert requests_services_revenue("What was Apple Services revenue?")
    assert not requests_services_revenue("What was Apple Services gross margin?")
    assert not requests_services_revenue("How did iPhone revenue perform?")


def test_bound_claims_survive_admission_and_future_filing_is_blocked():
    from app.services.evidence_references import admit_evidence
    from app.services.verified_sec_metric_service import structured_claims_from_evidence
    evidence = extract_services_revenue_evidence(_document(), ticker="AAPL")
    admitted, references, integrity = admit_evidence(evidence, as_of="2025-08-02")
    assert len(admitted) == 2
    claims = structured_claims_from_evidence(admitted)
    assert len(claims) == 3
    assert all(claim["scope"] == "Services" for claim in claims)
    assert all(claim["document_ref"]["quote"] for claim in claims)
    assert [reference["id"] for reference in references] == ["E1", "E2"]
    fresh_evidence = extract_services_revenue_evidence(_document(), ticker="AAPL")
    admitted, _, integrity = admit_evidence(fresh_evidence, as_of="2025-07-01")
    assert admitted == []
    assert integrity["admission"]["blocked_count"] == 2
