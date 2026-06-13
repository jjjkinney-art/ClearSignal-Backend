"""
Phase 10A · Slice 2+3 — Loop persistence layer.

Sections
--------
  § LOCK     — job_locks  (Slice 2, exclusively owned by loop_lock_service.py)
  § JOB      — scheduled_jobs  (Slice 3)
  § RUN      — job_runs  (append-only audit, Slice 3)
  § DELIVERY — delivery_ledger  (Slice 3)
  § NOTIFY   — notifications  (Slice 3)

Conventions (matching existing repos):
  * session is None → return safe default (None, False, []) — never raise
  * await session.flush() only — no commit (caller controls transaction)
  * lazy model imports inside each function to avoid circular imports at boot
  * no business logic — decision making lives in loop_*_service layers
  * synchronize_session=False on bulk UPDATE/DELETE (async-safe; the
    service reads current state before writing so identity map is irrelevant)
  * CAS (compare-and-swap) via WHERE expected_field=expected_value — if
    rowcount == 0, a concurrent writer won the race; caller retries or backs off
  * UNIQUE conflicts absorbed via begin_nested() savepoint — outer transaction
    remains valid after a conflict on INSERT

job_runs append-only rule
  The running→terminal UPDATE on a job_run is the ONE permitted UPDATE on
  that table.  No other UPDATE or DELETE may target job_runs.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)

logger = logging.getLogger(__name__)


# ===========================================================================
# § LOCK — job_locks  (exclusively managed by loop_lock_service.py)
# ===========================================================================

def _lock_model():
    from app.db.models import JobLock
    return JobLock


# ---------------------------------------------------------------------------
# Lock — READ
# ---------------------------------------------------------------------------

async def lock_read(session, lock_name: str) -> Optional[Any]:
    """Return the current JobLock row for *lock_name*, or None if absent."""
    if session is None:
        return None
    try:
        from sqlalchemy import select
        result = await session.execute(
            select(_lock_model()).where(_lock_model().lock_name == lock_name)
        )
        return result.scalar_one_or_none()
    except Exception as exc:
        logger.warning("[loop_repo] lock_read failed for %r: %r", lock_name, exc)
        return None


# ---------------------------------------------------------------------------
# Lock — ACQUIRE — INSERT (new lock, no prior row)
# ---------------------------------------------------------------------------

async def lock_insert(
    session,
    lock_name: str,
    holder_id: str,
    acquired_utc: datetime,
    lease_expires_utc: datetime,
    fence_token: int,
) -> bool:
    """
    Insert a new lock row.  Returns True if inserted, False on PK conflict.

    Uses a nested savepoint so a concurrent INSERT conflict does not corrupt
    the outer transaction — the savepoint is rolled back and the outer
    session remains usable.  On SQLite (single-process async) conflicts are
    practically impossible; on Postgres this guards the true parallel case.
    """
    if session is None:
        return False
    try:
        async with session.begin_nested():  # SAVEPOINT
            session.add(_lock_model()(
                lock_name=lock_name,
                holder_id=holder_id,
                acquired_utc=acquired_utc,
                lease_expires_utc=lease_expires_utc,
                fence_token=fence_token,
            ))
            await session.flush()
        return True
    except Exception as exc:
        logger.debug(
            "[loop_repo] lock_insert conflict for %r (expected in races): %r",
            lock_name, exc,
        )
        return False


# ---------------------------------------------------------------------------
# Lock — ACQUIRE — UPDATE (existing row: expired or re-acquire by same holder)
# ---------------------------------------------------------------------------

async def lock_update_cas(
    session,
    lock_name: str,
    expected_fence_token: int,
    holder_id: str,
    acquired_utc: datetime,
    lease_expires_utc: datetime,
    new_fence_token: int,
) -> bool:
    """
    Compare-and-swap update: overwrite the lock row only when the current
    fence_token matches *expected_fence_token*.

    Returns True if exactly one row was updated (CAS succeeded).
    Returns False if zero rows were updated (another holder raced us,
    or the row was deleted between our read and our write).
    """
    if session is None:
        return False
    try:
        from sqlalchemy import update
        stmt = (
            update(_lock_model())
            .where(
                _lock_model().lock_name == lock_name,
                _lock_model().fence_token == expected_fence_token,
            )
            .values(
                holder_id=holder_id,
                acquired_utc=acquired_utc,
                lease_expires_utc=lease_expires_utc,
                fence_token=new_fence_token,
            )
            .execution_options(synchronize_session=False)
        )
        result = await session.execute(stmt)
        await session.flush()
        return result.rowcount > 0
    except Exception as exc:
        logger.warning("[loop_repo] lock_update_cas failed for %r: %r", lock_name, exc)
        return False


# ---------------------------------------------------------------------------
# Lock — RENEW
# ---------------------------------------------------------------------------

async def lock_renew(
    session,
    lock_name: str,
    holder_id: str,
    fence_token: int,
    new_expires: datetime,
) -> bool:
    """
    Extend lease_expires_utc for an active lock.

    Returns True only when holder_id AND fence_token both match the current
    row — rejects zombie holders carrying a stale token from a prior lease.
    """
    if session is None:
        return False
    try:
        from sqlalchemy import update
        stmt = (
            update(_lock_model())
            .where(
                _lock_model().lock_name == lock_name,
                _lock_model().holder_id == holder_id,
                _lock_model().fence_token == fence_token,
            )
            .values(lease_expires_utc=new_expires)
            .execution_options(synchronize_session=False)
        )
        result = await session.execute(stmt)
        await session.flush()
        return result.rowcount > 0
    except Exception as exc:
        logger.warning("[loop_repo] lock_renew failed for %r: %r", lock_name, exc)
        return False


# ---------------------------------------------------------------------------
# Lock — RELEASE
# ---------------------------------------------------------------------------

async def lock_release(
    session,
    lock_name: str,
    holder_id: str,
    fence_token: int,
) -> bool:
    """
    Delete the lock row only when holder_id AND fence_token match.

    Returns True if deleted.  Returns False for:
      - no row (already released or never acquired)
      - wrong holder_id (different process)
      - stale fence_token (zombie process whose lease was reclaimed)

    Idempotent from the caller's perspective: calling release() twice for
    the same (holder, token) → first call returns True, second returns False
    (row already gone) — the caller may treat both as success.
    """
    if session is None:
        return False
    try:
        from sqlalchemy import delete
        stmt = (
            delete(_lock_model())
            .where(
                _lock_model().lock_name == lock_name,
                _lock_model().holder_id == holder_id,
                _lock_model().fence_token == fence_token,
            )
            .execution_options(synchronize_session=False)
        )
        result = await session.execute(stmt)
        await session.flush()
        return result.rowcount > 0
    except Exception as exc:
        logger.warning("[loop_repo] lock_release failed for %r: %r", lock_name, exc)
        return False


# ---------------------------------------------------------------------------
# Lock — REAP
# ---------------------------------------------------------------------------

async def lock_reap_expired(session, now: datetime) -> List[str]:
    """
    Delete all lock rows where lease_expires_utc < *now*.

    Returns the list of reclaimed lock_names.  Called by the tick loop's
    reap step (spec §2.2) and by reap_expired_locks() in the service.
    """
    if session is None:
        return []
    try:
        from sqlalchemy import select, delete
        # Read names first so we can return them
        name_result = await session.execute(
            select(_lock_model().lock_name).where(_lock_model().lease_expires_utc < now)
        )
        names = [row[0] for row in name_result.fetchall()]
        if not names:
            return []
        await session.execute(
            delete(_lock_model())
            .where(_lock_model().lock_name.in_(names))
            .execution_options(synchronize_session=False)
        )
        await session.flush()
        logger.debug("[loop_repo] reaped %d expired locks: %s", len(names), names)
        return names
    except Exception as exc:
        logger.warning("[loop_repo] lock_reap_expired failed: %r", exc)
        return []


# ===========================================================================
# § JOB — scheduled_jobs
# ===========================================================================

def _job_model():
    from app.db.models import ScheduledJob
    return ScheduledJob


# ---------------------------------------------------------------------------
# Job — READ
# ---------------------------------------------------------------------------

async def job_get_by_id(session, job_id: str) -> Optional[Any]:
    """Return the ScheduledJob row for *job_id*, or None.

    Uses populate_existing=True so the result always reflects the current
    DB state rather than a potentially-stale identity-map entry.
    """
    if session is None:
        return None
    try:
        from sqlalchemy import select
        result = await session.execute(
            select(_job_model())
            .where(_job_model().id == job_id)
            .execution_options(populate_existing=True)
        )
        return result.scalar_one_or_none()
    except Exception as exc:
        logger.warning("[loop_repo] job_get_by_id failed for %r: %r", job_id, exc)
        return None


async def job_get_by_identity(
    session,
    job_type: str,
    target_key: str,
    period_bucket: str,
) -> Optional[Any]:
    """Lookup by UNIQUE(job_type, target_key, period_bucket)."""
    if session is None:
        return None
    try:
        from sqlalchemy import select
        J = _job_model()
        result = await session.execute(
            select(J)
            .where(
                J.job_type == job_type,
                J.target_key == target_key,
                J.period_bucket == period_bucket,
            )
            .execution_options(populate_existing=True)
        )
        return result.scalar_one_or_none()
    except Exception as exc:
        logger.warning("[loop_repo] job_get_by_identity failed: %r", exc)
        return None


# ---------------------------------------------------------------------------
# Job — CREATE (idempotent get-or-create via savepoint)
# ---------------------------------------------------------------------------

async def job_create(
    session,
    job_type: str,
    target_key: str,
    period_bucket: str,
    *,
    next_run_utc: Optional[datetime] = None,
    cadence: Optional[str] = None,
    max_attempts: int = 3,
    catch_up_window_s: int = 3600,
    payload_json: Optional[Dict] = None,
) -> Optional[Any]:
    """
    Insert a new ScheduledJob row.

    Idempotent: if UNIQUE(job_type, target_key, period_bucket) already exists
    the INSERT is silently skipped via a savepoint, and the existing row is
    returned.  The scheduler uses this to enqueue without checking first.

    Returns the row (new or pre-existing), or None on unexpected error.
    """
    if session is None:
        return None
    J = _job_model()
    new_id = _uuid()
    try:
        async with session.begin_nested():
            session.add(J(
                id=new_id,
                job_type=job_type,
                target_key=target_key,
                period_bucket=period_bucket,
                next_run_utc=next_run_utc,
                cadence=cadence,
                max_attempts=max_attempts,
                catch_up_window_s=catch_up_window_s,
                payload_json=payload_json or {},
                state="scheduled",
            ))
            await session.flush()
    except Exception:
        # UNIQUE conflict — row already exists; fall through to SELECT
        pass
    return await job_get_by_identity(session, job_type, target_key, period_bucket)


# ---------------------------------------------------------------------------
# Job — CLAIM (select-then-CAS — safe for concurrent workers)
# ---------------------------------------------------------------------------

async def job_claim_due(
    session,
    now: datetime,
    holder_id: str,
    lease_expires_utc: datetime,
    batch_size: int = 10,
) -> List[Any]:
    """
    Select up to *batch_size* due jobs and atomically claim each one.

    A job is "due" when:
        state = 'scheduled'
        AND (next_run_utc IS NULL OR next_run_utc <= now)

    For each candidate, a CAS UPDATE (WHERE id=... AND state='scheduled')
    is attempted.  Rows where a concurrent worker already claimed the job
    (state changed between SELECT and UPDATE) are silently dropped.

    Returns the list of successfully claimed rows (re-fetched after UPDATE).
    """
    if session is None:
        return []
    try:
        from sqlalchemy import select, update
        J = _job_model()
        # SELECT candidates
        stmt = (
            select(J)
            .where(
                J.state == "scheduled",
                (J.next_run_utc == None) | (J.next_run_utc <= now),  # noqa: E711
            )
            .order_by(J.next_run_utc.nullsfirst())
            .limit(batch_size)
        )
        rows = (await session.execute(stmt)).scalars().all()
        if not rows:
            return []

        claimed = []
        for row in rows:
            result = await session.execute(
                update(J)
                .where(J.id == row.id, J.state == "scheduled")
                .values(
                    state="claimed",
                    holder_id=holder_id,
                    lease_expires_utc=lease_expires_utc,
                    fence_token=J.fence_token + 1,
                    attempts=J.attempts + 1,
                )
                .execution_options(synchronize_session=False)
            )
            if result.rowcount > 0:
                # populate_existing forces a DB read past the identity-map cache
                # so the returned object reflects the just-written state.
                fresh = await session.execute(
                    select(J)
                    .where(J.id == row.id)
                    .execution_options(populate_existing=True)
                )
                refreshed = fresh.scalar_one_or_none()
                if refreshed is not None:
                    claimed.append(refreshed)
        await session.flush()
        return claimed
    except Exception as exc:
        logger.warning("[loop_repo] job_claim_due failed: %r", exc)
        return []


# ---------------------------------------------------------------------------
# Job — STATE TRANSITIONS
# ---------------------------------------------------------------------------

async def job_update_state(
    session,
    job_id: str,
    new_state: str,
    *,
    expected_state: Optional[str] = None,
) -> bool:
    """
    Unconditional (or guarded) state transition.

    If *expected_state* is given, the UPDATE only applies when the current
    state matches — acts as a lightweight CAS to prevent double-transition.
    Returns True if a row was updated.
    """
    if session is None:
        return False
    try:
        from sqlalchemy import update
        J = _job_model()
        conditions = [J.id == job_id]
        if expected_state is not None:
            conditions.append(J.state == expected_state)
        result = await session.execute(
            update(J)
            .where(*conditions)
            .values(state=new_state)
            .execution_options(synchronize_session=False)
        )
        await session.flush()
        return result.rowcount > 0
    except Exception as exc:
        logger.warning(
            "[loop_repo] job_update_state failed for %r → %r: %r",
            job_id, new_state, exc,
        )
        return False


async def job_mark_success(
    session,
    job_id: str,
    holder_id: str,
    fence_token: int,
    *,
    last_generated_at: Optional[datetime] = None,
) -> bool:
    """
    Transition a claimed job to 'succeeded'.

    Validates holder_id + fence_token so a zombie worker whose lease was
    reclaimed cannot stamp the wrong job as succeeded.
    Clears the lease fields on success.
    """
    if session is None:
        return False
    try:
        from sqlalchemy import update
        J = _job_model()
        vals: Dict = {
            "state": "succeeded",
            "holder_id": None,
            "lease_expires_utc": None,
            "last_generated_at": last_generated_at or _now(),
        }
        result = await session.execute(
            update(J)
            .where(
                J.id == job_id,
                J.holder_id == holder_id,
                J.fence_token == fence_token,
            )
            .values(**vals)
            .execution_options(synchronize_session=False)
        )
        await session.flush()
        return result.rowcount > 0
    except Exception as exc:
        logger.warning("[loop_repo] job_mark_success failed for %r: %r", job_id, exc)
        return False


async def job_mark_failure(
    session,
    job_id: str,
    holder_id: str,
    fence_token: int,
    *,
    error: Optional[str] = None,
    next_run_utc: Optional[datetime] = None,
) -> bool:
    """
    Transition a claimed job back to 'failed'.

    The service layer decides whether to retry (pass a new next_run_utc)
    or call job_mark_dead_letter() when attempts >= max_attempts.
    Clears the lease fields; sets next_run_utc for retry scheduling.
    """
    if session is None:
        return False
    try:
        from sqlalchemy import update
        J = _job_model()
        result = await session.execute(
            update(J)
            .where(
                J.id == job_id,
                J.holder_id == holder_id,
                J.fence_token == fence_token,
            )
            .values(
                state="failed",
                holder_id=None,
                lease_expires_utc=None,
                next_run_utc=next_run_utc,
            )
            .execution_options(synchronize_session=False)
        )
        await session.flush()
        return result.rowcount > 0
    except Exception as exc:
        logger.warning("[loop_repo] job_mark_failure failed for %r: %r", job_id, exc)
        return False


async def job_mark_dead_letter(
    session,
    job_id: str,
    holder_id: str,
    fence_token: int,
) -> bool:
    """
    Transition a job to the terminal 'dead_letter' state.

    Called by the service when attempts >= max_attempts (or on unrecoverable
    error).  Validates holder_id + fence_token; clears lease fields.
    Once dead-lettered, the job will not be claimed again.
    """
    if session is None:
        return False
    try:
        from sqlalchemy import update
        J = _job_model()
        result = await session.execute(
            update(J)
            .where(
                J.id == job_id,
                J.holder_id == holder_id,
                J.fence_token == fence_token,
            )
            .values(
                state="dead_letter",
                holder_id=None,
                lease_expires_utc=None,
            )
            .execution_options(synchronize_session=False)
        )
        await session.flush()
        return result.rowcount > 0
    except Exception as exc:
        logger.warning("[loop_repo] job_mark_dead_letter failed for %r: %r", job_id, exc)
        return False


# ===========================================================================
# § RUN — job_runs  (append-only; one UPDATE permitted: running → terminal)
# ===========================================================================

def _run_model():
    from app.db.models import JobRun
    return JobRun


async def run_append(
    session,
    job_id: str,
    work_key: str,
    job_type: str,
    target_key: str,
    period_bucket: str,
    holder_id: str,
    fence_token: int,
    *,
    started_utc: Optional[datetime] = None,
) -> Optional[Any]:
    """
    Append an audit row for the start of a job execution.

    outcome is set to 'running'; call run_finish() to stamp the terminal
    outcome when the job completes (or fails).
    Returns the new row, or None on error.
    """
    if session is None:
        return None
    try:
        R = _run_model()
        row = R(
            id=_uuid(),
            job_id=job_id,
            work_key=work_key,
            job_type=job_type,
            target_key=target_key,
            period_bucket=period_bucket,
            holder_id=holder_id,
            fence_token=fence_token,
            started_utc=started_utc or _now(),
            outcome="running",
        )
        session.add(row)
        await session.flush()
        return row
    except Exception as exc:
        logger.warning("[loop_repo] run_append failed for job %r: %r", job_id, exc)
        return None


async def run_finish(
    session,
    run_id: str,
    outcome: str,
    *,
    spent_llm_calls: int = 0,
    drift_hit: bool = False,
    error: Optional[str] = None,
    finished_utc: Optional[datetime] = None,
) -> bool:
    """
    Stamp the terminal outcome on an existing run row.

    This is the ONE permitted UPDATE on job_runs: transitioning a 'running'
    row to a terminal state.  All other rows are immutable after creation.
    Returns True if the row was updated.
    """
    if session is None:
        return False
    try:
        from sqlalchemy import update
        R = _run_model()
        result = await session.execute(
            update(R)
            .where(R.id == run_id, R.outcome == "running")
            .values(
                outcome=outcome,
                finished_utc=finished_utc or _now(),
                spent_llm_calls=spent_llm_calls,
                drift_hit=drift_hit,
                error=error,
            )
            .execution_options(synchronize_session=False)
        )
        await session.flush()
        return result.rowcount > 0
    except Exception as exc:
        logger.warning("[loop_repo] run_finish failed for %r: %r", run_id, exc)
        return False


async def run_get_history(
    session,
    job_id: str,
    limit: int = 50,
) -> List[Any]:
    """Return the run history for *job_id* ordered by started_utc descending."""
    if session is None:
        return []
    try:
        from sqlalchemy import select
        R = _run_model()
        result = await session.execute(
            select(R)
            .where(R.job_id == job_id)
            .order_by(R.started_utc.desc())
            .limit(limit)
            .execution_options(populate_existing=True)
        )
        return result.scalars().all()
    except Exception as exc:
        logger.warning("[loop_repo] run_get_history failed for job %r: %r", job_id, exc)
        return []


async def run_lookup_by_work_key(
    session,
    work_key: str,
    *,
    outcome: Optional[str] = None,
) -> Optional[Any]:
    """
    Return the most recent run for *work_key*, optionally filtered by outcome.

    Primary use: idempotency short-circuit — the scheduler calls this with
    outcome='succeeded' before invoking a producer; if a row is found,
    the job is skipped (spec §3.1).
    """
    if session is None:
        return None
    try:
        from sqlalchemy import select
        R = _run_model()
        conditions = [R.work_key == work_key]
        if outcome is not None:
            conditions.append(R.outcome == outcome)
        result = await session.execute(
            select(R)
            .where(*conditions)
            .order_by(R.started_utc.desc())
            .limit(1)
            .execution_options(populate_existing=True)
        )
        return result.scalar_one_or_none()
    except Exception as exc:
        logger.warning(
            "[loop_repo] run_lookup_by_work_key failed for %r: %r", work_key, exc
        )
        return None


# ===========================================================================
# § DELIVERY — delivery_ledger
# ===========================================================================

def _delivery_model():
    from app.db.models import DeliveryLedger
    return DeliveryLedger


async def delivery_create(
    session,
    content_key: str,
    target_key: str,
    channel: str,
    content_hash: str,
    *,
    artifact_ref: Optional[str] = None,
    not_before_utc: Optional[datetime] = None,
    canonical_severity: Optional[str] = None,
    severity_rank: Optional[int] = None,
) -> Optional[Any]:
    """
    Insert a new delivery record.

    Uses a savepoint so a UNIQUE(content_key) conflict does not corrupt
    the outer transaction.  Returns None on conflict (dedup hard-stop).

    Phase 10C · Slice 4: accepts canonical_severity and severity_rank so
    the ranking triage decision is persisted on the ledger row at insert time.
    """
    if session is None:
        return None
    D = _delivery_model()
    new_id = _uuid()
    try:
        async with session.begin_nested():
            session.add(D(
                id=new_id,
                content_key=content_key,
                target_key=target_key,
                channel=channel,
                content_hash=content_hash,
                artifact_ref=artifact_ref,
                not_before_utc=not_before_utc,
                status="pending",
                canonical_severity=canonical_severity,
                severity_rank=severity_rank,
            ))
            await session.flush()
    except Exception:
        # UNIQUE conflict — this content has already been queued for delivery
        logger.debug(
            "[loop_repo] delivery_create conflict for content_key=%r (dedup)", content_key
        )
        return None
    # Re-fetch to return the full row with DB-generated defaults
    return await delivery_get_by_id(session, new_id)


async def delivery_content_key_exists(session, content_key: str) -> bool:
    """Return True if a delivery row for *content_key* already exists."""
    if session is None:
        return False
    try:
        from sqlalchemy import select, func
        D = _delivery_model()
        result = await session.execute(
            select(func.count()).select_from(D).where(D.content_key == content_key)
        )
        return (result.scalar() or 0) > 0
    except Exception as exc:
        logger.warning(
            "[loop_repo] delivery_content_key_exists failed for %r: %r", content_key, exc
        )
        return False


async def delivery_get_by_id(session, delivery_id: str) -> Optional[Any]:
    if session is None:
        return None
    try:
        from sqlalchemy import select
        result = await session.execute(
            select(_delivery_model())
            .where(_delivery_model().id == delivery_id)
            .execution_options(populate_existing=True)
        )
        return result.scalar_one_or_none()
    except Exception as exc:
        logger.warning("[loop_repo] delivery_get_by_id failed for %r: %r", delivery_id, exc)
        return None


async def delivery_get_by_content_key(session, content_key: str) -> Optional[Any]:
    if session is None:
        return None
    try:
        from sqlalchemy import select
        D = _delivery_model()
        result = await session.execute(
            select(D)
            .where(D.content_key == content_key)
            .execution_options(populate_existing=True)
        )
        return result.scalar_one_or_none()
    except Exception as exc:
        logger.warning(
            "[loop_repo] delivery_get_by_content_key failed for %r: %r", content_key, exc
        )
        return None


async def delivery_mark_delivered(
    session,
    delivery_id: str,
    *,
    delivered_at: Optional[datetime] = None,
) -> bool:
    if session is None:
        return False
    try:
        from sqlalchemy import update
        D = _delivery_model()
        result = await session.execute(
            update(D)
            .where(D.id == delivery_id)
            .values(status="delivered", delivered_at=delivered_at or _now())
            .execution_options(synchronize_session=False)
        )
        await session.flush()
        return result.rowcount > 0
    except Exception as exc:
        logger.warning(
            "[loop_repo] delivery_mark_delivered failed for %r: %r", delivery_id, exc
        )
        return False


async def delivery_mark_failed(
    session,
    delivery_id: str,
    *,
    increment_attempts: bool = True,
) -> bool:
    if session is None:
        return False
    try:
        from sqlalchemy import update
        D = _delivery_model()
        vals: Dict = {"status": "failed"}
        if increment_attempts:
            vals["attempts"] = D.attempts + 1
        result = await session.execute(
            update(D)
            .where(D.id == delivery_id)
            .values(**vals)
            .execution_options(synchronize_session=False)
        )
        await session.flush()
        return result.rowcount > 0
    except Exception as exc:
        logger.warning(
            "[loop_repo] delivery_mark_failed failed for %r: %r", delivery_id, exc
        )
        return False


async def delivery_mark_suppressed(session, delivery_id: str) -> bool:
    if session is None:
        return False
    try:
        from sqlalchemy import update
        D = _delivery_model()
        result = await session.execute(
            update(D)
            .where(D.id == delivery_id)
            .values(status="suppressed")
            .execution_options(synchronize_session=False)
        )
        await session.flush()
        return result.rowcount > 0
    except Exception as exc:
        logger.warning(
            "[loop_repo] delivery_mark_suppressed failed for %r: %r", delivery_id, exc
        )
        return False


async def delivery_get_pending(
    session,
    now: datetime,
    limit: int = 50,
) -> List[Any]:
    """
    Return up to *limit* pending deliveries that are ready to send.

    A pending delivery is ready when:
        status = 'pending'
        AND (not_before_utc IS NULL OR not_before_utc <= now)
    """
    if session is None:
        return []
    try:
        from sqlalchemy import select
        D = _delivery_model()
        result = await session.execute(
            select(D)
            .where(
                D.status == "pending",
                (D.not_before_utc == None) | (D.not_before_utc <= now),  # noqa: E711
            )
            .order_by(D.created_at.asc())
            .limit(limit)
        )
        return result.scalars().all()
    except Exception as exc:
        logger.warning("[loop_repo] delivery_get_pending failed: %r", exc)
        return []


# ===========================================================================
# § NOTIFY — notifications
# ===========================================================================

def _notif_model():
    from app.db.models import Notification
    return Notification


async def notification_create(
    session,
    user_id: str,
    kind: str,
    *,
    body_json: Optional[Dict] = None,
) -> Optional[Any]:
    """
    Insert a new in-app notification for *user_id*.
    Returns the new row, or None on error.
    """
    if session is None:
        return None
    try:
        N = _notif_model()
        row = N(
            id=_uuid(),
            user_id=user_id,
            kind=kind,
            body_json=body_json or {},
        )
        session.add(row)
        await session.flush()
        return row
    except Exception as exc:
        logger.warning(
            "[loop_repo] notification_create failed for user %r: %r", user_id, exc
        )
        return None


async def notification_get_by_id(session, notification_id: str) -> Optional[Any]:
    if session is None:
        return None
    try:
        from sqlalchemy import select
        result = await session.execute(
            select(_notif_model())
            .where(_notif_model().id == notification_id)
            .execution_options(populate_existing=True)
        )
        return result.scalar_one_or_none()
    except Exception as exc:
        logger.warning(
            "[loop_repo] notification_get_by_id failed for %r: %r", notification_id, exc
        )
        return None


async def notification_mark_read(
    session,
    notification_id: str,
    *,
    read_at: Optional[datetime] = None,
) -> bool:
    """Mark a single notification as read.  Idempotent: re-marking is a no-op."""
    if session is None:
        return False
    try:
        from sqlalchemy import update
        N = _notif_model()
        result = await session.execute(
            update(N)
            .where(N.id == notification_id, N.read_at == None)  # noqa: E711
            .values(read_at=read_at or _now())
            .execution_options(synchronize_session=False)
        )
        await session.flush()
        return result.rowcount > 0
    except Exception as exc:
        logger.warning(
            "[loop_repo] notification_mark_read failed for %r: %r", notification_id, exc
        )
        return False


async def notification_mark_all_read(
    session,
    user_id: str,
    *,
    read_at: Optional[datetime] = None,
) -> int:
    """Mark all unread notifications for *user_id* as read.  Returns count updated."""
    if session is None:
        return 0
    try:
        from sqlalchemy import update
        N = _notif_model()
        result = await session.execute(
            update(N)
            .where(N.user_id == user_id, N.read_at == None)  # noqa: E711
            .values(read_at=read_at or _now())
            .execution_options(synchronize_session=False)
        )
        await session.flush()
        return result.rowcount
    except Exception as exc:
        logger.warning(
            "[loop_repo] notification_mark_all_read failed for user %r: %r", user_id, exc
        )
        return 0


async def notification_list_unread(
    session,
    user_id: str,
    limit: int = 50,
) -> List[Any]:
    """Return unread notifications for *user_id*, newest first."""
    if session is None:
        return []
    try:
        from sqlalchemy import select
        N = _notif_model()
        result = await session.execute(
            select(N)
            .where(N.user_id == user_id, N.read_at == None)  # noqa: E711
            .order_by(N.created_at.desc())
            .limit(limit)
        )
        return result.scalars().all()
    except Exception as exc:
        logger.warning(
            "[loop_repo] notification_list_unread failed for user %r: %r", user_id, exc
        )
        return []


async def notification_list_all(
    session,
    user_id: str,
    limit: int = 50,
) -> List[Any]:
    """Return all notifications for *user_id* (read + unread), newest first."""
    if session is None:
        return []
    try:
        from sqlalchemy import select
        N = _notif_model()
        result = await session.execute(
            select(N)
            .where(N.user_id == user_id)
            .order_by(N.created_at.desc())
            .limit(limit)
        )
        return result.scalars().all()
    except Exception as exc:
        logger.warning(
            "[loop_repo] notification_list_all failed for user %r: %r", user_id, exc
        )
        return []
