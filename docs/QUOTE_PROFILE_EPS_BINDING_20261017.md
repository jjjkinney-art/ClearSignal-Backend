# Quote/profile/EPS binding — 17 October 2026 Auckland

Base: `62d6e3ebc93b73cdb3db36c0e188bad7116c34a8` (merged/deployed PR303).

## What this increment resolves

PR303 left currency and issuer identity absent because the reviewed quote schema
does not establish them. This increment binds a separate saved stable profile
to that quote and reconstructs its issuer's annual USD diluted-EPS pair using
the existing producer/reference contract. It detects cross-source symbol, CIK,
exchange-label and currency-label inconsistencies. All three inputs retain
their own source bindings. No profile snapshot price is used.

`validation.quote_eps_binding.assess_quote_eps_binding` consumes raw quote and
profile bytes with separate receipts, producer EPS items, final response
references, an exact expected symbol/ten-digit CIK, explicit analysis/evaluation
times and separate quote/profile age policies. Caller-authored passing reports
are not accepted as substitutes for those inputs.

This is an offline consistency report, not a live adapter, admitted price or P/E
calculator. Successful output is `binding_passed=true`, `status=partial`,
`admitted=false`, `launch_ready=false`. Security mapping, EPS compatibility,
market P/E and independent-adjudication flags remain false. No production module
imports it and no application evidence or scenario route changes.

## Reviewed provider schema

Official sources inspected on 17 October 2026 Auckland without API calls:

- [Company Profile Data API](https://site.financialmodelingprep.com/developer/docs/stable/profile-symbol).
- [Company Profile by CIK](https://site.financialmodelingprep.com/developer/docs/stable/profile-cik), whose displayed profile schema also includes the identifier/currency/flag fields.

The stable profile schema supplies a symbol, CIK, currency, exchange label,
ISIN and ADR/ETF/fund/active-trading flags. Those fields are secondary-provider
assertions, not an authoritative share-class, split or MIC mapping. In particular,
an agreement between profile currency and EPS currency does not by itself prove
the quote's currency or per-common-share unit. The report leaves the original
quote candidate's currency and unit null rather than rewriting its provenance.
No claim that the provider has no other mapping datasets is made.

## Binding rules

1. Re-run PR303's raw quote parser with the exact expected symbol and supplied
   quote policy. Quote failures cannot be replaced by a profile price or IPO date.
2. Parse at most 65,536 immutable profile bytes with duplicate-key detection,
   bounded numeric-token parsing and sanitized failure diagnostics. Require one
   record, a matching SHA-256/length receipt, exact stable-profile endpoint
   identity, requested symbol, canonical JSON media label and integer HTTP 200.
   Credential-bearing request URLs and arbitrary receipt extras are rejected.
3. Require exact symbol and expected CIK, explicit USD and an exchange label
   identical to the quote's provider label. The initial currency capability is
   USD only; no FX conversion or currency default. Keep an explicit provider ISIN
   with structural validation only. Its checksum and actual security mapping
   remain unverified. Require boolean false ADR/ETF/fund flags and boolean true
   active-trading flag. Numeric zero/one and strings cannot stand in for booleans.
   These flags still do not prove a common-share class or exclude every other
   unsupported instrument. Legacy profile payloads are not silently translated.
4. Require profile retrieval no later than analysis/evaluation. Apply an explicit
   profile retrieval-age tolerance with policy ID and integer seconds in the same
   0–604800 computational range as the earlier audit. This is not approval of a
   real market freshness threshold. Profile retrieval age is not source effective
   time: profile `source_observation_time` remains null. Profile price/timestamp,
   share-class hints, IPO date and arbitrary extras are ignored, not trusted.
5. Reconstruct EPS via the existing `_source_eps` contract against the expected
   CIK/symbol and exact admitted response reference. It still requires an available,
   unambiguous annual USD diluted-EPS comparison, positive current EPS, matching
   filing/period/claim metadata, and evidence available by the analysis date.
   Wrong issuer, currency, raw value, period, reference or freshness fails closed.
   Quarterly EPS is never annualized. The source retains its actual fiscal-year
   start/end, filing date and final response reference ID.

On failure, no partially bound source objects are returned. Only fixed status,
reason, bounded stage label and exception-class diagnostic are emitted. Error
messages, arbitrary source fields and endpoint query strings are never echoed.

## What remains unresolved

The report does not authenticate any supplied receipt or expected issuer mapping.
A fabricated body with a recomputed receipt can pass consistency; a test keeps
this limitation explicit. Documentation URLs describe fields, not inspectable
individual price observations. No real profile or quote body was captured here.

Profile data may not describe the mapping effective at an earlier quote date.
Its retrieval time is insufficient proof of that historical mapping. The report
does not establish common-share unit, share class, corporate actions/split basis,
EPS earnings-scope equivalence, a regular-session trade/official close, or an
approved freshness/session policy. SEC filing dates lack intraday availability
proof. Historical annual EPS remains historical annual EPS, never TTM or forward.

Consequently no price/EPS ratio, return, growth assumption or buy/sell threshold
is calculated. Existing PR302 trade/close admission and PR300's hypothetical-price
scenario contract remain unchanged. A linked candidate still fails the existing
source-price scenario gate. Useful-answer and launch readiness are not inferred
from a passing consistency report. Next work must establish actual security/share
and split compatibility and an admissible observation path before valuation.

## Verification

87 new cases cover the full raw quote/profile/reconstructed-EPS path, exact
reference IDs, profile hash/receipt corruption, mismatch and type failures,
duplicate/malformed/bounded JSON, missing flags, currency/identity/period errors,
retrieval chronology and age boundaries, alias isolation, source-hint
non-authority, recomputed-fabrication limitations and unchanged scenario rejection.

752 related tests passed without warnings on CPython 3.11.9 with audited versions
openai 2.32.0, httpx 0.28.1, httpcore 1.0.9, requests 2.32.5 and urllib3 2.8.0,
with invented credentials and sockets denied. The initial 223-test subset is not
additional coverage. The separate `tests/test_monitoring_freshness_pilot.py` and
`tests/test_source_monitoring_pilot.py` synthetic suite passed 36 tests without
warnings, for 788 regressions total. Use the same wrapper separately on those two
files. Import smoke passed with 135 routes. Hosted CI and independent review
remain pending.

To reproduce, use the socket-denying wrapper in
[PR302's contract review](DATED_PRICE_CAPTURE_CONTRACT_20261016.md), with this exact
related-file list:

```text
tests/test_quote_eps_binding.py tests/test_fmp_quote_capture.py
tests/test_dated_price_capture.py tests/test_source_anchored_valuation.py
tests/test_valuation_scenario_checker.py tests/test_fmp_profile_price_boundary.py
tests/test_fmp_provider.py tests/test_valuation_numeric_inputs.py
tests/test_valuation_period_labels.py tests/test_source_answer.py
tests/test_evidence_references.py tests/test_threshold_evidence_admission.py
tests/test_valuation_consistency.py tests/test_provider_secret_diagnostics.py
```

The pinned interpreter's transient target was absent on the first test command,
which exited 127 and ran no tests. It was restored with `uv python install 3.11.9`;
the existing audited dependency environment was reused and versions checked.
That runtime download was separate from socket-denied tests, not a provider API
request or pilot probe. The missing-runtime command is not counted as validation.

No provider API/SEC/model request, live execution, approval creation, deployment,
production activation, application admission change, quota/deadline/transport/
fencing change, historical ledger edit or reserved-holdout output occurred. All
eleven live approvals remain consumed; frozen provider exclusions are unchanged.
PR301's previously documented combined-suite thread warning is not claimed fixed.
