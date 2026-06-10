-- Phase 9F — Historical Evidence Engine
-- Single-table MVP: historical_analogs
--
-- Idempotent (uses IF NOT EXISTS throughout).
-- Apply AFTER 001_initial.sql and 002_add_user_id.sql on a live database.
--
-- Design principles:
--   * Unit = analog instance, not event.  One macro episode (dot-com) maps to
--     multiple instances (Cisco 2000, Amazon 2000) with distinct mechanisms.
--   * Match on setup and mechanism, never on outcome alone.
--   * disanalogy is NOT NULL by design — prevents trivia entries from existing.
--   * reaction_series is reserved for Phase 9G chart integration.
--
-- evidence_contexts (retrieval logging) is deferred until after MVP validation.

-- ---------------------------------------------------------------------------
-- historical_analogs
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS historical_analogs (
    id                   VARCHAR(36)          PRIMARY KEY,

    -- ── Identity / curation ───────────────────────────────────────────────
    label                VARCHAR(200)         NOT NULL UNIQUE,
    episode              VARCHAR(200)         NOT NULL DEFAULT '',
    entity_ticker        VARCHAR(20),                          -- NULL = macro/sector-level
    sector               VARCHAR(60)          NOT NULL DEFAULT '',
    business_model       VARCHAR(60)          NOT NULL DEFAULT '',
    quality_rating       VARCHAR(20)          NOT NULL DEFAULT 'moderate',
                                                               -- strong | moderate

    -- ── Setup fingerprint (what is MATCHED on) ────────────────────────────
    mechanism            VARCHAR(60)          NOT NULL,        -- see taxonomy
    concern_tags         JSONB                NOT NULL DEFAULT '[]',
    valuation_regime     VARCHAR(40)          NOT NULL DEFAULT '',
                                                               -- peak_multiple | compressed | neutral
    growth_phase         VARCHAR(40)          NOT NULL DEFAULT '',
                                                               -- hypergrowth | deceleration | mature
    macro_regime         VARCHAR(40)          NOT NULL DEFAULT '',
                                                               -- hiking | easing | inversion | neutral

    -- ── Outcome (the PAYLOAD presented to the user) ───────────────────────
    event_start          DATE,
    event_end            DATE,
    drawdown_pct         DOUBLE PRECISION,                     -- signed; e.g. -0.57 = -57%
    time_to_trough_days  INTEGER,
    time_to_recover_days INTEGER,                              -- NULL = never recovered in window
    outcome_summary      TEXT                 NOT NULL DEFAULT '',

    -- ── Phase 9G forward-compat: price series for charts ──────────────────
    reaction_series      JSONB                NOT NULL DEFAULT '[]',
                                                               -- [{t: ISO date, px_rel: float}]

    -- ── Credibility anchors (mandatory) ───────────────────────────────────
    why_relevant         TEXT                 NOT NULL DEFAULT '',
    disanalogy           TEXT                 NOT NULL,        -- "why it might NOT repeat" — NOT NULL enforced
    base_rate_note       TEXT                 NOT NULL DEFAULT '',
    data_confidence      VARCHAR(20)          NOT NULL DEFAULT 'moderate',
                                                               -- strong | moderate | loose
    source_note          VARCHAR(400)         NOT NULL DEFAULT '',

    created_at           TIMESTAMPTZ          NOT NULL DEFAULT now()
);

-- ── Indexes ───────────────────────────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS ix_hist_mechanism
    ON historical_analogs (mechanism);

CREATE INDEX IF NOT EXISTS ix_hist_sector
    ON historical_analogs (sector);

CREATE INDEX IF NOT EXISTS ix_hist_ticker
    ON historical_analogs (entity_ticker)
    WHERE entity_ticker IS NOT NULL;

CREATE INDEX IF NOT EXISTS ix_hist_quality
    ON historical_analogs (quality_rating);

-- GIN index on concern_tags JSONB for efficient overlap queries
CREATE INDEX IF NOT EXISTS ix_hist_concern_tags_gin
    ON historical_analogs USING GIN (concern_tags);
