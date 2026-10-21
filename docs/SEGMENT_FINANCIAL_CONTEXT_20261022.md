# Source-bound annual segment financial context

The ordinary broad-thesis disclosure path can now retain explicitly dimensioned
annual external sales and operating profit/loss from the same annual document
it already downloads. This adds substantive segment results to the retained
answer after PR325's source inspection. It does not complete the broad-company
research-quality gate.

## Behavior and source contract

A separate bounded XML callback target shares the existing Inline XBRL scalar,
namespace, identifier, resource and depth checks. The consolidated parser is
unchanged. A segment observation must resolve the issuer CIK, annual duration,
USD unit definition, numeric transformation, scale and sign, plus exactly the
supported consolidation and business-segment axes. Custom member identifiers are
preserved with their namespaces; their names are never interpreted as labels.

Visible table column spans establish the segment display labels and tie revenue
and operating results to the same member, column and annual period. Hidden/nested
tables, row spans, conflicting observations, late duplicate identifiers,
incomplete segments and malformed XML fail closed. The latest period block in
a table cannot silently fall back to an older block when incomplete. Displayed
currency/signs must agree with the source observation. Source-backed integer USD
amounts expand the explicit thousands scale; no binary floating-point arithmetic
or source-symbol currency guess is used.

The proof retains the table number, expanded header layout, period label, metric
rows/cells, fact/context/unit IDs, namespace-resolved dimensions and scalar
observations. Revenue and operating-result row references and separate complete
sentences for the operating-profit definition and corporate-cost allocation
survive final claim composition. These row quotes are normalized visible table
rows, with original cell/fact identities retained in the proof; they are not raw
HTML offset quotes. The corporate allocation caveat appears in the answer itself.

`RetrievedEvidence.segment_disclosures` is an additive field separate from
consolidated verified claims and historical order-context quotes. Its empty
serialization default is covered explicitly. Final binding reconstructs amounts,
periods, scopes, column labels, display literals, accounting caveats and summary
before accepting a segment-context claim. It rejects metadata/summary tampering,
wrong issuer/document/period and stale/conflicting/superseded evidence. The
financial foundation admits at most one such item, after the existing disclosures;
existing business/risk/competition/backlog caps and business-coverage rules remain.

The annual request opts into parsing with the already resolved issuer CIK.
Predecessor annuals remain risk-only and do not receive this extraction. There
is no additional source request, route, schema migration, dependency or rollout
flag. Download limits and authorization/quota policies are unchanged.

## Bounded support and deliberate remaining gaps

This first contract supports visible USD tables headed “(in thousands)”, explicit
December 31 annual period labels, “External net sales” and “Operating profit
(loss)” rows, two to eight consistently bound segment columns and a Total header.
It requires the supported explicit operating-profit definition and corporate
allocation sentence in the same immediately preceding substantive paragraph. Other currencies, fiscal-year ends, row/column structures,
axis combinations, typed dimensions, transformations or definitions remain gaps.
These restrictions are shared source-format rules; there is no ticker, issuer
namespace or segment-name allowlist. Synthetic tests use different invented
issuers/segment labels with unrelated member IDs.

Totals are not normalized or reconciled by this contract. The answer explicitly
states this and does not claim complete segment coverage or standalone segment
economics. It derives no exposure share, margin, growth rate, pricing/volume/cost
attribution, ranking of risks, competitive advantage, valuation or future result.
Known allocation/definition caveats are retained; independent review of source
entailment and material footnotes remains necessary.

## Retained application replay

Base is merged PR325, `6b9991429732518b4499ccb1c72fc13328341d5a`.
`SEGMENT_FINANCIAL_CONTEXT_REPLAY_20261022.json` compares the committed baseline
disclosure producer with the candidate, sharing the current financial producer,
admission and final source-answer gate. Both run the real bounded document
ingestion path. Discovery, DNS and HTTP responses are injected from retained
bodies; a socket audit hook denies external network activity. This is not a live
provider run or signed-in/browser acceptance.

The PR292 retained filing body remains 1,404,517 bytes with SHA-256
`8d9ea0ecbc1619994be67fe36900878ae6c825ba99047373ad749f9caedab8a1`.
The PR314 retained facts body remains SHA-256
`0f512e8670882f4d201d24252e31ab457f512be1aa6ac9b7243d3b8ec820e19f`.
Both receipts and all 19 facts-archive inventory hashes are checked. Source-origin
authenticity and present availability are not independently established.

The retained replay adds one claim containing these annual results for
2025-01-01 through 2025-12-31, with namespace-resolved USD units and scale:

| Source-spelled segment | External net sales, USD | Operating profit/(loss), USD |
| --- | ---: | ---: |
| Housewares / Small Appliance | 95,604,000 | (9,292,000) |
| Defense | 405,937,000 | 58,383,000 |
| Safety | 1,983,000 | (8,850,000) |

The operating-profit definition and allocation of corporate costs/assets to
Housewares/Small Appliance are included. Source table number 28 is the same
opening-table index 27 inspected in PR325; this contract numbers tables from one.
All ten preceding claims and their citation IDs are exactly preserved. Business
coverage, inferences and unanswered parts are unchanged; the candidate has eleven
claims and remains partial. The canonical question is the same exposed broad
thesis question, not a new benchmark or a narrower replacement for it.

The replay uses one retained facts substitution and two retained document
substitutions (one per version), with zero external requests/model calls. A
second final-source replay matches the committed result canonically. Original
captures, receipts, completed run ledgers and exposed baselines are unchanged.

```bash
python scripts/replay_retained_segment_financials.py CAPTURE_DIR FACTS_ZIP NEW_OUTPUT.json
```

The script refuses existing outputs. It must run offline with the existing
retained files; it has no capture/approval/execution-budget switch.

## Validation and acceptance boundaries

Fifty-five new tests cover synthetic label/member independence, namespace/unit/
scale/sign binding, period/context/issuer contamination, malformed/hidden/nested
source handling, duplicate IDs/conflicts, incomplete latest periods, unsupported
segments, final metadata tampering, same-download ingestion and ordinary
retrieval through final answer composition. The schema exact-key/default contract
is updated for the intentional additive field.

The new and adjacent suites pass 255 tests; business/financial-foundation/citation
regressions pass another 407. All five local CI groups pass (83/87/221/178/195).
Pinned Python 3.11.9 imports the application with 136 routes. Collection is clean;
counts, source/log hashes and replay comparison are recorded in
`SEGMENT_FINANCIAL_CONTEXT_VERIFICATION_20261022.json`. External sockets are denied
for local tests/replay/import checks; existing dependency deprecation warnings
are neither changed nor suppressed. Full hosted isolated-per-file CI is required
before merge; local groups are not a substitute.

This is an unblinded engineering implementation/replay. It supplies actual dated
segment results to one exposed answer; no independent usefulness score or company
pass rate follows. Products/services, causal revenue drivers, counter-evidence,
valuation relevance and broader sector/source support remain work. Reuse the
existing 100-company development/holdout benchmark and independent review gate;
no holdout outputs are inspected here. All twelve historical live approvals stay
consumed. No new financial-provider/model calls, spending, capture authority or
scenario activation is authorized by this change.
