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

## Amendment 1 (2026-11-08): the frontend routing defect, a candidate fix, and the routing regression cases

Recorded before any wiring, package, approval or retrieval. **Unchanged by this amendment:** the six selected issuers, the twelve exact questions in their registered order (`docs/generalization_cohort_5_cases.json`, sha256 `a56e53f7…11e4f6`), the six success criteria, the content-reporting split and the usefulness rubric. No issuer is substituted. Run 9 and its results are not touched.

**The original result is preserved.** The pinned frontend `138d6461` classified 10 of 12 questions as `company_analysis`; `VBREY:core_thesis` and `IFCNF:core_thesis` came back `investing_education` and took the general (model) route. That record (`docs/generalization_cohort_5_offline_checks.json`, and the local `intents.jsonl` and `identity.jsonl`) is not edited and stands as the pinned-frontend result.

**Diagnosis.** SEC registers an American depositary receipt program as `<registrant>/ADR`. The marker is captured with the final token, so the registrant's legal form was no longer at the end of the subject, and the legal-form test failed (343 distinct names in the retained directory end `/ADR`, 8 end `/ADR/`). The question then fell to the education pattern.

**Candidate fix (not merged, not deployed, not pinned).**

| | |
|---|---|
| Repository and PR | `jjjkinney-art/Ai-Intelligence-interface` #91, draft, do not merge |
| Branch and commit | `fix/adr-suffix-company-names`, `a2e768ce5990bc94ee840e6b07a069097302e09b` (one commit on `main` = `138d6461`) |
| Change | `queryIntent.ts` +10 / -2 and `queryIntent.test.ts` +63: the legal form is read from the subject without a trailing `/ADR` or `/ADR/` marker. No issuer is named and no intent is forced |
| Candidate classifier sha256 | `9f8b1e87fc9f9353bc2c53d9ee0768596b9d6fb54d100074d6381e5540dd340a` (pinned: `6ef10de3…1dc1df38`) |
| Resolver | unchanged from the pin (`6fa4e195…38542`) |
| Frontend CI (merge ref `220908c`, the merge of the commit into `138d6461`, tree `e3a85ea7…` identical to the commit's) | success, job `128633739881`, 2 m 27 s: 371 of 371 unit tests, 23 of 23 component test files, typecheck and build passed |

Evidence on the classifier alone: over all 8,003 distinct registered names and both question templates (16,006 questions), 288 change, all to `company_analysis`, all for names ending in the marker, none for any other name. Genuine education questions about ADRs, and a marker after no legal form, keep their route (tests added). Known limits left alone: 61 ADR names with other forms (lowercase "plc", the deliberately excluded "AB"/"SE", no legal form); a slash-terminated "/ADR/" name in the "would make … attractive" pattern; and two unrelated ADR phrasings that were already misrouted on `main`.

**Post-fix offline checks** (`docs/generalization_cohort_5_offline_checks_frontend_amendment.json`; no network, no guard refusal): all 12 questions classify as `company_analysis` and the backend identity check routes all 12 to research for the intended issuer (CIK verified), including `VBREY:core_thesis` and `IFCNF:core_thesis`. FORFF still resolves through FTS and IFCNF through IFHLY, same CIKs.

**Disclosure: VBREY and IFCNF are now routing regression cases.** They were selected by the rule, not for this property, and their misrouting was found before any retrieval. Their routing outcome is therefore known; their filing content is not: no filing, form, company-facts record or filing list for either issuer has been retrieved or read, and they stay in the denominator. A passing routing check for them is not evidence about their answers.

**What stays undecided (owner):**
- Whether to merge, deploy and re-pin the frontend. Until then the pilot's pin remains `138d6461` and, under that pin, blocker 1 above stands (the Run 5-style option A).
- If the fix is adopted: a new pin changes the wiring's frontend digests (pin commit, classifier sha), `CASE_INTENTS = company_analysis` for all twelve becomes a true statement, and the question digest is unchanged because the questions are. The frontend preview environments that Vercel creates automatically for a pull request are not a production deployment and do not change the pin.

**Backend application freeze:** unchanged. Source binding `ee102739…0482` (461 files), `app/` and `validation/` identical to `59efed3`. This amendment adds documentation only.

## Amendment 2 (2026-11-08): frontend merged and deployed, re-pin, and wiring as `run10`

Before any package, approval, retrieval or run. **Unchanged:** the six selected issuers, the twelve exact questions in their registered order (`docs/generalization_cohort_5_cases.json`, sha256 `a56e53f7…11e4f6`, byte-identical to `tests/ordinary_run10_cases.json`), the success criteria, the content-reporting split, the usefulness rubric, every limit, quota and timing value of `threshold_filing_v1`, and the backend `app/` tree. Run 9 and its results are not touched. The original 10-of-12 routing record and Amendment 1 are preserved byte for byte (their sha256 values are pinned by a test).

**Merge (owner-authorized on stated conditions).** Frontend PR #91 was squash-merged only after re-verifying that its head was `a2e768ce5990bc94ee840e6b07a069097302e09b`, its base `main` was still `138d6461a7d6822fd9b27c784a410f55b243a40e`, there were no conflicts, and all four checks were green (Frontend CI plus the Vercel checks). The merge produced `main` = **`77c33bbbb0c530e01f74b0d51502fabdf6d1ce12`**, whose tree (`e3a85ea7641b7b46ae7c6003d855107bfb5c694d`) is identical to the reviewed commit's, with classifier sha256 `9f8b1e87fc9f9353bc2c53d9ee0768596b9d6fb54d100074d6381e5540dd340a` and resolver sha256 `6fa4e195816df8c09a6439c86fb4c41d3a9d60990745cb877f492a5d7dd38542` (unchanged from the previous pin). A squash gives the code a new commit hash; the reviewed code and the deployed code are the same bytes.

**Production verification (both Vercel projects).**

| Project | Production deployment | Commit |
|---|---|---|
| `ai-intelligence-interface` | Production, Deployed (completed) | `77c33bbbb0c530e01f74b0d51502fabdf6d1ce12` |
| `project-qxbjx` | Production, Deployed (completed) | `77c33bbbb0c530e01f74b0d51502fabdf6d1ce12` |

Evidence: the repository's deployment records for both Production environments name that commit and `main`'s head; the Vercel dashboard's project list shows both projects' latest deployment as the #91 commit; and the new production deployments answer `/`, `/analyze`, `/login` and `/api/health` exactly as the previous (`138d6461`) production deployments did, on both projects. **Limits:** the classifier is bundled only in the sign-in-gated `/analyze` route, so the served bundle itself was not inspected, and the Vercel dashboard's deployment-detail pages did not render in the browser; the match rests on the deployed commit's source hashes. **Observation, not caused by this change:** on `project-qxbjx`, `/analyze` and `/login` return `MIDDLEWARE_INVOCATION_FAILED` on the new and on the previous production deployment alike; the main project redirects `/analyze` and serves `/login` normally.

**Re-pin (cohort 5 only).** Frontend `77c33bbbb0c530e01f74b0d51502fabdf6d1ce12`, classifier `9f8b1e87…340a`, resolver `6fa4e195…38542`. Every consumed cohort keeps `138d6461`: the contract, profile and frontend digests of runs 6 and 9 are unchanged by the wiring (run 6: `10b87f73…6c18`, `66cbeee5…1899`; run 9: `df3a0bee…36cd`, `de5ee19e…aa6e`, frontend `2f9c11c5…0e06`), and a test pins them.

**Offline checks with the deployed commit's own files** (`docs/generalization_cohort_5_offline_checks_deployed.json`; no network, no guard refusal): all 12 questions classify as `company_analysis` and the backend identity check routes all 12 to research for the intended CIK. This equals the candidate-commit result. FORFF resolves to FTS and IFCNF to IFHLY (same CIKs).

**A finding the offline check could not show: alternate tickers.** The loopback rehearsal of the wired cohort halted at `FORFF:core_thesis` with `invalid_response`. The native ledger, and the export that re-checks it, accepted an answer only if its `company` was exactly the case's issuer ticker (or empty). For FORFF and IFCNF the application answers with the other ticker SEC lists for the same CIK (FTS, IFHLY), so a live run would have halted at case 9. Corrected narrowly, in `validation/` only: one shared function (`answer_names_issuer`) accepts the case's own ticker, no company, or another ticker that **the SEC directory retained by this very run** lists under **the case's registered CIK**. A ticker listed under a different CIK, an unlisted or malformed ticker, any ticker when no directory was retained, and an unpadded CIK are still drift and halt. This does not loosen identity: it is checked by CIK against SEC's own record rather than by ticker spelling, and every earlier cohort answers with its own ticker, so its behaviour is unchanged. Tests cover each accepted and refused case. Three other tests that assumed the issuer's own ticker now state the resolved ticker explicitly.

**Wiring (`validation/`, six files):** the cohort and its profile (`run10`, `APPROVED_COHORT = 'run10'`), the per-cohort frontend pin and question digest (`6dba0677…00a3`), the case-record projection digest (`2e724123…1aaf`), the synthetic registrants (six issuers plus directory-only FTS and IFHLY rows), and the shared identity rule. The rehearsal fault target is `GALT:core_thesis` (the third issuer; its name has no comma, unlike NWBI's, which the application's named-subject rule does not accept for business sentences). Evidence templates were regenerated.

**Frozen implementation after wiring.**

| | |
|---|---|
| Backend `app/` tree | `e3ccf3e3de9b8d1e5c95e1cbb455582b1f244888`, unchanged from `59efed3` |
| Source binding | `ea576d2578917337964c1d80dcabd7de99a2d9e11d42fde26bd08dd72f1c5074` (461 files; `59efed3`'s was `ee102739…0482`, the difference being exactly the six `validation/` files above) |
| Frontend pin | `77c33bbbb0c530e01f74b0d51502fabdf6d1ce12` |

**Not done, and not authorized by this amendment:** no package, execution configuration, cost or retention evidence, approval file, new SEC retrieval, live run, backend merge or backend deployment.
