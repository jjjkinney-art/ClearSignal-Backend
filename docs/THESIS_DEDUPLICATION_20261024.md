# Complete-answer readability repair — 24 October 2026

## Finding and change

Reading the entire PR337 retained answer exposed a presentation regression: its
opening improved access to company-specific evidence but repeated segment results,
the impairment event and consolidated observations. The complete answer grew
from 1,814 words before PR337 to 2,259 words. This is an unblinded diagnostic by
the implementation assistant, not independent usefulness adjudication.

The foundation now moves the complete final-bound segment statement and complete
impairment statement into the opening instead of rendering them twice. The
segment statement retains its definition of operating profit, exact corporate
allocation, periods, management sales explanation and scope restrictions. The
impairment retains its dated event, management recovery assessment, duplicate-row
restriction and consolidated-versus-narrative-segment distinction. The repeated
consolidated-observation overview is removed; original financial comparisons and
their periods, direction interpretations and monitoring questions remain below.
Other business, product, organisation, order and risk context remains available.

This is general presentation logic over final-bound claim kinds, with no ticker,
issuer, concept or amount exceptions. Producer admission and final reconstruction
are unchanged. Structured claims stay in their original order with their original
reference IDs; only their prose placement changes. A claim-kind cap already limits
these two statement types to one each. Missing segment evidence still produces
an explicit incomplete-case statement; no missing evidence is manufactured.

## Retained comparison and verification

`scripts/replay_retained_thesis_deduplication.py` loads the committed PR337
foundation **and overview** at
`66f24ca4e276be8c14bd317a9b3c789b13b8f773` for its baseline. Both baseline and
candidate use identical ordinary ingestion/admission with retained PR292 filing
and PR314 company-facts responses. External sockets are denied. The baseline
exactly equals the archived PR337 candidate, rather than silently using the new
overview implementation with the old foundation.

`THESIS_DEDUPLICATION_REPLAY_20261024.json` records the complete before/after prose
and structured evidence. It verifies:

- Full source-answer objects are equal, including all fourteen claims,
  inferences, coverage and unanswered parts.
- Reference objects, segment disclosures and evidence-integrity results are equal.
- Each complete claim statement appears exactly once in candidate prose.
- The candidate is 1,909 words versus 2,259: **350 words / 15.5% fewer**.
- The original source hashes/receipts and all nineteen facts-archive inventory
  entries agree; zero external requests and zero model calls occur.

738 focused foundation/source-answer/segment/risk/monitoring tests passed. The
ordinary segment source-gate test checks a single complete statement, losses,
periods, allocation, final citations and cross-period uncertainty. The impairment
source-gate test additionally checks one complete event and repeat application
without accumulated prose or altered structured results. All 168 tests in the
three directly affected foundation/segment/impairment files pass after those
assertions were extended. `git diff --check` passes.

## Remaining work

The new candidate is still 95 words longer than the 1,814-word pre-overview answer.
Word count and evidence preservation do not establish useful research. This
single exposed NPK probe still has no verified valuation/expected-return boundary,
complete business model, relative competitive assessment or independently
established earnings bridge. Source consistency does not independently prove
source authenticity or current availability. No current ASML/ACHC rerun, exact
frozen-question pass, signed-in acceptance or independent blind review follows.

The next substantive gap is evidence for the economic and valuation assumptions
needed by the question, followed by independently assessed complete answers
across the frozen company-size/question groups. Broader development work still
requires its bounded quota plan and separate live authority. All twelve live
approvals are consumed. This repair uses no new capture, provider/model call,
spending, old-ledger execution, holdout access or activation. The rough 55%
planning estimate, null quality pass rate and open launch gate are unchanged.
