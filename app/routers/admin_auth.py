"""
Admin auth observability router — Phase 16 · Slice 8.

GET /admin/auth-status — returns the auth shadow readiness snapshot.

No credentials or secrets are exposed.  The endpoint is read-only and
works in bypass mode (AUTH_ENABLED=false).  No authentication is required
to call it (it is an internal/admin endpoint by convention, not enforcement).
Route protection is deferred to Slice 9.
"""

from __future__ import annotations

import logging
from typing import Any, Dict

from fastapi import APIRouter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get(
    "/auth-status",
    summary="Auth shadow readiness snapshot",
    response_model=Dict[str, Any],
)
async def get_auth_status() -> Dict[str, Any]:
    """Return a point-in-time snapshot of auth/identity configuration and DB state.

    Safe to call at any time.  Always returns a valid JSON response even when
    the database is unavailable (db_available=false, counts default to 0).

    No secret values are included in the response — only boolean presence flags.
    """
    try:
        from app.db.connection import get_session
        from app.services.auth_observability_service import (
            build_auth_snapshot,
            snapshot_to_dict,
        )

        async with get_session() as session:
            snap = await build_auth_snapshot(session)
        return snapshot_to_dict(snap)

    except Exception as exc:
        logger.error("[admin/auth-status] snapshot build failed: %r", exc)
        # Degrade: return a minimal error-state response rather than 500.
        from app.services.auth_observability_service import (
            build_auth_snapshot,
            snapshot_to_dict,
        )
        snap = await build_auth_snapshot(None)
        result = snapshot_to_dict(snap)
        result["error"] = f"DB unavailable: {type(exc).__name__}"
        return result
