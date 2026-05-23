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
    "evidence_quality":    0.20,
    "evidence_freshness":  0.15,
    "thesis_alignment":    0.25,
    "macro_uncertainty":   0.15,   # applied as (1 - macro_uncertainty)
    "valuation_certainty": 0.15,
    "estimate_dispersion": 0.06,
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
_HIGH_EXPECTATION_TICKERS = frozenset({
    "NVDA", "TSLA", "ARM", "SMCI", "PLTR", "SNOW", "CRWD", "DDOG",
    "NET", "SHOP", "COIN", "RBLX", "HOOD", "RIVN", "LCID",
    "CAVA", "CELH", "DUOL", "AI", "SOUN",
})


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
    # Inverted from macro confidence
    base = 1.0 - macro.confidence

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


def _score_expectation_fragility(
    valuation:  "ValuationView",
    evidence:   "List[RetrievedEvidence]",
    company:    "CompanyContext",
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

    # ── Ticker-specific structural premium ────────────────────────────────────
    # Phase 5e: increased from +0.15 to +0.20 — ensures HE tickers clear T6 threshold
    # (0.62) even with fairly_valued stance and minimal explicit signals:
    #   base(0.28) + fairly_valued(0.08) + HE(0.20) = 0.56 → not quite T6
    #   with any 2 priced_in_terms hits: +0.14 → 0.70 > T6 threshold
    ticker = (company.ticker or "").upper()
    if ticker in _HIGH_EXPECTATION_TICKERS:
        base += 0.20

    return round(min(0.95, max(0.05, base)), 4)


def _score_expectation_asymmetry(
    valuation:  "ValuationView",
    evidence:   "List[RetrievedEvidence]",
    company:    "CompanyContext",
    dims:       "ConvictionDimensions",
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

    # Structural ticker asymmetry — Phase 5e: increased +0.15 → +0.20
    ticker = (company.ticker or "").upper()
    if ticker in _HIGH_EXPECTATION_TICKERS:
        base += 0.20

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


def _confidence_band_label(
    final_score: float,
    dims:        "ConvictionDimensions",
) -> str:
    """Return a semantic setup label for the conviction band.

    The label is context-sensitive: the same score range can carry different
    labels depending on whether the dominant driver is fragility, asymmetry,
    or evidence quality / thesis alignment.

    Band targets (Phase 5d calibration):
        Durable    — ≥0.75  → high-alignment thesis
        Balanced   — 0.60–0.75 → actionable thesis / monitoring required
        Demanding  — 0.45–0.60 → mixed evidence / expectation-sensitive / asymmetric/fragile setup
        Speculative — 0.20–0.45 → speculative setup
        Minimal    — <0.20  → insufficient conviction

    These boundaries are intentionally tight: they force meaningful spread across
    the semantic tier meter.  A PM reading "Balanced" at 68% vs "Speculative" at
    32% should immediately understand the expectation asymmetry difference.
    """
    frag = dims.expectation_fragility
    asym = dims.expectation_asymmetry

    if final_score >= 0.75:
        return "high-alignment thesis"
    elif final_score >= 0.60:
        if frag > 0.60 or asym > 0.55:
            return "monitoring required"
        return "actionable thesis"
    elif final_score >= 0.45:
        if asym > 0.60:
            return "asymmetric setup"
        if frag > 0.65:
            return "expectation-sensitive"
        if dims.thesis_alignment < 0.45:
            return "fragile setup"
        return "mixed evidence"
    elif final_score >= 0.20:
        return "speculative setup"
    else:
        return "insufficient conviction"


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
    is_he          = _ticker_up in _HIGH_EXPECTATION_TICKERS

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

    return result


def _build_what_increases_conviction(
    dims:                ConvictionDimensions,
    company:             CompanyContext,
    uncertainty_drivers: List[str],
) -> str:
    """Build the ``what_increases_conviction`` field — PM-grade next steps.

    Company-specific drivers are injected into the template wherever the gap dimension
    maps to an actionable data event or market development.
    """
    gap_dim  = _dominant_gap(dims)
    template = _WHAT_INCREASES_TEMPLATES.get(gap_dim, "")
    ticker   = company.ticker or "this company"

    if not uncertainty_drivers:
        return template

    driver_1 = uncertainty_drivers[0]
    driver_2 = uncertainty_drivers[1] if len(uncertainty_drivers) > 1 else ""

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

    Returns
    -------
    ConvictionResult with final_score (0–1), per-dimension sub-scores,
    company-specific confidence_reasoning, and what_increases_conviction.
    """
    warnings_list = governance_warnings or []
    uncertainty_drivers = _get_uncertainty_drivers(company)

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
        expectation_fragility = _score_expectation_fragility(valuation, evidence, company),
    )

    # ── Pass 2: Score expectation_asymmetry (depends on dims_base fields) ────
    asymmetry_score = _score_expectation_asymmetry(valuation, evidence, company, dims_base)
    dims = dataclasses.replace(dims_base, expectation_asymmetry=asymmetry_score)

    # ── Compose: linear_base × fragility_mult × asymmetry_mult ───────────────
    frag_mult = _fragility_multiplier(dims.expectation_fragility)
    asym_mult = _asymmetry_multiplier(dims.expectation_asymmetry)
    raw_score = _compose_score(dims)  # internally applies both multipliers

    # ── Tiered contradiction compression ─────────────────────────────────────
    should_compress, compression_reasons, compression_factor = _check_contradiction_compression(
        dims, valuation, ranked, evidence
    )
    if should_compress:
        final_score = round(
            min(_MAX_SCORE, max(_MIN_SCORE, raw_score * compression_factor)), 4
        )
    else:
        final_score = raw_score

    # ── HE ticker structural compression (Phase 5e) ───────────────────────────
    # High-expectation tickers embed performance expectations that evidence alone
    # cannot fully reflect.  Even when the analytical picture is constructive,
    # the market setup embeds a fragility premium that systematically reduces
    # the defensible conviction level for these names.
    #
    # This fires AFTER contradiction compression as a final structural adjustment.
    # Intentionally mild (×0.88) — and ONLY when contradiction compression hasn't
    # already applied significant or severe penalties (≤0.80 factor).  This prevents
    # double-penalising tickers like NVDA-overpriced which already received T6
    # significant compression; the HE premium is for cases where the analytical
    # picture reads constructive but the market setup still embeds an unreflected risk.
    #
    # Conditions:
    #   - HE ticker
    #   - thesis_alignment > 0.45 (most real analyses; excludes pure empty-evidence cases)
    #   - contradiction compression was NONE or MILD only (factor > _COMPRESSION_SIGNIFICANT)
    _ticker_up = (company.ticker or "").upper()
    _existing_factor = compression_factor if should_compress else 1.0
    if (
        _ticker_up in _HIGH_EXPECTATION_TICKERS
        and dims.thesis_alignment > 0.45
        and _existing_factor > _COMPRESSION_SIGNIFICANT   # 0.80 — only fires when mild/none
    ):
        _he_pre = final_score
        final_score = round(min(_MAX_SCORE, max(_MIN_SCORE, final_score * _COMPRESSION_MILD)), 4)
        if not should_compress:
            should_compress = True
            compression_reasons = []
        compression_reasons.append(
            f"{_ticker_up} embeds structural expectation premium — "
            "market pricing reflects continued execution above consensus, "
            "creating setup sensitivity beyond what fundamentals alone support"
        )
        _logger.debug(
            "[he_structural_compression] ticker=%s pre=%.3f post=%.3f factor=%.2f",
            _ticker_up, _he_pre, final_score, _COMPRESSION_MILD,
        )

    # ── Semantic setup label ──────────────────────────────────────────────────
    setup_label = _confidence_band_label(final_score, dims)

    # ── Reasoning and what_increases_conviction ───────────────────────────────
    reasoning = _build_reasoning(
        dims, final_score, company, should_compress, compression_reasons, uncertainty_drivers,
        evidence=evidence, valuation=valuation,
    )
    what_increases = _build_what_increases_conviction(dims, company, uncertainty_drivers)

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

    return ConvictionResult(
        final_score                  = final_score,
        dimensions                   = dims,
        confidence_reasoning         = reasoning,
        what_increases_conviction    = what_increases,
        setup_label                  = setup_label,
        compression_applied          = should_compress,
        compression_reasons          = compression_reasons,
        fragility_multiplier_applied = frag_mult,
        asymmetry_multiplier_applied = asym_mult,
    )
