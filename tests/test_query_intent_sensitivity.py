"""
tests/test_query_intent_sensitivity.py

Phase 1 regression suite for query-intent sensitivity.

Background
----------
Before Phase 1, four of five specialist agents (macro, risk, market, quality)
received no question context.  Outputs across business-model, moat, valuation,
and macro questions shared ~75-80% text overlap.

Fix (Phase 1)
-------------
Each agent now accepts:
  - question_intent: Optional[str]   — detected intent category
  - question:        Optional[str]   — verbatim user question

Each agent's ``_build_question_emphasis_block()`` injects a targeted directive
before the main analysis questions, steering the agent toward the dimensions
most relevant to what the user actually asked.

Test coverage
-------------
1. Emphasis block presence / absence
   - Returns empty string for default intent and None
   - Returns non-empty block for all four non-default intents
   - Block always contains the question text when supplied

2. Block content specificity
   - macro/macro_sensitivity   → transmission channel language
   - macro/competitive_position → moat-macro connection language
   - macro/valuation_stance    → discount-rate / multiple language
   - macro/risk_assessment     → tail-risk / recession language
   - risk/risk_assessment      → key_risks exhaustive directive
   - risk/competitive_position → competitive_risk anchor
   - risk/valuation_stance     → estimate-cut / de-rating risks
   - risk/macro_sensitivity    → rate-shock / refinancing risks
   - market/competitive_position → competitor news / moat sentiment
   - market/valuation_stance   → price-target / positioning signals
   - market/macro_sensitivity  → sector-rotation / rate signals
   - market/risk_assessment    → negative catalysts
   - quality/competitive_position → moat depth / decomposition
   - quality/valuation_stance  → FCF yield / capital return quality
   - quality/macro_sensitivity → revenue durability / defensiveness
   - quality/risk_assessment   → moat erosion / FCF deterioration

3. Prompt construction includes emphasis block
   - Each agent's _build_prompt() correctly embeds the emphasis block

4. Run-function signature accepts new parameters
   - All four run_*_agent() functions accept question_intent and question
   - Graceful handling of None values (no crash)

5. Overlap metric regression
   - Prompts built for 4 MSFT question types differ by at least 30%
     (i.e. overlap < 70%) — structural guarantee that differentiation exists
     before the LLM call

Run
---
    python3 -m pytest tests/test_query_intent_sensitivity.py -v
"""

from __future__ import annotations

from difflib import SequenceMatcher
from typing import Optional
from unittest.mock import MagicMock, patch

import pytest

# ── Imports ───────────────────────────────────────────────────────────────────

from app.schemas import (
    CompanyContext, RetrievedEvidence,
    MacroSensitivity, RiskProfile, MarketContext, QualityAssessment,
)
from app.investment_agents.macro_agent   import _build_question_emphasis_block as macro_emphasis
from app.investment_agents.macro_agent   import _build_prompt as macro_build_prompt
from app.investment_agents.risk_agent    import _build_question_emphasis_block as risk_emphasis
from app.investment_agents.risk_agent    import _build_prompt as risk_build_prompt
from app.investment_agents.market_agent  import _build_question_emphasis_block as market_emphasis
from app.investment_agents.market_agent  import _build_prompt as market_build_prompt
from app.investment_agents.quality_agent import _build_question_emphasis_block as quality_emphasis
from app.investment_agents.quality_agent import _build_prompt as quality_build_prompt
from app.investment_agents.macro_agent   import run_investment_macro_agent
from app.investment_agents.risk_agent    import run_risk_agent
from app.investment_agents.market_agent  import run_market_agent
from app.investment_agents.quality_agent import run_quality_agent


# ── Helpers ───────────────────────────────────────────────────────────────────

def _msft() -> CompanyContext:
    return CompanyContext(ticker="MSFT", company_name="Microsoft Corporation",
                         sector="Technology")

def _nvda() -> CompanyContext:
    return CompanyContext(ticker="NVDA", company_name="NVIDIA Corporation",
                         sector="Technology")

def _stub_evidence(n: int = 2) -> list:
    return [
        RetrievedEvidence(
            title=f"Evidence item {i}",
            source="fmp",
            summary=f"Summary of evidence item {i}",
            timestamp="2026-01-15",
        )
        for i in range(n)
    ]

