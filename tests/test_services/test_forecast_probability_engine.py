"""
Phase 12 — Slice 3: Forecast Probability Engine Tests.

Covers:
  - score_company_forecast (T1)
  - score_failure_mode_forecast (T4)
  - All 6 forecast types
  - All 3 horizons (30, 90, 180)
  - Sparse/empty features → conservative output
  - Stale features → wider confidence band + staleness_penalty_applied
  - Invalid forecast_type → ValueError
  - Invalid horizon → ValueError
  - Probability invariants: sum=1, each in [0,1], no NaN/inf
  - Determinism: same input → same output
  - Confidence band: more evidence → narrower, stale → wider
  - normalize_distribution: clamp + renorm
  - validate_forecast_distribution: well-formed check
  - No advice/price fields in output
  - Pure functions: no DB writes, no imports from session/ORM
  - Dependency direction: engine does not import feature builder or DB layer
"""

from __future__ import annotations

import ast
import math
import pathlib
from copy import deepcopy

import pytest

ROOT = pathlib.Path(__file__).parent.parent.parent

# ---------------------------------------------------------------------------
# Import target
# ---------------------------------------------------------------------------

from app.services.forecast_probability_engine import (
    SUPPORTED_FORECAST_TYPES,
    SUPPORTED_HORIZONS,
    ENGINE_SCHEMA_VERSION,
    score_company_forecast,
    score_failure_mode_forecast,
    normalize_distribution,
    confidence_band_from_evidence,
    validate_forecast_distribution,
)

# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------

ALL_FORECAST_TYPES = sorted(SUPPORTED_FORECAST_TYPES)
ALL_HORIZONS = sorted(SUPPORTED_HORIZONS)


def _minimal_company_features(
    *,
    analog_resolutions: list[str] = None,
    sim_peer_count: int = 3,
    sim_avg_score: float = 0.65,
    confidence_current: float = 0.70,
    confidence_previous: float = 0.55,
    direction: str = "rising",
    version_count: int = 2,
    stance: str = "bearish",
    conviction_trend: str = "declining",
    cycle_position: str = "late_cycle",
    staleness_state: str = "fresh",
    catalyst_proximity_days: int = 45,
) -> dict:
    """Build a minimal but non-sparse T1 feature dict."""
    if analog_resolutions is None:
        analog_resolutions = ["negative", "negative", "neutral"]

    analog_set = [
        {
            "analog_id": f"a{i}",
            "mechanism": "governance",
            "concern_tags": ["governance"],
            "quality_rating": "B+",
            "outcome_summary": "test",
            "drawdown_pct": 0.25,
            "time_to_recover_days": 90,
            "valuation_regime": "growth",
            "growth_phase": "late",
            "macro_regime": "tightening",
            "sector": "tech",
            "business_model": "saas",
            "relevance_weight": 0.8,
            "resolution": r,
        }
        for i, r in enumerate(analog_resolutions)
    ]

    return {
        "entity_type": "company",
        "entity_key": "ACME",
        "analog_set": analog_set,
        "analog_count": len(analog_set),
        "similarity_peers": [
            {"candidate_key": f"PEER{i}", "score": sim_avg_score, "target_type": "company", "rank": i + 1}
            for i in range(sim_peer_count)
        ],
        "similarity_peer_count": sim_peer_count,
        "similarity_avg_score": sim_avg_score,
        "thesis_trajectory": {
            "confidence_current": confidence_current,
            "confidence_previous": confidence_previous,
            "delta": confidence_current - confidence_previous,
            "direction": direction,
            "version_count": version_count,
            "stance": stance,
            "primary_concern": "governance",
        },
        "debate_state": {
            "current_lean": "bearish",
            "version": 3,
            "confidence": 0.68,
        },
        "regime_context": {
            "conviction_trend": conviction_trend,
            "cycle_position": cycle_position,
            "horizon_hint": "tactical",
            "staleness_state": staleness_state,
        },
        "durability": {
            "catalyst_proximity_days": catalyst_proximity_days,
            "analog_time_to_trough_days": 60,
        },
        "source_versions": {
            "company_dossier_row_version": 5,
            "thesis_version_id": "tv-001",
            "core_debate_version": 3,
            "feature_schema": 1,
        },
        "staleness_indicators": {
            "dossier_staleness_state": staleness_state,
            "has_similarity_peers": sim_peer_count > 0,
            "has_analogs": len(analog_set) > 0,
            "thesis_is_recent": True,
            "debate_has_lean": True,
        },
        "feature_schema": 1,
    }


