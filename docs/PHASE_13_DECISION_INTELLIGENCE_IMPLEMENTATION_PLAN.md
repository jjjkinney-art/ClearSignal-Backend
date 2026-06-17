# Phase 13 — Decision Intelligence Implementation Plan

Status: **plan only — no code, no implementation.**
Companion to `PHASE_13_DECISION_INTELLIGENCE_SPEC.md` (approved). Every slice
below traces back to a section of that spec. This plan defines *how* to build
it safely, slice by slice, with validation, rollback, and a **commit checkpoint
after every slice**.

> Process note (carried from the Phase 11/12 deployment investigation): Phases
> 11 and 12 were built correctly but sat uncommitted in the working tree for an
> extended period, so production ran without them until a single late commit.
> Phase 13 fixes this by mandating a `git commit` at the close of each slice
> (§0, and the *Commit checkpoint* line in every slice). No slice is "done"
> until it is committed.

---

## 0. Guiding constraints (apply to every slice)

| Constraint | Enforcement |
|---|---|
| All flags default inert | `false/false/""/true/false/false` — verified by validation script check |
| Shadow-first, no live prioritization | No surface reads the ranking; no public route; `decision_delivery_enabled=false` |
| Prioritizes information only | No advice/size/price/trade column exists in schema; no-advice + no-trade tests per slice |
| No conviction / forecast mutation | Phase 13 is a pure sink; no `decision_*` write to any upstream table; AST + before/after snapshot tests |
| Dependency direction (SP-5) | Phase 13 reads 9G/10/11/12; nothing in 9G–12 reads `decision_*`; no order/execution/conviction/stance import; AST check |
| Schema additive only | `013_decision_intelligence.sql` is all `IF NOT EXISTS`; no `ALTER` on existing tables; 43 → 46 |
| Explainability or block | A priority with empty reason/why-now/deprioritizers/evidence is never stored |
| Tenant isolation | User-tier rows strictly scoped by `user_id`; no cross-user read; isolation test |
| Null-session safe | Every async function returns inert value on `session=None`; never raises |
| Committed before next slice | `git commit` at each slice close; `safe_state: true` held at every intermediate state |

Each slice is independently mergeable, reversible, and leaves `safe_state:
true`. No slice depends on a later slice to be safe.

---

## 1. Flags (introduced once, in Slice 13.1)

All six flags are added to `app/config.py` in Slice 13.1 so the inert defaults
exist before any consumer. Consumers are wired in later slices; until then the
flags read their inert default, making every intermediate state safe.

| Setting | Type | Default | First consumer slice |
|---|---|---|---|
| `decision_build_enabled` | bool | `false` | 13.5 (rebuild orchestration auto-build) |
| `decision_scoring_enabled` | bool | `false` | 13.5 (scoring auto-run via rebuild), 13.8 (shadow delivery gate) |
| `decision_targets_enabled` | str | `""` | 13.5 (candidate eligibility allowlist) |
| `decision_shadow` | bool | `true` | 13.8 (shadow journaling gate) |
| `decision_calibration_enabled` | bool | `false` | 13.9 (ranking-outcome logging gate) |
| `decision_delivery_enabled` | bool | `false` | reserved; never consumed in Phase 13 (live delivery = post-build Stage 4) |

The candidate builder, scoring engine, and explainability service remain
directly callable regardless of flags (same convention as Phases 11–12): flags
gate *automatic* invocation and *shadow journaling*, not the pure functions.

---

## 2. Slice list (overview)

| Slice | Name | Spec ref | Net-new safe? |
|---|---|---|---|
| 13.1 | Schema + repository + flags | §3, §2.2, §2.3 | ✅ inert tables only |
| 13.2 | Candidate builder | §4.2 | ✅ pure reads; writes nothing |
| 13.3 | Scoring engine (one parameterized model) | §5 | ✅ pure math + versioned weight config |
| 13.4 | Explainability + blocking gate | §6 | ✅ build-time gate, discards incomplete |
| 13.5 | Invalidation + rebuild orchestration (first writer) | §8.3, §2.1 | ✅ flag-gated; no auto-run by default |
| 13.6 | Read service + admin routes | §12 | ✅ read-only, additive, global tier |
| 13.7 | Portfolio-awareness (two-tier + isolation) | §7 | ✅ additive user tier; exposure multiplier |
| 13.8 | Shadow ranking delivery | §9.2 | ✅ journal-only; no surface reads |
| 13.9 | Calibration + drift (rank-order, churn) | §8.1–8.2 | ✅ flag-gated outcome logging |
| 13.10 | Observability + validation script + rollout doc | §10.6, §11, §12 | ✅ read-only snapshot |

