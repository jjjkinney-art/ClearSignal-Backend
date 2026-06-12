"""
Phase 10A · Slice 5 — Idempotency enforcement tests.

Covers:
  § KEYS     — build_payload_hash, build_work_key, build_content_key
  § CHECK    — check_work_key_succeeded (DB-backed read)
  § DELIVERY — guard_delivery (DB-backed write with dedup)
  § SCHEDULER integration —
      short-circuit does not execute producer twice,
      audit run is appended on short-circuit,
      failed run does not block retry,
      succeeded run blocks duplicate dispatch,
      two ticks same work_key = exactly one producer call
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.db.repositories import loop_repo
from app.services import loop_idempotency_service as idem
from app.services import loop_scheduler_service as sched
from app.services.loop_scheduler_service import ProducerResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _uid() -> str:
    return uuid.uuid4().hex[:10]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _past(s: int = 5) -> datetime:
    return _now() - timedelta(seconds=s)


def _holder() -> str:
    return f"test:{_uid()}"


async def _make_due_job(db_session, job_type="daily_brief",
                        target="user_001", bucket=None, max_attempts=3):
    bucket = bucket or f"2026-06-12-{_uid()[:6]}"
    return await loop_repo.job_create(
        db_session, job_type, target, bucket,
        next_run_utc=_past(5),
        max_attempts=max_attempts,
    )


# ---------------------------------------------------------------------------
# Auto-clean producers
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def clean_producers():
    yield
    for jt in list(sched.list_registered_producers()):
        sched.unregister_producer(jt)


@pytest.fixture
def loop_on(monkeypatch):
    monkeypatch.setattr(sched, "_is_loop_enabled", lambda: True)


# ===========================================================================
# § KEYS — pure functions, no session required
# ===========================================================================

class TestBuildPayloadHash:
    def test_same_dict_produces_same_hash(self):
        h1 = idem.build_payload_hash({"a": 1, "b": 2})
        h2 = idem.build_payload_hash({"a": 1, "b": 2})
        assert h1 == h2

    def test_different_insertion_order_same_hash(self):
        h1 = idem.build_payload_hash({"a": 1, "b": 2, "c": 3})
        h2 = idem.build_payload_hash({"c": 3, "a": 1, "b": 2})
        assert h1 == h2

    def test_nested_keys_sorted(self):
        h1 = idem.build_payload_hash({"outer": {"z": 9, "a": 1}})
        h2 = idem.build_payload_hash({"outer": {"a": 1, "z": 9}})
        assert h1 == h2

    def test_different_values_different_hash(self):
        h1 = idem.build_payload_hash({"conviction": 0.8})
        h2 = idem.build_payload_hash({"conviction": 0.9})
        assert h1 != h2

    def test_returns_64_hex_chars(self):
        h = idem.build_payload_hash({"x": 1})
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)

    def test_empty_dict(self):
        h = idem.build_payload_hash({})
        assert len(h) == 64  # hashes fine, deterministic

    def test_list_values_stable(self):
        h1 = idem.build_payload_hash({"tags": ["drift", "aapl"]})
        h2 = idem.build_payload_hash({"tags": ["drift", "aapl"]})
        assert h1 == h2


class TestBuildWorkKey:
    def test_deterministic(self):
        k1 = idem.build_work_key("daily_brief", "user_001", "2026-06-12")
        k2 = idem.build_work_key("daily_brief", "user_001", "2026-06-12")
        assert k1 == k2

    def test_returns_64_hex_chars(self):
        k = idem.build_work_key("daily_brief", "user_001", "2026-06-12")
        assert len(k) == 64
        assert all(c in "0123456789abcdef" for c in k)

    def test_differs_on_different_type(self):
        k1 = idem.build_work_key("daily_brief", "user_001", "2026-06-12")
        k2 = idem.build_work_key("watchlist_alert", "user_001", "2026-06-12")
        assert k1 != k2

    def test_differs_on_different_target(self):
        k1 = idem.build_work_key("daily_brief", "user_001", "2026-06-12")
        k2 = idem.build_work_key("daily_brief", "user_002", "2026-06-12")
        assert k1 != k2

    def test_differs_on_different_bucket(self):
        k1 = idem.build_work_key("daily_brief", "user_001", "2026-06-12")
        k2 = idem.build_work_key("daily_brief", "user_001", "2026-06-13")
        assert k1 != k2

    def test_matches_scheduler_internal_key(self):
        """The scheduler's _compute_work_key must be an alias for build_work_key."""
        from app.services.loop_scheduler_service import _compute_work_key
        k_idem = idem.build_work_key("daily_brief", "user_001", "2026-06-12")
        k_sched = _compute_work_key("daily_brief", "user_001", "2026-06-12")
        assert k_idem == k_sched


