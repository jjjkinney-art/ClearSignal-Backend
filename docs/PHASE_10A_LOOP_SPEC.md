# Continuous Intelligence Loop — Architecture Specification

**Phase:** 10A · the keystone primitive
**Status:** Design — not yet implemented
**Audience:** Principal/staff engineers, backend
**Scope:** Design only. No code, no migrations, no implementation in this document.
**Prerequisite read:** `COMPANY_DOSSIER_SPEC.md` (the substrate this loop consumes), Phase 9G canary infrastructure (`dossier_canary_cohort.py`, `dossier_canary_telemetry.py` — reused wholesale here).

---

## 0. Purpose and one-paragraph thesis

ClearSignal can analyze a company on demand, remember what it concluded, evolve that conclusion, and model the company in a persistent dossier. Every one of those capabilities is **request-driven**: nothing happens unless a user asks. A `grep` for any scheduler — `apscheduler`, `celery`, `cron`, a persisted tick loop — returns nothing across `app/`. The `BriefingSession` table already models a `delivered` state, but no code delivers. This is the precise gap between an **analysis tool** (responds when asked) and an **intelligence platform** (runs whether or not you are looking).

The **Continuous Intelligence Loop** is the missing architectural primitive: a durable, single-flight, idempotent scheduler that runs existing analysis producers on a cadence, regenerates work **only when the underlying substrate has materially changed** (drift-triggered, not timer-burning), and hands results to a delivery layer that is fully decoupled from generation. It does not add intelligence. It adds a heartbeat to the intelligence already built.

> **Design principle #1 — The loop orchestrates; it never re-derives.** Watchlist scanning (`watchlist_monitor.py`), briefing generation (`morning_brief_service.py`), drift detection (`thesis_drift.py`), and dossier reads already exist. The loop is the conductor that wakes them on schedule and routes their output. It contains zero analysis logic of its own. If a behavior can be expressed as "call an existing producer," it must be — the loop's surface area is scheduling, locking, idempotency, and delivery, nothing more.

---

## 1. The job model

The unit of work is a **job**: a typed, parameterized intent to run one producer against one target for one time bucket. Jobs are not threads or coroutines — they are **rows** with a state machine. The in-process runtime claims rows, executes the producer, and writes the outcome back. This makes the loop's entire state inspectable, recoverable, and idempotent by construction.

### 1.1 Job taxonomy

| `job_type` | Producer it calls | Cadence model | Target granularity |
|---|---|---|---|
| `watchlist_scan` | `watchlist_monitor.watchlist_change_detector` | drift-triggered (§5) | one user's watchlist |
| `daily_brief` | `morning_brief_service.generate_morning_brief_v2` | cadence (user-local morning) | one user |
| `dossier_refresh` | dossier extraction (existing post-dispatch path, invoked headless) | drift-triggered | one ticker |
| `delivery_flush` | delivery layer (§6) | cadence (frequent tick) | the delivery ledger |
| `maintenance` | lease reaping, dead-letter sweep, telemetry roll-up | cadence (infrequent) | global |

> The taxonomy is **closed and additive**: new job types arrive as new enum values + a producer binding, never by overloading an existing type. A `job_type` the runtime does not recognize is a no-op that logs `unknown_job_type` and transitions to `skipped` — forward compatibility for rolling deploys where the schedule registry is ahead of the code.

### 1.2 Job lifecycle (state machine)

```
            ┌─────────────┐
            │  scheduled  │  next_run_utc in the future
            └──────┬──────┘
                   │  tick: next_run_utc ≤ now AND lock acquired
                   ▼
            ┌─────────────┐
            │   claimed   │  holder + lease set; heartbeat running
            └──────┬──────┘
                   ▼
            ┌─────────────┐
            │   running   │  producer executing
            └──────┬──────┘
        ┌──────────┼───────────────┬────────────────┐
        ▼          ▼               ▼                ▼
  ┌──────────┐ ┌────────┐  ┌──────────────┐  ┌─────────────┐
  │succeeded │ │ failed │  │ skipped_stale│  │ dead_letter │
  └────┬─────┘ └───┬────┘  └──────────────┘  └─────────────┘
       │           │  attempts < max → back to scheduled (backoff)
       │           │  attempts ≥ max → dead_letter
       ▼           ▼
  reschedule next occurrence (cadence jobs) / consume (one-shot jobs)
```

