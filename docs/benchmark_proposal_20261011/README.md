# Representative 100-issuer proposal and holdout reservation

**Current status:** the approved JOUT-to-NPK substitution completes version 2
offline setup. See [finalized setup](reconciliation/FINALIZED_SETUP.md). The original proposal and
99-company assessment below remain historical evidence; execution is disabled.

Status: **classification policies approved and applied; evidence-gated setup review**.
[Current readiness and exact remaining blockers](reconciliation/SETUP_READINESS.md)
are authoritative over earlier review snapshots.
This is a planning artifact, not an expanded canonical registry, verified
market-cap dataset or answer-quality result.
No providers were used to generate ClearSignal answers. No paid captures ran.
The canonical `validation/issuer_registry.v1.json` remains unchanged. The approved
policy is versioned separately; no 100-company registry or execution plan has
been activated.

The user approved 100 issuers, at least 30 large, 30 mid and 30 small/micro with
10 additional slots, at least 10 sectors, at least 20 distinct complexity tags,
and 20 of the 100 reserved before further answer-quality tuning.

## Concrete allocation

[CANDIDATES.md](CANDIDATES.md) lists all 100 names with per-row observed-cap links
and actual source dates. [candidate_plan.json](candidate_plan.json) records the
same proposal and open verification fields. The allocation is 30/30/30 plus 10;
under the approved boundaries below the extra ten are large, producing 40/30/30.
They retain AA/DOCU from the historical baseline and add international source
complexity. All 18 prior registry issuers remain development candidates.

The proposed sector distribution spans 11 sectors. These are planning labels,
not independently verified sector classifications. The existing 18-issuer
registry contributes 29 distinct recorded complexity tags; those tags are
retained as explicit verification targets, not newly adjudicated business facts.
Confirm company-specific tags from filings rather than assigning 20 tags to every
issuer or treating tag counts as successful answer coverage.

Research targets include US and foreign issuers associated with the Netherlands,
Switzerland, Taiwan, Germany, Japan, Canada, Australia, the UK and Norway. Verify
domicile, listing/security identity, reporting basis and source availability per
issuer. Verify multiple fiscal calendars, including calendar-year and non-calendar
reporting; ADR/share-class mapping and fiscal-period comparability remain explicit
checks. Neither prospective geographic diversity nor existing registry accounting
labels establish verified source support.

## Approved classification policy

