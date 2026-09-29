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
2. Add append-only local artifact writing for manifests, outputs, scorecards, and ledger entries, using atomic creation and duplicate-run rejection.
3. Add point-in-time source adapters and leakage audits.
4. Add factual/citation graders calibrated against adjudicated examples.
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
