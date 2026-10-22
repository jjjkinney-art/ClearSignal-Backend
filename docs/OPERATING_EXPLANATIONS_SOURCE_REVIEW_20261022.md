# Retained operating explanations: source review

This is an unblinded engineering inspection at merged backend
`b2a777d45f2c05681c9f280b8561e44d4b81cad6` (PR327). It does not improve a
production answer or establish independent factual/usefulness acceptance.
PR327 post-merge CI run 39703181440 passed all 15 steps. A read-only production
health response at `2026-10-22T01:41:30Z` reported `status: ok`, production and
`build_commit: b2a777d45f2c`. This establishes process identity/liveness only.

## Finding

The already retained annual filing contains explicit management explanations
for segment sales and profit changes. The remaining driver gap is therefore
not demonstrated source absence. The existing qualitative Business-section
extractor deliberately cannot supply these numerical MD&A statements. Removing
its numeric filter, enlarging its quote cap or treating segment sales growth as
proof of demand would not provide a sound repair.

`OPERATING_EXPLANATIONS_SOURCE_MAP_20261022.json` retains 17 complete candidate
sentences, exact normalized offsets and quote hashes. It uses the unchanged
production visible-text normalizer and sentence iterator on local bytes only.
The source body is 1,404,517 bytes with SHA-256
`8d9ea0ecbc1619994be67fe36900878ae6c825ba99047373ad749f9caedab8a1`,
matching its existing PR292 receipt. The receipt does not independently establish
source authenticity. The map records the normalizer input hashes and normalized
text hash; these offsets are Unicode character positions, not raw HTML offsets.

Item 7 occupies normalized `[62215, 84983)`. Its first annual comparison block
starts at 64815 and ends at 69242, before the 2024/2023 block. The same comparison
heading occurs again in liquidity discussion: matching the year pair alone is
insufficient to select a results-of-operations context.

## Candidate disposition

These are descriptions of what management attributes to changes, not independently
verified causal findings. The exact source wording remains in the JSON. No new
numerical claim or causal conclusion is admitted by this inspection.

| Normalized passage | Explicit content | Proposed treatment |
| --- | --- | --- |
| 65568–65794 | Housewares sales decreased; units shipped and offsetting pricing are mentioned | Defer initially: the source's 47% offset wording needs careful denominator treatment; never restate it as a 47% price increase. |
| 65795–65959 | Defense sales comparison and increased shipments from backlog | Best bounded first candidate: explicit segment, metric, two amounts, change and a complete management attribution. Bind both annual amounts to the segment table before admission. Backlog shipments do not establish new orders or future conversion. |
| 65960–66051 | Safety sales increased with increased shipments | Potential companion; prior sales are not printed in this sentence. Do not silently compute a missing prior value from change and current amount. |
| 66054–66714 | Housewares gross profit, tariffs, LIFO accounting and distribution-centre relocation costs | Require the complete adjacent context. Do not cherry-pick tariffs or attach the pronoun-led sentences to a segment without a bound antecedent. Gross profit differs from operating profit. |
| 66715–66960 | Defense gross-profit comparison; sales, mix efficiencies and material costs | Requires a separate gross-profit metric contract and preceding comparison context. Source does not quantify or establish the direction of each individual driver. |
| 66961–67101 | Safety negative gross margins and startup/limited-revenue explanation | Keep gross-margin scope and both-year context. Do not promote to a forecast or substitute the operating ratio from PR327. |
| 67104–67842 | Segment selling/general expense changes and management explanations | Separate expense metric/period binding needed; prior-year adjustments and a business sale must remain explicit. |
| 67843–68326 | Vendor deposits, bankruptcy and impairment across several sentences | Require a bound multi-sentence event chain. A single pronoun-led impairment sentence is insufficient to identify the segment, deposit or counterparty. |
| 68329–68703 | Other-income decline, financing effects and inventory investment for Defense awards | Mixed company/segment scope with a two-sentence antecedent. Do not call this segment operating profit or infer a quantified inventory-to-interest mechanism. |

The JSON's business-predicate results are an isolated diagnostic, not a run of
the Business producer or final answer gate. In addition to the numeric/length
exclusions, these passages lie outside the eligible Business section. They need
a separate MD&A contract rather than a relaxed qualitative-business rule.

## Next shared implementation slice

Start with explicit segment net-sales comparisons and management-attributed
shipment explanations. Use a shared grammar and source structure, with no ticker,
segment-name or context-ID allowlist. Require all of the following:

1. A complete eligible annual Item 7 section, an explicit results comparison
   heading and a bounded comparison block. Reject TOC/cross-references, liquidity
   repetitions, missing closing boundaries and conflicting years.
2. An explicit segment subject within the complete explanatory sentence. Preserve
   the exact full quote, comparison-heading reference and source identity.
3. Namespace/dimension/unit-bound segment sales for both annual periods in the
   same filing/table. Match the source-spelled segment label, amounts and periods;
   verify any printed change or percentage without manufacturing omitted values.
   Existing latest-year ratios alone do not establish this two-period contract.
4. Label the explanation as management's attribution. It does not independently
   establish cause, demand, new awards, pricing power or future revenue. Retain
   unresolved offsetting drivers and avoid company-wide scope promotion.
5. Reconstruct the proof at final admission. Preserve existing claims, citations,
   accounting caveats and unanswered parts through an ordinary retained ingestion
   and final-composition before/after replay.
6. Test unseen segment labels and adversarial periods, repeated headings, mixed
   units, amended/comparison mismatches, missing prior amounts, ambiguous pronouns,
   forecasts, promotional clauses and numeric/proof tampering.

The exposed Defense sentence is a development example, not a frozen benchmark
pass. This review does not inspect holdouts, change the 100-issuer/600-case
benchmark, activate flags, resume ledgers or grant new live execution/spending
authority. All twelve previous live approvals remain consumed. Products/services,
counter-evidence, valuation relevance, independent usefulness and signed-in
personalized acceptance remain open.

## Verification

Re-read the local body and receipt, checked byte count/SHA-256, regenerated the
full normalized text with `_HTMLTextExtractor.normalized_visible_text` using
`preserve_sec_risk=True`, and checked every recorded quote against its exact
`[start:end]` slice and SHA-256. Repeated the comparison-block selection and
sentence inventory using `risk_sentence_spans`. No network access is needed for
these checks. No product code changed; existing CI results above are deployment
checkpoint evidence, not new tests for this document-only inspection.
