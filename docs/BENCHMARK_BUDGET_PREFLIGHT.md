# Offline benchmark budget foundation

`validation.capture_budget` is an isolated, opt-in accounting prototype. It does
not import the application, contact providers, read secrets or change production
request handling. The existing capture runner and production provider transports do not use it.
An isolated [fixture-only SDK transport](BENCHMARK_FIXTURE_TRANSPORT.md) exercises
its dispatch claims using synthetic in-memory responses only. Its preflight always reports `execution_allowed: false` and
`hard_usd_cap_established: false`. No spending approval or live execution is
established by this change. Existing capture controls are unchanged; this module
must not be represented as protecting a separately invoked existing runner.

## Actual guarantees within this module

- A policy binds configuration version, approval/pricing reference strings and
  exact bytes of the three saved v2 setup artifacts. References are required but
  are not authenticated approval or independent verification of prices.
- At most six explicitly named cases can be listed: ASML, ACHC and NPK, each with
  `core_thesis` and/or `decision_threshold`. Every case must be present in the
  manifest and in development metadata, absent from reserved holdouts and marked
  non-holdout in the registry. Setup changes invalidate the policy on reopening.
- SQLite `BEGIN IMMEDIATE` serializes reservations across local processes using
  the same ledger. Each reservation accounts for one physical request, including
  each retry. Request fees plus bounded input/output tokens are rounded upward
  to integer nanodollars, while approved budgets round downward. Conversion uses
  exact integer arithmetic independent of the ambient Decimal context. Floats,
  negative/nonfinite rates, unrecognized charge
  fields, unknown routes and units above policy limits are refused.
- Reservations never decrease, including after success, cancellation or timeout.
  Retrying requires another reservation. Missing, ambiguous or excessive usage
  halts subsequent reservations; late pending attempts may still settle after a
  halt. Actual known usage is reported separately from reserved cost.
- A cost/attempt-limit violation, unknown route or oversized reservation halts
  the pilot. One case may be active per ledger, and a case cannot be rerun or
  completed while attempts remain unresolved. This is a caller contract, not a
  dispatcher: the module itself sends no requests.
- Ledger creation is explicit and exclusive. Reopening requires existing state
  and an identical policy; missing files/tables are not silently reset. This
  assumes trusted durable local storage. It cannot defend against ledger
  deletion/replacement, rollback of the disk, creating a second pilot ledger,
  direct database tampering or bypassing the module.
- Preflight accepts exactly one case and creates a UUID artifact with setup and
  policy hashes. Its output uses exclusive creation and cannot overwrite an
  existing file. There is no `--execute` option. A preflight artifact does not
  consume a ledger case and is not a capture or quality result.

## Offline usage

Construct a policy with `schema_version: 1`, nonempty `pilot_id`,
`approval_reference`, `configuration_version`, `pricing_review_reference`, a
positive decimal-string `budget_usd`, positive integer `maximum_attempts`,
`approved_case_ids`, and `setup_sha256` from `setup_binding()`.
`prices` maps exact provider/model/operation route identifiers to:

- `currency: "USD"`, `all_incremental_charges_accounted: true`;
- decimal strings `request_usd`, `input_token_usd`, `output_token_usd`;
- integer `maximum_input_tokens` and `maximum_output_tokens`.

The all-charges flag is a reviewed input assertion, not proof. No real prices or
approved budget are supplied. Tests use invented fixture prices only.

```
python -m validation.capture_budget --policy /path/to/reviewed-policy.json \
  --case ASML:core_thesis --output /path/to/new-preflight.json
```

`AttemptLedger(path, policy, create=True)` explicitly initializes offline state;
`AttemptLedger(path, policy)` reopens it. `begin_case`, `reserve`, `settle` and
`finish_case` exercise accounting only. Bound fixture reservations require `claim_dispatch()` before dispatch, and only
one claimant can succeed. Accounting-only unbound reservations cannot claim.
New ledgers use schema version 2; older ledgers are refused without migration.

## Required integration before any spending

1. Obtain explicit user spending approval and a verified execution environment
   using existing authorized credentials. The inspected local environment has
   no provider credentials; production presence/configuration is unverified.
2. Independently verify current provider/model prices, account-specific fees,
   currencies, chargeable cache/reasoning/tool units and every external request
   route. Unrepresented fees require an extended reviewed schema or refusal.
3. Inventory actual model selections and every nested/SDK retry. Establish
   tokenizer-based upper bounds covering complete serialized requests, outputs
   and any other billed units. Supplied bounds here are trusted inputs; this
   module does not measure payloads or impose provider-side token limits.
4. Route **every physical chargeable attempt** through audited transports that
   reserve before dispatch. Disable hidden SDK retries or instrument each one.
   Ensure one reservation cannot authorize multiple dispatches. Enforce actual
   payload/output bounds, one case per invocation and the same durable ledger
   across retries/restarts/concurrency. Prevent alternate unmetered routes.
5. Parse provider usage reliably, including failures and late completions, and
   reconcile ambiguous responses conservatively. Detecting excess usage after
   a response cannot undo an incurred charge; predispatch bounds are essential.
6. Bind deployment/build identity and complete effective configuration to the
   approved policy, then independently review and test integration before CI
   approval and any separately authorized execution.

Until all these are covered, no whole-pilot USD ceiling is proven or enforced.
No holdouts, setup metadata, captured responses or acceptance gates are changed.
