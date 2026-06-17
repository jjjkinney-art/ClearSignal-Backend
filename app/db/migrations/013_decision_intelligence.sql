-- Phase 13 · Slice 1 — Decision Intelligence Schema
--
-- Idempotent (uses IF NOT EXISTS throughout). Apply AFTER 012_forecasting_engine.sql.
--
-- Adds three decision-intelligence tables only:
--   decision_priority     — priority ranking per attention candidate / user scope
--   decision_evidence     — normalised evidence rows backing each decision_priority
--   decision_ranking_log  — immutable ranking snapshots + outcome attribution
--
-- NO existing table is modified. No column added to any source table.
-- No FK constraints into source tables (soft references via entity_key / source_ref /
-- source_versions). All three tables are DERIVED/ANALYTICS and disposable — they can
-- be dropped and rebuilt from the intelligence substrate.
--
--   db_table_count: 43 → 46 (three new tables).
--
-- Safety invariants (enforced at application layer, not DDL):
--   * Decision Intelligence PRIORITIZES information; it does not make investment
--     decisions. NO buy / sell / hold / recommendation / position_size /
--     target_price / trade / execution column exists anywhere in this schema.
--   * No decision table ever carries raw dossier text, prompt text, or LLM output.
--   * decision_build_enabled and decision_scoring_enabled default to false, and
--     decision_delivery_enabled defaults to false (shadow true). Tables are inert
--     until those flags are flipped; no surface is reordered during the build phase.
--   * Decision Intelligence never writes to any source table in this or any later
--     slice — it is a pure sink (SP-5). Nothing in Phases 9G–12 imports Phase 13.
--   * decision_ranking_log is append-only: no UPDATE or DELETE path exists in the
--     application layer (enforced by AST inspection in the validation script).
--
-- candidate_type valid values (schema v1):
--   forecast | risk | catalyst | watchlist_item |
--   portfolio_exposure | thesis_transition | similarity_match
--
-- entity_type valid values:
--   company | thesis | failure_mode | portfolio
--
-- decision_priority (bucket) valid values:
--   critical | high | medium | low | informational
--
-- decision_schema: bumped when the scoring formula / weights / thresholds change;
--   stale priorities must be recomputed before serving.


-- ---------------------------------------------------------------------------
-- 44. decision_priority
-- ---------------------------------------------------------------------------
--
-- One row per (candidate_type, entity_type, entity_key, source_ref, user_id).
-- Stores the five component scores, the composite rank score + bucket, and the
-- explainability payload.
--
-- Score invariant: all five component scores and decision_rank_score are
--   constrained at the application layer to [0, 1] (enforced by the scoring
--   engine before upsert — Phase 13 Slice 3). No DDL CHECK to stay SQLite-compatible.
--
-- decision_reason / why_now: mandatory prose. Empty MUST NOT be stored — the
--   builder discards priorities that cannot explain themselves.
--
-- deprioritizers: JSON list of named conditions that would lower this priority.
--   Must be non-empty before storage.
--
-- user_id NULL = global / intrinsic tier; non-NULL = portfolio-adjusted user tier.

