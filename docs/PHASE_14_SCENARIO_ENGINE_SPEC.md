# Phase 14 — Scenario Engine

Status: **architecture only — no code, no implementation.**
This document defines what must be built in Phase 14 before any slice is
written. Every implementation decision must be traceable to a section here.
The companion build plan is `PHASE_14_SCENARIO_ENGINE_IMPLEMENTATION_PLAN.md`.

---

## 0. What this is not

Phase 14 produces **no predictions, no recommendations, no position sizing, no
target prices, no execution guidance.** It does not tell a user what *will*
happen or what to *do*. It answers one question, conditionally: **"What happens
if X changes?"**

The distinction is structural and load-bearing:

| Forecasting (Phase 12) answers | Decision (Phase 13) answers | Scenario (Phase 14) answers |
|---|---|---|
| What tends to happen next? | What matters most right now? | What happens *if* X changes? |
| Produces probabilities | Produces priorities | Produces conditional analyses |
| Generates new signal | Ranks existing signal | Propagates existing signal along a stated mechanism |
| Unconditional | Per-attention-candidate | Per-condition (the "if") |

A scenario is an **if → then → because** structure: a *condition* (the "if"), a
*transmission mechanism* (the "then", a stated cause→effect path), and the
*evidence and invalidators* that make it falsifiable (the "because"). It is a
conditional analysis, not a forecast of what will occur and not a suggestion of
what to do about it.

The no-advice boundary is enforced the same way Phase 12's no-price boundary and
Phase 13's no-recommendation boundary are enforced: **there are no fields to put
advice in.** No column holds a buy/sell/hold verdict, a recommended size, a
target price, or an execution instruction. There is no delivery path that emits
such a field. Any output that would read as investment advice or a market
prediction at the UI layer is blocked at the schema level because the schema
cannot represent it.

The Scenario Engine analyzes conditional consequences. It does not predict
outcomes and it does not make investment decisions.

---

## 1. Overview

### 1.1 What Phase 14 adds

Phases 9G–13 built a complete intelligence substrate and four answering engines:

- **Memory (9G)** — *What happened before?*
- **Similarity (11)** — *What does this resemble?*
- **Forecasting (12)** — *What tends to happen next?*
- **Decision Intelligence (13)** — *What matters most right now?*

Each engine surfaces signal about the *current* state of the world. None of
them answers a **conditional**: if a named condition changed — a rate move, an
earnings miss, a supply shock, a thesis break — *which forecasts, decisions, and
holdings would be affected, and through what mechanism?* A user can see that NVDA
has an active forecast, a similarity cluster, and a portfolio exposure, but has
**no mechanism that traces what a specific change would do to all of them at
once.**

Phase 14 adds that layer. It consumes the substrate and produces a single,
explainable, portfolio-aware **conditional analysis** — a scenario — that names
the condition, the transmission mechanism, the affected entities/forecasts/
decisions, the evidence, and the invalidators.

### 1.2 Core design principle

Every scenario is a **propagation over signals that already exist**, never a new
measurement and never a new prediction. The scenario outputs —

```
scenario_impact       qualitative directional effect along the mechanism
confidence_score      reliability of the underlying signals (from upstream)
uncertainty_score     disagreement / spread among the signals (from upstream)
affected_entities     which companies/sectors the mechanism reaches
affected_forecasts    which Phase 12 forecasts the condition would move
affected_decisions    which Phase 13 priorities the condition would re-weight
transmission_mechanism the explicit cause→effect path
evidence              upstream artifacts that support the analysis
invalidators          falsifiable conditions that would void the scenario
```

— are each derived entirely from upstream artifacts (memory, similarity edges,
forecasts, decision priorities, portfolio exposure, cross-exposure edges,
dossiers, watchlist intelligence). The scenario is a deterministic propagation
of a stated condition through those artifacts. **No output introduces
information the substrate did not already contain.** Phase 14 *propagates and
explains*; it does not observe, predict, or advise.

`confidence_score` and `uncertainty_score` are **carried from upstream** (Phase
12 calibration and signal spread) — Phase 14 does not invent its own probability.
They qualify how much weight the conditional analysis deserves; they are never
presented as the likelihood that the scenario *will* occur.

