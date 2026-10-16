# Dated price capture contract — 16 October 2026 Auckland

Base: `b1f29f7de39be5813c8c15c42e09bb59cb6ec5ae` (merged/deployed PR301).

## Scope and outcome

PR301 stopped promoting undated profiles into current-price evidence. This
increment implements an offline consistency audit for a normalized price
capture. It does not fetch a price or implement a vendor adapter. No application
module imports the audit, no production route changes, and the source-anchored
EPS calculator still accepts only explicitly hypothetical prices.

`validation.dated_price.audit_dated_price_capture` returns `contract_passed`,
not `available` or an admitted evidence item. Both successful and failed outputs
set `admitted=false` and `launch_ready=false`. Success means supplied bytes,
receipt, expected security and dates agree under an explicit supplied tolerance.
It is not proof that the source served those bytes or that the price is true.

## Explicit input contract

The first argument is immutable UTF-8 JSON bytes, with a computational size
bound of 65,536 bytes. This is a normalized-capture limit, not a change to any
SEC/model/public-document transport envelope. Duplicate keys, JSON numeric
scalars, nonfinite constants, malformed UTF-8, excessive nesting, unexpected
keys and missing required fields fail closed. Prices use bounded positive
decimal strings; no float conversion or exponent notation.

The normalized object has exactly four keys:

- `schema`: `dated-price-capture-v1`.
- `source_url`: exact separately expected source URL.
- `security`: exact symbol, ten-digit nonzero CIK, listing MIC, security ID,
  share class, instrument type, currency, price unit and split basis.
- `observation`: decimal-string value, kind, observed-at timestamp, session and
  source field identifier.

Security must agree field-for-field with the separately supplied expected
mapping. The initial supported subset is `underlying_common_share`, USD and
`USD/share`. ADRs, FX, preferred shares, funds and conversion shortcuts are
unsupported, including when the caller supplies a matching expected ADR object.
The identifiers are consistency constraints, not a validated security master.
No real issuer, listing or source price is built into the implementation.

Only explicitly labeled `last_trade` or `official_close` from a `regular`
session is supported. Bid, ask, profile snapshots and unspecified sessions do
not acquire trade semantics. The label itself does not verify an exchange
session, an official close, licensing or market-data delay.

The receipt has exactly SHA-256, byte length, source URL and retrieved-at. Hash
and length must match the supplied normalized bytes. A changed body with an old
receipt fails; a fabricated body with a newly fabricated matching receipt can
pass consistency. A test preserves this limitation explicitly.

Source references require HTTPS domain syntax without user information, query,
fragment, port, escaped characters, IP literals or common internal-only suffixes.
This is syntactic screening without DNS or network access. It does not establish
public reachability, a source allowlist, inspectability or secret absence in an
arbitrary path. A future adapter must supply a reviewed public reference rather
than reuse a credential-bearing request URL. Diagnostics never echo source URLs,
body values or exception messages; failures use a fixed rejection code and an
exception-class label.

## Time and freshness

All timestamps are explicit second-resolution UTC instants, not dates, IPO dates,
local times or invented retrieval-as-trade times. The order must satisfy:

`observed <= retrieved <= evaluated` and `observed <= analysis_as_of <= evaluated`.

Evaluation cannot be future-dated relative to the runtime UTC clock. Analysis can
precede retrieval for an explicitly retrospective audit; this does not assert the
capture was available to an investor at the historical analysis instant.

Freshness requires a supplied `policy_id` and integer `max_age_seconds`.
Observation age relative to `analysis_as_of` must be within that tolerance,
including its exact boundary. No default is selected. The allowed 0–604800
range is a computational contract bound, **not approval of any market freshness
threshold**. No calendar, holiday, trading-hours, delayed-feed or current-session
policy is certified here. A retrospective pass does not mean current today.

## Required next integration

1. Review a concrete provider's documented raw response, endpoint permissions,
   field semantics and public-reference policy. Preserve raw-to-normalized
   bindings; a caller-authored `source_field` and hash alone are insufficient.
2. Review the actual security mapping, currency/unit, listing/share class,
   split/corporate-action basis and any later ADR handling. No ticker-only grant.
3. Choose and review freshness/session policy for the intended user question.
4. Bind the compatible price and sourced EPS, including fiscal-vs-TTM/forward,
   earnings scope and split basis. Keep exit multiple, growth and horizon as
   explicit assumptions. The current scenario bridge must continue rejecting
   source-price assertions until this integration is reviewed and tested.
5. Independently adjudicate factual accuracy and useful answers across the frozen
   development cohort, then reserved holdouts and signed-in acceptance.

No claim of price availability, P/E verification, question-completeness increase
or launch-blocker completion percentage is made by this increment.

## Offline validation

The 98 new cases cover identity/listing/share-class/split mismatches, unsupported
currency and ADRs, values and observation kinds, explicit UTC chronology,
freshness boundaries and missing policies, receipt corruption, JSON duplicates
and malformed/resource-bound inputs, sanitized failures, output copy isolation,
and the unchanged source-price rejection in the existing EPS bridge.

Use pinned CPython 3.11.9 with the audited dependencies and this socket-denying
wrapper. It uses invented credentials, not credential files or live probes:

```bash
env -i PATH=/usr/bin:/bin OPENAI_API_KEY=TEST_ONLY \
SEC_USER_AGENT='Test contact@example.invalid' "$PINNED_PYTHON" -I -B - <<'PY'
import sys, socket
sys.path[:0] = ['.', 'tests']
socket.has_ipv6 = False
sys.addaudithook(lambda e, a: (_ for _ in ()).throw(RuntimeError('network blocked'))
                if e.startswith('socket.') else None)
import pytest
raise SystemExit(pytest.main(['-q',
    'tests/test_dated_price_capture.py', 'tests/test_source_anchored_valuation.py',
    'tests/test_valuation_scenario_checker.py', 'tests/test_fmp_profile_price_boundary.py',
    'tests/test_fmp_provider.py', 'tests/test_valuation_numeric_inputs.py',
    'tests/test_valuation_period_labels.py', 'tests/test_source_answer.py',
    'tests/test_evidence_references.py', 'tests/test_threshold_evidence_admission.py',
    'tests/test_valuation_consistency.py', 'tests/test_provider_secret_diagnostics.py']))
PY
```

This related suite passed 586 tests without warnings. The initial narrower
218-test run is a subset, not additional regression coverage. Run the same wrapper
separately with `tests/test_monitoring_freshness_pilot.py` and
`tests/test_source_monitoring_pilot.py`: 36 existing synthetic tests passed without
warnings, for 622 regression tests in total. Import smoke passed with 135 routes.
The new file collects 98 cases. Hosted CI and independent review remain separate
requirements.

No live requests, model calls, approval creation, historical ledger edits,
holdout outputs, production flags, transport/claim/fencing/quota/deadline changes
or provider access were performed. All eleven live approvals remain consumed;
FMP/NewsAPI/FRED exclusions in frozen pilot policies are unchanged. The PR301
combined-suite thread warning remains documented there; this increment neither
diagnoses nor claims to repair it.
