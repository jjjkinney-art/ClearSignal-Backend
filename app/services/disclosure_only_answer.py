"""A partial thesis answer made only of source-bound issuer disclosures.

When verified filing evidence supports a business description or a disclosed risk but no
pair of financial comparisons could be built, those disclosures are still delivered, and
the answer says plainly that no financial analysis was completed. It never states a
figure, baseline, threshold or inference of its own: every claim is a quotation the
existing producers already bound to its filing.

The financial gap is named only as far as retrieval confirms it. The IFRS taxonomy is
named as the reason only when the Company Facts response this process received contained
more ifrs-full than us-gaap concepts; otherwise the reason stays generic.
"""
import re

from .business_context import coverage_from_bound_descriptions, render_business_coverage
from .going_concern_disclosure import bound_going_concern
from .thesis_competition import bound_competition_description
from .thesis_disclosures import bound_business_description, bound_thesis_risk

CONTENT_SCOPE = 'disclosures_only'
# The only claim kinds a disclosure-only answer may carry. None states a figure.
DISCLOSURE_ONLY_KINDS = frozenset({'issuer_business_description', 'issuer_competition_description',
                                   'issuer_disclosed_risk', 'issuer_going_concern_disclosure'})
_PER_KIND_LIMIT = 2

IFRS_REASON = ('The SEC structured data retrieved for this issuer is tagged mainly under the IFRS taxonomy '
               '(ifrs-full), which this version does not read, so no revenue, profit or cash-flow comparison, '
               'monitoring baseline or threshold was attempted.')
GENERIC_REASON = ('A verified comparison of at least two current and prior-period financial figures could not be '
                  'built from the SEC data retrieved, so no financial comparison, monitoring baseline or '
                  'threshold was attempted.')


AS_REPORTED_IFRS_REASON = ('The SEC structured data retrieved for this issuer is tagged mainly under the IFRS taxonomy '
                           '(ifrs-full). It was read as reported (annual comparisons, in the filing\'s own currency, no '
                           'conversion), but no annual comparison could be shown, so no revenue, profit or cash-flow '
                           'comparison, monitoring baseline or threshold was attempted.')


def financial_gap(cik):
    """Why no financial analysis exists, naming IFRS only when retrieval confirmed it."""
    from ..providers.sec_client import observed_fact_taxonomies
    observed = observed_fact_taxonomies(cik) if isinstance(cik, str) else None
    if observed and observed.get('ifrs-full', 0) > observed.get('us-gaap', 0):
        from ..config import settings
        if getattr(settings, 'as_reported_financials_enabled', False) is True:
            return {'status': 'not_established', 'reason': 'as_reported_comparisons_not_shown',
                    'observed_taxonomies': observed, 'text': AS_REPORTED_IFRS_REASON}
        return {'status': 'not_established', 'reason': 'ifrs_taxonomy_not_supported',
                'observed_taxonomies': observed, 'text': IFRS_REASON}
    return {'status': 'not_established', 'reason': 'comparisons_unavailable',
            'observed_taxonomies': observed, 'text': GENERIC_REASON}


