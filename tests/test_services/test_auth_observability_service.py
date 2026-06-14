"""
Tests for app/services/auth_observability_service.py — Phase 16 · Slice 8.

Test matrix:
  1. TestNullSessionSnapshot    — session=None returns a degraded but valid snapshot
  2. TestEmptyDbSnapshot        — fresh DB with no data yields correct zeroes
  3. TestPopulatedSnapshot      — seeded DB returns accurate counts
  4. TestSafeStateLogic         — safe_state/reasons reflect correct conditions
  5. TestNoSecretsExposed       — snapshot dict never includes secret values
  6. TestDbFailureDegradation   — DB error sets db_available=False, returns safely
  7. TestAuthRoutesPresence     — route/middleware boolean flags correct
  8. TestSnapshotDict           — snapshot_to_dict is JSON-serialisable and complete
  9. TestAdminEndpoint          — GET /admin/auth-status returns 200 with expected keys
"""

from __future__ import annotations

import asyncio
import pytest
import pytest_asyncio
from unittest.mock import patch, MagicMock, AsyncMock

SYSTEM_DEFAULT_USER_ID = "00000000-0000-0000-0000-000000000001"
USER_A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def session():
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
    from sqlalchemy.orm import sessionmaker
    from app.db.models import Base

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as s:
        yield s

    await engine.dispose()


@pytest_asyncio.fixture
async def seeded_session():
    """Session with system user + real user + import audit entry."""
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
    from sqlalchemy.orm import sessionmaker
    from app.db.models import (
        Base, User, UserProfile, UserSettings, AuditLog,
        WatchedTicker, Portfolio,
    )

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as s:
        # System user
        s.add(User(
            id=SYSTEM_DEFAULT_USER_ID,
            email="system@clearsignal.internal",
            account_type="system",
            email_verified=True,
        ))
        s.add(UserProfile(user_id=SYSTEM_DEFAULT_USER_ID, onboarding_step="onboarding_complete"))
        s.add(UserSettings(user_id=SYSTEM_DEFAULT_USER_ID))

        # Real user
        s.add(User(id=USER_A, email="alice@example.com", account_type="individual"))
        s.add(UserProfile(user_id=USER_A, onboarding_step="import_completed"))
        s.add(UserSettings(user_id=USER_A))

        # Import audit entry for USER_A
        s.add(AuditLog(
            id="audit-run-1", user_id=USER_A,
            resource="import_run", resource_id=None, action="import",
        ))

        # System-owned rows (claimed)
        s.add(WatchedTicker(
            id="wt-1", user_id=SYSTEM_DEFAULT_USER_ID,
            ticker="AAPL", company_name="Apple", active=True,
        ))
        s.add(Portfolio(
            id="po-1", user_id=SYSTEM_DEFAULT_USER_ID,
            name="My Portfolio", is_default=True,
        ))

        await s.commit()
        yield s

    await engine.dispose()


# ---------------------------------------------------------------------------
# 1. TestNullSessionSnapshot
# ---------------------------------------------------------------------------

class TestNullSessionSnapshot:
    """session=None returns a degraded but structurally valid snapshot."""

    def test_returns_snapshot(self):
        from app.services.auth_observability_service import build_auth_snapshot
        snap = asyncio.get_event_loop().run_until_complete(build_auth_snapshot(None))
        assert snap is not None

    def test_db_available_false(self):
        from app.services.auth_observability_service import build_auth_snapshot
        snap = asyncio.get_event_loop().run_until_complete(build_auth_snapshot(None))
        assert snap.db_available is False

    def test_counts_are_zero(self):
        from app.services.auth_observability_service import build_auth_snapshot
        snap = asyncio.get_event_loop().run_until_complete(build_auth_snapshot(None))
        assert snap.user_count == 0
        assert snap.profile_count == 0
        assert snap.claimed_rows_count == 0
        assert snap.null_rows_count == 0

    def test_system_user_present_false(self):
        from app.services.auth_observability_service import build_auth_snapshot
        snap = asyncio.get_event_loop().run_until_complete(build_auth_snapshot(None))
        assert snap.system_user_present is False

    def test_safe_state_false_when_db_unavailable(self):
        from app.services.auth_observability_service import build_auth_snapshot
        snap = asyncio.get_event_loop().run_until_complete(build_auth_snapshot(None))
        # db_available=False → safe_state must be False
        assert snap.safe_state is False

    def test_generated_at_present(self):
        from app.services.auth_observability_service import build_auth_snapshot
        snap = asyncio.get_event_loop().run_until_complete(build_auth_snapshot(None))
        assert snap.generated_at
        assert "T" in snap.generated_at  # ISO format


