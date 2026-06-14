# Portfolio Intelligence — Architecture Specification

**Phase:** 10D · the portfolio layer
**Status:** Design — not yet implemented
**Audience:** Principal/staff engineers, backend, product
**Scope:** Design only. No code, no migrations, no implementation in this document.
**Prerequisite reads:** `COMPANY_DOSSIER_SPEC.md` (the company-level intelligence object this layer reads), `PHASE_10C_BRIEFING_AND_DELIVERY_SPEC.md` (the delivery channel this layer rides on), `PHASE_10A_LOOP_SPEC.md` (the heartbeat).

---

## 0. Purpose and one-paragraph thesis

ClearSignal can, as of Phase 10C, do four things well: understand a company's permanent character (dossier), track how views evolve over time (thesis versions + deltas), scan a watchlist for drift (10B), and deliver signals when something material changes (10C). What it cannot do is reason **across** the watchlist — to know that three holdings share a common macro exposure, that adding a fourth concentrates an already-crowded thematic bet, or that a HIGH-severity dossier update on NVDA is more urgent to a user who also holds AMD and MSFT than it would be to someone who doesn't. The system today treats every ticker as an island. Phase 10D builds the bridge.

**Phase 10D transforms ClearSignal from a company-intelligence engine into a portfolio-intelligence engine.** It introduces a Portfolio Model that describes *which companies a user holds or watches*, a Cross-Exposure Intelligence layer that surfaces shared risks across that portfolio, a Portfolio Health lens that characterizes concentration and thematic exposure without forecasting returns, and a Portfolio Insights layer that turns raw cross-exposure into ranked, actionable narratives. Every layer sits **above** the existing dossier and delivery stack — no Phase 1–10C logic is modified. 10D adds projections; it does not change the foundation.

> **Design principle #1 — No new analytical ground truth.** Every insight 10D surfaces is a *combination* of facts already captured in company dossiers, cross_exposures, and thesis versions. 10D does not run new LLM calls to synthesize novel company-level analysis. It aggregates, correlates, and ranks what Phase 9G already knows. The moment 10D claims to know something about a company that the dossier does not, it has broken this principle.

> **Design principle #2 — Portfolio insights describe exposure, not outcome.** 10D identifies that a user's portfolio has concentrated semiconductor exposure across four holdings. It does not predict whether semiconductors will go up or down. It does not recommend buying or selling anything. The insight is a *structural observation*, not a forecast. See §6 (Regulatory Boundary) for the normative list of what must never be generated.

> **Design principle #3 — The portfolio is user-authored; the intelligence is system-derived.** The user declares what they hold or watch. The system derives what it means for those holdings to coexist. 10D never infers ownership from trading patterns, session history, or search behavior. Portfolio membership is always an explicit user action.

> **Design principle #4 — Insights are ranked by portfolio relevance, not by company importance.** A CRITICAL-severity dossier update on a ticker the user owns at 30% weight is more urgent than a CRITICAL update on a ticker they hold at 2%. 10D's ranking layer applies portfolio context to severity labels; the severity label alone is not sufficient for portfolio-level prioritization.

---

## 1. Portfolio Model

### 1.1 Conceptual shape

A **Portfolio** is a named, user-owned collection of positions. Each position identifies a ticker, an optional weight or cost-basis, a membership class, and lifecycle metadata.

```
Portfolio(user_id, portfolio_id)
  name              — user-facing label ("My Tech Overweight", "Core Holdings")
  description       — optional free text
  created_at / updated_at
  positions[]       — ordered list of PortfolioPosition

PortfolioPosition(portfolio_id, ticker)
  membership_class  — owned | watchlist | on_radar
  weight            — optional float 0.0–1.0 (portfolio weight; does not need to sum to 1.0)
  cost_basis        — optional float (per share, user-supplied; never fetched from external APIs)
  shares            — optional float (share count)
  notes             — optional free text (user-annotated thesis notes)
  added_at / updated_at
  active            — bool (soft-delete; removing from portfolio sets active=False)
```

**Membership class semantics:**

| Class | Meaning | Portfolio health weight | Cross-exposure scope |
|---|---|---|---|
| `owned` | Position held in a brokerage account | Full | Full |
| `watchlist` | On the existing WatchedTicker watchlist, not yet owned | Fractional (configurable, default 0.5×) | Full |
| `on_radar` | Tracking but not on watchlist | Zero | Read-only (insight visibility, not health) |

