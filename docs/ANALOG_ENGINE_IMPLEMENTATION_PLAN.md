# Historical Analog Engine — Option B Implementation Plan

**Date:** 2026-06-24
**Status:** Blueprint only. No code changes.
**Prerequisite:** Historical Analog Engine Audit (complete)

---

## 1. Current Analog Library Inventory

### 22 Analogs (complete)

| # | Label | Mechanism | Sector | Business Model | Concern Tags |
|---|---|---|---|---|---|
| 1 | Cisco 2000 — telecom infra overbuild | infrastructure_overbuild | technology | infrastructure_supplier | capex_cycle, valuation_risk, concentration_risk |
| 2 | NVIDIA 2022 — gaming GPU inventory | inventory_channel_correction | technology | semiconductor_fabless | supply_chain_risk, valuation_risk, capex_cycle |
| 3 | Micron 2022 — memory supercycle | inventory_channel_correction | technology | semiconductor_manufacturer | supply_chain_risk, margin_pressure, valuation_risk |
| 4 | Texas Instruments 2022 — analog channel | inventory_channel_correction | technology | semiconductor_manufacturer | supply_chain_risk, margin_pressure, capex_cycle |
| 5 | NVIDIA 2018 — crypto air pocket | demand_air_pocket | technology | semiconductor_fabless | supply_chain_risk, valuation_risk, macro_slowdown_risk |
| 6 | Zoom 2022 — pandemic pull-forward | demand_air_pocket | technology | saas | macro_slowdown_risk, competitive_risk, valuation_risk |
| 7 | Peloton 2021 — fitness demand reversal | demand_air_pocket | consumer_discretionary | consumer_hardware | macro_slowdown_risk, margin_pressure, valuation_risk |
| 8 | Software/cloud 2021 — de-rating | multiple_compression | technology | saas | valuation_risk, interest_rate_risk |
| 9 | Amazon 2000 — dot-com collapse | multiple_compression | technology | e_commerce | valuation_risk, macro_slowdown_risk |
| 10 | Netflix Q1 2022 — subscriber stall | hypergrowth_deceleration | technology | internet_platform | competitive_risk, valuation_risk, macro_slowdown_risk |
| 11 | Meta 2022 — ATT + competitive | hypergrowth_deceleration | technology | internet_platform | att_privacy_risk, competitive_risk, valuation_risk, regulatory_risk |
| 12 | PayPal 2021 — fintech deceleration | hypergrowth_deceleration | technology | fintech_platform | competitive_risk, valuation_risk, macro_slowdown_risk |
| 13 | Intel 2019 — architecture displacement | competitive_displacement | technology | semiconductor_manufacturer | competitive_risk, ai_adoption_risk, valuation_risk, margin_pressure |
| 14 | Nokia 2007 — iPhone disruption | competitive_displacement | technology | consumer_hardware | competitive_risk, ai_adoption_risk |
| 15 | Qualcomm 2017 — in-house chip | competitive_displacement | technology | semiconductor_fabless | concentration_risk, competitive_risk, regulatory_risk, valuation_risk |
| 16 | SVB 2023 — deposit mismatch | rate_shock | financials | financial_intermediary | interest_rate_risk, concentration_risk, macro_slowdown_risk |
| 17 | Annaly/AGNC 2022 — mREIT erosion | rate_shock | financials | financial_intermediary | interest_rate_risk, margin_pressure |
| 18 | WaMu 2008 — CRE portfolio failure | credit_event | financials | financial_intermediary | cre_credit_risk, interest_rate_risk, macro_slowdown_risk |
| 19 | Bear Stearns 2007 — leverage crisis | credit_event | financials | financial_intermediary | cre_credit_risk, macro_slowdown_risk, concentration_risk |
| 20 | Alibaba 2020 — China regulatory | regulatory_break | technology | diversified_tech | regulatory_risk, geopolitical_risk, valuation_risk, competitive_risk |
| 21 | Meta 2021 — ATT privacy disruption | regulatory_break | technology | internet_platform | att_privacy_risk, regulatory_risk, margin_pressure, competitive_risk |
| 22 | Oil supermajors 2014 — OPEC shock | commodity_shock | energy | integrated_oil | macro_slowdown_risk, margin_pressure, currency_risk |

### Coverage Gaps

