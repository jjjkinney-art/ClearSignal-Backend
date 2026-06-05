"""
Institutional conviction modeler.

Produces a conviction score with real distributional spread by separating:
  (a) a seven-dimension LINEAR COMPOSITION of evidence, alignment, and macro quality
  (b) two NON-LINEAR POST-COMPOSITION MULTIPLIERS that capture expectation risk and
      execution asymmetry — dimensions whose effect on confidence should be threshold-
      triggered and compounding, not smoothed by a weighted average.

This architecture prevents midpoint gravity: a great business with stretched expectations
and narrow execution margin compounds two penalties multiplicatively, driving the score
into the "fragile/speculative" band even when evidence quality is high.

Architecture
────────────
                   ┌─────────────────────────────────────────────────┐
                   │  compute_conviction(evidence, agents, company…)  │
                   └──────────────────┬──────────────────────────────┘
                                      │
           ┌──────────────────────────▼──────────────────────────────┐
           │          Seven-dimension linear composition               │
           │  evidence_quality  · evidence_freshness                   │
           │  thesis_alignment  · macro_uncertainty                    │
           │  valuation_certainty · estimate_dispersion                │
           │  governance_risk                                           │
           └──────────────────────────┬──────────────────────────────┘
                                      │ _linear_base_score()
                                      ▼
                           base_score  (0–1)
                                      │
                    ┌─────────────────▼────────────────────────────┐
                    │  × fragility_multiplier (0.78–1.0)            │
                    │    (priced-in perfection, acceleration risk)   │
                    └─────────────────┬────────────────────────────┘
                                      ▼
                    ┌─────────────────▼────────────────────────────┐
                    │  × asymmetry_multiplier (0.85–1.0)            │
                    │    (execution dependency, optionality reliance) │
                    └─────────────────┬────────────────────────────┘
                                      ▼
                           pre_compression_score  (0–1)
                                      │
                    ┌─────────────────▼────────────────────────────┐
                    │  × compression_factor                          │
                    │  mild   (×0.88): single moderate trigger       │
                    │  significant (×0.80): stretched val + signals  │
                    │  severe  (×0.70): 3+ compounding triggers      │
                    └─────────────────┬────────────────────────────┘
                                      ▼
                           final_score  (0–1) + setup_label

Confidence band semantics
──────────────────────────
  80–92  high-alignment thesis       — fresh evidence + aligned agents + defensible multiple
  65–79  actionable thesis           — constructive with monitored open variables
  65–79  monitoring required         — same score range, fragility or asymmetry elevated
  50–64  expectation-sensitive       — good business but demanding setup
  50–64  fragile setup               — cross-agent conflict or stale evidence
  35–49  speculative setup           — weak evidence / unresolved contradictions
  35–49  asymmetric setup            — high execution dependency at stretched valuation
  12–34  insufficient conviction     — data too thin to form a defensible view

Linear dimension weights (must sum to 1.0)
──────────────────────────────────────────
  evidence_quality    20%  — source credibility, FMP coverage, density
  evidence_freshness  15%  — age of items (recent earnings boost, old filings penalise)
  thesis_alignment    25%  — cross-agent agreement + signal direction consensus
  macro_uncertainty   15%  — inverted: high uncertainty → lower score
  valuation_certainty 15%  — live ratio data, stance clarity, analyst data
  estimate_dispersion  6%  — analyst estimate convergence vs absence
  governance_risk      4%  — inverted: governance warnings → lower score

Post-composition multipliers (not in linear weights)
─────────────────────────────────────────────────────
  expectation_fragility  — priced-in perfection risk; penalty above 0.40 threshold
  expectation_asymmetry  — execution dependency; penalty above 0.35 threshold
"""
from __future__ import annotations

import dataclasses
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

_logger = logging.getLogger(__name__)

from ..schemas import (
    CompanyContext,
    CompanyKnowledgeProfile,
    MacroSensitivity,
    MarketContext,
    QualityAssessment,
    RetrievedEvidence,
    RiskProfile,
    ValuationView,
)

# ── Company-specific uncertainty drivers ─────────────────────────────────────
# Named variables that, when unresolved, suppress conviction for specific tickers.

_TICKER_UNCERTAINTY_DRIVERS: Dict[str, List[str]] = {
    # Semiconductors / AI infrastructure
    "NVDA":  ["hyperscaler CapEx guidance",        "custom ASIC adoption timeline",     "export restriction escalation"],
    "AMD":   ["GPU data-center share versus NVDA",  "MI300X enterprise attach rate",     "custom silicon competition intensifying"],
    "AVGO":  ["AI ASIC revenue concentration risk", "VMware integration trajectory",     "networking upgrade cycle cadence"],
    "ASML":  ["China EUV export controls",          "logic capex order visibility",       "High-NA EUV ramp timeline"],
    "LRCX":  ["WFE spending cycle trajectory",      "China equipment restriction risk",   "memory capex recovery pace"],
    "TSM":   ["geopolitical Taiwan risk premium",   "CoWoS packaging capacity",          "AI chip demand durability"],
    "ARM":   ["royalty rate renegotiation risk",    "custom silicon commoditisation",     "AI-specific IP adoption pace"],
    # Mega-cap technology
    "AAPL":  ["China demand trajectory",            "Services growth deceleration risk",  "hardware replacement cycle elongation"],
    "MSFT":  ["Azure growth deceleration",          "AI Copilot enterprise attach rate",  "cloud margin compression from AI capex"],
    "GOOGL": ["Search market-share erosion by AI",  "Cloud margin trajectory",            "AI-driven query monetization"],
    "GOOG":  ["Search market-share erosion by AI",  "Cloud margin trajectory",            "AI-driven query monetization"],
    "META":  ["Reels monetization durability",      "AI capex ROI timeline",             "regulatory ad-targeting constraints"],
    "AMZN":  ["AWS growth deceleration",            "retail margin recovery trajectory",  "AI services competitive moat"],
    "NFLX":  ["ad-tier ARPU scaling",              "password-sharing churn tail",        "content margin structure"],
    "CRM":   ["AI Agentforce attach rate",          "seat-count growth deceleration",     "competitive displacement risk"],
    # Enterprise SaaS / data / cloud
    "PLTR":  ["government contract renewal risk",   "commercial revenue growth durability","AI platform enterprise attach rate"],
    "SNOW":  ["enterprise AI spending persistence", "platform consumption growth rate",   "competitive displacement by warehouse-native AI"],
    "NOW":   ["AI workflow monetization pace",      "federal seat-count expansion",       "competitive displacement from platform sprawl"],
    "DDOG":  ["observability market consolidation", "enterprise consumption recovery",    "AI-driven workload monitoring attach rate"],
    "MDB":   ["Atlas consumption recovery pace",    "developer seat-count deceleration",  "competitive pressure from AWS DocumentDB"],
    "HUBS":  ["SMB demand resilience",              "AI-Breeze attach rate",              "seat expansion amid macro softness"],
    # Industrials / defense / aerospace
    "LMT":   ["DoD budget trajectory",             "F-35 program delivery cadence",      "classified programme contribution visibility"],
    "GE":    ["LEAP engine delivery backlog",       "services attach rate",               "power-grid demand durability"],
    "CAT":   ["infrastructure cycle direction",     "dealer inventory destocking pace",   "China construction activity"],
    "DE":    ["precision-ag adoption durability",   "farm equipment demand cycle",        "dealer channel inventory level"],
    # Consumer / retail
    "COST":  ["membership fee renewal rate",        "discretionary spend mix trajectory", "private-label penetration pace"],
    "TGT":   ["discretionary spend recovery",       "inventory shrink trajectory",        "private-label margin recovery"],
    "NKE":   ["China sell-through recovery",        "DTC margin trajectory",              "Americas wholesale channel reset"],
    # Energy / commodity
    "XOM":   ["oil price floor assumption",         "Permian Basin growth trajectory",    "LNG contract realisation"],
    "CVX":   ["Tengiz project ramp-up",             "oil price assumptions",              "Hess integration execution"],
    # Healthcare / Pharma
    "VRTX":  ["pipeline durability post-Trikafta",  "next-gen CFTR therapy data",        "pricing negotiation outcome"],
    "LLY":   ["GLP-1 manufacturing capacity",       "Mounjaro/Wegovy demand durability",  "biosimilar competitive entry"],
    "NVO":   ["GLP-1 obesity indication expansion", "Wegovy supply constraint resolution","biosimilar competitive timeline"],
    "REGN":  ["Dupixent patent cliff timeline",     "next pipeline milestone",            "PD-1 competitive positioning"],
    "MRNA":  ["mRNA platform commercial viability", "flu vaccine uptake data",            "oncology pipeline readout"],
    "ISRG":  ["robotic surgery system utilisation", "da Vinci 5 adoption curve",         "procedure volume recovery"],
    "CRSP":  ["FDA approval cadence for exa-cel",   "insurance reimbursement clarity",    "manufacturing scale economics"],
    # Financials
    "JPM":   ["NIM compression from rate normalisation", "credit cycle delinquency curve","IB revenue recovery pace"],
    "BAC":   ["NIM sensitivity to Fed rate path",   "credit-card charge-off trajectory",  "capital return clarity"],
    "GS":    ["IB fee pipeline recovery",           "market-making revenue volatility",   "FICC normalisation"],
    "MS":    ["wealth-management flow resilience",  "IB backlog conversion rate",         "capital markets recovery"],
    # Consumer
    "AMZN":  ["AWS growth deceleration",            "retail margin recovery",             "AI competitive moat"],
    "WMT":   ["grocery pricing power durability",   "eCommerce margin trajectory",        "advertising revenue attach"],
    "TSLA":  ["EV margin floor",                    "FSD regulatory approval pace",       "Optimus commercialisation timeline"],
}

_SECTOR_UNCERTAINTY_DRIVERS: Dict[str, List[str]] = {
    "Technology":             ["AI capex cycle sustainability",   "rate sensitivity on growth multiples",   "hyperscaler demand visibility"],
    "Health Care":            ["pipeline regulatory approval",    "pricing negotiation outcomes",           "patent cliff exposure"],
    "Financials":             ["NIM trajectory vs rate path",     "credit cycle delinquency trend",         "capital return clarity"],
    "Consumer Discretionary": ["consumer spending resilience",    "credit cycle impact on discretionary",   "pricing power durability"],
    "Consumer Staples":       ["volume vs pricing mix",           "private-label competition intensity",    "input cost deflation pass-through"],
    "Energy":                 ["commodity price trajectory",      "supply discipline adherence",            "transition capital allocation"],
    "Industrials":            ["capex cycle direction",           "margin recovery pace",                   "backlog conversion timeline"],
    "Materials":              ["commodity demand cycle",          "China construction activity",            "supply rationalization"],
    "Utilities":              ["rate-driven valuation adjustment", "renewable capex return visibility",      "regulatory rate-case outcomes"],
    "Real Estate":            ["rate sensitivity on cap rates",   "occupancy recovery trajectory",          "refinancing cost exposure"],
    "Communication Services": ["advertising cycle recovery",      "streaming subscriber trajectory",        "platform regulatory pressure"],
}

_DEFAULT_UNCERTAINTY_DRIVERS = [
    "near-term earnings trajectory",
    "valuation multiple durability under current macro conditions",
    "analyst estimate convergence",
]

# ── Source quality fingerprints ───────────────────────────────────────────────

_HIGH_QUALITY_SOURCES = ("fmp", "ratios-ttm", "key-metrics-ttm", "analyst-estimates",
                         "price-target", "sec", "edgar", "10-k", "10-q", "earnings call")
_MEDIUM_QUALITY_SOURCES = ("newsapi", "bloomberg", "reuters", "wsj", "ft", "barrons")
_EARNINGS_KEYWORDS = ("earnings", "eps", "quarterly results", "guidance", "fiscal",
                      "revenue beat", "revenue miss", "net income", "q1 ", "q2 ",
                      "q3 ", "q4 ", "annual results")

# ── Linear dimension weights ──────────────────────────────────────────────────
# Seven dimensions only. expectation_fragility and expectation_asymmetry are
# NOT in this table — they are post-composition multipliers (see below).

_WEIGHTS = {
    # Phase 6 calibration:
    #   evidence_quality  ↑ 0.20→0.22  (reward richer evidence pools)
    #   thesis_alignment  ↑ 0.25→0.28  (cross-agent signal convergence is the
    #                                    strongest forward-looking conviction signal)
    #   valuation_certainty ↓ 0.15→0.10  (valuation pressure CAPS upside via
    #                                    fragility/asymmetry multipliers — it
    #                                    should not also drag the base score for
    #                                    elite businesses at fair-to-full prices)
    #   estimate_dispersion ↑ 0.06→0.07
    #   governance_risk unchanged 0.04
    #   macro_uncertainty unchanged 0.15
    #   evidence_freshness unchanged 0.14  (small reduction to offset others)
    "evidence_quality":    0.22,
    "evidence_freshness":  0.14,
    "thesis_alignment":    0.28,
    "macro_uncertainty":   0.15,   # applied as (1 - macro_uncertainty)
    "valuation_certainty": 0.10,
    "estimate_dispersion": 0.07,
    "governance_risk":     0.04,   # applied as (1 - governance_risk)
}
assert abs(sum(_WEIGHTS.values()) - 1.0) < 1e-9, "Weights must sum to 1.0"

# ── Post-composition multiplier configuration ─────────────────────────────────
# expectation_fragility and expectation_asymmetry apply AFTER the linear sum as
# compounding non-linear penalties.  This prevents the linear averaging from
# smoothing away extreme valuation or execution signals.
#
# Each multiplier is thresholded: below the threshold, no penalty.
# Above the threshold, a linear penalty ramps up to the configured maximum.
#
# Phase 5c calibration (spread pressure):
#   fragility: 0.35 threshold (earlier onset), 0.45 scale (steeper ramp), 0.22 max
#              → at fragility 0.65: 13.5% penalty | at 0.80: 20.3% | at 0.95: 22% (capped)
#   asymmetry: 0.30 threshold (earlier onset), 0.35 scale (steeper ramp), 0.20 max
#              → at asymmetry 0.60: 10.5% penalty | at 0.75: 15.8% | at 0.90: 20% (capped)
#
# The _MAX caps are intentionally modest: even at worst-case fragility + asymmetry,
# a genuinely strong evidence base can still land in the 40–55% band rather than
# collapsing to "insufficient conviction".  The compression tier handles additional
# penalty when multiple structural triggers compound.

_FRAGILITY_THRESHOLD = 0.35   # Phase 5c: was 0.40 — penalty onset earlier
_FRAGILITY_SCALE     = 0.45   # Phase 5c: was 0.40 — steeper ramp to the cap
_FRAGILITY_MAX       = 0.22   # UNCHANGED — prevents over-compression for rich-but-real businesses

_ASYMMETRY_THRESHOLD = 0.30   # Phase 5c: was 0.35 — penalty onset earlier
_ASYMMETRY_SCALE     = 0.35   # Phase 5c: was 0.27 — steeper ramp
_ASYMMETRY_MAX       = 0.20   # Phase 5c: was 0.15 — higher ceiling for execution-binary setups

# ── Compression trigger thresholds ───────────────────────────────────────────
# Three severity tiers; the worst applicable tier is chosen, then compounded
# if multiple triggers fire simultaneously.

_COMPRESSION_MILD        = 0.88   # single moderate trigger
_COMPRESSION_SIGNIFICANT = 0.80   # stretched valuation + expectation mismatch
_COMPRESSION_SEVERE      = 0.70   # three or more compounding triggers

_MIN_SCORE = 0.12
_MAX_SCORE = 0.92

# Tickers where expectations are structurally elevated relative to evidence
# ── Durability-based calibration constants ────────────────────────────────────
#
# Phase 3 Architecture: COMPUTED DURABILITY replaces hardcoded ticker frozensets.
#
# Both _QUALITY_DURABLE_TICKERS and _HIGH_EXPECTATION_TICKERS are REMOVED.
# The system now computes business_durability_score [0, 1] from four layered sources:
#
#   1. CompanyKnowledgeProfile (structured facts — highest signal quality)
#      - recurring_revenue_sources quality and count
#      - recession_behavior resilience keywords
#      - valuation_style narrative/optionality signals (reduces durability)
#      - major_risks binary-outcome signals (reduces durability)
#      - competitive_advantages depth
#
#   2. QualityAssessment agent text (moat, revenue_durability, operating_quality)
#   3. RiskProfile agent text (binary risk, execution dependency signals)
#   4. Evidence corpus (recurring revenue, moat, defensive demand signals)
#
# This generalizes to ANY company in the universe:
#   High durability (0.65+) → Costco, MSFT, JPM, ASML, Visa — qualifies for label floor
#   Moderate durability (0.40–0.64) → NVDA, sector-specific compounders — some offset, no floor
#   Low durability (<0.40) → TSLA, PLTR, pre-revenue biotech — minimal offset, no floor
#
# Crucially: the valuation_stance signal ("overpriced" → +0.28 fragility) already
# captures the high-expectation dimension for any stock at elevated multiples.
# No ticker-specific premium is needed — the valuation agent provides this signal.

# Maximum fragility reduction for a perfectly durable business (durability_score = 1.0).
# Applied as: fragility -= durability_score × _DURABILITY_MAX_FRAGILITY_OFFSET
# At durability = 0.72: offset = 0.72 × 0.20 = 0.144 → COST overpriced: 0.56 - 0.144 = 0.416
_DURABILITY_MAX_FRAGILITY_OFFSET  = 0.20

# Maximum asymmetry reduction for a perfectly durable business.
# Recurring businesses have structurally lower execution binary-risk.
# COST membership renewal is not binary. MSFT O365 churn is not fragile-execution.
_DURABILITY_MAX_ASYMMETRY_OFFSET  = 0.12

