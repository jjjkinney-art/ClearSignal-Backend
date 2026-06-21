-- Phase 19 · Slice 1 — Visual Intelligence Schema
--
-- Idempotent (uses IF NOT EXISTS throughout). Apply AFTER 018_personal_experience.sql.
--
-- Adds three visual-intelligence tables only:
--   visual_spec_cache          — cached visual specifications (upsert on unique key)
--   visual_experience_event    — append-only visual generation log
--   ai_visual_generation_log   — append-only AI generation audit log
--
-- NO existing table is modified. No column added to any source table.
-- No FK constraints into truth tables (soft references via entity_key).
-- All three tables are DERIVED/VISUALIZATION and read truth layers read-only only.
--
--   db_table_count: 56 → 59 (three new tables).
--
-- Safety invariants (enforced at application layer, not DDL):
--   * Phase 19 visualizes intelligence — it never creates it.
--     NO buy / sell / recommendation / position_size / target_price /
--     trade / execution / forecast_override / similarity_override /
--     scenario_override / decision_override column exists anywhere in this schema.
--   * No visual table carries raw prompt text or LLM output.
--     ai_visual_generation_log stores prompt_hash (SHA-256) only.
--   * All five visual_* flags default to false/true (inert), keeping the phase
--     dormant on deploy (SP-19). No surface is changed during the build phase.
--   * visual_experience_event and ai_visual_generation_log are append-only:
--     no UPDATE or DELETE path exists in the application layer.
--   * visual_spec_cache rows may be upserted (spec_json updated on cache refresh).
--   * Phase 19 never writes to forecast_vector, similarity_edge, scenario_snapshot,
--     decision_priority, ticker_memory, learned_preference, user_signal_event,
--     personal_experience_cursor, personal_experience_event, or any upstream
--     source table (SP-19c).
--
-- rendering_tier valid values (visual_spec_cache, visual_experience_event):
--   json | svg | ai_image
--
-- run_reason valid values (all three tables):
--   shadow | delivery   (shadow until Stage 5 sign-off)


-- ---------------------------------------------------------------------------
-- 57. visual_spec_cache
-- ---------------------------------------------------------------------------
--
-- Caches rendered visual specifications to avoid redundant computation.
-- Upsert keyed on (user_id, visual_type, entity_key, data_hash).
--
-- SAFETY NOTE — columns that MUST NOT EXIST here:
--   buy / sell / recommendation / target_price / position_size / execution /
--   trade / forecast_override / similarity_override / scenario_override /
--   decision_override / prompt_text / raw_output

CREATE TABLE IF NOT EXISTS visual_spec_cache (
    id              VARCHAR(36)     NOT NULL,

    user_id         VARCHAR(36)     NOT NULL,

    visual_type     VARCHAR(50)     NOT NULL DEFAULT '',

    entity_key      VARCHAR(64)     NOT NULL DEFAULT '',

    data_hash       VARCHAR(64)     NOT NULL DEFAULT '',

    spec_json       TEXT            NOT NULL DEFAULT '',

    rendering_tier  VARCHAR(10)     NOT NULL DEFAULT 'json',

    explanation_valid BOOLEAN       NOT NULL DEFAULT FALSE,

    run_reason      VARCHAR(15)     NOT NULL DEFAULT 'shadow',

    generated_at    TIMESTAMPTZ     NOT NULL DEFAULT now(),

    expires_at      TIMESTAMPTZ,

    created_at      TIMESTAMPTZ     NOT NULL DEFAULT now(),

    PRIMARY KEY (id),

    CONSTRAINT uq_vsc_user_type_key_hash
        UNIQUE (user_id, visual_type, entity_key, data_hash)
);

CREATE INDEX IF NOT EXISTS ix_vsc_user_id
    ON visual_spec_cache (user_id);

CREATE INDEX IF NOT EXISTS ix_vsc_user_type
    ON visual_spec_cache (user_id, visual_type);

CREATE INDEX IF NOT EXISTS ix_vsc_entity_key
    ON visual_spec_cache (entity_key);

