"""Rebuilt financial monitoring benchmarks, never bull/bear price targets."""
from .financial_thesis_foundation import build_financial_foundation


def build_decision_monitoring(ticker, items, references, *, expected_cik=None):
    # The existing producer rechecks identity, raw facts, periods, currencies,
    # filing versions, summary and citation bindings. Model annotations cannot
    # authorize a monitoring benchmark.
    if not references:
        return None
    foundation = build_financial_foundation(ticker, items, references,
                                            expected_cik=expected_cik)
    if not foundation:
        return None
    calculations = [row for row in foundation['inferences']
                    if row['kind'] == 'operating_margin_calculation']
    if not calculations:
        return None
    benchmarks = []
    for row in calculations:
        benchmarks.append({
            'kind': 'reported_period_monitoring_benchmark',
            'metric': 'operating margin',
            'benchmark_percent': row['current']['margin_percent'],
            'period_start': row['current']['period_start'],
            'period_end': row['current']['period_end'],
            'formula': row['formula'],
            'inputs': row['current'],
            'reference_ids': row['reference_ids'],
            'condition': 'Review a future comparable margin below this reported-period benchmark.',
            'limitation': 'This is a monitoring benchmark, not a buy/sell boundary, forecast or materiality threshold.',
        })
    answer = 'Evidence-backed financial monitoring (partial)\n\n'
    answer += '\n\n'.join(row['text'] + ' ' + ' '.join(
        f'[{ref}]' for ref in row['reference_ids']) for row in calculations)
    answer += ('\n\nReview a future comparable margin below the cited current margin. '
               'Use the same consolidated scope, currency and reporting duration. '
               'This benchmark does not determine whether the stock is attractive or '
               'unattractive. Valuation boundaries, expected returns, operating KPI '
               'breakpoints and quantified earnings impacts remain unverified.')
    return {'answer': answer, 'benchmarks': benchmarks,
            'calculations': calculations, 'foundation': foundation}
