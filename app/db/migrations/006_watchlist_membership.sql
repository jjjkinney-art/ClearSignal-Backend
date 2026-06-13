-- Phase 10B · Slice 2 — Watchlist Membership
-- Adds watched_tickers table for DB-backed watchlist membership.
-- Idempotent: safe to run repeatedly (IF NOT EXISTS throughout).
--
-- user_id is nullable: NULL represents the global (single-user) watchlist.
-- Multi-user support (non-null user_id) is wired in Phase 10B Slice 3+.
-- Deduplication at the application layer; see watchlist_repo.ticker_add.

CREATE TABLE IF NOT EXISTS watched_tickers (
    id           VARCHAR(36)   NOT NULL,
    user_id      VARCHAR(64)   DEFAULT NULL,
    ticker       VARCHAR(20)   NOT NULL,
    company_name VARCHAR(200)  NOT NULL DEFAULT '',
    active       BOOLEAN       NOT NULL DEFAULT TRUE,
    added_at     TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    updated_at   TIMESTAMPTZ   NOT NULL DEFAULT NOW(),

    PRIMARY KEY (id)
);

CREATE INDEX IF NOT EXISTS ix_watched_tickers_ticker   ON watched_tickers (ticker);
CREATE INDEX IF NOT EXISTS ix_watched_tickers_active   ON watched_tickers (active);
CREATE INDEX IF NOT EXISTS ix_watched_tickers_user_id  ON watched_tickers (user_id);
