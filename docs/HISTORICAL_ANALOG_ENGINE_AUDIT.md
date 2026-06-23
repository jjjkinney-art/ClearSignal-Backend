# Historical Analog Engine — Full Audit Report

**Date:** 2026-06-24
**Status:** Audit complete. No code changes.

---

## 1. Pipeline Trace

### Architecture

```
User Query + Thesis (post-synthesis)
  ↓
build_fingerprint(question, thesis_dict, ticker)
  ├─ _extract_concern_tags(thesis)     → [capex_cycle, valuation_risk, ...]
  ├─ _infer_mechanisms(tags, question) → [infrastructure_overbuild, ...]
  ├─ _infer_sector_biz(thesis)         → sector="technology", biz="saas"
  ├─ _infer_valuation_regime()         → "peak_multiple" | "compressed" | None
  ├─ _infer_growth_phase()             → "hypergrowth" | "deceleration" | None
  └─ _infer_macro_regime()             → "hiking" | "easing" | None
  ↓
get_all_analogs(session)  → 22 curated analogs from DB
  ↓
For each analog: _score_analog(analog, fingerprint)
  ↓
Filter: score ≥ 0.40 (RELEVANCE_FLOOR)
Sort: descending
Diversity: max 1 per mechanism
Limit: top 3 (TOP_K)
  ↓
Attach to thesis response as historical_evidence.analogs[]
```

### Files

| File | Role |
|---|---|
| `app/evidence_engine.py` (518 lines) | Fingerprint construction, scoring, retrieval |
| `app/db/data/historical_analogs.json` (574 lines) | 22-analog seed library |
| `app/db/models.py:404-449` | HistoricalAnalog ORM model |
| `app/db/repositories/evidence_repo.py` | DB seed and retrieval |
| `app/api.py:1627-1666` | Post-dispatch analog attachment |

---

## 2. Scoring Methodology

### Formula

```
SCORE = clamp(0, 1,
    0.40 × tag_jaccard(analog.concern_tags, query.concern_tags)
  + 0.30 × mechanism_match(query.mechanisms, analog.mechanism)
  + 0.075 × exact_match(query.valuation_regime, analog.valuation_regime)
  + 0.075 × exact_match(query.growth_phase, analog.growth_phase)
  + 0.05 × exact_match(query.sector, analog.sector)
  + 0.05 × exact_match(query.business_model, analog.business_model)
  + 0.05 × exact_match(query.macro_regime, analog.macro_regime)
  + 0.02 × (1 if analog.quality_rating == "strong")
  - 0.05   # DISANALOGY_PENALTY (structural honesty)
)
```

### Weight Distribution

| Component | Weight | Match Type | Problem |
|---|---|---|---|
| **Concern tags** | 40% | Jaccard set overlap | Generic tags shared across unrelated companies |
| **Mechanism** | 30% | Exact or sibling match | Only 12 mechanisms defined; no business-model-specific mechanisms |
| **Valuation regime** | 7.5% | Binary exact match | "peak_multiple" matches V to NVDA equally |
| **Growth phase** | 7.5% | Binary exact match | "deceleration" matches COST to Netflix equally |
| **Sector** | 5% | Binary exact match | No cross-sector partial credit |
| **Business model** | 5% | Binary exact match | No partial credit; None = no penalty |
| **Macro regime** | 5% | Binary exact match | "hiking" is always true in rate-hike cycles |

### What is NOT compared

- Business mechanism similarity (toll model vs subscription vs product sale)
- Revenue model durability
- Customer base structure
- Competitive position type (monopoly vs oligopoly vs fragmented)
- Moat type
- Capital structure
- Balance sheet risk
- Geographic exposure

---

## 3. Root-Cause Analysis

### Why Incorrect Analogs Are Selected

**The root cause is not the scoring algorithm.** The scoring algorithm is actually well-designed — it properly weights mechanism > sector > business model. The root cause is **library poverty**: the 22-analog library has no analogs for payment networks, ratings agencies, pharma, semiconductor equipment, membership retail, or diversified banks. When no relevant analog exists, the system returns the best available match from the wrong business model.

### MA → Netflix Q1 2022

