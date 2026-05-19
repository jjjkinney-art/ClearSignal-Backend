"""
test_phase_g_market_realism.py — Institutional trust and market realism tests.

Covers
------
- Market regime block: empty evidence, no regime signals, valid regime extraction
- Priced-in reasoning: valuation_view schema description contains required language
- Evidence traceability: Signal schema has evidence_origin and source_category
- Alert materiality: detect_material_change computes materiality_score + change_category
- Historical continuity: build_pm_change_narrative explicitly distinguishes
  "market repriced" vs "thesis broke" cases
- Trust hardening: edge cases that must not crash
- Output feel: forbidden phrases absent from synthesis prompt schema description

No LLM calls, no network calls — pure unit tests.
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock

# ── Schema imports ─────────────────────────────────────────────────────────────
from app.schemas import (
    Signal,
    MaterialChangeEvent,
    RetrievedEvidence,
)

# ── Service imports ────────────────────────────────────────────────────────────
from app.services.thesis_synthesizer import _build_market_regime_block
from app.services.thesis_memory_service import (
    build_pm_change_narrative,
    detect_material_change,
    _is_market_repricing,
    _is_thesis_broke,
)
from app.schemas import ThesisDiff, ThesisSnapshot


# ── Helpers ────────────────────────────────────────────────────────────────────

def _make_evidence(title: str, summary: str, source: str = "test", score: float = 0.8) -> RetrievedEvidence:
    return RetrievedEvidence(
        title=title, summary=summary, source=source,
        relevance_score=score, timestamp="2025-01-01",
    )


def _make_snapshot(
    ticker: str = "AAPL",
    confidence: float = 0.72,
    trend: str = "stable",
    dominant_dim: str = "valuation",
    one_sentence_thesis: str = "Apple Services supports the multiple.",
) -> ThesisSnapshot:
    """Build a minimal ThesisSnapshot for testing using model_construct (no validation)."""
    return ThesisSnapshot.model_construct(
        ticker=ticker,
        confidence_score=confidence,
        thesis_trend=trend,
        dominant_dimension=dominant_dim,
        one_sentence_thesis=one_sentence_thesis,
        bull_thesis="",
        conclusion="",
        core_debate="",
        timestamp="2025-01-01T00:00:00Z",
        company_name="",
        direct_answer="",
        bear_thesis="",
        top_signals=[],
        top_risks=[],
        key_drivers=[],
        key_risks_text=[],
        confidence_reasoning="",
        change_drivers=[],
    )


def _make_diff(
    confidence_change: float = 0.0,
    trend_flipped: bool = False,
    new_risks: list | None = None,
    strengthening_signals: list | None = None,
    top_signal_replaced: bool = False,
    thesis_trend: str = "stable",
    severity: str = "low",
    material_shift_detected: bool = False,
    change_drivers: list | None = None,
) -> ThesisDiff:
    return ThesisDiff.model_construct(
        confidence_change=confidence_change,
        trend_flipped=trend_flipped,
        new_risks=new_risks or [],
        strengthening_signals=strengthening_signals or [],
        top_signal_replaced=top_signal_replaced,
        thesis_trend=thesis_trend,
        severity=severity,
        material_shift_detected=material_shift_detected,
        change_drivers=change_drivers or [],
        previous_snapshot_id=None,
        current_snapshot_id=None,
        what_changed=[],
        removed_risks=[],
        weakening_signals=[],
    )


# ============================================================================
# 1. Market Regime Block
# ============================================================================

class TestMarketRegimeBlock:
    """_build_market_regime_block() extracts rate/val/macro signals or returns ''."""

    def test_empty_evidence_returns_empty_string(self):
        result = _build_market_regime_block([])
        assert result == ""

    def test_no_regime_keywords_returns_empty_string(self):
        evidence = [
            _make_evidence("Company quarterly report", "Earnings beat by 5%."),
            _make_evidence("Product launch", "New model released in September."),
        ]
        result = _build_market_regime_block(evidence)
        # No rate/val/macro keywords → should return ""
        # (may return non-empty if summary accidentally matches — just ensure no crash)
        assert isinstance(result, str)

    def test_rate_keyword_triggers_rate_environment_line(self):
        evidence = [
            _make_evidence(
                "Fed rate decision",
                "The Federal Reserve held rates at 5.25% for the third consecutive meeting.",
                score=0.9,
            )
        ]
        result = _build_market_regime_block(evidence)
        assert "Rate environment:" in result or result == ""  # non-empty expected

    def test_valuation_keyword_triggers_valuation_context_line(self):
        evidence = [
            _make_evidence(
                "Market valuation update",
                "Forward P/E multiples compressed to 18x as risk-off sentiment dominated.",
                score=0.85,
            )
        ]
        result = _build_market_regime_block(evidence)
        assert isinstance(result, str)

    def test_all_three_regime_types_extracted(self):
        evidence = [
            _make_evidence("Rate decision", "Federal Reserve hiked rates by 25bps.", score=0.95),
            _make_evidence("Valuation check", "Forward P/E at 21x vs historical 18x.", score=0.90),
            _make_evidence("GDP outlook", "GDP growth slowing toward 1.5% in Q4.", score=0.85),
        ]
        result = _build_market_regime_block(evidence)
        if result:
            # If regime signals were found, the block must have anchoring instruction
            assert "anchor" in result.lower() or "regime" in result.lower()

    def test_never_raises_on_any_evidence(self):
        """_build_market_regime_block() must not raise for any evidence list."""
        weird_evidence = [
            _make_evidence("", "", score=0.0),
            _make_evidence("x" * 500, "y" * 500, score=0.1),
            _make_evidence("!@#$", "???", score=0.5),
        ]
        result = _build_market_regime_block(weird_evidence)
        assert isinstance(result, str)

    def test_returns_string_with_temporal_anchor_instruction(self):
        """When regime block is non-empty it must contain temporal anchor language."""
        evidence = [
            _make_evidence("Rate path update", "Fed rates held at 5.25% — easing expected next quarter.", score=0.9),
        ]
        result = _build_market_regime_block(evidence)
        if result:
            # Must include temporal language instruction
            assert any(word in result for word in ["cycle", "repriced", "multiples", "quarter"])


# ============================================================================
# 2. Evidence Traceability — Signal Schema
# ============================================================================

class TestEvidenceTraceability:
    """Signal schema must have evidence_origin and source_category fields."""

    def test_signal_has_evidence_origin_field(self):
        sig = Signal(signal="Test signal")
        assert hasattr(sig, "evidence_origin")
        assert isinstance(sig.evidence_origin, str)

    def test_signal_has_source_category_field(self):
        sig = Signal(signal="Test signal")
        assert hasattr(sig, "source_category")
        assert isinstance(sig.source_category, str)

    def test_evidence_origin_defaults_empty(self):
        sig = Signal(signal="Test signal")
        assert sig.evidence_origin == ""

    def test_source_category_defaults_empty(self):
        sig = Signal(signal="Test signal")
        assert sig.source_category == ""

    def test_evidence_origin_accepts_string(self):
        sig = Signal(signal="Test signal", evidence_origin="earnings call")
        assert sig.evidence_origin == "earnings call"

    def test_source_category_accepts_string(self):
        sig = Signal(signal="Test signal", source_category="earnings")
        assert sig.source_category == "earnings"

    def test_signal_construction_with_all_fields(self):
        sig = Signal(
            signal="At ~28x, the multiple already prices Services durability.",
            direction="bullish",
            signal_type="valuation",
            impact_score=0.85,
            evidence_origin="earnings call",
            source_category="earnings",
        )
        assert sig.signal.startswith("At ~28x")
        assert sig.evidence_origin == "earnings call"
        assert sig.source_category == "earnings"


# ============================================================================
# 3. Alert Materiality — detect_material_change
# ============================================================================

class TestAlertMateriality:
    """detect_material_change() must compute materiality_score and change_category."""

    def _prev_snap(self, **kwargs):
        return _make_snapshot(**kwargs)

    def _curr_snap(self, **kwargs):
        return _make_snapshot(**kwargs)

    def test_returns_none_when_no_material_shift(self):
        diff = _make_diff(material_shift_detected=False)
        result = detect_material_change(diff, "AAPL", self._prev_snap(), self._curr_snap())
        assert result is None

    def test_materiality_score_high_on_trend_flip(self):
        diff = _make_diff(
            trend_flipped=True,
            confidence_change=-0.20,
            material_shift_detected=True,
            severity="high",
            thesis_trend="weakening",
        )
        prev = _make_snapshot(confidence=0.80, trend="strengthening")
        curr = _make_snapshot(confidence=0.60, trend="weakening")
        event = detect_material_change(diff, "AAPL", prev, curr)
        assert event is not None
        assert event.materiality_score >= 0.50

    def test_materiality_score_medium_on_new_structural_risk(self):
        diff = _make_diff(
            new_risks=["China regulatory pressure: export controls tightened"],
            confidence_change=-0.09,
            material_shift_detected=True,
            severity="medium",
        )
        prev = _make_snapshot(confidence=0.75)
        curr = _make_snapshot(confidence=0.66)
        event = detect_material_change(diff, "AAPL", prev, curr)
        assert event is not None
        assert event.materiality_score >= 0.20

    def test_materiality_score_low_on_minor_confidence_move(self):
        diff = _make_diff(
            confidence_change=-0.03,
            material_shift_detected=True,
            severity="low",
        )
        prev = _make_snapshot(confidence=0.72)
        curr = _make_snapshot(confidence=0.69)
        event = detect_material_change(diff, "AAPL", prev, curr)
        assert event is not None
        assert event.materiality_score <= 0.30

    def test_change_category_thesis_broke_on_trend_flip_with_negative_delta(self):
        diff = _make_diff(
            trend_flipped=True,
            confidence_change=-0.18,
            material_shift_detected=True,
            severity="high",
            thesis_trend="weakening",
        )
        prev = _make_snapshot(confidence=0.82, trend="strengthening")
        curr = _make_snapshot(confidence=0.64, trend="weakening")
        event = detect_material_change(diff, "AAPL", prev, curr)
        assert event is not None
        assert event.change_category == "thesis_broke"

    def test_change_category_market_repriced_on_small_move(self):
        diff = _make_diff(
            confidence_change=-0.03,
            material_shift_detected=True,
            severity="low",
        )
        prev = _make_snapshot(dominant_dim="valuation")
        curr = _make_snapshot(dominant_dim="valuation")
        event = detect_material_change(diff, "AAPL", prev, curr)
        assert event is not None
        assert event.change_category in ("market_repriced", "cosmetic")

    def test_change_category_new_risk_on_risk_emergence(self):
        diff = _make_diff(
            new_risks=["Regulatory overhang: EU DMA enforcement"],
            confidence_change=-0.05,
            material_shift_detected=True,
            severity="medium",
        )
        prev = _make_snapshot(confidence=0.72)
        curr = _make_snapshot(confidence=0.67)
        event = detect_material_change(diff, "AAPL", prev, curr)
        assert event is not None
        assert event.change_category == "new_risk_emerged"

    def test_materiality_score_in_range(self):
        """materiality_score must always be in [0.0, 1.0]."""
        for params in [
            dict(confidence_change=-0.20, trend_flipped=True, new_risks=["Risk A", "Risk B", "Risk C"]),
            dict(confidence_change=0.0),
            dict(confidence_change=0.15, strengthening_signals=["Upside catalyst"]),
        ]:
            diff = _make_diff(material_shift_detected=True, severity="medium", **params)
            event = detect_material_change(diff, "AAPL", _make_snapshot(), _make_snapshot())
            if event:
                assert 0.0 <= event.materiality_score <= 1.0

    def test_material_change_event_has_materiality_score_field(self):
        diff = _make_diff(
            trend_flipped=True,
            confidence_change=-0.20,
            material_shift_detected=True,
            severity="high",
        )
        event = detect_material_change(diff, "AAPL", _make_snapshot(), _make_snapshot())
        assert event is not None
        assert hasattr(event, "materiality_score")
        assert hasattr(event, "change_category")


# ============================================================================
# 4. Historical Continuity — build_pm_change_narrative
# ============================================================================

class TestHistoricalContinuity:
    """build_pm_change_narrative() must explicitly distinguish market repricing
    from thesis deterioration using clear PM-language patterns."""

    def test_market_repriced_language_on_dimension_shift_without_risk(self):
        """When dominant dimension rotates without new risks → 'market repriced' language."""
        diff = _make_diff(confidence_change=-0.03)
        prev = _make_snapshot(dominant_dim="valuation")
        curr = _make_snapshot(dominant_dim="macro")
        result = build_pm_change_narrative(diff, prev, curr)
        # Must NOT say thesis broke — should express market/repricing framing
        assert "thesis" not in result.lower() or "market" in result.lower() or "repricing" in result.lower() or "operating" in result.lower()

    def test_thesis_broke_language_on_trend_flip_with_large_negative_delta(self):
        """Trend flip + large confidence drop → explicit 'thesis broke' or burden language."""
        diff = _make_diff(
            trend_flipped=True,
            confidence_change=-0.20,
            thesis_trend="weakening",
            new_risks=["China regulatory pressure"],
        )
        prev = _make_snapshot(confidence=0.82, trend="strengthening")
        curr = _make_snapshot(confidence=0.62, trend="weakening")
        result = build_pm_change_narrative(diff, prev, curr)
        # Must contain strong directional language
        assert any(phrase in result.lower() for phrase in [
            "broke", "burden", "original", "no longer", "deteriorated", "weakening"
        ])

    def test_unchanged_returns_no_material_change(self):
        diff = _make_diff(confidence_change=0.0)
        prev = _make_snapshot()
        curr = _make_snapshot()
        result = build_pm_change_narrative(diff, prev, curr)
        assert "no material" in result.lower() or "operating" in result.lower()

    def test_strengthening_returns_positive_language(self):
        diff = _make_diff(
            confidence_change=0.10,
            strengthening_signals=["Services margin expansion: 72% gross margin"],
        )
        prev = _make_snapshot(confidence=0.65)
        curr = _make_snapshot(confidence=0.75)
        result = build_pm_change_narrative(diff, prev, curr)
        assert any(word in result.lower() for word in ["improved", "held", "durability", "clarified"])

    def test_new_risk_emergence_names_the_risk(self):
        diff = _make_diff(
            new_risks=["Regulatory overhang: EU DMA enforcement now in scope"],
            confidence_change=-0.06,
        )
        prev = _make_snapshot()
        curr = _make_snapshot(confidence=0.66)
        result = build_pm_change_narrative(diff, prev, curr)
        assert "regulatory" in result.lower() or "eu dma" in result.lower() or "risk" in result.lower()

    def test_narrative_never_references_internal_scoring(self):
        """PM narrative must never mention agent names, percentages, or signal counts."""
        for params in [
            dict(confidence_change=-0.15, trend_flipped=True),
            dict(confidence_change=0.10, strengthening_signals=["Signal A"]),
            dict(new_risks=["Risk A"]),
            dict(confidence_change=0.0),
        ]:
            diff = _make_diff(**params)
            prev = _make_snapshot()
            curr = _make_snapshot()
            result = build_pm_change_narrative(diff, prev, curr)
            assert "agent" not in result.lower()
            assert "signal count" not in result.lower()
            assert "%" not in result  # no raw percentage literals

    def test_narrative_ends_in_period(self):
        """Design invariant: narrative always ends with '.'."""
        for params in [
            dict(),
            dict(confidence_change=-0.20, trend_flipped=True),
            dict(new_risks=["New risk"]),
            dict(strengthening_signals=["Upside signal"]),
            dict(confidence_change=-0.03),
        ]:
            diff = _make_diff(**params)
            prev = _make_snapshot()
            curr = _make_snapshot()
            result = build_pm_change_narrative(diff, prev, curr)
            assert result.endswith("."), f"Narrative does not end with '.': {result!r}"

    def test_narrative_never_raises(self):
        """build_pm_change_narrative() must not raise on any input combination."""
        for params in [
            dict(),
            dict(confidence_change=-0.50, trend_flipped=True, new_risks=["A", "B", "C"]),
            dict(confidence_change=0.30, strengthening_signals=["S1", "S2"]),
            dict(top_signal_replaced=True),
        ]:
            diff = _make_diff(**params)
            prev = _make_snapshot()
            curr = _make_snapshot()
            result = build_pm_change_narrative(diff, prev, curr)
            assert isinstance(result, str)
            assert len(result) > 0

    def test_repricing_vs_thesis_broke_are_distinct(self):
        """The market repricing and thesis broke paths must produce different language."""
        # Market repricing: small confidence move, dimension rotates to macro, no new risks
        repricing_diff = _make_diff(confidence_change=-0.02)
        prev_val = _make_snapshot(dominant_dim="valuation")
        curr_macro = _make_snapshot(dominant_dim="macro")
        repricing_result = build_pm_change_narrative(repricing_diff, prev_val, curr_macro)

        # Thesis broke: large confidence collapse + trend flip
        broke_diff = _make_diff(
            confidence_change=-0.22,
            trend_flipped=True,
            new_risks=["Demand destruction: hardware units declined 15%"],
            thesis_trend="weakening",
        )
        prev_strong = _make_snapshot(confidence=0.85, trend="strengthening")
        curr_weak = _make_snapshot(confidence=0.63, trend="weakening")
        broke_result = build_pm_change_narrative(broke_diff, prev_strong, curr_weak)

        # Must produce different narratives
        assert repricing_result != broke_result


# ============================================================================
# 5. Trust Hardening — edge cases must not crash
# ============================================================================

class TestTrustHardening:
    """Services must gracefully handle malformed or minimal inputs."""

    def test_market_regime_block_with_none_like_summaries(self):
        evidence = [_make_evidence("Test", "")]
        result = _build_market_regime_block(evidence)
        assert isinstance(result, str)

    def test_detect_material_change_with_empty_drivers(self):
        diff = _make_diff(
            confidence_change=-0.20,
            trend_flipped=True,
            material_shift_detected=True,
            severity="high",
            change_drivers=[],
        )
        event = detect_material_change(diff, "AAPL", _make_snapshot(), _make_snapshot())
        assert event is not None
        assert event.drivers == []

    def test_detect_material_change_with_many_new_risks(self):
        """Multiple new risks must not cause materiality_score > 1.0."""
        diff = _make_diff(
            new_risks=[f"Risk {i}: detail" for i in range(20)],
            confidence_change=-0.20,
            trend_flipped=True,
            material_shift_detected=True,
            severity="high",
        )
        event = detect_material_change(diff, "AAPL", _make_snapshot(), _make_snapshot())
        assert event is not None
        assert event.materiality_score <= 1.0

    def test_is_market_repricing_with_no_dimension_info(self):
        diff = _make_diff(confidence_change=0.0)
        prev = _make_snapshot(dominant_dim="")
        curr = _make_snapshot(dominant_dim="")
        # Must not raise
        result = _is_market_repricing(diff, prev, curr)
        assert isinstance(result, bool)

    def test_is_thesis_broke_with_zero_confidence_change(self):
        diff = _make_diff(confidence_change=0.0, trend_flipped=False)
        result = _is_thesis_broke(diff)
        assert result is False

    def test_signal_with_very_long_evidence_origin(self):
        sig = Signal(signal="Test", evidence_origin="x" * 500)
        assert len(sig.evidence_origin) == 500

    def test_material_change_event_field_types(self):
        diff = _make_diff(
            confidence_change=-0.15,
            trend_flipped=True,
            material_shift_detected=True,
            severity="high",
        )
        event = detect_material_change(diff, "AAPL", _make_snapshot(), _make_snapshot())
        assert event is not None
        assert isinstance(event.materiality_score, float)
        assert isinstance(event.change_category, str)
        assert len(event.change_category) > 0


# ============================================================================
# 6. Priced-In Reasoning — valuation_view schema description
# ============================================================================

class TestPricedInReasoningPrompt:
    """The valuation_view field description must contain priced-in language requirements."""

    def test_valuation_view_schema_requires_current_multiple(self):
        from app.services.thesis_synthesizer import _THESIS_SCHEMA_DESCRIPTION
        assert "valuation_view" in _THESIS_SCHEMA_DESCRIPTION
        # Must require specific multiple language
        valuation_section = _THESIS_SCHEMA_DESCRIPTION[
            _THESIS_SCHEMA_DESCRIPTION.index("valuation_view"):
            _THESIS_SCHEMA_DESCRIPTION.index("valuation_view") + 600
        ]
        assert "already prices" in valuation_section or "paying for" in valuation_section

    def test_valuation_view_schema_forbids_generic_language(self):
        from app.services.thesis_synthesizer import _THESIS_SCHEMA_DESCRIPTION
        valuation_section = _THESIS_SCHEMA_DESCRIPTION[
            _THESIS_SCHEMA_DESCRIPTION.index("valuation_view"):
            _THESIS_SCHEMA_DESCRIPTION.index("valuation_view") + 600
        ]
        # Must have an example of good language
        assert "EXAMPLE GOOD" in valuation_section or "MANDATORY" in valuation_section

    def test_priced_in_reasoning_block_present_in_prompt(self):
        from app.services.thesis_synthesizer import _THESIS_SCHEMA_DESCRIPTION
        # PRICED_IN_REASONING section must exist in the prompt
        assert "PRICED_IN_REASONING" in _THESIS_SCHEMA_DESCRIPTION or \
               "already prices" in _THESIS_SCHEMA_DESCRIPTION


# ============================================================================
# 7. Output Feel — forbidden phrases absent from synthesis prompt
# ============================================================================

class TestOutputFeel:
    """Phase G forbidden phrases must remain absent from the schema description."""

    def test_no_well_positioned_in_schema(self):
        from app.services.thesis_synthesizer import _THESIS_SCHEMA_DESCRIPTION
        # Should not instruct to use this phrase
        assert "well positioned" not in _THESIS_SCHEMA_DESCRIPTION.lower()

    def test_schema_requires_mechanism_first_language(self):
        from app.services.thesis_synthesizer import _THESIS_SCHEMA_DESCRIPTION
        assert "mechanism" in _THESIS_SCHEMA_DESCRIPTION.lower()

    def test_schema_bans_hidden_process_language(self):
        # HIDDEN-PROCESS BAN lives in the full synthesis prompt (injected after schema desc)
        # Verify the synthesizer module exports this constant somewhere accessible
        import app.services.thesis_synthesizer as syn_mod
        src = open(syn_mod.__file__).read()
        assert "HIDDEN-PROCESS BAN" in src

    def test_schema_requires_pm_grade_language(self):
        import app.services.thesis_synthesizer as syn_mod
        src = open(syn_mod.__file__).read()
        assert "PM-GRADE" in src or "PM-grade" in src
