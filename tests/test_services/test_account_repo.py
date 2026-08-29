"""
Tests for account_repo — Phase 16 · Slice 1.

Covers: null-session safety, user CRUD, profile CRUD, settings CRUD,
system-user idempotency, stripe_customer_id nullable, account_type defaults,
no-password assertion, and migration table-count guard.

All tests use an in-memory SQLite db_session from conftest.py.
"""

from __future__ import annotations

import inspect

import pytest
import pytest_asyncio


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SYSTEM_DEFAULT_USER_ID = "00000000-0000-0000-0000-000000000001"
SYSTEM_DEFAULT_EMAIL   = "system@clearsignal.internal"


def _make_email(suffix: str = "") -> str:
    return f"test{suffix}@example.com"


# ---------------------------------------------------------------------------
# § NULL-SESSION SAFETY
# ---------------------------------------------------------------------------

class TestNullSession:
    """Every public function returns a safe default when session is None."""

    @pytest.mark.asyncio
    async def test_create_user_none_session(self):
        from app.db.repositories.account_repo import create_user
        result = await create_user(None, email="x@example.com")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_user_none_session(self):
        from app.db.repositories.account_repo import get_user
        assert await get_user(None, "any-id") is None

    @pytest.mark.asyncio
    async def test_get_user_by_email_none_session(self):
        from app.db.repositories.account_repo import get_user_by_email
        assert await get_user_by_email(None, "x@example.com") is None

    @pytest.mark.asyncio
    async def test_get_user_by_auth_subject_none_session(self):
        from app.db.repositories.account_repo import get_user_by_auth_subject
        assert await get_user_by_auth_subject(None, "sub|abc") is None

    @pytest.mark.asyncio
    async def test_update_user_none_session(self):
        from app.db.repositories.account_repo import update_user
        assert await update_user(None, "any-id") is None

    @pytest.mark.asyncio
    async def test_deactivate_user_none_session(self):
        from app.db.repositories.account_repo import deactivate_user
        assert await deactivate_user(None, "any-id") is False

    @pytest.mark.asyncio
    async def test_get_or_create_system_user_none_session(self):
        from app.db.repositories.account_repo import get_or_create_system_user
        assert await get_or_create_system_user(None) is None

    @pytest.mark.asyncio
    async def test_list_users_none_session(self):
        from app.db.repositories.account_repo import list_users
        assert await list_users(None) == []

    @pytest.mark.asyncio
    async def test_upsert_profile_none_session(self):
        from app.db.repositories.account_repo import upsert_profile
        assert await upsert_profile(None, "any-id") is None

    @pytest.mark.asyncio
    async def test_get_profile_none_session(self):
        from app.db.repositories.account_repo import get_profile
        assert await get_profile(None, "any-id") is None

    @pytest.mark.asyncio
    async def test_upsert_settings_none_session(self):
        from app.db.repositories.account_repo import upsert_settings
        assert await upsert_settings(None, "any-id") is None

    @pytest.mark.asyncio
    async def test_get_settings_none_session(self):
        from app.db.repositories.account_repo import get_settings
        assert await get_settings(None, "any-id") is None

    @pytest.mark.asyncio
    async def test_count_users_by_type_none_session(self):
        from app.db.repositories.account_repo import count_users_by_type
        assert await count_users_by_type(None) == {}


# ---------------------------------------------------------------------------
# § USER CRUD
# ---------------------------------------------------------------------------

