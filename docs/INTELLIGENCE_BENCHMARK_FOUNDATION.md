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
5. Add blind analytical-review assignment and agreement reporting.
6. Add paraphrase groups, memory A/B fixtures, proactive-event replay, and protected subgroup scorecards.
7. Add production-safe shadow scheduling only after cost limits, operator visibility, quotas, and kill switches are verified.

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
