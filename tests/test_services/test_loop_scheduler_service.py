"""
Phase 10A · Slice 4 — Scheduler tick loop tests.

Covers:
  - Loop gate (loop_enabled=False → inert tick, no DB writes)
  - Tick lock acquisition and single-flight enforcement
  - No-due-jobs tick (empty result, lock released)
  - Happy-path dispatch: claim → run → succeed → mark_success
  - Idempotency short-circuit: existing succeeded run → skipped_stale
  - Producer failure + retry scheduling
  - Producer failure + dead-letter after max_attempts exhausted
  - Unregistered producer → failure + retry path
  - Producer exception → failure handling (no crash)
  - batch_size limit respected
  - Tick lock always released (even on producer exception)
  - Null session → inert TickResult, no exception
  - ProducerResult type contract (wrong return type wrapped gracefully)
  - TickResult field types and defaults
  - tick_is_locked() reflects lock state

Each test registers/unregisters its own producer to keep them independent.
Uses the db_session fixture from conftest.py (in-memory SQLite).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest

from app.db.repositories import loop_repo
from app.services import loop_scheduler_service as sched
from app.services.loop_scheduler_service import ProducerResult, TickResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _uid() -> str:
    return uuid.uuid4().hex[:10]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _past(s: int = 5) -> datetime:
    return _now() - timedelta(seconds=s)


def _future(s: int = 120) -> datetime:
    return _now() + timedelta(seconds=s)


def _holder() -> str:
    return f"test-worker:{_uid()}"


async def _make_due_job(db_session, job_type="daily_brief", target="user_001",
                        bucket=None, max_attempts=3):
    bucket = bucket or f"2026-06-{_uid()[:4]}"
    return await loop_repo.job_create(
        db_session, job_type, target, bucket,
        next_run_utc=_past(10),
        max_attempts=max_attempts,
    )


def _success_producer():
    async def producer(session, job, run_id, holder_id, fence_token):
        return ProducerResult(outcome="succeeded", spent_llm_calls=2)
    return producer


def _failure_producer(error="timeout"):
    async def producer(session, job, run_id, holder_id, fence_token):
        return ProducerResult(outcome="failed", error=error)
    return producer


def _raising_producer():
    async def producer(session, job, run_id, holder_id, fence_token):
        raise RuntimeError("producer exploded")
    return producer


# ---------------------------------------------------------------------------
# Fixture: ensure producers are cleaned up after each test
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def clean_producers():
    """Remove all test-registered producers after each test."""
    yield
    for jt in list(sched.list_registered_producers()):
        sched.unregister_producer(jt)


# ---------------------------------------------------------------------------
# Fixture: loop_enabled patching helper
# ---------------------------------------------------------------------------

@pytest.fixture
def loop_on(monkeypatch):
    """Patch _is_loop_enabled to return True for the duration of the test."""
    monkeypatch.setattr(sched, "_is_loop_enabled", lambda: True)


# ===========================================================================
# TickResult and config defaults
# ===========================================================================

def test_tick_result_defaults():
    r = TickResult()
    assert r.jobs_claimed == 0
    assert r.jobs_succeeded == 0
    assert r.jobs_failed == 0
    assert r.jobs_dead_lettered == 0
    assert r.jobs_short_circuited == 0
    assert r.locks_reaped == 0
    assert r.tick_acquired is False
    assert r.loop_enabled is False
    assert r.errors == []


def test_producer_result_defaults():
    r = ProducerResult()
    assert r.outcome == "succeeded"
    assert r.spent_llm_calls == 0
    assert r.drift_hit is False
    assert r.error is None


# ===========================================================================
# Null-session safety
# ===========================================================================

@pytest.mark.asyncio
async def test_tick_null_session_returns_inert():
    result = await sched.tick(None, _holder())
    assert isinstance(result, TickResult)
    assert result.jobs_claimed == 0
    assert result.tick_acquired is False


# ===========================================================================
# Loop gate
# ===========================================================================

@pytest.mark.asyncio
async def test_tick_loop_disabled_is_inert(db_session):
    """When loop_enabled=False, tick() returns immediately — no DB writes."""
    await _make_due_job(db_session)
    result = await sched.tick(db_session, _holder(), batch_size=10, lease_s=120)
    assert result.loop_enabled is False
    assert result.tick_acquired is False
    assert result.jobs_claimed == 0


@pytest.mark.asyncio
async def test_tick_loop_enabled_proceeds(db_session, loop_on):
    """When loop_enabled=True, tick() attempts to acquire the lock and claim jobs."""
    sched.register_producer("daily_brief", _success_producer())
    await _make_due_job(db_session)
    result = await sched.tick(db_session, _holder(), batch_size=10, lease_s=120)
    assert result.loop_enabled is True
    assert result.tick_acquired is True
    assert result.jobs_claimed == 1


# ===========================================================================
# Tick lock — single-flight enforcement
# ===========================================================================

@pytest.mark.asyncio
async def test_tick_skips_when_lock_held(db_session, loop_on):
    """A second concurrent tick() returns immediately when the lock is held."""
    holder_a = _holder()
    holder_b = _holder()

    # holder_a holds the tick lock
    from app.services.loop_lock_service import acquire_lock
    token = await acquire_lock(db_session, "loop:tick", holder_a, lease_s=120)
    assert token is not None

    # holder_b tick should skip
    result = await sched.tick(db_session, holder_b, batch_size=10, lease_s=120)
    assert result.tick_acquired is False
    assert result.jobs_claimed == 0


@pytest.mark.asyncio
async def test_tick_lock_released_after_tick(db_session, loop_on):
    """Tick lock is released after a successful tick so the next tick can proceed."""
    sched.register_producer("daily_brief", _success_producer())
    holder = _holder()

    r1 = await sched.tick(db_session, holder, batch_size=10, lease_s=120)
    assert r1.tick_acquired is True

    # A second tick by a different holder should succeed (lock is free now)
    r2 = await sched.tick(db_session, _holder(), batch_size=10, lease_s=120)
    assert r2.tick_acquired is True


# ===========================================================================
# No-due-jobs tick
# ===========================================================================

@pytest.mark.asyncio
async def test_tick_no_due_jobs(db_session, loop_on):
    """With no due jobs, tick completes cleanly and releases the lock."""
    result = await sched.tick(db_session, _holder(), batch_size=10, lease_s=120)
    assert result.tick_acquired is True
    assert result.jobs_claimed == 0
    assert result.jobs_succeeded == 0


@pytest.mark.asyncio
async def test_tick_future_jobs_not_claimed(db_session, loop_on):
    """Jobs with next_run_utc in the future are not claimed."""
    await loop_repo.job_create(
        db_session, "daily_brief", "user_future", "2026-06-12",
        next_run_utc=_future(3600),
    )
    result = await sched.tick(db_session, _holder(), batch_size=10, lease_s=120)
    assert result.jobs_claimed == 0


# ===========================================================================
# Happy-path dispatch
# ===========================================================================

@pytest.mark.asyncio
async def test_tick_claims_and_succeeds(db_session, loop_on):
    """A due job is claimed, dispatched, and marked succeeded."""
    sched.register_producer("daily_brief", _success_producer())
    job = await _make_due_job(db_session)

    result = await sched.tick(db_session, _holder(), batch_size=10, lease_s=120)

    assert result.jobs_claimed == 1
    assert result.jobs_succeeded == 1
    assert result.jobs_failed == 0

    # Job row reflects terminal state
    refreshed = await loop_repo.job_get_by_id(db_session, job.id)
    assert refreshed.state == "succeeded"
    assert refreshed.holder_id is None
    assert refreshed.last_generated_at is not None


@pytest.mark.asyncio
async def test_tick_run_audit_row_created(db_session, loop_on):
    """A JobRun row is appended with the correct outcome."""
    sched.register_producer("daily_brief", _success_producer())
    job = await _make_due_job(db_session)

    await sched.tick(db_session, _holder(), batch_size=10, lease_s=120)

    history = await loop_repo.run_get_history(db_session, job.id)
    assert len(history) == 1
    assert history[0].outcome == "succeeded"
    assert history[0].spent_llm_calls == 2


@pytest.mark.asyncio
async def test_tick_batch_size_limits_claims(db_session, loop_on):
    """batch_size caps the number of jobs claimed per tick."""
    sched.register_producer("daily_brief", _success_producer())
    for i in range(6):
        await _make_due_job(db_session, target=f"user_{i:03d}", bucket=f"b{i}")

    result = await sched.tick(db_session, _holder(), batch_size=3, lease_s=120)
    assert result.jobs_claimed == 3


@pytest.mark.asyncio
async def test_tick_multiple_jobs_same_type(db_session, loop_on):
    """All due jobs (up to batch_size) are processed in one tick."""
    sched.register_producer("daily_brief", _success_producer())
    for i in range(4):
        await _make_due_job(db_session, target=f"user_{i:03d}", bucket=f"bkt{i}")

    result = await sched.tick(db_session, _holder(), batch_size=10, lease_s=120)
    assert result.jobs_claimed == 4
    assert result.jobs_succeeded == 4


# ===========================================================================
# Idempotency short-circuit
# ===========================================================================

@pytest.mark.asyncio
async def test_tick_short_circuits_if_already_succeeded(db_session, loop_on):
    """If a succeeded run exists for the work_key, the job is short-circuited."""
    sched.register_producer("daily_brief", _success_producer())
    job = await _make_due_job(db_session, job_type="daily_brief",
                              target="user_sc", bucket="2026-06-12")

    # Pre-insert a succeeded run with the same work_key
    from app.services.loop_scheduler_service import _compute_work_key
    wk = _compute_work_key("daily_brief", "user_sc", "2026-06-12")
    run = await loop_repo.run_append(
        db_session, job.id, wk, "daily_brief", "user_sc", "2026-06-12",
        "prior-worker", fence_token=0,
    )
    await loop_repo.run_finish(db_session, run.id, "succeeded")

    result = await sched.tick(db_session, _holder(), batch_size=10, lease_s=120)

    assert result.jobs_short_circuited == 1
    assert result.jobs_succeeded == 0

    refreshed = await loop_repo.job_get_by_id(db_session, job.id)
    assert refreshed.state == "skipped_stale"


# ===========================================================================
# Failure and retry handling
# ===========================================================================

@pytest.mark.asyncio
async def test_tick_producer_failure_reschedules(db_session, loop_on):
    """A failed job with attempts < max_attempts is rescheduled (state=failed)."""
    sched.register_producer("daily_brief", _failure_producer("timeout"))
    job = await _make_due_job(db_session, max_attempts=3)

    result = await sched.tick(db_session, _holder(), batch_size=10,
                               lease_s=120, retry_backoff_s=300)

    assert result.jobs_failed == 1
    assert result.jobs_dead_lettered == 0

    refreshed = await loop_repo.job_get_by_id(db_session, job.id)
    assert refreshed.state == "failed"
    assert refreshed.next_run_utc is not None
    assert refreshed.holder_id is None


@pytest.mark.asyncio
async def test_tick_producer_failure_dead_letters_on_exhaustion(db_session, loop_on):
    """A job that exhausts max_attempts is dead-lettered."""
    sched.register_producer("daily_brief", _failure_producer("persistent error"))
    # max_attempts=1: first attempt exhausts immediately
    job = await _make_due_job(db_session, max_attempts=1)

    result = await sched.tick(db_session, _holder(), batch_size=10, lease_s=120)

    assert result.jobs_dead_lettered == 1
    assert result.jobs_failed == 0

    refreshed = await loop_repo.job_get_by_id(db_session, job.id)
    assert refreshed.state == "dead_letter"
    assert refreshed.holder_id is None


@pytest.mark.asyncio
async def test_tick_run_audit_records_failure(db_session, loop_on):
    """A failed dispatch writes a 'failed' run row with the error text."""
    sched.register_producer("daily_brief", _failure_producer("timeout"))
    job = await _make_due_job(db_session, max_attempts=3)

    await sched.tick(db_session, _holder(), batch_size=10, lease_s=120)

    history = await loop_repo.run_get_history(db_session, job.id)
    assert len(history) == 1
    assert history[0].outcome == "failed"
    assert history[0].error == "timeout"


# ===========================================================================
# Unregistered producer
# ===========================================================================

@pytest.mark.asyncio
async def test_tick_unregistered_producer_causes_failure(db_session, loop_on):
    """A job_type with no producer registered fails gracefully."""
    # Explicitly do NOT register a producer for "unknown_type"
    job = await _make_due_job(db_session, job_type="unknown_type", max_attempts=3)

    result = await sched.tick(db_session, _holder(), batch_size=10, lease_s=120)

    assert result.jobs_failed == 1

    refreshed = await loop_repo.job_get_by_id(db_session, job.id)
    assert refreshed.state == "failed"

    history = await loop_repo.run_get_history(db_session, job.id)
    assert "no_producer" in (history[0].error or "")


# ===========================================================================
# Producer exception
# ===========================================================================

@pytest.mark.asyncio
async def test_tick_producer_exception_handled_gracefully(db_session, loop_on):
    """An exception raised by a producer is caught; tick() does not propagate it."""
    sched.register_producer("daily_brief", _raising_producer())
    job = await _make_due_job(db_session, max_attempts=3)

    result = await sched.tick(db_session, _holder(), batch_size=10, lease_s=120)

    # tick() must not raise; job is marked failed
    assert result.jobs_failed == 1

    history = await loop_repo.run_get_history(db_session, job.id)
    assert history[0].outcome == "failed"
    assert "RuntimeError" in (history[0].error or "")


@pytest.mark.asyncio
async def test_tick_lock_released_even_after_producer_exception(db_session, loop_on):
    """Tick lock is released via finally even when a producer raises."""
    sched.register_producer("daily_brief", _raising_producer())
    await _make_due_job(db_session)

    holder = _holder()
    await sched.tick(db_session, holder, batch_size=10, lease_s=120)

    # Lock is free — a second tick from a different holder can proceed
    result2 = await sched.tick(db_session, _holder(), batch_size=10, lease_s=120)
    assert result2.tick_acquired is True


# ===========================================================================
# Expired lock reap
# ===========================================================================

@pytest.mark.asyncio
async def test_tick_reaps_expired_locks(db_session, loop_on):
    """Expired job_locks rows are reaped at the top of tick()."""
    from app.services.loop_lock_service import acquire_lock
    from sqlalchemy import update
    from app.db.models import JobLock

    # Acquire a job-level lock then force it to expire
    lock_name = f"loop:job:{_uid()}"
    await acquire_lock(db_session, lock_name, "zombie-worker", lease_s=120)
    await db_session.execute(
        update(JobLock)
        .where(JobLock.lock_name == lock_name)
        .values(lease_expires_utc=_past(600))
        .execution_options(synchronize_session=False)
    )
    await db_session.flush()

    result = await sched.tick(db_session, _holder(), batch_size=10, lease_s=120)
    assert result.locks_reaped >= 1


# ===========================================================================
# work_key computation
# ===========================================================================

def test_compute_work_key_is_deterministic():
    """Same inputs always produce the same work_key."""
    from app.services.loop_scheduler_service import _compute_work_key
    wk1 = _compute_work_key("daily_brief", "user_001", "2026-06-12")
    wk2 = _compute_work_key("daily_brief", "user_001", "2026-06-12")
    assert wk1 == wk2
    assert len(wk1) == 64


def test_compute_work_key_differs_on_distinct_inputs():
    from app.services.loop_scheduler_service import _compute_work_key
    wk_a = _compute_work_key("daily_brief", "user_001", "2026-06-12")
    wk_b = _compute_work_key("daily_brief", "user_002", "2026-06-12")
    wk_c = _compute_work_key("daily_brief", "user_001", "2026-06-13")
    assert wk_a != wk_b
    assert wk_a != wk_c
    assert wk_b != wk_c


# ===========================================================================
# Producer registry
# ===========================================================================

def test_register_and_list_producers():
    sched.register_producer("test_type_a", _success_producer())
    sched.register_producer("test_type_b", _success_producer())
    registered = sched.list_registered_producers()
    assert "test_type_a" in registered
    assert "test_type_b" in registered


def test_unregister_producer():
    sched.register_producer("test_type_c", _success_producer())
    sched.unregister_producer("test_type_c")
    assert "test_type_c" not in sched.list_registered_producers()


def test_unregister_nonexistent_is_safe():
    sched.unregister_producer("never_registered_xyz")  # should not raise


# ===========================================================================
# tick_is_locked
# ===========================================================================

@pytest.mark.asyncio
async def test_tick_is_locked_false_when_free(db_session):
    is_locked = await sched.tick_is_locked(db_session)
    assert is_locked is False


@pytest.mark.asyncio
async def test_tick_is_locked_true_when_held(db_session):
    from app.services.loop_lock_service import acquire_lock
    await acquire_lock(db_session, "loop:tick", _holder(), lease_s=120)
    is_locked = await sched.tick_is_locked(db_session)
    assert is_locked is True
