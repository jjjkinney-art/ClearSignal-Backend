# Coverage Expansion Phase 4 — Plan (Final Sweep)

**Date:** 2026-06-27
**Status:** Plan only. No code changes.
**Current coverage:** 80/118 structured (68%)
**Target:** 118/118 structured (100%)

---

## 1. Coverage Report

| Metric | Before | After Phase 4 |
|---|---|---|
| Structured profiles | 80 | **118** |
| Coverage | 68% | **100%** |
| Remaining unstructured | 38 | **0** |

---

## 2. Priority Ranking

### Tier 1 — High-Value (S&P 100 members, frequently searched)

| # | Ticker | Company | Sector | Why Urgent |
|---|---|---|---|---|
| 1 | **BA** | Boeing | Industrials | S&P 100, most-searched industrial, turnaround story |
| 2 | **CMCSA** | Comcast | Communications | S&P 100, cable/broadband + NBCUniversal |
| 3 | **T** | AT&T | Communications | S&P 100, telecom peer to VZ/TMUS |
| 4 | **VZ** | Verizon | Communications | S&P 100, telecom staple |
| 5 | **ABT** | Abbott Labs | Healthcare | S&P 100, diversified medtech |
| 6 | **MDT** | Medtronic | Healthcare | S&P 100, largest pure-play medtech |
| 7 | **NEE** | NextEra Energy | Utilities | Largest US utility, renewable energy leader |
| 8 | **UPS** | UPS | Industrials | Logistics duopoly with FedEx |
| 9 | **TGT** | Target | Consumer | Major retailer, peer to WMT |
| 10 | **MDLZ** | Mondelez | Consumer Staples | Global snacks, Oreo/Cadbury franchise |
| 11 | **ETN** | Eaton | Industrials | Electrification/power management leader |
| 12 | **EMR** | Emerson Electric | Industrials | Automation + climate tech |

### Tier 2 — REITs & Infrastructure (important asset classes)

| # | Ticker | Company | Sub-sector | Why Include |
|---|---|---|---|---|
| 13 | **AMT** | American Tower | Cell towers | Largest global tower REIT |
| 14 | **EQIX** | Equinix | Data centers | Largest data center REIT, AI/cloud play |
| 15 | **PLD** | Prologis | Logistics | Largest industrial REIT globally |
| 16 | **O** | Realty Income | Net lease | "Monthly Dividend Company", retail REIT |
| 17 | **SPG** | Simon Property | Malls | Largest US mall REIT |
| 18 | **PSA** | Public Storage | Self-storage | Largest self-storage REIT |
| 19 | **WELL** | Welltower | Senior housing | Largest senior housing REIT |
| 20 | **VICI** | VICI Properties | Gaming | Gaming/experiential REIT |
| 21 | **EQR** | Equity Residential | Apartments | Largest apartment REIT |
| 22 | **AMH** | American Homes 4 Rent | SFR | Single-family rental REIT |

### Tier 3 — Utilities (stable, lower search frequency)

| # | Ticker | Company | Why Include |
|---|---|---|---|
| 23 | **DUK** | Duke Energy | #2 US utility by customers |
| 24 | **SO** | Southern Company | Major Southeast utility |
| 25 | **EXC** | Exelon | Largest US nuclear fleet |
| 26 | **AEP** | American Electric Power | Major Midwest/South utility |
| 27 | **SRE** | Sempra | California + LNG export |
| 28 | **ED** | Consolidated Edison | NYC metro utility |
| 29 | **WEC** | WEC Energy | Upper Midwest utility |
| 30 | **PCG** | PG&E | California utility, wildfire risk |
| 31 | **AWK** | American Water Works | Largest US water utility |

### Tier 4 — Energy & Refining (commodity cyclicals)

| # | Ticker | Company | Why Include |
|---|---|---|---|
| 32 | **SLB** | SLB (Schlumberger) | Largest oilfield services |
| 33 | **EOG** | EOG Resources | Premium E&P operator |
| 34 | **DVN** | Devon Energy | Shale E&P |
| 35 | **OXY** | Occidental Petroleum | Permian + carbon capture |
| 36 | **MPC** | Marathon Petroleum | Largest US refiner |
| 37 | **PSX** | Phillips 66 | Refining + midstream |
| 38 | **VLO** | Valero Energy | Pure-play refiner |

---

## 3. Proposed Structured Fields

### Tier 1 — High-Value (12 companies)

