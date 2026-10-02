"""Owner-filtered loading for persisted historical thesis-memory artifacts.

The loader accepts one explicit conversation selection. Owner, deletion, role,
and ticker predicates are enforced before returning any artifact. Raw research
message text is never read.
"""

from __future__ import annotations

from typing import Any, Mapping

from sqlalchemy import select

from ..db.models import ResearchConversation, ResearchMessage
from .thesis_memory_artifacts import (
    THESIS_MEMORY_ARTIFACT_VERSION,
    build_thesis_memory_artifact,
)


MAX_ARTIFACT_SCAN_MESSAGES = 20


def _unavailable(status: str) -> dict[str, Any]:
    return {
        "applied": False,
        "status": status,
        "historical_only": True,
        "requires_fresh_evidence": True,
    }


async def load_owned_thesis_memory_artifact(
    session,
    *,
    user_id: str,
    conversation_id: str,
    target_ticker: str,
) -> dict[str, Any]:
    """Load the latest safe artifact for an explicitly selected owned conversation."""
    owner = (user_id or "").strip()
    selected_id = (conversation_id or "").strip()
    ticker = (target_ticker or "").strip().upper()[:20]
    if not owner or not selected_id or not ticker:
        return _unavailable("unavailable")

    conversation = (
        await session.execute(
            select(ResearchConversation).where(
                ResearchConversation.id == selected_id,
                ResearchConversation.user_id == owner,
                ResearchConversation.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if conversation is None:
        return _unavailable("unavailable")

    scoped_tickers = {
        str(value).strip().upper()
        for value in (conversation.scope_tickers or [])
        if str(value).strip()
    }
    if ticker not in scoped_tickers:
        return _unavailable("ticker_mismatch")

    messages = (
        await session.execute(
            select(ResearchMessage)
            .where(
                ResearchMessage.conversation_id == conversation.id,
                ResearchMessage.user_id == owner,
                ResearchMessage.role == "assistant",
            )
            .order_by(ResearchMessage.ordinal.desc())
            .limit(MAX_ARTIFACT_SCAN_MESSAGES)
        )
    ).scalars().all()

    for message in messages:
        snapshot = message.displayed_snapshot or {}
        if not isinstance(snapshot, Mapping):
            continue
        stored = snapshot.get("thesis_memory_artifact")
        if not isinstance(stored, Mapping):
            continue
        if (
            stored.get("artifact_version") != THESIS_MEMORY_ARTIFACT_VERSION
            or stored.get("status") != "available"
            or stored.get("historical_only") is not True
            or stored.get("requires_fresh_evidence") is not True
        ):
            continue

        # Re-project from the exact saved structured response instead of trusting
        # arbitrary keys that may exist in a stored JSON object.
        artifact = build_thesis_memory_artifact(snapshot.get("response"))
        if artifact.get("status") != "available":
            continue
        if artifact.get("ticker") != ticker:
            continue

        return {
            "applied": True,
            "status": "available",
            "historical_only": True,
            "requires_fresh_evidence": True,
            "conversation_id": conversation.id,
            "message_id": message.id,
            "created_at": message.created_at.isoformat(),
            "snapshot_version": message.snapshot_version,
            "artifact": artifact,
        }

    return _unavailable("no_artifact")
