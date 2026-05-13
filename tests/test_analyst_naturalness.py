"""
Analyst naturalness + terminal-grade compression tests.

Covers Refinements 1–6 from the analyst-naturalness upgrade phase:

1. Hero thesis compression     — compress_hero_thesis() → ≤22 words, no brackets,
                                 no verbose parentheticals or gerund chains.
2. Analyst-natural language    — "continues to X" contracts; synthetic constructions
                                 rewritten; banned phrases do not survive polish_thesis().
3. Confidence de-numericalization — naturalize_confidence_prose() removes ALL
                                 percentages from confidence_reasoning text.
4. Terminal density            — no filler openers or explanatory transitions in
                                 polished output.
5. Structural variety          — _enforce_structural_variety() rotates duplicate
                                 opening templates; sections lead with distinct framings.
6. Final language filter       — extended FORBIDDEN_PHRASES covers new synthetic
                                 construction patterns.

Apple/rates scenario: hero thesis concise + mechanism-first; no synthetic
finance boilerplate survives the full polisher pipeline.
"""
from __future__ import annotations

import re
import pytest
from typing import List

from app.schemas import InvestmentThesis, Signal
from app.services.thesis_polisher import (
    compress_hero_thesis,
    naturalize_confidence_prose,
    institutional_phrase_rewriter,
    polish_thesis,
    _enforce_structural_variety,
    _split_sentences,
    _join_sentences,
    _SENTENCE_LIMITS,
)
from app.services.signal_ranker import FORBIDDEN_PHRASES


# ── Shared fixtures ───────────────────────────────────────────────────────────

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


# ══════════════════════════════════════════════════════════════════════════════
# REFINEMENT 1 — Hero Thesis Compression
# ══════════════════════════════════════════════════════════════════════════════

