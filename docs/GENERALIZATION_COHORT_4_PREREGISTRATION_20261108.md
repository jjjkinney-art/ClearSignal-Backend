# Cohort 4: pre-registration of a fresh, unexposed cohort

Status: **plan for review only.** No package, approval file, retrieval, merge, deployment or run exists or is authorized by this document. Launch readiness stays false.

## Frozen implementation

| Item | Value |
|---|---|
| Frozen code | `5410eebcd24800943be7425ddc4401f7f7a817a5` on `pilot/run8-answer-quality` (draft [#378](https://github.com/jjjkinney-art/ClearSignal-Backend/pull/378), do not merge) |
| Tree | `78cf8a7831cd6c8e317671b111bfbb8396c5b24e` |
| `app/` tree | `4940dc839ebbb3aedbcfac865df37440455f0de7` |
| `validation/` tree | `c626312545068538fe39c64a0d71c8df9e70d94a` |
| Source binding | `d5806966f363ce5166fa2eccc3aaaf09f19405a1a4f5405d62c2dc94bb262cc8` (460 files, recomputed independently from an export) |
| CI at that commit | Job 128359647404: success, child 207 passed, 0 failed, 10 skipped, 51 of 51 required |
| Frontend pin | `138d6461a7d6822fd9b27c784a410f55b243a40e` |

**Known non-blocking warning:** two CI annotations, "Event loop is closed", come from `tests/test_services/test_scenario_seed_builder.py`. A file this branch does not change leaves an aiosqlite worker running after its event loop closes. The tests pass, and it is not fixed here.

**Any change under `app/` invalidates this plan.** The pilot contract binds cohort `run6`. Running this cohort needs a declared `validation/` amendment that wires its cases, digests and approved cohort, and that amendment needs its own CI before any package.

## Selection (fixed before it was applied; no filing was inspected)

- **Procedure:** `scripts/select_generalization_cohort_4.py` is the cohort 3 procedure with seed `clearsignal-generalization-4:`. It was committed in `8de7615` before it was applied. Output: `docs/generalization_cohort_4_selection.json`. A second run reproduced it byte for byte.
- **Source:** SEC `company_tickers.json` as retained in the Run 8 ledger (sha256 `76b4b2ab…bfe1faec2`, 10,409 rows). Ticker, CIK and name only. Nothing was fetched.
- **Buckets:** directory positions 1,001-2,500, 2,501-5,000 and 5,001-9,000, two issuers each, none from the top 1,000. These are **positions, not verified company sizes**.
- **Eligibility:** a ticker of 1-5 capital letters, and no fund, trust, ETF, acquisition, SPAC, BDC, REIT, partnership, income, portfolio or merger term in the name.
- **Exclusions by issuer (CIK),** which remove every alternate ticker:
  - every issuer in a Run 1-8 cohort or with any SEC response in a Run 1-8 ledger: 24 issuers;
  - every issuer whose ticker, CIK or name appears in `app/`, `tests/`, `validation/`, `docs/` or `scripts/` at `5410eeb`: 779 more.

| Bucket | Position | Ticker | CIK | SEC name | Alternate tickers |
|---|---|---|---|---|---|
| 1,001-2,500 | 1510 | CNK | 1385280 | Cinemark Holdings, Inc. | none |
| 1,001-2,500 | 2002 | COHU | 21535 | COHU INC | none |
| 2,501-5,000 | 2577 | TRIP | 1526520 | TripAdvisor, Inc. | none |
| 2,501-5,000 | 2989 | LXRX | 1062822 | LEXICON PHARMACEUTICALS, INC. | none |
| 5,001-9,000 | 7441 | MRX | 1997464 | Marex Group Ltd | none |
| 5,001-9,000 | 5479 | DCGO | 1822359 | DocGo Inc. | none |

**No substitution.** An unsupported filer, a missing or oversized filing, a failed identification or a failed answer stays in the denominator of 12.

**Prior exposure:** none of the six appears by ticker, CIK or name in the code base at `5410eeb` (by construction), in the assistant's memory, or in any pilot record other than whole-directory copies and identity maps covering every listed issuer. Every file version reachable from all 409 backend and 104 frontend branches, including history, was searched once: 0 matches, against a positive control (MNST or AAPL) found in 1,149 and 102 versions. No filing, company facts or filing list for these issuers has been retrieved or read.

## Questions

The same two templates as cohorts 2 and 3, with the SEC name verbatim (`docs/generalization_cohort_4_cases.json`):
- **core_thesis:** "What is the investment thesis for {name}, what supports it, and what could invalidate it? Distinguish reported facts from inference and cite material claims."
- **decision_threshold:** "Which valuation and operating assumptions would make {name} attractive or unattractive? Explain decision thresholds, evidence and uncertainty without inventing figures."

## Offline checks (`docs/generalization_cohort_4_offline_checks.json`)

Rerun at `5410eeb` with no network and no guard refusals:
- **Classification:** the unmodified classifier and resolver from frontend `138d6461` return `company_analysis` for all 12.
- **Identity and routing:** all 12 cases reach research for the correct issuer. None resolves no company, a wrong issuer or the general route.

## What counts as a useful answer (defined before any filing is seen)

Each answered case is judged on four components:

1. **Company-specific analysis:** statements about this issuer's own business, segments or results. Generic sector prose does not count.
2. **Material risks or drivers:** at least one issuer-disclosed risk or management-stated driver that bears on the question, rather than boilerplate.
3. **Supported claims:** every quotation and figure traceable to a retained SEC source.
4. **Clear account of missing evidence:** the answer says what it could not establish and why, naming the missing input. Examples: a share price and multiple for a valuation boundary, or a filing that was too large or late.

**Usefulness, 0/1/2, scored for all 12 cases:**
- **2:** components 1-3 are present at decision-relevant depth (more than headline figures), and component 4 is clear.
- **1:** component 3 holds, with some of 1 or 2, but the analysis is thin, or the core of the question is left open with a clear account of why.
- **0:** no substantive, supported content.

An insufficient-evidence response, an unresolved identity or a halted or unrun case scores 0. Its missing-evidence clarity is reported separately, as a yes or no.

**Thresholds:** a historical monitoring baseline presented as an investment threshold, a buy or sell boundary, or a target counts as an individual error. A baseline must be labelled as a baseline. Where no threshold can be supported, the answer must name the missing inputs and state no number.

## Assessment, reported separately and never pooled

1. **Operational completion:** `cases`, `outcome_counts`, requests, halts, size rejections, abandonments, stage timings and host readings.
2. **Delivered content:** `answer_content` per case.
3. **Claim accuracy:**
    - mechanical support of quotations, figures and derived values;
    - wrong figures;
    - unsupported statements;
    - baseline-as-threshold errors.
4. **Usefulness:** 0/1/2 for all 12, with missing-evidence clarity alongside.
5. **Research quality,** under the existing rubric (0/1/2 on company specificity, material risks, explanations of change, monitoring criteria and citation support), plus up to five material omissions per case.

No pooled score or pass rate. Results are compared with these criteria and the predictions, including where either is wrong.

## Predictions (stated before any data)

- **Identity:** 12 of 12 correct issuer.
- **Requests:** about 5 per thesis case and 4 per threshold case for 10-K filers. MRX is predicted to file a 20-F, which is unchecked general knowledge; if so, it gets fewer document requests and fewer comparisons.
- **Not predicted:** filing sizes, completion, content counts, figures, accuracy or usefulness. Any filing may be oversized; any host may throttle.

## Proposed success criteria (for review, not yet agreed)

| Area | Proposed criterion |
|---|---|
| Operational | All 12 cases finish, with no halt |
| Claim accuracy | All quotations verbatim; every figure and derived value reconciles; no wrong figure; no baseline presented as a threshold |
| Delivered content | At least 8 of 12 cases with source-bound claims |
| Usefulness | At least 8 of 12 cases score 1 or more, and at least 3 score 2 |
| Missing evidence | Every case with an unanswered part names what is missing |

A run that misses any criterion is reported as such. Meeting them would not establish launch readiness.

## What this evaluation can and cannot establish

**Can:**
- how this frozen version behaves operationally on six unexposed, mostly smaller issuers;
- whether its delivered claims are mechanically supported;
- model-assisted usefulness on these 12 cases;
- whether the Run 8 answer-quality rules hold up on filings they were not tuned on.

**Cannot:**
- statistical generalization (six issuers);
- the approximately 95% accuracy target, which needs a much larger sample and independent review;
- broad-company launch readiness or independent human validation;
- valuation, expected returns or investment cutoffs, which this pilot never states;
- web fallback, or any model or paid provider, which the pilot never uses;
- live cooperative cancellation, unless a filing task is actually abandoned in the run;
- representativeness.

## Before any run

1. A `validation/` amendment wiring this cohort, with its own CI.
2. A new frozen commit carrying it, its source binding and offline checks.
3. Clean clone, execution configuration, cost and retention evidence, package built twice, and the owner's separate approval.
4. Launch-time checks, then checks-only, then one execution.
