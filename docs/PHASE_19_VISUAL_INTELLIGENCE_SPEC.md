# Phase 19 — Visual Intelligence Layer

## Status

Architecture specification. No implementation.

---

## Problem

ClearSignal can answer seven foundational questions:

1. **What happened?** — Memory, ticker analysis, evidence pipeline
2. **What resembles this?** — Similarity Engine (Phase 11)
3. **What tends to happen next?** — Forecasting Engine (Phase 12)
4. **What matters most?** — Decision Intelligence (Phase 13)
5. **What happens if X changes?** — Scenario Engine (Phase 14)
6. **What have I learned about this user?** — User Learning (Phase 15)
7. **What matters to me right now?** — Personal Experience (Phase 18)

The intelligence exists. Users cannot absorb it quickly enough.

A forecast probability distribution is a JSON array. A scenario transmission path is a nested dict. A similarity network is a list of edges. A portfolio exposure map is a table of position weights. Each requires mental reconstruction — the user must read structured data and build a picture in their head.

Humans process visual information 60,000 times faster than text. A chart communicates in milliseconds what a table communicates in minutes.

---

## Goal

Transform ClearSignal from:

> "Read the intelligence."

into:

> "See the intelligence."

---

## Core Principle

**Phase 19 does not create intelligence. Phase 19 visualizes intelligence.**

It consumes the output of every upstream phase and produces visual representations: charts, maps, diagrams, timelines, networks, distributions, and AI-generated explanatory images. The intelligence is upstream. The visual is Phase 19.

Phase 19 never writes to any truth table. It reads forecasts, scenarios, decisions, similarities, preferences, portfolio state, and personal experience context — then produces visual specifications and rendered assets. The truth is upstream. The rendering is Phase 19.

---

## Upstream Dependencies

| Phase | What Phase 19 Reads | Visual Categories Served |
|---|---|---|
| 9G | Ticker memory, dossier state, evidence entries | Thesis evolution, evidence timelines |
| 10B | Watchlist state, thesis snapshots | Watchlist views, thesis change maps |
| 10D | Portfolio positions, insights, allocation | Exposure maps, concentration maps, dependency maps |
| 11 | Similarity edges, feature vectors, analog clusters | Similarity networks, analog clusters, precedent maps |
| 12 | Forecast vectors, evidence, calibration | Probability distributions, confidence bands, forecast evolution |
| 13 | Decision priorities, evidence, ranking | Attention priorities, decision trees, impact rankings |
| 14 | Scenario snapshots, evidence, transmission paths | Scenario trees, transmission diagrams, what-changed maps, impact maps |
| 15 | Learned preferences, signal events | Preference heatmaps, engagement patterns |
| 18 | Experience events, attention queue, brief, cursors | Attention timelines, change timelines, resume timelines |

Phase 19 writes to its own tables only (defined below). It never writes to any table listed above.

---

## Visual Categories

### 1. Market Visuals

Visualizations of current and historical market data contextualized by ClearSignal intelligence.

| Visual | Inputs | Output |
|---|---|---|
| Price chart with event markers | Price data, memory events, thesis changes | Annotated time-series chart |
| Performance chart | Price data, portfolio positions | Return chart with benchmark overlay |
| Volatility overlay | Price data, scenario plausibility | Price chart with volatility bands |
| Evidence timeline | Memory entries, evidence timestamps | Chronological evidence markers on timeline |

### 2. Forecast Visuals

Visualizations of the Forecasting Engine's probability assessments.

| Visual | Inputs | Output |
|---|---|---|
| Probability distribution | Forecast vector (bull/base/bear probabilities) | Horizontal bar or density chart showing outcome weights |
| Outcome tree | Forecast scenarios, conditional probabilities | Tree diagram with branching outcomes |
| Confidence band | Forecast vector, calibration history | Time-series with widening confidence envelope |
| Forecast evolution | Forecast vector history (snapshots over time) | Line chart showing how forecast shifted over time |

### 3. Scenario Visuals

Visualizations of the Scenario Engine's conditional analysis.

