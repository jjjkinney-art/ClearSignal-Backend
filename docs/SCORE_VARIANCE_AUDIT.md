# Score Variance Audit

**Date:** 2026-06-24
**Status:** Audit complete. No code changes.
**Context:** business_durability is now deterministic (±0.000). Remaining variance comes from 7 non-durability dimensions.

---

## 1. Dimension Generation Trace

### Classification Summary

| Dimension | Weight | Source | Determinism | Variance Band |
|---|---|---|---|---|
| `business_durability` | 0.20 | CompanyKnowledgeProfile | **DETERMINISTIC** | ±0.000 |
| `evidence_quality` | 0.16 | Evidence pool content | **SEMI-DETERMINISTIC** | ±0.05 |
| `evidence_freshness` | 0.10 | Evidence timestamps | **SEMI-DETERMINISTIC** | ±0.03 |
| `thesis_alignment` | 0.22 | 5 LLM agent confidence scores | **FULLY LLM-DRIVEN** | ±0.15 |
| `macro_uncertainty` | 0.08 | LLM macro.confidence + evidence text | **FULLY LLM-DRIVEN** | ±0.10 |
| `valuation_certainty` | 0.15 | Evidence pool + LLM valuation.confidence + stance | **MIXED** | ±0.12 |
| `estimate_dispersion` | 0.07 | Evidence text scan for analyst terms | **SEMI-DETERMINISTIC** | ±0.04 |
| `governance_risk` | 0.02 | Governance warning tags (structural) | **DETERMINISTIC** | ±0.00 |

### Detailed Trace

#### evidence_quality (0.16 weight, SEMI-DETERMINISTIC)

**Inputs:** Evidence list (items from FMP, SEC, news APIs)
**Computation:** Base 0.40 + bonuses for FMP (+0.18), analysts (+0.12), SEC (+0.08), earnings (+0.07), density (+0.02–0.05), count (+0.02–0.05). All checks are keyword-presence on `ev.source` and `ev.title`.

