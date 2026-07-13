"""V10 — Longitudinal KPI Dashboard (capstone)

The final blueprint battery.  Rather than evaluating a single snapshot, V10
AGGREGATES the whole V0-V9 program into an objective, numeric KPI dashboard
designed for continuous CI monitoring: it collects every battery's live score,
the engine's structural metrics, and the authoritative suite pass/fail counts,
then applies deployment gates, ranks KPIs by operational importance, computes
deltas against a committed baseline, and emits one institutional-readiness score.

Validation-only.  No production code is modified.  Every battery score is
recomputed live from the real engine + the standalone battery helpers; the
pass/fail counts come from a real subprocess pytest run over V1-V9 (+legacy).

Run:  python3 -m pytest tests/benchmark/v10_kpi_dashboard.py -v -s
Refresh the trend baseline:  python3 tests/benchmark/v10_kpi_dashboard.py --write-baseline
"""

from __future__ import annotations

import json
import statistics
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pytest

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parents[1]
_BASELINE = _HERE / "v10_kpi_baseline.json"
_ANALOG_SEED = _ROOT / "app" / "db" / "data" / "historical_analogs.json"

_BATTERY_FILES = [
    "v1_ranking_coherence", "v2_explanation_quality", "v3_decision_usefulness",
    "v4_analog_usefulness", "v5_thesis_change_usefulness", "v6_failure_taxonomy",
    "v7_portfolio_intelligence", "v8_competitive_benchmark",
    "v8_competitive_benchmark_legacy", "v9_blind_analyst_evaluation",
]


# ---------------------------------------------------------------------------
# Battery score collection (live, from standalone helpers)
# ---------------------------------------------------------------------------

def _v1_score() -> float:
    from tests.benchmark.v0_institutional_benchmark import PAIRWISE_CONSTRAINTS
    from app.services.conviction_modeler import _compute_structured_durability
    from app.services.company_knowledge import _KNOWLEDGE_DB
    dur = {tk: _compute_structured_durability(p) for tk, p in _KNOWLEDGE_DB.items()}
    pairs = [(a, b) for a, b, _ in PAIRWISE_CONSTRAINTS if a in dur and b in dur]
    ok = sum(1 for a, b in pairs if dur[a] >= dur[b])
    return round(100.0 * ok / len(pairs), 1) if pairs else 0.0


def _v2_score() -> float:
    from tests.benchmark.v2_explanation_quality import score_profile
    from app.services.company_knowledge import _KNOWLEDGE_DB
    vals = [score_profile(p).composite for p in _KNOWLEDGE_DB.values()]
    return round(statistics.mean(vals), 1) if vals else 0.0


def _v3_score() -> float:
    from tests.benchmark.v3_decision_usefulness import (
        DecisionScore, _score_actionability, _score_thesis_clarity,
        _score_thesis_breaker_quality, _score_risk_prioritization,
        _score_monitoring_quality, _score_consistency, _compute_differentiation,
    )
    from tests.benchmark.v0_institutional_benchmark import BENCHMARK
    from app.services.conviction_modeler import _compute_structured_durability, _TICKER_UNCERTAINTY_DRIVERS
    from app.services.company_knowledge import _KNOWLEDGE_DB
    durability = {tk: _compute_structured_durability(p) for tk, p in _KNOWLEDGE_DB.items()}
    diff = _compute_differentiation(_KNOWLEDGE_DB, durability)
    comps = []
    for tk, p in _KNOWLEDGE_DB.items():
        drivers = _TICKER_UNCERTAINTY_DRIVERS.get(tk, [])
        ds = DecisionScore(ticker=tk, company=p.company_name)
        ds.actionability = _score_actionability(p)[0]
        ds.thesis_clarity = _score_thesis_clarity(p)[0]
        ds.thesis_breaker_quality = _score_thesis_breaker_quality(p, drivers)[0]
        ds.risk_prioritization = _score_risk_prioritization(p, BENCHMARK.get(tk))[0]
        ds.monitoring_quality = _score_monitoring_quality(p, drivers)[0]
        ds.consistency = _score_consistency(p, durability[tk])[0]
        ds.differentiation = diff.get(tk, 0)
        comps.append(ds.composite)
    return round(statistics.mean(comps), 1) if comps else 0.0


