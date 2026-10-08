"""Reviewed integrated layouts remain document-specific and source-bound."""
from dataclasses import replace
from hashlib import sha256
import socket
import pytest
import requests
from app.services.reviewed_annual_layouts import REVIEWED_ANNUAL_LAYOUTS, reviewed_annual_layout
from app.services.public_document_ingestion import fetch_public_document, PublicDocumentError
from app.services.sec_risk_sections import risk_section_spans
from app.services.issuer_risk_evidence import bound_issuer_risk
from app.services.evidence_references import admit_evidence
from app.services.source_answer import apply_source_answer_gate
from app.schemas import InvestmentThesis
from tests.test_company_evidence_expansion import CASES, document, extract, official_directory
from tests.test_public_document_ingestion import _Response

LAYOUT = REVIEWED_ANNUAL_LAYOUTS[0]
OPEN = "Risk and security Risk factors The risk factors outlined in this section are categorized."
CLOSE = "Risk and security Information security We believe security matters."
QUOTE = "Export controls could adversely affect our operating results."
CASE = next(c for c in CASES if c["ticker"] == "ASML")


def integrated_document(text=None):
    return replace(document(CASE, form="20-F", text=text or f"{OPEN} {QUOTE} {CLOSE}"),
        requested_url=LAYOUT["url"], final_url=LAYOUT["url"], published_at=LAYOUT["filed_at"],
        content_hash=LAYOUT["content_hash"])


@pytest.mark.parametrize("field,value", [("url", LAYOUT["url"] + "?x=1"),
    ("form", "20-F/A"), ("filed_at", "2026-02-26"), ("content_hash", "a" * 64), ("cik", "353278")])
def test_registration_requires_exact_document_identity(field, value):
    args = dict(url=LAYOUT["url"], form=LAYOUT["form"], filed_at=LAYOUT["filed_at"],
        content_hash=LAYOUT["content_hash"], cik=LAYOUT["cik"])
    assert reviewed_annual_layout(**args)
    args[field] = value
    assert reviewed_annual_layout(**args) is None


def test_integrated_quote_binds_and_answers_with_its_actual_section():
    doc = integrated_document()
    items = extract(CASE, doc)
    assert len(items) == 1
    disclosure = items[0].risk_disclosures[0]
    assert doc.text[disclosure["start_offset"]:disclosure["end_offset"]] == QUOTE
    assert disclosure["document_ref"]["section"] == LAYOUT["section"]
    admitted, refs, _ = admit_evidence(items, evaluated_at="2026-10-08")
    thesis = InvestmentThesis(ticker="ASML", company_name=CASE["company"])
    assert apply_source_answer_gate(thesis, CASE["question"], admitted, references=refs)["status"] == "attributed"
    assert "[E1]" in thesis.direct_answer
    assert bound_issuer_risk(admitted[0], ticker="ASML", question=CASE["question"])
    for updates in ({"section": "Item 3.D. Risk Factors"}, {"url": LAYOUT["url"] + "?x"},
        {"risk_disclosures": [{**disclosure, "document_ref": []}]}):
        assert bound_issuer_risk(admitted[0].model_copy(update=updates), ticker="ASML", question=CASE["question"]) is None


@pytest.mark.parametrize("text", [f"Risk factors {QUOTE} {CLOSE}", f"{OPEN} {QUOTE}",
    f"{OPEN} Safe context. {CLOSE} {QUOTE}", f"{OPEN} {'Context. ' * 40000}{QUOTE} {CLOSE}"], ids=["bare", "unclosed", "outside", "oversized"])
def test_integrated_missing_boundaries_and_outside_quotes_withhold(text):
    assert extract(CASE, integrated_document(text)) == []


def test_wrong_hash_and_form_cannot_borrow_reviewed_layout():
    for updates in ({"content_hash": "b" * 64}, {"document_type": "20-F/A"},
        {"published_at": "2026-02-26"}):
        assert extract(CASE, replace(integrated_document(), **updates)) == []


def test_repeat_headers_do_not_close_section():
    text = f"{OPEN} Risk factors (continued) {QUOTE} {CLOSE}"
    spans = list(risk_section_spans(text, max_section_chars=320000, form="20-F", layout=LAYOUT))
    assert len(spans) == 1 and QUOTE in text[slice(*spans[0])]


@pytest.fixture
def public_dns(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k:
        [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))])


def fetch():
    return fetch_public_document(LAYOUT["url"], publisher="SEC EDGAR", published_at=LAYOUT["filed_at"],
        document_type="20-F", source_type="regulatory_filing", source_tier="primary",
        sec_periodic_limits=True, extract_tables=False)


def test_changed_registered_body_is_rejected_before_extraction(monkeypatch, public_dns):
    monkeypatch.setattr(requests, "get", lambda *a, **k: _Response(b"<p>Changed document</p>"))
    with pytest.raises(PublicDocumentError, match="hash mismatch"):
        fetch()


@pytest.mark.parametrize("declared", [False, True])
def test_registered_document_still_has_bounded_size(monkeypatch, public_dns, declared):
    response = _Response(b"x" * 30_000_001, headers={"Content-Length": "30000001"} if declared else {})
    monkeypatch.setattr(requests, "get", lambda *a, **k: response)
    with pytest.raises(PublicDocumentError, match="size limit"):
        fetch()
    assert response.closed


def test_unregistered_url_keeps_normal_periodic_byte_limit(monkeypatch, public_dns):
    monkeypatch.setattr(requests, "get", lambda *a, **k: _Response(b"x" * 15_000_001))
    with pytest.raises(PublicDocumentError, match="size limit"):
        fetch_public_document(LAYOUT["url"].replace("asml-20251231.htm", "other.htm"),
            publisher="SEC EDGAR", published_at=LAYOUT["filed_at"], document_type="20-F", source_type="regulatory_filing", source_tier="primary", sec_periodic_limits=True)


def test_explicit_legal_liabilities_are_adverse_but_bare_liabilities_are_not():
    quote = "Countries affected by export control restrictions may also introduce countermeasures, which could result in conflicting regulations and legal liabilities."
    assert len(extract(CASE, integrated_document(f"{OPEN} {quote} {CLOSE}"))) == 1
    for quote in ("Export controls could affect our liabilities.",
        "Export controls result in legal liabilities.", "Countermeasures could result in legal liabilities."):
        assert extract(CASE, integrated_document(f"{OPEN} {quote} {CLOSE}")) == []


def test_reviewed_ingestion_requires_visible_crosswalk(monkeypatch, public_dns):
    from app.services import reviewed_annual_layouts as registry
    body = f"<h2>{OPEN}</h2><p>{QUOTE}</p><h2>{CLOSE}</h2>".encode()
    fixture_layout = {**LAYOUT, "content_hash": sha256(body).hexdigest()}
    monkeypatch.setattr(registry, "REVIEWED_ANNUAL_LAYOUTS", (fixture_layout,))
    monkeypatch.setattr(requests, "get", lambda *a, **k: _Response(body))
    with pytest.raises(PublicDocumentError, match="mapping unavailable"):
        fetch()
    body += f"<p>{LAYOUT['mapping']}</p>".encode()
    fixture_layout["content_hash"] = sha256(body).hexdigest()
    assert fetch().text_ready
