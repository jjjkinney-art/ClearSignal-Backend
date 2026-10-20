# Explicit conditional scenario application integration

Base: PR309 merge `3234c5f8ca827a0b10ef1de8d3c862dd544b788c`.

## Result and activation boundary

`POST /research/valuation-scenarios` is a separate application endpoint behind
`CONDITIONAL_VALUATION_SCENARIOS_ENABLED=false`. No environment, deployment
setting, `/ask` route, frozen pilot, ledger, quota, or historical artifact is
changed. Publishing or deploying this code does not activate this endpoint.
Activation and any live acceptance require separate review and authorization.
All eleven previous live approvals remain consumed.

The route accepts explicit assumptions and reconstructs historical EPS from
server-owned SEC sources. A returned scenario remains `partial`, `admitted=false`
and `launch_ready=false`. It is conditional price sensitivity, not a forecast,
expected return, recommendation, observed quote, or verified current P/E.

## Request and response

Content type must be `application/json`. The exact JSON root contains only
`ticker` and `assumptions`. Ticker must be an exact supported uppercase symbol
of one to five letters, optionally followed by a dot and one class letter.
Caller CIKs, source claims, references, approvals, extra root keys, duplicate
JSON keys, nonfinite numbers and floating JSON numeric tokens are refused.
Decimal operands use the existing explicit string-value/unit/provenance contract.

Supported modes and complete assumption schemas are those in the canonical
application calculators:

- `evaluate_growth_scenario`: positive annual EPS and explicit assumed growth.
- `solve_required_earnings_growth`: positive annual EPS and explicit desired
  annualized price change; the answer solves a conditional requirement.
- `evaluate_earnings_recovery_scenario`: nonpositive annual EPS as context only,
  explicit hypothetical positive future fiscal EPS and exit multiple.

Every mode requires a hypothetical underlying-common-share price, explicit
same-issuer USD/GAAP/diluted/full-year/total-operations basis, horizon and excluded
distributions. The recovery mode additionally requires its dated future full
fiscal year. The endpoint requires today's UTC `scenario_as_of`: the current
SEC directory cannot establish a historical ticker mapping. Pure offline
calculators retain historical scenarios. Future-date checks now consistently use
UTC instead of the host's local day; numeric formulas and rounding are unchanged.

Responses separate historical `source_claims`/`evidence_references` from the
`scenario` and its supplied assumptions. References support reported historical
EPS, not future prices, EPS or multiples. Successful HTTP responses include
`Cache-Control: no-store`. No assumptions, answer, thread, alert or snapshot are
persisted by this route. This is not saved/reopened personalized research.

## Source selection and fail-closed gaps

The conflict-aware current SEC directory resolves an exact issuer. One existing
Company Facts adapter invocation requests diluted EPS (`USD/shares`) and Assets
in supported reporting currencies. Records must match CIK, annual 10-K/10-K/A
form, and filing/period dates no later than the scenario date. The existing
producer builds a comparable annual diluted-EPS pair and admission reconstructs
its source consistency. EPS must end at the latest available annual Assets
period; an exact accession, filed date and end-date Assets anchor must establish
USD and no competing supported reporting currency.

Absent, conflicting, stale or incompatible evidence returns an explicit gap.
Basic EPS, quarterly EPS, 20-F or EUR observations are not promoted. Retained
NPK basic-only evidence and ASML EUR/20-F evidence therefore do not establish
support for this first endpoint. ACHC's current annual loss can support only
the explicit recovery mode, not positive-EPS growth or current P/E.

The pure calculators now live in `app/services`; `validation` exports their
original functions as compatibility imports. Application code never depends on
validation execution modules. Source comparisons and references are rebuilt,
not accepted from the request. This is source-consistency validation, not
independent factual adjudication or quote/share-class/split compatibility.

## Controls and limits

The handler requires existing account admission before reading the request or
calling providers, with the application's existing configured auth bypass policy
unchanged. The production middleware protects new routes by default. The endpoint
is classified as expensive and shares the existing per-IP and per-user expensive
route budgets, global user budget and edge controls. `/ask`-specific entitlement
and daily model-request quotas are not repurposed; this route makes no model calls.
Feature-off requests return handler 404; global authentication can reject earlier.
Global `ENABLE_DATA_RETRIEVAL=false` returns 503 before providers.