# ---------------------------------------------------------------------------
# 2. TestEmptyDbSnapshot
# ---------------------------------------------------------------------------

class TestEmptyDbSnapshot:
    """Fresh empty DB returns correct zero counts."""

    @pytest.mark.asyncio
    async def test_all_counts_zero(self, session):
        from app.services.auth_observability_service import build_auth_snapshot
        snap = await build_auth_snapshot(session)
        assert snap.user_count == 0
        assert snap.real_user_count == 0
        assert snap.profile_count == 0
        assert snap.imported_users_count == 0

    @pytest.mark.asyncio
    async def test_db_available_true(self, session):
        from app.services.auth_observability_service import build_auth_snapshot
        snap = await build_auth_snapshot(session)
        assert snap.db_available is True

    @pytest.mark.asyncio
    async def test_system_user_absent(self, session):
        from app.services.auth_observability_service import build_auth_snapshot
        snap = await build_auth_snapshot(session)
        assert snap.system_user_present is False

    @pytest.mark.asyncio
    async def test_onboarding_by_step_empty(self, session):
        from app.services.auth_observability_service import build_auth_snapshot
        snap = await build_auth_snapshot(session)
        assert snap.onboarding_by_step == {}


# ---------------------------------------------------------------------------
# 3. TestPopulatedSnapshot
# ---------------------------------------------------------------------------

class TestPopulatedSnapshot:
    """Seeded DB returns accurate counts."""

    @pytest.mark.asyncio
    async def test_user_count(self, seeded_session):
        from app.services.auth_observability_service import build_auth_snapshot
        snap = await build_auth_snapshot(seeded_session)
        assert snap.user_count == 2  # system + USER_A

    @pytest.mark.asyncio
    async def test_real_user_count(self, seeded_session):
        from app.services.auth_observability_service import build_auth_snapshot
        snap = await build_auth_snapshot(seeded_session)
        assert snap.real_user_count == 1  # only USER_A

    @pytest.mark.asyncio
    async def test_profile_count(self, seeded_session):
        from app.services.auth_observability_service import build_auth_snapshot
        snap = await build_auth_snapshot(seeded_session)
        assert snap.profile_count == 2

    @pytest.mark.asyncio
    async def test_system_user_present(self, seeded_session):
        from app.services.auth_observability_service import build_auth_snapshot
        snap = await build_auth_snapshot(seeded_session)
        assert snap.system_user_present is True

    @pytest.mark.asyncio
    async def test_imported_users_count(self, seeded_session):
        from app.services.auth_observability_service import build_auth_snapshot
        snap = await build_auth_snapshot(seeded_session)
        assert snap.imported_users_count == 1

    @pytest.mark.asyncio
    async def test_claimed_rows_counted(self, seeded_session):
        from app.services.auth_observability_service import build_auth_snapshot
        snap = await build_auth_snapshot(seeded_session)
        # 1 watched_ticker + 1 portfolio = 2 claimed rows
        assert snap.claimed_rows_count == 2

    @pytest.mark.asyncio
    async def test_null_rows_zero(self, seeded_session):
        from app.services.auth_observability_service import build_auth_snapshot
        snap = await build_auth_snapshot(seeded_session)
        assert snap.null_rows_count == 0

    @pytest.mark.asyncio
    async def test_onboarding_by_step(self, seeded_session):
        from app.services.auth_observability_service import build_auth_snapshot
        snap = await build_auth_snapshot(seeded_session)
        # system user = onboarding_complete, USER_A = import_completed
        assert snap.onboarding_by_step.get("onboarding_complete", 0) == 1
        assert snap.onboarding_by_step.get("import_completed", 0) == 1


