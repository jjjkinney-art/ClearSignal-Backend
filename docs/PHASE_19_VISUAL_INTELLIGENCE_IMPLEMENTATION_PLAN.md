# Phase 19 — Visual Intelligence Implementation Plan

**Phase:** 19 · Visual Intelligence Layer
**Status:** Plan — implementation not started
**Source of truth:** `docs/PHASE_19_VISUAL_INTELLIGENCE_SPEC.md` (approved)
**Safety invariant family:** **SP-19** (spec §No-Advice Boundary)
**Scope:** Plan only. No code, no migrations, no implementation in this document.

---

## 0. How to read this plan

Phase 19 ships as **12 independently shippable slices**. The discipline is identical to Phases 13–18, which are already production-shadow validated:

- **Every slice ships behind inert flags.** Merging a slice changes nothing a user sees. Shipping is always a safe no-op until a flag is deliberately turned on in a later rollout stage.
- **Every slice is independently testable.** Each carries its own pytest suite (SQLite in-memory, null-session contract, AST safety checks). A slice is not "done" until its suite and the cumulative suite are green.
- **Every slice is independently reversible.** Because the data model is *additive only* (three new tables, zero `ALTER` on any source table) and every behavior is flag-gated, reverting a slice is a `git revert` with no data migration and no recompute.
- **Commit checkpoint after each slice**, message `feat(19): Slice 19.N — <name>`, mirroring the Phase 18 commit cadence.

> **Grounding note.** This plan invents no new release machinery. It reuses the proven Phase 18 pattern: additive model classes (no source-table `ALTER`), inert-default flags, per-service AST firewalls, an append-only shadow journal, a mandatory explainability gate, a `safe_state` observability snapshot + admin route, and a standalone `validate_19_*_shadow.py` script. Each slice below names the Phase 18 artifact it is modeled on.

> **Core constraint.** Phase 19 does not create intelligence. Phase 19 visualizes intelligence. It reads from every upstream phase but writes only to its own three tables: `visual_spec_cache`, `visual_experience_event`, and `ai_visual_generation_log`. No truth table is ever written, updated, or deleted by any Phase 19 service.

---

## 1. Slice overview

| Slice | Name | Unlocks (flag) | Serves stage | Depends on |
|---|---|---|---|---|
| **19.1** | Schema + Flags | — (all flags land inert) | 0 | — |
| **19.2** | Visual Repositories | — | 0 | 19.1 |
| **19.3** | Visual Spec Builder + Validation | `visual_orchestrator_enabled` | 1 | 19.2 |
| **19.4** | Market + Forecast Visuals | — | 1 | 19.3 |
| **19.5** | Scenario + Transmission Visuals | — | 1 | 19.3 |
| **19.6** | Similarity + Precedent Visuals | — | 1 | 19.3 |
| **19.7** | Portfolio + Exposure Visuals | — | 1 | 19.3 |
| **19.8** | Personal Experience Visuals | — | 1 | 19.3 |
| **19.9** | AI Visual Generation Layer | `visual_ai_enabled` | 4 | 19.3 |
| **19.10** | Visual Shadow Journal | `visual_shadow` | 3 | 19.3 |
| **19.11** | Visual Calibration | — | 4 | 19.10 |
| **19.12** | Observability + Shadow Validation | — | 4 | all |

### 1.1 Dependency graph

```
19.1 Schema+Flags
   └─▶ 19.2 Repositories
          └─▶ 19.3 Visual Spec Builder + Validation
                 ├─▶ 19.4 Market + Forecast Visuals
                 ├─▶ 19.5 Scenario + Transmission Visuals
                 ├─▶ 19.6 Similarity + Precedent Visuals
                 ├─▶ 19.7 Portfolio + Exposure Visuals
                 ├─▶ 19.8 Personal Experience Visuals
                 ├─▶ 19.9 AI Visual Generation Layer
                 └─▶ 19.10 Visual Shadow Journal
                           └─▶ 19.11 Visual Calibration
                                      └─▶ 19.12 Observability + Validation
```

Slices 19.4–19.8 are **parallel-safe** — they share no dependencies with each other, only with 19.3. They can be implemented in any order. Slices 19.9–19.12 are sequential.

---

## 2. Visual Priority Framework

Not every data point deserves a visual. The framework determines what is visualized and at which tier.

### What deserves a visual

An upstream intelligence output qualifies for visualization when:

1. **Structured quantitative data exists** — probabilities, scores, weights, edges, positions. No visuals from free-text-only outputs.
2. **Temporal or relational structure exists** — time series, networks, hierarchies, distributions. Flat key-value pairs are better as tables.
3. **The visual adds information density** — a chart communicates more than the raw data. If a single number tells the full story, no visual is needed.

