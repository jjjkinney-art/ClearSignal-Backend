# Conviction Engine Audit Report

**Date:** 2026-06-23
**Status:** Audit complete. No code changes made.
**Scope:** Full end-to-end trace, compression analysis, benchmarking, proposed replacement framework.

---

## 1. Current Architecture

### Pipeline Flow

```
LLM Thesis Synthesis
  → raw confidence_score (DISCARDED — always overridden)
  
compute_conviction()
  ├─ Score 7 linear dimensions [0, 1]
  │   evidence_quality    × 0.22
  │   evidence_freshness  × 0.14
  │   thesis_alignment    × 0.28  ← LARGEST weight
  │   (1 - macro_uncertainty) × 0.15
  │   valuation_certainty × 0.10
  │   estimate_dispersion × 0.07
  │   (1 - governance_risk) × 0.04
  │
  ├─ Compute business_durability_score [0, 1]
  │   (profile + agent text + evidence signals, 4 layers)
  │
  ├─ Apply archetype floors (if durability ≥ 0.65)
  │   evidence_quality floor 0.56, freshness floor 0.42, alignment floor 0.65
  │
  ├─ Compute expectation_fragility [0.05, 0.95]
  │   (valuation stance + priced-in text signals − durability offset)
  │
  ├─ Compute expectation_asymmetry [0.05, 0.90]
  │   (execution dependency + stance + text signals − durability offset)
  │
  ├─ linear_base_score = weighted sum of 7 dims
  │
  ├─ × fragility_multiplier   (0.78 – 1.0)
  ├─ × asymmetry_multiplier   (0.80 – 1.0)
  │   = raw_score
  │
  ├─ + durability_bonus: max(0, (durability − 0.40) × 0.10)
  │   = raw_score_with_bonus
  │
  ├─ Contradiction compression check (×0.70 / ×0.80 / ×0.88)
  │   (durable floor: compression ≥ 0.82 when durability ≥ 0.65)
  │
  └─ clamp(0.12, 0.92) = final_score
```

### Key Files

| File | Lines | Role |
|---|---|---|
| `app/services/conviction_modeler.py` | ~3,200 | Master scoring engine — all 7 dimensions, durability, fragility, asymmetry, compression, matrix labels |
| `app/services/thesis_synthesizer.py` | ~4,200 | Orchestrator — calls conviction modeler, overrides LLM score |

### Schema Version

`CONVICTION_SCHEMA_VERSION = "6-matrix"` (current production)

---

## 2. Sources of Score Compression

### Problem Statement

Current scores for high-quality compounders cluster in the 38–63% range. This is too compressed — a score of 63 for Visa and 38 for Nvidia does not adequately communicate the quality difference between a near-monopoly payment network and a momentum-driven semiconductor cycle.

### Compression Source #1: Multiplicative Penalty Stacking

The largest compression source is the **triple-multiplication** of penalties:

```
final = base × fragility_mult × asymmetry_mult × compression_factor
```

These multiply, not add. Even modest penalties compound:

| Component | Value | Cumulative |
|---|---|---|
| linear_base | 0.72 | 0.720 |
| × frag_mult (frag=0.45) | ×0.955 | 0.688 |
| × asym_mult (asym=0.40) | ×0.965 | 0.664 |
| × compression (mild) | ×0.880 | 0.584 |
| + dur_bonus (dur=0.70) | +0.030 | 0.614 |

**Impact:** A company with solid evidence (0.72 base) and only moderate fragility/asymmetry/compression loses **15 percentage points** through stacking. For elite compounders, this brings 72 → 61.

### Compression Source #2: Macro Uncertainty Tax (15% weight, always elevated)

`macro_uncertainty` is applied as `(1 - uncertainty) × 0.15`. In the current market regime, macro uncertainty is structurally elevated (Fed policy uncertainty, inflation persistence, geopolitical risk). This means ALL companies pay a ~7–10 point tax from macro alone, regardless of their individual quality.

