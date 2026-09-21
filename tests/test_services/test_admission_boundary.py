"""Section 0.15 — controlled-beta admission boundary.

Test matrix
-----------
  1.  TestGateDefault            — unset / malformed / unknown flag behaviour
  2.  TestTrustedClaims          — what counts as a trusted identity field
  3.  TestFirstLoginApproved     — approved identity is admitted and bound
  4.  TestFirstLoginDenied       — unapproved identity denied BEFORE provisioning
  5.  TestGrantLifecycle         — expired / revoked / replayed / already-used
  6.  TestConcurrentRedemption   — atomic redemption under concurrency
  7.  TestNoEmailRebinding       — same address, different subject cannot rebind
  8.  TestMetadataCannotAdmit    — user_metadata.email influences nothing
  9.  TestAdminNonEscalation     — admin never transfers through an address
  10. TestGrandfathering         — existing identities authorised by subject
  11. TestLogSanitisation        — no raw address in INFO logs
  12. TestOperatorOutput         — aggregate counts and opaque refs only
  13. TestEstablishedAccountEnforcement
                                 — existing ordinary and admin accounts with
                                   active / missing / expired / revoked grants
                                   in off / shadow / enforce
  14. TestPepperRequired         — no locator operation without a strong pepper
"""

from __future__ import annotations

import asyncio
import logging
import pytest
import pytest_asyncio
from datetime import datetime, timedelta, timezone

SUBJECT_A = "11111111-1111-1111-1111-111111111111"
SUBJECT_B = "22222222-2222-2222-2222-222222222222"
EMAIL_A = "Person.One@example.test"
EMAIL_B = "person.two@example.test"


def claims(subject=SUBJECT_A, email=EMAIL_A, provider="google", **extra):
    payload = {
        "sub": subject,
        "aud": "authenticated",
        "app_metadata": {"provider": provider, "providers": [provider]},
        "user_metadata": {},
    }
    if email is not None:
        payload["email"] = email
    payload.update(extra)
    return payload


@pytest_asyncio.fixture
async def session():
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
    from sqlalchemy.orm import sessionmaker
    from app.db.models import Base

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as s:
        yield s
    await engine.dispose()


#: A pepper of the required strength. Test-only, not a production value.
TEST_PEPPER = "t" * 48


@pytest.fixture
def mode(monkeypatch):
    """Set the admission mode for one test, with a valid pepper configured.

    shadow/enforce cannot evaluate a locator without a pepper, so the fixture
    supplies one. The tests that assert the pepper requirement itself clear it
    deliberately.
    """
    from app.config import settings

    monkeypatch.setattr(settings, "beta_admission_pepper", TEST_PEPPER, raising=False)

    def _set(value):
        monkeypatch.setattr(settings, "beta_admission_mode", value, raising=False)
    return _set


@pytest.fixture
def pepper(monkeypatch):
    """Set or clear the pepper for one test."""
    from app.config import settings

    def _set(value):
        monkeypatch.setattr(settings, "beta_admission_pepper", value, raising=False)
    return _set


async def _user_count(session) -> int:
    from sqlalchemy import select, func
    from app.db.models import User
    return (await session.execute(select(func.count()).select_from(User))).scalar() or 0


async def _audit_actions(session) -> list:
    from sqlalchemy import select
    from app.db.models import AuditLog
    rows = (await session.execute(select(AuditLog))).scalars().all()
    return [(r.action, r.resource, r.resource_id) for r in rows]


# ---------------------------------------------------------------------------
# 1. Gate default
# ---------------------------------------------------------------------------

