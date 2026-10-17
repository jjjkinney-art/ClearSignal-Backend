"""Invented split data and explicit hypothetical basis dates; never live feeds."""
from copy import deepcopy
from datetime import date, timedelta
from decimal import localcontext
from fractions import Fraction
import hashlib
import json

import pytest

from validation.dated_price import MAX_CAPTURE_BYTES
from validation.split_event_reconciliation import ENDPOINT, reconcile_listed_splits, MAX_FACTOR_EVENTS


def event(day='2026-02-25', numerator=4, denominator=1):
    return {'symbol': 'ZQXB', 'date': day, 'numerator': numerator,
        'denominator': denominator, 'splitType': 'stock-split'}


def args(rows=None, *, body=None):
    body = json.dumps([event()] if rows is None else rows).encode() if body is None else body
    return {'body': body, 'receipt': {'sha256': hashlib.sha256(body).hexdigest(),
        'byte_length': len(body), 'endpoint': ENDPOINT, 'requested_symbol': 'ZQXB',
        'requested_limit': 1000, 'retrieved_at': '2026-03-02T15:00:00Z',
        'status_code': 200, 'content_type': 'application/json'}, 'expected_symbol': 'ZQXB',
        'basis_assumption': {'already_adjusted_through': '2026-02-20', 'comparison_date': '2026-03-02',
            'provenance': {'kind': 'user_assumption', 'reference': 'Explicit invented basis for algebra only'}},
        'evaluated_at': '2026-03-02T15:01:00Z',
        'retrieval_age_policy': {'policy_id': 'synthetic-not-approved', 'max_age_seconds': 60}}


def frac(value):
    return Fraction(int(value['numerator']), int(value['denominator']))


def reject(a):
    r = reconcile_listed_splits(**a)
    assert r == {'mapped': False, 'status': 'insufficient_corporate_action_evidence',
        'admitted': False, 'launch_ready': False, 'classification': 'offline_listed_split_reconciliation',
        'reason': 'listed_split_reconciliation_rejected', 'diagnostic_type': r['diagnostic_type']}
    return r


@pytest.mark.parametrize('numerator,denominator', [(4, 1), (1, 10), (3, 2), (10, 4), (1, 1)])
def test_new_old_ratio_and_eps_inverse_are_exact_conditional_factors_only(numerator, denominator):
    a = args([event(numerator=numerator, denominator=denominator)])
    before = deepcopy(a)
    r = reconcile_listed_splits(**a)
    assert r['mapped'] and r['status'] == 'partial'
    assert frac(r['listed_event_share_factor']) == Fraction(numerator, denominator)
    assert frac(r['conditional_eps_multiplier']) == Fraction(denominator, numerator)
    assert frac(r['listed_event_share_factor']) * frac(r['conditional_eps_multiplier']) == 1
    assert 'eps_value' not in r and 'values' not in r and 'market_pe' not in r
    for flag in ('admitted', 'launch_ready', 'event_interval_completeness_verified', 'split_compatibility_verified',
        'eps_basis_verified', 'security_mapping_verified', 'observation_reference_inspectable', 'independently_adjudicated'):
        assert r[flag] is False
    assert r['events'][0]['fields']['numerator'] == '/0/numerator'
    assert a == before
    r['basis_assumption']['provenance']['reference'] = 'mutated'
    r['raw_binding']['sha256'] = 'mutated'
    assert a == before


def test_multiple_events_compose_as_rational_without_reapplying_in_basis_events():
    a = args([event('2026-02-27', 1, 2), event('2026-01-15', 10, 1), event('2026-02-25', 4, 1)])
    r = reconcile_listed_splits(**a)
    assert r['mapped'] and frac(r['listed_event_share_factor']) == Fraction(2)
    assert frac(r['conditional_eps_multiplier']) == Fraction(1, 2)
    assert r['applied_event_dates'] == ['2026-02-25', '2026-02-27']
    assert r['events'][0]['role'] == 'already_in_assumed_basis'
    assert r['events'][1]['fields']['date'] == '/2/date'  # sorted, original raw pointers
    with localcontext() as context:
        context.prec = 3
        assert reconcile_listed_splits(**a) == r


