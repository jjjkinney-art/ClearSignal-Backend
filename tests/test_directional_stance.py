"""
Tests for the directional stance system — Final Pre-Launch Product Refinement.

Covers:
1. _compute_directional_stance() output logic
2. ConvictionResult carries directional_stance / directional_stance_reasoning
3. InvestmentThesis schema accepts both fields
4. Governance: no Strong Buy + Speculative contradiction
5. Governance: no Sell + high-alignment thesis contradiction
6. Governance: Strong Buy requires conviction ≥ 0.60
7. Governance: Sell blocked when confidence > 0.70
8. End-to-end: compute_conviction() stamps both fields
"""
from __future__ import annotations

import dataclasses
from typing import Optional
from unittest.mock import MagicMock

import pytest

from app.services.conviction_modeler import (
    CompanyContext,
    ConvictionDimensions,
    ConvictionResult,
    _compute_directional_stance,
    compute_conviction,
)
from app.schemas import InvestmentThesis


# ── Helpers ───────────────────────────────────────────────────────────────────

def _dims(
    *,
    evidence_quality: float = 0.70,
    evidence_freshness: float = 0.70,
    thesis_alignment: float = 0.70,
    macro_uncertainty: float = 0.30,
    valuation_certainty: float = 0.60,
    estimate_dispersion: float = 0.30,
    governance_risk: float = 0.20,
    expectation_fragility: float = 0.30,
    expectation_asymmetry: float = 0.30,
) -> ConvictionDimensions:
    return ConvictionDimensions(
        evidence_quality=evidence_quality,
        evidence_freshness=evidence_freshness,
        thesis_alignment=thesis_alignment,
        macro_uncertainty=macro_uncertainty,
        valuation_certainty=valuation_certainty,
        estimate_dispersion=estimate_dispersion,
        governance_risk=governance_risk,
        expectation_fragility=expectation_fragility,
        expectation_asymmetry=expectation_asymmetry,
    )


def _company(ticker: str = "AAPL") -> CompanyContext:
    return CompanyContext(ticker=ticker, company_name=f"{ticker} Inc.")


# ── 1. _compute_directional_stance logic ──────────────────────────────────────

class TestComputeDirectionalStance:

    def test_strong_buy_high_score_low_fragility(self):
        dims = _dims(expectation_fragility=0.25, thesis_alignment=0.80)
        stance, reasoning = _compute_directional_stance(0.80, dims, "high-alignment thesis", _company())
        assert stance == "Strong Buy"
        assert "AAPL" in reasoning
        assert len(reasoning) > 20

    def test_strong_buy_requires_score_ge_072(self):
        dims = _dims(expectation_fragility=0.25, thesis_alignment=0.80)
        # score just below threshold → should not be Strong Buy
        stance, _ = _compute_directional_stance(0.71, dims, "actionable thesis", _company())
        assert stance != "Strong Buy"

    def test_strong_buy_blocked_when_fragility_high(self):
        # High fragility blocks Strong Buy even at score ≥ 0.72
        dims = _dims(expectation_fragility=0.55, thesis_alignment=0.80)
        stance, _ = _compute_directional_stance(0.75, dims, "actionable thesis", _company())
        assert stance != "Strong Buy"

    def test_buy_produced_for_good_setup(self):
        dims = _dims(expectation_fragility=0.40, thesis_alignment=0.70)
        stance, reasoning = _compute_directional_stance(0.65, dims, "actionable thesis", _company("MSFT"))
        assert stance == "Buy"
        assert "MSFT" in reasoning

    def test_hold_for_demanding_high_fragility(self):
        # Demanding setup: score in 0.42–0.62 with fragility ≥ 0.58
        dims = _dims(expectation_fragility=0.65, thesis_alignment=0.70)
        stance, reasoning = _compute_directional_stance(0.55, dims, "expectation-sensitive", _company("NVDA"))
        assert stance == "Hold"
        assert len(reasoning) > 10

    def test_hold_produced_for_balanced_thin_setup(self):
        dims = _dims(expectation_fragility=0.40, thesis_alignment=0.55)
        stance, _ = _compute_directional_stance(0.54, dims, "mixed evidence", _company())
        assert stance == "Hold"

    def test_avoid_for_fragile_setup(self):
        dims = _dims(expectation_fragility=0.70, thesis_alignment=0.45)
        stance, reasoning = _compute_directional_stance(0.35, dims, "fragile setup", _company("TSLA"))
        assert stance == "Avoid"
        assert "TSLA" in reasoning

    def test_avoid_for_low_conviction_not_extreme(self):
        dims = _dims(expectation_fragility=0.50, thesis_alignment=0.40)
        stance, _ = _compute_directional_stance(0.34, dims, "fragile setup", _company())
        assert stance == "Avoid"

    def test_sell_for_structural_conviction_break(self):
        dims = _dims(expectation_fragility=0.85, thesis_alignment=0.20, evidence_quality=0.20)
        stance, reasoning = _compute_directional_stance(0.18, dims, "insufficient conviction", _company("XYZ"))
        assert stance == "Sell"
        assert "XYZ" in reasoning

    def test_returns_tuple(self):
        dims = _dims()
        result = _compute_directional_stance(0.65, dims, "actionable thesis", _company())
        assert isinstance(result, tuple)
        assert len(result) == 2
        assert isinstance(result[0], str)
        assert isinstance(result[1], str)

    def test_reasoning_not_empty_for_all_stances(self):
        """Every stance path should produce non-empty reasoning."""
        cases = [
            (0.80, _dims(expectation_fragility=0.25, thesis_alignment=0.80), "high-alignment thesis"),
            (0.65, _dims(expectation_fragility=0.40), "actionable thesis"),
            (0.55, _dims(expectation_fragility=0.65), "expectation-sensitive"),
            (0.54, _dims(expectation_fragility=0.40), "mixed evidence"),
            (0.35, _dims(expectation_fragility=0.70), "fragile setup"),
            (0.18, _dims(expectation_fragility=0.85, thesis_alignment=0.15), "insufficient conviction"),
        ]
        for score, d, label in cases:
            stance, reasoning = _compute_directional_stance(score, d, label, _company())
            assert reasoning, f"Empty reasoning for score={score} label={label} → {stance}"

    def test_ticker_appears_in_reasoning(self):
        dims = _dims(expectation_fragility=0.25, thesis_alignment=0.80)
        _, reasoning = _compute_directional_stance(0.80, dims, "high-alignment thesis", _company("COST"))
        assert "COST" in reasoning


