"""
Phase 9G · Phase 0 — Pure-function tests for dossier_extraction_service.py

All tests run without a database session (pure / deterministic).
No mocks required.

Test plan:
  1. Fallback guard           — is_fallback_thesis
  2. Harvest                  — harvest_from_thesis (null-safe, signal mapping)
  3. Debate reconciliation    — 8-combination table-driven test + first-write
  4. Moat hysteresis          — 4-state machine + first-write + unknown axis guard
  5. Catalyst lifecycle       — specificity gate, dedup, transitions
  6. Variant reconciliation   — first-write, direction flip, no-change
  7. Durability reconciliation — unconditional op, signal pass-through
  8. Failure mode ops         — label key, evidence_refs, empty list
  9. Helpers                  — debate_text_distance, claim_hash, score_catalyst_specificity,
                                catalysts_match, infer_current_lean, is_material_thesis_delta,
                                build_revision_dict, build_evidence_dict
 10. build_extraction_plan    — integration: fallback skip, op list shape,
                                head_update present, skipped counters
"""

from __future__ import annotations

import types
from typing import Any, Optional

import pytest

from app.services.dossier_extraction_service import (
    TAU_HIGH,
    TAU_WRITE,
    SPECIFICITY_GATE,
    DEBATE_SIMILARITY_THRESHOLD,
    CATALYST_MATCH_RATIO,
    MOAT_AXES,
    DossierExtractionPayload,
    DossierOp,
    ExtractionPlan,
    MoatAxisExtract,
    CatalystExtract,
    VariantDivergenceExtract,
    is_fallback_thesis,
    harvest_from_thesis,
    build_extraction_plan,
    reconcile_debate,
    reconcile_moat_dimension,
    reconcile_catalysts,
    reconcile_variant,
    reconcile_durability,
    reconcile_failure_modes,
    debate_text_distance,
    is_material_thesis_delta,
    infer_current_lean,
    score_catalyst_specificity,
    catalysts_match,
    claim_hash,
    build_revision_dict,
    build_evidence_dict,
)


# ===========================================================================
# Helpers / stub builders
# ===========================================================================

def _ns(**kwargs) -> Any:
    """Return a SimpleNamespace (acts like an ORM model for attribute access)."""
    return types.SimpleNamespace(**kwargs)


def _thesis(**overrides) -> Any:
    """Return a minimal InvestmentThesis-like namespace."""
    defaults = dict(
        ticker             = "AAPL",
        company_name       = "Apple Inc.",
        directional_stance = "Buy",
        confidence_score   = 0.72,
        thesis_version_id  = "ver-001",
        conclusion         = "Solid upside",
        bull_thesis        = "Strong product cycle",
        score_source       = "live",
        thesis_trend       = "stable",
        setup_label        = "actionable thesis",
        change_vector      = {},
        what_changes_the_thesis = [],
        key_risks          = ["margin compression"],
        dominant_dimension = "",
        historical_evidence = None,
        catalyst_calendar  = None,
    )
    defaults.update(overrides)
    return _ns(**defaults)


def _existing_debate(**overrides) -> Any:
    defaults = dict(
        question          = "Will Apple maintain its premium pricing power?",
        bull_pole         = "Brand moat and ecosystem lock-in remain intact.",
        bear_pole         = "Competition may erode margins.",
        current_lean      = "bull",
        resolution_signal = "Watch gross margin trend Q1.",
        version           = 1,
        confidence        = 0.65,
    )
    defaults.update(overrides)
    return _ns(**defaults)


def _existing_dim(axis: str = "network_effects", strength: str = "strong",
                  trend: str = "stable", version: int = 1,
                  pending_flip: bool = False, **kw) -> Any:
    defaults = dict(rationale="Old rationale", vulnerability="")
    defaults.update(kw)
    return _ns(axis=axis, strength=strength, trend=trend,
               version=version, pending_flip=pending_flip,
               **defaults)


def _payload(**overrides) -> DossierExtractionPayload:
    defaults = dict(
        debate_question              = "Can Apple defend iPhone margins?",
        debate_bull_pole             = "Premium brand and services growth protect margins.",
        debate_bear_pole             = "Android competition intensifies.",
        debate_current_lean          = "bull",
        debate_resolution_signal     = "Watch Q2 gross margin vs 43% guide.",
        debate_extraction_confidence = 0.80,
        moat_axes                    = [],
        moat_extraction_confidence   = 0.80,
        new_catalysts                = [],
        catalyst_extraction_confidence = 0.70,
        triggered_catalyst_ids       = [],
        invalidated_catalyst_ids     = [],
        variant_divergences          = [],
        variant_extraction_confidence = 0.65,
    )
    defaults.update(overrides)
    return DossierExtractionPayload(**defaults)


def _empty_dossier() -> dict:
    return {
        "head":        None,
        "debate":      None,
        "dimensions":  [],
        "catalysts":   [],
        "variant":     None,
        "durability":  None,
        "failure_modes": [],
    }


# ===========================================================================
# 1. Fallback guard
# ===========================================================================

