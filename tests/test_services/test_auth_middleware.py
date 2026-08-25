"""
Tests for Phase 16 · Slice 3 — JWT middleware and auth dependencies.

Coverage:
  TestBypassMode        — AUTH_ENABLED=false always stamps system user
  TestExtractBearer     — header parsing edge cases
  TestVerifyJwtHs256    — HS256 JWT accept/reject paths (PyJWT mocked)
  TestVerifyAsymmetric  — ES256/RS256 JWKS verification and algorithm allowlist
  TestVerifyToken       — _verify_token routing HS256 vs asymmetric JWKS
  TestResolveIdentity   — full bypass / enforcement / no-token / bad-token
  TestMiddlewareDispatch— AuthMiddleware.dispatch stamps request.state
  TestGetCurrentUserId  — dependency fallback logic
  TestIsAuthenticated   — is_authenticated helper

Design constraints honoured:
  - All tests run without PyJWT installed (pytest-level mock; no real JWT library needed)
  - AUTH_ENABLED stays False throughout (bypass mode only in Phase 16)
  - No route protection tested (Slice 5)
  - No network calls (JWKS fetch is never triggered)
  - SYSTEM_DEFAULT_USER_ID == "00000000-0000-0000-0000-000000000001"
"""

from __future__ import annotations

import asyncio
import sys
import types
from typing import Any, Dict, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

SYSTEM_DEFAULT_USER_ID = "00000000-0000-0000-0000-000000000001"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_request(
    headers: Optional[Dict[str, str]] = None,
    state_attrs: Optional[Dict[str, Any]] = None,
) -> MagicMock:
    """Build a lightweight mock of a Starlette Request."""
    req = MagicMock()
    _headers = headers or {}
    req.headers = MagicMock()
    req.headers.get = lambda key, default="": _headers.get(key, default)

    # Starlette State object — lets us set arbitrary attributes
    class _State:
        pass

    req.state = _State()
    if state_attrs:
        for k, v in state_attrs.items():
            setattr(req.state, k, v)
    return req


def _run(coro):
    """Run a coroutine synchronously in tests.

    Uses asyncio.run (a fresh loop per call) rather than
    asyncio.get_event_loop().run_until_complete: the latter raises
    "There is no current event loop" once any earlier test in the process has
    called asyncio.run() (which closes the loop it created).  That made this
    whole file fail 17/43 whenever an asyncio.run()-based test ran first —
    a run-order-dependent flake now removed.
    """
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# 1. TestBypassMode
# ---------------------------------------------------------------------------

class TestBypassMode:
    """AUTH_ENABLED=false — every request resolves to system user."""

    def test_bypass_returns_system_user_id(self):
        """With no token and auth disabled, user_id == SYSTEM_DEFAULT_USER_ID."""
        req = _make_request()
        with patch("app.config.settings") as mock_settings:
            mock_settings.auth_enabled = False
            mock_settings.auth_bypass_user_id = SYSTEM_DEFAULT_USER_ID
            from app.middleware.auth_middleware import _resolve_identity

            result = _run(_resolve_identity(req))

        user_id, auth_subject, is_authenticated = result
        assert user_id == SYSTEM_DEFAULT_USER_ID
        assert auth_subject is None
        assert is_authenticated is False

    def test_bypass_ignores_bearer_token(self):
        """Bypass mode does not inspect Authorization header at all."""
        req = _make_request(headers={"authorization": "Bearer some.garbage.token"})
        with patch("app.config.settings") as mock_settings:
            mock_settings.auth_enabled = False
            mock_settings.auth_bypass_user_id = SYSTEM_DEFAULT_USER_ID
            from app.middleware.auth_middleware import _resolve_identity

            result = _run(_resolve_identity(req))

        user_id, _, is_auth = result
        assert user_id == SYSTEM_DEFAULT_USER_ID
        assert is_auth is False

    def test_bypass_uses_config_bypass_user_id(self):
        """auth_bypass_user_id from config is used, not a hardcoded constant."""
        custom_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        req = _make_request()
        with patch("app.config.settings") as mock_settings:
            mock_settings.auth_enabled = False
            mock_settings.auth_bypass_user_id = custom_id
            from app.middleware.auth_middleware import _resolve_identity

            result = _run(_resolve_identity(req))

        user_id, _, _ = result
        assert user_id == custom_id