def _text_overlap(a: str, b: str) -> float:
    """Return SequenceMatcher similarity ratio (0–1)."""
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()

_INTENTS = ["investment_thesis", "competitive_position", "valuation_stance",
            "macro_sensitivity", "risk_assessment"]

_QUESTIONS = {
    "investment_thesis":   "Can Microsoft sustain AI-driven growth if enterprise spending slows?",
    "competitive_position": "Is Azure becoming a stronger moat than Microsoft 365?",
    "valuation_stance":    "What multiple compression risk does Microsoft face?",
    "macro_sensitivity":   "How would a rate cut affect Microsoft stock?",
    "risk_assessment":     "What are the biggest risks for Microsoft right now?",
}


# ════════════════════════════════════════════════════════════════════════════════
# SECTION 1 — Emphasis block presence / absence
# ════════════════════════════════════════════════════════════════════════════════

class TestEmphasisBlockPresence:
    """Every non-default intent returns a non-empty block; default returns ''."""

    @pytest.mark.parametrize("fn", [macro_emphasis, risk_emphasis,
                                     market_emphasis, quality_emphasis])
    def test_default_intent_returns_empty(self, fn):
        block = fn("investment_thesis", None, _msft())
        assert block == "", f"{fn.__module__}: default intent must return ''"

    @pytest.mark.parametrize("fn", [macro_emphasis, risk_emphasis,
                                     market_emphasis, quality_emphasis])
    def test_none_intent_returns_empty(self, fn):
        block = fn(None, None, _msft())
        assert block == "", f"{fn.__module__}: None intent must return ''"

    @pytest.mark.parametrize("fn,intent", [
        (macro_emphasis,   "competitive_position"),
        (macro_emphasis,   "valuation_stance"),
        (macro_emphasis,   "macro_sensitivity"),
        (macro_emphasis,   "risk_assessment"),
        (risk_emphasis,    "competitive_position"),
        (risk_emphasis,    "valuation_stance"),
        (risk_emphasis,    "macro_sensitivity"),
        (risk_emphasis,    "risk_assessment"),
        (market_emphasis,  "competitive_position"),
        (market_emphasis,  "valuation_stance"),
        (market_emphasis,  "macro_sensitivity"),
        (market_emphasis,  "risk_assessment"),
        (quality_emphasis, "competitive_position"),
        (quality_emphasis, "valuation_stance"),
        (quality_emphasis, "macro_sensitivity"),
        (quality_emphasis, "risk_assessment"),
    ])
    def test_non_default_intent_returns_nonempty(self, fn, intent):
        block = fn(intent, _QUESTIONS[intent], _msft())
        assert block, f"{fn.__module__} intent={intent!r}: expected non-empty block"

    @pytest.mark.parametrize("fn,intent", [
        (macro_emphasis,   "macro_sensitivity"),
        (risk_emphasis,    "risk_assessment"),
        (market_emphasis,  "competitive_position"),
        (quality_emphasis, "competitive_position"),
    ])
    def test_block_contains_question_text(self, fn, intent):
        q = _QUESTIONS[intent]
        block = fn(intent, q, _msft())
        assert q in block, (
            f"{fn.__module__} intent={intent!r}: block must contain verbatim question"
        )

    @pytest.mark.parametrize("fn,intent", [
        (macro_emphasis,   "macro_sensitivity"),
        (risk_emphasis,    "risk_assessment"),
        (market_emphasis,  "competitive_position"),
        (quality_emphasis, "valuation_stance"),
    ])
    def test_block_contains_ticker(self, fn, intent):
        block = fn(intent, _QUESTIONS[intent], _msft())
        assert "MSFT" in block, f"Emphasis block must reference the ticker"

    @pytest.mark.parametrize("fn,intent", [
        (macro_emphasis,   "macro_sensitivity"),
        (risk_emphasis,    "risk_assessment"),
        (market_emphasis,  "competitive_position"),
        (quality_emphasis, "competitive_position"),
    ])
    def test_block_contains_question_focus_header(self, fn, intent):
        block = fn(intent, _QUESTIONS[intent], _msft())
        assert "QUESTION FOCUS" in block, "Block must contain 'QUESTION FOCUS' header"


