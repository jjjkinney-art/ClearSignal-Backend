"""
User context helpers for FastAPI dependency injection — Phase 16 · Slice 3.

get_current_user_id(request) is the single callable used throughout route
handlers to obtain the acting user's identity.  In bypass mode
(AUTH_ENABLED=false) it always returns SYSTEM_DEFAULT_USER_ID.  When auth
is active it returns request.state.user_id, which may be None if the
request carried no valid JWT.

No DB calls.  No network calls.  Pure request.state read.
"""

from __future__ import annotations

from typing import Optional

from starlette.requests import Request

SYSTEM_DEFAULT_USER_ID: str = "00000000-0000-0000-0000-000000000001"


def get_current_user_id(request: Request) -> Optional[str]:
    """Return the acting user's ID for this request.

    Reads from request.state, which AuthMiddleware stamps before any route
    handler runs.  Falls back to SYSTEM_DEFAULT_USER_ID when state is
    absent (e.g. in tests that bypass the middleware entirely).

    Returns:
        The user_id string (UUID) when AUTH_ENABLED=false (bypass) or when
        a valid JWT is present.  None only when AUTH_ENABLED=true and the
        request carries no valid token.
    """
    try:
        user_id: Optional[str] = request.state.user_id
        return user_id
    except AttributeError:
        # Middleware not attached (unit test or early-in-stack call)
        return SYSTEM_DEFAULT_USER_ID


def require_user_id(request: Request) -> str:
    """Return the acting user's ID, or raise 401 when the request is
    unauthenticated under enforcement mode.

    This is the identity resolver product routes (watchlist, portfolio,
    scenario, notifications) must use so user-scoped data is never served to
    an unauthenticated caller.

    Resolution:
      * AUTH_ENABLED=false (bypass)  — AuthMiddleware stamps
        SYSTEM_DEFAULT_USER_ID, which is returned unchanged (single-tenant
        behaviour preserved).
      * AUTH_ENABLED=true + valid JWT — the JWT `sub` is returned (per-user
        scoping).
      * AUTH_ENABLED=true + no/invalid token — request.state.user_id is None;
        this raises HTTP 401 rather than falling back to the bypass user.
      * No middleware in the stack (request is None or has no state, e.g. a
        direct-call unit test) — SYSTEM_DEFAULT_USER_ID, so local/dev
        testability is preserved.

    The bypass user is therefore used ONLY when auth is disabled or the
    middleware is absent — never as a silent fallback for a failed auth.
    """
    uid = get_current_user_id(request)
    if uid is None:
        # Reached only under AUTH_ENABLED=true with no/invalid JWT.
        from fastapi import HTTPException
        raise HTTPException(status_code=401, detail="Authentication required.")
    return uid


def get_auth_subject(request: Request) -> Optional[str]:
    """Return the JWT sub claim (Supabase auth subject), or None."""
    try:
        return request.state.auth_subject  # type: ignore[no-any-return]
    except AttributeError:
        return None


def is_authenticated(request: Request) -> bool:
    """Return True only if the request carries a verified JWT."""
    try:
        return bool(request.state.is_authenticated)
    except AttributeError:
        return False
