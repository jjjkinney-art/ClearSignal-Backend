"""Synthetic order context; never interpret backlog as recognized revenue."""
from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace

import pytest

from app.schemas import InvestmentThesis
from app.services import segment_order_context as service, thesis_disclosures as disclosures
from app.services.evidence_references import admit_evidence
from app.services.source_answer import apply_source_answer_gate
from test_financial_thesis_foundation import pair
from test_thesis_disclosures import document

DEFINITION = 'Backlog is defined as the value of orders from the customer less the amount of sales recognized against the orders.'
QUOTE = ('The contract backlog of the Water Systems segment was approximately $12,345,000, $10,000,000, and $9,500,000 at December 31, 2024, 2023, and 2022, respectively. ' + DEFINITION)


def doc(quote=QUOTE):
    return document(f'Item 1. Business {quote} Item 1A. Risk Factors Supply disruption could affect operations. Item 1B. Unresolved Staff Comments')


@pytest.mark.parametrize('label', ['Water Systems', 'Medical/Devices', 'Consumer & Industrial', 'Aerospace-Components'])
@pytest.mark.parametrize('approximation', [True, False])
def test_exact_complete_source_context_and_printed_values(label, approximation):
    quote = QUOTE.replace('Water Systems', label)
    if not approximation:
        quote = quote.replace('approximately ', '')
    document_value = doc(quote)
    item = service.extract_order_context(document_value, ticker='AAPL', cik='320193')[0]
    value = service.bound_order_context(item, ticker='AAPL', cik='320193')
    assert value['quote'] == quote
    assert document_value.text[value['start_offset']:value['end_offset']] == quote
    assert value['document_ref']['quote'] == quote
    context = value['order_context']
    assert context['scope'] == {'kind': 'named_segment', 'label': label}
    assert context['observations'] == [
        {'as_of': '2024-12-31', 'reported_amount': '$12,345,000'},
        {'as_of': '2023-12-31', 'reported_amount': '$10,000,000'},
        {'as_of': '2022-12-31', 'reported_amount': '$9,500,000'}]
    assert context['approximate'] is approximation
    assert context['currency_code'] is None
    assert context['numeric_normalization_performed'] is False
    assert item.verified_claims == [] and item.calculated_claims == []
    assert 'not recognized revenue or a forecast' in item.summary


def test_bom_preserved_and_following_forecast_not_clipped_into_context():
    quote = '\ufeff ' + QUOTE
    forecast = 'We expect all these orders to convert to revenue over the next year.'
    document_value = doc(quote + ' ' + forecast)
    item = service.extract_order_context(document_value, ticker='AAPL', cik='320193')[0]
    assert item.operating_disclosures[0]['quote'] == quote
    assert forecast not in item.summary


def test_decimal_amounts_remain_source_spelled_without_numeric_conversion():
    quote = QUOTE.replace('$12,345,000', '$12,345,000.50')
    item = service.extract_order_context(doc(quote), ticker='AAPL', cik='320193')[0]
    value = service.bound_order_context(item, ticker='AAPL', cik='320193')
    assert value['order_context']['observations'][0]['reported_amount'] == '$12,345,000.50'
    assert item.verified_claims == []


@pytest.mark.parametrize('quote', [
    QUOTE.replace('of the Water Systems segment', 'of this segment'),
    QUOTE.replace('of the Water Systems segment', 'of our competitor'),
    QUOTE.replace('was approximately', 'will be approximately'),
    QUOTE.replace('was approximately', 'is expected to be approximately'),
    QUOTE.replace('was approximately', 'was not approximately'),
    QUOTE.replace('$12,345,000', '$12,34,000'),
    QUOTE.replace('$12,345,000', '-$12,345,000'),
    QUOTE.replace('$12,345,000', '$12.3 million'),
    QUOTE.replace('2024, 2023, and 2022', '2024, 2024, and 2022'),
    QUOTE.replace('2024, 2023, and 2022', '2022, 2023, and 2024'),
    QUOTE.replace('December 31', 'February 30'),
    QUOTE.replace('respectively.', 'respectively, guaranteeing future revenue.'),
    QUOTE.replace(DEFINITION, 'Backlog guarantees future sales and profitability.'),
    QUOTE.replace(DEFINITION, 'Another sentence intervenes. ' + DEFINITION),
    QUOTE.replace('$10,000,000', '€10,000,000'),
    QUOTE.replace('The contract backlog', 'Our belief is that the contract backlog'),
    QUOTE.replace('Water Systems', 'Water Systems 2'),
])
def test_ambiguous_mixed_forecast_invalid_dates_and_incompatible_tokens_fail_closed(quote):
    assert service.parse_order_context(quote) is None
    assert service.extract_order_context(doc(quote), ticker='AAPL', cik='320193') == []


def test_definition_must_be_adjacent_and_inside_complete_business_window():
    text = f'Item 1. Business {QUOTE.replace(DEFINITION, "")} Item 1A. Risk Factors {DEFINITION} Item 1B. Unresolved Staff Comments'
    assert service.extract_order_context(document(text), ticker='AAPL', cik='320193') == []
    assert service.extract_order_context(document(QUOTE), ticker='AAPL', cik='320193') == []


