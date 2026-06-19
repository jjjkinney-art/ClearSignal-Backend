-- Phase 15 · Slice 1 — User Learning Schema
--
-- Idempotent (uses IF NOT EXISTS throughout). Apply AFTER 014_scenario_engine.sql.
--
-- Adds four user-learning tables only:
--   user_signal_event        — append-only behavioral event stream
--   learned_preference       — current-state evidence-backed belief per (user, dim, entity)
--   preference_evidence      — normalized evidence rows backing each preference (insert-only)
--   relevance_adjustment_log — append-only shadow journal of relevance adjustments
--
-- NO existing table is modified. No column added to any source table.
-- No FK constraints into truth tables (soft references via entity_key).
-- All four tables are DERIVED/PERSONALIZATION and read truth layers read-only only.
--
--   db_table_count: 49 → 53 (four new tables).
--
-- Safety invariants (enforced at application layer, not DDL):
--   * User Learning learns RELEVANCE only. It never rewrites truth.
--     NO buy / sell / hold / recommendation / position_size / target_price /
--     trade / execution / forecast_override / similarity_override /
--     scenario_override / decision_override column exists anywhere in this schema.
--   * No user-learning table carries raw prompt text, LLM output, or dossier text.
--   * All six learning_* flags default to false/true (inert), keeping the phase
--     dormant on deploy (SP-7). No surface is changed during the build phase.
--   * user_signal_event and preference_evidence and relevance_adjustment_log are
--     append-only: no UPDATE or DELETE path exists in the application layer.
--   * learned_preference rows may have their status field updated (decay,
--     falsification) — all other fields are only mutated by the inference pass.
--   * Phase 15 never writes to forecast_vector, similarity_edge, scenario_snapshot,
--     decision_priority, ticker_memory, or any upstream source table (SP-7a).
--
-- signal_type valid values (schema v1):
--   watchlist_add | watchlist_remove | search_query | search_click |
--   analysis_open | section_expand | alert_open | alert_act | alert_dismiss |
--   alert_mute | forecast_view | horizon_toggle | scenario_expand |
--   scenario_dismiss | portfolio_view | explicit_pref_set | explicit_pref_unset
--
-- polarity valid values:
--   positive | negative | neutral
--
-- entity_type valid values:
--   company | sector | theme | signal_type | horizon
--
-- dimension valid values (learned_preference):
--   sector_interest | company_interest | theme_interest | preferred_horizon |
--   preferred_signal_type | ignored_signal_type | portfolio_sensitivity
--
-- status valid values (learned_preference):
--   active | unresolved | decayed | falsified | explicit
--
-- prominence_tier valid values (relevance_adjustment_log):
--   pinned | normal | muted   (never "hidden" — SP-7d)
--
-- run_reason valid values (relevance_adjustment_log):
--   shadow | delivery   (shadow until Stage 5 sign-off)


-- ---------------------------------------------------------------------------
-- 50. user_signal_event
-- ---------------------------------------------------------------------------
--
-- Append-only raw behavioral event stream.
-- One row per observed user interaction. Never updated; aged out by retention.
--
-- surface_was_personalized + pre_personalization_rank:
--   Critical anti-feedback-loop fields. The learning pass uses pre_personalization_rank
--   to avoid reinforcing whatever the system already surfaced first (risk R2).
--
-- SAFETY NOTE — columns that MUST NOT EXIST here:
--   buy / sell / recommendation / target_price / position_size / execution /
--   trade / forecast_override / similarity_override / scenario_override / decision_override

CREATE TABLE IF NOT EXISTS user_signal_event (
    id                      VARCHAR(36)     NOT NULL,

    -- user_id: NULL not permitted — anonymous behavior is not learned
    user_id                 VARCHAR(36)     NOT NULL,

    -- signal_type: the behavioral event classification
    signal_type             VARCHAR(40)     NOT NULL DEFAULT '',

    -- polarity: positive | negative | neutral
    polarity                VARCHAR(10)     NOT NULL DEFAULT 'neutral',

    -- entity_type: company | sector | theme | signal_type | horizon
    entity_type             VARCHAR(20)     NOT NULL DEFAULT '',

    -- entity_key: ticker / sector_id / theme_key / signal_type_name / horizon_band
    entity_key              VARCHAR(200)    NOT NULL DEFAULT '',

    -- source_surface: which UI surface emitted the event (feed, alert, search, portfolio)
    source_surface          VARCHAR(60)     NOT NULL DEFAULT '',

    -- surface_was_personalized: whether the surface was already personalized when
    -- this event was captured — essential for unbiased learning (SP-7, risk R2)
    surface_was_personalized BOOLEAN       NOT NULL DEFAULT FALSE,

    -- pre_personalization_rank: item rank BEFORE any personalization (unbiased signal)
    pre_personalization_rank INTEGER        DEFAULT NULL,

    -- interaction_weight: normalized magnitude [0, 1] (e.g. dwell-scaled)
    interaction_weight      FLOAT           NOT NULL DEFAULT 1.0,

    -- occurred_at: when the interaction happened (event time)
    occurred_at             TIMESTAMPTZ     NOT NULL DEFAULT now(),

    -- created_at: when this row was ingested (ingest time) — immutable
    created_at              TIMESTAMPTZ     NOT NULL DEFAULT now(),

    PRIMARY KEY (id)
);

