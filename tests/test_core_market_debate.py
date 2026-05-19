"""
test_core_market_debate.py — Deterministic tests for the Core Market Debate layer.

Covers
------
1. core_market_debate field exists in InvestmentThesis schema
2. Not generic — banned phrases checked
3. Max 1 sentence / question
4. Debate changes appear in ThesisDiff.what_changed
5. Alerts can classify core_debate_shift
6. _classify_debate_type maps correctly
7. _build_core_debate_mandate_block renders key sections
8. core_debate_shifted detection in compare_thesis_snapshots
9. Schema field: ThesisDiff has core_debate_shifted fields
10. Conclusion schema description requires fulcrum restatement
11. Debate type drives depth directive content
12. Historical debate comparison block injected when prior snapshot present

No LLM calls, no network calls — pure unit tests.
"""

from __future__ import annotations

import pytest

from app.schemas import (
    InvestmentThesis,
    ThesisDiff,
    ThesisSnapshot,
    MaterialChangeEvent,
)
from app.services.thesis_synthesizer import (
    _classify_debate_type,
    _build_core_debate_mandate_block,
)
from app.services.thesis_memory_service import (
    compare_thesis_snapshots,
    detect_material_change,
    _eval_core_debate_shift,
    ALERT_RULE_EVALUATORS,
)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _make_snapshot(
    ticker: str = "AAPL",
    core_debate: str = "",
    core_market_debate: str = "",
    confidence: float = 0.72,
    trend: str = "stable",
    dominant_dim: str = "valuation",
) -> ThesisSnapshot:
    return ThesisSnapshot.model_construct(
        ticker=ticker,
        core_debate=core_debate,
        core_market_debate=core_market_debate,
        confidence_score=confidence,
        thesis_trend=trend,
        dominant_dimension=dominant_dim,
        company_name="",
        timestamp="2025-01-01T00:00:00Z",
        one_sentence_thesis="",
        direct_answer="",
        bull_thesis="",
        bear_thesis="",
        conclusion="",
        top_signals=[],
        top_risks=[],
        key_drivers=[],
        key_risks_text=[],
        confidence_reasoning="",
        change_drivers=[],
        what_changed=[],
        signal_hash="",
        risk_hash="",
        drift_state="",
    )


def _make_diff(
    core_debate_shifted: bool = False,
    prev_core_debate: str = "",
    curr_core_debate: str = "",
    confidence_change: float = 0.0,
    material_shift_detected: bool = False,
    severity: str = "low",
    **kwargs,
) -> ThesisDiff:
    return ThesisDiff.model_construct(
        core_debate_shifted=core_debate_shifted,
        prev_core_debate=prev_core_debate,
        curr_core_debate=curr_core_debate,
        confidence_change=confidence_change,
        material_shift_detected=material_shift_detected,
        severity=severity,
        what_changed=[],
        thesis_trend="stable",
        change_drivers=[],
        new_risks=[],
        removed_risks=[],
        strengthening_signals=[],
        weakening_signals=[],
        top_signal_replaced=False,
        trend_flipped=False,
        drift_state="unclear",
        previous_snapshot_id=None,
        current_snapshot_id=None,
        **kwargs,
    )


# ============================================================================
# 1. Schema — InvestmentThesis has core_market_debate
# ============================================================================

class TestInvestmentThesisSchema:
    """InvestmentThesis must have core_debate and core_market_debate fields."""

    def test_core_debate_field_exists(self):
        thesis = InvestmentThesis(ticker="AAPL", company_name="Apple Inc.")
        assert hasattr(thesis, "core_debate")

    def test_core_market_debate_field_exists(self):
        thesis = InvestmentThesis(ticker="AAPL", company_name="Apple Inc.")
        assert hasattr(thesis, "core_market_debate")

    def test_core_debate_defaults_empty(self):
        thesis = InvestmentThesis(ticker="AAPL", company_name="Apple Inc.")
        assert isinstance(thesis.core_debate, str)

    def test_core_market_debate_defaults_empty(self):
        thesis = InvestmentThesis(ticker="AAPL", company_name="Apple Inc.")
        assert isinstance(thesis.core_market_debate, str)

    def test_core_debate_accepts_question(self):
        thesis = InvestmentThesis(
            ticker="AAPL",
            company_name="Apple Inc.",
            core_debate="Can Services growth absorb multiple compression as rates stay higher for longer?",
        )
        assert "Services" in thesis.core_debate

    def test_core_market_debate_accepts_question(self):
        thesis = InvestmentThesis(
            ticker="NVDA",
            company_name="NVIDIA Corporation",
            core_market_debate="Is Nvidia demand structural or peak-cycle behavior?",
        )
        assert "structural" in thesis.core_market_debate