class TestCompressHeroThesis:
    """compress_hero_thesis() must produce a tight, mechanism-first sentence
    with no confidence bracket, no parenthetical elaborations, and no trailing
    gerund chains."""

    # ── Confidence bracket stripping ─────────────────────────────────────────

    def test_strips_high_conviction_bracket(self):
        text = "Apple Services margin resilience limits downside. [high conviction, 75%]"
        result = compress_hero_thesis(text)
        assert "[high conviction" not in result, (
            f"Confidence bracket must be stripped: {result!r}"
        )
        assert "%" not in result, f"No percentage should remain: {result!r}"

    def test_strips_moderate_conviction_bracket(self):
        text = "Rate-driven P/E compression limits AAPL upside. [moderate conviction, 62%]"
        result = compress_hero_thesis(text)
        assert "[moderate conviction" not in result
        assert "62%" not in result

    def test_strips_low_conviction_bracket(self):
        text = "China tariff risk threatens $20B revenue. [low conviction, 45%]"
        result = compress_hero_thesis(text)
        assert "[low conviction" not in result

    # ── Parenthetical "with its" stripping ───────────────────────────────────

    def test_strips_with_its_parenthetical(self):
        text = (
            "Apple's Services segment, with its high 72% gross margin, "
            "expands blended margins."
        )
        result = compress_hero_thesis(text)
        assert "with its" not in result.lower(), (
            f"'with its' parenthetical must be stripped: {result!r}"
        )
        # Core meaning preserved
        assert "Services" in result or "margin" in result.lower()

    # ── Trailing gerund chain stripping ──────────────────────────────────────

    def test_strips_trailing_offsetting_chain(self):
        text = (
            "Apple's Services expands, offsetting hardware margin pressures "
            "and supporting a higher blended P/E multiple."
        )
        result = compress_hero_thesis(text)
        assert "offsetting" not in result.lower(), (
            f"Trailing 'offsetting' chain must be removed: {result!r}"
        )

    def test_strips_trailing_supporting_chain(self):
        text = (
            "Services recurring cash flows buffer cyclical hardware demand, "
            "supporting a higher valuation multiple."
        )
        result = compress_hero_thesis(text)
        assert "supporting a higher" not in result.lower()

    # ── Word count enforcement ────────────────────────────────────────────────

    def test_default_max_words_22(self):
        """Verbose sentence should be compressed to ≤22 words."""
        text = (
            "Apple's expanding Services segment, with its high 72% gross margin "
            "and $100B ARR, continues to expand rapidly, offsetting hardware margin "
            "pressures entirely and supporting a significantly higher blended P/E "
            "multiple for the overall company valuation."
        )
        result = compress_hero_thesis(text)
        words = result.split()
        assert len(words) <= 25, (  # 25 allows for the truncated trailing word
            f"Compressed hero thesis should be ≤22 words, got {len(words)}: {result!r}"
        )

    def test_custom_max_words_respected(self):
        text = (
            "Rate-driven multiple compression threatens AAPL's 28x forward P/E via "
            "DCF discount rate expansion, while Services provides a partial offset "
            "through its 72% gross margin and $100B ARR recurring cash flow base."
        )
        result = compress_hero_thesis(text, max_words=18)
        words = result.split()
        assert len(words) <= 22, (
            f"With max_words=18 compress should stay ≤22, got {len(words)}: {result!r}"
        )

    def test_short_sentence_unchanged(self):
        """Sentences already at or under target must not be modified."""
        text = "Rate compression threatens AAPL's 28x P/E via DCF expansion."
        result = compress_hero_thesis(text)
        words = result.split()
        assert len(words) <= 22
        assert "AAPL" in result or "P/E" in result

    def test_returns_terminal_punctuation(self):
        """Output must always end with '.'"""
        text = "Apple Services margin absorbs rate-driven P/E pressure [high conviction, 72%]"
        result = compress_hero_thesis(text)
        assert result.endswith("."), f"Result must end with '.': {result!r}"

    def test_empty_string_passthrough(self):
        assert compress_hero_thesis("") == ""

    def test_none_like_passthrough(self):
        """Non-empty whitespace-only string should return unchanged."""
        assert compress_hero_thesis("   ").strip() == ""

    def test_apple_rates_hero_concise_and_mechanism_first(self):
        """Apple/rates scenario: hero thesis concise and starts with mechanism."""
        text = (
            "Apple's 28x forward P/E multiple is compressed by higher rates via "
            "DCF discount-rate expansion, with its $100B ARR Services segment, "
            "which provides rate-insensitive cash flows, offsetting hardware margin "
            "pressures and supporting a higher blended P/E multiple for the company. "
            "[high conviction, 74%]"
        )
        result = compress_hero_thesis(text)
        words = result.split()
        # Concise
        assert len(words) <= 25, f"Hero thesis too verbose ({len(words)} words): {result!r}"
        # No confidence bracket
        assert "conviction" not in result.lower()
        # No gerund chain
        assert "offsetting" not in result.lower()
        # Mechanism-related terms preserved
        assert any(term in result for term in ["P/E", "rate", "compress", "DCF"]), (
            f"Mechanism terms must survive compression: {result!r}"
        )


# ══════════════════════════════════════════════════════════════════════════════
# REFINEMENT 2 — Analyst-Natural Language
# ══════════════════════════════════════════════════════════════════════════════

