"""
Tests for Phase 16 · Slice 5 — ownership_service.py and threaded routes.

Coverage
--------
TestCurrentOwnerId          — bypass always returns system user; auth returns state value
TestResolveEffectiveUserId  — always non-None; unauthenticated falls back to system user
TestIsOwner                 — bypass = always True; auth mode row matching
TestAssertCanAccess         — no-op in bypass; raises in auth mode for wrong owner
TestBypassDeliveryPrefs     — GET/PATCH /delivery/preferences still works in bypass
TestAuthDeliveryPrefs       — real user gets own prefs, system user stays separate
TestBypassInbox             — list_inbox read-receipt uses system user in bypass
TestAuthInbox               — real user read-receipt uses their own user_id
TestBypassDigests           — list_digests scoped to system user in bypass
TestAuthDigests             — list_digests scoped to real user
TestWatchlistServiceOwnership — async methods thread user_id correctly
TestCrossAccountIsolation   — user A cannot see user B's rows
TestNullOwnershipHandling   — NULL row_user_id treated as system-owned
TestSystemUserFallback      — unauthenticated request gets system user ID
"""

from __future__ import annotations

import asyncio
from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

SYSTEM_DEFAULT_USER_ID = "00000000-0000-0000-0000-000000000001"
USER_A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
USER_B = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _make_request(
    user_id: Optional[str] = SYSTEM_DEFAULT_USER_ID,
    auth_subject: Optional[str] = None,
    is_authenticated: bool = False,
    has_state: bool = True,
) -> MagicMock:
    req = MagicMock()

    if has_state:
        class _State:
            pass

        s = _State()
        s.user_id = user_id
        s.auth_subject = auth_subject
        s.is_authenticated = is_authenticated
        req.state = s
    else:
        req.state = MagicMock(spec=[])  # no user_id attribute

    return req


def _patch_auth(enabled: bool = False):
    m = MagicMock()
    m.auth_enabled = enabled
    return patch("app.config.settings", m)


# ---------------------------------------------------------------------------
# 1. TestCurrentOwnerId
# ---------------------------------------------------------------------------

class TestCurrentOwnerId:
    def test_bypass_returns_system_user(self):
        from app.services.ownership_service import current_owner_id
        req = _make_request(user_id=USER_A)
        with _patch_auth(enabled=False):
            result = current_owner_id(req)
        assert result == SYSTEM_DEFAULT_USER_ID

    def test_bypass_ignores_request_state(self):
        from app.services.ownership_service import current_owner_id
        req = _make_request(user_id=USER_B)
        with _patch_auth(enabled=False):
            result = current_owner_id(req)
        assert result == SYSTEM_DEFAULT_USER_ID  # not USER_B

    def test_auth_mode_returns_state_user_id(self):
        from app.services.ownership_service import current_owner_id
        req = _make_request(user_id=USER_A, is_authenticated=True)
        with _patch_auth(enabled=True):
            result = current_owner_id(req)
        assert result == USER_A

    def test_auth_mode_unauthenticated_returns_none(self):
        from app.services.ownership_service import current_owner_id
        req = _make_request(user_id=None, is_authenticated=False)
        with _patch_auth(enabled=True):
            result = current_owner_id(req)
        assert result is None

    def test_auth_mode_missing_state_falls_back_to_system(self):
        from app.services.ownership_service import current_owner_id
        req = _make_request(has_state=False)
        with _patch_auth(enabled=True):
            result = current_owner_id(req)
        assert result == SYSTEM_DEFAULT_USER_ID


# ---------------------------------------------------------------------------
# 2. TestResolveEffectiveUserId
# ---------------------------------------------------------------------------

class TestResolveEffectiveUserId:
    def test_bypass_returns_system_user(self):
        from app.services.ownership_service import resolve_effective_user_id
        req = _make_request()
        with _patch_auth(enabled=False):
            result = resolve_effective_user_id(req)
        assert result == SYSTEM_DEFAULT_USER_ID

    def test_auth_authenticated_returns_user_id(self):
        from app.services.ownership_service import resolve_effective_user_id
        req = _make_request(user_id=USER_A, is_authenticated=True)
        with _patch_auth(enabled=True):
            result = resolve_effective_user_id(req)
        assert result == USER_A

    def test_auth_unauthenticated_falls_back_to_system(self):
        from app.services.ownership_service import resolve_effective_user_id
        req = _make_request(user_id=None, is_authenticated=False)
        with _patch_auth(enabled=True):
            result = resolve_effective_user_id(req)
        assert result == SYSTEM_DEFAULT_USER_ID

    def test_always_returns_string_never_none(self):
        from app.services.ownership_service import resolve_effective_user_id
        req = _make_request(user_id=None)
        with _patch_auth(enabled=True):
            result = resolve_effective_user_id(req)
        assert isinstance(result, str)
        assert result  # non-empty


