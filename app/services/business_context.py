"""Coverage of already admitted issuer descriptions, not new evidence admission."""
import re

FACETS = (
    ('activities', 'Products, services and operating activities'),
    ('revenue_model', 'How the issuer generates revenue'),
    ('customers_and_channels', 'Customers and distribution channels'),
    ('segments', 'Reported segment structure'),
)
_CUSTOMERS_OR_CHANNELS = re.compile(
    r'\b(?:to|for)\s+(?:our\s+)?'
    r'(?:(?:individual|institutional|commercial|retail|wholesale|corporate|enterprise)\s+){0,2}'
    r'(?:customers|clients|investors|consumers|patients|adults|retailers|wholesalers|businesses)\b|'
    r'\bthrough\s+(?:(?:independent|direct|partner)\s+)?(?:dealers|distributors|retailers|wholesalers|channels)\b', re.I)


def description_roles(quote):
    """Tag wording only after producer/final binding; tags never authorize a claim.

    No named-issuer lookup, rewriting or inference of revenue from a product
    sale is performed. Only an explicit main-clause revenue predicate gets that
    role; revenue earned by the issuer's customers cannot fill it.
    """
    from .thesis_disclosures import (
        _CURRENT_BUSINESS_PREDICATE, _CURRENT_REVENUE_MODEL, _CURRENT_PRODUCT_DISTRIBUTION,
        _CURRENT_SEGMENT_STRUCTURE, _NAMED_SEGMENT_STRUCTURE, _REPORTED_SEGMENT_LIST,
        _NAMED_ISSUER_ACTIVITY, _bare_segment_list, _customer_purpose_activity,
        _segment_business_scope,
    )
    if _segment_business_scope(quote):
        # A legal organization name is structure, not its operating activities.
        return {'segments'}
    roles = set()
    named_list = bool(_NAMED_SEGMENT_STRUCTURE.match(quote) or _REPORTED_SEGMENT_LIST.fullmatch(quote))
    segment_statement = bool(_CURRENT_SEGMENT_STRUCTURE.match(quote))
    if named_list or segment_statement:
        roles.add('segments')
    if _CURRENT_REVENUE_MODEL.match(quote):
        roles.add('revenue_model')
    if (_CURRENT_BUSINESS_PREDICATE.match(quote) or _customer_purpose_activity(quote)
            or _NAMED_ISSUER_ACTIVITY.match(quote)) and not named_list:
        roles.add('activities')
    if segment_statement and not _bare_segment_list(quote):
        roles.add('activities')
    if (_CURRENT_PRODUCT_DISTRIBUTION.fullmatch(quote) or _customer_purpose_activity(quote)
            or _CUSTOMERS_OR_CHANNELS.search(quote)):
        roles.add('customers_and_channels')
    return roles


def complementary_candidates(candidates):
    """Keep the existing first choice, then prefer additional descriptive roles.

    Input is the producer's already qualified, preference-sorted source spans.
    Original order breaks ties; full quotes, offsets and admission are untouched.
    """
    if not candidates:
        return []
    selected = candidates[:1]
    remaining = list(candidates[1:])
    covered = description_roles(selected[0][1])
    while remaining and len(selected) < 2:
        from .thesis_disclosures import _bare_segment_list
        # Preserve the producer's existing preference for actual operations
        # over unexplained segment acronyms, even when acronyms add a role.
        eligible = [i for i, row in enumerate(remaining) if not _bare_segment_list(row[1])]
        index = max(eligible or range(len(remaining)),
                    key=lambda i: (len(description_roles(remaining[i][1]) - covered), -i))
        row = remaining.pop(index)
        selected.append(row)
        covered.update(description_roles(row[1]))
    return selected


def coverage_from_bound_descriptions(descriptions, *, scoped_context=()):
    """Summarize only (bound quote, admitted response reference) pairs."""
    references = {key: [] for key, _ in FACETS}
    for quote, reference_id in descriptions:
        for key in description_roles(quote):
            if reference_id not in references[key]:
                references[key].append(reference_id)
    coverage = {
        'scope': 'sampled_issuer_descriptions', 'complete_business_model': False,
        'facets': [{'facet': key, 'label': label,
                    'status': 'source_description_present' if references[key] else 'not_verified',
                    'reference_ids': references[key]} for key, label in FACETS],
        'limitation': 'These are sampled issuer descriptions. Full business-model coverage, segment economics, competitive strength and causal financial drivers remain unverified.',
    }
    if scoped_context:
        # Supplied only by final-bound, selected disclosure branches. These
        # entries never fill issuer-wide facets or assert complete coverage.
        coverage['scoped_context'] = list(scoped_context)
        coverage['scope'] = 'sampled_issuer_descriptions_and_scoped_segment_context'
        coverage['limitation'] = (
            'The named-segment evidence above does not establish issuer-wide activities or a complete business model. '
            'Standalone segment economics, competitive strength and independently established causal drivers remain unverified. '
            'Reported figures and management attributions retain their original scope and periods.')
    return coverage


def render_business_coverage(coverage):
    lines = []
    scoped = coverage.get('scoped_context', [])
    for facet in coverage['facets']:
        if facet['reference_ids']:
            cites = ' '.join(f'[{ref}]' for ref in facet['reference_ids'])
            lines.append(f"{facet['label']}: sampled issuer description {cites}.")
        elif facet['facet'] == 'activities' and any(row['kind'] == 'segment_product_list' for row in scoped):
            lines.append(f"{facet['label']}: issuer-wide coverage remains unverified; named-segment product evidence is listed below.")
        else:
            lines.append(f"{facet['label']}: not verified in the admitted descriptions.")
    for row in scoped:
        cites = ' '.join(f'[{ref}]' for ref in row['reference_ids'])
        if row['kind'] == 'segment_product_list':
            lines.append(f"Named-segment product list: {row['segment_label']} {cites}.")
        elif row['kind'] == 'reported_segment_results':
            lines.append(f"Reported annual segment results: {', '.join(row['segment_labels'])}; "
                         f"{row['period_start']} to {row['period_end']} ({row['currency']}) {cites}.")
        elif row['kind'] == 'management_sales_explanation':
            lines.append(f"Management-attributed segment sales explanation: {row['segment_label']}; "
                         f"{row['current_start']} to {row['current_end']} versus "
                         f"{row['prior_start']} to {row['prior_end']} {cites}.")
    return '\n'.join(lines) + '\n' + coverage['limitation']
