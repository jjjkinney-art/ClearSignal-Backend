"""Synthetic coverage gaps do not manufacture newer-period financial facts."""
import pytest

from app.schemas import InvestmentThesis
from app.services.providers.sec_provider import _make_evidence
from app.services.financial_reporting_coverage import reporting_coverage
from app.services.source_answer import apply_source_answer_gate
from test_financial_thesis_foundation import pair, reference


def filing(period='2025-09-30'):
    return _make_evidence('Synthetic company', '10-Q', '2025-11-01', period,
        'https://www.sec.gov/Archives/edgar/data/320193/000032019325000002/quarter.htm')


@pytest.fixture(autouse=True)
def directory(monkeypatch):
    from app.services.providers import sec_provider
    monkeypatch.setattr(sec_provider, '_load_ticker_cik_map', lambda: {'AAPL': '0000320193'})


@pytest.mark.parametrize('question', [
    'How have revenue and operating income changed? Cite figures and periods.',
    'What is the investment thesis for AAPL, what supports it, and what could invalidate it? Cite claims.',
])
def test_newer_filing_makes_older_comparisons_partial_without_replacing_facts(question):
    material = pair() + [filing()]
    refs = [reference(item, f'E{i}') for i, item in enumerate(material, 1)]
    thesis = InvestmentThesis(ticker='AAPL', company_name='Synthetic company')
    first = apply_source_answer_gate(thesis, question, material, references=refs)
    second = apply_source_answer_gate(thesis, question, material, references=refs)
    assert first == second
    assert first['status'] == 'partial'
    assert {'latest-period revenue', 'latest-period operating income'}.issubset(first['unanswered_parts'])
    coverage = first['reporting_coverage']
    assert coverage['latest_discovered_reporting_period'] == '2025-09-30'
    assert coverage['filing_reference_id'] == 'E3'
    assert [row['reference_id'] for row in coverage['metrics_behind']] == ['E1', 'E2']
    assert 'Figures and changes for the newer reporting period were not verified' in thesis.direct_answer
    assert all('2025-09-30' not in row['claim'] for row in first['claims'])
    assert len(thesis.quantitative_claims) == 4
    assert thesis.directional_stance == '' and thesis.confidence_score == 0


@pytest.mark.parametrize('period', ['2025-03-31', '2025-06-30'])
def test_same_or_older_filing_does_not_create_false_lag(period):
    items = pair()
    assert reporting_coverage('AAPL', items + [filing(period)], items) == (None, '', [])


@pytest.mark.parametrize('changes', [
    {'reporting_period_end': None}, {'reporting_period_end': 'bad'},
    {'reporting_period_end': '2099-01-01'}, {'timestamp': '2099-01-01'},
    {'reporting_period_end': '2025-10-31'},
    {'filed_at': '2025-10-31'}, {'source_tier': 'secondary'},
    {'claim_type': 'reported_fact'}, {'document_type': '8-K'},
    {'extraction_method': 'generated'}, {'freshness_status': 'conflicting'},
    {'url': 'https://www.sec.gov/Archives/edgar/data/1318605/000032019325000002/quarter.htm'},
    {'url': 'https://example.com/Archives/edgar/data/320193/000032019325000002/quarter.htm'},
])
def test_ineligible_inventory_cannot_create_coverage_warning(changes):
    metadata = filing()
    for key, value in changes.items():
        setattr(metadata, key, value)
    items = pair()
    assert reporting_coverage('AAPL', items + [metadata], items) == (None, '', [])


def test_unadmitted_inventory_and_tampered_fact_do_not_create_warning():
    items = pair()
    refs = [reference(item, f'E{i}') for i, item in enumerate(items, 1)]
    assert reporting_coverage('AAPL', items + [filing()], items, refs) == (None, '', [])
    items[0].summary = 'Invented newer figures'
    coverage, _, gaps = reporting_coverage('AAPL', items + [filing()], items)
    assert [row['metric'] for row in coverage['metrics_behind']] == ['operating income']
    assert gaps == ['latest-period operating income']


def test_discovery_metadata_retains_structured_report_date_without_numeric_claims():
    item = filing()
    assert item.reporting_period_end == '2025-09-30'
    assert item.verified_claims == [] and item.claim_type == 'filing_metadata'
