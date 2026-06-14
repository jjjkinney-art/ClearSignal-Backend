# Accounts & Identity — Implementation Plan

**Phase:** 16 · the identity layer
**Source of truth:** `docs/PHASE_16_ACCOUNTS_SPEC.md` (approved — this plan does not redesign anything)
**Status:** Execution blueprint — no code in this document
**Convention basis:** All file paths, flags, migration discipline, and `db_table_count` guards reference the existing codebase (9A persistence, 10A loop, 10B watchlist, 10C delivery, 10D portfolio). Phase 16 reuses the existing nullable `user_id VARCHAR(64)` columns across 18 tables **wholesale** — no column type changes anywhere. It adds a canonical `users` identity record, a Supabase-issued JWT verification middleware, an append-only audit trail, a system-user ownership model for pre-16 data, and a one-time claim/import path. **It writes no new analysis and changes no intelligence behavior.**

---

## PART 1 — BUILD SLICES

Nine slices. Each is independently shippable, independently revertible, and leaves production in a working state if the next slice never lands. The slicing rule, carried from 10C/10D and adapted for an identity layer that sits *under* every existing feature: **identity before auth, auth-in-bypass before auth-enforced, system-ownership before user-ownership, and claim before NOT-NULL.** Nothing that *enforces* a token lands until the middleware that *verifies* one has run in bypass; nothing that *requires* `user_id` lands until every legacy NULL row has been claimed.

> **Standing safety property.** Every slice through Slice 8 lands with `AUTH_ENABLED=false` (the JWT middleware present but in bypass — it injects the `SYSTEM_DEFAULT_USER_ID` as `request.state.user_id` and never returns 401). The platform behaves exactly as the single-user system it is today while the entire accounts stack is built, seeded, and observed behind the bypass. The consequential flip to `AUTH_ENABLED=true` is a **config sequence in PART 7**, never a slice. This is 10C/10D's "build the whole stack in shadow, flip one flag at the end" discipline, applied to authentication.

> **The non-destructive imperative.** No migration in Phase 16 ever deletes, reassigns-away, or NULLs an existing user-owned row as a side effect. Legacy NULL rows are *claimed* by a well-known system user via additive `UPDATE ... WHERE user_id IS NULL` (Slice 4); real-user import is an explicit, one-time, opt-in `UPDATE ... WHERE user_id = SYSTEM_DEFAULT_USER_ID` guarded by a `claimed_at` sentinel (Slice 6). `NOT NULL` enforcement is the *last* structural change and only after a 30-day soak (PART 7). At every point before that, a full revert restores the prior single-user behavior with zero data loss.

> **The no-password imperative.** ClearSignal stores no password hash, salt, or credential anywhere in the application layer. Supabase Auth is the sole credential custodian. Magic link is primary, Google OAuth secondary. The backend only ever *verifies* a signed JWT — it never issues, hashes, or stores a secret. Any slice that introduces a password column or a bcrypt call violates the spec and is rejected at the gate.

---

### Slice 1 — Identity schema & CRUD (no auth, no enforcement)

**Objective:** Create the four new Phase 16.0 tables empty in production and expose pure user/profile/settings CRUD via the repository layer. The identity records can exist and be read; nothing authenticates against them yet, nothing enforces ownership. Zero behavioral change.

**Files:**
- `app/db/migrations/009_accounts.sql` (new — `CREATE TABLE IF NOT EXISTS` for `users`, `user_profiles`, `user_settings`, `audit_log`; all indexes per PART 2; `stripe_customer_id` and `org_id` placeholder columns included as nullable from day one so no later ALTER is needed)
- `app/db/models.py` (append ORM: `User`, `UserProfile`, `UserSettings`, `AuditLog`; mirror existing column conventions — `id VARCHAR(36)` UUID PK, `created_at`/`updated_at`, soft-state via `is_active`)
- `app/db/repositories/user_repo.py` (new — `create_user`, `get_user`, `get_user_by_email`, `update_user`, `deactivate_user`; `upsert_profile`, `get_profile`; `upsert_settings`, `get_settings`; null-object on `session=None`)
- `app/startup.py` (extend the migration registration comment block + the `db_table_count` before/after guard, the 10A–10D precedent; **table count 31 → 35**)

**Dependencies:** none new — reuses the existing 9A DB connection, session, and ORM conventions.

**Validation:** `db_table_count` rises by 4 (31 → 35) on `/health`; app boots clean; all existing tests pass untouched; migration idempotent (run twice — no error, no duplicate index). Unit: create→read→update→deactivate round-trip for a user; `get_user_by_email` is case-insensitive and unique; profile and settings upserts are 1:1 with the user and idempotent; `stripe_customer_id` and `org_id` accept NULL. `validate_10d_portfolio_shadow.py` still green (no regression to the 10D surface).

