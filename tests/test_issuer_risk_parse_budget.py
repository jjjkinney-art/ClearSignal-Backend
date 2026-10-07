"""Risk-only parsing preserves attribution while omitting unused table grids."""
from dataclasses import replace
import hashlib
import socket

import pytest
import requests

from app.services import live_issuer_kpi_service as live
from app.services import public_document_ingestion as ingestion
from app.services.evidence_references import admit_evidence
from app.services.issuer_risk_evidence import extract_issuer_risk_evidence
from app.services.source_answer import apply_source_answer_gate
from app.schemas import InvestmentThesis, RetrievedEvidence
from tests.test_public_document_ingestion import _Response

URL = "https://www.sec.gov/Archives/edgar/data/19617/000162828026008131/jpm.htm"
QUESTION = "What operating risks affect JPM credit losses?"
QUOTE = "Credit losses could increase and adversely affect our operating results."


@pytest.fixture(autouse=True)
def public_dns(monkeypatch):
    from app.services import issuer_identity
    directory = issuer_identity.parse_directory({"0": {
        "ticker": "JPM", "title": "JPMorgan Chase & Co.", "cik_str": 19617}})
    monkeypatch.setattr(issuer_identity, "_load_directory", lambda: directory)
    monkeypatch.setattr(issuer_identity, "_cache", directory)
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))])


def fetch(monkeypatch, body, **kwargs):
    monkeypatch.setattr(requests, "get", lambda *a, **k: _Response(body))
    return ingestion.fetch_public_document(URL, publisher="SEC EDGAR",
        published_at="2026-02-13", document_type="10-K",
        source_type="regulatory_filing", source_tier="primary",
        sec_periodic_limits=True, **kwargs)


@pytest.mark.parametrize("late_section", [False, True])
def test_text_only_matches_full_parser_through_admission_and_answer(monkeypatch, late_section):
    # Authored markup, including a risk inside a visible table and hidden decoys.
    preface = "Visible preface. " * (24000 if late_section else 1)
    body = ("<html><head><title>Authored annual</title></head><body>" + preface +
        '<ix:header><ix:hidden>Credit losses will destroy the company.</ix:hidden></ix:header>'
        '<div style="display:none">Item 1A. Risk Factors hidden-canary</div>'
        '<h2>Item 1A. Risk Factors</h2><table><tr><td>' + QUOTE + '</td></tr></table>'
        '<h2>Item 1B. Unresolved Staff Comments</h2><a href="/Archives/edgar/data/19617/notes.htm">Notes</a>'
        '</body></html>').encode()
    original = fetch(monkeypatch, body)
    # This fails if the supposedly text-only path still creates a grid parser.
    monkeypatch.setattr(ingestion, "_HTMLTableExtractor", lambda: pytest.fail("unused table pass"))
    optimized = fetch(monkeypatch, body, extract_tables=False)
    assert original.tables and optimized.tables == ()
    assert replace(original, tables=(), accessed_at=optimized.accessed_at) == optimized
    assert optimized.content_hash == hashlib.sha256(body).hexdigest()
    assert "hidden-canary" not in optimized.text
    assert optimized.text_window_start > 0 if late_section else optimized.text_window_start == 0
    outputs = []
    for document in (original, optimized):
        items = extract_issuer_risk_evidence(document, ticker="JPM", question=QUESTION)
        assert len(items) == 1 and items[0].risk_disclosures[0]["quote"] == QUOTE
        admitted, references, _ = admit_evidence(items, evaluated_at="2026-10-07")
        thesis = InvestmentThesis(ticker="JPM", company_name="JPMorgan Chase & Co.")
        result = apply_source_answer_gate(thesis, QUESTION, admitted, references=references)
        assert result["claims"] and "[E1]" in thesis.direct_answer
        outputs.append((result, thesis.direct_answer))
    assert outputs[0] == outputs[1]


@pytest.mark.parametrize("ticker,question,text_only", [
    ("JPM", QUESTION, True),
    ("NFLX", "What operating risks affect subscription renewals?", True),
    ("AAPL", "What public evidence supports Services revenue growth?", False),
    ("AAPL", "What operating risks affect Services revenue growth?", False),
    ("NFLX", "What were paid memberships?", False),
])
def test_only_periodic_risk_path_omits_tables(monkeypatch, ticker, question, text_only):
    filing = RetrievedEvidence(title="Authored report", source="SEC EDGAR", summary="Filed.",
        timestamp="2026-02-13", url=URL,
        document_type="8-K" if question == "What were paid memberships?" else "10-K")
    monkeypatch.setattr(live.sec_provider, "fetch_recent_filings", lambda *a, **k: [filing])
    calls = []
    def unavailable(url, **kwargs):
        calls.append(kwargs)
        raise ingestion.PublicDocumentError("unavailable")
    monkeypatch.setattr(live, "fetch_public_document", unavailable)
    assert live.fetch_live_issuer_kpi_evidence(ticker, question=question) == []
    assert calls
    assert all(c.get("extract_tables", True) is not text_only for c in calls)
    if text_only:
        assert all(c["sec_periodic_limits"] is True for c in calls)


def test_ordinary_documents_still_extract_tables_by_default(monkeypatch):
    body = b'<h1>Results</h1><table><tr><td>Revenue</td><td>12</td></tr></table>'
    monkeypatch.setattr(requests, "get", lambda *a, **k: _Response(body))
    document = ingestion.fetch_public_document("https://example.com/report.htm")
    assert document.tables[0].rows == (("Revenue", "12"),)


@pytest.mark.parametrize("periodic,limit", [(False, ingestion.MAX_DOCUMENT_BYTES),
    (True, ingestion.MAX_SEC_PERIODIC_BYTES)])
def test_text_only_does_not_relax_download_limits(monkeypatch, periodic, limit):
    response = _Response(b"", headers={"Content-Length": str(limit + 1)})
    monkeypatch.setattr(requests, "get", lambda *a, **k: response)
    with pytest.raises(ingestion.PublicDocumentError) as error:
        ingestion.fetch_public_document(URL, publisher="SEC EDGAR",
            document_type="10-K", source_type="regulatory_filing", source_tier="primary",
            sec_periodic_limits=periodic, extract_tables=False)
    assert error.value.size_limit_bytes == limit
    assert error.value.declared_bytes == limit + 1
    assert response.closed
