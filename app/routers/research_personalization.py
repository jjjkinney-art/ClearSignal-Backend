"""Protected API for explicit account-owned Intelligence Mode preferences."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel


router = APIRouter(prefix="/research/personalization", tags=["research-memory"])


class PersonalizationProfileRequest(BaseModel):
    enabled: bool = False
    response_depth: Literal["concise", "balanced", "deep"] = "balanced"
    time_horizon: Literal["near_term", "mixed", "multi_year"] = "mixed"
    analysis_emphasis: Literal[
        "downside_first", "balanced", "opportunity_first"
    ] = "balanced"
    evidence_style: Literal["primary_sources", "balanced_sources"] = "primary_sources"


def _owner(request: Request) -> str:
    from app.dependencies.auth import require_user_id

    return require_user_id(request)


def _factory():
    from app.db.connection import get_session_factory

    factory = get_session_factory()
    if factory is None:
        raise HTTPException(
            status_code=503,
            detail="Research personalization is unavailable.",
        )
    return factory


@router.get("", summary="Read the current account's Intelligence profile")
async def get_research_personalization(request: Request) -> dict:
    from app.services.research_personalization import get_profile

    owner = _owner(request)
    async with _factory()() as session:
        return await get_profile(session, user_id=owner)


@router.put("", summary="Set explicit Intelligence Mode preferences")
async def put_research_personalization(
    body: PersonalizationProfileRequest,
    request: Request,
) -> dict:
    from app.services.research_personalization import upsert_profile

    owner = _owner(request)
    async with _factory()() as session:
        profile = await upsert_profile(
            session,
            user_id=owner,
            enabled=body.enabled,
            response_depth=body.response_depth,
            time_horizon=body.time_horizon,
            analysis_emphasis=body.analysis_emphasis,
            evidence_style=body.evidence_style,
        )
        await session.commit()
    return profile


@router.delete("", summary="Delete explicit Intelligence Mode preferences")
async def delete_research_personalization(request: Request) -> dict:
    from app.services.research_personalization import delete_profile

    owner = _owner(request)
    async with _factory()() as session:
        deleted = await delete_profile(session, user_id=owner)
        if deleted:
            await session.commit()
    return {"deleted": deleted}
