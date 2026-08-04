"""Objective 5 — quantitative_claims validation.

Sprint 2A calibration note: the original duplicate-numerical-claim rule keyed
purely on ``value_text``, which flagged semantically unrelated claims that
happen to share a value (e.g. two different metrics both restating "25%").
Real MSFT production responses showed this is common and NOT a defect — an
LLM-generated thesis legitimately restates its central "fulcrum" metric (the
same real-world threshold) across direct_answer/bull_thesis/bear_thesis/
conclusion. The calibrated rule below requires a stronger combination of
evidence before calling two claims duplicates (see ``_duplicate_groups``).
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from ..models import Finding, QueryFixture, Severity

_VALID_PROVENANCE = {"reported", "derived", "estimated", "scenario", "heuristic"}
_MUST_QUALIFY = {"scenario", "estimated"}

# ── Duplicate-claim calibration ──────────────────────────────────────────────

# Thesis-level metric tags that map directly onto a real prose field on the
# thesis dict (set by app/integrity/thesis_wiring.py's _FIELD_DIMENSION).
# Agent-level claims use a different tag vocabulary ("valuation"/"macro"/
# "risk"/...) that does not correspond to a thesis dict key; for those we
# cannot re-derive surrounding context, so duplicate detection falls back to
# the coarser (value, metric, provenance) key without polarity disambiguation.
_METRIC_TO_THESIS_FIELD = {
    "direct_answer": "direct_answer",
    "bull_thesis": "bull_thesis",
    "bear_thesis": "bear_thesis",
    "valuation_view": "valuation_view",
    "macro_sensitivity": "macro_sensitivity",
    "conclusion": "conclusion",
    "what_changed": "what_changed",
}

_ABOVE_WORDS = ("above", "exceed", "exceeding", "over ", "greater than", "more than", "sustaining above", "growth of at least")
_BELOW_WORDS = ("below", "under ", "less than", "falls below", "decline", "declining", "decrease", "compress", "deceleration", "slowdown", "drop")


def _normalize_value(value_text: str) -> str:
    """Strip trailing punctuation/whitespace so '365,' / '365' / '365.' compare
    equal, without altering the number itself (leading '~', units, and ranges
    like '30-33x' are preserved — those are part of the claim's identity)."""
    return re.sub(r"[,.\s]+$", "", (value_text or "").strip().lower())


def _polarity_bucket(window: str) -> Optional[str]:
    w = window.lower()
    if any(p in w for p in _BELOW_WORDS):
        return "below"
    if any(p in w for p in _ABOVE_WORDS):
        return "above"
    return None


def _polarity_sequence(text: str, normalized_value: str) -> List[Optional[str]]:
    """Return the polarity bucket found around each occurrence of
    normalized_value in text, in left-to-right order (matching the order
    claim_extraction.py's regex scan produces the corresponding claims)."""
    if not isinstance(text, str) or not text:
        return []
    buckets: List[Optional[str]] = []
    # Search for the raw normalized value (escaped) as a substring match —
    # good enough to locate the occurrence; we only need the surrounding
    # window's polarity words, not a precise re-parse of the number.
    pattern = re.escape(normalized_value)
    for m in re.finditer(pattern, text.lower()):
        window = text[max(0, m.start() - 40): m.end() + 20]
        buckets.append(_polarity_bucket(window))
    return buckets


def _duplicate_groups(claims_meta: List[Dict[str, Any]], thesis: Dict[str, Any]) -> List[List[int]]:
    """Return groups (lists of claim indices) that should be reported as
    duplicates of each other, using the calibrated multi-signal rule:

        same normalized value AND same metric AND same provenance

    as the base key (already far stronger than value-alone), and — when the
    metric maps to a real thesis prose field — an additional polarity check
    that SPLITS a same-key group into sub-groups whose surrounding context
    (e.g. "above X" vs "below X") differs, so two directionally-opposite
    mentions of the same threshold are not flagged as duplicates of each other.
    Only sub-groups of size >= 2 are returned.
    """
    base_groups: Dict[Tuple[str, str, str], List[int]] = {}
    for meta in claims_meta:
        key = (meta["norm_value"], meta["metric"], meta["provenance"])
        base_groups.setdefault(key, []).append(meta["index"])

    result: List[List[int]] = []
    for (norm_value, metric, _prov), indices in base_groups.items():
        if len(indices) < 2:
            continue

        field_key = _METRIC_TO_THESIS_FIELD.get(metric)
        text = thesis.get(field_key) if field_key else None
        if isinstance(text, list):
            text = " ".join(str(t) for t in text)

        if not isinstance(text, str) or not text:
            # Can't disambiguate — keep the conservative default of flagging
            # the whole group (preserves detection of genuine duplicates).
            result.append(indices)
            continue

        buckets = _polarity_sequence(text, norm_value)
        if len(buckets) < len(indices) or len(set(buckets)) <= 1:
            # Not enough located occurrences to pair 1:1, or all occurrences
            # share the same (or no) polarity — treat as one duplicate group.
            result.append(indices)
            continue

        # Occurrences found in the SAME left-to-right order the claims were
        # extracted in (extract_claims scans front-to-back per field), so
        # zip index[i] <-> buckets[i] positionally.
        by_bucket: Dict[Optional[str], List[int]] = {}
        for idx, bucket in zip(indices, buckets):
            by_bucket.setdefault(bucket, []).append(idx)
        for bucket_indices in by_bucket.values():
            if len(bucket_indices) >= 2:
                result.append(bucket_indices)

    return result


# ── Product-name / identifier-number false-extraction detection ─────────────

# Conservative, explicit allowlist (not a blanket number blacklist) — matches
# the exact examples called out for Sprint 2A. Extend deliberately, not by
# pattern-matching every "<Capitalized word> <number>" occurrence.
_PRODUCT_IDENTIFIER_PATTERNS = [
    re.compile(r"\bMicrosoft\s+365\b", re.IGNORECASE),
    re.compile(r"\bOffice\s+365\b", re.IGNORECASE),
    re.compile(r"\bWindows\s+365\b", re.IGNORECASE),
    re.compile(r"\bFortune\s+500\b", re.IGNORECASE),
    re.compile(r"\bS&P\s*500\b", re.IGNORECASE),
    re.compile(r"\bForm\s+10-K\b", re.IGNORECASE),
    re.compile(r"\bForm\s+10-Q\b", re.IGNORECASE),
    re.compile(r"\bForm\s+8-K\b", re.IGNORECASE),
    re.compile(r"\bRule\s+10b5-1\b", re.IGNORECASE),
    re.compile(r"\bRule\s+144\b", re.IGNORECASE),
    re.compile(r"\bModel\s+[3SXY]\b"),  # Tesla Model 3/S/X/Y — case-sensitive, avoids matching "model x" prose
]


def _looks_like_product_identifier(metric: str, norm_value: str, thesis: Dict[str, Any]) -> Optional[str]:
    """Return the matched product/identifier phrase if this claim's value
    appears to have been extracted from a product name or regulatory
    identifier rather than a quantitative figure, else None."""
    field_key = _METRIC_TO_THESIS_FIELD.get(metric)
    text = thesis.get(field_key) if field_key else None
    if isinstance(text, list):
        text = " ".join(str(t) for t in text)
    if not isinstance(text, str) or not text:
        return None
    for pattern in _PRODUCT_IDENTIFIER_PATTERNS:
        for m in pattern.finditer(text):
            # Only flag when the matched phrase's own trailing number equals
            # this claim's value (e.g. "365" in "Microsoft 365") — contextual
            # evidence, not a bare number blacklist.
            trailing_num = re.search(r"\d+[\w-]*", m.group(0))
            if trailing_num and _normalize_value(trailing_num.group(0)) == norm_value:
                return m.group(0)
    return None


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

    claims_meta: List[Dict[str, Any]] = []

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
        metric = str(c.get("metric", "")).strip()

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

        norm_value = _normalize_value(value_text)

        # Product-name / regulatory-identifier number extracted as a claim
        # (e.g. "365" from "Microsoft 365"). Contextual, explicit-allowlist
        # check — never a blanket number blacklist.
        if norm_value:
            matched_phrase = _looks_like_product_identifier(metric, norm_value, thesis)
            if matched_phrase:
                findings.append(Finding(
                    code="product_identifier_extracted_as_claim", severity=Severity.MEDIUM, field=loc,
                    message=(
                        f"Claim '{value_text}' for metric '{metric}' appears to be extracted from the "
                        f"product/identifier name '{matched_phrase}', not a quantitative figure."
                    ),
                ))

        if norm_value:
            claims_meta.append({"index": i, "norm_value": norm_value, "metric": metric, "provenance": provenance})

    for group in _duplicate_groups(claims_meta, thesis):
        sample = claims[group[0]]
        findings.append(Finding(
            code="duplicate_numerical_claim", severity=Severity.MEDIUM, field="quantitative_claims",
            message=(
                f"Value '{sample.get('value_text')}' for metric '{sample.get('metric')}' "
                f"({sample.get('provenance')}) appears {len(group)} times with matching value/metric/"
                f"provenance and no distinguishing context — indices {group}."
            ),
        ))

    return findings
