# Unseen-company generalization evaluation — pre-registered plan (2026-10-30)

Status: **plan only.** No retrieval, package, approval or run exists for it.
The implementation is frozen at the commit that adds this document; any code
change after it invalidates this plan.

## Purpose and claim

Six companies never used in development, chosen before anything answer-
bearing about them was inspected, answer the same two ordinary questions.
The result will be called **fresh generalization evidence with model-assisted
review**. It is not independent human validation, not launch validation and
not a representative sample.

## Case selection (applied 2026-10-30, before any filing was seen)

Source: SEC `company_tickers.json` as retained in run 2 (sha256
`b5be63822ef78687908848b349820d9d6a962af9287e2164f44f4b217259f4ea`). It lists only ticker, CIK and name; its order is used as
a size proxy (a limitation: it is SEC's ordering, not a measured size).

Rule, fixed before applying it:
1. Size buckets by position: large 1–200, mid 501–1,500, small 2,501–5,000.
2. Exclude tickers already used (NPK, GOOGL/GOOG, INGR, NNBR, AMZN, MAN),
   tickers that are not 1–5 capital letters (share classes, units, warrants),
   and names matching fund/trust/ETF/acquisition/SPAC/BDC/REIT/partnership/
   income/portfolio/merger terms.
3. In each bucket take the two lowest `sha256("clearsignal-generalization-1:" + ticker)`.

Result (kept regardless of what the filings turn out to contain):

| Bucket | Position | Ticker | CIK | SEC name |
|---|---|---|---|---|
| large | 103 | SCCO | 1001838 | SOUTHERN COPPER CORP |
| large | 115 | BX | 1393818 | Blackstone Inc. |
| mid | 1130 | LNC | 59558 | LINCOLN NATIONAL CORP |
| mid | 576 | LVS | 1300514 | LAS VEGAS SANDS CORP |
| small | 3043 | BWMX | 1788257 | BETTERWARE DE MEXICO, S.A.P.I. DE C.V |
| small | 3445 | USCB | 1901637 | USCB FINANCIAL HOLDINGS, INC. |

The set includes an asset manager, a life insurer, a bank and a probable
foreign private issuer. No substitution is allowed: an unsupported filer, a
missing filing or a failed answer stays in the denominator.

Questions (the run-1/run-2 templates; the SEC name verbatim, trailing "/"
removed):
- `core_thesis`: "What is the investment thesis for {name}, what supports it,
  and what could invalidate it? Distinguish reported facts from inference and
  cite material claims."
- `decision_threshold`: "Which valuation and operating assumptions would make
  {name} attractive or unattractive? Explain decision thresholds, evidence and
  uncertainty without inventing figures."

Denominator: 12 cases.

## Pre-registered assessment

For every case, from the retained packet and ledger only:

1. **Outcome** (full, degraded, unanswered, operational failure, not run) and
   the system's unanswered parts. Completeness is reported separately from
   quality.
2. **Accuracy and support** (mechanical): every quotation verbatim in a
   retained body; every reported amount reconciled with retained XBRL facts
   by period; every derived change recomputed.
3. **Research quality**, 0/1/2 each, with the evidence quoted:
   company specificity; material risks (insufficient-evidence statements score
   1 when true, 0 when a qualifying risk was retained but omitted);
   explanations of change (does each quoted cause actually explain the stated
   change, period and scope?); monitoring criteria; citation support.
4. **Usefulness**, 0/1/2: 2 = an analyst learns decision-relevant,
   company-specific facts beyond headline figures; 1 = correct but mostly
   headline figures; 0 = misleading or empty.
5. **Material omissions**: for each case the reviewer lists up to five facts
   a careful analyst would expect (latest-period drivers, segment results,
   concentrations, major one-off items, the business model) and classifies
   each as present, **retained but omitted**, or **missing from the retained
   sources**.
6. **Errors** listed individually: wrong figure, misattributed quote, cause
   attached to the wrong period or scope, implied threshold or recommendation.

No pooled score across groups; no pass rate; launch readiness stays false.

## Minimal retrieval proposal (requires a new package and separate approval)

Reuse the ordinary pilot machinery and limits unchanged; only the cohort data
changes.

| Limit | Value |
|---|---|
| SEC requests | at most 66 in total; per case 8 (`core_thesis`) / 3 (`decision_threshold`), same per-stage caps |
| Time | 30 s / 20 s per case; 480 s wall clock; one case at a time; at most 4 concurrent SEC requests; at most 10 dispatches per second |
| Size | 16 MiB per response; 256 MiB retained |
| Calls | 0 model, 0 paid-provider, 0 retries, no redirects |
| Network | direct TLS to www.sec.gov and data.sec.gov only, pinned CA bundle |
| Cost | all-in ceiling USD 1.00 (flat-rate network; no billable call possible) |
| Configuration | filing fallback off; frontend pin re-verified at run time |
| Output | new directory `~/clearsignal-pilot/run-3`, 0700, 90-day retention |

Preparation steps (offline, before the package): replace the cohort file
with the twelve cases above; re-run the pinned frontend classifier on the new
question texts and update the pinned question hash; prepare and review the
package. Then Julian's separate approval names the package digest.
