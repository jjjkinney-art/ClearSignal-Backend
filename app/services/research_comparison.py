"""Deterministic gate for comparisons against selected historical research."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping


COMPARISON_VERSION = 2
MAX_EVIDENCE_CHANGES = 5
_DIRECTION_PATTERNS = {
    "strengthened": re.compile(r"\b(strengthened|strengthening|improved|stronger)\b", re.I),
    "weakened": re.compile(r"\b(weakened|weakening|deteriorated|weaker)\b", re.I),
    "unchanged": re.compile(r"\b(unchanged|stable|no material change)\b", re.I),
}
_STOPWORDS = {
    "about", "after", "against", "apple", "because", "been", "before",
    "company", "could", "current", "from", "growth", "have", "into",
    "more", "most", "that", "their", "these", "this", "thesis", "through",
    "what", "when", "which", "with", "would",
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


def _direction(value: str) -> str:
    found = [name for name, pattern in _DIRECTION_PATTERNS.items() if pattern.search(value)]
    return found[0] if len(found) == 1 else "unclear"


def _claimed_direction(thesis, conclusion: str) -> str:
    """Prefer explicit conclusion language, then the structured trend field."""
    direction = _direction(conclusion)
    if direction != "unclear":
        return direction
    trend = str(getattr(thesis, "thesis_trend", "") or "").strip().lower()
    return {
        "strengthening": "strengthened",
        "strengthened": "strengthened",
        "weakening": "weakened",
        "weakened": "weakened",
        "stable": "unchanged",
        "unchanged": "unchanged",
    }.get(trend, "unclear")


def _evidence_value(item: object, field: str, default: object = "") -> object:
    if isinstance(item, Mapping):
        return item.get(field, default)
    return getattr(item, field, default)


def _related_fresh_evidence(
    evidence: Iterable[object], *, prior_at: datetime, comparison_text: str,
) -> list[dict]:
    comparison_tokens = _tokens(comparison_text)
    related: list[dict] = []
    for item in evidence:
        timestamp = str(_evidence_value(item, "timestamp") or "")
        published_at = _parse_datetime(timestamp)
        if published_at is None or published_at <= prior_at:
            continue
        title = str(_evidence_value(item, "title") or "").strip()
        summary = str(_evidence_value(item, "summary") or "").strip()
        overlap = comparison_tokens & _tokens(f"{title} {summary}")
        if len(overlap) < 2:
            continue
        related.append({
            "title": title or "Untitled evidence",
            "source": str(_evidence_value(item, "source") or "Unknown source"),
            "published_at": published_at.date().isoformat(),
            "matched_terms": sorted(overlap)[:8],
            "url": str(_evidence_value(item, "url") or "") or None,
            "document_type": str(_evidence_value(item, "document_type") or "") or None,
            "page": _evidence_value(item, "page", None),
            "section": str(_evidence_value(item, "section") or "") or None,
        })
    related.sort(key=lambda item: item["published_at"], reverse=True)
    return related[:MAX_EVIDENCE_CHANGES]


def _confidence_movement(prior: object, current: object) -> dict:
    prior_value = float(prior) if isinstance(prior, (int, float)) else None
    current_value = float(current) if isinstance(current, (int, float)) else None
    delta = round(current_value - prior_value, 4) if (
        prior_value is not None and current_value is not None
    ) else None
    if delta is None:
        direction = "unavailable"
    elif delta > 0:
        direction = "increased"
    elif delta < 0:
        direction = "decreased"
    else:
        direction = "unchanged"
    return {
        "prior": prior_value,
        "current": current_value,
        "delta": delta,
        "direction": direction,
        "evidentiary_status": "context_only",
    }


def _longitudinal_delta(
    *, context: Mapping[str, Any], prior_conclusion: str, current_conclusion: str,
    status: str, direction: str, reason: str, confidence: dict, evidence_changes: list[dict],
) -> dict:
    """Stable UI/API shape for prior → current → why → confidence."""
    return {
        "prior": {
            "recorded_at": context.get("created_at"),
            "conclusion": prior_conclusion,
            "confidence": confidence["prior"],
        },
        "current": {
            "conclusion": current_conclusion,
            "confidence": confidence["current"],
        },
        "change": {
            "status": status,
            "direction": direction,
            "explanation": reason,
        },
        "confidence_movement": confidence,
        "supporting_evidence": evidence_changes,
    }


def apply_evidence_gated_comparison(thesis, context: Mapping[str, Any], evidence) -> dict:
    """Validate a model's directional comparison and correct unsupported prose.

    A directional claim is allowed only when attributable, related evidence is
    newer than the selected historical record. Confidence movement by itself is
    never treated as evidence that the thesis changed.
    """
    prior_at = _parse_datetime(context.get("created_at"))
    historical = context.get("historical_thesis")
    if prior_at is None or not isinstance(historical, Mapping):
        reason = "The selected historical snapshot could not be compared safely."
        return {
            "comparison_version": COMPARISON_VERSION,
            "status": "unavailable",
            "direction": "unclear",
            "reason": reason,
            "evidence_changes": [],
            "longitudinal_delta": _longitudinal_delta(
                context=context, prior_conclusion="", current_conclusion="",
                status="unavailable", direction="unclear", reason=reason,
                confidence=_confidence_movement(None, None), evidence_changes=[],
            ),
        }

    prior_conclusion = str(
        historical.get("direct_answer") or historical.get("conclusion") or ""
    ).strip()
    current_conclusion = str(
        getattr(thesis, "direct_answer", "") or getattr(thesis, "conclusion", "") or ""
    ).strip()
    claimed_direction = _claimed_direction(thesis, current_conclusion)
    related = _related_fresh_evidence(
        evidence,
        prior_at=prior_at,
        comparison_text=f"{prior_conclusion} {current_conclusion}",
    )

    prior_confidence = historical.get("confidence_score")
    current_confidence = getattr(thesis, "confidence_score", None)
    confidence = _confidence_movement(prior_confidence, current_confidence)
    confidence_delta = confidence["delta"]

    if claimed_direction in {"strengthened", "weakened"} and not related:
        cutoff = prior_at.date().isoformat()
        correction = (
            f"ClearSignal cannot verify that the prior thesis {claimed_direction} because "
            f"this analysis did not retrieve materially related evidence published after "
            f"the selected record dated {cutoff}. The prior conclusion remains historical; "
            "the current direction is unverified."
        )
        thesis.direct_answer = correction
        thesis.what_changed = [
            "No attributable, materially related evidence newer than the selected prior record was retrieved."
        ]
        thesis.thesis_trend = "unclear"
        thesis.change_drivers = []
        reason = "Directional change requires related evidence newer than the prior record."
        result = {
            "comparison_version": COMPARISON_VERSION,
            "status": "insufficient_new_evidence",
            "direction": "unclear",
            "claimed_direction_rejected": claimed_direction,
            "reason": reason,
            "prior_recorded_at": context.get("created_at"),
            "prior_conclusion": prior_conclusion,
            "current_conclusion": correction,
            "prior_confidence": prior_confidence if isinstance(prior_confidence, (int, float)) else None,
            "current_confidence": current_confidence if isinstance(current_confidence, (int, float)) else None,
            "confidence_delta": confidence_delta,
            "evidence_changes": [],
        }
        result["longitudinal_delta"] = _longitudinal_delta(
            context=context, prior_conclusion=prior_conclusion,
            current_conclusion=correction, status=result["status"],
            direction=result["direction"], reason=reason,
            confidence=confidence, evidence_changes=[],
        )
        return result

    status = "verified_change" if claimed_direction in {"strengthened", "weakened"} and related else "no_directional_change"
    direction = claimed_direction if status == "verified_change" else "unchanged"
    if status == "verified_change":
        thesis.what_changed = [
            f"{item['title']} — {item['source']} ({item['published_at']})"
            for item in related
        ]
        thesis.thesis_trend = "strengthening" if direction == "strengthened" else "weakening"
        thesis.change_drivers = list(thesis.what_changed)
    reason = (
        "Directional change is supported by related evidence newer than the prior record."
        if status == "verified_change"
        else "The analysis did not establish a supported directional change."
    )
    result = {
        "comparison_version": COMPARISON_VERSION,
        "status": status,
        "direction": direction,
        "reason": reason,
        "prior_recorded_at": context.get("created_at"),
        "prior_conclusion": prior_conclusion,
        "current_conclusion": current_conclusion,
        "prior_confidence": prior_confidence if isinstance(prior_confidence, (int, float)) else None,
        "current_confidence": current_confidence if isinstance(current_confidence, (int, float)) else None,
        "confidence_delta": confidence_delta,
        "evidence_changes": related,
    }
    result["longitudinal_delta"] = _longitudinal_delta(
        context=context, prior_conclusion=prior_conclusion,
        current_conclusion=current_conclusion, status=status, direction=direction,
        reason=reason, confidence=confidence, evidence_changes=related,
    )
    return result
