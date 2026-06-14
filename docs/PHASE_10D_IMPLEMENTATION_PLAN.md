# Portfolio Intelligence — Implementation Plan

**Phase:** 10D · the portfolio layer
**Source of truth:** `docs/PHASE_10D_PORTFOLIO_INTELLIGENCE_SPEC.md` (approved — this plan does not redesign anything)
**Status:** Execution blueprint — no code in this document
**Convention basis:** All file paths, flags, and table conventions reference the existing codebase (10A loop, 10B watchlist, 10C delivery). 10D reuses the 10C delivery spine (`loop_delivery_service.py`, `delivery_ledger`, `notifications`, `digest_batches`), the 10A loop tick as its generation trigger, the 10B `watched_tickers` substrate as its membership seed, and the 9G dossier + `cross_exposures` graph as its only analytical inputs **wholesale**. 10D adds a portfolio model, an exposure-projection layer, a template-bound insight generator, a health-metrics reader, and one new delivery producer — nothing more. **It computes no new company-level analysis.**

---

## PART 1 — BUILD SLICES

Nine slices. Each is independently shippable, independently revertible, and leaves production in a working state if the next slice never lands. The slicing rule, carried from 10C and sharpened for a portfolio layer that sits on top of the delivery stack: **model before projection, project before generate, generate before rank, rank before deliver, and everything in shadow before anything reaches a user.** Nothing that *produces a portfolio insight* lands until the model that *describes the portfolio* exists; nothing that *delivers* one lands until the regulatory guard that *vets its language* has run in shadow.

