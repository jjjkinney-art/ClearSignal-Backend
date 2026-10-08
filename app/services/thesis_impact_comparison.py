"""Audited orchestration for explicitly selected historical thesis comparison."""

from __future__ import annotations

import re
from typing import Any, Iterable, Mapping

from .thesis_impact_evidence import gate_thesis_impact_evidence
from .thesis_impact_result import build_thesis_impact_result


COMPARISON_ORCHESTRATOR_VERSION = 2
_STOPWORDS = {
    "about", "after", "against", "because", "been", "before", "company",
    "could", "current", "from", "growth", "have", "into", "more", "most",
    "that", "their", "these", "this", "thesis", "through", "what", "when",
    "which", "with", "would",
}


def _value(item: object, field: str, default: object = "") -> object:
    if isinstance(item, Mapping):
        return item.get(field, default)
    return getattr(item, field, default)


def _text(value: object) -> str:
    return " ".join(value.split()) if isinstance(value, str) else ""


def _tokens(value: object) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9]+", _text(value).lower())
        if len(token) >= 4 and token not in _STOPWORDS
    }


def _historical_thesis(context: Mapping[str, Any]) -> Mapping[str, Any]:
    artifact = context.get("artifact")
    if isinstance(artifact, Mapping):
        thesis = artifact.get("thesis")
        if isinstance(thesis, Mapping):
            return thesis
    thesis = context.get("historical_thesis")
    return thesis if isinstance(thesis, Mapping) else {}


def _claimed_direction(thesis: object) -> str:
    trend = _text(_value(thesis, "thesis_trend")).lower()
    mapped = {
        "strengthening": "stronger",
        "strengthened": "stronger",
        "weakening": "weaker",
        "weakened": "weaker",
        "stable": "unchanged",
        "unchanged": "unchanged",
    }.get(trend)
    if mapped:
        return mapped

    conclusion = _text(
        _value(thesis, "direct_answer") or _value(thesis, "conclusion")
    ).lower()
    directions = []
    if re.search(r"\b(strengthened|strengthening|stronger|improved)\b", conclusion):
        directions.append("stronger")
    if re.search(r"\b(weakened|weakening|weaker|deteriorated)\b", conclusion):
        directions.append("weaker")
    if re.search(r"\b(unchanged|stable|no material change)\b", conclusion):
        directions.append("unchanged")
    return directions[0] if len(directions) == 1 else "unverified"


def _evidence_ticker(item: object) -> str:
    """Retain producer scope; the selected thesis cannot supply missing scope."""
    tickers = set()
    explicit = _text(_value(item, "ticker")).upper()
    if explicit:
        tickers.add(explicit)
    for field in ("verified_claims", "risk_disclosures", "calculated_claims"):
        claims = _value(item, field, [])
        if isinstance(claims, list):
            for claim in claims:
                if isinstance(claim, Mapping):
                    ticker = _text(claim.get("ticker")).upper()
                    if ticker:
                        tickers.add(ticker)
    return next(iter(tickers)) if len(tickers) == 1 else ""


def _candidate_evidence(
    *,
    evidence: Iterable[object],
    comparison_text: str,
    references: list[dict] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, str]]]:
    comparison_tokens = _tokens(comparison_text)
    candidates: list[dict[str, Any]] = []
    display_by_id: dict[str, dict[str, str]] = {}
    for index, item in enumerate(evidence, 1):
        evidence_id = _text(
            _value(item, "evidence_id")
            or _value(item, "id")
            or _value(item, "source_id")
        ) or f"E{index}"
        title = _text(_value(item, "title")) or "Untitled evidence"
        summary = _text(_value(item, "summary"))
        overlap = comparison_tokens & _tokens(f"{title} {summary}")
        timestamp = (
            _value(item, "published_at")
            or _value(item, "filed_at")
            or _value(item, "observed_at")
            or _value(item, "timestamp")
        )
        url = _text(_value(item, "url"))
        reference = None
        if references is not None:
            from .evidence_references import _evidence_url
            url = _evidence_url(item) or ""
            reference = next((ref for ref in references
                if ref.get("title") == str(_value(item, "title") or "Untitled evidence").strip()[:300]
                and ref.get("source") == str(_value(item, "source") or "Unknown source").strip()[:120]
                and ref.get("published_at") == (str(_value(item, "timestamp") or "").strip()[:40] or None)
                and ref.get("url") == (url or None)), None)
            # Admission can remove earlier items. Never re-enumerate their
            # surviving citations or substitute an unmatched reference.
            evidence_id = _text(reference.get("id")) if reference else ""
            if not re.fullmatch(r"E[1-9]\d*", evidence_id):
                evidence_id = ""
        states = [_text(_value(item, "freshness_status")).lower(),
                  _text(_value(item, "freshness")).lower(),
                  _text(reference.get("freshness_status")).lower() if reference else ""]
        freshness = next((state for state in states if state in {
            "stale", "superseded", "conflicting", "unavailable", "future", "post_boundary",
        }), next((state for state in states if state and state != "unknown"), "unknown"))
        candidates.append({
            "evidence_id": evidence_id,
            "ticker": _evidence_ticker(item),
            "url": url,
            "published_at": timestamp,
            "materially_related": len(overlap) >= 2,
            # The router passes the post-admission evidence list. An explicit
            # false marker still fails closed.
            "admitted": _value(item, "admitted", True) is not False,
            "availability": ("unavailable" if freshness == "unavailable" else
                _value(item, "availability_status", _value(item, "availability", "available"))),
            "supersession": ("superseded" if freshness == "superseded" else
                _value(item, "supersession", "current")),
            "freshness": freshness,
            "material_conflict": _value(item, "material_conflict", False) is True,
            "conflict_status": ("conflicting" if freshness == "conflicting" else
                _value(item, "conflict_status", "")),
        })
        display_by_id[evidence_id] = {
            "title": title,
            "source": _text(_value(item, "source")) or "Unknown source",
        }
    return candidates, display_by_id