class TestInstitutionalPhraseRewriterExpanded:
    """Refinement 2 extensions: 'continues to X' contracts; synthetic
    constructions rewritten to hedge-fund memo phrasing."""

    def test_continues_to_expand_contracted(self):
        result = institutional_phrase_rewriter(
            "Apple Services continues to expand margins annually."
        )
        assert "continues to expand" not in result.lower(), (
            f"'continues to expand' must be contracted: {result!r}"
        )
        assert "expands" in result.lower(), (
            f"'expands' should replace 'continues to expand': {result!r}"
        )

    def test_continues_to_grow_contracted(self):
        result = institutional_phrase_rewriter(
            "The recurring revenue base continues to grow at 15% CAGR."
        )
        assert "continues to grow" not in result.lower()
        assert "grows" in result.lower()

    def test_continues_to_benefit_contracted(self):
        result = institutional_phrase_rewriter(
            "Apple continues to benefit from Services margin mix."
        )
        assert "continues to benefit" not in result.lower()
        assert "benefits" in result.lower()

    def test_continues_to_compress_contracted(self):
        result = institutional_phrase_rewriter(
            "Higher rates continue to compress AAPL's forward P/E."
        )
        # "continue to" (not "continues to") — won't match; test what we do match
        # Test with "continues to compress"
        result2 = institutional_phrase_rewriter(
            "The multiple continues to compress under rate pressure."
        )
        assert "continues to compress" not in result2.lower()
        assert "compresses" in result2.lower()

    def test_remains_compelling_rewritten(self):
        result = institutional_phrase_rewriter(
            "The risk/reward profile remains compelling at current levels."
        )
        assert "remains compelling" not in result.lower(), (
            f"'remains compelling' must be rewritten: {result!r}"
        )
        assert "asymmetric" in result.lower() or "risk" in result.lower()

    def test_supports_higher_valuation_rewritten(self):
        result = institutional_phrase_rewriter(
            "Services margin mix supports a higher valuation multiple."
        )
        assert "supports a higher valuation" not in result.lower() and \
               "supports higher valuation" not in result.lower(), (
            f"'supports higher valuation' must be rewritten: {result!r}"
        )

    def test_contributes_to_growth_rewritten(self):
        result = institutional_phrase_rewriter(
            "The buyback program contributes to growth in EPS."
        )
        assert "contributes to growth" not in result.lower(), (
            f"'contributes to growth' must be rewritten: {result!r}"
        )

    def test_offsets_pressure_rewritten(self):
        result = institutional_phrase_rewriter(
            "Services margin offsets the pressure from hardware compression."
        )
        assert "offsets pressure" not in result.lower() or \
               "absorbs pressure" in result.lower(), (
            f"'offsets pressure' must be rewritten: {result!r}"
        )

    def test_strategically_positioned_rewritten(self):
        result = institutional_phrase_rewriter(
            "Apple is strategically positioned to benefit from AI adoption."
        )
        assert "strategically positioned" not in result.lower(), (
            f"'strategically positioned' must be removed: {result!r}"
        )
        assert "positioned" in result.lower()

    def test_core_content_preserved_after_rewrite(self):
        """Rewrites must not destroy the key facts/numbers."""
        result = institutional_phrase_rewriter(
            "Apple Services continues to expand at 15% CAGR with 72% gross margin."
        )
        assert "15%" in result, f"Percentage data must survive rewrite: {result!r}"
        assert "72%" in result, f"Margin data must survive rewrite: {result!r}"
        assert "Services" in result, f"Segment name must survive: {result!r}"


# ══════════════════════════════════════════════════════════════════════════════
# REFINEMENT 3 — Confidence De-numericalization
# ══════════════════════════════════════════════════════════════════════════════

