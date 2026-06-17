# Phase 12 — Forecasting Engine Implementation Plan

Status: **plan only — no code, no implementation.**
Companion to `PHASE_12_FORECASTING_ENGINE_SPEC.md` (approved). Every slice
below traces back to a section of that spec. This plan defines *how* to build
it safely, slice by slice, with validation and rollback per slice.

---

## 0. Guiding constraints (apply to every slice)

| Constraint | Enforcement |
|---|---|
| All flags default inert | `false/false/""/true/false/false` — verified by validation script check 6 |
| Shadow-first, no live delivery | No `kind="forecast"` Notification; no public route; verified by validation checks 9, 13 |
| Probabilistic, explainable, descriptive only | No price columns in schema; mandatory `why`/`invalidators`; verified by checks 15, 16 |
| No target prices / buy-sell / advice language | No price field exists in data model; disclaimer constant mandatory; no-advice-language test per slice |
| Dependency direction | Phase 12 reads `similarity_edge`; nothing in 9G–11 reads `forecast_vector`; AST check 7 |
| No conviction/recommendation coupling | No `forecast_*` import of conviction/recommendation/notification_service/dossier_injection; AST check 8 |
| Schema additive only | `012_forecasting_engine.sql` is all `IF NOT EXISTS`, no `ALTER` on existing tables |
| Null-session safe | Every async function returns inert value on `session=None` |

Each slice is independently mergeable. Each slice leaves `safe_state: true`.
No slice depends on a later slice to be safe.

---

## 1. Flags (introduced once, in Slice 12.1)

All six flags are added to `app/config.py` in Slice 12.1 so the inert defaults
exist before any consumer. Consumers are wired in later slices but the flags
read `false` until then, making every intermediate state safe.

| Setting | Type | Default | First consumer slice |
|---|---|---|---|
| `forecast_build_enabled` | bool | `false` | 12.5 (invalidation/rebuild auto-build) |
| `forecast_scoring_enabled` | bool | `false` | 12.3 (probability engine auto-run via rebuild), 12.7 (delivery gate) |
| `forecast_targets_enabled` | str | `""` | 12.5 (rebuild scheduling allowlist) |
| `forecast_shadow` | bool | `true` | 12.7 (shadow journaling gate) |
| `forecast_calibration_enabled` | bool | `false` | 12.8 (outcome logging gate) |
| `forecast_delivery_enabled` | bool | `false` | reserved; never consumed in Phase 12 |

Builders and the probability engine remain directly callable regardless of
flags (same convention as Phase 11): flags gate *automatic* invocation and
*delivery journaling*, not the pure functions themselves.

---

## 2. Slice list (overview)

| Slice | Name | Spec ref | Net-new safe? |
|---|---|---|---|
| 12.1 | Schema + repository | §3, §2.2 | ✅ inert tables only |
| 12.2 | Feature builder (T1 company, T4 failure_mode) | §5.3–5.6, §4.1 | ✅ writes only forecast_vector inputs |
| 12.3 | Probability engine | §5.1–5.8 | ✅ pure ensemble math |
| 12.4 | Explainability | §6 | ✅ build-time gate, discards incomplete |
| 12.5 | Invalidation + rebuild triggering | §2.1, §10.2 step 1 | ✅ flag-gated, no auto-run by default |
| 12.6 | Read service + admin routes + dossier enrichment wrapper | §8.2, §11 | ✅ read-only, additive |
| 12.7 | Shadow delivery wiring | §8.3 | ✅ shadow channel, no flush pipeline |
| 12.8 | Calibration service | §7 | ✅ flag-gated outcome logging |
| 12.9 | Observability + validation script + rollout doc | §9.5, §11, §10 | ✅ read-only snapshot |

T2 (thesis) and portfolio forecasts are **deferred to Phase 13** per spec §16.
Slice 12.2 ships T1 + T4 only. The probability engine (12.3) is written gener-
ically so adding T2/portfolio later is config + a feature-builder function, not
an engine rewrite.

---

## 3. Slice detail

Each slice below lists: scope, files created/modified, validation, rollback.

---

### Slice 12.1 — Schema + Repository

**Scope**: Tables 41–43, ORM models, migration, repository, all six flags,
schema tests. No builders, no engine, no routes.

