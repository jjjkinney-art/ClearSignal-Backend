"""Shared product-channel grammar; invented identities, no network retrieval."""
from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace

import pytest
from test_thesis_disclosures import document
from app.services import thesis_disclosures as service
from app.services import issuer_identity

QUOTE = 'Products are sold primarily in the United States and Canada directly to retailers and also through independent distributors.'


@pytest.mark.parametrize('quote', [QUOTE, '\ufeff '+QUOTE,
    'Our products are sold principally in Europe directly to consumers and through independent retailers.',
    'Products are sold directly to customers and also through independent wholesalers.'])
def test_complete_product_channel_sentence_retains_exact_source_span(quote, monkeypatch):
    # No directory is necessary for a generic product-channel subject.
    monkeypatch.setattr(issuer_identity, '_load_directory', lambda: SimpleNamespace(symbols={}))
    text = f'Item 1. Business {quote} Item 1A. Risk Factors Supply disruption could affect product sales. Item 1B. Unresolved Staff Comments'
    doc = document(text)
    items = service.extract_business_descriptions(doc, ticker='AAPL', cik='320193')
    assert len(items) == 1
    value = service.bound_business_description(items[0], ticker='AAPL', cik='320193')
    assert value['quote'] == quote
    assert text[value['start_offset']:value['end_offset']] == quote
    assert value['document_ref']['quote'] == quote
    assert service.bound_business_description(items[0], ticker='AAPL', cik='999999') is None


@pytest.mark.parametrize('quote', [
    'Products may be sold primarily in the United States directly to retailers and through distributors.',
    'Products will be sold directly to customers and also through independent wholesalers.',
    'Products are expected to be sold primarily in Europe directly to consumers and through independent retailers.',
    'Products are sold directly to customers and through distributors, creating long-term value.',
    'Products are sold directly to customers and through distributors that enrich the lives of consumers.',
    'Products are sold directly to customers and through distributors at superior prices.',
    'Products are sold primarily to our employees through internal distributors and payroll deduction.',
    'Products are sold directly to customers and also through independent wholesalers at 20% margins.',
    'Products are sold directly to customers and also through independent wholesalers; demand may fall.',
    'Products are sold directly to customers and also through independent wholesalers. Another sentence.',
    'Our belief is that products are sold directly to customers and through independent wholesalers.',
    'The segment also markets an economy line of carbon monoxide and smoke alarms and a PFAS-Free Foam commercial fire extinguisher.',
    'The Safety segment provides innovative safety technology empowering organizations and individuals to protect what is most important.',
    'The company consists of three business segments without any further description of their operations.',
])
def test_other_prose_remains_rejected(quote):
    assert not service._business_quote(quote, ticker=None, cik=None)


@pytest.mark.parametrize('changes', [
    {'publisher':'Other publisher'}, {'source_tier':'secondary'},
    {'source_type':'news'}, {'extraction_method':'pdf'},
    {'document_type':'8-K'}, {'text_ready':False},
    {'final_url':'https://example.invalid/annual.htm'},
])
def test_existing_document_admission_stays_mandatory(changes):
    doc = document(f'Item 1. Business {QUOTE} Item 1A. Risk Factors')
    assert service.extract_business_descriptions(replace(doc, **changes), ticker='AAPL', cik='320193') == []


def test_bound_quote_tampering_still_refused():
    items = service.extract_business_descriptions(
        document(f'Item 1. Business {QUOTE} Item 1A. Risk Factors'), ticker='AAPL', cik='320193')
    item = deepcopy(items[0])
    item.business_disclosures[0]['quote'] = 'Invented rewritten distribution statement.'
    assert service.bound_business_description(item,ticker='AAPL',cik='320193') is None