The `watchlist` class bridges Phase 10B's `watched_tickers` table: a WatchedTicker with `active=True` is automatically reflected as a `watchlist`-class position in the default portfolio. This is a **read projection**, not a migration — `watched_tickers` remains the source of truth for the watchlist; the portfolio layer reads from it.

### 1.2 Multi-portfolio model

Each user may have **one or more named portfolios**. A ticker can appear in multiple portfolios with different weights (e.g., a company might be 5% of a "diversified core" portfolio and 15% of a "high-conviction ideas" portfolio). Portfolio health and cross-exposure are computed **per portfolio**, not globally.

A **default portfolio** is created implicitly when the user's first WatchedTicker row is written. It starts as a pure mirror of the watchlist (`membership_class=watchlist` for all active tickers, `weight=null`). The user can rename it, add positions with explicit weights, and create additional portfolios alongside it. The default portfolio's watchlist-class positions remain auto-synced; manual additions are not auto-synced.

### 1.3 What the portfolio model does NOT include

- Real-time market data, current prices, or current market values. Cost basis and shares are user-entered; 10D never computes a portfolio market value.
- Tax lots, wash-sale tracking, or realized/unrealized gain calculation.
- Benchmark comparisons (alpha vs. S&P 500, etc.).
- Suggestions for which securities to buy or sell.
- Any inferred holdings from behavior (search queries, session history, etc.).

---

## 2. Cross-Exposure Intelligence

### 2.1 What cross-exposure means in this context

The existing `CrossExposure` table (Phase 9B) already captures pairwise ticker relationships: `(ticker_a, ticker_b, exposure_type, strength, shared_concerns)`. 10D's Cross-Exposure Intelligence layer does not rebuild this from scratch. It **projects the CrossExposure graph onto a specific portfolio** — selecting only edges where *both* endpoints are positions in that portfolio — and derives aggregate exposure signals from the resulting subgraph.

### 2.2 Exposure aggregation model

For a given portfolio, the cross-exposure subgraph produces three aggregate signals:

**A. Shared risk clusters.** A cluster is a set of portfolio positions that share a `shared_concern` (from their pairwise CrossExposure rows). For each concern label appearing in two or more edges, the cluster is:

```
SharedRiskCluster
  concern_label     — string (e.g. "AI capex cycle", "rising rates", "China demand")
  member_tickers[]  — list of tickers sharing this concern
  cluster_weight    — sum of portfolio weights for member positions (null if no weights set)
  severity_ceiling  — highest canonical_severity among active dossier states for members
  exposure_type     — dominant exposure_type across edges in the cluster
```

**B. Hidden correlations.** Pairs of positions with `strength >= 0.7` (the "high-correlation" threshold, tunable) that the user may not recognize as related — e.g., a semiconductor equipment company and a cloud provider connected through AI-infrastructure capex. These are surfaced as `CorrelationAlert` objects.

**C. Concentration risk.** Positions where a single ticker's weight exceeds a concentration threshold (default: 20% of portfolio), and clusters where a single `shared_concern` covers more than 40% of portfolio weight. See §4 (Portfolio Health) for the metrics layer.

### 2.3 Catalyst propagation

When a new dossier catalyst is written (via `DossierCatalyst` upsert), 10D checks whether any catalyst's `trigger_label` matches shared concerns in existing CrossExposure edges for that ticker. If it does, the catalyst is **propagated** to the connected positions as a `PropagatedCatalyst` signal, tagged with the edge that carried it.

This propagation is **read-only observation**, not dossier modification. The propagated catalyst is surfaced as a portfolio insight (§3), not written back into any peer company's dossier.

### 2.4 Failure mode contagion

When a `DossierFailureMode` is activated for a ticker (i.e., an analog match fires and the failure mode is marked `active=True`), 10D checks for peer positions sharing the same `failure_category`. Peers are alerted via a `FailureModeContagion` portfolio insight. The insight cites both the triggering ticker and the failure category; it does not assert that the peer will fail.

### 2.5 Data freshness contract

Cross-exposure insights are only as fresh as the underlying `cross_exposures` and `company_dossier` rows. 10D exposes a `cross_exposure_as_of` timestamp on every portfolio insight, defined as the `min(updated_at)` across all CrossExposure edges contributing to that insight. If the staleness exceeds a configurable threshold (default: 7 days), the insight is tagged `stale_input` and its severity is capped at MEDIUM until the edge is refreshed.

