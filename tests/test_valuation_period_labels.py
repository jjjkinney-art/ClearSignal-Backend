"""Offline regressions for time-basis integrity in provider and agent evidence."""
import socket

import pytest

from app.schemas import CompanyContext
from app.services.providers import fmp_provider
from app.investment_agents.valuation_agent import _build_prompt, _filter_evidence


@pytest.fixture(autouse=True)
def forbid_network(monkeypatch):
    def blocked(*args, **kwargs):
        pytest.fail('Valuation period tests must not access the network')
    monkeypatch.setattr(socket, 'getaddrinfo', blocked)
    monkeypatch.setattr(socket.socket, 'connect', blocked)
    monkeypatch.setattr(socket.socket, 'connect_ex', blocked)
    monkeypatch.setattr(fmp_provider, '_get_api_key', lambda: 'synthetic-test-key')


def evidence(monkeypatch, ratios):
    monkeypatch.setattr(fmp_provider, '_fetch_json',
                        lambda url: [ratios] if '/ratios-ttm/' in url else [])
    return fmp_provider.fetch_valuation_ratios('TEST')


@pytest.mark.parametrize('payload', [
    {'peRatioTTM': 25}, {'priceEarningsRatioTTM': 25},
    {'peRatioTTM': 25, 'priceEarningsRatioTTM': 25},
])
def test_trailing_aliases_never_become_forward(monkeypatch, payload):
    items = evidence(monkeypatch, payload)
    assert len(items) == 1
    assert items[0].summary.count('Trailing P/E (TTM): 25.0x') == 1
    assert 'Forward P/E:' not in items[0].summary
    company = CompanyContext(ticker='TEST', company_name='Test Company')
    prompt = _build_prompt(company, _filter_evidence(items, company))
    assert 'Trailing P/E (TTM): 25.0x' in prompt
    assert 'Forward P/E: 25.0x' not in prompt


@pytest.mark.parametrize('forward', [20, 25, -5])
def test_explicit_forward_remains_independent(monkeypatch, forward):
    item = evidence(monkeypatch, {'peRatioTTM': 25, 'forwardPE': forward})[0]
    assert 'Trailing P/E (TTM): 25.0x' in item.summary
    assert f'Forward P/E: {forward:.1f}x' in item.summary
    assert item.title == 'TEST Valuation Multiples'
    assert 'valuation multiples (TTM)' not in item.summary


def test_conflicting_trailing_aliases_do_not_override_forward_or_other_metrics(monkeypatch):
    item = evidence(monkeypatch, {'peRatioTTM': 25, 'priceEarningsRatioTTM': 30,
                                 'forwardPE': 20, 'priceToSalesRatioTTM': 4})[0]
    assert 'Trailing P/E' not in item.summary
    assert 'Forward P/E: 20.0x' in item.summary
    assert 'Price/Sales (TTM): 4.0x' in item.summary


@pytest.mark.parametrize('invalid', [None, 0, False, True, '25', 'bad', [], {},
                                     float('nan'), float('inf'), -float('inf'), 10**400])
@pytest.mark.parametrize('key', ['peRatioTTM', 'priceEarningsRatioTTM', 'forwardPE'])
def test_invalid_ratio_does_not_discard_valid_other_evidence(monkeypatch, key, invalid):
    item = evidence(monkeypatch, {key: invalid, 'priceToSalesRatioTTM': 4})[0]
    assert 'P/E' not in item.summary
    assert 'Price/Sales (TTM): 4.0x' in item.summary


def test_forward_only_and_negative_trailing_keep_explicit_basis(monkeypatch):
    assert 'Forward P/E: 25.0x' in evidence(monkeypatch, {'forwardPE': 25})[0].summary
    assert 'Trailing P/E (TTM): -5.0x' in evidence(monkeypatch, {'peRatioTTM': -5})[0].summary


def test_invalid_primary_alias_does_not_hide_valid_alternate(monkeypatch):
    item = evidence(monkeypatch, {'peRatioTTM': 'bad', 'priceEarningsRatioTTM': 25})[0]
    assert 'Trailing P/E (TTM): 25.0x' in item.summary
    assert 'Forward P/E' not in item.summary


def test_provider_prose_does_not_become_bound_financial_foundation(monkeypatch):
    from app.services.financial_thesis_foundation import build_financial_foundation
    items = evidence(monkeypatch, {'priceEarningsRatioTTM': 25, 'forwardPE': 20})
    assert items
    assert items[0].timestamp == ''
    assert items[0].source_tier == 'unverified'
    assert items[0].verified_claims == []
    assert build_financial_foundation('TEST', items, [], expected_cik='123456') is None


def test_key_metrics_have_unknown_date_without_losing_valid_evidence(monkeypatch):
    monkeypatch.setattr(fmp_provider, '_fetch_json',
                        lambda url: [{'freeCashFlowYieldTTM': .05}]
                        if '/key-metrics-ttm/' in url else [])
    items = fmp_provider.fetch_valuation_ratios('TEST')
    assert len(items) == 1
    assert items[0].source == 'FMP/key-metrics-ttm'
    assert items[0].timestamp == ''
    assert 'FCF yield: 5.0%' in items[0].summary