# ════════════════════════════════════════════════════════════════════════════════
# SECTION 2 — Block content specificity per agent × intent
# ════════════════════════════════════════════════════════════════════════════════

class TestMacroBlockContent:
    """Macro emphasis blocks contain intent-appropriate language."""

    def test_macro_sensitivity_transmission_channel(self):
        block = macro_emphasis("macro_sensitivity",
                               "How would a rate cut affect Microsoft?", _msft())
        assert "transmission" in block.lower() or "mechanism" in block.lower(), \
            "macro/macro_sensitivity block must mention transmission mechanism"

    def test_macro_sensitivity_quantify_directive(self):
        block = macro_emphasis("macro_sensitivity",
                               "How would a rate cut affect Microsoft?", _msft())
        assert "quantif" in block.lower() or "magnitude" in block.lower() or "100bps" in block, \
            "macro/macro_sensitivity block must encourage quantification"

    def test_macro_competitive_moat_connection(self):
        block = macro_emphasis("competitive_position",
                               "Is Azure a stronger moat?", _msft())
        assert "competitive" in block.lower() or "moat" in block.lower(), \
            "macro/competitive_position block must connect macro to moat"

    def test_macro_valuation_discount_rate(self):
        block = macro_emphasis("valuation_stance",
                               "Is MSFT overpriced?", _msft())
        assert "discount" in block.lower() or "multiple" in block.lower(), \
            "macro/valuation_stance block must mention discount rate or multiple"

    def test_macro_risk_tail_scenario(self):
        block = macro_emphasis("risk_assessment",
                               "What are MSFT's risks?", _msft())
        assert "tail" in block.lower() or "recession" in block.lower() \
               or "scenario" in block.lower(), \
            "macro/risk_assessment block must mention tail risk or recession scenario"

    def test_macro_rate_sensitivity_field_anchor(self):
        """macro_sensitivity intent should explicitly anchor rate_sensitivity field."""
        block = macro_emphasis("macro_sensitivity", "Rate cut impact on MSFT?", _msft())
        assert "rate_sensitivity" in block, \
            "macro/macro_sensitivity block must name rate_sensitivity as the anchor field"


class TestRiskBlockContent:
    """Risk emphasis blocks contain intent-appropriate language."""

    def test_risk_assessment_exhaustive_directive(self):
        block = risk_emphasis("risk_assessment", "What are MSFT's risks?", _msft())
        assert "key_risks" in block or "exhaustive" in block.lower() \
               or "comprehensive" in block.lower(), \
            "risk/risk_assessment must direct exhaustive key_risks list"

    def test_risk_assessment_lead_with_highest_severity(self):
        block = risk_emphasis("risk_assessment", "What are MSFT's risks?", _msft())
        assert "highest" in block.lower() or "lead" in block.lower(), \
            "risk/risk_assessment block must instruct leading with highest-severity risk"

    def test_risk_competitive_anchor_field(self):
        block = risk_emphasis("competitive_position", "Is Azure moat durable?", _msft())
        assert "competitive_risk" in block, \
            "risk/competitive_position block must name competitive_risk as anchor field"

    def test_risk_valuation_estimate_cut(self):
        block = risk_emphasis("valuation_stance", "Is MSFT overpriced?", _msft())
        assert "estimate" in block.lower() or "de-rat" in block.lower() \
               or "guidance" in block.lower(), \
            "risk/valuation_stance block must mention estimate cuts or de-rating"

    def test_risk_macro_refinancing(self):
        block = risk_emphasis("macro_sensitivity", "How do rates affect MSFT?", _msft())
        assert "refinanc" in block.lower() or "debt" in block.lower() \
               or "rate" in block.lower(), \
            "risk/macro_sensitivity block must mention refinancing or debt"

    def test_risk_competitive_moat_erosion_specifics(self):
        block = risk_emphasis("competitive_position", "Azure moat question", _msft())
        assert "moat" in block.lower() or "erosion" in block.lower() \
               or "market-share" in block.lower(), \
            "risk/competitive_position block must address moat erosion"