### Tier selection rules

| Condition | Tier | Rationale |
|---|---|---|
| Frontend has a chart component for this type | **Tier 1: Structured JSON** | Fastest path. Frontend renders. Backend produces typed data spec. |
| Graph/tree/network topology requiring layout computation | **Tier 2: Server-side SVG** | Force-directed, hierarchical, or timeline layouts benefit from server-side computation. |
| Open-ended question spanning multiple intelligence sources | **Tier 3: AI-generated image** | No template fits. Requires spatial layout decisions. |
| Single scalar value (one number, one label) | **No visual** | A number in context is better than a chart of one bar. |
| Free-text narrative with no structured data | **No visual** | Visuals require data. Prose is not data. |

### Default tier assignments

| Visual Type | Default Tier |
|---|---|
| Price chart, performance chart, volatility overlay | Tier 1 (JSON) |
| Probability distribution, confidence band, forecast evolution | Tier 1 (JSON) |
| Exposure map, concentration map | Tier 1 (JSON) |
| Attention timeline, change timeline, resume timeline | Tier 1 (JSON) |
| Outcome tree, scenario tree | Tier 2 (SVG) |
| Transmission-path diagram, impact map | Tier 2 (SVG) |
| Similarity network, analog cluster, relationship graph | Tier 2 (SVG) |
| Dependency map | Tier 2 (SVG) |
| Precedent map, evidence timeline | Tier 2 (SVG) |
| What-changed map, thesis evolution | Tier 2 (SVG) |
| Scenario exposure matrix | Tier 2 (SVG) |
| Question-driven explanatory visuals | Tier 3 (AI) |
| Ecosystem/supply-chain maps | Tier 3 (AI) |

---

## 3. Per-slice detail

Each card states: **Objective · Adds · Likely files · Flags · Validation (slice tests) · Rollback · SP-19 enforced · Commit.**

---

### Slice 19.1 — Schema + Flags

**Objective.** Land the three additive tables and the five inert flags. Nothing executes; this is pure structure.

**Adds.** Three SQLAlchemy model classes (continuing global numbering; current head = 56):

| # | Table | Kind |
|---|---|---|
| 57 | `visual_spec_cache` | upsert-on-unique `(user_id, visual_type, entity_key, data_hash)` — cached visual specs |
| 58 | `visual_experience_event` | append-only visual generation log |
| 59 | `ai_visual_generation_log` | append-only AI generation audit log |

Five flags, all default inert: `visual_orchestrator_enabled=False`, `visual_renderer_enabled=False`, `visual_ai_enabled=False`, `visual_cache_enabled=False`, `visual_shadow=True`.

**Likely files.** `app/db/migrations/019_visual_intelligence.sql`; `app/db/models.py` (3 new classes); `app/config.py` (5 new flags); `tests/test_services/test_visual_intelligence_schema.py`.

**Flags.** All five land inert. No behavior change on merge.

**Validation (slice tests).** `db_table_count >= 59`; all three visual tables exist in metadata; indexes present; no advice/truth-override columns; ORM models importable; all five visual_* flags at inert defaults; migration idempotency markers (IF NOT EXISTS); migration SQL has no advice or trade terms; `visual_experience_event` and `ai_visual_generation_log` are append-only intent (AST: no update/delete in migration); round-trip insert/select on all three tables; null-session safe.

**Rollback.** `git revert`. Tables are empty and inert.

**SP-19 enforced.** SP-19c (writes only to Phase 19 tables; verified structurally — no upstream table references in migration DDL).

**Commit.** `feat(19): Slice 19.1 — Schema + Flags`

---

### Slice 19.2 — Visual Repositories

**Objective.** CRUD for all three Phase 19 tables. Pure DB access, no visual logic.

**Adds.** `visual_intelligence_repo` with:
- Cache: `upsert_visual_cache(session, *, user_id, visual_type, entity_key, data_hash, spec_json, rendering_tier, explanation_valid, run_reason, expires_at)`, `get_visual_cache(session, *, user_id, visual_type, entity_key, data_hash)`, `list_visual_cache(session, *, user_id, visual_type, limit)`, `count_visual_cache(session, *, user_id, visual_type)`, `invalidate_visual_cache(session, *, user_id, entity_key)`.
- Events: `add_visual_event(session, *, user_id, visual_type, entity_key, rendering_tier, explanation_valid, generation_ms, cache_hit, blocked_reason, run_reason)`, `list_visual_events(session, *, user_id, visual_type, run_reason, limit)`, `count_visual_events(session, *, user_id, visual_type, run_reason)`.
- AI Log: `add_ai_generation_log(session, *, user_id, visual_type, entity_key, prompt_hash, generation_model, generation_ms, validation_passed, validation_reason, banned_phrases_found, run_reason)`, `list_ai_generation_logs(session, *, user_id, visual_type, limit)`, `count_ai_generation_logs(session, *, user_id)`.

