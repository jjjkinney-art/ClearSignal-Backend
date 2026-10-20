# Nonpositive-EPS recovery scenario — 20 October 2026 Auckland

Base: `b4db0e853e12c221cbd30a89bce3deaf3b86bdf7` (merged/deployed PR308).

## Why this increment is needed

The remaining valuation gap is broader than quote/split compatibility. A read-only
inventory of the six saved PR295 answers found no explicit admitted EPS claim in
`source_answer.claims`; all six answers remain partial. Their recorded gaps are
preserved in [the readiness inventory](PILOT_VALUATION_READINESS_20261020.json).
This is an inventory of visible saved answers, not independent quality grading.

The already retained ACHC Company Facts body reconstructs annual diluted EPS
**−12.16 USD/share for 2025**, versus **2.78 USD/share for 2024**, filed 2026-02-27.
The existing positive-EPS P/E bridge correctly rejects the current loss. Another
identical pilot or a quote alone would not make that positive-P/E calculation
appropriate. No conclusion about the cause or persistence of the loss follows.

## Implemented generic path

`validation.earnings_recovery_scenario.evaluate_earnings_recovery` is a separate,
offline conditional price scenario for reported nonpositive annual EPS. There
are no issuer exceptions, network operations, production imports or automatic
recommendations. The exact source/reference reconstruction previously used by the
positive-P/E bridge is factored into `_annual_eps_context`; `_source_eps` remains
a positive-only wrapper. The existing bridge and quote-binding paths still reject
negative/zero EPS, and their regression tests remain unchanged.

The source anchor must still reconstruct one available, unambiguous annual
USD GAAP diluted-EPS comparison, with the exact final response reference and
historical availability dates. Quarterly EPS is not annualized. Historical zero
or loss is preserved as **context only**. The source value is not an input to
scenario arithmetic and is not divided into price or used as a growth denominator.
Positive historical EPS stays with the existing positive-EPS route.

Required future inputs are explicit hypothetical `user_assumption` operands:

- Positive entry price in USD per underlying common share.
- Positive target full-year diluted EPS in USD/shares.
- Positive exit P/E applied to that target EPS, and integer years 1–1000.
- Exact issuer, currency, GAAP, diluted, fiscal-year, total-operations basis;
  share/split compatibility remains a stated assumption, not verified evidence.
- An explicitly dated wholly future fiscal period and excluded distributions.

Source-observation provenance is refused for these hypothetical operands. There
are no defaults, adjusted-loss normalization, inferred break-even year or target
EPS. The target period must start after scenario time, last 300–380 days, end by
the calendar anniversary at the horizon, and lag that date by no more than 380
days. Those are computational contract bounds, not market-policy certification.
An unsupported anniversary, such as February 29 in a non-leap terminal year,
remains a gap rather than silently shifting the day. Future periods are caller
assumptions, not proof of the issuer's actual fiscal calendar or future results.

Arithmetic:

- `terminal_price = assumed_target_fiscal_EPS × assumed_exit_PE`
- `price_factor = terminal_price / assumed_entry_price`
- `annualized_price_change = price_factor^(1 / years) − 1`

The finite target-EPS × multiple product is retained exactly under a bounded
150-digit Decimal context; a Fraction check verifies it. Division/root/change
use 50-digit Decimal precision, ROUND_HALF_EVEN and finite resource bounds,
independently of ambient arithmetic settings. A nonzero price change lost to
rounding, a factor rounded to zero or a change rounded to −1 is refused. Exact
flat and negative conditional price changes are supported. The original reported
loss does not affect these numbers when the assumptions are held fixed.

Output is always partial, not admitted and not launch-ready. It explicitly
contains no current P/E, normalized EPS, EPS growth rate, earnings-recovery
probability, supported forward EPS, expected return or buy/sell threshold.
Dividends, transaction costs, funding requirements and dilution paths are not
modeled. The future per-share assumption must not be described as aggregate
profit recovery or as an independently verified unchanged share base.

## Retained ACHC demonstration

[The replay](ACHC_EARNINGS_RECOVERY_REPLAY_20261020.json) binds the retained raw
Company Facts hash/receipt to a newly reconstructed offline producer comparison.
Its response references are new offline reconstructions, **not original pilot
admissions**. No primary ACHC annual filing body was corroborated in this replay.

- Body length: 3,457,609 bytes.
- Body SHA-256: `b1d48d703acb9cf3f60aaa852af3b91f4c463c554bf1a3d1bbf0ae55d0e977a3`.
- Source: `https://data.sec.gov/api/xbrl/companyfacts/CIK0001520697.json`.
- Captured 2026-10-15; demonstration scenario/evaluation date 2026-10-16.
- Filter the retained records to annual 10-K/10-K/A USD/shares diluted EPS before
  using the existing producer. This is an explicit annual selection, not a claim
  that the latest quarterly EPS was used or that the default live route selected it.

