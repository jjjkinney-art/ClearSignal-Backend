"""Owner-scoped export for ClearSignal research memory.

The export is read-only and includes records still retained after an individual
conversation is hidden, so users can inspect the complete research-memory data
associated with their authenticated account.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select

from ..db.models import ResearchConversation, ResearchMessage
from .research_personalization import get_profile


EXPORT_SCHEMA_VERSION = 1


def _owner(user_id: str) -> str:
    owner = (user_id or "").strip()
    if not owner:
        raise ValueError("An authenticated owner is required")
    return owner


def _iso(value) -> str | None:
    return value.isoformat() if value is not None else None


def _conversation(row: ResearchConversation, messages: list[ResearchMessage]) -> dict:
    return {
        "id": row.id,
        "title": row.title,
        "scope": {
            "tickers": list(row.scope_tickers or []),
            "started_at": _iso(row.scope_started_at),
            "ended_at": _iso(row.scope_ended_at),
            "portfolio_id": row.scope_portfolio_id,
        },
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at),
        "deleted_at": _iso(row.deleted_at),
        "messages": [
            {
                "id": message.id,
                "ordinal": message.ordinal,
                "role": message.role,
                "text": message.text,
                "request_ref": message.request_ref,
                "snapshot_version": message.snapshot_version,
                "displayed_snapshot": dict(message.displayed_snapshot or {}),
                "created_at": _iso(message.created_at),
            }
            for message in messages
        ],
    }


async def export_research_memory(session, *, user_id: str) -> dict:
    """Return every research-memory record belonging to one authenticated owner."""

    owner = _owner(user_id)
    conversations = (
        await session.execute(
            select(ResearchConversation)
            .where(ResearchConversation.user_id == owner)
            .order_by(
                ResearchConversation.created_at.asc(),
                ResearchConversation.id.asc(),
            )
        )
    ).scalars().all()
    messages = (
        await session.execute(
            select(ResearchMessage)
            .where(ResearchMessage.user_id == owner)
            .order_by(
                ResearchMessage.conversation_id.asc(),
                ResearchMessage.ordinal.asc(),
            )
        )
    ).scalars().all()

    by_conversation: dict[str, list[ResearchMessage]] = {}
    for message in messages:
        by_conversation.setdefault(message.conversation_id, []).append(message)

    exported = [
        _conversation(row, by_conversation.get(row.id, []))
        for row in conversations
    ]
    return {
        "schema_version": EXPORT_SCHEMA_VERSION,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "owner_scope": "authenticated_account",
        "includes_hidden_conversations": True,
        "conversation_count": len(exported),
        "message_count": len(messages),
        "conversations": exported,
        "personalization": await get_profile(session, user_id=owner),
    }
