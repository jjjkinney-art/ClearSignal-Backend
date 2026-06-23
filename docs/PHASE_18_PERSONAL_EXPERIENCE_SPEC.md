# Phase 18 — Personal Experience Layer

## Status

Architecture specification. No implementation.

---

## Problem

ClearSignal can answer six foundational questions:

1. **What happened?** — Memory, ticker analysis, evidence pipeline
2. **What resembles this?** — Similarity Engine (Phase 11)
3. **What tends to happen next?** — Forecasting Engine (Phase 12)
4. **What matters most?** — Decision Intelligence (Phase 13)
5. **What happens if X changes?** — Scenario Engine (Phase 14)
6. **What have I learned about this user?** — User Learning (Phase 15)

The intelligence exists. The experience does not yet feel personal.

Today every user sees largely the same product. Watchlist order is static.
Feed ranking is alphabetical or chronological. The system knows what matters
to each user (Phase 15) but does not act on that knowledge. A user who
tracks 40 tickers gets the same flat list whether their top holding just
reported earnings or a peripheral watchlist item had a trivial price move.

---

## Goal

Transform ClearSignal from:

> "Analyze a company."

into:

> "Show me what matters to me."

---

## Core Principle

**Phase 18 does not create intelligence. Phase 18 orchestrates intelligence.**

It consumes the output of every upstream phase and determines:

- What appears first
- What appears second
- What deserves attention right now
- What can wait
- What should be surfaced proactively

Phase 18 never writes to any truth table. It reads evidence, scores,
forecasts, decisions, scenarios, preferences, and portfolio state — then
produces an ordering and a set of attention signals. The intelligence is
upstream. The experience is Phase 18.

---

## Upstream Dependencies

| Phase | What Phase 18 Reads | Table / Service |
|---|---|---|
| 9G | Ticker memory, dossier state | `ticker_memory`, `memory_entries` |
| 10A | Loop execution, scheduled jobs | `scheduled_job`, loop status |
| 10B | Watchlist state, thesis snapshots | `watched_ticker`, thesis snapshots |
| 10C | Delivery ledger, notification state | `delivery_ledger`, `notifications` |
| 10D | Portfolio positions, insights | `portfolios`, `portfolio_positions`, `portfolio_insights` |
| 11 | Similarity edges, feature vectors | `similarity_edge`, `similarity_feature_vector` |
| 12 | Forecast vectors, evidence, calibration | `forecast_vector`, `forecast_evidence`, `forecast_calibration_log` |
| 13 | Decision priorities, evidence, ranking | `decision_priority`, `decision_evidence`, `decision_ranking_log` |
| 14 | Scenario snapshots, evidence, run logs | `scenario_snapshot`, `scenario_evidence`, `scenario_run_log` |
| 15 | Learned preferences, signal events, relevance log | `learned_preference`, `user_signal_event`, `relevance_adjustment_log` |
| 16 | User identity, profile, settings | `users`, `user_profiles`, `user_settings` |
| 17 | Subscription tier, entitlements | `subscriptions`, `entitlement_cache` |

Phase 18 writes to its own tables only (defined below). It never writes to
any table listed above.

---

## Personal Experience Questions

The layer must answer, per user:

| Question | Primary Inputs |
|---|---|
| What changed since my last visit? | Memory diff, forecast diff, scenario diff, thesis diff |
| What deserves my attention now? | Decision priority, scenario plausibility shift, forecast drift |
| Which watchlist item moved most? | Forecast vector delta, thesis snapshot diff |
| Which scenario changed? | Scenario snapshot comparison, invalidation events |
| Which forecast changed? | Forecast vector delta, calibration events |
| Which thesis changed? | Memory entry diff, evidence freshness |
| What did I previously care about? | User signal events, learned preferences |
| What is most relevant to me today? | Relevance projection (Phase 15), portfolio overlap, recency |

---

## Architecture

### Layer Diagram