All functions accept `session` as the first positional argument. `session=None` → safe return (`None`/`[]`/`0`). No flag checks in the repo layer.

**Likely files.** `app/db/repositories/visual_intelligence_repo.py`; `tests/test_services/test_visual_intelligence_repo.py`.

**Flags.** None (repos are below flag gates).

**Validation (slice tests).** Upsert/get/list/count round-trips for cache; upsert cache increments on re-upsert; add/list/count round-trips for events; add/list/count round-trips for AI log; append-only: no `.update()`/`.delete()` in events or AI log sections (AST verified); invalidate_visual_cache only touches visual_spec_cache; null-session safe on all functions; no upstream table imports.

**Rollback.** `git revert`. Repo is inert without callers.

**SP-19 enforced.** SP-19c (writes only to Phase 19 tables); SP-19d (no upstream imports).

**Commit.** `feat(19): Slice 19.2 — Visual Repositories`

---

### Slice 19.3 — Visual Spec Builder + Validation

**Objective.** The core visual specification builder and the explainability validation engine. Every visual passes through this layer before rendering or serving.

**Adds.** Two services:

`visual_spec_builder_service` with:
- `build_visual_spec(*, visual_type, entity_key, data, labels, evidence_refs, rendering_tier)` → dict with `visual_type`, `version`, `data`, `labels`, `explainability`, `validation`, `rendering_tier`. Pure function.
- `select_rendering_tier(visual_type)` → `"json"` | `"svg"` | `"ai_image"`. Pure function. Implements the tier selection rules from §2.
- `hash_visual_data(data)` → SHA-256 string. Pure function. Used for cache keying.

`visual_validation_service` with:
- `validate_visual_spec(spec)` → `(ok, reason)`. Pure function. Checks: `what_am_i_looking_at` non-empty, `why_does_it_matter` non-empty, `supporting_evidence` non-empty list. Returns `(False, reason)` on any failure.
- `validate_visual_labels(labels)` → `(ok, reason)`. Pure function. Scans label text for banned phrases. Returns `(False, phrase_found)` on detection.
- `validate_visual_evidence(evidence_refs)` → `(ok, reason)`. Pure function. Checks at least one evidence reference present and non-empty.

All validation functions are pure — no DB access, no session required.

Gated on `visual_orchestrator_enabled`. Returns empty spec / `(False, "disabled")` when off.

**Likely files.** `app/services/visual_spec_builder_service.py`; `app/services/visual_validation_service.py`; `tests/test_services/test_visual_spec_builder_service.py`; `tests/test_services/test_visual_validation_service.py`.

**Flags.** `visual_orchestrator_enabled` (gate; off ⇒ empty specs).

**Validation (slice tests).** `build_visual_spec` produces complete spec with all fields; `select_rendering_tier` returns correct tier for each visual type; `hash_visual_data` is deterministic; `validate_visual_spec` passes valid specs; `validate_visual_spec` fails on missing `what_am_i_looking_at`; `validate_visual_spec` fails on missing `why_does_it_matter`; `validate_visual_spec` fails on missing/empty `supporting_evidence`; `validate_visual_labels` detects banned phrases; `validate_visual_labels` passes clean labels; `validate_visual_evidence` fails on empty list; all functions deterministic (same input → same output); no upstream table imports; banned-phrase AST scan on all string literals; null-session safe (for any async wrappers).

**Rollback.** `git revert` or `visual_orchestrator_enabled=False` — all specs return empty.

**SP-19 enforced.** SP-19a (banned-phrase validation), SP-19b (spec does not modify upstream data), SP-19c (writes nothing — spec builder is pure computation), SP-19d (no upstream feedback).

**Commit.** `feat(19): Slice 19.3 — Visual Spec Builder + Validation`

---

### Slice 19.4 — Market + Forecast Visuals

**Objective.** Assemble visual data specifications for market and forecast visual types: price chart, performance chart, volatility overlay, evidence timeline, probability distribution, outcome tree, confidence band, forecast evolution.

