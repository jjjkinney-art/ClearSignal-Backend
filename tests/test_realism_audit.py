"""
Productization realism audit tests.

Verifies that the conviction modeler produces company-specific, PM-grade
confidence_reasoning with no legacy boilerplate, generic AI phrases, or
hard-fail template strings surviving into the final payload.

Constraints:
- confidence_reasoning must reference the ticker
- confidence_reasoning must contain at least one company-specific uncertainty driver
- No _HARD_FAIL_CONFIDENCE_PHRASES appear in the output
- what_increases_conviction must be non-empty and company-specific
- setup_label must be one of the defined valid labels
- score range 0.20 ≤ final_score ≤ 0.80 for all standard tickers

All tests use compute_conviction() directly with realistic production-style inputs.
No mocking of the conviction modeler internals — these are integration-level assertions.
"""
from __future__ import annotations

import datetime
import pytest
from typing import List

from app.schemas import (
    CompanyContext, ValuationView, MacroSensitivity, RiskProfile,
    MarketContext, QualityAssessment, RetrievedEvidence,
)
from app.services.conviction_modeler import compute_conviction


# ── Shared helpers ────────────────────────────────────────────────────────────

_VALID_SETUP_LABELS = {
    "high-alignment thesis",
    "actionable thesis",
    "monitoring required",
    "expectation-sensitive",
    "mixed evidence",
    "fragile setup",
    "asymmetric setup",
    "speculative setup",
    "insufficient conviction",
}

_HARD_FAIL_PHRASES = [
    "limited evidence coverage means this position carries more uncertainty",
    "the framework is sound, the data is thin",
    "carries more uncertainty than the score reflects",
    "framework is sound",
    "more uncertainty than the score",
    "the data is too thin to act on",
    "thesis framework exists but the data",
    "data is too sparse to act on",
    "it's worth noting that",
    "it is worth noting that",
    "this is a complex situation",
    "it is important to note",
    "there are many factors",
    "various factors contribute",
]

_TSLA_DRIVERS = ["EV margin", "FSD", "Optimus", "margin"]
_NVDA_DRIVERS = ["hyperscaler", "CapEx", "ASIC", "export"]
_PLTR_DRIVERS = ["government", "commercial", "enterprise", "AI platform"]
_SNOW_DRIVERS = [
    "enterprise", "consumption", "AI spending", "warehouse",
    "product revenue", "NRR",
]
_MSFT_DRIVERS = ["Azure", "Copilot", "AI", "cloud"]
_ASML_DRIVERS = ["China", "EUV", "export", "capex"]


def _make_evidence(ticker: str, n: int = 3) -> List[RetrievedEvidence]:
    base_ts = datetime.datetime(2025, 3, 15, tzinfo=datetime.timezone.utc).isoformat()
    return [
        RetrievedEvidence(
            title=f"{ticker} Q1 earnings call transcript",
            source="SEC EDGAR",
            summary=f"{ticker} management discussed Q1 results and forward guidance.",
            timestamp=base_ts,
            relevance_score=0.90,
        ),
        RetrievedEvidence(
            title=f"{ticker} analyst price target update",
            source="analyst-estimates",
            summary=f"Analysts revised {ticker} price targets following earnings.",
            timestamp=base_ts,
            relevance_score=0.80,
        ),
        RetrievedEvidence(
            title=f"{ticker} 10-K annual report",
            source="SEC EDGAR",
            summary=f"{ticker} annual report showing risk factors and financial position.",
            timestamp=base_ts,
            relevance_score=0.85,
        ),
    ][:n]


def _make_company(ticker: str, sector: str = "Technology") -> CompanyContext:
    return CompanyContext(
        ticker=ticker,
        company_name=f"{ticker} Inc.",
        sector=sector,
        industry="Technology",
        market_cap=500e9,
    )


def _make_valuation(stance: str = "overpriced", conf: float = 0.45) -> ValuationView:
    return ValuationView(
        pe_assessment="Trading at a premium to peers",
        growth_view="Revenue growth moderating",
        margin_trend="Margins under pressure",
        overall="Elevated valuation relative to fundamentals",
        confidence=conf,
        valuation_stance=stance,
    )


def _make_macro(conf: float = 0.55) -> MacroSensitivity:
    return MacroSensitivity(
        rate_sensitivity="High — rate-sensitive growth story",
        overall="Macro headwinds from elevated rates",
        confidence=conf,
    )


def _make_risk(conf: float = 0.50) -> RiskProfile:
    return RiskProfile(
        key_risks=["Execution risk", "Competitive pressure"],
        overall="Elevated risk profile with multiple execution dependencies",
        confidence=conf,
    )


