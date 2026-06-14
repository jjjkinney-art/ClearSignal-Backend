-- Phase 16 · Slice 1 — Accounts & Identity Schema
--
-- Idempotent (uses IF NOT EXISTS throughout). Apply AFTER 008_portfolio_intelligence.sql.
--
-- Introduces the identity layer: four new tables that form the canonical
-- user identity model (users, user_profiles, user_settings, audit_log).
-- Also adds a forward-compat org_id column to portfolios so the Teams
-- sharing model (Phase 16 §8.2) needs no future schema rework.
--
-- This migration is ADDITIVE and INERT: it creates four new tables and
-- adds one nullable column to portfolios.  No existing table is otherwise
-- modified.  No auth behavior changes until later Phase 16 slices.
--
--   db_table_count: 31 → 35 (four new tables).
--
-- Design notes
--   * users.id is a VARCHAR(36) UUID string, consistent with all other PKs.
--   * user_profiles.user_id and user_settings.user_id are the PK (1:1 with users).
--   * audit_log is append-only: no UPDATE or DELETE path will ever exist in
--     any repository.
--   * stripe_customer_id and org_id are nullable placeholders, written
--     day-one so no future ALTER is needed (spec §8.1/§8.2).
--   * account_type ∈ {individual, team_member, institutional, system}.
--     The system user (00000000-0000-0000-0000-000000000001) uses 'system'.
--   * No password column anywhere in this migration (Phase 16 imperative:
--     Supabase Auth is the sole credential custodian).
--   * Soft FKs (no DDL FK constraints) consistent with the existing
--     no-FK-by-design discipline across this codebase.


-- ---------------------------------------------------------------------------
-- 32. users  (canonical identity record — one per Supabase account)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS users (
    id                  VARCHAR(36)   NOT NULL,
    -- email: case-folded at write time; UNIQUE enforces one account per address.
    email               VARCHAR(320)  NOT NULL,
    email_verified      BOOLEAN       NOT NULL DEFAULT FALSE,
    -- account_type: individual | team_member | institutional | system
    account_type        VARCHAR(20)   NOT NULL DEFAULT 'individual',
    is_active           BOOLEAN       NOT NULL DEFAULT TRUE,
    -- stripe_customer_id: forward-compat Stripe placeholder (spec §8.1).
    -- Nullable; never written in Phase 16 build slices.
    stripe_customer_id  VARCHAR(64)   DEFAULT NULL,
    -- auth_subject: Supabase JWT 'sub' claim; the binding between this row
    -- and the identity provider.  Nullable until Supabase is wired (Slice 3).
    auth_subject        VARCHAR(255)  DEFAULT NULL,
    last_sign_in_at     TIMESTAMPTZ   DEFAULT NULL,
    created_at          TIMESTAMPTZ   NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ   NOT NULL DEFAULT now(),

    PRIMARY KEY (id),
    CONSTRAINT uq_users_email          UNIQUE (email),
    CONSTRAINT uq_users_auth_subject   UNIQUE (auth_subject),
    CONSTRAINT uq_users_stripe_cust_id UNIQUE (stripe_customer_id)
);

CREATE INDEX IF NOT EXISTS ix_users_account_type   ON users (account_type);
CREATE INDEX IF NOT EXISTS ix_users_is_active       ON users (is_active);
-- Partial unique index: stripe_customer_id when non-NULL (DDL version of
-- the application-level uniqueness; nulls are excluded automatically in
-- PostgreSQL partial indexes, avoiding the NULL != NULL edge case).
CREATE UNIQUE INDEX IF NOT EXISTS uix_users_stripe_customer_id_nn
    ON users (stripe_customer_id)
    WHERE stripe_customer_id IS NOT NULL;


