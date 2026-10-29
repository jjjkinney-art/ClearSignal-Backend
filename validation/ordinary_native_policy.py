"""Fixed twelve-case native profile, for a separately approved future launcher.

This validates supplied operator records, not approver identity or invoice terms.
There is no launcher, credential lookup, network request, or approval generation.
The previously consumed profiles and the pending proposal alone are not accepted.
"""
import re

from validation.capture_budget import BudgetError, digest
from validation.ordinary_execution_contract import pending_manifest
from validation.ordinary_pilot_contract import CASES, quota_contract
from validation.pilot_approved import validate_execution
from validation.pilot_policy import AUDITED_DEPENDENCIES, MODEL_ROUTES, SEC_ROUTES

PURPOSE = 'approved_ordinary_twelve_case_pilot'
TEST_ONLY = 'TEST-ONLY-NOT-AN-APPROVAL'
# The cohort makes no model request, so a live run carries no model credential:
# OPENAI_API_KEY must be exactly this non-secret value.
ZERO_MODEL_PLACEHOLDER = 'ORDINARY-ZERO-MODEL-NO-CREDENTIAL'


def test_only_references(policy):
    """Whether any reference in the policy marks an invented test record."""
    execution = policy['execution_configuration']
    values = (policy['approval']['reference'], policy['approval']['run_id'],
              policy['retention_reference'], policy['pricing_review_reference'],
              execution['documentation_reference'], execution['verification_reference'])
    return any('test-only' in value.lower() for value in values)


def execution_package(*, cases, code_binding, dependencies, execution, output_dir,
                      all_in_usd, retention_reference, pricing_review_reference):
    if (type(code_binding) is not dict or set(code_binding) != {'revision', 'source_sha256'}
            or type(code_binding['revision']) is not str or not code_binding['revision']
            or dependencies != dict(AUDITED_DEPENDENCIES)):
        raise BudgetError('ordinary code/dependency binding refused')
    validate_execution(execution)
    if type(pricing_review_reference) is not str or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}', pricing_review_reference):
        raise BudgetError('explicit pricing review reference required')
    proposal = pending_manifest(cases=cases, source_sha256=code_binding['source_sha256'],
        dependency_sha256=digest(dependencies), output_dir=output_dir, all_in_usd=all_in_usd,
        retention_reference=retention_reference)
    return {'purpose': PURPOSE, 'proposal': proposal, 'code_binding': code_binding,
            'execution_configuration': execution, 'pricing_review_reference': pricing_review_reference,
            'invoice_ceiling_verified': False, 'approval_status': 'pending'}


def policy_for(code_binding, dependencies, approval, execution, *, cases, all_in_usd,
               retention_reference, pricing_review_reference):
    if type(approval) is not dict or set(approval) != {
            'reference', 'run_id', 'manifest_sha256', 'output_dir', 'all_in_usd',
            'execution_allowed', 'spending_authorized'}:
        raise BudgetError('new ordinary approval record required')
    package = execution_package(cases=cases, code_binding=code_binding, dependencies=dependencies,
        execution=execution, output_dir=approval['output_dir'], all_in_usd=all_in_usd,
        retention_reference=retention_reference, pricing_review_reference=pricing_review_reference)
    if (approval['manifest_sha256'] != digest(package) or approval['all_in_usd'] != all_in_usd
            or approval['execution_allowed'] is not True or approval['spending_authorized'] is not True
            or any(type(approval[k]) is not str or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}', approval[k])
                   or approval[k] in {'pending', 'NO_SPENDING_AUTHORITY'} for k in ('reference', 'run_id'))):
        raise BudgetError('separate approval must match complete ordinary package')
    limits = quota_contract()
    routes = (*MODEL_ROUTES, *SEC_ROUTES)
    return {'schema_version': 2, 'purpose': PURPOSE, 'pilot_id': approval['run_id'],
        'approval_reference': approval['reference'], 'approval': approval,
        'configuration_version': digest(package), 'code_binding': code_binding,
        'dependencies': dependencies, 'execution_configuration': execution,
        'pricing_review_reference': pricing_review_reference, 'budget_usd': all_in_usd,
        'retention_reference': retention_reference, 'case_records': cases,
        'setup_sha256': package['proposal']['case_records_sha256'],
        'maximum_attempts': 66, 'approved_case_ids': list(CASES),
        'invoice_ceiling_verified': False,
        # Source-evidence application path: SEC inputs only, no model routes.
        'configuration': {'variant': 'source_monitoring', 'model_attempts': 0,
                          'paid_provider_attempts': 0, 'follow_redirects': False,
                          'transport_retries': 0,
                          'settings': {'decision_monitoring_inputs_enabled': True,
                                       'decision_monitoring_filing_fallback_enabled': False,
                                       'auth_enabled': True}},
        'prices': {route: {'currency': 'USD', 'all_incremental_charges_accounted': False,
            'request_usd': '0', 'input_token_usd': '0', 'output_token_usd': '0',
            'maximum_input_tokens': 0, 'maximum_output_tokens': 0} for route in routes},
        'stage_quotas': limits['per_stage'],
        'quotas': {'groups': {'model': list(MODEL_ROUTES), 'sec': list(SEC_ROUTES)},
            'overall': {'model': 0, 'sec': 66}, 'sec_per_second': 10,
            'per_case': {case: {**dict.fromkeys(routes, 0), 'model': 0, **values}
                         for case, values in limits['per_case'].items()}}}
