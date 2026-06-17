# Phase 12 — Forecasting Engine

Status: **architecture only — no code, no implementation.**
This document defines what must be built in Phase 12 before any slice is
written. All implementation decisions must be traceable to a section here.

---

## 0. What this is not

Phase 12 produces **no price targets, no buy/sell signals, no investment
recommendations.** Every probability in this system answers a question about
*thesis trajectory*, *risk materialization*, *catalyst resolution*, or *regime
state* — not about where a security will trade.

Every output must include an explicit disclaimer. Any output that would read
as investment advice at the UI layer is blocked at the schema level (no price
fields exist anywhere in the data model).

This constraint is structural, not aspirational: there are no fields to put a
price in, and there are no delivery paths to an inbox that do not carry the
disclaimer.

---

## 1. Overview

### 1.1 What Phase 12 adds

Phases 9G–11 built a complete intelligence substrate: historical memory,
continuous loop, watchlist, delivery, portfolio intelligence, similarity
reasoning. Phase 12 consumes that substrate to answer: **what tends to happen
next?**

The output is not a prediction. It is a structured probability distribution
over **thesis-relevant outcomes** at an explicit horizon, backed by named
evidence and falsifiable by named invalidation conditions.

### 1.2 Core design principle

Every forecast is a **weighted ensemble over historical outcomes**, where the
weights come from:

1. Base rates derived from historical analogs (Phase 9G)
2. Similarity-weighted peer outcomes (Phase 11)
3. Current thesis trajectory signals (Phase 10A/10B)
4. Portfolio regime context (Phase 10D)

No component is new. Phase 12 composes existing intelligence into a
probability estimate. It does not add a new data collection layer.

### 1.3 Dependency direction (non-negotiable)

```
Phase 9G  Phase 10A/B/D  Phase 11
    ↓           ↓            ↓
          Phase 12
```

