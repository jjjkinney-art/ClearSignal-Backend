# Explicit euro annual-EPS scenarios and 20-F source support

Base: PR312 merge `bdd9ed812454b1d72a7c50cd9c592d56252b509e`.

## Scope and result

The default-off conditional scenario endpoint previously selected only annual
10-K/10-K/A EPS in USD. Add the exact `EUR/shares` unit and annual 20-F/20-F/A
selection for explicitly requested US-GAAP basic or diluted EPS. EUR requests
require hypothetical prices in `EUR/share` and, for recovery, future EPS in
`EUR/shares`. No currency, share basis or accounting taxonomy is inferred.

This repairs a general currency/form contract limitation. It does not establish
that ASML currently supplies a qualifying EPS pair or adequate currency anchor.
No retained actual ASML Company Facts EPS body was available for replay in this
checkout. All new EUR/20-F examples use invented observations, issuer and dates;
they are not observed ASML results. IFRS-tagged EPS remains unsupported.

The endpoint remains default-off. No runtime setting, ordinary `/ask` route,
model path, source permission, live request, pilot scope or ledger is changed.
All eleven prior live approvals remain consumed.

## Currency, source identity and mathematical contract

- `PER_SHARE_UNITS` contains exactly `USD/shares` and `EUR/shares`, derived from
  the existing USD/EUR reporting-currency policy. Binder and producer preserve
  exact units and display literal EUR-per-share values without dollar labels.
- Each comparison must use the requested basic/diluted concept and exact unit,
  known CIK, US-GAAP namespace and comparable annual periods. The parser never
  promotes `ifrs-full` or another namespace into `us-gaap`.
- The server accepts 10-K, 10-K/A, 20-F and 20-F/A for this annual path. 6-K,
  10-Q, partial-year annualization and unsupported currency units remain gaps.
- Currency must match an Assets anchor with the same accession, filing date,
  period end and filing form. Missing/competing reporting currencies or
  contradictory form metadata fail closed. Additional USD convenience-translation
  EPS cannot override a EUR Assets anchor, or vice versa.
- The historical EPS value, hypothetical entry price and future EPS all retain
  the requested currency. There is no FX conversion or quote retrieval. The
  price is explicitly per unconverted underlying common share; no ADR ratio,
  instrument identity or class-specific earnings-rights compatibility is proved.
- EUR supports annual GAAP total-operations EPS. Adjusted, continuing-operations,
  TTM, forward, basic/diluted substitutions and unsupported currency requests
  are not new supported source families.

The original USD-only basic/diluted scenario entry points remain USD-only and
delegate to shared currency-parameterized implementations. Existing quote binding
uses the default USD/diluted source helper and cannot consume EUR evidence. The
filing-cover/EPS value inspectors and quote/share/split admission gates are not
widened. This is structured Company Facts support, not new HTML document parsing
or a relaxation of reviewed annual-document byte/hash validation.

The equations, precision and rounding are unchanged: dimensionless multiples and
growth rates require same-currency operands; recovery terminal price retains
`EUR/share`. Nonpositive historical EPS remains context, never a P/E or growth
denominator. Observed market price, verified market P/E and FX/ADR conversion
flags remain false. Results remain partial, not admitted and not launch-ready.

Both EPS concepts and both supported units are selected from the same existing
Company Facts adapter invocation. There is no extra document fetch or new
provider invocation. This is not a hard physical-request quota guarantee; the
ordinary requests adapter and its redirect/timeout behavior remain unchanged.

## Offline evidence and compatibility

Tests cover both share bases, all three scenario modes, 20-F/20-F/A and 10-K,
exact EUR display/source/reference reconstruction, amendments, sign guards,
currency mismatches, translated-observation shortcuts, conflicting metadata,
unsupported taxonomy/forms/units and unchanged USD/quote-binding refusal.
Malformed/missing/unsupported currency is rejected before source work.

