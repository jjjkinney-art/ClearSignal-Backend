# FMP raw quote mapping — 17 October 2026 Auckland

Base: `413f3d6dc9291ec38e052b71c17e271cbb6a360c` (merged/deployed PR302).

## Provider review and scope decision

Official sources inspected without API calls or credentials:

- [Stable Stock Quote documentation](https://site.financialmodelingprep.com/developer/docs/stable/quote).
- [FMP's field guide, updated 24 March 2026](https://site.financialmodelingprep.com/education/index-articles/instant-stock-intelligence-a-comprehensive-guide-to-fmps-quote-api).
- [FMP FAQ](https://site.financialmodelingprep.com/faqs?code=data).

The field guide describes a one-record list with `symbol`, numeric `price`,
`exchange` and integer `timestamp`, among other fields. It defines the timestamp
as Unix time of quoted data. The FAQ describes exchange-local quote time zones;
we therefore support only the guide's numeric Unix representation, not guessed
local date strings. Neither a generic timestamp nor the listed exchange label
establishes a specific last-trade/official-close event or a security-master
binding. The displayed schema does not establish currency, issuer CIK, share
class or corporate-action basis. Those missing facts cannot be inferred from
NASDAQ text or a ticker. These are limits of this reviewed mapping, not a claim
that the provider has no additional datasets.

The resulting implementation is an offline raw-response mapper, not a live
retrieval adapter or an admitted quote. No endpoint has been called. Public
documentation inspection is separate from provider-data execution authority.

## Implementation

`validation.fmp_quote_capture.map_fmp_quote_capture` takes immutable saved bytes,
a separate receipt, exact expected symbol, analysis/evaluation instants and an
explicit freshness policy. The only supported endpoint identity is the stable
quote endpoint; the identity omits all query data and is paired with the exact
requested symbol. Credential-bearing request URLs, profile/legacy endpoints,
wrong symbols, non-200 statuses and non-JSON media receipts are rejected.

Receipt fields are exactly hash, byte length, endpoint, requested symbol,
retrieved-at, status and content type. All are supplied values; their agreement
does not prove a real request, successful authentication or source authenticity.
Media must be the canonical `application/json` label. Charset-bearing media
receipts are unsupported rather than silently rewritten. A future capture path
must document media normalization and preserve the original header separately.

The saved-body bound is 65,536 bytes. This is a parser computational bound and
does not modify transport response limits. A duplicate-key-detecting JSON parser
retains numeric token text without binary floating-point conversion. The used
price must be a positive decimal number token, at most 66 characters, without
exponent notation. Strings, booleans, nonfinite constants, malformed JSON,
unbounded numeric tokens and excessively nested inputs fail closed. The used
timestamp must be integer Unix seconds, at most ten digits, not milliseconds,
fractional seconds or a date string. No IPO/retrieval/previous-close fallback.

Exactly one record is required, with an exact case-sensitive symbol and a
bounded provider exchange label. Extra vendor fields may exist but never become
currency, CIK, session, share class or provenance merely because they look useful.
Neither free-text names nor arbitrary raw extras are copied into the result.
Changing a body without recomputing its receipt fails; fabricating both can pass
consistency. This limitation is tested.

Output retains price text, provider quote time in UTC and the original integer
timestamp. Its raw binding retains SHA-256/length and exact JSON pointers for
the four mapped fields. Price precision is unchanged; a calendar-day epoch
calculation independently checks the test timestamp. Original bytes remain
necessary for replay; a hash alone cannot reconstruct them. The function creates
no files and makes no retention decision.

Chronology is observation <= retrieval <= evaluation and observation <= analysis
<= evaluation. Evaluation cannot be future-dated. Age is relative to explicit
analysis time, never a claim of current freshness today. As in PR302, the supplied
policy ID/tolerance is not approval of a market-session or delayed-feed policy.

## Honest gaps and unchanged admission

`mapped=true` means only that mapping/consistency checks passed. Every result has
`admitted=false` and `launch_ready=false`. Success leaves currency, unit, issuer
CIK, MIC, security ID, share class, instrument type, split basis, session and
trade-or-close kind null. Provider quote time is never renamed last trade.
Documentation URLs describe a schema; they are not inspectable price evidence.
The explicit `observation_reference_inspectable=false` flag preserves this.

This candidate intentionally cannot pass PR302's trade/close capture audit or
PR300's hypothetical-price-only EPS scenario bridge as a source observation.
Both boundaries are tested and unchanged. No application module imports this
mapper. The existing legacy market snapshot provider is not repaired or newly
certified by this offline change.

Remaining integration requires a reviewed actual security/currency/share and
corporate-action mapping, documented observation/session semantics, inspectable
source-observation references, and matching EPS currency, share/split and
fiscal-vs-TTM/forward semantics. No output field named contract_passed, verified
claim, market multiple or scenario value is generated. Nothing here grants
provider credentials, pricing access or a new live-run approval. It does not
increase an adjudicated useful-answer count or clear the launch blocker.

## Offline verification

79 new cases cover exact raw mappings, decimal precision, independently checked
Unix time, receipt tampering, malformed and duplicate JSON, missing/ambiguous
records, symbol/exchange mismatches, unsupported values/timestamps, explicit
chronology/freshness boundaries, body bounds, source-hint non-authority,
sanitized diagnostics and unchanged downstream rejection.

665 related tests passed without warnings under pinned CPython 3.11.9, audited
dependencies and a socket-denying audit hook with invented credentials. The
initial 234-test subset is not additional coverage. Reproduce using the PR302
[offline wrapper](DATED_PRICE_CAPTURE_CONTRACT_20261016.md), prepending
`tests/test_fmp_quote_capture.py` to its exact related-file list. The separate
source-monitoring/freshness synthetic suite passed 36 tests without warnings,
for 701 regression tests total. Import smoke passed with 135 routes. Run the same
wrapper separately on `tests/test_monitoring_freshness_pilot.py` and
`tests/test_source_monitoring_pilot.py` to reproduce that synthetic suite. Hosted
CI and independent review remain pending.

No provider API/SEC/model request, live probe, approval creation, production
activation, application admission change, quota/deadline/transport/fencing
change, historical record edit or holdout output. All eleven approvals remain
consumed. Frozen FMP/NewsAPI/FRED exclusions remain unchanged. The documented
PR301 combined-suite thread warning is not claimed diagnosed or repaired.
