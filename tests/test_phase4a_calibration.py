"""
tests/test_phase4a_calibration.py

Phase 4A Conviction Calibration — regression tests.

Covers two targeted fixes:

  Fix 1 — Sell catch-all
    Before: any final_score < 0.30 unconditionally returned Sell.
    After:  Sell requires BOTH frag > 0.65 AND ta < 0.35 (positive deterioration
            signal).  Low-confidence companies (XOM-like, SBUX-like) with neutral-
            to-moderate thesis alignment return Avoid instead.

  Fix 2 — Accumulate rule ordering + durability threshold 0.65 → 0.60
    Before: Buy (explicit) evaluated before Accumulate (durable compounder).
            COST/JPM-class names with score ≥ 0.68 went to Buy.
    After:  Accumulate (durable) fires FIRST for durability ≥ 0.60 in non-cheap,
            non-euphoric/bubble regimes.  COST/JPM go to Accumulate.
            Buy is preserved for: durability < 0.60, OR regime == "cheap".

Run:
    python3 -m pytest tests/test_phase4a_calibration.py -v --tb=short
"""
from __future__ import annotations

import pytest

from app.services.conviction_modeler import (
    _compute_directional_stance,
    ConvictionDimensions,
)
from app.schemas import CompanyContext


# ── Helpers ───────────────────────────────────────────────────────────────────

def _dims(
    frag: float = 0.35,
    asym: float = 0.30,
    ta:   float = 0.62,
    eq:   float = 0.72,
    macro_uncertainty: float = 0.40,
) -> ConvictionDimensions:
    return ConvictionDimensions(
        evidence_quality      = eq,
        evidence_freshness    = 0.70,
        thesis_alignment      = ta,
        macro_uncertainty     = macro_uncertainty,
        valuation_certainty   = 0.55,
        estimate_dispersion   = 0.60,
        governance_risk       = 0.05,
        expectation_fragility = frag,
        expectation_asymmetry = asym,
    )


def _run(
    final_score:  float,
    frag:         float = 0.35,
    asym:         float = 0.30,
    ta:           float = 0.62,
    eq:           float = 0.72,
    macro:        float = 0.40,
    durability:   float = 0.50,
    regime:       str   = "fair",
    ticker:       str   = "TEST",
) -> str:
    dims    = _dims(frag=frag, asym=asym, ta=ta, eq=eq, macro_uncertainty=macro)
    company = CompanyContext(ticker=ticker, company_name=f"{ticker} Corp")
    stance, _ = _compute_directional_stance(
        final_score, dims, "actionable thesis", company,
        expectation_regime = regime,
        durability_score   = durability,
    )
    return stance


# ===========================================================================
# FIX 1 — Sell catch-all: low confidence → Avoid, not Sell
# ===========================================================================