**Files created**
- `app/db/migrations/012_forecasting_engine.sql` — tables 41–43, all
  `IF NOT EXISTS`, indexes, unique constraints. No `ALTER` on existing tables.
- `app/db/repositories/forecast_repo.py` — null-session-safe CRUD/upsert for
  `forecast_vector` and `forecast_evidence`; read-only access to
  `forecast_calibration_log`. Calibration writes are NOT in this repo (reserved
  for the calibration service to preserve immutability).
- `tests/test_services/test_forecast_schema.py` — ~25 tests.

**Files modified**
- `app/db/models.py` — add `ForecastVector` (table 41), `ForecastEvidence`
  (table 42), `ForecastCalibrationLog` (table 43) after the Phase 11 similarity
  models. JSON columns via existing `_json_col()` helper. Unique constraint on
  `forecast_vector(entity_type, entity_key, horizon, forecast_type, user_id)`.
- `app/config.py` — add the six `forecast_*` flags with inert defaults.

**Validation (Slice 12.1)**
- Schema tests: all three tables creatable; unique constraint enforced;
  null-session repository functions return `None/[]/0`; no price column exists
  on `forecast_vector`; round-trip upsert/get for vector and evidence.
- Invariant test: `forecast_calibration_log` has no UPDATE path in `forecast_repo`.
- `db_table_count >= 43` after `create_all`.
- AST: `forecast_repo` imports nothing from conviction/recommendation/forecast-
  delivery modules.

**Rollback (Slice 12.1)**
- Drop/truncate the three tables — pure additive schema, nothing reads them yet.
- Revert `config.py` flag additions (no consumer exists yet).
- No existing behavior changes; migration adds tables only.

---

### Slice 12.2 — Feature Builder (T1 company, T4 failure_mode)

**Scope**: Extract ensemble *inputs* (not probabilities) from the intelligence
substrate for two entity types. Writes the source-version snapshot. No
probability math yet.

**Files created**
- `app/services/forecast_feature_builder.py`
  - `build_company_forecast_features(session, ticker)` → reads
    `company_dossier`, `dossier_core_debate`, `thesis_versions`,
    `historical_analogs`, `similarity_edge` (Phase 11), `cross_exposures`.
  - `build_failure_mode_forecast_features(session, failure_mode_id)` → reads
    `dossier_failure_mode`, `historical_analogs`, `similarity_edge`.
  - Each returns a structured feature object: analog set + resolutions, similarity
    peer set + scores, thesis confidence trajectory, regime exposure, and the
    `source_versions` dict captured at read time.
  - Resolution-inference helpers (one per entity type) per spec §5.3.
- `tests/test_services/test_forecast_feature_builder.py` — ~20 tests.

**Files modified**: none (pure new module).

**Validation (Slice 12.2)**
- Per-entity-type feature extraction returns correct analog/similarity/thesis/
  regime components from seeded data.
- `source_versions` captured correctly (row versions match source rows).
- Null-session safety: returns `None`.
- **No source-table mutation test**: before/after snapshot of all read tables
  is byte-identical.
- AST: imports `similarity_edge` repo/model (allowed — consuming Phase 11), does
  NOT import conviction/recommendation/forecast-delivery.
- Empty-substrate test: no analogs + no similarity edges → feature object with
  empty components (engine will fall back to uniform priors), never raises.

**Rollback (Slice 12.2)**: delete the module + test. Nothing imports it yet.

---

### Slice 12.3 — Probability Engine

**Scope**: Pure ensemble math turning feature objects into probability
distributions. Deterministic, no I/O beyond reading the feature object.

**Files created**
- `app/services/forecast_probability_engine.py`
  - `compute_forecast_distribution(features, *, forecast_type, horizon)` →
    `{p_positive, p_negative, p_neutral, confidence_band_low, confidence_band_high,
    component_contributions}`.
  - Implements the four ensemble components (§5.3–5.6), the per-forecast-type
    weight config dict (§5.2, versioned), clamping to [0.01, 0.99],
    renormalization to sum 1.0, and confidence-band computation (§5.7).
  - `FORECAST_WEIGHT_CONFIG` versioned dict keyed by `forecast_type`; engine
    reads it rather than hardcoding per-call — enables future A/B without engine
    edits.
  - Supports the six forecast types from §4.2; validates `(entity_type,
    forecast_type)` pairs and rejects invalid combinations.