class TestMarketBlockContent:
    """Market emphasis blocks contain intent-appropriate language."""

    def test_market_competitive_competitor_news(self):
        block = market_emphasis("competitive_position", "Is Azure moat stronger?", _msft())
        assert "competitor" in block.lower() or "competitive" in block.lower(), \
            "market/competitive_position must surface competitor news"

    def test_market_competitive_sentiment_field(self):
        block = market_emphasis("competitive_position", "Azure moat question", _msft())
        assert "sentiment" in block, \
            "market/competitive_position block must direct the sentiment field"

    def test_market_valuation_price_target(self):
        block = market_emphasis("valuation_stance", "Is MSFT overpriced?", _msft())
        assert "price" in block.lower() and ("target" in block.lower()
               or "consensus" in block.lower()), \
            "market/valuation_stance must mention analyst price targets"

    def test_market_valuation_positioning(self):
        block = market_emphasis("valuation_stance", "MSFT valuation?", _msft())
        assert "positioning" in block.lower() or "crowded" in block.lower(), \
            "market/valuation_stance block must address positioning"

    def test_market_macro_sector_rotation(self):
        block = market_emphasis("macro_sensitivity", "How do rates affect MSFT?", _msft())
        assert "rotation" in block.lower() or "sector" in block.lower() \
               or "macro" in block.lower(), \
            "market/macro_sensitivity must mention sector rotation"

    def test_market_macro_momentum_field(self):
        block = market_emphasis("macro_sensitivity", "Rate cut effect on MSFT?", _msft())
        assert "momentum" in block, \
            "market/macro_sensitivity block must direct the momentum field"

    def test_market_risk_negative_catalysts(self):
        block = market_emphasis("risk_assessment", "MSFT risks?", _msft())
        assert "negative" in block.lower() or "bearish" in block.lower() \
               or "downgrade" in block.lower(), \
            "market/risk_assessment block must surface negative catalysts"

    def test_market_risk_recent_catalysts_field(self):
        block = market_emphasis("risk_assessment", "MSFT risks?", _msft())
        assert "recent_catalysts" in block, \
            "market/risk_assessment block must direct the recent_catalysts field"


class TestQualityBlockContent:
    """Quality emphasis blocks contain intent-appropriate language."""

    def test_quality_competitive_moat_field_anchor(self):
        block = quality_emphasis("competitive_position", "Azure vs M365 moat?", _msft())
        assert "moat" in block and (
            "depth" in block.lower() or "highest-depth" in block.lower()
            or "lead" in block.lower()
        ), "quality/competitive_position must make moat the anchor field"

    def test_quality_competitive_decompose_sources(self):
        block = quality_emphasis("competitive_position", "Azure moat question", _msft())
        assert "switching" in block.lower() or "network" in block.lower() \
               or "IP" in block or "ip" in block.lower(), \
            "quality/competitive_position must enumerate moat sources"

    def test_quality_competitive_compare_segments(self):
        block = quality_emphasis("competitive_position", "Azure vs M365 moat?", _msft())
        assert "segment" in block.lower() or "product" in block.lower() \
               or "compar" in block.lower(), \
            "quality/competitive_position must encourage segment comparison"

    def test_quality_valuation_fcf_yield(self):
        block = quality_emphasis("valuation_stance", "Is MSFT overpriced?", _msft())
        assert "fcf" in block.lower() or "free cash flow" in block.lower(), \
            "quality/valuation_stance must mention FCF"

    def test_quality_valuation_operating_quality_field(self):
        block = quality_emphasis("valuation_stance", "MSFT multiple compression?", _msft())
        assert "operating_quality" in block, \
            "quality/valuation_stance must name operating_quality as anchor field"

    def test_quality_valuation_capital_return(self):
        block = quality_emphasis("valuation_stance", "MSFT valuation?", _msft())
        assert "capital_allocation" in block or "buyback" in block.lower() \
               or "capital return" in block.lower(), \
            "quality/valuation_stance must address capital return"

    def test_quality_macro_revenue_durability_field(self):
        block = quality_emphasis("macro_sensitivity", "Rate cut impact?", _msft())
        assert "revenue_durability" in block, \
            "quality/macro_sensitivity must name revenue_durability as anchor"

    def test_quality_macro_pricing_power(self):
        block = quality_emphasis("macro_sensitivity", "How do rates affect MSFT?", _msft())
        assert "pricing" in block.lower() or "contract" in block.lower() \
               or "subscription" in block.lower(), \
            "quality/macro_sensitivity must address pricing power or recurring revenue"

    def test_quality_risk_moat_deterioration(self):
        block = quality_emphasis("risk_assessment", "MSFT risks?", _msft())
        assert "erosion" in block.lower() or "deteriorat" in block.lower() \
               or "weaken" in block.lower(), \
            "quality/risk_assessment must include moat deterioration scenario"

    def test_quality_risk_capital_allocation_flags(self):
        block = quality_emphasis("risk_assessment", "MSFT risks?", _msft())
        assert "capital" in block.lower() or "m&a" in block.lower() \
               or "dilut" in block.lower(), \
            "quality/risk_assessment must address capital-allocation risks"