Live (user-visible) delivery is **out of scope for the build phase** — it is
post-merge Stage 4 (§9), gated by the acceptance criteria in §10.

---

## 3. Slice detail

Each slice lists: scope, files created/modified, validation, rollback, commit
checkpoint.

---

### Slice 13.1 — Schema + Repository + Flags

**Scope**: Tables 44–46, ORM models, migration, repository, all six flags,
schema tests. No builder, no engine, no routes.

**Files created**
- `app/db/migrations/013_decision_intelligence.sql` — tables 44–46, all
  `IF NOT EXISTS`, indexes, unique constraint on `decision_priority
  (candidate_type, entity_type, entity_key, source_ref, user_id)`. No `ALTER`
  on existing tables.
- `app/db/repositories/decision_repo.py` — null-session-safe CRUD/upsert for
  `decision_priority` and `decision_evidence`; **insert-only** `add_ranking_log`
  for `decision_ranking_log` (no update/delete path); windowed
  `list_ranking_logs` / `count_ranking_logs`.
- `tests/test_services/test_decision_schema.py` — ~25 tests.

**Files modified**
- `app/db/models.py` — add `DecisionPriority` (44), `DecisionEvidence` (45),
  `DecisionRankingLog` (46) after the Phase 12 forecast models. JSON columns via
  the existing `_json_col()` helper.
- `app/config.py` — add the six `decision_*` flags with inert defaults.

**Validation**
- Schema tests: all three tables creatable; unique constraint enforced;
  null-session repo functions return `None/[]/0`; **no advice/size/price/trade
  column exists** on any of the three tables; round-trip upsert/get for priority
  and evidence.
- Invariant test: `decision_ranking_log` has no UPDATE/DELETE/merge path in
  `decision_repo` (AST).
- `db_table_count >= 46` after `create_all`.
- AST: `decision_repo` imports nothing from order/execution/conviction/stance/
  forecast-write modules.

**Rollback**: drop/truncate the three additive tables (nothing reads them yet);
revert the six config flags (no consumer exists). No existing behavior changes.

**Commit checkpoint**: `feat(13): Slice 13.1 — Decision Intelligence schema, repo, flags` → push.

---

### Slice 13.2 — Candidate Builder

**Scope**: Enumerate attention candidates from the substrate (spec §4.2). Pure
reads; returns candidate objects with their `source_versions` snapshot. Writes
nothing.

**Files created**
- `app/services/decision_candidate_builder.py`
  - `build_candidates_for_entity(session, entity_type, entity_key)` and
    `build_candidates_for_user(session, user_id)` → assemble the seven candidate
    types (forecast / risk / catalyst / watchlist_item / portfolio_exposure /
    thesis_transition / similarity_match) from `forecast_vector` (12),
    `failure_mode`/thesis transitions (10A/12), dated catalysts (9G/12),
    `watched_tickers` (10B), portfolio positions/insights (10D),
    `similarity_edge` (11).
  - Eligibility filter against `decision_targets_enabled` (empty ⇒ nothing
    eligible ⇒ inert).
  - Captures `source_versions` per candidate for staleness.
- `tests/test_services/test_decision_candidate_builder.py` — ~22 tests.

**Files modified**: none (pure new module).

**Validation**
- Each candidate type assembled correctly from seeded substrate rows.
- Eligibility allowlist honored (empty ⇒ zero candidates).
- `source_versions` captured correctly.
- **No source-table mutation test**: before/after byte-identical across all read
  tables.
- AST: imports 9G/10/11/12 repos/models (allowed); does NOT import order/
  execution/conviction/stance.
- Empty-substrate test: returns `[]`, never raises; null-session returns `[]`.

**Rollback**: delete module + test; no caller exists.

**Commit checkpoint**: `feat(13): Slice 13.2 — Decision candidate builder` → push.

---

### Slice 13.3 — Scoring Engine (one parameterized ranking model)

