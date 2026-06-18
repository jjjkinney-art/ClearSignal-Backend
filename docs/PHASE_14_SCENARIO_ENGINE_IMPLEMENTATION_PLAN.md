# Phase 14 — Scenario Engine Implementation Plan

Status: **plan only — no code, no implementation.**
Companion to `PHASE_14_SCENARIO_ENGINE_SPEC.md` (approved). Every slice below
traces back to a section of that spec. This plan defines *how* to build it
safely, slice by slice, with validation, rollback, and a **commit checkpoint
after every slice**.

> **Spec reconciliation note (resolved).** `PHASE_14_SCENARIO_ENGINE_SPEC.md`
> now exists in `docs/` and every `Spec ref` below has been reconciled against
> its real section numbers. The earlier placeholder references have been
> replaced. No slice may be built against a section number not confirmed against
> the committed spec.

> Process note (carried from Phases 11–13): Phases 11 and 12 were built
> correctly but sat uncommitted in the working tree, so production ran without
> them until a single late commit. Phase 13 fixed this with a mandatory
> `git commit` at the close of each slice. Phase 14 keeps that rule. No slice is
> "done" until it is committed and `safe_state: true` holds.

---

## 0. Guiding constraints (apply to every slice)

| Constraint | Enforcement |
|---|---|
| All flags default inert | `false/false/false/true/""/false` — verified by validation-script check |
| Shadow-first, no live scenario delivery | No surface reads scenarios; no public route; `scenario_delivery_enabled=false` |
| Conditional analysis only (SP-6) | A scenario is an *if→then→because* analysis. No prediction, recommendation, portfolio advice, or target price. No such column exists in schema; no-advice + no-target-price + no-prediction tests per slice |
| Transmission mechanism mandatory | Every scenario states an explicit cause→effect path; a scenario with no transmission path is never stored |
| Explainability or block | A scenario missing *what changed / why it matters / transmission / evidence / invalidators* is never stored |
| No duplicate intelligence | Phase 14 **consumes** 9G/10D/11/12/13 + cross-exposure; it re-derives no forecast, similarity, decision, or exposure signal of its own |
| No upstream mutation (SP-6) | Phase 14 is a pure sink; no `scenario_*` write to any upstream table; AST + before/after snapshot tests |
| Dependency direction (SP-6) | Phase 14 reads 9G/10D/11/12/13/cross-exposure; nothing in those phases reads `scenario_*`; no order/execution/conviction/stance import; AST check |
| Schema additive only | `014_scenario_engine.sql` is all `IF NOT EXISTS`; no `ALTER` on existing tables; 46 → 49 |
| Tenant isolation | User-tier scenarios strictly scoped by `user_id`; no cross-user read; isolation test |
| Null-session safe | Every async function returns an inert value on `session=None`; never raises |
| Committed before next slice | `git commit` at each slice close; `safe_state: true` held at every intermediate state |

Each slice is independently mergeable, reversible, and leaves `safe_state:
true`. No slice depends on a later slice to be safe.

**SP-6 (the Phase 14 invariant), stated once:** *Scenario output is a
conditional analysis. It must never predict an outcome, recommend an action,
size or advise on a position, or assert a target price. It must not import
order/execution/conviction/stance. It must not flow back into Memory,
Similarity, Forecasting, Decision Intelligence, Portfolio Intelligence, or
Cross Exposure.* SP-6 follows SP-4 (Phase 12 forecasting) and SP-5 (Phase 13
decision) and is enforced structurally, by AST scan, and by runtime
before/after snapshot in every slice that touches data.

---

## 1. Flags (introduced once, in Slice 14.1)

All six flags are added to `app/config.py` in Slice 14.1 so the inert defaults
exist before any consumer. Consumers are wired in later slices; until then each
flag reads its inert default, making every intermediate state safe. This mirrors
the Phase 13 six-flag shape exactly.

| Setting | Type | Default | First consumer slice |
|---|---|---|---|
| `scenario_build_enabled` | bool | `false` | 14.5 (assembly orchestration auto-build) |
| `scenario_evaluation_enabled` | bool | `false` | 14.5 (impact/transmission evaluation auto-run), 14.8 (shadow delivery gate) |
| `scenario_delivery_enabled` | bool | `false` | reserved; never consumed in Phase 14 (live delivery = post-build Stage 4) |
| `scenario_shadow` | bool | `true` | 14.8 (shadow journaling gate) |
| `scenario_targets_enabled` | str | `""` | 14.5 (scenario-seed eligibility allowlist) |
| `scenario_calibration_enabled` | bool | `false` | 14.9 (scenario-realization outcome logging gate) |

The seed builder, evaluation engine, and explainability service remain directly
callable regardless of flags (the Phase 11–13 convention): flags gate
*automatic* invocation and *shadow journaling*, not the pure functions.

---

## 2. Slice list (overview)

