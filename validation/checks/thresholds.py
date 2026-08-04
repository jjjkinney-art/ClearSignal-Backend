"""Objective 6 — decision_thresholds validation."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..models import Finding, QueryFixture, Severity

_VALID_DIRECTIONS = {"higher_is_better", "lower_is_better"}


def _num(v: Any) -> Optional[float]:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def check(thesis: Dict[str, Any], fixture: QueryFixture) -> List[Finding]:
    findings: List[Finding] = []
    thresholds = thesis.get("decision_thresholds") if isinstance(thesis, dict) else None
    if thresholds is None:
        return findings  # optional; presence tracked separately
    if not isinstance(thresholds, list):
        findings.append(Finding(
            code="malformed_thresholds", severity=Severity.HIGH, field="decision_thresholds",
            message="decision_thresholds is present but is not a list.",
        ))
        return findings

    for i, t in enumerate(thresholds):
        loc = f"decision_thresholds[{i}]"
        if not isinstance(t, dict):
            findings.append(Finding(
                code="malformed_threshold", severity=Severity.MEDIUM, field=loc,
                message="Threshold entry is not a JSON object.",
            ))
            continue

        metric = t.get("metric")
        if not metric:
            findings.append(Finding(
                code="threshold_missing_metric", severity=Severity.HIGH, field=loc,
                message="Threshold has no metric name.",
            ))

        unavailable = bool(t.get("unavailable"))
        display = t.get("display")
        if not display:
            findings.append(Finding(
                code="threshold_display_not_readable", severity=Severity.MEDIUM, field=loc,
                message=f"Threshold for '{metric}' has no readable display text.",
            ))

        if unavailable:
            if not t.get("reason"):
                findings.append(Finding(
                    code="unavailable_threshold_missing_reason", severity=Severity.MEDIUM, field=loc,
                    message=f"Threshold for '{metric}' is marked unavailable but has no reason.",
                ))
            # An unavailable threshold correctly has no bull/bear boundaries to validate further.
            continue

        # From here on the threshold claims to be a valid, actionable band.
        direction = str(t.get("direction", "")).strip().lower()
        if direction and direction not in _VALID_DIRECTIONS:
            findings.append(Finding(
                code="threshold_invalid_direction", severity=Severity.MEDIUM, field=loc,
                message=f"Direction '{direction}' is not one of {sorted(_VALID_DIRECTIONS)}.",
            ))

        bull = _num(t.get("bull_boundary"))
        bear = _num(t.get("bear_boundary"))

        if bull is None or bear is None:
            findings.append(Finding(
                code="threshold_missing_boundaries", severity=Severity.HIGH, field=loc,
                message=f"Threshold for '{metric}' is marked available but is missing numeric bull/bear boundaries.",
            ))
            continue

        # Identical bull and bear boundaries — no neutral interval possible.
        if bull == bear:
            findings.append(Finding(
                code="threshold_identical_boundaries", severity=Severity.CRITICAL, field=loc,
                message=f"Threshold for '{metric}' has identical bull and bear boundaries ({bull}).",
            ))
            continue

        # Directional coherence + overlap check — mirrors the backend's own
        # invariant, re-checked independently against the live response.
        incoherent = False
        if direction == "lower_is_better" and bull >= bear:
            incoherent = True
        elif direction == "higher_is_better" and bull <= bear:
            incoherent = True
        elif not direction:
            # No explicit direction — infer from which boundary is numerically
            # lower and flag only a genuine overlap (bull == bear already
            # caught above; anything else is at minimum a warning that we
            # couldn't confirm coherence).
            findings.append(Finding(
                code="threshold_direction_unconfirmed", severity=Severity.LOW, field=loc,
                message=f"Threshold for '{metric}' has no direction; coherence could not be fully verified.",
            ))

        if incoherent:
            findings.append(Finding(
                code="threshold_shown_available_but_contradictory", severity=Severity.CRITICAL, field=loc,
                message=(
                    f"Threshold for '{metric}' is marked available but bull/bear boundaries are "
                    f"incoherent for direction={direction} (bull={bull}, bear={bear}) — "
                    "the exact overlapping bull<31x/bear>28x class of bug."
                ),
            ))

        # Neutral interval presence + ordering.
        ni = t.get("neutral_interval")
        if isinstance(ni, list) and len(ni) == 2:
            lo, hi = _num(ni[0]), _num(ni[1])
            if lo is None or hi is None or lo > hi:
                findings.append(Finding(
                    code="threshold_neutral_interval_disordered", severity=Severity.HIGH, field=loc,
                    message=f"neutral_interval {ni} is not a valid ascending [low, high] pair.",
                ))
        elif not incoherent:
            findings.append(Finding(
                code="threshold_missing_neutral_interval", severity=Severity.MEDIUM, field=loc,
                message=f"Threshold for '{metric}' has no neutral_interval.",
            ))

        # Unit consistency: bull/bear/neutral values should share one unit field.
        unit = t.get("unit")
        if not unit:
            findings.append(Finding(
                code="threshold_missing_unit", severity=Severity.LOW, field=loc,
                message=f"Threshold for '{metric}' has no unit.",
            ))

        # Unsupported precision: an overly precise boundary (many decimal
        # places) with no assumptions/provenance backing it.
        for label, val in (("bull_boundary", bull), ("bear_boundary", bear)):
            if val is not None and abs(val - round(val, 1)) > 1e-9 and not t.get("assumptions"):
                findings.append(Finding(
                    code="threshold_unsupported_precision", severity=Severity.LOW, field=loc,
                    message=f"{label} {val} has unusually high precision with no supporting assumptions.",
                ))

        # Threshold not connected to any evidence/assumption backing.
        if not t.get("assumptions") and not t.get("provenance"):
            findings.append(Finding(
                code="threshold_without_evidence", severity=Severity.MEDIUM, field=loc,
                message=f"Threshold for '{metric}' has neither assumptions nor a provenance tag.",
            ))

    return findings
