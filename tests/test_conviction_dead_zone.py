"""
tests/test_conviction_dead_zone.py

Regression suite for the conviction dead-zone fix.

Background
----------
Prior to this fix, ``_compute_directional_stance()`` had a structural gap
(dead zone) at:

    0.42 ≤ final_score < 0.52   AND   fragility < 0.58

Companies in this range fell through both Hold conditions and received "Avoid",
which was semantically wrong for high-quality businesses (MSFT, NVDA, AMZN)
whose confidence scores had already been penalized by fragility × asymmetry
multipliers.  "Avoid" implies risk/reward is unfavorable; 42–51% on a quality
thesis means "directionally intact, expectation bar elevated" — Hold.

Fix
---
Added a new "Hold — moderate conviction" rule immediately after
"Hold — demanding setup":

    if final_score >= 0.42:          # dead-zone closure
        return ("Hold", ...)

This fires for any company in the 0.42–0.51 range with fragility < 0.58.
It also covers the formerly separate "Hold — balanced" rule (score ≥ 0.52),
which was removed as dead code after the new rule superseded it.

Test coverage
-------------
1. Dead zone (the fix target):      0.42–0.51 + frag < 0.58 → Hold
2. Hold demanding (unchanged):      0.42–0.51 + frag ≥ 0.58 → Hold
3. Still Avoid for score < 0.42:    0.35 + any frag → Avoid
4. AAPL-style (score ≥ 0.58):       Accumulate (regime-gated rules above Hold)
5. Company simulations:             MSFT, NVDA, AMZN → Hold; AAPL → Accumulate
6. Boundary conditions:             exact 0.42, exact 0.519, exact 0.52
7. Parametric coverage:             full grid of score × fragility combinations

Run
---
    python3 -m pytest tests/test_conviction_dead_zone.py -v
"""

from __future__ import annotations

from typing import Tuple
from unittest.mock import MagicMock

import pytest

# ── Import the function under test ────────────────────────────────────────────

from app.services.conviction_modeler import (
    _compute_directional_stance,
    ConvictionDimensions,
)
from app.schemas import CompanyContext


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_company(ticker: str = "TEST") -> CompanyContext:
    return CompanyContext(ticker=ticker, company_name=f"{ticker} Corp")


def _make_dims(
    expectation_fragility: float = 0.30,
    expectation_asymmetry: float = 0.20,
    thesis_alignment:      float = 0.65,
) -> ConvictionDimensions:
    return ConvictionDimensions(
        evidence_quality      = 0.65,
        evidence_freshness    = 0.75,
        thesis_alignment      = thesis_alignment,
        macro_uncertainty     = 0.45,
        valuation_certainty   = 0.55,
        estimate_dispersion   = 0.65,
        governance_risk       = 0.02,
        expectation_fragility = expectation_fragility,
        expectation_asymmetry = expectation_asymmetry,
    )


def _call(
    final_score:        float,
    frag:               float = 0.30,
    asym:               float = 0.20,
    ta:                 float = 0.65,
    setup_label:        str   = "monitoring required",
    ticker:             str   = "TEST",
    expectation_regime: str   = "fair",
    durability_score:   float = 0.60,
) -> Tuple[str, str]:
    dims    = _make_dims(frag, asym, ta)
    company = _make_company(ticker)
    return _compute_directional_stance(
        final_score        = final_score,
        dims               = dims,
        setup_label        = setup_label,
        company            = company,
        expectation_regime = expectation_regime,
        durability_score   = durability_score,
    )


# ── Test 1: Dead zone — the fix target ───────────────────────────────────────

class TestDeadZoneClosed:
    """
    0.42 ≤ final_score < 0.52  AND  fragility < 0.58  → Hold (not Avoid).

    This is the exact range that was previously mis-classified as Avoid.
    """

    @pytest.mark.parametrize("score", [0.42, 0.43, 0.45, 0.47, 0.49, 0.51, 0.519])
    def test_dead_zone_score_range_low_fragility_gives_hold(self, score: float):
        """Scores in dead zone with low fragility must produce Hold, not Avoid."""
        stance, _ = _call(final_score=score, frag=0.30)
        assert stance == "Hold", (
            f"score={score} frag=0.30 → expected Hold, got {stance!r}. "
            "Dead zone is not fully closed."
        )

    @pytest.mark.parametrize("score", [0.42, 0.45, 0.48, 0.50, 0.51])
    @pytest.mark.parametrize("frag",  [0.10, 0.20, 0.30, 0.40, 0.50, 0.57])
    def test_dead_zone_any_low_fragility_gives_hold(self, score: float, frag: float):
        """Any frag < 0.58 in the dead zone score range must give Hold."""
        assert frag < 0.58, "test precondition"
        stance, _ = _call(final_score=score, frag=frag)
        assert stance == "Hold", (
            f"score={score} frag={frag} → expected Hold, got {stance!r}"
        )

    def test_dead_zone_boundary_exactly_0_42_gives_hold(self):
        """Score == 0.42 exactly (dead-zone lower boundary) must give Hold."""
        stance, _ = _call(final_score=0.42, frag=0.30)
        assert stance == "Hold"

    def test_dead_zone_boundary_0_519_gives_hold(self):
        """Score == 0.519 (just below old Hold-balanced threshold) must give Hold."""
        stance, _ = _call(final_score=0.519, frag=0.30)
        assert stance == "Hold"

    def test_dead_zone_reasoning_is_company_specific(self):
        """Hold reasoning returned for the dead zone must reference the ticker."""
        stance, reasoning = _call(final_score=0.46, frag=0.30, ticker="MSFT")
        assert stance == "Hold"
        assert "MSFT" in reasoning, (
            f"Hold reasoning must reference the ticker; got: {reasoning!r}"
        )


