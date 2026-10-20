"""Loss-context price sensitivity with invented explicit recovery assumptions."""
from copy import deepcopy
from decimal import Decimal, localcontext
from fractions import Fraction

import pytest

from test_source_anchored_valuation import admitted, eps_item, assumptions as old_assumptions, run as old_run
from test_quote_eps_binding import inputs as quote_inputs
from validation.quote_eps_binding import assess_quote_eps_binding
from validation.earnings_recovery_scenario import evaluate_earnings_recovery, MODE


def assumptions():
    a = old_assumptions()
    a['mode'] = MODE
    del a['eps_growth_rate']
    a['price']['value'] = '64'
    a['exit_pe']['value'] = '25'
    a['target_eps'] = {'value': '4', 'unit': 'USD/shares',
        'provenance': {'kind': 'user_assumption', 'reference': 'Invented positive future EPS, not a forecast'}}
    a['target_fiscal_period'] = {'start': '2027-01-01', 'end': '2027-12-31'}
    return a


def run(a=None, current=-2, items=None, refs=None):
    if items is None:
        items, refs = admitted([eps_item(current=current)])
    return evaluate_earnings_recovery('ZQXB', items, refs, expected_cik='1234567',
        assumptions=assumptions() if a is None else a, evaluated_at='2026-03-03')


def rejected(a=None, current=-2, items=None, refs=None):
    r = run(a, current, items, refs)
    assert not r['available'] and not r['admitted'] and not r['launch_ready']
    assert 'values' not in r and 'source_eps' not in r and 'supplied_assumptions' not in r
    assert 'CANARY' not in str(r)
    return r


@pytest.mark.parametrize('current', [-2, 0, -100])
def test_loss_or_zero_is_context_only_and_terminal_algebra_is_independently_reproducible(current):
    a = assumptions(); before = deepcopy(a)
    r = run(a, current)
    assert r['available'] and r['status'] == 'partial'
    assert r['source_eps']['value'] == str(current)
    assert r['source_eps_role'] == 'reported_nonpositive_fiscal_context_only'
    assert not r['source_eps_used_in_scenario_arithmetic']
    assert r['terminal_valuation_date'] == '2028-03-02'
    assert Decimal(r['values']['assumed_terminal_price']) == 4 * 25 == 100
    assert Decimal(r['values']['terminal_price_factor']) == Decimal('1.5625')
    assert Decimal(r['values']['annualized_price_change']) == Decimal('0.25')
    assert Fraction(100,64) == Fraction(5,4)**2
    assert Decimal(r['values']['cumulative_price_change']) == Decimal('0.5625')
    assert a == before and not r['admitted'] and not r['launch_ready']
    assert not r['market_pe_verified'] and not r['earnings_recovery_probability_assessed']
    assert not {'entry_pe_derivation', 'current_pe', 'eps_growth_rate', 'adjusted_eps'} & r.keys()
    assert 'eps_growth_rate' not in r['values']


def test_historical_loss_size_does_not_change_scenario_arithmetic():
    assert run(current=-1)['values'] == run(current=-10000)['values']


@pytest.mark.parametrize('key,unit', [('price','USD/share'),('target_eps','USD/shares'),('exit_pe','x')])
@pytest.mark.parametrize('value', ['0', '-1', 'NaN', 'Infinity', '1e2', True, 4.0, ''])
def test_nonpositive_nonfinite_or_untyped_scenario_numbers_are_not_silently_repaired(key,unit,value):
    a = assumptions(); a[key]['value'] = value
    rejected(a)


@pytest.mark.parametrize('key', ['price','target_eps','exit_pe','horizon'])
def test_live_or_asserted_source_operands_are_not_accepted_as_hypothetical_inputs(key):
    a = assumptions(); a[key]['provenance'] = {'kind':'source_observation', 'reference':'CANARY', 'observation_date':'2026-03-02'}
    rejected(a)


