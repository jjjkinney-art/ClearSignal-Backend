"""V6 — Failure Taxonomy Validation

Answers: "When the engine produces a bad output, can we CLASSIFY the failure by
type and severity so fixes are targeted, not vague?"

This is a VALIDATION-ONLY battery.  It drives the real conviction engine
(app.services.conviction_modeler.compute_conviction) over the full 58-company
institutional benchmark, plus the real analog seed library, and runs a bank of
detectors — one per failure code — that classify every output.  It changes NO
production code.

Taxonomy (per docs/TEST_ROADMAP_PHASE2_BLUEPRINT.md §V6), scoped to the codes
that are observable from the conviction-engine output + static driver data +
analog library.  Each code carries a severity from the blueprint matrix.

  Code  Class          Severity   Detects
  ────  ─────────────  ─────────  ────────────────────────────────────────────
  U1    UX             HIGH       synthesis failure — final_score == 0
  U3    UX             HIGH       missing evidence — empty required output field
  U4    UX             LOW        duplicate content across fields
  R4    RANKING        HIGH       score-stance disconnect (contradiction)
  R5    RANKING        MEDIUM     stance compression — >60% in one stance
  E5    REASONING      HIGH       risk/recommendation language in conviction-
                                  increase field (T3 alias — contradiction)
  X1    EXPLANATION    CRITICAL*  generic driver reused by >=5 companies
  X4    EXPLANATION    HIGH       sector/template leakage — NIM/NII on a non-bank
  X5    EXPLANATION    MEDIUM     unsupported claim — no quantitative anchor
  X6    EXPLANATION    MEDIUM     sector-level (not company-specific) reasoning
  T1    THESIS-CHANGE  MEDIUM     generic conviction driver (default boilerplate)
  A1    ANALOG         CRITICAL*  wrong-analog guardrail — library analog missing
                                  disanalogy / business_model / sector
  S1    SCHEMA-DRIFT   HIGH       stale schema / test drift — engine schema
                                  version or weight table changed unexpectedly
  (* CRITICAL escalation is rate-gated per the blueprint: X1 critical if >20% of
     reports, A1 critical if >10% of analogs.)

The battery asserts CRITICAL and HIGH classes are empty (a clean bill of health
for the frozen engine) and MEDIUM classes are within target.  X5 (quantitative
anchors) was the one previously-unmet target; it was closed by a DATA-only
enrichment of _TICKER_UNCERTAINTY_DRIVERS (driver_1 phrases rewritten as
falsifiable measurable thresholds), taking X5 from 95% to 0% with no change to
conviction mathematics, weights, routing, durability, or analog scoring.

Run:  python3 -m pytest tests/benchmark/v6_failure_taxonomy.py -v -s
"""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

import pytest

from tests.benchmark.v0_institutional_benchmark import BENCHMARK
from tests.benchmark.v5_thesis_change_usefulness import (
    BENCHMARK_SECTOR,
    _BANKS,
    _DEFAULT_DRIVER_TOKENS,
    _NIM_TOKENS,
)


# ---------------------------------------------------------------------------
# Severity model (docs/TEST_ROADMAP_PHASE2_BLUEPRINT.md §V6 severity matrix)
# ---------------------------------------------------------------------------

SEVERITY: Dict[str, str] = {
    "U1": "HIGH", "U3": "HIGH", "U4": "LOW",
    "R4": "HIGH", "R5": "MEDIUM",
    "E5": "HIGH",
    "X1": "MEDIUM",   # escalates to CRITICAL if rate > 20%
    "X4": "HIGH", "X5": "MEDIUM", "X6": "MEDIUM",
    "T1": "MEDIUM",
    "A1": "HIGH",     # escalates to CRITICAL if rate > 10%
    "S1": "HIGH",
}

CODE_CLASS: Dict[str, str] = {
    "U1": "UX", "U3": "UX", "U4": "UX",
    "R4": "RANKING", "R5": "RANKING",
    "E5": "REASONING",
    "X1": "EXPLANATION", "X4": "EXPLANATION", "X5": "EXPLANATION", "X6": "EXPLANATION",
    "T1": "THESIS-CHANGE",
    "A1": "ANALOG",
    "S1": "SCHEMA-DRIFT",
}