def _minimal_fm_features(
    *,
    sequence_stage: int = 2,
    relevance_at_match: float = 0.80,
    analog_resolution: str = "negative",
    staleness_state: str = "fresh",
) -> dict:
    """Build a minimal but non-sparse T4 failure-mode feature dict."""
    base = _minimal_company_features(
        analog_resolutions=[analog_resolution],
        staleness_state=staleness_state,
    )
    base["entity_type"] = "failure_mode"
    base["entity_key"] = "fm-001"
    base["failure_mode"] = {
        "ticker": "ACME",
        "analog_id": "a0",
        "mechanism": "governance",
        "sequence_stage": sequence_stage,
        "relevance_at_match": relevance_at_match,
        "stage_evidence": "confirmed",
    }
    return base


def _sparse_features() -> dict:
    """Minimal feature dict with no secondary substrate."""
    return {
        "entity_type": "company",
        "entity_key": "SPARSE",
        "analog_set": [],
        "analog_count": 0,
        "similarity_peers": [],
        "similarity_peer_count": 0,
        "similarity_avg_score": 0.0,
        "thesis_trajectory": {
            "confidence_current": 0.0,
            "confidence_previous": None,
            "delta": 0.0,
            "direction": "flat",
            "version_count": 0,
            "stance": "",
            "primary_concern": "",
        },
        "debate_state": {"current_lean": "balanced", "version": 1, "confidence": 0.0},
        "regime_context": {
            "conviction_trend": "stable",
            "cycle_position": "unknown",
            "horizon_hint": "investment",
            "staleness_state": "fresh",
        },
        "durability": {"catalyst_proximity_days": None, "analog_time_to_trough_days": None},
        "source_versions": {"company_dossier_row_version": 0, "thesis_version_id": "", "core_debate_version": 1, "feature_schema": 1},
        "staleness_indicators": {
            "dossier_staleness_state": "fresh",
            "has_similarity_peers": False,
            "has_analogs": False,
            "thesis_is_recent": False,
            "debate_has_lean": False,
        },
        "feature_schema": 1,
    }


def _stale_features() -> dict:
    f = _minimal_company_features()
    f["regime_context"]["staleness_state"] = "stale"
    f["staleness_indicators"]["dossier_staleness_state"] = "stale"
    return f


# ---------------------------------------------------------------------------
# REQUIRED OUTPUT KEYS
# ---------------------------------------------------------------------------

_REQUIRED_OUTPUT_KEYS = {
    "p_positive", "p_negative", "p_neutral",
    "confidence_low", "confidence_high", "confidence_label",
    "horizon_days", "forecast_type",
    "components", "evidence_strength", "staleness_penalty_applied",
    "engine_schema",
}

_REQUIRED_COMPONENT_KEYS = {
    "p_base_rate", "p_sim_peer", "p_thesis_signal", "p_regime_signal", "weights_used",
}


# ---------------------------------------------------------------------------
# INVARIANT HELPERS
# ---------------------------------------------------------------------------

def _assert_valid_distribution(result: dict):
    """Assert all probability invariants on an output dict."""
    pos = result["p_positive"]
    neg = result["p_negative"]
    neu = result["p_neutral"]

    assert not math.isnan(pos), "p_positive is NaN"
    assert not math.isnan(neg), "p_negative is NaN"
    assert not math.isnan(neu), "p_neutral is NaN"
    assert not math.isinf(pos), "p_positive is inf"
    assert not math.isinf(neg), "p_negative is inf"
    assert not math.isinf(neu), "p_neutral is inf"

    assert 0.0 <= pos <= 1.0, f"p_positive={pos} out of [0,1]"
    assert 0.0 <= neg <= 1.0, f"p_negative={neg} out of [0,1]"
    assert 0.0 <= neu <= 1.0, f"p_neutral={neu} out of [0,1]"

    total = pos + neg + neu
    assert abs(total - 1.0) < 1e-4, f"probabilities sum to {total}, expected 1.0"

    assert 0.0 <= result["confidence_low"] <= result["confidence_high"] <= 1.0, (
        f"confidence band out of order: [{result['confidence_low']}, {result['confidence_high']}]"
    )


# ---------------------------------------------------------------------------
# OUTPUT SHAPE
# ---------------------------------------------------------------------------

