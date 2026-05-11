"""
Tests for the five investment specialist agents in app.investment_agents.

All LLM calls are mocked (monkeypatched). No network calls are made.
"""
from __future__ import annotations

import pytest
from unittest.mock import patch

from app.investment_agents import (
    run_valuation_agent,
    run_macro_agent,
    run_risk_agent,
    run_market_agent,
    run_quality_agent,
)
from app.schemas import (
    CompanyContext,
    ValuationView,
    MacroSensitivity,
    RiskProfile,
    MarketContext,
    QualityAssessment,
    RetrievedEvidence,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _company(ticker="AAPL", name="Apple Inc.", sector="Technology"):
    """Return a minimal CompanyContext for tests."""
    return CompanyContext(ticker=ticker, company_name=name, sector=sector)


def _ev(title, source="FMP", summary="Test summary", score=0.90):
    """Return a minimal RetrievedEvidence item."""
    return RetrievedEvidence(
        title=title,
        source=source,
        summary=summary,
        timestamp="2024-11-15",
        relevance_score=score,
    )


# ---------------------------------------------------------------------------
# TestGracefulDegradationNoEvidence
# ---------------------------------------------------------------------------


class TestGracefulDegradationNoEvidence:
    """Each agent must degrade gracefully when given an empty evidence list."""

    def test_valuation_agent_empty_evidence_returns_valuation_view(self):
        result = run_valuation_agent(_company(), evidence=[])
        assert isinstance(result, ValuationView)

    def test_valuation_agent_empty_evidence_has_zero_confidence(self):
        result = run_valuation_agent(_company(), evidence=[])
        assert result.confidence == 0.0

    def test_valuation_agent_empty_evidence_overall_not_empty(self):
        result = run_valuation_agent(_company(), evidence=[])
        assert len(result.overall) > 0

    def test_macro_agent_empty_evidence_returns_macro_sensitivity(self):
        result = run_macro_agent(_company(), evidence=[])
        assert isinstance(result, MacroSensitivity)

    def test_macro_agent_empty_evidence_has_zero_confidence(self):
        result = run_macro_agent(_company(), evidence=[])
        assert result.confidence == 0.0

    def test_macro_agent_empty_evidence_overall_not_empty(self):
        result = run_macro_agent(_company(), evidence=[])
        assert len(result.overall) > 0

    def test_risk_agent_empty_evidence_returns_risk_profile(self):
        result = run_risk_agent(_company(), evidence=[])
        assert isinstance(result, RiskProfile)

    def test_risk_agent_empty_evidence_has_zero_confidence(self):
        result = run_risk_agent(_company(), evidence=[])
        assert result.confidence == 0.0

    def test_risk_agent_empty_evidence_overall_not_empty(self):
        result = run_risk_agent(_company(), evidence=[])
        assert len(result.overall) > 0

    def test_market_agent_empty_evidence_returns_market_context(self):
        result = run_market_agent(_company(), evidence=[])
        assert isinstance(result, MarketContext)

    def test_market_agent_empty_evidence_has_zero_confidence(self):
        result = run_market_agent(_company(), evidence=[])
        assert result.confidence == 0.0

    def test_market_agent_empty_evidence_overall_not_empty(self):
        result = run_market_agent(_company(), evidence=[])
        assert len(result.overall) > 0

    def test_quality_agent_empty_evidence_returns_quality_assessment(self):
        result = run_quality_agent(_company(), evidence=[])
        assert isinstance(result, QualityAssessment)

    def test_quality_agent_empty_evidence_has_zero_confidence(self):
        result = run_quality_agent(_company(), evidence=[])
        assert result.confidence == 0.0

    def test_quality_agent_empty_evidence_overall_not_empty(self):
        result = run_quality_agent(_company(), evidence=[])
        assert len(result.overall) > 0


# ---------------------------------------------------------------------------
# TestNoRelevantEvidence
# ---------------------------------------------------------------------------


class TestNoRelevantEvidence:
    """Each agent should degrade when evidence exists but contains zero relevant items.

    Evidence items used here are specifically designed so that:
    - The title does NOT contain the ticker or company name.
    - The title and source contain no keywords from the agent's domain list.
    This forces the filter to return an empty list, causing graceful degradation.
    """

    # Valuation agent keywords include: income, revenue, earnings, eps, p/e, margin,
    # profitability, financial, fmp, price change, stock price.
    # An item about FRED macro data with no company name should be filtered out.
    def test_valuation_agent_pure_macro_evidence_returns_degraded(self):
        ev = _ev(
            "10-Year Minus 2-Year Treasury Spread: +0.49 pp",
            source="FRED (Federal Reserve Bank of St. Louis)",
        )
        result = run_valuation_agent(_company(), evidence=[ev])
        assert isinstance(result, ValuationView)
        assert result.confidence == 0.0

    # Macro agent keywords include: fred, treasury, yield, inflation, cpi, pce,
    # fed funds, federal reserve, recession, gdp, vix, credit spread, t10y2y, dgs.
    # A news item with no company name and no macro keyword should be filtered out.
    def test_macro_agent_pure_news_headline_returns_degraded(self):
        ev = _ev(
            "Smartphone industry sees competitive pressures",
            source="TechBlog",
        )
        result = run_macro_agent(_company(), evidence=[ev])
        assert isinstance(result, MacroSensitivity)
        assert result.confidence == 0.0

    # Risk agent keywords include: sec, edgar, 10-k, 10-q, annual report,
    # quarterly report, filing, debt, balance sheet, liability, leverage, risk.
    # A VIX data point has none of these and no company name.
    def test_risk_agent_pure_vix_evidence_returns_degraded(self):
        ev = _ev(
            "CBOE Volatility Index (VIXCLS): 22.5",
            source="FRED (Federal Reserve Bank of St. Louis)",
        )
        result = run_risk_agent(_company(), evidence=[ev])
        assert isinstance(result, RiskProfile)
        assert result.confidence == 0.0

    # Market agent keywords include: news, newsapi, bloomberg, reuters, cnbc,
    # catalyst, guidance, earnings beat, earnings miss, analyst, upgrade,
    # downgrade, price change.
    # A raw FRED treasury series has none of these and no company name.
    def test_market_agent_pure_fred_evidence_returns_degraded(self):
        ev = _ev(
            "10-Year Treasury Constant Maturity Rate: 4.3%",
            source="FRED (Federal Reserve Bank of St. Louis)",
        )
        result = run_market_agent(_company(), evidence=[ev])
        assert isinstance(result, MarketContext)
        assert result.confidence == 0.0

    # Quality agent keywords include: profile, company profile, fmp, business,
    # revenue, free cash flow, fcf, buyback, dividend, r&d, research,
    # intellectual property, subscription, recurring.
    # A generic news story with no company name or quality keyword should be filtered.
    def test_quality_agent_pure_news_headline_returns_degraded(self):
        ev = _ev(
            "Central banks signal caution on rate cuts",
            source="Reuters",
        )
        result = run_quality_agent(_company(), evidence=[ev])
        assert isinstance(result, QualityAssessment)
        assert result.confidence == 0.0


# ---------------------------------------------------------------------------
# TestEvidenceRouting — company-name match always passes the filter
# ---------------------------------------------------------------------------


class TestEvidenceRouting:
    """Evidence whose title contains the company name always passes the filter.

    This tests that the 'is_company_match' branch works correctly for each agent:
    any evidence title containing the company name is included regardless of domain
    keywords, meaning the LLM path would be called if we mock get_structured_response.
    We verify the schema type is correct (the mock is only reached when evidence passes).
    """

    def test_valuation_agent_accepts_company_name_in_title(self):
        """Evidence with company name in title is always relevant to valuation agent."""
        ev = _ev("Apple Inc. Annual Report (10-K)", source="SEC EDGAR")
        mock_output = ValuationView(
            overall="Valuation analysis based on filing.", confidence=0.55
        )
        with patch(
            "app.investment_agents.valuation_agent.get_structured_response",
            return_value=mock_output,
        ):
            result = run_valuation_agent(_company(), evidence=[ev])
        assert isinstance(result, ValuationView)
        assert result.confidence == pytest.approx(0.55)

    def test_macro_agent_accepts_company_name_in_title(self):
        """Evidence with company name in title is always relevant to macro agent."""
        ev = _ev("Apple Inc. Macro Outlook Q4 2024", source="Goldman Sachs")
        mock_output = MacroSensitivity(
            overall="Company-specific macro commentary.", confidence=0.45
        )
        with patch(
            "app.investment_agents.macro_agent.get_structured_response",
            return_value=mock_output,
        ):
            result = run_macro_agent(_company(), evidence=[ev])
        assert isinstance(result, MacroSensitivity)
        assert result.confidence == pytest.approx(0.45)

    def test_risk_agent_accepts_company_name_in_title(self):
        """Evidence with company name in title is always relevant to risk agent."""
        ev = _ev("Apple Inc. 10-K Annual Report", source="SEC EDGAR")
        mock_output = RiskProfile(
            overall="Risk analysis from filing.", confidence=0.70
        )
        with patch(
            "app.investment_agents.risk_agent.get_structured_response",
            return_value=mock_output,
        ):
            result = run_risk_agent(_company(), evidence=[ev])
        assert isinstance(result, RiskProfile)
        assert result.confidence == pytest.approx(0.70)

    def test_market_agent_accepts_company_name_in_title(self):
        """Evidence with company name in title is always relevant to market agent."""
        ev = _ev("Apple Inc. stock rises 3% on strong earnings", source="CNBC")
        mock_output = MarketContext(
            overall="Positive price action on earnings beat.", confidence=0.60
        )
        with patch(
            "app.investment_agents.market_agent.get_structured_response",
            return_value=mock_output,
        ):
            result = run_market_agent(_company(), evidence=[ev])
        assert isinstance(result, MarketContext)
        assert result.confidence == pytest.approx(0.60)

    def test_quality_agent_accepts_company_name_in_title(self):
        """Evidence with company name in title is always relevant to quality agent."""
        ev = _ev("Apple Inc. Business Quality Overview", source="Morgan Stanley")
        mock_output = QualityAssessment(
            overall="Strong moat from brand and ecosystem.", confidence=0.80
        )
        with patch(
            "app.investment_agents.quality_agent.get_structured_response",
            return_value=mock_output,
        ):
            result = run_quality_agent(_company(), evidence=[ev])
        assert isinstance(result, QualityAssessment)
        assert result.confidence == pytest.approx(0.80)


# ---------------------------------------------------------------------------
# TestLLMCallMocked
# ---------------------------------------------------------------------------


class TestLLMCallMocked:
    """When relevant evidence exists, agents should call LLM and return its output."""

    def test_valuation_agent_calls_llm_when_evidence_available(self):
        """FMP income statement and price-change evidence should be domain-relevant."""
        fmp_ev = _ev("Apple Inc. Income Statement FY2024", source="FMP")
        price_ev = _ev("Apple price change +5.2%", source="FMP")

        mock_output = ValuationView(
            pe_assessment="P/E at 28x, in line with sector median.",
            growth_view="Revenue grew 6% YoY.",
            overall="Fairly valued at current multiples.",
            confidence=0.82,
        )

        with patch(
            "app.investment_agents.valuation_agent.get_structured_response",
            return_value=mock_output,
        ):
            result = run_valuation_agent(_company(), evidence=[fmp_ev, price_ev])

        assert isinstance(result, ValuationView)
        assert result.confidence == pytest.approx(0.82)
        # evidence_used is populated with titles by the agent after LLM call
        assert result.evidence_used

    def test_macro_agent_calls_llm_when_fred_evidence_available(self):
        """FRED treasury evidence matches the 'treasury' and 'yield' keywords."""
        fred_ev = _ev(
            "10-Year Minus 2-Year Treasury Spread: +0.49 pp",
            source="FRED (Federal Reserve Bank of St. Louis)",
        )

        mock_output = MacroSensitivity(
            rate_sensitivity="Mildly rate sensitive due to DCF-heavy valuation.",
            overall="Moderate macro sensitivity.",
            confidence=0.75,
        )
        with patch(
            "app.investment_agents.macro_agent.get_structured_response",
            return_value=mock_output,
        ):
            result = run_macro_agent(_company(), evidence=[fred_ev])

        assert isinstance(result, MacroSensitivity)
        assert result.confidence == pytest.approx(0.75)

    def test_risk_agent_calls_llm_when_sec_evidence_available(self):
        """SEC EDGAR annual report triggers the 'sec', 'edgar', and '10-k' keywords."""
        sec_ev = _ev("Apple Inc. Annual Report (10-K)", source="SEC EDGAR")

        mock_output = RiskProfile(
            overall="Manageable risks.",
            key_risks=["Competition", "Regulation"],
            confidence=0.70,
        )
        with patch(
            "app.investment_agents.risk_agent.get_structured_response",
            return_value=mock_output,
        ):
            result = run_risk_agent(_company(), evidence=[sec_ev])

        assert isinstance(result, RiskProfile)
        assert result.confidence == pytest.approx(0.70)
        assert result.evidence_used

    def test_market_agent_calls_llm_when_news_available(self):
        """News source 'NewsAPI/Bloomberg' matches the 'newsapi' and 'bloomberg' keywords."""
        news_ev = _ev("Apple launches new iPhone", source="NewsAPI/Bloomberg")

        mock_output = MarketContext(
            momentum="Positive momentum.",
            overall="Bullish near-term.",
            confidence=0.65,
            recent_catalysts=["iPhone launch"],
        )
        with patch(
            "app.investment_agents.market_agent.get_structured_response",
            return_value=mock_output,
        ):
            result = run_market_agent(_company(), evidence=[news_ev])

        assert isinstance(result, MarketContext)
        assert result.confidence == pytest.approx(0.65)

    def test_quality_agent_calls_llm_when_profile_available(self):
        """'Apple Inc. Company Profile' matches on company name in title AND 'profile' keyword."""
        profile_ev = _ev("Apple Inc. Company Profile", source="FMP")

        mock_output = QualityAssessment(
            moat="Strong brand moat.",
            overall="High quality business.",
            confidence=0.88,
        )
        with patch(
            "app.investment_agents.quality_agent.get_structured_response",
            return_value=mock_output,
        ):
            result = run_quality_agent(_company(), evidence=[profile_ev])

        assert isinstance(result, QualityAssessment)
        assert result.confidence == pytest.approx(0.88)

    def test_valuation_agent_evidence_used_populated_with_titles(self):
        """evidence_used should contain the evidence title(s) after a successful LLM call."""
        ev = _ev("Apple Inc. Income Statement FY2024", source="FMP")
        mock_output = ValuationView(overall="Fairly valued.", confidence=0.70)

        with patch(
            "app.investment_agents.valuation_agent.get_structured_response",
            return_value=mock_output,
        ):
            result = run_valuation_agent(_company(), evidence=[ev])

        assert len(result.evidence_used) >= 1
        # Titles are stored truncated to 70 chars
        assert any("Apple Inc. Income Statement" in t for t in result.evidence_used)

    def test_risk_agent_evidence_used_populated(self):
        sec_ev = _ev("Apple Inc. Annual Report (10-K)", source="SEC EDGAR")
        mock_output = RiskProfile(overall="Low risk.", confidence=0.65)

        with patch(
            "app.investment_agents.risk_agent.get_structured_response",
            return_value=mock_output,
        ):
            result = run_risk_agent(_company(), evidence=[sec_ev])

        assert len(result.evidence_used) >= 1

    def test_market_agent_evidence_used_populated(self):
        news_ev = _ev("Apple launches new iPhone", source="NewsAPI/Bloomberg")
        mock_output = MarketContext(overall="Positive.", confidence=0.55)

        with patch(
            "app.investment_agents.market_agent.get_structured_response",
            return_value=mock_output,
        ):
            result = run_market_agent(_company(), evidence=[news_ev])

        assert len(result.evidence_used) >= 1

    def test_quality_agent_evidence_used_populated(self):
        profile_ev = _ev("Apple Inc. Company Profile", source="FMP")
        mock_output = QualityAssessment(overall="High quality.", confidence=0.80)

        with patch(
            "app.investment_agents.quality_agent.get_structured_response",
            return_value=mock_output,
        ):
            result = run_quality_agent(_company(), evidence=[profile_ev])

        assert len(result.evidence_used) >= 1


# ---------------------------------------------------------------------------
# TestLLMFailureDegradation
# ---------------------------------------------------------------------------


class TestLLMFailureDegradation:
    """Agents must catch LLM exceptions and degrade gracefully."""

    def test_valuation_agent_degrades_on_llm_exception(self):
        fmp_ev = _ev("Apple Inc. Income Statement FY2024", source="FMP")
        with patch(
            "app.investment_agents.valuation_agent.get_structured_response",
            side_effect=RuntimeError("LLM unavailable"),
        ):
            result = run_valuation_agent(_company(), evidence=[fmp_ev])
        assert isinstance(result, ValuationView)
        assert result.confidence == 0.0

    def test_macro_agent_degrades_on_llm_exception(self):
        fred_ev = _ev(
            "10-Year Minus 2-Year Treasury Spread: +0.49 pp",
            source="FRED (Federal Reserve Bank of St. Louis)",
        )
        with patch(
            "app.investment_agents.macro_agent.get_structured_response",
            side_effect=RuntimeError("LLM unavailable"),
        ):
            result = run_macro_agent(_company(), evidence=[fred_ev])
        assert isinstance(result, MacroSensitivity)
        assert result.confidence == 0.0

    def test_risk_agent_degrades_on_llm_exception(self):
        sec_ev = _ev("Apple Inc. Annual Report (10-K)", source="SEC EDGAR")
        with patch(
            "app.investment_agents.risk_agent.get_structured_response",
            side_effect=ConnectionError("Network failure"),
        ):
            result = run_risk_agent(_company(), evidence=[sec_ev])
        assert isinstance(result, RiskProfile)
        assert result.confidence == 0.0

    def test_market_agent_degrades_on_llm_exception(self):
        news_ev = _ev("Apple launches new iPhone", source="NewsAPI/Bloomberg")
        with patch(
            "app.investment_agents.market_agent.get_structured_response",
            side_effect=TimeoutError("Request timed out"),
        ):
            result = run_market_agent(_company(), evidence=[news_ev])
        assert isinstance(result, MarketContext)
        assert result.confidence == 0.0

    def test_quality_agent_degrades_on_llm_exception(self):
        profile_ev = _ev("Apple Inc. Company Profile", source="FMP")
        with patch(
            "app.investment_agents.quality_agent.get_structured_response",
            side_effect=ValueError("Bad response"),
        ):
            result = run_quality_agent(_company(), evidence=[profile_ev])
        assert isinstance(result, QualityAssessment)
        assert result.confidence == 0.0

    def test_valuation_agent_degraded_output_is_nonempty(self):
        """The 'overall' field in degraded output should explain the failure."""
        fmp_ev = _ev("Apple Inc. Income Statement FY2024", source="FMP")
        with patch(
            "app.investment_agents.valuation_agent.get_structured_response",
            side_effect=RuntimeError("LLM unavailable"),
        ):
            result = run_valuation_agent(_company(), evidence=[fmp_ev])
        assert len(result.overall) > 0

    def test_macro_agent_degraded_output_is_nonempty(self):
        fred_ev = _ev(
            "10-Year Minus 2-Year Treasury Spread: +0.49 pp",
            source="FRED (Federal Reserve Bank of St. Louis)",
        )
        with patch(
            "app.investment_agents.macro_agent.get_structured_response",
            side_effect=RuntimeError("LLM unavailable"),
        ):
            result = run_macro_agent(_company(), evidence=[fred_ev])
        assert len(result.overall) > 0


# ---------------------------------------------------------------------------
# TestDomainKeywordMatching
# ---------------------------------------------------------------------------


class TestDomainKeywordMatching:
    """Verify that each agent's keyword-based filter accepts the right evidence sources."""

    # --- Valuation agent ---

    def test_valuation_accepts_fmp_source_keyword(self):
        """Source 'FMP' matches the 'fmp' keyword in the valuation agent."""
        ev = _ev("Some generic headline", source="FMP")
        mock_output = ValuationView(overall="Analysis.", confidence=0.5)
        with patch(
            "app.investment_agents.valuation_agent.get_structured_response",
            return_value=mock_output,
        ):
            result = run_valuation_agent(_company(), evidence=[ev])
        assert result.confidence == pytest.approx(0.5)

    def test_valuation_accepts_earnings_keyword_in_title(self):
        ev = _ev("Q3 earnings summary and EPS estimates", source="Morningstar")
        mock_output = ValuationView(overall=".", confidence=0.4)
        with patch(
            "app.investment_agents.valuation_agent.get_structured_response",
            return_value=mock_output,
        ):
            result = run_valuation_agent(_company(), evidence=[ev])
        assert result.confidence == pytest.approx(0.4)

    # --- Macro agent ---

    def test_macro_accepts_fred_source_keyword(self):
        """Source containing 'fred' matches the macro agent."""
        ev = _ev("Unemployment rate: 3.8%", source="FRED (Federal Reserve Bank of St. Louis)")
        mock_output = MacroSensitivity(overall=".", confidence=0.5)
        with patch(
            "app.investment_agents.macro_agent.get_structured_response",
            return_value=mock_output,
        ):
            result = run_macro_agent(_company(), evidence=[ev])
        assert result.confidence == pytest.approx(0.5)

    def test_macro_accepts_inflation_keyword_in_title(self):
        ev = _ev("CPI inflation rose 3.2% year-over-year", source="BLS")
        mock_output = MacroSensitivity(overall=".", confidence=0.6)
        with patch(
            "app.investment_agents.macro_agent.get_structured_response",
            return_value=mock_output,
        ):
            result = run_macro_agent(_company(), evidence=[ev])
        assert result.confidence == pytest.approx(0.6)

    # --- Risk agent ---

    def test_risk_accepts_sec_in_source(self):
        """Source 'SEC EDGAR' matches the 'sec' and 'edgar' keywords."""
        ev = _ev("Generic company filings overview", source="SEC EDGAR")
        mock_output = RiskProfile(overall=".", confidence=0.5)
        with patch(
            "app.investment_agents.risk_agent.get_structured_response",
            return_value=mock_output,
        ):
            result = run_risk_agent(_company(), evidence=[ev])
        assert result.confidence == pytest.approx(0.5)

    def test_risk_accepts_debt_keyword_in_title(self):
        ev = _ev("Corporate debt levels at historic highs", source="Bloomberg")
        mock_output = RiskProfile(overall=".", confidence=0.45)
        with patch(
            "app.investment_agents.risk_agent.get_structured_response",
            return_value=mock_output,
        ):
            result = run_risk_agent(_company(), evidence=[ev])
        assert result.confidence == pytest.approx(0.45)

    # --- Market agent ---

    def test_market_accepts_newsapi_in_source(self):
        """Source 'NewsAPI/Bloomberg' matches the 'newsapi' keyword."""
        ev = _ev("Tech sector rallies ahead of Fed meeting", source="NewsAPI/Bloomberg")
        mock_output = MarketContext(overall=".", confidence=0.5)
        with patch(
            "app.investment_agents.market_agent.get_structured_response",
            return_value=mock_output,
        ):
            result = run_market_agent(_company(), evidence=[ev])
        assert result.confidence == pytest.approx(0.5)

    def test_market_accepts_analyst_keyword_in_title(self):
        ev = _ev("Analyst upgrades tech sector to overweight", source="Barclays")
        mock_output = MarketContext(overall=".", confidence=0.55)
        with patch(
            "app.investment_agents.market_agent.get_structured_response",
            return_value=mock_output,
        ):
            result = run_market_agent(_company(), evidence=[ev])
        assert result.confidence == pytest.approx(0.55)

    # --- Quality agent ---

    def test_quality_accepts_profile_keyword_in_title(self):
        ev = _ev("Sector company profile and fundamentals", source="Morningstar")
        mock_output = QualityAssessment(overall=".", confidence=0.5)
        with patch(
            "app.investment_agents.quality_agent.get_structured_response",
            return_value=mock_output,
        ):
            result = run_quality_agent(_company(), evidence=[ev])
        assert result.confidence == pytest.approx(0.5)

    def test_quality_accepts_fmp_source_keyword(self):
        """Source 'FMP' matches the 'fmp' keyword in the quality agent."""
        ev = _ev("Generic sector overview", source="FMP")
        mock_output = QualityAssessment(overall=".", confidence=0.4)
        with patch(
            "app.investment_agents.quality_agent.get_structured_response",
            return_value=mock_output,
        ):
            result = run_quality_agent(_company(), evidence=[ev])
        assert result.confidence == pytest.approx(0.4)


# ---------------------------------------------------------------------------
# TestOutputSchemaFields
# ---------------------------------------------------------------------------


class TestOutputSchemaFields:
    """Verify that mocked LLM output fields pass through to the returned object."""

    def test_valuation_agent_all_fields_propagate(self):
        ev = _ev("Apple Inc. Income Statement FY2024", source="FMP")
        mock_output = ValuationView(
            pe_assessment="P/E 28x",
            growth_view="Revenue +6%",
            margin_trend="Stable margins",
            discount_sensitivity="Moderate sensitivity",
            relative_value="In line with peers",
            overall="Fairly valued.",
            confidence=0.80,
        )
        with patch(
            "app.investment_agents.valuation_agent.get_structured_response",
            return_value=mock_output,
        ):
            result = run_valuation_agent(_company(), evidence=[ev])
        assert result.pe_assessment == "P/E 28x"
        assert result.growth_view == "Revenue +6%"
        assert result.margin_trend == "Stable margins"
        assert result.overall == "Fairly valued."

    def test_macro_agent_all_fields_propagate(self):
        ev = _ev(
            "10-Year Minus 2-Year Treasury Spread",
            source="FRED (Federal Reserve Bank of St. Louis)",
        )
        mock_output = MacroSensitivity(
            rate_sensitivity="High",
            inflation_sensitivity="Medium",
            recession_risk="Low",
            cyclicality="Defensive",
            overall="Mildly sensitive.",
            confidence=0.70,
        )
        with patch(
            "app.investment_agents.macro_agent.get_structured_response",
            return_value=mock_output,
        ):
            result = run_macro_agent(_company(), evidence=[ev])
        assert result.rate_sensitivity == "High"
        assert result.cyclicality == "Defensive"
        assert result.overall == "Mildly sensitive."

    def test_risk_agent_key_risks_list_propagates(self):
        ev = _ev("Apple Inc. Annual Report (10-K)", source="SEC EDGAR")
        mock_output = RiskProfile(
            key_risks=["Antitrust regulation", "Supply chain"],
            overall="Manageable.",
            confidence=0.65,
        )
        with patch(
            "app.investment_agents.risk_agent.get_structured_response",
            return_value=mock_output,
        ):
            result = run_risk_agent(_company(), evidence=[ev])
        assert result.key_risks == ["Antitrust regulation", "Supply chain"]

    def test_market_agent_recent_catalysts_list_propagates(self):
        ev = _ev("Apple launches new iPhone", source="NewsAPI/Bloomberg")
        mock_output = MarketContext(
            recent_catalysts=["iPhone launch", "Strong guidance"],
            overall="Bullish.",
            confidence=0.60,
        )
        with patch(
            "app.investment_agents.market_agent.get_structured_response",
            return_value=mock_output,
        ):
            result = run_market_agent(_company(), evidence=[ev])
        assert result.recent_catalysts == ["iPhone launch", "Strong guidance"]

    def test_quality_agent_moat_field_propagates(self):
        ev = _ev("Apple Inc. Company Profile", source="FMP")
        mock_output = QualityAssessment(
            moat="Ecosystem lock-in and brand premium",
            overall="High quality.",
            confidence=0.85,
        )
        with patch(
            "app.investment_agents.quality_agent.get_structured_response",
            return_value=mock_output,
        ):
            result = run_quality_agent(_company(), evidence=[ev])
        assert result.moat == "Ecosystem lock-in and brand premium"