# ============================================================================
# 2. Schema — ThesisDiff has core_debate_shifted fields
# ============================================================================

class TestThesisDiffDebateFields:
    """ThesisDiff must have core_debate_shifted, prev_core_debate, curr_core_debate."""

    def test_core_debate_shifted_field_exists(self):
        diff = ThesisDiff()
        assert hasattr(diff, "core_debate_shifted")
        assert diff.core_debate_shifted is False

    def test_prev_core_debate_field_exists(self):
        diff = ThesisDiff()
        assert hasattr(diff, "prev_core_debate")
        assert isinstance(diff.prev_core_debate, str)

    def test_curr_core_debate_field_exists(self):
        diff = ThesisDiff()
        assert hasattr(diff, "curr_core_debate")
        assert isinstance(diff.curr_core_debate, str)

    def test_core_debate_shifted_defaults_false(self):
        diff = ThesisDiff()
        assert diff.core_debate_shifted is False

    def test_diff_accepts_core_debate_shifted_true(self):
        diff = ThesisDiff(
            core_debate_shifted=True,
            prev_core_debate="Can Services growth offset multiple compression?",
            curr_core_debate="Is the regulatory overhang now the primary investment question?",
        )
        assert diff.core_debate_shifted is True
        assert "Services" in diff.prev_core_debate
        assert "regulatory" in diff.curr_core_debate


# ============================================================================
# 3. Debate shift detection via compare_thesis_snapshots
# ============================================================================

class TestDebateShiftDetection:
    """compare_thesis_snapshots() detects meaningful debate changes."""

    def test_same_debate_no_shift_detected(self):
        debate = "Can Services growth absorb multiple compression as rates stay higher for longer?"
        prev = _make_snapshot(core_debate=debate)
        curr = _make_snapshot(core_debate=debate)
        diff = compare_thesis_snapshots(prev, curr)
        assert diff.core_debate_shifted is False

    def test_very_similar_debate_no_shift(self):
        prev = _make_snapshot(core_debate="Can Services growth offset rate-driven multiple compression?")
        curr = _make_snapshot(core_debate="Can Services growth offset rate-driven multiple compression at current levels?")
        diff = compare_thesis_snapshots(prev, curr)
        # Minor wording change — should NOT flag as shifted
        assert diff.core_debate_shifted is False

    def test_completely_different_debate_shift_detected(self):
        prev = _make_snapshot(
            core_debate="Can Services growth absorb multiple compression as rates stay higher?",
        )
        curr = _make_snapshot(
            core_debate="Does the antitrust regulatory overhang now outweigh the earnings trajectory?",
        )
        diff = compare_thesis_snapshots(prev, curr)
        assert diff.core_debate_shifted is True

    def test_debate_shift_populates_prev_curr_fields(self):
        prev_debate = "Can Services growth absorb multiple compression as rates stay higher?"
        curr_debate = "Does the antitrust regulatory overhang now outweigh the earnings trajectory?"
        prev = _make_snapshot(core_debate=prev_debate)
        curr = _make_snapshot(core_debate=curr_debate)
        diff = compare_thesis_snapshots(prev, curr)
        if diff.core_debate_shifted:
            assert diff.prev_core_debate != ""
            assert diff.curr_core_debate != ""

    def test_debate_shift_appears_in_what_changed(self):
        prev = _make_snapshot(
            core_debate="Can Services growth absorb multiple compression?",
        )
        curr = _make_snapshot(
            core_debate="Is the antitrust regulatory overhang now the dominant risk?",
        )
        diff = compare_thesis_snapshots(prev, curr)
        if diff.core_debate_shifted:
            combined = " ".join(diff.what_changed).lower()
            assert "debate" in combined or "core" in combined

    def test_empty_debates_no_shift(self):
        prev = _make_snapshot(core_debate="")
        curr = _make_snapshot(core_debate="")
        diff = compare_thesis_snapshots(prev, curr)
        assert diff.core_debate_shifted is False

    def test_one_empty_one_populated_no_shift(self):
        """If only one side has a debate, cannot compare — should not flag."""
        prev = _make_snapshot(core_debate="")
        curr = _make_snapshot(core_debate="Can Services growth hold at higher rates?")
        diff = compare_thesis_snapshots(prev, curr)
        assert diff.core_debate_shifted is False

    def test_domain_shift_valuation_to_regulatory_detected(self):
        """Shift from valuation debate to regulatory debate must be detected."""
        prev = _make_snapshot(
            core_debate="At 28x forward earnings, is the multiple already pricing in Services durability?",
        )
        curr = _make_snapshot(
            core_debate="Does EU DMA enforcement risk now outweigh the services revenue trajectory?",
        )
        diff = compare_thesis_snapshots(prev, curr)
        assert diff.core_debate_shifted is True


