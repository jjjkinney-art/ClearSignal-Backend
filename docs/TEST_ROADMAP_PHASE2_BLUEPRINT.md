# Test Roadmap Phase 2 — Institutional-Grade Validation Blueprint

**Date:** 2026-06-27
**Status:** Blueprint only. No implementation.
**Phase 1 state:** 118/118 structured profiles, 750 tests passing, conviction engine feature-complete.
**Objective:** Prove ClearSignal produces genuinely useful investment decisions.

---

## Executive Summary

Phase 1 proved the engine works correctly. Phase 2 proves it works *usefully*. The distinction is critical: a system can score every company deterministically and still produce reports no investor would pay for.

This blueprint defines 10 evaluation dimensions, prioritized by ROI. The minimum viable validation requires **3 tests** (V1–V3). The full institutional-grade validation requires all 10.

### Priority Map

| ID | Test | ROI | Effort | Phase |
|---|---|---|---|---|
| **V1** | Ranking Coherence Battery | **Highest** | 2–3 hrs | Quick win |
| **V2** | Explanation Quality Scorecard | **Highest** | 3–4 hrs | Quick win |
| **V3** | Decision Usefulness Survey | **High** | 4–6 hrs | Quick win |
| V4 | Historical Analog Usefulness | High | 2–3 hrs | Short-term |
| V5 | Thesis-Change Usefulness | High | 2–3 hrs | Short-term |
| V6 | Failure Taxonomy | Medium | 3–4 hrs | Short-term |
| V7 | Portfolio Intelligence Test | Medium | 4–6 hrs | Medium-term |
| V8 | Competitive Benchmarking | Medium | 6–8 hrs | Medium-term |
| V9 | Blind Analyst Evaluation | High | External | Long-term |
| V10 | Longitudinal KPI Dashboard | Medium | 4–6 hrs | Long-term |

**Recommended minimum:** V1 + V2 + V3 = ~10 hours. These three tests cover ranking, explanation, and decision quality — the three axes that determine whether an investor would pay.

---

## V1: Ranking Coherence Battery

### Purpose

Answer: "Does the system rank companies in an order that an experienced investor would recognize as defensible?"

A system that ranks TSLA above V or MU above MSFT has a credibility problem that no amount of explanation quality can fix. Ranking coherence is the table-stakes test.

### Methodology

Run 118 companies through the full pipeline. Capture conviction_score, directional_stance, durability, and all conviction dimensions. Then apply four tests:

#### Test 1A — Archetype Ordering

Define expected ordering constraints that any credible analyst would agree with. These are not point estimates — they are *pairwise dominance* constraints.

```
COMPOUNDER > CYCLICAL (same sector):
  V > AXP              (pure toll > credit-taking toll)
  MSFT > INTC           (platform monopoly > foundry turnaround)
  COST > TGT            (membership moat > generic retail)
  KO > PEP              (if PEP existed; use MDLZ as proxy)
  MCO > GS              (ratings oligopoly > cyclical IB)

QUALITY > SPECULATIVE:
  MSFT > PLTR            (proven > unproven)
  V > COIN               (payment rail > crypto exchange)
  JNJ > CAVA             (pharma fortress > fast casual)
  COST > RBLX            (real compounder > gaming platform)

SECTOR-APPROPRIATE SPREAD:
  max(Technology) > max(Energy)          (MSFT 0.78 > XOM 0.35)
  max(Healthcare) > max(Commodity)       (UNH 0.73 > MU 0.25)
  min(Compounders) > max(Speculative)    (worst compounder > best speculative)
```

**Scoring:** Each violated constraint = 1 failure. Target: ≤2 violations out of ~30 constraints.

#### Test 1B — Stance Distribution Sanity

Check that the stance vocabulary is being used across its full range and that distribution matches market reality.

```
Expected distribution (approximate, 118 companies):
  Aggressive Buy:  0–3    (≤3% — truly exceptional setups)
  Buy:             5–15   (5–12%)
  Accumulate:      15–30  (13–25% — durable compounders)
  Hold:            30–50  (25–42% — largest bucket)
  Tactical:        5–15   (5–12%)
  Avoid:           15–30  (13–25%)
  Sell:            0–5    (≤4% — rare)
```

**Failure conditions:**
- All companies in same stance (compression failure)
- >50% Accumulate (grade inflation)
- 0 Avoid/Sell (no negative conviction = no signal)
- Aggressive Buy on >5 companies (threshold too low)