def build_disclosure_only(ticker, items, references, *, expected_cik=None):
    """Return the disclosure-only partial answer, or None when no disclosure is bound."""
    if expected_cik is None:
        from .providers.sec_provider import _load_ticker_cik_map
        try:
            expected_cik = _load_ticker_cik_map().get(ticker)
        except Exception:
            return None
    if not expected_cik or not expected_cik.isdigit():
        return None
    rows, selected, seen = [], [], set()
    counts = {kind: 0 for kind in DISCLOSURE_ONLY_KINDS}
    business = []
    # The issuer's going-concern conclusion is stated first; reference numbers keep the item order.
    for index, item in sorted(enumerate(items, start=1),
                              key=lambda pair: not getattr(pair[1], 'going_concern_disclosures', None)):
        value = (bound_business_description(item, ticker=ticker, cik=expected_cik)
                 or bound_competition_description(item, ticker=ticker, cik=expected_cik)
                 or bound_going_concern(item, ticker=ticker, cik=expected_cik)
                 or bound_thesis_risk(item, ticker=ticker))
        if (not value or value['claim_kind'] not in DISCLOSURE_ONLY_KINDS or value['quote'] in seen
                or counts[value['claim_kind']] >= _PER_KIND_LIMIT):
            continue
        reference_id = f'E{index}'
        if references is not None:
            ref = next((ref for ref in references
                        if ref.get('title') == item.title.strip()[:300]
                        and ref.get('source') == item.source.strip()[:120]
                        and ref.get('url') == item.url and ref.get('published_at') == item.timestamp), None)
            if not ref or not re.fullmatch(r'E[1-9]\d*', str(ref.get('id', ''))):
                continue
            reference_id = ref['id']
        row = {'claim': item.summary, 'reference_id': reference_id, 'claim_kind': value['claim_kind']}
        if value.get('competition_scope'):
            row['competition_scope'] = dict(value['competition_scope'])
        if value.get('business_scope'):
            row['business_scope'] = dict(value['business_scope'])
        if value.get('issuer_relationship'):
            # A predecessor's risk is not the current issuer's disclosure.
            continue
        rows.append(row)
        selected.append(item)
        seen.add(value['quote'])
        counts[value['claim_kind']] += 1
        if value['claim_kind'] == 'issuer_business_description':
            business.append((value['quote'], reference_id))
    if not rows:
        return None
    from .financial_thesis_foundation import ISSUER_DESCRIPTION_CAVEAT, ISSUER_RISK_CAVEAT
    gap = financial_gap(expected_cik)
    answer = ('Source-bound disclosures only (partial): no financial analysis was completed\n\n'
              + gap['text']
              + ' The statements below are quotations from the issuer\'s annual filing; they are not a financial '
                'analysis, a thesis or an assessment.\n\n'
              + ('Official business, competition and sampled risk context'
                 if counts['issuer_competition_description'] else 'Official business and sampled risk context')
              + '\n' + '\n\n'.join(
                  f"{row['claim'].removesuffix(ISSUER_RISK_CAVEAT).removesuffix(ISSUER_DESCRIPTION_CAVEAT)} "
                  f"[{row['reference_id']}]" for row in rows)
              + '\nThese short excerpts are issuer statements and partial context, not a complete business model '
                'or a ranking of the most material risks, and not independent assessments. Competitive advantage '
                'and future performance remain unverified; disclosed possibilities do not establish occurrence, '
                'probability or a quantified effect.')
    if not counts['issuer_disclosed_risk']:
        answer += ('\nNo company-specific risk disclosure met the selection rules for this answer; '
                   'material risks remain unverified.')
    coverage = coverage_from_bound_descriptions(business, scoped_context=[])
    if business:
        answer += '\n\nBusiness context coverage\n' + render_business_coverage(coverage)
    unanswered = ['financial performance and reported comparisons', 'monitoring baselines',
                  'valuation and expected returns',
                  'competitive position' if counts['issuer_business_description']
                  else 'business model and competitive position',
                  'investment thesis and its supporting/invalidation mechanisms']
    if counts['issuer_disclosed_risk']:
        unanswered.append('risk materiality, likelihood and effect on the investment case')
    else:
        unanswered.append('issuer-disclosed operating-risk mechanisms')
    if business:
        unanswered.append('business model completeness')
    answer += '\n\nThis is not a financial analysis. Unverified requested parts: ' + '; '.join(unanswered) + '.'
    return {'answer': answer, 'claims': rows, 'selected_items': selected, 'inferences': [],
            'unanswered_parts': unanswered, 'business_context_coverage': coverage,
            'content_scope': CONTENT_SCOPE, 'financial_analysis': {
                key: gap[key] for key in ('status', 'reason', 'observed_taxonomies')}}