- Phase 12 **imports from** Phases 9G, 10A/B/D, 11.
- **Nothing in Phases 9G–11 ever imports from Phase 12.**
- This is enforced by AST import-graph checks in the validation script
  (same mechanism as Phase 11's SP-4 enforcement).
- Violating this direction is a blocking defect.

---

## 2. Architecture

### 2.1 Service layer

Five services, one for each functional boundary:

```
forecast_feature_builder      builds forecast inputs from the intelligence substrate
forecast_probability_engine   computes probability distributions
forecast_explainability       constructs why/evidence/invalidators for each forecast
forecast_read_service         read-only access layer (admin + dossier + delivery)
forecast_observability        snapshot for /admin/forecast-status
```

Two supporting services:

```
forecast_invalidation_service    staleness detection and rebuild triggering
forecast_calibration_service     outcome logging and Brier-score computation
```

No delivery service in Phase 12 proper — forecast outputs are consumed by
the existing delivery layer (dossier enrichment, briefing builder, digest
composer, inbox writer). Those callers add the forecast block; Phase 12 does
not push anything to them.

### 2.2 Repository layer

Three new tables (see §3). One new repository:

```
forecast_repo    CRUD + upsert for forecast_vector and forecast_evidence
                 read-only access to forecast_calibration_log
```

Calibration writes go through a dedicated function in
`forecast_calibration_service`, not through the general repo, to preserve
the immutability invariant of calibration rows.

### 2.3 Config flags (all default inert)

| Setting name | Type | Default | Effect |
|---|---|---|---|
| `forecast_build_enabled` | bool | `false` | Gates automatic feature-vector builds from any producer |
| `forecast_scoring_enabled` | bool | `false` | Gates probability computation and edge materialization |
| `forecast_targets_enabled` | str | `""` | Comma-separated target_types active for automatic rebuild |
| `forecast_shadow` | bool | `true` | When all three above are true, gates shadow journaling into delivery_ledger |
| `forecast_calibration_enabled` | bool | `false` | Gates outcome logging and Brier-score computation |
| `forecast_delivery_enabled` | bool | `false` | Reserved for Phase 12+ live delivery; always false in Phase 12 |

Six flags. Safe state: `false/false/""/true/false/false`.

### 2.4 Null-session pattern

Every async function returns `None`/`[]`/`0`/`False`/`{}` when session is
`None`. No function in the forecast layer ever raises on a missing session.
Consistent with all Phases 10–11 conventions.

---

## 3. Data model

### Table 41: `forecast_vector`

The computed forecast for one entity, one horizon, one forecast type.

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `entity_type` | VARCHAR(20) | `company`, `thesis`, `failure_mode`, `portfolio` |
| `entity_key` | VARCHAR(200) | ticker / thesis_id / fm_id / portfolio_id |
| `horizon` | VARCHAR(20) | `near_term`, `medium_term`, `long_term` |
| `horizon_days` | INTEGER | 30 / 90 / 180 (default) |
| `forecast_type` | VARCHAR(50) | See §4.2 |
| `p_positive` | FLOAT | Probability of positive outcome |
| `p_negative` | FLOAT | Probability of negative outcome |
| `p_neutral` | FLOAT | Probability of neutral outcome (p_positive + p_negative + p_neutral ≈ 1.0) |
| `confidence_band_low` | FLOAT | Lower bound of 80% confidence interval on p_positive |
| `confidence_band_high` | FLOAT | Upper bound |
| `why` | TEXT | Human-readable summary explanation |
| `invalidators` | JSON (list) | Conditions that would materially change this forecast |
| `analog_basis` | JSON (list) | `historical_analog` IDs that set the base rate |
| `similarity_basis` | JSON (list) | `similarity_edge` IDs that adjusted the base rate |
| `evidence_summary` | JSON (list) | Top N evidence items (condensed; full set in `forecast_evidence`) |
| `source_versions` | JSON (dict) | Row versions of source data at build time |
| `forecast_schema` | INTEGER | Schema version, default 1 |
| `user_id` | VARCHAR(36) nullable | NULL = global |
| `built_at` | TIMESTAMP WITH TZ | |
| `expires_at` | TIMESTAMP WITH TZ | built_at + TTL (default 24h near_term, 72h medium, 168h long) |

Unique constraint: `(entity_type, entity_key, horizon, forecast_type, user_id)`.

**Invariants (enforced by builder, checked by validation script):**
- `p_positive + p_negative + p_neutral` must be within 0.001 of 1.0.
- `why` must be non-empty.
- `invalidators` must be non-empty (minimum one invalidation condition).
- `analog_basis` or `similarity_basis` must be non-empty (at least one named evidence source).
- `confidence_band_low <= p_positive <= confidence_band_high`.
- No price fields. No target price. No recommendation field.

### Table 42: `forecast_evidence`

One row per piece of evidence backing a forecast vector. Normalized out of
`forecast_vector` so that evidence items can be queried independently for
explainability and audit.

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `forecast_id` | VARCHAR(36) | FK → `forecast_vector.id` |
| `source_type` | VARCHAR(50) | `historical_analog`, `similarity_edge`, `thesis_version`, `watchlist_signal`, `portfolio_exposure`, `failure_mode_stage` |
| `source_id` | VARCHAR(200) | Primary key of the source row |
| `direction` | VARCHAR(20) | `bullish`, `bearish`, `neutral` (relative to the thesis) |
| `contribution` | FLOAT | Signed magnitude of probability shift this item caused |
| `weight` | FLOAT | Weight in the ensemble [0, 1] |
| `description` | TEXT | Human-readable statement of what this evidence says |
| `entity_type` | VARCHAR(20) | Denormalized for query convenience |
| `entity_key` | VARCHAR(200) | Denormalized for query convenience |
| `user_id` | VARCHAR(36) nullable | |
| `built_at` | TIMESTAMP WITH TZ | |

No unique constraint — one forecast can have many evidence rows.

### Table 43: `forecast_calibration_log`

Immutable outcome records used to compute Brier scores and calibration curves.
Written when an outcome is observed; never updated.

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `forecast_id` | VARCHAR(36) | FK → `forecast_vector.id` (the forecast being evaluated) |
| `entity_type` | VARCHAR(20) | Denormalized |
| `entity_key` | VARCHAR(200) | Denormalized |
| `horizon` | VARCHAR(20) | Denormalized |
| `forecast_type` | VARCHAR(50) | Denormalized |
| `p_positive_at_forecast` | FLOAT | Snapshot of probability at time of forecast |
| `p_negative_at_forecast` | FLOAT | |
| `p_neutral_at_forecast` | FLOAT | |
| `actual_outcome` | VARCHAR(50) | `positive`, `negative`, `neutral`, `unknown`, `inconclusive` |
| `brier_score` | FLOAT | `(p_positive_at_forecast - outcome_indicator)^2` where outcome_indicator ∈ {0, 1} |
| `evaluation_source` | VARCHAR(50) | `thesis_state_change`, `risk_event_observed`, `watchlist_resolved`, `manual_review` |
| `evaluated_at` | TIMESTAMP WITH TZ | |
| `evaluator_notes` | TEXT nullable | |
| `user_id` | VARCHAR(36) nullable | |
| `created_at` | TIMESTAMP WITH TZ | |

**Immutability**: No UPDATE is ever issued against this table. Each re-evaluation
creates a new row. Calibration trends are computed over the set of rows with
`evaluated_at` within a window.

### Migration

`012_forecasting_engine.sql` — adds tables 41–43. All `IF NOT EXISTS`. No
`ALTER` on any existing table. No source-table write-back.

---

## 4. Forecast types and outputs

### 4.1 Entity types

| Entity type | What it is | Primary source tables |
|---|---|---|
| `company` | Ticker-level thesis trajectory | `company_dossier`, `dossier_core_debate` |
| `thesis` | Specific thesis version trajectory | `thesis_versions`, `dossier_variant` |
| `failure_mode` | Risk/failure mode emergence | `dossier_failure_mode`, `historical_analogs` |
| `portfolio` | Portfolio-level regime state | `portfolio_positions`, `cross_exposures` |

### 4.2 Forecast types

| Forecast type | Entity types | Question answered |
|---|---|---|
| `thesis_strengthening` | company, thesis | How likely is it that the current thesis strengthens at this horizon? |
| `thesis_weakening` | company, thesis | How likely is it that the current thesis weakens or breaks down? |
| `risk_emergence` | failure_mode | How likely is it that this tracked risk materializes? |
| `catalyst_realization` | company, thesis | How likely is it that a named catalyst resolves bullishly for the thesis? |
| `similarity_outcome` | company, failure_mode | Given peer outcomes in this similarity cluster, how did their trajectories resolve? |
| `regime_transition` | portfolio | How likely is a macro/sector regime shift that materially affects this portfolio? |

Each `(entity_type, forecast_type)` pair has exactly one valid probability
framework path (see §5). Combinations not listed here are invalid and must
be rejected by the builder.

### 4.3 Horizon semantics

| Horizon label | Default `horizon_days` | Appropriate for |
|---|---|---|
| `near_term` | 30 | Catalyst-driven events, watchlist signals, near-stage failure modes |
| `medium_term` | 90 | Thesis trajectory, risk emergence at intermediate sequence stage |
| `long_term` | 180 | Regime transition, portfolio restructuring signals, late-stage thesis evolution |

Horizon must always be stated explicitly in the output. A forecast without
an explicit horizon is invalid and must not be stored.

---

## 5. Probability framework

### 5.1 Ensemble computation

Every probability estimate is a weighted ensemble over four components:

```
P(outcome | entity, horizon) =
    w_base   × P_base_rate(outcome | analog_set)
  + w_sim    × P_sim_peer(outcome | similarity_cluster)
  + w_thesis × P_thesis_signal(outcome | thesis_state)
  + w_regime × P_regime(outcome | portfolio_context)

subject to:
    w_base + w_sim + w_thesis + w_regime = 1.0
    component weights vary by forecast_type (see §5.2)
    ensemble output clamped to [0.01, 0.99] per outcome bin
    outcome bins renormalized to sum to 1.0 after clamping
```

### 5.2 Component weights by forecast type

| Forecast type | w_base | w_sim | w_thesis | w_regime |
|---|---|---|---|---|
| `thesis_strengthening` | 0.35 | 0.25 | 0.30 | 0.10 |
| `thesis_weakening` | 0.35 | 0.25 | 0.30 | 0.10 |
| `risk_emergence` | 0.50 | 0.30 | 0.15 | 0.05 |
| `catalyst_realization` | 0.25 | 0.20 | 0.40 | 0.15 |
| `similarity_outcome` | 0.20 | 0.60 | 0.15 | 0.05 |
| `regime_transition` | 0.30 | 0.10 | 0.10 | 0.50 |

These weights are encoded in a versioned config dict (not hardcoded per-call)
so they can be A/B tested without touching the core engine.

### 5.3 Component P_base_rate

Source: `historical_analogs` matched to the entity.

For each analog matched to the entity:
- Extract `relevance_at_match` as its weight.
- Look up the analog's resolution (how did this episode resolve relative to
  the thesis the entity was tracking at the time it was matched?).