**Scope**: One parameterized ranking model (spec §5). **Not** seven engines —
a single composite over five component scores, parameterized by a versioned
weight config keyed by `candidate_type`. Pure math; returns a scored object.

**Files created**
- `app/services/decision_constants.py` — `DECISION_WEIGHT_CONFIG` (per
  `candidate_type` `w_a/w_u/w_i`), `UNCERTAINTY_LAMBDA`, `BUCKET_THRESHOLDS`
  (§5.3), `EXPOSURE_MULTIPLIER` params (floor/cap, consumed in 13.7),
  `MANDATORY_DISCLAIMER` (verbatim no-advice line), `BANNED_ADVICE_PHRASES`,
  `DECISION_SCHEMA_VERSION`.
- `app/services/decision_scoring_engine.py`
  - Five component functions: `score_attention`, `score_urgency`,
    `score_impact` (intrinsic; exposure multiplier defaults to floor 1.0 here —
    user tier added in 13.7), `score_confidence`, `score_uncertainty`. Each
    bounded [0,1], each emitting traceable contributions.
  - `compute_decision_rank_score` — `raw = Σ w·score`; multiply by
    `confidence_score`; discount by `(1 − λ·uncertainty_score)`; `clamp01`.
  - `bucket_priority` — threshold map to `critical/high/medium/low/
    informational`.
- `tests/test_services/test_decision_scoring_engine.py` — ~28 tests.

**Files modified**: none.

**Validation**
- **Determinism**: identical inputs + schema ⇒ identical scores/order.
- **Monotonicity**: raising any single positive input never lowers
  `decision_rank_score` (others fixed).
- **Damping**: `confidence_score` is a multiplier (cannot inflate raw);
  `uncertainty_score` is a discount (cannot inflate); both unit-tested at
  boundaries.
- **Bucket consistency**: bucket always matches the score threshold.
- Component functions: each returns correct values from seeded upstream;
  uniform/empty fallback never raises.
- `confidence` and `uncertainty` are independent (not complements).
- No-advice string scan of the module + constants (data list skipped).

**Rollback**: delete engine + constants + test; no caller.

**Commit checkpoint**: `feat(13): Slice 13.3 — Decision scoring engine (parameterized)` → push.

---

### Slice 13.4 — Explainability + Blocking Gate

**Scope**: Construct `decision_reason` (why important), `why_now` (why now),
`evidence_summary` + `decision_evidence` rows, and `deprioritizers` (what would
reduce importance). Enforce the blocking gate (spec §6). Pure; the writer in
13.5 calls the gate before upsert.

**Files created**
- `app/services/decision_explainability_service.py`
  - `build_decision_explanation(candidate, scored)` → reason from the dominant
    dimension + top evidence; `why_now` from the dominant urgency driver;
    `deprioritizers` as named, falsifiable conditions; condensed
    `evidence_summary`.
  - `validate_decision_explanation(...)` → the gate: non-empty `decision_reason`
    AND non-empty `why_now` AND ≥1 `deprioritizers` AND ≥1 evidence item, else
    `False`.
- `tests/test_services/test_decision_explainability_service.py` — ~18 tests.

**Files modified**: none.

**Validation**
- Reason/why-now/deprioritizers/evidence built correctly from a scored
  candidate.
- Gate returns `False` for any missing field; incomplete explanations are
  flagged (the discard path is asserted here and again in 13.5).
- `deprioritizers` are falsifiable statements referencing real upstream
  conditions.
- No-advice string scan; disclaimer constant present and verbatim.

**Rollback**: delete module + test; no caller.

**Commit checkpoint**: `feat(13): Slice 13.4 — Decision explainability + blocking gate` → push.

---

### Slice 13.5 — Invalidation + Rebuild Orchestration (first writer)

**Scope**: The **first DB-writing slice**. Compose builder → scoring →
explainability gate → `upsert_decision_priority` + evidence. Staleness detection
and re-rank triggering. Flag-gated; no auto-run when flags are inert. Builds the
**global tier only** (`user_id = NULL`); the user tier is added in 13.7.