- `tests/test_services/test_forecast_probability_engine.py` — ~25 tests.

**Files modified**: none.

**Validation (Slice 12.3)**
- **Probability sum test**: `p_positive + p_negative + p_neutral` within 0.001
  of 1.0 across a wide grid of synthetic feature inputs.
- Clamping: no output bin < 0.01 or > 0.99.
- Confidence band: `low <= p_positive <= high`; band widens as
  `effective_evidence_count` falls and as staleness rises.
- Weight config: each forecast_type's weights sum to 1.0.
- Uniform-prior fallback: empty analog set → base component = 0.33/0.33/0.34;
  empty similarity set → sim component = uniform.
- Determinism: same input → same output, repeated.
- Invalid `(entity_type, forecast_type)` pair → rejected (returns None / raises
  a domain error caught by builder), never a malformed distribution.

**Rollback (Slice 12.3)**: delete module + test. No consumer yet (the orchestr-
ation that calls builder→engine→repo is wired in 12.5).

---

### Slice 12.4 — Explainability

**Scope**: Construct `why`, `invalidators`, evidence rows, and attach the
disclaimer. Enforce the discard-if-incomplete rule. This is the gate that
makes every stored forecast explainable.

**Files created**
- `app/services/forecast_explainability.py`
  - `build_why(features, distribution, *, entity_name, forecast_type, horizon)` →
    non-empty prose from the dominant component (§6.2, versioned template).
  - `build_invalidators(features, *, forecast_type)` → the three default
    invalidators + entity-specific ones (§6.3); always non-empty.
  - `build_evidence_rows(features, distribution, forecast_id, ...)` → one
    `ForecastEvidence` payload per analog/similarity/thesis/regime contributor,
    each with a human-readable `description`, signed `contribution`, `weight`,
    `direction`.
  - `assemble_evidence_summary(evidence_rows, top_n=5)` → ranked condensed list
    for `forecast_vector.evidence_summary`.
  - `validate_explainability(vector_payload)` → returns False (and logs a
    warning) if `why` empty, `invalidators` empty, or both `analog_basis` and
    `similarity_basis` empty. The builder/orchestrator discards any vector that
    fails this.
- `tests/test_services/test_forecast_explainability.py` — ~15 tests.

**Files modified**: none.

**Validation (Slice 12.4)**
- **Explainability completeness test**: a fully-populated feature set yields a
  vector with non-empty `why`, non-empty `invalidators`, ≥1 evidence row.
- **Discard test**: a feature set with no analogs AND no similarity edges → the
  vector is rejected by `validate_explainability` (no evidence basis).
- **No-advice-language test**: `why` and `invalidators` text contain none of a
  banned-phrase list (`buy`, `sell`, `hold`, `price target`, `fair value`,
  `recommend`, `should invest`, etc.) — case-insensitive scan of generated text.
- Disclaimer constant is referenced (defined in read service in 12.6; in 12.4 a
  placeholder constant or the read-service constant is imported once it exists —
  sequencing note: the disclaimer constant lives in `forecast_read_service`,
  introduced in 12.6; 12.4 may define an interim constant module
  `forecast_constants.py` that the read service later re-exports, to avoid a
  forward dependency).

> **Sequencing note**: To avoid a forward import, introduce
> `app/services/forecast_constants.py` in Slice 12.4 holding `DISCLAIMER`,
> banned-phrase list, and `FORECAST_SCHEMA_VERSION`. Slices 12.6/12.7 import
> from it. This keeps the disclaimer single-sourced.

**Rollback (Slice 12.4)**: delete module(s) + test. No consumer yet.

---

### Slice 12.5 — Invalidation + Rebuild Triggering

**Scope**: Orchestration — staleness detection, the builder→engine→explainability
→repo pipeline, batch rebuild, flag gating. This is the first slice where the
pure functions compose into stored `forecast_vector` rows. Still no delivery,
no dossier change, no auto-run by default.