| Business Model | Covered? | Needed For |
|---|---|---|
| payment_network | NO | V, MA |
| ratings_data_oligopoly | NO | SPGI |
| semiconductor_equipment | NO | ASML |
| pharma_pipeline | NO | LLY |
| membership_retail | NO | COST |
| diversified_bank | NO | JPM |
| government_enterprise | NO | PLTR |
| cloud_platform | PARTIAL | MSFT |
| semiconductor_fabless | YES | NVDA |
| consumer_hardware | YES | TSLA |
| infrastructure_supplier | YES | (generic) |

---

## 2. Expanded Analog Library Design

### New mechanisms to add

| Mechanism | Description | Business Models |
|---|---|---|
| `network_fee_compression` | Regulatory/competitive pressure on transaction fees | payment_network |
| `franchise_credibility_crisis` | Reputational/trust damage to franchise model | ratings_data_oligopoly |
| `export_control_restriction` | Government-mandated technology transfer ban | semiconductor_equipment |
| `patent_cliff` | Revenue collapse from patent expiration/competition | pharma_pipeline |
| `membership_elasticity_test` | Testing pricing power of membership model | membership_retail |
| `credit_cycle_loss` | Loan losses from credit deterioration | diversified_bank |
| `government_budget_cut` | Spending reduction impacting contract revenue | government_enterprise |
| `platform_transition` | Legacy→cloud/new-model migration | cloud_platform |

### New business_model values to add

```
payment_network, ratings_data_oligopoly, semiconductor_equipment,
pharma_pipeline, membership_retail, diversified_bank, government_enterprise,
cloud_platform
```

### Proposed New Analogs (38 total)

#### Payment Network (V, MA) — 5 analogs

| # | Label | Mechanism | Concern Tags |
|---|---|---|---|
| 23 | American Express 2015 — Costco co-brand loss | network_fee_compression | concentration_risk, competitive_risk |
| 24 | Visa 2010 — Durbin Amendment interchange cap | network_fee_compression | regulatory_risk, margin_pressure |
| 25 | EU Interchange Regulation 2015 — fee caps | network_fee_compression | regulatory_risk, margin_pressure, geopolitical_risk |
| 26 | Western Union 2015-2022 — digital remittance displacement | competitive_displacement | competitive_risk, ai_adoption_risk |
| 27 | India UPI 2016+ — zero-fee government payment bypass | regulatory_break | regulatory_risk, competitive_risk, geopolitical_risk |

#### Ratings/Data Oligopoly (SPGI) — 5 analogs

| # | Label | Mechanism | Concern Tags |
|---|---|---|---|
| 28 | Moody's 2008 — ratings credibility crisis (subprime AAA) | franchise_credibility_crisis | regulatory_risk, concentration_risk |
| 29 | S&P 2011 — US sovereign downgrade political backlash | franchise_credibility_crisis | regulatory_risk, geopolitical_risk |
| 30 | MSCI 2018 — China A-share inclusion controversy | regulatory_break | regulatory_risk, geopolitical_risk, concentration_risk |
| 31 | Thomson Reuters 2018 — Refinitiv separation/competition | competitive_displacement | competitive_risk, margin_pressure |
| 32 | Fitch 2023 — US downgrade scrutiny cycle | franchise_credibility_crisis | regulatory_risk, macro_slowdown_risk |

#### Semiconductor Equipment (ASML) — 5 analogs

| # | Label | Mechanism | Concern Tags |
|---|---|---|---|
| 33 | Applied Materials 2019 — China export restriction | export_control_restriction | geopolitical_risk, concentration_risk, regulatory_risk |
| 34 | ASML 2008-2009 — semiconductor CapEx collapse (−80% orders) | demand_air_pocket | capex_cycle, macro_slowdown_risk |
| 35 | KLA 2019 — DRAM/NAND capex pullback | demand_air_pocket | capex_cycle, concentration_risk |
| 36 | Tokyo Electron 2015 — blocked merger + cycle downturn | multiple_compression | capex_cycle, regulatory_risk, margin_pressure |
| 37 | Nikon 2013-2020 — lithography market share loss to ASML | competitive_displacement | competitive_risk, concentration_risk |

#### Pharma Pipeline (LLY) — 5 analogs

| # | Label | Mechanism | Concern Tags |
|---|---|---|---|
| 38 | Pfizer 2022-2023 — COVID revenue cliff (−$30B) | patent_cliff | concentration_risk, competitive_risk, macro_slowdown_risk |
| 39 | Celgene 2018 — Revlimid patent cliff + BMY acquisition | patent_cliff | concentration_risk, competitive_risk, valuation_risk |
| 40 | Biogen 2019 — Aduhelm FDA advisory rejection | regulatory_break | regulatory_risk, concentration_risk |
| 41 | AbbVie/Humira 2023 — biosimilar entry revenue erosion | competitive_displacement | competitive_risk, margin_pressure |
| 42 | Novo Nordisk 2016 — insulin pricing political pressure | network_fee_compression | regulatory_risk, margin_pressure, valuation_risk |