| Visual | Inputs | Output |
|---|---|---|
| What-changed map | Scenario snapshot diffs | Before/after comparison diagram |
| Transmission-path diagram | Scenario transmission edges | Directed graph: trigger → intermediate → impact |
| Scenario tree | Active scenarios per entity | Tree with plausibility scores on branches |
| Impact map | Scenario impact assessments, affected entities | Node-link diagram showing impact propagation |

### 4. Similarity Visuals

Visualizations of the Similarity Engine's relationship analysis.

| Visual | Inputs | Output |
|---|---|---|
| Similarity network | Similarity edges, scores | Force-directed graph of related entities |
| Analog cluster | Analog matches, similarity scores | Grouped cluster diagram |
| Precedent map | Historical analogs, outcome data | Timeline showing historical precedent |
| Relationship graph | Multi-dimensional similarity edges | Edge-weighted network diagram |

### 5. Portfolio Visuals

Visualizations of portfolio state and risk.

| Visual | Inputs | Output |
|---|---|---|
| Exposure map | Portfolio positions, sector/geography tags | Treemap or sunburst of exposure by dimension |
| Concentration map | Portfolio weights, position sizes | Heat map of concentration risk |
| Dependency map | Similarity edges between portfolio holdings | Network showing correlated positions |
| Scenario exposure | Scenario impacts × portfolio positions | Matrix showing portfolio sensitivity to scenarios |

### 6. Personal Experience Visuals

Visualizations of the user's personal intelligence layer.

| Visual | Inputs | Output |
|---|---|---|
| Attention timeline | Experience events, attention scores | Timeline of what demanded attention and when |
| Change timeline | Change candidates, recency scores | Timeline of what changed since last visit |
| Resume timeline | Resume candidates, continuation scores | Timeline of paused research and what changed |
| Thesis evolution | Memory entries, thesis snapshots over time | Multi-panel showing thesis drift per entity |

### 7. AI-Generated Visual Explanations

Context-rich, question-driven visual answers produced by combining structured intelligence with AI image generation.

| Question Pattern | Intelligence Consumed | Visual Output |
|---|---|---|
| "How has X changed?" | Memory diffs, forecast evolution, thesis snapshots | Annotated change timeline or evolution diagram |
| "Why does X matter?" | Similarity network, supply chain data, portfolio exposure | Ecosystem or supply-chain map |
| "What changed since my last visit?" | Personal experience events, change candidates | Personal change timeline with evidence markers |
| "What is the risk?" | Scenario impacts, portfolio exposure, concentration | Risk map combining scenario and portfolio views |
| "What do these have in common?" | Similarity edges, shared evidence, analog matches | Venn/cluster diagram of shared characteristics |

AI-generated visuals follow the same explainability and safety rules as all other visuals. The AI produces the visual layout and annotations — the underlying data is always from upstream intelligence, never invented by the image generation model.

---

## Architecture

### Layer Diagram

```
┌─────────────────────────────────────────────────────────┐
│                    Frontend / API                        │
│    GET /visual/:type   GET /visual/explain   WebSocket  │
└──────────────────────┬──────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────┐
│              PHASE 19 — Visual Intelligence              │
│                                                          │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐   │
│  │  Visual      │  │  Visual      │  │  AI Visual   │   │
│  │  Orchestrator│  │  Renderer    │  │  Generator   │   │
│  │              │  │              │  │              │   │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘   │
│         │                 │                 │            │
│  ┌──────▼─────────────────▼─────────────────▼────────┐  │
│  │              Visual Data Assembler                 │  │
│  │    Reads all upstream phases                       │  │
│  │    Produces typed visual data specifications       │  │
│  │    Enforces explainability gate                    │  │
│  └──────────────────────┬────────────────────────────┘  │
│                         │                                │
│  ┌──────────────────────▼────────────────────────────┐  │
│  │              Visual Validation Engine              │  │
│  │    Validates every visual answers 3 questions      │  │
│  │    Blocks visuals without evidence                 │  │
│  │    Enforces no-advice boundary                     │  │
│  └──────────────────────┬────────────────────────────┘  │
│                         │                                │
└─────────────────────────┼────────────────────────────────┘
                          │  reads only
┌─────────────────────────▼────────────────────────────────┐
│  Phase 9G │ 10B │ 10D │ 11 │ 12 │ 13 │ 14 │ 15 │ 18    │
│  Memory   │Watch│Port │Sim │Fore│Dec │Scen│Learn│Exper  │
└──────────────────────────────────────────────────────────┘
```

