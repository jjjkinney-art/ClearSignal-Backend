# Briefing & Delivery — Architecture Specification

**Phase:** 10C · the experience layer
**Status:** Design — not yet implemented
**Audience:** Principal/staff engineers, backend, product
**Scope:** Design only. No code, no migrations, no implementation in this document.
**Prerequisite read:** `PHASE_10A_LOOP_SPEC.md` (the heartbeat this layer rides on), `PHASE_10B_SHADOW_ROLLOUT.md` (the watchlist substrate and shadow posture), `COMPANY_DOSSIER_SPEC.md` (the change record both consume).

---

## 0. Purpose and one-paragraph thesis

After 10A and 10B, ClearSignal can do everything *except the last mile*. The loop ticks. Jobs are seeded. Watchlist scans run in shadow. Drift is detected. Delivery-ledger rows are written and deduplicated. Timelines are preserved. And **not one byte of intelligence reaches a user as a product experience.** The system today is a fully-wired power plant with the transmission lines stopping at the substation fence. Phase 10C is the transmission layer: it defines *what* a user receives, *when*, *triggered by what*, *ranked how*, *through which surface*, and — equally load-bearing — *what they must never receive*. It turns "the system noticed something changed" into "the user understood what changed and why it matters to them, without being buried."

> **Design principle #1 — 10C adds no new intelligence; it adds judgment about what is worth a human's attention.** Every signal 10C delivers was already computed by Phases 1–9 and detected by 10A/10B. 10C's entire surface area is *selection, ranking, packaging, pacing, and presentation*. The moment this layer starts computing a new analytical fact rather than routing an existing one, it has violated the same separation 10A drew between the loop and its producers. The watchlist scan decides *what changed*; 10C decides *whether to interrupt someone about it*.

> **Design principle #2 — The default is silence.** An intelligence platform earns the right to push by being right about what deserves a push. Most changes on most days do not. 10C is architected so that the cost of *not* delivering is structurally lower than the cost of delivering — the inverse of a notification system optimized for engagement. A quiet day produces a quiet inbox, on purpose.

---

## 1. The intelligence delivery model

The delivery model answers four questions. Each has a precise, defensible answer grounded in what already exists.

### 1.1 What should users receive?

Exactly three artifact classes, no more:

| Artifact | Cadence | Producer (exists) | Surface |
|---|---|---|---|
| **Daily Briefing** | once per user-local morning | `morning_brief_service.generate_morning_brief_v2` | inbox + briefing view |
| **Alert** | event-driven, drift-gated | `watchlist_scan` producer → `alert_prioritizer` | inbox + push (by severity) |
| **Digest** (the pressure-relief valve) | when alert volume would breach the daily cap | 10C batching layer (§4.5) | inbox only |

> The taxonomy is **closed and additive**, mirroring the 10A job taxonomy. A fourth artifact class arrives as a new enum + a producer binding, never by overloading "alert" into a catch-all. Anything that is neither a scheduled briefing nor an event-triggered alert nor a batched digest does not get delivered — it lives in the pulled in-app surfaces (timeline, watchlist, "what changed") where the user goes to *it*, rather than it coming to the user.

### 1.2 When should they receive it?

| Trigger class | Timing | Governed by |
|---|---|---|
| **Cadence** (briefing) | resolved to user-local morning, jittered | 10A §2.3 tz resolution |
| **Event** (alert) | at the next `delivery_flush` after generation, subject to quiet hours | 10A delivery separation §6 |
| **Coalesced** (digest) | at a fixed daily roll-up time, or when N pending alerts accumulate | 10C §4.5 |

Delivery time is **never** generation time. 10A already split these into separate transactions with separate failure domains; 10C inherits that split wholesale. A critical alert generated at 02:14 local does not wake the user — it waits behind quiet hours (§5.3) unless it clears the *override severity* (§3.3), and even then it is the severity, not the freshness, that earns the interruption.

### 1.3 What should trigger delivery?

A delivery is triggered only when **all** of these hold:

1. A producer wrote a delivery-ledger row (generation happened).
2. The row's underlying change cleared the **upstream materiality boundary** — it cut a `dossier_revision` or a `thesis_delta`, or the watchlist evaluator returned a non-`unchanged` drift direction with materiality above `drift_materiality_min` (currently 0.4, 10B-tuned).
3. The ranked severity (§3) is **at or above the channel's severity floor**.
4. No identical `content_key` was already delivered (the 10A/10B hard dedup).

This is a logical AND, enforced at the delivery boundary, not in any producer. The boundary is the single choke point — a producer cannot bypass it, and a new producer inherits it for free.

### 1.4 What should *never* trigger delivery?

This list is normative and is the spec's most important section. Each entry maps to an existing or specified guard.

