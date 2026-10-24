# Named-segment contract and revenue policies — 24 October 2026

## Result

Broad-thesis answers can now include two separately bound accounting-policy views:
named-segment contract terms and segment-specific revenue-recognition timing.
The retained NPK replay adds E15 and E16 after the existing fourteen claims.
All prior claims/references, calculations, coverage and unanswered parts remain
unchanged. The answer remains partial; issuer-wide business-model completeness
and valuation are not established by a segment policy.

The contract view preserves the customer/funding description, fixed-price basis
and explicit limited escalation exception for specific materials. The recognition
view preserves shipment-based recognition, receipt adjustments, legal title and
formal customer acceptance, and the termination-clause/over-time exception.
These are issuer-attributed policies. They do not measure realized revenue, cash
collections, general cost pass-through, future results or competitive advantage.

## Producer and final binding

`app/services/segment_revenue_policy.py` reconstructs a complete bounded accounting
policy proof beginning at the consolidated financial-statement notes heading and
its significant-accounting-policies heading. It requires one REVENUES subsection
and the next sequential numbered policy heading. The complete prefix through that
closing heading is retained, with its original visible-text offset and SHA-256.
Proofs are capped at 50,000 characters within the existing 360,000-character
periodic-document bound. Missing, duplicate, out-of-sequence or partial windows
remain gaps. Existing HTML visibility, document download and section selection
limits are unchanged; the implementation introduces no extra fetch.

Within that window, the bounded grammar requires complete adjacent contract or
recognition blocks. Repeated segment names must agree. The contract's customer
alias must have an explicit parenthesized introduction. The recognition block
must name three distinct segments and include both exceptions. Unknown extra
clauses or truncated exceptions cannot pass by clipping a shorter sentence.
Contract terms and recognition timing remain separate roles and claims.

The grammar is deliberately limited to the reviewed policy forms; it is not a
general accounting-policy interpreter. It uses no ticker, issuer name, industry,
amount, customer acronym or segment-name allowlist. Other source wording and
layouts remain unsupported until separately reviewed and tested.

The producer runs over the annual document already fetched by ordinary thesis
disclosure retrieval. Reviewed-predecessor sources remain excluded. A new default
empty `revenue_policy_disclosures` field carries the proof. Final binding reruns
the note window and complete grammar, reconstructs all context fields and offsets,
and checks issuer URL/CIK, ticker, metadata, source tier, date, freshness, summary
and claim-document reference. The foundation only admits final-bound claims and
canonical response reference IDs, with at most two policy claims.

The new section `Financial statement notes - Segment revenue policies` permits
complete SEC quotes up to 900 characters with a content hash. Ordinary business
quotes retain their 300-character cap. Policy claims do not clear the issuer-wide
business facets or change risk/valuation gap states. The financial foundation
retains its existing source-only confidence and scope behavior.

## Retained comparison and verification

`scripts/replay_retained_segment_revenue_policy.py` denies external sockets,
verifies the retained PR292 filing/receipt and PR314 facts/receipt plus all
nineteen archive inventory entries, and exercises ordinary ingestion, admission
and final answer composition. The baseline uses committed PR339 foundation and
overview at `b9f902e7e908210abe4890d279a550b004a2eab6`, disabling only the new policy
producer; it exactly reproduces the archived PR338 candidate.

`SEGMENT_REVENUE_POLICY_REPLAY_20261024.json` preserves the complete baseline and
candidate. It verifies fourteen prior claims and reference objects are equal,
segment financial disclosures and inferences are equal, and coverage and gaps
are unchanged. The candidate adds only E15 contract terms and E16 recognition
timing. Complete claim statements appear once. The new answer is 2,208 words
versus 1,909, adding distinct evidence rather than restoring the removed duplicate
overview. Length and claim count are not usefulness scores.

Thirty-five synthetic tests cover renamed issuers/segments, complete exceptions,
customer aliases, partial/duplicate note windows, changed antecedents, scoped quote
caps, proof/offset/hash/context/metadata tampering, ordinary single-fetch retrieval
and final citations/coverage. The focused foundation/source-answer/segment/risk/
monitoring suite passes 773 tests. The retained replay reports zero external
requests and zero model calls. No capture ledger is resumed.

Full repository collection finds 19,017 tests with zero collection errors. Five
CI regression groups pass separately: security 83, production routers 87,
auth/billing 221, conviction 178 and release closure 195. `git diff --check` passes.
The replay also retains both complete new producer proofs for source inspection.

## Remaining gates

This is one exposed generic NPK thesis probe. It is not an exact frozen core
question rerun, current ASML/ACHC evaluation, independent factual/usefulness
adjudication, signed-in acceptance or launch clearance. Receipt consistency does
not independently establish origin authenticity or current source availability.
The rough 55% planning estimate and null quality pass rate remain unchanged.

Next inspect the complete candidate answer for economic usefulness, then implement
the separately reviewed matched-period cash-flow explanation. Its annual evidence
must not explain later interim results without a matching bridge. Price/security
basis and explicit future valuation assumptions remain separate missing inputs.
All twelve live approvals remain consumed; no new capture, provider/model call,
spending, benchmark/holdout change, old-ledger execution or activation follows.