### Service Decomposition

| Service | Responsibility |
|---|---|
| `visual_orchestrator_service` | Top-level coordinator. Receives a visual request (type + parameters), assembles data, selects renderer, validates output, returns visual specification. |
| `visual_data_assembler_service` | Reads upstream phase data and produces typed visual data specifications. One assembler function per visual category. Pure reads, no writes. |
| `visual_renderer_service` | Converts visual data specifications into renderable output: SVG for charts/diagrams, structured JSON for frontend-rendered visuals, or image generation prompts for AI visuals. |
| `ai_visual_generator_service` | Handles AI-generated visual explanations. Converts structured intelligence data into image generation prompts. Validates that generated visuals contain no advisory language. |
| `visual_validation_service` | Validates every visual against the three required questions (what, why, evidence). Blocks visuals that fail validation. Enforces no-advice boundary. |
| `visual_cache_service` | Manages visual asset caching. Visuals are expensive to generate — cache by (visual_type, entity_key, data_hash, user_id). Invalidate on upstream data change. |
| `visual_shadow_journal_service` | Shadow-mode journaling: records what visuals would be generated, which passed validation, which were blocked. Append-only to `visual_experience_event`. |
| `visual_observability_service` | Observability snapshot, admin status endpoint, safe_state checks. |

---

## Rendering Strategy

### Three Rendering Tiers

| Tier | When | How | Latency |
|---|---|---|---|
| **Structured JSON** | Frontend has a chart component for this type | Return typed data spec; frontend renders | < 100ms |
| **Server-side SVG** | No frontend component exists; static chart needed | Generate SVG on backend; return as string or URL | < 500ms |
| **AI-generated image** | Question-driven or explanatory visual; no template fits | Construct prompt from structured data; call image model; validate; return URL | 2–10s |

The orchestrator selects the tier based on the visual type. Most market, forecast, and portfolio visuals use Tier 1 (structured JSON) because standard chart libraries handle them well. Scenario and similarity visuals often use Tier 2 (SVG) because their graph/tree layouts benefit from server-side computation. AI-generated explanatory visuals always use Tier 3.

### Structured JSON Visual Specification

Every Tier 1 visual returns a typed JSON specification:

```
{
  "visual_type": "forecast_distribution",
  "version": 1,
  "data": {
    "entity_key": "AAPL",
    "bull_probability": 0.30,
    "base_probability": 0.50,
    "bear_probability": 0.20,
    "confidence": 0.72,
    "as_of": "2026-06-21T00:00:00Z"
  },
  "labels": {
    "title": "AAPL Forecast Distribution",
    "subtitle": "As of June 21, 2026"
  },
  "explainability": {
    "what_am_i_looking_at": "Probability distribution across three forecast scenarios for AAPL.",
    "why_does_it_matter": "Forecast shifted toward bull scenario since last assessment.",
    "supporting_evidence": ["forecast_vector:AAPL:2026-06-21"]
  },
  "validation": {
    "valid": true,
    "checked_at": "2026-06-21T12:00:00Z"
  }
}
```

The frontend receives this spec and renders it using its own charting library. The backend never sends pixel data for Tier 1 visuals.

### Server-Side SVG

Tier 2 visuals produce SVG strings. The SVG is generated from structured data using deterministic layout algorithms (force-directed for networks, tree layout for hierarchies, timeline layout for chronological data). No LLM prose in SVG text elements — all labels come from upstream data fields.

### AI Image Generation

Tier 3 visuals use a structured prompt assembled from intelligence data:

```
{
  "prompt_type": "ecosystem_map",
  "entity": "NVIDIA",
  "data": {
    "supply_chain": [...],
    "similarity_edges": [...],
    "portfolio_exposure": 0.12
  },
  "style": "clean infographic, labeled nodes, no decorative elements",
  "constraints": [
    "no text containing buy, sell, or sizing language",
    "no arrows implying direction of action",
    "label all data sources"
  ]
}
```