| Slice | Name | Spec ref | Net-new safe? |
|---|---|---|---|
| 14.1 | Schema + repository + flags | §3, §2.2, §2.3 | ✅ inert tables only |
| 14.2 | Scenario seed builder (six frameworks) | §4.2 | ✅ pure reads; writes nothing |
| 14.3 | Transmission + impact evaluation engine | §5 | ✅ pure analysis over upstream signals |
| 14.4 | Explainability + blocking gate (5 mandatory fields) | §6 | ✅ build-time gate, discards incomplete |
| 14.5 | Scenario assembly + run orchestration (first writer) | §8.3, §2.1 | ✅ flag-gated; no auto-run by default |
| 14.6 | Read service + admin routes | §12 | ✅ read-only, additive, global tier |
| 14.7 | Portfolio impact propagation (two-tier + isolation) | §7 | ✅ additive user tier; exposure propagation |
| 14.8 | Shadow scenario delivery | §9.2 | ✅ journal-only; no surface reads |
| 14.9 | Calibration + drift (scenario realization) | §8.1–8.2 | ✅ flag-gated outcome logging |
| 14.10 | Observability + validation script + rollout doc | §10.6, §11, §12 | ✅ read-only snapshot |

Live (user-visible) scenario delivery is **out of scope for the build phase** —
it is post-merge Stage 4, gated by the acceptance criteria in §10.

---

## 3. Slice detail

Each slice lists: scope, files created/modified, validation, rollback, commit
checkpoint.

---

### Slice 14.1 — Schema + Repository + Flags

**Scope**: Tables 47–49, ORM models, migration, repository, all six flags,
schema tests. No builder, no engine, no routes.

**Files created**
- `app/db/migrations/014_scenario_engine.sql` — tables 47–49, all
  `IF NOT EXISTS`, indexes, unique constraint on `scenario_snapshot
  (scenario_type, entity_type, entity_key, scenario_key, user_id)`. No `ALTER`
  on existing tables.
  - `scenario_snapshot` (47) — one row per evaluated scenario: `scenario_type`
    (macro / company / sector / catalyst / failure_mode / portfolio),
    `condition` (the "if"), `transmission_path`, `impact_assessment` (qualitative,
    bounded — **not** a price/return target), `plausibility_band`
    (qualitative: e.g. remote/plausible/likely-conditional — never a probability
    sold as a prediction), `what_changed`, `why_it_matters`, `invalidators`,
    `source_versions`, `scenario_schema`, `user_id`, `built_at`, `expires_at`.
  - `scenario_evidence` (48) — evidence items backing a snapshot (source ref,
    upstream phase, captured value, captured-at).
  - `scenario_run_log` (49) — **append-only** run/shadow/outcome log
    (`run_reason`, `snapshot_reason`, `realized_state`, `evaluated_at`). No
    update/delete path.
- `app/db/repositories/scenario_repo.py` — null-session-safe CRUD/upsert for
  `scenario_snapshot` and `scenario_evidence`; **insert-only** `add_run_log` for
  `scenario_run_log` (no update/delete path); windowed `list_run_logs` /
  `count_run_logs`.
- `tests/test_services/test_scenario_schema.py` — ~25 tests.

**Files modified**
- `app/db/models.py` — add `ScenarioSnapshot` (47), `ScenarioEvidence` (48),
  `ScenarioRunLog` (49) after the Phase 13 decision models. JSON columns via the
  existing `_json_col()` helper.
- `app/config.py` — add the six `scenario_*` flags with inert defaults.

**Validation**
- Schema tests: all three tables creatable; unique constraint enforced;
  null-session repo functions return `None/[]/0`; **no advice/size/price/target/
  prediction column exists** on any of the three tables; round-trip upsert/get
  for snapshot and evidence.
- Invariant test: `scenario_run_log` has no UPDATE/DELETE/merge path in
  `scenario_repo` (AST).
- `db_table_count >= 49` after `create_all`.
- AST: `scenario_repo` imports nothing from order/execution/conviction/stance.

**Rollback**: drop/truncate the three additive tables (nothing reads them yet);
revert the six config flags (no consumer exists). No existing behavior changes.

**Commit checkpoint**: `feat(14): Slice 14.1 — Scenario Engine schema, repo, flags` → push.

---

### Slice 14.2 — Scenario Seed Builder (six frameworks)

**Scope**: Enumerate scenario seeds from the existing substrate (spec §4). Pure
reads; returns seed objects with their `source_versions` snapshot. Writes
nothing. **Consumes existing intelligence — derives none of its own.**

**Files created**
- `app/services/scenario_seed_builder.py`
  - `build_seeds_for_entity(session, entity_type, entity_key)` and
    `build_seeds_for_user(session, user_id)` → assemble the six scenario
    frameworks from upstream phases (no re-derivation):
    - **macro** — from dated macro catalysts / regime signals (9G, 12).
    - **company** — from `forecast_vector` (12) + `decision_priority` (13) +
      thesis transitions (10A/12).
    - **sector** — from `similarity_edge` clusters (11) + shared exposure (10D).
    - **catalyst** — from dated catalysts (9G/12).
    - **failure_mode** — from `failure_mode` rows / risk candidates (10A/12/13).
    - **portfolio** — from portfolio positions/insights (10D) + cross-exposure.
  - Eligibility filter against `scenario_targets_enabled` (empty ⇒ nothing
    eligible ⇒ inert).
  - Captures `source_versions` per seed for staleness.
