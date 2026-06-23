# Phase 18 — Personal Experience Implementation Plan

**Phase:** 18 · Personal Experience Layer
**Status:** Plan — implementation not started
**Source of truth:** `docs/PHASE_18_PERSONAL_EXPERIENCE_SPEC.md` (approved)
**Safety invariant family:** **SP-18** (spec §No-Advice Boundary)
**Scope:** Plan only. No code, no migrations, no implementation in this document.

---

## 0. How to read this plan

Phase 18 ships as **10 independently shippable slices**. The discipline is identical to Phases 13–15, which are already production-shadow validated:

- **Every slice ships behind inert flags.** Merging a slice changes nothing a user sees. Shipping is always a safe no-op until a flag is deliberately turned on in a later rollout stage.
- **Every slice is independently testable.** Each carries its own pytest suite (SQLite in-memory, null-session contract, AST safety checks). A slice is not "done" until its suite and the cumulative suite are green.
- **Every slice is independently reversible.** Because the data model is *additive only* (three new tables, zero `ALTER` on any source table) and every behavior is flag-gated, reverting a slice is a `git revert` with no data migration and no recompute.
- **Commit checkpoint after each slice**, message `feat(18): Slice 18.N — <name>`, mirroring the Phase 15 commit cadence.

> **Grounding note.** This plan invents no new release machinery. It reuses the proven Phase 15 pattern: additive model classes (no source-table `ALTER`), inert-default flags, per-service AST firewalls, an append-only shadow journal, a mandatory explainability gate, a `safe_state` observability snapshot + admin route, and a standalone `validate_18_*_shadow.py` script. Each slice below names the Phase 15 artifact it is modeled on.

> **Core constraint.** Phase 18 does not create intelligence. Phase 18 orchestrates intelligence. It reads from every upstream phase but writes only to its own three tables: `personal_experience_cursor`, `personal_experience_event`, and `personal_brief_snapshot`. No truth table is ever written, updated, or deleted by any Phase 18 service.

---

## 1. Slice overview

| Slice | Name | Unlocks (flag) | Serves stage | Depends on |
|---|---|---|---|---|
| **18.1** | Schema + Flags | — (all flags land inert) | 0 | — |
| **18.2** | Repositories | — | 0 | 18.1 |
| **18.3** | Change Detection | `experience_composer_enabled` | 1 | 18.2 |
| **18.4** | Attention Scoring | `experience_attention_enabled` | 2 | 18.2, 18.3 |
| **18.5** | Experience Composer + Explainability | — | 2 | 18.3, 18.4 |
| **18.6** | Personal Memory Context + Session Continuity | — | 2 | 18.2 |
| **18.7** | Personal Brief Builder | `experience_brief_enabled` | 3 | 18.5, 18.6 |
| **18.8** | Experience Shadow Journal | `experience_shadow` | 3 | 18.5 |
| **18.9** | Experience Calibration | — | 4 | 18.8 |
| **18.10** | Observability + Shadow Validation | — | 4 | all |

### 1.1 Dependency graph

```
18.1 Schema+Flags
   └─▶ 18.2 Repositories
          ├─▶ 18.3 Change Detection ──────────────┐
          │                                        │
          ├─▶ 18.6 Personal Memory Context ───────┤
          │                                        ▼
          └────────────────────────────▶ 18.4 Attention Scoring
                                                   └─▶ 18.5 Experience Composer + Explainability
                                                          ├─▶ 18.7 Personal Brief Builder
                                                          └─▶ 18.8 Experience Shadow Journal
                                                                 └─▶ 18.9 Experience Calibration
                                                                        └─▶ 18.10 Observability + Validation
```

The three read-only upstream consumers — **change detection** (18.3), **attention scoring** (18.4), and **personal memory context** (18.6) — communicate only through the additive tables and returned dicts, never through in-process mutation of upstream state. Any of the three can be disabled without breaking the others; the composer (18.5) degrades gracefully to zero-valued dimensions when a sub-service returns empty.

---

## 2. Per-slice detail

Each card states: **Objective · Adds · Likely files · Flags · Validation (slice tests) · Rollback · SP-18 enforced · Commit.**

---

### Slice 18.1 — Schema + Flags

**Objective.** Land the three additive tables and the six inert flags. Nothing executes; this is pure structure.

**Adds.** Three SQLAlchemy model classes (continuing global numbering; current head = 53):

| # | Table | Kind |
|---|---|---|
| 54 | `personal_experience_cursor` | upsert-on-unique `(user_id, entity_type, entity_key)` — view state |
| 55 | `personal_experience_event` | append-only surfacing log |
| 56 | `personal_brief_snapshot` | one per user per day (upsert-on-unique `(user_id, brief_date)`) |

Six flags, all default inert: `experience_composer_enabled=False`, `experience_shadow=True`, `experience_brief_enabled=False`, `experience_attention_enabled=False`, `experience_targets_enabled=""`, `experience_home_enabled=False`.

**Likely files.** `app/db/models.py` (3 new classes, **zero edits to existing tables**); `app/config.py` (6 flags + doc comments in the SP-18 style); `tests/test_services/test_personal_experience_schema.py`.

