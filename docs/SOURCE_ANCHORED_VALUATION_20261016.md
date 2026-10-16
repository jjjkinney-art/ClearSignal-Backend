# Offline fiscal-EPS scenario bridge — 16 October 2026 Auckland

Base: `5ac321d4f87aa1d97bcc7005543bd523f20da013` (merged/deployed PR299).

## Purpose and scope

The existing offline valuation checker evaluates supplied P/E and growth/return
assumptions. Its provenance fields are caller assertions. It does not rebuild a
reported EPS observation or explain an entry multiple's price/EPS operands.

`validation.source_anchored_valuation.evaluate_source_anchored_scenario` adds that
offline bridge. It accepts already admitted application evidence and references,
an exact issuer/CIK supplied by the trusted caller, explicit assumptions, and an
evaluation date. It reconstructs one unambiguous annual diluted-EPS comparison
with the existing SEC comparison producer and preserves the source filing,
current fiscal period, raw EPS and admitted response reference. Reconstruction
checks producer consistency; it is **not independent factual adjudication** or
cryptographic proof that arbitrary caller-created data came from SEC.

It calculates `assumed_price / reported_fiscal_diluted_eps` and passes that
conditional entry ratio into the existing scenario calculator. A historical
fiscal-year basis is explicit and remains distinct from current trailing-twelve-
month or forward earnings. The calculator now accepts `period_basis: fiscal_year`
alongside its existing two basis labels; entry/exit bases still must match.
No quarter is annualized, no TTM sum is invented and no future EPS is retrieved.

This increment has **no production route or UI integration** and no market-data
adapter. The production source-answer guard continues withholding unsupported
investment thresholds. There is no claim that the six live pilot answers now
contain valuations or that another launch gate has passed.

## Source and assumption boundary

Supported source anchor: an available, non-stale/non-conflicting SEC structured
XBRL pair for `us-gaap:EarningsPerShareDiluted`, `USD/shares`, consolidated scope,
with a supported annual form and positive current EPS. The old and current facts,
summary, URL, dates, identity and units are rebuilt; the response reference must
match and have a unique canonical E ID, fact type, extraction method, filing form
and reporting period. Missing/ambiguous/unavailable references cannot authorize
the ratio. Multiple different annual pairs fail closed. An invalid or quarterly
EPS candidate does not trigger a silent fallback to another annual candidate.

The existing `_rebuild` helper gains an opt-in `expected_unit: USD/shares` only
for exactly the diluted-EPS name and concept. Ordinary financial-foundation
callers retain the old monetary-unit contract; EPS cannot become an ordinary
revenue/income observation. Units are checked before the inline-fact branch.
Inline EPS is not supported by this bridge. Source availability/freshness checks
are preserved, not a claim that a fiscal observation equals current earnings.

All of the following remain explicit user assumptions, not source observations:

- A positive hypothetical USD price **per underlying common share**. The caller
  must explicitly affirm that unit; no ADR/security/share conversion is performed.
- Exact issuer, USD, GAAP, diluted-share and fiscal-year basis, with an explicit
  split basis and total/continuing-operations scope. Split/security compatibility
  and earnings scope remain user assertions, not independently verified facts.
- Exit P/E, whole-year horizon, and either annual EPS growth or required annual
  **price-only** return. Dividends/distributions must be explicitly excluded.

The bridge refuses a `source_observation` price/exit/rate/horizon rather than
allowing an unsupported price observation to inherit a valid EPS citation.
Unexpected operands or an exit operand's attempted basis override also fail.
The hypothetical price has a scenario date, not a market observation timestamp.
Both cited filings must have been published by that date; the scenario date must
not follow the explicit evaluation date, and neither may be in the future.
These are calendar-date checks, not an intraday availability guarantee.

No missing input is defaulted. The result keeps supplied assumptions separately
from the reported source anchor and the entry-ratio derivation. The derived entry
P/E is a hypothetical scenario input, not a reported market multiple. It retains
the calculator's 50-digit ROUND_HALF_EVEN arithmetic and computational limits.
The division itself uses an explicit context, so ambient Decimal settings cannot
change the result. Rounded division does not establish an exact rational ratio.
If rounding would erase a nonzero entry/exit multiple difference to identity,
an exact Fraction comparison detects that case and refuses the calculation.
This guard is not a guarantee to detect every possible rounding difference.

