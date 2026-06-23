# Phase 15 — User Learning Implementation Plan

**Phase:** 15 · User Learning & Personalization
**Status:** Plan — implementation not started
**Source of truth:** `docs/PHASE_15_USER_LEARNING_SPEC.md` (approved)
**Safety invariant family:** **SP-7** (spec §1.2)
**Scope:** Plan only. No code, no migrations, no implementation in this document.

---

## 0. How to read this plan

Phase 15 ships as **11 independently shippable slices**. The discipline is identical to Phases 13–14, which are already production-shadow validated:

- **Every slice ships behind inert flags.** Merging a slice changes nothing a user sees. Shipping is always a safe no-op until a flag is deliberately turned on in a later rollout stage.
- **Every slice is independently testable.** Each carries its own pytest suite (SQLite in-memory, null-session contract, AST safety checks). A slice is not "done" until its suite and the cumulative suite are green.
- **Every slice is independently reversible.** Because the data model is *additive only* (four new tables, zero `ALTER` on any source table) and every behavior is flag-gated, reverting a slice is a `git revert` with no data migration and no recompute.
- **Commit checkpoint after each slice**, message `feat(15): Slice 15.N — <name>`, mirroring the Phase 14 commit cadence.

> **Grounding note.** This plan invents no new release machinery. It reuses the proven Phase 14 pattern: additive model classes (no source-table `ALTER`), inert-default flags, per-service AST firewalls, an append-only run/shadow journal, a mandatory explanation-field gate, a `safe_state` observability snapshot + admin route, and a standalone `validate_NN_*_shadow.py` script. Each slice below names the Phase 14 artifact it is modeled on.

---

## 1. Slice overview

| Slice | Name | Unlocks (flag) | Serves stage | Depends on |
|---|---|---|---|---|
| **15.1** | Schema + Flags | — (all flags land inert) | 0 | — |
| **15.2** | Repositories | — | 0 | 15.1 |
| **15.3** | Signal Capture | `learning_capture_enabled` | 1 | 15.2 |
| **15.4** | Explainability Gate | — | 2 | 15.2 |
| **15.5** | Learning Inference | `learning_inference_enabled` | 2 | 15.3, 15.4 |
| **15.6** | Preference Decay & Falsification | — | 2 | 15.5 |
| **15.7** | Interest Profile & Priorities | — | 2 | 15.5, 15.6 |
| **15.8** | Relevance Engine | `learning_relevance_enabled` | 3 | 15.7 |
| **15.9** | Relevance Shadow Journal | `learning_shadow` | 3 | 15.8 |
| **15.10** | Preference Calibration | — | 4 | 15.5, 15.9 |
| **15.11** | Observability + Shadow Validation | — | 4 | all |

`learning_explicit_prefs_enabled` (explicit user preferences) and `learning_delivery_enabled` (Stage 5 go-live) are configuration switches, not slices — both land inert in 15.1 and are exercised by 15.3/15.5 (explicit) and 15.8/15.9 (delivery) respectively.

### 1.1 Dependency graph

```
15.1 Schema+Flags
   └─▶ 15.2 Repositories
          ├─▶ 15.3 Signal Capture ──────────────┐
          └─▶ 15.4 Explainability Gate ─────────┤
                                                ▼
                                       15.5 Learning Inference
                                          ├─▶ 15.6 Decay & Falsification
                                          └─▶ 15.7 Profile & Priorities
                                                     └─▶ 15.8 Relevance Engine
                                                            └─▶ 15.9 Relevance Shadow Journal
                                                                   └─▶ 15.10 Preference Calibration
                                                                          └─▶ 15.11 Observability + Validation
```

