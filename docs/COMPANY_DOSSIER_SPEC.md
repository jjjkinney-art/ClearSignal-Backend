# Company Dossier — Architecture Specification

**Phase:** 9G · Phase 0 (the foundation layer)
**Status:** Design — not yet implemented
**Audience:** Principal/staff engineers, backend + frontend
**Scope:** Design only. No code, no migrations, no implementation in this document.

---

## 0. Purpose and one-paragraph thesis

ClearSignal can already remember *what it concluded* (thesis versions), *how conviction moved* (deltas, investment memory), and *what historically rhymes* (historical analogs). What it cannot do is remember **what it understands about a company** — the moat, the central debate, the catalysts it is watching, the places it disagrees with the market. That understanding is regenerated from scratch on every query, which is the root cause of analyses that read like a strong one-shot AI writeup rather than the running view of an analyst who has covered the name for a year.

The **Company Dossier** is the canonical, persistent, versioned company-intelligence object. It is **read before synthesis** (injection) so the model argues from a prior position, and **updated after synthesis** (extraction) so each analysis compounds. It is the single upstream state object that the rest of Phase 9G — EV Table, Setup Similarity, Variant Perception, Failure Mode Fingerprint, Durability Score — reads from rather than each re-deriving company context independently.

> **Design principle #1 — One canonical company model.** Every downstream 9G feature consumes the dossier. None of them re-derives moat, debate, or catalysts on its own. The dossier is the source of truth; features are projections of it.

---

## 1. Schema design

The dossier is a **composite object keyed by `ticker`**, assembled from a small set of sub-objects. Each sub-object is independently versioned (see §6) and independently confidence-scored. The dossier is *not* a single opaque JSON blob — it is a set of typed facets so that updates, conflicts, and versioning can be reasoned about per facet.

### 1.1 Top-level shape

```
CompanyDossier(ticker)
  identity            — ticker, canonical name, sector, business model
  core_debate         — the one defining question (versioned)
  moat_profile        — structured competitive-advantage model (versioned, multi-dimension)
  catalyst_watchlist  — falsifiable bull/bear triggers (collection, each with lifecycle)
  prior_thesis_state  — denormalized pointer to the most recent thesis conclusion
  variant_perception  — where ClearSignal diverges from consensus (versioned)
  durability_signals  — horizon/cycle metadata feeding the Durability Score
  failure_modes       — references to active failure-pattern matches (links to analogs)
  evidence_refs       — provenance: which thesis_versions / analogs / filings support each facet
  meta                — timestamps, global confidence, schema_version, staleness state
```

### 1.2 Facet detail

#### `core_debate`
The single question that defines the investment case.

| Field | Type | Notes |
|---|---|---|
| `question` | text | e.g. *"Is AI-infrastructure capex a multi-year structural build or a 2024-vintage pull-forward facing 2025 digestion?"* |
| `bull_pole` / `bear_pole` | text | The two sides of the debate, stated as falsifiable positions. |
| `current_lean` | enum | `bull` / `bear` / `balanced` — where the latest synthesis landed. |
| `resolution_signal` | text | What observable would resolve the debate. |
| `version` | int | Monotonic; increments only on a *material* reframing (see §3.4). |
| `confidence` | float 0–1 | Extraction confidence for this debate framing. |
| `first_seen_at` / `updated_at` | ts | |

> **Grounding note.** `core_debate` and `core_market_debate` already exist as **transient fields on `InvestmentThesis`** (`schemas.py`) and are compared via difflib inside `thesis_memory_service` (`_eval_core_debate_shift`). The dossier's job is to **promote this transient output into canonical, versioned state** — not to invent a new concept. The existing difflib comparison becomes the *change detector that decides whether to cut a new debate version* (§3.4), rather than a throwaway per-snapshot diff.

#### `moat_profile`
The structured competitive-advantage model — the facet that most directly fixes "generic."