- `tests/test_services/test_scenario_seed_builder.py` — ~24 tests.

**Files modified**: none (pure new module).

**Validation**
- Each of the six frameworks assembled correctly from seeded substrate rows.
- Eligibility allowlist honored (empty ⇒ zero seeds).
- `source_versions` captured correctly.
- **No-duplication test**: the builder reads upstream signals and never
  recomputes a forecast, similarity edge, decision score, or exposure value
  (AST: it imports upstream *read* paths only; runtime: it emits no derived
  intelligence column).
- **No source-table mutation test**: before/after byte-identical across all read
  tables.
- AST: imports 9G/10D/11/12/13/cross-exposure repos/models (allowed); does NOT
  import order/execution/conviction/stance.
- Empty-substrate test: returns `[]`, never raises; null-session returns `[]`.

**Rollback**: delete module + test; no caller exists.

**Commit checkpoint**: `feat(14): Slice 14.2 — Scenario seed builder (six frameworks)` → push.

---

### Slice 14.3 — Transmission + Impact Evaluation Engine

**Scope**: The conditional-analysis core (spec §5). For each seed, construct the
**transmission path** (condition → mechanism → affected entities) and a bounded,
qualitative **impact assessment**. One parameterized model keyed by
`scenario_type`; pure analysis over upstream signals. **No prediction, no target
price, no return forecast** — impact is expressed as directional/qualitative
exposure, never a number sold as an outcome.

**Files created**
- `app/services/scenario_constants.py` — `SCENARIO_TRANSMISSION_CONFIG` (per
  `scenario_type` transmission templates and weighting), `PLAUSIBILITY_BANDS`
  (qualitative bands, §5.4), `IMPACT_BANDS` (qualitative directional bands, §5.2),
  `MANDATORY_DISCLAIMER` (verbatim conditional-analysis / no-advice line),
  `BANNED_ADVICE_PHRASES`, `BANNED_PREDICTION_PHRASES`, `BANNED_TARGET_PRICE_PHRASES`,
  `SCENARIO_SCHEMA_VERSION`.
- `app/services/scenario_evaluation_engine.py`
  - `build_transmission_path(seed)` → explicit cause→effect chain referencing
    real upstream conditions; empty path ⇒ flagged for the gate (14.4).
  - `assess_impact(seed, transmission)` → qualitative directional impact band
    (intrinsic; exposure propagation added in 14.7), bounded; never a price or
    return number.
  - `assess_plausibility(seed)` → qualitative band derived from upstream
    confidence/uncertainty (12) and corroborating evidence; **explicitly framed
    as conditional, not predictive**.
  - All outputs traceable to upstream contributions.
- `tests/test_services/test_scenario_evaluation_engine.py` — ~28 tests.

**Files modified**: none.

**Validation**
- **Determinism**: identical inputs + schema ⇒ identical transmission path,
  impact band, plausibility band, order.
- **Transmission completeness**: a seed with no derivable mechanism yields an
  empty path (which the 14.4 gate will block) — asserted here.
- **Conditional framing**: plausibility/impact are bands, never point
  predictions or prices; boundary tests assert no numeric target leaks into any
  field.
- Per-`scenario_type` weighting selects the right transmission template; it does
  **not** select a different engine (one parameterized model).
- No-advice + no-prediction + no-target-price string scan of the module +
  constants (data lists skipped).

**Rollback**: delete engine + constants + test; no caller.

**Commit checkpoint**: `feat(14): Slice 14.3 — Scenario transmission + impact evaluation` → push.

---

### Slice 14.4 — Explainability + Blocking Gate (five mandatory fields)

**Scope**: Construct and enforce the five mandatory explanation fields (spec §6):
**what changed**, **why it matters**, **transmission mechanism**, **evidence**,
**invalidators**. Pure; the writer in 14.5 calls the gate before upsert. Missing
any field blocks storage.

**Files created**
- `app/services/scenario_explainability_service.py`
  - `build_scenario_explanation(seed, evaluation)` → `what_changed` (the trigger
    condition), `why_it_matters` (the stakes), `transmission_path` (from 14.3),
    `evidence_summary` + `scenario_evidence` rows, and `invalidators` (named,
    falsifiable conditions that would void the scenario).
  - `validate_scenario_explanation(...)` → the gate: non-empty `what_changed`
    AND non-empty `why_it_matters` AND non-empty `transmission_path` AND ≥1
    `evidence` item AND ≥1 `invalidators`, else `False`.
- `tests/test_services/test_scenario_explainability_service.py` — ~20 tests.

**Files modified**: none.

**Validation**
- All five fields built correctly from an evaluated seed.
- Gate returns `False` for any missing field; incomplete scenarios are flagged
  (the discard path is asserted here and again in 14.5).
- `invalidators` are falsifiable statements referencing real upstream
  conditions.
- Transmission path is non-empty and references the cause→effect chain from 14.3.
- No-advice + no-prediction + no-target-price string scan; disclaimer constant
  present and verbatim.

