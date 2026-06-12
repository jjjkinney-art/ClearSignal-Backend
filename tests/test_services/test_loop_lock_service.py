"""
Phase 10A · Slice 2 — Lock service tests.

Covers all seven failure modes specified in the plan:
  1. Happy path                  — acquire → renew → release
  2. Concurrent acquisition      — two holders racing; exactly one wins
  3. Lease expiry reclaim        — expired lock can be taken by a new holder
  4. Fence token monotonicity    — each acquire increments the token
  5. Stale owner rejection       — zombie renew and release are rejected
  6. Release correctness         — release deletes only the matching row
  7. Double release safety       — second release on same (holder, token) is a no-op

Plus:
  - null session → safe default (no exception)
  - reap_expired_locks removes all expired rows
  - is_lock_free / get_lock_state observability
  - fence_check validates (holder, token) pair
  - multiple independent locks coexist

Uses the db_session fixture (in-memory SQLite) from conftest.py.
No scheduler, no jobs, no delivery — Slice 2 is locking only.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.services import loop_lock_service as svc


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _holder(name: str = "w") -> str:
    """Stable worker identity string."""
    return f"{name}:12345:{uuid.uuid4().hex[:8]}"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _past(seconds: int = 60) -> datetime:
    return _now() - timedelta(seconds=seconds)


async def _force_expire(db_session, lock_name: str) -> None:
    """Back-date the lease so the lock appears expired."""
    from sqlalchemy import update
    from app.db.models import JobLock
    await db_session.execute(
        update(JobLock)
        .where(JobLock.lock_name == lock_name)
        .values(lease_expires_utc=_past(120))
        .execution_options(synchronize_session=False)
    )
    await db_session.flush()


# ---------------------------------------------------------------------------
# 1. Happy path — acquire → renew → release
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_acquire_returns_fence_token(db_session):
    """Successful acquire returns an integer fence_token ≥ 1."""
    token = await svc.acquire_lock(db_session, "loop:tick", _holder("w1"))
    assert isinstance(token, int)
    assert token >= 1


@pytest.mark.asyncio
async def test_acquire_renew_release_cycle(db_session):
    """Full happy-path: acquire → renew → release all succeed."""
    holder = _holder("w1")
    lock = "loop:tick"

    token = await svc.acquire_lock(db_session, lock, holder, lease_s=120)
    assert token is not None

    renewed = await svc.renew_lock(db_session, lock, holder, token, lease_s=120)
    assert renewed is True

    released = await svc.release_lock(db_session, lock, holder, token)
    assert released is True


@pytest.mark.asyncio
async def test_lock_free_after_release(db_session):
    """Lock is free after release."""
    holder = _holder("w1")
    lock = "loop:cleanup"

    token = await svc.acquire_lock(db_session, lock, holder)
    assert token is not None
    await svc.release_lock(db_session, lock, holder, token)

    assert await svc.is_lock_free(db_session, lock) is True


@pytest.mark.asyncio
async def test_get_lock_state_after_acquire(db_session):
    """get_lock_state returns correct fields after acquire."""
    holder = _holder("w1")
    lock = "loop:job:abc"

    token = await svc.acquire_lock(db_session, lock, holder, lease_s=120)
    state = await svc.get_lock_state(db_session, lock)

    assert state is not None
    assert state["lock_name"] == lock
    assert state["holder_id"] == holder
    assert state["fence_token"] == token
    assert state["is_expired"] is False


# ---------------------------------------------------------------------------
# 2. Concurrent acquisition — two holders, exactly one wins
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_second_holder_cannot_steal_active_lock(db_session):
    """A second holder cannot acquire a lock held by a first with a valid lease."""
    holder_a = _holder("w1")
    holder_b = _holder("w2")
    lock = "loop:tick"

    token_a = await svc.acquire_lock(db_session, lock, holder_a, lease_s=120)
    assert token_a is not None

    token_b = await svc.acquire_lock(db_session, lock, holder_b, lease_s=120)
    assert token_b is None  # backed off — lock is held


@pytest.mark.asyncio
async def test_only_one_winner_among_sequential_acquirers(db_session):
    """
    Simulate K sequential acquire calls from different holders.
    Exactly one returns a token; the rest get None.
    (Sequential here; true concurrency tested on Postgres in staging.)
    """
    lock = "loop:tick"
    holders = [_holder(f"w{i}") for i in range(5)]

    results = []
    for h in holders:
        t = await svc.acquire_lock(db_session, lock, h, lease_s=120)
        results.append(t)

    winners = [t for t in results if t is not None]
    losers  = [t for t in results if t is None]

    assert len(winners) == 1, f"Expected exactly 1 winner, got {len(winners)}: {results}"
    assert len(losers) == 4


@pytest.mark.asyncio
async def test_same_holder_can_re_acquire(db_session):
    """The same holder can re-acquire its own active lock (token increments)."""
    holder = _holder("w1")
    lock = "loop:tick"

    token1 = await svc.acquire_lock(db_session, lock, holder, lease_s=120)
    assert token1 is not None

    token2 = await svc.acquire_lock(db_session, lock, holder, lease_s=120)
    assert token2 is not None
    assert token2 == token1 + 1  # token incremented on re-acquire


# ---------------------------------------------------------------------------
# 3. Lease expiry reclaim
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_expired_lock_can_be_claimed_by_new_holder(db_session):
    """After lease expiry a new holder can take the lock."""
    holder_a = _holder("w1")
    holder_b = _holder("w2")
    lock = "loop:tick"

    token_a = await svc.acquire_lock(db_session, lock, holder_a, lease_s=120)
    assert token_a is not None

    # Simulate expiry
    await _force_expire(db_session, lock)

    token_b = await svc.acquire_lock(db_session, lock, holder_b, lease_s=120)
    assert token_b is not None  # new holder acquired the expired lock


@pytest.mark.asyncio
async def test_is_lock_free_returns_true_after_expiry(db_session):
    """is_lock_free returns True when the lease has expired."""
    holder = _holder("w1")
    lock = "loop:job:xyz"

    await svc.acquire_lock(db_session, lock, holder, lease_s=120)
    await _force_expire(db_session, lock)

    assert await svc.is_lock_free(db_session, lock) is True


@pytest.mark.asyncio
async def test_reap_expired_locks_removes_expired_rows(db_session):
    """reap_expired_locks() deletes expired rows and returns their names."""
    holders = [(_holder(f"w{i}"), f"loop:reap:{i}") for i in range(3)]

    for holder, lock in holders:
        await svc.acquire_lock(db_session, lock, holder, lease_s=120)
        await _force_expire(db_session, lock)

    reclaimed = await svc.reap_expired_locks(db_session)

    assert len(reclaimed) == 3
    for _, lock in holders:
        assert lock in reclaimed
        assert await svc.is_lock_free(db_session, lock) is True


@pytest.mark.asyncio
async def test_reap_does_not_touch_active_locks(db_session):
    """reap_expired_locks() leaves active (non-expired) locks untouched."""
    active_holder = _holder("w1")
    active_lock   = "loop:active"
    expired_lock  = "loop:expired"

    await svc.acquire_lock(db_session, active_lock, active_holder, lease_s=300)
    await svc.acquire_lock(db_session, expired_lock, _holder("w2"), lease_s=120)
    await _force_expire(db_session, expired_lock)

    reclaimed = await svc.reap_expired_locks(db_session)

    assert expired_lock in reclaimed
    assert active_lock not in reclaimed
    # Active lock row still present
    state = await svc.get_lock_state(db_session, active_lock)
    assert state is not None
    assert state["holder_id"] == active_holder


# ---------------------------------------------------------------------------
# 4. Fence token monotonicity
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_fence_token_starts_at_1(db_session):
    """First acquire of a fresh lock always returns token = 1."""
    token = await svc.acquire_lock(db_session, "loop:fresh", _holder("w1"))
    assert token == 1


@pytest.mark.asyncio
async def test_fence_token_increments_on_each_acquire(db_session):
    """Each successful acquire increments the fence_token by 1 (crash-recovery path)."""
    holder = _holder("w1")
    lock = "loop:monotonic"

    token1 = await svc.acquire_lock(db_session, lock, holder)
    assert token1 == 1

    # Simulate crash (lease expires without release) — row stays, token preserved
    await _force_expire(db_session, lock)

    token2 = await svc.acquire_lock(db_session, lock, holder)
    assert token2 == 2

    await _force_expire(db_session, lock)

    token3 = await svc.acquire_lock(db_session, lock, holder)
    assert token3 == 3


@pytest.mark.asyncio
async def test_fence_token_increments_on_expiry_reclaim(db_session):
    """
    When a new holder reclaims an expired lock, the token increments
    (does not reset to 1) — each acquisition is a distinct lease generation.
    """
    lock    = "loop:generations"
    holder1 = _holder("w1")
    holder2 = _holder("w2")

    token1 = await svc.acquire_lock(db_session, lock, holder1)
    assert token1 == 1

    await _force_expire(db_session, lock)

    token2 = await svc.acquire_lock(db_session, lock, holder2)
    assert token2 == 2  # incremented, not reset

    await _force_expire(db_session, lock)

    holder3 = _holder("w3")
    token3 = await svc.acquire_lock(db_session, lock, holder3)
    assert token3 == 3  # monotonically increasing across holders


@pytest.mark.asyncio
async def test_fence_check_validates_holder_and_token(db_session):
    """fence_check() returns True only for the exact (holder, token) pair."""
    holder = _holder("w1")
    lock   = "loop:fence-check"

    token = await svc.acquire_lock(db_session, lock, holder)

    assert await svc.fence_check(db_session, lock, holder, token) is True
    assert await svc.fence_check(db_session, lock, holder, token + 1) is False  # wrong token
    assert await svc.fence_check(db_session, lock, _holder("impostor"), token) is False


@pytest.mark.asyncio
async def test_fence_check_false_after_reclaim(db_session):
    """fence_check() rejects the original holder's token after the lock was reclaimed."""
    lock    = "loop:zombie-check"
    holder1 = _holder("w1")
    holder2 = _holder("w2")

    token1 = await svc.acquire_lock(db_session, lock, holder1)

    await _force_expire(db_session, lock)
    token2 = await svc.acquire_lock(db_session, lock, holder2)
    assert token2 == token1 + 1

    # holder1's original token is now stale
    assert await svc.fence_check(db_session, lock, holder1, token1) is False
    # holder2's token is valid
    assert await svc.fence_check(db_session, lock, holder2, token2) is True


