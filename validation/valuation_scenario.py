"""Offline conditional EPS/PE algebra; no market retrieval or production wiring."""
from __future__ import annotations

from decimal import Decimal, DecimalException, localcontext, ROUND_HALF_EVEN, Context, InvalidOperation, DivisionByZero, Overflow
import json
from datetime import date
from fractions import Fraction
import re


class ValuationContractError(ValueError):
    """The explicit scenario cannot be evaluated without inventing inputs."""


def _object(value, keys, label):
    if not isinstance(value, dict) or set(value) != set(keys):
        raise ValuationContractError(f'{label}: expected exactly {sorted(keys)}')


def _text(value, label):
    if not isinstance(value, str) or not value.strip() or len(value) > 1000:
        raise ValuationContractError(f'{label}: requires nonempty text of at most 1000 characters')


def _provenance(value):
    if not isinstance(value, dict):
        raise ValuationContractError('provenance must be an object')
    keys = {'kind', 'reference'}
    if value.get('kind') == 'source_observation':
        keys.add('observation_date')
    _object(value, keys, 'provenance')
    if value['kind'] not in ('user_assumption', 'source_observation'):
        raise ValuationContractError('provenance kind must identify an assumption or source observation')
    _text(value['reference'], 'provenance reference')
    if value['kind'] == 'source_observation':
        observed = value['observation_date']
        try:
            if not isinstance(observed, str) or date.fromisoformat(observed).isoformat() != observed:
                raise ValueError
        except ValueError as exc:
            raise ValuationContractError('source observation_date requires an ISO calendar date') from exc


def _number(value):
    if not isinstance(value, str) or len(value) > 66 or not re.fullmatch(r'-?(?:0|[1-9]\d*)(?:\.\d+)?', value):
        raise ValuationContractError('numeric values require decimal strings, at most 66 characters; no exponent notation')
    return Decimal(value)


def _operand(value, *, unit, basis=False):
    _object(value, {'value', 'unit', 'provenance'} | ({'eps_basis'} if basis else set()), 'operand')
    if value['unit'] != unit:
        raise ValuationContractError(f'operand unit must be {unit}')
    _provenance(value['provenance'])
    return _number(value['value'])


def _basis(value):
    _object(value, {'issuer', 'currency', 'accounting', 'adjustment_definition',
                   'share_basis', 'period_basis', 'split_basis', 'earnings_scope'}, 'EPS basis')
    for key in ('issuer', 'split_basis'):
        _text(value[key], key)
    if not isinstance(value['currency'], str) or not re.fullmatch('[A-Z]{3}', value['currency']):
        raise ValuationContractError('currency must be an explicit three-letter code')
    if value['accounting'] not in ('gaap', 'adjusted'):
        raise ValuationContractError('accounting must be gaap or adjusted')
    if value['accounting'] == 'adjusted':
        _text(value['adjustment_definition'], 'adjustment definition')
    elif value['adjustment_definition'] != 'none':
        raise ValuationContractError('GAAP adjustment_definition must be none')
    if value['earnings_scope'] not in ('total_operations', 'continuing_operations'):
        raise ValuationContractError('earnings_scope must be total_operations or continuing_operations')
    if value['share_basis'] not in ('basic', 'diluted'):
        raise ValuationContractError('share_basis must be basic or diluted')
    if value['period_basis'] not in ('trailing_12_months', 'forward_12_months'):
        raise ValuationContractError('period_basis must specify trailing or forward 12 months')