**Rollback**: delete module + test; no caller.

**Commit checkpoint**: `feat(14): Slice 14.4 — Scenario explainability + blocking gate` → push.

---

### Slice 14.5 — Scenario Assembly + Run Orchestration (first writer)

**Scope**: The **first DB-writing slice**. Compose seed builder → evaluation →
explainability gate → `upsert_scenario_snapshot` + evidence + `add_run_log`.
Staleness detection and re-evaluation triggering. Flag-gated; no auto-run when
flags are inert. Builds the **global tier only** (`user_id = NULL`); the user
tier is added in 14.7.

**Files created**
- `app/services/scenario_assembly_service.py`
  - `assemble_scenarios_for_entity(session, entity_type, entity_key)` and
    `assemble_scenarios_for_target(...)` → enumerate seeds, evaluate, explain,
    **gate**, upsert surviving scenarios + evidence + a `scenario_run_log` row;
    discard blocked ones with a `blocked_explanation` log.
  - `mark_stale` / `find_stale` — `source_versions` behind upstream,
    `expires_at` passed, or `scenario_schema` changed.
  - Auto-build gated by `scenario_build_enabled` + `scenario_evaluation_enabled`
    + `scenario_targets_enabled`; default inert.
- `tests/test_services/test_scenario_assembly_service.py` — ~24 tests.

**Files modified**: none (writes via `scenario_repo`).

**Validation**
- End-to-end: seeded substrate → scenarios written with all five explanation
  fields; blocked scenarios discarded (assert the gate fires, no partial rows).
- Transmission + explainability invariants hold on every stored row.
- Staleness detection correct; re-evaluation updates in place; reads never
  trigger a rebuild (separation).
- Flags inert ⇒ zero writes (default state).
- **No upstream mutation** test: forecast/similarity/decision/portfolio/memory/
  cross-exposure tables byte-identical before/after an assembly run.
- AST: no conviction/order/execution/stance import; no upstream-write import.
- Null-session safe.

**Rollback**: truncate `scenario_snapshot` / `scenario_evidence` /
`scenario_run_log` assembly rows; delete service + test; flags stay inert. No
upstream change.

**Commit checkpoint**: `feat(14): Slice 14.5 — Scenario assembly + run orchestration (global tier)` → push.

---

### Slice 14.6 — Read Service + Admin Routes

**Scope**: Read-only access layer and admin routes (spec §12). Never builds or
re-evaluates. Global tier only (user-tier union added in 14.7).
Disclaimer-wrapped.

**Files created**
- `app/services/scenario_read_service.py`
  - `get_scenario_facet_for_entity(session, entity_type, entity_key)` →
    disclaimer-wrapped facet of global-tier scenarios, grouped by
    `scenario_type`.
  - `get_scenarios_for_user(session, user_id, *, limit)` → identity-scoped
    scenario set (global tier for now; union with user tier in 14.7).
  - Filters expired/invalid rows; never rebuilds.
- `tests/test_services/test_scenario_read_service.py` — ~16 tests.

**Files modified**
- `app/api.py` — add `GET /admin/scenario-status` (stub snapshot until 14.10),
  `GET /admin/scenario/{ticker}`, `GET /admin/scenarios` (query `user_id`). All
  `/admin/`-only; read-only; DB-down-safe.

**Validation**
- Facet shape: empty-state + populated; disclaimer present verbatim on facet and
  every item; **no advice/size/price/target/prediction field in any response**;
  every scenario item carries its transmission path and invalidators.
- Expired/invalid filtered; no rebuild on read (assert no write).
- Routes return safely; 404-free; DB-down degrades to empty facet, not 500.
- No public (non-`/admin/`) scenario route exists.

**Rollback**: remove the three admin routes; delete read service + test; no
schema/flag change.

**Commit checkpoint**: `feat(14): Slice 14.6 — Scenario read service + admin routes` → push.

---

### Slice 14.7 — Portfolio Impact Propagation (two-tier + tenant isolation)

**Scope**: Add the user-specific tier and exposure propagation (spec §7).
Company impact → portfolio impact → exposure propagation across holdings, using
Phase 10D portfolio intelligence and cross-exposure. Two-tier materialization
(global `user_id=NULL` + user tier); union/dedup in the read service; strict
tenant isolation. **Propagation expresses exposure pathways, not advice** — no
position sizing, no rebalancing recommendation.

**Files created**
- `app/services/scenario_portfolio_propagation.py`
  - `company_impact(session, scenario, entity_key)` → directional impact band on
    a single company (intrinsic).
  - `portfolio_impact(session, user_id, scenario)` → aggregate exposure pathway
    across the user's holdings (qualitative; bounded).
  - `propagate_exposure(session, user_id, scenario)` → cross-exposure
    propagation: which held entities are reached by the transmission path and
    how (via 10D + cross-exposure edges). Bounded to the user's holdings.
  - `assemble_user_scenarios(session, user_id)` → user-tier rows for entities the
    user touches, applying propagation; gated, additive.
- `tests/test_services/test_scenario_portfolio_propagation.py` — ~24 tests.

