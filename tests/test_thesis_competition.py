"""Synthetic competition prose tests; no assertion of real issuer advantage."""
from dataclasses import replace
from types import SimpleNamespace

import pytest

from app.services import thesis_competition as service, thesis_disclosures
from app.services.evidence_references import admit_evidence
from app.services.financial_thesis_foundation import build_financial_foundation
from test_thesis_disclosures import document, BUSINESS, RISK, QUESTION
from test_financial_thesis_foundation import pair

QUOTE = 'We compete primarily with established manufacturers in the market for specialized components.'


def competition_document(quote=QUOTE):
    return document(f'Item 1. Business Overview. {BUSINESS} {quote} '
                    f'Item 1A. Risk Factors {RISK} Item 1B. Unresolved Staff Comments')


def test_fetch_admission_and_answer_preserve_competitive_context(monkeypatch):
    doc = competition_document()
    monkeypatch.setattr(thesis_disclosures.sec_provider, '_load_ticker_cik_map', lambda: {'AAPL': '320193'})
    monkeypatch.setattr(thesis_disclosures.sec_provider, 'fetch_recent_filings', lambda *a, **kw: [
        SimpleNamespace(url=doc.final_url, timestamp=doc.published_at, document_type='10-K')])
    monkeypatch.setattr(thesis_disclosures, 'fetch_public_document', lambda *a, **kw: doc)
    fetched = thesis_disclosures.fetch_thesis_disclosures('AAPL', question=QUESTION)
    items = [i for i in fetched if i.competition_disclosures]
    assert len(items) == 1
    value = service.bound_competition_description(items[0], ticker='AAPL', cik='0000320193')
    assert doc.text[value['start_offset']:value['end_offset']] == QUOTE
    admitted, refs, _ = admit_evidence(pair() + fetched, evaluated_at='2025-08-05')
    result = build_financial_foundation('AAPL', admitted, refs)
    claims = [c for c in result['claims'] if c['claim_kind'] == 'issuer_competition_description']
    assert len(claims) == 1 and QUOTE in result['answer']
    assert any(r['id'] == claims[0]['reference_id'] for r in refs)
    assert 'competitive position' in result['unanswered_parts']
    assert 'valuation and expected returns' in result['unanswered_parts']
    assert 'durable advantage remain unverified' in result['answer']
    missing_refs = [r for r in refs if r['id'] != claims[0]['reference_id']]
    assert QUOTE not in build_financial_foundation('AAPL', admitted, missing_refs)['answer']


@pytest.mark.parametrize('quote', [
    'We compete on the basis of product performance, service quality and price in our markets.',
    'Our principal competitors include established manufacturers and regional distributors.',
    'Competition in our principal markets is based on product quality and customer service.',
])
def test_shared_rules_work_for_unseen_issuer(quote):
    doc = competition_document(quote)
    url = doc.final_url.replace('/320193/', '/1234567/')
    doc = replace(doc, requested_url=url, final_url=url)
    items = service.extract_competition_descriptions(doc, ticker='ZQXB', cik='1234567')
    assert len(items) == 1
    assert service.bound_competition_description(items[0], ticker='ZQXB', cik='1234567')['quote'] == quote


@pytest.mark.parametrize('quote', [
    'We believe our superior products provide a durable competitive advantage over other manufacturers.',
    'We compete with other manufacturers and expect to gain significant market share next year.',
    'We compete with other manufacturers and hold 80% of the global market for specialized components.',
    'We may compete with other manufacturers if we enter the specialized components market.',
    'Our competitor competes with other manufacturers in the specialized components market.',
])
def test_unsupported_claims_do_not_become_competitive_facts(quote):
    assert service.extract_competition_descriptions(competition_document(quote), ticker='AAPL', cik='320193') == []


