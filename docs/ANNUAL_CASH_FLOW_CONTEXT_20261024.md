# Matched annual operating cash-flow context — 24 October 2026

## Result

The retained answer now adds a management-attributed annual cash-use explanation
matched to same-document consolidated operating-cash-flow observations. In the
NPK probe, annual operating cash flow is **-$9.137m for 2025 versus -$53.426m for
2024**. Both are outflows. Management's complete working-capital/noncash-item
discussion is retained, including its prior-year context.

This explanation does not become a causal bridge for the later six-month cash-flow
increase. The original interim comparison and its `context_only` interpretation
remain unchanged. The new statement explains management's disclosed annual view;
it does not establish independently verified causality, persistence, sustainable
cash generation or a complete quantified reconciliation.

## Source and final binding

The existing bounded annual document fetch now also runs the existing conservative
Inline XBRL parser for the standard operating-cash-flow concept, retaining the
observations in a separate `PublicDocument.cash_flow_observations` field. No extra
document or provider request is added. Original inline-metric, segment-table and
impairment paths remain separate. Unsupported XML, transformations, entity/unit
identity, dimensions or ambiguity remain gaps under the existing parser.

`app/services/annual_cash_flow_context.py` reconstructs the complete Item 7/7A
window and requires matching current/prior comparison headings and the annual
liquidity comparison. A complete cash-use paragraph must end before investing
activities; current and prior management descriptions must both remain present.
It revalidates exactly two observations with the standard concept, matching GAAP
namespace, exact CIK, consolidated scope, USD unit, supported transformation/scale,
distinct fact/context identifiers and calendar-year dates. Each narrative cash-use
magnitude must equal the corresponding negative observation, and the stated
increase/decrease in cash used must agree with the signed amounts.

The initial grammar supports calendar-year annual **cash-use** comparisons with
the reviewed working-capital explanation form. Positive cash-generation, zero
flows, noncalendar fiscal years, different currencies and other narrative forms
are unsupported; they are not reinterpreted through this grammar. No ticker,
issuer, amount or year allowlist is used. The text/proof window stays within the
existing periodic-document and MD&A bounds; observation metadata is separately
capped. A new default-empty `cash_flow_disclosures` field carries this evidence.

The final binder repeats source-window, narrative, signed-amount and period
reconstruction, checks every structured context field, and validates the exact
summary, document reference, source metadata, availability/freshness and reporting
period. A separately scoped SEC reference permits up to 1,600 characters so the
complete 1,154-character observed paragraph need not lose prior-year or offsetting
context. Ordinary 300-character and existing policy/risk quote caps are unchanged.
Quoted noncash-item descriptions remain management attribution; they are not
new independently normalized measurements or cash payments.

The financial foundation appends at most one annual-context claim without
replacing its selected interim comparisons, recalculating a mixed-period ratio,
assigning a directional signal or clearing business/valuation gaps. Predecessor
sources remain excluded. Accounting policy, operating/investing/financing cash
flows and actual future cash generation remain distinct concepts.

## Verification

`scripts/replay_retained_annual_cash_flow_context.py` uses retained PR292 filing
and PR314 facts with external sockets denied and original receipt/hash/inventory
checks. Committed PR340 foundation/overview at
`40058ac6d95ecd65f9efb40d30203d73b39d30ff` forms the baseline; disabling only the
new cash-flow producer exactly reproduces the archived PR340 candidate.

`ANNUAL_CASH_FLOW_REPLAY_20261024.json` retains complete before/after answers,
source-answer results, references and full producer proof. E17 is added after the
sixteen prior claims. All sixteen claims and citation objects remain equal, as
do previous inferences, segment financials, coverage and unanswered parts. Every
complete claim statement appears once. The candidate grows from 2,208 to 2,460
words with new annual evidence; neither length nor claim count establishes quality.
The replay makes zero external requests and zero model calls and resumes no ledger.

Synthetic checks cover cash signs and movement direction, annual/interim and
current/prior period mismatches, missing/duplicate/malformed observations, entity,
currency, dimensions, scale, fact/context identifiers, namespace mismatch,
truncated prior-year explanation, section/hash/offset/context/summary/reference
tampering, scoped quote caps, existing single-fetch retrieval and final answer
behavior. Existing source, risk, segment, monitoring, document and inline-parser
regressions remain part of focused validation.

Final checks: 42 new synthetic cases; 874 focused tests passed; full collection
19,059 with zero errors; five CI groups passed separately (security 83, production
routers 87, auth/billing 221, conviction 178 and release closure 195).
`git diff --check` passes. Test-generated local timeline/watchlist changes were
restored separately from the implementation.

## Remaining gates

This is an unblinded implementation-assistant review of the complete answer and
its additional annual operating context. It is one
exposed generic NPK probe, not an exact frozen-question pass or current ASML/ACHC
rerun. No independent factual/usefulness review, complete cash reconciliation,
current interim explanation, signed-in acceptance or valuation boundary follows.
Receipt consistency does not independently establish origin authenticity or
current availability. Independent complete-answer assessment across company sizes
and question families is still required.

The rough 55% planning estimate and null quality pass rate remain unchanged. All
twelve live approvals are consumed. No new capture, provider/model request,
spending, old-ledger execution, benchmark/holdout change or activation follows.