**Files modified**
- `app/services/scenario_evaluation_engine.py` — `assess_impact` accepts an
  optional propagation context (defaults to intrinsic-only for the global tier).
- `app/services/scenario_assembly_service.py` — add the user-tier build path
  (gated, additive).
- `app/services/scenario_read_service.py` — union user-tier over global-tier,
  dedup by `(scenario_type, entity_type, entity_key, scenario_key)`, user-tier
  wins.

**Validation**
- **Exposure propagation**: a transmission path that reaches a held entity
  surfaces a portfolio-tier scenario for that user; an unexposed user sees only
  the global-tier scenario.
- **No advice leak**: propagation output names exposure pathways and magnitudes
  (qualitative) but never a recommended action, size, or rebalancing step
  (no-advice test on the propagation surface).
- **Tenant isolation**: a user-tier scenario is never readable under a different
  `user_id`; `SYSTEM_DEFAULT_USER_ID` baseline is global-tier only.
- Unexposed user falls back to global tier; union/dedup correct.
- Propagation is bounded to the transmission path — it does not invent edges
  absent from 10D / cross-exposure (AST + runtime: reads exposure, derives none).

**Rollback**: truncate user-tier rows (`user_id IS NOT NULL`); revert the three
modified services to their global-tier form; delete the new module + test. Global
tier unaffected.

**Commit checkpoint**: `feat(14): Slice 14.7 — Scenario portfolio impact propagation (two-tier, isolation)` → push.

---

### Slice 14.8 — Shadow Scenario Delivery

**Scope**: Journal the surfacing/promotion the engine *would* apply to delivery
surfaces — to `scenario_run_log` only (spec §9). No surface reads it.
Transition/snapshot based; no live notification; no surface mutation.

**Files created**
- `app/services/scenario_delivery_service.py`
  - `journal_shadow_scenarios(session, user_id)` → compute the surfaced set,
    append `scenario_run_log` rows (`snapshot_reason`, transition type); write to
    nothing else.
  - Gated by `scenario_evaluation_enabled` + `scenario_shadow`;
    `scenario_delivery_enabled` reserved/unused. Inert by default.
- `tests/test_services/test_scenario_delivery_service.py` — ~20 tests.

**Files modified**: none.

**Validation**
- Shadow journaling writes only `scenario_run_log`; no Notification row, no
  inbox/alert/briefing/watchlist/portfolio surface mutation (before/after
  snapshot).
- Idempotent / no churn-spam: re-journaling an unchanged scenario set does not
  duplicate (dedup or no-op).
- Flags inert ⇒ no journaling.
- AST: no order/execution/conviction import; no surface-write import.
- Null-session safe.

**Rollback**: delete `scenario_run_log` shadow rows; delete service + test; no
surface ever read it.

**Commit checkpoint**: `feat(14): Slice 14.8 — Scenario shadow delivery` → push.

---

### Slice 14.9 — Calibration + Drift (scenario realization)

**Scope**: Scenario-quality measurement (spec §8.1–8.2). The primary question: *did
scenarios flagged plausible, with their stated transmission path, actually
materialize?* Flag-gated outcome attribution via append-only log rows. **Not a
prediction scorecard** — it measures whether the *conditional analysis and its
invalidators held*, not whether a point forecast was right.

**Files created**
- `app/services/scenario_calibration_service.py`
  - `record_scenario_outcome(...)` → append a `scenario_run_log` row with
    `realized_state` (materialized / invalidated / unresolved) when a scenario's
    condition resolves. Immutable; never updates an existing row.
  - `compute_realization_agreement(...)` → concordance between
    `plausibility_band` and realized state over a rolling window (primary
    metric).
  - `compute_transmission_accuracy(...)` → when a scenario materialized, did the
    affected entities match the stated transmission path?
  - `compute_invalidator_hit_rate(...)` → how often a stated invalidator was the
    actual reason a scenario did not materialize (the explanation was honest).
  - `compute_stability_churn(...)` → snapshot-to-snapshot scenario set movement
    for unchanged inputs.
  - `detect_scenario_drift(...)` → windowed `improving/worsening/stable/
    insufficient_samples` on realization agreement.
  - Gated by `scenario_calibration_enabled`.
- `tests/test_services/test_scenario_calibration_service.py` — ~20 tests.

**Files modified**: none.

**Validation**
- Immutable append-only logging (AST: no update/delete; runtime: new row per
  outcome).
- Realization agreement, transmission accuracy, and invalidator hit-rate
  computed correctly on seeded outcomes.
- **No prediction-scorecard framing**: the service exposes
  realization/transmission/invalidator metrics, not a point-forecast accuracy
  headline (asserted).
- Churn within bound on a static-input fixture; high churn flagged on a
  jittered fixture.
- Drift classification correct; `insufficient_samples` below the minimum.
- Flags inert ⇒ no logging. Null-session safe.

**Rollback**: truncate calibration-origin `scenario_run_log` outcome rows;
delete service + test; flags stay inert.

**Commit checkpoint**: `feat(14): Slice 14.9 — Scenario calibration + drift (realization)` → push.