### 1.3 Dependency direction (non-negotiable)

```
Phase 9G   Phase 10A/B/C/D   Phase 11   Phase 12   Phase 13
   ↓             ↓              ↓          ↓          ↓
                         Phase 14
```

- Phase 14 **imports from** Phases 9G, 10A/B/C/D, 11, 12, 13 (and the dossier
  and cross-exposure substrate).
- **Nothing in Phases 9G–13 ever imports from Phase 14.**
- This is enforced by AST import-graph checks in the validation script (the same
  mechanism that enforced Phase 11/12 SP-4 and Phase 13 SP-5).
- Violating this direction is a blocking defect.

The corollary matters as much as the rule: **Scenario output must never flow
back upstream.** A scenario must not alter a forecast, a similarity score, a
decision priority, a thesis, a memory record, an exposure value, or a calibration
log. Phase 14 is a pure sink. See §13 (SP-6).

### 1.4 Relationship to delivery

Once validated, Phase 14 becomes a **conditional-analysis facet** on the existing
delivery surfaces (company view, portfolio intelligence, briefings, alerts). It
does not replace those surfaces or change what they contain — it adds an
"if-this-changes" analysis alongside them. Until validated, it produces a shadow
analysis that no surface reads (see §11).

---

## 2. Architecture

### 2.1 Service layer

Phase 14 adds a service layer of pure, independently-callable modules. The
build/evaluation/journaling flow is flag-gated; the pure functions are not.

| Service | Responsibility |
|---|---|
| `scenario_seed_builder` | Enumerate scenario seeds from the substrate (six frameworks); pure reads |
| `scenario_evaluation_engine` | Build the transmission path and assess impact/plausibility; pure analysis |
| `scenario_explainability_service` | Construct the five mandatory explanation fields; enforce the blocking gate |
| `scenario_assembly_service` | Compose seed → evaluate → explain → gate → persist (first writer); staleness/re-eval |
| `scenario_portfolio_propagation` | Company impact → portfolio impact → exposure propagation; user tier |
| `scenario_read_service` | Read-only, disclaimer-wrapped access; never builds |
| `scenario_delivery_service` | Shadow journaling of the surfaced set; no surface reads it |
| `scenario_calibration_service` | Realization / transmission / invalidator outcome attribution (append-only) |
| `scenario_observability_service` | Read-only snapshot for `/admin/scenario-status` and the validation script |

The seed builder, evaluation engine, and explainability service remain directly
callable regardless of flags (the Phase 11–13 convention): flags gate *automatic*
invocation and *shadow journaling*, not the pure functions.

### 2.2 Repository layer

`app/db/repositories/scenario_repo.py` provides null-session-safe access to the
three Phase 14 tables:

- Upsert/get for `scenario_snapshot` and `scenario_evidence`.
- **Insert-only** `add_run_log` for `scenario_run_log` — no update or delete path
  exists (append-only, like Phase 12/13 calibration logs).
- Windowed `list_run_logs` / `count_run_logs`.

Every repository function returns an inert value (`None` / `[]` / `0`) on
`session=None` and never raises. The repository imports nothing from
order/execution/conviction/stance modules.

### 2.3 Config flags (all default inert)

Six flags, added once in Slice 14.1, mirroring the Phase 13 six-flag shape. Every
default is inert; every intermediate build state is safe.

| Setting | Type | Default | Gates |
|---|---|---|---|
| `scenario_build_enabled` | bool | `false` | automatic seed/assembly building |
| `scenario_evaluation_enabled` | bool | `false` | automatic transmission/impact evaluation; shadow-delivery gate |
| `scenario_delivery_enabled` | bool | `false` | **reserved**; never consumed in Phase 14 (live surfacing = Stage 4) |
| `scenario_shadow` | bool | `true` | shadow journaling |
| `scenario_targets_enabled` | str | `""` | scenario-seed eligibility allowlist (empty ⇒ inert) |
| `scenario_calibration_enabled` | bool | `false` | realization-outcome logging |

`scenario_evaluation_enabled` AND `scenario_shadow` must both be true for shadow
journaling to occur; `scenario_delivery_enabled` is never read as a positive gate
in the build phase and must stay false.

### 2.4 Null-session pattern