@pytest.mark.parametrize('rows', [[], [event('2026-01-15')], [event('2026-02-20')], [event('2026-04-01')]])
def test_empty_prebasis_or_future_only_lists_never_establish_identity_factor(rows):
    r = reconcile_listed_splits(**args(rows))
    assert r['mapped'] and r['status'] == 'insufficient_corporate_action_evidence'
    assert 'listed_event_share_factor' not in r and 'conditional_eps_multiplier' not in r
    assert not r['event_interval_completeness_verified'] and not r['split_compatibility_verified']


def test_cutoff_is_explicit_not_derived_from_eps_period_end_or_filing_date():
    rows = [event('2026-02-15', 4, 1), event('2026-02-25', 3, 2)]
    a = args(rows)
    r = reconcile_listed_splits(**a)
    assert frac(r['listed_event_share_factor']) == Fraction(3, 2)
    a['basis_assumption']['already_adjusted_through'] = '2026-01-01'
    r = reconcile_listed_splits(**a)
    assert frac(r['listed_event_share_factor']) == Fraction(6)
    assert not r['eps_basis_verified']
    del a['basis_assumption']['already_adjusted_through']
    reject(a)


def test_comparison_day_event_blocks_factor_without_intraday_or_session_assumptions():
    r = reconcile_listed_splits(**args([event(), event('2026-03-02', 2, 1)]))
    assert r['mapped'] and r['factor_status'] == 'comparison_day_requires_effective_time'
    assert 'listed_event_share_factor' not in r and 'conditional_eps_multiplier' not in r


@pytest.mark.parametrize('rows', [[event(), event()], [event(), event(numerator=3)]])
def test_same_date_duplicate_or_conflicting_rows_are_not_double_counted(rows):
    reject(args(rows))


@pytest.mark.parametrize('key,value', [('numerator', 0), ('denominator', 0), ('numerator', -1),
    ('denominator', -2), ('numerator', True), ('denominator', None), ('numerator', '4'),
    ('numerator', 4.0), ('denominator', {}), ('numerator', 1000001), ('denominator', float('nan')),
    ('splitType', 'stock-dividend'), ('splitType', 'reverse-split'), ('splitType', None),
    ('symbol', 'OTHER'), ('symbol', 'zqxb'), ('date', '2026-02-30'), ('date', '2026-2-25')])
def test_bad_ratio_identity_type_or_date_is_not_repaired(key, value):
    row = event()
    row[key] = value
    reject(args([row]))


@pytest.mark.parametrize('mutation', [
    lambda a: a['receipt'].update(sha256='0'*64),
    lambda a: a['receipt'].update(byte_length=True),
    lambda a: a['receipt'].update(status_code=True),
    lambda a: a['receipt'].update(status_code=403),
    lambda a: a['receipt'].update(content_type='text/html'),
    lambda a: a['receipt'].update(endpoint=ENDPOINT+'?apikey=CANARY'),
    lambda a: a['receipt'].update(endpoint=ENDPOINT+'-calendar'),
    lambda a: a['receipt'].update(requested_symbol='OTHER'),
    lambda a: a['receipt'].update(requested_limit=True),
    lambda a: a['receipt'].update(requested_limit=0),
    lambda a: a['receipt'].update(requested_limit=1001),
    lambda a: a['receipt'].update(complete_coverage=True),
    lambda a: a.update(expected_symbol=[]),
    lambda a: a.update(body=a['body']+b' '),
    lambda a: a['receipt'].update(retrieved_at='2026-03-02T15:01:01Z'),
    lambda a: a['basis_assumption'].update(already_adjusted_through='2026-03-03'),
    lambda a: a['basis_assumption'].update(comparison_date='2099-01-01'),
    lambda a: a['basis_assumption'].update(eps_period_end='2025-12-31'),
    lambda a: a['basis_assumption']['provenance'].update(kind='source_observation'),
    lambda a: a['basis_assumption']['provenance'].update(reference=''),
    lambda a: a['retrieval_age_policy'].update(max_age_seconds=59),
    lambda a: a['retrieval_age_policy'].update(max_age_seconds=True),
    lambda a: a['retrieval_age_policy'].update(max_age_seconds=-1),
    lambda a: a['retrieval_age_policy'].update(max_age_seconds=604801),
    lambda a: a['retrieval_age_policy'].update(policy_id=''),
    lambda a: a.update(evaluated_at='2099-01-01T00:00:00Z'),
    lambda a: a.update(evaluated_at=None),
])
def test_receipt_calendar_and_missing_explicit_basis_contract_failures_are_sanitized(mutation):
    a = args()
    mutation(a)
    assert 'CANARY' not in json.dumps(reject(a))