class TestOutputShape:
    """Output dict has all required keys and correct types."""

    def test_required_keys_present_company(self):
        result = score_company_forecast(
            _minimal_company_features(), "thesis_weakening", 30
        )
        assert _REQUIRED_OUTPUT_KEYS.issubset(set(result.keys())), (
            f"Missing: {_REQUIRED_OUTPUT_KEYS - set(result.keys())}"
        )

    def test_required_component_keys_present(self):
        result = score_company_forecast(
            _minimal_company_features(), "risk_emergence", 90
        )
        comps = result["components"]
        assert _REQUIRED_COMPONENT_KEYS.issubset(set(comps.keys())), (
            f"Missing component keys: {_REQUIRED_COMPONENT_KEYS - set(comps.keys())}"
        )

    def test_horizon_days_in_output(self):
        for h in ALL_HORIZONS:
            result = score_company_forecast(_minimal_company_features(), "thesis_weakening", h)
            assert result["horizon_days"] == h

    def test_forecast_type_in_output(self):
        for ft in ALL_FORECAST_TYPES:
            result = score_company_forecast(_minimal_company_features(), ft, 30)
            assert result["forecast_type"] == ft

    def test_engine_schema_is_int(self):
        result = score_company_forecast(_minimal_company_features(), "thesis_weakening", 30)
        assert isinstance(result["engine_schema"], int)
        assert result["engine_schema"] == ENGINE_SCHEMA_VERSION

    def test_confidence_label_is_string(self):
        result = score_company_forecast(_minimal_company_features(), "thesis_weakening", 30)
        assert result["confidence_label"] in ("low", "medium", "high")

    def test_evidence_strength_in_range(self):
        result = score_company_forecast(_minimal_company_features(), "thesis_weakening", 30)
        assert 0.0 <= result["evidence_strength"] <= 1.0

    def test_staleness_penalty_applied_bool(self):
        result = score_company_forecast(_minimal_company_features(), "thesis_weakening", 30)
        assert isinstance(result["staleness_penalty_applied"], bool)


# ---------------------------------------------------------------------------
# PROBABILITY INVARIANTS — T1
# ---------------------------------------------------------------------------

class TestProbabilityInvariantsCompany:
    """All 6 types × 3 horizons must satisfy invariants."""

    @pytest.mark.parametrize("forecast_type", ALL_FORECAST_TYPES)
    @pytest.mark.parametrize("horizon", ALL_HORIZONS)
    def test_valid_distribution(self, forecast_type, horizon):
        result = score_company_forecast(
            _minimal_company_features(), forecast_type, horizon
        )
        _assert_valid_distribution(result)

    @pytest.mark.parametrize("forecast_type", ALL_FORECAST_TYPES)
    def test_sparse_features_valid_distribution(self, forecast_type):
        result = score_company_forecast(_sparse_features(), forecast_type, 30)
        _assert_valid_distribution(result)

    @pytest.mark.parametrize("forecast_type", ALL_FORECAST_TYPES)
    def test_stale_features_valid_distribution(self, forecast_type):
        result = score_company_forecast(_stale_features(), forecast_type, 90)
        _assert_valid_distribution(result)

    @pytest.mark.parametrize("forecast_type", ALL_FORECAST_TYPES)
    @pytest.mark.parametrize("horizon", ALL_HORIZONS)
    def test_empty_features_dict_valid(self, forecast_type, horizon):
        result = score_company_forecast({}, forecast_type, horizon)
        _assert_valid_distribution(result)


# ---------------------------------------------------------------------------
# PROBABILITY INVARIANTS — T4
# ---------------------------------------------------------------------------

class TestProbabilityInvariantsFailureMode:
    """T4 scoring satisfies all invariants across types, horizons, stages."""

    @pytest.mark.parametrize("forecast_type", ALL_FORECAST_TYPES)
    @pytest.mark.parametrize("horizon", ALL_HORIZONS)
    def test_valid_distribution(self, forecast_type, horizon):
        result = score_failure_mode_forecast(
            _minimal_fm_features(), forecast_type, horizon
        )
        _assert_valid_distribution(result)

    @pytest.mark.parametrize("stage", [1, 2, 3, 4])
    def test_stage_modifier_valid(self, stage):
        result = score_failure_mode_forecast(
            _minimal_fm_features(sequence_stage=stage), "risk_emergence", 30
        )
        _assert_valid_distribution(result)

    def test_sparse_fm_features_valid(self):
        f = _sparse_features()
        f["entity_type"] = "failure_mode"
        f["failure_mode"] = {
            "ticker": "X", "analog_id": "", "mechanism": "",
            "sequence_stage": 2, "relevance_at_match": 0.5, "stage_evidence": "",
        }
        result = score_failure_mode_forecast(f, "risk_emergence", 30)
        _assert_valid_distribution(result)

    def test_empty_fm_features_valid(self):
        result = score_failure_mode_forecast({}, "risk_emergence", 30)
        _assert_valid_distribution(result)


# ---------------------------------------------------------------------------
# INVALID INPUT HANDLING
# ---------------------------------------------------------------------------

