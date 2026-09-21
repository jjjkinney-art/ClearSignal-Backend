"""
Supabase Auth integration service — Phase 16 · Slice 4.

Bridges the Supabase JWT identity (auth_subject / JWT 'sub' claim) to a row
in the local ``users`` table.  Provisions user + profile + settings on first
login.  All subsequent logins are a single SELECT by auth_subject.

Key invariants
--------------
- No password handling anywhere.  Supabase Auth is the sole credential custodian.
- auth_subject (JWT 'sub') is the canonical Supabase identity handle, and the
  ONLY permanent identity key. Section 0.15 removed every other binding path.
- Email is case-folded before write. It is a display/contact label: it never
  locates, merges, rebinds or authorises a local user.
- Identity conflict (an address already held by another local row) FAILS
  CLOSED. Nothing is rebound and no user is provisioned.
- An existing auth_subject is never overwritten.
- user_metadata is user-writable and is never consulted for email, admission
  or identity binding.
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

    # Section 0.15: the user_metadata fallback is GONE. user_metadata is
    # writable by the account holder, so honouring user_metadata.email let a
    # caller nominate somebody else's address. Only the top-level claim, which
    # GoTrue populates from auth.users.email, is read.
    raw_email = payload.get("email")
    email = raw_email.strip().lower() if isinstance(raw_email, str) else ""
    email_verified = bool(
        payload.get("email_verified")
        or payload.get("email_confirmed_at")
    )

    from app.db.repositories.account_repo import (
        get_user_by_auth_subject,
        get_user_by_email,
    )
    from app.services import access_grant_service as grants

    ref = grants.subject_ref(auth_subject)

    # ------------------------------------------------------------------
    # Admission runs for EVERY identity, established or new.
    #
    # An earlier revision returned an already-bound user here, before any
    # grant was consulted. That made revocation meaningless under enforcement:
    # the one account you most want to be able to cut off — an existing one —
    # was the one the gate never looked at. The lookup by subject still
    # happens below, but it no longer short-circuits the decision, and it no
    # longer writes (touch_last_sign_in) before the decision is made.
    # ------------------------------------------------------------------
    identity = grants.trusted_identity(payload)
    if identity is None or identity.is_anonymous or not identity.email:
        # Unconditional, mode-independent: an identity with no
        # provider-supplied address, or an anonymous one, is never
        # provisioned. There is nothing to bind it to that we can trust.
        await grants.audit_admission(
            session, action=grants.ACTION_DENY, ref=ref,
            detail=grants.DENY_ANONYMOUS if (identity and identity.is_anonymous)
            else grants.DENY_NO_TRUSTED_EMAIL,
        )
        logger.info("[supabase_auth] admission denied subject_ref=%s", ref)
        return None

    # Established identity? Looked up now, acted on only after the gate.
    user = await get_user_by_auth_subject(session, auth_subject)

    # Admission gate. "off" leaves admission as it was; "shadow" evaluates
    # every identity and audits without denying; "enforce" requires an active
    # grant bound to THIS subject, for established accounts as well as new ones.
    from app.config import AdmissionConfigError
    try:
        from app.config import settings
        mode = settings.beta_admission_mode_normalized
    except AdmissionConfigError:
        # An unreadable policy is not an open door. Deny, and say nothing
        # about the configured value.
        await grants.audit_admission(
            session, action=grants.ACTION_DENY, ref=ref, detail=grants.DENY_CONFIG,
        )
        logger.warning(
            "[supabase_auth] admission configuration invalid; denying subject_ref=%s", ref,
        )
        return None

    # Narrow, explicit exemption: the system sentinel only. It is the
    # single-tenant/bypass identity the product itself runs as, never a
    # human account, and it holds no grant. Nothing else is exempt — an
    # administrator is an ordinary human identity to this gate.
    is_system_identity = auth_subject == SYSTEM_DEFAULT_USER_ID

    if mode in ("shadow", "enforce") and not is_system_identity:
        decision = await grants.evaluate_admission(
            session, payload, user_exists=user is not None,
        )
        if not decision.allowed:
            await grants.audit_admission(
                session, action=grants.ACTION_DENY, ref=ref, detail=decision.reason,
            )
            logger.info(
                "[supabase_auth] admission denied subject_ref=%s mode=%s", ref, mode,
            )
            if mode == "enforce":
                # Deny before any write: no provisioning, no rebinding, no
                # import, not even a last-sign-in timestamp.
                return None

    if user is not None:
        await touch_last_sign_in(session, user.id)
        return user

    # Identity conflict — a different local row already owns this address.
    #
    # This is where the old email-collision REBIND used to happen. Binding a
    # new subject onto an existing row let anyone who could obtain a token
    # carrying that address take the row over, inheriting whatever it had,
    # including administrator status. It now FAILS CLOSED: the existing row
    # keeps its own auth_subject, nothing is overwritten, and no user is
    # provisioned. Email is a label here, never an identity key.
    colliding = await get_user_by_email(session, identity.email)
    if colliding is not None:
        await grants.audit_admission(
            session, action=grants.ACTION_DENY, ref=ref, detail=grants.DENY_CONFLICT,
        )
        logger.info("[supabase_auth] identity conflict subject_ref=%s", ref)
        return None

    # First login — provision a new user with profile + settings
    user = await provision_new_user(
        session,
        auth_subject=auth_subject,
        email=identity.email,
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

    # Guard: the local id is taken by a row bound to a DIFFERENT subject.
    # Reusing it would silently move an established account onto this token.
    from app.db.repositories.account_repo import get_user as _get_user
    occupant = await _get_user(session, auth_subject)
    if occupant is not None and getattr(occupant, "auth_subject", None) != auth_subject:
        from app.services.access_grant_service import subject_ref as _subject_ref
        logger.info(
            "[supabase_auth] local id conflict, refusing to provision subject_ref=%s",
            _subject_ref(auth_subject),
        )
        return None

    # Create user. A unique-constraint race (two concurrent first logins)
    # surfaces here as an IntegrityError: deny rather than half-provision.
    try:
        user = await create_user(
            session,
            user_id=auth_subject,
            email=email,
            account_type="individual",
            email_verified=email_verified,
            auth_subject=auth_subject,
        )
    except Exception as exc:
        from app.services.access_grant_service import subject_ref as _subject_ref
        logger.info(
            "[supabase_auth] provisioning failed closed subject_ref=%s error=%s",
            _subject_ref(auth_subject), type(exc).__name__,
        )
        return None
    if user is None:
        return None

    # Section 0.15: no email, no user id. An opaque, one-way subject reference
    # still correlates this event with the matching audit row.
    from app.services.access_grant_service import subject_ref as _subject_ref
    logger.info(
        "[supabase_auth] provisioned new user subject_ref=%s",
        _subject_ref(auth_subject),
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
            claims = getattr(request.state, "auth_claims", None)
            if not isinstance(claims, dict):
                logger.warning(
                    "[supabase_auth] cannot provision %s without verified claims",
                    auth_subject,
                )
                return ctx
            user = await resolve_user_from_jwt(session, claims)
            if user is None:
                return ctx
            await session.commit()

        ctx.user_id = user.id
        request.state.user_id = user.id
        ctx.email = user.email
        ctx.account_type = user.account_type

        profile = await get_profile(session, user.id)
        if profile is not None:
            ctx.display_name = profile.display_name

    except Exception as exc:
        logger.warning("[supabase_auth] get_identity_context DB lookup failed: %r", exc)

    return ctx
