# ClearSignal Intelligence Benchmark — foundation contract

**Status:** implementation foundation  
**Schema:** `1`  
**Scope:** offline contracts and release-gate policy; no live requests, trades, or user-facing performance claims

## Why this exists

ClearSignal needs evidence that its analysis is factually trustworthy and genuinely useful across companies ranging from Apple to thinly covered small issuers. A single answer-quality score or backtested return cannot establish that. This contract preserves separate measurements for facts, evidence, reasoning, calibration, consistency, market usefulness, latency, and cost.

The existing production-validation harness remains the fast regression layer. This foundation adds the records required for frozen historical cases, sealed evaluation, memory A/B tests, proactive-event replay, and a live shadow research ledger.

## Non-negotiable invariants

1. Historical cases have an explicit timezone-aware `as_of` boundary.
2. No admitted source may have been published after that boundary.
3. Source content, generated output, configuration, and the complete manifest are SHA-256-addressed.
4. A completed output is not mutated. A correction or rerun receives a new `run_id` and may reference `parent_run_id`.
5. Feature flags are recorded in canonical order. Model, prompt, retrieval, build, and optional memory fixture versions are explicit.
6. Aggregate quality cannot hide critical failures or regressions in protected issuer groups.
7. Market returns never substitute for factual or analytical integrity.
8. Private user research is not benchmark data. Memory evaluation uses synthetic or explicitly consented fixtures with owner-isolation tests.

## Protocols

| Protocol | Purpose | Release cadence |
|---|---|---|
| `fast_regression` | Schemas, numerical checks, citations, issuer resolution and past production defects | Relevant PR and deployment |
| `frozen_historical` | Point-in-time analysis over a stratified company universe | Major release |
| `metamorphic_consistency` | Paraphrases, distractors and controlled reruns | Major release and regression investigation |
| `memory_personalization_ab` | Measure the incremental value and risks of account-owned memory | Personalization release |
| `proactive_noticing_replay` | Event → relevance → thesis impact → confidence change | Proactive-intelligence release |
| `live_shadow` | Immutable forward research and later outcome measurement | Fixed production schedule |
| `adversarial_failure` | Injection, stale data, conflicts, ambiguity, fiscal traps and provider failure | Weekly and before major release |

## Launch-stage gate

The first frozen threshold policy requires:

- material numerical accuracy ≥ 98%;
- correct claim/source/document/period binding ≥ 95%;
- zero fabricated material sources;
- zero cross-account exposures;
- zero open critical benchmark failures;
- zero detected point-in-time leakage;
- no protected market-cap or issuer-class regression;
- complete sealed historical evaluation;
- an operating live shadow ledger; and
- a passing reproducibility sample.

These are conjunctive gates, not inputs to an average. Any failure blocks the gate and produces a specific reason.

Longitudinal Brier score, calibration error, thesis-event accuracy, and benchmark-relative returns are explicitly marked as outcome-maturity-dependent. Their absence at launch does not become fabricated evidence of success or failure. Launch requires the measurement system to be operating; performance claims wait for predefined horizons, adequate samples, uncertainty intervals, independent review, and legal review.

## Next implementation slices

