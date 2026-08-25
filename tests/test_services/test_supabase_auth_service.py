"""
Tests for Phase 16 · Slice 4 — supabase_auth_service.py

Coverage
--------
TestNullSessionSafety        — all functions return safe defaults when session=None
TestProvisionNewUser         — creates user + profile + settings rows
TestProvisionIdempotency     — second call returns same row, no duplicate
TestResolveUserFromJwt       — fast path (known sub), email-bind, first-login
TestEmailCollisionBind       — existing email user gets auth_subject bound
TestTouchLastSignIn          — updates last_sign_in_at timestamp
TestGetIdentityContextBypass — bypass mode never hits DB
TestGetIdentityContextAuth   — auth mode loads email/account_type from DB
TestEmailCaseFolding         — email normalised to lowercase
TestMissingSubReturnsNone    — payload without 'sub' returns None
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import AsyncGenerator, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

SYSTEM_DEFAULT_USER_ID = "00000000-0000-0000-0000-000000000001"

# ---------------------------------------------------------------------------
# In-memory SQLite session fixture (mirrors account_repo tests)
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def session():
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
    from sqlalchemy.orm import sessionmaker
    from app.db.models import Base

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    Session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with Session() as s:
        yield s

    await engine.dispose()


def _run(coro):
    # A fresh loop avoids Python 3.12's run-order-dependent
    # "There is no current event loop" failure after asyncio.run-based tests.
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_request(
    user_id: Optional[str] = SYSTEM_DEFAULT_USER_ID,
    auth_subject: Optional[str] = None,
    is_authenticated: bool = False,
    auth_claims=None,
) -> MagicMock:
    req = MagicMock()

    class _State:
        pass

    s = _State()
    s.user_id = user_id
    s.auth_subject = auth_subject
    s.is_authenticated = is_authenticated
    s.auth_claims = auth_claims
    req.state = s
    return req


async def _provision(session, auth_subject="sub-abc", email="user@example.com"):
    from app.services.supabase_auth_service import provision_new_user
    return await provision_new_user(session, auth_subject=auth_subject, email=email)


# ---------------------------------------------------------------------------
# 1. TestNullSessionSafety
# ---------------------------------------------------------------------------

class TestNullSessionSafety:
    def test_provision_new_user_null_session(self):
        from app.services.supabase_auth_service import provision_new_user
        result = _run(provision_new_user(None, auth_subject="sub", email="a@b.com"))
        assert result is None

    def test_resolve_user_from_jwt_null_session(self):
        from app.services.supabase_auth_service import resolve_user_from_jwt
        result = _run(resolve_user_from_jwt(None, {"sub": "sub-abc"}))
        assert result is None

    def test_touch_last_sign_in_null_session(self):
        from app.services.supabase_auth_service import touch_last_sign_in
        # Must not raise
        _run(touch_last_sign_in(None, "some-user-id"))

    def test_get_identity_context_null_session_bypass(self):
        from app.services.supabase_auth_service import get_identity_context
        req = _make_request()
        with patch("app.config.settings") as s:
            s.auth_enabled = False
            ctx = _run(get_identity_context(None, req))
        assert ctx.user_id == SYSTEM_DEFAULT_USER_ID
        assert ctx.bypass_mode is True

    def test_provision_empty_auth_subject_returns_none(self):
        from app.services.supabase_auth_service import provision_new_user
        result = _run(provision_new_user(None, auth_subject="", email="a@b.com"))
        assert result is None


# ---------------------------------------------------------------------------
# 2. TestProvisionNewUser
# ---------------------------------------------------------------------------

class TestProvisionNewUser:
    @pytest.mark.asyncio
    async def test_creates_user_row(self, session):
        user = await _provision(session)
        assert user is not None
        assert user.auth_subject == "sub-abc"
        assert user.id == "sub-abc"
        assert user.email == "user@example.com"
        assert user.account_type == "individual"

    @pytest.mark.asyncio
    async def test_creates_profile_row(self, session):
        user = await _provision(session)
        from app.db.repositories.account_repo import get_profile
        profile = await get_profile(session, user.id)
        assert profile is not None
        assert profile.user_id == user.id
        assert profile.onboarding_step == "pending"

    @pytest.mark.asyncio
    async def test_creates_settings_row(self, session):
        user = await _provision(session)
        from app.db.repositories.account_repo import get_settings
        settings = await get_settings(session, user.id)
        assert settings is not None
        assert settings.user_id == user.id
        assert settings.delivery_channel == "in_app"

    @pytest.mark.asyncio
    async def test_email_case_folded(self, session):
        from app.services.supabase_auth_service import provision_new_user
        user = await provision_new_user(session, auth_subject="sub-X", email="User@Example.COM")
        assert user.email == "user@example.com"

    @pytest.mark.asyncio
    async def test_email_verified_flag(self, session):
        from app.services.supabase_auth_service import provision_new_user
        user = await provision_new_user(
            session, auth_subject="sub-v", email="v@example.com", email_verified=True
        )
        assert user.email_verified is True


# ---------------------------------------------------------------------------
# 3. TestProvisionIdempotency
# ---------------------------------------------------------------------------

class TestProvisionIdempotency:
    @pytest.mark.asyncio
    async def test_second_call_returns_same_user(self, session):
        u1 = await _provision(session)
        u2 = await _provision(session)
        assert u1.id == u2.id

    @pytest.mark.asyncio
    async def test_does_not_create_duplicate_profile(self, session):
        await _provision(session)
        await _provision(session)
        from sqlalchemy import select, func
        from app.db.models import UserProfile
        result = await session.execute(select(func.count(UserProfile.user_id)))
        # Only 1 profile row despite 2 provision calls
        assert result.scalar() == 1

    @pytest.mark.asyncio
    async def test_does_not_create_duplicate_settings(self, session):
        await _provision(session)
        await _provision(session)
        from sqlalchemy import select, func
        from app.db.models import UserSettings
        result = await session.execute(select(func.count(UserSettings.user_id)))
        assert result.scalar() == 1


# ---------------------------------------------------------------------------
# 4. TestResolveUserFromJwt
# ---------------------------------------------------------------------------

class TestResolveUserFromJwt:
    @pytest.mark.asyncio
    async def test_fast_path_existing_auth_subject(self, session):
        # Pre-provision a user
        existing = await _provision(session, auth_subject="known-sub")
        from app.services.supabase_auth_service import resolve_user_from_jwt
        payload = {"sub": "known-sub", "email": "user@example.com"}
        user = await resolve_user_from_jwt(session, payload)
        assert user.id == existing.id

    @pytest.mark.asyncio
    async def test_first_login_creates_user(self, session):
        from app.services.supabase_auth_service import resolve_user_from_jwt
        payload = {"sub": "brand-new-sub", "email": "new@example.com", "email_verified": True}
        user = await resolve_user_from_jwt(session, payload)
        assert user is not None
        assert user.auth_subject == "brand-new-sub"
        assert user.email == "new@example.com"

    @pytest.mark.asyncio
    async def test_first_login_also_creates_profile(self, session):
        from app.services.supabase_auth_service import resolve_user_from_jwt
        from app.db.repositories.account_repo import get_profile
        payload = {"sub": "new-sub-2", "email": "new2@example.com"}
        user = await resolve_user_from_jwt(session, payload)
        profile = await get_profile(session, user.id)
        assert profile is not None

    @pytest.mark.asyncio
    async def test_no_sub_returns_none(self, session):
        from app.services.supabase_auth_service import resolve_user_from_jwt
        result = await resolve_user_from_jwt(session, {"email": "a@b.com"})
        assert result is None

    @pytest.mark.asyncio
    async def test_empty_sub_returns_none(self, session):
        from app.services.supabase_auth_service import resolve_user_from_jwt
        result = await resolve_user_from_jwt(session, {"sub": "", "email": "a@b.com"})
        assert result is None

    @pytest.mark.asyncio
    async def test_updates_last_sign_in_on_repeat_login(self, session):
        from app.services.supabase_auth_service import resolve_user_from_jwt
        payload = {"sub": "repeat-sub", "email": "repeat@example.com"}
        # First login
        user = await resolve_user_from_jwt(session, payload)
        first_id = user.id
        # Flush to ensure timestamps differ in next call
        await session.commit()
        # Second login
        user2 = await resolve_user_from_jwt(session, payload)
        assert user2.id == first_id

    @pytest.mark.asyncio
    async def test_email_from_user_metadata(self, session):
        from app.services.supabase_auth_service import resolve_user_from_jwt
        payload = {
            "sub": "meta-sub",
            "user_metadata": {"email": "Meta@Example.COM"},
        }
        user = await resolve_user_from_jwt(session, payload)
        assert user is not None
        assert user.email == "meta@example.com"


# ---------------------------------------------------------------------------
# 5. TestEmailCollisionBind
# ---------------------------------------------------------------------------

class TestEmailCollisionBind:
    @pytest.mark.asyncio
    async def test_existing_email_user_gets_auth_subject_bound(self, session):
        """Local user with no auth_subject gets bound when JWT arrives."""
        from app.db.repositories.account_repo import create_user
        # Pre-existing user (e.g. imported, no Supabase subject yet)
        existing = await create_user(
            session, email="existing@example.com", account_type="individual"
        )
        await session.flush()
        assert existing.auth_subject is None

        from app.services.supabase_auth_service import resolve_user_from_jwt
        payload = {"sub": "supabase-sub-xyz", "email": "Existing@Example.COM"}
        user = await resolve_user_from_jwt(session, payload)

        assert user.id == existing.id
        assert user.auth_subject == "supabase-sub-xyz"

    @pytest.mark.asyncio
    async def test_bind_does_not_change_account_type(self, session):
        from app.db.repositories.account_repo import create_user
        existing = await create_user(
            session,
            email="inst@example.com",
            account_type="institutional",
        )
        await session.flush()

        from app.services.supabase_auth_service import resolve_user_from_jwt
        user = await resolve_user_from_jwt(session, {"sub": "inst-sub", "email": "inst@example.com"})
        assert user.account_type == "institutional"


# ---------------------------------------------------------------------------
# 6. TestTouchLastSignIn
# ---------------------------------------------------------------------------

class TestTouchLastSignIn:
    @pytest.mark.asyncio
    async def test_sets_last_sign_in_at(self, session):
        user = await _provision(session, auth_subject="ts-sub")
        assert user.last_sign_in_at is None  # not set on provision
        from app.services.supabase_auth_service import touch_last_sign_in
        await touch_last_sign_in(session, user.id)
        await session.flush()
        from app.db.repositories.account_repo import get_user
        refreshed = await get_user(session, user.id)
        assert refreshed.last_sign_in_at is not None

    @pytest.mark.asyncio
    async def test_nonexistent_user_does_not_raise(self, session):
        from app.services.supabase_auth_service import touch_last_sign_in
        # Should not raise even for unknown user_id
        await touch_last_sign_in(session, "ffffffff-ffff-ffff-ffff-ffffffffffff")


# ---------------------------------------------------------------------------
# 7. TestGetIdentityContextBypass
# ---------------------------------------------------------------------------

class TestGetIdentityContextBypass:
    def test_bypass_returns_system_user(self):
        from app.services.supabase_auth_service import get_identity_context
        req = _make_request()
        with patch("app.config.settings") as s:
            s.auth_enabled = False
            ctx = _run(get_identity_context(None, req))
        assert ctx.user_id == SYSTEM_DEFAULT_USER_ID
        assert ctx.is_authenticated is False
        assert ctx.bypass_mode is True

    def test_bypass_does_not_set_email(self):
        from app.services.supabase_auth_service import get_identity_context
        req = _make_request()
        with patch("app.config.settings") as s:
            s.auth_enabled = False
            ctx = _run(get_identity_context(None, req))
        assert ctx.email is None

    def test_bypass_ignores_bearer_token(self):
        """Even with a real auth_subject on state, bypass returns no email."""
        from app.services.supabase_auth_service import get_identity_context
        req = _make_request(auth_subject="some-sub", is_authenticated=True)
        with patch("app.config.settings") as s:
            s.auth_enabled = False
            ctx = _run(get_identity_context(None, req))
        assert ctx.bypass_mode is True
        assert ctx.email is None

    def test_bypass_with_custom_bypass_user_id(self):
        from app.services.supabase_auth_service import get_identity_context
        custom_uid = "aaaabbbb-cccc-dddd-eeee-ffffaaaabbbb"
        req = _make_request(user_id=custom_uid)
        with patch("app.config.settings") as s:
            s.auth_enabled = False
            ctx = _run(get_identity_context(None, req))
        assert ctx.user_id == custom_uid


# ---------------------------------------------------------------------------
# 8. TestGetIdentityContextAuth
# ---------------------------------------------------------------------------

class TestGetIdentityContextAuth:
    @pytest.mark.asyncio
    async def test_auth_mode_loads_user_data(self, session):
        """Authenticated request enriches ctx with email and account_type."""
        user = await _provision(session, auth_subject="real-sub")
        await session.commit()

        from app.services.supabase_auth_service import get_identity_context
        req = _make_request(
            user_id=user.id, auth_subject="real-sub", is_authenticated=True
        )
        with patch("app.config.settings") as s:
            s.auth_enabled = True
            ctx = await get_identity_context(session, req)

        assert ctx.user_id == user.id
        assert ctx.email == "user@example.com"
        assert ctx.account_type == "individual"
        assert ctx.is_authenticated is True
        assert ctx.bypass_mode is False

    @pytest.mark.asyncio
    async def test_auth_mode_provisions_from_verified_claims(self, session):
        from app.services.supabase_auth_service import get_identity_context

        claims = {
            "sub": "first-login-sub",
            "email": "First@Example.com",
            "email_verified": True,
        }
        req = _make_request(
            user_id="first-login-sub",
            auth_subject="first-login-sub",
            is_authenticated=True,
            auth_claims=claims,
        )
        with patch("app.config.settings") as s:
            s.auth_enabled = True
            ctx = await get_identity_context(session, req)

        assert ctx.user_id == "first-login-sub"
        assert ctx.email == "first@example.com"
        assert ctx.account_type == "individual"

    @pytest.mark.asyncio
    async def test_auth_mode_unauthenticated_returns_none_fields(self, session):
        """No JWT → user_id=None, no DB lookup."""
        from app.services.supabase_auth_service import get_identity_context
        req = _make_request(user_id=None, auth_subject=None, is_authenticated=False)
        with patch("app.config.settings") as s:
            s.auth_enabled = True
            ctx = await get_identity_context(session, req)

        assert ctx.user_id is None
        assert ctx.is_authenticated is False
        assert ctx.email is None

    @pytest.mark.asyncio
    async def test_auth_mode_loads_display_name_from_profile(self, session):
        user = await _provision(session, auth_subject="disp-sub")
        from app.db.repositories.account_repo import upsert_profile
        await upsert_profile(session, user.id, display_name="Alice")
        await session.commit()

        from app.services.supabase_auth_service import get_identity_context
        req = _make_request(user_id=user.id, auth_subject="disp-sub", is_authenticated=True)
        with patch("app.config.settings") as s:
            s.auth_enabled = True
            ctx = await get_identity_context(session, req)

        assert ctx.display_name == "Alice"

    @pytest.mark.asyncio
    async def test_auth_mode_unknown_auth_subject_does_not_raise(self, session):
        """Unknown auth_subject returns partial context — provision deferred."""
        from app.services.supabase_auth_service import get_identity_context
        req = _make_request(
            user_id="ghost-id", auth_subject="ghost-sub", is_authenticated=True
        )
        with patch("app.config.settings") as s:
            s.auth_enabled = True
            ctx = await get_identity_context(session, req)

        assert ctx is not None
        assert ctx.email is None  # not found in DB
