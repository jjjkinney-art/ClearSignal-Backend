# Explicit named-segment composition — 21 October 2026 Auckland

Base: `6c5d1e700f94350d57ac3b48755927a25d6e37e5` (merged PR321).

## Problem and resulting behavior

The retained NPK Business section explicitly describes the composition of its
Safety segment. The ordinary business-description producer rejects that sentence
as `subject_or_activity`, so its source-backed thesis retains a distribution
quote but reports segment structure as unverified.

A shared bounded rule now admits a complete sentence with an explicitly named
segment, a present-tense composition predicate and one source-spelled legal
organization. Supported predicates are `is currently comprised of`, `is comprised
of`, `consists of` and `comprises`. There is no ticker, segment-name or company-name
whitelist. Existing short-sentence, numeric, forecast, promotion, internal-activity,
complete-Business-section, issuer identity and document eligibility checks remain.

This is deliberately a structure-only statement. Its `business_scope` records
`{kind: named_segment, label: <source label>}`. The final binder reconstructs
that scope from the exact quote and rejects missing, changed or injected scope.
The final financial foundation carries it into the claim. The summary explicitly
limits its meaning; it does not independently establish legal ownership,
consolidation, activities, revenue contribution or segment economics. No entity
relationship, new financial fact or inferred segment identity is created.

The business coverage contract records a sampled segment description only.
Activities, revenue model, competitive position, valuation and full business-model
coverage remain unresolved without their own evidence. The complete-model flag
remains false. A named composition statement does not certify a complete list of
segments or complete coverage within that facet.

## Selection and boundaries

The existing two-description cap is unchanged. Operations retain priority over
composition, and the complementary-role selector can retain explicit revenue
instead of replacing it with an earlier structure-only sentence. For the retained
NPK source, the existing channel description remains the first excerpt and the
new composition statement fills the second slot.

Ambiguous `the segment`/`this segment`, competitor subjects, negative or expected
composition, mixed promotional/financial clauses and arbitrary product prose do
not qualify. Whole quotes, leading BOM characters and exact normalized offsets
are preserved. The new rule supports a bounded single legal-organization name
with a recognized suffix and optional quoted alias, not general subsidiary
relationship extraction or all legal-name conventions. Existing sentence
segmentation can join a suffix such as `Inc.` without a following alias to later
text; this patch does not change those boundaries or clip a partial sentence to
force admission.

No request schema, source quota/deadline, capture policy, feature flag, model
route or dependency changes. The existing default-disabled scenario feature is
unrelated and stays disabled under the recorded activation policy.

## Retained-source before/after

`scripts/replay_retained_segment_composition.py` verifies the retained PR292
filing against its body/length receipt and all 19 entries in the PR314 archive,
including the NPK Company Facts receipt. It executes the actual visible HTML
parser, complete-section selection, business producer, final business binder,
evidence admission and final source-answer gate. The baseline business producer
and binder come from the exact committed base; the other evidence producers and
final composition are shared between runs.

| Check | Base | Candidate |
| --- | --- | --- |
| Business descriptions | One distribution excerpt | Same excerpt plus the complete Safety composition sentence |
| Segment coverage | Not verified | Sampled source description with `Safety` scope and citation |
| Products/activities and revenue-model coverage | Not verified | Still not verified |
| Other claims | Four financial comparisons, competition and two risks | All seven claim texts preserved; reference numbers shift after the added excerpt |
| Full thesis | Partial | Still partial, with business completeness, competition and valuation gaps |

The replay JSON contains the full before/after answers, bound quotes, references
and coverage. A source hash/receipt establishes retained byte consistency, not
independent SEC origin authenticity or present availability. Filing metadata,
directory identity and the facts HTTP response are injected. This is an exposed
development comparison, not blind usefulness review or production HTTP/JWT,
persistence, browser or fresh-retrieval acceptance. No original archive, body,
ledger or historical answer is overwritten or resumed.

```sh
env -i PATH=/usr/bin:/bin OPENAI_API_KEY=TEST_ONLY \
  SEC_USER_AGENT='Test contact@example.invalid' \
  /PATH/TO/PINNED/python -I -B scripts/replay_retained_segment_composition.py \
  /PATH/TO/PR292/capture /PATH/TO/PR314-results.zip /NEW/replay.json
```

## Validation and remaining work

CPython 3.11.9 and the unchanged pinned direct requirements were installed in a
fresh environment. The new tests cover unfamiliar names and present-tense forms,
exact source spans/BOMs, scope tampering, issuer/section/document exclusions,
selection priority and ordinary disclosure retrieval through final composition
for a known and an invented issuer. Related source, business, financial-thesis
and wording-parity checks passed with external sockets denied. The five local
CI groups also passed. Exact counts, commands, source/log hashes and any remaining
collection/import limitations are recorded in the verification JSON. Hosted full
repository CI is required before merge; local selected checks are not the full
isolated-per-file regression.

This closes one demonstrated business-context extraction gap. Products, revenue
drivers, segment economics, risk materiality, comparative strength and supported
decision assumptions remain substantive work. Independent factual/usefulness
review, the existing development/holdout benchmark and signed-in personalized
acceptance remain separate launch gates. All twelve live approvals remain
consumed; no fresh execution, activation or spending authority follows. No new
company pass rate or launch-completion percentage is claimed.
