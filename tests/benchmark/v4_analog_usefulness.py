"""V4 — Historical Analog Usefulness Validation

Evaluates whether the historical-analog engine improves analyst understanding
and decision quality.  This is a VALIDATION battery only — it drives the real
retrieval engine (app.evidence_engine) and inspects the real analog library
(app/db/data/historical_analogs.json).  It changes NO production code.

Six dimensions (per the V4 charter):
  1. Relevance      — retrieved analogs share business model / mechanism /
                      risk pattern with the company (engine PRECISION).
  2. Specificity    — analogs cite specific history (numbers, named entity,
                      dates), not generic market commentary.
  3. Explanatory    — `why_relevant` explains WHY the current thesis is
                      fragile/durable via a causal or analogical mapping.
  4. Decision use   — analog carries a monitorable, quantified signal that
                      changes what an analyst would watch.
  5. Bad-analog     — engine avoids cross-sector / misleading analogs, and
                      every library analog self-declares its `disanalogy`.
  6. Coverage       — every benchmark archetype has an appropriate-family
                      analog available (library ceiling) and reachable (recall).

Ground truth: tests/benchmark/v0_institutional_benchmark.py
  (each BenchmarkEntry carries appropriate_analogs / inappropriate_analogs
   AnalogFamily lists whose values are the analog `mechanism` names).

Run:  python3 -m pytest tests/benchmark/v4_analog_usefulness.py -v
"""

from __future__ import annotations

import json
import re
import statistics
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

import pytest

from tests.benchmark.v0_institutional_benchmark import BENCHMARK, BenchmarkEntry


# ---------------------------------------------------------------------------
# Institutional thresholds  (calibrated against the current library/engine;
# `floor` gates CI, `target` documents the enrichment goal — see V4 report)
# ---------------------------------------------------------------------------

THRESH = {
    "precision_floor":       0.50,   # target 0.70 — relevant / retrieved
    "bad_analog_ceiling":    0.10,   # target 0.00 — inappropriate / retrieved
    "specificity_floor":     0.80,   # target 0.90
    "explanatory_floor":     0.65,   # target 0.85
    "monitorable_floor":     0.80,   # target 0.95
    "disanalogy_floor":      0.95,   # target 1.00
    "base_rate_floor":       0.90,   # target 1.00
    "recall_floor":          0.40,   # target 0.70 — companies retrieving >=1
    "composite_floor":       60.0,   # institutional pass
}

_SEED_FILE = (
    Path(__file__).resolve().parents[2]
    / "app" / "db" / "data" / "historical_analogs.json"
)

_NUM_RE = re.compile(r"\d[\d,\.]*\s*(%|bn|billion|bps|days|x|B|M|K)?", re.I)
_NAMED_RE = re.compile(r"[A-Z][a-zA-Z]{2,}|\$\d|\d{4}")   # proper noun / $amount / year
_EXPL_MARKERS = re.compile(
    r"(because|when|rests on|depends|mechanism|structural|precedent|similar|"
    r"same|parallel|faces|carries|shows|identical|risk that|drove|led to|"
    r"caused|forced|requires|demonstrates|illustrates|maps|applies|thesis)",
    re.I,
)

_LEGACY_ENRICHMENT_IDS = {
    "a0000000-0000-4000-8000-000000000024",
    "a0000000-0000-4000-8000-000000000025",
    "a0000000-0000-4000-8000-000000000027",
    "a0000000-0000-4000-8000-000000000040",
    "a0000000-0000-4000-8000-000000000043",
    "a0000000-0000-4000-8000-000000000045",
    "a0000000-0000-4000-8000-000000000053",
    "a0000000-0000-4000-8000-000000000056",
    "a0000000-0000-4000-8000-000000000060",
}


# ---------------------------------------------------------------------------
# Lightweight analog object mirroring the HistoricalAnalog ORM shape the engine
# reads.  We load straight from the seed JSON so the battery needs no DB.
# ---------------------------------------------------------------------------

class _Analog:
    __slots__ = (
        "id", "label", "episode", "entity_ticker", "sector", "business_model",
        "quality_rating", "mechanism", "concern_tags", "valuation_regime",
        "growth_phase", "macro_regime", "event_start", "event_end",
        "drawdown_pct", "time_to_trough_days", "time_to_recover_days",
        "outcome_summary", "reaction_series", "why_relevant", "disanalogy",
        "base_rate_note", "data_confidence", "source_note",
    )

    def __init__(self, rec: dict):
        for k in self.__slots__:
            setattr(self, k, rec.get(k))