#### Test 1C — Durability-Stance Alignment

Verify that durability is actually influencing stance decisions, not just being computed and ignored.

```
For all companies:
  durability ≥ 0.70 → stance ∈ {Accumulate, Buy, Aggressive Buy, Hold}  (never Avoid/Sell)
  durability ≤ 0.30 → stance ∈ {Hold, Tactical, Avoid, Sell}             (never Accumulate+)
  durability ≤ 0.25 → stance ∈ {Avoid, Sell, Hold}                       (never Buy/Accumulate)
```

**Exception:** LLM alignment variance can push a high-durability company to Hold on a bad run. Allow ≤3 exceptions.

#### Test 1D — Score-Stance Monotonicity

Within each durability tier, conviction scores should be monotonically related to stance ordering.

```
For companies in same durability band (±0.05):
  Accumulate should score higher than Hold
  Hold should score higher than Avoid
  Buy should score higher than Hold
```

**Scoring:** Count inversions. Target: ≤5% inversion rate.

### Output Format

```
RANKING COHERENCE REPORT
========================
Archetype ordering:     28/30 constraints satisfied (93%)
  Violations: [list]
Stance distribution:    PASS/FAIL + histogram
Durability-stance:      115/118 aligned (97%)
  Exceptions: [list with reasoning]
Score-stance monotone:  96% monotonic (4% inversions)
  Inversions: [list]

VERDICT: PASS / CONDITIONAL PASS / FAIL
```

---

## V2: Explanation Quality Scorecard

### Purpose

Answer: "Would an experienced analyst read this report and think 'this is useful' or 'this is generic'?"

This is the difference between a $50/month tool and a free screener. The explanation must contain information the investor didn't already know, or frame known information in a way that changes their thinking.

### Methodology

Sample 30 companies (10 compounders, 10 cyclicals, 10 speculative). For each, score the following dimensions on a 1–5 scale:

#### Dimension 2A — Specificity (1–5)

Does the report contain company-specific facts, or could you swap the ticker and the text would still make sense?

```
5 = Names specific products, revenue figures, competitive dynamics
    "iPhone represents 52% of revenue; Apple Intelligence-driven upgrade
     supercycle targeting 600M+ devices on pre-A17 silicon"
4 = References specific business segments with context
    "AWS margin expansion to 35%+ is the key swing factor"
3 = Mentions company name and sector but reasoning is semi-generic
    "Strong market position in cloud computing"
2 = Could apply to 5+ companies in the sector
    "Positioned to benefit from secular growth trends"
1 = Could apply to any company in any sector
    "Strong fundamentals with some macro headwinds"
```

#### Dimension 2B — Quantitative Support (1–5)

Does the report anchor claims in numbers?

```
5 = Multiple specific metrics with context
    "Renewal rates 92-93%, membership fee hike of $5 adds ~$1.5B annual revenue"
4 = At least 2 quantified claims
    "35% gross margin, growing 15% YoY"
3 = One quantified claim + qualitative reasoning
    "Revenue growing double digits"
2 = Vague quantitative language
    "Significant growth potential"
1 = Pure qualitative
    "Strong competitive position"
```

#### Dimension 2C — Uniqueness (1–5)

Does the report say something that Bloomberg Terminal headlines wouldn't?

```
5 = Insight that requires synthesis across multiple data points
    "ASML's EUV orderbook implies TSMC N3 ramp is 6 months ahead of
     Street models — the WFE cycle is front-loaded, not back-loaded"
4 = Non-obvious framing of known facts
    "Google TAC payment ($18-20B/yr) is simultaneously Apple's most
     durable revenue stream and its largest single-point-of-failure risk"
3 = Standard analyst framing
    "Cloud transition is the key growth driver"
2 = Bloomberg headline restatement
    "Revenue beat expectations"
1 = Could be auto-generated from a template
    "Company shows strong growth with some risks"
```

#### Dimension 2D — Boilerplate Detection (binary)

Scan for known boilerplate patterns. Each hit = 1 demerit.

```
Generic patterns (auto-detectable):
  "100bps rate rise compresses P/E by N turns"     (used for 8+ companies)
  "Rate compression"                                (as a standalone risk)
  "Competitive pressures"                           (without naming the competitor)
  "Regulatory scrutiny"                             (without naming the regulation)
  "Market conditions"                               (without specifying which)
  "Growth potential"                                 (without quantifying)
  "Strong fundamentals"                             (without specifying which)
  "Macro headwinds"                                 (without naming the headwind)
  "Positioned to benefit from secular trends"        (without naming the trend)
  "Attractive valuation"                             (without DCF/multiple context)
```

