"""Owner-filtered, bounded and transparent research recall."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field, field_validator, model_validator


router = APIRouter(prefix="/research", tags=["research-memory"])


class RecallRequest(BaseModel):
    query: str = Field(min_length=2, max_length=200)
    ticker: Optional[str] = Field(default=None, pattern=r"^[A-Za-z0-9.\-]{1,20}$")
    created_after: Optional[datetime] = None
    created_before: Optional[datetime] = None
    limit: int = Field(default=3, ge=1, le=3)

    @field_validator("query")
    @classmethod
    def clean_query(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 2:
            raise ValueError("Recall query is required")
        return value

    @field_validator("ticker")
    @classmethod
    def clean_ticker(cls, value: Optional[str]) -> Optional[str]:
        return value.strip().upper() if value else None

    @field_validator("created_after", "created_before")
    @classmethod
    def require_timezone(cls, value: Optional[datetime]) -> Optional[datetime]:
        if value is not None and value.tzinfo is None:
            raise ValueError("Recall timestamps must include a timezone")
        return value

    @model_validator(mode="after")
    def validate_window(self):
        if self.created_after and self.created_before and self.created_after > self.created_before:
            raise ValueError("created_after must not follow created_before")
        return self


def _owner(request: Request) -> str:
    from app.dependencies.auth import require_user_id

    return require_user_id(request)


@router.post("/recall", summary="Recall the current account's prior research")
async def recall_research(body: RecallRequest, request: Request) -> dict:
    from app.db.connection import get_session_factory
    from app.services.research_conversations import recall_conversations

    factory = get_session_factory()
    if factory is None:
        raise HTTPException(status_code=503, detail="Research recall is unavailable.")
    async with factory() as session:
        return await recall_conversations(
            session,
            user_id=_owner(request),
            query=body.query,
            ticker=body.ticker,
            created_after=body.created_after,
            created_before=body.created_before,
            limit=body.limit,
        )
