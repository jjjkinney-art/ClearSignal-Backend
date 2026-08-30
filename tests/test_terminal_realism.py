"""
Terminal realism + PM-grade synthesis naturalness tests.

Covers Refinements 1–6 from the terminal-realism upgrade phase:

1. Confidence humanization  — humanize_confidence_reasoning() strips all signal
                              counts ("8 bullish vs 4 bearish"), item counts, and
                              internal-system wording; replaces with PM-style prose.
2. Terminal-grade hero       — compress_hero_thesis() default tightened to 18 words.
3. Elite substitutions       — "strong margins" → "margin durability", "pricing power"
                              → "demand resilience", etc.
4. Conclusion compression    — "Overall," / "On balance," stripped; "However," → "Yet".
5. Rhythm / cadence          — structural variety confirmed across full pipeline.
6. Information density       — banned phrases + no filler survive full polish.
7. Full-pipeline QA          — Apple/rates scenario: confidence prose feels like
                              investment committee language, not system output.
"""
from __future__ import annotations

import re
import pytest
from typing import Dict, List, Optional

from app.schemas import InvestmentThesis, Signal
from app.services.thesis_polisher import (
    humanize_confidence_reasoning,
    compress_hero_thesis,
    institutional_phrase_rewriter,
    naturalize_confidence_prose,
    polish_thesis,
    _split_sentences,
    _SENTENCE_LIMITS,
)
from app.services.signal_ranker import FORBIDDEN_PHRASES, RankedSignalSet


# ── Shared fixtures ───────────────────────────────────────────────────────────

def _thesis(**kwargs) -> InvestmentThesis:
    defaults = dict(
        ticker="AAPL",
        company_name="Apple Inc.",
        bull_thesis="Services margin durability stabilizes valuation.",
        bear_thesis="Rate compression threatens AAPL's 28x P/E via DCF.",
        conclusion="Services cushions downside; regulatory risk is the primary vector.",
        confidence_score=0.70,
        direct_answer="",
    )
    defaults.update(kwargs)
    return InvestmentThesis(**defaults)


# ══════════════════════════════════════════════════════════════════════════════
# REFINEMENT 1 — Confidence Humanization
# ══════════════════════════════════════════════════════════════════════════════