The demonstration assumes a price of 64, target future fiscal EPS 4, exit P/E 25
and two years, with a target period 2027-01-01 through 2027-12-31. These are
**invented offline examples, not actual user choices, observed prices or forecasts**.
They give a terminal price of 100 and conditional annual price change of 0.25:
`100 / 64 = 25 / 16 = (5 / 4)^2`. This is algebraic sensitivity, not an ACHC
expected return or evidence that its earnings will recover. Reported −12.16 EPS
remains visible solely as context. Original body and receipt matched byte for
byte before/after replay; no historical ledger or run output was edited.

To reproduce under the pinned socket-denying wrapper from PR307's review:

```python
import hashlib, json
from pathlib import Path
from app.providers.sec_client import parse_company_fact_records
from app.integrity.sec_metric_evidence import comparable_metric_evidence
from app.services.evidence_references import admit_evidence
from validation.earnings_recovery_scenario import evaluate_earnings_recovery
from test_earnings_recovery_scenario import assumptions
p = Path('/workspace/scratch/a974112f317d/pr292-results-review/extracted/capture/achc-facts.json')
b = p.read_bytes()
assert hashlib.sha256(b).hexdigest() == 'b1d48d703acb9cf3f60aaa852af3b91f4c463c554bf1a3d1bbf0ae55d0e977a3'
records = parse_company_fact_records(json.loads(b), concept='EarningsPerShareDiluted', unit='USD/shares')
item = comparable_metric_evidence([r for r in records if r.form in ('10-K','10-K/A')],
    ticker='ACHC', expected_cik='1520697', concepts=('EarningsPerShareDiluted',),
    metric_name='diluted EPS', unit='USD/shares')
items, refs = admit_evidence([item], evaluated_at='2026-10-16')[:2]
a = assumptions()
a['scenario_as_of'] = '2026-10-16'
a['eps_basis']['issuer'] = 'ACHC'
r = evaluate_earnings_recovery('ACHC', items, refs, expected_cik='1520697',
    assumptions=a, evaluated_at='2026-10-16')
assert r['available'] and r['source_eps']['value'] == '-12.16'
```

## Finite next source/acceptance sequence

1. Review/validate this loss-aware conditional framework alongside the existing
   positive-EPS framework; neither grants an observed quote or expected return.
2. Build the shared production evidence/selection/composition path with explicit
   per-share concept and period labels, without changing source permissions by
   importing an offline helper. Missing EPS or unsupported methods remain gaps.
   ASML's saved financial references are EUR/20-F, outside the present USD/10-K
   filing inspector; NPK's retained numeric facts are basic EPS. Currency/form and
   concept coverage need their own supported paths, not ticker exceptions or
   automatic basic-to-diluted conversion.
3. Before requesting market-data capture, review source adequacy for the exact
   instrument, price currency/unit, observation/session semantics, EPS basis and
   corporate-action interval. FMP publicly documents quote, profile/identifiers
   and split dates/ratios; those descriptions alone do not supply the retained
   observation, full interval or class/basis proof required by our admission gates:
   [quote](https://site.financialmodelingprep.com/developer/docs/stable/quote),
   [profile](https://site.financialmodelingprep.com/developer/docs/stable/profile-symbol),
   [splits](https://site.financialmodelingprep.com/developer/docs/stable/splits-company).
   No provider API call or entitlement probe was made during documentation review.
   Nine quote/profile/split calls alone are not a promised solution to these gaps.
4. Prepare any new source-capture variant offline for exact-diff review and CI.
   FMP remains excluded from the existing frozen pilot: new access, retention,
   spending terms and exact single-run scope require fresh separate approval.
   Do not reuse any consumed approval, ledger or output path. This PR supplies
   no launcher, approval file or execution/spending authority.
5. After sufficient source proof and application wiring, run a newly approved
   bounded development check and independent usefulness/factual review. Reuse the
   existing 100-company/600-question benchmark and its reserved holdouts; expansion
   and signed-in acceptance remain separately gated. Do not equate arithmetic,
   safe partial answers or synthetic tests with useful-answer or launch scores.

No completion percentage or launch date is inferred from this increment.

## Validation

Pinned CPython 3.11.9, audited dependencies, invented fixtures and socket-denying
checks: **1,111 related tests passed**, including **69 new cases**, no warnings.
Separate existing source-monitoring/freshness synthetic suite: **36 passed**, no
warnings. Total **1,147 regressions**; the first 213-test subset is not additive.
Import smoke: 135 routes. Single-process collection: 18,025 tests, zero collection
errors; the existing Starlette/AnyIO deprecation warning was recorded. Hosted CI
and independent review remain pending.

Use PR308's exact related-suite list and PR307's pinned socket-denying wrapper,
prepending `tests/test_earnings_recovery_scenario.py`. Run the same two existing
synthetic pilot files separately. The new cases cover signed/zero source context,
old-route positive guards, exact source/reference reconstruction, positive future
inputs, provenance refusal, currencies/bases, chronology/annual periods, precision
loss, return/input isolation, flat/downside scenarios and independent Fraction
checks. No production setting, transport, deadline, quota, credential/proxy/CA,
claim, halt, fencing, retention rule or holdout output was changed. Monitoring
activation stays off and all eleven live approvals remain consumed.
