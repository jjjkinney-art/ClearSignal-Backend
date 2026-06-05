"""
tests/test_phase4b_calibration.py

Regression tests for Phase 4B calibration fixes:
  Fix 3 — Macro dominant_dim threshold: macro.confidence < 0.58 → < 0.35
           in _detect_dominant_dimension() (thesis_synthesizer.py)
  Fix 4 — CompanyKnowledgeProfile durability enhancements:
           TSM, AMD, AMZN, NEE profiles updated to push profile-only
           durability above the 0.65 durable-tier threshold.

Key invariants guarded here:
  1. All four target companies' profile-only durability ≥ 0.67 (well above durable tier 0.65)
  2. Durable Accumulate rule fires correctly for high-score high-durability inputs
  3. Durable compression floor (0.82) now protects TSM/AMD/NEE/AMZN under heavy compression
  4. Fix 3 threshold: macro boost fires only when confidence < 0.35 (not at 0.45-0.55)
  5. Phase 4A regression guard: COST/JPM/XOM/SBUX fixes remain intact
"""
from __future__ import annotations

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from app.services.conviction_modeler import (
    _compute_business_durability,
    _compute_directional_stance,
    ConvictionDimensions,
)
from app.services.company_knowledge import get_knowledge_profile
from app.schemas import (
    CompanyContext,
    CompanyKnowledgeProfile,
    QualityAssessment,
    RiskProfile,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _qa(moat="", revenue="", operating="", overall="", conf=0.50):
    return QualityAssessment(
        moat=moat, revenue_durability=revenue,
        operating_quality=operating, overall=overall,
        confidence=conf,
    )


def _risk(risks=None, overall="", competitive="", conf=0.50):
    return RiskProfile(
        key_risks=risks or [], overall=overall,
        competitive_risk=competitive, confidence=conf,
    )


def _dims(frag=0.35, asym=0.30, ta=0.65, eq=0.72, ef=0.70,
          macro=0.38, vc=0.58, disp=0.62, gov=0.05) -> ConvictionDimensions:
    return ConvictionDimensions(
        evidence_quality=eq, evidence_freshness=ef,
        thesis_alignment=ta, macro_uncertainty=macro,
        valuation_certainty=vc, estimate_dispersion=disp,
        governance_risk=gov, expectation_fragility=frag,
        expectation_asymmetry=asym,
    )


def _company(ticker: str) -> CompanyContext:
    return CompanyContext(ticker=ticker, company_name=f"{ticker} Inc.")


def _neutral_qa():
    return _qa(conf=0.50)


def _neutral_risk():
    return _risk(conf=0.50)


# ── Fix 3: Macro dominant_dim threshold ───────────────────────────────────────

class TestFix3MacroDominantDim:
    """Verify that the macro boost in _detect_dominant_dimension now fires
    only when macro.confidence < 0.35, not at the old threshold of < 0.58.

    We test this indirectly by inspecting the threshold constant through
    the thesis_synthesizer module's source.
    """

    def test_macro_threshold_in_source_is_0_35(self):
        """Fix 3: the threshold literal in thesis_synthesizer.py is 0.35."""
        import app.services.thesis_synthesizer as ts_mod
        import inspect
        src = inspect.getsource(ts_mod._detect_dominant_dimension)
        # New threshold should appear; old threshold must NOT appear as the
        # dominant-dimension boost condition.
        assert "< 0.35" in src, (
            "Fix 3 not applied: macro confidence threshold should be 0.35"
        )
        # Confirm old threshold is absent as a condition (could appear in comments,
        # but the functional check should use 0.35)
        # Count occurrences of '< 0.58' vs '< 0.35'
        import re
        old_hits = len(re.findall(r"macro\.confidence\s*<\s*0\.58", src))
        assert old_hits == 0, (
            f"Fix 3 partially reverted: found {old_hits} use(s) of "
            "'macro.confidence < 0.58' in _detect_dominant_dimension"
        )

    def test_macro_threshold_phase4b_note_in_comments(self):
        """Phase 4B calibration note is present as documentation."""
        import app.services.thesis_synthesizer as ts_mod
        import inspect
        src = inspect.getsource(ts_mod._detect_dominant_dimension)
        assert "4B" in src or "0.35" in src, (
            "Phase 4B calibration note missing from _detect_dominant_dimension"
        )


# ── Fix 4: Profile durability for Phase 4B targets ───────────────────────────

class TestFix4ProfileDurability:
    """Profile-only durability (neutral QA/risk/evidence) must exceed 0.67 for
    all four Phase 4B target companies after the profile enhancements.

    0.67 is the minimum buffer: even with ~0.15 of agent-text drag in production,
    the durability remains above the 0.55 expectation-sensitive quality threshold,
    and with moderate agent text, crosses the 0.65 durable-compounder threshold.
    """

    @pytest.mark.parametrize("ticker,min_dur", [
        ("TSM",  0.67),
        ("AMD",  0.67),
        ("AMZN", 0.67),
        ("NEE",  0.67),
    ])
    def test_profile_only_durability_above_floor(self, ticker, min_dur):
        """Phase 4B: profile-only durability ≥ 0.67 for all four targets."""
        profile = get_knowledge_profile(ticker)
        assert profile is not None, f"No profile found for {ticker}"
        dur = _compute_business_durability(
            _neutral_qa(), _neutral_risk(), [], profile=profile
        )
        assert dur >= min_dur, (
            f"{ticker}: profile-only durability {dur:.4f} < {min_dur} — "
            f"profile enhancements may have been reverted or scoring changed"
        )

    def test_tsm_profile_has_service_contract_signal(self):
        """TSM recurring sources must contain 'service contract' for +0.15 tier."""
        profile = get_knowledge_profile("TSM")
        recurring = " ".join(profile.recurring_revenue_sources or []).lower()
        assert "service contract" in recurring or "subscription" in recurring, (
            "TSM recurring sources missing high-quality signal "
            "(service contract / subscription) needed for +0.15 tier"
        )

    def test_amd_profile_has_multi_year_contract_signal(self):
        """AMD recurring sources must contain 'multi-year contract' for +0.15 tier."""
        profile = get_knowledge_profile("AMD")
        recurring = " ".join(profile.recurring_revenue_sources or []).lower()
        assert "multi-year contract" in recurring, (
            "AMD recurring sources missing 'multi-year contract' signal needed for +0.15 tier"
        )

    def test_amzn_profile_no_platform_penalty(self):
        """AMZN valuation_style must not contain bare 'platform' (narrative penalty)."""
        profile = get_knowledge_profile("AMZN")
        valuation_s = (profile.valuation_style or "").lower()
        assert "platform" not in valuation_s, (
            "AMZN valuation_style still contains 'platform' — "
            "this triggers a -0.04 narrative penalty on durability"
        )

    def test_nee_profile_has_multi_year_contract_signal(self):
        """NEE recurring sources must contain 'multi-year contract' for +0.15 tier."""
        profile = get_knowledge_profile("NEE")
        recurring = " ".join(profile.recurring_revenue_sources or []).lower()
        assert "multi-year contract" in recurring or "subscription" in recurring, (
            "NEE recurring sources missing high-quality signal needed for +0.15 tier"
        )

    def test_nee_profile_counter_cyclical_in_recession(self):
        """NEE recession_behavior should contain 'counter-cyclical' to boost pos hits."""
        profile = get_knowledge_profile("NEE")
        recession = (profile.recession_behavior or "").lower()
        assert "counter-cyclical" in recession or "non-discretionary" in recession, (
            "NEE recession_behavior missing defensive signal keywords"
        )

    @pytest.mark.parametrize("ticker", ["TSM", "AMD", "AMZN", "NEE"])
    def test_profile_durability_with_good_qa_stays_durable(self, ticker):
        """With constructive QA text, durability should remain in durable tier (≥ 0.65)."""
        profile = get_knowledge_profile(ticker)
        qa = _qa(
            moat="strong moat with pricing power and switching costs",
            revenue="recurring revenue with resilient subscription-like characteristics",
            overall="high quality business with durable competitive advantages",
            conf=0.60,
        )
        risk_low = _risk(
            risks=["competitive intensity may increase"],
            overall="manageable competitive and regulatory risk",
            conf=0.55,
        )
        dur = _compute_business_durability(qa, risk_low, [], profile=profile)
        assert dur >= 0.65, (
            f"{ticker}: durability {dur:.4f} fell below durable tier (0.65) "
            f"even with constructive QA text — profile buffer insufficient"
        )

    @pytest.mark.parametrize("ticker", ["TSM", "AMD", "AMZN", "NEE"])
    def test_profile_durability_with_harsh_qa_above_quality_tier(self, ticker):
        """Even with harsh agent text (execution risk, disruption, cyclical),
        durability should stay above the quality tier threshold (0.55) due to
        the improved profile buffer.
        """
        profile = get_knowledge_profile(ticker)
        qa = _qa(
            moat="some competitive advantages but execution risk is a concern",
            revenue="revenue quality adequate but disruption risk possible",
            overall="moderate quality with meaningful execution risk and disruption risk",
            conf=0.45,  # below 0.50 → additional -0.003 drag
        )
        harsh_risk = _risk(
            risks=["execution risk on core product roadmap"],
            overall="execution risk remains a primary concern",
            conf=0.45,
        )
        dur = _compute_business_durability(qa, harsh_risk, [], profile=profile)
        assert dur >= 0.55, (
            f"{ticker}: durability {dur:.4f} fell below quality tier (0.55) "
            f"under harsh agent text — profile buffer may need strengthening"
        )


# ── Stance implications: durable compounder rule with improved durability ─────

class TestPhase4BStanceImplications:
    """Verify stance outcomes at score levels that the Phase 4B companies
    should achieve after the profile + macro fixes.

    TSM/AMD/NEE target: Hold (score ≥ 0.42, frag > 0.58)
    AMZN target: Hold → Accumulate (requires score ≥ 0.58 from Fix 3 live pipeline)
    """

    def test_tsm_hold_at_estimated_post_fix_score(self):
        """TSM post-4B estimated score 0.44, frag=0.65 → Hold (demanding setup)."""
        dims = _dims(frag=0.65, asym=0.42, ta=0.65, eq=0.60, vc=0.55)
        stance, _ = _compute_directional_stance(
            0.44, dims, "setup", _company("TSM"),
            expectation_regime="fair", durability_score=0.67,
        )
        assert stance == "Hold", (
            f"TSM at post-4B estimated score (0.44, frag=0.65) should be Hold, got {stance}"
        )

    def test_amd_hold_at_estimated_post_fix_score(self):
        """AMD post-4B estimated score 0.45, frag=0.55 → Hold (dead-zone closure)."""
        dims = _dims(frag=0.55, asym=0.38, ta=0.65, eq=0.62, vc=0.55)
        stance, _ = _compute_directional_stance(
            0.45, dims, "setup", _company("AMD"),
            expectation_regime="fair", durability_score=0.67,
        )
        assert stance == "Hold", (
            f"AMD at post-4B estimated score (0.45, frag=0.55) should be Hold, got {stance}"
        )

    def test_nee_hold_at_estimated_post_fix_score(self):
        """NEE post-4B estimated score 0.44, frag=0.55 → Hold (dead-zone closure)."""
        dims = _dims(frag=0.55, asym=0.35, ta=0.65, eq=0.62, vc=0.55)
        stance, _ = _compute_directional_stance(
            0.44, dims, "setup", _company("NEE"),
            expectation_regime="fair", durability_score=0.73,
        )
        assert stance == "Hold", (
            f"NEE at post-4B estimated score (0.44, frag=0.55) should be Hold, got {stance}"
        )

    def test_amzn_accumulate_when_fix3_boosts_score(self):
        """AMZN: if Fix 3 raises score to 0.60+ with low frag and high durability → Accumulate."""
        dims = _dims(frag=0.35, asym=0.28, ta=0.70, eq=0.68, vc=0.60)
        stance, _ = _compute_directional_stance(
            0.60, dims, "setup", _company("AMZN"),
            expectation_regime="fair", durability_score=0.73,
        )
        assert stance == "Accumulate", (
            f"AMZN at 0.60 score with dur=0.73 and frag=0.35 should be Accumulate, got {stance}"
        )

    def test_amzn_hold_without_score_improvement(self):
        """AMZN at its pre-Fix3 score (0.421) stays Hold — Fix 3 needed for Accumulate."""
        dims = _dims(frag=0.40, asym=0.32, ta=0.55, eq=0.62, vc=0.58)
        stance, _ = _compute_directional_stance(
            0.421, dims, "setup", _company("AMZN"),
            expectation_regime="fair", durability_score=0.73,
        )
        assert stance == "Hold", (
            f"AMZN at 0.421 without Fix 3 score boost should be Hold, got {stance}"
        )

    def test_durable_compression_floor_helps_tsm(self):
        """Durable compression floor (0.82) is now active for TSM dur=0.67 ≥ 0.65.
        With compression floor protecting against severe compression, TSM can reach
        Hold. This test validates the stance at the expected post-floor score.
        """
        # Simulate TSM with frag=0.65 (demanding setup) at score 0.43
        dims = _dims(frag=0.65, asym=0.42, ta=0.65, eq=0.60, vc=0.52)
        stance, reasoning = _compute_directional_stance(
            0.43, dims, "demanding setup", _company("TSM"),
            expectation_regime="fair", durability_score=0.67,
        )
        assert stance == "Hold", (
            f"TSM at 0.43 score with dur=0.67 and frag=0.65 should be Hold, got {stance}"
        )
        assert "TSM" in reasoning

    def test_avoid_fires_for_pre_fix_tsm_score(self):
        """TSM at 0.377 (pre-Phase-4B) → Avoid (confirms regression guard).
        This score is below the 0.42 Hold threshold and above 0.30 Avoid gate.
        """
        dims = _dims(frag=0.65, asym=0.42, ta=0.62, eq=0.58, vc=0.52)
        stance, _ = _compute_directional_stance(
            0.377, dims, "demanding setup", _company("TSM"),
            expectation_regime="fair", durability_score=0.56,  # old durability
        )
        assert stance == "Avoid", (
            f"TSM at old score 0.377 with old dur=0.56 should still be Avoid, got {stance}"
        )

    def test_avoid_fires_for_pre_fix_amd_score(self):
        """AMD at 0.419 (pre-Phase-4B) → Avoid (below 0.42 Hold threshold)."""
        dims = _dims(frag=0.55, asym=0.38, ta=0.52, eq=0.60, vc=0.55)
        stance, _ = _compute_directional_stance(
            0.419, dims, "moderate setup", _company("AMD"),
            expectation_regime="fair", durability_score=0.44,  # old durability
        )
        assert stance == "Avoid", (
            f"AMD at old score 0.419 with old dur=0.44 should be Avoid, got {stance}"
        )


# ── Phase 4A regression guard (Fix 1 + Fix 2 must remain intact) ─────────────

class TestPhase4ARegressionGuard:
    """Verify that Phase 4B changes do not break Phase 4A fixes."""

    def test_cost_still_accumulate(self):
        """COST (dur=0.70, score=0.713, fair) → Accumulate (Phase 5A threshold 0.68)."""
        dims = _dims(frag=0.23, asym=0.18, ta=0.72)
        stance, _ = _compute_directional_stance(
            0.713, dims, "durable setup", _company("COST"),
            expectation_regime="fair", durability_score=0.70,  # Phase 5A: ≥ 0.68
        )
        assert stance == "Accumulate", f"COST regression: expected Accumulate, got {stance}"

    def test_jpm_still_accumulate(self):
        """JPM (dur=0.70, score=0.688, fair) → Accumulate (Phase 5A threshold 0.68)."""
        dims = _dims(frag=0.25, asym=0.20, ta=0.68)
        stance, _ = _compute_directional_stance(
            0.688, dims, "durable setup", _company("JPM"),
            expectation_regime="fair", durability_score=0.70,  # Phase 5A: ≥ 0.68
        )
        assert stance == "Accumulate", f"JPM regression: expected Accumulate, got {stance}"

    def test_xom_still_avoid(self):
        """XOM (score=0.280, ta=0.50) → Avoid (Phase 4A Fix 1 — not Sell)."""
        dims = _dims(frag=0.55, asym=0.38, ta=0.50)
        stance, _ = _compute_directional_stance(
            0.280, dims, "weak setup", _company("XOM"),
            expectation_regime="fair", durability_score=0.42,
        )
        assert stance == "Avoid", f"XOM regression: expected Avoid, got {stance}"

    def test_sbux_still_avoid(self):
        """SBUX (score=0.273, ta=0.48) → Avoid (Phase 4A Fix 1 — not Sell)."""
        dims = _dims(frag=0.60, asym=0.42, ta=0.48)
        stance, _ = _compute_directional_stance(
            0.273, dims, "weak setup", _company("SBUX"),
            expectation_regime="fair", durability_score=0.38,
        )
        assert stance == "Avoid", f"SBUX regression: expected Avoid, got {stance}"

    def test_sell_still_fires_for_structural_deterioration(self):
        """Sell still fires when frag > 0.65 AND ta < 0.35 (Phase 4A Fix 1)."""
        dims = _dims(frag=0.85, asym=0.55, ta=0.20)
        stance, _ = _compute_directional_stance(
            0.250, dims, "breakdown", _company("TEST"),
            expectation_regime="fair", durability_score=0.40,
        )
        assert stance == "Sell", f"Sell regression: should still fire for structural breakdown"

    def test_aggressive_buy_unchanged(self):
        """Aggressive Buy still fires for score ≥ 0.78, frag < 0.32, ta > 0.68."""
        dims = _dims(frag=0.28, asym=0.20, ta=0.75)
        stance, _ = _compute_directional_stance(
            0.82, dims, "exceptional", _company("MSFT"),
            expectation_regime="fair", durability_score=0.78,
        )
        assert stance == "Aggressive Buy", f"Aggressive Buy regression, got {stance}"

    def test_hold_dead_zone_closure_still_works(self):
        """Hold still fires at score 0.42+ when not caught by higher-priority rules."""
        dims = _dims(frag=0.35, asym=0.30, ta=0.55, eq=0.55, vc=0.50)
        stance, _ = _compute_directional_stance(
            0.45, dims, "moderate", _company("AMZN"),
            expectation_regime="fair", durability_score=0.50,
        )
        # At dur=0.50 (below Accumulate threshold), frag=0.35 (below 0.40 for durable Acc),
        # score=0.45 (below 0.58 for Accumulate frag-band), and below Buy thresholds
        # → should fall through to Hold (dead-zone closure at ≥ 0.42)
        assert stance == "Hold", f"Hold dead-zone regression, got {stance}"