@pytest.mark.parametrize('mutate', [
    lambda i: setattr(i, 'url', i.url.replace('/320193/', '/9999999/')),
    lambda i: setattr(i, 'summary', 'AAPL has a durable moat.'),
    lambda i: setattr(i, 'freshness_status', 'stale'),
    lambda i: setattr(i, 'availability_status', 'unavailable'),
    lambda i: setattr(i, 'section', 'Invented section'),
    lambda i: i.competition_disclosures[0].update(start_offset=True),
    lambda i: i.competition_disclosures[0].update(ticker='TSLA'),
    lambda i: i.competition_disclosures[0]['document_ref'].update(quote='Invented competitor.'),
    lambda i: i.competition_disclosures[0]['document_ref'].update(content_hash='invalid'),
    lambda i: i.competition_disclosures[0].update(reviewed_layout={'raw_content_hash': 'wrong'}),
])
def test_tampered_records_are_withheld(mutate):
    item = service.extract_competition_descriptions(competition_document(), ticker='AAPL', cik='320193')[0]
    mutate(item)
    assert service.bound_competition_description(item, ticker='AAPL', cik='320193') is None


def test_complete_sections_required_and_outside_prose_excluded():
    doc = document(f'{QUOTE} Item 1. Business Overview. {BUSINESS} '
                   f'Item 1A. Risk Factors {RISK} Item 1B. Unresolved Staff Comments')
    assert service.extract_competition_descriptions(doc, ticker='AAPL', cik='320193') == []
    assert service.extract_competition_descriptions(document(f'Item 1. Business {QUOTE}'), ticker='AAPL', cik='320193') == []


def test_risk_section_competition_has_exact_separate_provenance():
    doc = document(f'Item 1. Business Overview. {BUSINESS} Item 1A. Risk Factors '
                   f'{RISK} {QUOTE} Item 1B. Unresolved Staff Comments')
    item = service.extract_competition_descriptions(doc, ticker='AAPL', cik='320193')[0]
    value = service.bound_competition_description(item, ticker='AAPL', cik='320193')
    assert item.section == 'Item 1A. Risk Factors' and value['quote'] == QUOTE
    assert item.risk_disclosures == []


def test_predecessor_document_cannot_be_presented_as_current_competition():
    assert service.extract_competition_descriptions(competition_document(), ticker='XOM', cik='2115436') == []


def test_reviewed_foreign_layout_binding_and_current_identity_required():
    from app.services.reviewed_annual_layouts import REVIEWED_ANNUAL_LAYOUTS
    layout = REVIEWED_ANNUAL_LAYOUTS[0]
    text = (layout['business_mapping'] + ' Mapping ends. '
            'Risk and security Risk factors The risk factors outlined in this section are described here. '
            + QUOTE + ' Risk and security Information security We believe controls matter.')
    doc = replace(document(text), final_url=layout['url'], requested_url=layout['url'],
                  document_type='20-F', published_at=layout['filed_at'],
                  content_hash=layout['content_hash'],
                  canonical_content_hash=layout['canonical_content_hash'])
    item, = service.extract_competition_descriptions(doc, ticker='ASML', cik='0000937966')
    assert item.section == layout['section']
    assert service.bound_competition_description(item, ticker='ASML', cik='0000937966')
    assert service.bound_competition_description(item, ticker='ASML', cik='1234567') is None
    item.competition_disclosures[0]['reviewed_layout']['canonical_content_hash'] = '0' * 64
    assert service.bound_competition_description(item, ticker='ASML', cik='0000937966') is None


def test_predecessor_fetch_does_not_extract_competition(monkeypatch):
    doc = competition_document()
    monkeypatch.setattr(thesis_disclosures.sec_provider, '_load_ticker_cik_map', lambda: {'XOM': '2115436'})
    monkeypatch.setattr(thesis_disclosures.sec_provider, 'fetch_recent_filings', lambda *a, **kw: [])
    monkeypatch.setattr(thesis_disclosures, 'reviewed_predecessor_annual', lambda t: (
        SimpleNamespace(url=doc.final_url, timestamp=doc.published_at, document_type='10-K'), {'historical': True}))
    monkeypatch.setattr(thesis_disclosures, 'fetch_public_document', lambda *a, **kw: doc)
    monkeypatch.setattr(thesis_disclosures, 'extract_issuer_risk_evidence', lambda *a, **kw: [])
    def unexpected(*a, **kw):
        pytest.fail('predecessor must not enter current competition producer')
    monkeypatch.setattr(service, 'extract_competition_descriptions', unexpected)
    assert thesis_disclosures.fetch_thesis_disclosures('XOM', question=QUESTION) == []
