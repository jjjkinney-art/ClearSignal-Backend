# Phase 13 — Decision Intelligence

Status: **architecture only — no code, no implementation.**
This document defines what must be built in Phase 13 before any slice is
written. Every implementation decision must be traceable to a section here.

---

## 0. What this is not

Phase 13 produces **no recommendations, no position sizing, no trade
suggestions, no target prices.** It does not tell a user what to *do*. It
determines what *deserves their attention* and in what order.

The distinction is structural and load-bearing:

| Forecasting (Phase 12) answers | Decision Intelligence (Phase 13) answers |
|---|---|
| What tends to happen next? | What matters most right now? |
| Produces probabilities | Produces priorities |
| Generates new signal | Consumes existing signal |
| Per-outcome | Per-attention-candidate, ranked |

Phase 13 is a **prioritization engine, not a forecasting engine.** It never
generates a forecast, a probability, a similarity score, or a memory record.
It consumes those artifacts and ranks them by significance, urgency, and
expected impact.

The no-advice boundary is enforced the same way Phase 12's no-price boundary
is enforced: **there are no fields to put advice in.** No column holds a
buy/sell/hold verdict, a recommended size, a target price, or a trade
instruction. There is no delivery path that emits such a field. Any output
that would read as investment advice at the UI layer is blocked at the schema
level because the schema cannot represent it.

Decision Intelligence prioritizes information. It does not make investment
decisions.

---

## 1. Overview

### 1.1 What Phase 13 adds

Phases 9G–12 built a complete intelligence substrate and three answering
engines:

- **Memory (9G)** — *What happened before?*
- **Similarity (11)** — *What does this resemble?*
- **Forecasting (12)** — *What tends to happen next?*

Each engine surfaces signal independently. None of them ranks across
engines. A user with an active forecast on NVDA, a similarity match on a
watchlist name, three thesis transitions, and a portfolio risk has **no
mechanism that says which of these to look at first.** Every surface — inbox,
alerts, briefings, watchlist, portfolio view — orders its own items by its own
local rule (recency, severity, alphabetical). There is no global notion of
*consequence*.

Phase 13 adds that layer. It consumes the substrate and produces a single,
explainable, portfolio-aware **priority ranking** over attention candidates.

### 1.2 Core design principle

Every priority is a **composite over signals that already exist**, never a new
measurement. The five component scores —

```
attention_score   how much this should command attention
urgency_score     how time-sensitive it is
impact_score      expected magnitude of effect (portfolio-aware)
confidence_score  reliability of the underlying signals
uncertainty_score disagreement / spread among the signals
```

— are each derived entirely from upstream artifacts (forecasts, similarity
edges, thesis transitions, portfolio exposure, delivery transitions,
calibration history). The composite `decision_priority` is a deterministic
function of those five. No component introduces information the substrate did
not already contain. Phase 13 **re-weights and orders**; it does not observe.

### 1.3 Dependency direction (non-negotiable)

```
Phase 9G   Phase 10A/B/C/D   Phase 11   Phase 12
   ↓             ↓              ↓          ↓
                  Phase 13
```

- Phase 13 **imports from** Phases 9G, 10A/B/C/D, 11, 12.
- **Nothing in Phases 9G–12 ever imports from Phase 13.**
- This is enforced by AST import-graph checks in the validation script (the
  same mechanism that enforced Phase 11 SP-4 and Phase 12 SP-4-extension).
- Violating this direction is a blocking defect.

The corollary matters as much as the rule: **Decision output must never flow
back upstream.** A priority ranking must not alter a forecast, a similarity
score, a thesis, a memory record, or a calibration log. Phase 13 is a pure
sink. See §13 (SP-5).

### 1.4 Relationship to delivery

Once validated, Phase 13 becomes the **ordering and prominence layer** for the
existing delivery surfaces (inbox, alerts, briefings, watchlist, portfolio
intelligence). It does not replace those surfaces or change what they contain
— it changes the order in which their contents appear and which item is given
prominence. Until validated, it produces a shadow ranking that no surface
reads (see §11).

---

## 2. Architecture

### 2.1 Service layer

Five primary services, one per functional boundary (mirroring the Phase 12
shape):

```
decision_candidate_builder    assembles attention candidates from the substrate
decision_scoring_engine       computes the five component scores + composite
decision_explainability_service constructs why / why-now / evidence / de-prioritizers
decision_read_service         read-only access layer (admin + delivery consumers)
decision_observability_service snapshot for /admin/decision-status
```

Two supporting services:

```
decision_invalidation_service   staleness detection and re-rank triggering
decision_calibration_service    ranking-outcome logging + drift/stability metrics
```