[FINRA's market-cap explainer](https://www.finra.org/investors/insights/market-cap)
describes mid-cap values between $2bn and $10bn and large-cap values starting at
$10bn, with mega-cap above that range. The user approved these combined buckets:

- large/mega: USD market cap >= $10bn;
- mid: >= $2bn and < $10bn;
- small/micro: positive market cap < $2bn.

The user approved the equality rules, USD total-company equity basis, October 9,
2026 measurement date, and provisional use of the collected secondary figures.
[The versioned policy](../../validation/benchmark_classification_policy.v1.json)
records that approval. Count each company once across share classes and ADRs;
resolve conflicting figures and identity/share-class checks before admission.
Do not mechanically apply the US listing's share count to foreign total equity.

Every candidate has a market-cap summary observation from its linked public
StockAnalysis page, retrieved October 11, 2026. These are secondary aggregator
observations, not audited financial truth or independently verified values.
The refreshed 100 summaries explicitly state October 9, 2026. The earlier
observations (82 dated October 9 and 18 older) are preserved unchanged in
`prior_observations.json`; refreshed values are not backdated into that record.
Per-read UTC retrieval timestamps, requested/resolved URLs, short excerpts and
excerpt hashes are in `refreshed_source_observations.json`. Each candidate
references its observation ID. Three redirect reads reuse canonical excerpts.
Hashes cover excerpts only, not complete pages; mutable-page values remain
secondary observations. Retrieval time and source observation date are separate
fields. Values are rounded, transcribed from the summary statement; historical
table entries on the same page may differ. The subsequent same-snapshot review
found 55 matching displayed values and 45 unresolved differences. For
example, the UTMD page displayed $237.32m in its summary versus $237.30m in the
October 9 historical row. The NVS summary displayed $272.48bn versus $273.23bn in
its same-date historical row. Neither discrepancy crosses the approved tier
boundary, but neither is silently resolved as exact market value.

Examples of dated observed values: [ENS $6.48bn, October 9](https://stockanalysis.com/stocks/ens/market-cap/),
[UTMD $237.32m, October 9](https://stockanalysis.com/stocks/utmd/market-cap/), and
[NVS $272.48bn, October 9](https://stockanalysis.com/stocks/nvs/market-cap/).
The source supplies the observation; the provisional bucket is our conditional
classification under the approved policy, pending company admission checks.

The observations change the old baseline labels: AA/DOCU would be large and
ACHC/ACMR/MAN mid under this approved policy. This proposal records the old
registry entries for comparison; it never rewrites them. The refreshed NWN summary moved from $1.99bn dated October 6 to $2.01bn dated
October 9, crossing the approved cutoff. NWN is therefore recorded as a mid-cap
removed development candidate, replaced by RGR at an observed $691.22m dated
October 9. This preserves all 18 old registry issuers and all 20 holdouts.
Reconcile near-boundary names such as GRC, confirm active listing and issuer
identity, and resolve corporate actions before freezing an accepted new version.

## Current ticker corrections

Primary sources confirm the development-pool identity updates; historical aliases
are preserved and the 20 reserved holdouts are unchanged:

- [ASGN to Everforth / EFOR, April 24, 2026](https://www.sec.gov/Archives/edgar/data/890564/000089056426000025/asgn-20260424.htm).
- [IAC to People Incorporated / PPLI, June 4, 2026](https://ir.people-incorporated.com/news-releases/news-release-details/iac-now-people-incorporated-new-ticker-symbol).
- [Gannett / GCI to USA TODAY Co. / TDAY, November 18, 2025](https://www.usatodayco.com/pr/gannett-rebrands-to-usa-today-co/), corroborated by its [current investor-relations page](https://investors.usatodayco.com/).

The replacement [RGR issuer page](https://ruger.com/corporate/index.html?r=y)
confirms NYSE ticker RGR. Its size classification is still conditional on the
approved cutoff and secondary cap observation. These narrow identity checks do
not establish all candidates' legal identity or broader source coverage.

## Reserved evaluation-only pool

Twenty names are reserved within the 100; 80 remain the development pool. The
proposed holdout distribution is six large, seven mid and seven small/micro.
See `reserved_holdout` and the reservation/amendment record in the JSON files.
**Do not generate answer-quality fixtures or tune extraction/composition against
these 20 names before evaluation.** Identity/classification metadata research is
permitted and is not itself a ClearSignal answer-quality evaluation.

[exposure_audit.json](exposure_audit.json) records the audited commit identities,
aliases, empty results for reserved candidates, and positive matches for screened
alternatives. The initial screen searched all readable tracked files at HEAD,
including app company knowledge, tests, fixtures, docs and capture artifacts;
it also searched added/deleted text across all reachable commits: 690 backend
and 233 frontend commits. Both checkouts reported non-shallow history. Tickers
used case-sensitive token matching and supplied company-name aliases used
case-insensitive token matching. Additional historical ticker/alias checks are
recorded separately where needed.

This means **no match in the available audited repository history using the
recorded aliases**, not universally unseen. Private chats, untracked captures,
missing remote refs, prior inaccessible deployments and unknown aliases cannot
be excluded. The user reports not believing these names were previously used but cannot be
certain. Prior exposure outside the audited repositories therefore remains
**unknown**, not verified unseen. This qualification does not change the 20
reserved names or authorize tuning against them.
Binary files and embedded archives were not unpacked or semantically inspected;
`git --text` searches raw patch text only.
Broad financial-page metadata discovery did not execute or grade these issuers'
ClearSignal answers. A no-match result does not verify active listing, legal
identity or financial facts.

## Evaluation plan and remaining gates

Use the six existing question families unchanged: thesis, decision thresholds,
structural risks, comparable financial trends, operating metrics and recent
developments. This produces 600 planned cases: 480 development and 120 reserved
evaluation cases. At the existing maximum 20 cases per batch this is 30 batches.
This is a capacity plan, not permission to incur provider costs or run captures.

Separately exercise legal-name and ticker resolution; signed-in personalization
against selected preferences and saved research; saved-thesis comparison; readable
save/reopen; latency and freshness. Do not count this offline plan as completion
of those checks or as evidence of equal quality across issuers.

Keep the existing gates: at least 90% useful cited answers in each tier, numerical
accuracy >=98%, correct source binding >=95%, and zero fabricated sources,
issuer/period contamination, account leakage or issuer-level stop-ship failures.
Preserve the separate existing mid/small-cap factual suite unchanged: it requires
>=95% numerical accuracy and 100% claim/source binding
(`validation/cap_tier_factual_benchmark.py`, lines 22–23). These are independent
scoped gates, not a replacement or consolidation into a new threshold policy;
the overall 95% source-binding gate never relaxes that suite's 100% requirement.
Require primary-document adjudication and independent blind usefulness reviews.
Report gaps and failures by issuer and question family; do not silently replace
failing holdout issuers. Metadata corrections must preserve an amendment trail.

Policy approval is complete. External prior exposure remains qualified as unknown;
no further absolute attestation is required by this plan. Remaining data work is
company admission reconciliation and primary identity/sector/fiscal/jurisdiction
verification, followed by independently adjudicated captures only when separately
authorized.
The 100-company quality benchmark remains unexecuted and unaccepted.

## Admission reconciliation

[The cap review](reconciliation/cap_value_review.json) compares all 100 summaries
with their October 9 historical rows. [Its findings](reconciliation/supportingbrief.md)
list 26 conflicts and 19 differences conditionally compatible with an unconfirmed
rounding convention. All 45 differences remain unexplained. The user approved historical-row precedence
for exactly 19; the other 26 retain unselected exact values. The subsequently approved
classification-only rule evaluates their size tiers using documented dated shares
and October 9 prices; matching publisher tiers alone is insufficient. Nine affected names are reserved holdouts, which remain in the reservation.
Public methodology checks did not establish the discrepancy causes. The approved
19-name source rule selects a value without claiming source-confirmed rounding.

[The continued evidence review](reconciliation/FOLLOWUP_DECISION.md) investigates
all 45 differences and separates tier evidence from exact value reconciliation.
No summary/history difference changes a size tier. Primary share-count products
explain several material discrepancies, and a separate GRC check corroborates its
small-cap tier. Historical-row source precedence is now approved and applied for exactly
19 tiny differences; see [the approval record](reconciliation/approved_historical_precedence.json). The other 26 have now received classification-only adjudication: 25 have
supported tier evidence, while JOUT remains excluded for its unquoted Class B
valuation gap. These decisions do not certify any exact value. No general tolerance or new
requirement to independently audit every daily share count has been introduced.

Primary identity and security-class reviews are stored alongside that review.
Current SEC ticker mappings identify registrants; they do not independently establish
all share classes, October 9 continuity, or the publisher's company-total aggregation.
The approved provisional source policy does not require a new independent audit of
every price and share count. Known class/ADR gaps and source conflicts still need
evidence before admission. Corporate-action evidence, confirmed class distinctions,
and unresolved facts are kept separately so a current ticker lookup cannot silently
stand in for historical company identity.

The candidate JSON records per-company admission status, and
[the canonical setup decision](canonical_setup_decision.json) records what was
staged and why the historical registry remains unchanged. Current SEC mappings
are observations, not a blanket certification of every listing field; issuer
sources can expose stale mapping details that must be reconciled separately.
An approved policy and
100 proposed names are insufficient to activate a valid 100-company benchmark.
No issuer with an unresolved admission gate is admitted, no holdout is silently replaced, and no ClearSignal
answer capture, paid provider call, or live acceptance test ran in this review.

## Offline validation

The offline suites cover candidate/source policy, admission evidence and holdouts,
existing registry/fixture integration, numerical accuracy and citation binding:

```sh
PYTHONPATH=. python -m pytest -q --noconftest tests/test_benchmark_candidate_plan.py tests/test_benchmark_admission_readiness.py tests/test_benchmark_candidate_admission_builder.py tests/test_benchmark_registry.py tests/test_factual_citation_grading.py tests/test_cap_tier_factual_benchmark.py
```

Validation uses isolated Python 3.11.17 with application conftest excluded. The
unused `asyncio_mode` warning reflects omitted application plugins. See the current
readiness note for the final test count. The historical registry's strict coverage
audit still fails as expected: 18 issuers, 54 fixtures and eight sectors. Its
integrity passes; it is not an accepted 100-company cohort. Neither structural
checks nor existing fixture tests are live quality acceptance or full application
regression. No new execution manifest or answer-capture results are fabricated.