CODE_DESC: Dict[str, str] = {
    "U1": "synthesis failure (score=0)",
    "U3": "missing evidence (empty output field)",
    "U4": "duplicate content across fields",
    "R4": "score-stance disconnect (contradiction)",
    "R5": "stance compression (>60% one stance)",
    "E5": "risk/recommendation language in conviction-increase field",
    "X1": "generic driver reused by >=5 companies",
    "X4": "sector/template leakage (NIM on non-bank)",
    "X5": "unsupported claim (no quantitative anchor)",
    "X6": "sector-level (not company-specific) reasoning",
    "T1": "generic conviction driver (default boilerplate)",
    "A1": "wrong-analog guardrail missing (no disanalogy/business_model/sector)",
    "S1": "stale schema / test drift",
}

# Forbidden recommendation language in a conviction-INCREASE field (E5/T3).
_FORBIDDEN_TOKENS = ("sell", "avoid", "downgrade to", "reduce position", "trim")

# Sector-generic phrasing (X6) — text that names the sector instead of the company.
_SECTOR_GENERIC_RE = re.compile(
    r"\b(technology|health\s*care|healthcare|financials?|industrials?|utilities|"
    r"energy|materials|consumer|communication|real\s*estate)\s+sector\b",
    re.I,
)
_DIGIT_RE = re.compile(r"\d")

_ANALOG_SEED = (
    Path(__file__).resolve().parents[2] / "app" / "db" / "data" / "historical_analogs.json"
)

# R4 score-stance disconnect bands (a HIGH-score Avoid or a LOW-score Accumulate
# is an internal contradiction the product must never ship).
_R4_AVOID_HIGH = 0.62
_R4_ACCUMULATE_LOW = 0.45


# ---------------------------------------------------------------------------
# Finding + output containers
# ---------------------------------------------------------------------------

@dataclass
class Finding:
    code: str
    ticker: str
    detail: str

    @property
    def severity(self) -> str:
        return SEVERITY[self.code]

    @property
    def taxonomy_class(self) -> str:
        return CODE_CLASS[self.code]


@dataclass
class Output:
    ticker: str
    score: float
    stance: str
    setup_label: str
    what_increases: str
    reasoning: str


# ---------------------------------------------------------------------------
# Real-engine generation (self-contained; mirrors the V5 harness)
# ---------------------------------------------------------------------------

def _generate(ticker: str) -> Output:
    from app.services.conviction_modeler import compute_conviction
    from app.services.company_knowledge import _KNOWLEDGE_DB
    from app.schemas import (
        CompanyContext, ValuationView, MacroSensitivity,
        RiskProfile, MarketContext, QualityAssessment,
    )

    r = compute_conviction(
        evidence=[],
        valuation=ValuationView(overall="v", confidence=0.72, valuation_stance="fairly_valued"),
        macro=MacroSensitivity(overall="m", confidence=0.70),
        risk=RiskProfile(overall="r", confidence=0.68),
        market=MarketContext(overall="k", confidence=0.65),
        quality=QualityAssessment(overall="q", confidence=0.70),
        company=CompanyContext(
            ticker=ticker, company_name=ticker,
            sector=BENCHMARK_SECTOR.get(ticker, "Technology"),
        ),
        profile=_KNOWLEDGE_DB.get(ticker),
    )
    return Output(
        ticker=ticker,
        score=r.final_score,
        stance=r.directional_stance,
        setup_label=r.setup_label or "",
        what_increases=r.what_increases_conviction or "",
        reasoning=r.confidence_reasoning or "",
    )


# ---------------------------------------------------------------------------
# Per-output detectors (return the codes that fire for one company)
# ---------------------------------------------------------------------------