class TestFix1SellCatchAll:
    """
    Before Phase 4A: any final_score < 0.30 → Sell (unconditional).
    After Phase 4A:  Sell requires frag > 0.65 AND ta < 0.35.
                     Low-confidence companies with ta ≥ 0.35 → Avoid.
    """

    # ── XOM-like scenario ────────────────────────────────────────────────────
    # Commodity energy: high macro uncertainty drives score below 0.30,
    # but agents have mixed (not unanimously negative) alignment.

    def test_xom_like_low_score_moderate_ta_is_avoid_not_sell(self):
        """XOM-like: score=0.280, frag=0.55, ta=0.50 → Avoid (not Sell)."""
        stance = _run(
            final_score = 0.280,
            frag        = 0.55,
            ta          = 0.50,
            durability  = 0.42,
            regime      = "fair",
            ticker      = "XOM",
        )
        assert stance == "Avoid", (
            f"XOM-like (score=0.280, ta=0.50) should be Avoid after Fix 1; got {stance!r}. "
            "Low confidence with neutral agent alignment is insufficient conviction, not Sell."
        )

    def test_xom_like_with_high_macro_uncertainty_still_avoid(self):
        """Even with extreme macro uncertainty, ta=0.52 blocks Sell → Avoid."""
        stance = _run(
            final_score     = 0.270,
            frag            = 0.62,
            ta              = 0.52,
            macro           = 0.75,
            durability      = 0.40,
            regime          = "fair",
            ticker          = "XOM",
        )
        assert stance == "Avoid", (
            f"XOM with high macro uncertainty but ta=0.52 should be Avoid; got {stance!r}."
        )

    # ── SBUX-like scenario ───────────────────────────────────────────────────
    # Turnaround story: execution risk language elevates fragility/asymmetry,
    # contradiction compression drives score below 0.30.  Agents mixed on
    # recovery timeline → ta in 0.45-0.55 range.

    def test_sbux_like_turnaround_is_avoid_not_sell(self):
        """SBUX-like: score=0.273, frag=0.60, ta=0.48 → Avoid (not Sell)."""
        stance = _run(
            final_score = 0.273,
            frag        = 0.60,
            ta          = 0.48,
            asym        = 0.45,
            durability  = 0.38,
            regime      = "fair",
            ticker      = "SBUX",
        )
        assert stance == "Avoid", (
            f"SBUX-like (score=0.273, ta=0.48) should be Avoid after Fix 1; got {stance!r}. "
            "Turnaround with mixed agent alignment is insufficient conviction, not Sell."
        )

    def test_sbux_like_just_below_avoid_threshold_still_avoid(self):
        """Score=0.22, frag=0.58, ta=0.45 — well below 0.30 but ta > 0.35 → Avoid."""
        stance = _run(
            final_score = 0.220,
            frag        = 0.58,
            ta          = 0.45,
            durability  = 0.38,
            regime      = "fair",
            ticker      = "SBUX",
        )
        assert stance == "Avoid", (
            f"SBUX-like at 0.22 with ta=0.45 should be Avoid; got {stance!r}."
        )

    # ── Genuine Sell still fires ─────────────────────────────────────────────
    # Sell requires BOTH elevated expectations AND decisively negative agents.

    def test_sell_fires_for_structural_conviction_break(self):
        """High frag + very low ta → genuine Sell (structural deterioration)."""
        stance = _run(
            final_score = 0.18,
            frag        = 0.85,
            ta          = 0.20,    # decisively negative agents
            durability  = 0.30,
            regime      = "fair",
            ticker      = "BROKE",
        )
        assert stance == "Sell", (
            f"Score=0.18, frag=0.85, ta=0.20 should be Sell (structural break); got {stance!r}."
        )

    def test_sell_fires_at_frag_066_ta_034(self):
        """Boundary test: frag exactly > 0.65 and ta exactly < 0.35 → Sell."""
        stance = _run(
            final_score = 0.21,
            frag        = 0.66,    # just above threshold
            ta          = 0.34,    # just below threshold
            durability  = 0.25,
            ticker      = "BAD",
        )
        assert stance == "Sell", (
            f"frag=0.66, ta=0.34 should be Sell; got {stance!r}."
        )

    def test_sell_does_not_fire_when_ta_at_threshold(self):
        """ta exactly = 0.35 is NOT < 0.35 — Sell should NOT fire → Avoid."""
        stance = _run(
            final_score = 0.21,
            frag        = 0.80,
            ta          = 0.35,    # exactly at threshold, not below
            durability  = 0.25,
            ticker      = "EDGE",
        )
        assert stance == "Avoid", (
            f"ta=0.35 is not < 0.35, so Sell should not fire; got {stance!r}."
        )

    def test_sell_does_not_fire_when_frag_at_threshold(self):
        """frag exactly = 0.65 is NOT > 0.65 — Sell should NOT fire → Avoid."""
        stance = _run(
            final_score = 0.21,
            frag        = 0.65,    # exactly at threshold, not above
            ta          = 0.20,
            durability  = 0.25,
            ticker      = "EDGE2",
        )
        assert stance == "Avoid", (
            f"frag=0.65 is not > 0.65, so Sell should not fire; got {stance!r}."
        )

    def test_avoid_fires_for_scores_between_012_and_030(self):
        """All sub-0.30 scores with ta ≥ 0.35 should return Avoid (not Sell)."""
        for score in [0.12, 0.15, 0.20, 0.25, 0.29]:
            stance = _run(
                final_score = score,
                frag        = 0.50,
                ta          = 0.50,
                durability  = 0.40,
                ticker      = "LOW",
            )
            assert stance == "Avoid", (
                f"score={score}, ta=0.50 should be Avoid; got {stance!r}."
            )

    def test_sell_reasoning_mentions_deterioration(self):
        """Sell reasoning must reference negative/deterioration language."""
        from app.services.conviction_modeler import _compute_directional_stance
        dims = ConvictionDimensions(
            evidence_quality=0.25, evidence_freshness=0.30,
            thesis_alignment=0.18, macro_uncertainty=0.75,
            valuation_certainty=0.25, estimate_dispersion=0.30,
            governance_risk=0.30,
            expectation_fragility=0.82, expectation_asymmetry=0.70,
        )
        company = CompanyContext(ticker="TEST", company_name="Test Corp")
        stance, reasoning = _compute_directional_stance(
            0.15, dims, "insufficient conviction", company,
            expectation_regime="fair", durability_score=0.28,
        )
        assert stance == "Sell"
        assert any(kw in reasoning.lower() for kw in (
            "deteriorat", "negative", "downside", "structural"
        )), f"Sell reasoning must mention deterioration; got: {reasoning!r}"

    def test_avoid_reasoning_mentions_insufficient_conviction(self):
        """Sub-0.30 Avoid reasoning must reference insufficient conviction or evidence."""
        from app.services.conviction_modeler import _compute_directional_stance
        dims = ConvictionDimensions(
            evidence_quality=0.40, evidence_freshness=0.50,
            thesis_alignment=0.50, macro_uncertainty=0.72,
            valuation_certainty=0.30, estimate_dispersion=0.50,
            governance_risk=0.10,
            expectation_fragility=0.55, expectation_asymmetry=0.35,
        )
        company = CompanyContext(ticker="XOM", company_name="XOM Corp")
        stance, reasoning = _compute_directional_stance(
            0.27, dims, "fragile setup", company,
            expectation_regime="fair", durability_score=0.42,
        )
        assert stance == "Avoid"
        assert any(kw in reasoning.lower() for kw in (
            "insufficient", "conviction", "evidence", "directional"
        )), f"Avoid reasoning must mention insufficient conviction; got: {reasoning!r}"


