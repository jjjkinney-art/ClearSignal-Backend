-- Phase 12 · Slice 1 — Forecasting Engine Schema
--
-- Idempotent (uses IF NOT EXISTS throughout). Apply AFTER 011_similarity_engine.sql.
--
-- Adds three forecasting tables only:
--   forecast_vector          — probability distribution per entity/horizon/type
--   forecast_evidence        — normalised evidence rows backing each forecast_vector
--   forecast_calibration_log — immutable outcome records for Brier-score calibration
--
-- NO existing table is modified. No column added to any source table.
-- No FK constraints into source tables (soft references via entity_key / source_versions).
-- All three tables are DERIVED/ANALYTICS and disposable — they can be dropped and
-- rebuilt from the intelligence substrate.
--
--   db_table_count: 40 → 43 (three new tables).
--
-- Safety invariants (enforced at application layer, not DDL):
--   * No target-price column exists anywhere in this schema.
--   * No buy / sell / hold / recommendation field exists.
--   * No forecast table ever carries raw dossier text, prompt text, or LLM output.
--   * forecast_build_enabled and forecast_scoring_enabled default to false.
--     Tables are inert until those flags are flipped.
--   * Forecasting never writes to any source table in this or any later slice.
--   * forecast_calibration_log is append-only: no UPDATE or DELETE path exists
--     in the application layer (enforced by AST inspection in the validation script).
--   * Similarity (Phase 11) never imports from Phase 12 — dependency is one-way.
--
-- forecast_type valid values (schema v1):
--   thesis_strengthening | thesis_weakening | risk_emergence |
--   catalyst_realization | similarity_outcome | regime_transition
--
-- entity_type valid values:
--   company | thesis | failure_mode | portfolio
--
-- horizon valid values:
--   near_term | medium_term | long_term
--
-- forecast_schema: bumped when the probability framework or weight config changes;
--   stale vectors must be recomputed before serving.


-- ---------------------------------------------------------------------------
-- 41. forecast_vector
-- ---------------------------------------------------------------------------
--
-- One row per (entity_type, entity_key, horizon, forecast_type, user_id).
-- Stores the full probability distribution and the explainability payload.
--
-- p_positive / p_negative / p_neutral: constrained at the application layer
--   to sum within 0.001 of 1.0 (enforced by the probability engine before upsert).
--   No DDL CHECK constraint to keep the schema SQLite-compatible.
--
-- why: mandatory prose explanation of the dominant probability driver.
--   Empty string MUST NOT be stored — the builder discards incomplete forecasts.
--
-- invalidators: JSON list of named conditions that would materially change
--   this forecast. Must be non-empty before storage.
--
-- analog_basis / similarity_basis: JSON lists of source IDs.
--   At least one must be non-empty (the evidence requirement).
--
-- evidence_summary: JSON list of top-N condensed evidence items (full set in
--   forecast_evidence). Populated at build time for fast read-service access.
--
-- source_versions: JSON map {table: row_version} for staleness detection.
--   Mismatch with live substrate values triggers a rebuild.
--
-- forecast_schema: bumped when probability formula or weight config changes.