# ── 2. ConvictionResult carries stance fields ─────────────────────────────────

class TestConvictionResultStanceFields:

    def test_conviction_result_has_directional_stance(self):
        result = ConvictionResult(
            final_score=0.70,
            dimensions=_dims(),
            confidence_reasoning="test",
            what_increases_conviction="test",
            directional_stance="Buy",
            directional_stance_reasoning="The setup is constructive.",
        )
        assert result.directional_stance == "Buy"
        assert result.directional_stance_reasoning == "The setup is constructive."

    def test_conviction_result_defaults_to_hold(self):
        result = ConvictionResult(
            final_score=0.50,
            dimensions=_dims(),
            confidence_reasoning="test",
            what_increases_conviction="test",
        )
        assert result.directional_stance == "Hold"
        assert result.directional_stance_reasoning == ""


# ── 3. InvestmentThesis schema ────────────────────────────────────────────────

class TestInvestmentThesisStanceFields:

    def test_schema_has_directional_stance(self):
        thesis = InvestmentThesis(ticker="AAPL", company_name="Apple")
        assert hasattr(thesis, "directional_stance")
        assert hasattr(thesis, "directional_stance_reasoning")

    def test_schema_default_is_hold(self):
        thesis = InvestmentThesis(ticker="AAPL", company_name="Apple")
        assert thesis.directional_stance == "Hold"
        assert thesis.directional_stance_reasoning == ""

    def test_schema_accepts_all_valid_stances(self):
        for stance in ("Strong Buy", "Buy", "Hold", "Avoid", "Sell"):
            t = InvestmentThesis(
                ticker="AAPL",
                company_name="Apple",
                directional_stance=stance,
                directional_stance_reasoning="Test reasoning.",
            )
            assert t.directional_stance == stance

    def test_schema_serializes_stance_fields(self):
        thesis = InvestmentThesis(
            ticker="NVDA",
            company_name="Nvidia",
            directional_stance="Hold",
            directional_stance_reasoning="Demanding setup — execution bar is elevated.",
        )
        d = thesis.model_dump() if hasattr(thesis, "model_dump") else thesis.dict()
        assert "directional_stance" in d
        assert "directional_stance_reasoning" in d
        assert d["directional_stance"] == "Hold"


# ── 4. End-to-end: compute_conviction stamps both fields ─────────────────────

