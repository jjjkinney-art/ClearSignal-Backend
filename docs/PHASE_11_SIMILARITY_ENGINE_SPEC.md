# Phase 11 — Similarity Engine — Architecture Specification

**Phase:** 11 · Similarity & Resemblance Intelligence
**Status:** Design — not yet implemented
**Audience:** Principal/staff engineers, backend + frontend
**Scope:** Design only. No code, no migrations, no implementation in this document.
**Depends on:** 9G (Dossier + Historical Evidence), 10A (Loop), 10B (Watchlist), 10C (Delivery), 10D (Portfolio Intelligence), 16 (Accounts), 17 (Billing shadow)

---

## 0. Purpose and one-paragraph thesis

ClearSignal can already answer *"what is true about this company"* — its moat, its core debate, its catalysts, the places it disagrees with consensus, the historical episodes it rhymes with. Every one of those is a **per-entity** judgement. What the system cannot yet do is answer the **relational** question an experienced analyst asks reflexively: *"what does this remind me of?"* — which other names share this setup, which prior thesis this one echoes, which catalyst is structurally the same bet, which failure sequence is already in motion elsewhere, which regime this most resembles. The **Similarity Engine** is the relational layer. It does not produce any new primary intelligence. It is a **projection over intelligence that already exists** — it reads the dossier facets, the historical-analog library, the cross-exposure graph, and the portfolio substrate, encodes each into typed feature vectors, and computes *explainable* resemblance between any two comparable entities.

> **Design principle #1 — Similarity is a projection, never a source.** The engine owns no primary facts. Every feature it vectorises is read from a system that already persists it (dossier, evidence, exposure, portfolio, regime). If the engine appears to "know" something no upstream system knows, that is a bug, not a feature.

> **Design principle #2 — A score without a reason is not shippable.** Every similarity result must answer *"why is this similar?"* with the specific shared features that drove the score. A bare cosine number is an internal artifact, never a delivered one. Explainability is a hard output contract, not a nice-to-have (see §6).

> **Design principle #3 — Reuse the proven scorer.** `app/evidence_engine.py` already implements weighted, floored, diversity-enforced, disanalogy-penalised fingerprint matching against `historical_analogs`. The Similarity Engine generalises that exact pattern to new target types rather than inventing a parallel mechanism. The evidence engine becomes *one instance* of the general framework, not a competitor to it.

---

## 1. Similarity targets

The engine supports six **target types**. Each is a distinct `(query entity → candidate set)` relation with its own feature space, but all share one ranking framework (§5) and one explainability contract (§6).

| # | Target | Query entity | Candidate set | Primary substrate |
|---|---|---|---|---|
| T1 | **Company similarity** | a ticker's dossier | all other dossiers | `company_dossier` + facets |
| T2 | **Thesis similarity** | current/most-recent thesis | historical `thesis_versions` + other tickers' current theses | `thesis_versions`, `dossier_core_debate`, `dossier_variant` |
| T3 | **Catalyst similarity** | one `dossier_catalyst` | other open/resolved catalysts across tickers | `dossier_catalyst` |
| T4 | **Failure-mode similarity** | a ticker's active failure sequence | `historical_analogs` + other tickers' active failure modes | `dossier_failure_mode` + `historical_analogs` |
| T5 | **Macro-regime similarity** | current `MarketRegime` | historical regime snapshots + analog `macro_regime` tags | `market_regime_tracker`, `historical_analogs.macro_regime` |
| T6 | **Portfolio similarity** *(future use)* | a portfolio's exposure projection | other portfolios / model sleeves | `PortfolioExposureProjection`, `portfolio_positions` |

> **Grounding note.** T4 is *already half-built*: `dossier_failure_mode.analog_id` is a soft FK into `historical_analogs`, and the evidence engine already scores analog relevance. T4 is therefore the lowest-risk first target (§9 rollout). T6 is explicitly deferred — the projection object exists (`PortfolioExposureProjection`) but multi-portfolio comparison has no consumer until forecasting/scenario work lands.

### 1.1 Target taxonomy invariants