# ---------------------------------------------------------------------------
# 5. Stale owner rejection (zombie protection)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_zombie_renew_rejected_after_reclaim(db_session):
    """
    A zombie holder that resumes after its lease was reclaimed cannot
    renew the lease — the fence_token mismatch is the guard.
    """
    lock    = "loop:zombie-renew"
    zombie  = _holder("zombie")
    new_owner = _holder("new")

    zombie_token = await svc.acquire_lock(db_session, lock, zombie, lease_s=120)

    await _force_expire(db_session, lock)
    await svc.acquire_lock(db_session, lock, new_owner, lease_s=120)

    # Zombie resumes and tries to renew with stale token
    renewed = await svc.renew_lock(db_session, lock, zombie, zombie_token, lease_s=120)
    assert renewed is False


@pytest.mark.asyncio
async def test_zombie_release_rejected_after_reclaim(db_session):
    """
    A zombie holder that tries to release a lock it no longer owns is
    silently rejected — the new holder remains unaffected.
    """
    lock      = "loop:zombie-release"
    zombie    = _holder("zombie")
    new_owner = _holder("new")

    zombie_token = await svc.acquire_lock(db_session, lock, zombie, lease_s=120)

    await _force_expire(db_session, lock)
    new_token = await svc.acquire_lock(db_session, lock, new_owner, lease_s=120)
    assert new_token is not None

    # Zombie tries to release with stale token
    released = await svc.release_lock(db_session, lock, zombie, zombie_token)
    assert released is False  # zombie's release is a no-op

    # New owner's lock is untouched
    state = await svc.get_lock_state(db_session, lock)
    assert state is not None
    assert state["holder_id"] == new_owner
    assert state["fence_token"] == new_token


