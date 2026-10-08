"""Publisher retrieval, table identity and historical comparison boundaries."""
from dataclasses import replace
from datetime import date, datetime, timezone
from types import SimpleNamespace
import socket

import pytest
import requests

from app.services import issuer_release_evidence as service
from app.services.evidence_references import admit_evidence
from app.services.public_document_ingestion import DocumentLink, PublicDocumentError, fetch_public_document
from app.services.thesis_impact_comparison import evaluate_selected_thesis_impact

URL = "https://ir.tesla.com/press-release/tesla-third-quarter-2026-production-deliveries-and-deployments"
TITLE = "Tesla Third Quarter 2026 Production, Deliveries & Deployments"


def html():
    # A small reconstructed layout using the independently inspected official
    # October 2 release's headers and values; not a captured whole document.
    return f'''<html><head><title>{TITLE} | Tesla Investor Relations</title></head>
    <body><h2>{TITLE}</h2><p>Business Wire</p><p>Oct 2, 2026</p>
    <p>AUSTIN, Texas, October 2, 2026 – In the third quarter, we produced over
    464,000 vehicles, delivered over 486,000 vehicles and deployed 13.7 GWh.</p>
    <p>Q3 2026</p><table><tr><td></td><td>Production</td><td>Deliveries</td>
    <td>Subject to operating lease accounting</td></tr>
    <tr><td>Model 3/Y</td><td>457,387</td><td>478,237</td><td>1%</td></tr>
    <tr><td>Other Models</td><td>7,004</td><td>8,295</td><td>4%</td></tr>
    <tr><td>Total</td><td>464,391</td><td>486,532</td><td>1%</td></tr></table></body></html>'''


class Response:
    status_code = 200
    headers = {"Content-Type": "text/html"}
    encoding = "utf-8"
    def __init__(self, text): self.body = text.encode()
    def iter_content(self, chunk_size): yield self.body
    def raise_for_status(self): pass
    def close(self): pass


@pytest.fixture
def document(monkeypatch):
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 10, 8, tzinfo=timezone.utc)
    monkeypatch.setattr(service, "datetime", Clock)
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))])
    monkeypatch.setattr(requests, "get", lambda *a, **k: Response(html()))
    return fetch_public_document(URL, publisher="Tesla Investor Relations",
                                 document_type="press_release", source_type="issuer_release",
                                 source_tier="primary")


def test_parser_binds_exact_total_not_rounded_prose_or_model_row(document):
    evidence = service.extract_delivery_release(document, question="vehicle deliveries and vehicle production",
                                                evaluated_on=date(2026, 10, 8))
    assert [e.verified_claims[0]["raw_value"] for e in evidence] == [486532, 464391]
    for item in evidence:
        claim = item.verified_claims[0]
        assert claim["ticker"] == "TSLA"
        assert claim["unit"] == "vehicles"
        assert claim["period_end"] == "2026-09-30"
        assert claim["document_ref"]["content_hash"] == document.content_hash
        assert claim["document_ref"]["quote"] == "Total 464,391 486,532 1%"
        assert item.timestamp == "2026-10-02"
        assert item.url == URL
        assert item.reporting_period_start == "2026-07-01"


@pytest.mark.parametrize("mutation", [
    lambda d: replace(d, final_url="https://news.example.com/tesla"),
    lambda d: replace(d, requested_url="https://ir.tesla.com.evil.test/press-release/tesla-q3"),
    lambda d: replace(d, text_ready=False),
    lambda d: replace(d, source_tier="unverified"),
    lambda d: replace(d, content_hash="bad"),
    lambda d: replace(d, sections=()),
    lambda d: replace(d, text=d.text.replace("October 2, 2026", "January 2, 2026")),
    lambda d: replace(d, text=d.text.replace("October 2, 2026", "October 2, 2027")),
    lambda d: replace(d, text=d.text.replace("AUSTIN, Texas,", "Elsewhere,")),
    lambda d: replace(d, text=d.text.replace("Total 464,391", "Total 999,999")),
    lambda d: replace(d, tables=d.tables + d.tables),
    lambda d: replace(d, tables=(replace(d.tables[0], context="Q2 2026"),)),
    lambda d: replace(d, tables=(replace(d.tables[0], rows=d.tables[0].rows[:-1]),)),
    lambda d: replace(d, tables=(replace(d.tables[0], rows=(d.tables[0].rows[0],
        d.tables[0].rows[1], d.tables[0].rows[2], ("Total", "464,391", "486,533", "1%"))),)),
])
def test_unbound_ambiguous_wrong_period_and_foreign_documents_rejected(document, mutation):
    assert service.extract_delivery_release(mutation(document), question="deliveries",
                                             evaluated_on=date(2026, 10, 8)) == []


