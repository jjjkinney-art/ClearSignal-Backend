# Continuous Intelligence Loop — Implementation Plan

**Phase:** 10A · the keystone primitive
**Source of truth:** `docs/PHASE_10A_LOOP_SPEC.md` (locked — this plan does not redesign anything)
**Status:** Execution blueprint — no code in this document
**Convention basis:** All file paths, patterns, and table conventions reference the existing codebase (9A–9G precedents). The loop reuses the 9G canary machinery (`dossier_canary_cohort.py`, `dossier_canary_telemetry.py`) wholesale.

---

## PART 1 — BUILD SLICES

Ten slices. Each is independently shippable, independently revertible, and leaves production in a working state if the next slice never lands. The slicing rule, carried from the dossier plan and sharpened for a background system: **schema before lock, lock before driver, driver before producers, generation before delivery, delivery before exposure.** Nothing that *sends* exists until everything that *guards sending* has been tested in shadow.

> **Standing safety property.** Every slice through Slice 8 lands with `loop_enabled=False` (master gate) and `loop_shadow=True` (no sends). The loop can run, generate, and fill ledgers for weeks before a single notification reaches a user. This is the dossier plan's "extraction for months with injection off" discipline, applied to scheduling.

---

### Slice 1 — Schema & Migration

**Objective:** Create all loop tables empty in production + extend `BriefingSession`. Zero behavior change.

**Files:**
- `app/db/migrations/005_continuous_loop.sql` (new — `scheduled_jobs`, `job_runs`, `job_locks`, `delivery_ledger`, `notifications`; `ALTER` adds `content_hash`, `delivery_channel` to `briefing_sessions`)
- `app/db/models.py` (append ORM: `ScheduledJob`, `JobRun`, `JobLock`, `DeliveryLedger`, `Notification`; extend `BriefingSession`)
- `app/startup.py` (register migration in the startup-seed path, the 9F/9G guard pattern)

**Dependencies:** none.

**Validation:** `db_table_count` increases by 5 on the admin status endpoint; app boots clean; all existing tests pass untouched; migration idempotent (run twice, no error, no duplicate index); `briefing_sessions` gains two nullable columns with no row rewrite.

**Rollback strategy:** None needed — additive `IF NOT EXISTS` DDL, `ALTER ... ADD COLUMN` nullable, all unread/unwritten. Tables are inert without later slices. If reverted, the columns sit empty and harmless.

---

### Slice 2 — Lock service (lease + fence)

**Objective:** The single-flight foundation everything else trusts, built and proven *before* any driver can race. Pure mechanism, no scheduling.

**Files:**
- `app/services/loop_lock_service.py` (new — `acquire(name, holder, lease_s) → token|None`, `renew(name, holder, token)`, `release(name, holder, token)`, `reap_expired() → [reclaimed]`, `fence_check(name, token)`)
- `app/db/repositories/loop_repo.py` (new — the atomic compare-and-swap UPSERT against `job_locks`; lock section only this slice)

**Dependencies:** Slice 1.

**Validation:** Unit tests against in-memory SQLite + a real Postgres test DB (the conditional UPSERT semantics differ; both must pass): two concurrent `acquire` → exactly one token returned; `renew` extends `lease_expires_utc`; expired lease reclaimable by a new holder; `fence_check` rejects a stale token; `release` is idempotent. Null-session → null-object no-op (never 500).

**Rollback strategy:** Dead code until Slice 4. Revert = delete the service; no production caller exists. The `job_locks` table stays empty.

---

### Slice 3 — Repositories (job + run + ledger persistence)

**Objective:** Typed persistence over the loop tables. Still no callers.

**Files:**
- `app/db/repositories/loop_repo.py` (extend — `enqueue(job)` idempotent on `(job_type, target_key, period_bucket)`, `select_due(limit)`, `claim(job_id, holder, token, lease_s)`, `reschedule(job_id, next_run, period_bucket)`, `transition(job_id, state)`, `record_run(...)`, `dead_letter(job_id)`)
- `app/db/repositories/loop_delivery_repo.py` (new — `write_ledger(row)` honoring `UNIQUE(content_key)`, `select_undelivered(limit)`, `mark(status)`, `defer(not_before)`)

**Dependencies:** Slices 1–2.

**Validation:** Unit tests: enqueue dedup (second enqueue same key is absorbed, returns existing); `claim` respects optimistic state (`scheduled → claimed` only if still `scheduled`); `record_run` append-only (no update path exposed); `write_ledger` second identical `content_key` raises/absorbs at the constraint; null-object on `session=None`.

