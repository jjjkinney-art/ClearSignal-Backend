# Historical substantive-answer counts, reconciled by case (2026-11-07)

Read-only. Every run's retained packet is unchanged; its SHA-256 is in `docs/historical_substantive_reconciliation.json`, which also holds these rows. Content is computed by `answer_content` at `9725178` from what each packet retained. It says what was delivered, not whether it was right.

## Result

**No earlier assessment's substantive count changes.** Across 72 cases, none conflicts with an earlier report that classified it.

| Run | Packet `answered_unadjudicated` | Source-bound claims | Insufficient evidence | Identity unresolved | No answer | Not run | Earlier report |
|---|---|---|---|---|---|---|---|
| 1 | 4 | 3 | 1 | 0 | 1 | 7 | No substantive count reported |
| 2 | 12 | 12 | 0 | 0 | 0 | 0 | 12 partial; label called operational only |
| 3 | 0 | 0 | 0 | 2 | 1 | 9 | No answered cases |
| 4 | 12 | 9 | 3 | 0 | 0 | 0 | 9 verified, 3 honest refusals |
| 5 | 7 | 5 | 2 | 4 | 1 | 0 | 5 substantive, 2 empty, 4 no company, 1 halted |
| 6 | 0 | 0 | 0 | 0 | 1 | 11 | 1 halted, 11 not run |

## Explaining the differences

- **What differs is the packet label, not the assessments.** The packets count completion. The Run 2, 4 and 5 assessments already kept completion and substance apart, and Run 5 states its 7 versus 5 directly.
- **Amendment 3's framing was too broad.** It told readers of Runs 1, 4 and 5 to use the claims column, which is right for the packet's `full_answer`, but those runs' assessments did not make the error. Runs 4 and 5 give the same counts as here.
- **Run 1 is the one gap.** No earlier report gave a substantive count. Its label says 4 answered; `GOOGL:decision_threshold` has no claims, so 3 carry claims. This is new here, not a correction.
- **Run 4, `BX:core_thesis`:** its packet says `answered_unadjudicated`; `run4/CORRECTED_OUTCOMES_20261103.json` says degraded. Its content is still `source_bound_claims`: degradation and content are separate questions. The corrected file and the packet both stay as they are.
- **Words map, numbers do not move:** "honest refusal" and "empty" in earlier reports are `insufficient_evidence` here; "no company" is `identity_unresolved`; "halted" with no response is `no_answer`.
- **`operational_failure` in `outcome_counts` also overstates what ran.** It includes cases never run: Run 3's 10 is 1 halted and 9 not run, and Run 6's 12 is 1 halted and 11 not run. Run 5's 1 is the halted case.
- **Scoring is unchanged.** Run 4's rubric already scored an honest refusal 0 for usefulness, matching the rule now stated for future assessments.

## By case

### Run 1

Earlier record: no per-case substantive count reported; docs/ORDINARY_RUN2_PLAN_20261030.md records the halt and the 7 cases not answered.

| Case | Packet status | Application status | Claims | Content | Earlier report | Agrees |
|---|---|---|---|---|---|---|
| NPK:core_thesis | `answered_unadjudicated` | partial | 18 | `source_bound_claims` | None | Not classified |
| NPK:decision_threshold | `answered_unadjudicated` | partial | 4 | `source_bound_claims` | None | Not classified |
| GOOGL:core_thesis | `answered_unadjudicated` | partial | 6 | `source_bound_claims` | None | Not classified |
| GOOGL:decision_threshold | `answered_unadjudicated` | insufficient_claim_evidence | 0 | `insufficient_evidence` | None | Not classified |
| INGR:core_thesis | `halted` | None | 0 | `no_answer` | None | Not classified |
| INGR:decision_threshold | `not_run_after_halt` | None | 0 | `not_run` | None | Not classified |
| NNBR:core_thesis | `not_run_after_halt` | None | 0 | `not_run` | None | Not classified |
| NNBR:decision_threshold | `not_run_after_halt` | None | 0 | `not_run` | None | Not classified |
| AMZN:core_thesis | `not_run_after_halt` | None | 0 | `not_run` | None | Not classified |
| AMZN:decision_threshold | `not_run_after_halt` | None | 0 | `not_run` | None | Not classified |
| MAN:core_thesis | `not_run_after_halt` | None | 0 | `not_run` | None | Not classified |
| MAN:decision_threshold | `not_run_after_halt` | None | 0 | `not_run` | None | Not classified |

