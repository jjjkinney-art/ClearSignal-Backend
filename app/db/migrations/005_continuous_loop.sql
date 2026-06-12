-- Phase 10A · Slice 1 — Continuous Intelligence Loop schema
--
-- Idempotent (uses IF NOT EXISTS throughout).
-- Apply AFTER 004_company_dossier.sql.
--
-- Design principles carried from the Phase 10A spec (§1–§6):
--   * Jobs are rows with state machines, not coroutines.  The DB is the
--     source of truth; instances are stateless.
--   * Two idempotency keys: work_key (execution) prevents double-invocation;
--     content_key (delivery) prevents duplicate sends — both enforced below
--     the app layer as UNIQUE constraints.
--   * Lease-based locking with fence tokens: each new acquire increments the
--     token so zombie writers from dead holders can be rejected.
--   * Append-only audit (job_runs): NO UPDATE OR DELETE in any repo.
--     Same discipline as dossier_revision.
--   * No FOREIGN KEY constraints from the loop into thesis_versions,
--     dossier_revision, or ticker_memory — the loop reads those as dirty
--     signals and joins logically, keeping it independent (§5.4).
--   * JSON storage: JSONB on PostgreSQL; ORM uses sqlalchemy.JSON for compat.
--   * Row counts: 5 new tables → db_table_count goes from 19 → 24.


-- ---------------------------------------------------------------------------
-- 1. scheduled_jobs  (current-state head — one row per job instance)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS scheduled_jobs (
    id                VARCHAR(36)         PRIMARY KEY,

    -- ── Job identity ──────────────────────────────────────────────────────
    job_type          VARCHAR(60)         NOT NULL,
    target_key        VARCHAR(200)        NOT NULL,   -- user_id, ticker, or portfolio_id
    -- period_bucket: ISO date string or "drift" for one-shot drift jobs
    period_bucket     VARCHAR(40)         NOT NULL,

    -- ── State machine ─────────────────────────────────────────────────────
    -- state: scheduled | claimed | running | succeeded | failed |
    --        skipped_stale | dead_letter
    state             VARCHAR(20)         NOT NULL DEFAULT 'scheduled',

    -- ── Scheduling ────────────────────────────────────────────────────────
    next_run_utc      TIMESTAMPTZ,                   -- NULL = run ASAP
    cadence           VARCHAR(40),                   -- NULL for drift-only jobs
    catch_up_window_s INTEGER             NOT NULL DEFAULT 3600,

    -- ── Execution control ─────────────────────────────────────────────────
    attempts          INTEGER             NOT NULL DEFAULT 0,
    max_attempts      INTEGER             NOT NULL DEFAULT 3,

    -- ── Lease (NULL when job is unowned) ──────────────────────────────────
    holder_id         VARCHAR(200),
    lease_expires_utc TIMESTAMPTZ,
    -- fence_token: incremented on each claim; stale holders are rejected
    fence_token       INTEGER             NOT NULL DEFAULT 0,

    payload_json      JSONB               NOT NULL DEFAULT '{}',
    last_generated_at TIMESTAMPTZ,                   -- NULL until first successful run

    created_at        TIMESTAMPTZ         NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ         NOT NULL DEFAULT now(),

    -- Enqueue idempotency + drift coalescing: two signals for the same
    -- (type, target, bucket) collapse to one row
    CONSTRAINT uq_scheduled_job UNIQUE (job_type, target_key, period_bucket)
);


-- ---------------------------------------------------------------------------
-- 2. job_locks  (single-flight lease table)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS job_locks (
    -- Namespaced: "loop:tick", "loop:job:{id}"
    lock_name         VARCHAR(200)        PRIMARY KEY,

    holder_id         VARCHAR(200)        NOT NULL,
    acquired_utc      TIMESTAMPTZ         NOT NULL DEFAULT now(),
    lease_expires_utc TIMESTAMPTZ         NOT NULL,
    -- fence_token: monotonically incremented on each successful acquire;
    -- used by the lock service to reject writes from zombie holders
    fence_token       INTEGER             NOT NULL DEFAULT 0
);


-- ---------------------------------------------------------------------------
-- 3. job_runs  (append-only execution audit — NO UPDATE OR DELETE)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS job_runs (
    id            VARCHAR(36)         PRIMARY KEY,

    -- ── Provenance ────────────────────────────────────────────────────────
    -- Soft FK to scheduled_jobs.id — no CASCADE (job may be dead-lettered)
    job_id        VARCHAR(36)         NOT NULL,
    -- work_key = hash(job_type, target_key, period_bucket)
    -- Idempotency short-circuit: before invoking a producer the scheduler
    -- checks for a succeeded row with this key — if found, skip.
    work_key      VARCHAR(64)         NOT NULL,

    -- Denormalised from the job row (survives job deletion/dead-letter)
    job_type      VARCHAR(60)         NOT NULL,
    target_key    VARCHAR(200)        NOT NULL,
    period_bucket VARCHAR(40)         NOT NULL,

    -- ── Timing ────────────────────────────────────────────────────────────
    started_utc   TIMESTAMPTZ         NOT NULL DEFAULT now(),
    finished_utc  TIMESTAMPTZ,

    -- ── Outcome ───────────────────────────────────────────────────────────
    -- outcome: running | succeeded | failed | skipped_stale |
    --          short_circuited | dead_letter
    outcome       VARCHAR(30)         NOT NULL DEFAULT 'running',
    spent_llm_calls INTEGER           NOT NULL DEFAULT 0,
    drift_hit     BOOLEAN             NOT NULL DEFAULT FALSE,
    error         TEXT,

    -- ── Lease identity (who ran this; fence proof) ────────────────────────
    holder_id     VARCHAR(200)        NOT NULL,
    fence_token   INTEGER             NOT NULL DEFAULT 0
);


