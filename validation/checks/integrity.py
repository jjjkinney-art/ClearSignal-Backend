"""Objective 4 — content-integrity (_integrity block) validation.

Independent of app/integrity/consistency.py by design — this validates the
DEPLOYED backend's actual output, so it must not assume the backend's own
validator ran or ran correctly.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List

from ..models import Finding, QueryFixture, Severity
from ..util import get, get_text

_CHEAP_WORDS = ("undervalued", "cheap", "discount to intrinsic", "below intrinsic",
               "attractive entry", "margin of safety")
_STRETCHED_WORDS = ("overvalued", "expensive", "demanding", "stretched", "rich valuation",
                    "premium multiple", "limited upside", "priced for perfection",
                    "fully priced", "priced in", "no margin of safety")
_FAIR_WORDS = ("fairly valued", "fair value", "reasonably valued", "fairly priced")

_DEV_JARGON_MARKERS = (
    "chain of thought", "chain-of-thought", "as an ai", "system prompt", "developer note",
    "todo:", "fixme", "traceback", "stack trace", "nonetype", "keyerror", "```json",
    "internal use only", "debug:", "assistant:", "<think>",
)


def _prose_lean(text: str) -> str:
    t = text.lower()
    cheap = sum(1 for w in _CHEAP_WORDS if w in t)
    stretched = sum(1 for w in _STRETCHED_WORDS if w in t)
    fair = sum(1 for w in _FAIR_WORDS if w in t)
    if stretched and stretched >= cheap and stretched >= fair:
        return "stretched"
    if fair and fair >= cheap and fair >= stretched:
        return "fair"
    if cheap and cheap > stretched and cheap > fair:
        return "cheap"
    return "undetermined"


def check(thesis: Dict[str, Any], fixture: QueryFixture) -> List[Finding]:
    findings: List[Finding] = []

    prose = get_text(
        get(thesis, "valuation_view"), get(thesis, "conclusion"), get(thesis, "direct_answer"),
    )
    lean = _prose_lean(prose)
    regime = str(get(thesis, "expectation_regime")).strip().lower()

    integrity = thesis.get("_integrity") if isinstance(thesis, dict) else None

    # Malformed integrity object.
    if integrity is not None and not isinstance(integrity, dict):
        findings.append(Finding(
            code="malformed_integrity", severity=Severity.HIGH, field="_integrity",
            message="_integrity is present but is not a JSON object.",
        ))
        integrity = None

    price_label = str((integrity or {}).get("price_label", "")).strip()
    ok = (integrity or {}).get("ok", True) if integrity is not None else None
    violations = (integrity or {}).get("violations", []) if integrity is not None else []
    if not isinstance(violations, list):
        violations = []
        findings.append(Finding(
            code="malformed_integrity", severity=Severity.MEDIUM, field="_integrity.violations",
            message="_integrity.violations is present but is not a list.",
        ))

    # "Priced Cheap" alongside expensive/unclear prose — the exact Sprint 1B bug class.
    cheap_label = price_label.lower() in ("priced cheap", "cheap") or regime == "cheap"
    if cheap_label and lean == "stretched":
        findings.append(Finding(
            code="valuation_label_contradiction", severity=Severity.HIGH, field="price_label",
            message=(
                f"price_label/regime suggests 'cheap' but valuation prose reads as "
                f"'{lean}' (demanding/expensive language)."
            ),
        ))

    # Critical violations not reflected in price_label: integrity says NOT ok /
    # has a high-severity violation, but the price_label still reads like a
    # clean, confident valuation call (e.g. still "Priced Cheap"/"Priced Rich"
    # rather than a neutral/qualified label).
    has_high_violation = any(
        isinstance(v, dict) and str(v.get("severity", "")).lower() == "high" for v in violations
    )
    if has_high_violation and cheap_label:
        findings.append(Finding(
            code="critical_violation_not_reflected", severity=Severity.HIGH, field="price_label",
            message="A high-severity integrity violation exists but price_label still reads as a confident 'cheap' call.",
        ))

    # Clean status despite a clear structural contradiction the backend missed.
    if integrity is not None and ok is True and cheap_label and lean == "stretched":
        findings.append(Finding(
            code="clean_status_despite_contradiction", severity=Severity.HIGH, field="_integrity.ok",
            message="_integrity.ok=true despite a detectable cheap-label/expensive-prose contradiction.",
        ))

    # Raw developer terminology / internal jargon exposed in normal content.
    all_text = get_text(
        get(thesis, "direct_answer"), get(thesis, "conclusion"),
        get(thesis, "bull_thesis", "bull_case"), get(thesis, "bear_thesis", "bear_case"),
        get(thesis, "valuation_view"),
    ).lower()
    for marker in _DEV_JARGON_MARKERS:
        if marker in all_text:
            findings.append(Finding(
                code="dev_jargon_exposed", severity=Severity.CRITICAL, field="prose",
                message=f"Internal/developer terminology '{marker}' found in user-facing content.",
            ))
            break  # one finding is enough signal; avoid noisy duplicates

    return findings
