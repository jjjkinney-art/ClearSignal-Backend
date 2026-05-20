"""
Regression tests: Question-anchored valuation analysis.

Tests that:
1. _detect_question_intent correctly classifies valuation stance questions
2. _run_investment_pipeline wires up question_intent through the pipeline
3. InvestmentThesis carries question_intent and valuation_stance fields
4. Schemas have the required valuation_stance fields
5. Valuation agent accepts question_intent parameter

Run with:
    pytest tests/test_question_anchored_valuation.py -v
"""
import sys
import os
import pytest
from unittest.mock import patch, MagicMock

# Ensure the project root is on the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ─────────────────────────────────────────────────────────────────────────────
# 1.  _detect_question_intent — pattern classification
# ─────────────────────────────────────────────────────────────────────────────

class TestDetectQuestionIntent:
    """Unit tests for _detect_question_intent in router_service."""

    def _detect(self, q: str) -> str:
        from app.services.router_service import _detect_question_intent
        return _detect_question_intent(q)

    # ── Valuation stance patterns ──────────────────────────────────────────
    def test_overpriced_question(self):
        assert self._detect("Is Vertex Pharmaceuticals stock overpriced?") == "valuation_stance"

    def test_overvalued_question(self):
        assert self._detect("Is NVDA overvalued at this point?") == "valuation_stance"

    def test_underpriced_question(self):
        assert self._detect("Is Apple underpriced relative to its growth?") == "valuation_stance"

    def test_fair_value_question(self):
        assert self._detect("Is MSFT trading at fair value?") == "valuation_stance"

    def test_too_expensive_question(self):
        assert self._detect("Is Tesla too expensive right now?") == "valuation_stance"

    def test_too_cheap_question(self):
        assert self._detect("Is Meta too cheap given its earnings growth?") == "valuation_stance"

    def test_worth_buying_question(self):
        assert self._detect("Is Nvidia worth buying at this price?") == "valuation_stance"

    def test_good_price_question(self):
        assert self._detect("Is AAPL at a good price right now?") == "valuation_stance"

    def test_stretched_valuation_question(self):
        assert self._detect("Does AMZN have a stretched valuation?") == "valuation_stance"

    def test_discount_to_peers_question(self):
        assert self._detect("Is JPM trading at a discount to peers?") == "valuation_stance"

    def test_premium_to_peers_question(self):
        assert self._detect("Is VRTX trading at a premium to peers?") == "valuation_stance"

    def test_fairly_priced_question(self):
        assert self._detect("Is Google fairly priced at current levels?") == "valuation_stance"

    # ── Macro sensitivity patterns ─────────────────────────────────────────
    def test_rate_impact_question(self):
        assert self._detect("How would rate hikes affect Apple stock?") == "macro_sensitivity"

    def test_inflation_impact_question(self):
        assert self._detect("What happens if inflation rises sharply?") == "macro_sensitivity"

    def test_recession_impact_question(self):
        assert self._detect("How will a recession affect Microsoft?") == "macro_sensitivity"

    # ── Risk assessment patterns ───────────────────────────────────────────
    def test_biggest_risk_question(self):
        assert self._detect("What is the biggest risk for Moderna right now?") == "risk_assessment"

    def test_downside_risk_question(self):
        assert self._detect("What is the downside risk for VRTX?") == "risk_assessment"

    # ── Competitive position patterns ──────────────────────────────────────
    def test_vs_competitor_question(self):
        assert self._detect("How does VRTX compare vs Novartis?") == "competitive_position"

    def test_market_share_question(self):
        assert self._detect("What is Nvidia's market share in AI chips?") == "competitive_position"

    # ── Default investment thesis ──────────────────────────────────────────
    def test_general_thesis_question(self):
        assert self._detect("What is the investment thesis for Vertex Pharmaceuticals?") == "investment_thesis"

    def test_earnings_question_is_default(self):
        assert self._detect("How did VRTX earnings look last quarter?") == "investment_thesis"

    def test_empty_question(self):
        assert self._detect("") == "investment_thesis"