class TestBuildContentKey:
    def test_deterministic(self):
        ph = idem.build_payload_hash({"title": "brief"})
        k1 = idem.build_content_key("user_001", "in_app", "user_001", ph)
        k2 = idem.build_content_key("user_001", "in_app", "user_001", ph)
        assert k1 == k2

    def test_returns_64_hex_chars(self):
        ph = idem.build_payload_hash({"x": 1})
        k = idem.build_content_key("user_001", "in_app", "user_001", ph)
        assert len(k) == 64

    def test_differs_on_different_user(self):
        ph = idem.build_payload_hash({"x": 1})
        k1 = idem.build_content_key("user_001", "in_app", "user_001", ph)
        k2 = idem.build_content_key("user_002", "in_app", "user_001", ph)
        assert k1 != k2

    def test_differs_on_different_channel(self):
        ph = idem.build_payload_hash({"x": 1})
        k1 = idem.build_content_key("user_001", "in_app", "user_001", ph)
        k2 = idem.build_content_key("user_001", "email", "user_001", ph)
        assert k1 != k2

    def test_differs_on_different_payload_hash(self):
        ph1 = idem.build_payload_hash({"conviction": 0.8})
        ph2 = idem.build_payload_hash({"conviction": 0.9})
        k1 = idem.build_content_key("user_001", "in_app", "user_001", ph1)
        k2 = idem.build_content_key("user_001", "in_app", "user_001", ph2)
        assert k1 != k2

    def test_payload_order_does_not_affect_content_key(self):
        ph1 = idem.build_payload_hash({"a": 1, "b": 2})
        ph2 = idem.build_payload_hash({"b": 2, "a": 1})
        k1 = idem.build_content_key("user_001", "in_app", "user_001", ph1)
        k2 = idem.build_content_key("user_001", "in_app", "user_001", ph2)
        assert k1 == k2  # same payload hash → same content key


# ===========================================================================
# § CHECK — check_work_key_succeeded
# ===========================================================================

class TestCheckWorkKeySucceeded:
    @pytest.mark.asyncio
    async def test_false_when_no_run(self, db_session):
        wk = idem.build_work_key("daily_brief", "user_100", _uid())
        assert await idem.check_work_key_succeeded(db_session, wk) is False

    @pytest.mark.asyncio
    async def test_false_when_run_is_still_running(self, db_session):
        job = await _make_due_job(db_session, target="user_101")
        wk = idem.build_work_key(job.job_type, job.target_key, job.period_bucket)
        await loop_repo.run_append(
            db_session, job.id, wk, job.job_type, job.target_key,
            job.period_bucket, "w1", fence_token=1,
        )
        assert await idem.check_work_key_succeeded(db_session, wk) is False

    @pytest.mark.asyncio
    async def test_false_when_run_failed(self, db_session):
        job = await _make_due_job(db_session, target="user_102")
        wk = idem.build_work_key(job.job_type, job.target_key, job.period_bucket)
        run = await loop_repo.run_append(
            db_session, job.id, wk, job.job_type, job.target_key,
            job.period_bucket, "w1", fence_token=1,
        )
        await loop_repo.run_finish(db_session, run.id, "failed")
        assert await idem.check_work_key_succeeded(db_session, wk) is False

    @pytest.mark.asyncio
    async def test_true_when_run_succeeded(self, db_session):
        job = await _make_due_job(db_session, target="user_103")
        wk = idem.build_work_key(job.job_type, job.target_key, job.period_bucket)
        run = await loop_repo.run_append(
            db_session, job.id, wk, job.job_type, job.target_key,
            job.period_bucket, "w1", fence_token=1,
        )
        await loop_repo.run_finish(db_session, run.id, "succeeded")
        assert await idem.check_work_key_succeeded(db_session, wk) is True

    @pytest.mark.asyncio
    async def test_null_session_returns_false(self):
        wk = idem.build_work_key("daily_brief", "user_x", "bucket")
        assert await idem.check_work_key_succeeded(None, wk) is False


