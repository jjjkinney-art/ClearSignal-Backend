# Company Dossier — Implementation Plan

**Phase:** 9G · Phase 0
**Source of truth:** `docs/COMPANY_DOSSIER_SPEC.md` (locked — this plan does not redesign anything)
**Status:** Execution blueprint — no code in this document
**Convention basis:** All file paths, patterns, and table conventions below reference the existing codebase (9A–9F precedents).

---

## PART 1 — BUILD SLICES

Eight slices. Each is independently shippable, independently revertible, and leaves production in a working state if the next slice never lands. The slicing rule: **persistence before writers, writers before readers, readers before UI** — the same order that made 9F safe.

---

### Slice 1 — Schema & Migration

**Objective:** Create all dossier tables empty in production. Zero behavior change.

**Files:**
- `app/db/migrations/004_company_dossier.sql` (new)
- `app/db/models.py` (append ORM models: `CompanyDossier`, `DossierCoreDebate`, `DossierMoatDimension`, `DossierCatalyst`, `DossierVariant`, `DossierDurability`, `DossierFailureMode`, `DossierRevision`)
- `app/startup.py` (register migration in the startup-seed path, mirroring the 9F `003_historical_evidence.sql` activation)

**Dependencies:** none.

**Risk:** Minimal. Additive-only DDL, `IF NOT EXISTS` throughout (003 precedent). No reader or writer exists yet.

**Validation:** `db_table_count` increases by 8 in the admin status endpoint; app boots clean; all existing tests pass untouched; migration is idempotent (run twice, no error).

---

### Slice 2 — Repositories (persistence layer)

**Objective:** Typed read/write layer over the new tables. Still no callers.

**Files:**
- `app/db/repositories/dossier_repo.py` (new — head + facet CRUD)
- `app/db/repositories/dossier_revision_repo.py` (new — append-only log)
- `app/db/repositories/__init__.py` (exports)

**Dependencies:** Slice 1.

**Risk:** Minimal. Dead code until Slice 4 wires it. Null-object pattern (`session=None → None/[]`) identical to `memory_retrieval.py`, so a missing DB can never 500.

**Validation:** Unit tests against an in-memory SQLite session (existing `conftest.py` fixture pattern): round-trip every facet, optimistic-concurrency conflict test, revision append immutability test.

---

### Slice 3 — Extraction logic (pure functions, no wiring)

**Objective:** The reconciliation brain — pure, deterministic, fully unit-testable before it touches production flow.

**Files:**
- `app/services/dossier_extraction_service.py` (new — harvest from `InvestmentThesis`, confidence gates, hysteresis, debate-change rules, catalyst lifecycle, conflict resolution)
- `app/structured_output.py` (extend with the multi-facet extraction schema — one structured call per spec §10.1)
- `app/prompts.py` (extraction prompt constant)

**Dependencies:** Slice 2 (for types only — service stays side-effect-free; repo calls happen in Slice 4).

**Risk:** Low. Pure functions; the riskiest logic (hysteresis, debate stickiness) gets exhaustive table-driven tests *before* any production wiring.

**Validation:** Unit tests per update rule in PART 4; golden-file tests: feed three recorded production `InvestmentThesis` payloads (NVDA, AAPL, JPM) and assert extracted facets are sane and stable across runs.

---

### Slice 4 — Extraction wiring (post-dispatch write path)

**Objective:** Dossiers start being *written* in production. Still nothing reads them.

**Files:**
- `app/api.py` (post-dispatch hook, placed alongside the 9F historical-evidence stamping block — same best-effort/try-except envelope)
- `app/db/persistence.py` (extraction triggered after `persist_analysis_result` succeeds, so `source_version_id` always exists)
- `app/config.py` (feature flag: `dossier_extraction_enabled`, default **off**)

**Dependencies:** Slices 1–3.

**Risk:** **Medium — first production write path.** Mitigations: feature flag default-off; strictly post-dispatch (user response already streamed); any exception degrades to "no update this cycle" + log line; extraction failure cannot corrupt — facet writes are transactional per facet.

**Validation:** Flag on in staging → run 5 analyses across 3 tickers → inspect rows: head exists, facets populated, revisions logged, provenance rows present, second analysis of same ticker exercises reconciliation (not blind overwrite). `/ask` latency unchanged (extraction is post-dispatch).

