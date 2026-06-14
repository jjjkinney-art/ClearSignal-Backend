"""
Tests for app/services/onboarding_service.py — Phase 16 · Slice 7.

Test matrix:
  1.  TestNullSessionSafety      — all functions return safe defaults when session=None
  2.  TestGetOnboardingState     — read current state; pending alias; missing profile
  3.  TestAdvanceStep            — sequential step progression
  4.  TestAdvanceStepIdempotent  — advance at terminal is a no-op
  5.  TestCompleteStep           — jump to onboarding_complete from any step
  6.  TestSetStep                — explicit step write; unknown step raises
  7.  TestInvalidStep            — set_step rejects unknown names
  8.  TestMarkImportCompleted    — only advances up to import_completed; no-op past it
  9.  TestImportServiceHook      — execute_import drives onboarding to import_completed
  10. TestCompletedAt            — onboarding_completed_at stamped at terminal
  11. TestStateDataclass         — OnboardingState fields are consistent
"""

from __future__ import annotations

import asyncio
import pytest
import pytest_asyncio

SYSTEM_DEFAULT_USER_ID = "00000000-0000-0000-0000-000000000001"
USER_A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
USER_B = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"

STEPS = [
    "account_created",
    "auth_verified",
    "import_offered",
    "import_completed",
    "onboarding_complete",
]


# ---------------------------------------------------------------------------
# Shared SQLite fixture
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
    """Session with system-owned starter data for import integration tests."""
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
    from sqlalchemy.orm import sessionmaker
    from app.db.models import Base, WatchedTicker, Portfolio, PortfolioPosition

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as s:
        s.add(WatchedTicker(
            id="wt-sys-1", user_id=SYSTEM_DEFAULT_USER_ID,
            ticker="AAPL", company_name="Apple", active=True,
        ))
        s.add(Portfolio(
            id="po-sys-1", user_id=SYSTEM_DEFAULT_USER_ID,
            name="My Portfolio", is_default=True,
        ))
        s.add(PortfolioPosition(
            id="pos-sys-1", portfolio_id="po-sys-1",
            ticker="AAPL", membership_class="watchlist", active=True,
        ))
        await s.commit()
        yield s

    await engine.dispose()


# ---------------------------------------------------------------------------
# 1. TestNullSessionSafety
# ---------------------------------------------------------------------------

class TestNullSessionSafety:
    """All functions return safe defaults (not raise) when session is None."""

    def _run(self, coro):
        return asyncio.get_event_loop().run_until_complete(coro)

    def test_get_returns_empty_state(self):
        from app.services.onboarding_service import get_onboarding_state
        state = self._run(get_onboarding_state(None, USER_A))
        assert state.step == "account_created"
        assert state.is_complete is False

    def test_advance_returns_empty_state(self):
        from app.services.onboarding_service import advance_step
        state = self._run(advance_step(None, USER_A))
        assert state.step == "account_created"

    def test_complete_returns_empty_state(self):
        from app.services.onboarding_service import complete_step
        state = self._run(complete_step(None, USER_A))
        # Null session → empty state (not terminal)
        assert state.user_id == USER_A

    def test_set_step_returns_empty_state(self):
        from app.services.onboarding_service import set_step
        state = self._run(set_step(None, USER_A, "auth_verified"))
        assert state.step == "account_created"

    def test_mark_import_completed_returns_empty_state(self):
        from app.services.onboarding_service import mark_import_completed
        state = self._run(mark_import_completed(None, USER_A))
        assert state.step == "account_created"


# ---------------------------------------------------------------------------
# 2. TestGetOnboardingState
# ---------------------------------------------------------------------------

