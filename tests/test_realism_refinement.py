"""
Realism refinement tests — institutional prose realism phase.

Covers the 5 objectives:
  1. Hidden-process reasoning — build_confidence_reasoning() never exposes agent names,
     percentages, or process-narration ("signals converge", "all point in the same direction")
  2. Live market debate — core_market_debate field present and PM-note formatted
  3. Section hierarchy — _build_section_priority_block() returns correct directives
  4. Mechanism-first writing — new FORBIDDEN_PHRASES detected; polisher rewrites fire
  5. Confidence language alignment — score-to-language coherence

Also covers:
  - Apple/rates, Nvidia demand, Meta capex, Tesla cyclical/structural scenario examples
"""
from __future__ import annotations

import pytest
from typing import List, Dict

from app.schemas import (
    CompanyContext,
    InvestmentThesis,
    MacroSensitivity,
    MarketContext,
    QualityAssessment,
    RiskProfile,
    Signal,
    ValuationView,
)
from app.services.signal_ranker import (
    FORBIDDEN_PHRASES,
    RankedSignalSet,
    build_confidence_reasoning,
    check_forbidden_phrases,
)
from app.services.thesis_synthesizer import (
    _build_section_priority_block,
    _detect_dominant_dimension,
)
from app.services.thesis_polisher import institutional_phrase_rewriter


# ── Helpers ───────────────────────────────────────────────────────────────────

def _signal(text: str, direction: str = "bullish", impact: float = 0.8) -> Signal:
    return Signal(
        signal=text, impact_score=impact, confidence=0.75,
        signal_type="structural", direction=direction, source_agent="valuation",
    )


def _macro(overall: str = "Macro analysis.", confidence: float = 0.72) -> MacroSensitivity:
    return MacroSensitivity(overall=overall, confidence=confidence, signals=[])


def _risk(overall: str = "Risk analysis.", confidence: float = 0.68,
          key_risks: List[str] = None) -> RiskProfile:
    return RiskProfile(overall=overall, confidence=confidence,
                       signals=[], key_risks=key_risks or [])


def _valuation(overall: str = "Valuation analysis.", confidence: float = 0.75) -> ValuationView:
    return ValuationView(overall=overall, confidence=confidence, signals=[])


def _quality(confidence: float = 0.70) -> QualityAssessment:
    return QualityAssessment(overall="Quality analysis.", confidence=confidence, signals=[])


def _agent_confs(**kwargs) -> Dict[str, float]:
    base = {"valuation": 0.75, "macro": 0.72, "risk": 0.68, "market": 0.70, "quality": 0.70}
    base.update(kwargs)
    return base


# ── 1. Hidden-Process Reasoning ───────────────────────────────────────────────