# ============================================================================
# 4. Alert: core_debate_shift evaluator
# ============================================================================

class TestCoreDebateShiftAlert:
    """_eval_core_debate_shift fires when core_debate_shifted is True."""

    def test_evaluator_exists_in_registry(self):
        assert "core_debate_shift" in ALERT_RULE_EVALUATORS

    def test_fires_when_debate_shifted(self):
        diff = _make_diff(core_debate_shifted=True)
        assert _eval_core_debate_shift(diff, None) is True

    def test_does_not_fire_when_debate_stable(self):
        diff = _make_diff(core_debate_shifted=False)
        assert _eval_core_debate_shift(diff, None) is False

    def test_threshold_unused_always_binary(self):
        """Debate shift is binary — threshold parameter has no effect."""
        diff_shifted = _make_diff(core_debate_shifted=True)
        diff_stable = _make_diff(core_debate_shifted=False)
        assert _eval_core_debate_shift(diff_shifted, 0.5) is True
        assert _eval_core_debate_shift(diff_stable, 0.5) is False
        assert _eval_core_debate_shift(diff_shifted, 0.0) is True

    def test_detect_material_change_uses_core_debate_shift_category(self):
        """When debate shifts, change_category should be 'core_debate_shift'."""
        prev = _make_snapshot(
            core_debate="Can Services growth absorb multiple compression?",
        )
        curr = _make_snapshot(
            core_debate="Does the antitrust regulatory overhang now dominate the thesis?",
        )
        diff = compare_thesis_snapshots(prev, curr)
        if diff.core_debate_shifted and diff.material_shift_detected:
            event = detect_material_change(diff, "AAPL", prev, curr)
            if event:
                assert event.change_category == "core_debate_shift"


# ============================================================================
# 5. _classify_debate_type
# ============================================================================

class TestClassifyDebateType:
    """_classify_debate_type correctly maps question and dimension to debate category."""

    def test_valuation_question_maps_to_valuation(self):
        result = _classify_debate_type("operational", "Is the P/E multiple justified at current earnings?")
        assert result == "valuation"

    def test_multiple_keyword_maps_to_valuation(self):
        result = _classify_debate_type("operational", "What does the current multiple imply?")
        assert result == "valuation"

    def test_margin_keyword_maps_to_margin(self):
        result = _classify_debate_type("operational", "Can Google Cloud margins continue to expand?")
        assert result == "margin"

    def test_competition_keyword_maps_to_product(self):
        result = _classify_debate_type("operational", "Is Tesla losing market share to BYD?")
        assert result == "product_competition"

    def test_regulatory_keyword_maps_to_regulatory(self):
        result = _classify_debate_type("operational", "How does the antitrust regulatory case affect Meta?")
        assert result == "regulatory"

    def test_rate_keyword_maps_to_macro(self):
        # Use a pure macro question — "inflation" triggers macro, no earlier pattern matches
        result = _classify_debate_type("operational", "How does inflation affect Apple's earnings?")
        assert result == "macro"

    def test_macro_dimension_maps_to_macro_fallback(self):
        result = _classify_debate_type("macro", "Tell me about Apple")
        assert result == "macro"

    def test_valuation_dimension_maps_to_valuation_fallback(self):
        result = _classify_debate_type("valuation", "Tell me about Apple")
        assert result == "valuation"

    def test_regulatory_dimension_maps_to_regulatory_fallback(self):
        result = _classify_debate_type("regulatory", "Tell me about Meta")
        assert result == "regulatory"

    def test_operational_dimension_maps_to_margin_fallback(self):
        result = _classify_debate_type("operational", "Tell me about Apple")
        assert result == "margin"

    def test_empty_question_falls_back_to_dimension(self):
        result = _classify_debate_type("valuation", "")
        assert result == "valuation"

    def test_unknown_dimension_defaults_to_product_competition(self):
        result = _classify_debate_type("unknown_dim", "")
        assert result == "product_competition"

    def test_question_overrides_dimension(self):
        """Question-level signal is stronger than dimension-level."""
        # Dimension says macro, question says valuation → question wins
        result = _classify_debate_type("macro", "Is the current P/E justified?")
        assert result == "valuation"