### Run 2

Earlier record: offline-review/RUN2_ASSESSMENT_20261030.md: "Full answer" is operational completeness only; every source answer is partial.

| Case | Packet status | Application status | Claims | Content | Earlier report | Agrees |
|---|---|---|---|---|---|---|
| NPK:core_thesis | `answered_unadjudicated` | partial | 19 | `source_bound_claims` | partial, source-bound | Yes |
| NPK:decision_threshold | `answered_unadjudicated` | partial | 4 | `source_bound_claims` | partial, source-bound | Yes |
| GOOGL:core_thesis | `answered_unadjudicated` | partial | 8 | `source_bound_claims` | partial, source-bound | Yes |
| GOOGL:decision_threshold | `answered_unadjudicated` | partial | 4 | `source_bound_claims` | partial, source-bound | Yes |
| INGR:core_thesis | `answered_unadjudicated` | partial | 8 | `source_bound_claims` | partial, source-bound | Yes |
| INGR:decision_threshold | `answered_unadjudicated` | partial | 4 | `source_bound_claims` | partial, source-bound | Yes |
| NNBR:core_thesis | `answered_unadjudicated` | partial | 9 | `source_bound_claims` | partial, source-bound | Yes |
| NNBR:decision_threshold | `answered_unadjudicated` | partial | 4 | `source_bound_claims` | partial, source-bound | Yes |
| AMZN:core_thesis | `answered_unadjudicated` | partial | 8 | `source_bound_claims` | partial, source-bound | Yes |
| AMZN:decision_threshold | `answered_unadjudicated` | partial | 4 | `source_bound_claims` | partial, source-bound | Yes |
| MAN:core_thesis | `answered_unadjudicated` | partial | 8 | `source_bound_claims` | partial, source-bound | Yes |
| MAN:decision_threshold | `answered_unadjudicated` | partial | 4 | `source_bound_claims` | partial, source-bound | Yes |

### Run 3

Earlier record: no answered cases; no substantive count needed.

| Case | Packet status | Application status | Claims | Content | Earlier report | Agrees |
|---|---|---|---|---|---|---|
| SCCO:core_thesis | `identity_unresolved` | None | 0 | `identity_unresolved` | None | Not classified |
| SCCO:decision_threshold | `identity_unresolved` | None | 0 | `identity_unresolved` | None | Not classified |
| BX:core_thesis | `halted` | None | 0 | `no_answer` | None | Not classified |
| BX:decision_threshold | `not_run_after_halt` | None | 0 | `not_run` | None | Not classified |
| LNC:core_thesis | `not_run_after_halt` | None | 0 | `not_run` | None | Not classified |
| LNC:decision_threshold | `not_run_after_halt` | None | 0 | `not_run` | None | Not classified |
| LVS:core_thesis | `not_run_after_halt` | None | 0 | `not_run` | None | Not classified |
| LVS:decision_threshold | `not_run_after_halt` | None | 0 | `not_run` | None | Not classified |
| USCB:core_thesis | `not_run_after_halt` | None | 0 | `not_run` | None | Not classified |
| USCB:decision_threshold | `not_run_after_halt` | None | 0 | `not_run` | None | Not classified |
| BWMX:decision_threshold | `not_run_after_halt` | None | 0 | `not_run` | None | Not classified |
| BWMX:core_thesis | `not_run_after_halt` | None | 0 | `not_run` | None | Not classified |

### Run 4

Earlier record: offline-review/RUN4_ASSESSMENT_20261103.md: 9 verified answers, 3 honest refusals; BX:core_thesis corrected to degraded.

