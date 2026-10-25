"""Presentation of final-bound foundation rows; never a source admission path.

Called only after financial reconstruction, disclosure binding and response
reference selection. Does not infer cross-period drivers or rank risk materiality.
"""
from __future__ import annotations

OVERVIEW_CLAIM_KINDS = frozenset({
    'issuer_segment_financial_context', 'issuer_deposit_impairment_context',
})


def render_bound_overview(rows, *, operating_questions=()):
    paragraphs = ['Evidence-led case to investigate']
    segment = next((row for row in rows
                    if row['claim_kind'] == 'issuer_segment_financial_context'), None)
    if segment:
        # Move the complete final-bound statement, including definition, allocation
        # and any management explanation; do not create a competing short version.
        paragraphs.append('Reported segment economics\n' + segment['claim']
                          + f" [{segment['reference_id']}]")
        synthesis = segment_persistence_case(segment)
        if synthesis:
            paragraphs.append(synthesis)
        else:
            paragraphs.append('The conditional '
            'research case is whether the reported operations can sustain profitability; '
            'the table alone establishes neither persistence nor the causes of later consolidated results.')
    else:
        paragraphs.append('A company-specific economic case remains incomplete: the bound '
                          'financial comparisons below do not establish how the business sustains returns.')
    impairment = next((row for row in rows
                       if row['claim_kind'] == 'issuer_deposit_impairment_context'), None)
    if impairment:
        # Use the complete bound event already rendered by its producer, retaining
        # segment-scope and recovery caveats rather than shortening into causality.
        paragraphs.append('Dated adverse evidence to weigh separately\n' + impairment['claim']
                          + f" [{impairment['reference_id']}]")
    if operating_questions:
        from .operating_research_questions import render_operating_questions
        paragraphs.append('Operating questions to resolve\n' + render_operating_questions(operating_questions))
    paragraphs.append('Test the operating explanation, adverse evidence and persistence together. '
        'Different reporting periods and segment versus consolidated scope must not be combined '
        'into an unverified earnings bridge. Unexplained operating-cash-flow movements are context, '
        'not a favorable or adverse thesis signal. Historical monitoring levels do not establish '
        'valuation or an attractiveness boundary; valuation and expected returns remain unverified.')
    return '\n\n'.join(paragraphs)


def segment_persistence_case(row):
    """A conditional test from final-bound, reconciled segment signs only."""
    context = row.get('segment_context', {})
    segments = context.get('segments', [])
    if not context.get('totals_reconciled') or not segments:
        return None
    periods = {(s['start'], s['end']) for s in segments}
    if len(periods) != 1:
        return None
    positive = [s['label'] for s in segments if s['operating_income_usd'] > 0]
    negative = [s['label'] for s in segments if s['operating_income_usd'] < 0]
    if not positive and not negative:
        return None
    if len(positive) != 1 or not negative:
        return _other_segment_case(row, segments, positive, negative)
    start, end = next(iter(periods))
    return (f"Conditional investment case to test: for {start} to {end}, "
            f"{positive[0]} was the only reported segment with positive operating income, "
            f"while {' and '.join(negative)} reported operating losses. "
            "The case therefore depends on whether the profitable segment can sustain its "
            "reported contribution and whether the loss-making segments improve or continue "
            "to offset it. Subsequent comparable segment results that show weakening profit "
            "alongside persistent losses would weaken this case; sustained profit and narrowing "
            "losses would support it. These are conditional tests, not forecasts. The filing's "
            "cost allocations apply; reported segment profit is not standalone earning power "
            f"or consolidated cash generation. [{row['reference_id']}]")


def _other_segment_case(row, segments, positive, negative):
    start, end = segments[0]['start'], segments[0]['end']
    parts = [f"Conditional segment case to test, {start} to {end}:"]
    if positive:
        parts.append('Positive reported operating income: ' + '; '.join(positive) + '.')
    if negative:
        parts.append('Reported operating losses: ' + '; '.join(negative) + '.')
    zero = [s['label'] for s in segments if s['operating_income_usd'] == 0]
    if zero:
        parts.append('Zero reported operating income: ' + '; '.join(zero) + '.')
    if positive and negative:
        parts.append('Test whether the profitable segments sustain their contributions and '
                     'whether losses elsewhere narrow. Sustained profit and narrowing losses '
                     'would support this operating case; weakening profits and persistent or '
                     'widening losses would weaken it.')
    elif positive:
        parts.append('Test whether the reported profitable segments sustain their contributions. '
                     'Sustained comparable segment profits would support this operating case; '
                     'declining profits or a shift into losses would weaken it. Positive '
                     'segment results alone do not establish an attractive investment.')
    else:
        parts.append('A recovery case requires evidence of improving segment economics. '
                     'Narrowing comparable losses would support that case; persistent or '
                     'widening losses would weaken it. A loss does not itself establish '
                     'that recovery is likely or that the shares are inexpensive.')
    parts.append("These are conditional tests, not forecasts. Compare subsequent like-for-like "
                 "periods and segment definitions. The filing's cost allocations apply; "
                 "reported segment profit is not standalone earning power or consolidated "
                 f"cash generation. [{row['reference_id']}]")
    return ' '.join(parts)