def _safe_correction(prior_created_at: str, gate_status: str) -> str:
    if gate_status == "conflicting_evidence":
        return (
            "ClearSignal cannot verify a directional thesis change because the "
            "newer materially related evidence is conflicting. The prior conclusion "
            "remains historical; the current direction is unverified."
        )
    cutoff = (prior_created_at or "")[:10] or "the selected date"
    return (
        "ClearSignal cannot verify a directional thesis change because this "
        "analysis did not retrieve attributable, materially related, admitted "
        f"evidence newer than the selected record dated {cutoff}. The prior "
        "conclusion remains historical; the current direction is unverified."
    )


def evaluate_selected_thesis_impact(
    *,
    thesis: object,
    context: Mapping[str, Any],
    evidence: Iterable[object],
    evidence_integrity: Mapping[str, Any] | None = None,
    references: list[dict] | None = None,
) -> dict[str, Any]:
    """Run the newer-evidence gate and claim-binding validator as one audit."""
    historical = _historical_thesis(context)
    prior_created_at = _text(context.get("created_at"))
    ticker = _text(context.get("ticker")).upper()
    prior_conclusion = _text(
        historical.get("direct_answer") or historical.get("conclusion")
    )
    current_conclusion = _text(
        _value(thesis, "direct_answer") or _value(thesis, "conclusion")
    )
    candidates, display_by_id = _candidate_evidence(
        evidence=evidence,
        comparison_text=f"{prior_conclusion} {current_conclusion}",
        references=references,
    )
    gate = gate_thesis_impact_evidence(
        prior_created_at=prior_created_at,
        target_ticker=ticker,
        evidence=candidates,
        evidence_integrity=evidence_integrity,
    )

    proposed_direction = _claimed_direction(thesis)
    claims = []
    for item in gate.get("eligible_evidence", []):
        evidence_id = item["evidence_id"]
        display = display_by_id.get(evidence_id, {})
        claims.append({
            "text": (
                f"{display.get('title', 'New evidence')} — "
                f"{display.get('source', 'Unknown source')}"
            ),
            "evidence_ids": [evidence_id],
        })
    result = build_thesis_impact_result(
        gate=gate,
        proposed_direction=proposed_direction,
        rationale=(
            "The directional comparison is limited to attributable, materially "
            "related evidence newer than the selected historical record."
        ),
        claims=claims,
    )

    if result["status"] != "supported":
        correction = _safe_correction(prior_created_at, gate.get("status", ""))
        if hasattr(thesis, "direct_answer"):
            thesis.direct_answer = correction
        if hasattr(thesis, "what_changed"):
            thesis.what_changed = [
                "No qualifying evidence established a supported directional change."
            ]
        if hasattr(thesis, "thesis_trend"):
            thesis.thesis_trend = "unclear"
        if hasattr(thesis, "change_drivers"):
            thesis.change_drivers = []
        direction = "unclear"
        status = (
            "conflicting_evidence"
            if gate.get("status") == "conflicting_evidence"
            else "insufficient_new_evidence"
        )
        current_conclusion = correction
    else:
        direction = {
            "stronger": "strengthened",
            "weaker": "weakened",
            "unchanged": "unchanged",
        }[result["direction"]]
        status = (
            "verified_change"
            if direction in {"strengthened", "weakened"}
            else "no_directional_change"
        )
        if hasattr(thesis, "what_changed"):
            thesis.what_changed = [claim["text"] for claim in result["claims"]]
        if hasattr(thesis, "change_drivers"):
            thesis.change_drivers = list(thesis.what_changed)
        if hasattr(thesis, "thesis_trend"):
            thesis.thesis_trend = {
                "strengthened": "strengthening",
                "weakened": "weakening",
                "unchanged": "stable",
            }[direction]

    return {
        "comparison_version": 3,
        "orchestrator_version": COMPARISON_ORCHESTRATOR_VERSION,
        "status": status,
        "direction": direction,
        "reason": result["reason"],
        "prior_recorded_at": prior_created_at or None,
        "prior_conclusion": prior_conclusion,
        "current_conclusion": current_conclusion,
        "evidence_changes": result["evidence_references"],
        "evidence_gate": gate,
        "evidence_bound_result": result,
    }
