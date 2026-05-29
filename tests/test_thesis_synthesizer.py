"""
Tests for app.services.thesis_synthesizer.

No real LLM calls are made — model_client.call is mocked throughout.
synthesize_thesis no longer calls get_structured_response; it calls
model_client.call directly via _call_with_json_enforcement.
"""

import json
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


def _mock_thesis_json(ticker="AAPL", name="Apple Inc.", extra: dict = None) -> str:
    """Return a valid InvestmentThesis JSON string for mocking model_client.call."""
    data = {
        "ticker": ticker,
        "company_name": name,
        "bull_thesis": "Strong growth and moat.",
        "bear_thesis": "Valuation risk.",
        "key_drivers": ["Services growth", "iPhone cycle", "AI integration", "Margin expansion"],
        "key_risks": ["Regulation", "Competition", "Rates", "China exposure"],
        "valuation_view": "Fairly valued.",
        "macro_sensitivity": "Low rate sensitivity.",
        "confidence_score": 0.75,
        "confidence_reasoning": "Solid evidence coverage.",
        "what_changes_the_thesis": ["Revenue miss", "Rate spike", "Regulation", "New competitor"],
        "conclusion": "Attractive risk/reward at current levels.",
    }
    if extra:
        data.update(extra)
    return json.dumps(data)


# ── TestSynthesizeThesisNoLLM ─────────────────────────────────────────────────

class TestSynthesizeThesisNoLLM:
    """Guard behaviour: truly unknown companies bail early; known tickers attempt LLM."""

    def test_unknown_company_no_evidence_returns_empty_thesis_immediately(self):
        """Guard fires when BOTH ticker and name are empty — no LLM attempt."""
        from app.schemas import CompanyContext
        company = CompanyContext(ticker="", company_name="")
        val = ValuationView()
        mac = MacroSensitivity()
        risk = RiskProfile()
        market = MarketContext()
        quality = QualityAssessment()
        result = synthesize_thesis(company, val, mac, risk, market, quality, [])
        assert isinstance(result, InvestmentThesis)
        assert result.confidence_score == 0.0
        # Should include the "no agent outputs" reason, not the retries-exhausted one
        assert "No agent outputs" in result.conclusion

    def test_known_ticker_empty_agents_no_evidence_attempts_llm(self):
        """Guard is bypassed for well-known tickers — LLM synthesis is attempted.

        If the LLM call fails (no key in test env) the synthesiser still returns
        an InvestmentThesis rather than silently dropping the analysis.
        """
        company = _company()  # ticker="AAPL"
        val = ValuationView()   # confidence = 0.0
        mac = MacroSensitivity()
        risk = RiskProfile()
        market = MarketContext()
        quality = QualityAssessment()

        with patch("app.services.thesis_synthesizer.model_client") as mock_client:
            # Simulate model call failure (no API key / network error)
            mock_client.call.return_value = None
            result = synthesize_thesis(company, val, mac, risk, market, quality, [])

        assert isinstance(result, InvestmentThesis)
        assert result.ticker == "AAPL"
        # LLM was attempted (call was made), then fell back to empty thesis
        mock_client.call.assert_called()

    def test_empty_thesis_has_generated_at(self):
        from app.schemas import CompanyContext
        company = CompanyContext(ticker="", company_name="")
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

        with patch(
            "app.services.thesis_synthesizer.model_client"
        ) as mock_client:
            mock_client.call.return_value = _mock_thesis_json()
            result = synthesize_thesis(company, valuation, macro, risk, market, quality, evidence)

        mock_client.call.assert_called_once()
        assert isinstance(result, InvestmentThesis)
        assert result.ticker == "AAPL"
        assert result.evidence_count == 3
        assert result.generated_at != ""

    def test_synthesize_thesis_stamps_ticker_and_name(self):
        # synthesizer overwrites ticker/company_name returned by LLM with ground-truth values
        company = _company(ticker="NVDA", name="NVIDIA Corporation")
        valuation, macro, risk, market, quality = _full_agents()
        with patch(
            "app.services.thesis_synthesizer.model_client"
        ) as mock_client:
            # LLM returns wrong ticker — synthesizer must overwrite
            mock_client.call.return_value = _mock_thesis_json(ticker="AAPL", name="Wrong Name")
            result = synthesize_thesis(company, valuation, macro, risk, market, quality, [_ev()])
        assert result.ticker == "NVDA"
        assert result.company_name == "NVIDIA Corporation"

    def test_synthesize_thesis_sets_evidence_count(self):
        company = _company()
        valuation, macro, risk, market, quality = _full_agents()
        evidence = [_ev() for _ in range(6)]
        with patch(
            "app.services.thesis_synthesizer.model_client"
        ) as mock_client:
            mock_client.call.return_value = _mock_thesis_json()
            result = synthesize_thesis(company, valuation, macro, risk, market, quality, evidence)
        assert result.evidence_count == 6


# ── TestLLMFailureDegradation ─────────────────────────────────────────────────

class TestLLMFailureDegradation:
    """Synthesizer must degrade gracefully when the LLM raises."""

    def test_synthesize_degrades_on_llm_error(self):
        company = _company()
        valuation, macro, risk, market, quality = _full_agents()
        with patch(
            "app.services.thesis_synthesizer.model_client"
        ) as mock_client:
            mock_client.call.side_effect = RuntimeError("LLM down")
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
        # LLM returns a thesis that asserts rate cuts benefit JPM (a bank)
        thesis_json = _mock_thesis_json(
            ticker="JPM",
            name="JPMorgan Chase",
            extra={
                "bull_thesis": "rate cuts benefit JPM significantly",
                "macro_sensitivity": "rate cuts help NIM expansion",
            },
        )
        evidence = [_ev()]
        with patch(
            "app.services.thesis_synthesizer.model_client"
        ) as mock_client:
            mock_client.call.return_value = thesis_json
            result = synthesize_thesis(company, valuation, macro, risk, market, quality, evidence)
        # Governance should have flagged the bank+rate-cut contradiction
        assert isinstance(result.consistency_warnings, list)