# Minimum durability_score required for the label floor to fire.
# Below this threshold: the label floor does NOT apply — the business has not
# demonstrated sufficient structural durability through profile + agent signals.
# A durable business scores 0.65+ through: high-quality recurring revenue +
# recession resilience + absence of binary/narrative risk signals.
_DURABILITY_FLOOR_THRESHOLD = 0.65


# ── Setup archetype inference constants ───────────────────────────────────────
#
# Archetypes are INFERRED from durability_score — NOT from ticker identity.
# They encode: "what minimum scoring does this business class deserve even
# when literal evidence items are sparse?"
#
# The CompanyKnowledgeProfile encodes business model facts (recurring revenue
# structure, recession behavior, moat depth) as structured evidence.  For a
# durable compounder, the profile itself provides substantial conviction about
# the business setup even when real-time evidence items are absent or thin.
# These floors represent that information content of the profile.
#
# Archetype tiers (by durability_score):
#
#   durable_compounder (≥ 0.65):
#     Examples: COST, MSFT, JPM, ASML, V, MA, GOOGL, META
#     Profile knowledge → inherently well-understood recurring economics
#     evidence_quality floor:   0.56  (profile knowledge = substantial evidence)
#     evidence_freshness floor: 0.42  (business model stability)
#     thesis_alignment floor:   0.65  (structural conviction from known moat)
#     Plus durability bonus: +(durability-0.40)×0.10 ≈ +0.032 for COST
#     Plus compression floor: factor ≥ 0.82 (no over-compression for quality)
#     Target confidence range: 62–72% (Durable label)
#
#   expectation_sensitive_quality (0.55–0.65):
#     Examples: NVDA, AAPL, AMZN — quality but CapEx/growth-rate dependent
#     evidence_quality floor:   0.34
#     evidence_freshness floor: 0.24
#     thesis_alignment floor:   0.52  (ta ≥ 0.50 → "fragile setup" not speculative)
#     Target confidence range: 50–62% (Demanding label)
#
#   narrative_fragile / speculative_narrative (< 0.55):
#     Examples: TSLA, PLTR, SNOW — narrative-dependent, binary execution
#     No floors applied: standard sparse-evidence behavior
#     Target confidence range: <45% (Fragile or Speculative label)
#
# NOTE: The old constraint "_DURABLE_EQ_FLOOR < 0.50" was needed for a label
# floor trigger (evidence_quality < 0.50 → "mixed evidence") that was REMOVED
# in Phase 6.  setup_label now comes exclusively from _durability_matrix_label().
# The EQ floor can safely exceed 0.50.

_ARCHETYPE_DURABLE_THRESHOLD   = 0.65   # same as _DURABILITY_FLOOR_THRESHOLD
_ARCHETYPE_QUALITY_THRESHOLD   = 0.55   # between durable and narrative tiers

# Durable compounder floors — Phase 6 calibration (raised from 0.48/0.30/0.56)
# NOTE: The old constraint "EQ_FLOOR < 0.50" was needed for a label-floor trigger
# that has been REMOVED in Phase 6 (label now comes from _durability_matrix_label,
# not evidence_quality threshold).  These floors can safely exceed 0.50.
#
# Target score range with live evidence for COST/MSFT: 62–72%
# Sparse-evidence COST floor: ~42%  (floors only, no live evidence boost)
_DURABLE_EQ_FLOOR = 0.56   # was 0.48 — profile knowledge = substantial evidence baseline
_DURABLE_EF_FLOOR = 0.42   # was 0.30 — business model stability reduces freshness drag
_DURABLE_TA_FLOOR = 0.65   # was 0.56 — structural moat = persistent thesis alignment

# Expectation-sensitive quality floors
_QSEN_EQ_FLOOR = 0.34      # was 0.32
_QSEN_EF_FLOOR = 0.24      # was 0.22
_QSEN_TA_FLOOR = 0.52      # unchanged — ta ≥ 0.50 keeps "fragile setup" (not speculative)

# ── Durability persistence bonus ──────────────────────────────────────────────
# Applied as an additive bonus to raw_score after composition.
# Represents the persistent baseline conviction that business durability itself
# contributes — independent of evidence depth.
#
# Rationale: a durable compounder at full valuation is NOT equivalent to a
# speculative name at fair valuation.  The business quality premium must persist
# in the score even when evidence is mixed or the setup is demanding.
#
# Formula: bonus = max(0, (durability_score - 0.40) × _DURABILITY_BONUS_SCALE)
# At durability 0.72 (COST/MSFT):  +0.032  (+3.2pp)
# At durability 0.60 (threshold):   +0.020  (+2.0pp)
# At durability 0.55 (NVDA):        +0.015  (+1.5pp)
# At durability 0.40 (neutral):     +0.000  (no bonus)
# At durability 0.35 (TSLA/PLTR):   +0.000  (no bonus, clamped at 0)
_DURABILITY_BONUS_SCALE = 0.10

# ── Compression floor for high-durability businesses ─────────────────────────
# Even with maximum compression, a durable compounder (durability ≥ 0.65) cannot
# be pushed below this fraction of its raw pre-compression score.
# Prevents over-compression from stacking triggers for elite businesses.
# Value 0.82 means: compression can at most take 18% off the raw score.
# (Worst-case _COMPRESSION_SEVERE = ×0.70 becomes ×0.82 for durable compounders)
_DURABLE_MIN_COMPRESSION_FACTOR = 0.82


def _infer_archetype_floors(
    durability_score: float,
) -> Tuple[float, float, float]:
    """Infer evidence-quality/freshness/thesis-alignment floors from durability_score.

    Returns (eq_floor, ef_floor, ta_floor).

    Archetypes are inferred from the computed durability_score — no ticker identity.
    Any business that accumulates sufficient structural durability signals through
    profile + agent + evidence automatically qualifies for its archetype tier.

    Floors activate only when raw dim values fall below them (sparse evidence).
    With rich evidence, raw values exceed floors → no effect.
    """
    if durability_score >= _ARCHETYPE_DURABLE_THRESHOLD:
        return _DURABLE_EQ_FLOOR, _DURABLE_EF_FLOOR, _DURABLE_TA_FLOOR
    elif durability_score >= _ARCHETYPE_QUALITY_THRESHOLD:
        return _QSEN_EQ_FLOOR, _QSEN_EF_FLOOR, _QSEN_TA_FLOOR
    else:
        return 0.0, 0.0, 0.0  # narrative_fragile / speculative_narrative — no floors


# ── Data containers ───────────────────────────────────────────────────────────

@dataclasses.dataclass
class ConvictionDimensions:
    """Normalised 0–1 sub-scores for each conviction dimension.

    LINEAR dimensions (7, in _WEIGHTS):
      evidence_quality, evidence_freshness, thesis_alignment, valuation_certainty,
      estimate_dispersion — higher = better conviction.
      macro_uncertainty, governance_risk — higher = MORE risk (applied inverted).

    POST-COMPOSITION MULTIPLIER dimensions (2, NOT in _WEIGHTS):
      expectation_fragility — priced-in perfection risk; applied as a thresholded
                              penalty multiplier after the linear sum.
      expectation_asymmetry — execution dependency / optionality reliance; second
                              compounding multiplier applied after fragility.

    Both multiplier dimensions are stored here for API observability / debug panel.
    """
    evidence_quality:      float = 0.5
    evidence_freshness:    float = 0.5
    thesis_alignment:      float = 0.5
    macro_uncertainty:     float = 0.5   # high → bad
    valuation_certainty:   float = 0.5
    estimate_dispersion:   float = 0.5
    governance_risk:       float = 0.0   # high → bad
    expectation_fragility: float = 0.28  # high → bad; post-composition multiplier
    expectation_asymmetry: float = 0.20  # high → bad; post-composition multiplier

    def to_dict(self) -> Dict[str, float]:
        return dataclasses.asdict(self)


@dataclasses.dataclass
class ConvictionResult:
    """Output of ``compute_conviction``."""
    final_score:                  float
    dimensions:                   ConvictionDimensions
    confidence_reasoning:         str
    what_increases_conviction:    str
    setup_label:                  str   = "actionable thesis"
    compression_applied:          bool  = False
    compression_reasons:          List[str] = dataclasses.field(default_factory=list)
    fragility_multiplier_applied: float = 1.0
    asymmetry_multiplier_applied: float = 1.0
    # ── Directional stance (pre-launch product refinement) ────────────────────
    directional_stance:           str   = "Hold"
    directional_stance_reasoning: str   = ""
    # ── Analysis Foundation (Phase 2 — user-facing structured provenance) ─────
    # Clean, institutional-quality content for the Analysis Foundation section.
    # No internal telemetry labels (no GAP_* codes, no dimension names).
    # Replaces the raw confidence_reasoning wall in the production UI.
    analysis_foundation_evidence:    List[str] = dataclasses.field(default_factory=list)
    analysis_foundation_constraints: List[str] = dataclasses.field(default_factory=list)
    analysis_foundation_sources:     List[str] = dataclasses.field(default_factory=list)
    # ── Expectation Intelligence (Part 3) ─────────────────────────────────────
    expectation_regime:              str = "fair"   # cheap|fair|stretched|euphoric|bubble
    expectation_shift_severity:      str = "none"   # none|minor|moderate|significant|major


# ── Timestamp parser (reuse from calibrator pattern) ─────────────────────────

_TS_FORMAT_LENGTHS: List[Tuple[str, int]] = [
    ("%Y-%m-%dT%H:%M:%SZ", 20),
    ("%Y-%m-%dT%H:%M:%S",  19),
    ("%Y-%m-%dT%H:%M",     16),
    ("%Y-%m-%d",            10),
    ("%Y-%m",                7),
]


def _parse_ts(ts: Optional[str]) -> Optional[datetime]:
    if not ts:
        return None
    for fmt, n in _TS_FORMAT_LENGTHS:
        try:
            return datetime.strptime(ts.strip()[:n], fmt).replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            continue
    return None


def _age_days(ts: Optional[str]) -> Optional[int]:
    dt = _parse_ts(ts)
    if dt is None:
        return None
    return (datetime.now(timezone.utc) - dt).days


# ── Dimension computers ───────────────────────────────────────────────────────

def _score_evidence_quality(evidence: List[RetrievedEvidence]) -> float:
    """Score the quality and credibility of the evidence pool (0–1)."""
    if not evidence:
        return 0.15

    base = 0.40
    has_fmp_val = any(
        any(kw in (f"{ev.source} {ev.title}").lower()
            for kw in ("ratios-ttm", "key-metrics-ttm", "valuation_ratios", "fmp-ratios", "pe ratio"))
        for ev in evidence
    )
    has_analyst = any(
        any(kw in (f"{ev.source} {ev.title}").lower()
            for kw in ("analyst-estimates", "price-target", "analyst_estimates", "consensus"))
        for ev in evidence
    )
    has_filing = any(
        any(kw in (f"{ev.source} {ev.title}").lower()
            for kw in ("sec", "edgar", "10-k", "10-q", "8-k"))
        for ev in evidence
    )
    has_earnings = any(
        any(kw in (f"{ev.title} {ev.summary}").lower() for kw in _EARNINGS_KEYWORDS)
        for ev in evidence
    )
    high_q_count = sum(
        1 for ev in evidence
        if any(kw in (f"{ev.source} {ev.title}").lower() for kw in _HIGH_QUALITY_SOURCES)
    )

    if has_fmp_val:  base += 0.18
    if has_analyst:  base += 0.12
    if has_filing:   base += 0.08
    if has_earnings: base += 0.07
    # Density bonus: 5+ high-quality items
    if high_q_count >= 5: base += 0.05
    elif high_q_count >= 3: base += 0.02
    # Item count bonus (more coverage = more quality)
    if len(evidence) >= 10: base += 0.05
    elif len(evidence) >= 5: base += 0.02

    return round(min(0.95, max(0.10, base)), 4)


def _score_evidence_freshness(evidence: List[RetrievedEvidence]) -> float:
    """Score evidence freshness based on weighted age of items (0–1)."""
    if not evidence:
        return 0.15

    ages = [_age_days(getattr(ev, "timestamp", None)) for ev in evidence]
    known_ages = [a for a in ages if a is not None]

    if not known_ages:
        return 0.38   # no timestamps → penalised; conclusions may be stale

    # Weight towards the most recent items (top-5)
    recent_ages = sorted(known_ages)[:5]
    avg_age = sum(recent_ages) / len(recent_ages)

    # Freshness scale
    if avg_age <= 14:   return 0.95
    if avg_age <= 30:   return 0.88
    if avg_age <= 60:   return 0.75
    if avg_age <= 90:   return 0.62
    if avg_age <= 120:  return 0.50
    if avg_age <= 180:  return 0.38
    if avg_age <= 365:  return 0.25
    return 0.15


def _score_thesis_alignment(
    valuation: ValuationView,
    macro: MacroSensitivity,
    risk: RiskProfile,
    market: MarketContext,
    quality: QualityAssessment,
    ranked: Optional[Any],
) -> float:
    """Score cross-agent agreement and signal direction consensus (0–1)."""
    confs = [
        valuation.confidence, macro.confidence, risk.confidence,
        market.confidence, quality.confidence,
    ]
    mean_conf  = sum(confs) / len(confs)
    conf_range = max(confs) - min(confs)

    score = mean_conf

    # Penalise wide cross-agent spread
    if conf_range >= 0.40: score -= 0.12
    elif conf_range >= 0.30: score -= 0.07
    elif conf_range >= 0.20: score -= 0.03

    # Signal direction consensus
    if ranked is not None and getattr(ranked, "all_ranked", None):
        all_sigs  = ranked.all_ranked
        bullish_n = sum(1 for s in all_sigs if s.direction == "bullish")
        bearish_n = sum(1 for s in all_sigs if s.direction == "bearish")
        total_n   = max(len(all_sigs), 1)
        dominant_share = max(bullish_n, bearish_n) / total_n
        if dominant_share < 0.55:   score -= 0.12  # genuine split
        elif dominant_share < 0.65: score -= 0.05  # mild lean

    return round(min(0.95, max(0.10, score)), 4)


def _score_macro_uncertainty(macro: MacroSensitivity, evidence: List[RetrievedEvidence]) -> float:
    """Score macro uncertainty level (0–1; higher = MORE uncertain)."""
    # Inverted from macro confidence.
    # When confidence == 0.0 (default/absent), use a neutral 0.50 rather than 1.0.
    # Without this fix every company gets base=0.95 macro drag, uniformly
    # suppressing all scores by ~0.45 even when macro data is simply absent.
    raw_confidence = macro.confidence
    if raw_confidence < 0.01:
        base = 0.50  # neutral: no macro data → neither bullish nor bearish signal
    else:
        base = 1.0 - raw_confidence

    # Boost uncertainty if evidence contains rate/inflation volatility language
    rate_terms = ("rate hike", "rate cut", "fed pivot", "inflation surprise",
                  "yield inversion", "recession risk", "stagflation", "tightening",
                  "rate uncertainty", "macro shock")
    ev_text = " ".join(
        f"{ev.title} {ev.summary}" for ev in evidence[:8]
    ).lower()
    if any(t in ev_text for t in rate_terms):
        base = min(0.95, base + 0.08)

    return round(min(0.95, max(0.05, base)), 4)


def _score_valuation_certainty(
    valuation: ValuationView,
    evidence: List[RetrievedEvidence],
) -> float:
    """Score how certain the valuation picture is (0–1)."""
    base = 0.35

    # Live valuation data
    has_fmp_val = any(
        any(kw in (f"{ev.source} {ev.title}").lower()
            for kw in ("ratios-ttm", "key-metrics-ttm", "pe ratio", "ev/ebitda", "valuation_ratios"))
        for ev in evidence
    )
    if has_fmp_val: base += 0.25

    # Analyst estimates
    has_analyst = any(
        any(kw in (f"{ev.source} {ev.title}").lower()
            for kw in ("analyst-estimates", "price-target", "consensus"))
        for ev in evidence
    )
    if has_analyst: base += 0.15

    # Valuation stance clarity
    stance = (getattr(valuation, "valuation_stance", "") or "").lower()
    if stance and stance not in ("", "cannot_determine"):
        base += 0.15
    elif stance == "cannot_determine":
        base -= 0.10

    # Valuation confidence
    base = base * (0.5 + 0.5 * valuation.confidence)

    return round(min(0.95, max(0.10, base)), 4)


def _score_estimate_dispersion(evidence: List[RetrievedEvidence]) -> float:
    """Score analyst estimate convergence/presence (0–1; higher = better)."""
    has_analyst = any(
        any(kw in (f"{ev.source} {ev.title}").lower()
            for kw in ("analyst-estimates", "price-target", "consensus", "analyst estimates"))
        for ev in evidence
    )
    if not has_analyst:
        return 0.38   # penalised for absence

    # Check for dispersion language in summaries
    ev_text = " ".join(
        f"{ev.summary}" for ev in evidence
        if any(kw in (f"{ev.source} {ev.title}").lower()
               for kw in ("analyst-estimates", "price-target", "consensus"))
    ).lower()
    dispersion_terms = ("widely dispersed", "wide range", "divergent", "disagreement",
                        "mixed views", "revised down", "estimate cuts", "lowered guidance")
    tight_terms = ("consensus", "in line", "reiterate", "price target raised",
                   "buy", "outperform", "strong buy")

    has_dispersion = any(t in ev_text for t in dispersion_terms)
    has_tight      = any(t in ev_text for t in tight_terms)

    if has_dispersion and not has_tight: return 0.45
    if has_tight and not has_dispersion: return 0.82
    return 0.65   # neutral / present but unclear


def _score_governance_risk(governance_warnings: List[str]) -> float:
    """Score governance risk from consistency warnings (0–1; higher = more risk)."""
    if not governance_warnings:
        return 0.0

    # Weight by warning type: GOVERNANCE > OVERLAP > depth warnings
    risk = 0.0
    for w in governance_warnings:
        if "[GOVERNANCE]" in w:     risk += 0.12
        elif "[OVERLAP]" in w:      risk += 0.05
        elif "[DEPTH]" in w:        risk += 0.03
        else:                       risk += 0.04

    return round(min(0.60, risk), 4)


