# Phase 15 — User Learning Architecture Specification

**Phase:** 15 · User Learning & Personalization
**Status:** Design — not yet implemented
**Audience:** Principal/staff engineers, backend + frontend, trust & safety
**Scope:** Architecture only. No code, no migrations, no implementation in this document.
**Safety invariant family:** **SP-7** (defined in §1.2)

---

## 0. Purpose and the inversion

Every phase shipped so far answers a question **about the world**:

| Phase | Question | Object of knowledge |
|---|---|---|
| 9G Memory | What happened? | the company |
| 11 Similarity | What resembles this? | the setup |
| 12 Forecasting | What tends to happen next? | the outcome |
| 13 Decision | What matters most? | the priority |
| 14 Scenario | What happens if X changes? | the condition |

Phase 15 asks a question **about the user**:

> **What have I learned about this user?**

This is a categorical shift. Phases 9G–14 produce *truth*: model-derived, evidence-backed, user-independent statements about securities and markets. Phase 15 produces *relevance*: an evidence-backed model of what a **specific user** attends to, returns to, ignores, and finds useful.

The two must never be confused, and the architecture's central job is to keep them apart. Truth is computed once and is the same for every user. Relevance is computed per-user and changes only **what the user sees first**, never **what is true**.

> **Design principle #1 — Relevance is a projection of truth, never a rewrite of it.** Phase 15 reads the truth layers (forecasts, similarity, scenarios, decisions, memory) strictly read-only and emits an *ordering, prominence, and attention* layer on top. A forecast's probability, a similarity edge's weight, a decision's score, a scenario's plausibility — none of these is ever modified by anything in Phase 15. If User Learning vanished, every truth value in the system would be byte-for-byte identical.

### 0.1 One-paragraph thesis

The system already knows a great deal about the market and almost nothing about the person reading it. Two users with different mandates — a semiconductor specialist running a concentrated book and a generalist scanning for macro dislocations — receive the same feed in the same order. User Learning observes how each user actually behaves (what they watch, search, open, expand, act on, dismiss, and mute) and assembles an **explainable, falsifiable model of their interests and attention**. That model re-ranks and re-surfaces existing intelligence so the specialist sees their names first and the generalist sees the macro scenario first — **without either user's underlying numbers changing at all.** It learns *relevance*, not *truth*, and it ships shadow-first: nothing the user sees changes until the model is proven accurate, stable, non-fabricating, and incapable of mutating truth.

---

## 1. Design principles and the SP-7 firewall

### 1.1 Principles

> **#1 — Relevance is a projection of truth, never a rewrite of it.** (§0)

> **#2 — Observe, never assume.** Every learned preference is grounded in recorded behavioral events. The system never infers a preference from demographics, account tier, sector membership of holdings, or any prior that the user did not generate through action. No event → no preference.

> **#3 — Evidence threshold before assertion.** A preference is emitted only when its supporting evidence clears a minimum count and confidence. Below threshold the dimension is reported `unresolved`, not guessed. This is the direct analogue of the `insufficient_samples` contract in Phase 14 calibration.

> **#4 — Every belief is falsifiable.** No learned preference may exist without stating what evidence *would overturn it*. A preference that cannot be disproven is fabrication and is rejected at the explainability gate (§8).

> **#5 — Personalization can demote but never bury.** Relevance may reorder and re-weight prominence, but a safety-critical item (e.g. a critical-severity alert on a held position) has a guaranteed floor below which personalization cannot push it (the *relevance floor*, §7.4).

> **#6 — Negative space is signal.** What a user *ignores, dismisses, and mutes* is as informative as what they engage with — and more dangerous to misread. Negative signals are weighted asymmetrically and require repetition before they harden into an `ignored` preference (§5.4).

> **#7 — Shadow until proven.** The relevance layer journals what it *would* do long before it is permitted to do anything. No user-visible reordering occurs until the validation framework (§10) passes acceptance.

### 1.2 The SP-7 invariant family

SP-7 is the Phase 15 safety contract, enforced by read-only sessions, an import firewall, banned-phrase scans, and a dedicated validation script (§10.5), exactly as SP-6 is enforced for the Scenario Engine.

| ID | Invariant | Enforcement |
|---|---|---|
| **SP-7a** | **No-Truth-Mutation.** No Phase 15 component writes to any truth table: `forecast_vector`, `forecast_evidence`, `similarity_edge`, `similarity_feature_vector`, `scenario_snapshot`, `scenario_evidence`, `decision_priority`, `decision_evidence`, `ticker_memory`, `memory_entries`, `thesis_versions`, `thesis_deltas`, `company_dossier*`. | AST write-pattern scan; runtime read-only session; validation script. |
| **SP-7b** | **Read-Only-Upstream.** All consumption of truth layers uses read-only repository methods. No truth repository's write functions are imported. | Import firewall (AST). |
| **SP-7c** | **Ordering-Only-Influence.** Output may set display order, prominence tier, and feed/alert rank. Output may **not** alter any intrinsic score, probability, weight, or evidence field of any item. The intrinsic value passes through untouched; only position and presentation change. | Type-level separation (§7.2); validation. |
| **SP-7d** | **Relevance-Floor.** Personalization may not push a safety-critical item below its guaranteed rank floor, nor suppress it from a surface entirely. | Clamp in relevance scorer (§7.4). |
| **SP-7e** | **No-Fabrication.** No preference is asserted below the evidence threshold. No preference exists without resolvable evidence rows. | Threshold gate (§5.5); evidence-resolution validation. |
| **SP-7f** | **No-Portfolio-Advice.** Holdings and portfolio interactions may inform relevance only. No component emits a holdings recommendation, position size, buy/sell/hold verdict, or trade suggestion. | Banned-phrase scan; §9; import firewall (no conviction/order/execution). |
| **SP-7g** | **Explainability-Mandatory.** No learned preference may persist without all four explanation fields populated and well-formed (§8.1). | Explainability gate before persistence. |

