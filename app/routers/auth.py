"""
Auth routes — Phase 16 · Slice 4.

Three lightweight endpoints that expose identity state to clients.  They
work in bypass mode (AUTH_ENABLED=false) and are ready for enforcement mode
(AUTH_ENABLED=true) without code changes.

Endpoints
---------
    GET  /auth/me       — full identity context for the current request
    GET  /auth/session  — minimal session state (is_authenticated, auth_enabled)
    POST /auth/logout   — client-side logout acknowledgement

Design
------
* No route protection in Slice 4 (that is Slice 5).
* Every endpoint completes successfully in bypass mode.
* DB lookups are best-effort: if get_session() returns None (DATABASE_URL not
  set) the response still returns the identity known from request.state.
* No credential is ever logged.  auth_subject is logged at DEBUG only.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------

class MeResponse(BaseModel):
    user_id: Optional[str]
    auth_subject: Optional[str]
    is_authenticated: bool
    bypass_mode: bool
    email: Optional[str]
    account_type: Optional[str]
    display_name: Optional[str]


class SessionResponse(BaseModel):
    session_active: bool
    user_id: Optional[str]
    is_authenticated: bool
    auth_enabled: bool
    bypass_mode: bool


class LogoutResponse(BaseModel):
    status: str
    message: str


class ImportPreviewResponse(BaseModel):
    user_id: str
    already_imported: bool
    watchlist_count: int
    portfolio_count: int
    position_count: int
    delivery_pref_count: int
    estimated_actions: Dict[str, int]


class ImportResponse(BaseModel):
    user_id: str
    already_imported: bool
    watchlist_copied: int
    portfolio_copied: int
    position_copied: int
    delivery_pref_copied: int
    skipped: int
    audit_run_id: Optional[str]


class OnboardingResponse(BaseModel):
    user_id: str
    step: str
    step_index: int
    is_complete: bool
    next_step: Optional[str]
    completed_at: Optional[datetime]


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get(
    "/me",
    response_model=MeResponse,
    summary="Current user identity",
    description=(
        "Returns the acting user's identity as resolved by AuthMiddleware. "
        "In bypass mode (AUTH_ENABLED=false) always returns the system user. "
        "When AUTH_ENABLED=true and a valid JWT is present, returns the "
        "authenticated user (provisioning the local row on first login)."
    ),
)
async def get_me(request: Request) -> MeResponse:
    """Return the identity context for this request."""
    try:
        from app.db.connection import get_session
        from app.services.supabase_auth_service import get_identity_context

        async with get_session() as session:
            ctx = await get_identity_context(session, request)
    except Exception as exc:
        logger.warning("[auth/me] DB lookup failed (non-fatal): %r", exc)
        # Fall back to request.state only
        from app.services.supabase_auth_service import IdentityContext
        try:
            from app.config import settings as _s
            bypass_mode = not _s.auth_enabled
        except Exception:
            bypass_mode = True
        ctx = IdentityContext(
            user_id=getattr(request.state, "user_id", None),
            auth_subject=getattr(request.state, "auth_subject", None),
            is_authenticated=bool(getattr(request.state, "is_authenticated", False)),
            bypass_mode=bypass_mode,
        )

    return MeResponse(
        user_id=ctx.user_id,
        auth_subject=ctx.auth_subject,
        is_authenticated=ctx.is_authenticated,
        bypass_mode=ctx.bypass_mode,
        email=ctx.email,
        account_type=ctx.account_type,
        display_name=ctx.display_name,
    )


@router.get(
    "/session",
    response_model=SessionResponse,
    summary="Session state",
    description=(
        "Lightweight check: is there an active authenticated session? "
        "Does not perform any DB lookup. Safe to poll frequently."
    ),
)
async def get_session_info(request: Request) -> SessionResponse:
    """Return minimal session state from request.state + config."""
    try:
        from app.config import settings as _s
        auth_enabled = _s.auth_enabled
        bypass_mode = not auth_enabled
    except Exception:
        auth_enabled = False
        bypass_mode = True

    user_id: Optional[str] = getattr(request.state, "user_id", None)
    is_authenticated: bool = bool(getattr(request.state, "is_authenticated", False))

    return SessionResponse(
        session_active=user_id is not None,
        user_id=user_id,
        is_authenticated=is_authenticated,
        auth_enabled=auth_enabled,
        bypass_mode=bypass_mode,
    )


@router.post(
    "/logout",
    response_model=LogoutResponse,
    summary="Logout",
    description=(
        "Client-initiated session termination.  The actual token is invalidated "
        "client-side via the Supabase JS SDK (supabase.auth.signOut()). "
        "This endpoint provides a server-side acknowledgement and writes an "
        "audit log entry when a DB session is available."
    ),
)
async def logout(request: Request) -> LogoutResponse:
    """Acknowledge logout.  Audit-log the event when a session is available."""
    user_id: Optional[str] = getattr(request.state, "user_id", None)
    auth_subject: Optional[str] = getattr(request.state, "auth_subject", None)

    # Best-effort audit log — silent on failure
    try:
        from app.db.connection import get_session
        from app.db.models import AuditLog
        import uuid

        async with get_session() as session:
            if session is not None and user_id:
                entry = AuditLog(
                    id=str(uuid.uuid4()),
                    user_id=user_id,
                    resource="auth",
                    resource_id=auth_subject,
                    action="logout",
                    ip_address=_get_client_ip(request),
                )
                session.add(entry)
                await session.commit()
    except Exception as exc:
        logger.debug("[auth/logout] audit log failed (non-fatal): %r", exc)

    return LogoutResponse(status="ok", message="session cleared")


@router.get(
    "/import/preview",
    response_model=ImportPreviewResponse,
    summary="Preview existing-data import",
)
async def preview_existing_data(request: Request) -> ImportPreviewResponse:
    """Preview the system-owned starter data available to the signed-in user."""
    user_id = _require_authenticated_user(request)
    from app.db.connection import get_session
    from app.services.account_import_service import preview_import

    async with get_session() as session:
        if session is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Database unavailable",
            )
        result = await preview_import(session, user_id)

    return ImportPreviewResponse(**result.__dict__)


@router.post(
    "/import",
    response_model=ImportResponse,
    summary="Import existing data",
)
async def import_existing_data(request: Request) -> ImportResponse:
    """Idempotently copy existing starter data into the signed-in account."""
    user_id = _require_authenticated_user(request)
    from app.db.connection import get_session
    from app.services.account_import_service import execute_import

    async with get_session() as session:
        if session is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Database unavailable",
            )
        result = await execute_import(session, user_id)

    return ImportResponse(**result.__dict__)


@router.get(
    "/onboarding",
    response_model=OnboardingResponse,
    summary="Get onboarding state",
)
async def get_onboarding(request: Request) -> OnboardingResponse:
    """Return the signed-in user's current onboarding state."""
    user_id = _require_authenticated_user(request)
    from app.db.connection import get_session
    from app.services.onboarding_service import get_onboarding_state

    async with get_session() as session:
        if session is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Database unavailable",
            )
        result = await get_onboarding_state(session, user_id)

    return OnboardingResponse(**result.__dict__)


@router.post(
    "/onboarding/complete",
    response_model=OnboardingResponse,
    summary="Complete onboarding",
)
async def complete_onboarding(request: Request) -> OnboardingResponse:
    """Idempotently mark onboarding complete for the signed-in user."""
    user_id = _require_authenticated_user(request)
    from app.db.connection import get_session
    from app.services.onboarding_service import complete_step

    async with get_session() as session:
        if session is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Database unavailable",
            )
        result = await complete_step(session, user_id)
        await session.commit()

    return OnboardingResponse(**result.__dict__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _require_authenticated_user(request: Request) -> str:
    """Require a verified JWT-backed local identity (never the bypass user)."""
    if not bool(getattr(request.state, "is_authenticated", False)):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    from app.dependencies.auth import require_user_id
    return require_user_id(request)

def _get_client_ip(request: Request) -> Optional[str]:
    """Best-effort client IP extraction from X-Forwarded-For or direct connection."""
    xff = request.headers.get("x-forwarded-for", "")
    if xff:
        return xff.split(",")[0].strip()[:45]
    try:
        if request.client:
            return request.client.host[:45]
    except Exception:
        pass
    return None
