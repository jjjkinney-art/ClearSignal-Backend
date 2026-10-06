# Signed-in broad-company evidence acceptance

Recorded 7 October 2026 NZ / 6 October UTC after the owner confirmed deployment
of PR #194 (merged main `7e97e529fcbc4a2b42690b450c06a1339331dca9`).
The runtime SHA could not be independently retrieved from this environment;
the production frontend and authenticated analysis flow were exercised directly.

## Result: broad-company launch gate remains open

Fifteen fresh company/topic investigations across all eleven cohort sectors were
run through Intelligence Mode with explicit ticker scopes. Four returned dated
issuer risk disclosures with answer citations and inspectable SEC filing links.
Eleven returned readable, saved evidence-gap answers. Safe withholding prevents
unsupported claims, but is not a useful-answer coverage pass.

| Issuer | Sector | Topic | Observed result |
| --- | --- | --- | --- |
| WDFC | Consumer Staples | Distribution | Attributed disclosures |
| MAN | Industrials | Staffing demand | Evidence gap |
| DOCU | Technology | Subscription renewals | Attributed disclosures |
| AA | Materials | Energy supply | Evidence gap |
| ACHC | Health Care | Patient safety | Evidence gap |
| ACMR | Technology | Customer concentration | Evidence gap |
| JPM | Financials | Credit losses | Evidence gap |
| COST | Consumer Staples | Membership renewals | Evidence gap |
| LLY | Health Care | Drug development | Attributed disclosures |
| BA | Industrials | Production quality | Evidence gap |
| XOM | Energy | Commodity prices | Evidence gap |
| ETSY | Consumer Discretionary | Marketplace sellers | Evidence gap |
| NWE | Utilities | Energy supply | Evidence gap |
| SLG | Real Estate | Liquidity | Attributed disclosures |
| NFLX | Communication Services | Subscription renewals | Evidence gap |

Each run displayed the expected company ticker and two saved messages. Tests used
the marker `Broader coverage acceptance October 7.` and normal private account
storage; no shared ticker mutation or external notice delivery was requested.
This record excludes account identifiers, tokens, other private research, full
filing quotations and raw browser snapshots.

The four attributed results are UI observations, not independent certification
of every quote span, causal relevance, risk ranking, current risk occurrence or
investment quality. Lilly's second disclosure concerns general outsourcing and
clinical subjects; its relevance to drug development deserves further review.
Numeric context was shown separately and did not substitute for missing risks.
The other eighteen members of the frozen cohort were not exercised in this run.
This is a failing live sample, not a passed 33-company acceptance report.

## Private memory and history

Both History and Research Trail displayed all fifteen marked fresh analyses.
The History `AA` filter included the new Alcoa test under AA, alongside its
earlier correctly scoped test. Private recall ranked the new WD-40 investigation
as the likely match, and reopening preserved both saved messages and the cited
answer. Research Trail's WDFC filter also showed that answer. These checks do not
prove foreign-owner isolation in production; that remains covered separately by
the ownership regressions and launch acceptance procedures.

## Remediation and required next evidence

Code inspection found a reproducible fallback defect: a failed first quarterly
download skipped annual-risk discovery, allowing the remaining attempt to be
spent on another quarter. The fix prefers the latest annual filing in the
remaining slot after a failed first quarter, just as after a quarter with no
qualifying risks. Failed attempts still count, the default ceiling stays two,
and no quote/admission/identity gate or router deadline is relaxed.

This defect is not yet established as the cause of the eleven live gaps.
Production responses do not reveal download, section, timing or filter outcomes.
The read-only SEC acceptance report now records download/extraction timings,
normalized text length, Risk Factors heading and complete-section counts, topic
sentence counts and extracted-disclosure counts. Counts cover only the scanned
prefix when extraction stops at its two-disclosure limit. No source prose or
user-agent contact is added to diagnostics. Production logs also identify form,
text length, disclosure count and document elapsed time without question text.

Run the full CLI cohort in an environment with configured SEC contact and
working SEC access. Inspect actual failure metadata and compare isolated CLI
timing against production router logs; isolated timing does not reproduce the
full `/ask` deadline. Fix the observed root causes and repeat signed-in cases
before clearing broad coverage. Shared routes remain guarded, old analyses are
not backfilled, and foreign forms/multiple requested topics remain open gaps.

Local validation: 294 relevant tests across seven isolated modules pass on Python
3.12; clean collection finds 14,951 tests. Required pinned CI and a fresh live
retest of this follow-up change remain separate release checks.