> **Grounding note.** SP-7 is modeled directly on SP-6 (Phase 14). The Scenario Engine already proves the pattern works in production-shadow: an entire intelligence layer that reads the substrate, produces a derived projection, journals it shadow-only, and is validated by a standalone script (`tests/validate_14_scenario_shadow.py`) that asserts zero forbidden imports, zero truth writes, and a green `safe_state`. Phase 15 reuses that machinery wholesale rather than inventing a parallel safety mechanism.

---

## 2. System architecture

### 2.1 Layered view

Phase 15 is six cooperating layers. Each is independently flag-gated and independently inert by default.

```
                         ┌──────────────────────────────────────────────┐
   user actions ───────▶ │ 1. CAPTURE LAYER                             │
  (watch/search/open/    │    signal-event ingestion (append-only)      │
   expand/act/dismiss/    │    → user_signal_event                       │
   mute/explicit pref)   └───────────────────┬──────────────────────────┘
                                             │  raw behavioral stream
                                             ▼
                         ┌──────────────────────────────────────────────┐
                         │ 2. LEARNING LAYER                            │
                         │    periodic inference pass (idempotent)      │
                         │    aggregate → decay → threshold             │
                         │    → learned_preference + preference_evidence │
                         └───────────────────┬──────────────────────────┘
                                             │  evidence-backed beliefs
                                             ▼
                         ┌──────────────────────────────────────────────┐
                         │ 3. PROFILE LAYER (read projection)           │
                         │    assemble user_interest_profile +          │
                         │    learned_priorities                        │
                         └───────────────────┬──────────────────────────┘
                                             │  priorities (per dim/entity)
                  truth layers               ▼
   (forecast/similarity/   ┌────────────────────────────────────────────┐
    scenario/decision/  ──▶│ 4. RELEVANCE LAYER  (READ-ONLY upstream)   │
    alert sets)  READ-ONLY │    re-rank a truth-fixed result set        │
                         │    → relevance_adjustments,                  │
                         │      attention_preferences,                  │
                         │      personalization_context                 │
                         └──────┬───────────────────────────┬───────────┘
                                │ shadow journal            │ (delivery OFF
                                ▼                           ▼  until validated)
                  ┌─────────────────────────┐   ┌────────────────────────┐
                  │ 5. OBSERVABILITY/SHADOW │   │ 6. DELIVERY (gated)    │
                  │  relevance_adjustment_  │   │  apply ordering to a   │
                  │  log + admin status +   │   │  real surface          │
                  │  safe_state             │   │  (Stage 5 only)        │
                  └─────────────────────────┘   └────────────────────────┘
```

Every arrow into a truth layer is **read-only** (SP-7b). The only write targets in the whole phase are the four Phase 15 tables (§4) and — in Stage 5 only — the *order* in which an already-computed surface is rendered.

### 2.2 Component inventory

| Component | Responsibility | Writes to | Reads (read-only) |
|---|---|---|---|
| `user_signal_capture_service` | Normalize and append behavioral events | `user_signal_event` | — |
| `user_learning_inference_service` | Periodic pass: events → preferences | `learned_preference`, `preference_evidence` | `user_signal_event` |
| `user_preference_decay_service` | Time-decay and falsifier evaluation | `learned_preference` (status only) | `user_signal_event`, `learned_preference` |
| `user_profile_service` | Assemble `user_interest_profile`, `learned_priorities` (projection) | — (derived) | `learned_preference`, `preference_evidence` |
| `relevance_service` | Re-rank a truth-fixed result set | — (returns projection) | profile + the result set |
| `relevance_shadow_service` | Journal would-be adjustments | `relevance_adjustment_log` | relevance output |
| `user_learning_explainability_service` | Build/validate the 4 explanation fields | — (gate) | `preference_evidence` |
| `user_learning_observability_service` | Flags + metrics + `safe_state` snapshot | — | all Phase 15 tables |

> **Design principle #8 — Capture is decoupled from learning is decoupled from relevance.** The three heavy stages communicate only through append-only tables, never through in-process calls. This means each can be enabled, disabled, replayed, and validated independently, and a failure in one cannot corrupt another. It mirrors the Phase 10A Continuous Loop's lock-and-journal decoupling.

### 2.3 Null-session and degradation contract

Every Phase 15 async function honors the system-wide **null-session contract**: given `session=None` (or on any internal error), it returns the safe empty value (`[]` / `{}` / `None` / `0`) and never raises. The relevance layer additionally honors a **null-profile contract**: given an empty or sub-threshold profile (cold-start user), it returns the input result set **in its original, un-reordered truth order**. Personalization is always strictly optional; its absence is never an error and never changes correctness.

