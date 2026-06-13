# Phase 10B — Watchlist Intelligence Shadow Rollout

Phase 10B hardens the ClearSignal watchlist intelligence layer for shadow observation before promoting to production. This document covers the environment configuration, expected state, validation steps, rollback procedure, and criteria to advance to Phase 10C.

---

## 1. Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `DATABASE_URL` | Yes | — | PostgreSQL DSN (`postgresql+asyncpg://...`) |
| `LOOP_ENABLED` | No | `false` | Set `true` only to activate live loop production; keep `false` during shadow |
| `LOOP_SHADOW` | No | `true` | Set `true` to enable shadow delivery mode (writes to delivery_ledger with shadow flag) |
| `LOOP_SHADOW_TARGET` | No | `delivery_ledger` | Target table for shadow rows |
| `DRIFT_GATE_ENABLED` | No | `true` | Enables drift-gate guardrail; skip scan if drift below threshold |
| `DRIFT_MATERIALITY_MIN` | No | `0.2` | Minimum drift magnitude to trigger scan |
| `TIMELINE_LIVE_CAP` | No | `50` | Max live entries per (ticker, entry_type) in JSON timeline file |
| `BACKEND_URL` | Validation | `http://127.0.0.1:8000` | URL used by validate scripts and the frontend |
| `ADMIN_TOKEN` | No | `` | Bearer token for `/admin/*` endpoints (if auth enabled) |

Shadow mode configuration for local or staging environment:

```bash
export DATABASE_URL="postgresql+asyncpg://user:pass@localhost:5432/clearsignal"
export LOOP_ENABLED=false
export LOOP_SHADOW=true
export DRIFT_GATE_ENABLED=true
export DRIFT_MATERIALITY_MIN=0.2
```

---

## 2. Expected Database Table Count

After all migrations through Phase 10B have run, the database should contain **25 tables**.

Run migrations:

```bash
# Apply all migrations in order
psql $DATABASE_URL < app/db/migrations/001_initial.sql
psql $DATABASE_URL < app/db/migrations/002_...sql
# ... through ...
psql $DATABASE_URL < app/db/migrations/006_watchlist_membership.sql
```

Verify via `/health`:

```bash
curl http://localhost:8000/health | jq '.db_table_count'
# Expected: 25
```

Key tables added in Phase 10B:
- `watched_tickers` — ticker membership, `is_active` flag
- `scheduled_jobs` — `watchlist_scan` job rows seeded per (ticker, period_bucket)
- `delivery_ledger` — shadow delivery rows written when material changes observed

---

## 3. Expected Status Endpoints

| Endpoint | Method | Auth | Description |
|---|---|---|---|
| `/health` | GET | No | Database connectivity, table count, service version |
| `/admin/loop-status` | GET | Admin | Full observability snapshot: loop state, delivery stats, guardrails, watchlist section |
| `/admin/loop/enable` | POST | Admin | Flip `loop_enabled=true` |
| `/admin/loop/disable` | POST | Admin | Flip `loop_enabled=false` |
| `/admin/loop/shadow` | POST | Admin | Flip `loop_shadow=true/false` |
| `/admin/loop/seed-jobs` | POST | Admin | Seed `watchlist_scan` jobs for all active tickers |
| `/watchlist` | GET | No | All active watchlist entries with live drift state |
| `/watchlist/drift` | GET | No | Drift summaries — must agree with `/watchlist` |
| `/watchlist/status` | GET | No | Counts, tickers with analyses |
| `/morning-brief` | GET | No | Returns deprecation JSON `{deprecated: true, redirect: "/morning-brief/v2"}` |
| `/morning-brief/v2` | GET | No | Live v2 institutional brief (5 sections) |

### `/admin/loop-status` watchlist section (Phase 10B addition)

```json
{
  "status": "ok",
  "loop_enabled": false,
  "loop_shadow": true,
  "watchlist": {
    "active_ticker_count": 20,
    "active_tickers": ["AAPL", "AMZN", ...],
    "scan_jobs_total": 40,
    "duplicate_job_combos": 0,
    "drift_skip_count": 0
  },
  "delivery": {
    "total": 0,
    "shadow_count": 0,
    "live_count": 0,
    "duplicate_total": 0,
    "by_status": {}
  },
  "guardrails": {
    "drift_gate_enabled": true,
    "drift_materiality_min": 0.2
  }
}
```

---

## 4. How to Seed Jobs

Watchlist scan jobs must be seeded before the loop can run. The seeder is idempotent — running it multiple times is safe.

### Via HTTP (recommended)

```bash
curl -X POST http://localhost:8000/admin/loop/seed-jobs \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" | jq .
```

Expected response:

```json
{
  "status": "ok",
  "jobs_created": 40,
  "jobs_existing": 0,
  "tickers_seen": 20
}
```

On a re-run, `jobs_created=0` and `jobs_existing=40` is the correct idempotent state.

### Via Python CLI

```bash
python -c "
import asyncio
from app.db.connection import get_session
from app.services.watchlist_job_seeder import seed_watchlist_jobs

async def main():
    async with get_session() as sess:
        r = await seed_watchlist_jobs(sess)
        print(r)

asyncio.run(main())
"
```

---

## 5. How to Run Shadow Validation

The validation script checks all critical 10B readiness criteria without requiring the loop to be actively running.

### Prerequisites

```bash
# Backend must be running
uvicorn app.main:app --reload --port 8000 &

# Environment
export BACKEND_URL=http://localhost:8000
export ADMIN_TOKEN=your_token_here   # if auth enabled; blank otherwise
```

