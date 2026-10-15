# Opt-in latest-filing financial fallback for monitoring

## Demonstrated gap and scope

The PR292 retained ACHC Company Facts body has Q1 2026 core observations while
prior core-thesis output has producer-bound Q2 inline filing evidence. Raw-body
and parser checks agree; no Q2 observations in those captured core arrays are
being dropped by parsing. The snapshot does not prove the old response or any
upstream/cache cause. The existing newer-filing coverage notice honestly reports
this difference but cannot supply financial values from filing metadata.

The broad decision question does not explicitly name a core metric, so
`requests_filing_metrics` returns false. Even enabling that predicate alone would
not suffice: the filing reader's explicit-request filter would remove the core
comparisons from a broad question. This change handles both selection points.

## Disabled-by-default product capability

Add `decision_monitoring_filing_fallback_enabled=False` to Settings, configurable
by `DECISION_MONITORING_FILING_FALLBACK_ENABLED`. The new path requires this flag
AND `decision_monitoring_inputs_enabled` AND the existing decision-monitoring
intent predicate. Specialized segment/issuer KPI questions remain excluded from
this broadening. Existing explicit metric/thesis behavior stays unchanged.

When opted in, the router's existing filing task is scheduled for broad financial
monitoring questions. Its validated core comparisons are retained as the basis
for monitoring, rather than being filtered out merely because metric names were
not explicitly listed in the question. This reuses the existing latest domestic
filing reader, inline XBRL validation and whole-pair merger; no new transport or
additional provider is introduced. Foreign-filing coverage is not extended.

The fallback is parallel, not a sequential retry after Company Facts. It may
fetch a filing even when Company Facts is already current. It selects at most
one primary document using the existing recent-filings discovery. Existing
10-second general provider collection and source-document grace up to 20 seconds
remain unchanged. A failure yields no replacement facts, preserving previously
validated comparisons and any newer-period coverage warning.

No values come from metadata. Only rebuilt producer-bound comparisons may replace
older same-concept pairs. Aliases remain distinct, currencies/durations are not
joined, equal-period conflicts remain visible, and absent operating income still
means no operating margin. A current filing does not establish a buy/sell cutoff,
valuation or expected return. No synthetic operating-income derivation is added.

## What is intentionally not activated

This feature is OFF by default. No deployment environment value is changed here.
Therefore merging/deploying this PR alone does not improve current live monitoring
freshness or add SEC requests to it. This is implementation for reviewed rollout,
not a declaration that ACHC or the launch blocker is resolved.

Existing frozen pilot policy, quotas and launcher code remain byte-for-byte
unchanged. Their isolated environments do not carry the new optional variable,
so the new capability stays off and their original request allocation remains.
The two-source diagnostic capture policy is also unchanged. All ten approvals
remain consumed; no approval is reused and no live request/rerun occurs here.

A future enabled pilot requires a separate explicit variant/configuration review:
its current monitoring allocation has no filing-document slot. Account for the
additional submissions/discovery request(s) and at most one filing document per
applicable monitoring case. Audit archive/discovery behavior before fixing exact
new quotas; do not assume unused slots transfer or silently grow the old 33-GET
policy. Keep existing deadlines and all transport/claim/halt/fencing safeguards.
Only after exact-diff review, CI and the actual-executor checks should a new
single-use package be prepared for separate approval. Production activation
likewise waits for that validation and an explicit rollout decision.

## Offline validation

New tests cover disabled default/no added fetch, both required flags, broad
monitoring's retained revenue/net-income/cash comparisons, explicit absent-margin
behavior, whole same-concept replacement, alternative-concept refusal, as-of
refusal, specialized-topic exclusion, wrong issuer/metadata, failure preservation,
and clearing the newer-period metadata gap only when comparisons actually cover
that period. Test data is invented, including inline contexts/fact IDs.

The initial new test incorrectly expected a `status` key from the internal
monitoring producer. Its actual contract expresses partial coverage through the
answer, unanswered parts and empty benchmarks. The assertion was corrected to
check those existing fields; production output schema was not changed.

Tests use pinned CPython 3.11.9/audited dependencies, invented credentials and all
real socket audit operations denied. Existing source-document collection/router
and frozen source-monitoring regressions are run separately. Exact final results
are recorded below before publication. Hosted CI remains required before merge.

Final results: 179 financial/monitoring/filing/source-answer tests passed, plus
22 frozen-monitoring/new coverage tests and 45 source-document collection/router
regressions: 246 total passed. `git diff --check` passed. No policy, manifest,
execution configuration, historical ledger or provider limits were edited.

Each group used the same command pattern (FILES is the pytest paths/node IDs):

```bash
env -i PATH=/usr/bin:/bin OPENAI_API_KEY=TEST_ONLY \
  SEC_USER_AGENT='Test contact@example.invalid' PINNED_PYTHON -I -B -c \
  "import sys,socket;sys.path[:0]=['.','tests'];socket.has_ipv6=False;sys.addaudithook(lambda e,a: (_ for _ in ()).throw(RuntimeError('network blocked')) if e.startswith('socket.') else None);import pytest;raise SystemExit(pytest.main(['-q',FILES]))"
```

Group one: `tests/test_monitoring_filing_freshness.py`,
`tests/test_filing_metric_evidence.py`, `tests/test_monitoring_period_coverage.py`,
`tests/test_decision_monitoring_evidence.py`,
`tests/test_financial_thesis_foundation.py`, `tests/test_verified_sec_metrics.py`,
`tests/test_source_answer.py`.

Group two: `tests/test_source_monitoring_pilot.py` and the two added nodes
`tests/test_monitoring_filing_freshness.py::test_newer_filing_comparisons_clear_metadata_gap_only_when_covered`
and `tests/test_monitoring_filing_freshness.py::test_freshness_never_makes_revenue_aliases_interchangeable`.

Group three: `tests/test_source_document_collection_budget.py` and
`tests/test_router_evidence_bypass.py`.