def _make_market(conf: float = 0.55) -> MarketContext:
    return MarketContext(
        overall="Mixed market context",
        confidence=conf,
    )


def _make_quality(conf: float = 0.60) -> QualityAssessment:
    return QualityAssessment(
        overall="Business quality intact but setup demanding",
        confidence=conf,
    )


# ══════════════════════════════════════════════════════════════════════════════
# Class 1: Hard-fail phrase elimination
# ══════════════════════════════════════════════════════════════════════════════

class TestHardFailPhraseElimination:
    """No hard-fail boilerplate phrases survive in confidence_reasoning."""

    @pytest.mark.parametrize("ticker,sector", [
        ("TSLA", "Consumer Discretionary"),
        ("NVDA", "Technology"),
        ("PLTR", "Technology"),
        ("SNOW", "Technology"),
        ("MSFT", "Technology"),
        ("ASML", "Technology"),
        ("JPM",  "Financials"),
        ("VRTX", "Health Care"),
    ])
    def test_no_hard_fail_phrase_in_confidence_reasoning(self, ticker, sector):
        """confidence_reasoning must never contain any hard-fail boilerplate phrase."""
        company = _make_company(ticker, sector)
        conviction = compute_conviction(
            evidence=_make_evidence(ticker),
            valuation=_make_valuation(),
            macro=_make_macro(),
            risk=_make_risk(),
            market=_make_market(),
            quality=_make_quality(),
            company=company,
            ranked=None,
            governance_warnings=[],
        )
        reasoning_lc = conviction.confidence_reasoning.lower()
        for phrase in _HARD_FAIL_PHRASES:
            assert phrase.lower() not in reasoning_lc, (
                f"[{ticker}] Hard-fail phrase found in confidence_reasoning: {phrase!r}\n"
                f"Full reasoning: {conviction.confidence_reasoning!r}"
            )

    def test_no_hard_fail_phrase_with_empty_evidence(self):
        """Even with zero evidence, no hard-fail boilerplate should appear."""
        company = _make_company("TSLA", "Consumer Discretionary")
        conviction = compute_conviction(
            evidence=[],
            valuation=_make_valuation(),
            macro=_make_macro(),
            risk=_make_risk(),
            market=_make_market(),
            quality=_make_quality(),
            company=company,
            ranked=None,
            governance_warnings=[],
        )
        reasoning_lc = conviction.confidence_reasoning.lower()
        for phrase in _HARD_FAIL_PHRASES:
            assert phrase.lower() not in reasoning_lc, (
                f"Empty-evidence path emitted hard-fail phrase: {phrase!r}\n"
                f"Full reasoning: {conviction.confidence_reasoning!r}"
            )

    def test_no_hard_fail_phrase_with_low_quality_evidence(self):
        """With weak evidence (low relevance, stale), no boilerplate should escape."""
        company = _make_company("PLTR", "Technology")
        stale_ev = [
            RetrievedEvidence(
                title="Old PLTR quarterly filing",
                source="news",
                summary="Older context on Palantir operations.",
                timestamp="2022-01-15",
                relevance_score=0.20,
            )
        ]
        conviction = compute_conviction(
            evidence=stale_ev,
            valuation=_make_valuation("cannot_determine", conf=0.20),
            macro=_make_macro(conf=0.30),
            risk=_make_risk(conf=0.25),
            market=_make_market(conf=0.30),
            quality=_make_quality(conf=0.35),
            company=company,
            ranked=None,
            governance_warnings=["[GOVERNANCE] Stance conflicts with evidence"],
        )
        reasoning_lc = conviction.confidence_reasoning.lower()
        for phrase in _HARD_FAIL_PHRASES:
            assert phrase.lower() not in reasoning_lc, (
                f"Low-quality evidence path emitted hard-fail phrase: {phrase!r}\n"
                f"Full reasoning: {conviction.confidence_reasoning!r}"
            )


# ══════════════════════════════════════════════════════════════════════════════
# Class 2: Ticker reference in confidence_reasoning
# ══════════════════════════════════════════════════════════════════════════════