class TestIsFallbackThesis:
    def test_wall_cap_in_conclusion(self):
        t = _thesis(conclusion="Wall cap exceeded for this ticker")
        assert is_fallback_thesis(t) is True

    def test_synthesis_unavailable_in_bull(self):
        t = _thesis(bull_thesis="Synthesis unavailable at this time")
        assert is_fallback_thesis(t) is True

    def test_fallback_empty_score_source(self):
        t = _thesis(score_source="fallback_empty")
        assert is_fallback_thesis(t) is True

    def test_zero_confidence(self):
        t = _thesis(confidence_score=0.0)
        assert is_fallback_thesis(t) is True

    def test_none_confidence(self):
        t = _thesis(confidence_score=None)
        assert is_fallback_thesis(t) is True

    def test_valid_thesis_not_fallback(self):
        t = _thesis()
        assert is_fallback_thesis(t) is False

    def test_case_insensitive_wall_cap(self):
        t = _thesis(conclusion="WALL CAP EXCEEDED")
        assert is_fallback_thesis(t) is True

    def test_None_conclusion_safe(self):
        t = _thesis(conclusion=None, bull_thesis="Real thesis content", score_source="live")
        assert is_fallback_thesis(t) is False


# ===========================================================================
# 2. Harvest
# ===========================================================================

class TestHarvestFromThesis:
    def test_basic_fields_returned(self):
        t = _thesis()
        h = harvest_from_thesis(t)
        assert h["ticker"] == "AAPL"
        assert h["company_name"] == "Apple Inc."
        assert h["stance"] == "Buy"
        assert h["conviction"] == pytest.approx(0.72)

    def test_lean_mapped_from_stance(self):
        h = harvest_from_thesis(_thesis(directional_stance="Aggressive Buy"))
        assert h["current_lean"] == "bull"
        h2 = harvest_from_thesis(_thesis(directional_stance="Sell"))
        assert h2["current_lean"] == "bear"
        h3 = harvest_from_thesis(_thesis(directional_stance="Hold"))
        assert h3["current_lean"] == "balanced"

    def test_conviction_trend_mapped(self):
        h = harvest_from_thesis(_thesis(thesis_trend="strengthening"))
        assert h["conviction_trend"] == "rising"
        h2 = harvest_from_thesis(_thesis(thesis_trend="weakening"))
        assert h2["conviction_trend"] == "falling"

    def test_cycle_position_from_setup_label(self):
        h = harvest_from_thesis(_thesis(setup_label="High-Alignment Thesis"))
        assert h["cycle_position"] == "early"

    def test_tactical_stance_forces_trade_horizon(self):
        h = harvest_from_thesis(_thesis(directional_stance="Tactical"))
        assert h["horizon_hint"] == "trade"

    def test_primary_concern_from_key_risks(self):
        h = harvest_from_thesis(_thesis(key_risks=["rate risk", "FX headwind"]))
        assert h["primary_concern"] == "rate risk"

    def test_primary_concern_fallback_to_dominant_dimension(self):
        h = harvest_from_thesis(_thesis(key_risks=[], dominant_dimension="valuation"))
        assert h["primary_concern"] == "valuation"

    def test_catalyst_proximity_days_extracted(self):
        cal = _ns(days_to_event=45)
        h = harvest_from_thesis(_thesis(catalyst_calendar=cal))
        assert h["catalyst_proximity_days"] == 45

    def test_catalyst_proximity_days_none_when_absent(self):
        h = harvest_from_thesis(_thesis(catalyst_calendar=None))
        assert h["catalyst_proximity_days"] is None

    def test_failure_mode_analogs_extracted(self):
        analog = _ns(label="Cisco-2000", relevance_score=0.85,
                     drawdown_pct=0.72, time_to_trough_days=480)
        hist_ev = _ns(analogs=[analog])
        h = harvest_from_thesis(_thesis(historical_evidence=hist_ev))
        assert len(h["failure_mode_analogs"]) == 1
        assert h["failure_mode_analogs"][0]["label"] == "Cisco-2000"
        assert h["analog_time_to_trough_days"] == 480

    def test_failure_mode_empty_when_no_historical_evidence(self):
        h = harvest_from_thesis(_thesis(historical_evidence=None))
        assert h["failure_mode_analogs"] == []
        assert h["analog_time_to_trough_days"] is None

    def test_is_material_delta_embedded(self):
        t = _thesis(change_vector={"stance_shifted": True})
        h = harvest_from_thesis(t)
        assert h["is_material_delta"] is True

    def test_null_safe_missing_attributes(self):
        # Minimal object — only the required attributes
        t = _ns(confidence_score=0.60, conclusion="Fine", bull_thesis="Good",
                score_source="live")
        h = harvest_from_thesis(t)
        assert h["ticker"] == ""      # default empty
        assert h["conviction"] == pytest.approx(0.60)


# ===========================================================================
# 3. Debate reconciliation — 8-combination table-driven
# ===========================================================================

# Parameterize all 8 combinations of (semantic_shift, material_delta, high_conf)
# plus the expected outcome.
#
# Outcome codes:
#   "version_bump"   — write_debate with version N+1 + revision
#   "lean_only"      — only update_debate_lean (no write_debate)
#   "candidate"      — write_debate with same version + candidate revision

