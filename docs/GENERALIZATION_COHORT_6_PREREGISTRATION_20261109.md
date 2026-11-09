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