**Scoring:** 0 demerits = clean. ≥3 demerits = boilerplate failure.

#### Dimension 2E — Contradiction Detection (binary)

Check for internal contradictions within the same report.

```
Contradiction patterns:
  - key_driver and key_risk contain the same text (MCO bug from benchmark)
  - Stance is "Accumulate" but reasoning says "significant downside risk"
  - what_increases_conviction contradicts key_drivers[0]
  - Durability is 0.85 but reasoning mentions "uncertain business model"
  - Score is 70+ but setup_label is "fragile setup"
```

**Scoring:** Any contradiction = automatic quality failure for that report.

#### Dimension 2F — Actionability (1–5)

If an investor read only this report, would they know what to do next?

```
5 = Clear action framework with specific triggers
    "Accumulate on weakness below $180. Key catalyst: Q3 Azure growth
     print (Aug 29). Exit trigger: cloud growth below 25% for 2 consecutive Qs."
4 = Clear directional view with monitoring framework
    "Hold current position. Watch for Humira biosimilar erosion rate —
     if >15% annualized, reassess."
3 = Directional view but no triggers
    "Constructive long-term but near-term visibility is limited"
2 = Ambiguous — investor wouldn't change behavior
    "Some positives and some negatives to consider"
1 = No actionable content
    "Company is in the technology sector"
```

### Aggregation

```
Per-company score: mean(2A, 2B, 2C, 2F) - boilerplate_demerits*0.5
  Range: 0.0 to 5.0
  Target: ≥3.5 mean across 30 companies

Quality tiers:
  4.0+ = Institutional grade (worth paying for)
  3.5+ = Professional grade (competitive with free tools)
  3.0+ = Adequate (better than nothing, not differentiated)
  <3.0 = Insufficient (would not retain users)
```

### Output Format

```
EXPLANATION QUALITY SCORECARD
=============================
Company   Spec  Quant  Uniq  Action  Boiler  Contra  Total
-------   ----  -----  ----  ------  ------  ------  -----
V          4.5   4.0   3.5    4.0     0       No     4.0
TSLA       3.0   2.5   2.0    3.0     2       No     2.1
...

Mean specificity:      X.X / 5.0
Mean quant support:    X.X / 5.0
Mean uniqueness:       X.X / 5.0
Mean actionability:    X.X / 5.0
Boilerplate-free:      XX / 30 (XX%)
Contradiction-free:    XX / 30 (XX%)
Overall mean:          X.X / 5.0

VERDICT: Institutional / Professional / Adequate / Insufficient
```

---

## V3: Decision Usefulness Survey

### Purpose

Answer: "If I owned this company, would this report change what I do?"

This is the ultimate test. A report can be specific, quantitative, and unique but still not change an investor's behavior. Decision usefulness requires that the report reveals something the investor didn't already know, or reframes something they knew in a way that shifts their weighting.

### Methodology

For each of 30 companies, simulate an investor who:
- Already owns the stock
- Reads Bloomberg/WSJ daily
- Has a basic understanding of the company's business model

Score the report on a 5-point decision usefulness scale:

```
5 = "I would change my position size based on this report"
    The report identifies a thesis-breaking risk or underappreciated catalyst
    that the investor hadn't considered. This is rare and extremely valuable.

4 = "I would add this to my monitoring checklist"
    The report frames a risk/opportunity in a way that gives the investor
    a specific thing to watch. Not position-changing today, but investment-relevant.

3 = "I already knew this, but the framing is helpful"
    The report correctly identifies the key debates but doesn't add new
    information. Still useful as a structured summary.

2 = "This tells me nothing I don't already know"
    The report restates consensus views without adding analysis.
    An investor who reads Bloomberg already has this information.

1 = "This is actively unhelpful or misleading"
    The report contains errors, irrelevant analogs, or contradictory
    reasoning that would confuse an investor.
```

### Evaluation Protocol

For each company, evaluate three sub-components:

**3A — Key Driver Usefulness**
Would the identified key driver actually be the thing an analyst would focus on? Is it the correct first-order question?

```
V: "5% inflation adds ~5% to top line via transaction volumes"
→ Score: 4 — correct driver (inflation pass-through), quantified,
  but most V investors already know this.

MCO: "Fintech competition erodes..." (risk stated as driver)
→ Score: 1 — wrong field (risk as driver), factually misleading.
```

