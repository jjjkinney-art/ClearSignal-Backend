# Ordinary pilot run 2 — execution plan and pre-registered assessment (2026-10-30)

Status: **prepared, not approved, not executed.** This document is committed
before the execution package is prepared, so the package's `code_binding`
revision contains it. Any execution needs Julian Kinney's separate approval of
that package's SHA-256. Nothing here authorises a live request.

## 1. What is being run

The same twelve-case ordinary pilot as run 1 (`ordinary-20261030-01`, package
`f3ca1afd…`, consumed, halted at case 5), on one integration commit:

| Source | Contents |
|---|---|
| PR #350 | Native ordinary ledger, gate and boundary (foundation) |
| PR #352 | Approval-gated launcher, direct-TLS mode, and the **graceful-degradation amendment** |
| PR #353 | Revenue concept recency (GOOGL revenue was previously omitted) |
| PR #354 | Latest-period explanations; cited monitoring baselines; fewer repeated caveats |
| This branch | Monitoring baselines labelled historical, comparable period and unassessed seasonality stated |

### Graceful-degradation amendment (included explicitly)

Run 1 halted when the application's own evidence collector stopped waiting
(10 s; 20 s for source documents) while INGR Company Facts was still
downloading. With the amendment, the pilot boundary follows the application:
an evidence request the application abandons is abandoned by the gate, its
in-flight I/O is stopped, late response bytes are discarded (never retained,
never answered from), and the attempt is recorded with terminal status
`abandoned`. The case continues and is classified as a degraded answer
instead of halting the run. Abandoned attempts count against every quota.
Limitations: the wait mirror is coupled to the application's evidence rule;
a shared directory fetch owned by an abandoned stage degrades its waiters
(no late data); the drain is conservative. The amendment is enforced by
`tests/test_ordinary_isolated_worker.py::test_an_abandoned_evidence_request_degrades_one_answer_without_halting`
and `::test_the_abandoned_response_never_reaches_the_answer_and_closes_before_the_next_case`,
both listed in the evidence documents' derived `enforced_by`.

### Unchanged from run 1

- Cohort and case order: NPK, GOOGL, INGR, NNBR, AMZN, MAN × `core_thesis`,
  `decision_threshold`; same questions (`tests/ordinary_pilot_cases.json`).
- Limits (code constants, re-derived at run time): 66 SEC GETs total; per case
  8 (`core_thesis`) / 3 (`decision_threshold`) with the same per-stage caps;
  case deadlines 30 s / 20 s; wall clock 480 s; one case at a time, at most
  4 concurrent SEC requests, at most 10 dispatches per second; 16 MiB per
  response, 256 MiB retained; 0 retries; no redirects; 0 model attempts;
  0 paid-provider attempts.
- All-in ceiling USD 1.00.
- Direct TLS to `www.sec.gov` and `data.sec.gov` only, verified against the
  pinned certifi bundle with hostname checking; any inherited proxy refused;
  public DNS answers only.
- `DECISION_MONITORING_FILING_FALLBACK_ENABLED=false` (policy and worker).
  The explanation-based checks therefore appear only in `core_thesis`
  answers; threshold answers carry the margin baseline only.
- Output: a new directory, `/Users/juliankinney/clearsignal-pilot/run-2`,
  created 0700 by the launcher, which refuses an existing directory. 90-day
  retention. Run-1 files are not read or written by the launcher.

## 2. Pre-registered assessment

Written before execution; the post-run report follows it and states any
deviation.

### 2.1 Report all twelve outcomes

One row per case in case order, from `packet.json` and the ledger:
outcome class (`full_answer`, `degraded_answer`, `unanswered`,
`operational_failure`, or `not_run` after a halt), terminal status, SEC GETs
used against that case's cap, abandoned attempts, elapsed time, and unanswered
parts. The denominator is always twelve. A degraded answer is never a quality
pass.

### 2.2 Separate the cases by prior exposure

| Group | Cases | How to read it |
|---|---|---|
| A. Previously exposed | NPK and GOOGL × both questions | Answered in run 1 and used to develop #353/#354. Shows whether fixes hold on fresh retrieval; not independent evidence of quality. |
| B. Exposed by halt | INGR:core_thesis | Its timeout diagnosis shaped the amendment. Tests the operational fix, not answer quality development. |
| C. Not answered in run 1 | INGR:decision_threshold; NNBR, AMZN, MAN × both questions (7 cases) | The only fresh evidence on answer quality. |

No rate is pooled across groups. Group C is reported first for quality.

### 2.3 Completeness versus research quality

- **Completeness** (mechanical): outcome class and the system's own list of
  unanswered parts. A complete-looking answer can still be poor research,
  and an honest partial answer can be good research.
- **Research quality** (reviewed per answered case, each scored 0 / 1 / 2 with
  the evidence quoted):
  1. *Company specificity* — 2: rests on this issuer's own figures, segments,
     drivers or disclosures; 1: some issuer-specific content amid generic
     text; 0: could describe any company.
  2. *Material risks* — 2: risks tied to this issuer's reported business or
     results; 1: a real but boilerplate risk; 0: none, or misattributed.
  3. *Explanations of change* — 2: material latest-period changes explained
     from the filing (management attribution labelled, or the filing's own
     arithmetic); 1: changes stated without explanation although the saved
     filing contains one; 0: wrong or invented explanation. "No explanation
     in the source" is recorded separately and is not penalised.
  4. *Monitoring criteria* — 2: named historical baselines with period and
     duration, compared only with the corresponding period one year later,
     seasonality stated, no investment threshold implied; 1: baselines
     present but vague; 0: thresholds, targets or recommendations implied.
  5. *Citation support* — 2: every figure and quotation traced to a retained
     SEC body (quotations verbatim after whitespace normalisation; figures
     reconciled with the cited XBRL facts); 1: minor citation mismatch with
     correct content; 0: any unsupported figure or quotation.
- Accuracy errors (a wrong figure, a misattributed quotation, an invented
  cause, threshold or recommendation) are listed individually regardless of
  scores.
- For every gap, record whether the evidence was **missing from the retained
  sources** or **retained but omitted** by the answer.

### 2.4 Open product gap carried into the assessment

Risk selection is generic: risk excerpts are chosen by source order across
fixed topics, not by relevance to the issuer's reported business (run 1:
GOOGL intellectual-property boilerplate). The assessment records which risks
were selected and scores them under 2.3(2), but this gap is known and open;
it is neither a run-2 regression nor fixed by this package.

### 2.5 Operational checks

Zero model and paid-provider attempts; every count within its cap; no
redirects or retries; SEC 403/429 counts; abandoned attempts and the stages
that abandoned them; whether any late bytes were retained (must be none);
output inventory matches the declared inventory exactly; `request.json` and
`packet.json` contain no runtime values.

### 2.6 Review limits

The assessment is model-assisted unless a named human reviewer is recorded;
it is not independent human review. Run 2 is a small pilot, not launch
validation, and the twelve cases are not a representative sample.

## 3. After the run

Record SHA-256 hashes of every run-2 file immediately; do not rerun or retry
under the same approval; leave run-1 files unchanged; delete run 2 and its
evidence files 90 days after completion.