---

### Slice 5 — Injection (pre-synthesis read path)

**Objective:** Synthesis becomes positionally aware. The first behavior-visible slice.

**Files:**
- `app/services/dossier_injection_service.py` (new — budget assembly, relevance filtering, staleness annotation)
- `app/memory_context.py` (or sibling `dossier_context.py`) — `format_dossier_for_prompt`
- `app/api.py` (inject in the existing memory-block slot, ~lines 597–640, as a delimited sibling section)
- `app/config.py` (flag: `dossier_injection_enabled`, default **off**)

**Dependencies:** Slice 4 running long enough that dossiers exist (≥1 week of writes, or staging backfill).

**Risk:** **Highest in the plan — touches synthesis quality.** Mitigations: independent flag (extraction can run with injection off); hard token cap with priority-drop (PART 5); null-object on missing dossier = exact current behavior; A/B comparison in staging before prod flag flips.

**Validation:** Side-by-side synthesis outputs with flag on/off for a ticker with rich dossier: "on" output references prior view ("Since the prior analysis…"), conviction wall-cap and synthesis-fallback regressions absent, token count of injected block ≤ cap in 100% of sampled runs.

---

### Slice 6 — Read API

**Objective:** Expose the dossier to the frontend.

**Files:**
- `app/api.py` (new `GET /dossier/{ticker}`; extend `/ask` thesis payload with the injected-slice summary under `dossier_context`, mirroring how `memory_context` and `historical_evidence` ride the response)
- `app/schemas.py` (response models: `DossierResponse`, facet sub-models)

**Dependencies:** Slice 4 (data exists). Independent of Slice 5.

**Risk:** Low. Read-only; null-object → `404`/`null` for unknown tickers.

**Validation:** Contract tests: empty ticker, single-analysis ticker, multi-analysis ticker with revisions; response shape matches schema; p95 read < 50 ms (single indexed head read + bounded facets).

---

### Slice 7 — Frontend surfaces

**Objective:** Render the dossier. Spec §7 surfaces, built in dependency order.

**Files (all under `Ai-Intelligence-interface/frontend_cinematic/`):**
- `components/CoreDebateBanner.tsx` (new)
- `components/MoatProfileGrid.tsx` (new)
- `components/CatalystWatchlist.tsx` (new)
- `components/DossierTimeline.tsx` (new — history page lane)
- `app/(product)/analyze/page.tsx` (wire banner between thesis header and verdict; moat grid + catalysts in memory region; extend `extractInvestmentThesis` with `dossier_context` — same pattern as the 9F `historicalEvidence` extraction)
- `app/(product)/history/page.tsx` (second lane: dossier evolution)
- `app/(product)/watchlist/page.tsx` (lean / moat / open-catalyst / staleness columns)
- `app/(product)/company/page.tsx` (full dossier profile)
- `lib/api.ts` (dossier fetcher)

**Dependencies:** Slice 6.

**Risk:** Low. Null-safe components return `null` on missing dossier (the `InvestmentMemoryBanner` / `HistoricalEvidencePanel` precedent). TypeScript must stay at 0 errors.

**Validation:** `npx tsc --noEmit` clean; live browser verification against production backend (the 9F verification protocol): banner renders with real debate, moat arrows correct, catalysts lifecycle-styled, no hydration warnings introduced.

---

### Slice 8 — Hardening & ops

**Objective:** Production confidence: staleness, observability, backfill.

**Files:**
- `app/services/dossier_extraction_service.py` (staleness computation, confidence decay)
- `app/api.py` (admin endpoint: `GET /admin/dossier-status` — counts, staleness distribution, last-extraction errors; mirrors the 9F admin status endpoint)
- `app/enterprise/observability.py` (extraction success/failure counters, injection token-size histogram)
- One-off backfill script under `stage7a/` or `tests/` convention: replay latest `thesis_versions` per ticker through extraction to seed dossiers for already-covered names

**Dependencies:** Slices 4–6.

**Risk:** Low. Backfill is replay-through-the-same-governed-path — no hand-written dossiers.

**Validation:** Admin endpoint shows expected coverage (≥ all tickers in `.clearSignal_watchlist`); staleness states correct against known timestamps; error rate < 1% over a week of production extraction.

---

## PART 2 — DATABASE DESIGN

