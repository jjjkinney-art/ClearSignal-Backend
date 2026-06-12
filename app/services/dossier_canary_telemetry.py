"""
Phase 9G · Slice 5C — In-process telemetry for the dossier injection canary.

Records two event types per eligible request:

  injection_decision  — cohort assignment + block metadata, logged pre-synthesis
  injection_outcome   — synthesis result fields, logged post-dispatch

These events feed the metric calculations in dossier_canary_metrics and are
surfaced by GET /admin/dossier-injection-status.

Also owns the runtime kill-switch state (POST /admin/dossier-injection/disable|enable).
The override is an in-process flag: it takes effect immediately without a
redeploy and survives until the process restarts.

Pure in-memory, process-local, thread-safe.  Resets on restart.
"""

from __future__ import annotations

import threading
from collections import Counter, deque
from typing import Any, Deque, Dict, List, Optional

_LOCK = threading.Lock()
_MAX_RECENT = 200

# ── Kill-switch runtime override ─────────────────────────────────────────────
# None  → use the config setting (dossier_injection_enabled)
# False → force-disabled regardless of config
# True  → force-enabled  regardless of config  (use with care)
_enabled_override: Optional[bool] = None


def get_enabled(config_enabled: bool) -> bool:
    """Resolve effective enabled state: override wins over config."""
    with _LOCK:
        if _enabled_override is None:
            return config_enabled
        return _enabled_override


def force_disable() -> None:
    """Tier-0 kill switch: disable injection immediately, no redeploy."""
    global _enabled_override
    with _LOCK:
        _enabled_override = False


def force_enable() -> None:
    """Re-enable injection (clears a force_disable; config still governs if no override)."""
    global _enabled_override
    with _LOCK:
        _enabled_override = True


def clear_override() -> None:
    """Remove the runtime override so config_enabled is used again."""
    global _enabled_override
    with _LOCK:
        _enabled_override = None


def override_state() -> Optional[bool]:
    with _LOCK:
        return _enabled_override


# ── Decision events ───────────────────────────────────────────────────────────
_decisions: Deque[Dict[str, Any]] = deque(maxlen=_MAX_RECENT)
_decision_cohort_counts: Counter = Counter()
_decision_total = 0


def record_decision(
    *,
    session_id: str,
    cohort: str,
    ticker: str,
    canary_pct: int,
    token_count: int,
    facets: List[str],
    staleness: str,
    dossier_age_days: Optional[float],
    prior_stance: Optional[str],
) -> None:
    """Record one pre-synthesis cohort assignment event."""
    global _decision_total
    with _LOCK:
        _decision_total += 1
        _decision_cohort_counts[cohort] += 1
        _decisions.appendleft({
            "session_id": session_id,
            "cohort":      cohort,
            "ticker":      ticker,
            "canary_pct":  canary_pct,
            "token_count": token_count,
            "facets":      list(facets or []),
            "staleness":   staleness,
            "dossier_age_days": dossier_age_days,
            "prior_stance": prior_stance,
        })


# ── Outcome events ────────────────────────────────────────────────────────────
_outcomes: Deque[Dict[str, Any]] = deque(maxlen=_MAX_RECENT)
_outcome_total = 0

# Rolling conviction accumulator per cohort, for a fast mean estimate.
_conviction_sum:   Dict[str, float] = {"injected": 0.0, "control": 0.0}
_conviction_count: Dict[str, int]   = {"injected": 0,   "control": 0}
_specificity_sum:  Dict[str, float] = {"injected": 0.0, "control": 0.0}
_specificity_count: Dict[str, int]  = {"injected": 0,   "control": 0}
_cve_sum:   Dict[str, float] = {"injected": 0.0, "control": 0.0}
_cve_count: Dict[str, int]   = {"injected": 0,   "control": 0}
_fallback_count: Dict[str, int] = {"injected": 0, "control": 0}
_override_count: Dict[str, int] = {"injected": 0, "control": 0}  # prior_challenged=True


