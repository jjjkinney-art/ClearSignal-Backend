-- Phase 9A — Initial schema migration
-- PostgreSQL DDL for all 9 persistence tables.
--
-- This migration is idempotent (uses IF NOT EXISTS throughout).
-- Apply once against a fresh Render PostgreSQL instance or run
-- after setting DATABASE_URL in the Render environment.
--
-- For local dev with SQLite, tables are created automatically by
-- SQLAlchemy's Base.metadata.create_all() — you do not need this file.
--
-- Application order: run 001_initial.sql first, then all subsequent
-- migrations in numeric order.

-- ---------------------------------------------------------------------------
-- 1. thesis_versions
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS thesis_versions (
    id                  VARCHAR(36)     PRIMARY KEY,
    ticker              VARCHAR(20)     NOT NULL,
    company_name        VARCHAR(200)    NOT NULL DEFAULT '',
    session_id          VARCHAR(200)    NOT NULL DEFAULT '',
    question            TEXT            NOT NULL DEFAULT '',

    -- Core thesis scalars
    directional_stance  VARCHAR(50)     NOT NULL DEFAULT '',
    confidence_score    DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    bull_thesis         TEXT            NOT NULL DEFAULT '',
    bear_thesis         TEXT            NOT NULL DEFAULT '',
    verdict_rationale   TEXT            NOT NULL DEFAULT '',
    direct_answer       TEXT            NOT NULL DEFAULT '',
    why_not             TEXT            NOT NULL DEFAULT '',
    conclusion          TEXT            NOT NULL DEFAULT '',

    -- Structured JSON blobs (stored as JSONB for indexing on PostgreSQL)
    key_drivers         JSONB           NOT NULL DEFAULT '[]',
    key_risks           JSONB           NOT NULL DEFAULT '[]',
    macro_sensitivity   JSONB           NOT NULL DEFAULT '{}',
    threshold_zones     JSONB           NOT NULL DEFAULT '{}',

    created_at          TIMESTAMPTZ     NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_thesis_versions_ticker
    ON thesis_versions (ticker);
CREATE INDEX IF NOT EXISTS ix_thesis_versions_session_id
    ON thesis_versions (session_id);
CREATE INDEX IF NOT EXISTS ix_thesis_versions_ticker_created
    ON thesis_versions (ticker, created_at DESC);


-- ---------------------------------------------------------------------------
-- 2. thesis_deltas
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS thesis_deltas (
    id                      VARCHAR(36)     PRIMARY KEY,
    ticker                  VARCHAR(20)     NOT NULL,
    from_version_id         VARCHAR(36)     NOT NULL
        REFERENCES thesis_versions(id) ON DELETE CASCADE,
    to_version_id           VARCHAR(36)     NOT NULL
        REFERENCES thesis_versions(id) ON DELETE CASCADE,

    stance_changed          BOOLEAN         NOT NULL DEFAULT FALSE,
    conviction_delta        DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    bull_thesis_similarity  DOUBLE PRECISION NOT NULL DEFAULT 1.0,
    bear_thesis_similarity  DOUBLE PRECISION NOT NULL DEFAULT 1.0,
    magnitude               VARCHAR(20)     NOT NULL DEFAULT 'minor',
    changed_fields          JSONB           NOT NULL DEFAULT '[]',

    created_at              TIMESTAMPTZ     NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_thesis_deltas_ticker
    ON thesis_deltas (ticker);
CREATE INDEX IF NOT EXISTS ix_thesis_deltas_ticker_created
    ON thesis_deltas (ticker, created_at DESC);


-- ---------------------------------------------------------------------------
-- 3. ticker_memory
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ticker_memory (
    id                  VARCHAR(36)     PRIMARY KEY,
    ticker              VARCHAR(20)     NOT NULL UNIQUE,
    company_name        VARCHAR(200)    NOT NULL DEFAULT '',

    total_queries       INTEGER         NOT NULL DEFAULT 0,
    version_count       INTEGER         NOT NULL DEFAULT 0,

    last_query_at       TIMESTAMPTZ,
    last_stance         VARCHAR(50)     NOT NULL DEFAULT '',
    last_confidence     DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    dominant_concern    VARCHAR(100)    NOT NULL DEFAULT '',

    created_at          TIMESTAMPTZ     NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ     NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_ticker_memory_ticker
    ON ticker_memory (ticker);


-- ---------------------------------------------------------------------------
-- 4. memory_entries
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS memory_entries (
    id              VARCHAR(36)     PRIMARY KEY,
    ticker          VARCHAR(20)     NOT NULL,
    session_id      VARCHAR(200)    NOT NULL DEFAULT '',
    entry_type      VARCHAR(50)     NOT NULL DEFAULT 'analysis',
    content         TEXT            NOT NULL DEFAULT '',
    metadata_json   JSONB           NOT NULL DEFAULT '{}',
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_memory_entries_ticker
    ON memory_entries (ticker);
CREATE INDEX IF NOT EXISTS ix_memory_entries_ticker_type
    ON memory_entries (ticker, entry_type);
CREATE INDEX IF NOT EXISTS ix_memory_entries_created
    ON memory_entries (created_at DESC);


-- ---------------------------------------------------------------------------
-- 5. concern_tags
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS concern_tags (
    id              VARCHAR(36)     PRIMARY KEY,
    ticker          VARCHAR(20)     NOT NULL,
    tag_name        VARCHAR(100)    NOT NULL,
    mention_count   INTEGER         NOT NULL DEFAULT 0,
    first_seen_at   TIMESTAMPTZ     NOT NULL DEFAULT now(),
    last_seen_at    TIMESTAMPTZ     NOT NULL DEFAULT now(),
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT now(),

    CONSTRAINT uq_concern_ticker_tag UNIQUE (ticker, tag_name)
);

CREATE INDEX IF NOT EXISTS ix_concern_tags_ticker
    ON concern_tags (ticker);
CREATE INDEX IF NOT EXISTS ix_concern_tags_ticker_count
    ON concern_tags (ticker, mention_count DESC);


-- ---------------------------------------------------------------------------
-- 6. theme_clusters
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS theme_clusters (
    id              VARCHAR(36)     PRIMARY KEY,
    cluster_label   VARCHAR(200)    NOT NULL,
    tickers         JSONB           NOT NULL DEFAULT '[]',
    concern_overlap JSONB           NOT NULL DEFAULT '{}',
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ     NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_theme_clusters_label
    ON theme_clusters (cluster_label);


-- ---------------------------------------------------------------------------
-- 7. cross_exposures
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS cross_exposures (
    id              VARCHAR(36)     PRIMARY KEY,
    ticker_a        VARCHAR(20)     NOT NULL,
    ticker_b        VARCHAR(20)     NOT NULL,
    shared_concerns JSONB           NOT NULL DEFAULT '[]',
    exposure_type   VARCHAR(50)     NOT NULL DEFAULT 'thematic',
    strength        DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT now(),

    CONSTRAINT uq_cross_exposure_pair UNIQUE (ticker_a, ticker_b)
);

CREATE INDEX IF NOT EXISTS ix_cross_exposures_ticker_a
    ON cross_exposures (ticker_a);
CREATE INDEX IF NOT EXISTS ix_cross_exposures_ticker_b
    ON cross_exposures (ticker_b);


-- ---------------------------------------------------------------------------
-- 8. personalized_insights
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS personalized_insights (
    id              VARCHAR(36)     PRIMARY KEY,
    session_id      VARCHAR(200)    NOT NULL,
    ticker          VARCHAR(20)     NOT NULL,
    insight_type    VARCHAR(50)     NOT NULL DEFAULT '',
    insight_text    TEXT            NOT NULL DEFAULT '',
    supporting_data JSONB           NOT NULL DEFAULT '{}',
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_personalized_insights_session
    ON personalized_insights (session_id);
CREATE INDEX IF NOT EXISTS ix_personalized_insights_ticker
    ON personalized_insights (ticker);


-- ---------------------------------------------------------------------------
-- 9. briefing_sessions
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS briefing_sessions (
    id              VARCHAR(36)     PRIMARY KEY,
    session_date    DATE            NOT NULL,
    session_id      VARCHAR(200)    NOT NULL DEFAULT '',
    tickers_covered JSONB           NOT NULL DEFAULT '[]',
    status          VARCHAR(20)     NOT NULL DEFAULT 'pending',
    metadata_json   JSONB           NOT NULL DEFAULT '{}',
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_briefing_sessions_date
    ON briefing_sessions (session_date DESC);
