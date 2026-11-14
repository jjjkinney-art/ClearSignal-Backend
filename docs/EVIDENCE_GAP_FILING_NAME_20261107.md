# Evidence-gap notice names the actual filing (2026-11-07)

Run 7's BP notice said "the latest SEC filing". The document was BP's FY2025 20-F annual report, and BP's filing list holds newer 6-Ks. Each evidence task now records the form it chose, and the notice names that report. A task lost before choosing a filing, or any other form, says "an SEC filing".

This changes `app/`, so the frozen `app/` tree `b27c28a2ad527edb9ab2fb38896c2c8f3fe29d5b` does not describe this branch. It is separate from any change for the MNST halt. Do not merge. Using it in a run needs a new freeze, pre-registration, package and approval.

## A local timeout during testing

Local test runs on the operator's Mac, offline on invented data:

| Attempt | CPU speed limit | 1-minute load | Result |
|---|---|---|---|
| First, after minutes of sustained tests | 26% just after the failure | About 27 | `thesis_declared` case failed: the parent stopped the worker at the 20 s deadline in `BP:decision_threshold`, which reads no filing document and had all 5 requests settled |
| One rerun, after the Mac recovered | 100% at start, 71% after 15 s | About 4.5 | Passed |

This change is not an obvious cause, because that case reads no filing document, but that is not proven. Throttling is associated with the failure in one pair of runs. No cause was established. CI is the check for this branch.
