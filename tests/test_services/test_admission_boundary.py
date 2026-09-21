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


@pytest.fixture
def mode(monkeypatch):
    """Set the admission mode for one test."""
    from app.config import settings

    def _set(value):
        monkeypatch.setattr(settings, "beta_admission_mode", value, raising=False)
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

    @pytest.mark.parametrize("value", ["", "   ", "ENFORCED", "true", "1", "yes",
                                       "enforce!", "shadow mode", "off\n"])
    def test_malformed_and_unknown_resolve_to_off(self, value, mode):
        from app.config import settings
        mode(value)
        # Deliberate choice: an unreadable flag PRESERVES CURRENT BEHAVIOUR.
        # It must never silently enforce (locking out approved operators) and
        # never silently loosen anything beyond today's behaviour.
        assert settings.beta_admission_mode_normalized == "off"

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
    async def test_second_login_resolves_by_subject_without_a_grant(self, session, mode):
        mode("enforce")
        from app.services.access_grant_service import create_invite_grant, revoke_grant
        from app.services.supabase_auth_service import resolve_user_from_jwt

        await create_invite_grant(session, raw_email=EMAIL_A)
        first = await resolve_user_from_jwt(session, claims())
        assert first is not None

        # Even a later revocation does not un-provision; resolution is by sub.
        await revoke_grant(session, subject=SUBJECT_A)
        again = await resolve_user_from_jwt(session, claims())
        assert again is not None and again.id == first.id
        assert await _user_count(session) == 1


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
    async def test_grant_stores_no_address(self, session):
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
    async def test_one_grant_admits_exactly_one_of_two_racing_identities(self, tmp_path):
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
    async def test_status_counts_are_aggregate_only(self, session):
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
