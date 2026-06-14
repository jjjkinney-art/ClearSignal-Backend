"""
Tests for Phase 16 · Slice 4 — auth routes.

Strategy
--------
Routes are thin wrappers over supabase_auth_service.  We mount just the auth
router on a minimal FastAPI app, inject request.state via a test middleware,
and mock out the DB session so the tests run without a real database.

Coverage
--------
TestMeEndpointBypass       — GET /auth/me in bypass mode
TestMeEndpointAuth         — GET /auth/me in enforcement mode (mocked)
TestSessionEndpoint        — GET /auth/session
TestLogoutEndpoint         — POST /auth/logout
TestMeResponseShape        — response fields and types
TestSessionResponseShape   — response fields and types
TestLogoutResponseShape    — response fields and types
TestBypassPreservation     — bypass mode unchanged from pre-Slice-4
"""

from __future__ import annotations

from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

SYSTEM_DEFAULT_USER_ID = "00000000-0000-0000-0000-000000000001"

# ---------------------------------------------------------------------------
# Test app factory
# ---------------------------------------------------------------------------

def _build_app(
    user_id: Optional[str] = SYSTEM_DEFAULT_USER_ID,
    auth_subject: Optional[str] = None,
    is_authenticated: bool = False,
    auth_enabled: bool = False,
) -> FastAPI:
    """Build a minimal FastAPI app with the auth router and injected state."""
    app = FastAPI()

    # Inject request.state (replaces AuthMiddleware for route tests)
    @app.middleware("http")
    async def inject_state(request, call_next):
        request.state.user_id = user_id
        request.state.auth_subject = auth_subject
        request.state.is_authenticated = is_authenticated
        return await call_next(request)

    from app.routers.auth import router
    app.include_router(router)
    return app


def _client(
    user_id: Optional[str] = SYSTEM_DEFAULT_USER_ID,
    auth_subject: Optional[str] = None,
    is_authenticated: bool = False,
    auth_enabled: bool = False,
    mock_session=None,
) -> TestClient:
    """TestClient with mocked config and DB session."""
    app = _build_app(
        user_id=user_id,
        auth_subject=auth_subject,
        is_authenticated=is_authenticated,
    )
    client = TestClient(app, raise_server_exceptions=True)
    return client


# ---------------------------------------------------------------------------
# Shared patcher helpers
# ---------------------------------------------------------------------------

def _patch_settings(auth_enabled: bool = False):
    """Return a context manager that patches app.config.settings."""
    m = MagicMock()
    m.auth_enabled = auth_enabled
    return patch("app.config.settings", m)


def _patch_session(return_value=None):
    """Patch get_session to return a context-manager yielding None (no DB)."""
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _null_session():
        yield return_value

    return patch("app.db.connection.get_session", return_value=_null_session())


# ---------------------------------------------------------------------------
# 1. TestMeEndpointBypass
# ---------------------------------------------------------------------------

class TestMeEndpointBypass:
    def test_me_returns_200(self):
        with _patch_settings(auth_enabled=False):
            with _patch_session():
                client = _client()
                resp = client.get("/auth/me")
        assert resp.status_code == 200

    def test_me_bypass_user_id(self):
        with _patch_settings(auth_enabled=False):
            with _patch_session():
                client = _client()
                data = client.get("/auth/me").json()
        assert data["user_id"] == SYSTEM_DEFAULT_USER_ID

    def test_me_bypass_is_not_authenticated(self):
        with _patch_settings(auth_enabled=False):
            with _patch_session():
                data = _client().get("/auth/me").json()
        assert data["is_authenticated"] is False

    def test_me_bypass_mode_true(self):
        with _patch_settings(auth_enabled=False):
            with _patch_session():
                data = _client().get("/auth/me").json()
        assert data["bypass_mode"] is True

    def test_me_bypass_no_auth_subject(self):
        with _patch_settings(auth_enabled=False):
            with _patch_session():
                data = _client().get("/auth/me").json()
        assert data["auth_subject"] is None

    def test_me_bypass_email_null(self):
        with _patch_settings(auth_enabled=False):
            with _patch_session():
                data = _client().get("/auth/me").json()
        assert data["email"] is None

    def test_me_bad_token_in_bypass_still_returns_system_user(self):
        """Bypass ignores Authorization header content entirely."""
        with _patch_settings(auth_enabled=False):
            with _patch_session():
                client = _client()
                data = client.get("/auth/me", headers={"Authorization": "Bearer garbage"}).json()
        assert data["user_id"] == SYSTEM_DEFAULT_USER_ID
        assert data["bypass_mode"] is True