@pytest.mark.asyncio
async def test_wrong_holder_renew_rejected(db_session):
    """A holder that never acquired the lock cannot renew it."""
    lock         = "loop:wrong-holder-renew"
    real_holder  = _holder("real")
    fake_holder  = _holder("fake")

    token = await svc.acquire_lock(db_session, lock, real_holder)

    # Fake holder knows the correct token (e.g. read it from logs) but holder_id differs
    renewed = await svc.renew_lock(db_session, lock, fake_holder, token, lease_s=120)
    assert renewed is False


@pytest.mark.asyncio
async def test_wrong_holder_release_rejected(db_session):
    """A holder that never acquired the lock cannot release it."""
    lock         = "loop:wrong-holder-release"
    real_holder  = _holder("real")
    fake_holder  = _holder("fake")

    token = await svc.acquire_lock(db_session, lock, real_holder)

    released = await svc.release_lock(db_session, lock, fake_holder, token)
    assert released is False

    # Real holder's lock survives
    state = await svc.get_lock_state(db_session, lock)
    assert state is not None
    assert state["holder_id"] == real_holder


# ---------------------------------------------------------------------------
# 6. Release correctness
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_release_removes_row(db_session):
    """Release deletes the row; the lock is free afterwards."""
    holder = _holder("w1")
    lock   = "loop:release-row"

    token = await svc.acquire_lock(db_session, lock, holder)
    assert token is not None

    released = await svc.release_lock(db_session, lock, holder, token)
    assert released is True

    state = await svc.get_lock_state(db_session, lock)
    assert state is None  # row gone