CREATE TABLE IF NOT EXISTS decision_priority (
    id                  VARCHAR(36)     NOT NULL,

    -- candidate_type: forecast | risk | catalyst | watchlist_item |
    --   portfolio_exposure | thesis_transition | similarity_match
    candidate_type      VARCHAR(30)     NOT NULL,

    -- entity_type: company | thesis | failure_mode | portfolio
    entity_type         VARCHAR(20)     NOT NULL,
    -- entity_key: ticker | thesis_id | failure_mode_id | portfolio_id
    entity_key          VARCHAR(200)    NOT NULL,

    -- source_ref: id of the originating artifact (forecast_vector.id, etc.)
    source_ref          VARCHAR(200)    NOT NULL DEFAULT '',

    -- decision_priority: bucket — critical | high | medium | low | informational
    decision_priority   VARCHAR(20)     NOT NULL DEFAULT 'informational',
    -- Continuous [0,1] ordering score
    decision_rank_score FLOAT           NOT NULL DEFAULT 0.0,

    -- Five component scores, each [0,1]
    attention_score     FLOAT           NOT NULL DEFAULT 0.0,
    urgency_score       FLOAT           NOT NULL DEFAULT 0.0,
    impact_score        FLOAT           NOT NULL DEFAULT 0.0,
    confidence_score    FLOAT           NOT NULL DEFAULT 0.0,
    uncertainty_score   FLOAT           NOT NULL DEFAULT 0.0,

    -- Explainability (MUST be non-empty before storage)
    -- decision_reason: dominant-factor prose ("why important")
    decision_reason     TEXT            NOT NULL DEFAULT '',
    -- why_now: urgency-driver prose ("why now")
    why_now             TEXT            NOT NULL DEFAULT '',
    -- deprioritizers: JSON list of named conditions that would lower this priority
    deprioritizers      TEXT            NOT NULL DEFAULT '[]',

    -- evidence_summary: JSON list, top-N condensed from decision_evidence
    evidence_summary    TEXT            NOT NULL DEFAULT '[]',

    -- Provenance: {table: row_version} for staleness detection
    source_versions     TEXT            NOT NULL DEFAULT '{}',

    -- Invalidation key — bumped when scoring formula / weights / thresholds change
    decision_schema     INTEGER         NOT NULL DEFAULT 1,

    -- user_id: identity scoping (Phase 16). NULL = global / intrinsic tier.
    user_id             VARCHAR(36)     DEFAULT NULL,

    -- TTL materialisation
    built_at            TIMESTAMPTZ     NOT NULL DEFAULT now(),
    expires_at          TIMESTAMPTZ     NOT NULL DEFAULT (now() + INTERVAL '24 hours'),

    PRIMARY KEY (id),
    CONSTRAINT uq_decision_priority_candidate_entity_source_user
        UNIQUE (candidate_type, entity_type, entity_key, source_ref, user_id)
);

CREATE INDEX IF NOT EXISTS ix_dp_entity
    ON decision_priority (entity_type, entity_key);

CREATE INDEX IF NOT EXISTS ix_dp_candidate_type
    ON decision_priority (candidate_type);

CREATE INDEX IF NOT EXISTS ix_dp_priority
    ON decision_priority (decision_priority);

CREATE INDEX IF NOT EXISTS ix_dp_user_id
    ON decision_priority (user_id);

CREATE INDEX IF NOT EXISTS ix_dp_expires_at
    ON decision_priority (expires_at);

CREATE INDEX IF NOT EXISTS ix_dp_decision_schema
    ON decision_priority (decision_schema);

CREATE INDEX IF NOT EXISTS ix_dp_rank_score
    ON decision_priority (decision_rank_score);


-- ---------------------------------------------------------------------------
-- 45. decision_evidence
-- ---------------------------------------------------------------------------
--
-- One row per contributing upstream signal backing a decision_priority.
-- Normalised out of decision_priority so evidence items are queryable
-- independently for explainability and audit.
--
-- source_type valid values:
--   forecast_vector | similarity_edge | historical_analog | thesis_version |
--   watchlist_signal | portfolio_exposure | delivery_transition | calibration_log
--
-- dimension: attention | urgency | impact | confidence | uncertainty
--   — which component score this evidence fed.
--
-- contribution: signed contribution to that dimension.
-- weight: this evidence item's weight in the dimension aggregate [0, 1].
-- description: human-readable statement — MUST be non-empty.

