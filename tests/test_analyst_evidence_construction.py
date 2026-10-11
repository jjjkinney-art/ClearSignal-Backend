"""Offline contracts: estimates are usable but never reported or dated facts."""
import socket

import pytest

from app.services.providers import fmp_provider


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def blocked(*args, **kwargs):
        pytest.fail('No network permitted in analyst evidence tests')
    monkeypatch.setattr(socket, 'getaddrinfo', blocked)
    monkeypatch.setattr(socket.socket, 'connect', blocked)
    monkeypatch.setattr(socket.socket, 'connect_ex', blocked)
    monkeypatch.setattr(fmp_provider, '_get_api_key', lambda: 'synthetic-test-key')


def fetch(monkeypatch, estimates=None, targets=None):
    monkeypatch.setattr(fmp_provider, '_fetch_json',
                        lambda url: estimates if '/analyst-estimates/' in url else targets)
    return fmp_provider.fetch_analyst_estimates('TEST')


def test_valid_estimates_and_targets_return_actual_evidence(monkeypatch):
    items = fetch(monkeypatch, [{'date': '2027-06-30', 'estimatedRevenueAvg': 1e9,
        'estimatedEpsAvg': 2.5, 'estimatedRevenueLow': 9e8, 'estimatedRevenueHigh': 1.1e9,
        'numberAnalystEstimatedRevenue': 12}], [{'targetMean': 100, 'targetMedian': 99,
        'targetLow': 80, 'targetHigh': 120}])
    assert len(items) == 2
    assert 'Revenue est. (period ending 2027-06-30): $1.00B' in items[0].summary
    assert 'EPS est. (period ending 2027-06-30): $2.50' in items[0].summary
    assert '12 analyst estimates' in items[0].summary
    assert 'Consensus price target: $100.00' in items[1].summary
    assert 'Median: $99.00' in items[1].summary
    assert 'Range: $80.00 – $120.00' in items[1].summary
    from app.services.financial_thesis_foundation import build_financial_foundation
    assert build_financial_foundation('TEST', items, [], expected_cik='123456') is None
    for item in items:
        assert item.timestamp == ''
        assert item.claim_type == 'estimate'
        assert item.source_tier == 'unverified'
        assert item.verified_claims == []
        assert item.url is None
        assert item.reporting_period_end is None
        assert item.freshness_status == 'unknown'


@pytest.mark.parametrize('period', ['2000-01-01', '2099-01-01', None, '', 'bad', '2026-02-30'])
def test_period_does_not_become_publication_date_or_forward_claim(monkeypatch, period):
    item = fetch(monkeypatch, [{'date': period, 'estimatedEpsAvg': 0}])[0]
    assert item.timestamp == ''
    assert 'forward' not in item.summary.lower()
    assert 'EPS est.' in item.summary
    assert '$0.00' in item.summary
    assert ('period ending ' + period if period in ['2000-01-01', '2099-01-01']
            else 'period unavailable') in item.summary


@pytest.mark.parametrize('value', [None, True, False, '2.5', [], {}, float('nan'),
                                   float('inf'), -float('inf'), 10**400])
def test_malformed_fields_do_not_hide_independent_valid_values(monkeypatch, value):
    items = fetch(monkeypatch, [{'estimatedEpsAvg': value, 'estimatedRevenueAvg': 1e9}],
                  {'targetMean': value, 'targetMedian': 99})
    assert len(items) == 2
    assert 'EPS est.' not in items[0].summary
    assert 'Revenue est.' in items[0].summary
    assert 'Consensus price target' not in items[1].summary
    assert 'Median: $99.00' in items[1].summary


@pytest.mark.parametrize('payload', [None, [], {}, '', [None], [False], [{'x': 1}]])
def test_empty_or_malformed_payload_has_no_fabricated_evidence(monkeypatch, payload):
    assert fetch(monkeypatch, payload, payload) == []


def test_negative_earnings_and_zero_revenue_remain_estimates(monkeypatch):
    item = fetch(monkeypatch, [{'estimatedEpsAvg': -2, 'estimatedRevenueAvg': 0}])[0]
    assert 'EPS est. (period unavailable): $-2.00' in item.summary
    assert 'Revenue est. (period unavailable): $0.0M' in item.summary


def test_invalid_ranges_and_counts_are_not_rendered(monkeypatch):
    items = fetch(monkeypatch, [{'estimatedEpsAvg': 2, 'estimatedRevenueAvg': 100,
        'estimatedRevenueLow': 120, 'estimatedRevenueHigh': 80,
        'numberAnalystEstimatedRevenue': 1.5}], {'targetMean': 100,
        'targetLow': 120, 'targetHigh': 80})
    assert len(items) == 2
    assert 'range:' not in items[0].summary
    assert 'Based on' not in items[0].summary
    assert 'Range:' not in items[1].summary


def test_count_alone_is_not_an_estimate(monkeypatch):
    assert fetch(monkeypatch, [{'numberAnalystEstimatedRevenue': 12}]) == []


def test_consensus_alias_and_missing_key(monkeypatch):
    assert 'Consensus price target: $100.00' in fetch(monkeypatch, targets={'targetConsensus': 100})[0].summary
    monkeypatch.setattr(fmp_provider, '_get_api_key', lambda: '')
    assert fmp_provider.fetch_analyst_estimates('TEST') == []