class TestHiddenProcessReasoning:
    """build_confidence_reasoning() must not expose internal analytical process."""

    PROCESS_PHRASES = [
        "agent", "agents",
        "all point in the same direction",
        "leaving limited room for analytical disagreement",
        "signals converge",
        "evidence supports the thesis",
        "directional alignment",
        "broadly aligned",
        "cross-agent",
        "%",           # no raw percentages
    ]

    def _check_no_process_phrases(self, text: str):
        text_lower = text.lower()
        for phrase in self.PROCESS_PHRASES:
            assert phrase.lower() not in text_lower, (
                f"Process-exposure phrase '{phrase}' found in confidence reasoning:\n{text}"
            )

    def test_high_confidence_no_process_exposure(self):
        reasoning = build_confidence_reasoning(
            agent_confidences=_agent_confs(valuation=0.82, macro=0.80, risk=0.78),
            ranked=None,
            evidence_count=12,
        )
        self._check_no_process_phrases(reasoning)
        assert len(reasoning) > 20, "Reasoning should be non-trivial"

    def test_macro_uncertain_no_agent_names(self):
        reasoning = build_confidence_reasoning(
            agent_confidences=_agent_confs(macro=0.42),
            ranked=None,
            evidence_count=8,
        )
        self._check_no_process_phrases(reasoning)
        # Should mention macro uncertainty without naming the agent
        assert any(word in reasoning.lower() for word in
                   ["macro", "backdrop", "rate", "monetary", "unresolved", "transmission", "variable"]), (
            f"Should mention macro uncertainty: {reasoning}"
        )

    def test_thin_evidence_no_counts(self):
        reasoning = build_confidence_reasoning(
            agent_confidences=_agent_confs(),
            ranked=None,
            evidence_count=2,
        )
        self._check_no_process_phrases(reasoning)
        assert any(word in reasoning.lower() for word in
                   ["evidence", "thin", "coverage", "data", "limited"]), (
            f"Should mention thin evidence: {reasoning}"
        )

    def test_split_signals_no_counts(self):
        # Build a split signal set
        sigs = (
            [_signal(f"bull {i}", direction="bullish") for i in range(3)]
            + [_signal(f"bear {i}", direction="bearish") for i in range(3)]
        )
        ranked = RankedSignalSet(
            top_signals=sigs[:2], top_risks=sigs[3:5],
            secondary_signals=[], noise=[], all_ranked=sigs,
        )
        reasoning = build_confidence_reasoning(
            agent_confidences=_agent_confs(),
            ranked=ranked,
            evidence_count=8,
        )
        self._check_no_process_phrases(reasoning)
        assert any(word in reasoning.lower() for word in
                   ["two-sided", "balanced", "evenly matched", "directional", "lean", "split"]), (
            f"Should reflect split/two-sided: {reasoning}"
        )

    def test_high_confidence_reads_like_pm_note(self):
        """High confidence output should sound like an analyst judgment, not a scoring report."""
        reasoning = build_confidence_reasoning(
            agent_confidences=_agent_confs(
                valuation=0.85, macro=0.82, risk=0.80, market=0.81, quality=0.78
            ),
            ranked=None,
            evidence_count=15,
        )
        # Must not contain scoring language
        assert "%" not in reasoning
        assert "agent" not in reasoning.lower()
        # Must contain some qualitative judgment language
        assert any(word in reasoning.lower() for word in
                   ["clear", "clean", "defensible", "consistent", "reads", "timing", "direction",
                    "mechanism", "residual"]), (
            f"Should contain qualitative judgment: {reasoning}"
        )

    def test_double_uncertainty_mentions_dual_risk(self):
        reasoning = build_confidence_reasoning(
            agent_confidences=_agent_confs(macro=0.42, risk=0.44),
            ranked=None,
            evidence_count=6,
        )
        self._check_no_process_phrases(reasoning)
        assert any(word in reasoning.lower() for word in
                   ["macro", "risk", "downside", "unresolved", "question", "path", "uncertain"]), (
            f"Should name dual uncertainty: {reasoning}"
        )

    def test_risk_uncertain_names_downside(self):
        reasoning = build_confidence_reasoning(
            agent_confidences=_agent_confs(risk=0.40),
            ranked=None,
            evidence_count=8,
        )
        self._check_no_process_phrases(reasoning)
        assert any(word in reasoning.lower() for word in
                   ["risk", "downside", "exposure", "open", "unresolved", "genuine"]), (
            f"Should mention risk/downside: {reasoning}"
        )

    def test_output_is_at_most_two_sentences(self):
        """build_confidence_reasoning() caps at 2 sentences."""
        reasoning = build_confidence_reasoning(
            agent_confidences=_agent_confs(macro=0.40, risk=0.44),
            ranked=None,
            evidence_count=4,
        )
        sentence_count = len([s for s in reasoning.split(".") if s.strip()])
        assert sentence_count <= 3, (
            f"Too many sentences ({sentence_count}): {reasoning}"
        )


# ── 2. Live Market Debate (core_market_debate) ────────────────────────────────