| State | Meaning | Terminal? |
|---|---|---|
| `scheduled` | Eligible to run at/after `next_run_utc`. | no |
| `claimed` | A worker holds the lease and is about to run. Crash-recoverable via lease expiry (§4.3). | no |
| `running` | Producer executing; heartbeat renewing the lease. | no |
| `succeeded` | Producer returned cleanly; outcome recorded. | per-occurrence |
| `failed` | Producer raised; will retry with backoff until `max_attempts`. | no (until dead) |
| `skipped_stale` | Scheduled time is older than the catch-up window (§7.2) — the moment has passed; do not run. | per-occurrence |
| `dead_letter` | Exhausted `max_attempts`. Removed from the live queue, retained for inspection, alerts fired. | yes |

### 1.3 Job row shape

| Field | Type | Notes |
|---|---|---|
| `id` | uuid | |
| `job_type` | enum | §1.1 |
| `target_key` | str | `user_id`, normalized `ticker`, or `__global__`. The drift/idempotency keyspace. |
| `period_bucket` | str | The time bucket this occurrence belongs to, e.g. `2026-06-12` (daily) or `2026-06-12T14:00Z` (hourly). Half of the idempotency key (§3). |
| `state` | enum | §1.2 |
| `next_run_utc` | ts | When this occurrence becomes eligible. |
| `cadence` | str / null | cron-ish spec for cadence jobs; null for one-shot drift jobs. |
| `catch_up_window_s` | int | How late is still worth running (§7.2). |
| `attempts` | int | Retry counter. |
| `max_attempts` | int | Default 4 (mirrors the existing synthesis retry posture). |
| `holder_id` | str / null | The worker instance currently claiming it. |
| `lease_expires_utc` | ts / null | Lease deadline (§4.3). |
| `payload_json` | text | Producer parameters (e.g. which facets, which channel). |
| `created_at` / `updated_at` | ts | |

> **Grounding note.** This is the same modeling discipline as the dossier: a single-row "current state" table (`scheduled_jobs`, here) plus an append-only audit log (`job_runs`, §8). Reuse the SQLAlchemy + numbered-SQL-migration stack (`app/db/models.py`, next migration `005_continuous_loop.sql`, a `loop_repo.py` under `app/db/repositories/`). No new datastore.

---

## 2. The scheduler

> **Design principle #2 — The schedule lives in the database, never in process memory.** An in-process timer dies with the instance, double-fires behind a load balancer, and silently stops on a spun-down free tier. The `scheduled_jobs` table is the single source of truth for *what runs when*; any number of workers may drive it because the lock (§4) makes concurrent drivers safe.

### 2.1 The driver — two tiers, one lock

The thing that *advances time* is the **tick driver**. There are two viable hosts on Render, and the lock makes them interchangeable and even co-existable:

| Tier | Driver | When |
|---|---|---|
| **Bridge (ship first)** | An in-process `asyncio` task in the FastAPI app, started in the `startup.py` lifespan, that calls `tick()` every `loop_tick_interval_s`. | Phase 10A shadow + internal. Zero new infra. Safe on one instance; safe on N instances *because of the lock*. |
| **Target (harden to)** | A dedicated **Render Background Worker** (or Cron Job) running the same `tick()` loop, with the web service driver disabled. | Before canary ramp. Isolates scheduling from request-serving failure domains; survives web-tier autoscaling/spin-down independently. |

The `tick()` function is identical in both hosts. Migration from Bridge to Target is a config flip (`loop_driver = "in_process" | "worker"`), not a rewrite — the proof that the lock is doing its job is that running *both at once* produces no duplicate work.

> **Render-specific reality this addresses:** the web tier can run multiple instances behind the LB (duplicate timers), can spin down on lower tiers (missed ticks → §7.2 catch-up), and restarts on every deploy (in-flight jobs orphaned → §4.3 lease recovery). The DB-as-truth + lease-lock design makes all three non-events.