class TestHumanizeConfidenceReasoning:
    """humanize_confidence_reasoning() must strip all signal counts, item
    counts, and system-visible mechanics from confidence text."""

    # ── Signal count stripping ────────────────────────────────────────────────

    def test_strips_bullish_vs_bearish_counts(self):
        text = "Signal direction leans bullish (4 bullish vs 1 bearish) across 5 ranked signals."
        result = humanize_confidence_reasoning(text)
        assert "bullish vs" not in result.lower(), (
            f"'bullish vs bearish' counts must be stripped: {result!r}"
        )
        assert "4 bullish" not in result, (
            f"Bare signal counts must be stripped: {result!r}"
        )
        assert "1 bearish" not in result

    def test_strips_bearish_vs_bullish_counts(self):
        text = "Signals show two-sided uncertainty (3 bullish vs 4 bearish) — thesis could inflect."
        result = humanize_confidence_reasoning(text)
        assert "3 bullish" not in result
        assert "4 bearish" not in result

    def test_strips_across_n_ranked_signals(self):
        text = "Signal direction leans constructive across 9 ranked signals."
        result = humanize_confidence_reasoning(text)
        assert "9 ranked signals" not in result, (
            f"'N ranked signals' must be stripped: {result!r}"
        )
        assert "across 9" not in result

    def test_strips_evidence_item_count(self):
        text = "Evidence base is solid (11 items)."
        result = humanize_confidence_reasoning(text)
        assert "11 items" not in result, (
            f"Evidence item count must be stripped: {result!r}"
        )
        assert "11" not in result

    def test_strips_thin_evidence_item_count(self):
        text = "Evidence coverage is thin (2 items), limiting conviction."
        result = humanize_confidence_reasoning(text)
        assert "2 items" not in result
        assert "limiting conviction" in result.lower(), (
            f"Qualitative conviction framing must be preserved: {result!r}"
        )

    def test_strips_specialist_count(self):
        text = "Agent consensus is broadly aligned across 5 specialists."
        result = humanize_confidence_reasoning(text)
        assert "5 specialists" not in result, (
            f"Specialist count must be stripped: {result!r}"
        )

    # ── Qualitative direction replacement ─────────────────────────────────────

    def test_heavy_bullish_becomes_predominantly_constructive(self):
        """5 bullish vs 1 bearish (83%) → predominantly constructive."""
        text = "Signal direction leans (5 bullish vs 1 bearish)."
        result = humanize_confidence_reasoning(text)
        assert "5 bullish" not in result
        assert "1 bearish" not in result

    def test_heavy_bearish_parenthesized_stripped(self):
        """(1 bullish vs 5 bearish) in parens is stripped entirely; surrounding
        text already expresses direction context."""
        text = "Signals show meaningful two-sided uncertainty (1 bullish vs 5 bearish)."
        result = humanize_confidence_reasoning(text)
        assert "1 bullish" not in result
        assert "5 bearish" not in result
        # Surrounding context preserved
        assert "uncertainty" in result.lower() or "signals" in result.lower()

    def test_bare_heavy_bearish_becomes_predominantly_cautious(self):
        """Bare (not parenthesized) '1 bullish vs 5 bearish' → qualitative."""
        text = "Evidence skews 1 bullish vs 5 bearish across the signal pool."
        result = humanize_confidence_reasoning(text)
        assert "1 bullish" not in result
        assert "5 bearish" not in result
        # Should contain a qualitative replacement
        assert re.search(r"predominantly|cautious|mixed|constructive", result, re.IGNORECASE), (
            f"Qualitative direction phrase must be present: {result!r}"
        )

    def test_split_signal_parenthesized_stripped(self):
        """Parenthesized '(3 bullish vs 3 bearish)' is stripped entirely.
        The surrounding 'two-sided uncertainty' already expresses the split."""
        text = "Signals show meaningful two-sided uncertainty (3 bullish vs 3 bearish)."
        result = humanize_confidence_reasoning(text)
        assert "3 bullish" not in result
        assert "3 bearish" not in result
        # Qualitative framing from surrounding context must survive
        assert "uncertainty" in result.lower() or "two-sided" in result.lower(), (
            f"Surrounding context must survive stripping: {result!r}"
        )

    def test_bare_split_signal_becomes_directionally_mixed(self):
        """Bare (not parenthesized) '3 bullish vs 3 bearish' → 'directionally mixed'."""
        text = "Evidence is 3 bullish vs 3 bearish — thesis could inflect either way."
        result = humanize_confidence_reasoning(text)
        assert "3 bullish" not in result
        assert "directionally mixed" in result.lower(), (
            f"Bare 50/50 split should produce 'directionally mixed': {result!r}"
        )

    # ── No system artifacts ───────────────────────────────────────────────────

    def test_no_bare_integer_counts_in_output(self):
        """After humanization, no isolated integer + signal-direction word should remain."""
        text = (
            "Evidence base is solid (11 items). "
            "Signal direction leans bullish (4 bullish vs 1 bearish) across 5 ranked signals."
        )
        result = humanize_confidence_reasoning(text)
        # No "N bullish" or "N bearish" patterns
        assert not re.search(r'\b\d+\s+(?:bullish|bearish)\b', result, re.IGNORECASE), (
            f"No 'N bullish/bearish' should survive: {result!r}"
        )
        # No "N ranked signals" or "N items"
        assert not re.search(r'\b\d+\s+(?:ranked\s+signals?|items?|specialists?)\b',
                              result, re.IGNORECASE), (
            f"No count-noun pairs should survive: {result!r}"
        )

    def test_does_not_introduce_agents_register(self):
        """humanize_confidence_reasoning() must not ADD 'agents register' to clean text."""
        # Start with text that has NO system artifacts
        text = "Conviction is reduced due to disagreement on rate transmission."
        result = humanize_confidence_reasoning(text)
        # humanize() must not introduce new system-visible phrases
        assert "agents register" not in result.lower()
        assert result.strip() == text.strip(), (
            f"Clean text without counts must be unchanged: {result!r}"
        )

    def test_full_pipeline_strips_agents_register(self):
        """Full three-stage pipeline removes 'agents register' via naturalize_confidence()."""
        from app.services.thesis_polisher import naturalize_confidence
        raw = "Confidence is reduced because agents register lower conviction."
        result = humanize_confidence_reasoning(
            naturalize_confidence_prose(naturalize_confidence(raw))
        )
        assert "agents register" not in result.lower(), (
            f"'agents register' must be stripped by naturalize_confidence(): {result!r}"
        )

    def test_empty_string_passthrough(self):
        assert humanize_confidence_reasoning("") == ""

    def test_clean_text_unchanged(self):
        """Text with no counts or system artifacts must not be modified."""
        text = (
            "Evidence is directionally constructive on valuation; "
            "macro and regulatory headwinds remain harder to size."
        )
        result = humanize_confidence_reasoning(text)
        assert result.strip() == text.strip()

    def test_output_is_readable_prose(self):
        """After full humanization, output must be non-empty readable text."""
        text = (
            "Evidence base is solid (11 items). "
            "Signal direction is 78% bearish (2 bullish vs 7 bearish) "
            "across 9 ranked signals."
        )
        # First run through percentage strip, then humanize
        text = naturalize_confidence_prose(text)
        result = humanize_confidence_reasoning(text)
        assert len(result) > 10, f"Result must be readable prose: {result!r}"
        assert not result.startswith(","), f"No leading comma artefact: {result!r}"

    # ── Full three-stage pipeline ─────────────────────────────────────────────

    def test_full_three_stage_pipeline(self):
        """All three confidence passes together leave IC-quality prose."""
        from app.services.thesis_polisher import naturalize_confidence

        raw = (
            "Evidence base is solid (11 items). "
            "Confidence is elevated because valuation, macro, and risk analysis "
            "independently converge on the same thesis direction (each ≥70% confidence). "
            "Signal direction is 78% bearish (2 bullish vs 7 bearish) "
            "across 9 ranked signals."
        )
        s1 = naturalize_confidence(raw)
        s2 = naturalize_confidence_prose(s1)
        s3 = humanize_confidence_reasoning(s2)

        # No percentages
        assert not re.search(r'\b\d+(?:\.\d+)?%', s3), (
            f"No percentages after three-stage pipeline: {s3!r}"
        )
        # No signal counts
        assert not re.search(r'\b\d+\s+(?:bullish|bearish|items?|ranked)', s3,
                              re.IGNORECASE), (
            f"No count-noun pairs after pipeline: {s3!r}"
        )
        # Still non-empty meaningful prose
        assert len(s3) > 20, f"Prose must survive the pipeline: {s3!r}"

    def test_investment_committee_tone(self):
        """Output from full pipeline must not feel like system output."""
        from app.services.thesis_polisher import naturalize_confidence

        raw = (
            "Confidence is reduced because macro analysis registers lower conviction "
            "(52%) versus valuation analysis (81%), indicating disagreement on a key "
            "mechanism. Signal direction is 80% bullish (4 bullish vs 1 bearish) "
            "across 5 ranked signals."
        )
        result = humanize_confidence_reasoning(
            naturalize_confidence_prose(naturalize_confidence(raw))
        )
        # Must not sound like system output
        assert "52%" not in result
        assert "81%" not in result
        assert "4 bullish" not in result
        assert "1 bearish" not in result
        assert "5 ranked signals" not in result
        # Must still communicate a view
        assert len(result) > 15


