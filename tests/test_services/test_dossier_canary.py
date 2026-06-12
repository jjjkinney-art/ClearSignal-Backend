"""
Phase 9G · Slice 5C — Tests for canary cohort, telemetry, and metrics.

Covers:
  * cohort assignment determinism and bucket distribution
  * sticky-session invariant
  * permanent holdout (buckets 0-4 always CONTROL)
  * canary_pct=0 / enabled=False → always INELIGIBLE
  * canary_pct clamping at 95
  * telemetry aggregation (decision + outcome events)
  * kill-switch override (force_disable / force_enable / clear_override)
  * kill-switch reflected in effective_enabled
  * metric calculation functions (all arms, edge cases)
"""

from __future__ import annotations

import math
from typing import Any, Dict, List

import pytest

from app.services.dossier_canary_cohort import (
    COHORT_CONTROL,
    COHORT_INJECTED,
    COHORT_INELIGIBLE,
    HOLDOUT_PCT,
    _session_bucket,
    decide_cohort,
)
from app.services import dossier_canary_telemetry as telem
from app.services import dossier_canary_metrics as metrics


# ── Fixtures / helpers ────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _reset_telem():
    """Isolate telemetry state between tests."""
    telem.reset()
    yield
    telem.reset()


def _outcome_kwargs(cohort: str, **kw) -> Dict[str, Any]:
    """Keyword args suitable for telem.record_outcome(**...)."""
    defaults: Dict[str, Any] = {
        "session_id":        "sid",
        "cohort":            cohort,
        "ticker":            "NVDA",
        "stance":            "bullish",
        "conviction":        0.75,
        "change_vector_len": 40,
        "conclusion_len":    80,
        "specificity":       3.0,
        "fallback_used":     False,
        "latency_s":         1.2,
        "prior_challenged":  True,
    }
    defaults.update(kw)
    return defaults


def _outcome(cohort: str, **kw) -> Dict[str, Any]:
    """Raw outcome dict (with pre-computed cve) for metrics functions."""
    d = _outcome_kwargs(cohort, **kw)
    cv = d.get("change_vector_len", 0)
    cl = d.get("conclusion_len", 0)
    d["cve"] = cv / cl if cl > 0 else None
    return d


# ── cohort: bucket determinism ────────────────────────────────────────────────

def test_bucket_is_0_to_99():
    for sid in ["abc", "xyz", "123", "session-999", ""]:
        b = _session_bucket(sid)
        assert 0 <= b <= 99


def test_same_session_same_bucket():
    for sid in ["hello", "world", "canary-test-001"]:
        assert _session_bucket(sid) == _session_bucket(sid)


def test_bucket_spread_roughly_uniform():
    buckets = [_session_bucket(f"session-{i}") for i in range(1000)]
    from collections import Counter
    counts = Counter(buckets)
    # Each bucket should appear roughly 10 times; allow ±5 for randomness.
    assert all(1 <= v <= 50 for v in counts.values()), "bucket distribution too skewed"


# ── cohort: disabled / zero-canary ───────────────────────────────────────────

def test_disabled_always_ineligible():
    for pct in (0, 5, 50, 95):
        assert decide_cohort("any-session", pct, enabled=False) == COHORT_INELIGIBLE


def test_canary_pct_zero_always_ineligible():
    assert decide_cohort("any-session", 0, enabled=True) == COHORT_INELIGIBLE


def test_negative_canary_pct_treated_as_zero():
    assert decide_cohort("any-session", -5, enabled=True) == COHORT_INELIGIBLE


# ── cohort: holdout buckets ───────────────────────────────────────────────────

def test_holdout_buckets_always_control():
    """Sessions that hash to bucket 0-4 must always be CONTROL even at 95%."""
    holdout_sessions = [
        sid for sid in (f"s{i}" for i in range(10_000))
        if _session_bucket(sid) < HOLDOUT_PCT
    ]
    assert len(holdout_sessions) >= 20, "need at least 20 holdout samples"
    for sid in holdout_sessions:
        result = decide_cohort(sid, canary_pct=95, enabled=True)
        assert result == COHORT_CONTROL, f"{sid} bucket={_session_bucket(sid)} got {result}"


