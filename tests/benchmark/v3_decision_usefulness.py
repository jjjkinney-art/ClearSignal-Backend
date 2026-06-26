"""V3 — Decision Usefulness Validation

Measures whether ClearSignal produces investment conclusions that actually
improve decisions — not merely whether the explanations are well-written.

Evaluates 7 dimensions:
  1. Actionability         — would an investor know what to do?
  2. Thesis clarity        — is there one dominant investment idea?
  3. Decision differentiation — do different scores produce different advice?
  4. Thesis-breaker quality — are thesis-change triggers concrete and falsifiable?
  5. Risk prioritization   — is the #1 risk actually the biggest risk?
  6. Monitoring quality    — does output generate a practical monitoring checklist?
  7. Recommendation consistency — do all fields reinforce each other?

Run:  python3 -m pytest tests/benchmark/v3_decision_usefulness.py -v -s
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Dict, List, Optional, Set, Tuple

import pytest

from tests.benchmark.v0_institutional_benchmark import BENCHMARK, BenchmarkEntry


# ---------------------------------------------------------------------------
# Score container
# ---------------------------------------------------------------------------

@dataclass
class DecisionScore:
    ticker: str
    company: str

    actionability: int = 0           # 0-100
    thesis_clarity: int = 0          # 0-100
    differentiation: int = 0         # 0-100 (set at cohort level)
    thesis_breaker_quality: int = 0  # 0-100
    risk_prioritization: int = 0     # 0-100
    monitoring_quality: int = 0      # 0-100
    consistency: int = 0             # 0-100

    failures: List[str] = field(default_factory=list)

    @property
    def composite(self) -> float:
        return (
            self.actionability * 0.20
            + self.thesis_clarity * 0.15
            + self.differentiation * 0.10
            + self.thesis_breaker_quality * 0.20
            + self.risk_prioritization * 0.10
            + self.monitoring_quality * 0.10
            + self.consistency * 0.15
        )


# ---------------------------------------------------------------------------
# Pattern libraries
# ---------------------------------------------------------------------------

# Actionability: language that tells an investor what to do
_ACTION_PATTERNS = [
    re.compile(r'\b(buy|sell|add|reduce|accumulate|avoid|exit|trim)\b', re.I),
    re.compile(r'\b(on (weakness|dips?|pullback)|into strength)\b', re.I),
    re.compile(r'\b(entry point|price target|fair value)\b', re.I),
    re.compile(r'\b(catalyst|trigger|inflection|turning point)\b', re.I),
    re.compile(r'\b(upside|downside) (potential|risk|skew|asymmetry)\b', re.I),
    re.compile(r'\b(watch for|monitor|key (data|metric|print)|look for)\b', re.I),
    re.compile(r'\b(if .{5,40} then)\b', re.I),
    re.compile(r'\b(would (reassess|exit|increase|decrease))\b', re.I),
    re.compile(r'\b(position (size|sizing|management))\b', re.I),
    re.compile(r'\b(risk[/-]reward)\b', re.I),
]

# Thesis clarity: signals of a coherent single-idea thesis
_THESIS_SIGNALS = [
    re.compile(r'\b(primary|core|central|dominant|key|main) (thesis|investment|question|debate)\b', re.I),
    re.compile(r'\b(the (bull|bear) case (is|rests on|depends on))\b', re.I),
    re.compile(r'\b(the (key|central) question is)\b', re.I),
    re.compile(r'\b(single[- ]largest|most important|primary)\b', re.I),
    re.compile(r'\b(franchise|monopoly|duopoly|oligopoly)\b', re.I),
    re.compile(r'\b(pricing power|recurring revenue|subscription|toll|royalt)\b', re.I),
]

# Falsifiability: thesis-breaker is concrete and measurable
_FALSIFIABLE_PATTERNS = [
    re.compile(r'\d+%'),                                    # percentage threshold
    re.compile(r'\$\d+'),                                   # dollar threshold
    re.compile(r'\d+ (quarter|year|month|week)s?'),          # time bound
    re.compile(r'\b(below|above|exceeds?|falls? below)\b', re.I),  # comparison
    re.compile(r'\b(decline|drop|rise|increase) .{0,20}\d'),  # quantified change
    re.compile(r'\b(market share|penetration|adoption)\b', re.I),  # measurable KPI
    re.compile(r'\b(revenue|margin|earnings|FCF|EBITDA)\b', re.I),  # financial metric
    re.compile(r'\b(patent|approval|ruling|legislation)\b', re.I),  # binary event
    re.compile(r'\bQ[1-4]\b'),                               # quarter reference
    re.compile(r'\b20\d{2}\b'),                              # year reference
]

_VAGUE_BREAKER_PATTERNS = [
    re.compile(r'\bmonitor (competition|developments?|market)\b', re.I),
    re.compile(r'\bchanging (market|competitive) (conditions|dynamics|landscape)\b', re.I),
    re.compile(r'\b(general|overall) (economic|market) (conditions|environment)\b', re.I),
    re.compile(r'\b(increased|heightened) (competition|regulatory)\b', re.I),
    re.compile(r'\b(challenging|difficult) (environment|backdrop)\b', re.I),
]

# Monitoring: language that creates a practical checklist
_MONITORING_PATTERNS = [
    re.compile(r'\b(renewal rate|churn|retention|NPS)\b', re.I),
    re.compile(r'\b(same[- ]store|comp[- ]store|SSS)\b', re.I),
    re.compile(r'\b(ARPU|ARPA|ASP|ACV|RPU)\b'),
    re.compile(r'\b(DAU|MAU|DAP|subscriber|member)\b', re.I),
    re.compile(r'\b(backlog|book[- ]to[- ]bill|pipeline)\b', re.I),
    re.compile(r'\b(margin|operating margin|gross margin|EBITDA margin)\b', re.I),
    re.compile(r'\b(market share|wallet share|penetration)\b', re.I),
    re.compile(r'\b(guidance|consensus|estimate|revision)\b', re.I),
    re.compile(r'\b(volume|units?|shipments?|deliveries)\b', re.I),
    re.compile(r'\b(pricing|price hike|price increase|ASP)\b', re.I),
    re.compile(r'\b(CapEx|capital expenditure|investment)\b', re.I),
    re.compile(r'\b(free cash flow|FCF|cash conversion)\b', re.I),
    re.compile(r'\b(NIM|net interest margin|NII)\b', re.I),
    re.compile(r'\b(Phase [1-3I-V]+|FDA|approval|readout|trial)\b', re.I),
]


# ---------------------------------------------------------------------------
# Scoring functions
# ---------------------------------------------------------------------------

def _score_actionability(profile) -> Tuple[int, List[str]]:
    """Score whether the profile gives an investor a clear action framework."""
    failures = []

    # Gather action-relevant text
    risks = getattr(profile, "major_risks", []) or []
    rate = getattr(profile, "rate_sensitivity_note", "") or ""
    recession = getattr(profile, "recession_behavior", "") or ""
    valuation = getattr(profile, "valuation_style", "") or ""
    bm = getattr(profile, "business_model", "") or ""
    all_text = " ".join([bm, rate, recession, valuation] + risks)

    # Count action signals
    action_count = sum(len(p.findall(all_text)) for p in _ACTION_PATTERNS)

    # Score components
    score = 0
    score += min(30, action_count * 5)                  # action language
    score += 20 if len(valuation) > 100 else 0          # valuation framing
    score += 15 if len(rate) > 100 else 0               # rate sensitivity
    score += 15 if len(recession) > 100 else 0          # recession context
    score += 10 if len(risks) >= 3 else 0               # risk enumeration
    score += 10 if any(len(r) > 80 for r in risks) else 0  # detailed risks

    if action_count == 0:
        failures.append("NO_ACTION: zero action-oriented language in profile")
    if len(valuation) < 50:
        failures.append("NO_VALUATION: no valuation framing for decision context")

    return min(100, score), failures


def _score_thesis_clarity(profile) -> Tuple[int, List[str]]:
    """Score whether the profile has one dominant investment idea."""
    failures = []
    bm = getattr(profile, "business_model", "") or ""
    drivers = getattr(profile, "primary_revenue_drivers", []) or []

    # Thesis signal count
    thesis_signals = sum(len(p.findall(bm)) for p in _THESIS_SIGNALS)

    # Business model conciseness (a clear thesis is expressible concisely)
    bm_sentences = len(re.findall(r'[.!?]+', bm))

    # Revenue driver concentration — does one driver dominate?
    driver_has_pct = sum(1 for d in drivers if re.search(r'\d+%', d))

    score = 0
    score += min(30, thesis_signals * 8)                # thesis language
    score += 25 if bm_sentences <= 4 else 15 if bm_sentences <= 6 else 5  # conciseness
    score += 20 if driver_has_pct >= 1 else 0           # quantified drivers
    score += 15 if len(drivers) >= 3 else 5             # driver enumeration
    score += 10 if len(bm) >= 150 else 0                # substantive depth

    if thesis_signals == 0 and "monopoly" not in bm.lower() and "duopoly" not in bm.lower():
        failures.append("UNCLEAR_THESIS: no dominant investment idea signaled")

    return min(100, score), failures


def _score_thesis_breaker_quality(profile, uncertainty_drivers: List[str]) -> Tuple[int, List[str]]:
    """Score whether thesis-change triggers are concrete and falsifiable."""
    failures = []
    risks = getattr(profile, "major_risks", []) or []
    all_breakers = risks + uncertainty_drivers

    if not all_breakers:
        return 10, ["NO_BREAKERS: no risks or uncertainty drivers defined"]

    all_text = " ".join(all_breakers)

    # Falsifiability signals
    falsifiable_count = sum(len(p.findall(all_text)) for p in _FALSIFIABLE_PATTERNS)

    # Vague language count
    vague_count = sum(len(p.findall(all_text)) for p in _VAGUE_BREAKER_PATTERNS)

    # Per-breaker specificity
    specific_breakers = 0
    for b in all_breakers:
        b_falsifiable = sum(len(p.findall(b)) for p in _FALSIFIABLE_PATTERNS)
        if b_falsifiable >= 2:
            specific_breakers += 1

    specificity_rate = specific_breakers / len(all_breakers) if all_breakers else 0

    score = 0
    score += min(35, falsifiable_count * 3)             # falsifiable anchors
    score += min(25, specificity_rate * 30)             # per-breaker specificity
    score += 20 if len(uncertainty_drivers) >= 2 else 0 # has ticker-specific drivers
    score += 10 if len(risks) >= 3 else 0               # enough risks
    score += 10 if vague_count == 0 else 0              # no vague language

    if vague_count >= 2:
        failures.append(f"VAGUE_BREAKERS: {vague_count} vague thesis-change triggers")
    if specificity_rate < 0.3:
        failures.append(f"UNFALSIFIABLE: only {specificity_rate:.0%} of breakers are measurable")

    return min(100, score), failures


def _score_risk_prioritization(profile, benchmark_entry: Optional[BenchmarkEntry]) -> Tuple[int, List[str]]:
    """Score whether risks are ordered by actual importance."""
    failures = []
    risks = getattr(profile, "major_risks", []) or []

    if len(risks) < 2:
        return 30, ["FEW_RISKS: fewer than 2 risks to evaluate ordering"]

    score = 50  # base score for having ordered risks

    # Check if risk #1 is the longest/most detailed (proxy for most important)
    if len(risks[0]) >= max(len(r) for r in risks) * 0.7:
        score += 15

    # If we have a benchmark entry, check alignment
    if benchmark_entry and benchmark_entry.thesis_breakers:
        primary_breaker = benchmark_entry.thesis_breakers[0].lower()
        risk1 = risks[0].lower()
        # Check if risk #1 overlaps with the benchmark's primary thesis-breaker
        breaker_words = set(primary_breaker.split()) - {"the", "a", "an", "of", "in", "and", "or", "is", "to", "for", "from"}
        risk1_words = set(risk1.split()) - {"the", "a", "an", "of", "in", "and", "or", "is", "to", "for", "from"}
        overlap = len(breaker_words & risk1_words) / max(len(breaker_words), 1)
        if overlap >= 0.2:
            score += 20
        else:
            score += 5

    # Penalize if all risks are similar length (suggests no prioritization)
    if risks:
        lengths = [len(r) for r in risks]
        avg = sum(lengths) / len(lengths)
        variance = sum((l - avg) ** 2 for l in lengths) / len(lengths)
        if variance > 500:
            score += 15  # good variance = some risks more detailed

    return min(100, score), failures


def _score_monitoring_quality(profile, uncertainty_drivers: List[str]) -> Tuple[int, List[str]]:
    """Score whether the profile generates a practical monitoring checklist."""
    failures = []
    metrics = getattr(profile, "key_metrics", []) or []
    all_text = " ".join(metrics + uncertainty_drivers)

    # Monitoring signal count
    monitoring_count = sum(len(p.findall(all_text)) for p in _MONITORING_PATTERNS)

    score = 0
    score += min(40, monitoring_count * 5)              # monitoring signals
    score += min(30, len(metrics) * 5)                  # key metrics count
    score += 15 if len(uncertainty_drivers) >= 2 else 0 # uncertainty drivers
    score += 15 if any(re.search(r'\d', m) for m in metrics) else 0  # quantified metrics

    if len(metrics) < 3:
        failures.append("WEAK_MONITORING: fewer than 3 key metrics")
    if monitoring_count < 2:
        failures.append("NO_CHECKLIST: insufficient monitoring signals for quarterly tracking")

    return min(100, score), failures


def _score_consistency(profile, durability: float) -> Tuple[int, List[str]]:
    """Score whether all fields reinforce the same investment thesis."""
    failures = []
    score = 60  # base

    moats = getattr(profile, "moat_type", []) or []
    cyclicality = getattr(profile, "earnings_cyclicality", "") or ""
    risks = getattr(profile, "major_risks", []) or []
    drivers = getattr(profile, "primary_revenue_drivers", []) or []
    bm = (getattr(profile, "business_model", "") or "").lower()
    recession = (getattr(profile, "recession_behavior", "") or "").lower()
    advantages = getattr(profile, "competitive_advantages", []) or []

    # 1. High durability should have strong moats
    if durability >= 0.70 and len(moats) >= 2:
        score += 10
    elif durability < 0.40 and len(moats) <= 1:
        score += 10
    elif durability >= 0.70 and len(moats) <= 1:
        score -= 10
        failures.append("INCONSISTENT: high durability but weak moat set")

    # 2. Non-cyclical + recession-resilient = consistent
    if cyclicality == "non_cyclical":
        resilient_words = ["sticky", "stable", "resilient", "essential", "non-discretionary",
                          "continued", "protected", "inelastic", "grew", "growth"]
        if any(w in recession for w in resilient_words):
            score += 10
    elif cyclicality == "highly_cyclical":
        cyclical_words = ["decline", "drop", "swing", "volatile", "cyclical", "sensitive"]
        if any(w in recession for w in cyclical_words):
            score += 10

    # 3. Drivers should reference moat sources
    drivers_text = " ".join(d.lower() for d in drivers)
    moat_in_drivers = False
    for moat in moats:
        moat_keywords = {
            "network_effect": ["network", "platform", "marketplace", "user"],
            "brand": ["brand", "premium", "loyalty", "trust"],
            "switching_cost": ["switching", "embedded", "integrated", "locked"],
            "scale_economy": ["scale", "cost advantage", "largest", "#1"],
            "regulatory": ["regulatory", "licensed", "approved", "mandate"],
            "patent": ["patent", "IP", "proprietary", "pipeline"],
            "data_advantage": ["data", "algorithm", "AI", "analytics"],
            "natural_monopoly": ["monopoly", "only", "sole", "exclusive"],
        }
        if moat in moat_keywords:
            if any(kw in drivers_text for kw in moat_keywords[moat]):
                moat_in_drivers = True
                break

    if moat_in_drivers:
        score += 10

    # 4. Advantages should align with moat_type
    if len(advantages) >= 3 and len(moats) >= 2:
        score += 10

    return min(100, score), failures


# ---------------------------------------------------------------------------
# Decision differentiation (cohort-level)
# ---------------------------------------------------------------------------

def _compute_differentiation(profiles_db, durability_scores: Dict[str, float]) -> Dict[str, int]:
    """Score whether different-conviction companies produce different advice."""
    # Group by durability tier
    tiers: Dict[str, List[str]] = {"high": [], "mid": [], "low": []}
    for ticker, dur in durability_scores.items():
        if dur >= 0.65:
            tiers["high"].append(ticker)
        elif dur >= 0.45:
            tiers["mid"].append(ticker)
        else:
            tiers["low"].append(ticker)

    def _profile_text(ticker: str) -> str:
        p = profiles_db.get(ticker)
        if not p:
            return ""
        return " ".join([
            getattr(p, "business_model", "") or "",
            " ".join(getattr(p, "major_risks", []) or []),
            getattr(p, "valuation_style", "") or "",
        ])

    # Compute average intra-tier similarity
    def _avg_similarity(tickers: List[str]) -> float:
        if len(tickers) < 2:
            return 0.0
        total = 0.0
        count = 0
        sample = tickers[:20]  # cap for performance
        for i in range(len(sample)):
            for j in range(i + 1, len(sample)):
                t1 = _profile_text(sample[i])
                t2 = _profile_text(sample[j])
                if t1 and t2:
                    total += SequenceMatcher(None, t1[:500], t2[:500]).ratio()
                    count += 1
        return total / count if count > 0 else 0.0

    high_sim = _avg_similarity(tiers["high"])
    low_sim = _avg_similarity(tiers["low"])
    cross_sim_pairs = []
    for h in tiers["high"][:10]:
        for l in tiers["low"][:10]:
            t1 = _profile_text(h)
            t2 = _profile_text(l)
            if t1 and t2:
                cross_sim_pairs.append(SequenceMatcher(None, t1[:500], t2[:500]).ratio())

    cross_sim = sum(cross_sim_pairs) / len(cross_sim_pairs) if cross_sim_pairs else 0.5

    # Good differentiation: cross-tier similarity should be LOW
    # Score: lower cross_sim = higher differentiation
    diff_score = int(max(0, min(100, (1.0 - cross_sim) * 120)))

    scores = {}
    for ticker in durability_scores:
        scores[ticker] = diff_score  # same score for all (cohort-level metric)

    return scores


# ---------------------------------------------------------------------------
# Master scoring
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def scoring_context():
    from app.services.conviction_modeler import _compute_structured_durability, _TICKER_UNCERTAINTY_DRIVERS
    from app.services.company_knowledge import _KNOWLEDGE_DB

    durability = {}
    for ticker, p in _KNOWLEDGE_DB.items():
        durability[ticker] = _compute_structured_durability(p)

    diff_scores = _compute_differentiation(_KNOWLEDGE_DB, durability)

    all_scores: Dict[str, DecisionScore] = {}
    for ticker, profile in _KNOWLEDGE_DB.items():
        ds = DecisionScore(ticker=ticker, company=profile.company_name)
        unc_drivers = _TICKER_UNCERTAINTY_DRIVERS.get(ticker, [])
        benchmark_entry = BENCHMARK.get(ticker)
        dur = durability[ticker]

        act_score, act_fails = _score_actionability(profile)
        ds.actionability = act_score
        ds.failures.extend(act_fails)

        tc_score, tc_fails = _score_thesis_clarity(profile)
        ds.thesis_clarity = tc_score
        ds.failures.extend(tc_fails)

        ds.differentiation = diff_scores.get(ticker, 50)

        tb_score, tb_fails = _score_thesis_breaker_quality(profile, unc_drivers)
        ds.thesis_breaker_quality = tb_score
        ds.failures.extend(tb_fails)

        rp_score, rp_fails = _score_risk_prioritization(profile, benchmark_entry)
        ds.risk_prioritization = rp_score
        ds.failures.extend(rp_fails)

        mq_score, mq_fails = _score_monitoring_quality(profile, unc_drivers)
        ds.monitoring_quality = mq_score
        ds.failures.extend(mq_fails)

        con_score, con_fails = _score_consistency(profile, dur)
        ds.consistency = con_score
        ds.failures.extend(con_fails)

        all_scores[ticker] = ds

    return all_scores, durability


# ═══════════════════════════════════════════════════════════════════════════
# Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestActionability:
    def test_mean_above_threshold(self, scoring_context):
        scores, _ = scoring_context
        vals = [s.actionability for s in scores.values()]
        mean = sum(vals) / len(vals)
        assert mean >= 50, f"Mean actionability {mean:.1f} < 50"

    def test_no_zero_actionability(self, scoring_context):
        scores, _ = scoring_context
        zeros = [(t, s.actionability) for t, s in scores.items() if s.actionability < 15]
        assert len(zeros) == 0, (
            f"{len(zeros)} profiles have near-zero actionability:\n"
            + "\n".join(f"  {t}: {s}" for t, s in zeros[:10])
        )


class TestThesisClarity:
    def test_mean_above_threshold(self, scoring_context):
        scores, _ = scoring_context
        vals = [s.thesis_clarity for s in scores.values()]
        mean = sum(vals) / len(vals)
        assert mean >= 40, f"Mean thesis clarity {mean:.1f} < 40"


class TestDifferentiation:
    def test_cross_tier_differentiation(self, scoring_context):
        scores, _ = scoring_context
        diff_val = list(scores.values())[0].differentiation
        assert diff_val >= 50, f"Cross-tier differentiation {diff_val} < 50 (profiles too similar across tiers)"


class TestThesisBreakerQuality:
    def test_mean_above_threshold(self, scoring_context):
        scores, _ = scoring_context
        vals = [s.thesis_breaker_quality for s in scores.values()]
        mean = sum(vals) / len(vals)
        assert mean >= 35, f"Mean thesis-breaker quality {mean:.1f} < 35"

    def test_benchmark_companies_have_good_breakers(self, scoring_context):
        scores, _ = scoring_context
        benchmark_scores = [s.thesis_breaker_quality for t, s in scores.items() if t in BENCHMARK]
        mean = sum(benchmark_scores) / len(benchmark_scores) if benchmark_scores else 0
        assert mean >= 40, f"Benchmark company thesis-breaker mean {mean:.1f} < 40"


class TestRiskPrioritization:
    def test_mean_above_threshold(self, scoring_context):
        scores, _ = scoring_context
        vals = [s.risk_prioritization for s in scores.values()]
        mean = sum(vals) / len(vals)
        assert mean >= 50, f"Mean risk prioritization {mean:.1f} < 50"


class TestMonitoringQuality:
    def test_mean_above_threshold(self, scoring_context):
        scores, _ = scoring_context
        vals = [s.monitoring_quality for s in scores.values()]
        mean = sum(vals) / len(vals)
        assert mean >= 35, f"Mean monitoring quality {mean:.1f} < 35"

    def test_all_profiles_have_metrics(self, scoring_context):
        scores, _ = scoring_context
        no_metrics = [(t, s.monitoring_quality) for t, s in scores.items()
                      if s.monitoring_quality < 15]
        assert len(no_metrics) == 0, (
            f"{len(no_metrics)} profiles have <15 monitoring quality:\n"
            + "\n".join(f"  {t}: {s}" for t, s in no_metrics[:10])
        )


class TestRecommendationConsistency:
    def test_mean_above_threshold(self, scoring_context):
        scores, _ = scoring_context
        vals = [s.consistency for s in scores.values()]
        mean = sum(vals) / len(vals)
        assert mean >= 55, f"Mean consistency {mean:.1f} < 55"


class TestCompositeDecisionScore:
    def test_mean_composite_above_threshold(self, scoring_context):
        scores, _ = scoring_context
        vals = [s.composite for s in scores.values()]
        mean = sum(vals) / len(vals)
        assert mean >= 45, f"Mean decision usefulness {mean:.1f} < 45"

    def test_no_composite_below_floor(self, scoring_context):
        scores, _ = scoring_context
        floor_fails = [(t, s.composite) for t, s in scores.items() if s.composite < 20]
        assert len(floor_fails) == 0, (
            f"{len(floor_fails)} profiles below composite floor (20):\n"
            + "\n".join(f"  {t}: {s:.1f}" for t, s in
                        sorted(floor_fails, key=lambda x: x[1]))
        )


# ═══════════════════════════════════════════════════════════════════════════
# Report
# ═══════════════════════════════════════════════════════════════════════════

class TestDecisionUsefulnessReport:
    def test_generate_report(self, scoring_context):
        scores, durability = scoring_context

        report = []
        report.append("\n" + "=" * 100)
        report.append("V3 DECISION USEFULNESS REPORT")
        report.append("=" * 100)

        ranked = sorted(scores.items(), key=lambda x: x[1].composite, reverse=True)

        # ── Per-company table ─────────────────────────────────────────
        report.append(f"\n{'Rk':>3}  {'Ticker':>6}  {'Action':>6}  {'Thesis':>6}  {'Diff':>4}  "
                      f"{'Breaker':>7}  {'RiskPr':>6}  {'Monitor':>7}  {'Consist':>7}  {'COMP':>6}  Dur   Failures")
        report.append("-" * 100)

        for i, (ticker, s) in enumerate(ranked, 1):
            dur = durability.get(ticker, 0)
            fail_short = "; ".join(s.failures[:1]) if s.failures else "—"
            if len(fail_short) > 30:
                fail_short = fail_short[:30] + "..."
            report.append(
                f"  {i:2d}  {ticker:>6}  {s.actionability:6.0f}  {s.thesis_clarity:6.0f}  {s.differentiation:4.0f}  "
                f"{s.thesis_breaker_quality:7.0f}  {s.risk_prioritization:6.0f}  {s.monitoring_quality:7.0f}  "
                f"{s.consistency:7.0f}  {s.composite:6.1f}  {dur:.2f}  {fail_short}"
            )

        # ── Dimension statistics ──────────────────────────────────────
        report.append(f"\n{'─' * 100}")
        report.append("DIMENSION STATISTICS")
        report.append(f"{'─' * 100}")

        dims = [
            ("Actionability", lambda s: s.actionability),
            ("Thesis Clarity", lambda s: s.thesis_clarity),
            ("Differentiation", lambda s: s.differentiation),
            ("Thesis-Breaker", lambda s: s.thesis_breaker_quality),
            ("Risk Prioritization", lambda s: s.risk_prioritization),
            ("Monitoring", lambda s: s.monitoring_quality),
            ("Consistency", lambda s: s.consistency),
            ("COMPOSITE", lambda s: s.composite),
        ]
        for name, getter in dims:
            vals = [getter(s) for s in scores.values()]
            mean = sum(vals) / len(vals)
            report.append(f"  {name:22s}  mean={mean:5.1f}  min={min(vals):5.1f}  max={max(vals):5.1f}")

        # ── Quality tiers ─────────────────────────────────────────────
        report.append(f"\n{'─' * 100}")
        report.append("QUALITY TIERS")
        report.append(f"{'─' * 100}")

        tiers = {"Institutional (≥70)": [], "Professional (50-69)": [],
                 "Adequate (35-49)": [], "Weak (20-34)": [], "Insufficient (<20)": []}
        for ticker, s in scores.items():
            c = s.composite
            if c >= 70: tiers["Institutional (≥70)"].append(ticker)
            elif c >= 50: tiers["Professional (50-69)"].append(ticker)
            elif c >= 35: tiers["Adequate (35-49)"].append(ticker)
            elif c >= 20: tiers["Weak (20-34)"].append(ticker)
            else: tiers["Insufficient (<20)"].append(ticker)

        for tier, tickers in tiers.items():
            pct = len(tickers) * 100 // len(scores)
            report.append(f"  {tier:30s}  {len(tickers):3d}  ({pct:2d}%)")
            if 0 < len(tickers) <= 15:
                report.append(f"    {', '.join(sorted(tickers))}")

        # ── Failure taxonomy ──────────────────────────────────────────
        report.append(f"\n{'─' * 100}")
        report.append("FAILURE TAXONOMY")
        report.append(f"{'─' * 100}")

        failure_counts: Counter = Counter()
        for s in scores.values():
            for f in s.failures:
                category = f.split(":")[0]
                failure_counts[category] += 1

        total_f = sum(failure_counts.values())
        for cat, count in failure_counts.most_common():
            pct = count * 100 // max(total_f, 1)
            report.append(f"  {cat:25s}  {count:4d}  ({pct:2d}%)")

        report.append(f"\n  Total failure instances:  {total_f}")
        report.append(f"  Profiles with 0 failures: {sum(1 for s in scores.values() if not s.failures)}")

        # ── Bottom 10 ─────────────────────────────────────────────────
        report.append(f"\n{'─' * 100}")
        report.append("BOTTOM 10 — HIGHEST ROI IMPROVEMENTS")
        report.append(f"{'─' * 100}")

        for ticker, s in ranked[-10:]:
            report.append(f"\n  {ticker} ({s.company}) — composite={s.composite:.1f}")
            weakest_dim = min(
                [("Actionability", s.actionability), ("Thesis", s.thesis_clarity),
                 ("Breaker", s.thesis_breaker_quality), ("Monitor", s.monitoring_quality),
                 ("Consistency", s.consistency)],
                key=lambda x: x[1]
            )
            report.append(f"    Weakest dimension: {weakest_dim[0]} ({weakest_dim[1]})")
            if s.failures:
                for f in s.failures[:3]:
                    report.append(f"    - {f}")

        # ── Highest ROI improvements ──────────────────────────────────
        report.append(f"\n{'─' * 100}")
        report.append("HIGHEST ROI IMPROVEMENTS")
        report.append(f"{'─' * 100}")

        # Find dimensions where improving the floor would have the most impact
        dim_means = {}
        for name, getter in dims[:-1]:
            vals = [getter(s) for s in scores.values()]
            dim_means[name] = sum(vals) / len(vals)

        sorted_dims = sorted(dim_means.items(), key=lambda x: x[1])
        for name, mean in sorted_dims[:3]:
            report.append(f"  #{sorted_dims.index((name, mean))+1} {name}: mean={mean:.1f} — improving this dimension has highest ROI")

        # ── Verdict ───────────────────────────────────────────────────
        composites = [s.composite for s in scores.values()]
        mean_comp = sum(composites) / len(composites)
        inst_count = sum(1 for c in composites if c >= 70)
        insuf_count = sum(1 for c in composites if c < 20)

        report.append(f"\n{'=' * 100}")
        if mean_comp >= 65 and insuf_count == 0:
            verdict = "PASS — Institutional grade"
        elif mean_comp >= 55 and insuf_count <= 3:
            verdict = "CONDITIONAL PASS — Professional grade"
        elif mean_comp >= 45:
            verdict = "MARGINAL — Adequate for MVP"
        else:
            verdict = "FAIL — Decision usefulness insufficient"

        report.append(f"VERDICT: {verdict}")
        report.append(f"  Mean decision usefulness: {mean_comp:.1f}")
        report.append(f"  Institutional tier:       {inst_count}/{len(scores)} ({inst_count*100//len(scores)}%)")
        report.append(f"  Insufficient tier:        {insuf_count}/{len(scores)} ({insuf_count*100//len(scores)}%)")
        report.append("=" * 100)

        print("\n".join(report))
        assert True