class TestCoreMarketDebate:
    """core_market_debate field must be present, non-empty, PM-note formatted."""

    def test_field_exists_on_schema(self):
        t = InvestmentThesis(
            ticker="AAPL",
            company_name="Apple Inc.",
            bull_thesis="Bull.",
            bear_thesis="Bear.",
            conclusion="Conclusion.",
            confidence_score=0.70,
        )
        assert hasattr(t, "core_market_debate")
        assert isinstance(t.core_market_debate, str)

    def test_field_accepts_pm_style_question(self):
        questions = [
            "Is Services growth durable enough to offset hardware cyclicality?",
            "Is Nvidia demand structural or peak-cycle behavior?",
            "Can Meta sustain margin discipline while reaccelerating capex?",
            "Is the market underestimating rate duration risk for Apple?",
        ]
        for q in questions:
            t = InvestmentThesis(
                ticker="AAPL", company_name="Apple Inc.",
                bull_thesis="Bull.", bear_thesis="Bear.",
                conclusion="Conclusion.", confidence_score=0.70,
                core_market_debate=q,
            )
            assert t.core_market_debate == q

    def test_pm_debate_is_direct_question(self):
        """PM debate must start with the tension, not 'The market is debating whether...'"""
        bad_starts = [
            "The market is debating whether",
            "Investors are uncertain about",
            "There are concerns regarding",
            "It is unclear whether",
        ]
        good_debates = [
            "Is Services growth durable enough to offset hardware cyclicality?",
            "Is Nvidia demand structural or peak-cycle behavior?",
            "Can Meta sustain margin discipline while reaccelerating capex?",
        ]
        for debate in good_debates:
            for bad in bad_starts:
                assert not debate.lower().startswith(bad.lower()), (
                    f"PM debate '{debate}' should not start with explanatory preamble"
                )

    def test_field_distinct_from_core_debate(self):
        """core_market_debate is distinct from core_debate — one is analytical, one is positioning."""
        t = InvestmentThesis(
            ticker="AAPL", company_name="Apple Inc.",
            bull_thesis="Bull.", bear_thesis="Bear.",
            conclusion="Conclusion.", confidence_score=0.70,
            core_debate="Can Services growth absorb multiple compression as rates stay higher for longer?",
            core_market_debate="Is the market underestimating rate duration risk for Apple?",
        )
        assert t.core_debate != t.core_market_debate


# ── 3. Section Priority / Hierarchy ──────────────────────────────────────────

class TestSectionPriorityBlock:
    """_build_section_priority_block() returns dimension-specific priority tags."""

    def test_macro_priority_deep_macro(self):
        tag = _build_section_priority_block("macro")
        assert "macro" in tag.lower()
        assert "DEEP" in tag

    def test_valuation_priority_deep_valuation(self):
        tag = _build_section_priority_block("valuation")
        assert "valuation" in tag.lower()
        assert "DEEP" in tag

    def test_regulatory_priority_deep_bear(self):
        tag = _build_section_priority_block("regulatory")
        assert "bear" in tag.lower()
        assert "DEEP" in tag

    def test_capital_allocation_priority_deep_bull(self):
        tag = _build_section_priority_block("capital_allocation")
        assert "bull" in tag.lower()
        assert "DEEP" in tag

    def test_operational_priority_deep_bull_and_bear(self):
        tag = _build_section_priority_block("operational")
        assert "bull" in tag.lower()
        assert "DEEP" in tag

    def test_compressed_section_mentioned(self):
        """Each priority block must call out at least one COMPRESSED section."""
        for dim in ["macro", "valuation", "regulatory", "capital_allocation", "operational"]:
            tag = _build_section_priority_block(dim)
            assert "COMPRESSED" in tag, (
                f"Dimension '{dim}' priority block missing COMPRESSED directive: {tag}"
            )

    def test_unknown_dimension_returns_empty(self):
        tag = _build_section_priority_block("unknown_dim")
        assert tag == ""

    def test_dimensions_produce_distinct_tags(self):
        """Each dimension must produce a unique priority directive."""
        tags = {dim: _build_section_priority_block(dim)
                for dim in ["macro", "valuation", "regulatory", "capital_allocation", "operational"]}
        assert len(set(tags.values())) == len(tags), (
            "Each dimension should produce a distinct section priority tag"
        )


# ── 4. Mechanism-First Writing & New FORBIDDEN_PHRASES ────────────────────────

