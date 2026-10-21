"""Use successful real evaluator outputs, never treat a formatted fixture as admission."""
from copy import deepcopy
from decimal import Decimal, localcontext

import pytest

from app.services.conditional_scenario_explanation import explain_validated_scenario, _percent
from test_source_anchored_valuation import assumptions, run
from test_earnings_recovery_scenario import run as recovery
from test_conditional_valuation_api import enabled, post, payload, records
from app.services import conditional_valuation_service as svc


@pytest.mark.parametrize('mode', ['evaluate_growth_scenario', 'solve_required_earnings_growth'])
def test_explanation_uses_evaluated_values_keeps_gaps_and_does_not_change_evidence(mode):
    result = run(assumptions(mode))
    before = deepcopy(result)
    answer = explain_validated_scenario(result)
    assert answer['status'] == 'partial'
    assert answer['unanswered_parts'] == result['unanswered_parts']
    fact = answer['reported_facts'][0]
    assert fact['reference_ids'] == [result['source_eps']['reference_id']]
    assert '2025-01-01 to 2025-12-31' in fact['text']
    assert '5 USD/share' in fact['text']
    assert '[' not in answer['direct_answer']  # no historical citation laundering
    for key in ('annualized_price_change', 'cumulative_price_change'):
        displayed = answer['conditional_results'][key].removeprefix('approximately ').removesuffix('%')
        with localcontext() as context:
            context.prec = 100
            assert abs(Decimal(displayed) / 100 - Decimal(result['values'][key])) <= Decimal('0.00005')
    assert result == before
    assert 'do not establish expected total returns' in answer['direct_answer']
    assert 'buy/sell threshold' in answer['direct_answer']
    assert 'Historical fiscal EPS is not current TTM or forward EPS' in answer['direct_answer']


def test_known_growth_example_explains_fifty_percent_price_change_without_calling_it_a_forecast():
    answer = explain_validated_scenario(run())
    assert 'annualized price change of 50%' in answer['direct_answer']
    assert 'annual per-share EPS growth of 0%' in answer['direct_answer']
    assert answer['conditional_results']['cumulative_price_change'] == '125%'
    assert 'Future earnings and the exit multiple remain assumptions' in answer['direct_answer']


def test_required_growth_is_a_mathematical_condition_not_expected_growth():
    a = assumptions('solve_required_earnings_growth')
    a['price']['value'] = '225'
    a['exit_pe']['value'] = '20'
    a['annual_price_return_rate']['value'] = '0.1'
    answer = explain_validated_scenario(run(a))
    assert 'EPS growth of 65%' in answer['direct_answer']
    assert 'assumed 10% annual price-change target' in answer['direct_answer']
    assert 'does not assess whether that growth is achievable' in answer['direct_answer']


@pytest.mark.parametrize('current', [-2, 0, -10000])
def test_recovery_does_not_use_loss_magnitude_as_growth_denominator(current):
    result = recovery(current=current)
    answer = explain_validated_scenario(result)
    assert 'terminal price of 100 USD/share' in answer['direct_answer']
    assert 'annualized price change of 25%' in answer['direct_answer']
    assert 'historical context only; it is not a growth denominator' in answer['direct_answer']
    assert 'Recovery probability is unassessed' in answer['direct_answer']
    assert '2027-01-01 to 2027-12-31' in ' '.join(answer['explicit_assumptions'])
    assert f'{current} USD/share' in answer['reported_facts'][0]['text']


@pytest.mark.parametrize('fraction,expected', [
    ('0', '0%'), ('1', '100%'), ('0.001', '0.1%'),
    ('-0.25', '-25%'), ('0.1000', '10%'),
    ('0.1234567890123456789012345678901234567890123456789',
     'approximately 12.35%'),
    ('0.00001', 'approximately 0%'), ('-0.00001', 'approximately 0%'),
    ('0.12345', 'approximately 12.34%'),
])
def test_fraction_display_declares_rounding_without_float_or_sign_artifact(fraction, expected):
    assert _percent(fraction) == expected


def test_provenance_free_text_is_not_promoted_into_answer_or_citation():
    a = assumptions()
    for key in ('price', 'exit_pe', 'horizon', 'eps_growth_rate'):
        a[key]['provenance']['reference'] = 'CANARY BUY NOW [E999]'
    result = run(a)
    assert result['available']
    assert 'CANARY' not in str(explain_validated_scenario(result))
    assert 'E999' not in str(explain_validated_scenario(result))


def test_rejected_result_cannot_be_formatted_as_a_scenario():
    with pytest.raises(ValueError):
        explain_validated_scenario(run(assumptions(), items=[], refs=[]))


@pytest.mark.parametrize('mode', ['evaluate_growth_scenario', 'solve_required_earnings_growth', 'recovery'])
def test_guarded_endpoint_includes_explanation_only_after_successful_evaluation(enabled, monkeypatch, mode):
    if mode == 'recovery':
        monkeypatch.setattr(svc, 'get_company_fact_records_for_concept_units', lambda *a, **kw: records(-2))
    p = payload(loss=mode == 'recovery')
    if mode == 'solve_required_earnings_growth':
        p['assumptions'] = assumptions(mode)
    response = post(p)
    assert response.status_code == 200
    body = response.json()
    assert body['available'] and body['status'] == 'partial'
    assert body['explanation'] == explain_validated_scenario(body['scenario'])
    ids = {r['id'] for r in body['evidence_references']}
    assert set(body['explanation']['reported_facts'][0]['reference_ids']) <= ids
    assert body['admitted'] is False and body['launch_ready'] is False
    assert response.headers['cache-control'] == 'no-store'


def test_missing_source_never_receives_explanation(enabled, monkeypatch):
    monkeypatch.setattr(svc, 'get_company_fact_records_for_concept_units', lambda *a, **kw: [])
    body = post(payload()).json()
    assert not body['available'] and 'explanation' not in body


@pytest.mark.parametrize('basis', ['basic', 'diluted'])
@pytest.mark.parametrize('mode', ['evaluate_growth_scenario', 'solve_required_earnings_growth', 'evaluate_earnings_recovery_scenario'])
def test_eur_basis_and_currency_survive_explanation(basis, mode):
    from test_eur_annual_eps_scenarios import run as euro
    result = euro(mode=mode, share_basis=basis)
    answer = explain_validated_scenario(result)
    assert f'annual {basis} EPS' in answer['reported_facts'][0]['text']
    assert 'EUR/share' in answer['reported_facts'][0]['text']
    assert 'EUR/share' in answer['direct_answer']
    assert 'USD' not in str(answer) and '$' not in str(answer)


def test_negative_growth_and_negative_price_change_remain_signed_conditions():
    a = assumptions()
    a['eps_growth_rate']['value'] = '-0.2'
    a['exit_pe']['value'] = '20'
    answer = explain_validated_scenario(run(a))
    assert 'EPS growth of -20%' in answer['direct_answer']
    assert 'annualized price change of -20%' in answer['direct_answer']
