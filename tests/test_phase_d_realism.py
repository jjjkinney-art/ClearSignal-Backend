"""
Phase D — Elite PM Cognition Realism Tests

Seven objectives:
  1. ORCHESTRATION LEAKAGE REMOVAL  — new forbidden phrases + polisher rewrites
  2. COMPLETENESS BIAS REDUCTION    — implication compression patterns
  3. PM CADENCE REALISM             — CADENCE_VARIATION in synthesis prompt
  4. PRICED_IN_REASONING            — "already priced in" cognition
  5. TEMPORAL REALISM               — temporal anchoring language
  6. UNDERSTATED CONFIDENCE         — new bans + rewrites; PM-grade understatement
  7. SECTION ASYMMETRY SHARPENED    — DEEP vs COMPRESSED contrast; 1-sentence HARD CAP

All tests are deterministic — no LLM calls.
"""

from __future__ import annotations

import pytest
from typing import Dict, List, Optional

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
from app.services.thesis_polisher import (
    institutional_phrase_rewriter,
    polish_thesis,
)
from app.services.thesis_synthesizer import (
    _DEPTH_DIRECTIVES,
    _build_section_priority_block,
    _build_synthesis_prompt,
    _detect_dominant_dimension,
)


# ── Shared test fixtures ──────────────────────────────────────────────────────

def _company(ticker: str = "AAPL", sector: str = "Technology") -> CompanyContext:
    return CompanyContext(
        ticker=ticker,
        company_name=f"{ticker} Inc.",
        sector=sector,
        industry="Consumer Electronics",
    )


def _signal(text: str, direction: str = "bullish", signal_type: str = "macro") -> Signal:
    return Signal(
        signal=text,
        impact_score=0.80,
        confidence=0.75,
        signal_type=signal_type,
        direction=direction,
        source_agent="test",
    )


def _valuation(overall: str = "Valuation analysis.", confidence: float = 0.75) -> ValuationView:
    return ValuationView(overall=overall, confidence=confidence, signals=[])


def _macro(overall: str = "Macro analysis.", confidence: float = 0.60) -> MacroSensitivity:
    return MacroSensitivity(overall=overall, confidence=confidence, signals=[])


def _risk(overall: str = "Risk analysis.", confidence: float = 0.68) -> RiskProfile:
    return RiskProfile(overall=overall, confidence=confidence, signals=[])


def _market(overall: str = "Market context.", confidence: float = 0.72) -> MarketContext:
    return MarketContext(overall=overall, confidence=confidence, signals=[])


def _quality(overall: str = "Quality assessment.", confidence: float = 0.70) -> QualityAssessment:
    return QualityAssessment(overall=overall, confidence=confidence, signals=[])


def _thesis(**kwargs) -> InvestmentThesis:
    defaults = dict(
        ticker="AAPL",
        company_name="Apple Inc.",
        bull_thesis="Bull case text.",
        bear_thesis="Bear case text.",
        conclusion="Conclusion text.",
        confidence_score=0.70,
        direct_answer="",
    )
    defaults.update(kwargs)
    return InvestmentThesis(**defaults)


def _synthesis_prompt(ticker: str = "AAPL", macro_conf: float = 0.60) -> str:
    """Build a synthesis prompt for inspection tests."""
    company = _company(ticker)
    val = _valuation()
    mac = _macro(confidence=macro_conf)
    risk = _risk()
    mkt = _market()
    qual = _quality()
    return _build_synthesis_prompt(company, val, mac, risk, mkt, qual, evidence=[])


# ══════════════════════════════════════════════════════════════════════════════
# 1. ORCHESTRATION LEAKAGE REMOVAL
# ══════════════════════════════════════════════════════════════════════════════

class TestOrchestrationLeakageForbiddenPhrases:
    """Phase D: New orchestration leakage patterns appear in FORBIDDEN_PHRASES."""

    def test_signals_are_split_forbidden(self):
        assert "signals are split" in FORBIDDEN_PHRASES

    def test_signals_diverge_forbidden(self):
        assert "signals diverge" in FORBIDDEN_PHRASES

    def test_directional_disagreement_forbidden(self):
        assert "directional disagreement" in FORBIDDEN_PHRASES

    def test_analytical_disagreement_forbidden(self):
        assert "analytical disagreement" in FORBIDDEN_PHRASES

    def test_confidence_reduced_because_forbidden(self):
        assert "confidence reduced because" in FORBIDDEN_PHRASES

    def test_constructive_vs_cautious_forbidden(self):
        assert "constructive vs cautious" in FORBIDDEN_PHRASES

    def test_two_forces_affect_forbidden(self):
        assert "two forces affect" in FORBIDDEN_PHRASES

    def test_depending_on_which_scenario_forbidden(self):
        assert "depending on which scenario" in FORBIDDEN_PHRASES

    def test_in_opposite_directions_forbidden(self):
        assert "in opposite directions" in FORBIDDEN_PHRASES


