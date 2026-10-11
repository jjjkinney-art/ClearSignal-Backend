# Offline conditional valuation arithmetic

This standalone validation module and CLI evaluate explicitly supplied EPS/P-E
scenarios. They are not wired into production answers, do not retrieve prices
or forecasts, and do not select market assumptions. A successful calculation
is not source adjudication or launch acceptance.

Run:

```sh
python scripts/check_valuation_scenario.py validation/valuation_scenario.example.json
```

The example holds EPS unchanged while entry P/E of 20x becomes exit P/E of 45x
over two years. Price rises by a factor of 2.25, corresponding to a conditional
annual price change of 0.5 (50%). Dividends and other distributions are explicitly
excluded. This is not an expected return, total return, forecast or recommendation.

## Explicit contract

Exactly one mode must be specified:

* `evaluate_growth_scenario` supplies `eps_growth_rate` as an annual fraction.
* `solve_required_earnings_growth` supplies `annual_price_return_rate` as an
  annual price-only assumption. Despite the legacy-friendly mode name, the
  solved growth is **EPS growth**, not aggregate earnings or revenue growth.

Both require `distributions: "excluded"`, `entry_pe`, `exit_pe` and `horizon`.
The checked-in example shows every required key. Each P/E contains a decimal
string `value`, `unit: "x"`, `eps_basis` and `provenance`. Rate operands use
`unit: "annual_fraction"` and decimal strings (0.1 means 10%). Horizon uses an
integer `value` and `unit: "years"`. No input, dividend assumption or period is
defaulted; unexpected fields and mode-incompatible operands are rejected.

Entry and exit EPS bases must match exactly: issuer, currency, GAAP/adjusted
accounting, adjustment definition, earnings scope (`total_operations` or
`continuing_operations`), basic/diluted shares, trailing/forward
12-month period basis, and split basis. GAAP uses adjustment_definition `none`;
adjusted EPS requires a nonempty identical definition. These comparisons check
caller assertions, not the truth of financial statements. The period basis
never becomes an observation or publication date.

Each operand requires provenance with `kind` and a specific nonempty `reference`.
`user_assumption` must not include an invented observation date.
`source_observation` additionally requires an explicit ISO `observation_date`.
Dates and references are preserved, not fetched or independently verified; no
freshness claim is made. All-assumption scenarios are valid if labeled honestly.

## Equations and limits

Let M0 and MN be entry/exit P/E, g annual EPS growth, n years, and r the specified
annual price change. Absolute EPS cancels under the compatible basis contract:

```
P_N / P_0 = (MN / M0) * (1 + g)^n
annual_price_change = (P_N / P_0)^(1/n) - 1
g = (1 + r) * (M0 / MN)^(1/n) - 1
```

Positive P/E and annual rates greater than -1 are required for this positive-EPS
multiplicative contract. Unsupported nonpositive earnings/multiples are not
interpreted as investment opinions. There is no tolerance, score or acceptance
threshold for investment attractiveness.

Arithmetic uses an explicit Decimal context: 50 significant digits,
ROUND_HALF_EVEN, exponent limits -999999 through 999999. Results are rounded
Decimal computations, not a promise of exact transcendental roots. Detected rounding loss of a positive factor, supplied tiny rate, multiple
change or annual price change produces unavailability instead of a misleading
boundary value. These guards do not detect every possible rounding difference.
Supported horizons are integer years 1–1000; decimal strings are at most 66
characters. These are technical bounds, not investment policy. Fractional
horizons are rejected rather than rounded. Exponents and JSON floating-point
tokens are unsupported; decimals must be strings. CLI input is limited to
65536 characters. Duplicate keys, nonfinite constants and malformed JSON are
rejected at every nesting level.

Valid JSON with an incomplete/invalid contract returns `available: false` with
a specific reason and CLI exit 2. Successful evaluation returns `available:
true` with equations, inputs, provenance, numeric precision and limitations
(exit 0). Malformed JSON/file input yields a controlled parser error (exit 2).

## Validation and remaining work

Independent Fraction identities establish exact cases: unchanged EPS with
20x-to-45x over two years gives annual price change 50%; 45x-to-20x with 10%
required annual price change over two years requires EPS growth of 65%.
The 59 tests also cover signs, incompatible bases, explicit all-assumption scenarios,
invalid inputs/units/provenance, duplicate keys, ambient Decimal contexts,
precision limits and CLI failures. Network calls are prohibited in the tests.

The existing backend virtualenv was unavailable during this increment. The
stdlib-only checker tests ran in an isolated Python 3.12.14 environment with
pytest; repository application conftest was excluded. Production wiring,
source verification, model-output validation, full application regression and
live acceptance are not claimed. Review/CI must confirm the repository runtime.