_DEBATE_CASES = [
    # id                         shift  material  high    expected_outcome
    ("shift+material+highconf",  True,  True,     True,   "version_bump"),
    ("shift+material+lowconf",   True,  True,     False,  "candidate"),
    ("shift+nomaterial+highconf",True,  False,    True,   "candidate"),
    ("shift+nomaterial+lowconf", True,  False,    False,  "candidate"),
    ("noshift+material+highconf",False, True,     True,   "lean_only"),
    ("noshift+material+lowconf", False, True,     False,  "lean_only"),
    ("noshift+nomaterial+highconf",False,False,   True,   "lean_only"),
    ("noshift+nomaterial+lowconf",False,False,    False,  "lean_only"),
]


@pytest.mark.parametrize("case_id,shift,material,high,expected", _DEBATE_CASES,
                         ids=[c[0] for c in _DEBATE_CASES])
def test_debate_8combinations(case_id, shift, material, high, expected):
    """Table-driven test for all 8 debate update conditions."""
    existing = _existing_debate(version=2, current_lean="balanced")

    # Build new text: if shift=True, use completely different text; else reuse existing
    if shift:
        new_q    = "Totally unrelated question about supply chain disruption?"
        new_bull = "New bull pole about entirely different factor."
        new_bear = "New bear pole about completely different risk."
    else:
        new_q    = existing.question
        new_bull = existing.bull_pole
        new_bear = existing.bear_pole

    # For material: supply a change_vector with stance_shifted
    t = _thesis(change_vector={"stance_shifted": True} if material else {})

    conf = TAU_HIGH + 0.01 if high else TAU_WRITE + 0.01

    ops = reconcile_debate(
        debate_question          = new_q,
        debate_bull_pole         = new_bull,
        debate_bear_pole         = new_bear,
        debate_current_lean      = "bull",  # different from "balanced"
        debate_resolution_signal = "Watch EPS guidance.",
        existing_debate          = existing,
        is_material_delta        = material,
        extraction_confidence    = conf,
        version_id               = "ver-abc",
        ticker                   = "AAPL",
        session_id               = "s1",
    )

    write_ops   = [o for o in ops if o.kind == "write_debate"]
    lean_ops    = [o for o in ops if o.kind == "update_debate_lean"]

    if expected == "version_bump":
        assert len(write_ops) == 1, f"[{case_id}] expected exactly 1 write_debate op"
        assert write_ops[0].kwargs["version"] == 3, "version should be N+1"
        assert write_ops[0].kwargs["expect_version"] == 2
        assert write_ops[0].revision is not None
        assert write_ops[0].revision["new_version"] == 3
    elif expected == "lean_only":
        assert len(write_ops) == 0, f"[{case_id}] no write_debate expected"
        # lean update should be present (lean changed balanced→bull)
        assert len(lean_ops) == 1
    elif expected == "candidate":
        assert len(write_ops) == 1, f"[{case_id}] expected candidate write_debate"
        assert write_ops[0].kwargs["version"] == 2, "version should be UNCHANGED for candidate"
        assert write_ops[0].revision is not None
        # Candidate revision has prev_version == new_version
        assert write_ops[0].revision["prev_version"] == write_ops[0].revision["new_version"]
    else:
        pytest.fail(f"Unknown expected outcome: {expected}")


def test_debate_first_write_creates_version_1():
    ops = reconcile_debate(
        debate_question          = "Will margins hold?",
        debate_bull_pole         = "Services shield margins.",
        debate_bear_pole         = "Hardware saturation.",
        debate_current_lean      = "bull",
        debate_resolution_signal = "Q2 report.",
        existing_debate          = None,
        is_material_delta        = False,
        extraction_confidence    = 0.70,
        version_id               = "ver-001",
        ticker                   = "MSFT",
    )
    assert len(ops) == 1
    assert ops[0].kind == "write_debate"
    assert ops[0].kwargs["version"] == 1
    assert ops[0].kwargs["expect_version"] is None
    assert len(ops[0].evidence_refs) == 1


def test_debate_no_lean_op_when_lean_unchanged():
    existing = _existing_debate(current_lean="bull")
    ops = reconcile_debate(
        debate_question       = existing.question,
        debate_bull_pole      = existing.bull_pole,
        debate_bear_pole      = existing.bear_pole,
        debate_current_lean   = "bull",  # same as existing
        debate_resolution_signal = "",
        existing_debate       = existing,
        is_material_delta     = False,
        extraction_confidence = 0.60,
        version_id            = "v1",
        ticker                = "AAPL",
    )
    lean_ops = [o for o in ops if o.kind == "update_debate_lean"]
    assert len(lean_ops) == 0


# ===========================================================================
# 4. Moat hysteresis — 4-state machine
# ===========================================================================

