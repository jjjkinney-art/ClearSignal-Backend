"""Bounded 20-F Item 3 extraction; fixtures are authored, not live certification."""
from dataclasses import replace
from hashlib import sha256
import pytest
from app.services.sec_risk_sections import complete_risk_window, risk_section_spans
from app.services.public_document_ingestion import _HTMLTextExtractor
from app.services.issuer_risk_evidence import bound_issuer_risk
from app.services.evidence_references import admit_evidence
from app.services.source_answer import apply_source_answer_gate
from app.schemas import InvestmentThesis
from tests.test_company_evidence_expansion import CASES, document, extract, official_directory

END = "Item 4. Information on the Company"
QUOTE = "Export controls could adversely affect our operating results."

@pytest.mark.parametrize("opening", ["Item 3.D. Risk Factors", "Item 3. Key Information A. Reserved B. Capitalization Not applicable. C. Reasons Not applicable. D. Risk Factors", "ITEM 3 KEY INFORMATION Capitalization Not applicable. Risk Factors", "Ite m 3. Key Information D. Ri sk Factors"])
@pytest.mark.parametrize("form", ["20-F", "20-F/A"])
def test_supported_explicit_boundaries_bind_exact_sources(opening, form):
    case = next(c for c in CASES if c["ticker"] == "TSM")
    text = f"{opening} {QUOTE} {END} Business overview."
    doc = document(case, form=form, text=text)
    items = extract(case, doc)
    assert len(items) == 1
    value = items[0].risk_disclosures[0]
    assert text[value["start_offset"]:value["end_offset"]] == QUOTE
    assert value["document_ref"]["section"] == "Item 3.D. Risk Factors"
    admitted, refs, _ = admit_evidence(items, evaluated_at="2026-10-08")
    assert len(admitted) == 1
    thesis = InvestmentThesis(ticker="TSM", company_name=case["company"])
    result = apply_source_answer_gate(thesis, case["question"], admitted, references=refs)
    assert result["status"] == "attributed" and "[E1]" in thesis.direct_answer
    assert bound_issuer_risk(admitted[0], ticker="TSM", question=case["question"])
    forged = admitted[0].model_copy(update={"section": "Item 1A. Risk Factors"})
    assert bound_issuer_risk(forged, ticker="TSM", question=case["question"]) is None

@pytest.mark.parametrize("text", [
    f"Risk Factors {QUOTE} {END}",
    f"Item 1A. Risk Factors {QUOTE} Item 1B. Unresolved Staff Comments",
    f"Item 3.D. Risk Factors 12 {QUOTE} {END}",
    f'Please see “Item 3.D. Risk Factors” {QUOTE} {END}',
    f"Item 3. Key Information 3 D. Risk Factors {QUOTE} {END}",
    f"Item 3. Key Information D. Risk Factors {QUOTE}",
    f"Item 3. Key Information D. Risk Factors {QUOTE} See Item 4. Information on the Company 22",
    f"Item 3. Key Information " + "Preamble. " * 250 + f"Risk Factors {QUOTE} {END}",
])
def test_missing_ambiguous_or_cross_referenced_boundaries_withhold(text):
    case = next(c for c in CASES if c["ticker"] == "TSM")
    assert extract(case, document(case, form="20-F", text=text)) == []

@pytest.mark.parametrize("form", ["6-K", "40-F", "8-K", "10-K"])
def test_other_forms_cannot_borrow_foreign_boundaries(form):
    case = next(c for c in CASES if c["ticker"] == "TSM")
    assert extract(case, document(case, form=form, text=f"Item 3.D. Risk Factors {QUOTE} {END}")) == []