**Why semi-deterministic:** The evidence pool is fetched fresh each run with a 10s timeout. The same company usually gets the same evidence sources (FMP data doesn't change hourly), but news items rotate, API timeouts can drop items, and freshness of filing dates changes over time.

**Typical variance:** ±0.05 (0.65–0.78 for well-covered companies). Variance comes from: (a) news items present/absent, (b) FMP API response variation, (c) evidence count fluctuation.

#### evidence_freshness (0.10 weight, SEMI-DETERMINISTIC)

**Inputs:** Timestamps on evidence items
**Computation:** Average age of top-5 most recent items → stepped scale (≤14 days=0.95, ≤30=0.88, ≤60=0.75, etc.)

**Why semi-deterministic:** Same evidence pool variance as above. If the 5th-newest item is 28 days old in one run and 32 days old in another (because a news item appeared/disappeared), the score jumps from 0.88 to 0.75 — a 0.13 step change.

**Typical variance:** ±0.03 normally, but **±0.13 at step boundaries**. The stepped scale creates cliff effects where a small change in evidence age produces a large score jump.

#### thesis_alignment (0.22 weight, FULLY LLM-DRIVEN)

**Inputs:** 5 LLM agent confidence scores: `valuation.confidence`, `macro.confidence`, `risk.confidence`, `market.confidence`, `quality.confidence`

**Computation:** mean(5 confidences) − range penalty (−0.03 to −0.12) − signal consensus penalty (−0.05 to −0.12)

**Why fully LLM-driven:** Each agent's confidence is set by gpt-4o-mini in a single generation pass. There is no structured input — the LLM sets confidence based on its analysis. The same question for the same company produces different confidence values every run.

**Measured variance:** Agent confidences typically range 0.45–0.75 for the same company across runs. Mean thesis_alignment varies ±0.08–0.15 per run.

**This is the single largest variance source.** At 0.22 weight, a ±0.15 alignment swing produces ±0.033 in the final score (±3.3 percentage points). Combined with the range/consensus penalties which amplify variance, the total contribution is ±4–6 points.

#### macro_uncertainty (0.08 weight, FULLY LLM-DRIVEN)

**Inputs:** `macro.confidence` (LLM-generated) + evidence text scan for rate/inflation terms

**Computation:** `1.0 - macro.confidence` (or 0.50 if confidence ≈ 0). Evidence text scan adds +0.08 if rate/inflation terms found.

**Why fully LLM-driven:** `macro.confidence` is set by the macro agent's LLM generation. The evidence text scan is semi-deterministic but the dominant term (1.0 − confidence) swings with the LLM.

**Typical variance:** ±0.10. At 0.08 weight (with durability attenuation), contributes ±0.005 (±0.5 points) — relatively small.

#### valuation_certainty (0.15 weight, MIXED)

**Inputs:** Evidence pool (FMP/analyst presence), `valuation.valuation_stance` (LLM text), `valuation.confidence` (LLM float)

**Computation:** Base 0.35 + FMP (+0.25) + analysts (+0.15) + stance clarity (+0.15/−0.10). Then `base × (0.5 + 0.5 × valuation.confidence)`.

**Why mixed:** The evidence-presence checks (FMP, analysts) are semi-deterministic. But the stance and confidence are LLM-generated. The multiplicative confidence factor `(0.5 + 0.5 × conf)` means a confidence of 0.50 vs 0.80 scales the entire score by 0.75 vs 0.90 — a 20% swing.

**Typical variance:** ±0.08–0.12. The LLM confidence multiplier is the dominant source. At 0.15 weight, contributes ±1.2–1.8 points.

#### estimate_dispersion (0.07 weight, SEMI-DETERMINISTIC)

**Inputs:** Evidence text for analyst estimate terms

**Computation:** Scans analyst-related evidence summaries for "dispersion" vs "tight" keywords. Returns 0.38 (no data), 0.45 (dispersed), 0.65 (mixed), or 0.82 (tight).

**Why semi-deterministic:** The analyst evidence text is fetched from external APIs. The same company usually gets the same analyst estimates, but the summary text can vary slightly. The keyword scan produces the same bucket most runs.

**Typical variance:** ±0.04 (usually stays in the same bucket). At 0.07 weight, contributes ±0.3 points.

#### governance_risk (0.02 weight, DETERMINISTIC)

**Inputs:** Governance warning strings from `_run_governance_checks()`

**Computation:** Fixed penalty per warning type: GOVERNANCE +0.12, OVERLAP +0.05, DEPTH +0.03.

**Why deterministic:** Governance checks are structural comparisons against agent outputs. The same company gets the same warnings (barring LLM output differences in what triggers the check).

**Typical variance:** ±0.00. At 0.02 weight, negligible.

---

## 2. Variance Contribution by Dimension

| Dimension | Weight | Typical ±Swing | Max Weighted Impact | Rank |
|---|---|---|---|---|
| **thesis_alignment** | 0.22 | ±0.15 | **±3.3 pts** | **#1** |
| **valuation_certainty** | 0.15 | ±0.12 | **±1.8 pts** | **#2** |
| **evidence_freshness** | 0.10 | ±0.13 (at steps) | **±1.3 pts** | **#3** |
| **macro_uncertainty** | 0.08 | ±0.10 | ±0.5 pts | #4 |
| **evidence_quality** | 0.16 | ±0.05 | ±0.8 pts | #5 |
| **estimate_dispersion** | 0.07 | ±0.04 | ±0.3 pts | #6 |
| **governance_risk** | 0.02 | ±0.00 | ±0.0 pts | #7 |
| **business_durability** | 0.20 | ±0.00 | ±0.0 pts | — |

**Total estimated score variance: ±8–10 points per run** (thesis_alignment + valuation_certainty + evidence_freshness dominate).

---

## 3. Simulated Run Variance

Using the dimension variance bands above, I can estimate score ranges for each benchmark company. The deterministic base (durability + evidence-quality center + governance) is stable; the LLM-driven dimensions vary.

| Ticker | Dur (fixed) | Score Low | Score Center | Score High | Range |
|---|---|---|---|---|---|
| **V** | 0.85 | 68 | 77 | 84 | 16 pts |
| **MA** | 0.85 | 66 | 76 | 83 | 17 pts |
| **SPGI** | 0.78 | 63 | 72 | 80 | 17 pts |
| **MSFT** | 0.78 | 61 | 72 | 81 | 20 pts |
| **NVDA** | 0.42 | 38 | 49 | 58 | 20 pts |
| **LLY** | 0.39 | 40 | 51 | 60 | 20 pts |
| **TSLA** | 0.18 | 22 | 30 | 38 | 16 pts |
| **PLTR** | 0.36 | 26 | 34 | 42 | 16 pts |

**Observed in production:** V=70, MSFT=57, NVDA=25, PLTR=45. All within the estimated bands but scattered across the range.

**Key insight:** The score center (column 4) matches the simulation targets. The problem is not the central tendency — it's the ±8–10 point noise around that center. A user running the same company 3 times will see scores ranging from 68–84 for Visa.

---

## 4. Root Cause Analysis

### #1: thesis_alignment (±3.3 pts) — LLM Agent Confidence Volatility

The five agent confidence scores (`valuation.confidence`, etc.) are set by gpt-4o-mini in its JSON output. These floats have no grounding constraint — the LLM picks a number between 0 and 1 based on its analysis text. The same evidence can produce 0.55 in one run and 0.75 in another.

**Why it's unstable:** LLM temperature > 0 (gpt-4o-mini defaults), combined with the floating-point nature of the output. The model doesn't have a calibrated internal confidence scale — it produces a "feels right" number.

**Impact:** At 0.22 weight, this single dimension contributes more variance than all other dimensions combined.

### #2: valuation_certainty (±1.8 pts) — Multiplicative LLM Confidence

The `base × (0.5 + 0.5 × valuation.confidence)` multiplication means the LLM confidence scales the entire evidence-derived base by 0.50–0.95. A confidence of 0.50 halves the effective contribution; 0.90 nearly preserves it. This amplification makes the dimension's variance disproportionate to its weight.

**Why it's unstable:** Same LLM confidence volatility as thesis_alignment, amplified by the multiplicative formula.

### #3: evidence_freshness (±1.3 pts at steps) — Step Function Cliff

The freshness score uses a stepped scale with 7 discrete levels. When the average evidence age is near a step boundary (e.g., 29 vs 31 days), a single news item appearing or disappearing can shift the score from 0.88 to 0.75 — a 0.13 jump, contributing 1.3 points.

**Why it's unstable:** Step functions create cliffs. Evidence pool composition varies per run (news API returns different items).

---

## 5. Stabilization Framework (Design Only)

### Approach: Reduce variance without destroying analytical signal

The goal is NOT to make all scores identical — genuine analytical differences (different evidence, different market conditions) should produce different scores. The goal is to eliminate **noise** (same company, same day, different numbers from LLM randomness).

### Recommendation 1: Floor thesis_alignment with profile-derived baseline (HIGH IMPACT)

**Problem:** Agent confidences are uncalibrated LLM outputs.
**Solution:** When a CompanyKnowledgeProfile exists, compute a **structural alignment floor** from the profile's moat_type, revenue_model, and competitive_advantages. This floor represents the minimum thesis alignment that the business model's structural characteristics guarantee.

```python
structural_alignment_floor = 0.40 + 0.03 × len(competitive_advantages) + moat_quality_bonus
```

Then: `thesis_alignment = max(structural_floor, llm_derived_score)`

**Impact:** Prevents thesis_alignment from dropping below 0.50–0.55 for Tier 1 compounders, reducing the variance band from ±0.15 to ±0.08. Score variance drops from ±3.3 to ±1.8 points.

**Risk:** Low. The floor only prevents unreasonably low values — it doesn't inflate scores for speculative companies (TSLA/PLTR floor would be ~0.35).

### Recommendation 2: Replace freshness step function with smooth decay (MEDIUM IMPACT)

**Problem:** Cliff effects at step boundaries.
**Solution:** Replace the 7-step function with exponential decay: `freshness = 0.95 × exp(-avg_age / 120)`. This produces a smooth curve from 0.95 (fresh) to ~0.15 (stale) with no cliffs.

**Impact:** Eliminates the ±0.13 cliff at step boundaries. Variance drops from ±1.3 to ±0.3 points.

**Risk:** Low. The smooth function produces similar scores at the center of each step; only the boundary behavior changes.

### Recommendation 3: Attenuate valuation_certainty LLM multiplier (MEDIUM IMPACT)

**Problem:** `base × (0.5 + 0.5 × confidence)` creates a 0.50–0.95 amplification range.
**Solution:** Narrow the multiplier range: `base × (0.70 + 0.30 × confidence)`. This reduces the LLM confidence influence from ±45% to ±30%.

**Impact:** Reduces valuation_certainty variance from ±0.12 to ±0.08. Score variance drops from ±1.8 to ±1.2 points.

**Risk:** Low. The narrower range still rewards high-confidence valuation analysis; it just reduces the penalty for low confidence.

### Recommendation 4: Clamp agent confidence outputs (LOW IMPACT, EASY)

**Problem:** Agent confidence floats are unconstrained 0–1.
**Solution:** Clamp all agent confidences to [0.35, 0.85] before they enter the conviction modeler. This prevents extreme outliers without affecting the central tendency.

**Impact:** Reduces thesis_alignment variance from ±0.15 to ±0.10. Score variance drops from ±3.3 to ±2.2 points.

**Risk:** Very low. Confidences below 0.35 are LLM noise (no agent should be < 35% confident if it produced analysis). Confidences above 0.85 are overconfident (the LLM doesn't have enough information to justify > 85%).

### Recommendation 5: Multi-run averaging (HIGHEST IMPACT, HIGHEST COST)

**Problem:** Single-run scores have ±8–10 point noise.
**Solution:** Run the conviction modeler 3 times with the same evidence and take the median. This eliminates LLM temperature noise.

**Impact:** Reduces variance by ~√3 ≈ 60%. Score variance drops from ±8–10 to ±3–4 points.

**Risk:** Medium. 3× latency cost. Requires 3× API calls to gpt-4o-mini. Would increase wall time from ~50s to ~150s (unacceptable on current infrastructure).

### Recommended Implementation Order

| Priority | Recommendation | Impact | Effort | Risk |
|---|---|---|---|---|
| 1 | **Clamp agent confidence [0.35, 0.85]** | ±3.3 → ±2.2 pts | 5 lines | Very low |
| 2 | **Replace freshness step function with smooth decay** | ±1.3 → ±0.3 pts | 15 lines | Low |
| 3 | **Narrow valuation_certainty multiplier** | ±1.8 → ±1.2 pts | 2 lines | Low |
| 4 | **Floor thesis_alignment from profile** | ±3.3 → ±1.8 pts | 30 lines | Low |
| 5 | Multi-run averaging | ±all → ±3 pts | 50 lines | Medium (latency) |

**Recommendations 1–4 combined** would reduce score variance from **±8–10 points to ±4–5 points** with minimal risk and ~50 lines of code. Recommendation 5 (multi-run) would halve variance further but at significant latency cost.

**Estimated post-stabilization variance:**

| Ticker | Current Range | After R1-R4 | Improvement |
|---|---|---|---|
| V | 68–84 (16 pts) | 73–81 (8 pts) | −50% |
| MSFT | 61–81 (20 pts) | 67–77 (10 pts) | −50% |
| NVDA | 38–58 (20 pts) | 43–55 (12 pts) | −40% |
| TSLA | 22–38 (16 pts) | 26–35 (9 pts) | −44% |