Every async function across the service and repository layers accepts a possibly
`None` session and returns an inert value (`[]` / `None` / `{}` / `0`) rather than
raising. The observability snapshot degrades to an empty, `safe_state: true`
shape when the DB is unreachable. This is the same contract proven in Phases
11–13.

---

## 3. Data model

Three additive tables, numbered 47–49 (current schema ends at 46). All
`IF NOT EXISTS`; **no `ALTER` on any existing table.** Schema count 46 → 49.

### Table 47: `scenario_snapshot`

One row per evaluated scenario.

| Column | Type | Notes |
|---|---|---|
| `id` | uuid PK | |
| `scenario_type` | text | `macro` / `company` / `sector` / `catalyst` / `failure_mode` / `portfolio` |
| `entity_type` | text | `company` / `sector` / `macro` / `portfolio` |
| `entity_key` | text | ticker / sector id / macro key / portfolio id |
| `scenario_key` | text | stable identity of the condition (the "if") |
| `condition` | text | the triggering change being analyzed |
| `transmission_path` | json | ordered cause→effect chain (mechanism) |
| `scenario_impact` | text | qualitative directional band — **never a price/return target** |
| `plausibility_band` | text | qualitative band (e.g. `remote` / `plausible` / `likely_conditional`) — **conditional, not a prediction** |
| `confidence_score` | float | carried from upstream signals [0,1] |
| `uncertainty_score` | float | carried from upstream signals [0,1] |
| `affected_entities` | json | companies/sectors the mechanism reaches |
| `affected_forecasts` | json | Phase 12 forecast refs the condition would move |
| `affected_decisions` | json | Phase 13 priority refs the condition would re-weight |
| `what_changed` | text | explainability field 1 |
| `why_it_matters` | text | explainability field 2 |
| `invalidators` | json | falsifiable conditions that void the scenario |
| `evidence_summary` | json | condensed evidence (full rows in table 48) |
| `source_versions` | json | upstream artifact versions for staleness |
| `scenario_schema` | int | schema version |
| `user_id` | uuid NULL | `NULL` = global tier; non-null = user tier |
| `built_at` | timestamptz | |
| `expires_at` | timestamptz | TTL |

Unique constraint: `(scenario_type, entity_type, entity_key, scenario_key,
user_id)`.

**There is no column for advice, sizing, a target price, an execution
instruction, or a probability-of-occurrence.** The schema cannot represent any of
them.

### Table 48: `scenario_evidence`

Evidence items backing a snapshot.

| Column | Type | Notes |
|---|---|---|
| `id` | uuid PK | |
| `scenario_id` | uuid FK | → `scenario_snapshot.id` |
| `source_phase` | text | `memory` / `similarity` / `forecast` / `decision` / `portfolio` / `cross_exposure` / `dossier` / `watchlist` |
| `source_ref` | text | upstream artifact id |
| `captured_value` | json | the cited upstream value (read-only copy) |
| `captured_at` | timestamptz | |

### Table 49: `scenario_run_log`

**Append-only** run / shadow / outcome log. No update or delete path.

| Column | Type | Notes |
|---|---|---|
| `id` | uuid PK | |
| `scenario_id` | uuid NULL | nullable for run-level rows |
| `run_reason` | text | `assembly` / `shadow` / `calibration_outcome` |
| `snapshot_reason` | text | transition/journal classification |
| `realized_state` | text NULL | `materialized` / `invalidated` / `unresolved` (calibration only) |
| `rank_position` | int NULL | shadow surfacing position |
| `evaluated_at` | timestamptz | |

### Migration

`app/db/migrations/014_scenario_engine.sql` — tables 47–49 only, all
`IF NOT EXISTS`, indexes, the snapshot unique constraint. No `ALTER`. Mirrors the
additive-only pattern of `013_decision_intelligence.sql`.

---

## 4. Scenario questions and seed scope

### 4.1 The questions the engine answers

A scenario answers a conditional, scoped to one of six frameworks:

- **Macro** — *If a macro condition changes (rates, inflation print, regime),
  what propagates?*
- **Company** — *If this company's thesis/forecast breaks or confirms, what
  propagates?*
