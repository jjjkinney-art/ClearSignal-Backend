# Pilot transport diagnostics review

Base: `0110c2bcf4fd8b8ed5150635531627f795f83228` (merged PR #278).
Recovered input patch SHA-256: `a516e2fa276bafdc4d43a9d243cc5ab445f6017d2043b21b8209ec8ea00999af`.

## Observed live evidence and limits

The handoff reports five settled SEC requests, an unresolved first document
request, a `post_claim_failure` halt, no completed questions and no model
calls. The original exception was discarded. The original run artifacts are
not present in this review workspace; these live observations are supplied
by the handoff, not independently reconstructed here.

Multiple HTTP, transport, response-admission and cleanup failures can collapse
to this halt. Offline reproductions do not identify the historical cause.
Do not infer a 403, timeout, compression, document-size or TLS diagnosis.

## Review and correction

The patch records fixed codes only, bound to an existing claimed attempt and
an allowlisted route and stage. First-cause insertion and the halt share a
transaction. Later failures and cleanup do not replace an existing halt.
Old ledgers are readable without migration or retrospective cause invention.
Exception messages, provider bodies, headers and URLs are not diagnostic data.

Transport cleanup preserves a prior failure, and worker cleanup failure no
longer prevents terminal publication. Review found a second evidence-loss
path in the parent launcher: a nonzero worker exit after publication replaced
the terminal artifact. The final change leaves `artifact.json` byte-identical
and publishes the parent `worker_incomplete` verdict in
`launcher-failure.json`, including the available worker evidence. The launcher
returns the incomplete verdict even if the worker had published `complete`.

44 diagnostic tests pass, including primary-failure/close-failure precedence,
concurrent first-cause insertion, private-value rejection, legacy ledgers,
document fault partitions and both parent publication cases. All tests use
invented credentials and synthetic transport I/O. The review test harness
blocks Internet connections, external DNS and real credential files.

Final pinned CPython 3.11.9 validation completed 437 jobs: import and
collection, all five CI grouped gates, and isolated execution of all 430 test
files. The combined seven-file pilot suite passed 278 tests. Initial isolated
totals were 16,880 passed, 71 skipped and one failure. The unchanged
`test_beta_admission_cli.py::TestRefusals::test_unreachable_database_refuses_sanitised`
subprocess exited with -6 instead of 2. A focused comparison passed on both
unchanged base (0.81s) and final patch (0.56s), followed by 56/56 passing on
the entire CLI file. No application source was changed for that recheck.
The initial failure remains recorded; this is not a claim that the first full
run was uniformly green. Required hosted checks must pass on the published
head before merge.

## Scope and next investigation

No safety checks, host/CIK/accession/filename admission, redirects, retries,
timeouts, quotas, reserves, model allocations or execution authority change.
An unresolved dispatch remains unresolved; diagnostics do not settle it or
authorize replay. Application production code is unchanged.

All three prior live approvals are consumed. No live pilot was run during
this review. A fresh approval must bind the final reviewed code, execution
configuration, fresh run directory and budget before another live pilot.
That run can provide the first retained transport code; any fix must then be
supported by that evidence. Quality and launch readiness remain unadjudicated.