# ── Asymmetry keyword pools ───────────────────────────────────────────────────
# Used by _score_expectation_asymmetry (execution dependency / optionality risk)

_EXEC_DEPENDENCY_TERMS = (
    "flawless execution", "execution risk", "must execute",
    "near-perfect", "no margin for error", "requires perfect",
    "execution dependent", "priced in success", "assumes successful",
    "critical execution", "execution sensitive", "tight execution",
    "zero margin", "perfect delivery",
)
_OPTIONALITY_TERMS = (
    "optionality", "blue-sky scenario", "if it works", "long-duration call",
    "disruption story", "platform story", "transformative potential",
    "moonshot", "lottery ticket", "option value", "early stage optionality",
    "future optionality", "call option on",
)

# Keyword pools used by _score_expectation_fragility
_PRICED_IN_TERMS = (
    "priced for perfection", "priced to perfection", "high expectations",
    "rich valuation", "premium multiple", "stretched multiple",
    "elevated valuation", "demanding valuation", "growth at any price",
    "multiple expansion", "re-rating required", "premium to peers",
    "trading at a premium", "expensive on", "expensive relative",
)
_ACCELERATION_TERMS = (
    "growth acceleration", "continued acceleration", "beat and raise",
    "sustained hypergrowth", "must continue", "requires continued",
    "continued momentum", "acceleration required", "needs to accelerate",
    "consensus expects acceleration",
)
_ASYMMETRIC_RISK_TERMS = (
    "downside asymmetry", "asymmetric downside", "binary outcome",
    "single-catalyst", "single catalyst risk", "execution risk elevated",
    "guidance risk", "miss would significantly", "disappointment risk",
    "priced in near-perfection", "limited margin for error",
)
_SPECULATIVE_TERMS = (
    "speculative", "narrative-driven", "hype cycle", "pre-revenue",
    "loss-making", "burning cash", "optionality play", "early-stage",
    "unproven model", "early stage",
)


def _compute_business_durability(
    quality:  "QualityAssessment",
    risk:     "RiskProfile",
    evidence: "List[RetrievedEvidence]",
    profile:  "Optional[CompanyKnowledgeProfile]" = None,
) -> float:
    """Compute a continuous business-durability score [0, 1] from four layered sources.

    This replaces both _QUALITY_DURABLE_TICKERS and _HIGH_EXPECTATION_TICKERS frozensets.
    The score generalizes to any company in the universe without ticker-specific overrides.

    Score architecture
    ------------------
    Baseline:  0.40 (neutral — unknown company with no profile)

    Layer 1:   CompanyKnowledgeProfile (highest signal quality, structured facts)
               +0.04–0.15  recurring_revenue_sources (count × quality)
               ±0.04–0.10  recession_behavior (positive vs negative keywords)
               –0.04–0.12  valuation_style narrative/optionality signals (reduces durability)
               –0.04–0.12  major_risks binary-outcome signals (reduces durability)
               +0.04–0.08  competitive_advantages depth

    Layer 2:   QualityAssessment agent text (moat, revenue_durability, operating_quality)
               +0.03 per durability keyword hit (capped at 0.12)
               –0.03 per fragility keyword hit (capped at 0.12)
               ±0.06 confidence band adjustment

    Layer 3:   RiskProfile agent text (binary risk signals)
               –0.05 per binary-risk keyword hit (capped at 0.15)

    Layer 4:   Evidence corpus (first 12 items)
               +0.03 per durability term hit (capped at 0.10)
               –0.03 per narrative/speculative term hit (capped at 0.10)

    Expected ranges
    ---------------
    COST / MSFT / JPM / ASML (with profile): 0.68–0.78 → HIGH → floor fires (≥0.65) ✓
    NVDA (with profile):                     0.52–0.58 → MODERATE → no floor ✓
    TSLA (with profile):                     0.30–0.40 → LOW → no floor ✓
    PLTR (with profile):                     0.42–0.52 → LOW-MODERATE → no floor ✓
    Unknown company (no profile, 0 evidence): 0.40      → NEUTRAL → no floor ✓
    """
    score = 0.40  # neutral baseline for unknown companies

    # ── Layer 1: CompanyKnowledgeProfile ─────────────────────────────────────
    if profile is not None:
        recurring  = " ".join(profile.recurring_revenue_sources or []).lower()
        recession  = (profile.recession_behavior or "").lower()
        valuation_s = (profile.valuation_style or "").lower()
        risks      = " ".join(profile.major_risks or []).lower()

        # Recurring revenue quality — high-retention signals boost durability more.
        # "management fee" covers AUM-based financial institutions (JPM, BLK, V).
        # "multi-year" covers equipment/industrial service contracts without needing the
        #   exact phrase "multi-year contract" (covers "multi-year maintenance agreement").
        high_quality_signals = (
            "renewal rate", "membership", "multi-year contract", "service contract",
            "subscription", "patient adherence", "maintenance", "management fee",
        )
        n_recurring = len(profile.recurring_revenue_sources or [])
        n_hq = sum(1 for t in high_quality_signals if t in recurring)
        if n_hq >= 2 or (n_hq >= 1 and n_recurring >= 3):
            score += 0.15
        elif n_recurring >= 2:
            score += 0.08
        elif n_recurring >= 1:
            score += 0.04

        # Recession resilience — positive vs negative keyword balance.
        # "mission-critical" covers enterprise software / infrastructure (MSFT, ORCL).
        # "secular" covers businesses driven by long-run structural demand vs cyclical CapEx.
        positive_rec = (
            "stable", "resilient", "non-discretionary", "defensive", "essential",
            "counter-cyclical", "recession-resistant", "maintained dividend",
            "sticky", "visibility", "non-cyclical", "mission-critical", "secular",
        )
        negative_rec = (
            "discretionary", "fall 30", "fall 40", "cyclical", "steep decline",
            "sensitive to consumer", "volatile",
        )
        pos_hits = sum(1 for t in positive_rec if t in recession)
        neg_hits = sum(1 for t in negative_rec if t in recession)
        score += max(-0.12, min(0.10, (pos_hits - neg_hits) * 0.04))

        # Narrative/optionality penalty — reduces durability
        narrative_val = (
            "optionality", "blue-sky", "terminal value", "platform",
            "option value", "speculative",
        )
        score -= min(0.12, sum(1 for t in narrative_val if t in valuation_s) * 0.04)

        # Binary-outcome risk penalty from major_risks
        binary_risk = (
            "binary", "regulatory approval", "clinical trial", "fda approval",
            "make-or-break", "unproven", "key-person risk",
        )
        score -= min(0.12, sum(1 for t in binary_risk if t in risks) * 0.04)

        # Competitive advantages depth — wider moat → more durable
        n_adv = len(profile.competitive_advantages or [])
        if n_adv >= 4:
            score += 0.08
        elif n_adv >= 2:
            score += 0.04

    # ── Layer 2: QualityAssessment agent text ─────────────────────────────────
    qa_text = " ".join([
        quality.moat or "",
        quality.revenue_durability or "",
        quality.operating_quality or "",
        quality.overall or "",
    ]).lower()

    durability_terms = (
        "recurring", "subscription", "membership", "renewal", "moat",
        "pricing power", "switching cost", "defensive", "consistent margin",
        "free cash flow", "resilient", "capital-light", "mission-critical",
    )
    fragility_terms = (
        "binary", "pre-revenue", "speculative", "narrative", "optionality",
        "execution risk", "unproven", "disruption", "early stage",
    )
    score += min(0.12, sum(1 for t in durability_terms if t in qa_text) * 0.03)
    score -= min(0.12, sum(1 for t in fragility_terms if t in qa_text) * 0.03)
    score += (quality.confidence - 0.50) * 0.06  # above-average quality confidence lifts score

    # ── Layer 3: RiskProfile binary/execution risk ────────────────────────────
    risk_text = " ".join([
        " ".join(risk.key_risks or []),
        risk.overall or "",
        risk.competitive_risk or "",
    ]).lower()
    binary_risk_terms = (
        "binary outcome", "binary risk", "pre-revenue", "clinical trial",
        "fda approval", "execution binary", "no moat", "narrative-driven",
    )
    score -= min(0.15, sum(1 for t in binary_risk_terms if t in risk_text) * 0.05)

    # ── Layer 4: Evidence corpus (first 12 items) ─────────────────────────────
    ev_text = " ".join(
        f"{ev.title} {ev.summary}" for ev in evidence[:12]
    ).lower()
    ev_durability = (
        "recurring revenue", "subscription", "membership fee", "renewal rate",
        "pricing power", "moat", "free cash flow", "defensive demand", "essential",
    )
    ev_narrative = (
        "optionality", "platform potential", "if successful", "speculative",
        "binary", "pre-revenue", "early stage", "moonshot", "narrative",
    )
    score += min(0.10, sum(1 for t in ev_durability if t in ev_text) * 0.03)
    score -= min(0.10, sum(1 for t in ev_narrative if t in ev_text) * 0.03)

    return round(min(0.95, max(0.05, score)), 4)


def _score_expectation_fragility(
    valuation:        "ValuationView",
    evidence:         "List[RetrievedEvidence]",
    company:          "CompanyContext",
    durability_score: float = 0.50,
) -> float:
    """Score how fragile the current setup is relative to embedded expectations (0–1).

    Higher values indicate MORE fragility — i.e., the stock is priced for near-perfect
    execution and any shortfall would reprice materially.  Applied *inverted* in the
    weighted composition (same polarity as macro_uncertainty and governance_risk).
    """
    base = 0.28  # baseline: moderate but not extreme expectation risk

    # ── Valuation stance signal ───────────────────────────────────────────────
    stance = (getattr(valuation, "valuation_stance", "") or "").lower()
    if stance == "overpriced":
        base += 0.28
    elif stance == "fairly_valued":
        base += 0.08
    elif stance in ("undervalued", "attractive"):
        base -= 0.10

    # ── Evidence text signals ─────────────────────────────────────────────────
    ev_text = " ".join(
        f"{ev.title} {ev.summary}" for ev in evidence[:12]
    ).lower()

    priced_in_hits  = sum(1 for t in _PRICED_IN_TERMS      if t in ev_text)
    accel_hits      = sum(1 for t in _ACCELERATION_TERMS    if t in ev_text)
    asymmetry_hits  = sum(1 for t in _ASYMMETRIC_RISK_TERMS if t in ev_text)
    speculative_hits = sum(1 for t in _SPECULATIVE_TERMS    if t in ev_text)

    base += min(0.20, priced_in_hits  * 0.07)
    base += min(0.15, accel_hits      * 0.06)
    base += min(0.10, asymmetry_hits  * 0.04)
    base += min(0.10, speculative_hits * 0.04)

    # ── Business durability offset ────────────────────────────────────────────
    # Computed durability_score [0, 1] replaces both _HIGH_EXPECTATION_TICKERS and
    # _QUALITY_DURABLE_TICKERS frozensets.  Generalizes to any company in the universe.
    #
    # The valuation_stance signal ("overpriced" → +0.28) already captures the
    # high-expectation dimension for any expensive stock.  No ticker-specific premium
    # is needed — the valuation agent provides this signal.
    #
    # The durability offset then correctly differentiates:
    #   "high expectations on elite durable business" (COST, MSFT, ASML)
    #     → large offset → net fragility reduced → Balanced/Demanding territory
    #   "fragile narrative-dependent speculation" (TSLA, PLTR, SNOW)
    #     → minimal offset → full fragility → Fragile/Speculative territory
    #
    # Continuous scaling examples at "overpriced" stance (base = 0.56 before offset):
    #   durability=0.72 (COST):  offset = 0.72×0.20 = 0.144 → net fragility ≈ 0.416
    #   durability=0.55 (NVDA):  offset = 0.55×0.20 = 0.110 → net fragility ≈ 0.450
    #   durability=0.35 (TSLA):  offset = 0.35×0.20 = 0.070 → net fragility ≈ 0.490
    #   durability=0.05 (PLTR):  offset = 0.05×0.20 = 0.010 → net fragility ≈ 0.550
    base = max(0.05, base - durability_score * _DURABILITY_MAX_FRAGILITY_OFFSET)

    return round(min(0.95, max(0.05, base)), 4)


def _score_expectation_asymmetry(
    valuation:        "ValuationView",
    evidence:         "List[RetrievedEvidence]",
    company:          "CompanyContext",
    dims:             "ConvictionDimensions",
    durability_score: float = 0.50,
) -> float:
    """Score how much the setup requires near-perfect execution (0–1; higher = worse).

    Distinct from expectation_fragility:
      fragility  = HOW PRICED-IN expectations are (overvaluation magnitude)
      asymmetry  = HOW DEPENDENT the outcome is on flawless execution (risk skew)

    High asymmetry means a small miss creates a large repricing — the downside is
    disproportionate to the upside remaining.  Applied as the second post-composition
    multiplier in _compose_score.
    """
    base = 0.18

    # Valuation stance
    stance = (getattr(valuation, "valuation_stance", "") or "").lower()
    if stance == "overpriced":
        base += 0.18
    elif stance == "fairly_valued":
        base += 0.04
    elif stance in ("undervalued", "attractive"):
        base -= 0.05

    # ── Business durability offset ────────────────────────────────────────────
    # Recurring-economics businesses have structurally lower execution binary-risk.
    # COST membership renewal is NOT a binary outcome.  MSFT O365 churn is NOT
    # fragile-execution-dependent.  TSLA FSD delivery and PLTR commercial scaling
    # ARE binary-ish outcomes — their durability_score naturally reflects this.
    #
    # Continuous scaling examples at "overpriced" stance (base = 0.36 before offset):
    #   durability=0.72 (COST): offset = 0.72×0.12 = 0.086 → net asymmetry ≈ 0.274
    #   durability=0.55 (NVDA): offset = 0.55×0.12 = 0.066 → net asymmetry ≈ 0.294
    #   durability=0.35 (TSLA): offset = 0.35×0.12 = 0.042 → net asymmetry ≈ 0.318
    base = max(0.05, base - durability_score * _DURABILITY_MAX_ASYMMETRY_OFFSET)

    # Evidence text signals
    ev_text = " ".join(
        f"{ev.title} {ev.summary}" for ev in evidence[:12]
    ).lower()

    priced_hits  = sum(1 for t in _PRICED_IN_TERMS      if t in ev_text)
    exec_hits    = sum(1 for t in _EXEC_DEPENDENCY_TERMS if t in ev_text)
    option_hits  = sum(1 for t in _OPTIONALITY_TERMS     if t in ev_text)
    asym_hits    = sum(1 for t in _ASYMMETRIC_RISK_TERMS  if t in ev_text)

    base += min(0.12, priced_hits * 0.05)
    base += min(0.10, exec_hits   * 0.04)
    base += min(0.08, option_hits * 0.03)
    base += min(0.06, asym_hits   * 0.03)

    # Cross-dimension amplifiers (correlation between high fragility and asymmetry)
    if dims.expectation_fragility > 0.75:
        base += 0.08
    elif dims.expectation_fragility > 0.60:
        base += 0.04

    # Agent divergence amplifies asymmetry (disagreement = uncertain range of outcomes)
    if dims.thesis_alignment < 0.40:
        base += 0.10
    elif dims.thesis_alignment < 0.55:
        base += 0.04

    return round(min(0.90, max(0.05, base)), 4)


# ── Post-composition multiplier functions ─────────────────────────────────────

def _fragility_multiplier(fragility: float) -> float:
    """Translate expectation_fragility into a score multiplier (0.78–1.0).

    Thresholded: no penalty at or below 0.35.  Above the threshold, penalty ramps
    linearly at rate _FRAGILITY_SCALE per unit of excess, capped at _FRAGILITY_MAX.

    Phase 5c examples (threshold=0.35, scale=0.45, max=0.22):
      fragility = 0.30 → 1.000 (no penalty — reasonable expectations)
      fragility = 0.55 → 0.910 (9% penalty — somewhat stretched)
      fragility = 0.70 → 0.843 (15.7% penalty — priced for near-perfection)
      fragility = 0.80 → 0.798 (20.2% penalty — demanding setup)
      fragility = 0.95 → 0.780 (22% penalty — capped; extreme setup)
    """
    if fragility <= _FRAGILITY_THRESHOLD:
        return 1.0
    penalty = min(_FRAGILITY_MAX, (fragility - _FRAGILITY_THRESHOLD) * _FRAGILITY_SCALE)
    return round(1.0 - penalty, 4)


def _asymmetry_multiplier(asymmetry: float) -> float:
    """Translate expectation_asymmetry into a score multiplier (0.80–1.0).

    Thresholded: no penalty at or below 0.30.  Compounds with the fragility multiplier —
    a high-fragility + high-asymmetry setup receives BOTH penalties multiplicatively.

    Phase 5c examples (threshold=0.30, scale=0.35, max=0.20):
      asymmetry = 0.25 → 1.000 (no penalty — balanced risk/reward)
      asymmetry = 0.50 → 0.930 (7% penalty — moderate execution dependency)
      asymmetry = 0.70 → 0.860 (14% penalty — narrow margin for error)
      asymmetry = 0.85 → 0.803 (19.7% penalty — binary-outcome risk)
      asymmetry = 0.90 → 0.800 (20% penalty — capped; execution-binary setup)
    """
    if asymmetry <= _ASYMMETRY_THRESHOLD:
        return 1.0
    penalty = min(_ASYMMETRY_MAX, (asymmetry - _ASYMMETRY_THRESHOLD) * _ASYMMETRY_SCALE)
    return round(1.0 - penalty, 4)