The retained ACHC Company Facts replay verifies that the existing USD recovery
path still reconstructs annual diluted EPS -12.16 versus 2.78 and reproduces
terminal price 100 and annualized price change 0.25 from invented price 64,
future EPS 4, exit multiple 25 and two years. The 3,457,609-byte source body and
receipt hashes remain unchanged. `EUR_ANNUAL_EPS_VERIFICATION_20261020.json`
records the replay summary and test evidence. The directory, clock, account
state and provider boundary are supplied locally; this is not a signed-in live
request or actual user hypothesis. Prior replay files are not rewritten.

## Request-test worker teardown

An earlier focused run reported AnyIO worker threads still alive at test
teardown. The request test helper closed its asyncio loop after root-task
completion without joining the worker threads the request created. AnyIO's root
completion signals worker stop; it does not itself guarantee observed thread
exit before synchronous test teardown.

The shared request-test helper now joins only its newly created AnyIO workers
with a five-second bound and fails if any remain alive. The global thread-leak
guard is unchanged. A controlled reproduction holds a worker at thread exit
until released and verifies that the helper waits. Removing the cleanup makes
that regression fail; the original source was restored before final checks.
This establishes the test-harness cleanup requirement. It does not identify the
cause of any historical live-pilot halt or change production cancellation,
transport, stage supervision, quotas or deadlines. The five-second bound belongs
only to this test helper, not application or pilot execution.

## Remaining gates

Pinned-runtime offline checks deny IP sockets, DNS and connect operations;
AF_UNIX constructors are allowed for ASGI event loops. The synthetic pilot suite
denies all socket events. Required hosted CI and exact-diff review remain
necessary. There has been no production activation or live acceptance.

Actual foreign EPS availability, IFRS/other-currency capability, price/security
and corporate-action proof, independent factual/usefulness review, separately
approved development expansion using the existing cohort, reserved holdouts and
signed-in saved/reopened personalization remain open. This increment does not
establish universal coverage, resolve the broader launch blocker, revise its
completion percentage or promise a launch date.

Final local results: **1,555 related tests passed** with RuntimeWarning promoted
into errors, plus **36 existing synthetic pilot tests passed** (1,591 distinct
cases, including 69 new EUR/cleanup cases). Import smoke: **136 routes**;
single-process collection: **18,216 tests, zero errors**. The existing
Starlette/AnyIO BlockingPortal deprecation warning remains. The final related
run has no thread-teardown RuntimeWarning. Original pre-cleanup warning output,
cleanup-removal failure and final logs remain in the verification record. This
is not a claim that historical live worker or stage-timeout issues are fixed.
Hosted full per-file regression and review remain pending.

Reproduction commands (use the network-denying environment described above):

```sh
python -m pytest -q -W error::RuntimeWarning tests/test_eur_annual_eps_scenarios.py tests/test_basic_eps_scenarios.py tests/test_conditional_valuation_api.py tests/test_conditional_valuation_account_boundary.py tests/test_earnings_recovery_scenario.py tests/test_filed_eps_crosscheck.py tests/test_filing_eps_basis.py tests/test_split_event_reconciliation.py tests/test_filing_share_class.py tests/test_quote_eps_binding.py tests/test_fmp_quote_capture.py tests/test_dated_price_capture.py tests/test_source_anchored_valuation.py tests/test_valuation_scenario_checker.py tests/test_fmp_profile_price_boundary.py tests/test_fmp_provider.py tests/test_valuation_numeric_inputs.py tests/test_valuation_period_labels.py tests/test_source_answer.py tests/test_evidence_references.py tests/test_threshold_evidence_admission.py tests/test_valuation_consistency.py tests/test_provider_secret_diagnostics.py tests/test_public_document_ingestion.py tests/test_sec_inline_memory.py tests/test_launch_security.py tests/test_launch_access_policy.py tests/test_rate_limit_middleware.py tests/test_dependency_pinning.py tests/test_financial_thesis_foundation.py tests/test_financial_reporting_coverage.py tests/test_filing_metric_evidence.py tests/test_verified_sec_metrics.py tests/test_verified_sec_revenue.py tests/test_sec_metric_labels.py tests/test_sec_fact_binding.py
python -m pytest -q tests/test_monitoring_freshness_pilot.py tests/test_source_monitoring_pilot.py
python -m pytest tests/ --collect-only -q -o addopts=""
python -c "from app.main import app; print(len(app.routes))"
```
