# Phase 16 — Auth Shadow Rollout

**Status:** Shadow mode — `AUTH_ENABLED=false`
**Soak target:** 30 days before enforcement activation

---

## Overview

Phase 16 introduces the full Accounts & Identity layer: users table, JWT
middleware, auth routes, ownership threading, one-time data import, and
onboarding state tracking. The middleware, routing, and ownership code are
fully deployed but operate in **bypass mode** — every request resolves to
`SYSTEM_DEFAULT_USER_ID` and no JWT is inspected or enforced.

This document covers environment configuration, activation steps, rollback
procedures, and the 30-day soak rationale.

---

## Environment Variables

### Required (all phases)

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | — | PostgreSQL connection URL (required in production) |
| `OPENAI_API_KEY` | — | OpenAI key for LLM synthesis |
| `FRED_API_KEY` | — | FRED macro data key |

### Auth flags (Phase 16)

| Variable | Default | Description |
|---|---|---|
| `AUTH_ENABLED` | `false` | Master auth switch. Keep `false` during soak. |
| `SUPABASE_PROJECT_URL` | `""` | Supabase project URL. Required for RS256 JWKS verification. Example: `https://xyzabcde.supabase.co` |
| `SUPABASE_JWT_SECRET` | `""` | HS256 JWT secret. Set if using HS256 (simpler; preferred for first activation). |
| `SUPABASE_AUDIENCE` | `authenticated` | JWT `aud` claim value. Leave as default unless custom. |
| `AUTH_BYPASS_USER_ID` | `00000000-0000-0000-0000-000000000001` | UUID used when bypass is active. **Do not change.** |

### Safe defaults

All auth variables have safe defaults. With `AUTH_ENABLED=false` (the
default), the backend behaves identically to pre-Phase-16: every request is
treated as `SYSTEM_DEFAULT_USER_ID`, no JWT is inspected, and all existing
API surfaces remain unchanged.

---

## Activation Steps

### Pre-conditions (verify before flipping AUTH_ENABLED)

1. **Validation passes:**
   ```bash
   python3 tests/validate_16_auth_shadow.py
   ```
   All checks must show `PASS`. Specifically:
   - `safe_state=true`
   - `null_rows_count=0`
   - `system_user_present=true`
   - `db_table_count=35`

2. **Snapshot endpoint healthy:**
   ```
   GET /admin/auth-status → {"safe_state": true, "auth_bypass": true}
   ```

3. **Supabase project configured:**
   - Either `SUPABASE_JWT_SECRET` (HS256) or `SUPABASE_PROJECT_URL` (RS256) must be set.
   - Verify with `GET /admin/auth-status → {"supabase_secret_configured": true}`.

4. **30-day soak complete** (see Soak section below).

### Activation sequence

```bash
# 1. Set the JWT secret in your environment / secrets manager
export SUPABASE_JWT_SECRET="<your-supabase-jwt-secret>"

# 2. Flip the master switch
export AUTH_ENABLED=true

# 3. Deploy / restart workers
# Render: trigger a new deploy with updated env vars.

# 4. Smoke-test immediately after deploy
curl https://your-backend.onrender.com/admin/auth-status | jq .
# Expected: auth_enabled=true, auth_bypass=false, jwt_verification_enabled=true
```

### JWT verification mode

- **HS256 (recommended first):** Set `SUPABASE_JWT_SECRET`. Fast, no outbound
  network calls. Suitable for single-region deployments.
- **RS256 / JWKS:** Set `SUPABASE_PROJECT_URL`. The middleware fetches the
  JWKS from `{SUPABASE_PROJECT_URL}/auth/v1/keys` and caches it for 1 hour.
  Required if you want key rotation without a redeploy.

---

## Rollback

### Immediate rollback (< 1 minute)

Set `AUTH_ENABLED=false` and redeploy. All requests revert to bypass mode.
No data is modified by this rollback.

```bash
export AUTH_ENABLED=false
# Trigger redeploy on Render (or restart uvicorn workers)
```

### Data rollback (import undo)

If a user's data import needs to be undone:

```python
from app.services.account_import_service import rollback_import
# Inside an async context with a DB session:
result = await rollback_import(session, user_id)
print(f"Deleted: {result.total_deleted} rows")
```

The rollback reads the audit trail and deletes only the rows that were
created by `execute_import`. System-owned rows (`SYSTEM_DEFAULT_USER_ID`) are
never touched.

### Full ownership rollback (emergency)

If Phase 16 Slice 2 ownership claim needs to be reversed (e.g. to re-run
migration validation on a fresh DB copy):

```python
from app.services.system_user_service import restore_null_ownership
# Sets user_id back to NULL for all system-owned rows.
# Only valid before any real-user import has run.
result = await restore_null_ownership(session)
```

---

## Migration Plan

### Tables added in Phase 16 (Slice 1)

