"""
Accounts & Identity repository — Phase 16 · Slice 1.

Covers CRUD for users, user_profiles, and user_settings.
All functions accept an AsyncSession as the first positional argument.
Passing None is safe: every function returns an empty/falsy value instead
of raising.  This mirrors the ``session is None → return safe default``
contract used throughout the loop and portfolio repos.

No password handling anywhere — Supabase Auth is the sole credential custodian.
This repo never reads, writes, or validates a credential.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# System-default user identity — fixed UUID for legacy data ownership.
# Slice 2 seeds this row; here it is only referenced as a constant.
SYSTEM_DEFAULT_USER_ID: str = "00000000-0000-0000-0000-000000000001"
SYSTEM_DEFAULT_EMAIL:   str = "system@clearsignal.internal"


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# § USERS
# ---------------------------------------------------------------------------

async def create_user(
    session,
    *,
    user_id: Optional[str] = None,
    email: str,
    account_type: str = "individual",
    email_verified: bool = False,
    auth_subject: Optional[str] = None,
) -> Optional[object]:
    """Insert a new user row and return it.

    Email is case-folded before insert.  If a row with the same email already
    exists a ValueError is raised (let the caller decide whether to get_user
    instead).  Returns None when session is None.
    """
    if session is None:
        return None

    import uuid as _uuid_mod
    from app.db.models import User

    uid = user_id or str(_uuid_mod.uuid4())
    row = User(
        id=uid,
        email=email.strip().lower(),
        account_type=account_type,
        email_verified=email_verified,
        auth_subject=auth_subject,
    )
    session.add(row)
    await session.flush()
    return row


async def get_user(
    session,
    user_id: str,
) -> Optional[object]:
    """Return the User row by primary key, or None."""
    if session is None:
        return None

    from app.db.models import User
    from sqlalchemy import select

    result = await session.execute(
        select(User).where(User.id == user_id)
    )
    return result.scalar_one_or_none()


async def get_user_by_email(
    session,
    email: str,
) -> Optional[object]:
    """Return the User row whose email matches (case-insensitive), or None."""
    if session is None:
        return None

    from app.db.models import User
    from sqlalchemy import select

    result = await session.execute(
        select(User).where(User.email == email.strip().lower())
    )
    return result.scalar_one_or_none()


async def get_user_by_auth_subject(
    session,
    auth_subject: str,
) -> Optional[object]:
    """Return the User row whose auth_subject matches the Supabase JWT sub, or None."""
    if session is None:
        return None

    from app.db.models import User
    from sqlalchemy import select

    result = await session.execute(
        select(User).where(User.auth_subject == auth_subject)
    )
    return result.scalar_one_or_none()


async def update_user(
    session,
    user_id: str,
    *,
    email: Optional[str] = None,
    email_verified: Optional[bool] = None,
    account_type: Optional[str] = None,
    auth_subject: Optional[str] = None,
    stripe_customer_id: Optional[str] = None,
    last_sign_in_at: Optional[datetime] = None,
) -> Optional[object]:
    """Apply non-None keyword fields to the user row and flush.

    Returns the updated row, or None if the user is not found or session is None.
    """
    if session is None:
        return None

    row = await get_user(session, user_id)
    if row is None:
        return None

    if email is not None:
        row.email = email.strip().lower()
    if email_verified is not None:
        row.email_verified = email_verified
    if account_type is not None:
        row.account_type = account_type
    if auth_subject is not None:
        row.auth_subject = auth_subject
    if stripe_customer_id is not None:
        row.stripe_customer_id = stripe_customer_id
    if last_sign_in_at is not None:
        row.last_sign_in_at = last_sign_in_at

    row.updated_at = _now()
    await session.flush()
    return row


async def deactivate_user(
    session,
    user_id: str,
) -> bool:
    """Set is_active=False on the user row.

    Returns True if the row was found and deactivated, False otherwise.
    """
    if session is None:
        return False

    row = await get_user(session, user_id)
    if row is None:
        return False

    row.is_active = False
    row.updated_at = _now()
    await session.flush()
    return True


async def get_or_create_system_user(session) -> Optional[object]:
    """Return the system user row, creating it if absent.

    The system user has a fixed UUID (SYSTEM_DEFAULT_USER_ID) so this
    operation is idempotent regardless of how many times it is called.
    Returns None when session is None.
    """
    if session is None:
        return None

    row = await get_user(session, SYSTEM_DEFAULT_USER_ID)
    if row is not None:
        return row

    return await create_user(
        session,
        user_id=SYSTEM_DEFAULT_USER_ID,
        email=SYSTEM_DEFAULT_EMAIL,
        account_type="system",
        email_verified=True,
    )


async def list_users(
    session,
    *,
    account_type: Optional[str] = None,
    is_active: Optional[bool] = None,
    limit: int = 100,
) -> List:
    """Return user rows filtered by optional account_type and is_active."""
    if session is None:
        return []

    from app.db.models import User
    from sqlalchemy import select

    stmt = select(User).order_by(User.created_at)
    if account_type is not None:
        stmt = stmt.where(User.account_type == account_type)
    if is_active is not None:
        stmt = stmt.where(User.is_active == is_active)
    stmt = stmt.limit(limit)

    result = await session.execute(stmt)
    return list(result.scalars().all())


# ---------------------------------------------------------------------------
# § USER PROFILES
# ---------------------------------------------------------------------------

async def upsert_profile(
    session,
    user_id: str,
    *,
    display_name: Optional[str] = None,
    timezone: Optional[str] = None,
    locale: Optional[str] = None,
    onboarding_step: Optional[str] = None,
    onboarding_completed_at: Optional[datetime] = None,
) -> Optional[object]:
    """Create or update the UserProfile for user_id.

    On creation all provided fields are set; on update only non-None fields
    are applied.  Returns None when session is None.
    """
    if session is None:
        return None

    from app.db.models import UserProfile
    from sqlalchemy import select

    result = await session.execute(
        select(UserProfile).where(UserProfile.user_id == user_id)
    )
    row = result.scalar_one_or_none()

    if row is None:
        row = UserProfile(
            user_id=user_id,
            display_name=display_name,
            timezone=timezone or "UTC",
            locale=locale or "en",
            onboarding_step=onboarding_step or "pending",
            onboarding_completed_at=onboarding_completed_at,
        )
        session.add(row)
    else:
        if display_name is not None:
            row.display_name = display_name
        if timezone is not None:
            row.timezone = timezone
        if locale is not None:
            row.locale = locale
        if onboarding_step is not None:
            row.onboarding_step = onboarding_step
        if onboarding_completed_at is not None:
            row.onboarding_completed_at = onboarding_completed_at
        row.updated_at = _now()

    await session.flush()
    return row


async def get_profile(
    session,
    user_id: str,
) -> Optional[object]:
    """Return the UserProfile row for user_id, or None."""
    if session is None:
        return None

    from app.db.models import UserProfile
    from sqlalchemy import select

    result = await session.execute(
        select(UserProfile).where(UserProfile.user_id == user_id)
    )
    return result.scalar_one_or_none()


# ---------------------------------------------------------------------------
# § USER SETTINGS
# ---------------------------------------------------------------------------

async def upsert_settings(
    session,
    user_id: str,
    *,
    briefing_time_utc: Optional[int] = None,
    quiet_hours_start: Optional[int] = None,
    quiet_hours_end: Optional[int] = None,
    delivery_channel: Optional[str] = None,
    digest_enabled: Optional[bool] = None,
    theme: Optional[str] = None,
) -> Optional[object]:
    """Create or update the UserSettings for user_id.

    On creation all provided fields are set; on update only non-None fields
    are applied.  Returns None when session is None.
    """
    if session is None:
        return None

    from app.db.models import UserSettings
    from sqlalchemy import select

    result = await session.execute(
        select(UserSettings).where(UserSettings.user_id == user_id)
    )
    row = result.scalar_one_or_none()

    if row is None:
        row = UserSettings(
            user_id=user_id,
            briefing_time_utc=briefing_time_utc if briefing_time_utc is not None else 7,
            quiet_hours_start=quiet_hours_start if quiet_hours_start is not None else 22,
            quiet_hours_end=quiet_hours_end if quiet_hours_end is not None else 7,
            delivery_channel=delivery_channel or "in_app",
            digest_enabled=digest_enabled if digest_enabled is not None else True,
            theme=theme or "system",
        )
        session.add(row)
    else:
        if briefing_time_utc is not None:
            row.briefing_time_utc = briefing_time_utc
        if quiet_hours_start is not None:
            row.quiet_hours_start = quiet_hours_start
        if quiet_hours_end is not None:
            row.quiet_hours_end = quiet_hours_end
        if delivery_channel is not None:
            row.delivery_channel = delivery_channel
        if digest_enabled is not None:
            row.digest_enabled = digest_enabled
        if theme is not None:
            row.theme = theme
        row.updated_at = _now()

    await session.flush()
    return row


async def get_settings(
    session,
    user_id: str,
) -> Optional[object]:
    """Return the UserSettings row for user_id, or None."""
    if session is None:
        return None

    from app.db.models import UserSettings
    from sqlalchemy import select

    result = await session.execute(
        select(UserSettings).where(UserSettings.user_id == user_id)
    )
    return result.scalar_one_or_none()


# ---------------------------------------------------------------------------
# § HELPERS
# ---------------------------------------------------------------------------

async def count_users_by_type(session) -> Dict[str, int]:
    """Return a dict of account_type → count across all users.

    Used by the observability snapshot (Slice 8).  Returns {} when session is None.
    """
    if session is None:
        return {}

    from app.db.models import User
    from sqlalchemy import select, func

    result = await session.execute(
        select(User.account_type, func.count(User.id).label("n"))
        .group_by(User.account_type)
    )
    return {row.account_type: row.n for row in result.all()}
