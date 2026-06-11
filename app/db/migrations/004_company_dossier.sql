-- Phase 9G · Phase 0 — Company Dossier schema
--
-- Idempotent (uses IF NOT EXISTS throughout).
-- Apply AFTER 001_initial.sql, 002_add_user_id.sql, 003_historical_evidence.sql.
--
-- Design principles:
--   * Head + facet pattern: company_dossier is the single-row-per-ticker head
--     that injection reads in O(1); facet tables hold typed state with
--     independent versioning.
--   * Append-only audit: dossier_revision is NEVER updated or deleted — it is
--     the immutable causal trail for every material facet change.
--   * Soft foreign keys: no FOREIGN KEY constraints to thesis_versions or
--     historical_analogs so the dossier lifecycle is independent of those
--     tables (same convention as the rest of the schema).
--   * JSON storage: JSONB on PostgreSQL (native GIN / containment queries);
--     the ORM uses sqlalchemy.JSON which reads/writes both JSONB and TEXT.
--   * All nullable user_id / session_id for multi-tenant forward compat.
--   * Row counts: 9 new tables → db_table_count goes from 10 → 19.


-- ---------------------------------------------------------------------------
-- 1. company_dossier  (head — single row per ticker)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS company_dossier (
    id                    VARCHAR(36)         PRIMARY KEY,

    -- ── Identity ──────────────────────────────────────────────────────────
    ticker                VARCHAR(20)         NOT NULL UNIQUE,
    company_name          VARCHAR(200)        NOT NULL DEFAULT '',

    -- ── Denormalised prior-thesis-state cache (soft FK to thesis_versions) ─
    -- Source of truth lives in thesis_versions; this is a read-through cache.
    latest_version_id     VARCHAR(36),                          -- NULL until first analysis
    stance                VARCHAR(50)         NOT NULL DEFAULT '',
    conviction            DOUBLE PRECISION    NOT NULL DEFAULT 0.0,
    primary_concern       VARCHAR(200)        NOT NULL DEFAULT '',
    prior_as_of           TIMESTAMPTZ,

    -- ── Dossier meta ──────────────────────────────────────────────────────
    schema_version        INTEGER             NOT NULL DEFAULT 1,
    global_confidence     DOUBLE PRECISION    NOT NULL DEFAULT 0.0,
    -- staleness_state: fresh | aging | stale
    staleness_state       VARCHAR(20)         NOT NULL DEFAULT 'fresh',
    last_full_update_at   TIMESTAMPTZ,
    analysis_count        INTEGER             NOT NULL DEFAULT 0,
    -- row_version: optimistic-concurrency lock — bump on every write
    row_version           INTEGER             NOT NULL DEFAULT 0,

    -- ── Identity / audit ──────────────────────────────────────────────────
    user_id               VARCHAR(64),
    session_id            VARCHAR(200)        NOT NULL DEFAULT '',
    created_at            TIMESTAMPTZ         NOT NULL DEFAULT now(),
    updated_at            TIMESTAMPTZ         NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- 2. dossier_core_debate  (the one defining question — single row per ticker)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS dossier_core_debate (
    id                    VARCHAR(36)         PRIMARY KEY,

    ticker                VARCHAR(20)         NOT NULL UNIQUE,

    -- ── Debate framing ────────────────────────────────────────────────────
    question              TEXT                NOT NULL DEFAULT '',
    bull_pole             TEXT                NOT NULL DEFAULT '',
    bear_pole             TEXT                NOT NULL DEFAULT '',
    -- current_lean: bull | bear | balanced
    current_lean          VARCHAR(20)         NOT NULL DEFAULT 'balanced',
    resolution_signal     TEXT                NOT NULL DEFAULT '',

    -- ── Versioning / confidence ───────────────────────────────────────────
    version               INTEGER             NOT NULL DEFAULT 1,
    confidence            DOUBLE PRECISION    NOT NULL DEFAULT 0.0,

    user_id               VARCHAR(64),
    session_id            VARCHAR(200)        NOT NULL DEFAULT '',
    first_seen_at         TIMESTAMPTZ         NOT NULL DEFAULT now(),
    updated_at            TIMESTAMPTZ         NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- 3. dossier_moat_dimension  (one row per ticker × axis — bounded at 6 axes)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS dossier_moat_dimension (
    id                    VARCHAR(36)         PRIMARY KEY,

    ticker                VARCHAR(20)         NOT NULL,
    -- axis taxonomy: ecosystem_lockin | supply_chain_control | switching_costs
    --                | network_effects | regulatory_ip | management_execution
    axis                  VARCHAR(60)         NOT NULL,

    -- ── Dimension state ───────────────────────────────────────────────────
    -- strength: strong | moderate | weak | absent
    strength              VARCHAR(20)         NOT NULL DEFAULT 'moderate',
    -- trend:    strengthening | stable | weakening
    trend                 VARCHAR(20)         NOT NULL DEFAULT 'stable',
    rationale             TEXT                NOT NULL DEFAULT '',
    vulnerability         TEXT                NOT NULL DEFAULT '',

    -- ── Versioning / hysteresis ───────────────────────────────────────────
    version               INTEGER             NOT NULL DEFAULT 1,
    confidence            DOUBLE PRECISION    NOT NULL DEFAULT 0.0,
    -- pending_flip: TRUE when one synthesis disagrees with current state;
    -- flip commits only when a second synthesis agrees (hysteresis guard)
    pending_flip          BOOLEAN             NOT NULL DEFAULT FALSE,

    user_id               VARCHAR(64),
    session_id            VARCHAR(200)        NOT NULL DEFAULT '',
    last_changed_at       TIMESTAMPTZ         NOT NULL DEFAULT now(),

    CONSTRAINT uq_dossier_moat_ticker_axis UNIQUE (ticker, axis)
);

-- ---------------------------------------------------------------------------
-- 4. dossier_catalyst  (per-catalyst lifecycle — multiple per ticker)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS dossier_catalyst (
    -- UUID is stable across analyses for hit/miss tracking
    id                    VARCHAR(36)         PRIMARY KEY,

    ticker                VARCHAR(20)         NOT NULL,

    -- ── Catalyst definition ───────────────────────────────────────────────
    statement             TEXT                NOT NULL DEFAULT '',
    -- direction: bull_trigger | bear_trigger
    direction             VARCHAR(20)         NOT NULL DEFAULT 'bull_trigger',
    -- specificity: 0.0–1.0; catalysts below threshold (0.50) are discarded
    specificity           DOUBLE PRECISION    NOT NULL DEFAULT 0.0,
    expected_window       VARCHAR(100)        NOT NULL DEFAULT '',
    -- status: open | triggered | invalidated | expired
    status                VARCHAR(20)         NOT NULL DEFAULT 'open',
    -- how much this catalyst should move conviction if it fires (0.0–1.0)
    conviction_weight     DOUBLE PRECISION    NOT NULL DEFAULT 0.0,

    -- ── Provenance ────────────────────────────────────────────────────────
    -- soft FK to thesis_versions.id that introduced this catalyst
    source_version_id     VARCHAR(36),

    user_id               VARCHAR(64),
    session_id            VARCHAR(200)        NOT NULL DEFAULT '',
    created_at            TIMESTAMPTZ         NOT NULL DEFAULT now(),
    resolved_at           TIMESTAMPTZ                               -- NULL while open
);

-- ---------------------------------------------------------------------------
-- 5. dossier_variant  (consensus-divergence map — single row per ticker)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS dossier_variant (
    id                    VARCHAR(36)         PRIMARY KEY,

    ticker                VARCHAR(20)         NOT NULL UNIQUE,

    -- ── Divergences ───────────────────────────────────────────────────────
    -- JSON list of {dimension, consensus_view, clearsignal_view, direction,
    --               conviction} — bounded (2–3 entries)
    divergences           JSONB               NOT NULL DEFAULT '[]',

    -- ── Versioning ────────────────────────────────────────────────────────
    version               INTEGER             NOT NULL DEFAULT 1,
    confidence            DOUBLE PRECISION    NOT NULL DEFAULT 0.0,

    user_id               VARCHAR(64),
    session_id            VARCHAR(200)        NOT NULL DEFAULT '',
    updated_at            TIMESTAMPTZ         NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- 6. dossier_durability  (raw durability signals — single row per ticker)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS dossier_durability (
    id                    VARCHAR(36)         PRIMARY KEY,

    ticker                VARCHAR(20)         NOT NULL UNIQUE,

    -- ── Raw signals (never pre-scored; scoring is a pure function at read-time) ─
    -- cycle_position: early | mid | late | unknown
    cycle_position        VARCHAR(20)         NOT NULL DEFAULT 'unknown',
    catalyst_proximity_days  INTEGER,                  -- NULL if no open catalyst window
    analog_time_to_trough_days INTEGER,               -- from top failure-mode analog
    -- conviction_trend mirrors investment-memory direction: rising | falling | stable | volatile
    conviction_trend      VARCHAR(20)         NOT NULL DEFAULT 'stable',
    -- horizon_hint: trade | investment | secular
    horizon_hint          VARCHAR(20)         NOT NULL DEFAULT 'investment',

    user_id               VARCHAR(64),
    session_id            VARCHAR(200)        NOT NULL DEFAULT '',
    updated_at            TIMESTAMPTZ         NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- 7. dossier_failure_mode  (active failure-pattern matches — soft FK to
--    historical_analogs — multiple per ticker, one per analog)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS dossier_failure_mode (
    id                    VARCHAR(36)         PRIMARY KEY,

    ticker                VARCHAR(20)         NOT NULL,
    -- soft FK to historical_analogs.id — no CASCADE to keep lifecycles independent
    analog_id             VARCHAR(36)         NOT NULL,

    -- ── Stage placement ───────────────────────────────────────────────────
    sequence_stage        INTEGER             NOT NULL DEFAULT 1,
    stage_evidence        TEXT                NOT NULL DEFAULT '',
    -- snapshot of relevance_score at match time (the live score can drift)
    relevance_at_match    DOUBLE PRECISION    NOT NULL DEFAULT 0.0,

    user_id               VARCHAR(64),
    session_id            VARCHAR(200)        NOT NULL DEFAULT '',
    matched_at            TIMESTAMPTZ         NOT NULL DEFAULT now(),

    CONSTRAINT uq_dossier_failure_ticker_analog UNIQUE (ticker, analog_id)
);

-- ---------------------------------------------------------------------------
-- 8. dossier_revision  (append-only audit log — NO UPDATE OR DELETE PATH)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS dossier_revision (
    id                    VARCHAR(36)         PRIMARY KEY,

    ticker                VARCHAR(20)         NOT NULL,
    -- facet: core_debate | moat_dimension | catalyst | variant |
    --         durability | failure_mode | head
    facet                 VARCHAR(40)         NOT NULL,

    -- ── Change record ─────────────────────────────────────────────────────
    prev_version          INTEGER,                    -- NULL on first-create revisions
    new_version           INTEGER             NOT NULL,
    change_summary        TEXT                NOT NULL DEFAULT '',
    -- JSON object containing the before/after diff for the facet
    diff_json             JSONB               NOT NULL DEFAULT '{}',
    confidence            DOUBLE PRECISION    NOT NULL DEFAULT 0.0,

    -- ── Provenance ────────────────────────────────────────────────────────
    -- soft FK to thesis_versions.id that caused this revision
    source_version_id     VARCHAR(36),

    user_id               VARCHAR(64),
    session_id            VARCHAR(200)        NOT NULL DEFAULT '',
    -- created_at is immutable — this row is never updated
    created_at            TIMESTAMPTZ         NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- 9. dossier_evidence_ref  (per-claim provenance spine)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS dossier_evidence_ref (
    id                    VARCHAR(36)         PRIMARY KEY,

    ticker                VARCHAR(20)         NOT NULL,
    -- facet: same enum as dossier_revision.facet
    facet                 VARCHAR(40)         NOT NULL,
    -- stable hash of the specific claim (so refs survive text rewording)
    claim_hash            VARCHAR(64)         NOT NULL,

    -- ── Source ────────────────────────────────────────────────────────────
    -- source_type: thesis_version | analog | filing | financial_data | inferred
    source_type           VARCHAR(30)         NOT NULL DEFAULT 'inferred',
    -- source_id: FK value where applicable; NULL for inferred claims
    source_id             VARCHAR(36),

    user_id               VARCHAR(64),
    session_id            VARCHAR(200)        NOT NULL DEFAULT '',
    as_of                 TIMESTAMPTZ         NOT NULL DEFAULT now()
);


-- ============================================================================
-- INDEXES
-- ============================================================================

-- ── company_dossier ──────────────────────────────────────────────────────────
-- UNIQUE(ticker) already created as a table constraint above.
-- secondary index for user-scoped queries
CREATE INDEX IF NOT EXISTS ix_company_dossier_user_id
    ON company_dossier (user_id)
    WHERE user_id IS NOT NULL;

-- ── dossier_core_debate ──────────────────────────────────────────────────────
-- UNIQUE(ticker) already created as table constraint above.

-- ── dossier_moat_dimension ───────────────────────────────────────────────────
-- UNIQUE(ticker, axis) already created as table constraint above.
CREATE INDEX IF NOT EXISTS ix_dossier_moat_ticker
    ON dossier_moat_dimension (ticker);

CREATE INDEX IF NOT EXISTS ix_dossier_moat_pending_flip
    ON dossier_moat_dimension (ticker, pending_flip)
    WHERE pending_flip = TRUE;

-- ── dossier_catalyst ─────────────────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS ix_dossier_catalyst_ticker
    ON dossier_catalyst (ticker);

-- injection reads only open catalysts; watchlist UI filters by status
CREATE INDEX IF NOT EXISTS ix_dossier_catalyst_ticker_status
    ON dossier_catalyst (ticker, status);

CREATE INDEX IF NOT EXISTS ix_dossier_catalyst_source_version
    ON dossier_catalyst (source_version_id)
    WHERE source_version_id IS NOT NULL;

-- ── dossier_variant ──────────────────────────────────────────────────────────
-- UNIQUE(ticker) already created as table constraint above.

-- ── dossier_durability ───────────────────────────────────────────────────────
-- UNIQUE(ticker) already created as table constraint above.

-- ── dossier_failure_mode ─────────────────────────────────────────────────────
-- UNIQUE(ticker, analog_id) already created as table constraint above.
CREATE INDEX IF NOT EXISTS ix_dossier_failure_ticker
    ON dossier_failure_mode (ticker);

-- reverse lookup: which tickers currently match a given analog
CREATE INDEX IF NOT EXISTS ix_dossier_failure_analog
    ON dossier_failure_mode (analog_id);

-- ── dossier_revision (append-only) ───────────────────────────────────────────
CREATE INDEX IF NOT EXISTS ix_dossier_revision_ticker_facet_time
    ON dossier_revision (ticker, facet, created_at DESC);

CREATE INDEX IF NOT EXISTS ix_dossier_revision_ticker
    ON dossier_revision (ticker);

CREATE INDEX IF NOT EXISTS ix_dossier_revision_source_version
    ON dossier_revision (source_version_id)
    WHERE source_version_id IS NOT NULL;

-- ── dossier_evidence_ref ─────────────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS ix_dossier_evidence_ticker_facet
    ON dossier_evidence_ref (ticker, facet);

CREATE INDEX IF NOT EXISTS ix_dossier_evidence_source
    ON dossier_evidence_ref (source_type, source_id)
    WHERE source_id IS NOT NULL;