#### Membership Retail (COST) — 5 analogs

| # | Label | Mechanism | Concern Tags |
|---|---|---|---|
| 43 | Sam's Club 2018 — 63 store closures (Walmart retreat) | competitive_displacement | competitive_risk, margin_pressure |
| 44 | Costco 2009 — GFC membership renewal test (held 87%+) | membership_elasticity_test | macro_slowdown_risk |
| 45 | Amazon Prime grocery expansion 2017+ — competing membership | competitive_displacement | competitive_risk, ai_adoption_risk |
| 46 | Netflix 2019 — membership price elasticity test | membership_elasticity_test | competitive_risk, valuation_risk |
| 47 | Walmart 2015-2017 — grocery e-commerce investment cycle | margin_pressure | competitive_risk, margin_pressure, capex_cycle |

#### Diversified Bank (JPM) — 5 analogs

| # | Label | Mechanism | Concern Tags |
|---|---|---|---|
| 48 | JPMorgan 2008-2009 — GFC credit cycle (acquired Bear/WaMu) | credit_cycle_loss | cre_credit_risk, macro_slowdown_risk, interest_rate_risk |
| 49 | Wells Fargo 2016 — fake accounts scandal | franchise_credibility_crisis | regulatory_risk, concentration_risk |
| 50 | Citigroup 2008-2009 — TARP bailout requirement | credit_cycle_loss | cre_credit_risk, macro_slowdown_risk, concentration_risk |
| 51 | European banks 2011-2012 — sovereign contagion | credit_cycle_loss | geopolitical_risk, interest_rate_risk, macro_slowdown_risk |
| 52 | Credit Suisse 2023 — confidence crisis + forced merger | credit_event | concentration_risk, regulatory_risk, macro_slowdown_risk |

#### Government Enterprise (PLTR) — 4 analogs

| # | Label | Mechanism | Concern Tags |
|---|---|---|---|
| 53 | Booz Allen Hamilton 2013 — Snowden contract risk | franchise_credibility_crisis | concentration_risk, regulatory_risk |
| 54 | Leidos/SAIC 2012-2013 — sequestration budget cuts | government_budget_cut | macro_slowdown_risk, concentration_risk |
| 55 | MicroStrategy 2000 — narrative-driven tech collapse | multiple_compression | valuation_risk, concentration_risk |
| 56 | DXC Technology 2019-2021 — government IT contract attrition | competitive_displacement | competitive_risk, concentration_risk |

#### Cloud Platform (MSFT) — 4 analogs

| # | Label | Mechanism | Concern Tags |
|---|---|---|---|
| 57 | IBM 1990s — mainframe→client-server platform transition | platform_transition | competitive_risk, margin_pressure |
| 58 | Oracle 2012-2018 — cloud transition multiple compression | platform_transition | competitive_risk, valuation_risk, margin_pressure |
| 59 | Salesforce 2022 — SaaS multiple de-rating (15x→8x rev) | multiple_compression | valuation_risk, interest_rate_risk, margin_pressure |
| 60 | Google Cloud 2020-2023 — third-entrant share gains | competitive_displacement | competitive_risk, capex_cycle |

**Total after expansion: 60 analogs** (22 existing + 38 new)

---

## 3. Scoring Redesign

### Current Weights

| Component | Weight | Problem |
|---|---|---|
| concern_tag Jaccard | **0.40** | Generic tags (valuation_risk, competitive_risk) appear in every thesis → drives cross-sector matches |
| mechanism match | 0.30 | Good, but insufficient to overcome tag flooding |
| setup match | 0.15 | Acceptable |
| sector + business model | 0.10 | Too low — cross-sector matches too easy |
| macro regime | 0.05 | Acceptable |

### Proposed Weights

| Component | Weight | Change | Rationale |
|---|---|---|---|
| **business_model match** | **0.30** | NEW (was part of context at 0.05) | Primary filter: same business model = same risk structure |
| **mechanism match** | **0.25** | ↓ from 0.30 | Still the core structural signal, but no longer sole gate |
| **concern_tag Jaccard** | **0.15** | ↓ from 0.40 | Reduced to prevent generic-tag flooding |
| **sector match** | **0.10** | ↑ from 0.05 | Cross-sector matches should be expensive |
| **setup match** | **0.10** | ↓ from 0.15 | valuation + growth phase |
| **macro regime** | **0.05** | unchanged | |
| quality boost | +0.02 | unchanged | |
| disanalogy penalty | −0.03 | ↓ from −0.05 | Less punitive with better matching |

