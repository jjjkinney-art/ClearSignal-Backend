"""Bank net revenue retains its measure across producer, filing and answer paths."""
from copy import deepcopy
from dataclasses import replace

from app.schemas import InvestmentThesis
from app.services import verified_sec_metric_service as producer
from app.services.filing_metric_evidence import merge_latest_filing_metrics
from app.services.financial_thesis_foundation import build_financial_foundation, CORE_METRICS, _rebuild
from app.services.financial_reporting_coverage import reporting_coverage
from app.services.source_answer import apply_source_answer_gate
from test_filing_metric_evidence import _items, _xml, _filing
from test_financial_thesis_foundation import evidence, reference
from test_verified_sec_metrics import _record

CONCEPT = 'RevenuesNetOfInterestExpense'
LABEL = 'revenue net of interest expense'


def bank_filing():
    xml = _xml(CONCEPT, current='57,347', prior='44,912').replace('scale="3"', 'scale="6"')
    return _items(xml)[0]


def test_latest_inline_bank_revenue_has_same_concept_pairs_exact_values_and_replay():
    item = bank_filing()
    assert [c['raw_value'] for c in item.verified_claims] == [57347000000, 44912000000]
    assert {c['metric'] for c in item.verified_claims} == {f'us-gaap:{CONCEPT}'}
    assert f'AAPL {LABEL} increased 27.7%' in item.summary
    assert _rebuild(item, ticker='AAPL', cik='320193', name='revenue', concepts=CORE_METRICS['revenue'])
    altered = deepcopy(item)
    altered.summary = altered.summary.replace(LABEL, 'revenue')
    assert _rebuild(altered, ticker='AAPL', cik='320193', name='revenue', concepts=CORE_METRICS['revenue']) is None


def test_latest_bank_comparison_replaces_whole_older_generic_pair_and_closes_only_revenue_lag(monkeypatch):
    monkeypatch.setattr('app.services.providers.sec_provider._load_ticker_cik_map', lambda: {'AAPL':'320193'})
    old = evidence('Revenues', 'revenue')
    latest = bank_filing()
    cash = evidence('NetCashProvidedByUsedInOperatingActivities', 'operating cash flow')
    merged = merge_latest_filing_metrics([old, cash], [latest], ticker='AAPL')
    assert old not in merged and latest in merged and cash in merged
    material = merged + [_filing()]
    refs = [reference(x, f'E{i}') for i, x in enumerate(material, 1)]
    thesis = InvestmentThesis(ticker='AAPL', company_name='Synthetic bank')
    result = apply_source_answer_gate(thesis, 'What is the investment thesis for AAPL? Cite material claims.', material, references=refs)
    assert result['status'] == 'partial'
    assert 'latest-period revenue' not in result['unanswered_parts']
    assert 'operating income' in result['unanswered_parts']
    assert 'valuation and expected returns' in result['unanswered_parts']
    assert LABEL in thesis.direct_answer
    assert f'Reported {LABEL} is higher' in thesis.direct_answer
    assert thesis.confidence_score == 0 and thesis.directional_stance == ''
    coverage, _, _ = reporting_coverage('AAPL', material, result and merged, refs)
    assert [r['metric'] for r in coverage['metrics_behind']] == ['operating cash flow']


def test_equal_period_generic_and_bank_measures_cannot_silently_replace_each_other():
    ordinary = _items()[0]
    bank = bank_filing()
    from unittest.mock import patch
    with patch('app.services.providers.sec_provider._load_ticker_cik_map', return_value={'AAPL':'320193'}):
        assert merge_latest_filing_metrics([ordinary], [bank], ticker='AAPL') == [ordinary]
    cash = evidence('NetCashProvidedByUsedInOperatingActivities', 'operating cash flow')
    assert build_financial_foundation('AAPL', [ordinary, bank, cash], None, expected_cik='320193') is None


def test_company_facts_selects_complete_newer_bank_pair_in_one_fetch(monkeypatch):
    ordinary = [_record(), _record(value=110, start='2025-01-01', end='2025-03-31',
                    filed='2025-05-01', accession='0000320193-25-000001')]
    bank = [replace(row, concept=CONCEPT, start=row.start.replace('-01-01','-04-01'),
                    end=row.end.replace('-03-31','-06-30'), filed=row.filed.replace('-05-01','-08-01'))
            for row in ordinary]
    calls = []
    monkeypatch.setattr(producer, '_load_ticker_cik_map', lambda: {'AAPL':'320193'})
    monkeypatch.setattr(producer, 'get_company_fact_records_for_concept_units',
        lambda *a, **kw: calls.append(kw) or ordinary + bank)
    item, = producer.fetch_verified_metric_evidence('AAPL', question='Cite revenue trends')
    assert len(calls) == 1 and (CONCEPT, 'USD') in calls[0]['concept_units']
    assert LABEL in item.summary and item.reporting_period_end == '2025-06-30'
    # A current bank fact without its own prior-year fact cannot borrow ordinary revenue.
    monkeypatch.setattr(producer, 'get_company_fact_records_for_concept_units', lambda *a, **kw: ordinary + bank[1:])
    item, = producer.fetch_verified_metric_evidence('AAPL', question='Cite revenue trends')
    assert item.verified_claims[0]['metric'] == 'us-gaap:Revenues'


def test_old_bank_measure_remains_correctly_labeled_in_coverage_warning(monkeypatch):
    monkeypatch.setattr('app.services.providers.sec_provider._load_ticker_cik_map', lambda: {'AAPL':'320193'})
    old = evidence(CONCEPT, LABEL)
    coverage, notice, gaps = reporting_coverage('AAPL', [old, _filing()], [old])
    assert coverage['metrics_behind'][0]['metric'] == LABEL
    assert gaps == [f'latest-period {LABEL}'] and LABEL in notice