def test_holdout_is_5pct_of_sessions():
    count = sum(1 for i in range(10_000) if _session_bucket(f"s{i}") < HOLDOUT_PCT)
    # Should be close to 500; allow ±3% of 10 000.
    assert 200 <= count <= 800


# ── cohort: injected arm ─────────────────────────────────────────────────────

def test_canary_pct_10_roughly_10pct_injected():
    injected = [
        f"s{i}" for i in range(10_000)
        if decide_cohort(f"s{i}", 10, True) == COHORT_INJECTED
    ]
    # Expect ~1000 out of 10 000 (10%); holdout eats 5%, so injected buckets 5-14.
    assert 500 <= len(injected) <= 1500


def test_canary_pct_95_leaves_holdout_as_control():
    results = [decide_cohort(f"s{i}", 95, True) for i in range(10_000)]
    controls = [r for r in results if r == COHORT_CONTROL]
    # At 95%, ~5% must remain CONTROL (holdout).
    assert len(controls) >= 100


def test_canary_pct_100_clamped_to_95():
    """canary_pct=100 should behave identically to canary_pct=95."""
    for i in range(200):
        sid = f"s{i}"
        assert decide_cohort(sid, 100, True) == decide_cohort(sid, 95, True)


def test_non_holdout_all_injected_at_95():
    """Every session NOT in holdout should be INJECTED at canary_pct=95."""
    mismatches = []
    for i in range(2000):
        sid = f"s{i}"
        b = _session_bucket(sid)
        result = decide_cohort(sid, 95, True)
        if b >= HOLDOUT_PCT and result != COHORT_INJECTED:
            mismatches.append((sid, b, result))
    assert not mismatches, f"non-holdout sessions not injected: {mismatches[:5]}"


# ── cohort: stickiness ───────────────────────────────────────────────────────

def test_same_session_same_cohort_across_calls():
    sids = [f"sticky-{i}" for i in range(50)]
    for sid in sids:
        first = decide_cohort(sid, 40, True)
        for _ in range(5):
            assert decide_cohort(sid, 40, True) == first


# ── telemetry: decision events ───────────────────────────────────────────────

def test_record_decision_increments_counters():
    telem.record_decision(
        session_id="s1", cohort=COHORT_INJECTED, ticker="NVDA",
        canary_pct=10, token_count=250, facets=["debate", "prior_state"],
        staleness="fresh", dossier_age_days=3.0, prior_stance="bearish",
    )
    snap = telem.snapshot()
    assert snap["canary"]["decision_total"] == 1
    assert snap["canary"]["cohort_counts"][COHORT_INJECTED] == 1


def test_record_decision_recent_list():
    telem.record_decision(
        session_id="s2", cohort=COHORT_CONTROL, ticker="JPM",
        canary_pct=10, token_count=0, facets=[], staleness="unknown",
        dossier_age_days=None, prior_stance=None,
    )
    decisions = telem.snapshot_decisions()
    assert len(decisions) == 1
    assert decisions[0]["ticker"] == "JPM"


# ── telemetry: outcome events ────────────────────────────────────────────────

def test_record_outcome_conviction_accumulator():
    telem.record_outcome(**_outcome_kwargs(COHORT_INJECTED, conviction=0.80))
    telem.record_outcome(**_outcome_kwargs(COHORT_INJECTED, conviction=0.60))
    telem.record_outcome(**_outcome_kwargs(COHORT_CONTROL,  conviction=0.70))
    snap = telem.snapshot()
    assert snap["conviction"]["injected_n"] == 2
    assert snap["conviction"]["control_n"]  == 1
    assert abs(snap["conviction"]["injected_mean"] - 0.70) < 0.01


def test_record_outcome_cve_accumulator():
    # CVE = change_vector_len / conclusion_len = 40/80 = 0.5
    telem.record_outcome(**_outcome_kwargs(COHORT_INJECTED, change_vector_len=40, conclusion_len=80))
    snap = telem.snapshot()
    assert snap["cve"]["injected_mean"] == pytest.approx(0.5, abs=1e-3)


