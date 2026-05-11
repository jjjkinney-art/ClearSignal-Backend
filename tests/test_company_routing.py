"""Tests for company-specific routing in route_question().

Verifies that questions mentioning a known company AND investment intent
route to the investment_thesis pipeline (5 specialist agents + synthesizer)
instead of run_general_finance_agent, while macro-only questions still use
the general finance path.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest

from app.schemas import (
    CompanyContext,
    CompanyKnowledgeProfile,
    InvestmentThesis,
    MacroSensitivity,
    MarketContext,
    QualityAssessment,
    RiskProfile,
    ValuationView,
)


# ---------------------------------------------------------------------------
# Helpers / Fixtures
# ---------------------------------------------------------------------------

def _make_company(ticker: str = "AAPL", name: str = "Apple Inc.") -> CompanyContext:
    return CompanyContext(ticker=ticker, company_name=name, sector="Technology")


def _make_profile(ticker: str = "AAPL") -> CompanyKnowledgeProfile:
    return CompanyKnowledgeProfile(
        ticker=ticker,
        company_name="Apple Inc.",
        business_model="Premium hardware and services.",
        primary_revenue_drivers=["iPhone", "Services"],
        recurring_revenue_sources=["App Store", "iCloud"],
        rate_sensitivity_note="Premium multiple compresses when rates rise.",
        inflation_pass_through="Strong pricing power.",
        recession_behavior="iPhone upgrades extend in recessions.",
        major_risks=["China", "Regulation"],
        valuation_style="~28x P/E",
        key_metrics=["Services revenue", "iPhone ASP"],
        competitive_advantages=["Ecosystem lock-in"],
        business_model_keywords=["iPhone", "Services", "App Store"],
    )


def _make_thesis(ticker: str = "AAPL") -> InvestmentThesis:
    return InvestmentThesis(
        ticker=ticker,
        company_name="Apple Inc.",
        bull_thesis="Apple's Services margin drives p/e expansion.",
        bear_thesis="iPhone saturation weighs on revenue growth.",
        conclusion="AAPL is a high-quality compounder at a premium valuation.",
        confidence_score=0.75,
        key_drivers=["Services growth", "iPhone ASP"],
        key_risks=["China exposure", "Regulation"],
    )


def _make_valuation() -> ValuationView:
    return ValuationView(summary="AAPL at ~28x P/E, Services margin 72%.", confidence=0.7)


def _make_macro() -> MacroSensitivity:
    return MacroSensitivity(overall="Rate-sensitive premium multiple.", confidence=0.6)


def _make_risk() -> RiskProfile:
    return RiskProfile(overall="China revenue ~19% is main risk.", confidence=0.65)


def _make_market() -> MarketContext:
    return MarketContext(overall="iPhone installed base 1.2B, strong.", confidence=0.7)


def _make_quality() -> QualityAssessment:
    return QualityAssessment(overall="95% FCF conversion, AA- credit.", confidence=0.75)


def _minimal_request(question: str, company_name: str = "", intent: str = "") -> Any:
    """Build a minimal QuestionRequest-like object for testing."""
    from app.schemas import QuestionRequest
    return QuestionRequest(
        question=question,
        company_name=company_name,
        intent=intent or None,
    )


# ---------------------------------------------------------------------------
# Patch helpers
# ---------------------------------------------------------------------------

def _patch_investment_pipeline():
    """Return a context-manager stack patching all investment pipeline pieces."""
    from unittest.mock import patch
    patches = [
        patch(
            "app.services.router_service.detect_company",
            return_value=_make_company(),
        ),
        patch(
            "app.services.router_service.get_profile_for_company",
            return_value=_make_profile(),
        ),
        patch(
            "app.services.router_service.retrieve_market_evidence",
            return_value=[],
        ),
        patch(
            "app.services.router_service.retrieve_general_finance_evidence",
            return_value=[],
        ),
        patch(
            "app.services.router_service.partition_evidence",
            return_value=MagicMock(valuation=[], macro=[], risk=[], market=[], quality=[]),
        ),
        patch(
            "app.services.router_service.run_valuation_agent",
            return_value=_make_valuation(),
        ),
        patch(
            "app.services.router_service.run_investment_macro_agent",
            return_value=_make_macro(),
        ),
        patch(
            "app.services.router_service.run_risk_agent",
            return_value=_make_risk(),
        ),
        patch(
            "app.services.router_service.run_market_agent",
            return_value=_make_market(),
        ),
        patch(
            "app.services.router_service.run_quality_agent",
            return_value=_make_quality(),
        ),
        patch(
            "app.services.router_service.synthesize_thesis",
            return_value=_make_thesis(),
        ),
    ]
    return patches


# ---------------------------------------------------------------------------
# TestCompanyRouteDetection
# ---------------------------------------------------------------------------

class TestCompanyRouteDetection:
    """Company questions with investment intent should route to investment_thesis."""

    def _call_with_patches(self, question: str, company_name: str = "") -> Any:
        from app.services.router_service import route_question
        patches = _patch_investment_pipeline()
        # Start all patches
        mocks = [p.start() for p in patches]
        try:
            req = _minimal_request(question, company_name=company_name)
            response = route_question(req)
        finally:
            for p in patches:
                p.stop()
        return response

    def test_apple_rates_routes_to_investment_thesis(self):
        """'How would higher interest rates affect Apple stock?' → investment_thesis."""
        response = self._call_with_patches(
            "How would higher interest rates affect Apple stock?"
        )
        assert response.routing.get("pipeline") == "investment_thesis"

    def test_investment_thesis_pipeline_label(self):
        """Response agents_used should include thesis_synthesizer."""
        response = self._call_with_patches(
            "Is Apple stock a good investment at current valuations?"
        )
        assert "thesis_synthesizer" in response.agents_used

    def test_answer_contains_investment_thesis_key(self):
        """Response answer dict should have 'investment_thesis' key."""
        response = self._call_with_patches(
            "What is the bull and bear case for Apple stock?"
        )
        assert "investment_thesis" in response.answer

    def test_detected_ticker_in_routing(self):
        """Routing metadata should include detected_ticker."""
        response = self._call_with_patches(
            "How does inflation affect Apple's earnings?"
        )
        assert response.routing.get("detected_ticker") == "AAPL"

    def test_company_name_in_routing(self):
        """Routing metadata should include detected_company."""
        response = self._call_with_patches(
            "What are the risks for Apple stock?"
        )
        assert response.routing.get("detected_company") == "Apple Inc."

    def test_all_five_agents_in_agents_used(self):
        """All 5 specialist agents should be listed in agents_used."""
        response = self._call_with_patches(
            "How would rate hikes impact Apple's valuation and earnings?"
        )
        for agent in ["valuation", "macro", "risk", "market", "quality"]:
            assert agent in response.agents_used

    def test_nvda_routes_to_investment_thesis(self):
        """NVIDIA question routes to investment path (detecting NVDA company)."""
        patches = _patch_investment_pipeline()
        # Override detect_company to return NVDA
        patches[0] = patch(
            "app.services.router_service.detect_company",
            return_value=CompanyContext(ticker="NVDA", company_name="NVIDIA Corporation", sector="Technology"),
        )
        mocks = [p.start() for p in patches]
        try:
            from app.services.router_service import route_question
            req = _minimal_request("How would AI demand slowdown affect NVIDIA stock?")
            response = route_question(req)
        finally:
            for p in patches:
                p.stop()
        assert response.routing.get("pipeline") == "investment_thesis"

    def test_microsoft_recession_routes_to_investment(self):
        """Microsoft + recession question routes to investment_thesis."""
        patches = _patch_investment_pipeline()
        patches[0] = patch(
            "app.services.router_service.detect_company",
            return_value=CompanyContext(ticker="MSFT", company_name="Microsoft Corporation", sector="Technology"),
        )
        mocks = [p.start() for p in patches]
        try:
            from app.services.router_service import route_question
            req = _minimal_request("How would a recession affect Microsoft's cloud revenue?")
            response = route_question(req)
        finally:
            for p in patches:
                p.stop()
        assert response.routing.get("pipeline") == "investment_thesis"


# ---------------------------------------------------------------------------
# TestMacroOnlyQuestionsUseGeneralPath
# ---------------------------------------------------------------------------

class TestMacroOnlyQuestionsUseGeneralPath:
    """Pure macro questions with no company detected should use general finance."""

    def _call_with_no_company_detected(self, question: str) -> Any:
        """Patch detect_company to return None (no company detected)."""
        from app.services.router_service import route_question

        # We also need to mock the general finance agent to avoid real LLM calls
        from app.schemas import GeneralFinanceAnswer

        fake_answer = GeneralFinanceAnswer(
            answer="Treasury yields rise when bond prices fall as the Fed signals tighter policy.",
            bullets=["Higher yields raise discount rates.", "Yield curve can invert."],
            caveats=["Context matters."],
        )
        fake_answer.evidence_count = 0

        with (
            patch("app.services.router_service.detect_company", return_value=None),
            patch("app.services.router_service.run_general_finance_agent", return_value=fake_answer),
            patch("app.services.router_service.run_general_fallback_agent", return_value=fake_answer),
        ):
            req = _minimal_request(question)
            return route_question(req)

    def test_treasury_yield_question_uses_general_path(self):
        """'Why are Treasury yields rising?' → general finance path."""
        response = self._call_with_no_company_detected("Why are Treasury yields rising?")
        # Should NOT be investment_thesis
        assert response.routing.get("pipeline") != "investment_thesis"

    def test_yield_curve_question_uses_general_path(self):
        """'Why is the yield curve inverted?' → general finance path."""
        response = self._call_with_no_company_detected("Why is the yield curve inverted?")
        assert response.routing.get("pipeline") != "investment_thesis"

    def test_generic_inflation_question_uses_general_path(self):
        """'How does inflation affect stocks?' → general finance path."""
        response = self._call_with_no_company_detected("How does inflation affect stocks?")
        assert response.routing.get("pipeline") != "investment_thesis"

    def test_general_path_response_has_general_key(self):
        """General path response should have 'general' key in answer."""
        response = self._call_with_no_company_detected("Why are interest rates so high?")
        assert "general" in response.answer


# ---------------------------------------------------------------------------
# TestInvestmentIntentHelper
# ---------------------------------------------------------------------------

class TestInvestmentIntentHelper:
    """Unit tests for _has_investment_intent()."""

    def test_stock_keyword_triggers_intent(self):
        from app.services.router_service import _has_investment_intent
        assert _has_investment_intent("How would higher rates affect Apple stock?")

    def test_affect_keyword_triggers_intent(self):
        from app.services.router_service import _has_investment_intent
        assert _has_investment_intent("How would inflation affect Apple earnings?")

    def test_invest_keyword_triggers_intent(self):
        from app.services.router_service import _has_investment_intent
        assert _has_investment_intent("Is Tesla a good investment right now?")

    def test_valuation_keyword_triggers_intent(self):
        from app.services.router_service import _has_investment_intent
        assert _has_investment_intent("Is Apple's valuation stretched?")

    def test_pure_yield_question_no_intent(self):
        from app.services.router_service import _has_investment_intent
        # "rates" is in the keywords, so this will match — but detect_company
        # returning None is the real gate. This test is about intent detection.
        # "Why are Treasury yields rising?" does contain "rates" via "yield"
        # but let's check a truly macro-only question:
        assert not _has_investment_intent("Why is the yield curve inverted?")

    def test_treasury_yields_no_investment_intent(self):
        from app.services.router_service import _has_investment_intent
        # This should NOT trigger investment intent on its own
        result = _has_investment_intent("Why are Treasury yields rising today?")
        # This question contains no investment-specific nouns — no stock/share/invest etc.
        # "rates" is a keyword but "Treasury yields rising" is pure macro.
        # The actual gating depends on company detection, but intent-alone:
        assert not result

    def test_bull_thesis_triggers_intent(self):
        from app.services.router_service import _has_investment_intent
        assert _has_investment_intent("What is the bull case for NVDA?")

    def test_how_would_triggers_intent(self):
        from app.services.router_service import _has_investment_intent
        assert _has_investment_intent("How would a rate hike affect Apple?")


# ---------------------------------------------------------------------------
# TestCompanyDetectionGate
# ---------------------------------------------------------------------------

class TestCompanyDetectionGate:
    """When detect_company returns None, investment pipeline is NOT called."""

    def test_no_company_detected_never_calls_investment_pipeline(self):
        """If detect_company returns None, synthesize_thesis is never called."""
        from app.schemas import GeneralFinanceAnswer
        fake_answer = GeneralFinanceAnswer(
            answer="Rates affect growth stocks through the discount rate mechanism.",
            bullets=["Higher rates → lower PV of future earnings."],
            caveats=["Direction matters."],
        )
        fake_answer.evidence_count = 0

        synthesize_mock = MagicMock()
        with (
            patch("app.services.router_service.detect_company", return_value=None),
            patch("app.services.router_service.synthesize_thesis", synthesize_mock),
            patch("app.services.router_service.run_general_finance_agent", return_value=fake_answer),
            patch("app.services.router_service.run_general_fallback_agent", return_value=fake_answer),
        ):
            from app.services.router_service import route_question
            req = _minimal_request("How do rates affect growth stocks?")
            route_question(req)

        synthesize_mock.assert_not_called()

    def test_company_detected_but_no_intent_skips_investment_pipeline(self):
        """Company detected but no investment intent → should not call investment pipeline.

        This tests the _has_investment_intent gate: even with a company detected,
        if the question has no investment keywords, we fall through to general path.

        Note: this depends on what 'no intent' questions look like — e.g.,
        'Tell me about Apple' doesn't have investment intent keywords like
        'stock', 'invest', 'valuation', 'affect', etc.  But because "about"
        isn't in our intent list and it may still match via company routing
        depending on specific wording, we test a clearly non-investment question.
        """
        from app.schemas import GeneralFinanceAnswer
        fake_answer = GeneralFinanceAnswer(
            answer="Apple is a technology company.",
            bullets=[],
            caveats=[],
        )
        fake_answer.evidence_count = 0

        synthesize_mock = MagicMock()
        with (
            patch("app.services.router_service.detect_company", return_value=_make_company()),
            patch("app.services.router_service._has_investment_intent", return_value=False),
            patch("app.services.router_service.synthesize_thesis", synthesize_mock),
            patch("app.services.router_service.run_general_finance_agent", return_value=fake_answer),
            patch("app.services.router_service.run_general_fallback_agent", return_value=fake_answer),
        ):
            from app.services.router_service import route_question
            req = _minimal_request("Tell me about Apple.")
            route_question(req)

        synthesize_mock.assert_not_called()
