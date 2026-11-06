# Threshold filing explanations (default off)

`THRESHOLD_FILING_EXPLANATIONS_ENABLED` lets a threshold answer read the latest
10-Q or 10-K and use management's stated drivers. It is off by default.

## Contract profile

`THRESHOLD_FILING_PROFILE` in `validation/ordinary_pilot_contract.py` is the one
place binding the cohort, quotas (6 thesis, 5 threshold, 66 in all), switch, filing
wait and parse cutoff. A cohort it does not name keeps the original contract, so
consumed runs export unchanged. Its only cohort is rehearsal-only and is never
`APPROVED_COHORT`, so it cannot reach a package or approval. Using it for real means
pre-registering a cohort, naming it in the profile and making it `APPROVED_COHORT`.

The boundary refuses a switch that disagrees with the running cohort's contract in
either direction, and filing limits that differ from the profile's.

## Time limits

A threshold case keeps its 20 s deadline. Within it:

| Limit | Value | Why |
|---|---|---|
| Other evidence wait | 10 s | Unchanged |
| Filing parse cutoff | 12 s | Parsing cannot be interrupted, so a filing arriving later is not parsed |
| Filing wait | 16 s | Leaves time to compose the answer before the deadline |

**These cutoffs reserve processing time. They cannot guarantee completion on an
overloaded host.** A parse that started in time, or the answer itself, can still
run past 20 s when CPU is scarce, and in a pilot that halts the run.

## When evidence is lost

The answer opens with "Incomplete answer: ..." and `source_answer` carries
`degraded` and `evidence_gaps`. A pilot ledger records each stage the answer went
without in `ordinary_stage_abandonments`, in the same transaction as the answer,
even when the stage's requests settled. The export reports that case as
`answered_degraded_unadjudicated` and refuses a degraded answer with no record.
Answers from consumed runs never declare `degraded`, so their records and exports
are unaffected.

In a pilot, a failed SEC request is not a gap in the answer: the boundary halts the
run with the first failure recorded. That includes a peer that sends nothing for the
transport's 10 s read timeout. Only a filing that keeps arriving, but too slowly,
degrades one answer.