---

## 3. Learning sources

Phase 15 consumes eight behavioral streams. Each is captured as typed `user_signal_event` rows (§4.1). The table below fixes, for each source, the events captured, the preference dimensions they inform, and the **truth table they are read from read-only** (never written).

| # | Source | Captured events | Informs dimensions | Read-only upstream |
|---|---|---|---|---|
| 1 | **Watchlist behavior** | add, remove, reorder, pin, dwell on watchlist item | companies, sectors, themes | `watched_tickers` |
| 2 | **Search behavior** | query issued, result clicked, result ignored, query refined | companies, sectors, themes, signal types | (search logs / capture-time) |
| 3 | **Analysis history** | analysis opened, section expanded, time-on-analysis, re-open of same name | companies, themes, preferred horizons | `briefing_sessions`, `ticker_memory` |
| 4 | **Alert interactions** | alert delivered, opened, clicked, acted-on, dismissed, muted, snoozed | signal types, ignored signal types, sectors | `delivery_ledger`, `notifications` |
| 5 | **Forecast interactions** | forecast viewed, horizon toggled, evidence expanded, calibration viewed | preferred horizons, preferred signal types | `forecast_vector` (read-only) |
| 6 | **Scenario interactions** | scenario expanded, transmission-path opened, invalidator viewed, dismissed | themes, signal types, portfolio sensitivities | `scenario_snapshot` (read-only) |
| 7 | **Portfolio behavior** | holding viewed, position drilled, repeated visits to a holding's intel | companies, sectors, portfolio sensitivities | `portfolios`, `portfolio_positions`, `portfolio_insights` |
| 8 | **Explicit preferences** | user sets sector follow, horizon preference, signal-type mute, theme follow | all dimensions (highest weight) | (user input) |

> **Design principle #9 — Explicit beats inferred, but inferred is auditable.** An explicit preference (source 8) carries the highest evidence weight and can directly assert a dimension. Inferred preferences (sources 1–7) require the evidence threshold and always cite the specific events behind them. An explicit preference still carries a falsifier (the user can unset it), so the four-field explainability contract holds uniformly.

### 3.1 Signal polarity

Each event carries a **polarity**:

- **Positive** — engagement that indicates interest: add, open, expand, act-on, re-visit, explicit-follow.
- **Negative** — engagement that indicates disinterest: dismiss, mute, ignore-after-surface, explicit-mute.
- **Neutral** — observed-but-ambiguous: delivered-but-not-yet-seen, hover.

Polarity is not symmetric in weight (§5.4): a single dismissal does not equal a single open in magnitude, because "dismiss" frequently means "not now," not "never."

---

## 4. Data model

Phase 15 adds **four** tables, continuing the global numbering (current head: 49 = `scenario_run_log`). The five named *outputs* (§6) are mostly **read projections** assembled by services, not stored tables — only the raw stream, the learned beliefs, their evidence, and the shadow journal are persisted.

| # | Table | Kind | Lifecycle |
|---|---|---|---|
| 50 | `user_signal_event` | Append-only raw stream | Insert-only; aged out by retention window |
| 51 | `learned_preference` | Current-state belief | Upsert per (user, dimension, entity); status-mutable; decayable |
| 52 | `preference_evidence` | Normalized evidence per belief | Insert-only; references events |
| 53 | `relevance_adjustment_log` | Append-only shadow journal | Insert-only; the shadow output surface |

### 4.1 `user_signal_event` (#50)

The raw behavioral substrate. **Append-only** — never updated, never deleted except by the retention sweep.

| Field | Type | Notes |
|---|---|---|
| `id` | uuid | PK |
| `user_id` | uuid | FK to `users` (Phase 16). `NULL` is **not permitted** — anonymous behavior is not learned. |
| `signal_type` | enum | `watchlist_add`, `watchlist_remove`, `search_query`, `search_click`, `analysis_open`, `section_expand`, `alert_open`, `alert_act`, `alert_dismiss`, `alert_mute`, `forecast_view`, `horizon_toggle`, `scenario_expand`, `scenario_dismiss`, `portfolio_view`, `explicit_pref_set`, `explicit_pref_unset`. |
| `polarity` | enum | `positive` / `negative` / `neutral` (§3.1) |
| `entity_type` | enum | `company` / `sector` / `theme` / `signal_type` / `horizon` |
| `entity_key` | string | ticker / sector id / theme key / signal-type name / horizon band |
| `source_surface` | string | which surface emitted the event (feed, alert, search, portfolio) — needed for feedback-loop control (§11) |
| `surface_was_personalized` | bool | whether the surface the user acted on was already personalized — critical for unbiased learning (§11, risk R2) |
| `pre_personalization_rank` | int? | the item's rank *before* any personalization, when available — the unbiased position |
| `interaction_weight` | float | normalized magnitude of the interaction (e.g. dwell-scaled) |
| `occurred_at` | ts | event time |
| `created_at` | ts | ingest time |

Indexes: `(user_id, occurred_at)`, `(user_id, entity_type, entity_key)`, `(user_id, signal_type)`.

