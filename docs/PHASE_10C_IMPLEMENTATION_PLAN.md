# Briefing & Delivery — Implementation Plan

**Phase:** 10C · the experience layer
**Source of truth:** `docs/PHASE_10C_BRIEFING_AND_DELIVERY_SPEC.md` (approved — this plan does not redesign anything)
**Status:** Execution blueprint — no code in this document
**Convention basis:** All file paths, flags, and table conventions reference the existing codebase (10A loop, 10B watchlist). 10C reuses the 10A delivery spine (`loop_delivery_service.py`, `delivery_ledger`, `notifications`), the 10A/9G canary machinery (`loop_canary_cohort.py`, `loop_canary_telemetry.py`), and the existing guardrail boundary **wholesale**. 10C adds ranking, batching, one new delivery-time guard, per-user preferences, and the UX surfaces — nothing more.

---

## PART 1 — BUILD SLICES

Ten slices. Each is independently shippable, independently revertible, and leaves production in a working state if the next slice never lands. The slicing rule, carried from 10A and sharpened for a delivery-experience layer: **reconcile before rank, rank before batch, batch before recheck, prefs before promote, in-app before multi-channel, and everything in shadow before anything sends.** Nothing that *changes what reaches a user* lands until everything that *decides whether it should* has run in shadow.

> **Standing safety property.** Every slice through Slice 10 lands with the existing `loop_shadow=True` and `loop_internal_only=True`. 10C can rank, batch, recheck, and write digest/preference rows for weeks while the delivery service still emits `delivered_shadow` and reaches no external user. The consequential flip is a **config sequence in PART 5**, never a slice. This is 10A's "generation for weeks with delivery off" discipline, applied to the ranking-and-packaging layer that sits on top of it.

> **The reconciliation imperative.** Slice 1 exists because the spec (§3.2) found two divergent severity vocabularies already in the codebase (`alert_prioritizer`: `critical|high|medium|ignore`; `loop_delivery_service`: `info|warning|alert|critical`). This is the same dual-vocabulary trap 10B Slice 9 had to unwind for `drift_state`. 10C reconciles **first**, in one place, before any ranking is built on top — so the canonical ladder is load-bearing from line one, not retrofitted.

---

### Slice 1 — Severity reconciliation (canonical ladder, one translator)

**Objective:** Establish one canonical severity ladder (`info | notice | alert | critical`) and a single translation function from the `alert_prioritizer` vocabulary onto it. Pure mechanism, zero behavior change. The foundation every later slice trusts.

**Files:**
- `app/services/severity_model.py` (new — the canonical ladder constants, `_SEVERITY_RANK = {info:0, notice:1, alert:2, critical:3}`, and `to_canonical(prioritizer_value) → canonical` as the **only** translation point; mirrors the 10B Slice 9 single-translation-function discipline)
- `app/services/alert_prioritizer.py` (read-only audit — confirm it keeps its own vocabulary; no change to the tuned scorer)
- `app/services/loop_delivery_service.py` (read-only audit — confirm its existing `_SEVERITY_RANK` aligns; the canonical ladder *extends* the delivery-layer ladder by renaming `warning→notice` semantics, documented in the module header)

**Dependencies:** none.

**Validation:** Unit tests: every `alert_prioritizer` output (`ignore/medium/high/critical`) maps to exactly one canonical value; `to_canonical` is total (no input yields `None`); the rank ordering is strictly monotonic; round-trip from prioritizer score → severity → rank is stable. **Grep gate:** no second translation function exists anywhere (`to_canonical` is the sole call site converting between vocabularies).

**Rollback strategy:** Pure additive module with no caller yet. Revert = delete `severity_model.py`. No production path references it until Slice 3. The existing two vocabularies continue to function exactly as today.

---

### Slice 2 — Schema & migration

**Objective:** Create the three new 10C tables empty in production + add `severity` columns to `delivery_ledger` and `notifications`. Zero behavior change.

**Files:**
- `app/db/migrations/007_briefing_delivery.sql` (new — `CREATE TABLE IF NOT EXISTS` for `user_delivery_prefs`, `digest_batches`, `delivery_ledger_archive`; `ALTER TABLE ... ADD COLUMN` nullable `severity` on `delivery_ledger` and `notifications`; all indexes per PART 2)
- `app/db/models.py` (append ORM: `UserDeliveryPref`, `DigestBatch`, `DeliveryLedgerArchive`; add nullable `severity` to `DeliveryLedger` and `Notification`)
- `app/startup.py` (register migration in the startup-seed path with the `db_table_count` before/after guard, the 10A/10B precedent; **table count 25 → 28**)

**Dependencies:** Slice 1 (severity columns store canonical values).

**Validation:** `db_table_count` rises by 3 (25 → 28) on `/health`; app boots clean; all existing tests pass untouched; migration idempotent (run twice, no error, no duplicate index); the two `severity` columns are nullable with no row rewrite; `validate_10b_watchlist_shadow.py` still green (no regression to the 10B surface).

**Rollback strategy:** None needed — additive `IF NOT EXISTS` DDL + nullable `ALTER ADD COLUMN`, all unread/unwritten. Tables inert without later slices. The `severity` columns sit NULL and harmless if reverted; every existing reader ignores them.

---

### Slice 3 — Ranking: relevance scoring (shadow-computed)

**Objective:** Compose the three existing scorers into one per-change relevance score. Written to ledger metadata in shadow; **nothing acts on it yet**. Proves the composition is sane before any triage depends on it.

