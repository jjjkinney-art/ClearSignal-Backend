# Retained segment economics: source review and implementation boundary

This is an unblinded engineering source review at backend main
`e1efa689e4b72fe836563270d566113fcbca6f33`, after PR324. It is not a
new answer, independent factual/usefulness adjudication or launch acceptance.

## Deployment checkpoint

Render reports deploy `dep-dbca638u01pc73d2bhj0` live for that exact commit.
A read-only GET to `/healthz` returned HTTP 200, `status: ok`,
`build_commit: e1efa689e4b7`, and `environment: production` at
`2026-10-21T12:36:20Z`. This checks process identity/liveness, not research
quality, signed-in flow, provider availability or scenario activation.
No financial provider/model request or configuration change was made.

## What the retained source actually contains

The original PR292 filing body remains unchanged: 1,404,517 bytes, SHA-256
`8d9ea0ecbc1619994be67fe36900878ae6c825ba99047373ad749f9caedab8a1`.
Its receipt does not establish independent origin authenticity.

`SEGMENT_ECONOMICS_SOURCE_MAP_20261022.json` inventories local table structure.
Opening-table index 27, in Note L's segment discussion, spans decoded raw-HTML
characters `[1143293, 1230702)`; its exact UTF-8 re-encoding hashes to
`89079bbca4d1cd1d6b1fd6e01ee8ac72d678caf0bb5aceae43f7bbede6c21a03`.
These are raw HTML character offsets, distinct from normalized Business-section
offsets used by PR323/324. The selected table has 33 rows and 96 inline facts.

The following are printed table literals under **“(in thousands)”**, not new
normalized USD claims. Parentheses are preserved from the display; the map
keeps the underlying split cells and fact attributes.

| Year ended December 31 | Row | Housewares / Small Appliance | Defense | Safety | Total |
| --- | --- | --- | --- | --- | --- |
| 2025 | External net sales | 95,604 | 405,937 | 1,983 | 503,524 |
| 2025 | Operating profit (loss) | (9,292) | 58,383 | (8,850) | 40,241 |
| 2024 | External net sales | 102,799 | 284,025 | 1,404 | 388,228 |
| 2024 | Operating profit (loss) | 12,602 | 42,853 | (10,242) | 45,213 |
| 2023 | External net sales | 97,619 | 241,703 | 1,590 | 340,912 |
| 2023 | Operating profit (loss) | 7,352 | 38,286 | (10,605) | 35,033 |

This is substantive evidence availability in an already retained source. It
must not be described as information missing from the filing. It does not
establish the authenticity of the filing or independently adjudicate these facts.
No exposure percentage, margin, growth rate, causal driver or investment
conclusion has been calculated from these literals.

## Why a sentence rule will not repair this gap

`thesis_disclosures.extract_business_descriptions` deliberately searches the
complete Business section for bounded qualitative sentences. Note L's table
is elsewhere in the document and requires numerical and dimensional binding.
Increasing the two-description cap or relaxing a sentence regex does not provide
that binding.

`app/providers/sec_inline_facts.py` deliberately accepts consolidated contexts:
`_resource` requires an entity with only its identifier, excluding a segment
child; `validated_observation` requires `scope == consolidated`. The table's
segment facts instead reference dimensional contexts. For example, the Defense
2025 revenue fact `c141930511` references
`d_2025-01-01_2025-12-31_ConsolidationItemsAxis-OperatingSegmentsMember_StatementBusinessSegmentsAxis-DefenseMember`.
Its tag name is `us-gaap:Revenues`, `unitRef` is `USD`, and `scale` is `3`.
These attribute spellings are inspection evidence only. A context ID containing
“Defense” or a unit named “USD” cannot itself prove segment or currency meaning;
namespace-resolved context/unit definitions must be validated.

There are important accounting caveats near the table:

- The filing defines operating profit here as earnings before other income and
  income taxes.
- It says corporate activity costs and associated assets are included within
  Housewares/Small Appliance for all presented periods. A future answer must
  retain this caveat before interpreting that segment's reported losses or assets.
- The table's selling/general expense row carries footnote (1), excluding
  depreciation and amortization. Depreciation is a separate row. Do not silently
  treat that row as an all-inclusive operating expense definition.
- Header cells use colspans and display values use separate currency and closing
  parenthesis cells. Indexing each nonempty cell as a separate segment would
  misassign values. The source map retains empty cells and span attributes.