> **Design principle #10 — Capture the unbiased position.** `surface_was_personalized` and `pre_personalization_rank` exist so the learning pass can distinguish "the user chose this" from "the user clicked what we put on top." Without them, personalization becomes a self-fulfilling feedback loop. This is the single most important field-level decision in the schema.

### 4.2 `learned_preference` (#51)

The current-state, evidence-backed belief. One row per `(user_id, dimension, entity_key)`.

| Field | Type | Notes |
|---|---|---|
| `id` | uuid | PK |
| `user_id` | uuid | FK |
| `dimension` | enum | `sector_interest`, `company_interest`, `theme_interest`, `preferred_horizon`, `preferred_signal_type`, `ignored_signal_type`, `portfolio_sensitivity` (the seven of §6.1) |
| `entity_key` | string | the specific sector / company / theme / horizon / signal-type |
| `affinity` | float -1..1 | signed strength: positive = interest, negative = aversion/ignore |
| `confidence` | float 0..1 | how strongly the evidence supports the affinity |
| `evidence_count` | int | number of contributing events (denominator for thresholding) |
| `status` | enum | `active` / `unresolved` / `decayed` / `falsified` / `explicit` |
| `belief_basis` | text | explanation field 1 — *why we believe this* (§8.1) |
| `signal_strength_label` | enum | explanation field 3 — `strong` / `moderate` / `tentative` |
| `falsifier` | text | explanation field 4 — *what would change this belief* (§8.1) |
| `first_observed_at` | ts | |
| `last_reinforced_at` | ts | most recent supporting event — drives decay |
| `preference_schema` | int | bumped when the inference model changes (invalidation key) |
| `updated_at` | ts | |

Unique: `(user_id, dimension, entity_key)`. Evidence (field 2) is normalized into #52.

> **Note.** `affinity` is signed so that `ignored_signal_type` and the negative pole of any dimension are first-class, not a bolt-on. A strong negative affinity on `signal_type=scenario` means "this user reliably dismisses scenarios" and is used to *demote* (never hide — SP-7d) scenarios for that user.

### 4.3 `preference_evidence` (#52)

Explanation field 2 — the provenance of each belief. **Insert-only.**

| Field | Type | Notes |
|---|---|---|
| `id` | uuid | PK |
| `preference_id` | uuid | soft FK to `learned_preference` (no cascade) |
| `signal_event_id` | uuid | soft FK to `user_signal_event` |
| `contribution` | float | how much this event moved the affinity (post-decay) |
| `source` | enum | mirrors the learning source (§3) |
| `observed_at` | ts | |

The set of evidence rows for a preference must be **resolvable** (every `signal_event_id` exists) — checked by explainability validation (§10.4).

### 4.4 `relevance_adjustment_log` (#53)

The shadow output surface — the journal of what the relevance layer *would* do. **Append-only.** This is the Phase 15 analogue of `scenario_run_log`.

| Field | Type | Notes |
|---|---|---|
| `id` | uuid | PK |
| `user_id` | uuid | FK |
| `surface` | string | the surface being reordered (feed, alert_digest, watchlist) |
| `run_reason` | enum | `shadow` / `delivery` — `shadow` until Stage 5 |
| `item_ref` | string | the truth item being repositioned (forecast/scenario/decision/alert id) |
| `intrinsic_rank` | int | the item's truth-order rank (read-only input) |
| `adjusted_rank` | int | the rank personalization *would* assign |
| `relevance_weight` | float | the applied weight (bounded, §7.3) |
| `prominence_tier` | enum | `pinned` / `normal` / `muted` (never `hidden` — SP-7d) |
| `floor_applied` | bool | whether the relevance floor clamped this item |
| `evaluated_at` | ts | |
| `created_at` | ts | |

> **Critical:** `intrinsic_rank` and `adjusted_rank` are both recorded so that shadow validation can measure *exactly how much* personalization would have moved each item, and confirm that no safety-critical item was ever pushed below its floor. The item's underlying score is **not** in this table because Phase 15 never has it to write.

---

## 5. Learning framework

The learning pass is a **periodic, idempotent batch** (cadence governed by the continuous loop, Phase 10A) that transforms the event stream into beliefs. It never runs inline on a user request.

### 5.1 Pipeline

```
events (windowed) ─▶ group by (user, dimension, entity)
                  ─▶ time-decay each event's weight
                  ─▶ aggregate to a raw affinity + evidence_count
                  ─▶ threshold gate (min evidence, min confidence)
                  ─▶ explainability gate (4 fields well-formed)
                  ─▶ upsert learned_preference + insert preference_evidence
```

### 5.2 Dimension extraction

Each event maps to one or more `(dimension, entity_key)` targets via a fixed, versioned mapping (`preference_schema`). Examples (illustrative, not exhaustive):

- `analysis_open(ticker=NVDA)` → `company_interest:NVDA` (+), `sector_interest:semiconductors` (+, attenuated)
- `alert_dismiss(signal_type=scenario)` → `ignored_signal_type:scenario` (–), requires repetition (§5.4)
- `horizon_toggle(horizon=long)` → `preferred_horizon:long` (+)
- `portfolio_view(ticker=AAPL) × repeated` → `portfolio_sensitivity:AAPL` (+)

### 5.3 Recency decay

