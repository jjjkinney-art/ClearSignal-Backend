-- Phase 14 · Slice 1 — Scenario Engine Schema
--
-- Idempotent (uses IF NOT EXISTS throughout). Apply AFTER 013_decision_intelligence.sql.
--
-- Adds three scenario engine tables only:
--   scenario_snapshot   — one row per evaluated conditional scenario / user scope
--   scenario_evidence   — normalised evidence rows backing each scenario_snapshot
--   scenario_run_log    — immutable run / shadow / calibration-outcome log
--
-- NO existing table is modified. No column added to any source table.
-- No FK constraints into source tables (soft references via entity_key / source_ref /
-- source_versions). All three tables are DERIVED/ANALYTICS and disposable — they can
-- be dropped and rebuilt from the intelligence substrate.
--
--   db_table_count: 46 → 49 (three new tables).
--
-- Safety invariants (enforced at application layer, not DDL):
--   * The Scenario Engine answers "What happens if X changes?" — it produces
--     conditional analyses, not predictions and not recommendations. NO buy / sell /
--     hold / recommendation / position_size / target_price / trade / execution column
--     exists anywhere in this schema.
--   * No scenario table ever carries raw dossier text, prompt text, or LLM output.
--   * scenario_build_enabled and scenario_scoring_enabled default to false, and
--     scenario_delivery_enabled defaults to false (scenario_shadow true). Tables are
--     inert until those flags are flipped; no surface is changed during the build phase.
--   * The Scenario Engine never writes to any source table in this or any later slice —
--     it is a pure sink (SP-6). Nothing in Phases 9G–13 imports Phase 14.
--   * scenario_run_log is append-only: no UPDATE or DELETE path exists in the
--     application layer (enforced by AST inspection in the validation script).
--
-- scenario_type valid values (schema v1):
--   macro | company | sector | catalyst | failure_mode | portfolio
--
-- entity_type valid values:
--   company | sector | macro | portfolio
--
-- scenario_impact valid values (qualitative directional band):
--   significant_positive | moderate_positive | neutral | moderate_negative |
--   significant_negative | ambiguous
--
-- plausibility_band valid values (conditional framing — NOT a probability):
--   remote | plausible | likely_conditional
--
-- scenario_schema: bumped when the evaluation model / weights / thresholds change;
--   stale snapshots must be recomputed before serving.


-- ---------------------------------------------------------------------------
-- 47. scenario_snapshot
-- ---------------------------------------------------------------------------
--
-- One row per (scenario_type, entity_type, entity_key, scenario_key, user_id).
-- Stores the transmission path, impact/plausibility bands, the five mandatory
-- explanation fields, and the affected-entity/forecast/decision sets.
--
-- SAFETY NOTE — columns that MUST NOT EXIST here:
--   buy / sell / hold / recommendation / position_size / target_price /
--   trade / execution / predicted_return / price_target
--
-- transmission_path: JSON ordered list of cause→effect steps.
--   Must be non-empty before storage (gate enforced in Slice 14.4).
--
-- invalidators: JSON list of falsifiable conditions that would void the scenario.
--   Must be non-empty before storage.
--
-- user_id NULL = global / intrinsic tier; non-NULL = portfolio-adjusted user tier.

