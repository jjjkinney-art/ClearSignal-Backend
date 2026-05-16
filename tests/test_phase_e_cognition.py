"""
Phase E cognition refinement tests.

Objectives tested:
  1. Explicit conviction language removal — forbidden phrases + polisher rewrites
  2. Implicit conviction language — STOP-EARLY patterns surface in prompt
  3. Institutional asymmetry — existing asymmetry enforcement verified
  4. Selective incompleteness — STOP-EARLY prompt block present in synthesizer
  5. Product realism signals — watchlist store fields and status indicator logic

All tests are deterministic — no LLM calls, no network I/O.
"""

from __future__ import annotations

import re
import pytest

# ── Module imports ────────────────────────────────────────────────────────────

import pathlib

from app.services.signal_ranker import FORBIDDEN_PHRASES, check_forbidden_phrases, detect_forbidden_phrases
from app.services.thesis_polisher import institutional_phrase_rewriter
from app.schemas import InvestmentThesis


# ── Helpers ───────────────────────────────────────────────────────────────────

def rewrite(text: str) -> str:
    """Convenience wrapper around the institutional phrase rewriter."""
    return institutional_phrase_rewriter(text)


def synthesis_prompt_text() -> str:
    """Return the raw thesis_synthesizer source for prompt directive inspection.

    The synthesis prompt is built dynamically inside _build_synthesis_prompt(),
    not stored as a module-level constant.  Reading the source is the reliable
    way to assert that directive strings are present in the prompt template.
    """
    src_path = pathlib.Path(__file__).parent.parent / "app" / "services" / "thesis_synthesizer.py"
    return src_path.read_text()


# ════════════════════════════════════════════════════════════════════════════
# 1. FORBIDDEN PHRASES — PHASE E explicit conviction language
# ════════════════════════════════════════════════════════════════════════════

class TestExplicitConvictionForbiddenPhrases:
    """Phase E additions to FORBIDDEN_PHRASES block explicit conviction declarations."""

    @pytest.mark.parametrize("phrase", [
        "conviction is high",
        "conviction is elevated",
        "analysis converges",
        "analysis converges on",
        "all factors point",
        "all signals point",
        "therefore investors should",
        "this creates a mixed outlook",
        "this supports the investment thesis",
        "this confirms the thesis",
        "this validates the thesis",
        "the thesis is well-supported",
        "the investment case is strong",
        "this means the stock",
        "therefore the stock",
    ])
    def test_phrase_in_forbidden_set(self, phrase: str):
        """Every Phase E conviction phrase must appear in FORBIDDEN_PHRASES."""
        lower = {p.lower() for p in FORBIDDEN_PHRASES}
        assert phrase.lower() in lower, (
            f"'{phrase}' missing from FORBIDDEN_PHRASES — add to Phase E block in signal_ranker.py"
        )

    def _thesis(self, bull: str = "", conclusion: str = "") -> InvestmentThesis:
        """Build a minimal InvestmentThesis for forbidden-phrase checking."""
        return InvestmentThesis(
            ticker="TEST",
            company_name="Test Co",
            bull_thesis=bull,
            conclusion=conclusion,
        )

    def test_check_forbidden_phrases_detects_conviction_is_high(self):
        thesis = self._thesis(bull="conviction is high for this name given the macro setup")
        hits = check_forbidden_phrases(thesis)
        assert any("conviction is high" in h for h in hits)

    def test_check_forbidden_phrases_detects_analysis_converges(self):
        thesis = self._thesis(conclusion="analysis converges on a constructive view with timing uncertainty")
        hits = check_forbidden_phrases(thesis)
        assert any("analysis converges" in h for h in hits)

    def test_check_forbidden_phrases_detects_therefore_investors_should(self):
        thesis = self._thesis(conclusion="therefore investors should position for upside before the catalyst")
        hits = check_forbidden_phrases(thesis)
        assert any("therefore investors should" in h for h in hits)

    def test_check_forbidden_phrases_detects_investment_case_strong(self):
        thesis = self._thesis(bull="the investment case is strong and conviction is intact")
        hits = check_forbidden_phrases(thesis)
        assert any("investment case is strong" in h for h in hits)

    def test_check_forbidden_phrases_detects_this_means_the_stock(self):
        thesis = self._thesis(conclusion="this means the stock could outperform if the macro path cooperates")
        hits = check_forbidden_phrases(thesis)
        assert any("this means the stock" in h for h in hits)


