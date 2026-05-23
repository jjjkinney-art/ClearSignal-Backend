"""
Watchlist monitoring intelligence — institutional change detector.

Combines thesis drift analysis with evidence freshness state to produce
curated WatchAlert objects for tickers under active surveillance.

Design philosophy
-----------------
This is NOT a retail stock alert system.  Only institutional-grade changes
trigger alerts:
  - Setup regime transitions (not minor wording shifts)
  - Conviction moves ≥ defined thresholds
  - Evidence going from stale → fresh (or fresh → stale)
  - Dominant driver pivots
  - Expectation fragility escalation above the compression threshold

Noise suppression (hard rules)
-------------------------------
  1. conviction_delta < 0.06 → NO alert (below minimum signal threshold)
  2. setup_label changes within the same conviction band → NO alert
     (e.g. "actionable thesis" ↔ "monitoring required" is flagged;
      "actionable thesis" ↔ "high-alignment thesis" is flagged as upgrade)
  3. driver wording edits with Jaccard similarity > 0.60 → NO alert
  4. freshness transitions require a dimension-level tier change (STALE → FRESH),
     not just a change in age_days

Alert types
-----------
SETUP_DOWNGRADE           setup moved toward lower conviction tier
SETUP_UPGRADE             setup moved toward higher conviction tier
CONVICTION_DROP           conviction_score fell materially (≥ threshold)
CONVICTION_RISE           conviction_score rose materially (≥ threshold)
DRIVER_SHIFT              dominant driver/debate topic pivoted
RISK_REGIME_CHANGE        primary risk characterization shifted
STALE_TO_FRESH            a previously stale evidence dimension became fresh
FRESH_TO_STALE            a previously fresh evidence dimension became stale
FRAGILITY_ESCALATION      expectation_fragility crossed the compression threshold
FRAGILITY_DE_ESCALATION   expectation_fragility dropped below compression threshold

Usage
-----
    from app.services.watchlist_monitor import watchlist_change_detector
    from app.services.freshness_analyzer import analyze_evidence_freshness
    from app.services.thesis_drift import detect_investment_thesis_drift

    freshness = analyze_evidence_freshness(current_evidence)
    drift = detect_investment_thesis_drift(current_thesis, prior_thesis)
    alerts = watchlist_change_detector(
        current=current_thesis,
        prior=prior_thesis,
        freshness=freshness,
        prior_freshness=prior_freshness,   # optional
        drift=drift,                        # optional, computed if absent
    )
"""
from __future__ import annotations

import dataclasses
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from ..schemas import InvestmentThesis
from .freshness_analyzer import FreshnessProfile, TIER_FRESH, TIER_STALE, TIER_VERY_STALE, TIER_UNKNOWN
from .thesis_drift import (
    InvestmentThesisDrift,
    detect_investment_thesis_drift,
    DRIFT_CONVICTION_DROP, DRIFT_CONVICTION_RISE,
    DRIFT_SETUP_DOWNGRADE, DRIFT_SETUP_UPGRADE,
    DRIFT_DRIVER_SHIFT, DRIFT_RISK_REGIME,
    DRIFT_STANCE_SHIFT,
)


# ── Alert severity levels ─────────────────────────────────────────────────────

SEVERITY_HIGH   = "high"
SEVERITY_MEDIUM = "medium"
SEVERITY_LOW    = "low"


# ── Alert types ───────────────────────────────────────────────────────────────

ALERT_SETUP_DOWNGRADE         = "SETUP_DOWNGRADE"
ALERT_SETUP_UPGRADE           = "SETUP_UPGRADE"
ALERT_CONVICTION_DROP         = "CONVICTION_DROP"
ALERT_CONVICTION_RISE         = "CONVICTION_RISE"
ALERT_DRIVER_SHIFT            = "DRIVER_SHIFT"
ALERT_RISK_REGIME             = "RISK_REGIME_CHANGE"
ALERT_STALE_TO_FRESH          = "STALE_TO_FRESH"
ALERT_FRESH_TO_STALE          = "FRESH_TO_STALE"
ALERT_FRAGILITY_ESCALATION    = "FRAGILITY_ESCALATION"
ALERT_FRAGILITY_DE_ESCALATION = "FRAGILITY_DE_ESCALATION"
ALERT_STANCE_SHIFT            = "STANCE_SHIFT"