| Table | Purpose |
|---|---|
| `users` | Canonical identity record; one per Supabase account |
| `user_profiles` | Display name, timezone, onboarding step |
| `user_settings` | Briefing delivery and UI preferences |
| `audit_log` | Append-only mutation trail (no UPDATE/DELETE) |

Plus one additive column on `portfolios`:
- `org_id VARCHAR(36) NULL` — forward-compat Teams anchor (Phase 16 §8.2)

### Table count

`db_table_count = 35` (validated by `validate_16_auth_shadow.py`).

### Migration execution

All migrations are idempotent `CREATE TABLE IF NOT EXISTS` / `ALTER TABLE …
ADD COLUMN IF NOT EXISTS` statements applied at startup via
`app/db/migrations/009_accounts_identity.sql`.

No destructive DDL is used. No existing column is modified or dropped.

---

## 30-Day Soak Explanation

The middleware, routes, and ownership code are deployed but **enforcement
is off** for a deliberate soak period before `AUTH_ENABLED=true`.

### Why soak?

1. **Ownership claim verification.** The system must confirm that
   `claim_null_ownership` ran successfully and `null_rows_count=0` holds
   across all production traffic patterns before enforcement would make any
   row inaccessible.

2. **Import service validation.** Users need a chance to trigger
   `execute_import` (manually or via onboarding flow) so their data is
   correctly attributed before ownership becomes enforced.

3. **JWT middleware shadow observation.** With `AUTH_ENABLED=false`, the
   middleware runs on every request but only stamps `SYSTEM_DEFAULT_USER_ID`
   — a safe, observable rehearsal of the auth path without any enforcement
   risk. Any crash in the middleware degrades to bypass (fail-open design).

4. **Monitoring baseline.** `GET /admin/auth-status` is polled to confirm
   `safe_state=true` persists for 30 consecutive days. Any deviation (e.g.
   null rows reappearing, system user missing) is flagged before enforcement
   would expose it as an access failure.

5. **Rollback confidence.** A 30-day soak with zero incidents builds
   confidence that `AUTH_ENABLED=true` won't produce a surprise outage.

### Soak completion checklist

- [ ] `validate_16_auth_shadow.py` → all PASS for 30 days
- [ ] `GET /admin/auth-status → safe_state: true` for 30 days
- [ ] `null_rows_count = 0` confirmed in production snapshot
- [ ] At least one user has completed `execute_import` successfully
- [ ] Onboarding flow tested end-to-end in staging with `AUTH_ENABLED=true`
- [ ] JWT secret stored in secrets manager (not env file)
- [ ] Supabase project URL confirmed for RS256 (if RS256 chosen)
- [ ] All auth routes respond correctly: `/auth/me`, `/auth/session`, `/auth/logout`

---

## Auth Route Reference

| Method | Path | Bypass behavior | Auth behavior |
|---|---|---|---|
| `GET` | `/auth/me` | Returns system user identity | Returns JWT-resolved user identity |
| `GET` | `/auth/session` | Returns bypass session info | Returns real session info |
| `POST` | `/auth/logout` | Returns `{logged_out: true}` | Writes audit log entry |
| `GET` | `/admin/auth-status` | Returns snapshot with safe_state | Same |

---

## Security Notes

- **No password columns exist** on any model. Supabase Auth is the sole
  credential custodian. The backend never stores, hashes, or validates passwords.
- **JWT secrets are never logged.** The middleware logs token verification
  errors as `[auth] JWT verify failed` without including the token or secret.
- **The `auth_bypass_user_id` UUID is not a secret** — it is the well-known
  `SYSTEM_DEFAULT_USER_ID` anchor and is referenced openly in code comments.
  However it must not be changed; changing it would orphan all legacy rows.
- **`/admin/auth-status`** does not require authentication during soak.
  Route protection is added in Phase 16 Slice 9. Until then, the endpoint
  is protected by convention (internal network / Render private service).

---

## Observability

```bash
# Live snapshot (no auth required during soak)
curl https://your-backend.onrender.com/admin/auth-status | jq .

# Run validation locally against in-memory SQLite
python3 tests/validate_16_auth_shadow.py

# Run all Phase 16 tests
python3 -m pytest tests/test_services/test_auth_middleware.py \
                  tests/test_services/test_supabase_auth_service.py \
                  tests/test_services/test_auth_routes.py \
                  tests/test_services/test_ownership_service.py \
                  tests/test_services/test_account_import_service.py \
                  tests/test_services/test_onboarding_service.py \
                  tests/test_services/test_auth_observability_service.py \
                  -q
```

Expected output when healthy:
```json
{
  "auth_enabled": false,
  "auth_bypass": true,
  "safe_state": true,
  "null_rows_count": 0,
  "system_user_present": true,
  "db_table_count_expected": 35
}
```