### Business Model Matching Logic

```python
def _business_model_score(query_biz: str, analog_biz: str) -> float:
    """Score business model similarity with partial credit for related models."""
    if not query_biz or not analog_biz:
        return 0.3  # unknown → neutral (don't penalize)
    if query_biz == analog_biz:
        return 1.0  # exact match
    
    # Partial credit for related business models
    _RELATED_MODELS = {
        ("payment_network", "fintech_platform"):         0.5,
        ("ratings_data_oligopoly", "financial_intermediary"): 0.3,
        ("semiconductor_equipment", "semiconductor_manufacturer"): 0.4,
        ("semiconductor_equipment", "semiconductor_fabless"): 0.3,
        ("cloud_platform", "saas"):                      0.6,
        ("diversified_bank", "financial_intermediary"):   0.7,
        ("membership_retail", "e_commerce"):             0.3,
        ("government_enterprise", "saas"):               0.3,
    }
    pair = tuple(sorted([query_biz, analog_biz]))
    return _RELATED_MODELS.get(pair, 0.0)
```

### New Mechanism Siblings to Add

```python
_MECHANISM_SIBLINGS.update({
    "network_fee_compression":     "regulatory_break",
    "franchise_credibility_crisis": "regulatory_break",
    "export_control_restriction":   "regulatory_break",
    "patent_cliff":                 "competitive_displacement",
    "membership_elasticity_test":   "demand_air_pocket",
    "credit_cycle_loss":            "credit_event",
    "government_budget_cut":        "demand_air_pocket",
    "platform_transition":          "competitive_displacement",
})
```

### RELEVANCE_FLOOR Adjustment

Raise from **0.40 → 0.45**. With better matching, weak cross-sector matches should be filtered more aggressively.

---

## 4. Simulated Expected Results

### Before (current system)

| Company | Top Analog | Why Wrong |
|---|---|---|
| MA | Netflix Q1 2022 | Streaming ≠ payment network |
| SPGI | Qualcomm 2017-2019 | Chip customer ≠ ratings oligopoly |
| ASML | Alibaba 2020-2022 | Chinese antitrust ≠ export controls |
| LLY | Meta 2022 | Social media ≠ pharma pipeline |

### After (with expanded library + scoring reweight)

| Company | Expected Top Analog | Score Estimate | Why Correct |
|---|---|---|---|
| MA | **AmEx 2015 — Costco co-brand loss** | ~0.72 | Same business model (payment_network), same mechanism (network_fee_compression), same concern (concentration_risk, competitive_risk) |
| SPGI | **Moody's 2008 — ratings credibility crisis** | ~0.75 | Same business model (ratings_data_oligopoly), same mechanism (franchise_credibility_crisis), same concern (regulatory_risk) |
| ASML | **Applied Materials 2019 — China export restriction** | ~0.78 | Same business model (semiconductor_equipment), same mechanism (export_control_restriction), same concern (geopolitical_risk) |
| LLY | **Pfizer 2022-2023 — COVID revenue cliff** | ~0.68 | Same business model (pharma_pipeline), same mechanism (patent_cliff), same concern (concentration_risk) |

### Score Breakdown (MA → AmEx example)

```
business_model: payment_network == payment_network     → 0.30 × 1.0  = 0.30
mechanism:      network_fee_compression match          → 0.25 × 1.0  = 0.25
concern_tags:   {competitive_risk, concentration_risk} → 0.15 × 0.67 = 0.10
sector:         financials == financials                → 0.10 × 1.0  = 0.10
setup:          peak_multiple match                    → 0.05         = 0.05
macro:          hiking == hiking                       → 0.05 × 1.0  = 0.05
quality:        strong                                 → +0.02
disanalogy:                                            → −0.03
TOTAL:                                                                  0.84
```

Netflix score under new system: business_model mismatch (payment_network vs internet_platform → 0.0), sector mismatch (financials vs technology → 0.0), mechanism mismatch → 0.0. Total: ~0.12. **Well below the 0.45 floor — filtered out.**

---

## 5. Implementation Roadmap

### Phase 1: Library Expansion (Day 1-2)

**Files:**
- `app/db/data/historical_analogs.json` — add 38 new analog entries