---

## 3. Portfolio Insights

### 3.1 Insight taxonomy

Portfolio insights are **derived artifacts** — they combine signals from two or more positions to produce a statement that is true only in the context of a specific portfolio. They are not company-level insights (those live in the dossier and in 10A/10C alerts). They are not predictions (see §6). They are structured observations about the portfolio as a whole or about relationships within it.

The Phase 10D insight taxonomy is **closed** (mirroring the 10C delivery taxonomy):

| Insight type | Trigger | Severity ceiling |
|---|---|---|
| `concentration_breach` | Single position weight > threshold | HIGH |
| `cluster_concentration` | Single concern covers > threshold of portfolio weight | HIGH |
| `high_correlation_pair` | Pairwise `strength >= 0.7` between owned positions | MEDIUM |
| `propagated_catalyst` | Catalyst on position A propagates to position B via shared concern | Inherits from source catalyst (capped MEDIUM) |
| `failure_contagion` | Failure mode fires on position A; position B shares failure category | HIGH |
| `macro_sensitivity_cluster` | Multiple positions share a MacroSensitivity regime factor | MEDIUM |
| `thesis_divergence` | Two positions have opposing stances (`Accumulate` vs. `Avoid/Reduce`) on a shared concern | LOW |
| `coverage_gap` | Portfolio position has no active dossier (no Phase 9G coverage) | INFO |

No new insight types may be added without a spec amendment. A fourth-party signal that doesn't map to one of these types does not become a portfolio insight — it surfaces as a raw data point in the portfolio health view, not an actionable insight.

### 3.2 Insight generation lifecycle

```
[Cross-Exposure Refresh] → [Cluster Detector] → [Insight Candidates]
                                                        ↓
                                          [Portfolio Ranker (§3.3)]
                                                        ↓
                                      [Regulatory Guard (§6 filter)]
                                                        ↓
                                          [Delivery Router (§5)]
```

Generation is **triggered by**, not scheduled independently of, the existing 10A loop tick. When the loop tick fires a `watchlist_scan` that produces a dossier update or thesis delta, the portfolio layer re-evaluates all insights that reference the updated ticker. This keeps portfolio insight freshness locked to the company intelligence freshness; no separate cron is needed.

### 3.3 Insight ranking framework

Portfolio insights compete for delivery attention against each other and against company-level alerts. The ranking score for a portfolio insight is:

```
rank_score = base_severity_score
           × portfolio_weight_factor
           × novelty_factor
           × recency_factor
```

**base_severity_score**: Canonical severity mapped to numeric value (`CRITICAL=4, HIGH=3, MEDIUM=2, LOW=1, INFO=0`), per the existing `severity_model.py`.

**portfolio_weight_factor**: `1.0 + (cluster_weight / total_portfolio_weight)`. A cluster covering 60% of portfolio weight gets a 1.6× multiplier. A cluster with `weight=null` (no weights set) uses a fallback of 1.0.

**novelty_factor**: `1.0` if this insight has never been delivered to this user; `0.8` if delivered > 7 days ago; `0.3` if delivered in the last 7 days (suppresses re-alerting on stable concentrations).

**recency_factor**: `1.0` if the triggering dossier update is < 24h old; decays linearly to `0.5` at 7 days.

The final rank score is a float. Insights are sorted descending by rank score before routing through the delivery boundary (§5).

### 3.4 Insight deduplication

Portfolio insights share the same `content_key` dedup mechanism as company-level alerts (10A §3.4 / 10C §3.2):

```
content_key = sha256(portfolio_id + insight_type + cluster_label + period_bucket)
```

`period_bucket` is a 7-day bucket (not 24h, because portfolio insights are inherently slower-moving than company-level alerts). A `concentration_breach` on the same ticker in the same portfolio does not re-deliver within the same 7-day window unless the weight has changed by more than 5 percentage points.

### 3.5 Example insights (illustrative, non-normative)

These examples show what a correctly generated insight looks like. They are not templates to be copied verbatim.

> **CLUSTER CONCENTRATION — HIGH** `[AI infrastructure capex]`
> Four of your holdings (NVDA 22%, MSFT 15%, AMD 8%, TSMC 6%) share an *AI infrastructure capex* exposure through semiconductor supply chain. Combined weight: 51%. A capex digestion cycle affecting this cluster would hit over half your portfolio.