The generated image is validated post-generation:
1. OCR scan for banned phrases (advisory language check)
2. Metadata validation (explainability fields present)
3. Evidence reference check (at least one upstream source cited)

Failed validation → image blocked, logged to shadow journal, not served.

---

## AI Visual Generation Strategy

### When to Use AI Generation

AI-generated visuals are used when:
- The question is open-ended ("How has AI data-center demand changed?")
- No template visual type fits the question
- The answer requires combining multiple intelligence sources into a single coherent picture
- The visual benefits from spatial layout decisions that are difficult to template

### When NOT to Use AI Generation

- Standard charts (bar, line, pie, scatter) — use Tier 1 structured JSON
- Standard diagrams with known topology (trees, timelines) — use Tier 2 SVG
- Any visual where a deterministic template produces equivalent quality

### AI Visual Pipeline

```
User question
  → Question classifier (what intelligence is needed?)
  → Data assembler (read upstream phases)
  → Prompt builder (structured prompt from data, never raw user input)
  → Image generator (external model call)
  → Post-generation validator (OCR + metadata + evidence check)
  → Cache (keyed on data hash)
  → Return URL + explainability metadata
```

### Safety Constraints for AI Visuals

1. **Prompt is data-driven, not user-driven.** The user's question selects which data to include. The prompt is constructed from structured intelligence data, not from the user's raw text. The user never writes the image prompt.

2. **No advisory content in prompts.** Prompt templates are scanned for banned phrases at build time (AST scan, identical to Phases 15–18).

3. **Post-generation validation.** Every generated image is scanned for text content. Banned phrases in generated text → image blocked.

4. **Explainability required.** Every AI visual must answer the three questions (what, why, evidence) in its metadata. Missing metadata → visual blocked.

5. **Deterministic fallback.** If AI generation fails or is blocked, the system falls back to a Tier 2 SVG or Tier 1 JSON visual where possible. The user sees a visual, just not the AI-enhanced version.

---

## Explainability Requirements

Every visual — regardless of tier — must answer three questions:

| Question | Field | Required |
|---|---|---|
| What am I looking at? | `what_am_i_looking_at` | Non-empty string describing the visual |
| Why does it matter? | `why_does_it_matter` | Non-empty string explaining relevance |
| What evidence supports it? | `supporting_evidence` | Non-empty list of upstream data references |

### Explainability Gate

A visual with any empty or missing field is **blocked**. Blocked visuals are:
- Logged to the shadow journal with `explanation_valid=False`
- Never served to the user
- Counted in calibration metrics for coverage tracking

This is identical in structure to the Phase 18 explainability gate. The same four-field pattern, the same blocking behavior, the same shadow logging.

### Template-Based Explanations

All explainability text is template-derived. Templates are parameterized with entity names, dates, and score values — never with LLM-generated prose.

```
TEMPLATES = {
  "forecast_distribution": {
    "what": "{entity_key} forecast probability distribution across three scenarios.",
    "why":  "Forecast for {entity_key} was updated on {as_of_date}.",
  },
  "similarity_network": {
    "what": "Similarity relationships for {entity_key} based on {edge_count} connections.",
    "why":  "{entity_key} has {new_edge_count} new similarity connections since last assessment.",
  },
  ...
}
```

---

## Data Model

### New Tables

#### `visual_spec_cache`

Caches rendered visual specifications to avoid redundant computation.

| Column | Type | Description |
|---|---|---|
| `id` | UUID | Primary key |
| `user_id` | UUID | FK → users |
| `visual_type` | VARCHAR(50) | "forecast_distribution", "similarity_network", etc. |
| `entity_key` | VARCHAR(64) | Primary entity for this visual |
| `data_hash` | VARCHAR(64) | SHA-256 of input data (cache key) |
| `spec_json` | TEXT | The visual specification (JSON string) |
| `rendering_tier` | VARCHAR(10) | "json", "svg", "ai_image" |
| `explanation_valid` | BOOLEAN | Whether explainability gate passed |
| `run_reason` | VARCHAR(15) | "shadow" until live rollout |
| `generated_at` | TIMESTAMP | When the spec was generated |
| `expires_at` | TIMESTAMP | Cache expiration (NULL = no expiry) |
| `created_at` | TIMESTAMP | Row creation time |