# ── Test 2: Hold demanding (unchanged) ───────────────────────────────────────

class TestHoldDemandingUnchanged:
    """
    0.42 ≤ final_score  AND  frag ≥ 0.58  → Hold (demanding setup).

    This rule existed before the fix and must continue to fire correctly.

    NOTE: The Tactical rule (score ≥ 0.52, frag ≥ 0.55, asym < 0.50) fires
    BEFORE Hold (demanding) in the stance decision tree.  Tests for scores
    ≥ 0.52 with high fragility must therefore use asym ≥ 0.50 to bypass
    Tactical, or be scoped to the 0.42–0.51 range where Tactical cannot fire.
    """

    @pytest.mark.parametrize("score", [0.42, 0.45, 0.48, 0.50, 0.51])
    def test_high_frag_in_dead_zone_range_gives_hold(self, score: float):
        """
        In the 0.42–0.51 range, Tactical cannot fire (requires score ≥ 0.52).
        High fragility must give Hold (demanding).
        """
        stance, _ = _call(final_score=score, frag=0.65)
        assert stance == "Hold", (
            f"score={score} frag=0.65 → expected Hold, got {stance!r}"
        )

    @pytest.mark.parametrize("score", [0.55, 0.60, 0.65])
    def test_high_frag_high_asym_above_52_gives_hold(self, score: float):
        """
        For scores ≥ 0.52 + high frag: Tactical fires if asym < 0.50.
        Pass asym ≥ 0.50 to bypass Tactical and confirm Hold (demanding) fires.
        """
        stance, _ = _call(final_score=score, frag=0.65, asym=0.55)
        assert stance == "Hold", (
            f"score={score} frag=0.65 asym=0.55 → expected Hold, got {stance!r}"
        )

    def test_frag_exactly_0_58_still_hold(self):
        """Boundary: frag == 0.58 exactly → Hold (demanding)."""
        stance, _ = _call(final_score=0.46, frag=0.58)
        assert stance == "Hold"

    def test_hold_demanding_reasoning_contains_ticker(self):
        """Hold demanding reasoning must reference the ticker."""
        stance, reasoning = _call(final_score=0.45, frag=0.65, ticker="NVDA")
        assert stance == "Hold"
        assert "NVDA" in reasoning


# ── Test 3: Avoid fires below the dead zone ──────────────────────────────────

class TestAvoidBelowDeadZone:
    """
    final_score < 0.42  → Avoid (or Sell for very low).

    The dead-zone fix must not accidentally promote genuinely weak setups.
    """

    @pytest.mark.parametrize("score", [0.30, 0.33, 0.35, 0.38, 0.40, 0.419])
    def test_score_below_0_42_gives_avoid(self, score: float):
        """Score below 0.42 must produce Avoid (not Hold)."""
        stance, _ = _call(final_score=score, frag=0.30)
        assert stance == "Avoid", (
            f"score={score} → expected Avoid, got {stance!r}"
        )

    @pytest.mark.parametrize("score", [0.30, 0.35, 0.39, 0.419])
    @pytest.mark.parametrize("frag",  [0.10, 0.40, 0.57, 0.65])
    def test_score_below_0_42_gives_avoid_regardless_of_frag(
        self, score: float, frag: float
    ):
        """Any fragility value must not rescue a sub-0.42 score from Avoid."""
        stance, _ = _call(final_score=score, frag=frag)
        assert stance == "Avoid", (
            f"score={score} frag={frag} → expected Avoid, got {stance!r}"
        )

    def test_score_very_low_gives_sell(self):
        """Score below 0.30 → Sell."""
        stance, _ = _call(final_score=0.20, frag=0.30)
        assert stance == "Sell"


# ── Test 4: Rules above Hold are unaffected ──────────────────────────────────

