"""Conditional research links between admitted risks and reconstructed metrics.

This composer admits no evidence and does not estimate causality or materiality.
Its caller supplies only final-bound risk inferences and surviving comparisons.
"""
import re

_MEASURE = r'(?:revenue net of interest expense|revenues?|operating income|net income|operating cash flow)'
_OTHER = r'(?:business|financial condition|results of operations|operating results|liquidity)'
_TERM = rf'(?:our\s+)?(?:consolidated\s+)?(?:{_MEASURE}|{_OTHER})'
_EFFECT_LIST = re.compile(rf'our\s+(?:consolidated\s+)?(?:{_MEASURE}|{_OTHER})'
                          rf'(?:(?:,\s*(?:and\s+)?|\s+and\s+){_TERM})*', re.I)
_NAMES = re.compile(_MEASURE, re.I)


def risk_financial_link(risk, comparisons, *, filed_at):
    """Link explicit issuer-measure effect lists only, never broad topic labels.

    Reject third-party, adjusted, segment, negated and unresolved effect wording
    rather than deriving a financial target from a keyword somewhere in a quote.
    Historical predecessor risks cannot authorize current-successor links.
    """
    if risk['historical_context_only']:
        return None
    effect = risk['potential_effect']
    if not _EFFECT_LIST.fullmatch(effect):
        return None
    named = {name.lower() for name in _NAMES.findall(effect)}
    if 'revenues' in named:
        named.add('revenue')
    from .financial_thesis_foundation import financial_metric_label
    labels = {key: financial_metric_label(key, item.verified_claims[0]['metric'].split(':')[-1])
              for key, (item, _) in comparisons.items()}
    bank_revenue = labels.get('revenue') == 'revenue net of interest expense'
    targets = []
    for key, (item, ref) in comparisons.items():
        if key == 'operating cash flow' and bank_revenue:
            # The existing foundation treats this total as context only.
            # Do not turn a bank cash-flow total into a performance breakpoint.
            continue
        label = labels[key]
        match_name = label if key == 'revenue' and bank_revenue else key
        if match_name not in named:
            continue
        current, prior = item.verified_claims
        targets.append({'metric': label, 'reference_id': ref,
                        'current_period_start': current['period_start'],
                        'current_period_end': current['period_end'],
                        'prior_period_start': prior['period_start'],
                        'prior_period_end': prior['period_end']})
    if not targets:
        return None
    risk_ref = risk['reference_ids'][0]
    refs = list(dict.fromkeys([risk_ref] + [row['reference_id'] for row in targets]))
    text = (f'The issuer disclosure filed {filed_at} identifies a potential effect on “{effect}” '
            f'[{risk_ref}]. Relevant reported comparisons: ' + '; '.join(
                f"{row['metric']} for {row['current_period_start']} to {row['current_period_end']}, "
                f"against {row['prior_period_start']} to {row['prior_period_end']} [{row['reference_id']}]"
                for row in targets) + '.')
    test = (f'Research test: check whether “{risk["display_condition"]}” occurs and whether future '
            'like-for-like comparisons deteriorate in the named measures. Different reporting '
            'durations must be assessed separately. The disclosure and reported comparisons do '
            'not establish identical measure definitions or earnings attribution. They also do '
            'not establish a common observation period, that this risk caused reported changes, '
            'that improving results resolve it, or its likelihood or financial magnitude. '
            'This is a monitoring question, not a forecast or a buy/sell threshold.')
    return {'kind': 'risk_financial_monitoring_link', 'scope': risk['scope'],
            'condition': risk['condition'], 'potential_effect': effect,
            'risk_filed_at': filed_at, 'risk_reference_id': risk_ref,
            'financial_targets': targets, 'reference_ids': refs,
            'match_basis': 'explicit_financial_family', 'measure_equivalence_established': False,
            'causal_attribution_established': False, 'materiality_assessed': False,
            'text': text, 'conditional_test': test}


def render_risk_financial_links(links):
    return '\n\n'.join(row['text'] + ' ' + row['conditional_test'] for row in links)