class TestTickerReferenceInReasoning:
    """confidence_reasoning must always reference the company ticker."""

    @pytest.mark.parametrize("ticker", [
        "TSLA", "NVDA", "PLTR", "SNOW", "MSFT", "ASML", "JPM", "AAPL", "AMZN",
    ])
    def test_reasoning_contains_ticker(self, ticker):
        company = _make_company(ticker)
        conviction = compute_conviction(
            evidence=_make_evidence(ticker),
            valuation=_make_valuation(),
            macro=_make_macro(),
            risk=_make_risk(),
            market=_make_market(),
            quality=_make_quality(),
            company=company,
        )
        assert ticker.upper() in conviction.confidence_reasoning.upper(), (
            f"[{ticker}] confidence_reasoning does not reference the ticker.\n"
            f"Reasoning: {conviction.confidence_reasoning!r}"
        )

    def test_reasoning_contains_ticker_with_empty_evidence(self):
        """Ticker reference must survive even in zero-evidence edge case."""
        company = _make_company("NVDA", "Technology")
        conviction = compute_conviction(
            evidence=[],
            valuation=_make_valuation(),
            macro=_make_macro(),
            risk=_make_risk(),
            market=_make_market(),
            quality=_make_quality(),
            company=company,
        )
        assert "NVDA" in conviction.confidence_reasoning, (
            f"Ticker NVDA missing from zero-evidence reasoning: {conviction.confidence_reasoning!r}"
        )


# ══════════════════════════════════════════════════════════════════════════════
# Class 3: Company-specific uncertainty driver in confidence_reasoning
# ══════════════════════════════════════════════════════════════════════════════

class TestCompanySpecificDriverInReasoning:
    """confidence_reasoning must reference at least one company-specific uncertainty driver."""

    def _has_any_driver(self, reasoning: str, drivers: List[str]) -> bool:
        reasoning_lc = reasoning.lower()
        return any(d.lower() in reasoning_lc for d in drivers)

    def test_tsla_reasoning_contains_driver(self):
        """TSLA reasoning references EV margin, FSD, or Optimus."""
        company = _make_company("TSLA", "Consumer Discretionary")
        conviction = compute_conviction(
            evidence=_make_evidence("TSLA"),
            valuation=_make_valuation("overpriced", 0.40),
            macro=_make_macro(0.55),
            risk=_make_risk(0.50),
            market=_make_market(0.55),
            quality=_make_quality(0.60),
            company=company,
        )
        full_text = conviction.confidence_reasoning + " " + conviction.what_increases_conviction
        assert self._has_any_driver(full_text, _TSLA_DRIVERS), (
            f"TSLA output contains no company-specific uncertainty driver.\n"
            f"Expected one of: {_TSLA_DRIVERS}\n"
            f"Reasoning: {conviction.confidence_reasoning!r}\n"
            f"What increases: {conviction.what_increases_conviction!r}"
        )

    def test_nvda_reasoning_contains_driver(self):
        """NVDA reasoning references hyperscaler CapEx or ASIC."""
        company = _make_company("NVDA", "Technology")
        conviction = compute_conviction(
            evidence=_make_evidence("NVDA"),
            valuation=_make_valuation("overpriced", 0.40),
            macro=_make_macro(0.50),
            risk=_make_risk(0.50),
            market=_make_market(0.55),
            quality=_make_quality(0.70),
            company=company,
        )
        full_text = conviction.confidence_reasoning + " " + conviction.what_increases_conviction
        assert self._has_any_driver(full_text, _NVDA_DRIVERS), (
            f"NVDA output contains no company-specific uncertainty driver.\n"
            f"Expected one of: {_NVDA_DRIVERS}\n"
            f"Reasoning: {conviction.confidence_reasoning!r}\n"
            f"What increases: {conviction.what_increases_conviction!r}"
        )

    def test_pltr_reasoning_contains_driver(self):
        """PLTR reasoning references government contracts or commercial revenue."""
        company = _make_company("PLTR", "Technology")
        conviction = compute_conviction(
            evidence=_make_evidence("PLTR"),
            valuation=_make_valuation("overpriced", 0.35),
            macro=_make_macro(0.55),
            risk=_make_risk(0.45),
            market=_make_market(0.50),
            quality=_make_quality(0.55),
            company=company,
        )
        full_text = conviction.confidence_reasoning + " " + conviction.what_increases_conviction
        assert self._has_any_driver(full_text, _PLTR_DRIVERS), (
            f"PLTR output contains no company-specific uncertainty driver.\n"
            f"Expected one of: {_PLTR_DRIVERS}\n"
            f"Reasoning: {conviction.confidence_reasoning!r}\n"
            f"What increases: {conviction.what_increases_conviction!r}"
        )

    def test_snow_reasoning_contains_driver(self):
        """SNOW reasoning references enterprise AI spending or consumption."""
        company = _make_company("SNOW", "Technology")
        conviction = compute_conviction(
            evidence=_make_evidence("SNOW"),
            valuation=_make_valuation("overpriced", 0.40),
            macro=_make_macro(0.55),
            risk=_make_risk(0.50),
            market=_make_market(0.50),
            quality=_make_quality(0.55),
            company=company,
        )
        full_text = conviction.confidence_reasoning + " " + conviction.what_increases_conviction
        assert self._has_any_driver(full_text, _SNOW_DRIVERS), (
            f"SNOW output contains no company-specific uncertainty driver.\n"
            f"Expected one of: {_SNOW_DRIVERS}\n"
            f"Reasoning: {conviction.confidence_reasoning!r}\n"
            f"What increases: {conviction.what_increases_conviction!r}"
        )

    def test_asml_reasoning_contains_driver(self):
        """ASML reasoning references China export controls or EUV."""
        company = _make_company("ASML", "Technology")
        conviction = compute_conviction(
            evidence=_make_evidence("ASML"),
            valuation=_make_valuation("fairly_valued", 0.55),
            macro=_make_macro(0.55),
            risk=_make_risk(0.50),
            market=_make_market(0.55),
            quality=_make_quality(0.70),
            company=company,
        )
        full_text = conviction.confidence_reasoning + " " + conviction.what_increases_conviction
        assert self._has_any_driver(full_text, _ASML_DRIVERS), (
            f"ASML output contains no company-specific uncertainty driver.\n"
            f"Expected one of: {_ASML_DRIVERS}\n"
            f"Reasoning: {conviction.confidence_reasoning!r}\n"
            f"What increases: {conviction.what_increases_conviction!r}"
        )


