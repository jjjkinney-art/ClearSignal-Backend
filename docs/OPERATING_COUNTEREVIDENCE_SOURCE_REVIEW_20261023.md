# Retained operating counter-evidence: metric and event boundaries

Base: merged PR333, `4d8837f691a960b5801855c7f9cc40719ad49be7`.
PR333 post-merge CI passed. This is an unblinded local source inspection and next
contract proposal. It changes no production answer, quality score or launch gate.

## Findings

The retained MD&A has adverse operating context beyond the current segment sales
explanation: Housewares gross-profit decline and tariff accounting, approximate
distribution-centre relocation costs, expense changes, and a vendor-deposit
impairment. Defense's gross-profit increase appears in the same comparison block.
The point is to preserve supported positive and adverse context with their correct
metrics and dates, not to infer which observation is most material.

The source map records twelve complete MD&A sentences, exact normalized offsets
and hashes, plus two raw financial-statement table rows and their Inline XBRL
context/unit resources. These are extensions of the earlier operating-explanation
inspection; the original map remains unchanged. No new source was fetched.

| Evidence | Exact scope | Consequence for the next repair |
| --- | --- | --- |
| Housewares gross profit falls from $25.478m to $7.589m in 2025 versus 2024 | Gross profit; narrative states sales decline and tariffs | Do not bind these values to the existing operating-income segment row. A separately supported gross-profit contract is needed. |
| Tariffs are generally period costs under the segment's LIFO method | Pronoun-linked accounting-policy explanation | Keep the full antecedent and qualifications; no tariff rate, future cost or quantified earnings impact follows. |
| Relocation reduces gross profit by approximately $1.261m | Approximate cost; pronoun-linked segment | Do not silently remove “approximately” or relabel the cost as operating-income change. |
| Defense gross profit increases while displayed gross-profit/sales percentages fall | Gross profit, distinct from the existing operating-profit ratio | Both amount and percentage context matter. Neither is independent proof of stronger standalone economics. |
| Vendor deposits of $2.701m, subsequent vendor bankruptcy and full-deposit impairment | Three complete sentences, dated 2025, requiring vendor and deposit antecedents | Preserve the exact sequence, assessment and dates. “Recovery deemed unlikely” is management's assessment, not certainty about future recovery. |
| Consolidated income-statement impairment row and cash-flow reconciliation row both show 2,701 at scale 3 | Same custom concept, annual consolidated context and USD unit | One recognized $2.701m impairment. Do not add the observations or describe the non-cash reconciliation as a new cash payment. |
| “The above items” explain the operating-profit change | Aggregate management attribution | This sentence does not independently establish each component's amount, segment attribution or a complete causal bridge. |

The current thirteen-claim answer does not contain any of the twelve full selected
sentences verbatim. That exact-text check does not establish total semantic
absence, prove that every sentence should be shown, or constitute a usefulness
score. The source inspection establishes available context and binding problems.

## Numerical evidence for the next bounded contract

The income-statement row is in raw table index 12, row 7; the cash-flow row is in
table index 13, row 10. All indices are zero based and raw offsets refer to Unicode
characters in strict UTF-8 decoded HTML. These offsets are separate from the MD&A
normalized-text offsets. Each table's exact raw slice is hashed in the map.

Both current-year observations use source QName `npk:DepositsImpairment`, context
`d_2025-01-01_2025-12-31`, unit `USD`, displayed value `2,701`, and scale `3`.
The context identifies SEC CIK `0000080172`, dates 2025-01-01 to 2025-12-31, with
no segment or scenario. The unit measure resolves to ISO 4217 USD. The custom
namespace URI is recorded as source data; its prefix or local name alone is not
semantic qualification under the existing consolidated GAAP fact contract.

Expanding the display by its stated scale yields $2,701,000, agreeing with the
MD&A deposit amount. This is arithmetic and source consistency, not independent
factual adjudication. The consolidated expense does not become a dimensionally
reported Housewares expense merely because the narrative locates the vendor
deposits in that segment. Keep consolidated measurement and narrative segment
context as separate assertions.

## Chosen next shared contract

Implement **a dated management-reported vendor/deposit impairment explanation
linked to a single consolidated expense observation**, before attempting a wider
gross-profit or operating-profit causal bridge.

1. Require an eligible complete annual statement table, visible expense label,
   source-resolved QName/namespace, exact issuer, duration, currency, scale and
   sign. Reject dimensional or conflicting facts. A custom QName needs explicit
   visible-label/statement qualification; do not globally allow custom concepts
   or insert an issuer-specific concept exception into the GAAP parser.
2. Identify duplicate observations across income/cash-flow presentations as the
   same measurement. A cash-flow reconciliation row cannot independently become
   an expense, cash outflow or additive loss. Conflicts withhold the result.
3. Bind the complete MD&A comparison and event passage. Resolve the deposit
   amount, vendor antecedent, calendar dates, impairment timing, full-versus-partial
   wording and recovery assessment without clipping uncertainty or substituting
   an outside vendor identity. Unsupported events or pronouns stay gaps.
4. Match the narrative deposit/recognized impairment amount and reporting period
   to the qualified consolidated observation. Preserve the narrative segment label
   without inventing segment dimensions or treating the amount as a segment-table
   operating-income bridge. Do not map differing segment spellings by guesswork.
5. Reconstruct the scalar, statement label, complete passage, dates, scope and
   references at final binding. Label management attribution and retain limits on
   materiality, recurrence, recoverability, cash timing and future outcomes.
6. Test unseen issuers/custom namespaces/labels, conflicting duplicates, wrong
   issuer/currency/period/sign/scale/dimensions, partial impairments, multiple
   vendors, pronouns, approximate amounts and cash-flow versus expense roles.
   Then replay ordinary ingestion and final composition before/after with all
   previous claims and citations preserved.

This contract is not implemented by this review. The gross-profit/tariff and
relocation passages remain separate follow-up candidates requiring their own
metric and antecedent proof. No historical annual statement should explain a
later quarterly margin movement without independently bound matching evidence.

## Verification and limits

Re-read the original 1,404,517-byte body and receipt; SHA-256 remains
`8d9ea0ecbc1619994be67fe36900878ae6c825ba99047373ad749f9caedab8a1`.
Regenerated normalized text, the complete MD&A source window and all twelve
sentence spans; only leading whitespace/BOM padding is omitted. Checked exact
quote slices/hashes. Reparsed the raw tables and XML resources; verified the two
selected rows, same current-year context/concept/unit/scale, and display arithmetic.
Recorded hashes of the production normalizer, sentence/window and inventory inputs.
The original receipt does not certify independent origin authenticity.

No product code changed and no new implementation-test passes are claimed.
This exposed source review is not independent usefulness adjudication across
company sizes/questions. Broader company explanations, counter-evidence,
valuation, frozen development/holdout gates and signed-in acceptance remain open.
All twelve historical live approvals remain consumed. No capture, provider/model
call, spending, old-ledger resumption, holdout-output inspection, benchmark change
or activation occurred or is authorized by this proposal.