Unique constraint: `(user_id, visual_type, entity_key, data_hash)`.

#### `visual_experience_event`

Append-only log of visual generation events. Mirrors `personal_experience_event`.

| Column | Type | Description |
|---|---|---|
| `id` | UUID | Primary key |
| `user_id` | UUID | FK → users |
| `visual_type` | VARCHAR(50) | Type of visual requested |
| `entity_key` | VARCHAR(64) | Primary entity |
| `rendering_tier` | VARCHAR(10) | "json", "svg", "ai_image" |
| `explanation_valid` | BOOLEAN | Whether explainability gate passed |
| `generation_ms` | INTEGER | Time to generate in milliseconds |
| `cache_hit` | BOOLEAN | Whether the result came from cache |
| `blocked_reason` | VARCHAR(100) | Empty if not blocked; reason if blocked |
| `run_reason` | VARCHAR(15) | "shadow" until live rollout |
| `surfaced_at` | TIMESTAMP | When the visual was served |
| `created_at` | TIMESTAMP | Row creation time |

Append-only: INSERT only. No UPDATE. No DELETE.

#### `ai_visual_generation_log`

Audit log for AI-generated visuals. Tracks prompts sent and validation outcomes.

| Column | Type | Description |
|---|---|---|
| `id` | UUID | Primary key |
| `user_id` | UUID | FK → users |
| `visual_type` | VARCHAR(50) | Type of visual |
| `entity_key` | VARCHAR(64) | Primary entity |
| `prompt_hash` | VARCHAR(64) | SHA-256 of the prompt (prompt text NOT stored) |
| `generation_model` | VARCHAR(50) | Model used for generation |
| `generation_ms` | INTEGER | Time to generate |
| `validation_passed` | BOOLEAN | Whether post-generation validation passed |
| `validation_reason` | VARCHAR(100) | Empty if passed; reason if failed |
| `banned_phrases_found` | TEXT | Comma-separated list of any banned phrases detected |
| `run_reason` | VARCHAR(15) | "shadow" until live rollout |
| `created_at` | TIMESTAMP | Row creation time |

Append-only. **No prompt text stored** — only prompt_hash. This ensures no raw model input appears in audit tables.

---

## No-Advice Boundary — SP-19

**Phase 19 visualizes intelligence. It does not advise.**

| Rule | Constraint |
|---|---|
| **SP-19a** | No advisory language. Visuals illustrate data. No visual text may contain: buy, sell, hold, overweight, underweight, recommend, target price, position size, take a position, enter a trade, exit a trade, place an order, execute, short, long position, go long, go short, open a position, close a position. |
| **SP-19b** | Visualization does not change truth. A chart of a forecast is a rendering of the forecast — it does not alter the forecast's probabilities, confidence, or calibration. |
| **SP-19c** | Writes only to Phase 19 tables: `visual_spec_cache`, `visual_experience_event`, `ai_visual_generation_log`. No upstream table is ever written, updated, or deleted. |
| **SP-19d** | No upstream feedback. Phase 19 reads from all upstream phases but writes nothing back. A visual's rendering does not influence the intelligence it visualizes. |
| **SP-19e** | No directional arrows implying action. Visual elements like arrows must represent data relationships (similarity edges, transmission paths, causal chains) — never implied trading direction. |
| **SP-19f** | AI-generated visuals undergo post-generation safety validation. OCR scan for banned phrases. Any detection → visual blocked. |

### Enforcement

- **AST scan**: every Phase 19 service is scanned at test time for banned phrases in string literals (excluding docstrings). Identical to Phases 15–18.
- **Import firewall**: no Phase 19 service may import write functions from forecast_repo, decision_repo, scenario_repo, similarity_repo, or any upstream truth-table write module.
- **Mutation pattern scan**: no `.update()` or `.delete()` on upstream models.
- **Post-generation OCR**: AI-generated images scanned for banned text content.
- **Explainability gate**: 3-field requirement blocks visuals without evidence.

---

## Validation Framework

### Visual Validation Checks

