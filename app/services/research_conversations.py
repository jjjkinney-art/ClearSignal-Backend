"""Private account-owned conversation persistence for research memory.

No API route imports this module yet. The service deliberately starts with
bounded text search and explicit scope/date filters; semantic recall comes only
after isolation, deletion and retrieval-quality acceptance tests pass.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Iterable, Optional

from sqlalchemy import String, cast, delete, func, or_, select

from ..db.models import ResearchConversation, ResearchMessage


ALLOWED_ROLES = {"user", "assistant", "system"}
MAX_TITLE_LENGTH = 200
MAX_MESSAGE_LENGTH = 50_000
MAX_SNAPSHOT_BYTES = 100_000
MAX_SEARCH_LENGTH = 200
MAX_LIST_LIMIT = 50


def _owner(user_id: str) -> str:
    value = (user_id or "").strip()
    if not value:
        raise ValueError("An authenticated owner is required")
    return value


def _tickers(values: Optional[Iterable[str]]) -> list[str]:
    result: list[str] = []
    for value in values or ():
        ticker = str(value).strip().upper()
        if ticker and ticker not in result:
            result.append(ticker[:20])
    return result[:25]


def _conversation(row: ResearchConversation) -> dict:
    return {
        "id": row.id,
        "title": row.title,
        "scope": {
            "tickers": list(row.scope_tickers or []),
            "started_at": row.scope_started_at.isoformat() if row.scope_started_at else None,
            "ended_at": row.scope_ended_at.isoformat() if row.scope_ended_at else None,
            "portfolio_id": row.scope_portfolio_id,
        },
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
    }


def _message(row: ResearchMessage) -> dict:
    return {
        "id": row.id,
        "ordinal": row.ordinal,
        "role": row.role,
        "text": row.text,
        "request_ref": row.request_ref,
        "snapshot_version": row.snapshot_version,
        "displayed_snapshot": dict(row.displayed_snapshot or {}),
        "created_at": row.created_at.isoformat(),
    }


async def create_conversation(session, *, user_id: str, title: str = "",
                              tickers: Optional[Iterable[str]] = None,
                              scope_started_at: Optional[datetime] = None,
                              scope_ended_at: Optional[datetime] = None,
                              portfolio_id: Optional[str] = None) -> dict:
    owner = _owner(user_id)
    if scope_started_at and scope_ended_at and scope_started_at > scope_ended_at:
        raise ValueError("Research scope start must not follow its end")
    row = ResearchConversation(
        user_id=owner,
        title=(title or "").strip()[:MAX_TITLE_LENGTH],
        scope_tickers=_tickers(tickers),
        scope_started_at=scope_started_at,
        scope_ended_at=scope_ended_at,
        scope_portfolio_id=(portfolio_id or "").strip() or None,
    )
    session.add(row)
    await session.flush()
    return _conversation(row)


async def get_conversation(session, *, user_id: str, conversation_id: str,
                           include_messages: bool = True) -> Optional[dict]:
    owner = _owner(user_id)
    row = (await session.execute(select(ResearchConversation).where(
        ResearchConversation.id == conversation_id,
        ResearchConversation.user_id == owner,
        ResearchConversation.deleted_at.is_(None),
    ))).scalar_one_or_none()
    if row is None:
        return None
    result = _conversation(row)
    if include_messages:
        messages = (await session.execute(select(ResearchMessage).where(
            ResearchMessage.conversation_id == row.id,
            ResearchMessage.user_id == owner,
        ).order_by(ResearchMessage.ordinal.asc()))).scalars().all()
        result["messages"] = [_message(message) for message in messages]
    return result


async def append_message(session, *, user_id: str, conversation_id: str,
                         role: str, text: str, request_ref: Optional[str] = None,
                         displayed_snapshot: Optional[dict] = None,
                         snapshot_version: int = 1) -> Optional[dict]:
    owner = _owner(user_id)
    if role not in ALLOWED_ROLES:
        raise ValueError("Unsupported research message role")
    if not text or not text.strip():
        raise ValueError("Research message text is required")
    if len(text) > MAX_MESSAGE_LENGTH:
        raise ValueError("Research message is too large")
    if snapshot_version < 1:
        raise ValueError("snapshot_version must be positive")
    if displayed_snapshot is not None and not isinstance(displayed_snapshot, dict):
        raise ValueError("displayed_snapshot must be an object")
    snapshot = displayed_snapshot or {}
    if len(json.dumps(snapshot, ensure_ascii=False).encode("utf-8")) > MAX_SNAPSHOT_BYTES:
        raise ValueError("displayed_snapshot is too large")
    ref = (request_ref or "").strip()[:100] or None

    conversation = (await session.execute(select(ResearchConversation).where(
        ResearchConversation.id == conversation_id,
        ResearchConversation.user_id == owner,
        ResearchConversation.deleted_at.is_(None),
    ).with_for_update())).scalar_one_or_none()
    if conversation is None:
        return None

    if ref:
        existing = (await session.execute(select(ResearchMessage).where(
            ResearchMessage.conversation_id == conversation_id,
            ResearchMessage.user_id == owner,
            ResearchMessage.request_ref == ref,
            ResearchMessage.role == role,
        ))).scalar_one_or_none()
        if existing is not None:
            return _message(existing)

    last_ordinal = (await session.execute(select(func.max(ResearchMessage.ordinal)).where(
        ResearchMessage.conversation_id == conversation_id,
        ResearchMessage.user_id == owner,
    ))).scalar_one()
    row = ResearchMessage(
        conversation_id=conversation_id,
        user_id=owner,
        ordinal=(last_ordinal or 0) + 1,
        role=role,
        text=text.strip(),
        request_ref=ref,
        snapshot_version=snapshot_version,
        displayed_snapshot=snapshot,
    )
    session.add(row)
    conversation.updated_at = datetime.now(timezone.utc)
    await session.flush()
    return _message(row)


async def list_conversations(session, *, user_id: str, query: Optional[str] = None,
                             ticker: Optional[str] = None,
                             created_after: Optional[datetime] = None,
                             created_before: Optional[datetime] = None,
                             limit: int = 30) -> list[dict]:
    owner = _owner(user_id)
    bounded_limit = max(1, min(int(limit), MAX_LIST_LIMIT))
    term = (query or "").strip()[:MAX_SEARCH_LENGTH]
    stmt = select(ResearchConversation).where(
        ResearchConversation.user_id == owner,
        ResearchConversation.deleted_at.is_(None),
    )
    if ticker:
        wanted = ticker.strip().upper()[:20]
        # JSON containment differs across SQLite/PostgreSQL; the bounded text
        # predicate is portable and is always applied after owner filtering.
        stmt = stmt.where(func.lower(cast(ResearchConversation.scope_tickers, String)).contains(
            f'"{wanted.lower()}"'
        ))
    if created_after:
        stmt = stmt.where(ResearchConversation.created_at >= created_after)
    if created_before:
        stmt = stmt.where(ResearchConversation.created_at <= created_before)
    if term:
        matching_ids = select(ResearchMessage.conversation_id).where(
            ResearchMessage.user_id == owner,
            func.lower(ResearchMessage.text).contains(term.lower()),
        )
        stmt = stmt.where(or_(
            func.lower(ResearchConversation.title).contains(term.lower()),
            ResearchConversation.id.in_(matching_ids),
        ))
    rows = (await session.execute(stmt.order_by(
        ResearchConversation.updated_at.desc(), ResearchConversation.id.desc(),
    ).limit(bounded_limit))).scalars().all()
    return [_conversation(row) for row in rows]


async def soft_delete_conversation(session, *, user_id: str,
                                   conversation_id: str) -> bool:
    owner = _owner(user_id)
    row = (await session.execute(select(ResearchConversation).where(
        ResearchConversation.id == conversation_id,
        ResearchConversation.user_id == owner,
        ResearchConversation.deleted_at.is_(None),
    ).with_for_update())).scalar_one_or_none()
    if row is None:
        return False
    now = datetime.now(timezone.utc)
    row.deleted_at = now
    row.updated_at = now
    await session.flush()
    return True


async def hard_delete_conversation(session, *, user_id: str,
                                   conversation_id: str) -> bool:
    """Erase one owner's conversation and messages for verified deletion flows."""
    owner = _owner(user_id)
    row = (await session.execute(select(ResearchConversation).where(
        ResearchConversation.id == conversation_id,
        ResearchConversation.user_id == owner,
    ).with_for_update())).scalar_one_or_none()
    if row is None:
        return False
    await session.execute(delete(ResearchMessage).where(
        ResearchMessage.conversation_id == conversation_id,
        ResearchMessage.user_id == owner,
    ))
    await session.delete(row)
    await session.flush()
    return True
