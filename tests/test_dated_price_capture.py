"""Invented normalized bytes only; no providers, live captures or holdouts."""
from copy import deepcopy
import hashlib
import json

import pytest

from validation.dated_price import audit_dated_price_capture, MAX_CAPTURE_BYTES

URL = 'https://prices.example.invalid/observations/synthetic-001'
SECURITY = {'symbol': 'ZQXB', 'issuer_cik': '0001234567', 'listing_mic': 'XNAS',
    'security_id': 'synthetic-common-A', 'share_class': 'Class A',
    'instrument_type': 'underlying_common_share', 'currency': 'USD',
    'price_unit': 'USD/share', 'split_basis': 'synthetic unchanged basis 2026-03-02'}


def packet():
    return {'schema': 'dated-price-capture-v1', 'source_url': URL,
        'security': deepcopy(SECURITY), 'observation': {'value': '100.25',
            'kind': 'last_trade', 'observed_at': '2026-03-02T15:00:00Z',
            'session': 'regular', 'source_field': '/invented-trade/price'}}


def inputs(payload=None, body=None):
    if body is None:
        body = json.dumps(packet() if payload is None else payload).encode()
    receipt = {'byte_length': len(body), 'sha256': hashlib.sha256(body).hexdigest(),
        'source_url': URL, 'retrieved_at': '2026-03-02T15:00:10Z'}
    return {'body': body, 'receipt': receipt, 'expected_source_url': URL,
        'expected_security': deepcopy(SECURITY), 'analysis_as_of': '2026-03-02T15:01:00Z',
        'evaluated_at': '2026-03-02T15:02:00Z',
        'freshness_policy': {'policy_id': 'synthetic-test-only-not-approved', 'max_age_seconds': 60}}


def reject(args):
    result = audit_dated_price_capture(**args)
    assert result == {'contract_passed': False, 'admitted': False, 'launch_ready': False,
        'classification': 'offline_normalized_price_capture_audit',
        'reason': 'price_capture_contract_rejected', 'diagnostic_type': result['diagnostic_type']}
    return result


@pytest.mark.parametrize('kind', ['last_trade', 'official_close'])
def test_explicit_observation_passes_consistency_only_without_claiming_market_authority(kind):
    p = packet()
    p['observation']['kind'] = kind
    args = inputs(p)
    before = deepcopy(args)
    result = audit_dated_price_capture(**args)
    assert result['contract_passed'] and result['analysis_relative_age_seconds'] == 60
    assert result['observation']['value'] == '100.25'
    for flag in ('admitted', 'launch_ready', 'independently_adjudicated', 'market_session_verified',
                 'security_mapping_verified', 'eps_compatibility_verified'):
        assert result[flag] is False
    assert 'reference_id' not in result and 'values' not in result and 'verified_claims' not in result
    assert args == before
    result['security']['symbol'] = 'MUTATED'
    result['receipt']['sha256'] = 'MUTATED'
    assert args == before


@pytest.mark.parametrize('key,value', [
    ('symbol', 'OTHER'), ('issuer_cik', '0009999999'), ('listing_mic', 'XNYS'),
    ('security_id', 'synthetic-common-B'), ('share_class', 'Class B'),
    ('split_basis', 'different basis'), ('currency', 'EUR'), ('price_unit', 'EUR/share'),
    ('instrument_type', 'ADR'), ('symbol', 'zqxb'), ('issuer_cik', '1234567'),
    ('issuer_cik', '0000000000'), ('listing_mic', 'NASDAQ'), ('share_class', ''),
    ('security_id', {}), ('split_basis', ' unknown '), ('symbol', 'A/B'),
])
def test_security_mismatch_or_unsupported_binding_refused(key, value):
    p = packet()
    p['security'][key] = value
    reject(inputs(p))


@pytest.mark.parametrize('value', ['0', '-1', 'NaN', 'Infinity', '1e2', '01', '', True, 100.25, {}, None, '1' * 67])
def test_price_requires_positive_bounded_decimal_string(value):
    p = packet()
    p['observation']['value'] = value
    reject(inputs(p))


@pytest.mark.parametrize('key,value', [('kind', 'bid'), ('kind', 'ask'), ('kind', 'profile'),
    ('kind', []), ('session', 'after_hours'), ('session', None), ('source_field', ''),
    ('source_field', {'price': '100'}), ('observed_at', '2026-03-02'),
    ('observed_at', '2026-03-02T15:00:00'), ('observed_at', '2026-03-02T10:00:00-05:00'),
    ('observed_at', '2026-02-30T15:00:00Z'), ('observed_at', '2026-03-02T15:00:00.1Z'),
    ('observed_at', '2026-03-02T15:00:60Z')])
def test_observation_semantics_never_inferred_from_profile_or_retrieval(key, value):
    p = packet()
    p['observation'][key] = value
    reject(inputs(p))