**Rollback strategy:** Dead code until Slice 4/8 wire it. Revert = delete modules; tables remain empty and inert.

---

### Slice 4 — Scheduler tick (driver, no producers)

**Objective:** Time advances in production. Jobs are claimed, heartbeated, and completed as **no-ops**. Proves the lock serializes, leases reap, and ticks stay bounded — with zero producer risk.

**Files:**
- `app/services/loop_scheduler.py` (new — `tick()`: acquire tick lock → reap → `select_due` → per-job claim/run/record/reschedule → release; the producer call is a stub returning `succeeded` this slice)
- `app/startup.py` (Bridge driver: an `asyncio` task in the lifespan that calls `tick()` every `loop_tick_interval_s`, started only when `loop_enabled` AND `loop_driver="in_process"`)
- `app/config.py` (flags: `loop_enabled=False`, `loop_driver="in_process"`, `loop_tick_interval_s=60`, `loop_max_jobs_per_tick=50`, `loop_lock_lease_s=120` — all default-inert)

**Dependencies:** Slices 1–3.

**Risk:** **Medium — first thing that runs autonomously.** Mitigations: master flag default-off; tick wrapped in try/except that can never crash the web process; `loop_max_jobs_per_tick` bounds blast radius; no producer = no LLM spend, no user-visible effect.

**Validation:** Staging only, `loop_enabled=True`: seed N no-op jobs → observe `job_runs` rows accumulate, `succeeded` outcomes, schedule lag ≤ 1 interval, tick p100 < interval. **Two-instance test:** run two staging instances → still exactly N runs (lock works). Kill an instance mid-tick → next tick reaps the lease, job re-runs once, `work_key` (Slice 5) will make that safe.

**Rollback strategy:** `loop_enabled=False` — the driver task never starts; the lifespan skips it. Instant, no redeploy needed if toggled via the runtime override (added in Slice 9); redeploy with flag off otherwise. Tables stop being written.

---

### Slice 5 — Idempotency (work key + content key)

**Objective:** Make every job effectively-once. Wire the short-circuit and the dedup constraint into the run path.

**Files:**
- `app/services/loop_scheduler.py` (extend — compute `work_key = hash(job_type, target_key, period_bucket)`; before producer call, check `job_runs` for a `succeeded` row with that key → short-circuit to `succeeded`)
- `app/db/repositories/loop_delivery_repo.py` (extend — `content_key` computed/enforced on write)

**Dependencies:** Slice 4.

**Validation:** Unit + integration: replay the same occurrence twice → producer invoked once, second is short-circuit; force a redeploy mid-run in staging → no duplicate side effect; two `write_ledger` with identical `content_key` → one row, second suppressed at `UNIQUE`. **This slice's gate is the duplicate-delivery=0 invariant** that PART 5 requires for every rollout step.

**Rollback strategy:** Idempotency is purely additive guarding. Reverting re-exposes double-execution risk but breaks nothing structurally; since `loop_shadow=True` still blocks sends, the user-facing risk is nil until Slice 8. Practically: never reverted independently — it gates Slice 8.

---

### Slice 6 — Producer bindings (cadence, shadow generation)

**Objective:** Jobs start calling **real producers** and generating real artifacts — but `loop_shadow=True` means nothing is delivered. The briefing/watchlist content is generated and banked in the ledger only.

**Files:**
- `app/services/loop_producers.py` (new — the binding layer: `run_daily_brief(user)` → `morning_brief_service.generate_morning_brief_v2`; `run_watchlist_scan(user)` → `watchlist_monitor.watchlist_change_detector`; `run_dossier_refresh(ticker)` → headless dossier extraction. Each returns an artifact + `content_hash`, writes the delivery ledger, sets `BriefingSession.status="generated"`)
- `app/services/loop_scheduler.py` (extend — dispatch `job_type → producer`; cadence resolution + `period_bucket` computation with user-local tz, spec §2.3)
- `app/config.py` (`loop_shadow=True`, `loop_delivery_channel="in_app"`)