```
┌─────────────────────────────────────────────────────────┐
│                    Frontend / API                        │
│         GET /home   GET /brief   GET /attention          │
└──────────────────────┬──────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────┐
│              PHASE 18 — Personal Experience              │
│                                                          │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐   │
│  │  Experience   │  │  Attention   │  │  Personal    │   │
│  │  Composer     │  │  Scorer      │  │  Brief       │   │
│  │              │  │              │  │  Builder     │   │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘   │
│         │                 │                 │            │
│  ┌──────▼─────────────────▼─────────────────▼────────┐  │
│  │              Personalization Engine                 │  │
│  │    Reads Phase 15 relevance projections            │  │
│  │    Applies attention_priority + personal_relevance │  │
│  │    Enforces explainability gate                    │  │
│  └──────────────────────┬────────────────────────────┘  │
│                         │                                │
│  ┌──────────────────────▼────────────────────────────┐  │
│  │              Change Detection Engine               │  │
│  │    Diffs forecasts, scenarios, theses, memory      │  │
│  │    Computes recency_score + novelty_score          │  │
│  │    Tracks last_seen_at per user per entity         │  │
│  └──────────────────────┬────────────────────────────┘  │
│                         │                                │
└─────────────────────────┼────────────────────────────────┘
                          │  reads only
┌─────────────────────────▼────────────────────────────────┐
│  Phase 9G  │ 10A-D │ 11 │ 12 │ 13 │ 14 │ 15 │ 16 │ 17  │
│  Memory    │ Loop  │Sim │Fore│Dec │Scen│Learn│Auth│Bill  │
└──────────────────────────────────────────────────────────┘
```

### Service Decomposition

| Service | Responsibility |
|---|---|
| `experience_composer_service` | Top-level orchestrator. Calls all sub-services, merges results, produces final ranked experience payload. |
| `attention_scorer_service` | Scores every candidate item on 6 dimensions (below). Pure computation, no writes. |
| `change_detection_service` | Detects what changed since a user's last visit. Compares current state to `personal_experience_cursor` timestamps. |
| `personal_brief_builder_service` | Compiles a structured daily brief from scored + filtered items. |
| `experience_explainability_service` | Generates the "why am I seeing this?" explanation for every surfaced item. Blocks items that fail the explainability gate. |
| `personal_experience_observability_service` | Observability snapshot, admin status endpoint, safe_state checks. |

---

## Scoring Dimensions

Every candidate item receives six scores. All scores are floats in [0.0, 1.0].

| Dimension | Definition | Primary Source |
|---|---|---|
| `attention_priority` | How urgently this item demands the user's attention. Earnings beats, credit downgrades, and scenario invalidations score high. Routine mention events score low. | Decision Intelligence (Phase 13) priority ranking |
| `personal_relevance` | How much this item aligns with the user's learned preferences, portfolio, and history. | User Learning (Phase 15) relevance projection |
| `recency_score` | How recently the underlying evidence changed. Exponential decay from the most recent change timestamp. | Change Detection (forecast delta, memory diff, scenario change) |
| `novelty_score` | How new this information is to this specific user. Items the user has already seen score low. Items the user has never encountered score high. | `personal_experience_cursor.last_seen_at` vs item timestamp |
| `revisit_score` | How much an item the user previously engaged with has changed since they last looked. High when a previously-researched thesis has materially shifted. | User signal history (Phase 15) × forecast/scenario delta |
| `memory_relevance` | How strongly this item connects to the user's research history — previously analyzed companies, saved theses, revisited tickers. | Ticker memory, memory entries, watchlist interaction history |
| `portfolio_relevance` | How directly this item affects the user's portfolio positions. Items affecting large positions or concentrated holdings score higher. | Portfolio positions (Phase 10D), portfolio insights |

### Composite Score

```
experience_score = (
    w_attention  × attention_priority
  + w_relevance  × personal_relevance
  + w_recency    × recency_score
  + w_novelty    × novelty_score
  + w_revisit    × revisit_score
  + w_memory     × memory_relevance
  + w_portfolio  × portfolio_relevance
)
```