class TestReconcileMoatDimension:
    def _make_extract(self, strength: str = "moderate", trend: str = "weakening",
                      conf: float = 0.60) -> MoatAxisExtract:
        return MoatAxisExtract(axis="network_effects", strength=strength,
                               trend=trend, rationale="New rationale",
                               vulnerability="New vuln", confidence=conf)

    def test_first_write_creates_version_1(self):
        op = reconcile_moat_dimension(
            extract    = self._make_extract("strong", "stable", 0.65),
            existing   = None,
            version_id = "v1",
            ticker     = "AAPL",
        )
        assert op is not None
        assert op.kind == "upsert_dimension"
        assert op.kwargs["version"] == 1
        assert op.kwargs["expect_version"] is None
        assert len(op.evidence_refs) == 1

    def test_state2_same_direction_prose_update_no_version_bump(self):
        existing = _existing_dim("network_effects", "strong", "stable", version=2,
                                  pending_flip=False, rationale="Old", vulnerability="")
        # Same strength+trend, different rationale
        extract = MoatAxisExtract(axis="network_effects", strength="strong",
                                  trend="stable", rationale="New rationale",
                                  vulnerability="New vuln", confidence=0.65)
        op = reconcile_moat_dimension(extract=extract, existing=existing,
                                      version_id="v2", ticker="AAPL")
        assert op is not None
        assert op.kwargs["version"] == 2    # no bump
        assert op.revision is None

    def test_state2_same_direction_no_prose_change_returns_none(self):
        existing = _existing_dim("network_effects", "strong", "stable", version=1,
                                  pending_flip=False, rationale="Same", vulnerability="")
        extract = MoatAxisExtract(axis="network_effects", strength="strong",
                                  trend="stable", rationale="Same",
                                  vulnerability="", confidence=0.60)
        op = reconcile_moat_dimension(extract=extract, existing=existing,
                                      version_id="v1", ticker="AAPL")
        assert op is None

    def test_state3_first_flip_signal_sets_pending(self):
        existing = _existing_dim("network_effects", "strong", "stable", version=1,
                                  pending_flip=False)
        extract = self._make_extract("weak", "weakening", conf=0.60)   # conf < TAU_HIGH
        op = reconcile_moat_dimension(extract=extract, existing=existing,
                                      version_id="v1", ticker="AAPL")
        assert op is not None
        assert op.kind == "set_pending_flip"
        assert op.kwargs["pending"] is True

    def test_state4_second_consecutive_flip_commits(self):
        existing = _existing_dim("network_effects", "strong", "stable", version=1,
                                  pending_flip=True)          # already pending
        extract = self._make_extract("weak", "weakening", conf=0.60)   # conf < TAU_HIGH
        op = reconcile_moat_dimension(extract=extract, existing=existing,
                                      version_id="v2", ticker="AAPL")
        assert op is not None
        assert op.kind == "upsert_dimension"
        assert op.kwargs["version"] == 2
        assert op.kwargs["pending_flip"] is False
        assert op.revision is not None
        assert "hysteresis confirmed" in op.revision["change_summary"]

    def test_state5_high_conf_immediate_flip(self):
        existing = _existing_dim("network_effects", "strong", "stable", version=2,
                                  pending_flip=False)
        extract = self._make_extract("weak", "weakening", conf=TAU_HIGH + 0.01)
        op = reconcile_moat_dimension(extract=extract, existing=existing,
                                      version_id="v3", ticker="AAPL")
        assert op is not None
        assert op.kind == "upsert_dimension"
        assert op.kwargs["version"] == 3
        assert op.kwargs["pending_flip"] is False
        assert op.revision is not None
        assert "high-conf override" in op.revision["change_summary"]

    def test_same_direction_clears_stale_pending_flip(self):
        existing = _existing_dim("network_effects", "weak", "weakening", version=2,
                                  pending_flip=True, rationale="Old", vulnerability="")
        # Now extraction agrees: back to the existing direction
        extract = MoatAxisExtract(axis="network_effects", strength="weak",
                                  trend="weakening", rationale="Old", vulnerability="",
                                  confidence=0.60)
        op = reconcile_moat_dimension(extract=extract, existing=existing,
                                      version_id="v3", ticker="AAPL")
        assert op is not None
        assert op.kind == "set_pending_flip"
        assert op.kwargs["pending"] is False

    def test_unknown_axis_filtered_by_build_extraction_plan(self):
        # build_extraction_plan should skip axes not in MOAT_AXES
        extract = MoatAxisExtract(axis="brand_trust",   # not in taxonomy
                                  strength="strong", trend="stable",
                                  rationale="", vulnerability="", confidence=0.80)
        payload = _payload(moat_axes=[extract], moat_extraction_confidence=0.80)
        plan = build_extraction_plan(
            payload          = payload,
            existing_dossier = _empty_dossier(),
            thesis           = _thesis(),
            version_id       = "v1",
        )
        dim_ops = [o for o in plan.ops if o.kind == "upsert_dimension"]
        assert dim_ops == []


# ===========================================================================
# 5. Catalyst reconciliation
# ===========================================================================

