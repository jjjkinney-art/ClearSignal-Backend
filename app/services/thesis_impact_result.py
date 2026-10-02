"""Evidence-bound output contract for historical thesis-impact results.

This layer validates a proposed comparison. It does not retrieve evidence, infer
account ownership, or generate thesis direction. Every accepted material claim
must cite evidence already admitted by the thesis-impact evidence gate.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence


THESIS_IMPACT_RESULT_VERSION = 1
SUPPORTED_DIRECTIONS = {"stronger", "weaker", "unchanged"}
MAX_CHANGE_CLAIMS = 6
MAX_CLAIM_CHARS = 1_200
MAX_RATIONALE_CHARS = 2_000


def _clean_text(value: object, limit: int) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.split())[:limit]


def _unverified(
    gate: Mapping[str, Any] | None,
    reason: str,
) -> dict[str, Any]:
    gate_status = gate.get("status") if isinstance(gate, Mapping) else "unavailable"
    return {
        "result_version": THESIS_IMPACT_RESULT_VERSION,
        "status": "unverified",
        "direction": "unverified",
        "reason": reason,
        "gate_status": gate_status or "unavailable",
        "claims": [],
        "evidence_references": [],
    }


def build_thesis_impact_result(
    *,
    gate: Mapping[str, Any] | None,
    proposed_direction: str,
    rationale: str,
    claims: Sequence[Mapping[str, Any]] | None,
) -> dict[str, Any]:
    """Validate a bounded change result against gate-admitted evidence IDs."""
    if (
        not isinstance(gate, Mapping)
        or gate.get("status") != "ready"
        or gate.get("ready_for_comparison") is not True
    ):
        return _unverified(gate, "insufficient_new_evidence")

    direction = (proposed_direction or "").strip().lower()
    if direction not in SUPPORTED_DIRECTIONS:
        return _unverified(gate, "unsupported_direction")

    eligible = gate.get("eligible_evidence")
    if not isinstance(eligible, list) or not eligible:
        return _unverified(gate, "missing_eligible_evidence")

    eligible_by_id: dict[str, dict[str, Any]] = {}
    for item in eligible:
        if not isinstance(item, Mapping):
            continue
        evidence_id = item.get("evidence_id")
        url = item.get("url")
        source_time = item.get("source_time")
        if (
            isinstance(evidence_id, str)
            and evidence_id.strip()
            and isinstance(url, str)
            and url.strip()
            and isinstance(source_time, str)
            and source_time.strip()
        ):
            eligible_by_id[evidence_id.strip()] = {
                "evidence_id": evidence_id.strip(),
                "url": url.strip()[:2_000],
                "source_time": source_time.strip(),
                "source_time_field": item.get("source_time_field"),
            }
    if not eligible_by_id:
        return _unverified(gate, "missing_eligible_evidence")

    if not isinstance(claims, Sequence) or isinstance(claims, (str, bytes)):
        return _unverified(gate, "missing_change_claims")

    accepted_claims: list[dict[str, Any]] = []
    cited_ids: list[str] = []
    for item in list(claims)[:MAX_CHANGE_CLAIMS]:
        if not isinstance(item, Mapping):
            return _unverified(gate, "malformed_change_claim")
        text = _clean_text(item.get("text"), MAX_CLAIM_CHARS)
        evidence_ids = item.get("evidence_ids")
        if (
            not text
            or not isinstance(evidence_ids, Sequence)
            or isinstance(evidence_ids, (str, bytes))
        ):
            return _unverified(gate, "malformed_change_claim")

        normalized_ids: list[str] = []
        for raw_id in evidence_ids:
            if not isinstance(raw_id, str) or not raw_id.strip():
                return _unverified(gate, "malformed_evidence_reference")
            evidence_id = raw_id.strip()
            if evidence_id not in eligible_by_id:
                return _unverified(gate, "unadmitted_evidence_reference")
            if evidence_id not in normalized_ids:
                normalized_ids.append(evidence_id)
        if not normalized_ids:
            return _unverified(gate, "unsupported_change_claim")

        accepted_claims.append({
            "text": text,
            "evidence_ids": normalized_ids,
        })
        for evidence_id in normalized_ids:
            if evidence_id not in cited_ids:
                cited_ids.append(evidence_id)

    if not accepted_claims:
        return _unverified(gate, "missing_change_claims")

    cleaned_rationale = _clean_text(rationale, MAX_RATIONALE_CHARS)
    if not cleaned_rationale:
        return _unverified(gate, "missing_rationale")

    return {
        "result_version": THESIS_IMPACT_RESULT_VERSION,
        "status": "supported",
        "direction": direction,
        "reason": "evidence_bound_change",
        "gate_status": "ready",
        "rationale": cleaned_rationale,
        "claims": accepted_claims,
        "evidence_references": [
            eligible_by_id[evidence_id] for evidence_id in cited_ids
        ],
    }