# ---------------------------------------------------------------------------
# 4. TestSafeStateLogic
# ---------------------------------------------------------------------------

class TestSafeStateLogic:
    """safe_state and safe_state_reasons reflect each condition correctly."""

    @pytest.mark.asyncio
    async def test_safe_state_true_in_bypass_with_system_user(self, seeded_session):
        from app.services.auth_observability_service import build_auth_snapshot
        with patch("app.config.settings") as mock_s:
            mock_s.auth_enabled = False
            mock_s.supabase_project_url = ""
            mock_s.supabase_jwt_secret = ""
            snap = await build_auth_snapshot(seeded_session)
        assert snap.safe_state is True

    @pytest.mark.asyncio
    async def test_safe_state_false_when_auth_enabled(self, seeded_session):
        from app.services.auth_observability_service import build_auth_snapshot
        with patch("app.config.settings") as mock_s:
            mock_s.auth_enabled = True
            mock_s.supabase_project_url = ""
            mock_s.supabase_jwt_secret = ""
            snap = await build_auth_snapshot(seeded_session)
        assert snap.safe_state is False

    @pytest.mark.asyncio
    async def test_safe_state_false_when_system_user_missing(self, session):
        from app.services.auth_observability_service import build_auth_snapshot
        with patch("app.config.settings") as mock_s:
            mock_s.auth_enabled = False
            mock_s.supabase_project_url = ""
            mock_s.supabase_jwt_secret = ""
            snap = await build_auth_snapshot(session)
        # System user not seeded
        assert snap.system_user_present is False
        assert snap.safe_state is False

    @pytest.mark.asyncio
    async def test_safe_state_false_when_null_rows_present(self, seeded_session):
        from app.services.auth_observability_service import build_auth_snapshot
        from app.db.models import WatchedTicker

        # Add a NULL-owned row
        seeded_session.add(WatchedTicker(
            id="wt-null", user_id=None, ticker="GOOG", company_name="Alphabet", active=True,
        ))
        await seeded_session.flush()

        with patch("app.config.settings") as mock_s:
            mock_s.auth_enabled = False
            mock_s.supabase_project_url = ""
            mock_s.supabase_jwt_secret = ""
            snap = await build_auth_snapshot(seeded_session)

        assert snap.null_rows_count > 0
        assert snap.safe_state is False

    @pytest.mark.asyncio
    async def test_reasons_list_non_empty(self, seeded_session):
        from app.services.auth_observability_service import build_auth_snapshot
        snap = await build_auth_snapshot(seeded_session)
        assert len(snap.safe_state_reasons) >= 4  # one per safe-state factor

    @pytest.mark.asyncio
    async def test_reasons_contain_pass_or_fail(self, seeded_session):
        from app.services.auth_observability_service import build_auth_snapshot
        snap = await build_auth_snapshot(seeded_session)
        for reason in snap.safe_state_reasons:
            assert reason.startswith("PASS") or reason.startswith("FAIL")


# ---------------------------------------------------------------------------
# 5. TestNoSecretsExposed
# ---------------------------------------------------------------------------

class TestNoSecretsExposed:
    """Snapshot dict must never include secret values."""

    _SECRET_KEYS = {
        "supabase_jwt_secret",
        "supabase_project_url",
        "auth_bypass_user_id",
    }

    @pytest.mark.asyncio
    async def test_no_secret_keys_in_dict(self, session):
        from app.services.auth_observability_service import build_auth_snapshot, snapshot_to_dict
        snap = await build_auth_snapshot(session)
        d = snapshot_to_dict(snap)
        leaked = self._SECRET_KEYS & set(d.keys())
        assert len(leaked) == 0, f"Secret keys leaked: {leaked}"

    @pytest.mark.asyncio
    async def test_no_secret_values_exposed(self, session):
        """Even if a key maps to a non-empty value, it should be boolean flags only."""
        from app.services.auth_observability_service import build_auth_snapshot, snapshot_to_dict
        with patch("app.config.settings") as mock_s:
            mock_s.auth_enabled = False
            mock_s.supabase_project_url = "https://secret-project.supabase.co"
            mock_s.supabase_jwt_secret = "super-secret-jwt-value-12345"
            snap = await build_auth_snapshot(session)

        d = snapshot_to_dict(snap)
        # The secret values themselves must not appear anywhere in the dict
        for v in d.values():
            if isinstance(v, str):
                assert "super-secret" not in v
                assert "supabase.co" not in v

        # Only presence booleans
        assert isinstance(d["supabase_project_configured"], bool)
        assert isinstance(d["supabase_secret_configured"], bool)
        assert d["supabase_secret_configured"] is True
        assert d["supabase_project_configured"] is True