**Validation (slice tests).** Tables instantiate; columns/types/indexes/unique-constraints match spec; `user_id` is non-nullable on all three; round-trip insert/select on SQLite; flags exist and default inert; **DB table count == 56**; `personal_experience_event` is append-only by convention (verified by AST in 18.10); `personal_experience_cursor` unique constraint on `(user_id, entity_type, entity_key)`.

**Rollback.** `git revert`. No source table touched ⇒ no `ALTER` to undo, no data migration.

**SP-18 enforced.** SP-18c at the structural level — the only write targets introduced are the three Phase 18 tables; nothing references a truth table for write.

**Commit.** `feat(18): Slice 18.1 — Schema + Flags`

---

### Slice 18.2 — Repositories

**Objective.** Provide the insert/upsert/query surface for the three tables, with the immutability contracts baked in.

**Adds.** A `personal_experience_repo.py` with:
- `upsert_experience_cursor(session, *, user_id, entity_type, entity_key, last_seen_at, last_state_hash, ...)` — upsert keyed on `(user_id, entity_type, entity_key)`, updates `last_seen_at`, `last_state_hash`, `view_count`, `updated_at`.
- `get_experience_cursor(session, *, user_id, entity_type, entity_key)` — single cursor row.
- `list_experience_cursors(session, *, user_id, entity_type=None, limit=500)` — filtered query.
- `add_experience_event(session, *, user_id, surface, item_ref, ...)` — insert-only, no update, no delete.
- `list_experience_events(session, *, user_id, surface=None, run_reason=None, limit=500)` — filtered query.
- `count_experience_events(session, *, user_id=None, surface=None, run_reason=None)` — count query.
- `upsert_brief_snapshot(session, *, user_id, brief_date, ...)` — upsert keyed on `(user_id, brief_date)`.
- `get_brief_snapshot(session, *, user_id, brief_date)` — single brief row.
- `list_brief_snapshots(session, *, user_id, limit=30)` — filtered query.

All honor the null-session contract.

**Likely files.** `app/db/repositories/personal_experience_repo.py`; `tests/test_services/test_personal_experience_repo.py`.

**Validation (slice tests).** `add_experience_event` never updates an existing row (verified by AST: no `.update`/`UPDATE` path on event table); `upsert_experience_cursor` is idempotent on its unique key; `view_count` increments on re-upsert; `upsert_brief_snapshot` overwrites on `(user_id, brief_date)`; null-session returns `[]`/`None`/`0`; ordering (`surfaced_at`/`last_seen_at` desc) deterministic.

**Rollback.** `git revert`. No callers yet ⇒ inert.

**SP-18 enforced.** SP-18c (append-only event; controlled upsert on cursor/brief); import firewall test asserts the repo imports **no** truth-write repository.

**Commit.** `feat(18): Slice 18.2 — Repositories`

---

### Slice 18.3 — Change Detection Service

**Objective.** Detect what changed for a user since their last visit. The foundation for recency, novelty, and the "what changed since I was last here?" question.

**Adds.** `experience_change_detection_service` with:
- `detect_forecast_changes(session, *, user_id, run_override=None)` — reads `forecast_vector` rows for the user's watched/portfolio tickers, compares `confidence_score`/`direction` against `personal_experience_cursor.last_state_hash`. Returns a list of `{entity_key, entity_type, change_type, magnitude, old_hash, new_hash, changed_at}` dicts. A change is material when `abs(delta_confidence) >= 0.02` (2% materiality gate).
- `detect_scenario_changes(session, *, user_id, run_override=None)` — reads `scenario_snapshot` rows, compares plausibility/invalidation state against cursor. Returns same shape.
- `detect_thesis_changes(session, *, user_id, run_override=None)` — reads `ticker_memory`/`memory_entries` for watched tickers, compares content hash against cursor. Returns same shape.
- `detect_all_changes(session, *, user_id, run_override=None)` — orchestrates all three, returns merged + deduplicated list sorted by magnitude desc.
- `compute_recency_score(changed_at, now=None)` — pure function. Exponential decay: `exp(-elapsed_hours / 48)`. Range [0.0, 1.0].
- `compute_novelty_score(cursor_row, current_timestamp)` — pure function. 1.0 when cursor is None (never seen); decays toward 0.0 as `last_seen_at` approaches `current_timestamp`.
- `record_user_visit(session, *, user_id, entity_type, entity_key, state_hash)` — writes `personal_experience_cursor` via repo. This is how the system records "user saw this."

All async functions gated on `experience_composer_enabled`. Returns `[]`/`None` when off or session is None.

**Likely files.** `app/services/experience_change_detection_service.py`; `tests/test_services/test_experience_change_detection_service.py`.

**Flags.** `experience_composer_enabled` (gate; off ⇒ no changes detected, no cursors written).

**Validation (slice tests).** Gate off ⇒ empty list, no cursor rows; gate on ⇒ changes detected match seeded deltas; sub-materiality changes filtered (< 2% forecast drift ⇒ excluded); `compute_recency_score` returns 1.0 at t=0, ~0.5 at t=48h, approaches 0.0 for old timestamps; `compute_novelty_score` returns 1.0 for unseen items, 0.0 for just-seen items; `record_user_visit` upserts cursor with hash; read-only on all upstream tables (import firewall); null-session safe.

**Rollback.** `git revert` or `experience_composer_enabled=False` — change detection stops; existing cursor rows are harmless.

**SP-18 enforced.** SP-18c (writes only `personal_experience_cursor`); SP-18d (no upstream feedback — reads only).