# ---------------------------------------------------------------------------
# 2. TestExtractBearer
# ---------------------------------------------------------------------------

class TestExtractBearer:
    """_extract_bearer_token edge cases."""

    def _extract(self, header_value: str) -> Optional[str]:
        from app.middleware.auth_middleware import _extract_bearer_token

        req = _make_request(headers={"authorization": header_value})
        return _extract_bearer_token(req)

    def test_valid_bearer(self):
        assert self._extract("Bearer abc.def.ghi") == "abc.def.ghi"

    def test_bearer_case_insensitive(self):
        assert self._extract("bearer abc.def.ghi") == "abc.def.ghi"

    def test_no_auth_header_returns_none(self):
        req = _make_request()
        from app.middleware.auth_middleware import _extract_bearer_token

        assert _extract_bearer_token(req) is None

    def test_basic_auth_returns_none(self):
        assert self._extract("Basic dXNlcjpwYXNz") is None

    def test_empty_bearer_returns_none(self):
        assert self._extract("Bearer ") is None

    def test_bearer_only_returns_none(self):
        assert self._extract("Bearer") is None

    def test_whitespace_only_token_returns_none(self):
        assert self._extract("Bearer    ") is None

    def test_token_with_leading_spaces_stripped(self):
        result = self._extract("Bearer   token123")
        assert result == "token123"


# ---------------------------------------------------------------------------
# 3. TestVerifyJwtHs256
# ---------------------------------------------------------------------------

class TestVerifyJwtHs256:
    """_verify_jwt_hs256 accept/reject with mocked PyJWT."""

    def _call(self, token: str, secret: str, audience: str, mock_jwt):
        from app.middleware import auth_middleware as _mw

        # Temporarily patch module-level _pyjwt and _JWT_AVAILABLE
        old_jwt = _mw._pyjwt
        old_avail = _mw._JWT_AVAILABLE
        try:
            _mw._pyjwt = mock_jwt
            _mw._JWT_AVAILABLE = True
            return _mw._verify_jwt_hs256(token, secret, audience)
        finally:
            _mw._pyjwt = old_jwt
            _mw._JWT_AVAILABLE = old_avail

    def test_valid_token_returns_payload(self):
        mock_jwt = MagicMock()
        mock_jwt.decode.return_value = {"sub": "user-abc", "exp": 9999999999, "aud": "authenticated"}
        payload = self._call("token", "secret", "authenticated", mock_jwt)
        assert payload == {"sub": "user-abc", "exp": 9999999999, "aud": "authenticated"}

    def test_expired_token_returns_none(self):
        mock_jwt = MagicMock()
        mock_jwt.ExpiredSignatureError = Exception
        mock_jwt.InvalidAudienceError = type("IAE", (Exception,), {})
        mock_jwt.InvalidSignatureError = type("ISE", (Exception,), {})
        mock_jwt.DecodeError = type("DE", (Exception,), {})
        mock_jwt.decode.side_effect = mock_jwt.ExpiredSignatureError("expired")
        payload = self._call("token", "secret", "authenticated", mock_jwt)
        assert payload is None

    def test_bad_signature_returns_none(self):
        mock_jwt = MagicMock()
        mock_jwt.ExpiredSignatureError = type("ESE", (Exception,), {})
        mock_jwt.InvalidAudienceError = type("IAE", (Exception,), {})
        mock_jwt.InvalidSignatureError = Exception
        mock_jwt.DecodeError = type("DE", (Exception,), {})
        mock_jwt.decode.side_effect = mock_jwt.InvalidSignatureError("bad sig")
        payload = self._call("token", "secret", "authenticated", mock_jwt)
        assert payload is None

    def test_malformed_token_returns_none(self):
        mock_jwt = MagicMock()
        mock_jwt.ExpiredSignatureError = type("ESE", (Exception,), {})
        mock_jwt.InvalidAudienceError = type("IAE", (Exception,), {})
        mock_jwt.InvalidSignatureError = type("ISE", (Exception,), {})
        mock_jwt.DecodeError = Exception
        mock_jwt.decode.side_effect = mock_jwt.DecodeError("malformed")
        payload = self._call("token", "secret", "authenticated", mock_jwt)
        assert payload is None

    def test_wrong_audience_returns_none(self):
        mock_jwt = MagicMock()
        mock_jwt.ExpiredSignatureError = type("ESE", (Exception,), {})
        mock_jwt.InvalidAudienceError = Exception
        mock_jwt.InvalidSignatureError = type("ISE", (Exception,), {})
        mock_jwt.DecodeError = type("DE", (Exception,), {})
        mock_jwt.decode.side_effect = mock_jwt.InvalidAudienceError("wrong aud")
        payload = self._call("token", "secret", "authenticated", mock_jwt)
        assert payload is None

    def test_empty_secret_returns_none(self):
        mock_jwt = MagicMock()
        payload = self._call("token", "", "authenticated", mock_jwt)
        assert payload is None
        mock_jwt.decode.assert_not_called()

    def test_jwt_not_available_returns_none(self):
        from app.middleware import auth_middleware as _mw

        old_avail = _mw._JWT_AVAILABLE
        try:
            _mw._JWT_AVAILABLE = False
            result = _mw._verify_jwt_hs256("tok", "sec", "authenticated")
        finally:
            _mw._JWT_AVAILABLE = old_avail
        assert result is None

    def test_unexpected_exception_returns_none(self):
        mock_jwt = MagicMock()
        mock_jwt.ExpiredSignatureError = type("ESE", (Exception,), {})
        mock_jwt.InvalidAudienceError = type("IAE", (Exception,), {})
        mock_jwt.InvalidSignatureError = type("ISE", (Exception,), {})
        mock_jwt.DecodeError = type("DE", (Exception,), {})
        mock_jwt.decode.side_effect = RuntimeError("some unexpected error")
        payload = self._call("token", "secret", "authenticated", mock_jwt)
        assert payload is None


