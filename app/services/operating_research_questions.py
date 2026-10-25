"""Research questions from final-bound rows, never an evidence admission path.

These questions do not estimate effects, rank materiality or change signals.
Matching a filing/segment prevents unrelated policies being joined; it does not
establish a causal link between a policy and reported results.
"""


def _document(row):
    ref = row.get('document_ref', {})
    values = tuple(ref.get(key) for key in ('content_hash', 'url', 'published_at'))
    return values if all(isinstance(value, str) and value for value in values) else None


def _filing(row):
    from urllib.parse import urldefrag
    identity = _document(row)
    return (identity[0], urldefrag(identity[1])[0], identity[2]) if identity else None


def operating_research_questions(rows):
    """Called after final reconstruction and response reference selection only."""
    output = []
    segments = [r for r in rows if r['claim_kind'] == 'issuer_segment_financial_context']
    policies = [r for r in rows if r['claim_kind'] == 'issuer_segment_revenue_policy']
    for policy in policies:
        context = policy['policy_context']
        if (context['role'] != 'contract_terms'
                or context.get('price_terms') != 'fixed_price_with_limited_material_escalation_exception'):
            continue
        label, = context['segments']
        matches = [(row, segment) for row in segments
                   if _document(row) is not None and _document(row) == _document(policy)
                   for segment in row['segment_context']['segments'] if segment['label'] == label]
        if len(matches) != 1:
            continue
        row, segment = matches[0]
        output.append({
            'kind': 'operating_research_question', 'topic': 'contract_cost_exposure',
            'scope': 'named_segment', 'segment_label': label,
            'period_start': segment['start'], 'period_end': segment['end'],
            'reference_ids': [row['reference_id'], policy['reference_id']],
            'causal_attribution_established': False, 'materiality_assessed': False,
            'text': f"{label}, reported results for {segment['start']} to {segment['end']}: "
                'how sensitive are contract economics to actual cost changes under the disclosed '
                'fixed-price terms and limited material-escalation exception? Compare contract pricing, '
                'costs and mix with subsequent like-for-like segment results. The policy does not '
                'explain the reported profit or establish future margins.'})
    cash_rows = [r for r in rows if r['claim_kind'] == 'issuer_annual_cash_flow_context']
    for row in cash_rows:
        context = row['cash_flow_context']
        matches = [r for r in rows if r['claim_kind'] == 'issuer_cash_reconciliation'
            and _filing(row) is not None and _filing(r) == _filing(row)
            and r['cash_reconciliation']['totals'][0]['start'] == context['current_start']
            and r['cash_reconciliation']['totals'][0]['end'] == context['current_end']
            and r['cash_reconciliation']['totals'][1]['start'] == context['prior_start']
            and r['cash_reconciliation']['totals'][1]['end'] == context['prior_end']]
        matched = matches[0] if len(matches) == 1 else None
        output.append({
            'kind': 'operating_research_question', 'topic': 'annual_cash_conversion',
            'scope': 'consolidated', 'period_start': context['current_start'],
            'period_end': context['current_end'], 'reference_ids': [row['reference_id']] + ([matched['reference_id']] if matched else []),
            'causal_attribution_established': False, 'materiality_assessed': False,
            'text': f"Consolidated cash use for {context['current_start']} to {context['current_end']}: "
                + ('the complete statement-contribution reconciliation is provided below. Which '
                 'disclosed movements recur or reverse? Compare subsequent matched-period statements '
                 'before judging cash generation. Test later interim movements separately; the annual '
                 'reconciliation does not establish their drivers.' if matched else
                'which working-capital movements explain the annual cash outflow, and do they recur '
                'or reverse? Reconcile the complete cash-flow statement with management’s annual '
                'explanation before judging cash generation. Test later interim movements separately; '
                'the annual explanation does not establish their drivers.')})
    return output


def render_operating_questions(questions):
    return '\n\n'.join(question['text'] + ' ' + ' '.join(
        f'[{ref}]' for ref in question['reference_ids']) for question in questions)
