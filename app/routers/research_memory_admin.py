"""Authenticated operator rehearsals for private research-memory controls."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from app.security.authz import require_admin
from app.services.account_deletion_policy_rehearsal import (
    run_account_deletion_policy_rehearsal,
)
from app.services.account_deletion_preview_rehearsal import (
    run_account_deletion_preview_rehearsal,
)
from app.services.research_memory_deletion_rehearsal import (
    run_research_memory_deletion_rehearsal,
)
from app.services.thesis_notice_rehearsal import run_thesis_notice_rehearsal


router = APIRouter(prefix="/admin/research-memory", tags=["admin"])


@router.post("/thesis-notice-rehearsal")
async def thesis_notice_rehearsal(http_request: Request) -> dict:
    """Exercise the positive path entirely in an ephemeral in-memory database."""
    require_admin(http_request)
    try:
        return await run_thesis_notice_rehearsal()
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Thesis notice rehearsal unavailable: {type(exc).__name__}",
        ) from exc


@router.post("/deletion-rehearsal")
async def research_memory_deletion_rehearsal(http_request: Request) -> dict:
    """Prove research-memory deletion only in an ephemeral in-memory database."""
    require_admin(http_request)
    try:
        return await run_research_memory_deletion_rehearsal()
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=(
                "Research memory deletion rehearsal unavailable: "
                f"{type(exc).__name__}"
            ),
        ) from exc


@router.post("/account-deletion-preview-rehearsal")
async def account_deletion_preview_rehearsal(http_request: Request) -> dict:
    """Exercise aggregate deletion inventory in an ephemeral in-memory database."""
    require_admin(http_request)
    try:
        return await run_account_deletion_preview_rehearsal()
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=(
                "Account deletion preview rehearsal unavailable: "
                f"{type(exc).__name__}"
            ),
        ) from exc


@router.post("/account-deletion-policy-rehearsal")
async def account_deletion_policy_rehearsal(http_request: Request) -> dict:
    """Prove unresolved retention policy fails closed without live data access."""
    require_admin(http_request)
    try:
        return await run_account_deletion_policy_rehearsal()
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=(
                "Account deletion policy rehearsal unavailable: "
                f"{type(exc).__name__}"
            ),
        ) from exc