Default weights (tunable per user tier, never per individual user):

```
w_attention  = 0.25
w_relevance  = 0.20
w_recency    = 0.15
w_novelty    = 0.10
w_revisit    = 0.10
w_memory     = 0.10
w_portfolio  = 0.10
```

Weights sum to 1.0. Adjustments are constrained: no single weight may exceed
0.40, and no weight may be reduced below 0.05. This prevents degenerate
configurations where a single dimension dominates the experience.

---

## Data Model

### New Tables

#### `personal_experience_cursor`

Tracks each user's last-seen state per entity, enabling novelty and revisit scoring.

| Column | Type | Description |
|---|---|---|
| `id` | UUID | Primary key |
| `user_id` | UUID | FK → users |
| `entity_type` | VARCHAR(30) | "ticker", "scenario", "forecast", "thesis" |
| `entity_key` | VARCHAR(64) | Ticker symbol, scenario ID, forecast ID |
| `last_seen_at` | TIMESTAMP | When the user last viewed this entity |
| `last_state_hash` | VARCHAR(64) | Hash of the entity state when last seen (for drift detection) |
| `view_count` | INTEGER | Lifetime view count for this entity |
| `created_at` | TIMESTAMP | Row creation time |
| `updated_at` | TIMESTAMP | Last update time |

Unique constraint: `(user_id, entity_type, entity_key)`.

#### `personal_experience_event`

Append-only log of what was surfaced and why. Enables calibration and audit.

| Column | Type | Description |
|---|---|---|
| `id` | UUID | Primary key |
| `user_id` | UUID | FK → users |
| `surface` | VARCHAR(30) | "home", "brief", "attention_queue" |
| `item_ref` | VARCHAR(128) | Entity reference surfaced |
| `entity_type` | VARCHAR(30) | Type of entity |
| `entity_key` | VARCHAR(64) | Entity key |
| `experience_score` | FLOAT | Composite score at time of surfacing |
| `attention_priority` | FLOAT | Score dimension |
| `personal_relevance` | FLOAT | Score dimension |
| `recency_score` | FLOAT | Score dimension |
| `novelty_score` | FLOAT | Score dimension |
| `revisit_score` | FLOAT | Score dimension |
| `memory_relevance` | FLOAT | Score dimension |
| `portfolio_relevance` | FLOAT | Score dimension |
| `explanation_text` | TEXT | "Why am I seeing this?" explanation |
| `explanation_valid` | BOOLEAN | True if passed explainability gate |
| `run_reason` | VARCHAR(15) | "shadow" until live rollout |
| `surfaced_at` | TIMESTAMP | When the item was surfaced |
| `created_at` | TIMESTAMP | Row creation time |

Append-only: INSERT only. No UPDATE. No DELETE.

#### `personal_brief_snapshot`

Stores generated brief content for retrieval and audit.

| Column | Type | Description |
|---|---|---|
| `id` | UUID | Primary key |
| `user_id` | UUID | FK → users |
| `brief_date` | DATE | The date this brief covers |
| `brief_schema` | INTEGER | Schema version (starts at 1) |
| `items_surfaced` | INTEGER | Number of items included |
| `items_blocked` | INTEGER | Number of items that failed explainability |
| `top_attention_item` | VARCHAR(128) | Highest-priority item reference |
| `run_reason` | VARCHAR(15) | "shadow" until live rollout |
| `generated_at` | TIMESTAMP | When the brief was generated |
| `created_at` | TIMESTAMP | Row creation time |

One brief per user per day (unique on `user_id, brief_date`).

---

## Personalization Framework

### Input Assembly

For a given user + surface (home, brief, attention queue):

1. **Watchlist items**: all `watched_ticker` rows for the user
2. **Portfolio items**: all `portfolio_positions` for the user's portfolios
3. **Recent research**: entities from `user_signal_event` within 30 days
4. **Active scenarios**: non-expired `scenario_snapshot` rows for watched/portfolio tickers
5. **Active forecasts**: non-expired `forecast_vector` rows for watched/portfolio tickers
6. **Decision priorities**: `decision_priority` rows for the user's tickers