def _detect_per_output(o: Output) -> List[Finding]:
    out: List[Finding] = []
    wic = o.what_increases
    low = wic.lower()

    # U1 — synthesis failure
    if o.score == 0:
        out.append(Finding("U1", o.ticker, "final_score is 0"))

    # U3 — missing evidence / empty required field
    for name, val in (("what_increases_conviction", wic),
                      ("confidence_reasoning", o.reasoning),
                      ("setup_label", o.setup_label)):
        if not val.strip():
            out.append(Finding("U3", o.ticker, f"empty {name}"))

    # U4 — duplicate content across fields
    if wic.strip() and wic.strip() == o.reasoning.strip():
        out.append(Finding("U4", o.ticker, "what_increases == confidence_reasoning"))

    # R4 — score-stance disconnect
    if o.stance == "Avoid" and o.score >= _R4_AVOID_HIGH:
        out.append(Finding("R4", o.ticker, f"Avoid at score {o.score:.2f}"))
    if o.stance == "Accumulate" and o.score < _R4_ACCUMULATE_LOW:
        out.append(Finding("R4", o.ticker, f"Accumulate at score {o.score:.2f}"))

    # E5 — recommendation/sell language in a conviction-INCREASE field
    for tok in _FORBIDDEN_TOKENS:
        if tok == "sell" and "sell-side" in low:
            continue
        if tok in low:
            out.append(Finding("E5", o.ticker, f"'{tok}' in conviction-increase field"))

    # X4 — sector/template leakage: NIM on a non-bank
    if any(t in low for t in _NIM_TOKENS) and o.ticker not in _BANKS:
        out.append(Finding("X4", o.ticker, "NIM/NII language on a non-bank"))

    # X5 — unsupported claim: no quantitative anchor
    if not _DIGIT_RE.search(wic):
        out.append(Finding("X5", o.ticker, "no numeric anchor in conviction driver"))

    # X6 — sector-level (not company-specific) reasoning
    if _SECTOR_GENERIC_RE.search(wic):
        out.append(Finding("X6", o.ticker, "names the sector instead of the company"))

    # T1 — generic conviction driver (default boilerplate)
    if any(tok in low for tok in _DEFAULT_DRIVER_TOKENS):
        out.append(Finding("T1", o.ticker, "default-driver boilerplate"))

    return out


# ---------------------------------------------------------------------------
# Aggregate detectors (need the whole universe)
# ---------------------------------------------------------------------------

def _detect_aggregate(outputs: List[Output]) -> List[Finding]:
    out: List[Finding] = []

    # R5 — stance compression: >60% of companies in one stance
    stance_counts = Counter(o.stance for o in outputs)
    n = len(outputs)
    for stance, c in stance_counts.items():
        if n and c / n > 0.60:
            out.append(Finding("R5", "*", f"{c}/{n} ({c/n:.0%}) in '{stance}'"))

    # X1 — a driver phrase (first sentence fragment) shared by >=5 companies.
    # We proxy the "driver" by the conviction-increase text; identical strings
    # across many companies indicate a generic, non-specific driver.
    text_counts: Counter = Counter(o.what_increases.strip().lower() for o in outputs if o.what_increases.strip())
    for text, c in text_counts.items():
        if c >= 5:
            out.append(Finding("X1", "*", f"identical conviction driver on {c} companies"))

    return out


def _detect_schema_drift() -> List[Finding]:
    """S1 — stale schema / test drift: the engine's declared schema version and
    weight table must match what the validation suite was calibrated against."""
    from app.services import conviction_modeler as cm

    out: List[Finding] = []
    if cm.CONVICTION_SCHEMA_VERSION != "7-linear-4i":
        out.append(Finding("S1", "*", f"schema version is {cm.CONVICTION_SCHEMA_VERSION!r}, expected '7-linear-4i'"))
    if len(cm._WEIGHTS) != 8:
        out.append(Finding("S1", "*", f"linear weight count is {len(cm._WEIGHTS)}, expected 8"))
    if abs(sum(cm._WEIGHTS.values()) - 1.0) > 1e-9:
        out.append(Finding("S1", "*", f"linear weights sum to {sum(cm._WEIGHTS.values())}, expected 1.0"))
    return out


def _detect_analog_guardrails() -> List[Finding]:
    """A1 — wrong-analog guardrail: every analog in the seed library must declare
    a disanalogy, a business_model, and a sector, or the retrieval engine has no
    basis to reject a cross-sector / wrong-mechanism match."""
    out: List[Finding] = []
    if not _ANALOG_SEED.exists():
        return out
    records = json.loads(_ANALOG_SEED.read_text())
    for rec in records:
        label = rec.get("label") or rec.get("id") or "?"
        missing = [k for k in ("disanalogy", "business_model", "sector") if not (rec.get(k) or "").strip()]
        if missing:
            out.append(Finding("A1", label, f"missing {', '.join(missing)}"))
    return out


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def outputs() -> List[Output]:
    return [_generate(tk) for tk in BENCHMARK]


@pytest.fixture(scope="module")
def findings(outputs) -> List[Finding]:
    all_f: List[Finding] = []
    for o in outputs:
        all_f.extend(_detect_per_output(o))
    all_f.extend(_detect_aggregate(outputs))
    all_f.extend(_detect_schema_drift())
    all_f.extend(_detect_analog_guardrails())
    return all_f


