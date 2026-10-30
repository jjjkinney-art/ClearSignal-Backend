from copy import deepcopy
import pytest
from validation.ordinary_pilot_contract import quota_contract, validate_contract, CASES


def test_twelve_fixed_cases_and_nontransferable_limits():
    c = quota_contract()
    assert len(CASES) == 12 and len(set(CASES)) == 12
    assert sum(v['sec'] for v in c['per_case'].values()) == c['sec_gets'] == 66
    assert sum(v['sec/document'] for v in c['per_case'].values()) == 12
    assert validate_contract(c) == c
    assert c['execution_authorized'] is False
    # Stage directory slots share, rather than multiply, aggregate case limits.
    assert sum(s.get('sec/directory', 0) for s in c['per_stage'][CASES[0]].values()) == 5
    assert c['per_case'][CASES[0]]['sec/directory'] == 2
    # Routing may resolve identity through the directory only; totals unchanged.
    assert all(c['per_stage'][case]['routing'] == {'sec/directory': 1} for case in CASES)
    assert [c['per_case'][case]['sec'] for case in CASES] == [8 if case.endswith(':core_thesis') else 3 for case in CASES]
    assert sum(case.endswith(':core_thesis') for case in CASES) == 6


@pytest.mark.parametrize('mutation', [
    lambda c: c.update(execution_authorized=True),
    lambda c: c.update(sec_gets=67),
    lambda c: c.update(model_attempts=1),
    lambda c: c.update(concurrent_cases=True),
    lambda c: c.update(wall_seconds=480.0),
    lambda c: c['case_order'].reverse(),
    lambda c: c['case_order'].append('ASML:core_thesis'),
    lambda c: c['per_stage'][CASES[1]].update({'evidence.thesis_disclosures': {'sec/document': 1}}),
    lambda c: c['per_case'][CASES[0]].update({'sec/document': 3}),
    lambda c: c.update(approval='pretend'),
])
def test_contract_drift_is_rejected(mutation):
    c = quota_contract()
    mutation(c)
    with pytest.raises(ValueError):
        validate_contract(c)


def test_no_aliasing_or_historical_scope_expansion():
    from validation.capture_budget import PILOT_CASES
    before = deepcopy(PILOT_CASES)
    c = quota_contract()
    result = validate_contract(c)
    result['per_case'][CASES[0]]['sec'] = 999
    assert c == quota_contract()
    assert PILOT_CASES == before
    assert 'GOOGL:core_thesis' not in PILOT_CASES