def record_outcome(
    *,
    session_id: str,
    cohort: str,
    ticker: str,
    stance: Optional[str],
    conviction: Optional[float],
    change_vector_len: int,
    conclusion_len: int,
    specificity: Optional[float],
    fallback_used: bool,
    latency_s: Optional[float],
    prior_challenged: Optional[bool],
) -> None:
    """Record one post-synthesis outcome event."""
    global _outcome_total
    cve = (
        change_vector_len / conclusion_len
        if conclusion_len > 0 and change_vector_len >= 0
        else None
    )
    with _LOCK:
        _outcome_total += 1
        _outcomes.appendleft({
            "session_id":       session_id,
            "cohort":           cohort,
            "ticker":           ticker,
            "stance":           stance,
            "conviction":       conviction,
            "change_vector_len": change_vector_len,
            "conclusion_len":   conclusion_len,
            "cve":              cve,
            "specificity":      specificity,
            "fallback_used":    fallback_used,
            "latency_s":        latency_s,
            "prior_challenged": prior_challenged,
        })
        if cohort in _conviction_sum and conviction is not None:
            _conviction_sum[cohort]  += conviction
            _conviction_count[cohort] += 1
        if cohort in _specificity_sum and specificity is not None:
            _specificity_sum[cohort]  += specificity
            _specificity_count[cohort] += 1
        if cohort in _cve_sum and cve is not None:
            _cve_sum[cohort]  += cve
            _cve_count[cohort] += 1
        if cohort in _fallback_count and fallback_used:
            _fallback_count[cohort] += 1
        if cohort in _override_count and prior_challenged:
            _override_count[cohort] += 1


# ── Snapshot helpers ──────────────────────────────────────────────────────────

def _safe_mean(total: float, count: int) -> Optional[float]:
    if count == 0:
        return None
    return round(total / count, 4)


def snapshot_decisions() -> List[Dict[str, Any]]:
    with _LOCK:
        return list(_decisions)


def snapshot_outcomes() -> List[Dict[str, Any]]:
    with _LOCK:
        return list(_outcomes)


def snapshot() -> Dict[str, Any]:
    """Full JSON-serialisable canary telemetry snapshot."""
    with _LOCK:
        cohort_counts = dict(_decision_cohort_counts)
        conv_mean_inj  = _safe_mean(_conviction_sum["injected"],  _conviction_count["injected"])
        conv_mean_ctrl = _safe_mean(_conviction_sum["control"],   _conviction_count["control"])
        spec_mean_inj  = _safe_mean(_specificity_sum["injected"], _specificity_count["injected"])
        spec_mean_ctrl = _safe_mean(_specificity_sum["control"],  _specificity_count["control"])
        cve_mean_inj   = _safe_mean(_cve_sum["injected"],  _cve_count["injected"])
        cve_mean_ctrl  = _safe_mean(_cve_sum["control"],   _cve_count["control"])

        inj_outcomes = _conviction_count["injected"]
        ctrl_outcomes = _conviction_count["control"]

        override_rate_inj = (
            round(_override_count["injected"] / inj_outcomes, 4)
            if inj_outcomes > 0 else None
        )
        fallback_rate_inj = (
            round(_fallback_count["injected"] / inj_outcomes, 4)
            if inj_outcomes > 0 else None
        )
        fallback_rate_ctrl = (
            round(_fallback_count["control"] / ctrl_outcomes, 4)
            if ctrl_outcomes > 0 else None
        )

        return {
            "canary": {
                "decision_total":  _decision_total,
                "outcome_total":   _outcome_total,
                "cohort_counts":   cohort_counts,
                "enabled_override": _enabled_override,
            },
            "conviction": {
                "injected_mean":  conv_mean_inj,
                "control_mean":   conv_mean_ctrl,
                "injected_n":     _conviction_count["injected"],
                "control_n":      _conviction_count["control"],
            },
            "specificity": {
                "injected_mean":  spec_mean_inj,
                "control_mean":   spec_mean_ctrl,
            },
            "cve": {
                "injected_mean":  cve_mean_inj,
                "control_mean":   cve_mean_ctrl,
            },
            "echo": {
                "override_rate_injected": override_rate_inj,
            },
            "operational": {
                "fallback_rate_injected": fallback_rate_inj,
                "fallback_rate_control":  fallback_rate_ctrl,
            },
            "recent_decisions": list(_decisions)[:10],
            "recent_outcomes":  list(_outcomes)[:10],
        }


def reset() -> None:
    """Clear all canary telemetry and the kill-switch override (used by tests)."""
    global _decision_total, _outcome_total, _enabled_override
    with _LOCK:
        _decisions.clear()
        _outcomes.clear()
        _decision_cohort_counts.clear()
        for k in list(_conviction_sum):
            _conviction_sum[k] = 0.0
            _conviction_count[k] = 0
        for k in list(_specificity_sum):
            _specificity_sum[k] = 0.0
            _specificity_count[k] = 0
        for k in list(_cve_sum):
            _cve_sum[k] = 0.0
            _cve_count[k] = 0
        for k in list(_fallback_count):
            _fallback_count[k] = 0
        for k in list(_override_count):
            _override_count[k] = 0
        _decision_total = 0
        _outcome_total  = 0
        _enabled_override = None
