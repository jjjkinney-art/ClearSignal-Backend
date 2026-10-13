# Disabled benchmark live-adapter slice

Base: `85356c705a8ca7fa3db062f15f11c74681aa0d3b` (PR273).

This change adds a separate benchmark entrypoint:

```sh
python -m validation.pilot_live --output-dir /new/empty/output
```

It runs the six frozen development questions through the real investment pipeline and the owned HTTPX/httpcore HTTP transport, using internal synthetic socket streams. Real sockets remain prohibited by the isolated worker. The transport also refuses dispatch unless its backend is the exact internal synthetic backend. There is no execute, credential, approval, capture, resume, custom transport, or spending switch. This is a disabled adapter implementation, not authorization or readiness for a provider run.

The adapter retains schema 2 with an explicit `disabled_live_adapter_validation` purpose and a distinct pilot ID. Both modes retain the fixed quota, pacing, file identity, reopen, durable halt, atomic claim, and late-worker fences. Authority flags remain false. No schema 1 fallback exists.

Only the three frozen issuers and six questions are admitted. Core routes remain source-only. Threshold routes retain `gpt-4o-mini`, explicit default tier, full 128,000-input-token reservation, and stage-specific bounded output. Model attempts remain capped at 24 and SEC GETs at 30 with nontransferable case/stage quotas. FMP, NewsAPI and FRED remain excluded. The $0.5105664 token allocation is illustrative accounting, not an invoice ceiling or spending authorization.

The owned transport reconstructs headers from constants, disables retries and ambient environment/proxy discovery, follows no redirects, accepts only HTTP 200, rejects compressed responses, and caps response bodies at 16 MiB. The single exception is a fixed 30,000,000-byte envelope for an exact reviewed annual-layout registry document, authorized by validated submissions metadata; see `SEC_DOCUMENT_REVIEWED_ENVELOPE_20261014.md`. Incoming authorization/header values are not forwarded. Its invented bearer placeholder preserves the shape needed by environment-managed network-secret substitution without reading an actual credential. Substitution and authenticated execution are not exercised or enabled here.

SEC directory responses may contain other issuers, but each frozen ticker must occur exactly once with the reviewed CIK. Document routes are exact URLs derived from validated submission CIK/accession/primary-document tuples and frozen on first observation; repeated submissions cannot replace the admitted set. An accession's submitter prefix need not equal the issuer CIK. Encoded paths, traversal, alternate hosts and invented `report.htm` routes are not admitted.

Model responses accept harmless `refusal: null` and `annotations: []`, while tools, audio, unknown usage units, incomplete choices and excessive usage halt the run. Completed artifacts include pipeline answers/evidence and validated token/model/tier metadata. Response bodies and artifacts reject invented credential canaries; headers and transport exceptions are never persisted.

The whole-run deadline is 480 seconds: three source cases at 20 seconds, three threshold cases at 10 + 16 + 56 + 42 seconds, three seconds of existing drain allowance per case, and 30 seconds for startup/publication. Individual pipeline stage limits remain unchanged.

## Local verification

Runtime: CPython 3.11.9, with repository requirements and audited openai 2.32.0, httpx 0.28.1, httpcore 1.0.9, requests 2.32.5, urllib3 2.8.0 verified before tests.

```sh
/workspace/clearsignal-venv/bin/python -m pytest --confcutdir=tests \
  tests/test_pilot_live.py tests/test_pilot_policy_ledger.py \
  tests/test_pilot_rehearsal.py tests/test_pilot_preflight.py \
  tests/test_pilot_netrc_isolation.py -q
```

`--confcutdir=tests` excludes the production-importing repository conftest; integrated checks import the application only inside credential-isolated, socket-blocked children. Tests cover the actual HTTP protocol path with fake I/O, redirects, connection/read failures, size bounds, ordinary model responses, full directories, real-shaped accessions, exact document routes, usage rejection, quotas, concurrent claims, reopen/file replacement fencing, late workers and credential canaries.

One existing fault-test assertion was corrected for a legitimate concurrency interleaving: a worker can reserve before another worker halts, then be fenced before claiming. The test now reconciles persisted pending reservations separately from dispatch claims; it does not refund or allow those reservations to dispatch.

No production application files changed. Exact-diff independent review and required CI remain necessary before publication/merge. Launch quality is not adjudicated, live provider execution remains disabled, and this change does not declare the launch blocker resolved.