class TestGateDefault:
    def test_default_is_off(self):
        from app.config import Settings
        assert Settings().beta_admission_mode_normalized == "off"

    def test_unset_is_off(self):
        from app.config import resolve_admission_mode
        assert resolve_admission_mode(None) == "off"

    @pytest.mark.parametrize("value", ["", "   ", "\n", "\t "])
    def test_empty_is_off_because_that_is_how_unset_arrives(self, value):
        """An environment variable cannot express None; "" IS unset."""
        from app.config import resolve_admission_mode
        assert resolve_admission_mode(value) == "off"

    @pytest.mark.parametrize("value", [
        "ENFORCED",     # typo of a real word
        "enfore",       # plain typo
        "true", "1", "yes", "on",
        "enforce!",     # punctuation-polluted
        " shadow mode ",  # whitespace-polluted unsupported value
        "off\nenforce",   # smuggled second value
        "OFF ;",
    ])
    def test_unknown_or_malformed_fails_closed(self, value):
        """An explicitly supplied unsupported value must NOT read as "off".

        Silently degrading a typo to "off" would reopen admission while the
        operator believed the gate was on. It is a configuration error.
        """
        from app.config import AdmissionConfigError, resolve_admission_mode
        with pytest.raises(AdmissionConfigError):
            resolve_admission_mode(value)

    @pytest.mark.parametrize("value", [1, 0, True, [], {}, object()])
    def test_wrong_type_fails_closed(self, value):
        from app.config import AdmissionConfigError, resolve_admission_mode
        with pytest.raises(AdmissionConfigError):
            resolve_admission_mode(value)

    def test_error_never_discloses_the_configured_value(self):
        from app.config import AdmissionConfigError, resolve_admission_mode
        secret = "enforce-but-with-a-typo-and-a-secret"
        with pytest.raises(AdmissionConfigError) as exc:
            resolve_admission_mode(secret)
        assert secret not in str(exc.value)

    def test_startup_validation_rejects_a_bad_mode(self):
        from app.config import AdmissionConfigError, validate_admission_config

        class Bad:
            beta_admission_mode = "enfore"
            beta_admission_pepper = TEST_PEPPER

        with pytest.raises(AdmissionConfigError):
            validate_admission_config(Bad())

    @pytest.mark.asyncio
    async def test_invalid_mode_denies_at_request_time(self, session, monkeypatch):
        """Defence in depth: if a bad value ever reaches a request, deny."""
        from app.config import settings
        monkeypatch.setattr(settings, "beta_admission_mode", "enfore", raising=False)
        from app.services.supabase_auth_service import resolve_user_from_jwt
        assert await resolve_user_from_jwt(session, claims()) is None
        assert await _user_count(session) == 0

    @pytest.mark.parametrize("value,expected", [
        ("off", "off"), ("shadow", "shadow"), ("enforce", "enforce"),
        ("  ENFORCE  ", "enforce"), ("Shadow", "shadow"),
    ])
    def test_recognised_values(self, value, expected, mode):
        from app.config import settings
        mode(value)
        assert settings.beta_admission_mode_normalized == expected

    @pytest.mark.asyncio
    async def test_off_mode_still_admits_unapproved(self, session, mode):
        """Default-off preserves production behaviour: no grant needed."""
        mode("off")
        from app.services.supabase_auth_service import resolve_user_from_jwt
        user = await resolve_user_from_jwt(session, claims())
        assert user is not None
        assert user.auth_subject == SUBJECT_A

    @pytest.mark.asyncio
    async def test_shadow_mode_audits_but_admits(self, session, mode):
        mode("shadow")
        from app.services.supabase_auth_service import resolve_user_from_jwt
        user = await resolve_user_from_jwt(session, claims())
        assert user is not None
        actions = [a for (a, _r, _i) in await _audit_actions(session)]
        assert "deny" in actions, "shadow mode must record the decision it did not enforce"


# ---------------------------------------------------------------------------
# 2. Trusted claims
# ---------------------------------------------------------------------------

class TestTrustedClaims:
    def test_top_level_email_is_trusted(self):
        from app.services.access_grant_service import trusted_identity
        identity = trusted_identity(claims())
        assert identity.email == EMAIL_A.lower()
        assert identity.subject == SUBJECT_A

    def test_user_metadata_email_is_ignored(self):
        from app.services.access_grant_service import trusted_identity
        payload = claims(email=None)
        payload["user_metadata"] = {"email": "victim@example.test"}
        identity = trusted_identity(payload)
        assert identity.email == "", "user_metadata is writable by the account holder"

    def test_missing_subject_is_not_an_identity(self):
        from app.services.access_grant_service import trusted_identity
        assert trusted_identity({"email": EMAIL_A}) is None
        assert trusted_identity({"sub": "   "}) is None
        assert trusted_identity("not-a-dict") is None

    def test_provider_allow_list_is_strict(self):
        from app.services.access_grant_service import trusted_identity, provider_trusted
        assert provider_trusted(trusted_identity(claims()), allowed=["google"])
        assert not provider_trusted(trusted_identity(claims(provider="email")), allowed=["google"])
        # An extra linked provider is refused rather than admitted on its best one.
        mixed = claims()
        mixed["app_metadata"] = {"provider": "google", "providers": ["google", "email"]}
        assert not provider_trusted(trusted_identity(mixed), allowed=["google"])
        # No provider chain at all is refused.
        bare = claims()
        bare["app_metadata"] = {}
        assert not provider_trusted(trusted_identity(bare), allowed=["google"])


# ---------------------------------------------------------------------------
# 3 & 4. First login
# ---------------------------------------------------------------------------