class TestOrchestrationLeakagePolisherRewrites:
    """Phase D: Polisher rewrites orchestration leakage to PM-memo language."""

    @pytest.mark.parametrize("input_text,expected_absent,expected_present", [
        (
            "The signals are split on whether rates will normalise.",
            "signals are split",
            "two-sided",
        ),
        (
            "Signals diverge on the rate outlook for this quarter.",
            "signals diverge",
            "views diverge",
        ),
        (
            "There is directional disagreement across the investment framework.",
            "directional disagreement",
            "divergence",
        ),
        (
            "Analytical disagreement remains on the Services margin trajectory.",
            "analytical disagreement",
            "divergence",
        ),
        (
            "The constructive vs cautious split reflects genuine macro uncertainty.",
            "constructive vs cautious",
            "mixed",
        ),
        (
            "Evidence suggests that Services margins will remain resilient.",
            "evidence suggests",
            "data",
        ),
    ])
    def test_orchestration_rewrite_fires(self, input_text: str, expected_absent: str, expected_present: str):
        result = institutional_phrase_rewriter(input_text)
        assert expected_absent.lower() not in result.lower(), (
            f"Expected '{expected_absent}' to be rewritten.\n  Input:  {input_text!r}\n  Output: {result!r}"
        )
        assert expected_present.lower() in result.lower(), (
            f"Expected '{expected_present}' in rewritten text.\n  Input:  {input_text!r}\n  Output: {result!r}"
        )

    def test_signals_split_not_in_bull_thesis(self):
        """check_forbidden_phrases catches orchestration leakage in prose fields."""
        thesis = _thesis(bull_thesis="The signals are split on the rate outlook for AAPL.")
        warnings = check_forbidden_phrases(thesis)
        assert any("signals are split" in w for w in warnings), (
            f"Expected 'signals are split' warning, got: {warnings}"
        )

    def test_directional_disagreement_caught_in_bear(self):
        """check_forbidden_phrases catches 'directional disagreement' in bear_thesis."""
        thesis = _thesis(bear_thesis="There is directional disagreement on the macro path.")
        warnings = check_forbidden_phrases(thesis)
        assert any("directional disagreement" in w for w in warnings), (
            f"Expected 'directional disagreement' warning, got: {warnings}"
        )

    def test_no_orchestration_in_confidence_reasoning(self):
        """build_confidence_reasoning never produces orchestration leakage."""
        confs = {"valuation": 0.75, "macro": 0.48, "risk": 0.65, "market": 0.72, "quality": 0.70}
        result = build_confidence_reasoning(confs, None, 8)
        orchestration_phrases = [
            "signals are split", "signals diverge", "directional disagreement",
            "analytical disagreement", "constructive vs cautious",
            "confidence reduced because",
        ]
        for phrase in orchestration_phrases:
            assert phrase not in result.lower(), (
                f"Orchestration phrase '{phrase}' appeared in confidence_reasoning:\n  {result!r}"
            )

    def test_hidden_process_ban_in_prompt(self):
        """Synthesis prompt must include HIDDEN-PROCESS BAN directive."""
        prompt = _synthesis_prompt()
        assert "HIDDEN-PROCESS BAN" in prompt

    def test_prompt_bans_signals_are_split(self):
        """Synthesis prompt must specifically call out 'signals are split'."""
        prompt = _synthesis_prompt()
        assert "signals are split" in prompt


# ══════════════════════════════════════════════════════════════════════════════
# 2. COMPLETENESS BIAS REDUCTION
# ══════════════════════════════════════════════════════════════════════════════