def _v4_score() -> float:
    from tests.benchmark.v4_analog_usefulness import (
        _load_library, _score_library_analog, _run_retrieval, _composite,
    )
    lib = _load_library()
    return round(_composite(_run_retrieval(lib), [_score_library_analog(a) for a in lib]), 1)


def _v5_score() -> float:
    from tests.benchmark.v5_thesis_change_usefulness import _classify, _generate, _composite
    from tests.benchmark.v0_institutional_benchmark import BENCHMARK
    return round(_composite([_classify(tk, _generate(tk)) for tk in BENCHMARK]), 1)


def _v6_findings():
    from tests.benchmark import v6_failure_taxonomy as v6
    from tests.benchmark.v0_institutional_benchmark import BENCHMARK
    outs = [v6._generate(tk) for tk in BENCHMARK]
    findings = []
    for o in outs:
        findings.extend(v6._detect_per_output(o))
    findings.extend(v6._detect_aggregate(outs))
    findings.extend(v6._detect_schema_drift())
    findings.extend(v6._detect_analog_guardrails())
    return findings, len(outs)


def _v6_score() -> float:
    from tests.benchmark.v6_failure_taxonomy import _health
    findings, n = _v6_findings()
    return round(_health(findings, n), 1)


def _v7_score() -> float:
    from tests.benchmark.v7_portfolio_intelligence import PORTFOLIOS, _build_report, _composite
    return round(_composite({name: _build_report(name, h) for name, h in PORTFOLIOS.items()}), 1)


def _v8_score() -> float:
    from tests.benchmark.v8_competitive_benchmark import _measure_clearsignal, _composite
    return round(_composite(_measure_clearsignal()), 1)


def _v9_score() -> float:
    from tests.benchmark.v9_blind_analyst_evaluation import _run_panel, _overall
    return round(_overall(_run_panel())["ClearSignal"] * 20.0, 1)   # 1-5 -> 0-100


# ---------------------------------------------------------------------------
# Engine + coverage metrics
# ---------------------------------------------------------------------------

def _engine_metrics() -> Dict[str, object]:
    from app.services import conviction_modeler as cm
    from app.services.company_knowledge import _KNOWLEDGE_DB
    from app.services.conviction_modeler import compute_conviction
    from tests.benchmark.v0_institutional_benchmark import BENCHMARK
    from tests.benchmark.v5_thesis_change_usefulness import BENCHMARK_SECTOR
    from app.schemas import (
        CompanyContext, ValuationView, MacroSensitivity,
        RiskProfile, MarketContext, QualityAssessment,
    )

    struct_fields = ["moat_type", "revenue_model", "switching_cost_level", "customer_concentration",
                     "capital_intensity", "earnings_cyclicality", "narrative_dependence", "binary_risk_level"]
    fully = sum(1 for p in _KNOWLEDGE_DB.values()
                if all(getattr(p, f, None) for f in struct_fields))

    # Score dispersion across the benchmark (real engine, uniform agent inputs).
    scores = []
    for tk in BENCHMARK:
        r = compute_conviction(
            evidence=[],
            valuation=ValuationView(overall="v", confidence=0.72, valuation_stance="fairly_valued"),
            macro=MacroSensitivity(overall="m", confidence=0.70),
            risk=RiskProfile(overall="r", confidence=0.68),
            market=MarketContext(overall="k", confidence=0.65),
            quality=QualityAssessment(overall="q", confidence=0.70),
            company=CompanyContext(ticker=tk, company_name=tk,
                                   sector=BENCHMARK_SECTOR.get(tk, "Technology")),
            profile=_KNOWLEDGE_DB.get(tk),
        )
        scores.append(r.final_score)

    analog_n = len(json.loads(_ANALOG_SEED.read_text())) if _ANALOG_SEED.exists() else 0
    return {
        "schema_version": cm.CONVICTION_SCHEMA_VERSION,
        "weight_count": len(cm._WEIGHTS),
        "analog_library_size": analog_n,
        "company_count": len(_KNOWLEDGE_DB),
        "structured_coverage_pct": round(100.0 * fully / len(_KNOWLEDGE_DB), 1),
        "avg_conviction_variance": round(statistics.pvariance(scores), 5) if len(scores) > 1 else 0.0,
        "score_dispersion": round(statistics.pstdev(scores), 4) if len(scores) > 1 else 0.0,
    }