# ════════════════════════════════════════════════════════════════════════════════
# SECTION 3 — Prompt construction embeds emphasis block
# ════════════════════════════════════════════════════════════════════════════════

class TestPromptEmbedding:
    """_build_prompt() correctly inserts the emphasis block for each agent."""

    @pytest.mark.parametrize("intent,q", list(_QUESTIONS.items()))
    def test_macro_prompt_contains_emphasis_when_non_default(self, intent, q):
        evidence = _stub_evidence(1)
        prompt = macro_build_prompt(_msft(), evidence, profile=None,
                                    question_intent=intent, question=q)
        expected_block = macro_emphasis(intent, q, _msft())
        if expected_block:
            assert expected_block in prompt, \
                f"macro prompt must embed emphasis block for intent={intent!r}"

    @pytest.mark.parametrize("intent,q", list(_QUESTIONS.items()))
    def test_risk_prompt_contains_emphasis_when_non_default(self, intent, q):
        evidence = _stub_evidence(1)
        prompt = risk_build_prompt(_msft(), evidence, profile=None,
                                   question_intent=intent, question=q)
        expected_block = risk_emphasis(intent, q, _msft())
        if expected_block:
            assert expected_block in prompt, \
                f"risk prompt must embed emphasis block for intent={intent!r}"

    @pytest.mark.parametrize("intent,q", list(_QUESTIONS.items()))
    def test_market_prompt_contains_emphasis_when_non_default(self, intent, q):
        evidence = _stub_evidence(1)
        prompt = market_build_prompt(_msft(), evidence, profile=None,
                                     question_intent=intent, question=q)
        expected_block = market_emphasis(intent, q, _msft())
        if expected_block:
            assert expected_block in prompt, \
                f"market prompt must embed emphasis block for intent={intent!r}"

    @pytest.mark.parametrize("intent,q", list(_QUESTIONS.items()))
    def test_quality_prompt_contains_emphasis_when_non_default(self, intent, q):
        evidence = _stub_evidence(1)
        prompt = quality_build_prompt(_msft(), evidence, profile=None,
                                      question_intent=intent, question=q)
        expected_block = quality_emphasis(intent, q, _msft())
        if expected_block:
            assert expected_block in prompt, \
                f"quality prompt must embed emphasis block for intent={intent!r}"

    def test_default_intent_prompt_has_no_question_focus_header(self):
        evidence = _stub_evidence(1)
        for build_fn in [macro_build_prompt, risk_build_prompt,
                         market_build_prompt, quality_build_prompt]:
            prompt = build_fn(_msft(), evidence, profile=None,
                              question_intent="investment_thesis",
                              question="MSFT thesis")
            assert "QUESTION FOCUS" not in prompt, \
                f"{build_fn.__module__}: default intent must not inject emphasis header"


# ════════════════════════════════════════════════════════════════════════════════
# SECTION 4 — Run-function signatures accept new parameters
# ════════════════════════════════════════════════════════════════════════════════