One delivery-adjacent service (shadow-gated):

```
decision_ranking_service        the prioritization layer that orders/promotes
                                surface items — SHADOW-ONLY until §11 stage 4
```

No service in this layer writes to any upstream table. Every service follows
the **null-session pattern** (§2.4) and the **flag-inert default** (§2.3).

### 2.2 Repository layer

```
decision_repo
  upsert_decision_priority        insert-or-update one priority row
  list_decision_priorities        filtered read (entity / user / band)
  count_decision_priorities       observability counts
  delete_priority_evidence        clear evidence for a priority before rebuild
  add_priority_evidence           insert evidence rows
  add_ranking_log                 INSERT-ONLY append to the immutable log
  list_ranking_logs               windowed read for drift
  count_ranking_logs              observability counts
```

`add_ranking_log` has **no update and no delete path**, exactly like
`add_calibration_log` in Phase 12. Immutability is enforced in the repository
(no SELECT-then-update) and verified by AST inspection in the validation
script.

### 2.3 Config flags (all default inert)

```
decision_build_enabled        False   gate: assemble candidates / build priorities
decision_scoring_enabled      False   gate: compute component & composite scores
decision_delivery_enabled     False   gate: allow rankings to reorder real surfaces
decision_shadow               True    journal rankings to the shadow log only
decision_targets_enabled      ""      comma-separated entity_type allowlist
decision_calibration_enabled  False   gate: ranking-outcome logging + drift
```

Default production behavior is fully inert: with `decision_build_enabled` and
`decision_scoring_enabled` False, no priority is ever built; with
`decision_delivery_enabled` False and `decision_shadow` True, even a built
ranking is journaled to the shadow log and read by **no** user-visible surface.

Flag semantics mirror Phase 12 exactly so the operational runbook is identical:
build + scoring produce shadow artifacts; delivery is a separate, later gate.

### 2.4 Null-session pattern

Every async function returns the safe empty value (`None` / `[]` / `0` /
`False` / `{}`) immediately when `session is None`, and never raises. All DB
access is wrapped; failures degrade to the empty value and a debug log. This is
the same discipline used across Phases 10–12 and is required for the
observability route to be DB-down-safe.

---

## 3. Data model

Three new tables, continuing the global table numbering from Phase 12
(which ended at table 43, `forecast_calibration_log`).

### Table 44: `decision_priority`

The priority cache. One row per ranked attention candidate, per user scope.

| Column | Type | Notes |
|---|---|---|
| `id` | String(36) PK | uuid |
| `candidate_type` | String(30) | `forecast` \| `risk` \| `catalyst` \| `watchlist_item` \| `portfolio_exposure` \| `thesis_transition` \| `similarity_match` |
| `entity_type` | String(20) | `company` \| `thesis` \| `failure_mode` \| `portfolio` |
| `entity_key` | String(200) | ticker / thesis_id / failure_mode_id / portfolio_id |
| `source_ref` | String(200) | id of the originating artifact (forecast_vector.id, similarity_edge.id, watchlist row, etc.) |
| `decision_priority` | String(20) | bucket: `critical` \| `high` \| `medium` \| `low` \| `informational` |
| `decision_rank_score` | Float | continuous [0,1] used for ordering within and across buckets |
| `attention_score` | Float | [0,1] |
| `urgency_score` | Float | [0,1] |
| `impact_score` | Float | [0,1] — portfolio-aware (§7) |
| `confidence_score` | Float | [0,1] |
| `uncertainty_score` | Float | [0,1] |
| `decision_reason` | Text | dominant-factor prose — MUST be non-empty |
| `why_now` | Text | urgency driver prose — MUST be non-empty |
| `deprioritizers` | JSON list | named conditions that would lower this priority — MUST be non-empty |
| `evidence_summary` | JSON list | top-N condensed evidence items |
| `source_versions` | JSON dict | `{table: row_version}` provenance for staleness |
| `decision_schema` | Integer | bumped when the scoring formula or weights change |
| `user_id` | String(36) nullable | identity scope (Phase 16). NULL = global / unexposed baseline |
| `built_at` | DateTime(tz) | |
| `expires_at` | DateTime(tz) | TTL materialization |

**Unique constraint:** `(candidate_type, entity_type, entity_key, source_ref, user_id)`.

**Explainability invariant (enforced before upsert):** `decision_reason`,
`why_now` non-empty; `deprioritizers` a non-empty JSON list; at least one
`evidence_summary` item. A priority that cannot explain itself is **never
stored** (§6).