- **Like compares to like.** A query of type T_i only ever scores against candidates of type T_i. The engine never computes "how similar is this catalyst to this regime." Cross-type reasoning is a *future* concern handled by composition (§8), not by the core scorer.
- **The query entity is always resolvable from a `(ticker | portfolio_id | thesis_version_id | catalyst_id)` handle.** No free-text query enters the engine. (Free-text → entity resolution is upstream, owned by the router, out of scope here.)
- **Self is excluded.** The query entity never appears in its own result set.

---

## 2. Similarity sources (anti-duplication contract)

The engine reads **only** the following systems. This table is the complete authorised substrate; anything not listed here is off-limits to Phase 11.

| Source system | Table(s) / object | Features contributed | Targets served |
|---|---|---|---|
| **Company Dossier** | `company_dossier`, `dossier_core_debate`, `dossier_moat_dimension`, `dossier_variant`, `dossier_durability` | moat axes, debate framing/lean, variant divergences, durability signals, stance/conviction cache | T1, T2 |
| **Historical Evidence** | `historical_analogs` (+ `app/evidence_engine.py` scorer) | setup fingerprint (concern_tags, mechanism, valuation_regime, growth_phase, macro_regime), outcome payload | T2, T4, T5 |
| **Dossier Failure Modes** | `dossier_failure_mode` | active analog link, `sequence_stage`, `relevance_at_match` | T4 |
| **Dossier Catalysts** | `dossier_catalyst` | statement, direction, specificity, expected_window, status, conviction_weight | T3 |
| **Cross Exposure** | `cross_exposures` | shared_concerns, exposure_type, edge strength | T1, T6 |
| **Portfolio Intelligence** | `portfolio_positions`, `PortfolioExposureProjection` | position set, weights, shared/failure/catalyst clusters | T6 |
| **Market Regime** | `market_regime_tracker`, `MarketRegime` | rate_environment, risk_appetite, regime factors | T5 |

> **Design principle #4 — No new intelligence tables.** Phase 11 introduces *similarity-result* persistence (§4) and *feature-vector cache* tables only. It does **not** add a single column to any source table, and it never writes back into a source. The dossier does not learn that it is "similar to NVDA" — that relation lives entirely in the similarity layer.

> **Grounding note — the fingerprint already exists.** `SetupFingerprint` (`evidence_engine.py:85`) is the canonical feature primitive for T2/T4/T5. `concern_tags`, `inferred_mechanisms`, `valuation_regime`, `growth_phase`, `macro_regime` are already derived at request time by `build_fingerprint(...)`. Phase 11 promotes this transient dataclass into a **persisted, typed, multi-target feature vector** (§3) — it does not re-derive the fingerprint logic.

---

## 3. Data model

Two new concepts: the **feature vector** (typed, per-entity, per-target) and the **similarity edge** (a scored, explained relation between two entities). Both are *derived* and disposable — they can be dropped and rebuilt from the substrate at any time.

### 3.1 Feature vector — `similarity_feature_vector`

A typed, sparse feature representation of one entity for one target type. Stored, not just computed, so ranking is a cheap vector read rather than a full re-derivation on every query.

| Field | Type | Notes |
|---|---|---|
| `id` | uuid | |
| `target_type` | enum | `company | thesis | catalyst | failure_mode | regime | portfolio` |
| `entity_key` | string | `ticker` / `catalyst_id` / `thesis_version_id` / `portfolio_id` |
| `categorical` | json map | Discrete features: `{sector, business_model, valuation_regime, growth_phase, macro_regime, moat_composite, debate_lean, catalyst_direction, ...}` |
| `tag_set` | json list | Set-valued features for Jaccard: `concern_tags`, `mechanisms`, `shared_concerns`, moat axes present |
| `numeric` | json map | Bounded scalars in [0,1] or normalised: `conviction`, `durability_score`, `specificity`, `sequence_stage_norm` |
| `text_anchor` | text | The one human-readable sentence that *names* this entity's setup (used only for explanation rendering, never scored directly) |
| `source_versions` | json map | Provenance: which `row_version` / `version` of each facet produced this vector (staleness + invalidation key) |
| `vector_schema` | int | Bumped when feature taxonomy changes → forces global recompute |
| `built_at` | ts | |
| `user_id` | string | Identity scoping (Phase 16) — see §3.4 |

