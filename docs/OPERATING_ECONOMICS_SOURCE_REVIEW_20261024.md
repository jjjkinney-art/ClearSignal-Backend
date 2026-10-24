# Operating economics and valuation evidence review — 24 October 2026

## Finding

The retained filing contains more useful operating evidence than the current
answer admits. The next shared extraction slice should address **named-segment
contract economics and revenue recognition**, followed by matched-period cash-flow
explanations. This targets the missing explanation of how the company earns
revenue and bears costs, rather than another cosmetic answer revision.

Valuation arithmetic already exists separately in `conditional_valuation_math.py`
and source-anchored scenario services, behind disabled-by-default controls.
Building another calculator would repeat completed work. The broad threshold
answer still lacks an admitted price/security basis and explicit future earnings,
multiple, horizon and return assumptions. This inspection neither supplies those
inputs nor activates or connects that separate endpoint to broad `/ask`.

## Evidence inspected

`scripts/inspect_retained_operating_economics.py` reconstructs full normalized
visible text from the retained PR292 filing, verifies its body/receipt and text
hashes, and verifies all nineteen PR314 facts-archive manifest entries. It denies
external socket operations and writes a new output only. The resulting
`OPERATING_ECONOMICS_SOURCE_MAP_20261024.json` preserves eight complete passage
groups with exact character offsets, quote hashes, section windows, scope limits
and `new_production_admission: false`. No capture ledger is executed.

| Retained evidence | What it could add | Required boundary |
| --- | --- | --- |
| Business payment and inventory practices | Payment terms, seasonal inventory and just-in-time requirements | Practices do not measure a particular cash-flow movement |
| 2025 versus 2024 operating cash explanation | Management's working-capital and noncash-item explanation | Annual cash use remains an outflow; cannot explain 2026 interim results |
| Investing activities | Capital expenditure versus securities sales/maturities | Investing flows are separate from operating and financing cash flows |
| Line-of-credit financing | Evidence that financing activity exists | Proceeds are a flow, not a debt balance; tag absence is not zero debt |
| Revenue obligations and allowances | Delivery obligations, returns and variable consideration | Retain allowances and contract differences |
| Defense contract terms | Customer/funding exposure and fixed-price cost exposure | Retain limited escalation exception; do not infer pricing power |
| Segment revenue recognition | Shipment/receipt versus title and customer acceptance | Retain termination-clause/over-time exception; revenue is not cash collection |
| Advances and contract liabilities | Cash can precede revenue recognition | Balances, revenue releases and financing-component judgments differ |

The explicit Defense economics passage explains that contract prices are generally
not adjusted for actual contractor costs, except limited escalation provisions
for specific materials. That is more useful for evaluating operating assumptions
than treating rising consolidated margins as proof of an advantage. The adjacent
recognition passage qualifies the normal title/acceptance pattern with a possible
over-time exception. Both qualifications must survive extraction and rendering.

The retained payload lacks all five selected standard debt concepts inspected,
while the filing describes $23.624m of net line-of-credit proceeds during 2025.
This is a concrete reason to reject “missing debt tags means no debt.” It does
not establish a period-end debt amount, complete liabilities or a net-cash value.

## Existing contracts exercised offline

Using the existing annual source selectors at the fixed retained boundary of
15 October 2026:

- Basic annual USD EPS qualifies at 4.63 versus 5.82 for 2025 versus 2024.
  Diluted EPS does not qualify under the same latest-annual contract. Do not
  substitute basic for diluted or treat failure as zero diluted earnings.
- Annual operating cash flow qualifies at **-$9.137m versus -$53.426m**.
  A smaller outflow is not positive operating cash generation.
- Annual capital expenditure qualifies at $27.034m versus $7.531m. These are
  reported outflows, not depreciation, maintenance-only spending or a sustainable
  reinvestment requirement. No normalized free-cash-flow estimate is inferred.

These are separate offline source-contract diagnostics, not new claims in a
production answer. They do not change the existing six historical pilot outputs,
current NPK replay, benchmark questions, denominators or acceptance decisions.

## Next bounded shared implementation

Implement a separate producer and final binder for **explicitly named segment
contract/revenue-policy context**, beginning with the source-supported grammar
above. It should reconstruct the complete accounting-policy window, section
identity, issuer identity, paragraph offsets, adjacent exceptions and quote hash.
No ticker, company name, dollar amount or concept namespace may authorize the
grammar. Discovery and fetch budgets remain unchanged.

Keep contract economics separate from recognition timing and cash timing in the
schema. Preserve fixed-price limitations and escalation exceptions, each named
segment, management attribution and source date. Do not promote accounting policy
to realized performance, relative advantage or future revenue. A segment passage
must not clear issuer-wide business-model completeness. Longer complete statements
need scoped citation proof rather than weakening global quote caps or truncating
exceptions. Final binding must reproduce every displayed scalar and relationship.

Use synthetic issuer/segment names to challenge changed segments, missing exception
sentences, conflicting windows, orphan pronouns, stale sources, offset/hash/summary
tampering and quotation truncation. Replay the same retained input through ordinary
ingestion/admission and final answer, preserving all prior claims/citations and
gaps. Review the complete answer after implementation; extraction success is not
usefulness acceptance.

The later cash-flow slice needs separately bound annual statement amounts and
management explanation from the same comparison window. It must retain positive
versus negative cash signs, prior-year context, investing/financing distinctions
and uncertainty. It cannot turn this annual explanation into a bridge for the
later interim cash-flow increase. Valuation/security inputs remain a separate gap.

## Verification and limits

The inspection completed with eight offset/hash-checked passage groups, nineteen
verified archive entries, qualified basic EPS/annual cash-flow/capex diagnostics,
and zero external requests/model calls. `git diff --check` passes. This change
adds a reproducible source-inspection script and review artifacts; production
code, answers and settings are unchanged.

This is an unblinded review by the implementation assistant on exposed retained
evidence, not independent factual or usefulness adjudication. Receipt consistency
does not independently establish authenticity or current availability. The rough
55% planning estimate, null quality pass rate and open launch gate are unchanged.
All twelve live approvals remain consumed. No new capture, spending, old-ledger
resumption, holdout access or activation follows.