class TestReconcileCatalysts:
    def _make_extract(self, statement: str = "Revenue exceeds $100B in Q2 2027",
                      direction: str = "bull_trigger",
                      specificity: float = 0.0) -> CatalystExtract:
        return CatalystExtract(statement=statement, direction=direction,
                               specificity=specificity, expected_window="Q2 2027",
                               conviction_weight=0.7)

    def test_new_catalyst_above_gate_accepted(self):
        extract = self._make_extract("Revenue >$100B this quarter for a bull trigger")
        ops, n_skip = reconcile_catalysts(
            new_extracts       = [extract],
            triggered_ids      = [],
            invalidated_ids    = [],
            existing_catalysts = [],
            version_id         = "v1",
            ticker             = "AAPL",
        )
        assert n_skip == 0
        assert len([o for o in ops if o.kind == "append_catalyst"]) == 1

    def test_vague_catalyst_below_gate_skipped(self):
        extract = self._make_extract("Things might improve")
        ops, n_skip = reconcile_catalysts(
            new_extracts       = [extract],
            triggered_ids      = [],
            invalidated_ids    = [],
            existing_catalysts = [],
            version_id         = "v1",
            ticker             = "AAPL",
        )
        assert n_skip == 1
        assert len([o for o in ops if o.kind == "append_catalyst"]) == 0

    def test_explicit_high_specificity_overrides_heuristic(self):
        # When specificity is set explicitly above gate, use it directly
        extract = self._make_extract("Vague statement", specificity=0.80)
        ops, n_skip = reconcile_catalysts(
            new_extracts       = [extract],
            triggered_ids      = [],
            invalidated_ids    = [],
            existing_catalysts = [],
            version_id         = "v1",
            ticker             = "AAPL",
        )
        assert n_skip == 0
        assert len([o for o in ops if o.kind == "append_catalyst"]) == 1

    def test_duplicate_catalyst_not_added_again(self):
        existing_cat = _ns(statement="Revenue exceeds $100B in Q2 2027",
                           status="open")
        extract = self._make_extract("Revenue exceeds $100B in Q2 2027")
        ops, _ = reconcile_catalysts(
            new_extracts       = [extract],
            triggered_ids      = [],
            invalidated_ids    = [],
            existing_catalysts = [existing_cat],
            version_id         = "v1",
            ticker             = "AAPL",
        )
        assert len([o for o in ops if o.kind == "append_catalyst"]) == 0

    def test_triggered_id_emits_transition_op(self):
        ops, _ = reconcile_catalysts(
            new_extracts       = [],
            triggered_ids      = ["cat-uuid-1"],
            invalidated_ids    = [],
            existing_catalysts = [],
            version_id         = "v1",
            ticker             = "AAPL",
        )
        trans_ops = [o for o in ops if o.kind == "transition_catalyst"]
        assert len(trans_ops) == 1
        assert trans_ops[0].kwargs["new_status"] == "triggered"

    def test_invalidated_id_emits_transition_op(self):
        ops, _ = reconcile_catalysts(
            new_extracts       = [],
            triggered_ids      = [],
            invalidated_ids    = ["cat-uuid-2"],
            existing_catalysts = [],
            version_id         = "v1",
            ticker             = "AAPL",
        )
        trans_ops = [o for o in ops if o.kind == "transition_catalyst"]
        assert len(trans_ops) == 1
        assert trans_ops[0].kwargs["new_status"] == "invalidated"

    def test_same_cycle_dedup_prevents_two_identical_catalysts(self):
        stmt = "EPS beats by >5% for two consecutive quarters"
        e1 = self._make_extract(stmt, specificity=0.80)
        e2 = self._make_extract(stmt, specificity=0.80)
        ops, _ = reconcile_catalysts(
            new_extracts       = [e1, e2],
            triggered_ids      = [],
            invalidated_ids    = [],
            existing_catalysts = [],
            version_id         = "v1",
            ticker             = "AAPL",
        )
        assert len([o for o in ops if o.kind == "append_catalyst"]) == 1


# ===========================================================================
# 6. Variant reconciliation
# ===========================================================================

class TestReconcileVariant:
    def _make_divs(self, direction: str = "more_bullish") -> list:
        return [VariantDivergenceExtract(
            dimension        = "revenue_trajectory",
            consensus_view   = "Slowing growth",
            clearsignal_view = "Re-acceleration likely",
            direction        = direction,
            conviction       = 0.70,
        )]

    def test_first_write_creates_version_1(self):
        op = reconcile_variant(
            divergences           = self._make_divs(),
            existing              = None,
            extraction_confidence = 0.70,
            version_id            = "v1",
            ticker                = "NVDA",
        )
        assert op is not None
        assert op.kind == "write_variant"
        assert op.kwargs["version"] == 1
        assert op.kwargs["expect_version"] is None

    def test_no_op_when_no_divergences(self):
        op = reconcile_variant(
            divergences           = [],
            existing              = None,
            extraction_confidence = 0.70,
            version_id            = "v1",
            ticker                = "NVDA",
        )
        assert op is None

    def test_direction_flip_triggers_version_bump(self):
        old_div = [{"dimension": "revenue_trajectory", "direction": "more_bearish",
                    "consensus_view": "", "clearsignal_view": "", "conviction": 0.5}]
        existing = _ns(divergences=old_div, version=1)
        op = reconcile_variant(
            divergences           = self._make_divs(direction="more_bullish"),
            existing              = existing,
            extraction_confidence = 0.70,
            version_id            = "v2",
            ticker                = "NVDA",
        )
        assert op is not None
        assert op.kwargs["version"] == 2
        assert op.revision is not None

    def test_new_dimension_triggers_version_bump(self):
        old_div = [{"dimension": "valuation", "direction": "more_bullish",
                    "consensus_view": "", "clearsignal_view": "", "conviction": 0.5}]
        existing = _ns(divergences=old_div, version=1)
        # Add a dimension that wasn't there before
        op = reconcile_variant(
            divergences           = self._make_divs("more_bullish"),  # revenue_trajectory
            existing              = existing,
            extraction_confidence = 0.70,
            version_id            = "v2",
            ticker                = "NVDA",
        )
        assert op is not None
        assert op.kwargs["version"] == 2

    def test_no_change_returns_none(self):
        old_div = [{"dimension": "revenue_trajectory", "direction": "more_bullish",
                    "consensus_view": "", "clearsignal_view": "", "conviction": 0.7}]
        existing = _ns(divergences=old_div, version=1)
        op = reconcile_variant(
            divergences           = self._make_divs("more_bullish"),  # same direction
            existing              = existing,
            extraction_confidence = 0.70,
            version_id            = "v2",
            ticker                = "NVDA",
        )
        assert op is None


