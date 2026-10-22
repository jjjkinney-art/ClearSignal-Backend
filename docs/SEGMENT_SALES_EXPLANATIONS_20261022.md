# Source-bound segment sales explanations

Broad thesis answers can now retain a bounded management explanation for a
segment sales change, alongside the reported annual segment results. This is a
shared source grammar, not a ticker or segment-name rule. The current increment
supports explicit shipment-from-backlog and units-shipped sentences. It does not
complete the business model or independently establish causation.

## Admission and scope

The separate segment parser retains an optional adjacent prior-year proof from
the same table only after reconstructing that year's segment observations. The
primary result remains the latest year. A malformed latest year cannot fall back
to the older year. Original consolidated parsing and dimension exclusions remain
unchanged; no additional source request is introduced.

For a 10-K, a complete explicit Item 7 opening and Item 7A closing must bound the
MD&A text. TOC/cross-reference exclusions apply; multiple eligible boundaries,
oversized windows and missing boundaries withhold explanations. The first
comparison heading must match the latest/prior annual years, and the next heading
must identify prior/earlier years. Later repeated liquidity comparisons cannot
substitute for missing results context. This strict shape is intentionally
bounded and does not support arbitrary MD&A formats or foreign annual layouts.

A complete sentence must name the segment and print prior/current sales and a
change, with an explicit shipment explanation. Both values are reconstructed
from the same table's annual proofs with matching labels, columns, namespaces,
dimensions, USD units, scale, periods and accounting caveats. Segment identities
are not inferred from context-ID names. The start dates must have matching
month/day and consecutive years. The printed change and direction must agree
exactly; an optional whole-number percentage must match half-up rounding of the
same values. No omitted prior amount is manufactured from a change.

The complete sentence, comparison heading, prior revenue row and current revenue
row retain document references. Explanation metadata retains exact normalized
offsets, both annual dates, amounts and management attribution. The bounded MD&A
source window and its hash accompany the proof for final reconstruction. These
are source-backed producer proof checks, not independent authentication of the
filing. As with existing document proofs, final binding does not download or
independently authenticate the original source body.

The reported summary quotes management with both periods and explicitly says
that causation, new orders and future revenue are not independently established.
The ordinary final answer preserves the explanation/proof/references. Existing
derived segment ratios remain separate and unchanged. Unsupported language,
conflicts or missing context retain the original segment results without an
explanation. Partial/tampered explanation fields invalidate the evidence item
at final binding rather than silently stripping the unsupported material.

This first grammar does not admit the exposed Housewares pricing-offset sentence,
Safety's sentence with no explicit prior amount, multi-sentence event chains,
pronoun-only descriptions, gross-profit explanations or forecasts. Those require
separate support; a long factual-looking clause is not clipped out of a mixed
sentence. A management shipment explanation does not prove demand, pricing power,
competitive advantage, new awards, backlog conversion forecasts or valuation.

## Retained ordinary-path replay

`SEGMENT_SALES_EXPLANATIONS_REPLAY_20261022.json` compares committed PR328 main,
`4ccaf6a7d20395177c9d5aa21d5b5adae8906f5d`, with the candidate. The original
parser/producer/binder reproduce PR327's archived candidate exactly. Discovery,
DNS and HTTP responses are injected from unchanged PR292/PR314 retained bodies;
an audit hook denies external sockets. There are no financial-provider or model
requests, new captures, ledger resumptions or holdout inspections.

The retained Defense sentence prints sales increasing from USD 284,025,000 to
405,937,000, a 121,912,000 change (43% as displayed), and attributes the change
to increased shipments from backlog. Both annual values match the separately
reconstructed segment table. The exact full sentence and management-attribution
limitation survive normal ingestion, disclosure retrieval, admission and final
composition. This remains an exposed development example, not an independent
quality score or a ticker-specific rule.

Claim count stays eleven. All ten non-segment claims, every citation ID, prior
interpretations and segment calculations, business coverage and unanswered gaps
remain unchanged. The segment claim gains the management explanation and its
source proofs. The answer remains partial, including business completeness,
competitive assessment, valuation and risk-materiality gaps.

```bash
python scripts/replay_retained_segment_sales_explanations.py CAPTURE_DIR FACTS_ZIP NEW_OUTPUT.json
```

The script refuses an existing output and checks source receipts plus all 19
facts-archive inventory hashes. It uses one retained Company Facts response and
one retained filing response per version. Raw-source receipt consistency does not
establish independent origin authenticity, current availability or freshness.

## Validation and remaining gates

Synthetic tests cover unseen segment labels, increases/decreases, optional printed
percentages, exact change/value matching, unsupported language, missing prior
values, currency/dimension/period/namespace errors, duplicate explanations,
heading ambiguity, latest-year failure and proof/reference/summary tampering.
The retained replay checks actual ordinary-path composition and unchanged prior
claims. Detailed local counts and hashes are in
`SEGMENT_SALES_EXPLANATIONS_VERIFICATION_20261022.json`; hosted CI remains a
separate pre-merge requirement.

No route, schema migration, dependency, runtime flag, model or provider policy
changes. All twelve historical live approvals remain consumed. This is unblinded
engineering validation. Independent factual/usefulness adjudication, the existing
frozen development/holdout benchmark and signed-in personalized acceptance remain
open. Products/services, broader operating explanations, counter-evidence and
valuation relevance still require work. No launch-ready claim follows.