def test_late_20f_window_preserves_offsets_and_excludes_hidden_content():
    body = "<p>Visible preface. </p>" * 30000 + f"<h2>Item 3. Key Information</h2><h3>D. Risk Factors</h3><p>{QUOTE}</p><h2>{END}</h2><div hidden>Export controls could destroy us.</div>"
    p = _HTMLTextExtractor(); p.feed(body)
    full = p.normalized_visible_text(preserve_sec_risk=True)
    _, text, _, _ = p.result(max_chars=360000, preserve_sec_risk=True, risk_form="20-F")
    assert p.text_selection == "complete_sec_risk_section" and p.text_window_start > 0
    assert full[p.text_window_start:p.text_window_start + len(text)] == text
    assert QUOTE in text and "destroy" not in text
    assert complete_risk_window(full, form="20-F")
    assert complete_risk_window(full, form="10-K") is None

def test_explicit_size_ceiling_and_outside_section_decoys():
    text = f"Item 3.D. Risk Factors {'Context. ' * 40000}{QUOTE} {END}"
    assert list(risk_section_spans(text, max_section_chars=320000, form="20-F")) == []
    case = next(c for c in CASES if c["ticker"] == "TSM")
    assert extract(case, document(case, form="20-F", text=f"Item 3.D. Risk Factors Safe narrative. {END} {QUOTE}")) == []

def test_bare_risk_words_in_item3_prose_are_not_a_heading():
    case = next(c for c in CASES if c["ticker"] == "TSM")
    text = f"Item 3. Key Information Our Risk Factors include various matters. {QUOTE} {END}"
    assert extract(case, document(case, form="20-F", text=text)) == []

@pytest.mark.parametrize("form", ["20-F", "20-F/A"])
def test_form_specific_discovery_and_full_annual_fallback(monkeypatch, form):
    from app.services import live_issuer_kpi_service as live
    case = next(c for c in CASES if c["ticker"] == "TSM")
    doc = document(case, form="20-F", text=f"Item 3.D. Risk Factors {QUOTE} {END}")
    from app.schemas import RetrievedEvidence
    annual = RetrievedEvidence(title="TSM annual", source="SEC EDGAR", summary="Filed", timestamp="2026-03-02", url=doc.final_url, document_type="20-F")
    amendment = annual.model_copy(update={"document_type": form, "url": doc.final_url.replace("test.htm", "amendment.htm")})
    calls = []
    def discover(*args, **kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            assert "20-F" in kwargs["forms"] and "20-F/A" in kwargs["forms"]
            return [annual] if form == "20-F" else [amendment]
        assert kwargs["forms"] == ["20-F"]
        return [annual]
    def fetch(url, **kwargs):
        assert kwargs["sec_periodic_limits"] and kwargs["extract_tables"] is False
        if url == amendment.url and form == "20-F/A":
            return replace(doc, final_url=url, document_type=form, text="Signatures only")
        return doc
    monkeypatch.setattr(live.sec_provider, "fetch_recent_filings", discover)
    monkeypatch.setattr(live, "fetch_public_document", fetch)
    result = live.fetch_live_issuer_kpi_evidence("TSM", question=case["question"], user_agent="fixture")
    assert len(result) == 1
    assert len(calls) == (1 if form == "20-F" else 2)

@pytest.mark.parametrize("form", ["20-F", "20-F/A"])
def test_expanded_ingestion_and_long_reference_quotes_use_foreign_section(monkeypatch, form):
    import requests, socket
    from app.services.public_document_ingestion import fetch_public_document
    from tests.test_public_document_ingestion import _Response
    case = next(c for c in CASES if c["ticker"] == "TSM")
    long_quote = "Export controls " + "and related regulatory obligations " * 10 + "could adversely affect our operating results."
    body = f"<h2>Item 3.D. Risk Factors</h2><p>{long_quote}</p><h2>{END}</h2>".encode()
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34",443))])
    monkeypatch.setattr(requests, "get", lambda *a, **k: _Response(body))
    doc = fetch_public_document(document(case).final_url, publisher="SEC EDGAR", published_at="2026-03-02", document_type=form, source_type="regulatory_filing",source_tier="primary",sec_periodic_limits=True,extract_tables=False)
    result = extract(case, doc)
    assert len(result) == 1 and len(long_quote) > 300
    assert result[0].risk_disclosures[0]["document_ref"]["quote"] == long_quote