**The problem:** Visa's cross-border payments business is not meaningfully more macro-sensitive than it was 10 years ago, but the macro dimension treats it identically to a cyclical bank.

**Impact:** ~7–10% score reduction for all companies, irrespective of durability.

### Compression Source #3: Evidence Quality Ceiling (~0.75 typical)

`evidence_quality` has a theoretical max of 0.95 but typically lands at 0.65–0.78 because:
- Base starts at 0.40
- Each evidence source adds a small bonus (+0.07 to +0.18)
- Even perfect evidence coverage (FMP + SEC + analysts + earnings) rarely exceeds 0.78
- The +0.05 density bonus and +0.02 count bonus are too small to matter

**Impact:** The evidence dimension, weighted at 22%, contributes at most ~0.17 to the linear sum. A truly rich evidence set (0.78) vs. a moderate one (0.55) adds only 0.05 to the final score — a difference invisible to the user.

### Compression Source #4: Thesis Alignment Volatility (28% weight)

`thesis_alignment` is the mean of 5 agent confidence scores, penalized for agent disagreement. The problem:

- Agent confidences are LLM-generated and tend to cluster around 0.45–0.70
- The range penalty (-0.03 to -0.12) fires frequently
- Signal consensus penalty (-0.05 to -0.12) fires whenever agents disagree on direction

**Impact:** Even when all 5 agents are mildly bullish (0.55–0.70), the mean is ~0.62, and after range/consensus penalties it drops to ~0.50–0.55. At 28% weight, this contributes ~0.14–0.15 to the score — lower than it should be for a genuine consensus.

### Compression Source #5: Fragility Is Over-Triggered

`expectation_fragility` starts at a base of 0.28 (not zero) and accumulates upward:
- "overpriced" stance: +0.28 (→ 0.56 before any text signals)
- Priced-in text signals: +0.07 each (easily +0.14–0.21 from evidence)
- Then durability offset subtracts only `durability × 0.20` (max −0.20)

For a durable compounder at fair-to-full price:
- Base 0.28 + "fairly_valued" 0.08 + priced-in signals 0.14 = 0.50
- Durability offset: 0.72 × 0.20 = −0.144 → net = 0.356
- Fragility multiplier: 1.0 − (0.356 − 0.35) × 0.45 = 0.997 (minimal penalty)

But for a durable compounder at stretched valuation:
- Base 0.28 + "overpriced" 0.28 + priced-in signals 0.14 = 0.70
- Durability offset: 0.72 × 0.20 = −0.144 → net = 0.556
- Fragility multiplier: 1.0 − (0.556 − 0.35) × 0.45 = 0.907 (−9.3% penalty)

**Impact:** Any company trading at a premium multiple faces a ~5–15% fragility penalty on top of the linear composition. Since most quality compounders trade at premiums, this is a structural ceiling on their scores.

### Compression Source #6: Durability Bonus Is Too Small

The durability persistence bonus is:
```
bonus = max(0, (durability − 0.40) × 0.10)
```

For a durable compounder (durability = 0.72): bonus = 0.032 (3.2 percentage points).

This is too small. A business with 72% durability score — reflecting recurring revenue, switching costs, network effects — gets only 3.2 points added to its conviction. The fragility penalty alone can be 5–15 points. The bonus does not offset the penalty.

### Compression Source #7: No Structural Quality Signal in Linear Composition

None of the 7 linear dimensions directly measure **business quality**:
- `evidence_quality` measures data availability, not business quality
- `thesis_alignment` measures agent agreement, not structural advantage
- `valuation_certainty` measures data availability for valuation, not valuation attractiveness

Durability is computed separately and contributes only through:
1. Archetype floors (only for durability ≥ 0.65)
2. Durability bonus (+3.2% max for elite durability)
3. Fragility/asymmetry offset (−0.14 to −0.20 from fragility)

**The business quality signal — the most important factor for long-term conviction — is buried under layers of penalties rather than being a primary input.**

---

## 3. Benchmark Examples