**Files created**
- `app/services/decision_invalidation_service.py`
  - `rebuild_priorities_for_entity(session, entity_type, entity_key)` and
    `rebuild_priorities_for_target(...)` → enumerate candidates, score, explain,
    **gate**, upsert surviving priorities + evidence; discard blocked ones with a
    `blocked_explanation` log.
  - `mark_stale` / `find_stale` — `source_versions` behind upstream,
    `expires_at` passed, or `decision_schema` changed.
  - Auto-build gated by `decision_build_enabled` + `decision_scoring_enabled` +
    `decision_targets_enabled`; default inert.
- `tests/test_services/test_decision_invalidation_service.py` — ~22 tests.

**Files modified**: none (writes via `decision_repo`).

**Validation**
- End-to-end: seeded substrate → priorities written with full explanation;
  blocked candidates discarded (assert the gate fires, no partial rows).
- Score + explainability invariants hold on every stored row.
- Staleness detection correct; re-rank updates in place; reads never trigger a
  rebuild (separation).
- Flags inert ⇒ zero writes (default state).
- **No upstream mutation** test: forecast/similarity/memory/portfolio tables
  byte-identical before/after a rebuild.
- AST: no conviction/forecast-write/order import.
- Null-session safe.

**Rollback**: truncate `decision_priority` / `decision_evidence`; delete service
+ test; flags stay inert. No upstream change.

**Commit checkpoint**: `feat(13): Slice 13.5 — Decision invalidation + rebuild (global tier)` → push.

---

### Slice 13.6 — Read Service + Admin Routes

**Scope**: Read-only access layer and admin routes (spec §12). Never builds or
re-ranks. Global tier only (user-tier union added in 13.7). Disclaimer-wrapped.

**Files created**
- `app/services/decision_read_service.py`
  - `get_decision_facet_for_entity(session, entity_type, entity_key)` →
    disclaimer-wrapped facet of global-tier priorities, sorted by
    `decision_rank_score` desc.
  - `get_decision_ranking_for_user(session, user_id, *, limit)` → identity-
    scoped ranked set (global tier for now; union with user tier in 13.7).
  - Filters expired/invalid rows; never rebuilds.
- `tests/test_services/test_decision_read_service.py` — ~16 tests.

**Files modified**
- `app/api.py` — add `GET /admin/decision-status` (stub snapshot until 13.10),
  `GET /admin/decision/{ticker}`, `GET /admin/decisions` (query `user_id`). All
  `/admin/`-only; read-only; DB-down-safe.

**Validation**
- Facet shape: empty-state + populated; disclaimer present verbatim on facet and
  every item; **no advice/size/price/trade field in any response**.
- Expired/invalid filtered; no rebuild on read (assert no write).
- Routes return safely; 404-free; DB-down degrades to empty facet, not 500.
- No public (non-`/admin/`) decision route exists.

**Rollback**: remove the three admin routes; delete read service + test; no
schema/flag change.

**Commit checkpoint**: `feat(13): Slice 13.6 — Decision read service + admin routes` → push.

---

### Slice 13.7 — Portfolio-Awareness (two-tier + tenant isolation)

**Scope**: Add the user-specific tier (spec §7). Exposure multiplier on
`impact_score`; two-tier materialization (global `user_id=NULL` + user tier);
union/dedup in the read service; strict tenant isolation; no systemic-risk
suppression.

**Files created**
- `app/services/decision_portfolio_awareness.py`
  - `exposure_multiplier(session, user_id, entity_type, entity_key)` → derived
    from Phase 10D exposure; floor (no exposure ⇒ intrinsic only) to cap
    (material exposure ⇒ scaled, capped).
  - `rebuild_user_priorities(session, user_id)` → user-tier rows for entities the
    user touches, applying the multiplier; bounded to portfolio holdings.
- `tests/test_services/test_decision_portfolio_awareness.py` — ~22 tests.

**Files modified**
- `app/services/decision_scoring_engine.py` — `score_impact` accepts an
  `exposure_multiplier` (defaults to floor 1.0 for the global tier).
- `app/services/decision_invalidation_service.py` — add the user-tier build path
  (gated, additive).
- `app/services/decision_read_service.py` — union user-tier over global-tier,
  dedup by `(candidate_type, entity_type, entity_key)`, user-tier wins.

**Validation**
- **Exposure lift**: the same candidate ranks higher for an exposed user than an
  unexposed user.
- **No tunnel vision**: a high-intrinsic global priority is never ranked below a
  low-intrinsic user-tier priority by exposure alone.