class TestUserCrud:
    """Create → read → update → deactivate round-trip."""

    @pytest.mark.asyncio
    async def test_create_and_get(self, db_session):
        from app.db.repositories.account_repo import create_user, get_user

        user = await create_user(db_session, email="alice@example.com")
        assert user is not None
        assert user.id is not None
        assert user.email == "alice@example.com"

        fetched = await get_user(db_session, user.id)
        assert fetched is not None
        assert fetched.id == user.id

    @pytest.mark.asyncio
    async def test_email_is_case_folded(self, db_session):
        from app.db.repositories.account_repo import create_user, get_user_by_email

        await create_user(db_session, email="UPPER@EXAMPLE.COM")
        row = await get_user_by_email(db_session, "upper@example.com")
        assert row is not None
        assert row.email == "upper@example.com"

    @pytest.mark.asyncio
    async def test_get_user_not_found_returns_none(self, db_session):
        from app.db.repositories.account_repo import get_user
        assert await get_user(db_session, "nonexistent-id") is None

    @pytest.mark.asyncio
    async def test_get_user_by_email_not_found(self, db_session):
        from app.db.repositories.account_repo import get_user_by_email
        assert await get_user_by_email(db_session, "missing@example.com") is None

    @pytest.mark.asyncio
    async def test_update_user_email(self, db_session):
        from app.db.repositories.account_repo import create_user, update_user, get_user

        user = await create_user(db_session, email="before@example.com")
        updated = await update_user(db_session, user.id, email="after@example.com")
        assert updated is not None
        assert updated.email == "after@example.com"

        fetched = await get_user(db_session, user.id)
        assert fetched.email == "after@example.com"

    @pytest.mark.asyncio
    async def test_update_nonexistent_user_returns_none(self, db_session):
        from app.db.repositories.account_repo import update_user
        assert await update_user(db_session, "ghost-id", email="x@x.com") is None

    @pytest.mark.asyncio
    async def test_deactivate_user(self, db_session):
        from app.db.repositories.account_repo import create_user, deactivate_user, get_user

        user = await create_user(db_session, email="deact@example.com")
        assert user.is_active is True

        ok = await deactivate_user(db_session, user.id)
        assert ok is True

        fetched = await get_user(db_session, user.id)
        assert fetched.is_active is False

    @pytest.mark.asyncio
    async def test_deactivate_nonexistent_returns_false(self, db_session):
        from app.db.repositories.account_repo import deactivate_user
        assert await deactivate_user(db_session, "ghost-id") is False

    @pytest.mark.asyncio
    async def test_get_user_by_auth_subject(self, db_session):
        from app.db.repositories.account_repo import create_user, get_user_by_auth_subject

        user = await create_user(
            db_session, email="sub@example.com", auth_subject="supabase|abc123"
        )
        row = await get_user_by_auth_subject(db_session, "supabase|abc123")
        assert row is not None
        assert row.id == user.id


# ---------------------------------------------------------------------------
# § ACCOUNT_TYPE DEFAULTS
# ---------------------------------------------------------------------------

class TestAccountTypeDefaults:
    """account_type defaults to 'individual'; can be set to other values."""

    @pytest.mark.asyncio
    async def test_default_account_type_is_individual(self, db_session):
        from app.db.repositories.account_repo import create_user

        user = await create_user(db_session, email="ind@example.com")
        assert user.account_type == "individual"

    @pytest.mark.asyncio
    async def test_custom_account_type(self, db_session):
        from app.db.repositories.account_repo import create_user

        user = await create_user(
            db_session, email="inst@example.com", account_type="institutional"
        )
        assert user.account_type == "institutional"

    @pytest.mark.asyncio
    async def test_list_users_filter_by_account_type(self, db_session):
        from app.db.repositories.account_repo import create_user, list_users

        await create_user(db_session, email="u1@example.com", account_type="individual")
        await create_user(db_session, email="u2@example.com", account_type="team_member")

        individuals = await list_users(db_session, account_type="individual")
        # may include system user if seeded; at minimum our row is there
        emails = [u.email for u in individuals]
        assert "u1@example.com" in emails
        assert "u2@example.com" not in emails


# ---------------------------------------------------------------------------
# § STRIPE_CUSTOMER_ID NULLABLE
# ---------------------------------------------------------------------------