### New tables (8)

**Head (single-row-per-ticker):**

| Table | Key columns | Notes |
|---|---|---|
| `company_dossier` | `id` (uuid PK), `ticker` **UNIQUE**, `latest_version_id` FK→`thesis_versions.id`, `stance`, `conviction`, `primary_concern`, `as_of`, `schema_version`, `global_confidence`, `staleness_state`, `last_full_update_at`, `analysis_count`, `row_version` (optimistic lock), `created_at`, `updated_at` | The only table injection must read to decide "is there a dossier." Mirrors `ticker_memory` single-row pattern. |

**Facet "current" tables:**

| Table | Cardinality | Key columns |
|---|---|---|
| `dossier_core_debate` | 1:1 per ticker | `ticker` UNIQUE, `question`, `bull_pole`, `bear_pole`, `current_lean`, `resolution_signal`, `version`, `confidence`, `first_seen_at`, `updated_at` |
| `dossier_moat_dimension` | 1:N (≤6 axes) | `ticker`+`axis` UNIQUE composite, `strength`, `trend`, `rationale`, `vulnerability`, `version`, `confidence`, `pending_flip` (hysteresis state), `last_changed_at` |
| `dossier_catalyst` | 1:N bounded | `id` uuid PK (stable for hit/miss), `ticker`, `statement`, `direction`, `specificity`, `expected_window`, `status`, `conviction_weight`, `source_version_id` FK, `created_at`, `resolved_at` |
| `dossier_variant` | 1:1 per ticker | `ticker` UNIQUE, `divergences` (JSON list — bounded, render-only, never queried by element), `version`, `confidence`, `updated_at` |
| `dossier_durability` | 1:1 per ticker | `ticker` UNIQUE, `cycle_position`, `catalyst_proximity_days`, `analog_time_to_trough_days`, `conviction_trend`, `horizon_hint`, `updated_at` |
| `dossier_failure_mode` | 1:N | `ticker`, `analog_id` FK→`historical_analogs.id`, `sequence_stage`, `stage_evidence`, `relevance_at_match`, `matched_at` |

**Append-only (immutable):**

| Table | Key columns |
|---|---|
| `dossier_revision` | `id` PK, `ticker`, `facet`, `prev_version`, `new_version`, `change_summary`, `diff_json`, `confidence`, `source_version_id` FK, `created_at`. **No UPDATE/DELETE path in any repository.** |
| `dossier_evidence_ref` | `id` PK, `ticker`, `facet`, `claim_hash`, `source_type` (`thesis_version`/`analog`/`filing`/`financial_data`/`inferred`), `source_id`, `as_of` |

*(Provenance counted within the 8: head + 5 facet tables with failure_mode = 7, + revision + evidence_ref = 8 new tables — `dossier_variant`/`dossier_durability` may merge into the head if review prefers fewer 1:1 tables; spec permits either, plan defaults to separate tables for facet-level versioning clarity.)*

### Indexes

| Index | Table | Purpose |
|---|---|---|
| `UNIQUE(ticker)` | `company_dossier`, `dossier_core_debate`, `dossier_variant`, `dossier_durability` | O(1) injection read |
| `UNIQUE(ticker, axis)` | `dossier_moat_dimension` | one row per axis |
| `(ticker, status)` | `dossier_catalyst` | injection filters `open`; UI filters by status |
| `(ticker)`, `(analog_id)` | `dossier_failure_mode` | forward + reverse analog lookup |
| `(ticker, facet, created_at)` | `dossier_revision` | history timeline; off hot path |
| `(ticker, facet)` | `dossier_evidence_ref` | provenance lookup per facet |

### Migration plan

- **One file: `004_company_dossier.sql`.** All eight tables + indexes, `IF NOT EXISTS` throughout, header comment documenting design principles (003 precedent).
- Apply order: after 001/002/003 on live DB. Registered in `app/startup.py` startup-seed path with the same guard pattern as 9F (`db_table_count` check before/after).
- **No data migration** — tables start empty; population is Slice 4 (organic) + Slice 8 (backfill replay).
- **Rollback:** tables are inert without the feature flags; rollback = flags off. DDL itself never needs reverting (additive, unused).

### Relationships