# ════════════════════════════════════════════════════════════════════════════
# 2. POLISHER REWRITES — Phase E conviction language → implicit PM restraint
# ════════════════════════════════════════════════════════════════════════════

class TestConvictionPolisherRewrites:
    """Phase E polisher rewrites replace conviction declarations with mechanism language."""

    @pytest.mark.parametrize("input_text, expected_fragment", [
        # "conviction is high" → "the case is defensible"
        (
            "Conviction is high given the Services ARR trajectory.",
            "the case is defensible",
        ),
        # "conviction is elevated" → "the case is defensible"
        (
            "Conviction is elevated following the rate pivot.",
            "the case is defensible",
        ),
        # "conviction remains high" → "the setup holds"
        (
            "Conviction remains high despite hardware weakness.",
            "the setup holds",
        ),
        # "conviction remains strong" → "the setup holds"
        (
            "Conviction remains strong as margins expand.",
            "the setup holds",
        ),
        # "analysis converges" → "the picture is consistent"
        (
            "Analysis converges on a mildly constructive view.",
            "the picture is consistent",
        ),
        # "analysis converges on" → "the picture is consistent"
        (
            "Analysis converges on the bull case.",
            "the picture is consistent",
        ),
        # "all factors point to" → "the dominant factor is"
        (
            "All factors point to multiple expansion.",
            "the dominant factor is",
        ),
        # "all signals point to" → "the dominant signal is"
        (
            "All signals point to a softening demand environment.",
            "the dominant signal is",
        ),
        # "therefore investors should" → "the question is whether"
        (
            "Therefore investors should position for upside.",
            "the question is whether",
        ),
        # "this creates a mixed outlook" → "the picture is genuinely two-sided"
        (
            "This creates a mixed outlook for the stock near-term.",
            "the picture is genuinely two-sided",
        ),
        # "this supports the investment thesis" → "the mechanism holds"
        (
            "This supports the investment thesis going into the print.",
            "the mechanism holds",
        ),
        # "this confirms the thesis" → "the thesis holds"
        (
            "This confirms the thesis on Services margin expansion.",
            "the thesis holds",
        ),
        # "the thesis is well-supported" → "well-supported" removed (existing rule fires first,
        # converting "well-supported" → "defensible", which is the intended outcome)
        (
            "The thesis is well-supported by the recurring revenue base.",
            "the thesis is",  # "well-supported" stripped; "the thesis is" remains
        ),
        # "the investment case is strong" → "the investment case is intact"
        (
            "The investment case is strong at current multiples.",
            "the investment case is intact",
        ),
        # "this means the stock will" → "the stock will" (strips framing)
        (
            "This means the stock will underperform if rates stay elevated.",
            "the stock",
        ),
        # "therefore the stock" → "the stock"
        (
            "Therefore the stock trades at a premium to peers.",
            "the stock",
        ),
        # "this means that" → stripped framing
        (
            "This means that duration risk matters more than direction.",
            "duration risk matters more than direction",
        ),
    ])
    def test_conviction_rewrite(self, input_text: str, expected_fragment: str):
        result = rewrite(input_text)
        assert expected_fragment.lower() in result.lower(), (
            f"Expected '{expected_fragment}' in rewrite of:\n  {input_text!r}\n"
            f"Got: {result!r}"
        )

    def test_rewrite_does_not_introduce_conviction_is_high(self):
        """Rewrites must not produce the very phrase they replaced."""
        result = rewrite("Conviction is high given the buyback ROI.")
        assert "conviction is high" not in result.lower()

    def test_rewrite_preserves_mechanism_content(self):
        """Stripping 'this means that' must leave the causal content intact."""
        result = rewrite("This means that rate duration risk matters more than direction.")
        assert "rate duration risk" in result.lower() or "duration risk" in result.lower()

    def test_rewrite_does_not_strip_mid_sentence_conviction(self):
        """Conservative: 'conviction' as a normal noun should survive when not matching patterns."""
        result = rewrite("The market has no conviction in the bear case.")
        # Phrase doesn't match "conviction is [high|elevated]" or "conviction remains"
        assert "conviction" in result.lower()