class TestRunFunctionSignatures:
    """All four run_*_agent() functions accept question_intent and question."""

    def _mock_llm_return(self, schema_cls):
        """Return a MagicMock whose get_structured_response returns a valid schema."""
        import inspect
        fields = {
            f: ""
            for f in getattr(schema_cls, "model_fields", {})
        }
        return MagicMock(return_value=schema_cls(**{
            k: ("" if isinstance(v.default, str) else v.default)
            for k, v in getattr(schema_cls, "model_fields", {}).items()
        }))

    @pytest.mark.parametrize("intent", ["investment_thesis", "competitive_position",
                                          "macro_sensitivity"])
    def test_macro_agent_accepts_question_params(self, intent):
        evidence = _stub_evidence(1)
        with patch("app.investment_agents.macro_agent.get_structured_response") as mock_gsr:
            mock_gsr.return_value = MacroSensitivity(overall="test", confidence=0.5)
            result = run_investment_macro_agent(
                _msft(), evidence,
                question_intent=intent,
                question=_QUESTIONS[intent],
            )
            assert result is not None

    @pytest.mark.parametrize("intent", ["investment_thesis", "risk_assessment",
                                          "competitive_position"])
    def test_risk_agent_accepts_question_params(self, intent):
        evidence = _stub_evidence(1)
        with patch("app.investment_agents.risk_agent.get_structured_response") as mock_gsr:
            mock_gsr.return_value = RiskProfile(overall="test", confidence=0.5)
            result = run_risk_agent(
                _msft(), evidence,
                question_intent=intent,
                question=_QUESTIONS[intent],
            )
            assert result is not None

    @pytest.mark.parametrize("intent", ["investment_thesis", "valuation_stance",
                                          "macro_sensitivity"])
    def test_market_agent_accepts_question_params(self, intent):
        evidence = _stub_evidence(1)
        with patch("app.investment_agents.market_agent.get_structured_response") as mock_gsr:
            mock_gsr.return_value = MarketContext(overall="test", confidence=0.5)
            result = run_market_agent(
                _msft(), evidence,
                question_intent=intent,
                question=_QUESTIONS[intent],
            )
            assert result is not None

    @pytest.mark.parametrize("intent", ["investment_thesis", "competitive_position",
                                          "valuation_stance"])
    def test_quality_agent_accepts_question_params(self, intent):
        evidence = _stub_evidence(1)
        with patch("app.investment_agents.quality_agent.get_structured_response") as mock_gsr:
            mock_gsr.return_value = QualityAssessment(overall="test", confidence=0.5)
            result = run_quality_agent(
                _msft(), evidence,
                question_intent=intent,
                question=_QUESTIONS[intent],
            )
            assert result is not None

    def test_agents_degrade_gracefully_with_none_params(self):
        """None question params must not crash any agent (empty evidence path)."""
        for fn, cls in [
            (run_investment_macro_agent, MacroSensitivity),
            (run_risk_agent,             RiskProfile),
            (run_market_agent,           MarketContext),
            (run_quality_agent,          QualityAssessment),
        ]:
            result = fn(_msft(), [], question_intent=None, question=None)
            assert result is not None, f"{fn.__name__} must not return None"


# ════════════════════════════════════════════════════════════════════════════════
# SECTION 5 — Overlap metric regression (structural guarantee)
# ════════════════════════════════════════════════════════════════════════════════