def test_future_release_rejected_and_publication_not_retrieval_time(document):
    assert service.extract_delivery_release(document, question="deliveries",
                                             evaluated_on=date(2026, 10, 1)) == []
    evidence = service.extract_delivery_release(document, question="deliveries")
    assert evidence[0].timestamp != evidence[0].retrieved_at


def test_discovery_ignores_consensus_foreign_links_and_deduplicates(document, monkeypatch):
    index = replace(document, requested_url=service._INDEX, final_url=service._INDEX, links=(
        DocumentLink("https://ir.tesla.com/press-release/q3-consensus", "Q3 2026 Delivery Consensus"),
        DocumentLink("https://ir.tesla.com.evil.test/press-release/tesla-q3", TITLE),
        DocumentLink(URL, TITLE), DocumentLink(URL, TITLE),
    ))
    calls = []
    def fetch(url, **kwargs):
        calls.append(url)
        return index if url == service._INDEX else document
    monkeypatch.setattr(service, "fetch_public_document", fetch)
    result = service.fetch_issuer_release_evidence("TSLA", question="deliveries")
    assert len(result) == 1
    assert calls == [service._INDEX, URL]


def test_unsupported_issuer_or_question_does_not_fetch(monkeypatch):
    monkeypatch.setattr(service, "fetch_public_document", lambda *a, **k: pytest.fail("unexpected network"))
    assert service.fetch_issuer_release_evidence("AAPL", question="deliveries") == []
    assert service.fetch_issuer_release_evidence("TSLA", question="supercharger network") == []


def test_download_failure_remains_honest_gap(monkeypatch):
    def fail(*a, **k): raise PublicDocumentError("failed", failure_kind="timeout")
    monkeypatch.setattr(service, "fetch_public_document", fail)
    assert service.fetch_issuer_release_evidence("TSLA", question="deliveries") == []


def test_discovery_attempt_budget_and_redirected_index(document, monkeypatch):
    urls = [URL + suffix for suffix in ("-one", "-two", "-three")]
    index = replace(document, final_url=service._INDEX, links=tuple(
        DocumentLink(url, TITLE) for url in urls))
    calls = []
    def fetch(url, **kwargs):
        calls.append(url)
        if url == service._INDEX:
            return index
        raise PublicDocumentError("failed", failure_kind="timeout")
    monkeypatch.setattr(service, "fetch_public_document", fetch)
    assert service.fetch_issuer_release_evidence("TSLA", question="deliveries") == []
    assert calls == [service._INDEX, *urls[:2]]
    calls.clear()
    index = replace(index, final_url="https://other.example.com/press")
    assert service.fetch_issuer_release_evidence("TSLA", question="deliveries") == []
    assert calls == [service._INDEX]


def test_real_dates_allow_new_release_but_not_retrieved_old_release(document):
    evidence = service.extract_delivery_release(document, question="vehicle deliveries")
    admitted, refs, _ = admit_evidence(evidence, evaluated_at="2026-10-08T00:00:00Z")
    context = {"applied": True, "ticker": "TSLA", "created_at": "2026-09-26T00:00:00Z",
               "artifact": {"thesis": {"direct_answer": "Vehicle deliveries confirm execution."}}}
    thesis = SimpleNamespace(direct_answer="Vehicle deliveries provide stronger execution evidence. [E1]",
                             conclusion="", thesis_trend="strengthening", what_changed=[], change_drivers=[])
    audit = evaluate_selected_thesis_impact(thesis=thesis, context=context, evidence=admitted, references=refs)
    assert audit["evidence_gate"]["status"] == "ready"
    assert audit["status"] == "verified_change"
    context["created_at"] = "2026-10-03T00:00:00Z"
    audit = evaluate_selected_thesis_impact(thesis=thesis, context=context, evidence=admitted, references=refs)
    assert audit["evidence_gate"]["status"] == "insufficient_new_evidence"
    assert audit["status"] != "verified_change"
