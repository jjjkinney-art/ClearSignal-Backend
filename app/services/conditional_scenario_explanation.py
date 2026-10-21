"""Presentation of an internally validated scenario; no admission or valuation policy.

Call only with the successful result of the source-anchored scenario evaluators.
The evaluator remains responsible for identity, sources, assumptions and arithmetic.
No free-text provenance or caller-provided narrative is interpolated here.
"""
from decimal import Decimal, localcontext, ROUND_HALF_EVEN

from app.services.earnings_recovery_scenario import MODE as RECOVERY_MODE


def _percent(value):
    # Human display only. Exact evaluated fractions remain in scenario.values.
    with localcontext() as context:
        context.prec = max(100, len(value) + 4)
        exact = Decimal(value) * 100
        rounded = exact.quantize(Decimal('0.01'), rounding=ROUND_HALF_EVEN)
        rendered = format(rounded, 'f')
        if '.' in rendered:
            rendered = rendered.rstrip('0').rstrip('.')
        if rounded == 0:
            rendered = '0'
        return ('approximately ' if exact != rounded else '') + rendered + '%'


def explain_validated_scenario(result):
    """Build a research explanation after successful producer validation only."""
    if result.get('available') is not True:
        raise ValueError('successful validated scenario required')
    assumptions = result['supplied_assumptions']
    mode = result['mode']
    if mode not in {'evaluate_growth_scenario', 'solve_required_earnings_growth', RECOVERY_MODE}:
        raise ValueError('supported validated scenario mode required')
    eps = result['source_eps']
    currency = eps['currency']
    basis = eps['share_basis']
    years = str(assumptions['horizon']['value'])
    price = assumptions['price']['value']
    multiple = assumptions['exit_pe']['value']
    values = result['values']
    reported = (
        f"Reported annual {basis} EPS was {eps['value']} {currency}/share for "
        f"{eps['period_start']} to {eps['period_end']} (filed {eps['filed_at']}). "
        f"[{eps['reference_id']}]"
    )
    supplied = [
        f'Hypothetical starting price: {price} {currency}/underlying common share.',
        f'Assumed exit P/E: {multiple}x; horizon: {years} years.',
        'Currency, earnings scope and share/split compatibility are user assertions; no FX or ADR conversion is performed.',
    ]
    annual_change = _percent(values['annualized_price_change'])
    if mode == 'solve_required_earnings_growth':
        target = _percent(assumptions['annual_price_return_rate']['value'])
        required = _percent(values['eps_growth_rate'])
        supplied.append(f'Assumed annual price-change target: {target}.')
        direct = (
            f'At the hypothetical starting price of {price} {currency}/share and exit P/E of '
            f'{multiple}x over {years} years, annual per-share EPS growth of {required} '
            f'is mathematically required for the assumed {target} annual price-change target. '
            'This calculation does not assess whether that growth is achievable.'
        )
    elif mode == RECOVERY_MODE:
        target_eps = assumptions['target_eps']['value']
        period = assumptions['target_fiscal_period']
        supplied.append(
            f"Assumed future annual {basis} EPS: {target_eps} {currency}/share for "
            f"{period['start']} to {period['end']}."
        )
        direct = (
            f'Assumed future EPS of {target_eps} {currency}/share and exit P/E of {multiple}x '
            f"imply a hypothetical terminal price of {values['assumed_terminal_price']} {currency}/share "
            f'and annualized price change of {annual_change} from the hypothetical starting price '
            f'of {price} {currency}/share over {years} years. '
            'Reported nonpositive EPS is historical context only; it is not a growth denominator. '
            'Recovery probability is unassessed.'
        )
    else:
        growth = _percent(assumptions['eps_growth_rate']['value'])
        supplied.append(f'Assumed annual per-share EPS growth: {growth}.')
        direct = (
            f'Using reported annual EPS as the starting earnings amount, the hypothetical starting '
            f'price of {price} {currency}/share, annual per-share EPS growth of {growth} and exit '
            f'P/E of {multiple}x over {years} years imply annualized price change of {annual_change}. '
            'Future earnings and the exit multiple remain assumptions.'
        )
    limits = (
        'Price changes exclude distributions and do not establish expected total returns, '
        'a buy/sell threshold or investment attractiveness. The citation supports historical EPS '
        'only; it does not verify the assumed price, future earnings or exit multiple. '
        'Historical fiscal EPS is not current TTM or forward EPS.'
    )
    return {
        'status': 'partial',
        'classification': 'conditional_scenario_explanation',
        'direct_answer': direct + ' ' + limits,
        'reported_facts': [{'text': reported, 'reference_ids': [eps['reference_id']]}],
        'explicit_assumptions': supplied,
        'conditional_results': {
            'annualized_price_change': annual_change,
            'cumulative_price_change': _percent(values['cumulative_price_change']),
            'terminal_price_factor': values['terminal_price_factor'],
        },
        'percentage_display': {
            'decimal_places': 2, 'rounding': 'ROUND_HALF_EVEN',
            'inexact_prefix': 'approximately ', 'exact_fraction_values': 'scenario.values',
        },
        'unanswered_parts': list(result['unanswered_parts']),
    }
