# Shared SEC issuer-directory response

Base: `531c764054cda8008cf15287dc5eaf29add19dbe` (merged PR #280).
Base source binding, recomputed from that checkout:
`e2ac3aa37b82212e30e9e5070c30401630c3194d77e030336d49f83f52271cdc`.

## Evidence and verified cause

Run `reviewed-envelope-531c7640-20261014-01` halted with `stage_timeout`.
It completed 0 of 6 cases and made no model calls. Six SEC exchanges settled
and one second-directory claim from `thesis_disclosures` stayed unresolved;
it was claimed 19.870 s after the first SEC claim, near the unchanged
20-second evidence deadline. No transport failure or SEC refusal was
recorded.

The base source has two directory consumers. Each has its own cache and
issues its own GET of `https://www.sec.gov/files/company_tickers.json`
through `sec_provider._fetch_json`:

- `sec_provider._load_ticker_cik_map()` builds the reduced ticker→CIK map.
  It caches for the process lifetime and caches a failure as `{}`. The pilot
  worker resets it at the start of every case to rehearse the cold-directory
  allowance.
- `issuer_identity._load_directory()` builds the richer `Directory` of
  symbols, titles, name index and conflict withholding. It has a 3600 s TTL
  and a 30 s retry gate, and the worker never resets it.

The base offline rehearsal reproduces the duplicate. With `happy`,
`ASML:core_thesis` makes two `sec/directory` claims and every other case
makes one. With `reviewed_document_admitted`, where ASML fails the canonical
hash, ASML makes one; the identity-side fetch moves to the next case that
needs identity.

A stack trace taken in the isolated worker at the identity fetch shows:

```
fetch_thesis_disclosures → extract_issuer_risk_evidence
  → requested_risk_profile → _load_directory
```

That path runs only after `fetch_public_document` has returned, which
supports, by control flow only, that application validation and parsing
completed in the live run.

Remaining uncertainty:

- The live run did not save its halt time or pending futures. Stage
  expiration and cleanup timeout therefore remain indistinguishable.
- Removing one GET does not prove the remaining risk extraction finishes
  inside 20 s against the real filing. Only a separately approved run can
  show that.

## Change: cache ownership, freshness and isolation

`sec_provider.shared_company_tickers(max_age, timeout)` owns one shared copy
of the full parsed response. Each consumer still owns its own semantic cache,
validation and failure policy.

**Eligibility.** A response is reused only when both of these hold:

- Its binding is the same: URL, `sec_provider._fetch_json`, the module
  `urlopen`, `urllib.request.urlopen` and `OpenerDirector.open`, all compared
  by identity. Swapping any fetch path — a test transport, the pilot bridge
  or another configuration — forces a new fetch.
- It is younger than the caller's maximum age (3600 s for both consumers).

Freshness is anchored at a monotonic reading taken before the request.
`issuer_identity` sets its expiry from that time, not from reuse, so sharing
cannot stretch its one-hour freshness.

**Validation and copies.**

- Only a non-empty JSON object is retained. Malformed and empty responses are
  never shared.
- The stored copy and every returned copy are deep copies, so a consumer's
  mutation never reaches another consumer.
- If `issuer_identity` rejects a response (no valid symbols), it discards
  that exact generation, so its 30 s retry fetches again rather than reusing
  the rejected response. A rejection never discards a newer response.

**Concurrency.** One lock gives a single in-flight fetch, and it is always
the innermost lock (no inversion with either consumer lock). Waiters that
were queued behind a failed fetch receive that failure instead of fetching
again; a caller arriving afterwards may retry. Each consumer then applies its
existing failure policy unchanged: the ticker map withholds for the process,
and identity retries after 30 s.

**Run isolation.**

- Pilot runs execute in separate isolated processes, so nothing is shared
  across runs.
- The worker resets the shared response together with the ticker map at the
  start of every case. Each case keeps its own cold directory GET.
- Only the redundant identity-side GET disappears, removing at most one
  `sec/directory` claim per run.

**Unchanged.** Semantic validation, ambiguity and conflict withholding,
consumer outputs, quotas, deadlines, timeouts, retries and redirects, claims,
halts, fencing, credential isolation, the frozen scope and PR #280's envelope.

`tests/test_pilot_rehearsal.py` pinned 27 SEC claims for the frozen
rehearsal, which included the duplicate. It now pins 26, and it also asserts
exactly one directory claim per case.

## Validation (offline, CPython 3.11.9, audited dependencies)

Directory rows are invented, fetches are counting fakes, time uses a
controlled clock and concurrency uses explicit events. An audit hook refused
external DNS, external connections and real-home files.

New `tests/test_shared_sec_directory.py` (27 tests) covers:

- both consumer orders, and concurrent sharing of one in-flight fetch;
- a shared failure followed by recovery;
- ambiguous and conflicting identities, unsupported rows and malformed
  responses;
- rejection and discard;
- full-response preservation and mutation isolation;
- maximum age and expiry anchoring;
- isolation across fetch function, urllib entry points and reset;
- risk-profile reuse;
- the isolated worker, where risk extraction runs and no second directory
  GET occurs, and where a canonical-hash failure still prevents risk
  extraction;
- a late directory claim staying unresolved and fenced after
  `stage_timeout`;
- unchanged quotas and deadlines.

Fifteen of fifteen targeted mutations are killed.

Results:

- New tests: 27 passed. Rehearsal and new tests together: 70 passed.
- Related identity, SEC and pilot suites (68 files, run together):
  - base: 3,344 passed, 4 failed;
  - branch before the expectation update: 3,341 passed, 7 failed.
  - All four base failures, and the same four on the branch, are
    `routing_regression_tests.py::TestFrontendActiveTicker`. They read
    frontend files absent from this checkout, and CI's `test_*.py` loop does
    not run that file.
  - The three branch-only failures were the rehearsal's former
    `'sec': 27` expectation, updated as described above.
- CI replica, on CPython 3.11.9 with the audited dependencies:
  - import smoke: 135 routes;
  - collection: 17,052 tests, 0 errors;
  - five grouped gates: 80, 87, 221, 178 and 195 passed;
  - 432 files, each run separately: 16,981 passed, 71 skipped, 1 failed.
- The single failure,
  `test_personal_experience_brief_service.py::TestBuildDailyBrief::test_brief_date_defaults_to_today`,
  compares a UTC brief date with the local `date.today()`.
  - It fails identically on the unmodified base when the local date differs
    from UTC (NZDT 2026-10-14, UTC 2026-10-13).
  - It passes on this branch with `TZ=UTC`, as the hosted runner uses.
- The offline guard refused 12 external DNS lookups made by pre-existing
  tests; those tests passed anyway.
- Local macOS host adaptations, not committed, were applied identically to
  base and branch:
  - a bash 3.2 loop in place of `mapfile`;
  - the resolved `/tmp` path in one approved-test default;
  - `distro` subprocess probes disabled, because the worker reports a Linux
    uname.
- Hosted CI must pass on the published head.

Branch source binding: `3842e6e50f36c00e89909527cfa5a6ba7edd0ca5ef537b28ca92ada01323ae81`.

## Not established

This is offline only. The timeout and the broader launch blocker are not
live-confirmed fixed. A future pilot needs exact-diff review, required
hosted checks, and a new separate approval bound to this code and a validated
configuration, with a fresh output directory and an explicit spending
decision. All five previous live approvals are consumed.