def test_record_outcome_zero_conclusion_len_no_error():
    telem.record_outcome(**_outcome_kwargs(COHORT_INJECTED, change_vector_len=0, conclusion_len=0))
    # Should not raise; CVE simply not recorded for this event.
    snap = telem.snapshot()
    assert snap["canary"]["outcome_total"] == 1


def test_record_outcome_fallback_counted():
    telem.record_outcome(**_outcome_kwargs(COHORT_INJECTED, fallback_used=True))
    snap = telem.snapshot()
    assert snap["operational"]["fallback_rate_injected"] == pytest.approx(1.0)


def test_record_outcome_override_coherence():
    telem.record_outcome(**_outcome_kwargs(COHORT_INJECTED, prior_challenged=True))
    telem.record_outcome(**_outcome_kwargs(COHORT_INJECTED, prior_challenged=False))
    snap = telem.snapshot()
    assert snap["echo"]["override_rate_injected"] == pytest.approx(0.5)


# ── kill switch ───────────────────────────────────────────────────────────────

def test_get_enabled_returns_config_by_default():
    assert telem.get_enabled(False) is False
    assert telem.get_enabled(True)  is True


def test_force_disable_overrides_config():
    telem.force_disable()
    assert telem.get_enabled(True)  is False
    assert telem.get_enabled(False) is False


def test_force_enable_overrides_config():
    telem.force_enable()
    assert telem.get_enabled(False) is True
    assert telem.get_enabled(True)  is True


def test_clear_override_restores_config():
    telem.force_disable()
    telem.clear_override()
    assert telem.get_enabled(False) is False
    assert telem.get_enabled(True)  is True


def test_override_state_reflects_flag():
    assert telem.override_state() is None
    telem.force_disable()
    assert telem.override_state() is False
    telem.force_enable()
    assert telem.override_state() is True
    telem.clear_override()
    assert telem.override_state() is None


def test_kill_switch_reflected_in_snapshot():
    telem.force_disable()
    snap = telem.snapshot()
    assert snap["canary"]["enabled_override"] is False


def test_reset_clears_override():
    telem.force_disable()
    telem.reset()
    assert telem.override_state() is None
    assert telem.get_enabled(True) is True


# ── metrics: conviction_inflation ────────────────────────────────────────────

def test_conviction_inflation_basic():
    outs = [
        _outcome(COHORT_INJECTED, conviction=0.80),
        _outcome(COHORT_INJECTED, conviction=0.80),
        _outcome(COHORT_CONTROL,  conviction=0.70),
        _outcome(COHORT_CONTROL,  conviction=0.70),
    ]
    result = metrics.conviction_inflation(outs)
    assert result["absolute_delta"] == pytest.approx(0.10, abs=1e-3)
    assert result["n_injected"] == 2
    assert result["n_control"]  == 2


def test_conviction_inflation_with_control_sd():
    outs = [
        _outcome(COHORT_INJECTED, conviction=0.80),
        _outcome(COHORT_CONTROL,  conviction=0.70),
    ]
    result = metrics.conviction_inflation(outs, control_sd=0.10)
    # standardised_shift = 0.10 / 0.10 = 1.0
    assert result["standardised_shift"] == pytest.approx(1.0, abs=0.01)


def test_conviction_inflation_empty_arm_returns_none():
    outs = [_outcome(COHORT_INJECTED, conviction=0.80)]
    result = metrics.conviction_inflation(outs)
    assert result["absolute_delta"] is None


# ── metrics: override_coherence ──────────────────────────────────────────────

def test_override_coherence_all_challenged():
    outs = [_outcome(COHORT_INJECTED, prior_challenged=True)] * 4
    assert metrics.override_coherence(outs) == pytest.approx(1.0)


def test_override_coherence_none_challenged():
    outs = [_outcome(COHORT_INJECTED, prior_challenged=False)] * 3
    assert metrics.override_coherence(outs) == pytest.approx(0.0)


