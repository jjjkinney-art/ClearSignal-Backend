# Explicit basic-EPS conditional scenarios

Base: PR311 merge `5727952069e5d7f5ade2f2aba26d5ae933ecdbad`.

## Problem and resulting behavior

The default-off conditional scenario endpoint previously supported only annual
USD GAAP diluted EPS. A company with a usable basic-EPS comparison but no
qualifying diluted comparison therefore could not support even an explicitly
basic-EPS hypothesis. Retained NPK filing inspection motivated this general
coverage increment; it is not a ticker-specific exception or proof of NPK's
current Company Facts availability.

The endpoint now honors the explicit `assumptions.eps_basis.share_basis` choice:
`basic` selects only `us-gaap:EarningsPerShareBasic`; `diluted` selects only
`us-gaap:EarningsPerShareDiluted`. Both retain `USD/shares`, annual 10-K/10-K/A,
exact issuer, comparable-period reconstruction and the same-filing USD Assets
currency anchor. There is no automatic fallback or basis inference. If the
requested concept is missing, the response is an explicit gap even when the
other concept is available. Missing, malformed or unsupported share-basis
requests are rejected before directory/provider work.

This supports the existing explicit growth-sensitivity, required-growth and
nonpositive-EPS recovery modes on basic EPS. Positive-P/E calculations still
require positive historical EPS. Loss or zero EPS remains context only in the
recovery mode; future EPS, price, exit multiple and horizon remain explicit user
assumptions. For basic EPS, the supported source contract is annual USD GAAP total
operations, not adjusted/continuing/TTM/forward EPS. No forecast of dilution,
participating-security allocation or class-specific earnings rights is made.

## Implementation and compatibility

The original `evaluate_source_anchored_scenario` and
`evaluate_earnings_recovery` entry points remain diluted-only. Separate
`evaluate_basic_source_anchored_scenario` and `evaluate_basic_earnings_recovery`
entry points select the basic basis and reuse the same arithmetic. A basic
assumption cannot consume diluted source facts, or vice versa. The default
source helper and existing quote/profile/EPS binding remain diluted-only; basic
evidence does not acquire quote, split or security compatibility authorization.

The shared source reconstructor accepts only the two exact named concept/unit
pairs: diluted EPS/EarningsPerShareDiluted and basic EPS/EarningsPerShareBasic,
both explicitly per-share. Mixed concept families, wrong names, units, altered
claims or stale/conflicting references fail. Ordinary monetary financial-thesis
reconstruction retains its existing units and metric families.

Company Facts requests now parse both EPS concepts from the same JSON response.
This adds a requested concept/unit pair to the existing adapter invocation, not
a second provider invocation or document lookup. It creates no physical-request
quota guarantee; existing requests adapter behavior is unchanged. Returned
source EPS includes `share_basis`, reference and exact concept. Source-selection
text, calculation formula and limitations identify the requested basis.

Numeric formulas, precision and rounding are unchanged. The basic path does not
convert or relabel a basic value as diluted, infer that equal values are
interchangeable, or normalize a reported loss. A basic-scenario multiple is not
an observed market multiple or comparable to a diluted multiple without further
analysis. Share, split and earnings-rights compatibility remain explicit,
unverified assumptions.

## Retained-source replay

`ACHC_BASIC_EPS_API_REPLAY_20261020.json` records an offline ASGI replay using the
actual retained Company Facts body captured October 15. Body SHA-256:
`b1d48d703acb9cf3f60aaa852af3b91f4c463c554bf1a3d1bbf0ae55d0e977a3`,
3,457,609 bytes; receipt SHA-256:
`78a7c0def1eab8dd18eb1cfe065ff4e21b5c24b4f96f15825a22993edd603f28`.
Body and receipt hashes match before and after the replay.

The explicit basic request reconstructs 2025 EPS **-12.16** and 2024 EPS **2.79**.
The earlier diluted replay used **2.78** for 2024, demonstrating why the basis
must remain distinct even when current values happen to agree. Invented entry
price 64, future basic EPS 4, exit multiple 25 and a two-year horizon reproduce
terminal price 100, factor 1.5625 and annualized price change 0.25. Historical EPS
does not enter recovery arithmetic.