**Files created**
- `app/services/forecast_invalidation_service.py`
  - `is_forecast_stale(session, vector, *, ttl_hours=...)` — TTL by horizon
    (24h/72h/168h) + source-version change detection (thesis version, dossier
    row version, failure-mode sequence_stage) + orphan detection.
  - `rebuild_forecast_for_target(session, entity_type, entity_key, *, run_scoring=None)`
    — calls feature builder → probability engine → explainability →
    `validate_explainability` (discard if incomplete) → upsert vector + evidence.
  - `rebuild_forecast_for_ticker(session, ticker, *, run_scoring=None)` — all
    horizons × applicable forecast types for the ticker.
  - `rebuild_forecast_batch(session, *, limit, ttl_hours, run_scoring=None)`.
  - `_scoring_approved(run_override)` — explicit override wins; else
    `settings.forecast_scoring_enabled`.
- `tests/test_services/test_forecast_invalidation_service.py` — ~20 tests.

**Files modified**: none (no loop auto-registration in Phase 12 base — a Phase
12+ loop producer is out of scope, same posture as Phase 11 Slice 5).

**Validation (Slice 12.5)**
- Staleness: TTL expiry, source-version change, orphan all detected.
- Rebuild end-to-end: seeded ticker → stored `forecast_vector` + `forecast_evidence`
  rows with all explainability fields populated.
- **Discard path**: a ticker with no evidence basis produces NO stored vector.
- Flag gating: with `forecast_scoring_enabled=false` and no override, rebuild
  produces feature vectors but does not auto-run scoring (mirrors Phase 11 §10.2
  step semantics); explicit `run_scoring=True` override forces it.
- **Probability sum invariant** re-checked on stored rows.
- **No source-table mutation test** (only `forecast_*` tables written).
- AST: no conviction/recommendation/notification import.

**Rollback (Slice 12.5)**
- Truncate `forecast_vector` + `forecast_evidence` — pure caches.
- Delete the service + test. The builder/engine/explainability modules remain
  harmless (no caller).
- No flag was flipped; defaults keep auto-run off.

---

### Slice 12.6 — Read Service + Admin Routes + Dossier Enrichment Wrapper

**Scope**: Read-only access layer, two admin routes, and the additive dossier
enrichment wrapper. First slice where forecast data is *retrievable*, but only
via `/admin/` and only as an additive dossier annotation that is off by default.

**Files created**
- `app/services/forecast_read_service.py`
  - `DISCLAIMER` re-exported from `forecast_constants` (§6.5).
  - `get_forecast_for_target(session, entity_type, entity_key, *, limit)` —
    floor-passed/valid only, non-expired; drops any row missing `why`/
    `invalidators`/evidence (defense-in-depth); attaches disclaimer.
  - `get_forecast_for_ticker(session, ticker)` — aggregates across horizons +
    forecast types for the ticker.
  - `get_forecast_facet_for_ticker(session, ticker)` — `{has_forecast, ticker,
    forecasts, disclaimer}`, safe-empty when no data.
- `app/services/dossier_forecast_enrichment.py`
  - `build_forecast_context_block(session, ticker)` — wraps the facet; never raises.
  - `get_full_dossier_with_forecast_context(session, ticker)` — calls
    `dossier_repo.get_full_dossier` then attaches `forecast_context`; returns
    unmodified dossier when `forecast_build_enabled` or `forecast_scoring_enabled`
    is false; never touches head/debate/conviction/stance/verdict.
- `tests/test_services/test_forecast_read_service.py` — ~15 tests.
- `tests/test_services/test_dossier_forecast_enrichment.py` — ~8 tests.

**Files modified**
- `app/api.py` — add `GET /admin/forecast-status` (delegates to observability,
  which lands in 12.9 — until then it may delegate to a minimal snapshot in the
  read service, replaced in 12.9) and `GET /admin/forecast/{ticker}`.

> **Sequencing note**: `/admin/forecast-status` is added in 12.6 pointing at a
> minimal `build_forecast_status_snapshot` in the read service, then re-pointed
> to `forecast_observability.build_forecast_observability_snapshot` in 12.9 —
> exactly the Phase 11 Slice 6→8 pattern.

**Validation (Slice 12.6)**
- Read service: floor/validity gating, expired exclusion, disclaimer present in
  every non-empty response, safe-empty when no data.