| Never deliver | Why | Enforced by |
|---|---|---|
| A change that did not cut an upstream material-change row | No second definition of "material" (10A §5.4) | drift gate / dirty-signal read |
| A re-render of unchanged substrate | Byte-identical `content_hash` → dedup | `content_key` UNIQUE (exists) |
| The same content on two channels within a bucket | Channel is part of `content_key` | `content_key` UNIQUE (exists) |
| Anything below the severity floor | Pull, don't push (10A §6.3) | `severity_floor` guardrail (exists) |
| Anything to a muted target | User opted out of interruption | `mute_until` guardrail (exists) |
| Anything outside the waking window unless override-severity | Sleep is sacred | `quiet_hours` guardrail (exists) |
| The (N+1)th push in a day | Fatigue cap; overflow → digest | `daily_cap` guardrail (exists) → §4.5 |
| A backlogged briefing past its catch-up window | Stale info is worse than no info | 10A `skipped_stale` §7.2 |
| An alert on a name the user removed from the watchlist after generation | Relevance expired between generate and send | §3.5 relevance recheck at delivery |

> **Grounding note.** Seven of these nine guards already exist and run in shadow today (10A §6.3, 10B delivery service). 10C adds exactly two new ones: the digest overflow path (§4.5) and the delivery-time relevance recheck (§3.5). Everything else is *promotion of an already-built guard from shadow to live*, which is the safest possible way to ship a delivery system.

---

## 2. Daily Briefings

### 2.1 Generation

The briefing is **not generated by 10C**. `generate_morning_brief_v2` already exists, already runs as the `morning_brief` loop producer in shadow, and already returns the full institutional structure. 10C's contribution is *lifecycle and routing*, not content. The v2 output shape is fixed and consumed as-is:

```
generated_at · reference_date · ticker_count
regime_headline · regime_factors · rate_environment · risk_appetite
narrative_shifts[] · debate_shifts[] · priority_alerts[]
attention_required[] · watchlist_drift[] · top_movers[]
market_regime_note · brief_text
```

> The briefing is a **cadence job that fans out per watched name into "changed → real line / unchanged → template line"** (10A §5.2). A quiet portfolio yields a brief that is mostly regime context + "no material change across N names"; an eventful one yields proportional detail. The expensive path is gated behind the dirty signal, so a 23-name watchlist on a quiet day costs near-zero.

### 2.2 Prioritization within the briefing

The brief's internal ordering is **already a ranking problem the producer solves** via `attention_required`, `debate_shifts`, and `priority_alerts`. 10C does not re-rank inside the brief. It only decides, at the inbox layer, *how prominently the whole briefing renders* relative to same-day alerts — a briefing with a `critical` name in `attention_required` floats above a briefing that is pure regime context. That float is computed from the **max severity of any name inside the brief** (§3), not from a new score.

### 2.3 Briefing structure (delivery envelope)

10C wraps the v2 payload in a thin, channel-agnostic envelope. The envelope carries routing metadata; the payload carries content. This is the same generation/delivery split as 10A — the envelope is delivery-layer, the payload is producer-layer.

```
Briefing Envelope
├── header:   reference_date, regime_headline, name_count, max_severity
├── lead:     top 1–3 names from attention_required (the "read this first")
├── body:     the full v2 sections, collapsed by default per name
└── footer:   "N names unchanged" + link to full watchlist view
```

### 2.4 Briefing lifecycle

```
   ┌──────────┐  cadence job fires (user-local morning, jittered)
   │ pending  │
   └────┬─────┘
        │  generate_morning_brief_v2 succeeds; content_hash computed
        ▼
   ┌───────────┐  delivery-ledger row written (status: pending)
   │ generated │  BriefingSession.status = "generated"
   └────┬──────┘
        │  delivery_flush: quiet-hours / cap / mute / floor pass
        ▼
   ┌───────────┐  notification row written (in-app) / channel send
   │ delivered │  BriefingSession.status = "delivered"; delivered_at set
   └────┬──────┘
        │  user opens inbox → notification.read_at set
        ▼
   ┌────────┐
   │  read  │  (terminal for the user; row retained for timeline)
   └────────┘
```

The `BriefingSession.status` ladder (`pending → generated → delivered`) already exists with `content_hash` and `delivery_channel` columns added in 10A. 10C consumes this ladder unchanged and adds the `read` state via `notification.read_at` (already on the table).

### 2.5 Regeneration rules

| Situation | Rule |
|---|---|
| Same name dirties twice before the morning | **Coalesce** — one regeneration, not two (10A §5.3 drift coalescing, already enforced on `(job_type, target_key, period_bucket)`) |
| The brief already generated, then a name dirties | Do **not** regenerate the whole brief mid-day. The new change flows as an *alert* (§3), not a brief rewrite. The brief is a once-daily snapshot; intraday deltas are alerts. |
| The brief generated but failed to deliver (channel outage) | **Re-deliver, never re-generate** (10A §6.1). The banked `content_hash` is resent. No second LLM cost. |
| User changes timezone | Next occurrence resolves to the new local morning; the in-flight bucket is unaffected. |