**Adds.** `visual_market_forecast_service` with:
- `assemble_price_chart(session, *, entity_key, run_override)` → visual data dict for an annotated price chart. Reads `ticker_memory`, `memory_entries`.
- `assemble_performance_chart(session, *, entity_key, user_id, run_override)` → visual data dict. Reads `portfolio_positions`.
- `assemble_volatility_overlay(session, *, entity_key, run_override)` → visual data dict. Reads `scenario_snapshot` plausibility.
- `assemble_evidence_timeline(session, *, entity_key, run_override)` → visual data dict. Reads `memory_entries` timestamps.
- `assemble_forecast_distribution(session, *, entity_key, run_override)` → visual data dict. Reads `forecast_vector`.
- `assemble_outcome_tree(session, *, entity_key, run_override)` → visual data dict. Reads `forecast_vector`, conditional probabilities.
- `assemble_confidence_band(session, *, entity_key, run_override)` → visual data dict. Reads `forecast_vector`, `forecast_calibration_log`.
- `assemble_forecast_evolution(session, *, entity_key, run_override)` → visual data dict. Reads `forecast_vector` history.

Each function returns a structured dict ready for `build_visual_spec`. All are read-only on upstream tables. All gated on `visual_orchestrator_enabled`.

**Likely files.** `app/services/visual_market_forecast_service.py`; `tests/test_services/test_visual_market_forecast_service.py`.

**Flags.** `visual_orchestrator_enabled` (gate).

**Validation (slice tests).** Gate off ⇒ empty/None for all functions; each function returns a dict with `entity_key`, `visual_type`, `data`, `evidence_refs`; forecast_distribution data includes `bull_probability`, `base_probability`, `bear_probability`; evidence timeline data includes sorted timestamp list; read-only on all upstream tables (import firewall); no banned phrases in templates (AST scan); deterministic: same upstream data → same output; null-session safe.

**Rollback.** `git revert`. Assemblers are pure computation over reads.

**SP-19 enforced.** SP-19a (no advisory language in templates), SP-19b (reads forecast data, does not modify it), SP-19c (writes nothing), SP-19d (no upstream feedback).

**Commit.** `feat(19): Slice 19.4 — Market + Forecast Visuals`

---

### Slice 19.5 — Scenario + Transmission Visuals

**Objective.** Assemble visual data specifications for scenario visual types: what-changed map, transmission-path diagram, scenario tree, impact map.

**Adds.** `visual_scenario_service` with:
- `assemble_what_changed_map(session, *, entity_key, run_override)` → visual data dict. Reads `scenario_snapshot` diffs.
- `assemble_transmission_path(session, *, entity_key, scenario_id, run_override)` → visual data dict. Reads `scenario_evidence` transmission edges.
- `assemble_scenario_tree(session, *, entity_key, run_override)` → visual data dict. Reads active `scenario_snapshot` rows.
- `assemble_impact_map(session, *, entity_key, scenario_id, run_override)` → visual data dict. Reads `scenario_evidence`, affected entities.

Each function returns a structured dict with nodes and edges ready for Tier 2 SVG rendering.

**Likely files.** `app/services/visual_scenario_service.py`; `tests/test_services/test_visual_scenario_service.py`.

**Flags.** `visual_orchestrator_enabled` (gate).

**Validation (slice tests).** Gate off ⇒ empty; transmission path returns nodes + edges; scenario tree returns hierarchical structure; impact map returns affected entity list with impact scores; no directional-action arrows (SP-19e — validated by checking edge labels contain no advisory terms); read-only on upstream tables; banned-phrase AST scan; deterministic; null-session safe.

**Rollback.** `git revert`.

**SP-19 enforced.** SP-19a, SP-19b, SP-19c, SP-19d, SP-19e (no directional arrows implying action — edge labels validated).

**Commit.** `feat(19): Slice 19.5 — Scenario + Transmission Visuals`

---

### Slice 19.6 — Similarity + Precedent Visuals

**Objective.** Assemble visual data specifications for similarity visual types: similarity network, analog cluster, precedent map, relationship graph.

**Adds.** `visual_similarity_service` with:
- `assemble_similarity_network(session, *, entity_key, run_override)` → visual data dict. Reads `similarity_edge`, `similarity_feature_vector`.
- `assemble_analog_cluster(session, *, entity_key, run_override)` → visual data dict. Reads `historical_analogs`, similarity scores.
- `assemble_precedent_map(session, *, entity_key, run_override)` → visual data dict. Reads `historical_analogs`, outcome data.
- `assemble_relationship_graph(session, *, entity_key, run_override)` → visual data dict. Reads multi-dimensional `similarity_edge` rows.

Each returns nodes + edges + scores ready for Tier 2 SVG rendering.

**Likely files.** `app/services/visual_similarity_service.py`; `tests/test_services/test_visual_similarity_service.py`.