- **Tenant isolation**: a user-tier row is never readable under a different
  `user_id`; `SYSTEM_DEFAULT_USER_ID` baseline is global-tier only.
- Unexposed user falls back to global tier; union/dedup correct.
- Multiplier floor keeps systemic risks alive; cap bounds amplification.

**Rollback**: truncate user-tier rows (`user_id IS NOT NULL`); revert the three
modified services to their global-tier form; delete the new module + test. Global
tier unaffected.

**Commit checkpoint**: `feat(13): Slice 13.7 — Decision portfolio-awareness (two-tier, isolation)` → push.

---

### Slice 13.8 — Shadow Ranking Delivery

**Scope**: Journal the ordering/promotion the engine *would* apply to the
delivery surfaces — to `decision_ranking_log` only (spec §9.2). No surface reads
it. Transition/snapshot based; no live notification; no surface mutation.

**Files created**
- `app/services/decision_ranking_service.py`
  - `journal_shadow_ranking(session, user_id)` → compute the ranked set, append
    `decision_ranking_log` rows (`snapshot_reason`, `rank_position`); write to
    nothing else.
  - Gated by `decision_scoring_enabled` + `decision_shadow`; `decision_delivery_
    enabled` reserved/unused. Inert by default.
- `tests/test_services/test_decision_ranking_service.py` — ~20 tests.

**Files modified**: none.

**Validation**
- Shadow journaling writes only `decision_ranking_log`; no Notification row, no
  inbox/alert/briefing/watchlist/portfolio surface mutation (before/after
  snapshot).
- Idempotent / no churn-spam: re-journaling an unchanged ranking does not
  duplicate (dedup or no-op).
- Flags inert ⇒ no journaling.
- AST: no order/execution/conviction import; no surface-write import.
- Null-session safe.

**Rollback**: delete `decision_ranking_log` shadow rows; delete service + test;
no surface ever read it.

**Commit checkpoint**: `feat(13): Slice 13.8 — Decision shadow ranking delivery` → push.

---

### Slice 13.9 — Calibration + Drift (rank-order, churn, prominence)

**Scope**: Ranking-quality measurement (spec §8). **Not Brier** — the primary
metric is rank-order agreement, plus stability/churn and prominence-error
counts. Flag-gated outcome attribution via append-only log rows.

**Files created**
- `app/services/decision_calibration_service.py`
  - `record_ranking_outcome(...)` → append a `decision_ranking_log` row with
    `realized_significance` (material/immaterial/unknown) when a subject resolves
    (forecast calibrates / risk materializes-or-lapses / catalyst passes).
    Immutable; never updates an existing row.
  - `compute_rank_order_agreement(...)` → concordance between
    `decision_rank_score` and realized significance over a rolling window
    (primary metric).
  - `compute_stability_churn(...)` → snapshot-to-snapshot `rank_position`
    movement for unchanged inputs.
  - `compute_prominence_errors(...)` → **false prominence** (high-priority →
    immaterial) and **missed importance** (low-priority → material) counts.
  - `detect_ranking_drift(...)` → windowed `improving/worsening/stable/
    insufficient_samples` on agreement.
  - Gated by `decision_calibration_enabled`.
- `tests/test_services/test_decision_calibration_service.py` — ~18 tests.

**Files modified**: none.

**Validation**
- Immutable append-only logging (AST: no update/delete; runtime: new row per
  outcome).
- Rank-order agreement computed correctly on seeded outcomes; **Brier is not the
  primary metric** (asserted: the service exposes agreement/churn/prominence, not
  a Brier headline).
- Churn within bound on a static-input fixture; high churn flagged on a
  jittered fixture.
- False-prominence and missed-importance counts correct.
- Drift classification correct; `insufficient_samples` below the minimum.
- Flags inert ⇒ no logging. Null-session safe.

**Rollback**: truncate calibration-origin `decision_ranking_log` outcome rows;
delete service + test; flags stay inert.

**Commit checkpoint**: `feat(13): Slice 13.9 — Decision calibration + drift (rank-order)` → push.

---

### Slice 13.10 — Observability + Validation Script + Rollout Doc

**Scope**: Full observability snapshot, standalone validation script, rollout
documentation. Slice 13.10 = Phase 13 build complete.