class TestImplicationCompression:
    """Phase D: IMPLICATION_COMPRESSION in prompt; symmetric hedges rewritten."""

    def test_prompt_contains_implication_compression_block(self):
        """Synthesis prompt must include IMPLICATION_COMPRESSION block."""
        prompt = _synthesis_prompt()
        assert "IMPLICATION_COMPRESSION" in prompt

    def test_prompt_contains_stop_there_language(self):
        """Prompt must instruct model to stop once the implication is clear."""
        prompt = _synthesis_prompt()
        # Look for the "STOP THERE" language we added
        assert "STOP THERE" in prompt or "stop writing" in prompt.lower()

    def test_prompt_bans_symmetric_endings(self):
        """Prompt must ban 'could expand if X, but compress if Y' endings."""
        prompt = _synthesis_prompt()
        assert "could expand if" in prompt or "could compress if" in prompt  # examples of what's banned

    def test_prompt_contains_brevity_signals_conviction(self):
        """Prompt must assert that brevity = conviction."""
        prompt = _synthesis_prompt()
        assert "Brevity signals conviction" in prompt

    def test_whichever_prevails_forbidden(self):
        assert "whichever prevails" in FORBIDDEN_PHRASES

    def test_whichever_dominates_forbidden(self):
        assert "whichever dominates" in FORBIDDEN_PHRASES

    def test_either_scenario_forbidden(self):
        assert "either scenario" in FORBIDDEN_PHRASES

    def test_polisher_strips_whichever_prevails(self):
        """Polisher removes 'whichever prevails' from analytical prose."""
        result = institutional_phrase_rewriter(
            "Services growth or rate normalization will drive the outcome, whichever prevails."
        )
        assert "whichever prevails" not in result.lower()

    def test_polisher_handles_in_opposite_directions(self):
        """Polisher removes 'in opposite directions' orchestration language."""
        result = institutional_phrase_rewriter(
            "These two forces affect the multiple in opposite directions."
        )
        assert "in opposite directions" not in result.lower()


# ══════════════════════════════════════════════════════════════════════════════
# 3. PM CADENCE REALISM
# ══════════════════════════════════════════════════════════════════════════════

class TestCadenceVariation:
    """Phase D: CADENCE_VARIATION directives present in synthesis prompt."""

    def test_prompt_contains_cadence_variation_block(self):
        """Synthesis prompt must include CADENCE_VARIATION directive."""
        prompt = _synthesis_prompt()
        assert "CADENCE" in prompt

    def test_prompt_contains_writing_rhythm_block(self):
        """Synthesis prompt must include WRITING RHYTHM directive."""
        prompt = _synthesis_prompt()
        assert "WRITING RHYTHM" in prompt

    def test_prompt_contains_blunt_example_nothing_broken(self):
        """Prompt must give 'Nothing is broken yet' as a blunt cadence example."""
        prompt = _synthesis_prompt()
        assert "Nothing is broken" in prompt

    def test_prompt_contains_blunt_example_risk_is_duration(self):
        """Prompt must give 'The risk is duration' as a blunt cadence example."""
        prompt = _synthesis_prompt()
        assert "The risk is duration" in prompt

    def test_prompt_contains_blunt_example_china_matters(self):
        """Prompt must give 'China matters' as a blunt cadence example."""
        prompt = _synthesis_prompt()
        assert "China matters" in prompt

    def test_prompt_bans_uniform_cadence(self):
        """Prompt must warn against uniform paragraph cadence."""
        prompt = _synthesis_prompt()
        # Check for anti-uniformity language
        assert "uniform" in prompt.lower() or "same approximate length" in prompt.lower()

    def test_prompt_requires_bull_short_sentence(self):
        """Prompt must require bull_thesis to contain a short sentence (≤12 words)."""
        prompt = _synthesis_prompt()
        assert "12 words" in prompt or "≤ 12" in prompt

    def test_cadence_example_rates_matter(self):
        """Prompt must contain the 'Rates matter more than consensus' cadence example."""
        prompt = _synthesis_prompt()
        assert "Rates matter more than consensus" in prompt

    def test_prompt_instructs_abrupt_endings(self):
        """Prompt must say sections can end abruptly once the point is made."""
        prompt = _synthesis_prompt()
        assert "abrupt" in prompt.lower() or "stop there" in prompt or "end abruptly" in prompt.lower()


# ══════════════════════════════════════════════════════════════════════════════
# 4. PRICED_IN_REASONING
# ══════════════════════════════════════════════════════════════════════════════