> **Design principle #5 — Features are typed, not embedded.** The engine deliberately uses *interpretable* features (sets, categoricals, bounded scalars), not opaque learned embeddings. This is what makes §6 explainability tractable: every dimension has a name and a source. A future learned-embedding lane is possible (§8) but is additive and must carry its own explanation channel.

### 3.2 Similarity edge — `similarity_edge`

One scored, explained relation. Materialised for hot paths (dossier render, portfolio insight) and TTL-expired like the entitlement cache.

| Field | Type | Notes |
|---|---|---|
| `id` | uuid | |
| `target_type` | enum | as above |
| `query_key` | string | entity_key of the query side |
| `candidate_key` | string | entity_key of the candidate side |
| `score` | float 0–1 | composite similarity (§5) |
| `rank` | int | position within the query's result set at materialisation time |
| `contributions` | json list | **the explanation** — ordered list of `{feature, shared_value, weight, partial_score}` (§6) |
| `headline` | text | one-sentence "why similar" rendered string |
| `disanalogy` | text | the strongest *dissimilarity* — the honesty tax (§6.3) |
| `floor_passed` | bool | did this clear the relevance floor (else it is a "weak/none" result) |
| `score_schema` | int | weighting-profile version → invalidation key |
| `built_at` / `expires_at` | ts | TTL materialisation |
| `user_id` | string | scoping |

> **Design principle #6 — Edges are a cache, theses are truth.** A `similarity_edge` is never authoritative. It can always be recomputed from two feature vectors + a weighting profile. Dropping the whole `similarity_edge` table must degrade latency, never correctness.

### 3.3 Weighting profile (config, not table)

Per-target weight vectors live in versioned config (mirroring `InjectionConfig`), not in the DB, so they can be tuned and A/B-rolled without a migration. Each profile carries `score_schema` so edges built under an old profile are transparently invalidated.

### 3.4 Identity & isolation (Phase 16 alignment)

- **Substrate read scope.** Dossier/catalyst/failure-mode rows carry `user_id`. The engine respects the **same** ownership scoping as the source — a similarity query runs against the candidate set *visible to the requesting user* (system-default user sees the shared/global library).
- **No cross-tenant leakage.** A `similarity_edge` is scoped to the `user_id` whose candidate set produced it. The system-default global library (e.g. `historical_analogs`, which is read-only and unowned) is shared; user-owned dossiers are not.
- **Free / paid gating.** Similarity depth (top-K, number of targets, cross-portfolio T6) is an **entitlement** (Phase 17). Enforcement is failure-open and gated behind `ENTITLEMENTS_ENFORCED` exactly like every other Phase 17 limit — shadow-safe by default.

---

## 4. Architecture

```
                          ┌─────────────────────────────────────────┐
                          │            SOURCE SUBSTRATE              │
                          │  dossier · evidence · exposure · regime  │
                          │            · portfolio                   │
                          └───────────────┬─────────────────────────┘
                                          │ read-only (§2 contract)
                          ┌───────────────▼─────────────────────────┐
   (loop / extraction     │           FEATURE BUILDER               │
    invalidation events)─▶│  per (target_type, entity) → vector     │
                          │  reuses build_fingerprint() for T2/4/5  │
                          └───────────────┬─────────────────────────┘
                                          │ writes
                          ┌───────────────▼─────────────────────────┐
                          │      similarity_feature_vector (cache)   │
                          └───────────────┬─────────────────────────┘
                                          │ read
                          ┌───────────────▼─────────────────────────┐
                          │            SIMILARITY SCORER             │
                          │  weighted composite + floor + diversity  │
                          │  + disanalogy tax (generalised evidence  │
                          │  engine)                                 │
                          └───────────────┬─────────────────────────┘
                                          │ writes (TTL)
                          ┌───────────────▼─────────────────────────┐
                          │          similarity_edge (cache)         │
                          └───────────────┬─────────────────────────┘
                                          │ read
              ┌───────────────────────────┼───────────────────────────┐
              ▼                           ▼                           ▼
        DOSSIER RENDER            DELIVERY (brief/digest/         PORTFOLIO INSIGHT
        ("resembles …")           inbox/watchlist)               ("your NVDA setup
                                                                  echoes …")
```