- **Disclaimer-present test**: every read-service output path includes the
  constant.
- Dossier wrapper: `forecast_context` attached and additive; head/debate/
  conviction/stance/verdict byte-identical to plain `get_full_dossier`; returns
  unmodified dossier when flags inert.
- **NOT wired into `dossier_injection_service`** — test asserts
  `dossier_injection_service` source does not import `dossier_forecast_enrichment`.
- Route exposure: both routes under `/admin/`; no public forecast route (static
  AST source scan of `app/api.py`, per the Phase 11 Python-3.9 import-workaround).

**Rollback (Slice 12.6)**
- Remove the two routes from `app/api.py` (additive, no other route depends).
- Delete read service + enrichment wrapper + tests.
- Dossier responses revert to plain `get_full_dossier` (the wrapper was never
  wired into the default path anyway).

---

### Slice 12.7 — Shadow Delivery Wiring

**Scope**: Transition detection + shadow journaling into `delivery_ledger`
under `channel="forecast_shadow"`, reusing the existing dedup machinery. No
live delivery, no Notification rows.

**Files created**
- `app/services/forecast_delivery_service.py`
  - `FORECAST_DELIVERY_CHANNEL = "forecast_shadow"`,
    `DEFAULT_MATERIALITY_THRESHOLD = 0.10`.
  - `classify_transition(previous, current, *, materiality_threshold)` →
    `first_crossing` / `strengthened` / `weakened` / `disappeared` / None
    (steady-state) — mirrors `similarity_delivery_service` exactly (§8.3).
  - `detect_forecast_transitions(previous_vectors, current_vectors, ...)` →
    keyed by `(entity_type, entity_key, forecast_type, horizon, user_id)`.
  - `_delivery_approved(run_override)` — ALL of `forecast_build_enabled` +
    `forecast_scoring_enabled` + `forecast_shadow` must be true.
  - `record_forecast_transition_events(session, previous, current, *, run_override)`
    — gated; for each event `loop_idempotency_service.guard_delivery` →
    `delivery_create(channel="forecast_shadow", ...)` with deterministic
    `content_key` from `(entity_type, entity_key, forecast_type, horizon,
    payload_hash)`.
- `tests/test_services/test_forecast_delivery_service.py` — ~23 tests.

**Files modified**: none.

**Validation (Slice 12.7)**
- Transition classification across all five cases (incl. steady-state → None).
- **No steady-state spam test**: identical previous/current → zero events.
- Gating: with defaults (`build=false`), `record_*` returns `[]` immediately;
  only all-three-true journals.
- Dedup: same event twice → one ledger row (UNIQUE content_key conflict on 2nd).
- **Shadow-only test**: journaled rows have `channel="forecast_shadow"`,
  `status="pending"`; zero `Notification` rows created; no flush pipeline drains
  the channel.
- AST: no import of `notification_service`/conviction/recommendation.

**Rollback (Slice 12.7)**
- Delete `forecast_shadow` ledger rows freely (nothing reads them).
- Delete service + test.
- Flags stay inert; default behavior is a no-op regardless.

---

### Slice 12.8 — Calibration Service

**Scope**: Outcome observation, Brier scoring, immutable calibration logging,
drift detection. Flag-gated by `forecast_calibration_enabled` (default false).

**Files created**
- `app/services/forecast_calibration_service.py`
  - `log_forecast_outcome(session, forecast_id, actual_outcome, *,
    evaluation_source, evaluator_notes=None)` — writes ONE immutable
    `forecast_calibration_log` row; snapshots probabilities at forecast time;
    computes `brier_score` (binary; neutral/inconclusive excluded). Never UPDATEs.
  - `detect_outcomes(session, *, run_override=None)` — flag-gated; scans for
    thesis-state-change / risk-event / watchlist-resolution against forecasts
    within their horizon window (§7.2). Triggered by the Phase 10A loop when
    source tables are written (wiring deferred; in 12.8 it is callable but not
    auto-registered).
  - `compute_calibration_metrics(session, *, window_days, forecast_type=None)` →
    mean Brier (30/90/180d), resolution, reliability curve.
  - `calibration_status(session)` → `"cold_start"` (<20 evaluated) / `"active"`.
  - `detect_drift(session, ...)` → direction-bias / zero-resolution / Brier-floor
    alerts (§7.4).
