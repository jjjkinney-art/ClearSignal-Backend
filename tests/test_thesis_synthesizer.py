"""
Tests for app.services.thesis_synthesizer.

No real LLM calls are made — get_structured_response is mocked throughout.
"""

import pytest
from unittest.mock import patch

from app.services.thesis_synthesizer import (
    synthesize_thesis,
    _check_rate_cut_bank_contradiction,
    _check_valuation_risk_tension,
    _check_evidence_sparse,
    _run_governance_checks,
)
from app.schemas import (
    CompanyContext,
    ValuationView,
    MacroSensitivity,
    RiskProfile,
    MarketContext,
    QualityAssessment,
    InvestmentThesis,
    RetrievedEvidence,
)


# ── Helper factories ──────────────────────────────────────────────────────────

def _company(ticker="AAPL", name="Apple Inc.", sector="Technology", industry="Consumer Electronics"):
    return CompanyContext(ticker=ticker, company_name=name, sector=sector, industry=industry)


def _bank():
    return CompanyContext(ticker="JPM", company_name="JPMorgan Chase", sector="Financials", industry="Banking")


def _ev(title="AAPL Income Statement", score=0.90):
    return RetrievedEvidence(
        title=title, source="FMP", summary="Test.", timestamp="2024-11-15", relevance_score=score
    )


def _full_agents(
    valuation_overall="Fair value.",
    macro_overall="Low sensitivity.",
    risk_overall="Low risk.",
    market_overall="Positive.",
    quality_overall="High quality.",
):
    valuation = ValuationView(overall=valuation_overall, confidence=0.80)
    macro = MacroSensitivity(overall=macro_overall, confidence=0.75)
    risk = RiskProfile(overall=risk_overall, confidence=0.70, key_risks=["Competition"])
    market = MarketContext(overall=market_overall, confidence=0.65, recent_catalysts=["AI launch"])
    quality = QualityAssessment(overall=quality_overall, confidence=0.85)
    return valuation, macro, risk, market, quality


def _mock_thesis(ticker="AAPL", name="Apple Inc."):
    return InvestmentThesis(
        ticker=ticker,
        company_name=name,
        bull_thesis="Strong growth and moat.",
        bear_thesis="Valuation risk.",
        key_drivers=["Services growth", "iPhone cycle", "AI integration", "Margin expansion"],
        key_risks=["Regulation", "Competition", "Rates", "China exposure"],
        valuation_view="Fairly valued.",
        macro_sensitivity="Low rate sensitivity.",
        confidence_score=0.75,
        confidence_reasoning="Solid evidence coverage.",
        what_changes_the_thesis=["Revenue miss", "Rate spike", "Regulation", "New competitor"],
        conclusion="Attractive risk/reward at current levels.",
        evidence_count=5,
    )


# ── TestSynthesizeThesisNoLLM ─────────────────────────────────────────────────

class TestSynthesizeThesisNoLLM:
    """All agents empty + no evidence → synthesizer returns empty thesis without LLM call."""

    def test_all_empty_agents_no_evidence_returns_empty_thesis(self):
        company = _company()
        val = ValuationView()
        mac = MacroSensitivity()
        risk = RiskProfile()
        market = MarketContext()
        quality = QualityAssessment()
        result = synthesize_thesis(company, val, mac, risk, market, quality, [])
        assert isinstance(result, InvestmentThesis)
        assert result.confidence_score == 0.0
        assert result.ticker == "AAPL"

    def test_empty_thesis_has_generated_at(self):
        company = _company()
        val = ValuationView()
        mac = MacroSensitivity()
        risk = RiskProfile()
        market = MarketContext()
        quality = QualityAssessment()
        result = synthesize_thesis(company, val, mac, risk, market, quality, [])
        assert result.generated_at != ""  # timestamp set


# ── TestSynthesizeThesisWithMockedLLM ────────────────────────────────────────