class TestPricedInReasoning:
    """Phase D: PRICED_IN_REASONING block present and correct in synthesis prompt."""

    def test_prompt_contains_priced_in_reasoning_block(self):
        """Synthesis prompt must include PRICED_IN_REASONING block."""
        prompt = _synthesis_prompt()
        assert "PRICED_IN_REASONING" in prompt

    def test_prompt_requires_what_multiple_implies(self):
        """Prompt must instruct model to state what current multiple implies."""
        prompt = _synthesis_prompt()
        assert "implies" in prompt.lower() or "already prices" in prompt.lower()

    def test_prompt_contains_priced_in_example_good(self):
        """Prompt must give a 'already prices in' positive example."""
        prompt = _synthesis_prompt()
        assert "already prices" in prompt or "already priced" in prompt

    def test_prompt_contains_incremental_upside_requires(self):
        """Prompt must require 'incremental upside requires X' language."""
        prompt = _synthesis_prompt()
        assert "Incremental upside requires" in prompt or "incremental upside" in prompt.lower()

    def test_prompt_bans_timeless_valuation_language(self):
        """Prompt must identify timeless generic valuation claims as BAD."""
        prompt = _synthesis_prompt()
        # The prompt should show "Strong Services margins support the valuation" as BAD
        assert "Strong Services margins support the valuation" in prompt or "BAD" in prompt

    def test_prompt_requires_consensus_vs_nonconsensus(self):
        """Prompt must require distinguishing consensus from non-consensus view."""
        prompt = _synthesis_prompt()
        assert "consensus" in prompt.lower()
        assert "non-consensus" in prompt.lower() or "differentiated" in prompt.lower()

    def test_priced_in_language_not_flagged_as_forbidden(self):
        """'already priced in' is valid PM language — must not be in FORBIDDEN_PHRASES."""
        assert "already priced in" not in FORBIDDEN_PHRASES
        assert "priced in" not in FORBIDDEN_PHRASES


# ══════════════════════════════════════════════════════════════════════════════
# 5. TEMPORAL REALISM
# ══════════════════════════════════════════════════════════════════════════════

class TestTemporalRealism:
    """Phase D: Temporal realism requirements present in synthesis prompt."""

    def test_prompt_contains_temporal_realism_block(self):
        """Synthesis prompt must include TEMPORAL REALISM block."""
        prompt = _synthesis_prompt()
        assert "TEMPORAL REALISM" in prompt

    def test_prompt_contains_recently_marker(self):
        """Prompt must reference 'recently' as a temporal anchoring marker."""
        prompt = _synthesis_prompt()
        assert "recently" in prompt.lower()

    def test_prompt_contains_last_90_days(self):
        """Prompt must reference '90 days' as a temporal window."""
        prompt = _synthesis_prompt()
        assert "90 days" in prompt

    def test_prompt_contains_this_cycle(self):
        """Prompt must reference 'this cycle' as temporal framing."""
        prompt = _synthesis_prompt()
        assert "this cycle" in prompt.lower()

    def test_prompt_contains_since_rates_repriced(self):
        """Prompt must give 'since rates repriced' as temporal anchor example."""
        prompt = _synthesis_prompt()
        assert "since rates repriced" in prompt.lower() or "rates repriced" in prompt.lower()

    def test_prompt_contains_at_current_levels(self):
        """Prompt must reference 'at current levels' as temporal framing."""
        prompt = _synthesis_prompt()
        assert "at current levels" in prompt.lower()

    def test_prompt_bans_timeless_claims(self):
        """Prompt must warn against always-true claims that ignore present context."""
        prompt = _synthesis_prompt()
        assert "timeless" in prompt.lower() or "always or perpetually" in prompt.lower() or "5 years ago" in prompt

    def test_prompt_requires_this_week_feel(self):
        """Prompt must require the memo to feel like it was written this week."""
        prompt = _synthesis_prompt()
        assert "this week" in prompt or "TODAY" in prompt.upper()


# ══════════════════════════════════════════════════════════════════════════════
# 6. UNDERSTATED CONFIDENCE
# ══════════════════════════════════════════════════════════════════════════════

class TestUnderstatedConfidenceForbiddenPhrases:
    """Phase D: Overstated confidence phrases are in FORBIDDEN_PHRASES."""

    def test_highly_compelling_forbidden(self):
        assert "highly compelling" in FORBIDDEN_PHRASES

    def test_strongly_bullish_forbidden(self):
        assert "strongly bullish" in FORBIDDEN_PHRASES

    def test_strongly_bearish_forbidden(self):
        assert "strongly bearish" in FORBIDDEN_PHRASES

    def test_high_conviction_opportunity_forbidden(self):
        assert "high-conviction opportunity" in FORBIDDEN_PHRASES

    def test_exceptional_opportunity_forbidden(self):
        assert "exceptional opportunity" in FORBIDDEN_PHRASES

    def test_exceptional_investment_case_forbidden(self):
        assert "exceptional investment case" in FORBIDDEN_PHRASES

    def test_robust_thesis_forbidden(self):
        assert "robust thesis" in FORBIDDEN_PHRASES

    def test_unambiguously_bullish_forbidden(self):
        assert "unambiguously bullish" in FORBIDDEN_PHRASES