```
thesis_versions ──< source_version_id ── dossier_revision
        ▲                                dossier_catalyst
        └── latest_version_id ── company_dossier (head)
historical_analogs ──< analog_id ── dossier_failure_mode
ticker (normalized, app/db/ticker_normalizer.py) — logical join key everywhere; no FK to ticker_memory by design (spec §2.3)
```

---

## PART 3 — REPOSITORIES

Follow the existing `app/db/repositories/` conventions: module-level async functions (not classes) where the codebase does that, null-object on `session=None`, no business logic in repos.

| Repository | File | Responsibilities | API surface (conceptual) | Ownership boundary |
|---|---|---|---|---|
| **DossierRepo** (head) | `dossier_repo.py` | Head row lifecycle; optimistic lock; staleness read/write; the single "does a dossier exist" gate | `get_head(ticker)`, `upsert_head(...)`, `touch(ticker, row_version)`, `get_full_dossier(ticker)` (head + all facets, one round-trip for injection/API) | Owns `company_dossier` only. Never writes facets. |
| **DebateRepo** | `dossier_repo.py` (same module — facet section) | Current debate read/write; version bump on material change only | `get_debate(ticker)`, `write_debate(..., expect_version)`, `update_lean(ticker, lean)` (non-versioning) | Owns `dossier_core_debate`. Does **not** decide *whether* to version — extraction service decides, repo enforces `expect_version`. |
| **MoatRepo** | `dossier_repo.py` | Per-axis upsert; hysteresis state (`pending_flip`) persistence | `get_dimensions(ticker)`, `upsert_dimension(ticker, axis, ..., expect_version)`, `set_pending_flip(...)` | Owns `dossier_moat_dimension`. |
| **CatalystRepo** | `dossier_repo.py` | Append catalysts; lifecycle transitions; never delete | `list(ticker, status=None)`, `append(...)`, `transition(id, new_status, resolved_at)` | Owns `dossier_catalyst`. Transition validity (open→triggered etc.) enforced here; *which* transition is the service's call. |
| **VariantRepo / DurabilityRepo** | `dossier_repo.py` | 1:1 facet read/write | `get(ticker)`, `write(ticker, ..., expect_version)` | Own their tables. |
| **FailureModeRepo** | `dossier_repo.py` | Analog-link CRUD; stage updates | `list(ticker)`, `upsert(ticker, analog_id, stage, ...)` | Owns `dossier_failure_mode`. Never reads `historical_analogs` content — caller joins. |
| **RevisionRepo** | `dossier_revision_repo.py` | Append-only log + timeline reads | `append(...)`, `timeline(ticker, facet=None, limit)` | Owns `dossier_revision` + `dossier_evidence_ref`. **Exposes no update/delete.** Separate file to make immutability structurally obvious in review. |

**Boundary rules (enforced in review):**
1. Repos do persistence only — every gate/threshold/hysteresis decision lives in `dossier_extraction_service.py`.
2. Only the extraction service writes facets; only injection/API read them. No other service touches dossier tables.
3. Every facet write is paired with a `RevisionRepo.append` and an evidence-ref write **in the same transaction** — a facet change without an audit row must be impossible by construction.

---

## PART 4 — EXTRACTION PIPELINE (post-synthesis write path)

**Trigger:** after `persist_analysis_result` commits the new `thesis_version` (so `source_version_id` exists), inside the post-dispatch envelope in `api.py` — the 9F pattern: user response already streamed; failures degrade to no-op + log.

**Stages:**

```
1. HARVEST    — pull fields off the InvestmentThesis already in memory:
               core_debate, core_market_debate, key_risks, what_changes_the_thesis,
               conviction_dimensions, setup_label, valuation_stance, narrative text
2. EXTRACT    — ONE structured-output call (app/structured_output.py) producing
               all candidate facets + per-facet confidence + per-claim source spans
3. LOAD       — DossierRepo.get_full_dossier(ticker)  (or init empty on first run)
4. RECONCILE  — pure functions in dossier_extraction_service: gates → hysteresis →
               versioning decisions → catalyst lifecycle → conflict resolution
5. COMMIT     — per-facet transactions: facet write + revision append + evidence refs;
               refresh head (counters, staleness, global_confidence, row_version)
```

### What gets extracted / versioned / updated / ignored