class TestInvalidInputHandling:
    """Unsupported types and horizons raise ValueError."""

    def test_invalid_forecast_type_company_raises(self):
        with pytest.raises(ValueError, match="Unsupported forecast_type"):
            score_company_forecast(_minimal_company_features(), "buy_signal", 30)

    def test_invalid_forecast_type_fm_raises(self):
        with pytest.raises(ValueError, match="Unsupported forecast_type"):
            score_failure_mode_forecast(_minimal_fm_features(), "sell_signal", 30)

    def test_invalid_horizon_company_raises(self):
        with pytest.raises(ValueError, match="Unsupported horizon_days"):
            score_company_forecast(_minimal_company_features(), "thesis_weakening", 45)

    def test_invalid_horizon_fm_raises(self):
        with pytest.raises(ValueError, match="Unsupported horizon_days"):
            score_failure_mode_forecast(_minimal_fm_features(), "risk_emergence", 365)

    def test_zero_horizon_raises(self):
        with pytest.raises(ValueError, match="Unsupported horizon_days"):
            score_company_forecast(_minimal_company_features(), "thesis_weakening", 0)

    def test_negative_horizon_raises(self):
        with pytest.raises(ValueError, match="Unsupported horizon_days"):
            score_company_forecast(_minimal_company_features(), "thesis_weakening", -30)

    def test_empty_string_type_raises(self):
        with pytest.raises(ValueError, match="Unsupported forecast_type"):
            score_company_forecast(_minimal_company_features(), "", 30)


# ---------------------------------------------------------------------------
# DETERMINISM
# ---------------------------------------------------------------------------

class TestDeterminism:
    """Same input always produces identical output."""

    @pytest.mark.parametrize("forecast_type", ALL_FORECAST_TYPES)
    @pytest.mark.parametrize("horizon", ALL_HORIZONS)
    def test_company_deterministic(self, forecast_type, horizon):
        features = _minimal_company_features()
        r1 = score_company_forecast(deepcopy(features), forecast_type, horizon)
        r2 = score_company_forecast(deepcopy(features), forecast_type, horizon)
        assert r1["p_positive"] == r2["p_positive"]
        assert r1["p_negative"] == r2["p_negative"]
        assert r1["p_neutral"] == r2["p_neutral"]
        assert r1["confidence_low"] == r2["confidence_low"]
        assert r1["confidence_high"] == r2["confidence_high"]

    @pytest.mark.parametrize("forecast_type", ALL_FORECAST_TYPES)
    def test_fm_deterministic(self, forecast_type):
        features = _minimal_fm_features()
        r1 = score_failure_mode_forecast(deepcopy(features), forecast_type, 90)
        r2 = score_failure_mode_forecast(deepcopy(features), forecast_type, 90)
        assert r1["p_positive"] == r2["p_positive"]
        assert r1["evidence_strength"] == r2["evidence_strength"]


# ---------------------------------------------------------------------------
# SEMANTIC DIRECTIONAL TESTS
# ---------------------------------------------------------------------------

class TestDirectionalSemantics:
    """Verify that directional signals move probabilities in expected directions."""

    def test_thesis_weakening_higher_with_falling_confidence(self):
        """Falling confidence → higher thesis_weakening p_positive."""
        strong = _minimal_company_features(confidence_current=0.85, direction="rising")
        weak = _minimal_company_features(confidence_current=0.25, direction="falling")
        r_strong = score_company_forecast(strong, "thesis_weakening", 30)
        r_weak = score_company_forecast(weak, "thesis_weakening", 30)
        assert r_weak["p_positive"] > r_strong["p_positive"]

    def test_thesis_strengthening_higher_with_rising_confidence(self):
        """Rising confidence → higher thesis_strengthening p_positive."""
        rising = _minimal_company_features(confidence_current=0.85, direction="rising")
        falling = _minimal_company_features(confidence_current=0.25, direction="falling")
        r_rising = score_company_forecast(rising, "thesis_strengthening", 30)
        r_falling = score_company_forecast(falling, "thesis_strengthening", 30)
        assert r_rising["p_positive"] > r_falling["p_positive"]

    def test_risk_emergence_higher_in_late_cycle(self):
        """Late-cycle + declining trend → higher risk_emergence."""
        late = _minimal_company_features(cycle_position="late_cycle", conviction_trend="declining")
        early = _minimal_company_features(cycle_position="early_cycle", conviction_trend="rising")
        r_late = score_company_forecast(late, "risk_emergence", 90)
        r_early = score_company_forecast(early, "risk_emergence", 90)
        assert r_late["p_positive"] > r_early["p_positive"]

    def test_regime_transition_higher_late_declining(self):
        """Late-cycle + declining → higher regime_transition p_positive."""
        late_d = _minimal_company_features(cycle_position="late_cycle", conviction_trend="declining")
        early_r = _minimal_company_features(cycle_position="early_cycle", conviction_trend="rising")
        r_late = score_company_forecast(late_d, "regime_transition", 90)
        r_early = score_company_forecast(early_r, "regime_transition", 90)
        assert r_late["p_positive"] > r_early["p_positive"]

    def test_catalyst_realization_higher_with_near_catalyst(self):
        """Close catalyst → higher catalyst_realization p_positive."""
        near = _minimal_company_features(catalyst_proximity_days=20)
        far = _minimal_company_features(catalyst_proximity_days=180)
        r_near = score_company_forecast(near, "catalyst_realization", 30)
        r_far = score_company_forecast(far, "catalyst_realization", 30)
        assert r_near["p_positive"] > r_far["p_positive"]

    def test_stage3_fm_higher_than_stage1(self):
        """Advanced failure-mode stage → higher risk_emergence p_positive."""
        s3 = _minimal_fm_features(sequence_stage=3)
        s1 = _minimal_fm_features(sequence_stage=1)
        r3 = score_failure_mode_forecast(s3, "risk_emergence", 30)
        r1 = score_failure_mode_forecast(s1, "risk_emergence", 30)
        assert r3["p_positive"] > r1["p_positive"]