# ─────────────────────────────────────────────────────────────────────────────
# 2.  Schema fields — valuation_stance and question_intent exist
# ─────────────────────────────────────────────────────────────────────────────

class TestSchemaValuationStanceFields:
    """Verify that schema changes from Task 3 are present."""

    def test_valuation_view_has_valuation_stance(self):
        from app.schemas import ValuationView
        v = ValuationView(overall="Test", confidence=0.5)
        assert hasattr(v, "valuation_stance"), "ValuationView must have valuation_stance field"
        assert v.valuation_stance == "", "Default should be empty string"

    def test_valuation_view_has_valuation_stance_reasoning(self):
        from app.schemas import ValuationView
        v = ValuationView(overall="Test", confidence=0.5)
        assert hasattr(v, "valuation_stance_reasoning"), (
            "ValuationView must have valuation_stance_reasoning field"
        )
        assert v.valuation_stance_reasoning == "", "Default should be empty string"

    def test_valuation_view_stance_values(self):
        from app.schemas import ValuationView
        valid_stances = {"overpriced", "fairly_valued", "underpriced", "cannot_determine", ""}
        v = ValuationView(overall="Test", confidence=0.8, valuation_stance="overpriced")
        assert v.valuation_stance in valid_stances

    def test_investment_thesis_has_valuation_stance(self):
        from app.schemas import InvestmentThesis
        t = InvestmentThesis(
            ticker="VRTX",
            company_name="Vertex Pharmaceuticals",
            bull_thesis="Bull",
            bear_thesis="Bear",
            conclusion="Neutral",
            confidence_score=0.7,
        )
        assert hasattr(t, "valuation_stance"), "InvestmentThesis must have valuation_stance"
        assert t.valuation_stance == "", "Default should be empty string"

    def test_investment_thesis_has_question_intent(self):
        from app.schemas import InvestmentThesis
        t = InvestmentThesis(
            ticker="VRTX",
            company_name="Vertex Pharmaceuticals",
            bull_thesis="Bull",
            bear_thesis="Bear",
            conclusion="Neutral",
            confidence_score=0.7,
        )
        assert hasattr(t, "question_intent"), "InvestmentThesis must have question_intent"
        assert t.question_intent == "", "Default should be empty string"

    def test_investment_thesis_intent_can_be_set(self):
        from app.schemas import InvestmentThesis
        t = InvestmentThesis(
            ticker="VRTX",
            company_name="Vertex Pharmaceuticals",
            bull_thesis="Bull",
            bear_thesis="Bear",
            conclusion="Neutral",
            confidence_score=0.7,
            question_intent="valuation_stance",
            valuation_stance="overpriced",
        )
        assert t.question_intent == "valuation_stance"
        assert t.valuation_stance == "overpriced"


# ─────────────────────────────────────────────────────────────────────────────
# 3.  Valuation agent — accepts question_intent, builds correct prompt
# ─────────────────────────────────────────────────────────────────────────────

