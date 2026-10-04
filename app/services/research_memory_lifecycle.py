"""Internal owner-scoped deletion primitive for ClearSignal research memory.

This module exposes no HTTP route. Callers must independently verify identity,
approval, retention policy, and transaction boundaries before using it against a
persistent database. The admin rehearsal exercises it only with synthetic rows
in an ephemeral in-memory database.
"""

from __future__ import annotations

from sqlalchemy import delete

from app.db.models import (
    ResearchConversation,
    ResearchMessage,
    ResearchPersonalizationProfile,
    ResearchThesisNotice,
)


def _owner(user_id: str) -> str:
    owner = (user_id or "").strip()
    if not owner:
        raise ValueError("A verified owner is required")
    return owner


async def delete_owner_research_memory(session, *, user_id: str) -> dict[str, int]:
    """Delete one owner's research-memory rows inside the caller's transaction."""

    owner = _owner(user_id)
    counts: dict[str, int] = {}
    for key, model in (
        ("thesis_notices", ResearchThesisNotice),
        ("messages", ResearchMessage),
        ("conversations", ResearchConversation),
        ("personalization_profiles", ResearchPersonalizationProfile),
    ):
        result = await session.execute(delete(model).where(model.user_id == owner))
        counts[key] = max(0, int(result.rowcount or 0))
    await session.flush()
    return counts