> The single most important regeneration rule: **a briefing is immutable once generated for its bucket.** Intraday news does not retroactively edit this morning's brief — it produces an alert and feeds tomorrow's brief. This keeps the briefing a stable, citable artifact rather than a live-updating document the user can never "finish reading."

### 2.6 Delivery channels

| Channel | Phase | Sink | Notes |
|---|---|---|---|
| **in_app** | 10C ship-first | `notifications` table (exists, `kind="daily_brief"`) | zero third-party integration; frontend already has a polling contract |
| **email** | 10C later slice | external provider | the envelope is already channel-agnostic; email is a new sink, not a new payload |
| **push** | 10D-adjacent | mobile/web push | severity-gated; only `critical`/override clears quiet hours |

In-app ships first because it is the only channel that needs no external dependency and no new failure domain. Email and push are additive sinks behind the same `content_key`-deduplicated ledger.

---

## 3. Alerting

An alert is an event-triggered, drift-gated, single-name (or single-theme) interruption. Alerts are where 10C most needs discipline, because alerts are where fatigue is manufactured.

### 3.1 Alert types

Each alert type binds to an **existing detector**. 10C contributes the routing and the severity mapping, not the detection.

| Alert type | Fires when | Detector (exists) |
|---|---|---|
| **thesis_break** | thesis stance flips / conviction collapses past `material` | `thesis_drift` / `thesis_impact_evaluator` → drift `broke` |
| **conviction_change** | conviction moves beyond hysteresis without a full break | drift `weakened` / `strengthened` |
| **new_risk** | a failure mode / concern tag newly fires | `dossier_failure_mode` / `concern_tags` revision |
| **new_catalyst** | a catalyst transitions to fired/imminent | `dossier_catalyst` revision |
| **watchlist_relevance** | a watched name crosses a relevance threshold (drift materiality ≥ floor) | watchlist evaluator drift summary |
| **portfolio_relevance** *(10D-reserved)* | a held position is materially affected | **reserved** — see §8.1 |

> `portfolio_relevance` is specified now but **not implemented in 10C**. Its severity mapping and routing are defined here so that 10D is a producer binding, not an architecture change. This is the same forward-compatibility discipline 10A used for `job_type` enums.

### 3.2 Severity levels — reconciling the two existing vocabularies

**Finding (grounded):** the codebase currently carries *two divergent severity ladders*:

- `alert_prioritizer.py` → `critical | high | medium | ignore` (score thresholds 0.65 / 0.35 / 0.15)
- `loop_delivery_service.py` → `info | warning | alert | critical` (`_SEVERITY_RANK = {info:0, warning:1, alert:2, critical:3}`, floor default `info`)

Shipping 10C on top of both unreconciled would reproduce exactly the dual-vocabulary drift bug that 10B Slice 9 had to fix for `drift_state`. **10C must canonicalize one ladder and map the other onto it — it must not introduce a third.**

**Canonical 10C severity ladder** (chosen to extend the *delivery-layer* ladder, because delivery is the enforcement boundary and already ranks numerically):

| Canonical | Rank | Meaning | Default routing |
|---|---|---|---|
| `info` | 0 | context; pulled, never pushed | in-app inbox only, below the fold |
| `notice` | 1 | worth seeing in today's digest | inbox + digest batch |
| `alert` | 2 | worth an individual inbox item | inbox item + push if user opted in |
| `critical` | 3 | worth interrupting | inbox + push, **clears quiet hours** (§3.3) |

**Mapping from `alert_prioritizer` → canonical** (a pure lookup, owned in one place):

| prioritizer | → canonical |
|---|---|
| `ignore` | `info` |
| `medium` | `notice` |
| `high` | `alert` |
| `critical` | `critical` |

> The mapping lives in a single translation function at the delivery boundary, exactly as 10B Slice 9 put drift-vocabulary translation in one place. The prioritizer keeps its vocabulary (no churn to a tuned scorer); the delivery layer keeps its ranked ladder; one lookup bridges them. Adding a third vocabulary is a release blocker.

### 3.3 The override-severity rule

`critical` — and only `critical` — clears quiet hours. This is the single exception to §1.2's "delivery time is never generation time" pacing. A thesis breaking at 03:00 on a name the user is heavily watching is the one thing worth a 03:00 push. Everything else waits for the waking window. The override is **severity-gated, not freshness-gated** — newness alone never earns an interruption.

### 3.4 Alert lifecycle

```
   detector fires (drift / revision row newer than last_generated_at)
        │
        ▼
   ┌──────────┐  watchlist_scan producer emits alert payload + severity
   │ detected │  (already happens in shadow today, 10B Slice 5)
   └────┬─────┘
        │  alert_prioritizer → canonical severity (§3.2)
        ▼
   ┌──────────┐  delivery-ledger row (content_key dedup)
   │  ranked  │
   └────┬─────┘
        │  delivery_flush: relevance recheck (§3.5) + guardrails
        ├──────────────► suppressed (floor / mute / dup / relevance-expired)
        ├──────────────► deferred  (quiet hours, non-critical) → digest (§4.5)
        ▼
   ┌───────────┐
   │ delivered │  notification (kind="watchlist_alert") / push
   └───────────┘
```