class TestValuationAgentQuestionIntent:
    """Verify valuation_agent plumbing for question_intent."""

    def _make_company(self):
        from app.schemas import CompanyContext
        return CompanyContext(
            ticker="VRTX",
            company_name="Vertex Pharmaceuticals",
            sector="Healthcare",
            industry="Biotechnology",
        )

    def _make_evidence(self):
        from app.schemas import RetrievedEvidence
        return [RetrievedEvidence(
            title="VRTX Q4 Earnings",
            source="FMP",
            summary="Revenue beat; forward P/E at 28x.",
            relevance_score=0.9,
            timestamp="2026-01-01T00:00:00Z",
        )]

    def test_run_valuation_agent_accepts_question_intent(self):
        """run_valuation_agent must not raise when question_intent is passed."""
        from app.investment_agents.valuation_agent import run_valuation_agent
        company = self._make_company()
        evidence = self._make_evidence()

        # Mock the LLM call so we don't hit the network
        from app.schemas import ValuationView
        mock_result = ValuationView(
            overall="Test valuation.",
            confidence=0.7,
            valuation_stance="overpriced",
            valuation_stance_reasoning="Forward P/E of 28x exceeds peer median.",
        )
        with patch("app.investment_agents.valuation_agent.get_structured_response",
                   return_value=mock_result):
            result = run_valuation_agent(
                company=company,
                evidence=evidence,
                question_intent="valuation_stance",
            )
        assert result is not None
        assert isinstance(result, ValuationView)

    def test_valuation_agent_default_intent_is_none(self):
        """Without question_intent, the agent still works (no stance block injected)."""
        from app.investment_agents.valuation_agent import run_valuation_agent
        company = self._make_company()
        evidence = self._make_evidence()
        from app.schemas import ValuationView
        mock_result = ValuationView(overall="Neutral valuation.", confidence=0.6)
        with patch("app.investment_agents.valuation_agent.get_structured_response",
                   return_value=mock_result):
            result = run_valuation_agent(company=company, evidence=evidence)
        assert result is not None

    def test_build_prompt_includes_stance_block_for_valuation_intent(self):
        """_build_prompt must include stance instruction when intent=valuation_stance."""
        from app.investment_agents.valuation_agent import _build_prompt
        company = self._make_company()
        evidence = self._make_evidence()
        prompt = _build_prompt(company, evidence, question_intent="valuation_stance")
        assert "VALUATION STANCE REQUIRED" in prompt, (
            "_build_prompt must inject stance instruction block for valuation_stance intent"
        )
        assert "overpriced" in prompt.lower()
        assert "fairly_valued" in prompt.lower() or "fairly valued" in prompt.lower()

    def test_build_prompt_no_stance_block_for_default_intent(self):
        """_build_prompt must NOT inject stance block for default investment_thesis intent."""
        from app.investment_agents.valuation_agent import _build_prompt
        company = self._make_company()
        evidence = self._make_evidence()
        prompt = _build_prompt(company, evidence, question_intent="investment_thesis")
        assert "VALUATION STANCE REQUIRED" not in prompt

    def test_build_prompt_no_stance_block_when_intent_none(self):
        """_build_prompt must NOT inject stance block when question_intent is None."""
        from app.investment_agents.valuation_agent import _build_prompt
        company = self._make_company()
        evidence = self._make_evidence()
        prompt = _build_prompt(company, evidence)
        assert "VALUATION STANCE REQUIRED" not in prompt


# ─────────────────────────────────────────────────────────────────────────────
# 4.  FMP provider — fetch_valuation_ratios and fetch_analyst_estimates
# ─────────────────────────────────────────────────────────────────────────────

class TestFMPValuationEndpoints:
    """Verify the new FMP functions exist and return the right types."""

    def test_fetch_valuation_ratios_exists(self):
        from app.services.providers.fmp_provider import fetch_valuation_ratios
        assert callable(fetch_valuation_ratios)

    def test_fetch_analyst_estimates_exists(self):
        from app.services.providers.fmp_provider import fetch_analyst_estimates
        assert callable(fetch_analyst_estimates)

    def test_fetch_valuation_ratios_returns_list(self):
        """Without a real API key the function must return [] gracefully."""
        from app.services.providers.fmp_provider import fetch_valuation_ratios
        with patch("app.services.providers.fmp_provider._get_api_key", return_value=None):
            result = fetch_valuation_ratios("VRTX")
        assert isinstance(result, list)

    def test_fetch_analyst_estimates_returns_list(self):
        from app.services.providers.fmp_provider import fetch_analyst_estimates
        with patch("app.services.providers.fmp_provider._get_api_key", return_value=None):
            result = fetch_analyst_estimates("VRTX")
        assert isinstance(result, list)

    def test_fetch_valuation_ratios_items_are_retrieved_evidence(self):
        from app.services.providers.fmp_provider import fetch_valuation_ratios
        from app.schemas import RetrievedEvidence
        # Mock an API response
        mock_data = [{"peRatioTTM": 28.5, "priceToSalesRatioTTM": 14.2, "enterpriseValueMultipleTTM": 22.0}]
        with patch("app.services.providers.fmp_provider._get_api_key", return_value="fake_key"), \
             patch("app.services.providers.fmp_provider._fetch_json", return_value=mock_data):
            result = fetch_valuation_ratios("VRTX")
        assert isinstance(result, list)
        if result:
            assert isinstance(result[0], RetrievedEvidence)
            assert "VRTX" in result[0].title or "VRTX" in result[0].summary


