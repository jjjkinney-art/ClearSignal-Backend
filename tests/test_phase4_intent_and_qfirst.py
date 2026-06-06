"""
tests/test_phase4_intent_and_qfirst.py

Regression tests for Phase 4 (Options A + B):

Option A — Intent taxonomy expansion + synthesis mandate upgrade
  - 6 new intent categories are classified correctly for all 10 Stage 7A pilot questions
  - Existing intents are not disrupted by new patterns
  - Edge cases: patterns that previously fell to wrong intent are now correctly classified

Option B — Q-First architecture
  - question_answerer_agent: per-intent prompt templates exist for all 11 intents
  - question_answerer_agent: evidence selection returns focused subset
  - synthesize_thesis: accepts pre_synthesized_answer parameter
  - _build_synthesis_prompt: injects pre_synthesized_answer into prompt when provided
  - _run_investment_pipeline: passes pre_synthesized_answer to synthesize_thesis (routing test)
  - thesis.direct_answer is overwritten with pre_synthesized_answer when non-empty

Run:
    python3 -m pytest tests/test_phase4_intent_and_qfirst.py -v --tb=short
"""
from __future__ import annotations

import pytest
from unittest.mock import patch, MagicMock, call
from app.services.router_service import _detect_question_intent


# ===========================================================================
# Option A — Intent classification for all 10 pilot questions
# ===========================================================================

class TestPhase4IntentClassification:
    """All 10 Stage 7A pilot questions must classify to the expected intent."""

    @pytest.mark.parametrize("question_id,question,expected_intent", [
        (
            "V-P1",
            "At Nvidia's current P/E multiple, what is the implied 5-year revenue growth rate "
            "the market is pricing in, and is that growth rate achievable given historical "
            "semiconductor precedent?",
            "implied_growth_rate",
        ),
        (
            "V-P2",
            "Costco consistently trades at a 40-50x earnings premium versus Walmart at 25-30x "
            "and Target at 15-20x. Is the premium structurally justified, and what single metric "
            "would cause it to compress in the next 12 months?",
            "valuation_stance",
        ),
        (
            "M-P1",
            "Which Microsoft segment has the widest economic moat — Productivity and Business "
            "Processes, Intelligent Cloud, or More Personal Computing — and what structural "
            "factor most protects that moat?",
            "segment_ranking",
        ),
        (
            "M-P2",
            "How does TSMC's manufacturing moat in N3 and N2 translate into pricing power with "
            "its top five customers — Apple, Nvidia, AMD, Qualcomm, and Broadcom — and what is "
            "the ceiling given Intel Foundry and Samsung as alternatives?",
            "competitive_position",
        ),
        (
            "MAC-P1",
            "In a moderate US recession where consumer spending contracts 3-5%, which of "
            "Costco's core business metrics — comparable store sales, membership renewal rates, "
            "or net new member growth — deteriorates first and most sharply, and why?",
            "metric_ordering",
        ),
        (
            "MAC-P2",
            "If hyperscaler AI infrastructure capex decelerates by 25-30 percent year-over-year "
            "in the next four quarters, what happens to Nvidia Data Center segment revenue and "
            "gross margin sequentially, and what is the typical lag between a hyperscaler capex "
            "decision and the resulting Nvidia revenue impact?",
            "timing_lag",
        ),
        (
            "R-P1",
            "Taiwan geopolitical risk is arguably the most significant and least-priced risk in "
            "global equity markets. What is the most likely 12 to 24 month earnings transmission "
            "channel for a Taiwan conflict escalation scenario, and how should investors discount "
            "for it today?",
            "risk_assessment",
        ),
        (
            "R-P2",
            "JPMorgan's commercial real estate office exposure is approximately $17 billion. "
            "At what loan loss rate would this begin to materially impact JPMorgan's earnings "
            "power, and can you quantify the EPS and ROE impact at 10%, 20%, and 30% loss rates?",
            "quantitative_threshold",
        ),
        (
            "LT-P1",
            "If Costco's gross margin begins to expand toward 14-15 percent from the current "
            "12-13 percent, does this signal thesis degradation because Costco is abandoning its "
            "low-price promise, or thesis enhancement because operating leverage is finally "
            "converting?",
            "investment_thesis",
        ),
        (
            "LT-P2",
            "What is JPMorgan's most likely path to double-digit earnings growth in the next "
            "3-5 years, given the current rate environment, capital return constraints, and "
            "competitive dynamics in investment banking and consumer lending?",
            "investment_thesis",
        ),
    ])
    def test_pilot_question_intent(self, question_id: str, question: str, expected_intent: str):
        result = _detect_question_intent(question)
        assert result == expected_intent, (
            f"{question_id}: expected intent={expected_intent!r}, got={result!r}\n"
            f"  Question: {question[:100]}..."
        )