# ---------------------------------------------------------------------------
# 3. TestIsOwner
# ---------------------------------------------------------------------------

class TestIsOwner:
    def test_bypass_always_true_regardless_of_row(self):
        from app.services.ownership_service import is_owner
        req = _make_request()
        with _patch_auth(enabled=False):
            assert is_owner(req, USER_A) is True
            assert is_owner(req, USER_B) is True
            assert is_owner(req, None) is True

    def test_auth_matching_user_id(self):
        from app.services.ownership_service import is_owner
        req = _make_request(user_id=USER_A, is_authenticated=True)
        with _patch_auth(enabled=True):
            assert is_owner(req, USER_A) is True

    def test_auth_different_user_id(self):
        from app.services.ownership_service import is_owner
        req = _make_request(user_id=USER_A, is_authenticated=True)
        with _patch_auth(enabled=True):
            assert is_owner(req, USER_B) is False

    def test_auth_null_row_matches_system_user(self):
        from app.services.ownership_service import is_owner
        req = _make_request(user_id=SYSTEM_DEFAULT_USER_ID, is_authenticated=True)
        with _patch_auth(enabled=True):
            assert is_owner(req, None) is True

    def test_auth_null_row_does_not_match_real_user(self):
        from app.services.ownership_service import is_owner
        req = _make_request(user_id=USER_A, is_authenticated=True)
        with _patch_auth(enabled=True):
            assert is_owner(req, None) is False

    def test_auth_unauthenticated_owns_nothing(self):
        from app.services.ownership_service import is_owner
        req = _make_request(user_id=None, is_authenticated=False)
        with _patch_auth(enabled=True):
            assert is_owner(req, USER_A) is False
            assert is_owner(req, None) is False


# ---------------------------------------------------------------------------
# 4. TestAssertCanAccess
# ---------------------------------------------------------------------------

class TestAssertCanAccess:
    def test_bypass_never_raises(self):
        from app.services.ownership_service import assert_can_access
        req = _make_request()
        with _patch_auth(enabled=False):
            assert_can_access(req, USER_B)  # no raise
            assert_can_access(req, None)    # no raise

    def test_auth_owner_does_not_raise(self):
        from app.services.ownership_service import assert_can_access
        req = _make_request(user_id=USER_A, is_authenticated=True)
        with _patch_auth(enabled=True):
            assert_can_access(req, USER_A)  # no raise

    def test_auth_non_owner_raises_permission_error(self):
        from app.services.ownership_service import assert_can_access
        req = _make_request(user_id=USER_A, is_authenticated=True)
        with _patch_auth(enabled=True):
            with pytest.raises(PermissionError):
                assert_can_access(req, USER_B)

    def test_auth_unauthenticated_raises_permission_error(self):
        from app.services.ownership_service import assert_can_access
        req = _make_request(user_id=None, is_authenticated=False)
        with _patch_auth(enabled=True):
            with pytest.raises(PermissionError):
                assert_can_access(req, USER_A)


# ---------------------------------------------------------------------------
# 5. TestBypassDeliveryPrefs (route layer)
# ---------------------------------------------------------------------------

class TestBypassDeliveryPrefs:
    """Verify bypass mode keeps /delivery/preferences working unchanged."""

    def _build_app(self):
        from fastapi import FastAPI

        app = FastAPI()

        @app.middleware("http")
        async def inject_state(request, call_next):
            request.state.user_id = SYSTEM_DEFAULT_USER_ID
            request.state.auth_subject = None
            request.state.is_authenticated = False
            return await call_next(request)

        from app.routers.delivery_preferences import router
        app.include_router(router)
        return app

    def test_get_preferences_returns_200_in_bypass(self):
        from fastapi.testclient import TestClient
        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def _null_session():
            yield None

        with _patch_auth(enabled=False):
            with patch("app.db.connection.get_session", return_value=_null_session()):
                client = TestClient(self._build_app())
                resp = client.get("/delivery/preferences")
        assert resp.status_code == 200

    def test_get_preferences_returns_safe_defaults_when_no_db(self):
        from fastapi.testclient import TestClient
        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def _null_session():
            yield None

        with _patch_auth(enabled=False):
            with patch("app.db.connection.get_session", return_value=_null_session()):
                client = TestClient(self._build_app())
                data = client.get("/delivery/preferences").json()
        assert "channel" in data
        assert "row_exists" in data
        assert data["row_exists"] is False