**Rollback strategy:** None needed — additive `IF NOT EXISTS` DDL, all unread by any auth layer. Tables inert without later slices. Revert = remove the CRUD repo; the tables sit empty and harmless. No request path touches them.

---

### Slice 2 — System user seed + NULL-ownership backfill (idempotent)

**Objective:** Create the single well-known `SYSTEM_DEFAULT_USER` row and claim every legacy NULL `user_id` row for it, in one idempotent startup pass. After this slice, every user-scoped row in the database has a non-NULL owner — but the column is still nullable and nothing enforces it. This is the load-bearing data-safety slice.

**Files:**
- `app/services/system_user_service.py` (new — `ensure_system_user()` inserts the fixed `SYSTEM_DEFAULT_USER_ID` row if absent, `account_type='system'`, idempotent; `claim_orphan_rows()` runs the additive `UPDATE ... SET user_id = SYSTEM_DEFAULT_USER_ID WHERE user_id IS NULL` across the eight user-scoped tables per spec §5.2; both wrapped non-fatal)
- `app/config.py` (add `SYSTEM_DEFAULT_USER_ID` default `00000000-0000-0000-0000-000000000001` per spec Appendix B)
- `app/main.py` (extend the lifespan startup — after the 10D portfolio sync block, call `ensure_system_user()` then `claim_orphan_rows()`; mirrors the existing idempotent-backfill blocks, non-fatal on error, logs claimed-row counts per table)

**Dependencies:** Slice 1. Reads/writes only the existing user-scoped tables (`watched_tickers`, `portfolios`, `user_delivery_prefs`, `digest_batches`, `thesis_versions`, `memory_entries`, `personalized_insights`, `briefing_sessions`).

**Validation:** Unit: `ensure_system_user` inserts once, second call is a no-op (idempotent on the fixed UUID); `claim_orphan_rows` converts a seeded set of NULL rows to system-owned and leaves already-owned rows untouched; re-run claims zero additional rows. Integration: boot against a DB snapshot with NULL-owned watchlist + portfolio + prefs → all become `SYSTEM_DEFAULT_USER`-owned, counts logged, second boot claims nothing. **Data-safety gate:** assert no row count changes in any table (claim is `UPDATE`, never `DELETE`/`INSERT`); assert `SELECT COUNT(*) WHERE user_id IS NULL = 0` after the pass across all eight tables.

**Rollback strategy:** The claim is additive and reversible — a revert SQL `UPDATE ... SET user_id = NULL WHERE user_id = SYSTEM_DEFAULT_USER_ID` restores the prior NULL state exactly (the system user owns *only* what it claimed, so the inverse is precise). No data is lost in either direction. The system user row itself is harmless if left behind.

---

### Slice 3 — JWT verification middleware (present, in bypass)

**Objective:** Land the Supabase JWT verification middleware and the `require_auth` / `require_admin` FastAPI dependencies, with the master switch `AUTH_ENABLED=false`. In bypass, the middleware injects `SYSTEM_DEFAULT_USER_ID` as `request.state.user_id` and never rejects a request. The verification path is fully built and unit-tested but inert. No route is protected yet.

**Files:**
- `app/middleware/auth.py` (new — `extract_token(request)`, `verify_jwt(token)` validating signature against Supabase JWKS (in-memory cached, 1h TTL) + `exp`/`aud`/`iss` per spec §6.1; on `AUTH_ENABLED=false` short-circuits to the system identity)
- `app/dependencies/auth.py` (new — `require_auth` returns the verified `UserIdentity` or 401; `require_admin` additionally checks the `app_metadata.role='admin'` claim or 403; both honor the bypass switch)
- `app/config.py` (add `AUTH_ENABLED` default `false`, `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_JWT_SECRET`, `MAGIC_LINK_REDIRECT_URL` per spec Appendix B; secrets never logged)
- `app/main.py` (register the auth middleware in the app factory, ordered after CORS per spec §6.1)

**Dependencies:** Slice 2 (the bypass identity must exist). No route changes — middleware is registered but every route is still effectively public.

**Validation:** Unit (the defining tests): a valid Supabase-shaped JWT verifies and yields the correct `sub`→`user_id`; an expired token, a wrong-`aud` token, and a bad-signature token each fail closed; with `AUTH_ENABLED=false` every request — even with no token — resolves to `SYSTEM_DEFAULT_USER_ID` and no 401 is ever raised; with `AUTH_ENABLED=true` a missing token on a `require_auth` route yields 401 with the spec §6.1 generic body (no resource disclosure). JWKS cache: a key-rotation scenario re-fetches after TTL without a request failure. Integration: boot with `AUTH_ENABLED=false` → all existing endpoints behave identically to pre-16; `validate_10d_portfolio_shadow.py` still green.

**Rollback strategy:** Middleware is inert in bypass. Revert = remove the middleware registration; identity falls back to the existing implicit-global behavior. No secret is stored; removing env vars is sufficient cleanup. Because nothing is protected yet, reverting is invisible to clients.

