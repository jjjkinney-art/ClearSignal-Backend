# Cross-company coverage fix acceptance — 6 October 2026

**Status: local remediation and required CI passed; production sample found a history-indexing defect.**
See the [live acceptance report](CROSS_COMPANY_PRODUCTION_ACCEPTANCE_20261006.md)
for verified behavior, the Alcoa follow-up, and remaining gates.
The [original failing audit](CROSS_COMPANY_COVERAGE_AUDIT_20261006.md) remains
unchanged. This [post-fix report](CROSS_COMPANY_COVERAGE_FIX_ACCEPTANCE_20261006.json)
records the repaired code fingerprints and reproducible local checks. It does not
certify unrestricted public-company analysis or authorize launch.

## Repaired behavior

- A structured company selection requires an exact registered symbol, full
  alias/name, or exact official SEC identity. Unknown selections return a readable
  clarification before research; a peer in the question cannot replace them.
  `MAN` now means ManpowerGroup rather than a fuzzy match to Mylan/Viatris.
- Current companies beyond the local registry can resolve through the official
  SEC directory. The one-hour cache fails closed after expiry on feed failure,
  with retry backoff. Conflicting symbols and ambiguous names/share classes are
  withheld. Current metadata cannot establish a historical identity; reviewed
  temporal relationships remain on their existing resolver.
- Exact-ticker SEC filing retrieval no longer falls back to body-text searches
  that could return another issuer's filing merely mentioning the ticker.
- Source and operating-risk answers withhold unsupported generated thesis fields
  before persistence and emission. Unsupported issuer/topic risk requests cannot
  use consolidated revenue as risk evidence. A separately requested, admitted,
  document-bound metric may be answered as `partial`, with the risk part explicitly
  unverified. Already-bound issuer KPI claims retain their document provenance.
- Saved general/clarification turns store the visible answer rather than a JSON
  payload. Existing analyses and messages are not backfilled.

## Local results

| Check | Result |
|---|---:|
| Fixed benchmark cohort | 18 companies, 8 sectors |
| Exact local identity checks | 36/36 |
| Public router handoffs: ticker, name, question only | 54/54 |
| Wrong-company handoffs in that cohort | 0 |
| Consolidated-revenue risk decoys | 4/4 correctly withheld |
| Official-directory routing outside local registry | 15/15, across 5 companies |
| Exact symbols parsed from SEC snapshot | 10,433 |
| Withheld SEC snapshot row | 1: non-trading-style `NONE.` identifier |

The frozen size cohorts now pass all three input forms for 12/12 mega/large,
3/3 mid and 3/3 small/micro companies. Size tiers are the benchmark's
29 September classifications, not current market-cap measurements.

The additional official-directory handoffs cover WDFC (WD-40), MOD (Modine),
LQDT (Liquidity Services), NWE (NorthWestern), and AZZ. A regression also prevents
SEC's legal name `WD 40 CO` from selecting ticker `WD` inside that name. The
10,434-row directory is the previously captured official snapshot with SHA-256
recorded in the JSON report. These are identity tests, not 10,433 company analyses;
SEC rows include security classes and foreign issuers.

Validation: **1,478 tests passed** across the boundary and targeted regression
suites; **16 skipped** (obsolete module and separate frontend checks). The 38
broader regression modules ran in fresh interpreters, as required by repository
CI. Collection completed with **14,785 tests and zero collection errors**.
Warnings in broader runs concerned legacy test-worker cleanup and a dependency
alias deprecation; the final boundary suite passed without warnings. Full required
GitHub CI remains a separate gate for the uploaded head.

The first full CI run on `2c12f00` found one obsolete Tesla test expecting
exact-ticker EFTS fallback. That expectation is replaced with a regression that
requires withholding when the issuer map is unavailable; the legacy name-based
false-positive test now verifies that it actually reaches the intended filter.
The Tesla, SEC-provider and exact-identity suites pass together: **76 tests**.
Required CI passed on final PR head `7f625e1` (run `37455539765`).
PR #192 was squash merged as `de51491`.

The 32 public-router/pipeline admission cases include authenticated and unsigned
variants of four reviewed risk slices plus four unsupported slices. For AA,
ACHC, ACMR and MAN, producer-bound consolidated metrics remain inspectable but
cannot fill the unsupported operating-risk answer or retain an uncited bull case.
Owner-scoping and guarded legacy-memory regression checks pass locally.

## Remaining release gates

1. Required CI must pass on the final PR head; merge and verify the deployed
   backend commit before live acceptance.
2. While signed in, run DOCU's subscription-renewal question and inspect each
   cited disclosure against its exact filing. Reload the investigation and
   verify the saved answer and account-owned History/Research Trail record.
3. Exercise AA, ACHC, ACMR and MAN in ticker, name and question-only forms.
   Confirm the returned company identity, separately requested metric evidence,
   and an explicit gap for operating-risk topics without reviewed extraction.
4. Exercise at least one directory-only company such as WDFC; an unavailable
   directory must return a clarification, not another issuer's analysis.
5. Run an unknown selected ticker with a known peer in the question. It must
   require clarification; cross-account and signed-out access must remain denied.
6. Evaluate source quality, topic completeness, stale/conflicting records, and
   answer usability across the declared beta cohort. Passing handoff checks does
   not prove that an answer is materially useful or predicts market performance.

The reviewed qualitative-risk extractor still covers four issuer/topic pairs:
Apple Services, Microsoft Cloud, NVIDIA Data Center, and DocuSign subscription
renewals. Universal sector/topic risk extraction, foreign-filing depth and global
jurisdiction coverage remain roadmap work. Unsupported questions are handled
honestly; this patch does not claim those capabilities are complete. No
production analysis, account deletion, background delivery or shared ticker write
was executed by this acceptance audit.
