"""Literal filing EPS must agree with reconstructed source EPS, not just accession."""
from copy import deepcopy
from decimal import localcontext
import hashlib

import pytest

from test_filing_share_class import args, body, combined, combined_body
from test_filing_eps_basis import document, fact, context_copy, UNIT
from test_quote_eps_binding import inputs
from test_source_anchored_valuation import admitted, eps_item


def check(raw=None, producer=None):
    return combined(args(combined_body() if raw is None else raw), inputs=producer)


def rejected(raw, stage, producer=None):
    r = check(raw, producer)
    assert r == {'binding_passed': False, 'status': 'insufficient_valuation_inputs',
        'admitted': False, 'launch_ready': False, 'classification': 'offline_filed_share_basis_consistency',
        'reason': 'filed_share_basis_rejected', 'stage': stage}
    return r


def test_matching_exact_value_and_period_retains_both_provenances_without_market_pe():
    r = check()
    assert r['binding_passed'] and r['filed_eps_value_consistent']
    match = r['filed_eps_crosscheck']
    assert match['value'] == '5' and match['unit'] == 'USD/shares'
    assert match['concept'] == 'us-gaap:EarningsPerShareDiluted'
    assert match['filing_fact_ids'] == ['filedEPS']
    assert match['filing_observations'][0]['literal'] == '5.00'
    assert match['period_start'] == '2025-01-01' and match['period_end'] == '2025-12-31'
    assert match['response_reference_id'] == r['quote_profile_eps']['source_eps']['reference_id']
    assert match['raw_binding']['body_sha256'] == hashlib.sha256(combined_body()).hexdigest()
    assert match['comparison'] == 'exact_decimal_value_and_calendar_period'
    for key in ('current_security_mapping_verified', 'split_compatibility_verified',
                'price_unit_verified', 'eps_class_compatibility_verified', 'market_pe_verified', 'admitted', 'launch_ready'):
        assert r[key] is False
    assert not match['independent_origin_or_accuracy_verification']
    assert 'values' not in r and 'entry_pe_derivation' not in r


@pytest.mark.parametrize('value', ['999', '5.000000000000001', '0', '4.99'])
def test_same_accession_date_and_class_cannot_hide_wrong_filed_amount(value):
    rejected(document(fact('Diluted', value)), 'filed_eps_value_or_period')


def test_basic_even_equal_to_diluted_and_heading_do_not_supply_required_concept():
    raw = document(fact('Basic', '5')).replace(b'</body>', b'<p>Earnings per share, basic and diluted</p></body>')
    rejected(raw, 'filed_diluted_eps_not_observed')
    rejected(body(), 'filed_diluted_eps_not_observed')


@pytest.mark.parametrize('raw', [
    document(fact('Diluted', '5'), unit=UNIT.replace('iso:USD', 'iso:EUR')),
    document(fact('Diluted', '5'), unit='<xbrli:unit id="u"><xbrli:measure>iso:USD</xbrli:measure></xbrli:unit>'),
    document(fact('Diluted', '5', attrs='continuedAt="other"')),
    document(fact('Diluted', '5', attrs='format="ixt:unknown"')),
    document(fact('Diluted', '5', attrs='sign="-"')),
])
def test_wrong_unit_or_unsupported_fact_cannot_clear_exact_crosscheck(raw):
    stage = 'filed_eps_value_or_period' if b'sign="-"' in raw else 'filed_diluted_eps_not_observed'
    rejected(raw, stage)


@pytest.mark.parametrize('start,end', [
    ('2025-01-02', '2025-12-31'), ('2024-01-01', '2024-12-31'),
    ('2025-04-01', '2025-06-30'), ('2026-01-01', '2026-12-31'),
])
def test_same_amount_wrong_period_or_quarterly_context_does_not_match(start, end):
    raw = context_copy(document(fact('Diluted', '5')), start=start, end=end)
    stage = 'filed_eps_value_or_period' if start == '2025-01-02' else 'filed_diluted_eps_not_observed'
    rejected(raw, stage)


def test_one_matching_fact_does_not_override_conflicting_current_facts():
    raw = document(fact('Diluted', '5')+fact('Diluted', '6', 'conflict'))
    rejected(raw, 'filed_diluted_eps_conflicting')


