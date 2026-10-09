"""Synthetic issuer prose: tests do not claim these are actual SEC disclosures."""
from dataclasses import replace
from hashlib import sha256
from types import SimpleNamespace

import pytest

from app.services import thesis_disclosures as service
from app.services.public_document_ingestion import PublicDocument, _HTMLTextExtractor
from app.services.financial_thesis_foundation import build_financial_foundation
from app.services.evidence_references import admit_evidence
from app.schemas import InvestmentThesis
from app.services.source_answer import apply_source_answer_gate
from test_financial_thesis_foundation import pair

BUSINESS = "We manufacture specialized components and distribute our products through independent dealers."
RISK = "Supply chain disruptions could adversely affect our ability to manufacture and deliver products."
QUESTION = "What is the investment thesis for AAPL, what supports it, and what could invalidate it? Cite material claims."


def document(text=None, **changes):
    text = text or f"Item 1. Business Overview. {BUSINESS} Item 1A. Risk Factors {RISK} Item 1B. Unresolved Staff Comments"
    url = "https://www.sec.gov/Archives/edgar/data/320193/000032019325000001/annual.htm"
    return replace(PublicDocument(url, url, 'text/html', sha256(text.encode()).hexdigest(),
        len(text), 'Synthetic annual', text, (), (), (), 'html', True, '2025-08-01',
        publisher='SEC EDGAR', published_at='2025-08-01', document_type='10-K',
        source_type='regulatory_filing', source_tier='primary'), **changes)


def business_item():
    return service.extract_business_descriptions(document(), ticker="AAPL", cik="320193")[0]


def risk_item():
    return service.extract_issuer_risk_evidence(document(), ticker="AAPL",
        question="What operating risk affects Supply chain?")[0]


def test_exact_business_span_survives_producer_and_binder():
    item = business_item()
    value = service.bound_business_description(item, ticker="AAPL", cik="320193")
    assert value["quote"] == BUSINESS
    assert document().text[value["start_offset"]:value["end_offset"]] == BUSINESS
    assert item.verified_claims == []
    assert "competitive advantage" in item.summary


@pytest.mark.parametrize("changes", [dict(document_type="20-F"), dict(publisher="Other"),
    dict(published_at="2099-01-01"), dict(source_tier="secondary"), dict(text_ready=False)])
def test_ineligible_document_does_not_authorize_business_description(changes):
    assert service.extract_business_descriptions(document(**changes), ticker="AAPL", cik="320193") == []


@pytest.mark.parametrize("text", [
    f"Item 1. Business 2 {BUSINESS} Item 1A. Risk Factors 3",
    f"See Item 1. Business Overview. {BUSINESS} Item 1A. Risk Factors {RISK}",
    f"Item 1. Business Overview. {BUSINESS}",
    "Item 1. Business Overview. We will manufacture superior products and deliver the best results for all customers. Item 1A. Risk Factors",
    "Item 1. Business Overview. We manufacture specialized components and sell 400 products through dealers. Item 1A. Risk Factors",
])
def test_incomplete_toc_cross_reference_forecast_and_numeric_business_text_fail_closed(text):
    assert service.extract_business_descriptions(document(text), ticker="AAPL", cik="320193") == []


@pytest.mark.parametrize("mutation", [
    lambda item: setattr(item, "summary", "Invented moat"),
    lambda item: setattr(item, "source_tier", "secondary"),
    lambda item: setattr(item, "freshness_status", "stale"),
    lambda item: item.business_disclosures[0].update(ticker="TSLA"),
    lambda item: item.business_disclosures[0].update(start_offset=True),
    lambda item: item.business_disclosures[0]["document_ref"].update(content_hash="bad"),
    lambda item: item.business_disclosures[0]["document_ref"].update(quote="Invented quote."),
])
def test_mutated_business_proof_is_rejected(mutation):
    item = business_item()
    mutation(item)
    assert service.bound_business_description(item, ticker="AAPL", cik="320193") is None


def test_other_issuer_cannot_authorize_business_quote():
    assert service.bound_business_description(business_item(), ticker="AAPL", cik="1318605") is None