This produces a candidate set. Every item in the candidate set is scored,
explained, and ranked.

### Scoring Pipeline

```
candidates = assemble_candidates(user_id)
    → list of (entity_type, entity_key, raw_data)

for each candidate:
    scores = attention_scorer.score(candidate, user_context)
        → {attention_priority, personal_relevance, recency_score,
           novelty_score, revisit_score, memory_relevance, portfolio_relevance}
    
    composite = weighted_sum(scores, weights)
    
    explanation = explainability.explain(candidate, scores)
        → {text: str, valid: bool, evidence: list}
    
    if not explanation.valid:
        block(candidate)  # unexplainable items never surface
        continue
    
    ranked_items.append((candidate, composite, scores, explanation))

ranked_items.sort(key=composite, reverse=True)
```

### Novelty Reserve

Inherited from Phase 15 (SP-7d anti-filter-bubble):

- 15% of top-ranked slots are reserved for items with no matching preference
- This prevents the experience from becoming an echo chamber
- Novelty reserve items must still pass the explainability gate

### Attention Floor

Items with `attention_priority > 0.8` are never ranked below position 5,
regardless of other scores. This ensures that genuinely urgent events
(earnings misses, credit downgrades, regulatory actions) are always visible.

---

## Home Experience

The home surface presents a personalized, ranked view of the user's
intelligence landscape.

### Sections

| Section | Content | Source |
|---|---|---|
| **Most Important Change** | Single highest-scored item with full explanation. The one thing the user should know right now. | Top-1 from composite ranking |
| **Attention Queue** | 3–5 items requiring attention, with brief explanations. Filtered by `attention_priority > 0.5`. | Top-N from ranking, attention-filtered |
| **Watchlist Drift** | Which watchlist items have changed most since the user's last visit. Sorted by `novelty_score × recency_score`. | Change detection on watched tickers |
| **Thesis Changes** | Watchlist items whose thesis (memory state) has materially changed. | Memory entry diff vs `personal_experience_cursor.last_state_hash` |
| **Scenario Changes** | Scenarios that shifted in plausibility or were invalidated. | Scenario snapshot comparison |
| **Forecast Changes** | Forecasts that drifted beyond a materiality gate since last seen. | Forecast vector delta |
| **Revisit Suggestions** | Previously researched items that have changed since the user last looked. Sorted by `revisit_score`. | User signal history × entity change |

Each section is independently populated and ranked. Sections with no
qualifying items are omitted (not shown empty).

---

## Personal Brief

A daily structured summary generated per user.

### Brief Structure

```
{
  "brief_date":    "2026-06-20",
  "user_id":       "...",
  "what_changed":  [
    {
      "entity":      "AAPL",
      "change_type": "forecast_drift",
      "summary":     "Revenue forecast confidence dropped 12% after Q3 miss.",
      "scores":      { ... },
      "explanation": "You watch AAPL and it is your largest portfolio position."
    }
  ],
  "why_it_matters": [
    {
      "entity":      "NVDA",
      "reason":      "Scenario 'AI capex slowdown' plausibility increased to 72%.",
      "explanation": "NVDA is in your portfolio and is correlated with your MSFT position."
    }
  ],
  "deserves_attention": [
    { ... items with attention_priority > 0.7 ... }
  ],
  "can_be_ignored": [
    { ... items with experience_score < 0.2 and no material change ... }
  ],
  "meta": {
    "items_evaluated":  42,
    "items_surfaced":   8,
    "items_blocked":    2,
    "run_reason":       "shadow",
    "generated_at":     "2026-06-20T06:00:00Z"
  }
}
```

### Brief Generation Rules

- Generated once per day per user (idempotent on `user_id + brief_date`)
- Only items that pass the explainability gate appear in the brief
- "Can be ignored" section only appears when the user has > 20 tracked items
  (avoids implying dismissal of a small watchlist)
