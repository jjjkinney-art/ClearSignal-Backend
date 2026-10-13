# Reviewed SEC document envelope

Base: `4e855a824f32e11317363765ddaf50d96bbb8c58` (merged PR #279).
Base source binding, independently recomputed from that checkout:
`8f72f614601dcce55628faa2fe8e490a544d1c493a3ddd6feaee8c58a8c091cc`.

## Evidence and what it does and does not establish

The latest approved pilot halted on ASML with first transport-failure code
`response_size`, route `sec/document`, stage `evidence.thesis_disclosures`,
after five settled SEC requests (one directory, one facts, three
submissions), with one unresolved document claim, zero completed cases and
zero model calls. The saved request fingerprint matches the reviewed
registry URL
`https://www.sec.gov/Archives/edgar/data/937966/000162828026011378/asml-20251231.htm`.

`OwnedHTTPTransport.exchange` raises `response_size` only after HTTP 200 and
identity encoding, when retained streamed bytes plus the next raw chunk
exceed `MAX_RESPONSE_BYTES` (16,777,216). The code therefore proves the
streamed body crossed 16,777,216 bytes. It does not establish the media
type, filing contents, canonical hash, total length, authentication, or
that the body fits within 30,000,000 bytes. None of those are assumed here.

Root cause: the application's reviewed annual-layout registry already
admits this exact document at up to 30,000,000 bytes, with a mandatory
canonical-hash check, but the benchmark transport applied its 16 MiB
envelope to every route. The transport refused a document the application
contract permits before the application could validate it.

## Change and authorization boundary

- `MAX_RESPONSE_BYTES` is unchanged for every route. `REVIEWED_DOCUMENT_MAX_BYTES`
  is a constant (30,000,000). It is not a parameter, and `exchange` accepts
  no caller limit.
- On each validated `sec/submissions` response, the boundary records
  `(form, filingDate)` for every admitted document URL. Rows are recorded
  only if `filingDate` is a list aligned with the other recent arrays. Rows
  that disagree about one URL make it ambiguous, and it gets no record.
  A later submissions response with different metadata halts with
  `configuration_drift`, exactly as a changed URL set already did.
- The transport mints a `ReviewedDocumentEnvelope` only when
  `reviewed_annual_layout(url, form, filed_at, cik=cik)` matches the exact
  URL, form, filing date and 10-digit issuer CIK, and the registry entry
  states exactly 30,000,000 bytes. A registry edit cannot widen the
  transport. A conflicting second mint withdraws the authorization.
- For `sec/document` only, the boundary passes the envelope when both its
  own submission record and the transport's mint exist for the current
  issuer's CIK and URL. The transport then requires that exact minted
  object (identity, not equality), a GET to that URL under
  `www.sec.gov/Archives/edgar/data/`, a fresh registry re-derivation, and
  with the approved exchange gate a claimed `sec/document` route. Any
  mismatch is `request_gate` before dispatch.
- Why unrelated documents cannot receive the envelope: the decision reads
  only boundary-validated submissions data and the registry. No request
  header, ticker, caller value, URL alone or caller-constructed object
  affects it. Another issuer's submissions produce URLs under its own CIK,
  which never equal the registry URL, and the registry also checks the CIK.
- `Content-Length` is checked strictly. More than one value, or anything but
  1 to 15 ASCII digits, is `protocol_error`. A declaration above the active
  envelope is `response_size` before the body is read. A declaration never
  admits anything: observed streamed bytes are enforced regardless. h11
  itself already rejects signed or conflicting values, and collapses
  identical duplicates.
- Reads are httpcore's fixed 64 KiB socket reads (pinned httpcore 1.0.9).
  The growable buffer never exceeds the envelope. It is copied once to an
  immutable payload and cleared before validation. The previous code made
  up to three copies on the runtime path. On overflow the exchange raises
  and closes the response, and the first failure code survives a failing
  close.
- Complete-body validation is unchanged: SEC media type, credential and
  runtime reflection on the whole payload, then the application's own
  bounded read and canonical-hash check. SEC settlement still does not
  imply usable evidence.

Memory, measured on synthetic I/O (macOS, CPython 3.11.9) for one
30,000,000-byte reviewed document:

| Path | Peak RSS increase |
|---|---|
| Transport only | 60.1 MB (2.00× body) |
| Transport, bridge and application up to its hash rejection | 91.7 MB (3.06× body) |

A body whose hash matches proceeds to decoding and HTML parsing and will use
more. Process RSS is not bounded by the cap.

Unchanged: global cap, no truncation, no fallback or substitute filing, no
redirects, retries or replays, operation and inactivity timeouts (10 s for
SEC), stage supervision, the 480-second run deadline, quotas, claims,
durable halts, late-worker fencing, proxy and CA validation, credential
canaries, frozen scope and model routes. FMP, NewsAPI and FRED remain
excluded. The synthetic bridge still forwards Content-Type only.

## Validation (offline, pinned CPython 3.11.9, audited dependencies)

The harness used invented credentials and synthetic socket I/O, with an
invented HOME. An audit hook refused external DNS, external connections and
real-home file access.

- New `tests/test_sec_document_envelope.py`: 73 passed. It covers exact
  authorization versus wrong URL, CIK, form, date, accession and aligned
  dates; missing submissions; forged envelopes; both byte boundaries
  (30,000,000 accepted; 30,000,001 rejected with Content-Length,
  close-delimited and chunked framing); ordinary document, JSON and model
  envelopes at 16,777,216 and 16,777,217; malformed, duplicate, misleading
  and over-limit Content-Length; bounded reads and close; first cause
  preserved over a failing close; read timeout; reflection and media on
  large bodies; downstream canonical-hash rejection through the real bridge;
  the approved gate path; and two isolated-worker scenarios. The overflow
  scenario reproduces the observed halt shape at 30,000,001 bytes.
- Mutation check: 20 of 20 mutants killed. The first pass killed 16, and the
  four weak tests it exposed were strengthened.
- Focused pilot and ingestion suite (36 existing files plus the new file):
  1,615 passed. The same suite on the unmodified base passed 1,542.
- CI replica: import smoke (135 routes); collection (17,024 tests, 0
  errors); all five grouped gates (80, 87, 221, 178 and 195 passed); and 431
  test files each run in a fresh interpreter, with 16,953 passed, 71 skipped
  and 1 failed.
- That failure is unrelated and recorded as initial:
  `test_personal_experience_brief_service.py::TestBuildDailyBrief::test_brief_date_defaults_to_today`
  compares a UTC brief date with the local `date.today()`. It fails
  identically on the unmodified base when local date ≠ UTC date (local
  NZDT 2026-10-14, UTC 2026-10-13). It passes on this branch with
  `TZ=UTC`, which is what the hosted runner uses.
- Local host adaptations, not committed:
  - macOS bash 3.2 lacks `mapfile`, so the per-file loop used an equivalent
    NUL-safe read loop.
  - `/tmp` is a symlink on macOS, so one approved-test default path was
    substituted with its resolved spelling at collection time.
  - The worker reports a Linux uname, so `distro` would shell out to
    `lsb_release`. Its subprocess probes were disabled to match Linux.
  - All were applied identically to base and branch. Hosted CI must still
    pass on the published head.

Branch source binding: `e2ac3aa37b82212e30e9e5070c30401630c3194d77e030336d49f83f52271cdc`.

## Not established and live-verification requirements

Offline tests do not prove the real filing is at most 30,000,000 bytes,
downloads within the SEC operation timeouts and stage supervision, carries
an accepted media type, or matches the registered canonical hash. A
compliant download could still fail closed on any of these, and that would
be the correct result.

All four live approvals are consumed. A future run needs:

- a new separate approval bound to this reviewed code (the new source
  binding and revision);
- a separately validated execution configuration (the historical hash is
  evidence only);
- a fresh output directory and ledger, with no resume or reset;
- an explicit spending decision. The $0.52 ledger allowance is not an
  invoice ceiling.

Merge, deployment and launch readiness are not claimed. Passing offline
tests does not resolve the launch blocker.
