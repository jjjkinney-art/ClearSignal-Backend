"""Private account-owned conversation persistence and bounded text recall.

The service deliberately starts with deterministic text search and explicit
scope/date filters. Semantic recall comes only after isolation, deletion and
retrieval-quality acceptance tests pass.
"""

from __future__ import annotations

import json
import re
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
MAX_RECALL_MESSAGES = 500
MAX_RECALL_CANDIDATES = 3
RESPONSE_SNAPSHOT_VERSION = 1

_RECALL_STOPWORDS = {
    "a", "about", "an", "and", "are", "as", "at", "be", "did", "do",
    "for", "from", "had", "has", "have", "i", "in", "is", "it", "last",
    "me", "month", "my", "of", "on", "or", "our", "that", "the", "this",
    "to", "was", "we", "were", "what", "when", "which", "with", "you",
}


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


def _recall_tokens(value: str) -> set[str]:
    """Normalize ordinary-language recall terms without an external index.

    This intentionally remains deterministic and inspectable. It is not a
    semantic/vector search and never sends stored text to a model.
    """
    tokens: set[str] = set()
    for raw in re.findall(r"[a-z0-9]+", (value or "").lower()):
        if raw in _RECALL_STOPWORDS or len(raw) < 2:
            continue
        token = raw
        for suffix in ("ation", "ments", "ment", "ing", "ies", "ed", "s"):
            if token.endswith(suffix) and len(token) - len(suffix) >= 4:
                token = token[:-len(suffix)]
                break
        tokens.add(token)
    return tokens


def _excerpt(text: str, matched_tokens: set[str], limit: int = 360) -> str:
    cleaned = " ".join((text or "").split())
    if len(cleaned) <= limit:
        return cleaned
    lowered = cleaned.lower()
    positions = [lowered.find(token) for token in matched_tokens if lowered.find(token) >= 0]
    start = max(0, (min(positions) if positions else 0) - 80)
    end = min(len(cleaned), start + limit)
    prefix = "…" if start else ""
    suffix = "…" if end < len(cleaned) else ""
    return f"{prefix}{cleaned[start:end].strip()}{suffix}"


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


def assistant_text_from_response(response: dict) -> str:
    """Return exact searchable text from a completed /ask response.

    Prefer explicit answer fields that already exist in the emitted payload.
    When a response has only a structured shape, serialize that shape instead
    of manufacturing a summary or conclusion.
    """
    answer = response.get("answer")
    candidates: list[object] = []
    if isinstance(answer, dict):
        thesis = answer.get("investment_thesis")
        if isinstance(thesis, dict):
            candidates.extend((thesis.get("direct_answer"), thesis.get("conclusion")))
        candidates.extend((answer.get("answer"), answer.get("direct_answer")))
    candidates.append(answer)
    for candidate in candidates:
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    return json.dumps(answer if answer is not None else {}, ensure_ascii=False, sort_keys=True)


async def append_completed_turn(session, *, user_id: str, conversation_id: str,
                                question: str, response: dict,
                                request_ref: Optional[str] = None) -> bool:
    """Atomically stage one successful user/assistant turn for the owner.

    The caller controls the transaction boundary. Any validation failure in
    the assistant snapshot therefore rolls back the user message too.
    """
    if not isinstance(response, dict):
        raise ValueError("Completed research response must be an object")
    user_message = await append_message(
        session,
        user_id=user_id,
        conversation_id=conversation_id,
        role="user",
        text=question,
        request_ref=request_ref,
    )
    if user_message is None:
        return False
    assistant_message = await append_message(
        session,
        user_id=user_id,
        conversation_id=conversation_id,
        role="assistant",
        text=assistant_text_from_response(response),
        request_ref=request_ref,
        displayed_snapshot={
            "response_version": RESPONSE_SNAPSHOT_VERSION,
            "response": response,
        },
        snapshot_version=RESPONSE_SNAPSHOT_VERSION,
    )
    return assistant_message is not None


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


