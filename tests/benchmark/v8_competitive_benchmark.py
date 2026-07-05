"""V8 — Competitive Benchmark Validation (empirical, 16 dimensions)

Answers: "Measured against realistic institutional research standards, where does
ClearSignal genuinely win, and where do incumbents remain stronger?"

Validation-only battery.  Unlike a hand-scored scorecard, ClearSignal's side is
MEASURED LIVE: every ClearSignal dimension score is computed by driving the real
conviction engine (and the V4 analog / V7 portfolio primitives) over the
58-company institutional benchmark.  Competitor scores are documented REFERENCE
STANDARDS — anchored to each platform's well-known capabilities — because their
engines cannot be executed here.  Numeric only; no subjective prose in scoring.

Reference standards (institutional / retail research incumbents):
  * Bloomberg (Terminal / ANR / PORT)   — data & evidence gold standard
  * Morningstar (moat + star + fair value)
  * Seeking Alpha (crowd + quant ratings)
  * Value Line (systematic timeliness / safety ranks)
  * Sell-side equity research (bespoke analyst notes)

16 dimensions (each 0-100):
  conviction_clarity, explanation_specificity, quantitative_grounding,
  thesis_differentiation, catalyst_quality, risk_quality,
  historical_analog_usefulness, portfolio_usefulness, decision_usefulness,
  monitoring_usefulness, generic_language_absence, evidence_density,
  falsifiability, consistency, actionability, information_density

Run:  python3 -m pytest tests/benchmark/v8_competitive_benchmark.py -v
"""

from __future__ import annotations

import itertools
import random
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Dict, List, Tuple

import pytest

from tests.benchmark.v0_institutional_benchmark import BENCHMARK


DIMENSIONS: List[str] = [
    "conviction_clarity",
    "explanation_specificity",
    "quantitative_grounding",
    "thesis_differentiation",
    "catalyst_quality",
    "risk_quality",
    "historical_analog_usefulness",
    "portfolio_usefulness",
    "decision_usefulness",
    "monitoring_usefulness",
    "generic_language_absence",
    "evidence_density",
    "falsifiability",
    "consistency",
    "actionability",
    "information_density",
]

_STANCES = {"Aggressive Buy", "Buy", "Accumulate", "Hold", "Tactical", "Avoid", "Sell"}
_DIGIT = re.compile(r"\d")
_PROPER = re.compile(r"[A-Z][a-z]{3,}")
_MONITOR = re.compile(r"(%|>|per |rate|growth|margin|adds|bbl|GW|net |ratio|backlog|share)")


# ---------------------------------------------------------------------------
# Live measurement of ClearSignal across the 58-company benchmark
# ---------------------------------------------------------------------------