def test_equivalent_facts_preserve_ids_but_conflicting_basic_eps_does_not_relabel_diluted():
    raw = document(fact('Diluted', '5.00')+fact('Diluted', '5', 'duplicate')+fact('Basic', '6', 'basic'))
    r = check(raw)
    assert r['binding_passed']
    assert r['filed_eps_crosscheck']['filing_fact_ids'] == ['duplicate', 'eps']
    assert {row['concept'] for row in r['filed_eps_crosscheck']['filing_observations']} == {'EarningsPerShareDiluted'}


def test_transformed_scaled_literal_matches_by_exact_decimal_not_string_or_float():
    raw = document(fact('Diluted', '500', attrs='format="ixt:num-dot-decimal"')).replace(b'scale="0"', b'scale="-2"')
    assert check(raw)['binding_passed']
    raw = document(fact('Diluted', '5.00000000000000000000000000000000000001'))
    with localcontext() as ctx:
        ctx.prec = 2
        rejected(raw, 'filed_eps_value_or_period')
        assert check()['binding_passed']


def test_source_observation_and_final_reference_rebuilt_not_caller_overrides():
    a = inputs(); a['items'][0].verified_claims[0]['raw_value'] = 5.01
    rejected(combined_body(), 'quote_profile_eps', a)
    a = inputs(); a['references'][0]['reporting_period_start'] = '2025-01-02'
    rejected(combined_body(), 'quote_profile_eps', a)
    a = inputs(); a['filed_eps_value_consistent'] = True
    rejected(combined_body(), 'input_contract', a)


def test_another_accession_form_or_filing_date_does_not_match_before_numeric_check():
    a = args(combined_body())
    a['receipt']['url'] = a['receipt']['url'].replace('000123456726000001', '000123456726000002')
    assert combined(a)['stage'] == 'same_eps_filing'
    a = args(combined_body()); a['filed_at'] = '2026-02-21'
    assert combined(a)['stage'] == 'same_eps_filing'


def test_mutation_of_returned_crosscheck_cannot_change_source_inputs_or_future_result():
    a = args(combined_body()); producer = inputs()
    before = deepcopy(a); claims = deepcopy(producer['items'][0].verified_claims)
    r = combined(a, producer)
    r['filed_eps_crosscheck']['filing_observations'][0]['value'] = '999'
    r['filed_eps_crosscheck']['raw_binding']['body_sha256'] = '0'*64
    assert a == before and producer['items'][0].verified_claims == claims
    assert combined(a, producer)['filed_eps_crosscheck']['filing_observations'][0]['value'] == '5.00'


def test_policy_extraction_failure_does_not_become_implicit_eps_match():
    from test_filing_eps_basis import POLICY
    policies = ''.join(POLICY.replace('id="policy"', f'id="policy{i}"') for i in range(33))
    rejected(document(fact('Diluted', '5'), policy=policies), 'filed_eps_inspection')


def test_producer_prior_year_is_not_silently_claimed_crosschecked():
    r = check()
    assert 'prior comparison' in ' '.join(r['limitations'])
    assert all(row['end'] == '2025-12-31' for row in r['filed_eps_crosscheck']['filing_observations'])


@pytest.mark.parametrize('value,literal', [(5.1, '5.10'), (2.675, '2.675'), (0.001, '0.001')])
def test_fractional_reported_eps_matches_source_decimal_representation(value, literal):
    producer = inputs()
    producer['items'], producer['references'] = admitted([eps_item(current=value)])
    assert check(document(fact('Diluted', literal)), producer)['binding_passed']


def test_conflicting_annual_starts_are_not_resolved_by_one_matching_context():
    raw = document(fact('Diluted', '5'))
    raw = context_copy(raw, start='2025-01-02')
    raw = raw.replace(b'</body>', fact('Diluted', '5', 'original').encode()+b'</body>')
    rejected(raw, 'filed_diluted_eps_conflicting')


def test_fabricated_matching_pair_still_has_no_independent_origin_or_rights_proof():
    raw = document(fact('Diluted', '500'))
    producer = inputs(); producer['items'], producer['references'] = admitted([eps_item(current=500)])
    r = check(raw, producer)
    assert r['binding_passed'] and r['filed_eps_value_consistent']
    assert not r['filed_eps_crosscheck']['independent_origin_or_accuracy_verification']
    assert not r['eps_class_compatibility_verified'] and not r['market_pe_verified']