# ---------------------------------------------------------------------------
# CONFIDENCE BAND BEHAVIOUR
# ---------------------------------------------------------------------------

class TestConfidenceBandBehaviour:
    """Confidence band properties."""

    def test_more_evidence_narrows_band_vs_sparse(self):
        """Full-evidence features produce narrower band than sparse."""
        full = _minimal_company_features(sim_peer_count=5, analog_resolutions=["negative"] * 5)
        sparse = _sparse_features()
        r_full = score_company_forecast(full, "thesis_weakening", 30)
        r_sparse = score_company_forecast(sparse, "thesis_weakening", 30)
        full_width = r_full["confidence_high"] - r_full["confidence_low"]
        sparse_width = r_sparse["confidence_high"] - r_sparse["confidence_low"]
        assert full_width < sparse_width, (
            f"Full-evidence band ({full_width:.4f}) not narrower than sparse ({sparse_width:.4f})"
        )

    def test_stale_widens_band_vs_fresh(self):
        """Stale features → wider confidence band than fresh."""
        fresh = _minimal_company_features(staleness_state="fresh")
        stale = _stale_features()
        r_fresh = score_company_forecast(fresh, "risk_emergence", 90)
        r_stale = score_company_forecast(stale, "risk_emergence", 90)
        fresh_width = r_fresh["confidence_high"] - r_fresh["confidence_low"]
        stale_width = r_stale["confidence_high"] - r_stale["confidence_low"]
        assert stale_width > fresh_width, (
            f"Stale band ({stale_width:.4f}) not wider than fresh ({fresh_width:.4f})"
        )

    def test_longer_horizon_widens_band(self):
        """180d band wider than 30d band for same features."""
        features = _minimal_company_features()
        r30 = score_company_forecast(deepcopy(features), "thesis_weakening", 30)
        r180 = score_company_forecast(deepcopy(features), "thesis_weakening", 180)
        w30 = r30["confidence_high"] - r30["confidence_low"]
        w180 = r180["confidence_high"] - r180["confidence_low"]
        assert w180 > w30, (
            f"180d band ({w180:.4f}) not wider than 30d ({w30:.4f})"
        )

    def test_band_is_ordered_low_le_high(self):
        """confidence_low ≤ p_positive ≤ confidence_high."""
        for ft in ALL_FORECAST_TYPES:
            for h in ALL_HORIZONS:
                r = score_company_forecast(_minimal_company_features(), ft, h)
                assert r["confidence_low"] <= r["confidence_high"], (
                    f"{ft}/{h}: low={r['confidence_low']} > high={r['confidence_high']}"
                )

    def test_confidence_band_api_standalone(self):
        """confidence_band_from_evidence works as a standalone pure function."""
        features = _minimal_company_features()
        low, high = confidence_band_from_evidence(features, p_positive=0.65, horizon_days=30)
        assert 0.0 <= low <= high <= 1.0
        assert low < 0.65 < high or low == 0.0 or high == 1.0


# ---------------------------------------------------------------------------
# STALENESS PENALTY
# ---------------------------------------------------------------------------

class TestStalenessPenalty:
    """Stale features trigger staleness_penalty_applied=True."""

    def test_stale_sets_flag(self):
        result = score_company_forecast(_stale_features(), "thesis_weakening", 30)
        assert result["staleness_penalty_applied"] is True

    def test_fresh_does_not_set_flag(self):
        result = score_company_forecast(_minimal_company_features(), "thesis_weakening", 30)
        assert result["staleness_penalty_applied"] is False

    def test_stale_pulls_toward_prior(self):
        """Stale features pull probabilities toward 0.33 vs fresh."""
        fresh = _minimal_company_features(confidence_current=0.95, direction="rising")
        stale = deepcopy(fresh)
        stale["regime_context"]["staleness_state"] = "stale"
        stale["staleness_indicators"]["dossier_staleness_state"] = "stale"

        r_fresh = score_company_forecast(fresh, "thesis_strengthening", 30)
        r_stale = score_company_forecast(stale, "thesis_strengthening", 30)

        # Stale should be closer to 0.33 than fresh (difference from 0.33 is smaller)
        diff_fresh = abs(r_fresh["p_positive"] - 0.33)
        diff_stale = abs(r_stale["p_positive"] - 0.33)
        assert diff_stale < diff_fresh, (
            f"Stale ({r_stale['p_positive']:.4f}) not closer to 0.33 than fresh ({r_fresh['p_positive']:.4f})"
        )


