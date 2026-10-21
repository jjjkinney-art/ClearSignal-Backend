"""Invented segment/company names; source scope must survive final composition."""
from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace

import pytest

from app.schemas import InvestmentThesis
from app.services import thesis_disclosures as service
from app.services.business_context import description_roles
from app.services.evidence_references import admit_evidence
from app.services.source_answer import apply_source_answer_gate
from test_financial_thesis_foundation import pair
from test_thesis_disclosures import document


QUOTE = 'The Laboratory Systems segment is currently comprised of Quartz Instruments, Inc. ("Quartz").'
CHANNELS = 'Products are sold directly to retailers and also through independent distributors.'


def fixture(quote=QUOTE):
    return document(f'Item 1. Business {CHANNELS} {quote} Item 1A. Risk Factors '
                    'Supply disruption could adversely affect operations. Item 1B. Unresolved Staff Comments')


@pytest.mark.parametrize('label', ['Laboratory Systems', 'Water/Filtration', 'Consumer & Industrial', 'Aerospace-Components'])
@pytest.mark.parametrize('predicate', ['is currently comprised of', 'is comprised of', 'consists of', 'comprises'])
def test_unseen_explicit_segment_structure_keeps_exact_scope_and_span(label, predicate):
    quote = f'The {label} segment {predicate} Quartz Instruments, Inc. ("Quartz").'
    doc = fixture(quote)
    items = service.extract_business_descriptions(doc, ticker='AAPL', cik='320193')
    assert len(items) == 2
    item = items[1]
    value = service.bound_business_description(item, ticker='AAPL', cik='320193')
    assert value['quote'] == quote
    assert doc.text[value['start_offset']:value['end_offset']] == quote
    assert value['document_ref']['quote'] == quote
    assert value['business_scope'] == {'kind': 'named_segment', 'label': label}
    assert description_roles(quote) == {'segments'}
    assert 'composition of the named segment only' in item.summary


@pytest.mark.parametrize('quote', [
    '\ufeff \ufeff ' + QUOTE,
    'The Clinical Devices segment consists of Quartz Laboratories LLC.',
    'The Clinical Devices segment comprises Quartz Laboratories Corporation.',
    'The Clinical Devices segment is comprised of Quartz Laboratories Ltd. ("Quartz").',
    'The Clinical Devices segment is comprised of Quartz Laboratories, Inc. ("Quartz").',
])
def test_bom_and_legal_suffixes_preserve_complete_quote(quote):
    doc = fixture(quote)
    item = service.extract_business_descriptions(doc, ticker='AAPL', cik='320193')[1]
    value = service.bound_business_description(item, ticker='AAPL', cik='320193')
    assert value['quote'] == quote
    assert doc.text[value['start_offset']:value['end_offset']] == quote
    assert description_roles(quote) == {'segments'}


@pytest.mark.parametrize('quote', [
    QUOTE.replace('The Laboratory Systems', 'The'),
    QUOTE.replace('The Laboratory Systems', 'This'),
    QUOTE.replace('The Laboratory Systems', 'Our competitor\'s Laboratory Systems'),
    QUOTE.replace('is currently comprised of', 'may be comprised of'),
    QUOTE.replace('is currently comprised of', 'will be comprised of'),
    QUOTE.replace('is currently comprised of', 'is expected to be comprised of'),
    QUOTE.replace('is currently comprised of', 'is not comprised of'),
    QUOTE.replace('Quartz Instruments, Inc.', 'superior Quartz Instruments, Inc.'),
    QUOTE.replace('Quartz Instruments, Inc.', 'Quartz Instruments, Inc. and other operations'),
    QUOTE.replace('Quartz Instruments, Inc.', 'our employees'),
    QUOTE[:-1] + ', creating long-term value.',
    QUOTE[:-1] + ' and generates revenue from services.',
    QUOTE.replace('Laboratory Systems', 'Laboratory Systems 2'),
    QUOTE.replace('Quartz Instruments, Inc.', 'Quartz Instruments'),
])
def test_unscoped_forecast_mixed_or_promotional_prose_is_not_admitted(quote):
    assert not service._business_quote(quote)
    items = service.extract_business_descriptions(fixture(quote), ticker='AAPL', cik='320193')
    assert [x.business_disclosures[0]['quote'] for x in items] == [CHANNELS]


def test_whole_sentence_boundaries_are_preserved_with_following_unrelated_sentence():
    assert not service._business_quote(QUOTE + ' Another sentence.')
    doc = fixture(QUOTE + ' Another sentence.')
    items = service.extract_business_descriptions(doc, ticker='AAPL', cik='320193')
    assert [x.business_disclosures[0]['quote'] for x in items] == [CHANNELS, QUOTE]


