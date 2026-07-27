"""Objective 3 — response-structure validation."""
from __future__ import annotations

from typing import Any, Dict, List

from ..models import Finding, QueryFixture, Severity
from ..util import get, get_list

# logical field -> candidate backend keys (tolerant of naming drift)
FIELD_CANDIDATES: Dict[str, List[str]] = {
    "active_ticker":            ["ticker"],
    "direct_answer":            ["direct_answer"],
    "thesis_summary":           ["one_sentence_thesis", "conclusion", "core_takeaway"],
    "valuation_interpretation": ["valuation_view", "expectation_regime", "valuation_stance"],
    "bull_case":                ["bull_thesis", "bull_case"],
    "bear_case":                ["bear_thesis", "bear_case"],
    "risks":                    ["key_risks", "top_risks"],
    "catalysts":                ["catalyst_calendar", "what_changed"],
    "confidence":                ["confidence_score"],
    "evidence":                  ["evidence_count", "evidence_used", "analysis_foundation_sources"],
    "_integrity":                ["_integrity"],
    "quantitative_claims":       ["quantitative_claims"],
    "decision_thresholds":       ["decision_thresholds"],
    "claim_provenance_summary":  ["claim_provenance_summary"],
}


def field_presence(thesis: Dict[str, Any]) -> Dict[str, bool]:
    """Return {logical_field: is_present_and_non_empty} for every tracked field."""
    presence: Dict[str, bool] = {}
    for logical, keys in FIELD_CANDIDATES.items():
        present = False
        for k in keys:
            v = thesis.get(k) if isinstance(thesis, dict) else None
            if v not in (None, "", [], {}):
                present = True
                break
        presence[logical] = present
    return presence


def check(thesis: Dict[str, Any], fixture: QueryFixture) -> List[Finding]:
    findings: List[Finding] = []
    if not isinstance(thesis, dict) or not thesis:
        findings.append(Finding(
            code="malformed_response", severity=Severity.CRITICAL,
            message="Response body is missing or not a JSON object.",
        ))
        return findings

    presence = field_presence(thesis)

    # Ticker / company mismatch — CRITICAL (wrong-company answer is the worst
    # possible failure mode for an investment analysis tool).
    ticker = str(get(thesis, "ticker")).strip().upper()
    if ticker and fixture.ticker and ticker != fixture.ticker.upper():
        findings.append(Finding(
            code="ticker_mismatch", severity=Severity.CRITICAL, field="ticker",
            message=f"Response ticker '{ticker}' does not match requested '{fixture.ticker}'.",
        ))
    company = str(get(thesis, "company_name", "company")).strip().lower()
    if company and fixture.company.lower() not in company and company not in fixture.company.lower():
        findings.append(Finding(
            code="company_mismatch", severity=Severity.HIGH, field="company_name",
            message=f"Response company '{company}' does not clearly match requested '{fixture.company}'.",
        ))

    # Required-by-fixture fields escalate to real findings; everything else is
    # tracked in field_presence only (per objective 3: missing optional fields
    # should not automatically fail).
    for req in fixture.requires:
        if not presence.get(req, False):
            findings.append(Finding(
                code="missing_required_field", severity=Severity.HIGH, field=req,
                message=f"Fixture requires '{req}' but it is missing/empty in the response.",
            ))

    # Baseline sanity: every response should have SOME direct answer or thesis
    # summary — a completely empty analytical payload is a CRITICAL failure
    # regardless of what the fixture explicitly requires.
    if not presence["direct_answer"] and not presence["thesis_summary"]:
        findings.append(Finding(
            code="empty_analysis", severity=Severity.CRITICAL,
            message="Response has neither a direct_answer nor a thesis summary — analysis is effectively empty.",
        ))

    # Blank/truncated section heuristic: a present-but-very-short bull/bear case.
    bull = get(thesis, "bull_thesis", "bull_case")
    bear = get(thesis, "bear_thesis", "bear_case")
    for label, text in (("bull_case", bull), ("bear_case", bear)):
        if isinstance(text, str) and 0 < len(text.strip()) < 15:
            findings.append(Finding(
                code="truncated_section", severity=Severity.MEDIUM, field=label,
                message=f"{label} is present but suspiciously short ({len(text.strip())} chars).",
            ))

    return findings
