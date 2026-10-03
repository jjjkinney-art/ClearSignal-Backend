"""Owner-selected, zero-delivery preview for thesis-relevant evidence.

The async boundary reuses the account-owned research-memory loader, including
its owner, deletion, ticker, and structured-snapshot predicates. The pure
projection returns an audit preview only; it never persists state or delivers
a notification.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping

from .evidence_references import _safe_public_url
from .thesis_notice_candidates import build_thesis_notice_candidates


THESIS_NOTICE_PREVIEW_VERSION = 1


def _value(item: object, field: str, default: object = "") -> object:
    if isinstance(item, Mapping):
        return item.get(field, default)
    return getattr(item, field, default)


def _evidence_id(item: object) -> str:
    return str(_value(item, "id") or _value(item, "evidence_id") or "").strip()


def _bounded_evidence_snapshot(item: object) -> dict[str, Any]:
    """Keep only presentation-safe trigger metadata from admitted evidence."""
    return {
        "title": str(_value(item, "title") or "Untitled evidence")[:300],
        "source": str(_value(item, "source") or "Unknown source")[:120],
        "published_at": str(
            _value(item, "published_at")
            or _value(item, "filed_at")
            or _value(item, "timestamp")
            or ""
        )[:40] or None,
        "url": _safe_public_url(_value(item, "url", None)),
        "document_type": str(_value(item, "document_type") or "")[:80] or None,
        "section": str(_value(item, "section") or "")[:160] or None,
        "page": _value(item, "page", None),
    }


def build_selected_thesis_notice_preview(
    *, context: Mapping[str, Any] | None, evidence_items: Iterable[object],
) -> dict[str, Any]:
    """Evaluate current evidence against one already-authorized memory context."""
    unavailable = {
        "preview_version": THESIS_NOTICE_PREVIEW_VERSION,
        "available": False,
        "delivery_enabled": False,
        "status": "unavailable",
        "candidates": [],
    }
    if not isinstance(context, Mapping) or context.get("applied") is not True:
        result = dict(unavailable)
        result["status"] = str(
            context.get("status") if isinstance(context, Mapping) else "unavailable"
        )
        return result

    required = ("conversation_id", "message_id", "ticker", "created_at")
    if any(not context.get(field) for field in required):
        return unavailable
    thesis = context.get("historical_thesis")
    if not isinstance(thesis, Mapping) or not thesis:
        result = dict(unavailable)
        result["status"] = "no_structured_snapshot"
        return result

    artifact = {
        "status": "available",
        "historical_only": True,
        "requires_fresh_evidence": True,
        "ticker": str(context["ticker"]).upper(),
        "thesis": dict(thesis),
    }
    material = list(evidence_items)
    candidates = build_thesis_notice_candidates(
        artifact=artifact,
        artifact_recorded_at=str(context["created_at"]),
        evidence_items=material,
        owner_selected=True,
    )
    evidence_by_id = {
        _evidence_id(item): item for item in material if _evidence_id(item)
    }
    for candidate in candidates:
        item = evidence_by_id.get(str(candidate.get("evidence_id") or ""))
        if item is not None:
            candidate["evidence"] = _bounded_evidence_snapshot(item)
    return {
        "preview_version": THESIS_NOTICE_PREVIEW_VERSION,
        "available": True,
        "delivery_enabled": False,
        "status": "candidate_found" if candidates else "no_material_change_candidate",
        "selection": {
            "conversation_id": context["conversation_id"],
            "message_id": context["message_id"],
            "ticker": str(context["ticker"]).upper(),
            "recorded_at": context["created_at"],
            "historical_only": True,
        },
        "candidates": candidates,
    }


async def preview_selected_thesis_notices(
    session, *, user_id: str, conversation_id: str, target_ticker: str,
    evidence_items: Iterable[object],
) -> dict[str, Any]:
    """Load exactly one owner-selected record, then build a zero-delivery preview."""
    from .research_memory_context import load_selected_research_context

    context = await load_selected_research_context(
        session,
        user_id=user_id,
        conversation_id=conversation_id,
        target_ticker=target_ticker,
    )
    return build_selected_thesis_notice_preview(
        context=context,
        evidence_items=evidence_items,
    )