| Signal in thesis | Action | Versioned? |
|---|---|---|
| `core_debate` / `core_market_debate` text | candidate debate framing | Only per debate rules below |
| Stance/conviction/concern | mirror into head `prior_thesis_state` fields | No (cache refresh) |
| Moat-relevant narrative (drivers, risks, moat language) | candidate axis updates on the **fixed 6-axis taxonomy** | On strength/trend flip past hysteresis |
| `what_changes_the_thesis` + catalyst-shaped statements | candidate catalysts | No (lifecycle, each transition logged) |
| Consensus-divergence language | candidate variant divergences | On direction flip / new divergence |
| Cycle/horizon language + analog trough data + memory trend | durability signals (raw) | No (signals, not grades) |
| Active analog matches (from 9F retrieval already on the response) | failure-mode links + stage | Stage change logs revision |
| **Anything not mappable to a facet** | **ignored** — never free-form-stored | — |
| **Any claim without a source span** | stored only as `source_type=inferred`, excluded from injection priority | — |

### Thresholds & rules (initial values — calibration owned by Slice 8)

| Rule | Value |
|---|---|
| `τ_write` — minimum extraction confidence to write any facet | **0.55** (below: retain existing, log observation) |
| `τ_high` — single-shot override confidence | **0.75** |
| Catalyst specificity gate | **0.50** (below: discard, don't store) |
| **Hysteresis** (moat strength/trend, composite) | flip only after **2 consecutive agreeing syntheses** (`pending_flip` holds state) OR 1 synthesis ≥ `τ_high` |
| Catalyst lifecycle | fired→`triggered`; contradicted→`invalidated` (pointer to invalidating version); past window→`expired`; never deleted |
| Concurrency | optimistic `expect_version` per facet; stale write loses, re-reads, retries once |

### Debate update rules (spec §3.4 — operationalized)

A new debate **version** requires **all three**:
1. **Semantic distance:** difflib ratio below the existing `_eval_core_debate_shift` threshold (cheap first filter; embedding distance as tiebreak if ambiguous).
2. **Corroboration:** the same cycle produced a material thesis delta — stance change, or conviction move at `magnitude="material"` per the existing `thesis_deltas` classification.
3. **Confidence:** extraction confidence ≥ `τ_high` (0.75).

If only (1): update `current_lean` if warranted (non-versioning), log a *candidate shift* revision row, leave debate text untouched. A debate re-versioning >2 times in 90 days is flagged in the admin endpoint (oscillation alarm, spec §8.4).

---

## PART 5 — INJECTION PIPELINE (pre-synthesis read path)

**Location:** `api.py` memory-block slot (~597–640), as a delimited sibling section to `format_memory_for_prompt` output:

```
=== WHAT YOU ALREADY KNOW ABOUT {TICKER} (prior dossier — a prior to update, not facts to repeat) ===
[staleness line] e.g. "Last materially updated 34d ago — re-verify against fresh evidence."
[debate] [prior state] [moat] [catalysts] [variant] [failure/durability]
=== END PRIOR DOSSIER ===
```

**Hard cap: 350 tokens.** Enforced mechanically (tokenize → trim), not by hoping the formatter stays small.

**Budget, priority order (drop from bottom up when over cap):**

| Pri | Facet | Budget | Filter |
|---|---|---|---|
| 1 (never dropped) | core_debate | 60 | always — the anchor |
| 2 (never dropped) | prior_thesis_state | 40 | one line: stance · conviction · concern · as-of |
| 3 | moat_profile | 80 | only `strength != absent`; `weakening` axes first |
| 4 | catalyst_watchlist | 80 | `status=open` only, top 3 by `conviction_weight` |
| 5 | variant_perception | 50 | top 1–2 divergences by conviction |
| 6 (first dropped) | durability + failure | 40 | only if active failure-mode match exists |

**Relevance filtering (query-conditioned):** router's `question_intent` shifts budget — valuation questions expand variant/durability and shrink catalysts; competitive-risk questions expand weakening-moat axes + failure stage; default split otherwise. Off-topic facets get zero budget rather than compressed text.

**Truncation rules:** trim at facet granularity (whole facet in or out), never mid-sentence; within a facet, drop list items (4th catalyst, 3rd divergence) before shortening prose.

**Null/staleness behavior:** no dossier → inject nothing (current behavior, bit-for-bit). `stale` dossier → still injected but with the staleness warning prominent and confidence-decayed facets excluded.

**Anti-bloat guarantee:** injection size is logged per request (Slice 8 histogram); p100 must stay ≤ 350 tokens, alarm if a regression pushes the formatter over.

---

## PART 6 — TEST PLAN

### Unit tests (Slices 2–3, 5 — run in CI, no DB beyond in-memory SQLite)

| Area | Cases |
|---|---|
| Repos | facet round-trips; `UNIQUE` violations; optimistic-lock conflict (stale `expect_version` rejected); revision append-only (no update path exists); null-session null-object returns |
| Confidence gates | extraction at 0.54 retains existing; 0.56 writes; per-facet independence |
| Hysteresis | single flip suppressed → `pending_flip`; second agreeing flip commits; disagreeing second observation clears pending; `τ_high` single-shot bypass |
| Debate rules | table-driven over the 3-condition matrix (8 combinations — only all-three versions); lean update without re-version; candidate-shift revision logged; oscillation counter |
| Catalyst lifecycle | every legal transition; illegal transitions rejected; invalidation pointer set; expiry by window; specificity gate discards |
| Injection budget | over-budget dossier trims in priority order; debate+prior never dropped; cap enforced at p100 with adversarially long facets; intent-conditioned budget shifts |
| Provenance | facet write without source span → `inferred`; inferred excluded from priority; facet write without evidence ref impossible (transaction test) |

### Integration tests (against test DB, existing `pytest.ini`/`conftest.py` harness)

1. **Cold start:** first analysis of a fresh ticker → dossier created, all facets populated or absent-with-reason, revisions logged.
2. **Warm update:** second analysis → reconciliation (not overwrite); unchanged facets keep versions; mirrored head fields refresh.
3. **Material change:** crafted thesis pair forcing stance flip → debate re-version fires; moat flip enters `pending_flip` not commit.
4. **Extraction failure injection:** structured-output call raises → response unaffected, dossier untouched, error logged.
5. **Injection round-trip:** dossier present → prompt contains delimited block ≤ cap; dossier absent → prompt byte-identical to pre-dossier behavior.
6. **End-to-end `/ask`:** flags on → response carries `dossier_context`; `GET /dossier/{ticker}` matches what extraction wrote.

### Migration tests

- `004` applies clean on a copy of production schema (001+002+003 applied).
- Idempotency: apply twice, no error, no duplicate indexes.
- App boots with tables present and flags off → zero behavior diff (golden `/ask` response comparison).

### Production validation (per slice, gates in PART 7)

| Slice | Gate to proceed |
|---|---|
| 1 | `db_table_count` +8 on admin status; boot clean |
| 4 | 1 week shadow extraction: error rate <1%, ≥90% of analyzed tickers have dossiers, manual spot-check of 5 dossiers reads sane, `/ask` p95 latency unchanged |
| 5 | staging A/B: 10 paired syntheses reviewed — injected runs reference prior view, zero wall-cap/synthesis-fallback regressions, injected block ≤350 tok in 100% |
| 6–7 | live browser verification (9F protocol): banner/moat/catalysts render with production data, `tsc --noEmit` clean, no new hydration warnings |
| 8 | backfill coverage = 100% of watchlist tickers; oscillation alarms quiet for 2 weeks |

---

## PART 7 — IMPLEMENTATION ORDER

Sequenced to keep production risk monotonically bounded: every week ends in a shippable, revertible state.

**Week 1 — Foundations (no production behavior change)**
- Days 1–2: Slice 1 (migration + models) → deploy. Tables exist, empty.
- Days 3–5: Slice 2 (repos + unit tests) → deploy. Dead code in prod, fully tested.

**Week 2 — Extraction brain (still no behavior change)**
- Days 1–4: Slice 3 (extraction service, pure logic + structured-output schema; table-driven tests for gates/hysteresis/debate rules).
- Day 5: Slice 4 wiring behind `dossier_extraction_enabled=off` → deploy dark.

**Week 3 — Shadow writes**
- Day 1: flip extraction flag ON in production. Dossiers accumulate; nothing reads them.
- Days 1–5: monitor (error rate, latency, dossier sanity spot-checks). Build Slice 6 (read API) in parallel; deploy read API end of week (read-only, safe while shadow runs).
- **Gate:** Slice 4 production-validation criteria met before Week 4.

**Week 4 — Injection (the consequential flip)**
- Days 1–2: Slice 5 built + unit tests; deploy behind `dossier_injection_enabled=off`.
- Days 3–4: staging A/B (10 paired syntheses, reviewed).
- Day 5: flip injection ON in production. **Rollback at any sign of synthesis regression = one flag, instant.**

**Week 5 — Surfaces**
- Days 1–4: Slice 7 frontend (banner → moat grid → catalysts → history lane → watchlist columns → company page, in that order — each component independently null-safe and shippable).
- Day 5: live browser verification against production.

**Week 6 — Hardening**
- Slice 8: backfill replay for watchlist tickers, admin status endpoint, observability counters, staleness tuning, threshold calibration review (`τ` values vs. observed extraction-confidence distribution).

**Standing rule:** flags are independent. Extraction can run for months with injection off; injection can be killed without losing accumulated dossiers. The dossier dataset only ever grows under governed writes.

---

## PART 8 — PHASE DEPENDENCIES (how the future plugs in)

The dossier becomes the backbone by contract, not aspiration — each future feature is a **projection of facets that exist from day one**, per spec §9. None requires reshaping a dossier table.

| Future system | Reads | Writes | Connection mechanics |
|---|---|---|---|
| **Setup Similarity Dashboard** | head identity, `dossier_moat_dimension`, `dossier_durability.cycle_position`, `dossier_failure_mode.analog_id` | — | Pairs current-side facets against analog-side profiles in `historical_analogs`, dimension-by-dimension. Current side already structured; feature adds comparison + render only. |
| **Variant Perception** | `dossier_variant` (native facet) | extraction already populates it | Pure render + extraction-prompt enrichment. Zero new plumbing — this is why it was folded into Phase 0. |
| **EV Table** | debate poles → scenarios; open catalysts → scenario trigger conditions; failure-mode analog drawdown → bear anchor; durability signals | — | Consumes dossier qualitatives + financial-data layer quantitatives. Needs no new dossier state. |
| **Failure Mode Fingerprint** | `dossier_failure_mode` (stage, evidence) | stage updates via the existing extraction reconcile step | Enriches `historical_analogs` with `failure_sequence` (their table, not ours); dossier already holds the per-ticker stage pointer. |
| **Durability Score** | `dossier_durability` raw signals | — | Pure read-time scoring function. Signals-not-grades storage means formula changes never need migration. |
| **Analog→Fragility (9G Phase 1)** | `dossier_failure_mode` relevance + drawdown | — | Feeds conviction model's fragility *input*; conviction stays single-sourced on thesis versions (spec §5 boundary). |

**Compatibility guarantees carried into implementation:**
1. Additive-only migrations (`005_…` onward) — no future feature reshapes dossier tables.
2. `meta.schema_version` on the head row from day one.
3. `dossier_evidence_ref` exists before any feature needs provenance — trust never retrofitted.
4. Repos expose facet reads generically (`get_full_dossier`), so new consumers never write bespoke SQL against dossier tables.

---

## DELIVERABLE SUMMARY

1. **Build slices:** 8 (PART 1) — schema → repos → extraction logic → extraction wiring → injection → read API → frontend → hardening.
2. **File list:** 1 migration, 1 models append, 2 repo modules, 2 services, structured-output + prompts extensions, api.py (3 touchpoints), config flags ×2, schemas append, 4 new frontend components + 4 page wirings + api fetcher, observability + admin endpoint, backfill script. (Full enumeration in each slice.)
3. **Migration plan:** single additive `004_company_dossier.sql`, idempotent, startup-registered, flag-gated activation, rollback = flags off (PART 2).
4. **Test plan:** unit (gates/hysteresis/debate/lifecycle/budget/provenance), integration (cold/warm/material/failure/round-trip/e2e), migration (clean + idempotent + zero-diff boot) (PART 6).
5. **Validation plan:** per-slice production gates — table count → shadow-write week → staging A/B → live browser verification → backfill coverage (PART 6 table).
6. **Production rollout sequence:** 6 weeks, dark-deploy then flag-flip pattern, extraction ON week 3, injection ON week 4, UI week 5, hardening week 6; both flags independently revertible at all times (PART 7).

*End of implementation plan. No code, no migrations, no implementation in this document — execution may begin immediately against it.*
