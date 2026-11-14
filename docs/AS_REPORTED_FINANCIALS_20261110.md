# IFRS and as-reported-currency annual comparisons (default off)

Status: do-not-merge draft on `quality/ifrs-as-reported`, from the Task 1 head `e5e7930`, reviewable independently of the
remedy router. Offline work on retained SEC facts only: no live retrieval, provider, spend, pilot, merge or deployment.
#383, #384 and Cohort 6 are untouched.

## What it does

`settings.as_reported_financials_enabled` (default `False`). With it off, nothing changes. With it on, when the existing
US-GAAP USD/EUR path found no comparison for an issuer, the sec_metrics task builds **annual** comparisons from the Company
Facts response that path already fetched (handed over through an optional `capture` argument; **no additional request**) for revenue, operating income, net income and operating cash flow from:

- `ifrs-full` facts (Revenue, ProfitLossFromOperatingActivities, ProfitLoss, CashFlowsFromUsedInOperatingActivities), or
- `us-gaap` facts in a currency other than USD or EUR (for example CAD),

taken from annual filings (10-K, 20-F, 40-F and amendments).

Rules, each withholding with a stated reason rather than guessing:

| Rule | Withheld reason |
|---|---|
| Units are kept exactly as reported. **No currency conversion**, ever; figures in different currencies or taxonomies are never compared or combined | `ambiguous_basis_or_currency`, `no_comparable_prior_year_period` |
| One reporting basis per issuer: the (taxonomy, currency) with the most recent annual balance sheet; a tie withholds everything | `ambiguous_basis_or_currency` |
| A comparison is two annual facts of the same concept, unit and taxonomy, one year apart on the same duration, each unambiguous after resolving duplicates (a later filing's restatement replaces the earlier figure) | `ambiguous_current_observation`, `ambiguous_prior_observation`, `no_comparable_prior_year_period` |
| Alias concepts are tried separately and never joined; the latest period wins, ties keep the configured order | |
| Interim facts (6-K, 10-Q) are not compared | `no_comparable_prior_year_period` |
| Zero or non-positive amounts are not turned into percentages | `prior_value_zero`, `non_positive_value` |
| A comparison much older than the issuer's latest balance sheet | `stale_relative_to_latest_balance_sheet` |
| A concept the issuer does not report | `concept_not_reported` |

The existing freshness policy still applies afterwards: evidence that admission marks stale is not shown, as on the US-GAAP path.

## Shared-interface change (approved for this slice only)

Additive metadata on the claims this path produces: `taxonomy`, `currency` (already present for USD/EUR) and
`reporting_basis` (`IFRS` or `US-GAAP`). Claims from the existing path are untouched. The foundation re-derives each comparison
from its two bound facts (`rebuild_as_reported`) and rejects any tampered unit, currency, taxonomy, basis, accession, period,
value or summary. Also additive: IFRS concept labels, `_value()` renders an ISO currency unit that previously raised, the
client's `parse_company_fact_records` gained `taxonomy` and `forms` parameters (defaults unchanged), and the Task 1 outcome record
gained the reason `as_reported_comparison_withheld`.

## Consequences to know

- **No additional request.** Enabling the flag makes the same single Company Facts request as before (tests assert identical
  request counts with the flag on and off, for BP, Marex, Betterware, Fortis and a US-GAAP issuer). If the existing request failed
  there is nothing to read and no retry. The flag stays off in every pilot profile.
- **Decision-threshold answers are unchanged** with the flag on: the path is not used for those questions, so no
  as-reported comparison, margin or baseline appears there.
- **Stale retained data.** Betterware's retained facts end at FY2024, so its comparisons are built but not shown; the answer and
  outcome record say so.
- The legacy sentence "this version does not read IFRS" is replaced, flag on, by one that says the data was read as reported
  and no annual comparison could be shown.

## Evidence (retained bodies, offline)

| Issuer | Before | After | Reconciliation to the retained SEC observations |
|---|---|---|---|
| BP (IFRS, USD) | no financial comparison | revenue, profit from operating activities, net income, operating cash flow | 8 of 8 bound facts match exactly |
| Marex (IFRS, USD) | none | revenue, net income, operating cash flow; operating income withheld (concept not reported) | 6 of 6 |
| Betterware (IFRS, MXN) | none | 3 built in MXN, none shown (stale) | 6 of 6 |
| Fortis (us-gaap, CAD, 40-F) | none | revenue, operating income, net income, operating cash flow in CAD | 8 of 8 |

Matching means concept, unit, period, accession, form, filed date and value equal a retained SEC observation. Flag off, all
48 retained cases are identical to the previous baseline apart from clock text; with the flag on only the four targeted issuers'
thesis answers change (thresholds do not). Full before and after answers: `offline-review/AS_REPORTED_BEFORE_AFTER_20261110.md`.

## Limits

Annual only; no interim, quarterly, segment, per-share or balance-sheet measures; no bank, insurer or other sector measures; no
conversion or cross-currency comparison; claim accuracy, coverage and usefulness are not measured here. The 98% accuracy,
95% binding and zero-fabrication launch gates still apply to these claims. Broad-company coverage (including 40-F and 6-K
document reading) and a credible web fallback remain explicit pre-launch work.