**Work:**
- Write 38 JSON analog objects with all required fields
- Each analog needs: id, label, episode, entity_ticker, sector, business_model, quality_rating, mechanism, concern_tags, valuation_regime, growth_phase, macro_regime, event_start, event_end, drawdown_pct, time_to_trough_days, time_to_recover_days, outcome_summary, reaction_series, why_relevant, disanalogy, base_rate_note, data_confidence, source_note
- Add new business_model values: payment_network, ratings_data_oligopoly, semiconductor_equipment, pharma_pipeline, membership_retail, diversified_bank, government_enterprise, cloud_platform

**LOC:** ~900 (JSON data entries)
**Risk:** Zero — purely additive data, no algorithm change
**Can deploy independently:** Yes — even without scoring changes, the new analogs improve results by providing relevant matches

### Phase 2: Scoring Reweight (Day 2-3)

**Files:**
- `app/evidence_engine.py` — modify `_score_analog()`, add `_business_model_score()`, update weights, add mechanism siblings, raise RELEVANCE_FLOOR

**Work:**
- Add `_business_model_score()` function with partial-credit table
- Reweight scoring formula (tag 0.40→0.15, add biz_model 0.30, etc.)
- Add new mechanism types to `_TAG_TO_PRIMARY_MECHANISM`
- Add new mechanism siblings
- Raise `RELEVANCE_FLOOR` from 0.40 to 0.45
- Update `_infer_sector_biz()` to recognize new business_model values

**LOC:** ~150 (scoring function changes)
**Risk:** Medium — all companies' analog selections change
**Can deploy independently:** No — should deploy after library expansion

### Phase 3: Fingerprint Enhancement (Day 3-4)

**Files:**
- `app/evidence_engine.py` — modify `build_fingerprint()` to use CompanyKnowledgeProfile

**Work:**
- When a CompanyKnowledgeProfile is available, use its structured fields to set:
  - `business_model` from profile (deterministic, not text-inferred)
  - `sector` from profile (deterministic)
  - Additional concern_tags from profile.major_risks
- This makes the fingerprint more stable (less dependent on thesis text)

**LOC:** ~50
**Risk:** Low — additive improvement to fingerprint accuracy
**Depends on:** Structured durability profiles (already deployed)

### Phase 4: Testing + Validation (Day 4-5)

**Files:**
- `tests/test_db/test_evidence_engine.py` — update/expand tests
- New: `tests/test_analog_regression.py` — benchmark regression suite

**Work:**
- Update existing tests for new weights and floor
- Add regression tests: V→AmEx, MA→AmEx, SPGI→Moody's, ASML→AppliedMat, LLY→Pfizer
- Add negative tests: MA≠Netflix, SPGI≠Qualcomm, ASML≠Alibaba, LLY≠Meta
- Run full 11-company production validation

**LOC:** ~200
**Risk:** None — tests only

### Summary

| Phase | Files | LOC | Risk | Deploys Independently |
|---|---|---|---|---|
| 1: Library expansion | historical_analogs.json | ~900 | Zero | Yes |
| 2: Scoring reweight | evidence_engine.py | ~150 | Medium | After Phase 1 |
| 3: Fingerprint enhancement | evidence_engine.py | ~50 | Low | After Phase 2 |
| 4: Testing | test files | ~200 | None | — |
| **Total** | **3 files + tests** | **~1,300** | **Medium** | **Sequential** |

### Estimated Timeline

- Day 1-2: Library expansion (38 analogs, each requiring research for outcome data)
- Day 3: Scoring reweight + fingerprint enhancement
- Day 4: Testing + regression validation
- Day 5: Production validation + deploy

### Migration Risk

**Low.** The library expansion (Phase 1) is purely additive — it can never make results worse because new analogs only add candidates; they don't remove existing ones. The scoring reweight (Phase 2) changes all results, but since the current results are known-bad (MA→Netflix, SPGI→Qualcomm), any change toward business-model-relevant matches is an improvement.

### Regression Risk

**Medium for Phase 2.** The scoring reweight could theoretically make NVDA or TSLA (which currently get good analogs from the existing library) match worse. This is why Phase 4 testing runs the full 11-company suite before deploy.

**Mitigation:** The existing NVDA/TSLA analogs have both mechanism AND sector AND business_model match — they will score even higher under the new weights (business_model match gives them +0.30 that they currently get +0.05 for). The only risk is to companies currently getting acceptable analogs via mechanism-only match; those should be verified.