| Check | Validated By |
|---|---|
| Explainability gate: 3 fields present and non-empty | `visual_validation_service` |
| No banned phrases in visual text/labels | AST scan (build time) + runtime validation |
| No upstream table writes | Import firewall + mutation pattern scan |
| Data hash matches input data | Cache validation |
| AI visual post-generation safety | OCR scan + metadata validation |
| Rendering tier appropriate for visual type | Orchestrator validation |
| Evidence references resolve to real upstream data | Evidence reference check |

### Calibration Metrics

| Metric | Formula | Min Samples |
|---|---|---|
| `explainability_coverage` | `valid_count / total_count` from visual events | 10 |
| `cache_hit_rate` | `cache_hits / total_requests` | 20 |
| `ai_validation_pass_rate` | `passed / total_ai_generations` | 5 |
| `generation_latency_p95` | 95th percentile of `generation_ms` | 20 |
| `blocked_visual_rate` | `blocked_count / total_count` | 10 |

---

## Rollout Framework

### Flags

| Flag | Default | Purpose |
|---|---|---|
| `visual_orchestrator_enabled` | `False` | Gate for visual orchestration |
| `visual_renderer_enabled` | `False` | Gate for server-side rendering |
| `visual_ai_enabled` | `False` | Gate for AI image generation |
| `visual_cache_enabled` | `False` | Gate for visual caching |
| `visual_shadow` | `True` | Shadow journaling (always on) |

### Rollout Stages

| Stage | Flags Enabled | Behavior |
|---|---|---|
| **0 — Shadow** | All defaults | Code deployed, fully inert. Shadow journal records what would be generated. |
| **1 — Structured JSON** | `visual_orchestrator_enabled` | Tier 1 visuals (structured JSON) generated and cached. No rendering. |
| **2 — SVG Rendering** | + `visual_renderer_enabled` | Tier 2 visuals (SVG) generated server-side. Still shadow-only. |
| **3 — Caching** | + `visual_cache_enabled` | Visual cache active. Performance validation. |
| **4 — AI Generation** | + `visual_ai_enabled` | AI-generated visuals with post-generation safety. Shadow-only. |
| **5 — Live** | `visual_shadow=False` | Visuals delivered to users. Requires frontend integration. |

### Rollback

Every stage is independently reversible:
- Set the flag back to its default value
- No data migration required
- Existing cache rows and journal entries are inert
- `git revert` any slice without data consequences

Emergency rollback: set all flags to defaults (Stage 0).

---

## Risks

| Risk | Mitigation |
|---|---|
| AI-generated visuals contain advisory language | Post-generation OCR scan; blocked on detection; shadow-first rollout |
| Visual generation latency impacts API response time | Tier selection (JSON < 100ms, SVG < 500ms); async generation for AI visuals; caching |
| Cache staleness: visual shows outdated data | Cache keyed on `data_hash` — upstream data change invalidates cache automatically |
| AI image generation costs | Shadow-first (measure volume before enabling); cache aggressively; rate limit per user |
| Explainability gap: visual shown without context | Mandatory 3-field explainability gate; blocked without evidence |
| Visual implies trading action | SP-19e: no directional arrows implying action; post-generation validation; banned-phrase scan |
| Upstream data unavailable | Graceful degradation: visual returns empty spec with `explanation_valid=False`; never fabricates data |

---

## Acceptance Criteria

- [ ] All visual categories defined with inputs and outputs
- [ ] Three rendering tiers specified with selection criteria
- [ ] AI visual generation pipeline specified with safety constraints
- [ ] Explainability gate: 3 required fields per visual
- [ ] SP-19 no-advice boundary defined and enforcement specified
- [ ] Data model: 3 new tables (cache, events, AI log)
- [ ] No prompt text stored in any table (prompt_hash only)
- [ ] Rollout framework: 5 flags, 6 stages, independent rollback
- [ ] Validation framework: 7 checks, 5 calibration metrics
- [ ] Shadow-first deployment strategy
- [ ] No truth-table mutation by any Phase 19 service
- [ ] No upstream feedback loop
- [ ] All visual text template-derived (no LLM prose in labels)
- [ ] Post-generation AI safety validation specified
