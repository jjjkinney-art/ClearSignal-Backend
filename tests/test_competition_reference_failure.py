"""Invented prose reproduces a citation-limit failure; no real filing replay."""
from types import SimpleNamespace

import pytest

from app.services import thesis_competition, thesis_disclosures
from test_thesis_disclosures import BUSINESS, RISK, QUESTION, document


LONG_COMPETITION = (
    'We compete with established national manufacturers and regional suppliers '
    'on the basis of product availability, customer service, distribution coverage '
    'and technical support across our markets, including suppliers serving '
    'specialized applications through independent dealers, direct sales channels '
    'and service relationships with industrial customers.'
)
SHORT_COMPETITION = 'We compete with regional suppliers on the basis of product availability and customer service.'
SECOND_BUSINESS = 'We provide maintenance services and technical support to industrial customers through independent dealers.'


def test_one_unrepresentable_competition_quote_preserves_other_thesis_evidence(monkeypatch, caplog):
    assert 300 < len(LONG_COMPETITION) <= 450
    doc = document(f'Item 1. Business {BUSINESS} {SECOND_BUSINESS} '
                   f'{LONG_COMPETITION} {SHORT_COMPETITION} '
                   f'Item 1A. Risk Factors {RISK} Item 1B. Unresolved Staff Comments')
    monkeypatch.setattr(thesis_disclosures.sec_provider, '_load_ticker_cik_map', lambda: {'AAPL': '320193'})
    monkeypatch.setattr(thesis_disclosures.sec_provider, 'fetch_recent_filings', lambda *a, **kw: [
        SimpleNamespace(url=doc.final_url, timestamp=doc.published_at, document_type='10-K')])
    monkeypatch.setattr(thesis_disclosures, 'fetch_public_document', lambda *a, **kw: doc)
    with caplog.at_level('INFO', logger=thesis_disclosures.__name__):
        items = thesis_disclosures.fetch_thesis_disclosures('AAPL', question=QUESTION)
    business = [item for item in items if item.business_disclosures]
    competition = [item for item in items if item.competition_disclosures]
    assert len(business) == 2
    assert len(competition) == 1
    assert any(item.risk_disclosures for item in items)
    assert all(thesis_disclosures.bound_business_description(item, ticker='AAPL', cik='320193')
               for item in business)
    bound = thesis_competition.bound_competition_description(competition[0], ticker='AAPL', cik='320193')
    assert bound['quote'] == SHORT_COMPETITION
    assert doc.text[bound['start_offset']:bound['end_offset']] == SHORT_COMPETITION
    row = next(r.thesis_disclosure_diagnostics for r in caplog.records
               if hasattr(r, 'thesis_disclosure_diagnostics'))
    assert row['status'] == 'extraction_complete'
    assert row['business_count'] == 2 and row['competition_count'] == 1


@pytest.mark.parametrize('section, expected', [('business', 0), ('risk', 1)])
def test_existing_section_specific_quote_limits_are_preserved(section, expected):
    business = LONG_COMPETITION if section == 'business' else BUSINESS
    risk = LONG_COMPETITION if section == 'risk' else RISK
    doc = document(f'Item 1. Business {business} Item 1A. Risk Factors {risk} '
                   'Item 1B. Unresolved Staff Comments')
    items = thesis_competition.extract_competition_descriptions(doc, ticker='AAPL', cik='320193')
    assert len(items) == expected
    if items:
        assert thesis_competition.bound_competition_description(items[0], ticker='AAPL', cik='320193')['quote'] == LONG_COMPETITION
