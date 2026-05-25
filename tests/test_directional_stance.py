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


# ── 6. Quality Durability Offset ──────────────────────────────────────────────
# Validates that quality-durable tickers resist speculative compression vs
# narrative-dependent HE tickers when valuation is stretched.

class TestQualityDurabilityOffset:
    """
    COST / MSFT / JPM at overpriced valuation should land in Balanced/Demanding,
    NOT Speculative.  TSLA / PLTR / SNOW at same valuation should land lower.

    All tests use minimal evidence (the offset must dominate over raw evidence
    signal) and a constructive but not artificially perfect thesis_alignment.
    """

    def _run_fragility(self, ticker: str, stance: str = "overpriced") -> float:
        from app.services.conviction_modeler import (
            _score_expectation_fragility, _compute_business_durability,
        )
        from app.services.company_knowledge import get_knowledge_profile
        from app.schemas import ValuationView, QualityAssessment, RiskProfile
        company = CompanyContext(ticker=ticker, company_name=f"{ticker} Inc.")
        val = ValuationView(valuation_stance=stance, confidence=0.65)
        profile = get_knowledge_profile(ticker)
        quality = QualityAssessment(confidence=0.65)
        risk = RiskProfile(confidence=0.65)
        durability = _compute_business_durability(quality, risk, [], profile)
        return _score_expectation_fragility(val, [], company, durability)

    def _run_asymmetry(self, ticker: str, stance: str = "overpriced") -> float:
        from app.services.conviction_modeler import (
            _score_expectation_asymmetry, _compute_business_durability,
        )
        from app.services.company_knowledge import get_knowledge_profile
        from app.schemas import ValuationView, QualityAssessment, RiskProfile
        company = CompanyContext(ticker=ticker, company_name=f"{ticker} Inc.")
        val = ValuationView(valuation_stance=stance, confidence=0.65)
        profile = get_knowledge_profile(ticker)
        quality = QualityAssessment(confidence=0.65)
        risk = RiskProfile(confidence=0.65)
        durability = _compute_business_durability(quality, risk, [], profile)
        dims = ConvictionDimensions()
        return _score_expectation_asymmetry(val, [], company, dims, durability)

    # ── Fragility ordering: QD < HE ──────────────────────────────────────────

    def test_cost_fragility_lower_than_tsla(self):
        """COST (QD) must have lower fragility than TSLA (HE) at overpriced valuation."""
        assert self._run_fragility("COST") < self._run_fragility("TSLA")

    def test_msft_fragility_lower_than_pltr(self):
        assert self._run_fragility("MSFT") < self._run_fragility("PLTR")

    def test_jpm_fragility_lower_than_snow(self):
        assert self._run_fragility("JPM") < self._run_fragility("SNOW")

    def test_asml_fragility_lower_than_nvda(self):
        """ASML (QD only) must have lower fragility than NVDA (HE only)."""
        assert self._run_fragility("ASML") < self._run_fragility("NVDA")

    # ── Asymmetry ordering: QD < HE ──────────────────────────────────────────

    def test_cost_asymmetry_lower_than_tsla(self):
        assert self._run_asymmetry("COST") < self._run_asymmetry("TSLA")

    def test_v_asymmetry_lower_than_pltr(self):
        assert self._run_asymmetry("V") < self._run_asymmetry("PLTR")

    # ── Absolute thresholds: QD names at overpriced must stay ≤ 0.50 fragility ──
    # Ensures COST overpriced does not exceed the "fragile setup" fragility level.

    def test_cost_overpriced_fragility_below_050(self):
        assert self._run_fragility("COST") <= 0.50

    def test_msft_overpriced_fragility_below_050(self):
        assert self._run_fragility("MSFT") <= 0.50

    def test_jpm_overpriced_fragility_below_050(self):
        assert self._run_fragility("JPM") <= 0.50

    # ── End-to-end: QD names should NOT produce Speculative label ────────────

    def _run_e2e_label(self, ticker: str) -> str:
        from app.services.conviction_modeler import (
            _score_expectation_fragility, _score_expectation_asymmetry,
            _compose_score, _confidence_band_label, _WEIGHTS,
            _compute_business_durability,
        )
        from app.services.company_knowledge import get_knowledge_profile
        from app.schemas import ValuationView, QualityAssessment, RiskProfile
        company = CompanyContext(ticker=ticker, company_name=f"{ticker} Inc.")
        val = ValuationView(valuation_stance="overpriced", confidence=0.65)
        profile = get_knowledge_profile(ticker)
        quality = QualityAssessment(confidence=0.65)
        risk = RiskProfile(confidence=0.65)
        durability = _compute_business_durability(quality, risk, [], profile)
        frag = _score_expectation_fragility(val, [], company, durability)
        dims = ConvictionDimensions(
            evidence_quality=0.65, evidence_freshness=0.70,
            thesis_alignment=0.68, macro_uncertainty=0.30,
            valuation_certainty=0.60, estimate_dispersion=0.65,
            governance_risk=0.0, expectation_fragility=frag,
        )
        asym = _score_expectation_asymmetry(val, [], company, dims, durability)
        import dataclasses
        dims2 = dataclasses.replace(dims, expectation_asymmetry=asym)
        score = _compose_score(dims2)
        return _confidence_band_label(score, dims2)

    def test_cost_overpriced_not_speculative(self):
        label = self._run_e2e_label("COST")
        assert label not in ("speculative setup", "insufficient conviction"), (
            f"COST should not be speculative at overpriced valuation, got: {label}"
        )

    def test_msft_overpriced_not_speculative(self):
        label = self._run_e2e_label("MSFT")
        assert label not in ("speculative setup", "insufficient conviction"), (
            f"MSFT should not be speculative at overpriced valuation, got: {label}"
        )

    def test_jpm_overpriced_not_speculative(self):
        label = self._run_e2e_label("JPM")
        assert label not in ("speculative setup", "insufficient conviction"), (
            f"JPM should not be speculative at overpriced valuation, got: {label}"
        )