---

### Slice 14.10 — Observability + Validation Script + Rollout Doc

**Scope**: Full observability snapshot, standalone validation script, rollout
documentation. Slice 14.10 = Phase 14 build complete.

**Files created**
- `app/services/scenario_observability_service.py`
  - `build_scenario_observability_snapshot(session)` → flags (all 6),
    db_available, scenario_count (+ by `scenario_type`, by plausibility band,
    global vs user tier), evidence_count, run_log_count, expired_count,
    realization_agreement, transmission_accuracy, invalidator_hit_rate,
    churn_metric, drift_state, shadow_journal_count, shadow_escalated_count,
    live_notification_count, latest_built_at, `safe_state`, snapshot_utc.
  - `safe_state = scenario_shadow=true AND scenario_delivery_enabled=false AND
    shadow_escalated_count=0 AND live_notification_count=0 AND no advice/target/
    prediction field present`. Read-only, DB-down-safe; channel literal
    duplicated, not imported (Phase 11–13 pattern).
- `tests/test_services/test_scenario_observability_service.py` — ~16 tests.
- `tests/validate_14_scenario_engine_shadow.py` — shadow validation script
  (§10.6), exit 0/1.
- `docs/PHASE_14_SCENARIO_ENGINE_SHADOW_ROLLOUT.md` — env vars, local +
  production validation, internal probe procedure, rollout stages, rollback,
  no-advice / no-target-price / no-prediction / SP-6 boundaries, acceptance
  criteria.

**Files modified**
- `app/api.py` — re-point `GET /admin/scenario-status` to
  `scenario_observability_service.build_scenario_observability_snapshot`.

**Validation**
- Snapshot: empty-DB shape, populated counts, DB-down degradation, `safe_state`
  true/false combinations, no-secret-leakage, flags section types, tier split.
- Validation script: all checks pass locally (exit 0), including no-advice,
  no-target-price, no-prediction, no-conviction-import, no-upstream-write,
  transmission-path-present, portfolio-propagation, tenant isolation, run-log
  immutability, `db_table_count >= 49`, tables 47–49 exist, `safe_state: true`
  (DB-down + DB-up).
- Full regression: `tests/test_services/test_scenario_*.py` all pass.

**Rollback**: re-point the route to the 14.6 stub snapshot; delete observability
service + script + doc. No schema/flag change.

**Commit checkpoint**: `feat(14): Slice 14.10 — Scenario observability + validation + rollout (Phase 14 complete)` → push.

---

## 4. Scenario framework build plan (cross-slice, spec §4–5)

The six scenario types are **not** six engines. They are **one parameterized
model** (Slice 14.3) — a single transmission-and-impact evaluator parameterized
by a versioned config keyed by `scenario_type`. Build order within the engine:

1. `build_transmission_path` — cause→effect chain from upstream conditions
   (same function for all six types; the config supplies the template and the
   eligible upstream sources).
2. `assess_impact` — qualitative directional band (intrinsic; exposure
   propagation added in 14.7).
3. `assess_plausibility` — qualitative band from upstream confidence/uncertainty
   and corroboration, **framed as conditional**.
4. Propagation term (Slice 14.7): `portfolio_impact = propagate(intrinsic_impact,
   exposure_paths)`; the propagation is the **only** per-user term, defaulting to
   intrinsic-only for the global tier.

| scenario_type | primary upstream sources | per-user? |
|---|---|---|
| `macro` | macro catalysts / regime (9G, 12) | via propagation onto holdings |
| `company` | forecast (12), decision (13), thesis transitions (10A/12) | via propagation onto holdings |
| `sector` | similarity clusters (11), shared exposure (10D) | via propagation onto holdings |
| `catalyst` | dated catalysts (9G/12) | via propagation onto holdings |
| `failure_mode` | failure modes / risk candidates (10A/12/13) | via propagation onto holdings |
| `portfolio` | portfolio positions/insights (10D) + cross-exposure | yes (inherently per-user) |

`scenario_type` selects the transmission template and eligible sources; it does
**not** select a different engine. Adding a scenario type later is a config row,
not an engine rewrite.

---

## 5. Explainability gate (cross-slice, spec §6)

Enforced at the point of storage, in Slice 14.5's assembly orchestration, using
Slice 14.4's `validate_scenario_explanation`. A scenario is stored only if **all
five** mandatory fields are present:

- `what_changed` non-empty, AND
- `why_it_matters` non-empty, AND
- `transmission_path` non-empty (an explicit cause→effect mechanism), AND
- ≥1 `scenario_evidence` row, AND
- ≥1 `invalidators` (falsifiable conditions that would void the scenario).

Any scenario failing the gate is discarded with a `blocked_explanation` log,
never written. Verified by the discard test in 14.4 and 14.5 and by the
validation-script explainability check. **A scenario with no transmission
mechanism is, by definition, not a scenario — it is blocked.**

---

## 6. Portfolio impact propagation plan (cross-slice, spec §7)