# ---------------------------------------------------------------------------
# 6. TestDbFailureDegradation
# ---------------------------------------------------------------------------

class TestDbFailureDegradation:
    """DB error sets db_available=False; snapshot is still returned."""

    @pytest.mark.asyncio
    async def test_db_error_returns_snapshot(self, session):
        from app.services.auth_observability_service import build_auth_snapshot

        # Make session.execute raise
        session.execute = AsyncMock(side_effect=RuntimeError("simulated DB error"))
        snap = await build_auth_snapshot(session)

        assert snap is not None
        assert snap.db_available is False

    @pytest.mark.asyncio
    async def test_db_error_counts_are_zero(self, session):
        from app.services.auth_observability_service import build_auth_snapshot

        session.execute = AsyncMock(side_effect=RuntimeError("simulated DB error"))
        snap = await build_auth_snapshot(session)

        assert snap.user_count == 0
        assert snap.claimed_rows_count == 0

    @pytest.mark.asyncio
    async def test_db_error_safe_state_false(self, session):
        from app.services.auth_observability_service import build_auth_snapshot

        session.execute = AsyncMock(side_effect=RuntimeError("simulated DB error"))
        snap = await build_auth_snapshot(session)
        assert snap.safe_state is False


# ---------------------------------------------------------------------------
# 7. TestAuthRoutesPresence
# ---------------------------------------------------------------------------

class TestAuthRoutesPresence:
    """Route and middleware boolean flags are accurate."""

    @pytest.mark.asyncio
    async def test_auth_middleware_present(self, session):
        from app.services.auth_observability_service import build_auth_snapshot
        snap = await build_auth_snapshot(session)
        assert snap.auth_middleware_present is True

    @pytest.mark.asyncio
    async def test_auth_routes_registered(self, session):
        from app.services.auth_observability_service import build_auth_snapshot
        snap = await build_auth_snapshot(session)
        assert snap.auth_routes_registered is True

    @pytest.mark.asyncio
    async def test_auth_middleware_false_when_missing(self, session):
        from app.services.auth_observability_service import build_auth_snapshot, _check_auth_middleware
        with patch(
            "app.services.auth_observability_service._check_auth_middleware",
            return_value=False,
        ):
            snap = await build_auth_snapshot(session)
        assert snap.auth_middleware_present is False

    @pytest.mark.asyncio
    async def test_auth_routes_false_when_missing(self, session):
        from app.services.auth_observability_service import build_auth_snapshot
        with patch(
            "app.services.auth_observability_service._check_auth_routes",
            return_value=False,
        ):
            snap = await build_auth_snapshot(session)
        assert snap.auth_routes_registered is False


# ---------------------------------------------------------------------------
# 8. TestSnapshotDict
# ---------------------------------------------------------------------------