**Files created**
- `app/services/decision_observability_service.py`
  - `build_decision_observability_snapshot(session)` → flags (all 6),
    db_available, priority_count (+ by candidate_type, by bucket, global vs user
    tier), evidence_count, ranking_log_count, expired_count,
    rank_order_agreement, churn_metric, false_prominence_count,
    missed_importance_count, drift_state, shadow_journal_count,
    shadow_escalated_count, live_notification_count, latest_built_at,
    `safe_state`, snapshot_utc.
  - `safe_state = decision_shadow=true AND decision_delivery_enabled=false AND
    shadow_escalated_count=0 AND live_notification_count=0 AND no advice field
    present`. Read-only, DB-down-safe; channel literal duplicated, not imported
    (Phase 11/12 pattern).
- `tests/test_services/test_decision_observability_service.py` — ~14 tests.
- `tests/validate_13_decision_intelligence_shadow.py` — shadow validation script
  (§10.6), exit 0/1.
- `docs/PHASE_13_DECISION_INTELLIGENCE_SHADOW_ROLLOUT.md` — env vars, local +
  production validation, internal probe procedure, rollout stages, rollback,
  no-advice / no-trade / SP-5 boundaries, acceptance criteria.

**Files modified**
- `app/api.py` — re-point `GET /admin/decision-status` to
  `decision_observability_service.build_decision_observability_snapshot`.

**Validation**
- Snapshot: empty-DB shape, populated counts, DB-down degradation, `safe_state`
  true/false combinations, no-secret-leakage, flags section types, tier split.
- Validation script: all checks pass locally (exit 0), including no-advice,
  no-trade, no-conviction-import, no-forecast-write, ranking monotonicity,
  damping, portfolio-awareness, tenant isolation, log immutability,
  `db_table_count >= 46`, tables 44–46 exist, `safe_state: true` (DB-down + DB-up).
- Full regression: `tests/test_services/test_decision_*.py` all pass.

**Rollback**: re-point the route to the 13.6 stub snapshot; delete observability
service + script + doc. No schema/flag change.

**Commit checkpoint**: `feat(13): Slice 13.10 — Decision observability + validation + rollout (Phase 13 complete)` → push.

---

## 4. Ranking model build plan (cross-slice, spec §5)

The seven candidate types are **not** seven engines. They are **one
parameterized model** (Slice 13.3) — a single composite over five component
scores, parameterized by a versioned weight config keyed by `candidate_type`.
Build order within the engine:

1. Five component functions: `score_attention`, `score_urgency`, `score_impact`
   (intrinsic), `score_confidence`, `score_uncertainty` — each independently
   unit-tested with uniform/empty fallback.
2. Composite: `raw = w_a·attention + w_u·urgency + w_i·impact`, then
   `× confidence_score`, then `× (1 − λ·uncertainty_score)`, `clamp01`.
3. Bucketing: fixed thresholds → `critical/high/medium/low/informational`.
4. Portfolio term (Slice 13.7): `impact_score = clamp01(intrinsic_impact ×
   exposure_multiplier)`; the multiplier is the **only** per-user term, defaulting
   to floor 1.0 for the global tier.

`candidate_type` selects the weight row (a `risk` weights urgency higher; a
`portfolio_exposure` weights impact higher); it does **not** select a different
engine. Adding a candidate type later is a config row, not an engine rewrite.

| candidate_type | dominant weight | per-user? |
|---|---|---|
| `forecast` | impact × confidence | via exposure on impact |
| `risk` | urgency × impact | via exposure on impact |
| `catalyst` | impact × proximity (urgency) | via exposure on impact |
| `watchlist_item` | attention × urgency | global unless held |
| `portfolio_exposure` | impact (exposure-weighted) | yes |
| `thesis_transition` | attention | global unless held |
| `similarity_match` | attention (edge weight) | global unless held |

---

## 5. Explainability gate (cross-slice, spec §6)

Enforced at the point of storage, in Slice 13.5's rebuild orchestration, using
Slice 13.4's `validate_decision_explanation`. A priority is stored only if:

- `decision_reason` non-empty, AND
- `why_now` non-empty, AND
- `deprioritizers` non-empty (≥1, falsifiable), AND
- ≥1 `decision_evidence` row, AND
- all five component scores ∈ [0,1] and `decision_rank_score` bucket-consistent.