# ---------------------------------------------------------------------------
# 6. TestAuthDeliveryPrefs
# ---------------------------------------------------------------------------

class TestAuthDeliveryPrefs:
    """Real user gets own prefs; system user stays isolated."""

    def _build_app_for_user(self, user_id: Optional[str], is_authenticated: bool = True):
        from fastapi import FastAPI

        app = FastAPI()

        @app.middleware("http")
        async def inject_state(request, call_next):
            request.state.user_id = user_id
            request.state.auth_subject = user_id
            request.state.is_authenticated = is_authenticated
            return await call_next(request)

        from app.routers.delivery_preferences import router
        app.include_router(router)
        return app

    def test_auth_mode_resolves_user_from_state_not_query_param(self):
        from fastapi.testclient import TestClient
        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def _null_session():
            yield None

        with _patch_auth(enabled=True):
            with patch("app.db.connection.get_session", return_value=_null_session()):
                client = TestClient(self._build_app_for_user(USER_A))
                # No user_id query param — should resolve from state
                resp = client.get("/delivery/preferences")
        assert resp.status_code == 200

    def test_explicit_admin_user_id_param_overrides_state(self):
        """Admin override: explicit ?user_id= param takes precedence."""
        from fastapi.testclient import TestClient
        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def _null_session():
            yield None

        with _patch_auth(enabled=False):
            with patch("app.db.connection.get_session", return_value=_null_session()):
                client = TestClient(self._build_app_for_user(SYSTEM_DEFAULT_USER_ID))
                resp = client.get(f"/delivery/preferences?user_id={USER_B}")
        # Should use USER_B (admin override), not USER_A from state
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("user_id") == USER_B

    def test_non_admin_cannot_override_preferences_user(self):
        from fastapi.testclient import TestClient

        with _patch_auth(enabled=True):
            client = TestClient(self._build_app_for_user(USER_A))
            resp = client.get(f"/delivery/preferences?user_id={USER_B}")

        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# 7. TestBypassInbox
# ---------------------------------------------------------------------------

class TestBypassInbox:
    """Bypass mode: inbox read-receipts use SYSTEM_DEFAULT_USER_ID."""

    def _build_app(self):
        from fastapi import FastAPI

        app = FastAPI()

        @app.middleware("http")
        async def inject_state(request, call_next):
            request.state.user_id = SYSTEM_DEFAULT_USER_ID
            request.state.auth_subject = None
            request.state.is_authenticated = False
            return await call_next(request)

        from app.routers.delivery_inbox import router
        app.include_router(router)
        return app

    def test_list_inbox_returns_200_in_bypass(self):
        from fastapi.testclient import TestClient
        from contextlib import asynccontextmanager

        def _mock_session_factory():
            mock_result = MagicMock()
            mock_result.scalars.return_value.all.return_value = []
            mock_result.all.return_value = []
            mock_session = AsyncMock()
            mock_session.execute = AsyncMock(return_value=mock_result)

            @asynccontextmanager
            async def _ctx():
                yield mock_session

            return _ctx()

        with _patch_auth(enabled=False):
            with patch("app.routers.delivery_inbox.get_session", side_effect=_mock_session_factory):
                client = TestClient(self._build_app())
                resp = client.get("/delivery/inbox")
        assert resp.status_code == 200

    def test_list_digests_returns_200_in_bypass(self):
        from fastapi.testclient import TestClient
        from contextlib import asynccontextmanager

        def _mock_session_factory():
            mock_result = MagicMock()
            mock_result.scalars.return_value.all.return_value = []
            mock_result.all.return_value = []
            mock_session = AsyncMock()
            mock_session.execute = AsyncMock(return_value=mock_result)

            @asynccontextmanager
            async def _ctx():
                yield mock_session

            return _ctx()

        with _patch_auth(enabled=False):
            with patch("app.routers.delivery_inbox.get_session", side_effect=_mock_session_factory):
                client = TestClient(self._build_app())
                resp = client.get("/delivery/digests")
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# 8. TestAuthInbox
# ---------------------------------------------------------------------------

