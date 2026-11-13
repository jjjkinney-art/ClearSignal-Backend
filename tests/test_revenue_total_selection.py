"""When revenue concepts for the same period disagree, the answer shows total revenues.

Defect (recorded in offline-review/DEFECT_REVENUE_DENOMINATOR_20261113.md): Fortis's retained Company Facts give
both total revenues (us-gaap:Revenues, 12.17B CAD) and revenue from contracts with customers (11.9B CAD) for
FY2025, and the answer showed the narrower line as "revenue" and divided total operating income by it (operating
margin 29.34% instead of 28.69%). Retained facts are trimmed copies from pilot Runs 4, 8, 9 and 11; the US-GAAP
issuer below is constructed and labelled as such, to show the rule is not specific to one ticker or taxonomy.
"""
import copy
import json
from decimal import Decimal
from pathlib import Path

import pytest

from app.config import settings
from app.providers import sec_client
from app.services import as_reported_financials as ar
from app.services import financial_thesis_foundation as foundation
from app.services import verified_sec_metric_service as service

DATA = Path(__file__).resolve().parent / 'data'
FACTS = json.loads((DATA / 'company_facts_as_reported_retained_runs4_11.json').read_text())
TRIMMED = json.loads((DATA / 'company_facts_trimmed_retained_runs4_11.json').read_text())


class Reply:
    def __init__(self, body):
        self._body = body

    def raise_for_status(self):
        pass

    def json(self):
        return self._body


def as_reported(key, ticker):
    records = sec_client.as_reported_records_from_facts(FACTS[key], str(FACTS[key]['cik']), specs=ar.requested_specs())
    return ar.build_comparisons(records, ticker=ticker, cik=str(FACTS[key]['cik']))[0]


def revenue_of(items):
    return next(i for i in items if i.verified_claims[0]['metric'].split(':')[1] in
                {c for by in ar.CORE['revenue'].values() for c in by})


def margin(items, ticker, cik):
    references = [{'id': f'E{i}', 'title': item.title.strip()[:300], 'source': item.source.strip()[:120],
                   'url': item.url, 'published_at': item.timestamp, 'freshness_status': 'current'}
                  for i, item in enumerate(items, start=1)]
    built = foundation.build_financial_foundation(ticker, items, references, expected_cik=cik)
    rows = [i for i in (built or {}).get('inferences', []) if i.get('kind') == 'operating_margin_calculation']
    return built, (rows[0] if rows else None)


# --- the reproduced case ----------------------------------------------------------------------------

def test_fortis_revenue_is_total_revenues_not_the_narrower_contract_line(monkeypatch):
    revenue = revenue_of(as_reported('FORFF', 'FTS'))
    assert revenue.verified_claims[0]['metric'] == 'us-gaap:Revenues'
    assert [c['raw_value'] for c in revenue.verified_claims] == [12170000000, 11508000000]
    assert 'revenue (as reported) increased 5.8% to 12.2B CAD' in revenue.summary


def test_fortis_margin_uses_total_revenues_as_its_denominator(monkeypatch):
    monkeypatch.setattr(settings, 'as_reported_financials_enabled', True, raising=False)
    items = as_reported('FORFF', 'FTS')
    for item in items:
        item.freshness_status = 'current'
    built, row = margin(items, 'FTS', str(FACTS['FORFF']['cik']))
    assert row is not None
    assert Decimal(row['current']['revenue']['raw_value']) == 12170000000
    assert round(Decimal(row['current']['margin_percent']), 2) == Decimal('28.69')
    assert round(Decimal(row['prior']['margin_percent']), 2) == Decimal('28.61')
    shown = json.dumps({k: built[k] for k in ('answer', 'claims', 'inferences')}, default=str)
    assert '29.34' not in shown and '29.28' not in shown and '28.69' in shown


# --- generalization ---------------------------------------------------------------------------------

def test_ifrs_issuers_with_a_narrower_contract_line_already_show_total_revenue():
    # BP and Marex (retained) report both ifrs-full:Revenue and RevenueFromContractsWithCustomers with different values.
    for key, total in (('BP', 192549000000), ('MRX', 2024100000)):
        revenue = revenue_of(as_reported(key, key))
        assert revenue.verified_claims[0]['metric'] == 'ifrs-full:Revenue' and revenue.verified_claims[0]['raw_value'] == total