# ---------------------------------------------------------------------------
# 4. TestVerifyAsymmetric
# ---------------------------------------------------------------------------

class TestVerifyAsymmetric:
    """Supabase JWKS verification supports only RS256 and ES256."""

    @pytest.mark.parametrize("algorithm", ["RS256", "ES256"])
    def test_accepts_supported_algorithm_and_verifies_claims(self, algorithm):
        from app.middleware import auth_middleware as _mw

        mock_jwt = MagicMock()
        mock_jwt.get_unverified_header.return_value = {"alg": algorithm, "kid": "key-1"}
        mock_jwt.PyJWKClient.return_value.get_signing_key_from_jwt.return_value.key = "public-key"
        mock_jwt.decode.return_value = {
            "sub": "user-1",
            "aud": "authenticated",
            "exp": 9999999999,
            "iss": "https://proj.supabase.co/auth/v1",
        }

        with patch.object(_mw, "_pyjwt", mock_jwt), patch.object(
            _mw, "_JWT_AVAILABLE", True
        ), patch.object(_mw, "_jwks_clients", {}):
            payload = _run(_mw._verify_jwt_asymmetric(
                "token", "https://proj.supabase.co", "authenticated"
            ))

        assert payload["sub"] == "user-1"
        _, kwargs = mock_jwt.decode.call_args
        assert kwargs["algorithms"] == [algorithm]
        assert kwargs["issuer"] == "https://proj.supabase.co/auth/v1"
        assert kwargs["options"]["require"] == ["sub", "exp", "aud", "iss"]

    def test_rejects_algorithm_outside_allowlist(self):
        from app.middleware import auth_middleware as _mw

        mock_jwt = MagicMock()
        mock_jwt.get_unverified_header.return_value = {"alg": "HS256"}
        with patch.object(_mw, "_pyjwt", mock_jwt), patch.object(
            _mw, "_JWT_AVAILABLE", True
        ), patch.object(_mw, "_jwks_clients", {}):
            payload = _run(_mw._verify_jwt_asymmetric(
                "token", "https://proj.supabase.co", "authenticated"
            ))

        assert payload is None
        mock_jwt.PyJWKClient.assert_not_called()
        mock_jwt.decode.assert_not_called()