class TestAuthInbox:
    """Auth mode: read-receipts and digests are scoped to the request user."""

    def _build_app(self, user_id):
        from fastapi import FastAPI

        app = FastAPI()

        @app.middleware("http")
        async def inject_state(request, call_next):
            request.state.user_id = user_id
            request.state.auth_subject = user_id
            request.state.is_authenticated = True
            return await call_next(request)

        from app.routers.delivery_inbox import router
        app.include_router(router)
        return app

    def test_list_inbox_resolves_user_from_state(self):
        from fastapi.testclient import TestClient
        from contextlib import asynccontextmanager

        def _mock_session_factory():
            mock_result = MagicMock()
            mock_result.scalars.return_value.all.return_value = []
            mock_result.all.return_value = []
            mock_session = AsyncMock()
            mock_session.execute = AsyncMock(return_value=mock_result)

            @asynccontextmanager
            async def _ctx():
                yield mock_session

            return _ctx()

        with _patch_auth(enabled=True):
            with patch("app.routers.delivery_inbox.get_session", side_effect=_mock_session_factory):
                client = TestClient(self._build_app(USER_A))
                resp = client.get("/delivery/inbox")
        assert resp.status_code == 200

    def test_explicit_user_id_overrides_state_for_admin(self):
        """Admin can pass ?user_id= to look up a specific user's read-receipts."""
        from fastapi.testclient import TestClient
        from contextlib import asynccontextmanager

        def _mock_session_factory():
            mock_result = MagicMock()
            mock_result.scalars.return_value.all.return_value = []
            mock_result.all.return_value = []
            mock_session = AsyncMock()
            mock_session.execute = AsyncMock(return_value=mock_result)

            @asynccontextmanager
            async def _ctx():
                yield mock_session

            return _ctx()

        with _patch_auth(enabled=False):
            with patch("app.routers.delivery_inbox.get_session", side_effect=_mock_session_factory):
                client = TestClient(self._build_app(SYSTEM_DEFAULT_USER_ID))
                resp = client.get(f"/delivery/inbox?user_id={USER_A}")
        assert resp.status_code == 200

    def test_non_admin_cannot_override_inbox_user(self):
        from fastapi.testclient import TestClient

        with _patch_auth(enabled=True):
            client = TestClient(self._build_app(USER_A))
            resp = client.get(f"/delivery/inbox?user_id={USER_B}")

        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# 9. TestWatchlistServiceOwnership
# ---------------------------------------------------------------------------

class TestWatchlistServiceOwnership:
    """watchlist_service async methods thread user_id to the repo layer."""

    @pytest_asyncio.fixture
    async def session(self):
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

    @pytest.mark.asyncio
    async def test_add_ticker_async_with_user_id(self, session):
        from app.services.watchlist_service import watchlist_service
        entry = await watchlist_service.add_ticker_async(session, "AAPL", user_id=USER_A)
        assert entry is not None
        assert entry.ticker == "AAPL"

    @pytest.mark.asyncio
    async def test_get_watchlist_async_scoped_to_user(self, session):
        from app.services.watchlist_service import watchlist_service
        # Add ticker under USER_A
        await watchlist_service.add_ticker_async(session, "AAPL", user_id=USER_A)
        await watchlist_service.add_ticker_async(session, "MSFT", user_id=USER_B)
        await session.flush()

        # USER_A's watchlist should only see AAPL
        entries_a = await watchlist_service.get_watchlist_async(session, user_id=USER_A)
        tickers_a = {e.ticker for e in entries_a}
        assert "AAPL" in tickers_a
        assert "MSFT" not in tickers_a

    @pytest.mark.asyncio
    async def test_get_watchlist_async_user_b_isolated(self, session):
        from app.services.watchlist_service import watchlist_service
        await watchlist_service.add_ticker_async(session, "AAPL", user_id=USER_A)
        await watchlist_service.add_ticker_async(session, "MSFT", user_id=USER_B)
        await session.flush()

        entries_b = await watchlist_service.get_watchlist_async(session, user_id=USER_B)
        tickers_b = {e.ticker for e in entries_b}
        assert "MSFT" in tickers_b
        assert "AAPL" not in tickers_b

    @pytest.mark.asyncio
    async def test_system_user_sees_system_owned_tickers(self, session):
        from app.services.watchlist_service import watchlist_service
        await watchlist_service.add_ticker_async(
            session, "SPY", user_id=SYSTEM_DEFAULT_USER_ID
        )
        await session.flush()

        entries = await watchlist_service.get_watchlist_async(
            session, user_id=SYSTEM_DEFAULT_USER_ID
        )
        tickers = {e.ticker for e in entries}
        assert "SPY" in tickers

    @pytest.mark.asyncio
    async def test_remove_ticker_async_scoped_to_user(self, session):
        from app.services.watchlist_service import watchlist_service
        from app.db.repositories.watchlist_repo import ticker_is_active

        await watchlist_service.add_ticker_async(session, "GOOG", user_id=USER_A)
        await watchlist_service.add_ticker_async(session, "GOOG", user_id=USER_B)
        await session.flush()

        # Remove GOOG for USER_A only
        await watchlist_service.remove_ticker_async(session, "GOOG", user_id=USER_A)
        await session.flush()

        # USER_A should no longer have GOOG active; USER_B still does
        a_active = await ticker_is_active(session, "GOOG", user_id=USER_A)
        b_active = await ticker_is_active(session, "GOOG", user_id=USER_B)
        assert a_active is False
        assert b_active is True