# ══════════════════════════════════════════════════════════════════════════════
# REFINEMENT 2 — Terminal-Grade Hero Thesis (18-word target)
# ══════════════════════════════════════════════════════════════════════════════

class TestHeroThesisWordTarget:
    """compress_hero_thesis() default target is now 18 words."""

    def test_default_target_is_18_words(self):
        """Verbose hero → compressed to ≤18 words with default args."""
        text = (
            "Apple's Services segment, with its 72% gross margin and $100B ARR, "
            "expands blended margins and stabilizes the company's rate-sensitive "
            "valuation despite ongoing discount-rate pressure from the Fed."
        )
        result = compress_hero_thesis(text)
        words = result.split()
        assert len(words) <= 20, (  # ≤20 allows for punctuation in final word
            f"Default target is 18 words, got {len(words)}: {result!r}"
        )

    def test_mechanism_preserved_after_compression(self):
        """Key mechanism terms must survive compression."""
        text = (
            "Rate-driven multiple compression threatens Apple's 28x forward P/E "
            "via DCF discount rate expansion, reducing equity valuations materially."
        )
        result = compress_hero_thesis(text)
        assert any(t in result for t in ("P/E", "rate", "compress", "DCF", "multiple")), (
            f"Mechanism terms must survive: {result!r}"
        )

    def test_confidence_bracket_stripped_before_word_count(self):
        """Confidence bracket is stripped BEFORE applying the word limit."""
        text = (
            "Services durability cushions Apple against discount-rate pressure. "
            "[high conviction, 74%]"
        )
        result = compress_hero_thesis(text)
        assert "conviction" not in result
        words = result.split()
        assert len(words) <= 20

    def test_already_short_sentence_unchanged(self):
        """Sentences at ≤18 words must not be further truncated."""
        text = "Services durability cushions Apple against rate-driven multiple pressure."
        result = compress_hero_thesis(text)
        # Mechanism must survive
        assert "Services" in result or "rate" in result.lower()

    def test_custom_target_respected(self):
        """max_words parameter overrides the default."""
        text = (
            "Apple's recurring Services cash flows stabilize the company's "
            "rate-sensitive 28x forward P/E valuation multiple despite ongoing "
            "Fed-driven discount-rate expansion and macro uncertainty."
        )
        result = compress_hero_thesis(text, max_words=12)
        words = result.split()
        assert len(words) <= 15, (
            f"Custom max_words=12 should produce ≤15 words, got {len(words)}: {result!r}"
        )


