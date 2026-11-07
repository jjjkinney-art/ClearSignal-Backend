# Cohort 3 follow-up, revision 2: pre-registration after Run 7

Status: **plan only.** No package, approval file, retrieval, merge, deployment or run exists or is authorized by this document. Launch readiness stays false.

## What a run would be

An **operational follow-up on an exposed cohort, with mostly unseen answer-quality evidence. It is not a blind generalization test.** Oversized-filing recovery was developed after BP's Run 6 failure. Cooperative cancellation was developed after MNST's halt in Run 7. An operational success would not be independent evidence that either generalizes.

It could show whether the machinery completes all 12 cases against the live SEC, and how recovery and cancellation behave on real filings. It could not show generalization to new companies, independent human validation, representativeness or launch readiness.

## Frozen version

| Item | Value |
|---|---|
| Source commit | `64a393f69a843776d53bb0be9f8911077a4c64f6`, on `pilot/followup-combined` (draft [#377](https://github.com/jjjkinney-art/ClearSignal-Backend/pull/377), do not merge) |
| Tree | `9d2de800e788b722507528c26596b30246374d01` |
| `app/` tree | `3239ae89c62dbff6d342d841c1842291e29e05ce` |
| `validation/` tree | `c626312545068538fe39c64a0d71c8df9e70d94a` |
| Source binding | `ee9c0d0c5941cf93a16f903a52b327cf9125cf062d74a08c48f01498bcddca6b` (459 files, recomputed independently from an export of the commit) |
| CI at that commit | Job 128313761373: success. Child 217 collected, 207 passed, 0 failed, 10 skipped, 51 of 51 required |
| Frontend pin | `138d6461a7d6822fd9b27c784a410f55b243a40e` |

This replaces the freeze at `9725178` (`app/` tree `b27c28a2...`), which Run 7 consumed. Only `docs/` changes after that commit. **Any change under `app/` or `validation/` invalidates this plan.**

## Cohort (unchanged, no substitution)

BP, MNST, CRDO, LLYVA, DGXX, VIRC, in that order, each `core_thesis` then `decision_threshold`: the same twelve questions as `docs/generalization_cohort_3_cases.json`. No issuer may be swapped because of Run 6, Run 7 or anything later.

## Exposure

Operational exposure means knowing how the machinery behaved on an issuer. Answer-quality exposure means having seen what it delivered, or the source content that would judge it.

| Issuer | Operational exposure | Answer-quality exposure |
|---|---|---|
| **BP** | **High.** Runs 6 and 7. Known: its FY2025 20-F exceeds 16 MiB and was rejected in Run 7 after 16,780,634 bytes, with no Content-Length; request counts; the filing list's forms, dates and whole-filing sizes. Recovery was designed around it. | **Partial.** Run 7's two BP responses were read and assessed: both report insufficient evidence with no claims, so usefulness 0 and accuracy unassessable. BP's company facts and filing text have not been read. No BP research content has been seen, because none was delivered. |
| **MNST** | **High.** Run 7 halted on its thesis case. Offline replays of the retained responses gave filenames, sizes, function timings and operational statuses, including `answered_unadjudicated` for both cases in one replay. Cancellation was designed around this halt. | **None assessed.** Filing text, company facts, answers and source-answer status were not read. The replay's answers were deleted unread. That status is operational and says nothing about content. |
| CRDO, DGXX, VIRC | Low: identity and routing checks and the shared directory. Their tickers name synthetic test fixtures with invented data. | None. |
| LLYVA | Low: known to abstain on identity, by offline check. | None. |

Run 7 retained MNST's and BP's responses in its ledger. Any later reading of them for this cohort must be disclosed.

## Run 7's cause stays unconfirmed

**The cause of the delay in Run 7's `MNST:core_thesis` is unconfirmed.** Its filing task ran over 19 s after download, against 4-6 s in offline replays, and no host readings or stage timings exist from that window.

Observations, none showing what happened in Run 7:

- During an offline replay, the CPU speed limit fell from 100 to 26 in about 16 s.
- A synthetic test run missed a 20 s deadline with the limit at 26 and load about 27, and passed once rerun after the Mac recovered.
- Another synthetic test missed a deadline as the limit fell from 94 to 34 with load 12-20, and passed on its rerun, **even though the limit fell from 100 to 26 within 30 s at load about 6**.

So throttling is associated with some misses but does not produce one every time, and it can begin within seconds of a check at launch that passed. This version records host readings and stage timings during a run, so another delay could be examined. They would not by themselves prove a cause.

## What changed since Run 7

- **Cancellation:** a filing task checks for abandonment between processing stages and stops at the next checkpoint. Abandoned evidence is excluded. The next case starts only after the task has ended.
- **Status:** `unanswered_evidence_abandoned` when evidence was abandoned and the application reports insufficient evidence.
- **Notice:** a lost filing is named as "the annual report (Form 20-F)" or "the quarterly report (Form 10-Q)", or "an SEC filing" if none was chosen.
- **Records:** stage timings in the ledger, and `host_readings.json` from launch to exit.
- **Unchanged:** all deadlines, limits, quotas, questions and the rubric.

## Offline checks (`docs/generalization_cohort_3_followup_offline_checks_v2.json`)

Rerun at `64a393f` with no network and no guard refusals. All 12 classify as `company_analysis`, with hashes matching frontend `138d6461`. 10 cases reach research for the correct issuer, both LLYVA cases resolve no company, and none reaches a wrong issuer or the general route. Both are identical to the records at `45f5283`. BP's document path is unchanged: one annual document in its thesis case and none in its threshold case. These do not exercise a full answer.

## Run 7 against its predictions

Right: BP's one rejection and no repeat, its request counts, statuses and content; MNST's thesis case's 5 requests and 2 documents. Wrong: "no predicted halt". Untested: the 9 cases not run, and MNST's thesis outcome, which produced no answer.

## Predicted outcomes (before any new data)

| Case | Requests | Filing documents | Operational status | Delivered content |
|---|---|---|---|---|
| BP:core_thesis | 4 | 1, **rejected** | `unanswered_size_rejected` | `insufficient_evidence` |
| BP:decision_threshold | 3 | 0 | `answered_unadjudicated` | `insufficient_evidence` |
| MNST:core_thesis | 5 | 2 | `answered_unadjudicated` | `source_bound_claims` |
| MNST:decision_threshold | 4 | 1 | `answered_unadjudicated` | `source_bound_claims` |
| CRDO:core_thesis | 5 | 2 | `answered_unadjudicated` | `source_bound_claims` |
| CRDO:decision_threshold | 4 | 1 | `answered_unadjudicated` | `source_bound_claims` |
| LLYVA:core_thesis | 0 | 0 | `identity_unresolved` | `identity_unresolved` |
| LLYVA:decision_threshold | 0 | 0 | `identity_unresolved` | `identity_unresolved` |
| DGXX:core_thesis | 4 or 5 | 1 or 2 | `answered_unadjudicated` | Unknown |
| DGXX:decision_threshold | 3 or 4 | 0 or 1 | `answered_unadjudicated` | Unknown |
| VIRC:core_thesis | 5 | 2 | `answered_unadjudicated` | `source_bound_claims` |
| VIRC:decision_threshold | 4 | 1 | `answered_unadjudicated` | `source_bound_claims` |

- **Totals:** 41-45 of 66 requests and 11-13 filing-document requests. `outcome_counts`: 9 `full_answer`, 3 `unanswered`, 0 `degraded_answer`, 0 `operational_failure`. Content: 6-8 `source_bound_claims`, 2-4 `insufficient_evidence`, 2 `identity_unresolved`.
- **BP's rows are expectations from exposure,** not independent predictions. BP's notice is expected to name the annual report (Form 20-F).
- **Completion is the least certain prediction.** Runs 6 and 7 both halted where none was predicted. A slow task on a throttled host could turn any filing case into a degraded or unanswered one, or halt the run if it never reaches a checkpoint.
- **Weakest content predictions:** threshold cases generally, and everything about DGXX. MNST's replay status does not support its content prediction.
- **Not predicted:** any figure, explanation, accuracy, research quality or usefulness.

## Unknown filing sizes and repeats

Only BP's document is known, as over 16 MiB. MNST's two retained documents were 3,778,512 and 3,441,267 bytes. Sizes for CRDO, DGXX and VIRC are unknown. Any may be rejected, lowering content counts without changing request counts. Nothing is remembered between requests, so the same document can be rejected again if requested again. No repeat is expected for BP.

## Failures that still halt the run

- oversized directory, filing-list or company-facts responses;
- an oversized filing whose connection did not close cleanly, or whose rejection does not reconcile;
- an answer that does not declare its rejected filing;
- connection, DNS or TLS failures, redirects, HTTP error or throttling responses, wrong encoding, malformed or refused responses;
- a peer silent for the 10 s read timeout;
- passing a case deadline (30 s thesis, 20 s threshold) or the 480 s run limit, including through a slow host;
- **a task still running at the end of its case, because code between two checkpoints cannot be interrupted;**
- a stage timing that falls after the next case began, at export;
- identity mismatches, accounting or quota violations, configuration drift, any model or paid-provider attempt, and any other security failure.

## Approved-mode coverage gaps

**Exercised by Run 7, on the earlier version:** approved-mode launch, real DNS and direct TLS, a real oversized filing and its recovery, two cases finishing, the gap notice's size wording, `answer_content`, and real parsing of MNST's filings up to the halt.

**Never exercised in approved mode:**

- a complete run, or any case after the third;
- cooperative cancellation on a real filing;
- stage timing and host readings in a live run;
- the notice naming the actual report;
- the filing wait, parse cutoff and degradation on live responses;
- pacing and concurrency across a full run;
- real SEC sizes, timing and rate behaviour for CRDO, DGXX and VIRC.

The tests use invented data, a loopback server, and an invented stage held by `time.sleep`, not real slow parsing. How long real stages take under heavy throttling has not been measured. Six isolated-worker tests fail on the operator's Mac with `offline_network_attempt` and pass in CI, with the cause not established. Two synthetic tests each failed once locally on a deadline and passed on rerun, as above. Transport failures still halt, so this does not satisfy the broader degradation launch requirement.

## Assessment (rubric preserved)

The rubric is unchanged: mechanical accuracy of quotes, amounts and derived values; research quality 0/1/2 on company specificity, material risks, explanations of change, monitoring criteria and citation support; usefulness 0/1/2; up to five material omissions per case; individual errors. No pooled score, pass rate or improvement claim.

**Reported separately, for all 12 cases, never merged:** operational completion; substantive content, where only `source_bound_claims` counts as a substantive answer; accuracy, only where there is content to check; and usefulness, 0 for a response with no substantive answer. Results are compared with the predictions above, and BP and MNST are reported with this document's exposure statement.

## Risk summary for any future approval

Any approval request must state: oversized filings are not read and cost that answer its evidence; sizes are unknown except as above; every failure listed above halts the run; code between checkpoints cannot be interrupted; the coverage gaps above; Run 7's cause is unconfirmed; the Mac's CPU limit can fall within seconds of a passing check at launch; this is not a blind test; and an approval is consumed by one execution.

## Remaining before any execution

1. CI success on the commit carrying this document, with `app/` and `validation/` unchanged.
2. A clean clone at that commit, with no `.env`, under the audited CPython 3.11.9 and dependencies.
3. New execution configuration, with the network path and pinned CA re-verified.
4. New cost and retention evidence from the current templates, listing `host_readings.json` in the inventory, with the owner's confirmations re-stated.
5. A new package built twice, with a new `run_id`, reference and unused output directory, and its review summary. The packages, approvals and directories of Runs 6 and 7 stay consumed.
6. The owner's separate approval naming the package digest and spending limit.
7. Immediately before launch: package integrity, the production frontend deployment and hashes, network settings, AC power and host condition, then checks-only, then one execution if everything passes.