Any priority failing the gate is discarded with a `blocked_explanation` log,
never written. Verified by the discard test in 13.4 and 13.5 and by the
validation-script explainability check.

---

## 6. Portfolio-awareness plan (cross-slice, spec §7)

| Concern | Slice | Mechanism |
|---|---|---|
| Intrinsic (global) priorities | 13.5 | `user_id = NULL`, exposure multiplier = floor 1.0 |
| Exposure multiplier | 13.7 | derived from Phase 10D exposure; floor → cap |
| User-tier build | 13.7 | bounded to the user's holdings |
| Two-tier union/dedup | 13.7 | read service unions user over global; user wins |
| Tenant isolation | 13.7 | `user_id` scoping; no cross-user read |
| No systemic-risk suppression | 13.7 | floor keeps high-intrinsic global rows alive |

Variation by user flows through **one** term (`impact_score`'s exposure
multiplier). No other score is per-user. This keeps the per-user surface small,
testable, and auditable.

---

## 7. Calibration plan (cross-slice, spec §8) — not Brier

Decision calibration measures **ranking quality**, not probability accuracy.
Phase 12's Brier score is **not** the main metric.

| Metric | Slice | What it answers |
|---|---|---|
| Rank-order agreement | 13.9 | Did high-priority items turn out more material than low-priority ones? (primary) |
| Priority stability / churn | 13.9 | Do rankings flicker for unchanged inputs? |
| False prominence | 13.9 | How often did a high-priority item turn out immaterial? |
| Missed importance | 13.9 | How often did a low-priority item turn out material? |
| Drift | 13.9 | Is rank-order agreement worsening / improving / stable? |
| Surfacing | 13.10 | All of the above in `/admin/decision-status` |

Outcome attribution is append-only to `decision_ranking_log` (immutable, like
Phase 12 calibration). Calibration is vacuous on first deploy (cold-start), as
expected; no live delivery until §10 acceptance criteria are met.

---

## 8. Delivery plan (cross-slice, spec §9)

Phase 13 ships **shadow-only** ranking (Slice 13.8). The consumption surfaces
(inbox, alerts, briefings, watchlist, portfolio intelligence) are documented in
spec §9.1 but only the shadow journaling is built — the ranking is written to
`decision_ranking_log` and read by **no** surface. Live ordering/promotion of
real surfaces (`decision_delivery_enabled=true`) is **out of scope for the build
phase** and is gated, per-surface and reversible, behind the acceptance criteria
below.

---

## 9. Rollout stages (post-merge, spec §11)

| Stage | Flag change | Effect | Monitor |
|---|---|---|---|
| 0 — Delivered | none | All inert; tables empty; `safe_state: true` | `/admin/decision-status` |
| 1 — Shadow build + scoring | `DECISION_BUILD_ENABLED=true`, `DECISION_SCORING_ENABLED=true`, `DECISION_TARGETS_ENABLED=company` | Global-tier priorities build/score; no delivery | priority_count; block-rate; safe_state |
| 2 — Shadow ranking + calibration | `DECISION_CALIBRATION_ENABLED=true` (shadow stays true) | Shadow rankings journaled; outcomes attributed | rank-order agreement; churn; drift `stable/improving`; shadow_escalated_count=0 |
| 3 — Portfolio (user-tier) shadow | `DECISION_TARGETS_ENABLED=company,portfolio` | User-tier priorities build; portfolio-awareness validated on live shadow data | exposure lift; no tunnel vision; isolation |
| 4 — Live delivery (user-visible) | **out of scope (build phase)** — `DECISION_DELIVERY_ENABLED=true` behind per-surface gate | Rankings order/promote real surfaces | acceptance criteria §10 + human sign-off |

Each stage is reversible by setting the flag back to its default.

---

## 10. Acceptance criteria (Phase 13 build complete → Stage 4 eligible)

Before any live-delivery (Stage 4) gate may be opened:

1. `tests/validate_13_decision_intelligence_shadow.py` exits 0 in production.
2. `/admin/decision-status` reports `safe_state: true`, `shadow_escalated_count:
   0`, `live_notification_count: 0`.
3. All `tests/test_services/test_decision_*.py` pass (every slice).
4. `priority_count > 0` after Stage 1 for 24h+; explainability block-rate within
   the expected band.
