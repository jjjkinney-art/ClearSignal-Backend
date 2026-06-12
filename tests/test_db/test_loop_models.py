"""
Phase 10A · Slice 1 — Continuous Intelligence Loop ORM model tests.

Validates that all 5 loop tables (+ BriefingSession extension):
  - can be created in an in-memory SQLite DB via Base.metadata.create_all
  - accept round-trip writes and reads
  - enforce their UNIQUE constraints
  - store JSON columns correctly
  - honour nullable/non-nullable invariants

Uses the db_session fixture (SQLite in-memory) from conftest.py.
No scheduler, lock service, or delivery logic is tested here — Slice 1 is schema only.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone, timedelta

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _id() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _soon(seconds: int = 120) -> datetime:
    return datetime.now(timezone.utc) + timedelta(seconds=seconds)


# ---------------------------------------------------------------------------
# 20. ScheduledJob
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_scheduled_job_roundtrip(db_session):
    """Create a ScheduledJob and read it back with all fields intact."""
    from app.db.models import ScheduledJob
    from sqlalchemy import select

    job = ScheduledJob(
        id=_id(),
        job_type="daily_brief",
        target_key="user-abc",
        period_bucket="2026-06-13",
        state="scheduled",
        next_run_utc=_soon(3600),
        cadence="daily",
        catch_up_window_s=3600,
        attempts=0,
        max_attempts=3,
        holder_id=None,
        lease_expires_utc=None,
        fence_token=0,
        payload_json={"tz": "America/New_York"},
        last_generated_at=None,
        created_at=_now(),
        updated_at=_now(),
    )
    db_session.add(job)
    await db_session.flush()

    result = await db_session.execute(
        select(ScheduledJob).where(ScheduledJob.target_key == "user-abc")
    )
    fetched = result.scalar_one()
    assert fetched.job_type == "daily_brief"
    assert fetched.state == "scheduled"
    assert fetched.cadence == "daily"
    assert fetched.fence_token == 0
    assert fetched.holder_id is None
    assert fetched.lease_expires_utc is None
    assert isinstance(fetched.payload_json, dict)
    assert fetched.payload_json["tz"] == "America/New_York"
    assert fetched.last_generated_at is None


@pytest.mark.asyncio
async def test_scheduled_job_unique_constraint(db_session):
    """UNIQUE(job_type, target_key, period_bucket) prevents duplicate enqueue."""
    from app.db.models import ScheduledJob

    kwargs = dict(
        job_type="daily_brief", target_key="user-abc", period_bucket="2026-06-13",
        created_at=_now(), updated_at=_now(),
    )
    db_session.add(ScheduledJob(id=_id(), **kwargs))
    db_session.add(ScheduledJob(id=_id(), **kwargs))  # duplicate triple
    with pytest.raises(Exception):
        await db_session.flush()
    await db_session.rollback()


@pytest.mark.asyncio
async def test_scheduled_job_different_period_bucket_allowed(db_session):
    """Same (job_type, target_key) with different period_bucket is allowed."""
    from app.db.models import ScheduledJob

    base = dict(job_type="watchlist_scan", target_key="user-abc",
                created_at=_now(), updated_at=_now())
    db_session.add(ScheduledJob(id=_id(), period_bucket="2026-06-13", **base))
    db_session.add(ScheduledJob(id=_id(), period_bucket="2026-06-14", **base))
    await db_session.flush()  # must not raise


@pytest.mark.asyncio
async def test_scheduled_job_drift_only_no_cadence(db_session):
    """Drift-only jobs have cadence=None and no next_run_utc."""
    from app.db.models import ScheduledJob
    from sqlalchemy import select

    job = ScheduledJob(
        id=_id(),
        job_type="dossier_refresh",
        target_key="NVDA",
        period_bucket="drift",
        state="scheduled",
        cadence=None,
        next_run_utc=None,
        created_at=_now(),
        updated_at=_now(),
    )
    db_session.add(job)
    await db_session.flush()

    result = await db_session.execute(
        select(ScheduledJob).where(ScheduledJob.target_key == "NVDA")
    )
    fetched = result.scalar_one()
    assert fetched.cadence is None
    assert fetched.next_run_utc is None


@pytest.mark.asyncio
async def test_scheduled_job_claimed_state(db_session):
    """A claimed job has holder_id, lease_expires_utc, and fence_token > 0."""
    from app.db.models import ScheduledJob
    from sqlalchemy import select

    job = ScheduledJob(
        id=_id(),
        job_type="daily_brief",
        target_key="user-xyz",
        period_bucket="2026-06-13",
        state="claimed",
        holder_id="worker-1",
        lease_expires_utc=_soon(120),
        fence_token=1,
        created_at=_now(),
        updated_at=_now(),
    )
    db_session.add(job)
    await db_session.flush()

    result = await db_session.execute(
        select(ScheduledJob).where(ScheduledJob.target_key == "user-xyz")
    )
    fetched = result.scalar_one()
    assert fetched.state == "claimed"
    assert fetched.holder_id == "worker-1"
    assert fetched.fence_token == 1
    assert fetched.lease_expires_utc is not None


# ---------------------------------------------------------------------------
# 21. JobLock
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_job_lock_roundtrip(db_session):
    """Create a JobLock and read it back."""
    from app.db.models import JobLock
    from sqlalchemy import select

    lock = JobLock(
        lock_name="loop:tick",
        holder_id="worker-1",
        acquired_utc=_now(),
        lease_expires_utc=_soon(120),
        fence_token=7,
    )
    db_session.add(lock)
    await db_session.flush()

    result = await db_session.execute(
        select(JobLock).where(JobLock.lock_name == "loop:tick")
    )
    fetched = result.scalar_one()
    assert fetched.holder_id == "worker-1"
    assert fetched.fence_token == 7


@pytest.mark.asyncio
async def test_job_lock_pk_uniqueness(db_session):
    """Two JobLock rows with the same lock_name must raise IntegrityError."""
    from app.db.models import JobLock

    kwargs = dict(holder_id="w1", acquired_utc=_now(), lease_expires_utc=_soon())
    db_session.add(JobLock(lock_name="loop:tick", fence_token=1, **kwargs))
    db_session.add(JobLock(lock_name="loop:tick", fence_token=2, **kwargs))  # duplicate PK
    with pytest.raises(Exception):
        await db_session.flush()
    await db_session.rollback()


@pytest.mark.asyncio
async def test_job_lock_multiple_named_locks(db_session):
    """Different lock names coexist without conflict."""
    from app.db.models import JobLock

    job_id = _id()
    kwargs = dict(holder_id="w1", acquired_utc=_now(), lease_expires_utc=_soon())
    db_session.add(JobLock(lock_name="loop:tick",          fence_token=3, **kwargs))
    db_session.add(JobLock(lock_name=f"loop:job:{job_id}", fence_token=1, **kwargs))
    await db_session.flush()  # must not raise


# ---------------------------------------------------------------------------
# 22. JobRun  (append-only audit)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_job_run_roundtrip(db_session):
    """Create a JobRun and read it back with all fields."""
    from app.db.models import JobRun
    from sqlalchemy import select

    job_id = _id()
    run = JobRun(
        id=_id(),
        job_id=job_id,
        work_key="abc123def456",
        job_type="daily_brief",
        target_key="user-abc",
        period_bucket="2026-06-13",
        started_utc=_now(),
        finished_utc=_now(),
        outcome="succeeded",
        spent_llm_calls=2,
        drift_hit=True,
        error=None,
        holder_id="worker-1",
        fence_token=3,
    )
    db_session.add(run)
    await db_session.flush()

    result = await db_session.execute(
        select(JobRun).where(JobRun.job_id == job_id)
    )
    fetched = result.scalar_one()
    assert fetched.outcome == "succeeded"
    assert fetched.spent_llm_calls == 2
    assert fetched.drift_hit is True
    assert fetched.error is None
    assert fetched.fence_token == 3


@pytest.mark.asyncio
async def test_job_run_multiple_per_job(db_session):
    """Multiple runs per job are allowed (retry history)."""
    from app.db.models import JobRun
    from sqlalchemy import select

    job_id = _id()
    work_key = "wk-001"
    runs = [
        ("failed",    1, "timeout"),
        ("failed",    2, "timeout"),
        ("succeeded", 3, None),
    ]
    for outcome, fence, err in runs:
        db_session.add(JobRun(
            id=_id(), job_id=job_id,
            work_key=work_key,
            job_type="watchlist_scan",
            target_key="user-abc",
            period_bucket="2026-06-13",
            started_utc=_now(),
            finished_utc=_now(),
            outcome=outcome,
            error=err,
            holder_id="worker-1",
            fence_token=fence,
        ))
    await db_session.flush()

    result = await db_session.execute(
        select(JobRun).where(JobRun.job_id == job_id)
    )
    rows = result.scalars().all()
    assert len(rows) == 3
    succeeded = [r for r in rows if r.outcome == "succeeded"]
    assert len(succeeded) == 1
    assert succeeded[0].error is None


@pytest.mark.asyncio
async def test_job_run_running_state(db_session):
    """A running job has finished_utc=None and outcome='running'."""
    from app.db.models import JobRun
    from sqlalchemy import select

    run = JobRun(
        id=_id(),
        job_id=_id(),
        work_key="wk-running",
        job_type="dossier_refresh",
        target_key="NVDA",
        period_bucket="drift",
        started_utc=_now(),
        finished_utc=None,  # still running
        outcome="running",
        holder_id="worker-2",
        fence_token=0,
    )
    db_session.add(run)
    await db_session.flush()

    result = await db_session.execute(
        select(JobRun).where(JobRun.work_key == "wk-running")
    )
    fetched = result.scalar_one()
    assert fetched.outcome == "running"
    assert fetched.finished_utc is None


# ---------------------------------------------------------------------------
# 23. DeliveryLedger
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_delivery_ledger_roundtrip(db_session):
    """Create a DeliveryLedger row and read it back."""
    from app.db.models import DeliveryLedger
    from sqlalchemy import select

    briefing_id = _id()
    row = DeliveryLedger(
        id=_id(),
        content_key="ck-abc123",
        target_key="user-abc",
        channel="in_app",
        content_hash="sha256-deadbeef",
        artifact_ref=briefing_id,
        status="pending",
        attempts=0,
        not_before_utc=None,
        created_at=_now(),
        delivered_at=None,
    )
    db_session.add(row)
    await db_session.flush()

    result = await db_session.execute(
        select(DeliveryLedger).where(DeliveryLedger.content_key == "ck-abc123")
    )
    fetched = result.scalar_one()
    assert fetched.channel == "in_app"
    assert fetched.status == "pending"
    assert fetched.artifact_ref == briefing_id
    assert fetched.delivered_at is None


@pytest.mark.asyncio
async def test_delivery_ledger_content_key_unique(db_session):
    """UNIQUE(content_key) is the duplicate-delivery hard stop."""
    from app.db.models import DeliveryLedger

    kwargs = dict(
        target_key="user-abc", channel="in_app",
        content_hash="sha256-xyz", created_at=_now(),
    )
    db_session.add(DeliveryLedger(id=_id(), content_key="ck-dupe", **kwargs))
    db_session.add(DeliveryLedger(id=_id(), content_key="ck-dupe", **kwargs))  # duplicate
    with pytest.raises(Exception):
        await db_session.flush()
    await db_session.rollback()


@pytest.mark.asyncio
async def test_delivery_ledger_different_content_keys(db_session):
    """Different content_keys for the same user are allowed."""
    from app.db.models import DeliveryLedger

    kwargs = dict(
        target_key="user-abc", channel="in_app",
        content_hash="sha256-xyz", created_at=_now(),
    )
    db_session.add(DeliveryLedger(id=_id(), content_key="ck-001", **kwargs))
    db_session.add(DeliveryLedger(id=_id(), content_key="ck-002", **kwargs))
    await db_session.flush()  # must not raise


@pytest.mark.asyncio
async def test_delivery_ledger_delivered_state(db_session):
    """A delivered row has delivered_at set and status='delivered'."""
    from app.db.models import DeliveryLedger
    from sqlalchemy import select

    delivered_ts = _now()
    row = DeliveryLedger(
        id=_id(),
        content_key="ck-delivered",
        target_key="user-abc",
        channel="in_app",
        content_hash="sha256-done",
        status="delivered",
        attempts=1,
        created_at=_now(),
        delivered_at=delivered_ts,
    )
    db_session.add(row)
    await db_session.flush()

    result = await db_session.execute(
        select(DeliveryLedger).where(DeliveryLedger.content_key == "ck-delivered")
    )
    fetched = result.scalar_one()
    assert fetched.status == "delivered"
    assert fetched.delivered_at is not None
    assert fetched.attempts == 1


# ---------------------------------------------------------------------------
# 24. Notification
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_notification_roundtrip(db_session):
    """Create a Notification and read it back."""
    from app.db.models import Notification
    from sqlalchemy import select

    body = {"headline": "NVDA dossier updated", "ticker": "NVDA", "kind": "dossier_update"}
    notif = Notification(
        id=_id(),
        user_id="user-abc",
        kind="dossier_update",
        body_json=body,
        read_at=None,
        created_at=_now(),
    )
    db_session.add(notif)
    await db_session.flush()

    result = await db_session.execute(
        select(Notification).where(Notification.user_id == "user-abc")
    )
    fetched = result.scalar_one()
    assert fetched.kind == "dossier_update"
    assert fetched.read_at is None
    assert isinstance(fetched.body_json, dict)
    assert fetched.body_json["ticker"] == "NVDA"


@pytest.mark.asyncio
async def test_notification_multiple_per_user(db_session):
    """Multiple notifications per user are allowed."""
    from app.db.models import Notification
    from sqlalchemy import select

    kinds = ["daily_brief", "watchlist_alert", "dossier_update"]
    for kind in kinds:
        db_session.add(Notification(
            id=_id(), user_id="user-multi", kind=kind,
            body_json={"kind": kind}, created_at=_now(),
        ))
    await db_session.flush()

    result = await db_session.execute(
        select(Notification).where(Notification.user_id == "user-multi")
    )
    rows = result.scalars().all()
    assert len(rows) == 3


@pytest.mark.asyncio
async def test_notification_mark_read(db_session):
    """read_at transitions from None to a timestamp."""
    from app.db.models import Notification
    from sqlalchemy import select

    notif_id = _id()
    db_session.add(Notification(
        id=notif_id, user_id="user-read", kind="daily_brief",
        body_json={}, read_at=None, created_at=_now(),
    ))
    await db_session.flush()

    # Simulate marking as read
    result = await db_session.execute(
        select(Notification).where(Notification.id == notif_id)
    )
    fetched = result.scalar_one()
    assert fetched.read_at is None
    fetched.read_at = _now()
    await db_session.flush()

    result2 = await db_session.execute(
        select(Notification).where(Notification.id == notif_id)
    )
    updated = result2.scalar_one()
    assert updated.read_at is not None


# ---------------------------------------------------------------------------
# BriefingSession extension (Phase 10A columns)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_briefing_session_new_columns(db_session):
    """BriefingSession accepts content_hash and delivery_channel (nullable)."""
    from app.db.models import BriefingSession
    from sqlalchemy import select
    from datetime import date

    today = date.today()
    row = BriefingSession(
        id=_id(),
        session_date=today,
        session_id="sess-loop-001",
        tickers_covered='["NVDA", "AAPL"]',
        status="generated",
        metadata_json="{}",
        content_hash="sha256-abc123",
        delivery_channel="in_app",
        created_at=_now(),
    )
    db_session.add(row)
    await db_session.flush()

    result = await db_session.execute(
        select(BriefingSession).where(BriefingSession.session_id == "sess-loop-001")
    )
    fetched = result.scalar_one()
    assert fetched.content_hash == "sha256-abc123"
    assert fetched.delivery_channel == "in_app"
    assert fetched.status == "generated"


@pytest.mark.asyncio
async def test_briefing_session_new_columns_nullable(db_session):
    """BriefingSession with NULL content_hash and delivery_channel is valid."""
    from app.db.models import BriefingSession
    from sqlalchemy import select
    from datetime import date

    row = BriefingSession(
        id=_id(),
        session_date=date.today(),
        session_id="sess-loop-002",
        status="pending",
        created_at=_now(),
        # content_hash and delivery_channel omitted — must default to None
    )
    db_session.add(row)
    await db_session.flush()

    result = await db_session.execute(
        select(BriefingSession).where(BriefingSession.session_id == "sess-loop-002")
    )
    fetched = result.scalar_one()
    assert fetched.content_hash is None
    assert fetched.delivery_channel is None


# ---------------------------------------------------------------------------
# Smoke test — all 5 loop tables accept writes together
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_all_loop_tables_exist(db_session):
    """Smoke: create one row in each of the 5 loop tables without error."""
    from app.db.models import (
        ScheduledJob, JobLock, JobRun, DeliveryLedger, Notification,
    )

    job_id = _id()
    now = _now()

    job = ScheduledJob(
        id=job_id, job_type="daily_brief",
        target_key="user-smoke", period_bucket="2026-06-13",
        state="scheduled", fence_token=0,
        created_at=now, updated_at=now,
    )
    lock = JobLock(
        lock_name="loop:tick",
        holder_id="worker-smoke",
        acquired_utc=now,
        lease_expires_utc=_soon(120),
        fence_token=1,
    )
    run = JobRun(
        id=_id(), job_id=job_id,
        work_key="wk-smoke",
        job_type="daily_brief",
        target_key="user-smoke",
        period_bucket="2026-06-13",
        started_utc=now, finished_utc=now,
        outcome="succeeded",
        holder_id="worker-smoke", fence_token=1,
    )
    ledger = DeliveryLedger(
        id=_id(), content_key="ck-smoke",
        target_key="user-smoke", channel="in_app",
        content_hash="sha256-smoke",
        status="pending", created_at=now,
    )
    notif = Notification(
        id=_id(), user_id="user-smoke",
        kind="daily_brief", body_json={},
        created_at=now,
    )

    for obj in [job, lock, run, ledger, notif]:
        db_session.add(obj)

    await db_session.flush()
    # If we reach here, all 5 loop tables exist and accept writes.
