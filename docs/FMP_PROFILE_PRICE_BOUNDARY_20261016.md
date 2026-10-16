# Company profiles are not dated price observations — 16 October 2026 Auckland

Base: `53b64bea721cfa78ebbe668551206f757ca1c738` (merged/deployed PR300).

## Reproduced defect

`fetch_company_profile` read `price`, `mktCap`, `pe` and `beta` from the profile
payload, formatted money with `$`, called the price current and P/E trailing,
and set the evidence publication timestamp to `ipoDate`. It accepted the first
record without checking the returned symbol. A company's IPO date cannot date a
quote, and the payload fields alone did not establish currency, trade time,
security/share basis or the P/E period. No live observation was needed to
demonstrate this adapter behavior.

The investigation originally targeted a future dated-price contract. This
concrete existing boundary defect takes priority; this PR does not claim to
deliver the complete quote adapter.

## Changed behavior

The existing one-request profile fetch now emits company-profile context only:
name, provider-listed exchange, sector/industry and the existing bounded
description. The title explicitly says Company profile. Price, market cap, P/E
and beta snapshot fields are omitted rather than relabeled or given an invented
timestamp/currency. A generic payload `timestamp`, date, currency or ADR flag
does not grant price admission. The original description cap remains 300 chars.

The publication timestamp is empty; observation/retrieval dates are not invented.
References retain unknown freshness. Source family stays market data, tier
authoritative secondary, claim type unknown, with a Company profile document
type and structured-API extraction method. No verified financial claim is
created. This is provider context, not independently verified issuer business
evidence or a CIK/security identity mapping.

The request symbol is normalized and bounded to supported ticker characters.
Exactly one object and an explicit matching normalized response symbol are
required. Missing, malformed, multiple or different-symbol records return no
profile. Invalid request symbols fail before dispatch. Optional text fields must
be strings; objects are not serialized as prose. Malformed snapshot numbers do
not discard otherwise usable profile context because those fields are unused.
No extra requests, credentials or provider endpoints are introduced.

One old title test expected market-cap text; it now asserts the intended profile
title and absence of the unsupported market-cap snapshot. All other existing
provider tests remain intact. Existing source-answer and valuation guards are
not relaxed: profile context cannot become an EPS anchor or authorize generated
investment thresholds.

## Requirements still needed for price admission

A future dedicated quote adapter needs reviewed source bindings for:

1. Exact symbol, issuer CIK, listing/exchange and security/share class, including
   any underlying-share/ADR conversion and split basis.
2. Explicit currency and price unit; distinguish a trade/close/bid/ask and avoid
   silently treating all provider numbers as the same observation type.
3. A precise source observation timestamp/timezone, retrieval time and analysis
   boundary; use a reviewed freshness/market-session policy, not an IPO or
   retrieval date as trade time.
4. A finite positive source value, exact source-field/response provenance and
   credential-free inspectable reference. Consistency checks and source receipt
   are distinct from independent factual adjudication.
5. Compatible EPS currency/security/split and period semantics. Fiscal-year EPS
   must not become current TTM/forward earnings. Future exit multiples and growth
   assumptions remain assumptions, never market facts or the user's own choices
   merely because a model generated them.

These are review requirements, not source authorization, new endpoint access,
an approved freshness threshold or spending authority. The PR300 offline bridge
continues accepting hypothetical prices only; no observed-price path is wired.
The separate legacy `app/providers/fmp_client.py` market snapshot and other FMP
valuation/estimate adapters are not modified or newly certified by this fix.
This PR closes the demonstrated profile mislabeling, not every quote or valuation
gap. Removing unsupported numbers does not itself improve useful-answer coverage.

## Offline verification

536 regression tests passed on CPython 3.11.9 with audited dependencies, invented
credentials and socket operations denied: 500 related tests including 43 new
profile-boundary cases, plus 36 existing isolated source-monitoring/freshness
pilot tests. Import smoke passed with 135 routes. Tests check exact context
preservation, unknown date/freshness, excluded snapshots, one/no dispatch,
wrong/missing/ambiguous symbols, malformed optional fields, currencies/ADR/generic
date non-authority, secret-free references and unchanged EPS/threshold admission.

The 500-test combined suite emitted one RuntimeWarning from the existing
`TestRouterPipelineIntentFlow::test_pipeline_calls_fetch_valuation_ratios_for_all_questions`:
a ThreadPoolExecutor worker was still alive at test teardown. That test passed
in fresh isolated interpreters on both the clean exact base and this branch
without a warning. The combined-suite warning is retained as a limitation; its
cause is not established or claimed fixed. The synthetic pilot suite had no
warning. An earlier broader command named a nonexistent test file and collected
no tests; it was corrected and is not counted as a passing run.

Use the socket-denying isolated wrapper in
[the existing regression instructions](RISK_FINANCIAL_MONITORING_LINKS_20261016.md)
with this exact related-file list:

```text
tests/test_fmp_profile_price_boundary.py tests/test_fmp_provider.py
tests/test_valuation_numeric_inputs.py tests/test_valuation_period_labels.py
tests/test_source_anchored_valuation.py tests/test_provider_secret_diagnostics.py
tests/test_market_evidence_routing.py tests/test_source_answer.py
tests/test_evidence_references.py tests/test_threshold_evidence_admission.py
tests/test_valuation_consistency.py tests/test_question_anchored_valuation.py
```

The same wrapper with `tests/test_monitoring_freshness_pilot.py` and
`tests/test_source_monitoring_pilot.py` reproduces the additional synthetic suite.
For the warning investigation, use only the full node ID quoted above on each
checkout. Hosted CI and independent review remain pending.

No live request, model call, production flag, SEC/model quota, deadline,
transport/hash rule, ledger or historical record changed. FMP remains excluded
from the frozen live-pilot policies. All eleven live approvals are consumed.
The existing 100-company development/holdout and signed-in quality gates and
launch readiness remain unresolved.
