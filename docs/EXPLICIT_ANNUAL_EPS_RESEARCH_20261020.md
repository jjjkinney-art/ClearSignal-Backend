# Explicit annual EPS in normal research answers

Base: PR315 merge `24b34570da63696de862daddbd776350cdd2cce6`.
This change is implemented and verified offline; no new provider request,
production setting change or live approval was used. Twelve live approvals remain
consumed. No valuation endpoint activation, scenario assumption extraction or
broad investment-thesis completion is introduced.

## Defect and behavior

On the clean base, replaying the retained PR314 ASML/NPK Company Facts through
`fetch_verified_metric_evidence` for “Cite the latest annual basic EPS” returns no
items for either issuer. The ordinary metric list requests diluted USD EPS, so
it misses ASML's EUR observations and NPK's current basic observations.

The normal research pipeline now recognizes explicit annual/fiscal-year basic,
diluted, or basic-and-diluted EPS fact questions, including questions without the
word “cite”. It enters the existing deterministic source-evidence view and skips
model stages. It makes one Company Facts retrieval for exact requested EPS
concepts in supported per-share currencies plus Assets anchors. The latest
available annual Assets period must match the comparison, with an unambiguous
reporting currency and exact same accession, filing date and form. No other-basis
or currency fallback, quarterly annualization, stale annual substitution, FX,
ADR conversion, forecast, quote or new source is added.

The renderer uses the existing `_annual_eps_context` contract to reconstruct
reported current/prior values, summary, identity, unit, annual form, availability,
periods and unique admitted reference metadata before publishing. Unrelated
monetary facts, tampered summaries/values, stale or ambiguous references and
conflicting candidates cannot fill an EPS slot. Basic and diluted requests have
separate claim/gap slots. A supported basic comparison cannot make a missing
diluted slot disappear. All observations remain explicitly dated annual facts.

Supported requests preserve USD/EUR or infer one supported reporting currency
from the annual Assets anchor. Conflicting supported currencies and recognized
unsupported currency requests remain gaps. The vocabulary is bounded; arbitrary
natural-language currency/financial interpretation is not claimed.

Questions without explicit share basis, specifically named historical years,
adjusted/IFRS/forward/TTM/quarterly requests, ADR/ADS/preferred requests, broad
thesis/risk/valuation questions and mixed named monetary-metric requests do not
enter this new selector. Their existing routing remains intact. This patch does
not claim to resolve those other question types. Existing threshold and financial
monitoring safeguards remain ahead of this EPS fact renderer.

## Actual retained-source replay

`scripts/replay_retained_annual_eps_research.py` verifies the original PR314
results archive and both bodies/receipts, substitutes only those exact saved
Company Facts responses below the real provider parser, and runs the normal
`_run_investment_pipeline` with persistence disabled. Other provider/profile
outputs, company context and the frozen ticker/CIK map are injected offline.
The test guard refuses external socket, DNS and connect activity; local AF_UNIX
construction is allowed for the runtime. No actual live approval is consulted.

| Question | Outcome |
| --- | --- |
| ASML annual basic EPS, EUR | attributed, 24.73 versus 19.25 |
| ASML annual diluted EPS, EUR | attributed, 24.71 versus 19.24 |
| NPK annual basic EPS, USD | attributed, 4.63 versus 5.82 |
| NPK annual diluted EPS, USD | insufficient evidence, annual diluted EPS gap |
| NPK annual basic and diluted EPS, USD | partial, basic comparison plus diluted gap |
| ASML annual basic EPS, USD | insufficient evidence, no conversion |

All six pipeline responses use source-evidence mode, preserve reference bindings,
skip every model stage and report no assessed investment conviction. The new
response record is `ANNUAL_EPS_RESEARCH_REPLAY_20261020.json`; it does not overwrite
or replace the original capture diagnostics or ledgers.

From the repository root, with audited CPython 3.11.9 and pinned dependencies:

```sh
env -i PATH=/usr/bin:/bin OPENAI_API_KEY=TEST_ONLY \
  SEC_USER_AGENT='Test contact@example.invalid' \
  /PATH/TO/PINNED/python -I -B scripts/replay_retained_annual_eps_research.py \
  /PATH/TO/PR314-results.zip /NEW/replay.json
```

The script imports the existing pytest isolation fixture to substitute unrelated
providers and count skipped model stages. This is offline validation tooling,
not a runtime product dependency. Its own newly created executor workers are
joined with a five-second test bound; production supervision is unchanged.

## Validation and limits

The verification JSON preserves exact focused/combined/baseline warning logs
and collection/import results. Final results: **51 new tests**, **528 related
tests passed**, **18,343 tests collected with zero errors**, **136 import routes**. Existing source-evidence latency tests can emit non-daemon executor
teardown warnings in a combined run; the clean base also reproduces that warning
class. They are recorded, not suppressed or claimed fixed. The new focused tests
and retained replay finish their own workers and do not change the global guard.
Hosted CI is required for the exact published head.

No full historical inventory was independently revalidated in this checkout.
Original captured bodies/receipts are verified by hash and remain unchanged.
Frozen pilot policy, requests, quotas, deadlines, source capture limits, credentials
and consumed records are unchanged; changing product source code necessarily
changes the source binding for any future separately approved live execution.

This is one bounded improvement to the normal fact-answer path, applicable by
source contract rather than ticker or market cap. It is not full /ask HTTP/JWT
acceptance, financial adjudication, real current-directory identity verification,
personalization/save-reopen acceptance, valuation-threshold integration, broad
thesis completeness, or development/holdout benchmark acceptance. The broader
universal-company launch blocker remains open.
