"""Offline quota contract for the proposed ordinary pilot; grants no execution.

Separate from historical approval/ledger policy. No network, credentials, app
imports, output creation or execution entrypoint. This is not a dispatch fence.
"""
from copy import deepcopy
import os

QUESTIONS = ('core_thesis', 'decision_threshold')
# Runs 1 and 2 used these issuers with tests/ordinary_pilot_cases.json (kept
# unchanged). Run 3 is the pre-registered unseen-company evaluation in
# docs/GENERALIZATION_EVAL_PLAN_20261030.md.
RUN_1_2_ISSUERS = ('NPK', 'GOOGL', 'INGR', 'NNBR', 'AMZN', 'MAN')
RUN_3_ISSUERS = ('SCCO', 'BX', 'LNC', 'LVS', 'USCB', 'BWMX')
# Run 5 is unseen-company cohort 2, pre-registered in
# docs/GENERALIZATION_COHORT_2_PREREGISTRATION_20261105.md. Amendment 2 moves
# BNY:core_thesis last, before any retrieval: the pinned frontend sends it as
# investing_education, the general route attempts a model call, and the
# zero-model boundary halts the run there. Last, it costs no other case; it
# stays in the denominator as a failed case.
RUN_5_ISSUERS = ('SMFG', 'BNY', 'OWL', 'TWST', 'AGEN', 'FSTR')
RUN_5_LAST_CASE = 'BNY:core_thesis'
# Run 6 is unseen-company cohort 3, pre-registered in
# docs/GENERALIZATION_COHORT_3_PREREGISTRATION_20261106.md and connected by its
# amendment 1. No case is reordered: no halt is predicted.
RUN_6_ISSUERS = ('BP', 'MNST', 'CRDO', 'LLYVA', 'DGXX', 'VIRC')
# Both BWMX cases are predicted offline to halt the run, so they are ordered
# last and no other case is lost; both stay in the denominator. The threshold
# question resolves to another issuer, whose SEC request the boundary refuses
# before dispatch; the thesis question is classified by the pinned frontend as
# a general intent, which the backend answers with a model (zero-model rule).
LAST_CASE = 'BWMX:core_thesis'
COHORTS = {
    'run3': ('tests/ordinary_run3_cases.json',
             tuple(case for case in (f'{i}:{q}' for i in RUN_3_ISSUERS for q in QUESTIONS) if case != LAST_CASE)
             + (LAST_CASE,)),
    'runs-1-2': ('tests/ordinary_pilot_cases.json',
                 tuple(f'{i}:{q}' for i in RUN_1_2_ISSUERS for q in QUESTIONS)),
    'run5': ('tests/ordinary_run5_cases.json',
             tuple(case for case in (f'{i}:{q}' for i in RUN_5_ISSUERS for q in QUESTIONS) if case != RUN_5_LAST_CASE)
             + (RUN_5_LAST_CASE,)),
    'run6': ('tests/ordinary_run6_cases.json',
             tuple(f'{i}:{q}' for i in RUN_6_ISSUERS for q in QUESTIONS)),
}
# Rehearsal fault scenarios target the thesis case at this index and the
# threshold case after it: the third issuer's, unless that issuer is predicted
# unresolved (run 5: OWL), then the next issuer whose two cases are answered.
FAULT_CASE_INDEX = {'run5': 5}
# The only cohort an approved package or run may use.
APPROVED_COHORT = 'run6'
# Rehearsal tests may select the historical cohort to keep exercising a fully
# completing run; the approved launcher refuses any selection, so an approved
# execution always uses APPROVED_COHORT, whose case records its package binds.
COHORT = os.environ.get('ORDINARY_PILOT_COHORT', APPROVED_COHORT)
if COHORT not in COHORTS:
    raise ValueError('unknown ordinary pilot cohort')
COHORT_FILE, CASES = COHORTS[COHORT]
# Kept for the historical run-3 cohort's tests.
LAST_CASE = CASES[-1] if COHORT != 'run3' else LAST_CASE
FAULT_CASE_INDEX = FAULT_CASE_INDEX.get(COHORT, 4)
ISSUERS = tuple(dict.fromkeys(case.split(':')[0] for case in CASES))

