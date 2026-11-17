"""Losses, operating deficits and cash used are compared for as-reported issuers (foreign private issuers and non-USD filers), worded without a
percentage, in the filing's own currency, bound to both facts. Before this a zero or negative amount withheld the comparison
(`non_positive_value`), so a loss-making issuer kept only revenue. Development finding: about two thirds of omitted foreign-issuer
cells were withheld for this reason. Revenue stays withheld when zero or negative. Facts: the retained trimmed Company Facts of
diagnostic D1 (CGC, CAD, US-GAAP; MTA, USD, IFRS)."""
import json
from pathlib import Path

import pytest

from app.config import settings
from app.providers import sec_client
from app.services import as_reported_financials as ar
from app.services import financial_thesis_foundation as foundation

DATA = json.loads((Path(__file__).resolve().parent / 'data' / 'company_facts_lone_comparison_retained_d1.json').read_text())


@pytest.fixture(autouse=True)
def as_reported_on(monkeypatch):
    monkeypatch.setattr(settings, 'as_reported_financials_enabled', True, raising=False)


def built(key):
    cik = str(DATA[key]['cik'])
    records = sec_client.as_reported_records_from_facts(DATA[key], cik, specs=ar.requested_specs())
    items, withheld = ar.build_comparisons(records, ticker=key, cik=cik)
    return items, withheld, cik


def by_metric(items):
    return {i.verified_claims[0]['metric'].split(':')[1]: i for i in items}


@pytest.mark.parametrize('key,currency', [('CGC', 'CAD'), ('MTA', 'USD')])
def test_all_four_core_measures_are_compared_and_nothing_is_withheld(key, currency):
    items, withheld, cik = built(key)
    assert len(items) == 4 and withheld == []
    for item in items:
        assert {c['unit'] for c in item.verified_claims} == {currency} and len(item.verified_claims) == 2
        assert 'no currency conversion was applied' in item.summary
        assert ar.rebuild_as_reported(item, ticker=key, cik=cik, name=next(
            n for n, by in ar.CORE.items() if item.verified_claims[0]['metric'].split(':')[1] in {c for cs in by.values() for c in cs})) == item


def test_a_loss_in_both_years_says_whether_it_widened_or_narrowed_with_no_percentage():
    items, _, _ = built('CGC')
    op = by_metric(items)['OperatingIncomeLoss']
    assert 'was a loss in both periods; the loss widened by 44.5M CAD; signed amounts: -161.7M CAD' in op.summary and '%' not in op.summary
    net = by_metric(items)['NetIncomeLoss']
    assert 'the loss narrowed by 246M CAD' in net.summary and '%' not in net.summary
    assert [c['raw_value'] < 0 for c in op.verified_claims] == [True, True]


def test_cash_used_in_both_years_and_a_sign_change_are_worded_as_states():
    cgc = by_metric(built('CGC')[0])['NetCashProvidedByUsedInOperatingActivities']
    assert cgc.summary.startswith('CGC cash used in operating activities decreased by 101.9M CAD; signed amounts: -63.8M CAD')
    mta = by_metric(built('MTA')[0])['CashFlowsFromUsedInOperatingActivities']
    assert mta.summary.startswith('MTA operating cash flow moved from cash used to cash provided; signed amounts: $4.4M')


def test_the_amounts_and_periods_come_from_the_two_bound_facts():
    for key in ('CGC', 'MTA'):
        items, _, _ = built(key)
        for item in items:
            current, prior = item.verified_claims
            assert current['period_end'] > prior['period_end'] and current['currency'] == prior['currency'] == current['unit']
            assert current['document_ref']['reference_id'].startswith('sec:') and prior['document_ref']['reference_id'].startswith('sec:')


@pytest.mark.parametrize('key', ['CGC', 'MTA'])
def test_the_financial_foundation_now_has_all_four_comparisons(key):
    items, withheld, cik = built(key)
    for item in items:
        item.freshness_status = 'current'
    refs = [{'id': f'E{i}', 'title': item.title.strip()[:300], 'source': item.source.strip()[:120], 'url': item.url,
             'published_at': item.timestamp, 'freshness_status': 'current'} for i, item in enumerate(items, 1)]
    result = foundation.build_financial_foundation(key, items, refs, expected_cik=cik)
    assert result is not None and len(result['claims']) == 4


def rec(**over):
    base = dict(cik='1', taxonomy='ifrs-full', concept='ProfitLoss', label='x', unit='KRW', value=10, start='2024-01-01', end='2024-12-31',
                filed='2025-03-01', form='20-F', accession='0000000001-25-000001')
    base.update(over)
    base['filing_url'] = f"https://www.sec.gov/Archives/edgar/data/1/{base['accession'].replace('-', '')}/{base['accession']}-index.htm"
    return sec_client.SecFactRecord(**base)


def pair_of(current, prior, concept='ProfitLoss'):
    return (rec(concept=concept, value=current, start='2025-01-01', end='2025-12-31', filed='2026-03-01', accession='0000000001-26-000001'),
            rec(concept=concept, value=prior))


@pytest.mark.parametrize('current,prior,words', [
    (-5, 10, 'moved from a profit to a loss, a change of 15 KRW'),
    (10, -5, 'moved from a loss to a profit, a change of 15 KRW'),
    (0, 10, 'moved from a profit to zero, a change of 10 KRW'),
    (-10, -5, 'was a loss in both periods; the loss widened by 5 KRW'),
    (-5, -10, 'was a loss in both periods; the loss narrowed by 5 KRW'),
    (-5, -5, 'was a loss in both periods; the loss was unchanged'),
])
def test_every_sign_combination_for_net_income(current, prior, words):
    cur, old = pair_of(current, prior)
    item, why = ar.evidence_from_pair(cur, old, ticker='T', expected_cik='1', metric_name='net income')
    assert why is None and words in item.summary and '%' not in item.summary and 'KRW' in item.summary
    assert ar.rebuild_as_reported(item, ticker='T', cik='1', name='net income') == item


def test_a_zero_prior_year_is_still_withheld_and_revenue_is_never_signed():
    cur, old = pair_of(5, 0)
    assert ar.evidence_from_pair(cur, old, ticker='T', expected_cik='1', metric_name='net income')[1] == 'prior_value_zero'
    cur, old = pair_of(-5, 10, concept='Revenue')
    assert ar.evidence_from_pair(cur, old, ticker='T', expected_cik='1', metric_name='revenue')[1] == 'non_positive_value'
    cur, old = pair_of(5, -10, concept='Revenue')
    assert ar.evidence_from_pair(cur, old, ticker='T', expected_cik='1', metric_name='revenue')[1] == 'non_positive_value'


def test_positive_comparisons_are_worded_exactly_as_before():
    cur, old = pair_of(120, 100)
    item, _ = ar.evidence_from_pair(cur, old, ticker='T', expected_cik='1', metric_name='net income')
    assert item.summary.startswith('T net income including noncontrolling interests increased 20.0% to 120 KRW for the period 2025-01-01 to 2025-12-31, from 100 KRW')