- **Sector** — *If a sector-wide condition shifts, which names move and why?*
- **Catalyst** — *If this dated catalyst resolves one way, what follows?*
- **Failure-mode** — *If this named failure mode triggers, what is affected?*
- **Portfolio** — *If condition X occurs, what happens to this user's holdings?*

Each is conditional. None asserts the condition *will* occur.

### 4.2 Seed assembly (the six frameworks, one builder)

`scenario_seed_builder` assembles seeds from the substrate — **consuming, never
re-deriving** upstream intelligence:

| Framework | Primary upstream sources |
|---|---|
| `macro` | macro catalysts / regime signals (9G, 12) |
| `company` | forecast (12), decision priority (13), thesis transitions (10A/12), dossier |
| `sector` | similarity clusters (11), shared exposure (10D) |
| `catalyst` | dated catalysts (9G/12), watchlist intelligence (10B) |
| `failure_mode` | failure modes / risk candidates (10A/12/13) |
| `portfolio` | portfolio positions/insights (10D) + cross-exposure |

Eligibility is filtered against `scenario_targets_enabled` (empty ⇒ nothing
eligible ⇒ inert). Each seed captures `source_versions` for staleness. The
builder reads upstream *read* paths only; it never recomputes a forecast,
similarity edge, decision score, or exposure value.

---

## 5. Evaluation framework

One parameterized model keyed by `scenario_type` — **not six engines.** Build
order within `scenario_evaluation_engine`:

### 5.1 Transmission mechanism

`build_transmission_path(seed)` constructs the explicit cause→effect chain:
condition → mechanism → affected entities/forecasts/decisions. The path
references real upstream conditions (a forecast that would move, a similarity
edge that carries contagion, a cross-exposure link). **A seed with no derivable
mechanism produces an empty path** — which the §6 gate blocks. A scenario with no
transmission mechanism is, by definition, not a scenario.

### 5.2 Impact assessment

`assess_impact(seed, transmission)` produces `scenario_impact` as a **qualitative
directional band** (intrinsic at the global tier; exposure propagation added at
the user tier, §7). It is bounded and never a price, a return number, or a
position size. It expresses *direction and reach along the mechanism*, not a
magnitude an advisor would act on.

### 5.3 Confidence and uncertainty

`confidence_score` and `uncertainty_score` are **carried from upstream** (Phase
12 calibration reliability and signal spread). Phase 14 does not invent its own.
They are independent (not complements) and qualify the weight of the conditional
analysis — never the likelihood the scenario occurs.

### 5.4 Plausibility bands

`assess_plausibility(seed)` maps upstream confidence/uncertainty and corroborating
evidence to a **qualitative band** (`remote` / `plausible` / `likely_conditional`
or equivalent). The band is explicitly conditional framing — it is never a
probability sold as a prediction, and no numeric likelihood-of-occurrence is
stored.

### 5.5 Determinism

Identical inputs + schema version ⇒ identical transmission path, impact band,
plausibility band, affected-set, and ordering. `scenario_type` selects the
transmission template and eligible sources; it does **not** select a different
engine. Adding a scenario type later is a config row, not an engine rewrite.

---

## 6. Explainability framework

Every stored scenario must answer **five mandatory questions**. The gate is
enforced at the point of storage (in §8.3 assembly, using the §6 validator):

1. **What changed** — the triggering condition (`what_changed`).
2. **Why it matters** — the stakes (`why_it_matters`).
3. **Transmission mechanism** — the explicit cause→effect path
   (`transmission_path`, from §5.1).
4. **Evidence** — ≥1 `scenario_evidence` row citing upstream artifacts.
5. **Invalidators** — ≥1 falsifiable condition that would void the scenario.

`validate_scenario_explanation(...)` returns `False` if **any** of the five is
missing. A scenario failing the gate is discarded with a `blocked_explanation`
log and **never written.** Incomplete explanations are not stored in degraded
form — they are blocked entirely. `invalidators` must be falsifiable statements
referencing real upstream conditions, not generic hedges.

---

## 7. Portfolio impact framework

Phase 14 propagates a scenario onto a user's holdings. The user tier is additive
over the global tier.

### 7.1 Company impact

`company_impact(...)` — the intrinsic directional band on a single company
(global tier, `user_id = NULL`), independent of any user's holdings.

