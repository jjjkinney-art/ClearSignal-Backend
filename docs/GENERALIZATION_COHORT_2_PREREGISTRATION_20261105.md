# Unseen-company evaluation, cohort 2: pre-registration (2026-11-05)

Status: **plan only.** No package, approval, retrieval or run exists for it.

## Frozen implementation

- Code: `773449d` on `pilot/run5-integration` (do not merge). This is the run-4
  integration stack `8380090` plus backend #360 (research quality, with its
  review findings resolved) and #361 (stage-abandonment reporting).
- The implementation is frozen at the commit that adds this document. Any later
  change under `app/` or `validation/` invalidates this plan; it would need a
  new pre-registration.
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
- **Buckets by position:** large 1–200, mid 501–1,500, small 2,501–5,000.
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

| Bucket | Position | Ticker | CIK | SEC name |
|---|---|---|---|---|
| large | 101 | SMFG | 1022837 | SUMITOMO MITSUI FINANCIAL GROUP, INC. |
| large | 171 | BNY | 1390777 | Bank of New York Mellon Corp |
| mid | 709 | OWL | 1823945 | BLUE OWL CAPITAL INC. |
| mid | 963 | TWST | 1581280 | Twist Bioscience Corp |
| small | 3715 | AGEN | 1098972 | AGENUS INC |
| small | 3465 | FSTR | 352825 | FOSTER L B CO |

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