### 2.2 What a tick does

A single `tick()` is deliberately small and bounded:

1. **Acquire the tick lock** (`lock_name = "loop:tick"`, §4). If another worker holds it, return immediately — no two ticks overlap.
2. **Reap** expired leases (jobs whose `lease_expires_utc < now` while in `claimed`/`running` → return to `scheduled`, increment `attempts`).
3. **Select** up to `loop_max_jobs_per_tick` due jobs (`state = scheduled AND next_run_utc ≤ now`), ordered by `next_run_utc`. On Postgres, `SELECT ... FOR UPDATE SKIP LOCKED` is the optimization; the lease table is the portable fallback (SQLite local, Postgres prod — the stack already degrades gracefully).
4. **For each selected job**: claim → run producer → record outcome → reschedule or consume. Jobs within a tick run with bounded concurrency; a job that exceeds its own deadline is abandoned to lease expiry, not awaited forever.
5. **Release the tick lock.**

`loop_max_jobs_per_tick` is the backpressure valve (§9.7): a flood of due work drains over several ticks rather than melting one tick.

### 2.3 Cadence resolution and time zones

> **Design principle #3 — Schedules are stored in UTC; user-facing cadence is resolved at render time.** A "7am daily brief" is stored as a cadence + the user's IANA tz, never as a fixed UTC instant. The next occurrence is computed with a tz library so DST shifts are correct automatically.

- Cadence jobs carry a cron-ish `cadence` + the target's timezone. On success, the next occurrence's `next_run_utc` and `period_bucket` are computed forward.
- Drift jobs have null `cadence` — they are enqueued on demand (§5) and consumed once.
- DST/clock-skew correctness is a render-time concern, not a storage concern, which keeps the `scheduled_jobs` rows immune to timezone politics.

---

## 3. Idempotency guarantees

> **Design principle #4 — Assume every job runs at least twice; design so the second run is a no-op.** Deploys reissue ticks, leases expire and reclaim, retries replay. Exactly-once execution is unattainable on commodity infra; **effectively-once side effects** are achievable and are the actual requirement.

Two layers, two keys.

### 3.1 Execution idempotency — the work key

Every job occurrence has a stable **work key**:

```
work_key = hash(job_type, target_key, period_bucket)
```

Before a producer runs, the runtime checks `job_runs` (§8) for a `succeeded` row with the same `work_key`. If one exists, the job short-circuits to `succeeded` **without invoking the producer**. This makes catch-up (§7.2) and retry safe: re-running "the daily brief for user U on 2026-06-12" after it already succeeded does nothing.

### 3.2 Delivery idempotency — the content key

Generation and delivery dedup on a different key, because identical content must not be sent twice even across separate job occurrences:

```
content_key = hash(target_key, channel, content_hash, period_bucket)
content_hash = hash(rendered artifact body)
```

The delivery ledger (§6) carries a `UNIQUE(content_key)`. A second attempt to deliver the same body to the same user on the same channel for the same bucket is **suppressed** at the database constraint — the strongest possible guarantee, enforced below the application layer. `content_hash` additionally means a name whose substrate did not change yields a *byte-identical* brief line, which the dedup layer can collapse (§5.3).

### 3.3 Producer idempotency contract

Each producer the loop calls must satisfy: **running it twice against unchanged substrate produces no additional durable side effect beyond the first.** The existing producers already approximate this — `morning_brief_service` is a pure function of substrate state; `watchlist_monitor` emits alerts that are deduped downstream. The contract is made explicit so future producers are held to it. Producers that must mutate state (e.g. `dossier_refresh`) inherit the dossier's own optimistic-concurrency + hysteresis guards (`COMPANY_DOSSIER_SPEC.md` §3.5, §8.3) — the loop adds no new mutation semantics.

---

## 4. The locking model

> **Design principle #5 — Single-flight is enforced by a lease, not a mutex.** A lock that cannot expire deadlocks the system the moment its holder crashes. Every lock in the loop is a **time-boxed lease** that a crashed holder forfeits automatically.

### 4.1 The lock table