@pytest.mark.parametrize('changes', [
    {'publisher': 'Other'}, {'document_type': '8-K'}, {'document_type': '10-Q'},
    {'source_tier': 'secondary'}, {'source_type': 'news'}, {'extraction_method': 'pdf'},
    {'text_ready': False}, {'final_url': 'https://example.invalid/annual.htm'},
    {'published_at': '2023-01-01'}, {'published_at': '2099-01-01'},
])
def test_document_identity_and_chronology_gates_are_unchanged(changes):
    assert service.extract_order_context(replace(doc(), **changes), ticker='AAPL', cik='320193') == []


@pytest.mark.parametrize('change', ['scope', 'amount', 'date', 'currency', 'definition', 'bool_type', 'metadata_missing', 'summary', 'offset', 'issuer', 'stale', 'section', 'filed_at', 'period'])
def test_final_binding_reconstructs_all_metadata_and_rejects_tampering(change):
    item = deepcopy(service.extract_order_context(doc(), ticker='AAPL', cik='320193')[0])
    value = item.operating_disclosures[0]
    context = value['order_context']
    if change == 'scope': context['scope']['label'] = 'Different'
    elif change == 'amount': context['observations'][0]['reported_amount'] = '$999'
    elif change == 'date': context['observations'][0]['as_of'] = '2023-12-31'
    elif change == 'currency': context['currency_code'] = 'USD'
    elif change == 'definition': context['definition'] = 'Forecast sales'
    elif change == 'bool_type': context['numeric_normalization_performed'] = 0
    elif change == 'metadata_missing': del value['order_context']
    elif change == 'summary': item.summary = 'Guaranteed future revenue.'
    elif change == 'offset': value['start_offset'] += 1
    elif change == 'issuer': value['ticker'] = 'OTHER'
    elif change == 'stale': item.freshness_status = 'stale'
    elif change == 'section': item.section = 'Item 1A. Risk Factors'
    elif change == 'filed_at': item.filed_at = '2024-01-01'
    elif change == 'period': item.reporting_period_end = '2024-12-31'
    if change != 'summary': item.summary = service._summary(value)
    assert service.bound_order_context(item, ticker='AAPL', cik='320193') is None


def test_one_order_item_cap_and_wrong_cik_denial():
    assert service.extract_order_context(doc(), ticker='AAPL', cik='999999') == []
    document_value = doc(QUOTE + ' ' + QUOTE.replace('Water Systems', 'Clinical Devices'))
    assert len(service.extract_order_context(document_value, ticker='AAPL', cik='320193')) == 1


def test_normal_disclosure_retrieval_and_final_answer_keep_business_and_thesis_gaps(monkeypatch):
    from app.services import issuer_identity
    ticker, cik = 'ZQXB', '1234567'
    directory = issuer_identity.parse_directory({'0': {'ticker': ticker, 'title': 'Invented issuer', 'cik_str': int(cik)}})
    monkeypatch.setattr(issuer_identity, '_load_directory', lambda: directory)
    monkeypatch.setattr(disclosures.sec_provider, '_load_ticker_cik_map', lambda: {ticker: cik})
    channel = 'Products are sold directly to retailers and also through independent distributors.'
    structure = 'The Clinical Devices segment consists of Quartz Laboratories LLC.'
    document_value = doc(channel + ' ' + structure + ' ' + QUOTE)
    url = document_value.final_url.replace('/320193/', f'/{cik}/')
    document_value = replace(document_value, final_url=url, requested_url=url)
    calls = []
    monkeypatch.setattr(disclosures.sec_provider, 'fetch_recent_filings', lambda *a, **kw: [
        SimpleNamespace(url=url, timestamp=document_value.published_at, document_type='10-K')])
    def saved_document(*args, **kwargs):
        calls.append(args[0]); return document_value
    monkeypatch.setattr(disclosures, 'fetch_public_document', saved_document)
    items = disclosures.fetch_thesis_disclosures(ticker, question=f'What is the investment thesis for {ticker}?')
    assert len(calls) == 1
    assert sum(bool(item.business_disclosures) for item in items) == 2
    assert sum(bool(item.operating_disclosures) for item in items) == 1
    admitted, refs, _ = admit_evidence(pair(ticker=ticker, cik=cik) + items, evaluated_at='2025-08-05')
    thesis = InvestmentThesis(ticker=ticker, company_name='Invented issuer')
    result = apply_source_answer_gate(thesis, f'What is the investment thesis for {ticker}? Cite material claims.', admitted, references=refs)
    order_claims = [claim for claim in result['claims'] if claim['claim_kind'] == 'issuer_order_backlog_context']
    assert len(order_claims) == 1 and QUOTE in order_claims[0]['claim']
    assert f"[{order_claims[0]['reference_id']}]" in thesis.direct_answer
    assert order_claims[0]['order_context']['currency_code'] is None
    assert 'not recognized revenue or a forecast' in thesis.direct_answer
    assert result['status'] == 'partial'
    assert result['business_context_coverage']['complete_business_model'] is False
    assert 'business model completeness' in result['unanswered_parts']
    assert 'valuation and expected returns' in result['unanswered_parts']
