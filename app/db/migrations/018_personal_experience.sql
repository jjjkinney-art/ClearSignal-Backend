-- Phase 18 · Slice 1 — Personal Experience Schema
--
-- Idempotent (uses IF NOT EXISTS throughout). Apply AFTER 015_user_learning.sql.
--
-- Adds three personal-experience tables only:
--   personal_experience_cursor   — user view state per entity (upsert on unique key)
--   personal_experience_event    — append-only surfacing log (what was shown and why)
--   personal_brief_snapshot      — one brief per user per day (upsert on unique key)
--
-- NO existing table is modified. No column added to any source table.
-- No FK constraints into truth tables (soft references via entity_key).
-- All three tables are DERIVED/PERSONALIZATION and read truth layers read-only only.
--
--   db_table_count: 53 → 56 (three new tables).
--
-- Safety invariants (enforced at application layer, not DDL):
--   * Phase 18 orchestrates intelligence — it never creates it.
--     NO buy / sell / hold / recommendation / position_size / target_price /
--     trade / execution / forecast_override / similarity_override /
--     scenario_override / decision_override column exists anywhere in this schema.
--   * No personal-experience table carries raw prompt text, LLM output, or dossier text.
--   * All six experience_* flags default to false/true (inert), keeping the phase
--     dormant on deploy (SP-18). No surface is changed during the build phase.
--   * personal_experience_event is append-only: no UPDATE or DELETE path exists
--     in the application layer.
--   * personal_experience_cursor rows may be upserted (last_seen_at, view_count,
--     last_state_hash updated on revisit).
--   * personal_brief_snapshot rows are upserted keyed on (user_id, brief_date).
--   * Phase 18 never writes to forecast_vector, similarity_edge, scenario_snapshot,
--     decision_priority, ticker_memory, learned_preference, user_signal_event, or
--     any upstream source table (SP-18c).
--
-- entity_type valid values (personal_experience_cursor):
--   ticker | scenario | forecast | thesis | decision | portfolio
--
-- surface valid values (personal_experience_event):
--   home | brief | attention_queue
--
-- run_reason valid values (personal_experience_event, personal_brief_snapshot):
--   shadow | delivery   (shadow until Stage 5 sign-off)


-- ---------------------------------------------------------------------------
-- 54. personal_experience_cursor
-- ---------------------------------------------------------------------------
--
-- Tracks each user's last-seen state per entity.
-- Upsert keyed on (user_id, entity_type, entity_key).
-- Enables novelty scoring (how new is this to the user?) and revisit scoring
-- (how much has this changed since the user last looked?).
--
-- SAFETY NOTE — columns that MUST NOT EXIST here:
--   buy / sell / recommendation / target_price / position_size / execution /
--   trade / forecast_override / similarity_override / scenario_override / decision_override

CREATE TABLE IF NOT EXISTS personal_experience_cursor (
    id              VARCHAR(36)     NOT NULL,

    -- user_id: NULL not permitted — anonymous users have no experience state
    user_id         VARCHAR(36)     NOT NULL,

    -- entity_type: ticker | scenario | forecast | thesis | decision | portfolio
    entity_type     VARCHAR(30)     NOT NULL DEFAULT '',

    -- entity_key: ticker symbol, scenario ID, forecast ID, etc.
    entity_key      VARCHAR(64)     NOT NULL DEFAULT '',

    -- last_seen_at: when the user last viewed this entity
    last_seen_at    TIMESTAMPTZ     NOT NULL DEFAULT now(),

    -- last_state_hash: hash of the entity state at last view (for drift detection)
    last_state_hash VARCHAR(64)     NOT NULL DEFAULT '',

    -- view_count: lifetime view count for this entity by this user
    view_count      INTEGER         NOT NULL DEFAULT 0,

    created_at      TIMESTAMPTZ     NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ     NOT NULL DEFAULT now(),

    PRIMARY KEY (id),
    CONSTRAINT uq_pec_user_entity
        UNIQUE (user_id, entity_type, entity_key)
);

CREATE INDEX IF NOT EXISTS ix_pec_user_id
    ON personal_experience_cursor (user_id);

CREATE INDEX IF NOT EXISTS ix_pec_user_entity_type
    ON personal_experience_cursor (user_id, entity_type);

CREATE INDEX IF NOT EXISTS ix_pec_last_seen_at
    ON personal_experience_cursor (last_seen_at);


-- ---------------------------------------------------------------------------
-- 55. personal_experience_event
-- ---------------------------------------------------------------------------
--
-- Append-only log of what was surfaced and why. Enables calibration and audit.
-- INSERT-ONLY. run_reason=shadow until Stage 5 sign-off.
--
-- All 7 scoring dimensions are recorded so shadow validation can compare
-- the would-be experience against the current (unpersonalized) product.
--
-- explanation_valid: False when the item failed the explainability gate
-- (blocked from surfacing but still logged for calibration).
--
-- SAFETY NOTE — columns that MUST NOT EXIST here:
--   buy / sell / recommendation / target_price / position_size / execution /
--   trade / forecast_override / similarity_override / scenario_override / decision_override