### 4.1 Components

1. **Feature Builder** — pure function `(target_type, entity, substrate snapshot) → feature_vector`. Idempotent. For T2/T4/T5 it *calls the existing* `build_fingerprint()` and widens the result; it never forks that logic.
2. **Similarity Scorer** — pure function `(query_vector, candidate_vector, weighting_profile) → (score, contributions, disanalogy)`. A direct generalisation of `_score_analog()` (`evidence_engine.py:180`): Jaccard on tag sets, exact/sibling match on categoricals, bounded-scalar proximity on numerics, quality boost, flat disanalogy penalty, clamp to [0,1].
3. **Ranker** — applies relevance floor, diversity constraint (at most one candidate per *dominant feature class*, mirroring "one analog per mechanism"), top-K, and writes materialised edges.
4. **Invalidation Controller** — subscribes to dossier `row_version` bumps, `DossierRevision` writes, catalyst lifecycle transitions, and regime changes; marks affected feature vectors dirty and expires dependent edges.

### 4.2 Compute model — read-time vs. precomputed

- **T1/T4 (dossier-render hot path):** precomputed and materialised. The dossier read path must not block on a fan-out scoring pass. Edges are rebuilt by the loop (§4.3), served from cache on render.
- **T2/T3/T5 (interactive / on-demand):** computed read-time against cached vectors, optionally materialised if requested inside a delivery surface.
- **T6 (future):** batch-only.

### 4.3 Loop integration (10A)

The Continuous Loop already walks watched tickers and refreshes intelligence. Phase 11 adds **one idempotent step** to the existing loop cadence: *for each ticker whose feature vector is dirty, rebuild the vector and re-rank its edges.* This reuses the loop's lock service, repositories, and scheduler — it does **not** introduce a second scheduler. Similarity freshness is therefore bounded by the loop interval, which is the correct cadence (resemblance does not change faster than the underlying dossier).

---

## 5. Ranking framework

### 5.1 Composite score

For a query vector *q* and candidate vector *c* under weighting profile *W*:

```
score(q, c) =  Σ_f  W_f · sim_f(q_f, c_f)            (Σ W_f = 1.0)
             + quality_boost(c)                       (small, bounded)
             − disanalogy_penalty                     (flat honesty tax)
        clamp → [0, 1]
```

Per-feature similarity `sim_f` by feature kind:

| Feature kind | `sim_f` | Example |
|---|---|---|
| tag set | Jaccard `|A∩B| / |A∪B|` | shared `concern_tags`, shared moat axes |
| categorical | `1.0` exact / `0.5` sibling / `0` none (sibling map per dimension) | `valuation_regime`, `growth_phase`, `business_model` |
| bounded scalar | `1 − |a−b|` | `conviction`, `specificity`, `durability_score` |
| ordinal | graded by distance | `sequence_stage`, `debate_lean` (bull/balanced/bear) |

> **Grounding note.** This is the evidence-engine formula with named generality. The current production weights for T4/analog (`0.40` tag, `0.30` mechanism, `0.15` setup, `0.10` context, `0.05` macro) become the **default weighting profile for the failure-mode target** and the template for the other five profiles.

### 5.2 Floor, diversity, top-K

- **Relevance floor.** Below-floor candidates are not returned as "weak matches dressed as strong"; they collapse into an explicit `none/weak` state (the watchlist/brief renders "no strong resemblance found" rather than a forced low-confidence row). Reuses the `RELEVANCE_FLOOR` discipline.
- **Diversity constraint.** At most one candidate per dominant feature class so a result set is not five variations of the same match (generalises "one analog per mechanism").
- **Top-K.** Per-target, entitlement-gated (§3.4).

### 5.3 Tie-breaking & determinism

Ties broken by (a) higher provenance confidence, (b) fresher `source_versions`, (c) lexical `candidate_key` — so ranking is **deterministic** for identical substrate, which is a precondition for the drift tests in §7.

---

## 6. Similarity / explainability framework

> **The output contract: every edge answers "why is this similar?" before it ships.**

### 6.1 Contribution decomposition

Scoring is **additive and inspectable**. The scorer emits, alongside the scalar, an ordered `contributions` list:

```
contributions = [
  {feature: "concern_tags",     shared_value: ["capex_cycle","supply_chain_risk"], weight: 0.40, partial: 0.27},
  {feature: "mechanism",        shared_value: "demand_pull_forward",               weight: 0.30, partial: 0.30},
  {feature: "valuation_regime", shared_value: "peak_multiple",                     weight: 0.15, partial: 0.15},
  ...
]
```

The headline is rendered from the top-N contributions, never from the raw score.

### 6.2 Explanation requirements (hard gates)

1. **No orphan scores.** An edge with an empty `contributions` list is invalid and must not be persisted or delivered.
2. **Feature-named, not vibes.** Each contribution names a real feature and the concrete shared value — "both at peak multiple entering deceleration with capex-cycle exposure," not "structurally similar."
3. **Provenance reachable.** Each contribution traces to a source row/version via `source_versions`, so a user can ask "where did this come from" and reach the dossier facet or analog.
4. **Magnitude honesty.** The rendered strength language (strong / moderate / weak resemblance) is a pure function of the floored score band — the words cannot overstate the number.

### 6.3 Disanalogy — the honesty tax

Mirroring the evidence library's mandatory `disanalogy` field, every edge surfaces its **strongest dissimilarity**: the highest-weight feature on which the two entities *disagree*. A resemblance result that cannot name how the two differ is treated as suspicious and down-ranked. This prevents the engine from manufacturing false confidence — *"resembles NVDA-2018 on setup, but differs on customer concentration and balance-sheet flexibility."*

---

## 7. Delivery integration

Similarity appears **only** where it earns attention, and always as an explained line, never a bare score. Each surface reads materialised edges; none computes similarity inline.

| Surface | Where it appears | Form | Target(s) |
|---|---|---|---|
| **Dossiers** | new "Resembles" facet on the dossier render | top-K company + failure-mode edges, each with headline + disanalogy | T1, T4 |
| **Briefings** (`MorningBriefV2`) | a "Pattern echoes" line inside *What Changed* / *Debate Shifts* when a watched name newly resembles a prior thesis or active failure sequence | 1–2 highest-score edges, suppressed below floor | T2, T4 |
| **Watchlists** | per-row affordance: "echoes 2 prior setups" chip; opens contribution detail | one company + one thesis edge per row | T1, T2 |
| **Portfolio insights** | augments existing exposure clusters: "this cluster resembles the 2022 software de-rating" | regime + failure-mode edges over the portfolio's tickers | T4, T5, (T6 future) |
| **Inbox** (in-app delivery) | a similarity event is emitted only on a *new strong* edge crossing the floor (state transition, not steady-state) | single edge, headline + CTA to dossier | T1, T2, T4 |
| **Digests** (`digest_batch_service`) | batched "patterns forming across your names" section | deduped strong edges across the watchlist, capped | T1, T2, T4 |

> **Design principle #7 — Similarity is delivered on transitions, not on existence.** The inbox/digest surfaces fire when an edge *crosses the floor for the first time* (a setup that now rhymes with something it didn't yesterday). Steady-state resemblances live passively on the dossier/watchlist and never spam delivery. This reuses the loop's existing dedup/content-hash machinery (10A/10C) — a similarity event is just another delivery candidate subject to relevance + dedup gating.