# ── Matrix-based setup label constants ───────────────────────────────────────
#
# Phase 1+2 architectural refactor: setup_label is now derived from a
# 2D matrix of (durability_score, expectation_risk) — completely independent
# of the composite confidence score.
#
# This separation is critical:
#   confidence_score → reflects evidence depth and uncertainty (can be low for COST)
#   setup_label      → reflects BUSINESS SETUP QUALITY (NEVER "speculative" for a durable compounder)
#
# Matrix tiers:
#   Durable compounder (durability ≥ 0.60): Balanced–Demanding range only
#   Quality cyclical (0.40 ≤ durability < 0.60): Fragile–Demanding range
#   Narrative/speculative (durability < 0.40): Speculative–Fragile range
_DURABILITY_MATRIX_HIGH = 0.60   # durable compounder threshold
_DURABILITY_MATRIX_MID  = 0.40   # quality cyclical threshold

# ── Conviction system version constants ──────────────────────────────────────
# These are imported by startup.py and /debug/version to prove the live process
# is running the matrix architecture code, not a stale pre-matrix version.
#
# CONVICTION_SCHEMA_VERSION: bump whenever the label vocabulary or matrix layout
#   changes — forces frontend DEV overlay to show the new version.
# ARCHETYPE_MATRIX_ENABLED: always True in this module — startup.py asserts it.
#   If this import fails or returns False, the server refuses to start.
CONVICTION_SCHEMA_VERSION = "6-matrix"
ARCHETYPE_MATRIX_ENABLED  = True

# ── [DEPLOYMENT PROOF] Module-level import-time marker ───────────────────────
# This print fires the MOMENT Python imports conviction_modeler — at server boot.
# Search Render logs for "MATRIX_CONVICTION_MODEL_ACTIVE" to confirm the live
# process loaded THIS file (not a stale pre-matrix version).
# If this line does NOT appear in Render logs after deploy, the file was not
# deployed — check git push status and Render build logs.
print(
    f"[conviction_modeler] MATRIX_CONVICTION_MODEL_ACTIVE "
    f"schema={CONVICTION_SCHEMA_VERSION} "
    f"matrix_enabled={ARCHETYPE_MATRIX_ENABLED} "
    f"durability_high={_DURABILITY_MATRIX_HIGH} "
    f"durability_mid={_DURABILITY_MATRIX_MID}"
)


def _compute_expectation_risk(dims: "ConvictionDimensions") -> float:
    """Compute a single expectation-risk score [0, 1] from conviction dimensions.

    Combines expectation_fragility (valuation/execution premium) and
    expectation_asymmetry (binary-outcome risk) into a single risk scalar.

    Higher = more expectation risk (closer to Speculative).
    Lower  = lower expectation risk (closer to High-Alignment).
    """
    return round(
        0.70 * dims.expectation_fragility + 0.30 * dims.expectation_asymmetry,
        4,
    )


def _durability_matrix_label(durability_score: float, expectation_risk: float) -> str:
    """Derive setup_label from a 2D durability × expectation-risk matrix.

    This function is the SOLE source of setup_label in compute_conviction().
    It completely replaces both _confidence_band_label() and the label-floor
    block that previously patched score-derived labels after the fact.

    Design guarantees:
      - Durable compounders (durability ≥ 0.60) NEVER receive "speculative setup".
      - Narrative/optionality businesses (durability < 0.40) NEVER receive
        "high-alignment thesis" or "actionable thesis".
      - Only expectation_risk drives where within each tier the label lands.
      - The confidence_score (evidence depth) does NOT affect the label.

    Matrix
    ──────
    Durable compounder (durability ≥ 0.60):
      exp_risk < 0.35 → "high-alignment thesis"    (strong conviction, low premium risk)
      exp_risk < 0.50 → "actionable thesis"         (good setup, manageable premium)
      exp_risk < 0.65 → "monitoring required"       (durable but demanding valuation)
      exp_risk ≥ 0.65 → "expectation-sensitive"     (stretched valuation on quality name)

    Quality cyclical (0.40 ≤ durability < 0.60):
      exp_risk < 0.35 → "actionable thesis"         (good quality at reasonable valuation)
      exp_risk < 0.55 → "fragile setup"             (quality + some expectation risk)
      exp_risk < 0.75 → "asymmetric setup"          (high expectation risk on cyclical)
      exp_risk ≥ 0.75 → "speculative setup"         (extreme expectation risk, rare)

    Narrative/speculative (durability < 0.40):
      exp_risk < 0.40 → "fragile setup"             (narrative but not fully speculative)
      exp_risk < 0.60 → "speculative setup"         (narrative + material expectation risk)
      exp_risk ≥ 0.60 → "insufficient conviction"   (narrative + extreme premium → no edge)
    """
    if durability_score >= _DURABILITY_MATRIX_HIGH:
        # Durable compounder tier — Balanced/Demanding range only.
        # "speculative setup" is STRUCTURALLY IMPOSSIBLE from this branch.
        if expectation_risk < 0.35:
            label = "high-alignment thesis"
        elif expectation_risk < 0.50:
            label = "actionable thesis"
        elif expectation_risk < 0.65:
            label = "monitoring required"
        else:
            label = "expectation-sensitive"

    elif durability_score >= _DURABILITY_MATRIX_MID:
        # Quality cyclical tier — Fragile/Demanding range
        if expectation_risk < 0.35:
            label = "actionable thesis"
        elif expectation_risk < 0.55:
            label = "fragile setup"
        elif expectation_risk < 0.75:
            label = "asymmetric setup"
        else:
            label = "speculative setup"

    else:
        # Narrative/speculative tier — Speculative range
        if expectation_risk < 0.40:
            label = "fragile setup"
        elif expectation_risk < 0.60:
            label = "speculative setup"
        else:
            label = "insufficient conviction"

    # ── Phase 6: Live classification assertion ────────────────────────────────
    # [INVALID_ARCHETYPE_CLASSIFICATION] fires when a durable compounder somehow
    # receives a speculative label — this should be structurally IMPOSSIBLE from
    # the durable tier branch, but we assert it explicitly as a production guard.
    # If this fires, it means _DURABILITY_MATRIX_HIGH was incorrectly overridden
    # or there's a code path bug — NOT a normal calibration signal.
    if (durability_score >= _DURABILITY_MATRIX_HIGH
            and label in ("speculative setup", "insufficient conviction")):
        _logger.error(
            "[INVALID_ARCHETYPE_CLASSIFICATION] durability=%.3f >= threshold=%.2f "
            "but label=%r — this is a matrix code bug. "
            "expectation_risk=%.3f. Overriding to 'expectation-sensitive'.",
            durability_score, _DURABILITY_MATRIX_HIGH, label, expectation_risk,
        )
        label = "expectation-sensitive"

    return label


def _confidence_band_label(
    final_score: float,
    dims:        "ConvictionDimensions",
) -> str:
    """Return a semantic setup label for the conviction band.

    The label is context-sensitive: the same score can produce different labels
    depending on the dominant driver — fragility, asymmetry, or thesis alignment.

    Pre-launch recalibration target distribution:
        Durable     — ≥0.72  → high-alignment thesis / actionable thesis
                      (MSFT, COST, V, JPM — strong evidence, low expectations)
        Balanced    — 0.58–0.72 → actionable thesis / monitoring required
                      (GOOGL, META, ASML — solid, some expectations embedded)
        Demanding   — 0.42–0.58 + high fragility → expectation-sensitive / asymmetric
                      (NVDA, AAPL, AMZN — great businesses, demanding setup)
        Fragile     — 0.25–0.42 or moderate fragility → fragile setup
                      (TSLA, SNOW — real business, little room for misses)
        Speculative — <0.30 or low thesis alignment → speculative setup
                      (PLTR, C3.ai — narrative-dependent, conviction-thin)

    Escape valves (pre-launch):
        - High-quality names compressed by fragility multiplier but with strong
          thesis_alignment escape into "expectation-sensitive" rather than "speculative".
        - Moderate-quality names with real revenues escape "speculative" into "fragile setup".
    """
    frag = dims.expectation_fragility
    asym = dims.expectation_asymmetry
    ta   = dims.thesis_alignment

    # ── Tier 1: Durable (≥0.72) ──────────────────────────────────────────────
    if final_score >= 0.72:
        if frag < 0.40 and asym < 0.40:
            return "high-alignment thesis"
        return "actionable thesis"

    # ── Tier 2: Balanced (0.58–0.72) ─────────────────────────────────────────
    elif final_score >= 0.58:
        if frag > 0.62 or asym > 0.55:
            return "monitoring required"
        if ta < 0.48:
            return "mixed evidence"
        return "actionable thesis"

    # ── Tier 3: Demanding (0.42–0.58) ────────────────────────────────────────
    elif final_score >= 0.42:
        if asym > 0.65:
            return "asymmetric setup"
        if frag > 0.60:
            return "expectation-sensitive"
        if ta < 0.45:
            return "fragile setup"
        return "mixed evidence"

    # ── Tier 4: Fragile / Speculative (0.25–0.42) ────────────────────────────
    elif final_score >= 0.25:
        # High-quality demanding names that compressed through fragility×asymmetry
        # (e.g. NVDA with ta ≥ 0.62 and high fragility) → expectation-sensitive, not speculative
        if frag > 0.60 and ta >= 0.62:
            return "expectation-sensitive"
        # Real businesses with moderate thesis quality (e.g. TSLA) → fragile, not speculative
        if ta >= 0.50 or frag >= 0.50:
            return "fragile setup"
        return "speculative setup"

    # ── Tier 5: Minimal (<0.25) ───────────────────────────────────────────────
    else:
        return "insufficient conviction"


# ── Directional stance synthesis ──────────────────────────────────────────────

def _compute_directional_stance(
    final_score:        float,
    dims:               "ConvictionDimensions",
    setup_label:        str,
    company:            "CompanyContext",
    expectation_regime: str   = "fair",   # NEW — regime from _classify_expectation_regime
    durability_score:   float = 0.50,     # NEW — business durability [0, 1]
) -> Tuple[str, str]:
    """Derive a directional stance and institutional reasoning from the conviction output.

    Outputs
    -------
    stance    : one of the expanded stance vocabulary below
    reasoning : 1-2 sentence institutional explanation — PM-grade, not generic.

    Stance vocabulary (ordered from most to least constructive):
      "Aggressive Buy"  — exceptional setup: very high conviction, low fragility
      "Buy"             — solid setup: clear upside asymmetry, attractive/cheap regime
      "Accumulate"      — durable compounder at fair/attractive valuation; add on dips
      "Hold"            — thesis intact but expectation bar elevated; no urgent add
      "Tactical"        — short-term catalyst window; limited structural conviction
      "Avoid"           — weak evidence or fragile setup; risk/reward unfavorable
      "Sell"            — structural conviction break; deteriorating evidence base

    Design rules (Phase 3 calibration)
    ------------------------------------
    - BUY requires clear upside asymmetry (low frag + high ta) AND a regime that
      is not stretched/euphoric/bubble.  Quality alone is insufficient.
    - ACCUMULATE captures durable compounders at fair/attractive valuation where
      expectations are partially priced-in but the structural thesis is intact.
    - Regime-gating: stretched/euphoric/bubble regimes block Buy (broad) from firing.
    - Early Avoid: euphoric/bubble + low conviction → Avoid before other rules.
    - Reasoning must reference the expectation context, not just score.
    - Language must be institutional: no "BUY because fundamentals are strong."
    """
    frag   = dims.expectation_fragility
    asym   = dims.expectation_asymmetry
    ta     = dims.thesis_alignment
    vc     = dims.valuation_certainty
    ticker = (company.ticker or "the company").upper()

    # ── Early Avoid: euphoric/bubble regime + insufficient conviction ─────────
    # When the market is pricing perfection, only very high conviction survives.
    if expectation_regime in ("euphoric", "bubble") and final_score < 0.60:
        return (
            "Avoid",
            f"{ticker} is priced for outcomes that current evidence cannot support. "
            f"The expectation regime ({expectation_regime}) leaves minimal margin for "
            f"execution variance — the risk/reward is unfavorable at this entry.",
        )

    # ── Aggressive Buy ────────────────────────────────────────────────────────
    # Exceptional setup: very high conviction, low fragility, very high alignment
    # Market undervalues durable compounding; setup does not require perfection.
    if final_score >= 0.78 and frag < 0.32 and ta > 0.68:
        return (
            "Aggressive Buy",
            f"Current expectations on {ticker} leave material room for upside — "
            f"the setup does not require above-consensus delivery to work. "
            f"Low fragility and strong cross-signal alignment support adding size.",
        )

    # ── Accumulate (durable compounder — Phase 4A: moved above Buy) ─────────
    # Phase 4A calibration: this rule fires BEFORE Buy (explicit) and Buy (broad).
    # Durable compounders (durability ≥ 0.60) at fair/attractive/stretched valuation
    # should Accumulate rather than Buy — quality is recognised but the entry does
    # not offer the asymmetry required for a full Buy call.
    #
    # Threshold change: 0.65 → 0.60 to capture COST/JPM-class businesses that
    # lack a CompanyKnowledgeProfile and compute durability ~0.60-0.64 from
    # QA text + evidence layers alone.
    #
    # Regime exclusions (Phase 4A):
    #   "cheap"          → genuine deep-value entry; Buy is appropriate even for
    #                       durable compounders at genuinely cheap valuations.
    #   "euphoric"/"bubble" → blocked by the early Avoid gate above.
    #
    # Examples: COST (0.713, fair, dur~0.63) → Accumulate. JPM (0.688, fair, dur~0.62)
    # → Accumulate.  META (0.63, attractive, dur=0.72) → Accumulate.
    if (durability_score >= 0.60 and final_score >= 0.58 and frag < 0.40
            and expectation_regime not in ("cheap", "euphoric", "bubble")):
        return (
            "Accumulate",
            f"{ticker} is a durable compounder with a high-quality business, but the "
            f"current entry does not offer the clear upside asymmetry required for a "
            f"full Buy. The thesis is intact; add on pullbacks rather than at spot.",
        )

    # ── Buy (explicit) ────────────────────────────────────────────────────────
    # High-conviction, manageable expectation risk, regime supports entry.
    # Now fires for: durability < 0.60, OR regime == "cheap" with high conviction.
    # Regime gate: stretched/euphoric/bubble block this rule.
    if (final_score >= 0.68 and frag < 0.40 and ta > 0.60
            and expectation_regime not in ("stretched", "euphoric", "bubble")):
        return (
            "Buy",
            f"The setup on {ticker} offers clear upside asymmetry — evidence quality is "
            f"high, the thesis is aligned across signals, and the current multiple does "
            f"not require above-consensus execution to defend.",
        )

    # ── Accumulate (frag band) ────────────────────────────────────────────────
    # Quality business where expectations are partially priced-in.
    # The key distinction from Buy: expectations are priced-in (frag 0.40-0.62),
    # so the business is high-quality but the entry point matters.
    if final_score >= 0.58 and 0.40 <= frag < 0.62:
        return (
            "Accumulate",
            f"{ticker} is a quality business where current pricing already reflects "
            f"operational strength — the setup favours adding on dips rather than "
            f"chasing at current levels. The thesis holds; the entry matters.",
        )

    # ── Buy (broad) — regime-gated ────────────────────────────────────────────
    # Solid conviction with manageable expectation risk — blocked in
    # stretched/euphoric/bubble regimes where quality is already priced.
    if (final_score >= 0.62 and frag < 0.58
            and expectation_regime not in ("stretched", "euphoric", "bubble")):
        return (
            "Buy",
            f"Business quality and setup support a constructive view on {ticker}. "
            f"Risk/reward remains favorable at current expectations without requiring "
            f"above-consensus execution.",
        )

    # ── Tactical ─────────────────────────────────────────────────────────────
    # Moderate score + high fragility but identifiable catalyst — not a full add.
    # The asymmetry exists but the structural case is thin.  Time-bounded.
    if final_score >= 0.52 and frag >= 0.55 and asym < 0.50:
        return (
            "Tactical",
            f"The {ticker} setup has near-term asymmetry around a specific catalyst but "
            f"lacks the structural conviction for a full position. Risk/reward is "
            f"acceptable tactically; the setup is not a conviction add.",
        )

    # ── Tactical (euphoric/bubble, moderate conviction) ───────────────────────
    if expectation_regime in ("euphoric", "bubble") and final_score >= 0.60 and asym < 0.50:
        return (
            "Tactical",
            f"{ticker} has identifiable near-term momentum, but the expectation regime "
            f"({expectation_regime}) means the structural risk/reward is unfavorable "
            f"for a full position. Tactical-only at current pricing.",
        )

    # ── Hold — demanding setup ────────────────────────────────────────────────
    # Elevated expectations leave limited margin of safety; pause before adding
    if final_score >= 0.42 and frag >= 0.58:
        return (
            "Hold",
            f"The business is strong, but the current setup leaves limited room for "
            f"execution misses on {ticker}. The thesis is intact; the expectation bar "
            f"is elevated — patience is required before adding.",
        )

    # ── Hold — moderate conviction (dead-zone closure) ───────────────────────
    # Closes the gap at final_score 0.42–0.51 with fragility < 0.58.
    #
    # Before this rule, companies with:
    #   0.42 ≤ final_score < 0.52   AND   fragility < 0.58
    # fell through both Hold conditions and received "Avoid" — an incorrect
    # classification for high-quality businesses (MSFT, NVDA, AMZN) where the
    # conviction modeler has already applied fragility and asymmetry multiplier
    # penalties.  A final_score that survives to 0.42–0.51 after those penalties
    # represents "thesis intact, expectation bar moderate-to-elevated" — Hold, not
    # Avoid.  "Avoid" implies risk/reward is unfavorable; at 42–51% confidence on
    # a quality business with moderate fragility, that is too harsh.
    #
    # Calibration note: the confidence score is NOT changed here.  The conviction
    # modeler already discounted fragility and asymmetry multiplicatively before
    # arriving at final_score.  Classifying the resulting score as Avoid would be
    # a second penalty on top of penalties already applied.
    if final_score >= 0.42:
        return (
            "Hold",
            f"The {ticker} thesis is directionally intact but conviction sits at a "
            f"moderate level — the evidence base and expectation setup do not yet "
            f"support adding. Monitor for a catalyst or valuation reset before acting.",
        )

    # ── Avoid ─────────────────────────────────────────────────────────────────
    # Weak evidence + fragile setup — risk/reward unfavorable.
    if final_score >= 0.30:
        if frag > 0.65:
            return (
                "Avoid",
                f"The valuation on {ticker} now depends on assumptions that are difficult "
                f"to defend with present evidence. The setup requires above-consensus "
                f"execution with limited downside protection.",
            )
        return (
            "Avoid",
            f"Evidence on {ticker} does not support a constructive position at current "
            f"prices. Too many open variables remain unresolved to establish a "
            f"high-conviction directional view.",
        )

    # ── Sell ──────────────────────────────────────────────────────────────────
    # Phase 4A: Sell requires POSITIVE evidence of structural deterioration —
    # not merely low confidence.  Low confidence maps to Avoid (insufficient
    # conviction to form any directional view).  Sell requires:
    #   (a) elevated expectations still embedded  (frag > 0.65)   AND
    #   (b) cross-agent consensus decisively negative  (ta < 0.35)
    #
    # Rationale: institutionally, "Sell" implies conviction that the stock
    # declines.  A company with score < 0.30 but neutral-to-mixed agent
    # alignment (ta 0.35–0.60) lacks the negative conviction needed for Sell
    # — it is simply under-researched or macro-uncertain.  Conflating
    # insufficient evidence with a Sell call is a category error.
    #
    # XOM / SBUX example: score < 0.30 but ta ~0.50 → Avoid, not Sell.
    # Genuine Sell example: score < 0.30, frag = 0.85, ta = 0.20 → Sell.
    if frag > 0.65 and ta < 0.35:
        return (
            "Sell",
            f"The evidence base on {ticker} signals structural deterioration: agent "
            f"consensus is decisively negative and elevated expectations remain embedded "
            f"in the current multiple — the risk/reward is asymmetrically to the downside.",
        )

    # ── Avoid (sub-0.30 catch-all) ────────────────────────────────────────────
    # Any score below 0.30 that does not meet the Sell conditions above indicates
    # insufficient conviction to form a directional view — not a conviction-short.
    return (
        "Avoid",
        f"The evidence base on {ticker} is insufficient to support a directional "
        f"position — conviction is too low to establish a high-confidence view. "
        f"Revisit when evidence quality and agent alignment improve.",
    )