- `tests/test_services/test_forecast_calibration_service.py` — ~15 tests.

**Files modified**: none (no loop auto-registration in base).

**Validation (Slice 12.8)**
- Brier score correct for known (p, outcome) pairs.
- Neutral/inconclusive excluded from binary Brier.
- **Immutability test**: re-evaluation creates a NEW row, never updates; AST
  inspection confirms no UPDATE statement against `forecast_calibration_log` in
  the service source.
- Cold-start threshold: `<20` evaluated → `"cold_start"`; `>=20` → `"active"`.
- Window aggregation (30/90/180d) correct.
- **Drift tests**: all-0.80 forecasts + all-negative outcomes → direction-bias
  alert; all-0.50 forecasts → zero-resolution flag.
- Flag gating: `forecast_calibration_enabled=false` + no override → `detect_outcomes`
  is a no-op.

**Rollback (Slice 12.8)**
- Truncate `forecast_calibration_log` — analytics only; nothing depends on it.
- Delete service + test.
- Flag inert by default; no outcome logging happens without the flip.

---

### Slice 12.9 — Observability + Validation Script + Rollout Doc

**Scope**: The full observability snapshot, the standalone validation script,
and the rollout documentation. Slice 12.9 = Phase 12 complete.

**Files created**
- `app/services/forecast_observability_service.py`
  - `build_forecast_observability_snapshot(session)` → full snapshot (§11):
    flags (all 6), db_available, vector_counts (4 entity types), evidence_count,
    calibration_log_count, calibration_status, mean_brier_score_30d,
    shadow_delivery_count, shadow_escalated_count, live_notification_count,
    latest_vector_built_at, latest_forecast_scored_at, calibration_warnings,
    safe_state, snapshot_utc.
  - `safe_state = forecast_shadow=true AND forecast_delivery_enabled=false AND
    shadow_escalated_count=0 AND live_notification_count=0`.
  - Read-only, DB-down-safe, never raises. Duplicates the `"forecast_shadow"`
    channel literal rather than importing the delivery module (clean import graph,
    Phase 11 Slice 8 pattern).
- `tests/test_services/test_forecast_observability_service.py` — ~12 tests.
- `tests/validate_12_forecast_shadow.py` — 18-check script (§9.5), exit 0/1.
- `docs/PHASE_12_FORECASTING_SHADOW_ROLLOUT.md` — env vars, local + production
  validation, internal probe procedure, rollout sequence, rollback, no-forecast→
  conviction boundary, no-write-back boundary, acceptance criteria.

**Files modified**
- `app/api.py` — re-point `GET /admin/forecast-status` to
  `forecast_observability_service.build_forecast_observability_snapshot`.

**Validation (Slice 12.9)**
- Observability snapshot: empty-DB shape, populated counts, DB-down degradation,
  `safe_state` true/false combinations, no-secret-leakage, flags section types.
- Validation script: all 18 checks pass locally (exit 0).
- Full regression: `tests/test_services/test_forecast_*.py` all pass.

**Rollback (Slice 12.9)**
- Re-point the route back to the minimal read-service snapshot (12.6 form).
- Delete observability service + validation script + rollout doc.
- No schema or flag change.

---

## 4. Probability engine build plan (cross-slice, spec §5)

The six forecast types are NOT six engines. They are one ensemble engine
(Slice 12.3) parameterized by a versioned weight config and fed by entity-type
feature builders (Slice 12.2 ships T1+T4; T2/portfolio deferred). Build order
within the engine:

1. Four component functions: `P_base_rate` (§5.3), `P_sim_peer` (§5.4),
   `P_thesis_signal` (§5.5), `P_regime` (§5.6). Each independently unit-tested
   with uniform-prior fallback.
2. Ensemble combiner: weighted sum per `FORECAST_WEIGHT_CONFIG[forecast_type]`,
   clamp [0.01, 0.99], renormalize to sum 1.0.
3. Confidence band (§5.7): `BASE_BAND_WIDTH=0.20`, narrows with
   `effective_evidence_count = len(analog_basis) + 2×len(similarity_basis)`,
   widens with staleness.