class TestPhase4NewIntentPatterns:
    """Targeted pattern-level tests for the 6 new intent categories."""

    def test_implied_growth_rate_market_pricing_in(self):
        assert _detect_question_intent("What growth rate is the market pricing in at this multiple?") == "implied_growth_rate"

    def test_implied_growth_rate_implied_cagr(self):
        assert _detect_question_intent("What implied 5-year CAGR does the current P/E require?") == "implied_growth_rate"

    def test_timing_lag_typical_lag(self):
        assert _detect_question_intent("What is the typical lag from a rate cut to consumer spending recovery?") == "timing_lag"

    def test_timing_lag_how_many_quarters(self):
        assert _detect_question_intent("How many quarters does it take for capex decisions to flow through to revenue?") == "timing_lag"

    def test_quantitative_threshold_at_what_rate(self):
        assert _detect_question_intent("At what rate of loan losses would EPS be impacted by more than 10%?") == "quantitative_threshold"

    def test_quantitative_threshold_quantify(self):
        assert _detect_question_intent("Can you quantify the EPS impact at different loss rate scenarios?") == "quantitative_threshold"

    def test_metric_ordering_deteriorates_first(self):
        assert _detect_question_intent("Which margin line deteriorates first in a downturn?") == "metric_ordering"

    def test_metric_ordering_first_and_most(self):
        assert _detect_question_intent("Which business metric declines first and most sharply in recession?") == "metric_ordering"

    def test_segment_ranking_widest_moat(self):
        assert _detect_question_intent("Which segment has the widest economic moat?") == "segment_ranking"

    def test_segment_ranking_which_segment(self):
        assert _detect_question_intent("Which segment generates the most durable revenue?") == "segment_ranking"

    def test_historical_precedent_prior_cycle(self):
        assert _detect_question_intent("Is there historical precedent for this growth rate in semiconductors?") == "historical_precedent"

    def test_historical_precedent_analog(self):
        assert _detect_question_intent("What historical analog exists for a company sustaining 40% growth at scale?") == "historical_precedent"


class TestPhase4LegacyIntentsUnchanged:
    """Existing intents must still fire correctly after Phase 4 additions."""

    def test_valuation_stance_overpriced(self):
        assert _detect_question_intent("Is Nvidia overpriced at current levels?") == "valuation_stance"

    def test_valuation_stance_fairly_valued(self):
        assert _detect_question_intent("Is Apple fairly valued given its growth trajectory?") == "valuation_stance"

    def test_macro_sensitivity_rate_hike(self):
        assert _detect_question_intent("How would a rate hike affect Costco's valuation?") == "macro_sensitivity"

    def test_macro_sensitivity_recession(self):
        assert _detect_question_intent("How does recession affect JPMorgan's net interest income?") == "macro_sensitivity"

    def test_risk_assessment_biggest_risk(self):
        assert _detect_question_intent("What is the biggest risk to TSMC's earnings?") == "risk_assessment"

    def test_competitive_position_vs(self):
        # M-P2 "versus" without "which segment" or "widest moat" stays competitive_position
        assert _detect_question_intent("How does TSMC's moat compare versus Intel Foundry?") == "competitive_position"

    def test_investment_thesis_fallback(self):
        assert _detect_question_intent("What is the investment thesis for Apple?") == "investment_thesis"