- Build a weighted frequency table over {positive, negative, neutral}.
- P_base_rate = that weighted frequency distribution.

If no analogs exist: P_base_rate = {positive: 0.33, negative: 0.33, neutral: 0.34}
(uniform prior — contributes no information).

Analog resolution states are inferred from `historical_analogs.mechanism` and
`concern_tags` combined with the current entity's `dossier_failure_mode.label`
and `sequence_stage`. The specific resolution-inference rules are defined in
`forecast_feature_builder` (one function per entity_type).

### 5.4 Component P_sim_peer

Source: `similarity_edge` (Phase 11, floor_passed=True, not expired).

For each edge connecting the entity to a peer:
- Retrieve the peer's own `P_base_rate` (recursively, one level only — no
  transitive traversal).
- Weight by `similarity_edge.score`.
- Aggregate into a peer-outcome distribution.
- P_sim_peer = score-weighted average of peer distributions.

If no floor-passed similarity edges exist: P_sim_peer = uniform prior.

**Important**: This is the only path by which Phase 11 data enters Phase 12.
Phase 12 reads `similarity_edge` rows. Phase 11 never reads `forecast_vector`
rows. The dependency is unidirectional.

### 5.5 Component P_thesis_signal

Source: `thesis_versions`, `dossier_variant`, `dossier_core_debate`.

- Compute the thesis confidence trajectory: is `confidence_score` in the most
  recent thesis version higher, lower, or flat relative to the N-1 version?
- Map to a directional signal: rising → bullish shift on `thesis_strengthening`;
  falling → bearish shift.
- Magnitude is `|delta_confidence| / 100` scaled to a [0, 0.3] shift.
- If no prior version exists: no shift (neutral).
- `core_debate_confidence` and `durability_*` fields provide secondary signals
  with half the weight of the primary confidence trajectory.

