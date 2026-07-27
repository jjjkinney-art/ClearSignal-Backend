"""Objective 5 — quantitative_claims validation."""
from __future__ import annotations

from typing import Any, Dict, List

from ..models import Finding, QueryFixture, Severity

_VALID_PROVENANCE = {"reported", "derived", "estimated", "scenario", "heuristic"}
_MUST_QUALIFY = {"scenario", "estimated"}


def check(thesis: Dict[str, Any], fixture: QueryFixture) -> List[Finding]:
    findings: List[Finding] = []
    claims = thesis.get("quantitative_claims") if isinstance(thesis, dict) else None
    if claims is None:
        return findings  # optional field; absence is tracked by structure.py, not a claims finding
    if not isinstance(claims, list):
        findings.append(Finding(
            code="malformed_claims", severity=Severity.HIGH, field="quantitative_claims",
            message="quantitative_claims is present but is not a list.",
        ))
        return findings

    seen_values: Dict[str, int] = {}

    for i, c in enumerate(claims):
        loc = f"quantitative_claims[{i}]"
        if not isinstance(c, dict):
            findings.append(Finding(
                code="malformed_claim", severity=Severity.MEDIUM, field=loc,
                message="Claim entry is not a JSON object.",
            ))
            continue

        value_text = c.get("value_text") or ""
        rendered = c.get("rendered") or ""
        provenance = str(c.get("provenance", "")).strip().lower()

        # Empty/unrenderable claim.
        if not value_text and not rendered:
            findings.append(Finding(
                code="empty_claim", severity=Severity.MEDIUM, field=loc,
                message="Claim has neither value_text nor rendered — nothing displayable.",
            ))
            continue

        # Classification must be one of the five provenance values.
        if provenance not in _VALID_PROVENANCE:
            findings.append(Finding(
                code="invalid_claim_provenance", severity=Severity.CRITICAL, field=loc,
                message=f"Claim provenance '{provenance or '(empty)'}' is not one of {sorted(_VALID_PROVENANCE)}.",
            ))

        # SCENARIO/ESTIMATED must carry a visible qualifier (assumptions, confidence,
        # or the qualifier already baked into `rendered`).
        if provenance in _MUST_QUALIFY:
            has_qualifier = bool(c.get("assumptions") or c.get("confidence")) or provenance in rendered.lower()
            if not has_qualifier:
                findings.append(Finding(
                    code="scenario_presented_as_fact", severity=Severity.CRITICAL, field=loc,
                    message=f"{provenance} claim '{value_text}' has no visible qualification — could read as a reported fact.",
                ))

        # REPORTED claims materially important (has a metric name, i.e. clearly
        # tied to a specific figure) should carry a source.
        if provenance == "reported" and c.get("metric") and not c.get("source"):
            findings.append(Finding(
                code="missing_source_for_reported_claim", severity=Severity.HIGH, field=loc,
                message=f"Reported claim '{value_text}' for metric '{c.get('metric')}' has no source.",
            ))

        # Time-sensitive reported claims need as_of / freshness_status.
        if provenance == "reported" and not c.get("as_of") and not c.get("freshness_status"):
            findings.append(Finding(
                code="missing_freshness_metadata", severity=Severity.MEDIUM, field=loc,
                message=f"Reported claim '{value_text}' has no as_of or freshness_status.",
            ))

        # Stale claims must be marked (stale=True or a stale-ish freshness_status).
        fstatus = str(c.get("freshness_status", "")).lower()
        if fstatus in ("stale", "very_stale") and not c.get("stale"):
            findings.append(Finding(
                code="stale_claim_not_marked", severity=Severity.HIGH, field=loc,
                message=f"Claim '{value_text}' has freshness_status='{fstatus}' but stale flag is not set.",
            ))
        if c.get("stale") and not c.get("as_of") and fstatus != "source_date_unavailable":
            findings.append(Finding(
                code="stale_precision_unqualified", severity=Severity.HIGH, field=loc,
                message=f"Stale claim '{value_text}' presented without an as-of date or explicit qualification.",
            ))

        # Confidence, if present, must be a recognizable value.
        conf = c.get("confidence")
        if conf not in (None, "") and str(conf).lower() not in ("low", "medium", "high"):
            findings.append(Finding(
                code="invalid_confidence_value", severity=Severity.LOW, field=loc,
                message=f"Confidence value '{conf}' is not one of low/medium/high.",
            ))

        # Scenario claims should generally carry assumptions.
        if provenance == "scenario" and not c.get("assumptions"):
            findings.append(Finding(
                code="scenario_missing_assumptions", severity=Severity.MEDIUM, field=loc,
                message=f"Scenario claim '{value_text}' has no assumptions captured.",
            ))

        # Duplicate numeric claim detection (same value_text repeated).
        key = value_text.strip().lower()
        if key:
            seen_values[key] = seen_values.get(key, 0) + 1

    for value, count in seen_values.items():
        if count > 1:
            findings.append(Finding(
                code="duplicate_numerical_claim", severity=Severity.MEDIUM, field="quantitative_claims",
                message=f"Value '{value}' appears {count} times among quantitative_claims.",
            ))

    return findings