def _failure_taxonomy_counts() -> Dict[str, int]:
    """U/R/E/X/T/A/S class counts from the V6 findings."""
    findings, _ = _v6_findings()
    classes = {"U": 0, "R": 0, "E": 0, "X": 0, "T": 0, "A": 0, "S": 0}
    for f in findings:
        prefix = f.code[0]
        if prefix in classes:
            classes[prefix] += 1
    return classes


# ---------------------------------------------------------------------------
# Authoritative suite counts (subprocess pytest over V1-V9 + legacy, not V10)
# ---------------------------------------------------------------------------

def _run_suite_counts() -> Dict[str, int]:
    files = [str(_HERE / f"{b}.py") for b in _BATTERY_FILES]
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", *files, "--tb=no", "-q", "-p", "no:cacheprovider"],
        cwd=str(_ROOT), capture_output=True, text=True, timeout=600,
    )
    out = proc.stdout + proc.stderr
    import re
    def grab(word):
        m = re.search(r"(\d+) " + word, out)
        return int(m.group(1)) if m else 0
    passed, failed, xfailed, errors = grab("passed"), grab("failed"), grab("error"), 0
    xfailed = grab("xfailed")
    total = passed + failed + xfailed
    return {"total": total, "passed": passed, "failed": failed,
            "xfailed": xfailed, "errors": grab("error")}


# ---------------------------------------------------------------------------
# KPI assembly
# ---------------------------------------------------------------------------

@dataclass
class KPI:
    name: str
    value: float
    importance: str            # Critical / High / Medium / Informational
    unit: str = ""


def collect_kpis() -> Dict[str, KPI]:
    counts = _run_suite_counts()
    eng = _engine_metrics()
    tax = _failure_taxonomy_counts()

    v = {
        "v1": _v1_score(), "v2": _v2_score(), "v3": _v3_score(), "v4": _v4_score(),
        "v5": _v5_score(), "v6": _v6_score(), "v7": _v7_score(), "v8": _v8_score(),
        "v9": _v9_score(),
    }
    battery_composite = round(statistics.mean(v.values()), 1)
    pass_rate = round(100.0 * counts["passed"] / counts["total"], 1) if counts["total"] else 0.0

    k: Dict[str, KPI] = {}
    def add(name, val, imp, unit=""):
        k[name] = KPI(name, val, imp, unit)

    # Critical
    add("validation_pass_rate", pass_rate, "Critical", "%")
    add("failure_count", counts["failed"], "Critical")
    add("regression_errors", counts["errors"], "Critical")
    add("ranking_coherence_v1", v["v1"], "Critical")
    # High
    add("benchmark_composite", battery_composite, "High")
    add("explanation_quality_v2", v["v2"], "High")
    add("decision_usefulness_v3", v["v3"], "High")
    add("failure_health_v6", v["v6"], "High")
    add("total_tests", counts["total"], "High")
    # Medium
    add("analog_usefulness_v4", v["v4"], "Medium")
    add("thesis_change_v5", v["v5"], "Medium")
    add("portfolio_intelligence_v7", v["v7"], "Medium")
    add("competitive_v8", v["v8"], "Medium")
    add("blind_analyst_v9", v["v9"], "Medium")
    add("score_dispersion", eng["score_dispersion"], "Medium")
    add("avg_conviction_variance", eng["avg_conviction_variance"], "Medium")
    add("xfailed_documented", counts["xfailed"], "Medium")
    # Informational
    add("structured_coverage", eng["structured_coverage_pct"], "Informational", "%")
    add("company_count", eng["company_count"], "Informational")
    add("analog_library_size", eng["analog_library_size"], "Informational")
    add("weight_count", eng["weight_count"], "Informational")
    for cls, n in tax.items():
        add(f"failtax_{cls}", n, "Informational")
    return k


# ---------------------------------------------------------------------------
# Deployment gates
# ---------------------------------------------------------------------------

@dataclass
class Gate:
    name: str
    status: str          # PASS / WARNING / FAIL
    detail: str


