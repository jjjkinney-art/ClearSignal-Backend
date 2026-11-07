# Unseen-company evaluation, cohort 2: pre-registration (2026-11-05)

Status: **plan only.** No package, approval, retrieval or run exists for it.

## Frozen implementation

- Code: `773449d` on `pilot/run5-integration` (do not merge). This is the run-4
  integration stack `8380090` plus backend #360 (research quality, with its
  review findings resolved) and #361 (stage-abandonment reporting).
- The implementation is frozen at the commit that adds this document
  (`d2be09f`). Any later change under `app/` invalidates this plan.
- Amendments 1 and 2 (below, both before any retrieval) change `validation/`
  and `tests/` only: amendment 1 configures the run-5 cohort; amendment 2
  fixes a rehearsal fixture defect and moves one case last. Any other change
  under `validation/` would need a new pre-registration.
- The run-3/run-4 cohort (SCCO, BX, LNC, LVS, BWMX, USCB) is now **development
  evidence**: #360 was designed on its results. It cannot measure
  generalization and is excluded here.

## Claim

Six companies never used in development or in any pilot answer the same two
ordinary questions. The result would be **fresh generalization evidence with
model-assisted review**. It is not independent human validation, not launch
validation and not a representative sample. Launch readiness stays false.

## Selection (fixed before it was applied; no filing was inspected)

Script: `scripts/select_generalization_cohort.py`. Output:
`docs/generalization_cohort_2_selection.json`.

- **Source:** SEC `company_tickers.json` as retained in run 4 (sha256
  `de59c00edabfb8b540c61ea4805446763bc9ba6aa8b42fa2955f5439556558d2`, 10,410
  rows). It lists only ticker, CIK and name. Its order is used as a size proxy;
  that is SEC's ordering, not a measured size.
- **Buckets by directory position:** positions 1–200, 501–1,500 and
  2,501–5,000. The selection output labels them `large`, `mid` and `small`.
  These are **directory-position buckets, not verified company sizes**; no
  market value or revenue was looked up.
- **Eligibility:**
  - the ticker is 1–5 capital letters (no share classes, units or warrants);
  - the name has no fund, trust, ETF, acquisition, SPAC, BDC, REIT,
    partnership, income, portfolio or merger term.
- **Exclusion of previously studied issuers, by CIK** (this removes every
  alternate ticker of the same issuer):
  - every issuer in a pilot cohort (runs 1–4 `request.json`) or with any SEC
    response retained in a run 1–4 ledger: 12 issuers;
  - every issuer whose ticker, CIK or registrant name appears anywhere in
    `app/`, `tests/`, `validation/`, `docs/` or `scripts/` at `773449d`:
    772 further issuers. Common-word tickers are over-excluded; this is
    conservative.
- **Ranking:** in each bucket, the two lowest
  `sha256("clearsignal-generalization-2:" + ticker)`, one per issuer.

Result. It is kept whatever the filings turn out to contain.

| Directory-position bucket | Position | Ticker | CIK | SEC name |
|---|---|---|---|---|
| 1–200 | 101 | SMFG | 1022837 | SUMITOMO MITSUI FINANCIAL GROUP, INC. |
| 1–200 | 171 | BNY | 1390777 | Bank of New York Mellon Corp |
| 501–1,500 | 709 | OWL | 1823945 | BLUE OWL CAPITAL INC. |
| 501–1,500 | 963 | TWST | 1581280 | Twist Bioscience Corp |
| 2,501–5,000 | 3715 | AGEN | 1098972 | AGENUS INC |
| 2,501–5,000 | 3465 | FSTR | 352825 | FOSTER L B CO |

**No substitution.** An unsupported filer (for example a foreign private issuer
filing a 20-F under IFRS), a missing filing, a failed identification or a failed
answer stays in the denominator.

## Prior exposure (disclosed)

- **Code and records:** none of the six appear, by ticker, CIK or name, in any
  of the 349 backend branch heads (positive control: SCCO found in 8 files), the
  frontend history, the original project tree, the offline-review records or
  the assistant's memory. No SEC response for any of them is retained in a
  pilot ledger.
