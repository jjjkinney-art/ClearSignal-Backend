# Selected-comparison evidence boundaries — 8 October 2026

## Confirmed preceding milestone

The owner reported the deployed post209 full source-inspection cohort passing
33/33. Backend health reported commit `138551afa52a`; frontend PR80 deployed.
Fresh signed-in AAPL, SPOT, ASML, TSM, NVO and AA source answers preserved issuer
scope, attributed disclosure citations and unassessed confidence. All six passed
reload/reopening with two saved messages and citations. An older saved Apple
source answer also displayed the new unassessed-confidence label.

Browser completion observations were AAPL 10.4s, SPOT 2.5s, TSM 10.7s, NVO 8.4s
and AA 9.3s. ASML completed, but its timing was not captured precisely following
a selector timeout. These include observation overhead; they are neither server
timings nor p50/p95 measurements. Source-answer acceptance does not close the
broader launch gates.

## Defects reproduced in the next memory gate

Six regression cases failed before repair. The comparison adapter replaced an
evidence item's issuer scope with the selected record's ticker. Explicit MSFT
or missing issuer scope could consequently support an AAPL strengthening result
when words and dates matched. The adapter also ignored the production
`freshness_status` and `availability_status` fields, and the comparison gate
accepted stale evidence as supporting a current directional change.

An additional admission-boundary check exposed citation renumbering: after E1
was blocked, the surviving E2 could be presented as E1 in a comparison.

## Repair and limits

- Preserve explicit producer issuer scope or a single consistent issuer from
  structured claims. Missing, mixed or contradictory scope cannot be supplied
  by the selected thesis.
- Carry canonical reference IDs and computed admission freshness into the
  comparison. Match the exact title, source, publication timestamp and public
  URL; an absent or mismatched reference cannot support a change.
- Block stale and unknown freshness from directional comparison. Stale records
  remain inspectable supporting context under the existing admission policy.
- Preserve the existing fail-closed correction, original historical conclusion,
  account-owned persistence and disabled external delivery.

535 local regression checks pass, including the current related-evidence
positive path, issuer mismatches, structured claim scope, computed staleness,
canonical citation survival, conflict/unavailable/superseded states, memory and
notice regressions, ordinary analysis, and source-answer coverage regressions.

This may turn previously accepted unscoped/unknown evidence into a safe gap.
Unscoped provider records need explicit producer binding before they can qualify.
Lexical material relevance and generated direction remain limited comparison
mechanisms; this repair does not prove semantic directional correctness or a
natural-evidence live positive comparison. Synthetic unit evidence is used only
in tests, never inserted into production research or notices.

## Deployment acceptance

After CI, merge and deployment, confirm the deployed commit. Run the full
33-company source-inspection check again. Reopen a real historical investigation
and explicitly select it for a fresh comparison; verify the displayed audit and
saved citations retain the same source records and issuer. Old, stale, unrelated,
unscoped or conflicting evidence must not create a supported direction or an
eligible notice. A live positive result requires a real owner-selected record
and genuinely newer related public evidence; do not alter dates or create
synthetic production evidence to make the gate pass. Confirm ordinary analysis,
fresh source answers and saved reopening still work. Mobile/accessibility and
the larger numerical accuracy benchmark remain separate roadmap gates.