class TestUnderstatedConfidencePolisherRewrites:
    """Phase D: Polisher rewrites overstated confidence to measured PM language."""

    @pytest.mark.parametrize("input_text,expected_absent,expected_present", [
        (
            "This is a highly compelling investment opportunity.",
            "highly compelling",
            "reasonable",
        ),
        (
            "The outlook is strongly bullish for AAPL given Services durability.",
            "strongly bullish",
            "constructive",
        ),
        (
            "The strongly bearish case requires both rate and hardware deterioration.",
            "strongly bearish",
            "cautious",
        ),
        (
            "This represents a high-conviction opportunity at current levels.",
            "high-conviction opportunity",
            "defensible",
        ),
        (
            "This is a robust thesis supported by multiple structural drivers.",
            "robust thesis",
            "defensible",
        ),
        (
            "The exceptional opportunity here lies in Services margin durability.",
            "exceptional opportunity",
            "reasonable",
        ),
    ])
    def test_understated_confidence_rewrite_fires(
        self, input_text: str, expected_absent: str, expected_present: str
    ):
        result = institutional_phrase_rewriter(input_text)
        assert expected_absent.lower() not in result.lower(), (
            f"Expected '{expected_absent}' to be rewritten.\n  Input:  {input_text!r}\n  Output: {result!r}"
        )
        assert expected_present.lower() in result.lower(), (
            f"Expected '{expected_present}' in rewritten text.\n  Input:  {input_text!r}\n  Output: {result!r}"
        )

    def test_highly_compelling_caught_in_bull_thesis(self):
        """check_forbidden_phrases catches 'highly compelling' in bull_thesis."""
        thesis = _thesis(bull_thesis="This is a highly compelling risk/reward setup for AAPL.")
        warnings = check_forbidden_phrases(thesis)
        assert any("highly compelling" in w for w in warnings), (
            f"Expected 'highly compelling' warning, got: {warnings}"
        )

    def test_strongly_bullish_caught_in_conclusion(self):
        """check_forbidden_phrases catches 'strongly bullish' in conclusion."""
        thesis = _thesis(conclusion="The thesis is strongly bullish given Services trajectory.")
        warnings = check_forbidden_phrases(thesis)
        assert any("strongly bullish" in w for w in warnings), (
            f"Expected 'strongly bullish' warning, got: {warnings}"
        )

    def test_prompt_bans_highly_compelling(self):
        """Synthesis prompt must specifically ban 'highly compelling'."""
        prompt = _synthesis_prompt()
        assert "highly compelling" in prompt

    def test_prompt_bans_strongly_bullish(self):
        """Synthesis prompt must ban 'strongly bullish'."""
        prompt = _synthesis_prompt()
        assert "strongly bullish" in prompt

    def test_prompt_contains_nothing_broken_yet(self):
        """Prompt must give 'Nothing is broken yet' as understated bullish language."""
        prompt = _synthesis_prompt()
        assert "Nothing is broken yet" in prompt

    def test_prompt_contains_thesis_still_works(self):
        """Prompt must give 'The thesis still works' as understated bullish language."""
        prompt = _synthesis_prompt()
        assert "The thesis still works" in prompt

    def test_build_confidence_no_overstated_language(self):
        """build_confidence_reasoning must not produce overstated confidence phrases."""
        confs = {"valuation": 0.85, "macro": 0.82, "risk": 0.80, "market": 0.83, "quality": 0.81}
        result = build_confidence_reasoning(confs, None, 12)
        overstated = ["highly compelling", "strongly bullish", "exceptional", "high-conviction"]
        for phrase in overstated:
            assert phrase not in result.lower(), (
                f"Overstated phrase '{phrase}' found in confidence_reasoning:\n  {result!r}"
            )


# ══════════════════════════════════════════════════════════════════════════════
# 7. SECTION ASYMMETRY SHARPENED
# ══════════════════════════════════════════════════════════════════════════════

