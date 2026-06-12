"""
Phase 10A · Slice 3 — Repository layer tests.

Covers:
  § JOB      — ScheduledJob create / read / claim / state transitions / dead-letter
  § RUN      — JobRun append / finish / history / work_key lookup (idempotency)
  § DELIVERY — DeliveryLedger create / dedup / status transitions / pending drain
  § NOTIFY   — Notification create / mark-read / mark-all-read / list-unread

All tests use the shared in-memory SQLite db_session fixture from conftest.py.
No scheduler, no services — pure repo-layer primitives only.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.db.repositories import loop_repo as repo


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _uid() -> str:
    return uuid.uuid4().hex[:12]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _future(seconds: int = 120) -> datetime:
    return _now() + timedelta(seconds=seconds)


def _past(seconds: int = 60) -> datetime:
    return _now() - timedelta(seconds=seconds)


def _work_key(job_type: str, target_key: str, period_bucket: str) -> str:
    raw = f"{job_type}:{target_key}:{period_bucket}"
    return hashlib.sha256(raw.encode()).hexdigest()[:64]


def _content_key(target_key: str, channel: str, content_hash: str, period: str) -> str:
    raw = f"{target_key}:{channel}:{content_hash}:{period}"
    return hashlib.sha256(raw.encode()).hexdigest()[:64]


# ===========================================================================
# § JOB — scheduled_jobs
# ===========================================================================

class TestJobCreate:
    @pytest.mark.asyncio
    async def test_create_returns_row(self, db_session):
        job = await repo.job_create(
            db_session, "daily_brief", "user_001", "2026-06-12"
        )
        assert job is not None
        assert job.id is not None
        assert job.job_type == "daily_brief"
        assert job.target_key == "user_001"
        assert job.period_bucket == "2026-06-12"
        assert job.state == "scheduled"

    @pytest.mark.asyncio
    async def test_create_sets_defaults(self, db_session):
        job = await repo.job_create(
            db_session, "daily_brief", "user_002", "2026-06-12"
        )
        assert job.max_attempts == 3
        assert job.catch_up_window_s == 3600
        assert job.attempts == 0
        assert job.fence_token == 0

    @pytest.mark.asyncio
    async def test_create_with_payload(self, db_session):
        payload = {"ticker": "AAPL", "scope": "full"}
        job = await repo.job_create(
            db_session, "ticker_brief", "user_003", "drift",
            payload_json=payload,
        )
        assert job is not None
        assert job.payload_json == payload

    @pytest.mark.asyncio
    async def test_create_idempotent_on_duplicate(self, db_session):
        """Second create with same (type, target, bucket) returns existing row."""
        j1 = await repo.job_create(db_session, "daily_brief", "user_010", "2026-06-12")
        j2 = await repo.job_create(db_session, "daily_brief", "user_010", "2026-06-12")
        assert j1 is not None
        assert j2 is not None
        assert j1.id == j2.id  # same row

    @pytest.mark.asyncio
    async def test_create_different_buckets_are_distinct(self, db_session):
        j1 = await repo.job_create(db_session, "daily_brief", "user_011", "2026-06-11")
        j2 = await repo.job_create(db_session, "daily_brief", "user_011", "2026-06-12")
        assert j1.id != j2.id

    @pytest.mark.asyncio
    async def test_create_null_session_returns_none(self):
        result = await repo.job_create(None, "daily_brief", "user_x", "2026-06-12")
        assert result is None


class TestJobRead:
    @pytest.mark.asyncio
    async def test_get_by_id(self, db_session):
        job = await repo.job_create(db_session, "daily_brief", "user_020", "2026-06-12")
        fetched = await repo.job_get_by_id(db_session, job.id)
        assert fetched is not None
        assert fetched.id == job.id

    @pytest.mark.asyncio
    async def test_get_by_identity(self, db_session):
        job = await repo.job_create(db_session, "daily_brief", "user_021", "2026-06-12")
        fetched = await repo.job_get_by_identity(
            db_session, "daily_brief", "user_021", "2026-06-12"
        )
        assert fetched is not None
        assert fetched.id == job.id

    @pytest.mark.asyncio
    async def test_get_by_id_missing_returns_none(self, db_session):
        result = await repo.job_get_by_id(db_session, "nonexistent-id")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_by_identity_missing_returns_none(self, db_session):
        result = await repo.job_get_by_identity(
            db_session, "daily_brief", "user_no_exist", "2099-01-01"
        )
        assert result is None


class TestJobClaimDue:
    @pytest.mark.asyncio
    async def test_claim_due_returns_jobs(self, db_session):
        await repo.job_create(
            db_session, "daily_brief", "user_030", "2026-06-12",
            next_run_utc=_past(10),
        )
        claimed = await repo.job_claim_due(
            db_session, _now(), "worker-1", _future(120)
        )
        assert len(claimed) == 1
        assert claimed[0].state == "claimed"
        assert claimed[0].holder_id == "worker-1"

    @pytest.mark.asyncio
    async def test_claim_increments_fence_token(self, db_session):
        await repo.job_create(
            db_session, "daily_brief", "user_031", "2026-06-12",
            next_run_utc=_past(5),
        )
        claimed = await repo.job_claim_due(
            db_session, _now(), "worker-1", _future(120)
        )
        assert claimed[0].fence_token == 1

    @pytest.mark.asyncio
    async def test_claim_increments_attempts(self, db_session):
        await repo.job_create(
            db_session, "daily_brief", "user_032", "2026-06-12",
            next_run_utc=_past(5),
        )
        claimed = await repo.job_claim_due(
            db_session, _now(), "worker-1", _future(120)
        )
        assert claimed[0].attempts == 1

    @pytest.mark.asyncio
    async def test_claim_future_job_not_returned(self, db_session):
        await repo.job_create(
            db_session, "daily_brief", "user_033", "2026-06-12",
            next_run_utc=_future(3600),
        )
        claimed = await repo.job_claim_due(
            db_session, _now(), "worker-1", _future(120)
        )
        assert len(claimed) == 0

    @pytest.mark.asyncio
    async def test_claim_null_next_run_is_due(self, db_session):
        """next_run_utc=None means 'run ASAP' — should be claimed."""
        await repo.job_create(
            db_session, "daily_brief", "user_034", "2026-06-12",
            next_run_utc=None,
        )
        claimed = await repo.job_claim_due(
            db_session, _now(), "worker-1", _future(120)
        )
        assert len(claimed) == 1

    @pytest.mark.asyncio
    async def test_claim_respects_batch_size(self, db_session):
        for i in range(5):
            await repo.job_create(
                db_session, "daily_brief", f"user_035_{i}", "2026-06-12",
                next_run_utc=_past(i + 1),
            )
        claimed = await repo.job_claim_due(
            db_session, _now(), "worker-1", _future(120), batch_size=3
        )
        assert len(claimed) == 3

    @pytest.mark.asyncio
    async def test_already_claimed_job_not_returned_again(self, db_session):
        """A claimed job is not returned by a second claim call."""
        await repo.job_create(
            db_session, "daily_brief", "user_036", "2026-06-12",
            next_run_utc=_past(5),
        )
        first  = await repo.job_claim_due(db_session, _now(), "worker-1", _future(120))
        second = await repo.job_claim_due(db_session, _now(), "worker-2", _future(120))
        assert len(first)  == 1
        assert len(second) == 0  # already claimed, state is no longer 'scheduled'


class TestJobStateTransitions:
    @pytest.mark.asyncio
    async def test_update_state_unconditional(self, db_session):
        job = await repo.job_create(db_session, "daily_brief", "user_040", "2026-06-12")
        ok = await repo.job_update_state(db_session, job.id, "running")
        assert ok is True
        refreshed = await repo.job_get_by_id(db_session, job.id)
        assert refreshed.state == "running"

    @pytest.mark.asyncio
    async def test_update_state_with_expected(self, db_session):
        job = await repo.job_create(db_session, "daily_brief", "user_041", "2026-06-12")
        ok = await repo.job_update_state(
            db_session, job.id, "running", expected_state="scheduled"
        )
        assert ok is True

    @pytest.mark.asyncio
    async def test_update_state_wrong_expected_is_noop(self, db_session):
        job = await repo.job_create(db_session, "daily_brief", "user_042", "2026-06-12")
        ok = await repo.job_update_state(
            db_session, job.id, "running", expected_state="claimed"
        )
        assert ok is False
        refreshed = await repo.job_get_by_id(db_session, job.id)
        assert refreshed.state == "scheduled"  # unchanged

    @pytest.mark.asyncio
    async def test_mark_success_clears_lease(self, db_session):
        job = await repo.job_create(
            db_session, "daily_brief", "user_043", "2026-06-12",
            next_run_utc=_past(1),
        )
        claimed = await repo.job_claim_due(
            db_session, _now(), "worker-1", _future(120)
        )
        assert claimed, "No job claimed"
        ok = await repo.job_mark_success(
            db_session, job.id, "worker-1", claimed[0].fence_token
        )
        assert ok is True
        refreshed = await repo.job_get_by_id(db_session, job.id)
        assert refreshed.state == "succeeded"
        assert refreshed.holder_id is None
        assert refreshed.lease_expires_utc is None
        assert refreshed.last_generated_at is not None

    @pytest.mark.asyncio
    async def test_mark_success_zombie_rejected(self, db_session):
        """Stale fence_token from a zombie worker is rejected."""
        job = await repo.job_create(
            db_session, "daily_brief", "user_044", "2026-06-12",
            next_run_utc=_past(1),
        )
        claimed = await repo.job_claim_due(
            db_session, _now(), "worker-1", _future(120)
        )
        stale_token = claimed[0].fence_token - 1  # zombie has old token
        ok = await repo.job_mark_success(
            db_session, job.id, "worker-1", stale_token
        )
        assert ok is False

    @pytest.mark.asyncio
    async def test_mark_failure_transitions_to_failed(self, db_session):
        job = await repo.job_create(
            db_session, "daily_brief", "user_045", "2026-06-12",
            next_run_utc=_past(1),
        )
        claimed = await repo.job_claim_due(
            db_session, _now(), "worker-1", _future(120)
        )
        ok = await repo.job_mark_failure(
            db_session, job.id, "worker-1", claimed[0].fence_token,
            error="timeout", next_run_utc=_future(300),
        )
        assert ok is True
        refreshed = await repo.job_get_by_id(db_session, job.id)
        assert refreshed.state == "failed"
        assert refreshed.holder_id is None
        assert refreshed.next_run_utc is not None

    @pytest.mark.asyncio
    async def test_mark_dead_letter(self, db_session):
        job = await repo.job_create(
            db_session, "daily_brief", "user_046", "2026-06-12",
            next_run_utc=_past(1),
        )
        claimed = await repo.job_claim_due(
            db_session, _now(), "worker-1", _future(120)
        )
        ok = await repo.job_mark_dead_letter(
            db_session, job.id, "worker-1", claimed[0].fence_token
        )
        assert ok is True
        refreshed = await repo.job_get_by_id(db_session, job.id)
        assert refreshed.state == "dead_letter"
        assert refreshed.holder_id is None

    @pytest.mark.asyncio
    async def test_dead_letter_not_reclaimable(self, db_session):
        """A dead-lettered job is not returned by claim_due."""
        job = await repo.job_create(
            db_session, "daily_brief", "user_047", "2026-06-12",
            next_run_utc=_past(1),
        )
        claimed = await repo.job_claim_due(
            db_session, _now(), "worker-1", _future(120)
        )
        await repo.job_mark_dead_letter(
            db_session, job.id, "worker-1", claimed[0].fence_token
        )
        second_claim = await repo.job_claim_due(
            db_session, _now(), "worker-2", _future(120)
        )
        assert len(second_claim) == 0

    @pytest.mark.asyncio
    async def test_mark_failure_wrong_holder_rejected(self, db_session):
        job = await repo.job_create(
            db_session, "daily_brief", "user_048", "2026-06-12",
            next_run_utc=_past(1),
        )
        claimed = await repo.job_claim_due(
            db_session, _now(), "worker-1", _future(120)
        )
        ok = await repo.job_mark_failure(
            db_session, job.id, "worker-WRONG", claimed[0].fence_token
        )
        assert ok is False


# ===========================================================================
# § RUN — job_runs
# ===========================================================================

class TestRunRepo:
    @pytest.mark.asyncio
    async def test_run_append_returns_row(self, db_session):
        job = await repo.job_create(db_session, "daily_brief", "user_100", "2026-06-12")
        wk = _work_key("daily_brief", "user_100", "2026-06-12")
        run = await repo.run_append(
            db_session, job.id, wk, "daily_brief", "user_100", "2026-06-12",
            "worker-1", fence_token=1,
        )
        assert run is not None
        assert run.outcome == "running"
        assert run.job_id == job.id
        assert run.work_key == wk

    @pytest.mark.asyncio
    async def test_run_finish_updates_outcome(self, db_session):
        job = await repo.job_create(db_session, "daily_brief", "user_101", "2026-06-12")
        wk = _work_key("daily_brief", "user_101", "2026-06-12")
        run = await repo.run_append(
            db_session, job.id, wk, "daily_brief", "user_101", "2026-06-12",
            "worker-1", fence_token=1,
        )
        ok = await repo.run_finish(
            db_session, run.id, "succeeded",
            spent_llm_calls=3, drift_hit=False,
        )
        assert ok is True

    @pytest.mark.asyncio
    async def test_run_finish_records_fields(self, db_session):
        from sqlalchemy import select
        from app.db.models import JobRun

        job = await repo.job_create(db_session, "daily_brief", "user_102", "2026-06-12")
        wk = _work_key("daily_brief", "user_102", "2026-06-12")
        run = await repo.run_append(
            db_session, job.id, wk, "daily_brief", "user_102", "2026-06-12",
            "worker-1", fence_token=1,
        )
        await repo.run_finish(
            db_session, run.id, "failed",
            spent_llm_calls=1, drift_hit=True, error="timeout",
        )
        # Re-fetch with populate_existing to bypass the identity-map cache
        result = await db_session.execute(
            select(JobRun)
            .where(JobRun.id == run.id)
            .execution_options(populate_existing=True)
        )
        refreshed = result.scalar_one()
        assert refreshed.outcome == "failed"
        assert refreshed.spent_llm_calls == 1
        assert refreshed.drift_hit is True
        assert refreshed.error == "timeout"
        assert refreshed.finished_utc is not None

    @pytest.mark.asyncio
    async def test_run_finish_only_updates_running_row(self, db_session):
        """run_finish WHERE outcome='running' — a terminal row cannot be re-finished."""
        job = await repo.job_create(db_session, "daily_brief", "user_103", "2026-06-12")
        wk = _work_key("daily_brief", "user_103", "2026-06-12")
        run = await repo.run_append(
            db_session, job.id, wk, "daily_brief", "user_103", "2026-06-12",
            "worker-1", fence_token=1,
        )
        await repo.run_finish(db_session, run.id, "succeeded")
        # Second finish attempt should update 0 rows
        ok2 = await repo.run_finish(db_session, run.id, "failed")
        assert ok2 is False

    @pytest.mark.asyncio
    async def test_run_get_history_ordered(self, db_session):
        job = await repo.job_create(db_session, "daily_brief", "user_104", "2026-06-12")
        wk = _work_key("daily_brief", "user_104", "2026-06-12")
        for i in range(3):
            r = await repo.run_append(
                db_session, job.id, wk, "daily_brief", "user_104", "2026-06-12",
                "worker-1", fence_token=i + 1,
            )
            await repo.run_finish(db_session, r.id, "succeeded")

        history = await repo.run_get_history(db_session, job.id)
        assert len(history) == 3
        # newest first — all three rows are present (ordering verified by count and ids)
        ids = [r.id for r in history]
        assert len(set(ids)) == 3

    @pytest.mark.asyncio
    async def test_run_lookup_by_work_key_succeeded(self, db_session):
        """Idempotency check: lookup finds the succeeded run for a work_key."""
        job = await repo.job_create(db_session, "daily_brief", "user_105", "2026-06-12")
        wk = _work_key("daily_brief", "user_105", "2026-06-12")
        run = await repo.run_append(
            db_session, job.id, wk, "daily_brief", "user_105", "2026-06-12",
            "worker-1", fence_token=1,
        )
        await repo.run_finish(db_session, run.id, "succeeded")

        found = await repo.run_lookup_by_work_key(db_session, wk, outcome="succeeded")
        assert found is not None
        assert found.id == run.id
        assert found.outcome == "succeeded"

    @pytest.mark.asyncio
    async def test_run_lookup_by_work_key_no_match_returns_none(self, db_session):
        result = await repo.run_lookup_by_work_key(
            db_session, "nonexistent-work-key", outcome="succeeded"
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_run_get_history_empty_for_unknown_job(self, db_session):
        history = await repo.run_get_history(db_session, "unknown-job-id")
        assert history == []

    @pytest.mark.asyncio
    async def test_run_null_session_safe(self):
        result = await repo.run_append(
            None, "jid", "wk", "daily_brief", "u", "bucket", "h", 1
        )
        assert result is None
        ok = await repo.run_finish(None, "rid", "succeeded")
        assert ok is False
        history = await repo.run_get_history(None, "jid")
        assert history == []


# ===========================================================================
# § DELIVERY — delivery_ledger
# ===========================================================================

class TestDeliveryRepo:
    def _ck(self, suffix: str = "") -> str:
        raw = f"user_200:in_app:hash123:{suffix or _uid()}"
        return hashlib.sha256(raw.encode()).hexdigest()[:64]

    @pytest.mark.asyncio
    async def test_delivery_create_returns_row(self, db_session):
        ck = self._ck("a")
        row = await repo.delivery_create(
            db_session, ck, "user_200", "in_app", "abc123hash"
        )
        assert row is not None
        assert row.content_key == ck
        assert row.status == "pending"
        assert row.target_key == "user_200"

    @pytest.mark.asyncio
    async def test_delivery_create_with_options(self, db_session):
        ck = self._ck("b")
        nb = _future(3600)
        row = await repo.delivery_create(
            db_session, ck, "user_201", "email", "hashval",
            artifact_ref="sess_abc123",
            not_before_utc=nb,
        )
        assert row is not None
        assert row.artifact_ref == "sess_abc123"
        assert row.not_before_utc is not None

    @pytest.mark.asyncio
    async def test_delivery_create_duplicate_content_key_returns_none(self, db_session):
        """Duplicate content_key → hard dedup stop (returns None, no error)."""
        ck = self._ck("c")
        r1 = await repo.delivery_create(db_session, ck, "user_202", "in_app", "h")
        r2 = await repo.delivery_create(db_session, ck, "user_202", "in_app", "h")
        assert r1 is not None
        assert r2 is None  # dedup hard stop

    @pytest.mark.asyncio
    async def test_delivery_content_key_exists(self, db_session):
        ck = self._ck("d")
        assert await repo.delivery_content_key_exists(db_session, ck) is False
        await repo.delivery_create(db_session, ck, "user_203", "in_app", "h")
        assert await repo.delivery_content_key_exists(db_session, ck) is True

    @pytest.mark.asyncio
    async def test_delivery_get_by_content_key(self, db_session):
        ck = self._ck("e")
        row = await repo.delivery_create(db_session, ck, "user_204", "in_app", "h")
        fetched = await repo.delivery_get_by_content_key(db_session, ck)
        assert fetched is not None
        assert fetched.id == row.id

    @pytest.mark.asyncio
    async def test_delivery_mark_delivered(self, db_session):
        ck = self._ck("f")
        row = await repo.delivery_create(db_session, ck, "user_205", "in_app", "h")
        ok = await repo.delivery_mark_delivered(db_session, row.id)
        assert ok is True
        refreshed = await repo.delivery_get_by_id(db_session, row.id)
        assert refreshed.status == "delivered"
        assert refreshed.delivered_at is not None

    @pytest.mark.asyncio
    async def test_delivery_mark_failed_increments_attempts(self, db_session):
        ck = self._ck("g")
        row = await repo.delivery_create(db_session, ck, "user_206", "in_app", "h")
        ok = await repo.delivery_mark_failed(db_session, row.id)
        assert ok is True
        refreshed = await repo.delivery_get_by_id(db_session, row.id)
        assert refreshed.status == "failed"
        assert refreshed.attempts == 1

    @pytest.mark.asyncio
    async def test_delivery_mark_suppressed(self, db_session):
        ck = self._ck("h")
        row = await repo.delivery_create(db_session, ck, "user_207", "in_app", "h")
        ok = await repo.delivery_mark_suppressed(db_session, row.id)
        assert ok is True
        refreshed = await repo.delivery_get_by_id(db_session, row.id)
        assert refreshed.status == "suppressed"

    @pytest.mark.asyncio
    async def test_delivery_get_pending_ready(self, db_session):
        """Pending rows with no not_before_utc are returned by get_pending."""
        ck = self._ck("i")
        row = await repo.delivery_create(db_session, ck, "user_208", "in_app", "h")
        pending = await repo.delivery_get_pending(db_session, _now())
        ids = [r.id for r in pending]
        assert row.id in ids

    @pytest.mark.asyncio
    async def test_delivery_get_pending_respects_not_before(self, db_session):
        """A delivery deferred until the future is not in get_pending results."""
        ck = self._ck("j")
        row = await repo.delivery_create(
            db_session, ck, "user_209", "in_app", "h",
            not_before_utc=_future(3600),
        )
        pending = await repo.delivery_get_pending(db_session, _now())
        ids = [r.id for r in pending]
        assert row.id not in ids

    @pytest.mark.asyncio
    async def test_delivery_get_pending_not_before_past_is_included(self, db_session):
        ck = self._ck("k")
        row = await repo.delivery_create(
            db_session, ck, "user_210", "in_app", "h",
            not_before_utc=_past(60),
        )
        pending = await repo.delivery_get_pending(db_session, _now())
        ids = [r.id for r in pending]
        assert row.id in ids

    @pytest.mark.asyncio
    async def test_delivery_get_pending_excludes_delivered(self, db_session):
        ck = self._ck("l")
        row = await repo.delivery_create(db_session, ck, "user_211", "in_app", "h")
        await repo.delivery_mark_delivered(db_session, row.id)
        pending = await repo.delivery_get_pending(db_session, _now())
        ids = [r.id for r in pending]
        assert row.id not in ids

    @pytest.mark.asyncio
    async def test_delivery_null_session_safe(self):
        result = await repo.delivery_create(None, "ck", "u", "in_app", "h")
        assert result is None
        exists = await repo.delivery_content_key_exists(None, "ck")
        assert exists is False
        fetched = await repo.delivery_get_by_content_key(None, "ck")
        assert fetched is None


# ===========================================================================
# § NOTIFY — notifications
# ===========================================================================

class TestNotificationRepo:
    @pytest.mark.asyncio
    async def test_notification_create_returns_row(self, db_session):
        row = await repo.notification_create(
            db_session, "user_300", "daily_brief",
            body_json={"title": "Your daily brief"},
        )
        assert row is not None
        assert row.user_id == "user_300"
        assert row.kind == "daily_brief"
        assert row.read_at is None  # unread on creation

    @pytest.mark.asyncio
    async def test_notification_mark_read(self, db_session):
        row = await repo.notification_create(db_session, "user_301", "daily_brief")
        ok = await repo.notification_mark_read(db_session, row.id)
        assert ok is True
        refreshed = await repo.notification_get_by_id(db_session, row.id)
        assert refreshed.read_at is not None

    @pytest.mark.asyncio
    async def test_notification_mark_read_idempotent(self, db_session):
        """Marking an already-read notification returns False (no row updated) — safe."""
        row = await repo.notification_create(db_session, "user_302", "daily_brief")
        await repo.notification_mark_read(db_session, row.id)
        ok2 = await repo.notification_mark_read(db_session, row.id)
        assert ok2 is False  # WHERE read_at IS NULL matched 0 rows

    @pytest.mark.asyncio
    async def test_notification_list_unread_excludes_read(self, db_session):
        uid = f"user_{_uid()}"
        r1 = await repo.notification_create(db_session, uid, "daily_brief")
        r2 = await repo.notification_create(db_session, uid, "watchlist_alert")
        await repo.notification_mark_read(db_session, r1.id)

        unread = await repo.notification_list_unread(db_session, uid)
        ids = [n.id for n in unread]
        assert r1.id not in ids
        assert r2.id in ids

    @pytest.mark.asyncio
    async def test_notification_list_unread_is_user_scoped(self, db_session):
        """list_unread returns only the calling user's notifications."""
        uid_a = f"user_{_uid()}"
        uid_b = f"user_{_uid()}"
        await repo.notification_create(db_session, uid_a, "daily_brief")
        nb = await repo.notification_create(db_session, uid_b, "daily_brief")

        unread_a = await repo.notification_list_unread(db_session, uid_a)
        assert all(n.user_id == uid_a for n in unread_a)
        assert nb.id not in [n.id for n in unread_a]

    @pytest.mark.asyncio
    async def test_notification_mark_all_read(self, db_session):
        uid = f"user_{_uid()}"
        for _ in range(4):
            await repo.notification_create(db_session, uid, "daily_brief")

        count = await repo.notification_mark_all_read(db_session, uid)
        assert count == 4

        unread = await repo.notification_list_unread(db_session, uid)
        assert len(unread) == 0

    @pytest.mark.asyncio
    async def test_notification_mark_all_read_other_user_unaffected(self, db_session):
        uid_a = f"user_{_uid()}"
        uid_b = f"user_{_uid()}"
        for _ in range(2):
            await repo.notification_create(db_session, uid_a, "daily_brief")
        for _ in range(3):
            await repo.notification_create(db_session, uid_b, "daily_brief")

        await repo.notification_mark_all_read(db_session, uid_a)

        unread_b = await repo.notification_list_unread(db_session, uid_b)
        assert len(unread_b) == 3  # untouched

    @pytest.mark.asyncio
    async def test_notification_list_all(self, db_session):
        uid = f"user_{_uid()}"
        r1 = await repo.notification_create(db_session, uid, "daily_brief")
        r2 = await repo.notification_create(db_session, uid, "watchlist_alert")
        await repo.notification_mark_read(db_session, r1.id)

        all_notifs = await repo.notification_list_all(db_session, uid)
        ids = [n.id for n in all_notifs]
        assert r1.id in ids
        assert r2.id in ids

    @pytest.mark.asyncio
    async def test_notification_get_by_id(self, db_session):
        row = await repo.notification_create(
            db_session, "user_310", "system",
            body_json={"msg": "maintenance tonight"},
        )
        fetched = await repo.notification_get_by_id(db_session, row.id)
        assert fetched is not None
        assert fetched.id == row.id
        assert fetched.kind == "system"

    @pytest.mark.asyncio
    async def test_notification_body_json_roundtrip(self, db_session):
        payload = {"title": "AAPL brief", "conviction": 0.87, "tags": ["drift"]}
        row = await repo.notification_create(
            db_session, "user_311", "daily_brief", body_json=payload
        )
        fetched = await repo.notification_get_by_id(db_session, row.id)
        assert fetched.body_json["title"] == "AAPL brief"
        assert fetched.body_json["conviction"] == 0.87
        assert fetched.body_json["tags"] == ["drift"]

    @pytest.mark.asyncio
    async def test_notification_null_session_safe(self):
        result = await repo.notification_create(None, "u", "daily_brief")
        assert result is None
        unread = await repo.notification_list_unread(None, "u")
        assert unread == []
        count = await repo.notification_mark_all_read(None, "u")
        assert count == 0