# ── Weighted composition ──────────────────────────────────────────────────────

def _linear_base_score(dims: ConvictionDimensions) -> float:
    """Seven-dimension weighted linear combination → base score (0–1).

    Does NOT include expectation_fragility or expectation_asymmetry — those are
    post-composition multipliers applied in _compose_score().
    """
    raw = (
        dims.evidence_quality             * _WEIGHTS["evidence_quality"]
        + dims.evidence_freshness         * _WEIGHTS["evidence_freshness"]
        + dims.thesis_alignment           * _WEIGHTS["thesis_alignment"]
        + (1.0 - dims.macro_uncertainty)  * _WEIGHTS["macro_uncertainty"]
        + dims.valuation_certainty        * _WEIGHTS["valuation_certainty"]
        + dims.estimate_dispersion        * _WEIGHTS["estimate_dispersion"]
        + (1.0 - dims.governance_risk)    * _WEIGHTS["governance_risk"]
    )
    return round(min(_MAX_SCORE, max(_MIN_SCORE, raw)), 4)


def _compose_score(dims: ConvictionDimensions) -> float:
    """Full conviction composition: linear base × fragility mult × asymmetry mult.

    Pipeline:
        _linear_base_score(dims)
            × _fragility_multiplier(dims.expectation_fragility)
            × _asymmetry_multiplier(dims.expectation_asymmetry)
        → pre-compression score (0–1)

    Contradiction compression (if triggered) is applied separately in compute_conviction.
    """
    base      = _linear_base_score(dims)
    frag_mult = _fragility_multiplier(dims.expectation_fragility)
    asym_mult = _asymmetry_multiplier(dims.expectation_asymmetry)
    return round(min(_MAX_SCORE, max(_MIN_SCORE, base * frag_mult * asym_mult)), 4)


# ── Contradiction-aware compression ──────────────────────────────────────────

def _check_contradiction_compression(
    dims:     "ConvictionDimensions",
    valuation: "ValuationView",
    ranked:    Optional[Any],
    evidence:  "List[RetrievedEvidence]",
) -> Tuple[bool, List[str], float]:
    """Detect conflicting signal combinations and return the compression factor.

    Returns (should_compress, list_of_reasons, compression_factor).
    Three tiers of severity are evaluated independently; the worst applicable tier
    sets the base factor, which is then compounded by 0.94 for each additional trigger.

    Trigger severity
    ────────────────
    MILD (×0.88):
      1. Bullish signals vs overpriced valuation under macro uncertainty
      2. Stale evidence compounding governance risk
      3. Agent disagreement + analyst estimate dispersion
      4. No valuation anchor and no analyst consensus
      5. Speculative catalyst language in evidence

    SIGNIFICANT (×0.80):
      6. High expectation fragility with constructive thesis alignment
         (great company priced for perfection)
      7. Overpriced valuation + evidence requires continued acceleration
      8. Extreme macro uncertainty (>0.80) with elevated valuation

    SEVERE (×0.70):
      Escalated automatically when ≥3 total triggers fire or ≥2 significant
      triggers are present simultaneously.
    """
    mild_reasons:        List[str] = []
    significant_reasons: List[str] = []

    # ── Signal lean helper ────────────────────────────────────────────────────
    bullish_lean = False
    if ranked is not None and getattr(ranked, "all_ranked", None):
        sigs      = ranked.all_ranked
        bullish_n = sum(1 for s in sigs if s.direction == "bullish")
        bearish_n = sum(1 for s in sigs if s.direction == "bearish")
        bullish_lean = bullish_n > bearish_n

    stance   = (getattr(valuation, "valuation_stance", "") or "").lower()
    ev_text  = " ".join(
        f"{ev.title} {ev.summary}" for ev in evidence[:10]
    ).lower()

    # ── MILD triggers ─────────────────────────────────────────────────────────

    # T1: bullish signals vs overpriced valuation under macro uncertainty
    if bullish_lean and stance == "overpriced" and dims.macro_uncertainty > 0.55:
        mild_reasons.append(
            "bullish signal lean conflicts with overpriced valuation under active macro uncertainty"
        )

    # T2: stale evidence compounding governance risk
    if dims.evidence_freshness < 0.40 and dims.governance_risk > 0.15:
        mild_reasons.append(
            "stale evidence compounds governance risk — thesis may rest on outdated inputs"
        )

    # T3: agent disagreement + analyst estimate dispersion
    if dims.thesis_alignment < 0.45 and dims.estimate_dispersion < 0.50:
        mild_reasons.append(
            "cross-agent disagreement and analyst estimate dispersion jointly suppress conviction"
        )

    # T4: no valuation anchor and no analyst consensus
    if dims.valuation_certainty < 0.35 and dims.estimate_dispersion < 0.42:
        mild_reasons.append(
            "no live multiple data and no analyst consensus — valuation anchor absent"
        )

    # T5: speculative/narrative catalyst language dominating evidence
    spec_hit_count = sum(1 for t in _SPECULATIVE_TERMS if t in ev_text)
    if spec_hit_count >= 2:
        mild_reasons.append(
            f"speculative or narrative-driven language detected in evidence "
            f"({spec_hit_count} signals) — reduces structural durability of the thesis"
        )

    # ── SIGNIFICANT triggers ──────────────────────────────────────────────────

    # T6: high expectation fragility + constructive thesis = priced-for-perfection trap
    # Phase 5e: lowered threshold 0.70 → 0.62 so TSLA/PLTR/NVDA with only HE premium trigger
    if dims.expectation_fragility > 0.62 and dims.thesis_alignment > 0.60:
        significant_reasons.append(
            "thesis alignment is constructive but expectations are elevated — "
            "the stock setup is more demanding than the business quality alone implies"
        )

    # T7: overpriced valuation + evidence explicitly requires continued acceleration
    accel_hit_count = sum(1 for t in _ACCELERATION_TERMS if t in ev_text)
    if stance == "overpriced" and accel_hit_count >= 2:
        significant_reasons.append(
            f"overpriced valuation stance combined with {accel_hit_count} acceleration-dependency "
            "signals — current pricing requires the business to outrun its multiple"
        )

    # T8: extreme macro uncertainty + elevated expectations (double-headwind)
    if dims.macro_uncertainty > 0.80 and dims.expectation_fragility > 0.55:
        significant_reasons.append(
            "extreme macro uncertainty overlaps with elevated expectations — "
            "rate/growth path risk creates asymmetric downside when already priced optimistically"
        )

    # ── Severity escalation ───────────────────────────────────────────────────
    all_reasons   = significant_reasons + mild_reasons
    total_triggers = len(all_reasons)

    if not all_reasons:
        return False, [], 1.0

    if len(significant_reasons) >= 2 or total_triggers >= 4:
        # Severe: multiple compounding signals leave little margin
        factor = _COMPRESSION_SEVERE
    elif significant_reasons or total_triggers >= 2:
        # Significant: one high-severity or two mild triggers
        factor = _COMPRESSION_SIGNIFICANT
    else:
        # Mild: single low-severity trigger
        factor = _COMPRESSION_MILD

    return True, all_reasons, factor


# ── Company-specific uncertainty language ─────────────────────────────────────

def _get_uncertainty_drivers(company: CompanyContext) -> List[str]:
    """Return company-specific uncertainty variables, falling back to sector."""
    ticker = (company.ticker or "").upper()
    if ticker in _TICKER_UNCERTAINTY_DRIVERS:
        return _TICKER_UNCERTAINTY_DRIVERS[ticker]
    sector = company.sector or ""
    if sector in _SECTOR_UNCERTAINTY_DRIVERS:
        return _SECTOR_UNCERTAINTY_DRIVERS[sector]
    return _DEFAULT_UNCERTAINTY_DRIVERS


def _dominant_gap(dims: ConvictionDimensions) -> str:
    """Return the name of the dimension with the worst normalised conviction score.

    Inverted dimensions are expressed as their conviction-friendly complement so that
    the minimum corresponds to the greatest drag on the final score.
    Includes both post-composition multiplier dimensions for reasoning purposes.
    """
    effective = {
        "evidence_quality":    dims.evidence_quality,
        "evidence_freshness":  dims.evidence_freshness,
        "thesis_alignment":    dims.thesis_alignment,
        "macro_certainty":     1.0 - dims.macro_uncertainty,
        "valuation_certainty": dims.valuation_certainty,
        "estimate_dispersion": dims.estimate_dispersion,
        "governance_safety":   1.0 - dims.governance_risk,
        "expectation_safety":  1.0 - dims.expectation_fragility,
        "asymmetry_safety":    1.0 - dims.expectation_asymmetry,
    }
    return min(effective, key=effective.get)


# ── Retrieval tagging + weighting ────────────────────────────────────────────

# Keywords used by _classify_evidence_tags to assign retrieval intelligence tags
_TAG_RECENT_CHANGE_KEYWORDS = (
    "raised guidance", "lowered guidance", "cut guidance", "revised higher", "revised lower",
    "estimate revision", "beat expectations", "missed estimates", "tone shift",
    "management tone", "cautious language", "more optimistic", "changed language",
    "material change", "new development", "updated forecast",
)
_TAG_ESTIMATE_REVISION_KEYWORDS = (
    "estimate revision", "raised estimate", "lowered estimate", "cut estimate",
    "revised higher", "revised lower", "consensus revision", "estimate cut",
    "estimate raise", "upward revision", "downward revision", "eps revision",
    "price target raised", "price target cut", "pt raised", "pt cut",
)
_TAG_TONE_SHIFT_KEYWORDS = (
    "tone shift", "management tone", "cautious language", "more optimistic",
    "conservative guidance", "bullish commentary", "bearish commentary",
    "changed language", "messaging shift", "less confident", "more confident",
    "walked back", "tempered expectations",
)
_TAG_VALUATION_REGIME_KEYWORDS = (
    "multiple expansion", "multiple compression", "re-rating", "de-rating",
    "premium valuation", "discount valuation", "historically expensive",
    "historically cheap", "stretched multiple", "trough multiple", "peak multiple",
    "pe expansion", "ev/ebitda expansion",
)
_TAG_EXPECTATION_CHANGE_KEYWORDS = (
    "consensus expectations", "expectation change", "higher expectations", "lower expectations",
    "priced in", "already priced", "expectations reset", "reset lower", "reset higher",
    "bar raised", "bar lowered", "setup improved", "setup deteriorated",
)
_TAG_SENTIMENT_REGIME_KEYWORDS = (
    "upgrade", "downgrade", "initiat", "sentiment shift", "analyst consensus",
    "bullish sentiment", "bearish sentiment", "short interest", "short squeeze",
    "flows", "put/call ratio", "options positioning",
)
_TAG_POSITIONING_KEYWORDS = (
    "institutional ownership", "13f", "hedge fund", "position change",
    "net long", "net short", "crowded trade", "positioning data",
    "ownership increase", "ownership decrease",
)
_TAG_MACRO_TRANSITION_KEYWORDS = (
    "rate cut", "rate hike", "fed pivot", "policy change", "monetary transition",
    "macro regime", "rate regime", "cycle change", "soft landing confirmed",
    "recession risk", "growth deceleration", "regime transition",
)
_TAG_EXECUTION_SIGNAL_KEYWORDS = (
    "beat", "miss", "above consensus", "below consensus", "in line with",
    "exceeded estimates", "fell short", "guidance raised", "guidance cut",
    "outperformed", "underperformed", "delivered vs",
)
_TAG_BALANCE_SHEET_EVENT_KEYWORDS = (
    "buyback", "share repurchase", "dividend increase", "dividend cut",
    "debt reduction", "refinanced", "capital return", "net cash increased",
    "leverage reduced", "balance sheet strength", "fcf inflection",
)

# Age thresholds for recent_change tag (days)
_RECENT_CHANGE_AGE_DAYS = 45


def _classify_evidence_tags(
    evidence: "List[RetrievedEvidence]",
) -> "List[RetrievedEvidence]":
    """Assign retrieval intelligence tags and weights to each evidence item in-place.

    Returns the same list with retrieval_tags and retrieval_weight populated.
    Does NOT modify the original objects — returns new objects with tags set.

    Tagging logic:
    - Parse each item's title + summary against keyword pools
    - Assign tags matching the content type
    - Compute retrieval_weight:
        base = 1.0
        recent_change tag    → +0.60
        estimate_revision    → +0.50
        execution_signal     → +0.40
        tone_shift           → +0.35
        expectation_change   → +0.30
        macro_transition     → +0.25
        sentiment_regime     → +0.20
        valuation_regime     → +0.20
        positioning          → +0.15
        balance_sheet_event  → +0.15
        generic company desc → weight 0.60 (below baseline)
    """
    from datetime import datetime, timezone, timedelta
    import copy as _copy

    now = datetime.now(timezone.utc)
    cutoff_recent = now - timedelta(days=_RECENT_CHANGE_AGE_DAYS)

    result = []
    for ev in evidence:
        corpus = f"{ev.title} {ev.summary}".lower()
        tags: list = []

        # Date-based recency tag
        try:
            ev_date = datetime.fromisoformat(ev.timestamp.replace("Z", "+00:00"))
            if ev_date.tzinfo is None:
                ev_date = ev_date.replace(tzinfo=timezone.utc)
            if ev_date >= cutoff_recent:
                tags.append("recent_change")
        except (ValueError, AttributeError):
            pass

        # Content-based tags
        if any(kw in corpus for kw in _TAG_ESTIMATE_REVISION_KEYWORDS):
            tags.append("estimate_revision")
        if any(kw in corpus for kw in _TAG_TONE_SHIFT_KEYWORDS):
            tags.append("tone_shift")
        if any(kw in corpus for kw in _TAG_VALUATION_REGIME_KEYWORDS):
            tags.append("valuation_regime")
        if any(kw in corpus for kw in _TAG_EXPECTATION_CHANGE_KEYWORDS):
            tags.append("expectation_change")
        if any(kw in corpus for kw in _TAG_SENTIMENT_REGIME_KEYWORDS):
            tags.append("sentiment_regime")
        if any(kw in corpus for kw in _TAG_POSITIONING_KEYWORDS):
            tags.append("positioning")
        if any(kw in corpus for kw in _TAG_MACRO_TRANSITION_KEYWORDS):
            tags.append("macro_transition")
        if any(kw in corpus for kw in _TAG_EXECUTION_SIGNAL_KEYWORDS):
            tags.append("execution_signal")
        if any(kw in corpus for kw in _TAG_BALANCE_SHEET_EVENT_KEYWORDS):
            tags.append("balance_sheet_event")

        # Compute weight
        weight = 1.0
        if "recent_change"      in tags: weight += 0.60
        if "estimate_revision"  in tags: weight += 0.50
        if "execution_signal"   in tags: weight += 0.40
        if "tone_shift"         in tags: weight += 0.35
        if "expectation_change" in tags: weight += 0.30
        if "macro_transition"   in tags: weight += 0.25
        if "sentiment_regime"   in tags: weight += 0.20
        if "valuation_regime"   in tags: weight += 0.20
        if "positioning"        in tags: weight += 0.15
        if "balance_sheet_event" in tags: weight += 0.15

        # Generic company description penalty (no actionable tags)
        if not tags:
            weight = 0.60  # below baseline — deprioritize generic descriptions

        # Cap at 3.0
        weight = round(min(3.0, weight), 3)

        # Return new RetrievedEvidence with tags set (avoids mutating caller's list)
        try:
            tagged = ev.model_copy(update={"retrieval_tags": tags, "retrieval_weight": weight})
        except AttributeError:
            # pydantic v1 fallback
            tagged = ev.copy(update={"retrieval_tags": tags, "retrieval_weight": weight})
        result.append(tagged)

    return result