| Case | Packet status | Application status | Claims | Content | Earlier report | Agrees |
|---|---|---|---|---|---|---|
| SCCO:core_thesis | `answered_unadjudicated` | partial | 7 | `source_bound_claims` | verified answer | Yes |
| SCCO:decision_threshold | `answered_unadjudicated` | partial | 3 | `source_bound_claims` | verified answer | Yes |
| BX:core_thesis | `answered_unadjudicated` | partial | 8 | `source_bound_claims` | verified answer | Yes |
| BX:decision_threshold | `answered_unadjudicated` | partial | 3 | `source_bound_claims` | verified answer | Yes |
| LNC:core_thesis | `answered_unadjudicated` | partial | 9 | `source_bound_claims` | verified answer | Yes |
| LNC:decision_threshold | `answered_unadjudicated` | partial | 3 | `source_bound_claims` | verified answer | Yes |
| LVS:core_thesis | `answered_unadjudicated` | partial | 4 | `source_bound_claims` | verified answer | Yes |
| LVS:decision_threshold | `answered_unadjudicated` | partial | 4 | `source_bound_claims` | verified answer | Yes |
| USCB:core_thesis | `answered_unadjudicated` | partial | 4 | `source_bound_claims` | verified answer | Yes |
| USCB:decision_threshold | `answered_unadjudicated` | insufficient_claim_evidence | 0 | `insufficient_evidence` | honest refusal | Yes |
| BWMX:decision_threshold | `answered_unadjudicated` | insufficient_claim_evidence | 0 | `insufficient_evidence` | honest refusal | Yes |
| BWMX:core_thesis | `answered_unadjudicated` | insufficient_claim_evidence | 0 | `insufficient_evidence` | honest refusal | Yes |

### Run 5

Earlier record: offline-review/RUN5_ASSESSMENT_20261105.md: 7 operationally full, 5 substantive, 2 empty, 4 no company, 1 halted.

| Case | Packet status | Application status | Claims | Content | Earlier report | Agrees |
|---|---|---|---|---|---|---|
| SMFG:core_thesis | `identity_unresolved` | None | 0 | `identity_unresolved` | no company | Yes |
| SMFG:decision_threshold | `identity_unresolved` | unresolved_company_identity | 0 | `identity_unresolved` | no company | Yes |
| BNY:decision_threshold | `answered_unadjudicated` | partial | 6 | `source_bound_claims` | substantive | Yes |
| OWL:core_thesis | `identity_unresolved` | None | 0 | `identity_unresolved` | no company | Yes |
| OWL:decision_threshold | `identity_unresolved` | unresolved_company_identity | 0 | `identity_unresolved` | no company | Yes |
| TWST:core_thesis | `answered_unadjudicated` | partial | 7 | `source_bound_claims` | substantive | Yes |
| TWST:decision_threshold | `answered_unadjudicated` | insufficient_claim_evidence | 0 | `insufficient_evidence` | empty | Yes |
| AGEN:core_thesis | `answered_unadjudicated` | partial | 6 | `source_bound_claims` | substantive | Yes |
| AGEN:decision_threshold | `answered_unadjudicated` | partial | 3 | `source_bound_claims` | substantive | Yes |
| FSTR:core_thesis | `answered_unadjudicated` | partial | 6 | `source_bound_claims` | substantive | Yes |
| FSTR:decision_threshold | `answered_unadjudicated` | insufficient_claim_evidence | 0 | `insufficient_evidence` | empty | Yes |
| BNY:core_thesis | `halted` | None | 0 | `no_answer` | halted | Yes |

### Run 6

Earlier record: offline-review/RUN6_RESULTS_20261107.md, as corrected: 1 halted, 11 not run, no answers.

| Case | Packet status | Application status | Claims | Content | Earlier report | Agrees |
|---|---|---|---|---|---|---|
| BP:core_thesis | `halted` | None | 0 | `no_answer` | halted | Yes |
| BP:decision_threshold | `not_run_after_halt` | None | 0 | `not_run` | not run | Yes |
| MNST:core_thesis | `not_run_after_halt` | None | 0 | `not_run` | not run | Yes |
| MNST:decision_threshold | `not_run_after_halt` | None | 0 | `not_run` | not run | Yes |
| CRDO:core_thesis | `not_run_after_halt` | None | 0 | `not_run` | not run | Yes |
| CRDO:decision_threshold | `not_run_after_halt` | None | 0 | `not_run` | not run | Yes |
| LLYVA:core_thesis | `not_run_after_halt` | None | 0 | `not_run` | not run | Yes |
| LLYVA:decision_threshold | `not_run_after_halt` | None | 0 | `not_run` | not run | Yes |
| DGXX:core_thesis | `not_run_after_halt` | None | 0 | `not_run` | not run | Yes |
| DGXX:decision_threshold | `not_run_after_halt` | None | 0 | `not_run` | not run | Yes |
| VIRC:core_thesis | `not_run_after_halt` | None | 0 | `not_run` | not run | Yes |
| VIRC:decision_threshold | `not_run_after_halt` | None | 0 | `not_run` | not run | Yes |