class TestGetOnboardingState:
    """get_onboarding_state reads profile row correctly."""

    @pytest.mark.asyncio
    async def test_no_profile_returns_account_created(self, session):
        from app.services.onboarding_service import get_onboarding_state
        state = await get_onboarding_state(session, USER_A)
        assert state.step == "account_created"
        assert state.step_index == 0
        assert state.is_complete is False

    @pytest.mark.asyncio
    async def test_pending_alias_maps_to_account_created(self, session):
        """DB value 'pending' (model default) is presented as account_created."""
        from app.db.models import UserProfile
        session.add(UserProfile(user_id=USER_A, onboarding_step="pending"))
        await session.flush()

        from app.services.onboarding_service import get_onboarding_state
        state = await get_onboarding_state(session, USER_A)
        assert state.step == "account_created"

    @pytest.mark.asyncio
    async def test_reads_stored_step(self, session):
        from app.db.models import UserProfile
        session.add(UserProfile(user_id=USER_A, onboarding_step="auth_verified"))
        await session.flush()

        from app.services.onboarding_service import get_onboarding_state
        state = await get_onboarding_state(session, USER_A)
        assert state.step == "auth_verified"
        assert state.step_index == 1

    @pytest.mark.asyncio
    async def test_next_step_populated(self, session):
        from app.db.models import UserProfile
        session.add(UserProfile(user_id=USER_A, onboarding_step="import_offered"))
        await session.flush()

        from app.services.onboarding_service import get_onboarding_state
        state = await get_onboarding_state(session, USER_A)
        assert state.next_step == "import_completed"

    @pytest.mark.asyncio
    async def test_next_step_none_at_terminal(self, session):
        from app.db.models import UserProfile
        session.add(UserProfile(user_id=USER_A, onboarding_step="onboarding_complete"))
        await session.flush()

        from app.services.onboarding_service import get_onboarding_state
        state = await get_onboarding_state(session, USER_A)
        assert state.next_step is None
        assert state.is_complete is True


# ---------------------------------------------------------------------------
# 3. TestAdvanceStep
# ---------------------------------------------------------------------------

class TestAdvanceStep:
    """advance_step moves through the sequence one at a time."""

    @pytest.mark.asyncio
    async def test_advance_from_no_profile(self, session):
        """Advancing with no profile creates profile at auth_verified."""
        from app.services.onboarding_service import advance_step, get_onboarding_state
        state = await advance_step(session, USER_A)
        assert state.step == "auth_verified"

    @pytest.mark.asyncio
    async def test_advance_from_account_created(self, session):
        from app.db.models import UserProfile
        session.add(UserProfile(user_id=USER_A, onboarding_step="account_created"))
        await session.flush()

        from app.services.onboarding_service import advance_step
        state = await advance_step(session, USER_A)
        assert state.step == "auth_verified"

    @pytest.mark.asyncio
    async def test_advance_full_sequence(self, session):
        """Advancing from account_created through to onboarding_complete."""
        from app.services.onboarding_service import advance_step, get_onboarding_state, set_step

        await set_step(session, USER_A, "account_created")
        for expected in [
            "auth_verified",
            "import_offered",
            "import_completed",
            "onboarding_complete",
        ]:
            state = await advance_step(session, USER_A)
            assert state.step == expected

    @pytest.mark.asyncio
    async def test_advance_persists_to_db(self, session):
        from app.db.models import UserProfile
        from sqlalchemy import select
        from app.services.onboarding_service import set_step, advance_step

        await set_step(session, USER_A, "account_created")
        await advance_step(session, USER_A)

        profile = (await session.execute(
            select(UserProfile).where(UserProfile.user_id == USER_A)
        )).scalar_one()
        assert profile.onboarding_step == "auth_verified"


# ---------------------------------------------------------------------------
# 4. TestAdvanceStepIdempotent
# ---------------------------------------------------------------------------

class TestAdvanceStepIdempotent:
    """advance_step at terminal is a no-op."""

    @pytest.mark.asyncio
    async def test_advance_at_terminal_no_op(self, session):
        from app.services.onboarding_service import complete_step, advance_step

        await complete_step(session, USER_A)
        state = await advance_step(session, USER_A)
        assert state.step == "onboarding_complete"
        assert state.is_complete is True

    @pytest.mark.asyncio
    async def test_advance_twice_same_step_no_duplicate(self, session):
        """Two advances from auth_verified → import_offered only once."""
        from app.services.onboarding_service import set_step, advance_step

        await set_step(session, USER_A, "auth_verified")
        state1 = await advance_step(session, USER_A)
        assert state1.step == "import_offered"

        # Already at import_offered; advance again
        state2 = await advance_step(session, USER_A)
        assert state2.step == "import_completed"


# ---------------------------------------------------------------------------
# 5. TestCompleteStep
# ---------------------------------------------------------------------------