> **FAILURE CONTAGION — HIGH** `[regulatory fragmentation]`
> A *regulatory fragmentation* failure mode is now active for GOOGL (analog: EU antitrust 2017). Your portfolio also holds META and AMZN, which share the *regulatory fragmentation* failure category. The failure mode is not asserted for META or AMZN; this is a shared structural vulnerability alert.

> **THESIS DIVERGENCE — LOW** `[China demand]`
> AAPL (stance: Accumulate, conviction 0.78) and NKE (stance: Reduce, conviction 0.71) have opposing stances on *China demand* as a thesis driver. This is a portfolio-level tension, not a conflict — both stances may be correct for their respective companies.

---

## 4. Portfolio Health

### 4.1 What portfolio health is

Portfolio health is a set of **structural characterization metrics** that describe the portfolio's current composition. It answers questions like "how concentrated is this portfolio?" and "what thematic exposures are we running?" without making any prediction about what those characteristics mean for future returns.

Health metrics are computed on demand (for the portfolio health view) and periodically (as inputs to insight generation). They are not stored as a single health score — a single number would compress too much nuance and would imply a forecast.

### 4.2 Concentration metrics

**Position concentration (Herfindahl-Hirschman Index, HHI):** When weights are provided, compute `HHI = Σ(weight_i²)`. HHI is provided as a raw number (0–1), not interpreted as "good" or "bad." The UI may show a reference band (e.g., "equal-weight 20-position portfolio → HHI ≈ 0.05") for context, never as a target.

**Top-N concentration:** What fraction of portfolio weight is in the top 3, top 5, top 10 positions? Shown only when weights are provided.

**Single-position cap breach:** Positions exceeding the user's configured `max_single_position_pct` (default: 20%, configurable). Flagged as INFO; never as a recommendation to reduce.

**Effective N (diversification number):** `1/HHI`, rounded to one decimal. Interpretable as "the portfolio behaves like a portfolio of N equal-weight positions." Shown for reference.

### 4.3 Thematic exposure metrics

Using the `cluster_weight` values from §2.2, thematic exposure summarizes the portfolio's concentration in macro-thematic buckets derived from `shared_concerns` labels:

```
ThematicExposure
  theme               — concern label (e.g. "AI infrastructure capex", "rising rates")
  tickers_in_theme[]  — tickers with this concern in their cross_exposures
  portfolio_weight    — sum of weights for those tickers (null if no weights)
  trend_direction     — direction most dossier stances point re: this theme (bull/bear/mixed)
  most_recent_update  — latest dossier updated_at among members
```

Themes are derived from existing `CrossExposure.shared_concerns` values — they are not a new taxonomy. The system does not create theme labels; it aggregates existing concern labels.

### 4.4 Regime sensitivity metrics

The existing `MacroSensitivity` schema (from dossier construction) identifies each company's sensitivity to macro regime factors (e.g., interest rate direction, USD strength, credit spread widening). Portfolio regime sensitivity aggregates these per-company sensitivities into a portfolio-level view:

```
RegimeSensitivity
  regime_factor       — e.g. "rising rates", "USD strengthening"
  exposed_tickers[]   — portfolio positions flagged sensitive to this factor
  portfolio_weight    — cluster weight
  sensitivity_sign    — positive (helped by regime) / negative (hurt) / mixed
```

When a dossier update for any portfolio position changes a `MacroSensitivity` value, the portfolio-level `RegimeSensitivity` view is recomputed at the next loop tick.

### 4.5 What portfolio health does NOT compute

- Portfolio volatility, beta, or correlation with any index.
- Value at risk, drawdown, or any metric requiring price history.
- Expected return for any time horizon.
- Sharpe, Sortino, or any risk-adjusted return metric.
- Any metric that requires real-time or historical price data.
- A single "health score" or "portfolio rating."

These exclusions are normative. The system may display them as "not available" or simply omit the section when insufficient data is present, but it must never estimate or proxy them using non-price data.

---

## 5. Delivery Integration

### 5.1 Portfolio insights as first-class delivery artifacts

Portfolio insights are delivered through the same delivery pipeline as company-level alerts (10C). They are a new *artifact class* — added to the existing taxonomy alongside Daily Briefing, Alert, and Digest — not a new delivery channel. The delivery boundary (dedup, quiet hours, daily cap, severity floor) applies unchanged.