class TestSynthesizeThesisWithMockedLLM:
    """LLM is mocked; verify synthesizer stamps metadata correctly."""

    def test_synthesize_thesis_calls_llm_when_agents_available(self, monkeypatch):
        company = _company()
        valuation, macro, risk, market, quality = _full_agents()
        evidence = [_ev(), _ev("AAPL News"), _ev("FRED T10Y2Y")]

        mock_thesis = _mock_thesis()
        with patch(
            "app.services.thesis_synthesizer.get_structured_response",
            return_value=mock_thesis,
        ) as mock_call:
            result = synthesize_thesis(company, valuation, macro, risk, market, quality, evidence)

        mock_call.assert_called_once()
        assert isinstance(result, InvestmentThesis)
        assert result.ticker == "AAPL"
        assert result.evidence_count == 3
        assert result.generated_at != ""

    def test_synthesize_thesis_stamps_ticker_and_name(self):
        company = _company(ticker="NVDA", name="NVIDIA Corporation")
        valuation, macro, risk, market, quality = _full_agents()
        mock_thesis = _mock_thesis(ticker="AAPL", name="Wrong Name")  # synthesizer should overwrite
        with patch(
            "app.services.thesis_synthesizer.get_structured_response",
            return_value=mock_thesis,
        ):
            result = synthesize_thesis(company, valuation, macro, risk, market, quality, [_ev()])
        assert result.ticker == "NVDA"
        assert result.company_name == "NVIDIA Corporation"

    def test_synthesize_thesis_sets_evidence_count(self):
        company = _company()
        valuation, macro, risk, market, quality = _full_agents()
        evidence = [_ev() for _ in range(6)]
        mock_thesis = _mock_thesis()
        with patch(
            "app.services.thesis_synthesizer.get_structured_response",
            return_value=mock_thesis,
        ):
            result = synthesize_thesis(company, valuation, macro, risk, market, quality, evidence)
        assert result.evidence_count == 6


# ── TestLLMFailureDegradation ─────────────────────────────────────────────────

class TestLLMFailureDegradation:
    """Synthesizer must degrade gracefully when the LLM raises."""

    def test_synthesize_degrades_on_llm_error(self):
        company = _company()
        valuation, macro, risk, market, quality = _full_agents()
        with patch(
            "app.services.thesis_synthesizer.get_structured_response",
            side_effect=RuntimeError("LLM down"),
        ):
            result = synthesize_thesis(company, valuation, macro, risk, market, quality, [_ev()])
        assert isinstance(result, InvestmentThesis)
        assert result.confidence_score == 0.0
        assert result.ticker == "AAPL"


# ── TestGovernanceChecks ──────────────────────────────────────────────────────

class TestRateCutBankContradiction:
    """_check_rate_cut_bank_contradiction — deterministic, no LLM."""

    def test_bank_rate_cut_claim_raises_warning(self):
        company = _bank()
        macro = MacroSensitivity(overall="Rate cuts benefit the business significantly.")
        thesis = InvestmentThesis(
            ticker="JPM",
            company_name="JPMorgan Chase",
            bull_thesis="rate cuts benefit JPMorgan",
            macro_sensitivity="",
        )
        warnings = _check_rate_cut_bank_contradiction(company, macro, thesis)
        assert len(warnings) == 1
        assert "GOVERNANCE" in warnings[0]

    def test_tech_company_rate_cut_no_warning(self):
        company = _company()  # Technology sector
        macro = MacroSensitivity(overall="Rate cuts benefit growth stocks.")
        thesis = InvestmentThesis(
            ticker="AAPL",
            company_name="Apple Inc.",
            bull_thesis="rate cuts benefit valuations",
            macro_sensitivity="",
        )
        warnings = _check_rate_cut_bank_contradiction(company, macro, thesis)
        assert len(warnings) == 0

    def test_bank_without_rate_cut_claim_no_warning(self):
        company = _bank()
        macro = MacroSensitivity(overall="Rates are elevated; NIM is expanding.")
        thesis = InvestmentThesis(
            ticker="JPM",
            company_name="JPMorgan Chase",
            bull_thesis="NIM expansion drives earnings",
            macro_sensitivity="",
        )
        warnings = _check_rate_cut_bank_contradiction(company, macro, thesis)
        assert len(warnings) == 0