@pytest.mark.parametrize('mutation', [
    lambda a:a.update(distributions='included'), lambda a:a.update(mode='evaluate_growth_scenario'),
    lambda a:a.update(price_per_underlying_common_share=False),
    lambda a:a['eps_basis'].update(issuer='OTHER'), lambda a:a['eps_basis'].update(currency='EUR'),
    lambda a:a['eps_basis'].update(share_basis='basic'), lambda a:a['eps_basis'].update(period_basis='trailing_12_months'),
    lambda a:a['eps_basis'].update(accounting='adjusted', adjustment_definition='invented loss normalization'),
    lambda a:a['eps_basis'].update(earnings_scope='continuing_operations'),
    lambda a:a['target_eps'].update(unit='USD'), lambda a:a['price'].update(unit='EUR/share'),
    lambda a:a['horizon'].update(value=True), lambda a:a['horizon'].update(value=0),
    lambda a:a['horizon'].update(value=1001), lambda a:a['horizon'].update(unit='months'),
    lambda a:a.update(scenario_as_of='2099-01-01'), lambda a:a.update(scenario_as_of='2026-02-19'),
    lambda a:a.update(extra='CANARY'), lambda a:a['target_fiscal_period'].update(extra='CANARY'),
    lambda a:a['target_fiscal_period'].update(start='2026-01-01'),
    lambda a:a['target_fiscal_period'].update(end='2028-12-31'),
    lambda a:a['target_fiscal_period'].update(start='2027-04-01',end='2027-06-30'),
    lambda a:a['target_fiscal_period'].update(start='2026-03-03',end='2027-01-01'),
    lambda a:a['target_fiscal_period'].update(start='2027-13-01'),
])
def test_wrong_basis_timing_schema_or_units_remain_explicit_gaps(mutation):
    a=assumptions();mutation(a);rejected(a)


def test_positive_historical_eps_uses_existing_route_not_recovery_context():
    rejected(current=5)
    assert old_run()['available']


@pytest.mark.parametrize('current', [-2, 0])
def test_existing_positive_pe_and_quote_binding_guards_remain_unchanged(current):
    items,refs = admitted([eps_item(current=current)])
    assert not old_run(old_assumptions(),items,refs)['available']
    a = quote_inputs();a['items'],a['references']=items,refs
    q = assess_quote_eps_binding(**a)
    assert not q['binding_passed'] and q['stage']=='sec_eps'


@pytest.mark.parametrize('mutation', [
    lambda items,refs:items[0].verified_claims[0].update(raw_value=-999),
    lambda items,refs:refs[0].update(id='unbound'),
    lambda items,refs:refs[0].update(reporting_period_end='2024-12-31'),
    lambda items,refs:setattr(items[0],'availability_status','unavailable'),
    lambda items,refs:setattr(items[0],'freshness_status','stale'),
])
def test_signed_eps_context_still_requires_reconstructed_source_and_exact_admitted_reference(mutation):
    items,refs = admitted([eps_item(current=-2)]);mutation(items,refs)
    rejected(items=items,refs=refs)


def test_quarterly_eps_is_not_annualized_into_recovery_context():
    items,refs=admitted([eps_item(-2,annual=False)])
    rejected(items=items,refs=refs)


def test_ambient_precision_and_returned_object_mutation_do_not_change_operands():
    a=assumptions()
    with localcontext() as c:
        c.prec=2
        r=run(a)
    assert Decimal(r['values']['annualized_price_change']) == Decimal('0.25')
    r['supplied_assumptions']['target_eps']['value']='999'
    assert a['target_eps']['value']=='4' and run(a)['values']==r['values']


def test_tiny_price_change_that_rounds_away_fails_instead_of_returning_zero():
    a=assumptions();a['price']['value']='1'
    a['target_eps']['value']='1.'+'0'*59+'1'
    a['exit_pe']['value']='1'
    rejected(a)


def test_extreme_positive_ratio_cannot_round_to_negative_one_change():
    a=assumptions();a['price']['value']='9'*60
    a['target_eps']['value']='0.'+'0'*59+'1'
    a['exit_pe']['value']='1'
    rejected(a)


def test_flat_and_negative_conditional_price_changes_are_retained_without_recommendation():
    a=assumptions();a['price']['value']='100'
    r=run(a);assert r['available'] and Decimal(r['values']['annualized_price_change'])==0
    a['price']['value']='400'
    r=run(a);assert r['available'] and Decimal(r['values']['annualized_price_change'])==Decimal('-0.5')