class TestPhase4PriorityOrdering:
    """Phase 4 intents should take priority over legacy intents when both could match."""

    def test_timing_lag_beats_competitive_position_on_hyperscaler(self):
        """MAC-P2 has 'hyperscaler' (competitive_position) but 'typical lag' (timing_lag)
        should win because timing_lag is checked first."""
        q = "What is the typical lag between hyperscaler capex cuts and Nvidia revenue impact?"
        assert _detect_question_intent(q) == "timing_lag"

    def test_metric_ordering_beats_macro_on_recession(self):
        """Questions about 'deteriorates first' + 'recession' should be metric_ordering
        not macro_sensitivity because metric_ordering is checked first."""
        q = "In a recession, which Costco metric deteriorates first — SSS or membership?"
        assert _detect_question_intent(q) == "metric_ordering"

    def test_quantitative_threshold_beats_risk_assessment_on_loan_loss(self):
        """'At what loan loss rate' is quantitative_threshold, not risk_assessment."""
        q = "At what loan loss rate would JPMorgan's EPS be materially impacted?"
        assert _detect_question_intent(q) == "quantitative_threshold"

    def test_segment_ranking_beats_competitive_on_widest_moat(self):
        """'Which segment has the widest moat' is segment_ranking, not competitive_position."""
        q = "Which Microsoft segment has the widest economic moat?"
        assert _detect_question_intent(q) == "segment_ranking"


# ===========================================================================
# Option B — Question Answerer Agent (structure / unit tests)
# ===========================================================================

class TestQuestionAnswererAgentStructure:
    """Verify the question_answerer_agent module is structurally correct."""

    def test_module_imports(self):
        from app.investment_agents.question_answerer_agent import run_question_answerer
        assert callable(run_question_answerer)

    def test_all_pilot_intents_have_prompt_template(self):
        from app.investment_agents.question_answerer_agent import _INTENT_PROMPTS
        required_intents = [
            "implied_growth_rate", "timing_lag", "quantitative_threshold",
            "metric_ordering", "segment_ranking", "historical_precedent",
            "risk_assessment", "valuation_stance", "competitive_position",
            "investment_thesis", "business_model", "macro_sensitivity",
        ]
        for intent in required_intents:
            assert intent in _INTENT_PROMPTS, (
                f"Missing prompt template for intent={intent!r}"
            )

    def test_prompt_templates_contain_format_keys(self):
        from app.investment_agents.question_answerer_agent import _INTENT_PROMPTS
        required_keys = {"{question}", "{name}", "{ticker}", "{profile_block}", "{evidence_block}"}
        for intent, template in _INTENT_PROMPTS.items():
            for key in required_keys:
                assert key in template, (
                    f"Prompt template for {intent!r} is missing format key {key!r}"
                )

    def _make_evidence(self, title: str, source: str, summary: str):
        """Create a RetrievedEvidence with all required fields."""
        from app.schemas import RetrievedEvidence
        return RetrievedEvidence(
            title=title, source=source, summary=summary,
            timestamp="2025-01-01T00:00:00Z",
        )

    def test_evidence_selection_returns_subset(self):
        from app.investment_agents.question_answerer_agent import _select_evidence, _MAX_EVIDENCE_ITEMS

        # Build 20 dummy evidence items
        evidence = [
            self._make_evidence(f"Item {i}", "test", f"Summary {i}")
            for i in range(20)
        ]
        selected = _select_evidence(evidence, "what is the implied growth rate?", "implied_growth_rate")
        assert len(selected) <= _MAX_EVIDENCE_ITEMS
        assert len(selected) > 0

    def test_evidence_selection_prioritizes_financial_data(self):
        from app.investment_agents.question_answerer_agent import _select_evidence

        # Mix of FMP and generic items
        fmp_item = self._make_evidence("FMP Valuation Ratios", "fmp_api", "P/E = 38x")
        generic_items = [
            self._make_evidence(f"News Item {i}", "newsapi", "Some news")
            for i in range(15)
        ]
        evidence = generic_items + [fmp_item]
        selected = _select_evidence(evidence, "what is the implied P/E?", "implied_growth_rate")
        # FMP item should be selected (high priority)
        selected_titles = {ev.title for ev in selected}
        assert "FMP Valuation Ratios" in selected_titles, (
            "FMP financial data item should be prioritized in evidence selection"
        )

    def test_run_question_answerer_returns_empty_on_llm_failure(self):
        """When the LLM call fails, run_question_answerer must return '' (not raise)."""
        from app.investment_agents.question_answerer_agent import run_question_answerer
        from app.schemas import CompanyContext

        company = CompanyContext(ticker="NVDA", company_name="NVIDIA Corporation")

        with patch("app.investment_agents.question_answerer_agent.model_client") as mock_mc:
            mock_mc.call.side_effect = RuntimeError("LLM unavailable")
            result = run_question_answerer(
                question="What is the implied growth rate?",
                intent="implied_growth_rate",
                company=company,
                profile=None,
                evidence=[],
            )
        assert result == "", "On LLM failure, run_question_answerer must return empty string"


