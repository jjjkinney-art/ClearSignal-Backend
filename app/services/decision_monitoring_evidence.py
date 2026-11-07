"""Rebuilt financial monitoring benchmarks, never bull/bear price targets."""
from datetime import date
from decimal import Decimal
import re

from .financial_thesis_foundation import build_financial_foundation


# Exactly what a decision threshold would need and SEC filings do not supply. Stated instead of a number.
MISSING_THRESHOLD_INPUTS = [
    {'decision': 'Valuation boundary',
     'missing': 'a dated share price and share count, and a valuation multiple or discount rate with its stated basis'},
    {'decision': 'Expected return',
     'missing': 'a dated entry price, a forecast of earnings or cash flow with its assumptions, and a holding period'},
    {'decision': 'Investment cutoff', 'missing': "the investor's own required return and risk limit"},
    {'decision': 'Operating KPI breakpoint or quantified earnings impact',
     'missing': 'reported KPI history and a stated, reproducible link from that KPI to earnings'},
]


def render_missing_threshold_inputs():
    return ('\n\nNot a decision threshold\nThe figures above are historical baselines for monitoring. '
            'A decision threshold needs inputs this evidence does not contain, so none is stated:\n'
            + '\n'.join(f"- {row['decision']}: needs {row['missing']}." for row in MISSING_THRESHOLD_INPUTS))


def build_decision_monitoring(ticker, items, references, *, expected_cik=None):
    result = _build_decision_monitoring(ticker, items, references, expected_cik=expected_cik)
    if result is None:
        return None
    result['answer'] += render_missing_threshold_inputs()
    result['missing_threshold_inputs'] = MISSING_THRESHOLD_INPUTS
    coverage = _newer_filing_coverage(result['foundation'], items, references)
    if coverage:
        result['reporting_period_coverage'] = coverage
        result['unanswered_parts'] = result.get('unanswered_parts', []) + [
            'financial comparisons for the newer listed filing period']
        result['answer'] += (
            '\n\nReporting-period coverage: a retrieved filing listing identifies '
            f"a newer reporting period ending {coverage['newer_listed_period_end']} "
            + ' '.join(f'[{ref}]' for ref in coverage['filing_reference_ids'])
            + '. Some cited financial comparisons cover older periods, as dated above. '
            'The newer filing listing does not verify its financial amounts. '
            'Comparisons for that newer period remain unverified in this answer.')
    return result


def _newer_filing_coverage(foundation, items, references):
    """Metadata can identify a coverage gap, never authorize newer metric values."""
    from .thesis_disclosures import _business_issuer_url
    selected = [item for item in foundation['selected_items'] if item.verified_claims]
    if not selected:
        return None
    issuer = re.match(r'^https://www\.sec\.gov/Archives/edgar/data/([0-9]+)/', selected[0].url or '')
    if not issuer:
        return None
    def bound_reference(item):
        matches = [ref for ref in references
            if ref.get('title') == item.title.strip()[:300]
            and ref.get('source') == item.source.strip()[:120]
            and ref.get('url') == item.url and ref.get('published_at') == item.timestamp
            and re.fullmatch(r'E[1-9]\d*', str(ref.get('id', '')))]
        if len(matches) != 1:
            return None
        ref = matches[0]
        return ref if sum(other.get('id') == ref['id'] for other in references) == 1 else None
    listings = []
    for item in items:
        if (item.claim_type != 'filing_metadata' or item.source != 'SEC EDGAR'
                or item.source_type != 'regulatory_filing' or item.source_tier != 'primary'
                or item.extraction_method != 'publisher_feed'
                or item.document_type not in {'10-Q', '10-Q/A', '10-K', '10-K/A', '20-F', '20-F/A'}
                or item.freshness_status in {'stale', 'conflicting', 'superseded', 'unavailable'}
                or item.availability_status != 'available'
                or not _business_issuer_url(item.url, issuer[1])):
            continue
        try:
            end, filed = date.fromisoformat(item.reporting_period_end), date.fromisoformat(item.timestamp)
            if (end.isoformat() != item.reporting_period_end or filed.isoformat() != item.timestamp
                    or not end <= filed <= date.today()):
                continue
        except (TypeError, ValueError):
            continue
        ref = bound_reference(item)
        if (ref and ref.get('claim_type') == 'filing_metadata'
                and ref.get('document_type') == item.document_type
                and ref.get('reporting_period_end') == item.reporting_period_end):
            listings.append((item.reporting_period_end, ref['id']))
    if not listings:
        return None
    latest = max(end for end, _ in listings)
    older = []
    for item in selected:
        current = item.verified_claims[0]
        ref = bound_reference(item)
        if ref and current['period_end'] < latest:
            older.append({'metric': current['metric'], 'period_end': current['period_end'],
                          'reference_id': ref['id']})
    if not older:
        return None
    return {'status': 'newer_filing_metadata_available', 'newer_listed_period_end': latest,
            'filing_reference_ids': sorted({ref for end, ref in listings if end == latest}),
            'older_comparisons': older}


