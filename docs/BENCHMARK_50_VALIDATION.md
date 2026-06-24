# 50-Company Benchmark Validation Report

**Date:** 2026-06-24
**Build:** `fb2b14c`
**Companies tested:** 48 (deduplicated from 50)
**Responded successfully:** 37/48 (77%)
**Failed/zero-score:** ADP, KKR, BX, KLAC, LOW, MCD, CAVA, MELI, AXON (score=0), NVO, VEEV (timeout)

---

## 1. Benchmark Table

| # | Ticker | Score | Stance | Dur | Category | Top Driver | Top Risk | Top Analog |
|---|---|---|---|---|---|---|---|---|
| 1 | TSM | 72 | Accumulate | 0.87 | QUAL_CYC | N3/N2 exclusive production | Arizona fab cost competitiveness | Intel 2019 displacement |
| 2 | V | 70 | Accumulate | 0.85 | COMPOUNDER | 5% inflation adds ~5% to top line | 100bps rate rise compresses P/E 3-4 turns | Western Union displacement |
| 3 | MA | 69 | Accumulate | 0.85 | COMPOUNDER | Raised cross-border guidance | 100bps rate rise compresses P/E | India UPI bypass |
| 4 | AVGO | 68 | Accumulate | 0.81 | SEMI | Custom AI ASIC growth | Rate compression | — |
| 5 | SPGI | 67 | Accumulate | 0.78 | COMPOUNDER | Credit ratings oligopoly + S&P 500 franchise | Regulatory changes to ratings | Thomson Reuters competition |
| 6 | META | 67 | Accumulate | 0.77 | QUAL_CYC | 5% DAP increase | Rate compression | Netflix 2022 |
| 7 | WMT | 66 | Accumulate | 0.77 | CONSUMER | Supply chain scale + EDLP | Rate compression | Netflix 2022 |
| 8 | GOOGL | 65 | Accumulate | 0.73 | QUAL_CYC | Dominant Google Search position | Rate compression | Software/cloud de-rating |
| 9 | COST | 63 | Accumulate | 0.69 | COMPOUNDER | Renewal rates 92-93% | Economic downturn | Amazon Prime competition |
| 10 | ASML | 63 | Hold | 0.61 | COMPOUNDER | EUV monopoly | Rate compression | Tokyo Electron merger block |
| 11 | UBER | 63 | Accumulate | 0.69 | OTHER | Advertising revenue growth | Rate compression on driver financing | Meta 2022 |
| 12 | ABBV | 60 | Accumulate | 0.70 | PHARMA | Strong FCF generation | Humira erosion | AbbVie Humira biosimilar (own history) |
| 13 | MSFT | 58 | Accumulate | 0.78 | COMPOUNDER | Azure revenue growth sustained | Intensified cloud competition | Salesforce 2022 compression |
| 14 | JPM | 58 | Hold | 0.64 | QUAL_CYC | NII growth from rates | NIM decline | Credit Suisse 2023 |
| 15 | AMZN | 55 | Hold | 0.70 | QUAL_CYC | AWS margin expansion | AWS growth deceleration | Netflix 2022 |
| 16 | HD | 54 | Hold | 0.70 | CONSUMER | Pro contractor revenue | Declining existing home sales | Software/cloud de-rating |
| 17 | LRCX | 53 | Hold | 0.67 | SEMI | 45% global etch share | NAND WFE decline | Tokyo Electron merger block |
| 18 | SNOW | 53 | Hold | 0.54 | SPECULATIVE | 40x forward earnings (misstated as driver) | AWS/Azure competition | Software/cloud de-rating |
| 19 | SHOP | 50 | Hold | 0.54 | OTHER | Brand recognition | Emerging competitors | Zoom 2022 pull-forward |
| 20 | COIN | 47 | Hold | 0.44 | SPECULATIVE | Transaction volume uptick | Regulatory scrutiny | Meta ATT 2021 |
| 21 | PFE | 45 | Hold | 0.57 | PHARMA | Seagen ADC portfolio | Integration challenges | Biogen Aduhelm |
| 22 | PLTR | 45 | Hold | 0.36 | SPECULATIVE | GAAP profitability milestone | Rate compression | DXC IT contract attrition |
| 23 | LLY | 44 | Hold | 0.39 | COMPOUNDER | Mounjaro fastest-growing diabetes drug | Rate compression | AbbVie Humira biosimilar |
| 24 | AMAT | 44 | Hold | 0.57 | SEMI | Secular semicon growth | Customer CapEx cutback | ASML 2008 CapEx collapse |
| 25 | INTU | 39 | Avoid | 0.54 | OTHER | Brand and network effects | Fintech competition | Software/cloud de-rating |
| 26 | BLK | 35 | Avoid | 0.52 | QUAL_CYC | iShares AUM growth | Market downturn AUM decline | Software/cloud de-rating |
| 27 | QCOM | 35 | Avoid | 0.53 | SEMI | QTL licensing margin | QTL licensing decline | Software/cloud de-rating |
| 28 | SBUX | 35 | Avoid | 0.53 | CONSUMER | Rewards loyalty program | Rewards member decline | Netflix 2022 |
| 29 | NKE | 35 | Avoid | 0.53 | CONSUMER | DTC channel growth | Competitive pressures | Netflix 2022 |
| 30 | CRM | 35 | Avoid | 0.53 | OTHER | Agentforce adoption | Customer retention weakening | Netflix 2022 |
| 31 | AMD | 34 | Avoid | 0.49 | SEMI | Data center revenue growth | Intel/custom ASIC competition | Qualcomm customer concentration |
| 32 | NVDA | 31 | Avoid | 0.42 | SEMI | Data Center growth from Blackwell | Hyperscaler CapEx declining | NVDA 2022 inventory correction |
| 33 | RBLX | 30 | Avoid | 0.37 | SPECULATIVE | User engagement | DAU decline | Netflix 2022 |
| 34 | MCO | 29 | Avoid | 0.37 | COMPOUNDER | Fintech competition erodes... (risk as driver!) | Same text as driver | Software/cloud de-rating |
| 35 | REGN | 29 | Avoid | 0.37 | PHARMA | Regulatory scrutiny (risk as driver!) | Same text as driver | Qualcomm customer concentration |
| 36 | VRTX | 29 | Avoid | 0.37 | PHARMA | Biotech competition (risk as driver!) | Same text as driver | Qualcomm customer concentration |
| 37 | TSLA | 25 | Avoid | 0.18 | SPECULATIVE | Vehicle delivery growth | Rate compression on affordability | Nokia 2007 iPhone disruption |