**Files:**
- `app/services/relevance_ranker.py` (new — `score(change) → relevance` composing `severity_weight` (Slice 1 canonical) × `materiality` (drift evaluator, exists) × `user_proximity` × `recency_decay` ÷ `name_saturation`, per spec §4.1; `user_proximity` and `name_saturation` are **counts over existing tables**, not new analytics)
- `app/db/repositories/loop_delivery_repo.py` (extend — persist computed `severity` + relevance into the ledger row's metadata on write; read helpers for `name_saturation` = today's ledger rows for the name, `user_proximity` = watchlist membership weight)
- `app/services/loop_producers.py` (extend — `watchlist_scan` producer calls `relevance_ranker.score` and stamps `severity` on the ledger row; still `delivered_shadow`)

**Dependencies:** Slices 1–2. Reads watchlist membership via the **existing** `watched_tickers` / `watchlist_service` interface (the 10B substrate).

**Validation:** Unit: each composition input independently moves the score in the expected direction; a muted/unwatched name scores below an actively-watched one; `name_saturation` decays the 2nd/3rd same-name change (spec §4.4); score is deterministic and bounded. Shadow integration: enqueue a synthetic overnight with 50 changes → assert the relevance distribution is **not** degenerate (not all-equal, not all-max) — the §4.3 "no bucket where pushes == changes" sanity check, computed but not yet enforced.

**Rollback strategy:** Dead-weight computation. Revert = stop stamping severity/relevance; the columns return to NULL. No triage reads them yet, so reverting changes no delivery behavior. Shadow guarantees zero user impact regardless.

---

### Slice 4 — Triage gate (classify; still shadow)

**Objective:** Turn relevance + canonical severity into a routing decision per change: **individual / digest / pull-only / suppress** (spec §4.3). The decision is recorded on the ledger row; the delivery service still shadows, so the decision is observable but inert.

**Files:**
- `app/services/delivery_triage.py` (new — `classify(change) → route ∈ {individual, digest, pull_only, suppress}` per the §4.2/§4.3 rules: `relevance ≥ threshold AND severity ≥ alert → individual`; `severity == notice OR alert-over-cap → digest`; `severity == info → pull_only`; below-materiality/muted/dup/relevance-expired → `suppress`)
- `app/services/loop_delivery_service.py` (extend — read the triage route; in shadow, log the route and the would-be channel, emit `delivered_shadow` regardless)
- `app/config.py` (add `delivery_relevance_threshold` for the `alert` vs `notice` cut, default tuned conservatively pending shadow calibration; `delivery_digest_enabled=False` placeholder for Slice 5)

**Dependencies:** Slice 3.

**Validation:** Unit: the four routes are mutually exclusive and total over all (severity × relevance × membership) combinations; an `info` change never routes `individual`; a duplicate `content_key` always routes `suppress`. Shadow integration: the 50-change synthetic resolves to a small `individual` set, a `digest` set, a `pull_only` set, and a `suppress` set whose sizes match the §4.3 worked example shape (≈4 / ≈9 / ≈5 / rest). **Gate:** no input is unclassified.

**Rollback strategy:** Revert the triage read; delivery falls back to the 10B shadow behavior (emit `delivered_shadow` for everything). Strictly less selective, never broken. Shadow blocks any user impact.

---

### Slice 5 — Digest batching (overflow → digest, not drop)

**Objective:** Convert the existing `daily_cap` *suppress* behavior into *graceful overflow* — cap-breaching and `notice`-severity changes batch into one `digest` item instead of being lost (spec §4.5). The single behavioral improvement to an existing guardrail. Writes `digest_batches` rows in shadow; no send.