def _load_library() -> List[_Analog]:
    recs = json.loads(_SEED_FILE.read_text(encoding="utf-8"))
    return [_Analog(r) for r in recs]


def _make_thesis(e: BenchmarkEntry) -> dict:
    """Deterministic representative thesis for a benchmark company.

    Uses the benchmark's own thesis_breakers as key_risks so the fingerprint's
    mechanism inference reflects the company's genuine fragility surface.
    """
    return {
        "key_risks": list(e.thesis_breakers),
        "bear_thesis": " ".join(e.thesis_breakers),
        "macro_sensitivity": "high" if "cyclical" in e.cyclicality else "moderate",
        "conclusion": e.primary_thesis,
    }


# ---------------------------------------------------------------------------
# Per-analog library-quality scoring
# ---------------------------------------------------------------------------

@dataclass
class AnalogLibraryScore:
    label: str
    specific: bool = False
    explanatory: bool = False
    monitorable: bool = False
    has_disanalogy: bool = False
    has_base_rate: bool = False


def _score_library_analog(a: _Analog) -> AnalogLibraryScore:
    out = a.outcome_summary or ""
    why = a.why_relevant or ""
    dis = a.disanalogy or ""
    base = a.base_rate_note or ""

    # Specificity: outcome cites >=2 quantities AND a named entity/date, len>60
    specific = (
        len(_NUM_RE.findall(out)) >= 2
        and bool(_NAMED_RE.search(out))
        and len(out) > 60
    )

    # Explanatory: substantive why_relevant that draws a causal / analogical map
    explanatory = len(why) >= 80 and (
        bool(_EXPL_MARKERS.search(why)) or len(why) >= 150
    )

    # Monitorable: quantified magnitude/timing AND a base-rate note the analyst
    # can convert into a watch trigger
    monitorable = (
        (a.drawdown_pct is not None or a.time_to_trough_days is not None)
        and len(base) > 20
    )

    return AnalogLibraryScore(
        label=a.label,
        specific=specific,
        explanatory=explanatory,
        monitorable=monitorable,
        has_disanalogy=len(dis) > 20,
        has_base_rate=len(base) > 20,
    )


# ---------------------------------------------------------------------------
# Per-company engine-retrieval result
# ---------------------------------------------------------------------------

@dataclass
class CompanyAnalogResult:
    ticker: str
    company: str
    archetype: str
    appropriate: set = field(default_factory=set)
    inappropriate: set = field(default_factory=set)
    retrieved_mechanisms: List[str] = field(default_factory=list)
    n_retrieved: int = 0
    n_relevant: int = 0       # retrieved mechanism in appropriate set
    n_bad: int = 0            # retrieved mechanism in inappropriate set
    library_has_appropriate: bool = False   # coverage ceiling


def _run_retrieval(analogs: List[_Analog]) -> Dict[str, CompanyAnalogResult]:
    from app.evidence_engine import build_fingerprint, retrieve_historical_analogs
    from app.services.company_knowledge import _KNOWLEDGE_DB

    lib_mechanisms = {a.mechanism for a in analogs}
    out: Dict[str, CompanyAnalogResult] = {}

    for tk, e in BENCHMARK.items():
        appr = {f.value for f in e.appropriate_analogs}
        inappr = {f.value for f in e.inappropriate_analogs}
        r = CompanyAnalogResult(
            ticker=tk,
            company=e.company,
            archetype=e.archetype.value,
            appropriate=appr,
            inappropriate=inappr,
            library_has_appropriate=bool(appr & lib_mechanisms),
        )

        prof = _KNOWLEDGE_DB.get(tk)
        if prof is not None:
            fp = build_fingerprint(
                f"What could break the {e.company} thesis?",
                _make_thesis(e),
                ticker=tk,
                profile=prof,
            )
            retrieved = retrieve_historical_analogs(analogs, fp)
            r.retrieved_mechanisms = [x["mechanism"] for x in retrieved]
            r.n_retrieved = len(retrieved)
            r.n_relevant = sum(1 for m in r.retrieved_mechanisms if m in appr)
            r.n_bad = sum(1 for m in r.retrieved_mechanisms if m in inappr)

        out[tk] = r

    return out


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def library() -> List[_Analog]:
    return _load_library()


@pytest.fixture(scope="module")
def library_scores(library) -> List[AnalogLibraryScore]:
    return [_score_library_analog(a) for a in library]