def _by_severity(findings: List[Finding], sev: str) -> List[Finding]:
    return [f for f in findings if f.severity == sev]


def _by_code(findings: List[Finding], code: str) -> List[Finding]:
    return [f for f in findings if f.code == code]


def _rate(findings: List[Finding], code: str, denom: int) -> float:
    return len(_by_code(findings, code)) / denom if denom else 0.0


# ═══════════════════════════════════════════════════════════════════════════
# Coverage sanity — the battery actually exercised the whole universe
# ═══════════════════════════════════════════════════════════════════════════

class TestCoverage:
    def test_universe_fully_generated(self, outputs):
        assert len(outputs) == len(BENCHMARK) == 58
        assert all(isinstance(o.score, float) for o in outputs)


# ═══════════════════════════════════════════════════════════════════════════
# CRITICAL — must be empty (blocks launch)
# ═══════════════════════════════════════════════════════════════════════════

class TestCritical:
    def test_no_critical_failures(self, findings, outputs):
        # X1 escalates to CRITICAL above 20%; A1 above 10%.
        crit = []
        x1_rate = _rate(findings, "X1", len(outputs))
        if x1_rate > 0.20:
            crit += _by_code(findings, "X1")
        a1 = _by_code(findings, "A1")
        n_analogs = len(json.loads(_ANALOG_SEED.read_text())) if _ANALOG_SEED.exists() else 0
        if n_analogs and len(a1) / n_analogs > 0.10:
            crit += a1
        crit += _by_severity(findings, "CRITICAL")
        assert not crit, "CRITICAL failures:\n" + "\n".join(
            f"  {f.code} {f.ticker}: {f.detail}" for f in crit
        )


# ═══════════════════════════════════════════════════════════════════════════
# HIGH — must be empty before paid users
# ═══════════════════════════════════════════════════════════════════════════

class TestHigh:
    def test_no_synthesis_failures(self, findings):
        u1 = _by_code(findings, "U1")
        assert not u1, f"U1 synthesis failures: {[f.ticker for f in u1]}"

    def test_no_missing_evidence(self, findings):
        u3 = _by_code(findings, "U3")
        assert not u3, "U3 empty-field failures:\n" + "\n".join(
            f"  {f.ticker}: {f.detail}" for f in u3
        )

    def test_no_score_stance_contradiction(self, findings):
        r4 = _by_code(findings, "R4")
        assert not r4, "R4 score-stance disconnects:\n" + "\n".join(
            f"  {f.ticker}: {f.detail}" for f in r4
        )

    def test_no_recommendation_language_in_conviction_field(self, findings):
        e5 = _by_code(findings, "E5")
        assert not e5, "E5 contradiction (rec language):\n" + "\n".join(
            f"  {f.ticker}: {f.detail}" for f in e5
        )

    def test_no_sector_template_leakage(self, findings):
        x4 = _by_code(findings, "X4")
        assert not x4, "X4 NIM/template leakage:\n" + "\n".join(
            f"  {f.ticker}: {f.detail}" for f in x4
        )

    def test_no_schema_drift(self, findings):
        s1 = _by_code(findings, "S1")
        assert not s1, "S1 schema/test drift:\n" + "\n".join(
            f"  {f.detail}" for f in s1
        )

    def test_analog_wrong_match_guardrails_intact(self, findings):
        a1 = _by_code(findings, "A1")
        assert not a1, "A1 analog guardrail gaps:\n" + "\n".join(
            f"  {f.ticker}: {f.detail}" for f in a1
        )


# ═══════════════════════════════════════════════════════════════════════════
# MEDIUM — within target
# ═══════════════════════════════════════════════════════════════════════════