### 3.5 Delivery-time relevance recheck (new in 10C)

Between generation and send, the world can change: the user removes the name, mutes it, or a higher-severity alert on the same name supersedes this one. 10C adds a **recheck at the delivery boundary** that re-reads current watchlist membership and mute state immediately before send. An alert whose relevance expired in that gap is `suppressed`, not sent. This is the one genuinely new guard alerts need, and it lives at the boundary with all the others.

---

## 4. Intelligence ranking — the "50 things changed overnight" problem

This is the heart of 10C. If fifty names dirty overnight, the system must decide what matters, what to suppress, what to batch — and be *right enough* that the user trusts the inbox.

> **Design principle #3 — Ranking is composition of existing scores, not a new model.** The codebase already has three scorers: `signal_scoring` (importance 0–100 + confidence + horizon), `signal_ranker` (composite impact × type-priority × direction × sensitivity), and `alert_prioritizer` (severity score). 10C *composes* these into a single per-change relevance score. It does not train, prompt, or invent a fourth.

### 4.1 The relevance score (composition formula)

For each candidate change, 10C computes:

```
relevance = severity_weight        (from alert_prioritizer canonical, §3.2)
          × materiality            (from the drift evaluator, 0–1, already computed)
          × user_proximity         (is it on the watchlist? heavily watched? — §4.2)
          × recency_decay          (how fresh is the triggering event)
          ÷ name_saturation        (how many alerts this name already produced today — §4.4)
```