| Concern | Slice | Mechanism |
|---|---|---|
| Company impact (global) | 14.3 | intrinsic directional band, `user_id = NULL` |
| Portfolio impact | 14.7 | aggregate exposure pathway across the user's holdings |
| Exposure propagation | 14.7 | cross-exposure edges (10D + cross-exposure) reached by the transmission path |
| User-tier build | 14.7 | bounded to the user's holdings |
| Two-tier union/dedup | 14.7 | read service unions user over global; user wins |
| Tenant isolation | 14.7 | `user_id` scoping; no cross-user read |
| No advice leak | 14.7 | propagation names pathways/magnitude, never an action/size/rebalance |

Variation by user flows through **one** path (`portfolio_impact`'s propagation
term). No other field is per-user. This keeps the per-user surface small,
testable, and auditable — and keeps Phase 14 strictly on the conditional-analysis
side of SP-6.

---

## 7. Calibration plan (cross-slice, spec §8.1–8.2) — realization, not prediction

Scenario calibration measures whether **conditional analyses held**, not whether
a point forecast was accurate. Phase 12's Brier score and Phase 13's rank-order
agreement are **not** the Phase 14 metric.

| Metric | Slice | What it answers |
|---|---|---|
| Realization agreement | 14.9 | Did plausible-flagged scenarios materialize more than remote-flagged ones? (primary) |
| Transmission accuracy | 14.9 | When a scenario materialized, did the affected entities match the stated path? |
| Invalidator hit-rate | 14.9 | When a scenario did not materialize, was a stated invalidator the reason? (honesty of the explanation) |
| Stability / churn | 14.9 | Do scenario sets flicker for unchanged inputs? |
| Drift | 14.9 | Is realization agreement worsening / improving / stable? |
| Surfacing | 14.10 | All of the above in `/admin/scenario-status` |

Outcome attribution is append-only to `scenario_run_log` (immutable, like Phase
12/13 calibration). Calibration is vacuous on first deploy (cold-start), as
expected; no live delivery until §10 acceptance criteria are met.

---

## 8. Delivery plan (cross-slice, spec §9)

Phase 14 ships **shadow-only** scenario surfacing (Slice 14.8). The consumption
surfaces (inbox, alerts, briefings, company facet, portfolio intelligence) are
documented in the spec but only the shadow journaling is built — the surfaced set
is written to `scenario_run_log` and read by **no** surface. Live
surfacing/promotion of real surfaces (`scenario_delivery_enabled=true`) is **out
of scope for the build phase** and is gated, per-surface and reversible, behind
the acceptance criteria below.

---

## 9. Rollout stages (post-merge, spec §11)

| Stage | Flag change | Effect | Monitor |
|---|---|---|---|
| 0 — Delivered | none | All inert; tables empty; `safe_state: true` | `/admin/scenario-status` |
| 1 — Shadow build + evaluation | `SCENARIO_BUILD_ENABLED=true`, `SCENARIO_EVALUATION_ENABLED=true`, `SCENARIO_TARGETS_ENABLED=company` | Global-tier scenarios build/evaluate; no delivery | scenario_count; block-rate; safe_state |
| 2 — Shadow surfacing + calibration | `SCENARIO_CALIBRATION_ENABLED=true` (shadow stays true) | Shadow surfacing journaled; outcomes attributed | realization agreement; transmission accuracy; drift `stable/improving`; shadow_escalated_count=0 |
| 3 — Portfolio (user-tier) shadow | `SCENARIO_TARGETS_ENABLED=company,sector,portfolio` | User-tier scenarios build; propagation validated on live shadow data | exposure propagation correctness; isolation |
| 4 — Live surfacing (user-visible) | **out of scope (build phase)** — `SCENARIO_DELIVERY_ENABLED=true` behind per-surface gate | Scenarios surface on real surfaces | acceptance criteria §10 + human sign-off |

Each stage is reversible by setting the flag back to its default.

---

## 10. Acceptance criteria (Phase 14 build complete → Stage 4 eligible)

Before any live-surfacing (Stage 4) gate may be opened:

1. `tests/validate_14_scenario_engine_shadow.py` exits 0 in production.
2. `/admin/scenario-status` reports `safe_state: true`, `shadow_escalated_count:
   0`, `live_notification_count: 0`.
3. All `tests/test_services/test_scenario_*.py` pass (every slice).
4. `scenario_count > 0` after Stage 1 for 24h+; explainability block-rate within
   the expected band; **every stored scenario has a non-empty transmission path
   and ≥1 invalidator**.
5. Scenario stability: churn within bound over 7+ days of shadow snapshots.
6. Calibration: realization agreement above a defined floor; transmission
   accuracy and invalidator hit-rate within targets; drift `stable`/`improving`
   over the most recent window.
7. Portfolio propagation: exposure pathways demonstrated against live shadow
   data; tenant isolation holds; no advice/size/rebalance leak.
8. **No advice/size/price/target/prediction field anywhere** in any response
   (`/admin/` and non-`/admin/`); no-advice, no-target-price, and no-prediction
   tests green.
9. SP-6 verified: AST confirms no `scenario_*` module imports order/execution/
   conviction/stance, and no scenario output writes back to memory/similarity/
   forecast/decision/portfolio/cross-exposure.