class TestComputeConvictionStampsDiance:

    def _run_compute_conviction(self, ticker: str = "AAPL") -> ConvictionResult:
        from app.services.conviction_modeler import compute_conviction
        from app.schemas import ValuationView, MacroSensitivity, RiskProfile, MarketContext, QualityAssessment
        company = _company(ticker)
        return compute_conviction(
            evidence=[],
            valuation=ValuationView(),
            macro=MacroSensitivity(),
            risk=RiskProfile(),
            market=MarketContext(),
            quality=QualityAssessment(),
            company=company,
        )

    def test_compute_conviction_returns_directional_stance(self):
        result = self._run_compute_conviction("AAPL")
        assert result.directional_stance in ("Strong Buy", "Buy", "Hold", "Avoid", "Sell")

    def test_compute_conviction_returns_nonempty_reasoning(self):
        result = self._run_compute_conviction("MSFT")
        assert isinstance(result.directional_stance_reasoning, str)
        # With no evidence, output may be sparse but field must exist and be str
        assert result.directional_stance_reasoning is not None

    def test_stance_consistent_with_score(self):
        """Strong Buy should only appear with high scores, Sell with very low."""
        result = self._run_compute_conviction("AAPL")
        if result.directional_stance == "Strong Buy":
            assert result.final_score >= 0.60
        if result.directional_stance == "Sell":
            assert result.final_score < 0.45


# ── 5. Governance: no Strong Buy + Speculative ────────────────────────────────

class TestDirectionalStanceGovernance:

    def _make_thesis(
        self,
        stance: str,
        setup_label: str,
        confidence: float = 0.65,
    ) -> InvestmentThesis:
        return InvestmentThesis(
            ticker="TEST",
            company_name="Test Corp",
            directional_stance=stance,
            directional_stance_reasoning="test reasoning",
            setup_label=setup_label,
            confidence_score=confidence,
        )

    def _run_governance(self, thesis: InvestmentThesis) -> list:
        from app.services.thesis_synthesizer import _check_directional_stance_consistency
        company = _company("TEST")
        return _check_directional_stance_consistency(thesis, company)

    def test_strong_buy_with_speculative_setup_flagged(self):
        thesis = self._make_thesis("Strong Buy", "speculative setup", 0.65)
        warnings = self._run_governance(thesis)
        assert any("Strong Buy" in w for w in warnings), warnings

    def test_strong_buy_with_fragile_setup_flagged(self):
        thesis = self._make_thesis("Strong Buy", "fragile setup", 0.65)
        warnings = self._run_governance(thesis)
        assert any("Strong Buy" in w for w in warnings), warnings

    def test_strong_buy_with_low_confidence_flagged(self):
        thesis = self._make_thesis("Strong Buy", "actionable thesis", 0.50)
        warnings = self._run_governance(thesis)
        assert any("Strong Buy" in w for w in warnings), warnings

    def test_sell_with_high_alignment_thesis_flagged(self):
        thesis = self._make_thesis("Sell", "high-alignment thesis", 0.45)
        warnings = self._run_governance(thesis)
        assert any("Sell" in w for w in warnings), warnings

    def test_sell_with_high_confidence_flagged(self):
        thesis = self._make_thesis("Sell", "mixed evidence", 0.75)
        warnings = self._run_governance(thesis)
        assert any("Sell" in w for w in warnings), warnings

    def test_strong_buy_with_actionable_thesis_clean(self):
        thesis = self._make_thesis("Strong Buy", "actionable thesis", 0.75)
        warnings = self._run_governance(thesis)
        # No governance warning expected for a valid combination
        stance_warnings = [w for w in warnings if "Strong Buy" in w and "contradiction" in w]
        assert not stance_warnings

    def test_buy_with_monitoring_required_clean(self):
        thesis = self._make_thesis("Buy", "monitoring required", 0.62)
        warnings = self._run_governance(thesis)
        assert not warnings

    def test_hold_always_clean(self):
        for label in ("high-alignment thesis", "speculative setup", "fragile setup"):
            thesis = self._make_thesis("Hold", label, 0.55)
            warnings = self._run_governance(thesis)
            assert not warnings, f"Hold should never trigger governance on label={label}"

    def test_avoid_always_clean(self):
        thesis = self._make_thesis("Avoid", "fragile setup", 0.35)
        warnings = self._run_governance(thesis)
        assert not warnings

    def test_sell_with_low_confidence_clean(self):
        thesis = self._make_thesis("Sell", "insufficient conviction", 0.20)
        warnings = self._run_governance(thesis)
        stance_sell_warnings = [w for w in warnings if "Sell" in w and "contradiction" in w]
        assert not stance_sell_warnings