The delivery ledger `artifact_ref` for a portfolio insight points to a `portfolio_insights` row (§5.4), not to a `briefing_sessions` row or a `dossier_revision` row.

### 5.2 Watchlist alerts — portfolio context enrichment

When the 10C delivery pipeline generates a company-level alert (e.g., "NVDA dossier updated, severity HIGH"), the portfolio layer **enriches** the alert before delivery if the recipient's portfolio contains related positions. Enrichment adds a `portfolio_context` block to the notification body:

```json
{
  "portfolio_context": {
    "portfolio_name": "Core Holdings",
    "position_weight": 0.22,
    "cluster": {
      "concern": "AI infrastructure capex",
      "peer_tickers": ["MSFT", "AMD", "TSMC"],
      "cluster_weight": 0.51
    }
  }
}
```

Enrichment is additive — it does not change the alert's severity or content key. A non-enriched and an enriched delivery of the same alert have the same `content_key`; the dedup applies before enrichment.

### 5.3 Daily briefing — portfolio intelligence section

When `morning_brief_service` generates the daily briefing, it calls a new `portfolio_intelligence_section()` helper that:

1. Pulls the user's default portfolio.
2. Runs the cluster detector (§2.2) against the current cross_exposures + dossier states.
3. Ranks the top N portfolio insights (N=3 by default, configurable via settings).
4. Returns a structured section with those insights for inclusion in the briefing.

The briefing's existing sections (executive summary, watchlist scan, sector pulse, macro context) are unchanged. The portfolio intelligence section is appended *after* the existing watchlist scan section. If no portfolio insights are above INFO severity, the section is omitted — the briefing does not pad with low-value portfolio content.

### 5.4 Standalone portfolio insight notifications

Portfolio insights with severity MEDIUM or above that are triggered by a real-time dossier update (not the daily brief cycle) are eligible for standalone delivery via the 10C alert path. The trigger is:

1. A `company_dossier` or `dossier_revision` update fires for a ticker.
2. The loop tick re-evaluates portfolio insights referencing that ticker.
3. A new or changed portfolio insight ranks above the delivery floor.
4. The insight is not deduped (content_key not in delivery_ledger).
5. The insight is routed through the 10C delivery boundary (severity check, quiet hours, cap).

Standalone portfolio notifications use `kind="portfolio_alert"` in the `Notification` table (new kind value, additive).

### 5.5 Inbox experience

In the in-app inbox, portfolio insights and company alerts are interleaved in a single unified feed, sorted by delivery time. The UI distinguishes them by `kind`: `"portfolio_alert"` vs. `"watchlist_alert"` vs. `"daily_brief"`. The backend provides `kind` on every `Notification` row; the frontend routes display based on it. 10D defines no new backend inbox API surface — the existing `/delivery/inbox` and `/delivery/preferences` endpoints serve portfolio insights without change.

### 5.6 Portfolio digest

When portfolio insights accumulate and would breach the daily cap, they are coalesced into a Portfolio Digest using the same 10C `DigestBatch` mechanism. The digest's `period_bucket` uses a 7-day window (matching the portfolio insight dedup window in §3.4). A digest consolidates all MEDIUM and below portfolio insights into a single "here's what shifted in your portfolio this week" notification.

---

## 6. Regulatory Boundary

### 6.1 What ClearSignal is

ClearSignal is an **intelligence and awareness tool**. It observes, characterizes, and surfaces structural observations about companies and portfolios. It is not a registered investment advisor, broker-dealer, or financial planner. Nothing it generates constitutes investment advice, a recommendation to buy or sell a security, or personalized financial guidance.

### 6.2 What may never be generated

The following classes of output are **categorically prohibited** in Phase 10D and all future phases. They are not currently prohibited for technical reasons; they are prohibited because generating them would constitute investment advice, which this system is not authorized to provide.

| Prohibited output | Example | Rationale |
|---|---|---|
| Buy / sell / hold recommendations | "You should sell NVDA" | Direct investment advice |
| Price targets or return forecasts | "NVDA has 30% upside" | Price prediction |
| Optimal weight suggestions | "Reduce NVDA to 15% to rebalance" | Portfolio prescription |
| Risk-adjusted return comparisons | "MSFT has better risk/reward than AMD" | Comparative investment advice |
| Tax advice | "Harvest this loss before year-end" | Regulated tax advice |
| Margin or leverage recommendations | "Use options to hedge this concentration" | Regulated financial advice |
| Rebalancing triggers | "Your semiconductor weight has exceeded optimal levels" | Implicit sell recommendation |
| Statements about what concentration means for performance | "This concentration will hurt you in a downturn" | Return forecast |

