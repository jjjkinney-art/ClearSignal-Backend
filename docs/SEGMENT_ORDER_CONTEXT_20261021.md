# Historical segment order context — 21 October 2026 Auckland

Base: merged PR323, `1d1f0b7dfb0875b70f58e87497219114ecc57be2`.

## Problem and behavior

The retained annual Business section contains three dated Defense-segment
contract-backlog amounts and an adjacent definition of backlog. The qualitative
business-description producer intentionally rejects numerical prose. Consequently
the source-backed thesis omits potentially relevant order context even though it
is present in the already retrieved source.

A separate bounded producer now admits one historical order excerpt from that
same annual document. It requires an explicitly named segment, three printed
dollar amounts paired by `respectively` with three distinct descending years,
one valid common month/day, and the complete adjacent definition of backlog.
The excerpt comprises two complete sentences; it cannot cross the complete
Business-section boundary or skip an intervening sentence. No document request
or discovery slot is added. Reviewed predecessor context cannot supply it.

The additive `RetrievedEvidence.operating_disclosures` field carries the
producer-bound record. The final binder reconstructs the segment label, exact
printed amounts, dates, approximation status and definition from the quote.
It validates issuer/document/section/date/reference metadata, source offsets,
availability, freshness and the summary. Unknown or tampered fields fail closed;
JSON-type equality also prevents a numeric zero replacing a false boolean.

The new claim kind is `issuer_order_backlog_context`. The final thesis carries
its exact `order_context` and citation, with a one-item final cap independent of
the existing two business-description cap. Business, competition and risk
limits stay intact; no earlier description is displaced by the new item.

## Meaning and limits

- The observations are historical point-in-time backlog as reported, not annual
  sales, recognized revenue, a forecast, a guaranteed conversion pipeline or a
  measure of company-wide materiality.
- Printed amount tokens remain strings, including dollar signs, commas and any
  decimal places. The adjacent excerpt does not establish an ISO currency code;
  `currency_code` remains null. There is no normalization, FX conversion, growth
  calculation or ratio to the financial comparisons.
- The definition is retained beside the values. A subsequent production/shipment
  forecast is not included or transformed into an observed outcome. Delivery,
  cancellations, revenue conversion and profitability remain unverified.
- The parser supports this bounded three-observation prose shape, not arbitrary
  backlog tables, all issuer definitions, currencies or reporting conventions.
  Unsupported formats remain absent rather than being guessed or clipped.
- The ordinary source-backed thesis stays partial. The business-model coverage,
  inferences and unanswered parts are unchanged; no new confidence percentage,
  investment recommendation or valuation threshold is supplied.

## Retained-source replay

`scripts/replay_retained_order_context.py` uses the original PR292 filing and
PR314 facts archive. It verifies the filing's body/length receipt, the facts
receipt and all 19 archive inventory hashes. It executes the actual visible HTML
parser, ordinary thesis-disclosure retrieval with injected discovery/document
responses, producer extraction, final binding, evidence admission and final
source composition. Baseline disclosure retrieval comes from the exact merged
base. Financial production and final composition are shared between runs.

| Retained-source check | Base | Candidate |
| --- | --- | --- |
| Final claims | Nine | Same nine, plus one historical order-context claim |
| Existing claims and reference IDs | Retained | Exactly preserved |
| Business descriptions, including Safety composition | Retained | Retained without displacement |
| Business coverage, inferences and unanswered parts | Partial | Exactly unchanged |
| New context | Absent | Defense backlog amounts at 2025/2024/2023 year ends, definition and exact citation |
| Normalized currency, growth or revenue conversion | Not supplied | Still not supplied |

The two cases each use one local substitution of the retained annual document;
financial facts are assembled once from one retained response substitution.
No external provider request or model call occurs. Exact quotes, before/after
answers and references are in the replay JSON. Hash consistency is not
independent source-origin verification or current-source availability. Directory
identity, filing metadata and source responses are injected; this is exposed
development evidence, not production auth/storage/browser or independent blind
usefulness acceptance. Original source bodies and ledgers are not resumed or
overwritten.

```sh
env -i PATH=/usr/bin:/bin OPENAI_API_KEY=TEST_ONLY \
  SEC_USER_AGENT='Test contact@example.invalid' \
  /PATH/TO/PINNED/python -I -B scripts/replay_retained_order_context.py \
  /PATH/TO/PR292/capture /PATH/TO/PR314-results.zip /NEW/replay.json
```

## Validation and next gates

The new suite covers unseen segment names, exact dates/amounts/BOMs/decimals,
invalid date ordering, malformed amounts, future or ambiguous subjects, mixed
currencies, missing/intervening definitions, section/document exclusions,
source-metadata tampering, both caps and ordinary retrieval through final
composition. Python 3.11.9, unchanged direct dependency pins, related tests, local
CI groups, collection/import checks and source/log hashes are recorded in the
verification JSON. Hosted full isolated-per-file CI remains required before merge.

This is an additive response-evidence field and a bounded source/answer increment,
not a new provider or an activation change. Source quotas, deadlines, frozen
benchmark/holdouts and all consumed approvals are unchanged. The maximum admitted
thesis context grows by one excerpt from the same document, not by a new fetch.
There is no live run, spending or fresh-source retention authority.

Business products, revenue drivers, actual segment economics, counter-evidence,
risk materiality and competitive strength still need substantive work. Independent
factual/usefulness adjudication, development/holdout validation and signed-in
personalized acceptance remain open. No company pass rate or launch-readiness
percentage follows from this replay.
