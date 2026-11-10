# Remedy router and source eligibility gate (offline, unwired)

Status: do-not-merge draft on `quality/evidence-remedy`, from `e5e7930` (the Task 1 head). Offline work on retained
evidence only: no live request, provider, spend, pilot, merge or deployment. #383, #384 and Cohort 6 are untouched.
The module is imported by nothing in `app/` or `validation/` and the Task 1 flag stays off: with the module present,
every answer is unchanged.

## What it is

`app/services/evidence_remedy.py` makes the first fallback decisions executable, as recommendations only.

- **`remedy_for(record)`** takes one Task 1 `evidence_outcomes` record and recommends one of: `none`,
  `better_reading_of_retained_sec_evidence`, `new_sec_retrieval_needed`, `retry_same_source`, `alternate_source`,
  `disclose_only`, `withhold`. It never retries, sleeps, fetches or edits an answer (`executes_anything` is always
  false). A retry recommendation names the failure class and says a budget is required; it gives **no attempt count**,
  because that is an unapproved cost decision.
- **`source_eligibility(claim_type, descriptor)`** decides from **metadata only** whether a source may go on to claim
  verification: `eligible_for_verification`, `eligible_labelled` or `withhold`. **It never marks a claim verified**
  (`claim_verified` is always false). Verification is a separate step against retained bytes, which this module cannot do.
- **`arbitrate(candidates, claim_type)`** decides which candidates for one claim may go forward when they disagree. It
  never verifies a claim (`claim_verified` is always false) and applies **no source ranking unless
  `policy.tier_ranking_approved`** (default false): until then any disagreement among eligible candidates withholds
  all of them. Source ranking and conflict resolution remain an open decision.
- **`tier_breakdown(decisions)`** counts decisions by source tier for reporting.

## The five evidence situations are kept apart

| Situation | Task 1 outcome | Recommendation |
|---|---|---|
| Retained readable evidence | `selection_rules_not_met` | better reading of retained text; unproven that the filing has the disclosure |
| Listed but unread filing | `annual_form_not_read`, `interim_form_not_read`, `no_filing_listed` | new SEC retrieval (needs live approval); better reading only if the document is already retained for another need |
| Unsupported retained data | `ifrs_taxonomy`, `non_usd_reporting`, `no_same_period_pair` | better reading of data already held, as filed, in its own taxonomy and currency (no conversion) |
| Confirmed absence | `registration_only_filing_list`, `concept_absent_from_returned_facts` | alternate source, gated, for a registration-only ADR; disclose only for an absent concept |
| Failed retrieval | `failed` + class | per class, below |

Failure classes are classified and recommended separately: 429, 5xx, transport and timeout, time limit, filing-list
failure and not-read give a budgeted retry recommendation; a 404 is **never** absence and is **not retried**
(disclosed as an unproven gap, and flagged for owner review if a retained filing list shows XBRL filings); a 403 is not retried blindly and is referred for access-policy review; a different-entity response and an
oversize document are disclosed (a retry cannot help).

## Policy defaults to unapproved

Every approval a rule needs lives in `SourcePolicy`, whose default approves nothing: identity mappings, home
regulators, licensed market-data providers, event corroboration, labelled third-party figures, and issuer
investor-relations numbers. With the default policy **no alternate-source claim is eligible**, and an alternate-source
recommendation carries `permitted: false` and the approvals it is blocked by. The policies in the tests are invented
fixtures, not decisions.

Decisions already encoded: eligibility never verifies; alternate-source claims are withheld while identity or source
policy is unapproved; opinion is never evidence; third-party characterisation of an issuer is opinion; issuer-published
numbers are not eligible for verification unless a policy says so (decision 1, default off); no publication time or
content hash, or stale or superseded evidence, is withheld; candidate text (titles, excerpts) cannot influence a
decision; wire copies of one origin count once.

Still unapproved (listed in the decision table): which regulators are primary, the ADR-to-issuer mapping rule, the
event corroboration rule, whether labelled third-party figures may appear, the market-data provider and its terms,
and retry budgets.

## Launch gates

Claims that come from a fallback source count toward **the same launch gates as every other claim**: at least 98%
material-number accuracy, at least 95% claim-to-source binding, and zero fabricated sources. They are reported with a
separate breakdown by source tier (`tier_breakdown` counts eligibility decisions by tier; accuracy per tier is measured
by the benchmark, not here). Eligibility is not verification, and nothing in this change measures claim accuracy,
delivered coverage or usefulness. The six pilot criteria are unchanged.

## Explicit pre-launch work (not done here)

1. **Broad-company coverage.** IFRS and as-reported-currency reading, 40-F and 6-K reading, and obscure or foreign
   issuers, so useful research does not depend on being a US-GAAP, USD, 10-K filer.
2. **Credible web fallback.** Source selection, ranking and conflict policy approval, home-regulator access, licensing,
   a market-data provider, spend and latency budgets, and live evaluation on unfamiliar companies.
3. The 3 Oct roadmap has no milestone for either; adding them is a scope decision.

## Tests

`tests/test_evidence_remedy.py` (56 tests): the five situations on real Task 1 records from Runs 4, 8, 9 and 11,
each failure class separately, the default-policy withholds, identity gating, the full eligibility matrix, conflict
arbitration, injection resistance, tier breakdown, and guards (no network or sleep, no importer, no Cohort 6 issuer).