### 7.2 Portfolio impact and exposure propagation

`portfolio_impact(session, user_id, scenario)` aggregates the exposure pathway
across the user's holdings. `propagate_exposure(...)` walks the transmission path
through Phase 10D portfolio intelligence and cross-exposure edges to identify
**which held entities the scenario reaches and how.** Propagation is bounded to
the user's holdings and to edges that already exist upstream — it invents no
edge. It names pathways and qualitative magnitude; it **never** emits an action,
size, or rebalancing step.

### 7.3 Two-tier materialization

- **Global tier** (`user_id = NULL`) — intrinsic scenarios, portfolio-independent.
- **User tier** (`user_id = <uid>`) — scenarios with propagation applied, bounded
  to the user's holdings.

The read service unions user-tier over global-tier and dedups by
`(scenario_type, entity_type, entity_key, scenario_key)`; the user-tier row wins.

### 7.4 Isolation invariant

A user-tier scenario is never readable under a different `user_id`. The
`SYSTEM_DEFAULT_USER_ID` baseline is global-tier only. Tenant isolation is
verified by an explicit cross-user read test.

---

## 8. Calibration, drift, and invalidation

Scenario calibration measures whether **conditional analyses held** — not whether
a point forecast was accurate. Phase 12's Brier score and Phase 13's rank-order
agreement are **not** the Phase 14 metric.

### 8.1 Realization outcome attribution

When a scenario's condition resolves, `record_scenario_outcome(...)` appends a
`scenario_run_log` row with `realized_state` ∈ `{materialized, invalidated,
unresolved}`. Append-only; never updates an existing row. Derived metrics:

- **Realization agreement** (primary) — did `plausible`-flagged scenarios
  materialize more than `remote`-flagged ones?
- **Transmission accuracy** — when a scenario materialized, did the affected
  entities match the stated transmission path?
- **Invalidator hit-rate** — when a scenario did not materialize, was a stated
  invalidator the actual reason? (a measure of explanation honesty)

These are exposed instead of any prediction-accuracy headline.

### 8.2 Drift / stability

- **Stability / churn** — snapshot-to-snapshot scenario-set movement for
  unchanged inputs (should be low).
- **Drift** — windowed `improving` / `worsening` / `stable` /
  `insufficient_samples` on realization agreement.

Gated by `scenario_calibration_enabled`. Calibration is vacuous on first deploy
(cold-start), as expected.

### 8.3 Invalidation and re-evaluation

`scenario_assembly_service` detects staleness (`source_versions` behind upstream,
`expires_at` passed, `scenario_schema` changed) and re-evaluates in place. Reads
never trigger a rebuild (strict separation). Auto-evaluation is gated by
`scenario_build_enabled` + `scenario_evaluation_enabled` +
`scenario_targets_enabled`; default inert.

---

## 9. Delivery framework

### 9.1 Consumption surfaces

Once validated, scenarios surface as a conditional-analysis facet on the company
view, portfolio intelligence, briefings, and alerts. These surfaces are described
here for context only.

### 9.2 Shadow journaling

In the build phase, `scenario_delivery_service.journal_shadow_scenarios(...)`
computes the surfaced set and appends `scenario_run_log` rows
(`run_reason="shadow"`) — and writes to **nothing else.** No Notification row, no
surface mutation. Gated by `scenario_evaluation_enabled` + `scenario_shadow`;
`scenario_delivery_enabled` is reserved and unused. Journaling is idempotent (no
churn-spam on unchanged sets).

### 9.3 What is not built in Phase 14

Live (user-visible) surfacing — `scenario_delivery_enabled=true` ordering or
promoting real surfaces — is **out of scope for the build phase.** It is Stage 4,
gated per-surface and reversibly behind the acceptance criteria in §16.

---

## 10. Validation framework

### 10.1 Transmission-path validation

Every stored scenario has a non-empty `transmission_path`; a seed with no
derivable mechanism is blocked (not stored). Determinism: identical inputs ⇒
identical path and affected-set.

### 10.2 Explainability validation

The five mandatory fields are present on every stored scenario; the gate blocks
any scenario missing one; `invalidators` are falsifiable and reference real
upstream conditions.

### 10.3 Drift validation

