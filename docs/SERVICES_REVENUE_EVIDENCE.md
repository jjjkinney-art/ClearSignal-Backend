# Source-bound Services revenue evidence

## Problem and behavior

The signed-in Apple evidence question verified on backend `64c6143` correctly
returned insufficient claim evidence. It retrieved consolidated SEC facts but
had no Services-specific extraction path. Filing metadata and company-wide
revenue cannot establish Services revenue, growth, or gross margin.

This change preserves bounded HTML table cells during public-document ingestion
and adds an Apple Services revenue producer. Services revenue/growth/thesis
questions request up to two recent periodic SEC filings through the existing
issuer-KPI task and evidence-collection deadline. A supported table yields:

- Reported Services net sales for an explicitly headed three-month period and
  the prior-year three-month period, with currency units preserved.
- Reported year-over-year change only when the table explicitly supplies a
  `Change` column consistent with those reported amounts.
- Producer-bound claims with the filing URL, SHA-256 content hash, table number,
  bounded Services row quotation, period end, duration and Services scope.

Only admitted SEC claims enter `verified_sec_facts`. The source-answer gate
renders dated evidence references and explains that those observations do not
by themselves establish future growth, gross margin or an invalidating risk.

## Coverage and boundaries

Initial issuer coverage is Apple, SEC CIK 320193, using its USD quarterly
net-sales layouts. This is not generic segment coverage across all issuers.
Annual-only tables, ambiguous units/headers, nested or incomplete tables,
cost-of-sales rows, forecasts and conflicting disclosures remain excluded.
Margins are not inferred from consolidated profit or an adjacent percentage
table without its own period headers. No reported percentage is manufactured
from the difference between the two revenue amounts.

The generic issuer-KPI route remains available for its existing metric families.
Point-in-time analyses continue to disable live issuer-document retrieval.
This change adds no research-memory writes, backfill, monitoring, notification
delivery or shared-ticker route permissions.

## Validation

The full original Apple 10-Q filed 2025-08-01 was fetched and parsed locally.
Its quarterly Services net sales of $27,423 million and $24,213 million and its
explicitly reported 13% change were extracted separately from year-to-date
amounts. The normalized financial-table fixture retains original visible cells,
row order and period headers; it is historical regression data, not current data.

Tests cover real table extraction, issuer identity, document provenance,
quarter/year-to-date separation, missing and reordered period headers, units,
conflicting disclosures, inconsistent growth columns, admission, preserved
claim anchors, request scope, document budgets and retrieval failures. Existing
source-answer, public-document, KPI, SEC-provider, routing, comparison and
research-memory regressions are required before merge.

## Post-deployment check

Run a new private AAPL investigation in Intelligence Mode:

> What is the strongest current public evidence for Apple's services-growth
> thesis, which operating risk could invalidate it, and what remains unverified?

Expect dated Services observations with inspectable references when a supported
filing arrives within the evidence deadline. Otherwise retain the explicit
insufficient-evidence answer. Do not require the historical fixture's numbers
in a current response. Confirm saved messages, History and Research Trail retain
the same emitted answer. Broader segment/margin extraction and analysis-quality
benchmarking remain separate roadmap work.

## Services source-response boundary

Services evidence questions return a bounded evidence view across the whole
`investment_thesis` payload. Generated narratives, signals, thresholds and
model-extracted quantitative claims are withheld, including nested compressed
theses. Headline and conclusion reflect the source gate. Only document-bound
Services amounts/growth from selected admitted evidence enter quantitative
claims. Pipeline confidence diagnostics are preserved; they are not a
probability that a Services claim or forecast is correct.

The boundary runs before legacy persistence and again at serialization after
comparison processing. Account-owned snapshots therefore store the same
restricted thesis that was emitted. Existing records are not rewritten.

The October 5 live run saved correctly but returned no Services-specific
observations. Deployment is confirmed, while live extraction acceptance remains
open. The synthesis log alone does not establish why retrieval failed: inspect
the earlier issuer KPI filing discovery/document extraction lines for that run
before changing network budgets or relaxing the evidence gate.