**BA — Boeing**
```
moat_type: ["regulatory", "scale_economy"]
revenue_model: "project_contract"
switching_cost_level: "very_high"
customer_concentration: "moderate"
capital_intensity: "capital_intensive"
earnings_cyclicality: "highly_cyclical"
narrative_dependence: "high"
binary_risk_level: "moderate"
```
Expected durability: **0.38** — Duopoly with Airbus but quality crisis, massive cash burn, highly cyclical commercial aviation orders. Very high switching costs (airlines committed to fleet type). High narrative dependence (737 MAX recovery, defense execution). Binary risk from certification/safety events.

**CMCSA — Comcast**
```
moat_type: ["scale_economy", "regulatory"]
revenue_model: "subscription"
switching_cost_level: "moderate"
customer_concentration: "diversified"
capital_intensity: "capital_intensive"
earnings_cyclicality: "mild"
narrative_dependence: "low"
binary_risk_level: "none"
```
Expected durability: **0.55** — Cable broadband monopoly in many markets (regulatory moat), but cord-cutting headwinds. NBCUniversal/Peacock streaming adds mixed revenue. Capital-intensive (network buildout). Mild cyclicality (broadband is essential).

**T — AT&T**
```
moat_type: ["scale_economy", "regulatory"]
revenue_model: "subscription"
switching_cost_level: "moderate"
customer_concentration: "diversified"
capital_intensity: "capital_intensive"
earnings_cyclicality: "non_cyclical"
narrative_dependence: "none"
binary_risk_level: "none"
```
Expected durability: **0.55** — Telecom duopoly/triopoly with VZ/TMUS. Subscription model with moderate switching costs (contracts, number portability friction). Capital-intensive (5G, fiber buildout). Non-cyclical — people don't cancel phone service in recessions.

**VZ — Verizon**
```
moat_type: ["scale_economy", "regulatory", "brand"]
revenue_model: "subscription"
switching_cost_level: "moderate"
customer_concentration: "diversified"
capital_intensity: "capital_intensive"
earnings_cyclicality: "non_cyclical"
narrative_dependence: "none"
binary_risk_level: "none"
```
Expected durability: **0.58** — Premium telecom brand, best network quality perception. Same structure as T but stronger brand and execution. Non-cyclical essential service.

**ABT — Abbott Laboratories**
```
moat_type: ["patent", "brand", "regulatory"]
revenue_model: "product_sale"
switching_cost_level: "high"
customer_concentration: "diversified"
capital_intensity: "moderate"
earnings_cyclicality: "non_cyclical"
narrative_dependence: "none"
binary_risk_level: "low"
```
Expected durability: **0.62** — Diversified medtech (diagnostics, devices, nutrition, pharma). FreeStyle Libre (CGM) is a consumer-facing franchise with recurring revenue characteristics. Regulatory moat (FDA/CE approvals). Non-cyclical healthcare spending. Low binary risk from product recalls.

