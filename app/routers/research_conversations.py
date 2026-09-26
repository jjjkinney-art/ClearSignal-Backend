"""Protected HTTP surface for account-owned research conversations.

This router exposes the private persistence layer without enabling semantic
recall or accepting client-authored assistant conclusions.  Assistant turns
will be written server-side when the authenticated ``/ask`` integration is
added; this first route slice only permits users to append their own text.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field, field_validator, model_validator


router = APIRouter(prefix="/research/conversations", tags=["research-memory"])


class ConversationCreateRequest(BaseModel):
    title: str = Field(default="", max_length=200)
    tickers: list[str] = Field(default_factory=list, max_length=25)
    scope_started_at: Optional[datetime] = None
    scope_ended_at: Optional[datetime] = None
    portfolio_id: Optional[str] = Field(default=None, max_length=128)

    @field_validator("tickers")
    @classmethod
    def validate_tickers(cls, values: list[str]) -> list[str]:
        result: list[str] = []
        for raw in values:
            ticker = (raw or "").strip().upper()
            if not ticker or len(ticker) > 20 or not all(
                char.isalnum() or char in ".-" for char in ticker
            ):
                raise ValueError("Each ticker must be a valid symbol of at most 20 characters")
            if ticker not in result:
                result.append(ticker)
        return result

    @field_validator("scope_started_at", "scope_ended_at")
    @classmethod
    def require_timezone(cls, value: Optional[datetime]) -> Optional[datetime]:
        if value is not None and value.tzinfo is None:
            raise ValueError("Research scope timestamps must include a timezone")
        return value

    @model_validator(mode="after")
    def validate_scope_window(self):
        if (
            self.scope_started_at
            and self.scope_ended_at
            and self.scope_started_at > self.scope_ended_at
        ):
            raise ValueError("scope_started_at must not follow scope_ended_at")
        return self


class UserMessageCreateRequest(BaseModel):
    text: str = Field(min_length=1, max_length=50_000)
    request_ref: Optional[str] = Field(default=None, max_length=100)

    @field_validator("text")
    @classmethod
    def validate_text(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("Message text is required")
        return text


def _owner(request: Request) -> str:
    from app.dependencies.auth import require_user_id

    return require_user_id(request)


def _factory():
    from app.db.connection import get_session_factory

    factory = get_session_factory()
    if factory is None:
        raise HTTPException(status_code=503, detail="Research conversations are unavailable.")
    return factory


@router.post("", status_code=201, summary="Create a private research conversation")
async def create_research_conversation(
    body: ConversationCreateRequest,
    request: Request,
) -> dict:
    from app.services.research_conversations import create_conversation

    owner = _owner(request)
    async with _factory()() as session:
        conversation = await create_conversation(
            session,
            user_id=owner,
            title=body.title,
            tickers=body.tickers,
            scope_started_at=body.scope_started_at,
            scope_ended_at=body.scope_ended_at,
            portfolio_id=body.portfolio_id,
        )
        await session.commit()
    return conversation


@router.get("", summary="Search the current account's research conversations")
async def list_research_conversations(
    request: Request,
    q: Optional[str] = Query(default=None, max_length=200),
    ticker: Optional[str] = Query(default=None, pattern=r"^[A-Za-z0-9.\-]{1,20}$"),
    created_after: Optional[datetime] = None,
    created_before: Optional[datetime] = None,
    limit: int = Query(default=30, ge=1, le=50),
) -> list[dict]:
    from app.services.research_conversations import list_conversations

    if any(
        value is not None and value.tzinfo is None
        for value in (created_after, created_before)
    ):
        raise HTTPException(status_code=422, detail="Date filters must include a timezone")
    if created_after and created_before and created_after > created_before:
        raise HTTPException(status_code=422, detail="created_after must not follow created_before")
    owner = _owner(request)
    async with _factory()() as session:
        return await list_conversations(
            session,
            user_id=owner,
            query=q,
            ticker=ticker,
            created_after=created_after,
            created_before=created_before,
            limit=limit,
        )


@router.get("/{conversation_id}", summary="Open one private research conversation")
async def get_research_conversation(conversation_id: str, request: Request) -> dict:
    from app.services.research_conversations import get_conversation

    owner = _owner(request)
    async with _factory()() as session:
        conversation = await get_conversation(
            session, user_id=owner, conversation_id=conversation_id
        )
    if conversation is None:
        raise HTTPException(status_code=404, detail="Research conversation not found.")
    return conversation


@router.post(
    "/{conversation_id}/messages",
    status_code=201,
    summary="Append the current user's message to a research conversation",
)
async def append_research_user_message(
    conversation_id: str,
    body: UserMessageCreateRequest,
    request: Request,
) -> dict:
    from app.services.research_conversations import append_message

    owner = _owner(request)
    async with _factory()() as session:
        message = await append_message(
            session,
            user_id=owner,
            conversation_id=conversation_id,
            role="user",
            text=body.text,
            request_ref=body.request_ref,
        )
        if message is not None:
            await session.commit()
    if message is None:
        raise HTTPException(status_code=404, detail="Research conversation not found.")
    return message


@router.delete("/{conversation_id}", summary="Remove a private research conversation")
async def delete_research_conversation(conversation_id: str, request: Request) -> dict:
    from app.services.research_conversations import soft_delete_conversation

    owner = _owner(request)
    async with _factory()() as session:
        deleted = await soft_delete_conversation(
            session, user_id=owner, conversation_id=conversation_id
        )
        if deleted:
            await session.commit()
    if not deleted:
        raise HTTPException(status_code=404, detail="Research conversation not found.")
    return {"deleted": True, "conversation_id": conversation_id}