**Flags.** `visual_orchestrator_enabled` (gate).

**Validation (slice tests).** Gate off ⇒ empty; similarity network returns nodes + weighted edges; analog cluster returns grouped entities with scores; precedent map returns chronological items; edge weights in [0.0, 1.0]; read-only on upstream tables; banned-phrase AST scan; deterministic; null-session safe.

**Rollback.** `git revert`.

**SP-19 enforced.** SP-19a, SP-19b, SP-19c, SP-19d.

**Commit.** `feat(19): Slice 19.6 — Similarity + Precedent Visuals`

---

### Slice 19.7 — Portfolio + Exposure Visuals

**Objective.** Assemble visual data specifications for portfolio visual types: exposure map, concentration map, dependency map, scenario exposure matrix.

**Adds.** `visual_portfolio_service` with:
- `assemble_exposure_map(session, *, user_id, portfolio_id, run_override)` → visual data dict. Reads `portfolio_positions`, sector/geography tags.
- `assemble_concentration_map(session, *, user_id, portfolio_id, run_override)` → visual data dict. Reads `portfolio_positions` weights.
- `assemble_dependency_map(session, *, user_id, portfolio_id, run_override)` → visual data dict. Reads `similarity_edge` between portfolio holdings.
- `assemble_scenario_exposure(session, *, user_id, portfolio_id, run_override)` → visual data dict. Reads `scenario_snapshot` impacts × `portfolio_positions`.

**Likely files.** `app/services/visual_portfolio_service.py`; `tests/test_services/test_visual_portfolio_service.py`.

**Flags.** `visual_orchestrator_enabled` (gate).

**Validation (slice tests).** Gate off ⇒ empty; exposure map returns position weights summing to ≤ 1.0; concentration map returns heat values in [0.0, 1.0]; dependency map returns edges between portfolio-held entities only; scenario exposure returns a matrix of (scenario × position) sensitivities; no dollar amounts in visual data (weights only, not values — SP-19a); read-only on upstream tables; banned-phrase AST scan; deterministic; null-session safe.

**Rollback.** `git revert`.

**SP-19 enforced.** SP-19a (no dollar amounts, weights only), SP-19b, SP-19c, SP-19d.

**Commit.** `feat(19): Slice 19.7 — Portfolio + Exposure Visuals`

---

### Slice 19.8 — Personal Experience Visuals

**Objective.** Assemble visual data specifications for personal experience visual types: attention timeline, change timeline, resume timeline, thesis evolution.

**Adds.** `visual_experience_service` with:
- `assemble_attention_timeline(session, *, user_id, run_override)` → visual data dict. Reads `personal_experience_event` attention scores.
- `assemble_change_timeline(session, *, user_id, run_override)` → visual data dict. Reads Phase 18 change candidates, recency scores.
- `assemble_resume_timeline(session, *, user_id, run_override)` → visual data dict. Reads Phase 18 resume candidates, continuation scores.
- `assemble_thesis_evolution(session, *, user_id, entity_key, run_override)` → visual data dict. Reads `ticker_memory`, thesis snapshot history.

**Likely files.** `app/services/visual_experience_service.py`; `tests/test_services/test_visual_experience_service.py`.

**Flags.** `visual_orchestrator_enabled` (gate).

**Validation (slice tests).** Gate off ⇒ empty; attention timeline returns chronological events with scores; change timeline returns items sorted by recency; resume timeline returns items sorted by continuation_score; thesis evolution returns multi-entity time series; tenant isolation (user A's timeline does not appear in user B's visual); read-only on upstream tables (Phase 18 tables are read, not written); banned-phrase AST scan; deterministic; null-session safe.

**Rollback.** `git revert`.

**SP-19 enforced.** SP-19a, SP-19b, SP-19c, SP-19d.

**Commit.** `feat(19): Slice 19.8 — Personal Experience Visuals`

---

### Slice 19.9 — AI Visual Generation Layer

**Objective.** Handle AI-generated visual explanations: question classification, prompt building, post-generation safety validation, deterministic fallback.