### 5.6 Component P_regime

Source: `portfolio_positions`, `cross_exposures`, watchlist macro signals.

- Aggregate portfolio-level exposure to the current macro_regime tag.
- If the entity's `historical_analogs` contain `macro_regime` values that
  cluster tightly, that cluster's historical outcome distribution becomes
  P_regime.
- Otherwise: portfolio-level aggregate `macro_regime` exposure signal from
  Phase 10D (regime concentration) provides a directional nudge.
- This component has the most uncertainty and the lowest weight in most
  forecast types (see §5.2).

### 5.7 Confidence bands

The 80% confidence interval on `p_positive` is computed from:
- Evidence count: more named analog/similarity sources → narrower band.
- Source quality: floor-passed similarity edges, high-relevance analogs →
  narrower band.
- Thesis data freshness: stale thesis (beyond TTL) → wider band.

Formula:

```
band_half_width = BASE_BAND_WIDTH × (1 / sqrt(effective_evidence_count))
                × staleness_discount

BASE_BAND_WIDTH = 0.20
effective_evidence_count = len(analog_basis) + 2 × len(similarity_basis)
staleness_discount = 1.0 if all sources fresh, up to 2.0 if all stale

confidence_band_low  = max(0.01, p_positive - band_half_width)
confidence_band_high = min(0.99, p_positive + band_half_width)
```

The band is always reported; it is never suppressed even when evidence is
plentiful.

### 5.8 Forecast schema versioning

`forecast_schema = 1` corresponds to the weights and formulas in §5.2–5.6.
When the probability framework is updated, `forecast_schema` increments. The
calibration log always denormalizes the probabilities at forecast time, so
old forecasts can be evaluated against their own schema version's expectations.

---

## 6. Explainability framework

Explainability is not optional. A forecast that cannot be explained is not
stored.

### 6.1 Required explanation fields

Every `forecast_vector` row must have:

| Field | Requirement |
|---|---|
| `why` | Non-empty prose explanation of the dominant probability driver |
| `invalidators` | Non-empty list of conditions that would materially change this forecast |
| `analog_basis` OR `similarity_basis` | At least one non-empty |
| `evidence_summary` | At least one evidence item with a human-readable `description` |

Builder enforces these at construction time. A forecast vector that fails any
of these checks is not upserted — it is discarded with a logger.warning entry.

### 6.2 `why` construction

`why` is built from the dominant component (the one with the highest
`contribution` magnitude among all evidence items in `forecast_evidence`):

```
"{entity_name}'s {forecast_type} probability is {p_positive:.0%} ({horizon_label})
 because {dominant_component_description}. This is based on {N} historical analog(s)
 and {M} similarity peer(s)."
```

If `p_positive < 0.35` and `p_negative > 0.45`:
```
"The balance of evidence points toward {negative_label} at {horizon_label}:
 {dominant_component_description}."
```

The exact template is defined in `forecast_explainability` and versioned
alongside `forecast_schema`.

### 6.3 `invalidators` construction

Three default invalidators are always generated:

1. **Evidence revision**: "If [primary analog] is reclassified or its outcome
   judgment changes, this forecast's base rate shifts."
2. **Similarity dissolution**: "If similarity peers diverge materially in
   mechanism or concern tags, the peer-outcome component becomes unreliable."
3. **Regime change**: "A macro_regime shift not captured in current portfolio
   context would require a full rebuild."

Entity-specific invalidators are appended:
- `thesis_weakening`: "If the company resolves the [primary_concern] ahead of
  schedule, this forecast's negative probability overstates risk."
- `risk_emergence`: "If the failure mode's sequence_stage advances beyond
  [current_stage], a higher-urgency forecast replaces this one."
- `catalyst_realization`: "If [catalyst] is removed from the watchlist as
  resolved, this forecast is superseded."

### 6.4 Evidence rendering

Every `forecast_evidence` row has a human-readable `description` field. At
read time, `forecast_read_service` assembles the top 5 evidence items (ranked
by `|contribution|`) into an ordered list for display:

```json
[
  {
    "rank": 1,
    "source_type": "historical_analog",
    "source_id": "...",
    "direction": "bearish",
    "description": "Inventory channel correction in semiconductor hardware (2015–2016) resolved negatively for thesis-strengthening in 8 of 10 analogous episodes.",
    "contribution": -0.12
  },
  ...
]
```

This list is the `evidence_summary` written into `forecast_vector` at build
time. The full set is always queryable from `forecast_evidence`.

### 6.5 Disclaimer (mandatory)

Every forecast output at every surface (API response, dossier block, briefing
line, digest item) must include:

> "These probabilities describe historical pattern frequencies and are not
> investment advice, price targets, or recommendations to buy or sell any
> security. Past patterns do not guarantee future outcomes."

The disclaimer string is a constant defined in `forecast_read_service`. No
delivery path is permitted to omit it.

---

## 7. Calibration framework

### 7.1 Purpose