class TestSectionAsymmetrySharpened:
    """Phase D: DEEP vs COMPRESSED contrast is pushed further; 1-sentence HARD CAP."""

    def test_macro_directive_has_hard_cap_language(self):
        """_DEPTH_DIRECTIVES['macro'] must specify 1-sentence HARD CAP for valuation_view."""
        directive = _DEPTH_DIRECTIVES["macro"]
        assert "HARD CAP" in directive or "hard cap" in directive.lower()

    def test_macro_directive_compressed_valuation_is_1_sentence(self):
        """Macro directive must explicitly limit valuation_view to 1 sentence."""
        directive = _DEPTH_DIRECTIVES["macro"]
        assert "1 sentence" in directive

    def test_macro_directive_deep_macro_sensitivity(self):
        """Macro directive must mark macro_sensitivity as DEEP."""
        directive = _DEPTH_DIRECTIVES["macro"]
        assert "DEEP" in directive
        assert "macro_sensitivity" in directive

    def test_macro_directive_contains_enforcement_language(self):
        """Macro directive must state the failure condition for asymmetry violation."""
        directive = _DEPTH_DIRECTIVES["macro"]
        assert "failed" in directive.lower() or "failure" in directive.lower() or "ENFORCEMENT" in directive

    def test_valuation_directive_compressed_macro(self):
        """Valuation directive must mark macro_sensitivity as COMPRESSED (1 sentence)."""
        directive = _DEPTH_DIRECTIVES["valuation"]
        assert "1 sentence" in directive
        assert "COMPRESSED" in directive
        assert "macro_sensitivity" in directive

    def test_regulatory_directive_deep_bear_thesis(self):
        """Regulatory directive must mark bear_thesis as DEEP."""
        directive = _DEPTH_DIRECTIVES["regulatory"]
        assert "DEEP" in directive
        assert "bear_thesis" in directive
        assert "4 sentences" in directive

    def test_capital_allocation_directive_deep_bull(self):
        """Capital allocation directive must mark bull_thesis as DEEP."""
        directive = _DEPTH_DIRECTIVES["capital_allocation"]
        assert "DEEP" in directive
        assert "bull_thesis" in directive

    def test_capital_allocation_directive_compressed_macro(self):
        """Capital allocation directive must mark macro_sensitivity as COMPRESSED (1 sentence)."""
        directive = _DEPTH_DIRECTIVES["capital_allocation"]
        assert "1 sentence" in directive
        assert "macro_sensitivity" in directive

    def test_operational_directive_both_bull_bear_deep(self):
        """Operational directive must mark BOTH bull_thesis and bear_thesis as DEEP."""
        directive = _DEPTH_DIRECTIVES["operational"]
        assert directive.count("DEEP") >= 2, (
            f"Expected at least 2 DEEP markers in operational directive, got: {directive.count('DEEP')}"
        )

    def test_section_priority_block_macro_shows_compressed_valuation(self):
        """_build_section_priority_block('macro') must show valuation_view=COMPRESSED."""
        block = _build_section_priority_block("macro")
        assert "COMPRESSED" in block
        assert "valuation" in block.lower() or "valuation_view" in block.lower()

    def test_section_priority_block_valuation_shows_compressed_macro(self):
        """_build_section_priority_block('valuation') must show macro_sensitivity=COMPRESSED."""
        block = _build_section_priority_block("valuation")
        assert "COMPRESSED" in block
        assert "macro" in block.lower()

    def test_all_directives_have_hard_cap(self):
        """All _DEPTH_DIRECTIVES must contain 'HARD CAP' language."""
        for dim, directive in _DEPTH_DIRECTIVES.items():
            assert "HARD CAP" in directive or "1 sentence" in directive, (
                f"Directive for '{dim}' is missing HARD CAP / 1-sentence language:\n{directive[:300]}"
            )

    def test_macro_dominant_detection_weights_macro(self):
        """_detect_dominant_dimension elevates macro when macro_confidence is low."""
        mac = _macro(
            overall="Federal Reserve rate hike compressed discount rates sharply.",
            confidence=0.42,  # low → +2.0 macro boost
        )
        val = _valuation(overall="Valuation looks full at 28x.", confidence=0.75)
        risk = _risk(overall="Rate duration is the primary risk.")
        dominant = _detect_dominant_dimension(mac, risk, val, ranked=None)
        assert dominant == "macro", f"Expected 'macro' dominant, got '{dominant}'"

    def test_prompt_contains_section_asymmetry_block(self):
        """Synthesis prompt must include SECTION ASYMMETRY directive."""
        prompt = _synthesis_prompt()
        assert "SECTION ASYMMETRY" in prompt


# ══════════════════════════════════════════════════════════════════════════════
# Integration scenario tests — 4 ticker examples
# ══════════════════════════════════════════════════════════════════════════════

