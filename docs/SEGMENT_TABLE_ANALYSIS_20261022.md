# Reconciled segment-table relationships

The existing source-bound annual segment context now supports an explicitly
separate calculation section. It checks reported table totals before presenting
sales shares and operating-profit/external-sales ratios. The reported figures
remain reported evidence; percentages are labelled derived and carry their exact
integer inputs, formulas, fact IDs, currency, annual dates and display rounding.

## Source and arithmetic boundary

The segment XML parser can retain a visible Total column only when its fact
resolves the supported consolidation axis and OperatingSegmentsMember without a
business-segment member. This has scope `reported_segment_total`. Neither this
aggregation nor an individual segment observation becomes a consolidated-company
fact; the original consolidated parser and its dimension exclusions are unchanged.

For both external sales and operating profit/loss, reconstruction checks the
Total header/cell/fact identity, displayed sign/currency, concept, scale, USD unit,
annual dates and dimension scope against every segment. Every input comes from
the same bound table/document. The reported segment amounts must sum exactly to
each corresponding bound total. No rounding plug, tolerance, missing-segment
allocation, inferred total or company-facts fallback supplies a denominator.
“Exact” here describes arithmetic on published values, which may themselves be
rounded; it does not verify the underlying unrounded accounts.

States are explicit: unavailable totals, mismatched totals, matched zero sales,
or matched totals with supported ratios. Missing/unsupported totals preserve the
existing reported segment context. A mismatch retains the source-reported figures
and states the failure; all ratios are withheld. Zero total sales yield no
percentage analysis. A zero-sales segment can have a zero sales share, but no
operating-profit/sales ratio. Negative operating results are retained; loss ratios
can legitimately be below minus 100% and are not clamped.

Supported formulas are:

- Segment external sales / reported segment-table external-sales total × 100.
- Segment operating profit or loss / that segment's external sales × 100.

Ratios retain integer USD numerator/denominator values and are displayed to one
decimal with Decimal half-up rounding in an explicit precision context. The
period, currency and source fact IDs accompany each result. Rounding does not
change reconciliation inputs, and displayed shares need not sum to 100.0%.
No operating-income contribution percentage is manufactured when losses cancel
profits; operating income is never used as a share denominator.

## Answer integration and interpretation

Reported evidence summaries contain the dated amounts and accounting caveats,
without presenting percentages as reported facts. Final binding reconstructs the
nested reconciliation/calculation metadata before composition. The financial
foundation appends a `segment_table_calculation` with provenance `derived` to its
existing interpretation contract, citing the segment evidence and preserving the
revenue/operating-result row references and accounting caveat references.

The human-readable section names its annual period, explains the denominators
and presents one plain-text line per segment. It does not depend on a frontend
Markdown-table renderer. This is backend composition, not browser validation.

A sales share is a share of the reported table, not independently bound
consolidated-company revenue. An operating ratio uses the issuer's reported
allocation and definition; it is not standalone segment economics. The existing
corporate-cost/assets allocation caveat remains beside the reported amounts and
is repeated as a qualification on the ratios. These calculations do not establish
pricing/volume/cost drivers, growth, competitive advantage, valuation,
expected returns or the most material future risks.

## Retained-source comparison

Base is merged PR326, `d38dc06ffcb1c046b2a95659c78691872e6ef9ef`.
`SEGMENT_ANALYSIS_REPLAY_20261022.json` compares the committed original segment
parser/producer/binder with the candidate through real ordinary ingestion,
disclosure retrieval, admission and final composition. Discovery, DNS and HTTP
responses are injected from the existing retained bodies. A socket audit hook
denies external network activity. There is no live financial-provider/model call.

The reproduced baseline must exactly equal PR326's retained candidate result in
`SEGMENT_FINANCIAL_CONTEXT_REPLAY_20261022.json`; it does. The existing eleven
citation IDs, ten non-segment claims, business coverage and unanswered parts are
preserved. The segment claim carries the enriched proof/context; a new derived
interpretation is appended after all prior interpretations. Claim count remains
eleven. The answer remains partial, with business completeness, competitive and
valuation/materiality gaps still open.

The unchanged PR292 filing body is 1,404,517 bytes, SHA-256
`8d9ea0ecbc1619994be67fe36900878ae6c825ba99047373ad749f9caedab8a1`.
The unchanged PR314 facts body is SHA-256
`0f512e8670882f4d201d24252e31ab457f512be1aa6ac9b7243d3b8ec820e19f`.
Receipts and all 19 facts-archive inventory hashes match. Source-origin
authenticity/current availability are not independently established.

For the retained 2025 annual table, segment sales sum to reported table sales of
USD 503,524,000 and operating results sum to reported table operating profit of
USD 40,241,000. The derived relationships are:

| Source-spelled segment | Share of reported table external sales | Reported operating profit / external sales |
| --- | ---: | ---: |
| Housewares / Small Appliance | 19.0% | -9.7% |
| Defense | 80.6% | 14.4% |
| Safety | 0.4% | -446.3% |

Housewares/Small Appliance includes the source-described corporate allocation.
Safety's large negative ratio is not truncated or converted into a forecast.
The example is exposed development evidence, not a ticker rule or an independent
usefulness score. The denominator scope is intentionally narrower than a claim
about consolidated-company revenue.

```bash
python scripts/replay_retained_segment_analysis.py CAPTURE_DIR FACTS_ZIP NEW_OUTPUT.json
```

The CLI refuses existing outputs. It uses one retained facts response and one
retained annual-document response per version. Original source bodies, receipts,
completed execution ledgers and prior results remain unchanged.

## Verification and next gates

31 new tests cover separately bound totals, unsupported/duplicate total metadata,
exact reconciliation failure, zero denominators, negative results, half-up
rounding, global Decimal precision changes, every-segment scope consistency,
derived-metadata tampering and reported-versus-derived final composition. Focused
and adjacent suites, local CI groups, collection/import results, hashes and final
replay checks are recorded in `SEGMENT_TABLE_ANALYSIS_VERIFICATION_20261022.json`.
Full hosted isolated-per-file CI is required before merge.

No new download, route, dependency, schema migration or scenario-flag change is
introduced. Existing source-format/currency/period limitations remain. This is
unblinded engineering validation; independent factual/source/usefulness review,
the frozen development/holdout benchmark and signed-in personalized acceptance
remain open. Products/services, causal operating explanations, counter-evidence
and valuation relevance still require work. No quality pass rate or launch-ready
claim follows. All twelve historical live approvals remain consumed; this change
grants no new source capture, model call, spending or activation authority.