| Field | Type | Notes |
|---|---|---|
| `dimensions` | list of `MoatDimension` | One row per moat axis. |
| `composite_strength` | enum | `wide` / `narrow` / `eroding` / `none` — rolled up from dimensions. |
| `version` | int | |
| `confidence` | float | |

`MoatDimension`:

| Field | Type | Notes |
|---|---|---|
| `axis` | enum | `ecosystem_lockin`, `supply_chain_control`, `switching_costs`, `network_effects`, `regulatory_ip`, `management_execution`. Fixed taxonomy (extensible, versioned). |
| `strength` | enum | `strong` / `moderate` / `weak` / `absent`. |
| `trend` | enum | `strengthening` / `stable` / `weakening`. |
| `rationale` | text | One sentence, company-specific. |
| `vulnerability` | text | The specific vector that erodes this axis (e.g. *CUDA → open-source compute / hyperscaler custom silicon*). |
| `last_changed_at` | ts | |

#### `catalyst_watchlist`
A **collection** (not a single versioned object) — each catalyst has its own lifecycle.

| Field | Type | Notes |
|---|---|---|
| `id` | uuid | Stable across analyses so hit/miss can be tracked. |
| `statement` | text | Specific and falsifiable: *"Datacenter revenue accelerates >$28B in a quarter without China re-rating."* |
| `direction` | enum | `bull_trigger` / `bear_trigger`. |
| `specificity` | float 0–1 | Gate: vague catalysts (< threshold) are dropped, not stored. |
| `expected_window` | text | e.g. `Q1-2026`, `next-2-earnings`. |
| `status` | enum | `open` / `triggered` / `invalidated` / `expired`. |
| `conviction_weight` | float | How much this catalyst should move conviction if it fires. |
| `created_at` / `resolved_at` | ts | |
| `source_version_id` | fk | The thesis_version that introduced it. |

#### `prior_thesis_state` (denormalized pointer, **not** a copy)
A thin cache of the most recent conclusion so injection doesn't need a join-heavy read. It **references**, never duplicates, `thesis_versions`.

| Field | Type | Notes |
|---|---|---|
| `latest_version_id` | fk → `thesis_versions.id` | Source of truth lives there. |
| `stance` | enum | mirror of latest |
| `conviction` | float | mirror of latest `confidence_score` |
| `primary_concern` | text | mirror of dominant concern |
| `as_of` | ts | |

> This facet is intentionally a **read-through cache**, not authoritative state. See §5 anti-duplication rules.

#### `variant_perception`
Where ClearSignal disagrees with implied consensus.

| Field | Type | Notes |
|---|---|---|
| `divergences` | list | Each: `dimension` (revenue trajectory / moat durability / competitive risk / valuation), `consensus_view`, `clearsignal_view`, `direction` (`more_bullish`/`more_bearish`), `conviction`. |
| `version` | int | |
| `confidence` | float | |

#### `durability_signals`
Feeds the Durability Score (Phase 5) — stored as raw signals, not a computed grade, so the scoring logic can evolve without a migration.

| Field | Type | Notes |
|---|---|---|
| `cycle_position` | enum | `early` / `mid` / `late` / `unknown`. |
| `catalyst_proximity_days` | int | Nearest open catalyst window. |
| `analog_time_to_trough_days` | int | From the top failure-mode analog. |
| `conviction_trend` | enum | mirrors investment memory direction. |
| `horizon_hint` | enum | `trade` / `investment` / `secular` — extracted, not yet scored. |

#### `failure_modes`
Active failure-pattern matches — **references** into `historical_analogs`, plus the matched stage.

| Field | Type | Notes |
|---|---|---|
| `analog_id` | fk → `historical_analogs.id` | No analog data is copied. |
| `sequence_stage` | int | "Stage 2 of 5". |
| `stage_evidence` | text | Why we believe we're at this stage. |
| `relevance_at_match` | float | Snapshot of relevance when matched. |
| `matched_at` | ts | |