@pytest.fixture(scope="module")
def retrieval(library) -> Dict[str, CompanyAnalogResult]:
    return _run_retrieval(library)


# ---------------------------------------------------------------------------
# Aggregate helpers
# ---------------------------------------------------------------------------

def _precision(retrieval: Dict[str, CompanyAnalogResult]) -> float:
    tot = sum(r.n_retrieved for r in retrieval.values())
    rel = sum(r.n_relevant for r in retrieval.values())
    return rel / tot if tot else 0.0


def _bad_rate(retrieval: Dict[str, CompanyAnalogResult]) -> float:
    tot = sum(r.n_retrieved for r in retrieval.values())
    bad = sum(r.n_bad for r in retrieval.values())
    return bad / tot if tot else 0.0


def _recall(retrieval: Dict[str, CompanyAnalogResult]) -> float:
    with_prof = [r for r in retrieval.values() if r.n_retrieved or r.library_has_appropriate]
    got = sum(1 for r in retrieval.values() if r.n_retrieved > 0)
    # denominator = companies that COULD retrieve (library has an appropriate family)
    could = sum(1 for r in retrieval.values() if r.library_has_appropriate)
    return got / could if could else 0.0


def _frac(scores, attr) -> float:
    return sum(1 for s in scores if getattr(s, attr)) / len(scores) if scores else 0.0


# ═══════════════════════════════════════════════════════════════════════════
# Dimension 1 — Analog Relevance (engine precision)
# ═══════════════════════════════════════════════════════════════════════════

class TestAnalogRelevance:
    def test_precision_meets_floor(self, retrieval):
        p = _precision(retrieval)
        misses = []
        for r in retrieval.values():
            for m in r.retrieved_mechanisms:
                if m not in r.appropriate:
                    misses.append(f"  {r.ticker}: retrieved '{m}' not in {sorted(r.appropriate)}")
        print(f"\nEngine precision (relevant/retrieved): {p:.1%}  "
              f"(floor {THRESH['precision_floor']:.0%})")
        if misses:
            print("Non-appropriate retrievals:")
            print("\n".join(misses[:15]))
        assert p >= THRESH["precision_floor"], (
            f"Analog precision {p:.1%} below floor {THRESH['precision_floor']:.0%}"
        )

    def test_relevant_companies_have_matching_mechanism(self, retrieval):
        """Companies that retrieve should mostly land >=1 appropriate-family analog."""
        retrievers = [r for r in retrieval.values() if r.n_retrieved > 0]
        good = [r for r in retrievers if r.n_relevant > 0]
        rate = len(good) / len(retrievers) if retrievers else 0.0
        print(f"\nCompanies with >=1 relevant analog among retrievers: "
              f"{len(good)}/{len(retrievers)} = {rate:.0%}")
        assert rate >= 0.50, f"Only {rate:.0%} of retrievers got a relevant analog"


# ═══════════════════════════════════════════════════════════════════════════
# Dimension 2 — Analog Specificity (library)
# ═══════════════════════════════════════════════════════════════════════════

class TestAnalogSpecificity:
    def test_library_specificity(self, library_scores):
        frac = _frac(library_scores, "specific")
        fails = [s.label[:48] for s in library_scores if not s.specific]
        print(f"\nLibrary specificity: {frac:.0%}  (floor {THRESH['specificity_floor']:.0%})")
        if fails:
            print("Non-specific analogs (enrichment targets):")
            for f in fails[:12]:
                print(f"  {f}")
        assert frac >= THRESH["specificity_floor"], (
            f"Specificity {frac:.0%} below floor {THRESH['specificity_floor']:.0%}"
        )


# ═══════════════════════════════════════════════════════════════════════════
# Dimension 3 — Explanatory Value (library)
# ═══════════════════════════════════════════════════════════════════════════