CREATE INDEX IF NOT EXISTS ix_vsc_run_reason
    ON visual_spec_cache (run_reason);


-- ---------------------------------------------------------------------------
-- 58. visual_experience_event
-- ---------------------------------------------------------------------------
--
-- Append-only log of visual generation events.
-- INSERT-ONLY. No UPDATE. No DELETE.
--
-- SAFETY NOTE — columns that MUST NOT EXIST here:
--   buy / sell / recommendation / target_price / position_size / execution /
--   trade / forecast_override / similarity_override / scenario_override /
--   decision_override / prompt_text / raw_output

CREATE TABLE IF NOT EXISTS visual_experience_event (
    id              VARCHAR(36)     NOT NULL,

    user_id         VARCHAR(36)     NOT NULL,

    visual_type     VARCHAR(50)     NOT NULL DEFAULT '',

    entity_key      VARCHAR(64)     NOT NULL DEFAULT '',

    rendering_tier  VARCHAR(10)     NOT NULL DEFAULT 'json',

    explanation_valid BOOLEAN       NOT NULL DEFAULT FALSE,

    generation_ms   INTEGER         NOT NULL DEFAULT 0,

    cache_hit       BOOLEAN         NOT NULL DEFAULT FALSE,

    blocked_reason  VARCHAR(100)    NOT NULL DEFAULT '',

    run_reason      VARCHAR(15)     NOT NULL DEFAULT 'shadow',

    surfaced_at     TIMESTAMPTZ     NOT NULL DEFAULT now(),

    created_at      TIMESTAMPTZ     NOT NULL DEFAULT now(),

    PRIMARY KEY (id)
);

CREATE INDEX IF NOT EXISTS ix_vee_user_id
    ON visual_experience_event (user_id);

CREATE INDEX IF NOT EXISTS ix_vee_visual_type
    ON visual_experience_event (visual_type);

CREATE INDEX IF NOT EXISTS ix_vee_run_reason
    ON visual_experience_event (run_reason);

CREATE INDEX IF NOT EXISTS ix_vee_surfaced_at
    ON visual_experience_event (surfaced_at);


-- ---------------------------------------------------------------------------
-- 59. ai_visual_generation_log
-- ---------------------------------------------------------------------------
--
-- Append-only audit log for AI-generated visuals.
-- INSERT-ONLY. No UPDATE. No DELETE.
-- Stores prompt_hash (SHA-256) only — NO raw prompt text or model output.
--
-- SAFETY NOTE — columns that MUST NOT EXIST here:
--   prompt_text / raw_prompt / model_output / raw_output /
--   buy / sell / recommendation / target_price / position_size / execution /
--   trade / forecast_override / similarity_override / scenario_override /
--   decision_override

CREATE TABLE IF NOT EXISTS ai_visual_generation_log (
    id                  VARCHAR(36)     NOT NULL,

    user_id             VARCHAR(36)     NOT NULL,

    visual_type         VARCHAR(50)     NOT NULL DEFAULT '',

    entity_key          VARCHAR(64)     NOT NULL DEFAULT '',

    prompt_hash         VARCHAR(64)     NOT NULL DEFAULT '',

    generation_model    VARCHAR(50)     NOT NULL DEFAULT '',

    generation_ms       INTEGER         NOT NULL DEFAULT 0,

    validation_passed   BOOLEAN         NOT NULL DEFAULT FALSE,

    validation_reason   VARCHAR(100)    NOT NULL DEFAULT '',

    banned_phrases_found TEXT           NOT NULL DEFAULT '',

    run_reason          VARCHAR(15)     NOT NULL DEFAULT 'shadow',

    created_at          TIMESTAMPTZ     NOT NULL DEFAULT now(),

    PRIMARY KEY (id)
);

CREATE INDEX IF NOT EXISTS ix_avgl_user_id
    ON ai_visual_generation_log (user_id);

CREATE INDEX IF NOT EXISTS ix_avgl_visual_type
    ON ai_visual_generation_log (visual_type);

CREATE INDEX IF NOT EXISTS ix_avgl_run_reason
    ON ai_visual_generation_log (run_reason);