---

## 2. Anomaly Table

### A) Obvious Mis-Rankings

| Anomaly | Severity | Detail |
|---|---|---|
| **MCO (29) ranked below TSLA (25) area** | CRITICAL | Moody's is a ratings oligopoly duopoly with SPGI. It should score 60-70, not 29. MCO has no structured durability profile (dur=0.37 = text-based fallback), so it gets the same score as a speculative startup. |
| **REGN (29) and VRTX (29)** | HIGH | Regeneron (Dupixent franchise, $12B+ revenue) and Vertex (CF monopoly) should score 45-55 as quality pharma, not 29. Both lack structured profiles and get default dur=0.37. |
| **BLK (35) below COIN (47)** | HIGH | BlackRock ($10T AUM, the world's largest asset manager) scored below Coinbase (crypto exchange with 90% revenue cyclicality). BLK lacks a structured profile. |
| **AVGO (68) above MSFT (58)** | MEDIUM | Broadcom is a quality semiconductor but scoring above Microsoft (deeper moat, more diversified) is questionable. AVGO has a structured profile with dur=0.81; MSFT's LLM dimensions ran low. |
| **UBER (63) = COST (63)** | MEDIUM | Uber at the same score as Costco is aggressive. Uber has no moat comparable to COST's membership model. UBER dur=0.69 seems high for a company with ongoing profitability questions. |

### B) Obvious Mis-Classifications

| Anomaly | Severity | Detail |
|---|---|---|
| **MCO: risk text used as driver** | CRITICAL | MCO driver = "Emerging fintech competition could erode..." — this is a RISK, not a driver. The LLM confused the fields. |
| **REGN: risk text used as driver** | CRITICAL | REGN driver = "Regulatory scrutiny on drug pricing is impacting..." — same confusion. |
| **VRTX: risk text used as driver** | CRITICAL | VRTX driver = "High competition in the biotech sector could..." — same pattern. |
| **SNOW: valuation stated as driver** | MEDIUM | SNOW driver = "At ~40x forward earnings..." — this is a valuation observation, not a business driver. |

### C) Scores Too High

| Ticker | Score | Expected | Why Too High |
|---|---|---|---|
| **UBER** | 63 | 45-55 | dur=0.69 is inflated — Uber's moat is weaker than this implies. No structured profile; text-based durability favored Uber's "network effect" keyword matches. |
| **TSM** | 72 | 60-68 | dur=0.87 — TSMC has a great moat but 0.87 is near V/MA level. The structured profile may over-score TSM's switching costs. TSM has customer concentration risk (Apple ~25% revenue) that should compress durability. |
| **COIN** | 47 | 30-38 | Coinbase at 47 ("Hold") is too high for a company whose revenue drops 80% in crypto winters. dur=0.44 is generous for a crypto exchange. |

### D) Scores Too Low

| Ticker | Score | Expected | Why Too Low |
|---|---|---|---|
| **MCO** | 29 | 60-70 | No structured durability profile → text-based dur=0.37. MCO is Moody's — a ratings duopoly with SPGI. Should be within 5 points of SPGI (67). |
| **REGN** | 29 | 45-55 | No profile → default dur=0.37. Regeneron has Dupixent ($12B+), Eylea, and a deep pipeline. |
| **VRTX** | 29 | 50-60 | No profile → default dur=0.37. Vertex has a monopoly on CF treatment (90%+ share). |
| **BLK** | 35 | 55-65 | No profile → dur=0.52 (text-based). BlackRock's $10T AUM franchise deserves structured durability. |
| **MSFT** | 58 | 65-75 | Has structured profile (dur=0.78) but LLM alignment ran low this run. Variance issue, not structural. |
| **NVDA** | 31 | 45-55 | Has structured profile (dur=0.42) but LLM alignment ran very low. Same variance issue. |

### E) Analogs That Make No Sense

| Ticker | Analog | Problem |
|---|---|---|
| **WMT** → Netflix 2022 | Walmart is a grocery/retail giant. Netflix is a streaming service. Zero business model overlap. |
| **HD** → Software/cloud de-rating | Home Depot is a hardware retailer. Software de-rating is irrelevant. |
| **SBUX** → Netflix 2022 | Starbucks is a restaurant chain. Netflix subscriber stall has no parallel. |
| **NKE** → Netflix 2022 | Nike is an athletic brand. Same problem. |
| **CRM** → Netflix 2022 | Salesforce → Netflix is wrong. CRM should match its own 2022 de-rating (which is in the library). |
| **BLK** → Software/cloud de-rating | BlackRock is an asset manager. Software de-rating is not the mechanism. |
| **QCOM** → Software/cloud de-rating | Qualcomm is a semiconductor company. Wrong sector, wrong mechanism. |
| **REGN** → Qualcomm customer concentration | Regeneron is pharma. Qualcomm's modem customer risk is unrelated. |
| **VRTX** → Qualcomm customer concentration | Same problem — pharma ≠ semiconductor. |
| **MCO** → Software/cloud de-rating | Moody's is a ratings oligopoly. Software de-rating has no parallel. |
| **COIN** → Meta ATT 2021 | Coinbase is crypto. Apple's ATT privacy change is unrelated. |
| **UBER** → Meta 2022 | Uber is ride-hailing. Meta's advertising disruption is unrelated. |

**Pattern:** Companies without structured profiles (no `business_model` override in fingerprint) fall through to the text-inferred business model. When text inference fails (returns None), the `_business_model_score` returns 0.3 (neutral) for ALL analogs, making concern-tag Jaccard the dominant factor again. This produces cross-sector matches.

### F) Generic Drivers/Risks

| Ticker | Generic Signal | Type |
|---|---|---|
| TSLA | "Vehicle delivery growth" | Driver — applies to any EV company |
| NVDA | "Data Center revenue growth" | Driver — generic growth claim |
| COST | "Economic downturn impacting consumer spending" | Risk — sector-level |
| SBUX | "Decline in active Rewards members" | Risk — OK but generic framing |
| NKE | "Competitive pressures" | Risk — applies to any company |
| Multiple | "100bps rate rise compresses P/E by N turns" | Risk — boilerplate for 8 companies |

---

## 3. Statistics

| Metric | Value |
|---|---|
| Companies tested | 48 |
| Successful responses | 37 (77%) |
| Score=0 (synthesis failed) | 8 (17%) |
| Timeouts | 3 (6%) |
| Score range | 25–72 (47 points) |
| Median | 50 |
| Mean | 49.4 |
| Compounders average (V,MA,SPGI,COST,MSFT,ASML,LLY) | 62.0 |
| Speculative average (TSLA,PLTR,RBLX,COIN,SNOW) | 36.0 |
| Analog coverage | 36/37 (97%) |
| Correct analogs | 18/36 (50%) |
| Cross-sector mismatches | 12/36 (33%) |
| Generic driver at #1 | 5/37 (14%) |
| "100bps rate rise" boilerplate | 8/37 (22%) |

---

## 4. Top 10 Remaining Weaknesses (Ranked)

| # | Weakness | Severity | Companies Affected | Root Cause |
|---|---|---|---|---|
| **1** | **Companies without structured durability profiles score 29–37 regardless of quality** | CRITICAL | MCO (29), REGN (29), VRTX (29), BLK (35), and all unprofiled companies | The text-based durability fallback produces ~0.37 for most companies. Only the 11 profiled companies get accurate durability. The remaining 90+ profiles in company_knowledge.py lack structured fields. |
| **2** | **Cross-sector analog matching for unprofiled companies** | HIGH | WMT→Netflix, HD→Software, SBUX→Netflix, NKE→Netflix, BLK→Software, QCOM→Software, MCO→Software, CRM→Netflix | When `business_model` is None (no structured profile), the business_model_score returns 0.3 neutral for ALL analogs, making concern_tag Jaccard dominate → cross-sector matches return. |
| **3** | **"100bps rate rise" boilerplate risk for 22% of companies** | HIGH | V, MA, AVGO, META, GOOGL, ASML, LLY, PLTR | The macro agent generates identical rate-sensitivity text for every company. The generic risk penalty doesn't fire because it contains numbers. |
| **4** | **8 companies returned score=0** (synthesis failure) | HIGH | ADP, KKR, BX, KLAC, LOW, MCD, CAVA, MELI, AXON | LLM synthesis produced invalid JSON or empty thesis. These companies may have insufficient evidence or profile data. |
| **5** | **Risk text used as driver for 3 companies** | HIGH | MCO, REGN, VRTX | The LLM confused key_drivers and key_risks fields — driver contains risk language. These three also have the lowest scores (29), suggesting the entire synthesis was confused. |
| **6** | **LLM thesis_alignment variance still causes ±10-14 point swings** | MEDIUM | MSFT (58 vs target 65-75), NVDA (31 vs target 45-55) | R1-R3 reduced variance from ±16-20 to ±8-10, but some runs still land well outside target range. |
| **7** | **UBER durability inflated (0.69)** | MEDIUM | UBER | Text-based durability matched "network effect" keywords. Uber's moat is weaker than COST's but scores the same durability. |
| **8** | **Netflix 2022 analog overused** | MEDIUM | WMT, AMZN, CRM, SBUX, NKE, RBLX, HD (7 companies) | Netflix 2022 is the "default" analog when no business-model-specific match exists. Its concern_tags (competitive_risk, valuation_risk, macro_slowdown_risk) overlap broadly. |
| **9** | **3 timeouts** | LOW | NVO, VEEV, MCD | Render 60s proxy timeout. Infrastructure issue, not code issue. |
| **10** | **TSM durability (0.87) may be too high** | LOW | TSM | TSM's customer concentration (Apple ~25%) should compress durability below V/MA level. The structured profile may need adjustment. |