async def recall_conversations(session, *, user_id: str, query: str,
                               ticker: Optional[str] = None,
                               created_after: Optional[datetime] = None,
                               created_before: Optional[datetime] = None,
                               limit: int = MAX_RECALL_CANDIDATES) -> dict:
    """Return explicit owner-scoped recall candidates without prompt injection.

    Retrieval is deliberately bounded and deterministic. Owner and deletion
    predicates are applied in SQL before any in-process ranking. The returned
    excerpts are quotations from saved messages, never synthesized summaries.
    """
    owner = _owner(user_id)
    normalized_query = (query or "").strip()[:MAX_SEARCH_LENGTH]
    query_tokens = _recall_tokens(normalized_query)
    if not query_tokens:
        return {
            "status": "unavailable", "query": normalized_query,
            "scope": {"ticker": (ticker or "").strip().upper()[:20] or None},
            "historical_only": True,
            "current_evidence_checked": False,
            "candidates": [],
        }

    stmt = (
        select(ResearchConversation, ResearchMessage)
        .join(
            ResearchMessage,
            ResearchMessage.conversation_id == ResearchConversation.id,
        )
        .where(
            ResearchConversation.user_id == owner,
            ResearchConversation.deleted_at.is_(None),
            ResearchMessage.user_id == owner,
        )
    )
    wanted_ticker = (ticker or "").strip().upper()[:20]
    if wanted_ticker:
        stmt = stmt.where(
            func.lower(cast(ResearchConversation.scope_tickers, String)).contains(
                f'"{wanted_ticker.lower()}"'
            )
        )
    if created_after:
        stmt = stmt.where(ResearchConversation.created_at >= created_after)
    if created_before:
        stmt = stmt.where(ResearchConversation.created_at <= created_before)
    rows = (await session.execute(
        stmt.order_by(ResearchMessage.created_at.desc()).limit(MAX_RECALL_MESSAGES)
    )).all()

    grouped: dict[str, dict] = {}
    for conversation, message in rows:
        candidate = grouped.setdefault(conversation.id, {
            "conversation": conversation,
            "messages": [],
            "matched_tokens": set(),
            "score": 0.0,
        })
        message_tokens = _recall_tokens(message.text)
        title_tokens = _recall_tokens(conversation.title)
        ticker_tokens = {str(value).lower() for value in (conversation.scope_tickers or [])}
        overlap = query_tokens & (message_tokens | title_tokens | ticker_tokens)
        if overlap:
            coverage = len(overlap) / len(query_tokens)
            precision = len(overlap) / max(1, len(message_tokens | title_tokens | ticker_tokens))
            score = coverage * 0.8 + min(precision, 0.2)
            if normalized_query.lower() in message.text.lower():
                score += 0.08
            candidate["score"] = max(candidate["score"], score)
            candidate["matched_tokens"].update(overlap)
        candidate["messages"].append(message)

    ranked = sorted(
        (item for item in grouped.values() if item["score"] >= 0.34),
        key=lambda item: (
            item["score"],
            item["conversation"].updated_at,
            item["conversation"].id,
        ),
        reverse=True,
    )
    bounded_limit = max(1, min(int(limit), MAX_RECALL_CANDIDATES))
    selected = ranked[:bounded_limit]
    candidates = []
    for item in selected:
        conversation = item["conversation"]
        matching_messages = sorted(
            (
                message for message in item["messages"]
                if query_tokens & _recall_tokens(message.text)
            ),
            key=lambda message: (message.created_at, message.ordinal),
            reverse=True,
        )[:2]
        if not matching_messages:
            matching_messages = sorted(
                item["messages"],
                key=lambda message: (message.created_at, message.ordinal),
                reverse=True,
            )[:2]
        candidates.append({
            "conversation": _conversation(conversation),
            "match": {
                "score": round(min(item["score"], 1.0), 3),
                "terms": sorted(item["matched_tokens"]),
                "reason": "Shared terms in your saved title, scope, or transcript.",
            },
            "excerpts": [{
                "message_id": message.id,
                "role": message.role,
                "text": _excerpt(message.text, item["matched_tokens"]),
                "created_at": message.created_at.isoformat(),
                "snapshot_version": message.snapshot_version,
                "displayed_snapshot": dict(message.displayed_snapshot or {}),
            } for message in matching_messages],
        })

    status = "unavailable"
    if candidates:
        status = "matched"
        if len(selected) > 1:
            top, second = selected[0]["score"], selected[1]["score"]
            if second >= top * 0.8 and top - second <= 0.12:
                status = "ambiguous"
    return {
        "status": status,
        "query": normalized_query,
        "scope": {"ticker": wanted_ticker or None},
        "historical_only": True,
        "current_evidence_checked": False,
        "candidates": candidates,
    }


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