**Score invariant (enforced before upsert):** all five component scores ∈
[0,1]; `decision_rank_score` ∈ [0,1]; `decision_priority` bucket consistent
with `decision_rank_score` thresholds (§5.7).

This is a **DERIVED cache** — dropping `decision_priority` degrades latency,
never correctness. No advice, size, price, or trade field exists here.

### Table 45: `decision_evidence`

Normalized evidence rows, one per contributing upstream signal. Mirrors
`forecast_evidence`.

| Column | Type | Notes |
|---|---|---|
| `id` | String(36) PK | uuid |
| `priority_id` | String(36) | soft FK to `decision_priority.id`, no CASCADE |
| `source_type` | String(40) | `forecast_vector` \| `similarity_edge` \| `historical_analog` \| `thesis_version` \| `watchlist_signal` \| `portfolio_exposure` \| `delivery_transition` \| `calibration_log` |
| `source_id` | String(200) | primary key of the source row |
| `dimension` | String(20) | which score this fed: `attention` \| `urgency` \| `impact` \| `confidence` \| `uncertainty` |
| `contribution` | Float | signed contribution to that dimension |
| `weight` | Float | weight in the dimension aggregate [0,1] |
| `description` | Text | human-readable statement — MUST be non-empty |
| `entity_type` | String(20) | denormalized |
| `entity_key` | String(200) | denormalized |
| `user_id` | String(36) nullable | identity scope |
| `built_at` | DateTime(tz) | |

No unique constraint — one priority has many evidence rows.

### Table 46: `decision_ranking_log`

Immutable append-only snapshot of rankings, used for drift and stability
validation. Modeled on `forecast_calibration_log`: **no update path, no delete
path, in any service or repository.**

| Column | Type | Notes |
|---|---|---|
| `id` | String(36) PK | uuid |
| `priority_id` | String(36) | soft FK, denormalized to survive priority expiry |
| `candidate_type` | String(30) | denormalized |
| `entity_type` | String(20) | denormalized |
| `entity_key` | String(200) | denormalized |
| `user_id` | String(36) nullable | identity scope |
| `decision_priority` | String(20) | bucket at snapshot time |
| `decision_rank_score` | Float | score at snapshot time |
| `rank_position` | Integer | ordinal position within the user's ranked set at snapshot time |
| `snapshot_reason` | String(40) | `scheduled` \| `rebuild` \| `transition` \| `manual_review` |
| `realized_significance` | String(20) nullable | filled later by calibration: `material` \| `immaterial` \| `unknown` |
| `evaluated_at` | DateTime(tz) | immutable |
| `created_at` | DateTime(tz) | immutable — never updated |

`realized_significance` is written **once** at evaluation time by appending a
*new* log row keyed to the same `priority_id`, never by updating an existing
row (append-only outcome attribution, identical to Phase 12 calibration).

### Migration

`013_decision_intelligence.sql` — creates tables 44–46 and their indexes.
Applied at startup via the existing idempotent `create_all` hook (the same
path that brought Phase 12 from 38 → 43 tables). Expected production table
count after deploy: **46**.

---

## 4. Decision questions and candidate scope

### 4.1 The questions the engine answers

| Question | Candidate type | Ranked by |
|---|---|---|
| Which forecast matters most? | `forecast` | impact × confidence, urgency by horizon |
| Which risk deserves attention now? | `risk` | urgency × impact, portfolio-weighted |
| Which catalyst is most consequential? | `catalyst` | impact × proximity |
| Which watchlist item should move up? | `watchlist_item` | attention × urgency |
| Which portfolio exposure has the largest expected effect? | `portfolio_exposure` | impact (exposure-weighted) |
| What deserves the user's attention today? | *all, ranked together* | `decision_rank_score` desc |

The sixth question is the product: a single cross-engine ranking. The first
five are filtered views of that same ranking.

### 4.2 Candidate assembly

`decision_candidate_builder` enumerates candidates from the substrate:

- **forecast** candidates from `forecast_vector` rows with material probability
  mass (Phase 12).
- **risk** candidates from `failure_mode` forecasts + risk-emergence thesis
  transitions (Phase 10A/12).
- **catalyst** candidates from catalyst-realization forecasts + dated catalysts
  in the dossier (Phase 12 / 9G).
- **watchlist_item** candidates from watched tickers with recent signals
  (Phase 10B).
- **portfolio_exposure** candidates from portfolio positions and insights
  (Phase 10D).
- **thesis_transition** candidates from recent thesis-version deltas (Phase 10A).
- **similarity_match** candidates from floor-passed similarity edges touching
  watched/held entities (Phase 11).