CREATE TABLE IF NOT EXISTS decision_evidence (
    id              VARCHAR(36)     NOT NULL,

    -- Soft FK to decision_priority.id — no CASCADE
    priority_id     VARCHAR(36)     NOT NULL,

    -- source_type: forecast_vector | similarity_edge | historical_analog |
    --   thesis_version | watchlist_signal | portfolio_exposure |
    --   delivery_transition | calibration_log
    source_type     VARCHAR(40)     NOT NULL,
    -- source_id: primary key of the source row
    source_id       VARCHAR(200)    NOT NULL,

    -- dimension: attention | urgency | impact | confidence | uncertainty
    dimension       VARCHAR(20)     NOT NULL DEFAULT 'attention',

    -- Signed contribution to the dimension aggregate
    contribution    FLOAT           NOT NULL DEFAULT 0.0,

    -- Weight in the dimension aggregate [0, 1]
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

CREATE INDEX IF NOT EXISTS ix_de_priority_id
    ON decision_evidence (priority_id);

CREATE INDEX IF NOT EXISTS ix_de_source
    ON decision_evidence (source_type, source_id);

CREATE INDEX IF NOT EXISTS ix_de_entity
    ON decision_evidence (entity_type, entity_key);

CREATE INDEX IF NOT EXISTS ix_de_user_id
    ON decision_evidence (user_id);


-- ---------------------------------------------------------------------------
-- 46. decision_ranking_log
-- ---------------------------------------------------------------------------
--
-- Immutable ranking snapshot used for drift and stability validation.
-- This table has NO UPDATE or DELETE path in any service or repository.
-- Each snapshot (and each later outcome attribution) creates a NEW row.
-- Modelled on forecast_calibration_log: append-only, immutable, permanent.
--
-- snapshot_reason: scheduled | rebuild | transition | manual_review
--
-- realized_significance: material | immaterial | unknown — filled later by
--   appending a NEW row keyed to the same priority_id, never by updating an
--   existing row. Used by Phase 13 Slice 9 calibration for rank-order agreement
--   (NOT a Brier score).

CREATE TABLE IF NOT EXISTS decision_ranking_log (
    id                    VARCHAR(36)   NOT NULL,

    -- Soft FK to decision_priority.id — denormalised to survive priority expiry
    priority_id           VARCHAR(36)   NOT NULL,

    -- Denormalised from the priority row at snapshot time
    candidate_type        VARCHAR(30)   NOT NULL DEFAULT '',
    entity_type           VARCHAR(20)   NOT NULL DEFAULT '',
    entity_key            VARCHAR(200)  NOT NULL DEFAULT '',

    -- user_id: identity scoping (Phase 16). NULL = global.
    user_id               VARCHAR(36)   DEFAULT NULL,

    -- Bucket + score at snapshot time
    decision_priority     VARCHAR(20)   NOT NULL DEFAULT 'informational',
    decision_rank_score   FLOAT         NOT NULL DEFAULT 0.0,
    -- Ordinal position within the user's ranked set at snapshot time
    rank_position         INTEGER       NOT NULL DEFAULT 0,

    -- snapshot_reason: scheduled | rebuild | transition | manual_review
    snapshot_reason       VARCHAR(40)   NOT NULL DEFAULT 'scheduled',

    -- realized_significance: material | immaterial | unknown (filled later, append-only)
    realized_significance VARCHAR(20)   DEFAULT NULL,

    -- When this snapshot / outcome was recorded — immutable
    evaluated_at          TIMESTAMPTZ   NOT NULL DEFAULT now(),

    -- created_at is immutable — this row is NEVER updated
    created_at            TIMESTAMPTZ   NOT NULL DEFAULT now(),

    PRIMARY KEY (id)
);

CREATE INDEX IF NOT EXISTS ix_drl_priority_id
    ON decision_ranking_log (priority_id);

CREATE INDEX IF NOT EXISTS ix_drl_entity
    ON decision_ranking_log (entity_type, entity_key);

CREATE INDEX IF NOT EXISTS ix_drl_user_id
    ON decision_ranking_log (user_id);

CREATE INDEX IF NOT EXISTS ix_drl_evaluated_at
    ON decision_ranking_log (evaluated_at);

CREATE INDEX IF NOT EXISTS ix_drl_candidate_type
    ON decision_ranking_log (candidate_type, evaluated_at);