**3B — Key Risk Usefulness**
Is the identified risk actually the thing that would break the thesis? Or is it a generic sector risk?

```
AAPL: "DOJ antitrust action forces Search default competition —
       Google TAC at risk ($18-20B/yr)"
→ Score: 5 — specific, quantified, thesis-breaking, not obvious
  to most retail investors.

SBUX: "Competitive pressures"
→ Score: 1 — applies to literally every company.
```

**3C — What-Increases-Conviction Usefulness**
Does the "what increases conviction" field identify the actual catalyst an investor should watch?

```
NVDA: "Clarity on hyperscaler CapEx guidance for FY26"
→ Score: 4 — correct first-order uncertainty.

Generic: "Improved financial performance"
→ Score: 1 — meaningless.
```

### Aggregation

```
Per-company: mean(3A, 3B, 3C)
Target: ≥3.0 mean (= "I already knew this, but the framing is helpful")
Stretch: ≥3.5 mean (= "some reports actually add new information")

Distribution targets:
  Score 5: ≥5% of reports (rare but present — the reports that justify paying)
  Score 4: ≥25% of reports (the monitoring-checklist tier)
  Score 3: ≥40% of reports (the structured-summary tier)
  Score 2: ≤25% of reports (consensus restatement — acceptable for less-followed names)
  Score 1: ≤5% of reports (actively bad — these are bugs)
```

---

## V4: Historical Analog Usefulness

### Purpose

Answer: "Do the returned analogs genuinely improve investment understanding, or are they noise?"

### Methodology

For each of 30 companies, evaluate the top analog on a 4-point scale:

```
4 = Highly Useful — same business model, same mechanism, genuinely improves
    understanding of what could happen.
    "NVDA → NVDA 2022 inventory correction" — same company, same mechanism,
    directly informative about downside magnitude and recovery time.

3 = Useful — related business model, related mechanism, provides useful
    historical context even if not perfect.
    "AVGO → ASML 2008 CapEx collapse" — different company but same sector,
    same mechanism (semiconductor capex cycle), informative.

2 = Neutral — technically not wrong but doesn't add investment value.
    "GOOGL → Software/cloud de-rating 2022" — correct sector but the analog
    is so broad it doesn't tell you anything specific about Alphabet.

1 = Misleading — wrong business model, wrong mechanism, would actively
    confuse an investor.
    "WMT → Netflix 2022 subscriber stall" — a grocery retailer matched
    to a streaming service. No business model overlap. Misleading.
```

### Key Metrics

```
Highly Useful (4):     target ≥20% of reports
Useful (3):            target ≥40% of reports
Neutral (2):           acceptable ≤30% of reports
Misleading (1):        target ≤5% of reports (each is a bug)

Cross-sector mismatch rate: target ≤5% (was 33% in pre-structured benchmark)
Same-business-model rate:   target ≥60%
No-analog rate:             acceptable up to 15% (honest "no match" > bad match)
```

### Specific Checks

```
1. Business model alignment: Does the analog's business model match the
   company's business model? (Use _REVENUE_TO_BIZ_MODEL mapping.)

2. Mechanism relevance: Is the analog's mechanism the mechanism most likely
   to affect this company? (A semiconductor company should get capex_cycle
   or inventory_correction, not subscriber_churn.)

3. Disanalogy honesty: Does the disanalogy field identify a real difference,
   or is it boilerplate? ("Different time period" = boilerplate.
   "TSMC's monopoly position is structurally stronger than Intel's
   1999 duopoly" = honest.)

4. Magnitude calibration: Is the drawdown_pct plausible for this type
   of event? (A -57% drawdown analog for a regulated utility would be
   misleading — utilities don't drop 57%.)
```

---

## V5: Thesis-Change Usefulness

### Purpose

Answer: "Does 'what increases conviction' identify true thesis-breaking events, or is it generic?"

### Methodology

For 30 companies, classify the `what_increases_conviction` field:

```
Category A — Thesis-Specific Catalyst (target: ≥50%)
  Names a specific event, metric, or data point that would actually
  change an investor's view.
  "Clarity on FY26 hyperscaler CapEx guidance" (NVDA)
  "Trikafta international pricing acceleration" (VRTX)
  "Ad-supported tier reaching 40M+ subscribers" (NFLX)

Category B — Correct Direction, Insufficient Specificity (target: ≤35%)
  Identifies the right business area but doesn't name the trigger.
  "Cloud growth acceleration" (MSFT) — correct area, but what metric?
  "Margin expansion" (UBER) — which margin? What level?

Category C — Generic / Boilerplate (target: ≤10%)
  Could apply to any company.
  "Improved financial performance"
  "Favorable macroeconomic conditions"
  "Positive earnings surprise"

Category D — Wrong / Contradictory (target: 0%)
  Names something that contradicts the thesis or is factually wrong.
  "NIM trajectory improvement" for a non-bank (SPGI, V, MA)
  Risk language in conviction-increase field
```