@pytest.mark.parametrize('change', ['missing', 'label', 'kind', 'extra'])
def test_final_binding_rejects_scope_tampering(change):
    item = deepcopy(service.extract_business_descriptions(fixture(), ticker='AAPL', cik='320193')[1])
    value = item.business_disclosures[0]
    if change == 'missing':
        del value['business_scope']
    elif change == 'label':
        value['business_scope']['label'] = 'Different segment'
    elif change == 'kind':
        value['business_scope']['kind'] = 'company'
    else:
        value['business_scope']['complete'] = True
    item.summary = service._business_summary(value)
    assert service.bound_business_description(item, ticker='AAPL', cik='320193') is None


def test_unscoped_business_cannot_gain_caller_supplied_segment_scope():
    item = deepcopy(service.extract_business_descriptions(fixture(), ticker='AAPL', cik='320193')[0])
    item.business_disclosures[0]['business_scope'] = {'kind': 'named_segment', 'label': 'Invented'}
    item.summary = service._business_summary(item.business_disclosures[0])
    assert service.bound_business_description(item, ticker='AAPL', cik='320193') is None


def test_business_section_identity_and_document_admission_remain_required():
    for changes in ({'publisher': 'Other'}, {'source_tier': 'secondary'},
                    {'document_type': '8-K'}, {'text_ready': False},
                    {'final_url': 'https://example.invalid/annual.htm'}):
        assert service.extract_business_descriptions(replace(fixture(), **changes), ticker='AAPL', cik='320193') == []
    assert service.extract_business_descriptions(fixture(), ticker='AAPL', cik='999999') == []
    doc = document(f'Item 1. Business {CHANNELS} Item 1A. Risk Factors {QUOTE} Item 1B. Unresolved Staff Comments')
    assert [x.business_disclosures[0]['quote'] for x in service.extract_business_descriptions(doc, ticker='AAPL', cik='320193')] == [CHANNELS]


@pytest.mark.parametrize('ticker,cik', [('AAPL', '320193'), ('ZQXB', '1234567')])
def test_final_answer_preserves_segment_scope_without_claiming_operations_or_full_model(monkeypatch, ticker, cik):
    from app.services import issuer_identity
    directory = issuer_identity.parse_directory({'0': {
        'ticker': ticker, 'cik_str': int(cik), 'title': 'Invented test company'}})
    monkeypatch.setattr(issuer_identity, '_load_directory', lambda: directory)
    monkeypatch.setattr(service.sec_provider, '_load_ticker_cik_map', lambda: {ticker: cik})
    doc = fixture()
    url = doc.final_url.replace('/320193/', f'/{cik}/')
    doc = replace(doc, final_url=url, requested_url=url)
    monkeypatch.setattr(service.sec_provider, 'fetch_recent_filings', lambda *a, **kw: [
        SimpleNamespace(url=url, timestamp=doc.published_at, document_type='10-K')])
    monkeypatch.setattr(service, 'fetch_public_document', lambda *a, **kw: doc)
    fetched = service.fetch_thesis_disclosures(ticker, question=f'What is the investment thesis for {ticker}?')
    items = [item for item in fetched if item.business_disclosures]
    admitted, refs, _ = admit_evidence(pair(ticker=ticker, cik=cik) + items, evaluated_at='2025-08-05')
    thesis = InvestmentThesis(ticker=ticker, company_name='Invented test company')
    result = apply_source_answer_gate(thesis,
        f'What is the investment thesis for {ticker}? Cite material claims.', admitted, references=refs)
    assert result['status'] == 'partial'
    claim = next(c for c in result['claims'] if c.get('business_scope'))
    assert claim['business_scope'] == {'kind': 'named_segment', 'label': 'Laboratory Systems'}
    assert QUOTE in claim['claim'] and f"[{claim['reference_id']}]" in thesis.direct_answer
    facets = {x['facet']: x for x in result['business_context_coverage']['facets']}
    assert facets['segments']['reference_ids'] == [claim['reference_id']]
    assert facets['activities']['status'] == facets['revenue_model']['status'] == 'not_verified'
    assert result['business_context_coverage']['complete_business_model'] is False
    assert 'business model completeness' in result['unanswered_parts']
    assert 'competitive position' in result['unanswered_parts']
    assert 'valuation and expected returns' in result['unanswered_parts']


def test_structure_cannot_displace_earlier_priority_operations_and_revenue_within_two_item_cap():
    activity = 'We manufacture specialized components and distribute our products through independent dealers.'
    revenue = 'We generate revenue primarily from sales of products and related customer support services.'
    doc = document(f'Item 1. Business {QUOTE} {activity} {revenue} Item 1A. Risk Factors')
    items = service.extract_business_descriptions(doc, ticker='AAPL', cik='320193')
    assert [x.business_disclosures[0]['quote'] for x in items] == [activity, revenue]