def _weight_sort_evidence(
    evidence: "List[RetrievedEvidence]",
) -> "List[RetrievedEvidence]":
    """Sort evidence by retrieval_weight descending (highest-priority first).

    If retrieval_tags have not been assigned, classifies first.
    Items with equal weight preserve original order (stable sort).
    """
    # Classify if not done
    if evidence and not getattr(evidence[0], "retrieval_tags", None):
        evidence = _classify_evidence_tags(evidence)
    return sorted(evidence, key=lambda e: getattr(e, "retrieval_weight", 1.0), reverse=True)


# ── Expectation regime classifier ─────────────────────────────────────────────

# Expectation regime thresholds derived from expectation_fragility + valuation signals
# Regime labels: cheap | fair | stretched | euphoric | bubble
_REGIME_BUBBLE     = 0.86   # fragility above this → bubble (disconnected from reality)
_REGIME_EUPHORIC   = 0.68   # fragility above this → euphoric  (tightened: 0.72→0.68)
_REGIME_STRETCHED  = 0.50   # fragility above this → stretched
_REGIME_FAIR       = 0.36   # fragility above this → fair      (raised: 0.32→0.36)
_REGIME_ATTRACTIVE = 0.20   # fragility above this → attractive (NEW — between cheap and fair)
# below _REGIME_ATTRACTIVE → cheap


def _classify_expectation_regime(
    expectation_fragility: float,
    valuation_stance:      str = "",
    durability_score:      float = 0.50,
) -> str:
    """Map expectation fragility + valuation signals to a regime label.

    Regime philosophy:
    - Does NOT directly say "buy" or "avoid" — it describes what the market
      is pricing, not what to do about it.
    - durability_score adjusts the thresholds: high-quality businesses can
      sustain stretched multiples longer (higher bar for "euphoric" label).
    - valuation_stance from the valuation agent overrides as a hard signal
      when available.

    Returns: 'cheap' | 'attractive' | 'fair' | 'stretched' | 'euphoric' | 'bubble'
    """
    # Hard overrides from valuation agent stance
    vs = (valuation_stance or "").lower()
    if vs in ("bubble", "severely_overpriced"):
        return "bubble"
    if vs == "euphoric":
        return "euphoric"

    # Durability adjustment: high-quality businesses shift thresholds up
    # (they can trade at higher multiples sustainably)
    dur_adj = durability_score * 0.12   # max +0.12 at durability=1.0

    bubble_thresh     = _REGIME_BUBBLE     + dur_adj
    euphoric_thresh   = _REGIME_EUPHORIC   + dur_adj
    stretched_thresh  = _REGIME_STRETCHED  + dur_adj
    fair_thresh       = _REGIME_FAIR       + dur_adj
    attractive_thresh = _REGIME_ATTRACTIVE + dur_adj

    if expectation_fragility >= bubble_thresh:
        return "bubble"
    if expectation_fragility >= euphoric_thresh:
        return "euphoric"
    if expectation_fragility >= stretched_thresh:
        return "stretched"
    if expectation_fragility >= fair_thresh:
        return "fair"
    if expectation_fragility >= attractive_thresh:
        return "attractive"
    return "cheap"


def _classify_expectation_shift_severity(
    evidence: "List[RetrievedEvidence]",
) -> str:
    """Classify the severity of recent expectation shifts in the evidence pool.

    Scans evidence for revision count, direction consistency, and tone shift
    signals.  Returns:
        'none'        — no material expectation movement detected
        'minor'       — 1-2 directional signals, same direction
        'moderate'    — 3-4 consistent signals or mix of large + small
        'significant' — 5+ consistent signals or major single revision
        'major'       — overwhelming consensus shift in one direction
    """
    ev_text = " ".join(f"{ev.title} {ev.summary}" for ev in evidence[:15]).lower()

    # Count positive and negative revision signals
    positive_signals = sum(1 for kw in (
        "raised estimate", "revised higher", "estimate raise", "upward revision",
        "raised guidance", "raised price target", "pt raised", "beat estimates",
        "above consensus", "better than expected", "exceeded",
    ) if kw in ev_text)

    negative_signals = sum(1 for kw in (
        "lowered estimate", "revised lower", "estimate cut", "downward revision",
        "lowered guidance", "cut guidance", "missed estimates", "below consensus",
        "worse than expected", "fell short", "missed",
    ) if kw in ev_text)

    total = positive_signals + negative_signals
    max_dir = max(positive_signals, negative_signals)

    # Also check for tone shift keywords (qualitative signal)
    tone_shifts = sum(1 for kw in _TAG_TONE_SHIFT_KEYWORDS if kw in ev_text)

    effective_score = max_dir + (tone_shifts * 0.5)

    if effective_score >= 6:
        return "major"
    if effective_score >= 4:
        return "significant"
    if effective_score >= 2.5 or (total >= 3 and tone_shifts >= 1):
        return "moderate"
    if effective_score >= 1:
        return "minor"
    return "none"


# ── Analysis Foundation builder ──────────────────────────────────────────────

def _build_analysis_foundation(
    evidence:   "List[RetrievedEvidence]",
    dims:       "ConvictionDimensions",
    company:    "CompanyContext",
) -> Tuple[List[str], List[str], List[str]]:
    """Build structured Analysis Foundation content for the production UI.

    Returns (evidence_used, constraints, sources) — all human-readable,
    no internal telemetry labels (no GAP_* codes, no dimension field names).

    Design rules
    ------------
    - evidence_used : categories of evidence that contributed to the analysis.
      Ordered by signal richness: richer categories first.  Uses full domain
      labels (e.g. "estimate revision trend") not raw counts.
    - constraints   : what is missing or thin — phrased as informational context,
                      not error codes or internal taxonomy.
    - sources       : data providers that were reflected in the evidence pool.

    Evidence category taxonomy (Part 1 expansion):
      structural   — capital structure, long-term durability signals
      cyclical     — cycle-position, inventory, capacity utilisation
      valuation    — ratios, price multiples, peer comparisons
      sentiment    — analyst upgrades/downgrades, short interest, positioning
      execution    — quarterly delivery vs expectations, guidance beats/misses
      balance_sheet— net cash, debt, buyback capacity
      demand       — unit volumes, attach rates, geographic demand trends
      macro        — rates, FX, inflation, recession signals
      regulatory   — FDA, antitrust, government contract, compliance events
      positioning  — consensus positioning, institutional ownership shifts

    Historical context layer:
      QoQ / YoY comparisons, estimate revision direction, management tone shifts.
    """
    ev_used:     List[str] = []
    constraints: List[str] = []
    sources:     List[str] = []

    # ── Retrieval weighting: sort evidence by intelligence value ──────────────
    # Classify tags if not already done, then sort by weight so high-value
    # items (recent changes, estimate revisions, execution signals) lead the
    # corpus and receive earlier positional priority in the synthesis prompt.
    weighted_evidence = _weight_sort_evidence(list(evidence)) if evidence else []

    # ── Build search corpus (titles + summaries for richer matching) ──────────
    # Use weighted-sorted evidence — high-weight items indexed first
    ev_corpus = " ".join(
        f"{ev.source} {ev.title} {ev.summary}" for ev in weighted_evidence
    ).lower()
    ev_title_corpus = " ".join(
        f"{ev.source} {ev.title}" for ev in weighted_evidence
    ).lower()

    # ── Retrieval tag presence (high-intelligence signals) ───────────────────
    all_tags: list = []
    for ev in weighted_evidence:
        all_tags.extend(getattr(ev, "retrieval_tags", []) or [])
    has_retrieval_recent    = "recent_change"      in all_tags
    has_retrieval_revision  = "estimate_revision"  in all_tags
    has_retrieval_tone      = "tone_shift"          in all_tags
    has_retrieval_sentiment = "sentiment_regime"    in all_tags
    has_retrieval_execution = "execution_signal"    in all_tags
    has_retrieval_regime    = "macro_transition"    in all_tags
    has_retrieval_valuation = "valuation_regime"    in all_tags
    has_retrieval_position  = "positioning"         in all_tags
    has_retrieval_bs        = "balance_sheet_event" in all_tags
    has_retrieval_expect    = "expectation_change"  in all_tags

    # ── Core category detection ───────────────────────────────────────────────
    has_valuation = any(kw in ev_title_corpus for kw in (
        "ratios-ttm", "key-metrics-ttm", "pe ratio", "ev/ebitda",
        "valuation_ratios", "fmp-ratios", "price-to", "forward pe",
        "price target", "fair value",
    ))
    has_analyst = any(kw in ev_title_corpus for kw in (
        "analyst-estimates", "price-target", "consensus", "estimate",
        "upgrade", "downgrade", "initiat",
    ))
    has_filing = any(kw in ev_title_corpus for kw in (
        "10-k", "10-q", "8-k", "sec", "edgar", "annual report",
    ))
    has_earnings = any(kw in ev_corpus for kw in _EARNINGS_KEYWORDS)
    has_macro = any(kw in ev_corpus for kw in (
        "macro", "rate", "inflation", "fed", "yield", "monetary", "economic",
        "fomc", "gdp", "recession", "soft landing",
    ))
    has_competitive = any(kw in ev_corpus for kw in (
        "competitive", "market share", "peer", "industry", "moat",
        "pricing power", "competitive positioning", "market position",
    ))
    has_recurring = any(kw in ev_corpus for kw in (
        "membership", "subscription", "recurring", "renewal", "retention",
        "arr", "annual recurring", "contract",
    ))
    has_ir = any(kw in ev_title_corpus for kw in (
        "investor relations", "ir ", "annual report", "investor day",
    ))

    # ── Extended category detection (Part 1 expansion) ───────────────────────
    has_balance_sheet = any(kw in ev_corpus for kw in (
        "balance sheet", "net cash", "debt", "leverage", "buyback",
        "share repurchase", "capital return", "cash position", "liquidity",
        "free cash flow", "fcf", "net debt",
    ))
    has_demand = any(kw in ev_corpus for kw in (
        "unit volume", "units sold", "attach rate", "demand trend",
        "channel inventory", "sell-through", "shipment", "order book",
        "consumer demand", "enterprise demand", "backlog",
    ))
    has_regulatory = any(kw in ev_corpus for kw in (
        "regulatory", "fda", "antitrust", "doj", "ftc", "government contract",
        "compliance", "investigation", "approval", "legislation", "tariff",
    ))
    has_sentiment = any(kw in ev_corpus for kw in (
        "upgrade", "downgrade", "short interest", "positioning", "sentiment",
        "flows", "options activity", "put/call", "institutional ownership",
        "hedge fund", "13f",
    ))
    has_execution = any(kw in ev_corpus for kw in (
        "beat", "miss", "guidance", "raised guidance", "lowered guidance",
        "above consensus", "below consensus", "in line", "vs estimate",
        "outperformed", "underperformed", "execution",
    ))

    # ── Historical / temporal context detection (Part 1 expansion) ───────────
    has_qoq = any(kw in ev_corpus for kw in (
        "quarter-over-quarter", "qoq", "sequential", "prior quarter",
        "last quarter", "q/q", "quarter to quarter",
    ))
    has_yoy = any(kw in ev_corpus for kw in (
        "year-over-year", "yoy", "y/y", "prior year", "last year",
        "annual comparison", "year on year",
    ))
    has_revision = any(kw in ev_corpus for kw in (
        "estimate revision", "raised estimate", "lowered estimate",
        "cut estimate", "revised higher", "revised lower", "consensus revision",
        "estimate cut", "estimate raise", "upward revision", "downward revision",
    ))
    has_tone_shift = any(kw in ev_corpus for kw in (
        "tone shift", "management tone", "cautious language", "more optimistic",
        "conservative guidance", "bullish commentary", "bearish commentary",
        "changed language", "messaging shift",
    ))
    has_regime = any(kw in ev_corpus for kw in (
        "rate regime", "macro regime", "current cycle", "this cycle",
        "since rates", "since repricing", "regime change",
    ))

    # ── Build ev_used list (ordered by analytical richness) ───────────────────
    # Retrieval-tagged signals take priority (highest intelligence value)
    if has_retrieval_recent or has_retrieval_execution or has_execution:
        ev_used.append("execution vs expectations")
    if has_retrieval_revision or has_revision:
        ev_used.append("estimate revision trend")
    if has_retrieval_tone or has_tone_shift:
        ev_used.append("management tone shift")
    if has_retrieval_expect or has_revision:
        ev_used.append("expectation regime context")
    if has_earnings:
        ev_used.append("earnings commentary")
        sources.append("earnings transcripts")

    # Valuation and analyst coverage
    if has_valuation:
        ev_used.append("valuation multiple context")
        sources.append("Financial Modeling Prep")
    if has_analyst:
        ev_used.append("analyst estimate consensus")
        sources.append("analyst consensus feeds")
    if has_retrieval_sentiment or has_sentiment:
        ev_used.append("analyst sentiment shift")
    if has_retrieval_valuation or has_revision:
        ev_used.append("valuation regime context")
    if has_retrieval_position:
        ev_used.append("institutional positioning shift")

    # Business fundamentals
    if has_recurring:
        ev_used.append("recurring revenue mechanics")
    if has_retrieval_bs or has_balance_sheet:
        ev_used.append("balance sheet and capital structure")
    if has_demand:
        ev_used.append("demand trend and volume indicators")
    if has_competitive:
        ev_used.append("competitive positioning")

    # Macro and regime context
    if has_retrieval_regime or has_macro:
        ev_used.append("macro rate sensitivity")
        sources.append("Federal Reserve data")
    if has_regime:
        ev_used.append("market regime context")

    # Historical comparisons
    if has_qoq:
        ev_used.append("sequential quarter comparison")
    if has_yoy:
        ev_used.append("year-over-year trajectory")
    if has_tone_shift:
        ev_used.append("management tone shift")

    # Structural / regulatory
    if has_filing:
        ev_used.append("SEC filing disclosures")
        sources.append("SEC filings")
    if has_regulatory:
        ev_used.append("regulatory and compliance context")
    if dims.evidence_quality >= 0.60 or len(evidence) >= 5:
        ev_used.append("margin and profitability trajectory")

    if has_ir:
        sources.append("company investor relations")

    # Always include IR for named companies
    ticker = (company.ticker or "").upper()
    if ticker and "company investor relations" not in sources:
        sources.append("company investor relations")

    if not ev_used:
        ev_used = ["limited evidence available for this analysis"]

    # ── Constraints (what is absent or thin) ─────────────────────────────────
    if len(evidence) < 3:
        constraints.append("limited recent evidence depth")
    if not has_earnings:
        constraints.append("limited recent earnings data")
    if not has_analyst:
        constraints.append("incomplete analyst estimate coverage")
    if not has_valuation:
        constraints.append("incomplete valuation anchor data")
    if dims.evidence_freshness < 0.45:
        constraints.append("stale management commentary")
    if not has_filing and len(evidence) < 5:
        constraints.append("SEC filing evidence limited")
    if not has_revision and has_analyst:
        constraints.append("estimate revision direction unclear")

    # ── Deduplicate (preserve insertion order) ────────────────────────────────
    ev_used     = list(dict.fromkeys(ev_used))
    constraints = list(dict.fromkeys(constraints))
    sources     = list(dict.fromkeys(sources))

    return ev_used, constraints, sources


# ── Reasoning builder ─────────────────────────────────────────────────────────

_DRIVER_SENTENCES = {
    "evidence_quality": (
        "Conviction is constrained by the evidence base — "
        "live valuation ratios and analyst price-target consensus are the key missing inputs "
        "that would directly anchor the thesis."
    ),
    "evidence_freshness": (
        "The evidence base does not fully reflect recent developments — "
        "conclusions drawn from older filings may not capture the current operating regime "
        "or the most recent guidance cycle."
    ),
    "thesis_alignment": (
        "The analytical picture is genuinely two-sided — "
        "the bull and bear cases are more evenly matched than a clean directional call requires, "
        "with cross-agent views pointing in conflicting directions."
    ),
    "macro_certainty": (
        "The macro transmission remains the primary unresolved variable — "
        "the rate path, growth outlook, and their combined effect on the multiple "
        "are harder to call than the fundamental picture alone implies."
    ),
    "valuation_certainty": (
        "The valuation anchor is absent — without live multiple data "
        "the current-price-to-intrinsic-value comparison carries more uncertainty than the score reflects, "
        "and multiple-based conclusions depend on assumptions that are not yet validated."
    ),
    "estimate_dispersion": (
        "Sell-side estimates remain dispersed or absent — "
        "without a converged consensus the earnings trajectory and implied multiple "
        "are harder to defend than the directional thesis suggests."
    ),
    "governance_safety": (
        "Analytical consistency checks flagged tensions between the stated thesis "
        "and the underlying evidence — these unresolved contradictions "
        "prevent a higher conviction assignment until they are reconciled."
    ),
    "expectation_safety": (
        "The primary tension is that the business quality is already priced in — "
        "upside requires execution above elevated consensus expectations, not merely meeting them. "
        "The setup becomes fragile if any of the core drivers miss by even a small margin."
    ),
    "asymmetry_safety": (
        "The risk/reward is skewed against the current holder — the setup requires near-perfect "
        "execution continuation while the downside from even a modest miss would be "
        "disproportionately large relative to the remaining upside."
    ),
}

