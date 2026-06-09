-- Phase 9B — Add user_id and future-proof identity columns
--
-- Idempotent: uses IF NOT EXISTS / IF column does not already exist pattern.
-- Apply AFTER 001_initial.sql on a live database.
--
-- Changes:
--   thesis_versions      — add user_id, widen session_id to VARCHAR(64)
--   memory_entries       — add user_id, widen session_id to VARCHAR(64)
--   personalized_insights— add user_id
--   thesis_deltas        — add debounce_visible (feed deduplication flag)
--
-- user_id is NULL by default (anonymous sessions).  Populated once the
-- frontend generates and persists a stable UUID per authenticated user
-- (Phase 9C Watchlist Intelligence).

-- ---------------------------------------------------------------------------
-- thesis_versions — add user_id
-- ---------------------------------------------------------------------------
ALTER TABLE thesis_versions
    ADD COLUMN IF NOT EXISTS user_id VARCHAR(64) DEFAULT NULL;

CREATE INDEX IF NOT EXISTS ix_thesis_versions_user_id
    ON thesis_versions (user_id)
    WHERE user_id IS NOT NULL;

-- ---------------------------------------------------------------------------
-- memory_entries — add user_id
-- ---------------------------------------------------------------------------
ALTER TABLE memory_entries
    ADD COLUMN IF NOT EXISTS user_id VARCHAR(64) DEFAULT NULL;

CREATE INDEX IF NOT EXISTS ix_memory_entries_user_id
    ON memory_entries (user_id)
    WHERE user_id IS NOT NULL;

-- ---------------------------------------------------------------------------
-- personalized_insights — add user_id
-- ---------------------------------------------------------------------------
ALTER TABLE personalized_insights
    ADD COLUMN IF NOT EXISTS user_id VARCHAR(64) DEFAULT NULL;

CREATE INDEX IF NOT EXISTS ix_personalized_insights_user_id
    ON personalized_insights (user_id)
    WHERE user_id IS NOT NULL;

-- ---------------------------------------------------------------------------
-- thesis_deltas — add debounce_visible for material feed deduplication
--
-- When two material deltas arrive for the same ticker on the same calendar
-- day (UTC), the one with the smaller |conviction_delta| is marked
-- debounce_visible = FALSE and excluded from the material change feed.
-- The delta row is retained for audit; only feed visibility is suppressed.
-- ---------------------------------------------------------------------------
ALTER TABLE thesis_deltas
    ADD COLUMN IF NOT EXISTS debounce_visible BOOLEAN NOT NULL DEFAULT TRUE;

CREATE INDEX IF NOT EXISTS ix_thesis_deltas_feed
    ON thesis_deltas (magnitude, created_at DESC)
    WHERE debounce_visible = TRUE;