- No LLM-generated prose in the brief itself — all text is templated from
  structured fields. This eliminates prompt injection risk and ensures
  deterministic, auditable output.

---

## Personal Memory

The experience layer tracks what the user has previously engaged with:

| Signal | Source | Use |
|---|---|---|
| Previously researched | `user_signal_event` where `signal_type = "research"` | Boosts `memory_relevance` for entities the user has studied |
| Previously watched | `watched_ticker` add/remove history | Detects re-interest in removed watchlist items |
| Previously analyzed | Analysis request history (audit_log) | Identifies companies the user has explicitly asked about |
| Previous thesis states | `personal_experience_cursor.last_state_hash` | Enables "what changed since you last looked" |

Phase 18 does not write to `user_signal_event` or `learned_preference`.
It only reads those tables. Personal memory tracking is limited to the
`personal_experience_cursor` table (defined above).

---

## Personal Ranking

Ranking is driven by three upstream systems in combination:

| System | Contribution |
|---|---|
| **Decision Intelligence (Phase 13)** | Provides `attention_priority` — what objectively demands attention based on evidence quality, urgency, and information significance |
| **User Learning (Phase 15)** | Provides `personal_relevance` — what subjectively matters to this user based on learned preferences, interaction history, and affinity signals |
| **Portfolio Context (Phase 10D)** | Provides `portfolio_relevance` — what affects the user's actual holdings, weighted by position size and concentration |

No single system dominates. The composite score blends all three, constrained
by the weight bounds defined in the Scoring Dimensions section.

---

## No-Advice Boundary (SP-18)

Phase 18 inherits and extends the SP-7 boundary from Phase 15:

### SP-18a: No investment guidance

Phase 18 must not:

- Recommend buying any security
- Recommend selling any security
- Recommend position sizing
- Recommend trade execution
- Recommend timing of entry or exit
- Use the words: buy, sell, hold, overweight, underweight, recommend,
  target price, position size, take a position, enter a trade, exit a trade,
  place an order, execute, short, long position, go long, go short,
  open a position, close a position

### SP-18b: Ordering is not advice

Personalization changes the ordering of items. It does not change the truth
of any item. A forecast vector is the same forecast vector regardless of
where it appears in the ranking. A scenario snapshot has the same plausibility
regardless of whether it is surfaced first or tenth.

**Ordering is presentation. It is not recommendation.**

### SP-18c: No truth mutation

Phase 18 writes only to:
- `personal_experience_cursor` (user view state)
- `personal_experience_event` (append-only surfacing log)
- `personal_brief_snapshot` (daily brief metadata)

Phase 18 never writes to:
- `forecast_vector`, `forecast_evidence`, `forecast_calibration_log`
- `similarity_edge`, `similarity_feature_vector`
- `scenario_snapshot`, `scenario_evidence`, `scenario_run_log`
- `decision_priority`, `decision_evidence`, `decision_ranking_log`
- `learned_preference`, `user_signal_event`, `relevance_adjustment_log`
- `ticker_memory`, `memory_entries`
- `delivery_ledger`, `notifications`
- `portfolios`, `portfolio_positions`, `portfolio_insights`

### SP-18d: No upstream feedback

Phase 18 output does not flow back into any upstream engine:
- Experience scores do not influence forecast confidence
- Attention priority does not change decision rankings
- Personal relevance does not modify similarity edges
- Brief content does not alter scenario plausibility
- No Phase 18 output is used as input to any Phase 11–15 service

---

## Explainability Framework

### Explainability Gate

Every item surfaced to a user must have a valid explanation. An explanation
is valid when it answers all four questions:

1. **Why am I seeing this?** — The reason this item was selected
2. **Why now?** — What changed to trigger surfacing at this time
3. **What changed?** — The specific delta from previous state
4. **What evidence supports it?** — At least one concrete evidence reference

If any of these four fields is empty, null, or fails validation, the item
is blocked from surfacing. Blocked items are logged to `personal_experience_event`
with `explanation_valid = false` for calibration.

### Explanation Structure