The preceding-context string in the JSON is a diagnostic preview assembled from
visible text, not a citation span. Production claims must bind the original
context paragraphs separately; the preview cannot serve as admission proof.

## Next shared product repair

Implement a separate, source-bound segment observation contract, leaving the
consolidated parser and its exclusions intact. Start with explicit annual
external revenue and operating profit/loss, rather than arbitrary metrics or
promotional sentence clipping. This is a capability boundary, not an issuer rule:
no ticker/member-name allowlist or interpretation of context ID text.

1. Resolve XML namespaces, issuer identifier, annual duration, unit definition,
   transform, scale and sign from the same complete document. Reject duplicate
   identifiers, typed/unknown dimensions, ambiguous periods, conflicting values,
   unsupported transforms and mislabeled consolidated/segment totals.
2. Preserve the actual dimension/member identities and bind their display labels
   to the same table/filing. Inspect the consolidation axis as well as the segment
   axis; stripping all dimensions would contaminate consolidated evidence.
3. Bind table headers, metric labels, displayed values and material definitions/
   allocation footnotes. A claim needs more than the scalar quote currently used
   by consolidated Inline XBRL references.
4. Reconstruct this proof at final admission and keep segment observations apart
   from consolidated comparisons. Missing or inconsistent metadata remains a gap.
5. Only then derive dated exposure/margin comparisons with checked totals,
   explicit denominators and allocation caveats. Increasing segment revenue is
   not proof of pricing, volume, demand, competitive advantage or future returns.
6. Replay the retained source before/after through the ordinary answer route,
   preserving existing claims/citations/gaps. Test unseen synthetic labels and
   adversarial dimensions, units, signs, duplicate IDs, column spans and footnotes.
   Obtain independent factual/usefulness review under the existing gate before
   treating the richer answer as useful research.

No current answer is improved by this inspection-only change. Products/services,
causal operating explanations, counter-evidence and valuation relevance remain
open alongside the segment economics implementation. The frozen 100-company
benchmark and holdouts are unchanged. All twelve historical live approvals stay
consumed; this source map grants no external capture, model call, spending,
activation or live acceptance authority.

## Reproduction and verification

From repository root, using the already retained PR292 capture:

```bash
python scripts/inspect_retained_html_table.py CAPTURE/npk-filing.html CAPTURE/npk-filing.html.receipt.json NEW_OUTPUT.json --table-index 27
```

The CLI accepts only local paths, checks the receipt's body hash/length/media
type, decodes strict UTF-8, refuses incomplete tables/cells and refuses to
overwrite outputs. It preserves source offsets, row/cell order, structural
attributes and inline fact attributes without normalizing financial values.
Selected tables containing nested tables are refused; an innermost table can
be selected explicitly. CSS/presentation attributes are omitted from the map.
This is a review helper, not a general HTML or XBRL financial parser.

Fourteen focused tests pass on Python 3.11.9 with external sockets denied. They
cover exact Unicode source spans/hashes, entity decoding, sign/scale/context
attribute preservation, colspan structure, hash/length/media mismatches,
incomplete tables/cells, nested selection and invalid indices. The retained
source map was regenerated and compared canonically, and all 544 selected cell
spans were checked against the original HTML. No production module changes.
The initial head passed hosted CI run `39601628048` (all 15 job steps).
The review correction below requires fresh hosted CI at the corrected head.


## Review correction

Review of the inspection helper found two defects outside production code.
Joining HTML text callbacks with inserted spaces could alter a numeric display
literal split across inline markup (`<b>9</b>,292` became `9 ,292`). It now joins
adjacent fragments exactly before collapsing existing whitespace. The helper
also accepted some mismatched or implicitly closed cell/row tags despite its
stated incomplete-structure rejection. It now requires matched cell tags and
explicit row/cell closure, refusing malformed structures rather than completing
them heuristically.

Six additional regression cases cover split inline number text, mismatched
closing tags, missing row closure, a new row before closure, cells outside rows
and a new cell before closure. All fourteen tests pass with sockets denied.
The corrected retained-source map changes seven selected cell whitespace strings
and several table previews; all original source spans, table hashes, row/cell
counts, inline attributes and numeric characters are unchanged. The seven cells
contain loss-parenthesis display text, now without inserted leading spaces.
Neither version normalizes their signs or amounts into financial claims.

The source review remains unblinded and the production segment-economics
implementation remains outstanding. The initial CI success is not a pass for
the corrected head; fresh hosted CI must complete before merge.
