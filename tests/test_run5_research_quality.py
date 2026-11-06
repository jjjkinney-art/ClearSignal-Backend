"""General causes of the run-5 research gaps, reproduced offline.

Run 5 (unseen cohort 2) is development evidence from here on. No rule names
an issuer; fixtures are invented or short passages of the retained filings.
"""
from app.services import verified_sec_metric_service as producer
from app.services.financial_thesis_foundation import CORE_METRICS
from test_verified_sec_metrics import _record

INCLUDING = 'RevenueFromContractWithCustomerIncludingAssessedTax'


def _pair(concept, current=120, prior=100, year=2026):
    return [_record(concept=concept, value=prior, start=f'{year - 1}-04-01', end=f'{year - 1}-06-30',
                    filed=f'{year - 1}-08-01', accession=f'0000320193-{(year - 1) % 100}-000001'),
            _record(concept=concept, value=current, start=f'{year}-04-01', end=f'{year}-06-30',
                    filed=f'{year}-08-01', accession=f'0000320193-{year % 100}-000001')]


def _revenue(monkeypatch, records):
    monkeypatch.setattr(producer, '_load_ticker_cik_map', lambda: {'AAPL': '320193'})
    monkeypatch.setattr(producer, 'get_company_fact_records_for_concept_units', lambda *a, **kw: records)
    items = producer.fetch_verified_metric_evidence('AAPL', question='Cite revenue trends')
    return [i for i in items if 'revenue' in i.summary.lower()]


def test_revenue_tagged_only_including_assessed_tax_is_a_revenue_comparison(monkeypatch):
    item, = _revenue(monkeypatch, _pair(INCLUDING))
    assert {c['metric'] for c in item.verified_claims} == {f'us-gaap:{INCLUDING}'}
    assert 'revenue from contracts with customers including assessed taxes increased 20.0%' in item.summary
    assert INCLUDING in CORE_METRICS['revenue']


def test_an_equal_period_tie_keeps_the_previously_selected_concept(monkeypatch):
    # Both concepts for the same periods: the earlier-configured concept wins,
    # values are never joined across concepts.
    item, = _revenue(monkeypatch, _pair('Revenues', 120, 100) + _pair(INCLUDING, 125, 104))
    assert {c['metric'] for c in item.verified_claims} == {'us-gaap:Revenues'}


def test_a_more_recent_including_pair_replaces_a_stale_preferred_pair(monkeypatch):
    item, = _revenue(monkeypatch, _pair('Revenues', year=2025) + _pair(INCLUDING, year=2026))
    assert item.reporting_period_end == '2026-06-30'
    assert {c['metric'] for c in item.verified_claims} == {f'us-gaap:{INCLUDING}'}