1. **Implemented in the registry slice:** versioned issuer metadata now stratifies all existing 36 fixtures, enforces structural integrity, and reports the current 12/100 issuer coverage honestly. Continue growing the core universe without discarding prior baselines.
2. **Implemented in the artifact-store slice:** append-only local run bundles now publish manifests, outputs and scorecards atomically with duplicate-run rejection; forward shadow entries are immutable and hash-chained. Continue with production-safe storage/retention design only after the offline contract is accepted.
3. **Implemented in the point-in-time slice:** source-type-aware timestamp adapters and a fail-closed leakage audit now gate historical evidence. Continue by integrating the gate into the frozen historical runner when that runner is introduced.
4. **Implemented in the factual-grading slice:** deterministic numerical-dimension scoring and explicit citation adjudication now produce the two launch-gate metrics. Continue by calibrating automated graders against a growing set of double-reviewed examples before allowing automation to supply adjudications.
5. **Implemented in the blind-review slice:** opaque output packets, deterministic multi-reviewer assignment, fixed analytical rubrics, identity-bound submissions, and disagreement reporting now prevent model identity from influencing review and keep unresolved judgments visible. Continue by calibrating rubric anchors with double-reviewed examples and a documented adjudication workflow.
6. **Paraphrase, memory A/B, proactive replay, and protected subgroup scorecards implemented:** the benchmark now exposes material wording instability, isolates memory lift and safety, replays thesis-aware event detection, and prevents aggregate results from hiding under-sampled or failing issuer groups. Continue expanding frozen cases until every protected group meets its declared sample floor.
7. **Shadow safety, durable state, operator controls, provider cancellation, inert scheduling, and a frozen rehearsal implemented:** the inert-default admission boundary enforces cost ceilings, quotas, concurrency, timeouts, capability allowlists, idempotency and kill switches. Synthetic reservations, fenced leases, hash-chained lifecycle transitions, kill state, aggregate administrator controls, and content-free provider cancellation acknowledgements survive restarts with explicit retention. The scheduler evaluates one caller-supplied tick, requires dry-run admission, and cannot reserve or execute work. A registry-pinned seven-issuer rehearsal spans six sectors, two domiciles and US GAAP/IFRS while explicitly preserving the known mid-cap and small/micro-cap gaps. Continue by running this rehearsal in the deployment environment before considering any execution capability.

## Registry audit

Run the offline structural audit after changing either the fixture suite or issuer registry:

```bash
python3 scripts/benchmark_registry_audit.py
```

The default command fails on registry/fixture integrity defects but reports launch-target gaps without failing. CI can adopt the strict launch-coverage gate when the expansion is intended to be complete:

```bash
python3 scripts/benchmark_registry_audit.py --strict-targets
```

Registry v1 maps the original 36 fixtures to 12 unique issuers. It deliberately reports zero mid-cap and zero small/micro-cap coverage. This prevents the historical large-company suite from being mistaken for evidence that ClearSignal already performs consistently across the public-company universe.

## Append-only evidence artifacts

`validation.benchmark_artifacts.BenchmarkArtifactStore` provides the offline evidence contract. Each completed run is staged in a private directory, fsynced, and atomically published under its immutable `run_id`. The store refuses duplicate identifiers and verifies the manifest, output, scorecard, and bundle hashes independently.

Forward shadow observations are stored as one immutable file per event. Every entry records the prior entry hash, making deletion, reordering, payload alteration, or head corruption detectable. A file lock serializes local writers and an optional expected-head hash prevents stale writers from appending to an unexpected chain.

Verify a store without changing it:

```bash
python3 scripts/benchmark_artifact_verify.py /path/to/artifact-store
```

This filesystem implementation is an offline foundation, not authorization to put private production research into local artifacts. A later production design must define encrypted storage, access control, retention/deletion, backups, operator permissions, regional handling, and account-owned data boundaries before any user-derived record is admitted.

## Point-in-time source admission

Historical evaluation must use the timestamp at which the exact admitted bytes became public. The adapter therefore uses SEC acceptance time for filings, publication time for issuer releases/news/transcripts, observation time for market and consensus data, and an explicit availability time for other sources. Retrieval time is never accepted as a publication fallback.

If a document was later amended, `revision_published_at` supersedes the original date for those revised bytes. A pre-boundary original publication cannot authorize a post-boundary revision. Historical bytes retrieved after the case date require a valid SHA-256 hash; otherwise the audit cannot prove that later content did not leak into the case and fails closed.

Audit a proposed source manifest before running a historical case:

```bash
python3 scripts/benchmark_point_in_time_audit.py source-manifest.json
```

Future source versions, missing semantic timestamps, impossible retrieval ordering, missing document identity, invalid version hashes, and duplicate source IDs are stop-ship findings. Properly timestamped secondary sources may be admitted but retain an explicit human-review finding for provenance and entailment.

## Factual and citation grading

The factual grader scores each frozen claim across value/sign, unit, currency, fiscal period, consolidated-or-segment scope, expected document identity, document existence, and citation entailment. A material numerical claim passes only when every numerical dimension is correct. Citation binding passes only when the cited document exists, matches the frozen reference source, and an explicit adjudication says the cited evidence supports the claim.

Entailment is never inferred from keyword overlap. Adjudications record a reviewer identity, rationale and one of `supports`, `partial`, `contradicts`, `not_found`, or `pending`. Pending or missing adjudication remains incorrect for the launch-gate ratio and sets `fully_adjudicated=false`; it is never silently counted as a pass.