Every input on the right already exists except `user_proximity` and `name_saturation`, both of which are *counts over existing tables* (watchlist membership, today's delivery-ledger rows for the name), not new analytics.

### 4.2 What matters vs. what does not

| Decision | Rule |
|---|---|
| **Matters** (deliver individually) | `relevance` ≥ alert threshold AND canonical severity ≥ `alert` |
| **Matters mildly** (batch into digest) | canonical severity == `notice`, OR `alert` that overflows the daily cap |
| **Does not matter** (pull-only) | canonical severity == `info` → lands in timeline/"what changed", never pushed |
| **Suppressed** (never surfaced as a push or digest line) | below materiality floor, muted, duplicate, relevance-expired |

### 4.3 What gets delivered vs. suppressed vs. batched (the triage)

```
        50 overnight changes
                │
                ▼
   ┌────────────────────────────┐
   │ upstream materiality gate   │  did it cut a revision/delta? drift ≥ floor?
   └─────────────┬───────────────┘
       fails ────┴──── passes (say, 18 survive)
        │                  │
   (dropped)               ▼
                ┌──────────────────────┐
                │ relevance scoring §4.1│
                └──────────┬───────────┘
              ┌────────────┼────────────┐
              ▼            ▼             ▼
        critical/alert  notice      info
        (say 4)        (say 9)      (say 5)
              │            │             │
        individual     DIGEST       pull-only
        inbox+push     (one batched  (timeline /
        (cap-checked)   item)        "what changed")
```

Fifty changes become **four pushes, one digest, five pull-only entries** — and the four pushes are themselves cap-checked (§4.5). The user sees five inbox items, not fifty interruptions.

### 4.4 Per-name saturation (anti-spam within a single name)

A single volatile name producing eight alerts in one night must not generate eight inbox items. `name_saturation` divides relevance by the count of alerts already emitted for that name in the bucket, so the second and third alert on the same name decay sharply. Past a threshold, further same-name changes **roll into that name's digest line** rather than producing new items. This is the per-name mirror of §4.5's global cap.

### 4.5 Batching — the digest

When alert volume would breach `daily_cap` (an existing guardrail, currently suppressing overflow), 10C **redirects overflow into a digest** rather than dropping it. The digest is one inbox item summarizing K lower-severity changes: "9 watchlist names had notable-but-not-urgent moves overnight." This converts the existing hard cap (which silently suppressed) into a *graceful overflow* (which batches). It is the only behavioral change to an existing guardrail in 10C, and it strictly increases information delivered while holding interruption count flat.

> **Grounding note.** Today `daily_cap` overflow → `suppressed` (information lost). 10C: `daily_cap` overflow → digest (information preserved, interruption bounded). This is a Pareto improvement on the current shadow behavior and is the single most user-visible win of the phase.

---

## 5. Delivery system

Most of this layer exists and runs in shadow. This section states what 10C *promotes to live* and the two things it *adds*.

### 5.1 Notification model

`notifications` table (exists): `user_id`, `kind` (`daily_brief | watchlist_alert | dossier_update | system`), `body_json`, `read_at`, `created_at`. The in-app inbox is `GET /notifications` sorted unread-first. 10C uses this table unchanged as the in-app sink. Email/push channels do **not** write notification rows — they are separate sinks behind the same ledger (so a name's alert can hit push without duplicating the inbox row).

### 5.2 Delivery model

The `delivery_ledger` (exists): `content_key` UNIQUE (hard dedup), `target_key`, `channel`, `content_hash`, `artifact_ref`, `status` (`pending | delivered | failed | suppressed | deferred`), `attempts`, `not_before_utc`, `delivered_at`. Generation writes `pending`; `delivery_flush` drains it; status records the outcome. This is the 10A delivery separation, already built and shadow-validated. 10C flips `loop_shadow` off for canaried cohorts — the ledger stops being write-only and starts producing sends.

### 5.3 Quiet hours

Exists (`delivery_quiet_hours_start/end`). Non-`critical` deliveries inside the window are `deferred` via `not_before_utc` and swept into the morning digest or the next waking-window flush. `critical` overrides (§3.3). No change beyond promoting it live.

### 5.4 Batching, deduplication

Batching: §4.5 digest. Deduplication: `content_key` UNIQUE — the strongest guarantee, enforced below the app layer, already shadow-proven at **duplicate_delivery_count = 0** (the 10A/10B release gate). 10C inherits the gate verbatim.

### 5.5 User controls

| Control | Mechanism | State |
|---|---|---|
| **Mute a name** | `mute_until` on the watch target | guardrail exists |
| **Quiet hours window** | per-user setting | guardrail exists; per-user storage is a 10C additive column |
| **Severity floor per channel** | `delivery_severity_floor` | exists globally; per-channel is a 10C additive setting |
| **Channel opt-in/out** | per-user channel preference | new in 10C (additive table, §9) |
| **Digest vs. individual** | per-user pacing preference | new in 10C (additive setting) |

User controls are the user-facing arm of the same guardrails the system already enforces. The architecture exposes existing knobs; it does not build a parallel preference engine.

### 5.6 Fatigue prevention

Fatigue is prevented structurally, by composition of guards rather than a single "fatigue model":

1. **Default silence** (§0 principle #2) — most changes never push.
2. **Severity floor** — only `alert`+ pushes.
3. **Daily cap → digest** (§4.5) — interruption count is bounded regardless of volume.
4. **Per-name saturation** (§4.4) — one volatile name cannot flood.
5. **Quiet hours** — time-boxed.
6. **Coalescing** (10A §5.3) — repeated dirties collapse.

No single knob prevents fatigue; the *product* of these does. This is deliberate — a lone fatigue heuristic is gameable and brittle; layered structural limits are not.

### 5.7 Delivery-ledger lifecycle

```
 pending ──flush──► delivering ──► delivered (delivered_at set, terminal)
    │                   │
    │                   ├──► failed (attempts++) ──retry/backoff──► delivering
    │                   │                          (attempts ≥ max → dead, alert)
    ├──quiet/cap──────► deferred ──not_before_utc passes──► pending
    └──guardrail──────► suppressed (terminal: floor/mute/dup/relevance)
```

Ledger rows are **retained, never deleted** — they are the delivery audit trail and the input to the "what changed" history (§6.6). A retention/rollup policy (mirroring 10B's timeline archival, LIVE_CAP-style) ages old `delivered`/`suppressed` rows into an archive table without losing the audit. Archival is the only lifecycle addition.

### 5.8 Notification lifecycle

```
 created (read_at = NULL) ──user opens inbox──► read (read_at set)
                          ──ages past window──► archived (rollup, audit-preserved)
```

Unread-first ordering is the existing frontend contract. Archival mirrors §5.7 and 10B timeline archival — same discipline, same idempotency, same corrupt-row tolerance.

---

## 6. User experience

10C defines six surfaces. Two are **push** (come to the user); four are **pull** (the user comes to them). The push/pull split is the spine of fatigue prevention — anything not worth interrupting still exists, just on a pull surface.

### 6.1 Briefing experience

The once-daily anchor. Opens to the envelope (§2.3): regime headline, the 1–3 "read this first" names, then the collapsed per-name body, then "N unchanged." It is a **stable, finishable artifact** — generated once, immutable for the day, citable. The user can always answer "what's my morning read?" with one item.

### 6.2 Alert experience

An individual, severity-badged inbox item (and push, if `alert`+). Each alert answers three questions in its envelope: *what changed* (the drift direction + driver), *why it matters* (the severity rationale from the prioritizer), *what name* (the ticker + current thesis state). An alert is never a raw signal dump — it is the packaged judgment.

### 6.3 Inbox experience

The unified `GET /notifications` surface, unread-first. Briefings, alerts, and digests interleave by time and float by severity (§2.2). The inbox is the **single source of "what has the system told me."** It is the home base; everything pushed also lands here.

### 6.4 Timeline experience

The per-name history (10B timeline store, capped + archived). The pull surface for "what has happened to *this name* over time." `info`-severity changes that never pushed still land here — the timeline is the complete record, the inbox is the curated interruption stream.

### 6.5 Watchlist experience

The 10B watchlist with live drift state (`/watchlist` + `/watchlist/drift`, reconciled in Slice 9). The pull surface for "what's the current state of everything I watch." Drift direction renders inline; the user scans health at a glance without any push.

### 6.6 "What changed" experience

The cross-name delta view: "what changed across everything since I last looked." Composed from the delivery ledger + timeline archive — every material change in a window, ranked by §4.1 relevance, regardless of whether it pushed. This is the surface that makes *default silence* safe: nothing is lost, the user can always pull the full picture, so the system can afford to push only the few things that truly warrant it.

> **The UX thesis:** push is a privilege the system earns by being right; pull is a guarantee the system always honors. Every byte of intelligence is always available on a pull surface (timeline, watchlist, what-changed); only the highest-relevance slice is ever pushed (briefing, alert). The user never fears missing something by not being interrupted.

---

## 7. Rollout strategy

Identical discipline to 10A/9G, reusing `loop_canary_cohort.py` (CRC32 on `user_id`) and `loop_canary_telemetry.py` (kill switch) **unchanged**. 10C adds no rollout machinery — it is the third customer of the canary infra.

| Stage | Config | Behavior | Gate to advance |
|---|---|---|---|
| **Shadow** | `loop_enabled=True, loop_shadow=True, canary_pct=0` | Generate briefings + alerts, rank, write ledger, **deliver nothing**. (Where 10B left us.) | Ranking distribution sane (no stage where 50→50 pushes); `duplicate_delivery_count = 0`; digest-overflow path produces correct batches in ledger; relevance recheck suppresses correctly. |
| **Internal** | `loop_shadow=False`, deliver to own `user_id` only | Read your own briefings + alerts for a week. | Cadence-feel, briefing quality, alert-fatigue felt firsthand; quiet-hours/cap/mute/digest all fire correctly; no 03:00 push that wasn't `critical`. |
| **Canary 5%** | `canary_pct=5` | CRC32 cohort, permanent 5% holdout. | Delivery success rate ≥ target; **mute/unsubscribe rate below threshold** (the fatigue SLA); cost/cycle ≤ ceiling; dead-letter ~0; digest-vs-individual ratio healthy. |
| **Ramp** | `5 → 25 → 50 → 95` | Hold 5% control permanently. | Each step: no duplicate deliveries, delivery SLA held, **mute/unsubscribe flat or falling**, cost linear-not-exponential, schedule lag flat. |

> **The fatigue SLA is the gate that matters.** 10A's gate was `duplicate_delivery_count = 0`. 10C's defining gate is **mute/unsubscribe rate** — it is the direct measure of whether the ranking earned its pushes. A canary with perfect delivery mechanics but a rising mute rate is a **failed** canary, because it means the system pushed things people didn't want. Cost and correctness are necessary; restraint is the actual product.

### 7.1 Rollback plan

Additive everywhere; rollback is safe at every step.

- **Instant:** `POST /admin/loop/disable` (Tier-0 kill switch, exists) halts all delivery with no redeploy. Generation continues to shadow.
- **Per-cohort:** drop `canary_pct` to 0 — cohort reverts to shadow (generate, don't deliver). No data loss; ledger keeps filling.
- **Code:** revert to the 10B tag; all new tables are additive and unreferenced by older code (`unknown_kind` notifications are ignored, mirroring 10A's `unknown_job_type`).

### 7.2 Kill switch behavior

The exact `force_disable` / `force_enable` (clears override) semantics from `loop_canary_telemetry.py`, reused verbatim (10A §8.2). One in-process flag, resets on restart, config governs when override is null. When disabled: producers still run, ledger still fills (shadow), **zero sends**. The kill switch stops *delivery*, never *generation* — so flipping it off and back on never loses or duplicates intelligence (the ledger's `content_key` dedup absorbs the resume).

---

## 8. Future compatibility

10C's architecture must not have to be reopened for 10D and beyond. Each future capability is a **producer or a sink**, not an architectural change — the same closed-and-additive discipline 10A used.

### 8.1 Portfolio Intelligence (10D)

`portfolio_relevance` alert type is **reserved in §3.1** with its severity mapping pre-defined. 10D binds a portfolio detector to that type; the entire ranking (§4), delivery (§5), and UX (§6) machinery applies unchanged. Portfolio-weighted `user_proximity` (a held position weighs more than a watched one) slots into the existing relevance formula (§4.1) as a multiplier — no new pipeline. The "what changed" surface (§6.6) becomes "what changed in *my portfolio*" by filtering the same ledger.

### 8.2 Forecasting

A forecast is a new artifact class (§1.1 is additive) and a new producer. It rides the same cadence-job model as the briefing (10A §5.2), the same delivery separation, the same ranking. "Your thesis on NVDA implies X by Q3" is a briefing section or an alert, delivered through the existing envelope.

### 8.3 Similarity Engine

Already partially present as `historical_analogs` (Phase 9F). Similarity-driven alerts ("this setup rhymes with a prior episode") bind as a detector behind `new_risk`/`new_catalyst` types, or a new reserved type. The relevance formula consumes its score as another `severity_weight` input.

### 8.4 Investment Jarvis vision

The end-state — a proactive analyst that tells you what you need to know before you ask — is the *sum* of these surfaces: the briefing is its morning report, alerts are its taps on the shoulder, the digest is its restraint, "what changed" is its memory, and the ranking is its judgment. 10C builds the judgment-and-delivery spine that every future Jarvis capability plugs into as a producer. **Nothing in 10C presumes a single user**: `target_key` is already `user_id`-shaped throughout, so multi-user and per-user proactivity are config/data, not rearchitecture.

---

## 9. Data model

All additive. No table is reshaped; no column is dropped. Mirrors the 10A/10B migration discipline (numbered SQL, `IF NOT EXISTS`, nullable new columns).

### 9.1 Reused unchanged

| Table | Role in 10C |
|---|---|
| `delivery_ledger` | the delivery transaction record + dedup (the spine) |
| `notifications` | in-app channel sink (inbox) |
| `briefing_sessions` | generation-side ladder (`pending→generated→delivered`, `content_hash`, `delivery_channel`) |
| `watched_tickers` | watchlist membership → `user_proximity` input |
| `scheduled_jobs` / `job_runs` | the cadence/event jobs that trigger generation |

### 9.2 New / extended (additive)

| Object | Kind | Purpose |
|---|---|---|
| `user_delivery_prefs` | **new table** | per-user: quiet-hours window, per-channel severity floor, channel opt-in, digest-vs-individual pacing (§5.5). NULL row = system defaults. |
| `digest_batches` | **new table** | one row per digest item: `user_id`, `bucket`, `member_content_keys[]`, `summary_json`, status. The §4.5 overflow sink. |
| `delivery_ledger_archive` | **new table** | aged-out ledger rows (§5.7), JSONL/row archive mirroring 10B timeline archival. |
| `notifications.severity` | **new nullable column** | canonical severity (§3.2) for inbox float ordering. Nullable → no rewrite. |
| `delivery_ledger.severity` | **new nullable column** | canonical severity for cap/floor/override decisions at the boundary. |

> The severity columns are the physical home of the §3.2 reconciliation: one canonical value, written once at ranking time, read by every guardrail. This prevents the dual-vocabulary drift the spec warns about by giving severity exactly one storage location.

---

## 10. Event flows and lifecycle diagrams

### 10.1 End-to-end: overnight change → morning inbox

```
 22:00–06:00  substrate changes (dossier_revision / thesis_delta rows land)
     │
     ▼
 loop tick  ──► drift gate: is target dirty since last_generated_at?  ──no──► (nothing)
     │ yes
     ▼
 watchlist_scan producer  ──► alert payload + prioritizer severity
     │
     ▼
 §3.2 canonical severity  ──► §4.1 relevance score
     │
     ▼
 triage (§4.3): critical/alert | notice | info
     │            │              │
     │            │              └─► pull-only (timeline / what-changed)
     │            └─► digest_batches row (§4.5)
     ▼
 delivery_ledger row (content_key dedup, severity, not_before)
     │
     ▼  [user-local morning] delivery_flush
 §3.5 relevance recheck + guardrails (quiet/cap/mute/floor)
     │
     ├─ suppressed / deferred
     ▼
 notification row(s) (kind=daily_brief / watchlist_alert) + push if severity≥alert
     │
     ▼
 inbox renders: briefing (float by max severity) + N alerts + 1 digest
```

### 10.2 The cap-overflow → digest flow (the 10C-defining path)

```
 alert ranked `alert`/`notice`  ──► delivery_flush
     │
     ▼
 daily_cap check: delivered-today ≥ cap?
     │                         │
     no                        yes
     ▼                         ▼
 individual notification   digest_batches: append content_key
                               │
                               ▼ (at digest roll-up time)
                           one notification (kind=digest) summarizing K items
```

### 10.3 Generation/delivery decoupling (inherited from 10A)

```
 GENERATION (paid once, banked)        DELIVERY (retried independently)
 ──────────────────────────────        ────────────────────────────────
 producer runs                         read pending/deferred ledger rows
 compute content_hash + severity       relevance recheck (§3.5)
 write ledger (status=pending)         guardrails (quiet/cap/mute/floor)
 STOP — never sends                    send → delivered | failed(retry) | suppressed
```

---

## 11. Risks

| # | Risk | Likelihood | Mitigation |
|---|---|---|---|
| 11.1 | **Third severity vocabulary** creeps in, reproducing the 10B drift-state bug | medium | §3.2 canonical ladder + single translation function; "new vocabulary = release blocker" gate; severity stored in exactly one column (§9.2) |
| 11.2 | **Fatigue** — ranking pushes too much; mute rate climbs | high (the core product risk) | layered structural limits (§5.6); fatigue SLA is *the* canary gate (§7); default-silence posture (§0) |
| 11.3 | **Under-delivery** — ranking too conservative; users miss real signals | medium | "what changed" pull surface (§6.6) guarantees nothing is lost; tune relevance threshold against shadow distribution before canary |
| 11.4 | **Digest becomes a junk drawer** — everything overflows into it, nobody reads it | medium | digest is overflow of *already-material* changes only (below it is suppressed, not digested); per-name saturation (§4.4) keeps a single name from filling it |
| 11.5 | **Quiet-hours override abused** — too many `critical`s wake people | medium | `critical` is the top of a tuned scorer (0.65 threshold), not a producer flag; monitor override-push rate as a canary sub-metric |
| 11.6 | **Relevance recheck race** — name muted between recheck and send | low | recheck is at the boundary immediately pre-send; residual race is absorbed by `content_key` idempotency on retry |
| 11.7 | **Email/push failure domain** leaks into in-app | low | channels are independent sinks behind the ledger; a push-provider outage degrades to "delivered in-app, push failed (retry)", never blocks the inbox |
| 11.8 | **Cost runaway** from a drift storm | low | inherited 10A circuit breaker (`loop_llm_calls_ceiling_per_cycle`, §9.6); generation gated behind upstream materiality |
| 11.9 | **Per-user prefs absent** at launch (single-user today) | low | `user_delivery_prefs` NULL row = system defaults; multi-user is data, not rearchitecture (§8.4) |

---

## 12. Validation gates

Each stage advances only when its gates are green. Gates are measurable from `/admin/loop-status` (extended in 10C with delivery + ranking sections) and the validation script pattern established in 10A/10B.

### 12.1 Shadow-stage gates

| Gate | Pass condition |
|---|---|
| Ranking sanity | No bucket where pushes == changes (proves triage compresses) |
| Duplicate delivery | `duplicate_delivery_count = 0` (inherited hard gate) |
| Digest overflow | Cap-breaching buckets produce `digest_batches` rows with correct membership |
| Relevance recheck | Muted/removed names between gen and (simulated) send → `suppressed` |
| Severity reconciliation | Every ledger row's `severity` ∈ canonical ladder; zero rows with prioritizer-only vocabulary |
| Channel split | In-app row written; email/push sinks do **not** duplicate the notification row |

### 12.2 Internal-stage gates

| Gate | Pass condition |
|---|---|
| Quiet hours | Zero non-`critical` sends inside the window over 7 days |
| Override discipline | Every quiet-hours send was canonical `critical` |
| Cadence feel | Briefing arrives once per local morning, jittered, never duplicated |
| Cap → digest | Overflow batched, not lost; digest readable |
| Mute | Muting a name stops its pushes within one flush, still appears in timeline |

### 12.3 Canary-stage gates (the ones that decide the phase)

| Gate | Pass condition | Why it's the real bar |
|---|---|---|
| **Mute/unsubscribe rate** | below threshold and **flat or falling** across ramp | the fatigue SLA — the direct measure of whether ranking earned its pushes |
| Delivery success rate | ≥ target | user-visible reliability |
| Cost/cycle | ≤ ceiling, linear in ramp | restraint is also a cost control |
| Dead-letter | ~0 | poison-delivery detector |
| Holdout integrity | permanent 5% control never delivered | clean comparison arm |

> **The single advancement criterion, stated plainly:** 10C proceeds to wider ramp *if and only if* delivering intelligence did not make users turn it off. Every other gate is mechanical correctness; this one is the product. A technically flawless delivery system with a rising mute rate has failed at the only thing 10C exists to do — be worth the interruption.

---

## 13. Open questions for implementation phase

None block the architecture; all are calibration.

1. **Relevance threshold** — the `alert` vs `notice` cut on §4.1 relevance. Set from the shadow-stage distribution of scores against actual substrate events; per-tier, not global, once real cohorts exist.
2. **Digest roll-up time** — fixed daily time vs. accumulation-triggered (N pending). Lean: a fixed pre-morning roll-up so the digest rides into the briefing flush, plus an accumulation trigger for high-volume days.
3. **Per-name saturation curve** (§4.4) — how sharply the 2nd/3rd same-name alert decays. Tune against the most volatile names in shadow.
4. **Quiet-hours default window** — system default before per-user prefs exist. Reuse the existing `delivery_quiet_hours_start/end` config defaults; confirm against the single-user's timezone.
5. **Digest summary rendering** — deterministic template vs. one LLM call per digest. Lean: deterministic template first (zero added cost, mirrors the briefing's "unchanged" line), LLM summary only if the template reads poorly.
6. **Archive retention windows** (§5.7/§5.8) — how long delivered/read rows stay live before rollup. Mirror 10B timeline `LIVE_CAP` discipline; size against inbox query performance.
7. **Push provider** — deferred to the email/push slice; the channel-agnostic envelope means this is a sink-selection decision, not an architecture decision.

---

*End of specification. Design only — implementation, schema migrations, and code are out of scope for this document. 10C builds no new intelligence; it builds the judgment about which intelligence is worth a human's attention, and the disciplined path by which it arrives.*