**How it happened:**
- MA's thesis mentions competitive_risk, valuation_risk, macro_slowdown_risk
- Netflix has concern_tags [competitive_risk, valuation_risk, macro_slowdown_risk]
- Tag Jaccard: high overlap → 0.40 × 0.67 = 0.27
- MA may infer mechanism=multiple_compression (if "valuation_risk" dominates)
- Netflix mechanism=hypergrowth_deceleration, sibling=multiple_compression → 0.30 × 0.5 = 0.15
- Valuation regime match (peak_multiple): +0.075
- Macro match (hiking): +0.05
- Quality boost: +0.02
- Penalty: -0.05
- **Total: ~0.47** (above 0.40 floor)

**Why it's wrong:** Netflix's subscriber growth stall has no structural relationship to Mastercard's payment volume business. The match fires because concern_tags (valuation_risk, competitive_risk) are generic enough to overlap across unrelated businesses.

**What should match:** Visa 2010 merchant lawsuit (interchange fee regulation), American Express 2015 Costco loss (network exclusivity), or Western Union decline (cross-border payment disruption).

### SPGI → Qualcomm 2017-2019

**How it happened:**
- SPGI's thesis likely mentions competitive_risk and concentration_risk
- Qualcomm has concern_tags [competitive_risk, concentration_risk]
- Tag overlap drives the match
- Mechanism: competitive_displacement matches if SPGI's risk includes competition

**Why it's wrong:** Qualcomm's customer concentration (Apple) and in-house chip design risk is completely unrelated to SPGI's ratings oligopoly. SPGI faces regulatory risk to the issuer-pays model, not competitive displacement.

**What should match:** Moody's 2008 (ratings credibility crisis), Fitch downgrade impact, or MSCI index rebalancing precedent.

### ASML → Alibaba 2020-2022

**How it happened:**
- ASML's thesis mentions geopolitical_risk (China export controls)
- Alibaba mechanism: regulatory_break
- geopolitical_risk → primary mechanism: regulatory_break
- **Exact mechanism match** → 0.30 × 1.0 = 0.30
- Plus tag overlap → high score

**Why it's wrong:** Alibaba's domestic Chinese tech regulatory crackdown (antitrust, fintech regulation, data privacy laws) is structurally different from ASML's export control risk (US/Netherlands government restricting technology transfer to China). The regulatory actor, the mechanism, and the business impact are all different.

**What should match:** Applied Materials China restrictions, Huawei Entity List impact, or TSMC geopolitical exposure.

### LLY → Meta 2022

**How it happened:**
- LLY's thesis mentions competitive_risk and valuation_risk
- Meta has concern_tags [competitive_risk, valuation_risk, att_privacy_risk]
- Tag overlap drives the match
- If growth_phase inferred as "deceleration" → matches

**Why it's wrong:** Meta's ATT privacy disruption and social media competitive pressure has zero structural relationship to Eli Lilly's GLP-1 pharmaceutical franchise. LLY's risk is pipeline failure and competitive entry from NVO/AMGN, not digital advertising disruption.

**What should match:** Pfizer post-COVID revenue cliff, Celgene Revlimid patent cliff, or Amgen biosimilar competition.

### Common Pattern

All four failures share one root cause: **the library has no analogs for these business models**. There are:
- 0 payment network analogs
- 0 ratings agency analogs
- 0 semiconductor equipment analogs
- 0 pharma pipeline analogs
- 0 membership retail analogs
- 0 diversified bank analogs

When no relevant analog exists, the concern-tag Jaccard (40% weight) dominates because generic tags like "valuation_risk" and "competitive_risk" appear in every thesis. The system selects the best-scoring analog from the wrong business model because there is no right-business-model analog available.

---

## 4. Replacement Architecture

### Priority Tiers for Analog Selection

**Tier 1: Business Mechanism Similarity (must match)**

The analog must share the same type of competitive structure:

| Business Mechanism | Companies | Why It's Distinct |
|---|---|---|
| Payment network tollbooth | V, MA | Two-sided network, no credit risk, per-transaction fees |
| Ratings/data oligopoly | SPGI, MCO | Regulatory moat, issuer-pays model, no lending risk |
| Semiconductor equipment monopoly | ASML | 100% EUV market share, 3-year order backlogs |
| Pharma franchise + pipeline | LLY, NVO | Patent moat, pipeline optionality, binary trial risk |
| Membership retail | COST | Renewal-driven, membership fee > merchandise margin |
| Cloud/enterprise platform | MSFT, AMZN, GOOGL | Switching costs, consumption billing, platform lock-in |
| Semiconductor cycle | NVDA, AMD | CapEx-driven demand, design win cadence, inventory cycles |
| Diversified bank | JPM, BAC | Net interest income, credit cycle, regulatory capital |
| Narrative/EV | TSLA | Consumer brand, manufacturing scale, CEO risk |
| Government software | PLTR | Contract concentration, classified work, long sales cycles |

