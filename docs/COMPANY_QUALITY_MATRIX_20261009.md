# Company-quality matrix: first capture increment

This increment turns the universal-company-quality roadmap into a reproducible
multi-question capture plan. It does not establish quality parity or launch
readiness. The existing registry contains 18 issuers: 12 large, three mid-sized
and three small/micro-cap companies, with classifications frozen on September
29, 2026. The minimum 100-issuer milestone remains unmet; classifications and
new issuer entries need verification before broader acceptance.

## Scope and result meanings

The default matrix contains 108 cases: each registered issuer receives questions
about its investment thesis, decision thresholds, structural risks, financial
trends, sector operating metrics and recent developments. Cases interleave size
tiers within each question family. The matrix and registry hashes identify the
exact scope of each capture; changing filters changes the matrix identity.

Execution reuses the existing synthetic pipeline boundary. It makes real
provider requests when explicitly enabled, but supplies no user memory or
personalization and enables no persistence or notification delivery. It does
not exercise authenticated API access, saved-thesis selection or save/reopen.
Those require separate signed-in acceptance.

- `not_executed`: planned case, no provider call.
- `captured`: response collected, not a factual or useful-answer pass.
- `execution_failed`: runner exception, not an honest evidence-gap response.
- `not_reviewed`: no quality adjudication has occurred.

Reports always leave quality pass rate unset and launch readiness false. Counts
by size and question family describe capture status only. Each captured response
has a hash for subsequent review. Exception messages are excluded from reports;
only exception classes are recorded. An execution failure does not suppress
later cases and causes a nonzero exit after the batch completes.

## Running on Render after deployment

List the complete plan without provider execution:

```bash
python scripts/benchmark_company_quality.py \
  --plan --output /tmp/company-quality-plan-v1.json
```

Collect an initial eight-case batch spanning all three size tiers:

```bash
CLEARSIGNAL_BENCHMARK_CAPTURE_ENABLED=true \
python scripts/benchmark_company_quality.py \
  --ticker AA --ticker ACHC --ticker AAPL --ticker TSLA \
  --family core_thesis --family financial_trends \
  --execute --limit 8 --output /tmp/company-quality-first8-v1.json
```

These familiar issuers establish an initial diagnostic baseline, not an unseen
holdout. The full default matrix runs in batches of at most 20 cases. Use offsets
0, 20, 40, 60, 80 and 100, with a distinct output filename per batch:

```bash
CLEARSIGNAL_BENCHMARK_CAPTURE_ENABLED=true \
python scripts/benchmark_company_quality.py \
  --execute --offset 0 --limit 20 \
  --output /tmp/company-quality-batch-000-v1.json
```

The output is written atomically before execution and after every completed
case. Execution refuses an existing output path to preserve earlier results.
After interruption, retain the checkpoint and use its `next_offset` with the
same registry, ticker and family filters and a new output path. Check matching
matrix hashes before combining batches. Resuming advances past completed cases,
including failed captures; separately rerun failed cases using their ticker and
family filters. Copy reports out of `/tmp` before a restart or deployment.

Without `--execute`, the runner only writes an unexecuted batch. A zero exit
code means planning/capture completed, never that answer quality passed.

## Acceptance work that follows capture

1. Review claims, numbers, periods and citation bindings against primary
   sources. Preserve the existing numerical and source-integrity gates; do not
   automatically grade broad narratives with unrelated factual references.
2. Review usefulness and issuer specificity blind to company size. Record
   evidence gaps separately and publish results by size and question family.
3. Expand and verify the registry to at least 100 representative issuers,
   including at least 30 per main size tier, and reserve unseen holdout issuers.
4. Exercise the signed-in path with explicit research preferences, historical
   theses, comparable question types and save/reopen checks across size tiers.
5. Use observed recurring failures to prioritize shared discovery, retrieval,
   extraction and answer-composition fixes, then rerun failing and unseen cases.

The first increment was validated with 58 local tests covering this runner,
registry integrity, existing factual grading and subgroup scorecards. Default
dry runs produced 108 planned cases and no executed or adjudicated answers.
At creation, real provider output and signed-in quality acceptance were pending.

## First deployed capture findings — October 9, 2026 Auckland

The user ran the eight-case AA/ACHC/AAPL/TSLA batch on PR217's deployed commit
`1bc80c2cd818e1fdb6ec11c6d64577cbc59fada0`. All eight responses were captured.
The four core-thesis answers were identical operating-risk gaps; the four
financial answers returned revenue and operating cash flow but omitted requested
profitability while reporting no unanswered parts. No full useful-answer pass
is established by this batch, and its numbers have not been independently
adjudicated against the cited documents.

The shared source-answer route activates for citation and invalidation wording.
It deliberately withholds generated thesis conclusions. A broad question needs
source-supported thesis composition and explicit coverage of its supporting and
invalidation mechanisms; merely changing the route would not establish that
those claims are supported. This remains a P0 launch blocker across size tiers.

The immediate completeness increment requests operating and net income when a
question asks about profitability, preserves all requested metric slots beyond
the usual three-claim presentation limit, and marks missing producer-bound
metrics as partial. Both start and end dates are included in duration
comparisons so quarter and year-to-date observations are distinguishable.
Profit amounts are explicitly distinguished from margins. Broad thesis gaps
now name the unverified thesis and its mechanisms rather than only a risk slot.
Source attribution and thesis-comparison safeguards remain in place.

After deployment, repeat the same eight cases with a fresh output path. Review
profitability coverage, date ranges and missing parts before independent
numerical/citation adjudication. The thesis cases are expected to remain gaps
until the broader composition work passes evidence binding and usefulness
acceptance. The Render logs also report missing FMP and NewsAPI configuration;
record those provider limitations separately from SEC discovery, which returned
filings for all four issuers. A missing static profile alone did not prevent
AA or ACHC from returning structured financial observations.
