# Named-segment competitive context — 21 October 2026 Auckland

Base: merged PR317, `daa095f3c1038be2a228d9b958cbcbf07e3e1f3e`.
This is an offline development increment, not a live pilot or launch acceptance.

## Demonstrated missing context

The retained NPK business section contains this complete disclosure:

> The Defense segment competes for its business primarily on the basis of technical competence, product quality, manufacturing experience, and price.

The committed extractor admits company-subject forms such as “We compete” but
misses this explicit named-segment form. Offline replay of the retained filing
and Company Facts bytes demonstrates zero competition claims before this change
and one afterward in the normal core-thesis pipeline. The original broad
question, source-only route and unresolved question parts are preserved.

This is a demonstrated extraction gap in exposed development material. It does
not prove an earlier live exception had this cause, independent SEC origin
verification, or that other untested companies now pass.

## Shared rule and source scope

A bounded grammar admits a complete “The [named] segment competes …” sentence
that states competition with/against others or its basis. Names are read literally
from the sentence, without a ticker dictionary, preceding-heading expansion,
pronoun resolution or inference from “it” or “this segment.” Source quotes may
retain leading SEC BOM characters; no content or offsets are removed.

Only a complete, eligible current-issuer SEC business section can supply this
new form. A named segment in risk-only prose, a predecessor/wrong-CIK document,
an incomplete section, forecast, promotional claim, numeric market share or
internal workforce context does not qualify. Existing length, source identity,
reference, hash, date, availability, freshness and two-description limits remain.
This extends the admitted grammar; it does not relax the existing excluded
claim categories or source-validation requirements.

The evidence carries `competition_scope: {kind: named_segment, label: ...}`.
Final binding reconstructs that scope from the exact quote and checks the
business-section requirement again. Omitted, forged or changed scope fails
closed, including a forged segment on an ordinary company-subject disclosure.
The final thesis claim retains the scope rather than flattening it into a
company-wide claim. Presentation explicitly identifies named-segment context
and leaves relative strength, market share and durable advantage unverified.
It does not independently assert ownership, importance or materiality of that
segment merely from the label.

The company-level competitive-position and valuation gaps remain open. The
response stays partial with no assessed investment conviction. No segment
margin, earnings impact, risk likelihood, moat or investment attractiveness is
inferred. In particular, consolidated financial comparisons are not relabeled
as segment comparisons or used to rank this segment's competitive strength.

## Retained replay and boundaries

`scripts/replay_retained_segment_competition.py` requires the retained PR292
capture directory, the PR314 results ZIP and a fresh output filename. It checks
both body hash/length receipts and all 19 PR314 archive inventory entries.

- NPK HTML: 1,404,517 bytes; SHA-256
  `8d9ea0ecbc1619994be67fe36900878ae6c825ba99047373ad749f9caedab8a1`.
- NPK facts: 2,490,080 bytes; SHA-256
  `0f512e8670882f4d201d24252e31ab457f512be1aa6ac9b7243d3b8ec820e19f`.

It uses the application HTML normalizer and real Company Facts parser/metric
producer, source admission, final binding and normal research pipeline. It loads
only the committed baseline competition extractor to compare old/new selection.
The new output preserves both responses and is separate from historical records.
`NAMED_SEGMENT_COMPETITION_REPLAY_20261021.json` retains that comparison; existing
saved answers are not backfilled or silently rewritten.
The candidate's admitted claim retains the exact quote, offsets, original filing
URL, business section and final response citation. All newly created replay
executor workers finish within the existing five-second offline join check.

The source GETs are substituted with retained bytes; directory identity, filing
metadata and unrelated providers are injected. External socket/DNS/connect events
are denied (local AF_UNIX construction is allowed for the event loop). There are
zero external provider requests and model calls. This is not transport/HTTP/JWT,
production database, browser or fresh current-source acceptance. Body hashes
establish retained-byte integrity, not independent origin authenticity: the
original filing receipt explicitly records origin verification as false.

```sh
env -i PATH=/usr/bin:/bin OPENAI_API_KEY=TEST_ONLY \
  SEC_USER_AGENT='Test contact@example.invalid' \
  /PATH/TO/PINNED/python -I -B scripts/replay_retained_segment_competition.py \
  /PATH/TO/PR292/capture /PATH/TO/PR314-results.zip /NEW/replay.json
```

The replay uses existing pytest fixtures as offline tooling, not runtime product
dependencies. No raw bodies, original ledgers or credentials are committed or
rewritten. Full historical inventories are not independently revalidated here.

## Validation and remaining work

28 new tests cover unseen segment names, exact BOM-bearing quotes/offsets,
final source-answer scope, citation binding, continued partial status, forged
metadata, wrong issuer/stale evidence and excluded prose/sections. The new and
existing competition selection passes 62 tests; the related selection passes
595 tests, including the normal pipeline and signed local save/retry suite.
Twelve existing executor teardown warnings remain in the combined run; they are
recorded and not claimed fixed. Collection finds 18,393 tests with zero errors;
import smoke finds 136 routes. Exact commands, original-log hashes and results
are retained in `NAMED_SEGMENT_COMPETITION_VERIFICATION_20261021.json`.
Hosted CI/full isolated per-file regression must pass on the published head.

No production flags, deadlines, quotas, claim/fencing rules, capture policies,
credentials or consumed run records change. All twelve live approvals remain
consumed; no new execution, retention or spending authority follows. Any future
pilot needs a new source binding/configuration review and separate approval.

This adds useful scoped context, not a complete competitive assessment.
Independent source/usefulness review, evidence for valuation assumptions and
risk materiality, broader business coverage, and the existing development/
reserved-holdout benchmark remain launch gates. No new company pass rate or
completion percentage is inferred from this single retained case.