Interest is non-stationary. Each event's contribution is decayed by age:

```
weight(event, t_now) = interaction_weight · exp(−λ · age_days)
raw_affinity(user, dim, entity) = Σ_events signed(polarity) · weight(event, t_now)
```

`λ` is dimension-specific: company interest decays slower than a single search; ignored-signal preferences decay slowest (a mute should persist). `last_reinforced_at` drives decay between passes; a preference with no reinforcing event for its dimension's half-life transitions `active → decayed`.

### 5.4 Asymmetric negative weighting

Per principle #6, negative events are weighted asymmetrically and gated by repetition:

- A negative event contributes with a damping factor `κ < 1` relative to a positive event of equal magnitude.
- An `ignored_*` preference may reach `active` only after **N distinct negative events across distinct sessions** (a single bad day cannot mute a signal type).
- A subsequent positive event on the same entity **resets** the negative accumulation (the user came back).

### 5.5 Threshold gate (SP-7e)

A preference is asserted `active` only when:

```
evidence_count ≥ MIN_EVENTS[dimension]   AND   confidence ≥ MIN_CONFIDENCE[dimension]
```

Otherwise the preference is written/kept as `unresolved` (visible to observability, **invisible to the relevance layer**). This is the structural guarantee against fabrication: the relevance layer consumes only `active` and `explicit` preferences.

### 5.6 Confidence model

`confidence` rises with evidence count, consistency (low variance in polarity), and recency, and falls with sparsity and oscillation. It is the same shape as the calibration confidence used in Phase 14 and feeds the `signal_strength_label` (strong / moderate / tentative) shown in explanations.

---

## 6. User profile and outputs

The profile layer assembles the five required outputs. Four are **read projections** (computed on demand, DB-down-safe); one (`relevance_adjustments`) is produced by the relevance layer per request.

### 6.1 `user_interest_profile`

The aggregate, queryable model — a projection over `learned_preference` (status ∈ {active, explicit}) across the **seven learnable dimensions**:

| Dimension | Meaning |
|---|---|
| `sectors of interest` | sectors the user repeatedly engages |
| `companies of interest` | names the user watches/opens/revisits |
| `recurring themes` | themes co-occurring across the user's analyses |
| `preferred horizons` | short / medium / long bias from forecast/horizon behavior |
| `preferred signal types` | forecast / scenario / decision / similarity / memory affinity |
| `ignored signal types` | signal types the user reliably dismisses/mutes |
| `portfolio sensitivities` | holdings/sectors the user attends to most |