@pytest.mark.parametrize('body', [b'', b'\xff', b'{}', b'null', b'[{', b'[true]',
    b'[{"date":"2026-01-01","date":"2026-02-01"}]', b'['*2000+b']'*2000,
    b'[{"x":'+b'1'*5000+b'}]'])
def test_malformed_duplicate_and_resource_bound_inputs_return_fixed_gap(body):
    reject(args(body=body))


def test_body_limit_and_record_limit_saturation_are_not_completeness_proof():
    a = args()
    at_bound = a['body']+b' '*(MAX_CAPTURE_BYTES-len(a['body']))
    assert reconcile_listed_splits(**args(body=at_bound))['mapped']
    reject(args(body=at_bound+b' '))
    a['receipt']['requested_limit'] = 1
    r = reconcile_listed_splits(**a)
    assert r['mapped'] and r['requested_limit_reached']
    assert not r['event_interval_completeness_verified']
    a = args([event(), event('2026-02-26')])
    a['receipt']['requested_limit'] = 1
    reject(a)


def test_factor_event_bound_and_large_exact_products_are_computationally_bounded():
    dates = [(date(2020, 1, 1)+timedelta(days=i)).isoformat() for i in range(MAX_FACTOR_EVENTS+1)]
    a = args([event(day, 1000000, 1) for day in dates[:-1]])
    a['basis_assumption']['already_adjusted_through'] = '2019-12-31'
    r = reconcile_listed_splits(**a)
    assert r['mapped'] and frac(r['listed_event_share_factor']) == 1000000**MAX_FACTOR_EVENTS
    a = args([event(day) for day in dates])
    a['basis_assumption']['already_adjusted_through'] = '2019-12-31'
    reject(a)


def test_optional_coverage_share_class_and_intraday_hints_are_not_authority():
    row = event()
    row.update(complete=True, shareClass='Common', effectiveTime='00:00:00', secret='CANARY')
    r = reconcile_listed_splits(**args([row]))
    assert r['mapped'] and not r['event_interval_completeness_verified']
    assert 'CANARY' not in json.dumps(r) and 'shareClass' not in json.dumps(r)


def test_recomputed_fabrication_does_not_become_origin_or_eps_compatibility_proof():
    r = reconcile_listed_splits(**args([event(numerator=999)]))
    assert r['mapped'] and not r['independently_adjudicated']
    assert not r['eps_basis_verified'] and not r['split_compatibility_verified']


def test_split_report_cannot_be_injected_into_existing_share_basis_gate():
    from test_filing_share_class import args as filing_args
    from test_quote_eps_binding import inputs
    from validation.share_basis_binding import assess_filed_share_basis
    current = inputs()
    current['split_report'] = reconcile_listed_splits(**args())
    filing = filing_args()
    r = assess_filed_share_basis(current, filing['body'], filing['receipt'], form=filing['form'],
        filed_at=filing['filed_at'], reporting_period_end=filing['reporting_period_end'])
    assert not r['binding_passed'] and r['stage'] == 'input_contract'
