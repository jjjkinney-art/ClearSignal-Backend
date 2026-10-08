"""Reviewed integrated layouts remain document-specific and source-bound."""
from dataclasses import replace
from hashlib import sha256
import socket
import pytest
import requests
from app.services.reviewed_annual_layouts import REVIEWED_ANNUAL_LAYOUTS, reviewed_annual_layout, reviewed_body_hash
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
    fixture_layout = {**LAYOUT, "content_hash": sha256(body).hexdigest(), "canonical_content_hash": reviewed_body_hash(body)}
    monkeypatch.setattr(registry, "REVIEWED_ANNUAL_LAYOUTS", (fixture_layout,))
    monkeypatch.setattr(requests, "get", lambda *a, **k: _Response(body))
    with pytest.raises(PublicDocumentError, match="mapping unavailable"):
        fetch()
    body += f"<p>{LAYOUT['mapping']}</p>".encode()
    fixture_layout["content_hash"] = sha256(body).hexdigest()
    fixture_layout["canonical_content_hash"] = reviewed_body_hash(body)
    assert fetch().text_ready


@pytest.mark.parametrize("tail", [
    b'<script type="text/javascript"  src="/First/transport/Path"></script>',
    b'<script type="text/javascript"  src="/Different/path_123-ABC"></script>',
    b'',
])
def test_only_reviewed_empty_transport_tail_is_ignored(tail):
    core = b'<html><body><p>Visible filing text.</p>'
    assert reviewed_body_hash(core + tail + b'</body></html>\n') == sha256(core + b'</body></html>\n').hexdigest()


@pytest.mark.parametrize("changed", [
    b'<html><body><p>Changed filing text.</p></body></html>\n',
    b'<html><body><p>Visible filing text.</p><script type="text/javascript"  src="/path">alert(1)</script></body></html>\n',
    b'<html><body><p>Visible filing text.</p><script type="text/javascript"  src="https://other.example/path"></script></body></html>\n',
    b'<html><body><script type="text/javascript"  src="/path"></script><p>Visible filing text.</p></body></html>\n',
    b'<html><body><p hidden>extra metadata</p><p>Visible filing text.</p></body></html>\n',
])
def test_visible_and_other_hidden_changes_still_change_fingerprint(changed):
    assert reviewed_body_hash(changed) != sha256(b'<html><body><p>Visible filing text.</p></body></html>\n').hexdigest()


def test_transport_variants_ingest_and_bind_their_actual_raw_hash(monkeypatch, public_dns):
    from app.services import reviewed_annual_layouts as registry
    core = f"<html><body><p>{LAYOUT['mapping']}</p><h2>{OPEN}</h2><p>{QUOTE}</p><h2>{CLOSE}</h2>".encode()
    base = core + b'</body></html>\n'
    fixture_layout = {**LAYOUT, "content_hash": sha256(base).hexdigest(), "canonical_content_hash": reviewed_body_hash(base)}
    monkeypatch.setattr(registry, "REVIEWED_ANNUAL_LAYOUTS", (fixture_layout,))
    for path in ("/transport/One", "/transport/Two_123"):
        body = core + f'<script type="text/javascript"  src="{path}"></script>'.encode() + b'</body></html>\n'
        monkeypatch.setattr(requests, "get", lambda *a, **k: _Response(body))
        doc = fetch()
        assert doc.content_hash == sha256(body).hexdigest()
        assert doc.canonical_content_hash == fixture_layout["canonical_content_hash"]
        item = extract(CASE, doc)[0]
        admitted, refs, _ = admit_evidence([item], evaluated_at="2026-10-08")
        thesis = InvestmentThesis(ticker="ASML", company_name=CASE["company"])
        assert apply_source_answer_gate(thesis, CASE["question"], admitted, references=refs)["status"] == "attributed"
        value = item.risk_disclosures[0]
        assert value["document_ref"]["content_hash"] == doc.content_hash
        assert doc.text[value["start_offset"]:value["end_offset"]] == QUOTE
        assert bound_issuer_risk(item, ticker="ASML", question=CASE["question"])
        for binding in (None, [], {}, {**value["reviewed_layout"], "raw_content_hash": "a" * 64},
            {**value["reviewed_layout"], "canonical_content_hash": "a" * 64},
            {**value["reviewed_layout"], "registry_id": "other"}):
            forged = item.model_copy(update={"risk_disclosures": [{**value, "reviewed_layout": binding}]})
            assert bound_issuer_risk(forged, ticker="ASML", question=CASE["question"]) is None
        restored = type(item).model_validate_json(item.model_dump_json())
        assert bound_issuer_risk(restored, ticker="ASML", question=CASE["question"])
    changed = core.replace(QUOTE.encode(), b"Export controls could cause a different adverse outcome.") + b'</body></html>\n'
    monkeypatch.setattr(requests, "get", lambda *a, **k: _Response(changed))
    with pytest.raises(PublicDocumentError, match="hash mismatch"):
        fetch()
