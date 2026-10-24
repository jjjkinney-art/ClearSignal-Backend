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