class TestFirstLoginApproved:
    @pytest.mark.asyncio
    async def test_approved_identity_is_admitted_and_bound(self, session, mode):
        mode("enforce")
        from app.services.access_grant_service import create_invite_grant
        from app.services.supabase_auth_service import resolve_user_from_jwt

        await create_invite_grant(session, raw_email=EMAIL_A)
        user = await resolve_user_from_jwt(session, claims())

        assert user is not None
        assert user.auth_subject == SUBJECT_A
        assert user.email == EMAIL_A.lower()

    @pytest.mark.asyncio
    async def test_second_login_needs_no_second_grant(self, session, mode):
        """A repeated login reuses the bound grant; it never consumes another."""
        mode("enforce")
        from app.services.access_grant_service import create_invite_grant, grant_status_counts
        from app.services.supabase_auth_service import resolve_user_from_jwt

        await create_invite_grant(session, raw_email=EMAIL_A)
        first = await resolve_user_from_jwt(session, claims())
        assert first is not None

        again = await resolve_user_from_jwt(session, claims())
        assert again is not None and again.id == first.id
        assert await _user_count(session) == 1
        counts = await grant_status_counts(session)
        assert counts["total"] == 1 and counts["approved_redeemed"] == 1

    @pytest.mark.asyncio
    async def test_revocation_cuts_off_the_bound_account(self, session, mode):
        """Revoking after admission denies the NEXT login under enforcement.

        The account row is not deleted — revocation removes access, it does
        not un-provision.
        """
        mode("enforce")
        from app.services.access_grant_service import create_invite_grant, revoke_grant
        from app.services.supabase_auth_service import resolve_user_from_jwt

        await create_invite_grant(session, raw_email=EMAIL_A)
        first = await resolve_user_from_jwt(session, claims())
        assert first is not None

        await revoke_grant(session, subject=SUBJECT_A)
        await session.flush()

        assert await resolve_user_from_jwt(session, claims()) is None
        assert await _user_count(session) == 1, "the row survives; only access is cut"


class TestFirstLoginDenied:
    @pytest.mark.asyncio
    async def test_unapproved_denied_before_provisioning(self, session, mode):
        mode("enforce")
        from app.services.supabase_auth_service import resolve_user_from_jwt

        user = await resolve_user_from_jwt(session, claims())

        assert user is None
        assert await _user_count(session) == 0, "denial must precede provisioning"

    @pytest.mark.asyncio
    async def test_denial_writes_only_a_sanitised_audit_row(self, session, mode):
        mode("enforce")
        from app.services.supabase_auth_service import resolve_user_from_jwt
        from app.services.access_grant_service import subject_ref

        await resolve_user_from_jwt(session, claims())
        rows = await _audit_actions(session)

        assert [a for (a, _r, _i) in rows] == ["deny"]
        blob = " ".join(str(i) for (_a, _r, i) in rows)
        assert EMAIL_A.lower() not in blob and SUBJECT_A not in blob
        assert subject_ref(SUBJECT_A) in blob

    @pytest.mark.asyncio
    async def test_no_import_side_effect_on_denial(self, session, mode):
        """A denied identity gets no starter data and no profile rows."""
        mode("enforce")
        from sqlalchemy import select, func
        from app.db.models import UserProfile, WatchedTicker
        from app.services.supabase_auth_service import resolve_user_from_jwt

        await resolve_user_from_jwt(session, claims())

        profiles = (await session.execute(select(func.count()).select_from(UserProfile))).scalar()
        tickers = (await session.execute(select(func.count()).select_from(WatchedTicker))).scalar()
        assert (profiles or 0) == 0 and (tickers or 0) == 0

    @pytest.mark.asyncio
    @pytest.mark.parametrize("gate_mode", ["off", "shadow", "enforce"])
    async def test_anonymous_identity_fails_closed_in_every_mode(self, session, mode, gate_mode):
        mode(gate_mode)
        from app.services.supabase_auth_service import resolve_user_from_jwt
        payload = claims(email=None, provider="anonymous")
        payload["is_anonymous"] = True
        assert await resolve_user_from_jwt(session, payload) is None
        assert await _user_count(session) == 0

    @pytest.mark.asyncio
    @pytest.mark.parametrize("gate_mode", ["off", "shadow", "enforce"])
    async def test_missing_email_fails_closed_in_every_mode(self, session, mode, gate_mode):
        mode(gate_mode)
        from app.services.supabase_auth_service import resolve_user_from_jwt
        assert await resolve_user_from_jwt(session, claims(email=None)) is None
        assert await _user_count(session) == 0

    @pytest.mark.asyncio
    async def test_untrusted_provider_denied_under_enforcement(self, session, mode):
        mode("enforce")
        from app.services.access_grant_service import create_invite_grant
        from app.services.supabase_auth_service import resolve_user_from_jwt

        await create_invite_grant(session, raw_email=EMAIL_A)
        # Holds a valid grant, but arrives on a provider we do not trust.
        assert await resolve_user_from_jwt(session, claims(provider="email")) is None
        assert await _user_count(session) == 0


# ---------------------------------------------------------------------------
# 5. Grant lifecycle
# ---------------------------------------------------------------------------