def _evaluate_scenario(payload):
    """Evaluate explicit price-only assumptions, not expected/total returns.

    EPS cancels in P_N/P_0 = (exit_PE/entry_PE) * (1+EPS_growth)^N.
    Precision and resource bounds are computational limits, not market policy.
    """
    if not isinstance(payload, dict):
        raise ValuationContractError('scenario must be an object')
    mode = payload.get('mode')
    if mode not in ('solve_required_earnings_growth', 'evaluate_growth_scenario'):
        raise ValuationContractError('explicit supported mode required')
    rate_key = 'annual_price_return_rate' if mode == 'solve_required_earnings_growth' else 'eps_growth_rate'
    _object(payload, {'mode', 'distributions', 'entry_pe', 'exit_pe', 'horizon', rate_key}, 'scenario')
    if payload['distributions'] != 'excluded':
        raise ValuationContractError('only explicitly excluded dividends/distributions are supported')
    entry = _operand(payload['entry_pe'], unit='x', basis=True)
    terminal = _operand(payload['exit_pe'], unit='x', basis=True)
    for key in ('entry_pe', 'exit_pe'):
        _basis(payload[key]['eps_basis'])
    if payload['entry_pe']['eps_basis'] != payload['exit_pe']['eps_basis']:
        raise ValuationContractError('entry and exit EPS bases must match exactly')
    if entry <= 0 or terminal <= 0:
        raise ValuationContractError('positive P/E values required for this positive-EPS ratio contract')
    horizon = payload['horizon']
    _object(horizon, {'value', 'unit', 'provenance'}, 'horizon')
    _provenance(horizon['provenance'])
    years = horizon['value']
    if type(years) is not int or not 1 <= years <= 1000 or horizon['unit'] != 'years':
        raise ValuationContractError('horizon requires integer years from 1 through 1000 (computational bound)')
    rate = _operand(payload[rate_key], unit='annual_fraction')
    if rate <= -1:
        raise ValuationContractError('annual rate must exceed -1 for positive multiplicative factors')
    try:
        with localcontext(Context(prec=50, rounding=ROUND_HALF_EVEN, Emin=-999999,
                                  Emax=999999, capitals=1, clamp=0,
                                  traps=[InvalidOperation, DivisionByZero, Overflow])) as ctx:
            one = Decimal(1)
            n = Decimal(years)
            if rate != 0 and one + rate == one:
                raise ValuationContractError('rate is too small to preserve at 50-digit precision')
            multiple_ratio = entry / terminal if mode == 'solve_required_earnings_growth' else terminal / entry
            if entry != terminal and multiple_ratio == one:
                raise ValuationContractError('multiple change was lost at 50-digit precision')
            if mode == 'solve_required_earnings_growth':
                multiple_root = multiple_ratio ** (one / n)
                if multiple_ratio != one and multiple_root == one:
                    raise ValuationContractError('multiple root change was lost at 50-digit precision')
                growth = (one + rate) * multiple_root - one
                # Recognize only an exact algebraic zero; never use a tolerance
                # to turn a small nonzero growth requirement into zero.
                if (Fraction(1) + Fraction(rate)) ** years * Fraction(entry) == Fraction(terminal):
                    growth = Decimal(0)
                price_factor = (one + rate) ** years
                annual_price = rate
                formula = 'EPS_growth = (1 + annual_price_return) * (entry_PE / exit_PE)^(1 / years) - 1'
            else:
                growth = rate
                price_factor = multiple_ratio * (one + growth) ** years
                annual_price = price_factor ** (one / n) - one
                formula = 'price_factor = (exit_PE / entry_PE) * (1 + EPS_growth)^years; annual_price_change = price_factor^(1 / years) - 1'
            if growth <= -one or annual_price <= -one or price_factor <= 0:
                raise ValuationContractError('rounding lost a positive factor at 50-digit precision')
            if price_factor != one and annual_price == 0:
                raise ValuationContractError('annual price change was lost at 50-digit precision')
            cumulative_change = price_factor - one
            if cumulative_change <= -one:
                raise ValuationContractError('cumulative price change lost a positive terminal factor at 50-digit precision')
            values = {'eps_growth_rate': growth, 'terminal_price_factor': price_factor,
                      'cumulative_price_change': cumulative_change,
                      'annualized_price_change': annual_price}
            if not all(value.is_finite() for value in values.values()):
                raise ValuationContractError('calculation exceeded finite arithmetic bounds')
            rendered = {key: str(value) for key, value in values.items()}
    except DecimalException as exc:
        raise ValuationContractError('calculation exceeded Decimal arithmetic bounds') from exc
    return {'available': True, 'classification': 'conditional_price_only_scenario', 'mode': mode,
            'distributions': 'excluded', 'formula': formula, 'values': rendered,
            'numeric_contract': {'precision_digits': 50, 'rounding': 'ROUND_HALF_EVEN',
                                 'annual_rates': 'annual_fraction',
                                 'cumulative_price_change': 'total_horizon_fraction',
                                 'price_factor': 'dimensionless'},
            'inputs': payload,
            'limitations': ['Not an expected return, total return, forecast or recommendation.',
                            'EPS growth is per-share growth, not aggregate earnings or revenue growth.',
                            'Dividends and other distributions are excluded.',
                            'Input provenance and compatible bases are caller assertions, not independently verified.',
                            'Decimal rounding applies; no acceptance tolerance or investment score is assigned.']}


def evaluate_scenario(payload):
    """Return explicit unavailability rather than inventing incomplete inputs."""
    try:
        return _evaluate_scenario(payload)
    except ValuationContractError as exc:
        return {'available': False, 'reason': str(exc),
                'classification': 'conditional_price_only_scenario',
                'distributions': 'excluded',
                'limitations': ['No calculation supplied; not an expected return or recommendation.']}


def load_scenario(text):
    """Reject duplicate keys and nonstandard numeric constants at every depth."""
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValuationContractError('duplicate JSON key')
            result[key] = value
        return result
    def invalid_constant(value):
        raise ValuationContractError('nonfinite JSON constant is not allowed')
    def integer(value):
        if len(value.lstrip('-')) > 4:
            raise ValuationContractError('JSON integer exceeds supported horizon representation')
        return int(value)
    def floating(value):
        raise ValuationContractError('JSON floating-point tokens are unsupported; use explicit decimal strings')
    try:
        return json.loads(text, object_pairs_hook=unique, parse_constant=invalid_constant,
                          parse_int=integer, parse_float=floating)
    except ValuationContractError:
        raise
    except (ValueError, RecursionError) as exc:
        raise ValuationContractError('invalid scenario JSON') from exc