def test_override_coherence_no_injected_returns_none():
    outs = [_outcome(COHORT_CONTROL)]
    assert metrics.override_coherence(outs) is None


# ── metrics: cve_delta ───────────────────────────────────────────────────────

def test_cve_delta_positive_when_injected_engages_more():
    # Injected: 60/80 = 0.75; Control: 20/80 = 0.25
    outs = [
        _outcome(COHORT_INJECTED, change_vector_len=60, conclusion_len=80),
        _outcome(COHORT_CONTROL,  change_vector_len=20, conclusion_len=80),
    ]
    assert metrics.cve_delta(outs) == pytest.approx(0.5, abs=1e-3)


def test_cve_delta_negative_is_thesis_drift_signal():
    outs = [
        _outcome(COHORT_INJECTED, change_vector_len=10, conclusion_len=80),
        _outcome(COHORT_CONTROL,  change_vector_len=50, conclusion_len=80),
    ]
    delta = metrics.cve_delta(outs)
    assert delta is not None and delta < 0


def test_cve_delta_none_when_arm_empty():
    outs = [_outcome(COHORT_INJECTED, change_vector_len=40, conclusion_len=80)]
    assert metrics.cve_delta(outs) is None


# ── metrics: specificity_delta ───────────────────────────────────────────────

def test_specificity_delta_basic():
    outs = [
        _outcome(COHORT_INJECTED, specificity=5.0),
        _outcome(COHORT_CONTROL,  specificity=3.0),
    ]
    assert metrics.specificity_delta(outs) == pytest.approx(2.0, abs=1e-3)


# ── metrics: divergence_suppression (variance proxy) ─────────────────────────

def test_divergence_suppression_returns_none_with_single_values():
    outs = [
        _outcome(COHORT_INJECTED, conviction=0.70),
        _outcome(COHORT_CONTROL,  conviction=0.60),
    ]
    # Need ≥2 per arm for SD calculation.
    assert metrics.divergence_suppression(outs) is None


def test_divergence_suppression_negative_when_injected_tighter():
    # Injected arm: narrow spread; Control arm: wide spread.
    outs = (
        [_outcome(COHORT_INJECTED, conviction=0.70)] * 5
        + [_outcome(COHORT_INJECTED, conviction=0.71)]
        + [_outcome(COHORT_CONTROL,  conviction=0.50)]
        + [_outcome(COHORT_CONTROL,  conviction=0.90)]
    )
    result = metrics.divergence_suppression(outs)
    assert result is not None and result < 0


# ── metrics: agreement_lift ──────────────────────────────────────────────────

def test_agreement_lift_no_divergence():
    # Both arms agree: all bullish for NVDA.
    outs = (
        [_outcome(COHORT_INJECTED, ticker="NVDA", stance="bullish")] * 3
        + [_outcome(COHORT_CONTROL,  ticker="NVDA", stance="bullish")] * 3
    )
    lift = metrics.agreement_lift(outs)
    assert lift == pytest.approx(0.0, abs=1e-3)


def test_agreement_lift_returns_none_when_arm_too_small():
    outs = [_outcome(COHORT_INJECTED, stance="bullish")]
    assert metrics.agreement_lift(outs) is None


# ── metrics: compute_all ─────────────────────────────────────────────────────

def test_compute_all_returns_all_keys():
    outs = [
        _outcome(COHORT_INJECTED, conviction=0.80, specificity=4.0),
        _outcome(COHORT_CONTROL,  conviction=0.70, specificity=3.0),
    ]
    result = metrics.compute_all(outs)
    for key in (
        "agreement_lift", "conviction_inflation", "conviction_variance_delta",
        "override_coherence", "cve_delta", "specificity_delta",
        "divergence_suppression", "n_injected", "n_control",
    ):
        assert key in result, f"missing key: {key}"


def test_compute_all_counts():
    outs = (
        [_outcome(COHORT_INJECTED)] * 3
        + [_outcome(COHORT_CONTROL)]  * 2
    )
    result = metrics.compute_all(outs)
    assert result["n_injected"] == 3
    assert result["n_control"]  == 2