### NIM Boilerplate Check

Verify the `_TICKER_UNCERTAINTY_DRIVERS` fix is working:
- V, MA, SPGI should NOT contain "NIM" language
- JPM, BAC, WFC, GS SHOULD contain NIM-related language (it's correct for banks)

---

## V6: Failure Taxonomy

### Purpose

Build a classification system for every failure discovered across V1–V5 so failures can be tracked, prioritized, and fixed systematically.

### Taxonomy

```
RANKING FAILURES (R-class)
  R1: Archetype inversion — compounder ranked below cyclical
  R2: Quality inversion — high-durability company in Avoid
  R3: Speculative inflation — speculative company in Accumulate/Buy
  R4: Score-stance disconnect — high score but negative stance (or vice versa)
  R5: Compression — >60% of companies in same stance

REASONING FAILURES (E-class)
  E1: Risk-as-driver — risk language in key_drivers field
  E2: Driver-as-risk — driver language in key_risks field
  E3: Self-contradiction — stance reasoning contradicts stance
  E4: Dimension contradiction — high durability + "uncertain business model"
  E5: Field confusion — what_increases_conviction contains risk language

EXPLANATION FAILURES (X-class)
  X1: Generic driver — key_driver could apply to 5+ companies
  X2: Generic risk — key_risk could apply to 5+ companies
  X3: Boilerplate — "100bps rate rise" or similar templated text
  X4: NIM boilerplate — NIM/NII language for non-bank companies
  X5: Missing quantitative anchor — no numbers in driver or risk
  X6: Sector-level reasoning — "technology sector growth" instead of
      company-specific analysis

ANALOG FAILURES (A-class)
  A1: Cross-sector mismatch — analog from unrelated sector
  A2: Wrong mechanism — analog mechanism doesn't apply to this company
  A3: Business model mismatch — analog business model ≠ company business model
  A4: Boilerplate disanalogy — "different time period" instead of real difference
  A5: Magnitude implausibility — drawdown_pct impossible for this company type
  A6: Overuse — same analog used for >5 companies in the same run

THESIS-CHANGE FAILURES (T-class)
  T1: Generic conviction driver — "improved performance"
  T2: NIM boilerplate for non-bank
  T3: Risk language in conviction-increase field
  T4: Contradicts key_drivers[0]

PORTFOLIO FAILURES (P-class)
  P1: Concentration blindness — doesn't flag sector concentration
  P2: Correlation blindness — doesn't flag correlated positions
  P3: Missing deterioration — fails to flag declining thesis
  P4: False improvement — flags improvement that isn't supported by evidence

UX FAILURES (U-class)
  U1: Score = 0 (synthesis failure)
  U2: Timeout
  U3: Empty fields (key_drivers empty, what_increases_conviction empty)
  U4: Duplicate content across fields
```

### Severity Matrix

```
CRITICAL (blocks product launch):
  R1, R2, E1, E3, X1 (if >20% of reports), A1 (if >10%)

HIGH (must fix before paid users):
  R3, R4, E2, E5, X3, X4, A2, A3, T2, T3, U1

MEDIUM (fix in first 90 days):
  R5, X2, X5, X6, A4, A5, A6, T1, P1-P4

LOW (improve over time):
  E4, U4
```

---

## V7: Portfolio Intelligence Test

### Purpose

Answer: "Given a real portfolio, does ClearSignal produce portfolio-level intelligence that a PM would find useful?"

### Methodology

Construct 3 synthetic portfolios representing common investor archetypes:

**Portfolio A — Growth/Quality (typical tech investor)**
```
AAPL, MSFT, GOOGL, AMZN, META, NVDA, AVGO, TSM, CRM, SHOP,
NFLX, UBER, PANW, SNOW, PLTR, AMD, COIN, RBLX, TSLA, ABNB
```

**Portfolio B — Dividend/Value (typical income investor)**
```
V, MA, JNJ, PG, KO, MCD, COST, WMT, HD, ABBV,
PFE, MRK, VZ, T, DUK, NEE, O, AMT, EQIX, SPG
```

**Portfolio C — Balanced/Institutional (typical 60/40 PM)**
```
AAPL, MSFT, AMZN, JPM, BAC, UNH, JNJ, PG, XOM, CVX,
V, MA, HD, COST, LMT, RTX, NEE, AMT, BRK.B, GE,
ABBV, TMO, HON, CAT, DE
```

For each portfolio, evaluate whether ClearSignal produces:

```
1. ATTENTION RANKING — Which 3-5 companies deserve attention today?
   (Based on conviction change, thesis deterioration, or catalyst proximity)
   Metric: Does the ranking match what an experienced PM would prioritize?

2. HIDDEN RISK IDENTIFICATION
   Sector concentration:  Does it flag that Portfolio A is 100% tech?
   Factor exposure:       Does it flag that Portfolio A is all high-beta growth?
   Correlation risk:      Does it flag that NVDA/AMD/AVGO/TSM move together?
   Binary event risk:     Does it flag that LLY has a Phase 3 readout?
   Metric: Number of real risks identified / Number of real risks present

3. STRONGEST OPPORTUNITY
   Which company has the best risk/reward right now?
   Metric: Does the identified company have the highest conviction score
   AND a defensible reason for why NOW?

4. DETERIORATING THESIS
   Which companies show declining thesis quality?
   Metric: Can it detect when key_drivers have weakened or when
   what_increases_conviction hasn't materialized?

5. IMPROVING THESIS
   Which companies show strengthening thesis?
   Metric: Same as above, in reverse.

6. CONCENTRATION RISK
   Single-name concentration:  Flag any position >10% of portfolio
   Sector concentration:       Flag any sector >30% of portfolio
   Factor concentration:       Flag correlated risk clusters
   Metric: Accuracy of concentration flags
```

### Scoring

```
Per-portfolio: 6 sub-scores, each 1-5
Aggregate: mean across 3 portfolios × 6 dimensions
Target: ≥3.0 (useful) across all dimensions
Stretch: ≥3.5 (differentiated — does something Bloomberg doesn't)
```

---

## V8: Competitive Benchmarking

### Purpose

Answer: "Where is ClearSignal materially better than existing platforms, and where is it worse?"

### Methodology

For 10 representative companies, compare ClearSignal's output against what an investor would get from each platform. This is a conceptual evaluation, not an API-to-API comparison.

**Evaluation matrix:**

| Dimension | Bloomberg | Morningstar | FactSet | Seeking Alpha | GuruFocus | ClearSignal |
|---|---|---|---|---|---|---|
| Speed to actionable view | ❌ Requires terminal expertise | ⚠️ Report format, slow to parse | ❌ Data-heavy, requires analysis | ⚠️ Article format, variable quality | ⚠️ Metric-heavy, requires interpretation | ✅ Single question → thesis |
| Business model specificity | ✅ Deep fundamental data | ✅ Moat analysis | ✅ Consensus estimates | ⚠️ Varies by author | ⚠️ Quantitative focus | ? Evaluate |
| Historical context | ⚠️ Chart-based, user interprets | ⚠️ Fair value history | ✅ Historical comparables | ⚠️ Author-dependent | ✅ Historical data | ? Evaluate (analog engine) |
| Risk identification | ✅ CDS, options, credit | ⚠️ Uncertainty rating | ✅ Risk models | ⚠️ Author-dependent | ⚠️ Financial health metrics | ? Evaluate |
| Portfolio integration | ✅ PORT function | ⚠️ X-Ray tool | ✅ Portfolio analytics | ❌ None | ❌ None | ? Evaluate |
| Cost | $24K/yr | $200/yr | $12K/yr | $240/yr | $500/yr | TBD |
| Accessibility | ❌ Terminal-only | ✅ Web | ⚠️ Web, complex | ✅ Web | ✅ Web | ✅ Natural language |

### ClearSignal Competitive Advantages to Validate

```
1. SPEED TO INSIGHT (expected advantage)
   Time from "I want to know about NVDA" to actionable thesis:
     Bloomberg: 5-15 min (navigate terminal, read multiple screens)
     Morningstar: 3-5 min (read report)
     ClearSignal: 30-60 sec (ask question, read response)
   → Validate: Is the ClearSignal answer actually as useful in 60 sec
     as 15 min on Bloomberg? Or is it faster but shallower?

2. THESIS FRAMING (expected advantage)
   ClearSignal's thesis is pre-synthesized. Bloomberg gives you data
   and expects you to form the thesis. For non-professional investors,
   this is a genuine advantage.
   → Validate: Does the pre-synthesized thesis miss nuances that
     a Bloomberg user would catch?

3. HISTORICAL ANALOGS (potential advantage)
   No existing platform provides "here's what happened last time a
   company in this situation faced this mechanism" as a structured feature.
   → Validate: Are the analogs actually useful? (V4 covers this.)

4. NATURAL LANGUAGE INTERFACE (expected advantage)
   "What should I think about NVDA?" vs navigating a terminal.
   → Validate: Does the NL interface sacrifice precision for convenience?
```

### ClearSignal Competitive Gaps to Document

```
1. REAL-TIME DATA (gap)
   Bloomberg/FactSet have live data. ClearSignal relies on LLM knowledge
   (training cutoff) + user-provided context.
   → Document: How stale can the data be before the thesis is wrong?

2. QUANTITATIVE MODELS (gap)
   FactSet/Bloomberg have DCF models, consensus estimates, factor models.
   ClearSignal has qualitative reasoning with some quantitative anchoring.
   → Document: For which company types does this matter most?

3. COVERAGE BREADTH (gap)
   Bloomberg covers 50K+ securities. ClearSignal profiles 118.
   → Document: What happens when a user asks about a company not in the DB?

4. REGULATORY/COMPLIANCE (gap)
   Bloomberg terminals are approved for institutional use. ClearSignal
   would need compliance review before institutional adoption.
   → Document: What compliance features are missing?
```

---

## V9: Blind Analyst Evaluation

### Purpose

The gold standard: would an experienced investor rate ClearSignal's output as professional-grade without knowing its source?

### Methodology

**Design:**
1. Select 10 companies across sectors
2. For each company, produce 3 "research briefs" from different sources:
   - ClearSignal output (reformatted to remove branding)
   - Morningstar analyst note (reformatted)
   - GPT-4/Claude raw output (same question, no system prompt)
3. Randomize and anonymize ("Brief A / B / C")
4. Present to 3–5 experienced investors (>5 years experience)

**Evaluation criteria (per brief):**
```
1. "I would use this to make a real investment decision"    (1-5)
2. "This identifies the correct first-order question"       (1-5)
3. "This contains information I didn't already know"        (1-5)
4. "This is specific to this company, not generic"          (1-5)
5. "I would recommend this tool to a colleague"             (1-5)
```

**Success criteria:**
```
ClearSignal rated ≥ raw LLM on all 5 dimensions:     MINIMUM (system prompt adds value)
ClearSignal rated ≥ Morningstar on dimensions 1,4:     STRETCH (speed + specificity win)
ClearSignal rated ≥ 3.5 on all dimensions:             TARGET (professional grade)
```

### Recruitment

Evaluate through:
- Personal network (investors, PMs, analysts)
- Finance subreddits (r/SecurityAnalysis, r/ValueInvesting) — anonymous survey
- Finance Twitter/X — post blinded examples and poll

**Note:** This is the only test that requires external participation. All other tests can be run internally. Defer this until V1–V6 pass.

---

## V10: Longitudinal KPI Dashboard

### Purpose

Track quality over time as the system evolves, so regressions are caught before users notice them.

### Metrics

```
RANKING KPIs (weekly, automated)
  archetype_ordering_score:       % of pairwise constraints satisfied
  stance_distribution_entropy:    Shannon entropy of stance distribution (higher = better spread)
  durability_stance_alignment:    % of companies where dur tier matches stance tier

EXPLANATION KPIs (weekly, automated where possible)
  boilerplate_rate:               % of reports with ≥1 boilerplate pattern
  generic_risk_rate:              % of key_risks that match generic patterns
  nim_boilerplate_rate:           % of non-bank reports with NIM language
  quantitative_density:           mean count of numbers per report
  specificity_proxy:              mean count of company-specific keywords per report

ANALOG KPIs (weekly, automated)
  cross_sector_mismatch_rate:     % of analogs from unrelated sector
  same_business_model_rate:       % of analogs with matching business model
  analog_coverage_rate:           % of companies that receive ≥1 analog above relevance floor
  analog_diversity:               number of unique analogs used across all companies

DECISION KPIs (monthly, manual sample)
  decision_usefulness_mean:       mean score across 30-company sample (1-5)
  thesis_change_specificity:      % of what_increases_conviction in Category A
  actionability_mean:             mean actionability score (1-5)

RELIABILITY KPIs (continuous, automated)
  synthesis_failure_rate:         % of requests returning score=0
  timeout_rate:                   % of requests exceeding 60s
  empty_field_rate:               % of responses with empty key_drivers or key_risks
  run_to_run_variance:            std dev of conviction_score across 5 runs of same company
```

### Alert Thresholds

```
RED (investigate immediately):
  boilerplate_rate > 25%
  cross_sector_mismatch_rate > 15%
  synthesis_failure_rate > 10%
  decision_usefulness_mean < 2.5

YELLOW (investigate within 1 week):
  generic_risk_rate > 20%
  nim_boilerplate_rate > 0%
  run_to_run_variance > 12 points
  analog_coverage_rate < 80%

GREEN (healthy):
  All metrics within targets
```

---

## Implementation Roadmap

### Quick Wins (Week 1) — V1 + V2 + V3

```
Day 1-2: V1 — Ranking Coherence Battery
  - Run 118 companies (reuse validate_100_company.py pattern)
  - Automate archetype ordering constraints
  - Automate stance distribution check
  - Manual review of top-10 and bottom-10

Day 3-4: V2 — Explanation Quality Scorecard
  - Sample 30 companies
  - Score dimensions 2A-2F (manual with automated boilerplate detection)
  - Produce scorecard

Day 5: V3 — Decision Usefulness Survey
  - Score same 30 companies on decision usefulness
  - Cross-reference with V2 scores
  - Identify worst-performing companies
```

**Deliverable:** Quality baseline with numeric scores. First "is this worth paying for?" answer.

### Short-Term (Week 2-3) — V4 + V5 + V6

```
Week 2: V4 + V5 — Analog and Thesis-Change evaluation
  - Score analogs for same 30 companies
  - Classify what_increases_conviction
  - Build automated NIM boilerplate detector

Week 3: V6 — Failure Taxonomy
  - Classify all failures from V1-V5
  - Prioritize by severity
  - Produce fix roadmap
```

**Deliverable:** Complete failure inventory. Prioritized fix list.

### Medium-Term (Week 4-6) — V7 + V8

```
Week 4-5: V7 — Portfolio Intelligence Test
  - Build 3 synthetic portfolios
  - Run all companies
  - Evaluate portfolio-level intelligence

Week 6: V8 — Competitive Benchmarking
  - Conceptual comparison across 6 platforms
  - Document advantages and gaps
  - Identify positioning strategy
```

**Deliverable:** Competitive positioning document. Portfolio feature gap analysis.

### Long-Term (Month 2+) — V9 + V10

```
Month 2: V9 — Blind Analyst Evaluation
  - Recruit 3-5 evaluators
  - Run blinded comparison
  - Analyze results

Ongoing: V10 — KPI Dashboard
  - Automate weekly metric collection
  - Build alerting
  - Track quality over time
```

**Deliverable:** External validation. Continuous quality monitoring.

---

## Minimum Viable Validation

If time is constrained, the **smallest test set that provides the highest confidence** is:

```
1. V1 Test 1A only — Archetype Ordering (30 constraints, 1 hour)
   → Answers: "Is the ranking defensible?"

2. V2 Dimension 2D only — Boilerplate Detection (automated, 30 min)
   → Answers: "How much of the output is generic?"

3. V3 for 10 companies only — Decision Usefulness (2 hours)
   → Answers: "Would an investor find this useful?"
```

Total: ~3.5 hours. This gives a preliminary pass/fail on product viability.

---

## Success Criteria Summary

| Metric | Minimum (launch) | Target (paid product) | Stretch (institutional) |
|---|---|---|---|
| Archetype ordering | ≥90% constraints | ≥95% | ≥98% |
| Boilerplate-free rate | ≥75% | ≥90% | ≥95% |
| Decision usefulness mean | ≥2.5 | ≥3.0 | ≥3.5 |
| Analog useful rate | ≥60% | ≥75% | ≥85% |
| Thesis-change Category A | ≥40% | ≥55% | ≥70% |
| Contradiction rate | ≤5% | ≤2% | 0% |
| Cross-sector analog | ≤10% | ≤5% | ≤2% |
| Synthesis failure rate | ≤10% | ≤5% | ≤2% |
| Run-to-run variance | ≤12 pts | ≤8 pts | ≤5 pts |
| Expert rating (V9) | ≥ raw LLM | ≥3.5/5.0 | ≥ Morningstar |