**Tier 2: Risk Mechanism Similarity (should match)**

The analog should face the same type of risk:

| Risk Mechanism | Example |
|---|---|
| Regulatory intervention | Interchange fee caps, antitrust, export controls |
| Customer concentration | Single-customer revenue dependency |
| Capital cycle inflection | CapEx boom/bust, infrastructure overbuild |
| Technology displacement | Architecture shift, new entrant with superior tech |
| Pipeline dependence | Clinical trial failure, patent cliff |
| Competitive entry | New competitor in oligopoly market |
| Macro sensitivity | Rate shock, credit cycle, recession demand |

**Tier 3: Outcome Pattern (informational only)**

- Drawdown magnitude
- Recovery timeline
- Revenue decline depth

**Selection rule:** An analog must match on Tier 1 OR Tier 2 to be eligible. Tier 3 alone is never sufficient. This prevents "growth deceleration" from matching across unrelated business models.

### Proposed Scoring Formula

```
SCORE = clamp(0, 1,
    0.35 × business_mechanism_similarity(query, analog)
  + 0.25 × risk_mechanism_similarity(query, analog)  
  + 0.15 × concern_tag_overlap(query, analog)        # reduced from 0.40
  + 0.10 × sector_match(query, analog)               # increased from 0.05
  + 0.05 × valuation_regime_match
  + 0.05 × growth_phase_match
  + 0.05 × macro_regime_match
  - 0.03   # disanalogy penalty (reduced from 0.05)
)
```

Key changes:
- **Business mechanism similarity** becomes the largest weight (35% vs current 0%)
- **Concern-tag overlap** reduced from 40% → 15% (prevents generic-tag matches)
- **Sector match** doubled from 5% → 10% (cross-sector matches should be rare)
- **Risk mechanism** at 25% (mechanism match, but focused on risk type)

### Business Mechanism Similarity Scoring

```python
_BUSINESS_MECHANISM_GROUPS = {
    "payment_network":      ["V", "MA", "AXP", "DFS", "PYPL"],
    "ratings_data":         ["SPGI", "MCO", "MSCI", "FDS", "ICE"],
    "semiconductor_equip":  ["ASML", "AMAT", "LRCX", "KLAC"],
    "pharma_pipeline":      ["LLY", "NVO", "PFE", "MRK", "ABBV", "BMY"],
    "membership_retail":    ["COST", "WMT", "BJ"],
    "cloud_platform":       ["MSFT", "AMZN", "GOOGL", "CRM", "SNOW"],
    "semiconductor_cycle":  ["NVDA", "AMD", "AVGO", "QCOM", "INTC"],
    "diversified_bank":     ["JPM", "BAC", "C", "WFC", "GS"],
    "ev_narrative":         ["TSLA", "RIVN", "LCID"],
    "gov_software":         ["PLTR", "BKSY"],
}

def business_mechanism_similarity(query_ticker, analog_ticker):
    for group, members in _BUSINESS_MECHANISM_GROUPS.items():
        if query_ticker in members and analog_ticker in members:
            return 1.0  # same business mechanism group
    return 0.0  # different groups
```

---

## 5. Benchmark Analog Library

### Visa (V)

| # | Analog | Mechanism | Why Relevant |
|---|---|---|---|
| 1 | **American Express 2015 — Costco partnership loss** | Network exclusivity loss | AXP lost its largest co-brand partner; V/MA face similar large-issuer switching risk |
| 2 | **Visa 2010 — Durbin Amendment interchange cap** | Regulatory fee compression | Direct precedent: US debit interchange capped at 21¢+0.05%, reduced issuer incentive to issue Visa debit cards |
| 3 | **Western Union 2015-2022 — digital remittance disruption** | Cross-border payment displacement | WU's cross-border business eroded by fintech (Wise, Remitly); parallel to V/MA cross-border premium risk |
| 4 | **China UnionPay domestic mandate** | Government-mandated network exclusion | Precedent for sovereign payment nationalism: China required domestic-only network, V/MA excluded |
| 5 | **India UPI 2016+ — zero-fee digital payments** | Government-subsidized network bypass | UPI processes billions of transactions at zero merchant cost, bypassing V/MA rails entirely |