Realization agreement, transmission accuracy, and invalidator hit-rate compute
correctly on seeded outcomes; churn within bound on a static fixture, flagged on a
jittered fixture; drift classification correct; `insufficient_samples` below the
minimum.

### 10.4 Portfolio-propagation validation

Exposure propagation reaches the correct held entities; an unexposed user sees
only the global tier; tenant isolation holds; propagation invents no edge absent
upstream; no advice/size/rebalance leak on the propagation surface.

### 10.5 No-advice validation

No advice/size/price/target/prediction field exists in any response (`/admin/`
and non-`/admin/`). AST string scans confirm no buy/sell/hold, no target-price,
and no point-prediction language in any `scenario_*` module (data constant lists
excluded). The mandatory conditional-analysis disclaimer is present verbatim.

### 10.6 Validation script

`tests/validate_14_scenario_engine_shadow.py` — a standalone script (exit 0/1)
checking: `db_table_count >= 49`; tables 47–49 exist; all scenario services
importable; all six flags inert by default; no order/execution/conviction/stance
imports; no upstream write-back; no advice/target-price/prediction language;
transmission-path-present invariant; portfolio-propagation; tenant isolation;
`scenario_run_log` immutability; no public scenario route; `/admin/scenario-status`
present; `safe_state: true` (DB-down and DB-up); no Notification rows.

---

## 11. Rollout strategy

### Stage 0 — Shadow validation (initial deploy state)
All flags inert. Tables empty. `safe_state: true`. Monitored via
`/admin/scenario-status`.

### Stage 1 — Build + evaluation (internal only)
`SCENARIO_BUILD_ENABLED=true`, `SCENARIO_EVALUATION_ENABLED=true`,
`SCENARIO_TARGETS_ENABLED=company`. Global-tier scenarios build and evaluate; no
delivery. Monitor scenario_count, explainability block-rate, safe_state.

### Stage 2 — Shadow surfacing + calibration
`SCENARIO_CALIBRATION_ENABLED=true` (shadow stays true). Shadow surfacing
journaled; outcomes attributed. Monitor realization agreement, transmission
accuracy, drift `stable`/`improving`, `shadow_escalated_count=0`.

### Stage 3 — Portfolio (user-tier) shadow
`SCENARIO_TARGETS_ENABLED=company,sector,portfolio`. User-tier scenarios build;
propagation validated on live shadow data. Monitor propagation correctness,
isolation.

### Stage 4 — Delivery (user-visible) — **separate sign-off**
`SCENARIO_DELIVERY_ENABLED=true` behind a per-surface gate. **Out of scope for the
build phase.** Requires the §16 acceptance criteria and human sign-off.

### Rollback
Each stage is reversible by resetting the flag to its default. The three additive
tables may be dropped/truncated with no effect outside Phase 14.

---

## 12. Admin routes

All `/admin/`-only, read-only, DB-down-safe. No public (non-`/admin/`) scenario
route exists.

| Route | Purpose |
|---|---|
| `GET /admin/scenario-status` | Observability snapshot (§2.1 `scenario_observability_service`) |
| `GET /admin/scenario/{ticker}` | Disclaimer-wrapped scenario facet for an entity |
| `GET /admin/scenarios?user_id=` | Identity-scoped scenario set |

Every response is disclaimer-wrapped and carries the transmission path and
invalidators; none carries an advice/size/price/target/prediction field.

---

## 13. Security and safety constraints

### SP-6 — no scenario → action / prediction pipeline (extends SP-5)

Scenario output is a **conditional analysis**. SP-6 states:

> Scenario output must never predict an outcome, recommend an action, size or
> advise on a position, or assert a target price. It must not import
> order/execution/conviction/stance. It must not flow back into Memory,
> Similarity, Forecasting, Decision Intelligence, Portfolio Intelligence,
> Cross-Exposure, dossiers, or watchlist intelligence.

SP-6 follows SP-4 (Phase 12) and SP-5 (Phase 13). It is enforced structurally
(no field exists to hold advice or a prediction), by AST import-graph scan (no
forbidden imports; no upstream-write import), and by runtime before/after
snapshot in every data-touching slice.

### No-advice boundary (structural)