### Simulated Score Trace

For each company, I trace the pipeline using typical dimension values:

#### Visa (V) — Current: ~63

| Dimension | Typical Value | × Weight | Contribution |
|---|---|---|---|
| evidence_quality | 0.72 | × 0.22 | 0.158 |
| evidence_freshness | 0.80 | × 0.14 | 0.112 |
| thesis_alignment | 0.62 | × 0.28 | 0.174 |
| (1 − macro_uncertainty) | 0.52 | × 0.15 | 0.078 |
| valuation_certainty | 0.60 | × 0.10 | 0.060 |
| estimate_dispersion | 0.70 | × 0.07 | 0.049 |
| (1 − governance_risk) | 0.92 | × 0.04 | 0.037 |
| **linear_base** | | | **0.668** |

Durability: ~0.75 → archetype floors active, durability bonus = +0.035
Fragility: ~0.42 → frag_mult = 0.969 (−3.1%)
Asymmetry: ~0.35 → asym_mult = 0.983 (−1.7%)

```
raw = 0.668 × 0.969 × 0.983 = 0.636
+ bonus 0.035 = 0.671
× compression 0.88 (mild — stretched valuation) = 0.591
durable floor: max(0.591, 0.671 × 0.82) = max(0.591, 0.550) = 0.591
```

**Predicted: 59. Observed: ~63.** Close — the difference is in dimension variance between runs.

**Expected rational range: 72–80.** Visa is a near-monopoly toll road on global commerce. Two companies process 90%+ of global card volume. Recurring transaction fees. No credit risk. Enormous switching costs. 60%+ margins. This should be Tier 1.

**Gap:** −13 to −17 points. Caused by: macro tax (−7), fragility on premium valuation (−3), compression (−6), insufficient durability reward (+3.5 vs needed +10–15).

---

#### Mastercard (MA) — Current: ~44

Similar profile to Visa but lower score suggests either higher fragility (premium multiple) or worse agent alignment in recent runs.

**Expected: 70–78.** Nearly identical business quality to Visa. The 19-point gap between V (63) and MA (44) is itself evidence of score instability — two nearly identical businesses should not produce a 19-point spread.

**Gap:** −26 to −34 points. Same structural causes as Visa, amplified by run-to-run alignment volatility.

---

#### S&P Global (SPGI) — Current: ~53

| Factor | Estimate | Impact |
|---|---|---|
| linear_base | ~0.65 | Solid evidence, moderate alignment |
| Durability | ~0.70 | Data/index monopoly — should be higher |
| Fragility | ~0.48 | Premium multiple → penalty |
| Compression | ~0.88 | Mild trigger |