| Field | Type | Notes |
|---|---|---|
| `lock_name` | str, PK | e.g. `loop:tick`, `loop:job:{id}`. Namespaced. |
| `holder_id` | str | Instance identity: `{host}:{pid}:{boot_uuid}`. |
| `acquired_utc` | ts | |
| `lease_expires_utc` | ts | `acquired + loop_lock_lease_s` (default 120s). |
| `fence_token` | bigint | Monotonic counter, incremented on every acquisition (§4.4). |

### 4.2 Acquire / renew / release

- **Acquire** is a single atomic compare-and-swap, expressed as a conditional `UPSERT`: *take the lock iff it is unheld or its lease has expired.* Two workers racing → exactly one row write wins; the loser sees zero rows affected and backs off. This is the entire mutual-exclusion guarantee, and it rides on the database's row-level atomicity rather than any application coordination.
- **Renew (heartbeat)**: while a job runs, the holder pushes `lease_expires_utc` forward on an interval well inside the lease (e.g. every `lease_s / 3`). A job that runs longer than one lease stays valid as long as its process is alive to heartbeat.
- **Release**: on completion, delete/clear the lock row. Crash before release → the lease simply expires and the next tick reaps it.

### 4.3 Crash recovery

If the holder dies mid-`running`:
1. Its heartbeat stops; `lease_expires_utc` is not pushed forward.
2. The next `tick()` reap step finds a `claimed`/`running` job whose lease expired, returns it to `scheduled`, and increments `attempts`.
3. Re-execution is safe because of §3.1 — if the dead process actually *finished the side effect* before dying, the `work_key` short-circuit catches it; if it died mid-side-effect, the producer's own idempotency (§3.3) absorbs the replay.

### 4.4 Fencing (the subtle one)

A holder can be **wrongly presumed dead** — paused by GC/CPU starvation past its lease, then resuming to write after another worker has taken over. The `fence_token` defends the side effect: every lease acquisition increments it, the holder carries its token into the producer, and any guarded write asserts *"my token ≥ the latest token for this lock."* A resurrected zombie holds a stale token and its write is rejected. In practice most loop side effects are already idempotent (§3), so fencing is the belt-and-suspenders layer for the few that are not (e.g. delivery sends).

---

## 5. Drift-triggered execution

> **Design principle #6 — The timer decides *when to check*; drift decides *whether to spend*.** Re-synthesizing every watched name on every tick multiplies LLM cost by (names × users × frequency) and produces briefings that say the same thing daily. The loop regenerates **only** when the substrate underneath a target has materially changed. This is the single most important cost-and-quality control in the design.

### 5.1 The dirty signal — reuse the existing change log

The substrate already emits change events; the loop does not need a new one. Two existing sources:

| Source | Emits | Already written by |
|---|---|---|
| `dossier_revision` (append-only) | a row per *material* facet change (debate reframed, moat axis flipped, catalyst fired) | dossier extraction, post-dispatch |
| `thesis_deltas` | stance change / conviction move beyond `material` magnitude | thesis evolution (`thesis_change_logic.py`, `thesis_drift.py`) |

A target is **dirty** for a job type if a qualifying row in either source is newer than the target's `last_generated_at` for that job type.

> **Anti-duplication:** the loop introduces no parallel change-detection. It *reads* `dossier_revision` and `thesis_deltas`, which already encode "what materially changed," using the same materiality predicates those subsystems already enforce (hysteresis, `material` magnitude). Defining a second notion of "changed" would create two sources of truth — exactly the failure the dossier spec's §5 forbids.

### 5.2 Two execution modes per job type

| Mode | Trigger | Cost posture |
|---|---|---|
| **Cadence** | `next_run_utc` arrives (e.g. daily brief at 7am local). | Always runs the *job*, but the producer renders a cheap "no material change" line for clean names — no LLM call. |
| **Drift** | A dirty signal lands for the target (e.g. a catalyst fired overnight). | Enqueues a one-shot job that *does* spend (re-synthesis / dossier refresh), because something real changed. |

The daily brief is therefore a **cadence job that fans out per watched name into "changed → spend / unchanged → template."** The expensive path is gated entirely behind §5.1 dirtiness. A quiet portfolio costs near-zero per day; an eventful one spends proportionally to what actually happened.