```
{
  "why_seeing":     "AAPL is on your watchlist and is your largest portfolio position.",
  "why_now":        "Revenue forecast confidence changed by 12% since your last visit.",
  "what_changed":   "Forecast drift: Q4 revenue estimate dropped from $94B to $89B.",
  "evidence":       [
    {"type": "forecast_vector", "id": "fv_abc123", "field": "confidence_score"},
    {"type": "user_signal_event", "id": "use_def456", "signal_type": "research"}
  ],
  "valid":          true
}
```

### Explanation Templates

Explanations are generated from templates, not LLM prose:

| Trigger | Template Pattern |
|---|---|
| Watchlist item changed | "{entity} is on your watchlist. {what_changed}." |
| Portfolio holding changed | "{entity} is in your portfolio ({position_pct}%). {what_changed}." |
| Previously researched | "You previously researched {entity}. {what_changed} since your last analysis." |
| Scenario shift | "Scenario '{scenario_name}' for {entity} changed plausibility from {old}% to {new}%." |
| Forecast drift | "Forecast for {entity} {field} changed by {delta} since {last_seen}." |
| Preference match | "Based on your interest in {dimension}: {entity_key}. {what_changed}." |

Templates ensure determinism, auditability, and freedom from prompt injection.

---

## Validation Framework

### Personalization Validation

Verifies that personalization functions correctly without introducing bias:

- **Rank stability**: given identical inputs, the same user sees the same ranking
- **Weight bounds**: no composite weight exceeds 0.40 or drops below 0.05
- **Novelty reserve**: at least 15% of top slots go to non-preference items
- **Attention floor**: items with `attention_priority > 0.8` appear in top 5
- **User isolation**: user A's preferences do not leak into user B's ranking

### Explainability Validation

Verifies that every surfaced item has a valid, complete explanation:

- **Completeness**: all four explanation fields are non-empty
- **Accuracy**: `evidence` references exist in the source tables
- **Determinism**: same inputs produce the same explanation text
- **No LLM prose**: explanation text matches a known template pattern
- **Block rate**: items failing the gate are logged but never surfaced

### Drift Validation

Verifies that the change detection system accurately identifies material changes:

- **True positive rate**: material changes are detected (no missed earnings events)
- **Materiality gate**: trivial changes (< 2% forecast drift) are filtered out
- **Staleness check**: `personal_experience_cursor` timestamps are current
- **Hash consistency**: `last_state_hash` matches the actual entity state

### No-Advice Validation

Verifies SP-18a compliance across all Phase 18 services:

- **AST scan**: no banned phrases in non-docstring string constants
- **Import audit**: no conviction, order, execution, stance imports
- **Template audit**: no template produces advisory language
- **Write audit**: Phase 18 writes only to its own three tables
- **Feedback audit**: no Phase 18 output feeds back into Phases 11–15

### Ordering Validation

Verifies that personalization changes ordering only, never truth:

- **Read-only audit**: Phase 18 services have no write-path to upstream tables
- **Idempotency**: running the scoring pipeline twice produces the same ranking
- **Score range**: all dimension scores are in [0.0, 1.0]
- **Composite range**: composite score is in [0.0, 1.0]
- **No side effects**: calling `experience_composer.compose()` creates no
  upstream table mutations (verified by row-count before/after)

---

## Rollout Strategy

### Shadow-First

Phase 18 follows the same shadow-first pattern as all prior phases:

```
EXPERIENCE_COMPOSER_ENABLED = false    # Top-level gate
EXPERIENCE_SHADOW = true               # All output goes to log only
EXPERIENCE_BRIEF_ENABLED = false       # Brief generation off
EXPERIENCE_ATTENTION_ENABLED = false   # Attention scoring off
EXPERIENCE_TARGETS_ENABLED = ""        # No downstream consumers
```

### Rollout Stages