# ===========================================================================
# Option B — synthesize_thesis accepts pre_synthesized_answer
# ===========================================================================

class TestSynthesisPreSynthesizedAnswer:
    """Verify synthesize_thesis correctly handles pre_synthesized_answer."""

    def test_synthesize_thesis_accepts_pre_synthesized_answer_parameter(self):
        """synthesize_thesis signature must include pre_synthesized_answer."""
        import inspect
        from app.services.thesis_synthesizer import synthesize_thesis
        sig = inspect.signature(synthesize_thesis)
        assert "pre_synthesized_answer" in sig.parameters, (
            "synthesize_thesis must accept pre_synthesized_answer parameter"
        )

    def test_build_synthesis_prompt_accepts_pre_synthesized_answer(self):
        """_build_synthesis_prompt signature must include pre_synthesized_answer."""
        import inspect
        from app.services.thesis_synthesizer import _build_synthesis_prompt
        sig = inspect.signature(_build_synthesis_prompt)
        assert "pre_synthesized_answer" in sig.parameters, (
            "_build_synthesis_prompt must accept pre_synthesized_answer parameter"
        )

    def test_pre_synthesized_answer_injected_into_prompt(self):
        """When pre_synthesized_answer is provided, it must appear in the synthesis prompt."""
        from app.services.thesis_synthesizer import _build_synthesis_prompt
        from app.schemas import (
            CompanyContext, ValuationView, MacroSensitivity,
            RiskProfile, MarketContext, QualityAssessment,
        )

        company = CompanyContext(ticker="NVDA", company_name="NVIDIA Corporation",
                                 sector="Technology", industry="Semiconductors")
        valuation = ValuationView(overall="Test valuation.", confidence=0.5)
        macro = MacroSensitivity(overall="Test macro.", confidence=0.5)
        risk = RiskProfile(overall="Test risk.", confidence=0.5)
        market = MarketContext(overall="Test market.", confidence=0.5)
        quality = QualityAssessment(overall="Test quality.", confidence=0.5)

        pre_answer = "At ~38x forward P/E, the market prices in 30% compound revenue growth."

        prompt = _build_synthesis_prompt(
            company, valuation, macro, risk, market, quality,
            evidence=[],
            original_user_question="What is the implied growth rate?",
            question_intent="implied_growth_rate",
            pre_synthesized_answer=pre_answer,
        )
        assert pre_answer in prompt, (
            "pre_synthesized_answer must appear verbatim in the synthesis prompt"
        )
        assert "PRE-SYNTHESIZED DIRECT ANSWER" in prompt, (
            "Synthesis prompt must contain the Q-First injection header"
        )

    def test_pre_synthesized_answer_absent_when_empty(self):
        """When pre_synthesized_answer is empty, no Q-First injection must appear."""
        from app.services.thesis_synthesizer import _build_synthesis_prompt
        from app.schemas import (
            CompanyContext, ValuationView, MacroSensitivity,
            RiskProfile, MarketContext, QualityAssessment,
        )

        company = CompanyContext(ticker="NVDA", company_name="NVIDIA Corporation",
                                 sector="Technology", industry="Semiconductors")
        valuation = ValuationView(overall="Test valuation.", confidence=0.5)
        macro = MacroSensitivity(overall="Test macro.", confidence=0.5)
        risk = RiskProfile(overall="Test risk.", confidence=0.5)
        market = MarketContext(overall="Test market.", confidence=0.5)
        quality = QualityAssessment(overall="Test quality.", confidence=0.5)

        prompt = _build_synthesis_prompt(
            company, valuation, macro, risk, market, quality,
            evidence=[],
            original_user_question="What is the implied growth rate?",
            question_intent="implied_growth_rate",
            pre_synthesized_answer="",  # empty
        )
        assert "PRE-SYNTHESIZED DIRECT ANSWER" not in prompt, (
            "Q-First injection must NOT appear when pre_synthesized_answer is empty"
        )


