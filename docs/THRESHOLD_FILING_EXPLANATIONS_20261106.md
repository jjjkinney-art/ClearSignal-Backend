# Threshold filing explanations (default off)

`THRESHOLD_FILING_EXPLANATIONS_ENABLED` lets a threshold answer read the latest
10-Q or 10-K and use management's stated drivers. It is off by default.

## Contract profile

`THRESHOLD_FILING_PROFILE` in `validation/ordinary_pilot_contract.py` is the one
place binding the cohort, question order, frontend pin, quotas (6 thesis, 5 threshold,
66 in all), switch, and timing: 16 s filing wait, 12 s parse cutoff, 10 s read timeout,
30 s and 20 s case deadlines and the 480 s run limit. Its cohort is run 6, pre-registered
in `GENERALIZATION_COHORT_3_PREREGISTRATION_20261106.md`. A cohort it does not name keeps
the original contract, so consumed runs export unchanged under their own selection, and
the launcher refuses any selected cohort.

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

## Transport failures halt the run

Graceful degradation and transport failure are different outcomes:

| Event | Outcome |
|---|---|
| A filing still arriving at the 16 s wait | One answer degraded; the run continues |
| A complete filing arriving after the 12 s cutoff | One answer degraded; the run continues |
| Connection failure, or no bytes within the 10 s read timeout | **The run halts**, with the first failure recorded |
| Refused or malformed SEC response | **The run halts**, with the first failure recorded |

The 10 s read timeout is deliberate and stays. A halted run reports its remaining
cases as not run; nothing substitutes for them.

**This does not satisfy the broader degradation launch requirement.** It covers slow
filings on threshold answers, in a pilot boundary. Graceful handling of transport
failures remains unimplemented and unvalidated, and no live run has exercised any of
this.
