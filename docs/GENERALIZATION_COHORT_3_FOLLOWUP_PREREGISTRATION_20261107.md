# Cohort 3 follow-up: pre-registration of an operational follow-up

Status: **plan only.** No package, approval file, retrieval, merge, deployment or run exists or is
authorized by this document. Launch readiness stays false.

## What this run would be

An **operational follow-up with previously unseen answer-quality evidence. It is not a blind
generalization test.**

**Disclosure:** oversized-filing recovery was developed after Run 6 failed on BP's FY2025 20-F. Its design,
the tests and this plan's BP predictions all use what that failure revealed. This cohort is exposed for
operational development, so any operational success is not independent evidence that the handling
generalizes.

**What stays unseen:** no answer exists for any of the 12 cases. Run 6 retained BP's directory, filing-list
and company-facts responses; only the filing list was read. BP's company facts and filing text have not
been inspected, and nothing was retrieved for the other five issuers beyond the shared directory.

**It could show:** whether the machinery completes all 12 cases against the live SEC, how recovery behaves
on a real oversized filing, and what these questions produce for these issuers, assessed by the rubric.

**It could not show:** generalization to new companies, independent human validation, representativeness or
launch readiness. Earlier runs do not validate this version: none used the recovery path, and Run 6 made
4 requests and halted.

## Frozen implementation

