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

## Part B. The selected cohort and the checks run before any wiring (added after the rule was applied)

Part A and `scripts/select_generalization_cohort_5.py` were committed and pushed as `788543a` before this part existed. The rule was then applied, twice, to the retained directory (`docs/generalization_cohort_5_selection.json`, sha256 `eda0d55e…877ac`; the second run was identical byte for byte). Excluded by CIK: 30 issuers from pilot Runs 1-9 cohorts or with any retained SEC response, and 780 more whose ticker, CIK or name appears in the code base at `59efed3`.

| Bucket | Position | Ticker | CIK | SEC name | Alternate tickers |
|---|---|---|---|---|---|
| 1,001-2,500 | 2018 | NWBI | 1471265 | Northwest Bancshares, Inc. | none |
| 1,001-2,500 | 1241 | VBREY | 1000377 | Vibra Energia S.A./ADR | none |
| 2,501-5,000 | 3576 | GALT | 1133416 | GALECTIN THERAPEUTICS INC | none |
| 2,501-5,000 | 3918 | AUDC | 1086434 | AUDIOCODES LTD | none |
| 5,001-9,000 | 8931 | FORFF | 1666175 | Fortis Inc. | FTS |
| 5,001-9,000 | 7785 | IFCNF | 2035057 | Inficon Holding AG/ADR | IFHLY |

**Every selected issuer stays**, whatever its filings turn out to be. No filing, form or company-facts check was made. Alternate tickers exist only because the directory lists them for the same CIK; they are excluded as issuers and are listed here for completeness.

**Prior exposure:** none of the six appears by ticker, alternate ticker, CIK or name in the code base at `59efed3` (by construction), in the assistant's memory, or in any pilot record other than whole-directory copies and whole-directory identity maps. Every file version reachable from all 411 backend and 104 frontend local branch heads was searched once: 0 matches, against positive controls found in 1,157 and 102 versions. The local branch heads were last fetched on 2026-10-30 (backend), so the search covers local refs only. No filing, company facts or filing list for these issuers has been retrieved or read.

### Offline checks (`docs/generalization_cohort_5_offline_checks.json`)

Run offline through the guard against `59efed3`, with no network request and no guard refusal. The classifier and resolver are the unmodified frontend files at `138d6461` (sha256 verified against that commit; runner differs only in a `.ts` import suffix; Node 24.15.0).

| Result | Cases |
|---|---|
| `company_analysis`, correct issuer, routed to research | NWBI both, VBREY decision_threshold, GALT both, AUDC both, FORFF both, IFCNF decision_threshold (10 of 12). FORFF resolves through its alternate ticker FTS and IFCNF through IFHLY; the CIK matches |
| **`investing_education`, no company, `general_finance` route** | **VBREY:core_thesis and IFCNF:core_thesis (2 of 12)** |

### Blockers before wiring

1. **Two cases classify as `investing_education`.** Both names end in "/ADR", which the pinned frontend resolver does not recognise, so the question falls to the education pattern and the backend takes the general route, which attempts a model call (`run_general_finance_agent`). The pilot's zero-model boundary does not allow that. This has a precedent: in Run 5 the pinned frontend sent `BNY:core_thesis` as `investing_education` and the run halted there; amendment 2 moved that case last so it cost no other case. Also, `validation/ordinary_frontend_intents.py` currently fixes `CASE_INTENTS` to `company_analysis` for every case ("what the pinned classifier returns"), which would be false for these two, so wiring must record the intents the classifier actually returned. The cohort is not changed: no substitution. Options for the owner, not decided here:
   - **A (recommended, the Run 5 precedent):** wire the two cases with their true intent and move both last, so the other ten cases complete; the first of them is predicted to halt the run, the second to be `not_run_after_halt`, and both stay in the denominator. Criterion 1 is then predicted to fail by design, and that prediction is recorded in advance.
   - **B:** fix the frontend classifier and resolver for "/ADR" names, re-pin, and re-classify. This changes the pinned frontend, which is outside the backend freeze, and needs its own review.
   - **C:** send `company_analysis` for these two regardless of what the frontend returns. Not recommended: it would measure a route production does not take.
2. **Wiring changes the source binding.** A `validation/` amendment connecting this cohort as `run10` (cases, intents, question digest, synthetic registrants, expectations, profile) changes `ee102739…0482`, needs its own CI (the child profile names `run9` today), and produces a new frozen commit. The binding above is the frozen implementation's; the packaged binding will differ by exactly the wiring.
3. **CI evidence is on the merge ref.** It matches `59efed3` only while main stays an ancestor of the branch. If main moves, recheck before packaging.
4. **Launch conditions are not verified here:** the frontend deployment and hashes, host power and condition, network configuration, the package, the approval and the owner's confirmations all come later.

### Predictions (stated before any data; filer forms are unchecked general knowledge)

- **Identity and routing (verified offline):** 10 of 12 cases route to research for the correct issuer; 2 route to the general (model) path.
- **Filer forms (not checked):** NWBI and GALT are expected to file 10-Ks (NWBI a bank; GALT a clinical-stage company, so a revenue comparison may be absent and a disclosure-only answer is plausible). AUDC is expected to file a 20-F and FORFF a 40-F. VBREY and IFCNF are ADR names that may have no SEC periodic report at all. Unsupported-form, missing-filing and oversized-filing outcomes are all plausible and all stay in the denominator.
- **Requests:** about 5 per thesis case and 4 per threshold case for 10-K filers, fewer where no document is read.
- **Not predicted:** filing sizes, completion, content counts, accuracy or usefulness.

### What this document does not authorize

No wiring, package, approval file, retrieval, execution, merge or deployment. Run 9, its scores and its consumed approval are unchanged.