**MDT — Medtronic**
```
moat_type: ["patent", "scale_economy", "regulatory"]
revenue_model: "product_sale"
switching_cost_level: "high"
customer_concentration: "diversified"
capital_intensity: "moderate"
earnings_cyclicality: "non_cyclical"
narrative_dependence: "none"
binary_risk_level: "low"
```
Expected durability: **0.62** — Largest pure-play medtech company. Patent portfolio + FDA approvals create deep moat. Surgeons trained on Medtronic devices create switching costs. Non-cyclical (elective procedures defer but don't disappear).

**NEE — NextEra Energy**
```
moat_type: ["regulatory", "scale_economy"]
revenue_model: "subscription"
switching_cost_level: "very_high"
customer_concentration: "diversified"
capital_intensity: "capital_intensive"
earnings_cyclicality: "non_cyclical"
narrative_dependence: "none"
binary_risk_level: "low"
```
Expected durability: **0.62** — Largest US utility + largest renewable energy developer. Regulated utility (FPL) provides stable cash flow. Very high switching costs (customers can't choose utility). Capital-intensive but rate-based recovery. Low binary risk from regulatory/hurricane exposure.

**UPS — United Parcel Service**
```
moat_type: ["scale_economy", "brand"]
revenue_model: "product_sale"
switching_cost_level: "moderate"
customer_concentration: "diversified"
capital_intensity: "capital_intensive"
earnings_cyclicality: "moderate"
narrative_dependence: "none"
binary_risk_level: "none"
```
Expected durability: **0.48** — Logistics duopoly with FedEx but Amazon building competing network. Capital-intensive (fleet, sorting hubs). Moderate cyclicality (e-commerce volumes track consumer spending). No real switching costs — shippers easily compare rates.

**TGT — Target**
```
moat_type: ["brand", "scale_economy"]
revenue_model: "product_sale"
switching_cost_level: "low"
customer_concentration: "diversified"
capital_intensity: "moderate"
earnings_cyclicality: "moderate"
narrative_dependence: "none"
binary_risk_level: "none"
```
Expected durability: **0.42** — Mass-market retailer competing with WMT and AMZN. Brand differentiation ("cheap chic") but low switching costs. Moderate cyclicality — discretionary categories (apparel, home) more sensitive than grocery.

**MDLZ — Mondelez International**
```
moat_type: ["brand", "scale_economy"]
revenue_model: "product_sale"
switching_cost_level: "low"
customer_concentration: "diversified"
capital_intensity: "moderate"
earnings_cyclicality: "non_cyclical"
narrative_dependence: "none"
binary_risk_level: "none"
```
Expected durability: **0.52** — Global snack brands (Oreo, Cadbury, Ritz, Toblerone). Brand moat with pricing power but low switching costs (consumers can buy competitor snacks). Non-cyclical — snack consumption is recession-resistant.

**ETN — Eaton Corporation**
```
moat_type: ["scale_economy", "patent", "brand"]
revenue_model: "product_sale"
switching_cost_level: "high"
customer_concentration: "diversified"
capital_intensity: "moderate"
earnings_cyclicality: "moderate"
narrative_dependence: "none"
binary_risk_level: "none"
```
Expected durability: **0.58** — Electrical/power management leader benefiting from electrification megatrend. High switching costs (electrical infrastructure is designed-in). Patent portfolio in power management. Moderate cyclicality (construction/industrial end markets).

**EMR — Emerson Electric**
```
moat_type: ["scale_economy", "brand", "switching_cost"]
revenue_model: "mixed"
switching_cost_level: "high"
customer_concentration: "diversified"
capital_intensity: "moderate"
earnings_cyclicality: "moderate"
narrative_dependence: "none"
binary_risk_level: "none"
```
Expected durability: **0.58** — Industrial automation + climate tech. High switching costs (control systems deeply embedded in manufacturing processes). Mixed model (product + service/software). Moderate cyclicality from industrial end markets.

### Tier 2 — REITs & Infrastructure (10 companies)

| Ticker | moat_type | revenue_model | switching | concentration | capital | cyclicality | narrative | binary | Est. Dur |
|---|---|---|---|---|---|---|---|---|---|
| **AMT** | regulatory, switching_cost | subscription | very_high | diversified | capital_intensive | non_cyclical | none | none | 0.62 |
| **EQIX** | switching_cost, scale_economy | subscription | very_high | diversified | capital_intensive | non_cyclical | none | none | 0.62 |
| **PLD** | scale_economy, brand | subscription | high | diversified | capital_intensive | mild | none | none | 0.55 |
| **O** | scale_economy | subscription | moderate | diversified | capital_intensive | mild | none | none | 0.52 |
| **SPG** | scale_economy, brand | mixed | moderate | diversified | capital_intensive | moderate | none | none | 0.45 |
| **PSA** | brand, scale_economy | subscription | moderate | diversified | moderate | non_cyclical | none | none | 0.55 |
| **WELL** | scale_economy | subscription | moderate | diversified | capital_intensive | non_cyclical | none | none | 0.50 |
| **VICI** | scale_economy | subscription | very_high | concentrated | capital_intensive | mild | none | none | 0.52 |
| **EQR** | scale_economy, brand | subscription | low | diversified | capital_intensive | mild | none | none | 0.45 |
| **AMH** | scale_economy | subscription | moderate | diversified | capital_intensive | mild | none | none | 0.48 |

### Tier 3 — Utilities (9 companies)

| Ticker | moat_type | revenue_model | switching | concentration | capital | cyclicality | narrative | binary | Est. Dur |
|---|---|---|---|---|---|---|---|---|---|
| **DUK** | regulatory | subscription | very_high | diversified | capital_intensive | non_cyclical | none | low | 0.60 |
| **SO** | regulatory | subscription | very_high | diversified | capital_intensive | non_cyclical | none | none | 0.60 |
| **EXC** | regulatory, scale_economy | subscription | very_high | diversified | capital_intensive | non_cyclical | none | low | 0.60 |
| **AEP** | regulatory | subscription | very_high | diversified | capital_intensive | non_cyclical | none | none | 0.60 |
| **SRE** | regulatory, scale_economy | subscription | very_high | diversified | capital_intensive | non_cyclical | none | low | 0.60 |
| **ED** | regulatory | subscription | very_high | diversified | capital_intensive | non_cyclical | none | none | 0.60 |
| **WEC** | regulatory | subscription | very_high | diversified | capital_intensive | non_cyclical | none | none | 0.60 |
| **PCG** | regulatory | subscription | very_high | diversified | capital_intensive | non_cyclical | none | moderate | 0.55 |
| **AWK** | regulatory, natural_monopoly | subscription | very_high | diversified | capital_intensive | non_cyclical | none | none | 0.62 |

### Tier 4 — Energy & Refining (7 companies)

| Ticker | moat_type | revenue_model | switching | concentration | capital | cyclicality | narrative | binary | Est. Dur |
|---|---|---|---|---|---|---|---|---|---|
| **SLB** | scale_economy, data_advantage | mixed | moderate | diversified | capital_intensive | highly_cyclical | none | none | 0.38 |
| **EOG** | scale_economy | product_sale | none | diversified | capital_intensive | highly_cyclical | none | none | 0.35 |
| **DVN** | scale_economy | product_sale | none | diversified | capital_intensive | highly_cyclical | none | none | 0.35 |
| **OXY** | scale_economy | product_sale | none | diversified | capital_intensive | highly_cyclical | none | low | 0.32 |
| **MPC** | scale_economy | product_sale | none | diversified | capital_intensive | highly_cyclical | none | none | 0.35 |
| **PSX** | scale_economy | mixed | none | diversified | capital_intensive | highly_cyclical | none | none | 0.35 |
| **VLO** | scale_economy | product_sale | none | diversified | capital_intensive | highly_cyclical | none | none | 0.35 |

---

## 4. Notable Expected Score Movements

| Ticker | Before (text ~0.37) | After (structured) | Movement | Why |
|---|---|---|---|---|
| **AMT** | ~0.37 | ~0.62 | **+0.25** | Tower leases = very high switching, non-cyclical, subscription |
| **EQIX** | ~0.37 | ~0.62 | **+0.25** | Data center leases, very high switching, mission-critical |
| **ABT** | ~0.37 | ~0.62 | **+0.25** | Diversified medtech, patent + regulatory moat, non-cyclical |
| **MDT** | ~0.37 | ~0.62 | **+0.25** | Largest medtech, surgeon switching costs, non-cyclical |
| **NEE** | ~0.37 | ~0.62 | **+0.25** | Regulated utility + renewables, very high switching |
| **AWK** | ~0.37 | ~0.62 | **+0.25** | Water monopoly, natural_monopoly + regulatory |
| **DUK/SO/EXC/AEP/ED/WEC** | ~0.37 | ~0.60 | **+0.23** | Regulated utilities, non-cyclical, very high switching |
| **ETN** | ~0.37 | ~0.58 | **+0.21** | Electrification leader, high switching costs |
| **EMR** | ~0.37 | ~0.58 | **+0.21** | Industrial automation, high switching costs |
| **BA** | ~0.37 | ~0.38 | **+0.01** | Narrative dependence + binary risk offset the duopoly moat |
| **OXY** | ~0.37 | ~0.32 | **−0.05** | Commodity cyclical, zero switching costs |

---

## 5. Expected Durability Distribution After Phase 4

| Range | Count | Examples |
|---|---|---|
| 0.80+ | 4 | V, MA, ADP, AXP |
| 0.70–0.79 | 10 | MSFT, SPGI, MCO, INTU, UNH, TMO, SHOP, MCD, KO, VEEV |
| 0.60–0.69 | 24 | COST, GOOGL, CRM, PANW, BLK, BRK.B, ORCL, UBER, AAPL, JPM, AMT, EQIX, ABT, MDT, NEE, AWK... |
| 0.50–0.59 | 20 | CMCSA, T, VZ, PLD, PSA, MDLZ, ETN, EMR, SCHW, KKR, BX, PG, VRTX, DE, REGN... |
| 0.40–0.49 | 17 | GS, TXN, AMAT, LRCX, HD, LOW, NKE, PFE, CAT, DIS, MRK, TGT, SPG, UPS, COIN... |
| 0.30–0.39 | 12 | BA, SLB, XOM, CVX, COP, EOG, DVN, OXY, MPC, PSX, VLO, PLTR |
| 0.20–0.29 | 2 | MU, CAVA |
| <0.20 | 1 | TSLA |

---

## 6. Implementation Plan

**Effort:** ~1 hour (38 companies × 8 fields × ~2 min each)

**Risk:** Zero. No code changes. No formula changes. No regression risk.

**Process:**
1. Add 8 structured fields to each of the 38 existing profiles
2. Run `python3 -c "from app.services.company_knowledge import ..."` to verify all 118 profiles load
3. Run core regression suite (test_conviction_modeler, test_company_knowledge, etc.)
4. Compute and verify durability scores for all 38
5. Commit

**Expected time from start to commit:** ~60–90 minutes.

**Outcome:** 100% structured coverage. Every company in the database gets deterministic durability scoring. Text-based fallback only applies to companies not yet in company_knowledge.py.