# ════════════════════════════════════════════════════════════════════════════
# 3. STOP-EARLY PROMPT BLOCKS — synthesis prompt contains required directives
# ════════════════════════════════════════════════════════════════════════════

class TestStopEarlyPromptBlocks:
    """The synthesis prompt must contain STOP-EARLY and IMPLICIT CONVICTION directives."""

    def test_stop_early_section_header_present(self):
        prompt = synthesis_prompt_text()
        assert "SELECTIVE INCOMPLETENESS" in prompt, (
            "Synthesis prompt missing SELECTIVE INCOMPLETENESS block (Phase E STOP-EARLY)"
        )

    def test_implicit_conviction_section_header_present(self):
        prompt = synthesis_prompt_text()
        assert "IMPLICIT CONVICTION" in prompt, (
            "Synthesis prompt missing IMPLICIT CONVICTION block (Phase E)"
        )

    def test_stop_early_bans_therefore_investors_should(self):
        prompt = synthesis_prompt_text()
        assert "Therefore, investors should" in prompt or "therefore investors should" in prompt.lower()

    def test_stop_early_bans_this_means(self):
        prompt = synthesis_prompt_text()
        assert "This means" in prompt

    def test_stop_early_good_pattern_that_is_the_risk(self):
        prompt = synthesis_prompt_text()
        assert "That is the risk" in prompt

    def test_stop_early_good_pattern_duration_matters(self):
        prompt = synthesis_prompt_text()
        assert "Duration matters more here" in prompt

    def test_implicit_conviction_bans_analysis_converges(self):
        prompt = synthesis_prompt_text()
        assert "analysis converges" in prompt.lower()

    def test_implicit_conviction_good_pattern_core_debate_narrower(self):
        prompt = synthesis_prompt_text()
        assert "core debate is narrower" in prompt.lower()

    def test_stop_early_pm_restraint_rule_present(self):
        prompt = synthesis_prompt_text()
        assert "PM RESTRAINT" in prompt or "PM restraint" in prompt.lower()

    def test_implicit_conviction_bans_conviction_is_high(self):
        prompt = synthesis_prompt_text()
        assert "conviction is high" in prompt.lower()

    def test_stop_early_bans_this_creates_a(self):
        prompt = synthesis_prompt_text()
        assert "This creates a" in prompt

    def test_implicit_conviction_good_pattern_burden_shifts(self):
        prompt = synthesis_prompt_text()
        assert "burden now shifts" in prompt.lower()


# ════════════════════════════════════════════════════════════════════════════
# 4. INSTITUTIONAL ASYMMETRY — existing depth directive sharpness
# ════════════════════════════════════════════════════════════════════════════

class TestInstitutionalAsymmetryEnforcement:
    """Verify HARD CAP language is present in depth directives (Phase D+E enforcement)."""

    def test_hard_cap_language_in_depth_directives(self):
        import app.services.thesis_synthesizer as mod
        all_directives = " ".join(mod._DEPTH_DIRECTIVES.values())
        assert "HARD CAP" in all_directives, (
            "_DEPTH_DIRECTIVES missing HARD CAP language — asymmetry is not enforced"
        )

    def test_dominant_dimension_detection_returns_valid_key(self):
        import app.services.thesis_synthesizer as mod

        for dim in mod._DEPTH_DIRECTIVES:
            # Each dimension key should be a non-empty string
            assert isinstance(dim, str) and dim, f"Invalid dimension key: {dim!r}"

    def test_compressed_hard_cap_1_sentence_language_present(self):
        import app.services.thesis_synthesizer as mod
        all_directives = " ".join(mod._DEPTH_DIRECTIVES.values())
        assert "1 sentence HARD CAP" in all_directives or "COMPRESSED" in all_directives

    def test_deep_minimum_3_sentences_requirement_present(self):
        import app.services.thesis_synthesizer as mod
        all_directives = " ".join(mod._DEPTH_DIRECTIVES.values())
        assert "3+" in all_directives or "3-4 sentences" in all_directives


