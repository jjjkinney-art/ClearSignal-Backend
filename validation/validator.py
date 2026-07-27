"""Aggregates all Sprint 2A checks against one raw /ask response."""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from .checks import claims, integrity, presentation, structure, thresholds
from .models import Finding, QueryFixture, Severity


def extract_thesis(raw_response: Any) -> Optional[Dict[str, Any]]:
    """Pull the investment_thesis dict out of a raw /ask response, tolerant of
    the response being malformed/absent entirely."""
    if not isinstance(raw_response, dict):
        return None
    answer = raw_response.get("answer")
    if not isinstance(answer, dict):
        return None
    thesis = answer.get("investment_thesis")
    return thesis if isinstance(thesis, dict) else None


def validate(
    raw_response: Any, fixture: QueryFixture,
) -> Tuple[Optional[Dict[str, Any]], List[Finding], Dict[str, bool]]:
    """Run every check module against one response. Never raises — a checker
    exception becomes a CRITICAL 'validator_error' finding so a bug in the
    harness itself is visible rather than silently losing a result."""
    thesis = extract_thesis(raw_response)
    findings: List[Finding] = []
    presence: Dict[str, bool] = {}

    if thesis is None:
        findings.append(Finding(
            code="malformed_response", severity=Severity.CRITICAL,
            message="Could not locate answer.investment_thesis in the response.",
        ))
        return None, findings, presence

    presence = structure.field_presence(thesis)

    for module in (structure, integrity, claims, thresholds, presentation):
        try:
            findings.extend(module.check(thesis, fixture))
        except Exception as exc:  # the harness must survive a checker bug
            findings.append(Finding(
                code="validator_error", severity=Severity.CRITICAL, field=module.__name__,
                message=f"Checker {module.__name__} raised {exc!r}.",
            ))

    return thesis, findings, presence