@pytest.mark.asyncio
async def test_release_only_removes_matching_lock(db_session):
    """Releasing one lock does not disturb a sibling lock."""
    holder = _holder("w1")

    t1 = await svc.acquire_lock(db_session, "loop:sibling-a", holder)
    t2 = await svc.acquire_lock(db_session, "loop:sibling-b", holder)

    await svc.release_lock(db_session, "loop:sibling-a", holder, t1)

    assert await svc.get_lock_state(db_session, "loop:sibling-a") is None  # gone
    sibling_b = await svc.get_lock_state(db_session, "loop:sibling-b")
    assert sibling_b is not None  # untouched
    assert sibling_b["fence_token"] == t2


@pytest.mark.asyncio
async def test_after_release_new_holder_can_acquire(db_session):
    """After the holder releases, a different holder can immediately acquire."""
    lock      = "loop:release-reacquire"
    holder_a  = _holder("w1")
    holder_b  = _holder("w2")

    t_a = await svc.acquire_lock(db_session, lock, holder_a)
    await svc.release_lock(db_session, lock, holder_a, t_a)

    t_b = await svc.acquire_lock(db_session, lock, holder_b)
    assert t_b is not None
    # After a clean release (row deleted), next acquire does a fresh INSERT — starts at 1.
    # Token monotonicity across crash-recovery cycles is tested separately.
    assert t_b >= 1


# ---------------------------------------------------------------------------
# 7. Double release safety (idempotent release)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_double_release_is_safe(db_session):
    """Releasing the same (holder, token) twice is safe — second is a no-op."""
    holder = _holder("w1")
    lock   = "loop:double-release"

    token = await svc.acquire_lock(db_session, lock, holder)

    first  = await svc.release_lock(db_session, lock, holder, token)
    second = await svc.release_lock(db_session, lock, holder, token)

    assert first  is True   # first release succeeded
    assert second is False  # second: row already gone, no error raised


@pytest.mark.asyncio
async def test_release_on_nonexistent_lock_is_safe(db_session):
    """release_lock() on a lock that was never acquired returns False without error."""
    result = await svc.release_lock(
        db_session, "loop:nonexistent", _holder("w1"), fence_token=42
    )
    assert result is False