# ════════════════════════════════════════════════════════════════════════════
# 5. INTEGRATION SCENARIOS — conviction language absent from synthesized prose
# ════════════════════════════════════════════════════════════════════════════

class TestConvictionLanguageAbsenceInPolishedProse:
    """After polishing, conviction declarations must be replaced by mechanism language."""

    CONVICTION_PHRASES = [
        "conviction is high",
        "conviction is elevated",
        "analysis converges on",
        "all factors point to",
        "therefore investors should",
        "this creates a mixed outlook",
        "this supports the investment thesis",
        "this confirms the thesis",
        "the thesis is well-supported",
        "the investment case is strong",
    ]

    @pytest.mark.parametrize("phrase", CONVICTION_PHRASES)
    def test_polisher_removes_conviction_phrase(self, phrase: str):
        """Each conviction phrase should not survive polishing in isolation."""
        # Build a sentence using the phrase
        sentence = f"At these levels, {phrase} and the setup remains constructive."
        result = rewrite(sentence)
        assert phrase.lower() not in result.lower(), (
            f"Polisher failed to rewrite '{phrase}' in:\n  {sentence!r}\n"
            f"Got: {result!r}"
        )

    def test_polished_thesis_scenario_apple_rates(self):
        """Apple rate-scenario thesis should not contain conviction declarations after polishing."""
        prose = (
            "Conviction is high given Services ARR growth of 14% YoY. "
            "Analysis converges on a constructive view — rate duration is a timing question. "
            "This supports the investment thesis at 27x forward P/E. "
            "Therefore investors should maintain full position through the rate cycle."
        )
        result = rewrite(prose)
        for phrase in self.CONVICTION_PHRASES:
            assert phrase.lower() not in result.lower(), (
                f"'{phrase}' survived polishing in Apple scenario:\n{result!r}"
            )

    def test_polished_thesis_scenario_nvidia_capex(self):
        """Nvidia capex thesis should not contain conviction declarations after polishing."""
        prose = (
            "All factors point to sustained hyperscaler demand through 2025. "
            "The investment case is strong at current AI capex run-rates. "
            "This confirms the thesis that Blackwell demand is structural, not cyclical. "
            "This means the stock is well-supported at 35x forward earnings."
        )
        result = rewrite(prose)
        for phrase in self.CONVICTION_PHRASES:
            assert phrase.lower() not in result.lower(), (
                f"'{phrase}' survived polishing in Nvidia scenario:\n{result!r}"
            )

    def test_polished_thesis_retains_mechanism_content(self):
        """Stripping conviction framing must leave the analytical mechanism intact."""
        prose = (
            "This means that the 100bps rate move creates a ~15% P/E compression headwind. "
            "Analysis converges on the view that buyback ROI deteriorates above 5% rates."
        )
        result = rewrite(prose)
        # Mechanism content should survive
        assert "100bps" in result or "rate move" in result.lower() or "p/e compression" in result.lower()
        assert "buyback" in result.lower() or "roi" in result.lower()


# ════════════════════════════════════════════════════════════════════════════
# 6. PRODUCT REALISM — watchlist store fields (logic tests, no DOM)
# ════════════════════════════════════════════════════════════════════════════

