"""
Phase 9G · Slice 5C — Canary metric calculations.

Pure functions — no I/O, no side effects.  All inputs are lists of outcome dicts
as produced by dossier_canary_telemetry.snapshot_outcomes().

Metrics surfaced here:

  agreement_lift        — do injected sessions arrive at the same stance as control?
  conviction_inflation  — mean conviction delta (injected − control), absolute and
                          standardised (requires baseline SD from S1b)
  override_coherence    — fraction of injected sessions where prior_challenged=True
  cve_delta             — change-vector engagement ratio delta (thesis-drift guard)
  specificity_delta     — numeric-specificity mean delta (injected − control)
  divergence_suppression— conviction variance delta proxy (anchoring narrows spread)

No gating logic is implemented here — that lives in the advance-gate layer (Slice 5D).
These are calculation primitives only.
"""

from __future__ import annotations

import math
import statistics
from typing import Any, Dict, List, Optional

from .dossier_canary_cohort import COHORT_INJECTED, COHORT_CONTROL


# ── Helpers ───────────────────────────────────────────────────────────────────

def _arm(outcomes: List[Dict[str, Any]], cohort: str) -> List[Dict[str, Any]]:
    return [r for r in outcomes if r.get("cohort") == cohort]


def _field(records: List[Dict[str, Any]], key: str) -> List[float]:
    """Extract non-None numeric values for key from records."""
    out = []
    for r in records:
        v = r.get(key)
        if v is not None:
            try:
                out.append(float(v))
            except (TypeError, ValueError):
                pass
    return out


def _mean_safe(vals: List[float]) -> Optional[float]:
    if not vals:
        return None
    return statistics.mean(vals)


def _stdev_safe(vals: List[float]) -> Optional[float]:
    if len(vals) < 2:
        return None
    return statistics.stdev(vals)


# ── Metric functions ──────────────────────────────────────────────────────────

def agreement_lift(outcomes: List[Dict[str, Any]]) -> Optional[float]:
    """Fraction of injected outcomes where stance agrees with the control arm's
    modal stance for the same ticker.

    Returns the difference (injected_agreement_rate − control_agreement_rate).
    A positive value means injection pushes toward the control-arm consensus;
    negative means injection diverges from it.  Returns None if either arm has
    insufficient data (< 2 records).
    """
    inj = _arm(outcomes, COHORT_INJECTED)
    ctrl = _arm(outcomes, COHORT_CONTROL)
    if len(inj) < 2 or len(ctrl) < 2:
        return None

    # Build ticker→modal_stance from the control arm.
    from collections import Counter
    ctrl_by_ticker: Dict[str, Counter] = {}
    for r in ctrl:
        t = r.get("ticker") or "_unknown"
        s = r.get("stance")
        if s:
            ctrl_by_ticker.setdefault(t, Counter())[s] += 1

    ctrl_modal: Dict[str, str] = {
        t: cnt.most_common(1)[0][0] for t, cnt in ctrl_by_ticker.items()
    }

    # For each injected record, check if it agrees with the control modal stance.
    inj_eligible = [r for r in inj if r.get("ticker") in ctrl_modal and r.get("stance")]
    if not inj_eligible:
        return None

    inj_agree = sum(
        1 for r in inj_eligible
        if r["stance"] == ctrl_modal.get(r["ticker"])
    )
    inj_rate = inj_agree / len(inj_eligible)

    # Compute the control's own self-agreement rate (fraction that match modal).
    ctrl_eligible = [r for r in ctrl if r.get("ticker") in ctrl_modal and r.get("stance")]
    ctrl_agree = sum(
        1 for r in ctrl_eligible
        if r["stance"] == ctrl_modal.get(r["ticker"])
    )
    ctrl_rate = ctrl_agree / len(ctrl_eligible) if ctrl_eligible else 0.0

    return round(inj_rate - ctrl_rate, 4)


def conviction_inflation(
    outcomes: List[Dict[str, Any]],
    control_sd: Optional[float] = None,
) -> Dict[str, Any]:
    """Mean conviction delta and standardised shift between injected and control arms.

    Args:
        outcomes:    flat list of outcome records.
        control_sd:  SD of conviction in the control arm, measured at S1b baseline.
                     When None (pre-S1b), only the absolute delta is computable.

    Returns dict with:
        mean_injected, mean_control, absolute_delta,
        standardised_shift (None until control_sd is known),
        n_injected, n_control.
    """
    inj_vals  = _field(_arm(outcomes, COHORT_INJECTED), "conviction")
    ctrl_vals = _field(_arm(outcomes, COHORT_CONTROL),  "conviction")

    mean_inj  = _mean_safe(inj_vals)
    mean_ctrl = _mean_safe(ctrl_vals)

    abs_delta = (
        round(mean_inj - mean_ctrl, 4)
        if mean_inj is not None and mean_ctrl is not None
        else None
    )
    std_shift = (
        round(abs_delta / control_sd, 4)
        if abs_delta is not None and control_sd and control_sd > 0
        else None
    )

    return {
        "mean_injected":    round(mean_inj, 4)  if mean_inj  is not None else None,
        "mean_control":     round(mean_ctrl, 4) if mean_ctrl is not None else None,
        "absolute_delta":   abs_delta,
        "standardised_shift": std_shift,
        "n_injected":       len(inj_vals),
        "n_control":        len(ctrl_vals),
    }


