# Phase 11 — Similarity Engine — Implementation Plan

**Phase:** 11 · Similarity & Resemblance Intelligence
**Status:** Plan — not yet implemented
**Spec basis:** `docs/PHASE_11_SIMILARITY_ENGINE_SPEC.md`
**Audience:** Principal/staff engineers, backend + frontend
**Scope:** Plan only. No code, no migrations, no implementation in this document.

**Convention basis:** All file paths, flags, and table conventions reference the existing codebase. Phase 11 reuses the **9G evidence engine** (`app/evidence_engine.py` — `SetupFingerprint`, `build_fingerprint`, `_score_analog`, `retrieve_historical_analogs`) as its scoring kernel **wholesale**, the **9G dossier facets** + `historical_analogs` + `cross_exposures` as its only analytical inputs, the **10A loop** tick as its rebuild trigger, the **10C delivery spine** (`loop_delivery_service`, `digest_batch_service`, `in_app_delivery_service`) as its only delivery path, the **10D observability pattern** (`*_observability_service` + `/admin/*-status` + `validate_*_shadow.py`), and the **16/17 identity + shadow-flag** discipline. **It computes no new company-level analysis and writes back to no source table.**

---

## PART 0 — STANDING SAFETY PROPERTIES

> **SP-1 · No new primary facts.** Phase 11 adds exactly two derived tables (`similarity_feature_vector`, `similarity_edge`) and **zero columns on any existing table**. Every slice carries a *no-write-back* gate: a property test asserting the full source substrate is byte-identical after an engine run. A PR that writes to a dossier/analog/exposure/portfolio table fails the build. (Spec §2, principle #4.)

> **SP-2 · Reuse, do not fork.** Targets T2/T4/T5 call the *existing* `build_fingerprint()` and the *existing* `_score_analog()` generalisation — they do not re-derive fingerprint or scoring logic. `historical_analogs` is read-only library data; Phase 11 never seeds, edits, or migrates it. (Spec §2 grounding note, principle #3.)

> **SP-3 · Shadow-first, inert by default.** Every slice through Slice 8 lands with all `similarity_*` flags at safe defaults: `similarity_build_enabled=false`, `similarity_scoring_enabled=false`, `similarity_delivery_enabled=false`, `similarity_targets=""`. The engine can build vectors and materialise edges for weeks while every result is unread by any surface. The consequential flips are a **config sequence in PART 5**, never a slice. This is 10C/10D's "compute for weeks with delivery off" discipline.

> **SP-4 · Similarity never influences forecasts during Phase 11 (the defining boundary).** No `similarity_edge` is ever read by any forecasting, scenario, ranking-of-outcomes, or conviction-scoring path in this phase. Edges are **descriptive only**. This is enforced structurally, not by convention:
> - No forecasting consumer is wired in any slice (there is no forecasting system to wire — the boundary is preserved by *not building the bridge*).
> - A standing **dependency-direction test** asserts that no module under `app/services/` *other than* the Phase 11 surfaces in PART 3 imports the similarity reader, and that the similarity reader imports nothing from a forecasting/conviction module.
> - The disanalogy + floor discipline (Spec §6.3) keeps every edge framed as resemblance, never prediction. (Spec §8, principle #8; risk R9.)

> **SP-5 · Validation + rollback for every slice.** Each slice below states its **Validation** (what proves it correct and inert) and **Rollback strategy** (how to revert with zero data loss and zero user impact) explicitly. Derived tables are always droppable-and-rebuildable from substrate (Spec §3.2, principle #6), so rollback never risks a primary fact.

---

## PART 1 — BUILD SLICES

> **Table-count contract.** Current baseline is **38 tables** (post-17, asserted by `validate_17_billing_shadow.py`). Slice 1 raises it to **40**. `/health` `db_table_count` is asserted at each relevant slice.

### Slice 1 — Schema: derived tables, dark (no read, no write)

Create the two derived tables and nothing else. Both are inert — no builder, no scorer, no reader.

**Files:**
- `app/db/migrations/011_similarity_engine.sql` (new — `similarity_feature_vector`, `similarity_edge`; additive `CREATE TABLE IF NOT EXISTS`; indexes per PART 2)
- `app/db/models.py` (add `SimilarityFeatureVector`, `SimilarityEdge` ORM classes — mirrors the dossier facet model style; `user_id` nullable for identity scoping)
- `app/config.py` (add the four `similarity_*` flags at safe defaults — see PART 5)

**Validation:** `db_table_count` rises by 2 (38 → 40) on `/health`; app boots clean; migration idempotent (run twice → no error, no duplicate index); all existing tests pass untouched; `validate_17_billing_shadow.py` still green (no regression to prior surfaces). Structural: both tables carry `*_schema` invalidation columns (`vector_schema`, `score_schema`) and TTL columns (`built_at`, `expires_at` on edges).

**Rollback strategy:** None needed — additive `IF NOT EXISTS` DDL, unread by any layer. Revert = drop the two tables (or leave them empty and harmless). No source table touched; no behavior changes.

---

### Slice 2 — Feature Builder for T4 (failure-mode), shadow-write only

The lowest-risk target first: `dossier_failure_mode.analog_id` already links to `historical_analogs`, so the substrate is half-built. Build feature vectors for the failure-mode target only; write them behind `similarity_build_enabled`; **nothing reads them.**

**Files:**
- `app/services/similarity_feature_builder.py` (new — `build_feature_vector(target_type, entity, substrate) → SimilarityFeatureVector`; for T4 it calls the existing `build_fingerprint()` and widens the result into the typed `categorical`/`tag_set`/`numeric` shape; pure, idempotent)
- `app/db/repositories/similarity_repo.py` (new — `upsert_feature_vector`, `get_feature_vector`, `mark_vector_dirty`; null-session-safe, mirrors `dossier_repo` style)

**Validation:** Unit: a failure-mode entity with known `analog_id` + `sequence_stage` produces a vector whose `tag_set` equals the analog's `concern_tags` and whose `source_versions` records the contributing `relevance_at_match`; an entity with no dossier produces an empty vector (no crash). **SP-1 gate:** no-write-back property test — `dossier_failure_mode` + `historical_analogs` byte-identical after a build pass. **SP-3 gate:** with `similarity_build_enabled=false`, the builder is a no-op (zero rows written). Build latency recorded.

**Rollback strategy:** Vectors are write-only dead weight. Revert = set `similarity_build_enabled=false` (instant, no redeploy) or unregister the builder. Existing vectors are unread; drop the table content if desired. No source data risk.

---

### Slice 3 — Similarity Scorer (generalised evidence engine), shadow-materialise

Generalise `_score_analog()` into a multi-target scorer and materialise T4 edges behind `similarity_scoring_enabled`. **No surface reads edges yet.**

**Files:**
- `app/services/similarity_scorer.py` (new — `score(query_vector, candidate_vector, weighting_profile) → (score, contributions, disanalogy)`; direct generalisation of `_score_analog`: Jaccard on `tag_set`, exact/sibling on `categorical`, `1−|a−b|` on `numeric`, quality boost, flat disanalogy penalty, clamp [0,1]; emits the additive `contributions` decomposition — Spec §6.1)
- `app/services/similarity_weighting.py` (new — versioned per-target weighting profiles in config form, each carrying `score_schema`; the production analog weights `0.40/0.30/0.15/0.10/0.05` become the default T4 profile — Spec §5.1 grounding note)
- `app/services/similarity_ranker.py` (new — relevance floor, diversity (one candidate per dominant feature class), top-K, deterministic tie-break (Spec §5.3); writes `similarity_edge` rows with TTL)
- `app/db/repositories/similarity_repo.py` (extend — `upsert_edge`, `get_edges_for_query`, `expire_edges`)

**Validation:** Unit: two vectors with known shared tags score to the hand-computed composite; `contributions` partials sum (± quality/disanalogy) to `score` within tolerance (Spec §10.4 reconciliation); an empty `contributions` list raises/skips and is **never persisted** (orphan-score gate); below-floor candidates collapse to a `floor_passed=false` weak state, not a forced row; identical substrate + profile → identical scores and ranks (determinism). **SP-4 gate:** dependency-direction test — `similarity_scorer`/`ranker` import nothing from any forecasting/conviction module. Shadow integration: with `similarity_scoring_enabled=true` but `similarity_delivery_enabled=false`, T4 edges materialise and are visible only via the Slice 8 admin snapshot.

**Rollback strategy:** Edges are a TTL cache (Spec §3.2). Revert = `similarity_scoring_enabled=false` (instant) → materialisation halts, existing edges expire by TTL and are unread. Dropping the table degrades latency only, never correctness. No source touched.

---

### Slice 4 — Invalidation Controller (loop-driven freshness)

Wire vector/edge invalidation into the **existing 10A loop tick** — no second scheduler. For each ticker whose dossier moved, mark its vector dirty and expire dependent edges; the next loop pass rebuilds.

**Files:**
- `app/services/similarity_invalidation.py` (new — subscribes to `company_dossier.row_version` bumps, `DossierRevision` writes, `dossier_catalyst` lifecycle transitions, regime changes; marks vectors dirty, expires edges)
- `app/services/loop_*` integration point (extend the existing loop step registration — one idempotent "rebuild dirty similarity vectors + re-rank" call reusing the loop's lock service, repos, scheduler; Spec §4.3)

**Validation:** Unit: a `row_version` bump on a ticker's dossier marks exactly that ticker's vector dirty and expires only its edges (no fan-out beyond dependents); a `source_versions` mismatch forces rebuild on next read; a `vector_schema`/`score_schema` bump invalidates globally (Spec §10.3). Integration: drive a synthetic loop tick with a dossier update on a T4-clustered ticker → its vector rebuilds, its edges re-rank, all in shadow. **SP-3 gate:** with build/scoring flags off, the loop step is a no-op. No new scheduler introduced (grep gate: no `cron`/scheduler registration outside the existing loop).

**Rollback strategy:** Revert the loop-step registration — similarity stops refreshing but banked vectors/edges remain valid and inert. The loop itself is unaffected (additive step). Instant via flag; no redeploy needed to neutralise (flags gate the step body).

---

### Slice 5 — Targets T1 + T2 (company, thesis), shadow

Extend the builder/scorer to company and thesis targets. Reuses the same kernel; only the feature projection differs. Still shadow — no surface reads.

**Files:**
- `app/services/similarity_feature_builder.py` (extend — T1 from `company_dossier` + moat/variant/durability facets; T2 from `thesis_versions` + `dossier_core_debate` + `dossier_variant`, reusing `build_fingerprint` for the setup features)
- `app/services/similarity_weighting.py` (extend — default T1 and T2 weighting profiles, each `score_schema`-stamped)
- `app/config.py` (`similarity_targets` now accepts `failure_mode,company,thesis`)

**Validation:** Unit: a T1 query excludes self (Spec §1.1); a T1 result set obeys the diversity constraint (no N variants of one feature class); a T2 edge between a current thesis and a historical `thesis_version` carries a disanalogy naming the strongest divergence; identity scoping — a user's query never returns another user's owned dossier, while the shared `historical_analogs` library is visible to all (Spec §3.4, §10.1). **SP-1 gate:** no-write-back over the widened substrate. Score distributions per target logged via the admin snapshot; non-degenerate (not all-equal, not all-max).

**Rollback strategy:** `similarity_targets` is a config list — remove `company,thesis` to drop those targets instantly, leaving T4 live or all dark. Vectors/edges for dropped targets expire unread. No source data risk; no redeploy.

---

### Slice 6 — Read API + dossier "Resembles" facet (shadow-readable, internal only)

Introduce the **single** similarity reader and expose it on the dossier render — but gated so only internal users see it while `similarity_delivery_enabled=false`. This is the first *read* path.

**Files:**
- `app/services/similarity_read_service.py` (new — the *only* module any surface calls; `get_resembles(entity_key, target_types) → List[edge view]`; reads materialised edges, renders headline + disanalogy; never computes inline on the hot path; entitlement-gated depth per Spec §3.4)
- `app/api.py` (extend the dossier render to include a `resembles` facet sourced from `similarity_read_service`; omitted entirely when no above-floor edge exists — "no strong resemblance found", never a forced low-confidence row)

**Validation:** Unit: the facet is absent when all edges are below floor; present (top-K, rank-ordered, each with headline + disanalogy) otherwise; every rendered edge has non-empty `contributions` and a reachable `source_versions` provenance (Spec §6.2 gates); rendered strength language is a pure function of the score band (language-magnitude lock, Spec §10.4). **SP-4 gate:** dependency-direction test confirms `similarity_read_service` is imported only by the PART 3 surfaces and imports no forecasting module. Internal-user gating verified (mirrors `LOOP_INTERNAL_USER_IDS`).

**Rollback strategy:** Revert the dossier render extension — the dossier falls back to its existing facets, no `resembles` section. The reader is additive and unread elsewhere. Instant; the read path is gated behind the internal-user set + flags.

---

### Slice 7 — Delivery integration (brief / watchlist / portfolio / inbox / digest), shadow

Wire similarity into the existing delivery surfaces, **transition-only** (fire on an edge first crossing the floor), all behind `similarity_delivery_enabled=false`. Reuses the 10C/10D delivery spine and dedup — no new pipeline.

**Files:**
- `app/services/morning_brief_service.py` (extend — a "Pattern echoes" line inside *What Changed* / *Debate Shifts* when a watched name newly resembles a prior thesis or active failure sequence; suppressed below floor)
- `app/services/portfolio_insight_service.py` (extend — augment existing exposure clusters with regime/failure-mode resemblance lines; T6 portfolio-to-portfolio explicitly **not** wired)
- `app/services/in_app_delivery_service.py` + `app/services/digest_batch_service.py` (extend — a similarity delivery candidate is emitted only on a *new strong* edge (state transition), subject to the existing relevance + dedup + content-hash gating; Spec §7 principle #7)
- watchlist row render (extend — "echoes N prior setups" chip → opens contribution detail)

**Validation:** Unit: a delivery candidate fires only on a floor-crossing transition, never on steady-state existence; a similarity event flows through the existing dedup/content-hash path (no double-send); the brief line is omitted when no above-floor edge exists; quiet-hours/cap/floor apply exactly as for a company alert; cap overflow coalesces into the existing digest bucket. **SP-4 gate:** the portfolio surface reads similarity for *description only* — a structural test asserts no similarity field feeds any portfolio ranking/health/forecast computation. Shadow integration: drive a full overnight → brief carries a "Pattern echoes" line, watchlist carries chips, inbox/digest resolve candidates — all as shadow/`delivered_shadow`, zero external send.

**Rollback strategy:** `similarity_delivery_enabled=false` keeps everything in shadow regardless. Revert the surface extension calls — brief falls back to its existing five sections, watchlist drops the chip, no inbox/digest similarity events. The 10C/10D delivery paths are strictly unaffected (additive). Instant, no redeploy for the shadow flag.

---

### Slice 8 — Observability & shadow validator

Mirror the 10D/17 observability discipline: one admin snapshot + one standalone validator.

**Files:**
- `app/services/similarity_observability_service.py` (new — `build_similarity_snapshot(session) → dict`: vector coverage % by target, edge counts by target, floor pass-rate, **mean `contributions` per edge (must be > 0 — the orphan-score gate)**, stale-vector count, `similarity_*` flag states, `safe_state` (= all delivery flags off); never raises, null-object on `session=None` — the 10C/10D observability discipline; **no secret values**)
- `app/api.py` (add `GET /admin/similarity-status`)
- `tests/validate_11_similarity_shadow.py` (new — runnable as a script + module, path-setup at top per the 17 validator; checks: `db_table_count=40`, both similarity tables exist, scoring kernel reuse (imports `evidence_engine`), all `similarity_*` flags false, `safe_state=true`, zero orphan scores, no-write-back holds, dependency-direction boundary holds (SP-4))

**Validation:** Admin endpoint shows all PART-4 metrics; mean contributions per edge > 0; orphan-score count = 0; `safe_state=true`; `validate_11_similarity_shadow.py` exits 0 against staging. Snapshot never raises on `session=None` (returns zeros, `db_available=false`). `validate_17_billing_shadow.py` still green (prior surface untouched).

**Rollback strategy:** Observability is additive and read-only; reverting removes visibility but breaks no path. The validator is a test artifact. No production path depends on either.

---

## PART 2 — DATABASE PLAN

### New tables (2) — all additive, no existing table modified

| Table | Purpose | Key columns |
|---|---|---|
| `similarity_feature_vector` | typed per-(target, entity) feature cache | `target_type`, `entity_key`, `categorical` (json), `tag_set` (json), `numeric` (json), `text_anchor`, `source_versions` (json), `vector_schema`, `built_at`, `user_id` |
| `similarity_edge` | scored, explained relation (TTL cache) | `target_type`, `query_key`, `candidate_key`, `score`, `rank`, `contributions` (json), `headline`, `disanalogy`, `floor_passed`, `score_schema`, `built_at`, `expires_at`, `user_id` |

### Indexes

- `similarity_feature_vector`: unique `(target_type, entity_key, user_id)`; index on `vector_schema` (global invalidation sweep).
- `similarity_edge`: index `(target_type, query_key, user_id)` (the hot read); index `expires_at` (TTL sweep); index `score_schema` (invalidation).

### Migration

- Single file `011_similarity_engine.sql`, idempotent (`CREATE TABLE IF NOT EXISTS`, `CREATE INDEX IF NOT EXISTS`), startup-registered like prior migrations. Table count **38 → 40**.
- **No `ALTER` on any existing table** (SP-1). Zero foreign-key constraints into source tables (soft references via `entity_key`/`source_versions` only — keeps the similarity lifecycle independent of the substrate, mirroring `dossier_failure_mode.analog_id`'s soft FK).
- **Rollback:** tables inert without the `similarity_*` flags; rollback = flags stay false / drop the two tables. DDL never needs reverting (additive, unused until wired).

---

## PART 3 — SERVICE PLAN

| Service | Role | Reuses |
|---|---|---|
| `similarity_feature_builder` | substrate → typed vector | `evidence_engine.build_fingerprint` (T2/T4/T5) |
| `similarity_scorer` | (vector, vector, profile) → (score, contributions, disanalogy) | generalises `evidence_engine._score_analog` |
| `similarity_weighting` | versioned per-target weight profiles + `score_schema` | `InjectionConfig` config-not-table pattern |
| `similarity_ranker` | floor + diversity + top-K + deterministic tie-break → edges | `retrieve_historical_analogs` floor/diversity discipline |
| `similarity_invalidation` | dirty-marking on substrate change, loop-driven | 10A loop tick, lock service, repos |
| `similarity_read_service` | **sole** surface-facing reader; renders headline + disanalogy | materialised edges; entitlement gate (17) |
| `similarity_observability_service` | admin snapshot, null-safe, secret-free | 10D/17 observability pattern |
| `similarity_repo` | persistence for vectors + edges | `dossier_repo` null-session-safe style |

**Dependency-direction invariant (SP-4):** surfaces → `similarity_read_service` → repo. Builder/scorer/ranker are write-side only. No node in this graph imports a forecasting/conviction/scenario module, and nothing outside PART 3's named surfaces imports `similarity_read_service`. A standing import-graph test enforces this.

---

## PART 4 — VALIDATION PLAN

### Boundary checks (the defining gates)

- **No new primary facts (SP-1):** no-write-back property test — full source substrate byte-identical after a complete engine run. Asserted from Slice 2 onward.
- **No forecast influence (SP-4):** import-graph test — similarity reader is consumed only by PART 3 surfaces; builder/scorer/reader import no forecasting/conviction module. Asserted from Slice 3 onward.
- **Zero orphan scores (Spec §10.4):** CI asserts no persisted/delivered edge has empty `contributions`; mean contributions per edge > 0 on the admin snapshot.

### Correctness checks

- Substrate isolation: empty source tables → empty result sets, zero exceptions.
- Self-exclusion: query entity never in its own results.
- Determinism: identical substrate + profile → identical scores and ranks (precondition for drift tests).
- Identity scoping: no cross-tenant leakage; shared library visible to all.
- Cache equivalence: a materialised edge equals a fresh recompute for the same `source_versions` + `score_schema`.

### Similarity-quality checks

- Golden resemblance set (mirrors the 9G golden-set harness): hand-curated good matches must surface in top-K for their target.
- Floor calibration: labelled strong/weak/none triples land in the correct band; precision@K tracked.
- Diversity: no result set is N variants of one feature class.
- Disanalogy presence: every above-floor edge carries a non-empty, feature-grounded disanalogy.

### Drift checks

- Score stability under no-op rebuilds (catches non-determinism / float regressions).
- Bounded, monotonic response to a single-facet change (no cliff edges — mirrors moat `pending_flip` hysteresis).
- Schema-bump invalidation: bumping `vector_schema`/`score_schema` forces an observable full recompute; no stale-schema edge served.

### Test harness

- **Unit/integration:** `tests/test_services/test_similarity_*` (builder, scorer, ranker, invalidation, read, observability).
- **Shadow validation:** `tests/validate_11_similarity_shadow.py` (staging): `db_table_count=40`, both tables present, kernel-reuse import check, all `similarity_*` flags false, `safe_state=true`, orphan-score count 0, no-write-back holds, SP-4 boundary holds. Exit 0 gates each stage.

---

## PART 5 — ROLLOUT SEQUENCE

Reuses the 10A/9G cohort + kill switch unchanged, adding four independent `similarity_*` flags. Each stage defines **advance / hold / rollback** explicitly. **Default state is fully inert** (all four flags false / empty).

| Flag | Default | Controls |
|---|---|---|
| `similarity_build_enabled` | `false` | feature-vector writes |
| `similarity_scoring_enabled` | `false` | edge materialisation |
| `similarity_targets` | `""` | which targets are active (`failure_mode,company,thesis,catalyst,regime`) |
| `similarity_delivery_enabled` | `false` | whether any surface delivers similarity |

### Shadow stage
- Flip `similarity_build_enabled=true`, then `similarity_scoring_enabled=true`, `similarity_targets=failure_mode`. Vectors build, edges materialise, **nothing reads**. Watch the admin snapshot: coverage, floor pass-rate, score distribution, orphan-score = 0.
- **Advance when:** distributions non-degenerate, orphan-score 0, no-write-back + SP-4 tests green, latency within budget.
- **Rollback:** set both flags false (instant, no redeploy) — materialisation halts, edges expire unread. Production unaffected (no surface reads).

### Internal stage
- Widen `similarity_targets=failure_mode,company,thesis`; expose the dossier `resembles` facet to `LOOP_INTERNAL_USER_IDS` only (delivery still off).
- **Advance when:** internal review confirms matches read as resemblance (never prediction), every edge shows a headline + disanalogy, no false-confidence complaints.
- **Rollback:** drop `similarity_targets` back to `failure_mode` or remove internal-user exposure — instant, edges bank unread.

### Canary stage
- Flip `similarity_delivery_enabled=true` for the existing canary cohort (`*_canary_pct` machinery). Transition-only events flow through the 10C/10D delivery spine.
- **Advance when:** delivery volume sane, dedup correct, opt-out respected, zero forecast-path reads (SP-4 monitor).
- **Rollback:** `similarity_delivery_enabled=false` (instant, similarity-specific halt — leaves all 10C/10D company/portfolio alerts live) or the loop kill switch `POST /admin/loop/disable` (halts the rebuild tick). Generated edges persist; the `content_key`/dedup absorbs any resume.

### Ramp
- Add `catalyst,regime` targets; widen the cohort step-by-step.
- **Rollback at any step:** drop `similarity_targets` to the last-green set, or `similarity_delivery_enabled=false`, or `POST /admin/loop/disable`. The kill switch stops *delivery/rebuild*, never destroys edges — flipping off and back on never loses or duplicates results (TTL + `score_schema` absorb the resume).

---

## PART 6 — DEPENDENCIES

### On 9G — the analytical substrate + the scoring kernel (already shipped)
- **`app/evidence_engine.py`** — `SetupFingerprint`, `build_fingerprint`, `_score_analog`, `retrieve_historical_analogs`: the scoring kernel Phase 11 generalises. **Reused wholesale**, not forked (SP-2).
- **`historical_analogs`** — read-only library for T4/T5; never seeded or migrated by Phase 11.
- **Dossier facets** (`company_dossier`, `dossier_core_debate`, `dossier_moat_dimension`, `dossier_catalyst`, `dossier_variant`, `dossier_durability`, `dossier_failure_mode`) + `DossierRevision` — the feature substrate and the invalidation trigger (`row_version`).
- **`cross_exposures`** — T1/T6 shared-concern features.

### On 10A — the loop & rollout spine (already shipped)
- The loop tick + lock service + scheduler — Phase 11 adds one idempotent rebuild step, no second scheduler.
- The flag substrate + `LOOP_INTERNAL_USER_IDS` + `*_canary_pct` + `POST /admin/loop/disable` kill switch — Phase 11's rollout is a config sequence over this machinery plus four new flags.

### On 10C/10D — the delivery spine + observability pattern (already shipped)
- `loop_delivery_service`, `digest_batch_service`, `in_app_delivery_service`, `morning_brief_service`, `portfolio_insight_service` — the only delivery surfaces; Phase 11 adds additive lines/chips/events through the existing dedup + content-hash + relevance gating. No new pipeline.
- The `*_observability_service` + `/admin/*-status` + `validate_*_shadow.py` triad — Phase 11 mirrors it exactly.

### On 16/17 — identity + entitlements (already shipped)
- `user_id` scoping on derived rows mirrors source ownership; the shared global library is unowned.
- Similarity depth/top-K/target breadth are entitlements gated behind `ENTITLEMENTS_ENFORCED` — failure-open, shadow-safe by default.

---

## PART 7 — IMPLEMENTATION ORDER

- **Week 1 — substrate, dark.** Slice 1 (schema, 38→40) + Slice 2 (T4 builder, build flag off). Dark-deploy; no read, no write until flag-flip. No-write-back test green.
- **Week 2 — scoring + freshness, shadow.** Slice 3 (scorer/ranker, scoring flag off) + Slice 4 (loop invalidation). Flip build+scoring on in shadow for T4; watch distributions on the admin snapshot. SP-4 import-graph test green.
- **Week 3 — breadth + read, internal.** Slice 5 (T1/T2) + Slice 6 (read service + dossier facet, internal users only, delivery off). Golden-set + explainability gates green.
- **Week 4 — delivery wiring, shadow.** Slice 7 (brief/watchlist/portfolio/inbox/digest, delivery flag off) + Slice 8 (observability + `validate_11_similarity_shadow.py`). Full overnight in shadow; `safe_state=true`.
- **Week 5 — governed rollout.** PART 5 sequence: shadow → internal → canary → ramp, adding `catalyst,regime` last. Kill switch + four flags revertible at every step.

**Standing rule:** the four `similarity_*` flags are independent and layered — build, scoring, targets, delivery flip in sequence, each revertible without touching the others or any prior phase. Vectors and edges are a droppable cache; the source substrate is never written; no edge ever reaches a forecast. The dataset only ever grows under governed, idempotent, explainable, no-write-back writes.

---

## DELIVERABLE SUMMARY

1. **Build slices (8):** schema-dark → T4 builder → scorer/ranker → loop invalidation → T1/T2 → read service + dossier facet → delivery wiring → observability + validator; each shadow-stamped, each with explicit validation + rollback (PART 1).
2. **Safe slicing:** every slice lands inert behind the four `similarity_*` flags; the consequential flips are a PART 5 config sequence, never a slice (SP-3).
3. **No new primary facts:** 2 additive derived tables, zero `ALTER`, zero FK into source, a per-slice no-write-back property test (SP-1, PART 2).
4. **Kernel reuse:** `evidence_engine` + `historical_analogs` reused wholesale as the scoring substrate; targets are projections over the existing fingerprint, never re-derivations (SP-2, PART 6).
5. **Shadow-first rollout:** dark-deploy then layered flag-flips, internal → canary → ramp, kill switch + four flags revertible at all times (PART 5, PART 7).
6. **No forecast influence (the defining boundary):** edges are descriptive only; no forecasting consumer is wired; an import-graph dependency-direction test enforces the boundary from Slice 3 (SP-4, PART 3/4).
7. **Validation + rollback for every slice:** boundary gates (no-write-back, no-forecast, zero-orphan-score) + correctness + similarity-quality + drift checks, each measurable on `/admin/similarity-status` and asserted by `validate_11_similarity_shadow.py`; every slice states a zero-data-loss rollback (PART 4, PART 1).