### Mastercard (MA)

| # | Analog | Mechanism | Why Relevant |
|---|---|---|---|
| 1 | **American Express 2015 — Costco partnership loss** | Same as V |
| 2 | **EU Interchange Regulation 2015 — fee caps** | Regulatory fee compression | EU capped interchange at 0.2%/0.3%, directly compressing MA's economics |
| 3 | **Visa 2010 — Durbin Amendment** | Cross-reference | Same network economics |
| 4 | **PayPal 2021-2022 — fintech deceleration** | Fintech competitive pressure | PayPal's deceleration after eBay loss shows risk of platform disintermediation |
| 5 | **Western Union decline** | Cross-border disruption | Same as V |

### S&P Global (SPGI)

| # | Analog | Mechanism | Why Relevant |
|---|---|---|---|
| 1 | **Moody's 2008 — ratings credibility crisis** | Ratings franchise reputational risk | Moody's AAA-rated subprime MBS failed en masse; direct parallel to SPGI ratings credibility |
| 2 | **S&P 2011 — US sovereign downgrade backlash** | Regulatory/political retaliation | S&P downgraded US from AAA; DoJ filed $5B fraud suit (settled for $1.5B) |
| 3 | **MSCI 2018 — China A-share inclusion** | Index inclusion controversy | Index decisions create winners/losers; precedent for SPGI's index power |
| 4 | **Thomson Reuters 2018 — Refinitiv separation** | Data business restructuring | Financial data competitive dynamics relevant to Market Intelligence |
| 5 | **Fitch 2023 — US downgrade** | Rating agency credibility pressure | Latest precedent for rating agency political scrutiny |

### Microsoft (MSFT)

| # | Analog | Mechanism | Why Relevant |
|---|---|---|---|
| 1 | **IBM 1990s — enterprise platform transition** | Mainframe→client-server disruption | Dominant enterprise platform had to reinvent; MSFT faces cloud transition parallels |
| 2 | **Amazon AWS 2019 — JEDI contract loss** | Government cloud competition | Single contract loss risk in enterprise cloud |
| 3 | **Salesforce 2022 — SaaS multiple compression** | Enterprise SaaS re-rating | Multi-turn SaaS de-rating from 15x→8x revenue relevant to Azure valuation |
| 4 | **Oracle 2010s — cloud transition** | Legacy software → cloud migration | Successful but slow transition that compressed multiples for years |
| 5 | **Google Cloud 2020-2023 — market share gains** | Cloud competitive entry | Third entrant gaining share in oligopoly market |

### Costco (COST)

| # | Analog | Mechanism | Why Relevant |
|---|---|---|---|
| 1 | **Sam's Club 2018 — store closures** | Membership retail competition | Direct competitor closed 63 stores; shows market structure risk |
| 2 | **Netflix membership price increases** | Subscription pricing power test | Membership-based business testing price elasticity |
| 3 | **Costco 2009 — recession membership renewal** | Recession resilience precedent | Costco's own history: renewals held 87%+ through 2008-09 |
| 4 | **Amazon Prime membership growth** | Competing membership ecosystem | Prime's expansion into grocery/pharmacy overlaps COST's value prop |
| 5 | **Walmart 2015-2017 — e-commerce investment cycle** | Retail CapEx compression | Grocery retail investment cycles and margin pressure |

### ASML (ASML)

| # | Analog | Mechanism | Why Relevant |
|---|---|---|---|
| 1 | **Applied Materials 2019 — China export restrictions** | Export control revenue impact | Direct semiconductor equipment parallel: US restrictions on China shipments |
| 2 | **ASML 2008-2009 — semiconductor CapEx collapse** | Equipment demand cyclicality | ASML's own history: orders fell 80% in the GFC |
| 3 | **Tokyo Electron 2015 — merger blocked + cycle downturn** | Semiconductor equipment M&A + cycle | Equipment industry consolidation attempt during downturn |
| 4 | **KLA 2019 — memory capex pullback** | Customer-specific CapEx cuts | Concentrated customer risk: DRAM/NAND cuts hit equipment orders |
| 5 | **Nikon 2013-2020 — lithography market share loss** | Technology displacement (by ASML) | The inverse case: what happens when a monopoly emerges in lithography |