CREATE INDEX IF NOT EXISTS ix_use_user_occurred
    ON user_signal_event (user_id, occurred_at);

CREATE INDEX IF NOT EXISTS ix_use_user_entity
    ON user_signal_event (user_id, entity_type, entity_key);

CREATE INDEX IF NOT EXISTS ix_use_user_signal_type
    ON user_signal_event (user_id, signal_type);

CREATE INDEX IF NOT EXISTS ix_use_polarity
    ON user_signal_event (polarity);


-- ---------------------------------------------------------------------------
-- 51. learned_preference
-- ---------------------------------------------------------------------------
--
-- Current-state, evidence-backed belief. One row per (user_id, dimension, entity_key).
-- Status-mutable: the decay pass may update `status`, `affinity`, `confidence`,
-- `last_reinforced_at`. All other fields mutated only by the inference pass.
--
-- affinity [-1, 1]: positive = interest, negative = aversion/ignore.
-- confidence [0, 1]: evidence quality (consistency + recency + count).
-- signal_strength_label: human-readable confidence band for the explainability gate.
--
-- The four mandatory explainability fields (SP-7g) are:
--   1. belief_basis         — why we believe this (inference rule that fired)
--   2. preference_evidence rows (#52) — the contributing events
--   3. signal_strength_label + confidence — how strong the signal is
--   4. falsifier            — what evidence would overturn this belief
--
-- A preference missing any of these four is rejected at the gate and never reaches
-- status=active (enforced by the application layer).

CREATE TABLE IF NOT EXISTS learned_preference (
    id                  VARCHAR(36)     NOT NULL,

    user_id             VARCHAR(36)     NOT NULL,

    -- dimension: sector_interest | company_interest | theme_interest |
    --   preferred_horizon | preferred_signal_type | ignored_signal_type |
    --   portfolio_sensitivity
    dimension           VARCHAR(30)     NOT NULL DEFAULT '',

    -- entity_key: the specific sector / company / theme / horizon / signal-type
    entity_key          VARCHAR(200)    NOT NULL DEFAULT '',

    -- affinity: signed strength [-1, 1]
    affinity            FLOAT           NOT NULL DEFAULT 0.0,

    -- confidence: evidence quality [0, 1]
    confidence          FLOAT           NOT NULL DEFAULT 0.0,

    -- evidence_count: number of contributing events (denominator for threshold)
    evidence_count      INTEGER         NOT NULL DEFAULT 0,

    -- status: active | unresolved | decayed | falsified | explicit
    status              VARCHAR(15)     NOT NULL DEFAULT 'unresolved',

    -- Explainability field 1: why we believe this
    belief_basis        TEXT            NOT NULL DEFAULT '',

    -- Explainability field 3: signal strength label (consistent with confidence)
    --   strong | moderate | tentative
    signal_strength_label VARCHAR(10)  NOT NULL DEFAULT 'tentative',

    -- Explainability field 4: what evidence would overturn this belief (falsifier)
    falsifier           TEXT            NOT NULL DEFAULT '',

    first_observed_at   TIMESTAMPTZ     NOT NULL DEFAULT now(),
    last_reinforced_at  TIMESTAMPTZ     NOT NULL DEFAULT now(),

    -- preference_schema: bumped when inference model changes (invalidation key)
    preference_schema   INTEGER         NOT NULL DEFAULT 1,

    updated_at          TIMESTAMPTZ     NOT NULL DEFAULT now(),

    PRIMARY KEY (id),
    CONSTRAINT uq_learned_preference_user_dim_entity
        UNIQUE (user_id, dimension, entity_key)
);

CREATE INDEX IF NOT EXISTS ix_lp_user_id
    ON learned_preference (user_id);

CREATE INDEX IF NOT EXISTS ix_lp_user_dimension
    ON learned_preference (user_id, dimension);

CREATE INDEX IF NOT EXISTS ix_lp_user_entity
    ON learned_preference (user_id, entity_key);

CREATE INDEX IF NOT EXISTS ix_lp_status
    ON learned_preference (status);

CREATE INDEX IF NOT EXISTS ix_lp_dimension_entity
    ON learned_preference (dimension, entity_key);

CREATE INDEX IF NOT EXISTS ix_lp_last_reinforced
    ON learned_preference (last_reinforced_at);


-- ---------------------------------------------------------------------------
-- 52. preference_evidence
-- ---------------------------------------------------------------------------
--
-- Explainability field 2 — the normalized provenance of each learned belief.
-- INSERT-ONLY. Every belief must have >= MIN_EVENTS[dimension] resolvable rows.
--
-- preference_id: soft FK to learned_preference (no CASCADE — evidence outlives decay)
-- signal_event_id: soft FK to user_signal_event (no CASCADE — survives retention sweep)
-- contribution: how much this event moved the affinity after decay scaling
-- source: learning source number (1-8 per spec §3)

CREATE TABLE IF NOT EXISTS preference_evidence (
    id                  VARCHAR(36)     NOT NULL,

    -- Soft FK to learned_preference.id — no CASCADE
    preference_id       VARCHAR(36)     NOT NULL,

    -- Soft FK to user_signal_event.id — no CASCADE
    signal_event_id     VARCHAR(36)     NOT NULL,

    -- contribution: decay-scaled impact on the affinity
    contribution        FLOAT           NOT NULL DEFAULT 0.0,

    -- source: mirrors the learning source category (§3)
    source              VARCHAR(30)     NOT NULL DEFAULT '',

    observed_at         TIMESTAMPTZ     NOT NULL DEFAULT now(),

    PRIMARY KEY (id)
);

CREATE INDEX IF NOT EXISTS ix_pe_preference_id
    ON preference_evidence (preference_id);

CREATE INDEX IF NOT EXISTS ix_pe_signal_event_id
    ON preference_evidence (signal_event_id);

CREATE INDEX IF NOT EXISTS ix_pe_observed_at
    ON preference_evidence (observed_at);


-- ---------------------------------------------------------------------------
-- 53. relevance_adjustment_log
-- ---------------------------------------------------------------------------
--
-- The shadow output surface — the append-only journal of what the relevance
-- layer WOULD do. Analogue of scenario_run_log in Phase 14.
-- INSERT-ONLY. run_reason=shadow until Stage 5 sign-off.
--
-- intrinsic_rank: the item's truth-order rank (read-only input from the truth layer)
-- adjusted_rank: the rank personalization would assign
-- prominence_tier: pinned | normal | muted  (NEVER hidden — SP-7d)
-- floor_applied: true when the SP-7d relevance floor clamped this item
--
-- SAFETY: intrinsic_rank and adjusted_rank are both persisted so shadow
-- validation can confirm no safety-critical item was pushed below its floor.
-- The item's underlying score is NOT stored here — Phase 15 never has it to write.

CREATE TABLE IF NOT EXISTS relevance_adjustment_log (
    id                  VARCHAR(36)     NOT NULL,

    user_id             VARCHAR(36)     NOT NULL,

    -- surface: the surface being reordered (feed | alert_digest | watchlist)
    surface             VARCHAR(40)     NOT NULL DEFAULT '',

    -- run_reason: shadow | delivery  (shadow until Stage 5 sign-off)
    run_reason          VARCHAR(15)     NOT NULL DEFAULT 'shadow',

    -- item_ref: the truth item being repositioned (forecast/scenario/decision/alert id)
    item_ref            VARCHAR(200)    NOT NULL DEFAULT '',

    -- intrinsic_rank: truth-order position (read-only input, never modified)
    intrinsic_rank      INTEGER         NOT NULL DEFAULT 0,

    -- adjusted_rank: the rank personalization would assign
    adjusted_rank       INTEGER         NOT NULL DEFAULT 0,

    -- relevance_weight: the applied weight (bounded ± W_MAX, e.g. ±0.5)
    relevance_weight    FLOAT           NOT NULL DEFAULT 0.0,

    -- prominence_tier: pinned | normal | muted  (NEVER hidden — SP-7d)
    prominence_tier     VARCHAR(10)     NOT NULL DEFAULT 'normal',

    -- floor_applied: true when the relevance floor clamped this item (SP-7d)
    floor_applied       BOOLEAN         NOT NULL DEFAULT FALSE,

    -- evaluated_at: when the adjustment was computed — immutable
    evaluated_at        TIMESTAMPTZ     NOT NULL DEFAULT now(),

    -- created_at: ingest time — immutable
    created_at          TIMESTAMPTZ     NOT NULL DEFAULT now(),

    PRIMARY KEY (id)
);

CREATE INDEX IF NOT EXISTS ix_ral_user_id
    ON relevance_adjustment_log (user_id);

CREATE INDEX IF NOT EXISTS ix_ral_user_surface
    ON relevance_adjustment_log (user_id, surface);

CREATE INDEX IF NOT EXISTS ix_ral_run_reason
    ON relevance_adjustment_log (run_reason);

CREATE INDEX IF NOT EXISTS ix_ral_evaluated_at
    ON relevance_adjustment_log (evaluated_at);

CREATE INDEX IF NOT EXISTS ix_ral_item_ref
    ON relevance_adjustment_log (item_ref);