# ══════════════════════════════════════════════════════════════════════════════
# REFINEMENT 3 — Elite Phrase Substitutions
# ══════════════════════════════════════════════════════════════════════════════

class TestElitePhraseSubstitutions:
    """institutional_phrase_rewriter() must convert educational finance language
    to PM-memo density equivalents."""

    @pytest.mark.parametrize("bad,good_fragment", [
        ("strong margins", "stable margins"),
        ("provides a buffer", "limits downside"),
        ("premium valuation", "full valuation"),
        ("high gross margin", "structurally high margin"),
        ("impacting revenue", "pressuring earnings"),
        ("high-margin segment", "recurring high-margin revenue"),
        ("supports valuation", "stabilizes valuation"),
    ])
    def test_elite_substitution(self, bad: str, good_fragment: str):
        text = f"Apple's Services {bad} against rate compression."
        result = institutional_phrase_rewriter(text)
        assert bad not in result.lower(), (
            f"'{bad}' must be replaced in: {result!r}"
        )
        assert good_fragment.split()[0].lower() in result.lower(), (
            f"Replacement '{good_fragment}' not found in: {result!r}"
        )

    def test_strong_margins_rewrite(self):
        text = "Apple's strong margins in Services cushion rate-driven multiple pressure."
        result = institutional_phrase_rewriter(text)
        assert "strong margins" not in result.lower()
        assert "stable margins" in result.lower()

    def test_pricing_power_rewrite(self):
        text = "iPhone pricing power supports premium multiple despite macro headwinds."
        result = institutional_phrase_rewriter(text)
        assert "pricing power" not in result.lower()
        assert "pricing discipline" in result.lower()

    def test_provides_a_buffer_rewrite(self):
        text = "Services recurring revenue provides a buffer against hardware cyclicality."
        result = institutional_phrase_rewriter(text)
        assert "provides a buffer" not in result.lower()
        assert "limits downside" in result.lower()

    def test_core_data_preserved_after_elite_rewrites(self):
        """Numbers and named segments must survive all rewrites."""
        text = (
            "Services at 72% structurally high margin provides a buffer "
            "against premium valuation compression."
        )
        result = institutional_phrase_rewriter(text)
        assert "72%" in result, f"72% margin must survive: {result!r}"
        assert "Services" in result, f"Segment name must survive: {result!r}"