# ── Fragility compression threshold ──────────────────────────────────────────
# Must match conviction_modeler.py — the score at which fragility starts
# applying a meaningful multiplier.

_FRAGILITY_COMPRESSION_THRESHOLD = 0.62


# ── Data structure ────────────────────────────────────────────────────────────

@dataclasses.dataclass
class WatchAlert:
    """A single institutional monitoring alert for a watched ticker.

    Attributes
    ----------
    ticker       : The watched ticker symbol.
    alert_type   : One of the ALERT_* constants.
    severity     : "high" | "medium" | "low"
    message      : Institutional-quality prose description (1-2 sentences).
    prior_value  : String representation of the prior state.
    current_value: String representation of the current state.
    conviction_delta : Signed delta in confidence_score (current − prior).
    generated_at : ISO-8601 UTC timestamp of alert generation.
    """
    ticker:          str
    alert_type:      str
    severity:        str
    message:         str
    prior_value:     str = ""
    current_value:   str = ""
    conviction_delta: float = 0.0
    generated_at:    str = dataclasses.field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> Dict[str, Any]:
        return dataclasses.asdict(self)


# ── Freshness tier comparison ─────────────────────────────────────────────────

def _stale_tier(tier: str) -> bool:
    return tier in (TIER_STALE, TIER_VERY_STALE)


def _fresh_tier(tier: str) -> bool:
    return tier == TIER_FRESH


# ── Alert builders ────────────────────────────────────────────────────────────

def _build_drift_alerts(
    ticker: str,
    drift: InvestmentThesisDrift,
) -> List[WatchAlert]:
    """Convert drift events into WatchAlerts."""
    alerts: List[WatchAlert] = []

    if DRIFT_SETUP_DOWNGRADE in drift.drift_types:
        alerts.append(WatchAlert(
            ticker=ticker,
            alert_type=ALERT_SETUP_DOWNGRADE,
            severity=SEVERITY_HIGH,
            message=(
                f"Setup downgraded from '{drift.setup_label_prior}' to "
                f"'{drift.setup_label_current}' — {ticker} is less actionable "
                "under current evidence conditions."
            ),
            prior_value=drift.setup_label_prior,
            current_value=drift.setup_label_current,
            conviction_delta=drift.conviction_delta,
        ))

    if DRIFT_SETUP_UPGRADE in drift.drift_types:
        alerts.append(WatchAlert(
            ticker=ticker,
            alert_type=ALERT_SETUP_UPGRADE,
            severity=SEVERITY_MEDIUM,
            message=(
                f"Setup upgraded from '{drift.setup_label_prior}' to "
                f"'{drift.setup_label_current}' — {ticker} conviction framework "
                "is more defensible."
            ),
            prior_value=drift.setup_label_prior,
            current_value=drift.setup_label_current,
            conviction_delta=drift.conviction_delta,
        ))

    if DRIFT_CONVICTION_DROP in drift.drift_types:
        alerts.append(WatchAlert(
            ticker=ticker,
            alert_type=ALERT_CONVICTION_DROP,
            severity=SEVERITY_HIGH if abs(drift.conviction_delta) >= 0.12 else SEVERITY_MEDIUM,
            message=(
                f"Conviction on {ticker} dropped {abs(drift.conviction_delta):.0%} — "
                "the evidence base or setup quality deteriorated. "
                "Review before acting on the prior thesis."
            ),
            prior_value=f"{(drift.conviction_delta + (drift.conviction_delta * -1 + drift.conviction_delta)):.0%}",
            current_value=f"{drift.conviction_delta:.0%}",
            conviction_delta=drift.conviction_delta,
        ))

    if DRIFT_CONVICTION_RISE in drift.drift_types:
        alerts.append(WatchAlert(
            ticker=ticker,
            alert_type=ALERT_CONVICTION_RISE,
            severity=SEVERITY_MEDIUM,
            message=(
                f"Conviction on {ticker} improved {drift.conviction_delta:.0%} — "
                "fresh evidence or improved setup quality strengthened the thesis."
            ),
            conviction_delta=drift.conviction_delta,
        ))

    if DRIFT_DRIVER_SHIFT in drift.drift_types:
        alerts.append(WatchAlert(
            ticker=ticker,
            alert_type=ALERT_DRIVER_SHIFT,
            severity=SEVERITY_HIGH,
            message=(
                f"Primary debate for {ticker} shifted — market focus moved "
                f"from '{drift.prior_dominant_driver}' toward "
                f"'{drift.current_dominant_driver}'."
            ),
            prior_value=drift.prior_dominant_driver,
            current_value=drift.current_dominant_driver,
            conviction_delta=drift.conviction_delta,
        ))

    if DRIFT_RISK_REGIME in drift.drift_types:
        alerts.append(WatchAlert(
            ticker=ticker,
            alert_type=ALERT_RISK_REGIME,
            severity=SEVERITY_HIGH,
            message=(
                f"Risk regime changed for {ticker} — the dominant risk characterization "
                "is materially different. Re-evaluate position sizing and hedges."
            ),
            conviction_delta=drift.conviction_delta,
        ))

    if DRIFT_STANCE_SHIFT in drift.drift_types:
        alerts.append(WatchAlert(
            ticker=ticker,
            alert_type=ALERT_STANCE_SHIFT,
            severity=SEVERITY_HIGH,
            message=(
                f"Valuation regime shifted for {ticker} — stance changed from "
                f"'{drift.setup_label_prior}' context. "
                "Revisit entry/exit levels."
            ),
            conviction_delta=drift.conviction_delta,
        ))

    return alerts


