# Bound business-context coverage — 16 October 2026 Auckland

Base: `bbb971db41cd965b5e15adee2bdf153c0a96a315` (PR296).

## Demonstrated problem

PR295's retained NPK answer admits a factual annual-filing distribution sentence.
That establishes a channel description, not the issuer's products, revenue
mechanism, segment economics or a full business model. The financial foundation
previously removed its general business-model gap whenever any business quote
was admitted, even while its prose correctly warned that excerpts were partial.
The saved six-case quality review identified this mismatch.

The extractor also selected the first two qualifying descriptions after its
existing issuer/operations/segment preferences. In an invented transfer fixture,
two similar operating descriptions occupied both slots while a later explicit
revenue-model sentence qualified but was not selected.

## Changed behavior

Only already qualified full business sentences enter the new selector. It keeps
the previous first choice, then prefers a second description that adds a role:
operating activities, explicit revenue mechanism, customers/channels or segment
structure. Original order breaks ties. The existing preference for actual
operations over unexplained segment acronyms remains in force. The two-item cap,
sentence limits, exact source spans and document/issuer/section guards remain.
No new sentence grammar, source, download or larger evidence allowance is added.

The final composer computes `business_context_coverage` only from descriptions
that pass final binding and have admitted response reference IDs. It does not
trust a producer/caller's facet annotation. Each facet reports a sampled source
description or `not_verified`, with the actual admitted IDs. A customer earning
revenue cannot fill the issuer-revenue facet. A spelled-out segment list does
not establish operating activities, revenue contribution or segment economics.
Named subjects require the existing identity checks before classification; the
classifier itself performs no issuer lookup or network call.

The business binder now explicitly rejects unavailable evidence, consistent
with the final admission boundary. Source/currency/financial comparison logic,
quote qualifications, competition and risk admission remain unchanged.

When business quotes are admitted, readable answers display which facets those
quotes support and retain `business model completeness` in unanswered parts.
`complete_business_model` remains false: no collection of these short samples
automatically proves complete coverage. With no admitted description the existing
combined business-model/competitive-position gap remains. Competitive advantage,
valuation, risk materiality and causal explanations remain separate unanswered
requirements. The source answer is still partial; no confidence/conviction score
or recommendation is invented.

Example: a distribution-only description provides customer/channel context;
activities, revenue mechanism and segments stay unverified. A directly stated
subscription/fee revenue mechanism can be selected alongside the existing
activity quote without admitting a third quote or paraphrasing either sentence.
This improves the use of available qualified evidence; it does not claim to
extract a full business model from every issuer's filing.

## Offline evidence and validation

[NPK replay summary](business_context_npk_replay_20261016.json) binds the existing
PR292 retained HTML body SHA-256
`8d9ea0ecbc1619994be67fe36900878ae6c825ba99047373ad749f9caedab8a1`.
The actual public-document bounded reader, visible-text normalization, business
extractor, final binder and evidence admission ran with a local response fixture,
invented DNS result and socket-denying audit hook. No external request occurred.
The exact source sentence and span reproduce; one description is admitted and
only the customers/channels facet is present. The final classifier reproduces
the saved coverage. This is saved-body replay, not fresh SEC or live-pilot proof.
The response ID in that isolated replay is E1, not the earlier pilot's E5.

472 focused tests passed on CPython 3.11.9 with audited dependencies and sockets
denied. This includes 22 new tests and existing business/disclosure, financial
foundation, competition, product-channel, source-answer, citation, margin and
diagnostic regressions. New cases cover complementary selection and preserved
caps/spans, distribution-only and segment-only gaps, customer revenue, qualified
customer wording, unchanged rejection of forecasts/promotion/financing/internal
activities, unavailable/stale/wrong-issuer/unreferenced proof, caller annotations
and final remapped citation IDs. An initial selector version failed the existing
segment-acronym preference test; that was corrected and the final suite passed.

All 36 existing source-monitoring and monitoring-freshness synthetic pilot tests
also passed, for 508 completed regression tests total. These retain the existing
quota/claim/deadline and zero-model checks. Required hosted CI and independent
review remain pending. No old live result is replaced or relabeled by the
offline replay. Production monitoring-fallback settings, held-out reservation,
transport, request/stage quotas, deadlines, claims, fences and historical records
are unchanged. All eleven live approvals remain consumed; no new approval or
execution package is created by this change.

## Remaining launch work

Broader sourced business/segment coverage, economic drivers, independently
supported competitive assessment, valuation/decision boundaries and quantified
risk relevance remain open. The 100-company development/holdout plan and signed-in
personalization gates remain unchanged. Do not count this honest coverage report
or the synthetic selection improvement as a full useful-answer or launch pass.