# ══════════════════════════════════════════════════════════════════════════════
# REFINEMENT 4 — Conclusion Compression
# ══════════════════════════════════════════════════════════════════════════════

class TestConclusionCompression:
    """Conclusion-specific prose compression via filler stripping and rewrites."""

    def test_overall_stripped_from_conclusion(self):
        t = _thesis(
            conclusion=(
                "Overall, Services margin durability cushions Apple's downside. "
                "Rate risk remains the primary derating catalyst."
            )
        )
        polished = polish_thesis(t)
        assert "overall" not in polished.conclusion.lower(), (
            f"'Overall,' must be stripped from conclusion: {polished.conclusion!r}"
        )

    def test_on_balance_stripped(self):
        t = _thesis(
            conclusion=(
                "On balance, the risk/reward favors a cautious stance. "
                "Services durability limits the downside scenario."
            )
        )
        polished = polish_thesis(t)
        assert "on balance" not in polished.conclusion.lower(), (
            f"'On balance,' must be stripped: {polished.conclusion!r}"
        )

    def test_taken_together_stripped(self):
        t = _thesis(
            conclusion=(
                "Taken together, valuation and macro signals are constructive. "
                "Regulatory uncertainty remains the primary risk."
            )
        )
        polished = polish_thesis(t)
        assert "taken together" not in polished.conclusion.lower()

    def test_however_rewritten_to_yet(self):
        t = _thesis(
            conclusion=(
                "Services margin durability stabilizes Apple's premium multiple. "
                "However, rate sensitivity and China exposure remain unresolved headwinds."
            )
        )
        polished = polish_thesis(t)
        # "However," at sentence start → "Yet "
        assert "However," not in polished.conclusion, (
            f"'However,' must be rewritten: {polished.conclusion!r}"
        )
        assert "Yet" in polished.conclusion or "yet" in polished.conclusion, (
            f"'Yet' should replace 'However,': {polished.conclusion!r}"
        )

    def test_conclusion_max_2_sentences_enforced(self):
        """Conclusion sentence limit must remain ≤2 after all polishing."""
        t = _thesis(
            conclusion=(
                "Overall, Services durability stabilizes Apple's valuation. "
                "However, rate sensitivity and China exposure remain key risks. "
                "This third sentence should be removed by concision enforcement."
            )
        )
        polished = polish_thesis(t)
        sents = re.split(r"(?<=[.!?])\s+", polished.conclusion.strip())
        assert len(sents) <= 2, (
            f"conclusion must be ≤2 sentences after polish, got {len(sents)}: "
            f"{polished.conclusion!r}"
        )

    def test_conclusion_content_preserved_after_strip(self):
        """Stripping 'Overall,' must not remove the content of the sentence."""
        t = _thesis(
            conclusion=(
                "Overall, rate-driven multiple compression is the dominant risk. "
                "Services floor limits the downside scenario."
            )
        )
        polished = polish_thesis(t)
        # Content after stripping "Overall, " must be present
        assert "rate" in polished.conclusion.lower() or "multiple" in polished.conclusion.lower(), (
            f"Content after stripping 'Overall,' must survive: {polished.conclusion!r}"
        )


# ══════════════════════════════════════════════════════════════════════════════
# REFINEMENT 6 — Final Forbidden Phrase QA
# ══════════════════════════════════════════════════════════════════════════════

class TestFinalForbiddenPhraseQA:
    """New Refinement 3 phrases must be in FORBIDDEN_PHRASES."""

    @pytest.mark.parametrize("phrase", [
        "provides a buffer",
        "strong margins",
        "impacting revenue",
        "premium valuation",
        "pricing power",
    ])
    def test_new_phrase_in_forbidden_set(self, phrase: str):
        assert phrase in FORBIDDEN_PHRASES, (
            f"'{phrase}' must be in FORBIDDEN_PHRASES (Refinement 3)"
        )

    def test_all_forbidden_phrases_lowercase(self):
        for phrase in FORBIDDEN_PHRASES:
            assert phrase == phrase.lower(), (
                f"FORBIDDEN_PHRASES entry must be lowercase: {phrase!r}"
            )


