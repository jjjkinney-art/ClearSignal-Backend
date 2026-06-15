-- Phase 17 · Slice 1 — Billing Schema
--
-- Idempotent (uses IF NOT EXISTS throughout). Apply AFTER 009_accounts_identity.sql.
--
-- Adds three billing tables (subscriptions, stripe_events, entitlement_cache)
-- and two additive nullable/defaulted columns on users (plan, plan_updated_at).
-- No existing table is otherwise modified.
--
-- This migration is ADDITIVE and INERT: it creates structure only.  No Stripe
-- SDK calls, no checkout, no webhook handlers, no entitlement enforcement are
-- wired until later Phase 17 slices.  STRIPE_ENABLED=false throughout.
--
--   db_table_count: 35 → 38 (three new tables).
--
-- Design notes
--   * users.plan is a DENORMALISED cache of subscriptions.plan_name.
--     The subscriptions table is the authoritative billing source.
--     users.plan exists for fast entitlement reads and observability only.
--   * stripe_events has NO payload_json column.  Raw Stripe payloads may
--     contain PII.  Events are retrievable from Stripe by stripe_event_id.
--   * entitlement_cache is the per-user resolved plan+limits cache (1h TTL).
--     Cache misses fall back to live subscriptions query, then free tier.
--   * All PKs are VARCHAR(36) UUID strings, consistent with all other tables.
--   * Soft FKs (no DDL FK constraints) per codebase discipline.


-- ---------------------------------------------------------------------------
-- users — add plan + plan_updated_at (Phase 17 billing anchor)
-- ---------------------------------------------------------------------------
-- plan: denormalised billing-plan cache.  Default 'free' for all existing rows.
-- system user is updated to plan='system' below.
ALTER TABLE users
    ADD COLUMN IF NOT EXISTS plan VARCHAR(20) NOT NULL DEFAULT 'free';

ALTER TABLE users
    ADD COLUMN IF NOT EXISTS plan_updated_at TIMESTAMPTZ DEFAULT NULL;

-- Stamp system user with plan='system' (idempotent: no-op if already set).
UPDATE users
    SET plan = 'system'
    WHERE id  = '00000000-0000-0000-0000-000000000001'
      AND plan != 'system';


-- ---------------------------------------------------------------------------
-- 36. subscriptions  (one row per Stripe subscription lifecycle event)
-- ---------------------------------------------------------------------------
--
-- Invariant (application-enforced, not DB-level):
--   At most one row per user_id where status IN
--   ('active', 'trialing', 'past_due', 'paused').
--   Historical rows (canceled, lapsed) are retained for compliance.
--
-- status ∈ {active, trialing, past_due, canceled, paused, lapsed}
-- plan_name ∈ {free, pro, teams, institutional}
-- billing_interval ∈ {month, year, custom}

CREATE TABLE IF NOT EXISTS subscriptions (
    id                      VARCHAR(36)   NOT NULL,
    -- user_id: the subscriber (soft FK → users.id)
    user_id                 VARCHAR(36)   NOT NULL,
    -- org_id: Teams billing anchor (soft FK → organizations.id — Phase 18+)
    org_id                  VARCHAR(36)   DEFAULT NULL,
    -- Stripe binding columns
    stripe_subscription_id  VARCHAR(64)   NOT NULL,
    stripe_customer_id      VARCHAR(64)   NOT NULL,
    stripe_price_id         VARCHAR(64)   NOT NULL,
    -- plan_name: free | pro | teams | institutional
    plan_name               VARCHAR(20)   NOT NULL,
    -- billing_interval: month | year | custom (Institutional contracts)
    billing_interval        VARCHAR(10)   NOT NULL DEFAULT 'month',
    -- status lifecycle: active → past_due → lapsed; or active → canceled
    status                  VARCHAR(20)   NOT NULL,
    -- trial window (NULL when no trial)
    trial_ends_at           TIMESTAMPTZ   DEFAULT NULL,
    -- current billing period
    current_period_start    TIMESTAMPTZ   NOT NULL,
    current_period_end      TIMESTAMPTZ   NOT NULL,
    -- cancellation state
    cancel_at_period_end    BOOLEAN       NOT NULL DEFAULT FALSE,
    canceled_at             TIMESTAMPTZ   DEFAULT NULL,
    -- grace period for failed payments (set by invoice.payment_failed handler)
    grace_period_ends_at    TIMESTAMPTZ   DEFAULT NULL,
    -- seat_count: Syndicate/Teams seat billing quantity
    seat_count              INTEGER       NOT NULL DEFAULT 1,
    created_at              TIMESTAMPTZ   NOT NULL DEFAULT now(),
    updated_at              TIMESTAMPTZ   NOT NULL DEFAULT now(),

    PRIMARY KEY (id),
    CONSTRAINT uq_subscriptions_stripe_sub_id UNIQUE (stripe_subscription_id)
);

