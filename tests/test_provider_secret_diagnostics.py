"""Only synthetic credentials and intercepted transports; never provider traffic."""
import io
import json
import logging
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, quote_plus, urlsplit
from unittest.mock import MagicMock

import pytest

KEY = 'ZXQV_fixture_secret+/=?&'


def assert_private(capsys, caplog, key=KEY):
    captured = capsys.readouterr()
    logs = captured.out + captured.err + caplog.text
    assert key not in logs
    assert key[:4] not in logs
    assert quote_plus(key) not in logs
    assert 'api_key=' not in logs
    assert 'apikey=' not in logs


@pytest.mark.parametrize('key', [KEY, 'ZQ'])
@pytest.mark.parametrize('outcome', ['ok', 'http', 'network', 'unexpected'])
def test_fred_diagnostics(monkeypatch, capsys, caplog, key, outcome):
    from app.services import general_finance_evidence as fred
    monkeypatch.setenv('FRED_API_KEY', key)
    def fake_open(url, timeout):
        assert parse_qs(urlsplit(url).query)['api_key'] == [key]
        if outcome == 'http':
            raise HTTPError(url, 400, url, {}, io.BytesIO(url.encode()))
        if outcome == 'network':
            raise URLError(url)
        if outcome == 'unexpected':
            raise RuntimeError(url)
        response = MagicMock()
        response.__enter__.return_value = response
        response.read.return_value = json.dumps({'observations': [
            {'date': '2026-01-01', 'value': '1'}, {'value': '.'}]}).encode()
        return response
    monkeypatch.setattr(fred, 'urlopen', fake_open)
    result = fred.fetch_fred_series('DGS10')
    assert len(result) == (1 if outcome == 'ok' else 0)
    assert_private(capsys, caplog, key)
    if outcome == 'http':
        assert '400' in caplog.text


@pytest.mark.parametrize('function', ['search_ticker', 'fetch_company_profile', 'fetch_price_change',
    'fetch_income_metrics', 'fetch_debt_metrics', 'fetch_earnings_calendar',
    'fetch_valuation_ratios', 'fetch_analyst_estimates'])
@pytest.mark.parametrize('error', [HTTPError, URLError, RuntimeError])
def test_fmp_error_diagnostics(monkeypatch, capsys, caplog, function, error):
    from app.services.providers import fmp_provider as fmp
    monkeypatch.setenv('FMP_API_KEY', KEY)
    caplog.set_level(logging.DEBUG, logger=fmp.__name__)
    requests = []
    def fail(url, timeout=8):
        requests.append(url)
        if error is HTTPError:
            raise HTTPError(url, 401, url, {}, None)
        raise error(url)
    monkeypatch.setattr(fmp, '_fetch_json', fail)
    assert not getattr(fmp, function)('AAPL')
    assert requests
    assert_private(capsys, caplog)
    assert caplog.records


def test_legacy_fmp_error_diagnostics(monkeypatch, capsys, caplog):
    from app.providers import fmp_client
    def fail(url, timeout):
        assert KEY in url
        raise RuntimeError(url)
    monkeypatch.setattr(fmp_client.requests, 'get', fail)
    assert fmp_client._get('https://financialmodelingprep.com/api/v3/profile/AAPL?apikey=' + KEY) is None
    assert_private(capsys, caplog)
