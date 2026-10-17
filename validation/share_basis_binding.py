"""Combine rebuilt quote/profile/EPS inputs with the same annual filing's class."""
from validation.filing_share_class import extract_filed_share_class
from validation.quote_eps_binding import assess_quote_eps_binding


def assess_filed_share_basis(binding_inputs, filing_body, filing_receipt, *,
                             form, filed_at, reporting_period_end):
    """Rebuild source reports; no caller assertion or empty event list clears splits."""
    if not isinstance(binding_inputs, dict):
        return _gap('input_contract')
    expected = {'quote_body', 'quote_receipt', 'profile_body', 'profile_receipt',
        'items', 'references', 'expected_symbol', 'expected_cik', 'analysis_as_of',
        'evaluated_at', 'quote_freshness_policy', 'profile_retrieval_policy'}
    if set(binding_inputs) != expected:
        return _gap('input_contract')
    binding = assess_quote_eps_binding(**binding_inputs)
    if not binding['binding_passed']:
        return _gap('quote_profile_eps')
    cover = extract_filed_share_class(filing_body, filing_receipt,
        expected_cik=binding_inputs['expected_cik'], expected_symbol=binding_inputs['expected_symbol'],
        form=form, filed_at=filed_at, reporting_period_end=reporting_period_end)
    if not cover['extracted']:
        return _gap('filed_share_class')
    eps = binding['source_eps']
    if (eps['period_end'] != reporting_period_end or eps['filed_at'] != filed_at
            or eps['document_type'] != form
            or eps['document_ref'].get('url', '').rsplit('/', 1)[0]
               != cover['raw_binding']['url'].rsplit('/', 1)[0]):
        return _gap('same_eps_filing')
    return {'binding_passed': True, 'status': 'partial', 'admitted': False, 'launch_ready': False,
        'classification': 'offline_filed_share_basis_consistency',
        'quote_profile_eps': binding, 'filed_share_class': cover,
        'same_eps_filing': True, 'declared_common_share_title_bound': True,
        'current_security_mapping_verified': False, 'split_compatibility_verified': False,
        'price_unit_verified': False, 'eps_class_compatibility_verified': False,
        'market_pe_verified': False,
        'corporate_action_status': 'not_established_no_complete_event_evidence',
        'unanswered_parts': ['current listing/identifier mapping and price unit',
            'complete corporate-action interval and EPS split basis',
            'class-specific EPS scope and distribution rights',
            'quote session/observation admission and independently adjudicated source accuracy'],
        'limitations': ['Same-filing class declaration is narrower than current quote/EPS compatibility.',
            'No detected split or an empty event list cannot prove no corporate action.',
            'No ratio, conversion, source admission or recommendation is calculated.']}


def _gap(stage):
    return {'binding_passed': False, 'status': 'insufficient_valuation_inputs',
        'admitted': False, 'launch_ready': False,
        'classification': 'offline_filed_share_basis_consistency',
        'reason': 'filed_share_basis_rejected', 'stage': stage}