**Enforcement mechanism:** Every portfolio insight text is generated from a closed template set. Templates are reviewed at spec-time for regulatory compliance. Free-form LLM generation of portfolio insight text is not permitted in 10D. Templates describe structural observations only ("Four holdings share X exposure; combined weight is Y%") and must not include opinion, forecast, or recommendation language. Any template that would require the word "should," "will," "expect," or "recommend" must be redesigned to remove those words.

### 6.3 Disclaimer infrastructure

All portfolio health views and portfolio insight notifications must carry a consistent, non-dismissible disclaimer at the API response level:

```json
{
  "regulatory_disclaimer": "Portfolio intelligence is for informational purposes only and does not constitute investment advice, a recommendation to buy or sell any security, or personalized financial guidance. ClearSignal is not a registered investment advisor."
}
```

This field is present on all portfolio-related API responses. It is the backend's responsibility, not the frontend's — a frontend that strips the disclaimer still served a response that contained it.

### 6.4 What is permitted

| Permitted output | Example |
|---|---|
| Structural characterization | "Four holdings share AI capex exposure; combined weight 51%" |
| Concern propagation | "NVDA's AI capex catalyst is also a concern for AMD and TSMC per cross-exposure records" |
| Concentration observation | "NVDA exceeds your configured 20% single-position cap" |
| Thesis state reporting | "Your NVDA dossier stance is Accumulate; your NKE stance is Reduce" |
| Failure mode alerting | "A regulatory fragmentation failure mode is active for GOOGL; META and AMZN share this category" |
| Staleness flagging | "TSMC dossier has not been updated in 14 days" |
| Coverage gap flagging | "BABA has no active dossier; cross-exposure insights are unavailable" |

---

## 7. Future Compatibility

### 7.1 Forecasting hooks (reserved, not implemented)

The Phase 10D portfolio model is designed to accommodate a future **Scenario Analysis** layer without schema changes. The `PortfolioPosition.weight` field is the entry point: a scenario engine could vary weights (or add hypothetical positions) and re-run the health and cross-exposure computations against the modified portfolio snapshot. This requires only a new service layer reading the existing schema — no new tables.

Reserved extension point: a `ScenarioSnapshot` object (not persisted in 10D) that holds a transient portfolio state against which insights and health metrics can be recomputed. Scenario snapshots are ephemeral — they are never persisted to the portfolio table, never routed to the delivery pipeline, and never shown in the inbox.

### 7.2 Similarity engine compatibility

The existing `HistoricalAnalog` table (Phase 9F) already captures structural similarity between a company's current setup and historical precedents. A future **Setup Similarity** feature for portfolios would ask: "Which historical portfolio profiles (in terms of thematic exposure and concentration) preceded specific macro outcomes?" This requires a new `PortfolioAnalog` table (not in scope for 10D) but would read directly from the `ThematicExposure` and `RegimeSensitivity` outputs defined in §4 — those outputs are the natural feature vector for portfolio-level similarity.

The 10D health schema is designed with this in mind: `ThematicExposure` and `RegimeSensitivity` are returned as structured objects (not flat strings), so they can be serialized as numeric feature vectors without a schema migration.

### 7.3 Investment Jarvis vision

The long-term product vision is a natural-language interface that answers portfolio-level questions in conversational form: "What's the biggest macro risk in my portfolio right now?" or "Walk me through why my semiconductor exposure is concentrated." This is the **Investment Jarvis** layer.

10D's architecture supports this by ensuring that all portfolio intelligence outputs (insights, health metrics, cross-exposure clusters) are structured objects with machine-readable fields — not raw prose. A Jarvis layer would consume these structured objects and render them as natural language, using the same Claude API that today generates dossier prose. It would not need access to portfolio schema internals; the 10D service API is the abstraction boundary.

What Jarvis must never do (even in future phases): generate output that violates the §6.2 prohibited list. The regulatory boundary is not relaxed for conversational interfaces.

### 7.4 Multi-user and institutional compatibility

The current `Portfolio` model uses `user_id` as the first-class identity key, mirroring `watched_tickers` and `user_delivery_prefs`. This is compatible with a future multi-user, multi-account model:

- A **shared portfolio** (e.g., an investment club, a family account) maps to a single `portfolio_id` with multiple `user_id` rows in a `PortfolioMember` join table (not in 10D scope).
- An **institutional portfolio** (e.g., a fund's current holdings) maps to the same schema; the only difference is how `weight` is computed (from AUM percentages rather than personal allocations).
- A **model portfolio** (a benchmark or target allocation) is a `Portfolio` with `is_model=True`; positions have weights but no `cost_basis` or `shares`. Not in 10D scope.

The 10D schema does not need to change to support any of these; they require only new API surfaces on top of the existing portfolio table.

---

## 8. Schema design summary

The following new tables are required. All are additive — no existing table is modified by Phase 10D.

### 8.1 `portfolios`

| Column | Type | Notes |
|---|---|---|
| `id` | UUID | Primary key |
| `user_id` | VARCHAR(64) | Owner; NULL = global/single-user |
| `name` | VARCHAR(200) | User-facing label |
| `description` | TEXT | Optional free text |
| `is_default` | BOOLEAN | True for the auto-created watchlist-mirror portfolio |
| `created_at` | TIMESTAMPTZ | |
| `updated_at` | TIMESTAMPTZ | |

Unique constraint: `(user_id, name)`.

### 8.2 `portfolio_positions`

| Column | Type | Notes |
|---|---|---|
| `id` | UUID | Primary key |
| `portfolio_id` | VARCHAR(36) | FK → portfolios.id |
| `ticker` | VARCHAR(20) | |
| `membership_class` | VARCHAR(20) | `owned \| watchlist \| on_radar` |
| `weight` | FLOAT | Nullable; 0.0–1.0 |
| `cost_basis` | FLOAT | Nullable; user-supplied |
| `shares` | FLOAT | Nullable; user-supplied |
| `notes` | TEXT | Nullable |
| `active` | BOOLEAN | Soft-delete |
| `added_at` | TIMESTAMPTZ | |
| `updated_at` | TIMESTAMPTZ | |

Unique constraint: `(portfolio_id, ticker)`. A ticker appears at most once per portfolio; re-adding the same ticker reactivates the existing row.

### 8.3 `portfolio_insights`

| Column | Type | Notes |
|---|---|---|
| `id` | UUID | Primary key |
| `portfolio_id` | VARCHAR(36) | FK → portfolios.id |
| `insight_type` | VARCHAR(60) | Closed enum from §3.1 |
| `cluster_label` | VARCHAR(200) | Theme/concern label driving this insight |
| `member_tickers` | TEXT | JSON array |
| `cluster_weight` | FLOAT | Nullable; aggregated portfolio weight |
| `severity` | VARCHAR(20) | Canonical severity |
| `severity_rank` | INTEGER | Numeric rank (0–4) |
| `rank_score` | FLOAT | Computed ranking score (§3.3) |
| `body_json` | TEXT | JSON; structured insight payload |
| `cross_exposure_as_of` | TIMESTAMPTZ | Freshness bound (§2.5) |
| `stale_input` | BOOLEAN | True if cross-exposure inputs exceed staleness threshold |
| `content_key` | VARCHAR(64) | Dedup key (§3.4); UNIQUE |
| `created_at` | TIMESTAMPTZ | |
| `updated_at` | TIMESTAMPTZ | |
| `last_delivered_at` | TIMESTAMPTZ | Nullable; set on delivery |

### 8.4 No new delivery tables

Portfolio insights route through the existing `delivery_ledger` and `notifications` tables. `artifact_ref` in `delivery_ledger` points to `portfolio_insights.id`. A new `kind` value (`"portfolio_alert"`) is added to the `notifications.kind` enum — this is additive (no migration needed; the column is a free-form VARCHAR).

---

## 9. API surface

All portfolio API routes are new additions under `/portfolio`. They are not modifications to any existing route.

### 9.1 Portfolio management

| Method | Path | Description |
|---|---|---|
| `GET` | `/portfolio` | List user's portfolios |
| `POST` | `/portfolio` | Create a portfolio |
| `GET` | `/portfolio/{portfolio_id}` | Get portfolio with positions |
| `PATCH` | `/portfolio/{portfolio_id}` | Update portfolio name/description |
| `DELETE` | `/portfolio/{portfolio_id}` | Soft-delete portfolio |
| `GET` | `/portfolio/{portfolio_id}/positions` | List positions |
| `POST` | `/portfolio/{portfolio_id}/positions` | Add position |
| `PATCH` | `/portfolio/{portfolio_id}/positions/{ticker}` | Update position weight/class |
| `DELETE` | `/portfolio/{portfolio_id}/positions/{ticker}` | Remove position (sets active=False) |

### 9.2 Portfolio intelligence

| Method | Path | Description |
|---|---|---|
| `GET` | `/portfolio/{portfolio_id}/health` | Portfolio health metrics (§4) |
| `GET` | `/portfolio/{portfolio_id}/insights` | Ranked portfolio insights (§3) |
| `GET` | `/portfolio/{portfolio_id}/cross-exposure` | Cross-exposure clusters (§2) |
| `GET` | `/portfolio/{portfolio_id}/themes` | Thematic exposure summary (§4.3) |
| `GET` | `/portfolio/{portfolio_id}/regime-sensitivity` | Macro regime sensitivity (§4.4) |

### 9.3 Admin / observability

| Method | Path | Description |
|---|---|---|
| `GET` | `/admin/portfolio-status` | 10D observability snapshot (mirrors 10C `/admin/delivery-status` pattern) |

All portfolio intelligence responses include the `regulatory_disclaimer` field (§6.3).

---

## 10. Rollout strategy

### 10.1 Phase ordering

10D does not extend Phase 10C's delivery pipeline; it adds a new producer to it. The prerequisite order is:

1. Phase 10C delivery pipeline must be fully validated (validate_10c_delivery_shadow.py all-pass). ✓ (done as of 2026-06-13)
2. Phase 9G company dossiers must be in production with active cross_exposures populated.
3. Phase 10B watchlist with `watched_tickers` populated.
4. Then: 10D portfolio layer.

### 10.2 Slice ordering (recommended)

| Slice | Scope | Gate |
|---|---|---|
| 10D-1 | Portfolio model schema + CRUD API (no intelligence) | API integration tests pass |
| 10D-2 | Default portfolio auto-creation from watched_tickers mirror | Watchlist sync verified |
| 10D-3 | Cross-exposure projection (read cross_exposures, build clusters) | Cluster output verified against known cross_exposure rows |
| 10D-4 | Portfolio health metrics (HHI, thematic exposure, regime sensitivity) | Health metrics verified against test portfolio with known weights |
| 10D-5 | Portfolio insight generation + ranking | Insight ranking verified; regulatory guard verified (no prohibited language in templates) |
| 10D-6 | Delivery integration — briefing enrichment + standalone alert routing | Shadow delivery verified (no real notifications); enrichment verified in briefing body |
| 10D-7 | Insight dedup + digest coalescing | Dedup verified across 7-day window; digest verified under cap |
| 10D-8 | `/admin/portfolio-status` observability endpoint | Status snapshot verified |
| 10D-9 | Live delivery enablement (canary at 1%) | All prior slices PASS; regulatory disclaimer present on all responses |

### 10.3 Safe defaults

Before 10D-9, portfolio insights are generated and stored in `portfolio_insights` but **not delivered** — they flow into shadow delivery (the existing 10C `delivered_shadow` path). This mirrors the 10C shadow rollout exactly. A `portfolio_insights_shadow=true` flag (mirroring `delivery_shadow`) gates the switch from shadow to live.

---

## 11. Risk register

| Risk | Likelihood | Mitigation |
|---|---|---|
| Cross-exposure data sparsity — few edges populated → few insights | Medium | Coverage gap insight (§3.1) surfaces tickers without dossiers; insights degrade gracefully to empty list, not error |
| Template language drifts into prohibited territory during development | Medium | Regulatory review of every template at 10D-5 slice gate; automated keyword scan for prohibited terms |
| Portfolio insight volume overwhelms daily delivery cap | Low-Medium | Digest coalescing (§5.6); 7-day dedup window suppresses re-alerting on stable concentrations |
| Weight data absent (users don't enter weights) | High | All metrics degrade gracefully to ticker-count-based metrics when weights are null; HHI and cluster_weight are nullable |
| Cross-exposure `strength` threshold (0.7) set too low → false correlation alerts | Medium | Threshold is configurable; default is conservative; can be tuned per deployment |
| User interprets structural observation as a recommendation | Low | Disclaimer infrastructure (§6.3); template language review; no implication of action required |
