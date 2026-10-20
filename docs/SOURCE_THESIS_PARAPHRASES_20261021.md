# Equivalent source-backed thesis requests — 21 October 2026 Auckland

Base: merged PR318, `ba6c70df35c84b94ffab30c9419a416f13a63438`.
This is offline product work, not a live pilot or launch acceptance.

## Demonstrated inconsistency

With identical company evidence, the existing broad-thesis selector recognizes
“What is the investment thesis for NPK?” but not equivalent explicit requests
such as “Explain the investment thesis for NPK” or “What is NPK's investment
thesis?” All three can explicitly request citations and enter the source route.

The missed forms fall through to the ordinary source list. In the retained NPK
replay, they return `attributed` with an empty `unanswered_parts` list rather than
the canonical partial financial foundation. That label supports the listed facts;
it is not proof that the broader thesis is complete. The defect is inconsistent
question scope/composition and omitted broader gaps, not demonstrated fabricated
numbers or a proven production incident.

## Bounded shared classifier

`is_broad_thesis_request` preserves the legacy form and additionally recognizes:

- Explain, outline, summarize/summarise, give or provide an investment thesis;
- possessive company wording, including straight/curly apostrophes;
- the contracted “What's the investment thesis …” form;
- an optional “please” or “me” in the supported instruction forms.

New forms require a bounded request prefix and thesis object. They exclude
personal/saved/prior/selected/portfolio and comparative/change tasks. They do
not resolve issuer identity or authorize sources from the company name in a
sentence. Existing ticker/CIK, source binding, period, freshness, metric and
reference checks remain responsible for evidence admission.

The shared selector is used by core metric selection, disclosure retrieval and
final answer composition. Equivalent explicit source requests now receive the
same core evidence selection, partial foundation, supported inferences and
unanswered thesis parts as the canonical question. Newly recognized wording can
therefore schedule the existing bounded disclosure stage that it previously
missed. Core-metric defaults for recognized forms also become the same four
metrics on the ordinary generated route; that route still runs its models.
Stage/request limits and deadlines themselves do not change.

This does not change the separate source-request detector: uncited ordinary
analysis still uses the existing generated route. It does not bypass segment,
Services, named-risk/KPI guards, change decision-threshold handling, supply
missing valuation assumptions, remove business/competition/risk gaps, or turn
partial evidence into a complete investment thesis. New requests outside the
supported grammar remain outside this increment; it is not general language
understanding or a claim that every possible paraphrase is covered.

## Offline evidence and tests

52 new tests check exact result/answer parity against the canonical question for
twelve supported forms across Apple and an invented unseen issuer. They also
check bounded core retrieval and skipped models in the actual research pipeline,
unchanged ordinary generated analysis, empty-evidence gaps, and exclusion of
saved/personal/comparative/meta and scoped Services/supply-chain/cloud tasks.
New tests join their own executor workers without changing production deadlines.

`scripts/replay_retained_thesis_wording.py` loads the retained PR292 NPK filing
and PR314 NPK Company Facts bytes. Both bodies match hash/length receipts; all
19 PR314 archive inventory entries match. It assembles admitted evidence once,
then exercises the real final source gate on identical inputs, substituting
only the committed baseline broad-thesis selector for the before comparison.

| Retained-data check | Baseline selector | Candidate selector |
| --- | --- | --- |
| Twelve equivalent explicit source requests | Flat attributed fact list; no declared unanswered parts | Exact canonical partial foundation and explicit gaps |
| Financial comparisons/business/competition/risks | Not all included by the flat presentation | Canonical source-bound claims retained |
| Competitive position, valuation/returns, business completeness and risk materiality | Not declared by that fallback | Remain explicit unresolved parts |
| Complete investment thesis/launch acceptance | Not established | Not established |

All twelve candidate results and direct answers exactly match the canonical
result. `SOURCE_THESIS_PARAPHRASES_REPLAY_20261021.json` retains the canonical
claims/references, before/after answers, statuses, gaps and canonical result
hashes. This is an exposed development comparison, not blind usefulness review.

```sh
env -i PATH=/usr/bin:/bin OPENAI_API_KEY=TEST_ONLY \
  SEC_USER_AGENT='Test contact@example.invalid' \
  /PATH/TO/PINNED/python -I -B scripts/replay_retained_thesis_wording.py \
  /PATH/TO/PR292/capture /PATH/TO/PR314-results.zip /NEW/wording-replay.json
```

The retained replay covers final composition, not full HTTP/JWT/database/browser
or fresh retrieval acceptance. Synthetic tests separately cover normal pipeline
selection/model skipping. Directory identity, filing metadata and the source
HTTP response are injected. Hashes establish byte integrity, not independent SEC
origin authenticity or present availability. The filing receipt explicitly
records independent origin verification as false. No source-origin proof is
inferred by changing question wording.

## Release checks and authority

The verification JSON records exact selections, commands, logs and original-log
hashes. Final focused selection passes 52 tests; related selection passes 537.
Eight existing executor teardown warnings remain in the combined related run;
none are suppressed or claimed fixed. Collection finds 18,445 tests with zero
errors and import smoke finds 136 routes. Required hosted CI/full isolated-per-
file regression remains pending on the published head.

No runtime dependencies, production flags, API contracts, evidence producers,
frozen benchmark questions/holdouts, scenario activation, deadlines, quotas,
claim/fencing rules or capture policies change. Original bodies and consumed
records are not rewritten; full historical inventories are not independently
revalidated here. All twelve live approvals remain consumed. No new live
execution, retention or spending authority is created.

The broader launch blocker still requires useful company-specific competition,
valuation/decision assumptions and risk-materiality analysis, independent source/
usefulness review, broader development/holdout results and production signed-in
acceptance. This increment corrects question handling; it creates no new company
pass rate, launch-readiness result or defensible completion percentage.
