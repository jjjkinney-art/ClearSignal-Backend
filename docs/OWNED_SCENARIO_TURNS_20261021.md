# Explicit scenario turns in authenticated research — 21 October 2026

Base: `35d3cb299283367359aab0d97fb648ea1ae69fe6` (merged PR320).

## Behavior and scope

`POST /ask` can now receive an explicit `conditional_valuation` object with the
existing `{ticker, assumptions}` contract. This separate dispatcher runs only
when BOTH `owned_research_scenarios_enabled` and
`conditional_valuation_scenarios_enabled` are true. Both default false. Retrieval
and real authenticated account state are also required; system/bypass identity
cannot use this path. No production setting is changed here.

Normal questions must omit the new field. An explicitly supplied null or invalid
object is rejected rather than silently reinterpreted as ordinary research.
The internal `route_question` entry point refuses non-null scenario inputs, so
bypassing the HTTP owner checks cannot send them to the generative pipeline.

The existing /ask authentication, beta admission, entitlements, question limits,
rate limits and daily quota run first. An explicit conversation ID and request
reference are required. Ownership and deletion are checked before source work.
Fresh scenarios require a conversation scoped to exactly the explicitly selected
ticker, a matching `company_name`, and matching optional active ticker/as-of.
Portfolio, grounding or selected-memory context is not silently incorporated.
Missing assumptions never receive inferred values or model fallback.

The raw original JSON is checked for duplicate keys, floating-point/nonfinite
JSON tokens and the existing scenario request bound of 16,384 observed bytes.
Declared-length syntax, duplicates and over-limit declarations are checked too.
This check follows FastAPI request parsing; it is not a claim that framework
allocation or process memory is bounded to 16 KiB. No transport, source-selection,
canonical-hash, deadline, quota or live-pilot policy is enlarged.

## Input contract

Create/select an owned research conversation with `tickers: ["ASML"]`, then send
an explicit scenario turn. This is a structural example only, not execution or
spending authority; all numeric inputs below are invented hypotheses.

```json
{
  "company_name": "ASML",
  "question": "Explain this explicit hypothetical scenario.",
  "research_conversation_id": "<owned ASML conversation ID>",
  "research_request_ref": "<fresh client-generated reference>",
  "conditional_valuation": {
    "ticker": "ASML",
    "assumptions": {
      "mode": "evaluate_growth_scenario",
      "scenario_as_of": "<today in UTC, YYYY-MM-DD>",
      "distributions": "excluded",
      "price_per_underlying_common_share": true,
      "price": {"value": "100", "unit": "EUR/share", "provenance": {"kind": "user_assumption", "reference": "My hypothetical input"}},
      "exit_pe": {"value": "20", "unit": "x", "provenance": {"kind": "user_assumption", "reference": "My hypothetical input"}},
      "horizon": {"value": 2, "unit": "years", "provenance": {"kind": "user_assumption", "reference": "My hypothetical input"}},
      "eps_growth_rate": {"value": "0", "unit": "annual_fraction", "provenance": {"kind": "user_assumption", "reference": "My hypothetical input"}},
      "eps_basis": {"issuer": "ASML", "currency": "EUR", "accounting": "gaap", "adjustment_definition": "none", "share_basis": "basic", "period_basis": "fiscal_year", "earnings_scope": "total_operations", "split_basis": "User asserts identical unconverted underlying common-share basis"}
    }
  }
}
```

Numeric operands are explicit decimal strings; the horizon is integer years.
Required-growth mode replaces `eps_growth_rate` with
`annual_price_return_rate`; recovery mode instead requires `target_eps` and an
explicit `target_fiscal_period`. Existing evaluator semantics remain: annual
basic/diluted USD/EUR EPS, no basis fallback, same-filing currency anchor, explicit
price/share assertions, hypothetical exit multiple and distributions excluded.
Actual source sign/basis/period or mathematical failures remain explicit gaps.
The structured scenario object is authoritative for this calculation; arbitrary
question text is not parsed into additional scenario inputs or recommendations.

## Saved response and retry contract

The response uses a general-answer envelope with `answer.direct_answer`,
`answer.general.answer`, exact `evidence_references`, and
`answer.conditional_valuation.{request,result}`. Historical EPS alone is cited;
future earnings, prices, growth and multiples remain assumptions. The service's
standalone no-persistence statement is replaced with the wrapper's actual scope.
No investment-thesis object, thesis memory artifact, portfolio write or alert is
created. Existing History saves the exact response and displayed assistant text.
A missing-source result is also saved with its original inputs and explicit gap.

Persistence is mandatory for this opt-in path. Missing/foreign/deleted ownership
fails before providers; unavailable storage fails closed. An unsuccessful save
never emits an unsaved completed response. One owner-scoped read may recover a
concurrent winner or ambiguously committed response, without redispatching.

An owner/conversation/request reference identifies the original completed turn.
Reusing it returns that exact snapshot, even if question/assumptions change or UTC
rolls over, and adds `X-Research-Turn-Replayed: true`. Use a NEW reference for a
new calculation. JSON and opt-in NDJSON final frames carry the same canonical
payload with `Cache-Control: no-store`. Preflight quotas still apply to retries.
Concurrent first requests are NOT provider-at-most-once. Provider failures without
a completed record may be dispatched again only by a subsequent client request;
this change does not add a durable execution ledger or automatic rerun.

## Offline evidence and remaining gates

See `OWNED_SCENARIO_TURNS_VERIFICATION_20261021.json` for commands, log digests,
results and limitations. The new suite exercises real local signed JWTs, beta
admission, /ask preflight, source evaluation and disposable SQLite ownership.
It checks exact save/reopen, changed-input and next-day no-fetch retries,
JSON/NDJSON parity, scope rejection, source gaps, quota enforcement, both flags,
auth bypass rejection, raw JSON/body bounds, storage/evaluation failure and
ambiguous post-commit recovery. An assertion prevents normal model dispatch.

`replay_owned_scenario_turns.py` verifies all 19 PR314 archive hashes and both
body receipts, then uses the real provider parser and evaluators through signed
/ask for six ASML/NPK scenarios and three source/scenario gaps. All nine displayed
answers and inputs reopen exactly and changed-input retries fetch nothing.
Eighteen foreign-account read/dispatch attempts are denied. No external requests
or model calls occur. Full responses are retained in
`OWNED_SCENARIO_TURNS_REPLAY_20261021.json`; directory/date identity is injected.
The original bodies/ledgers are neither overwritten nor resumed; complete
historical inventories were not independently revalidated here.

This completes a backend contract, not the browser assumption-entry form or
production end-to-end acceptance. Those, real deployment/auth/storage behavior,
concurrent dispatch policy, independent usefulness review and the frozen broad
company development/holdout benchmark remain open. Hypothetical math does not
establish forecasts, expected total returns, attractiveness or launch readiness.
All twelve prior live approvals remain consumed; no live execution, endpoint
activation, spending or fresh retention authority follows. Hosted CI is required
before merge.
