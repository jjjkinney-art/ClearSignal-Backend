# Bounded monitoring-freshness pilot review — 2026-10-15

Base: `26a36783311691538226d4ebac7dcd65a3f59330` (PR294).

## Purpose and authority

This separate six-case variant exercises the opt-in filing fallback introduced by PR294. ASML, ACHC and NPK retain the frozen core_thesis and decision_threshold questions. Every case is source-only; all model quotas are zero. It is offline by default. The production setting remains default OFF; this patch edits no application code or deployment configuration.

The new approved entrypoint requires a newly reviewed manifest, exact source binding, validated execution configuration, separate execution/spending authorization and a fresh output directory. All ten prior live approvals are consumed. Neither these tests nor this document authorize a live request, reset, resume or rerun. Existing consumed ledgers are not opened or modified by this work. No historical remote-file preservation claim is made without access to those files.

## Fixed request allocation

| Case family | Directory | Submissions | Facts | Documents | SEC total per case |
| --- | ---: | ---: | ---: | ---: | ---: |
| core_thesis | 2 | 3 | 1 | 2 | 8 |
| decision_threshold | 1 | 2 | 1 | 1 | 5 |

Three cases of each family give a fixed maximum of 39 SEC GETs, with zero model attempts. The prior source-monitoring policy remains 33 GETs; the control policy remains 30 GETs and 24 model attempts. No quota transfers across cases, stages or routes.

Durable stage reservations are written atomically with the attempt reservation. The existing request fingerprint also binds the stage. Unknown, missing, malformed or exhausted stage bindings halt before dispatch.

| Evidence stage | Submissions | Facts | Documents |
| --- | ---: | ---: | ---: |
| evidence.sec | 1 | 0 | 0 |
| evidence.sec_metrics | 0 | 1 | 0 |
| evidence.filing_metrics | 1 | 0 | 1 |
| evidence.thesis_disclosures (core only) | 1 | 0 | 1 |

Each eligible stage can win the directory first-fetch race, with at most one directory slot at that stage. Aggregate case directory caps still apply; stage allowances do not add extra directory budget. Core disclosure fallback requiring an additional document fails closed rather than borrowing the metrics document slot.

The domestic recent-filings path supplies one additional submissions request and at most one exact submissions-derived primary document for a threshold case. It does not authorize archive scans, full-text search, alternative URLs, retries or redirects. ASML may have no qualifying domestic form; absence remains a gap.

## Isolation, deadlines and validation

Only the new isolated child enables both monitoring inputs and monitoring filing fallback. Other modes explicitly reconstruct fallback OFF rather than inheriting an ambient flag. Runtime drift is rejected.

The owned transport, exact document authorization, reviewed ASML envelope, application byte/media/canonical-hash validation, at-most-once claims, durable halt, late-worker fencing, concurrency controls, proxy/CA admission and credential canaries remain in force. FMP, NewsAPI and FRED stay excluded. No raw-body retention is added.

Deadlines are unchanged: the ordinary first evidence wait is 10 seconds; only the existing qualifying core-document path can receive its existing 20-second grace. Threshold filing work receives no new grace. The existing 3-second drain and 480-second whole-run deadline remain fixed. A real slow filing may still halt this variant.

The US$0.52 ledger allowance is not an invoice ceiling. Zero model quotas do not prove an invoice amount.

## Offline verification

Tests run on CPython 3.11.9 with audited dependencies, invented credentials and a socket-denying audit hook. Isolated worker fixtures also prohibit external dispatch.

- New variant suite: 16 passed.
- Policy, approval, capture-budget and application freshness suites: 177 passed.
- Existing source-monitoring suite: 20 passed.
- Two-source capture suite: 42 passed.
- Remaining netrc-isolation, reviewed-envelope, owned-transport and integrated-rehearsal group: 157 passed. Total completed local regression tests: 412.
- Import smoke: 135 routes.
- Timeout and redirect cases also passed separately (2 tests already included in the new 16).
- For a fixed invented binding/configuration, all five pre-existing policy generators produce dictionaries identical to the base implementation: offline, live_adapter_validation, source_monitoring, approved and approved_source_monitoring.
- The actual isolated synthetic pipeline completed all six cases, with zero models or unresolved claims. The newer domestic inline filing supplies four 2025-12-31 comparisons instead of older 2024-12-31 facts. Its persisted references bind the filing URL and dates; their generic extraction_method label is not evidence of the parsing route by itself.
- Stage-ledger rows are checked against fixed caps. A document requested from the wrong stage is refused before its native exchange. Old approval manifests cannot authorize this variant. Missing approval cannot launch the approved entrypoint.

An earlier combined run hit the repository's 30-second per-test watchdog during execution-service instability. It is not counted as a pass; the completed rerun of all 16 new tests passed in 24.32 seconds. Subsequent execution-service disconnects interrupted compatibility work; only completed results are counted. The final compatibility group completed successfully in 437.07 seconds. Required hosted CI results must still be reviewed before merge.

## Remaining limits and next gate

Synthetic data does not establish ACHC's live financial freshness, ASML/NPK live completion, foreign-filing coverage, complete thesis quality or launch readiness. A historical margin remains a monitoring benchmark, never a buy/sell threshold or valuation.

Review the exact diff and required hosted CI before merge. After merge, a separate session may prepare a package against the exact merged commit and its own validated environment, then stop for fresh single-run authorization. Do not execute a pilot from this review document.