class TestExplanatoryValue:
    def test_library_explanatory(self, library_scores):
        frac = _frac(library_scores, "explanatory")
        fails = [s.label[:48] for s in library_scores if not s.explanatory]
        print(f"\nExplanatory value: {frac:.0%}  (floor {THRESH['explanatory_floor']:.0%})")
        if fails:
            print("Thin why_relevant (enrichment targets):")
            for f in fails[:12]:
                print(f"  {f}")
        assert frac >= THRESH["explanatory_floor"], (
            f"Explanatory {frac:.0%} below floor {THRESH['explanatory_floor']:.0%}"
        )

    def test_legacy_enrichments_remain_specific_explanatory_and_sourced(self, library):
        """Sprint 5G corrections must not regress to vague, unsupported prose."""
        enriched = {a.id: a for a in library if a.id in _LEGACY_ENRICHMENT_IDS}

        assert set(enriched) == _LEGACY_ENRICHMENT_IDS
        for analog in enriched.values():
            score = _score_library_analog(analog)
            assert score.specific, analog.label
            assert score.explanatory, analog.label
            assert "https://" in analog.source_note, analog.label

        completed_operational_windows = {
            "a0000000-0000-4000-8000-000000000027",
            "a0000000-0000-4000-8000-000000000045",
            "a0000000-0000-4000-8000-000000000060",
        }
        for analog_id in completed_operational_windows:
            assert enriched[analog_id].event_end is not None


# ═══════════════════════════════════════════════════════════════════════════
# Dimension 4 — Decision Usefulness (monitorable, quantified signal)
# ═══════════════════════════════════════════════════════════════════════════

class TestDecisionUsefulness:
    def test_library_monitorable(self, library_scores):
        frac = _frac(library_scores, "monitorable")
        print(f"\nMonitorable (quantified + base-rate): {frac:.0%}  "
              f"(floor {THRESH['monitorable_floor']:.0%})")
        assert frac >= THRESH["monitorable_floor"], (
            f"Monitorable {frac:.0%} below floor {THRESH['monitorable_floor']:.0%}"
        )

    def test_base_rate_coverage(self, library_scores):
        frac = _frac(library_scores, "has_base_rate")
        print(f"\nBase-rate note present: {frac:.0%}  (floor {THRESH['base_rate_floor']:.0%})")
        assert frac >= THRESH["base_rate_floor"], (
            f"Base-rate coverage {frac:.0%} below floor {THRESH['base_rate_floor']:.0%}"
        )


# ═══════════════════════════════════════════════════════════════════════════
# Dimension 5 — Bad-Analog Detection
# ═══════════════════════════════════════════════════════════════════════════

class TestBadAnalogDetection:
    def test_engine_avoids_inappropriate(self, retrieval):
        rate = _bad_rate(retrieval)
        appearances = []
        for r in retrieval.values():
            for m in r.retrieved_mechanisms:
                if m in r.inappropriate:
                    appearances.append(f"  {r.ticker}: surfaced inappropriate '{m}'")
        print(f"\nBad-analog appearance rate: {rate:.1%}  "
              f"(ceiling {THRESH['bad_analog_ceiling']:.0%})")
        if appearances:
            print("\n".join(appearances[:10]))
        assert rate <= THRESH["bad_analog_ceiling"], (
            f"Bad-analog rate {rate:.1%} above ceiling {THRESH['bad_analog_ceiling']:.0%}"
        )

    def test_every_analog_declares_disanalogy(self, library_scores):
        frac = _frac(library_scores, "has_disanalogy")
        fails = [s.label[:48] for s in library_scores if not s.has_disanalogy]
        print(f"\nDisanalogy self-declared: {frac:.0%}  (floor {THRESH['disanalogy_floor']:.0%})")
        if fails:
            print("Missing disanalogy:", fails[:8])
        assert frac >= THRESH["disanalogy_floor"], (
            f"Disanalogy coverage {frac:.0%} below floor {THRESH['disanalogy_floor']:.0%}"
        )


# ═══════════════════════════════════════════════════════════════════════════
# Dimension 6 — Coverage (library ceiling + engine recall)
# ═══════════════════════════════════════════════════════════════════════════

class TestCoverage:
    def test_every_archetype_has_appropriate_analog(self, retrieval):
        """Library ceiling: every archetype must have >=1 appropriate-family analog."""
        by_arche: Dict[str, List[bool]] = {}
        for r in retrieval.values():
            by_arche.setdefault(r.archetype, []).append(r.library_has_appropriate)
        print("\nArchetype coverage ceiling (library has appropriate family):")
        gaps = []
        for a, flags in sorted(by_arche.items()):
            covered = sum(flags)
            print(f"  {a:<16} {covered}/{len(flags)}")
            if covered < len(flags):
                gaps.append(a)
        assert not gaps, f"Archetypes with an uncovered company: {gaps}"

    def test_engine_recall_meets_floor(self, retrieval):
        """Recall gap: of companies that COULD retrieve, how many actually do.

        This is the primary documented improvement target — the library ceiling
        is 100% but business-model gating suppresses recall.
        """
        rec = _recall(retrieval)
        zero = [r.ticker for r in retrieval.values()
                if r.library_has_appropriate and r.n_retrieved == 0]
        print(f"\nEngine recall (retrieved / could-retrieve): {rec:.0%}  "
              f"(floor {THRESH['recall_floor']:.0%}, target {0.70:.0%})")
        print(f"Reachable-but-unretrieved ({len(zero)}): {zero[:25]}")
        assert rec >= THRESH["recall_floor"], (
            f"Recall {rec:.0%} below floor {THRESH['recall_floor']:.0%}"
        )


