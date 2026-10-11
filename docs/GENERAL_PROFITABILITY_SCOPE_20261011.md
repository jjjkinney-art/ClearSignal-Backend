# General profitability scope — 11 October 2026

The deployed post242 capture completed all 36 cases. Financial-trend answers
were attributed for 13 of 18 issuers; AA, ACHC, JPM, LLY and XOM remained partial
because the generic profitability question implicitly required operating income.
All 18 broad investment-thesis answers remained partial. Capture completion and
claim attribution are not adjudicated usefulness or launch readiness.

## Reporting evidence reviewed

Downloaded the exact latest quarterly documents cited in the supplied capture:

- [AA](https://www.sec.gov/Archives/edgar/data/1675149/000119312526326265/aa-20260630.htm)
- [ACHC](https://www.sec.gov/Archives/edgar/data/1520697/000119312526321076/achc-20260630.htm)
- [JPM](https://www.sec.gov/Archives/edgar/data/19617/000162828026054343/jpm-20260630.htm)
- [LLY](https://www.sec.gov/Archives/edgar/data/59478/000005947826000081/lly-20260630.htm)
- [XOM](https://www.sec.gov/Archives/edgar/data/2115436/000003408826000093/xom-20260630.htm)

All downloads returned HTTP 200 and contained no OperatingIncomeLoss tag.
The reviewed consolidated income statements for AA, ACHC and LLY report pretax
and net income without a separate operating-income subtotal. This is a scoped
observation about these statements, not proof that the issuers never report an
operating measure elsewhere. The application must not infer disclosure absence
from missing facts or a failed retrieval.

AA, ACHC, JPM and LLY yielded four comparisons through the existing bounded
inline parser and filing-metric producer in a local replay. XOM's quarterly
inline contexts identify predecessor CIK 34088, so the current-CIK 2115436
parser correctly rejects them. No identity exception is added. The SEC Company
Facts response for current CIK 2115436 independently produced the four existing
XOM comparisons. Each of the five local source-gate replays answered the generic
financial-trends question using a verified net-income comparison, with operating
income still explicitly unverified. This replay is not a live /ask, latency,
snapshot-reopen or complete benchmark result.

## Scope correction

Retrieval continues requesting operating income and net income for profitability.
A general profitability question may be supported by at least one independently
rebuilt core profit comparison. An explicitly named operating-income or net-income
measure remains required. Pretax income alone remains supplementary and cannot
satisfy generic profitability. Conflicting core profit comparisons prevent scope
completion. Other metric gaps and newer-filing coverage gaps remain required.

The source answer exposes profitability_coverage with per-measure
verified_comparison, conflicting_comparisons or not_verified status and selected
citation IDs. Missing measures remain visible in the direct answer, even when
an attributed generic answer is possible. A not_verified status does not mean
not_reported. No operating-income arithmetic, margin calculation, ticker-specific
shortcut, benchmark prompt change or question-family deletion is introduced.

Broad investment-thesis composition is unchanged and remains partial where
operating income, competitive position, valuation or risk interpretation is
unverified. The 100-issuer quality gate, unseen-company coverage, personalization,
source adjudication and eventual 500-issuer validation remain open priorities.

## Validation and deployment acceptance

181 focused tests passed across profitability coverage, financial thesis
foundations, source answers, bank net revenue, reporting coverage, filing metrics
and the company-quality matrix. Tests include explicit synonyms, wrong issuer,
tampered claims, conflicting comparisons, missing references, unavailable
identity, supplementary pretax and unchanged broad-thesis gaps. Benchmark tests
continue requiring not_adjudicated and launch_ready=false without adjudication.

After CI and deployment, capture the five financial-trend cases in Render and
inspect citations, periods, profitability_coverage and missing-measure notices.
Then repeat the complete 36-case capture. Do not record an 18/18 production
financial result or change the launch gate until that capture is available.