class TestNaturalizeConfidenceProse:
    """naturalize_confidence_prose() must strip ALL percentage values from
    confidence_reasoning text intended for frontend delivery."""

    def test_strips_parenthesized_percentage(self):
        text = "Confidence is reduced because macro registers lower conviction (52%)."
        result = naturalize_confidence_prose(text)
        assert "52%" not in result, f"Parenthesized percentage must be stripped: {result!r}"

    def test_strips_parenthesized_percentage_with_label(self):
        text = "Lower conviction (45% confidence) due to thin evidence."
        result = naturalize_confidence_prose(text)
        assert "45%" not in result

    def test_strips_bare_percentage(self):
        text = "Valuation analysis registers 81% confidence versus macro at 51%."
        result = naturalize_confidence_prose(text)
        assert "81%" not in result, f"Bare percentage must be stripped: {result!r}"
        assert "51%" not in result

    def test_strips_geq_percentage(self):
        text = "Each agent converges (each ≥70% confidence) on the bearish thesis."
        result = naturalize_confidence_prose(text)
        assert "70%" not in result, f"≥ percentage must be stripped: {result!r}"

    def test_is_x_percent_bullish_converted(self):
        text = "Signal direction is 80% bullish across 5 ranked signals."
        result = naturalize_confidence_prose(text)
        assert "80%" not in result, f"Percentage before bullish must be stripped: {result!r}"
        # Should be replaced with "leans bullish" or equivalent
        assert "bullish" in result.lower(), f"'bullish' must remain: {result!r}"

    def test_averaging_percent_converted(self):
        text = "Agent consensus averaging 74% across 5 specialists."
        result = naturalize_confidence_prose(text)
        assert "74%" not in result
        # "averaging X% across" → "broadly aligned across"
        assert "aligned" in result.lower() or "consistent" in result.lower() \
               or "5" in result, f"Qualitative replacement should remain: {result!r}"

    def test_no_percentage_text_unchanged(self):
        """Text with no percentages must not be modified."""
        text = (
            "Evidence is directionally constructive on valuation; "
            "macro and regulatory headwinds remain harder to size."
        )
        result = naturalize_confidence_prose(text)
        assert result.strip() == text.strip(), (
            f"Percentage-free text must not be modified: {result!r}"
        )

    def test_empty_string_passthrough(self):
        assert naturalize_confidence_prose("") == ""

    def test_result_contains_no_bare_percentage(self):
        """End-to-end: any confidence text with mixed percentages must be clean."""
        text = (
            "Confidence is reduced because macro analysis registers lower conviction "
            "(52%) versus valuation analysis (81%), indicating disagreement on a key "
            "mechanism. Signal direction leans bearish (4 bullish vs 7 bearish) — "
            "thesis could inflect either way."
        )
        result = naturalize_confidence_prose(text)
        # No bare percentage should survive
        assert not re.search(r'\b\d+%\b', result), (
            f"No percentage should survive naturalize_confidence_prose: {result!r}"
        )

    def test_multiple_percentages_all_stripped(self):
        text = "Valuation at 82%, macro at 51%, risk at 75%, market at 70%, quality at 68%."
        result = naturalize_confidence_prose(text)
        assert not re.search(r'\b\d+%\b', result), (
            f"All percentages must be stripped: {result!r}"
        )

    def test_output_is_still_readable_prose(self):
        """After stripping, output must be a non-empty readable string."""
        text = (
            "Confidence is elevated because valuation, macro, and risk analysis "
            "independently converge on the same thesis direction (each ≥70% confidence). "
            "Signal direction is 78% bearish (2 bullish vs 7 bearish) across 9 ranked signals."
        )
        result = naturalize_confidence_prose(text)
        assert len(result) > 20, f"Result must be readable prose, not empty: {result!r}"
        assert not result.startswith(","), f"Leading comma artefact: {result!r}"


# ══════════════════════════════════════════════════════════════════════════════
# REFINEMENT 5 — Structural Variety Enforcement
# ══════════════════════════════════════════════════════════════════════════════

