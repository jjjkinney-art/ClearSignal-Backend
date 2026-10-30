"""Offline quota contract for the proposed ordinary pilot; grants no execution.

Separate from historical approval/ledger policy. No network, credentials, app
imports, output creation or execution entrypoint. This is not a dispatch fence.
"""
from copy import deepcopy

# Runs 1 and 2 used these issuers with tests/ordinary_pilot_cases.json (kept
# unchanged). Run 3 is the pre-registered unseen-company evaluation in
# docs/GENERALIZATION_EVAL_PLAN_20261030.md.
RUN_1_2_ISSUERS = ('NPK', 'GOOGL', 'INGR', 'NNBR', 'AMZN', 'MAN')
COHORT_FILE = 'tests/ordinary_run3_cases.json'
ISSUERS = ('SCCO', 'BX', 'LNC', 'LVS', 'USCB', 'BWMX')
QUESTIONS = ('core_thesis', 'decision_threshold')
# Both BWMX cases are predicted offline to halt the run, so they are ordered
# last and no other case is lost; both stay in the denominator. The threshold
# question resolves to another issuer, whose SEC request the boundary refuses
# before dispatch; the thesis question is classified by the pinned frontend as
# a general intent, which the backend answers with a model (zero-model rule).
LAST_CASE = 'BWMX:core_thesis'
CASES = tuple(case for case in (f'{issuer}:{question}' for issuer in ISSUERS for question in QUESTIONS)
              if case != LAST_CASE) + (LAST_CASE,)


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
