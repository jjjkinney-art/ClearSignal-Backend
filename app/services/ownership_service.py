"""
Ownership resolution helpers — Phase 16 · Slice 5.

Provides a single, consistent way to determine "which user owns this request"
across all service and route layers.

The central invariant:
  When AUTH_ENABLED=false (bypass, the default throughout Phase 16 build slices),
  every function returns SYSTEM_DEFAULT_USER_ID.  No behaviour changes; the
  system user is the implicit owner of all pre-auth content.

When AUTH_ENABLED=true:
  Functions resolve from request.state.user_id (stamped by AuthMiddleware).
  An unauthenticated request (no valid JWT) returns user_id=None; callers that
  require an owner must handle that case explicitly (401 via require_auth dep,
  Slice 6).

Isolation guarantee:
  is_owner() and assert_can_access() enforce that a row whose user_id field
  differs from the acting user_id is never silently returned.  In bypass mode
  the check is always skipped — global ownership is intentional.

Null-session / no-request safety:
  All functions handle missing request.state gracefully — they fall back to
  SYSTEM_DEFAULT_USER_ID rather than raising.
"""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)

SYSTEM_DEFAULT_USER_ID: str = "00000000-0000-0000-0000-000000000001"


def _auth_enabled() -> bool:
    """Return True when JWT enforcement is active."""
    try:
        from app.config import settings as _s
        return bool(_s.auth_enabled)
    except Exception:
        return False


def current_owner_id(request) -> Optional[str]:
    """Resolve the acting user's local ID from the request.

    Bypass mode (AUTH_ENABLED=false):
        Returns SYSTEM_DEFAULT_USER_ID always.

    Enforcement mode (AUTH_ENABLED=true):
        Returns request.state.user_id — may be None when the request carries
        no valid JWT.  Callers that require authentication must check this.

    Falls back to SYSTEM_DEFAULT_USER_ID when request.state is absent (e.g.
    in loop/background contexts where no HTTP request exists).
    """
    if not _auth_enabled():
        return SYSTEM_DEFAULT_USER_ID

    try:
        return request.state.user_id  # type: ignore[no-any-return]
    except AttributeError:
        logger.debug("[ownership] request.state.user_id absent — using system user")
        return SYSTEM_DEFAULT_USER_ID


def resolve_effective_user_id(request) -> str:
    """Always return a non-None user_id for ownership queries.

    Returns current_owner_id(request), falling back to SYSTEM_DEFAULT_USER_ID
    when the auth mode returns None (unauthenticated request).

    Use this for repo calls that require a non-null user_id filter.  When the
    return value is SYSTEM_DEFAULT_USER_ID the caller will see the system-owned
    rows (correct in bypass mode and for unauthenticated requests that reach a
    pre-auth endpoint).
    """
    uid = current_owner_id(request)
    return uid if uid is not None else SYSTEM_DEFAULT_USER_ID


def is_owner(request, row_user_id: Optional[str]) -> bool:
    """Return True if the acting user owns the row identified by row_user_id.

    In bypass mode: always True (global ownership; no per-user isolation).
    In enforcement mode: compares the resolved user_id to the row's user_id.
      Null row_user_id is treated as system-owned — only the system user
      matches it (legacy NULL rows have been claimed by Slice 2).
    """
    if not _auth_enabled():
        return True  # bypass: all access allowed

    effective = current_owner_id(request)
    if effective is None:
        return False  # unauthenticated request owns nothing

    if row_user_id is None:
        return effective == SYSTEM_DEFAULT_USER_ID
    return effective == row_user_id


def assert_can_access(request, row_user_id: Optional[str]) -> None:
    """Raise PermissionError if the acting user cannot access this row.

    In bypass mode: no-op (always succeeds).
    In enforcement mode: raises PermissionError when is_owner() is False.

    Use this at the read boundary when returning a single row by ID.
    Raise → route handler should convert to 403 Forbidden.
    """
    if not _auth_enabled():
        return

    if not is_owner(request, row_user_id):
        effective = current_owner_id(request)
        logger.warning(
            "[ownership] access denied: acting_user=%s row_user=%s",
            effective,
            row_user_id,
        )
        raise PermissionError("access denied: row owned by a different user")


def system_user_id() -> str:
    """Return the canonical system user UUID (constant helper)."""
    return SYSTEM_DEFAULT_USER_ID