# ===========================================================================
# § DELIVERY — guard_delivery
# ===========================================================================

class TestGuardDelivery:
    def _ph(self, seed: str = "default") -> str:
        return idem.build_payload_hash({"seed": seed})

    @pytest.mark.asyncio
    async def test_creates_delivery_row_on_first_call(self, db_session):
        ph = self._ph()
        row = await idem.guard_delivery(
            db_session, "user_200", "in_app", "user_200", ph
        )
        assert row is not None
        assert row.status == "pending"

    @pytest.mark.asyncio
    async def test_returns_none_on_duplicate(self, db_session):
        ph = self._ph("dup")
        r1 = await idem.guard_delivery(
            db_session, "user_201", "in_app", "user_201", ph
        )
        r2 = await idem.guard_delivery(
            db_session, "user_201", "in_app", "user_201", ph
        )
        assert r1 is not None
        assert r2 is None  # duplicate suppressed

    @pytest.mark.asyncio
    async def test_different_users_same_payload_both_created(self, db_session):
        ph = self._ph("shared")
        r1 = await idem.guard_delivery(
            db_session, "user_202", "in_app", "user_202", ph
        )
        r2 = await idem.guard_delivery(
            db_session, "user_203", "in_app", "user_203", ph
        )
        assert r1 is not None
        assert r2 is not None
        assert r1.id != r2.id  # different content_keys

    @pytest.mark.asyncio
    async def test_different_channels_both_created(self, db_session):
        ph = self._ph("channel-test")
        r1 = await idem.guard_delivery(
            db_session, "user_204", "in_app", "user_204", ph
        )
        r2 = await idem.guard_delivery(
            db_session, "user_204", "email", "user_204", ph
        )
        assert r1 is not None
        assert r2 is not None

    @pytest.mark.asyncio
    async def test_different_payload_both_created(self, db_session):
        ph1 = self._ph("v1")
        ph2 = self._ph("v2")
        r1 = await idem.guard_delivery(
            db_session, "user_205", "in_app", "user_205", ph1
        )
        r2 = await idem.guard_delivery(
            db_session, "user_205", "in_app", "user_205", ph2
        )
        assert r1 is not None
        assert r2 is not None

    @pytest.mark.asyncio
    async def test_null_session_returns_none(self):
        ph = self._ph()
        result = await idem.guard_delivery(None, "u", "in_app", "u", ph)
        assert result is None

    @pytest.mark.asyncio
    async def test_content_key_stored_on_row(self, db_session):
        ph = self._ph("key-check")
        expected_ck = idem.build_content_key("user_206", "in_app", "user_206", ph)
        row = await idem.guard_delivery(
            db_session, "user_206", "in_app", "user_206", ph
        )
        assert row.content_key == expected_ck

    @pytest.mark.asyncio
    async def test_artifact_ref_stored(self, db_session):
        ph = self._ph("ref-test")
        row = await idem.guard_delivery(
            db_session, "user_207", "in_app", "user_207", ph,
            artifact_ref="session_abc123",
        )
        assert row is not None
        assert row.artifact_ref == "session_abc123"


# ===========================================================================
# § SCHEDULER integration
# ===========================================================================