class TestGrantLifecycle:
    @pytest.mark.asyncio
    async def test_expired_grant_denies(self, session, mode):
        mode("enforce")
        from app.services.access_grant_service import create_invite_grant
        from app.services.supabase_auth_service import resolve_user_from_jwt

        await create_invite_grant(
            session, raw_email=EMAIL_A,
            expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
        )
        assert await resolve_user_from_jwt(session, claims()) is None
        assert await _user_count(session) == 0

    @pytest.mark.asyncio
    async def test_revoked_grant_denies(self, session, mode):
        mode("enforce")
        from app.services.access_grant_service import create_invite_grant, revoke_grant
        from app.services.supabase_auth_service import resolve_user_from_jwt

        await create_invite_grant(session, raw_email=EMAIL_A)
        assert await revoke_grant(session, raw_email=EMAIL_A) == 1
        assert await resolve_user_from_jwt(session, claims()) is None
        assert await _user_count(session) == 0

    @pytest.mark.asyncio
    async def test_already_used_grant_cannot_admit_a_second_identity(self, session, mode):
        mode("enforce")
        from app.services.access_grant_service import create_invite_grant
        from app.services.supabase_auth_service import resolve_user_from_jwt

        await create_invite_grant(session, raw_email=EMAIL_A)
        assert await resolve_user_from_jwt(session, claims(subject=SUBJECT_A)) is not None

        # Same address, a different identity: the grant is spent.
        second = await resolve_user_from_jwt(
            session, claims(subject=SUBJECT_B, email=EMAIL_A)
        )
        assert second is None
        assert await _user_count(session) == 1

    @pytest.mark.asyncio
    async def test_replayed_first_login_is_idempotent(self, session, mode):
        mode("enforce")
        from app.services.access_grant_service import create_invite_grant
        from app.services.supabase_auth_service import resolve_user_from_jwt

        await create_invite_grant(session, raw_email=EMAIL_A)
        for _ in range(3):
            assert await resolve_user_from_jwt(session, claims()) is not None
        assert await _user_count(session) == 1

    @pytest.mark.asyncio
    async def test_grant_stores_no_address(self, session, pepper):
        pepper(TEST_PEPPER)
        from sqlalchemy import select
        from app.db.models import AccessGrant
        from app.services.access_grant_service import create_invite_grant

        await create_invite_grant(session, raw_email=EMAIL_A)
        row = (await session.execute(select(AccessGrant))).scalars().first()
        assert EMAIL_A.lower() not in str(row.email_locator)
        assert len(row.email_locator) == 64    # HMAC-SHA256 hex digest


# ---------------------------------------------------------------------------
# 6. Concurrency
# ---------------------------------------------------------------------------

class TestConcurrentRedemption:
    @pytest.mark.asyncio
    async def test_one_grant_admits_exactly_one_of_two_racing_identities(self, tmp_path, mode):
        mode("enforce")
        """Two different subjects redeem the same grant at once.

        A file-backed database, because each connection to an in-memory
        SQLite gets its own copy and the sessions would never contend.
        """
        from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
        from sqlalchemy.orm import sessionmaker
        from app.db.models import Base
        from app.services.access_grant_service import create_invite_grant, evaluate_admission

        engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/race.db")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        maker = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        async with maker() as setup:
            await create_invite_grant(setup, raw_email=EMAIL_A)
            await setup.commit()

        async def attempt(subject):
            async with maker() as s:
                decision = await evaluate_admission(s, claims(subject=subject))
                if decision.allowed:
                    await s.commit()
                else:
                    await s.rollback()
                return decision.allowed

        results = await asyncio.gather(
            attempt(SUBJECT_A), attempt(SUBJECT_B), return_exceptions=True
        )
        wins = [r for r in results if r is True]
        assert len(wins) == 1, f"exactly one redemption may win, got {results}"

        # And the grant is bound to precisely one subject.
        from sqlalchemy import select
        from app.db.models import AccessGrant
        async with maker() as check:
            rows = (await check.execute(select(AccessGrant))).scalars().all()
            assert len([r for r in rows if r.subject]) == 1
        await engine.dispose()


# ---------------------------------------------------------------------------
# 7 & 8. Binding invariants
# ---------------------------------------------------------------------------