CREATE TABLE IF NOT EXISTS personal_experience_event (
    id                  VARCHAR(36)     NOT NULL,

    -- user_id: NULL not permitted
    user_id             VARCHAR(36)     NOT NULL,

    -- surface: home | brief | attention_queue
    surface             VARCHAR(30)     NOT NULL DEFAULT '',

    -- item_ref: entity reference surfaced
    item_ref            VARCHAR(128)    NOT NULL DEFAULT '',

    -- entity_type: type of entity
    entity_type         VARCHAR(30)     NOT NULL DEFAULT '',

    -- entity_key: entity key
    entity_key          VARCHAR(64)     NOT NULL DEFAULT '',

    -- experience_score: composite score at time of surfacing
    experience_score    FLOAT           NOT NULL DEFAULT 0.0,

    -- 7 scoring dimensions
    attention_priority  FLOAT           NOT NULL DEFAULT 0.0,
    personal_relevance  FLOAT           NOT NULL DEFAULT 0.0,
    recency_score       FLOAT           NOT NULL DEFAULT 0.0,
    novelty_score       FLOAT           NOT NULL DEFAULT 0.0,
    revisit_score       FLOAT           NOT NULL DEFAULT 0.0,
    memory_relevance    FLOAT           NOT NULL DEFAULT 0.0,
    portfolio_relevance FLOAT           NOT NULL DEFAULT 0.0,

    -- explanation_text: "Why am I seeing this?" explanation (templated, not LLM prose)
    explanation_text    TEXT            NOT NULL DEFAULT '',

    -- explanation_valid: True if passed explainability gate
    explanation_valid   BOOLEAN         NOT NULL DEFAULT FALSE,

    -- run_reason: shadow | delivery  (shadow until Stage 5 sign-off)
    run_reason          VARCHAR(15)     NOT NULL DEFAULT 'shadow',

    -- surfaced_at: when the item was surfaced
    surfaced_at         TIMESTAMPTZ     NOT NULL DEFAULT now(),

    -- created_at: ingest time — immutable
    created_at          TIMESTAMPTZ     NOT NULL DEFAULT now(),

    PRIMARY KEY (id)
);

CREATE INDEX IF NOT EXISTS ix_pee_user_id
    ON personal_experience_event (user_id);

CREATE INDEX IF NOT EXISTS ix_pee_user_surface
    ON personal_experience_event (user_id, surface);

CREATE INDEX IF NOT EXISTS ix_pee_run_reason
    ON personal_experience_event (run_reason);

CREATE INDEX IF NOT EXISTS ix_pee_surfaced_at
    ON personal_experience_event (surfaced_at);

CREATE INDEX IF NOT EXISTS ix_pee_item_ref
    ON personal_experience_event (item_ref);


-- ---------------------------------------------------------------------------
-- 56. personal_brief_snapshot
-- ---------------------------------------------------------------------------
--
-- Stores metadata about each daily brief for retrieval and audit.
-- One brief per user per day (upsert keyed on user_id, brief_date).
-- run_reason=shadow until Stage 5 sign-off.
--
-- SAFETY NOTE — columns that MUST NOT EXIST here:
--   buy / sell / recommendation / target_price / position_size / execution /
--   trade / forecast_override / similarity_override / scenario_override / decision_override

CREATE TABLE IF NOT EXISTS personal_brief_snapshot (
    id                  VARCHAR(36)     NOT NULL,

    -- user_id: NULL not permitted
    user_id             VARCHAR(36)     NOT NULL,

    -- brief_date: the date this brief covers
    brief_date          DATE            NOT NULL,

    -- brief_schema: schema version (starts at 1)
    brief_schema        INTEGER         NOT NULL DEFAULT 1,

    -- items_surfaced: number of items included in the brief
    items_surfaced      INTEGER         NOT NULL DEFAULT 0,

    -- items_blocked: number of items that failed the explainability gate
    items_blocked       INTEGER         NOT NULL DEFAULT 0,

    -- top_attention_item: highest-priority item reference
    top_attention_item  VARCHAR(128)    NOT NULL DEFAULT '',

    -- run_reason: shadow | delivery  (shadow until Stage 5 sign-off)
    run_reason          VARCHAR(15)     NOT NULL DEFAULT 'shadow',

    -- generated_at: when the brief was generated
    generated_at        TIMESTAMPTZ     NOT NULL DEFAULT now(),

    -- created_at: ingest time
    created_at          TIMESTAMPTZ     NOT NULL DEFAULT now(),

    PRIMARY KEY (id),
    CONSTRAINT uq_pbs_user_brief_date
        UNIQUE (user_id, brief_date)
);

CREATE INDEX IF NOT EXISTS ix_pbs_user_id
    ON personal_brief_snapshot (user_id);

CREATE INDEX IF NOT EXISTS ix_pbs_user_brief_date
    ON personal_brief_snapshot (user_id, brief_date);

CREATE INDEX IF NOT EXISTS ix_pbs_run_reason
    ON personal_brief_snapshot (run_reason);