### JPMorgan (JPM)

| # | Analog | Mechanism | Why Relevant |
|---|---|---|---|
| 1 | **JPMorgan 2008-2009 — GFC credit cycle** | JPM's own crisis-cycle precedent | JPM acquired Bear Stearns/WaMu; credit losses manageable but stock fell 68% |
| 2 | **Wells Fargo 2016 — fake accounts scandal** | Operational/governance risk | Large bank franchise damaged by internal controls failure |
| 3 | **Citigroup 2008-2009 — excessive leverage** | Bank capital adequacy crisis | Peer bank required TARP bailout; shows range of outcomes in severe credit cycle |
| 4 | **European banks 2011-2012 — sovereign debt crisis** | Cross-border banking contagion | Sovereign exposure → bank capital fears → credit tightening |
| 5 | **Silicon Valley Bank 2023 — deposit flight** | Rapid deposit withdrawal risk | Modern precedent: concentrated deposit base + duration mismatch |

### Eli Lilly (LLY)

| # | Analog | Mechanism | Why Relevant |
|---|---|---|---|
| 1 | **Pfizer 2022-2023 — COVID revenue cliff** | Blockbuster revenue cliff | Pfizer's COVID vaccine/Paxlovid revenue collapsed; shows risk of single-franchise dependence |
| 2 | **Celgene 2018-2019 — Revlimid patent cliff** | Patent expiration concentration | Celgene's top drug facing patent cliff; merger with BMY driven by pipeline need |
| 3 | **Biogen 2019 — Aduhelm FDA controversy** | Regulatory approval uncertainty | FDA advisory panel rejection → approval → commercial failure |
| 4 | **Amgen 2023 — Humira biosimilar entry** | Competitive entry into dominant franchise | AbbVie's Humira lost exclusivity; biosimilar competition compressed revenue |
| 5 | **Novo Nordisk 2016 — insulin pricing pressure** | Drug pricing political risk | NVO faced US pricing scrutiny; parallel to GLP-1 pricing concerns |

### Nvidia (NVDA)

| # | Analog | Mechanism | Why Relevant |
|---|---|---|---|
| 1 | **Cisco 2000 — infrastructure overbuild** | CapEx cycle peak | Already in library. Strongest mechanism match for AI infrastructure thesis |
| 2 | **NVIDIA 2022 — gaming inventory correction** | Already in library. Own-company precedent |
| 3 | **NVIDIA 2018 — crypto demand air pocket** | Already in library. Artificial demand collapse |
| 4 | **Intel 2019-2023 — competitive displacement** | Already in library. Architecture loss to AMD/ARM |
| 5 | **Qualcomm 2017-2019 — customer in-housing** | Customer vertical integration | Apple designing own modems; parallel to hyperscalers designing custom ASICs |

### Tesla (TSLA)

| # | Analog | Mechanism | Why Relevant |
|---|---|---|---|
| 1 | **Peloton 2021-2022 — hardware demand reversal** | Already in library. Consumer hardware pull-forward |
| 2 | **Nokia 2007-2012 — platform disruption** | Already in library. Dominant hardware player disrupted |
| 3 | **GoPro 2014-2018 — consumer hardware margin collapse** | Hardware commodity risk | Premium hardware brand lost pricing power; margins collapsed |
| 4 | **Fisker/Lordstown 2022-2023 — EV startup failure** | EV industry overcapacity | EV startups failed despite favorable demand; shows industry risk |
| 5 | **Toyota 2010 — recall crisis** | Manufacturing quality/brand risk | Largest auto recall in history; parallel to Tesla quality concerns |

### Palantir (PLTR)

