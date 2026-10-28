# Ordinary twelve-case pilot: integrated native path (disabled)

Base: PR #350 head `6090ce050b1618fc7bf4fa453148731c82653d27` on
`pilot/offline-ordinary-accounting`. Main was `2b31b14` (after PR #349).
Cohort: NPK, GOOGL, INGR, NNBR, AMZN, MAN. Each issuer has `core_thesis`
then `decision_threshold`, from `tests/ordinary_pilot_cases.json`. The
projection hash is `fa9159ab…08747e3`.

No live request, approval, spending, deployment or configuration change is
part of this work. Every source body below is invented. The approvals used
offline are invented `TEST-ONLY-NOT-AN-APPROVAL` records and grant nothing.

## What PR #350 had, and the defects

PR #350 contained two disconnected stacks:

- **Rehearsal stack.** `OfflineAccounting` with its lifecycle, coordinator,
  artifacts, wire rehearsal, worker and supervisor. It ran the real pipeline
  on simulated accounting.
- **Native stack.** `OrdinaryNativeLedger`, `OrdinaryNativeGate`,
  `OrdinaryHTTPTransport` and `exchange_sec`. These were only unit-tested;
  no worker used them.

Concrete defects, each verified by reading the code and then by running it:

1. **No integration.** The worker never touched the native ledger, gate or
   transport. It also replaced `verify_network_configuration` with a stub.
2. **Limits enforced by halting, not pacing.** A 5th outstanding request or
   an 11th wire entry within one second halted the run, and `exchange_sec`
   treated the ledger's own `RateLimitDelay` as fatal. The evidence pool runs
   SEC stages in parallel, so a real core case would halt itself. The
   integrated rehearsal reaches 4 in flight, and before the fix its pacing
   would otherwise have halted the run on dozens of claims.
3. **Strict UTF-8 screening.** Retention decoded every body as strict UTF-8.
   An EDGAR filing containing a single Windows-1252 byte would halt the run.
4. **No document admission.** Filing documents were not admitted at all. The
   fixture helper required an artificial single-row 10-K response.
5. **Conflicting output ownership.** The native ledger created its output
   directory, while the launcher created the same directory before spawning.
6. **First cause lost.** `exchange_sec` collapsed every failure into
   `invalid_response` and never recorded the transport code.
7. **No native lifecycle.** There was no atomic answer-plus-case completion,
   no parent-side export from the native ledger, and no record of failed
   exchanges beyond the first.

## The integrated path

- **`validation/ordinary_native_boundary.py`.** A `PilotBoundary` subclass
  on the same pattern as the historical `ApprovedBoundary`. Each SEC GET the
  application makes goes through, in order:
  1. the route and stage check (exact issuer URLs; documents only if
     admitted);
  2. a nontransferable stage reservation;
  3. a wait for one of 4 slots, bounded by the case deadline;
  4. a paced durable dispatch claim;
  5. `OrdinaryNativeGate`, which records native intent and then the durable
     wire entry, pacing at 10/s;
  6. `OrdinaryHTTPTransport`;
  7. semantic admission;
  8. `complete_response`, which retains body and receipt before settlement.

  The first meaningful cause is recorded, and every failed exchange gets a
  fixed-code row. Any model request halts. Paid-provider keys must be absent,
  and non-SEC requests are refused.
- **Filing documents.** Admitted only from a validated submissions response
  for the same case and stage, using `submission_documents()`. That parser
  was extracted unchanged from `LiveAdapterBoundary.sec_content`, so the
  historical path and this one share one implementation. It handles
  multi-row responses, the supported form set, accession syntax, unfetchable
  filenames (excluded) and inconsistent rows. Drift between submissions
  within a case halts.
- **`OrdinaryNativeLedger`.**
  - The launcher owns output creation (`create_fresh_output`). The ledger
    accepts only that exact fresh state: 0700, empty `isolated-home`, the
    launcher's `request.json`. It then creates its file exclusively. There is
    no resume.
  - Rate excess paces; concurrency excess halts.
  - Screening checks raw bytes, then parsed JSON or entity-decoded text.
  - `complete_case` retains the whole answer and finishes the case in one
    transaction; `finish_case` cannot finish without an answer.
- **`ordinary_native_export.py`.** Parent-side, read-only export after the
  child exits or is killed and reaped. It records the parent's stop reason
  first, which also rolls back a killed child's hot journal. It verifies:
  - the policy hash, case order and deadlines;
  - quotas against the frozen contract;
  - every receipt against its immutable request digest, and body hashes;
  - native intent before every wire entry;
  - at most 10 entries per second and 4 concurrent entries, from durable
    timestamps;
  - answers belonging to completed cases.

  It reports all twelve outcomes and refuses inconsistent records, including
  mistyped stored values.
- **Worker and launcher.**
  - Fences are installed before application imports.
  - The worker verifies that the actually loaded code (content hash) and
    dependency versions match the bound policy, and runs the real
    proxy/CA-identity check before creating the ledger.
  - Each case runs under the parent's existing deadline protocol: 30 s
    thesis, 20 s threshold, 480 s whole run. On expiry the parent kills and
    reaps the child.
  - The DNS rule is the historical approved worker's: inside a claimed
    exchange only the proxy resolves, via the gate. The application's SSRF
    check for exact SEC hosts receives a fixed invented public address. This
    neutralises that application check by design, because every request
    travels via the reviewed proxy to the exact claimed URL.
- **`_ordinary_synthetic_sec.py`.** Invented directory, multi-row
  submissions, companyfacts and filing HTML beneath the gate's
  `ScopedBackend`, with one-shot faults. There is no live backend and no live
  entrypoint anywhere in this path.
- **Retired.** `OfflineAccounting` and its lifecycle, coordinator,
  artifacts, wire rehearsal, offline runner, `exchange_sec`, and their tests.
  Their properties were re-established on the native path: quota and stage
  exhaustion, case order and deadlines, no late work, answer screening and
  immutability, export tamper detection, document sequencing, transport
  request-form refusal and the reviewed-envelope ban. The route-parity test
  keeps its application-level assertions and drops only its fixture-transport
  variants.

## Contract amendment (decided by the project owner on 2026-10-29)

The frontend calls `/ask` with `company_name=""`
(`frontend_cinematic/app/(product)/analyze/page.tsx`), so `route_question`
resolves the company from the question text. For issuers missing from the
local company database (NPK, INGR, NNBR), that calls `discover_company`,
which fetches the SEC directory before any evidence stage. The original
per-stage quotas had no slot for that request, so the frontend-shaped
request halted on NPK, case 1.

Option (a) was chosen. Every case gains a `routing` stage that admits
exactly one `sec/directory` request and nothing else. The per-case totals
(8/3 SEC, 2/1 directory) and the 66-request overall total are unchanged. The
routing directory response is shared, so the pipeline's directory step reuses
it instead of making a second request. The proposal manifest therefore
changes, and any approval must bind the amended contract.

The main rehearsal now enters exactly as the frontend does, through
`route_question(question, company_name="")` inside the `routing` stage. It
runs in authenticated mode (`AUTH_ENABLED=true`, pinned in the policy), as
production `/ask` does. In unauthenticated mode the router writes the legacy
global watchlist and history, including a database write; a pilot must not
perform those.

## Application fix: short registrant names with their legal form (NNBR)

The NNBR questions name the company "NN INC", which is also its SEC
registrant name. The directory indexes names by `name_key`, which strips the
legal form, so NNBR is indexed as "nn". Question windows were compared as raw
words. The window "nn inc" never equalled "nn", and the single word "nn" is
below the five-character minimum. The frontend-shaped `/ask` therefore
returned an unresolved-identity response for both NNBR cases.

The same defect made "Compare NN INC with WD-40 CO" silently resolve to WD-40
alone.

Fix (`issuer_identity.discover_company`, free text only): a multi-word window
that ends in an explicit legal form (Inc, Corp, Co, Ltd, …) also matches its
`name_key`. The legal form makes a short name exact. These are still refused:
- a bare short word ("nn");
- an uppercase token that is not a ticker ("NN");
- a stop-word legal name;
- a short name shared by two registrants ("AB INC" and "AB CORP");
- a question naming two issuers.

Tests reproduce the defect through `discover_company` and through
`route_question` with `company_name=""`. All 2,267 tests in the 49 identity,
detection and routing test files pass, against 2,257 before the 10 new tests.
The two non-equivalent mutations of the fix are killed.

An answer naming no issuer is still retained and reported as
`identity_unresolved`, never as a pass. One naming another issuer still halts
as drift.

## Evidence, all offline (sockets refused, invented credentials and sources)

- **Happy run through the frontend-shaped `/ask` path.** 12 of 12 cases are
  answered, and every company, NNBR included, is identified from the question
  text.
  - 60 SEC exchanges: 7 per thesis case and 3 per threshold case. All are
    within the contract and retained before settlement.
  - The routing slot was used exactly once (NPK, case 1), and that case made
    no second directory request.
  - Every answer reference traces to a retained body, a document admitted by
    that case's own retained submissions, or a filing-index page for an
    accession those submissions list.
  - 0 model requests, 0 blocked external operations, 0 unfinished tasks.
- **Read failure, redirect, oversize body, connect failure.** In each case
  the first cause is preserved (`read_error`, `http_redirect`,
  `response_size`, `connect_error`). In-flight siblings are recorded honestly
  with no fabricated body or receipt. All twelve outcomes are reported.
- **Stalled peer.** The parent killed the child at about 30.0 s (thesis) or
  about 20.0 s (threshold) and exported from the durable ledger, without
  trusting the killed worker's report.
- **Mismatched source hash or CA identity.** The worker refuses before any
  ledger, gate or request.
- **Mutation testing.** 26 of 26 live targeted mutations on the pilot path
  are killed, plus 2 of 2 on the identity fix. They include the routing slot
  and its directory-only scope, the authenticated-mode pin and setting, drift
  versus unresolved answers, and every export check.
- **Hosted CI on the previous head `d33e726`.** All 15 steps passed,
  including the full isolated-per-file regression. A local replica of every
  gate showed the same result, apart from four files that fail identically on
  the unmodified base on macOS: `/tmp` symlink literals, a local-date-vs-UTC
  test, and an interpreter-shutdown flake.

## Not established

- **Not real research quality.** Answers built from invented filings are not
  research quality, citation support or source authenticity. Hashes show
  integrity only.
- **Not real network behaviour.** Neither physical connection timing, SEC
  arrival timing nor real SEC response sizes are established. Rate and
  concurrency are enforced and recorded at owned HTTPX entry.
- **Not authenticated or browser coverage.** The `/ask` authentication
  preflight, ownership, persistence of owned history and streaming layers are
  not exercised. Only `route_question` and the pipeline are, in authenticated
  mode.
- **Not a cost ceiling.** Zero model and provider calls do not establish an
  all-in invoice ceiling (`invoice_ceiling_verified=False`).
- **Not reviewed.** No independent review has occurred.
