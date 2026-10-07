"""Deterministic freshness, revision, and contradiction states for evidence."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Iterable, Mapping


_STALE_AFTER_DAYS = {
    "market_data": 3,
    "news": 14,
    "trade_publication": 30,
    "government_dataset": 45,
    "exchange": 45,
    "issuer_release": 180,
    "investor_presentation": 180,
    "transcript": 180,
    "regulator": 365,
    "regulatory_filing": 550,
}
_EXPLICIT_STATES = {
    "current", "stale", "superseded", "conflicting", "unavailable", "unknown",
}


def _instant(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = datetime.fromisoformat(text[:10])
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _claim_key(claim: Mapping[str, object]) -> tuple[str, ...] | None:
    ticker = str(claim.get("ticker") or "").strip().upper()
    metric = str(claim.get("metric") or "").strip()
    period = str(
        claim.get("period_end") or claim.get("as_of") or claim.get("period") or ""
    ).strip()
    unit = str(claim.get("unit") or "").strip()
    scope = str(claim.get("scope") or "consolidated").strip()
    if not ticker or not metric or not period or not unit:
        return None
    return ticker, metric, period, unit, scope


def _claim_value(claim: Mapping[str, object]) -> str | None:
    value = claim.get("raw_value")
    if value is None or isinstance(value, bool):
        return None
    try:
        return format(Decimal(str(value)).normalize(), "f")
    except (InvalidOperation, ValueError):
        return None


def _conflict_id(key: tuple[str, ...]) -> str:
    digest = hashlib.sha256("|".join(key).encode("utf-8")).hexdigest()[:16]
    return f"conflict:{digest}"


def _revision_groups(items: list[object]) -> dict[tuple[str, ...], list[tuple[int, dict]]]:
    groups: dict[tuple[str, ...], list[tuple[int, dict]]] = {}
    for index, item in enumerate(items):
        claims = getattr(item, "verified_claims", [])
        if not isinstance(claims, list):
            continue
        for claim in claims:
            if not isinstance(claim, Mapping):
                continue
            key = _claim_key(claim)
            value = _claim_value(claim)
            if key and value is not None:
                groups.setdefault(key, []).append((index, {"value": value, **dict(claim)}))
    return groups


def apply_evidence_integrity(
    items: Iterable[object], references: list[dict], *, as_of: str | None = None,
    evaluated_at: str | None = None,
) -> dict:
    """Annotate references and return a fail-closed evidence integrity summary."""
    material = list(items)
    reference_by_item = {
        int(reference.get("_item_index", index)): reference
        for index, reference in enumerate(references)
    }
    evaluation_clock = _instant(evaluated_at) or datetime.now(timezone.utc)
    boundary = _instant(as_of) or evaluation_clock
    counts = {state: 0 for state in _EXPLICIT_STATES}
    conflicts: list[dict] = []

    for index, reference in enumerate(references):
        item_index = int(reference.get("_item_index", index))
        item = material[item_index] if item_index < len(material) else None
        explicit = str(getattr(item, "freshness_status", "") or "").lower()
        status = explicit if explicit in _EXPLICIT_STATES else "unknown"
        reason = str(getattr(item, "status_reason", "") or "").strip()
        # Relationship proof cannot be used before it was public, and must
        # never replace the historical source's actual filing/freshness date.
        from .issuer_succession import item_predecessor_provenance
        disclosures = getattr(item, "risk_disclosures", []) or []
        has_relationship = any(isinstance(value, dict) and "issuer_relationship" in value
                               for value in disclosures)
        if has_relationship:
            predecessor = item_predecessor_provenance(item)
            if predecessor is None:
                status, reason = "unavailable", "predecessor relationship is not authorized for this source"
            elif _instant(predecessor["available_at"]) > boundary:
                status, reason = "unavailable", "predecessor relationship proof is after analysis boundary"
        if status == "unknown":
            available = getattr(item, "availability_status", "available")
            timestamp = _instant(
                reference.get("observed_at")
                or reference.get("filed_at")
                or reference.get("published_at")
            )
            threshold = _STALE_AFTER_DAYS.get(str(reference.get("source_type") or ""))
            if available == "unavailable":
                status, reason = "unavailable", reason or "source unavailable"
            elif timestamp is not None and timestamp > boundary:
                status = "unavailable"
                reason = reason or "evidence timestamp is after analysis boundary"
            elif timestamp is not None and threshold is not None:
                age_days = max(0, (boundary - timestamp).days)
                if age_days > threshold:
                    status = "stale"
                    reason = reason or f"evidence is {age_days} days old"
                else:
                    status = "current"
                    reason = reason or f"evidence is {age_days} days old"
        reference["freshness_status"] = status
        reference["status_reason"] = reason or None
        reference["conflict_group_id"] = None
        reference["supersedes_reference_id"] = None

    for key, rows in _revision_groups(material).items():
        indexes = sorted({index for index, _ in rows if index in reference_by_item})
        if len(rows) < 2 or not indexes:
            continue
        amendments = [
            index for index in indexes
            if str(reference_by_item[index].get("document_type") or "").endswith("/A")
        ]
        if amendments and len(indexes) > 1:
            latest = max(
                amendments,
                key=lambda index: str(reference_by_item[index].get("filed_at") or ""),
            )
            older = [index for index in indexes if index != latest]
            if older:
                reference_by_item[latest]["supersedes_reference_id"] = (
                    reference_by_item[older[-1]]["id"]
                )
                for index in older:
                    reference_by_item[index]["freshness_status"] = "superseded"
                    reference_by_item[index]["status_reason"] = (
                        f"superseded by {reference_by_item[latest]['id']}"
                    )
            continue
        values = {row["value"] for _, row in rows}
        if len(values) > 1:
            group_id = _conflict_id(key)
            reference_ids = []
            for index in indexes:
                reference_by_item[index]["freshness_status"] = "conflicting"
                reference_by_item[index]["status_reason"] = "material claim values disagree"
                reference_by_item[index]["conflict_group_id"] = group_id
                reference_ids.append(reference_by_item[index]["id"])
            conflicts.append({
                "id": group_id,
                "claim": {
                    "ticker": key[0], "metric": key[1], "period": key[2],
                    "unit": key[3], "scope": key[4],
                },
                "reference_ids": reference_ids,
            })

    for reference in references:
        counts[reference["freshness_status"]] += 1
        item_index = int(reference.get("_item_index", -1))
        if 0 <= item_index < len(material):
            item = material[item_index]
            try:
                setattr(item, "freshness_status", reference["freshness_status"])
                setattr(item, "status_reason", reference.get("status_reason"))
            except (AttributeError, TypeError, ValueError):
                # Immutable provider records still receive the status through
                # their audit reference; mutable RetrievedEvidence records also
                # carry it into every downstream prompt.
                pass
    active_states = {state for state, count in counts.items() if count}
    if not references:
        overall = "unavailable"
    elif conflicts:
        overall = "conflicting"
    elif len(active_states) == 1:
        overall = next(iter(active_states))
    else:
        overall = "mixed"
    return {
        "schema_version": 1,
        "overall_status": overall,
        "as_of": as_of,
        "evaluated_at": evaluation_clock.isoformat(),
        "counts": counts,
        "has_material_conflict": bool(conflicts),
        "conflicts": conflicts,
    }