Grade a prepared claim set:

```bash
python3 scripts/benchmark_factual_grade.py grade-input.json --require-complete
```

The resulting scorecard exposes `material_numerical_accuracy`, `claim_source_binding`, `fabricated_material_sources`, pending review count, per-claim dimension results, and explicit findings. Automated entailment may be introduced only after its outputs are calibrated against double-reviewed human examples and its version is recorded with the benchmark run.

### Captured product-output grading

`validation.generated_output_grading` connects the frozen factual grader to
serialized responses from ClearSignal's real investment pipeline. The adapter
admits only structured `answer.verified_sec_facts` that remain reported,
ticker-matched, metric-matched, and bound to the exact frozen SEC accession.
Generated prose and generic extracted numbers are never promoted into verified
facts. Value, unit, currency, period, scope, and claim/source identity then pass
through the same deterministic launch gate used by the curated evidence pack.

The grader is deliberately offline: response capture and provider execution are
separate operations, and grading cannot write research memory, user records,
notifications, or benchmark scheduler state.

```bash
python3 scripts/benchmark_generated_outputs.py captured-output.json
```

The companion capture command is inert by default. It validates only synthetic,
registry-listed cases and rejects account IDs, user IDs, memory, personalization,
conversation, and delivery state. Real provider/model execution requires both
the `--execute` switch and an explicit process-level enablement. The runner calls
the investment pipeline with all context absent and legacy history side effects
disabled; its JSON output can be passed directly to the grader above.

```bash
python3 scripts/benchmark_pipeline_capture.py capture-manifest.json

CLEARSIGNAL_BENCHMARK_CAPTURE_ENABLED=true \
  python3 scripts/benchmark_pipeline_capture.py capture-manifest.json --execute \
  > captured-output.json
```

## Blind analytical review

Analytical quality is evaluated from packets that expose an opaque output ID, the case question, the analysis and a rubric version—but reject model, provider, prompt, build, treatment, variant and memory identities, including nested metadata. Every output requires at least two distinct assigned reviewers. Submissions are bound to the exact assignment, reviewer, output and rubric version.

The fixed v1 dimensions are responsiveness, reasoning, materiality, counterarguments, uncertainty and usefulness, each scored from 1–5 with a required rationale and `pass`, `review`, or `fail` verdict. Reporting includes normalized analytical quality, pairwise dimension agreement within one rubric point, mean absolute score gap, verdict agreement, missing assignments and outputs requiring adjudication. Missing reviews, verdict disagreement, or a mean dimension gap above one leave the suite incomplete.

Score a prepared review bundle:

```bash
python3 scripts/benchmark_blind_review.py blind-review.json --require-complete
```

The offline layer does not reveal the mapping from opaque output IDs to source runs. That mapping and the blinding secret belong in a separately access-controlled coordinator; neither may be included in reviewer packets or scorecard artifacts.

## Paraphrase consistency

Each frozen paraphrase group binds semantically equivalent but textually distinct questions to one case, issuer, as-of boundary, and source snapshot. The runner supplies structured output signatures; this evaluator never guesses semantic equivalence from wording and never treats prose similarity as quality.

Every pair in a group is compared, not merely each variant against a favored baseline. Material inconsistencies include changed answer/abstain/clarify behavior, changed thesis direction, confidence movement beyond an explicit tolerance, missing or conflicting material claim signatures, changed source binding, and risk or catalyst overlap below an explicit floor. Harmless prose and ordering differences are ignored.

Run the offline evaluator with:

```bash
python3 scripts/benchmark_paraphrase_consistency.py paraphrases.json --require-consistent
```

The scorecard reports pair- and group-level consistency plus every material finding. Empty suites remain visibly unevaluated, and any material inconsistency can fail the CLI gate. Thresholds are recorded in the input rather than inferred or silently relaxed.

## Personalized research-memory A/B

Memory evaluation uses matched control and treatment runs with the same case, question, source snapshot, build, model, prompt and retrieval versions. The control must have memory disabled and cannot recall or apply any record. The treatment is the only arm with memory enabled, which isolates the incremental effect of account-owned research context.

