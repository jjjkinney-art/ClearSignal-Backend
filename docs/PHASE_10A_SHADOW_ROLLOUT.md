# Phase 10A Continuous Intelligence Loop — Shadow Rollout Checklist

This document covers everything needed to deploy Phase 10A in shadow mode,
validate it is healthy, and safely advance to canary rollout.

**Shadow mode definition:** `loop_enabled=False`, `loop_shadow=True`.
The loop infrastructure is fully deployed (DB tables, scheduler, delivery ledger,
canary telemetry), but the tick scheduler does not fire autonomously and no
briefings reach users.  All writes are to the `delivery_ledger` with status
`delivered_shadow` only.

---

## 1. Environment Variables

All settings have safe defaults for shadow mode. Set these explicitly in
your deployment environment (Render, Railway, etc.):

| Variable | Shadow Value | Notes |
|---|---|---|
| `LOOP_ENABLED` | `false` | Must be False for shadow. Governs tick scheduler. |
| `LOOP_SHADOW` | `true` | Enables shadow delivery path in loop_delivery_service |
| `LOOP_CANARY_PCT` | `0` | No external users in canary during shadow |
| `LOOP_INTERNAL_ONLY` | `true` | Only internal users can exercise the canary path |
| `LOOP_INTERNAL_USER_IDS` | `""` | Comma-separated UUIDs of internal testers (optional) |
| `LOOP_DRIFT_GATE_ENABLED` | `true` | Enables cost protection; keep on |
| `LOOP_FORCE_RUN` | `false` | Never force in shadow/production |
| `LOOP_DRIFT_MATERIALITY_MIN` | `0.4` | Score threshold; 0.4 is the recommended default |
| `LOOP_TICK_BATCH_SIZE` | `10` | Jobs claimed per tick; default safe |
| `LOOP_LOCK_LEASE_S` | `120` | Tick lock lease in seconds |
| `LOOP_RETRY_BACKOFF_S` | `300` | Retry back-off after failure |
| `DELIVERY_QUIET_HOURS_START` | `22` | UTC hour; start of no-delivery window |
| `DELIVERY_QUIET_HOURS_END` | `7` | UTC hour; end of no-delivery window |
| `DELIVERY_DAILY_CAP` | `20` | Max deliveries per channel/target/day |
| `DELIVERY_SEVERITY_FLOOR` | `info` | Minimum severity to allow through |

> **Never set `LOOP_ENABLED=true` until canary validation passes.**

---

## 2. DB Migration

Phase 10A adds 5 new tables. Migration is in:

```
app/db/migrations/005_continuous_loop.sql
```

After deploy, verify via `/health`:

```json
{ "db_table_count": 24, ... }
```

Expected table count: **24** (19 pre-Phase-10A + 5 new: `scheduled_jobs`,
`job_locks`, `job_runs`, `delivery_ledger`, `notifications`).

---

## 3. Status Fields

`GET /admin/loop-status` returns the canonical loop snapshot. Key fields:

```json
{
  "status": "ok",
  "snapshot_utc": "2026-06-12T12:00:00Z",
  "db_available": true,
  "loop_enabled": false,
  "loop_shadow": true,
  "effective_enabled": false,
  "override_state": null,
  "canary": {
    "canary_pct": 0,
    "internal_only": true,
    "cohort_counts": {}
  },
  "telemetry": {
    "kill_switch": { "enabled_override": null, "effective_state": "config_governed" },
    "counters": { "tick_count": 0, ... },
    "cohort_counts": {},
    "recent_ticks": []
  },
  "config": { ... },
  "jobs":     { "total": 0, "by_state": {} },
  "runs":     { "total": 0, "by_outcome": {}, "recent": [] },
  "delivery": { "total": 0, "by_status": {}, "shadow_count": 0 },
  "locks":    { "tick_lock": null, "tick_lock_held": false },
  "guardrails": { ... }
}
```

**Shadow-healthy indicators:**
- `loop_enabled`: `false`
- `loop_shadow`: `true`
- `effective_enabled`: `false`
- `override_state`: `null` (kill switch not active)
- `db_available`: `true` (or `"partial"`)
- `delivery.by_status.delivered_shadow`: incrementing when ticks run manually

---

## 4. How to Enable / Disable

### Temporarily disable (kill switch — in-process, no redeploy):
```http
POST /admin/loop/disable
```
Takes effect immediately for all subsequent `tick()` calls.
Survives until `/admin/loop/enable` is called or process restarts.

### Restore config governance:
```http
POST /admin/loop/enable
```
Clears the kill switch. Does NOT force-enable if `LOOP_ENABLED=false` in config.

### Permanently enable (requires redeploy):
Set `LOOP_ENABLED=true` in environment and redeploy.

---

## 5. Validation Gates (Shadow → S0)

Run the deployment validator after every deploy:

```bash
python tests/validate_10a_loop_shadow.py --url https://<your-backend>.onrender.com
```

All of the following must pass before advancing to S0 (1% canary):