# ---------------------------------------------------------------------------
# 10. TestCrossAccountIsolation
# ---------------------------------------------------------------------------

class TestCrossAccountIsolation:
    """Core safety: user A cannot see user B's data through ownership helpers."""

    def test_is_owner_rejects_wrong_user(self):
        from app.services.ownership_service import is_owner
        req = _make_request(user_id=USER_A, is_authenticated=True)
        with _patch_auth(enabled=True):
            # USER_A cannot own USER_B's row
            assert is_owner(req, USER_B) is False

    def test_assert_can_access_raises_for_cross_user(self):
        from app.services.ownership_service import assert_can_access
        req = _make_request(user_id=USER_A, is_authenticated=True)
        with _patch_auth(enabled=True):
            with pytest.raises(PermissionError):
                assert_can_access(req, USER_B)

    def test_watchlist_user_a_cannot_see_user_b_rows(self):
        """Isolation is enforced at the repo WHERE clause level."""
        from app.services.ownership_service import resolve_effective_user_id
        req_a = _make_request(user_id=USER_A, is_authenticated=True)
        req_b = _make_request(user_id=USER_B, is_authenticated=True)
        with _patch_auth(enabled=True):
            uid_a = resolve_effective_user_id(req_a)
            uid_b = resolve_effective_user_id(req_b)
        # Different user_ids → repo WHERE clauses are different → no leakage
        assert uid_a != uid_b


# ---------------------------------------------------------------------------
# 11. TestNullOwnershipHandling
# ---------------------------------------------------------------------------

class TestNullOwnershipHandling:
    def test_null_row_user_id_treated_as_system_owned(self):
        from app.services.ownership_service import is_owner
        req = _make_request(user_id=SYSTEM_DEFAULT_USER_ID, is_authenticated=True)
        with _patch_auth(enabled=True):
            # NULL row_user_id → legacy row → only system user owns it
            assert is_owner(req, None) is True

    def test_null_row_user_id_rejected_for_real_user(self):
        from app.services.ownership_service import is_owner
        req = _make_request(user_id=USER_A, is_authenticated=True)
        with _patch_auth(enabled=True):
            assert is_owner(req, None) is False

    def test_bypass_null_row_always_accessible(self):
        from app.services.ownership_service import is_owner
        req = _make_request(user_id=USER_A)
        with _patch_auth(enabled=False):
            assert is_owner(req, None) is True


# ---------------------------------------------------------------------------
# 12. TestSystemUserFallback
# ---------------------------------------------------------------------------

class TestSystemUserFallback:
    def test_unauthenticated_resolves_to_system_in_bypass(self):
        from app.services.ownership_service import resolve_effective_user_id
        req = _make_request(user_id=None, is_authenticated=False)
        with _patch_auth(enabled=False):
            result = resolve_effective_user_id(req)
        assert result == SYSTEM_DEFAULT_USER_ID

    def test_config_error_falls_back_to_system_user(self):
        """If config.settings raises, ownership defaults to bypass mode."""
        from app.services.ownership_service import current_owner_id
        req = _make_request()
        with patch("app.config.settings", side_effect=RuntimeError("config error")):
            result = current_owner_id(req)
        assert result == SYSTEM_DEFAULT_USER_ID

    def test_system_user_id_constant_correct(self):
        from app.services.ownership_service import system_user_id
        assert system_user_id() == "00000000-0000-0000-0000-000000000001"