_WHAT_INCREASES_TEMPLATES = {
    "evidence_quality": (
        "Live valuation ratios (forward P/E, EV/EBITDA) and analyst price-target consensus "
        "would directly raise the evidence quality score and unlock a higher conviction tier."
    ),
    "evidence_freshness": (
        "A recent earnings print or updated management guidance would refresh the evidence "
        "base and allow temporal qualifiers to be dropped from the thesis."
    ),
    "thesis_alignment": (
        "Convergence of the risk and valuation analytical views — "
        "currently the most divergent dimensions — would materially raise conviction."
    ),
    "macro_certainty": (
        "Clarity on the rate path (next FOMC decision or inflation print) and "
        "confirmation that the macro transmission mechanism operates as assumed "
        "would sharpen the timing call and lift conviction."
    ),
    "valuation_certainty": (
        "Current-quarter multiple data (forward P/E, EV/EBITDA, FCF yield) "
        "and an analyst consensus price target would anchor the valuation view "
        "and resolve the current uncertainty."
    ),
    "estimate_dispersion": (
        "Convergence of analyst estimates after the next earnings report "
        "would tighten the sell-side envelope and allow a higher conviction assignment."
    ),
    "governance_safety": (
        "Resolution of the analytical inconsistencies flagged in this thesis — "
        "particularly the stance-conclusion alignment — would remove the governance discount."
    ),
    "expectation_safety": (
        "Evidence that the current valuation already implies reasonable (not heroic) assumptions "
        "would raise conviction on the stock setup — either through a valuation reset that "
        "makes the risk/reward more asymmetric, or a sustained beat-and-raise cycle that "
        "earns the current multiple rather than borrowing against future growth."
    ),
    "asymmetry_safety": (
        "Evidence that the setup's downside is contained — either through a valuation reset, "
        "a demonstrated margin of safety, or execution that definitively de-risks the "
        "acceleration dependency — would reduce the asymmetric risk and raise conviction."
    ),
}


def _sanitize_reasoning(text: str) -> str:
    """Strip internal telemetry vocabulary from user-facing reasoning text.

    This is a defensive final-pass sanitizer — a last line of defence against
    any diagnostic artifact surfacing in the production UI.

    Strips:
      - GAP_* diagnostic codes (e.g. GAP_SPARSE, GAP_VALUATION_ABSENT)
      - ALL_CAPS_UNDERSCORE internal schema identifiers
      - Known ontology / telemetry vocabulary
      - Trailing whitespace artefacts

    The function is idempotent and safe to call on already-clean strings.
    """
    import re as _re

    # 1. Strip GAP_* codes (e.g. "GAP_SPARSE_EVIDENCE", "GAP_VALUATION_ABSENT")
    text = _re.sub(r'\bGAP_[A-Z_]+\b', '', text)

    # 2. Strip ALL_CAPS_UNDERSCORE internal identifiers (4+ chars, ≥1 underscore)
    text = _re.sub(r'\b[A-Z]{2,}(?:_[A-Z]{2,})+\b', '', text)

    # 3. Strip known internal ontology vocabulary
    _BANNED_PHRASES = (
        "directional inference",
        "not grounded analysis",
        "cross-agent signals",       # ok in DEV but not user-facing
        "conviction_modeler",
        "evidence_quality",
        "evidence_freshness",
        "thesis_alignment",
        "macro_uncertainty",
        "valuation_certainty",
        "estimate_dispersion",
        "expectation_fragility",
        "expectation_asymmetry",
        "governance_risk",
        "expectation_safety",
        "asymmetry_safety",
    )
    for phrase in _BANNED_PHRASES:
        text = text.replace(phrase, "")

    # 4. Collapse multiple spaces / leading/trailing whitespace
    text = _re.sub(r'  +', ' ', text).strip()

    return text


def _build_reasoning(
    dims:                ConvictionDimensions,
    final_score:         float,
    company:             CompanyContext,
    compression_applied: bool,
    compression_reasons: List[str],
    uncertainty_drivers: List[str],
    evidence:            Optional[List["RetrievedEvidence"]] = None,
    valuation:           Optional["ValuationView"] = None,
) -> str:
    """Build a 2–3 sentence company-specific conviction reasoning string.

    Language patterns mirror PM-grade investment committee communication:
    - High conviction: mechanism + multiple defensible
    - Actionable but demanding: business quality vs. expectation setup
    - Expectation-sensitive: great company, fragile stock setup
    - Asymmetric: disproportionate downside on any miss
    - Speculative: open variables dominate the outcome range
    - Insufficient: too thin to defend

    Phase 5e: realism-specific language patterns for expectation fragility
    dominance — "little room for misses", "multiple vulnerable if growth
    moderates", "acceleration required", HE-ticker explicit awareness.

    Hardening pass: evidence stale/sparse context and valuation multiple
    are now injected into the gap sentence for more specific diagnostics.
    """
    import re as _re

    parts: List[str] = []
    ticker         = company.ticker or "the company"
    _ticker_up     = (company.ticker or "").upper()
    # Derived from computed fragility/asymmetry — no hardcoded ticker lists.
    # A "high-expectation" setup is one where the market has embedded significant
    # execution premiums: high fragility combined with high asymmetry.
    # This drives more precise reasoning language (acceleration vs continuation framing)
    # and accurately reflects the actual computed setup — not a static ticker classification.
    is_he          = (dims.expectation_fragility > 0.56 and dims.expectation_asymmetry > 0.44)

    # ── Evidence context: stale / sparse diagnostics ──────────────────────────
    _ev_list   = evidence or []
    _ev_count  = len(_ev_list)
    _ev_sparse = _ev_count < 3                      # fewer than 3 items → very thin

    _ev_ages       = [_age_days(getattr(ev, "timestamp", None)) for ev in _ev_list]
    _ev_known_ages = [a for a in _ev_ages if a is not None]
    _ev_avg_age    = (sum(_ev_known_ages) / len(_ev_known_ages)) if _ev_known_ages else None
    _ev_stale      = _ev_avg_age is not None and _ev_avg_age > 180   # >6 months avg
    _ev_very_stale = _ev_avg_age is not None and _ev_avg_age > 365   # >12 months avg

    # ── Valuation multiple extraction (for expectation_safety language) ───────
    _pe_raw   = getattr(valuation, "pe_assessment", "") if valuation is not None else ""
    _pe_text  = str(_pe_raw).lower() if _pe_raw and isinstance(_pe_raw, str) else ""
    _pe_match = _re.search(r'(\d{2,3}(?:\.\d+)?)\s*x', _pe_text) if _pe_text else None
    _pe_ratio = float(_pe_match.group(1)) if _pe_match else None

    # Phase 5e: align high_fragility threshold with T6 compression threshold (0.62)
    high_fragility = dims.expectation_fragility > 0.62
    high_asymmetry = dims.expectation_asymmetry > 0.58
    # moderate fragility: priced for perfection but below the severe tier
    mod_fragility  = 0.45 < dims.expectation_fragility <= 0.62

    # ── Tier opener: score × fragility × asymmetry × HE-ticker aware ──────────
    if final_score >= 0.80:
        if high_fragility and is_he:
            tier_opener = (
                f"Conviction on {ticker} is high on business quality, "
                "but the stock setup is structurally demanding — "
                "current pricing assumes execution above consensus with little room for misses."
            )
        elif high_fragility:
            tier_opener = (
                f"Conviction on {ticker} is high on business quality, "
                "but the stock setup is demanding — "
                "current pricing assumes near-perfect continuation of recent execution."
            )
        else:
            tier_opener = (
                f"The investment case for {ticker} reads with high clarity — "
                "the mechanism is consistent with the earnings driver and the multiple "
                "does not require heroic assumptions."
            )
    elif final_score >= 0.65:
        if high_asymmetry and is_he:
            tier_opener = (
                f"The {ticker} thesis is constructive on the business, "
                "but the stock setup is asymmetrically positioned — "
                "the multiple is priced for acceleration, and the downside from even "
                "a modest miss is disproportionate to the remaining upside."
            )
        elif high_asymmetry:
            tier_opener = (
                f"The {ticker} thesis is constructive on the business, "
                "but the setup is asymmetrically positioned — "
                "the downside from even a modest miss is disproportionate to remaining upside."
            )
        elif high_fragility and is_he:
            tier_opener = (
                f"The {ticker} thesis is directionally sound, but the stock setup is "
                "harder than the business case implies — elevated expectations leave little "
                "room for misses, and the multiple is vulnerable if growth moderates "
                "even marginally."
            )
        elif high_fragility:
            tier_opener = (
                f"The {ticker} thesis is directionally sound, but the stock setup is harder "
                "than the business case alone implies — elevated expectations leave limited "
                "room for execution misses or valuation derating."
            )
        elif mod_fragility and is_he:
            tier_opener = (
                f"Conviction on {ticker} is constructive, but the market already prices "
                "continued strong execution — modest misses can reprice the multiple "
                "faster than the business deteriorates."
            )
        else:
            tier_opener = (
                f"Conviction on {ticker} is constructive but not unambiguous — "
                "the core mechanism holds while one or two variables remain open."
            )
    elif final_score >= 0.50:
        if high_asymmetry and high_fragility and is_he:
            tier_opener = (
                f"The {ticker} stock setup demands near-perfect execution — "
                "expectations are elevated, the outcome range is binary, and "
                "acceleration is required to sustain the current multiple, "
                "not merely continuation of recent trends."
            )
        elif high_asymmetry and high_fragility:
            tier_opener = (
                f"The {ticker} stock setup carries a material conviction discount — "
                "expectations are elevated and the outcome is binary enough that "
                "near-perfect execution is required to justify current pricing."
            )
        elif high_fragility and is_he:
            tier_opener = (
                f"The {ticker} setup carries a real conviction discount — "
                "multiple key drivers are priced for acceleration, and the stock "
                "is vulnerable to any guide-down or estimate cut; there is little "
                "room for misses at this expectation level."
            )
        elif high_fragility:
            tier_opener = (
                f"The {ticker} thesis carries a real conviction discount — "
                "the framework is directionally sound but the setup is "
                "expectation-sensitive in a way that caps the score."
            )
        elif mod_fragility and is_he:
            tier_opener = (
                f"The {ticker} thesis is directionally intact but the setup is "
                "demanding — the stock is priced for continued above-consensus delivery, "
                "and the multiple is vulnerable if growth moderates even modestly."
            )
        else:
            tier_opener = (
                f"The {ticker} thesis carries a real conviction discount — "
                "the framework is directionally sound but the outcome range is wider "
                "than a clean call requires."
            )
    elif final_score >= 0.35:
        _primary_driver = uncertainty_drivers[0] if uncertainty_drivers else "key business variables"
        if is_he:
            tier_opener = (
                f"Conviction on {ticker} is limited despite business quality — "
                f"the stock setup demands execution well above what current evidence on "
                f"{_primary_driver} can confidently support, and multiple open variables "
                "make this a speculative call at current expectations."
            )
        else:
            tier_opener = (
                f"Conviction on {ticker} is limited — "
                f"the outcome range is too wide to defend a clean directional call, "
                f"with {_primary_driver} representing the primary unresolved variable."
            )
    else:
        # final_score < 0.35: evidence is too thin to act on — keep the tier_opener
        # focused on the evidence-gap level without repeating the uncertainty driver
        # (the middle gap_sentence handles the company-specific driver anchor).
        if _ev_count == 0:
            tier_opener = (
                f"No usable evidence on {ticker} was available — "
                "a directional conviction call cannot be made without current operating data, "
                "and any directional view would be inference only."
            )
        elif _ev_sparse:
            tier_opener = (
                f"Evidence on {ticker} is extremely limited ({_ev_count} item{'s' if _ev_count != 1 else ''}) — "
                "current data is insufficient to support a defensible conviction level, "
                "and a directional call would overstate the evidence base."
            )
        else:
            tier_opener = (
                f"Current evidence on {ticker} does not yet support a defensible conviction level — "
                "the analytical framework is directionally intact but there is insufficient "
                "operating data to act on the thesis at current prices."
            )
    parts.append(tier_opener)

    # ── Middle: dominant gap with company-specific language ───────────────────
    gap_dim     = _dominant_gap(dims)
    generic_gap = _DRIVER_SENTENCES.get(gap_dim, "")

    if uncertainty_drivers and gap_dim in (
        "macro_certainty", "evidence_quality", "evidence_freshness",
        "valuation_certainty", "estimate_dispersion",
        "expectation_safety", "asymmetry_safety",
    ):
        driver = uncertainty_drivers[0]
        if gap_dim == "macro_certainty":
            gap_sentence = (
                f"The key unresolved variable is {driver} — "
                "until that trajectory clarifies, the timing call remains "
                "harder than the direction call."
            )
        elif gap_dim == "evidence_quality":
            gap_sentence = (
                f"The evidence base for {ticker}'s {driver} is limited — "
                f"without direct data on {driver}, conviction reflects "
                "analytical inference and cross-agent signals rather than grounded primary evidence."
            )
        elif gap_dim == "evidence_freshness":
            if _ev_very_stale and _ev_avg_age:
                _age_mo = round(_ev_avg_age / 30)
                gap_sentence = (
                    f"Operating assumptions on {ticker}'s {driver} rely on evidence "
                    f"that is approximately {_age_mo} months old — at this lag, "
                    "execution data predates meaningful market regime changes and makes "
                    "the valuation framework difficult to validate against current conditions."
                )
            elif _ev_stale and _ev_avg_age:
                _age_mo = round(_ev_avg_age / 30)
                gap_sentence = (
                    f"The evidence base on {ticker}'s {driver} is approximately "
                    f"{_age_mo} months old — management commentary, estimate revisions, "
                    "and recent execution data are absent, which reduces confidence in "
                    "execution-sensitive assumptions."
                )
            else:
                gap_sentence = (
                    f"The evidence base predates the latest developments on {driver} — "
                    "conclusions may not fully reflect the current execution picture "
                    "or the most recent guidance cycle."
                )
        elif gap_dim == "valuation_certainty":
            gap_sentence = (
                f"The valuation call is constrained by uncertainty around {driver} — "
                "without current ratio data the multiple anchor is absent."
            )
        elif gap_dim == "estimate_dispersion":
            gap_sentence = (
                f"Analyst estimates remain dispersed, particularly around {driver} — "
                "sell-side consensus has not yet converged."
            )
        elif gap_dim == "expectation_safety":
            _pe_clause = (
                f"At ~{_pe_ratio:.0f}x forward earnings, "
                if _pe_ratio and _pe_ratio > 25 else ""
            )
            if dims.expectation_fragility > 0.80:
                gap_sentence = (
                    f"{_pe_clause}the setup is demanding — {driver} is priced for continued "
                    "acceleration, leaving little room for misses. "
                    "Expectations are elevated to a level where even modest shortfalls "
                    "create asymmetric repricing; the multiple is vulnerable if growth "
                    "moderates even slightly."
                )
            elif dims.expectation_fragility > 0.62:
                # Phase 5e: lowered from 0.65 to match T6 threshold
                gap_sentence = (
                    f"The primary tension is that {driver} is priced optimistically — "
                    f"{_pe_clause}the stock setup requires outrunning elevated expectations, "
                    "not merely meeting them. The multiple is vulnerable if growth moderates or "
                    "execution disappoints even marginally."
                )
            elif dims.expectation_fragility > 0.45 and is_he:
                # Phase 5e: HE-ticker moderate fragility — still call out expectation risk
                gap_sentence = (
                    f"{_pe_clause}{ticker}'s {driver} carries embedded expectation premium — "
                    "the market prices above-consensus execution as the base case, "
                    "meaning any guide-down or estimate cut reprices faster than "
                    "the fundamental deterioration warrants."
                )
            else:
                gap_sentence = (
                    f"The primary tension is that {driver} is priced optimistically — "
                    f"{_pe_clause}the stock setup requires the business to outrun elevated "
                    "expectations, not merely meet them."
                )
        elif gap_dim == "asymmetry_safety":
            if is_he:
                gap_sentence = (
                    f"Execution dependency on {driver} creates pronounced asymmetric risk "
                    f"for {ticker} — a miss reprices materially while upside from a beat "
                    "is largely priced in; acceleration is required, not just continuation."
                )
            else:
                gap_sentence = (
                    f"Execution dependency on {driver} creates asymmetric risk — "
                    "a miss reprices materially while upside from a beat is largely priced in."
                )
        else:
            gap_sentence = generic_gap
        parts.append(gap_sentence)
    elif generic_gap:
        parts.append(generic_gap)

    # ── Closing: compression / fragility / asymmetry note ────────────────────
    if compression_applied and compression_reasons:
        reason_summary = compression_reasons[0]
        if len(compression_reasons) >= 2:
            if is_he:
                parts.append(
                    f"The setup becomes acutely fragile if any key driver disappoints — "
                    f"{reason_summary}."
                )
            else:
                parts.append(
                    f"The setup becomes fragile if any of the key drivers disappoint — "
                    f"{reason_summary}."
                )
        else:
            parts.append(
                f"A conviction discount was applied because: {reason_summary}."
            )
    elif high_asymmetry and not compression_applied and len(parts) < 3:
        if is_he:
            parts.append(
                f"The market leaves no room for stumble on {ticker} — "
                "any shortfall against elevated expectations creates asymmetric repricing, "
                "and the multiple is vulnerable to even a modest guide-down."
            )
        else:
            parts.append(
                "The market leaves no room for stumble — "
                "any shortfall against elevated expectations creates asymmetric repricing."
            )
    elif high_fragility and not compression_applied and len(parts) < 3:
        if dims.expectation_fragility > 0.80:
            parts.append(
                "Acceleration is required — not just continuation — for the current "
                "multiple to be sustained. Any deceleration reprices the thesis materially."
            )
        elif is_he:
            parts.append(
                f"Acceleration is required to hold the {ticker} multiple, not merely "
                "continuation — current pricing reflects consensus-beating execution "
                "as the base case, leaving the stock vulnerable if growth moderates."
            )
        else:
            parts.append(
                "Current expectations leave little room for execution misses; "
                "the market already assumes near-perfect continuation."
            )
    elif mod_fragility and is_he and not compression_applied and len(parts) < 3:
        # Phase 5e: catch HE tickers with moderate fragility that slipped through above
        parts.append(
            f"The {ticker} multiple is vulnerable if growth moderates — "
            "current pricing assumes continued above-consensus delivery, "
            "and even a modest deceleration creates repricing risk disproportionate "
            "to the underlying business change."
        )

    result = " ".join(parts[:3])   # cap at 3 sentences

    # ── Realism guard: reasoning must always reference the ticker ─────────────
    # If parts is unexpectedly empty (edge-case path not yet covered), emit a
    # company-specific minimal fallback rather than an empty string.
    if not result or (company.ticker and company.ticker.upper() not in result.upper()):
        _primary = uncertainty_drivers[0] if uncertainty_drivers else "key operating variables"
        result = (
            f"Conviction on {ticker} reflects the current evidence depth — "
            f"the primary open variable is {_primary}, and until that resolves, "
            "the timing call is harder than the directional case."
        )

    # ── Phase 4: production sanitizer — strip any leaked telemetry vocabulary ──
    return _sanitize_reasoning(result)