**Dependencies:** Slice 5. Reads watch targets via the **existing** `watchlist_service` interface (decouples 10A from 10B's table migration — spec §10).

**Risk:** **Medium — first LLM spend on the loop.** Mitigations: shadow (no delivery); `loop_max_jobs_per_tick` caps fan-out; producers are existing, already-tested code called behind their existing interfaces; cost is observable in `job_runs.spent_llm_calls` before any drift amplification (Slice 7).

**Validation:** Staging shadow: enqueue daily-brief jobs for 5 test users → `BriefingSession` rows reach `generated`, delivery ledger fills with `pending` rows, **zero deliveries**, `content_hash` populated, producers invoked through their real interfaces. `/ask` latency and the running S0 dossier canary both unaffected (loop runs out-of-band).

**Rollback strategy:** Revert the producer dispatch to the Slice 4 no-op stub, or `loop_enabled=False`. Generated `BriefingSession`/ledger rows are inert (nothing reads them until Slice 8). No user impact at any point — shadow guarantees it.

---

### Slice 7 — Drift triggering (cost gate)

**Objective:** Stop burning the timer. Regenerate **only** when the substrate materially changed; cadence jobs render cheap "no change" lines for clean names.

**Files:**
- `app/services/loop_drift.py` (new — `is_dirty(job_type, target, since)` reads `dossier_revision` + `thesis_deltas`; `enqueue_drift_jobs()` scans for material rows newer than each target's `last_generated_at`, enqueues one-shot drift jobs with §5.3 coalescing)
- `app/services/loop_producers.py` (extend — cadence producer checks `is_dirty` per watched name; clean → templated line, no LLM call; dirty → spend)
- `app/db/repositories/loop_repo.py` (extend — `last_generated_at` per `(target, job_type)`; drift-job enqueue idempotent on the §5.3 key)

**Dependencies:** Slice 6. Consumes the existing material-change record; defines **no** parallel change predicate (spec §5.4).

**Validation:** Unit: a target with a fresh `dossier_revision` is dirty; without, clean. Coalescing: five dirty signals in one bucket → one job. Integration in staging: a name with no overnight change → brief renders templated line, `spent_llm_calls=0`, `drift_hit=False`; a name with a fired catalyst → regeneration, `drift_hit=True`. **Cost proof:** a quiet test portfolio costs ~0 LLM calls/cycle.

**Rollback strategy:** Disable drift enqueue + force cadence producers to always-spend (revert to Slice 6 behavior). Strictly more expensive, never broken — safe degradation. Or `loop_enabled=False`.

---

### Slice 8 — Delivery (the first sends, gated)

**Objective:** Complete the `generated → delivered` ladder. The `delivery_flush` job drains the ledger to the **in-app channel**. Sends remain blocked by `loop_shadow=True` until rollout (PART 5) flips it per stage.

**Files:**
- `app/services/loop_delivery_service.py` (new — `flush()`: `select_undelivered` → guardrails (quiet hours, frequency cap via `alert_prioritizer`, `mute_until`, severity floor) → send → `mark("delivered"|"failed"|"suppressed")`; `in_app` channel writes a `notifications` row; fence-checked send for non-idempotent channels)
- `app/services/loop_scheduler.py` (extend — `delivery_flush` cadence job, frequent tick)
- `app/api.py` (extend — `GET /notifications` for the in-app inbox the frontend polls; read-only)

**Dependencies:** Slices 5 (content_key dedup), 6 (ledger fills), 7 (cost-gated volume).

**Risk:** **Highest in the plan — the only slice that can reach a user.** Mitigations: `loop_shadow` blocks all sends until PART 5 internal stage; `content_key UNIQUE` makes duplicate delivery impossible at the DB; guardrails enforced at the boundary, not in producers; in-app channel only (no email/push) means worst case is an extra inbox row, never a spurious push; per-recipient ledger means a partial failure retries only failed rows.

**Validation:** Staging with `loop_shadow=False` to test users: ledger `pending → delivered`, `notifications` rows appear, duplicate-delivery count **exactly 0** under forced retry + double-driver, quiet-hours defers via `not_before_utc`, `mute_until` suppresses (still generates), severity floor filters. Then `loop_shadow=True` restored for production deploy.

**Rollback strategy:** `loop_shadow=True` — instant halt of all sends, generation continues, ledger accumulates `pending` (recoverable, never lost). Tier-0 kill switch (Slice 9) `POST /admin/loop/disable` halts everything with no redeploy. In-app rows are non-destructive even if erroneously created.

---

### Slice 9 — Canary + kill switch (9G reuse)

**Objective:** Per-user gradual exposure + instant runtime halt, reusing the dossier canary machinery unchanged.

**Files:**
- `app/services/loop_telemetry.py` (new — mirrors `dossier_canary_telemetry.py` API exactly: `get_enabled(config)`, `force_disable()`, `force_enable()` (clears override), `clear_override()`, `record_*`, `snapshot()`)
- `app/services/loop_delivery_service.py` (extend — gate delivery on `dossier_canary_cohort.decide_cohort(user_id, loop_canary_pct, enabled)`; **same module, keyed on `user_id`** instead of session_id; permanent 5% holdout, 95-cap inherited)
- `app/api.py` (extend — `GET /admin/loop-status`, `POST /admin/loop/disable`, `POST /admin/loop/enable`)
- `app/config.py` (`loop_canary_pct=0`)

**Dependencies:** Slice 8. Reuses `dossier_canary_cohort.py` with no modification (spec §10).

**Validation:** Unit: cohort bucketing on user_id deterministic + holdout invariant (the existing canary tests, re-pointed); kill-switch cycle disable→enable(clears override)→config-governs (the exact 4611401 fix semantics). Integration: `loop_canary_pct=5` delivers to ~5% of test users (minus holdout); `disable` halts sends instantly; status endpoint reflects override state.

**Rollback strategy:** `POST /admin/loop/disable` (runtime, no redeploy) or `loop_canary_pct=0`. The kill switch is *itself* the rollback mechanism for the whole system — this slice exists to make rollback instant.

---

### Slice 10 — Observability, hardening & Target driver

**Objective:** Production confidence: full metrics, cost circuit breaker, dead-letter handling, and migration from the in-process Bridge driver to the dedicated Target worker.

**Files:**
- `app/services/loop_scheduler.py` (extend — circuit breaker: halt drift jobs when `spent_llm_calls`/cycle > `loop_llm_calls_ceiling_per_cycle`; dead-letter sweep in the `maintenance` job)
- `app/services/loop_telemetry.py` (extend — schedule lag, tick latency p50/p95/p100, drift-hit rate, delivery success rate, dedup-suppression count, lock-contention + lease-reap counters)
- `app/enterprise/observability.py` (loop counters alongside the existing dossier counters)
- `app/worker.py` (new — the Target driver: a Render Background Worker running the same `tick()` loop; activated by `loop_driver="worker"`, which disables the in-process Bridge)
- `app/config.py` (`loop_llm_calls_ceiling_per_cycle`, set from shadow-observed rates)

**Dependencies:** Slices 4–9.

**Validation:** Admin endpoint shows all PART-4 metrics; circuit breaker trips on a synthetic drift storm and auto-resets next cycle; a poison job reaches `dead_letter` after `max_attempts` without blocking peers. **Bridge→Target cutover proof:** run both drivers simultaneously in staging → duplicate-work count = 0 (the §9.9 deliberate test), then flip `loop_driver="worker"` and confirm the Bridge stands down.

**Rollback strategy:** `loop_driver="in_process"` reverts to the Bridge driver (proven since Slice 4). Circuit breaker and dead-letter are additive guards — reverting removes protection but breaks nothing. Worker service can be scaled to zero on Render independently of the web service.

---

## PART 2 — DATABASE PLAN

### New tables (5) + 1 extension

**Schedule registry (current-state):**

| Table | Key columns | Notes |
|---|---|---|
| `scheduled_jobs` | `id` uuid PK, `job_type`, `target_key`, `period_bucket`, `state`, `next_run_utc`, `cadence` (null for drift), `catch_up_window_s`, `attempts`, `max_attempts`, `holder_id`, `lease_expires_utc`, `fence_token`, `payload_json`, `last_generated_at`, `created_at`, `updated_at` | The "head" of the loop. `UNIQUE(job_type, target_key, period_bucket)` is the enqueue-idempotency + drift-coalescing constraint. |

**Single-flight lease:**

| Table | Key columns | Notes |
|---|---|---|
| `job_locks` | `lock_name` PK, `holder_id`, `acquired_utc`, `lease_expires_utc`, `fence_token` (monotonic) | Namespaced (`loop:tick`, `loop:job:{id}`). Acquire = atomic conditional UPSERT (spec §4.2). |

**Append-only audit (immutable):**

| Table | Key columns | Notes |
|---|---|---|
| `job_runs` | `id` PK, `job_id`, `work_key`, `job_type`, `target_key`, `period_bucket`, `started_utc`, `finished_utc`, `outcome`, `spent_llm_calls`, `drift_hit`, `error`, `holder_id`, `fence_token` | **No UPDATE/DELETE in any repo.** The forensics + idempotency-lookup layer. `dossier_revision` analogue. |

**Delivery (current-state + dedup constraint):**

| Table | Key columns | Notes |
|---|---|---|
| `delivery_ledger` | `id` PK, `content_key` **UNIQUE**, `target_key`, `channel`, `content_hash`, `artifact_ref`, `status`, `attempts`, `not_before_utc`, `created_at`, `delivered_at` | The `UNIQUE(content_key)` is the duplicate-delivery guarantee enforced below the app layer (spec §3.2). |
| `notifications` | `id` PK, `user_id`, `kind`, `body_json`, `read_at`, `created_at` | The in-app channel sink; frontend polls it. First channel, zero third-party infra. |

**Extension (additive `ALTER`):**

| Table | Added columns | Notes |
|---|---|---|
| `briefing_sessions` | `content_hash`, `delivery_channel` (both nullable) | Completes the existing `pending → generated → delivered` ladder; no row rewrite. |

### Migration

- **One file: `005_continuous_loop.sql`** — five `CREATE TABLE IF NOT EXISTS` + indexes + two `ALTER TABLE ... ADD COLUMN`. Header comment documenting the spec's design principles (003/004 precedent).
- Apply order: after `004_company_dossier.sql`. Registered in `app/startup.py` with the `db_table_count` before/after guard.
- **No data migration** — tables start empty; population is organic (Slice 6 generation, Slice 8 delivery).
- **Rollback:** tables inert without flags; rollback = flags off. The `ALTER` columns are nullable and ignored by all existing readers. DDL never needs reverting (additive, unused until wired).

### Indexes

| Index | Table | Purpose |
|---|---|---|
| `UNIQUE(job_type, target_key, period_bucket)` | `scheduled_jobs` | enqueue idempotency + drift coalescing |
| `(state, next_run_utc)` | `scheduled_jobs` | the `select_due` hot path — the loop's most frequent query |
| `(lease_expires_utc)` | `scheduled_jobs` | lease reaping scan |
| PK `(lock_name)` | `job_locks` | O(1) lock acquire |
| `(work_key, outcome)` | `job_runs` | idempotency short-circuit lookup (§3.1) |
| `(job_id, started_utc)` | `job_runs` | per-job run history |
| `UNIQUE(content_key)` | `delivery_ledger` | duplicate-delivery hard stop |
| `(status, not_before_utc)` | `delivery_ledger` | `delivery_flush` drain query |
| `(user_id, read_at)` | `notifications` | inbox poll (unread first) |

### Relationships

```
scheduled_jobs ──< job_id ── job_runs            (one job, many run attempts)
scheduled_jobs ── target_key ──┐                 (logical join, no FK — user_id or normalized ticker)
                               ├─ delivery_ledger.target_key
                               └─ notifications.user_id
job_locks  — namespaced advisory, no FK (lock_name is the key)
delivery_ledger ── artifact_ref ── briefing_sessions / notifications   (logical pointer)
DIRTY SIGNAL (read-only, no FK):  dossier_revision, thesis_deltas  ──read──>  loop_drift
```

No FK from the loop into `thesis_versions`, `dossier_revision`, or `ticker_memory` — the loop **reads** those as the dirty signal and joins logically by ticker/user, keeping it independent of those subsystems' lifecycles (the dossier spec's §2.3 discipline).

---

## PART 3 — SERVICE PLAN

Follow `app/services/` conventions: module-level async functions, null-object on `session=None`, no business logic in repos. Four services, each with a hard boundary.

| Service | File | Responsibilities | Does NOT |
|---|---|---|---|
| **Scheduler service** | `loop_scheduler.py` | Own `tick()`: acquire tick lock → reap leases → `select_due` → per-job claim/run/record/reschedule. Cadence + `period_bucket` resolution (user-local tz). Circuit breaker. Backpressure (`max_jobs_per_tick`). Dispatch `job_type → producer`. | Never sends. Never computes briefing/watchlist content. Never decides materiality. |
| **Lock service** | `loop_lock_service.py` | Lease acquire/renew/release, expiry reaping, fence-token issue + check. The only module that writes `job_locks`. | No knowledge of jobs, producers, or delivery — pure mutual-exclusion primitive. |
| **Delivery service** | `loop_delivery_service.py` | `flush()`: drain ledger → guardrails (quiet hours, caps, mute, severity floor) → channel send → status mark. Cohort gate (canary). Fence-checked sends. | Never generates artifacts. Never bypasses the `content_key` constraint. Guardrails live here, nowhere else. |
| **Producer interface** | `loop_producers.py` | Thin bindings: `run_daily_brief`, `run_watchlist_scan`, `run_dossier_refresh`. Call existing producers through their existing interfaces; compute `content_hash`; write ledger + `BriefingSession`. Drift gate (clean → template, dirty → spend). | Never reimplements generation. Never sends. Never schedules. |

**Supporting modules:** `loop_drift.py` (dirty-signal reader, spec §5.1), `loop_telemetry.py` (9G telemetry/kill-switch clone), `loop_repo.py` + `loop_delivery_repo.py` (persistence).

**Boundary rules (enforced in review):**
1. Only the scheduler claims/runs jobs; only the delivery service sends; only producers generate. No service crosses two of those roles.
2. Every state transition is paired with a `job_runs` append **in the same transaction** — a run without an audit row must be impossible by construction (the dossier plan's facet+revision rule, applied to jobs).
3. The lock service is the *only* writer of `job_locks`; every other service requests leases through it, never touches the table.
4. Materiality is read, never defined (spec §5.4): `loop_drift` consumes `dossier_revision`/`thesis_deltas` and adds no threshold of its own.

---

## PART 4 — FAILURE TESTING

The loop's correctness *is* its failure behavior. Each of the spec §9 failures gets a dedicated, repeatable test. The four the brief names explicitly, plus the rest:

### Duplicate-execution testing
- **Replay test:** invoke the same occurrence twice (same `work_key`) → assert producer called once, second short-circuits to `succeeded`, one `job_runs` row marked short-circuited.
- **Redeploy-mid-run:** in staging, trigger a deploy while a job runs → assert no duplicate side effect (ledger row count unchanged, `content_key` collision suppressed).
- **Double-driver:** run Bridge + Target simultaneously (the §9.9 deliberate test) → assert duplicate-work count = **0**. This is the gate for every rollout step.
- **Invariant:** duplicate-delivery count is monitored continuously and is a **release blocker** at any non-zero value.

### Lock-contention testing
- **N-way acquire race:** spin up K concurrent `acquire(loop:tick)` → exactly one token returned, K−1 back off cleanly.
- **Lease renewal under load:** a long-running job heartbeats past one lease duration → lease never expires while the holder lives; assert no reap.
- **Contention counter:** assert the telemetry lock-contention counter increments on losers (observability sanity).
- **Postgres `SKIP LOCKED` vs SQLite fallback:** the same contention test passes on both backends (the stack runs SQLite local, Postgres prod).

### Restart-recovery testing
- **Crash mid-`running`:** SIGKILL a worker holding a job → assert next tick reaps the expired lease, returns job to `scheduled`, increments `attempts`, and re-runs exactly once (work_key absorbs any completed side effect).
- **Lease-expiry reclaim:** artificially expire a lease → another worker reclaims; fence token increments; the original holder's late write (if any) is fence-rejected.
- **Missed-tick catch-up vs skip:** simulate a 40-minute outage → a brief within its `catch_up_window` runs; one past the window transitions to `skipped_stale`, not delivered. Simulate a 3-day outage → assert no backlog flood (all stale occurrences skipped, only the current bucket runs).
- **DB-unavailable:** drop the DB session → loop degrades to no-op (null-object, `connection.py` pattern), no crash; resumes cleanly when DB returns.

### Dead-letter testing
- **Poison job:** bind a job to a producer that deterministically raises → assert it retries with backoff to `max_attempts`, then transitions to `dead_letter`, fires an alert, and is removed from the live `select_due` set.
- **Non-blocking:** assert a dead-lettering job does **not** stall its peers (per-row claim, no shared queue head) — run a poison job alongside healthy jobs, confirm healthy ones complete on schedule.
- **Inspectability:** dead-lettered jobs remain queryable with their full `job_runs` failure history for postmortem.

### Plus (spec §9 completeness)
- **Cost runaway:** synthetic drift storm pushes `spent_llm_calls` over ceiling → circuit breaker halts drift jobs, cadence/templated continue, auto-resets next cycle.
- **Backpressure:** enqueue 10× `max_jobs_per_tick` → drains oldest-first across ticks, lag metric rises and alarms, nothing melts.
- **Schema-ahead-of-code:** inject an `unknown_job_type` row → job → `skipped` + logged, old code unaffected (rolling-deploy safety).

**Harness:** unit tests on in-memory SQLite + a Postgres test DB for lock semantics (existing `pytest.ini`/`conftest.py`); integration tests against the test DB; the double-driver and crash tests run in staging with two real instances.

---

## PART 5 — ROLLOUT SEQUENCE

Identical discipline to 9G, reusing its cohort + kill switch + telemetry. Each stage has an exact, measured gate; the kill switch (`POST /admin/loop/disable`) halts delivery instantly at any stage, no redeploy.

### Shadow stage
**Config:** `loop_enabled=True, loop_shadow=True, loop_canary_pct=0, loop_driver="in_process"`
**Behavior:** loop runs, producers generate, drift gates, ledger fills — **zero sends.**
**Advancement criteria (all required):**
- Schedule lag ≤ 1 tick interval, sustained 72h.
- Tick latency p100 < tick interval.
- **Duplicate-delivery count = 0** under a deliberate double-driver run and a forced redeploy.
- Idempotency holds across ≥1 real production deploy (work_key short-circuits observed).
- Drift-hit rate tracks the substrate event rate (not stuck at 0 or 1) — proves §5 gating works.
- Cost: `spent_llm_calls`/cycle within projected envelope; a quiet test cohort costs ~0.
- Zero unhandled exceptions in the tick loop over the window.

### Internal stage
**Config:** `loop_shadow=False`, delivery cohort restricted to **own `user_id`(s) only**.
**Behavior:** real in-app deliveries to the team.
**Advancement criteria:**
- Read your own daily briefs for **7 consecutive days** — cadence feels right, content is correct, no 3am notifications (quiet hours verified live).
- Guardrails verified end-to-end: a muted name suppresses delivery (still generates); frequency cap holds; severity floor filters.
- Delivery success rate ≥ target on the in-app channel.
- Zero duplicate notifications in the inbox over the week.

### 5% canary stage
**Config:** `loop_canary_pct=5` (CRC32 on `user_id` via the reused `dossier_canary_cohort`; permanent 5% holdout, 95-cap).
**Behavior:** ~5% of users receive real briefings; a held-out 5% never does (the comparison arm).
**Advancement criteria (sustained 72h or ≥200 delivered, whichever later):**
- Delivery success rate ≥ target.
- **Duplicate-delivery count = 0** (non-negotiable, monitored continuously).
- Unsubscribe/mute rate below threshold (the user-fatigue gate).
- Cost/cycle ≤ `loop_llm_calls_ceiling_per_cycle`; cost scales **linearly**, not exponentially, with cohort size.
- Dead-letter rate ~0; schedule lag flat.
- No regression to the concurrently-running dossier canary or `/ask` latency.

### Ramp
**Config:** `loop_canary_pct: 5 → 25 → 50 → 95` (hold the 5% holdout permanently).
**Per-step gate (each step dwells until met):**
- All 5%-stage criteria still green at the larger N.
- Cost remains linear in cohort size (the exponential-blowup tripwire).
- Mute/unsubscribe below threshold at the new exposure.
- Schedule lag and tick latency flat (no scaling cliff as job volume grows).
- **Any** duplicate delivery, cost-ceiling breach, or lag spike → halt, do not advance; kill switch available for instant rollback.

> The 5% holdout is permanent post-GA — it is the standing control arm for measuring the loop's effect on retention, exactly as the dossier canary retains its holdout.

---

## PART 6 — DEPENDENCIES (what 10A must deliver before 10B / 10C / 10D)

10A is the keystone; 10B–10D are consumers. The contracts each later phase depends on:

### Before Phase 10B (Watchlist Intelligence elevation)
- **Stable producer-binding interface** (`loop_producers.run_watchlist_scan`) so 10B's consolidated watchlist service can be swapped in behind it without touching the scheduler.
- **The drift signal** (`loop_drift.is_dirty`) operational — 10B's per-name intelligence regenerates on drift, not on a timer.
- **The flatfile→table decision deferred cleanly:** 10A reads targets via `watchlist_service`, so 10B owns the `watchlist_entries` migration without 10A blocking on it. 10A must **not** hard-code the flatfile path anywhere except behind that interface.

### Before Phase 10C (Daily Briefing, pushed)
- **The full delivery spine**: `delivery_ledger`, `delivery_flush`, the guardrail boundary (quiet hours/caps/mute/severity), and `content_key` dedup — all shipped and proven in 10A's in-app channel.
- **Channel abstraction** in `loop_delivery_service` so 10C adds `email`/`push` as new `channel` enum values, not a rewrite. The `notifications` (in-app) channel is the reference implementation.
- **The canary + kill switch** (`loop_telemetry`, `/admin/loop/*`) so 10C's broader push rollout reuses the exact rollout ladder.
- **Cadence resolution with user-local tz** (spec §2.3) — 10C's "7am in the user's zone" depends on it existing in 10A.

### Before Phase 10D (Portfolio Intelligence)
- **A proven drift→generate→deliver loop** that 10D's portfolio-risk job (`run_portfolio_risk`) plugs into as one more `job_type` + producer binding — no new loop machinery.
- **The `target_key` keyspace generalized beyond user/ticker** to accept `portfolio_id` (already a string key; 10D adds a producer, not a schema change to `scheduled_jobs`).
- **The cost circuit breaker** (Slice 10) hardened, because portfolio risk fans out across holdings × cross-exposures and is the heaviest producer — 10D must inherit a working ceiling, not discover the need for one.
- **The regulatory content filter** lives in 10D's producer + the delivery guardrail layer; 10A must keep the guardrail boundary the single chokepoint so 10D can insert "risk-surfacing-not-advice" enforcement in exactly one place.

> **The contract in one line:** after 10A, every later phase is *"bind a producer to a `job_type` and let the loop run it"* — scheduling, locking, idempotency, drift-gating, delivery, canary, and kill switch are solved once, here.

---

## PART 7 — IMPLEMENTATION ORDER

Sequenced so production risk is monotonically bounded; every week ends shippable and revertible, and nothing reaches a user until Week 5.

**Week 1 — Foundations (no autonomous behavior)**
- Days 1–2: Slice 1 (migration + models) → deploy. Tables exist, empty.
- Days 3–5: Slice 2 (lock service + dual-backend tests) → deploy. The trust foundation, fully tested before anything races it.

**Week 2 — Persistence + driver (no producers, no spend)**
- Days 1–2: Slice 3 (repos + unit tests) → deploy dark.
- Days 3–5: Slice 4 (scheduler tick, no-op jobs, Bridge driver behind `loop_enabled=off`) + Slice 5 (idempotency). Staging two-instance + crash tests.

**Week 3 — Shadow generation**
- Day 1: Slice 6 (producer bindings) → flip `loop_enabled=on`, `loop_shadow=on` in production. Generation accumulates; **zero sends.**
- Days 2–5: Slice 7 (drift gating) → confirm cost collapses to near-zero on quiet names. Monitor lag, latency, cost, drift-hit rate.
- **Gate:** Shadow-stage advancement criteria (PART 5) met before Week 4.

**Week 4 — Delivery built, still shadowed**
- Days 1–3: Slice 8 (delivery service, in-app channel, guardrails) — tested with `loop_shadow=off` to **test users in staging only**, then `loop_shadow=on` for the production deploy.
- Days 4–5: Slice 9 (canary + kill switch, 9G reuse) + admin endpoints.

**Week 5 — First real users (the consequential flip)**
- Day 1: **Internal stage** — `loop_shadow=off`, cohort = own user_id. Read your own briefings.
- Days 2–5: live for the week; verify cadence, quiet hours, guardrails, zero duplicates. **Rollback at any sign = `POST /admin/loop/disable`, instant.**

**Week 6 — Canary, ramp & hardening**
- Slice 10 (observability, circuit breaker, dead-letter, Bridge→Target cutover).
- 5% canary → ramp 5→25→50→95 per PART 5 gates, dwelling at each step.

**Standing rule:** flags are independent and layered — `loop_enabled` (master), `loop_shadow` (no-send), `loop_canary_pct` (exposure). Generation can run for weeks with sends off; sends can be killed without losing generated artifacts (they bank in the ledger). The loop's dataset only ever grows under governed, idempotent writes.

---

## DELIVERABLE SUMMARY

1. **Build slices:** 10 (PART 1) — schema → lock → repos → scheduler tick → idempotency → producers → drift → delivery → canary/kill-switch → observability/Target-driver. Each with objective, files, dependencies, validation, rollback.
2. **Database plan:** 5 new tables + 1 additive `ALTER`, single migration `005_continuous_loop.sql`, idempotent, startup-registered, flag-gated, rollback = flags off (PART 2).
3. **Service plan:** scheduler / lock / delivery services + producer-interface bindings, each with a hard role boundary and the "one transition, one audit row" rule (PART 3).
4. **Failure testing:** duplicate-execution, lock-contention, restart-recovery, dead-letter — plus cost-runaway, backpressure, schema-ahead, DB-down — each a repeatable test; duplicate-delivery=0 is the standing release blocker (PART 4).
5. **Rollout sequence:** shadow → internal → 5% canary → ramp, each with exact measured advancement criteria, reusing the 9G cohort + kill switch; permanent 5% holdout (PART 5).
6. **Phase dependencies:** the exact contracts 10A must deliver before 10B (producer interface + drift + flatfile decoupling), 10C (delivery spine + channel abstraction + canary), and 10D (generalized target_key + cost ceiling + single guardrail chokepoint) (PART 6).
7. **Production rollout:** 6 weeks, dark-deploy then layered flag-flips; generation Week 3, delivery built Week 4, first users Week 5, ramp Week 6; three independent flags revertible at all times; kill switch is the instant rollback (PART 7).

*End of implementation plan. No code, no migrations, no implementation in this document — execution may begin immediately against it.*
