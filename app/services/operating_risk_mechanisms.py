"""Conditional cost/profitability mechanisms from final-bound issuer risk prose.

No evidence admission, effect quantification, source retrieval or risk ranking.
"""
import re

_OWNER = r"(?:our|the Company['’]s)"
_EFFECT = (rf'(?:(?:significantly|materially) )?increase {_OWNER} '
           r'(?:(?:labor|operating|production|compliance|material|procurement) )?costs'
           rf'(?: and risks)? and reduce (?:{_OWNER} )?profitability')
_RELATIVE = re.compile(rf'(?P<condition>.{{15,500}}?) that (?P<modality>may|could|can) '
                       rf'(?P<effect>{_EFFECT})\.', re.I)
_DIRECT = re.compile(rf'(?P<condition>.{{15,500}}?) (?P<modality>may|could|can) '
                     rf'(?P<effect>{_EFFECT})\.', re.I)
_UNRESOLVED = re.compile(r'^(?:(?:Furthermore|Moreover|However|In addition),?\s+)?'
                         r'(?:this|these|that|those|it|they|such|we|the foregoing|the above|'
                         r'the situation|the risks|our actions|our efforts|our measures)\b', re.I)


def operating_risk_mechanism(value, reference_id, comparisons, *, filed_at):
    """Compose only after the caller's final risk and financial reconstruction.

    Profitability context is not a measure of the disclosed cost effect. In
    particular, no income concept or margin is inferred from 'profitability'.
    """
    if value.get('issuer_relationship'):
        return None
    quote = value['quote']
    match = _RELATIVE.fullmatch(quote) or _DIRECT.fullmatch(quote)
    if not match:
        return None
    condition = match['condition']
    from .issuer_risk_evidence import RISK_TOPICS
    topic = RISK_TOPICS.get(value['scope'])
    if (not topic or not re.search(topic, condition, re.I)
            or _UNRESOLVED.match(condition)
            or re.search(r'\b(?:may|might|could|can|will|would|not|never|no)\b', condition, re.I)):
        return None
    from .financial_thesis_foundation import financial_metric_label
    context = []
    for key in ('operating income', 'net income'):
        if key not in comparisons:
            continue
        item, ref = comparisons[key]
        current, prior = item.verified_claims
        context.append({'metric': financial_metric_label(key, current['metric'].split(':')[-1]),
                        'reference_id': ref, 'role': 'profitability_context_only',
                        'current_period_start': current['period_start'],
                        'current_period_end': current['period_end'],
                        'prior_period_start': prior['period_start'],
                        'prior_period_end': prior['period_end']})
    text = f'Issuer-stated cost/profitability mechanism, filed {filed_at}: “{quote}” [{reference_id}].'
    if context:
        text += ' Reported profitability context to examine: ' + '; '.join(
            f"{row['metric']} for {row['current_period_start']} to {row['current_period_end']}, "
            f"against {row['prior_period_start']} to {row['prior_period_end']} [{row['reference_id']}]"
            for row in context) + '.'
    else:
        text += ' No reconstructed operating-income or net-income comparison is available for context.'
    test = ('Research test: seek evidence of the disclosed operating condition and cost movements, '
            'then assess future like-for-like profitability alongside that evidence. '
            'The quoted possibility does not establish occurrence, likelihood or materiality. '
            'Profitability comparisons are context, not a measurement of this cost effect; '
            'they do not establish common periods, identical definitions, causality or a quantified '
            'earnings impact. Improving results do not establish that the risk is resolved. '
            'This is a monitoring question, not a forecast or a buy/sell threshold.')
    return {'kind': 'operating_risk_monitoring_inference', 'scope': value['scope'],
            'condition': condition, 'potential_effect': match['effect'],
            'modality': match['modality'], 'source_quote': quote,
            'risk_reference_id': reference_id, 'risk_filed_at': filed_at,
            'financial_context': context,
            'reference_ids': list(dict.fromkeys([reference_id] + [row['reference_id'] for row in context])),
            'causal_attribution_established': False, 'materiality_assessed': False,
            'measure_equivalence_established': False, 'text': text, 'conditional_test': test}