Each entry carries its affinity, confidence, signal-strength label, and a pointer to its explanation (§8). Cold-start users return an **empty profile**, not a default profile (principle #2).

### 6.2 `learned_priorities`

A ranked, per-entity **salience map** derived from the profile: for a given candidate set of entities/signal-types, the priorities the relevance layer should weight. This is the bridge object between "what we know about the user" and "how to order this specific list." It contains *weights*, never *scores* — it cannot express truth.

### 6.3 `relevance_adjustments`

Produced per request by the relevance layer (§7): the concrete list of `(item_ref, intrinsic_rank → adjusted_rank, prominence_tier, floor_applied)` deltas for a specific surface and result set. In shadow mode these are journaled to `relevance_adjustment_log` and **not applied**.

### 6.4 `attention_preferences`

The *form and timing* of attention, distinct from *content* interest:

- preferred density (how many items per surface)
- preferred cadence (digest frequency, quiet hours) — read-only-aligned with Phase 10C delivery prefs
- preferred depth (does the user expand evidence, or skim?)
- modality affinity (does the user engage alerts vs briefings vs feed?)

`attention_preferences` influences *how much* and *how often*, never *what is true*. It informs delivery batching and density only.

### 6.5 `personalization_context`

The single immutable bundle handed to a ranking consumer at request time:

```
personalization_context = {
   user_id,
   profile:              user_interest_profile (active + explicit only),
   priorities:           learned_priorities,
   attention:            attention_preferences,
   relevance_floor:      the safety-critical clamp config (SP-7d),
   provenance:           per-dimension explanation pointers,
   schema_version, generated_at, db_available, safe_state
}
```

It is read-only to the consumer. A consumer that ignores it produces the un-personalized (truth-order) result — which must always remain correct.

---

## 7. Relevance framework

The relevance layer is the projection that turns priorities into ordering. It is the **only** layer that touches a user-visible surface, and even then only in Stage 5.

### 7.1 Contract

Input: a **truth-fixed result set** — items already fully computed by the truth layers, each carrying an `intrinsic_priority` (and, where applicable, a `severity`). Output: the **same items**, re-ordered, each annotated with a `prominence_tier`. No item's intrinsic fields are read for mutation; none is added or removed (SP-7c, SP-7d).

> **Design principle #11 — Same set, new order.** The relevance layer is a permutation-with-annotation over its input. It may not add an item (that would be fabricating intelligence), may not drop an item (that would be hiding truth — SP-7d), and may not edit an item (SP-7c). Its entire expressive power is *order* and *prominence tier*.

### 7.2 Type-level separation

`intrinsic_priority` enters as an immutable input field and is **copied, never mutated**, into the output. The output ordering is a separate field (`adjusted_rank`). A reviewer can confirm SP-7c by checking that no code path assigns to an item's intrinsic fields — the same static-analysis guarantee SP-6 gives the Scenario Engine.

### 7.3 Relevance scoring

```
relevance_weight(item, user) = clamp(
    Σ_dim  affinity(user, dim) · match(item, dim) · confidence(user, dim),
    [W_MIN, W_MAX]
)

display_score(item) = intrinsic_priority(item) · (1 + relevance_weight(item, user))
adjusted_rank       = rank by descending display_score
```

`intrinsic_priority` is read-only; `display_score` is an ephemeral ordering key that exists only inside the sort and is never persisted onto the item. `[W_MIN, W_MAX]` is bounded (e.g. ±0.5) so personalization is a **nudge, not an override** — a top-truth item can be moved, but a bottom item cannot leapfrog the entire board on relevance alone.

### 7.4 The relevance floor (SP-7d)

Before emitting order, the layer applies the floor:

```
if item.severity == critical:
    adjusted_rank = min(adjusted_rank, FLOOR_RANK)     # cannot be buried
    prominence_tier = max(prominence_tier, normal)     # cannot be muted
    floor_applied = True
no item is ever assigned prominence_tier = hidden       # SP-7d: demote, never hide
```

A critical alert on a held position can be demoted *within reason* but is guaranteed a floor and can never be muted or dropped. This is the hard stop that makes personalization safe to ship.

### 7.5 Novelty reserve (anti-bubble)

To prevent the echo chamber (risk R1, §11), a fixed fraction of every personalized surface is reserved for **high-intrinsic, low-affinity** items — important things the user has *not* historically engaged. Personalization gets the majority of the surface; novelty keeps a guaranteed minority. This is a relevance-layer policy, not a truth change.

---

## 8. Explainability framework

Per the requirement, **every** learned preference must answer four questions. These map to four mandatory, persisted fields, gated before write (SP-7g). This is the direct analogue of the Scenario Engine's mandatory five-field explanation gate.

### 8.1 The four mandatory fields

| # | Question | Field | Source | Well-formed iff |
|---|---|---|---|---|
| 1 | **Why do we believe this?** | `belief_basis` | the inference rule that fired | non-empty; names the behavior pattern (e.g. "opened NVDA analysis 14× in 30d") |
| 2 | **What evidence supports it?** | `preference_evidence` rows (#52) | the contributing events | ≥ `MIN_EVENTS[dimension]` resolvable event rows |
| 3 | **How strong is the signal?** | `signal_strength_label` + `confidence` | the confidence model (§5.6) | label ∈ {strong, moderate, tentative}; consistent with confidence |
| 4 | **What would change this belief?** | `falsifier` | the decay/reversal condition | non-empty; states an observable (e.g. "30d without a semiconductor interaction, or 3 dismissals") |

A preference missing or malformed on **any** field is rejected at the gate and never reaches `active`. A preference that cannot state its falsifier (field 4) is, by definition, unfalsifiable and therefore fabrication — it is rejected (principle #4).

### 8.2 Surfacing explanations

Because each preference is self-describing, the system can render — for any personalized ordering — a per-item "why you're seeing this" trace:

> *"NVDA scenario surfaced first because you opened NVDA analyses 14× in the last 30 days (strong). This will fade if you stop engaging semiconductors for 30 days."*

This trace is assembled entirely from the four fields plus the relevance weight; it never exposes another user's data and never asserts truth ("you should…"), only relevance ("you tend to…").

---

## 9. Decision boundary and portfolio context

This section restates the requirement's hard boundary as enforced contract.

### 9.1 What User Learning MAY influence

| Influence | Mechanism | Invariant |
|---|---|---|
| ordering | `adjusted_rank` (§7.3) | SP-7c |
| prominence | `prominence_tier` (§4.4) | SP-7c, SP-7d |
| feed ranking | relevance layer over the feed surface | SP-7c |
| alert ranking | relevance layer over the alert digest | SP-7c, SP-7d (floor) |

### 9.2 What User Learning MUST NOT influence

| Forbidden | Why | Invariant |
|---|---|---|
| forecasts | truth — same for all users | SP-7a |
| similarity scores | truth | SP-7a |
| scenario outputs | truth (and SP-6 already protects it) | SP-7a |
| underlying evidence | provenance of truth | SP-7a |

### 9.3 Portfolio context boundary (SP-7f)

User Learning **may consider** holdings, watchlists, and repeated portfolio interactions — strictly as *relevance signal* (e.g. "this user attends most to their semiconductor holdings, so rank their semiconductor intelligence higher").

User Learning **must not**:

- recommend buying, selling, holding, sizing, or adjusting any position
- emit a target price or directional verdict
- import or call any conviction, order, execution, or decision-write module
- produce any portfolio-level instruction of any kind

Holdings inform *what to show first*, never *what to do*. SP-7f is enforced by the same banned-phrase scan and import firewall that protect SP-6 in Phase 14.

---

## 10. Validation framework

Phase 15 defines five validation surfaces. The first four are *quality* measures; the fifth is a *safety* gate that must be green before any stage advance.

### 10.1 Preference accuracy

**Question:** do learned preferences predict subsequent engagement?
**Method:** hold out the most recent window of events. From preferences learned on the earlier window, predict which entities/signal-types the user will engage in the held-out window. Measure:

```
preference_accuracy = correctly_predicted_engagements / total_predicted_engagements
```

Reported with `insufficient_samples` when the user has too few events (mirrors Phase 14 calibration). A preference layer that cannot beat truth-order engagement is not worth shipping.

### 10.2 Preference drift

**Question:** are preferences stable, or thrashing?
**Method:** track affinity trajectories across passes. Compute, per dimension:

```
drift_rate = fraction of active preferences whose affinity sign flips within a window
```

High drift = the model is chasing noise. Healthy interest evolves slowly; drift above a band flags the dimension's `λ`/threshold for tuning and suppresses delivery for that dimension.

### 10.3 False-preference detection

**Question:** are we asserting interests the user does not actually have?
**Method:** two detectors:

- **Precision check:** an `active` preference that receives *zero* reinforcing engagement over a full half-life is a false positive → `decayed`/`falsified`. Track `false_preference_rate`.
- **Burst detector:** a preference whose evidence is concentrated in a single session/day (low session-entropy) is flagged as a possible single-burst artifact and held at `unresolved` until corroborated across sessions (§5.4).

### 10.4 Explainability validation

**Question:** is every belief well-formed and grounded?
**Method:** for every `active`/`explicit` preference assert:

- all four fields present and non-empty (SP-7g)
- every `preference_evidence.signal_event_id` resolves to a real event
- `evidence_count` ≥ `MIN_EVENTS[dimension]`
- `falsifier` parses to a checkable condition

Any failure blocks the preference from the relevance layer.

### 10.5 No-truth-mutation validation (the safety gate)

**Question:** has Phase 15 touched truth?
**Method:** a standalone script — `tests/validate_15_user_learning_shadow.py` — modeled exactly on `tests/validate_14_scenario_shadow.py`, asserting (exit 0 required):

- DB table count ≥ 53; the four Phase 15 tables exist
- every Phase 15 service imports cleanly
- all Phase 15 flags inert by default (§11.1)
- **no Phase 15 service imports any truth-write repository** (forecast/similarity/scenario/decision/memory/dossier write functions) — AST import firewall (SP-7b)
- **no Phase 15 service contains a write pattern against any truth table** — AST write scan (SP-7a)
- no conviction / order / execution import anywhere (SP-7f)
- no buy/sell/hold/target-price/position-size language in any string constant (SP-7f, banned-phrase scan)
- no preference persisted below threshold (SP-7e)
- relevance layer never emits `prominence_tier = hidden`; floor is always applied to critical items (SP-7d)
- `safe_state.overall == true` on the observability snapshot
- `relevance_adjustment_log.run_reason == shadow` everywhere until Stage 5

### 10.6 Observability snapshot

A `GET /admin/user-learning-status` admin route (read-only, DB-down-safe) returns flags, metrics (event counts by type, preference counts by dimension/status, shadow-adjustment count, latest-pass timestamp), and a structured `safe_state` with named sub-checks (`no_truth_writes`, `shadow_only`, `no_portfolio_advice`, `floor_enforced`, `no_sub_threshold_preferences`), exactly mirroring `build_scenario_observability_snapshot`.

---

## 11. Rollout strategy

Shadow-first, identical in philosophy to Phase 14. No user-visible personalization exists until §10 passes acceptance.

### 11.1 Flags (all default inert)

| Flag | Default | Gate |
|---|---|---|
| `learning_capture_enabled` | `false` | append `user_signal_event` rows |
| `learning_inference_enabled` | `false` | run the learning pass → `learned_preference` |
| `learning_relevance_enabled` | `false` | compute relevance adjustments |
| `learning_shadow` | `true` | journal adjustments to `relevance_adjustment_log` without applying |
| `learning_delivery_enabled` | `false` | **apply** ordering to a real surface — never `true` before Stage 5 sign-off |
| `learning_explicit_prefs_enabled` | `false` | accept explicit user preferences |

With these defaults: nothing is captured, nothing is learned, no surface changes. The phase is fully inert on deploy — the same guarantee Phase 14 ships with.

### 11.2 Stages

| Stage | Flags on | Effect | Exit criterion |
|---|---|---|---|
| **0 — Inert baseline** | none | services deployed, fully dormant | `validate_15` exits 0 |
| **1 — Capture only** | `capture` | events accumulate; nothing learned | event stream healthy; no truth writes |
| **2 — Shadow inference** | `capture`, `inference`, `shadow` | preferences learned + explained; **no surface change** | preference_accuracy ≥ target; explainability validation green |
| **3 — Shadow relevance** | + `relevance` | adjustments computed + journaled; compare would-be vs truth order | drift within band; false_preference_rate within band; floor always honored in log |
| **4 — Acceptance** | (no new flags) | run full §10 suite over a real shadow window | all five validations pass; `safe_state` green |
| **5 — Delivery** | + `delivery` (per-surface, per-cohort) | personalization applied to a real surface, staged by cohort | live engagement non-regression; instant rollback ready |

`learning_explicit_prefs_enabled` may be turned on from Stage 2 onward independently (explicit preferences are the safest signal and the most defensible to surface).

### 11.3 Rollback

Set `learning_delivery_enabled=false` to return any surface to truth order instantly — no data migration, no recompute. Learned preferences persist (harmless while not applied) or can be parked by also clearing `learning_relevance_enabled`. Because the relevance layer is a pure permutation over a truth-fixed set, removing it can never change correctness — only order.

### 11.4 Cohort staging at Stage 5

Delivery turns on per-surface and per-cohort (internal users → opt-in beta → percentage ramp), each step gated on engagement non-regression and zero safety-gate violations, mirroring the canary discipline used elsewhere in the system.

---

## 12. Risks and mitigations

| ID | Risk | Mitigation |
|---|---|---|
| **R1** | **Filter bubble / echo chamber** — personalization suppresses novel or contrarian intelligence. | Novelty reserve (§7.5); relevance floor (§7.4); bounded weight (§7.3) so personalization nudges, never dominates. |
| **R2** | **Feedback loop** — learning from an already-personalized surface reinforces itself. | Capture `surface_was_personalized` + `pre_personalization_rank` (§4.1, principle #10); learn from unbiased position; reserve a holdout cohort that is never personalized, as a clean signal. |
| **R3** | **Single-burst overfitting** — one busy day fabricates a false preference. | Min-evidence threshold (§5.5); cross-session repetition requirement (§5.4); burst detector (§10.3). |
| **R4** | **Negative-signal misread** — a dismiss treated as "never" when it meant "not now." | Asymmetric damping `κ` (§5.4); repetition gate for `ignored_*`; positive event resets negative accumulation. |
| **R5** | **Cold start** — new user has no signal. | Empty profile, not default profile (principle #2); null-profile contract returns truth order (§2.3); explicit prefs as the fast path. |
| **R6** | **Truth contamination** — accidental write-back into a truth table. | SP-7a/b; read-only sessions; import firewall + write-scan in `validate_15` (§10.5); the entire phase has only four write targets. |
| **R7** | **Privacy / creepiness** — over-precise inference feels invasive. | Conservative thresholds; user-visible, user-controllable preferences; every belief explainable and falsifiable (§8); explicit unset always available. |
| **R8** | **Portfolio-advice leak** — holdings interest drifts into recommendation. | SP-7f; banned-phrase scan; import firewall (no conviction/order/execution); holdings inform order only (§9.3). |
| **R9** | **Stale preference** — interests change, model lags. | Recency decay (§5.3); drift detection (§10.2); falsifier-driven `decayed`/`falsified` transitions. |
| **R10** | **Suppressing a safety-critical alert** — personalization buries something the user needed to see. | Relevance floor (SP-7d, §7.4): demote-never-hide; critical severity is clamped and can never be muted or dropped. |

---

## 13. Grounding and related work

Phase 15 invents almost no new machinery; it composes proven patterns from earlier phases:

| Pattern | First proven in | Reused here |
|---|---|---|
| Shadow-first rollout with inert default flags | Phase 14 Scenario Engine | §11 |
| Standalone `validate_NN_*_shadow.py` safety script | Phase 14 (`validate_14_scenario_shadow.py`) | §10.5 |
| `safe_state` observability snapshot + admin route | Phase 14 (`scenario_observability_service`) | §10.6 |
| Append-only run/shadow journal (`*_run_log`) | Phase 13/14 (`decision_ranking_log`, `scenario_run_log`) | `relevance_adjustment_log` (§4.4) |
| Mandatory explanation-field gate before persist | Phase 14 (5-field scenario explanation) | 4-field preference gate (§8) |
| `insufficient_samples` / threshold-before-assertion | Phase 14 calibration | evidence threshold (§5.5) |
| Recency-decayed scoring + drift metrics | Phase 14 calibration | §5.3, §10.2 |
| Null-session / DB-down degradation contract | system-wide | §2.3 |
| Per-user scoping on `user_id` | Phase 16 Accounts & Identity | all tables (§4) |
| Banned-phrase + import firewall (no advice) | Phase 13 SP-5 / Phase 14 SP-6 | SP-7f (§9.3) |

### 13.1 New artifacts Phase 15 will introduce (implementation phase, not this doc)

- Tables 50–53 (§4)
- Services in the component inventory (§2.2)
- Six flags (§11.1)
- `GET /admin/user-learning-status` (§10.6)
- `tests/validate_15_user_learning_shadow.py` (§10.5)
- `docs/PHASE_15_USER_LEARNING_ROLLOUT.md` (operational runbook, authored at implementation time)

### 13.2 Open questions for implementation review

1. **Cadence of the learning pass** — event-count-triggered vs fixed-interval vs both. Leaning: piggyback on the Phase 10A continuous loop with an event-count floor.
2. **Theme extraction source** — whether `theme_interest` is derived from existing `theme_clusters` (9G) read-only or from a Phase-15-local co-occurrence pass. Leaning: read `theme_clusters` to avoid re-deriving truth.
3. **Retention window** for `user_signal_event` — balances learning richness against privacy footprint. Leaning: rolling window aligned with the longest dimension half-life, with explicit-pref events exempt.
4. **Holdout cohort size** for unbiased feedback-loop control (R2) — what fraction never gets personalized, permanently, as a clean measurement baseline.

---

*End of Phase 15 architecture specification. Design only — no code, no migrations, no implementation.*