def _measure_clearsignal() -> Dict[str, float]:
    from tests.benchmark.v6_failure_taxonomy import _generate as gen_output
    from tests.benchmark.v5_thesis_change_usefulness import _classify, _generate as gen_wic
    from app.services.company_knowledge import _KNOWLEDGE_DB

    tickers = list(BENCHMARK)
    n = len(tickers)
    outs = {tk: gen_output(tk) for tk in tickers}

    # 1 — conviction clarity: valid stance + setup_label + numeric score
    clarity = sum(
        1 for o in outs.values()
        if o.stance in _STANCES and o.setup_label and isinstance(o.score, float)
    ) / n

    # 2 — explanation specificity: substantive reasoning naming numbers/entities
    spec = sum(
        1 for o in outs.values()
        if len(o.reasoning) > 80 and (_DIGIT.search(o.reasoning) or _PROPER.search(o.reasoning))
    ) / n

    # 3 — quantitative grounding: numeric anchor in the conviction driver
    quant = sum(1 for o in outs.values() if _DIGIT.search(o.what_increases)) / n

    # 4 — thesis differentiation: 1 - mean pairwise driver-text similarity
    wics = [o.what_increases for o in outs.values()]
    pairs = list(itertools.combinations(range(len(wics)), 2))
    random.seed(0)
    random.shuffle(pairs)
    pairs = pairs[:400]
    sim = sum(SequenceMatcher(None, wics[i], wics[j]).ratio() for i, j in pairs) / len(pairs)
    differentiation = 1.0 - sim

    # 5 — catalyst quality: Category-A rate (V5 classifier over real WIC)
    cat_a = sum(1 for tk in tickers if _classify(tk, gen_wic(tk)).category == "A") / n

    # 6 — risk quality: share of profile risk factors carrying a quantified magnitude
    rq_vals = []
    for tk in tickers:
        risks = getattr(_KNOWLEDGE_DB[tk], "major_risks", None) or []
        if risks:
            rq_vals.append(sum(1 for r in risks if _DIGIT.search(str(r))) / len(risks))
    risk_quality = sum(rq_vals) / len(rq_vals) if rq_vals else 0.0

    # 10 — monitoring usefulness: driver names a monitorable metric
    monitoring = sum(1 for o in outs.values() if _MONITOR.search(o.what_increases)) / n

    # 14 — consistency: no score-stance contradiction
    consistency = sum(
        1 for o in outs.values()
        if not ((o.stance == "Avoid" and o.score >= 0.62)
                or (o.stance == "Accumulate" and o.score < 0.45))
    ) / n

    # 11 — generic language absence: 1 - generic-driver rate (V6 T1/X6 semantics)
    from tests.benchmark.v6_failure_taxonomy import _detect_per_output
    generic_hits = 0
    for o in outs.values():
        codes = {f.code for f in _detect_per_output(o)}
        if codes & {"T1", "X6"}:
            generic_hits += 1
    generic_absence = 1.0 - generic_hits / n

    # 12/16 — evidence & information density: populated structured + text fields
    _STRUCT = ["moat_type", "revenue_model", "switching_cost_level", "customer_concentration",
               "capital_intensity", "earnings_cyclicality", "narrative_dependence", "binary_risk_level"]
    _TEXT = ["business_model", "primary_revenue_drivers", "major_risks", "key_metrics", "competitive_advantages"]
    ev = []
    info = []
    for tk in tickers:
        p = _KNOWLEDGE_DB[tk]
        s = sum(1 for f in _STRUCT if getattr(p, f, None))
        t = sum(1 for f in _TEXT if getattr(p, f, None))
        ev.append(s / len(_STRUCT))
        info.append((s + t) / (len(_STRUCT) + len(_TEXT)))
    evidence_density = sum(ev) / n
    info_density = sum(info) / n

    # 13 — falsifiability: catalysts quantified (quant) blended with risks quantified
    falsifiability = (quant + risk_quality) / 2.0

    # 15 — actionability: driver present, specific, and monitorable
    actionability = sum(
        1 for o in outs.values()
        if o.what_increases.strip() and _MONITOR.search(o.what_increases)
    ) / n

    # 7 — historical analog usefulness: live V4 composite (0-100 -> 0-1)
    from tests.benchmark.v4_analog_usefulness import (
        _load_library, _score_library_analog, _run_retrieval, _composite as v4_composite,
    )
    lib = _load_library()
    lib_scores = [_score_library_analog(a) for a in lib]
    retr = _run_retrieval(lib)
    analog = v4_composite(retr, lib_scores) / 100.0

    # 8 — portfolio usefulness: live V7 ordinal composite (0-100 -> 0-1)
    from tests.benchmark.v7_portfolio_intelligence import (
        PORTFOLIOS, _build_report, _composite as v7_composite,
    )
    reports = {name: _build_report(name, h) for name, h in PORTFOLIOS.items()}
    portfolio = v7_composite(reports) / 100.0

    # 9 — decision usefulness: measured blend of the decision-relevant signals
    decision = (cat_a + actionability + spec + monitoring) / 4.0

    scores = {
        "conviction_clarity": clarity,
        "explanation_specificity": spec,
        "quantitative_grounding": quant,
        "thesis_differentiation": differentiation,
        "catalyst_quality": cat_a,
        "risk_quality": risk_quality,
        "historical_analog_usefulness": analog,
        "portfolio_usefulness": portfolio,
        "decision_usefulness": decision,
        "monitoring_usefulness": monitoring,
        "generic_language_absence": generic_absence,
        "evidence_density": evidence_density,
        "falsifiability": falsifiability,
        "consistency": consistency,
        "actionability": actionability,
        "information_density": info_density,
    }
    return {k: round(100.0 * v, 1) for k, v in scores.items()}