---

### Slice 4 — Auth routes + Supabase wiring (proxy only, still bypassed)

**Objective:** Expose the thin backend auth surface — a magic-link proxy and a token-refresh passthrough — and document the Supabase project configuration. The backend never sees a credential; it forwards to Supabase and handles the returned JWT. Routes exist and function end-to-end against a configured Supabase project, but the rest of the app is still in `AUTH_ENABLED=false` bypass.

**Files:**
- `app/api/auth.py` (new — `POST /auth/magic-link` proxies the Supabase magic-link request; `POST /auth/token/refresh` exchanges the refresh-token cookie for a new access token; `POST /auth/logout` revokes the refresh token via Supabase `signOut`; all public routes, no `require_auth`)
- `app/api.py` (extend — mount the auth router; add `/auth/*` to the public-route allowlist per spec §4.3)
- `docs/PHASE_16_SUPABASE_SETUP.md` (new — operator runbook: create Supabase project, enable magic link, configure Google OAuth (scopes `email`,`profile` only per spec §8.3), set redirect URL, copy `SUPABASE_URL`/`ANON_KEY`/`JWT_SECRET` into Render env, configure SMTP relay (Resend/SendGrid) for deliverability per spec risk table)

**Dependencies:** Slice 3 (JWT verification must exist to validate what Supabase returns). Requires a live Supabase project (operator task in the runbook).

**Validation:** Integration against a staging Supabase project: `POST /auth/magic-link` triggers a delivered email; clicking the link yields a valid JWT that `verify_jwt` accepts; `POST /auth/token/refresh` rotates the access token and invalidates the old refresh token (spec §6.4); `POST /auth/logout` revokes server-side. Public-route check: all three `/auth/*` endpoints respond without a bearer token. Rate-limit smoke: the magic-link endpoint honors the 5 req/min/IP cap (spec §6.5) at the proxy layer. No credential ever appears in backend logs (assert via log scan in the test harness).

**Rollback strategy:** Revert = unmount the auth router. Supabase project remains configured but unused. No data written, no enforcement active. Clients see the routes disappear; no existing flow breaks because nothing depends on them yet.

---

### Slice 5 — Ownership-scoped reads/writes (system-owned, pre-enforcement)

**Objective:** Thread `request.state.user_id` through every user-scoped service and repository so reads filter by owner and writes stamp the owner. With `AUTH_ENABLED=false` every request still resolves to `SYSTEM_DEFAULT_USER_ID`, so behavior is unchanged — but the *plumbing* for per-user isolation is now complete and exercised end-to-end under the system identity.

**Files:**
- `app/db/repositories/portfolio_repo.py` (extend — every read accepts and filters by `user_id`; every write stamps `user_id`; `portfolio_positions`/`portfolio_insights` inherit ownership via `portfolio_id` per spec §4.2)
- `app/db/repositories/watchlist_repo.py` (extend — `ticker_add`/`list`/`remove` accept and filter by `user_id` per spec §4.2)
- `app/db/repositories/delivery_prefs_repo.py` (extend — prefs keyed by `user_id`; copy-on-first-access from the system-user defaults per spec §4.2)
- `app/api.py` (extend — every user-scoped route gains the `require_auth` dependency injecting `user_id`; admin routes gain `require_admin`; the public/authenticated/admin tiering per spec §4.3 is now wired, though enforcement is still bypassed)
- `app/services/*` (extend the portfolio, watchlist, delivery, and briefing services to pass `user_id` from the request context into their repo calls — no logic change, parameter threading only)

**Dependencies:** Slices 2–3. Touches the read/write surface of every user-scoped feature but changes no business logic.