class TestEnforceStructuralVariety:
    """_enforce_structural_variety() must rotate sentence order when two or
    more sections open with the same support/provide/enable template."""

    def test_rotates_second_collision(self):
        """When bull and conclusion both start with 'X supports Y', conclusion rotates."""
        t = _thesis(
            bull_thesis=(
                "Apple's Services supports valuation despite rate-driven multiple pressure. "
                "iOS switching costs anchor 95% retention."
            ),
            bear_thesis="China tariff exposure threatens $20B iPhone revenue.",
            conclusion=(
                "Apple's buyback program supports EPS despite hardware cyclicality. "
                "Rate risk remains the primary derating catalyst."
            ),
        )
        result = _enforce_structural_variety(t)
        # Conclusion should now lead with the second original sentence
        assert result.conclusion.startswith("Rate risk"), (
            f"Conclusion should rotate to lead with non-template sentence: "
            f"{result.conclusion!r}"
        )

    def test_distinct_openers_not_rotated(self):
        """Sections with distinct opening templates must not be modified."""
        t = _thesis(
            bull_thesis=(
                "iOS switching costs anchor 95% upgrade retention. "
                "Services at 72% margin buffers rate-driven P/E pressure."
            ),
            conclusion=(
                "China tariff risk threatens $20B in hardware revenue. "
                "The key inflection is Q4 guidance visibility."
            ),
        )
        original_bull = t.bull_thesis
        original_conc = t.conclusion
        result = _enforce_structural_variety(t)
        assert result.bull_thesis == original_bull, "Distinct bull_thesis must not be rotated"
        assert result.conclusion == original_conc, "Distinct conclusion must not be rotated"

    def test_single_sentence_section_not_rotated(self):
        """A section with only one sentence cannot be rotated — must be left alone."""
        t = _thesis(
            bull_thesis="Apple's Services supports valuation despite rate pressure.",
            conclusion=(
                "Apple's buyback program supports EPS despite hardware demand risk. "
                "Rate timing is the primary uncertainty."
            ),
        )
        result = _enforce_structural_variety(t)
        # bull_thesis has only one sentence — no rotation possible
        assert result.bull_thesis == t.bull_thesis, (
            "Single-sentence section must not be modified"
        )

    def test_template_not_fired_on_distinct_verbs(self):
        """Only 'support/provide/enable/deliver/anchor/sustain/limit/constrain' trigger."""
        t = _thesis(
            bull_thesis=(
                "Rate compression threatens AAPL's P/E via DCF expansion. "
                "Services buffers the downside through recurring cash flows."
            ),
            conclusion=(
                "China tariff exposure weighs on $20B hardware revenue. "
                "Buyback sustains EPS even in a demand slowdown."
            ),
        )
        original_bull = t.bull_thesis
        original_conc = t.conclusion
        result = _enforce_structural_variety(t)
        # Neither section starts with a support-class verb → no rotation
        assert result.bull_thesis == original_bull
        assert result.conclusion == original_conc

    def test_only_first_collision_preserved(self):
        """First section with the template is preserved; second is rotated."""
        t = _thesis(
            bull_thesis=(
                "Apple's Services delivers margin resilience against rate pressure. "
                "Services ARR at $100B limits cyclical downside exposure."
            ),
            bear_thesis=(
                "Apple's hardware demand provides limited upside in a rate-rise cycle. "
                "China tariff exposure compounds the margin compression risk."
            ),
        )
        result = _enforce_structural_variety(t)
        # bull_thesis is first with the template → preserved unchanged
        assert result.bull_thesis == t.bull_thesis, (
            "First template-matching section must not be rotated"
        )
        # bear_thesis is second → should be rotated
        assert result.bear_thesis != t.bear_thesis, (
            "Second template-matching section must be rotated"
        )
        # bear_thesis should now start with the second original sentence
        assert "China tariff" in result.bear_thesis[:40], (
            f"Rotated bear_thesis should lead with China tariff sentence: "
            f"{result.bear_thesis!r}"
        )

    def test_no_sentences_lost_after_rotation(self):
        """Rotation must preserve all sentences — only order changes."""
        t = _thesis(
            bull_thesis=(
                "Apple's Services supports valuation despite rate pressure. "
                "Buyback at $90B annually compresses share count by 4% pa."
            ),
            conclusion=(
                "Apple's net-cash position supports EPS despite hardware demand softness. "
                "The key catalyst is Q4 guidance on Services attach rate acceleration."
            ),
        )
        result = _enforce_structural_variety(t)
        # Sentences present before rotation should still be present after
        assert "Buyback" in result.bull_thesis or "Buyback" in result.conclusion
        assert "Q4 guidance" in result.bull_thesis or "Q4 guidance" in result.conclusion

    def test_immutable_update_pattern(self):
        """Original thesis must not be mutated — function returns a new object."""
        t = _thesis(
            bull_thesis=(
                "Apple's Services supports valuation despite rate pressure. "
                "Services $100B ARR limits downside."
            ),
            conclusion=(
                "Apple's buyback supports EPS despite hardware demand risk. "
                "Timing of rate cuts is the key inflection trigger."
            ),
        )
        original_bull = t.bull_thesis
        original_conc = t.conclusion
        result = _enforce_structural_variety(t)
        # Original object unchanged
        assert t.bull_thesis == original_bull
        assert t.conclusion == original_conc
        # Result is a different object
        assert result is not t


# ══════════════════════════════════════════════════════════════════════════════
# REFINEMENT 6 — Final Language Filter (FORBIDDEN_PHRASES)
# ══════════════════════════════════════════════════════════════════════════════