**Commit.** `feat(18): Slice 18.3 — Change Detection`

---

### Slice 18.4 — Attention Scoring Service

**Objective.** Score every candidate item on all 7 dimensions. Pure computation over upstream data — no writes except to return scored dicts.

**Adds.** `experience_attention_scorer_service` with:
- `score_item(session, *, user_id, entity_type, entity_key, change_context=None, memory_context=None, run_override=None)` → dict with all 7 dimension scores + `experience_score` composite.
- `score_items(session, *, user_id, candidates, change_context=None, memory_context=None, run_override=None)` → list of scored dicts, sorted by `experience_score` desc.
- `compute_composite_score(dimension_scores, weights=None)` — pure function. Weighted sum with default weights from spec. Enforces weight bounds: `0.05 ≤ w ≤ 0.40`, sum == 1.0. Returns float in [0.0, 1.0].
- `validate_weights(weights)` — pure function. Returns `(ok, reason)`.
- `apply_attention_floor(scored_items)` — pure function. Items with `attention_priority > 0.8` are never ranked below position 5.
- `apply_novelty_reserve(scored_items, reserve_fraction=0.15)` — pure function. Ensures 15% of top slots go to items with no matching preference (anti-filter-bubble).

Scoring sources per dimension:

| Dimension | Read from |
|---|---|
| `attention_priority` | `decision_priority` (Phase 13) — highest priority for this entity |
| `personal_relevance` | `learned_preference` (Phase 15) — affinity × confidence for matching dimension |
| `recency_score` | `change_context` (from 18.3) — exponential decay from last change |
| `novelty_score` | `personal_experience_cursor` (18.2) — how new this is to this user |
| `revisit_score` | `memory_context` (from 18.6, or 0.0 if unavailable) — change × prior engagement |
| `memory_relevance` | `memory_context` (from 18.6, or 0.0 if unavailable) — research history strength |
| `portfolio_relevance` | `portfolio_positions` (Phase 10D) — position weight in user's portfolio |

Gated on `experience_attention_enabled`. Returns empty scored items (all dimensions 0.0) when off.

**Likely files.** `app/services/experience_attention_scorer_service.py`; `tests/test_services/test_experience_attention_scorer_service.py`.

**Flags.** `experience_attention_enabled` (gate; off ⇒ all scores 0.0).

**Validation (slice tests).** Gate off ⇒ all scores 0.0; all dimension scores in [0.0, 1.0]; composite score in [0.0, 1.0]; weight bounds enforced (0.05–0.40, sum=1.0); invalid weights rejected with reason; attention floor: `attention_priority > 0.8` ⇒ rank ≤ 5; novelty reserve: 15% of top slots reserved for non-preference items when ≥ 4 items scored; `portfolio_relevance` derived from position weight, not position value (no dollar amounts leaked); read-only on all upstream tables (import firewall); deterministic: same inputs produce same scores; null-session safe.

**Rollback.** `git revert` or `experience_attention_enabled=False` — all scores return 0.0.

**SP-18 enforced.** SP-18a (no advisory language in scores — scores are floats, not text), SP-18b (scores do not change truth), SP-18c (writes nothing), SP-18d (no upstream feedback).

**Commit.** `feat(18): Slice 18.4 — Attention Scoring`

---

### Slice 18.5 — Experience Composer + Explainability

**Objective.** The top-level orchestrator: assemble candidates, score, explain, gate, rank, and return the experience payload. Includes the explainability gate (spec §Explainability Framework).

**Adds.** Two services:

`experience_explainability_service` with:
- `build_experience_explanation(candidate, scores, change_context=None, memory_context=None)` — pure function. Returns `{why_seeing, why_now, what_changed, evidence, valid}`. Uses templates (not LLM prose). Returns `valid=False` when any of the four fields cannot be populated.
- `validate_experience_explanation(explanation)` — pure function. Returns `(ok, reason)`. Checks all four fields are non-empty, evidence is non-empty, no banned phrases.

`experience_composer_service` with:
- `compose_experience(session, *, user_id, surface="home", run_override=None)` → full experience payload dict.
- `assemble_candidates(session, *, user_id)` — gathers watchlist items, portfolio positions, recent research entities, active scenarios, active forecasts, decision priorities. Returns candidate list.

Composition pipeline:
1. `assemble_candidates` → candidate set
2. For each candidate: `attention_scorer.score_item` → dimension scores
3. For each scored candidate: `explainability.build_experience_explanation` → explanation
4. Gate: candidates with `explanation.valid == False` are blocked (logged but not surfaced)
5. Apply attention floor + novelty reserve
6. Sort by `experience_score` desc → assign final ranks
7. Return ranked, explained, gated payload

Gated on `experience_composer_enabled`. Returns `{items: [], blocked_count: 0, ...}` when off.

**Likely files.** `app/services/experience_explainability_service.py`; `app/services/experience_composer_service.py`; `tests/test_services/test_experience_explainability_service.py`; `tests/test_services/test_experience_composer_service.py`.

**Flags.** `experience_composer_enabled` (top-level gate).

**Validation (slice tests).**