`available: true` means the conditional calculation can be supplied. It also
returns `status: partial`, `launch_ready: false`, `market_pe_verified: false`,
and unresolved market/security verification, supported future earnings/exit
valuation, expected total returns and attractiveness. `available: false` means
no calculation is supplied. Neither state is a recommendation or quality score.

## Independently checked invented examples

The test issuer ZQXB and its source documents are entirely invented fixtures.
For a reported annual EPS of 5 and assumed price 100, entry P/E is 20. With exit
P/E 45, unchanged EPS and a two-year horizon, the exact identity
`45/20 = (3/2)^2` establishes a conditional annual price change of 50%.
For assumed price 225 (entry 45x), exit 20x and an assumed 10% annual price-only
return over two years, `20/45 × (33/20)^2 = (11/10)^2` requires 65% annual EPS
growth. Fraction identities check these cases independently of the implementation.
They are arithmetic illustrations, not market forecasts or selected assumptions
for any real issuer. No saved pilot or reserved-holdout outputs are used.

## Validation

1,030 tests passed offline with CPython 3.11.9, audited dependencies, invented
credentials and socket operations denied: 994 related regressions (including 57
new bridge cases) and 36 existing isolated source-monitoring/freshness pilot
tests. Import smoke passed with 135 routes. No failed initial/final test run in
this increment. Full hosted CI and independent review remain pending.

New checks include exact independent algebra in both modes, current/prior dates
and admitted ID mapping, incompatible currency/period/accounting/share bases,
quarterly/nonpositive/conflicting EPS, wrong CIK/issuer, altered amounts/summary,
stale/unavailable evidence, ambiguous/metadata-only/malformed references, missing
or malformed assumptions, fake source-price provenance, caller basis overrides,
ambient precision, defensive copies, pre-inline unit rejection and unchanged
production threshold withholding. Related suites cover SEC facts/currency/labels,
financial foundation/reporting, source/threshold admission, decision routing,
valuation inputs/periods/consistency, margin, business context and both risk
composition increments.

Reproduction uses the socket-denying wrapper in
[the existing regression instructions](RISK_FINANCIAL_MONITORING_LINKS_20261016.md).
The exact related-file list for this increment is:

```text
tests/test_source_anchored_valuation.py tests/test_valuation_scenario_checker.py
tests/test_financial_thesis_foundation.py tests/test_source_answer.py
tests/test_threshold_evidence_admission.py tests/test_decision_monitoring_evidence.py
tests/test_decision_monitoring_routing.py tests/test_sec_fact_binding.py
tests/test_sec_fact_records.py tests/test_verified_sec_metrics.py
tests/test_verified_sec_revenue.py tests/test_sec_metric_labels.py
tests/test_native_currency_sec_facts.py tests/test_financial_reporting_coverage.py
tests/test_operating_margin_assessment.py tests/test_valuation_numeric_inputs.py
tests/test_valuation_period_labels.py tests/test_signed_valuation_thresholds.py
tests/test_question_anchored_valuation.py tests/test_valuation_consistency.py
tests/test_business_context_coverage.py tests/test_risk_financial_monitoring.py
tests/test_operating_risk_mechanisms.py tests/test_thesis_disclosures.py
```

For the additional synthetic suite use only
`tests/test_monitoring_freshness_pilot.py` and
`tests/test_source_monitoring_pilot.py` in the same wrapper.

## Next gates and authority

Real market observations need a separate dated price/security/share-basis source
contract. Broader currencies, EPS bases and TTM/forward coverage are not completed
here. UI/API wiring needs an explicit user-assumption path and cannot silently
use model-chosen assumptions as the user's own. Independent source verification,
question usefulness and the existing 100-company development/holdout and signed-in
acceptance gates remain open. This bridge alone does not solve attractiveness.

No live request, model call, new pilot package, production flag, retrieval
selection, physical quota, deadline, transport/hash rule or ledger is changed.
All eleven live approvals remain consumed. Historical run files were not used or
modified. Nothing authorizes another live pilot or spending.