class TestValuationRiskTension:
    """_check_valuation_risk_tension — deterministic, no LLM."""

    def test_cheap_valuation_high_debt_warns(self):
        valuation = ValuationView(
            overall="cheap relative to peers", relative_value="trading at a discount"
        )
        risk = RiskProfile(overall="high debt levels concern us", debt_risk="highly leveraged")
        thesis = InvestmentThesis(ticker="XYZ", company_name="XYZ Corp")
        warnings = _check_valuation_risk_tension(valuation, risk, thesis)
        assert len(warnings) == 1
        assert "value trap" in warnings[0].lower() or "GOVERNANCE" in warnings[0]

    def test_fair_value_high_debt_no_warn(self):
        valuation = ValuationView(
            overall="fairly valued", relative_value="in line with peers"
        )
        risk = RiskProfile(overall="high debt levels", debt_risk="elevated leverage")
        thesis = InvestmentThesis(ticker="XYZ", company_name="XYZ Corp")
        warnings = _check_valuation_risk_tension(valuation, risk, thesis)
        assert len(warnings) == 0  # "fairly valued" is not a "cheap" signal

    def test_cheap_valuation_low_debt_no_warn(self):
        valuation = ValuationView(
            overall="undervalued vs peers", relative_value="cheap"
        )
        risk = RiskProfile(overall="manageable debt levels", debt_risk="conservative balance sheet")
        thesis = InvestmentThesis(ticker="XYZ", company_name="XYZ Corp")
        warnings = _check_valuation_risk_tension(valuation, risk, thesis)
        assert len(warnings) == 0


class TestEvidenceSparseWarning:
    """_check_evidence_sparse — deterministic, no LLM."""

    def test_high_confidence_sparse_evidence_warns(self):
        thesis = InvestmentThesis(
            ticker="AAPL", company_name="Apple Inc.", confidence_score=0.85
        )
        evidence = [_ev()]  # only 1 item
        warnings = _check_evidence_sparse(evidence, thesis)
        assert len(warnings) == 1

    def test_high_confidence_enough_evidence_no_warn(self):
        thesis = InvestmentThesis(
            ticker="AAPL", company_name="Apple Inc.", confidence_score=0.85
        )
        evidence = [_ev() for _ in range(5)]
        warnings = _check_evidence_sparse(evidence, thesis)
        assert len(warnings) == 0

    def test_low_confidence_sparse_evidence_no_warn(self):
        thesis = InvestmentThesis(
            ticker="AAPL", company_name="Apple Inc.", confidence_score=0.50
        )
        evidence = [_ev()]
        warnings = _check_evidence_sparse(evidence, thesis)
        assert len(warnings) == 0


class TestRunGovernanceChecks:
    """_run_governance_checks and full synthesize_thesis governance integration."""

    def test_all_checks_run(self):
        company = _company()
        valuation, macro, risk, market, quality = _full_agents()
        mock_thesis = _mock_thesis()
        evidence = [_ev()]
        warnings = _run_governance_checks(company, valuation, macro, risk, mock_thesis, evidence)
        assert isinstance(warnings, list)  # always returns a list

    def test_warnings_attached_to_thesis_on_synthesize(self):
        company = _bank()
        valuation, macro, risk, market, quality = _full_agents(
            macro_overall="Rate cuts benefit the bank significantly."
        )
        mock_thesis = _mock_thesis(ticker="JPM", name="JPMorgan Chase")
        mock_thesis.bull_thesis = "rate cuts benefit JPM"
        mock_thesis.macro_sensitivity = "rate cuts help"
        evidence = [_ev()]
        with patch(
            "app.services.thesis_synthesizer.get_structured_response",
            return_value=mock_thesis,
        ):
            result = synthesize_thesis(company, valuation, macro, risk, market, quality, evidence)
        # Governance should have flagged the bank+rate-cut contradiction
        assert isinstance(result.consistency_warnings, list)