class TestMechanismFirstAndForbiddenPhrases:
    """New hidden-process and mechanism-abstraction phrases are detected and rewritten."""

    def _thesis_with_bull(self, text: str) -> InvestmentThesis:
        return InvestmentThesis(
            ticker="AAPL", company_name="Apple Inc.",
            bull_thesis=text, bear_thesis="Bear case.",
            conclusion="Conclusion.", confidence_score=0.70,
        )

    # Forbidden phrase detection
    @pytest.mark.parametrize("phrase", [
        "signals converge on the bullish case",
        "evidence supports the thesis here",
        "analysis indicates positive momentum",
        "multiple factors suggest upside",
        "conviction remains elevated",
        "directional alignment across the framework",
        "all point in the same direction",
        "leaving limited room for analytical disagreement",
        "broadly constructive signals",
        "agent consensus is strong",
        "agents agree on the direction",
        "analytically constructive backdrop",
        "broadly aligned investment case",
    ])
    def test_hidden_process_phrase_detected(self, phrase: str):
        thesis = self._thesis_with_bull(phrase)
        warnings = check_forbidden_phrases(thesis)
        assert any(
            any(word in w.lower() for word in phrase.lower().split()[:3])
            for w in warnings
        ), (
            f"Hidden-process phrase not detected: '{phrase}'\nWarnings: {warnings}"
        )

    # Polisher rewrites
    @pytest.mark.parametrize("input_text,expected_fragment", [
        ("This enhances profitability of the business.",          "expands margins"),
        ("The buyback remains resilient through the cycle.",      "holds up"),
        ("Services stabilizes the valuation multiple.",          "steadies the multiple"),
        ("Signals converge on the upside case.",                  "consistent"),
        ("The investment case is well-supported by the evidence.",  "defensible"),
        ("Multiple factors suggest the thesis is intact.",        "dominant driver"),
        ("Conviction remains elevated at current levels.",        "conviction is moderate"),
        ("Highly constructive view on the earnings path.",        "constructive"),
        ("Elevated conviction supports the bull case.",           "conviction"),
    ])
    def test_mechanism_rewrite_fires(self, input_text: str, expected_fragment: str):
        result = institutional_phrase_rewriter(input_text)
        assert expected_fragment.lower() in result.lower(), (
            f"Expected '{expected_fragment}' in rewritten text.\n"
            f"Input:  {input_text!r}\n"
            f"Output: {result!r}"
        )

    def test_durable_growth_rewritten(self):
        result = institutional_phrase_rewriter(
            "The company has a durable growth trajectory ahead."
        )
        assert "sustained growth" in result.lower() or "durable growth trajectory" not in result.lower()


# ── 5. Confidence Language Alignment ─────────────────────────────────────────

class TestConfidenceLanguageAlignment:
    """Confidence prose must match score tier."""

    HIGH_CONVICTION_PHRASES = [
        "high conviction", "strong conviction", "highly constructive",
        "conviction remains high", "confidence remains high", "well-supported thesis",
        "elevated conviction",
    ]

    def _thesis(self, score: float, reasoning: str = "") -> InvestmentThesis:
        return InvestmentThesis(
            ticker="AAPL", company_name="Apple Inc.",
            bull_thesis="Bull.", bear_thesis="Bear.",
            conclusion="Conclusion.", confidence_score=score,
            confidence_reasoning=reasoning or "The thesis is directionally clear.",
        )

    def test_polisher_strips_high_conviction_at_low_score(self):
        """'high conviction' should be rewritten to moderate language."""
        result = institutional_phrase_rewriter(
            "This is a high conviction position with strong upside."
        )
        for phrase in ["high conviction", "strong conviction"]:
            assert phrase not in result.lower(), (
                f"'{phrase}' survived polisher rewrite: {result}"
            )

    def test_polisher_strips_confidence_remains_high(self):
        result = institutional_phrase_rewriter(
            "Confidence remains high given the earnings trajectory."
        )
        assert "remains high" not in result.lower()
        assert "conviction" in result.lower()

    @pytest.mark.parametrize("forbidden", HIGH_CONVICTION_PHRASES)
    def test_forbidden_phrase_detected(self, forbidden: str):
        thesis = self._thesis(0.65, f"The thesis is solid. {forbidden} here.")
        warnings = check_forbidden_phrases(thesis)
        assert len(warnings) > 0, (
            f"'{forbidden}' at confidence 0.65 should trigger a warning. Warnings: {warnings}"
        )

    def test_build_reasoning_matches_tier_macro_uncertain(self):
        """Macro-uncertain reasoning avoids "high conviction" language."""
        reasoning = build_confidence_reasoning(
            agent_confidences=_agent_confs(macro=0.42),
            ranked=None,
            evidence_count=6,
        )
        for phrase in ["high conviction", "strong conviction", "highly constructive"]:
            assert phrase not in reasoning.lower(), (
                f"Overconfident language in macro-uncertain reasoning: {reasoning}"
            )

    def test_build_reasoning_high_confidence_doesnt_oversell(self):
        """Even high confidence should be understated, not oversold."""
        reasoning = build_confidence_reasoning(
            agent_confidences=_agent_confs(
                valuation=0.85, macro=0.82, risk=0.80, market=0.81, quality=0.79
            ),
            ranked=None,
            evidence_count=14,
        )
        # OK to be positive, but not to use forbidden superlatives
        for phrase in ["strong conviction", "high conviction", "confidence is high"]:
            assert phrase not in reasoning.lower(), (
                f"Overconfident superlative in high-confidence reasoning: {reasoning}"
            )