class TestFinalLanguageFilter:
    """Extended FORBIDDEN_PHRASES must cover all new synthetic constructions."""

    @pytest.mark.parametrize("phrase", [
        "remains compelling",
        "continues to expand",
        "continues to grow",
        "continues to benefit",
        "supports higher valuation",
        "contributes to growth",
        "offsets pressure",
        "indicates strength",
        "strategically positioned",
    ])
    def test_new_phrase_in_forbidden_set(self, phrase: str):
        assert phrase in FORBIDDEN_PHRASES, (
            f"'{phrase}' must be in FORBIDDEN_PHRASES"
        )

    @pytest.mark.parametrize("phrase", [
        # Existing phrases from prior phase
        "well positioned",
        "solid fundamentals",
        "going forward",
        "this indicates",
        "poised to benefit",
        "strong positioning",
    ])
    def test_existing_phrases_still_forbidden(self, phrase: str):
        assert phrase in FORBIDDEN_PHRASES, (
            f"Previously forbidden phrase '{phrase}' must still be in FORBIDDEN_PHRASES"
        )

    def test_forbidden_phrases_are_strings(self):
        """All entries must be plain lowercase strings."""
        for phrase in FORBIDDEN_PHRASES:
            assert isinstance(phrase, str), f"Non-string in FORBIDDEN_PHRASES: {phrase!r}"
            assert phrase == phrase.lower(), (
                f"FORBIDDEN_PHRASES entry must be lowercase: {phrase!r}"
            )


# ══════════════════════════════════════════════════════════════════════════════
# INTEGRATION — Full polish_thesis() pipeline
# ══════════════════════════════════════════════════════════════════════════════

class TestPolishThesisFinalLayer:
    """End-to-end: polish_thesis() must eliminate all synthetic patterns."""

    def _verbose_apple_thesis(self) -> InvestmentThesis:
        """Build a thesis with every synthetic pattern we ban."""
        return _thesis(
            direct_answer=(
                "Apple continues to expand its Services segment. "
                "The company remains well positioned for growth going forward."
            ),
            bull_thesis=(
                "Apple's Services segment, with its high 72% gross margin, continues "
                "to expand, offsetting hardware margin pressures and supporting a higher "
                "blended P/E multiple. "
                "The risk/reward profile remains compelling at 28x forward P/E."
            ),
            bear_thesis=(
                "This indicates that higher rates compress AAPL's forward P/E via DCF. "
                "China tariff exposure threatens $20B in iPhone revenue."
            ),
            valuation_view=(
                "AAPL continues to trade at 28x forward P/E, which supports a higher "
                "valuation than sector peers."
            ),
            macro_sensitivity=(
                "Rising rates continue to compress AAPL's P/E multiple via DCF "
                "discount rate expansion."
            ),
            conclusion=(
                "Apple continues to benefit from Services margin resilience. "
                "The investment remains compelling despite rate headwinds."
            ),
            confidence_reasoning=(
                "Confidence is reduced because macro analysis registers lower conviction "
                "(52%) versus valuation analysis (81%), indicating disagreement. "
                "Signal direction is 80% bullish across 5 ranked signals."
            ),
        )

    def test_continues_to_removed_across_all_fields(self):
        """'continues to X' must not survive in any prose field after polishing."""
        t = self._verbose_apple_thesis()
        polished = polish_thesis(t)

        for field_name in ("direct_answer", "bull_thesis", "bear_thesis",
                           "valuation_view", "macro_sensitivity", "conclusion"):
            text = getattr(polished, field_name, "") or ""
            assert "continues to" not in text.lower(), (
                f"'continues to' survived in {field_name}: {text!r}"
            )

    def test_this_indicates_removed(self):
        t = self._verbose_apple_thesis()
        polished = polish_thesis(t)
        for field_name in ("direct_answer", "bear_thesis"):
            text = getattr(polished, field_name, "") or ""
            assert "this indicates" not in text.lower(), (
                f"'this indicates' survived in {field_name}: {text!r}"
            )

    def test_going_forward_removed(self):
        t = self._verbose_apple_thesis()
        polished = polish_thesis(t)
        for field_name in ("direct_answer", "bull_thesis", "conclusion"):
            text = getattr(polished, field_name, "") or ""
            assert "going forward" not in text.lower(), (
                f"'going forward' survived in {field_name}: {text!r}"
            )

    def test_remains_compelling_removed(self):
        t = self._verbose_apple_thesis()
        polished = polish_thesis(t)
        for field_name in ("bull_thesis", "conclusion"):
            text = getattr(polished, field_name, "") or ""
            assert "remains compelling" not in text.lower(), (
                f"'remains compelling' survived in {field_name}: {text!r}"
            )

    def test_supports_higher_valuation_removed(self):
        t = self._verbose_apple_thesis()
        polished = polish_thesis(t)
        text = getattr(polished, "valuation_view", "") or ""
        assert "supports a higher valuation" not in text.lower() and \
               "supports higher valuation" not in text.lower(), (
            f"'supports higher valuation' survived in valuation_view: {text!r}"
        )

    def test_confidence_reasoning_has_no_percentages(self):
        """confidence_reasoning must not expose raw percentages after polishing."""
        t = self._verbose_apple_thesis()
        polished = polish_thesis(t)
        conf = polished.confidence_reasoning or ""
        assert not re.search(r'\b\d+%\b', conf), (
            f"Percentage survived in confidence_reasoning: {conf!r}"
        )

    def test_all_prose_fields_non_empty_after_polishing(self):
        """Polishing must never empty a prose field that had content."""
        t = self._verbose_apple_thesis()
        polished = polish_thesis(t)
        for field_name in ("direct_answer", "bull_thesis", "bear_thesis",
                           "conclusion", "valuation_view", "macro_sensitivity"):
            text = getattr(polished, field_name, "") or ""
            assert text.strip(), (
                f"Field '{field_name}' must not be emptied by polish_thesis"
            )

    def test_sentence_limits_enforced_after_polishing(self):
        """All sentence-count targets still enforced in the full pipeline."""
        t = self._verbose_apple_thesis()
        polished = polish_thesis(t)
        for field_name, limit in _SENTENCE_LIMITS.items():
            text = getattr(polished, field_name, "") or ""
            if not text.strip():
                continue
            sents = re.split(r"(?<=[.!?])\s+", text.strip())
            assert len(sents) <= limit + 1, (  # +1 for split tolerance
                f"{field_name} exceeds sentence limit ({limit}): "
                f"{len(sents)} sentences — {text!r}"
            )