Declared and observed request bytes are capped at 16,384, including streaming
without or with misleading Content-Length. Duplicate or malformed lengths fail.
Source calls run in a worker thread through existing adapters and their timeouts.
This is not a bounded pilot executor: it adds no new hard whole-request deadline,
physical network request quota, ledger or cancellation fencing. The directory
may reuse its existing cache. One Company Facts invocation does not prove one
physical request (existing adapter redirect behavior is unchanged).

No live SEC, FMP, NewsAPI, FRED or model calls were used for this implementation.
No source-price entitlement, proxy/CA change or new execution authority is granted.

## Offline verification and remaining acceptance

ASGI tests inject invented SEC records and account state. They cover gates,
strict bodies, source identity/currency/annual selection, source reconstruction,
positive and loss-context modes, UTC boundaries, no-store and isolated assumptions.
Middleware tests prove expensive IP/user limits, including normalized trailing
slashes. This is not real JWT/account acceptance.

The retained ACHC replay in
`ACHC_CONDITIONAL_API_REPLAY_20261020.json` passes actual saved Company Facts bytes
through the ASGI route, injecting the directory, account state, clock and provider
boundary. It reconstructs 2025 diluted EPS -12.16 and reproduces terminal price
100, factor 1.5625 and annualized change 0.25 from invented price 64, future EPS 4,
exit P/E 25 and two years. The body and receipt hashes remain unchanged. No claim
is made that these assumptions are user choices, forecasts, original pilot
admissions or a successful live account request. Historical ledgers were not
revalidated in this checkout.

Tests use CPython 3.11.9 and existing pinned dependencies with an empty environment
apart from test placeholders. IP sockets, DNS and connect calls are denied by an
audit hook; local AF_UNIX constructors are allowed for ASGI event loops. The 36
existing synthetic pilot tests also passed with every socket audit event denied.
Hosted CI, independent answer/usefulness review, approved activation/live
acceptance, signed-in save/reopen/isolation, international/basic-EPS coverage and
the existing development/holdout benchmark remain separate gates.

Final local results: **1,235 related/application/security tests passed**, plus
**36 existing synthetic pilot tests passed** (1,271 distinct tests). Import smoke
registered **136 routes**. Single-process collection found **18,069 tests with
zero collection errors**. One existing Starlette/AnyIO deprecation warning appears
in the security run and collection; it is not a test failure. The new request
suite has 41 cases; rate-limit parameterization adds three cases to the existing
middleware suite. The full per-file repository regression has not been run
locally; hosted CI remains required.

Reproduction commands (run with the above network-denying environment):

```sh
python -m pytest -q tests/test_conditional_valuation_api.py tests/test_earnings_recovery_scenario.py tests/test_filed_eps_crosscheck.py tests/test_filing_eps_basis.py tests/test_split_event_reconciliation.py tests/test_filing_share_class.py tests/test_quote_eps_binding.py tests/test_fmp_quote_capture.py tests/test_dated_price_capture.py tests/test_source_anchored_valuation.py tests/test_valuation_scenario_checker.py tests/test_fmp_profile_price_boundary.py tests/test_fmp_provider.py tests/test_valuation_numeric_inputs.py tests/test_valuation_period_labels.py tests/test_source_answer.py tests/test_evidence_references.py tests/test_threshold_evidence_admission.py tests/test_valuation_consistency.py tests/test_provider_secret_diagnostics.py tests/test_public_document_ingestion.py tests/test_sec_inline_memory.py tests/test_launch_security.py tests/test_launch_access_policy.py tests/test_rate_limit_middleware.py tests/test_dependency_pinning.py
python -m pytest -q tests/test_monitoring_freshness_pilot.py tests/test_source_monitoring_pilot.py
python -m pytest tests/ --collect-only -q -o addopts=""
python -c "from app.main import app; print(len(app.routes))"
```