**Adds.** `ai_visual_generator_service` with:
- `classify_visual_question(question, *, entity_key)` → dict with `visual_type`, `intelligence_sources`, `suggested_tier`. Pure function. Maps question patterns to visual types and data sources.
- `build_ai_visual_prompt(*, visual_type, entity_key, data, style, constraints)` → dict with `prompt_type`, `entity`, `data`, `style`, `constraints`. Pure function. Constructs a structured prompt from intelligence data. Never passes raw user text into the prompt.
- `hash_prompt(prompt)` → SHA-256 string. Pure function. For audit logging (prompt text is never stored).
- `validate_ai_visual_output(output_metadata)` → `(ok, reason, banned_phrases_found)`. Pure function. Checks for banned phrases in any text content. Checks explainability fields present. Returns `(False, reason, [phrases])` on any failure.
- `generate_ai_visual(session, *, user_id, visual_type, entity_key, data, run_override)` → dict with `image_url` or `None`, `validation_passed`, `fallback_spec`, `generation_ms`. Async. Calls image generation model, validates output, logs to `ai_visual_generation_log`. Falls back to Tier 2/1 spec on failure.

Gated on `visual_ai_enabled`. Returns `None` / fallback spec when off.

**Likely files.** `app/services/ai_visual_generator_service.py`; `tests/test_services/test_ai_visual_generator_service.py`.

**Flags.** `visual_ai_enabled` (gate; off ⇒ all AI generation returns None with deterministic fallback).

**Validation (slice tests).** Gate off ⇒ None / fallback for all functions; `classify_visual_question` maps known patterns correctly; `classify_visual_question` returns `"unknown"` for unrecognized patterns; `build_ai_visual_prompt` never includes raw user text; `build_ai_visual_prompt` templates have no banned phrases (AST scan); `hash_prompt` is deterministic; `validate_ai_visual_output` detects banned phrases; `validate_ai_visual_output` fails on missing explainability; `validate_ai_visual_output` passes clean output; `generate_ai_visual` logs to `ai_visual_generation_log` with `prompt_hash` (not prompt text); `generate_ai_visual` falls back to deterministic visual on failure; no prompt text stored anywhere (grep for prompt text patterns); read-only on upstream tables; null-session safe.

**Rollback.** `git revert` or `visual_ai_enabled=False` — AI generation stops; deterministic fallbacks serve instead.

**SP-19 enforced.** SP-19a (prompt templates scanned), SP-19b, SP-19c (writes only `ai_visual_generation_log`), SP-19d, SP-19f (post-generation validation).

**Commit.** `feat(19): Slice 19.9 — AI Visual Generation Layer`

---

### Slice 19.10 — Visual Shadow Journal

**Objective.** Journal what the visual layer *would* generate, without serving it. The shadow observation layer (modeled on Phase 18 Slice 18.8).

**Adds.** `visual_shadow_journal_service` with:
- `journal_visual_event(session, *, user_id, visual_type, entity_key, rendering_tier, explanation_valid, generation_ms, cache_hit, blocked_reason, run_override)` → writes one `visual_experience_event` row via repo. `run_reason="shadow"` hardcoded.
- `journal_visual_batch(session, *, user_id, visual_specs, run_override)` → journals multiple visual specs. Returns list of inserted rows.
- `classify_visual_transition(current_spec, previous_spec)` → pure function. Returns transition type: `"new_visual"`, `"data_changed"`, `"tier_changed"`, `"validation_changed"`, or `None`.

Deduplication: recent events within `_DEDUP_WINDOW_SECONDS` (3600) with the same `(user_id, visual_type, entity_key, rendering_tier)` are skipped.

Gated on `visual_shadow` (True by default — shadow is always on). Returns `[]` when off or session is None.

**Likely files.** `app/services/visual_shadow_journal_service.py`; `tests/test_services/test_visual_shadow_journal_service.py`.

**Flags.** `visual_shadow` (on by default — journals everything).

**Validation (slice tests).** Shadow on ⇒ events journaled; shadow off ⇒ no rows; `run_reason="shadow"` on all rows; deduplication within window; different visual types ⇒ separate rows; blocked visuals journaled with `blocked_reason`; `classify_visual_transition` returns correct types; append-only (no `.update`/`.delete` in module — AST verified); no notification imports; null-session safe.

**Rollback.** `git revert`. Journal rows are inert.

**SP-19 enforced.** SP-19c (writes only `visual_experience_event`), SP-19d (no upstream feedback).

**Commit.** `feat(19): Slice 19.10 — Visual Shadow Journal`

---

### Slice 19.11 — Visual Calibration

**Objective.** Measure whether the visual layer is generating the right things: explainability coverage, cache efficiency, AI validation rates, generation latency, blocked visual rates.

