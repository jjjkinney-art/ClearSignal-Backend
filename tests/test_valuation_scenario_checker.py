"""Independent exact algebra and strict offline scenario contracts."""
from copy import deepcopy
from decimal import Decimal
from fractions import Fraction
import json
import socket

import pytest

from validation.valuation_scenario import evaluate_scenario, load_scenario, ValuationContractError
from scripts.check_valuation_scenario import main


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def blocked(*args, **kwargs):
        pytest.fail('Offline checker must not use network')
    monkeypatch.setattr(socket, 'getaddrinfo', blocked)
    monkeypatch.setattr(socket.socket, 'connect', blocked)


def scenario(mode='evaluate_growth_scenario'):
    provenance = {'kind': 'user_assumption', 'reference': 'Explicit scenario supplied for arithmetic review'}
    basis = {'issuer': 'TEST', 'currency': 'USD', 'accounting': 'gaap',
             'adjustment_definition': 'none', 'share_basis': 'diluted',
             'period_basis': 'trailing_12_months', 'split_basis': 'unchanged split-adjusted share basis'}
    def pe(value):
        return {'value': value, 'unit': 'x', 'eps_basis': deepcopy(basis), 'provenance': deepcopy(provenance)}
    result = {'mode': mode, 'distributions': 'excluded', 'entry_pe': pe('20'), 'exit_pe': pe('45'),
              'horizon': {'value': 2, 'unit': 'years', 'provenance': deepcopy(provenance)}}
    key = 'eps_growth_rate' if mode == 'evaluate_growth_scenario' else 'annual_price_return_rate'
    result[key] = {'value': '0', 'unit': 'annual_fraction', 'provenance': deepcopy(provenance)}
    return result


def test_exact_price_change_with_zero_eps_growth_and_ratio_cancellation():
    result = evaluate_scenario(scenario())
    assert result['available']
    values = {key: Decimal(value) for key, value in result['values'].items()}
    # Independently: prices 20 -> 45 with unchanged EPS; (3/2)^2 = 9/4.
    assert Fraction(45, 20) == Fraction(3, 2)**2
    assert values['terminal_price_factor'] == Decimal('2.25')
    assert values['annualized_price_change'] == Decimal('0.5')
    assert values['cumulative_price_change'] == Decimal('1.25')
    assert values['eps_growth_rate'] == 0
    assert 'not independently verified' in ' '.join(result['limitations'])


def test_exact_required_eps_growth_independent_fraction_identity():
    payload = scenario('solve_required_earnings_growth')
    payload['entry_pe']['value'], payload['exit_pe']['value'] = '45', '20'
    payload['annual_price_return_rate']['value'] = '0.1'
    result = evaluate_scenario(payload)
    # EPS grows 33/20 per year: (20/45)*(33/20)^2 = (11/10)^2.
    assert Fraction(20, 45) * Fraction(33, 20)**2 == Fraction(11, 10)**2
    assert result['available']
    assert Decimal(result['values']['eps_growth_rate']) == Decimal('0.65')
    assert Decimal(result['values']['terminal_price_factor']) == Decimal('1.21')
    assert Decimal(result['values']['annualized_price_change']) == Decimal('0.1')


@pytest.mark.parametrize('growth', ['0', '-0.2', '0.1'])
def test_unchanged_multiple_one_year_equals_explicit_eps_change(growth):
    payload = scenario()
    payload['exit_pe']['value'] = '20'
    payload['horizon']['value'] = 1
    payload['eps_growth_rate']['value'] = growth
    result = evaluate_scenario(payload)
    assert Decimal(result['values']['annualized_price_change']) == Decimal(growth)


@pytest.mark.parametrize('field', ['issuer', 'currency', 'accounting', 'adjustment_definition',
                                    'share_basis', 'period_basis', 'split_basis'])
def test_incompatible_bases_refused(field):
    payload = scenario()
    payload['exit_pe']['eps_basis'][field] = 'different'
    assert not evaluate_scenario(payload)['available']


@pytest.mark.parametrize('value', [True, False, 1, 1.2, None, {}, [], 'NaN', 'Infinity',
                                   '1e3', '1,000', '+1', ' 1', '1 ', '9'*67])
def test_numeric_ambiguity_refused(value):
    payload = scenario()
    payload['entry_pe']['value'] = value
    result = evaluate_scenario(payload)
    assert not result['available'] and result['reason']


@pytest.mark.parametrize('value', [True, 0, -1, 1.5, '2', 1001])
def test_horizon_is_explicit_supported_integer_years(value):
    payload = scenario()
    payload['horizon']['value'] = value
    assert not evaluate_scenario(payload)['available']


@pytest.mark.parametrize('key', ['entry_pe', 'exit_pe', 'horizon', 'eps_growth_rate'])
def test_missing_and_unexpected_fields_refused_at_each_operand(key):
    payload = scenario()
    del payload[key]['provenance']
    assert not evaluate_scenario(payload)['available']
    payload = scenario()
    payload[key]['dividend'] = '0.1'
    assert not evaluate_scenario(payload)['available']