def _build_freshness_alerts(
    ticker: str,
    freshness: FreshnessProfile,
    prior_freshness: Optional[FreshnessProfile],
    conviction_delta: float,
) -> List[WatchAlert]:
    """Generate freshness transition alerts (stale→fresh and fresh→stale)."""
    if prior_freshness is None:
        return []

    alerts: List[WatchAlert] = []
    dim_names = ["earnings", "filing", "estimates", "valuation", "macro"]
    dim_labels = {
        "earnings":  "earnings evidence",
        "filing":    "SEC filing evidence",
        "estimates": "analyst estimates",
        "valuation": "live valuation ratios",
        "macro":     "macro context",
    }

    for dim in dim_names:
        cur_dim  = getattr(freshness, dim, None)
        prior_dim = getattr(prior_freshness, dim, None)
        if cur_dim is None or prior_dim is None:
            continue

        label = dim_labels.get(dim, dim)

        # STALE → FRESH: meaningful positive transition
        if _stale_tier(prior_dim.tier) and _fresh_tier(cur_dim.tier):
            alerts.append(WatchAlert(
                ticker=ticker,
                alert_type=ALERT_STALE_TO_FRESH,
                severity=SEVERITY_MEDIUM,
                message=(
                    f"Fresh {label} is now available for {ticker} — "
                    "previous analysis relied on stale data. "
                    "Conviction and valuation assumptions should be revisited."
                ),
                prior_value=f"{dim} stale ({prior_dim.age_days}d)",
                current_value=f"{dim} fresh ({cur_dim.age_days}d)" if cur_dim.age_days else f"{dim} fresh",
                conviction_delta=conviction_delta,
            ))

        # FRESH → STALE: degradation alert (evidence aging out)
        if _fresh_tier(prior_dim.tier) and _stale_tier(cur_dim.tier):
            alerts.append(WatchAlert(
                ticker=ticker,
                alert_type=ALERT_FRESH_TO_STALE,
                severity=SEVERITY_LOW,
                message=(
                    f"{label.title()} for {ticker} has aged out — "
                    f"data is now {cur_dim.age_days or '?'} days old. "
                    "Thesis assumptions may need to be refreshed."
                ),
                prior_value=f"{dim} fresh",
                current_value=f"{dim} stale ({cur_dim.age_days}d)",
                conviction_delta=conviction_delta,
            ))

    return alerts


