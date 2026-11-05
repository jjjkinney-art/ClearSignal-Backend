"""What a synthetic or loopback rehearsal of the active cohort is expected to do.

Every case whose pinned frontend intent is company analysis is answered; a
case the pinned frontend sends with a general intent reaches no company and is
counted as identity_unresolved, not a halt. Runs 1-2 therefore complete all
twelve cases. Run 3 completes with BWMX:core_thesis unresolved until the
frontend that recognises its legal form is deployed and re-pinned. Run 5
completes with five cases unresolved: BNY:core_thesis (general frontend
intent) and both SMFG and OWL questions (directory ambiguity).

The frozen run-3 commit (6efe7d2) was pre-registered to halt at
BWMX:decision_threshold, which resolved to another issuer (DE); that
prediction, its rehearsal and the run-3 outputs are preserved with that commit.
"""
from validation.ordinary_frontend_intents import frontend_intent
from validation.ordinary_pilot_contract import CASES, COHORT

EXPECTED_HALT = None
# Run 5: the frozen backend leaves these unresolved from SEC's directory alone
# (SMFG shares its CIK with a second unsuffixed symbol, SMFNF; "Blue Owl Capital"
# also names OBDC), predicted offline before packaging and kept in the cohort.
IDENTITY_UNRESOLVED = {'run5': ('SMFG:core_thesis', 'SMFG:decision_threshold',
                                'OWL:core_thesis', 'OWL:decision_threshold')}.get(COHORT, ())
UNRESOLVED = [case for case in CASES
              if frontend_intent(case) != 'company_analysis' or case in IDENTITY_UNRESOLVED]
COMPLETED = [case for case in CASES if case not in UNRESOLVED]
EXPECTED_STATUS = 'complete'
EXPECTED_CASE_STATUSES = ['identity_unresolved' if case in UNRESOLVED else 'answered_unadjudicated'
                          for case in CASES]
# SEC exchanges per answered case: seven for a thesis question, three otherwise;
# plus the routing-stage directory GET when the first case resolves no company
# (its response is retained, then shared with later cases).
EXPECTED_SEC_EXCHANGES = (sum(7 if case.endswith(':core_thesis') else 3 for case in COMPLETED)
                          + (CASES[0] in IDENTITY_UNRESOLVED))
# The route each unresolved case takes: a general frontend intent takes the
# general route; an unresolved identity asks for clarification (a thesis question
# through entity suggestions). None of them makes an SEC evidence request.
UNRESOLVED_ROUTES = [('general_finance', None) if frontend_intent(case) != 'company_analysis'
                     else ('entity_suggestion' if case.endswith(':core_thesis')
                           else 'company_identity_clarification', None)
                     for case in UNRESOLVED]
