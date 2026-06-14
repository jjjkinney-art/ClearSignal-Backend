-- Phase 10D · Slice 1 — Portfolio Intelligence Schema
--
-- Idempotent (uses IF NOT EXISTS throughout). Apply AFTER 007_briefing_delivery.sql.
--
-- Introduces the portfolio-model layer: three new tables that represent a
-- user-authored portfolio (portfolios), its constituent positions
-- (portfolio_positions), and system-derived portfolio insights
-- (portfolio_insights).
--
-- This migration is ADDITIVE and INERT: it creates three new tables.
-- No existing table is modified.  No delivery behavior changes.  No analytical
-- logic runs until later 10D slices wire in the exposure-projection and insight
-- generation services.
--
--   db_table_count: 28 → 31 (three new tables).
--
-- Design notes
--   * user_id is nullable: NULL = global (single-user) portfolio, mirroring
--     watched_tickers (006) and user_delivery_prefs (007).
--   * portfolio_positions uses UNIQUE(portfolio_id, ticker) for append-idempotency:
--     re-adding a removed ticker reactivates the existing row rather than
--     inserting a duplicate.  Mirrors the watched_tickers pattern.
--   * membership_class ∈ {owned, watchlist, on_radar} (spec §1.1).
--   * All financial fields (weight, cost_basis, shares) are nullable:
--     the system NEVER fetches or derives these from external APIs.
--   * portfolio_insights.content_key UNIQUE is the §3.4 generation-side dedup:
--     a 7-day period_bucket key prevents re-generating an identical insight
--     within the same window.
--   * No ALTER on any existing table.  The notifications.kind column gains the
--     value "portfolio_alert" at runtime — an additive enum value on a free-form
--     VARCHAR, requiring no migration DDL.
--   * JSON storage: JSONB on PostgreSQL (full JSONB semantics); the ORM uses
--     sqlalchemy.JSON for SQLite compat (test fixtures).


-- ---------------------------------------------------------------------------
-- 29. portfolios  (user-authored portfolio head — one per named collection)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS portfolios (
    id          VARCHAR(36)   NOT NULL,
    -- user_id: NULL = global/single-user portfolio, mirroring watched_tickers.
    user_id     VARCHAR(64)   DEFAULT NULL,
    name        VARCHAR(200)  NOT NULL DEFAULT 'My Portfolio',
    description TEXT          DEFAULT NULL,
    -- is_default: True for the auto-created watchlist-mirror portfolio (Slice 2).
    is_default  BOOLEAN       NOT NULL DEFAULT FALSE,
    created_at  TIMESTAMPTZ   NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ   NOT NULL DEFAULT now(),

    PRIMARY KEY (id),
    -- One named portfolio per user.  Application enforces uniqueness; constraint
    -- is the hard backstop (mirrors uq_user_delivery_prefs_user_channel).
    CONSTRAINT uq_portfolios_user_name UNIQUE (user_id, name)
);

CREATE INDEX IF NOT EXISTS ix_portfolios_user_id   ON portfolios (user_id);
CREATE INDEX IF NOT EXISTS ix_portfolios_is_default ON portfolios (user_id, is_default);


-- ---------------------------------------------------------------------------
-- 30. portfolio_positions  (per-portfolio position rows)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS portfolio_positions (
    id               VARCHAR(36)  NOT NULL,
    portfolio_id     VARCHAR(36)  NOT NULL,
    ticker           VARCHAR(20)  NOT NULL,
    -- membership_class: owned | watchlist | on_radar  (spec §1.1)
    membership_class VARCHAR(20)  NOT NULL DEFAULT 'watchlist',
    -- weight, cost_basis, shares: ALL user-supplied; NEVER fetched externally.
    weight           FLOAT        DEFAULT NULL,   -- 0.0–1.0; optional
    cost_basis       FLOAT        DEFAULT NULL,   -- per share; optional
    shares           FLOAT        DEFAULT NULL,   -- share count; optional
    notes            TEXT         DEFAULT NULL,
    -- active: soft-delete flag (mirrors watched_tickers).
    active           BOOLEAN      NOT NULL DEFAULT TRUE,
    added_at         TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),

    PRIMARY KEY (id),
    -- Append-idempotency: re-adding a ticker reactivates the existing row.
    -- (mirrors the watchlist_repo.ticker_add discipline)
    CONSTRAINT uq_portfolio_positions_portfolio_ticker UNIQUE (portfolio_id, ticker)
);