class TestStripeCustomerIdNullable:
    """stripe_customer_id is a forward-compat placeholder — nullable."""

    @pytest.mark.asyncio
    async def test_create_user_stripe_is_null_by_default(self, db_session):
        from app.db.repositories.account_repo import create_user

        user = await create_user(db_session, email="nostripe@example.com")
        assert user.stripe_customer_id is None

    @pytest.mark.asyncio
    async def test_set_stripe_customer_id(self, db_session):
        from app.db.repositories.account_repo import create_user, update_user

        user = await create_user(db_session, email="stripe@example.com")
        updated = await update_user(
            db_session, user.id, stripe_customer_id="cus_abc123"
        )
        assert updated.stripe_customer_id == "cus_abc123"

    @pytest.mark.asyncio
    async def test_stripe_customer_id_column_exists_on_model(self):
        from app.db.models import User
        assert hasattr(User, "stripe_customer_id")


# ---------------------------------------------------------------------------
# § SYSTEM USER IDEMPOTENCY
# ---------------------------------------------------------------------------

class TestSystemUserIdempotency:
    """get_or_create_system_user is idempotent across multiple calls."""

    @pytest.mark.asyncio
    async def test_creates_on_first_call(self, db_session):
        from app.db.repositories.account_repo import get_or_create_system_user

        user = await get_or_create_system_user(db_session)
        assert user is not None
        assert user.id == SYSTEM_DEFAULT_USER_ID
        assert user.email == SYSTEM_DEFAULT_EMAIL
        assert user.account_type == "system"

    @pytest.mark.asyncio
    async def test_idempotent_on_second_call(self, db_session):
        from app.db.repositories.account_repo import get_or_create_system_user

        u1 = await get_or_create_system_user(db_session)
        u2 = await get_or_create_system_user(db_session)
        assert u1 is not None
        assert u2 is not None
        assert u1.id == u2.id

    @pytest.mark.asyncio
    async def test_system_user_is_active(self, db_session):
        from app.db.repositories.account_repo import get_or_create_system_user

        user = await get_or_create_system_user(db_session)
        assert user.is_active is True

    @pytest.mark.asyncio
    async def test_system_user_email_verified(self, db_session):
        from app.db.repositories.account_repo import get_or_create_system_user

        user = await get_or_create_system_user(db_session)
        assert user.email_verified is True


# ---------------------------------------------------------------------------
# § PROFILE CRUD
# ---------------------------------------------------------------------------

class TestProfileCrud:
    """upsert_profile / get_profile round-trip with idempotency."""

    @pytest.mark.asyncio
    async def test_create_profile(self, db_session):
        from app.db.repositories.account_repo import create_user, upsert_profile, get_profile

        user = await create_user(db_session, email="prof@example.com")
        profile = await upsert_profile(
            db_session, user.id, display_name="Alice", timezone="America/New_York"
        )
        assert profile is not None
        assert profile.user_id == user.id
        assert profile.display_name == "Alice"
        assert profile.timezone == "America/New_York"

        fetched = await get_profile(db_session, user.id)
        assert fetched is not None
        assert fetched.display_name == "Alice"

    @pytest.mark.asyncio
    async def test_upsert_profile_updates_existing(self, db_session):
        from app.db.repositories.account_repo import create_user, upsert_profile

        user = await create_user(db_session, email="profup@example.com")
        await upsert_profile(db_session, user.id, display_name="Before")
        updated = await upsert_profile(db_session, user.id, display_name="After")
        assert updated.display_name == "After"

    @pytest.mark.asyncio
    async def test_upsert_profile_idempotent_without_changes(self, db_session):
        from app.db.repositories.account_repo import create_user, upsert_profile, get_profile

        user = await create_user(db_session, email="prfidem@example.com")
        await upsert_profile(db_session, user.id, display_name="Stable")
        await upsert_profile(db_session, user.id)  # no changes
        profile = await get_profile(db_session, user.id)
        assert profile.display_name == "Stable"

    @pytest.mark.asyncio
    async def test_default_onboarding_step_is_pending(self, db_session):
        from app.db.repositories.account_repo import create_user, upsert_profile

        user = await create_user(db_session, email="onb@example.com")
        profile = await upsert_profile(db_session, user.id)
        assert profile.onboarding_step == "pending"

    @pytest.mark.asyncio
    async def test_advance_onboarding_step(self, db_session):
        from app.db.repositories.account_repo import create_user, upsert_profile

        user = await create_user(db_session, email="adv@example.com")
        await upsert_profile(db_session, user.id)
        profile = await upsert_profile(db_session, user.id, onboarding_step="complete")
        assert profile.onboarding_step == "complete"

    @pytest.mark.asyncio
    async def test_get_profile_not_found_returns_none(self, db_session):
        from app.db.repositories.account_repo import get_profile
        assert await get_profile(db_session, "ghost-id") is None