| Item | Value |
|---|---|
| Source commit | `9725178b17ee7104d18f9c8ff046dd09375ece9c`, on `pilot/oversized-filing-recovery` (draft [#374](https://github.com/jjjkinney-art/ClearSignal-Backend/pull/374), do not merge) |
| `app/` tree | `b27c28a2ad527edb9ab2fb38896c2c8f3fe29d5b` |
| `validation/` tree | `c0798be1890836e8bb61ec6bd894a8d0969ef2eb` |
| Source binding | `13cc7f4bb28c6a62c72ce8cb8cbeddc3cd68f760298047934c47ef0d668c29ba` (458 files, recomputed independently from an export of the commit) |
| CI at that commit | Job 128258863946: success, child 213 collected, 203 passed, 0 failed, 10 skipped, 47 of 47 required |
| Frontend pin | `138d6461a7d6822fd9b27c784a410f55b243a40e` |

Only `docs/` changes after that commit. **Any change under `app/` or `validation/` invalidates this plan.**
The commit carrying this document is the one a package would bind; it has its own CI record.

## Cohort (unchanged, no substitution)

BP (313807), MNST (865752), CRDO (1807794), LLYVA (2078416), DGXX (1854368), VIRC (751365), in that order,
each `core_thesis` then `decision_threshold`: the same twelve questions, unchanged from
`docs/generalization_cohort_3_cases.json`. No issuer may be swapped because of Run 6 or anything later.

## Offline checks (`docs/generalization_cohort_3_followup_offline_checks.json`)

Rerun at `9725178` with no network. The guard recorded no refusals.

- **Frontend classification:** the unmodified classifier and resolver, hash-matched to `138d6461` (Node
  24.15.0), return `company_analysis` for all 12.
- **Identity and routing:** `scripts/check_cohort_routes.py`, with the research pipeline stubbed, on the
  retained directory: 10 cases reach research for the correct issuer; both LLYVA cases resolve no company;
  none reaches a wrong issuer or the general route.
- **Same as `45f5283`:** classification and identity are byte-identical to the earlier records.
- **BP's document path:** the frozen request logic, run on Run 6's retained filing list only (see below).

These check classification, identity and request selection. They do not exercise a full answer.

## Predicted outcomes (stated before any new data)

| Case | Requests | Filing documents | Operational status | Delivered content |
|---|---|---|---|---|
| BP:core_thesis | 4 | 1: `bp-20251231.htm`, **rejected** | `unanswered_size_rejected` | `insufficient_evidence` |
| BP:decision_threshold | 3 | **0** | `answered_unadjudicated` | `insufficient_evidence` |
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

- **Totals:** 41-45 of the 66 permitted SEC requests, and 11-13 filing-document requests. The run completes
  with no predicted halt. `outcome_counts`: 9 `full_answer`, 3 `unanswered`, 0 `degraded_answer`,
  0 `operational_failure`. Delivered content: 6-8 `source_bound_claims`, 2-4 `insufficient_evidence`,
  2 `identity_unresolved`.
- **The `full_answer` count is operational.** BP's threshold case is predicted to count there while
  delivering no substantive answer.
- **Basis for BP's content:** BP's filing form comes from the retained list. That BP reports under IFRS is
  general knowledge, unchecked; the IFRS path is not implemented, so its facts are predicted to support
  no comparison. If its facts do support one, `BP:core_thesis` becomes `answered_degraded_unadjudicated`.
- **Weakest predictions:** the threshold content of MNST, CRDO and VIRC, since Runs 4 and 5 each had threshold
  cases with no claims, and everything about DGXX, whose filing form is unchecked general knowledge.
- **Not predicted:** any figure, explanation, accuracy, research quality or usefulness.

## BP's expected size rejection and repeat download

- **Size rejection, expected once:** `bp-20251231.htm` exceeded 16 MiB in Run 6. The exact size is unknown,
  because Run 6 recorded neither. The new record will capture the bytes read or the declared length.
- **Repeat download of that filing, not expected:** the offline check shows `BP:core_thesis` requests that one
  document and `BP:decision_threshold` requests none, because the threshold path looks only for 10-K and
  10-Q forms and BP's list holds none. An earlier statement that BP's threshold case would download it
  again was wrong, and amendment 2 now says so.
- **Should a second request occur, it is a finding:** the document would be downloaded and rejected again,
  each time charged to quota. Nothing is remembered between requests.
- **Other issuers can repeat:** a latest filing can be requested in both of an issuer's cases, and an annual
  filing that is also the latest can be requested twice within a thesis case. If oversized, each request is
  a separate rejection, up to about 16 MiB of transfer and part of that case's deadline.

## Unknown filing sizes

Only BP's size is known, and only as "over 16 MiB". Sizes for MNST, CRDO, DGXX and VIRC are unknown and will
stay so unless a run or a separately approved check retrieves them. Whole-filing sizes in a filing list do
not give a primary document's size. Any of them may also be rejected. That would lower content counts but
leave request counts and operational completion unchanged, and would not be grounds for substitution.

Rejected downloads add transfer that the 16 MiB per response bound covers, and time that case deadlines
cover: BP's took about 4.4 s to reach the limit in Run 6. A slower download that passes the filing wait is
treated as a slow filing instead.

## Failures that still halt the run

An oversized filing document no longer halts by itself. These still do; remaining cases are not run and
nothing is substituted:

- oversized directory, filing-list or company-facts responses;
- an oversized filing whose connection did not close cleanly, or whose rejection does not reconcile;
- an answer that does not declare its rejected filing;
- connection, DNS or TLS failures, redirects, HTTP error or throttling responses, wrong encoding, malformed or
  refused responses;
- a peer silent for the 10 s read timeout;
- passing a case deadline (30 s thesis, 20 s threshold) or the 480 s run limit, including through a slow host;
- identity mismatches, accounting or quota violations, configuration drift, any model or paid-provider
  attempt, and any other security failure.

A slow filing still arriving at 16 s, or complete after the 12 s parse cutoff, degrades one answer instead.

## Approved-mode coverage gaps

**Exercised once, by Run 6's 4 requests, then halted:** approved-mode launch, the real resolver, real DNS,
direct TLS with a real certificate chain, the network check on the real configuration, real SEC responses on
all four routes, an approved worker's ledger, export and packet for a halted run, `live_network: true`. This
is limited evidence on one issuer through an early halt, on code before this version.

**Never exercised in approved mode:**

- a complete run, more than one case, or a case that finishes;
- recovery itself: rejection recording, the `size_rejected` status, a real server's behaviour after the
  client closes, and continuing to the next case;
- the answer's gap notice and `answer_content` in a live packet;
- the filing wait, parse cutoff, degradation and shared submissions on live responses;
- real parsing of any filing under this profile;
- pacing and concurrency at the scale of a full run;
- real SEC sizes, timing and rate behaviour beyond those 4 requests;
- approved-mode cost and retained bytes for a complete run.

The offline tests use invented data and a loopback server with a test CA. The outcome-record test returns a
loopback worker's result to the real launcher. Six isolated-worker tests fail on the operator's Mac with
`offline_network_attempt`, at the earlier base commit too, and pass in CI. The cause is not established.

Transport failures still halt, so this does not satisfy the broader degradation launch requirement.

## Assessment (rubric preserved)

The rubric is unchanged from the cohort 2 and original cohort 3 pre-registrations: mechanical accuracy of quotes,
amounts and derived values; research quality 0/1/2 on company specificity, material risks, explanations of
change, monitoring criteria and citation support; usefulness 0/1/2; up to five material omissions per case;
individual errors. No pooled score, pass rate, or improvement claim.

**Reported separately, for all 12 cases, never merged:**

1. **Operational completion:** `cases`, `outcome_counts`, requests, halts, size rejections and timing.
2. **Substantive content:** `answer_content`. Only `source_bound_claims` counts as a substantive answer.
3. **Accuracy:** only where there is content to check. A response with none is unassessable, not accurate.
4. **Usefulness:** delivered usefulness per case. A response with no substantive answer scores 0.

Outcomes are also compared with the predictions above, including where those are wrong. BP's results are reported
with this document's exposure statement. Originals are preserved and hashed before assessment.

## Historical counts

`docs/HISTORICAL_SUBSTANTIVE_RECONCILIATION_20261107.md` reconciles Runs 1-6 by case with the earlier
reports. No earlier assessment's count changes, and no retained output was altered.

## Risk summary for any future approval

Any approval request must state: oversized filings are not read and cost that answer its evidence; sizes are
unknown except BP's; every failure listed above halts the run; the coverage gaps above; this run is not a blind
test; a host check must pass, because a slow host can halt the run; and an approval is consumed by one execution.

## Remaining before any execution

1. CI success on the commit carrying this document, with `app/` and `validation/` unchanged.
2. Offline checks repeated only if the frontend pin or frozen trees change.
3. A clean clone at that commit, with no `.env`, under the audited CPython 3.11.9 and dependencies.
4. New execution configuration, with the network path and pinned CA re-verified.
5. New cost and retention evidence from the current templates, because the enforcing-test lists changed,
   with the owner's attestations re-confirmed rather than carried silently.
6. A new package, built reproducibly, naming a new `run_id`, reference and unused output directory, with its
   review summary. Run 6's package, approval and directory stay consumed and are not reused.
7. Owner's separate approval naming the package digest and spending limit.
8. Immediately before launch: package integrity, frontend pin, network settings, AC power and host condition,
   then checks-only, then one execution if everything passes.