# ===========================================================================
# 7. Durability reconciliation
# ===========================================================================

class TestReconcileDurability:
    def test_always_returns_op(self):
        h = {
            "cycle_position":             "mid",
            "catalyst_proximity_days":    30,
            "analog_time_to_trough_days": 365,
            "conviction_trend":           "rising",
            "horizon_hint":               "investment",
        }
        op = reconcile_durability(harvested=h, ticker="AAPL")
        assert op is not None
        assert op.kind == "write_durability"

    def test_nullable_signals_passed_through(self):
        h = {
            "cycle_position":             "unknown",
            "catalyst_proximity_days":    None,
            "analog_time_to_trough_days": None,
            "conviction_trend":           "stable",
            "horizon_hint":               "investment",
        }
        op = reconcile_durability(harvested=h, ticker="TSLA")
        assert op.kwargs["catalyst_proximity_days"] is None
        assert op.kwargs["analog_time_to_trough_days"] is None

    def test_all_signals_propagated(self):
        h = {
            "cycle_position":             "early",
            "catalyst_proximity_days":    10,
            "analog_time_to_trough_days": 180,
            "conviction_trend":           "rising",
            "horizon_hint":               "trade",
        }
        op = reconcile_durability(harvested=h, ticker="META")
        assert op.kwargs["cycle_position"] == "early"
        assert op.kwargs["catalyst_proximity_days"] == 10
        assert op.kwargs["conviction_trend"] == "rising"
        assert op.kwargs["horizon_hint"] == "trade"


# ===========================================================================
# 8. Failure mode ops
# ===========================================================================

class TestReconcileFailureModes:
    def test_empty_list_returns_empty(self):
        ops = reconcile_failure_modes([], ticker="AAPL", version_id="v1")
        assert ops == []

    def test_label_key_in_kwargs_not_analog_id(self):
        analogs = [{"label": "Cisco-2000", "relevance_score": 0.85,
                    "drawdown_pct": 0.72, "time_to_trough_days": 480}]
        ops = reconcile_failure_modes(analogs, ticker="AAPL", version_id="v1")
        assert len(ops) == 1
        assert ops[0].kind == "upsert_failure_mode"
        assert "analog_label" in ops[0].kwargs
        assert "analog_id"    not in ops[0].kwargs
        assert ops[0].kwargs["analog_label"] == "Cisco-2000"

    def test_evidence_ref_attached(self):
        analogs = [{"label": "Nortel-2000", "relevance_score": 0.70,
                    "drawdown_pct": None, "time_to_trough_days": None}]
        ops = reconcile_failure_modes(analogs, ticker="MSFT", version_id="v1")
        assert len(ops[0].evidence_refs) == 1
        assert ops[0].evidence_refs[0]["source_type"] == "analog"
        # source_id is None (Slice 4 fills after label resolution)
        assert ops[0].evidence_refs[0]["source_id"] is None

    def test_missing_label_skipped(self):
        analogs = [{"label": "", "relevance_score": 0.90,
                    "drawdown_pct": 0.5, "time_to_trough_days": 300}]
        ops = reconcile_failure_modes(analogs, ticker="AAPL", version_id="v1")
        assert ops == []

    def test_multiple_analogs_produce_multiple_ops(self):
        analogs = [
            {"label": "Cisco-2000", "relevance_score": 0.85, "drawdown_pct": 0.72,
             "time_to_trough_days": 480},
            {"label": "Sun Micro-2001", "relevance_score": 0.62, "drawdown_pct": 0.88,
             "time_to_trough_days": 600},
        ]
        ops = reconcile_failure_modes(analogs, ticker="NVDA", version_id="v1")
        assert len(ops) == 2


# ===========================================================================
# 9. Helpers
# ===========================================================================

class TestDebateTextDistance:
    def test_identical_texts_distance_zero(self):
        assert debate_text_distance("Hello world", "Hello world") == pytest.approx(0.0)

    def test_empty_both_returns_1(self):
        assert debate_text_distance("", "") == pytest.approx(1.0)

    def test_one_empty_returns_1(self):
        assert debate_text_distance("Something meaningful", "") == pytest.approx(1.0)

    def test_completely_different_near_1(self):
        d = debate_text_distance("abc def ghi", "xyz uvw rst")
        assert d >= 0.70

    def test_similar_texts_low_distance(self):
        base = "Will Apple maintain its premium pricing power in 2027?"
        same_ish = "Will Apple maintain its premium pricing power in 2027?"
        assert debate_text_distance(base, same_ish) < 0.10

    def test_distance_is_symmetric(self):
        a = "Bull thesis: margins expand"
        b = "Bear thesis: margins compress"
        assert debate_text_distance(a, b) == pytest.approx(debate_text_distance(b, a))