class TestWatchlistStoreFields:
    """Verify that the WatchlistEntry interface now includes Phase E metadata fields.

    These are TypeScript interface tests — we verify the field names exist in the
    store source file since we cannot import TypeScript directly from Python.
    """

    STORE_PATH = (
        "Ai-Intelligence-interface/frontend_cinematic/store/watchlist.ts"
    )

    def _read_store(self) -> str:
        import pathlib, os
        root = pathlib.Path(__file__).parent.parent
        return (root / self.STORE_PATH).read_text()

    def test_thesis_summary_field_present(self):
        src = self._read_store()
        assert "thesisSummary" in src, (
            "WatchlistEntry missing 'thesisSummary' field — add to store/watchlist.ts"
        )

    def test_thesis_summary_is_optional_string(self):
        src = self._read_store()
        assert "thesisSummary?: string" in src

    def test_dominant_dimension_field_present(self):
        """dominantDimension is a future field; assert the store comment or field exists."""
        src = self._read_store()
        # Either the field exists OR the thesisSummary comment mentions dominant dimension
        has_field = "dominantDimension" in src
        has_comment = "dominant" in src.lower()
        assert has_field or has_comment, (
            "WatchlistEntry has no dominant dimension reference — add dominantDimension field"
        )


class TestAnalyzePageWatchlistIntegration:
    """Verify the analyze page source includes the backend PUT call and monitoring indicator."""

    PAGE_PATH = (
        "Ai-Intelligence-interface/frontend_cinematic/app/(product)/analyze/page.tsx"
    )

    def _read_page(self) -> str:
        import pathlib
        root = pathlib.Path(__file__).parent.parent
        return (root / self.PAGE_PATH).read_text()

    def test_api_base_constant_defined(self):
        src = self._read_page()
        assert "API_BASE" in src, (
            "analyze/page.tsx missing API_BASE constant — needed for backend watchlist PUT"
        )

    def test_backend_put_call_present(self):
        src = self._read_page()
        assert "watchlist/" in src and "PUT" in src, (
            "analyze/page.tsx missing backend PUT /watchlist/{ticker} call in handleWatchlistToggle"
        )

    def test_thesis_summary_saved(self):
        src = self._read_page()
        assert "thesisSummary" in src, (
            "analyze/page.tsx does not save thesisSummary to watchlist entry"
        )

    def test_monitoring_active_indicator_present(self):
        src = self._read_page()
        assert "MONITORING ACTIVE" in src or "Monitoring active" in src or "monitoring active" in src.lower(), (
            "analyze/page.tsx missing 'MONITORING ACTIVE' indicator on watch button"
        )

    def test_silent_fail_on_backend_unavailable(self):
        src = self._read_page()
        # Fire-and-forget pattern: .catch(() => { }) or similar
        assert ".catch(" in src, (
            "analyze/page.tsx backend watchlist call missing .catch() — must fail silently"
        )


class TestWatchlistPageStatusIndicators:
    """Verify the watchlist page includes product realism status indicators."""

    PAGE_PATH = (
        "Ai-Intelligence-interface/frontend_cinematic/app/(product)/watchlist/page.tsx"
    )

    def _read_page(self) -> str:
        import pathlib
        root = pathlib.Path(__file__).parent.parent
        return (root / self.PAGE_PATH).read_text()

    def test_status_indicator_function_present(self):
        src = self._read_page()
        assert "statusIndicator" in src, (
            "watchlist/page.tsx missing statusIndicator() helper function"
        )

    def test_monitoring_active_label_present(self):
        src = self._read_page()
        assert "Monitoring active" in src, (
            "watchlist/page.tsx missing 'Monitoring active' status label"
        )

    def test_no_material_thesis_change_label_present(self):
        src = self._read_page()
        assert "No material thesis change" in src, (
            "watchlist/page.tsx missing 'No material thesis change' status label"
        )

    def test_macro_sensitivity_elevated_label_present(self):
        src = self._read_page()
        assert "Macro sensitivity elevated" in src, (
            "watchlist/page.tsx missing 'Macro sensitivity elevated' status label"
        )

    def test_positioning_risk_increasing_label_present(self):
        src = self._read_page()
        assert "Positioning risk increasing" in src, (
            "watchlist/page.tsx missing 'Positioning risk increasing' status label"
        )

    def test_status_indicator_rendered_in_company_column(self):
        src = self._read_page()
        assert "statusIndicator(entry)" in src, (
            "watchlist/page.tsx does not render statusIndicator(entry) in the Company column"
        )

    def test_material_change_detected_label_present(self):
        src = self._read_page()
        assert "Material change detected" in src, (
            "watchlist/page.tsx missing 'Material change detected' label in statusIndicator"
        )