#### `evidence_refs` (provenance spine)
Every non-trivial facet value points back to what justified it. This is the **falsifiability requirement** from the 9G review made structural.

| Field | Type | Notes |
|---|---|---|
| `facet` | enum | which sub-object |
| `claim_hash` | str | stable id of the specific claim |
| `source_type` | enum | `thesis_version` / `analog` / `filing` / `financial_data` / `inferred` |
| `source_id` | str | fk where applicable |
| `as_of` | ts | |

> **`inferred` is a first-class source type.** A claim with no harder source is *labeled* inferred, never silently presented as sourced. The frontend renders sourced vs inferred distinctly (§7).

#### `meta`

| Field | Type | Notes |
|---|---|---|
| `schema_version` | int | dossier schema, for forward migration |
| `global_confidence` | float | weakest-link or weighted roll-up of facet confidences |
| `staleness_state` | enum | `fresh` / `aging` / `stale` (§8.1) |
| `last_full_update_at` | ts | |
| `analysis_count` | int | how many syntheses have touched this dossier |

---

## 2. Persistence architecture

### 2.1 Storage substrate
Reuse the existing SQLAlchemy + raw-SQL-migration stack (`app/db/models.py`, `app/db/migrations/00X_*.sql`, `app/db/repositories/`). No new database technology. The dossier is **relational, not a document store** — facet-level versioning and conflict resolution require row-level granularity that a single JSON blob would forfeit.

### 2.2 Single-row vs append-only — **hybrid, and the split is deliberate**

> **Design principle #2 — Current state is single-row; history is append-only.** Reads on the hot path (injection) hit exactly one row per facet. Auditability lives in side tables that injection never touches.

Three table classes:

**(a) `company_dossier` — single-row-per-ticker (the "head").**
One row per ticker (`UNIQUE(ticker)`, mirroring the `ticker_memory` pattern). Holds the *current* pointer/version numbers and the denormalized `prior_thesis_state` and `meta`. This is the only table injection reads. O(1) lookup.

**(b) Facet "current" tables — single-row-per-(ticker, facet-key).**
`dossier_core_debate`, `dossier_moat_dimension` (one row per ticker×axis), `dossier_catalyst` (one row per catalyst id, lifecycle-mutated in place), `dossier_variant`, `dossier_durability`, `dossier_failure_mode`. These hold the live value and a `version` integer.

**(c) `dossier_revision` — append-only audit log (the "history").**
Every material change to any facet appends one immutable row: `{id, ticker, facet, prev_version, new_version, change_summary, diff_json, confidence, source_version_id, created_at}`. Never updated, never deleted. This is the time-travel + auditability layer and the substrate for the History page (§7.2). It is the dossier analogue of `thesis_deltas`.

Catalysts are mutated **in place** for lifecycle transitions (`open → triggered`) but each transition still appends a `dossier_revision` row. The catalyst row is current-state; the revision log is the audit trail.

### 2.3 Relationships

```
ticker (logical key, normalized via app/db/ticker_normalizer.py)
  │
  ├─1:1─ company_dossier (head)
  │        ├─ prior_thesis_state.latest_version_id ─FK→ thesis_versions.id
  │        └─ meta
  │
  ├─1:1─ dossier_core_debate
  ├─1:N─ dossier_moat_dimension      (N = axes, bounded ~6)
  ├─1:N─ dossier_catalyst            (bounded; expired ones archived)
  ├─1:1─ dossier_variant
  ├─1:1─ dossier_durability
  ├─1:N─ dossier_failure_mode ───FK→ historical_analogs.id
  │
  └─1:N─ dossier_revision (append-only, all facets)
```

There is **no foreign key from the dossier into `ticker_memory`** — both are keyed by the same normalized ticker and joined logically, keeping the dossier independent of the memory subsystem's lifecycle.

### 2.4 Indexes