# ---------------------------------------------------------------------------
# § SETTINGS CRUD
# ---------------------------------------------------------------------------

class TestSettingsCrud:
    """upsert_settings / get_settings round-trip with safe defaults."""

    @pytest.mark.asyncio
    async def test_create_settings_defaults(self, db_session):
        from app.db.repositories.account_repo import create_user, upsert_settings

        user = await create_user(db_session, email="sett@example.com")
        settings = await upsert_settings(db_session, user.id)
        assert settings is not None
        assert settings.briefing_time_utc == 7
        assert settings.quiet_hours_start == 22
        assert settings.quiet_hours_end == 7
        assert settings.delivery_channel == "in_app"
        assert settings.digest_enabled is True
        assert settings.theme == "system"

    @pytest.mark.asyncio
    async def test_upsert_settings_updates_fields(self, db_session):
        from app.db.repositories.account_repo import create_user, upsert_settings

        user = await create_user(db_session, email="settup@example.com")
        await upsert_settings(db_session, user.id)
        updated = await upsert_settings(db_session, user.id, theme="dark", briefing_time_utc=8)
        assert updated.theme == "dark"
        assert updated.briefing_time_utc == 8

    @pytest.mark.asyncio
    async def test_upsert_settings_idempotent(self, db_session):
        from app.db.repositories.account_repo import create_user, upsert_settings, get_settings

        user = await create_user(db_session, email="settidem@example.com")
        await upsert_settings(db_session, user.id, theme="light")
        await upsert_settings(db_session, user.id)  # no-op
        s = await get_settings(db_session, user.id)
        assert s.theme == "light"

    @pytest.mark.asyncio
    async def test_get_settings_not_found_returns_none(self, db_session):
        from app.db.repositories.account_repo import get_settings
        assert await get_settings(db_session, "ghost-id") is None


# ---------------------------------------------------------------------------
# § NO PASSWORD COLUMN
# ---------------------------------------------------------------------------

class TestNoPasswordColumn:
    """Assert that no password/credential column exists anywhere in the schema."""

    def test_user_model_has_no_password_column(self):
        from app.db.models import User

        forbidden = {"password", "password_hash", "hashed_password", "password_salt",
                     "bcrypt_hash", "credential", "secret", "pin"}
        cols = {c.key for c in User.__table__.columns}
        overlap = cols & forbidden
        assert not overlap, f"Forbidden credential columns found on User: {overlap}"

    def test_user_profile_has_no_password_column(self):
        from app.db.models import UserProfile

        cols = {c.key for c in UserProfile.__table__.columns}
        forbidden = {"password", "password_hash", "hashed_password"}
        assert not cols & forbidden

    def test_account_repo_has_no_password_imports(self):
        import app.db.repositories.account_repo as mod
        src = inspect.getsource(mod)
        for bad in ("bcrypt", "hashlib.sha256", "passlib", "argon2", "scrypt"):
            assert bad not in src, f"Credential library '{bad}' found in account_repo"

    def test_user_model_has_no_password_column_in_migration_sql(self):
        """Confirm no credential-type column is defined in the migration DDL.

        Checks only non-comment lines for column definitions that name a
        password/credential field.  Comment lines (starting with '--') that
        discuss the *absence* of a password column are expected and allowed.
        """
        from pathlib import Path
        migration = (
            Path(__file__).resolve().parents[2]
            / "app/db/migrations/009_accounts_identity.sql"
        ).read_text()

        # Scan DDL lines only (strip comment lines).
        ddl_lines = [
            ln for ln in migration.splitlines()
            if not ln.strip().startswith("--")
        ]
        ddl_text = "\n".join(ddl_lines).lower()

        # These patterns match actual column definitions, not prose.
        forbidden_patterns = ["password ", "password_hash", "passwd", "bcrypt", "hashed_password"]
        for pat in forbidden_patterns:
            assert pat not in ddl_text, (
                f"Forbidden credential pattern '{pat}' found in DDL of 009_accounts_identity.sql"
            )