CREATE TABLE IF NOT EXISTS forecast_vector (
    id              VARCHAR(36)     NOT NULL,

    -- entity_type: company | thesis | failure_mode | portfolio
    entity_type     VARCHAR(20)     NOT NULL,
    -- entity_key: ticker | thesis_id | failure_mode_id | portfolio_id
    entity_key      VARCHAR(200)    NOT NULL,

    -- Horizon
    -- horizon: near_term | medium_term | long_term
    horizon         VARCHAR(20)     NOT NULL,
    -- horizon_days: 30 | 90 | 180 (or custom)
    horizon_days    INTEGER         NOT NULL DEFAULT 30,

    -- forecast_type: thesis_strengthening | thesis_weakening | risk_emergence |
    --   catalyst_realization | similarity_outcome | regime_transition
    forecast_type   VARCHAR(50)     NOT NULL,

    -- Probability distribution — must sum to ~1.0 (enforced by app layer)
    p_positive      FLOAT           NOT NULL DEFAULT 0.33,
    p_negative      FLOAT           NOT NULL DEFAULT 0.33,
    p_neutral       FLOAT           NOT NULL DEFAULT 0.34,

    -- 80% confidence interval on p_positive
    confidence_band_low  FLOAT      NOT NULL DEFAULT 0.0,
    confidence_band_high FLOAT      NOT NULL DEFAULT 1.0,

    -- Explainability (MUST be non-empty before storage)
    -- why: dominant probability driver, human-readable prose
    why             TEXT            NOT NULL DEFAULT '',
    -- invalidators: JSON list of named invalidation conditions
    invalidators    TEXT            NOT NULL DEFAULT '[]',

    -- Evidence provenance — at least one must be non-empty
    -- analog_basis: JSON list of historical_analog IDs that set the base rate
    analog_basis    TEXT            NOT NULL DEFAULT '[]',
    -- similarity_basis: JSON list of similarity_edge IDs that adjusted the base rate
    similarity_basis TEXT           NOT NULL DEFAULT '[]',

    -- evidence_summary: JSON list, top-N condensed from forecast_evidence
    evidence_summary TEXT           NOT NULL DEFAULT '[]',

    -- Provenance: {table: row_version} for staleness detection
    source_versions TEXT            NOT NULL DEFAULT '{}',

    -- Invalidation key — bumped when probability formula or weight config changes
    forecast_schema INTEGER         NOT NULL DEFAULT 1,

    -- user_id: identity scoping (Phase 16). NULL = global.
    user_id         VARCHAR(36)     DEFAULT NULL,

    -- TTL materialisation
    built_at        TIMESTAMPTZ     NOT NULL DEFAULT now(),
    expires_at      TIMESTAMPTZ     NOT NULL DEFAULT (now() + INTERVAL '24 hours'),

    PRIMARY KEY (id),
    CONSTRAINT uq_forecast_vector_entity_horizon_type_user
        UNIQUE (entity_type, entity_key, horizon, forecast_type, user_id)
);

CREATE INDEX IF NOT EXISTS ix_fv_entity
    ON forecast_vector (entity_type, entity_key);

CREATE INDEX IF NOT EXISTS ix_fv_entity_type
    ON forecast_vector (entity_type);

CREATE INDEX IF NOT EXISTS ix_fv_forecast_type
    ON forecast_vector (forecast_type);

CREATE INDEX IF NOT EXISTS ix_fv_user_id
    ON forecast_vector (user_id);

CREATE INDEX IF NOT EXISTS ix_fv_expires_at
    ON forecast_vector (expires_at);

CREATE INDEX IF NOT EXISTS ix_fv_forecast_schema
    ON forecast_vector (forecast_schema);


-- ---------------------------------------------------------------------------
-- 42. forecast_evidence
-- ---------------------------------------------------------------------------
--
-- One row per piece of evidence backing a forecast_vector.
-- Normalised out of forecast_vector so evidence items are queryable
-- independently for explainability, audit, and calibration diagnostics.
--
-- source_type valid values:
--   historical_analog | similarity_edge | thesis_version | watchlist_signal |
--   portfolio_exposure | failure_mode_stage
--
-- direction: bullish | bearish | neutral  (relative to the thesis)
--
-- contribution: signed magnitude of probability shift caused by this evidence.
--   Negative = bearish shift on p_positive.
--
-- weight: this evidence item's weight in the ensemble [0, 1].
--
-- description: human-readable statement of what this evidence says.
--   MUST be non-empty.

CREATE TABLE IF NOT EXISTS forecast_evidence (
    id              VARCHAR(36)     NOT NULL,

    -- Soft FK to forecast_vector.id — no CASCADE
    forecast_id     VARCHAR(36)     NOT NULL,

    -- source_type: historical_analog | similarity_edge | thesis_version |
    --   watchlist_signal | portfolio_exposure | failure_mode_stage
    source_type     VARCHAR(50)     NOT NULL,
    -- source_id: primary key of the source row
    source_id       VARCHAR(200)    NOT NULL,

    -- direction: bullish | bearish | neutral
    direction       VARCHAR(20)     NOT NULL DEFAULT 'neutral',

    -- Signed probability shift caused by this evidence item
    contribution    FLOAT           NOT NULL DEFAULT 0.0,

    -- Weight in the ensemble [0, 1]
    weight          FLOAT           NOT NULL DEFAULT 0.0,

    -- Human-readable statement — MUST be non-empty
    description     TEXT            NOT NULL DEFAULT '',

    -- Denormalised for query convenience
    entity_type     VARCHAR(20)     NOT NULL DEFAULT '',
    entity_key      VARCHAR(200)    NOT NULL DEFAULT '',

    -- user_id: identity scoping (Phase 16). NULL = global.
    user_id         VARCHAR(36)     DEFAULT NULL,

    built_at        TIMESTAMPTZ     NOT NULL DEFAULT now(),

    PRIMARY KEY (id)
);