def _build_what_increases_conviction(
    dims:                ConvictionDimensions,
    company:             CompanyContext,
    uncertainty_drivers: List[str],
    question_intent:     Optional[str] = None,
) -> str:
    """Build the ``what_increases_conviction`` field — PM-grade next steps.

    Company-specific drivers are injected into the template wherever the gap dimension
    maps to an actionable data event or market development.

    Phase 3: when ``question_intent`` is set, the output is further tailored to name
    the specific confirming / disconfirming signal most relevant to what the user asked.
    This prevents the ``valuation_certainty`` template from dominating all question types.
    """
    gap_dim  = _dominant_gap(dims)
    template = _WHAT_INCREASES_TEMPLATES.get(gap_dim, "")
    ticker   = company.ticker or "this company"

    driver_1 = uncertainty_drivers[0] if uncertainty_drivers else f"{ticker}-specific developments"
    driver_2 = uncertainty_drivers[1] if len(uncertainty_drivers) > 1 else ""

    # ── Phase 3: question-intent override ────────────────────────────────────
    # When the user's question has a specific analytical dimension, produce a
    # confirming + disconfirming signal pair anchored on that dimension rather
    # than the generic gap-dimension template.  Returns early so the gap-dim
    # branches below do not fire.
    if question_intent and question_intent not in ("investment_thesis", None):
        if question_intent == "competitive_position":
            return (
                f"CONFIRMING: Market-share data or enterprise win/loss announcements "
                f"showing {ticker} holding or gaining vs key competitors in {driver_1} "
                f"would be the highest-value conviction signal. "
                f"DISCONFIRMING: A competitor announcement of workload migration away from "
                f"{ticker}, or a pricing concession that signals moat erosion, would be the "
                f"primary signal to watch."
            )
        elif question_intent == "macro_sensitivity":
            macro_event = driver_1 if "rate" in driver_1.lower() or "macro" in driver_1.lower() \
                          else "rate path and economic cycle"
            return (
                f"CONFIRMING: The next Fed decision or inflation print confirming a rate "
                f"trajectory supportive of {ticker}'s multiple would be the clearest "
                f"conviction catalyst. "
                f"DISCONFIRMING: A hawkish surprise or deterioration in {macro_event} "
                f"beyond consensus expectations would signal the macro transmission mechanism "
                f"is working against the thesis."
            )
        elif question_intent == "valuation_stance":
            return (
                f"CONFIRMING: An earnings beat with raised guidance on {driver_1}, or an "
                f"analyst upgrade cluster citing improving risk/reward at current multiples, "
                f"would confirm the valuation is justified. "
                f"DISCONFIRMING: A guidance cut, estimate revision downward, or multiple "
                f"de-rate triggered by a {ticker}-specific miss would be the primary "
                f"disconfirming trigger to watch."
            )
        elif question_intent == "risk_assessment":
            return (
                f"RISK-MATERIALIZING: {driver_1} — if this develops adversely, treat it as "
                f"confirmation the primary risk is playing out. "
                f"RISK-RESOLUTION: Conversely, a clear announcement or data point that "
                f"structurally removes {driver_1} from the risk register would be the "
                f"highest-value de-risking signal for {ticker}."
            )

    # ── Default: existing gap-dimension logic (unchanged) ────────────────────
    if not uncertainty_drivers:
        return template

    if gap_dim == "macro_certainty":
        return (
            f"Clarity on {driver_1} would be the single biggest conviction driver. "
            + (f"A secondary resolution trigger is {driver_2}." if driver_2 else "")
        ).strip()

    elif gap_dim in ("evidence_quality", "evidence_freshness"):
        return (
            f"The next {ticker} earnings print or management update on {driver_1} "
            "would be the highest-value evidence addition for raising conviction."
        )

    elif gap_dim == "valuation_certainty":
        return (
            f"Current-quarter multiple data anchored to {driver_1} developments "
            "and an updated analyst consensus price target would resolve the valuation uncertainty."
        )

    elif gap_dim == "estimate_dispersion":
        return (
            f"Post-earnings analyst revision convergence, particularly around {driver_1}, "
            "would tighten the sell-side envelope and allow a higher conviction tier."
        )

    elif gap_dim == "expectation_safety":
        return (
            f"Evidence that current pricing implies reasonable assumptions on {driver_1} — "
            "or a reset of expectations to a more achievable level — would meaningfully raise "
            f"conviction on the {ticker} stock setup. "
            + (
                f"Separately, resolution of {driver_2} would reduce the binary risk "
                "in the current expectation structure."
                if driver_2 else ""
            )
        ).strip()

    elif gap_dim == "asymmetry_safety":
        return (
            f"Demonstrated execution discipline on {driver_1} — "
            "showing the business can deliver without requiring acceleration above consensus — "
            f"would de-risk the asymmetric setup and allow a higher conviction tier for {ticker}."
            + (
                f" A resolution of {driver_2} would further reduce the binary tail risk."
                if driver_2 else ""
            )
        ).strip()

    return template


# ── Public entry point ────────────────────────────────────────────────────────

def compute_conviction(
    evidence:            List[RetrievedEvidence],
    valuation:           ValuationView,
    macro:               MacroSensitivity,
    risk:                RiskProfile,
    market:              MarketContext,
    quality:             QualityAssessment,
    company:             CompanyContext,
    ranked:              Optional[Any] = None,
    governance_warnings: Optional[List[str]] = None,
    profile:             Optional[CompanyKnowledgeProfile] = None,
    question_intent:     Optional[str] = None,
) -> ConvictionResult:
    """Compute institutional-grade conviction score and reasoning.

    Parameters
    ----------
    evidence            : Full evidence pool fed into the synthesis.
    valuation/macro/…   : Specialist agent outputs.
    company             : Company identity (ticker, sector).
    ranked              : Optional RankedSignalSet from rank_signals().
    governance_warnings : Consistency warning strings from _run_governance_checks().
    profile             : Optional company knowledge profile.
    question_intent     : Detected question intent from _detect_question_intent().
                          When set, ``what_increases_conviction`` is branched by intent
                          to produce a confirming + disconfirming signal pair anchored on
                          the dimension the user actually asked about.

    Returns
    -------
    ConvictionResult with final_score (0–1), per-dimension sub-scores,
    company-specific confidence_reasoning, and what_increases_conviction.
    """
    warnings_list = governance_warnings or []
    uncertainty_drivers = _get_uncertainty_drivers(company)

    # ── Business durability score ─────────────────────────────────────────────
    # Computed from: CompanyKnowledgeProfile + QualityAssessment + RiskProfile + evidence.
    # Replaces _QUALITY_DURABLE_TICKERS and _HIGH_EXPECTATION_TICKERS frozensets.
    # High durability (≥0.65) → label floor fires; continuous offset on fragility/asymmetry.
    durability_score = _compute_business_durability(quality, risk, evidence, profile)
    _logger.debug(
        "[durability] ticker=%s score=%.4f threshold=%.2f floor_fires=%s",
        company.ticker or "UNKNOWN", durability_score, _DURABILITY_FLOOR_THRESHOLD,
        durability_score >= _DURABILITY_FLOOR_THRESHOLD,
    )

    # ── Pass 1: Score the seven linear dimensions + expectation_fragility ─────
    dims_base = ConvictionDimensions(
        evidence_quality      = _score_evidence_quality(evidence),
        evidence_freshness    = _score_evidence_freshness(evidence),
        thesis_alignment      = _score_thesis_alignment(
                                    valuation, macro, risk, market, quality, ranked),
        macro_uncertainty     = _score_macro_uncertainty(macro, evidence),
        valuation_certainty   = _score_valuation_certainty(valuation, evidence),
        estimate_dispersion   = _score_estimate_dispersion(evidence),
        governance_risk       = _score_governance_risk(warnings_list),
        expectation_fragility = _score_expectation_fragility(
                                    valuation, evidence, company, durability_score),
    )

    # ── Archetype-informed scoring floors (sparse evidence protection) ─────────
    # Archetype is inferred from durability_score — NOT from ticker identity.
    # For durable compounders, the CompanyKnowledgeProfile encodes business model
    # facts that provide structural conviction even when literal evidence is sparse.
    # The floor represents: "this profile knowledge is itself a form of evidence."
    #
    # Design constraint: _DURABLE_EQ_FLOOR < 0.50 ensures the QD label floor
    # condition (evidence_quality < 0.50) still fires for sparse-evidence durable
    # businesses, lifting "mixed evidence" → "monitoring required" (Balanced tier).
    #
    # Effect on target tickers (sparse evidence, overpriced valuation):
    #   durable_compounder:           score ~32% → ~47%  label: Balanced ✓
    #   expectation_sensitive_quality: score ~32% → ~40%  label: Fragile  ✓
    #   narrative_fragile:             score ~31-33%        label: Speculative ✓
    _eq_raw = dims_base.evidence_quality
    _ef_raw = dims_base.evidence_freshness
    _ta_raw = dims_base.thesis_alignment
    _eq_floor, _ef_floor, _ta_floor = _infer_archetype_floors(durability_score)
    if _eq_floor > 0.0 or _ta_floor > 0.0:
        dims_base = dataclasses.replace(
            dims_base,
            evidence_quality   = max(_eq_raw, _eq_floor),
            evidence_freshness = max(_ef_raw, _ef_floor),
            thesis_alignment   = max(_ta_raw, _ta_floor),
        )
        _logger.debug(
            "[archetype_floors] ticker=%s durability=%.3f "
            "eq %.3f→%.3f  ef %.3f→%.3f  ta %.3f→%.3f",
            company.ticker or "UNKNOWN", durability_score,
            _eq_raw, dims_base.evidence_quality,
            _ef_raw, dims_base.evidence_freshness,
            _ta_raw, dims_base.thesis_alignment,
        )

    # ── Pass 2: Score expectation_asymmetry (depends on dims_base fields) ────
    asymmetry_score = _score_expectation_asymmetry(
        valuation, evidence, company, dims_base, durability_score)
    dims = dataclasses.replace(dims_base, expectation_asymmetry=asymmetry_score)

    # ── Ticker identifier (used in log lines below) ──────────────────────────
    _ticker_up = (company.ticker or "UNKNOWN").upper()

    # ── Compose: linear_base × fragility_mult × asymmetry_mult ───────────────
    frag_mult = _fragility_multiplier(dims.expectation_fragility)
    asym_mult = _asymmetry_multiplier(dims.expectation_asymmetry)
    raw_score = _compose_score(dims)  # internally applies both multipliers

    # ── Durability persistence bonus ─────────────────────────────────────────
    # Additive bonus representing structural business quality conviction that
    # exists independent of evidence depth.  Applied before compression so
    # compression can still cap upside, but the bonus protects the floor.
    _durability_bonus = max(0.0, (durability_score - 0.40) * _DURABILITY_BONUS_SCALE)
    raw_score_with_bonus = round(
        min(_MAX_SCORE, max(_MIN_SCORE, raw_score + _durability_bonus)), 4
    )
    _logger.debug(
        "[durability_bonus] ticker=%s durability=%.3f bonus=%.4f "
        "raw=%.4f raw_with_bonus=%.4f",
        _ticker_up, durability_score, _durability_bonus, raw_score, raw_score_with_bonus,
    )

    # ── Tiered contradiction compression ─────────────────────────────────────
    should_compress, compression_reasons, compression_factor = _check_contradiction_compression(
        dims, valuation, ranked, evidence
    )
    if should_compress:
        # For durable compounders: compression cannot exceed _DURABLE_MIN_COMPRESSION_FACTOR
        # Prevents over-stacking for elite businesses at demanding valuations.
        if durability_score >= _ARCHETYPE_DURABLE_THRESHOLD:
            compression_factor = max(compression_factor, _DURABLE_MIN_COMPRESSION_FACTOR)
        final_score = round(
            min(_MAX_SCORE, max(_MIN_SCORE, raw_score_with_bonus * compression_factor)), 4
        )
    else:
        final_score = raw_score_with_bonus

    # ── Semantic setup label ──────────────────────────────────────────────────
    # Note: The Phase 5e HE structural compression (×0.88 for high-expectation tickers)
    # has been removed.  The durability-based fragility/asymmetry offsets now correctly
    # differentiate high-expectation-durable (COST, MSFT) from high-expectation-fragile
    # (TSLA, PLTR) setups without requiring a post-compression ticker-specific override.
    # The overpriced valuation stance (+0.28 fragility) combined with the durability
    # offset provides the correct natural spread.
    # ── Matrix-based setup label (Phase 1+2 architecture) ────────────────────
    # setup_label is derived from a 2D (durability × expectation_risk) matrix.
    # This completely replaces _confidence_band_label() + the label-floor patch.
    #
    # Key design guarantee:
    #   - Durable compounders (durability ≥ 0.60) NEVER receive "speculative setup".
    #   - The composite confidence_score (evidence depth) does NOT affect the label.
    #   - Only business durability class + expectation risk level determine the label.
    #
    # Logging for traceability:
    _expectation_risk = _compute_expectation_risk(dims)
    setup_label = _durability_matrix_label(durability_score, _expectation_risk)
    _logger.debug(
        "[matrix_label] ticker=%s durability=%.3f expectation_risk=%.3f → label=%s "
        "(frag=%.3f asym=%.3f final_score=%.3f)",
        _ticker_up, durability_score, _expectation_risk, setup_label,
        dims.expectation_fragility, dims.expectation_asymmetry, final_score,
    )

    # ── Expectation regime (computed BEFORE stance so it gates stance rules) ──
    _val_stance = (getattr(valuation, "valuation_stance", "") or "").lower()
    _exp_regime = _classify_expectation_regime(
        expectation_fragility = dims.expectation_fragility,
        valuation_stance      = _val_stance,
        durability_score      = durability_score,
    )

    # ── Directional stance ────────────────────────────────────────────────────
    _stance, _stance_reasoning = _compute_directional_stance(
        final_score, dims, setup_label, company,
        expectation_regime = _exp_regime,
        durability_score   = durability_score,
    )

    # ── Reasoning and what_increases_conviction ───────────────────────────────
    reasoning = _build_reasoning(
        dims, final_score, company, should_compress, compression_reasons, uncertainty_drivers,
        evidence=evidence, valuation=valuation,
    )
    what_increases = _build_what_increases_conviction(
        dims, company, uncertainty_drivers, question_intent=question_intent
    )

    # ── Analysis Foundation (user-facing structured provenance) ───────────────
    _af_evidence, _af_constraints, _af_sources = _build_analysis_foundation(
        evidence, dims, company
    )

    # ── Expectation Intelligence ──────────────────────────────────────────────
    _exp_shift_sev = _classify_expectation_shift_severity(evidence)

    # ── Structured telemetry ──────────────────────────────────────────────────
    if should_compress:
        _compression_tier = (
            "severe"       if compression_factor <= _COMPRESSION_SEVERE
            else "significant" if compression_factor <= _COMPRESSION_SIGNIFICANT
            else "mild"
        )
    else:
        _compression_tier = "none"

    _logger.debug(
        "[conviction_telemetry] ticker=%s "
        "linear_base=%.3f fragility_score=%.3f asymmetry_score=%.3f "
        "expectation_safety=%.3f frag_mult=%.3f asym_mult=%.3f "
        "raw_score=%.3f final_score=%.3f "
        "setup_label=%s compression_tier=%s compression_reasons=%d",
        company.ticker or "UNKNOWN",
        _linear_base_score(dims),
        dims.expectation_fragility,
        dims.expectation_asymmetry,
        round(1.0 - dims.expectation_fragility, 3),
        frag_mult, asym_mult,
        raw_score, final_score,
        setup_label, _compression_tier, len(compression_reasons),
    )

    # ── [BACKEND_FINAL_RESPONSE] — mandatory INFO log before serialization ────
    # This is the AUTHORITATIVE last-mile log. If Render logs show this line
    # with wrong values, the bug is in conviction_modeler. If it shows correct
    # values but the frontend renders wrong values, the bug is in serialization
    # or the proxy. Search for "[BACKEND_FINAL_RESPONSE]" in Render logs.
    _logger.info(
        "[BACKEND_FINAL_RESPONSE] ticker=%s "
        "conviction_schema=%s matrix_enabled=%s "
        "durability=%.3f expectation_risk=%.3f "
        "setup_label=%s final_score=%.4f (%d%%) "
        "frag_mult=%.3f asym_mult=%.3f compression=%s",
        _ticker_up,
        CONVICTION_SCHEMA_VERSION, ARCHETYPE_MATRIX_ENABLED,
        durability_score, _expectation_risk,
        setup_label, final_score, round(final_score * 100),
        frag_mult, asym_mult, should_compress,
    )

    return ConvictionResult(
        final_score                       = final_score,
        dimensions                        = dims,
        confidence_reasoning              = reasoning,
        what_increases_conviction         = what_increases,
        setup_label                       = setup_label,
        compression_applied               = should_compress,
        compression_reasons               = compression_reasons,
        fragility_multiplier_applied      = frag_mult,
        asymmetry_multiplier_applied      = asym_mult,
        directional_stance                = _stance,
        directional_stance_reasoning      = _stance_reasoning,
        analysis_foundation_evidence      = _af_evidence,
        analysis_foundation_constraints   = _af_constraints,
        analysis_foundation_sources       = _af_sources,
        expectation_regime                = _exp_regime,
        expectation_shift_severity        = _exp_shift_sev,
    )
