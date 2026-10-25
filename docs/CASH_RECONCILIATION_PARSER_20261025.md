# Complete indirect-cash parser contract — 25 October 2026

## Implemented boundary

`app/providers/sec_cash_reconciliation.py` parses a complete annual cash-flow
table into a bounded XML capsule and reconstructs its displayed indirect-cash
reconciliation. It preserves both the signed taxonomy value and the printed
cash contribution of each fact. Only displayed contributions are summed.

This is the parser/reconstruction layer. It is deliberately not connected to
ordinary ingestion, `RetrievedEvidence`, final source admission, citations or
`/ask`; no existing answer changes. Each result explicitly returns
`admitted=false`, `source_binding_established=false`,
`semantic_component_nonoverlap_verified=false` and `launch_ready=false`.
Source-bound answer integration remains a separate next step.

## Source and arithmetic requirements

- Complete operating and investing section boundaries, a calendar-year heading
  and an unambiguous two- or three-column year header are required. Every
  component has all period columns. The first numeric row is standard GAAP net
  income; the last is standard GAAP operating cash flow. Intermediate anchors,
  repeated concepts, unknown untagged rows and unbound numeric cells are gaps.
- Facts require exact SEC CIK, consolidated duration contexts, distinct IDs,
  compatible row concepts, unit/currency, supported literal/transform/scale,
  visible year alignment and identical period/context columns. Periods must be
  adjacent calendar years, newest first. No quarterly annualization is performed.
- The initial currency set is USD/EUR/GBP, supplied explicitly with no fallback
  or conversion. Generic synthetic tables exercise all three; the retained real
  filing exercises USD only. Other currencies and noncalendar/interim layouts
  remain unsupported by this version.
- Source cells retain parentheses and their closing cells. A negative taxonomy
  value is not automatically a cash deduction, and a positive taxonomy value
  is not automatically a cash inflow. All components must sum exactly to each
  reported total; component changes must sum exactly to the total change. There
  is no residual plug, normalization or sustainability signal.
- The separate parser recognizes the reviewed fixed-zero dash transform and
  source-labelled issuer-extension contributions within the complete table.
  These are not new standalone financial-concept permissions. The existing
  conservative Inline XBRL, segment and impairment parsers are unchanged.
- Hidden/active content, nested or competing cash tables, namespace rebinding,
  duplicate IDs, unsupported continuations/nil facts, dimensions and ambiguous
  signs/layouts fail closed. XML size, depth, node, namespace, row, cell and
  capsule limits apply; entity/doctype declarations are rejected.

No ticker, issuer, amount, year or fixed fifteen-component allowlist is used.
The initial annual-heading and two recognized nonnumeric subheading forms are
bounded grammar support, not universal filing coverage.

## Replay and checks

`scripts/replay_retained_cash_reconciliation.py` verifies the retained filing's
body hash/length against its receipt and pinned values, then executes the new
parser and reconstructs its capsule with external sockets denied. It compares
every numeric row, fact ID, period, displayed contribution and signed taxonomy
value against the committed PR343 source map. All sixteen numeric rows match:
fifteen components plus the operating-cash total in each of three columns.

`CASH_RECONCILIATION_PARSER_REPLAY_20261025.json` retains the complete 112,532
character XML capsule and the reconstructed values. Annual totals remain
-$9.137m, -$53.426m and +$45.389m for 2025, 2024 and 2023, respectively, with
zero residual in every column. The current/prior component changes sum to
$44.289m. No answer-generation path, model, external request or old execution
ledger runs. Receipt consistency does not independently authenticate origin.

The 56 new synthetic cases exercise generic row labels and different row
sets, three currencies, positive/negative/zero cash, losses, scale consistency,
opposing display/taxonomy signs, extension/zero rows, omitted or ambiguous rows,
duplicate facts, missing resources, period/header/CIK mismatches, hidden content,
namespace/format/resource bounds and reparsing after capsule/hash modification.
The focused and adjacent suites pass 377 tests. The retained replay repeats
byte-for-byte with SHA-256
`a54a93981659fc7a27573594f7324a54da291801c82f80f9fa8299f0fe0255bb`.
Full collection finds 19,129 tests with zero errors. Full repository regression
remains for PR CI; none of these checks establishes independent research acceptance.

## Source binding still required

A capsule hash establishes internal consistency, not identity with the original
document. A synthetic test removes two offsetting rows and rehashes the capsule:
the altered statement still reconciles. That test intentionally preserves
`source_binding_established=false` and `admitted=false`. A valid-looking source
hash also cannot grant source authority. Exact arithmetic must not be treated as
proof of completeness, original-source authenticity or semantic nonoverlap.

The next layer must bind the capsule to the source document, verify source
metadata/availability/periods and independently reconstruct the final claim. It
must retain all source rows and caveats, reject substitutions, and distinguish
statement contributions from independently established causal drivers. It must
not explain later interim cash movements with annual evidence or count a
noncash impairment adjustment as another loss or new cash payment. Only after
that binding and citation path is verified should an ordinary answer admit a
quantified bridge.

No current ASML/ACHC cash-table rerun or complete-answer assessment follows from
this exposed retained probe. Broader economic reasoning, sustainable earnings
and cash, valuation, signed-in behavior and independent usefulness across
company sizes remain open. The rough 55% planning judgment is unchanged, not a
measured completion rate. All twelve live approvals remain consumed; no new
capture, provider/model call, spending, benchmark/holdout access or activation.