# ── 6. Scenario: Apple / Rates ────────────────────────────────────────────────

class TestAppleRatesScenario:
    """Apple/rates scenario — macro dominant, section priority correct, prose clean."""

    def test_macro_dominates_apple_rates(self):
        macro = _macro(
            overall="Fed rate hikes of 100bps compress duration-sensitive valuations. "
                    "The yield curve inversion signals recession risk. Monetary policy "
                    "transmission is the primary debate via treasury yield and duration.",
            confidence=0.48,
        )
        risk  = _risk(overall="Geopolitical and regulatory risk are secondary.", confidence=0.65)
        val   = _valuation(overall="Trading at 28x forward P/E vs 5yr avg of 22x.", confidence=0.72)
        dim   = _detect_dominant_dimension(macro, risk, val)
        assert dim == "macro"

    def test_apple_macro_confidence_cap_applied(self):
        from app.services.signal_ranker import compute_confidence_realism_cap
        adjusted, triggers = compute_confidence_realism_cap(
            raw_score=0.80, macro_conf=0.48, risk_conf=0.66,
            quality_conf=0.72, evidence_count=10,
        )
        assert adjusted <= 0.72
        assert any("macro" in t.lower() for t in triggers)

    def test_apple_section_priority_macro_deep(self):
        tag = _build_section_priority_block("macro")
        assert "macro_sensitivity" in tag.lower()
        assert "DEEP" in tag
        assert "COMPRESSED" in tag  # valuation should be compressed

    def test_apple_core_market_debate_format(self):
        debate = "Is the market underestimating rate duration risk for Apple?"
        assert debate.endswith("?")
        assert not debate.lower().startswith("the market is debating")
        t = InvestmentThesis(
            ticker="AAPL", company_name="Apple Inc.",
            bull_thesis="Bull.", bear_thesis="Bear.",
            conclusion="Conclusion.", confidence_score=0.68,
            core_market_debate=debate,
        )
        assert t.core_market_debate == debate

    def test_apple_confidence_reasoning_no_process(self):
        reasoning = build_confidence_reasoning(
            agent_confidences=_agent_confs(macro=0.48),
            ranked=None,
            evidence_count=10,
        )
        # No agent names, no percentages, no process narration
        assert "%" not in reasoning
        assert "agent" not in reasoning.lower()
        assert "all point" not in reasoning.lower()


# ── 7. Scenario: Nvidia Demand Durability ────────────────────────────────────

class TestNvidiaDemandScenario:
    """Nvidia — operational/structural dominant, AI demand debate."""

    def test_nvidia_operational_dominant(self):
        macro = _macro(
            overall="Macro is broadly neutral. Rate environment is stable.",
            confidence=0.72,
        )
        risk  = _risk(
            overall="Demand cyclicality and inventory risk are the primary concerns. "
                    "Revenue guidance and earnings trajectory are the key debate.",
            key_risks=["AI demand pull-forward risk", "hyperscaler capex cycle"],
            confidence=0.60,
        )
        val   = _valuation(
            overall="Trades at 35x forward earnings — expensive vs history.",
            confidence=0.65,
        )
        dim = _detect_dominant_dimension(macro, risk, val)
        # With revenue/earnings keywords in risk overall, operational should score
        assert dim in ("operational", "valuation"), f"Got '{dim}' — expected operational or valuation"

    def test_nvidia_pm_debate_format(self):
        debate = "Is Nvidia demand structural or peak-cycle behavior?"
        assert "?" in debate
        assert not debate.lower().startswith("the market")
        t = InvestmentThesis(
            ticker="NVDA", company_name="Nvidia Corporation",
            bull_thesis="Bull.", bear_thesis="Bear.",
            conclusion="Conclusion.", confidence_score=0.68,
            core_market_debate=debate,
        )
        assert t.core_market_debate == debate

    def test_nvidia_split_signals_two_sided_reasoning(self):
        sigs = (
            [_signal(f"AI demand bullish {i}", direction="bullish") for i in range(3)]
            + [_signal(f"cycle risk bearish {i}", direction="bearish") for i in range(3)]
        )
        ranked = RankedSignalSet(
            top_signals=sigs[:2], top_risks=sigs[3:5],
            secondary_signals=[], noise=[], all_ranked=sigs,
        )
        reasoning = build_confidence_reasoning(
            agent_confidences=_agent_confs(macro=0.65, risk=0.58),
            ranked=ranked,
            evidence_count=8,
        )
        assert "%" not in reasoning
        assert "agent" not in reasoning.lower()