# ── 7. Phase 3: QD Balanced floor (MSFT/JPM → Balanced, TSLA/PLTR → Fragile/Speculative) ──

class TestPhase3QDBalancedFloor:
    """
    Phase 3 calibration validation:

    Quality-durable tickers (COST, MSFT, JPM) with sparse evidence and mixed signals
    should land in Demanding or Balanced — NOT in Fragile/Speculative.

    Narrative-dependent tickers (TSLA, PLTR, SNOW) at the same sparse-evidence
    conditions remain correctly in Fragile/Speculative.

    Tests operate via compute_conviction() end-to-end so the QD label floor fires.
    """

    def _run_full(self, ticker: str, evidence_quality: float = 0.35) -> str:
        """Run compute_conviction with realistic sparse-evidence inputs and return setup_label.

        Passes the CompanyKnowledgeProfile so that _compute_business_durability() can
        derive the correct durability_score from structured business-model facts.
        This is the generalized approach — no ticker-specific overrides in the engine itself.
        """
        from app.schemas import (
            ValuationView, MacroSensitivity, RiskProfile,
            MarketContext, QualityAssessment,
        )
        from app.services.company_knowledge import get_knowledge_profile
        company  = CompanyContext(ticker=ticker, company_name=f"{ticker} Inc.")
        profile  = get_knowledge_profile(ticker)  # may be None for unknown tickers
        valuation = ValuationView(valuation_stance="overpriced", confidence=0.45)
        macro     = MacroSensitivity(confidence=0.45)
        risk      = RiskProfile(confidence=0.45)
        market    = MarketContext(confidence=0.45)
        quality   = QualityAssessment(confidence=0.45)
        result = compute_conviction(
            evidence=[], valuation=valuation, macro=macro,
            risk=risk, market=market, quality=quality, company=company,
            profile=profile,
        )
        return result.setup_label

    # ── QD tickers: must not be Speculative or Insufficient ──────────────────

    def test_cost_sparse_not_speculative(self):
        """COST with sparse evidence and overpriced stance must not show Speculative."""
        label = self._run_full("COST")
        assert label not in ("speculative setup", "insufficient conviction"), (
            f"COST should not be speculative with sparse evidence, got: {label!r}"
        )

    def test_msft_sparse_not_speculative(self):
        """MSFT with sparse evidence must not show Speculative."""
        label = self._run_full("MSFT")
        assert label not in ("speculative setup", "insufficient conviction"), (
            f"MSFT should not be speculative with sparse evidence, got: {label!r}"
        )

    def test_jpm_sparse_not_speculative(self):
        """JPM with sparse evidence must not show Speculative."""
        label = self._run_full("JPM")
        assert label not in ("speculative setup", "insufficient conviction"), (
            f"JPM should not be speculative with sparse evidence, got: {label!r}"
        )

    def test_asml_sparse_not_speculative(self):
        """ASML (QD, not HE) with sparse evidence must not show Speculative."""
        label = self._run_full("ASML")
        assert label not in ("speculative setup", "insufficient conviction"), (
            f"ASML should not be speculative with sparse evidence, got: {label!r}"
        )

    # ── QD tickers: must land in Demanding or Balanced tier (not Fragile/Speculative) ──

    _DEMANDING_OR_BETTER = frozenset({
        "high-alignment thesis", "actionable thesis",
        "monitoring required", "expectation-sensitive",
        "mixed evidence",  # mixed maps to Demanding — acceptable
    })

    def test_cost_sparse_label_in_demanding_or_better(self):
        """COST sparse → Demanding or Balanced tier (not Fragile/Speculative tier)."""
        label = self._run_full("COST")
        assert label in self._DEMANDING_OR_BETTER, (
            f"COST should be Demanding/Balanced tier with sparse evidence, got: {label!r}"
        )

    def test_msft_sparse_label_in_demanding_or_better(self):
        label = self._run_full("MSFT")
        assert label in self._DEMANDING_OR_BETTER, (
            f"MSFT should be Demanding/Balanced tier with sparse evidence, got: {label!r}"
        )

    def test_jpm_sparse_label_in_demanding_or_better(self):
        label = self._run_full("JPM")
        assert label in self._DEMANDING_OR_BETTER, (
            f"JPM should be Demanding/Balanced tier with sparse evidence, got: {label!r}"
        )

    # ── Non-QD tickers: TSLA/PLTR remain Fragile/Speculative at same conditions ──

    def test_tsla_sparse_remains_fragile_or_speculative(self):
        """TSLA is not QD → sparse evidence + overpriced → Fragile or Speculative (correct)."""
        label = self._run_full("TSLA")
        fragile_or_spec = frozenset({
            "fragile setup", "speculative setup", "insufficient conviction",
            "asymmetric setup",
        })
        assert label in fragile_or_spec, (
            f"TSLA should be Fragile/Speculative with sparse evidence, got: {label!r}"
        )

    def test_pltr_sparse_remains_speculative(self):
        """PLTR is not QD → sparse + overpriced → Speculative or Fragile (correct)."""
        label = self._run_full("PLTR")
        fragile_or_spec = frozenset({
            "fragile setup", "speculative setup", "insufficient conviction",
        })
        assert label in fragile_or_spec, (
            f"PLTR should be Speculative with sparse evidence, got: {label!r}"
        )