| Gate | Check |
|---|---|
| Backend reachable | `GET /health` → 200 |
| DB tables correct | `db_table_count == 24` |
| Loop status returns | `GET /admin/loop-status` → 200, `status=ok` |
| All required fields present | All 12 top-level snapshot keys present |
| `loop_shadow=True` | Shadow mode active |
| `loop_enabled=False` | Tick scheduler dormant |
| `loop_canary_pct=0` | No external users in canary |
| `override_state=null` | Kill switch not active |
| `db_available` not False | DB reachable |

---

## 6. Advancing from Shadow to S0 (1% Canary)

Preconditions:
1. All shadow validation gates pass.
2. At least 24 hours of shadow dwell with no 5xx errors on loop endpoints.
3. `delivery.by_status.delivered_shadow` > 0 (loop has produced at least one shadow delivery).
4. No `kill_switch.effective_state == "force_disabled"`.

Steps:
1. Set `LOOP_CANARY_PCT=1` in environment.
2. Set `LOOP_ENABLED=true` in environment.
3. Redeploy.
4. Verify: `GET /admin/loop-status` → `canary_pct=1`, `effective_enabled=true`.
5. Run `validate_10a_loop_shadow.py --no-expect-shadow --expect-db-tables 24`.
6. Monitor `GET /admin/loop-status` hourly for 24h S0 dwell.
7. S0 gate criteria: zero 5xx, `delivery.shadow_count` incrementing, no `over_cap_count` > 0.

---

## 7. Rollback Procedure

### Immediate (in-process, no redeploy):
```http
POST /admin/loop/disable
```
Stops all tick processing immediately. Delivery ledger rows stay in `delivered_shadow`.
No user impact. Can be reversed with `POST /admin/loop/enable`.

### Full rollback (requires redeploy):
Set `LOOP_ENABLED=false`, `LOOP_CANARY_PCT=0` in environment and redeploy.

### Data rollback (extreme, requires DB access):
The 5 Phase 10A tables are append-only and isolated. Dropping them is a last resort.
Prefer the in-process kill switch for all operational rollback scenarios.

---

## 8. Failure Modes

| Symptom | Likely cause | Action |
|---|---|---|
| `/admin/loop-status` returns `db_available: false` | DB connection error | Check DB env vars; check DB server health; restart process |
| `db_available: "partial"` | One or more DB queries failed | Check logs for `[observability] *_section failed`; non-fatal, investigate |
| `effective_enabled: false` when `loop_enabled=true` | Kill switch active (`override_state: false`) | `POST /admin/loop/enable` to clear |
| `telemetry.counters.jobs_failed` incrementing | Producer errors | Check `runs.recent[].error` for error message |
| `delivery.by_status.suppressed` > 0 | Severity floor, daily cap, or quiet hours | Check `guardrails` section; adjust if needed |
| `telemetry.counters.lock_contention_count` high | Multiple instances racing on tick lock | Normal for multi-instance; monitor, not an error unless `jobs_succeeded=0` |
| `runs.recent[].drift_hit=true` on all runs | No substrate changes; drift gate firing | Normal in quiet periods; check `loop_drift_materiality_min` if unexpected |

---

## 9. Monitoring Queries

```bash
# Shadow delivery count (should increment when loop is active)
curl -s https://<backend>/admin/loop-status | python3 -c \
  "import sys, json; d=json.load(sys.stdin); print(d['delivery']['shadow_count'])"

# Tick health
curl -s https://<backend>/admin/loop-status | python3 -c \
  "import sys, json; d=json.load(sys.stdin); c=d['telemetry']['counters']; \
   print(f\"ticks={c['tick_count']} ok={c['jobs_succeeded']} fail={c['jobs_failed']}\")"

# Recent run errors
curl -s https://<backend>/admin/loop-status | python3 -c \
  "import sys, json; d=json.load(sys.stdin)
for r in d['runs']['recent']:
  if r['outcome'] == 'failed':
    print(r['job_type'], r['target_key'], r['error'])"
```

---

## 10. Phase 10A Slice Summary

| Slice | Description | Status |
|---|---|---|
| 1 | DB schema (5 tables, ORM, migration) | ✓ Done |
| 2 | Lock service (acquire/renew/release/reap) | ✓ Done |
| 3 | Repositories (39 functions) | ✓ Done |
| 4 | Scheduler (tick, register_producer, TickResult) | ✓ Done |
| 5 | Idempotency (work_key, content_key guards) | ✓ Done |
| 6 | Shadow producer bindings (watchlist_scan, morning_brief, timeline_rollup) | ✓ Done |
| 7 | Drift triggering / cost gate (should_run_job, materiality scoring) | ✓ Done |
| 8 | Delivery ledger / shadow delivery (enqueue, flush, guardrails) | ✓ Done |
| 9 | Canary cohort + kill switch (CRC32 cohort, admin endpoints) | ✓ Done |
| 10 | Observability + deployment validation (this document) | ✓ Done |

**Phase 10B** (real delivery channels, in-app notifications) is the next phase.
Do not merge 10B work until 24h S0 shadow dwell passes all gates.
