# Conditional scenario explanations — 21 October 2026

Base: `4a4dc586bca2c6db2642e35ed1741a002b234404` (merged PR319).

The existing, default-disabled `/research/valuation-scenarios` endpoint returned
validated source EPS and scenario arithmetic without a composed research answer.
This change adds an `explanation` object after successful source reconstruction
and scenario evaluation. It does not integrate the separate endpoint into `/ask`
or activate it in production.

## Behavior

- Growth scenario: states the hypothetical price, annual per-share EPS growth,
  exit multiple and horizon and explains conditional annualized price change.
- Required-growth scenario: explains the EPS growth mathematically required for
  the explicitly assumed annual price-change target, without assessing feasibility.
- Recovery scenario: explains assumed future annual EPS, terminal price and price
  change. Reported nonpositive EPS remains context, never a growth denominator;
  recovery probability stays unassessed.
- `reported_facts` preserves annual basic/diluted basis, currency, reporting dates,
  filing date and the exact admitted EPS reference ID. Citations are not attached
  to future earnings, assumed prices or multiples. Free-text assumption provenance
  is not interpolated into the explanation.
- Percentages are displayed to at most two decimal places, HALF_EVEN, with
  `approximately` whenever rounding changes a value. Exact decimal fractions
  remain unchanged in `scenario.values`; rounding is presentation only.
- Existing partial status, source/scenario payloads, unanswered parts, no-store,
  identity/authentication, feature/retrieval guards and failure responses remain.
  A failed evaluation has no explanation.

The formatter is an internal presentation function, not an evidence-admission
API. It accepts successful evaluator outputs only; it does not independently
reconstruct or certify arbitrary dictionaries. Producers remain the authority
for source identity, annual-period/currency/share-basis checks and arithmetic.

## Offline verification

See `CONDITIONAL_SCENARIO_EXPLANATION_VERIFICATION_20261021.json` for exact
commands, log digests, results and limitations. Focused tests use actual evaluator
outputs and guarded local HTTP responses for growth, required growth, recovery,
EUR basic/diluted basis, signed losses, negative growth and rounding boundaries.
Related suites include the existing real account-boundary and request contracts.

The updated `scripts/replay_retained_eps_scenarios.py` additionally checks six
successful ASML EUR basic/diluted and NPK USD basic explanations against retained
PR314 bodies. The replay verifies body hashes/receipts and follows actual provider
parsing, evidence reconstruction and the local scenario HTTP handler. Historical
citations and explicit stale/missing EPS and recovery gaps remain intact. Display
percentages are checked independently with exact rational arithmetic against the
unchanged scenario fractions. Full responses are saved in
`CONDITIONAL_SCENARIO_EXPLANATION_REPLAY_20261021.json`.

Replay command (existing archive, fresh report path):

```sh
python scripts/replay_retained_eps_scenarios.py \
  /path/to/ClearSignal-PR314-EPS-source-capture-results.zip \
  /fresh/path/scenario-explanations.json
```

All hypothetical inputs in this replay are invented demonstrations. Network is
blocked; directory, UTC boundary and request identity are injected. This does not
prove live identity, observed price, share/split compatibility, source truth,
scenario usefulness, persistence or personalized `/ask` acceptance. No historical
ledger or output directory is reused or modified; complete historical inventories
were not independently revalidated here.

## Remaining launch work

No buy/sell threshold, expected total return, investment attractiveness,
independently supported future earnings, probability or competitive advantage is
established. No endpoint activation, new provider/model dispatch, live run,
spending authority or broader company-coverage percentage follows. All twelve
live approvals remain consumed. Broader thesis composition, explicit-assumption
user flow, signed-in save/reopen, independent usefulness review and the frozen
development/holdout benchmark remain required. Hosted CI is required before merge.