class TestCompleteStep:
    """complete_step jumps directly to onboarding_complete."""

    @pytest.mark.asyncio
    async def test_complete_from_any_step(self, session):
        from app.services.onboarding_service import set_step, complete_step

        for step in STEPS[:-1]:
            await set_step(session, USER_A, step)
            state = await complete_step(session, USER_A)
            assert state.step == "onboarding_complete"
            assert state.is_complete is True

    @pytest.mark.asyncio
    async def test_complete_idempotent(self, session):
        from app.services.onboarding_service import complete_step

        state1 = await complete_step(session, USER_A)
        state2 = await complete_step(session, USER_A)
        assert state1.step == state2.step == "onboarding_complete"

    @pytest.mark.asyncio
    async def test_complete_persists(self, session):
        from app.db.models import UserProfile
        from sqlalchemy import select
        from app.services.onboarding_service import complete_step

        await complete_step(session, USER_A)

        profile = (await session.execute(
            select(UserProfile).where(UserProfile.user_id == USER_A)
        )).scalar_one()
        assert profile.onboarding_step == "onboarding_complete"


# ---------------------------------------------------------------------------
# 6. TestSetStep
# ---------------------------------------------------------------------------

class TestSetStep:
    """set_step writes any valid step name directly."""

    @pytest.mark.asyncio
    async def test_set_each_step(self, session):
        from app.services.onboarding_service import set_step, get_onboarding_state

        for step in STEPS:
            state = await set_step(session, USER_A, step)
            assert state.step == step

    @pytest.mark.asyncio
    async def test_set_same_step_is_noop(self, session):
        from app.services.onboarding_service import set_step

        state1 = await set_step(session, USER_A, "auth_verified")
        state2 = await set_step(session, USER_A, "auth_verified")
        assert state1.step == state2.step == "auth_verified"

    @pytest.mark.asyncio
    async def test_set_lower_step_allowed(self, session):
        """Admin can reset step to an earlier value."""
        from app.services.onboarding_service import set_step

        await set_step(session, USER_A, "import_completed")
        state = await set_step(session, USER_A, "auth_verified")
        assert state.step == "auth_verified"


# ---------------------------------------------------------------------------
# 7. TestInvalidStep
# ---------------------------------------------------------------------------

class TestInvalidStep:
    """set_step raises ValueError for unknown step names."""

    @pytest.mark.asyncio
    async def test_unknown_step_raises(self, session):
        from app.services.onboarding_service import set_step

        with pytest.raises(ValueError, match="unknown onboarding step"):
            await set_step(session, USER_A, "wizard_complete")

    @pytest.mark.asyncio
    async def test_empty_string_raises(self, session):
        from app.services.onboarding_service import set_step

        with pytest.raises(ValueError):
            await set_step(session, USER_A, "")

    @pytest.mark.asyncio
    async def test_pending_alias_rejected_by_set_step(self, session):
        """'pending' is a DB alias; set_step should not accept it as a named step."""
        from app.services.onboarding_service import set_step

        with pytest.raises(ValueError):
            await set_step(session, USER_A, "pending")


# ---------------------------------------------------------------------------
# 8. TestMarkImportCompleted
# ---------------------------------------------------------------------------

class TestMarkImportCompleted:
    """mark_import_completed advances to import_completed; no-op past it."""

    @pytest.mark.asyncio
    async def test_advances_from_import_offered(self, session):
        from app.services.onboarding_service import set_step, mark_import_completed

        await set_step(session, USER_A, "import_offered")
        state = await mark_import_completed(session, USER_A)
        assert state.step == "import_completed"

    @pytest.mark.asyncio
    async def test_advances_from_earlier_step(self, session):
        """Even at auth_verified, mark_import_completed jumps to import_completed."""
        from app.services.onboarding_service import set_step, mark_import_completed

        await set_step(session, USER_A, "auth_verified")
        state = await mark_import_completed(session, USER_A)
        assert state.step == "import_completed"

    @pytest.mark.asyncio
    async def test_noop_when_already_import_completed(self, session):
        from app.services.onboarding_service import set_step, mark_import_completed

        await set_step(session, USER_A, "import_completed")
        state = await mark_import_completed(session, USER_A)
        assert state.step == "import_completed"

    @pytest.mark.asyncio
    async def test_noop_when_onboarding_complete(self, session):
        """Does not regress back from onboarding_complete."""
        from app.services.onboarding_service import complete_step, mark_import_completed

        await complete_step(session, USER_A)
        state = await mark_import_completed(session, USER_A)
        assert state.step == "onboarding_complete"


# ---------------------------------------------------------------------------
# 9. TestImportServiceHook
# ---------------------------------------------------------------------------