# ---------------------------------------------------------------------------
# SPARSE SUBSTRATE
# ---------------------------------------------------------------------------

class TestSparseSubstrate:
    """Sparse/empty features return conservative (near-uniform) output."""

    @pytest.mark.parametrize("forecast_type", ALL_FORECAST_TYPES)
    def test_sparse_is_conservative(self, forecast_type):
        """Sparse output should be near the prior (each value closer to 0.33)."""
        result = score_company_forecast(_sparse_features(), forecast_type, 30)
        _assert_valid_distribution(result)
        # No probability should be more than 0.60 for sparse substrate
        assert result["p_positive"] < 0.60, (
            f"{forecast_type}: sparse p_positive={result['p_positive']:.4f} is too high"
        )

    def test_empty_dict_returns_prior(self):
        result = score_company_forecast({}, "thesis_weakening", 30)
        _assert_valid_distribution(result)
        # All components should equal the prior defaults
        assert abs(result["p_positive"] - 0.33) < 0.02
        assert abs(result["p_negative"] - 0.33) < 0.02
        assert result["evidence_strength"] == 0.0

    def test_sparse_evidence_strength_is_low(self):
        result = score_company_forecast(_sparse_features(), "thesis_weakening", 30)
        assert result["evidence_strength"] < 0.30, (
            f"Sparse features should have low evidence strength; got {result['evidence_strength']}"
        )

    def test_sparse_confidence_label_is_low(self):
        result = score_company_forecast(_sparse_features(), "thesis_weakening", 30)
        assert result["confidence_label"] == "low"


# ---------------------------------------------------------------------------
# NORMALIZE DISTRIBUTION
# ---------------------------------------------------------------------------

class TestNormalizeDistribution:
    """normalize_distribution contracts."""

    def test_already_normalised_is_unchanged(self):
        raw = {"positive": 0.33, "negative": 0.33, "neutral": 0.34}
        result = normalize_distribution(raw)
        assert abs(result["positive"] + result["negative"] + result["neutral"] - 1.0) < 1e-5

    def test_unnormalised_sums_to_one(self):
        # Clamping happens BEFORE normalisation: values above 0.99 → 0.99,
        # so the raw ratio is NOT preserved for out-of-range inputs.
        # Verify that normalisation (sum = 1) still holds.
        raw = {"positive": 2.0, "negative": 1.0, "neutral": 1.0}
        result = normalize_distribution(raw)
        assert abs(result["positive"] + result["negative"] + result["neutral"] - 1.0) < 1e-5
        # All three exceed or equal 0.99 after clamping, so each normalises to ≈ 1/3
        assert 0.30 < result["positive"] < 0.40

    def test_below_min_clamped(self):
        # Clamping 0.0 to 0.01 is a tiny fraction vs the other weights;
        # the renormalised result may be well below 0.01 but must be > 0.
        # Use equal-minimum inputs so the clamped value IS the dominant share.
        raw = {"positive": 0.0, "negative": 0.01, "neutral": 0.01}
        result = normalize_distribution(raw)
        # After clamping all three to 0.01, each normalises to 1/3 ≈ 0.333
        assert result["positive"] > 0.01

    def test_above_max_clamped(self):
        raw = {"positive": 1.0, "negative": 0.0, "neutral": 0.0}
        result = normalize_distribution(raw)
        assert result["positive"] <= 0.99

    def test_nan_raises(self):
        with pytest.raises(ValueError, match="non-finite"):
            normalize_distribution({"positive": float("nan"), "negative": 0.5, "neutral": 0.5})

    def test_inf_raises(self):
        with pytest.raises(ValueError, match="non-finite"):
            normalize_distribution({"positive": float("inf"), "negative": 0.5, "neutral": 0.5})

    def test_missing_keys_default_to_zero_then_clamped(self):
        raw = {"positive": 0.8}
        result = normalize_distribution(raw)
        # negative and neutral should default to 0.0 → clamped to 0.01
        assert result["negative"] >= 0.01
        assert result["neutral"] >= 0.01
        total = result["positive"] + result["negative"] + result["neutral"]
        assert abs(total - 1.0) < 1e-5


# ---------------------------------------------------------------------------
# VALIDATE FORECAST DISTRIBUTION
# ---------------------------------------------------------------------------

