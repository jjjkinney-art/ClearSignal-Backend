"""Objective 8 — the severity framework, as an explicit, documented reference.

Every Finding produced by validation/checks/*.py is assigned one of these four
levels at the point it is created. This module does not re-derive severity —
it documents the criteria and provides aggregation helpers used by report.py.

CRITICAL
    - materially false or contradictory investment conclusion
    - wrong ticker/company
    - raw internal reasoning exposure
    - invalid threshold shown as actionable
    - scenario presented as reported fact
    - severe numerical unit error

HIGH
    - unsupported material factual claim
    - stale material data presented as current
    - valuation contradiction
    - missing integrity warning for a clear conflict
    - citation does not support the associated claim

MEDIUM
    - missing provenance metadata
    - weak threshold assumptions
    - incomplete freshness information
    - duplicated claim
    - unclear fiscal period

LOW
    - wording, formatting, or non-material metadata issue
"""
from __future__ import annotations

from typing import Dict, Iterable, List

from .models import Finding, QueryOutcome, Severity

# Maps each finding `code` produced anywhere in validation/checks/* to the
# CRITICAL/HIGH/MEDIUM/LOW criterion it satisfies (documentation only — the
# authoritative severity is the one set on the Finding itself).
CODE_TO_CRITERION: Dict[str, str] = {
    "malformed_response": "materially false or contradictory investment conclusion",
    "ticker_mismatch": "wrong ticker/company",
    "company_mismatch": "wrong ticker/company",
    "dev_jargon_exposed": "raw internal reasoning exposure",
    "json_fragment_in_prose": "raw internal reasoning exposure",
    "threshold_shown_available_but_contradictory": "invalid threshold shown as actionable",
    "threshold_identical_boundaries": "invalid threshold shown as actionable",
    "invalid_claim_provenance": "scenario presented as reported fact",
    "scenario_presented_as_fact": "scenario presented as reported fact",
    "empty_analysis": "materially false or contradictory investment conclusion",

    "missing_required_field": "unsupported material factual claim",
    "missing_source_for_reported_claim": "unsupported material factual claim",
    "stale_claim_not_marked": "stale material data presented as current",
    "stale_precision_unqualified": "stale material data presented as current",
    "valuation_label_contradiction": "valuation contradiction",
    "critical_violation_not_reflected": "missing integrity warning for a clear conflict",
    "clean_status_despite_contradiction": "missing integrity warning for a clear conflict",
    "malformed_integrity": "missing integrity warning for a clear conflict",
    "threshold_missing_boundaries": "unsupported material factual claim",
    "threshold_neutral_interval_disordered": "unsupported material factual claim",
    "absent_source_for_reported_figures": "unsupported material factual claim",

    "missing_freshness_metadata": "incomplete freshness information",
    "duplicate_numerical_claim": "duplicated claim",
    "duplicate_paragraph": "duplicated claim",
    "scenario_missing_assumptions": "weak threshold assumptions",
    "threshold_without_evidence": "weak threshold assumptions",
    "threshold_missing_neutral_interval": "weak threshold assumptions",
    "threshold_direction_unconfirmed": "weak threshold assumptions",
    "unavailable_threshold_missing_reason": "missing provenance metadata",
    "threshold_display_not_readable": "missing provenance metadata",
    "truncated_section": "unclear fiscal period",
    "blank_or_truncated_section": "unclear fiscal period",

    "invalid_confidence_value": "wording, formatting, or non-material metadata issue",
    "threshold_missing_unit": "wording, formatting, or non-material metadata issue",
    "threshold_missing_metric": "wording, formatting, or non-material metadata issue",
    "threshold_invalid_direction": "wording, formatting, or non-material metadata issue",
    "unsupported_precise_percentage": "wording, formatting, or non-material metadata issue",
    "fiscal_year_ambiguity": "unclear fiscal period",
    "percentage_vs_point_ambiguity": "wording, formatting, or non-material metadata issue",
    "malformed_citation": "citation does not support the associated claim",
    "threshold_unsupported_precision": "wording, formatting, or non-material metadata issue",
    "malformed_claim": "wording, formatting, or non-material metadata issue",
    "malformed_claims": "unsupported material factual claim",
    "malformed_thresholds": "unsupported material factual claim",
    "empty_claim": "wording, formatting, or non-material metadata issue",
    "validator_error": "materially false or contradictory investment conclusion",
}


def count_by_severity(outcomes: Iterable[QueryOutcome]) -> Dict[str, int]:
    counts = {s.value: 0 for s in Severity}
    for outcome in outcomes:
        for f in outcome.findings:
            counts[f.severity.value] += 1
    return counts


def findings_by_code(outcomes: Iterable[QueryOutcome]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for outcome in outcomes:
        for f in outcome.findings:
            counts[f.code] = counts.get(f.code, 0) + 1
    return counts


def all_findings_flat(outcomes: Iterable[QueryOutcome]) -> List[Dict]:
    rows = []
    for outcome in outcomes:
        for f in outcome.findings:
            rows.append({
                "fixture_id": outcome.fixture.id,
                "ticker": outcome.fixture.ticker,
                "company": outcome.fixture.company,
                "category": outcome.fixture.category,
                **f.to_dict(),
            })
    return rows
