"""Authenticated operator controls for inert benchmark shadow state."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.db.connection import get_session
from app.security.authz import require_admin
from app.services import benchmark_shadow_state_service as state


router = APIRouter(prefix="/admin/benchmark-shadow", tags=["admin"])


class KillRequest(BaseModel):
    expected_version: int = Field(ge=0)
    reason_code: Literal[
        "operator_stop", "cost_investigation", "integrity_investigation",
        "maintenance", "rollback", "test_rehearsal",
    ]


class RestoreRequest(BaseModel):
    expected_version: int = Field(ge=0)


def _request_metadata(request: Request) -> tuple[str | None, str | None]:
    forwarded = request.headers.get("x-forwarded-for", "").split(",", 1)[0].strip()
    ip_address = forwarded or (request.client.host if request.client else None)
    return ip_address, request.headers.get("user-agent")


@router.get("/status")
async def benchmark_shadow_status(http_request: Request) -> dict:
    require_admin(http_request)
    try:
        async with get_session() as session:
            return await state.build_operator_snapshot(
                session, now=datetime.now(timezone.utc)
            )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Benchmark shadow state unavailable: {type(exc).__name__}",
        ) from exc


@router.post("/kill")
async def benchmark_shadow_kill(body: KillRequest, http_request: Request) -> dict:
    actor_id = require_admin(http_request)
    now = datetime.now(timezone.utc)
    ip_address, user_agent = _request_metadata(http_request)
    async with get_session() as session:
        if session is None:
            raise HTTPException(status_code=503, detail="Benchmark shadow database unavailable.")
        control = await state.control_state(session, actor_id=actor_id, now=now)
        if control.version != body.expected_version:
            raise HTTPException(status_code=409, detail="Control version changed; refresh status.")
        if control.manual_kill:
            return await state.build_operator_snapshot(session, now=now)
        changed = await state.set_kill_state(
            session, expected_version=body.expected_version, manual_kill=True,
            automatic_kill=bool(control.automatic_kill),
            reason_code=body.reason_code, actor_id=actor_id, now=now,
        )
        if not changed:
            raise HTTPException(status_code=409, detail="Control version changed; refresh status.")
        await state.append_operator_audit(
            session, actor_id=actor_id, action="benchmark_shadow_kill",
            occurred_at=now, ip_address=ip_address, user_agent=user_agent,
        )
        return await state.build_operator_snapshot(session, now=now)


@router.post("/restore")
async def benchmark_shadow_restore(body: RestoreRequest, http_request: Request) -> dict:
    """Clear only the manual stop; an automatic safety halt is preserved."""
    actor_id = require_admin(http_request)
    now = datetime.now(timezone.utc)
    ip_address, user_agent = _request_metadata(http_request)
    async with get_session() as session:
        if session is None:
            raise HTTPException(status_code=503, detail="Benchmark shadow database unavailable.")
        control = await state.control_state(session, actor_id=actor_id, now=now)
        if control.version != body.expected_version:
            raise HTTPException(status_code=409, detail="Control version changed; refresh status.")
        if not control.manual_kill:
            return await state.build_operator_snapshot(session, now=now)
        automatic = bool(control.automatic_kill)
        changed = await state.set_kill_state(
            session, expected_version=body.expected_version, manual_kill=False,
            automatic_kill=automatic,
            reason_code=control.reason_code if automatic else None,
            actor_id=actor_id, now=now,
        )
        if not changed:
            raise HTTPException(status_code=409, detail="Control version changed; refresh status.")
        await state.append_operator_audit(
            session, actor_id=actor_id, action="benchmark_shadow_restore",
            occurred_at=now, ip_address=ip_address, user_agent=user_agent,
        )
        return await state.build_operator_snapshot(session, now=now)
