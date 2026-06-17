-- Phase 11 · Slice 1 — Similarity Engine Schema
--
-- Idempotent (uses IF NOT EXISTS throughout). Apply AFTER 010_subscriptions_billing.sql.
--
-- Adds two derived/cache tables only:
--   similarity_feature_vector  — typed per-(target_type, entity_key) feature cache
--   similarity_edge            — scored, explained resemblance relation (TTL cache)
--
-- NO existing table is modified. No column added to any source table.
-- No FK constraints into source tables (soft references via entity_key / source_versions).
-- Both tables are DERIVED and disposable — they can be dropped and rebuilt from substrate.
--
--   db_table_count: 38 → 40 (two new tables).
--
-- Safety invariants (enforced at application layer, not DDL):
--   * The builder never writes to historical_analogs, company_dossier, dossier_*,
--     cross_exposures, portfolio_*, thesis_versions, or any delivery table.
--   * Edges are a cache — dropping similarity_edge degrades latency, never correctness.
--   * similarity_build_enabled defaults to false; tables are inert until that flag flips.
--   * Similarity never influences forecasting paths during Phase 11.
--
-- target_type valid values:
--   company | thesis | catalyst | failure_mode | regime | portfolio
--
-- score_schema / vector_schema: bumped when the scoring formula or feature
--   taxonomy changes respectively, triggering global invalidation of stale rows.


-- ---------------------------------------------------------------------------
-- 39. similarity_feature_vector
-- ---------------------------------------------------------------------------
--
-- One row per (target_type, entity_key, user_id) combination.
-- entity_key is one of: ticker, portfolio_id, catalyst_id, thesis_version_id.
--
-- categorical: JSON map of discrete features
--   {sector, business_model, valuation_regime, growth_phase, macro_regime,
--    moat_composite, debate_lean, catalyst_direction, ...}
--
-- tag_set: JSON list for Jaccard similarity
--   concern_tags, mechanisms, shared_concerns, moat axes present
--
-- numeric: JSON map of bounded scalars in [0,1]
--   conviction, durability_score, specificity, sequence_stage_norm, ...
--
-- text_anchor: one human-readable sentence naming this entity's setup.
--   Used only for explanation rendering; never scored directly.
--
-- source_versions: JSON map of {table: row_version/version} provenance records.
--   Mismatch between stored source_versions and live values triggers a rebuild.
--
-- vector_schema: bumped when the feature taxonomy changes; old rows are stale.

CREATE TABLE IF NOT EXISTS similarity_feature_vector (
    id              VARCHAR(36)     NOT NULL,

    -- target_type: company | thesis | catalyst | failure_mode | regime | portfolio
    target_type     VARCHAR(20)     NOT NULL,
    -- entity_key: ticker | portfolio_id | catalyst_id | thesis_version_id
    entity_key      VARCHAR(200)    NOT NULL,

    -- Typed feature representations (all three populated where available)
    categorical     TEXT            NOT NULL DEFAULT '{}',
    tag_set         TEXT            NOT NULL DEFAULT '[]',
    numeric         TEXT            NOT NULL DEFAULT '{}',

    -- Human-readable anchor for explanation rendering (never scored)
    text_anchor     TEXT            NOT NULL DEFAULT '',

    -- Provenance: {table: row_version} for staleness detection
    source_versions TEXT            NOT NULL DEFAULT '{}',

    -- Invalidation key — bumped when feature taxonomy changes
    vector_schema   INTEGER         NOT NULL DEFAULT 1,

    -- user_id: identity scoping (Phase 16).
    -- NULL = shared global library (historical_analogs, etc.)
    user_id         VARCHAR(36)     DEFAULT NULL,

    built_at        TIMESTAMPTZ     NOT NULL DEFAULT now(),

    PRIMARY KEY (id),
    CONSTRAINT uq_similarity_feature_vector_type_key_user
        UNIQUE (target_type, entity_key, user_id)
);

CREATE INDEX IF NOT EXISTS ix_sfv_target_type_entity
    ON similarity_feature_vector (target_type, entity_key);

CREATE INDEX IF NOT EXISTS ix_sfv_user_id
    ON similarity_feature_vector (user_id);

CREATE INDEX IF NOT EXISTS ix_sfv_vector_schema
    ON similarity_feature_vector (vector_schema);


-- ---------------------------------------------------------------------------
-- 40. similarity_edge
-- ---------------------------------------------------------------------------
--
-- One row per (target_type, query_key, candidate_key, user_id) scored relation.
-- Materialised for hot paths; expires by TTL.
--
-- contributions: JSON list of {feature, shared_value, weight, partial_score}.
--   MUST be non-empty for every above-floor edge — the orphan-score invariant.
--
-- headline: rendered "why similar" one-liner built from top contributions.
--
-- disanalogy: the strongest dissimilarity — the honesty tax.
--   Every above-floor edge must name how the two entities differ.
--
-- floor_passed: False means this is a weak/none result (stored for diagnostics,
--   never delivered as a strong resemblance).
--
-- score_schema: bumped when the scoring formula or weight profile changes;
--   edges with stale score_schema must be recomputed before serving.

CREATE TABLE IF NOT EXISTS similarity_edge (
    id              VARCHAR(36)     NOT NULL,

    -- target_type: company | thesis | catalyst | failure_mode | regime | portfolio
    target_type     VARCHAR(20)     NOT NULL,
    -- query_key / candidate_key: entity_key values (ticker etc.)
    query_key       VARCHAR(200)    NOT NULL,
    candidate_key   VARCHAR(200)    NOT NULL,

    -- Composite score [0, 1]
    score           FLOAT           NOT NULL DEFAULT 0.0,
    -- Rank within this query's result set at materialisation time
    rank            INTEGER         NOT NULL DEFAULT 0,

    -- Explanation (MUST be non-empty for floor_passed=true edges)
    contributions   TEXT            NOT NULL DEFAULT '[]',
    -- Rendered one-sentence "why similar"
    headline        TEXT            NOT NULL DEFAULT '',
    -- Strongest dissimilarity — the honesty tax
    disanalogy      TEXT            NOT NULL DEFAULT '',

    -- Whether this edge passed the relevance floor
    floor_passed    BOOLEAN         NOT NULL DEFAULT FALSE,

    -- Invalidation key — bumped when scoring formula or weight profile changes
    score_schema    INTEGER         NOT NULL DEFAULT 1,

    -- user_id: identity scoping (Phase 16)
    user_id         VARCHAR(36)     DEFAULT NULL,

    -- TTL materialisation columns
    built_at        TIMESTAMPTZ     NOT NULL DEFAULT now(),
    expires_at      TIMESTAMPTZ     NOT NULL DEFAULT (now() + INTERVAL '24 hours'),

    PRIMARY KEY (id),
    CONSTRAINT uq_similarity_edge_type_query_candidate_user
        UNIQUE (target_type, query_key, candidate_key, user_id)
);

CREATE INDEX IF NOT EXISTS ix_se_query
    ON similarity_edge (target_type, query_key, user_id);

CREATE INDEX IF NOT EXISTS ix_se_candidate
    ON similarity_edge (target_type, candidate_key, user_id);

CREATE INDEX IF NOT EXISTS ix_se_expires_at
    ON similarity_edge (expires_at);

CREATE INDEX IF NOT EXISTS ix_se_score_schema
    ON similarity_edge (score_schema);

CREATE INDEX IF NOT EXISTS ix_se_floor_passed
    ON similarity_edge (floor_passed);