> **Grounding note.** No surface gets a new delivery pipeline. Each consumes `similarity_edge` and renders within the section structure that already exists (`MorningBriefV2`'s five sections, the watchlist row, the portfolio insight card, `in_app_delivery_service`, `digest_batch_service`).

---

## 8. Future compatibility

The engine is designed as the relational substrate three later capabilities will compose on top of. None is built in Phase 11; each is *enabled* by it.

- **Forecasting.** "Names resembling setup X historically did Y" — T2/T4 edges joined to `historical_analogs` outcome payloads (`drawdown_pct`, `time_to_recover_days`, `reaction_series`) give an empirical base rate. The engine supplies the *resembling set*; forecasting supplies the *outcome distribution*. The split is intentional: similarity stays descriptive, forecasting owns the predictive claim.
- **Scenario analysis.** Regime similarity (T5) lets a scenario ("rates re-accelerate") be expressed as "move the portfolio into the regime it most resembles in the analog library, replay outcomes." T5 edges are the regime-mapping primitive.
- **Decision intelligence.** Cross-type composition — "this catalyst (T3) in this regime (T5) on a name with this failure mode (T4)" — is a *composed* query over multiple single-type edge sets. The core scorer stays single-type (§1.1); composition is a higher layer that intersects edge sets, never a new scorer.
- **Learned-embedding lane (optional).** A future embedding feature may be added as one more *typed feature* with its own explanation channel (nearest-neighbour exemplars), additively, behind a flag. It never replaces the interpretable features and never bypasses §6.

> **Design principle #8 — Composition over a fatter scorer.** Every future capability is a *consumer* of single-type edges or a *composer* of several. The scorer's job stays small and testable. Resisting "just add cross-type scoring" is what keeps §6 and §7 honest.

---

## 9. Rollout strategy

Mirrors the project's established shadow-first ladder (9G canary, 10x shadow, 17 billing shadow). **Every stage is reversible and flag-gated; default state is fully inert.**

| Stage | Gate | State | Validation |
|---|---|---|---|
| **0 · Schema** | migration only | `similarity_feature_vector` + `similarity_edge` created, unused | table-count assertion; no read/write path live |
| **1 · Feature build (shadow)** | `SIMILARITY_BUILD_ENABLED=false` | builder runs in loop, writes vectors, **no surface reads** | vector coverage %, build latency, zero delivery change |
| **2 · Scoring (shadow)** | `SIMILARITY_SCORING_ENABLED=false` | edges materialised, **not delivered**; observable via `/admin/similarity-status` | score distributions, floor pass-rate, determinism check |
| **3 · Target T4 live** | `SIMILARITY_TARGETS=failure_mode` | failure-mode resemblance on dossier only (lowest risk — substrate already half-built) | explanation completeness, no orphan scores |
| **4 · T1/T2 live** | add `company,thesis` | dossier "Resembles" + watchlist chips | engagement, false-positive review |
| **5 · Delivery transitions** | `SIMILARITY_DELIVERY_ENABLED=false→true` | inbox/digest fire on floor-crossing | delivery volume, dedup correctness, opt-out respect |
| **6 · T3/T5** | add `catalyst,regime` | brief + portfolio surfaces | quality review |
| **7 · Entitlement gating** | `ENTITLEMENTS_ENFORCED` (Phase 17) | depth/top-K gated by plan | 402 behaviour for over-limit, failure-open verified |

- **Master inertness.** With all `SIMILARITY_*` flags false, Phase 11 is invisible: no surface changes, no delivery, only (optionally) shadow vector builds that nothing reads.
- **Observability.** A single `GET /admin/similarity-status` snapshot (mirroring `/admin/billing-status` and the portfolio/delivery observability services): vector coverage, edge counts by target, floor pass-rate, mean contributions per edge, stale-vector count, `safe_state` (= all delivery flags off). DB-down-safe, secret-free, never raises.
- **T6 explicitly out of this rollout.** Portfolio-to-portfolio similarity ships only when a forecasting/scenario consumer exists.

---

## 10. Validation

### 10.1 Correctness tests

- **Substrate isolation.** With every source table empty, all targets return empty result sets and raise nothing (mirrors the exposure projection's "empty when <2 positions / substrate missing" contract).
- **No write-back.** Property test: running the full engine over a fixture leaves every source table byte-identical (asserts §2 read-only contract).
- **Self-exclusion.** A query entity never appears in its own results.
- **Determinism.** Identical substrate + identical weighting profile → identical scores and ranks across runs (precondition for drift testing).
- **Identity scoping.** A user's query never returns another user's owned entity; the shared global library is visible to all.
- **Cache equivalence.** A materialised edge equals a freshly recomputed one for the same `source_versions` + `score_schema` (asserts §3.2 "edges are a cache" invariant).

### 10.2 Similarity quality tests

- **Golden resemblance set.** A curated fixture of known good matches — e.g. "NVDA-2024 setup should rank a Cisco-2000-style infrastructure-buildout analog in its top-K for T4." Asserts the *right* matches surface, not just that *some* match surfaces. Mirrors the 9G golden-set harness.
- **Floor calibration.** Hand-labelled strong/weak/none triples must land in the correct band; precision@K on the labelled set tracked over time.
- **Diversity.** No result set is N variations of one feature class.
- **Disanalogy presence.** Every above-floor edge carries a non-empty, feature-grounded disanalogy.

### 10.3 Drift tests

- **Score stability under no-op rebuilds.** Re-running the builder/scorer on unchanged substrate must not move scores (catches non-determinism and floating-point regressions).
- **Bounded response to small changes.** A single-facet dossier change moves affected edge scores by a bounded, monotonic amount — no cliff edges from a one-sentence rationale edit (mirrors the moat hysteresis / `pending_flip` philosophy).
- **Schema-bump invalidation.** Bumping `vector_schema` or `score_schema` forces a full, observable recompute; no stale-schema edge is ever served.
- **Weighting-profile A/B.** Two profiles over the same substrate produce comparable, logged distributions so a tuning change's effect is measurable before promotion.

### 10.4 Explainability requirements (test-enforced)

1. **Zero orphan scores** — CI asserts no persisted/delivered edge has empty `contributions`.
2. **Contribution sum reconciliation** — Σ `partial` (± quality/disanalogy terms) reconciles to `score` within tolerance; the explanation *is* the computation, not a post-hoc narrative.
3. **Provenance reachability** — every contribution's `source_versions` entry resolves to a live source row.
4. **Language-magnitude lock** — rendered strength words are a pure function of the score band; a property test forbids "strong" copy on a below-band score.

---

## 11. Risks

| # | Risk | Mitigation |
|---|---|---|
| R1 | **False resemblance / spurious confidence** — engine asserts similarity that an analyst would reject | Relevance floor + mandatory disanalogy (§6.3) + golden-set precision tracking (§10.2); below-floor collapses to honest "no strong resemblance" |
| R2 | **Substrate duplication creep** — a future PR adds a "similarity needs its own copy of X" table | §2 authorised-substrate table is a hard contract; the no-write-back property test (§10.1) fails the build if violated |
| R3 | **Stale edges** — dossier moves, edge doesn't | Invalidation controller keyed on `row_version`/`DossierRevision`/catalyst lifecycle (§4.1); `source_versions` mismatch forces rebuild; loop-bounded freshness (§4.3) |
| R4 | **Delivery spam** — similarity floods inbox/digest | Transition-only firing (§7, principle #7) + reuse of 10A/10C dedup + entitlement caps |
| R5 | **Cross-tenant leakage** — user A sees similarity into user B's dossier | Identity scoping mirrors source ownership (§3.4); scoping test in §10.1 |
| R6 | **Explainability rot** — scores ship faster than reasons | Explanation is a *hard gate* not a feature; orphan-score CI check (§10.4) blocks merge |
| R7 | **Score instability / non-determinism** — same inputs, different output erodes trust | Deterministic tie-breaks (§5.3) + drift tests (§10.3) |
| R8 | **Performance fan-out** — N² scoring on dossier render | Precompute + materialise for hot targets (§4.2); read-time only for interactive; loop does the heavy pass off the request path |
| R9 | **Scope creep into prediction** — engine starts implying outcomes | Hard descriptive/predictive split (§8, principle #8); forecasting is a *consumer*, never inside the scorer |
| R10 | **Premature T6** — portfolio similarity built with no consumer | T6 explicitly deferred from the §9 rollout until a forecasting/scenario surface needs it |

---

## 12. Summary

Phase 11 turns ClearSignal from a system that *understands each company* into one that *understands what each company resembles* — without minting a single new fact. It is a thin, explainable, reversible relational layer that vectorises existing dossier/evidence/exposure/regime/portfolio intelligence, scores resemblance with the proven evidence-engine mechanics generalised to six target types, and delivers each match as a feature-named "why," with its disanalogy stated, only where and when it earns attention. It ships behind the same shadow-first, flag-gated, observability-backed ladder as every prior phase, and it is built so that forecasting, scenario analysis, and decision intelligence can later *compose* on its edges rather than re-derive resemblance themselves.

> **One-line invariant.** *A score the engine cannot explain, trace, and contradict with a disanalogy is not allowed to leave the engine.*