A candidate is **eligible** only if its `candidate_type`'s `entity_type` is in
`decision_targets_enabled` (empty allowlist ⇒ nothing eligible ⇒ inert).

---

## 5. Ranking framework

### 5.1 The five component scores

Each score is a bounded aggregate over weighted evidence contributions, each
contribution traceable to one upstream artifact (and recorded in
`decision_evidence`).

**attention_score** — intrinsic salience, independent of the holder.
Inputs: forecast materiality (probability shift magnitude, Phase 12),
similarity strength (edge weight, Phase 11), thesis-transition recency and
magnitude (Phase 10A), delivery-signal density (Phase 10C transitions).

**urgency_score** — time-sensitivity.
Inputs: forecast horizon (near_term ≫ long_term), catalyst proximity (days to
dated event), risk-emergence velocity (rate of probability change across
rebuilds), watchlist trigger recency.

**impact_score** — expected magnitude of effect. **Portfolio-aware (§7).**
Inputs: forecast probability mass on consequential outcomes (Phase 12),
portfolio exposure magnitude for this entity (Phase 10D), thesis centrality
(how load-bearing the affected thesis is).

**confidence_score** — reliability of the underlying signal.
Inputs: forecast confidence-band width (narrow ⇒ high, Phase 12), calibration
track record (Brier history for this forecast_type/horizon, Phase 12),
evidence density (count and independence of contributing sources).

**uncertainty_score** — internal disagreement / spread.
Inputs: forecast distribution entropy (Phase 12), conflicting evidence
directions (bullish vs bearish contributions on the same candidate),
calibration drift state (Phase 12 drift = worsening raises uncertainty).

`confidence_score` and `uncertainty_score` are **not** complements. A candidate
can be high-confidence and high-uncertainty (a reliably measured but genuinely
contested situation), or low on both (thin evidence, no disagreement because
there is nothing to disagree about). Both are surfaced; neither is derived from
the other.

### 5.2 Composite priority

```
raw = w_a·attention_score + w_u·urgency_score + w_i·impact_score
decision_rank_score = clamp01( raw · confidence_score · (1 − λ · uncertainty_score) )
```

- `w_a, w_u, w_i` are fixed weights per `candidate_type` (a risk weights
  urgency higher; a portfolio_exposure weights impact higher). The weight
  table is versioned under `decision_schema`.
- `confidence_score` acts as a **multiplier**: an unreliable signal is damped,
  never amplified. A candidate cannot rank high on weak evidence.
- `uncertainty_score` acts as a **discount** (λ ∈ [0,1], fixed per schema): a
  contested candidate is pulled down but not zeroed — contested-and-material is
  still worth attention.

This structure guarantees two properties the validation framework checks
(§10): **monotonicity** (raising any positive input never lowers the score,
holding others fixed) and **damping** (confidence/uncertainty can only reduce a
raw priority, never inflate it).

### 5.3 Bucketing

`decision_rank_score` maps to `decision_priority` by fixed thresholds:

```
≥ 0.80  critical
≥ 0.60  high
≥ 0.40  medium
≥ 0.20  low
<  0.20 informational
```

Thresholds are part of `decision_schema`; changing them bumps the schema
version and triggers a full re-rank (§8 invalidation).

### 5.4 Determinism

Given identical upstream artifacts and identical `decision_schema`, the engine
produces byte-identical scores. No randomness, no wall-clock term inside the
score (wall-clock enters only via `urgency_score` proximity inputs, which are
themselves derived from stored dated events, not `now()` directly — `now()` is
captured once per build and passed as an explicit parameter for testability,
mirroring the Phase 12 staleness pattern).

---

## 6. Explainability framework

Every priority must answer four questions or be **blocked** (never stored):

| Question | Field | Construction |
|---|---|---|
| Why is this important? | `decision_reason` | the dominant contributing dimension + its top evidence item |
| Why now? | `why_now` | the dominant `urgency_score` driver (horizon / proximity / velocity / recency) |
| What evidence supports it? | `evidence_summary` + `decision_evidence` rows | top-N weighted contributions across dimensions, each naming its source artifact |
| What would reduce its importance? | `deprioritizers` | named, falsifiable conditions whose occurrence would lower the score |

`deprioritizers` are the decision-layer analogue of Phase 12 `invalidators`:
concrete, checkable statements ("forecast confidence band widens past 0.4",
"position is closed", "catalyst date passes without event"). They make a
priority **falsifiable** — a reviewer can state what would change the ranking.