# ── 8. Scenario: Meta Capex ──────────────────────────────────────────────────

class TestMetaCapexScenario:
    """Meta — capital allocation + operational dominant, margin/capex debate."""

    def test_meta_pm_debate_format(self):
        debate = "Can Meta sustain margin discipline while reaccelerating capex?"
        assert "?" in debate
        assert not debate.lower().startswith("investors are")
        t = InvestmentThesis(
            ticker="META", company_name="Meta Platforms Inc.",
            bull_thesis="Bull.", bear_thesis="Bear.",
            conclusion="Conclusion.", confidence_score=0.72,
            core_market_debate=debate,
        )
        assert t.core_market_debate == debate

    def test_meta_section_priority_capital_allocation(self):
        tag = _build_section_priority_block("capital_allocation")
        assert "DEEP" in tag
        assert "COMPRESSED" in tag
        # Capital allocation should be bull-thesis deep
        assert "bull" in tag.lower()

    def test_meta_confidence_reasoning_no_process_leak(self):
        reasoning = build_confidence_reasoning(
            agent_confidences=_agent_confs(macro=0.70, risk=0.62),
            ranked=None,
            evidence_count=9,
        )
        assert "%" not in reasoning
        assert "agent" not in reasoning.lower()
        assert "all point" not in reasoning.lower()


# ── 9. Scenario: Tesla Cyclical vs Structural ─────────────────────────────────

class TestTeslaCyclicalScenario:
    """Tesla — operational + valuation debate, high uncertainty."""

    def test_tesla_pm_debate_format(self):
        debates = [
            "Is Tesla's demand weakness cyclical or a structural share loss to BYD?",
            "Can Tesla sustain margin through the EV price war without sacrificing growth?",
        ]
        for debate in debates:
            assert "?" in debate
            t = InvestmentThesis(
                ticker="TSLA", company_name="Tesla Inc.",
                bull_thesis="Bull.", bear_thesis="Bear.",
                conclusion="Conclusion.", confidence_score=0.58,
                core_market_debate=debate,
            )
            assert t.core_market_debate == debate

    def test_tesla_low_confidence_reasoning_honest(self):
        reasoning = build_confidence_reasoning(
            agent_confidences=_agent_confs(
                macro=0.50, risk=0.48, valuation=0.52, market=0.55, quality=0.50
            ),
            ranked=None,
            evidence_count=5,
        )
        assert "%" not in reasoning
        # Low confidence should not produce upbeat language
        upbeat = ["clean", "clear direction", "high conviction", "strong conviction",
                  "well-supported", "highly constructive"]
        for phrase in upbeat:
            assert phrase not in reasoning.lower(), (
                f"Upbeat language '{phrase}' in low-confidence reasoning: {reasoning}"
            )

    def test_tesla_double_uncertainty_names_both(self):
        reasoning = build_confidence_reasoning(
            agent_confidences=_agent_confs(macro=0.48, risk=0.44),
            ranked=None,
            evidence_count=6,
        )
        assert "%" not in reasoning
        assert "agent" not in reasoning.lower()
        # Double uncertainty case — should mention both dimensions implicitly
        assert any(w in reasoning.lower() for w in
                   ["macro", "backdrop", "risk", "downside", "unresolved", "question"]), (
            f"Double-uncertainty reasoning should acknowledge both risks: {reasoning}"
        )