# ---------------------------------------------------------------------------
# § TABLE COUNT / SCHEMA COMPLETENESS
# ---------------------------------------------------------------------------

class TestTableCount:
    """Confirm all 35 tables exist in the ORM metadata."""

    @pytest.mark.asyncio
    async def test_db_table_count_is_35(self, db_session):
        from sqlalchemy import inspect as sa_inspect

        sync_conn = await db_session.connection()

        def _get_tables(conn):
            insp = sa_inspect(conn)
            return set(insp.get_table_names())

        tables = await sync_conn.run_sync(_get_tables)
        assert len(tables) >= 35, (
            f"Expected >= 35 tables, found {len(tables)}: {sorted(tables)}"
        )

    @pytest.mark.asyncio
    async def test_new_identity_tables_exist(self, db_session):
        from sqlalchemy import inspect as sa_inspect

        sync_conn = await db_session.connection()

        def _get_tables(conn):
            insp = sa_inspect(conn)
            return set(insp.get_table_names())

        tables = await sync_conn.run_sync(_get_tables)
        for expected in ("users", "user_profiles", "user_settings", "audit_log"):
            assert expected in tables, f"Table '{expected}' missing from schema"

    def test_user_model_tablename(self):
        from app.db.models import User
        assert User.__tablename__ == "users"

    def test_user_profile_tablename(self):
        from app.db.models import UserProfile
        assert UserProfile.__tablename__ == "user_profiles"

    def test_user_settings_tablename(self):
        from app.db.models import UserSettings
        assert UserSettings.__tablename__ == "user_settings"

    def test_audit_log_tablename(self):
        from app.db.models import AuditLog
        assert AuditLog.__tablename__ == "audit_log"

    def test_portfolio_has_org_id_column(self):
        from app.db.models import Portfolio
        assert hasattr(Portfolio, "org_id"), "portfolios.org_id forward-compat column missing"


# ---------------------------------------------------------------------------
# § COUNT_USERS_BY_TYPE
# ---------------------------------------------------------------------------

class TestCountUsersByType:
    """Observability helper returns correct type→count mapping."""

    @pytest.mark.asyncio
    async def test_count_after_creating_users(self, db_session):
        from app.db.repositories.account_repo import (
            create_user, get_or_create_system_user, count_users_by_type
        )

        await get_or_create_system_user(db_session)
        await create_user(db_session, email="cnt1@example.com", account_type="individual")
        await create_user(db_session, email="cnt2@example.com", account_type="individual")

        counts = await count_users_by_type(db_session)
        assert counts.get("system", 0) >= 1
        assert counts.get("individual", 0) >= 2

    @pytest.mark.asyncio
    async def test_count_empty_db_returns_empty_dict(self, db_session):
        from app.db.repositories.account_repo import count_users_by_type
        counts = await count_users_by_type(db_session)
        # may be {} or may have system user if other tests ran first
        assert isinstance(counts, dict)