def _build_fragility_alerts(
    ticker: str,
    current: InvestmentThesis,
    prior: InvestmentThesis,
    conviction_delta: float,
) -> List[WatchAlert]:
    """Alert on expectation_fragility crossing the compression threshold."""
    alerts: List[WatchAlert] = []

    cur_dims  = getattr(current, "conviction_dimensions", None) or {}
    prior_dims = getattr(prior, "conviction_dimensions", None) or {}

    cur_frag  = float(cur_dims.get("expectation_fragility", 0.0) or 0.0)
    prior_frag = float(prior_dims.get("expectation_fragility", 0.0) or 0.0)

    t = _FRAGILITY_COMPRESSION_THRESHOLD

    # Escalation: prior below threshold, current above
    if prior_frag < t <= cur_frag:
        alerts.append(WatchAlert(
            ticker=ticker,
            alert_type=ALERT_FRAGILITY_ESCALATION,
            severity=SEVERITY_HIGH,
            message=(
                f"Expectation fragility on {ticker} crossed the compression threshold "
                f"({prior_frag:.2f} → {cur_frag:.2f}) — the stock is now priced for "
                "near-perfect execution, compressing conviction meaningfully."
            ),
            prior_value=f"{prior_frag:.2f}",
            current_value=f"{cur_frag:.2f}",
            conviction_delta=conviction_delta,
        ))

    # De-escalation: prior above threshold, current below
    elif prior_frag >= t > cur_frag:
        alerts.append(WatchAlert(
            ticker=ticker,
            alert_type=ALERT_FRAGILITY_DE_ESCALATION,
            severity=SEVERITY_MEDIUM,
            message=(
                f"Expectation fragility on {ticker} dropped below the compression threshold "
                f"({prior_frag:.2f} → {cur_frag:.2f}) — the setup is less "
                "perfection-dependent, supporting higher conviction."
            ),
            prior_value=f"{prior_frag:.2f}",
            current_value=f"{cur_frag:.2f}",
            conviction_delta=conviction_delta,
        ))

    return alerts


# ── Public API ────────────────────────────────────────────────────────────────

def watchlist_change_detector(
    current:         InvestmentThesis,
    prior:           InvestmentThesis,
    freshness:       Optional[FreshnessProfile] = None,
    prior_freshness: Optional[FreshnessProfile] = None,
    drift:           Optional[InvestmentThesisDrift] = None,
) -> List[WatchAlert]:
    """Generate institutional WatchAlert objects for a watched ticker.

    Parameters
    ----------
    current         : Newly generated InvestmentThesis.
    prior           : Previously stored InvestmentThesis for the same ticker.
    freshness       : FreshnessProfile from the current evidence pool.
    prior_freshness : FreshnessProfile from the prior evidence pool (optional).
    drift           : Pre-computed InvestmentThesisDrift (computed if None).

    Returns
    -------
    List[WatchAlert] — ordered by severity (high first).
    Empty list when no institutional-grade changes are detected.
    """
    ticker = (current.ticker or "UNKNOWN").upper()

    # Compute drift if not supplied
    if drift is None:
        try:
            drift = detect_investment_thesis_drift(current, prior)
        except Exception:
            return []

    alerts: List[WatchAlert] = []

    # Drift-based alerts
    alerts.extend(_build_drift_alerts(ticker, drift))

    # Freshness transition alerts
    if freshness is not None:
        alerts.extend(_build_freshness_alerts(
            ticker, freshness, prior_freshness, drift.conviction_delta
        ))

    # Fragility threshold alerts
    alerts.extend(_build_fragility_alerts(
        ticker, current, prior, drift.conviction_delta
    ))

    # Sort: high severity first, then medium, then low
    _order = {SEVERITY_HIGH: 0, SEVERITY_MEDIUM: 1, SEVERITY_LOW: 2}
    alerts.sort(key=lambda a: _order.get(a.severity, 3))

    return alerts


def format_watch_alerts(alerts: List[WatchAlert]) -> str:
    """Format a list of WatchAlerts into an institutional-grade summary string.

    Returns empty string when alerts list is empty.
    Suitable for embedding in API responses or PM monitoring dashboards.
    """
    if not alerts:
        return ""

    lines = []
    for alert in alerts:
        sev_tag = {"high": "⚠", "medium": "◈", "low": "○"}.get(alert.severity, "·")
        lines.append(f"{sev_tag} [{alert.alert_type}] {alert.message}")
    return "\n".join(lines)
