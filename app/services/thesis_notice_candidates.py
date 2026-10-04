"""Deterministic, zero-delivery candidates for thesis-relevant new evidence.

This module is intentionally a pure decision boundary. It does not poll,
schedule work, write memory, or send notifications. A later delivery layer
may consume an eligible candidate only after separate authorization and
operational controls are approved.
"""

from __future__ import annotations

import re
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

NOTICE_CANDIDATE_VERSION = 1
MAX_MATCHED_TERMS = 8
_BLOCKED_STATES = {"conflicting", "superseded", "unavailable", "future"}
_STOPWORDS = {
    "about", "after", "against", "been", "before", "company", "could",
    "current", "from", "growth", "have", "into", "more", "most", "that",
    "their", "these", "this", "thesis", "through", "what", "when", "which",
    "with", "would",
}


def _parse_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    cleaned = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(cleaned)
    except ValueError:
        try:
            parsed = datetime.fromisoformat(cleaned[:10])
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _tokens(value: object) -> set[str]:
    if not isinstance(value, str):
        return set()
    return {
        token for token in re.findall(r"[a-z0-9]+", value.lower())
        if len(token) >= 4 and token not in _STOPWORDS
    }


def _value(item: object, field: str, default: object = "") -> object:
    if isinstance(item, Mapping):
        return item.get(field, default)
    return getattr(item, field, default)


def _artifact_text(artifact: Mapping[str, Any]) -> str:
    thesis = artifact.get("thesis")
    if not isinstance(thesis, Mapping):
        return ""
    parts: list[str] = []
    for value in thesis.values():
        if isinstance(value, str):
            parts.append(value)
        elif isinstance(value, list):
            parts.extend(str(item) for item in value if isinstance(item, str))
    return " ".join(parts)


def evaluate_thesis_notice_candidate(
    *, artifact: Mapping[str, Any], artifact_recorded_at: str,
    evidence: object, owner_selected: bool = False,
) -> dict[str, Any]:
    """Return an auditable eligibility decision without causing side effects."""
    base: dict[str, Any] = {
        "candidate_version": NOTICE_CANDIDATE_VERSION,
        "eligible": False,
        "delivery_enabled": False,
        "reason": "unavailable",
        "ticker": None,
        "evidence_id": None,
        "matched_terms": [],
    }
    if artifact.get("status") != "available":
        base["reason"] = "artifact_unavailable"
        return base
    if not owner_selected:
        base["reason"] = "owner_selection_required"
        return base

    ticker = str(artifact.get("ticker") or "").strip().upper()
    evidence_ticker = str(_value(evidence, "ticker") or "").strip().upper()
    base["ticker"] = ticker or None
    base["evidence_id"] = str(
        _value(evidence, "id") or _value(evidence, "evidence_id") or ""
    ).strip() or None
    if ticker and evidence_ticker and ticker != evidence_ticker:
        base["reason"] = "ticker_mismatch"
        return base

    state = str(
        _value(evidence, "freshness_status")
        or _value(evidence, "availability")
        or "current"
    ).strip().lower()
    if state in _BLOCKED_STATES or bool(_value(evidence, "material_conflict", False)):
        base["reason"] = "evidence_not_admitted"
        return base

    prior_at = _parse_datetime(artifact_recorded_at)
    evidence_at = _parse_datetime(
        _value(evidence, "published_at")
        or _value(evidence, "filed_at")
        or _value(evidence, "timestamp")
    )
    if prior_at is None or evidence_at is None:
        base["reason"] = "timestamp_unavailable"
        return base
    if evidence_at <= prior_at:
        base["reason"] = "not_newer_than_thesis"
        return base

    thesis_tokens = _tokens(_artifact_text(artifact))
    evidence_tokens = _tokens(
        f"{_value(evidence, 'title')} {_value(evidence, 'summary')} "
        f"{_value(evidence, 'section')}"
    )
    matched = sorted(thesis_tokens & evidence_tokens)[:MAX_MATCHED_TERMS]
    base["matched_terms"] = matched
    if len(matched) < 2:
        base["reason"] = "not_materially_related"
        return base

    base["eligible"] = True
    base["reason"] = "new_admitted_related_evidence"
    return base


def build_thesis_notice_candidates(
    *, artifact: Mapping[str, Any], artifact_recorded_at: str,
    evidence_items: Iterable[object], owner_selected: bool = False,
) -> list[dict[str, Any]]:
    """Evaluate evidence deterministically; return only eligible candidates."""
    candidates = [
        evaluate_thesis_notice_candidate(
            artifact=artifact,
            artifact_recorded_at=artifact_recorded_at,
            evidence=item,
            owner_selected=owner_selected,
        )
        for item in evidence_items
    ]
    return [candidate for candidate in candidates if candidate["eligible"]]


def evaluate_thesis_notice_candidates(
    *, artifact: Mapping[str, Any], artifact_recorded_at: str,
    evidence_items: Iterable[object], owner_selected: bool = False,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Return eligible candidates plus bounded aggregate decision telemetry.

    The summary contains only fixed reason codes and counts. It intentionally
    excludes thesis text, evidence text, owner identifiers, and evidence IDs so
    it is safe to attach to account-owned response metadata.
    """
    decisions = [
        evaluate_thesis_notice_candidate(
            artifact=artifact,
            artifact_recorded_at=artifact_recorded_at,
            evidence=item,
            owner_selected=owner_selected,
        )
        for item in evidence_items
    ]
    eligible = [decision for decision in decisions if decision["eligible"]]
    rejection_counts = Counter(
        str(decision.get("reason") or "unavailable")
        for decision in decisions
        if not decision["eligible"]
    )
    return eligible, {
        "evaluated_count": len(decisions),
        "eligible_count": len(eligible),
        "rejection_counts": dict(sorted(rejection_counts.items())),
    }