@pytest.mark.asyncio
async def test_renew_on_nonexistent_lock_returns_false(db_session):
    """renew_lock() on a lock that doesn't exist returns False without error."""
    result = await svc.renew_lock(
        db_session, "loop:nonexistent", _holder("w1"), fence_token=1, lease_s=120
    )
    assert result is False


# ---------------------------------------------------------------------------
# Null-session safety
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_acquire_null_session_returns_none():
    """acquire_lock(session=None) returns None without raising."""
    result = await svc.acquire_lock(None, "loop:tick", _holder("w1"))
    assert result is None


@pytest.mark.asyncio
async def test_renew_null_session_returns_false():
    result = await svc.renew_lock(None, "loop:tick", _holder("w1"), fence_token=1)
    assert result is False


@pytest.mark.asyncio
async def test_release_null_session_returns_false():
    result = await svc.release_lock(None, "loop:tick", _holder("w1"), fence_token=1)
    assert result is False


@pytest.mark.asyncio
async def test_get_lock_state_null_session_returns_none():
    result = await svc.get_lock_state(None, "loop:tick")
    assert result is None


@pytest.mark.asyncio
async def test_reap_null_session_returns_empty():
    result = await svc.reap_expired_locks(None)
    assert result == []


@pytest.mark.asyncio
async def test_fence_check_null_session_returns_false():
    result = await svc.fence_check(None, "loop:tick", _holder("w1"), fence_token=1)
    assert result is False


@pytest.mark.asyncio
async def test_is_lock_free_null_session_returns_true():
    """Null session → assume free (safe default — callers may proceed)."""
    result = await svc.is_lock_free(None, "loop:tick")
    assert result is True


# ---------------------------------------------------------------------------
# Multiple independent locks coexist
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_multiple_independent_locks(db_session):
    """
    Multiple locks with different names are fully independent.
    Acquiring or releasing one has no effect on others.
    """
    holder = _holder("w1")
    locks = [f"loop:job:{uuid.uuid4().hex[:6]}" for _ in range(4)]

    tokens = {}
    for lock in locks:
        t = await svc.acquire_lock(db_session, lock, holder, lease_s=120)
        assert t is not None, f"Failed to acquire {lock}"
        tokens[lock] = t

    # Each lock has its own token starting at 1
    for t in tokens.values():
        assert t == 1

    # Release half
    for lock in locks[:2]:
        await svc.release_lock(db_session, lock, holder, tokens[lock])

    # The other half are unaffected
    for lock in locks[2:]:
        state = await svc.get_lock_state(db_session, lock)
        assert state is not None
        assert state["holder_id"] == holder


@pytest.mark.asyncio
async def test_tick_lock_and_job_lock_independent(db_session):
    """The tick lock and a per-job lock are independent namespaces."""
    tick_holder = _holder("tick-worker")
    job_holder  = _holder("job-worker")

    tick_token = await svc.acquire_lock(db_session, "loop:tick",    tick_holder)
    job_token  = await svc.acquire_lock(db_session, "loop:job:123", job_holder)

    assert tick_token is not None
    assert job_token  is not None

    # Releasing one does not affect the other
    await svc.release_lock(db_session, "loop:tick", tick_holder, tick_token)
    assert await svc.is_lock_free(db_session, "loop:tick") is True
    assert await svc.is_lock_free(db_session, "loop:job:123") is False


# ---------------------------------------------------------------------------
# Renewal extends lease (not just a no-op)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_renew_extends_lease(db_session):
    """renew_lock() pushes lease_expires_utc forward."""
    from sqlalchemy import select
    from app.db.models import JobLock

    holder = _holder("w1")
    lock   = "loop:renew-extends"

    token = await svc.acquire_lock(db_session, lock, holder, lease_s=10)

    # Capture original expiry
    result = await db_session.execute(
        select(JobLock).where(JobLock.lock_name == lock)
    )
    original_expires = result.scalar_one().lease_expires_utc

    # Renew with a longer lease
    await svc.renew_lock(db_session, lock, holder, token, lease_s=300)

    result2 = await db_session.execute(
        select(JobLock).where(JobLock.lock_name == lock)
    )
    new_expires = result2.scalar_one().lease_expires_utc

    assert new_expires > original_expires
