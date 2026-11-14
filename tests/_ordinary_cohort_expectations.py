"""What a synthetic or loopback rehearsal of the active cohort is expected to do.

Every case whose pinned frontend intent is company analysis and whose company
the frozen backend identifies is answered. A company-analysis case whose
identity stays unresolved is counted identity_unresolved. A case the pinned
frontend sends with a general intent takes the general route, which attempts a
model call; the zero-model boundary refuses it and halts the run there
(invalid_request), on every host. With the frontend pinned to 138d646, no cohort
case takes it, so every cohort completes: run 5 here answers ten cases and leaves
OWL x2 unresolved, run 6 answers ten and leaves LLYVA x2 unresolved, and runs 9 and 10 answer
all twelve (run 10 is pinned to frontend 77c33bb, which classifies its two "/ADR" thesis
questions as company analysis; at 138d646 they were investing education and would have halted
the run). Run 5 itself
was bound to 84466b2 and halted at BNY:core_thesis; that record stays with its frozen
commit, 0d7152a.

The frozen run-3 commit (6efe7d2) was pre-registered to halt at
BWMX:decision_threshold, which resolved to another issuer (DE); that
prediction, its rehearsal and the run-3 outputs are preserved with that commit.
"""
import pytest

from validation.ordinary_frontend_intents import frontend_intent
from validation.ordinary_pilot_contract import CASES, COHORT, contract_profile

# A general frontend intent reaches the general route's model call, which the
# zero-model boundary refuses: the run halts at the first such case.
GENERAL_INTENT = [case for case in CASES if frontend_intent(case) != 'company_analysis']
EXPECTED_HALT = (GENERAL_INTENT[0], 'invalid_request') if GENERAL_INTENT else None
_HALT_INDEX = CASES.index(EXPECTED_HALT[0]) if EXPECTED_HALT else len(CASES)
# Run 5: unresolved from SEC's directory alone. "Blue Owl Capital" also names
# OBDC (a different registrant), so both OWL questions stay unresolved. SMFG,
# unresolved at the frozen run-5 commit (its CIK also lists the OTC
# foreign-ordinary line SMFNF), now resolves (fix/run5-identity-suggestions).
# Run 6: LLYVA, LLYVB and LLYVK are one issuer's distinct share classes, so its name
# abstains by design. Both cases stay in the denominator.
IDENTITY_UNRESOLVED = {'run5': ('OWL:core_thesis', 'OWL:decision_threshold'),
                       'run6': ('LLYVA:core_thesis', 'LLYVA:decision_threshold'),
                       'run9': (),
                       'run10': ()}.get(COHORT, ())
# Run 10: SEC's directory lists Fortis Inc. under FTS as well as FORFF, and Inficon Holding AG/ADR
# under IFHLY as well as IFCNF (same CIKs). Name resolution returns the first two, which the ledger
# accepts because the directory it retained lists them under the case's registered CIK.
RESOLVED_TICKER = {'run10': {'FORFF': 'FTS', 'IFCNF': 'IFHLY'}}.get(COHORT, {})


def resolved_ticker(case_id):
    """The ticker the application's answer names for this case's issuer."""
    issuer = case_id.split(':')[0]
    return RESOLVED_TICKER.get(issuer, issuer)


UNRESOLVED = [case for case in CASES[:_HALT_INDEX] if case in IDENTITY_UNRESOLVED]
COMPLETED = [case for case in CASES[:_HALT_INDEX] if case not in UNRESOLVED]
# Registration-only registrants (see validation._ordinary_synthetic_sec.REGISTRATION_ONLY; VBREY in run 10):
# SEC's own filing list proves they have no XBRL data, so the application makes no company-facts request
# and no filing request, says why, and the case is recorded unanswered_registration_only. It is a recorded
# outcome (the run goes on) and stays in the denominator of twelve.
from validation._ordinary_synthetic_sec import REGISTRATION_ONLY
REGISTRATION_ONLY_CASES = [case for case in COMPLETED if case.split(':')[0] in REGISTRATION_ONLY]
EXPECTED_STATUS = 'halted' if EXPECTED_HALT else 'complete'
EXPECTED_CASE_STATUSES = (['identity_unresolved' if case in UNRESOLVED else
                           'unanswered_registration_only' if case in REGISTRATION_ONLY_CASES else 'answered_unadjudicated'
                           for case in CASES[:_HALT_INDEX]]
                          + (['halted'] + ['not_run_after_halt'] * (len(CASES) - _HALT_INDEX - 1)
                             if EXPECTED_HALT else []))
# One refused model request: the halt stops the general agent's retries.
EXPECTED_REFUSED_MODEL_REQUESTS = 1 if EXPECTED_HALT else 0
# SEC exchanges per answered case: seven for a thesis question, three otherwise;
# plus the routing-stage directory GET when the first case resolves no company
# (its response is retained, then shared with later cases).
# Under the threshold-filing profile: five (one shared submissions response) and four
# (that response, plus the filing).
EXPECTED_THESIS_EXCHANGES, EXPECTED_THRESHOLD_EXCHANGES = (5, 4) if contract_profile() else (7, 3)
# A registration-only case makes two: the directory lookup and the submissions response. No facts request.
REGISTRATION_ONLY_EXCHANGES = 2


