"""Objective 7 — factual and presentation-risk heuristics.

These are deliberately conservative: low-certainty heuristics generate LOW/
MEDIUM warnings rather than automatic failures, per the sprint's instruction.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List

from ..models import Finding, QueryFixture, Severity
from ..util import get, get_text

_JSON_FRAGMENT_RE = re.compile(r'[{\[]\s*"[a-zA-Z_]+"\s*:', re.MULTILINE)
_PRECISE_PCT_RE = re.compile(r'\b\d{1,3}\.\d{2,}\s?%')
_MONEY_RE = re.compile(r'\$\s?\d[\d,]*\.?\d*\s?(B|M|K|billion|million|thousand)?', re.IGNORECASE)
_FISCAL_YEAR_RE = re.compile(r'\bFY\s?(\d{2}|\d{4})\b', re.IGNORECASE)
_CITATION_RE = re.compile(r'\[[^\]]{0,60}\]|\([^)]{0,60}(10-[KQ]|earnings call|filing)[^)]{0,60}\)', re.IGNORECASE)
_PP_CONFUSION_RE = re.compile(r'\b(\d+(\.\d+)?)\s?%\s?(increase|decrease|rise|drop|higher|lower)\b', re.IGNORECASE)


def _paragraphs(text: str) -> List[str]:
    return [p.strip() for p in re.split(r"\n\s*\n|\.\s{2,}", text) if len(p.strip()) > 40]


def check(thesis: Dict[str, Any], fixture: QueryFixture) -> List[Finding]:
    findings: List[Finding] = []
    if not isinstance(thesis, dict):
        return findings

    prose_fields = {
        "direct_answer": get(thesis, "direct_answer"),
        "conclusion": get(thesis, "conclusion"),
        "bull_case": get(thesis, "bull_thesis", "bull_case"),
        "bear_case": get(thesis, "bear_thesis", "bear_case"),
        "valuation_view": get(thesis, "valuation_view"),
    }
    all_text = get_text(*prose_fields.values())

    # JSON fragments inside prose.
    for field_name, text in prose_fields.items():
        if isinstance(text, str) and _JSON_FRAGMENT_RE.search(text):
            findings.append(Finding(
                code="json_fragment_in_prose", severity=Severity.CRITICAL, field=field_name,
                message=f"'{field_name}' appears to contain a raw JSON fragment.",
            ))

    # Duplicate paragraphs across bull/bear/conclusion (near-identical text
    # reused rather than distinct analysis).
    seen: Dict[str, str] = {}
    for field_name, text in prose_fields.items():
        if not isinstance(text, str):
            continue
        for para in _paragraphs(text):
            norm = re.sub(r"\s+", " ", para.lower())[:200]
            if norm in seen and seen[norm] != field_name:
                findings.append(Finding(
                    code="duplicate_paragraph", severity=Severity.MEDIUM, field=field_name,
                    message=f"Paragraph in '{field_name}' duplicates content already seen in '{seen[norm]}'.",
                ))
            else:
                seen[norm] = field_name

    # Unsupported precise percentages (e.g. "34.27%") without any nearby
    # claim/source backing (best-effort: only flag if no quantitative_claims
    # entry shares the same figure).
    claim_values = {
        str(c.get("value_text", "")).strip() for c in (thesis.get("quantitative_claims") or [])
        if isinstance(c, dict)
    }
    for m in _PRECISE_PCT_RE.finditer(all_text):
        figure = m.group(0).strip()
        if not any(figure in cv or cv in figure for cv in claim_values):
            findings.append(Finding(
                code="unsupported_precise_percentage", severity=Severity.LOW, field="prose",
                message=f"Precise percentage '{figure}' appears in prose with no matching quantitative_claims entry.",
            ))
            break  # one representative finding avoids flooding the report

    # Fiscal-year ambiguity: "FY24" without a clear surrounding calendar-year anchor.
    for m in _FISCAL_YEAR_RE.finditer(all_text):
        window = all_text[max(0, m.start() - 40): m.end() + 40]
        if not re.search(r"20\d{2}", window.replace(m.group(0), "")):
            findings.append(Finding(
                code="fiscal_year_ambiguity", severity=Severity.LOW, field="prose",
                message=f"'{m.group(0)}' used without a clear calendar-year anchor nearby.",
            ))
            break

    # Percentage vs percentage-point confusion heuristic: "X% increase" near
    # a value that looks like it should be percentage points (e.g. margin
    # discussion) — conservative, single representative flag.
    if "margin" in all_text.lower() or "share" in all_text.lower():
        for m in _PP_CONFUSION_RE.finditer(all_text):
            context = all_text[max(0, m.start() - 30): m.start()].lower()
            if "margin" in context or "share" in context:
                findings.append(Finding(
                    code="percentage_vs_point_ambiguity", severity=Severity.LOW, field="prose",
                    message=f"'{m.group(0)}' near margin/share language — verify percentage vs. percentage-point.",
                ))
                break

    # Absent sources for major reported facts: any quantitative_claims entry
    # with provenance=reported and a metric, but no source (delegated to
    # claims.py for the structured case; here we do a prose-level fallback —
    # a dollar figure in prose with no citation-like marker nearby at all).
    money_matches = list(_MONEY_RE.finditer(all_text))
    if money_matches and not _CITATION_RE.search(all_text) and not claim_values:
        findings.append(Finding(
            code="absent_source_for_reported_figures", severity=Severity.MEDIUM, field="prose",
            message="Prose contains dollar figures with no citation marker and no structured claims to back them.",
        ))

    # Malformed citation heuristic: bracketed citation with no content, or
    # dangling brackets.
    if re.search(r"\[\s*\]|\(\s*\)", all_text):
        findings.append(Finding(
            code="malformed_citation", severity=Severity.LOW, field="prose",
            message="Empty citation bracket/parenthesis found in prose.",
        ))

    # Blank / truncated sections beyond structure.py's short-text check:
    # a field present but consisting only of whitespace/punctuation.
    for field_name, text in prose_fields.items():
        if isinstance(text, str) and text and not re.search(r"[A-Za-z]{3,}", text):
            findings.append(Finding(
                code="blank_or_truncated_section", severity=Severity.MEDIUM, field=field_name,
                message=f"'{field_name}' contains no readable content (punctuation/whitespace only).",
            ))

    return findings
