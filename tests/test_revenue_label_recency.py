"""Revenue uses the issuer's current comparable concept, not the first configured one.

Fixtures are unmodified subsets of SEC Company Facts bodies retained by the
ordinary pilot run (see each fixture's _provenance). Alphabet stopped tagging
RevenueFromContractWithCustomerExcludingAssessedTax after 2025-03-31 and
reports Revenues; National Presto reports Revenues only.
"""
import json
from pathlib import Path

import pytest

from app.providers.sec_client import parse_company_fact_records
from app.services import verified_sec_metric_service as producer
from test_verified_sec_metrics import _record

FIXTURES = Path(__file__).with_name('fixtures')
QUESTION = 'How has revenue changed? Cite revenue trends.'


def _company_facts(monkeypatch, name, ticker):
    data = json.loads((FIXTURES / f'{name}_revenue_companyfacts_subset.json').read_text())
    cik = str(data['cik'])
    monkeypatch.setattr(producer, '_load_ticker_cik_map', lambda: {ticker: cik.zfill(10)})
    monkeypatch.setattr(producer, 'get_company_fact_records_for_concept_units',
        lambda _cik, *, concept_units, **_: [
            record for concept, unit in dict.fromkeys(concept_units)
            for record in parse_company_fact_records(data, concept=concept, unit=unit)])
    return data


def _revenue(items):
    rows = [item for item in items if item.verified_claims
            and item.verified_claims[0]['metric'].split(':')[-1] in
            ('Revenues', 'RevenueFromContractWithCustomerExcludingAssessedTax', 'RevenuesNetOfInterestExpense')]
    assert len(rows) <= 1
    return rows[0] if rows else None


def test_alphabet_revenue_uses_the_current_revenues_pair_from_retained_evidence(monkeypatch):
    _company_facts(monkeypatch, 'alphabet', 'GOOGL')
    item = _revenue(producer.fetch_verified_metric_evidence('GOOGL', question=QUESTION))
    assert item is not None, 'revenue was dropped as stale'
    current, prior = item.verified_claims
    # One concept on both sides; nothing joined across concepts.
    assert current['metric'] == prior['metric'] == 'us-gaap:Revenues'
    assert (current['period_start'], current['period_end'], current['raw_value']) == ('2026-07-01', '2026-09-30', 127577000000)
    assert (prior['period_start'], prior['period_end'], prior['raw_value']) == ('2025-07-01', '2025-09-30', 102346000000)
    assert current['unit'] == prior['unit'] == 'USD' and item.reporting_period_end == '2026-09-30'


def test_the_older_preferred_concept_is_complete_but_stale_for_alphabet(monkeypatch):
    # Documents the defect: the configured first concept alone stops at 2025-03-31.
    data = _company_facts(monkeypatch, 'alphabet', 'GOOGL')
    rows = parse_company_fact_records(data, concept='RevenueFromContractWithCustomerExcludingAssessedTax', unit='USD')
    item = producer.comparable_metric_evidence(rows, ticker='GOOGL', expected_cik=str(data['cik']),
        concepts=('RevenueFromContractWithCustomerExcludingAssessedTax',), metric_name='revenue')
    assert item is not None and item.reporting_period_end == '2025-03-31'


def test_national_presto_revenue_selection_is_unchanged(monkeypatch):
    _company_facts(monkeypatch, 'national_presto', 'NPK')
    item = _revenue(producer.fetch_verified_metric_evidence('NPK', question=QUESTION))
    current, prior = item.verified_claims
    assert current['metric'] == prior['metric'] == 'us-gaap:Revenues'
    assert (current['period_end'], current['raw_value']) == ('2026-07-05', 146596000)
    assert (prior['period_end'], prior['raw_value']) == ('2025-06-29', 120449000)


def test_equal_periods_keep_the_configured_concept_order(monkeypatch):
    rows = []
    for concept, values in (('RevenueFromContractWithCustomerExcludingAssessedTax', (100, 112)),
                            ('Revenues', (101, 113))):
        rows += [_record(concept=concept, value=values[0]),
                 _record(concept=concept, value=values[1], start='2025-01-01', end='2025-03-31',
                         filed='2025-05-01', accession='0000320193-25-000001')]
    monkeypatch.setattr(producer, '_load_ticker_cik_map', lambda: {'AAPL': '320193'})
    monkeypatch.setattr(producer, 'get_company_fact_records_for_concept_units', lambda *a, **k: rows)
    item = _revenue(producer.fetch_verified_metric_evidence('AAPL', question=QUESTION))
    assert item.verified_claims[0]['metric'] == 'us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax'
    assert [c['raw_value'] for c in item.verified_claims] == [112, 100]