Calibration answers: when the system said P(thesis_strengthening) = 0.70,
did the thesis strengthen 70% of the time? Without calibration, probabilities
are assertions, not measurements.

### 7.2 Outcome detection

Outcomes are logged to `forecast_calibration_log` when:

- **Thesis state change**: `thesis_versions` row is added with a materially
  different `confidence_score` (delta > 10 points in either direction) for an
  entity that had a `thesis_strengthening` or `thesis_weakening` forecast
  within its horizon window.
- **Risk event observed**: A `dossier_failure_mode` entry advances in
  `sequence_stage` for an entity that had a `risk_emergence` forecast.
- **Watchlist resolution**: A watchlist item is resolved (status change) for
  an entity that had a `catalyst_realization` forecast.
- **Manual review**: An operator can log outcomes via an admin function when
  automated detection does not apply.

Outcome detection runs in `forecast_calibration_service` and is triggered by
the continuous loop (Phase 10A) when the above source tables are written.

### 7.3 Brier score

For a binary outcome (event happened / did not happen):

```
brier_score = (p_positive_at_forecast - outcome_indicator)^2

outcome_indicator = 1.0 if actual_outcome == "positive"
                  = 0.0 if actual_outcome == "negative"
                  = None if actual_outcome in ("neutral", "unknown", "inconclusive")
```

Neutral and inconclusive outcomes are excluded from the binary Brier score.
A separate calibration metric tracks how well the system identifies when
"neutral" is the right forecast.

Rolling aggregates computed by `forecast_calibration_service`:
- **Mean Brier score** over 30d / 90d / 180d windows per forecast_type.
- **Resolution** (variance of forecasts — a system that always says 50% has
  zero resolution).
- **Reliability** (mean forecast vs. mean outcome frequency per probability
  bucket, aggregated into a calibration curve).

### 7.4 Calibration alerts

`forecast_observability` flags a calibration warning when:
- Mean Brier score over the last 30d exceeds `0.25` (equivalent to a system
  that says 50% on everything) for any forecast_type with ≥ 10 evaluated
  forecasts.
- Resolution is near zero (all forecasts clustering within ±0.05 of 0.50).
- A systematic direction bias is detected (mean outcome direction diverges
  from mean forecast direction by more than 15 percentage points).

Calibration warnings are surfaced in `/admin/forecast-status`. They do not
block production operation but are listed as acceptance-criteria gates before
any live delivery path is enabled.

### 7.5 Cold-start period

Phase 12 has no historical forecast record on first deployment. Calibration is
vacuous until at least 20 forecasts have been evaluated against observed
outcomes. The observability snapshot reports `calibration_status: "cold_start"`
until that threshold is reached, and `calibration_status: "active"` thereafter.

---

## 8. Delivery framework

Phase 12 does not implement a live delivery path. It defines where forecasts
go when they are eventually consumed. All delivery in Phase 12 is shadow-only,
journaled to `delivery_ledger` under `channel="forecast_shadow"`.

### 8.1 Consumption surfaces

| Surface | What forecast provides | Trigger |
|---|---|---|
| **Dossier** (company, ticker) | `forecast_context` block — a `resembles` analog for the future: "What this tends to look like at 30/90/180d" | Added by `dossier_forecast_enrichment` (read-only wrapper, same pattern as `dossier_similarity_enrichment`) |
| **Watchlist** briefing | Per-ticker forecast summary appended to the existing watchlist digest | Read by briefing builder when `forecast_delivery_enabled=true` |
| **Delivery briefing** | Forecast transitions (new floor-crossed, materially shifted) appear as a new section in the morning briefing | Transition detection in `forecast_delivery_service` (same pattern as `similarity_delivery_service`) |
| **Portfolio intelligence** | Portfolio-level `regime_transition` forecast added to the portfolio snapshot | Consumed by `portfolio_intelligence_service` as a read-only append |
| **Inbox** | High-confidence (p_positive > 0.75) forecast transitions delivered as a dedicated `forecast` notification kind | Gated by `forecast_delivery_enabled` and requires its own Phase 12+ slice |
| **Digest** | Weekly/daily probability summary across all tickers | Gated by `forecast_delivery_enabled` |

### 8.2 Dossier integration contract

`dossier_forecast_enrichment.get_full_dossier_with_forecast_context(session, ticker)`:
- Calls the existing `dossier_repo.get_full_dossier(session, ticker)`.
- Calls `forecast_read_service.get_forecast_facet_for_ticker(session, ticker)`.
- Attaches the result as `dossier["forecast_context"]`.
- Never modifies `head`, `debate`, `conviction`, `stance`, `verdict_rationale`,
  or any other existing field.
- Returns the unmodified dossier when `forecast_build_enabled=False` or
  `forecast_scoring_enabled=False`.

This is not wired into `dossier_injection_service`. The LLM prompt never sees
forecast probabilities. Forecast context is a read-layer annotation, not a
generation-layer input.

### 8.3 Transition detection

`forecast_delivery_service` mirrors `similarity_delivery_service` exactly:

Transition types (parallel structure):
- `first_crossing`: entity had no floor-passed forecast → now has one above a
  materiality threshold.
- `strengthened`: `p_positive` increased by ≥ `MATERIALITY_THRESHOLD` (default
  0.10) between consecutive forecasts.
- `weakened`: `p_positive` decreased by ≥ `MATERIALITY_THRESHOLD`.
- `disappeared`: floor-passed forecast expired without replacement.

Delivery gating: ALL of `forecast_build_enabled`, `forecast_scoring_enabled`,
and `forecast_shadow` must be True for shadow journaling. `forecast_delivery_enabled`
must additionally be True for any live notification.

Dedup: `loop_idempotency_service.guard_delivery` + `delivery_create` with
`channel="forecast_shadow"` and a deterministic `content_key` derived from
`(entity_type, entity_key, forecast_type, horizon, payload_hash)`.

### 8.4 What is not built in Phase 12

Phase 12 does not build:
- A live notification path (no rows with `kind="forecast"` in `Notification`).
- A public API route exposing forecast probabilities to end users.
- Any LLM prompt modification.
- Any conviction or stance modification.

These are explicit Phase 13+ decisions.

---

## 9. Validation framework

### 9.1 Unit test coverage

Each service has its own test file:

| File | Min tests | Focus |
|---|---|---|
| `test_forecast_feature_builder.py` | 20 | Per-entity-type feature extraction, null-session safety, source_versions written correctly |
| `test_forecast_probability_engine.py` | 25 | Ensemble math, clamping, normalization, weight configs |
| `test_forecast_explainability.py` | 15 | `why` non-empty, `invalidators` non-empty, disclaimer present |
| `test_forecast_read_service.py` | 15 | Floor-pass gating, expired exclusion, disclaimer mandatory |
| `test_forecast_observability.py` | 12 | Snapshot shape, calibration_status, safe_state logic |
| `test_forecast_invalidation_service.py` | 20 | Staleness detection, rebuild triggering, flag-gating |
| `test_forecast_calibration_service.py` | 15 | Brier score math, outcome logging, cold-start flag |

Total minimum: 122 unit tests.

### 9.2 Invariant tests (per-slice)

Every slice must include:
- **No source-table mutation test**: before/after snapshot of all source tables
  confirms no writes occurred.
- **No forecast/conviction import test**: AST-based import check confirms the
  module does not import from forecasting or conviction modules (enforcing SP-4
  for modules that should remain upstream of Phase 12).
- **Null-session safety test**: all async functions return safely when
  session=None.
- **Explainability completeness test**: any `forecast_vector` produced by the
  builder has all required explanation fields non-empty.
- **Disclaimer present test**: all read-service outputs include the disclaimer
  constant.

### 9.3 Calibration tests

`test_forecast_calibration_service.py` covers:
- Brier score computed correctly for a known (p_positive, outcome) pair.
- Neutral/inconclusive outcomes excluded from binary Brier.
- Calibration log rows are never updated (immutability enforced by absence of
  UPDATE calls in the service — verified by AST inspection of the service file).
- Cold-start threshold: `calibration_status = "cold_start"` when fewer than 20
  evaluated forecasts exist.
- Mean Brier score aggregation over 30d/90d/180d windows.

### 9.4 Drift tests

`test_forecast_calibration_service.py` additionally covers:
- Direction bias detection: synthetic forecasts all at 0.80, outcomes all
  negative → bias alert is raised.
- Resolution detection: all forecasts at 0.50 → zero resolution flagged.

### 9.5 Validation script

`tests/validate_12_forecast_shadow.py` — mirrors Phase 11 validation script:

Checks:
1. `db_table_count >= 43`
2. `forecast_vector` table exists
3. `forecast_evidence` table exists
4. `forecast_calibration_log` table exists
5. All forecast service modules importable
6. All 6 flags default to inert values
7. No forecast module imports similarity_* (unidirectional dependency enforced)
8. No forecast module imports conviction/recommendation/notification_service
9. No public (non-`/admin/`) route exposes "forecast"
10. `/admin/forecast-status` and `/admin/forecast/{ticker}` declared
11. `safe_state=True` with session=None
12. `safe_state=True` on a clean DB
13. Zero `Notification` rows with `kind="forecast"`
14. Zero `forecast_shadow` ledger rows escalated to `status="delivered"`
15. Every floor-passed forecast has non-empty `why`, `invalidators`,
    `analog_basis` or `similarity_basis`
16. Disclaimer constant present in `forecast_read_service` module source
17. Calibration log immutability: no UPDATE statement in
    `forecast_calibration_service` source (AST-verified)
18. No source-table mutation during the validation probe itself

18 checks. Exit 0 / exit 1.

---

## 10. Rollout strategy

### 10.1 Current state at Phase 12 delivery

All flags default inert. No forecast is computed automatically. No forecast
appears in any dossier, briefing, or inbox. The tables exist; they are empty.
`/admin/forecast-status` reports `safe_state: true` and all counts at zero.