def _gate(value: float, pass_at: float, warn_at: float, name: str, higher_better: bool = True) -> Gate:
    if higher_better:
        status = "PASS" if value >= pass_at else ("WARNING" if value >= warn_at else "FAIL")
    else:
        status = "PASS" if value <= pass_at else ("WARNING" if value <= warn_at else "FAIL")
    return Gate(name, status, f"{value} (pass@{pass_at}, warn@{warn_at})")


def deployment_gates(k: Dict[str, KPI]) -> List[Gate]:
    return [
        _gate(k["validation_pass_rate"].value, 95, 90, "validation_pass_rate"),
        _gate(k["failure_count"].value, 0, 0, "critical_failures", higher_better=False),
        _gate(k["regression_errors"].value, 0, 0, "regression_errors", higher_better=False),
        _gate(k["ranking_coherence_v1"].value, 90, 80, "ranking_coherence"),
        _gate(k["benchmark_composite"].value, 75, 65, "benchmark_composite"),
        _gate(k["explanation_quality_v2"].value, 70, 60, "explanation_quality"),
        _gate(k["failure_health_v6"].value, 90, 80, "failure_health"),
    ]


def _overall_gate(gates: List[Gate]) -> str:
    if any(g.status == "FAIL" for g in gates):
        return "FAIL"
    if any(g.status == "WARNING" for g in gates):
        return "WARNING"
    return "PASS"


# ---------------------------------------------------------------------------
# Institutional readiness score (single 0-100 summary of V0-V10)
# ---------------------------------------------------------------------------

def institutional_readiness(k: Dict[str, KPI]) -> float:
    # Weighted blend across the program's pillars.
    return round(
        0.20 * k["validation_pass_rate"].value
        + 0.15 * k["ranking_coherence_v1"].value
        + 0.15 * k["benchmark_composite"].value
        + 0.12 * k["explanation_quality_v2"].value
        + 0.10 * k["decision_usefulness_v3"].value
        + 0.10 * k["failure_health_v6"].value
        + 0.08 * k["competitive_v8"].value
        + 0.05 * k["blind_analyst_v9"].value
        + 0.05 * k["thesis_change_v5"].value
        - 5.0 * k["failure_count"].value
        - 5.0 * k["regression_errors"].value,
        1,
    )


# ---------------------------------------------------------------------------
# Trend / baseline
# ---------------------------------------------------------------------------

def _load_baseline() -> Optional[Dict[str, float]]:
    if _BASELINE.exists():
        try:
            return json.loads(_BASELINE.read_text())
        except Exception:
            return None
    return None


def _kpi_values(k: Dict[str, KPI]) -> Dict[str, float]:
    return {name: kpi.value for name, kpi in k.items()}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def kpis() -> Dict[str, KPI]:
    return collect_kpis()


# ═══════════════════════════════════════════════════════════════════════════
# KPI integrity
# ═══════════════════════════════════════════════════════════════════════════

class TestKPIs:
    def test_all_kpis_numeric(self, kpis):
        for name, kpi in kpis.items():
            assert isinstance(kpi.value, (int, float)), f"{name} not numeric"
            assert kpi.importance in {"Critical", "High", "Medium", "Informational"}

    def test_core_kpis_present(self, kpis):
        required = {"validation_pass_rate", "benchmark_composite", "ranking_coherence_v1",
                    "explanation_quality_v2", "failure_health_v6", "score_dispersion",
                    "structured_coverage", "analog_library_size", "company_count"}
        assert required <= set(kpis)

    def test_engine_frozen(self, kpis):
        assert kpis["weight_count"].value == 8
        assert kpis["structured_coverage"].value == 100.0


# ═══════════════════════════════════════════════════════════════════════════
# Deployment gates
# ═══════════════════════════════════════════════════════════════════════════

class TestDeploymentGates:
    def test_no_gate_fails(self, kpis):
        gates = deployment_gates(kpis)
        fails = [g for g in gates if g.status == "FAIL"]
        assert not fails, "Deployment gates FAILED:\n" + "\n".join(
            f"  {g.name}: {g.detail}" for g in fails
        )

    def test_overall_gate_not_fail(self, kpis):
        assert _overall_gate(deployment_gates(kpis)) in {"PASS", "WARNING"}

    def test_no_critical_failures(self, kpis):
        assert kpis["failure_count"].value == 0
        assert kpis["regression_errors"].value == 0


