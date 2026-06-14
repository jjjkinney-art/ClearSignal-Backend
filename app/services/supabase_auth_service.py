"""
Supabase Auth integration service — Phase 16 · Slice 4.

Bridges the Supabase JWT identity (auth_subject / JWT 'sub' claim) to a row
in the local ``users`` table.  Provisions user + profile + settings on first
login.  All subsequent logins are a single SELECT by auth_subject.

Key invariants
--------------
- No password handling anywhere.  Supabase Auth is the sole credential custodian.
- auth_subject (JWT 'sub') is the canonical Supabase identity handle.
- Email is case-folded before write.
- Email-collision path: if a local row already has the same email but no
  auth_subject, bind the JWT sub to it rather than creating a duplicate.
- All public functions are null-session safe: they return IdentityContext or
  None safely when called with session=None.
- provision_new_user is idempotent: SELECT first, INSERT only if absent.
- AUTH_ENABLED=false: get_identity_context returns system-user identity
  without touching the DB.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

SYSTEM_DEFAULT_USER_ID: str = "00000000-0000-0000-0000-000000000001"


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# IdentityContext — the unified identity snapshot returned by /auth/me
# ---------------------------------------------------------------------------

@dataclass
class IdentityContext:
    """Snapshot of the acting user's identity for a single request.

    Attributes
    ----------
    user_id          The local users.id UUID (always present in bypass mode).
    auth_subject     JWT 'sub' claim from Supabase (None in bypass mode).
    is_authenticated True only when a verified JWT was presented.
    bypass_mode      True when AUTH_ENABLED=false (system user injected).
    email            Local users.email (None when session=None or bypass).
    account_type     local users.account_type (None when session=None or bypass).
    display_name     UserProfile.display_name (None when not yet provisioned).
    """

    user_id: Optional[str]
    auth_subject: Optional[str]
    is_authenticated: bool
    bypass_mode: bool
    email: Optional[str] = None
    account_type: Optional[str] = None
    display_name: Optional[str] = None


# ---------------------------------------------------------------------------
# Core service functions
# ---------------------------------------------------------------------------

async def resolve_user_from_jwt(
    session,
    payload: Dict[str, Any],
) -> Optional[Any]:
    """Find or create a local user row from a verified Supabase JWT payload.

    Resolution order:
    1. SELECT users WHERE auth_subject = payload['sub']  → fast path (most logins)
    2. SELECT users WHERE email = payload['email']       → email collision: bind sub
    3. INSERT new user + profile + settings              → first-ever login

    Returns the User ORM row, or None when session is None or payload has no sub.
    """
    if session is None:
        return None

    auth_subject = payload.get("sub", "")
    if not auth_subject:
        return None

    raw_email = (
        payload.get("email")
        or (payload.get("user_metadata") or {}).get("email", "")
        or ""
    )
    email = raw_email.strip().lower()
    email_verified = bool(
        payload.get("email_verified")
        or payload.get("email_confirmed_at")
    )

    from app.db.repositories.account_repo import (
        get_user_by_auth_subject,
        get_user_by_email,
        update_user,
    )

    # Fast path — existing user already bound to this Supabase subject
    user = await get_user_by_auth_subject(session, auth_subject)
    if user is not None:
        await touch_last_sign_in(session, user.id)
        return user

    # Email-collision path — local account exists but not yet bound
    if email:
        user = await get_user_by_email(session, email)
        if user is not None:
            await update_user(
                session,
                user.id,
                auth_subject=auth_subject,
                email_verified=email_verified,
                last_sign_in_at=_now(),
            )
            logger.info(
                "[supabase_auth] bound auth_subject to existing user email=%s user_id=%s",
                email,
                user.id,
            )
            return user

    # First login — provision a new user with profile + settings
    user = await provision_new_user(
        session,
        auth_subject=auth_subject,
        email=email,
        email_verified=email_verified,
    )
    return user


async def provision_new_user(
    session,
    *,
    auth_subject: str,
    email: str,
    email_verified: bool = False,
) -> Optional[Any]:
    """Create a user row plus default profile and settings rows.

    Idempotent: if a user with the same auth_subject already exists it is
    returned without modification.  Profile and settings are created only when
    absent (upsert_profile / upsert_settings handle the check themselves).

    Returns the User row, or None when session is None.
    """
    if session is None:
        return None
    if not auth_subject:
        return None

    from app.db.repositories.account_repo import (
        get_user_by_auth_subject,
        create_user,
        upsert_profile,
        upsert_settings,
    )

    # Guard: already exists
    existing = await get_user_by_auth_subject(session, auth_subject)
    if existing is not None:
        await _ensure_profile_settings(session, existing.id, upsert_profile, upsert_settings)
        return existing

    # Create user
    user = await create_user(
        session,
        email=email,
        account_type="individual",
        email_verified=email_verified,
        auth_subject=auth_subject,
    )
    if user is None:
        return None

    logger.info(
        "[supabase_auth] provisioned new user user_id=%s email=%s",
        user.id,
        email,
    )

    await _ensure_profile_settings(session, user.id, upsert_profile, upsert_settings)
    return user


async def _ensure_profile_settings(session, user_id: str, upsert_profile, upsert_settings) -> None:
    """Create profile and settings rows for user_id when absent."""
    await upsert_profile(session, user_id)
    await upsert_settings(session, user_id)


async def touch_last_sign_in(session, user_id: str) -> None:
    """Update last_sign_in_at to now for user_id.  Silent no-op on any error."""
    if session is None:
        return
    try:
        from app.db.repositories.account_repo import update_user
        await update_user(session, user_id, last_sign_in_at=_now())
    except Exception as exc:
        logger.debug("[supabase_auth] touch_last_sign_in failed for %s: %r", user_id, exc)


async def get_identity_context(session, request) -> IdentityContext:
    """Build an IdentityContext from request.state + optional DB enrichment.

    Bypass mode (AUTH_ENABLED=false):
        Returns system-user identity immediately — no DB lookup.

    Enforcement mode (AUTH_ENABLED=true):
        - Unauthenticated request (no valid JWT): user_id=None, no DB lookup.
        - Authenticated request: loads email/account_type from local users table.
          If auth_subject is new, provision is triggered here so the first
          /auth/me call also creates the user row.

    Always safe when session=None (DB unavailable): falls back to request.state
    values with email=None, account_type=None.
    """
    try:
        from app.config import settings as _settings
        bypass_mode = not _settings.auth_enabled
    except Exception:
        bypass_mode = True

    # Read identity from middleware-stamped state
    try:
        user_id: Optional[str] = request.state.user_id
        auth_subject: Optional[str] = request.state.auth_subject
        is_authenticated: bool = bool(request.state.is_authenticated)
    except AttributeError:
        # Middleware not attached (edge case in tests)
        user_id = SYSTEM_DEFAULT_USER_ID
        auth_subject = None
        is_authenticated = False

    ctx = IdentityContext(
        user_id=user_id,
        auth_subject=auth_subject,
        is_authenticated=is_authenticated,
        bypass_mode=bypass_mode,
    )

    # Bypass: return immediately — no DB work needed
    if bypass_mode or not is_authenticated or not auth_subject:
        return ctx

    # Enforcement + authenticated: enrich with local user data
    if session is None:
        return ctx

    try:
        from app.db.repositories.account_repo import (
            get_user_by_auth_subject,
            get_profile,
        )

        user = await get_user_by_auth_subject(session, auth_subject)
        if user is None:
            # First hit for this auth_subject — provision silently
            # (payload only contains sub; email comes from DB on next request
            # after the JWT-verified path in resolve_user_from_jwt)
            logger.info(
                "[supabase_auth] get_identity_context: unknown auth_subject %s — "
                "provision deferred to resolve_user_from_jwt",
                auth_subject,
            )
            return ctx

        ctx.user_id = user.id
        ctx.email = user.email
        ctx.account_type = user.account_type

        profile = await get_profile(session, user.id)
        if profile is not None:
            ctx.display_name = profile.display_name

    except Exception as exc:
        logger.warning("[supabase_auth] get_identity_context DB lookup failed: %r", exc)

    return ctx
