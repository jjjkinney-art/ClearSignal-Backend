"""A within-issuer profitability calculation, not proof of competitive advantage."""
from decimal import Decimal, DecimalException, localcontext


def operating_margin_assessment(metrics, references):
    """Use only core comparisons already reconstructed and selected by the foundation.

    Cross-metric alignment is stricter than independent trend admission: both
    years must share exact periods, units and filing versions. Never infer a
    denominator, resolve conflicting concepts, or invent answer citations.
    """
    if references is None or not {'revenue', 'operating income'} <= metrics.keys():
        return None
    revenue, revenue_ref = metrics['revenue']
    income, income_ref = metrics['operating income']
    if revenue_ref == income_ref:
        return None
    for item, identifier in ((revenue, revenue_ref), (income, income_ref)):
        if (item.availability_status != 'available'
                or item.freshness_status in {'stale', 'conflicting', 'superseded', 'unavailable'}):
            return None
        matches = [ref for ref in references if ref.get('id') == identifier]
        if len(matches) != 1:
            return None
        ref = matches[0]
        if (ref.get('title') != item.title.strip()[:300]
                or ref.get('source') != item.source.strip()[:120]
                or ref.get('url') != item.url or ref.get('published_at') != item.timestamp
                or ref.get('freshness_status') in {'stale', 'conflicting', 'superseded', 'unavailable'}):
            return None
    periods = []
    try:
        with localcontext() as context:
            context.prec = 40
            for sales, profit in zip(revenue.verified_claims, income.verified_claims):
                if (sales['metric'] not in {'us-gaap:Revenues',
                        'us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax'}
                        or profit['metric'] != 'us-gaap:OperatingIncomeLoss'
                        or any(sales[key] != profit[key] for key in (
                            'ticker', 'scope', 'unit', 'currency', 'period_start', 'period_end', 'source'))
                        or any(sales['document_ref'].get(key) != profit['document_ref'].get(key)
                               for key in ('url', 'published_at', 'content_hash'))):
                    return None
                denominator = Decimal(str(sales['raw_value']))
                numerator = Decimal(str(profit['raw_value']))
                if not denominator.is_finite() or denominator <= 0 or not numerator.is_finite():
                    return None
                margin = numerator / denominator * 100
                periods.append({
                    'period_start': sales['period_start'], 'period_end': sales['period_end'],
                    'currency': sales['currency'], 'margin_percent': str(margin),
                    'revenue': {'raw_value': str(denominator), 'reference_id': revenue_ref,
                                'document_ref': dict(sales['document_ref'])},
                    'operating_income': {'raw_value': str(numerator), 'reference_id': income_ref,
                                         'document_ref': dict(profit['document_ref'])},
                })
            if len(periods) != 2:
                return None
            current, prior = periods
            current_margin = Decimal(current['margin_percent'])
            prior_margin = Decimal(prior['margin_percent'])
            change = current_margin - prior_margin
            direction = 'widened' if change > 0 else 'narrowed' if change < 0 else 'unchanged'
            magnitude = (f'{abs(change):.2f} percentage points' if abs(change) >= Decimal('0.01')
                         else 'less than 0.01 percentage points')
            movement = f'{direction} by {magnitude}' if change else 'was unchanged'
            text = (
                f'Calculated operating margin {movement}: {current_margin:.2f}% for '
                f'{current["period_start"]} to {current["period_end"]}, versus {prior_margin:.2f}% '
                f'for {prior["period_start"]} to {prior["period_end"]}. '
                'Formula: operating income / revenue × 100, using the cited consolidated '
                'reported amounts in each period; displayed margins are rounded to two decimals. '
                'This is within-issuer profitability evidence, not a peer comparison or proof '
                'of pricing power, market share or durable competitive advantage. '
                'The drivers of the margin change remain unverified.'
            )
            if current_margin <= 0:
                text += ' The current operating margin is non-positive; any narrowing of losses is not positive operating profitability.'
            return {
                'kind': 'operating_margin_calculation', 'provenance': 'derived',
                'metric': 'operating margin', 'signal': 'context_only',
                'formula': 'operating_income / revenue * 100',
                'change_formula': 'current_margin_percent - prior_margin_percent',
                'change_unit': 'percentage_points', 'change_percentage_points': str(change),
                'direction': direction, 'current': current, 'prior': prior,
                'reference_ids': [revenue_ref, income_ref], 'text': text,
                'conditional_test': 'The cited margin is a historical baseline, not an investment threshold. '
                    'A lower margin for the corresponding period one year later would weaken the profitability '
                    'assumption. Review pricing, costs and product mix, and comparable peer evidence, before '
                    'drawing a competitive-strength conclusion; this is not a forecast.',
            }
    except (KeyError, TypeError, ValueError, DecimalException):
        return None