class TestAppleRatesScenario:
    """Apple / rates scenario: macro dominant, orchestration-free output."""

    def test_confidence_reasoning_no_orchestration(self):
        """Apple/rates confidence reasoning must be orchestration-free."""
        # Macro uncertain (rates re-pricing), all others moderate
        confs = {"valuation": 0.72, "macro": 0.44, "risk": 0.66, "market": 0.70, "quality": 0.68}
        result = build_confidence_reasoning(confs, None, 9)
        banned = [
            "signals are split", "signals diverge", "directional disagreement",
            "analytical disagreement", "constructive vs cautious",
            "confidence reduced because", "evidence suggests the thesis",
        ]
        for phrase in banned:
            assert phrase not in result.lower(), (
                f"Orchestration phrase '{phrase}' in Apple/rates output:\n  {result!r}"
            )

    def test_confidence_reasoning_names_macro_uncertainty(self):
        """Apple/rates: macro uncertainty case should name the macro variable."""
        confs = {"valuation": 0.72, "macro": 0.44, "risk": 0.66, "market": 0.70, "quality": 0.68}
        result = build_confidence_reasoning(confs, None, 9)
        assert (
            "macro" in result.lower()
            or "timing" in result.lower()
            or "unresolved" in result.lower()
        ), f"Apple/rates should name macro uncertainty:\n  {result!r}"

    def test_apple_synthesis_prompt_macro_dominant(self):
        """Apple/rates synthesis prompt should have macro-dominant depth directives."""
        company = _company("AAPL")
        val = _valuation(overall="AAPL trades at 28x forward.", confidence=0.73)
        mac = _macro(
            overall="Federal Reserve rate hike drives DCF compression for AAPL.",
            confidence=0.42,  # triggers macro dominance
        )
        risk = _risk(overall="Rate duration risk for long-duration cash flows.")
        mkt = _market()
        qual = _quality()
        prompt = _build_synthesis_prompt(company, val, mac, risk, mkt, qual, evidence=[])
        # Macro dominant → should include DEEP label for macro_sensitivity
        assert "macro_sensitivity" in prompt
        assert "COMPRESSED" in prompt  # valuation should be COMPRESSED


class TestNvidiaDemandDurabilityScenario:
    """Nvidia demand durability scenario: understated even when constructive."""

    def test_confidence_reasoning_understated_when_bullish(self):
        """High confidence case must still use understated language."""
        confs = {"valuation": 0.80, "macro": 0.78, "risk": 0.75, "market": 0.82, "quality": 0.77}
        result = build_confidence_reasoning(confs, None, 12)
        overstated = [
            "highly compelling", "strongly bullish", "exceptional opportunity",
            "unambiguously", "high conviction", "strong conviction",
        ]
        for phrase in overstated:
            assert phrase not in result.lower(), (
                f"Overstated phrase '{phrase}' in Nvidia/high-conf output:\n  {result!r}"
            )

    def test_confidence_reasoning_high_conf_names_timing(self):
        """High confidence case must name timing as residual uncertainty."""
        confs = {"valuation": 0.80, "macro": 0.78, "risk": 0.75, "market": 0.82, "quality": 0.77}
        result = build_confidence_reasoning(confs, None, 12)
        assert (
            "timing" in result.lower()
            or "reads cleanly" in result.lower()
            or "investment case" in result.lower()
        ), f"High conf case should name timing uncertainty:\n  {result!r}"

    def test_nvda_no_forbidden_in_rewritten_text(self):
        """Polisher removes all forbidden phrases from a constructed Nvidia bull thesis."""
        nvda_bull = (
            "This is a highly compelling investment case for NVDA — the data center demand "
            "signals converge on a multi-year structural cycle. The evidence supports the thesis "
            "of sustained AI capex, and strong conviction remains elevated given the GPU scarcity."
        )
        result = institutional_phrase_rewriter(nvda_bull)
        banned = ["highly compelling", "signals converge", "evidence supports the thesis",
                  "strong conviction", "remains elevated"]
        for phrase in banned:
            assert phrase not in result.lower(), (
                f"Phrase '{phrase}' survived polisher in NVDA text:\n  Input:  {nvda_bull!r}\n  Output: {result!r}"
            )


class TestMetaCapexScenario:
    """Meta capex cycle scenario: completeness bias + understated confidence."""

    def test_meta_no_symmetric_hedge_in_polished_text(self):
        """Polisher should handle 'whichever prevails' endings in Meta-style prose."""
        meta_text = (
            "Reality Labs losses compress Meta's margins while Advantage+ revenue offsets them, "
            "whichever prevails."
        )
        result = institutional_phrase_rewriter(meta_text)
        assert "whichever prevails" not in result.lower(), (
            f"'whichever prevails' survived polisher:\n  Input:  {meta_text!r}\n  Output: {result!r}"
        )

    def test_meta_constructive_vs_cautious_rewritten(self):
        """'constructive vs cautious' is rewritten to a direct directional statement."""
        meta_text = "The constructive vs cautious split on Meta's capex cycle reflects genuine uncertainty."
        result = institutional_phrase_rewriter(meta_text)
        assert "constructive vs cautious" not in result.lower(), (
            f"'constructive vs cautious' survived polisher:\n  Output: {result!r}"
        )

    def test_meta_robust_thesis_rewritten(self):
        """'robust thesis' rewritten to 'defensible thesis'."""
        meta_text = "Meta's AI-driven ad stack underpins a robust thesis for margin recovery."
        result = institutional_phrase_rewriter(meta_text)
        assert "robust thesis" not in result.lower()
        assert "defensible" in result.lower()