**Adds.** `visual_calibration_service` with:
- `calculate_explainability_coverage(session, *, user_id, run_override)` → dict. `coverage = valid_count / total_count` from `visual_experience_event`. Returns `{coverage, valid_count, blocked_count, total_count, sufficient_samples}`. Min samples: 10.
- `calculate_cache_hit_rate(session, *, user_id, run_override)` → dict. `hit_rate = cache_hits / total_requests`. Min samples: 20.
- `calculate_ai_validation_pass_rate(session, *, user_id, run_override)` → dict. `pass_rate = passed / total_ai_generations` from `ai_visual_generation_log`. Min samples: 5.
- `calculate_generation_latency(session, *, user_id, run_override)` → dict. `p95 = 95th percentile of generation_ms`. Min samples: 20.
- `calculate_blocked_visual_rate(session, *, user_id, run_override)` → dict. `blocked_rate = blocked_count / total_count`. Min samples: 10.
- `summarize_visual_calibration(session, *, user_id, run_override)` → dict aggregating all five metrics.

All metric functions are observational — pure reads from Phase 19 event/log tables. Nothing modified.

Gated on `visual_shadow` (True by default).

**Likely files.** `app/services/visual_calibration_service.py`; `tests/test_services/test_visual_calibration_service.py`.

**Flags.** `visual_shadow` (gate).

**Validation (slice tests).** Gate off ⇒ all metrics return `sufficient_samples=False`; each metric computes correctly with seeded data; insufficient samples ⇒ metric value is None; all metric functions read-only; append-only (no writes except through record functions); no upstream table imports; banned-phrase AST scan; null-session safe.

**Rollback.** `git revert`. Calibration is read-only.

**SP-19 enforced.** SP-19c (writes nothing — pure reads), SP-19d (no upstream feedback).

**Commit.** `feat(19): Slice 19.11 — Visual Calibration`

---

### Slice 19.12 — Observability + Shadow Validation

**Objective.** Create observability, validation, rollout readiness, and safe-state reporting. Final slice — completes Phase 19.

**Adds.**

1. `visual_observability_service` with `build_visual_intelligence_snapshot(session)` → dict:
   - `flags` — all 5 visual_* flags
   - `metrics` — cache_count, event_count, ai_log_count, shadow_event_count, blocked_event_count
   - `safe_state` — shadow_only, no_live_delivery, no_truth_mutation, no_advisory_generation, no_upstream_mutation, explainability_gate_active, overall
   - `schema_version`, `generated_at`, `disclaimer`
   - DB-down-safe.

2. Admin route: `GET /admin/visual-intelligence-status` in `app/api.py`.

3. Validation script: `tests/validate_19_visual_intelligence_shadow.py` — validates all tables exist, all services import, all flags safe, no forbidden imports, no upstream writes, no advisory language, explainability gate present, shadow-only behavior, calibration append-only, safe_state overall true.

4. Rollout document: `docs/PHASE_19_VISUAL_INTELLIGENCE_SHADOW_ROLLOUT.md`.

**Likely files.** `app/services/visual_observability_service.py`; `app/api.py` (admin route); `tests/validate_19_visual_intelligence_shadow.py`; `docs/PHASE_19_VISUAL_INTELLIGENCE_SHADOW_ROLLOUT.md`; `tests/test_services/test_visual_observability_service.py`.

**Flags.** None (observability is always-on).

**Validation (slice tests).** Snapshot returns complete structure; all safe_state sub-checks True at defaults; safe_state.overall True; schema_version == 1; disclaimer present and contains no banned phrases; DB-down safe (session=None returns valid snapshot); admin route registered in api.py; validation script exits 0; no banned phrases in source (AST scan); no upstream truth-table imports; no mutation patterns.

**Rollback.** `git revert`. Observability is read-only.

**SP-19 enforced.** All SP-19 rules. This slice validates that the entire Phase 19 surface adheres to the safety boundary.

**Commit.** `feat(19): Slice 19.12 — Observability + Shadow Validation`

---

## 4. Validation plan

### Per-slice validation (runs with each slice)

| Check | Applies to |
|---|---|
| Flag gate: off ⇒ empty/None/[] | Every service function |
| Null-session: session=None ⇒ safe return | Every async function |
| AST banned-phrase scan (excluding docstrings) | Every service source file |
| Import firewall: no upstream write-module imports | Every service source file |
| Mutation pattern scan: no `.update()`/`.delete()` | Event and log services |
| Deterministic: same inputs → same outputs | All pure functions |
| Explainability gate: 3 fields required | All visual specs |

### Cross-slice validation (runs at 19.12)

| Check | Validated By |
|---|---|
| All 3 tables exist with correct columns | Schema tests |
| All services importable | Import checks |
| All 5 flags at safe defaults | Config validation |
| No upstream truth-table writes across all services | Import firewall + mutation scan |
| No advisory language across all services | AST scan |
| Explainability gate blocks incomplete visuals | Validation service tests |
| Shadow journal records blocked visuals | Shadow journal tests |
| Calibration metrics computable | Calibration tests |
| safe_state.overall == True | Observability snapshot |