CREATE INDEX IF NOT EXISTS ix_fe_forecast_id
    ON forecast_evidence (forecast_id);

CREATE INDEX IF NOT EXISTS ix_fe_entity
    ON forecast_evidence (entity_type, entity_key);

CREATE INDEX IF NOT EXISTS ix_fe_source_type
    ON forecast_evidence (source_type, source_id);

CREATE INDEX IF NOT EXISTS ix_fe_user_id
    ON forecast_evidence (user_id);


-- ---------------------------------------------------------------------------
-- 43. forecast_calibration_log
-- ---------------------------------------------------------------------------
--
-- Immutable outcome records used to compute Brier scores and calibration
-- curves.  This table is append-only — no UPDATE or DELETE is ever issued
-- against it from the application layer.
--
-- actual_outcome valid values:
--   positive | negative | neutral | unknown | inconclusive
--
-- brier_score = (p_positive_at_forecast - outcome_indicator)^2
--   where outcome_indicator = 1.0 if positive, 0.0 if negative.
--   NULL when actual_outcome is neutral / unknown / inconclusive
--   (these are excluded from the binary Brier metric).
--
-- evaluation_source valid values:
--   thesis_state_change | risk_event_observed | watchlist_resolved | manual_review
--
-- created_at is immutable — this row is NEVER updated.

CREATE TABLE IF NOT EXISTS forecast_calibration_log (
    id              VARCHAR(36)     NOT NULL,

    -- Soft FK to forecast_vector.id — denormalised to survive vector expiry
    forecast_id     VARCHAR(36)     NOT NULL,

    -- Denormalised from the forecast_vector row at evaluation time
    entity_type     VARCHAR(20)     NOT NULL DEFAULT '',
    entity_key      VARCHAR(200)    NOT NULL DEFAULT '',
    horizon         VARCHAR(20)     NOT NULL DEFAULT '',
    forecast_type   VARCHAR(50)     NOT NULL DEFAULT '',

    -- Snapshot of probabilities at the time of the original forecast
    p_positive_at_forecast  FLOAT   NOT NULL DEFAULT 0.0,
    p_negative_at_forecast  FLOAT   NOT NULL DEFAULT 0.0,
    p_neutral_at_forecast   FLOAT   NOT NULL DEFAULT 0.0,

    -- Observed outcome
    -- actual_outcome: positive | negative | neutral | unknown | inconclusive
    actual_outcome  VARCHAR(50)     NOT NULL DEFAULT 'unknown',

    -- Brier score for this forecast/outcome pair.
    -- NULL when actual_outcome is neutral / unknown / inconclusive.
    brier_score     FLOAT           DEFAULT NULL,

    -- evaluation_source: thesis_state_change | risk_event_observed |
    --   watchlist_resolved | manual_review
    evaluation_source VARCHAR(50)   NOT NULL DEFAULT 'manual_review',

    -- When the outcome was observed
    evaluated_at    TIMESTAMPTZ     NOT NULL DEFAULT now(),

    -- Optional operator notes
    evaluator_notes TEXT            DEFAULT NULL,

    -- user_id: identity scoping (Phase 16). NULL = global.
    user_id         VARCHAR(36)     DEFAULT NULL,

    -- created_at is immutable — this row is NEVER updated
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT now(),

    PRIMARY KEY (id)
);

CREATE INDEX IF NOT EXISTS ix_fcl_forecast_id
    ON forecast_calibration_log (forecast_id);

CREATE INDEX IF NOT EXISTS ix_fcl_entity
    ON forecast_calibration_log (entity_type, entity_key);

CREATE INDEX IF NOT EXISTS ix_fcl_evaluated_at
    ON forecast_calibration_log (evaluated_at);

CREATE INDEX IF NOT EXISTS ix_fcl_forecast_type
    ON forecast_calibration_log (forecast_type, evaluated_at);

CREATE INDEX IF NOT EXISTS ix_fcl_user_id
    ON forecast_calibration_log (user_id);