5. Ranking stability: churn within bound over 7+ days of shadow snapshots.
6. Calibration: rank-order agreement above a defined floor; drift
   `stable`/`improving` over the most recent window; false-prominence and
   missed-importance within targets.
7. Portfolio-awareness: exposure lift demonstrated, no tunnel-vision
   suppression, tenant isolation holds — all against live shadow data.
8. No advice/size/price/trade field anywhere in any response (`/admin/` and
   non-`/admin/`); no-trade and no-advice tests green.
9. SP-5 verified: AST confirms no `decision_*` module imports order/execution/
   conviction/stance, and no decision output writes back to forecast/similarity/
   memory/calibration.
10. Human sign-off on reason quality and the per-surface delivery gate plan.

---

## 11. Per-slice rollback summary

| Slice | Rollback |
|---|---|
| 13.1 | Drop 3 tables; revert 6 config flags; no behavior change |
| 13.2 | Delete candidate builder + test; no caller |
| 13.3 | Delete scoring engine + constants + test; no caller |
| 13.4 | Delete explainability + test; no caller |
| 13.5 | Truncate `decision_priority`/`decision_evidence`; delete service + test; flags stay off |
| 13.6 | Remove 3 admin routes; delete read service + test; no schema/flag change |
| 13.7 | Truncate user-tier rows; revert 3 services to global-tier form; delete module + test |
| 13.8 | Delete shadow `decision_ranking_log` rows; delete service + test |
| 13.9 | Truncate calibration outcome rows; delete service + test; flags stay off |
| 13.10 | Re-point route to 13.6 stub snapshot; delete observability + script + doc |

Every rollback is local to its slice and requires no schema revert beyond
optionally dropping the three additive tables (which nothing outside Phase 13
reads).

---

## 12. Files summary

**Created across Phase 13**
- `app/db/migrations/013_decision_intelligence.sql`
- `app/db/repositories/decision_repo.py`
- `app/services/decision_candidate_builder.py`
- `app/services/decision_scoring_engine.py`
- `app/services/decision_constants.py`
- `app/services/decision_explainability_service.py`
- `app/services/decision_invalidation_service.py`
- `app/services/decision_read_service.py`
- `app/services/decision_portfolio_awareness.py`
- `app/services/decision_ranking_service.py`
- `app/services/decision_calibration_service.py`
- `app/services/decision_observability_service.py`
- `tests/test_services/test_decision_schema.py`
- `tests/test_services/test_decision_candidate_builder.py`
- `tests/test_services/test_decision_scoring_engine.py`
- `tests/test_services/test_decision_explainability_service.py`
- `tests/test_services/test_decision_invalidation_service.py`
- `tests/test_services/test_decision_read_service.py`
- `tests/test_services/test_decision_portfolio_awareness.py`
- `tests/test_services/test_decision_ranking_service.py`
- `tests/test_services/test_decision_calibration_service.py`
- `tests/test_services/test_decision_observability_service.py`
- `tests/validate_13_decision_intelligence_shadow.py`
- `docs/PHASE_13_DECISION_INTELLIGENCE_SHADOW_ROLLOUT.md`

**Modified across Phase 13**
- `app/db/models.py` (tables 44–46; Slice 13.1)
- `app/config.py` (six flags; Slice 13.1)
- `app/api.py` (three `/admin/` routes; Slice 13.6, route re-pointed 13.10)
- `app/services/decision_scoring_engine.py` (exposure term; Slice 13.7)
- `app/services/decision_invalidation_service.py` (user-tier path; Slice 13.7)
- `app/services/decision_read_service.py` (two-tier union; Slice 13.7)

No existing service, model field, or route outside Phase 13 changes behavior.
Every modification is additive.

---

## 13. Estimated test count

| Slice | Tests |
|---|---|
| 13.1 | ~25 |
| 13.2 | ~22 |
| 13.3 | ~28 |
| 13.4 | ~18 |
| 13.5 | ~22 |
| 13.6 | ~16 |
| 13.7 | ~22 |
| 13.8 | ~20 |
| 13.9 | ~18 |
| 13.10 | ~14 + validation script |

Phase 13 total: **~205 unit tests + 1 shadow validation script.**

Commit cadence: **10 commits, one per slice**, each leaving `safe_state: true`
and the suite green — no repeat of the Phase 11/12 uncommitted-working-tree gap.
