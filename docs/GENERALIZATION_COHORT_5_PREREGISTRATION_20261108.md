# Generalization cohort 5: pre-registration of a fresh, unexposed cohort

Status: **plan for review only.** No package, approval file, retrieval, merge, deployment or run exists or is authorized by this document. Launch readiness stays false. Run 9 and its results are not revised by anything here.

*Part A (this commit) is written and committed before the selection rule is applied. Part B is added only after it is applied.*

## Part A. Frozen implementation, evidence boundaries, and the rule (fixed before application)

### Frozen implementation

| Item | Value |
|---|---|
| Frozen code (the commit intended for packaging, subject to the wiring amendment below) | `59efed3ec71e51a79fe8db5e6c109b7371f5ff53` on `pilot/run9-answer-fixes` (draft [#379](https://github.com/jjjkinney-art/ClearSignal-Backend/pull/379), do not merge) |
| Tree | `31580fb4c5790e3a11dbf14fbd503d69506f7cc0` |
| `app/` tree | `e3ccf3e3de9b8d1e5c95e1cbb455582b1f244888` |
| `validation/` tree | `6122186765c7b0cdf0b9c0a131a3ef83ce37e187` |
| Source binding | `ee102739d72ebe94c0f4774fbce4397ba62b138b385f1fd9583afc9582700482` (461 files: `app/**/*.py` and `validation/*.py`) |
| Changes since Run 9's frozen `af36f55` | 7 files under `app/` and `validation/` (disclosure-only partial answers, explanation cleanup, Human Capital exclusion, staff-competition exclusion, coverage counts); no limit, quota, question or rubric change |
| Frontend pin | `138d6461a7d6822fd9b27c784a410f55b243a40e` (recorded; re-verified at launch, not here) |
| Runtime | CPython 3.11.9, audited dependencies as in earlier packages |

**The bound source was recomputed three ways and is identical:** from a clean `git archive` of `59efed3` (461 files), from an export of CI's merge ref `9fb20b9`, and from the worktree. The two trees are byte-identical (`git diff` between them is empty).

### CI evidence: the merge ref is not the commit we would package

CI does not test `59efed3` itself. It tests the pull-request merge ref.

| | Commit | Role |
|---|---|---|
| Intended package source | `59efed3ec71e51a79fe8db5e6c109b7371f5ff53` | The commit a package's `revision` would record |
| What CI checked out | `9fb20b9a02ed914e7e9192d4b359b065dc76eec9` = merge of `59efed3` into main `448f5f47f318f1f71702e6deb0af683299fde5de` | Test evidence |

Main's tip is an ancestor of `59efed3`, so the merge adds nothing: the merge ref's tree equals `59efed3`'s, and its source binding is the same value above. CI evidence on the merge ref therefore describes the same bytes, but it is evidence about `9fb20b9`, not a test of `59efed3`'s commit hash. If main moves before packaging, this equivalence must be rechecked.

CI job `128619861108` (`test (py3.11, pinned)`): success. 19,791 tests collected; no FAILED or ERROR line. Pilot child process, cohort `run9`, profile `threshold_filing_v1`: 218 collected, 208 passed, 0 failed, 0 errors, 10 skipped (original-cohort-only tests); **51 of 51 required tests passed, none missing**. The child profile names cohort `run9`; the wiring amendment below must connect the new cohort and obtain its own CI.

### What the live runs did and did not exercise

| Behaviour | Live evidence |
|---|---|
| Oversized-filing recovery | **Exercised** in Runs 7 and 8: each had one real size rejection (BP) that ended as `unanswered_size_rejected`. Run 6 halted on an oversized filing before that handling existed. Run 9 had no size rejection |
| Disclosure-only partial answers and `answered_degraded_unadjudicated` for a thesis case | **Not exercised live.** The behaviour did not exist during any run. Evidence is offline only: replay on retained ledgers and loopback rehearsals. BP's live outcome was under the earlier rule, and its rejected body was not retained, so it cannot be replayed under the new one |
| Cooperative cancellation | **Not exercised.** No filing task was abandoned in Runs 8 or 9. Unverified live |
| Web fallback | **Not exercised.** The pilot never uses it (the fallback setting is off). Unverified |
| IFRS reading | Not implemented. A disclosure-only answer names the taxonomy gap only when retrieval confirmed it |

### Selection rule (written here and in `scripts/select_generalization_cohort_5.py` before it is applied)

- **Procedure:** the cohort 4 procedure (`scripts/select_generalization_cohort.py`) with seed `clearsignal-generalization-5:`. An issuer's rank is `sha256(seed + ticker)`, lowest first.
- **Source:** the SEC `company_tickers.json` as retained in the Run 8 and Run 9 ledgers (sha256 `76b4b2ab…bfe1faec2`, 10,409 rows, identical bytes in both). Ticker, CIK and name only. Nothing is fetched.
- **Buckets:** directory positions 1,001-2,500, 2,501-5,000 and 5,001-9,000, two issuers each, none from the top 1,000. These are positions, not verified company sizes.
- **Eligibility:** a ticker of 1-5 capital letters, and no fund, trust, ETF, acquisition, SPAC, BDC, REIT, partnership, income, portfolio or merger term in the name.
- **Exclusions, by issuer (CIK), which removes every alternate ticker:** every issuer in a pilot Run 1-9 cohort or with any SEC response in a Run 1-9 ledger; every issuer whose ticker, CIK or name appears in `app/`, `tests/`, `validation/`, `docs/` or `scripts/` at `59efed3`. The code base is read at that fixed commit, so a re-run reproduces the same exclusions.
- **No substitution:** an unsupported filer, a missing or oversized filing, a failed identification or a failed answer stays in the denominator of 12. No filing, form or company-facts check is made before or after selection.
- **Naming:** this is generalization cohort 5, to be wired as `run10`. It is unrelated to the older directory `~/clearsignal-pilot/cohort-5`, which holds cohort 2's inputs.

### Questions

The same two templates as cohorts 2-4, with the SEC name verbatim:
- **core_thesis:** "What is the investment thesis for {name}, what supports it, and what could invalidate it? Distinguish reported facts from inference and cite material claims."
- **decision_threshold:** "Which valuation and operating assumptions would make {name} attractive or unattractive? Explain decision thresholds, evidence and uncertainty without inventing figures."

### Criteria (unchanged) and how content is reported

The existing pilot criteria stand exactly:
1. All 12 cases reach a recorded outcome, with no halt.
2. All quotations and figures reconcile.
3. No historical baseline is presented as an investment threshold.
4. At least 8 cases deliver source-bound claims.
5. At least 8 score 1 or higher for usefulness, including at least 3 that score 2.
6. Every unanswered part names the missing evidence.

Content is reported as three kinds, never pooled (`docs/PILOT_ANSWER_CONTENT_REPORTING.md`): financial claims (`source_bound_claims`), disclosure-only content (`source_bound_disclosures_only`) and no substantive answer. Two coverage numbers are always given together:
- **total source-backed coverage:** financial claims plus disclosure-only;
- **the count used for criterion 4:** financial claims only. **Disclosure-only cases are excluded from it.**

Usefulness is scored 0/1/2 with the existing rubric, unchanged, on what each answer actually delivers. A disclosure-only answer is scored like any other: its quoted business and risk statements count under the rubric's components, its stated absence of financial analysis counts under missing-evidence clarity, and it counts toward criterion 5 at whatever score it earns. The scorer records, for each such case, what it delivered. Claim accuracy, delivered content and usefulness stay separate assessments.
