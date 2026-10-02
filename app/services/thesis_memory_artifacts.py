"""Deterministic, bounded thesis-memory artifacts for account-owned research.

Artifacts are projections of the exact response already saved for an account-owned
assistant message. They are not current evidence, are never inferred from raw
transcript text, and must not be injected into a future analysis without explicit
owner selection and fresh-evidence validation.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence


THESIS_MEMORY_ARTIFACT_VERSION = 1
MAX_TEXT_CHARS = 1_500
MAX_LIST_ITEMS = 8
MAX_EVIDENCE_REFERENCES = 12

_TEXT_FIELDS = (
    "one_sentence_thesis",
    "direct_answer",
    "conclusion",
    "bull_thesis",
    "bear_thesis",
    "what_would_change_this_view",
)
_LIST_FIELDS = (
    "key_drivers",
    "key_risks",
    "what_to_monitor",
    "invalidation_conditions",
)
_REFERENCE_FIELDS = (
    "evidence_references",
    "evidence",
    "sources",
)
_REFERENCE_KEYS = (
    "id",
    "evidence_id",
    "source_id",
    "title",
    "url",
    "publisher",
    "document_type",
    "published_at",
    "filed_at",
    "period_end",
    "freshness",
    "availability",
    "supersession",
    "material_conflict",
)


def _clean_text(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.split())[:MAX_TEXT_CHARS]


def _clean_list(value: object) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    cleaned: list[str] = []
    for item in value[:MAX_LIST_ITEMS]:
        if isinstance(item, Mapping):
            text = _clean_text(
                item.get("text")
                or item.get("claim")
                or item.get("label")
                or item.get("description")
            )
        else:
            text = _clean_text(item)
        if text and text not in cleaned:
            cleaned.append(text)
    return cleaned


def _ticker(response: Mapping[str, Any]) -> str:
    routing = response.get("routing")
    candidates = [
        routing.get("detected_ticker") if isinstance(routing, Mapping) else None,
        response.get("ticker"),
        response.get("company_ticker"),
    ]
    for candidate in candidates:
        value = _clean_text(candidate).upper()
        if value and len(value) <= 20 and all(char.isalnum() or char in ".-" for char in value):
            return value
    return ""


def _reference(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    result: dict[str, Any] = {}
    for key in _REFERENCE_KEYS:
        item = value.get(key)
        if isinstance(item, str):
            cleaned = _clean_text(item)
            if cleaned:
                result[key] = cleaned
        elif isinstance(item, bool):
            result[key] = item
    return result


def _evidence_references(
    response: Mapping[str, Any], thesis: Mapping[str, Any]
) -> list[dict[str, Any]]:
    containers: list[object] = []
    for field in _REFERENCE_FIELDS:
        containers.append(thesis.get(field))
        containers.append(response.get(field))

    result: list[dict[str, Any]] = []
    identities: set[tuple[object, ...]] = set()
    for container in containers:
        if not isinstance(container, list):
            continue
        for item in container:
            reference = _reference(item)
            if not reference:
                continue
            identity = (
                reference.get("id"),
                reference.get("evidence_id"),
                reference.get("source_id"),
                reference.get("url"),
                reference.get("title"),
            )
            if identity in identities:
                continue
            identities.add(identity)
            result.append(reference)
            if len(result) >= MAX_EVIDENCE_REFERENCES:
                return result
    return result


def build_thesis_memory_artifact(response: Mapping[str, Any] | None) -> dict[str, Any]:
    """Project one completed response into a safe historical thesis artifact.

    An empty/unstructured response returns an explicit unavailable state. The
    projection copies only allow-listed structured fields; raw conversation text,
    general-answer branches, and arbitrary model metadata are excluded.
    """
    unavailable = {
        "artifact_version": THESIS_MEMORY_ARTIFACT_VERSION,
        "status": "unavailable",
        "historical_only": True,
        "requires_fresh_evidence": True,
    }
    if not isinstance(response, Mapping):
        return unavailable

    answer = response.get("answer")
    thesis = answer.get("investment_thesis") if isinstance(answer, Mapping) else None
    if not isinstance(thesis, Mapping):
        return unavailable

    fields: dict[str, Any] = {}
    for field in _TEXT_FIELDS:
        cleaned = _clean_text(thesis.get(field))
        if cleaned:
            fields[field] = cleaned
    for field in _LIST_FIELDS:
        cleaned = _clean_list(thesis.get(field))
        if cleaned:
            fields[field] = cleaned

    confidence = thesis.get("confidence_score")
    if isinstance(confidence, (int, float)) and not isinstance(confidence, bool):
        fields["confidence_score"] = max(0.0, min(float(confidence), 100.0))

    references = _evidence_references(response, thesis)
    if not fields and not references:
        return unavailable

    artifact: dict[str, Any] = {
        "artifact_version": THESIS_MEMORY_ARTIFACT_VERSION,
        "status": "available",
        "historical_only": True,
        "requires_fresh_evidence": True,
        "ticker": _ticker(response) or None,
        "thesis": fields,
        "evidence_references": references,
    }
    evidence_integrity = response.get("evidence_integrity")
    if isinstance(evidence_integrity, Mapping):
        artifact["evidence_integrity"] = {
            key: evidence_integrity[key]
            for key in (
                "overall_status",
                "has_material_conflict",
                "admitted_count",
                "blocked_count",
            )
            if key in evidence_integrity
            and isinstance(evidence_integrity[key], (str, bool, int))
        }
    return artifact