class TestNoEmailRebinding:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("gate_mode", ["off", "shadow", "enforce"])
    async def test_same_address_different_subject_cannot_rebind(self, session, mode, gate_mode):
        mode(gate_mode)
        from app.services.access_grant_service import create_invite_grant
        from app.services.supabase_auth_service import resolve_user_from_jwt

        await create_invite_grant(session, raw_email=EMAIL_A)
        first = await resolve_user_from_jwt(session, claims(subject=SUBJECT_A))
        assert first is not None

        attacker = await resolve_user_from_jwt(session, claims(subject=SUBJECT_B, email=EMAIL_A))

        assert attacker is None, "an address must never rebind an existing local user"
        from app.db.repositories.account_repo import get_user
        unchanged = await get_user(session, first.id)
        assert unchanged.auth_subject == SUBJECT_A, "existing subject must never be overwritten"
        assert await _user_count(session) == 1

    @pytest.mark.asyncio
    async def test_email_collision_never_reaches_update_user(self, session, mode, monkeypatch):
        """Structural: the rebinding call site is gone, not merely guarded."""
        mode("off")
        from app.services.supabase_auth_service import resolve_user_from_jwt
        from app.db.repositories import account_repo

        await resolve_user_from_jwt(session, claims(subject=SUBJECT_A))

        called = {"n": 0}
        original = account_repo.update_user

        async def spy(*args, **kwargs):
            if "auth_subject" in kwargs:
                called["n"] += 1
            return await original(*args, **kwargs)

        monkeypatch.setattr(account_repo, "update_user", spy)
        await resolve_user_from_jwt(session, claims(subject=SUBJECT_B, email=EMAIL_A))
        assert called["n"] == 0

    def test_source_contains_no_email_binding_path(self):
        """Mutation guard: re-adding a lookup-by-email bind must fail here."""
        import inspect
        from app.services import supabase_auth_service as mod
        source = inspect.getsource(mod.resolve_user_from_jwt)
        # Tokenise away comments and docstrings so prose about the removed
        # path cannot satisfy — or break — this assertion.
        import io, tokenize
        code = []
        for tok in tokenize.generate_tokens(io.StringIO(source).readline):
            if tok.type in (tokenize.COMMENT, tokenize.STRING):
                continue
            code.append(tok.string)
        body = " ".join(code)
        assert "get_user_by_email" in body, "the conflict check itself must remain"
        assert "update_user" not in body, "no rebinding write may exist in this path"


class TestMetadataCannotAdmit:
    @pytest.mark.asyncio
    async def test_metadata_email_cannot_redeem_a_grant(self, session, mode):
        mode("enforce")
        from app.services.access_grant_service import create_invite_grant
        from app.services.supabase_auth_service import resolve_user_from_jwt

        await create_invite_grant(session, raw_email=EMAIL_A)
        payload = claims(subject=SUBJECT_B, email=None)
        payload["user_metadata"] = {"email": EMAIL_A}

        assert await resolve_user_from_jwt(session, payload) is None
        assert await _user_count(session) == 0

    @pytest.mark.asyncio
    async def test_metadata_email_cannot_target_an_existing_user(self, session, mode):
        mode("off")
        from app.services.supabase_auth_service import resolve_user_from_jwt
        first = await resolve_user_from_jwt(session, claims(subject=SUBJECT_A))
        assert first is not None

        payload = claims(subject=SUBJECT_B, email=None)
        payload["user_metadata"] = {"email": EMAIL_A}
        assert await resolve_user_from_jwt(session, payload) is None

        from app.db.repositories.account_repo import get_user
        assert (await get_user(session, first.id)).auth_subject == SUBJECT_A


# ---------------------------------------------------------------------------
# 9. Admin non-escalation
# ---------------------------------------------------------------------------

class TestAdminNonEscalation:
    @pytest.mark.asyncio
    async def test_admin_cannot_be_inherited_through_an_address(self, session, mode, monkeypatch):
        mode("off")
        from app.config import settings
        from app.services.supabase_auth_service import resolve_user_from_jwt
        from app.security.authz import is_admin

        admin_user = await resolve_user_from_jwt(session, claims(subject=SUBJECT_A))
        monkeypatch.setattr(settings, "admin_user_ids", admin_user.id, raising=False)
        assert is_admin(admin_user.id)

        # A second identity claiming the admin's address gets nothing at all.
        attacker = await resolve_user_from_jwt(session, claims(subject=SUBJECT_B, email=EMAIL_A))
        assert attacker is None
        assert not is_admin(SUBJECT_B)

    def test_admin_requires_a_bound_identity(self, monkeypatch):
        from fastapi import HTTPException
        from app.config import settings
        from app.security import authz

        class State:
            user_id = SUBJECT_A
            auth_subject = None          # no bound subject on this request
            is_authenticated = True
            admission_denied = False

        class Req:
            state = State()

        monkeypatch.setattr(settings, "auth_enabled", True, raising=False)
        monkeypatch.setattr(settings, "admin_user_ids", SUBJECT_A, raising=False)
        with pytest.raises(HTTPException) as exc:
            authz.require_admin(Req())
        assert exc.value.status_code == 403

    def test_bypass_mode_operator_is_still_admin(self, monkeypatch):
        from app.config import settings
        from app.security import authz
        monkeypatch.setattr(settings, "auth_enabled", False, raising=False)

        class Req:
            class state:
                user_id = "00000000-0000-0000-0000-000000000001"
                auth_subject = None
                is_authenticated = False
                admission_denied = False

        assert authz.require_admin(Req()) == "00000000-0000-0000-0000-000000000001"


# ---------------------------------------------------------------------------
# 10. Grandfathering
# ---------------------------------------------------------------------------