**Expected: 70–78.** SPGI owns the credit ratings oligopoly (with Moody's), the S&P index franchise, and market data infrastructure. Near-zero churn. Regulatory moat. This is a structural monopoly with higher durability than the score reflects.

**Gap:** −17 to −25 points. Durability underweighted, macro tax, valuation fragility penalty on a quality premium.

---

#### Microsoft (MSFT) — Current: ~48

**Expected: 65–75.** Cloud infrastructure (Azure), enterprise software (Office 365), platform effects. Recurring revenue, high switching costs. Some execution risk on AI CapEx, but the core business is fortress-quality.

**Gap:** −17 to −27 points. Macro tax, fragility on tech premium, AI CapEx narrative adds fragility text signals, alignment volatility between agents.

---

#### Eli Lilly (LLY) — Current: ~46

**Expected: 55–65.** GLP-1 franchise is real but pipeline-dependent. Less structural durability than network-effect businesses. Regulatory and competition risk are genuine. Score should be meaningfully below Visa/SPGI but above Nvidia.

**Gap:** −9 to −19 points. Pharma pipeline = genuine fragility. But the current score underweights the GLP-1 market leadership and overpunishes macro uncertainty.

---

#### Nvidia (NVDA) — Current: ~38

**Expected: 45–55.** Dominant in the current AI cycle but with genuine questions: is this a structural platform shift or a CapEx cycle? High durability of competitive position but fragile earnings expectations. Should be below Lilly (less recurring revenue, more cycle-dependent).

**Gap:** −7 to −17 points. High fragility is partially justified, but macro tax and compression stack are excessive.

---

#### Tesla (TSLA) — estimated

**Expected: 25–38.** Narrative-heavy, binary outcomes, CEO risk, competition intensifying. Low durability. High fragility justified. Current framework may already handle this correctly.

---

### Summary: Expected vs Current

| Company | Current | Expected | Gap |
|---|---|---|---|
| Visa | ~63 | 72–80 | −9 to −17 |
| Mastercard | ~44 | 70–78 | −26 to −34 |
| S&P Global | ~53 | 70–78 | −17 to −25 |
| Microsoft | ~48 | 65–75 | −17 to −27 |
| Eli Lilly | ~46 | 55–65 | −9 to −19 |
| Nvidia | ~38 | 45–55 | −7 to −17 |
| Tesla | ~30? | 25–38 | ±5 |

**The framework is most broken for Tier 1 compounders.** The gap narrows as business quality decreases, confirming that the structural-quality signal is underweighted and the penalty stack is dominating.

---

## 4. Proposed Replacement Framework

### Design Principles

1. **Business quality must be a primary input, not a modifier.** The most important factor in long-term conviction — the structural quality of the business — should appear in the linear composition, not only as a bonus/offset/floor.

2. **Penalties must be additive, not multiplicative.** Multiplicative stacking creates compressive nonlinearities that flatten scores. Penalties should subtract from the score, not multiply it down.

3. **Macro should be attenuated by durability.** A toll-road monopoly is not equally sensitive to macro uncertainty as a regional bank. The macro penalty should scale with business cyclicality.

4. **Evidence quality ≠ conviction.** Rich evidence availability is necessary but not sufficient for high conviction. A data-rich speculative stock should not score higher than a data-moderate monopoly.

5. **Wider scoring bands are better than compressed ranges.** The framework should produce genuine separation: Tier 1 at 72–85, Tier 4 at 20–38.

### Proposed 9-Dimension Linear Model

Replace the current 7+2 model (7 linear + 2 multiplicative) with a 9-dimension linear model:

| Dimension | Weight | Source | Notes |
|---|---|---|---|
| **business_durability** | 0.25 | Computed durability score | PRIMARY quality signal — moat, recurring revenue, switching costs, network effects |
| **thesis_alignment** | 0.20 | Agent consensus | Cross-agent agreement, signal convergence |
| **evidence_quality** | 0.15 | Evidence pool richness | FMP, SEC, analyst coverage |
| **valuation_position** | 0.12 | Valuation stance + fragility | Combined: undervalued → boost, overpriced → penalty |
| **evidence_freshness** | 0.08 | Age of evidence | Recent earnings, filings |
| **execution_certainty** | 0.08 | 1.0 − expectation_asymmetry | Replaces the multiplicative asymmetry penalty |
| **macro_resilience** | 0.06 | (1 − macro_uncertainty) × durability_attenuation | Macro penalty REDUCED for durable businesses |
| **estimate_convergence** | 0.04 | Analyst consensus dispersion | Tight estimates → higher |
| **governance_quality** | 0.02 | 1.0 − governance_risk | Minimal weight — governance rarely differentiates |

**Key changes:**
- `business_durability` becomes the largest weight (25% vs current 0% in linear)
- `valuation_position` replaces the separate `valuation_certainty` + fragility multiplier
- `execution_certainty` replaces the separate asymmetry multiplier
- `macro_resilience` is attenuated: `(1 − macro) × (0.3 + 0.7 × durability)` — durable businesses pay 30–100% of the macro penalty instead of 100%
- No multiplicative stacking — all penalties are inside the linear sum

### Proposed Post-Composition Adjustments

Only **one** post-composition modifier, applied **additively** (not multiplicatively):

**Contradiction penalty** (additive, not multiplicative):
```
if contradiction_detected:
    penalty = -0.03 (mild) | -0.06 (significant) | -0.10 (severe)
    final = linear_sum + penalty
```

Max post-composition penalty: −10 points. Current max: −30 points (0.70 × multiplier stacking).

**Durability floor** (unchanged):
- If durability ≥ 0.65: final_score ≥ 0.45 (prevents durable compounders from collapsing)

### Expected Score Ranges Under New Framework

| Tier | Companies | Expected Range |
|---|---|---|
| **Tier 1: Structural Monopoly** | Visa, Mastercard, SPGI | 72–85 |
| **Tier 2: Platform Compounder** | Microsoft, ASML, Costco | 62–75 |
| **Tier 3: Quality Growth** | Eli Lilly, Nvidia (cycle peak) | 48–62 |
| **Tier 4: Narrative/Speculative** | Tesla, Palantir | 25–40 |

**Spread:** 45–60 points from Tier 1 to Tier 4 (vs current 25–30 point spread).

### Simulated Visa Score Under New Framework

| Dimension | Value | × Weight | Contribution |
|---|---|---|---|
| business_durability | 0.82 | × 0.25 | 0.205 |
| thesis_alignment | 0.62 | × 0.20 | 0.124 |
| evidence_quality | 0.72 | × 0.15 | 0.108 |
| valuation_position | 0.55 | × 0.12 | 0.066 |
| evidence_freshness | 0.80 | × 0.08 | 0.064 |
| execution_certainty | 0.72 | × 0.08 | 0.058 |
| macro_resilience | 0.74 | × 0.06 | 0.044 |
| estimate_convergence | 0.70 | × 0.04 | 0.028 |
| governance_quality | 0.92 | × 0.02 | 0.018 |
| **linear_sum** | | | **0.715** |
| + contradiction penalty | | | 0.000 |
| **final_score** | | | **0.715 → 72** |

Visa moves from 63 → 72. The durability signal (0.82 × 0.25 = 0.205) replaces the lost points from macro tax removal and fragility unstacking.

### Simulated Tesla Score Under New Framework

| Dimension | Value | × Weight | Contribution |
|---|---|---|---|
| business_durability | 0.32 | × 0.25 | 0.080 |
| thesis_alignment | 0.42 | × 0.20 | 0.084 |
| evidence_quality | 0.60 | × 0.15 | 0.090 |
| valuation_position | 0.25 | × 0.12 | 0.030 |
| evidence_freshness | 0.70 | × 0.08 | 0.056 |
| execution_certainty | 0.30 | × 0.08 | 0.024 |
| macro_resilience | 0.35 | × 0.06 | 0.021 |
| estimate_convergence | 0.45 | × 0.04 | 0.018 |
| governance_quality | 0.60 | × 0.02 | 0.012 |
| **linear_sum** | | | **0.415** |
| + contradiction penalty (significant) | | | −0.060 |
| **final_score** | | | **0.355 → 36** |

Tesla stays at 36. The low durability (0.32 × 0.25 = 0.080) naturally produces a low score without needing multiplicative penalty stacking.

**Spread: Visa 72 − Tesla 36 = 36 points** (vs current ~25 points). The framework separates quality tiers more effectively.

---

## 5. Recommended Implementation Order

### Phase 1: Reweight Linear Composition (Low risk)

1. Add `business_durability` as a linear dimension at 0.25 weight
2. Merge `expectation_fragility` into `valuation_position` at 0.12 weight
3. Merge `expectation_asymmetry` into `execution_certainty` at 0.08 weight
4. Add durability attenuation to `macro_resilience`
5. Remove multiplicative fragility/asymmetry multipliers
6. Reduce weights of other dimensions to sum to 1.0
7. Bump CONVICTION_SCHEMA_VERSION to "7-linear"

### Phase 2: Simplify Contradiction Compression (Low risk)

1. Convert compression from multiplicative (×0.70–0.88) to additive (−0.03 to −0.10)
2. Keep the durable-floor protection (durability ≥ 0.65 → floor)
3. Remove severe compression tier (−30% max → −10% max)

### Phase 3: Recalibrate Durability Computer (Medium risk)

1. Increase reward for: recurring revenue, switching costs, network effects, capital efficiency
2. Increase penalty for: narrative dependence, binary outcomes, CEO risk
3. Target ranges: Tier 1 at 0.78–0.88, Tier 4 at 0.25–0.38
4. Validate against the benchmark companies

### Phase 4: Regression Test All Companies (Required)

1. Run the benchmark set (V, MA, SPGI, MSFT, LLY, NVDA, TSLA, COST, ASML, JPM)
2. Verify Tier 1 lands at 72–85
3. Verify Tier 4 lands at 25–38
4. Verify no company score changes by more than 25 points in a single update
5. Verify directional stance labels remain coherent

---

## 6. Estimated Impact on Current Scores

| Company | Current | After Phase 1 | After Phase 2 | After Phase 3 |
|---|---|---|---|---|
| Visa | ~63 | ~68 | ~70 | ~75 |
| Mastercard | ~44 | ~58 | ~62 | ~73 |
| SPGI | ~53 | ~62 | ~65 | ~72 |
| Microsoft | ~48 | ~58 | ~60 | ~68 |
| ASML | ~45 | ~55 | ~58 | ~65 |
| Costco | ~50 | ~58 | ~60 | ~66 |
| Eli Lilly | ~46 | ~50 | ~52 | ~58 |
| Nvidia | ~38 | ~42 | ~44 | ~50 |
| Tesla | ~30 | ~32 | ~32 | ~34 |

**Phase 1 alone** (reweighting, no durability recalibration) produces a ~5–15 point uplift for quality compounders while leaving speculative names roughly unchanged. This is the safest first step.

**Phase 2** (compression simplification) adds another 2–5 points by removing the multiplicative stacking.

**Phase 3** (durability recalibration) adds the final 5–8 points for Tier 1 by properly rewarding structural monopoly characteristics.

---

## Appendix: Dimension Computation Trace (Quick Reference)

```
evidence_quality     = 0.40 base + FMP(+0.18) + analysts(+0.12) + SEC(+0.08) + earnings(+0.07) + density(+0.05) + count(+0.02)
evidence_freshness   = weighted age of top-5 items (0.15 stale → 0.95 fresh)
thesis_alignment     = mean(5 agent confs) − range_penalty − consensus_penalty
macro_uncertainty    = (1 − macro.confidence) + volatility_boost, applied as (1−X)
valuation_certainty  = 0.35 base + FMP(+0.25) + analysts(+0.15) + stance_clarity(+0.15/−0.10), × (0.5 + 0.5 × val.conf)
estimate_dispersion  = text-scan of analyst summaries (0.38 no data → 0.82 tight consensus)
governance_risk      = warning tag weights (0.03–0.12 each), applied as (1−X)

business_durability  = 0.40 base + recurring_rev(+0.15) + resilience(±0.10) − narrative(−0.12) − binary_risk(−0.12) + competitive(+0.08) + text_signals

expectation_fragility = 0.28 base + stance(−0.10 to +0.28) + text_signals(+0.07 each, many categories) − durability_offset(dur×0.20)
expectation_asymmetry = 0.18 base + stance(−0.05 to +0.18) + text_signals(+0.03–0.05 each) − durability_offset(dur×0.12) + cross-amplifiers

fragility_multiplier  = 1.0 − min(0.22, max(0, (frag − 0.35) × 0.45))
asymmetry_multiplier  = 1.0 − min(0.20, max(0, (asym − 0.30) × 0.35))
durability_bonus      = max(0, (dur − 0.40) × 0.10)
compression_factor    = 0.70 | 0.80 | 0.88 | 1.0 (durable floor: ≥ 0.82)

final = clamp(0.12, 0.92, (base × frag_mult × asym_mult + dur_bonus) × compression)
```
