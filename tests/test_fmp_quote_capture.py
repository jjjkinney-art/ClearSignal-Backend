"""Invented FMP-shaped bytes; never live quotes or documentation sample values."""
from copy import deepcopy
import hashlib
import json

import pytest

from validation.fmp_quote_capture import ENDPOINT, map_fmp_quote_capture
from validation.dated_price import MAX_CAPTURE_BYTES

SYMBOL = 'ZQXB'
STAMP = 1772463600  # 2026-03-02T15:00:00Z, independently checked below


def row():
    return {'symbol': SYMBOL, 'price': 100.25, 'exchange': 'NASDAQ', 'timestamp': STAMP}


def args(payload=None, *, body=None):
    if body is None:
        body = json.dumps([row()] if payload is None else payload).encode()
    return {'body': body, 'receipt': {'sha256': hashlib.sha256(body).hexdigest(),
        'byte_length': len(body), 'endpoint': ENDPOINT, 'requested_symbol': SYMBOL,
        'retrieved_at': '2026-03-02T15:00:10Z', 'status_code': 200,
        'content_type': 'application/json'}, 'expected_symbol': SYMBOL,
        'analysis_as_of': '2026-03-02T15:01:00Z', 'evaluated_at': '2026-03-02T15:02:00Z',
        'freshness_policy': {'policy_id': 'synthetic-only-not-approved', 'max_age_seconds': 60}}


def reject(a):
    result = map_fmp_quote_capture(**a)
    assert result == {'mapped': False, 'admitted': False, 'launch_ready': False,
        'classification': 'offline_fmp_quote_candidate', 'reason': 'fmp_quote_capture_rejected',
        'diagnostic_type': result['diagnostic_type']}
    return result


def test_exact_raw_value_field_receipt_and_utc_time_are_bound_without_inventing_security():
    a = args()
    before = deepcopy(a)
    r = map_fmp_quote_capture(**a)
    assert r['mapped'] and not r['admitted'] and not r['launch_ready']
    assert r['candidate']['provider_quoted_at'] == '2026-03-02T15:00:00Z'
    # Unix epoch arithmetic using calendar-day difference, not mapper conversion.
    from datetime import date
    assert STAMP == (date(2026, 3, 2) - date(1970, 1, 1)).days * 86400 + 15 * 3600
    assert r['candidate']['price_value'] == '100.25'
    assert r['analysis_relative_age_seconds'] == 60
    assert r['candidate']['timestamp_semantics'] == 'provider_quote_time'
    for field in ('currency', 'price_unit', 'issuer_cik', 'listing_mic', 'security_id',
                  'share_class', 'split_basis', 'instrument_type', 'trade_or_close_kind', 'session'):
        assert r['candidate'][field] is None
    assert r['raw_binding']['sha256'] == hashlib.sha256(a['body']).hexdigest()
    assert r['raw_binding']['fields']['price_value'] == '/0/price'
    assert r['raw_binding']['fields']['provider_quoted_at'] == '/0/timestamp'
    assert r['observation_reference_inspectable'] is False
    assert 'contract_passed' not in r and 'values' not in r and 'verified_claims' not in r
    assert a == before
    r['supplied_freshness_policy']['max_age_seconds'] = 999
    r['raw_binding']['requested_symbol'] = 'CHANGED'
    assert a == before


@pytest.mark.parametrize('value', [0, -1, True, None, '100.25', {}, [], float('nan'), float('inf')])
def test_invalid_prices_refused(value):
    p = row()
    p['price'] = value
    reject(args([p]))


@pytest.mark.parametrize('token', [b'1e2', b'1E+2', b'1' * 67, b'0.000' + b'0' * 66 + b'1'])
def test_numeric_price_token_bounds_and_no_scientific_notation(token):
    body = args()['body'].replace(b'100.25', token)
    reject(args(body=body))


def test_decimal_price_lexeme_is_preserved_without_float_rounding():
    body = args()['body'].replace(b'100.25', b'100.123456789012345678901234567890123456789')
    result = map_fmp_quote_capture(**args(body=body))
    assert result['mapped']
    assert result['candidate']['price_value'] == '100.123456789012345678901234567890123456789'


@pytest.mark.parametrize('value', [True, 0, -1, STAMP * 1000, str(STAMP), STAMP + 0.5, None, {}, 9999999999])
def test_timestamp_is_not_guessed_from_milliseconds_strings_or_other_types(value):
    p = row()
    p['timestamp'] = value
    reject(args([p]))


@pytest.mark.parametrize('token', [b'1772463600.0', b'1.7724636e9', b'1' * 5000])
def test_unix_time_requires_bounded_integer_token(token):
    reject(args(body=args()['body'].replace(str(STAMP).encode(), token)))


@pytest.mark.parametrize('payload', [[], {}, [row(), row()], [None], [True],
    [{'symbol': 'OTHER', 'price': 100.25, 'timestamp': STAMP, 'exchange': 'NASDAQ'}],
    [{'symbol': SYMBOL, 'price': 100.25, 'exchange': 'NASDAQ', 'ipoDate': '2026-03-02'}],
    [{'symbol': SYMBOL, 'timestamp': STAMP, 'exchange': 'NASDAQ', 'previousClose': 100.25}],
    [{'symbol': SYMBOL, 'price': 100.25, 'timestamp': STAMP}],
    [{'symbol': SYMBOL.lower(), 'price': 100.25, 'timestamp': STAMP, 'exchange': 'NASDAQ'}]])
