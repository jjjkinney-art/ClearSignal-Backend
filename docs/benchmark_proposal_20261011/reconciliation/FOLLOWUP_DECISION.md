# Cap evidence follow-up and narrow source choice

The 45 discrepancies have now been investigated individually, with primary
share-count and security evidence where accessible. They are not 45 arithmetic
defects. None changes the observed size tier. No company has been admitted and
no new source convention has been applied.

## Material findings

| Case | What the evidence establishes | Remaining limit |
|---|---|---|
| GEF | July 27 A/B counts and October 9 class prices produce **$4.338bn**. The $3.78bn and $4.65bn displays can instead be reproduced using different Class A pricing proxies. | Intervening share changes remain unreconciled; the numerical matches do not prove vendor methodology. |
| NNBR | August 5 primary shares × October 9 close produce **$326.194m**. The summary uses a substantially larger implied count. | Inspected primary evidence does not explain the secondary 93.74m shares. |
| LLY | August 3 primary shares × October 9 close produce **$1.110tn**, supporting the historical display. | The secondary 891.36m share count differs materially from the primary 941.357065m. |
| EQNR | A confirmed 1:1 ADS ratio excludes a simple conversion-factor error. The historical cap reproduces a year-end 2025 count; later capital and treasury disclosures change the count. | Need free issuer transaction/capital disclosures covering October 5–9. Prior weekly publications were Tuesdays; the next publication date is not promised. |
| PETS / JOUT | Lower cap observations numerically track exclusion of issued restricted shares. Primary gross-count estimates are **$27.857m / $448.111m**. | Count dates differ from price dates. JOUT additionally requires an explicit unquoted Class B valuation proxy; it is not an observed B price. |
| GRC | July 27 primary common shares × October 9 regular close produce **$1.954bn**, corroborating both $1.95bn displays below $2bn. | A dated reported-share estimate, not proof of the exact October 9 share count. |

Seven of the eight other domestic cases now have SEC-count estimates: AJG
supports the summary display; NVDA, VTR, PG, NEE, SHW and RHI support historical
display neighborhoods. Visa now has a July 21 class table and September 18
conversion ratios: the conditional conversion-parity estimate is $719.228bn;
Class A alone is $656.850bn. Neither reconciles the two vendor caps. NVIDIA's
primary count is itself rounded. None of these matches establishes the
publisher's calculation or removes the disclosed date gap.

All products, operands, source URLs, retrieval timestamps and limitations are
stored in the five follow-up JSON files listed in
[the admission summary](followup_admission_summary.json). The additional
[GRC boundary check](grc_boundary_followup.json) is separate from the 45 conflicts.
Percentages in the combined summary use the summary cap as denominator.

## Smallest source-policy choice

For **19 named cases only**, the differences are $10,000–$50,000, or
0.00110572%–0.02050651% of the summary value. Provider documentation identifies
USD-million units but does not confirm the publisher's rounding convention.
No tolerance has been inferred from these amounts.

**Proposed choice:** use the published October 9 historical-row value, at its
displayed precision, as the classification value for these 19 names; preserve
both observations and their unconfirmed cause. This chooses a dated source field;
it does not certify that the competing values are equivalent.

RGR, SWBI, BGS, HBB, VLGEA, CAL, ANGO, UTMD, USNA, MLR, MTRX, PLOW, SGC,
NATH, RELL, ACNB, CCBG, NGS and FRPH.

If approved, this would resolve the benchmark's source-field selection for those
19 only. It would not authorize execution, automatically admit a company,
waive its class/identity checks, or resolve the other 26 cases. The alternative
is to retain these 19 blocks until a provider correction or documented dated
value resolves them. **The proposal is not approved or applied.**

The larger cases retain their specific evidence tasks, especially Greif's class
prices, NN's larger secondary share count, Lilly's conflicting count, Equinor's
capital changes, and PetMed/Johnson Outdoors' issued-restricted-share treatment.
No blanket latest-reported-share convention is activated. Dated estimates are
useful evidence under the provisional-source policy, not a new requirement for
an independent audit of all shares and prices.

Holdouts and their unknown exposure outside the audited repositories are unchanged.
There were no ClearSignal answer captures, paid data calls, or production actions.


## Practical completion path for the other 26

The 19-name source choice remains pending and is independent of this proposal.
Do not spend additional research cycles proving a publisher's exact calculation
when the benchmark only needs a defensible size classification.

**Recommended separate policy decision:** permit a classification-only admission
review using October 9 regular-close USD prices and dated, publicly reported
company-wide common shares available by that date. Preserve the actual count,
price and publication dates; exclude treasury, include issued restricted common
shares, and adjust known intervening capital actions. Keep the two vendor values
and their unresolved cause in the audit record. This is an explicitly provisional
reported-share estimate, not certification of exact October 9 capitalization.
It changes the current conflict-admission rule and therefore requires approval;
it is not activated by this document. It introduces no numeric tolerance.

| Evidence group | Names | Exact remaining limitation and action |
|---|---|---|
| Primary common-share estimates already calculated | NNBR, LLY, PETS, AIN, WDFC, NOG, NVDA, AJG, VTR, PG, NEE, SHW, RHI, TDAY | Count dates precede October 9; exact intervening share movements/vendor methodology are not established. Under the proposed convention, review known corporate actions and retain dated estimates instead of demanding exact provider reconciliation. AIN is closest to a boundary in this group: $1.75512bn versus $2bn. |
| Quoted classes / known capital changes | GEF, EQNR | GEF has both actual class prices and July counts. EQNR has July issued capital and October 2 treasury counts, published October 6; October 5–9 movements remain unverified. Apply the reported-share convention only if approved, with these limitations explicit. |
| Unquoted/restricted class valuation | JOUT, V | Counts are available. JOUT needs an explicit A-price proxy for B; Visa needs explicit conversion-parity valuation for B/C and dated ratio treatment. These are separate valuation assumptions, not missing arithmetic or raw-count aggregation. |
| Foreign share-count/publication provenance | ASML, NVS, SAP, SONY, TM, RY, BHP, UL | ADR/direct-share identities are established, but the stored evidence does not establish an adequate dated net company-wide common count for seven names; Sony has a September 30 count but its publication timing is unverified. ASML requires a dated filing to settle reversed share-page labels; TM needs one coherent issued/treasury date; RY excludes preferred equity. Acquire these exact fields from issuer filings before classification-only admission. Two agreeing tiers from one secondary publisher are not independent verification. |

After approval, finish the bounded metadata checks for all 100 names, including
identity, class basis, sector/fiscal/jurisdiction fields and unresolved near-boundary
cases. Recompute 30/30/30 plus ten, company uniqueness, sector/tag coverage and the
unchanged 20-name holdout reservation. Admit only individually cleared names;
do not call a partially cleared cohort a completed benchmark.

Then validate an offline 600-case manifest (480 development / 120 holdout),
source-binding and numerical checker paths using existing permitted fixtures.
Report missing captures separately. New controlled paid/live captures still
require separate authorization; preserve blind holdouts and the existing quality
gates. Neither this source convention nor passing metadata tests supplies quality
acceptance evidence.