# ===========================================================================
# FIX 2 — Accumulate rule ordering + threshold 0.65 → 0.60
# ===========================================================================

class TestFix2AccumulateOrdering:
    """
    Before Phase 4A: Buy (explicit) fired before Accumulate (durable compounder).
                     COST (score=0.713, dur~0.63, regime=fair) → Buy.
    After Phase 4A:  Accumulate (durable) fires FIRST for durability ≥ 0.60 in
                     non-cheap regimes.  COST/JPM → Accumulate.
    """

    # ── COST-like scenario ────────────────────────────────────────────────────
    # COST: score=0.713, frag~0.23 (low — membership moat), ta~0.72,
    # durability~0.62-0.65 (QA text: membership/renewal/moat/pricing power),
    # regime="fair"

    def test_cost_like_high_score_low_frag_fair_is_accumulate(self):
        """COST-like: score=0.713, frag=0.23, dur=0.63, regime=fair → Accumulate."""
        stance = _run(
            final_score = 0.713,
            frag        = 0.23,
            ta          = 0.72,
            durability  = 0.63,
            regime      = "fair",
            ticker      = "COST",
        )
        assert stance == "Accumulate", (
            f"COST-like (score=0.713, dur=0.63, regime=fair) should be Accumulate after "
            f"Phase 4A Fix 2; got {stance!r}. Durable compounder rule must fire before "
            "Buy (explicit)."
        )

    def test_cost_exact_durability_threshold_fires(self):
        """Exactly at durability=0.60 threshold → Accumulate fires."""
        stance = _run(
            final_score = 0.70,
            frag        = 0.25,
            ta          = 0.68,
            durability  = 0.60,    # exactly at threshold
            regime      = "fair",
            ticker      = "COST",
        )
        assert stance == "Accumulate", (
            f"durability=0.60 exactly at threshold should be Accumulate; got {stance!r}."
        )

    # ── JPM-like scenario ─────────────────────────────────────────────────────
    # JPM: score=0.688, frag~0.25, ta~0.68, durability~0.62, regime="fair"

    def test_jpm_like_high_score_low_frag_fair_is_accumulate(self):
        """JPM-like: score=0.688, frag=0.25, dur=0.62, regime=fair → Accumulate."""
        stance = _run(
            final_score = 0.688,
            frag        = 0.25,
            ta          = 0.68,
            durability  = 0.62,
            regime      = "fair",
            ticker      = "JPM",
        )
        assert stance == "Accumulate", (
            f"JPM-like (score=0.688, dur=0.62, regime=fair) should be Accumulate after "
            f"Phase 4A Fix 2; got {stance!r}."
        )

    def test_jpm_at_attractive_regime_is_accumulate(self):
        """JPM at attractive regime with high durability → still Accumulate."""
        stance = _run(
            final_score = 0.688,
            frag        = 0.30,
            ta          = 0.68,
            durability  = 0.62,
            regime      = "attractive",
            ticker      = "JPM",
        )
        assert stance == "Accumulate", (
            f"JPM at attractive regime with dur=0.62 should be Accumulate; got {stance!r}."
        )

    # ── COST at stretched regime (existing behavior) ──────────────────────────

    def test_cost_at_stretched_regime_is_not_buy(self):
        """COST at stretched regime: Accumulate or Hold — never Buy."""
        stance = _run(
            final_score = 0.62,
            frag        = 0.48,
            ta          = 0.63,
            durability  = 0.82,
            regime      = "stretched",
            ticker      = "COST",
        )
        assert stance not in ("Buy", "Aggressive Buy"), (
            f"COST at stretched regime must not be Buy; got {stance!r}."
        )

    # ── Buy preserved for low-durability companies ────────────────────────────

    def test_buy_fires_for_low_durability_at_fair(self):
        """With durability=0.50 (< 0.60), durable rule doesn't fire → Buy."""
        stance = _run(
            final_score = 0.72,
            frag        = 0.30,
            ta          = 0.70,
            durability  = 0.50,    # below threshold
            regime      = "fair",
            ticker      = "NVDA",
        )
        assert stance in ("Buy", "Aggressive Buy"), (
            f"NVDA with durability=0.50 at fair regime should be Buy; got {stance!r}."
        )

    def test_buy_fires_for_low_durability_at_attractive(self):
        """Low-durability company at attractive regime → Buy (durable rule inactive)."""
        stance = _run(
            final_score = 0.70,
            frag        = 0.34,
            ta          = 0.70,
            durability  = 0.50,
            regime      = "attractive",
            ticker      = "AMD",
        )
        assert stance in ("Buy", "Aggressive Buy"), (
            f"AMD (dur=0.50) at attractive regime should be Buy; got {stance!r}."
        )

    # ── Buy preserved for high-durability at cheap regime ────────────────────

    def test_buy_fires_for_high_durability_at_cheap_regime(self):
        """Phase 4A: cheap regime excludes durable Accumulate → Buy fires."""
        stance = _run(
            final_score = 0.72,
            frag        = 0.25,
            ta          = 0.70,
            durability  = 0.75,    # high durability
            regime      = "cheap",  # cheap = genuine deep value → Buy OK
            ticker      = "COST",
        )
        assert stance in ("Buy", "Aggressive Buy"), (
            f"COST at cheap regime should be Buy even with high durability; got {stance!r}. "
            "Cheap regime excludes the durable Accumulate gate — deep value warrants Buy."
        )

    def test_buy_fires_for_high_durability_msft_at_cheap(self):
        """MSFT at cheap regime (durable Accumulate excluded) → Buy."""
        stance = _run(
            final_score = 0.72,
            frag        = 0.25,
            ta          = 0.72,
            durability  = 0.78,
            regime      = "cheap",
            ticker      = "MSFT",
        )
        assert stance in ("Buy", "Aggressive Buy"), (
            f"MSFT at cheap regime should be Buy; got {stance!r}."
        )

    # ── Accumulate does not fire below durability threshold ──────────────────

    def test_accumulate_durable_does_not_fire_at_059(self):
        """durability=0.59 (< 0.60) → durable rule doesn't fire."""
        # score=0.69, frag=0.25, ta=0.68 → Buy (explicit) would fire if durable doesn't
        stance = _run(
            final_score = 0.69,
            frag        = 0.25,
            ta          = 0.68,
            durability  = 0.59,    # just below new threshold
            regime      = "fair",
            ticker      = "TEST",
        )
        # Buy (explicit) should fire: 0.69≥0.68, frag<0.40, ta>0.60, regime not stretched/euphoric/bubble
        assert stance in ("Buy", "Aggressive Buy"), (
            f"durability=0.59 is below threshold → durable Accumulate shouldn't fire; "
            f"Buy should fire instead. Got {stance!r}."
        )

    # ── Durable Accumulate blocked in euphoric/bubble ─────────────────────────

    def test_durable_accumulate_blocked_in_euphoric(self):
        """Euphoric regime blocks durable Accumulate (early gate fires first)."""
        stance = _run(
            final_score = 0.65,
            frag        = 0.35,
            ta          = 0.65,
            durability  = 0.80,
            regime      = "euphoric",
            ticker      = "BUBL",
        )
        # Early avoid fires: euphoric + score=0.65 >= 0.60 → doesn't trigger early avoid
        # Actually score=0.65 >= 0.60, so early avoid doesn't fire.
        # Durable Accumulate: euphoric is in exclusion → doesn't fire.
        # Buy explicit: regime=euphoric → blocked.
        # Buy broad: regime=euphoric → blocked.
        # Falls through to Hold or lower.
        assert stance not in ("Buy", "Aggressive Buy"), (
            f"Euphoric regime must block Buy/Aggressive Buy; got {stance!r}."
        )

    # ── Phase 4A combined: both fixes working together ────────────────────────

    def test_cost_high_score_is_not_sell_and_is_accumulate(self):
        """COST: score=0.713 — should be Accumulate (Fix 2), definitely not Sell."""
        stance = _run(
            final_score = 0.713,
            frag        = 0.23,
            ta          = 0.72,
            durability  = 0.63,
            regime      = "fair",
            ticker      = "COST",
        )
        assert stance != "Sell", f"COST should never be Sell; got {stance!r}."
        assert stance == "Accumulate", f"COST should be Accumulate; got {stance!r}."

    def test_xom_like_low_score_is_avoid_not_sell_and_not_buy(self):
        """XOM: score=0.280 — should be Avoid (Fix 1), not Sell, not Buy."""
        stance = _run(
            final_score = 0.280,
            frag        = 0.55,
            ta          = 0.50,
            durability  = 0.42,
            regime      = "fair",
            ticker      = "XOM",
        )
        assert stance not in ("Sell", "Buy", "Aggressive Buy"), (
            f"XOM should not be Sell or Buy; got {stance!r}."
        )
        assert stance == "Avoid", f"XOM should be Avoid; got {stance!r}."


