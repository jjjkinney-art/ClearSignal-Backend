"""Fail-closed evidence gate for historical thesis-impact comparison.

This module does not decide whether a thesis strengthened or weakened. It only
determines whether attributable current evidence is eligible for that later
comparison.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping, Sequence


THESIS_IMPACT_GATE_VERSION = 1
MAX_CANDIDATE_EVIDENCE = 100
MAX_ELIGIBLE_EVIDENCE = 20
_BLOCKING_AVAILABILITY = {"unavailable", "removed", "inaccessible"}
_BLOCKING_SUPERSESSION = {"superseded", "amended", "replaced"}
_BLOCKING_FRESHNESS = {"future", "post_boundary"}


def _parse_time(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _evidence_time(evidence: Mapping[str, Any]) -> tuple[str | None, datetime | None]:
    for field in ("published_at", "filed_at", "observed_at"):
        parsed = _parse_time(evidence.get(field))
        if parsed is not None:
            return field, parsed
    return None, None


def _identifier(evidence: Mapping[str, Any]) -> str:
    for field in ("evidence_id", "id", "source_id"):
        value = evidence.get(field)
        if isinstance(value, str) and value.strip():
            return value.strip()[:200]
    return ""


def _status_value(evidence: Mapping[str, Any], field: str) -> str:
    value = evidence.get(field)
    return value.strip().lower() if isinstance(value, str) else ""


def gate_thesis_impact_evidence(
    *,
    prior_created_at: str,
    target_ticker: str,
    evidence: Sequence[Mapping[str, Any]] | None,
    evidence_integrity: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return evidence eligible to evaluate a selected historical thesis.

    Callers must supply the selected thesis record's creation time. Retrieval
    time is deliberately ignored: a newly retrieved old document is not new
    evidence.
    """
    base = {
        "gate_version": THESIS_IMPACT_GATE_VERSION,
        "ready_for_comparison": False,
        "direction": "unverified",
        "eligible_evidence": [],
    }
    prior_time = _parse_time(prior_created_at)
    ticker = (target_ticker or "").strip().upper()[:20]
    if prior_time is None or not ticker:
        return {**base, "status": "invalid_prior_record"}

    if isinstance(evidence_integrity, Mapping) and (
        evidence_integrity.get("has_material_conflict") is True
        or str(evidence_integrity.get("overall_status", "")).lower() == "conflicting"
    ):
        return {**base, "status": "conflicting_evidence"}

    eligible: list[dict[str, Any]] = []
    blocked_counts: dict[str, int] = {}
    saw_new_material_conflict = False

    candidates = evidence if isinstance(evidence, Sequence) else ()
    for item in list(candidates)[:MAX_CANDIDATE_EVIDENCE]:
        if not isinstance(item, Mapping):
            blocked_counts["malformed"] = blocked_counts.get("malformed", 0) + 1
            continue
        item_ticker = str(item.get("ticker") or "").strip().upper()[:20]
        if item_ticker != ticker:
            blocked_counts["ticker_mismatch"] = blocked_counts.get(
                "ticker_mismatch", 0
            ) + 1
            continue
        if item.get("materially_related") is not True:
            blocked_counts["not_materially_related"] = blocked_counts.get(
                "not_materially_related", 0
            ) + 1
            continue

        time_field, item_time = _evidence_time(item)
        if item_time is None:
            blocked_counts["missing_source_time"] = blocked_counts.get(
                "missing_source_time", 0
            ) + 1
            continue
        if item_time <= prior_time:
            blocked_counts["not_newer"] = blocked_counts.get("not_newer", 0) + 1
            continue

        has_conflict = (
            item.get("material_conflict") is True
            or _status_value(item, "conflict_status") == "conflicting"
        )
        if has_conflict:
            saw_new_material_conflict = True
            blocked_counts["material_conflict"] = blocked_counts.get(
                "material_conflict", 0
            ) + 1
            continue

        availability = _status_value(item, "availability")
        supersession = _status_value(item, "supersession")
        freshness = _status_value(item, "freshness")
        if availability in _BLOCKING_AVAILABILITY:
            reason = "unavailable"
        elif supersession in _BLOCKING_SUPERSESSION:
            reason = "superseded"
        elif freshness in _BLOCKING_FRESHNESS:
            reason = "future"
        elif item.get("admitted") is not True:
            reason = "not_admitted"
        else:
            reason = ""

        if reason:
            blocked_counts[reason] = blocked_counts.get(reason, 0) + 1
            continue

        evidence_id = _identifier(item)
        url = item.get("url")
        if not evidence_id or not isinstance(url, str) or not url.strip():
            blocked_counts["unattributed"] = blocked_counts.get(
                "unattributed", 0
            ) + 1
            continue

        eligible.append({
            "evidence_id": evidence_id,
            "url": url.strip()[:2_000],
            "source_time_field": time_field,
            "source_time": item_time.isoformat(),
        })
        if len(eligible) >= MAX_ELIGIBLE_EVIDENCE:
            break

    result = {
        **base,
        "status": "insufficient_new_evidence",
        "prior_created_at": prior_time.isoformat(),
        "ticker": ticker,
        "blocked_counts": blocked_counts,
    }
    if saw_new_material_conflict:
        result["status"] = "conflicting_evidence"
        return result
    if eligible:
        result["status"] = "ready"
        result["ready_for_comparison"] = True
        result["eligible_evidence"] = eligible
    return result
