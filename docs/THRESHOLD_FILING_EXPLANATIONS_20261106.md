# Threshold filing explanations (default off)

`THRESHOLD_FILING_EXPLANATIONS_ENABLED` lets a threshold answer read the latest
10-Q or 10-K and use management's stated drivers. It is off by default. Approved
pilot contracts do not change; the proposed quotas exist only in
`validation/ordinary_option_b_candidate.py`.

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