4. Horizon handling: the same engine runs per horizon (30/90/180); horizon
   affects which analogs/signals are in-window (feature builder) and the TTL
   (invalidation service), not the ensemble formula.

Forecast types mapped to entity types and components:

| forecast_type | entity types (Phase 12) | dominant component |
|---|---|---|
| `thesis_strengthening` | company | thesis signal + base rate |
| `thesis_weakening` | company | thesis signal + base rate |
| `risk_emergence` | failure_mode | base rate (analogs) |
| `catalyst_realization` | company | thesis signal |
| `similarity_outcome` | company, failure_mode | sim peer (w_sim=0.60) |
| `regime_transition` | (portfolio — deferred to Phase 13) | regime |

`regime_transition` is defined in the engine config in 12.3 but has no Phase 12
feature builder (portfolio builder deferred); it is exercised only by synthetic
tests until Phase 13 ships the portfolio feature builder.

---

## 5. Explainability gate (cross-slice, spec §6)

Explainability is enforced at the point of storage, in Slice 12.5's rebuild
orchestration, using Slice 12.4's `validate_explainability`. A vector is stored
only if:

- `why` non-empty, AND
- `invalidators` non-empty (≥1), AND
- (`analog_basis` non-empty OR `similarity_basis` non-empty), AND
- ≥1 `forecast_evidence` row, AND
- horizon explicitly set, AND
- confidence band present with `low <= p_positive <= high`.

Any vector failing the gate is discarded with a `logger.warning`, never written.
This is verified by the discard test in 12.4 and 12.5 and by validation-script
check 15.

---

## 6. Calibration plan (cross-slice, spec §7)

| Stage | Slice | What |
|---|---|---|
| Logging primitive | 12.8 | `log_forecast_outcome` — immutable row, Brier at forecast-time snapshot |
| Outcome detection | 12.8 | `detect_outcomes` — thesis-change / risk-event / watchlist-resolution; flag-gated |
| Metrics | 12.8 | `compute_calibration_metrics` — mean Brier 30/90/180d, resolution, reliability curve |
| Status | 12.8 | `calibration_status` — cold_start (<20) / active |
| Drift | 12.8 | `detect_drift` — direction bias, zero resolution, Brier floor |
| Surfacing | 12.9 | `mean_brier_score_30d`, `calibration_status`, `calibration_warnings` in `/admin/forecast-status` |
| Loop wiring | Phase 12+ (deferred) | auto-trigger `detect_outcomes` from Phase 10A loop on source writes |

Calibration is vacuous on first deploy (cold-start), as expected. No live
delivery is permitted until acceptance criteria §8 are met.

---

## 7. Delivery plan (cross-slice, spec §8)

Phase 12 ships **shadow-only** delivery (Slice 12.7). The consumption surfaces
(dossier, watchlist, briefing, portfolio, inbox, digest) are documented in spec
§8.1 but only the dossier enrichment wrapper (Slice 12.6, additive, off by
default) and shadow journaling (Slice 12.7) are built. Transition-based only —
no steady-state forecasts are re-delivered (verified by the no-spam test in
12.7). Live delivery (Notification `kind="forecast"`, public surfacing) is a
Phase 13 decision gated by the acceptance criteria below.

---

## 8. Rollout stages (post-merge, spec §10.2)

| Stage | Flag change | Effect | Monitor |
|---|---|---|---|
| 0 — Delivered | none | All inert; tables empty; `safe_state: true` | `/admin/forecast-status` |
| 1 — Shadow build | `FORECAST_BUILD_ENABLED=true` | Builders auto-callable by a future producer; no scoring/delivery | counts; safe_state |
| 2 — Shadow scoring + journaling | `FORECAST_SCORING_ENABLED=true` (shadow stays true) | Probabilities computed; transitions journaled to `forecast_shadow`; zero user impact | shadow_escalated_count=0 |
| 3 — Calibration active | `FORECAST_CALIBRATION_ENABLED=true` | Outcome logging + Brier accrue | calibration_status→active; mean Brier<0.25 |
| 4 — Dossier enrichment (internal review) | caller opt-in (no flag) | `forecast_context` shown in internal review sessions only; never in `dossier_injection` | human review of output quality |
| 5 — Live delivery | **out of scope (Phase 13)** | requires new live branch + Notification kind + design sign-off | acceptance criteria §8 |