# ─────────────────────────────────────────────────────────────────────────────
# 5.  Router pipeline — question_intent flows through end-to-end
# ─────────────────────────────────────────────────────────────────────────────

class TestRouterPipelineIntentFlow:
    """Verify _run_investment_pipeline wires question_intent through."""

    def _make_company(self):
        from app.schemas import CompanyContext
        return CompanyContext(
            ticker="VRTX",
            company_name="Vertex Pharmaceuticals",
            sector="Healthcare",
            industry="Biotechnology",
        )

    def _make_thesis(self, question_intent="valuation_stance", valuation_stance="overpriced"):
        from app.schemas import InvestmentThesis
        return InvestmentThesis(
            ticker="VRTX",
            company_name="Vertex Pharmaceuticals",
            bull_thesis="VRTX's CF franchise...",
            bear_thesis="Pipeline risk...",
            conclusion="Moderately overpriced.",
            confidence_score=0.7,
            key_drivers=["CF franchise"],
            key_risks=["pipeline risk"],
            question_intent=question_intent,
            valuation_stance=valuation_stance,
        )

    def test_detect_question_intent_imported_by_router(self):
        """_detect_question_intent must be importable from router_service."""
        from app.services.router_service import _detect_question_intent
        assert callable(_detect_question_intent)

    def test_vrtx_overpriced_question_classified_correctly(self):
        from app.services.router_service import _detect_question_intent
        intent = _detect_question_intent("Is Vertex Pharmaceuticals stock overpriced?")
        assert intent == "valuation_stance", (
            f"Expected 'valuation_stance', got {intent!r}"
        )

    def test_pipeline_stamps_question_intent_on_thesis(self):
        """_run_investment_pipeline must set thesis.question_intent from the question."""
        from app.services.router_service import _run_investment_pipeline
        from app.schemas import CompanyContext, RetrievedEvidence, ValuationView, MacroSensitivity
        from app.schemas import RiskProfile, MarketContext, QualityAssessment

        company = self._make_company()
        thesis = self._make_thesis(question_intent="valuation_stance", valuation_stance="overpriced")

        empty_ev: list = []
        mock_val = ValuationView(overall=".", confidence=0.7, valuation_stance="overpriced")
        mock_macro = MacroSensitivity(overall=".", confidence=0.6)
        mock_risk = RiskProfile(overall=".", confidence=0.6)
        mock_market = MarketContext(overall=".", confidence=0.6)
        mock_quality = QualityAssessment(overall=".", confidence=0.6)

        with patch("app.services.router_service.retrieve_market_evidence", return_value=empty_ev), \
             patch("app.services.router_service.retrieve_general_finance_evidence", return_value=empty_ev), \
             patch("app.services.router_service.fetch_valuation_ratios", return_value=empty_ev), \
             patch("app.services.router_service.fetch_analyst_estimates", return_value=empty_ev), \
             patch("app.services.router_service.get_profile_for_company", return_value=None), \
             patch("app.services.router_service.partition_evidence") as mock_part, \
             patch("app.services.router_service.run_valuation_agent", return_value=mock_val), \
             patch("app.services.router_service.run_investment_macro_agent", return_value=mock_macro), \
             patch("app.services.router_service.run_risk_agent", return_value=mock_risk), \
             patch("app.services.router_service.run_market_agent", return_value=mock_market), \
             patch("app.services.router_service.run_quality_agent", return_value=mock_quality), \
             patch("app.services.router_service.synthesize_thesis", return_value=thesis), \
             patch("app.services.router_service.watchlist_service"):

            # Set up the mock partition
            from app.services.evidence_partitioner import EvidencePartition
            mock_part.return_value = EvidencePartition(
                valuation=[], macro=[], risk=[], market=[], quality=[]
            )

            response = _run_investment_pipeline(
                company=company,
                question="Is Vertex Pharmaceuticals stock overpriced?",
                request_id="test-123",
            )

        assert response is not None
        thesis_data = response.answer.get("investment_thesis", {})
        # question_intent should be stamped — either by the pipeline directly
        # or already on the thesis from synthesize_thesis
        assert thesis_data.get("question_intent") == "valuation_stance", (
            f"question_intent not found or wrong in response: {thesis_data.get('question_intent')!r}"
        )

    def test_pipeline_calls_fetch_valuation_ratios_for_stance_question(self):
        """For valuation_stance questions, pipeline must call fetch_valuation_ratios."""
        from app.services.router_service import _run_investment_pipeline
        from app.schemas import ValuationView, MacroSensitivity, RiskProfile, MarketContext, QualityAssessment

        company = self._make_company()
        thesis = self._make_thesis()
        empty_ev: list = []

        with patch("app.services.router_service.retrieve_market_evidence", return_value=empty_ev), \
             patch("app.services.router_service.retrieve_general_finance_evidence", return_value=empty_ev), \
             patch("app.services.router_service.fetch_valuation_ratios", return_value=empty_ev) as mock_val_ratios, \
             patch("app.services.router_service.fetch_analyst_estimates", return_value=empty_ev), \
             patch("app.services.router_service.get_profile_for_company", return_value=None), \
             patch("app.services.router_service.partition_evidence") as mock_part, \
             patch("app.services.router_service.run_valuation_agent",
                   return_value=ValuationView(overall=".", confidence=0.7)), \
             patch("app.services.router_service.run_investment_macro_agent",
                   return_value=MacroSensitivity(overall=".", confidence=0.6)), \
             patch("app.services.router_service.run_risk_agent",
                   return_value=RiskProfile(overall=".", confidence=0.6)), \
             patch("app.services.router_service.run_market_agent",
                   return_value=MarketContext(overall=".", confidence=0.6)), \
             patch("app.services.router_service.run_quality_agent",
                   return_value=QualityAssessment(overall=".", confidence=0.6)), \
             patch("app.services.router_service.synthesize_thesis", return_value=thesis), \
             patch("app.services.router_service.watchlist_service"):

            from app.services.evidence_partitioner import EvidencePartition
            mock_part.return_value = EvidencePartition(
                valuation=[], macro=[], risk=[], market=[], quality=[]
            )

            _run_investment_pipeline(
                company=company,
                question="Is Vertex Pharmaceuticals stock overpriced?",
                request_id="test-456",
            )

        mock_val_ratios.assert_called_once_with("VRTX")

    def test_pipeline_does_not_call_fetch_valuation_ratios_for_default_question(self):
        """For non-stance questions, pipeline must NOT call fetch_valuation_ratios."""
        from app.services.router_service import _run_investment_pipeline
        from app.schemas import ValuationView, MacroSensitivity, RiskProfile, MarketContext, QualityAssessment

        company = self._make_company()
        thesis = self._make_thesis(question_intent="investment_thesis", valuation_stance="")
        empty_ev: list = []

        with patch("app.services.router_service.retrieve_market_evidence", return_value=empty_ev), \
             patch("app.services.router_service.retrieve_general_finance_evidence", return_value=empty_ev), \
             patch("app.services.router_service.fetch_valuation_ratios", return_value=empty_ev) as mock_val_ratios, \
             patch("app.services.router_service.fetch_analyst_estimates", return_value=empty_ev) as mock_est, \
             patch("app.services.router_service.get_profile_for_company", return_value=None), \
             patch("app.services.router_service.partition_evidence") as mock_part, \
             patch("app.services.router_service.run_valuation_agent",
                   return_value=ValuationView(overall=".", confidence=0.7)), \
             patch("app.services.router_service.run_investment_macro_agent",
                   return_value=MacroSensitivity(overall=".", confidence=0.6)), \
             patch("app.services.router_service.run_risk_agent",
                   return_value=RiskProfile(overall=".", confidence=0.6)), \
             patch("app.services.router_service.run_market_agent",
                   return_value=MarketContext(overall=".", confidence=0.6)), \
             patch("app.services.router_service.run_quality_agent",
                   return_value=QualityAssessment(overall=".", confidence=0.6)), \
             patch("app.services.router_service.synthesize_thesis", return_value=thesis), \
             patch("app.services.router_service.watchlist_service"):

            from app.services.evidence_partitioner import EvidencePartition
            mock_part.return_value = EvidencePartition(
                valuation=[], macro=[], risk=[], market=[], quality=[]
            )

            _run_investment_pipeline(
                company=company,
                question="What is the investment thesis for Vertex Pharmaceuticals?",
                request_id="test-789",
            )

        mock_val_ratios.assert_not_called()
        mock_est.assert_not_called()