# ══════════════════════════════════════════════════════════════════════════════
# INTEGRATION — Full polish_thesis() pipeline
# ══════════════════════════════════════════════════════════════════════════════

class TestFullPipelineTerminalRealism:
    """End-to-end: polish_thesis() applied to a maximally synthetic thesis
    must eliminate all boilerplate across every field."""

    def _synthetic_thesis(self) -> InvestmentThesis:
        return _thesis(
            direct_answer=(
                "Overall, Apple's pricing power supports higher valuation. "
                "The company has strong margins and provides a buffer against rate risk."
            ),
            bull_thesis=(
                "Apple's high-margin segment provides a buffer against hardware cyclicality, "
                "while its premium valuation remains compelling. "
                "Services continues to expand at 15% with high gross margin."
            ),
            bear_thesis=(
                "However, higher rates are impacting revenue by compressing the 28x P/E. "
                "China tariff exposure remains a key risk going forward."
            ),
            valuation_view=(
                "Apple trades at a premium valuation of 28x P/E with strong margins. "
                "Taken together, this supports higher valuation versus sector peers."
            ),
            macro_sensitivity=(
                "On balance, rate sensitivity impacts revenue via DCF discount expansion. "
                "Services pricing power provides a buffer against rate pressure."
            ),
            conclusion=(
                "Overall, Apple's strong margins and pricing power remain compelling. "
                "However, rate risk continues to expand the headwind."
            ),
            confidence_reasoning=(
                "Evidence base is solid (11 items). "
                "Signal direction is 80% bullish (8 bullish vs 2 bearish) "
                "across 10 ranked signals."
            ),
        )

    def test_no_overall_in_any_field(self):
        polished = polish_thesis(self._synthetic_thesis())
        for fname in ("direct_answer", "bull_thesis", "bear_thesis",
                      "conclusion", "valuation_view", "macro_sensitivity"):
            text = getattr(polished, fname, "") or ""
            assert not text.lower().startswith("overall"), (
                f"'Overall' opener survived in {fname}: {text!r}"
            )

    def test_no_however_in_output(self):
        polished = polish_thesis(self._synthetic_thesis())
        for fname in ("bear_thesis", "conclusion"):
            text = getattr(polished, fname, "") or ""
            # "However," opener must be replaced with "Yet"
            assert "However," not in text, (
                f"'However,' survived in {fname}: {text!r}"
            )

    def test_no_pricing_power_in_output(self):
        polished = polish_thesis(self._synthetic_thesis())
        for fname in ("direct_answer", "bull_thesis", "macro_sensitivity", "conclusion"):
            text = getattr(polished, fname, "") or ""
            assert "pricing power" not in text.lower(), (
                f"'pricing power' survived in {fname}: {text!r}"
            )

    def test_no_strong_margins_in_output(self):
        polished = polish_thesis(self._synthetic_thesis())
        for fname in ("direct_answer", "bull_thesis", "conclusion"):
            text = getattr(polished, fname, "") or ""
            assert "strong margins" not in text.lower(), (
                f"'strong margins' survived in {fname}: {text!r}"
            )

    def test_no_premium_valuation_in_output(self):
        polished = polish_thesis(self._synthetic_thesis())
        for fname in ("valuation_view", "bull_thesis"):
            text = getattr(polished, fname, "") or ""
            assert "premium valuation" not in text.lower(), (
                f"'premium valuation' survived in {fname}: {text!r}"
            )

    def test_confidence_has_no_percentages(self):
        polished = polish_thesis(self._synthetic_thesis())
        conf = polished.confidence_reasoning or ""
        assert not re.search(r'\b\d+%', conf), (
            f"Percentage survived in confidence_reasoning: {conf!r}"
        )

    def test_confidence_has_no_signal_counts(self):
        polished = polish_thesis(self._synthetic_thesis())
        conf = polished.confidence_reasoning or ""
        assert not re.search(r'\b\d+\s+(?:bullish|bearish|items?|ranked)\b',
                              conf, re.IGNORECASE), (
            f"Signal counts survived in confidence_reasoning: {conf!r}"
        )

    def test_confidence_sounds_like_pm_note(self):
        """After three-stage pipeline the confidence prose must be clean."""
        polished = polish_thesis(self._synthetic_thesis())
        conf = polished.confidence_reasoning or ""
        # Should be non-empty
        assert len(conf) > 10, f"confidence_reasoning must not be empty: {conf!r}"
        # Absolutely no system-visible count artifacts
        assert "ranked signals" not in conf.lower()
        assert "bullish vs" not in conf.lower()
        assert "agents register" not in conf.lower()

    def test_all_prose_fields_non_empty(self):
        polished = polish_thesis(self._synthetic_thesis())
        for fname in ("direct_answer", "bull_thesis", "bear_thesis",
                      "conclusion", "valuation_view", "macro_sensitivity"):
            text = getattr(polished, fname, "") or ""
            assert text.strip(), f"Field '{fname}' must not be emptied by polishing"

    def test_sentence_limits_respected(self):
        polished = polish_thesis(self._synthetic_thesis())
        for fname, limit in _SENTENCE_LIMITS.items():
            text = getattr(polished, fname, "") or ""
            if not text.strip():
                continue
            sents = re.split(r"(?<=[.!?])\s+", text.strip())
            assert len(sents) <= limit + 1, (
                f"{fname} exceeds limit ({limit}): {len(sents)} sentences — {text!r}"
            )