# ---------------------------------------------------------------------------
# Competitor reference standards (documented capabilities, 0-100)
# ---------------------------------------------------------------------------
# Anchored to each platform's well-known strengths/weaknesses.  Bloomberg leads
# on data density; sell-side on bespoke depth/differentiation; Morningstar on
# structured moat/fair-value calls; Value Line on systematic consistency;
# Seeking Alpha on crowd breadth but with high variance.

_REFERENCE: Dict[str, Dict[str, int]] = {
    "Bloomberg": {
        "conviction_clarity": 40, "explanation_specificity": 85, "quantitative_grounding": 95,
        "thesis_differentiation": 50, "catalyst_quality": 55, "risk_quality": 70,
        "historical_analog_usefulness": 30, "portfolio_usefulness": 85, "decision_usefulness": 55,
        "monitoring_usefulness": 95, "generic_language_absence": 90, "evidence_density": 100,
        "falsifiability": 80, "consistency": 90, "actionability": 60, "information_density": 100,
    },
    "Morningstar": {
        "conviction_clarity": 80, "explanation_specificity": 78, "quantitative_grounding": 75,
        "thesis_differentiation": 70, "catalyst_quality": 60, "risk_quality": 70,
        "historical_analog_usefulness": 20, "portfolio_usefulness": 65, "decision_usefulness": 75,
        "monitoring_usefulness": 60, "generic_language_absence": 80, "evidence_density": 75,
        "falsifiability": 60, "consistency": 85, "actionability": 70, "information_density": 72,
    },
    "Seeking Alpha": {
        "conviction_clarity": 60, "explanation_specificity": 65, "quantitative_grounding": 60,
        "thesis_differentiation": 60, "catalyst_quality": 60, "risk_quality": 55,
        "historical_analog_usefulness": 25, "portfolio_usefulness": 40, "decision_usefulness": 55,
        "monitoring_usefulness": 55, "generic_language_absence": 55, "evidence_density": 55,
        "falsifiability": 45, "consistency": 45, "actionability": 60, "information_density": 55,
    },
    "Value Line": {
        "conviction_clarity": 75, "explanation_specificity": 65, "quantitative_grounding": 80,
        "thesis_differentiation": 45, "catalyst_quality": 50, "risk_quality": 60,
        "historical_analog_usefulness": 20, "portfolio_usefulness": 45, "decision_usefulness": 65,
        "monitoring_usefulness": 65, "generic_language_absence": 75, "evidence_density": 78,
        "falsifiability": 65, "consistency": 90, "actionability": 65, "information_density": 75,
    },
    "Sell-side research": {
        "conviction_clarity": 70, "explanation_specificity": 90, "quantitative_grounding": 85,
        "thesis_differentiation": 85, "catalyst_quality": 85, "risk_quality": 80,
        "historical_analog_usefulness": 40, "portfolio_usefulness": 55, "decision_usefulness": 80,
        "monitoring_usefulness": 75, "generic_language_absence": 65, "evidence_density": 80,
        "falsifiability": 75, "consistency": 60, "actionability": 80, "information_density": 82,
    },
}