class TestTeslaValuationCompressionScenario:
    """Tesla valuation compression scenario: direction split + priced-in cognition."""

    def test_tesla_direction_split_confidence_no_orchestration(self):
        """Direction-split case must not produce orchestration leakage."""
        # 3 bullish, 3 bearish signals → genuine split
        bull_sigs = [
            Signal(signal="Full Self Driving attach rates accelerate EPS.", impact_score=0.8,
                   confidence=0.7, signal_type="catalyst", direction="bullish", source_agent="test"),
            Signal(signal="Energy segment gross margin expands toward 20%.", impact_score=0.75,
                   confidence=0.7, signal_type="structural", direction="bullish", source_agent="test"),
            Signal(signal="Cybertruck volume ramp reduces unit cost.", impact_score=0.7,
                   confidence=0.65, signal_type="operational", direction="bullish", source_agent="test"),
        ]
        bear_sigs = [
            Signal(signal="EV demand softens as tax credit uncertainty weighs.", impact_score=0.8,
                   confidence=0.72, signal_type="risk", direction="bearish", source_agent="test"),
            Signal(signal="Auto gross margin compresses on ASP cuts.", impact_score=0.78,
                   confidence=0.70, signal_type="risk", direction="bearish", source_agent="test"),
            Signal(signal="China market share erodes amid BYD competition.", impact_score=0.73,
                   confidence=0.68, signal_type="risk", direction="bearish", source_agent="test"),
        ]
        ranked = RankedSignalSet(
            top_signals=bull_sigs,
            top_risks=bear_sigs,
            all_ranked=bull_sigs + bear_sigs,
        )
        confs = {"valuation": 0.65, "macro": 0.62, "risk": 0.60, "market": 0.68, "quality": 0.63}
        result = build_confidence_reasoning(confs, ranked, 8)

        orchestration_banned = [
            "signals are split", "directional disagreement", "analytical disagreement",
            "constructive vs cautious",
        ]
        for phrase in orchestration_banned:
            assert phrase not in result.lower(), (
                f"Orchestration phrase '{phrase}' in Tesla direction-split output:\n  {result!r}"
            )

    def test_tesla_split_confidence_names_two_sided(self):
        """Direction-split case should name the two-sided nature without process language."""
        bull_sigs = [
            Signal(signal="FSD EPS acceleration.", impact_score=0.8, confidence=0.7,
                   signal_type="catalyst", direction="bullish", source_agent="t"),
            Signal(signal="Energy margin expansion.", impact_score=0.75, confidence=0.7,
                   signal_type="structural", direction="bullish", source_agent="t"),
            Signal(signal="Cybertruck ramp.", impact_score=0.7, confidence=0.65,
                   signal_type="operational", direction="bullish", source_agent="t"),
        ]
        bear_sigs = [
            Signal(signal="EV demand softens.", impact_score=0.8, confidence=0.72,
                   signal_type="risk", direction="bearish", source_agent="t"),
            Signal(signal="Auto margin compression.", impact_score=0.78, confidence=0.70,
                   signal_type="risk", direction="bearish", source_agent="t"),
            Signal(signal="China share erosion.", impact_score=0.73, confidence=0.68,
                   signal_type="risk", direction="bearish", source_agent="t"),
        ]
        ranked = RankedSignalSet(
            top_signals=bull_sigs, top_risks=bear_sigs,
            all_ranked=bull_sigs + bear_sigs,
        )
        confs = {"valuation": 0.65, "macro": 0.62, "risk": 0.60, "market": 0.68, "quality": 0.63}
        result = build_confidence_reasoning(confs, ranked, 8)
        # Should describe the two-sided nature analytically
        assert (
            "two-sided" in result.lower()
            or "evenly matched" in result.lower()
            or "balanced" in result.lower()
            or "genuinely" in result.lower()
        ), f"Tesla direction-split should name two-sided nature:\n  {result!r}"