# ══════════════════════════════════════════════════════════════════════════════
# Class 4: Reasoning non-emptiness and length
# ══════════════════════════════════════════════════════════════════════════════

class TestReasoningNonEmptiness:
    """confidence_reasoning and what_increases_conviction must be substantive."""

    @pytest.mark.parametrize("ticker", ["TSLA", "NVDA", "PLTR", "JPM", "AAPL"])
    def test_confidence_reasoning_is_non_empty(self, ticker):
        company = _make_company(ticker)
        conviction = compute_conviction(
            evidence=_make_evidence(ticker),
            valuation=_make_valuation(),
            macro=_make_macro(),
            risk=_make_risk(),
            market=_make_market(),
            quality=_make_quality(),
            company=company,
        )
        assert conviction.confidence_reasoning, (
            f"[{ticker}] confidence_reasoning is empty"
        )
        assert len(conviction.confidence_reasoning) >= 80, (
            f"[{ticker}] confidence_reasoning is too short (<80 chars): "
            f"{conviction.confidence_reasoning!r}"
        )

    @pytest.mark.parametrize("ticker", ["TSLA", "NVDA", "PLTR"])
    def test_what_increases_conviction_is_non_empty(self, ticker):
        company = _make_company(ticker)
        conviction = compute_conviction(
            evidence=_make_evidence(ticker),
            valuation=_make_valuation(),
            macro=_make_macro(),
            risk=_make_risk(),
            market=_make_market(),
            quality=_make_quality(),
            company=company,
        )
        assert conviction.what_increases_conviction, (
            f"[{ticker}] what_increases_conviction is empty"
        )
        assert len(conviction.what_increases_conviction) >= 40, (
            f"[{ticker}] what_increases_conviction too short: "
            f"{conviction.what_increases_conviction!r}"
        )


# ══════════════════════════════════════════════════════════════════════════════
# Class 5: Setup label validity
# ══════════════════════════════════════════════════════════════════════════════

class TestSetupLabelValidity:
    """setup_label must always be one of the defined valid labels."""

    @pytest.mark.parametrize("ticker,sector", [
        ("TSLA", "Consumer Discretionary"),
        ("NVDA", "Technology"),
        ("JPM",  "Financials"),
        ("VRTX", "Health Care"),
        ("PLTR", "Technology"),
        ("SNOW", "Technology"),
    ])
    def test_setup_label_is_valid(self, ticker, sector):
        company = _make_company(ticker, sector)
        conviction = compute_conviction(
            evidence=_make_evidence(ticker),
            valuation=_make_valuation(),
            macro=_make_macro(),
            risk=_make_risk(),
            market=_make_market(),
            quality=_make_quality(),
            company=company,
        )
        assert conviction.setup_label in _VALID_SETUP_LABELS, (
            f"[{ticker}] setup_label={conviction.setup_label!r} not in valid set: "
            f"{sorted(_VALID_SETUP_LABELS)}"
        )


# ══════════════════════════════════════════════════════════════════════════════
# Class 6: Score range
# ══════════════════════════════════════════════════════════════════════════════