10. Human sign-off on transmission-path and invalidator quality, and on the
    per-surface delivery gate plan.

---

## 11. Per-slice rollback summary

| Slice | Rollback |
|---|---|
| 14.1 | Drop 3 tables; revert 6 config flags; no behavior change |
| 14.2 | Delete seed builder + test; no caller |
| 14.3 | Delete evaluation engine + constants + test; no caller |
| 14.4 | Delete explainability + test; no caller |
| 14.5 | Truncate `scenario_snapshot`/`scenario_evidence`/`scenario_run_log`; delete service + test; flags stay off |
| 14.6 | Remove 3 admin routes; delete read service + test; no schema/flag change |
| 14.7 | Truncate user-tier rows; revert 3 services to global-tier form; delete module + test |
| 14.8 | Delete shadow `scenario_run_log` rows; delete service + test |
| 14.9 | Truncate calibration outcome rows; delete service + test; flags stay off |
| 14.10 | Re-point route to 14.6 stub snapshot; delete observability + script + doc |

Every rollback is local to its slice and requires no schema revert beyond
optionally dropping the three additive tables (which nothing outside Phase 14
reads).

---

## 12. Files summary

**Created across Phase 14**
- `app/db/migrations/014_scenario_engine.sql`
- `app/db/repositories/scenario_repo.py`
- `app/services/scenario_seed_builder.py`
- `app/services/scenario_evaluation_engine.py`
- `app/services/scenario_constants.py`
- `app/services/scenario_explainability_service.py`
- `app/services/scenario_assembly_service.py`
- `app/services/scenario_read_service.py`
- `app/services/scenario_portfolio_propagation.py`
- `app/services/scenario_delivery_service.py`
- `app/services/scenario_calibration_service.py`
- `app/services/scenario_observability_service.py`
- `tests/test_services/test_scenario_schema.py`
- `tests/test_services/test_scenario_seed_builder.py`
- `tests/test_services/test_scenario_evaluation_engine.py`
- `tests/test_services/test_scenario_explainability_service.py`
- `tests/test_services/test_scenario_assembly_service.py`
- `tests/test_services/test_scenario_read_service.py`
- `tests/test_services/test_scenario_portfolio_propagation.py`
- `tests/test_services/test_scenario_delivery_service.py`
- `tests/test_services/test_scenario_calibration_service.py`
- `tests/test_services/test_scenario_observability_service.py`
- `tests/validate_14_scenario_engine_shadow.py`
- `docs/PHASE_14_SCENARIO_ENGINE_SHADOW_ROLLOUT.md`

**Modified across Phase 14**
- `app/db/models.py` (tables 47–49; Slice 14.1)
- `app/config.py` (six flags; Slice 14.1)
- `app/api.py` (three `/admin/` routes; Slice 14.6, route re-pointed 14.10)
- `app/services/scenario_evaluation_engine.py` (propagation term; Slice 14.7)
- `app/services/scenario_assembly_service.py` (user-tier path; Slice 14.7)
- `app/services/scenario_read_service.py` (two-tier union; Slice 14.7)

No existing service, model field, or route outside Phase 14 changes behavior.
Every modification is additive.

---

## 13. Estimated test count

| Slice | Tests |
|---|---|
| 14.1 | ~25 |
| 14.2 | ~24 |
| 14.3 | ~28 |
| 14.4 | ~20 |
| 14.5 | ~24 |
| 14.6 | ~16 |
| 14.7 | ~24 |
| 14.8 | ~20 |
| 14.9 | ~20 |
| 14.10 | ~16 + validation script |

Phase 14 total: **~217 unit tests + 1 shadow validation script.**

Commit cadence: **10 commits, one per slice**, each leaving `safe_state: true`
and the suite green — no repeat of the Phase 11/12 uncommitted-working-tree gap.

---

## 14. Dependency map (what Phase 14 reads — and the SP-6 one-way wall)

Phase 14 is a **pure downstream sink**. It reads, never writes back.

```
        Memory (9G) ┐
     Similarity (11)│
    Forecasting (12)├──read──▶  Scenario Engine (14)  ──write──▶  scenario_snapshot
Decision Intel (13)│              (seeds → transmission →           scenario_evidence
   Portfolio (10D) │               impact → explainability →        scenario_run_log
  Cross Exposure   ┘               gate → shadow journal)
                                          │
                                          └── reads back into 9G/10D/11/12/13/
                                              cross-exposure?  ❌ NEVER (SP-6)
```

- **Consumes, never duplicates** (Req 5): no forecast, similarity edge, decision
  score, or exposure value is recomputed inside Phase 14 — it reads the
  materialized upstream value and cites it as evidence.
- **One-way dependency** (SP-6 / Req 3): nothing in 9G/10D/11/12/13/cross-exposure
  imports or reads `scenario_*`. Enforced by AST in 14.2, 14.5, 14.7, and the
  14.10 validation script.
- **No live coupling**: the only write targets are the three additive Phase 14
  tables; the only "delivery" in the build phase is the shadow `scenario_run_log`
  journal that no surface reads.
