"""Cross-check rebuilt quote/profile/EPS against the same filing's literal EPS."""
from decimal import Decimal

from validation.filing_eps_basis import inspect_filing_eps_basis
from validation.filing_share_class import extract_filed_share_class
from validation.quote_eps_binding import assess_quote_eps_binding


def assess_filed_share_basis(binding_inputs, filing_body, filing_receipt, *,
                             form, filed_at, reporting_period_end):
    """Require literal diluted EPS agreement; this still does not clear splits."""
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
    inspection = inspect_filing_eps_basis(filing_body, filing_receipt,
        expected_cik=binding_inputs['expected_cik'], expected_symbol=binding_inputs['expected_symbol'],
        form=form, filed_at=filed_at, reporting_period_end=reporting_period_end)
    if not inspection['inspected']:
        return _gap('filed_eps_inspection')
    coverage = next(row for row in inspection['reporting_period_coverage']
                    if row['concept'] == 'EarningsPerShareDiluted')
    if coverage['status'] != 'observed':
        return _gap('filed_diluted_eps_' + coverage['status'])
    observations = [row for row in inspection['observations']
                    if row['concept'] == 'EarningsPerShareDiluted' and row['end'] == reporting_period_end]
    if not observations or any(row['start'] != eps['period_start'] or row['end'] != eps['period_end']
                              or Decimal(row['value']) != Decimal(eps['value']) for row in observations):
        return _gap('filed_eps_value_or_period')
    return {'binding_passed': True, 'status': 'partial', 'admitted': False, 'launch_ready': False,
        'classification': 'offline_filed_share_basis_consistency',
        'quote_profile_eps': binding, 'filed_share_class': cover,
        'same_eps_filing': True, 'declared_common_share_title_bound': True,
        'filed_eps_value_consistent': True,
        'filed_eps_crosscheck': {
            'concept': eps['concept'], 'value': eps['value'], 'unit': 'USD/shares',
            'period_start': eps['period_start'], 'period_end': eps['period_end'],
            'response_reference_id': eps['reference_id'],
            'filing_fact_ids': coverage['fact_ids'],
            'filing_observations': observations,
            'raw_binding': inspection['raw_binding'],
            'comparison': 'exact_decimal_value_and_calendar_period',
            'independent_origin_or_accuracy_verification': False},
        'current_security_mapping_verified': False, 'split_compatibility_verified': False,
        'price_unit_verified': False, 'eps_class_compatibility_verified': False,
        'market_pe_verified': False,
        'corporate_action_status': 'not_established_no_complete_event_evidence',
        'unanswered_parts': ['current listing/identifier mapping and price unit',
            'complete corporate-action interval and EPS split basis',
            'class-specific EPS scope and distribution rights',
            'quote session/observation admission and independently adjudicated source accuracy'],
        'limitations': ['Exact filed EPS agreement is source consistency, not current quote/EPS compatibility.',
            'Only current fiscal diluted EPS is cross-checked; this does not independently verify the prior comparison.',
            'No detected split or an empty event list cannot prove no corporate action.',
            'No ratio, conversion, source admission or recommendation is calculated.']}


def _gap(stage):
    return {'binding_passed': False, 'status': 'insufficient_valuation_inputs',
        'admitted': False, 'launch_ready': False,
        'classification': 'offline_filed_share_basis_consistency',
        'reason': 'filed_share_basis_rejected', 'stage': stage}