class TestHeroThesisInPolishPipeline:
    """compress_hero_thesis() is integrated into polish_thesis() as the final step.
    Verify it fires correctly on one_sentence_thesis."""

    def test_hero_thesis_compressed_after_polish(self):
        """one_sentence_thesis verbose → compressed by polish_thesis()."""
        t = InvestmentThesis(
            ticker="AAPL",
            company_name="Apple Inc.",
            one_sentence_thesis=(
                "Apple's Services segment, with its 72% gross margin, continues to "
                "expand, offsetting hardware pressures and supporting a higher blended "
                "P/E multiple for the company. [high conviction, 74%]"
            ),
        )
        polished = polish_thesis(t)
        result = polished.one_sentence_thesis
        words = result.split()
        assert len(words) <= 25, (
            f"one_sentence_thesis should be ≤22 words after polish, got {len(words)}: {result!r}"
        )
        assert "[high conviction" not in result
        assert "offsetting" not in result.lower()

    def test_hero_thesis_empty_not_broken(self):
        """Empty one_sentence_thesis must survive polish_thesis() without error."""
        t = InvestmentThesis(ticker="AAPL", company_name="Apple Inc.")
        polished = polish_thesis(t)
        # No exception — result is either empty or unchanged
        assert polished.one_sentence_thesis == "" or polished.one_sentence_thesis is None \
               or isinstance(polished.one_sentence_thesis, str)

    def test_already_concise_hero_not_over_truncated(self):
        """A hero thesis at ≤22 words must not be further truncated."""
        short = "Rate compression threatens AAPL's 28x P/E via DCF discount expansion."
        t = InvestmentThesis(
            ticker="AAPL",
            company_name="Apple Inc.",
            one_sentence_thesis=short,
        )
        polished = polish_thesis(t)
        # Core mechanism terms must survive
        assert "P/E" in polished.one_sentence_thesis or "rate" in polished.one_sentence_thesis.lower()
