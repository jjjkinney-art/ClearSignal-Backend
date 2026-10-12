# Concept-bound metric labels and signed operating cash flow

Generic labels previously displayed `NetIncomeLoss` and `ProfitLoss` as the same
net-income measure. New outputs distinguish net income attributable to the parent
from net income including noncontrolling interests. `scope=consolidated` still
means the reporting entity/context; a separate `income_attribution` field carries
the ownership distinction. Parent-attributable income is not parent-only accounts.
Figures, concept selection, units, periods, source references and original source
labels are preserved. Existing saved snapshots are not rewritten.

The definitions and worked examples were supplied by the coordinator's independent
taxonomy review:

- [FASB 2025 documentation labels](https://xbrl.fasb.org/us-gaap/2025/elts/us-gaap-doc-2025.xml):
  `NetIncomeLoss` is after-tax profit/loss attributable to the parent; `ProfitLoss`
  includes the noncontrolling portion.
- [FASB comprehensive-income example 1a](https://xbrl.fasb.org/impdocs/OCI_TIG/othercompincome.htm)
  reconciles the consolidated result, noncontrolling interest and parent result.
- [FASB revenue examples 10–12](https://xbrl.fasb.org/impdocs/Rev2_TIG/Revenue.htm)
  and [SEC-filed concept definitions](https://www.sec.gov/Archives/edgar/data/1065280/000106528024000030/R74.htm)
  illustrate why broad `Revenues` is not equivalent to customer-contract revenue
  or an issuer-specific total that includes other income.
- [XBRL US attribution guidance](https://xbrl.us/guidance/specific-non-controlling-interest-elements/)
  distinguishes these income concepts even when a filer has no noncontrolling interest.

`Revenues` therefore displays as **revenue (as reported)**. It is not globally
renamed to XOM's "total revenues and other income." Customer-contract revenue
excluding assessed taxes and revenue net of interest expense retain distinct
labels. Original source labels remain on the bound claims/document references;
the current producer does not carry a separately verified issuer presentation
caption, so summaries do not guess one from a ticker or arbitrary label text.
The archived audit excerpts omit exact concept/context metadata; they cannot
establish an archived XBRL tag by themselves.

For two negative operating-cash-flow amounts, the comparison describes increased,
decreased or unchanged **cash used**, retaining signed current/prior amounts.
For a sign crossing or a move to zero, it states the cash-provided/cash-used
transition without calling it percentage growth. A zero prior amount remains
withheld under the existing comparison gate. No economic-performance inference
is added. Bank cash flow remains context-only when justified by a bound
net-interest-revenue comparison.

Frozen regression values reproduce the supplied ACHC/XOM/JPM audit arithmetic,
but use authored filing identities; they are not new primary-source captures.
Tests cover attribution, preserved original labels and amounts, broad/narrow
revenue distinction, negative cash flow, zero/sign crossings, and rejection of
tampered attribution or mixed concepts. Existing issuer/period/reference and
inline-filing binding checks continue to run. No benchmark membership, reserved
holdouts, live-capture flags or evidence gates change.