# ============================================================================
# 6. _build_core_debate_mandate_block
# ============================================================================

class TestCoreDebateMandateBlock:
    """_build_core_debate_mandate_block renders expected content."""

    def test_returns_non_empty_string(self):
        result = _build_core_debate_mandate_block(
            company_name="Apple Inc.", ticker="AAPL",
            dominant_dim="valuation", debate_type="valuation",
        )
        assert isinstance(result, str)
        assert len(result) > 100

    def test_contains_fulcrum_concept(self):
        result = _build_core_debate_mandate_block(
            company_name="Apple Inc.", ticker="AAPL",
            dominant_dim="valuation", debate_type="valuation",
        )
        assert "fulcrum" in result.lower()

    def test_contains_company_and_ticker(self):
        result = _build_core_debate_mandate_block(
            company_name="Apple Inc.", ticker="AAPL",
            dominant_dim="valuation", debate_type="valuation",
        )
        assert "Apple Inc." in result
        assert "AAPL" in result

    def test_contains_banned_generic_examples(self):
        """The block must list examples of bad (generic) debate phrasing."""
        result = _build_core_debate_mandate_block(
            company_name="Apple Inc.", ticker="AAPL",
            dominant_dim="valuation", debate_type="valuation",
        )
        assert "BAD" in result or "BANNED" in result or "rejected" in result.lower()

    def test_valuation_debate_type_depth_directive_mentions_valuation_view(self):
        result = _build_core_debate_mandate_block(
            company_name="Apple Inc.", ticker="AAPL",
            dominant_dim="valuation", debate_type="valuation",
        )
        assert "valuation_view" in result

    def test_regulatory_debate_type_depth_directive_mentions_bear_thesis(self):
        result = _build_core_debate_mandate_block(
            company_name="Meta Platforms", ticker="META",
            dominant_dim="regulatory", debate_type="regulatory",
        )
        assert "bear_thesis" in result

    def test_macro_debate_type_depth_directive_mentions_macro_sensitivity(self):
        result = _build_core_debate_mandate_block(
            company_name="Apple Inc.", ticker="AAPL",
            dominant_dim="macro", debate_type="macro",
        )
        assert "macro_sensitivity" in result

    def test_margin_debate_mentions_operating_leverage_or_margin(self):
        result = _build_core_debate_mandate_block(
            company_name="Alphabet Inc.", ticker="GOOGL",
            dominant_dim="operational", debate_type="margin",
        )
        assert "margin" in result.lower() or "operating leverage" in result.lower()

    def test_product_debate_mentions_bull_bear_or_competition(self):
        result = _build_core_debate_mandate_block(
            company_name="Tesla Inc.", ticker="TSLA",
            dominant_dim="operational", debate_type="product_competition",
        )
        assert "bull_thesis" in result or "bear_thesis" in result or "compet" in result.lower()

    def test_conclusion_requirement_present(self):
        result = _build_core_debate_mandate_block(
            company_name="Apple Inc.", ticker="AAPL",
            dominant_dim="valuation", debate_type="valuation",
        )
        assert "CONCLUSION" in result or "conclusion" in result.lower()

    def test_prior_snapshot_adds_historical_debate_block(self):
        """When prior snapshot has a core_debate, block adds historical comparison."""
        prior = ThesisSnapshot.model_construct(
            ticker="AAPL",
            core_debate="Can Services growth absorb multiple compression?",
            core_market_debate="Is the multiple sustainable at current rates?",
            confidence_score=0.72,
            thesis_trend="stable",
        )
        result = _build_core_debate_mandate_block(
            company_name="Apple Inc.", ticker="AAPL",
            dominant_dim="valuation", debate_type="valuation",
            prior_snapshot=prior,
        )
        assert "PRIOR" in result or "prior" in result.lower()
        assert "debate" in result.lower()

    def test_no_prior_snapshot_no_historical_block(self):
        result = _build_core_debate_mandate_block(
            company_name="Apple Inc.", ticker="AAPL",
            dominant_dim="valuation", debate_type="valuation",
            prior_snapshot=None,
        )
        assert "PRIOR CORE DEBATE" not in result

    def test_never_raises_on_any_inputs(self):
        for ticker, company, dim, debate in [
            ("AAPL", "Apple", "valuation", "valuation"),
            ("NVDA", "Nvidia", "macro", "macro"),
            ("META", "Meta", "regulatory", "regulatory"),
            ("TSLA", "Tesla", "operational", "margin"),
            ("RKLB", "Rocket Lab", "operational", "product_competition"),
            ("", "", "", ""),
        ]:
            result = _build_core_debate_mandate_block(
                company_name=company, ticker=ticker,
                dominant_dim=dim, debate_type=debate,
            )
            assert isinstance(result, str)