class TestSnapshotDict:
    """snapshot_to_dict returns all required keys and JSON-serialisable values."""

    _REQUIRED_KEYS = {
        "auth_enabled", "auth_bypass", "jwt_verification_enabled",
        "supabase_project_configured", "supabase_secret_configured",
        "db_available", "system_user_present",
        "user_count", "real_user_count", "profile_count", "settings_count",
        "onboarding_by_step", "imported_users_count",
        "claimed_rows_count", "null_rows_count",
        "auth_routes_registered", "auth_middleware_present",
        "safe_state", "safe_state_reasons", "generated_at",
    }

    @pytest.mark.asyncio
    async def test_all_required_keys_present(self, session):
        from app.services.auth_observability_service import build_auth_snapshot, snapshot_to_dict
        snap = await build_auth_snapshot(session)
        d = snapshot_to_dict(snap)
        missing = self._REQUIRED_KEYS - set(d.keys())
        assert not missing, f"Missing keys: {missing}"

    @pytest.mark.asyncio
    async def test_json_serialisable(self, session):
        import json
        from app.services.auth_observability_service import build_auth_snapshot, snapshot_to_dict
        snap = await build_auth_snapshot(session)
        d = snapshot_to_dict(snap)
        # Must not raise
        serialised = json.dumps(d)
        assert serialised

    @pytest.mark.asyncio
    async def test_auth_bypass_is_inverse_of_auth_enabled(self, session):
        from app.services.auth_observability_service import build_auth_snapshot, snapshot_to_dict
        snap = await build_auth_snapshot(session)
        d = snapshot_to_dict(snap)
        assert d["auth_bypass"] == (not d["auth_enabled"])


# ---------------------------------------------------------------------------
# 9. TestAdminEndpoint
# ---------------------------------------------------------------------------

class TestAdminEndpoint:
    """GET /admin/auth-status returns 200 with expected shape."""

    def _build_app(self):
        from fastapi import FastAPI
        from app.routers.admin_auth import router

        app = FastAPI()

        @app.middleware("http")
        async def inject_state(request, call_next):
            request.state.user_id = SYSTEM_DEFAULT_USER_ID
            request.state.auth_subject = None
            request.state.is_authenticated = False
            return await call_next(request)

        app.include_router(router)
        return app

    def test_returns_200(self):
        from fastapi.testclient import TestClient
        from contextlib import asynccontextmanager
        from unittest.mock import AsyncMock, MagicMock

        def _mock_session_factory():
            mock_result = MagicMock()
            mock_result.scalars.return_value.all.return_value = []
            mock_result.all.return_value = []
            mock_result.scalar_one_or_none.return_value = None
            mock_result.scalar_one.return_value = 0

            mock_session = AsyncMock()
            mock_session.execute = AsyncMock(return_value=mock_result)

            @asynccontextmanager
            async def _ctx():
                yield mock_session

            return _ctx()

        with patch("app.db.connection.get_session", side_effect=_mock_session_factory):
            client = TestClient(self._build_app())
            resp = client.get("/admin/auth-status")

        assert resp.status_code == 200

    def test_response_has_safe_state(self):
        from fastapi.testclient import TestClient
        from contextlib import asynccontextmanager
        from unittest.mock import AsyncMock, MagicMock

        def _mock_session_factory():
            mock_result = MagicMock()
            mock_result.scalars.return_value.all.return_value = []
            mock_result.all.return_value = []
            mock_result.scalar_one_or_none.return_value = None
            mock_result.scalar_one.return_value = 0

            mock_session = AsyncMock()
            mock_session.execute = AsyncMock(return_value=mock_result)

            @asynccontextmanager
            async def _ctx():
                yield mock_session

            return _ctx()

        with patch("app.db.connection.get_session", side_effect=_mock_session_factory):
            client = TestClient(self._build_app())
            resp = client.get("/admin/auth-status")

        body = resp.json()
        assert "safe_state" in body
        assert "auth_enabled" in body
        assert "auth_bypass" in body

    def test_no_secrets_in_response(self):
        from fastapi.testclient import TestClient
        from contextlib import asynccontextmanager
        from unittest.mock import AsyncMock, MagicMock

        def _mock_session_factory():
            mock_result = MagicMock()
            mock_result.scalars.return_value.all.return_value = []
            mock_result.all.return_value = []
            mock_result.scalar_one_or_none.return_value = None
            mock_result.scalar_one.return_value = 0

            mock_session = AsyncMock()
            mock_session.execute = AsyncMock(return_value=mock_result)

            @asynccontextmanager
            async def _ctx():
                yield mock_session

            return _ctx()

        with patch("app.db.connection.get_session", side_effect=_mock_session_factory):
            client = TestClient(self._build_app())
            resp = client.get("/admin/auth-status")

        body = resp.json()
        assert "supabase_jwt_secret" not in body
        assert "supabase_project_url" not in body
        assert "auth_bypass_user_id" not in body