### Run validation

```bash
# Basic run — checks all 14 criteria
python tests/validate_10b_watchlist_shadow.py

# With job seeding (seeds before checking job counts)
python tests/validate_10b_watchlist_shadow.py --seed-jobs

# With verbose JSON output
python tests/validate_10b_watchlist_shadow.py --verbose

# Against a remote deployment
python tests/validate_10b_watchlist_shadow.py \
  --url https://your-backend.onrender.com \
  --token $ADMIN_TOKEN

# Skip table-count assertion (useful against a dev DB)
python tests/validate_10b_watchlist_shadow.py --expect-db-tables 0
```

### Expected output (all passing)

```
Phase 10B Watchlist Shadow Readiness Validator
Target:         http://localhost:8000
Expect tables:  25
Seed jobs:      False

[1] GET /health — backend reachable, db_table_count
  ✓ [PASS] status 200
  ✓ [PASS] status=ok
  ✓ [PASS] db_table_count=25
  ✓ [PASS] db_enabled=True

[2] GET /admin/loop-status — watchlist section present
  ✓ [PASS] status 200
  ...

[14] Timeline cap / archival readiness
  ✓ [PASS] /watchlist/status reachable and structured

============================================================
SUMMARY: 38/38 checks passed  (2 skipped)
============================================================
```

Exit code 0 = all checks passed. Exit code 1 = one or more failed. Exit code 2 = network error.

---

## 6. Rollback Steps

Phase 10B changes are additive — no destructive schema changes. Rollback is safe at any step.

### Rollback: Disable loop + shadow

```bash
curl -X POST http://localhost:8000/admin/loop/disable \
  -H "Authorization: Bearer $ADMIN_TOKEN"

# Set shadow off (keeps delivery_ledger rows but stops new writes)
curl -X POST http://localhost:8000/admin/loop/shadow \
  -H "Content-Type: application/json" \
  -d '{"enabled": false}' \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

### Rollback: Revert DB tables

```sql
-- Remove Phase 10B tables only (safe — no FK dependencies on core tables)
DROP TABLE IF EXISTS watched_tickers CASCADE;
-- Note: scheduled_jobs and delivery_ledger were introduced in Phase 10A
-- Only drop them if rolling back to Phase 9G baseline
```

### Rollback: Revert code

```bash
git checkout phase-10a-complete -- app/ tests/
```

Phase 10A tag `0b45e28` is the last known-good baseline with 534+ tests passing.

---

## 7. Failure Modes and Remediation

| Symptom | Likely Cause | Remediation |
|---|---|---|
| `db_table_count` != 25 | Missing migration | Run remaining `.sql` files in `app/db/migrations/` |
| `active_ticker_count = 0` | `watched_tickers` empty | Run `POST /admin/loop/seed-jobs` or manually insert tickers |
| `scan_jobs_total = 0` | Jobs not seeded | Run `POST /admin/loop/seed-jobs` |
| `duplicate_job_combos > 0` | Seeder ran without UNIQUE constraint | Drop duplicates: `DELETE FROM scheduled_jobs WHERE id NOT IN (SELECT MIN(id) FROM scheduled_jobs GROUP BY job_type, target_key, period_bucket)` |
| `/watchlist` and `/watchlist/drift` ticker mismatch | Stale index.json has extra entries vs DB | Run `GET /watchlist/status` to reconcile; remove stale tickers from index |
| `GET /morning-brief` returns v1 output instead of deprecation JSON | api.py handler not updated | Check `app/api.py` `get_morning_brief()` — should return `{deprecated: true, ...}` |
| `drift_gate_enabled = False` | Missing env var | Set `DRIFT_GATE_ENABLED=true` and restart |
| shadow_count stays 0 after loop tick | Drift gate filtering all events | Lower `DRIFT_MATERIALITY_MIN` or inject a test event |
| Archive directory missing on first write | `os.makedirs` not called | `timeline_store._ensure_archive_dir()` auto-creates — verify file permissions |

---

## 8. Criteria to Proceed to Phase 10C

All of the following must be true before advancing:

**Infrastructure**
- [ ] `GET /health` returns `db_table_count=25`, `status=ok`
- [ ] `watched_tickers` table populated with all active tickers (>= 1)
- [ ] `scheduled_jobs` seeded, `duplicate_job_combos=0`

**Loop behavior (shadow)**
- [ ] `loop_shadow=true`, `loop_enabled=false`
- [ ] At least one shadow tick observed (`shadow_count > 0` in delivery section)
- [ ] `duplicate_total=0` in delivery ledger (content-key dedup working)
- [ ] `drift_skip_count` > 0 (drift gate firing on at least some evaluations)

**Data consistency**
- [ ] `GET /watchlist` and `GET /watchlist/drift` return identical ticker sets
- [ ] No stale `drift_state` values (evaluator vocab: `broke | weakened | strengthened | unchanged | priced_in`)

**Deprecation**
- [ ] `GET /morning-brief` returns `{deprecated: true, redirect: "/morning-brief/v2"}`
- [ ] `GET /morning-brief/v2` returns valid 5-section brief

**Timeline**
- [ ] Timeline live files do not exceed 50 entries per (ticker, entry_type)
- [ ] Archive JSONL files append-only and readable (`load_archive()` returns valid entries)

**Tests**
- [ ] Full test suite: `pytest tests/ -x` passes with 0 failures (excluding known pre-existing `test_mute_until_future_defers_row`)
- [ ] `python tests/validate_10b_watchlist_shadow.py` exits 0

When all boxes are checked, Phase 10C (live promotion) may proceed.
