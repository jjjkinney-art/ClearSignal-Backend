-- Phase 10C · Slice 2 — Delivery Preferences Schema
--
-- Idempotent (uses IF NOT EXISTS throughout). Apply AFTER 006_watchlist_membership.sql.
--
-- Adds the data model for user delivery preferences and future digest batching.
-- This migration is ADDITIVE and INERT: it creates three new tables and adds two
-- nullable columns to delivery_ledger. No delivery behavior changes; nothing reads
-- or writes these objects until later 10C slices wire them in.
--
--   db_table_count: 25 → 28 (three new tables).
--
-- Design notes
--   * user_id is nullable: NULL represents the global (single-user) preference set,
--     mirroring watched_tickers (006). Multi-user wires in later slices.
--   * Severity values stored here are CANONICAL (app/services/severity_model.py,
--     Slice 1): one of critical | high | medium | low | info.
--   * Defaults mirror the existing settings.delivery_* globals so that an ABSENT
--     prefs row == current global behavior (safe defaults; spec §5.5).
--   * JSON storage: JSONB on PostgreSQL; the ORM uses sqlalchemy.JSON for compat.
--   * delivery_ledger_archive is append-only (no UPDATE/DELETE), mirroring the
--     job_runs / dossier_revision audit discipline.


-- ---------------------------------------------------------------------------
-- 26. user_delivery_prefs  (per-user, per-channel delivery preferences)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS user_delivery_prefs (
    id                VARCHAR(36)   NOT NULL,
    user_id           VARCHAR(64)   DEFAULT NULL,         -- NULL = global single-user
    channel           VARCHAR(40)   NOT NULL DEFAULT 'in_app',
    enabled           BOOLEAN       NOT NULL DEFAULT TRUE,
    -- min_severity: canonical severity floor (severity_model). Default 'info'
    -- matches settings.delivery_severity_floor.
    min_severity      VARCHAR(20)   NOT NULL DEFAULT 'info',
    quiet_hours_start INTEGER       NOT NULL DEFAULT 22,  -- matches delivery_quiet_hours_start
    quiet_hours_end   INTEGER       NOT NULL DEFAULT 7,   -- matches delivery_quiet_hours_end
    timezone          VARCHAR(64)   NOT NULL DEFAULT 'UTC',
    daily_cap         INTEGER       NOT NULL DEFAULT 20,  -- matches delivery_daily_cap
    mute_until        TIMESTAMPTZ   DEFAULT NULL,
    created_at        TIMESTAMPTZ   NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ   NOT NULL DEFAULT now(),

    PRIMARY KEY (id),
    -- One prefs row per (user_id, channel). Application-level dedup via
    -- get_or_create_prefs; the constraint is the hard backstop.
    CONSTRAINT uq_user_delivery_prefs_user_channel UNIQUE (user_id, channel)
);

CREATE INDEX IF NOT EXISTS ix_user_delivery_prefs_user_id ON user_delivery_prefs (user_id);
CREATE INDEX IF NOT EXISTS ix_user_delivery_prefs_channel ON user_delivery_prefs (channel);


-- ---------------------------------------------------------------------------
-- 27. digest_batches  (per-user, per-channel, per-bucket digest accumulator)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS digest_batches (
    id            VARCHAR(36)   NOT NULL,
    user_id       VARCHAR(64)   DEFAULT NULL,
    channel       VARCHAR(40)   NOT NULL DEFAULT 'in_app',
    -- period_bucket: YYYY-MM-DD (or finer) string identifying the digest window.
    period_bucket VARCHAR(40)   NOT NULL,
    -- status: open | rendered | delivered (lifecycle for later slices)
    status        VARCHAR(20)   NOT NULL DEFAULT 'open',
    item_count    INTEGER       NOT NULL DEFAULT 0,
    payload_json  JSONB         NOT NULL DEFAULT '{}',
    content_key   VARCHAR(64)   DEFAULT NULL,
    created_at    TIMESTAMPTZ   NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ   NOT NULL DEFAULT now(),

    PRIMARY KEY (id),
    -- One open batch per (user_id, channel, period_bucket): the append-idempotency
    -- constraint so a second change in the bucket updates rather than inserts.
    CONSTRAINT uq_digest_batches_user_channel_bucket UNIQUE (user_id, channel, period_bucket)
);

CREATE INDEX IF NOT EXISTS ix_digest_batches_user_id     ON digest_batches (user_id);
CREATE INDEX IF NOT EXISTS ix_digest_batches_status      ON digest_batches (status);
CREATE INDEX IF NOT EXISTS ix_digest_batches_bucket      ON digest_batches (period_bucket);
CREATE INDEX IF NOT EXISTS ix_digest_batches_content_key ON digest_batches (content_key);


-- ---------------------------------------------------------------------------
-- 28. delivery_ledger_archive  (append-only aged-out delivery rows)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS delivery_ledger_archive (
    id                   VARCHAR(36)   NOT NULL,
    -- original_delivery_id: the delivery_ledger.id this row was archived from.
    original_delivery_id VARCHAR(36)   DEFAULT NULL,
    user_id              VARCHAR(64)   DEFAULT NULL,
    channel              VARCHAR(40)   NOT NULL DEFAULT 'in_app',
    target_key           VARCHAR(200)  DEFAULT NULL,
    status               VARCHAR(20)   DEFAULT NULL,
    payload_json         JSONB         NOT NULL DEFAULT '{}',
    content_key          VARCHAR(64)   DEFAULT NULL,
    archived_at          TIMESTAMPTZ   NOT NULL DEFAULT now(),

    PRIMARY KEY (id)
);

CREATE INDEX IF NOT EXISTS ix_delivery_archive_original   ON delivery_ledger_archive (original_delivery_id);
CREATE INDEX IF NOT EXISTS ix_delivery_archive_user_id    ON delivery_ledger_archive (user_id);
CREATE INDEX IF NOT EXISTS ix_delivery_archive_content    ON delivery_ledger_archive (content_key);
CREATE INDEX IF NOT EXISTS ix_delivery_archive_archived   ON delivery_ledger_archive (archived_at);


-- ---------------------------------------------------------------------------
-- delivery_ledger — additive canonical-severity columns (nullable, no rewrite)
-- ---------------------------------------------------------------------------
-- canonical_severity: one of critical|high|medium|low|info (severity_model).
-- severity_rank: the numeric rank (severity_model.severity_rank), 0..4.
-- Both nullable so existing rows require no rewrite and pre-10C readers ignore them.
ALTER TABLE delivery_ledger
    ADD COLUMN IF NOT EXISTS canonical_severity VARCHAR(20);
ALTER TABLE delivery_ledger
    ADD COLUMN IF NOT EXISTS severity_rank      INTEGER;

CREATE INDEX IF NOT EXISTS ix_delivery_ledger_canonical_severity
    ON delivery_ledger (canonical_severity);