### 10.2 Rollout sequence

**Step 1 — Shadow build (internal only):**
- Flip `FORECAST_BUILD_ENABLED=true`.
- A future Slice N+ loop producer (not in Phase 12 base) calls the builders
  automatically. Until then, builders are invocable only manually or via the
  internal probe procedure.
- No probability computation, no delivery, no dossier change.

**Step 2 — Shadow scoring + shadow journaling:**
- Flip `FORECAST_SCORING_ENABLED=true` (keeping `FORECAST_SHADOW=true`).
- Probability engine runs. Transition events journal to
  `delivery_ledger(channel="forecast_shadow")`. Still zero user-visible
  impact — no flush pipeline drains this channel.
- Monitor `/admin/forecast-status` for `safe_state: true` and zero
  `shadow_escalated_count`.

**Step 3 — Calibration active:**
- Flip `FORECAST_CALIBRATION_ENABLED=true`.
- Outcome detection begins. Brier scores accumulate.
- Monitor `/admin/forecast-status` for `calibration_status: "active"` (≥20
  evaluated forecasts) and mean Brier score < 0.25.
- This step has no user-visible impact.

**Step 4 — Dossier enrichment opt-in (internal review only):**
- A specific internal caller invokes
  `dossier_forecast_enrichment.get_full_dossier_with_forecast_context`
  instead of `get_full_dossier` for internal review sessions.
- Never wired into `dossier_injection_service`.
- Requires explicit sign-off: the `forecast_context` block is additive and
  read-only, but this is the first time forecast data appears in a human-facing
  surface, and it needs a human to review the output quality before any broader
  exposure.

**Step 5 — Live delivery (out of scope for Phase 12):**
- Would require: (a) implementing the live branch in `forecast_delivery_service`
  (analogous to Phase 10C's shadow→live promotion), (b) adding
  `kind="forecast"` to the Notification model, (c) a Phase 13 design
  decision on which surfaces display forecast probabilities with what disclaimer
  UX, and (d) a calibration review confirming mean Brier < 0.20 over at
  least 60 evaluated forecasts.
- None of this is in Phase 12.

### 10.3 Rollback

Every step is flag-gated and additive:
- Setting any gating flag back to `false` immediately returns that code path to
  its inert form.
- `forecast_vector`, `forecast_evidence`, `forecast_calibration_log` are pure
  cache / analytics tables. Truncating them loses only rebuild latency and
  calibration history; nothing in the dossier, delivery, or briefing layer
  depends on their continued existence when `forecast_build_enabled=false`.
- No schema revert needed. `012_forecasting_engine.sql` only adds three new
  tables. Rolling back code does not require rolling back schema.

---

## 11. Admin routes

Two new routes, both under `/admin/`, both read-only, both delegating to
`forecast_observability`:

**`GET /admin/forecast-status`**

Returns the full observability snapshot:
```json
{
  "flags": {
    "forecast_build_enabled": false,
    "forecast_scoring_enabled": false,
    "forecast_targets_enabled": "",
    "forecast_shadow": true,
    "forecast_calibration_enabled": false,
    "forecast_delivery_enabled": false
  },
  "db_available": true,
  "vector_counts": {"company": 0, "thesis": 0, "failure_mode": 0, "portfolio": 0},
  "evidence_count": 0,
  "calibration_log_count": 0,
  "calibration_status": "cold_start",
  "mean_brier_score_30d": null,
  "shadow_delivery_count": 0,
  "shadow_escalated_count": 0,
  "live_notification_count": 0,
  "safe_state": true,
  "snapshot_utc": "..."
}
```

**`GET /admin/forecast/{ticker}`**

Returns the ticker's current forecasts (all horizons, all forecast types,
floor-passed only, non-expired), formatted for human inspection. Includes
full `evidence_summary`, `why`, `invalidators`, confidence bands, and the
mandatory disclaimer.

---

## 12. Security and safety constraints

### SP-4 extension (no forecast → conviction pipeline)

Phase 11 established SP-4: similarity must not influence forecasts. Phase 12
extends this:

**Forecast output must not influence conviction, stance, verdict_rationale,
or any LLM prompt, directly or indirectly.**

Enforcement:
- No `forecast_*` module imports from `conviction_engine`, `recommendation`,
  `dossier_injection_service`, or `notification_service`.
- No existing module is modified to import from `forecast_*` until Phase 13
  explicitly designs and approves such a link.
- AST import-graph check in the validation script catches violations.

### No credential leakage

`forecast_observability` exposes only counts, booleans, floats, timestamps,
and the four flag values. No payload JSON, no raw model output, no dossier
text, no prompt text ever appears in the observability snapshot.

### Disclaimer enforcement

The disclaimer string is defined once as a constant in `forecast_read_service`.
Any function that returns forecast probabilities must attach this constant.
The validation script checks that the constant exists in the source. Any
API route that returns forecast data includes it in the response schema.

### No price fields