# ---------------------------------------------------------------------------
# 5. TestVerifyToken — routing
# ---------------------------------------------------------------------------

class TestVerifyToken:
    """_verify_token picks legacy HS256 vs asymmetric JWKS from settings."""

    def test_uses_hs256_when_secret_set(self):
        with patch("app.config.settings") as mock_settings:
            mock_settings.supabase_jwt_secret = "my-secret"
            mock_settings.supabase_audience = "authenticated"
            mock_settings.supabase_project_url = ""
            with patch(
                "app.middleware.auth_middleware._verify_jwt_hs256",
                return_value={"sub": "u1"},
            ) as mock_hs256:
                from app.middleware.auth_middleware import _verify_token

                result = _run(_verify_token("token"))

        mock_hs256.assert_called_once_with("token", "my-secret", "authenticated")
        assert result == {"sub": "u1"}

    def test_uses_asymmetric_jwks_when_no_secret_but_project_url(self):
        with patch("app.config.settings") as mock_settings:
            mock_settings.supabase_jwt_secret = ""
            mock_settings.supabase_project_url = "https://proj.supabase.co"
            mock_settings.supabase_audience = "authenticated"
            with patch(
                "app.middleware.auth_middleware._verify_jwt_asymmetric",
                new=AsyncMock(return_value={"sub": "u2"}),
            ) as mock_asymmetric:
                from app.middleware.auth_middleware import _verify_token

                result = _run(_verify_token("token"))

        mock_asymmetric.assert_awaited_once_with(
            "token", "https://proj.supabase.co", "authenticated"
        )
        assert result == {"sub": "u2"}

    def test_returns_none_when_neither_configured(self):
        with patch("app.config.settings") as mock_settings:
            mock_settings.supabase_jwt_secret = ""
            mock_settings.supabase_project_url = ""
            from app.middleware.auth_middleware import _verify_token

            result = _run(_verify_token("token"))

        assert result is None


# ---------------------------------------------------------------------------
# 6. TestResolveIdentity
# ---------------------------------------------------------------------------

class TestResolveIdentity:
    """_resolve_identity full decision tree."""

    def test_bypass_always_returns_system_user(self):
        req = _make_request()
        with patch("app.config.settings") as s:
            s.auth_enabled = False
            s.auth_bypass_user_id = SYSTEM_DEFAULT_USER_ID
            from app.middleware.auth_middleware import _resolve_identity

            uid, sub, is_auth = _run(_resolve_identity(req))

        assert uid == SYSTEM_DEFAULT_USER_ID
        assert sub is None
        assert is_auth is False

    def test_enforcement_no_token_returns_none(self):
        req = _make_request()  # no Authorization header
        with patch("app.config.settings") as s:
            s.auth_enabled = True
            from app.middleware.auth_middleware import _resolve_identity

            uid, sub, is_auth = _run(_resolve_identity(req))

        assert uid is None
        assert sub is None
        assert is_auth is False

    def test_enforcement_bad_token_returns_none(self):
        req = _make_request(headers={"authorization": "Bearer garbage"})
        with patch("app.config.settings") as s:
            s.auth_enabled = True
            with patch(
                "app.middleware.auth_middleware._verify_token",
                new=AsyncMock(return_value=None),
            ):
                from app.middleware.auth_middleware import _resolve_identity

                uid, sub, is_auth = _run(_resolve_identity(req))

        assert uid is None
        assert is_auth is False

    def test_enforcement_valid_token_returns_sub(self):
        req = _make_request(headers={"authorization": "Bearer valid.jwt.token"})
        payload = {"sub": "real-user-uuid", "aud": "authenticated", "exp": 9999999999}
        with patch("app.config.settings") as s:
            s.auth_enabled = True
            with patch(
                "app.middleware.auth_middleware._verify_token",
                new=AsyncMock(return_value=payload),
            ):
                from app.middleware.auth_middleware import _resolve_identity

                uid, sub, is_auth = _run(_resolve_identity(req))

        assert uid == "real-user-uuid"
        assert sub == "real-user-uuid"
        assert is_auth is True
        assert req.state.auth_claims == payload

    def test_enforcement_payload_missing_sub_returns_none(self):
        req = _make_request(headers={"authorization": "Bearer valid.jwt.token"})
        # Payload with no 'sub' field
        payload = {"aud": "authenticated", "exp": 9999999999}
        with patch("app.config.settings") as s:
            s.auth_enabled = True
            with patch(
                "app.middleware.auth_middleware._verify_token",
                new=AsyncMock(return_value=payload),
            ):
                from app.middleware.auth_middleware import _resolve_identity

                uid, sub, is_auth = _run(_resolve_identity(req))

        assert uid is None
        assert is_auth is False