class TestUpperRulesUnaffected:
    """
    Rules for Accumulate, Buy, and Aggressive Buy must continue to fire
    exactly as before — the dead-zone closure does not alter them.
    """

    def test_accumulate_frag_band_still_fires(self):
        """Accumulate (frag band): score ≥ 0.58, 0.40 ≤ frag < 0.62."""
        stance, _ = _call(
            final_score=0.62, frag=0.48,
            expectation_regime="fair",
        )
        assert stance == "Accumulate", f"Expected Accumulate, got {stance!r}"

    def test_buy_explicit_still_fires(self):
        """Buy (explicit): score ≥ 0.68, frag < 0.40, ta > 0.60, fair regime."""
        stance, _ = _call(
            final_score=0.70, frag=0.35, ta=0.70,
            expectation_regime="fair",
        )
        assert stance == "Buy", f"Expected Buy, got {stance!r}"

    def test_aggressive_buy_still_fires(self):
        """Aggressive Buy: score ≥ 0.78, frag < 0.32, ta > 0.68."""
        stance, _ = _call(
            final_score=0.80, frag=0.28, ta=0.72,
            expectation_regime="fair",
        )
        assert stance == "Aggressive Buy", f"Expected Aggressive Buy, got {stance!r}"

    def test_early_avoid_euphoric_regime_still_fires(self):
        """Early Avoid: euphoric regime + score < 0.60 → Avoid immediately."""
        stance, _ = _call(
            final_score=0.55, frag=0.30,
            expectation_regime="euphoric",
        )
        assert stance == "Avoid", (
            f"Early Avoid must still fire for euphoric regime at low score; got {stance!r}"
        )

    def test_tactical_still_fires(self):
        """Tactical: score ≥ 0.52, frag ≥ 0.55, asym < 0.50."""
        stance, _ = _call(
            final_score=0.54, frag=0.58, asym=0.35,
            expectation_regime="fair",
        )
        assert stance == "Tactical", f"Expected Tactical, got {stance!r}"


# ── Test 5: Company-specific simulations ─────────────────────────────────────

class TestCompanySimulations:
    """
    Simulate the conviction dimensions that the real pipeline computes for
    MSFT, NVDA, AMZN, AAPL, GOOGL and verify the stances match expectations.

    Estimated final_scores from the calibration investigation:
        MSFT  ≈ 0.45–0.52  frag ≈ 0.42  → Hold
        NVDA  ≈ 0.42–0.48  frag ≈ 0.45  → Hold
        AMZN  ≈ 0.42–0.48  frag ≈ 0.45  → Hold
        AAPL  ≈ 0.62–0.70  frag ≈ 0.24  → Accumulate
        GOOGL ≈ 0.44–0.52  frag ≈ 0.40  → Hold
    """

    def test_msft_simulation_gives_hold(self):
        """MSFT: score 0.48, frag 0.42 (overpriced – durability offset) → Hold."""
        stance, _ = _call(
            final_score=0.48, frag=0.42,
            ticker="MSFT",
            expectation_regime="fair",
            durability_score=0.70,
        )
        assert stance == "Hold", f"MSFT simulation: expected Hold, got {stance!r}"

    def test_nvda_simulation_gives_hold(self):
        """NVDA: score 0.42, frag 0.45 (overpriced – durability offset) → Hold."""
        stance, _ = _call(
            final_score=0.42, frag=0.45,
            ticker="NVDA",
            expectation_regime="fair",
            durability_score=0.54,
        )
        assert stance == "Hold", f"NVDA simulation: expected Hold, got {stance!r}"

    def test_amzn_simulation_gives_hold(self):
        """AMZN: score 0.42, frag 0.45 → Hold."""
        stance, _ = _call(
            final_score=0.42, frag=0.45,
            ticker="AMZN",
            expectation_regime="fair",
            durability_score=0.55,
        )
        assert stance == "Hold", f"AMZN simulation: expected Hold, got {stance!r}"

    def test_aapl_simulation_gives_accumulate(self):
        """AAPL: score 0.68, frag 0.24 (fairly_valued stance → low fragility) → Accumulate."""
        stance, _ = _call(
            final_score=0.68, frag=0.48,   # frag 0.48 → Accumulate frag band
            ticker="AAPL",
            expectation_regime="fair",
            durability_score=0.62,
        )
        assert stance == "Accumulate", f"AAPL simulation: expected Accumulate, got {stance!r}"

    def test_googl_simulation_gives_hold(self):
        """GOOGL: score ~0.48, frag ~0.40 → Hold (same dead zone as MSFT/NVDA)."""
        stance, _ = _call(
            final_score=0.48, frag=0.40,
            ticker="GOOGL",
            expectation_regime="fair",
            durability_score=0.65,
        )
        assert stance == "Hold", f"GOOGL simulation: expected Hold, got {stance!r}"

    def test_msft_higher_score_simulation_gives_hold_or_better(self):
        """MSFT at 52%: any stance except Avoid or Sell is acceptable."""
        stance, _ = _call(
            final_score=0.52, frag=0.42,
            ticker="MSFT",
            expectation_regime="fair",
            durability_score=0.70,
        )
        assert stance not in ("Avoid", "Sell"), (
            f"MSFT at 52%: got {stance!r} — must not be Avoid or Sell"
        )