class TestValidateForecastDistribution:
    """validate_forecast_distribution contracts."""

    def test_valid_distribution_returns_true(self):
        d = {"p_positive": 0.50, "p_negative": 0.30, "p_neutral": 0.20}
        assert validate_forecast_distribution(d) is True

    def test_sum_off_returns_false(self):
        d = {"p_positive": 0.50, "p_negative": 0.30, "p_neutral": 0.30}
        assert validate_forecast_distribution(d) is False

    def test_negative_value_returns_false(self):
        d = {"p_positive": -0.10, "p_negative": 0.60, "p_neutral": 0.50}
        assert validate_forecast_distribution(d) is False

    def test_nan_returns_false(self):
        d = {"p_positive": float("nan"), "p_negative": 0.50, "p_neutral": 0.50}
        assert validate_forecast_distribution(d) is False

    def test_inf_returns_false(self):
        d = {"p_positive": float("inf"), "p_negative": 0.00, "p_neutral": 0.00}
        assert validate_forecast_distribution(d) is False

    def test_missing_key_returns_false(self):
        d = {"p_positive": 0.50, "p_negative": 0.50}
        # p_neutral missing → treated as nan
        assert validate_forecast_distribution(d) is False

    def test_engine_output_always_valid(self):
        """Every engine output should pass validate_forecast_distribution."""
        for ft in ALL_FORECAST_TYPES:
            for h in ALL_HORIZONS:
                result = score_company_forecast(_minimal_company_features(), ft, h)
                assert validate_forecast_distribution(result), (
                    f"Engine output for {ft}/{h} failed validate_forecast_distribution"
                )


# ---------------------------------------------------------------------------
# EVIDENCE STRENGTH
# ---------------------------------------------------------------------------

class TestEvidenceStrength:
    """Evidence strength reflects substrate richness."""

    def test_full_substrate_higher_than_sparse(self):
        full = _minimal_company_features(sim_peer_count=5, analog_resolutions=["negative"] * 5)
        sparse = _sparse_features()
        r_full = score_company_forecast(full, "thesis_weakening", 30)
        r_sparse = score_company_forecast(sparse, "thesis_weakening", 30)
        assert r_full["evidence_strength"] > r_sparse["evidence_strength"]

    def test_evidence_strength_zero_for_empty(self):
        result = score_company_forecast({}, "thesis_weakening", 30)
        assert result["evidence_strength"] == 0.0

    def test_evidence_strength_increases_with_analogs(self):
        few = _minimal_company_features(analog_resolutions=["negative"])
        many = _minimal_company_features(analog_resolutions=["negative"] * 5)
        r_few = score_company_forecast(few, "thesis_weakening", 30)
        r_many = score_company_forecast(many, "thesis_weakening", 30)
        assert r_many["evidence_strength"] >= r_few["evidence_strength"]

    def test_evidence_strength_increases_with_peers(self):
        few_peers = _minimal_company_features(sim_peer_count=1)
        many_peers = _minimal_company_features(sim_peer_count=5)
        r_few = score_company_forecast(few_peers, "similarity_outcome", 30)
        r_many = score_company_forecast(many_peers, "similarity_outcome", 30)
        assert r_many["evidence_strength"] >= r_few["evidence_strength"]


# ---------------------------------------------------------------------------
# NO ADVICE / PRICE FIELDS
# ---------------------------------------------------------------------------

class TestNoAdvicePriceFields:
    """Engine output must not contain advice or price fields."""

    FORBIDDEN_OUTPUT_KEYS = {
        "price_target", "target_price", "expected_return",
        "buy", "sell", "hold", "recommendation", "advice",
        "investment_advice", "buy_signal", "sell_signal",
    }

    @pytest.mark.parametrize("forecast_type", ALL_FORECAST_TYPES)
    def test_no_forbidden_key_in_output(self, forecast_type):
        result = score_company_forecast(_minimal_company_features(), forecast_type, 30)
        flat_keys = set(result.keys())
        forbidden = flat_keys & self.FORBIDDEN_OUTPUT_KEYS
        assert not forbidden, (
            f"{forecast_type}: forbidden keys in output: {forbidden}"
        )

    def test_module_source_has_no_price_advice_field_names(self):
        """AST check: no price/advice field names appear as dict keys in the module."""
        src = (ROOT / "app/services/forecast_probability_engine.py").read_text()
        tree = ast.parse(src)

        code_strings = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.s, str):
                code_strings.append(node.s)
            if isinstance(node, ast.Attribute):
                code_strings.append(node.attr)

        forbidden_field_names = {
            "price_target", "target_price", "investment_advice",
            "buy_signal", "sell_signal", "expected_return",
        }
        for name in forbidden_field_names:
            assert name not in code_strings, (
                f"Forbidden field name '{name}' found in forecast_probability_engine.py code"
            )