class TestIsMaterialThesisDelta:
    def test_stance_shifted_is_material(self):
        t = _thesis(change_vector={"stance_shifted": True})
        assert is_material_thesis_delta(t) is True

    def test_large_conviction_delta_is_material(self):
        t = _thesis(change_vector={"conviction_delta": 0.20})
        assert is_material_thesis_delta(t) is True

    def test_small_conviction_delta_not_material(self):
        t = _thesis(change_vector={"conviction_delta": 0.05})
        assert is_material_thesis_delta(t) is False

    def test_thesis_trend_strengthening_is_material(self):
        t = _thesis(thesis_trend="strengthening", change_vector={})
        assert is_material_thesis_delta(t) is True

    def test_thesis_trend_weakening_is_material(self):
        t = _thesis(thesis_trend="weakening", change_vector={})
        assert is_material_thesis_delta(t) is True

    def test_thesis_trend_stable_not_material(self):
        t = _thesis(thesis_trend="stable", change_vector={})
        assert is_material_thesis_delta(t) is False

    def test_null_change_vector_not_material(self):
        t = _thesis(change_vector=None)
        assert is_material_thesis_delta(t) is False

    def test_negative_conviction_delta_magnitude_checked(self):
        t = _thesis(change_vector={"conviction_delta": -0.20})
        assert is_material_thesis_delta(t) is True


class TestInferCurrentLean:
    @pytest.mark.parametrize("stance,expected", [
        ("Aggressive Buy", "bull"),
        ("Buy",            "bull"),
        ("Accumulate",     "bull"),
        ("Hold",           "balanced"),
        ("Tactical",       "balanced"),
        ("Avoid",          "bear"),
        ("Sell",           "bear"),
        ("Unknown",        "balanced"),   # fallback
        ("",               "balanced"),
    ])
    def test_stance_mapping(self, stance, expected):
        t = _thesis(directional_stance=stance)
        assert infer_current_lean(t) == expected


class TestScoreCatalystSpecificity:
    def test_vague_below_gate(self):
        assert score_catalyst_specificity("Things may improve") < SPECIFICITY_GATE

    def test_quantitative_threshold_adds_score(self):
        s = score_catalyst_specificity("Revenue >$100B next quarter")
        assert s >= SPECIFICITY_GATE

    def test_empty_string_returns_zero(self):
        assert score_catalyst_specificity("") == 0.0

    def test_full_specific_statement_high_score(self):
        s = score_catalyst_specificity(
            "EPS guidance raised above $7.50 in Q3 2027 earnings report"
        )
        assert s >= SPECIFICITY_GATE

    def test_score_bounded_at_1(self):
        assert score_catalyst_specificity(
            "Revenue >$100B in Q2 2027 earnings with EPS >$5 guidance raised"
        ) <= 1.0


class TestCatalystsMatch:
    def test_identical_statements_match(self):
        assert catalysts_match("Revenue beats guidance", "Revenue beats guidance") is True

    def test_very_similar_match(self):
        assert catalysts_match(
            "Revenue exceeds $100B in Q2 2027",
            "Revenue exceeds 100 billion in Q2 2027",
        ) is True

    def test_completely_different_no_match(self):
        assert catalysts_match("Rate cut by Fed in H1", "Revenue beats EPS") is False

    def test_empty_no_match(self):
        assert catalysts_match("", "something") is False
        assert catalysts_match("something", "") is False


class TestClaimHash:
    def test_deterministic(self):
        assert claim_hash("hello") == claim_hash("hello")

    def test_different_inputs_different_hashes(self):
        assert claim_hash("abc") != claim_hash("def")

    def test_returns_64_chars(self):
        assert len(claim_hash("test")) == 64

    def test_empty_string_safe(self):
        h = claim_hash("")
        assert len(h) == 64


class TestBuildRevisionDict:
    def test_has_required_keys(self):
        d = build_revision_dict(
            ticker="AAPL", facet="core_debate",
            prev_version=1, new_version=2,
            before={"q": "old"}, after={"q": "new"},
            change_summary="Changed", confidence=0.80,
            source_version_id="ver-001",
        )
        for key in ("ticker", "facet", "prev_version", "new_version",
                    "change_summary", "diff_json", "confidence",
                    "source_version_id"):
            assert key in d
        assert d["diff_json"]["before"] == {"q": "old"}
        assert d["diff_json"]["after"]  == {"q": "new"}


class TestBuildEvidenceDict:
    def test_has_required_keys(self):
        d = build_evidence_dict("AAPL", "core_debate", "Claim text",
                                source_type="thesis_version", source_id="ver-001")
        for key in ("ticker", "facet", "claim_hash", "source_type", "source_id"):
            assert key in d
        assert d["claim_hash"] == claim_hash("Claim text")

    def test_inferred_has_none_source_id(self):
        d = build_evidence_dict("AAPL", "moat_dimension", "claim",
                                source_type="inferred")
        assert d["source_id"] is None


# ===========================================================================
# 10. build_extraction_plan — integration
# ===========================================================================