# ─────────────────────────────────────────────────────────────────────────────
# 6.  Thesis synthesizer — question_intent parameter accepted
# ─────────────────────────────────────────────────────────────────────────────

class TestThesisSynthesizerQuestionIntent:
    """Verify synthesize_thesis accepts question_intent without error."""

    def _make_inputs(self):
        from app.schemas import (
            CompanyContext, ValuationView, MacroSensitivity, RiskProfile,
            MarketContext, QualityAssessment, RetrievedEvidence,
        )
        company = CompanyContext(
            ticker="VRTX", company_name="Vertex Pharmaceuticals",
            sector="Healthcare", industry="Biotechnology",
        )
        valuation = ValuationView(overall="Overpriced on multiples.", confidence=0.75,
                                  valuation_stance="overpriced",
                                  valuation_stance_reasoning="Forward P/E 28x vs peer 22x.")
        macro = MacroSensitivity(overall="Rate-insensitive.", confidence=0.6)
        risk = RiskProfile(overall="Pipeline risk.", confidence=0.65)
        market = MarketContext(overall="Strong momentum.", confidence=0.7)
        quality = QualityAssessment(overall="High quality earnings.", confidence=0.8)
        evidence = [RetrievedEvidence(
            title="VRTX ratios", source="FMP/ratios-ttm",
            summary="P/E 28x, EV/EBITDA 22x.", relevance_score=0.95,
            timestamp="2026-01-01T00:00:00Z",
        )]
        return company, valuation, macro, risk, market, quality, evidence

    def test_synthesize_thesis_accepts_question_intent_parameter(self):
        """synthesize_thesis must accept question_intent kwarg without raising."""
        from app.services.thesis_synthesizer import synthesize_thesis
        from app.schemas import InvestmentThesis

        company, valuation, macro, risk, market, quality, evidence = self._make_inputs()
        mock_thesis = InvestmentThesis(
            ticker="VRTX",
            company_name="Vertex Pharmaceuticals",
            bull_thesis="CF dominance.",
            bear_thesis="Pipeline risk.",
            conclusion="Overpriced.",
            confidence_score=0.7,
            question_intent="valuation_stance",
            valuation_stance="overpriced",
        )

        with patch("app.services.thesis_synthesizer._call_with_json_enforcement",
                   return_value=mock_thesis), \
             patch("app.services.thesis_synthesizer.rank_signals", return_value=None), \
             patch("app.services.thesis_synthesizer.check_synthesis_depth", return_value=[]), \
             patch("app.services.thesis_synthesizer.check_forbidden_phrases", return_value=[]), \
             patch("app.services.thesis_synthesizer.detect_signal_overlap", return_value=[]), \
             patch("app.services.thesis_synthesizer.polish_thesis", side_effect=lambda t, **kw: t):
            result = synthesize_thesis(
                company=company,
                valuation=valuation,
                macro=macro,
                risk=risk,
                market=market,
                quality=quality,
                evidence=evidence,
                original_user_question="Is Vertex Pharmaceuticals stock overpriced?",
                question_intent="valuation_stance",
            )

        assert result is not None
        assert isinstance(result, InvestmentThesis)

    def test_synthesize_thesis_stamps_question_intent_on_result(self):
        """synthesize_thesis must stamp question_intent on the returned thesis."""
        from app.services.thesis_synthesizer import synthesize_thesis
        from app.schemas import InvestmentThesis

        company, valuation, macro, risk, market, quality, evidence = self._make_inputs()
        mock_thesis = InvestmentThesis(
            ticker="VRTX",
            company_name="Vertex Pharmaceuticals",
            bull_thesis="CF dominance.",
            bear_thesis="Pipeline risk.",
            conclusion="Overpriced.",
            confidence_score=0.7,
        )
        # thesis starts without question_intent — synthesizer should stamp it

        with patch("app.services.thesis_synthesizer._call_with_json_enforcement",
                   return_value=mock_thesis), \
             patch("app.services.thesis_synthesizer.rank_signals", return_value=None), \
             patch("app.services.thesis_synthesizer.check_synthesis_depth", return_value=[]), \
             patch("app.services.thesis_synthesizer.check_forbidden_phrases", return_value=[]), \
             patch("app.services.thesis_synthesizer.detect_signal_overlap", return_value=[]), \
             patch("app.services.thesis_synthesizer.polish_thesis", side_effect=lambda t, **kw: t):
            result = synthesize_thesis(
                company=company,
                valuation=valuation,
                macro=macro,
                risk=risk,
                market=market,
                quality=quality,
                evidence=evidence,
                original_user_question="Is Vertex Pharmaceuticals stock overpriced?",
                question_intent="valuation_stance",
            )

        assert result.question_intent == "valuation_stance", (
            f"Expected question_intent='valuation_stance', got {result.question_intent!r}"
        )

    def test_synthesize_thesis_propagates_valuation_stance_from_agent(self):
        """synthesize_thesis must copy valuation_stance from valuation agent when LLM omits it."""
        from app.services.thesis_synthesizer import synthesize_thesis
        from app.schemas import InvestmentThesis

        company, valuation, macro, risk, market, quality, evidence = self._make_inputs()
        # LLM returns thesis without valuation_stance — synthesizer should backfill
        mock_thesis = InvestmentThesis(
            ticker="VRTX",
            company_name="Vertex Pharmaceuticals",
            bull_thesis="CF dominance.",
            bear_thesis="Pipeline risk.",
            conclusion="Overpriced.",
            confidence_score=0.7,
            valuation_stance="",  # LLM left it empty
        )

        with patch("app.services.thesis_synthesizer._call_with_json_enforcement",
                   return_value=mock_thesis), \
             patch("app.services.thesis_synthesizer.rank_signals", return_value=None), \
             patch("app.services.thesis_synthesizer.check_synthesis_depth", return_value=[]), \
             patch("app.services.thesis_synthesizer.check_forbidden_phrases", return_value=[]), \
             patch("app.services.thesis_synthesizer.detect_signal_overlap", return_value=[]), \
             patch("app.services.thesis_synthesizer.polish_thesis", side_effect=lambda t, **kw: t):
            result = synthesize_thesis(
                company=company,
                valuation=valuation,  # valuation.valuation_stance = "overpriced"
                macro=macro,
                risk=risk,
                market=market,
                quality=quality,
                evidence=evidence,
                original_user_question="Is Vertex Pharmaceuticals stock overpriced?",
                question_intent="valuation_stance",
            )

        # The synthesizer should have backfilled from the valuation agent
        assert result.valuation_stance == "overpriced", (
            f"Expected 'overpriced' propagated from valuation agent, got {result.valuation_stance!r}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# 7.  Synthesis prompt — valuation_stance intent produces correct anchor block
# ─────────────────────────────────────────────────────────────────────────────

class TestSynthesisPromptValuationStance:
    """Verify _build_synthesis_prompt generates correct block for valuation_stance."""

    def _make_inputs(self):
        from app.schemas import (
            CompanyContext, ValuationView, MacroSensitivity, RiskProfile,
            MarketContext, QualityAssessment, RetrievedEvidence,
        )
        company = CompanyContext(
            ticker="VRTX", company_name="Vertex Pharmaceuticals",
            sector="Healthcare", industry="Biotechnology",
        )
        valuation = ValuationView(
            overall="Overpriced.", confidence=0.75,
            valuation_stance="overpriced",
            valuation_stance_reasoning="P/E 28x vs peer 22x median.",
        )
        macro = MacroSensitivity(overall=".", confidence=0.6)
        risk = RiskProfile(overall=".", confidence=0.6)
        market = MarketContext(overall=".", confidence=0.6)
        quality = QualityAssessment(overall=".", confidence=0.6)
        evidence: list = []
        return company, valuation, macro, risk, market, quality, evidence

    def test_valuation_stance_prompt_requires_explicit_verdict(self):
        from app.services.thesis_synthesizer import _build_synthesis_prompt
        company, valuation, macro, risk, market, quality, evidence = self._make_inputs()
        prompt = _build_synthesis_prompt(
            company, valuation, macro, risk, market, quality, evidence,
            original_user_question="Is Vertex Pharmaceuticals stock overpriced?",
            question_intent="valuation_stance",
        )
        # Should include the valuation-stance override anchor block
        assert "VALUATION STANCE ANSWER" in prompt or "valuation_stance" in prompt.lower(), (
            "Synthesis prompt must contain valuation stance answer block for valuation_stance intent"
        )

    def test_valuation_stance_prompt_includes_verdict_options(self):
        from app.services.thesis_synthesizer import _build_synthesis_prompt
        company, valuation, macro, risk, market, quality, evidence = self._make_inputs()
        prompt = _build_synthesis_prompt(
            company, valuation, macro, risk, market, quality, evidence,
            original_user_question="Is Vertex Pharmaceuticals stock overpriced?",
            question_intent="valuation_stance",
        )
        assert "overpriced" in prompt.lower()
        assert "fairly_valued" in prompt.lower() or "fairly valued" in prompt.lower()
        assert "underpriced" in prompt.lower()
        assert "cannot_determine" in prompt.lower()

    def test_non_valuation_prompt_uses_standard_anchor_block(self):
        from app.services.thesis_synthesizer import _build_synthesis_prompt
        company, valuation, macro, risk, market, quality, evidence = self._make_inputs()
        prompt = _build_synthesis_prompt(
            company, valuation, macro, risk, market, quality, evidence,
            original_user_question="What is the investment thesis for Vertex?",
            question_intent="investment_thesis",
        )
        # Standard anchor block should appear, not valuation stance override
        assert "QUESTION-ANCHORED DIRECT ANSWER RULES" in prompt
        assert "VALUATION STANCE ANSWER" not in prompt

    def test_low_confidence_valuation_prompt_includes_caveat(self):
        """When valuation confidence < 0.45, prompt must require low-confidence caveat."""
        from app.services.thesis_synthesizer import _build_synthesis_prompt
        from app.schemas import (
            CompanyContext, ValuationView, MacroSensitivity, RiskProfile,
            MarketContext, QualityAssessment,
        )
        company = CompanyContext(
            ticker="VRTX", company_name="Vertex Pharmaceuticals",
            sector="Healthcare", industry="Biotechnology",
        )
        low_conf_valuation = ValuationView(
            overall="Insufficient evidence.", confidence=0.30,
            valuation_stance="", valuation_stance_reasoning="",
        )
        macro = MacroSensitivity(overall=".", confidence=0.6)
        risk = RiskProfile(overall=".", confidence=0.6)
        market = MarketContext(overall=".", confidence=0.6)
        quality = QualityAssessment(overall=".", confidence=0.6)

        prompt = _build_synthesis_prompt(
            company, low_conf_valuation, macro, risk, market, quality, [],
            original_user_question="Is VRTX overpriced?",
            question_intent="valuation_stance",
        )
        assert "low-confidence" in prompt.lower(), (
            "Prompt must include 'low-confidence' caveat requirement when valuation confidence < 0.45"
        )