The directory, account request state, clock and provider boundary are injected
offline. There is no external dispatch, real identity session, current market
observation or live pilot. These are invented demonstration assumptions, not
actual user choices, forecasts or original pilot admissions. This replay proves
neither a current NPK Company Facts pair nor ASML EUR/20-F support. Historical
run files and ledgers were not revalidated in this checkout.

## Verification and controls

New tests exercise all three modes, exact source labels and reference binding,
separate current values when both bases exist, missing-basis/no-fallback gaps,
claim tampering/mixed concepts, quote-binding refusal, positive/loss sign guards,
source units/currency/period/conflicts and request-time schema checks. Existing
calculator, monetary foundation, producer, filing, account, routing/security and
frozen synthetic pilot suites are checked separately from live acceptance.

All local verification uses CPython 3.11.9 and pinned dependencies. IP sockets,
DNS and connect events are denied; local AF_UNIX constructors are allowed for
ASGI event loops. The existing synthetic pilot suite denies every socket event.
No production setting, auth/admission policy, timeout, quota, proxy/CA rule,
model path, persistence behavior or frozen pilot manifest is changed. The endpoint
remains default-off, and all eleven prior live approvals remain consumed.

Required hosted CI and exact-diff review precede merge. Separately approved
activation/live validation, adequate source coverage, independent factual and
usefulness adjudication, development/holdout benchmark and signed-in saved
personalization remain launch gates. This increment enables an explicit basis
choice; it does not establish complete answers for all smaller companies or
resolve the broader launch blocker.

Final local results: **1,471 related tests passed**, plus **36 existing synthetic
pilot tests passed** (1,507 distinct cases, including 49 new basic-EPS cases).
Import smoke registered **136 routes**; single-process collection found **18,147
cases with zero errors**. `BASIC_EPS_VERIFICATION_20261020.json` preserves counts
and original focused/related/pilot and differential warning-check output.

One final combined run reported `AnyIO worker thread` still alive at teardown in
an unchanged existing request test. The affected module passed 41/41 without
warnings when run separately on clean base `57279520` and this branch. This does
not identify the cause or prove the warning fixed or branch-caused. It remains a
review limitation. An existing Starlette/AnyIO deprecation warning also remains.
Full hosted per-file repository regression is pending.

Reproduction commands (run with the network-denying environment described above):

```sh
python -m pytest -q tests/test_basic_eps_scenarios.py tests/test_conditional_valuation_api.py tests/test_conditional_valuation_account_boundary.py tests/test_earnings_recovery_scenario.py tests/test_filed_eps_crosscheck.py tests/test_filing_eps_basis.py tests/test_split_event_reconciliation.py tests/test_filing_share_class.py tests/test_quote_eps_binding.py tests/test_fmp_quote_capture.py tests/test_dated_price_capture.py tests/test_source_anchored_valuation.py tests/test_valuation_scenario_checker.py tests/test_fmp_profile_price_boundary.py tests/test_fmp_provider.py tests/test_valuation_numeric_inputs.py tests/test_valuation_period_labels.py tests/test_source_answer.py tests/test_evidence_references.py tests/test_threshold_evidence_admission.py tests/test_valuation_consistency.py tests/test_provider_secret_diagnostics.py tests/test_public_document_ingestion.py tests/test_sec_inline_memory.py tests/test_launch_security.py tests/test_launch_access_policy.py tests/test_rate_limit_middleware.py tests/test_dependency_pinning.py tests/test_financial_thesis_foundation.py tests/test_financial_reporting_coverage.py tests/test_filing_metric_evidence.py tests/test_verified_sec_metrics.py tests/test_verified_sec_revenue.py tests/test_sec_metric_labels.py
python -m pytest -q tests/test_monitoring_freshness_pilot.py tests/test_source_monitoring_pilot.py
python -m pytest tests/ --collect-only -q -o addopts=""
python -c "from app.main import app; print(len(app.routes))"
```