CREATE TABLE IF NOT EXISTS scenario_snapshot (
    id                  VARCHAR(36)     NOT NULL,

    -- scenario_type: macro | company | sector | catalyst | failure_mode | portfolio
    scenario_type       VARCHAR(30)     NOT NULL,

    -- entity_type: company | sector | macro | portfolio
    entity_type         VARCHAR(20)     NOT NULL,
    -- entity_key: ticker | sector_id | macro_key | portfolio_id
    entity_key          VARCHAR(200)    NOT NULL,

    -- scenario_key: stable identity of the condition ("the if")
    scenario_key        VARCHAR(200)    NOT NULL DEFAULT '',

    -- condition: human-readable description of the triggering change
    condition           TEXT            NOT NULL DEFAULT '',

    -- transmission_path: ordered JSON list of cause→effect steps — MUST be non-empty
    transmission_path   TEXT            NOT NULL DEFAULT '[]',

    -- scenario_impact: qualitative directional band — NOT a price or return target
    --   significant_positive | moderate_positive | neutral |
    --   moderate_negative | significant_negative | ambiguous
    scenario_impact     VARCHAR(30)     NOT NULL DEFAULT 'ambiguous',

    -- plausibility_band: conditional framing — NOT a probability of occurrence
    --   remote | plausible | likely_conditional
    plausibility_band   VARCHAR(30)     NOT NULL DEFAULT 'plausible',

    -- Confidence/uncertainty carried from upstream signals [0,1] — NOT Phase 14's own
    confidence_score    FLOAT           NOT NULL DEFAULT 0.0,
    uncertainty_score   FLOAT           NOT NULL DEFAULT 0.0,

    -- Affected upstream artefacts (JSON lists of soft references)
    affected_entities   TEXT            NOT NULL DEFAULT '[]',
    affected_forecasts  TEXT            NOT NULL DEFAULT '[]',
    affected_decisions  TEXT            NOT NULL DEFAULT '[]',

    -- The five mandatory explanation fields (MUST be non-empty before storage)
    -- 1. what_changed: the triggering condition
    what_changed        TEXT            NOT NULL DEFAULT '',
    -- 2. why_it_matters: the stakes
    why_it_matters      TEXT            NOT NULL DEFAULT '',
    -- (3. transmission_path — stored above)
    -- 4. evidence_summary: condensed from scenario_evidence rows
    evidence_summary    TEXT            NOT NULL DEFAULT '[]',
    -- 5. invalidators: falsifiable conditions that void this scenario — MUST be non-empty
    invalidators        TEXT            NOT NULL DEFAULT '[]',

    -- Provenance: {table: row_version} for staleness detection
    source_versions     TEXT            NOT NULL DEFAULT '{}',

    -- Invalidation key — bumped when the evaluation model / weights change
    scenario_schema     INTEGER         NOT NULL DEFAULT 1,

    -- user_id: identity scoping. NULL = global / intrinsic tier.
    user_id             VARCHAR(36)     DEFAULT NULL,

    -- TTL materialisation
    built_at            TIMESTAMPTZ     NOT NULL DEFAULT now(),
    expires_at          TIMESTAMPTZ     NOT NULL DEFAULT (now() + INTERVAL '72 hours'),

    PRIMARY KEY (id),
    CONSTRAINT uq_scenario_snapshot_type_entity_key_user
        UNIQUE (scenario_type, entity_type, entity_key, scenario_key, user_id)
);

CREATE INDEX IF NOT EXISTS ix_ss_entity
    ON scenario_snapshot (entity_type, entity_key);

CREATE INDEX IF NOT EXISTS ix_ss_scenario_type
    ON scenario_snapshot (scenario_type);

CREATE INDEX IF NOT EXISTS ix_ss_plausibility
    ON scenario_snapshot (plausibility_band);

CREATE INDEX IF NOT EXISTS ix_ss_user_id
    ON scenario_snapshot (user_id);

CREATE INDEX IF NOT EXISTS ix_ss_expires_at
    ON scenario_snapshot (expires_at);

CREATE INDEX IF NOT EXISTS ix_ss_scenario_schema
    ON scenario_snapshot (scenario_schema);

CREATE INDEX IF NOT EXISTS ix_ss_scenario_key
    ON scenario_snapshot (scenario_key);


-- ---------------------------------------------------------------------------
-- 48. scenario_evidence
-- ---------------------------------------------------------------------------
--
-- One row per contributing upstream signal backing a scenario_snapshot.
-- Normalised out of scenario_snapshot so evidence items are queryable
-- independently for explainability and audit.
--
-- source_phase valid values:
--   memory | similarity | forecast | decision | portfolio |
--   cross_exposure | dossier | watchlist
--
-- captured_value: the cited upstream value (read-only snapshot at build time).