The blocking gate is hard: the builder validates explanation completeness
*before* `upsert_decision_priority`. A candidate whose evidence is too thin to
produce a non-empty reason, why-now, and at least one deprioritizer is dropped
with a logged `blocked_explanation` status. No partial priorities reach the
cache. This is the same discipline as Phase 12's `blocked_explanation` path.

Mandatory framing line: every decision surface (admin or, later, user-visible)
carries a verbatim disclaimer asserting that priorities order information and
are **not** investment advice or trade recommendations. The disclaimer is a
constant, emitted at the facet level and on every item, identical in mechanism
to Phase 12's `MANDATORY_DISCLAIMER`.

---

## 7. Portfolio-awareness framework

Decision priority **may vary by user**, and the variation flows through
exactly one channel: `impact_score`.

### 7.1 The exposure multiplier

`impact_score` is computed as:

```
impact_score = clamp01( intrinsic_impact · exposure_multiplier )
```

- `intrinsic_impact` is holder-independent (forecast magnitude × thesis
  centrality). This is what a **global / NULL-user** priority row carries.
- `exposure_multiplier` is the user-specific term, derived from Phase 10D
  portfolio exposure for this entity:
  - no exposure ⇒ multiplier at a floor (e.g. baseline 1.0, intrinsic only —
    the candidate is *not erased*, it simply isn't amplified);
  - material exposure ⇒ multiplier scales with position weight, capped.

A risk to NVDA therefore yields a **high** priority for a user holding NVDA and
a **lower** (but non-zero) priority for a user with no exposure — both from the
same intrinsic signal, differing only in the exposure multiplier. This is the
worked example in the requirements, realized through one well-defined term.

### 7.2 Two-tier materialization

- **Global tier** (`user_id = NULL`): intrinsic priorities, built once,
  shared. These answer "what is objectively significant" and back the
  unexposed baseline.
- **User tier** (`user_id = <uuid>`): exposure-adjusted priorities, built per
  user with portfolio context. Only built for users with a portfolio and only
  for entities they touch — keeping the user tier bounded.

A user's ranked set is the union of their user-tier rows and the global-tier
rows for entities they have *not* personalized, deduplicated by
`(candidate_type, entity_type, entity_key)` with the user-tier row winning.

### 7.3 Isolation invariant

A user-tier priority row is **never** readable under another user's scope. The
read service filters on `user_id` with the same identity-scoping discipline as
Phase 16. Cross-user leakage of a ranking is a blocking defect and is checked
explicitly in portfolio-awareness validation (§10).

### 7.4 No systemic-risk suppression

Exposure amplifies; it must not *suppress*. A systemic, high-intrinsic-impact
risk (market-wide regime transition) must remain visible to an unexposed user
because its intrinsic impact is high — the floor multiplier guarantees the
global-tier row survives. The risk register (§14) tracks "portfolio tunnel
vision" as an explicit failure mode; validation asserts that a high-intrinsic
global priority is never ranked below a low-intrinsic user-tier priority purely
because of exposure.

---

## 8. Calibration, drift, and invalidation

### 8.1 Ranking outcome attribution

`decision_calibration_service` (gated by `decision_calibration_enabled`)
appends a `decision_ranking_log` outcome row when a priority's subject resolves
— a forecast calibrates (Phase 12), a risk materializes or lapses, a catalyst
passes. `realized_significance` records whether the thing we ranked highly
turned out to be material.

This enables the key calibration question for a *prioritization* engine: **did
high-priority items turn out to matter more than low-priority items?** Measured
as rank-order agreement (e.g. concordance between `decision_rank_score` and
realized significance) over a rolling window. This is the decision-layer
analogue of the Brier score: not "was the probability right" but "was the
ordering right."

### 8.2 Drift / stability

Two drift signals, both computed over the immutable log:

- **Calibration drift** — is rank-order agreement worsening, improving, or
  stable across consecutive windows? (Same windowed-comparison shape as Phase
  12 drift, with `insufficient_samples` below a minimum.)
- **Ranking stability (churn)** — how much do `rank_position` values move
  between consecutive snapshots for unchanged underlying artifacts? High churn
  with static inputs indicates an unstable scoring formula (flicker), which is
  a UX hazard for a prioritization layer and a blocking concern before delivery
  is enabled.

No automatic remediation. Drift is reported; weight/threshold changes are
human decisions that bump `decision_schema`.

### 8.3 Invalidation and re-rank

`decision_invalidation_service` marks a priority stale when any
`source_versions` entry is behind the current upstream row version, when
`expires_at` passes, or when `decision_schema` changes. Stale priorities are
rebuilt by the builder; reads never trigger a rebuild (read/write separation,
same as Phase 12 read service).

---

## 9. Delivery framework

### 9.1 Consumption surfaces

Once validated and `decision_delivery_enabled`, the ranking becomes the
ordering/prominence layer for:

- **inbox** — notification ordering by `decision_rank_score`
- **alerts** — promotion of `critical`/`high` candidates
- **briefings** — lead-item selection and section ordering
- **watchlist** — top-of-list ordering
- **portfolio intelligence** — exposure-ranked attention

The ranking determines **order and prominence only**. It never changes the
*content* of a surface item, never adds an item a surface would not otherwise
show, and never emits a new advice-bearing field.

### 9.2 Shadow journaling

Before delivery is enabled, `decision_ranking_service` writes the ranking it
*would* apply to `decision_ranking_log` (channel-style, append-only) and to
nothing else. No surface reads it. This is the exact shadow mechanism Phases 11
and 12 used for delivery transitions — a journaled, inert artifact that proves
the layer works without exposing it.

### 9.3 What is not built in Phase 13

- No new notification *types* (Phase 13 reorders existing ones).
- No new delivery channels.
- No trade, order, or execution surface — ever.
- No write-back to forecast/similarity/memory.

---

## 10. Validation framework

Five validation classes, each a hard gate before the next rollout stage.

### 10.1 Ranking validation

- **Determinism** — identical inputs + schema ⇒ identical scores and order.
- **Monotonicity** — raising any single positive input (attention/urgency/
  intrinsic-impact) never lowers `decision_rank_score`, others fixed.
- **Damping** — `confidence_score` and `uncertainty_score` can only reduce a
  raw priority, never inflate it.
- **Bucket consistency** — `decision_priority` always matches the
  `decision_rank_score` threshold (§5.3).
- **Bounded churn** — with static upstream artifacts, snapshot-to-snapshot
  `rank_position` movement stays within a defined bound.

### 10.2 Explainability validation

- Every stored priority has non-empty `decision_reason`, `why_now`, and a
  non-empty `deprioritizers` list, plus ≥1 `evidence_summary` item.
- Every `decision_evidence` row names a real upstream `source_id` of the
  declared `source_type`.
- A candidate with insufficient evidence is **blocked**, not stored with empty
  fields (assert the `blocked_explanation` path fires).

### 10.3 Drift validation

- Rank-order agreement computable over the log; drift classified
  `improving` / `worsening` / `stable` / `insufficient_samples`.
- Churn metric computable and within bound on a static-input fixture.
- `decision_ranking_log` is append-only: AST check that `add_ranking_log`
  has no update/delete/merge, and no service updates an existing log row.

### 10.4 Portfolio-awareness validation

- The **same** candidate ranks higher for an exposed user than for an
  unexposed user (exposure multiplier works).
- A high-intrinsic global priority is **never** suppressed below a
  low-intrinsic user-tier priority by exposure alone (no tunnel vision).
- A user-tier priority is **never** readable under a different `user_id`
  (isolation).
- Unexposed user falls back to global-tier rows correctly (union/dedup).

### 10.5 No-advice validation

- AST + string scan over all decision_* modules: no `buy` / `sell` / `hold` /
  `overweight` / `underweight` / `target price` / `position size` /
  `recommend` / `trade` language in any non-docstring, non-data string.
- Schema check: no column in tables 44–46 can hold an advice, size, price, or
  trade value (structural — there is no such field).
- Disclaimer present verbatim on every facet and item.
- Import-graph check: no decision_* module imports any order/execution/
  conviction/stance module (SP-5, §13).
- No public (non-`/admin/`) route exposes any decision_* path until §11 stage 4.

### 10.6 Validation script

`tests/validate_13_decision_intelligence_shadow.py` — same shape as
`validate_12_forecasting_shadow.py`: importability of all decision_* services,
all six flags at inert defaults, import-graph hygiene, no-advice string
hygiene (with infrastructure/data modules skipped), route exposure, log
immutability, `db_table_count ≥ 46`, tables 44–46 exist, `safe_state == true`
on DB-down and DB-up, no source-table mutation during the probe, no
ranking escalated to a live surface, explainability + ranking + portfolio
invariants on whatever rows exist. **Exit 0 on full pass.**

---

## 11. Rollout strategy

Shadow-first. No user-visible prioritization until validated. Flag semantics
identical to Phase 12 so the runbook carries over.

### Stage 0 — Shadow validation (initial deploy state)
All flags inert (`*_enabled = False`, `decision_shadow = True`,
`decision_targets_enabled = ""`). `validate_13_*` exits 0;
`/admin/decision-status` returns `safe_state: true`. No user-visible change.

### Stage 1 — Build + scoring (internal only)
Prereq: Stage 0 green; ≥ 2 weeks of Phase 12 forecast + calibration data.
```
decision_build_enabled=true
decision_scoring_enabled=true
decision_targets_enabled=company
```
Global-tier priorities build. Monitor `priority_count`, score distributions,
explainability block-rate. No delivery. Acceptance: `priority_count > 0`,
`safe_state: true`, block-rate within expected range.

### Stage 2 — Shadow ranking + calibration
Prereq: Stage 1 green; ≥ 50 priorities built.
```
decision_calibration_enabled=true
```
`decision_ranking_service` journals shadow rankings; calibration begins
attributing outcomes. Monitor rank-order agreement, churn, drift trend.
Acceptance: churn within bound; drift `stable`/`improving`;
`shadow_escalated_count == 0`.

### Stage 3 — Portfolio (user-tier) shadow
Prereq: Stage 2 green; portfolio data present.
```
decision_targets_enabled=company,portfolio
```
User-tier priorities build for users with portfolios. Portfolio-awareness
validation must pass against live shadow data (exposure lift present, no tunnel
vision, isolation holds). Still no user-visible change.

### Stage 4 — Delivery (user-visible) — **separate sign-off**
Prereq: Stages 0–3 green; explicit acceptance criteria (§16) met; human
sign-off.
```
decision_delivery_enabled=true
```
Rankings begin ordering real surfaces. Roll out behind a per-surface or
per-cohort gate (inbox first, then alerts/briefings/watchlist/portfolio), each
reversible independently.

### Rollback
Set all `decision_*` flags to inert defaults; restart. Surfaces revert to their
prior local ordering immediately (the ranking layer is additive, not
destructive). Tables retain data; no loss from a flag rollback. To purge:
`DELETE FROM decision_priority;` (evidence is soft-FK; ranking log is immutable
history and is retained for audit).

---

## 12. Admin routes

```
GET /admin/decision-status        observability snapshot (flags, counts,
                                  drift/churn summary, safe_state)
GET /admin/decision/{ticker}      read-only facet for one entity (global tier),
                                  disclaimer-wrapped, no advice fields
GET /admin/decisions              read-only ranked set for a given user_id
                                  (query param), identity-scoped
```

All `/admin/`-only. No public route. Read-only; never builds or re-ranks. All
DB-down-safe via the null-session pattern. `safe_state` is true when
`decision_delivery_enabled = False` AND `decision_shadow = True` AND no ranking
has escalated to a live surface AND no advice-bearing field is present.

---

## 13. Security and safety constraints

### SP-5 — no decision → action pipeline (extends SP-4)

SP-4 forbade forecast output from influencing conviction/stance/verdict/LLM
prompts. **SP-5 extends this to the decision layer:**

- Decision output must **never** initiate, recommend, size, or describe a
  trade.
- No decision_* module may import any order-management, execution, conviction,
  stance, or brokerage module. (AST import-graph check.)
- Decision output must **never** flow back into forecasts, similarity, memory,
  or calibration. Phase 13 is a pure sink (§1.3).
- Decision priority must not appear in any LLM prompt that generates analysis,
  thesis, or conviction text — ranking is a post-analysis ordering concern, not
  an input to analysis.

### No-advice boundary (structural)

No column in tables 44–46 can represent advice, position size, target price, or
a trade instruction. There is no delivery path that emits such a field.
Enforced at schema review and by no-advice validation (§10.5).

### No credential / secret leakage

The observability snapshot and all admin facets emit only booleans, strings,
counts, and bounded scores — never raw upstream payloads, prompt text, model
output, or any secret. Same discipline as the Phase 11/12 observability
services.

### Identity isolation

User-tier rows are strictly scoped by `user_id`. No cross-user read. The
`SYSTEM_DEFAULT_USER_ID` baseline is global-tier only and cannot carry
portfolio exposure.

---

## 14. Risks and mitigations

| Risk | Description | Mitigation |
|---|---|---|
| Ranking flicker | Small input changes reorder the list jarringly | Churn metric + bounded-churn validation gate before delivery; hysteresis in bucketing (schema-versioned) |
| Portfolio tunnel vision | Exposure amplification buries systemic risks for unexposed users | Floor multiplier keeps intrinsic priorities alive; explicit no-suppression validation (§10.4) |
| Calibration cold-start | No outcome history ⇒ confidence term untrained | `insufficient_samples` state; confidence falls back to forecast-band width until calibration matures (Phase 12 cold-start pattern) |
| Attention monoculture | Same few names always rank top; genuine novelty buried | Track candidate-type and entity diversity in observability; novelty/recency contributes to attention_score |
| Explainability gaming | Formula tuned to pass the gate, not to be meaningful | Deprioritizers must be falsifiable and checked against real upstream conditions; human review of block-rate and reason quality at Stage 1 |
| Upstream contamination | Decision output silently feeds back into forecasts | SP-5 import-graph check is a blocking defect; Phase 13 is a pure sink by construction |
| Feedback loop via delivery | Surfacing an item changes user behavior, which changes signal, which changes ranking | Delivery is a late, separately-gated, per-surface reversible stage; ranking does not consume its own delivery effects |
| User-scope leakage | One user sees another's portfolio-adjusted ranking | Identity-scoping isolation invariant + explicit validation; same discipline as Phase 16 |
| Weight opacity | Composite weights are a hidden policy | Weights versioned under `decision_schema`; every change bumps the version and triggers full re-rank + fresh calibration window |

---

## 15. Dependency map

```
                 ┌─────────────────────────────────────────┐
   Phase 9G ─────┤ historical memory, analog history        │
   Phase 10A ────┤ thesis evolution, delivery transitions    │
   Phase 10B ────┤ watchlist signals                         │
   Phase 10C ────┤ delivery / briefing transitions           │ ──► decision_candidate_builder
   Phase 10D ────┤ portfolio exposure, portfolio insights    │ ──► decision_scoring_engine
   Phase 11 ─────┤ similarity matches                        │ ──► decision_explainability_service
   Phase 12 ─────┤ forecasts, calibration signals            │
                 └─────────────────────────────────────────┘
                                  │ (imports one-directional)
                                  ▼
                        decision_priority (44)
                        decision_evidence (45)
                        decision_ranking_log (46)
                                  │
                                  ▼ (shadow until Stage 4)
                 inbox · alerts · briefings · watchlist · portfolio
```

One-directional, top-to-bottom. No arrow ever points back up (SP-5).

---

## 16. Acceptance criteria for any Phase 13 live delivery (Stage 4)

- [ ] `validate_13_decision_intelligence_shadow.py` exits 0 in production.
- [ ] `/admin/decision-status` returns `safe_state: true`.
- [ ] All decision_* unit + invariant test suites pass.
- [ ] `priority_count > 0` after Stage 1 for 24h+; explainability block-rate
      within expected band.
- [ ] Ranking stability: churn within bound over 7+ days of shadow snapshots.
- [ ] Calibration: rank-order agreement above a defined floor; drift
      `stable`/`improving` over the most recent window.
- [ ] Portfolio-awareness: exposure lift demonstrated, no tunnel-vision
      suppression, isolation holds — all against live shadow data.
- [ ] No advice/size/price/trade field anywhere in any response (non-`/admin/`
      and `/admin/`).
- [ ] SP-5 import-graph check green: no decision_* → order/execution/conviction
      import; no upstream write-back.
- [ ] Human sign-off on reason quality and the per-surface delivery gate plan.

---

## 17. Slice plan

A suggested decomposition mirroring the Phase 12 slice cadence. Each slice
ships its own tests; no slice enables a flag.

1. **Schema** — tables 44–46, migration 013, model invariants, schema tests.
2. **Repository** — `decision_repo` (priorities, evidence, immutable log),
   insert-only `add_ranking_log`, repo tests.
3. **Candidate builder** — substrate enumeration + eligibility filter.
4. **Scoring engine** — five component scores + composite + bucketing,
   determinism/monotonicity/damping tests.
5. **Explainability** — reason/why-now/evidence/deprioritizers + blocking gate.
6. **Invalidation + rebuild orchestration** — staleness, re-rank, read/write
   separation.
7. **Read service + internal facets** — `/admin/decision/{ticker}`,
   `/admin/decisions`, disclaimer wrapping.
8. **Portfolio-awareness** — exposure multiplier, two-tier materialization,
   isolation, no-suppression.
9. **Shadow ranking delivery** — journal-only `decision_ranking_service`,
   `decision_ranking_log`, no surface reads.
10. **Calibration + drift** — outcome attribution, rank-order agreement, churn,
    drift classification.
11. **Observability + validation + rollout docs** —
    `decision_observability_service`, `/admin/decision-status`,
    `validate_13_decision_intelligence_shadow.py`,
    `PHASE_13_DECISION_INTELLIGENCE_SHADOW_ROLLOUT.md`.

Phase 13 ends at the close of Slice 11, fully observable, in confirmed shadow
mode, with the Stage-4 delivery gate (§16) deferred to an explicit,
human-signed-off decision. **Live delivery is out of scope for the build
phase.**