def test_composer_keeps_disclosures_separate_from_financial_inferences_and_materiality():
    items = pair() + [business_item(), risk_item()]
    result = build_financial_foundation("AAPL", items, None, expected_cik="320193")
    assert len(result["claims"]) == 4
    assert len(result["inferences"]) == 2
    assert BUSINESS in result["answer"] and RISK in result["answer"]
    assert "competitive position" in result["unanswered_parts"]
    assert "valuation and expected returns" in result["unanswered_parts"]
    assert "risk materiality, likelihood and effect on the investment case" in result["unanswered_parts"]
    assert "issuer-disclosed operating-risk mechanisms" not in result["unanswered_parts"]
    assert "not a complete business model or a ranking" in result["answer"]


def test_unadmitted_quotes_do_not_close_missing_parts():
    items = pair() + [business_item(), risk_item()]
    refs = [{"id": f"E{i}", "title": item.title, "source": item.source,
             "url": item.url, "published_at": item.timestamp} for i, item in enumerate(items[:2], 1)]
    result = build_financial_foundation("AAPL", items, refs, expected_cik="320193")
    assert len(result["claims"]) == 2
    assert "business model and competitive position" in result["unanswered_parts"]
    assert "issuer-disclosed operating-risk mechanisms" in result["unanswered_parts"]


def test_duplicate_quotes_do_not_expand_context_or_change_reference_ids():
    items = pair() + [business_item(), business_item(), risk_item(), risk_item()]
    result = build_financial_foundation("AAPL", items, None, expected_cik="320193")
    assert len(result["claims"]) == 4
    assert [row["reference_id"] for row in result["claims"]][-2:] == ["E3", "E5"]


def test_gate_is_idempotent_with_canonical_references_and_no_conviction(monkeypatch):
    monkeypatch.setattr(service.sec_provider, "_load_ticker_cik_map", lambda: {"AAPL": "320193"})
    items, refs, _ = admit_evidence(pair() + [business_item(), risk_item()], evaluated_at="2025-08-05")
    thesis = InvestmentThesis(ticker="AAPL", company_name="Apple")
    first = apply_source_answer_gate(thesis, QUESTION, items, references=refs)
    second = apply_source_answer_gate(thesis, QUESTION, items, references=refs)
    assert first == second
    assert first["status"] == "partial"
    assert thesis.confidence_score == 0 and thesis.directional_stance == ""
    assert all(row["reference_id"] in {r["id"] for r in refs} for row in first["claims"])


def test_live_fetch_spends_one_document_slot_and_keeps_both_bound_sections(monkeypatch):
    calls = []
    monkeypatch.setattr(service.sec_provider, "_load_ticker_cik_map", lambda: {"AAPL": "320193"})
    monkeypatch.setattr(service.sec_provider, "fetch_recent_filings", lambda *a, **k:
        [SimpleNamespace(url=document().final_url, timestamp='2025-08-01', document_type='10-K')])
    def fetch(*args, **kwargs):
        calls.append(kwargs)
        return document()
    monkeypatch.setattr(service, "fetch_public_document", fetch)
    items = service.fetch_thesis_disclosures("AAPL", question=QUESTION)
    assert len(calls) == 1 and calls[0]["preserve_sec_business"] is True
    assert calls[0]["extract_tables"] is False
    assert len(items) == 2
    assert items[0].business_disclosures and items[1].risk_disclosures


def test_discovery_failure_and_segment_requests_return_empty(monkeypatch):
    def unavailable(*a, **k):
        raise RuntimeError("offline")
    monkeypatch.setattr(service.sec_provider, "_load_ticker_cik_map", unavailable)
    assert service.fetch_thesis_disclosures("AAPL", question=QUESTION) == []
    assert not service.requests_thesis_disclosures("AAPL", "What is the investment thesis for Apple Services? Cite sources.")
    assert not service.requests_thesis_disclosures("AAPL", "What is the investment thesis for the App Store? Cite sources.")
    assert not service.requests_thesis_disclosures("AAPL", "What is the investment thesis for supply chain growth? Cite sources.")


def test_large_filing_opt_in_preserves_business_and_risk_without_raising_ceiling():
    parser = _HTMLTextExtractor()
    parser.feed('<p>' + 'Preamble. ' * 100 + document().text + '</p>')
    _, ordinary, _, _ = parser.result(max_chars=400, preserve_sec_risk=True)
    _, combined, _, _ = parser.result(max_chars=400, preserve_sec_risk=True, preserve_sec_business=True)
    assert 'Item 1. Business' not in ordinary
    assert BUSINESS in combined and RISK in combined
    assert len(combined) <= 400