Fixtures contain opaque memory IDs and labels, never transcript text. Synthetic data is the default. Explicitly consented benchmark data requires a consent reference; ordinary private user research is not admitted. Expected relevant records must be active, owned by the fixture account and scoped to the same ticker.

The scorecard reports analytical-quality lift, factual- and citation-integrity deltas, relevant recall, recall precision, unsupported personalization and privacy failures. Any cross-account recall, cross-ticker recall, unregistered record, applied stale/deleted record, applied irrelevant memory, unsupported personalized claim, or integrity regression blocks `safe_to_expand`. Negative analytical lift and missed recall remain visible without being mislabeled as privacy exposure.

Run the offline evaluator with:

```bash
python3 scripts/benchmark_memory_ab.py memory-ab.json --require-safe
```

An empty suite is never considered safe. Passing this structural evaluator does not authorize automatic transcript injection or broader rollout; production-equivalent owner isolation, deletion, latency, cost and limited-cohort quality gates remain required by the cross-conversation memory contract.

## Proactive-noticing event replay

Each replay joins a frozen synthetic account-owned thesis to a later public event, an explicit expected relevance/impact judgment, and any observed alert. The thesis must predate the event, the ticker must match, and the evaluator rejects non-synthetic owner identifiers. Expected assumption links and confidence-change ranges are frozen before scoring.

The scorecard measures relevant-event detection recall, alert precision, thesis-impact accuracy, timeliness, assumption-link recall/precision, noise, privacy exposure and look-ahead leakage. Alerts must bind to the frozen event source, target the correct owner and ticker, appear only after publication, stay inside the replay window, link only known assumptions, and keep confidence movement inside the adjudicated range. Missing material alerts, source errors, impact errors, privacy violations and pre-publication alerts fail closed. Late and duplicate alerts remain visible as usefulness/noise failures rather than being hidden in an average.

Run the offline evaluator with:

```bash
python3 scripts/benchmark_proactive_replay.py replay.json --require-safe
```

An empty replay suite is not safe to expand. Passing offline replay does not start monitoring or authorize user-facing alerts; live scheduling still requires cost limits, quotas, operator visibility, delivery deduplication and kill-switch verification.

## Protected subgroup scorecards

Each benchmark observation carries issuer metadata for market-cap tier, coverage tier, domicile, sector, profitability, evidence mode, reporting complexity and personalization mode. The scorecard evaluates explicitly configured protected groups against frozen metric thresholds, maximum gaps from the overall result, minimum observation counts and minimum distinct-issuer counts.

Overall averages never override subgroup evidence. A group with too few observations or issuers is `insufficient`, not passing. A group fails when a required metric is missing, breaches its absolute threshold, or regresses from the overall benchmark by more than the declared gap. Critical case failures—including fabricated material sources, privacy exposure and point-in-time leakage—remain launch blockers regardless of group averages.

Run the offline evaluator with:

```bash
python3 scripts/benchmark_subgroup_scorecard.py subgroups.json --require-pass
```

The launch gate may consume `subgroup_regression_count`, but this report also preserves insufficient groups and critical case failures separately so missing small-company evidence cannot be mistaken for acceptable performance.

## Shadow safety control plane

`validation.shadow_safety` is the admission boundary for a future benchmark scheduler. Its default policy is disabled and dry-run. It rejects non-synthetic account references, non-allowlisted capabilities, duplicate identifiers with changed payloads, work above declared cost ceilings, exhausted daily/account/issuer quotas, concurrency overflow and requests received while either kill switch is engaged.

Dry-run decisions reserve no job and incur no cost. An enabled non-dry-run policy may create a reservation, but this module cannot execute research, call a provider, write account-owned memory or send a notification. Timeout reaping and kill-switch cancellation release active capacity while preserving terminal audit state. Actual cost above the daily budget automatically engages a fail-closed kill switch.

The operator can validate a configuration without activating work:

```bash
python3 scripts/benchmark_shadow_safety.py shadow-policy.json --require-inert
```

Production scheduling remains blocked until a separately reviewed dry-run
scheduler integration and explicit rollout approval are designed and verified.

## Inert dry-run scheduler