# ═══════════════════════════════════════════════════════════════════════════
# Composite V4 score
# ═══════════════════════════════════════════════════════════════════════════

def _composite(retrieval, library_scores) -> float:
    precision = _precision(retrieval)
    bad = _bad_rate(retrieval)
    specificity = _frac(library_scores, "specific")
    explanatory = _frac(library_scores, "explanatory")
    monitorable = _frac(library_scores, "monitorable")
    disanalogy = _frac(library_scores, "has_disanalogy")
    recall = _recall(retrieval)

    relevance_dim = precision * (1.0 - bad)          # precision, penalised by bad hits
    bad_dim = 1.0 - bad
    coverage_dim = recall                             # ceiling is 100% by construction

    return 100.0 * (
        0.25 * relevance_dim
        + 0.15 * specificity
        + 0.15 * explanatory
        + 0.20 * monitorable
        + 0.15 * bad_dim
        + 0.10 * coverage_dim
    )


class TestCompositeScore:
    def test_composite_meets_institutional_floor(self, retrieval, library_scores):
        score = _composite(retrieval, library_scores)
        print(f"\nV4 composite analog-usefulness score: {score:.1f}  "
              f"(floor {THRESH['composite_floor']:.0f})")
        assert score >= THRESH["composite_floor"], (
            f"V4 composite {score:.1f} below floor {THRESH['composite_floor']:.0f}"
        )


# ---------------------------------------------------------------------------
# Standalone report
# ---------------------------------------------------------------------------

def _report() -> None:
    library = _load_library()
    lib_scores = [_score_library_analog(a) for a in library]
    retr = _run_retrieval(library)

    print("=" * 68)
    print("V4 — HISTORICAL ANALOG USEFULNESS REPORT")
    print("=" * 68)
    print(f"Library size: {len(library)} analogs")
    print(f"Benchmark universe: {len(retr)} companies\n")

    print("Engine")
    print(f"  precision (relevant/retrieved): {_precision(retr):.1%}")
    print(f"  bad-analog rate:                {_bad_rate(retr):.1%}")
    print(f"  recall (retrieved/reachable):   {_recall(retr):.0%}")
    print()
    print("Library quality")
    print(f"  specificity:   {_frac(lib_scores,'specific'):.0%}")
    print(f"  explanatory:   {_frac(lib_scores,'explanatory'):.0%}")
    print(f"  monitorable:   {_frac(lib_scores,'monitorable'):.0%}")
    print(f"  disanalogy:    {_frac(lib_scores,'has_disanalogy'):.0%}")
    print(f"  base-rate:     {_frac(lib_scores,'has_base_rate'):.0%}")
    print()
    print(f"COMPOSITE: {_composite(retr, lib_scores):.1f}")

    # Strongest / weakest analogs by library quality
    def q(s: AnalogLibraryScore) -> int:
        return sum([s.specific, s.explanatory, s.monitorable,
                    s.has_disanalogy, s.has_base_rate])
    ranked = sorted(lib_scores, key=q, reverse=True)
    print("\nStrongest analogs (5/5 library quality):")
    for s in [s for s in ranked if q(s) == 5][:8]:
        print(f"  {s.label[:56]}")
    print("\nWeakest analogs (enrichment targets):")
    for s in sorted(lib_scores, key=q)[:8]:
        print(f"  [{q(s)}/5] {s.label[:52]}")

    # Recall gaps by archetype
    print("\nRecall gaps (reachable but unretrieved), by archetype:")
    by_a: Dict[str, List[str]] = {}
    for r in retr.values():
        if r.library_has_appropriate and r.n_retrieved == 0:
            by_a.setdefault(r.archetype, []).append(r.ticker)
    for a, tks in sorted(by_a.items()):
        print(f"  {a:<16} {tks}")


if __name__ == "__main__":
    _report()
