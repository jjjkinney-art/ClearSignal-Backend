"""Offline quota contract for the proposed ordinary pilot; grants no execution.

Separate from historical approval/ledger policy. No network, credentials, app
imports, output creation or execution entrypoint. This is not a dispatch fence.
"""
from copy import deepcopy

ISSUERS = ('NPK', 'GOOGL', 'INGR', 'NNBR', 'AMZN', 'MAN')
QUESTIONS = ('core_thesis', 'decision_threshold')
CASES = tuple(f'{issuer}:{question}' for issuer in ISSUERS for question in QUESTIONS)


def quota_contract():
    per_case, per_stage = {}, {}
    for case in CASES:
        core = case.endswith(':core_thesis')
        per_case[case] = {'sec': 8 if core else 3, 'sec/directory': 2 if core else 1,
                          'sec/submissions': 3 if core else 1, 'sec/facts': 1,
                          'sec/document': 2 if core else 0}
        stages = {'evidence.sec': {'sec/directory': 1, 'sec/submissions': 1},
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