class TestImportServiceHook:
    """execute_import drives onboarding to import_completed."""

    @pytest.mark.asyncio
    async def test_execute_import_advances_onboarding(self, seeded_session):
        from app.services.account_import_service import execute_import
        from app.services.onboarding_service import get_onboarding_state

        await execute_import(seeded_session, USER_A)

        state = await get_onboarding_state(seeded_session, USER_A)
        assert state.step == "import_completed"

    @pytest.mark.asyncio
    async def test_second_import_does_not_regress_onboarding(self, seeded_session):
        """Import already done; onboarding stays at import_completed (or later)."""
        from app.services.account_import_service import execute_import
        from app.services.onboarding_service import get_onboarding_state, complete_step

        await execute_import(seeded_session, USER_A)
        # User completes onboarding
        await complete_step(seeded_session, USER_A)

        # Rollback + re-import (simulated by calling import again — no-op)
        await execute_import(seeded_session, USER_A)  # already_imported → no hook

        state = await get_onboarding_state(seeded_session, USER_A)
        assert state.step == "onboarding_complete"  # not regressed

    @pytest.mark.asyncio
    async def test_import_hook_only_advances_not_regresses(self, seeded_session):
        """If onboarding is already at onboarding_complete, import hook is a no-op."""
        from app.services.onboarding_service import complete_step, set_step
        from app.services.account_import_service import execute_import, rollback_import
        from app.services.onboarding_service import get_onboarding_state

        # Set user to already complete
        await set_step(seeded_session, USER_A, "onboarding_complete")

        # Import + rollback so we can call execute_import fresh
        await execute_import(seeded_session, USER_A)

        state = await get_onboarding_state(seeded_session, USER_A)
        assert state.step == "onboarding_complete"  # not rolled back


# ---------------------------------------------------------------------------
# 10. TestCompletedAt
# ---------------------------------------------------------------------------

class TestCompletedAt:
    """onboarding_completed_at is stamped exactly once at terminal."""

    @pytest.mark.asyncio
    async def test_completed_at_none_before_terminal(self, session):
        from app.services.onboarding_service import set_step, get_onboarding_state

        await set_step(session, USER_A, "import_completed")
        state = await get_onboarding_state(session, USER_A)
        assert state.completed_at is None

    @pytest.mark.asyncio
    async def test_completed_at_stamped_at_terminal(self, session):
        from app.services.onboarding_service import complete_step, get_onboarding_state

        await complete_step(session, USER_A)
        state = await get_onboarding_state(session, USER_A)
        assert state.completed_at is not None

    @pytest.mark.asyncio
    async def test_completed_at_not_overwritten_on_second_complete(self, session):
        """Calling complete_step twice preserves the original timestamp."""
        from app.services.onboarding_service import complete_step, get_onboarding_state
        import asyncio as _asyncio

        await complete_step(session, USER_A)
        state1 = await get_onboarding_state(session, USER_A)
        ts1 = state1.completed_at

        await _asyncio.sleep(0.01)
        await complete_step(session, USER_A)
        state2 = await get_onboarding_state(session, USER_A)
        assert state2.completed_at == ts1  # unchanged


# ---------------------------------------------------------------------------
# 11. TestStateDataclass
# ---------------------------------------------------------------------------

class TestStateDataclass:
    """OnboardingState fields are internally consistent."""

    @pytest.mark.asyncio
    async def test_step_index_matches_steps_list(self, session):
        from app.services.onboarding_service import set_step, get_onboarding_state

        for i, step in enumerate(STEPS):
            await set_step(session, USER_A, step)
            state = await get_onboarding_state(session, USER_A)
            assert state.step_index == i

    @pytest.mark.asyncio
    async def test_is_complete_only_at_terminal(self, session):
        from app.services.onboarding_service import set_step, get_onboarding_state

        for step in STEPS[:-1]:
            await set_step(session, USER_A, step)
            state = await get_onboarding_state(session, USER_A)
            assert state.is_complete is False

        await set_step(session, USER_A, "onboarding_complete")
        state = await get_onboarding_state(session, USER_A)
        assert state.is_complete is True

    @pytest.mark.asyncio
    async def test_next_step_sequence_correct(self, session):
        from app.services.onboarding_service import set_step, get_onboarding_state

        for i, step in enumerate(STEPS[:-1]):
            await set_step(session, USER_A, step)
            state = await get_onboarding_state(session, USER_A)
            assert state.next_step == STEPS[i + 1]

    @pytest.mark.asyncio
    async def test_user_id_preserved(self, session):
        from app.services.onboarding_service import get_onboarding_state

        state = await get_onboarding_state(session, USER_B)
        assert state.user_id == USER_B