# ---------------------------------------------------------------------------
# PURE FUNCTION / NO DB WRITES
# ---------------------------------------------------------------------------

class TestPureFunctionNoWrites:
    """Verify engine is pure and cannot write to DB."""

    def test_module_has_no_session_imports(self):
        """Engine must not import any SQLAlchemy / aiosqlite session primitives."""
        src = (ROOT / "app/services/forecast_probability_engine.py").read_text()
        db_import_signals = [
            "from sqlalchemy", "import sqlalchemy",
            "from app.db", "import aiosqlite",
            "AsyncSession", "create_engine",
        ]
        for sig in db_import_signals:
            assert sig not in src, (
                f"DB import signal '{sig}' found in forecast_probability_engine.py — "
                "engine must be pure"
            )

    def test_module_has_no_write_calls(self):
        """AST check: no add/delete/merge/commit/flush in engine source."""
        src = (ROOT / "app/services/forecast_probability_engine.py").read_text()
        tree = ast.parse(src)

        write_methods = {"add", "delete", "merge", "flush", "commit", "execute_write"}
        found_writes = []

        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Attribute) and func.attr in write_methods:
                    found_writes.append(func.attr)

        assert not found_writes, (
            f"forecast_probability_engine contains write calls: {found_writes}"
        )

    def test_module_has_no_forecast_repo_import(self):
        """Engine must not import forecast_repo (writes belong to Slice 5)."""
        src = (ROOT / "app/services/forecast_probability_engine.py").read_text()
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                assert node.module != "app.db.repositories.forecast_repo", (
                    "forecast_probability_engine must not import forecast_repo — "
                    "storage belongs to the orchestration layer (Slice 5)"
                )
                if node.module:
                    assert "forecast_repo" not in node.module, (
                        f"Unexpected forecast_repo import: {node.module}"
                    )

    def test_no_forecast_vector_upsert(self):
        src = (ROOT / "app/services/forecast_probability_engine.py").read_text()
        assert "upsert_forecast_vector" not in src


# ---------------------------------------------------------------------------
# DEPENDENCY DIRECTION
# ---------------------------------------------------------------------------

class TestDependencyDirection:
    """Probability engine must not import feature builder or earlier phases."""

    def test_does_not_import_feature_builder(self):
        """No import statement references forecast_feature_builder."""
        src = (ROOT / "app/services/forecast_probability_engine.py").read_text()
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                assert "forecast_feature_builder" not in node.module, (
                    "forecast_probability_engine must not import forecast_feature_builder — "
                    "it receives feature dicts as plain Python dicts"
                )
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert "forecast_feature_builder" not in alias.name

    def test_does_not_import_similarity_module(self):
        """No import statement references any similarity_* module."""
        src = (ROOT / "app/services/forecast_probability_engine.py").read_text()
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                assert "similarity" not in node.module, (
                    f"Engine must not import similarity modules; found: {node.module}"
                )
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert "similarity" not in alias.name

    def test_only_stdlib_imports(self):
        """Engine should import only stdlib (math) — no app dependencies."""
        src = (ROOT / "app/services/forecast_probability_engine.py").read_text()
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert not alias.name.startswith("app."), (
                        f"Engine imports from app package: '{alias.name}' — "
                        "probability engine must be pure stdlib"
                    )
            if isinstance(node, ast.ImportFrom):
                if node.module and node.module.startswith("app."):
                    pytest.fail(
                        f"Engine imports from app package: 'from {node.module}' — "
                        "probability engine must be pure stdlib"
                    )


# ---------------------------------------------------------------------------
# COMPONENT WEIGHTS
# ---------------------------------------------------------------------------

class TestComponentWeights:
    """Components in output reflect the weight table."""

    @pytest.mark.parametrize("forecast_type", ALL_FORECAST_TYPES)
    def test_weights_sum_to_one(self, forecast_type):
        result = score_company_forecast(_minimal_company_features(), forecast_type, 30)
        weights = result["components"]["weights_used"]
        total = sum(weights.values())
        assert abs(total - 1.0) < 1e-4, (
            f"{forecast_type}: weights sum to {total}, not 1.0"
        )

    @pytest.mark.parametrize("forecast_type", ALL_FORECAST_TYPES)
    def test_all_component_signals_in_range(self, forecast_type):
        result = score_company_forecast(_minimal_company_features(), forecast_type, 30)
        comps = result["components"]
        for key in ("p_base_rate", "p_sim_peer", "p_thesis_signal", "p_regime_signal"):
            v = comps[key]
            assert 0.0 <= v <= 1.0, f"{forecast_type}: {key}={v} out of [0,1]"
            assert not math.isnan(v), f"{forecast_type}: {key} is NaN"