def expected_exchanges(case):
    """SEC exchanges an answered case makes."""
    if case in REGISTRATION_ONLY_CASES:
        return REGISTRATION_ONLY_EXCHANGES
    return EXPECTED_THESIS_EXCHANGES if case.endswith(':core_thesis') else EXPECTED_THRESHOLD_EXCHANGES


EXPECTED_SEC_EXCHANGES = sum(expected_exchanges(case) for case in COMPLETED) + (CASES[0] in IDENTITY_UNRESOLVED)
# The route each unresolved case takes: an unresolved identity asks for
# clarification (a thesis question through entity suggestions) and makes no
# SEC evidence request. A halted case records no route.
UNRESOLVED_ROUTES = [('entity_suggestion' if case.endswith(':core_thesis')
                      else 'company_identity_clarification', None) for case in UNRESOLVED]

# These build their own requests against the original quota shape. They still run, on
# that contract, in test_ordinary_historical_cohort, which requires each one to pass.
ORIGINAL_QUOTA_SHAPE = pytest.mark.skipif(
    contract_profile() is not None, reason='original quota shape; verified by test_ordinary_historical_cohort')
ORIGINAL_QUOTA_SHAPE_TESTS = {
    'test_ordinary_native_boundary': ('test_multi_row_submissions_admit_exact_supported_documents_for_their_stage',
                                      'test_submissions_drift_within_a_case_halts',
                                      'test_requests_wait_for_one_of_four_slots_instead_of_halting'),
    'test_ordinary_native_ledger': ('test_concurrency_is_checked_at_wire_entry_and_duplicate_claims_never_replay',
                                    'test_actual_entry_rate_is_independent_of_earlier_reservation_rate',
                                    'test_a_fifth_concurrent_wire_entry_halts',
                                    'test_case_completes_only_with_its_own_screened_timely_answer',
                                    'test_no_late_work_after_a_case_is_complete'),
    'test_ordinary_pilot_contract': ('test_twelve_fixed_cases_and_nontransferable_limits',),
}


def attempt_reconciliation_problems(packet, limits):
    """Why a packet's attempts do not account for themselves, dispatched or not.

    Reservation charges quota and wire entry records a dispatch; an abandoned stage can
    stop a request between the two. So attempts and wire entries differ by exactly the
    attempts that never reached the wire, each of which must have a terminal record.
    """
    problems = []
    attempts = packet['attempts']
    dispatched = [a for a in attempts if a['wire_entered_offset_ms'] is not None]
    never = [a for a in attempts if a['wire_entered_offset_ms'] is None]
    abandoned_stages = {(row['case_id'], row['stage']) for row in packet['abandoned_stages']}
    if packet['attempt_count'] != len(attempts) or packet['attempt_count'] != len(dispatched) + len(never):
        problems.append('attempt count does not reconcile')
    if packet['wire_entries'] != len(dispatched):
        problems.append('wire entries do not match dispatched attempts')
    for attempt in never:
        label = (attempt['case_id'], attempt['stage'], attempt['route'])
        if attempt['status'] != 'abandoned':
            problems.append(f'never dispatched without an abandoned status: {label}')
        if attempt['failure'] != {'code': 'abandoned', 'detail': attempt['route']}:
            problems.append(f'never dispatched without its terminal record: {label}')
        if attempt['response'] is not None:
            problems.append(f'never dispatched but has a response: {label}')
    for attempt in attempts:
        label = (attempt['case_id'], attempt['stage'], attempt['route'])
        if attempt['status'] == 'abandoned' and (attempt['case_id'], attempt['stage']) not in abandoned_stages:
            problems.append(f'abandoned attempt without its stage record: {label}')
        if attempt['status'] == 'settled' and (attempt['response'] is None or attempt['wire_entered_offset_ms'] is None):
            problems.append(f'settled attempt without its response and wire entry: {label}')
        if attempt['status'] == 'size_rejected' and (
                attempt['response'] is not None or attempt['wire_entered_offset_ms'] is None
                or attempt['failure'] != {'code': 'size_rejected', 'detail': 'response_size'}
                or attempt['route'] != 'sec/document'):
            problems.append(f'size rejection without its terminal record: {label}')
        if attempt['status'] not in {'settled', 'abandoned', 'size_rejected'}:
            problems.append(f'attempt without a terminal status: {label}')
    # Quotas charge every reservation, including those that never reached the wire.
    if len(attempts) > limits['sec_gets']:
        problems.append('attempts exceed the run limit')
    for case in {a['case_id'] for a in attempts}:
        mine = [a for a in attempts if a['case_id'] == case]
        if len(mine) > limits['per_case'][case]['sec']:
            problems.append(f'attempts exceed the case limit: {case}')
        for route in {a['route'] for a in mine}:
            if sum(a['route'] == route for a in mine) > limits['per_case'][case][route]:
                problems.append(f'attempts exceed the route limit: {case} {route}')
        for stage, route in {(a['stage'], a['route']) for a in mine}:
            if (sum(a['stage'] == stage and a['route'] == route for a in mine)
                    > limits['per_stage'][case].get(stage, {}).get(route, 0)):
                problems.append(f'attempts exceed the stage limit: {case} {stage} {route}')
    return problems