**Validation:** Unit: each repo read returns only rows matching the supplied `user_id`; each write stamps the supplied `user_id`; a cross-user read (user A requesting user B's portfolio id) returns empty/403 in the repo layer regardless of the `AUTH_ENABLED` switch. Integration under bypass: every existing endpoint behaves identically to pre-16 because all traffic resolves to the system user — `validate_10d_portfolio_shadow.py` and `validate_10c_delivery_shadow.py` both still green. **Isolation gate (pre-flip dry run):** flip `AUTH_ENABLED=true` in a test harness with two seeded users → user A cannot read, modify, or delete any of user B's portfolios/watchlist/prefs/inbox (HTTP 403, no resource disclosure per spec §4.3); flip back to bypass for production.

**Rollback strategy:** The `user_id` threading is additive and inert under bypass. Revert = drop the `require_auth` dependencies and the parameter threading; all traffic returns to implicit-global. No data shape changes, so reverting is a pure code revert with no migration. The hardest slice to build but among the safest to revert because the system identity makes it a no-op until the flag flips.

---

### Slice 6 — One-time data import/claim (opt-in, sentinel-guarded)

**Objective:** Let the **first real user** optionally claim the system-owned watchlist and portfolios as their own, via an explicit, idempotent, race-safe operation. This is the bridge from single-user data to a real account. The claim is opt-in, one-time, and reversible until enforcement.

**Files:**
- `app/services/data_claim_service.py` (new — `claim_system_data(new_user_id)` runs the additive `UPDATE ... SET user_id = :new_user_id WHERE user_id = SYSTEM_DEFAULT_USER_ID` across `watched_tickers`, `portfolios`, `user_delivery_prefs` per spec §5.3; **excludes** `thesis_versions`/`memory_entries`/`briefing_sessions` which stay on the system user as an audit trail; guarded by a `claimed_at` sentinel on the system-user row to prevent the §5.3 race; returns a count summary or "nothing to import")
- `app/db/repositories/user_repo.py` (extend — `mark_system_data_claimed(by_user_id, at)` sets the sentinel atomically with `WHERE claimed_at IS NULL` so concurrent claims resolve to exactly one winner)
- `app/api/auth.py` (extend — `POST /auth/import-existing-data` calls the claim for the authenticated user; returns the import summary for the onboarding screen; requires `require_auth`)

**Dependencies:** Slices 2 + 5. Operates on system-owned rows produced by Slice 2.

**Validation:** Unit: a first claim moves all system-owned watchlist/portfolio/prefs rows to the new user and stamps `claimed_at`; a second claim (same or different user) finds the sentinel set and returns "nothing to import" with zero row changes; `thesis_versions`/`memory_entries`/`briefing_sessions` are **never** re-owned (audit-trail invariant). **Race gate:** two concurrent `claim_system_data` calls resolve to exactly one winner via the `WHERE claimed_at IS NULL` atomic guard — the loser gets the graceful "no data to import" path, never an error (spec §5.3 race mitigation). Integration: sign up a synthetic first user → import → their account shows the previously-global watchlist and portfolios; system user now owns zero watchlist/portfolio rows.

**Rollback strategy:** The claim is a precise `UPDATE` with an exact inverse (`SET user_id = SYSTEM_DEFAULT_USER_ID WHERE user_id = :that_user AND <claimed in this op>`); the `claimed_at` sentinel can be reset by an admin to re-open import. No row is created or destroyed. If the slice is reverted entirely, the import endpoint disappears and data stays wherever it currently sits — harmless under bypass.

---

### Slice 7 — Onboarding state machine + audit trail wiring

**Objective:** Drive the spec §7 sign-up→onboarding flow server-side and begin writing the append-only `audit_log` on every user-scoped mutation. Onboarding state advances through the four steps; every create/update/delete on a user resource leaves a compliance record. Still under bypass — exercised with the system user.

**Files:**
- `app/services/user_onboarding_service.py` (new — the §7.1 state machine: `pending → watchlist → portfolio → briefing → complete`; `advance_onboarding(user_id, step)`; reads/writes `user_profiles.onboarding_step`; idempotent advances)
- `app/services/audit_service.py` (new — `record(user_id, resource, resource_id, action, ip, user_agent)` appends an `audit_log` row per spec §6.6; append-only, never updates or deletes; non-fatal on write failure so it can never block a user action)
- `app/api.py` (extend — wire `audit_service.record` into every POST/PUT/PATCH/DELETE on user-scoped routes; add `GET /onboarding/state` and `POST /onboarding/advance`)
- `app/db/repositories/user_repo.py` (extend — `append_audit_log` write-once helper)

**Dependencies:** Slices 1 + 5. Audit wiring rides on the Slice 5 route surface.

**Validation:** Unit: the onboarding machine advances only forward through the four states, rejects skips that violate ordering, and is idempotent on re-advance; `audit_service.record` appends exactly one row per mutation with correct `resource`/`action`/`ip`; an audit write failure does not roll back or block the underlying user action (defense-in-depth, non-fatal). Integration: a full synthetic onboarding (profile→watchlist→portfolio→briefing) lands `onboarding_step='complete'` and an audit trail with one row per mutation. **Append-only gate:** assert the audit repo exposes no update/delete path (write-once by construction).

**Rollback strategy:** Onboarding state is advisory metadata; reverting leaves users at whatever step they reached with no functional impact. The audit log is additive and append-only; reverting stops new rows but loses no history. Neither touches the intelligence or delivery paths.

---

### Slice 8 — Observability & auth shadow validator

**Objective:** Make Phase 16 readiness *observable* and provide the production validation script — the 16-analogue of `validate_10d_portfolio_shadow.py`. Surfaces identity counts, claim state, auth-flag posture, and isolation-dry-run results without enabling enforcement.

**Files:**
- `app/services/accounts_observability_service.py` (new — null-safe, DB-down-safe snapshot per the 10C/10D observability precedent: `auth_flags` (`AUTH_ENABLED`, Supabase configured y/n — never the secret values), `users` count by `account_type`, `system_user` claim state (`claimed_at`, orphan-row counts across the eight tables), `audit_log` row count, `onboarding` step distribution, `safe_state`, `db_available`, `snapshot_utc`)
- `app/api.py` (extend — `GET /admin/accounts-status` delegating to the snapshot, `require_admin`; read-only, DB-down-safe per the `/admin/portfolio-status` precedent)
- `tests/validate_16_auth_shadow.py` (new — the deployment validator: `/health` ok + `db_table_count >= 35`; `/admin/accounts-status` 200 with `safe_state=true`; `AUTH_ENABLED=false` (or, in the enforced stage, the two-user isolation dry-run passes); system user present; zero orphan NULL `user_id` rows; no password column anywhere; Supabase configured; exits 0/1 on pass/fail per the 10C/10D script convention)
- `docs/PHASE_16_ACCOUNTS_ROLLOUT.md` (new — the operator rollout guide: env vars, safe defaults, how to run the validator, the staged flip sequence from PART 7, rollback steps, NOT-NULL gate criteria)

**Dependencies:** Slices 1–7. Reads everything the prior slices produced.

**Validation:** Unit: the snapshot is null-session safe (returns structurally complete zeros), DB-down-safe (degrades to zeros, never 500s), and exposes **no secret** (a key-scan test asserts `SUPABASE_JWT_SECRET`/`ANON_KEY` values never appear in the response, mirroring the 10D "no secrets exposed" gate). The validator passes against a clean staging deploy with `AUTH_ENABLED=false`. Production: `db_table_count = 35`, `safe_state=true`, system user present, zero orphan NULL rows, no password column detected.

**Rollback strategy:** Read-only admin GET + offline script. Revert = remove the endpoint and script; observability disappears but no behavior changes. The validator is the canary for the PART 7 flip; it is the last thing reverted, never the first.

---

## PART 2 — DATABASE / SCHEMA PLAN

### New tables (4) — all additive, no existing table modified

| # | Table | Purpose | Key columns |
|---|---|---|---|
| 32 | `users` | Canonical identity (1 per Supabase account) | `id` PK, `email` UNIQUE, `email_verified`, `account_type`, `is_active`, `stripe_customer_id` (NULL placeholder), `last_sign_in_at` |
| 33 | `user_profiles` | Display + onboarding state | `user_id` PK/FK, `display_name`, `timezone`, `locale`, `onboarding_step`, `onboarding_completed_at` |
| 34 | `user_settings` | Briefing/delivery/theme prefs | `user_id` PK/FK, `briefing_time_utc`, `quiet_hours_start/end`, `delivery_channel`, `digest_enabled`, `theme` |
| 35 | `audit_log` | Append-only mutation trail | `id` PK, `user_id` FK, `resource`, `resource_id`, `action`, `ip_address`, `user_agent`, `created_at` |

`db_table_count`: **31 → 35** (four new tables).

### Forward-compat columns shipped day one (no later ALTER)

- `users.stripe_customer_id VARCHAR(32) UNIQUE DEFAULT NULL` — the Stripe placeholder per spec §8.1 (designed, never written in Phase 16).
- `users.account_type VARCHAR(20) DEFAULT 'individual'` — accepts `'individual' | 'team_member' | 'institutional' | 'system'`; carries the future Teams/Institutional split per spec §8.2/§8.3.
- A nullable `org_id VARCHAR(36) DEFAULT NULL` is **added to `portfolios`** in `009_accounts.sql` (additive, unused) so the Teams sharing model per spec §8.2 needs no future schema rework. No `organizations` table is created in Phase 16.

### System-user ownership model

- One fixed row in `users`: `id = SYSTEM_DEFAULT_USER_ID` (`00000000-0000-0000-0000-000000000001`), `account_type='system'`, `email='system@clearsignal.internal'`. Seeded idempotently at startup (Slice 2).
- All eight legacy user-scoped tables have their NULL `user_id` rows claimed to this id (Slice 2), making every row owned before any enforcement.
- A `claimed_at TIMESTAMPTZ` sentinel (carried on the system-user row, or a dedicated single-row `system_claim_state` if a column on `users` is undesirable) gates the one-time real-user import against races (Slice 6).

### Claim / import model

- **System claim (Slice 2):** `UPDATE <table> SET user_id = SYSTEM_DEFAULT_USER_ID WHERE user_id IS NULL` — additive, idempotent, exact inverse exists.
- **User import (Slice 6):** `UPDATE <watchlist|portfolios|prefs> SET user_id = :new_user_id WHERE user_id = SYSTEM_DEFAULT_USER_ID`, atomic-guarded by `WHERE claimed_at IS NULL`. Analysis/memory/briefing history is deliberately excluded and retained on the system user.

### Migration

- Single additive migration `009_accounts.sql`, `CREATE TABLE IF NOT EXISTS` throughout, registered in `app/startup.py` with the before/after `db_table_count` guard (the 10A–10D precedent).
- `create_all()` at startup also materializes the ORM tables for SQLite test fixtures, mirroring the existing pattern; the SQL migration is the production path.
- **`NOT NULL` enforcement is a separate, later migration** (`010_user_id_not_null.sql`), applied only in PART 7 after the 30-day soak confirms zero orphan rows. It is the **only** constraint-adding migration in the phase and the only non-trivially-reversible step.

### Indexes

- `users`: UNIQUE on `email`; index on `account_type`; UNIQUE on `stripe_customer_id` (partial/where-not-null).
- `user_profiles`/`user_settings`: PK on `user_id` (1:1).
- `audit_log`: index on `(user_id, created_at)` and on `(resource, resource_id)` for compliance queries.
- `portfolios.org_id`: index for the future Teams membership join (unused but present).

### Relationships

- `users (1) → user_profiles (1)`, `users (1) → user_settings (1)` — strict 1:1, created on first sign-in.
- `users (1) → audit_log (N)` — append-only.
- Every existing `user_id` column becomes a **soft** FK to `users.id` (logical join, no DDL FK constraint — consistent with the existing no-FK-by-ticker discipline across the codebase). The single hard FK introduced is `user_profiles.user_id`/`user_settings.user_id → users.id`.

---

## PART 3 — AUTH PLAN

### Supabase project setup (operator runbook — `PHASE_16_SUPABASE_SETUP.md`, Slice 4)

1. Create a Supabase project in the chosen region (data-residency forward-compat, spec §8.3).
2. Enable **Email magic link** as the primary provider; disable email/password unless a fallback is later required.
3. Enable **Google OAuth** with minimum scopes `email`, `profile` only (spec §8.3 — no Drive/Calendar creep).
4. Set the redirect URL to `MAGIC_LINK_REDIRECT_URL` (`https://app.clearsignal.ai/auth/callback`).
5. Configure a custom SMTP relay (Resend or SendGrid) on a dedicated sending domain to protect magic-link deliverability (the top risk in spec §10).
6. Copy `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_JWT_SECRET` into Render env. Never commit them.

### Env vars (spec Appendix B)

| Variable | Purpose | Safe default |
|---|---|---|
| `AUTH_ENABLED` | Master enforcement toggle | `false` (bypass) |
| `SUPABASE_URL` | Project URL (JWKS + auth proxy) | — (required Slice 4) |
| `SUPABASE_ANON_KEY` | Public client key | — |
| `SUPABASE_JWT_SECRET` | JWT signature verification | — |
| `SYSTEM_DEFAULT_USER_ID` | Fixed UUID for legacy data ownership | `00000000-0000-0000-0000-000000000001` |
| `MAGIC_LINK_REDIRECT_URL` | Post-link redirect | `https://app.clearsignal.ai/auth/callback` |

### JWT verification (Slice 3)

- Purely cryptographic, **no per-request DB call**. Signature verified against Supabase JWKS (in-memory cache, 1h TTL, re-fetch on rotation). Validate `exp`, `aud='authenticated'`, `iss`. The `sub` claim becomes `request.state.user_id`.
- `app_metadata.role='admin'` gates admin routes; `app_metadata.account_type` carries the plan/account context for future gating.

### Backend middleware (Slice 3)

- Chain: `CORS → extract_token → verify_jwt → inject request.state.user_id → handler`.
- `AUTH_ENABLED=false` short-circuits `verify_jwt` to the system identity — the bypass that keeps every pre-16 flow working while the stack is built.

### Protected vs public routes (spec §4.3)

- **Public:** `/health`, `/healthz`, `/`, `/auth/*`.
- **Authenticated (`require_auth`):** `/portfolio*`, `/watchlist*`, `/notifications`, `/briefing*`, `/onboarding*`, `/analyze`, `/ask`.
- **Admin (`require_admin`):** `/admin/*` including the new `/admin/accounts-status`.
- Tiering is wired in Slice 5 but enforced only when `AUTH_ENABLED=true` (PART 7).

---

## PART 4 — MIGRATION PLAN

### How NULL `user_id` rows become system-owned

Slice 2's `claim_orphan_rows()` runs the additive per-table `UPDATE ... SET user_id = SYSTEM_DEFAULT_USER_ID WHERE user_id IS NULL` at startup, idempotently, logging counts. After one pass, zero orphan rows remain. No row is created or destroyed; only the owner field is filled.

### How the first user imports/copies existing data

Slice 6's opt-in `POST /auth/import-existing-data` runs the precise `UPDATE ... WHERE user_id = SYSTEM_DEFAULT_USER_ID` for watchlist/portfolios/prefs only, atomic-guarded by the `claimed_at` sentinel. The onboarding screen offers it once ("We found an existing watchlist with N tickers — import it?"). Decline leaves the data on the system user for later admin assignment.

### How destructive reassignment is avoided

- Every ownership change is an `UPDATE` of the `user_id` field; **never** a `DELETE` or row rewrite.
- The system claim and the user import each have an **exact inverse** SQL, so any reassignment is reversible until NOT-NULL enforcement.
- Analysis/memory/briefing history is **never** re-owned away from the system user — it is the permanent audit baseline.

### How rollback is preserved

- All schema is additive `IF NOT EXISTS` until the final `010_user_id_not_null.sql`.
- `AUTH_ENABLED=false` means a full code revert at any slice restores single-user behavior with zero data migration.
- The `NOT NULL` migration is gated behind a 30-day soak and a validator confirming zero orphan rows (PART 7) — it is the single point past which rollback requires re-allowing NULLs (`011_user_id_nullable.sql`, kept on standby).

---

## PART 5 — FRONTEND PLAN

*(Frontend lives in the `Ai-Intelligence-interface` submodule; this plan specifies behavior, not files.)*

- **Sign in:** Email-entry screen → `POST /auth/magic-link` → "check your inbox" confirmation. Magic link is the default path.
- **Magic link callback:** `/auth/callback` consumes the Supabase OTP, receives the JWT, stores the **access token in memory only** and the **refresh token in an httpOnly Secure SameSite=Strict cookie** (spec §6.4) — never `localStorage`.
- **Google OAuth:** "Sign in with Google" button → Supabase OAuth → same callback/token handling. Minimum scopes only.
- **Session handling:** SDK auto-refreshes on 401 via the refresh-token cookie; logout calls `POST /auth/logout` to revoke server-side. No "remember me" toggle — the 30-day sliding refresh token is always set.
- **Onboarding import screen:** the spec §7 four-step wizard (profile → watchlist → portfolio → briefing). The watchlist step surfaces the Slice 6 import offer ("Import from existing watchlist?"); the portfolio step offers "Import from watchlist / Start blank / Skip" per spec §7.2.
- **Logged-in app shell:** every API call carries `Authorization: Bearer <access_token>`; the shell reads `/onboarding/state` to decide whether to resume the wizard or render the dashboard.

---

## PART 6 — VALIDATION PLAN

### Auth checks (the defining gates)

- Valid/expired/wrong-aud/bad-signature JWT behavior (Slice 3).
- Bypass mode: zero 401s, every request resolves to the system user (Slice 3).
- Magic-link + Google round-trips against staging Supabase (Slice 4).
- No credential in logs; no password column anywhere (Slices 4, 8).

### Authorization checks

- Public/authenticated/admin tiering returns 200/401/403 correctly when `AUTH_ENABLED=true` (Slice 5 dry-run, PART 7).
- `require_admin` rejects a non-admin JWT with 403, no resource disclosure.

### Ownership / isolation checks

- Two-user dry-run: user A cannot read/modify/delete user B's portfolios, watchlist, prefs, or inbox (HTTP 403/empty, no disclosure — Slice 5).
- Portfolio positions/insights inherit ownership via `portfolio_id` (Slice 5).

### Migration checks

- System claim is idempotent, additive, exactly invertible; zero orphan rows after; no row-count change (Slice 2).
- User import is one-time, race-safe, excludes analysis history (Slice 6).
- `NOT NULL` migration applies only after zero-orphan verification (PART 7).

### Production validation

- `tests/validate_16_auth_shadow.py`: `/health` ok + `db_table_count = 35`; `/admin/accounts-status` `safe_state=true`; system user present; zero orphan NULL rows; Supabase configured; no password column; no secret exposed. Exits 0/1 per the 10C/10D convention (Slice 8).

---

## PART 7 — ROLLOUT SEQUENCE

The build lands entirely under `AUTH_ENABLED=false`. The flip is staged, each stage gated by the validator and reversible by a single flag.

### Shadow auth stage (Slices 1–8 deployed, `AUTH_ENABLED=false`)

The full accounts stack is live: tables seeded, system user owns all legacy data, middleware present in bypass, auth routes functional, ownership plumbing threaded, onboarding + audit wired, observability green. The platform behaves exactly as the single-user system. **Gate:** `validate_16_auth_shadow.py` passes; `db_table_count=35`; zero orphan rows; 0 regressions in `tests/test_services/` and the 10C/10D validators.

### Internal auth stage (`AUTH_ENABLED=true`, internal/staging only)

Enable enforcement in a non-production environment. Sign up the first internal user, run the Slice 6 import, exercise every portfolio/watchlist/delivery/briefing flow under a real JWT, run the two-user isolation suite. **Gate:** isolation suite green; import works and is race-safe; production still in bypass.

### Protected beta stage (`AUTH_ENABLED=true`, production, allowlist)

Enable enforcement in production for an allowlisted set of beta users (gate on `users.is_active` + an `app_metadata` beta flag). Frontend sends bearer tokens; onboarding wizard live. Monitor `audit_log` for unexpected mutations and 401 rates (should be ~0 — there are no legacy sessions). **Gate:** zero auth errors for 48h; beta users can import and isolate correctly.

### Public beta stage (`AUTH_ENABLED=true`, production, open sign-up)

Open magic-link/Google sign-up to the public. System user still holds any un-imported legacy data. Monitor deliverability (magic-link bounce rate — the top spec risk), Supabase availability, and audit volume. **Gate:** deliverability healthy; Supabase stable; no isolation incidents.

### NOT-NULL enforcement (≥30-day soak after public beta)

Confirm `SELECT COUNT(*) WHERE user_id = SYSTEM_DEFAULT_USER_ID` is 0 across watchlist/portfolio (all claimed or acknowledged-unclaimed); apply `010_user_id_not_null.sql`; remove the `AUTH_ENABLED` bypass branch — auth is now unconditionally required on protected routes. **Gate:** 30-day soak elapsed; zero orphan rows; `011_user_id_nullable.sql` kept on standby as the rollback.

### Rollback (any stage before NOT-NULL)

Flip `AUTH_ENABLED=false` → instant return to single-user bypass behavior, zero data change. Deeper revert: unmount auth routes / middleware (code revert, no migration). The system-claim and user-import each have exact inverse SQL. Only past the NOT-NULL line does rollback require the standby `011` migration.

---

## PART 8 — DEPENDENCIES

### On 9A persistence (already shipped)
- DB connection, async session, `create_all()`, the `get_session` null-object contract, the migration-registration + `db_table_count` guard pattern.

### On 10A–10D (already shipped, validated)
- The observability-service pattern (`delivery_observability_service`, `portfolio_observability_service`) — the template for `accounts_observability_service` and the `/admin/*-status` route shape.
- The shadow-validator script convention (`validate_10c/10d_*_shadow.py`) — the template for `validate_16_auth_shadow.py`.
- Every existing `user_id VARCHAR(64) nullable` column — the substrate Phase 16 makes real.

### External (new in Phase 16)
- **Supabase Auth project** — identity provider, JWKS source, magic-link/OAuth issuer (operator-provisioned, Slice 4).
- **SMTP relay (Resend/SendGrid)** on a dedicated domain — magic-link deliverability (top risk mitigation).
- No new Python runtime dependency beyond a JWT/JWKS verification library; **no bcrypt, no password library** (by design).

---

## PART 9 — IMPLEMENTATION ORDER

```
Slice 1  Identity schema & CRUD .............. tables 31 → 35, inert
Slice 2  System user + NULL claim ............ all legacy rows owned (DATA-SAFETY)
Slice 3  JWT middleware (bypass) ............. verification built, AUTH_ENABLED=false
Slice 4  Auth routes + Supabase wiring ....... magic-link/OAuth functional, still bypassed
Slice 5  Ownership threading ................. per-user plumbing, no-op under system identity
Slice 6  One-time import/claim .............. first-user bridge, race-safe (NON-DESTRUCTIVE)
Slice 7  Onboarding + audit trail ........... §7 wizard + §6.6 compliance log
Slice 8  Observability + validator .......... /admin/accounts-status + validate_16
─────────────────────────────────────────────────────────────────────────────
PART 7   Staged flip: shadow → internal → protected beta → public beta → NOT NULL
```

Each slice ends with the platform working and revertible. The order enforces the standing safety property: **identity exists before anything authenticates; every legacy row is owned before anything enforces ownership; the import is race-safe before any user touches it; and the whole stack is observable and shadow-validated before the first `AUTH_ENABLED=true` flip.**

---

## DELIVERABLE SUMMARY

| Artifact | Count |
|---|---|
| Build slices | 8 (+ a 5-stage rollout flip) |
| New tables | 4 (`users`, `user_profiles`, `user_settings`, `audit_log`); `db_table_count` 31 → 35 |
| Forward-compat columns (day one, unused) | `users.stripe_customer_id`, `users.account_type`, `portfolios.org_id` |
| New migrations | `009_accounts.sql` (additive); `010_user_id_not_null.sql` (post-soak); `011_user_id_nullable.sql` (standby rollback) |
| New services | system-user, data-claim, onboarding, audit, accounts-observability |
| New middleware/deps | `middleware/auth.py`, `dependencies/auth.py` |
| New routes | `/auth/*`, `/onboarding/*`, `/admin/accounts-status` |
| New validators/docs | `validate_16_auth_shadow.py`, `PHASE_16_SUPABASE_SETUP.md`, `PHASE_16_ACCOUNTS_ROLLOUT.md` |
| Master safety flag | `AUTH_ENABLED=false` until PART 7 |
| Credential storage | none — Supabase Auth is sole custodian; no password column anywhere |

This document is an execution plan only. It contains no code and does not modify the approved `PHASE_16_ACCOUNTS_SPEC.md` architecture.