Each stage is reversible by setting the flag back to its default.

---

## 9. Acceptance criteria (Phase 12 complete → Phase 13 eligible)

Before any Phase 13 live-delivery slice may be proposed:

1. `tests/validate_12_forecast_shadow.py` exits 0 in production.
2. `/admin/forecast-status` reports `safe_state: true`, `shadow_escalated_count: 0`,
   `live_notification_count: 0`.
3. All `tests/test_services/test_forecast_*.py` pass (every slice).
4. `calibration_status: "active"` (≥20 evaluated forecasts).
5. `mean_brier_score_30d < 0.25` for every forecast_type with ≥10 evaluated
   forecasts.
6. A documented internal probe has been run against representative tickers and a
   human has reviewed `why` / `invalidators` / evidence for coherence.
7. SP-4 extension verified: AST import check confirms no `forecast_*` module is
   imported by conviction/recommendation/LLM/notification, and no forecast output
   reaches a stance/conviction/verdict field.
8. Mean Brier over ≥60 evaluated forecasts < 0.20 before any live notification
   path is opened.

---

## 10. Per-slice rollback summary

| Slice | Rollback |
|---|---|
| 12.1 | Drop 3 tables; revert config flags; no behavior change |
| 12.2 | Delete feature builder module + test; no caller |
| 12.3 | Delete engine module + test; no caller |
| 12.4 | Delete explainability + constants module + test; no caller |
| 12.5 | Truncate `forecast_vector`/`forecast_evidence`; delete service + test; flags stay off |
| 12.6 | Remove 2 admin routes; delete read service + enrichment + tests; dossier reverts |
| 12.7 | Delete `forecast_shadow` ledger rows; delete delivery service + test |
| 12.8 | Truncate `forecast_calibration_log`; delete calibration service + test |
| 12.9 | Re-point route to minimal snapshot; delete observability + script + doc |

Every rollback is local to the slice and requires no schema revert beyond
optionally dropping the three additive tables (which nothing outside Phase 12
reads).

---

## 11. Files summary

**Created across Phase 12**
- `app/db/migrations/012_forecasting_engine.sql`
- `app/db/repositories/forecast_repo.py`
- `app/services/forecast_feature_builder.py`
- `app/services/forecast_probability_engine.py`
- `app/services/forecast_explainability.py`
- `app/services/forecast_constants.py`
- `app/services/forecast_invalidation_service.py`
- `app/services/forecast_read_service.py`
- `app/services/dossier_forecast_enrichment.py`
- `app/services/forecast_delivery_service.py`
- `app/services/forecast_calibration_service.py`
- `app/services/forecast_observability_service.py`
- `tests/test_services/test_forecast_schema.py`
- `tests/test_services/test_forecast_feature_builder.py`
- `tests/test_services/test_forecast_probability_engine.py`
- `tests/test_services/test_forecast_explainability.py`
- `tests/test_services/test_forecast_invalidation_service.py`
- `tests/test_services/test_forecast_read_service.py`
- `tests/test_services/test_dossier_forecast_enrichment.py`
- `tests/test_services/test_forecast_delivery_service.py`
- `tests/test_services/test_forecast_calibration_service.py`
- `tests/test_services/test_forecast_observability_service.py`
- `tests/validate_12_forecast_shadow.py`
- `docs/PHASE_12_FORECASTING_SHADOW_ROLLOUT.md`

**Modified across Phase 12**
- `app/db/models.py` (tables 41–43; Slice 12.1)
- `app/config.py` (six flags; Slice 12.1)
- `app/api.py` (two `/admin/` routes; Slice 12.6, re-pointed 12.9)

No existing service, model field, or route behavior changes. Every modification
is additive.

---

## 12. Estimated test count

| Slice | Tests |
|---|---|
| 12.1 | ~25 |
| 12.2 | ~20 |
| 12.3 | ~25 |
| 12.4 | ~15 |
| 12.5 | ~20 |
| 12.6 | ~23 (15 + 8) |
| 12.7 | ~23 |
| 12.8 | ~15 |
| 12.9 | ~12 + 18-check validation script |

Phase 12 total: **~178 unit tests + 18-check validation script.**