class TestGrandfathering:
    @pytest.mark.asyncio
    async def test_existing_identities_are_authorised_by_subject(self, session, mode):
        mode("off")
        from app.services.supabase_auth_service import resolve_user_from_jwt
        from app.services.access_grant_service import (
            grandfather_existing_subjects, grant_status_counts,
        )

        await resolve_user_from_jwt(session, claims(subject=SUBJECT_A, email=EMAIL_A))
        await resolve_user_from_jwt(session, claims(subject=SUBJECT_B, email=EMAIL_B))

        result = await grandfather_existing_subjects(session)
        assert result["granted"] == 2 and result["examined"] == 2

        counts = await grant_status_counts(session)
        assert counts["subject_grants"] == 2 and counts["invite_grants"] == 0

        # Re-running is idempotent.
        again = await grandfather_existing_subjects(session)
        assert again["granted"] == 0 and again["already_granted"] == 2

    @pytest.mark.asyncio
    async def test_grandfathered_identity_passes_enforcement(self, session, mode):
        mode("off")
        from app.services.supabase_auth_service import resolve_user_from_jwt
        from app.services.access_grant_service import grandfather_existing_subjects

        existing = await resolve_user_from_jwt(session, claims())
        await grandfather_existing_subjects(session)

        # Flip the gate on: the established identity still resolves by subject.
        from app.config import settings
        settings.beta_admission_mode = "enforce"
        assert (await resolve_user_from_jwt(session, claims())).id == existing.id

    @pytest.mark.asyncio
    async def test_unbound_rows_are_skipped_not_granted(self, session):
        """Authorisation is never derived from an address."""
        from app.db.repositories.account_repo import create_user
        from app.services.access_grant_service import grandfather_existing_subjects

        await create_user(session, user_id="legacy-row", email="legacy@example.test",
                          account_type="individual")
        result = await grandfather_existing_subjects(session)
        assert result["granted"] == 0 and result["skipped_unbound"] == 1


# ---------------------------------------------------------------------------
# 11 & 12. Sanitised output
# ---------------------------------------------------------------------------

class TestLogSanitisation:
    @pytest.mark.asyncio
    async def test_no_address_or_subject_in_info_logs(self, session, mode, caplog):
        mode("enforce")
        from app.services.access_grant_service import create_invite_grant
        from app.services.supabase_auth_service import resolve_user_from_jwt

        with caplog.at_level(logging.INFO):
            await create_invite_grant(session, raw_email=EMAIL_A)
            await resolve_user_from_jwt(session, claims())                  # admitted
            await resolve_user_from_jwt(session, claims(subject=SUBJECT_B,
                                                       email=EMAIL_B))     # denied

        text = "\n".join(r.getMessage() for r in caplog.records)
        assert EMAIL_A.lower() not in text.lower()
        assert EMAIL_B.lower() not in text.lower()
        assert SUBJECT_A not in text and SUBJECT_B not in text
        assert "subject_ref=" in text

    def test_source_has_no_email_log_interpolation(self):
        import inspect
        from app.services import supabase_auth_service as mod
        source = inspect.getsource(mod)
        for line in source.splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if "logger.info" in stripped:
                assert "email" not in stripped


class TestOperatorOutput:
    @pytest.mark.asyncio
    async def test_status_counts_are_aggregate_only(self, session, pepper):
        pepper(TEST_PEPPER)
        from app.services.access_grant_service import create_invite_grant, grant_status_counts
        await create_invite_grant(session, raw_email=EMAIL_A)
        counts = await grant_status_counts(session)
        assert set(counts) == {
            "total", "approved_pending", "approved_redeemed", "revoked",
            "expired_pending", "subject_grants", "invite_grants",
        }
        assert all(isinstance(v, int) for v in counts.values())

    def test_cli_takes_no_address_argument(self):
        import inspect
        import scripts.beta_admission as cli
        source = inspect.getsource(cli)
        assert "getpass" in source, "addresses must come from a masked prompt"
        assert '"--email"' not in source and "'--email'" not in source

    def test_subject_ref_is_one_way_and_short(self):
        from app.services.access_grant_service import subject_ref
        ref = subject_ref(SUBJECT_A)
        assert SUBJECT_A not in ref and len(ref) == 12
        assert ref == subject_ref(SUBJECT_A) != subject_ref(SUBJECT_B)


# ---------------------------------------------------------------------------
# 13. Enforcement and revocation for ESTABLISHED accounts
# ---------------------------------------------------------------------------

async def _establish(session, subject=SUBJECT_A, email=EMAIL_A):
    """Create an ordinary, subject-bound account the way a first login does."""
    from app.config import settings
    from app.services.supabase_auth_service import resolve_user_from_jwt
    before = settings.beta_admission_mode
    settings.beta_admission_mode = "off"
    try:
        user = await resolve_user_from_jwt(session, claims(subject=subject, email=email))
    finally:
        settings.beta_admission_mode = before
    assert user is not None
    return user