# ===========================================================================
# Regression guard — previously passing behaviors must not change
# ===========================================================================

class TestPhase4ARegressionGuard:
    """Verify that Fix 1 and Fix 2 do not break existing correct behavior."""

    def test_aggressive_buy_still_fires_at_very_high_conviction(self):
        """Aggressive Buy still fires for score≥0.78, frag<0.32, ta>0.68."""
        stance = _run(
            final_score = 0.82,
            frag        = 0.25,
            ta          = 0.80,
            durability  = 0.50,
            regime      = "fair",
        )
        assert stance == "Aggressive Buy", (
            f"Aggressive Buy should fire at score=0.82; got {stance!r}."
        )

    def test_hold_still_fires_in_dead_zone(self):
        """Hold still fires for score in 0.42-0.51 (dead-zone closure)."""
        for score in [0.42, 0.45, 0.49, 0.51]:
            stance = _run(
                final_score = score,
                frag        = 0.40,
                ta          = 0.55,
                durability  = 0.50,
                regime      = "fair",
            )
            assert stance == "Hold", (
                f"Hold should fire in dead-zone at score={score}; got {stance!r}."
            )

    def test_avoid_still_fires_above_030(self):
        """Avoid still fires for score ≥ 0.30 with weak evidence (existing behavior)."""
        stance = _run(
            final_score = 0.35,
            frag        = 0.70,
            ta          = 0.45,
            durability  = 0.40,
            regime      = "fair",
        )
        assert stance == "Avoid", (
            f"Avoid should fire for score=0.35 with high frag; got {stance!r}."
        )

    def test_buy_explicit_blocked_in_stretched_regime(self):
        """Buy (explicit) still blocked in stretched regime."""
        stance = _run(
            final_score = 0.72,
            frag        = 0.30,
            ta          = 0.70,
            durability  = 0.50,
            regime      = "stretched",
        )
        assert stance not in ("Buy", "Aggressive Buy"), (
            f"Buy (explicit) must be blocked in stretched regime; got {stance!r}."
        )

    def test_early_avoid_still_fires_euphoric_low_conviction(self):
        """Early Avoid gate still fires: euphoric + score < 0.60 → Avoid."""
        stance = _run(
            final_score = 0.55,
            frag        = 0.50,
            ta          = 0.62,
            durability  = 0.80,
            regime      = "euphoric",
        )
        assert stance == "Avoid", (
            f"Early Avoid must fire: euphoric + score=0.55; got {stance!r}."
        )

    def test_accumulate_frag_band_still_fires(self):
        """Accumulate frag-band rule (0.40 ≤ frag < 0.62) still fires."""
        stance = _run(
            final_score = 0.65,
            frag        = 0.46,
            ta          = 0.63,
            durability  = 0.50,
            regime      = "fair",
        )
        assert stance == "Accumulate", (
            f"Accumulate frag-band should fire for frag=0.46; got {stance!r}."
        )

    def test_tactical_still_fires(self):
        """Tactical rule still fires: score≥0.52, frag≥0.55, asym<0.50."""
        stance = _run(
            final_score = 0.54,
            frag        = 0.60,
            asym        = 0.40,
            ta          = 0.57,
            durability  = 0.50,
            regime      = "stretched",
        )
        assert stance == "Tactical", (
            f"Tactical should fire for score=0.54, frag=0.60, asym=0.40; got {stance!r}."
        )

    def test_sell_vocab_in_directional_stance_set(self):
        """Sell must still be a reachable stance — not permanently removed."""
        dims = ConvictionDimensions(
            evidence_quality=0.20, evidence_freshness=0.25,
            thesis_alignment=0.15, macro_uncertainty=0.80,
            valuation_certainty=0.15, estimate_dispersion=0.25,
            governance_risk=0.40,
            expectation_fragility=0.88, expectation_asymmetry=0.75,
        )
        company = CompanyContext(ticker="SELL", company_name="Sell Corp")
        stance, _ = _compute_directional_stance(
            0.15, dims, "insufficient conviction", company,
            expectation_regime="fair", durability_score=0.20,
        )
        assert stance == "Sell", (
            f"Extreme deterioration (frag=0.88, ta=0.15) must still produce Sell; got {stance!r}."
        )