def _build_decision_monitoring(ticker, items, references, *, expected_cik=None):
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
        # Missing operating income must not discard other independently rebuilt
        # comparisons. Do not use this path to bypass mismatched margin inputs.
        # A bank reports no operating-income line: the same partial path, but
        # the margin is not applicable rather than unverified.
        not_applicable = 'operating income' in foundation.get('not_applicable', ())
        if 'operating income' not in foundation['unanswered_parts'] and not not_applicable:
            return None
        observations = [row for row in foundation['inferences']
                        if row['kind'] == 'financial_inference']
        answer = 'Evidence-backed financial monitoring (partial)\n\n'
        answer += '\n\n'.join(row['claim'] + f" [{row['reference_id']}]"
                              for row in foundation['claims'])
        answer += '\n\nMonitoring conditions\n' + '\n\n'.join(
            row['text'] + ' ' + ' '.join(f'[{ref}]' for ref in row['reference_ids'])
            + ' ' + row['conditional_test'] for row in observations)
        answer += ('\n\n' + ('Banks report no operating-income line, so no operating margin '
                   'or margin benchmark applies. Pretax income, if shown, is supplementary '
                   'profitability context. ' if not_applicable else
                   'Operating income was not verified, so no operating margin '
                   'or margin benchmark has been calculated. Pretax income, if '
                   'shown, is supplementary profitability context and does not '
                   'establish operating income. ') +
                   'Evaluate each comparison against '
                   'its own reporting period; these observations do not establish '
                   'a common-period ratio or causal relationship. They do not '
                   'determine whether the stock is attractive or unattractive. '
                   'Valuation boundaries, expected returns, operating KPI '
                   'breakpoints and quantified earnings impacts remain unverified.')
        return {'answer': answer, 'benchmarks': [], 'calculations': observations,
                'foundation': foundation,
                'unanswered_parts': [] if not_applicable else ['operating income', 'operating margin']}
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
            'condition': ('Monitoring condition: the margin for the corresponding period one year later is lower than '
                          f"this {Decimal(row['current']['margin_percent']):.2f}% baseline, on the same scope, currency "
                          'and duration.'),
            'limitation': 'This is a monitoring benchmark, not a buy/sell boundary, forecast or materiality threshold.',
        })
    answer = 'Evidence-backed financial monitoring (partial)\n\n'
    answer += '\n\n'.join(row['text'] + ' ' + ' '.join(
        f'[{ref}]' for ref in row['reference_ids']) for row in calculations)
    answer += '\n\nMonitoring criteria\n' + '\n'.join(
        f"- Historical baseline, not an investment threshold: operating margin of "
        f"{Decimal(row['current']['margin_percent']):.2f}% for {row['current']['period_start']} to "
        f"{row['current']['period_end']}. Monitoring condition: if the margin for the corresponding period one "
        f"year later is lower than this {Decimal(row['current']['margin_percent']):.2f}% baseline, on the same "
        "consolidated scope, currency and duration, that would "
        + ("mean a larger operating loss relative to revenue and weaken any recovery assumption"
           if Decimal(row['current']['margin_percent']) <= 0 else "weaken the profitability assumption")
        + "; it would not by itself make the company unattractive. "
        + ' '.join(f'[{ref}]' for ref in row['reference_ids']) for row in calculations)
    explanation = next((row for row in foundation['claims'] if row.get('period_explanation')), None)
    if explanation:
        from .current_period_explanation import monitoring_criteria
        # Management's own stated drivers and the filing's bridge, as bound.
        answer += ''.join(f"\n- {line} [{explanation['reference_id']}]"
                          for line in monitoring_criteria(explanation['period_explanation']))
    answer += ('\nThese criteria restate reported figures and management attributions. They do not '
               'determine whether the stock is attractive or unattractive. Seasonality between different '
               'quarters has not been assessed, so a sequential quarter is not a comparable period. Valuation '
               'boundaries, expected returns, operating KPI breakpoints and quantified earnings impacts remain '
               'unverified.')
    return {'answer': answer, 'benchmarks': benchmarks,
            'calculations': calculations, 'foundation': foundation}