CREATE TABLE IF NOT EXISTS scenario_evidence (
    id              VARCHAR(36)     NOT NULL,

    -- Soft FK to scenario_snapshot.id — no CASCADE
    scenario_id     VARCHAR(36)     NOT NULL,

    -- source_phase: which upstream phase/substrate this evidence comes from
    source_phase    VARCHAR(30)     NOT NULL DEFAULT '',

    -- source_ref: primary key or stable identifier of the upstream artefact
    source_ref      VARCHAR(200)    NOT NULL DEFAULT '',

    -- captured_value: the cited upstream value at build time (read-only copy)
    captured_value  TEXT            NOT NULL DEFAULT '{}',

    -- Denormalised for query convenience
    entity_type     VARCHAR(20)     NOT NULL DEFAULT '',
    entity_key      VARCHAR(200)    NOT NULL DEFAULT '',

    -- user_id: identity scoping. NULL = global.
    user_id         VARCHAR(36)     DEFAULT NULL,

    captured_at     TIMESTAMPTZ     NOT NULL DEFAULT now(),

    PRIMARY KEY (id)
);

CREATE INDEX IF NOT EXISTS ix_se_scenario_id
    ON scenario_evidence (scenario_id);

CREATE INDEX IF NOT EXISTS ix_se_source
    ON scenario_evidence (source_phase, source_ref);

CREATE INDEX IF NOT EXISTS ix_se_entity
    ON scenario_evidence (entity_type, entity_key);

CREATE INDEX IF NOT EXISTS ix_se_user_id
    ON scenario_evidence (user_id);


-- ---------------------------------------------------------------------------
-- 49. scenario_run_log
-- ---------------------------------------------------------------------------
--
-- Immutable run / shadow / calibration-outcome log.
-- This table has NO UPDATE or DELETE path in any service or repository.
-- Each run, shadow journal, or calibration outcome creates a NEW row.
-- Modelled on decision_ranking_log and forecast_calibration_log: append-only,
-- immutable, permanent.
--
-- run_reason valid values:
--   assembly | shadow | calibration_outcome
--
-- snapshot_reason: transition/journal classification (free text, e.g.
--   "first_surface", "condition_strengthened", "condition_weakened",
--   "condition_resolved", "condition_invalidated").
--
-- realized_state: materialized | invalidated | unresolved
--   Filled on calibration_outcome rows only. Never updated on an existing row;
--   a new outcome row is appended instead.

CREATE TABLE IF NOT EXISTS scenario_run_log (
    id              VARCHAR(36)     NOT NULL,

    -- Soft FK to scenario_snapshot.id — nullable for run-level rows not tied to
    -- a specific snapshot (e.g. a full-assembly run log row)
    scenario_id     VARCHAR(36)     DEFAULT NULL,

    -- Denormalised from the snapshot row at log time (survives snapshot expiry)
    scenario_type   VARCHAR(30)     NOT NULL DEFAULT '',
    entity_type     VARCHAR(20)     NOT NULL DEFAULT '',
    entity_key      VARCHAR(200)    NOT NULL DEFAULT '',

    -- user_id: identity scoping. NULL = global.
    user_id         VARCHAR(36)     DEFAULT NULL,

    -- run_reason: assembly | shadow | calibration_outcome
    run_reason      VARCHAR(30)     NOT NULL DEFAULT 'assembly',

    -- snapshot_reason: transition/journal classification
    snapshot_reason VARCHAR(60)     NOT NULL DEFAULT '',

    -- realized_state: materialized | invalidated | unresolved (calibration only)
    realized_state  VARCHAR(20)     DEFAULT NULL,

    -- Ordinal surface position at shadow-journal time
    rank_position   INTEGER         DEFAULT NULL,

    -- When this run / outcome was recorded — immutable
    evaluated_at    TIMESTAMPTZ     NOT NULL DEFAULT now(),

    -- created_at is immutable — this row is NEVER updated
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT now(),

    PRIMARY KEY (id)
);

CREATE INDEX IF NOT EXISTS ix_srl_scenario_id
    ON scenario_run_log (scenario_id);

CREATE INDEX IF NOT EXISTS ix_srl_entity
    ON scenario_run_log (entity_type, entity_key);

CREATE INDEX IF NOT EXISTS ix_srl_user_id
    ON scenario_run_log (user_id);

CREATE INDEX IF NOT EXISTS ix_srl_evaluated_at
    ON scenario_run_log (evaluated_at);

CREATE INDEX IF NOT EXISTS ix_srl_scenario_type
    ON scenario_run_log (scenario_type, evaluated_at);

CREATE INDEX IF NOT EXISTS ix_srl_run_reason
    ON scenario_run_log (run_reason);