async def _grant_state(session, subject, state):
    """Put this subject's grant into `state`: active | missing | expired | revoked."""
    from app.services.access_grant_service import (
        create_subject_grant, revoke_grant, STATUS_APPROVED,
    )
    from sqlalchemy import select
    from app.db.models import AccessGrant

    if state == "missing":
        return
    await create_subject_grant(session, subject=subject)
    if state == "active":
        return
    row = (await session.execute(
        select(AccessGrant).where(AccessGrant.subject == subject)
    )).scalars().first()
    if state == "expired":
        row.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        row.status = STATUS_APPROVED
    elif state == "revoked":
        await revoke_grant(session, subject=subject)
    await session.flush()


class TestEstablishedAccountEnforcement:
    """The account the gate most needs to be able to cut off is an existing one.

    An earlier revision returned a subject-bound user before consulting any
    grant, so revocation did nothing under enforcement. These tests pin the
    corrected semantics across all three modes.
    """

    @pytest.mark.asyncio
    @pytest.mark.parametrize("state", ["active", "missing", "expired", "revoked"])
    async def test_off_mode_never_denies_an_established_account(self, session, mode, state):
        user = await _establish(session)
        await _grant_state(session, SUBJECT_A, state)
        mode("off")

        from app.services.supabase_auth_service import resolve_user_from_jwt
        again = await resolve_user_from_jwt(session, claims())
        assert again is not None and again.id == user.id

    @pytest.mark.asyncio
    @pytest.mark.parametrize("state", ["active", "missing", "expired", "revoked"])
    async def test_shadow_mode_evaluates_but_never_denies(self, session, mode, state):
        user = await _establish(session)
        await _grant_state(session, SUBJECT_A, state)
        mode("shadow")

        from app.services.supabase_auth_service import resolve_user_from_jwt
        again = await resolve_user_from_jwt(session, claims())
        assert again is not None and again.id == user.id

        actions = [a for (a, _r, _i) in await _audit_actions(session)]
        if state == "active":
            assert "deny" not in actions
        else:
            assert "deny" in actions, "shadow must produce evidence it would have denied"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("state,admitted", [
        ("active", True), ("missing", False), ("expired", False), ("revoked", False),
    ])
    async def test_enforce_mode_requires_a_live_bound_grant(self, session, mode, state, admitted):
        user = await _establish(session)
        await _grant_state(session, SUBJECT_A, state)
        mode("enforce")

        from app.services.supabase_auth_service import resolve_user_from_jwt
        result = await resolve_user_from_jwt(session, claims())

        if admitted:
            assert result is not None and result.id == user.id
        else:
            assert result is None, f"{state} grant must deny an established account"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("state", ["missing", "expired", "revoked"])
    async def test_denial_mutates_no_user_data(self, session, mode, state):
        """Denial writes nothing about the user — not even a sign-in stamp."""
        from sqlalchemy import select, func
        from app.db.models import User, WatchedTicker, Portfolio, AuditLog
        from app.db.repositories.account_repo import get_user

        user = await _establish(session)
        await _grant_state(session, SUBJECT_A, state)
        await session.flush()

        before = await get_user(session, user.id)
        before_sign_in = before.last_sign_in_at
        before_subject = before.auth_subject
        before_email = before.email
        before_users = (await session.execute(select(func.count()).select_from(User))).scalar()

        mode("enforce")
        from app.services.supabase_auth_service import resolve_user_from_jwt
        assert await resolve_user_from_jwt(session, claims()) is None

        after = await get_user(session, user.id)
        assert after.last_sign_in_at == before_sign_in, "no sign-in stamp on denial"
        assert after.auth_subject == before_subject, "no rebinding on denial"
        assert after.email == before_email
        assert (await session.execute(select(func.count()).select_from(User))).scalar() == before_users
        # No starter data was imported on the way out.
        assert (await session.execute(select(func.count()).select_from(WatchedTicker))).scalar() in (0, None)
        assert (await session.execute(select(func.count()).select_from(Portfolio))).scalar() in (0, None)
        # The only trace of the login attempt is the sanitised denial event.
        rows = (await session.execute(select(AuditLog))).scalars().all()
        assert [r.action for r in rows][-1] == "deny"
        assert len([r for r in rows if r.action == "deny"]) == 1
        assert EMAIL_A.lower() not in " ".join(str(r.resource_id) for r in rows)

    @pytest.mark.asyncio
    async def test_admin_does_not_bypass_enforcement(self, session, mode, monkeypatch):
        """Admin is an ordinary human identity to this gate.

        No emergency-access bypass exists, deliberately: one is not invented
        here, and if it is ever wanted it must be designed and approved.
        """
        from app.config import settings
        from app.security.authz import is_admin

        admin_user = await _establish(session)
        monkeypatch.setattr(settings, "admin_user_ids", admin_user.id, raising=False)
        assert is_admin(admin_user.id), "precondition: this really is the admin"

        await _grant_state(session, SUBJECT_A, "revoked")
        mode("enforce")

        from app.services.supabase_auth_service import resolve_user_from_jwt
        assert await resolve_user_from_jwt(session, claims()) is None

    @pytest.mark.asyncio
    async def test_grandfathering_is_what_makes_enforcement_survivable(self, session, mode):
        """The documented rollout prerequisite, proven rather than asserted."""
        from app.services.access_grant_service import grandfather_existing_subjects
        from app.services.supabase_auth_service import resolve_user_from_jwt

        user = await _establish(session)
        mode("enforce")
        assert await resolve_user_from_jwt(session, claims()) is None, (
            "without grandfathering, enforcement locks out existing accounts"
        )

        mode("off")
        result = await grandfather_existing_subjects(session)
        assert result["granted"] == 1
        await session.flush()

        mode("enforce")
        again = await resolve_user_from_jwt(session, claims())
        assert again is not None and again.id == user.id

    @pytest.mark.asyncio
    async def test_system_identity_exemption_is_narrow(self, session, mode):
        """Only the system sentinel is exempt — not admins, not anyone else."""
        from app.services.supabase_auth_service import (
            SYSTEM_DEFAULT_USER_ID, resolve_user_from_jwt,
        )
        from app.db.repositories.account_repo import create_user

        await create_user(
            session, user_id=SYSTEM_DEFAULT_USER_ID, email="system@clearsignal.internal",
            account_type="system", auth_subject=SYSTEM_DEFAULT_USER_ID,
        )
        await _establish(session, subject=SUBJECT_B, email=EMAIL_B)
        await session.flush()
        mode("enforce")

        system = await resolve_user_from_jwt(
            session, claims(subject=SYSTEM_DEFAULT_USER_ID, email="system@clearsignal.internal"),
        )
        assert system is not None, "the product's own identity is exempt"

        # An ordinary account with no grant is not.
        assert await resolve_user_from_jwt(session, claims(subject=SUBJECT_B, email=EMAIL_B)) is None