No column on tables 47–49 holds a buy/sell/hold verdict, a recommended size, a
target price, an execution instruction, or a probability-of-occurrence. No
delivery path emits one. The boundary holds because the schema cannot represent a
violation.

### No credential / secret leakage

The observability snapshot contains only counts, booleans, qualitative bands, and
ISO timestamps — never raw upstream payloads, prompts, model output, or secrets.

### Identity isolation

User-tier scenarios are strictly scoped by `user_id`. No cross-user read is
possible. `SYSTEM_DEFAULT_USER_ID` is global-tier only.

---

## 14. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Scenario reads as a prediction | Plausibility/impact are qualitative bands; no numeric likelihood-of-occurrence column; no-prediction string scan; conditional disclaimer verbatim |
| Scenario reads as advice | No advice/size/price field exists; no-advice AST scan; SP-6 |
| Re-deriving upstream intelligence | Builder/evaluator read upstream values and cite them as evidence; no recompute; no-duplication test |
| Transmission path is hand-wavy | Path must reference real upstream conditions; empty/ungrounded path is blocked by the §6 gate |
| Exposure propagation invents edges | Propagation bounded to existing 10D / cross-exposure edges; runtime test asserts no invented edge |
| Upstream mutation | Pure-sink; AST + before/after snapshot per slice; SP-6 |
| Cross-tenant leakage | `user_id` scoping; explicit isolation test |
| Uncommitted working tree (Phase 11/12 regression) | Commit checkpoint per slice; `safe_state: true` held at every intermediate state |

---

## 15. Dependency map

```
        Memory (9G) ┐
     Similarity (11)│
    Forecasting (12)│
Decision Intel (13) ├──read──▶  Scenario Engine (14)  ──write──▶  scenario_snapshot
   Portfolio (10D)  │             (seed → transmission →           scenario_evidence
  Cross-Exposure    │              impact → explainability →        scenario_run_log
        Dossiers    │              gate → shadow journal)
 Watchlist Intel    ┘                     │
                                          └── read back into upstream?  ❌ NEVER (SP-6)
```

- **Consumes, never duplicates**: no forecast, similarity edge, decision score,
  or exposure value is recomputed; the materialized upstream value is read and
  cited as evidence.
- **One-way dependency**: nothing in 9G–13 / cross-exposure / dossier / watchlist
  imports `scenario_*`. Enforced by AST in the builder, assembly, propagation, and
  the validation script.
- **No live coupling**: the only write targets are the three additive Phase 14
  tables; the only build-phase "delivery" is the shadow `scenario_run_log` journal
  that no surface reads.

---

## 16. Acceptance criteria for any Phase 14 live delivery (Stage 4)

Before any live-surfacing gate may be opened:

1. `tests/validate_14_scenario_engine_shadow.py` exits 0 in production.
2. `/admin/scenario-status` reports `safe_state: true`, `shadow_escalated_count:
   0`, `live_notification_count: 0`.
3. All `tests/test_services/test_scenario_*.py` pass (every slice).
4. `scenario_count > 0` after Stage 1 for 24h+; explainability block-rate within
   the expected band; every stored scenario has a non-empty transmission path and
   ≥1 invalidator.
5. Scenario stability: churn within bound over 7+ days of shadow snapshots.
6. Calibration: realization agreement above a defined floor; transmission accuracy
   and invalidator hit-rate within targets; drift `stable`/`improving` over the
   most recent window.
7. Portfolio propagation: exposure pathways demonstrated against live shadow data;
   tenant isolation holds; no advice/size/rebalance leak.
8. No advice/size/price/target/prediction field anywhere in any response; no-advice,
   no-target-price, and no-prediction tests green.
9. SP-6 verified: AST confirms no `scenario_*` module imports order/execution/
   conviction/stance, and no scenario output writes back to any upstream phase.
10. Human sign-off on transmission-path and invalidator quality, and on the
    per-surface delivery gate plan.

---

## 17. Slice plan

The build is decomposed into 10 independently-shippable, reversible slices
(14.1–14.10), each committed before the next, each leaving `safe_state: true`.
See `PHASE_14_SCENARIO_ENGINE_IMPLEMENTATION_PLAN.md` for the per-slice scope,
files, validation, rollback, and commit checkpoints. No slice may be built
against a section number not confirmed against this spec.