| Table | Index | Why |
|---|---|---|
| `company_dossier` | `UNIQUE(ticker)` | O(1) injection read. |
| `dossier_moat_dimension` | `(ticker, axis)` unique | one row per axis. |
| `dossier_catalyst` | `(ticker, status)` | injection filters to `open`; watchlist UI filters by status. |
| `dossier_failure_mode` | `(ticker)`, `(analog_id)` | reverse lookup "which tickers match this analog." |
| `dossier_revision` | `(ticker, facet, created_at)` | history page timeline; never on hot path. |

### 2.5 Read/write paths

- **Injection read (hot):** single indexed read of `company_dossier` + at most the bounded facet tables for the ticker. Target: one round-trip, cacheable.
- **Extraction write (post-synthesis, off the user's critical path):** runs after the response is dispatched (same pattern as the 9F historical-evidence post-dispatch hook in `api.py`). Never blocks the user-visible response.

---

## 3. Extraction pass (after synthesis)

### 3.1 Where it runs
Post-dispatch, mirroring the existing 9F pattern (`api.py` historical-evidence stamping) and `persist_analysis_result`. The user's response is already streamed before extraction begins. Extraction failure must **never** corrupt the dossier or the response — it degrades to "no update this cycle."

### 3.2 Pipeline
1. **Harvest** the just-produced `InvestmentThesis` (already contains `core_debate`, `core_market_debate`, `key_risks`, `what_changes_the_thesis`, `conviction_dimensions`, `setup_label`, moat-adjacent narrative).
2. **Structured extraction passes** (one focused LLM call per facet group, or a single multi-facet structured-output call via `app/structured_output.py`) to normalize prose into the typed facets in §1.
3. **Load** the existing dossier (or initialize an empty one on first analysis).
4. **Reconcile** each facet against its current value using the update rules below.
5. **Commit**: update facet "current" rows, append `dossier_revision` rows for material changes, refresh `company_dossier` head + `meta`.

### 3.3 Update rules (per facet)

> **Design principle #3 — Updates are governed, not trusting.** A single synthesis is one noisy observation. Facets move on evidence, not on every restatement.

| Rule | Detail |
|---|---|
| **Confidence gate** | A new facet value is written only if extraction `confidence ≥ τ_write` (proposed 0.55). Below that, the existing value is retained and the observation is logged but not promoted. |
| **Specificity gate (catalysts)** | Catalysts below `specificity` threshold (proposed 0.5) are discarded, not stored. Prevents "monitor for a catalyst" placeholders from polluting the watchlist. |
| **Hysteresis (trends)** | Moat `trend` and `composite_strength` only flip after **2 consecutive** syntheses agree, or one synthesis with `confidence ≥ τ_high` (0.75). Single-shot flips are suppressed. This is the primary defense against oscillation (§8.4). |
| **Monotonic versioning** | A facet `version` increments only on a *material* change (semantic, not cosmetic). Reworded-but-equivalent text does not cut a version. |
| **Catalyst lifecycle** | Existing open catalysts are matched against the new thesis. Fired → `triggered`; contradicted → `invalidated`; past window → `expired`. New catalysts are appended. Catalysts are **never silently deleted** — only lifecycle-transitioned, preserving hit/miss history. |
| **Provenance required** | Every written facet value writes/updates an `evidence_refs` row. A value with no harder source is tagged `inferred`. |

### 3.4 When does the core debate change?

The core debate is the most identity-defining facet; it must be **sticky**. A new debate **version** is cut only when *all* hold:

1. **Semantic distance** between prior and new debate framing exceeds threshold (reuse the existing difflib ratio in `_eval_core_debate_shift` as the cheap first filter; escalate to embedding distance if difflib is ambiguous).
2. The change is corroborated by a **material thesis delta** (stance change, or conviction move beyond the memory subsystem's `material` magnitude) — i.e., the debate shifted *because the case shifted*, not because the model phrased it differently.
3. Extraction `confidence ≥ τ_high`.

If only (1) holds, the debate text is **not** re-versioned; instead `current_lean` may update (a cheap, non-versioning field) and the divergence is logged to `dossier_revision` as a *candidate* shift. This prevents debate oscillation while still recording that wording moved.

### 3.5 Conflict resolution
- **New vs existing, both confident:** newer wins **only** if it clears the hysteresis bar; otherwise existing is retained and conflict is logged.
- **Contradictory catalysts** (a new bull trigger that negates an open bear trigger): both are kept; the older is marked `invalidated` with a pointer to the invalidating version. History is never destroyed.
- **Concurrent writes** (two analyses racing): facet writes are guarded by optimistic concurrency on the facet `version`; a stale write loses and re-reads. The dossier head carries a row-version for the same reason.

---

## 4. Injection pass (before synthesis)

### 4.1 Goal
Make synthesis *positionally aware* — arguing from a remembered prior view — without flooding the prompt. The injected block is a **briefing memo to the analyst**, not a data dump.

### 4.2 Placement
Injected alongside the existing memory block in `api.py` (the `format_memory_for_prompt` slot, ~`api.py:597–640`), as a **distinct, clearly delimited section** in the synthesis system context:

```
=== WHAT YOU ALREADY KNOW ABOUT {TICKER} (prior dossier) ===
... compact briefing ...
=== END PRIOR DOSSIER ===
```

It precedes the live evidence/agent outputs so the model treats the dossier as *standing context* and the fresh evidence as *this cycle's update*.

### 4.3 Token budget — hard cap

> **Design principle #4 — Bounded, relevance-filtered injection.** The dossier can grow without bound; the injected view cannot. Target ≤ ~350 tokens.

Budget allocation (approximate):

| Facet | Budget | Filtering rule |
|---|---|---|
| core_debate | ~60 tok | Always inject (it's the anchor). |
| moat_profile | ~80 tok | Only dimensions where `strength != absent`; lead with `weakening` axes. |
| catalyst_watchlist | ~80 tok | Only `status=open`, top 3 by `conviction_weight`. |
| prior_thesis_state | ~40 tok | One line: stance, conviction, primary concern, as-of. |
| variant_perception | ~50 tok | Top 1–2 divergences by conviction. |
| durability / failure | ~40 tok | Only if an active failure-mode match exists. |

If the assembled block exceeds budget, drop facets in reverse priority order: failure/durability → variant → catalysts(tail) → moat(stable axes). The debate and prior state are never dropped.

### 4.4 Relevance filtering by question
The injected slice is **query-conditioned**. A valuation question pulls the valuation divergence + cycle position; a competitive-risk question pulls weakening moat axes + active failure-mode stage. The router's `question_intent` (already on `InvestmentThesis`) selects which facets get their budget expanded. This keeps injection both small and on-topic.

### 4.5 Staleness annotation
The injected block states freshness: *"(dossier last materially updated 34 days ago — treat as prior, re-verify)."* The model is told the dossier is a **prior to update, not a fact to repeat**. This is a prompt-level mitigation for stale-dossier risk (§8.1).

### 4.6 First-analysis behavior
No dossier → inject nothing (null-object pattern, consistent with `get_memory_context` returning `None`). Synthesis runs cold; extraction *creates* the dossier. No special-casing downstream.

---

## 5. Relationship to existing systems (anti-duplication)

> **Design principle #5 — The dossier holds understanding, not events or conclusions.** It is the only facet of state that models the *company*. Everything else models *analyses* or *evidence*.

| System | Owns | Dossier relationship | Anti-duplication rule |
|---|---|---|---|
| **Thesis Evolution** (`thesis_versions`, `thesis_deltas`) | Append-only record of each analysis and the diffs between them. | Dossier `prior_thesis_state` **references** `thesis_versions.id`; extraction is *triggered by* a new version. | Dossier never copies thesis narrative. It stores a pointer + a few mirrored scalars for hot-path reads only. |
| **Investment Memory** (`ticker_memory`, `memory_context`) | Roll-up statistics: query count, conviction trend, dominant concern, notable events. | Dossier `durability_signals.conviction_trend` mirrors the memory direction; both keyed by ticker. | Memory = *quantitative trajectory*. Dossier = *qualitative model*. Memory answers "how has conviction moved?"; dossier answers "what is the debate / moat / catalysts?" No overlap in semantics. |
| **Historical Evidence** (`historical_analogs`, `evidence_engine`) | The curated cross-company analog library + retrieval. | Dossier `failure_modes` **references** `historical_analogs.id` + matched stage. | Dossier never copies analog rows. It records *which* analogs are live for this ticker and *where in the failure sequence* we sit. Analog content stays in the evidence DB. |
| **Conviction Model** (`conviction_dimensions`, `setup_label`, multipliers on `InvestmentThesis`) | Per-analysis scoring of evidence/fragility/asymmetry. | Dossier *reads* conviction outputs during extraction (to populate durability + variant). In 9G Phase 1, the analog signal feeds the **fragility input**, not the dossier. | Dossier does **not** store a conviction score of its own. Conviction is per-analysis and lives on the thesis version. Storing it in the dossier would create two sources of truth. |
| **Router** (`question_intent`, company detection) | Classifies the incoming question; resolves the entity. | Router output **selects** which dossier facets get injection budget (§4.4). | Router owns *routing*; dossier owns *content*. Router never writes the dossier; dossier never re-classifies questions. |

**The clean mental model:**
- `thesis_versions` = *"what we said, each time."*
- `ticker_memory` = *"how the numbers moved."*
- `historical_analogs` = *"what the world has seen before."*
- **`company_dossier` = *"what we understand about this company."***

Only the dossier models the company itself. That gap is precisely what Phase 0 closes.

---

## 6. Versioning strategy

### 6.1 Per-facet, not per-dossier
Versioning a single monolithic dossier would make the moat version churn every time a catalyst fires. Instead **each facet carries its own monotonic `version`**, and the `dossier_revision` append-only log records every material transition with `{facet, prev_version, new_version, diff, confidence, source_version_id}`.

### 6.2 What counts as a version-cutting change

| Facet | Cuts a new version when… | Does *not* version on… |
|---|---|---|
| core_debate | §3.4 (semantic shift + material thesis delta + high confidence) | rewording; lean flips (lean is a non-versioning field) |
| moat_profile | a dimension `strength` or `trend` flips after hysteresis; an axis added/retired | rationale rewording |
| variant_perception | a divergence direction flips or a new divergence appears | restating the same divergence |
| catalyst | (catalysts version via lifecycle, not text) — each status transition logs a revision | re-mention of an open catalyst |
| durability_signals | cycle position or horizon hint changes | proximity recomputation |

### 6.3 Auditability guarantees
- Every material change is reconstructable from `dossier_revision` (immutable, time-ordered).
- Each revision links to the `thesis_version` that caused it → full causal chain: *"moat ecosystem axis flipped strong→moderate on 2026-03-14, caused by thesis version X, confidence 0.78, because: <stage_evidence>."*
- The History page (§7.2) renders this directly.
- No facet value can change without either (a) a revision row, or (b) being a non-versioning field (lean, proximity) explicitly enumerated as such.

### 6.4 Schema evolution
`meta.schema_version` allows the dossier shape itself to evolve. New facets are added as new tables (additive migrations, the 9F precedent) — never by reshaping a blob. Old dossiers without the facet simply read as null until the next extraction populates them.

---

## 7. Frontend surfaces

The dossier is **read-through** on the frontend — components consume facets already present on the `/ask` response (extended) or a dedicated `GET /dossier/{ticker}` endpoint for the standalone views. No business logic in the client.

### 7.1 Analysis page (`app/(product)/analyze`)
- **Core Debate banner** — single persistent line between the thesis header and the verdict: *"Core Debate: Is AI capex durable into 2026? · ClearSignal leans bear · updated 12d ago."* Click → expands poles + resolution signal.
- **Moat profile grid** — in the memory/context region: axes with strength + directional arrows (↑/→/↓), weakening axes surfaced first.
- **Catalyst watchlist** — open catalysts with direction + window; triggered/invalidated shown struck-through with date.
- **Provenance affordance** — sourced facets show a source chip; `inferred` facets are visually distinct (the §1 evidence_refs requirement made visible). Reuses the existing forensic-audit visual language.

### 7.2 History page (`app/(product)/history`)
- **Dossier timeline** — rendered from `dossier_revision`: a per-facet change log. *"Moat: ecosystem lock-in strong → moderate (Mar 14) · Debate reframed (Jan 2) · Catalyst fired: datacenter rev >$28B (Feb 26)."*
- This is the dossier's natural home for the "what we learned over time" story — distinct from thesis evolution (which shows conviction trajectory). History page gets **two lanes**: conviction trajectory (existing) + dossier evolution (new).

### 7.3 Watchlist page (`app/(product)/watchlist`)
- **Dossier-derived columns** per ticker: current lean, composite moat (with trend arrow), count of open catalysts, nearest catalyst window, staleness badge.
- **Staleness surfacing** — `stale` dossiers flagged so the user knows which names need a refresh. Turns the watchlist into a coverage-health dashboard, not just a price list.

### 7.4 Company page (`app/(product)/company`)
The natural canonical home: render the **full dossier** as the company's standing intelligence profile, with each facet expandable and its revision history inline.

---

## 8. Failure modes and mitigations

### 8.1 Stale dossier
**Risk:** an old dossier is injected as if current; the model repeats a moat assessment that markets have moved past.
**Mitigations:** (a) `staleness_state` computed from `last_full_update_at` (`fresh < 14d`, `aging < 60d`, `stale ≥ 60d` — tune per sector velocity); (b) injection **annotates** age and instructs the model to treat the dossier as a prior to re-verify (§4.5); (c) watchlist surfaces stale names (§7.3); (d) confidence decays with age so a stale high-confidence claim doesn't outrank fresh evidence.

### 8.2 Hallucinated updates
**Risk:** extraction invents a moat axis or catalyst not supported by the synthesis.
**Mitigations:** (a) `τ_write` confidence gate; (b) **provenance required** — every written value needs an `evidence_refs` row; values that cannot be tied to the thesis text are tagged `inferred` and excluded from injection budget priority; (c) fixed moat-axis taxonomy prevents invented dimensions; (d) extraction is constrained structured output (`app/structured_output.py`), not free-form.

### 8.3 Conflicting updates
**Risk:** two analyses (or two facets within one) disagree.
**Mitigations:** optimistic-concurrency on facet `version` (§3.5); newer wins only past hysteresis; contradictions are preserved (invalidated, not deleted) with causal pointers; all conflicts logged to `dossier_revision`.

### 8.4 Oscillating debates / flip-flopping moat
**Risk:** the core debate or moat trend flips every analysis, destroying the "stable analyst view" the dossier exists to create.
**Mitigations:** (a) **hysteresis** — trends/strength flip only on 2 consecutive agreeing syntheses or one high-confidence one (§3.3); (b) debate re-versioning requires a corroborating *material* thesis delta, not just text drift (§3.4); (c) `current_lean` absorbs minor sentiment swings as a cheap non-versioning field so the debate *text* stays stable while lean breathes; (d) a debate that re-versions more than N times in a window is flagged for review (instability is itself a signal).

### 8.5 Prompt pollution
**Risk:** the injected block grows, derails synthesis, or biases it toward confirming the prior.
**Mitigations:** (a) hard token cap with priority-ordered dropping (§4.3); (b) clear delimiters so the model separates "prior" from "this cycle's evidence"; (c) injection framed as *"a prior to update,"* explicitly inviting disagreement — the dossier must not become a self-reinforcing echo chamber; (d) Phase 9G's Red Team / Variant Perception features actively reward *divergence* from the prior, structurally counterbalancing confirmation bias; (e) relevance filtering (§4.4) keeps off-topic facets out entirely.

### 8.6 Extraction blocking the response (operational)
**Risk:** the post-synthesis extraction pass slows or breaks the user path.
**Mitigation:** extraction is strictly post-dispatch and best-effort (the 9F precedent). Any failure degrades to "no dossier update this cycle" and is logged; the user response is unaffected.

---

## 9. Future compatibility — how Phase 9G features plug in

The dossier is designed as the **substrate** the rest of 9G reads. Each downstream feature is a *projection or consumer* of dossier facets, never an independent re-derivation.

| Future feature | Reads from dossier | Writes to dossier | Plug-in contract |
|---|---|---|---|
| **Setup Similarity Dashboard** | `identity`, `moat_profile`, `durability_signals.cycle_position`; pairs against `failure_modes.analog_id`. | nothing (read-only consumer). | Compares current company facets vs the analog's stored profile dimension-by-dimension. The dossier already holds the "current side"; the analog DB holds the "historical side." No new state. |
| **Variant Perception** | already a **native facet** (`variant_perception`). | the facet itself, via extraction. | The feature is just the render + extraction of an existing facet — zero new plumbing. This is why it was folded into Phase 0. |
| **EV Table** | `core_debate` (poles → scenarios), `catalyst_watchlist` (triggers → scenario conditions), `failure_modes` (bear-case drawdown anchor), `durability_signals`. | nothing. | Bull/Base/Bear scenarios map onto debate poles + catalysts; bear return anchors to the failure-mode analog's drawdown. The dossier supplies every qualitative input; the financial-data layer supplies the numbers. |
| **Failure Mode Fingerprint** | `failure_modes` (analog ref + `sequence_stage` + `stage_evidence`). | updates `sequence_stage` via extraction as signals progress. | The facet exists from day one; the feature enriches `historical_analogs` with `failure_sequence` and updates the stage pointer. |
| **Durability Score** | `durability_signals` (stored raw, not pre-scored). | nothing (scoring is a pure function of stored signals). | Because signals are stored raw, the scoring formula can change without a migration. The score is computed at read time. |
| **Analog→Fragility (Phase 1)** | `failure_modes` relevance + drawdown. | nothing — feeds the conviction model's fragility *input*, per §5. | Keeps conviction single-sourced on the thesis version; dossier supplies the analog linkage only. |

> **Forward-compatibility guarantees:**
> 1. **Additive-only growth** — new facets arrive as new tables (9F precedent), never as reshaped blobs. Existing readers are unaffected.
> 2. **Raw-signal storage** — durability and similar derived metrics store inputs, not computed grades, so scoring logic evolves freely.
> 3. **Reference-not-copy** — every cross-system link (analogs, thesis versions, financial data) is a foreign-key reference, so the dossier never goes stale relative to its sources beyond the controlled `staleness_state`.
> 4. **Provenance from day one** — `evidence_refs` exists before any feature needs it, so trust/traceability never requires a retrofit.

---

## 10. Open questions for implementation phase

These are flagged for the build phase; none block the architecture:

1. **Extraction cost** — one multi-facet structured call vs several focused calls. Lean: one structured-output call to bound latency/cost, fan out only if quality suffers.
2. **Confidence thresholds** (`τ_write`, `τ_high`, specificity, staleness windows) — values proposed above are starting points to calibrate against real syntheses, ideally per-sector.
3. **Moat-axis taxonomy finality** — the six axes are a strong default; confirm against a sample of covered names before locking, since adding axes later is additive but retiring them is a migration.
4. **Dossier read endpoint shape** — extend `/ask` response vs a dedicated `GET /dossier/{ticker}`. Lean: both — `/ask` carries the injected slice for the analysis page; the standalone endpoint serves the company/history/watchlist views.

---

*End of specification. Design only — implementation, schema migrations, and code are out of scope for this document.*
