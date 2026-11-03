"""What a synthetic or loopback rehearsal of the active cohort is expected to do.

Every case whose pinned frontend intent is company analysis is answered; a
case the pinned frontend sends with a general intent reaches no company and is
counted as identity_unresolved, not a halt. Runs 1-2 therefore complete all
twelve cases. Run 3 completes with BWMX:core_thesis unresolved until the
frontend that recognises its legal form is deployed and re-pinned.

The frozen run-3 commit (6efe7d2) was pre-registered to halt at
BWMX:decision_threshold, which resolved to another issuer (DE); that
prediction, its rehearsal and the run-3 outputs are preserved with that commit.
"""
from validation.ordinary_frontend_intents import frontend_intent
from validation.ordinary_pilot_contract import CASES

EXPECTED_HALT = None
UNRESOLVED = [case for case in CASES if frontend_intent(case) != 'company_analysis']
COMPLETED = [case for case in CASES if case not in UNRESOLVED]
EXPECTED_STATUS = 'complete'
EXPECTED_CASE_STATUSES = ['identity_unresolved' if case in UNRESOLVED else 'answered_unadjudicated'
                          for case in CASES]
# SEC exchanges per answered case: seven for a thesis question, three otherwise.
EXPECTED_SEC_EXCHANGES = sum(7 if case.endswith(':core_thesis') else 3 for case in COMPLETED)
