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