### 5.3 Drift coalescing

Multiple dirty signals for the same target within a window must **not** produce multiple jobs. Enqueue is idempotent on `(job_type, target_key, period_bucket)` — a second dirty signal in the same bucket finds the job already `scheduled` and is absorbed. Five catalysts firing on one name before the morning brief produce one regeneration, not five. This is the producer-side mirror of the delivery dedup in §3.2.

### 5.4 The materiality boundary is owned upstream

What counts as "material enough to spend" is **not** a loop parameter. It is whatever already cut a `dossier_revision` row or a `thesis_delta`. If the business wants briefings to react to smaller moves, the fix is to tune the upstream materiality thresholds (`τ_high`, hysteresis, `material` magnitude — already spec'd and tuned in 9G), not to add a competing knob in the loop. The loop stays a pure consumer of "material change" as defined by the systems that own that judgment.

---

## 6. Delivery separation

> **Design principle #7 — Generation and delivery are separate transactions with separate failure domains.** A briefing that generated successfully but failed to send must be re-sendable without re-generating. A send that the channel dropped must retry without re-billing an LLM call. The `BriefingSession.status` ladder already anticipates this; the loop completes it.

### 6.1 The split

```
  generation job            delivery job (delivery_flush, frequent cadence)
  ─────────────             ──────────────────────────────────────────────
  produce artifact   ──►    read undelivered ledger rows
  compute content_hash      enforce quiet hours / caps / mute (§6.3)
  write delivery ledger     send via channel
  status: generated         status: delivered | failed(retry) | suppressed
```

Generation **never sends.** It writes a row to the delivery ledger and stops. A separate, frequently-ticking `delivery_flush` job drains the ledger. This means: generation cost is paid once and banked; delivery is retried independently with its own backoff; and a channel outage degrades to "generated, not yet delivered" — visible, recoverable, never a lost briefing and never a double charge.

### 6.2 The delivery ledger

| Field | Type | Notes |
|---|---|---|
| `id` | uuid | |
| `content_key` | str, **UNIQUE** | §3.2 — the hard dedup constraint. |
| `target_key` | str | user. |
| `channel` | enum | `in_app` (ship first), `email`, `push` (later). |
| `content_hash` | str | body fingerprint. |
| `artifact_ref` | str | pointer to the generated `BriefingSession` / notification body. |
| `status` | enum | `pending` / `delivering` / `delivered` / `failed` / `suppressed`. |
| `attempts` | int | independent of the generation job's attempts. |
| `not_before_utc` | ts | quiet-hours / backoff deferral. |
| `created_at` / `delivered_at` | ts | |

> **Reuse:** `BriefingSession` (`status: pending → generated → delivered`) is the generation-side record; the delivery ledger is the send-side record. Extend `BriefingSession` with `content_hash` + `delivery_channel` (additive migration) rather than reshaping it. The in-app channel writes to a `notifications` table the frontend already polls patterns for — the cheapest channel to ship, and it needs no third-party integration.

### 6.3 Delivery guardrails (enforced at the boundary, not in prompts)

| Guardrail | Rule | Source |
|---|---|---|
| **Quiet hours** | No send outside the user's waking window; defer via `not_before_utc`. | per-user setting |
| **Frequency cap** | ≤ N pushes/day/user; overflow coalesces or drops by severity. | reuse `alert_prioritizer.py` severity |
| **Mute** | `mute_until` on the watch target suppresses delivery (still generates, for the in-app inbox). | watchlist entry |
| **Severity floor** | Below-threshold alerts never push; they remain in the pulled in-app view only. | `signal_scoring.py` |

Crucially these live in the **delivery layer**, so they apply uniformly across channels and cannot be bypassed by a producer. Generation is allowed to be chatty; delivery is the disciplined gate.

---

## 7. Scheduling edge cases

### 7.1 Overlap (the same job, twice, concurrently)
Prevented structurally: a job is claimed via the lease (§4) before it runs. A second worker selecting the same row fails the conditional claim and moves on. The tick lock additionally serializes the *selection* phase.

### 7.2 Missed ticks — catch-up vs. skip
After an outage (deploy, spin-down, crash), due jobs have piled up. Two behaviors, chosen per job by `catch_up_window_s`:

- **Within the window** (`now − scheduled_time ≤ catch_up_window`): run it. A 7am brief delivered at 7:40 after a deploy is still useful.
- **Past the window**: transition to `skipped_stale`. Three days of backlogged morning briefs after a long outage must **not** all fire — that is notification spam and stale information. The brief's window is a few hours, not days.

The `work_key` (§3.1) guarantees that catch-up never double-runs an occurrence that already succeeded before the outage.

### 7.3 Cadence drift / thundering herd
If all users share a 7am-UTC brief, every tick at 7am floods. Mitigations: (a) cadence resolves to *user-local* time (§2.3), spreading load across time zones naturally; (b) `loop_max_jobs_per_tick` (§2.2) drains bursts across ticks; (c) optional per-user jitter on the resolved minute. The loop should *spread*, never *spike*.

### 7.4 Clock skew between instances
All comparisons are against the database clock (`now()` in SQL), not instance wall-clocks, so lease and due-time decisions are consistent regardless of per-instance drift.

---

## 8. Observability

> **Design principle #8 — The loop is invisible by nature, so it must be relentlessly instrumented.** A request path announces its own failures to a waiting user. A background loop fails silently unless every tick, claim, run, and send is counted and inspectable. Observability is not a feature of the loop; it is a precondition for trusting it.

### 8.1 Durable audit — `job_runs` (append-only)

The dossier's `dossier_revision` analogue. One immutable row per execution attempt:

| Field | Notes |
|---|---|
| `id`, `job_id`, `work_key` | links back to the occurrence |
| `job_type`, `target_key`, `period_bucket` | |
| `started_utc` / `finished_utc` | latency = difference |
| `outcome` | `succeeded` / `failed` / `skipped_stale` / `dead_letter` |
| `spent_llm_calls` | cost proxy (§5) — 0 for templated/clean runs |
| `drift_hit` | bool — did this run find material change? |
| `error` | truncated traceback on failure |
| `holder_id`, `fence_token` | which worker, which lease generation |

Never updated, never deleted — the time-travel + forensics layer, exactly as `dossier_revision` is for the dossier.

### 8.2 In-process snapshot + admin surface

Reuse the 9G telemetry pattern (`dossier_canary_telemetry.snapshot()`) verbatim in shape. Expose:

- `GET /admin/loop-status` — current snapshot: per-job-type counts (scheduled/running/succeeded/failed/dead), schedule lag (max `now − next_run` among overdue), tick latency p50/p95/p100, drift-hit rate, delivery success rate, dedup-suppression count, LLM-calls-this-cycle vs ceiling, lock-contention counter, lease-reap counter, `enabled_override` state.
- `POST /admin/loop/disable` / `POST /admin/loop/enable` — the Tier-0 kill switch, **reusing the exact `force_disable` / `force_enable` (clears override) semantics** from `dossier_canary_telemetry.py`. One in-process flag, no redeploy, resets on restart, config governs when override is null.

### 8.3 The metrics that gate rollout

| Metric | Healthy | Why it matters |
|---|---|---|
| **Schedule lag** | ≤ 1 tick interval | proves the driver is actually advancing time |
| **Duplicate-delivery count** | **exactly 0** | the idempotency contract; non-zero is a release blocker |
| **Tick latency p100** | < tick interval | a tick must finish before the next begins |
| **Drift-hit rate** | matches substrate event rate | sanity that §5 gating works, not stuck on/off |
| **Delivery success rate** | ≥ target | the user-visible SLA |
| **LLM-calls / cycle** | ≤ ceiling | cost circuit breaker (§9.6) input |
| **Dead-letter rate** | ~0 | poison-job detector |

---

## 9. Failure recovery

> **Design principle #9 — Every failure degrades to a safe, named, recoverable state — never to silent loss or silent duplication.** The loop's job is to make "the instance died at 6:59am" a non-event.

| # | Failure | Detection | Recovery |
|---|---|---|---|
| 9.1 | **Instance crash mid-job** | lease stops renewing | next tick reaps expired lease → `scheduled` (attempts++); `work_key` + producer idempotency absorb any partial side effect (§3, §4.3) |
| 9.2 | **Missed ticks (outage)** | due jobs accumulate | catch-up within window, `skipped_stale` past it (§7.2); no backlog spam |
| 9.3 | **Poison job** (deterministic producer failure) | `attempts ≥ max_attempts` | → `dead_letter`, removed from live queue, alert fired; **does not block** other jobs (per-row claim, not a shared queue head) |
| 9.4 | **Partial delivery** (some recipients/channels failed) | per-row delivery ledger status | only `failed`/`pending` rows retry; `delivered` rows are immutable; no re-generation |
| 9.5 | **Zombie holder** (GC pause past lease) | fence token mismatch | stale-token write rejected (§4.4) |
| 9.6 | **Cost runaway** (drift storm → LLM flood) | `spent_llm_calls` this cycle > `loop_llm_calls_ceiling_per_cycle` | **circuit breaker**: halt drift jobs (cadence/templated continue), set a degraded flag, alert; auto-reset next cycle when under ceiling |
| 9.7 | **Backpressure** (more due than capacity) | due count > `loop_max_jobs_per_tick` | drain across ticks oldest-first; lag metric rises and is alertable; system slows, never melts |
| 9.8 | **DB unavailable** | session acquisition fails | **null-object degradation** — the loop becomes a no-op, exactly as the persistence layer already does when `DATABASE_URL` is unset (`connection.py`). No crash, no partial writes. Resumes when the DB returns. |
| 9.9 | **Duplicate drivers** (Bridge + Target both live) | — | non-event by design: the tick lock + per-job lease serialize them. This is the *test* for §4, run deliberately during the Bridge→Target migration. |
| 9.10 | **Schema ahead of code** (rolling deploy) | `unknown_job_type` | job → `skipped` + logged; old code ignores job types it predates (§1.1) |

---

## 10. Relationship to existing systems (anti-duplication)

> **Design principle #10 — The loop reuses 9G's rollout machinery wholesale.** Cohort assignment, kill switch, telemetry snapshot, and post-dispatch hook patterns were built and battle-tested in the dossier canary. The loop is their second customer, not a reimplementation.

| System | Owns | Loop relationship | Anti-duplication rule |
|---|---|---|---|
| **`dossier_canary_cohort.py`** | CRC32 deterministic bucketing, 5% holdout, 95-cap. | Loop canary buckets on `user_id` using this module **unchanged**. | The loop adds no bucketing logic. `decide_cohort` is keyed on user_id instead of session_id — same function, different key. |
| **`dossier_canary_telemetry.py`** | kill-switch override, snapshot pattern. | Loop's kill switch and `/admin/loop-status` mirror this module's API exactly. | No second kill-switch implementation; the `force_disable`/`force_enable`(clear-override)/`get_enabled(config)` contract is copied, not reinvented. |
| **`morning_brief_service.py`** | briefing generation (v1/v2, narrative/debate/priority shifts). | Loop *calls* `generate_morning_brief_v2`. | The loop never generates briefing content. It schedules the call and routes the result. |
| **`watchlist_monitor.py` / `watchlist_service.py`** | drift/freshness/fragility alerts, watch targets. | Loop *calls* `watchlist_change_detector`; reads watch targets via `watchlist_service`. | The loop does not reimplement watchlist scanning. It also does **not** depend on 10B's table migration — it reads targets through the existing service interface, decoupling 10A from 10B. |
| **`dossier_revision` / `thesis_deltas`** | the material-change record. | Loop reads them as the dirty signal (§5.1). | The loop defines no parallel "changed" predicate. Materiality is owned upstream (§5.4). |
| **`BriefingSession` table** | the `pending→generated→delivered` ladder. | Loop completes the ladder: generation sets `generated`, delivery sets `delivered`. | Extend additively (`content_hash`, `delivery_channel`); never reshape. |
| **`connection.py` null-object mode** | graceful DB-absent degradation. | Loop inherits it (§9.8). | No bespoke "DB down" handling; the existing pattern covers it. |
| **`alert_prioritizer.py` / `signal_scoring.py`** | severity/priority. | Delivery guardrails (§6.3) consume severity. | The loop does not re-rank; it gates delivery on existing scores. |

**The clean mental model:**
- 9G canary infra = *"how we roll a change out safely."*
- producers (brief, watchlist, dossier) = *"the work."*
- **the loop = *"when the work runs, exactly once in effect, and how its result reaches the user."***

The loop is plumbing. Every drop of intelligence flowing through it was built in Phases 1–9.

---

## 11. Configuration

Mirror the `dossier_injection_*` naming and the all-off-by-default posture (`config.py`):

| Setting | Default | Role |
|---|---|---|
| `loop_enabled` | `False` | master gate (config arm of the kill switch). |
| `loop_shadow` | `False` | run + generate + write ledger, but **deliver nothing** (shadow stage). |
| `loop_canary_pct` | `0` | % of users (CRC32 on user_id) receiving real delivery; permanent 5% holdout, 95 cap. |
| `loop_driver` | `"in_process"` | `in_process` (Bridge) → `worker` (Target). |
| `loop_tick_interval_s` | `60` | driver cadence. |
| `loop_max_jobs_per_tick` | `50` | backpressure valve (§9.7). |
| `loop_lock_lease_s` | `120` | lease TTL (§4). |
| `loop_llm_calls_ceiling_per_cycle` | tuned | cost circuit breaker (§9.6). |
| `loop_delivery_channel` | `"in_app"` | first channel; email/push later. |

---

## 12. Rollout plan

Identical discipline to 9G, reusing its cohort + kill-switch + telemetry:

| Stage | Config | Gate to advance |
|---|---|---|
| **Shadow** | `loop_enabled=True, loop_shadow=True, loop_canary_pct=0` | Loop runs, jobs generate, delivery ledger fills — **zero sends.** Validate: schedule lag ≤ 1 tick, tick p100 < interval, **duplicate-delivery count = 0** under deliberate double-driver (§9.9), idempotency holds across a forced redeploy, drift-hit rate tracks substrate events. |
| **Internal** | `loop_shadow=False`, deliver to own `user_id` only | Read your own briefings for a week. Generation-quality and cadence-feel bugs surface here. Validate quiet-hours/caps/mute (§6.3). |
| **Canary 5%** | `loop_canary_pct=5` | CRC32 on user_id (reused module), permanent control arm. Gate: delivery success rate, unsubscribe/mute rate, cost/cycle ≤ ceiling, dead-letter ~0. |
| **Ramp** | `5 → 25 → 50 → 95` | Each step: no duplicate deliveries, delivery SLA held, mute/unsubscribe below threshold, cost linear-not-exponential, schedule lag flat. Hold the 5% holdout permanently. |

The kill switch (`POST /admin/loop/disable`) halts all delivery instantly, no redeploy, at any stage — the same Tier-0 control the dossier canary already has.

---

## 13. Open questions for implementation phase

None block the architecture; all are calibration:

1. **Driver host for Target tier** — Render Background Worker vs Cron Job. Lean: Background Worker running the `tick()` loop (Cron's minimum granularity and cold-start cost fit poorly with a 60s tick). Confirm against Render plan limits.
2. **`loop_llm_calls_ceiling_per_cycle`** — set from observed shadow-stage drift-hit rates × covered names; per-tier, not global, once real traffic exists.
3. **In-app `notifications` table shape** — confirm the frontend's existing polling contract so the first channel needs no new client work.
4. **Catch-up windows per job type** — daily brief (hours) is clear; `dossier_refresh` and `watchlist_scan` windows want tuning against how stale a regenerated artifact may acceptably be.
5. **Lease TTL vs longest producer** — 120s assumes producers finish well inside it; a multi-facet `dossier_refresh` invoked headless may run longer and lean harder on heartbeat renewal. Measure the p100 producer runtime in shadow and size the lease at ~3× it.
6. **Fence-token enforcement scope** — required for delivery sends; likely unnecessary for idempotent generation. Confirm which side effects are non-idempotent and fence only those.

---

*End of specification. Design only — implementation, schema migrations, and code are out of scope for this document.*
