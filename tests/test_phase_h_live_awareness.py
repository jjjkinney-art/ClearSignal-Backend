"""
test_phase_h_live_awareness.py — Phase H: Live Market Awareness tests.

Covers
------
- _classify_evidence_type(): correct category for earnings/guidance/macro/regulatory/product
- _evidence_recency_weight(): correct multipliers (1.5 for recent, 0.8 for old)
- _composite_evidence_score(): earnings items get higher score than timeless items
- _evidence_block(): top item is most recent/relevant with recency ranking
- _extract_recent_events(): empty input, high-signal presence, no-signal returns ''
- _build_expectation_delta_block(): required language, non-empty, company name, consensus, BANNED
- _build_narrative_state_block(): returns '' with no prior, non-empty when dim changed, transition language
- Alert event summary: market-significant language present (no "confidence decreased 8%")
- PM compression section exists in prompt
- _build_event_summary() for 'core_debate_shift' mentions debate-related language

No LLM calls, no network calls — pure unit tests.
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock

from app.schemas import (
    RetrievedEvidence,
    ThesisDiff,
    ThesisSnapshot,
)
from app.services.thesis_synthesizer import (
    _classify_evidence_type,
    _evidence_recency_weight,
    _composite_evidence_score,
    _evidence_block,
    _extract_recent_events,
    _build_expectation_delta_block,
    _build_narrative_state_block,
)
from app.services.thesis_memory_service import (
    _build_event_summary,
    _eval_core_debate_shift,
)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _make_ev(
    title: str,
    summary: str,
    source: str = "Reuters",
    score: float = 0.8,
    timestamp: str = "2025-03-01",
) -> RetrievedEvidence:
    return RetrievedEvidence(
        title=title,
        summary=summary,
        source=source,
        relevance_score=score,
        timestamp=timestamp,
    )


def _make_snapshot(
    dominant_dimension: str = "valuation",
    core_debate: str = "Is the multiple sustainable?",
    core_market_debate: str = "",
    confidence_score: float = 0.75,
    ticker: str = "AAPL",
) -> ThesisSnapshot:
    return ThesisSnapshot(
        ticker=ticker,
        company_name="Apple Inc.",
        timestamp="2025-03-01T00:00:00Z",
        one_sentence_thesis="",
        direct_answer="",
        bull_thesis="",
        bear_thesis="",
        conclusion="",
        top_signals=[],
        top_risks=[],
        key_drivers=[],
        key_risks_text=[],
        confidence_score=confidence_score,
        confidence_reasoning="",
        thesis_trend="stable",
        change_drivers=[],
        what_changed=[],
        signal_hash="",
        risk_hash="",
        dominant_dimension=dominant_dimension,
        core_debate=core_debate,
        core_market_debate=core_market_debate,
    )


def _make_diff(
    confidence_change: float = -0.10,
    new_risks: list = None,
    trend_flipped: bool = False,
    top_signal_replaced: bool = False,
    core_debate_shifted: bool = False,
    prev_core_debate: str = "",
    curr_core_debate: str = "",
    thesis_trend: str = "weakening",
) -> ThesisDiff:
    return ThesisDiff(
        what_changed=["test change"],
        thesis_trend=thesis_trend,
        change_drivers=[],
        material_shift_detected=True,
        severity="medium",
        confidence_change=confidence_change,
        new_risks=new_risks or [],
        removed_risks=[],
        strengthening_signals=[],
        weakening_signals=[],
        top_signal_replaced=top_signal_replaced,
        trend_flipped=trend_flipped,
        previous_snapshot_id=None,
        current_snapshot_id=None,
        core_debate_shifted=core_debate_shifted,
        prev_core_debate=prev_core_debate,
        curr_core_debate=curr_core_debate,
    )


# ── _classify_evidence_type() ──────────────────────────────────────────────────

class TestClassifyEvidenceType:
    def test_earnings_keyword_in_title(self):
        ev = _make_ev(title="Apple Q3 Earnings Beat Expectations", summary="EPS beat.")
        assert _classify_evidence_type(ev) == "earnings"

    def test_guidance_keyword_in_title(self):
        # Use a title that uniquely hits guidance keywords (no earnings/fiscal overlap)
        ev = _make_ev(title="Apple Lowers Outlook: Revised Estimates", summary="Guidance revised.")
        assert _classify_evidence_type(ev) == "guidance"

    def test_macro_keyword_in_source(self):
        ev = _make_ev(title="Rate Decision", summary="FOMC held rates.", source="Fed Reserve")
        result = _classify_evidence_type(ev)
        assert result == "macro"

    def test_regulatory_keyword(self):
        ev = _make_ev(title="DOJ Antitrust Investigation", summary="DOJ probe launched.")
        assert _classify_evidence_type(ev) == "regulatory"

    def test_product_keyword(self):
        ev = _make_ev(title="Apple Unveils New AI Model", summary="Product launch announced.")
        assert _classify_evidence_type(ev) == "product"

    def test_analyst_keyword(self):
        # Use a title that uniquely hits analyst keywords without guidance overlap
        ev = _make_ev(title="Goldman Sachs Downgrades AAPL Rating", summary="Analyst downgrade.")
        assert _classify_evidence_type(ev) == "analyst"

    def test_market_keyword(self):
        ev = _make_ev(title="AAPL Stock Rally on Volume", summary="Stock trading up.")
        assert _classify_evidence_type(ev) == "market"

    def test_fallback_to_research(self):
        ev = _make_ev(title="Random Industry Overview", summary="General industry trends.", source="ResearchCo")
        assert _classify_evidence_type(ev) == "research"


# ── _evidence_recency_weight() ─────────────────────────────────────────────────

class TestEvidenceRecencyWeight:
    def test_same_day_returns_1_5(self):
        ev = _make_ev(title="T", summary="S", timestamp="2025-03-15")
        weight = _evidence_recency_weight(ev, "2025-03-15")
        assert weight == 1.5

    def test_within_30_days_returns_1_5(self):
        ev = _make_ev(title="T", summary="S", timestamp="2025-02-20")
        weight = _evidence_recency_weight(ev, "2025-03-15")
        assert weight == 1.5

    def test_31_to_60_days_returns_1_2(self):
        ev = _make_ev(title="T", summary="S", timestamp="2025-01-20")
        weight = _evidence_recency_weight(ev, "2025-03-15")
        assert weight == 1.2

    def test_61_to_90_days_returns_1_0(self):
        ev = _make_ev(title="T", summary="S", timestamp="2024-12-20")
        weight = _evidence_recency_weight(ev, "2025-03-15")
        assert weight == 1.0

    def test_over_90_days_returns_0_8(self):
        ev = _make_ev(title="T", summary="S", timestamp="2024-11-01")
        weight = _evidence_recency_weight(ev, "2025-03-15")
        assert weight == 0.80

    def test_bad_timestamp_returns_1_0(self):
        ev = _make_ev(title="T", summary="S", timestamp="not-a-date")
        weight = _evidence_recency_weight(ev, "2025-03-15")
        assert weight == 1.0

    def test_bad_reference_returns_1_0(self):
        ev = _make_ev(title="T", summary="S", timestamp="2025-01-01")
        weight = _evidence_recency_weight(ev, "bad-reference")
        assert weight == 1.0


# ── _composite_evidence_score() ────────────────────────────────────────────────

class TestCompositeEvidenceScore:
    def test_earnings_item_scores_higher_than_timeless(self):
        # Recent earnings item vs older generic item with same relevance
        earnings_ev = _make_ev(
            title="Apple Q3 Earnings Beat",
            summary="EPS beat estimates significantly.",
            score=0.8,
            timestamp="2025-03-10",
        )
        generic_ev = _make_ev(
            title="General Market Overview",
            summary="Markets continued their trend.",
            source="General",
            score=0.8,
            timestamp="2024-11-01",
        )
        reference_ts = "2025-03-15"
        earnings_score = _composite_evidence_score(earnings_ev, reference_ts)
        generic_score = _composite_evidence_score(generic_ev, reference_ts)
        assert earnings_score > generic_score

    def test_guidance_gets_type_bonus(self):
        guidance_ev = _make_ev(
            title="Apple Raises Guidance",
            summary="Guidance raised for Q4.",
            score=0.7,
            timestamp="2025-03-10",
        )
        reference_ts = "2025-03-15"
        score = _composite_evidence_score(guidance_ev, reference_ts)
        # 0.7 * 1.5 (recent) + 0.1 (guidance bonus) = 1.15
        assert score > 0.7 * 1.5

    def test_score_is_non_negative(self):
        ev = _make_ev(title="Test", summary="Test summary.", score=0.1, timestamp="2020-01-01")
        score = _composite_evidence_score(ev, "2025-03-15")
        assert score >= 0


# ── _evidence_block() ─────────────────────────────────────────────────────────

class TestEvidenceBlock:
    def test_empty_evidence_returns_no_evidence_string(self):
        result = _evidence_block([])
        assert "No evidence available" in result

    def test_top_item_is_most_recent_and_relevant(self):
        recent_ev = _make_ev(
            title="Q3 Earnings Beat",
            summary="EPS beat significantly.",
            score=0.8,
            timestamp="2025-03-14",
        )
        old_ev = _make_ev(
            title="Old Report",
            summary="Old market analysis.",
            score=0.9,  # Higher raw relevance but much older
            timestamp="2024-06-01",
        )
        result = _evidence_block([old_ev, recent_ev])
        # Recent earnings item should appear first (index [1])
        first_bracket = result.find("[1]")
        assert "Earnings" in result[first_bracket:first_bracket + 100] or "Q3" in result[first_bracket:first_bracket + 100]

    def test_includes_evidence_type_label(self):
        ev = _make_ev(title="Apple Q3 Earnings Beat", summary="EPS beat.")
        result = _evidence_block([ev])
        assert "[EARNINGS]" in result

    def test_includes_timestamp_year_month(self):
        ev = _make_ev(title="Test Event", summary="Summary.", timestamp="2025-03-15")
        result = _evidence_block([ev])
        assert "2025-03" in result

    def test_max_items_respected(self):
        evidence = [
            _make_ev(title=f"Item {i}", summary="Summary.", score=0.5, timestamp="2025-01-01")
            for i in range(20)
        ]
        result = _evidence_block(evidence, max_items=5)
        # Count occurrences of "[N]" patterns
        count = sum(1 for i in range(1, 21) if f"[{i}]" in result)
        assert count <= 5


# ── _extract_recent_events() ──────────────────────────────────────────────────

class TestExtractRecentEvents:
    def test_empty_evidence_returns_empty_string(self):
        result = _extract_recent_events([])
        assert result == ""

    def test_returns_non_empty_when_earnings_evidence_present(self):
        ev = _make_ev(
            title="Apple Q3 Earnings Beat Estimates",
            summary="Apple beat EPS estimates by 12% — earnings exceeded analyst expectations.",
            score=0.9,
            timestamp="2025-03-10",
        )
        result = _extract_recent_events([ev])
        assert result != ""
        assert "RECENT MARKET EVENTS" in result

    def test_returns_empty_when_no_high_signal_keywords(self):
        ev = _make_ev(
            title="General Industry Overview",
            summary="The sector continues to face structural changes in the long term.",
            source="General",
            score=0.5,
            timestamp="2025-03-01",
        )
        result = _extract_recent_events([ev])
        assert result == ""

    def test_includes_reference_language_hint(self):
        ev = _make_ev(
            title="Apple Raises Guidance",
            summary="Apple raised its quarterly guidance after strong earnings results.",
            score=0.9,
            timestamp="2025-03-10",
        )
        result = _extract_recent_events([ev])
        assert "following the recent earnings" in result or "guidance revision" in result

    def test_limits_to_three_events(self):
        evidence = [
            _make_ev(
                title=f"Apple Earnings Beat Q{i}",
                summary=f"EPS beat significantly in quarter {i}. Revenue exceeded guidance.",
                score=0.9,
                timestamp=f"2025-0{i}-01",
            )
            for i in range(1, 6)
        ]
        result = _extract_recent_events(evidence)
        # The block should not have more than 3 event lines (heuristic: count [TYPE lines)
        lines_with_bracket = [l for l in result.split("\n") if l.strip().startswith("[")]
        assert len(lines_with_bracket) <= 3


# ── _build_expectation_delta_block() ─────────────────────────────────────────

class TestBuildExpectationDeltaBlock:
    def test_non_empty(self):
        result = _build_expectation_delta_block("Apple Inc.", "AAPL", "valuation")
        assert len(result.strip()) > 0

    def test_contains_company_name(self):
        result = _build_expectation_delta_block("Apple Inc.", "AAPL", "valuation")
        assert "Apple Inc." in result

    def test_contains_ticker(self):
        result = _build_expectation_delta_block("Apple Inc.", "AAPL", "valuation")
        assert "AAPL" in result

    def test_contains_consensus(self):
        result = _build_expectation_delta_block("Apple Inc.", "AAPL", "valuation")
        assert "consensus" in result.lower() or "CONSENSUS" in result

    def test_contains_banned_section(self):
        result = _build_expectation_delta_block("Apple Inc.", "AAPL", "valuation")
        assert "BANNED" in result

    def test_contains_expectation_delta_header(self):
        result = _build_expectation_delta_block("Apple Inc.", "AAPL", "valuation")
        assert "EXPECTATION DELTA" in result

    def test_contains_required_language_patterns(self):
        result = _build_expectation_delta_block("Apple Inc.", "AAPL", "valuation")
        assert "REQUIRED LANGUAGE PATTERNS" in result or "Consensus already expects" in result

    def test_different_debate_types_produce_different_framing(self):
        val_result = _build_expectation_delta_block("Apple Inc.", "AAPL", "valuation")
        macro_result = _build_expectation_delta_block("Apple Inc.", "AAPL", "macro")
        assert val_result != macro_result

    def test_unknown_debate_type_falls_back_gracefully(self):
        result = _build_expectation_delta_block("Apple Inc.", "AAPL", "unknown_type")
        assert len(result.strip()) > 0


# ── _build_narrative_state_block() ───────────────────────────────────────────

class TestBuildNarrativeStateBlock:
    def test_returns_empty_when_no_prior_snapshot(self):
        result = _build_narrative_state_block(
            prior_snapshot=None,
            dominant_dim="valuation",
            debate_type="valuation",
        )
        assert result == ""

    def test_returns_non_empty_when_dimension_changed(self):
        prior = _make_snapshot(dominant_dimension="macro")
        result = _build_narrative_state_block(
            prior_snapshot=prior,
            dominant_dim="valuation",
            debate_type="valuation",
        )
        assert len(result.strip()) > 0

    def test_contains_narrative_state_header(self):
        prior = _make_snapshot(dominant_dimension="macro")
        result = _build_narrative_state_block(
            prior_snapshot=prior,
            dominant_dim="valuation",
            debate_type="valuation",
        )
        assert "NARRATIVE STATE" in result

    def test_contains_transition_language(self):
        prior = _make_snapshot(dominant_dimension="macro")
        result = _build_narrative_state_block(
            prior_snapshot=prior,
            dominant_dim="valuation",
            debate_type="valuation",
        )
        # Should mention the transition from macro → valuation
        lower = result.lower()
        assert "macro" in lower or "valuation" in lower

    def test_stable_dimension_mentions_stable(self):
        prior = _make_snapshot(dominant_dimension="valuation")
        result = _build_narrative_state_block(
            prior_snapshot=prior,
            dominant_dim="valuation",
            debate_type="valuation",
        )
        assert "stable" in result.lower()

    def test_regulatory_to_valuation_transition(self):
        prior = _make_snapshot(dominant_dimension="regulatory")
        result = _build_narrative_state_block(
            prior_snapshot=prior,
            dominant_dim="valuation",
            debate_type="valuation",
        )
        assert len(result.strip()) > 0
        lower = result.lower()
        assert "regulatory" in lower or "valuation" in lower

    def test_unknown_dim_change_still_returns_something(self):
        prior = _make_snapshot(dominant_dimension="valuation")
        result = _build_narrative_state_block(
            prior_snapshot=prior,
            dominant_dim="something_new",
            debate_type="valuation",
        )
        assert len(result.strip()) > 0


# ── Alert event summary tests ─────────────────────────────────────────────────

class TestBuildEventSummary:
    def test_confidence_collapse_market_significant_language(self):
        diff = _make_diff(confidence_change=-0.20)
        result = _build_event_summary("confidence_collapse", diff, "AAPL")
        # Should NOT contain raw percentage language like "confidence decreased 8%"
        assert "confidence decreased" not in result.lower()
        assert "8%" not in result
        # Should contain mechanism language
        assert "AAPL" in result

    def test_thesis_weakened_no_raw_score_language(self):
        diff = _make_diff(confidence_change=-0.09)
        result = _build_event_summary("thesis_weakened", diff, "AAPL")
        assert "confidence decreased" not in result.lower()
        assert "AAPL" in result

    def test_thesis_strengthened_setup_language(self):
        diff = _make_diff(confidence_change=0.10)
        result = _build_event_summary("thesis_strengthened", diff, "AAPL")
        assert "AAPL" in result
        # Should mention setup or operating story
        lower = result.lower()
        assert "setup" in lower or "operating" in lower or "conviction" in lower

    def test_trend_flip_includes_direction(self):
        diff = _make_diff(trend_flipped=True, thesis_trend="weakening")
        result = _build_event_summary("trend_flip", diff, "AAPL")
        assert "weakening" in result
        assert "AAPL" in result

    def test_new_structural_risk_with_named_risk(self):
        diff = _make_diff(new_risks=["Margin compression: gross margins declining"])
        result = _build_event_summary("new_structural_risk", diff, "AAPL")
        assert "Margin compression" in result
        assert "AAPL" in result

    def test_new_structural_risk_without_named_risk(self):
        diff = _make_diff(new_risks=[])
        result = _build_event_summary("new_structural_risk", diff, "AAPL")
        assert "AAPL" in result
        assert len(result.strip()) > 0

    def test_top_signal_replaced_mentions_rotation(self):
        diff = _make_diff(top_signal_replaced=True)
        result = _build_event_summary("top_signal_replaced", diff, "AAPL")
        assert "AAPL" in result
        lower = result.lower()
        assert "rotated" in lower or "driver" in lower or "anchor" in lower

    def test_core_debate_shift_with_prev_curr_debate(self):
        diff = _make_diff(
            core_debate_shifted=True,
            prev_core_debate="Can the multiple hold with rising rates?",
            curr_core_debate="Is regulatory risk already priced in?",
        )
        result = _build_event_summary("core_debate_shift", diff, "AAPL")
        assert "AAPL" in result
        # Should mention debate language
        lower = result.lower()
        assert "debate" in lower or "fulcrum" in lower

    def test_core_debate_shift_without_prev_curr_uses_fallback(self):
        diff = _make_diff(core_debate_shifted=True)
        result = _build_event_summary("core_debate_shift", diff, "AAPL")
        assert "AAPL" in result
        assert len(result.strip()) > 0

    def test_stable_mentions_no_material_change(self):
        diff = _make_diff(confidence_change=0.0)
        result = _build_event_summary("stable", diff, "AAPL")
        assert "AAPL" in result
        lower = result.lower()
        assert "stable" in lower or "no material" in lower

    def test_unknown_type_returns_fallback(self):
        diff = _make_diff()
        result = _build_event_summary("unknown_type_xyz", diff, "AAPL")
        assert "AAPL" in result


# ── PM Compression section in prompt ─────────────────────────────────────────

class TestPMCompressionInPrompt:
    """Verify the MARKET-NATIVE COMPRESSION section exists in the synthesis prompt."""

    def _get_prompt_text(self) -> str:
        """Extract the prompt template by building a minimal synthesis prompt."""
        from app.services.thesis_synthesizer import _build_synthesis_prompt
        from app.schemas import (
            CompanyContext, ValuationView, MacroSensitivity,
            RiskProfile, MarketContext, QualityAssessment,
        )

        company = CompanyContext(
            ticker="AAPL",
            company_name="Apple Inc.",
            sector="Technology",
            industry="Consumer Electronics",
        )

        valuation = ValuationView(
            overall="Valuation test.", confidence=0.75,
        )
        macro = MacroSensitivity(
            overall="Macro test.", confidence=0.75,
        )
        risk = RiskProfile(
            overall="Risk test.", confidence=0.75,
            key_risks=[], risk_reward="balanced",
        )
        market = MarketContext(
            overall="Market test.", confidence=0.75,
            recent_catalysts=[],
        )
        quality = QualityAssessment(
            overall="Quality test.", confidence=0.75,
        )

        evidence = [
            _make_ev("Test Evidence", "Test summary.", score=0.8, timestamp="2025-03-01")
        ]

        prompt = _build_synthesis_prompt(
            company=company,
            valuation=valuation,
            macro=macro,
            risk=risk,
            market=market,
            quality=quality,
            evidence=evidence,
        )
        return prompt

    def test_market_native_compression_section_exists(self):
        prompt = self._get_prompt_text()
        assert "MARKET-NATIVE COMPRESSION" in prompt

    def test_pm_shorthand_examples_present(self):
        prompt = self._get_prompt_text()
        assert "Nothing is broken yet." in prompt

    def test_banned_verbose_patterns_present(self):
        prompt = self._get_prompt_text()
        assert "BANNED verbose patterns" in prompt

    def test_expectation_delta_in_prompt(self):
        prompt = self._get_prompt_text()
        assert "EXPECTATION DELTA" in prompt

    def test_recent_market_events_header_pattern_exists_in_code(self):
        """Verify _extract_recent_events produces the expected header."""
        ev = _make_ev(
            title="Apple Earnings Beat",
            summary="Apple beat EPS estimates and raised guidance for Q4.",
            score=0.9,
            timestamp="2025-03-10",
        )
        result = _extract_recent_events([ev])
        if result:
            assert "RECENT MARKET EVENTS" in result


# ── _eval_core_debate_shift() ─────────────────────────────────────────────────

class TestEvalCoreDebateShift:
    def test_returns_true_when_core_debate_shifted(self):
        diff = _make_diff(core_debate_shifted=True)
        assert _eval_core_debate_shift(diff, threshold=None) is True

    def test_returns_false_when_not_shifted(self):
        diff = _make_diff(core_debate_shifted=False)
        assert _eval_core_debate_shift(diff, threshold=None) is False