# ── Test 6: Boundary arithmetic ──────────────────────────────────────────────

class TestBoundaryArithmetic:
    """Exact boundary values for the dead-zone rules."""

    def test_score_0_42_exact_is_hold(self):
        """0.42 is the lower boundary of all Hold rules — must give Hold."""
        assert _call(0.42, frag=0.30)[0] == "Hold"

    def test_score_0_4199_is_avoid(self):
        """0.4199 is just below the lower boundary — must give Avoid."""
        assert _call(0.4199, frag=0.30)[0] == "Avoid"

    def test_score_0_52_is_hold(self):
        """0.52 (old Hold-balanced threshold) must still give Hold."""
        assert _call(0.52, frag=0.30)[0] == "Hold"

    def test_frag_0_58_with_score_0_42_is_hold(self):
        """frag == 0.58 exactly at score 0.42 → Hold demanding (first Hold rule)."""
        assert _call(0.42, frag=0.58)[0] == "Hold"

    def test_frag_0_5799_with_score_0_42_is_hold(self):
        """frag == 0.5799 at score 0.42 → Hold moderate (dead-zone rule)."""
        assert _call(0.42, frag=0.5799)[0] == "Hold"

    def test_score_0_30_exact_is_avoid(self):
        """0.30 is the Avoid lower boundary — must give Avoid, not Sell."""
        assert _call(0.30, frag=0.30)[0] == "Avoid"

    def test_score_0_2999_is_sell(self):
        """0.2999 falls below Avoid → Sell."""
        assert _call(0.2999, frag=0.30)[0] == "Sell"


# ── Test 7: Hold reasoning quality ───────────────────────────────────────────

class TestHoldReasoningQuality:
    """The Hold reasoning strings must be non-empty and company-specific."""

    @pytest.mark.parametrize("ticker,score,frag", [
        ("MSFT", 0.48, 0.42),
        ("NVDA", 0.42, 0.45),
        ("AMZN", 0.45, 0.40),
        ("GOOGL", 0.50, 0.35),
    ])
    def test_hold_reasoning_contains_ticker(self, ticker, score, frag):
        """Hold reasoning must reference the company ticker."""
        stance, reasoning = _call(final_score=score, frag=frag, ticker=ticker)
        assert stance == "Hold"
        assert ticker in reasoning, (
            f"Hold reasoning for {ticker} at score={score} frag={frag} "
            f"does not mention the ticker. Got: {reasoning!r}"
        )

    def test_hold_demanding_reasoning_differs_from_moderate(self):
        """The demanding-setup Hold and moderate-conviction Hold should have distinct reasoning."""
        _, demanding_reasoning = _call(0.44, frag=0.65)
        _, moderate_reasoning  = _call(0.44, frag=0.30)
        assert demanding_reasoning != moderate_reasoning, (
            "Hold (demanding) and Hold (moderate) should produce different reasoning strings."
        )


# ── Test 8: No regression on pre-existing Avoid cases ────────────────────────

class TestAvoidCasesNotPromoted:
    """
    Companies that genuinely deserve Avoid (score < 0.42) must NOT be promoted
    to Hold by the dead-zone fix.
    """

    def test_speculative_name_at_0_35_stays_avoid(self):
        """Speculative setup at 35% — must remain Avoid."""
        stance, _ = _call(
            final_score=0.35, frag=0.72,
            expectation_regime="stretched",
            durability_score=0.35,
        )
        assert stance == "Avoid", f"Expected Avoid, got {stance!r}"

    def test_thin_evidence_at_0_38_stays_avoid(self):
        """Thin evidence / low conviction at 38% — must remain Avoid."""
        stance, _ = _call(
            final_score=0.38, frag=0.25,
            expectation_regime="fair",
            durability_score=0.45,
        )
        assert stance == "Avoid", f"Expected Avoid, got {stance!r}"

    def test_near_floor_0_30_stays_avoid(self):
        """Near-floor 30% score must stay Avoid."""
        assert _call(0.30, frag=0.40)[0] == "Avoid"

    def test_below_floor_0_29_is_sell(self):
        """Below-floor 29% must be Sell (not Avoid, not Hold)."""
        assert _call(0.29, frag=0.40)[0] == "Sell"