**Files:**
- `app/services/digest_builder.py` (new — `accumulate(user, bucket, change)` appends a `content_key` to the open `digest_batches` row; `render(batch) → summary` via deterministic template first (spec open-Q #5), one inbox item summarizing K changes)
- `app/services/loop_delivery_service.py` (extend — route `digest` changes to `digest_builder` instead of `STATUS_SUPPRESSED_GUARDRAIL`; cap-overflow of `individual` items reroutes to digest rather than `suppressed`)
- `app/db/repositories/loop_delivery_repo.py` (extend — `digest_batches` CRUD: open/append/close-per-bucket, idempotent on `(user_id, bucket)`)
- `app/config.py` (`delivery_digest_enabled=True`, `delivery_digest_rollup_hour` for the roll-up time)

**Dependencies:** Slice 4.

**Validation:** Unit: cap overflow appends to digest, does not drop; a second change in the same bucket appends to the **same** digest row (idempotent on `(user_id, bucket)`); per-name saturation rolls repeated same-name changes into that name's digest line (spec §4.4); `render` produces a stable deterministic summary. Shadow integration: drive a user past `daily_cap` → assert zero `suppressed` rows that *should* have been digested, exactly one `digest_batches` row with correct membership, total information preserved (no change silently lost). **This is the §4.5 Pareto-improvement gate: information delivered strictly increases, interruption count held flat.**

**Rollback strategy:** `delivery_digest_enabled=False` — overflow reverts to the existing `daily_cap` suppress behavior (10B baseline). No data loss in either mode (suppressed rows are retained in the ledger). `digest_batches` rows become inert. Instant config flip, no redeploy.

---

### Slice 6 — Delivery-time relevance recheck (the new guard)

**Objective:** Add the one genuinely new guardrail 10C needs (spec §3.5): re-read current watchlist membership + mute state immediately before send, suppressing any alert whose relevance expired between generation and delivery. Lands at the delivery boundary with all the existing guards.

**Files:**
- `app/services/loop_delivery_service.py` (extend — in `flush()`, before send, call a `_relevance_still_valid(row)` check reading live `watched_tickers.active` + `mute_until`; on fail → `STATUS_SUPPRESSED_GUARDRAIL` with reason `relevance_expired`)
- `app/services/delivery_triage.py` (extend — expose the relevance predicate so generation-time and delivery-time use the **same** definition, no second notion)
- `app/db/repositories/loop_delivery_repo.py` (extend — `reason` taxonomy adds `relevance_expired` alongside the existing `quiet_hours/daily_cap/mute_until/severity_floor`)

**Dependencies:** Slices 3–5. Reads the 10B watchlist substrate live.

**Validation:** Unit: a name removed from the watchlist between generate and (simulated) send → `suppressed`, reason `relevance_expired`; a name muted in the gap → `suppressed`; an unchanged-relevance name → passes. Race test: mute applied between recheck and send → the residual is absorbed by `content_key` idempotency on retry (no double-send, no crash). Shadow integration: the recheck fires and logs in shadow without altering `delivered_shadow` accounting.

**Rollback strategy:** Revert the recheck call — delivery falls back to generation-time relevance only (10B behavior). Strictly less strict, never broken; worst case is a delivered alert on a just-removed name, which is non-destructive (an inbox row). Shadow blocks any user impact pre-rollout.

---

### Slice 7 — User delivery preferences

**Objective:** Per-user control over quiet-hours window, per-channel severity floor, channel opt-in/out, and digest-vs-individual pacing (spec §5.5). NULL row = system defaults (the current global config), so the single-user product behaves identically until a preference is set.

**Files:**
- `app/db/repositories/user_prefs_repo.py` (new — `get_prefs(user_id) → prefs | defaults`, `set_pref(user_id, key, value)`; null-object returns system defaults when no row)
- `app/services/loop_delivery_service.py` (extend — guardrails read per-user prefs first, fall back to `settings.delivery_*` globals; the existing global config becomes the default layer, not the only layer)
- `app/api.py` (extend — `GET /me/delivery-prefs`, `PUT /me/delivery-prefs`; read/write the user's own row only)

**Dependencies:** Slice 2 (`user_delivery_prefs` table). Independent of Slices 3–6 (can land in parallel).

**Validation:** Unit: absent row → exact current global behavior (quiet 22–07, cap 20, floor `info`); a set quiet-hours window overrides the global for that user only; channel opt-out suppresses that channel while leaving others; digest-pacing preference forces `notice` items to digest even below cap. Integration: two users with different prefs get independently-gated delivery from the same change. **Multi-user-readiness gate:** `target_key`/`user_id` keyed throughout, so per-user prefs are data, not rearchitecture (spec §8.4).

**Rollback strategy:** Revert the prefs read — guardrails use the global `settings.delivery_*` only (current behavior). The `user_delivery_prefs` table goes inert; no user loses delivery, all revert to system defaults. Additive and safe.

---

### Slice 8 — In-app delivery & UX read surfaces

**Objective:** Complete the in-app experience the spec defines (§6): the briefing envelope, the severity-floated inbox, the digest item, and the "what changed" cross-name view. Read-only API surfaces over the ledger + notifications + timeline. Sends remain blocked by `loop_shadow=True` until PART 5.

**Files:**
- `app/services/briefing_envelope.py` (new — wrap the existing `generate_morning_brief_v2` payload in the §2.3 envelope: header/lead/body/footer + `max_severity` for inbox float; pure packaging, no content generation)
- `app/api.py` (extend — `GET /notifications` already exists; add severity-float ordering; `GET /notifications/digest/{id}` for digest expansion; `GET /what-changed` cross-name delta view composed from ledger + timeline archive per §6.6; `GET /briefing/{date}` for the envelope)
- `app/services/loop_delivery_service.py` (extend — `in_app` channel writes a `notifications` row carrying the canonical `severity` for float ordering; `kind` ∈ `daily_brief | watchlist_alert | digest | system`)

**Dependencies:** Slices 4–6. Reuses the existing `notifications` table and frontend polling contract (zero client rework for the inbox).

**Validation:** Unit: the envelope floats a briefing with a `critical` name above a pure-regime briefing (spec §2.2); `/what-changed` returns every material change in a window ranked by relevance, including `pull_only` (`info`) changes that never pushed (spec §6.6 — proves nothing is lost). Shadow integration: drive a full overnight → inbox renders briefing + N alerts + 1 digest in correct severity-float order, all as `delivered_shadow` (no external send). The `digest` notification expands to its member changes.

**Rollback strategy:** The read APIs are non-destructive (GET only). Revert = remove the new endpoints; the inbox falls back to the existing flat `GET /notifications`. No write-path change, no data risk. Shadow keeps all of this invisible to external users until rollout.

---

### Slice 9 — Channel abstraction (email / push as additive sinks)

**Objective:** Add `email` and `push` as new `channel` values behind the **same** `content_key`-deduplicated ledger — additive sinks, not a rewrite (spec §2.6, §5.1). Push is severity-gated; only `critical`/override clears quiet hours (spec §3.3). Still shadow.

**Files:**
- `app/services/delivery_channels.py` (new — a thin channel-dispatch interface: `send(channel, row) → result`; `in_app` (exists) is the reference implementation; `email` and `push` are new sinks that do **not** write `notifications` rows — they are separate failure domains behind the ledger)
- `app/services/loop_delivery_service.py` (extend — route by `channel`; per-channel severity floor from user prefs (Slice 7); the override-severity rule (`critical` clears quiet hours) enforced once at the boundary)
- `app/config.py` (`delivery_channels_enabled` allowlist, default `["in_app"]`; email/push providers behind feature flags, default off)

**Dependencies:** Slices 7–8. The override-severity rule depends on the canonical ladder (Slice 1).

**Validation:** Unit: a `critical` push clears quiet hours; an `alert` push defers inside quiet hours; email/push sinks do **not** duplicate the in-app notification row for the same `content_key` (the §5.1 no-double-inbox guarantee); a push-provider failure marks only the push row `failed` (retry) and never blocks the in-app row (spec §11.7 failure isolation). Shadow integration: all three channels resolve routes in shadow; none send externally (`delivered_shadow`).

**Rollback strategy:** `delivery_channels_enabled=["in_app"]` — email/push stand down instantly, in-app unaffected. Each channel is an independent sink; disabling one cannot break another. Config flip, no redeploy.

---

### Slice 10 — Observability, fatigue metrics, archival & rollout controls

**Objective:** Production confidence: extend `/admin/loop-status` with delivery + ranking + **fatigue** sections; wire mute/unsubscribe tracking; ledger + notification archival (spec §5.7/§5.8); and the canary/kill-switch reuse for 10C's broader push rollout.

**Files:**
- `app/services/loop_observability.py` (extend — add a `delivery` ranking section: severity distribution, digest coverage, route counts (individual/digest/pull-only/suppress), and a `fatigue` section: mute rate, unsubscribe/opt-out rate, duplicate-delivery rate, push-override rate)
- `app/services/loop_canary_telemetry.py` (reuse unchanged — the `force_disable`/`force_enable`(clears override)/`get_enabled(config)` kill switch already governs the loop; 10C delivery inherits it)
- `app/services/loop_canary_cohort.py` (reuse unchanged — CRC32 on `user_id`, permanent 5% holdout, 95-cap; 10C delivery gates on it exactly as 10A does)
- `app/services/delivery_archival.py` (new — age `delivered`/`suppressed`/`read` rows into `delivery_ledger_archive` + notification rollup, mirroring the 10B timeline-archival discipline: idempotent, append-only, corrupt-row tolerant)
- `app/api.py` (extend — `/admin/loop-status` delivery+fatigue sections; `POST /admin/loop/disable` already halts delivery)
- `tests/validate_10c_briefing_shadow.py` (new — the shadow-readiness validator, mirroring `validate_10b_watchlist_shadow.py`: severity reconciled, ranking non-degenerate, digest coverage correct, duplicate-delivery=0, relevance-recheck suppresses, channels don't double-write)

**Dependencies:** Slices 1–9.

**Validation:** Admin endpoint shows all PART-4 metrics; severity distribution is non-degenerate; digest coverage tracks cap-overflow; archival ages old rows without losing the audit (corrupt archive line skipped, live read unaffected — the 10B archival test pattern); `validate_10c_briefing_shadow.py` exits 0 against staging. Kill-switch cycle (disable → enable-clears-override → config-governs) verified, reusing the 10A telemetry tests re-pointed.

**Rollback strategy:** Observability and archival are additive; reverting removes visibility/rollup but breaks no delivery. The kill switch (`POST /admin/loop/disable`) is itself the system-wide rollback (runtime, no redeploy). Archival can be paused independently; live tables simply grow until it resumes.

---

## PART 2 — DATABASE PLAN

### New tables (3) + 2 column extensions

**Per-user preferences (current-state):**

| Table | Key columns | Notes |
|---|---|---|
| `user_delivery_prefs` | `id` uuid PK, `user_id` UNIQUE, `quiet_hours_start`, `quiet_hours_end`, `severity_floor_json` (per-channel), `channels_optin_json`, `pacing` (`individual`\|`digest`), `created_at`, `updated_at` | NULL/absent row = system defaults (`settings.delivery_*`). The §5.5 user-controls home. `UNIQUE(user_id)` — one prefs row per user. |

**Digest overflow sink (current-state per bucket):**

| Table | Key columns | Notes |
|---|---|---|
| `digest_batches` | `id` uuid PK, `user_id`, `bucket` (YYYY-MM-DD), `member_content_keys_json` (array), `summary_json`, `status` (`open`\|`rendered`\|`delivered`), `created_at`, `delivered_at` | The §4.5 graceful-overflow sink. `UNIQUE(user_id, bucket)` is the append-idempotency constraint (a second change in the bucket appends, never inserts). |

**Append-only delivery archive (immutable):**

| Table | Key columns | Notes |
|---|---|---|
| `delivery_ledger_archive` | `id` PK, `content_key`, `target_key`, `channel`, `severity`, `status`, `archived_at`, `original_created_at`, `body_json` | The §5.7 aged-out ledger rows. **Append-only**, JSONL-discipline mirror of 10B timeline archival. Audit-preserving; corrupt row tolerated on read. |

**Column extensions (additive `ALTER`):**

| Table | Added column | Notes |
|---|---|---|
| `delivery_ledger` | `severity` (nullable) | canonical severity (§3.2) read by cap/floor/override decisions. The single storage home that prevents dual-vocabulary drift. |
| `notifications` | `severity` (nullable) | canonical severity for inbox float ordering (§2.2/§6.3). |

> The two `severity` columns are the **physical home of the §3.2 reconciliation**: one canonical value, written once at ranking time (Slice 3), read by every guardrail and the inbox. Giving severity exactly one storage location is what structurally prevents a third vocabulary from re-emerging.

### New fields summary

| Field | Table | Type | Written by | Read by |
|---|---|---|---|---|
| `severity` | `delivery_ledger` | str (canonical) | Slice 3 ranker | guardrails, archival |
| `severity` | `notifications` | str (canonical) | Slice 8 in-app send | inbox float ordering |
| `quiet_hours_start/end` | `user_delivery_prefs` | int | Slice 7 prefs API | delivery guardrails |
| `severity_floor_json` | `user_delivery_prefs` | json | Slice 7 | per-channel floor |
| `channels_optin_json` | `user_delivery_prefs` | json | Slice 7 | channel dispatch |
| `pacing` | `user_delivery_prefs` | str | Slice 7 | triage (digest vs individual) |
| `member_content_keys_json` | `digest_batches` | json | Slice 5 builder | digest render |

### Migration

- **One file: `007_briefing_delivery.sql`** — three `CREATE TABLE IF NOT EXISTS` + indexes + two `ALTER TABLE ... ADD COLUMN` (nullable). Header comment documenting the spec's §3.2 reconciliation and §4.5 digest design (003–006 precedent).
- Apply order: after `006_watchlist_membership.sql`. Registered in `app/startup.py` with the `db_table_count` before/after guard. **Table count 25 → 28.**
- **No data migration** — tables start empty; population is organic (Slice 5 digest, Slice 7 prefs, Slice 10 archival). The `severity` columns backfill lazily as new ledger/notification rows are written; existing rows stay NULL and are ignored by readers.
- **Rollback:** tables inert without flags; rollback = `delivery_digest_enabled=False` / `delivery_channels_enabled=["in_app"]` / revert reads. DDL never needs reverting (additive, unused until wired).

### Indexes

| Index | Table | Purpose |
|---|---|---|
| `UNIQUE(user_id)` | `user_delivery_prefs` | one prefs row per user; O(1) lookup on the delivery hot path |
| `UNIQUE(user_id, bucket)` | `digest_batches` | digest append-idempotency (§4.5) |
| `(status, bucket)` | `digest_batches` | digest roll-up/drain query |
| `(content_key)` | `delivery_ledger_archive` | audit lookup by delivered content |
| `(archived_at)` | `delivery_ledger_archive` | retention/rollup scans |
| `(severity, status)` | `delivery_ledger` | severity-floor + cap decisions at the boundary |
| `(user_id, read_at, severity)` | `notifications` | inbox poll, unread-first then severity-float |

> The existing 10A `UNIQUE(content_key)` on `delivery_ledger` is **untouched** — it remains the duplicate-delivery hard stop. 10C adds the severity index alongside it; it does not reshape the dedup guarantee.

### Relationships

```
user_delivery_prefs ── user_id ──┐  (logical join, no FK)
                                  ├─ delivery_ledger.target_key  (guardrail reads prefs)
digest_batches ── member_content_keys_json ──> delivery_ledger.content_key  (logical pointer array)
delivery_ledger ──aged──> delivery_ledger_archive   (append-only rollup, no FK)
notifications ──aged──> (notification rollup)        (mirrors §5.8)
RANKING INPUTS (read-only, no FK):  watched_tickers, watchlist drift, alert_prioritizer  ──read──> relevance_ranker
```

No FK from 10C into `watched_tickers`, `thesis_deltas`, or `dossier_revision` — the ranker **reads** them as inputs and joins logically by ticker/user, keeping 10C independent of those subsystems' lifecycles (the 10A §5.4 / 10B discipline).

---

## PART 3 — SERVICE PLAN

Follow `app/services/` conventions: module-level functions, null-object on `session=None`/absent prefs, no business logic in repos. The 10C services sit **on top of** the 10A delivery spine, never replacing it.

| Service | File | Responsibilities | Does NOT |
|---|---|---|---|
| **Severity model** | `severity_model.py` | The canonical ladder + the single `to_canonical` translator (§3.2). The only vocabulary bridge. | Never scores; never ranks. Pure translation + ordering. |
| **Relevance ranker** | `relevance_ranker.py` | Compose existing scores into one relevance value (§4.1). Read `user_proximity`, `name_saturation`, `recency_decay` as counts. | Never trains/prompts/invents a score. Never decides routing (that's triage). |
| **Delivery triage** | `delivery_triage.py` | `classify → {individual, digest, pull_only, suppress}` (§4.3). Own the relevance predicate used at both generation and delivery time. | Never sends. Never generates. Never defines materiality (read from upstream). |
| **Digest builder** | `digest_builder.py` | Accumulate cap-overflow + `notice` changes into one batch; deterministic render (§4.5). | Never sends. Never re-ranks. |
| **Briefing envelope** | `briefing_envelope.py` | Wrap the existing v2 payload in the §2.3 envelope; compute `max_severity` for float. | Never generates briefing content (reuses `generate_morning_brief_v2`). |
| **Delivery channels** | `delivery_channels.py` | Channel dispatch (`in_app`/`email`/`push`) as independent sinks behind the ledger (§5.1). | Never bypasses `content_key`. Email/push never write `notifications` rows. |
| **Delivery service** | `loop_delivery_service.py` (extend) | The existing 10A boundary: drain ledger → guardrails (now incl. per-user prefs + relevance recheck) → dispatch → mark. Override-severity rule. | Still the **only** sender. Still never generates. Guardrails live here, nowhere else. |

**Supporting modules:** `user_prefs_repo.py` (per-user prefs), `delivery_archival.py` (rollup), `loop_observability.py` (extend — fatigue/ranking sections), `loop_canary_*` (reuse unchanged).

**Boundary rules (enforced in review):**
1. **One vocabulary bridge.** `severity_model.to_canonical` is the *only* function converting between the prioritizer and delivery ladders. A second is a release blocker (the §3.2 imperative).
2. **Ranking composes, never computes.** `relevance_ranker` may only multiply/divide existing scores + counts; it may not introduce a new analytical judgment (§4 design principle #3).
3. **The delivery service is the only sender.** Triage, ranking, digest, and envelope decide and package; only `loop_delivery_service.flush()` emits. No new module sends.
4. **Materiality and relevance are read, never redefined.** Triage's relevance predicate reads watchlist/drift state; it adds no threshold the upstream systems don't already own.
5. **Per-user prefs default to globals.** Absent a `user_delivery_prefs` row, behavior is byte-identical to today's global `settings.delivery_*` — single-user safety.

---

## PART 4 — VALIDATION PLAN

10C's correctness is *what it chose not to deliver*. Every metric below is exposed on `/admin/loop-status` (Slice 10) and asserted by `validate_10c_briefing_shadow.py`. The fatigue metrics are the ones that decide the phase.

### Fatigue metrics (the defining gates)

| Metric | Definition | Healthy | How measured |
|---|---|---|---|
| **Mute rate** | mutes applied ÷ active watched names, rolling 7d | below threshold AND **flat or falling** across ramp | `watched_tickers.mute_until` set-events ÷ active names |
| **Unsubscribe rate** | channel opt-outs ÷ delivered users, rolling 7d | below threshold AND flat or falling | `user_delivery_prefs.channels_optin_json` opt-out transitions |
| **Push-override rate** | quiet-hours `critical` sends ÷ total pushes | small and stable (only genuine breaks wake users) | delivery-ledger sends where `severity=critical` AND inside quiet window |
| **Interruptions/user/day** | individual pushes + digest items per user | bounded by `daily_cap`, regardless of change volume | count of `delivered` non-`pull_only` rows per user-day |

> **The fatigue SLA is the advancement gate.** 10A's gate was duplicate-delivery=0. 10C's defining gate is **mute/unsubscribe rate flat-or-falling**. A canary with flawless mechanics but a rising mute rate is a *failed* canary — it means ranking pushed things people didn't want. This is non-negotiable and monitored continuously.

### Mechanical metrics

| Metric | Definition | Healthy | How measured |
|---|---|---|---|
| **Duplicate-delivery rate** | distinct sends with identical `content_key` | **exactly 0** (inherited 10A hard gate) | `content_key` UNIQUE violations / suppressed-duplicate count |
| **Digest coverage** | changes routed to digest ÷ changes that overflowed cap or scored `notice` | ≈100% (no overflow silently suppressed) | `digest_batches` membership ÷ (cap-overflow + `notice` count) |
| **Severity distribution** | share of changes per canonical level (`info/notice/alert/critical`) | non-degenerate; `critical` is a small tail, not the mode | histogram of ledger `severity` per bucket |
| **Ranking compression** | pushes ÷ total overnight changes | ≪ 1 (the §4.3 "50 → ~4 pushes" property) | individual-route count ÷ total changes in bucket |
| **Relevance-recheck suppression** | alerts suppressed for `relevance_expired` ÷ generated alerts | small, non-zero (proves the guard fires) | ledger rows with reason `relevance_expired` |
| **Delivery success rate** | `delivered` ÷ (`delivered` + `failed`) per channel | ≥ target | delivery-ledger status counts |

### Test harness

- **Unit** (in-memory SQLite, CI): severity translation totality (Slice 1); ranker monotonicity (Slice 3); triage exhaustiveness (Slice 4); digest idempotency (Slice 5); relevance-recheck (Slice 6); prefs default-to-global (Slice 7); envelope float (Slice 8); channel no-double-write (Slice 9).
- **Integration** (Postgres test DB, existing `pytest.ini`/`conftest.py`): the 50-change synthetic overnight → assert the full triage distribution, digest coverage, and severity histogram; relevance-recheck suppression under simulated gap-mutation.
- **Shadow validation** (`validate_10c_briefing_shadow.py`, staging): severity reconciled (every ledger row canonical), ranking non-degenerate, digest coverage correct, **duplicate-delivery=0**, channels don't double-write, fatigue metrics computable. Exit 0 gates the internal stage.
- **The standing invariant:** duplicate-delivery=0 is a **release blocker** at any non-zero value, exactly as in 10A.

---

## PART 5 — ROLLOUT SEQUENCE

Reuses the 10A/9G cohort + kill switch + telemetry **unchanged**. The flag substrate already exists (`loop_shadow`, `loop_internal_only`, `loop_internal_user_ids`, `loop_canary_pct`). 10C adds no rollout machinery — it is the third customer of the canary infra. Each stage defines **advance / hold / rollback** criteria explicitly.

### Shadow stage
**Config:** `loop_enabled=True, loop_shadow=True, loop_internal_only=True, loop_canary_pct=0` (where 10B left production).
**Behavior:** rank, triage, batch, recheck, write digest/prefs/severity rows — **zero sends** (`delivered_shadow`).
- **Advance when (all, sustained 72h):** severity reconciled (100% of ledger rows carry a canonical value, zero prioritizer-vocabulary leaks); ranking compression ≪ 1 (no bucket where pushes == changes); digest coverage ≈100% (no overflow suppressed); **duplicate-delivery = 0** under forced double-driver + redeploy; relevance-recheck suppresses correctly; `validate_10c_briefing_shadow.py` exits 0; zero unhandled exceptions in the delivery path.
- **Hold when:** ranking distribution degenerate (all-equal/all-max); digest coverage < 100% (overflow leaking to suppress); any severity row with a non-canonical value.
- **Rollback:** none needed — shadow reaches no user. Revert the offending slice; production stays at 10B behavior.

### Internal stage
**Config:** `loop_shadow=False`, `loop_internal_only=True`, `loop_internal_user_ids=<team>`.
**Behavior:** real in-app deliveries to the named internal set only.
- **Advance when:** team reads its own briefings for **7 consecutive days** — cadence feels right, no 3am non-`critical` push (quiet hours verified live), digest is readable and not a junk drawer; all guardrails verified end-to-end (mute suppresses + still generates, cap → digest, severity floor filters, per-user prefs honored); delivery success rate ≥ target on in-app; **zero duplicate notifications** in the inbox over the week; mute/unsubscribe among the team = 0.
- **Hold when:** any 3am non-`critical` push; digest unread/unhelpful; a guardrail bypassed; any duplicate inbox row.
- **Rollback:** `loop_shadow=True` — instant halt of sends, generation continues, ledger accumulates recoverable rows. Or `POST /admin/loop/disable` (runtime, no redeploy).

### 5% canary stage
**Config:** `loop_internal_only=False, loop_canary_pct=5` (CRC32 on `user_id` via the reused `loop_canary_cohort`; permanent 5% holdout, 95-cap).
**Behavior:** ~5% receive real briefings + alerts + digests; a held-out 5% never does (the comparison arm).
- **Advance when (sustained 72h or ≥200 delivered, whichever later):** **mute/unsubscribe rate below threshold AND flat-or-falling** (the fatigue SLA — the gate that matters); duplicate-delivery = 0 (continuous); delivery success rate ≥ target; push-override rate small and stable; cost/cycle within ceiling and **linear** in cohort size; digest coverage ≈100%; no regression to `/ask` latency or the running loop.
- **Hold when:** mute/unsubscribe rising; push-override rate climbing (too many `critical`s); cost super-linear; digest coverage slipping.
- **Rollback:** `loop_canary_pct=0` (cohort reverts to shadow — generate, don't deliver, no data loss) or `POST /admin/loop/disable` (instant, system-wide).

### Ramp
**Config:** `loop_canary_pct: 5 → 25 → 50 → 95` (hold the 5% holdout permanently).
- **Advance (each step dwells until met):** all 5%-stage gates still green at the larger N; **mute/unsubscribe flat or falling** at the new exposure; cost linear in cohort size (the exponential-blowup tripwire); schedule lag + delivery latency flat (no scaling cliff); duplicate-delivery = 0.
- **Hold when:** any fatigue metric rises at the new N; cost goes super-linear; latency/lag spikes.
- **Rollback:** drop `loop_canary_pct` to the last-green step, or to 0; `POST /admin/loop/disable` for instant full halt. The kill switch stops *delivery*, never *generation* — flipping off and back on never loses or duplicates intelligence (the `content_key` dedup absorbs the resume).

> The 5% holdout is **permanent** post-GA — the standing control arm for measuring 10C's effect on retention and fatigue, exactly as the 10A loop and dossier canary retain theirs.

---

## PART 6 — DEPENDENCIES

### Dependencies on 10A (the delivery spine — already shipped)
- **`delivery_ledger` + `content_key` UNIQUE** — 10C ranks and routes *into* this ledger; the duplicate-delivery guarantee is inherited, not rebuilt.
- **`loop_delivery_service.flush()` + the guardrail boundary** (quiet hours / daily cap / mute / severity floor) — 10C extends this single chokepoint with per-user prefs and the relevance recheck; it adds no second send path.
- **The generation/delivery split** — 10C's "rank at generation, recheck at delivery" depends on these being separate transactions (10A §6), already true.
- **Canary cohort + kill switch** (`loop_canary_cohort.py`, `loop_canary_telemetry.py`) — reused unchanged for 10C's push rollout.
- **Cadence resolution with user-local tz** (10A §2.3) — the briefing's "user-local morning" depends on it existing.
- **The flag substrate** (`loop_shadow`, `loop_internal_only`, `loop_canary_pct`) — 10C's rollout is a config sequence over flags 10A already defined.

### Dependencies on 10B (the watchlist substrate — already shipped)
- **`watched_tickers` + live drift state** — `relevance_ranker.user_proximity` reads watchlist membership; the relevance recheck reads `active` + `mute_until` live (Slice 6).
- **The drift evaluator** (`thesis_impact_evaluator.get_watchlist_drift`) — supplies the `materiality` input to the relevance score; 10C consumes it, defines no parallel materiality.
- **The reconciled `drift_state`** (10B Slice 9 single-source discipline) — 10C's §3.2 severity reconciliation follows the same one-translator pattern; the 10B fix is the precedent.
- **Timeline archival discipline** (10B Slice 7) — `delivery_archival.py` mirrors it (idempotent, append-only, corrupt-row tolerant).
- **The `watchlist_scan` producer** — already stamps shadow alert payloads (10B Slice 5); Slice 3 adds severity/relevance stamping to the same producer.

### Prerequisites 10C must deliver before 10D (Portfolio Intelligence)
- **The `portfolio_relevance` alert type reserved** (spec §3.1) with its severity mapping pre-defined — 10D binds a portfolio detector to it; the entire ranking/triage/delivery/UX machinery applies unchanged.
- **`user_proximity` as a pluggable multiplier** (Slice 3) — 10D slots portfolio-weighting (a held position > a watched one) into the existing relevance formula as one more multiplier, no new pipeline.
- **The single guardrail chokepoint** preserved (`loop_delivery_service`) so 10D inserts "risk-surfacing-not-advice" enforcement in exactly one place (the regulatory filter lives at the boundary, never in a producer).
- **The `what-changed` surface generalizable** (Slice 8, §6.6) — becomes "what changed in *my portfolio*" by filtering the same ledger on held positions; no new surface.
- **Per-user prefs + multi-user keying** (Slice 7) proven — 10D's portfolio is per-user by construction; `target_key`/`user_id` keyed throughout means 10D is data + a producer binding, not rearchitecture.

> **The contract in one line:** after 10C, every future delivery is *"rank an existing signal, route it through the one boundary, and let the canary govern exposure"* — severity reconciliation, ranking, batching, fatigue control, channel abstraction, and the rollout ladder are solved once, here.

---

## PART 7 — IMPLEMENTATION ORDER

Sequenced so user-facing risk is monotonically bounded; every week ends shippable and revertible, and nothing reaches an external user until the internal stage in Week 5.

**Week 1 — Reconciliation & schema (no behavior change)**
- Days 1–2: Slice 1 (severity model + single translator + grep gate) → deploy. The vocabulary is canonical before anything builds on it.
- Days 3–5: Slice 2 (migration `007` + models, table count 25→28) → deploy. Tables exist, empty; `severity` columns NULL.

**Week 2 — Ranking & triage (shadow-computed, inert)**
- Days 1–3: Slice 3 (relevance ranker, shadow-stamped) → deploy dark. Severity/relevance populate; nothing acts on them.
- Days 4–5: Slice 4 (triage gate, route recorded, still shadow). Run the 50-change synthetic; confirm non-degenerate distribution.

**Week 3 — Batching & the new guard (shadow)**
- Days 1–3: Slice 5 (digest builder — the §4.5 Pareto improvement) → confirm cap-overflow batches instead of dropping, coverage ≈100%.
- Days 4–5: Slice 6 (delivery-time relevance recheck) → confirm gap-mutation suppresses.
- **Gate:** Shadow-stage advancement criteria (PART 5) on track.

**Week 4 — Prefs, UX & channels (still shadow)**
- Days 1–2: Slice 7 (user delivery prefs; default-to-global safety) → deploy.
- Days 3–4: Slice 8 (briefing envelope, inbox float, `/what-changed`, digest expansion — read APIs).
- Day 5: Slice 9 (channel abstraction; in-app reference, email/push behind flags off).

**Week 5 — Observability, validator & the consequential flip**
- Days 1–2: Slice 10 (fatigue/ranking metrics on `/admin/loop-status`, archival, `validate_10c_briefing_shadow.py`). **Gate:** shadow validator exits 0; all PART-4 mechanical metrics green.
- Day 3: **Internal stage** — `loop_shadow=False`, `loop_internal_only=True`, team user_ids. Read your own briefings.
- Days 4–5: live for the team; verify cadence, quiet hours, digest readability, zero duplicates. **Rollback at any sign = `loop_shadow=True` or `POST /admin/loop/disable`, instant.**

**Week 6 — Canary & ramp**
- Internal stage completes its 7-day soak (spanning into Week 6 as needed).
- 5% canary → ramp 5→25→50→95 per PART 5 gates, dwelling at each step on the **fatigue SLA** (mute/unsubscribe flat-or-falling). Hold the 5% holdout permanently.

**Standing rule:** flags are independent and layered — `loop_shadow` (no-send), `loop_internal_only` (named set), `loop_canary_pct` (exposure). Ranking and batching run for weeks with sends off; sends can be killed without losing generated artifacts (they bank in the ledger as `delivered_shadow`/`pending`). 10C's dataset only ever grows under governed, idempotent writes.

---

## DELIVERABLE SUMMARY

1. **Build slices:** 10 (PART 1) — severity-reconcile → schema → relevance-rank → triage → digest-batch → relevance-recheck → user-prefs → in-app-UX → channel-abstraction → observability/fatigue/archival. Each with objective, files, dependencies, validation, rollback. All land with `loop_shadow=True`.
2. **Delivery model sequence:** shadow → internal → 5% canary → ramp (PART 5), a config sequence over existing flags, never a slice; the consequential flip is Week 5.
3. **Database plan:** 3 new tables (`user_delivery_prefs`, `digest_batches`, `delivery_ledger_archive`) + 2 additive `severity` columns, single migration `007_briefing_delivery.sql`, idempotent, startup-registered, table count 25→28, rollback = flags off (PART 2).
4. **Validation plan:** fatigue metrics (mute rate, unsubscribe rate, push-override rate, interruptions/user/day) as the defining gates, plus mechanical metrics (duplicate-delivery=0, digest coverage, severity distribution, ranking compression, relevance-recheck suppression, delivery success) — each measurable on `/admin/loop-status` and asserted by `validate_10c_briefing_shadow.py` (PART 4).
5. **Rollout gates:** advance / hold / rollback criteria stated explicitly per stage; the fatigue SLA (mute/unsubscribe flat-or-falling) is the advancement gate; duplicate-delivery=0 is the standing release blocker; kill switch is the instant rollback (PART 5).
6. **Dependencies:** the exact contracts 10C consumes from 10A (delivery spine + guardrail boundary + canary + tz cadence) and 10B (watched_tickers + drift evaluator + reconciliation precedent + archival discipline), and the prerequisites 10C delivers for 10D (reserved portfolio_relevance type + pluggable user_proximity + single guardrail chokepoint + generalizable what-changed + multi-user prefs) (PART 6).
7. **Production rollout:** 6 weeks, reconcile-and-dark-deploy then layered flag-flips; ranking Week 2, batching Week 3, UX Week 4, first internal users Week 5, canary/ramp Week 6; three independent flags revertible at all times; kill switch is the instant system-wide rollback (PART 7).

*End of implementation plan. No code, no migrations, no implementation in this document — execution may begin immediately against it. 10C builds the judgment about which intelligence is worth a human's attention and the disciplined, reversible path by which it arrives.*