> **Standing safety property.** Every slice through Slice 8 lands with `portfolio_insights_shadow=True` (mirroring 10C's `delivery_shadow`) and the 10C delivery flags at their safe defaults (`delivery_in_app_enabled=false`, `delivery_shadow=true`). 10D can model portfolios, project cross-exposure, generate and rank insights, and write `portfolio_insights` rows for weeks while every insight flows into the existing `delivered_shadow` path and reaches no user. The consequential flip is a **config sequence in PART 5**, never a slice. This is 10C's "rank and batch for weeks with delivery off" discipline, inherited one layer up.

> **The no-new-intelligence imperative.** Slice 3 (exposure projection) exists because every portfolio insight is a *combination* of facts already in `cross_exposures`, `company_dossier`, and `dossier_*` facets (spec §0 principle #1). 10D **reads** that graph and aggregates it; it never issues an LLM call to synthesize a new company-level fact. The grep gate in Slice 5 enforces this: no portfolio service imports the synthesis path. If 10D ever claims to know something a dossier does not, the principle is broken.

> **The regulatory imperative.** Slice 5 (insight generation) is template-bound from line one. There is no free-form LLM generation of insight text anywhere in 10D (spec §6.2). The canonical template set is the *only* producer of insight prose, reviewed at the slice gate against the prohibited-language list. This is the portfolio analogue of 10C's "one severity vocabulary" discipline: one prose source, vetted once, never bypassed.

---

### Slice 1 — Portfolio model: schema & CRUD (no intelligence)

**Objective:** Create the three new 10D tables empty in production and expose pure portfolio/position CRUD. A user can create a portfolio and add positions; nothing is computed from them yet. Zero analytical behavior.

**Files:**
- `app/db/migrations/008_portfolio_intelligence.sql` (new — `CREATE TABLE IF NOT EXISTS` for `portfolios`, `portfolio_positions`, `portfolio_insights`; all indexes per PART 2)
- `app/db/models.py` (append ORM: `Portfolio`, `PortfolioPosition`, `PortfolioInsight`; mirror the existing `watched_tickers` / `user_delivery_prefs` column conventions — `user_id` nullable, soft-delete `active`, `created_at`/`updated_at`)
- `app/db/repositories/portfolio_repo.py` (new — `create_portfolio`, `get_portfolio`, `list_portfolios`, `update_portfolio`, `soft_delete_portfolio`; `add_position`, `update_position`, `remove_position` (sets `active=False`), `list_positions`; null-object on `session=None`)
- `app/api.py` (extend — the §9.1 management routes: `GET/POST /portfolio`, `GET/PATCH/DELETE /portfolio/{id}`, position sub-routes; each carries the §6.3 `regulatory_disclaimer` field)
- `app/startup.py` (register migration with the `db_table_count` before/after guard, the 10A/10B/10C precedent; **table count 28 → 31**)

**Dependencies:** none new — reuses the existing DB connection, session, and API router conventions.

**Validation:** `db_table_count` rises by 3 (28 → 31) on `/health`; app boots clean; all existing tests pass untouched; migration idempotent (run twice, no error, no duplicate index). Unit: create→read→update→soft-delete round-trip for a portfolio; `add_position` is idempotent on `(portfolio_id, ticker)` (re-adding reactivates, never duplicates — the `watched_tickers` discipline); `weight`/`cost_basis`/`shares` accept NULL. API: every portfolio response includes `regulatory_disclaimer`. `validate_10c_delivery_shadow.py` still green (no regression to the 10C surface).

**Rollback strategy:** None needed — additive `IF NOT EXISTS` DDL, all unread by any intelligence layer. Tables inert without later slices. Revert = remove the CRUD routes; the tables sit empty and harmless. No delivery path touches them.

---

### Slice 2 — Default portfolio: watchlist mirror

**Objective:** Auto-create a default portfolio that mirrors the existing `watched_tickers` as `watchlist`-class positions. The portfolio model becomes populated for every existing user with zero user action. A pure read-projection of 10B state — `watched_tickers` remains source of truth.

**Files:**
- `app/services/portfolio_service.py` (new — `ensure_default_portfolio(user_id)` creates the `is_default=True` portfolio if absent; `sync_watchlist_positions(user_id)` upserts a `watchlist`-class position per active `WatchedTicker`, soft-deletes positions whose ticker left the watchlist; idempotent)
- `app/main.py` (extend the lifespan startup — after the existing 10B `watched_tickers` backfill, call `sync_watchlist_positions` for the global user; mirrors the existing idempotent-backfill block, non-fatal on error)
- `app/db/repositories/portfolio_repo.py` (extend — `get_default_portfolio(user_id)`, `upsert_watchlist_position`)

**Dependencies:** Slice 1. Reads the 10B `watched_tickers` table and `watchlist_service` (the existing membership interface).

**Validation:** Unit: a user with N active watched tickers gets one `is_default` portfolio with N `watchlist`-class positions; removing a ticker from the watchlist soft-deletes the mirrored position on next sync; manual (non-watchlist) positions are **never** touched by the sync (only `membership_class=watchlist` rows are reconciled). Startup integration: boot against a DB with existing `watched_tickers` → default portfolio appears, position count matches active watchlist count, re-run leaves counts unchanged (idempotent). No write to `watched_tickers` (read-only projection verified by grep gate).

**Rollback strategy:** Revert the startup sync call — default portfolios stop refreshing but existing rows remain valid and inert. The watchlist is unaffected (never written). No intelligence reads positions yet, so reverting changes no behavior.

---

### Slice 3 — Cross-exposure projection (read-only clusters)

**Objective:** Project the existing `cross_exposures` graph onto a portfolio — select edges where both endpoints are positions — and build the three §2.2 aggregate signals (shared risk clusters, high-correlation pairs, concentration). Computed and exposed read-only; **no insight is generated, nothing is delivered.** Proves the projection is sane before generation depends on it.

**Files:**
- `app/services/portfolio_exposure_service.py` (new — `project(portfolio) → ExposureGraph`: select `cross_exposures` edges with both endpoints in the portfolio; `cluster_shared_concerns(graph) → [SharedRiskCluster]`; `find_correlation_pairs(graph, threshold) → [CorrelationAlert]`; `cross_exposure_as_of(graph) → min(updated_at)` for the §2.5 freshness bound; tag `stale_input` past the staleness threshold)
- `app/db/repositories/portfolio_repo.py` (extend — read helpers: `positions_for(portfolio)`, `cross_exposure_edges_for(tickers)` reading the existing `cross_exposures` table)
- `app/api.py` (extend — `GET /portfolio/{id}/cross-exposure` returns clusters + pairs + `cross_exposure_as_of`; read-only, disclaimer-bearing)
- `app/config.py` (add `portfolio_correlation_threshold` default `0.7`, `portfolio_staleness_days` default `7`, both tunable per §2.5/§11)

**Dependencies:** Slices 1–2. Reads the 9G `cross_exposures` table read-only; joins logically by ticker (no FK).

**Validation:** Unit: a portfolio of three positions with two shared-concern edges produces exactly one cluster covering both concerns' members; an edge with `strength ≥ threshold` surfaces as a `CorrelationAlert`, one below does not; `cluster_weight` sums member weights when present and is NULL when any member weight is absent; `cross_exposure_as_of` equals the min edge `updated_at`; an edge older than `portfolio_staleness_days` flags `stale_input`. Integration: project against a seeded portfolio with known `cross_exposures` rows → cluster membership matches the hand-computed expectation; a portfolio whose positions share no edges yields an **empty** cluster list (graceful, not error — the §11 sparsity mitigation).

**Rollback strategy:** Dead-weight computation behind a read-only GET. Revert = remove the endpoint; nothing downstream consumes the projection yet. The `cross_exposures` table is never written. No delivery behavior changes.

---

### Slice 4 — Portfolio health metrics (read-only characterization)

**Objective:** Compute the §4 structural metrics — HHI / effective-N / top-N concentration, thematic exposure (from `shared_concerns`), regime sensitivity (from `MacroSensitivity`). Read-only characterization, exposed on the health endpoint. **No forecast, no score, no recommendation** (spec §4.5 exclusions enforced).

**Files:**
- `app/services/portfolio_health_service.py` (new — `concentration(portfolio) → {hhi, effective_n, top_n, cap_breaches}` computed only when weights present, degrade-to-count when absent; `thematic_exposure(portfolio) → [ThematicExposure]` aggregating `cross_exposures.shared_concerns`; `regime_sensitivity(portfolio) → [RegimeSensitivity]` aggregating per-company `MacroSensitivity`; never emits a single composite score)
- `app/api.py` (extend — `GET /portfolio/{id}/health`, `GET /portfolio/{id}/themes`, `GET /portfolio/{id}/regime-sensitivity`; all read-only, all disclaimer-bearing)
- `app/config.py` (add `portfolio_max_single_position_pct` default `0.20` for the cap-breach flag, configurable per §4.2)

**Dependencies:** Slices 1–3 (reuses the exposure projection's cluster/theme aggregation). Reads `MacroSensitivity` from the existing dossier construction output.

**Validation:** Unit: HHI of an equal-weight 5-position portfolio ≈ 0.20, effective-N ≈ 5.0; a 30% position trips the cap-breach flag at the 20% default; a portfolio with **no weights** returns count-based metrics and NULL HHI (no crash, no fabricated weight — the §11 missing-weight mitigation); thematic exposure groups tickers by `shared_concern` label with summed weight; regime sensitivity groups by `regime_factor` with sign. **Regulatory gate:** assert no health response contains any of the §4.5-prohibited fields (volatility, beta, VaR, Sharpe, expected return, composite score) — a structural test over the response schema, not a string scan. Integration: health view of a seeded weighted portfolio matches hand-computed HHI/effective-N.

**Rollback strategy:** Read-only GETs over additive computation. Revert = remove the endpoints; no write path, no data risk. Health is never an input to delivery, so reverting is invisible to the pipeline.

---

### Slice 5 — Insight generation (template-bound, shadow-stamped)

**Objective:** Turn exposure clusters + health signals into the §3.1 closed-taxonomy insights, with prose produced **only** from the canonical template set (spec §6.2). Insights are written to `portfolio_insights` and stamped with canonical severity; **nothing is ranked or delivered yet.** This is the slice where the regulatory boundary becomes load-bearing.

**Files:**
- `app/services/portfolio_insight_templates.py` (new — the closed template set, one template per §3.1 insight type; each emits structural-observation prose only; **no `should`/`will`/`expect`/`recommend`** by construction; this is the *only* source of insight text in 10D)
- `app/services/portfolio_insight_service.py` (new — `generate(portfolio) → [InsightCandidate]`: run the §3.1 detectors over the Slice 3 projection + Slice 4 health, map each to its template, stamp canonical `severity`/`severity_rank` via the existing `severity_model.py`, compute `cross_exposure_as_of`; cap severity at MEDIUM when `stale_input`)
- `app/services/portfolio_regulatory_guard.py` (new — `vet(insight_text) → ok | violation`: the §6.2 enforcement filter; scans rendered prose for the prohibited-language set; any hit blocks the insight and logs a violation — defense-in-depth behind the template constraint)
- `app/db/repositories/portfolio_repo.py` (extend — `upsert_insight` keyed on `content_key` (§3.4), `list_insights(portfolio)`)
- `app/services/loop_producers.py` (extend — register a `portfolio_insight` producer on the existing 10A loop tick: when a `watchlist_scan` writes a dossier update for ticker T, re-evaluate insights for portfolios containing T; write `portfolio_insights` rows in shadow)

**Dependencies:** Slices 3–4. Reuses `severity_model.py` (10C Slice 1) for canonical severity. Triggered by the existing 10A loop tick — no new cron.

**Validation:** Unit: each of the 8 §3.1 insight types generates from a constructed trigger; an insight with `stale_input` is capped at MEDIUM; `content_key = sha256(portfolio_id + insight_type + cluster_label + period_bucket)` is stable and dedups a same-bucket regeneration; a weight change > 5pp produces a new `content_key`, ≤ 5pp does not (§3.4). **Regulatory gate (the defining test):** every template, rendered against a battery of synthetic clusters, passes `portfolio_regulatory_guard.vet` — zero prohibited-language hits; and an *intentionally* non-compliant template is caught by the guard (proving the filter fires, not just that current templates happen to pass). Shadow integration: drive a synthetic loop tick with a dossier update on a clustered ticker → `portfolio_insights` rows appear with correct severity, all in shadow, none delivered.

**Rollback strategy:** Insights are generated but inert (no ranking, no delivery). Revert = stop the producer registration; `portfolio_insights` stops growing, existing rows are unread. `portfolio_insights_shadow=True` guarantees zero user impact regardless. The regulatory guard is additive and can stay even if generation is reverted.

---

### Slice 6 — Insight ranking (portfolio-relevance scoring)

**Objective:** Apply the §3.3 ranking formula so insights compete for delivery attention by portfolio relevance, not raw severity. Ranking is computed and stored on the insight row; the delivery pipeline still shadows, so ranking is observable but inert.

**Files:**
- `app/services/portfolio_insight_ranker.py` (new — `rank(insight) → rank_score = base_severity_score × portfolio_weight_factor × novelty_factor × recency_factor` per §3.3; `portfolio_weight_factor` reads cluster/total weight (fallback 1.0 when weights absent); `novelty_factor` reads `last_delivered_at`; `recency_factor` reads the triggering dossier `updated_at`)
- `app/services/portfolio_insight_service.py` (extend — stamp `rank_score` on each insight at generation; sort candidates descending before they reach the delivery boundary)
- `app/db/repositories/portfolio_repo.py` (extend — persist `rank_score`, read `last_delivered_at` for novelty)

**Dependencies:** Slice 5. Reuses the canonical `severity_rank` from `severity_model.py`. Structurally mirrors 10C's `relevance_ranker` (compose existing signals, introduce no new analytical judgment).

**Validation:** Unit: each of the four factors independently moves `rank_score` in the expected direction; a CRITICAL insight on a 30%-weight cluster outranks a CRITICAL on a 2%-weight cluster (the §0 principle #4 property — the test that proves portfolio context dominates raw severity); a just-delivered insight (novelty 0.3) ranks below a never-delivered peer of equal severity; the weightless fallback (factor 1.0) keeps scores bounded and deterministic. Shadow integration: 50 synthetic insights → the `rank_score` distribution is non-degenerate (not all-equal, not all-max — the 10C anti-degeneracy check applied to portfolio insights).

**Rollback strategy:** Dead-weight computation. Revert = stop stamping `rank_score`; insights fall back to raw severity ordering. No delivery reads the score yet, so reverting changes no behavior. Shadow blocks any user impact.

---

### Slice 7 — Delivery integration (briefing enrichment + standalone routing, shadow)

**Objective:** Wire portfolio insights into the 10C delivery pipeline as a new artifact class and enrichment layer (§5) — briefing section, alert `portfolio_context` enrichment, standalone `portfolio_alert` routing, digest coalescing. All through the existing delivery boundary; all still in shadow.

**Files:**
- `app/services/morning_brief_service.py` (extend — add the §5.3 `portfolio_intelligence_section()` helper appended after the existing watchlist-scan section; top-N insights, omitted entirely if all INFO; **existing sections unchanged**)
- `app/services/loop_delivery_service.py` (extend — the §5.2 enrichment: when a company-level alert's recipient holds related positions, add the `portfolio_context` block *after* dedup (enrichment never changes `content_key`); route standalone MEDIUM+ `portfolio_alert` insights through the existing guardrail boundary; coalesce overflow into the existing `digest_batches` with a 7-day `period_bucket` per §5.6)
- `app/db/repositories/loop_delivery_repo.py` (extend — `artifact_ref` points to `portfolio_insights.id`; `kind="portfolio_alert"` written on the `notifications` row — additive enum value, no migration)
- `app/config.py` (add `portfolio_insights_shadow=True` (the 10D shadow gate), `portfolio_briefing_top_n` default `3`)

**Dependencies:** Slices 5–6. Reuses the 10C `delivery_ledger`/`notifications`/`digest_batches` tables and the single guardrail chokepoint **unchanged** — 10D adds a producer, not a delivery path.

**Validation:** Unit: the briefing section is omitted when all insights are INFO and present (top-N, rank-ordered) otherwise; enrichment adds `portfolio_context` without altering `content_key` (an enriched and non-enriched delivery of the same alert share a key — the §5.2 no-double-send guarantee); a standalone MEDIUM insight routes through quiet-hours/cap/floor exactly as a company alert; cap overflow coalesces into one `digest_batches` row on a 7-day bucket, not 24h. Shadow integration: drive a full overnight → the briefing carries a portfolio section, an enriched alert carries `portfolio_context`, standalone insights resolve routes — all as `delivered_shadow`, zero external send, `kind="portfolio_alert"` stamped correctly.

**Rollback strategy:** `portfolio_insights_shadow=True` keeps everything in shadow regardless. Revert the enrichment/section calls — the briefing falls back to its existing sections, alerts deliver without `portfolio_context`, no standalone portfolio routing. The 10C delivery path is strictly unaffected (additive producer). Instant, no redeploy for the shadow flag.

---

### Slice 8 — Observability & shadow validator

**Objective:** Production confidence: a `/admin/portfolio-status` snapshot mirroring 10C's `/admin/delivery-status`, plus a `validate_10d_portfolio_shadow.py` shadow-readiness validator. No delivery behavior; pure visibility.

**Files:**
- `app/services/portfolio_observability_service.py` (new — `build_portfolio_snapshot(session) → dict`: portfolio/position counts, insight counts by type and severity, cluster coverage, `stale_input` rate, **regulatory-guard violation count (must be 0)**, `portfolio_insights_shadow` flag state, `safe_state`; never raises, null-object on `session=None` — the 10C observability discipline)
- `app/api.py` (extend — `GET /admin/portfolio-status`, disclaimer-bearing, follows the 10C admin-endpoint try/except null-fallback pattern)
- `tests/validate_10d_portfolio_shadow.py` (new — the shadow-readiness validator mirroring `validate_10c_delivery_shadow.py`: portfolio model populated, projection non-degenerate, insights template-bound, **regulatory violations = 0**, every response carries `regulatory_disclaimer`, severity canonical, no health response leaks a §4.5-prohibited field, `safe_state=true`)
- `tests/test_services/test_portfolio_admin_api.py` (new — the admin-endpoint test suite, following the 10C `test_delivery_admin_api.py` inline-handler pattern to sidestep the Python 3.9 import constraint)

**Dependencies:** Slices 1–7.

**Validation:** Admin endpoint shows all PART-4 metrics; regulatory-guard violation count is **0**; `safe_state=true` (insights in shadow); `validate_10d_portfolio_shadow.py` exits 0 against staging. Every portfolio API response asserted to carry `regulatory_disclaimer`. The snapshot never raises on `session=None` (returns zeros). `validate_10c_delivery_shadow.py` still green (10C surface untouched).

**Rollback strategy:** Observability is additive and read-only; reverting removes visibility but breaks no delivery. The validator is a test artifact. No production path depends on either.

---

## PART 2 — DATABASE PLAN

### New tables (3) — all additive, no existing table modified

**Portfolio head (user-authored):**

| Table | Key columns | Notes |
|---|---|---|
| `portfolios` | `id` uuid PK, `user_id` (nullable — NULL = global/single-user), `name`, `description`, `is_default` (bool), `created_at`, `updated_at` | The §1.1 portfolio head. `is_default=True` is the auto-created watchlist-mirror (Slice 2). `UNIQUE(user_id, name)` — one named portfolio per user. |

**Portfolio positions (user-authored holdings/watchlist):**

| Table | Key columns | Notes |
|---|---|---|
| `portfolio_positions` | `id` uuid PK, `portfolio_id` FK→portfolios, `ticker`, `membership_class` (`owned`\|`watchlist`\|`on_radar`), `weight` (nullable float), `cost_basis` (nullable), `shares` (nullable), `notes` (nullable), `active` (bool soft-delete), `added_at`, `updated_at` | The §1.1 position rows. `UNIQUE(portfolio_id, ticker)` — append-idempotency (re-add reactivates, never duplicates — the `watched_tickers` discipline). All financial fields user-supplied; **never fetched from external APIs** (§1.3). |

**Portfolio insights (system-derived, current-state):**

| Table | Key columns | Notes |
|---|---|---|
| `portfolio_insights` | `id` uuid PK, `portfolio_id` FK→portfolios, `insight_type` (closed §3.1 enum), `cluster_label`, `member_tickers` (json), `cluster_weight` (nullable), `severity` (canonical), `severity_rank` (int), `rank_score` (float), `body_json`, `cross_exposure_as_of`, `stale_input` (bool), `content_key` UNIQUE, `created_at`, `updated_at`, `last_delivered_at` (nullable) | The §8.3 derived-insight rows. `UNIQUE(content_key)` is the §3.4 dedup hard stop (7-day bucket). `severity`/`severity_rank` use the canonical `severity_model.py` ladder. |

### New fields summary

| Field | Table | Type | Written by | Read by |
|---|---|---|---|---|
| `membership_class` | `portfolio_positions` | str enum | Slice 1 CRUD / Slice 2 sync | health weighting, exposure scope |
| `weight` | `portfolio_positions` | float (nullable) | Slice 1 CRUD (user) | health metrics, ranking weight factor |
| `severity`/`severity_rank` | `portfolio_insights` | str/int (canonical) | Slice 5 generator | ranking, delivery floor |
| `rank_score` | `portfolio_insights` | float | Slice 6 ranker | delivery prioritization |
| `content_key` | `portfolio_insights` | str (UNIQUE) | Slice 5 generator | dedup (§3.4) |
| `cross_exposure_as_of` | `portfolio_insights` | ts | Slice 5 generator | staleness display/cap (§2.5) |
| `stale_input` | `portfolio_insights` | bool | Slice 5 generator | severity cap, UI flag |
| `last_delivered_at` | `portfolio_insights` | ts (nullable) | Slice 7 delivery | novelty factor (§3.3) |

> **No new delivery tables (§8.4).** Portfolio insights route through the existing `delivery_ledger` and `notifications`. `delivery_ledger.artifact_ref` points at `portfolio_insights.id`; `notifications.kind` gains the value `"portfolio_alert"` — additive on a free-form VARCHAR, **no migration, no `ALTER`.** The 10C `digest_batches` table absorbs portfolio digests with a 7-day `period_bucket` (no schema change). This is the single most important structural property of 10D: it adds a producer, not a pipeline.

### Migration

- **One file: `008_portfolio_intelligence.sql`** — three `CREATE TABLE IF NOT EXISTS` + indexes (PART 2). Header comment documenting the §0 no-new-intelligence and §6 regulatory-boundary design. Follows the 003–007 precedent.
- Apply order: after `007_briefing_delivery.sql`. Registered in `app/startup.py` with the `db_table_count` before/after guard. **Table count 28 → 31.**
- **No data migration** — tables start empty; population is organic (Slice 2 watchlist mirror, Slice 1 user CRUD, Slice 5 insight generation). No `ALTER` on any existing table — the `notifications.kind` extension is a new enum *value*, not a column change.
- **Startup note:** unlike 10C, 10D needs **no idempotent `ALTER TABLE` block** in the lifespan (the 02e5a73 pattern) because 10D adds only new tables — `create_all` handles those fully. The only lifespan addition is the Slice 2 `sync_watchlist_positions` call, modeled on the existing 10B backfill block.
- **Rollback:** tables inert without `portfolio_insights_shadow=False`; rollback = shadow flag stays True / revert producer registration. DDL never needs reverting (additive, unused until wired).

### Indexes

| Index | Table | Purpose |
|---|---|---|
| `UNIQUE(user_id, name)` | `portfolios` | one named portfolio per user; default-portfolio lookup |
| `(user_id, is_default)` | `portfolios` | O(1) default-portfolio resolution on the hot path |
| `UNIQUE(portfolio_id, ticker)` | `portfolio_positions` | position append-idempotency (re-add reactivates) |
| `(portfolio_id, active)` | `portfolio_positions` | active-position scan for projection/health |
| `(ticker, active)` | `portfolio_positions` | reverse lookup: "which portfolios hold T" (the loop-tick re-evaluation in Slice 5) |
| `UNIQUE(content_key)` | `portfolio_insights` | §3.4 dedup hard stop |
| `(portfolio_id, severity_rank)` | `portfolio_insights` | ranked insight read for briefing/delivery |
| `(insight_type, created_at)` | `portfolio_insights` | observability histograms (Slice 8) |

> The existing 10C `UNIQUE(content_key)` on `delivery_ledger` is **untouched** — it remains the duplicate-delivery hard stop. 10D's own `UNIQUE(content_key)` on `portfolio_insights` is the *generation*-side dedup (a 7-day bucket); the two are independent guarantees at different layers.

### Relationships

```
portfolios ──1:N──> portfolio_positions          (FK; soft-delete cascade by convention, not DDL)
portfolio_positions ── ticker ──(logical)──> watched_tickers     (Slice 2 mirror; READ-only, no FK)
portfolio_positions ── ticker ──(logical)──> company_dossier     (insight inputs; READ-only, no FK)
EXPOSURE INPUTS (read-only, no FK): cross_exposures, dossier_catalyst, dossier_failure_mode, MacroSensitivity ──read──> portfolio_exposure_service / portfolio_health_service
portfolio_insights ── artifact_ref ──> delivery_ledger.artifact_ref   (logical pointer; 10D insight → 10C delivery)
portfolio_insights ──coalesce──> digest_batches      (7-day bucket; reuses 10C table)
```

No FK from 10D into `cross_exposures`, `company_dossier`, `dossier_*`, or `watched_tickers` — the exposure and health services **read** them as inputs and join logically by ticker, keeping 10D independent of those subsystems' lifecycles (the 10A §5.4 / 10B / 10C discipline). The only physical FK is `portfolio_positions → portfolios`, the one ownership relationship 10D itself owns.

---

## PART 3 — SERVICE PLAN

Follow `app/services/` conventions: module-level functions, null-object on `session=None`, no business logic in repos. The 10D services sit **on top of** the 9G dossier graph and the 10C delivery spine, never replacing either.

| Service | File | Responsibilities | Does NOT |
|---|---|---|---|
| **Portfolio** | `portfolio_service.py` | Portfolio/position lifecycle; default-portfolio creation; watchlist mirror sync (§1.2, §2). | Never computes insights. Never writes `watched_tickers`. |
| **Exposure projection** | `portfolio_exposure_service.py` | Project `cross_exposures` onto a portfolio; build clusters, correlation pairs, freshness bound (§2.2, §2.5). | Never writes `cross_exposures`. Never invents an edge or a concern label. Never delivers. |
| **Health** | `portfolio_health_service.py` | Structural metrics: HHI/effective-N/concentration, thematic exposure, regime sensitivity (§4). | **Never forecasts.** Never emits a composite score or any §4.5-prohibited metric. Never recommends. |
| **Insight generation** | `portfolio_insight_service.py` | Detect §3.1 insights over projection+health; stamp canonical severity; compute `content_key`/freshness (§3.1–3.2, §3.4). | Never generates prose itself (delegates to templates). Never delivers. Never calls the LLM synthesis path. |
| **Insight templates** | `portfolio_insight_templates.py` | The closed template set — the **only** source of insight prose (§6.2). | Never includes `should`/`will`/`expect`/`recommend`. Never opinion/forecast/recommendation. |
| **Regulatory guard** | `portfolio_regulatory_guard.py` | Vet rendered prose against the §6.2 prohibited-language set; block + log violations. | Never edits prose (it blocks, it does not rewrite). Defense-in-depth behind templates. |
| **Insight ranking** | `portfolio_insight_ranker.py` | Compose the §3.3 factors into `rank_score`. | Never trains/prompts/invents a score. Never decides delivery (that's the 10C boundary). |
| **Observability** | `portfolio_observability_service.py` | `/admin/portfolio-status` snapshot; violation count; shadow state (§9.3). | Never raises. Never sends. Pure read. |

**Reused 10C/10A services (unchanged):** `loop_delivery_service.py` (the only sender — 10D adds enrichment + a route, no second send path), `severity_model.py` (the canonical ladder), `morning_brief_service.py` (extended with one appended section), `digest_batches` repo (portfolio digests reuse it), `loop_producers.py` (the loop tick hosts the new producer).

**Boundary rules (enforced in review):**
1. **No new company-level intelligence.** Exposure and health services may only *read and aggregate* `cross_exposures`/`dossier_*`/`MacroSensitivity`. A portfolio service importing the synthesis/LLM path is a release blocker (the §0 principle #1 imperative; grep gate in Slice 5).
2. **One prose source.** `portfolio_insight_templates` is the *only* producer of insight text. Free-form generation anywhere in 10D is a release blocker (§6.2).
3. **The delivery service is still the only sender.** Generation, ranking, and templating decide and package; only `loop_delivery_service.flush()` emits. 10D adds no new sender.
4. **Health never forecasts.** The health service emits structural characterization only; any §4.5-prohibited metric is a release blocker (structural schema test in Slice 4).
5. **Every response carries the disclaimer.** The §6.3 `regulatory_disclaimer` is a backend responsibility on every portfolio response — absence is a release blocker (asserted in Slice 8 validator).

---

## PART 4 — VALIDATION PLAN

10D's correctness is *what it refuses to say*. Beyond mechanical correctness, the regulatory and insight-quality gates are the ones that decide the phase. Every metric below is exposed on `/admin/portfolio-status` (Slice 8) and asserted by `validate_10d_portfolio_shadow.py`.

### Regulatory checks (the defining gates)

| Check | Definition | Healthy | How measured |
|---|---|---|---|
| **Prohibited-language violations** | rendered insights containing any §6.2 prohibited term/pattern | **exactly 0** (release blocker) | `portfolio_regulatory_guard.vet` over every generated insight; violation counter on `/admin/portfolio-status` |
| **Disclaimer presence** | portfolio API responses carrying `regulatory_disclaimer` | **100%** | schema assertion over every `/portfolio/*` and `/admin/portfolio-status` response |
| **Forecast-field absence** | health responses containing a §4.5-prohibited field (volatility, beta, VaR, Sharpe, expected return, composite score) | **0 fields present** | structural schema test over the health/themes/regime responses |
| **Template-bound prose** | insight text originating outside the canonical template set | **0** (grep gate: no free-form generation import in portfolio services) | static analysis + the no-synthesis-import grep gate |

> **The regulatory SLA is the advancement gate.** 10C's gate was mute/unsubscribe flat-or-falling. 10D's defining gate is **zero prohibited-language violations and 100% disclaimer presence**. A portfolio layer with flawless mechanics but a single recommendation-shaped insight is a *failed* layer — it has crossed the line from intelligence into unlicensed advice. Non-negotiable, monitored continuously, and a hard release blocker at any non-zero violation count.

### Correctness checks

| Check | Definition | Healthy | How measured |
|---|---|---|---|
| **Position idempotency** | re-adding a ticker to a portfolio | reactivates, never duplicates | `UNIQUE(portfolio_id, ticker)`; re-add test |
| **Watchlist-mirror fidelity** | default-portfolio `watchlist` positions vs. active `watched_tickers` | exact match after sync; manual positions untouched | Slice 2 sync test |
| **Projection correctness** | clusters vs. hand-computed `cross_exposures` subgraph | exact membership match; empty on no shared edges | Slice 3 integration |
| **Insight dedup** | distinct insights with identical `content_key` | **0** (7-day bucket; >5pp weight change re-keys) | `UNIQUE(content_key)` on `portfolio_insights` |
| **Enrichment non-mutation** | `content_key` of an enriched vs. non-enriched alert | identical (enrichment is additive) | Slice 7 unit (the §5.2 no-double-send property) |
| **HHI / effective-N** | concentration math on a known weighted portfolio | matches hand-computed values; NULL when weightless | Slice 4 unit |

### Insight-quality checks

| Check | Definition | Healthy | How measured |
|---|---|---|---|
| **Ranking discrimination** | high-weight-cluster insight vs. low-weight-cluster of equal severity | high-weight ranks above (§0 principle #4) | Slice 6 unit |
| **Rank non-degeneracy** | `rank_score` distribution over a synthetic batch | not all-equal, not all-max | shadow integration (the 10C anti-degeneracy check) |
| **Severity sanity** | canonical-severity histogram over insights | non-degenerate; CRITICAL a small tail, not the mode | `/admin/portfolio-status` histogram |
| **Sparsity graceful degradation** | a portfolio with no shared edges | empty insight list, no error | Slice 3 + Slice 5 |
| **Staleness cap** | an insight built on `stale_input` edges | severity capped at MEDIUM | Slice 5 unit |
| **Novelty suppression** | a just-delivered insight re-evaluated within 7d | novelty factor 0.3, dedup blocks re-send | Slice 6 + §3.4 |

### Test harness

- **Unit** (in-memory SQLite, CI): portfolio CRUD + position idempotency (Slice 1); watchlist mirror (Slice 2); projection/cluster math (Slice 3); HHI/health + forecast-field-absence (Slice 4); template regulatory-guard battery + intentional-violation catch (Slice 5); ranking discrimination (Slice 6); enrichment non-mutation (Slice 7).
- **Integration** (Postgres test DB, existing `pytest.ini`/`conftest.py`): seeded-portfolio projection vs. hand-computed clusters; full synthetic loop tick → insight generation → ranking → shadow delivery; disclaimer presence across every endpoint.
- **Shadow validation** (`validate_10d_portfolio_shadow.py`, staging): regulatory violations = 0, disclaimer 100%, no forecast fields, projection non-degenerate, insights template-bound, severity canonical, `safe_state=true`. Exit 0 gates the internal stage.
- **The standing invariant:** prohibited-language violations = 0 and disclaimer presence = 100% are **release blockers** at any deviation, the regulatory analogue of 10A's duplicate-delivery=0.

---

## PART 5 — ROLLOUT SEQUENCE

Reuses the 10C delivery flags + the 10A/9G cohort + kill switch **unchanged**, adding exactly one 10D flag (`portfolio_insights_shadow`). 10D is the fourth customer of the canary infra; it adds no rollout machinery. Each stage defines **advance / hold / rollback** explicitly.

### Shadow stage
**Config:** `portfolio_insights_shadow=True`, `delivery_in_app_enabled=false`, `delivery_shadow=true` (where 10C left production — safe state).
**Behavior:** model portfolios, project exposure, generate + rank + template-vet insights, enrich briefings, write `portfolio_insights` rows — **zero sends** (everything flows into `delivered_shadow`).
- **Advance when (all, sustained 72h):** regulatory violations = 0 (the defining gate); disclaimer presence = 100%; zero §4.5-prohibited fields in any health response; projection non-degenerate; ranking non-degenerate; insight dedup = 0 duplicates under forced double-driver + redeploy; `validate_10d_portfolio_shadow.py` exits 0; zero unhandled exceptions in the portfolio path; `validate_10c_delivery_shadow.py` still green (no 10C regression).
- **Hold when:** any prohibited-language violation; any missing disclaimer; any forecast field leaking into health; degenerate projection/ranking; a watchlist-mirror write to `watched_tickers`.
- **Rollback:** none needed — shadow reaches no user. Revert the offending slice; production stays at 10C safe state.

### Internal stage
**Config:** `portfolio_insights_shadow=False`, `delivery_in_app_enabled=true`, `delivery_shadow=false`, `delivery_internal_only=true`, `LOOP_INTERNAL_USER_IDS=<team>`.
**Behavior:** real portfolio insights + enriched briefings delivered to the named internal set only.
- **Advance when:** team runs real portfolios for **7 consecutive days** — insights read as structural observations (never advice), cadence feels right, the briefing portfolio section is useful and not noise, digests readable; all guardrails verified end-to-end (severity floor, quiet hours, cap → digest, dedup); **zero prohibited-language reports** from the team reading live insights; **zero duplicate** portfolio notifications in the inbox over the week; delivery success rate ≥ target.
- **Hold when:** any insight reads as a recommendation; any missing disclaimer in the live UI; a guardrail bypassed; any duplicate inbox row.
- **Rollback:** `portfolio_insights_shadow=True` — instant halt of portfolio sends, generation continues, rows bank as `delivered_shadow`. Or `POST /admin/loop/disable` (runtime, no redeploy — halts the loop tick that drives generation).

### Canary stage
**Config:** `delivery_internal_only=false`, `delivery_canary_pct=1` (CRC32 on `user_id` via the reused `loop_canary_cohort`; permanent holdout; the same 1% S0 dwell posture the loop uses).
**Behavior:** ~1% receive real portfolio insights; a held-out arm never does (the comparison group).
- **Advance when (sustained 72h or ≥200 delivered insights, whichever later):** regulatory violations = 0 (continuous); disclaimer presence = 100%; mute/unsubscribe on portfolio insights below threshold AND flat-or-falling (inheriting 10C's fatigue SLA for the new artifact class); insight dedup = 0; delivery success ≥ target; cost/cycle linear in cohort size; no regression to `/ask` latency or the running loop.
- **Hold when:** any regulatory violation; mute/unsubscribe rising on portfolio insights; cost super-linear; dedup slipping.
- **Rollback:** `delivery_canary_pct=0` (cohort reverts to shadow) or `portfolio_insights_shadow=True` (portfolio-specific halt, leaves 10C company alerts live) or `POST /admin/loop/disable` (instant, system-wide).

### Ramp
**Config:** `delivery_canary_pct: 1 → 5 → 25 → 50 → 95` (hold a permanent holdout).
- **Advance (each step dwells until met):** all canary-stage gates still green at the larger N; **regulatory violations = 0** and **fatigue flat-or-falling** at the new exposure; cost linear in cohort size; delivery latency + loop lag flat (no scaling cliff); insight dedup = 0.
- **Hold when:** any regulatory violation at the new N; any fatigue metric rises; cost super-linear; latency/lag spikes.
- **Rollback:** drop `delivery_canary_pct` to the last-green step or to 0; `portfolio_insights_shadow=True` for a portfolio-only halt; `POST /admin/loop/disable` for instant full halt. The kill switch stops *delivery*, never *generation* — flipping off and back on never loses or duplicates insights (the `content_key` dedup absorbs the resume).

> The holdout is **permanent** post-GA — the standing control arm for measuring 10D's effect on engagement and fatigue, exactly as the loop, dossier, and 10C delivery retain theirs. `portfolio_insights_shadow` is the unique 10D lever: it can halt the portfolio layer alone without touching live 10C company alerts — a finer-grained kill switch than 10C had.

---

## PART 6 — DEPENDENCIES

### Dependencies on 10A (the loop & rollout spine — already shipped)
- **The loop tick** (`loop_producers.py` / `watchlist_scan`) — 10D's insight producer rides the existing tick; when a scan writes a dossier update, the portfolio layer re-evaluates affected portfolios. **No new cron** (spec §3.2).
- **The canary cohort + kill switch** (`loop_canary_cohort.py`, `loop_canary_telemetry.py`) — reused unchanged for 10D's portfolio-insight rollout; `POST /admin/loop/disable` halts generation system-wide.
- **The flag substrate** (`delivery_*`, `LOOP_INTERNAL_USER_IDS`, `delivery_canary_pct`) — 10D's rollout is a config sequence over flags 10A/10C already defined, plus the single new `portfolio_insights_shadow`.

### Dependencies on 10B (the watchlist substrate — already shipped)
- **`watched_tickers`** — the Slice 2 default-portfolio mirror reads it as the seed for `watchlist`-class positions; `watched_tickers` remains source of truth (read-only projection).
- **The idempotent startup-backfill pattern** (the existing 10B `watched_tickers` block in `main.py` lifespan) — the precedent for the Slice 2 `sync_watchlist_positions` startup call.

### Dependencies on 10C (the delivery spine — already shipped, validated 2026-06-13)
- **`delivery_ledger` + `notifications` + `content_key` dedup** — portfolio insights route *into* this ledger as a new artifact class; `artifact_ref` points at `portfolio_insights.id`, `kind="portfolio_alert"` (additive enum value, no migration).
- **`loop_delivery_service.flush()` + the single guardrail boundary** (quiet hours / daily cap / mute / severity floor / per-user prefs) — 10D adds enrichment and one route at this single chokepoint; it adds no second send path. The regulatory guard sits at generation; the delivery guard stays exactly where 10C put it.
- **`severity_model.py` — the canonical ladder** — 10D stamps insight severity with the existing `to_canonical`/`severity_rank`; no new vocabulary (the §3.2 reconciliation is inherited, not rebuilt).
- **`digest_batches` + the digest builder** — portfolio digests reuse the 10C table and coalescing with a 7-day `period_bucket` (no schema change).
- **`morning_brief_service.generate_morning_brief_v2`** — the §5.3 portfolio section is appended to the existing briefing; existing sections unchanged.
- **The shadow posture + `/admin/delivery-status` observability pattern** — `/admin/portfolio-status` and `validate_10d_portfolio_shadow.py` mirror the 10C Slice 10 artifacts (`build_delivery_snapshot`, `validate_10c_delivery_shadow.py`) including the null-object/never-raise discipline and the inline-handler test pattern for the Python 3.9 import constraint.

### Dependencies on 9G (the dossier graph — the only analytical input)
- **`cross_exposures`** — the entire exposure-projection layer reads this graph; 10D never writes it (read-only, no FK).
- **`company_dossier` + `dossier_catalyst` + `dossier_failure_mode`** — catalyst propagation (§2.3) and failure contagion (§2.4) read these facets; coverage-gap insights flag tickers without a dossier.
- **`MacroSensitivity`** — the regime-sensitivity health metric (§4.4) aggregates per-company sensitivities; 10D never recomputes them.

> **The contract in one line:** after 10D, every portfolio insight is *"aggregate an existing dossier/cross-exposure fact, render it through a vetted template, rank it by portfolio weight, route it through the one 10C boundary, and let the canary govern exposure"* — the model, projection, regulatory boundary, and rollout ladder are solved once, here. 10D introduces zero new company-level intelligence and zero new delivery path.

---

## PART 7 — IMPLEMENTATION ORDER

Sequenced so user-facing and **regulatory** risk is monotonically bounded; every week ends shippable and revertible, and nothing reaches an external user until the internal stage in Week 4.

**Week 1 — Model & mirror (no intelligence)**
- Days 1–2: Slice 1 (migration `008` + models + CRUD, table count 28→31) → deploy. Portfolios and positions exist; nothing is computed.
- Days 3–4: Slice 2 (default-portfolio watchlist mirror, startup sync) → deploy. Every existing user has a populated default portfolio, read-projected from `watched_tickers`.
- Day 5: Slice 3 (cross-exposure projection, read-only endpoint) → deploy dark. Clusters compute; nothing consumes them.

**Week 2 — Health & generation (shadow, regulatory boundary load-bearing)**
- Days 1–2: Slice 4 (health metrics + forecast-field-absence gate) → deploy. The §4.5 exclusions are structurally enforced from this point.
- Days 3–5: Slice 5 (template-bound insight generation + regulatory guard) → deploy in shadow. **Gate:** the regulatory battery passes (zero prohibited-language hits) and the intentional-violation test catches. This is the load-bearing regulatory slice.

**Week 3 — Ranking, delivery integration & observability (still shadow)**
- Days 1–2: Slice 6 (portfolio-relevance ranking) → deploy. Confirm ranking discrimination + non-degeneracy on the synthetic batch.
- Days 3–4: Slice 7 (briefing section, alert enrichment, standalone routing, digest coalescing) → deploy in shadow. Confirm enrichment never mutates `content_key`.
- Day 5: Slice 8 (`/admin/portfolio-status` + `validate_10d_portfolio_shadow.py`). **Gate:** shadow validator exits 0; regulatory violations = 0; disclaimer presence = 100%.

**Week 4 — Internal stage & the consequential flip**
- Days 1–2: confirm all shadow-stage advancement criteria sustained 72h (PART 5).
- Day 3: **Internal stage** — `portfolio_insights_shadow=False`, `delivery_internal_only=true`, team user_ids. Run real portfolios; read your own insights.
- Days 4–5: live for the team; verify insights read as observations (never advice), disclaimer present in the UI, cadence, zero duplicates. **Rollback at any sign = `portfolio_insights_shadow=True` or `POST /admin/loop/disable`, instant.**

**Week 5 — Canary & ramp**
- Internal stage completes its 7-day soak (spanning into Week 5 as needed).
- 1% canary → ramp 1→5→25→50→95 per PART 5 gates, dwelling at each step on the **regulatory SLA** (violations = 0, disclaimer 100%) *and* the inherited fatigue SLA (mute/unsubscribe flat-or-falling). Hold the holdout permanently.

**Standing rule:** flags are independent and layered — `portfolio_insights_shadow` (10D-only no-send), `delivery_internal_only` (named set), `delivery_canary_pct` (exposure). Generation and ranking run for weeks with sends off; portfolio sends can be killed without touching 10C company alerts (the finer-grained lever) and without losing generated insights (they bank as `delivered_shadow`/`pending`, and `content_key` dedup absorbs any resume). 10D's dataset only ever grows under governed, idempotent, template-vetted writes.

---

## DELIVERABLE SUMMARY

1. **Build slices:** 9 (PART 1) — model+CRUD → watchlist-mirror → exposure-projection → health-metrics → template-bound-generation+regulatory-guard → relevance-ranking → delivery-integration → observability/validator. Each with objective, files, dependencies, validation, rollback. All land with `portfolio_insights_shadow=True`.
2. **Portfolio intelligence sequence:** portfolio model → holdings (positions + watchlist mirror) → exposure projection → insight generation → health metrics → delivery integration — exactly the §3 build order, each gated before the next.
3. **Database plan:** 3 new tables (`portfolios`, `portfolio_positions`, `portfolio_insights`), single migration `008_portfolio_intelligence.sql`, idempotent, startup-registered, table count 28→31, **no `ALTER` on any existing table** (the `notifications.kind` extension is a new enum value), rollback = shadow flag stays True (PART 2).
4. **Validation plan:** regulatory checks (prohibited-language violations = 0, disclaimer presence = 100%, zero forecast fields, template-bound prose) as the defining gates; plus correctness checks (position/mirror idempotency, projection fidelity, insight dedup, enrichment non-mutation, HHI math) and insight-quality checks (ranking discrimination, non-degeneracy, sparsity degradation, staleness cap, novelty suppression) — each measurable on `/admin/portfolio-status` and asserted by `validate_10d_portfolio_shadow.py` (PART 4).
5. **Rollout gates:** advance / hold / rollback stated explicitly per stage; the regulatory SLA (violations = 0, disclaimer 100%) is the advancement gate and a standing release blocker; `portfolio_insights_shadow` is the unique finer-grained kill switch (halts the portfolio layer alone); the loop kill switch is the instant system-wide rollback (PART 5).
6. **Dependencies:** the exact contracts 10D consumes from 10A (loop tick + canary + flags), 10B (`watched_tickers` mirror + startup-backfill pattern), 10C (delivery ledger + single guardrail boundary + `severity_model` + digest + briefing + observability pattern), and 9G (`cross_exposures` + dossier facets + `MacroSensitivity` as the only analytical inputs) (PART 6).
7. **Production rollout:** 5 weeks, dark-deploy the model then layered flag-flips; model+mirror Week 1, health+generation Week 2, ranking+delivery+observability Week 3, first internal users Week 4, canary/ramp Week 5; the `portfolio_insights_shadow` flag and the loop kill switch revertible at all times (PART 7).

*End of implementation plan. No code, no migrations, no implementation in this document — execution may begin immediately against it. 10D builds the layer that reasons across a portfolio while never crossing from intelligence into advice: every insight is an existing fact, aggregated, vetted by template, and routed through the one delivery boundary 10C already proved.*