- **Directory only:** the selection read the retained directory rows (ticker,
  CIK, name) and nothing else. No filing, company-facts or submissions data was
  opened.
- **General knowledge:** the reviewing model has general background knowledge
  of these public companies, for example that SMFG is a Japanese bank group and
  BNY a US custody bank. It was not used for selection and cannot be removed.
  The reviewer must score from the retained packet only.
- **Design history:** the bucket rule is the one used for cohort 1, whose
  outcomes are known. Only the seed and the CIK-based exclusions are new.

## Questions

The run-1/run-2 templates, with the SEC name verbatim:

- `core_thesis`: "What is the investment thesis for {name}, what supports it,
  and what could invalidate it? Distinguish reported facts from inference and
  cite material claims."
- `decision_threshold`: "Which valuation and operating assumptions would make
  {name} attractive or unattractive? Explain decision thresholds, evidence and
  uncertainty without inventing figures."

Denominator: 12 cases.

## Pre-registered assessment

For every case, from the retained packet and ledger only:

1. **Outcome:** full, degraded (including a stage the application abandoned
   after its download, per #361), unanswered, operational failure or not run.
   Completeness is reported separately from quality.
2. **Accuracy and support** (mechanical):
   - every quotation is verbatim in a retained body;
   - every reported amount reconciles with retained XBRL facts by period;
   - every derived change is recomputed.
3. **Research quality,** scored 0/1/2 each, with the evidence quoted:
   - company specificity;
   - material risks;
   - explanations of change (does each quoted cause explain the stated change,
     period and scope?);
   - monitoring criteria;
   - citation support.
4. **Usefulness,** scored 0/1/2: 2 = decision-relevant, company-specific facts
   beyond headline figures; 1 = correct but mostly headline figures;
   0 = misleading or empty.
5. **Material omissions:** up to five expected facts per case, each classified
   as present, retained but omitted, or missing from the retained sources.
6. **Errors,** listed individually: wrong figure, misattributed quote, cause
   attached to the wrong period or scope, implied threshold or recommendation.

No pooled score across groups, no pass rate, and no comparison presented as
improvement over the run-4 development results.

## Expected limits (stated before any data)

- **Foreign or IFRS filers:** the IFRS fallback roadmap (concept map,
  inline-IFRS reader, non-USD units) is not implemented. Such a case is expected
  to be degraded or unanswered and is scored as it is.
- **Bank and asset-manager measures:** these are explicit gaps where standard
  US-GAAP facts do not supply them.

## Retrieval proposal (needs a new package and Julian's separate approval)

The ordinary pilot machinery and limits are reused unchanged; only the cohort
changes. As for cohort 1:

- **Requests and time:**
  - at most 66 SEC requests;
  - per case: 8 requests in 30 s (`core_thesis`) or 3 requests in 20 s
    (`decision_threshold`);
  - 480 s wall clock, one case at a time;
  - at most 4 concurrent SEC requests and 10 dispatches per second.
- **Size:** 16 MiB per response; 256 MiB retained.
- **Calls:** no model or paid-provider calls, no retries.
- **Network:** direct TLS to www.sec.gov and data.sec.gov only, with a pinned CA
  bundle.
- **Cost:** all-in ceiling USD 1.00.
- **Configuration:**
  - filing fallback off;
  - the frontend pin is re-verified at run time;
  - output goes to a new directory with mode 0700.

Preparation is offline, before any package:

1. Write the cohort file for these twelve cases.
2. Re-run the pinned frontend classifier on the new question texts and update
   the pinned question hash.
3. Regenerate the package: #361 changed the retention evidence's table list,
   so earlier packages are invalid.
4. Review the package.

Julian's approval then names the package digest. Nothing in this document
authorizes retrieval or a run.

## Amendment 1 (2026-11-05, before packaging): cohort configuration and predictions

No company, question, assessment item or limit changes. `app/` is unchanged
from `d2be09f`. The following were made after the freeze, in one commit, and
only to configure and rehearse this cohort:

**`validation/`**

- `ordinary_pilot_contract.py`:
  - adds the `run5` cohort, in the pre-registered order;
  - makes it the only cohort an approved package or run may use
    (`APPROVED_COHORT`);
  - names the rehearsal fault-target case (`FAULT_CASE_INDEX`).
- `ordinary_approved.py`: the cohort check reads `APPROVED_COHORT`.
- `ordinary_execution_contract.py`: the run-5 case-record projection digest.
- `ordinary_frontend_intents.py`: pins the deployed frontend `84466b2`. Its
  classifier and resolver are byte-identical to `d66be31`. Adds the run-5
  question digest and intents.
- `_ordinary_synthetic_sec.py`: invented rehearsal data only. Adds the run-5
  registrants, plus the real directory rows that share their CIK or name
  (SMFNF, OBDC, OTF), so the rehearsal resolves names as the live directory
  does.
- `_ordinary_rehearsal_worker.py`: the fault target is now `FAULT_CASE_INDEX`
  (TWST), because index 4 (OWL) is predicted unresolved.

**`tests/`** and **`docs/ordinary-evidence/`**

- Adds the case file `tests/ordinary_run5_cases.json`.
- Rehearsal expectations now include the predicted unresolved cases and
  their routes.
- Assertions that assumed every case resolves were generalized.
- The committed cost-evidence template is regenerated (per-case keys only).

**No case is reordered or removed.** No case is predicted to halt the run:
an unresolved case is counted as unanswered and the run continues.

### Predicted outcomes (offline, before any retrieval)

Method:

- The deployed frontend classifier was run unmodified on the twelve exact
  questions (questions sha256 `1dd2bd96…14e8`, Node 24.15.0). Its files were
  exported from `84466b2`; `queryIntent.ts` sha256 is `f0b6a07b…dde8`.
- The frozen backend routed each question with that intent against SEC's
  retained directory (run 4, sha256 `de59c00e…58d2`). The research pipeline
  and general agents were stubbed, and nothing was read from the network.
  Routing reads no filing.

| Case | Frontend intent | Backend route | Prediction |
|---|---|---|---|
| SMFG:core_thesis | company_analysis | entity suggestion | **unresolved** (unrelated suggestions shown) |
| SMFG:decision_threshold | company_analysis | identity clarification | **unresolved** |
| BNY:core_thesis | **investing_education** | general route | **failed: model call refused, run halts** (see amendment 2) |
| BNY:decision_threshold | company_analysis | research | correct issuer |
| OWL:core_thesis | company_analysis | entity suggestion | **unresolved** (unrelated suggestions shown) |
| OWL:decision_threshold | company_analysis | identity clarification | **unresolved** |
| TWST ×2, AGEN ×2, FSTR ×2 | company_analysis | research | correct issuer |

Causes, from directory data and the pinned code:

- **SMFG:** two unsuffixed symbols on one CIK (SMFG, SMFNF), so the
  share-class rule abstains.
- **OWL:** "BLUE OWL CAPITAL INC." and "Blue Owl Capital Corp" (OBDC) share
  the name core, so the identity is ambiguous.
- **BNY:core_thesis:** the deployed frontend classifies this text as
  investing education.
- **Unrelated suggestions:** for the two unresolved thesis questions, the
  backend suggests Ford, Citigroup and Applied Materials. These are generic
  examples, but they are misleading. No SEC request is made for them.

Predicted totals (as corrected by amendment 2):

- 7 of 12 cases reach research on the correct issuer.
- 4 of 12 are unresolved (SMFG ×2, OWL ×2).
- 1 of 12 fails: BNY:core_thesis halts the run.
- No case routes to a wrong issuer.

**Unsupported research versus operational degradation.** These are reported
separately:

- An unresolved identity, a general route or an unsupported filer
  (non-US-GAAP data) is **unsupported research**. It is a product limitation
  and is counted as unanswered.
- A timeout, an abandoned stage or a transport failure on a supported case is
  **operational degradation or failure**. Neither can be predicted without
  filings, which were not inspected.
- The two SMFG cases would also face the unimplemented IFRS path, but they are
  predicted to stop at identity first. That expectation comes from general
  knowledge that SMFG is a foreign private issuer, not from any filing, and
  was not used to change anything.

These cases stay in the twelve-case denominator. The predictions are not
evidence of research quality.

## Amendment 2 (2026-11-05, before any retrieval): model-call halt and case order

No company, question, assessment item or limit changes. `app/` is unchanged
from `d2be09f`. Run 5 remains unapproved.

### What was found

Hosted CI on amendment 1 (`47b3589`, run 41977440729) failed: the synthetic
rehearsal halted with `invalid_request` before BNY:decision_threshold. The
same tests passed on the Mac. Traced offline, in both environments:

1. **Classifier.** The deployed frontend (`84466b2`, classifier sha256
   `f0b6a07b…dde8`) sends BNY:core_thesis as `investing_education`.
2. **Backend routing.** The frozen `/ask` treats that intent as general and
   calls `run_general_finance_agent`. That agent **always makes a model
   call**: no FRED key is set, so it retrieves no evidence and goes straight to
   the model.
3. **Model-call safeguard on Linux (CI).** The request reaches the pilot's
   OpenAI mock. The zero-model boundary refuses it, which halts the run with
   `invalid_request`.
4. **Model-call safeguard on macOS.** The worker's platform fixture reports
   `uname` as Linux on every host, so the OpenAI SDK's header code asks
   `distro.id()` for the distribution. macOS has no `/etc/os-release`, so
   `distro` runs `lsb_release` as a subprocess. The worker's audit hook refuses
   that subprocess's `/dev/null` open with a `RuntimeError`, so the model call
   failed **before reaching the boundary**:
   - nothing was counted as a model request;
   - the general agent fell back to a canned answer;
   - the case looked like an ordinary unresolved case.

   This was confirmed by tracing the worker's diagnostics in a throwaway,
   uncommitted copy: `distro` → `lsb_release` → "write outside fresh rehearsal
   output", three attempts.

Checked and ruled out:

- credentials: the same placeholder key, and the OpenAI client is constructed
  in both environments;
- mocks: the SDK patches are installed before the app is imported;
- leaked local state: no untracked or ignored files, and fresh outputs and
  homes.

The same worker runs the approved live mode, so **on this Mac a live run
would also have hidden the model attempt**. That is a safeguard defect in the
fixture, not application behaviour.

### What changed

- `validation/_ordinary_rehearsal_worker.py`: `distro.id()` returns a fixed
  value, alongside the existing platform fixture. Every model request now
  reaches the zero-model boundary on every host. With this line removed, the
  Mac reproduces the masked "complete" run; with it, the Mac halts exactly as
  CI does.
- **BNY:core_thesis is retained as a failed case and moved last.** It
  genuinely attempts a model call and halts the run. Following the run-3
  precedent (BWMX:core_thesis), it is ordered after the other eleven cases so
  their observations are preserved.

  New order: SMFG ×2, BNY:decision_threshold, OWL ×2, TWST ×2, AGEN ×2,
  FSTR ×2, BNY:core_thesis.

  All twelve cases stay in the denominator. **This order differs from the
  order pre-registered on 2026-11-05 and is disclosed here.** It was made
  before any retrieval and changes no case's content.
- Case file, projection digest and question digest are re-derived for the
  new order. The intents are unchanged.
- Rehearsal expectations now assert the explained outcome, without weakening
  any check:
  - status `halted`, halt `invalid_request` at the last case;
  - exactly one refused model request;
  - the exact SEC exchange count, which is now asserted unconditionally where
    a halt previously relaxed it;
  - seven answered and four identity-unresolved cases.
- The fault-target case index follows the new order (TWST:core_thesis).

### Predicted outcome (live)

- 7 cases answered on the correct issuer.
- 4 unresolved (SMFG ×2, OWL ×2).
- BNY:core_thesis: a refused model attempt halts the run. It is counted as a
  failed case. It is unsupported research caused by the frontend intent, not
  an SEC or transport fault.
