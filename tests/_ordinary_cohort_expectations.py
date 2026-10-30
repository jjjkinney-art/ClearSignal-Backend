"""What a synthetic or loopback rehearsal of the active cohort is expected to do.

Runs 1-2 complete all twelve cases. Run 3 halts at its eleventh case, as
pre-registered: the BWMX threshold question resolves to another issuer (DE),
whose answer the ledger refuses, and the BWMX thesis question is not run.
"""
from validation.ordinary_pilot_contract import CASES, COHORT

EXPECTED_HALT = None if COHORT == 'runs-1-2' else ('BWMX:decision_threshold', 'invalid_response')
COMPLETED = CASES if EXPECTED_HALT is None else CASES[:CASES.index(EXPECTED_HALT[0])]
EXPECTED_STATUS = 'complete' if EXPECTED_HALT is None else 'halted'
EXPECTED_CASE_STATUSES = (['answered_unadjudicated'] * 12 if EXPECTED_HALT is None else
                          ['answered_unadjudicated'] * len(COMPLETED) + ['halted']
                          + ['not_run_after_halt'] * (len(CASES) - len(COMPLETED) - 1))