`validation.shadow_scheduler` converts fixed synthetic schedules into
deterministic slot-bound request identifiers and evaluates a single
caller-supplied tick through the shadow safety boundary. It has no daemon,
system clock, database, provider, research, memory, delivery or notification
dependency. It rejects non-synthetic accounts, schedules faster than five
minutes, duplicate schedule identifiers, unbounded catch-up and every safety
policy where `dry_run` is false.

The command below produces a content-free audit plan and fails if any active
reservation appears:

```bash
python3 scripts/benchmark_shadow_scheduler.py schedule.json --require-inert
```

This integration does not authorize a cron trigger or live execution. The next
review must freeze synthetic fixture selection, verify a production-equivalent
dry-run deployment, and confirm zero provider calls, user-memory writes and
notifications before any broader scheduler capability is considered.

## Frozen dry-run rehearsal

`validation/shadow_schedule.v1.json` pins seven synthetic schedules to issuer
registry v1 and its exact content hash. The selection spans six sectors, the US
and Netherlands, and US GAAP/IFRS. Because the current registry contains only
mega/large-cap issuers, the manifest must state the `mid_cap` and `small_micro`
gaps; the rehearsal rejects attempts to hide either gap.

Run the same deterministic tick locally or in the deployment environment:

```bash
python3 scripts/benchmark_shadow_rehearsal.py \
  --at 2026-10-01T00:01:00Z
```

The rehearsal passes only when every decision is dry-run, active jobs and
reserved cost remain zero, and the isolated integration has no provider,
research, memory, delivery or notification dependency. This is deployment
evidence, not permission to enable live execution.

An authenticated administrator may invoke the same frozen check in a deployed
build with `POST /admin/benchmark-shadow/rehearsal`. The response exposes only
aggregate counts, hashes, declared coverage gaps and pass/fail checks; synthetic
account references, schedule identifiers and issuer identifiers are omitted.
The route neither requires nor writes benchmark database state and always
reports `execution_enabled=false`.

## Durable shadow state

Migration `0009_benchmark_shadow_state` adds three isolated operational tables: a mutable job head, an append-only hash-chained transition audit and a versioned global kill-switch record. The tables accept synthetic benchmark identifiers and operational metadata only; there are no prompt, question, answer, evidence or payload columns.

Claims and renewals use holder identity plus monotonic fence tokens so a restarted or delayed worker cannot complete work after its lease was superseded. Expired leases recover to `timed_out` exactly once and conservatively charge the full reserved cost. Request identifiers remain idempotent across sessions and deployments, while reuse with a changed fingerprint fails closed. Manual/automatic kill state uses version compare-and-swap and survives process restarts.

Retention cleanup is the only deletion path. It removes a terminal job and its transition chain only after `retention_until`; reserved or running jobs are never eligible. The state service imports no scheduler, provider, delivery or notification module and therefore cannot activate live work.

## Authenticated operator controls

The central `/admin/*` boundary and explicit handler-level administrator checks protect three benchmark endpoints: aggregate status, engage manual kill, and restore manual control. Mutations require the last observed control version; stale concurrent operators receive `409` rather than overwriting newer state. Every effective mutation appends a security audit row with the authenticated actor.

`POST /admin/benchmark-shadow/restore` clears only `manual_kill`. It never clears `automatic_kill`, cannot enable execution, and cannot create or claim a job. Status responses contain aggregate counts, costs, lease health and transition-integrity state but no synthetic account references, job identifiers, prompts, evidence or outputs.

## Provider cancellation boundary

Migration `0010_benchmark_cancellation` adds a content-free audit of
external cancellation attempts. It stores the provider name, job fence,
attempt number, bounded outcome and a SHA-256 operation-reference hash; it does
not store the provider operation reference, prompt, evidence, answer or output.

Cancellation is deliberately two-phase. The caller first commits a local
`cancelled` fence and transition, which prevents a delayed worker or provider
result from completing the job. Only after that commit may it call an injected
provider adapter with a maximum 30-second deadline. Rejection, timeout, adapter
error or an unverified result monotonically engages the automatic kill switch.
Provider calls use a durable single-flight claim; a concurrent caller observes
the in-progress state without issuing a duplicate call, while an expired claim
can be recovered after a process restart.
Retries append new attempts without reopening the job, and a later
acknowledgement never clears an existing automatic stop. This boundary imports
no live provider, scheduler, delivery or notification implementation.
