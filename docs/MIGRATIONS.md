# Database Migrations (Alembic)

ClearSignal uses **Alembic** for versioned, reviewed, reversible schema changes.
As of Sprint 1A the application **no longer creates or alters the schema at
startup** — migrations are an explicit deployment step.

## Architecture: before → after

**Before**
- `init_db()` ran `Base.metadata.create_all()` on every boot (created missing
  tables, but could not alter existing ones).
- The app lifespan ran an idempotent `ALTER TABLE delivery_ledger …` block to
  patch columns `create_all` couldn't add — schema mutation on every boot, no
  history, no review, no rollback.

**After**
- Schema lives in versioned migrations under `alembic/versions/`.
- `alembic upgrade head` (a deploy step) brings any database to the current schema.
- Startup only **verifies** status (read-only) and logs a loud warning if the DB
  is behind head or unmanaged. It issues **no DDL**.

## Migration files

| Revision | Purpose | Reversible? |
|---|---|---|
| `0001_baseline` | Adopt the full current schema via `create_all(checkfirst=True)` — idempotent (creates on a fresh DB, no-op on an existing one). | Downgrade **DROPS ALL TABLES** — destructive; test/disposable DBs only. |
| `0002_delivery_ledger_severity` | Versioned replacement for the Phase 10C lifespan ALTER: adds `canonical_severity`, `severity_rank`, and index `ix_delivery_ledger_canonical_severity`. Idempotent (introspects first). | Downgrade drops the two columns + index. Rows preserved; the **column values are discarded**. |
| `0003_users_billing_columns` | Adds missing `users.plan` and `users.plan_updated_at` columns on legacy databases, defaults existing users to `free`, and restores the system user's `system` plan. | Downgrade drops the two columns. User rows remain, but plan values are discarded. |
| `0004_portfolios_org_id` | Adds the missing nullable `portfolios.org_id` compatibility column on legacy databases so account import can read the current Portfolio model. | Downgrade drops `org_id`. Portfolio rows remain. |

Because the delta migrations are idempotent, `alembic upgrade head` is safe to run on
any of the three database states below and converges them to the current schema.

## The three database states

| State | Action | Result |
|---|---|---|
| **New / empty DB** | `alembic upgrade head` | 0001 creates all tables, 0002 is a no-op → full current schema. |
| **Existing DB already matching the schema** (created by the old `create_all` path, columns present) | `alembic stamp head` *(preferred)*, or `alembic upgrade head` (safe: every op is idempotent) | DB marked at head; no data touched. |
| **Legacy DB missing the 10C columns** | `alembic upgrade head` | 0001 no-ops (tables exist), 0002 adds the missing columns + index. No rows lost. |

> Prefer `stamp head` for a known-current DB — it records the revision without
> running any DDL.

## Commands

```bash
alembic upgrade head        # apply all migrations (THE deploy step)
alembic current             # show the DB's current revision
alembic history --verbose   # show migration history
alembic stamp head          # mark an already-current DB without running DDL
alembic downgrade -1        # revert one revision (mind the irreversible notes)
```

The database URL is resolved by `alembic/env.py` from `DATABASE_URL`
(environment / `.env`) — it is **not** stored in `alembic.ini`.

## Pre-deploy procedure

1. **Back up the database** (managed-Postgres snapshot or `pg_dump`). This is the
   real rollback for any destructive/irreversible change.
2. Review the pending migrations: `alembic history` and `git diff` the new
   revision files.
3. Put the service in maintenance / drain if the migration is not
   backward-compatible with the currently running code (the two migrations here
   are additive and backward-compatible, so zero-downtime is fine).
4. Run the migration as a release step **before** the new app version serves
   traffic:
   ```bash
   DATABASE_URL=... alembic upgrade head
   ```
5. Deploy the app. On boot, `init_db` logs `schema up-to-date at Alembic head …`;
   if you see `schema is BEHIND head` or `NOT under Alembic control`, stop and run
   the migration.

For a first-time adoption on the existing production DB, use `alembic stamp head`
once (the schema already matches), then normal `upgrade head` on subsequent deploys.

## Rollback procedure

1. **Preferred: restore the pre-deploy backup** (always safe, always complete).
2. **Schema rollback for reversible steps:**
   ```bash
   alembic downgrade -1      # or: alembic downgrade <revision>
   ```
   - `0002` downgrade is reversible for **structure** but **discards** the values
     in `canonical_severity` / `severity_rank` (no rows lost).
   - `0001` downgrade **drops every table** — never run against a DB with real
     data; restore from backup instead.
3. Redeploy the previous app version.

## Failed-migration recovery

If `alembic upgrade head` fails partway:

1. **Do not run the app against a partially-migrated DB.** Startup will warn
   `BEHIND head`; keep the previous app version serving (its code is compatible
   with the pre-migration schema for additive changes).
2. Inspect state: `alembic current` (last good revision) and the migration error.
3. Fix-forward (preferred): correct the migration and re-run `alembic upgrade
   head` — the two migrations here are idempotent, so re-running is safe.
4. If the DB is left inconsistent and cannot be fixed forward: **restore the
   pre-deploy backup** and retry.
5. Postgres note: Alembic wraps each migration in a transaction, so a failing
   migration on Postgres rolls back cleanly. SQLite (dev/tests) runs
   non-transactional DDL — recover disposable SQLite DBs by recreating them.

## Irreversible / lossy operations (call these out in review)

- **`0001` downgrade** → `drop_all()` (all data lost). Disposable DBs only.
- **`0002` downgrade** → drops `canonical_severity` / `severity_rank` (those
  column values are lost; rows are not).
- **`0003` downgrade** → drops `users.plan` / `users.plan_updated_at` (those
  column values are lost; user rows are not).

Any future migration that drops a column/table, narrows a type, or backfills with
data loss **must** document it here and be preceded by a backup.

## Adding a new migration

```bash
# after editing app/db/models.py:
DATABASE_URL=... alembic revision --autogenerate -m "describe change"
# review the generated file (autogenerate is a draft, not gospel), then:
DATABASE_URL=... alembic upgrade head
```

`alembic/env.py` sets `target_metadata = Base.metadata` and `compare_type=True`
so autogenerate diffs against the models. Always hand-review the generated script,
especially for data-affecting operations, and add a test in
`tests/test_alembic_migrations.py`.
