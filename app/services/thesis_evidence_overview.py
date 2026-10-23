"""Presentation of final-bound foundation rows; never a source admission path.

Called only after financial reconstruction, disclosure binding and response
reference selection. Does not infer cross-period drivers or rank risk materiality.
"""
from __future__ import annotations


def render_bound_overview(rows, comparisons, interpretations):
    paragraphs = ['Evidence-led case to investigate']
    segment = next((row for row in rows
                    if row['claim_kind'] == 'issuer_segment_financial_context'), None)
    if segment:
        context = segment['segment_context']
        segments = context['segments']
        period = f"{segments[0]['start']} to {segments[0]['end']}"
        figures = []
        for item in segments:
            result = item['operating_income_usd']
            figures.append(f"{item['label']}: external sales ${item['revenue_usd']:,}, "
                           f"operating {'loss' if result < 0 else 'profit'} ${abs(result):,}")
        paragraphs.append(f"Reported segment economics ({period}; {context['currency']}): "
                          + '; '.join(figures) + f". [{segment['reference_id']}]")
        # Keep the exact allocation adjacent to the shortened figures.
        paragraphs.append(segment['source_proof']['allocation'] + f" [{segment['reference_id']}] "
            'These allocated results do not establish standalone economics. The conditional '
            'research case is whether the reported operations can sustain profitability; '
            'the table alone establishes neither persistence nor the causes of later consolidated results.')
        for explanation in segment.get('sales_explanations', []):
            paragraphs.append(f"Management's sales explanation ({explanation['current_start']} to "
                f"{explanation['current_end']} versus {explanation['prior_start']} to "
                f"{explanation['prior_end']}): {explanation['quote']} "
                f"{explanation['limitation']} [{segment['reference_id']}]")
    else:
        paragraphs.append('A company-specific economic case remains incomplete: the bound '
                          'financial comparisons below do not establish how the business sustains returns.')
    financial = []
    signals = {row['metric']: row for row in interpretations if row['kind'] == 'financial_inference'}
    for item, ref in comparisons.values():
        current = item.verified_claims[0]
        prior = item.verified_claims[1]
        # Match using the final reference, not a concept label or ticker heuristic.
        inference = next((row for row in signals.values() if row['reference_ids'] == [ref]), None)
        if inference:
            financial.append(inference['text'].split(' This total alone', 1)[0]
                + f" Current period: {current['period_start']} to {current['period_end']}. [{ref}]")
            financial[-1] += f" Prior comparison: {prior['period_start']} to {prior['period_end']}."
    if financial:
        paragraphs.append('Consolidated observations\n' + '\n'.join(financial))
    impairment = next((row for row in rows
                       if row['claim_kind'] == 'issuer_deposit_impairment_context'), None)
    if impairment:
        # Use the complete bound event already rendered by its producer, retaining
        # segment-scope and recovery caveats rather than shortening into causality.
        paragraphs.append('Dated adverse evidence to weigh separately\n' + impairment['claim']
                          + f" [{impairment['reference_id']}]")
    paragraphs.append('Test the operating explanation, adverse evidence and persistence together. '
        'Different reporting periods and segment versus consolidated scope must not be combined '
        'into an unverified earnings bridge. Unexplained operating-cash-flow movements are context, '
        'not a favorable or adverse thesis signal. Historical monitoring levels do not establish '
        'valuation or an attractiveness boundary; valuation and expected returns remain unverified.')
    return '\n\n'.join(paragraphs)