# Threshold answers read the latest filing. This is the one place that binds the
# cohort, question order, frontend pin, request quotas, application switch and timing
# settings together. A cohort not named here keeps the contract below exactly as it was,
# so consumed runs still export unchanged, under their own cohort selection.
THRESHOLD_FILING_PROFILE = {
    'name': 'threshold_filing_v1',
    'cohort': 'run6',
    'case_order': list(COHORTS['run6'][1]),
    'questions_sha256': 'c0617b758458f25c7517393d00809a8d667ad2023b1689e16b813c19be74a4a1',
    'frontend': {'commit': '138d6461a7d6822fd9b27c784a410f55b243a40e',
                 'classifier_sha256': '6ef10de383a75628b72bda552b624489992c84730e43ee884f56a4bc6dc1df38',
                 'resolver_sha256': '6fa4e195816df8c09a6439c86fb4c41d3a9d60990745cb877f492a5d7dd38542'},
    'sec_gets_per_case': {'core_thesis': 6, 'decision_threshold': 5},
    'sec_gets': 66,
    'switch': 'threshold_filing_explanations_enabled',
    'filing_wait_seconds': 16,
    'filing_parse_cutoff_seconds': 12,
    'read_timeout_seconds': 10,
    'case_seconds': {'core_thesis': 30, 'decision_threshold': 20},
    'wall_seconds': 480,
}


def contract_profile():
    """The running cohort's named profile, or None for the original contract."""
    return deepcopy(THRESHOLD_FILING_PROFILE) if COHORT == THRESHOLD_FILING_PROFILE['cohort'] else None


def quota_contract():
    per_case, per_stage = {}, {}
    for case in CASES:
        core = case.endswith(':core_thesis')
        per_case[case] = {'sec': 8 if core else 3, 'sec/directory': 2 if core else 1,
                          'sec/submissions': 3 if core else 1, 'sec/facts': 1,
                          'sec/document': 2 if core else 0}
        # One routing-stage directory slot: /ask resolves a company named only
        # in question text through the SEC directory before evidence stages.
        # Per-case and overall totals are unchanged; the shared directory
        # response then serves the pipeline instead of a second GET.
        stages = {'routing': {'sec/directory': 1},
                  'evidence.sec': {'sec/directory': 1, 'sec/submissions': 1},
                  'evidence.sec_metrics': {'sec/directory': 1, 'sec/facts': 1}}
        if core:
            for stage in ('evidence.filing_metrics', 'evidence.thesis_disclosures'):
                stages[stage] = {'sec/directory': 1, 'sec/submissions': 1, 'sec/document': 1}
        per_stage[case] = stages
    if contract_profile() is not None:
        for case in CASES:
            if case.endswith(':core_thesis'):
                per_case[case].update({'sec': 6, 'sec/submissions': 1})
            else:
                per_case[case].update({'sec': 5, 'sec/directory': 2, 'sec/document': 1})
                # Whichever stage arrives first fetches the case's one submissions response.
                per_stage[case]['evidence.filing_metrics'] = {
                    'sec/directory': 1, 'sec/submissions': 1, 'sec/document': 1}
    return {'case_order': list(CASES), 'sec_gets': 66, 'per_case': per_case,
            'per_stage': per_stage, 'execution_authorized': False,
            'model_attempts': 0, 'paid_provider_attempts': 0,
            'wall_seconds': 480, 'concurrent_cases': 1, 'concurrent_sec': 4,
            'body_max_bytes': 16777216, 'aggregate_raw_body_max_bytes': 268435456}


def validate_contract(candidate):
    """Accept exactly this proposal, including types; never authorize dispatch."""
    # Equality alone admits True as 1 and floating-point substitutions for ints.
    def exact(left, right):
        if type(left) is not type(right):
            return False
        if isinstance(right, dict):
            return left.keys() == right.keys() and all(exact(left[k], v) for k, v in right.items())
        if isinstance(right, list):
            return len(left) == len(right) and all(exact(a, b) for a, b in zip(left, right))
        return left == right
    if not exact(candidate, quota_contract()):
        raise ValueError('ordinary pilot contract drift; execution remains unauthorized')
    return deepcopy(candidate)