class TestSchedulerIdempotency:
    """
    End-to-end idempotency tests through tick().

    Producer call counts are tracked via a mutable counter so we can
    assert exactly-once dispatch without using mocks.
    """

    def _counting_producer(self, counter: list):
        """Returns a producer that increments counter[0] on each call."""
        async def producer(session, job, run_id, holder_id, fence_token):
            counter[0] += 1
            return ProducerResult(outcome="succeeded", spent_llm_calls=1)
        return producer

    def _failing_producer(self, counter: list):
        async def producer(session, job, run_id, holder_id, fence_token):
            counter[0] += 1
            return ProducerResult(outcome="failed", error="transient")
        return producer

    @pytest.mark.asyncio
    async def test_two_ticks_same_work_key_calls_producer_once(
        self, db_session, loop_on
    ):
        """
        First tick: claims job, dispatches producer, marks succeeded.
        Second tick: finds work_key already succeeded, short-circuits.
        Producer must be called exactly once.
        """
        calls = [0]
        sched.register_producer("daily_brief", self._counting_producer(calls))
        job = await _make_due_job(db_session, target="user_sc_001",
                                  bucket="2026-06-12")

        # First tick — succeeds
        r1 = await sched.tick(db_session, _holder(), batch_size=10, lease_s=120)
        assert r1.jobs_succeeded == 1
        assert calls[0] == 1

        # Reset job to 'scheduled' to simulate re-enqueueing the same work
        await loop_repo.job_update_state(db_session, job.id, "scheduled")

        # Second tick — short-circuits
        r2 = await sched.tick(db_session, _holder(), batch_size=10, lease_s=120)
        assert r2.jobs_short_circuited == 1
        assert r2.jobs_succeeded == 0

        # Producer was NOT called again
        assert calls[0] == 1, f"Producer called {calls[0]} times, expected 1"

    @pytest.mark.asyncio
    async def test_short_circuit_audit_run_appended(self, db_session, loop_on):
        """The short-circuit path appends a 'short_circuited' JobRun for audit."""
        calls = [0]
        sched.register_producer("daily_brief", self._counting_producer(calls))
        job = await _make_due_job(db_session, target="user_sc_002",
                                  bucket="2026-06-12")

        # First tick succeeds
        await sched.tick(db_session, _holder(), batch_size=10, lease_s=120)

        # Reset job
        await loop_repo.job_update_state(db_session, job.id, "scheduled")

        # Second tick — short-circuit
        await sched.tick(db_session, _holder(), batch_size=10, lease_s=120)

        history = await loop_repo.run_get_history(db_session, job.id)
        outcomes = {r.outcome for r in history}
        assert "succeeded" in outcomes
        assert "short_circuited" in outcomes

    @pytest.mark.asyncio
    async def test_failure_does_not_block_retry(self, db_session, loop_on):
        """
        A failed run must NOT trigger the short-circuit check.
        The second tick (after failure) must call the producer again.
        """
        from sqlalchemy import update as sa_update
        from app.db.models import ScheduledJob

        calls = [0]
        fail_calls = [0]

        fail_producer = self._failing_producer(fail_calls)
        success_producer = self._counting_producer(calls)

        # First tick: failing producer
        sched.register_producer("daily_brief", fail_producer)
        job = await _make_due_job(db_session, target="user_retry_001",
                                  bucket="2026-06-12", max_attempts=3)

        r1 = await sched.tick(db_session, _holder(), batch_size=10, lease_s=120)
        assert r1.jobs_failed == 1
        assert fail_calls[0] == 1

        # Reset state='scheduled' AND move next_run_utc to past (simulates backoff elapsed)
        await loop_repo.job_update_state(db_session, job.id, "scheduled")
        await db_session.execute(
            sa_update(ScheduledJob)
            .where(ScheduledJob.id == job.id)
            .values(next_run_utc=_past(10))
            .execution_options(synchronize_session=False)
        )

        # Second tick: now with a succeeding producer
        sched.unregister_producer("daily_brief")
        sched.register_producer("daily_brief", success_producer)

        r2 = await sched.tick(db_session, _holder(), batch_size=10, lease_s=120)
        assert r2.jobs_succeeded == 1
        assert calls[0] == 1, "Success producer must be called on retry"

    @pytest.mark.asyncio
    async def test_success_blocks_duplicate_rerun(self, db_session, loop_on):
        """
        After a success, re-scheduling the same (type, target, bucket) MUST
        NOT execute the producer again.
        """
        calls = [0]
        sched.register_producer("daily_brief", self._counting_producer(calls))
        job = await _make_due_job(db_session, target="user_block_001",
                                  bucket="2026-06-12")

        # First tick
        await sched.tick(db_session, _holder(), batch_size=10, lease_s=120)
        assert calls[0] == 1

        # Reset job (simulate drift re-enqueue)
        await loop_repo.job_update_state(db_session, job.id, "scheduled")

        # Three more ticks — should all short-circuit
        for _ in range(3):
            await sched.tick(db_session, _holder(), batch_size=10, lease_s=120)
            await loop_repo.job_update_state(db_session, job.id, "scheduled")

        assert calls[0] == 1, f"Producer called {calls[0]} times, expected 1"

    @pytest.mark.asyncio
    async def test_idempotency_survives_retry_cycle(self, db_session, loop_on):
        """
        Full lifecycle: fail → retry → succeed → re-schedule → short-circuit.
        """
        from sqlalchemy import update as sa_update
        from app.db.models import ScheduledJob

        calls = [0]

        # Tick 1: fail
        sched.register_producer("daily_brief", self._failing_producer([0]))
        job = await _make_due_job(db_session, target="user_cycle_001",
                                  bucket="2026-06-12", max_attempts=3)
        r1 = await sched.tick(db_session, _holder(), batch_size=10, lease_s=120)
        assert r1.jobs_failed == 1

        # Tick 2: succeed — reset state and backdate next_run_utc so it's due
        await loop_repo.job_update_state(db_session, job.id, "scheduled")
        await db_session.execute(
            sa_update(ScheduledJob)
            .where(ScheduledJob.id == job.id)
            .values(next_run_utc=_past(10))
            .execution_options(synchronize_session=False)
        )
        sched.unregister_producer("daily_brief")
        sched.register_producer("daily_brief", self._counting_producer(calls))
        r2 = await sched.tick(db_session, _holder(), batch_size=10, lease_s=120)
        assert r2.jobs_succeeded == 1
        assert calls[0] == 1

        # Tick 3: short-circuit (work already done)
        await loop_repo.job_update_state(db_session, job.id, "scheduled")
        r3 = await sched.tick(db_session, _holder(), batch_size=10, lease_s=120)
        assert r3.jobs_short_circuited == 1
        assert calls[0] == 1  # still only called once

    @pytest.mark.asyncio
    async def test_duplicate_delivery_suppressed(self, db_session):
        """
        guard_delivery() called twice with identical inputs must only create
        one DeliveryLedger row; the second call returns None.
        """
        ph = idem.build_payload_hash({"headline": "AAPL brief", "conviction": 0.87})
        user_id = "user_dup_001"

        r1 = await idem.guard_delivery(db_session, user_id, "in_app", user_id, ph)
        r2 = await idem.guard_delivery(db_session, user_id, "in_app", user_id, ph)

        assert r1 is not None
        assert r2 is None  # dedup — no second row

        # Confirm only one row exists in the DB
        from sqlalchemy import select, func
        from app.db.models import DeliveryLedger
        result = await db_session.execute(
            select(func.count()).select_from(DeliveryLedger)
            .where(DeliveryLedger.target_key == user_id)
        )
        count = result.scalar()
        assert count == 1

    @pytest.mark.asyncio
    async def test_work_key_stable_across_calls(self, db_session, loop_on):
        """
        The same work_key computed before and after a tick is identical.
        Confirms the scheduler's key matches what idem produces.
        """
        job = await _make_due_job(db_session, job_type="daily_brief",
                                  target="user_wk_001", bucket="2026-06-12")

        wk_before = idem.build_work_key(
            job.job_type, job.target_key, job.period_bucket
        )

        calls = [0]
        sched.register_producer("daily_brief", self._counting_producer(calls))
        await sched.tick(db_session, _holder(), batch_size=10, lease_s=120)

        # The run row must carry the same work_key
        history = await loop_repo.run_get_history(db_session, job.id)
        assert len(history) >= 1
        assert history[0].work_key == wk_before

    @pytest.mark.asyncio
    async def test_different_buckets_are_independent(self, db_session, loop_on):
        """
        Jobs for the same user/type but different period_buckets are
        independent — both produce separate work_keys and run separately.
        """
        calls = [0]
        sched.register_producer("daily_brief", self._counting_producer(calls))

        job_a = await _make_due_job(db_session, target="user_bkt_001",
                                    bucket="2026-06-11")
        job_b = await _make_due_job(db_session, target="user_bkt_001",
                                    bucket="2026-06-12")

        wk_a = idem.build_work_key("daily_brief", "user_bkt_001", "2026-06-11")
        wk_b = idem.build_work_key("daily_brief", "user_bkt_001", "2026-06-12")
        assert wk_a != wk_b  # distinct keys

        r = await sched.tick(db_session, _holder(), batch_size=10, lease_s=120)
        assert r.jobs_succeeded == 2
        assert calls[0] == 2  # both dispatched