# ---------------------------------------------------------------------------
# 2. TestMeEndpointAuth
# ---------------------------------------------------------------------------

class TestMeEndpointAuth:
    def test_me_unauthenticated_returns_null_user_id(self):
        """No valid JWT → user_id=None in enforcement mode."""
        with _patch_settings(auth_enabled=True):
            with _patch_session():
                client = _client(user_id=None, auth_subject=None, is_authenticated=False)
                data = client.get("/auth/me").json()
        assert data["user_id"] is None
        assert data["is_authenticated"] is False
        assert data["bypass_mode"] is False

    def test_me_authenticated_returns_real_user(self):
        """Authenticated request with mocked identity context."""
        from app.services.supabase_auth_service import IdentityContext

        fake_ctx = IdentityContext(
            user_id="real-user-uuid",
            auth_subject="real-sub",
            is_authenticated=True,
            bypass_mode=False,
            email="real@example.com",
            account_type="individual",
        )

        with _patch_settings(auth_enabled=True):
            with patch(
                "app.services.supabase_auth_service.get_identity_context",
                new=AsyncMock(return_value=fake_ctx),
            ):
                with _patch_session():
                    client = _client(
                        user_id="real-user-uuid",
                        auth_subject="real-sub",
                        is_authenticated=True,
                    )
                    data = client.get("/auth/me").json()

        assert data["user_id"] == "real-user-uuid"
        assert data["is_authenticated"] is True
        assert data["email"] == "real@example.com"
        assert data["bypass_mode"] is False


# ---------------------------------------------------------------------------
# 3. TestSessionEndpoint
# ---------------------------------------------------------------------------

class TestSessionEndpoint:
    def test_session_returns_200(self):
        with _patch_settings(auth_enabled=False):
            data = _client().get("/auth/session").json()
        # If we get here, status was 200
        assert "session_active" in data

    def test_session_active_when_user_id_set(self):
        with _patch_settings(auth_enabled=False):
            data = _client(user_id=SYSTEM_DEFAULT_USER_ID).get("/auth/session").json()
        assert data["session_active"] is True

    def test_session_not_active_when_user_id_none(self):
        with _patch_settings(auth_enabled=True):
            data = _client(user_id=None).get("/auth/session").json()
        assert data["session_active"] is False

    def test_session_bypass_mode_reflects_config(self):
        with _patch_settings(auth_enabled=False):
            data = _client().get("/auth/session").json()
        assert data["bypass_mode"] is True
        assert data["auth_enabled"] is False

    def test_session_enforcement_mode(self):
        with _patch_settings(auth_enabled=True):
            data = _client(user_id="u1", is_authenticated=True).get("/auth/session").json()
        assert data["auth_enabled"] is True
        assert data["bypass_mode"] is False

    def test_session_is_authenticated_false_in_bypass(self):
        with _patch_settings(auth_enabled=False):
            data = _client(is_authenticated=False).get("/auth/session").json()
        assert data["is_authenticated"] is False

    def test_session_is_authenticated_true_in_auth_mode(self):
        with _patch_settings(auth_enabled=True):
            data = _client(user_id="u2", is_authenticated=True).get("/auth/session").json()
        assert data["is_authenticated"] is True

    def test_session_user_id_returned(self):
        with _patch_settings(auth_enabled=False):
            data = _client(user_id=SYSTEM_DEFAULT_USER_ID).get("/auth/session").json()
        assert data["user_id"] == SYSTEM_DEFAULT_USER_ID


# ---------------------------------------------------------------------------
# 4. TestLogoutEndpoint
# ---------------------------------------------------------------------------