CREATE INDEX IF NOT EXISTS ix_portfolio_positions_portfolio_id ON portfolio_positions (portfolio_id);
CREATE INDEX IF NOT EXISTS ix_portfolio_positions_ticker       ON portfolio_positions (ticker);
CREATE INDEX IF NOT EXISTS ix_portfolio_positions_active       ON portfolio_positions (portfolio_id, active);
-- Reverse lookup: "which portfolios hold ticker T" — used by the loop-tick
-- re-evaluation in Slice 5 (insight generation on dossier update).
CREATE INDEX IF NOT EXISTS ix_portfolio_positions_ticker_active ON portfolio_positions (ticker, active);


-- ---------------------------------------------------------------------------
-- 31. portfolio_insights  (system-derived portfolio insights — current-state)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS portfolio_insights (
    id                   VARCHAR(36)   NOT NULL,
    portfolio_id         VARCHAR(36)   NOT NULL,
    -- insight_type: closed enum from spec §3.1
    --   concentration_breach | cluster_concentration | high_correlation_pair |
    --   propagated_catalyst | failure_contagion | macro_sensitivity_cluster |
    --   thesis_divergence | coverage_gap
    insight_type         VARCHAR(60)   NOT NULL DEFAULT '',
    -- cluster_label: the shared-concern or theme label driving this insight.
    cluster_label        VARCHAR(200)  NOT NULL DEFAULT '',
    -- member_tickers: JSON array of ticker strings in this cluster.
    member_tickers       TEXT          NOT NULL DEFAULT '[]',
    -- cluster_weight: sum of portfolio weights for member positions; NULL when
    -- positions have no weights set.
    cluster_weight       FLOAT         DEFAULT NULL,
    -- severity: canonical per severity_model.py (critical|high|medium|low|info).
    severity             VARCHAR(20)   NOT NULL DEFAULT 'info',
    -- severity_rank: numeric rank (4=critical … 0=info).
    severity_rank        INTEGER       NOT NULL DEFAULT 0,
    -- rank_score: composite ranking score from spec §3.3 (Slice 6 stamps this).
    rank_score           FLOAT         NOT NULL DEFAULT 0.0,
    -- body_json: structured insight payload (rendered template prose + metadata).
    body_json            TEXT          NOT NULL DEFAULT '{}',
    -- cross_exposure_as_of: min(updated_at) across contributing cross_exposure
    -- edges — the freshness bound (spec §2.5).
    cross_exposure_as_of TIMESTAMPTZ   DEFAULT NULL,
    -- stale_input: True when cross_exposure_as_of exceeds the staleness threshold.
    -- Caps severity at MEDIUM when True.
    stale_input          BOOLEAN       NOT NULL DEFAULT FALSE,
    -- content_key: sha256(portfolio_id + insight_type + cluster_label + period_bucket).
    -- UNIQUE — the §3.4 generation-side dedup hard stop (7-day bucket).
    content_key          VARCHAR(64)   NOT NULL DEFAULT '',
    created_at           TIMESTAMPTZ   NOT NULL DEFAULT now(),
    updated_at           TIMESTAMPTZ   NOT NULL DEFAULT now(),
    -- last_delivered_at: stamped by the delivery layer (Slice 7); NULL = never delivered.
    last_delivered_at    TIMESTAMPTZ   DEFAULT NULL,

    PRIMARY KEY (id),
    -- §3.4 dedup hard stop: one insight per (portfolio, type, cluster, period).
    CONSTRAINT uq_portfolio_insights_content_key UNIQUE (content_key)
);

CREATE INDEX IF NOT EXISTS ix_portfolio_insights_portfolio_id  ON portfolio_insights (portfolio_id);
CREATE INDEX IF NOT EXISTS ix_portfolio_insights_severity_rank ON portfolio_insights (portfolio_id, severity_rank);
CREATE INDEX IF NOT EXISTS ix_portfolio_insights_type_created  ON portfolio_insights (insight_type, created_at);
CREATE INDEX IF NOT EXISTS ix_portfolio_insights_content_key   ON portfolio_insights (content_key);