-- ---------------------------------------------------------------------------
-- 33. user_profiles  (display + onboarding state — 1:1 with users)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS user_profiles (
    -- PK is the user_id — strict 1:1 with users.
    user_id              VARCHAR(36)   NOT NULL,
    display_name         VARCHAR(200)  DEFAULT NULL,
    timezone             VARCHAR(64)   NOT NULL DEFAULT 'UTC',
    locale               VARCHAR(10)   NOT NULL DEFAULT 'en',
    -- onboarding_step: pending | watchlist | portfolio | briefing | complete
    onboarding_step      VARCHAR(30)   NOT NULL DEFAULT 'pending',
    onboarding_completed_at TIMESTAMPTZ DEFAULT NULL,
    created_at           TIMESTAMPTZ   NOT NULL DEFAULT now(),
    updated_at           TIMESTAMPTZ   NOT NULL DEFAULT now(),

    PRIMARY KEY (user_id)
);


-- ---------------------------------------------------------------------------
-- 34. user_settings  (briefing + delivery + UI preferences — 1:1 with users)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS user_settings (
    -- PK is the user_id — strict 1:1 with users.
    user_id              VARCHAR(36)   NOT NULL,
    -- briefing_time_utc: hour (0–23) for daily briefing delivery.
    briefing_time_utc    INTEGER       NOT NULL DEFAULT 7,
    quiet_hours_start    INTEGER       NOT NULL DEFAULT 22,
    quiet_hours_end      INTEGER       NOT NULL DEFAULT 7,
    -- delivery_channel: in_app | email | push
    delivery_channel     VARCHAR(40)   NOT NULL DEFAULT 'in_app',
    digest_enabled       BOOLEAN       NOT NULL DEFAULT TRUE,
    -- theme: light | dark | system
    theme                VARCHAR(20)   NOT NULL DEFAULT 'system',
    created_at           TIMESTAMPTZ   NOT NULL DEFAULT now(),
    updated_at           TIMESTAMPTZ   NOT NULL DEFAULT now(),

    PRIMARY KEY (user_id)
);


-- ---------------------------------------------------------------------------
-- 35. audit_log  (append-only mutation trail — NEVER updated or deleted)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS audit_log (
    id           VARCHAR(36)   NOT NULL,
    -- user_id: the actor (may be the system user UUID).
    user_id      VARCHAR(36)   DEFAULT NULL,
    -- resource: the entity type (e.g. 'portfolio', 'watchlist', 'user').
    resource     VARCHAR(60)   NOT NULL DEFAULT '',
    -- resource_id: the entity PK.
    resource_id  VARCHAR(200)  DEFAULT NULL,
    -- action: create | update | delete | import | export | login | logout
    action       VARCHAR(40)   NOT NULL DEFAULT '',
    ip_address   VARCHAR(45)   DEFAULT NULL,   -- IPv4 or IPv6
    user_agent   TEXT          DEFAULT NULL,
    -- created_at is immutable — this row is never updated.
    created_at   TIMESTAMPTZ   NOT NULL DEFAULT now(),

    PRIMARY KEY (id)
);

-- Compliance query index: all events for a user ordered by time.
CREATE INDEX IF NOT EXISTS ix_audit_log_user_id_created_at
    ON audit_log (user_id, created_at);
-- Compliance query index: all events on a specific resource.
CREATE INDEX IF NOT EXISTS ix_audit_log_resource_resource_id
    ON audit_log (resource, resource_id);


-- ---------------------------------------------------------------------------
-- portfolios — add org_id forward-compat column (spec §8.2)
-- ---------------------------------------------------------------------------
-- org_id is the future Teams sharing anchor.  Added as a nullable placeholder
-- day-one so the Teams membership model (Phase 16 §8.2) needs no future ALTER.
-- No organizations table is created in Phase 16; this column is inert.
ALTER TABLE portfolios
    ADD COLUMN IF NOT EXISTS org_id VARCHAR(36) DEFAULT NULL;

CREATE INDEX IF NOT EXISTS ix_portfolios_org_id
    ON portfolios (org_id)
    WHERE org_id IS NOT NULL;