class TestLogoutEndpoint:
    def test_logout_returns_200(self):
        with _patch_session():
            data = _client().post("/auth/logout").json()
        assert data["status"] == "ok"

    def test_logout_response_message(self):
        with _patch_session():
            data = _client().post("/auth/logout").json()
        assert "session cleared" in data["message"].lower()

    def test_logout_works_in_bypass_mode(self):
        with _patch_settings(auth_enabled=False):
            with _patch_session():
                resp = _client().post("/auth/logout")
        assert resp.status_code == 200

    def test_logout_works_when_db_unavailable(self):
        """Logout must succeed even when DB session is None (non-fatal)."""
        with _patch_session(return_value=None):
            resp = _client().post("/auth/logout")
        assert resp.status_code == 200

    def test_logout_works_with_no_user_id(self):
        """Unauthenticated logout still returns 200."""
        with _patch_session(return_value=None):
            resp = _client(user_id=None).post("/auth/logout")
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# 5. TestMeResponseShape
# ---------------------------------------------------------------------------

class TestMeResponseShape:
    def test_all_expected_fields_present(self):
        with _patch_settings(auth_enabled=False):
            with _patch_session():
                data = _client().get("/auth/me").json()
        expected_keys = {
            "user_id", "auth_subject", "is_authenticated",
            "bypass_mode", "email", "account_type", "display_name",
        }
        assert expected_keys.issubset(data.keys())

    def test_is_authenticated_is_bool(self):
        with _patch_settings(auth_enabled=False):
            with _patch_session():
                data = _client().get("/auth/me").json()
        assert isinstance(data["is_authenticated"], bool)

    def test_bypass_mode_is_bool(self):
        with _patch_settings(auth_enabled=False):
            with _patch_session():
                data = _client().get("/auth/me").json()
        assert isinstance(data["bypass_mode"], bool)


# ---------------------------------------------------------------------------
# 6. TestSessionResponseShape
# ---------------------------------------------------------------------------

class TestSessionResponseShape:
    def test_all_expected_fields_present(self):
        with _patch_settings(auth_enabled=False):
            data = _client().get("/auth/session").json()
        expected_keys = {
            "session_active", "user_id", "is_authenticated",
            "auth_enabled", "bypass_mode",
        }
        assert expected_keys.issubset(data.keys())

    def test_session_active_is_bool(self):
        with _patch_settings(auth_enabled=False):
            data = _client().get("/auth/session").json()
        assert isinstance(data["session_active"], bool)

    def test_auth_enabled_is_bool(self):
        with _patch_settings(auth_enabled=False):
            data = _client().get("/auth/session").json()
        assert isinstance(data["auth_enabled"], bool)


# ---------------------------------------------------------------------------
# 7. TestLogoutResponseShape
# ---------------------------------------------------------------------------

class TestLogoutResponseShape:
    def test_status_field_present(self):
        with _patch_session():
            data = _client().post("/auth/logout").json()
        assert "status" in data

    def test_message_field_present(self):
        with _patch_session():
            data = _client().post("/auth/logout").json()
        assert "message" in data


# ---------------------------------------------------------------------------
# 8. TestBypassPreservation
# ---------------------------------------------------------------------------

class TestBypassPreservation:
    def test_no_route_protection_on_me(self):
        """GET /auth/me returns 200 even with no Authorization header."""
        with _patch_settings(auth_enabled=False):
            with _patch_session():
                resp = _client().get("/auth/me")
        assert resp.status_code == 200

    def test_no_route_protection_on_session(self):
        with _patch_settings(auth_enabled=False):
            resp = _client().get("/auth/session")
        assert resp.status_code == 200

    def test_no_route_protection_on_logout(self):
        with _patch_session():
            resp = _client().post("/auth/logout")
        assert resp.status_code == 200

    def test_system_user_id_constant_matches(self):
        """The bypass user_id is the well-known system UUID."""
        with _patch_settings(auth_enabled=False):
            with _patch_session():
                data = _client().get("/auth/me").json()
        assert data["user_id"] == "00000000-0000-0000-0000-000000000001"