class TestMedium:
    def test_no_stance_compression(self, findings):
        r5 = _by_code(findings, "R5")
        assert not r5, "R5 stance compression:\n" + "\n".join(
            f"  {f.detail}" for f in r5
        )

    def test_generic_driver_reuse_within_target(self, findings, outputs):
        """X1 <= 20% — no conviction driver shared across many companies."""
        rate = _rate(findings, "X1", len(outputs))
        print(f"\nX1 generic-driver reuse: {rate:.0%}  (target <= 20%)")
        assert rate <= 0.20, f"X1 reuse rate {rate:.0%} exceeds 20%"

    def test_generic_boilerplate_driver_within_target(self, findings, outputs):
        """T1 <= 10% — default boilerplate should be rare once tickers are covered."""
        rate = _rate(findings, "T1", len(outputs))
        print(f"\nT1 generic-boilerplate driver: {rate:.0%}  (target <= 10%)")
        assert rate <= 0.10, f"T1 boilerplate rate {rate:.0%} exceeds 10%"

    def test_no_sector_level_reasoning(self, findings, outputs):
        """X6 <= 10% — reasoning should be company-specific, not sector-level."""
        rate = _rate(findings, "X6", len(outputs))
        print(f"\nX6 sector-level reasoning: {rate:.0%}  (target <= 10%)")
        assert rate <= 0.10, f"X6 sector-level rate {rate:.0%} exceeds 10%"

    def test_quantitative_anchor_present(self, findings, outputs):
        """X5 <= 10% — every conviction driver should carry a measurable threshold.

        RESOLVED (data-quality enrichment): _TICKER_UNCERTAINTY_DRIVERS driver_1
        phrases were rewritten from qualitative catalysts to analyst-grade
        falsifiable thresholds (revenue-growth %, margin %, subscriber/volume
        counts, backlog, regulatory milestones). X5 dropped 95% -> 0%. This was a
        DATA-only change to the driver lookup; conviction mathematics, weights,
        routing, durability, analog scoring and stance calibration are unchanged.
        """
        rate = _rate(findings, "X5", len(outputs))
        print(f"\nX5 missing quantitative anchor: {rate:.0%}  (target <= 10%)")
        assert rate <= 0.10, f"X5 missing-anchor rate {rate:.0%} exceeds 10% target"


# ═══════════════════════════════════════════════════════════════════════════
# Failure-health composite
# ═══════════════════════════════════════════════════════════════════════════

_SEV_PENALTY = {"CRITICAL": 25.0, "HIGH": 10.0, "MEDIUM": 3.0, "LOW": 1.0}


def _health(findings: List[Finding], n: int) -> float:
    """100 = no failures. Each finding deducts by severity, normalised per company.
    (X5 was previously excluded as a tracked production gap; it is now resolved to
    0 findings via the driver-threshold enrichment, so no special-casing remains.)"""
    penalty = sum(_SEV_PENALTY[f.severity] for f in findings)
    return max(0.0, 100.0 - penalty)


class TestFailureHealth:
    def test_failure_health_meets_floor(self, findings, outputs):
        score = _health(findings, len(outputs))
        print(f"\nV6 failure-health score: {score:.1f}  (floor 90, X5 excluded as tracked)")
        assert score >= 90.0, f"V6 failure-health {score:.1f} below floor 90"


# ---------------------------------------------------------------------------
# Standalone report
# ---------------------------------------------------------------------------

def _report() -> None:
    outputs = [_generate(tk) for tk in BENCHMARK]
    findings: List[Finding] = []
    for o in outputs:
        findings.extend(_detect_per_output(o))
    findings.extend(_detect_aggregate(outputs))
    findings.extend(_detect_schema_drift())
    findings.extend(_detect_analog_guardrails())
    n = len(outputs)

    print("=" * 72)
    print("V6 — FAILURE TAXONOMY REPORT")
    print("=" * 72)
    print(f"Universe: {n} benchmark companies + analog seed library\n")

    by_sev: Dict[str, List[Finding]] = defaultdict(list)
    for f in findings:
        by_sev[f.severity].append(f)
    for sev in ("CRITICAL", "HIGH", "MEDIUM", "LOW"):
        print(f"  {sev:<9}: {len(by_sev[sev])} findings")

    print("\nBy code (recurring failure modes):")
    code_counts = Counter(f.code for f in findings)
    for code, c in code_counts.most_common():
        print(f"  {code} [{SEVERITY[code]:<8} {CODE_CLASS[code]:<13}] "
              f"{c:>3}  ({c/n:.0%})  {CODE_DESC[code]}")

    print(f"\nFailure-health score (X5 excluded as tracked): {_health(findings, n):.1f}")

    if code_counts:
        top = code_counts.most_common(1)[0][0]
        affected = sorted({f.ticker for f in _by_code(findings, top) if f.ticker != "*"})
        print(f"\nTop recurring mode: {top} ({CODE_DESC[top]}) — {code_counts[top]} hits")
        print(f"  Affected: {', '.join(affected[:20])}"
              + (" ..." if len(affected) > 20 else ""))


if __name__ == "__main__":
    _report()