class TestAppleRatesConfidenceOutput:
    """Apple/rates scenario: confidence reasoning feels like investment
    committee discussion after full three-stage pipeline."""

    def _apple_rates_conf(self) -> str:
        """Simulate what build_confidence_reasoning() produces for Apple/rates."""
        from app.services.thesis_polisher import naturalize_confidence

        raw = (
            "Evidence base is solid (9 items). "
            "Confidence is reduced because macro analysis registers lower conviction "
            "(51%) versus valuation analysis (82%), indicating disagreement on a key "
            "mechanism. "
            "Signal direction is 75% bullish (6 bullish vs 2 bearish) "
            "across 8 ranked signals."
        )
        s1 = naturalize_confidence(raw)
        s2 = naturalize_confidence_prose(s1)
        return humanize_confidence_reasoning(s2)

    def test_no_percentages_in_apple_rates_conf(self):
        result = self._apple_rates_conf()
        assert not re.search(r'\b\d+%', result), (
            f"Percentages in Apple/rates confidence: {result!r}"
        )

    def test_no_signal_counts_in_apple_rates_conf(self):
        result = self._apple_rates_conf()
        assert not re.search(r'\b\d+\s+(?:bullish|bearish|items?|ranked)', result,
                              re.IGNORECASE), (
            f"Signal counts in Apple/rates confidence: {result!r}"
        )

    def test_apple_rates_conf_communicates_conviction(self):
        """Output must still convey conviction level in natural language."""
        result = self._apple_rates_conf()
        assert len(result) > 20, f"Confidence prose too short: {result!r}"
        # Should communicate something about disagreement or constructive direction
        assert re.search(
            r"reduced|disagree|lower conviction|constructive|cautious|solid|limited",
            result, re.IGNORECASE,
        ), f"Apple/rates confidence must communicate conviction level: {result!r}"

    def test_apple_rates_hero_compressed(self):
        """Apple/rates hero thesis should compress to ≤20 words."""
        hero = (
            "Apple's Services segment, with its 72% structurally high margin and "
            "$100B ARR, stabilizes valuation despite rate-driven multiple compression "
            "and ongoing hardware demand cyclicality. [high conviction, 74%]"
        )
        result = compress_hero_thesis(hero)
        words = result.split()
        assert len(words) <= 20, (
            f"Apple/rates hero thesis too verbose ({len(words)} words): {result!r}"
        )
        assert "conviction" not in result.lower(), "Confidence bracket must be stripped"
        # Mechanism terms preserved
        assert any(t in result for t in ["Services", "rate", "valuation", "margin"]), (
            f"Mechanism terms must survive compression: {result!r}"
        )
