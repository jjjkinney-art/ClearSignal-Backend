"""What a synthetic or loopback rehearsal of the active cohort is expected to do.

Every case whose pinned frontend intent is company analysis and whose company
the frozen backend identifies is answered. A company-analysis case whose
identity stays unresolved is counted identity_unresolved. A case the pinned
frontend sends with a general intent takes the general route, which attempts a
model call; the zero-model boundary refuses it and halts the run there
(invalid_request), on every host. With the frontend pinned to 138d646, no cohort
case takes it, so every cohort completes: run 5 here answers ten cases and leaves
OWL x2 unresolved. Run 5 itself was bound to 84466b2 and halted at BNY:core_thesis;
that record stays with its frozen commit, 0d7152a.

The frozen run-3 commit (6efe7d2) was pre-registered to halt at
BWMX:decision_threshold, which resolved to another issuer (DE); that
prediction, its rehearsal and the run-3 outputs are preserved with that commit.
"""
from validation.ordinary_frontend_intents import frontend_intent
from validation.ordinary_pilot_contract import CASES, COHORT

# A general frontend intent reaches the general route's model call, which the
# zero-model boundary refuses: the run halts at the first such case.
GENERAL_INTENT = [case for case in CASES if frontend_intent(case) != 'company_analysis']
EXPECTED_HALT = (GENERAL_INTENT[0], 'invalid_request') if GENERAL_INTENT else None
_HALT_INDEX = CASES.index(EXPECTED_HALT[0]) if EXPECTED_HALT else len(CASES)
# Run 5: unresolved from SEC's directory alone. "Blue Owl Capital" also names
# OBDC (a different registrant), so both OWL questions stay unresolved. SMFG,
# unresolved at the frozen run-5 commit (its CIK also lists the OTC
# foreign-ordinary line SMFNF), now resolves (fix/run5-identity-suggestions).
IDENTITY_UNRESOLVED = {'run5': ('OWL:core_thesis', 'OWL:decision_threshold')}.get(COHORT, ())
UNRESOLVED = [case for case in CASES[:_HALT_INDEX] if case in IDENTITY_UNRESOLVED]
COMPLETED = [case for case in CASES[:_HALT_INDEX] if case not in UNRESOLVED]
EXPECTED_STATUS = 'halted' if EXPECTED_HALT else 'complete'
EXPECTED_CASE_STATUSES = (['identity_unresolved' if case in UNRESOLVED else 'answered_unadjudicated'
                           for case in CASES[:_HALT_INDEX]]
                          + (['halted'] + ['not_run_after_halt'] * (len(CASES) - _HALT_INDEX - 1)
                             if EXPECTED_HALT else []))
# One refused model request: the halt stops the general agent's retries.
EXPECTED_REFUSED_MODEL_REQUESTS = 1 if EXPECTED_HALT else 0
# SEC exchanges per answered case: seven for a thesis question, three otherwise;
# plus the routing-stage directory GET when the first case resolves no company
# (its response is retained, then shared with later cases).
EXPECTED_SEC_EXCHANGES = (sum(7 if case.endswith(':core_thesis') else 3 for case in COMPLETED)
                          + (CASES[0] in IDENTITY_UNRESOLVED))
# The route each unresolved case takes: an unresolved identity asks for
# clarification (a thesis question through entity suggestions) and makes no
# SEC evidence request. A halted case records no route.
UNRESOLVED_ROUTES = [('entity_suggestion' if case.endswith(':core_thesis')
                      else 'company_identity_clarification', None) for case in UNRESOLVED]