-- ---------------------------------------------------------------------------
-- 4. delivery_ledger  (current-state delivery record with dedup guarantee)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS delivery_ledger (
    id           VARCHAR(36)         PRIMARY KEY,

    -- content_key = hash(target_key, channel, content_hash, period_bucket)
    -- UNIQUE constraint is the DB-layer duplicate-delivery hard stop.
    content_key  VARCHAR(64)         NOT NULL,

    target_key   VARCHAR(200)        NOT NULL,
    -- channel: in_app | email | push  (10C adds email/push as new values)
    channel      VARCHAR(40)         NOT NULL DEFAULT 'in_app',
    content_hash VARCHAR(64)         NOT NULL,
    -- artifact_ref: pointer to the source artifact (e.g. briefing_sessions.id)
    artifact_ref VARCHAR(200),

    -- status: pending | delivered | failed | suppressed | deferred
    status       VARCHAR(20)         NOT NULL DEFAULT 'pending',
    attempts     INTEGER             NOT NULL DEFAULT 0,
    -- not_before_utc: deferred by quiet hours, frequency cap, etc.
    not_before_utc TIMESTAMPTZ,

    created_at   TIMESTAMPTZ         NOT NULL DEFAULT now(),
    delivered_at TIMESTAMPTZ,

    CONSTRAINT uq_delivery_content_key UNIQUE (content_key)
);


-- ---------------------------------------------------------------------------
-- 5. notifications  (in-app channel sink; frontend polls GET /notifications)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS notifications (
    id         VARCHAR(36)         PRIMARY KEY,

    user_id    VARCHAR(64)         NOT NULL,
    -- kind: daily_brief | watchlist_alert | dossier_update | system
    kind       VARCHAR(60)         NOT NULL DEFAULT '',
    body_json  JSONB               NOT NULL DEFAULT '{}',
    read_at    TIMESTAMPTZ,                  -- NULL until user reads it
    created_at TIMESTAMPTZ         NOT NULL DEFAULT now()
);


-- ============================================================================
-- INDEXES
-- ============================================================================

-- ── scheduled_jobs ───────────────────────────────────────────────────────────
-- UNIQUE(job_type, target_key, period_bucket) already created as table constraint.

-- Hot path: select_due query (the loop's most frequent read)
CREATE INDEX IF NOT EXISTS ix_scheduled_jobs_state_next_run
    ON scheduled_jobs (state, next_run_utc);

-- Lease-reap scan
CREATE INDEX IF NOT EXISTS ix_scheduled_jobs_lease_expires
    ON scheduled_jobs (lease_expires_utc)
    WHERE lease_expires_utc IS NOT NULL;

-- ── job_locks ─────────────────────────────────────────────────────────────────
-- PK (lock_name) already O(1) — no additional indexes needed.

-- ── job_runs (append-only) ────────────────────────────────────────────────────
-- Idempotency short-circuit: lookup by work_key + outcome
CREATE INDEX IF NOT EXISTS ix_job_runs_work_key_outcome
    ON job_runs (work_key, outcome);

-- Per-job run history
CREATE INDEX IF NOT EXISTS ix_job_runs_job_id_started
    ON job_runs (job_id, started_utc);

-- ── delivery_ledger ───────────────────────────────────────────────────────────
-- UNIQUE(content_key) already created as table constraint.

-- delivery_flush drain query
CREATE INDEX IF NOT EXISTS ix_delivery_ledger_status_not_before
    ON delivery_ledger (status, not_before_utc);

-- ── notifications ─────────────────────────────────────────────────────────────
-- Inbox poll: unread rows first (read_at IS NULL sorts first with NULLs FIRST)
CREATE INDEX IF NOT EXISTS ix_notifications_user_id_read_at
    ON notifications (user_id, read_at);


-- ============================================================================
-- EXTENSION — briefing_sessions (additive ALTER; no row rewrite)
-- ============================================================================
-- Completes the pending → generated → delivered ladder that BriefingSession
-- already models.  Both columns are nullable so no DEFAULT and no rewrite.

ALTER TABLE briefing_sessions
    ADD COLUMN IF NOT EXISTS content_hash     VARCHAR(64);

ALTER TABLE briefing_sessions
    ADD COLUMN IF NOT EXISTS delivery_channel VARCHAR(40);
