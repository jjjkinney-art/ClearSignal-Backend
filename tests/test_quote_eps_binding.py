"""Invented profile/quote bytes plus reconstructed invented SEC EPS pairs."""
from copy import deepcopy
import hashlib
import json

import pytest

from test_fmp_quote_capture import args as quote_args
from test_source_anchored_valuation import admitted, eps_item
from validation.dated_price import MAX_CAPTURE_BYTES
from validation.quote_eps_binding import assess_quote_eps_binding, PROFILE_ENDPOINT


def profile():
    return {'symbol': 'ZQXB', 'cik': '0001234567', 'currency': 'USD',
        'exchange': 'NASDAQ', 'isin': 'US0000000010',
        'isAdr': False, 'isEtf': False, 'isFund': False, 'isActivelyTrading': True}


def inputs(payload=None, *, body=None):
    quote = quote_args()
    body = json.dumps([profile()] if payload is None else payload).encode() if body is None else body
    items, refs = admitted()
    return {'quote_body': quote['body'], 'quote_receipt': quote['receipt'],
        'profile_body': body, 'profile_receipt': {'sha256': hashlib.sha256(body).hexdigest(),
            'byte_length': len(body), 'endpoint': PROFILE_ENDPOINT, 'requested_symbol': 'ZQXB',
            'retrieved_at': '2026-03-02T14:59:00Z', 'status_code': 200, 'content_type': 'application/json'},
        'items': items, 'references': refs, 'expected_symbol': 'ZQXB', 'expected_cik': '0001234567',
        'analysis_as_of': quote['analysis_as_of'], 'evaluated_at': quote['evaluated_at'],
        'quote_freshness_policy': quote['freshness_policy'],
        'profile_retrieval_policy': {'policy_id': 'synthetic-not-approved', 'max_age_seconds': 120}}


def reject(a, stage=None):
    r = assess_quote_eps_binding(**a)
    assert not r['binding_passed'] and not r['admitted'] and not r['launch_ready']
    assert r['reason'] == 'quote_profile_eps_binding_rejected'
    assert 'quote' not in r and 'source_eps' not in r and 'values' not in r
    if stage:
        assert r['stage'] == stage
    return r


def test_binds_raw_profile_currency_cik_and_exchange_to_reconstructed_eps_without_computing_pe():
    a = inputs()
    before_profile = a['profile_body'], deepcopy(a['profile_receipt'])
    r = assess_quote_eps_binding(**a)
    assert r['binding_passed'] and r['status'] == 'partial'
    assert all(r['checks'].values())
    assert r['source_eps']['value'] == '5'
    assert r['source_eps']['period_basis'] == 'fiscal_year'
    assert r['source_eps']['reference_id'] == a['references'][0]['id']
    assert r['profile']['provider_cik'] == '0001234567'
    assert r['profile']['provider_currency'] == 'USD'
    assert r['profile']['provider_isin'] == 'US0000000010'
    assert r['profile']['source_observation_time'] is None
    assert r['profile']['retrieval_age_seconds'] == 120
    assert r['profile']['raw_binding']['fields']['currency'] == '/0/currency'
    assert r['profile']['raw_binding']['sha256'] == hashlib.sha256(a['profile_body']).hexdigest()
    assert r['quote']['candidate']['currency'] is None  # provenance stays separate
    for flag in ('admitted', 'launch_ready', 'security_mapping_verified', 'eps_compatibility_verified',
                 'market_pe_verified', 'independently_adjudicated'):
        assert r[flag] is False
    assert 'values' not in r and 'entry_pe_derivation' not in r
    r['profile']['raw_binding']['sha256'] = 'mutated'
    assert (a['profile_body'], a['profile_receipt']) == before_profile


@pytest.mark.parametrize('key,value', [('symbol', 'OTHER'), ('symbol', 'zqxb'), ('cik', '0009999999'),
    ('cik', 1234567), ('cik', '1234567'), ('currency', 'EUR'), ('currency', None),
    ('exchange', None), ('exchange', {}), ('exchange', ' NASDAQ'), ('exchange', 'XNYS'),
    ('isin', ''), ('isin', None), ('isin', 'US-SYNTHETIC'), ('isin', {'id': 'US0000000010'})])
def test_provider_mapping_mismatch_is_not_a_fallback_or_currency_conversion(key, value):
    p = profile()
    p[key] = value
    reject(inputs([p]), 'quote_profile_exchange' if key == 'exchange' and value == 'XNYS' else 'profile_capture')


@pytest.mark.parametrize('key', ['isAdr', 'isEtf', 'isFund'])
@pytest.mark.parametrize('value', [True, 'false', 0, None])
def test_non_adr_fund_flags_must_be_explicit_booleans(key, value):
    p = profile()
    p[key] = value
    reject(inputs([p]), 'profile_capture')


@pytest.mark.parametrize('value', [False, 'true', 1, None])
def test_active_trading_flag_is_not_inferred(value):
    p = profile()
    p['isActivelyTrading'] = value
    reject(inputs([p]), 'profile_capture')


@pytest.mark.parametrize('key', list(profile()))
def test_required_profile_field_cannot_be_missing(key):
    p = profile()
    del p[key]
    reject(inputs([p]), 'profile_capture')