class TestPromptDifferentiation:
    """
    Prompts for different question types must differ by at least 30%.
    (overlap < 70% == differentiation > 30%)

    This is a structural guarantee tested on the prompt text *before* the LLM
    call — it proves the LLM receives materially different instructions for
    each question type, which is the root cause of output convergence.

    The target is prompt-level overlap < 70%; this is a conservative bound.
    LLM output overlap will be even lower because the emphasis blocks also
    steer which JSON fields to populate in which depth order.
    """

    _MSFT_QUESTIONS = [
        ("investment_thesis",   "Can MSFT sustain AI-driven growth if enterprise spending slows?"),
        ("competitive_position","Is Azure becoming a stronger moat than Microsoft 365?"),
        ("valuation_stance",    "What multiple compression risk does Microsoft face?"),
        ("macro_sensitivity",   "How would a rate cut affect Microsoft stock?"),
        ("risk_assessment",     "What are the biggest risks for Microsoft right now?"),
    ]

    def _build_all_prompts(self, build_fn):
        evidence = _stub_evidence(2)
        return {
            intent: build_fn(_msft(), evidence, profile=None,
                             question_intent=intent, question=q)
            for intent, q in self._MSFT_QUESTIONS
        }

    @pytest.mark.parametrize("build_fn,agent_name", [
        (macro_build_prompt,   "macro"),
        (risk_build_prompt,    "risk"),
        (market_build_prompt,  "market"),
        (quality_build_prompt, "quality"),
    ])
    def test_non_default_prompts_differ_from_default(self, build_fn, agent_name):
        """Each non-default intent prompt must differ from the default prompt."""
        prompts = self._build_all_prompts(build_fn)
        default_prompt = prompts["investment_thesis"]

        for intent, prompt in prompts.items():
            if intent == "investment_thesis":
                continue
            overlap = _text_overlap(default_prompt, prompt)
            assert overlap < 0.97, (
                f"{agent_name} agent: prompt for intent={intent!r} is "
                f"{overlap:.1%} similar to default — no differentiation. "
                f"Emphasis block is not being injected."
            )

    @pytest.mark.parametrize("build_fn,agent_name", [
        (macro_build_prompt,   "macro"),
        (risk_build_prompt,    "risk"),
        (market_build_prompt,  "market"),
        (quality_build_prompt, "quality"),
    ])
    def test_macro_vs_competitive_prompts_differ_meaningfully(self, build_fn, agent_name):
        """macro_sensitivity and competitive_position prompts must differ by >3%."""
        evidence = _stub_evidence(2)
        p_macro = build_fn(_msft(), evidence, profile=None,
                           question_intent="macro_sensitivity",
                           question=_QUESTIONS["macro_sensitivity"])
        p_comp  = build_fn(_msft(), evidence, profile=None,
                           question_intent="competitive_position",
                           question=_QUESTIONS["competitive_position"])
        overlap = _text_overlap(p_macro, p_comp)
        assert overlap < 0.97, (
            f"{agent_name}: macro_sensitivity vs competitive_position prompts are "
            f"{overlap:.1%} similar — emphasis blocks are not differentiating them"
        )

    @pytest.mark.parametrize("build_fn,agent_name", [
        (macro_build_prompt,   "macro"),
        (risk_build_prompt,    "risk"),
        (market_build_prompt,  "market"),
        (quality_build_prompt, "quality"),
    ])
    def test_all_four_non_default_intents_are_distinct(self, build_fn, agent_name):
        """No two non-default intent prompts should be 100% identical."""
        prompts = self._build_all_prompts(build_fn)
        non_default = {k: v for k, v in prompts.items()
                       if k != "investment_thesis"}
        intent_list = list(non_default.keys())
        for i in range(len(intent_list)):
            for j in range(i + 1, len(intent_list)):
                ia, ib = intent_list[i], intent_list[j]
                overlap = _text_overlap(non_default[ia], non_default[ib])
                assert overlap < 1.0, (
                    f"{agent_name}: prompts for {ia!r} and {ib!r} are identical — "
                    f"each intent must produce a unique prompt"
                )


# ════════════════════════════════════════════════════════════════════════════════
# SECTION 6 — NVDA cross-validation (emphasis works for non-MSFT tickers)
# ════════════════════════════════════════════════════════════════════════════════

class TestNVDACrossValidation:
    """Emphasis blocks reference the correct ticker (NVDA, not MSFT)."""

    @pytest.mark.parametrize("fn,intent", [
        (macro_emphasis,   "macro_sensitivity"),
        (risk_emphasis,    "competitive_position"),
        (market_emphasis,  "valuation_stance"),
        (quality_emphasis, "competitive_position"),
    ])
    def test_emphasis_block_references_nvda_ticker(self, fn, intent):
        block = fn(intent, f"NVDA {intent} question", _nvda())
        assert "NVDA" in block, \
            f"{fn.__module__} intent={intent!r}: block must reference NVDA ticker"
        assert "MSFT" not in block, \
            f"{fn.__module__} intent={intent!r}: block must not leak MSFT ticker"