def constructed_records(contract, total, operating, *, unit='GBP', cik='4242'):
    """A constructed US-GAAP issuer reporting both revenue concepts in GBP (utility-like); not retained data."""
    body = {'cik': int(cik), 'facts': {'us-gaap': {}}}

    def rows(values):
        return [{'start': f'{year}-01-01', 'end': f'{year}-12-31', 'val': value, 'accn': f'000{int(cik):07d}-{year % 100:02d}-000001',
                 'fy': year, 'fp': 'FY', 'form': '10-K', 'filed': f'{year + 1}-02-15'} for year, value in values]
    for concept, values in (('RevenueFromContractWithCustomerExcludingAssessedTax', contract), ('Revenues', total),
                            ('OperatingIncomeLoss', operating)):
        body['facts']['us-gaap'][concept] = {'label': concept, 'units': {unit: rows(values)}}
    return sec_client.as_reported_records_from_facts(body, cik, specs=ar.requested_specs())


def test_another_issuer_and_currency_follow_the_same_rule(monkeypatch):
    monkeypatch.setattr(settings, 'as_reported_financials_enabled', True, raising=False)
    records = constructed_records(contract=[(2024, 5_500_000_000), (2025, 6_000_000_000)],
                                  total=[(2024, 9_000_000_000), (2025, 10_000_000_000)],
                                  operating=[(2024, 1_300_000_000), (2025, 1_500_000_000)])
    items, _ = ar.build_comparisons(records, ticker='UTIL', cik='4242')
    revenue = revenue_of(items)
    assert revenue.verified_claims[0]['metric'] == 'us-gaap:Revenues' and revenue.verified_claims[0]['unit'] == 'GBP'
    for item in items:
        item.freshness_status = 'current'
    _, row = margin(items, 'UTIL', '4242')
    assert row is not None and round(Decimal(row['current']['margin_percent']), 2) == Decimal('15.00')  # not 25.00


def test_equal_values_keep_the_configured_order():
    same = [(2024, 9_000_000_000), (2025, 10_000_000_000)]
    items, _ = ar.build_comparisons(constructed_records(contract=same, total=same, operating=[(2024, 1), (2025, 2)]),
                                    ticker='UTIL', cik='4242')
    assert revenue_of(items).verified_claims[0]['metric'] == 'us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax'


def test_a_more_recent_concept_still_wins_over_an_older_total():
    items, _ = ar.build_comparisons(constructed_records(contract=[(2024, 5_500_000_000), (2025, 6_000_000_000)],
                                                       total=[(2023, 8_000_000_000), (2024, 9_000_000_000)],
                                                       operating=[(2024, 1), (2025, 2)]), ticker='UTIL', cik='4242')
    revenue = revenue_of(items)
    assert revenue.verified_claims[0]['metric'] == 'us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax'
    assert revenue.reporting_period_end == '2025-12-31'


def test_the_default_us_gaap_path_is_not_changed_by_this_fix():
    # The same selection rule in the default US-GAAP USD/EUR path is pinned by an existing test
    # (tests/test_revenue_label_recency.py::test_equal_periods_keep_the_configured_concept_order). Changing it is a
    # separate decision, recorded in offline-review/DEFECT_REVENUE_DENOMINATOR_20261113.md.
    source = (Path(__file__).resolve().parent.parent / 'app/services/verified_sec_metric_service.py').read_text()
    assert 'latest_revenue' not in source


def test_values_are_never_joined_across_concepts():
    revenue = revenue_of(as_reported('FORFF', 'FTS'))
    assert {c['metric'] for c in revenue.verified_claims} == {'us-gaap:Revenues'}


# --- a case where evidence is insufficient stays insufficient ---------------------------------------

def test_an_issuer_without_a_revenue_concept_gets_no_revenue_and_no_margin(monkeypatch):
    galt = copy.deepcopy(TRIMMED['GALT (Run 11, us-gaap, no revenue concept)'])
    monkeypatch.setattr(service, '_load_ticker_cik_map', lambda: {'GALT': str(galt['cik']).zfill(10)})
    monkeypatch.setattr(service, 'facts_not_applicable', lambda cik: None)
    monkeypatch.setattr(sec_client.requests, 'get', lambda *a, **k: Reply(copy.deepcopy(galt)))
    for flag in (False, True):
        monkeypatch.setattr(settings, 'as_reported_financials_enabled', flag, raising=False)
        items = service.fetch_verified_metric_evidence('GALT', question='What is the investment thesis for GALT?')
        assert not [i for i in items if i.verified_claims[0]['metric'].split(':')[1] in
                    {c for by in ar.CORE['revenue'].values() for c in by}]
        _, row = margin(items, 'GALT', str(galt['cik']))
        assert row is None


def test_latest_revenue_returns_the_first_candidate_when_there_is_one():
    revenue = revenue_of(as_reported('MRX', 'MRX'))
    assert ar.latest_revenue([revenue]) is revenue