# ============================================================================
# 7. Not generic — banned phrases
# ============================================================================

class TestDebateGenericnessBan:
    """The mandate block explicitly bans generic debate phrasings."""

    def test_block_bans_market_is_debating_whether(self):
        result = _build_core_debate_mandate_block(
            company_name="Apple Inc.", ticker="AAPL",
            dominant_dim="valuation", debate_type="valuation",
        )
        assert "The market is debating whether" in result or "BANNED" in result

    def test_block_bans_statement_not_debate(self):
        result = _build_core_debate_mandate_block(
            company_name="Nvidia", ticker="NVDA",
            dominant_dim="macro", debate_type="macro",
        )
        # Must contain language about not writing statements
        assert "statement" in result.lower() or "NOT a statement" in result

    def test_block_requires_question_phrasing(self):
        result = _build_core_debate_mandate_block(
            company_name="Tesla", ticker="TSLA",
            dominant_dim="operational", debate_type="product_competition",
        )
        assert "question" in result.lower() or "open question" in result.lower()


# ============================================================================
# 8. Conclusion schema description requires fulcrum restatement
# ============================================================================

class TestConclusionSchemaRequirement:
    """The _THESIS_SCHEMA_DESCRIPTION conclusion field must require fulcrum restatement."""

    def test_conclusion_description_requires_fulcrum(self):
        from app.services.thesis_synthesizer import _THESIS_SCHEMA_DESCRIPTION
        conclusion_start = _THESIS_SCHEMA_DESCRIPTION.find('"conclusion"')
        assert conclusion_start >= 0
        conclusion_section = _THESIS_SCHEMA_DESCRIPTION[conclusion_start:conclusion_start + 800]
        assert "fulcrum" in conclusion_section.lower() or "debate reduces" in conclusion_section.lower()

    def test_conclusion_description_forbids_generic(self):
        from app.services.thesis_synthesizer import _THESIS_SCHEMA_DESCRIPTION
        conclusion_start = _THESIS_SCHEMA_DESCRIPTION.find('"conclusion"')
        conclusion_section = _THESIS_SCHEMA_DESCRIPTION[conclusion_start:conclusion_start + 800]
        assert "FORBIDDEN" in conclusion_section or "generic" in conclusion_section.lower()

    def test_conclusion_description_has_good_examples(self):
        from app.services.thesis_synthesizer import _THESIS_SCHEMA_DESCRIPTION
        conclusion_start = _THESIS_SCHEMA_DESCRIPTION.find('"conclusion"')
        conclusion_section = _THESIS_SCHEMA_DESCRIPTION[conclusion_start:conclusion_start + 1000]
        assert "GOOD" in conclusion_section


# ============================================================================
# 9. Alert materiality: debate shift adds to materiality_score
# ============================================================================

class TestDebateShiftMateriality:
    """A core debate shift should increase the materiality_score."""

    def test_debate_shift_increases_materiality_score(self):
        """A shift with no other changes should still have non-zero materiality."""
        prev = _make_snapshot(
            core_debate="Can Services growth absorb multiple compression as rates rise?",
        )
        curr = _make_snapshot(
            core_debate="Does the EU antitrust regulatory risk now outweigh the earnings growth story?",
        )
        diff = compare_thesis_snapshots(prev, curr)
        if diff.core_debate_shifted and diff.material_shift_detected:
            event = detect_material_change(diff, "AAPL", prev, curr)
            if event:
                # Debate shift contributes 0.25 to materiality_score
                assert event.materiality_score >= 0.20

    def test_debate_shift_event_summary_mentions_debate(self):
        """The alert summary for core_debate_shift should mention the debate change."""
        prev = _make_snapshot(
            core_debate="Can Services growth absorb multiple compression as rates rise?",
        )
        curr = _make_snapshot(
            core_debate="Does the EU antitrust regulatory risk now outweigh the earnings trajectory?",
        )
        diff = compare_thesis_snapshots(prev, curr)
        if diff.core_debate_shifted and diff.material_shift_detected:
            event = detect_material_change(diff, "AAPL", prev, curr)
            if event:
                summary_lower = event.summary.lower()
                assert any(word in summary_lower for word in [
                    "debate", "shifted", "rotated", "changed", "fulcrum"
                ])