@pytest.mark.parametrize('mutation,stage', [
    (lambda a: a.update(expected_cik='1234567'), 'expected_issuer'),
    (lambda a: a.update(expected_cik='0000000000'), 'expected_issuer'),
    (lambda a: a.update(expected_cik=[]), 'expected_issuer'),
    (lambda a: a.update(expected_symbol='OTHER'), 'quote_capture'),
    (lambda a: a['quote_receipt'].update(sha256='0' * 64), 'quote_capture'),
    (lambda a: a['profile_receipt'].update(sha256='0' * 64), 'profile_capture'),
    (lambda a: a['profile_receipt'].update(byte_length=True), 'profile_capture'),
    (lambda a: a['profile_receipt'].update(status_code=True), 'profile_capture'),
    (lambda a: a['profile_receipt'].update(status_code=403), 'profile_capture'),
    (lambda a: a['profile_receipt'].update(content_type='text/html'), 'profile_capture'),
    (lambda a: a['profile_receipt'].update(endpoint=PROFILE_ENDPOINT+'?apikey=SYNTHETIC_CANARY'), 'profile_capture'),
    (lambda a: a['profile_receipt'].update(requested_symbol='OTHER'), 'profile_capture'),
    (lambda a: a['profile_receipt'].update(extra='unreviewed'), 'profile_capture'),
    (lambda a: a['profile_receipt'].update(retrieved_at='2026-03-02T15:01:01Z'), 'profile_capture'),
    (lambda a: a['profile_receipt'].update(retrieved_at='2026-03-02'), 'profile_capture'),
    (lambda a: a['profile_retrieval_policy'].update(max_age_seconds=119), 'profile_capture'),
    (lambda a: a['profile_retrieval_policy'].update(max_age_seconds=True), 'profile_capture'),
    (lambda a: a['profile_retrieval_policy'].update(max_age_seconds=-1), 'profile_capture'),
    (lambda a: a['profile_retrieval_policy'].update(max_age_seconds=604801), 'profile_capture'),
    (lambda a: a['profile_retrieval_policy'].update(policy_id=''), 'profile_capture'),
    (lambda a: a.update(profile_retrieval_policy={}), 'profile_capture'),
    (lambda a: a.update(references=[]), 'sec_eps'),
    (lambda a: a['references'][0].update(id='invented'), 'sec_eps'),
    (lambda a: a['items'][0].verified_claims[0].update(raw_value=999), 'sec_eps'),
    (lambda a: a['items'][0].verified_claims[0].update(currency='EUR'), 'sec_eps'),
    (lambda a: a['items'][0].verified_claims[0].update(ticker='OTHER'), 'sec_eps'),
    (lambda a: setattr(a['items'][0], 'freshness_status', 'stale'), 'sec_eps'),
])
def test_bad_receipts_policies_and_eps_return_sanitized_failure_without_partial_admission(mutation, stage):
    a = inputs()
    mutation(a)
    r = reject(a, stage)
    assert 'SYNTHETIC_CANARY' not in json.dumps(r)


@pytest.mark.parametrize('body', [b'', b'\xff', b'null', b'{}', b'[]', b'[null]', b'[{',
    b'[{"cik":"0009999999","cik":"0001234567"}]', b'[' * 2000 + b']' * 2000,
    b'[{"unused":NaN}]', b'[{"unused":' + b'1' * 5000 + b'}]'])
def test_malformed_profile_shapes_never_leak_or_authorize(body):
    reject(inputs(body=body), 'profile_capture')


def test_exact_profile_body_limit_then_overflow_and_ambiguous_records():
    body = inputs()['profile_body']
    at_bound = body + b' ' * (MAX_CAPTURE_BYTES-len(body))
    assert assess_quote_eps_binding(**inputs(body=at_bound))['binding_passed']
    reject(inputs(body=at_bound+b' '), 'profile_capture')
    reject(inputs([profile(), profile()]), 'profile_capture')


@pytest.mark.parametrize('current,annual', [(0, True), (-1, True), (5, False)])
def test_nonpositive_or_quarterly_eps_never_changes_into_annual_pe(current, annual):
    a = inputs()
    a['items'], a['references'] = admitted([eps_item(current, annual=annual)])
    reject(a, 'sec_eps')


def test_references_must_preserve_exact_final_response_id_and_period():
    a = inputs()
    a['references'][0]['id'] = 'E29'
    r = assess_quote_eps_binding(**a)
    assert r['binding_passed'] and r['source_eps']['reference_id'] == 'E29'
    a['references'][0]['reporting_period_end'] = '2024-12-31'
    reject(a, 'sec_eps')


def test_extra_profile_price_ipo_and_security_hints_do_not_fill_unsupported_gaps():
    p = profile()
    p.update(price=999, ipoDate='1980-01-01', split_basis='unchanged',
        share_class='common', mic='XNAS', secret='SYNTHETIC_CANARY')
    r = assess_quote_eps_binding(**inputs([p]))
    assert r['binding_passed'] and r['quote']['candidate']['price_value'] == '100.25'
    assert not r['eps_compatibility_verified'] and not r['security_mapping_verified']
    assert 'SYNTHETIC_CANARY' not in json.dumps(r)
    assert r['profile']['source_observation_time'] is None


def test_recomputed_fabricated_receipts_can_pass_consistency_but_not_authentication_or_valuation():
    p = profile()
    p['isin'] = 'US1111111111'
    r = assess_quote_eps_binding(**inputs([p]))
    assert r['binding_passed'] and not r['independently_adjudicated']
    assert not r['eps_compatibility_verified'] and 'values' not in r


def test_new_profile_currency_does_not_mutate_quote_candidate_or_existing_source_price_gate():
    from test_source_anchored_valuation import assumptions, run
    r = assess_quote_eps_binding(**inputs())
    p = assumptions()
    p['price']['value'] = r['quote']['candidate']['price_value']
    p['price']['provenance'] = {'kind': 'source_observation', 'reference': 'Provider candidate',
        'observation_date': '2026-03-02'}
    assert not run(p)['available']
    assert r['quote']['candidate']['price_unit'] is None