def test_wrong_ambiguous_missing_or_profile_values_cannot_be_selected(payload):
    reject(args(payload))


@pytest.mark.parametrize('value', ['', ' NASDAQ', 'NASDAQ ', {}, None, 'X' * 33, 'secret\ntext', 'https://secret.invalid'])
def test_provider_exchange_label_is_bounded_text_not_a_url_or_security_master(value):
    p = row()
    p['exchange'] = value
    reject(args([p]))


@pytest.mark.parametrize('mutation', [
    lambda a: a['receipt'].update(sha256='0' * 64),
    lambda a: a['receipt'].update(byte_length=True),
    lambda a: a['receipt'].update(byte_length=0),
    lambda a: a['receipt'].update(endpoint=ENDPOINT + '?apikey=SYNTHETIC_CANARY'),
    lambda a: a['receipt'].update(endpoint='https://financialmodelingprep.com/api/v3/quote/ZQXB'),
    lambda a: a['receipt'].update(requested_symbol='OTHER'),
    lambda a: a['receipt'].update(status_code=True),
    lambda a: a['receipt'].update(status_code=403),
    lambda a: a['receipt'].update(content_type='text/html'),
    lambda a: a['receipt'].update(extra='SYNTHETIC_CANARY'),
    lambda a: a.update(expected_symbol='OTHER'),
    lambda a: a.update(expected_symbol=[]),
    lambda a: a.update(expected_symbol='ZQXB/other'),
    lambda a: a['freshness_policy'].update(max_age_seconds=59),
    lambda a: a['freshness_policy'].update(max_age_seconds=True),
    lambda a: a['freshness_policy'].update(max_age_seconds=604801),
    lambda a: a['freshness_policy'].update(policy_id=''),
    lambda a: a.update(freshness_policy={}),
    lambda a: a['receipt'].update(retrieved_at='2026-03-02T14:59:59Z'),
    lambda a: a['receipt'].update(retrieved_at='2026-03-02T15:02:01Z'),
    lambda a: a.update(analysis_as_of='2026-03-02T14:59:59Z'),
    lambda a: a.update(analysis_as_of='2026-03-02T15:02:01Z'),
    lambda a: a.update(evaluated_at='2099-01-01T00:00:00Z'),
    lambda a: a.update(evaluated_at=None),
])
def test_receipt_chronology_or_policy_failures_return_fixed_diagnostics(mutation):
    a = args()
    mutation(a)
    r = reject(a)
    assert 'SYNTHETIC_CANARY' not in json.dumps(r)


@pytest.mark.parametrize('body', [b'', b'\xff', b'{', b'[[]]',
    b'[{"symbol":"OTHER","symbol":"ZQXB"}]', b'[' * 2000 + b']' * 2000])
def test_parser_failures_never_leak_source_values(body):
    reject(args(body=body))


def test_exact_byte_bound_then_overflow_and_caller_dictionary_refusal():
    body = args()['body']
    at_bound = body + b' ' * (MAX_CAPTURE_BYTES - len(body))
    assert map_fmp_quote_capture(**args(body=at_bound))['mapped']
    reject(args(body=at_bound + b' '))
    a = args()
    a['body'] = [row()]
    reject(a)


def test_optional_raw_identity_currency_and_session_hints_do_not_upgrade_admission():
    p = row()
    p.update(currency='USD', cik='0001234567', isAdr=False, shareClass='A',
        session='regular', kind='last_trade', split_basis='unchanged',
        secret='SYNTHETIC_CANARY', name='SYNTHETIC_CANARY')
    r = map_fmp_quote_capture(**args([p]))
    assert r['mapped'] and not r['admitted']
    assert 'SYNTHETIC_CANARY' not in json.dumps(r)
    assert r['candidate']['currency'] is None and r['candidate']['session'] is None


def test_raw_receipt_replay_accepts_recomputed_fabrication_without_claiming_authenticity():
    p = row()
    p['price'] = 999
    r = map_fmp_quote_capture(**args([p]))
    assert r['mapped'] and not r['admitted']
    assert 'not proof that FMP served these bytes' in ' '.join(r['limitations'])


def test_candidate_cannot_pass_trade_capture_or_source_eps_scenario_as_an_observation():
    from test_dated_price_capture import inputs
    from validation.dated_price import audit_dated_price_capture
    from test_source_anchored_valuation import assumptions, run
    r = map_fmp_quote_capture(**args())
    candidate = r['candidate']
    a = inputs()
    packet = json.loads(a['body'])
    packet['observation'].update(value=candidate['price_value'],
        observed_at=candidate['provider_quoted_at'], kind=candidate['trade_or_close_kind'],
        session=candidate['session'])
    a = inputs(payload=packet)
    assert not audit_dated_price_capture(**a)['contract_passed']
    p = assumptions()
    p['price'] = {'value': candidate['price_value'], 'unit': 'USD/share',
        'provenance': {'kind': 'source_observation', 'reference': ENDPOINT,
                       'observation_date': candidate['provider_quoted_at'][:10]}}
    assert not run(p)['available']