CREATE INDEX IF NOT EXISTS ix_subscriptions_user_id
    ON subscriptions (user_id);

CREATE INDEX IF NOT EXISTS ix_subscriptions_status
    ON subscriptions (status);

CREATE INDEX IF NOT EXISTS ix_subscriptions_stripe_customer_id
    ON subscriptions (stripe_customer_id);


-- ---------------------------------------------------------------------------
-- 37. stripe_events  (webhook idempotency table)
-- ---------------------------------------------------------------------------
--
-- Dedup key: stripe_event_id (UNIQUE).  The webhook handler checks this
-- column before processing; replay returns 200 without re-running handlers.
--
-- NO payload_json column: raw Stripe event data may contain PII (email,
-- billing address, card last-4).  Retrieve the full event from Stripe's
-- dashboard or API by stripe_event_id for debugging.
--
-- processing_status ∈ {pending, ok, error, skipped}

CREATE TABLE IF NOT EXISTS stripe_events (
    id                VARCHAR(36)   NOT NULL,
    -- stripe_event_id: evt_* from Stripe — the global dedup key
    stripe_event_id   VARCHAR(64)   NOT NULL,
    -- event_type: e.g. customer.subscription.updated, invoice.paid
    event_type        VARCHAR(80)   NOT NULL,
    -- processing_status: pending | ok | error | skipped
    processing_status VARCHAR(20)   NOT NULL DEFAULT 'pending',
    -- error_detail: populated only when processing_status='error'
    error_detail      TEXT          DEFAULT NULL,
    -- processed_at: timestamp when the handler completed (or failed)
    processed_at      TIMESTAMPTZ   NOT NULL DEFAULT now(),
    created_at        TIMESTAMPTZ   NOT NULL DEFAULT now(),

    PRIMARY KEY (id),
    CONSTRAINT uq_stripe_events_stripe_event_id UNIQUE (stripe_event_id)
);

CREATE INDEX IF NOT EXISTS ix_stripe_events_event_type
    ON stripe_events (event_type);

CREATE INDEX IF NOT EXISTS ix_stripe_events_processing_status
    ON stripe_events (processing_status);


-- ---------------------------------------------------------------------------
-- 38. entitlement_cache  (per-user resolved plan limits, 1h TTL)
-- ---------------------------------------------------------------------------
--
-- PK is user_id — one cache row per user.
-- Invalidated on every subscription lifecycle event.
-- Cache miss → recompute from subscriptions → free fallback on error.
--
-- dossier_monthly_limit = -1 means unlimited.
-- features_json: JSON object of boolean feature flags per spec §3.3.

CREATE TABLE IF NOT EXISTS entitlement_cache (
    -- PK is user_id — one row per user
    user_id               VARCHAR(36)   NOT NULL,
    -- plan_name: the resolved plan (may differ from users.plan during grace)
    plan_name             VARCHAR(20)   NOT NULL,
    plan_status           VARCHAR(20)   NOT NULL,
    -- resource limits: -1 = unlimited
    watchlist_limit       INTEGER       NOT NULL,
    portfolio_limit       INTEGER       NOT NULL,
    position_limit        INTEGER       NOT NULL,
    dossier_monthly_limit INTEGER       NOT NULL,
    -- features_json: serialised boolean feature flags (JSON text)
    features_json         TEXT          NOT NULL DEFAULT '{}',
    -- trial_days_remaining: NULL when not in trial
    trial_days_remaining  INTEGER       DEFAULT NULL,
    computed_at           TIMESTAMPTZ   NOT NULL,
    -- expires_at: cache row is stale after this timestamp (TTL = 1h)
    expires_at            TIMESTAMPTZ   NOT NULL,

    PRIMARY KEY (user_id)
);