def conviction_variance_delta(outcomes: List[Dict[str, Any]]) -> Optional[float]:
    """SD of conviction in injected arm minus SD in control arm.

    Anchoring can suppress conviction variance even while keeping the mean
    stable.  A negative (or very low) value here means the injected arm has
    less spread — consistent with the prior narrowing the model's output range.
    """
    inj_vals  = _field(_arm(outcomes, COHORT_INJECTED), "conviction")
    ctrl_vals = _field(_arm(outcomes, COHORT_CONTROL),  "conviction")
    sd_inj  = _stdev_safe(inj_vals)
    sd_ctrl = _stdev_safe(ctrl_vals)
    if sd_inj is None or sd_ctrl is None:
        return None
    return round(sd_inj - sd_ctrl, 4)


def override_coherence(outcomes: List[Dict[str, Any]]) -> Optional[float]:
    """Fraction of injected outcomes where prior_challenged=True.

    High coherence means the model is engaging with the prior (acknowledging it
    or explaining why it was revised).  A falling rate in the injected arm
    suggests the model is silently deferring rather than reasoning through the prior.
    """
    inj = _arm(outcomes, COHORT_INJECTED)
    eligible = [r for r in inj if r.get("prior_challenged") is not None]
    if not eligible:
        return None
    challenged = sum(1 for r in eligible if r["prior_challenged"])
    return round(challenged / len(eligible), 4)


def cve_delta(outcomes: List[Dict[str, Any]]) -> Optional[float]:
    """Change-vector engagement ratio delta: mean(CVE_injected) − mean(CVE_control).

    CVE = change_vector_len / conclusion_len per outcome record.
    Negative CVE_delta means injected responses engage less with what changed —
    the thesis-drift signal (model concluding without reasoning through the delta).
    """
    inj_vals  = _field(_arm(outcomes, COHORT_INJECTED), "cve")
    ctrl_vals = _field(_arm(outcomes, COHORT_CONTROL),  "cve")
    m_inj  = _mean_safe(inj_vals)
    m_ctrl = _mean_safe(ctrl_vals)
    if m_inj is None or m_ctrl is None:
        return None
    return round(m_inj - m_ctrl, 4)


def specificity_delta(outcomes: List[Dict[str, Any]]) -> Optional[float]:
    """Mean numeric-specificity delta: mean(injected) − mean(control).

    Positive = injected responses cite more numbers (expected if injection adds
    grounding).  Negative = injected responses are less number-grounded than
    control, a quality regression signal.
    """
    inj_vals  = _field(_arm(outcomes, COHORT_INJECTED), "specificity")
    ctrl_vals = _field(_arm(outcomes, COHORT_CONTROL),  "specificity")
    m_inj  = _mean_safe(inj_vals)
    m_ctrl = _mean_safe(ctrl_vals)
    if m_inj is None or m_ctrl is None:
        return None
    return round(m_inj - m_ctrl, 4)


def divergence_suppression(outcomes: List[Dict[str, Any]]) -> Optional[float]:
    """Conviction-variance proxy for divergence suppression.

    Divergence suppression = injected sessions converging on the prior's view
    even when fresh evidence points elsewhere.  The conviction-variance delta
    (injected SD − control SD) is a measurable proxy: anchoring narrows the
    output distribution around the prior.

    This is a structural placeholder for the full thesis-distance metric
    (Slice 5D), which requires per-record thesis-distance scores.  For now,
    returns conviction_variance_delta as the available proxy.
    """
    return conviction_variance_delta(outcomes)


def compute_all(
    outcomes: List[Dict[str, Any]],
    control_sd: Optional[float] = None,
) -> Dict[str, Any]:
    """Compute all canary metrics in one pass.  Returns a dict suitable for
    embedding directly in the admin status response."""
    return {
        "agreement_lift":         agreement_lift(outcomes),
        "conviction_inflation":   conviction_inflation(outcomes, control_sd=control_sd),
        "conviction_variance_delta": conviction_variance_delta(outcomes),
        "override_coherence":     override_coherence(outcomes),
        "cve_delta":              cve_delta(outcomes),
        "specificity_delta":      specificity_delta(outcomes),
        "divergence_suppression": divergence_suppression(outcomes),
        "n_injected":             len(_arm(outcomes, COHORT_INJECTED)),
        "n_control":              len(_arm(outcomes, COHORT_CONTROL)),
    }
