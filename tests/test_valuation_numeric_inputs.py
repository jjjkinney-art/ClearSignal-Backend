"""Provider-to-prompt numeric integrity without any live requests."""
import socket

import pytest

from app.schemas import CompanyContext
from app.services.providers import fmp_provider as provider
from app.investment_agents.valuation_agent import _build_prompt, _filter_evidence


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def blocked(*args, **kwargs):
        pytest.fail('Numeric validation must not access the network')
    monkeypatch.setattr(socket, 'getaddrinfo', blocked)
    monkeypatch.setattr(socket.socket, 'connect', blocked)
    monkeypatch.setattr(socket.socket, 'connect_ex', blocked)
    monkeypatch.setattr(provider, '_get_api_key', lambda: 'synthetic')


def retrieve(monkeypatch, ratios=None, metrics=None):
    monkeypatch.setattr(provider, '_fetch_json', lambda url:
        [ratios or {}] if '/ratios-ttm/' in url else [metrics or {}])
    return provider.fetch_valuation_ratios('TEST')


@pytest.mark.parametrize('field', [
    'enterpriseValueMultipleTTM', 'evToEbitdaTTM', 'priceToSalesRatioTTM',
    'priceToFreeCashFlowsRatioTTM', 'priceFreeCashFlowRatioTTM',
    'priceToBookRatioTTM', 'returnOnEquityTTM',
])
@pytest.mark.parametrize('bad', [True, False, '12', 'bad', float('nan'), float('inf'), float('-inf'), [], {}])
def test_bad_ratio_field_neither_invents_numbers_nor_discards_valid_pe(monkeypatch, field, bad):
    item, = retrieve(monkeypatch, {'peRatioTTM': 25, field: bad})
    assert item.summary == 'TEST valuation multiples: Trailing P/E (TTM): 25.0x.'
    company = CompanyContext(ticker='TEST', company_name='Test')
    prompt = _build_prompt(company, _filter_evidence([item], company))
    assert item.summary in prompt
    assert item.timestamp == ''
    assert item.verified_claims == []


@pytest.mark.parametrize('field', [
    'revenuePerShareTTM', 'freeCashFlowYieldTTM', 'enterpriseValueTTM', 'netDebtToEBITDATTM',
])
@pytest.mark.parametrize('bad', [True, False, '12', 'bad', float('nan'), float('inf'), float('-inf'), [], {}])
def test_bad_key_metric_preserves_independent_valid_roic(monkeypatch, field, bad):
    item, = retrieve(monkeypatch, metrics={field: bad, 'roicTTM': .125})
    assert item.summary == 'TEST key metrics (TTM): ROIC: 12.5%.'


@pytest.mark.parametrize('bad', [True, 'bad', float('nan'), float('inf')])
def test_invalid_roic_alone_cannot_create_evidence(monkeypatch, bad):
    assert retrieve(monkeypatch, metrics={'roicTTM': bad}) == []


@pytest.mark.parametrize('first,second,label', [
    ('enterpriseValueMultipleTTM', 'evToEbitdaTTM', 'EV/EBITDA (TTM)'),
    ('priceToFreeCashFlowsRatioTTM', 'priceFreeCashFlowRatioTTM', 'Price/FCF (TTM)'),
])
def test_aliases_do_not_hide_valid_values_or_silently_choose_conflicts(monkeypatch, first, second, label):
    item, = retrieve(monkeypatch, {first: 'bad', second: 12})
    assert f'{label}: 12.0x' in item.summary
    item, = retrieve(monkeypatch, {first: 12, second: 12})
    assert item.summary.count(label) == 1
    item, = retrieve(monkeypatch, {'peRatioTTM': 25, first: 12, second: 15})
    assert label not in item.summary
    assert '25.0x' in item.summary


def test_zero_and_negative_reported_metrics_keep_their_numeric_meaning(monkeypatch):
    ratios, metrics = retrieve(monkeypatch,
        {'returnOnEquityTTM': 0, 'priceToFreeCashFlowsRatioTTM': -10},
        {'freeCashFlowYieldTTM': -.025, 'netDebtToEBITDATTM': 0, 'roicTTM': 0})
    assert 'ROE (TTM): 0.0%' in ratios.summary
    assert 'Price/FCF (TTM): -10.0x' in ratios.summary
    assert 'FCF yield: -2.5%' in metrics.summary
    assert 'Net Debt/EBITDA: 0.00x' in metrics.summary
    assert 'ROIC: 0.0%' in metrics.summary
    assert retrieve(monkeypatch, {'priceToSalesRatioTTM': 0}) == []


def test_percentage_conversion_does_not_overflow_a_finite_provider_number(monkeypatch):
    item, = retrieve(monkeypatch, {'returnOnEquityTTM': 1e308})
    assert 'inf' not in item.summary.lower()
    assert 'nan' not in item.summary.lower()
    assert 'ROE (TTM): ' + '1' + '0' * 310 + '.0%' in item.summary