def test_oversized_business_falls_back_to_complete_risk_section():
    parser = _HTMLTextExtractor()
    parser.feed('<p>' + 'Preamble. ' * 100 + 'Item 1. Business Overview. ' + BUSINESS * 10
                + f' Item 1A. Risk Factors {RISK} Item 1B. Unresolved Staff Comments</p>')
    _, text, _, _ = parser.result(max_chars=400, preserve_sec_risk=True, preserve_sec_business=True)
    assert RISK in text and BUSINESS not in text
    assert len(text) <= 400


def test_directory_resolved_unseen_issuer_uses_same_producers(monkeypatch):
    from app.services import issuer_identity
    directory = issuer_identity.parse_directory({"0": {
        "ticker": "ZQXS", "title": "Synthetic Components Inc.", "cik_str": 1234567}})
    monkeypatch.setattr(issuer_identity, "_load_directory", lambda: directory)
    monkeypatch.setattr(issuer_identity, "_cache", directory)
    url = document().final_url.replace('/320193/', '/1234567/')
    doc = document(final_url=url, requested_url=url)
    business = service.extract_business_descriptions(doc, ticker="ZQXS", cik="1234567")
    risks = service.extract_issuer_risk_evidence(doc, ticker="ZQXS",
        question="What operating risk affects Supply chain?")
    items = pair(ticker="ZQXS", cik="1234567") + business + risks
    result = build_financial_foundation("ZQXS", items, None, expected_cik="1234567")
    assert len(result["claims"]) == 4
    assert BUSINESS in result["answer"] and RISK in result["answer"]
    assert "competitive position" in result["unanswered_parts"]


@pytest.mark.parametrize('heading', ['Company Background', 'Overview', 'GENERAL',
                                     'Business Overview', 'Segment Information'])
def test_unpunctuated_shared_heading_preserves_complete_sentence_and_exact_span(heading):
    doc = document(f'Item 1. Business {heading} {BUSINESS} Item 1A. Risk Factors {RISK} Item 1B. Unresolved Staff Comments')
    stats = {}
    items = service.extract_business_descriptions(doc, ticker='AAPL', cik='320193', diagnostics=stats)
    assert len(items) == 1
    value = service.bound_business_description(items[0], ticker='AAPL', cik='320193')
    assert value['quote'] == BUSINESS
    assert doc.text[value['start_offset']:value['end_offset']] == BUSINESS
    assert stats['status'] == 'business_extracted' and stats['heading_prefixes_removed'] == 1
    assert BUSINESS not in repr(stats)


@pytest.mark.parametrize('prefix', ['If approved,', 'Our competitor says', 'Previously,',
                                    'Overview we may change our plans.', 'General hypothetical case'])
def test_arbitrary_prefix_cannot_be_removed_to_create_current_business_fact(prefix):
    doc = document(f'Item 1. Business {prefix} {BUSINESS} Item 1A. Risk Factors {RISK} Item 1B. Unresolved Staff Comments')
    items = service.extract_business_descriptions(doc, ticker='AAPL', cik='320193')
    # Only the separately punctuated complete sentence qualifies, never a
    # clipped conditional or a sentence attributed to a competitor.
    assert len(items) == (1 if prefix.endswith('.') else 0)


def test_business_diagnostics_distinguish_missing_section_from_rejected_prose():
    missing, rejected = {}, {}
    service.extract_business_descriptions(document(text=f'Item 1A. Risk Factors {RISK} Item 1B. Unresolved Staff Comments'),
        ticker='AAPL', cik='320193', diagnostics=missing)
    service.extract_business_descriptions(document(text='Item 1. Business Overview We may manufacture specialized components for customers in the future. Item 1A. Risk Factors'),
        ticker='AAPL', cik='320193', diagnostics=rejected)
    assert missing['status'] == 'no_complete_business_section'
    assert rejected['status'] == 'no_qualifying_business_sentence'
    assert rejected['rejection_counts'] == {'numeric_or_forward_looking': 1}
