# Listed split reconciliation — 18 October 2026 Auckland

Base: `bd67a2502921db2ac8001e18b2f37f933a04bc3d` (merged/deployed PR305).

## Implemented scope

`validation.split_event_reconciliation.reconcile_listed_splits` maps a saved
FMP stable split response and computes exact rational factors for listed events
under explicit hypothetical calendar-basis assumptions. It does not adjust any
reported EPS value or quote price, and cannot clear the existing share-basis gate.
There are no production imports, requests, settings or evidence-admission changes.

The key distinction is between the financial period and the share basis in which
its EPS is already expressed. A period-end or filing date is not automatically a
split-adjustment cutoff. The caller must explicitly supply `already_adjusted_through`
and `comparison_date` with `user_assumption` provenance; there is no default or
source-observation provenance shortcut. Test assumptions are invented scenarios,
not statements that the actual user selected these dates.

## Official source review

Public documentation inspected without provider API calls:

- [Stock Split Details API](https://site.financialmodelingprep.com/developer/docs/stable/splits-company).
- [Stable documentation with displayed split fields](https://site.financialmodelingprep.com/de/developer/docs).
- [Changelog](https://site.financialmodelingprep.com/developer/docs/changelog).

The documented split ratio is new shares divided by old shares. The displayed
schema uses symbol, date, numerator, denominator and splitType. The API has a
requested result limit; a returned list does not itself establish a complete
relevant corporate-action interval. This implementation supports only the explicit
stock-split type and retains unknown completeness even below the requested limit.
It does not infer equivalent semantics for dividends, spin-offs or other types.

## Input and source binding

Saved UTF-8 JSON bytes must fit the existing normalized-capture bound of 65,536
bytes. The separate receipt must contain exactly SHA-256, byte length, stable
split endpoint identity, exact requested symbol, requested limit, retrieval time,
integer HTTP 200 and canonical application/json. Endpoint identity contains no
query/key and must match the split-company route, not the calendar or legacy
route. Body hash and byte length must match; supplied receipt/source authenticity
remains unverified. A recomputed fabricated receipt can pass consistency, which
is tested rather than represented as authenticated data.

The requested limit is an integer 1–1000, and the response cannot exceed it.
`requested_limit_reached` is explicit. Saturation is a warning signal, never
proof that all events were returned; non-saturation is also not completeness.
Caller receipt extras such as `complete_coverage=true` are rejected.

Each row must match the exact symbol, have a canonical ISO date, splitType
stock-split and positive whole-number JSON numerator/denominator tokens. Strings,
booleans, fractions, exponents, zero/negative amounts, nonfinite constants,
duplicate JSON keys, malformed input and unsupported event types fail closed.
Each component is at most 1,000,000, a computational bound rather than an equity
policy. Duplicate or conflicting events on one date are rejected rather than
silently deduplicated or multiplied. Unknown optional row fields are not copied
or trusted as class, completeness or effective-time proof.

Events are sorted by date while preserving exact original JSON field pointers
and ratio integers. The raw receipt remains bound to the complete saved response.
No live capture, output file, historical record or new retention decision is
created by the function.

## Conditional algebra and no-double-adjustment rule

For each supplied event after the already-adjusted date and strictly before the
comparison date:

`listed share factor = product(new shares / old shares)`.

The conditional EPS scaling factor is its exact rational inverse. No binary float,
rounded decimal or ambient Decimal precision is involved. Products include at
most 128 events; with bounded components, returned integer strings remain bounded.
No current/prior financial observations or source EPS values are rewritten.

For example, the synthetic fixture contains a 10-for-1 event already included in
the assumed basis, then a 4-for-1 and a 1-for-2 event. Only the latter two are
applied, yielding a listed share factor of 2 and inverse EPS factor of 1/2. Reusing
the already-included event would produce the wrong factor of 20. Tests explicitly
check the cutoff and preserve the difference between that assumption and a fact.

A comparison-day event blocks a factor when it lies after the assumed basis:
the saved schema provides a date, not intraday effectiveness/session proof.
No local-market-calendar or quote-date equivalence is inferred from UTC retrieval
time. Calendar boundaries remain user assumptions, not verified exchange dates.

An empty list, a pre-basis-only list or a future-only list returns a mapped but
insufficient-evidence status **without** an identity factor or EPS multiplier.
Even when listed events happen to multiply to 1, this does not prove no omitted
corporate action. The completeness, split compatibility, EPS basis, security
mapping, independent-adjudication and inspectability flags remain false.

## Time and remaining integration

Basis dates must be ordered and no later than evaluation. Retrieval must precede
evaluation and satisfy an explicit supplied retrieval-age policy, with the same
0–604800-second computational range used in preceding offline contracts. No real
market freshness tolerance is approved here. Retrieval age is not source update
time, and a retrospective list does not prove it was available at the comparison
date. Evaluation cannot be future-dated.

All outputs remain unadmitted and not launch ready. A passing factor is labeled
listed-events-only and conditional on the assumed basis. No EPS amount, price,
P/E, forecast or threshold is calculated. A passing split report cannot be injected
into PR305's raw-input contract to make it clear split compatibility. Actual
complete corporate-action coverage, source-supported EPS split basis, share-class
identity, quote unit and session/observation admission remain unresolved.

## Offline verification

73 new tests cover ratio direction, reverse/fractional ratios expressed by whole
components, exact composition, the already-adjusted cutoff, absent-event
non-authority, ambiguous same-day events, duplicate/conflicting dates, truncation
signals, raw binding/JSON/resource bounds, provenance, chronological boundaries,
sanitized diagnostics, fabrication limitations and unchanged share-gate rejection.
The initial focused run passed 197 tests; it is a subset, not additional coverage.
Final related suite: **951 passed**, no warnings. Separate synthetic pilot
suite: **36 passed**, no warnings. Total **987** regression tests. No failed
assertion runs or live source captures were used for this increment.

Use the socket-denying pinned CPython 3.11.9 wrapper from
[PR302](DATED_PRICE_CAPTURE_CONTRACT_20261016.md), with PR305's exact related-file
list and `tests/test_split_event_reconciliation.py` prepended. Run the separate
`tests/test_monitoring_freshness_pilot.py` and `tests/test_source_monitoring_pilot.py`
synthetic suite using that same wrapper. Import smoke passed with 135 routes.
Hosted CI and independent review remain pending.

No provider API/SEC/model request, live probe, approval creation, production
activation, evidence-admission change, transport/deadline/quota/fencing change,
historical-run edit or holdout output. All eleven live approvals remain consumed;
frozen FMP/NewsAPI/FRED exclusions remain unchanged. The prior PR301 thread warning
is not claimed diagnosed or fixed. This is reconciliation machinery, not a new
adjudicated answer-quality result or launch-completion percentage.