### AI visual validation (19.9-specific)

| Check | Validated By |
|---|---|
| Prompt templates contain no banned phrases | AST scan on prompt templates |
| Prompt text never stored (only hash) | Grep for prompt storage patterns |
| Post-generation validator detects banned phrases | Unit tests with planted phrases |
| Deterministic fallback works when AI fails | Fallback path tests |
| Raw user text never in prompt | Input isolation tests |

---

## 5. Rollout plan

### Rollout stages (from spec)

| Stage | Flags Enabled | What Happens | Exit Criteria |
|---|---|---|---|
| **0 — Shadow** | All defaults | Code deployed, fully inert. Shadow journal accumulates. | All validation checks pass. safe_state.overall == true. |
| **1 — Structured JSON** | `visual_orchestrator_enabled=True` | Tier 1 visual specs generated. No rendering. Shadow journal captures. | Specs generating without errors. Explainability coverage > 0.9. |
| **2 — SVG Rendering** | + `visual_renderer_enabled=True` | Tier 2 SVGs generated server-side. Still shadow-only. | SVGs generating < 500ms p95. No banned phrases in SVG text. |
| **3 — Caching** | + `visual_cache_enabled=True` | Visual cache active. Performance validation. | Cache hit rate > 0.5 after warm-up. Cache invalidation working. |
| **4 — AI Generation** | + `visual_ai_enabled=True` | AI visuals with post-generation safety. Shadow-only. | AI validation pass rate > 0.9. No banned phrases detected. |
| **5 — Live** | `visual_shadow=False` | Visuals served to users. Requires frontend integration. | All Stage 4 criteria met. Frontend integration complete. |

### Rollback

Every stage is independently reversible. Set the flag back to its default. No data migration. Existing cache and journal rows are inert. Emergency rollback: all flags to defaults (Stage 0).

---

## 6. Estimated test scope

| Slice | Estimated Tests |
|---|---|
| 19.1 Schema + Flags | ~50 |
| 19.2 Visual Repositories | ~55 |
| 19.3 Visual Spec Builder + Validation | ~50 |
| 19.4 Market + Forecast Visuals | ~55 |
| 19.5 Scenario + Transmission Visuals | ~40 |
| 19.6 Similarity + Precedent Visuals | ~40 |
| 19.7 Portfolio + Exposure Visuals | ~45 |
| 19.8 Personal Experience Visuals | ~40 |
| 19.9 AI Visual Generation Layer | ~50 |
| 19.10 Visual Shadow Journal | ~30 |
| 19.11 Visual Calibration | ~35 |
| 19.12 Observability + Shadow Validation | ~25 |
| **Total** | **~515** |

---

## 7. Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| AI-generated visuals contain advisory language | Medium | High | Post-generation OCR; banned-phrase scan; shadow-first rollout; deterministic fallback |
| SVG rendering latency exceeds 500ms for complex graphs | Medium | Medium | Limit node/edge counts; cache aggressively; async generation |
| Cache staleness shows outdated visual | Low | Medium | Cache keyed on `data_hash` — upstream change invalidates automatically |
| AI image generation cost exceeds budget | Medium | Medium | Shadow-first (measure volume); cache; rate limit per user; Tier 3 only for question-driven |
| Explainability templates produce stale explanations | Low | Low | Templates reference upstream data timestamps; evidence_refs checked at validation time |
| Visual implies trading action via arrow direction | Low | High | SP-19e enforced; edge labels validated; post-generation scan for AI visuals |
| Upstream data unavailable at render time | Medium | Low | Graceful degradation: empty spec with `explanation_valid=False`; never fabricates data |

---

## 8. Acceptance criteria

- [ ] All 12 slices committed and tested
- [ ] Cumulative test suite passing (~515 tests)
- [ ] Validation script: all checks pass
- [ ] Admin route: safe_state.overall == true
- [ ] Shadow journal accumulating events without errors
- [ ] No truth-table writes by any Phase 19 service
- [ ] No advisory language in any service or template
- [ ] No user-visible behavior change at Stage 0
- [ ] Explainability gate: 3 fields enforced on every visual
- [ ] AI visual prompts: no raw user text; no prompt text stored
- [ ] Post-generation safety validation operational
- [ ] Deterministic fallback for failed AI visuals
- [ ] Cache invalidation on upstream data change
- [ ] Rollback tested (flag toggle → inert) at every stage
- [ ] All SP-19 rules verified by AST scan + import firewall + mutation pattern scan