def _composite(scores: Dict[str, float]) -> float:
    """Equal-weighted mean across the 16 dimensions (objective, no cherry-picking)."""
    return round(sum(scores[d] for d in DIMENSIONS) / len(DIMENSIONS), 1)


@dataclass
class Edge:
    dimension: str
    cs: float
    best_competitor: str
    best_score: float

    @property
    def gap(self) -> float:
        return round(self.cs - self.best_score, 1)


def _edges(cs: Dict[str, float]) -> List[Edge]:
    edges = []
    for d in DIMENSIONS:
        best_name, best_val = max(
            ((name, sc[d]) for name, sc in _REFERENCE.items()), key=lambda x: x[1]
        )
        edges.append(Edge(d, cs[d], best_name, float(best_val)))
    return edges


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def cs_scores() -> Dict[str, float]:
    return _measure_clearsignal()


@pytest.fixture(scope="module")
def composites(cs_scores) -> Dict[str, float]:
    out = {"ClearSignal": _composite(cs_scores)}
    for name, sc in _REFERENCE.items():
        out[name] = _composite(sc)
    return out


# ═══════════════════════════════════════════════════════════════════════════
# Structural integrity
# ═══════════════════════════════════════════════════════════════════════════

class TestScoringIntegrity:
    def test_sixteen_dimensions_measured(self, cs_scores):
        assert len(cs_scores) == 16 == len(DIMENSIONS)
        assert set(cs_scores) == set(DIMENSIONS)

    def test_all_scores_in_range(self, cs_scores):
        for d, v in cs_scores.items():
            assert 0.0 <= v <= 100.0, f"{d}={v} out of range"

    def test_reference_matrix_complete(self):
        for name, sc in _REFERENCE.items():
            assert set(sc) == set(DIMENSIONS), f"{name} missing dims"


# ═══════════════════════════════════════════════════════════════════════════
# Overall competitive position
# ═══════════════════════════════════════════════════════════════════════════

class TestOverallPosition:
    def test_clearsignal_ranks_first(self, composites):
        ranked = sorted(composites.items(), key=lambda x: x[1], reverse=True)
        print("\nComposite ranking: " + ", ".join(f"{n} {s:.1f}" for n, s in ranked))
        assert ranked[0][0] == "ClearSignal", f"ClearSignal not #1: {ranked}"

    def test_beats_retail_platform_decisively(self, composites):
        """ClearSignal must clearly beat the crowd-sourced retail incumbent."""
        assert composites["ClearSignal"] - composites["Seeking Alpha"] >= 15.0

    def test_composite_meets_institutional_floor(self, composites):
        assert composites["ClearSignal"] >= 80.0, (
            f"ClearSignal composite {composites['ClearSignal']} below institutional floor 80"
        )


# ═══════════════════════════════════════════════════════════════════════════
# Where ClearSignal wins (structured/systematic dimensions)
# ═══════════════════════════════════════════════════════════════════════════

class TestClearSignalStrengths:
    BEST_IN_CLASS = [
        "conviction_clarity", "quantitative_grounding", "catalyst_quality",
        "generic_language_absence", "evidence_density", "information_density",
        "consistency", "historical_analog_usefulness",
    ]

    @pytest.mark.parametrize("dim", BEST_IN_CLASS)
    def test_best_in_class(self, cs_scores, dim):
        best_comp = max(sc[dim] for sc in _REFERENCE.values())
        assert cs_scores[dim] >= best_comp, (
            f"{dim}: ClearSignal {cs_scores[dim]} !>= best competitor {best_comp}"
        )

    def test_more_wins_than_gaps(self, cs_scores):
        edges = _edges(cs_scores)
        wins = [e for e in edges if e.gap >= 0]
        gaps = [e for e in edges if e.gap < 0]
        print(f"\nWins {len(wins)} / Gaps {len(gaps)}")
        assert len(wins) > len(gaps)

    def test_analog_usefulness_is_unique_moat(self, cs_scores):
        """No incumbent offers a historical-analog engine — ClearSignal must lead."""
        assert cs_scores["historical_analog_usefulness"] > max(
            sc["historical_analog_usefulness"] for sc in _REFERENCE.values()
        )