The two halves — the **learning pipeline** (15.3→15.7) and the **relevance pipeline** (15.8→15.9) — communicate only through the additive tables, never through in-process calls (spec §2.2, principle #8). Either half can be disabled without breaking the other.

---

## 2. Per-slice detail

Each card states: **Objective · Adds · Likely files · Flags · Validation (slice tests) · Rollback · SP-7 enforced · Commit.**

---

### Slice 15.1 — Schema + Flags

**Objective.** Land the four additive tables and the six inert flags. Nothing executes; this is pure structure.

**Adds.** Four SQLAlchemy model classes (continuing global numbering; current head = 49):

| # | Table | Kind |
|---|---|---|
| 50 | `user_signal_event` | append-only raw behavioral stream |
| 51 | `learned_preference` | current-state belief (status-mutable, decayable) |
| 52 | `preference_evidence` | insert-only evidence per belief |
| 53 | `relevance_adjustment_log` | append-only shadow journal |

Six flags, all default inert: `learning_capture_enabled=False`, `learning_inference_enabled=False`, `learning_relevance_enabled=False`, `learning_shadow=True`, `learning_delivery_enabled=False`, `learning_explicit_prefs_enabled=False`.

**Likely files.** `app/db/models.py` (4 new classes, **zero edits to existing tables**); `app/config.py` (6 flags + doc comments in the SP-7 style); `tests/test_services/test_user_learning_schema.py`.

**Validation (slice tests).** Tables instantiate; columns/enums/indexes/unique-constraints match spec §4; `user_id` is non-nullable on all four; round-trip insert/select on SQLite; flags exist and default inert; **DB table count == 53**.

**Rollback.** `git revert`. No source table touched ⇒ no `ALTER` to undo, no data migration.

**SP-7 enforced.** SP-7a/b at the structural level — the only write targets introduced are the four Phase 15 tables; nothing references a truth table for write.

**Commit.** `feat(15): Slice 15.1 — Schema + Flags`

---

### Slice 15.2 — Repositories

**Objective.** Provide the insert/upsert/query surface for the four tables, with the immutability contracts baked in.

**Adds.** A `user_learning_repo.py` with: `add_signal_event` (insert-only), `list_signal_events` (windowed, filterable), `count_signal_events`; `upsert_learned_preference` (one row per `(user_id, dimension, entity_key)`), `list_learned_preferences`, `set_preference_status` (status-only mutation), `count_learned_preferences`; `add_preference_evidence` (insert-only), `list_preference_evidence`; `add_relevance_adjustment` (insert-only), `list_relevance_adjustments`, `count_relevance_adjustments`. All honor the null-session contract.

**Likely files.** `app/db/repositories/user_learning_repo.py`; `tests/test_repositories/test_user_learning_repo.py`.

**Validation (slice tests).** Each insert-only function never updates an existing row (verified by AST: no `.update`/`UPDATE` path on event/evidence/log tables, mirroring `add_run_log`); `upsert_learned_preference` is idempotent on its unique key; `set_preference_status` changes only `status`/timestamps; null-session returns `[]`/`None`/`0`; ordering (`occurred_at`/`evaluated_at` desc) deterministic.

**Rollback.** `git revert`. No callers yet ⇒ inert.

**SP-7 enforced.** SP-7a (append-only event/evidence/log; status-only mutation on preference); import firewall test asserts the repo imports **no** truth-write repository.

**Commit.** `feat(15): Slice 15.2 — Repositories`

---

### Slice 15.3 — Signal Capture

**Objective.** Normalize and append behavioral events. The Stage-1 capability.

**Adds.** `user_signal_capture_service` with `record_signal_event(...)` (typed signal_type/polarity/entity; captures `surface_was_personalized` + `pre_personalization_rank` for unbiased learning — spec §4.1 principle #10) and a `record_explicit_preference(...)` path gated by `learning_explicit_prefs_enabled`. Flag-gated on `learning_capture_enabled`; returns `None` without writing when the gate is off (the `_delivery_approved`-style pattern from Phase 14).

**Likely files.** `app/services/user_signal_capture_service.py`; `tests/test_services/test_user_signal_capture_service.py`. (Event emission from existing surfaces — feed/alert/search/portfolio — is wired in Stage 1 ops, not in this slice; the service accepts events from any caller.)

**Flags.** `learning_capture_enabled` (capture), `learning_explicit_prefs_enabled` (explicit path).

**Validation (slice tests).** Gate off ⇒ zero rows written, returns `None`; gate on ⇒ exactly one row per call with correct polarity/entity mapping; unsupported `signal_type` rejected (no row); `user_id=None` rejected (anonymous behavior is never learned — spec §4.1); null-session safe.

**Rollback.** `git revert` or set `learning_capture_enabled=False` — the stream stops; existing rows are harmless (read by nothing until 15.5).

**SP-7 enforced.** SP-7a/b (writes only `user_signal_event`); reads no truth table.

**Commit.** `feat(15): Slice 15.3 — Signal Capture`

---

### Slice 15.4 — Explainability Gate

**Objective.** Build and validate the four mandatory explanation fields. This lands **before** inference because inference must pass every preference through the gate (spec §8, SP-7g).

**Adds.** `user_learning_explainability_service` with `build_preference_explanation(...)` → `{belief_basis, evidence_refs, signal_strength_label, falsifier}` and `validate_preference_explanation(...)` → `(ok, reason)`. A preference failing any of the four fields is rejected and may never reach `active` (the analogue of Phase 14's 5-field scenario explanation gate).

**Likely files.** `app/services/user_learning_explainability_service.py`; `tests/test_services/test_user_learning_explainability_service.py`.

**Validation (slice tests).** All four fields required and well-formed; `falsifier` must state a checkable observable (unfalsifiable ⇒ reject — principle #4); `evidence_refs` must be ≥ `MIN_EVENTS[dimension]` and resolvable; `signal_strength_label ∈ {strong, moderate, tentative}` consistent with confidence; pure functions (no DB) ⇒ fast unit tests; **banned-phrase AST scan** (no buy/sell/hold/target-price/position-size in any string constant).

**Rollback.** `git revert`. No persistence path yet ⇒ inert.

**SP-7 enforced.** SP-7g (mandatory explanation), SP-7f (banned-phrase scan).

**Commit.** `feat(15): Slice 15.4 — Explainability Gate`

---

### Slice 15.5 — Learning Inference

**Objective.** The periodic pass: events → evidence-backed preferences, across all seven dimensions, with the threshold-before-assertion guarantee.

**Adds.** `user_learning_inference_service.run_inference_pass(...)`: window events → map to `(dimension, entity_key)` via a versioned `preference_schema` → aggregate with recency-decayed weight → **threshold gate** (`MIN_EVENTS`/`MIN_CONFIDENCE`; below ⇒ `unresolved`, invisible to relevance — SP-7e) → **explainability gate** (15.4) → `upsert_learned_preference` + `add_preference_evidence`. Idempotent; never runs inline on a request. Supports the seven dimensions: `sector_interest`, `company_interest`, `theme_interest`, `preferred_horizon`, `preferred_signal_type`, `ignored_signal_type`, `portfolio_sensitivity`.

**Likely files.** `app/services/user_learning_inference_service.py`; `tests/test_services/test_user_learning_inference_service.py`. (Theme extraction reads `theme_clusters` (9G) **read-only** — open question §13.2 of spec, resolved here as read-only.)

**Flags.** `learning_inference_enabled` (gate; off ⇒ no preferences written).

**Validation (slice tests).** Sub-threshold evidence ⇒ `unresolved`, never `active` (no-fabrication); each of the seven dimensions extracted from the right signal types; idempotent re-run produces no duplicate evidence; preference rejected when explanation invalid; portfolio interactions produce `portfolio_sensitivity` only — **never** a recommendation (SP-7f AST scan); read-only on `theme_clusters`/`forecast_vector`/`scenario_snapshot` (import firewall); null-session safe.

**Rollback.** `git revert` or `learning_inference_enabled=False` — preferences stop being produced; existing rows read by nothing until 15.7/15.8.

**SP-7 enforced.** SP-7a/b (reads truth read-only, writes only preference/evidence), SP-7e (threshold gate), SP-7f (no portfolio advice), SP-7g (explanation gate).

**Commit.** `feat(15): Slice 15.5 — Learning Inference`

---

### Slice 15.6 — Preference Decay & Falsification

**Objective.** Keep beliefs current: time-decay affinities, evaluate falsifiers, transition stale/disproven preferences.

**Adds.** `user_preference_decay_service` with `apply_decay(...)` (recency decay by dimension-specific `λ`; `active → decayed` past half-life) and `evaluate_falsifiers(...)` (`active → falsified` when the stated falsifier condition is met, e.g. repeated dismissals or N days without reinforcement). Asymmetric negative weighting (`κ`) and the repetition gate for `ignored_*` live here (spec §5.4). Status-only mutations via `set_preference_status`.

**Likely files.** `app/services/user_preference_decay_service.py`; `tests/test_services/test_user_preference_decay_service.py`.

**Validation (slice tests).** Decay reduces affinity monotonically with age; a preference unreinforced past its half-life → `decayed`; a met falsifier → `falsified`; a positive event resets negative accumulation (a returning user); `ignored_*` requires N cross-session negatives before `active`; **no truth write** (status-only on `learned_preference`); null-session safe.

**Rollback.** `git revert`. Decay is a maintenance pass; disabling it freezes affinities (safe — preferences simply stop aging).

**SP-7 enforced.** SP-7a (status-only mutation, no truth write), SP-7e (decay supports anti-fabrication over time).

**Commit.** `feat(15): Slice 15.6 — Preference Decay & Falsification`

---

### Slice 15.7 — Interest Profile & Priorities

**Objective.** Assemble the read projections: `user_interest_profile` and `learned_priorities`. No new storage — derived on demand, DB-down-safe.

**Adds.** `user_profile_service` with `build_user_interest_profile(...)` (aggregate over `active`+`explicit` preferences across the seven dimensions, each carrying affinity/confidence/strength + explanation pointer) and `build_learned_priorities(...)` (ranked per-entity salience **weights**, never scores). Cold-start ⇒ **empty profile**, not a default profile (principle #2). Also assembles `attention_preferences` (density/cadence/depth/modality — spec §6.4).

**Likely files.** `app/services/user_profile_service.py`; `tests/test_services/test_user_profile_service.py`.

**Validation (slice tests).** Only `active`/`explicit` preferences appear (never `unresolved`/`decayed`/`falsified`); cold-start returns empty, not defaults; priorities contain weights not scores (type/shape check — SP-7c); profile carries explanation provenance for every entry; DB-down ⇒ empty projection with `db_available=False`; null-session safe.

**Rollback.** `git revert`. Projection consumed by nothing until 15.8 ⇒ inert.

**SP-7 enforced.** SP-7b (read-only over preferences), SP-7c (priorities are weights, not scores), SP-7e (unresolved excluded).

**Commit.** `feat(15): Slice 15.7 — Interest Profile & Priorities`

---

### Slice 15.8 — Relevance Engine

**Objective.** The projection that turns priorities into ordering: boosts, penalties, novelty reserve, relevance floor. Truth never changes — only ranking.

**Adds.** `relevance_service.apply_relevance(result_set, personalization_context)` → a **permutation-with-annotation** over a truth-fixed input set (spec §7, principle #11): computes bounded `relevance_weight ∈ [W_MIN, W_MAX]`, derives `display_score = intrinsic_priority · (1 + relevance_weight)` (ephemeral sort key — never persisted onto the item), emits `adjusted_rank` + `prominence_tier ∈ {pinned, normal, muted}`. Applies **relevance boosts** (positive affinity), **relevance penalties** (negative affinity — demote, never hide), the **novelty reserve** (guaranteed minority of high-intrinsic/low-affinity items), and the **relevance floor** (SP-7d: critical-severity items clamped above `FLOOR_RANK`, never `muted`, never `hidden`). Builds `personalization_context` (spec §6.5).

**Likely files.** `app/services/relevance_service.py`; `tests/test_services/test_relevance_service.py`.

**Flags.** `learning_relevance_enabled` (off ⇒ returns input in original truth order — the null-profile contract).

**Validation (slice tests).** Output is a permutation of the input — no item added, dropped, or edited (SP-7c); `intrinsic_priority` byte-identical in vs out; `prominence_tier` is never `hidden`; a critical item is never pushed below `FLOOR_RANK` and never `muted` (SP-7d) even under maximum penalty; novelty reserve always populated when eligible items exist; weight respects `[W_MIN, W_MAX]` clamp (nudge-not-override); empty/cold-start profile ⇒ unchanged truth order; null-session safe.

**Rollback.** `git revert` or `learning_relevance_enabled=False` — surfaces return to truth order instantly (pure permutation removal can never change correctness — spec §11.3).

**SP-7 enforced.** SP-7c (ordering-only), SP-7d (floor, demote-never-hide), SP-7a (no truth write — returns a projection, persists nothing onto items).

**Commit.** `feat(15): Slice 15.8 — Relevance Engine`

---

### Slice 15.9 — Relevance Shadow Journal

**Objective.** Journal what the relevance engine *would* do, without applying it. The Stage-3 shadow surface.

**Adds.** `relevance_shadow_service.journal_adjustments(...)`: runs 15.8 over a real result set and writes `relevance_adjustment_log` rows (`run_reason="shadow"`, recording `intrinsic_rank → adjusted_rank`, `relevance_weight`, `prominence_tier`, `floor_applied`) **without** changing any surface. Gated on `learning_shadow`; `learning_delivery_enabled` stays `False` (no application) until Stage 5. The Phase 14 `scenario_delivery_service` shadow-journal pattern, reused.

**Likely files.** `app/services/relevance_shadow_service.py`; `tests/test_services/test_relevance_shadow_service.py`.

**Flags.** `learning_shadow` (journal), `learning_delivery_enabled` (must be `False` here).

**Validation (slice tests).** Gate off ⇒ no rows; gate on ⇒ one row per repositioned item with both ranks recorded; **no Notification/delivery-ledger write** (journal-only, like Phase 14 shadow); `run_reason` is always `shadow` while `learning_delivery_enabled=False`; floor-clamped items recorded with `floor_applied=True`; idempotent (deduped) re-journal; null-session safe.

**Rollback.** `git revert` or `learning_shadow=False`. Journal rows are inert (no consumer).

**SP-7 enforced.** SP-7c/d (records ordering + floor), SP-7a (writes only the journal table; no surface, no Notification).

**Commit.** `feat(15): Slice 15.9 — Relevance Shadow Journal`

---

### Slice 15.10 — Preference Calibration

**Objective.** Make preference quality measurable: accuracy, drift, false-preference detection. Append-only metrics over the shadow window.

**Adds.** `user_preference_calibration_service` with `calculate_preference_accuracy(...)` (held-out: do learned preferences predict subsequent engagement? — spec §10.1), `calculate_preference_drift(...)` (affinity sign-flip rate per dimension — §10.2), `detect_false_preferences(...)` (precision check: `active` preference with zero reinforcement past a half-life; plus single-burst/low-session-entropy detector — §10.3), and `summarize_preference_calibration(...)`. Every metric reports `insufficient_samples` below `MIN_SAMPLES` (the Phase 14 calibration contract). Reads events + preferences read-only; writes nothing it is not allowed to (metrics are computed, not stored as truth).

**Likely files.** `app/services/user_preference_calibration_service.py`; `tests/test_services/test_user_preference_calibration_service.py`.

**Validation (slice tests).** Accuracy correct on a seeded predict/observe split; drift detects an induced sign-flip; false-preference detector flags a zero-reinforcement preference and a single-burst preference; `insufficient_samples` below threshold; no `.update`/`.delete`; null-session safe.

**Rollback.** `git revert`. Read-only metrics ⇒ inert.

**SP-7 enforced.** SP-7b (read-only), SP-7a (no truth write).

**Commit.** `feat(15): Slice 15.10 — Preference Calibration`

---

### Slice 15.11 — Observability + Shadow Validation

**Objective.** Close the phase: observability snapshot, admin route, the standalone validation script, and the operational runbook. The Phase 14 Slice 14.10 analogue.

**Adds.**
- `user_learning_observability_service.build_user_learning_observability_snapshot(...)`: flags; metrics (event counts by type, preference counts by dimension/status, shadow-adjustment count, latest-pass timestamp, calibration summary); structured `safe_state` sub-checks: `no_truth_writes`, `shadow_only`, `no_portfolio_advice`, `floor_enforced`, `no_sub_threshold_preferences`, plus `overall`. DB-down-safe.
- `GET /admin/user-learning-status` (read-only) delegating to it.
- `tests/validate_15_user_learning_shadow.py` (exit 0 required) — the umbrella safety gate.
- `docs/PHASE_15_USER_LEARNING_ROLLOUT.md` — operational runbook (env vars, stage commands, probe procedure, rollback, acceptance).

**Validation script checks (the nine required validations land here as an aggregate).**

| Required validation | Where enforced |
|---|---|
| preference accuracy | 15.10 service + script asserts it runs |
| preference drift | 15.10 service + script asserts it runs |
| false preference detection | 15.10 service + script asserts it runs |
| explainability | 15.4 gate + script: every `active` preference has 4 resolvable fields |
| **no-truth-mutation** | script: AST write-scan — zero writes to any truth table across all Phase 15 services |
| **no-forecast-write** | script: no `forecast_vector`/`forecast_evidence` write pattern or write-repo import |
| **no-similarity-write** | script: no `similarity_edge`/`similarity_feature_vector` write pattern or import |
| **no-scenario-write** | script: no `scenario_snapshot`/`scenario_evidence` write pattern or import |
| **no-decision-write** | script: no `decision_priority`/`decision_evidence` write pattern or import |

Plus: DB table count ≥ 53; the four tables exist; all Phase 15 services import cleanly; all flags inert by default; no conviction/order/execution import (SP-7f); no banned-phrase string constants (SP-7f); no preference persisted below threshold (SP-7e); relevance never emits `hidden` and always floors critical items (SP-7d); `safe_state.overall == true`; `relevance_adjustment_log.run_reason == shadow` everywhere until Stage 5.

**Likely files.** `app/services/user_learning_observability_service.py`; `app/api.py` (one route); `tests/test_services/test_user_learning_observability_service.py`; `tests/validate_15_user_learning_shadow.py`; `docs/PHASE_15_USER_LEARNING_ROLLOUT.md`.

**Rollback.** `git revert`. Read-only observability + script + doc ⇒ inert.

**SP-7 enforced.** All of SP-7, aggregated and asserted.

**Commit.** `feat(15): Slice 15.11 — Observability + Shadow Validation`

---

## 3. Flags (consolidated)

| Flag | Default | Turned on at | Effect |
|---|---|---|---|
| `learning_capture_enabled` | `False` | Stage 1 | append `user_signal_event` rows |
| `learning_explicit_prefs_enabled` | `False` | Stage 2 (independent) | accept explicit user preferences |
| `learning_inference_enabled` | `False` | Stage 2 | run the learning pass → `learned_preference` |
| `learning_relevance_enabled` | `False` | Stage 3 | compute relevance adjustments |
| `learning_shadow` | `True` | (already on) | journal adjustments without applying |
| `learning_delivery_enabled` | `False` | Stage 5 only | **apply** ordering to a real surface |

Default posture on deploy: nothing captured, nothing learned, no surface changed — fully inert, identical to the Phase 14 ship posture.

---

## 4. Rollout stages

Mirrors spec §11.2. No user-visible personalization until Stage 5, and only after the §5 acceptance gate is green.

| Stage | Slices live | Flags on | Effect | Exit criterion |
|---|---|---|---|---|
| **0 — Inert baseline** | 15.1–15.2 | none | tables + repos deployed, dormant | `validate_15` exits 0; table count 53 |
| **1 — Capture only** | +15.3 | `capture` | events accumulate; nothing learned | event stream healthy; zero truth writes |
| **2 — Shadow inference** | +15.4–15.7 | `inference` (+`explicit` opt) | preferences learned + explained; **no surface change** | preference_accuracy ≥ target; explainability validation green |
| **3 — Shadow relevance** | +15.8–15.9 | `relevance`, `shadow` | adjustments computed + journaled; compare would-be vs truth order | drift within band; false_preference_rate within band; floor always honored in log |
| **4 — Acceptance** | +15.10–15.11 | (no new flags) | full validation suite over a real shadow window | all nine validations pass; `safe_state` green |
| **5 — Delivery** | (no new slices) | `delivery` (per-surface, per-cohort) | personalization applied to a real surface, cohort-ramped | live-engagement non-regression; instant rollback ready |

Stage 5 ramps per-surface and per-cohort (internal → opt-in beta → percentage), each step gated on engagement non-regression and zero safety-gate violations.

---

## 5. Acceptance criteria

### 5.1 Per-slice gate (every slice)

- Slice's own pytest suite green **and** the cumulative Phase 15 suite green.
- `validate_15_user_learning_shadow.py` exits 0 (from 15.11 onward; earlier slices run the subset that exists).
- AST safety tests green: no truth-write import, no conviction/order/execution import, no banned-phrase string constant.
- All flags still inert by default; merging the slice changes nothing a user sees.
- Commit checkpoint recorded.

### 5.2 Phase-level acceptance (gate to Stage 5)

- [ ] `validate_15_user_learning_shadow.py` exits 0 with all checks passing.
- [ ] All Phase 15 pytest suites pass.
- [ ] `GET /admin/user-learning-status` returns `safe_state.overall: true` with every sub-check true.
- [ ] **No-truth-mutation proven:** zero writes to any forecast/similarity/scenario/decision/evidence table across all Phase 15 services (AST + runtime).
- [ ] **no-forecast-write / no-similarity-write / no-scenario-write / no-decision-write** each individually green.
- [ ] preference_accuracy ≥ target over a real shadow window (beats truth-order baseline).
- [ ] preference_drift within band; false_preference_rate within band.
- [ ] Every `active`/`explicit` preference has all four explanation fields, resolvable evidence, and a checkable falsifier.
- [ ] Relevance engine proven a pure permutation: intrinsic values byte-identical in/out; no `hidden`; critical items always floored.
- [ ] `relevance_adjustment_log.run_reason == shadow` everywhere; `learning_delivery_enabled=False` throughout the validation window.
- [ ] No buy/sell/hold/target-price/position-size language anywhere; no portfolio recommendation path (SP-7f).

Only when every box is checked may `learning_delivery_enabled` be considered, per-surface and per-cohort.

---

## 6. Rollback playbook

| Level | Action | Effect | Data impact |
|---|---|---|---|
| **Instant (surface)** | `learning_delivery_enabled=False` | any surface returns to truth order immediately | none |
| **Stop relevance** | `learning_relevance_enabled=False` (and/or `learning_shadow=False`) | no adjustments computed/journaled | none (journal rows inert) |
| **Stop learning** | `learning_inference_enabled=False` | preferences stop updating (existing rows harmless, read by nothing) | none |
| **Stop capture** | `learning_capture_enabled=False` | event stream stops | none (events read by nothing) |
| **Code-level** | `git revert <slice commit>` | removes the slice | none — additive tables only, no source `ALTER` |
| **Data-level (optional)** | retention sweep / truncate the four Phase 15 tables | clears learned state | confined to the four additive tables; zero truth impact |

Because the relevance layer is a pure permutation over a truth-fixed set, removing it can never change correctness — only order. Because the schema is additive-only, no rollback ever requires a source-table migration.

---

## 7. Commit checkpoint discipline

One commit per slice, message `feat(15): Slice 15.N — <name>`, after that slice's suite **and** the cumulative suite are green and the validation script (where present) exits 0 — identical to the cadence used through Phases 13–14. Do not begin slice N+1 until slice N is committed.

---

## 8. Likely-files index (whole phase)

| Area | Files |
|---|---|
| Schema | `app/db/models.py` (+4 classes, 0 edits to existing tables) |
| Flags | `app/config.py` (+6 flags) |
| Repositories | `app/db/repositories/user_learning_repo.py` |
| Services | `app/services/user_signal_capture_service.py`, `user_learning_explainability_service.py`, `user_learning_inference_service.py`, `user_preference_decay_service.py`, `user_profile_service.py`, `relevance_service.py`, `relevance_shadow_service.py`, `user_preference_calibration_service.py`, `user_learning_observability_service.py` |
| Admin route | `app/api.py` (+1 read-only route) |
| Tests | `tests/test_services/test_*` (one per service), `tests/test_repositories/test_user_learning_repo.py`, `tests/test_services/test_user_learning_schema.py` |
| Validation | `tests/validate_15_user_learning_shadow.py` |
| Runbook | `docs/PHASE_15_USER_LEARNING_ROLLOUT.md` |

---

*End of Phase 15 implementation plan. Plan only — no code, no migrations, no implementation. Build begins at Slice 15.1.*