class TestScoreRange:
    """final_score must stay within [0.20, 0.80] for all standard inputs."""

    @pytest.mark.parametrize("ticker", ["TSLA", "NVDA", "PLTR", "JPM", "AAPL"])
    def test_score_within_range(self, ticker):
        company = _make_company(ticker)
        conviction = compute_conviction(
            evidence=_make_evidence(ticker),
            valuation=_make_valuation(),
            macro=_make_macro(),
            risk=_make_risk(),
            market=_make_market(),
            quality=_make_quality(),
            company=company,
        )
        assert 0.20 <= conviction.final_score <= 0.80, (
            f"[{ticker}] final_score={conviction.final_score} out of [0.20, 0.80]"
        )


# ══════════════════════════════════════════════════════════════════════════════
# Class 7: Dominant uncertainty source in synthesizer _HARD_FAIL_CONFIDENCE_PHRASES
# ══════════════════════════════════════════════════════════════════════════════

class TestHardFailPhraseListCompleteness:
    """_HARD_FAIL_CONFIDENCE_PHRASES must include all known legacy boilerplate."""

    def test_hard_fail_list_covers_original_legacy_phrases(self):
        """Original signal_ranker.py boilerplate must be in the hard-fail list."""
        import app.services.thesis_synthesizer as ts
        phrases = ts._HARD_FAIL_CONFIDENCE_PHRASES
        required = [
            "limited evidence coverage means this position carries more uncertainty",
            "the framework is sound, the data is thin",
            "framework is sound",
            "the data is too thin to act on",
        ]
        for phrase in required:
            assert any(phrase.lower() in p.lower() or p.lower() in phrase.lower()
                      for p in phrases), (
                f"Hard-fail list missing required phrase: {phrase!r}\n"
                f"Current list: {phrases}"
            )

    def test_hard_fail_list_covers_new_generic_ai_boilerplate(self):
        """Generic AI boilerplate phrases must be blocked."""
        import app.services.thesis_synthesizer as ts
        phrases = ts._HARD_FAIL_CONFIDENCE_PHRASES
        assert any("it is important to note" in p.lower() for p in phrases), (
            "'it is important to note' not in hard-fail list"
        )
        assert any("there are many factors" in p.lower() for p in phrases), (
            "'there are many factors' not in hard-fail list"
        )

    def test_conviction_modeler_source_has_no_hardcoded_thin_phrase(self):
        """The old 'data is too thin to act on' phrase must not appear in conviction_modeler.py."""
        import inspect
        import app.services.conviction_modeler as cm
        src = inspect.getsource(cm)
        assert "data is too thin to act on" not in src, (
            "Hardcoded 'data is too thin to act on' phrase still in conviction_modeler.py source"
        )
        assert "thesis framework exists but the data" not in src, (
            "Hardcoded legacy tier_opener phrase still in conviction_modeler.py source"
        )


# ══════════════════════════════════════════════════════════════════════════════
# Class 8: Ticker uncertainty driver coverage
# ══════════════════════════════════════════════════════════════════════════════

class TestTickerUncertaintyDriverCoverage:
    """Key tickers must have company-specific uncertainty drivers configured."""

    def test_required_tickers_have_specific_drivers(self):
        """All user-critical tickers must be in _TICKER_UNCERTAINTY_DRIVERS."""
        from app.services.conviction_modeler import _TICKER_UNCERTAINTY_DRIVERS
        required = ["TSLA", "NVDA", "MSFT", "AAPL", "PLTR", "SNOW", "ASML", "JPM"]
        for ticker in required:
            assert ticker in _TICKER_UNCERTAINTY_DRIVERS, (
                f"Ticker {ticker} missing from _TICKER_UNCERTAINTY_DRIVERS"
            )
            drivers = _TICKER_UNCERTAINTY_DRIVERS[ticker]
            assert len(drivers) >= 2, (
                f"Ticker {ticker} has fewer than 2 uncertainty drivers: {drivers}"
            )

    def test_default_uncertainty_drivers_are_non_generic(self):
        """Default drivers should not be obviously boilerplate."""
        from app.services.conviction_modeler import _DEFAULT_UNCERTAINTY_DRIVERS
        boilerplate = ["macro outlook", "analyst estimate dispersion", "limited near-term"]
        for phrase in boilerplate:
            assert not any(phrase.lower() in d.lower() for d in _DEFAULT_UNCERTAINTY_DRIVERS), (
                f"Default uncertainty driver contains boilerplate phrase: {phrase!r}\n"
                f"Current drivers: {_DEFAULT_UNCERTAINTY_DRIVERS}"
            )
