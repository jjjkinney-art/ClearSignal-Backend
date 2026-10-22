"""Exact segment-table reconciliation and explicitly derived ratios.

The denominator is the reported table total, not a consolidated-company figure.
No tolerance, missing-segment allocation or rounding plug is used.
"""
from decimal import Decimal, localcontext, ROUND_HALF_UP

from ..providers.sec_segment_facts import total_amount


def _bound_total(proof, metric, rows, cik):
    try:
        row = proof['metrics'][metric]
        entry = row.get('total')
        if not isinstance(entry, dict):
            return None
        obs, column = entry['observation'], entry['column']
        cells = row['cells']
        if (entry['label'] != 'Total' or type(column) is not int or not 2 <= column < len(cells) - 1
                or proof['headers'][column] != 'Total' or cells[column]['fact_ids'] != [obs['fact_id']]
                or cells[column - 1]['text'] not in {'', '$'}
                or cells[column + 1]['text'] != (')' if obs['sign'] == '-' else '')
                or cells[column]['text'] != ('(' if obs['sign'] == '-' else '') + obs['literal']
                or obs['scale'] != 3 or obs['start'] != rows[0]['start'] or obs['end'] != rows[0]['end']
                or any(obs['dimensions'] != r['dimensions'][:1] or obs['start'] != r['start'] or obs['end'] != r['end'] for r in rows)
                or obs['concept'] != row['entries'][0]['observation']['concept']):
            return None
        value = total_amount(obs, cik=cik)
        if value is None or (metric == 'revenue' and value < 0):
            return None
        return {'amount_usd': value, 'observation': obs, 'column': column}
    except (KeyError, TypeError, ValueError, IndexError, AttributeError):
        return None


def _ratio(numerator, denominator, *, kind, label, input_ids):
    with localcontext() as arithmetic:
        arithmetic.prec = 80
        display = (Decimal(numerator) * 100 / Decimal(denominator)).quantize(Decimal('0.1'), rounding=ROUND_HALF_UP)
    return {'kind': kind, 'segment_label': label, 'provenance': 'derived',
            'numerator_usd': numerator, 'denominator_usd': denominator,
            'multiplier': 100, 'display_percent': format(display, '.1f'),
            'rounding': 'one decimal, half up', 'formula': 'numerator_usd / denominator_usd * 100',
            'currency': 'USD', 'input_fact_ids': input_ids}


def segment_analysis(proof, rows, *, cik):
    period = {'period_start': rows[0]['start'], 'period_end': rows[0]['end']}
    totals = {metric: _bound_total(proof, metric, rows, cik) for metric in ('revenue', 'operating_income')}
    if any(total is None for total in totals.values()):
        return {**period, 'status': 'unavailable', 'scope': 'reported_segment_table', 'totals': {}, 'derived_ratios': []}
    sums = {'revenue': sum(row['revenue_usd'] for row in rows),
            'operating_income': sum(row['operating_income_usd'] for row in rows)}
    if any(sums[metric] != totals[metric]['amount_usd'] for metric in sums):
        return {**period, 'status': 'mismatch', 'scope': 'reported_segment_table', 'totals': totals,
                'segment_sums_usd': sums, 'derived_ratios': []}
    if totals['revenue']['amount_usd'] <= 0:
        return {**period, 'status': 'zero_revenue', 'scope': 'reported_segment_table', 'totals': totals,
                'segment_sums_usd': sums, 'derived_ratios': []}
    ratios = []
    for i, row in enumerate(rows):
        revenue_fact = proof['metrics']['revenue']['entries'][i]['observation']['fact_id']
        income_fact = proof['metrics']['operating_income']['entries'][i]['observation']['fact_id']
        ratios.append(_ratio(row['revenue_usd'], totals['revenue']['amount_usd'],
            kind='share_of_reported_table_external_sales', label=row['label'],
            input_ids=[revenue_fact, totals['revenue']['observation']['fact_id']]))
        if row['revenue_usd'] > 0:
            ratios.append(_ratio(row['operating_income_usd'], row['revenue_usd'],
                kind='reported_segment_operating_margin', label=row['label'], input_ids=[income_fact, revenue_fact]))
    for ratio in ratios:
        ratio.update(period)
    return {**period, 'status': 'matched', 'scope': 'reported_segment_table', 'totals': totals,
            'segment_sums_usd': sums, 'derived_ratios': ratios}


def render_segment_analysis(analysis):
    if analysis['status'] == 'mismatch':
        return 'Reported segment amounts do not sum exactly to the bound table totals. Shares and margins are withheld.'
    if analysis['status'] == 'unavailable':
        return 'Reported totals and completeness of segment coverage have not been independently reconciled.'
    if analysis['status'] == 'zero_revenue':
        return 'Segment amounts sum to the reported table totals, but total external sales are zero; percentage analysis is unavailable.'
    text = (f"For {analysis['period_start']} to {analysis['period_end']}, segment external sales and operating results each sum exactly to the reported table totals. "
            'Derived percentages are rounded to one decimal. Sales shares use the reported table external-sales total; '
            'operating ratios use each segment\'s reported operating profit divided by its external sales.\n\n')
    grouped = {}
    for ratio in analysis['derived_ratios']:
        grouped.setdefault(ratio['segment_label'], {})[ratio['kind']] = ratio['display_percent'] + '%'
    text += '\n'.join(f"{label}: sales share {values['share_of_reported_table_external_sales']}; "
                       f"reported operating ratio {values.get('reported_segment_operating_margin', 'unavailable (zero sales)')}."
                       for label, values in grouped.items())
    return (text + '\n\nThe sales-share denominator is the reported segment-table total, not independently bound consolidated-company revenue. '
            'Corporate cost allocation affects the operating ratios; these are not standalone segment margins. '
            'Rounded shares may not sum to 100.0%. No growth, operating driver, valuation or future performance is inferred.')
