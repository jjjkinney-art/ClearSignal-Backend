"""Authenticated export surface for account-owned research memory."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse


router = APIRouter(prefix="/research", tags=["research-memory"])


def _owner(request: Request) -> str:
    from app.dependencies.auth import require_user_id

    return require_user_id(request)


def _factory():
    from app.db.connection import get_session_factory

    factory = get_session_factory()
    if factory is None:
        raise HTTPException(status_code=503, detail="Research export is unavailable.")
    return factory


@router.get("/export", summary="Export the current account's research memory")
async def export_research_memory(request: Request) -> JSONResponse:
    from app.services.research_export import export_research_memory as build_export

    owner = _owner(request)
    async with _factory()() as session:
        payload = await build_export(session, user_id=owner)
    return JSONResponse(
        content=payload,
        headers={
            "Content-Disposition": 'attachment; filename="clearsignal-research-memory.json"',
            "Cache-Control": "private, no-store",
        },
    )