# ---------------------------------------------------------------------------
# 14. Pepper is mandatory wherever a locator is involved
# ---------------------------------------------------------------------------

class TestPepperRequired:
    @pytest.mark.parametrize("value", [None, "", "   ", "short", "x" * 31, 12345])
    def test_locator_refuses_without_a_strong_pepper(self, value, pepper):
        from app.config import AdmissionConfigError
        from app.services.access_grant_service import email_locator
        pepper(value)
        with pytest.raises(AdmissionConfigError):
            email_locator(EMAIL_A)

    def test_minimum_length_is_enforced_exactly(self, pepper):
        from app.config import ADMISSION_PEPPER_MIN_LENGTH
        from app.services.access_grant_service import email_locator
        pepper("y" * ADMISSION_PEPPER_MIN_LENGTH)
        assert len(email_locator(EMAIL_A)) == 64

    def test_no_unkeyed_fallback_exists_in_source(self):
        """Mutation guard: a default key must not creep back in."""
        import inspect
        from app.services import access_grant_service as mod
        source = inspect.getsource(mod.email_locator)
        assert "clearsignal-admission" not in source
        assert "admission_pepper_ok" in source

    def test_different_peppers_give_different_locators(self, pepper):
        from app.services.access_grant_service import email_locator
        pepper("a" * 40)
        first = email_locator(EMAIL_A)
        pepper("b" * 40)
        assert email_locator(EMAIL_A) != first

    @pytest.mark.asyncio
    async def test_grant_creation_refuses_without_a_pepper(self, session, pepper):
        from app.config import AdmissionConfigError
        from app.services.access_grant_service import create_invite_grant
        pepper("")
        with pytest.raises(AdmissionConfigError):
            await create_invite_grant(session, raw_email=EMAIL_A)

    def test_off_mode_starts_without_a_pepper(self):
        from app.config import validate_admission_config

        class Cfg:
            beta_admission_mode = "off"
            beta_admission_pepper = ""

        assert validate_admission_config(Cfg()) == "off"

    @pytest.mark.parametrize("gate_mode", ["shadow", "enforce"])
    def test_locator_modes_fail_startup_without_a_pepper(self, gate_mode):
        from app.config import AdmissionConfigError, validate_admission_config

        class Cfg:
            beta_admission_mode = gate_mode
            beta_admission_pepper = "too-short"

        with pytest.raises(AdmissionConfigError) as exc:
            validate_admission_config(Cfg())
        assert "too-short" not in str(exc.value), "never echo the configured value"

    @pytest.mark.asyncio
    async def test_missing_pepper_denies_rather_than_admits(self, session, mode, pepper):
        """A locator that cannot be computed is a denial, never a free pass."""
        from app.services.access_grant_service import create_invite_grant
        from app.services.supabase_auth_service import resolve_user_from_jwt

        await create_invite_grant(session, raw_email=EMAIL_A)   # fixture pepper
        mode("enforce")
        pepper("")                                             # then lose it
        assert await resolve_user_from_jwt(session, claims()) is None
        assert await _user_count(session) == 0