| Stage | Flags | What Happens | Verify |
|---|---|---|---|
| **0. Deploy** | All defaults | Tables exist, services import, safe_state=true | Validation script exits 0 |
| **1. Change Detection** | `EXPERIENCE_COMPOSER_ENABLED=true`, shadow=true | Change detection runs, cursors populate | Cursor rows appear for test user |
| **2. Scoring** | + `EXPERIENCE_ATTENTION_ENABLED=true`, shadow=true | Scoring pipeline runs, events logged | `personal_experience_event` rows with `run_reason=shadow` |
| **3. Brief (shadow)** | + `EXPERIENCE_BRIEF_ENABLED=true`, shadow=true | Briefs generated but not delivered | `personal_brief_snapshot` rows with `run_reason=shadow` |
| **4. Internal preview** | shadow=true, internal user only | One internal account sees personalized home | Manual inspection, no external users |
| **5. Live (requires sign-off)** | shadow=false | Personalized experience visible to all users | Full validation suite, calibration metrics stable |

### Rollback

Set all flags to defaults. No data is deleted. Cursor and event tables
retain historical data for post-incident analysis.

---

## Risks

| Risk | Impact | Mitigation |
|---|---|---|
| **Filter bubble** | User only sees what they already know about | Novelty reserve (15% of top slots), weight bounds |
| **Stale personalization** | Preferences decay but experience doesn't adapt | Phase 15 decay/falsification, recency scoring |
| **Explainability failure** | Items surfaced without valid explanation | Explainability gate blocks unexplainable items |
| **Truth distortion perception** | User mistakes ordering for recommendation | SP-18b disclaimer, no advisory language |
| **Performance degradation** | Scoring pipeline too slow for real-time | Pre-compute during loop tick, cache composite scores |
| **Cross-user leakage** | Tenant isolation failure in scoring | User ID scoping on all queries, tenant isolation tests |
| **Feedback loop** | High-relevance items get more engagement, increasing relevance further | Anti-feedback-loop: `surface_was_personalized` flag on new signals (Phase 15 R2) |

---

## Feature Flags

| Flag | Type | Default | Description |
|---|---|---|---|
| `experience_composer_enabled` | bool | `false` | Top-level gate for the entire experience layer |
| `experience_shadow` | bool | `true` | When true, all output goes to event log only |
| `experience_brief_enabled` | bool | `false` | Enable daily brief generation |
| `experience_attention_enabled` | bool | `false` | Enable attention scoring pipeline |
| `experience_targets_enabled` | str | `""` | Comma-separated list of enabled experience surfaces |
| `experience_home_enabled` | bool | `false` | Enable personalized home experience |

---

## Acceptance Criteria

Phase 18 shadow validation passes when all of the following hold:

- [ ] All Phase 18 services importable
- [ ] All Phase 18 feature flags at safe defaults
- [ ] `safe_state.overall = true` from observability snapshot
- [ ] Validation script exits 0
- [ ] No truth-table writes in any Phase 18 service
- [ ] No advisory language in any Phase 18 service
- [ ] No upstream feedback paths (SP-18d verified by import audit)
- [ ] Explainability gate blocks items without complete explanations
- [ ] Novelty reserve enforced (15% of top slots)
- [ ] Attention floor enforced (priority > 0.8 → top 5)
- [ ] Weight bounds enforced (0.05 ≤ w ≤ 0.40)
- [ ] Tenant isolation verified (user A ≠ user B)
- [ ] Shadow event log populates correctly
- [ ] Brief snapshot populates correctly (shadow mode)
- [ ] All Phase 15 tests still pass (no regression)
- [ ] All Phase 13 tests still pass (no regression)
- [ ] No public experience route exists before sign-off
- [ ] Admin status endpoint returns complete observability snapshot

---

## Non-Goals (Explicitly Out of Scope)

- **LLM-generated prose in the experience layer** — all text is templated
- **Real-time streaming updates** — experience is computed per-request or per-tick
- **Social/collaborative features** — Phase 18 is single-user personalization
- **Recommendation of securities** — ordering is not advice (SP-18b)
- **Custom weight tuning per user** — weights vary by tier only, not per individual
- **Phase 19 integration** — Phase 19 is a separate spec