# ═══════════════════════════════════════════════════════════════════════════
# Suite health
# ═══════════════════════════════════════════════════════════════════════════

class TestSuiteHealth:
    def test_pass_rate_high(self, kpis):
        assert kpis["validation_pass_rate"].value >= 95.0

    def test_full_program_test_count(self, kpis):
        # V1-V9 + legacy should contribute a substantial battery
        assert kpis["total_tests"].value >= 150


# ═══════════════════════════════════════════════════════════════════════════
# Trend / regression detection vs committed baseline
# ═══════════════════════════════════════════════════════════════════════════

class TestTrend:
    def test_no_metric_regressed_vs_baseline(self, kpis):
        base = _load_baseline()
        if base is None:
            pytest.skip("no baseline committed yet — first run establishes it")
        cur = _kpi_values(kpis)
        # KPIs where lower is worse (score-type). Allow a small tolerance.
        score_kpis = ["validation_pass_rate", "benchmark_composite", "ranking_coherence_v1",
                      "explanation_quality_v2", "decision_usefulness_v3", "failure_health_v6",
                      "analog_usefulness_v4", "thesis_change_v5", "portfolio_intelligence_v7",
                      "competitive_v8", "blind_analyst_v9"]
        regressions = []
        for name in score_kpis:
            if name in base and cur.get(name, 0) + 0.5 < base[name]:
                regressions.append(f"  {name}: {base[name]} -> {cur[name]}")
        assert not regressions, "KPI REGRESSIONS vs baseline:\n" + "\n".join(regressions)


# ═══════════════════════════════════════════════════════════════════════════
# Institutional readiness + dashboard
# ═══════════════════════════════════════════════════════════════════════════

class TestReadiness:
    def test_institutional_readiness_floor(self, kpis):
        score = institutional_readiness(kpis)
        assert score >= 80.0, f"Institutional readiness {score} below 80"

    def test_dashboard(self, kpis):
        gates = deployment_gates(kpis)
        base = _load_baseline() or {}
        cur = _kpi_values(kpis)
        readiness = institutional_readiness(kpis)

        L = ["", "=" * 78, "V10 — LONGITUDINAL KPI DASHBOARD", "=" * 78]
        L.append(f"\nINSTITUTIONAL READINESS SCORE: {readiness:.1f} / 100")
        L.append(f"DEPLOYMENT DECISION: {_overall_gate(gates)}")

        L.append("\nDeployment gates:")
        for g in gates:
            L.append(f"  [{g.status:<7}] {g.name:<22} {g.detail}")

        L.append("\nKPI table (by importance)   previous -> current (delta):")
        order = {"Critical": 0, "High": 1, "Medium": 2, "Informational": 3}
        for name, kpi in sorted(kpis.items(), key=lambda x: (order[x[1].importance], x[0])):
            prev = base.get(name)
            if prev is None:
                trend = f"{kpi.value:>10}{kpi.unit:<2}  (new)"
            else:
                d = round(kpi.value - prev, 2)
                arrow = "=" if d == 0 else ("+" if d > 0 else "")
                trend = f"{prev:>8} -> {kpi.value:<8}{kpi.unit:<2} ({arrow}{d})"
            L.append(f"  {kpi.importance:<13} {name:<26} {trend}")

        L.append("\nValidation program V0-V10: COMPLETE")
        print("\n".join(L))
        assert True


# ---------------------------------------------------------------------------
# CLI: refresh baseline
# ---------------------------------------------------------------------------

def _write_baseline() -> None:
    k = collect_kpis()
    _BASELINE.write_text(json.dumps(_kpi_values(k), indent=2, sort_keys=True))
    print(f"baseline written: {_BASELINE}")


if __name__ == "__main__":
    if "--write-baseline" in sys.argv:
        _write_baseline()
    else:
        k = collect_kpis()
        print("Institutional readiness:", institutional_readiness(k))
        print("Deployment:", _overall_gate(deployment_gates(k)))