def test_mode_exclusivity_distribution_and_domain_guards():
    payload = scenario()
    payload['annual_price_return_rate'] = deepcopy(payload['eps_growth_rate'])
    assert not evaluate_scenario(payload)['available']
    for key, value in [('distributions', 'included'), ('mode', 'auto')]:
        payload = scenario(); payload[key] = value
        assert not evaluate_scenario(payload)['available']
    for key, value in [('entry_pe', '0'), ('exit_pe', '-1'), ('eps_growth_rate', '-1')]:
        payload = scenario(); payload[key]['value'] = value
        assert not evaluate_scenario(payload)['available']


def test_provenance_dates_are_explicit_not_inferred_and_do_not_claim_verification():
    payload = scenario()
    provenance = {'kind': 'source_observation', 'reference': 'https://example.test/observation',
                  'observation_date': '2025-06-30'}
    payload['entry_pe']['provenance'] = provenance
    assert evaluate_scenario(payload)['available']
    del provenance['observation_date']
    assert not evaluate_scenario(payload)['available']
    provenance['observation_date'] = '2025-02-30'
    assert not evaluate_scenario(payload)['available']
    payload = scenario()
    payload['entry_pe']['provenance']['observation_date'] = '2025-06-30'
    assert not evaluate_scenario(payload)['available']


def test_adjusted_eps_requires_identical_explicit_definition():
    payload = scenario()
    for key in ('entry_pe', 'exit_pe'):
        payload[key]['eps_basis'].update(accounting='adjusted', adjustment_definition='excludes restructuring only')
    assert evaluate_scenario(payload)['available']
    payload['exit_pe']['eps_basis']['adjustment_definition'] = ''
    assert not evaluate_scenario(payload)['available']


@pytest.mark.parametrize('text', ['{"a":1,"a":2}', '{"nested":{"a":1,"a":2}}',
                                  '{"a":NaN}', '{"a":Infinity}', '{"a":-Infinity}', '{'])
def test_json_parser_rejects_duplicate_and_nonfinite_input(text):
    with pytest.raises(ValuationContractError):
        load_scenario(text)


def test_cli_success_and_unavailable_are_machine_readable(tmp_path, capsys):
    path = tmp_path / 'scenario.json'
    path.write_text(json.dumps(scenario()))
    assert main([str(path)]) == 0
    assert json.loads(capsys.readouterr().out)['available']
    path.write_text('{}')
    assert main([str(path)]) == 2
    result = json.loads(capsys.readouterr().out)
    assert not result['available'] and result['reason']
    path.write_text('{"mode":"a","mode":"b"}')
    with pytest.raises(SystemExit) as exc:
        main([str(path)])
    assert exc.value.code == 2


def test_ambient_decimal_context_cannot_change_result_or_cause_traps():
    from decimal import localcontext, ROUND_UP, Inexact
    payload = scenario()
    payload['horizon']['value'] = 3
    payload['exit_pe']['value'] = '40'
    expected = evaluate_scenario(payload)
    with localcontext() as context:
        context.prec = 3
        context.rounding = ROUND_UP
        context.Emax = 1
        context.Emin = -1
        context.traps[Inexact] = True
        assert evaluate_scenario(payload) == expected


def test_unrepresentable_rate_or_domain_is_unavailable_not_minus_one():
    payload = scenario()
    payload['eps_growth_rate']['value'] = '0.' + '0'*60 + '1'
    assert not evaluate_scenario(payload)['available']
    payload = scenario('solve_required_earnings_growth')
    payload['entry_pe']['value'] = '0.' + '0'*60 + '1'
    payload['exit_pe']['value'] = '9'*60
    payload['horizon']['value'] = 1
    assert not evaluate_scenario(payload)['available']


@pytest.mark.parametrize('text', ['{"horizon":' + '9'*4500 + '}', '{"value":1e9999}',
                                  '{"value":1.0}'])
def test_json_number_limits_are_controlled_contract_errors(text):
    with pytest.raises(ValuationContractError):
        load_scenario(text)


def test_invalid_utf8_and_oversize_file_have_controlled_cli_exit(tmp_path):
    path = tmp_path / 'bad.json'
    for content in [b'\xff', b' '*65537]:
        path.write_bytes(content)
        with pytest.raises(SystemExit) as exc:
            main([str(path)])
        assert exc.value.code == 2


@pytest.mark.parametrize('mode', ['evaluate_growth_scenario', 'solve_required_earnings_growth'])
def test_multiple_difference_cannot_round_to_identity(mode):
    payload = scenario(mode)
    payload['entry_pe']['value'] = '1'
    payload['exit_pe']['value'] = '1.' + '0'*60 + '1'
    payload['horizon']['value'] = 1
    assert not evaluate_scenario(payload)['available']


def test_genuine_offsetting_growth_and_multiple_compression_remain_valid():
    payload = scenario()
    payload['entry_pe']['value'], payload['exit_pe']['value'] = '25', '20'
    payload['eps_growth_rate']['value'] = '0.25'
    payload['horizon']['value'] = 1
    result = evaluate_scenario(payload)
    assert result['available']
    assert Decimal(result['values']['terminal_price_factor']) == 1
    assert Decimal(result['values']['annualized_price_change']) == 0
