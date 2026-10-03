"""Protected API for the current account's thesis notice inbox."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel


router = APIRouter(prefix="/research/notices", tags=["research-memory"])


class NoticeStatusRequest(BaseModel):
    status: Literal["unread", "read", "dismissed"]


def _owner(request: Request) -> str:
    from app.dependencies.auth import require_user_id
    return require_user_id(request)


def _factory():
    from app.db.connection import get_session_factory
    factory = get_session_factory()
    if factory is None:
        raise HTTPException(status_code=503, detail="Research notices are unavailable.")
    return factory


@router.get("", summary="List the current account's thesis notices")
async def list_research_thesis_notices(
    request: Request,
    status: Literal["unread", "read", "dismissed"] | None = None,
    ticker: str | None = Query(default=None, pattern=r"^[A-Za-z0-9.\-]{1,20}$"),
    limit: int = Query(default=50, ge=1, le=100),
) -> list[dict]:
    from app.services.research_thesis_notices import list_notices
    async with _factory()() as session:
        return await list_notices(
            session, user_id=_owner(request), status=status,
            ticker=ticker, limit=limit,
        )


@router.patch("/{notice_id}", summary="Update one owned thesis notice")
async def update_research_thesis_notice(
    notice_id: str, body: NoticeStatusRequest, request: Request,
) -> dict:
    from app.services.research_thesis_notices import set_notice_status
    async with _factory()() as session:
        notice = await set_notice_status(
            session, user_id=_owner(request), notice_id=notice_id,
            status=body.status,
        )
        if notice is not None:
            await session.commit()
    if notice is None:
        raise HTTPException(status_code=404, detail="Research notice not found.")
    return notice


@router.delete("/{notice_id}", summary="Delete one owned thesis notice")
async def delete_research_thesis_notice(notice_id: str, request: Request) -> dict:
    from app.services.research_thesis_notices import delete_notice
    async with _factory()() as session:
        deleted = await delete_notice(
            session, user_id=_owner(request), notice_id=notice_id,
        )
        if deleted:
            await session.commit()
    if not deleted:
        raise HTTPException(status_code=404, detail="Research notice not found.")
    return {"deleted": True, "notice_id": notice_id}