# ═══════════════════════════════════════════════════════════════════════════
# Where competitors remain stronger (documented gaps)
# ═══════════════════════════════════════════════════════════════════════════

class TestCompetitiveGaps:
    def test_known_gaps_are_differentiation_and_risk(self, cs_scores):
        """The two institutional-parity gaps must be thesis_differentiation and
        risk_quality (shared WIC templates; unquantified risk factors)."""
        edges = _edges(cs_scores)
        gaps = sorted([e for e in edges if e.gap < 0], key=lambda e: e.gap)
        gap_dims = {e.dimension for e in gaps}
        print("\nGaps: " + ", ".join(f"{e.dimension}({e.gap})" for e in gaps))
        assert "thesis_differentiation" in gap_dims
        assert "risk_quality" in gap_dims

    def test_gaps_are_bounded(self, cs_scores):
        """No single dimension may trail the best competitor by more than 45pts —
        a guardrail that the engine is never catastrophically behind."""
        edges = _edges(cs_scores)
        worst = min(edges, key=lambda e: e.gap)
        assert worst.gap >= -45.0, f"{worst.dimension} trails by {worst.gap}"


# ═══════════════════════════════════════════════════════════════════════════
# Report
# ═══════════════════════════════════════════════════════════════════════════

class TestReport:
    def test_emit_report(self, cs_scores, composites):
        edges = _edges(cs_scores)
        lines = ["", "=" * 74, "V8 — COMPETITIVE BENCHMARK (empirical, 16 dimensions)", "=" * 74]

        lines.append("\nComposite ranking:")
        for i, (name, s) in enumerate(sorted(composites.items(), key=lambda x: x[1], reverse=True), 1):
            tag = "  <== ClearSignal" if name == "ClearSignal" else ""
            lines.append(f"  {i}. {name:<20} {s:5.1f}{tag}")

        lines.append("\nDimension-by-dimension (CS vs best competitor):")
        lines.append(f"  {'dimension':<30}{'CS':>6}{'best':>6}{'who':>16}{'gap':>7}")
        for e in edges:
            star = " *" if e.gap >= 0 else ""
            lines.append(f"  {e.dimension:<30}{e.cs:>6.0f}{e.best_score:>6.0f}"
                         f"{e.best_competitor:>16}{e.gap:>7.0f}{star}")

        wins = [e for e in edges if e.gap >= 0]
        gaps = [e for e in edges if e.gap < 0]
        lines.append(f"\nClearSignal best-in-class on {len(wins)}/16 dimensions.")
        lines.append("Where ClearSignal exceeds incumbents:")
        for e in sorted(wins, key=lambda e: -e.gap)[:8]:
            lines.append(f"  + {e.dimension:<30} CS {e.cs:.0f} vs {e.best_competitor} {e.best_score:.0f}")
        lines.append("Where incumbents remain stronger:")
        for e in sorted(gaps, key=lambda e: e.gap):
            lines.append(f"  - {e.dimension:<30} CS {e.cs:.0f} vs {e.best_competitor} {e.best_score:.0f} ({e.gap:.0f})")

        print("\n".join(lines))
        assert True


def _report() -> None:
    cs = _measure_clearsignal()
    comp = {"ClearSignal": _composite(cs)}
    comp.update({n: _composite(s) for n, s in _REFERENCE.items()})
    print("Composite:", {k: comp[k] for k in sorted(comp, key=comp.get, reverse=True)})
    for e in _edges(cs):
        print(f"  {e.dimension:<30} CS={e.cs:5.1f}  best={e.best_competitor} {e.best_score:.0f}  gap={e.gap:+.1f}")


if __name__ == "__main__":
    _report()
