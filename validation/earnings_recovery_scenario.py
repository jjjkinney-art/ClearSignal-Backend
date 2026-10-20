"""Offline loss-context scenario with explicit future EPS, never current P/E.

Historical nonpositive EPS is context only. No market observation, forecast,
loss normalization, percentage EPS recovery or production admission is supplied.
"""
from copy import deepcopy
from datetime import date
from decimal import Context, Decimal, DecimalException, localcontext, ROUND_HALF_EVEN
from decimal import InvalidOperation, DivisionByZero, Overflow
from fractions import Fraction

from validation.source_anchored_valuation import _annual_eps_context, _assumption, _calendar
from validation.valuation_scenario import ValuationContractError, _basis, _object, _operand, _provenance

CLASSIFICATION = 'source_anchored_conditional_earnings_recovery_scenario'
MODE = 'evaluate_earnings_recovery_scenario'


def evaluate_earnings_recovery(ticker, items, references, *, expected_cik,
                               assumptions, evaluated_at):
    """Scenario price = assumed positive future EPS × assumed exit multiple.

    No growth rate is calculated from the reported loss or zero EPS. The result
    is a price-only sensitivity to invented/explicit inputs, not expected return.
    """
    try:
        _object(assumptions, {'mode', 'scenario_as_of', 'price', 'price_per_underlying_common_share',
            'eps_basis', 'target_eps', 'target_fiscal_period', 'exit_pe', 'horizon', 'distributions'}, 'recovery assumptions')
        if assumptions['mode'] != MODE or assumptions['distributions'] != 'excluded':
            raise ValuationContractError('explicit recovery mode and excluded distributions required')
        scenario, evaluated = _calendar(assumptions['scenario_as_of']), _calendar(evaluated_at)
        if not scenario <= evaluated <= date.today():
            raise ValuationContractError('scenario/evaluation dates cannot be in the future')
        if assumptions['price_per_underlying_common_share'] is not True:
            raise ValuationContractError('explicit underlying common-share price assumption required')
        basis = assumptions['eps_basis']
        _basis(basis)
        if (basis['issuer'] != ticker or basis['currency'] != 'USD'
                or basis['accounting'] != 'gaap' or basis['share_basis'] != 'diluted'
                or basis['period_basis'] != 'fiscal_year' or basis['earnings_scope'] != 'total_operations'):
            raise ValuationContractError('same-issuer USD GAAP diluted full-year total-operations basis required')
        for key in ('price', 'target_eps', 'exit_pe', 'horizon'):
            _assumption(assumptions[key])
        price = _operand(assumptions['price'], unit='USD/share')
        target = _operand(assumptions['target_eps'], unit='USD/shares')
        multiple = _operand(assumptions['exit_pe'], unit='x')
        if price <= 0 or target <= 0 or multiple <= 0:
            raise ValuationContractError('positive hypothetical price, future EPS and exit P/E required')
        horizon = assumptions['horizon']
        _object(horizon, {'value', 'unit', 'provenance'}, 'horizon')
        _provenance(horizon['provenance'])
        years = horizon['value']
        if type(years) is not int or not 1 <= years <= 1000 or horizon['unit'] != 'years':
            raise ValuationContractError('horizon requires integer years 1 through 1000')
        try:
            terminal_date = scenario.replace(year=scenario.year + years)
        except ValueError as exc:
            raise ValuationContractError('unsupported terminal calendar anniversary') from exc
        period = assumptions['target_fiscal_period']
        _object(period, {'start', 'end'}, 'target fiscal period')
        start, end = _calendar(period['start']), _calendar(period['end'])
        if (not scenario < start <= end <= terminal_date
                or not 300 <= (end - start).days + 1 <= 380
                or (terminal_date - end).days > 380):
            raise ValuationContractError('explicit future full fiscal year ending by terminal date required')
        eps = _annual_eps_context(ticker, expected_cik, items, references, scenario)
        if Decimal(eps['value']) > 0:
            raise ValuationContractError('this recovery context requires reported nonpositive annual EPS')
        # Two <=66-character decimal operands have an exact finite product at 150 digits.
        with localcontext(Context(prec=150, Emin=-999999, Emax=999999,
                                  traps=[InvalidOperation, DivisionByZero, Overflow])):
            terminal_price = target * multiple
        if Fraction(terminal_price) != Fraction(target) * Fraction(multiple):
            raise ValuationContractError('terminal-price product lost precision')
        with localcontext(Context(prec=50, rounding=ROUND_HALF_EVEN, Emin=-999999, Emax=999999,
                                  traps=[InvalidOperation, DivisionByZero, Overflow])):
            factor = terminal_price / price
            if factor == 1 and Fraction(terminal_price) != Fraction(price):
                raise ValuationContractError('price change lost at 50-digit precision')
            cumulative = factor - 1
            annual = factor ** (Decimal(1) / Decimal(years)) - 1
            if (factor <= 0 or cumulative <= -1 or annual <= -1
                    or (factor != 1 and annual == 0)):
                raise ValuationContractError('positive price factor or change lost at 50-digit precision')
        values = {'assumed_terminal_price': format(terminal_price, 'f'),
            'terminal_price_factor': str(factor), 'cumulative_price_change': str(cumulative),
            'annualized_price_change': str(annual)}
        if not all(Decimal(value).is_finite() for value in values.values()):
            raise ValuationContractError('finite calculation bounds exceeded')
        return {'available': True, 'status': 'partial', 'classification': CLASSIFICATION,
            'mode': MODE, 'admitted': False, 'launch_ready': False,
            'source_eps': eps, 'source_eps_role': 'reported_nonpositive_fiscal_context_only',
            'source_eps_used_in_scenario_arithmetic': False,
            'supplied_assumptions': deepcopy(assumptions),
            'terminal_valuation_date': terminal_date.isoformat(), 'values': values,
            'formula': 'terminal_price = assumed_future_fiscal_EPS * assumed_exit_PE; price_factor = terminal_price / assumed_price; annualized_price_change = price_factor^(1 / years) - 1',
            'numeric_contract': {'terminal_price_unit': 'USD/share', 'price_factor': 'dimensionless',
                'change_units': 'fractions_not_percentages', 'precision_digits': 50,
                'terminal_product_exact': True, 'rounding': 'ROUND_HALF_EVEN'},
            'market_pe_verified': False, 'earnings_recovery_probability_assessed': False,
            'basis_verification': 'currency/share/split/earnings compatibility remains explicit user assumption',
            'unanswered_parts': ['observed market price and security/share/split compatibility',
                'source-supported future earnings and exit valuation',
                'recovery likelihood, expected total returns and investment attractiveness'],
            'limitations': ['Reported nonpositive EPS is retained as context, not divided into price or used as a growth denominator.',
                'Future positive EPS, entry price, exit P/E and horizon are explicit hypothetical user assumptions.',
                'No normalized/adjusted EPS, current P/E, EPS growth rate, recovery probability or forecast is established.',
                'The target fiscal year is explicitly dated; it is not reported, TTM or source-supported forward EPS.',
                'The 300–380-day annual duration and 380-day terminal lag are computational contract bounds, not market policy.',
                'Only conditional price change is calculated; distributions, dilution paths, funding needs and transaction costs are not modeled.',
                'Source reconstruction is consistency, not independent factual adjudication or application evidence admission.']}
    except (ValuationContractError, DecimalException) as exc:
        return {'available': False, 'status': 'insufficient_recovery_scenario_inputs',
            'classification': CLASSIFICATION, 'reason': str(exc), 'admitted': False, 'launch_ready': False,
            'limitations': ['No scenario calculation supplied; no forecast, current P/E or recommendation established.']}