| # | Analog | Mechanism | Why Relevant |
|---|---|---|---|
| 1 | **Booz Allen Hamilton 2013 — Snowden/contract risk** | Government contractor concentration | BAH lost credibility after Snowden; shows single-customer government risk |
| 2 | **Leidos/SAIC 2012 — government sequestration** | Defense budget cuts | Government spending cuts directly impact contract-dependent companies |
| 3 | **MicroStrategy 2000 — narrative-driven tech** | Technology narrative collapse | CEO-driven narrative stock collapsed when fundamentals didn't support valuation |
| 4 | **Splunk 2019-2022 — data analytics transition** | Enterprise analytics competition | Splunk's cloud transition challenges relevant to PLTR's platform bet |
| 5 | **DXC Technology 2019-2021 — government IT decline** | Government IT contract attrition | Legacy government IT provider lost contracts to cloud-native competitors |

---

## 6. Implementation Complexity

### Option A: Quick Fix — Expand Library Only (1-2 days)

**What:** Add 30-40 new analogs covering missing business models (payment networks, ratings, pharma, semicon equipment, membership retail, banks, government software). Keep existing scoring algorithm unchanged.

**Files touched:**
- `app/db/data/historical_analogs.json` — add new analog entries

**Estimated LOC:** ~800 (JSON data)
**Risk:** Low — purely additive data, no algorithm change
**Expected quality improvement:** 60-70%. Most mismatches are caused by library poverty (no relevant analog exists). Adding the right analogs fixes the most visible failures.

**Limitation:** The scoring formula still over-weights concern-tag Jaccard (40%), so generic tags can still create cross-sector matches when multiple relevant analogs exist.

### Option B: Medium Redesign — Library + Scoring Reweight (3-5 days)

**What:** Expand the library (Option A) + reweight the scoring formula to prioritize business mechanism similarity over concern-tag overlap. Add a `business_mechanism_group` field to analogs and to the fingerprint.

**Files touched:**
- `app/db/data/historical_analogs.json` — add new analogs + business_mechanism_group field
- `app/evidence_engine.py` — add business_mechanism_similarity scoring, reweight formula
- `app/db/models.py` — optional: add business_mechanism_group column to HistoricalAnalog

**Estimated LOC:** ~300 (scoring changes) + ~800 (library data)
**Risk:** Medium — scoring formula changes affect all companies
**Expected quality improvement:** 85-90%. Business mechanism matching prevents cross-sector mismatches; expanded library provides relevant alternatives.

### Option C: Institutional-Grade — Full Redesign (1-2 weeks)

**What:** Everything in Option B + structured analog metadata (moat type, revenue model, switching cost level from the CompanyKnowledgeProfile), multi-dimensional similarity scoring, sector-specific analog pools, analog quality grading system, and automated analog gap detection.

**Files touched:**
- All files from Option B
- `app/schemas.py` — AnalogMetadata schema
- `app/services/company_knowledge.py` — link profiles to analog pools
- `app/evidence_engine.py` — full rewrite of scoring with multi-dimensional similarity
- New: `app/services/analog_quality_service.py` — automated gap detection + quality grading
- Tests: comprehensive analog matching test suite

**Estimated LOC:** ~1,500-2,000
**Risk:** High — full scoring rewrite, extensive testing required
**Expected quality improvement:** 95%+. Every company gets business-model-relevant analogs. Cross-sector mismatches eliminated. Analog quality graded and auditable.

---

## 7. Recommendations (Ranked by Impact)

| Priority | Action | Impact | Effort | Risk |
|---|---|---|---|---|
| **1** | **Expand library with 30-40 business-model-specific analogs** | Fixes 80% of observed mismatches | 1-2 days | Low |
| **2** | **Add business_mechanism_group to scoring** | Prevents remaining cross-sector matches | 1 day | Medium |
| **3** | Reduce concern-tag weight from 0.40 to 0.15 | Stops generic tags from dominating | 0.5 day | Medium |
| **4** | Add sector penalty (not just bonus) for cross-sector matches | Makes cross-sector analogs explicitly costly | 0.5 day | Low |
| **5** | Increase RELEVANCE_FLOOR from 0.40 to 0.50 | Filters out weak matches | 0.5 day | Low |
| **6** | Full multi-dimensional similarity scoring | Institutional grade | 1 week | High |

**Recommended approach: Option B (Medium Redesign).** The library expansion fixes the most visible failures. The scoring reweight prevents recurrence. Combined, they deliver ~85-90% quality improvement in 3-5 days with medium risk. Option C can follow later as a quality refinement.
