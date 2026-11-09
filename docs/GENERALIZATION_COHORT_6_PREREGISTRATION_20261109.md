# Generalization cohort 6: pre-registration of a fresh, unexposed cohort

Status: **Part A, written and committed before the rule is applied.** Nothing in this document selects, wires,
packages, approves or runs anything. Draft #381 stays a do-not-merge draft; this lives on its own branch
(`cohort6/preregistration`) so #381's head is not moved.

## Part A. Frozen implementation, evidence, and the rule (fixed before application)

### Frozen implementation

| | |
|---|---|
| Commit | `26d2859c49216809902b9d2d042e435d93e6f50a` (head of draft #381, `quality/going-concern-and-drivers`) |
| Tree | `f7459031c82f42a67d7e87b3ed30a2fa0a2ca6a5`; `app/` tree `b3edb44e6600c3dbd182485ec3023eacd9420dfe`; `validation/` tree `7d5077a8b996ede7906a449b111d58251b659e05` |
| Source binding (`app/**/*.py` + `validation/*.py`) | `27f21d9109b35b063c943dbe127a77d4515476bdf7226bf5f2808518c83577cd` (464 files); **unchanged** from `76d1512` (`26d2859` changed only one test file) |
| What it adds over Run 11's `0540938` | a going-concern reader (`app/services/going_concern_disclosure.py`), a chart lead-in rule for management's stated drivers (`current_period_explanation.clause_starts`), and bank deposit and net-loan comparisons; see `docs/GOING_CONCERN_DRIVERS_AND_BANK_BALANCES_20261109.md` |
| Not changed | the registration-only rule, the pilot boundary, every limit, quota and timing value of `threshold_filing_v1`, and cohort 5's records |
| Frontend pin (unchanged) | `77c33bbbb0c530e01f74b0d51502fabdf6d1ce12` (classifier `9f8b1e87…340a`, resolver `6fa4e195…38542`) |

### CI evidence for the frozen commit (merge ref, not the commit itself)

CI runs on the pull request's merge ref. For `26d2859`: run 42548421588, job 128938378406, `test (py3.11, pinned)`: **success**.
Merge ref `7e4f4ad` (parents `448f5f4` and `26d2859`) has tree `f7459031…`, **identical** to the branch tree, so CI tested exactly this
code. Profile child report: cohort `run10`, profile `threshold_filing_v1`, 226 collected, **216 passed, 0 failed, 0 errors, 10 skipped**;
**54 required tests, none missing or not passed**; return code 0. 523 per-file runs finished; one exited 5 (a file whose only test is skipped,
allowed by the script), the rest 0. The first run on `76d1512` failed one test (`TestRetrievedEvidenceSchema::test_serialization`, which
enumerates the evidence schema); that was a one-line test update, reported before it was made. Local timing failures seen earlier coincided
with high machine load; their cause was not established.

### What is *not* verified about the frozen code
It has never run live. The going-concern classifier was tested on one retained issuer's filings plus constructed cases; the lead-in rule on one
filing; the balance comparisons on one bank. Cooperative cancellation and web fallback remain untested live. Broad launch readiness and a
~95% accuracy target remain unverified. Run 11's package is bound to `0540938` and is **not valid** for this code.

### Selection rule

Applied by `scripts/select_generalization_cohort_6.py` (committed with this document, before it is applied), which reads only the retained
SEC company directory and the exclusion lists. It reads no filing, no company facts and no answer-bearing source, and makes no request.

* **Directory:** `company_tickers.json` as retained in the Run 11 ledger, sha256 `a04725d9ea575489715bd16544f1cdcd420080fd81b8d8779dbb5ee19cdc62cb`
  (797,279 bytes, 10,419 rows). It is newer than the one cohort 5 used (`76b4b2ab…`, 10,409 rows) and is chosen for that reason alone, before any draw.
* **Seed:** `clearsignal-generalization-6:`; an issuer's rank is `sha256(seed + ticker)`, lowest first.
* **Buckets (directory position, not verified size):** 1,001 to 2,500, 2,501 to 5,000, 5,001 to 9,000; two issuers each; none from the top 1,000.
* **Eligible:** a ticker of 1 to 5 capital letters, and none of fund, trust, ETF, acquisition, SPAC, BDC, REIT, partnership, income, portfolio or
  merger in the registrant name.
* **Excluded by CIK, which removes every alternate ticker of an issuer:** (a) every issuer in a pilot Run 1 to 11 cohort, or with any SEC response in a
  Run 1 to 11 ledger (the request records and ledgers); (b) every issuer whose ticker, CIK or name appears in `app/`, `tests/`, `validation/`, `docs/`
  or `scripts/` at the frozen commit above. One issuer once, whatever its ticker.
* **No substitution.** Whatever is selected stays in the 12-case denominator even if its filing is oversized, missing, of an unsupported form,
  unreadable, in another currency, or has no company facts, and even if a pre-wiring check flags a risk.
* **Reproduction:** the rule is applied twice; the two outputs must be byte-identical.
* **Questions:** the two registered templates used for cohorts 3 to 5, with the registrant's SEC name; order: each issuer's thesis then threshold
  question, issuers in bucket order.

### Criteria (unchanged) and how content is reported

The existing six criteria stand exactly:
1. All 12 cases reach a recorded outcome, with no halt.
2. All quotations and figures reconcile.
3. No historical baseline is presented as an investment threshold.
4. At least 8 cases deliver source-bound claims.
5. At least 8 score 1 or higher for usefulness, including at least 3 that score 2.
6. Every unanswered part names the missing evidence.

Content is reported as three kinds, never pooled: financial claims (`source_bound_claims`), disclosure-only content
(`source_bound_disclosures_only`) and no substantive answer. Total source-backed coverage and the count used for criterion 4 (financial claims
only; disclosure-only cases excluded) are always given together. `unanswered_registration_only` cases are reported apart as their own stratum and count
as unanswered. Run 11's original scores, assessment and consumed approval are preserved and are not rescored; a later run is reported apart from it.

### Assessment protocol (additions that read the existing rubric strictly; no criterion changes)

1. **A verified figure is not an explanation.** Report separately, per answer with financial claims: (a) the figures verified (quotation, figure, derived
   value); and (b) for each headline movement, whether a management-stated driver is bound to it, with its period and attribution checked, or the
   movement is unexplained. The usefulness rubric's second component asks for an issuer-disclosed risk or management-stated driver; a verified number
   alone does not satisfy it. Report the count of explained and unexplained headline movements.
2. **Material omissions are reported separately from usefulness** (up to five per case; each classified present, retained but omitted, or missing from the
   retained evidence), as in earlier cohorts.
3. **A mandatory going-concern check for every case with a retained current periodic filing.** Scan that filing for substantial-doubt language by an
   independent pass (a plain search for "substantial doubt" and "going concern", read by the scorer), not by the application's own classifier, and
   record one of: no such statement; a current disclosure the answer states; **a current disclosure the answer missed** (a material omission, reported
   on its own line); or only boilerplate or historical text. Report missed disclosures by name.
4. **Financial and disclosure-only coverage are never merged**, and "insufficient evidence", "registration-only", "halted" and "not run" are
   four different non-answers, each reported by name.
5. Scoring remains model-assisted by the same model that wrote the code: not independent validation.

### What this document does not authorize
No wiring of a cohort, no new SEC retrieval, no package, approval, live run, merge or deployment. A later amendment would have to do each of those, in the
open, before it happens.

## Part B. The selected cohort and the checks run before any wiring (added after the rule was applied)

The rule and seed were committed first (`bf79e6f36fc54896da457c27351fd67590609bdc`) and then applied twice through
`scripts/select_generalization_cohort_6.py` under the offline guard (no network); the two outputs are byte-identical, sha256
`1935ee86e2932c1804d124adb96f7e19174bbb52ae653717819fa85eb6601206` (`docs/generalization_cohort_6_selection.json`). Exclusions: 36 CIKs of earlier cohorts or with any SEC response in a Run 1 to 11 ledger, and
782 further CIKs named in the code base at `26d2859`.

### The cohort (no substitution; all 12 cases stay in the denominator)

| Bucket | Directory position | Ticker | CIK | SEC name |
|---|---|---|---|---|
| mid | 1,822 | ERO | 1853860 | Ero Copper Corp. |
| mid | 2,256 | MGRT | 2033377 | Mega Fortune Co Ltd |
| small | 3,045 | MYGN | 899923 | MYRIAD GENETICS INC |
| small | 3,110 | SUPV | 1517399 | Grupo Supervielle S.A. |
| micro | 8,771 | FMSTW | 1935418 | Foremost Clean Energy Ltd. (the directory also lists `FMST` under this CIK) |
| micro | 6,336 | OPTT | 1378140 | Ocean Power Technologies, Inc. |

Twelve questions (`docs/generalization_cohort_6_cases.json`, sha256 `f271e20ee68f040eeb0da4d145f3351f049d899fc105f50fe9d8685cea0ea7cb`): each issuer's thesis then threshold question, in that order.
No run ID, output path, package or wiring exists.

### Exposure checks (all passed)
1. **By CIK (the rule):** none of the six CIKs is in an earlier cohort, and every alternate ticker of an issuer is excluded with it. The directory lists
   one alternate for a selected CIK (`FMST` beside `FMSTW`); neither is a studied ticker.
2. **Retained ledgers:** none of the six CIKs appears in any SEC URL retained in the Run 1 to 11 ledgers (24, 60, 2, 59, 34, 3, 11, 42, 52, 11 and 37 URLs).
3. **Every reachable file version, all branches:** the backend repository (417 refs, 4,089 text files, 1,164 positive-control files) and both frontend clones
   (106 refs, 724 files each) hold **no** path that mentions any selected ticker, name or CIK. The scan is `offline-review/cohort6/exposure6.py`.

### Offline identity and routing (frozen backend app tree; pinned frontend classifier; nothing retrieved)
All 12 questions classify `company_analysis` (classifier at `77c33bbb`, sha256 `9f8b1e87…340a`; the Node runner copy differs by one import-extension line, the other
132 lines identical). Backend routing: **10 of 12 reach research and the correct issuer.** `FMSTW:core_thesis` and `FMSTW:decision_threshold` return **no company**
(`entity_suggestion` / `company_identity_clarification`). Cause: the same-CIK rule discounts only five-letter `…F` foreign ordinary lines, so a warrant line makes `FMST` and
`FMSTW` two share classes and the resolver abstains. In the pilot that is `identity_unresolved` with no SEC request, not a halt. Record:
`docs/generalization_cohort_6_offline_checks.json` (sha256 `b20e4f31c604c518a85c22e9d8fba0ea4d9be2c04def6587d3b06a737de275c5`).

### Risks flagged before wiring (they stay in the denominator; none is a reason to substitute)
"Checked" means observed offline in this document; "unchecked" means general knowledge, not verified, since no filing or facts were read.

| Issuer | Risk | Basis | In the pilot |
|---|---|---|---|
| FMSTW (2 cases) | Identity not resolved (warrant line beside the common line) | **checked** | `identity_unresolved`, no SEC request; 2 of 12 cases cannot deliver a claim |
| ERO | Canadian cross-border (40-F) filer; the annual-disclosure producers read only 10-K and 20-F; IFRS reporter, so company facts may be absent or not US-GAAP | unchecked | if its company-facts request returns an error, the registration-only rule does not apply to a registrant that files 40-F and 6-K, so the request failing **halts the run at case 1, leaving 11 cases not run** |
| MGRT | A very recent registrant (a high CIK); may have no annual report and no XBRL company facts yet | unchecked | the same halt mechanism, at case 3 |
| SUPV | Argentine bank filing 20-F in IFRS and a non-USD currency | unchecked | most likely an insufficient-evidence or disclosure-only answer, not a halt, if company facts exist |
| MYGN, OPTT | US domestic filers; OPTT has an April fiscal year-end, a comma in its name (the named-subject rule's known gap) and small revenue | unchecked | ordinary risks: oversized or unreadable filings, thin comparisons |
| Any | A facts or document request that is issued and fails halts the run; later cases are then not run | checked (design) | a halt at case 1 or 3 would fail criterion 1 and leave 9 to 11 cases unobserved |
| Any | A current going-concern disclosure the answer misses | unchecked | scored by the protocol above, from the retained filing |

**Criteria 4 and 5 are structurally hard for this draw.** With 2 cases already unresolved and the foreign-filer risks above, reaching 8 of 12 cases with source-bound
claims needs nearly every domestic and foreign case to deliver, which is unlikely. This is recorded now, not after the data.

### Predictions (stated before any data; filer forms are unchecked general knowledge)
* **Identity:** 10 of 12 research with the correct issuer, 2 unresolved (observed offline above, not a prediction).
* **Forms:** MYGN and OPTT 10-K; ERO a 40-F; SUPV a 20-F; MGRT and FMSTW uncertain.
* **Not predicted:** whether the run completes, filing sizes, content counts, figures, accuracy or usefulness.

### Options, none applied (the cohort is fixed whatever is chosen)
(a) Accept the draw as registered. (b) Design, without code, how a registrant with no company facts that is not registration-only should be handled, and whether a warrant line
beside a common line should resolve to the common symbol; either would need its own tests, a new package and a fresh approval, and cannot change this cohort. Neither is done here.

### What this document does not authorize
No wiring of this cohort, no new SEC retrieval, no run identity, package, approval, live run, merge or deployment.