The data model (§3) has no column for price, target price, fair value, or
price-change-percent. Adding such a column requires a schema migration that
must be reviewed against the Phase 12 philosophical constraints (§0). The
validator checks that the `forecast_vector` table definition does not contain
any such column.

---

## 13. Risks and mitigations

| Risk | Likelihood | Mitigation |
|---|---|---|
| Base rates from small analog sets are unreliable | High | Confidence band widens with small `effective_evidence_count`; cold-start calibration status surfaced prominently |
| Similarity engine has few floor-passed edges (Phase 11 cold start) | High | `w_sim` component falls back to uniform prior gracefully; no crash |
| Calibration lag — outcomes take 30–180 days to observe | Certain | Cold-start period is expected and surfaced; no live delivery until Brier < 0.20 over ≥60 forecasts |
| Forecast probabilities misread as investment advice | High | Disclaimer is mandatory and structural (not optional); no price fields exist; no buy/sell recommendation field exists |
| Phase 11 similarity cold start reduces P_sim_peer quality | Medium | Ensemble still produces valid output (falls back to uniform prior); observability snapshot surfaces the dependency |
| Forecast schema drift — old forecasts evaluated against new weights | Medium | `forecast_schema` versioning + calibration log snapshots probabilities at forecast time |
| Dependency direction violation (something in Phase 11 imports Phase 12) | Low | AST import-graph check in validation script; same enforcement as Phase 11 SP-4 |
| Calibration outcomes detected incorrectly (false positive/negative) | Medium | Manual review override; `evaluator_notes` field in calibration log; inconclusive status for ambiguous cases |

---

## 14. Dependency map

```
                         ┌─────────────────────────────────────┐
                         │           Phase 12 services          │
                         │                                      │
   historical_analogs ──▶│  forecast_feature_builder            │
   company_dossier    ──▶│  forecast_probability_engine ────────│──▶ forecast_vector
   thesis_versions    ──▶│  forecast_explainability             │    forecast_evidence
   dossier_variant    ──▶│  forecast_invalidation_service       │    forecast_calibration_log
   similarity_edge    ──▶│  forecast_calibration_service        │
   portfolio_positions──▶│  forecast_read_service               │
   cross_exposures    ──▶│  forecast_observability              │
                         └─────────────────────────────────────┘
                                          │
                              read-only consumption
                                          │
                    ┌─────────────────────┼──────────────────┐
                    ▼                     ▼                   ▼
           dossier_forecast_    forecast_delivery_   /admin/forecast-*
           enrichment            service (shadow)    (read-only admin)
```

**Nothing above the top line reads from `forecast_vector`.**
**Nothing inside the top box imports from conviction, recommendation, LLM, or notification.**

---

## 15. Acceptance criteria for any Phase 13 live delivery

Before any Phase 13 slice proposes live delivery or UI surfacing of forecasts:

1. `tests/validate_12_forecast_shadow.py` exits 0 in production.
2. `/admin/forecast-status` reports `safe_state: true`, `shadow_escalated_count: 0`,
   `live_notification_count: 0`.
3. All `tests/test_services/test_forecast_*.py` pass.
4. `calibration_status: "active"` (≥20 evaluated forecasts).
5. `mean_brier_score_30d < 0.25` for all forecast types with ≥10 evaluated
   forecasts.
6. A documented internal probe has been run against representative tickers and
   the output quality (why text, invalidators, evidence items) has been reviewed
   by a human for coherence and accuracy.
7. A design decision is written down (not implied) specifying: which UI surface,
   what disclaimer UX, and explicit confirmation that no forecast output has ever
   appeared in a conviction, stance, or verdict field. SP-4 extension (§12)
   verified by re-running the AST import check.
8. Mean Brier score over ≥60 evaluated forecasts is < 0.20 before any live
   notification path is opened.

---

## 16. Slice plan

Suggested sequencing (each slice is independently mergeable, shadow-gated):

| Slice | Deliverable |
|---|---|
| 12.1 | Schema only: tables 41–43, ORM models, migration, repository, schema tests |
| 12.2 | Feature builder: company (T1) and failure_mode (T4) feature extraction |
| 12.3 | Probability engine: ensemble math, weight configs, clamping, normalization |
| 12.4 | Explainability: `why`, `invalidators`, disclaimer, evidence assembly |
| 12.5 | Invalidation + rebuild: staleness detection, batch rebuild, flag gating |
| 12.6 | Read service + admin routes + dossier enrichment wrapper |
| 12.7 | Shadow delivery wiring: transition detection + shadow journaling |
| 12.8 | Calibration service: outcome detection, Brier score, drift detection |
| 12.9 | Observability service + validation script + rollout documentation |

Slice 12.9 corresponds to Phase 12 complete. Slices 12.2 and 12.4 may be
combined if the feature-builder output is simple enough that explainability
can be built in the same slice without scope creep.

**Do not implement beyond Slice 12.9 in Phase 12.** Thesis-level (T2) and
portfolio-level forecasts are deliberately deferred to confirm the T1/T4
framework is sound before expanding targets.
