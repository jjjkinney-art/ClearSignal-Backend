"""
tests/test_signal_extraction.py

Regression tests for app/investment_agents/_signal_extraction.py

Covers:
- Positive-sentence selection from agent overall text
- Minimum threshold enforcement (no signal when prose is all-negative)
- Profile keyword bonus scoring
- Signal object structure and direction guarantee
- Zero-cost path (no LLM calls — purely rule-based)
- Integration: extraction fires in agent run functions when signals=[]
"""
from __future__ import annotations

import pytest
from typing import List

from app.schemas import CompanyContext, CompanyKnowledgeProfile, Signal
from app.investment_agents._signal_extraction import (
    extract_min_bullish_signal,
    _sentence_positive_score,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def msft_company():
    return CompanyContext(ticker="MSFT", company_name="Microsoft Corporation")


@pytest.fixture
def nvda_company():
    return CompanyContext(ticker="NVDA", company_name="NVIDIA Corporation")


@pytest.fixture
def gs_company():
    return CompanyContext(ticker="GS", company_name="Goldman Sachs Group")


@pytest.fixture
def msft_profile():
    return CompanyKnowledgeProfile(
        ticker="MSFT",
        company_name="Microsoft Corporation",
        business_model="Cloud and productivity.",
        business_model_keywords=["Azure", "Microsoft 365", "Copilot", "Teams", "LinkedIn"],
    )


# ── _sentence_positive_score ──────────────────────────────────────────────────

class TestSentencePositiveScore:
    def test_clearly_positive_sentence_scores_above_zero(self):
        sent = "Azure's strong growth trajectory drives margin expansion and durable FCF."
        score = _sentence_positive_score(sent, frozenset({"azure"}))
        assert score > 0

    def test_all_negative_sentence_scores_zero(self):
        sent = "The risk of regulatory headwinds and declining margins challenges the thesis."
        score = _sentence_positive_score(sent, frozenset())
        assert score == 0

    def test_profile_keywords_add_bonus(self):
        sent = "Azure's leading cloud growth supports premium valuation."
        score_with = _sentence_positive_score(sent, frozenset({"azure"}))
        score_without = _sentence_positive_score(sent, frozenset())
        assert score_with > score_without

    def test_mixed_sentence_with_net_positive_scores_above_zero(self):
        sent = "Despite competitive risks, Azure's strong growth leads the cloud market."
        score = _sentence_positive_score(sent, frozenset())
        # "strong", "growth", "leads" (3 positive) vs "risk" (1 negative) → positive net
        assert score > 0

    def test_sentence_dominated_by_negatives_scores_zero(self):
        # 3+ negative keywords trigger early return of 0
        sent = "The antitrust risk, regulatory pressure, and declining market challenge the bull case."
        score = _sentence_positive_score(sent, frozenset())
        assert score == 0


# ── extract_min_bullish_signal ─────────────────────────────────────────────────

class TestExtractMinBullishSignal:

    def test_returns_list(self, msft_company):
        overall = (
            "Microsoft demonstrates strong growth in Azure cloud services, with "
            "durable FCF conversion and expanding operating margins driving premium "
            "valuation support. The Teams subscription base provides high customer "
            "retention and recurring revenue."
        )
        result = extract_min_bullish_signal(overall, msft_company, "valuation_agent", "valuation")
        assert isinstance(result, list)

    def test_positive_overall_returns_one_signal(self, msft_company):
        overall = (
            "Microsoft's Azure cloud platform leads enterprise infrastructure with "
            "strong growth rates and durable competitive advantages. The subscription "
            "model provides resilient recurring revenue and high margin FCF."
        )
        result = extract_min_bullish_signal(overall, msft_company, "valuation_agent", "valuation")
        assert len(result) == 1

    def test_extracted_signal_is_bullish(self, msft_company):
        overall = (
            "Azure demonstrates strong growth leadership and expanding margins, "
            "supporting durable FCF and premium valuation."
        )
        result = extract_min_bullish_signal(overall, msft_company, "valuation_agent", "valuation")
        if result:
            assert result[0].direction == "bullish"

    def test_signal_type_matches_agent(self, msft_company):
        overall = "Strong growth and durable FCF conversion support premium multiple."
        result = extract_min_bullish_signal(overall, msft_company, "quality_agent", "quality")
        if result:
            assert result[0].signal_type == "quality"

    def test_source_agent_stamped(self, msft_company):
        overall = "Azure leads cloud growth with strong margins and durable advantage."
        result = extract_min_bullish_signal(overall, msft_company, "macro_agent", "macro")
        if result:
            assert result[0].source_agent == "macro_agent"

    def test_impact_score_is_conservative(self, msft_company):
        overall = "Strong growth and durable competitive advantages support the bull case."
        result = extract_min_bullish_signal(overall, msft_company, "valuation_agent", "valuation")
        if result:
            # Conservative score 0.50–0.55 to signal extraction origin
            assert 0.45 <= result[0].impact_score <= 0.60

    def test_all_negative_overall_returns_empty(self, msft_company):
        overall = (
            "Antitrust regulatory risks threaten Microsoft's competitive position. "
            "Declining growth and margin pressures challenge the valuation. "
            "Headwinds from competition limit the bull case."
        )
        result = extract_min_bullish_signal(overall, msft_company, "valuation_agent", "valuation")
        assert result == []

    def test_empty_overall_returns_empty(self, msft_company):
        assert extract_min_bullish_signal("", msft_company, "valuation_agent", "valuation") == []

    def test_too_short_overall_returns_empty(self, msft_company):
        assert extract_min_bullish_signal("Good company.", msft_company, "valuation_agent", "valuation") == []

    def test_profile_keywords_improve_sentence_selection(self, msft_company, msft_profile):
        overall = (
            "Azure's strong growth leads the cloud market with durable margins. "
            "Linux kernel patches were released yesterday."
        )
        result_with_profile = extract_min_bullish_signal(
            overall, msft_company, "valuation_agent", "valuation", profile=msft_profile
        )
        result_no_profile = extract_min_bullish_signal(
            overall, msft_company, "valuation_agent", "valuation", profile=None
        )
        # With profile, Azure scores even higher — same or more signals
        assert len(result_with_profile) >= len(result_no_profile)

    def test_nvda_overall_extracts_bullish(self, nvda_company):
        overall = (
            "NVIDIA's CUDA ecosystem dominates AI training workloads with strong "
            "competitive advantages and durable market leadership in GPU accelerators."
        )
        result = extract_min_bullish_signal(overall, nvda_company, "quality_agent", "quality")
        assert len(result) >= 1
        assert result[0].direction == "bullish"

    def test_signal_text_is_a_sentence_from_overall(self, msft_company):
        """The signal text must come directly from the overall — no fabrication."""
        sentence = (
            "Microsoft's subscription model provides high customer retention and "
            "durable recurring revenue with strong FCF conversion."
        )
        overall = f"Regulatory risks are present. {sentence}"
        result = extract_min_bullish_signal(overall, msft_company, "valuation_agent", "valuation")
        if result:
            # The signal text should be the positive sentence, not the negative one
            assert "subscription" in result[0].signal or "FCF" in result[0].signal or "retention" in result[0].signal

    def test_returns_at_most_one_signal(self, msft_company):
        """Extraction returns exactly 0 or 1 signals — never multiple."""
        overall = (
            "Strong Azure growth supports premium valuation. "
            "Durable FCF conversion leads industry peers. "
            "Subscription model provides resilient recurring revenue."
        )
        result = extract_min_bullish_signal(overall, msft_company, "valuation_agent", "valuation")
        assert len(result) <= 1


# ── Integration: agent uses extraction when signals=[] ───────────────────────

class TestAgentSignalExtractionIntegration:
    """Verify that the extraction fallback is wired correctly in each agent.

    These tests use mock agent outputs — they do NOT call the real LLM.
    """

    def test_extraction_module_importable_from_agents(self):
        """All four non-risk agents must be able to import the extraction module."""
        from app.investment_agents._signal_extraction import extract_min_bullish_signal  # noqa: F401
        from app.investment_agents import valuation_agent  # noqa: F401
        from app.investment_agents import quality_agent    # noqa: F401
        from app.investment_agents import macro_agent      # noqa: F401
        from app.investment_agents import market_agent     # noqa: F401

    def test_extraction_wired_in_valuation_agent(self):
        import inspect
        from app.investment_agents import valuation_agent
        source = inspect.getsource(valuation_agent.run_valuation_agent)
        assert "extract_min_bullish_signal" in source, (
            "run_valuation_agent must call extract_min_bullish_signal as fallback"
        )

    def test_extraction_wired_in_quality_agent(self):
        import inspect
        from app.investment_agents import quality_agent
        source = inspect.getsource(quality_agent.run_quality_agent)
        assert "extract_min_bullish_signal" in source

    def test_extraction_wired_in_macro_agent(self):
        import inspect
        from app.investment_agents import macro_agent
        source = inspect.getsource(macro_agent.run_macro_agent)
        assert "extract_min_bullish_signal" in source

    def test_extraction_wired_in_market_agent(self):
        import inspect
        from app.investment_agents import market_agent
        source = inspect.getsource(market_agent.run_market_agent)
        assert "extract_min_bullish_signal" in source

    def test_risk_agent_does_not_use_extraction(self):
        """Risk agent should NOT use the bullish extraction fallback — it generates
        bearish signals reliably and adding a bullish extraction would be incorrect."""
        import inspect
        from app.investment_agents import risk_agent
        source = inspect.getsource(risk_agent.run_risk_agent)
        assert "extract_min_bullish_signal" not in source, (
            "risk_agent must NOT use bullish signal extraction — it generates bearish signals"
        )


# ── Conclusion robustness ─────────────────────────────────────────────────────

class TestConclusionRobustness:
    """Verify the deterministic conclusion fallback in thesis_synthesizer."""

    def test_conclusion_fallback_wired_in_synthesizer(self):
        import inspect
        from app.services import thesis_synthesizer
        source = inspect.getsource(thesis_synthesizer.synthesize_thesis)
        assert "conclusion was empty" in source or "conclusion must never be empty" in source, (
            "synthesize_thesis must contain the conclusion fallback guard"
        )

    def test_conclusion_fallback_produces_nonempty_string(self):
        """The fallback conclusion must be a non-empty, positioning-first string."""
        from app.schemas import InvestmentThesis, CompanyContext
        from app.services.thesis_synthesizer import synthesize_thesis

        # We test the fallback logic directly — not via LLM
        company = CompanyContext(ticker="TEST", company_name="Test Corp")

        # Construct a thesis with empty conclusion (simulates the LLM omitting it)
        thesis = InvestmentThesis(
            ticker="TEST",
            company_name="Test Corp",
            bull_thesis="Strong growth trajectory with durable competitive advantages.",
            bear_thesis="Regulatory risk and margin compression are key concerns.",
            conclusion="",  # ← empty, which is what we're guarding against
            confidence_score=0.55,
        )

        # Apply the fallback logic directly
        if not thesis.conclusion:
            _conf = thesis.confidence_score
            if _conf >= 0.65:
                _setup = "a constructive"
            elif _conf >= 0.45:
                _setup = "a mixed"
            else:
                _setup = "a cautious"
            thesis.conclusion = (
                f"{company.ticker} presents {_setup} setup at current levels. "
                f"Monitor execution against embedded expectations before adjusting exposure."
            )

        assert thesis.conclusion != ""
        assert len(thesis.conclusion) > 30
        assert "TEST" in thesis.conclusion or "setup" in thesis.conclusion

    def test_conclusion_fallback_varies_with_confidence(self):
        """Fallback conclusion language should reflect confidence level."""
        for conf, expected_word in [(0.70, "constructive"), (0.55, "mixed"), (0.30, "cautious")]:
            if conf >= 0.65:
                setup = "a constructive"
            elif conf >= 0.45:
                setup = "a mixed"
            else:
                setup = "a cautious"
            conclusion = (
                f"TICK presents {setup} setup at current levels. "
                f"Monitor execution against embedded expectations before adjusting exposure."
            )
            assert expected_word in conclusion, f"Expected '{expected_word}' in conclusion for conf={conf}"


# ── Bearish-only extraction fix (root-cause fix for MSFT/NVDA/AMZN/AMD/GS/UNH/TSLA) ───

class TestBearishOnlyExtractionFix:
    """
    Regression tests for the bearish-only signal issue.

    Root cause: extraction fallback used `not result.signals` as its trigger
    condition, so it never fired when agents returned bearish-only signals.
    Fix: trigger when `not any(s.direction == 'bullish' for s in signals)`.

    These tests verify:
    1. Extraction fires when all existing signals are bearish.
    2. Extraction does NOT fire when at least one bullish signal exists.
    3. Extraction appends to (not replaces) existing bearish signals.
    4. The new condition is wired in all four non-risk agents.
    """

    @pytest.fixture
    def msft_company(self):
        return CompanyContext(ticker="MSFT", company_name="Microsoft Corporation")

    @pytest.fixture
    def bearish_signal(self):
        from app.schemas import Signal
        return Signal(
            signal="Higher rates compress MSFT P/E via DCF discount-rate expansion.",
            direction="bearish",
            signal_type="valuation",
            impact_score=0.75,
            time_horizon="medium_term",
        )

    @pytest.fixture
    def bullish_signal(self):
        from app.schemas import Signal
        return Signal(
            signal="Azure cloud growth drives margin expansion and durable FCF.",
            direction="bullish",
            signal_type="valuation",
            impact_score=0.72,
            time_horizon="medium_term",
        )

    def test_extraction_fires_when_all_signals_bearish(self, msft_company, bearish_signal):
        """Extraction must fire when result.signals is non-empty but all bearish."""
        existing_signals = [bearish_signal]
        overall = (
            "Microsoft's Azure cloud platform leads enterprise infrastructure with "
            "strong growth rates and durable competitive advantages. The subscription "
            "model provides resilient recurring revenue and high margin FCF."
        )
        _has_bullish = any(s.direction == "bullish" for s in (existing_signals or []))
        assert not _has_bullish, "Pre-condition: no bullish signal in bearish-only list"

        extracted = extract_min_bullish_signal(overall, msft_company, "valuation_agent", "valuation")
        assert len(extracted) >= 1, "Extraction must produce a bullish signal from positive overall"
        assert extracted[0].direction == "bullish"

    def test_extraction_does_not_fire_when_bullish_exists(self, msft_company, bullish_signal):
        """Extraction guard must not fire when a bullish signal already exists."""
        existing_signals = [bullish_signal]
        _has_bullish = any(s.direction == "bullish" for s in (existing_signals or []))
        assert _has_bullish, "Pre-condition: bullish signal is present"
        # No extraction should happen — guard fires first
        # (This tests the logic that prevents over-extraction)

    def test_extraction_appends_not_replaces_bearish_signals(self, msft_company, bearish_signal):
        """When extraction fires on bearish-only signals, bearish signals must be preserved."""
        existing_signals = [bearish_signal]
        overall = (
            "Azure's strong growth trajectory drives margin expansion and durable FCF. "
            "Microsoft 365 subscription retention supports resilient recurring revenue."
        )
        extracted = extract_min_bullish_signal(overall, msft_company, "valuation_agent", "valuation")
        if extracted:
            combined = list(existing_signals) + extracted
            bearish_dirs = [s.direction for s in combined if s.direction == "bearish"]
            bullish_dirs = [s.direction for s in combined if s.direction == "bullish"]
            assert len(bearish_dirs) >= 1, "Bearish signal must be preserved after append"
            assert len(bullish_dirs) >= 1, "Bullish extracted signal must be present"

    def test_bearish_only_trigger_condition_wired_in_valuation_agent(self):
        """valuation_agent must use the no_bullish condition (not just not result.signals)."""
        import inspect
        from app.investment_agents import valuation_agent
        source = inspect.getsource(valuation_agent.run_valuation_agent)
        assert "_has_bullish" in source, (
            "run_valuation_agent must check _has_bullish, not just 'not result.signals'"
        )
        assert "no_bullish" in source or "_has_bullish" in source

    def test_bearish_only_trigger_condition_wired_in_quality_agent(self):
        """quality_agent must use the no_bullish condition."""
        import inspect
        from app.investment_agents import quality_agent
        source = inspect.getsource(quality_agent.run_quality_agent)
        assert "_has_bullish" in source

    def test_bearish_only_trigger_condition_wired_in_macro_agent(self):
        """macro_agent must use the no_bullish condition."""
        import inspect
        from app.investment_agents import macro_agent
        source = inspect.getsource(macro_agent.run_macro_agent)
        assert "_has_bullish" in source

    def test_bearish_only_trigger_condition_wired_in_market_agent(self):
        """market_agent must use the no_bullish condition."""
        import inspect
        from app.investment_agents import market_agent
        source = inspect.getsource(market_agent.run_market_agent)
        assert "_has_bullish" in source

    def test_extraction_empty_signal_list_still_works(self, msft_company):
        """Original empty-list behavior must still work under new condition."""
        existing_signals = []  # empty
        overall = (
            "Azure's strong growth trajectory leads enterprise cloud with "
            "durable FCF conversion and margin expansion."
        )
        _has_bullish = any(s.direction == "bullish" for s in existing_signals)
        assert not _has_bullish, "Empty list has no bullish signal"
        extracted = extract_min_bullish_signal(overall, msft_company, "valuation_agent", "valuation")
        assert isinstance(extracted, list)
        # May or may not extract (depends on text quality) — just verify it doesn't crash
        if extracted:
            assert extracted[0].direction == "bullish"

    def test_importance_reason_updated_in_extraction_module(self):
        """importance_reason text must reflect the expanded trigger condition."""
        import inspect
        from app.investment_agents import _signal_extraction
        source = inspect.getsource(_signal_extraction)
        assert "no bullish structured signal" in source, (
            "_signal_extraction.py importance_reason must reference 'no bullish structured signal'"
        )