*Explainability:*
- All four fields required and non-empty for `valid=True`.
- Missing `why_now` ⇒ `valid=False`.
- Missing `evidence` ⇒ `valid=False`.
- Template patterns produce deterministic text — same inputs, same output.
- No LLM prose: explanation text matches known template patterns.
- Banned-phrase AST scan (no buy/sell/hold/target-price in any template string).

*Composer:*
- Gate off ⇒ empty items list, zero blocked.
- Items failing explainability are blocked (logged with `explanation_valid=False`), never surfaced.
- Returned items are a subset of candidates — no items added that weren't candidates.
- Attention floor enforced in output.
- Novelty reserve enforced in output.
- Deterministic: same inputs produce same ranking.
- Output contains all 7 dimension scores per item.
- Read-only on all upstream tables (import firewall).
- Null-session safe.

**Rollback.** `git revert` or `experience_composer_enabled=False` — returns empty payload.

**SP-18 enforced.** SP-18a (banned-phrase scan on templates), SP-18b (ordering only — truth values byte-identical), SP-18c (writes nothing — composer is pure computation; journaling is 18.8's job), SP-18d (no upstream feedback).

**Commit.** `feat(18): Slice 18.5 — Experience Composer + Explainability`

---

### Slice 18.6 — Personal Memory Context + Session Continuity

**Objective.** Provide the "what was I doing last time?" layer. This is a **first-class Phase 18 feature** — not an afterthought. It answers: *What was I researching last time? What changed since my last visit? Can I resume my previous investigation? Where did my prior thesis work leave off?*

**Adds.** `personal_memory_context_service` with:

*Session Continuity (the user's research narrative):*
- `get_last_research_context(session, *, user_id, run_override=None)` → dict describing the user's most recent research activity: `{last_entity_key, last_entity_type, last_seen_at, last_surface, last_state_hash, days_since_last_visit}`. Reads from `personal_experience_cursor` (most recent row) + `user_signal_event` (most recent research signal). Returns `None` when no prior activity exists.
- `get_research_resumption_candidates(session, *, user_id, limit=5, run_override=None)` → list of entities the user was actively investigating, with what changed since they last looked. Each candidate includes `{entity_key, entity_type, last_seen_at, changes_since: [...], thesis_drift: float}`. This directly answers "resume previous investigation."
- `get_thesis_continuations(session, *, user_id, limit=5, run_override=None)` → list of previously analyzed tickers whose thesis (ticker_memory) has materially changed since the user's last analysis. Each includes `{ticker, last_analysis_at, thesis_changed: bool, change_summary: str}`. This answers "continue prior thesis work."

*Memory Relevance Scoring:*
- `compute_memory_relevance(session, *, user_id, entity_key, entity_type, run_override=None)` → float in [0.0, 1.0]. Higher when the user has more research history with this entity. Based on: signal event count for this entity, view count from cursor, recency of last interaction.
- `compute_revisit_score(session, *, user_id, entity_key, entity_type, change_magnitude=0.0, run_override=None)` → float in [0.0, 1.0]. Combines prior engagement strength with the magnitude of change since last visit. High when a previously-researched entity has changed significantly.
- `build_memory_context(session, *, user_id, entity_keys, run_override=None)` → dict mapping `entity_key → {memory_relevance, revisit_score, last_seen_at, view_count, research_history_depth}`. Bulk computation for the scorer (18.4).

All async functions gated on `experience_composer_enabled`. Returns `None`/`[]`/`{}` when off or session is None.

**Likely files.** `app/services/personal_memory_context_service.py`; `tests/test_services/test_personal_memory_context_service.py`.

**Flags.** `experience_composer_enabled` (gate).

**Validation (slice tests).** Gate off ⇒ `None`/`[]`/`{}`; no prior activity ⇒ `get_last_research_context` returns `None`; seeded research history ⇒ correct `last_entity_key` and `days_since_last_visit`; `get_research_resumption_candidates` returns only entities with prior engagement; `get_thesis_continuations` returns only tickers with material thesis change (memory diff); `compute_memory_relevance` returns 0.0 for unknown entities, higher for deeply-researched entities; `compute_revisit_score` returns 0.0 when no prior engagement, higher when prior engagement + material change; read-only on all upstream tables (`user_signal_event`, `personal_experience_cursor`, `ticker_memory` — all reads, no writes); null-session safe; tenant isolation (user A's research history does not appear in user B's context).

**Rollback.** `git revert`. Read-only service ⇒ inert. Composer degrades to `memory_relevance=0.0` and `revisit_score=0.0` for all items.

**SP-18 enforced.** SP-18c (writes nothing), SP-18d (no upstream feedback — reads only from Phase 9G/15 tables + Phase 18 cursors).

**Commit.** `feat(18): Slice 18.6 — Personal Memory Context + Session Continuity`

---

### Slice 18.7 — Personal Brief Builder

**Objective.** Generate a daily structured brief per user from the composer's ranked, explained output.

**Adds.** `personal_brief_builder_service` with:
- `build_daily_brief(session, *, user_id, brief_date=None, run_override=None)` → full brief dict (spec §Personal Brief). Calls `experience_composer.compose_experience` with `surface="brief"`, then structures the output into `what_changed`, `why_it_matters`, `deserves_attention`, and `can_be_ignored` sections.
- `should_generate_brief(session, *, user_id, brief_date)` → bool. Returns `False` if a brief already exists for this `(user_id, brief_date)` (idempotent gate).
- `store_brief_metadata(session, *, user_id, brief_date, items_surfaced, items_blocked, top_attention_item, run_reason="shadow")` → writes `personal_brief_snapshot` via repo.

Brief structure rules (from spec):
- `what_changed` — items with `recency_score > 0.5` AND material change detected.
- `why_it_matters` — items with `attention_priority > 0.5` AND valid explanation.
- `deserves_attention` — items with `attention_priority > 0.7`.
- `can_be_ignored` — only when user tracks > 20 entities; items with `experience_score < 0.2` and no material change.
- All text is templated from structured fields. No LLM prose.
- `run_reason="shadow"` until live rollout.

Gated on `experience_brief_enabled`. Returns `None` when off.

**Likely files.** `app/services/personal_brief_builder_service.py`; `tests/test_services/test_personal_brief_builder_service.py`.

**Flags.** `experience_brief_enabled` (gate; off ⇒ no briefs generated).

**Validation (slice tests).** Gate off ⇒ `None`; idempotent: second call for same `(user_id, brief_date)` returns existing brief, does not re-generate; brief contains all required sections; `can_be_ignored` absent when user tracks ≤ 20 entities; all brief items passed explainability gate; `run_reason="shadow"` on all stored snapshots; `personal_brief_snapshot` row created with correct counts; no LLM prose (all text matches template patterns); banned-phrase AST scan; null-session safe.

**Rollback.** `git revert` or `experience_brief_enabled=False` — brief generation stops; existing snapshot rows are inert.

**SP-18 enforced.** SP-18a (no advisory language in briefs), SP-18c (writes only `personal_brief_snapshot`), SP-18d (no upstream feedback).

**Commit.** `feat(18): Slice 18.7 — Personal Brief Builder`

---

### Slice 18.8 — Experience Shadow Journal

**Objective.** Journal what the experience layer *would* surface, without delivering it. The shadow observation layer (modeled on Phase 15 Slice 15.9).

**Adds.** `experience_shadow_journal_service` with:
- `journal_experience_event(session, *, user_id, surface, scored_item, explanation, run_override=None)` → writes one `personal_experience_event` row via repo. All 7 dimension scores recorded. `run_reason="shadow"` hardcoded.
- `journal_composed_experience(session, *, user_id, surface, composed_result, run_override=None)` → journals all items from a composed experience (both surfaced and blocked). Returns list of inserted rows.
- `classify_experience_transition(current_event, previous_event=None)` — pure function. Returns transition type: `"new_item"`, `"score_increased"`, `"score_decreased"`, `"item_removed"`, `"explanation_changed"`, or `None` for no material change.

Deduplication: recent events within `_DEDUP_WINDOW_SECONDS` (3600) with the same `(user_id, surface, item_ref, experience_score)` are skipped.

Gated on `experience_shadow` (True by default — shadow is always on). Returns `[]` when the gate is off or session is None.

**Likely files.** `app/services/experience_shadow_journal_service.py`; `tests/test_services/test_experience_shadow_journal_service.py`.

**Flags.** `experience_shadow` (on by default — journals everything).

**Validation (slice tests).** Shadow on ⇒ events journaled with all 7 scores; shadow off ⇒ no rows; `run_reason="shadow"` on all rows; deduplication within window (same item+score ⇒ 1 row); different items ⇒ separate rows; blocked items journaled with `explanation_valid=False`; `classify_experience_transition` returns correct types; append-only (no `.update`/`.delete` in module — AST verified); null-session safe.

**Rollback.** `git revert`. Journal rows are inert (no consumer).

**SP-18 enforced.** SP-18c (writes only `personal_experience_event`), SP-18d (no upstream feedback).

**Commit.** `feat(18): Slice 18.8 — Experience Shadow Journal`

---

### Slice 18.9 — Experience Calibration

**Objective.** Make experience quality measurable: scoring accuracy, explainability coverage, ranking stability, attention floor enforcement. Append-only metrics over the shadow window (modeled on Phase 15 Slice 15.10).

**Adds.** `experience_calibration_service` with:
- `calculate_scoring_accuracy(session, *, user_id, run_override=None)` → dict. Compares shadow-surfaced items against subsequent user engagement (from `user_signal_event`). `accuracy = engaged_count / surfaced_count`. Returns `{accuracy, engaged_count, surfaced_count, sufficient_samples, min_samples}`.
- `calculate_explainability_coverage(session, *, user_id, run_override=None)` → dict. `coverage = valid_count / total_count` from `personal_experience_event`. Returns `{coverage, valid_count, blocked_count, total_count, sufficient_samples}`.
- `calculate_ranking_stability(session, *, user_id, run_override=None)` → dict. Measures rank variance across consecutive journal entries for the same items. `stability = 1 - mean_rank_variance`. Returns `{stability, items_tracked, sufficient_samples}`.
- `calculate_attention_floor_compliance(session, *, user_id, run_override=None)` → dict. Checks that `attention_priority > 0.8` items were ranked ≤ 5 in all journal entries. Returns `{compliance_rate, violations, total_checks, sufficient_samples}`.
- `summarize_experience_calibration(session, *, user_id, run_override=None)` → full calibration summary bundling all four metrics + `calibration_schema=1` + `generated_at`.

All metrics report `insufficient_samples` below minimum evidence counts.

**Likely files.** `app/services/experience_calibration_service.py`; `tests/test_services/test_experience_calibration_service.py`.

**Validation (slice tests).** No journal entries ⇒ all metrics `None` + `sufficient_samples=False`; seeded engaged outcomes ⇒ correct accuracy; all events with valid explanations ⇒ `coverage=1.0`; floor violations seeded ⇒ `compliance_rate < 1.0`; stable ranking ⇒ `stability` near 1.0; no `.update`/`.delete` in module (AST); reads only from Phase 18 tables + `user_signal_event` (import firewall); null-session safe.

**Rollback.** `git revert`. Read-only metrics ⇒ inert.

**SP-18 enforced.** SP-18c (writes nothing), SP-18d (no upstream feedback).

**Commit.** `feat(18): Slice 18.9 — Experience Calibration`

---

### Slice 18.10 — Observability + Shadow Validation

**Objective.** Close the phase: observability snapshot, admin route, the standalone validation script, and the operational runbook. The Phase 15 Slice 15.11 analogue.

**Adds.**

`personal_experience_observability_service.build_personal_experience_snapshot(session)`:
- **flags** — all 6 `experience_*` config flags with current values.
- **metrics** — `personal_experience_cursor` count, `personal_experience_event` count, `personal_brief_snapshot` count, event count by surface, event count by `run_reason`, brief count by `run_reason`, latest cursor timestamp, latest event timestamp, latest brief timestamp, blocked event count (`explanation_valid=False`).
- **safe_state** — structured sub-checks:
  - `shadow_only`: `experience_shadow=True` AND NOT `experience_home_enabled`
  - `no_live_personalization`: NOT `experience_home_enabled`
  - `no_truth_mutation`: always True (structural — confirmed by flag gates)
  - `no_recommendation_consumers`: NOT bool(`experience_targets_enabled`)
  - `no_upstream_feedback`: always True (structural — confirmed by import audit)
  - `overall`: AND of all sub-checks
- **db_available**, **schema_version**, **snapshot_utc**, **disclaimer**.

`GET /admin/personal-experience-status` — delegates to observability service. Read-only, DB-down-safe.

`tests/validate_18_personal_experience_shadow.py` (exit 0 required) — comprehensive shadow validation:

| # | Check | Description |
|---|---|---|
| 1 | `db_table_count >= 56` | Schema includes Phase 18 tables |
| 2 | Phase 18 tables exist | `personal_experience_cursor`, `personal_experience_event`, `personal_brief_snapshot` |
| 3 | All Phase 18 services importable | 8 services + 1 repo |
| 4 | All flags inert | 6 flags at safe defaults |
| 5 | No recommendation imports | No conviction/order/execution/stance in any service |
| 6 | No truth-table mutation imports | No forecast/similarity/scenario/decision write functions |
| 7 | No forecast write-back | No `add_forecast`/`upsert_forecast` in any service |
| 8 | No similarity write-back | No `add_similarity`/`upsert_similarity` in any service |
| 9 | No scenario write-back | No `add_scenario_snapshot`/`upsert_scenario` in any service |
| 10 | No decision write-back | No `add_decision`/`upsert_decision` in any service |
| 11 | No target-price/trade language | AST banned-phrase scan across all services |
| 12 | No public experience route | No `/experience` or `/personalization` route outside `/admin/` |
| 13 | Admin status route present | `/admin/personal-experience-status` in `api.py` |
| 14 | `safe_state.overall` True | Null-session snapshot returns overall=True |
| 15 | No Notification rows | No Phase 18 service writes to Notification |
| 16 | Explainability invariants | `build_experience_explanation` exists, is sync/pure |
| 17 | Attention floor invariant | `apply_attention_floor` exists, enforces priority > 0.8 → top 5 |
| 18 | Novelty reserve invariant | `apply_novelty_reserve` exists, enforces 15% reserve |
| 19 | Weight bounds invariant | `validate_weights` rejects weights outside 0.05–0.40 |
| 20 | Calibration append-only | No `.update`/`.delete` in calibration service |
| 21 | Session continuity functions exist | `get_last_research_context`, `get_research_resumption_candidates`, `get_thesis_continuations` all present |
| 22 | No upstream feedback (SP-18d) | No Phase 18 service imports a Phase 11–15 write function |

`docs/PHASE_18_PERSONAL_EXPERIENCE_SHADOW_ROLLOUT.md` — operational runbook.

**Likely files.** `app/services/personal_experience_observability_service.py`; `app/api.py` (+1 read-only route); `tests/test_services/test_personal_experience_observability_service.py`; `tests/validate_18_personal_experience_shadow.py`; `docs/PHASE_18_PERSONAL_EXPERIENCE_SHADOW_ROLLOUT.md`.

**Validation (slice tests).** Null-session ⇒ db_available=False, all counts 0, safe_state.overall=True; populated DB ⇒ counts reflect inserts; schema_version is int; no secret-like keys; admin route calls `build_personal_experience_snapshot`; disclaimer present.

**Rollback.** `git revert`. Read-only observability + script + doc ⇒ inert.

**SP-18 enforced.** All of SP-18, aggregated and asserted.

**Commit.** `feat(18): Slice 18.10 — Observability + Shadow Validation`

---

## 3. Flags (consolidated)

| Flag | Default | Turned on at | Effect |
|---|---|---|---|
| `experience_composer_enabled` | `False` | Stage 1 | enable change detection + cursor writes |
| `experience_attention_enabled` | `False` | Stage 2 | enable 7-dimension attention scoring |
| `experience_shadow` | `True` | (already on) | journal all surfacing decisions to event log |
| `experience_brief_enabled` | `False` | Stage 3 | generate daily brief snapshots |
| `experience_targets_enabled` | `""` | Stage 5 only | comma-separated list of live experience surfaces |
| `experience_home_enabled` | `False` | Stage 5 only | **deliver** personalized home experience to users |

Default posture on deploy: nothing detected, nothing scored, no surface changed — fully inert, identical to the Phase 15 ship posture.

---

## 4. Rollout stages

No user-visible personalization until Stage 5, and only after the acceptance gate is green.

| Stage | Slices live | Flags on | Effect | Exit criterion |
|---|---|---|---|---|
| **0 — Inert baseline** | 18.1–18.2 | none | tables + repos deployed, dormant | `validate_18` exits 0; table count 56 |
| **1 — Change detection** | +18.3 | `composer` | changes detected, cursors populate | cursor rows appear; zero truth writes |
| **2 — Shadow scoring** | +18.4–18.6 | `attention` | scoring pipeline runs, memory context available; **no surface change** | scores computed correctly; session continuity returns sensible results |
| **3 — Shadow brief + journal** | +18.7–18.8 | `brief`, `shadow` | briefs generated + events journaled; compare would-be experience vs current product | event rows with `run_reason=shadow`; brief snapshots populated |
| **4 — Acceptance** | +18.9–18.10 | (no new flags) | full validation suite over a real shadow window | all 22 validation checks pass; `safe_state` green; calibration metrics stable |
| **5 — Delivery** | (no new slices) | `home`, `targets` (per-surface, per-cohort) | personalized experience visible to users, cohort-ramped | live-engagement non-regression; instant rollback ready |

Stage 5 ramps per-surface and per-cohort (internal → opt-in beta → percentage), each step gated on engagement non-regression and zero safety-gate violations.

---

## 5. Acceptance criteria

### 5.1 Per-slice gate (every slice)

- Slice's own pytest suite green **and** the cumulative Phase 18 suite green.
- `validate_18_personal_experience_shadow.py` exits 0 (from 18.10 onward; earlier slices run the subset that exists).
- AST safety tests green: no truth-write import, no conviction/order/execution import, no banned-phrase string constant.
- All flags still inert by default; merging the slice changes nothing a user sees.
- Commit checkpoint recorded.

### 5.2 Phase-level acceptance (gate to Stage 5)

- [ ] `validate_18_personal_experience_shadow.py` exits 0 with all 22 checks passing.
- [ ] All Phase 18 pytest suites pass.
- [ ] `GET /admin/personal-experience-status` returns `safe_state.overall: true` with every sub-check true.
- [ ] **No-truth-mutation proven:** zero writes to any forecast/similarity/scenario/decision/memory table across all Phase 18 services (AST + runtime).
- [ ] **no-forecast-write / no-similarity-write / no-scenario-write / no-decision-write** each individually green.
- [ ] Scoring accuracy ≥ baseline over a real shadow window.
- [ ] Explainability coverage ≥ 95% (≤ 5% blocked items).
- [ ] Ranking stability ≥ 0.85 (low rank variance across consecutive runs).
- [ ] Attention floor compliance = 100% (no violations).
- [ ] Every surfaced item has all four explanation fields, non-empty evidence, and no banned phrases.
- [ ] Weight bounds enforced: no weight outside [0.05, 0.40], sum == 1.0.
- [ ] Novelty reserve enforced: ≥ 15% of top slots go to non-preference items.
- [ ] Session continuity functions return correct results for seeded research history.
- [ ] Tenant isolation verified: user A's experience does not leak into user B's.
- [ ] `personal_experience_event.run_reason == "shadow"` everywhere until Stage 5.
- [ ] No buy/sell/hold/target-price/position-size language anywhere; no portfolio recommendation path (SP-18a).
- [ ] No upstream feedback path: no Phase 18 service writes to any Phase 11–15 table (SP-18d).

Only when every box is checked may `experience_home_enabled` be considered, per-surface and per-cohort.

---

## 6. Rollback playbook

| Level | Action | Effect | Data impact |
|---|---|---|---|
| **Instant (surface)** | `experience_home_enabled=False` + `experience_targets_enabled=""` | any surface returns to current (unpersonalized) experience | none |
| **Stop briefs** | `experience_brief_enabled=False` | brief generation stops | none (snapshot rows inert) |
| **Stop scoring** | `experience_attention_enabled=False` | all scores return 0.0 | none |
| **Stop detection** | `experience_composer_enabled=False` | change detection stops, no cursors written | none (cursor rows harmless) |
| **Code-level** | `git revert <slice commit>` | removes the slice | none — additive tables only, no source `ALTER` |
| **Data-level (optional)** | retention sweep / truncate the three Phase 18 tables | clears experience state | confined to the three additive tables; zero truth impact |

Because the experience layer reads upstream data and produces only ordering + explanations, removing it can never change correctness — only the user's view of what appears first. Because the schema is additive-only, no rollback ever requires a source-table migration.

---

## 7. Validation framework detail

### Personalization validation (enforced in 18.4, 18.5, 18.10)

- Rank stability: same inputs → same ranking (deterministic sort)
- Weight bounds: `0.05 ≤ w ≤ 0.40`, sum == 1.0
- Novelty reserve: ≥ 15% of top-N slots for non-preference items
- Attention floor: `attention_priority > 0.8` → rank ≤ 5
- User isolation: user A's scores do not appear in user B's experience

### Explainability validation (enforced in 18.5, 18.10)

- Completeness: `why_seeing`, `why_now`, `what_changed`, `evidence` all non-empty
- Accuracy: evidence references exist in source tables (resolvable)
- Determinism: same inputs → same explanation text
- No LLM prose: text matches a known template pattern
- Block rate: items failing the gate are logged (`explanation_valid=False`) but never surfaced

### Ordering validation (enforced in 18.4, 18.5, 18.10)

- Read-only audit: no write-path to upstream tables (import firewall)
- Idempotency: calling `compose_experience` twice → same ranking
- Score range: all 7 dimensions in [0.0, 1.0]; composite in [0.0, 1.0]
- No side effects: `compose_experience` creates no upstream table mutations

### Drift validation (enforced in 18.3, 18.9, 18.10)

- True positive rate: material changes are detected (seeded forecast drift → detected)
- Materiality gate: sub-2% forecast drift filtered out
- Staleness check: cursor timestamps are current
- Hash consistency: `last_state_hash` matches actual entity state

### No-advice validation (enforced in every slice, aggregated in 18.10)

- AST scan: no banned phrases in non-docstring string constants
- Import audit: no conviction/order/execution/stance imports
- Template audit: no template produces advisory language
- Write audit: Phase 18 writes only to its own three tables
- Feedback audit: no Phase 18 output feeds back into Phases 11–15

---

## 8. Estimated test scope

| Slice | Service(s) | Est. tests |
|---|---|---|
| 18.1 | Schema | ~45 |
| 18.2 | Repos | ~60 |
| 18.3 | Change Detection | ~70 |
| 18.4 | Attention Scoring | ~80 |
| 18.5 | Composer + Explainability | ~85 |
| 18.6 | Memory Context + Session Continuity | ~75 |
| 18.7 | Brief Builder | ~65 |
| 18.8 | Shadow Journal | ~60 |
| 18.9 | Calibration | ~70 |
| 18.10 | Observability + Validation | ~50 |
| **Total** | | **~660** |

Each slice carries AST safety tests (banned phrases, import firewalls, append-only verification), null-session tests, flag-gate tests, and tenant-isolation tests in addition to functional tests.

---

## 9. Risks

| Risk | Impact | Slice where mitigated |
|---|---|---|
| Filter bubble | User only sees familiar items | 18.4 (novelty reserve), 18.5 (reserve enforcement) |
| Stale personalization | Preferences decay but experience doesn't adapt | 18.3 (recency scoring), 18.6 (revisit scoring) |
| Explainability failure | Items surfaced without valid explanation | 18.5 (gate blocks invalid items) |
| Truth distortion perception | User mistakes ordering for advice | SP-18b disclaimer in all output, no advisory language |
| Performance degradation | Scoring pipeline too slow | Pre-compute during loop tick, cache composites |
| Cross-user leakage | Tenant isolation failure | User-scoped queries, tenant isolation tests in every slice |
| Feedback loop | High-relevance items dominate | Phase 15 `surface_was_personalized` flag on new signals |
| Session state corruption | Cursor hashes drift from real state | 18.3 hash re-computation, 18.9 hash consistency checks |

---

## 10. Commit checkpoint discipline

One commit per slice, message `feat(18): Slice 18.N — <name>`, after that slice's suite **and** the cumulative suite are green and the validation script (where present) exits 0 — identical to the cadence used through Phases 13–15. Do not begin slice N+1 until slice N is committed.

---

## 11. Likely-files index (whole phase)

| Area | Files |
|---|---|
| Schema | `app/db/models.py` (+3 classes, 0 edits to existing tables) |
| Flags | `app/config.py` (+6 flags) |
| Repositories | `app/db/repositories/personal_experience_repo.py` |
| Services | `app/services/experience_change_detection_service.py`, `experience_attention_scorer_service.py`, `experience_explainability_service.py`, `experience_composer_service.py`, `personal_memory_context_service.py`, `personal_brief_builder_service.py`, `experience_shadow_journal_service.py`, `experience_calibration_service.py`, `personal_experience_observability_service.py` |
| Admin route | `app/api.py` (+1 read-only route: `GET /admin/personal-experience-status`) |
| Tests | `tests/test_services/test_personal_experience_schema.py`, `test_personal_experience_repo.py`, `test_experience_change_detection_service.py`, `test_experience_attention_scorer_service.py`, `test_experience_explainability_service.py`, `test_experience_composer_service.py`, `test_personal_memory_context_service.py`, `test_personal_brief_builder_service.py`, `test_experience_shadow_journal_service.py`, `test_experience_calibration_service.py`, `test_personal_experience_observability_service.py` |
| Validation | `tests/validate_18_personal_experience_shadow.py` |
| Runbook | `docs/PHASE_18_PERSONAL_EXPERIENCE_SHADOW_ROLLOUT.md` |

---

*End of Phase 18 implementation plan. Plan only — no code, no migrations, no implementation. Build begins at Slice 18.1.*