# ---------------------------------------------------------------------------
# 7. TestMiddlewareDispatch
# ---------------------------------------------------------------------------

class TestMiddlewareDispatch:
    """AuthMiddleware.dispatch stamps request.state attributes."""

    def _dispatch(self, user_id, auth_subject, is_auth):
        """Helper: run dispatch with patched _resolve_identity."""

        async def _fake_resolve(req):
            return user_id, auth_subject, is_auth

        class _FakeApp:
            async def __call__(self, scope, receive, send):
                pass

        from app.middleware.auth_middleware import AuthMiddleware

        mw = AuthMiddleware(_FakeApp())
        req = _make_request()
        response = MagicMock()
        response.headers = {}

        async def call_next(r):
            return response

        with patch("app.middleware.auth_middleware._resolve_identity", side_effect=_fake_resolve):
            with patch(
                "app.middleware.auth_middleware._resolve_local_user_id",
                new=AsyncMock(return_value=user_id),
            ):
                _run(mw.dispatch(req, call_next))

        return req

    def test_bypass_stamps_system_user(self):
        req = self._dispatch(SYSTEM_DEFAULT_USER_ID, None, False)
        assert req.state.user_id == SYSTEM_DEFAULT_USER_ID
        assert req.state.auth_subject is None
        assert req.state.is_authenticated is False

    def test_valid_jwt_stamps_real_user(self):
        req = self._dispatch("real-user-id", "real-user-id", True)
        assert req.state.user_id == "real-user-id"
        assert req.state.auth_subject == "real-user-id"
        assert req.state.is_authenticated is True

    def test_no_token_stamps_none(self):
        req = self._dispatch(None, None, False)
        assert req.state.user_id is None
        assert req.state.is_authenticated is False

    @pytest.mark.parametrize(
        ("auth_enabled", "expected_user_id"),
        [(False, SYSTEM_DEFAULT_USER_ID), (True, None)],
    )
    def test_dispatch_resolution_failure_respects_auth_mode(
        self, auth_enabled, expected_user_id
    ):
        """Resolution errors bypass only when auth is disabled."""
        from app.middleware.auth_middleware import AuthMiddleware

        class _FakeApp:
            async def __call__(self, scope, receive, send):
                pass

        mw = AuthMiddleware(_FakeApp())
        req = _make_request()
        response = MagicMock()
        response.headers = {}

        async def call_next(r):
            return response

        async def _raising_resolve(req):
            raise RuntimeError("unexpected error")

        with patch("app.config.settings") as s:
            s.auth_enabled = auth_enabled
            s.auth_bypass_user_id = SYSTEM_DEFAULT_USER_ID
            with patch(
                "app.middleware.auth_middleware._resolve_identity",
                side_effect=_raising_resolve,
            ):
                # Must not raise
                _run(mw.dispatch(req, call_next))

        assert req.state.user_id == expected_user_id
        assert req.state.is_authenticated is False


# ---------------------------------------------------------------------------
# 8. TestGetCurrentUserId
# ---------------------------------------------------------------------------

