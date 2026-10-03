"""Account-owned lifecycle for zero-delivery thesis notice previews."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any, Mapping

from sqlalchemy import select

from ..db.models import ResearchConversation, ResearchMessage, ResearchThesisNotice

_STATUSES = {"unread", "read", "dismissed"}
_MAX_TERMS = 8


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _serialize(row: ResearchThesisNotice) -> dict[str, Any]:
    return {
        "id": row.id,
        "ticker": row.ticker,
        "status": row.status,
        "source": {
            "conversation_id": row.conversation_id,
            "message_id": row.message_id,
            "evidence_id": row.evidence_id,
        },
        "matched_terms": list(row.matched_terms or []),
        "candidate_version": row.candidate_version,
        "preview_version": row.preview_version,
        "delivery_enabled": False,
        "detected_at": row.detected_at.isoformat() if row.detected_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _fingerprint(*, conversation_id: str, message_id: str,
                 ticker: str, evidence_id: str) -> str:
    canonical = "\x1f".join((conversation_id, message_id, ticker, evidence_id))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


async def persist_notice_preview(session, *, user_id: str,
                                 preview: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    """Persist eligible server preview candidates, idempotently and owner-scoped."""
    owner = (user_id or "").strip()
    if not owner or not isinstance(preview, Mapping):
        return []
    if (preview.get("available") is not True
            or preview.get("delivery_enabled") is not False
            or preview.get("status") != "candidate_found"):
        return []
    selection = preview.get("selection")
    if not isinstance(selection, Mapping):
        return []
    conversation_id = str(selection.get("conversation_id") or "").strip()
    message_id = str(selection.get("message_id") or "").strip()
    ticker = str(selection.get("ticker") or "").strip().upper()
    if not conversation_id or not message_id or not ticker:
        return []

    owned_source = (await session.execute(
        select(ResearchMessage.id)
        .join(ResearchConversation, ResearchConversation.id == ResearchMessage.conversation_id)
        .where(
            ResearchConversation.id == conversation_id,
            ResearchConversation.user_id == owner,
            ResearchConversation.deleted_at.is_(None),
            ResearchMessage.id == message_id,
            ResearchMessage.user_id == owner,
            ResearchMessage.conversation_id == conversation_id,
        )
    )).scalar_one_or_none()
    if owned_source is None:
        return []

    persisted: list[dict[str, Any]] = []
    candidates = preview.get("candidates")
    if not isinstance(candidates, list):
        return []
    for candidate in candidates:
        if not isinstance(candidate, Mapping):
            continue
        if candidate.get("eligible") is not True or candidate.get("delivery_enabled") is not False:
            continue
        if str(candidate.get("ticker") or "").strip().upper() != ticker:
            continue
        evidence_id = str(candidate.get("evidence_id") or "").strip()
        if not evidence_id:
            continue
        fingerprint = _fingerprint(
            conversation_id=conversation_id, message_id=message_id,
            ticker=ticker, evidence_id=evidence_id,
        )
        row = (await session.execute(select(ResearchThesisNotice).where(
            ResearchThesisNotice.user_id == owner,
            ResearchThesisNotice.fingerprint == fingerprint,
        ))).scalar_one_or_none()
        if row is None:
            terms = candidate.get("matched_terms")
            bounded_terms = [str(term)[:80] for term in terms[:_MAX_TERMS]] \
                if isinstance(terms, list) else []
            row = ResearchThesisNotice(
                user_id=owner,
                conversation_id=conversation_id,
                message_id=message_id,
                ticker=ticker,
                evidence_id=evidence_id[:200],
                fingerprint=fingerprint,
                matched_terms=bounded_terms,
                candidate_version=int(candidate.get("candidate_version") or 1),
                preview_version=int(preview.get("preview_version") or 1),
                delivery_enabled=False,
                status="unread",
                detected_at=_utcnow(),
                updated_at=_utcnow(),
            )
            session.add(row)
            await session.flush()
        persisted.append(_serialize(row))
    return persisted


async def list_notices(session, *, user_id: str, status: str | None = None,
                       ticker: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    owner = (user_id or "").strip()
    if not owner:
        return []
    stmt = (
        select(ResearchThesisNotice)
        .join(ResearchConversation,
              ResearchConversation.id == ResearchThesisNotice.conversation_id)
        .where(
            ResearchThesisNotice.user_id == owner,
            ResearchConversation.user_id == owner,
            ResearchConversation.deleted_at.is_(None),
        )
    )
    if status in _STATUSES:
        stmt = stmt.where(ResearchThesisNotice.status == status)
    if ticker:
        stmt = stmt.where(ResearchThesisNotice.ticker == ticker.strip().upper())
    rows = (await session.execute(
        stmt.order_by(ResearchThesisNotice.detected_at.desc(),
                      ResearchThesisNotice.id.desc()).limit(max(1, min(limit, 100)))
    )).scalars().all()
    return [_serialize(row) for row in rows]


async def set_notice_status(session, *, user_id: str, notice_id: str,
                            status: str) -> dict[str, Any] | None:
    if status not in _STATUSES:
        raise ValueError("unsupported notice status")
    row = (await session.execute(select(ResearchThesisNotice).where(
        ResearchThesisNotice.id == notice_id,
        ResearchThesisNotice.user_id == (user_id or "").strip(),
    ))).scalar_one_or_none()
    if row is None:
        return None
    row.status = status
    row.updated_at = _utcnow()
    await session.flush()
    return _serialize(row)


async def delete_notice(session, *, user_id: str, notice_id: str) -> bool:
    row = (await session.execute(select(ResearchThesisNotice).where(
        ResearchThesisNotice.id == notice_id,
        ResearchThesisNotice.user_id == (user_id or "").strip(),
    ))).scalar_one_or_none()
    if row is None:
        return False
    await session.delete(row)
    await session.flush()
    return True
