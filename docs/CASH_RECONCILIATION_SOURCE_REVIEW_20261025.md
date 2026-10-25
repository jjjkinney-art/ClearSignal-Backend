# Retained cash-reconciliation source review — 25 October 2026

## Result and consequence

The retained annual statement supplies a complete printed reconciliation of net
earnings to operating cash flow. The missing quantified bridge in the current
answer is not established source absence. Fifteen displayed components reconcile
exactly in each of the three annual columns. This source review changes no
production answer or admission rule.

| Annual period | Sum of printed components | Reported operating cash flow | Residual |
| --- | ---: | ---: | ---: |
| 2025 | -$9.137m | -$9.137m | $0 |
| 2024 | -$53.426m | -$53.426m | $0 |
| 2023 | $45.389m | $45.389m | $0 |

For 2025, the printed net earnings of $33.084m plus the next nine reconciliation
adjustments of $16.642m, less the five displayed operating-asset/liability
contributions of $58.863m, equal the $9.137m cash outflow. These groups describe
the reviewed statement rows; they are not independently normalized earnings or
proof that every adjustment is noncash or recurring.

The 2025 versus 2024 improvement is $44.289m. The inventory contribution changes
from -$87.579m to -$29.028m, a $58.551m reduction in cash drain, rather than a
positive inventory cash inflow. Offsets include $8.376m lower net earnings,
$9.625m greater receivables cash drain and a $10.104m adverse change in the income
taxes payable contribution. The source map retains all fifteen component changes;
their sum equals the reported cash-flow change. This is statement arithmetic,
not independently established causality or a forecast of reversal/persistence.

## Sign distinction that a shared contract must preserve

The signed taxonomy value is not automatically the displayed contribution to the
indirect cash-flow reconciliation. Examples in 2025:

| Source row | Signed Inline XBRL value | Printed cash contribution |
| --- | ---: | ---: |
| Accounts receivable, net | $22.902m | -$22.902m |
| Inventories | $29.028m | -$29.028m |
| (Gain) loss on disposal of property, plant and equipment | -$0.013m | $0.013m |
| Gain on sale of subsidiary | $0.253m | -$0.253m |
| Other reconciliation adjustment | -$0.230m | $0.230m |

Naively summing signed taxonomy values gives **+$94.799m** for 2025, which is
$103.936m away from reported operating cash flow. The existing answer does not
perform that incorrect sum; this review identifies a hazard for the next
implementation. Neither multiplying every working-capital concept by -1 nor
guessing from labels supplies a general cash-flow contract.

The table also contains two issuer-extension concepts and dash zero literals.
Those remain diagnostic observations. The conservative production Inline XBRL
parser is unchanged; unsupported extension/zero formats have not been admitted.

## Cross-company retained-source check

The script also checks the three retained company-facts bodies against their
receipts and pinned hashes, using 15 October as the historical diagnostic cutoff.
This is an inventory, not selection/admission of new evidence or a current rerun.

| Issuer | Latest annual CFO candidate in retained facts | Complete cash table available in this review |
| --- | --- | --- |
| NPK | 2025, USD, -$9.137m | Yes |
| ASML | 2025, EUR 12,658.5m | No |
| ACHC | 2025, USD, $131.898m | No |

No currency conversion is performed. Source units are preserved in the
machine-readable report. The selected component
concepts differ: ASML lacks four and ACHC three of the standard concepts present
in the reviewed NPK component set. Absence does not mean a zero amount, a missing
economic activity or absence of an equivalent concept. Presence does not prove
same-statement completeness or compatible contribution signs. The two NPK
extension concepts further rule out treating a standard-concept presence count
as a complete reconciliation. No cross-company bridge is qualified.

## Review artifact and verification

`scripts/inspect_retained_cash_reconciliation.py` reads only retained files with
external sockets denied. The filing body hash/length are pinned and match its
receipt. The PR314 facts archive verifies all nineteen inventory entries; all
three facts bodies match pinned hashes and receipt lengths. No ledger is opened
or executed. Operating rows retain visible cells, Inline XBRL attributes,
fact/context identifiers, context XML, periods and both sign interpretations.
`CASH_RECONCILIATION_SOURCE_MAP_20261025.json` retains all rows, three exact
reconciliations, complete component changes and the three-company inventories.

The source is annual cash-flow table 14 (one-based) in the retained NPK filing.
The serialized table hash identifies the inspected XML subtree; the original
body hash identifies the retained document. These are consistency checks, not
independent origin authentication. Review arithmetic is separate from a reusable
source qualification or factual/usefulness adjudication.

The standalone inspection reproduces byte-for-byte under the host Python and
the pinned Python 3.11.9 runtime. The JSON SHA-256 is
`f570c8faff02bec1feb0a2a476c4186615ed837f2a3b9bc92ef3f44d44360ff9`.
All three zero residuals, the complete component-change sum, both extension
concepts and source inventories are asserted. Script syntax and `git diff
--check` pass. No application code changes, so application suites were not
rerun locally for this source-review-only change.

## Next bounded implementation and remaining gates

Build a shared indirect-cash reconciliation contract that preserves complete
statement boundaries, column headings, actual cash-contribution signs, qualified
fact/context/unit identity and periods. Keep taxonomy values and display
contributions separate. Reject incomplete/ambiguous rows, unsupported formatting,
duplicate facts and unexplained residuals. Do not plug residuals, infer zeros,
double-count reconciliation adjustments as new cash payments or promote a
component change to a sustainability signal. Test generic synthetic issuers,
different row sets, signs, annual/interim periods, currencies and exceptions;
this observed fifteen-row layout must not become an issuer-specific allowlist.

Before final-answer admission, reconstruct the complete bridge independently of
producer metadata and preserve scoped source references. A qualified annual
bridge must not explain a later interim movement. Sustainable earnings/cash,
financial exposure, competitive economics and valuation still need assessment.
Existing conditional valuation arithmetic supplies none of the missing market
price/security basis or future assumptions, and remains off by default.

This is unblinded source review, not improved production answers, current
ASML/ACHC reruns, a frozen-question pass, independent usefulness or launch
acceptance. The rough 55% planning judgment remains unchanged; measured quality
pass rate remains null. All twelve live approvals remain consumed. No new
capture, provider/model calls, spending, benchmark/holdout access or activation.