@pytest.mark.parametrize('mutation', [
    lambda a: a['receipt'].update(sha256='0' * 64),
    lambda a: a['receipt'].update(byte_length=True),
    lambda a: a['receipt'].update(byte_length=a['receipt']['byte_length'] + 1),
    lambda a: a['receipt'].update(source_url='https://other.example.invalid/quote'),
    lambda a: a['receipt'].update(extra='not accepted'),
    lambda a: a['receipt'].pop('retrieved_at'),
    lambda a: a.update(body=a['body'] + b' '),
    lambda a: a.update(expected_security={}),
    lambda a: a.update(expected_security=None),
    lambda a: a.update(expected_source_url='https://other.example.invalid/quote'),
    lambda a: a['freshness_policy'].update(max_age_seconds=59),
    lambda a: a['freshness_policy'].update(max_age_seconds=True),
    lambda a: a['freshness_policy'].update(max_age_seconds=-1),
    lambda a: a['freshness_policy'].update(max_age_seconds=604801),
    lambda a: a['freshness_policy'].update(policy_id=''),
    lambda a: a['freshness_policy'].pop('policy_id'),
    lambda a: a.update(freshness_policy=None),
    lambda a: a['receipt'].update(retrieved_at='2026-03-02T14:59:59Z'),
    lambda a: a['receipt'].update(retrieved_at='2026-03-02T15:02:01Z'),
    lambda a: a.update(analysis_as_of='2026-03-02T14:59:59Z'),
    lambda a: a.update(analysis_as_of='2026-03-02T15:02:01Z'),
    lambda a: a.update(evaluated_at='2099-01-01T00:00:00Z'),
    lambda a: a.update(evaluated_at=None),
])
def test_receipt_freshness_and_chronology_fail_closed(mutation):
    args = inputs()
    mutation(args)
    reject(args)


@pytest.mark.parametrize('url', ['http://prices.example.invalid/quote',
    'https://user:secret@prices.example.invalid/quote', 'https://prices.example.invalid/quote?apikey=SECRET',
    'https://prices.example.invalid/quote#SECRET', 'https://127.0.0.1/quote',
    'https://[::1]/quote', 'https://localhost/quote', 'https://prices.internal/quote',
    'https://prices.example.invalid:443/quote', 'https://prices.example.invalid/%73ecret',
    'https://prices.example.invalid/a b', 'https://prices.example.invalid/\\SECRET'])
def test_uninspectable_or_credential_bearing_reference_is_not_echoed(url):
    p = packet()
    p['source_url'] = url
    args = inputs(p)
    args.update(expected_source_url=url)
    args['receipt']['source_url'] = url
    result = reject(args)
    assert 'SECRET' not in json.dumps(result) and url not in json.dumps(result)


@pytest.mark.parametrize('body', [b'', b'[]', b'null', b'{}', b'\xff', b'{',
    b'{"schema":"x","schema":"dated-price-capture-v1"}',
    b'{"x":NaN}', b'{"x":Infinity}', b'{"x":1}', b'{"x":1.5}',
    b'{"x":' + b'1' * 5000 + b'}', b'[' * 2000 + b']' * 2000])
def test_malformed_duplicate_or_unbounded_parser_shapes_return_sanitized_gap(body):
    reject(inputs(body=body))


def test_exact_byte_bound_and_one_byte_over_including_whitespace():
    body = inputs()['body']
    bounded = body + b' ' * (MAX_CAPTURE_BYTES - len(body))
    assert audit_dated_price_capture(**inputs(body=bounded))['contract_passed']
    reject(inputs(body=bounded + b' '))
    reject(inputs(body=bytearray(body)))


def test_unknown_or_missing_fields_and_nested_duplicate_cannot_grant_implicit_defaults():
    for section in (None, 'security', 'observation'):
        p = packet()
        target = p if section is None else p[section]
        key = next(iter(target))
        del target[key]
        reject(inputs(p))
        p = packet()
        (p if section is None else p[section])['extra'] = 'unreviewed'
        reject(inputs(p))
    body = inputs()['body'].replace(b'"value": "100.25"', b'"value": "1", "value": "100.25"')
    reject(inputs(body=body))


def test_historical_as_of_and_retrieval_before_analysis_are_explicit_not_current_claims():
    args = inputs()
    args['evaluated_at'] = '2026-04-01T00:00:00Z'
    result = audit_dated_price_capture(**args)
    assert result['contract_passed']
    assert 'not a statement that this observation is current today' in ' '.join(result['limitations'])
    args['analysis_as_of'] = '2026-03-02T15:00:00Z'
    args['freshness_policy']['max_age_seconds'] = 0
    assert audit_dated_price_capture(**args)['contract_passed']


def test_receipt_can_be_recomputed_for_fabricated_input_so_audit_is_never_authentication():
    p = packet()
    p['observation']['value'] = '999999'
    result = audit_dated_price_capture(**inputs(p))
    assert result['contract_passed'] and not result['independently_adjudicated']
    assert not result['admitted'] and not result['security_mapping_verified']


def test_successful_audit_cannot_replace_explicit_hypothetical_price_in_existing_eps_bridge():
    from test_source_anchored_valuation import admitted, assumptions, run
    args = inputs()
    audited = audit_dated_price_capture(**args)
    payload = assumptions()
    payload['price'] = {'value': audited['observation']['value'], 'unit': 'USD/share',
        'provenance': {'kind': 'source_observation', 'reference': URL, 'observation_date': '2026-03-02'}}
    items, refs = admitted()
    result = run(payload, items, refs)
    assert not result['available'] and 'values' not in result