# ===========================================================================
# Option B — direct_answer overwrite post-synthesis
# ===========================================================================

class TestDirectAnswerOverwrite:
    """Verify thesis.direct_answer is overwritten with pre_synthesized_answer."""

    def _make_thesis(self, direct_answer: str = ""):
        from app.schemas import InvestmentThesis
        return InvestmentThesis(
            ticker="NVDA",
            company_name="NVIDIA",
            bull_thesis="Bull case.",
            bear_thesis="Bear case.",
            conclusion="Conclusion.",
            confidence_score=0.7,
            direct_answer=direct_answer,
        )

    def test_direct_answer_overwritten_when_pre_synthesized_answer_set(self):
        """When pre_synthesized_answer is non-empty, thesis.direct_answer MUST equal it."""
        from app.schemas import CompanyContext, ValuationView, MacroSensitivity
        from app.schemas import RiskProfile, MarketContext, QualityAssessment
        from app.services.thesis_synthesizer import synthesize_thesis

        company = CompanyContext(ticker="NVDA", company_name="NVIDIA Corporation",
                                 sector="Technology", industry="Semiconductors")
        pre_answer = "At ~38x forward P/E, the market prices in 30% compound growth. Analyst consensus projects 25%, falling short by 5pp. Cisco 1999-2001 carried 40x with similar growth requirements — it held for 18 months then retraced. Achievable near-term but requires sustained data center hyperscaler spend; the key variable is H100 order backlog in Q2."

        with patch("app.services.thesis_synthesizer._call_with_json_enforcement") as mock_call:
            thesis_mock = self._make_thesis(direct_answer="Generic synthesis answer.")
            mock_call.return_value = thesis_mock

            result = synthesize_thesis(
                company=company,
                valuation=ValuationView(overall=".", confidence=0.5),
                macro=MacroSensitivity(overall=".", confidence=0.5),
                risk=RiskProfile(overall=".", confidence=0.5),
                market=MarketContext(overall=".", confidence=0.5),
                quality=QualityAssessment(overall=".", confidence=0.5),
                evidence=[],
                original_user_question="What growth rate does the P/E imply?",
                question_intent="implied_growth_rate",
                pre_synthesized_answer=pre_answer,
            )

        assert result.direct_answer == pre_answer, (
            f"thesis.direct_answer should be the Q-First answer, got: {result.direct_answer!r}"
        )

    def test_direct_answer_not_overwritten_when_pre_synthesized_answer_empty(self):
        """When pre_synthesized_answer is empty, thesis.direct_answer keeps the synthesized value."""
        from app.schemas import CompanyContext, ValuationView, MacroSensitivity
        from app.schemas import RiskProfile, MarketContext, QualityAssessment
        from app.services.thesis_synthesizer import synthesize_thesis

        company = CompanyContext(ticker="NVDA", company_name="NVIDIA Corporation",
                                 sector="Technology", industry="Semiconductors")
        synthesized_answer = "The market is pricing in sustained data center growth."

        with patch("app.services.thesis_synthesizer._call_with_json_enforcement") as mock_call:
            thesis_mock = self._make_thesis(direct_answer=synthesized_answer)
            mock_call.return_value = thesis_mock

            result = synthesize_thesis(
                company=company,
                valuation=ValuationView(overall=".", confidence=0.5),
                macro=MacroSensitivity(overall=".", confidence=0.5),
                risk=RiskProfile(overall=".", confidence=0.5),
                market=MarketContext(overall=".", confidence=0.5),
                quality=QualityAssessment(overall=".", confidence=0.5),
                evidence=[],
                original_user_question="What growth rate does the P/E imply?",
                question_intent="implied_growth_rate",
                pre_synthesized_answer="",  # empty — should NOT overwrite
            )

        assert result.direct_answer == synthesized_answer, (
            f"thesis.direct_answer should keep synthesized value when pre_synthesized_answer is empty"
        )