class TestBuildExtractionPlan:
    def test_fallback_thesis_returns_empty_plan(self):
        t = _thesis(score_source="fallback_empty")
        plan = build_extraction_plan(
            payload          = _payload(),
            existing_dossier = _empty_dossier(),
            thesis           = t,
            version_id       = "v1",
        )
        assert plan.is_fallback is True
        assert plan.ops == []

    def test_valid_thesis_produces_ops(self):
        plan = build_extraction_plan(
            payload          = _payload(),
            existing_dossier = _empty_dossier(),
            thesis           = _thesis(),
            version_id       = "v1",
        )
        assert plan.is_fallback is False
        assert len(plan.ops) > 0

    def test_head_update_always_present(self):
        plan = build_extraction_plan(
            payload          = _payload(),
            existing_dossier = _empty_dossier(),
            thesis           = _thesis(),
            version_id       = "v1",
        )
        assert plan.head_update is not None
        assert plan.head_update["ticker"] == "AAPL"

    def test_debate_op_emitted_above_confidence_gate(self):
        plan = build_extraction_plan(
            payload          = _payload(debate_extraction_confidence=0.80),
            existing_dossier = _empty_dossier(),
            thesis           = _thesis(),
            version_id       = "v1",
        )
        debate_ops = [o for o in plan.ops if "debate" in o.kind]
        assert len(debate_ops) >= 1

    def test_debate_op_skipped_below_confidence_gate(self):
        plan = build_extraction_plan(
            payload          = _payload(debate_extraction_confidence=0.40),
            existing_dossier = _empty_dossier(),
            thesis           = _thesis(),
            version_id       = "v1",
        )
        debate_ops = [o for o in plan.ops if "debate" in o.kind]
        assert debate_ops == []
        assert plan.skipped_low_conf >= 1

    def test_durability_op_always_emitted(self):
        plan = build_extraction_plan(
            payload          = _payload(),
            existing_dossier = _empty_dossier(),
            thesis           = _thesis(),
            version_id       = "v1",
        )
        dur_ops = [o for o in plan.ops if o.kind == "write_durability"]
        assert len(dur_ops) == 1

    def test_moat_op_with_valid_axis(self):
        ax = MoatAxisExtract(axis="network_effects", strength="strong",
                             trend="stable", rationale="R", vulnerability="",
                             confidence=0.80)
        plan = build_extraction_plan(
            payload          = _payload(moat_axes=[ax], moat_extraction_confidence=0.80),
            existing_dossier = _empty_dossier(),
            thesis           = _thesis(),
            version_id       = "v1",
        )
        dim_ops = [o for o in plan.ops if o.kind == "upsert_dimension"]
        assert len(dim_ops) == 1

    def test_catalyst_below_specificity_gate_counted(self):
        cat = CatalystExtract(statement="Things might improve",
                              direction="bull_trigger", specificity=0.0,
                              expected_window="", conviction_weight=0.5)
        plan = build_extraction_plan(
            payload          = _payload(new_catalysts=[cat],
                                        catalyst_extraction_confidence=0.70),
            existing_dossier = _empty_dossier(),
            thesis           = _thesis(),
            version_id       = "v1",
        )
        assert plan.skipped_specificity >= 1

    def test_analysis_count_incremented(self):
        existing_head = _ns(analysis_count=5)
        dossier = {**_empty_dossier(), "head": existing_head}
        plan = build_extraction_plan(
            payload          = _payload(),
            existing_dossier = dossier,
            thesis           = _thesis(),
            version_id       = "v1",
        )
        assert plan.head_update["analysis_count"] == 6

    def test_ticker_carried_to_plan(self):
        plan = build_extraction_plan(
            payload          = _payload(),
            existing_dossier = _empty_dossier(),
            thesis           = _thesis(ticker="NVDA", company_name="Nvidia Corp."),
            version_id       = "v1",
        )
        assert plan.ticker == "NVDA"
        assert plan.head_update["ticker"] == "NVDA"

    def test_failure_mode_op_emitted_from_historical_analogs(self):
        analog = _ns(label="Cisco-2000", relevance_score=0.85,
                     drawdown_pct=0.72, time_to_trough_days=480)
        hist_ev = _ns(analogs=[analog])
        t = _thesis(historical_evidence=hist_ev)
        plan = build_extraction_plan(
            payload          = _payload(),
            existing_dossier = _empty_dossier(),
            thesis           = t,
            version_id       = "v1",
        )
        fm_ops = [o for o in plan.ops if o.kind == "upsert_failure_mode"]
        assert len(fm_ops) == 1
        assert fm_ops[0].kwargs["analog_label"] == "Cisco-2000"

    def test_source_version_id_on_plan(self):
        plan = build_extraction_plan(
            payload          = _payload(),
            existing_dossier = _empty_dossier(),
            thesis           = _thesis(),
            version_id       = "ver-xyz",
        )
        assert plan.source_version_id == "ver-xyz"

    def test_wall_cap_conclusion_is_fallback(self):
        t = _thesis(conclusion="wall cap exceeded: AAPL", confidence_score=0.72)
        plan = build_extraction_plan(
            payload          = _payload(),
            existing_dossier = _empty_dossier(),
            thesis           = t,
            version_id       = "v1",
        )
        assert plan.is_fallback is True
        assert plan.ops == []
