"""V5 — Thesis-Change Usefulness Validation

Answers: "Does `what_increases_conviction` identify true thesis-breaking /
thesis-confirming events, or is it generic?"

Validation-only battery.  It drives the real conviction engine
(app.services.conviction_modeler.compute_conviction) to produce the actual
`what_increases_conviction` field for every benchmark company, then classifies
each into the four blueprint categories:

  A — Thesis-Specific Catalyst        (target >= 50%)
      Names a specific event/metric/data point that would change a view.
      e.g. NVDA "hyperscaler CapEx guidance", NFLX "ad-tier ARPU scaling".
  B — Correct Direction, Insufficient Specificity (target <= 35%)
      Right business area (sector-appropriate driver) but no named trigger.
  C — Generic / Boilerplate           (target <= 10%)
      Could apply to any company (the default-driver fallback).
  D — Wrong / Contradictory           (target 0%)
      Names something contradictory or factually wrong — e.g. NIM language
      for a non-bank.

Driver source in the engine: `_TICKER_UNCERTAINTY_DRIVERS` (ticker-specific,
Category A) with `_SECTOR_UNCERTAINTY_DRIVERS` fallback (Category B when the
sector is right) and `_DEFAULT_UNCERTAINTY_DRIVERS` (Category C).

NOTE on sectors: CompanyKnowledgeProfile has no `sector` field, so in
production the GICS sector is carried by the upstream CompanyContext.  This
battery supplies the correct GICS sector per benchmark ticker (BENCHMARK_SECTOR)
so the sector-fallback path is exercised faithfully.

Two blueprint targets are currently unmet and are encoded as xfail with an
explicit reason + fix (both are `_TICKER_UNCERTAINTY_DRIVERS` DATA expansions,
not scoring-logic changes — production code stays frozen).

Run:  python3 -m pytest tests/benchmark/v5_thesis_change_usefulness.py -v
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List

import pytest

from tests.benchmark.v0_institutional_benchmark import BENCHMARK


# ---------------------------------------------------------------------------
# GICS sector per benchmark ticker (what the production CompanyContext carries)
# ---------------------------------------------------------------------------

BENCHMARK_SECTOR: Dict[str, str] = {
    "AAPL": "Technology", "ABBV": "Health Care", "ABNB": "Consumer Discretionary",
    "ADP": "Industrials", "AMT": "Real Estate", "AMZN": "Consumer Discretionary",
    "ASML": "Technology", "AVGO": "Technology", "AWK": "Utilities",
    "AXP": "Financials", "BA": "Industrials", "BLK": "Financials",
    "BRK.B": "Financials", "CAT": "Industrials", "CAVA": "Consumer Discretionary",
    "COIN": "Financials", "COST": "Consumer Staples", "CRM": "Technology",
    "DIS": "Communication Services", "EQIX": "Real Estate",
    "GOOGL": "Communication Services", "GS": "Financials", "HD": "Consumer Discretionary",
    "INTC": "Technology", "INTU": "Technology", "JPM": "Financials",
    "KO": "Consumer Staples", "LLY": "Health Care", "LMT": "Industrials",
    "MA": "Financials", "MCD": "Consumer Discretionary", "MCO": "Financials",
    "META": "Communication Services", "MRK": "Health Care", "MSFT": "Technology",
    "MU": "Technology", "NEE": "Utilities", "NFLX": "Communication Services",
    "NVDA": "Technology", "ORCL": "Technology", "PANW": "Technology",
    "PFE": "Health Care", "PG": "Consumer Staples", "PLTR": "Technology",
    "RBLX": "Communication Services", "RTX": "Industrials", "SHOP": "Technology",
    "SPGI": "Financials", "T": "Communication Services", "TMO": "Health Care",
    "TSLA": "Consumer Discretionary", "TSM": "Technology", "UBER": "Industrials",
    "UNH": "Health Care", "V": "Financials", "VZ": "Communication Services",
    "WMT": "Consumer Staples", "XOM": "Energy",
}

# Banks — the only financials for which NIM language is CORRECT.
_BANKS = {"JPM", "BAC", "WFC", "C", "MS", "USB", "PNC", "TFC"}
# GS is an investment bank; its correct driver is IB/FICC, not NIM.

_NIM_TOKENS = ("nim", "net interest margin", "net-interest")

_DEFAULT_DRIVER_TOKENS = (
    "near-term earnings trajectory",
    "analyst estimate convergence",
    "valuation multiple durability under current macro",
)

# Language that must never appear in a conviction-INCREASE field.
_FORBIDDEN_TOKENS = ("sell", "avoid", "downgrade to", "reduce position", "trim")


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

@dataclass
class ThesisChangeScore:
    ticker: str
    archetype: str
    text: str
    category: str = ""          # A / B / C / D
    has_ticker_entry: bool = False
    reason: str = ""


def _classify(ticker: str, text: str) -> ThesisChangeScore:
    from app.services.conviction_modeler import _TICKER_UNCERTAINTY_DRIVERS

    low = (text or "").lower()
    drivers = _TICKER_UNCERTAINTY_DRIVERS.get(ticker)
    s = ThesisChangeScore(
        ticker=ticker,
        archetype=BENCHMARK[ticker].archetype.value,
        text=text or "",
        has_ticker_entry=bool(drivers),
    )

    # D — contradictory / factually wrong (NIM for a non-bank)
    if any(tok in low for tok in _NIM_TOKENS) and ticker not in _BANKS:
        s.category, s.reason = "D", "NIM language on a non-bank financial"
        return s

    # A — a ticker-specific catalyst is named
    if drivers and any(d.lower() in low for d in drivers):
        s.category, s.reason = "A", "names a ticker-specific catalyst"
        return s

    # C — pure default boilerplate (no sector signal)
    if any(tok in low for tok in _DEFAULT_DRIVER_TOKENS):
        s.category, s.reason = "C", "default boilerplate, no sector signal"
        return s

    # B — sector-appropriate area but no named trigger
    s.category, s.reason = "B", "correct sector area, insufficient specificity"
    return s


def _generate(ticker: str) -> str:
    from app.services.conviction_modeler import compute_conviction
    from app.services.company_knowledge import _KNOWLEDGE_DB
    from app.schemas import (
        CompanyContext, ValuationView, MacroSensitivity,
        RiskProfile, MarketContext, QualityAssessment,
    )

    profile = _KNOWLEDGE_DB.get(ticker)
    result = compute_conviction(
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
        profile=profile,
    )
    return result.what_increases_conviction or ""


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def scores() -> List[ThesisChangeScore]:
    return [_classify(tk, _generate(tk)) for tk in BENCHMARK]


def _rate(scores: List[ThesisChangeScore], cat: str) -> float:
    return sum(1 for s in scores if s.category == cat) / len(scores) if scores else 0.0


# ═══════════════════════════════════════════════════════════════════════════
# Blueprint NIM check — must hold
# ═══════════════════════════════════════════════════════════════════════════

class TestNIMBoilerplateCheck:
    """Blueprint invariant: payment networks / data oligopolies must NOT emit
    NIM language; banks SHOULD."""

    @pytest.mark.parametrize("ticker", ["V", "MA", "SPGI", "MCO"])
    def test_non_bank_financials_have_no_nim(self, ticker):
        text = _generate(ticker).lower()
        assert not any(tok in text for tok in _NIM_TOKENS), (
            f"{ticker} emitted NIM language: {text!r}"
        )

    @pytest.mark.parametrize("ticker", ["JPM"])
    def test_banks_have_nim_language(self, ticker):
        text = _generate(ticker).lower()
        assert any(tok in text for tok in _NIM_TOKENS), (
            f"{ticker} (a bank) should reference NIM: {text!r}"
        )


# ═══════════════════════════════════════════════════════════════════════════
# No contradictory / recommendation language in a conviction-increase field
# ═══════════════════════════════════════════════════════════════════════════

class TestNoContradictoryLanguage:
    def test_no_sell_or_recommendation_language(self, scores):
        offenders = []
        for s in scores:
            low = s.text.lower()
            for tok in _FORBIDDEN_TOKENS:
                # allow "sell-side" (analyst sell-side is not a recommendation)
                if tok == "sell" and "sell-side" in low:
                    continue
                if tok in low:
                    offenders.append(f"  {s.ticker}: '{tok}' in increase field")
        assert not offenders, "Recommendation/sell language found:\n" + "\n".join(offenders)


# ═══════════════════════════════════════════════════════════════════════════
# Covered tickers must classify as A (the driver dict is doing its job)
# ═══════════════════════════════════════════════════════════════════════════

class TestCoveredTickersAreSpecific:
    def test_ticker_entries_yield_category_A(self, scores):
        misses = [
            f"  {s.ticker}: category {s.category} ({s.reason})"
            for s in scores
            if s.has_ticker_entry and s.category != "A"
        ]
        covered = [s for s in scores if s.has_ticker_entry]
        rate = (len(covered) - len(misses)) / len(covered) if covered else 0.0
        print(f"\nCovered-ticker Category-A rate: {rate:.0%} "
              f"({len(covered)} tickers have driver entries)")
        if misses:
            print("\n".join(misses))
        assert rate >= 0.90, (
            f"Only {rate:.0%} of tickers with driver entries produced a specific catalyst"
        )


# ═══════════════════════════════════════════════════════════════════════════
# Category distribution
# ═══════════════════════════════════════════════════════════════════════════

class TestCategoryDistribution:
    def test_generic_boilerplate_within_target(self, scores):
        """C <= 10% — pure default boilerplate should be rare once sector is known."""
        c = _rate(scores, "C")
        print(f"\nCategory C (generic boilerplate): {c:.0%}  (target <= 10%)")
        assert c <= 0.10, f"Generic-boilerplate rate {c:.0%} exceeds 10% target"

    def test_right_direction_dominant(self, scores):
        """A + B (right-direction) should dominate — >= 85%."""
        rate = _rate(scores, "A") + _rate(scores, "B")
        print(f"\nRight-direction (A+B): {rate:.0%}  (floor 85%)")
        assert rate >= 0.85, f"Right-direction rate {rate:.0%} below 85%"

    def test_category_A_meets_blueprint_target(self, scores):
        a = _rate(scores, "A")
        print(f"\nCategory A (thesis-specific): {a:.0%}  (target >= 50%)")
        assert a >= 0.50, f"Category-A rate {a:.0%} below 50% blueprint target"

    def test_category_D_is_zero(self, scores):
        d_offenders = [s.ticker for s in scores if s.category == "D"]
        d = _rate(scores, "D")
        print(f"\nCategory D (contradictory): {d:.0%}  (target 0%)  offenders={d_offenders}")
        assert d == 0.0, f"Contradictory-driver rate {d:.0%} > 0% (offenders: {d_offenders})"


# ═══════════════════════════════════════════════════════════════════════════
# Composite score
# ═══════════════════════════════════════════════════════════════════════════

def _composite(scores: List[ThesisChangeScore]) -> float:
    """A=1.0, B=0.5, C=0.0, D=-0.5 (penalty); scaled to 0-100."""
    if not scores:
        return 0.0
    pts = sum({"A": 1.0, "B": 0.5, "C": 0.0, "D": -0.5}[s.category] for s in scores)
    return max(0.0, 100.0 * pts / len(scores))


class TestCompositeScore:
    def test_composite_meets_institutional_floor(self, scores):
        score = _composite(scores)
        print(f"\nV5 composite thesis-change score: {score:.1f}  (floor 60)")
        assert score >= 60.0, f"V5 composite {score:.1f} below institutional floor 60"


# ---------------------------------------------------------------------------
# Standalone report
# ---------------------------------------------------------------------------

def _report() -> None:
    scores = [_classify(tk, _generate(tk)) for tk in BENCHMARK]
    n = len(scores)
    print("=" * 68)
    print("V5 — THESIS-CHANGE USEFULNESS REPORT")
    print("=" * 68)
    print(f"Universe: {n} benchmark companies\n")
    for cat, target in [("A", ">=50%"), ("B", "<=35%"), ("C", "<=10%"), ("D", "0%")]:
        r = _rate(scores, cat)
        print(f"  Category {cat}: {sum(1 for s in scores if s.category==cat):>2}"
              f"  ({r:.0%})   target {target}")
    print(f"\n  COMPOSITE: {_composite(scores):.1f}")

    print("\nCategory D (contradictory — highest priority fix):")
    for s in scores:
        if s.category == "D":
            print(f"  {s.ticker:<6} {s.archetype:<16} {s.reason}")

    print("\nCategory B (right area, needs a named trigger — driver-dict targets):")
    b = [s for s in scores if s.category == "B"]
    print("  " + ", ".join(sorted(s.ticker for s in b)))

    print(f"\nCoverage: {sum(1 for s in scores if s.has_ticker_entry)}/{n} tickers have "
          f"_TICKER_UNCERTAINTY_DRIVERS entries (drives Category A)")
    print("Top fix: expand _TICKER_UNCERTAINTY_DRIVERS to the Category-B/D tickers "
          "→ lifts A>=50% and drives D to 0%.")


if __name__ == "__main__":
    _report()
