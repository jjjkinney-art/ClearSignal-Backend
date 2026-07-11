"""Authorization helpers for sensitive/internal endpoints (Sprint 0).

Admin resolution:
  * The system / bypass user (AUTH_ENABLED=false) is treated as admin, so a
    single-tenant operator retains full access without extra config.
  * When AUTH_ENABLED=true, only user IDs listed in ADMIN_USER_IDS are admins.
"""
from __future__ import annotations

from fastapi import HTTPException
from starlette.requests import Request

from ..config import settings
from ..dependencies.auth import require_user_id, SYSTEM_DEFAULT_USER_ID


def is_admin(user_id: str) -> bool:
    if user_id == SYSTEM_DEFAULT_USER_ID:
        return True
    return user_id in settings.admin_user_ids_list


def require_admin(request: Request) -> str:
    """Return the acting user_id if admin; raise 401 (unauth) or 403 (non-admin)."""
    user_id = require_user_id(request)   # 401 when AUTH_ENABLED and no valid token
    if not is_admin(user_id):
        raise HTTPException(status_code=403, detail="Administrator access required.")
    return user_id
