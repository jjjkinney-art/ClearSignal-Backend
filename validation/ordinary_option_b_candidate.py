"""Option B: a CANDIDATE configuration, not a pilot contract.

Proposes 6 SEC requests per thesis case and 5 per threshold case within the
unchanged 66-request ceiling, with threshold answers reading the latest filing
and one submissions response per case. Nothing approved reads this module:
``ordinary_pilot_contract.quota_contract`` and every package built from it stay
as they are. It exists so the proposal can be rehearsed against the invented SEC
backend. A pilot using it needs its own pre-registration, package and approval.
"""
from contextlib import contextmanager
import copy
import importlib
import json

from validation.capture_budget import BudgetError
from validation.ordinary_native_boundary import DOCUMENT_STAGES, OrdinaryNativeBoundary
from validation.ordinary_pilot_contract import CASES, quota_contract as _approved_contract

CANDIDATE = 'option_b'
_LIMIT_MODULES = ('ordinary_pilot_contract', 'ordinary_native_export', 'ordinary_native_policy',
                  'ordinary_native_ledger', 'ordinary_native_boundary', 'ordinary_transport',
                  'ordinary_execution_contract')


def candidate_quota_contract():
    """The approved contract with only the Option B request limits changed."""
    limits = copy.deepcopy(_approved_contract())
    for case in limits['case_order']:
        if case.endswith(':core_thesis'):
            limits['per_case'][case].update({'sec': 6, 'sec/submissions': 1})
        else:
            limits['per_case'][case].update({'sec': 5, 'sec/directory': 2, 'sec/document': 1})
            # The filing-metrics stage may be the one that fetches the shared response.
            limits['per_stage'][case]['evidence.filing_metrics'] = {
                'sec/directory': 1, 'sec/submissions': 1, 'sec/document': 1}
    return limits


def validate_candidate(limits):
    """Refuse a candidate that exceeds the ceiling or claims authority to run."""
    thesis = [case for case in CASES if case.endswith(':core_thesis')]
    threshold = [case for case in CASES if not case.endswith(':core_thesis')]
    routes = ('sec/directory', 'sec/submissions', 'sec/facts', 'sec/document')
    per_case = limits['per_case']
    if (limits['execution_authorized'] is not False or limits['sec_gets'] != 66
            or limits['model_attempts'] != 0 or limits['paid_provider_attempts'] != 0
            or len(thesis) != 6 or len(threshold) != 6
            or any(per_case[case]['sec'] != 6 for case in thesis)
            or any(per_case[case]['sec'] != 5 for case in threshold)
            or any(sum(per_case[case][route] for route in routes) != per_case[case]['sec'] for case in CASES)
            or sum(per_case[case]['sec'] for case in CASES) != 66
            or any(per_case[case]['sec/submissions'] != 1 for case in CASES)):
        raise BudgetError('option B candidate limits refused')
    return limits


def _install(contract):
    previous = {}
    for name in _LIMIT_MODULES:
        module = importlib.import_module('validation.' + name)
        previous[name] = module.quota_contract
        module.quota_contract = contract
    return previous


def activate():
    """In a worker process that lives only for one candidate rehearsal."""
    validate_candidate(candidate_quota_contract())
    _install(candidate_quota_contract)


@contextmanager
def candidate_limits():
    previous = _install(candidate_quota_contract)
    try:
        yield
    finally:
        for name, contract in previous.items():
            importlib.import_module('validation.' + name).quota_contract = contract


class OptionBBoundary(OrdinaryNativeBoundary):
    """One validated submissions response admits its documents for the whole case.

    Every other check is inherited. A discarded late response is never admitted,
    because the parent only reaches ``_admit`` for a live, unabandoned exchange.
    """
    threshold_filing = True

    def active(self):
        super().active()
        # The approved policy shape has no key for this switch, so check it here.
        if self.settings is not None and self.settings.threshold_filing_explanations_enabled is not True:
            self.refuse('configuration_drift')

    def _admit(self, route, stage, media, content):
        super()._admit(route, stage, media, content)
        if route == 'sec/submissions':
            with self.lock:
                urls = self.admitted[(self.case_run, stage)]
                for other in DOCUMENT_STAGES:
                    self.admitted[(self.case_run, other)] = urls


def run_candidate_rehearsal(output_dir, *, scenario='happy'):
    """Invented SEC backend and invented approval; never a live path."""
    from validation.ordinary_isolated_rehearsal import cohort_selection, rehearsal_policy, require_runtime, run_worker
    from validation.ordinary_native_ledger import create_fresh_output
    from validation._ordinary_rehearsal_worker import REHEARSAL_RUNTIME, SCENARIO_FAULTS
    if scenario not in SCENARIO_FAULTS:
        raise BudgetError('option B rehearsal scenario refused')
    require_runtime()
    with candidate_limits():
        output = create_fresh_output(output_dir)
        policy = rehearsal_policy(output)
        result = run_worker(output, policy, mode='rehearsal', scenario=scenario, environment=cohort_selection(),
                            forbidden=tuple(REHEARSAL_RUNTIME.values()), synthetic=True, candidate=CANDIDATE)
    result['approval'] = 'invented_test_only'
    result['candidate'] = CANDIDATE
    return result


if __name__ == '__main__':  # python -m validation.ordinary_option_b_candidate <output> <scenario>
    import sys
    print(json.dumps(run_candidate_rehearsal(sys.argv[1], scenario=sys.argv[2]), default=str))