class TestGetCurrentUserId:
    """get_current_user_id dependency helper."""

    def test_returns_state_user_id_when_set(self):
        req = _make_request(state_attrs={"user_id": "user-abc"})
        from app.dependencies.auth import get_current_user_id

        assert get_current_user_id(req) == "user-abc"

    def test_returns_none_when_user_id_is_none(self):
        req = _make_request(state_attrs={"user_id": None})
        from app.dependencies.auth import get_current_user_id

        assert get_current_user_id(req) is None

    def test_falls_back_to_system_user_when_state_absent(self):
        """Middleware not attached — fallback to SYSTEM_DEFAULT_USER_ID."""
        req = _make_request()  # no state_attrs set
        from app.dependencies.auth import get_current_user_id, SYSTEM_DEFAULT_USER_ID as _SYS

        result = get_current_user_id(req)
        assert result == _SYS

    def test_returns_system_user_in_bypass_mode_end_to_end(self):
        """Simulated full dispatch: middleware bypass → dependency returns system id."""
        req = _make_request()
        req.state.user_id = SYSTEM_DEFAULT_USER_ID
        req.state.auth_subject = None
        req.state.is_authenticated = False

        from app.dependencies.auth import get_current_user_id

        assert get_current_user_id(req) == SYSTEM_DEFAULT_USER_ID


# ---------------------------------------------------------------------------
# 9. TestIsAuthenticated
# ---------------------------------------------------------------------------

class TestIsAuthenticated:
    """is_authenticated and get_auth_subject helpers."""

    def test_authenticated_true_when_state_set(self):
        req = _make_request(state_attrs={"is_authenticated": True})
        from app.dependencies.auth import is_authenticated

        assert is_authenticated(req) is True

    def test_authenticated_false_in_bypass(self):
        req = _make_request(state_attrs={"is_authenticated": False})
        from app.dependencies.auth import is_authenticated

        assert is_authenticated(req) is False

    def test_authenticated_false_when_state_absent(self):
        req = _make_request()
        from app.dependencies.auth import is_authenticated

        assert is_authenticated(req) is False

    def test_auth_subject_returns_none_in_bypass(self):
        req = _make_request(state_attrs={"auth_subject": None})
        from app.dependencies.auth import get_auth_subject

        assert get_auth_subject(req) is None

    def test_auth_subject_returns_sub_when_authenticated(self):
        req = _make_request(state_attrs={"auth_subject": "auth-subject-uuid"})
        from app.dependencies.auth import get_auth_subject

        assert get_auth_subject(req) == "auth-subject-uuid"

    def test_auth_subject_fallback_when_state_absent(self):
        req = _make_request()
        from app.dependencies.auth import get_auth_subject

        assert get_auth_subject(req) is None


# ---------------------------------------------------------------------------
# 10. TestNoBehaviorChange
# ---------------------------------------------------------------------------

class TestNoBehaviorChange:
    """Bypass mode must not alter any pre-Phase-16 observable behavior."""

    def test_middleware_does_not_block_request(self):
        """Dispatch must always call call_next and return a response."""
        from app.middleware.auth_middleware import AuthMiddleware

        class _FakeApp:
            async def __call__(self, scope, receive, send):
                pass

        mw = AuthMiddleware(_FakeApp())
        req = _make_request()
        called = []

        async def call_next(r):
            called.append(True)
            response = MagicMock()
            response.headers = {}
            return response

        with patch("app.config.settings") as s:
            s.auth_enabled = False
            s.auth_bypass_user_id = SYSTEM_DEFAULT_USER_ID
            _run(mw.dispatch(req, call_next))

        assert called, "call_next was never invoked — middleware blocked the request"

    def test_bypass_does_not_inspect_jwt_library(self):
        """No PyJWT functions are called in bypass mode."""
        from app.middleware import auth_middleware as _mw

        mock_jwt = MagicMock()
        old_jwt = _mw._pyjwt
        _mw._pyjwt = mock_jwt
        try:
            req = _make_request(headers={"authorization": "Bearer some.token"})
            with patch("app.config.settings") as s:
                s.auth_enabled = False
                s.auth_bypass_user_id = SYSTEM_DEFAULT_USER_ID
                _run(_mw._resolve_identity(req))

            mock_jwt.decode.assert_not_called()
        finally:
            _mw._pyjwt = old_jwt
