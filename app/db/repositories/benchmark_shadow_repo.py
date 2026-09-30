"""Persistence primitives for synthetic benchmark shadow state.

Business rules live in ``benchmark_shadow_state_service``.  This repository
owns compare-and-swap writes and the sole retention deletion path.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, List, Optional, Sequence


def _models():
    from app.db.models import (
        BenchmarkShadowControl, BenchmarkShadowJob, BenchmarkShadowTransition,
    )
    return BenchmarkShadowControl, BenchmarkShadowJob, BenchmarkShadowTransition


def _cancellation_model():
    from app.db.models import BenchmarkShadowCancellation
    return BenchmarkShadowCancellation


async def job_by_request(session, request_id: str) -> Optional[Any]:
    if session is None:
        return None
    from sqlalchemy import select
    _, Job, _ = _models()
    result = await session.execute(
        select(Job).where(Job.request_id == request_id)
        .execution_options(populate_existing=True)
    )
    return result.scalar_one_or_none()


async def job_by_id(session, job_id: str) -> Optional[Any]:
    if session is None:
        return None
    from sqlalchemy import select
    _, Job, _ = _models()
    result = await session.execute(
        select(Job).where(Job.id == job_id)
        .execution_options(populate_existing=True)
    )
    return result.scalar_one_or_none()


async def insert_job(session, **values) -> Optional[Any]:
    if session is None:
        return None
    _, Job, _ = _models()
    try:
        async with session.begin_nested():
            row = Job(**values)
            session.add(row)
            await session.flush()
        return row
    except Exception:
        return None


async def claim_job_cas(
    session, *, job_id: str, expected_token: int, holder_id: str,
    lease_expires_at: datetime, started_at: datetime,
) -> bool:
    if session is None:
        return False
    from sqlalchemy import exists, select, update
    Control, Job, _ = _models()
    safe_control = exists(select(Control.id).where(
        Control.id == "global",
        Control.manual_kill.is_(False),
        Control.automatic_kill.is_(False),
    ))
    result = await session.execute(
        update(Job).where(
            Job.id == job_id,
            Job.status == "reserved",
            Job.fence_token == expected_token,
            safe_control,
        ).values(
            status="running", holder_id=holder_id,
            lease_expires_at=lease_expires_at,
            fence_token=expected_token + 1, started_at=started_at,
            updated_at=started_at,
        ).execution_options(synchronize_session=False)
    )
    await session.flush()
    return result.rowcount == 1


async def renew_lease_cas(
    session, *, job_id: str, holder_id: str, fence_token: int,
    lease_expires_at: datetime, updated_at: datetime,
) -> bool:
    if session is None:
        return False
    from sqlalchemy import exists, select, update
    Control, Job, _ = _models()
    safe_control = exists(select(Control.id).where(
        Control.id == "global",
        Control.manual_kill.is_(False),
        Control.automatic_kill.is_(False),
    ))
    result = await session.execute(
        update(Job).where(
            Job.id == job_id, Job.status == "running",
            Job.holder_id == holder_id, Job.fence_token == fence_token,
            safe_control,
        ).values(lease_expires_at=lease_expires_at, updated_at=updated_at)
        .execution_options(synchronize_session=False)
    )
    await session.flush()
    return result.rowcount == 1


async def finish_job_cas(
    session, *, job_id: str, holder_id: str, fence_token: int,
    status: str, finished_at: datetime, actual_cost_usd: float,
    failure_code: Optional[str],
) -> bool:
    if session is None:
        return False
    from sqlalchemy import update
    _, Job, _ = _models()
    result = await session.execute(
        update(Job).where(
            Job.id == job_id, Job.status == "running",
            Job.holder_id == holder_id, Job.fence_token == fence_token,
        ).values(
            status=status, finished_at=finished_at,
            actual_cost_usd=actual_cost_usd, failure_code=failure_code,
            holder_id=None, lease_expires_at=None, updated_at=finished_at,
        ).execution_options(synchronize_session=False)
    )
    await session.flush()
    return result.rowcount == 1


async def cancel_job_cas(
    session, *, job_id: str, fence_token: int, finished_at: datetime,
    conservative_cost_usd: float, failure_code: str,
) -> bool:
    """Fence a running job locally before any external cancellation call."""
    if session is None:
        return False
    from sqlalchemy import update
    _, Job, _ = _models()
    result = await session.execute(
        update(Job).where(
            Job.id == job_id, Job.status == "running",
            Job.fence_token == fence_token,
        ).values(
            status="cancelled", finished_at=finished_at,
            actual_cost_usd=conservative_cost_usd,
            failure_code=failure_code, holder_id=None,
            lease_expires_at=None, updated_at=finished_at,
        ).execution_options(synchronize_session=False)
    )
    await session.flush()
    return result.rowcount == 1


async def expired_running_jobs(session, now: datetime) -> Sequence[Any]:
    if session is None:
        return ()
    from sqlalchemy import select
    _, Job, _ = _models()
    result = await session.execute(
        select(Job).where(Job.status == "running", Job.lease_expires_at < now)
        .order_by(Job.id)
    )
    return tuple(result.scalars().all())


async def timeout_job_cas(
    session, *, job_id: str, holder_id: str, fence_token: int,
    finished_at: datetime, conservative_cost_usd: float,
) -> bool:
    if session is None:
        return False
    from sqlalchemy import update
    _, Job, _ = _models()
    result = await session.execute(
        update(Job).where(
            Job.id == job_id, Job.status == "running",
            Job.holder_id == holder_id, Job.fence_token == fence_token,
            Job.lease_expires_at < finished_at,
        ).values(
            status="timed_out", finished_at=finished_at,
            actual_cost_usd=conservative_cost_usd, failure_code="lease_expired",
            holder_id=None, lease_expires_at=None, updated_at=finished_at,
        ).execution_options(synchronize_session=False)
    )
    await session.flush()
    return result.rowcount == 1


async def latest_transition(session, job_id: str) -> Optional[Any]:
    if session is None:
        return None
    from sqlalchemy import select
    _, _, Transition = _models()
    result = await session.execute(
        select(Transition).where(Transition.job_id == job_id)
        .order_by(Transition.sequence.desc()).limit(1)
    )
    return result.scalar_one_or_none()


async def transitions_for_job(session, job_id: str) -> Sequence[Any]:
    if session is None:
        return ()
    from sqlalchemy import select
    _, _, Transition = _models()
    result = await session.execute(
        select(Transition).where(Transition.job_id == job_id)
        .order_by(Transition.sequence)
    )
    return tuple(result.scalars().all())


async def insert_transition(session, **values) -> Optional[Any]:
    if session is None:
        return None
    _, _, Transition = _models()
    try:
        async with session.begin_nested():
            row = Transition(**values)
            session.add(row)
            await session.flush()
        return row
    except Exception:
        return None


async def cancellation_attempt_count(session, job_id: str, fence_token: int) -> int:
    if session is None:
        return 0
    from sqlalchemy import func, select
    Cancellation = _cancellation_model()
    result = await session.execute(select(func.count(Cancellation.id)).where(
        Cancellation.job_id == job_id,
        Cancellation.fence_token == fence_token,
    ))
    return int(result.scalar_one() or 0)


async def latest_cancellation(session, job_id: str, fence_token: int) -> Optional[Any]:
    if session is None:
        return None
    from sqlalchemy import select
    Cancellation = _cancellation_model()
    result = await session.execute(
        select(Cancellation).where(
            Cancellation.job_id == job_id,
            Cancellation.fence_token == fence_token,
        ).order_by(Cancellation.attempt_number.desc()).limit(1)
    )
    return result.scalar_one_or_none()


async def insert_cancellation(session, **values) -> Optional[Any]:
    if session is None:
        return None
    Cancellation = _cancellation_model()
    try:
        async with session.begin_nested():
            row = Cancellation(**values)
            session.add(row)
            await session.flush()
        return row
    except Exception:
        return None


async def cancellation_by_id(session, cancellation_id: str) -> Optional[Any]:
    if session is None:
        return None
    from sqlalchemy import select
    Cancellation = _cancellation_model()
    result = await session.execute(
        select(Cancellation).where(Cancellation.id == cancellation_id)
        .execution_options(populate_existing=True)
    )
    return result.scalar_one_or_none()


async def complete_cancellation_cas(
    session, *, cancellation_id: str, outcome: str,
    call_token: str, completed_at: datetime, failure_code: Optional[str],
) -> bool:
    if session is None:
        return False
    from sqlalchemy import update
    Cancellation = _cancellation_model()
    result = await session.execute(
        update(Cancellation).where(
            Cancellation.id == cancellation_id,
            Cancellation.outcome == "calling",
            Cancellation.call_token == call_token,
        ).values(
            outcome=outcome, completed_at=completed_at,
            failure_code=failure_code, call_token=None, call_deadline=None,
        ).execution_options(synchronize_session=False)
    )
    await session.flush()
    return result.rowcount == 1


async def claim_cancellation_call_cas(
    session, *, cancellation_id: str, call_token: str,
    call_deadline: datetime, now: datetime,
) -> bool:
    """Single-flight provider call with deadline-based crash recovery."""
    if session is None:
        return False
    from sqlalchemy import and_, or_, update
    Cancellation = _cancellation_model()
    result = await session.execute(
        update(Cancellation).where(
            Cancellation.id == cancellation_id,
            or_(
                Cancellation.outcome == "pending",
                and_(
                    Cancellation.outcome == "calling",
                    Cancellation.call_deadline < now,
                ),
            ),
        ).values(
            outcome="calling", call_token=call_token,
            call_deadline=call_deadline,
        ).execution_options(synchronize_session=False)
    )
    await session.flush()
    return result.rowcount == 1


async def engage_automatic_kill(
    session, *, reason_code: str, updated_by: str, updated_at: datetime,
) -> bool:
    """Monotonic automatic stop; never clears or overwrites manual state."""
    if session is None:
        return False
    from sqlalchemy import update
    Control, _, _ = _models()
    await session.execute(
        update(Control).where(
            Control.id == "global", Control.automatic_kill.is_(False),
        ).values(
            automatic_kill=True, reason_code=reason_code,
            version=Control.version + 1, updated_by=updated_by,
            updated_at=updated_at,
        ).execution_options(synchronize_session=False)
    )
    await session.flush()
    current = await control_read(session)
    return bool(current and current.automatic_kill)


async def control_read(session) -> Optional[Any]:
    if session is None:
        return None
    from sqlalchemy import select
    Control, _, _ = _models()
    result = await session.execute(
        select(Control).where(Control.id == "global")
        .execution_options(populate_existing=True)
    )
    return result.scalar_one_or_none()


async def control_insert(session, *, updated_by: str, updated_at: datetime) -> Optional[Any]:
    if session is None:
        return None
    Control, _, _ = _models()
    try:
        async with session.begin_nested():
            row = Control(
                id="global", manual_kill=False, automatic_kill=False,
                reason_code=None, version=0, updated_by=updated_by,
                updated_at=updated_at,
            )
            session.add(row)
            await session.flush()
        return row
    except Exception:
        return None


async def control_update_cas(
    session, *, expected_version: int, manual_kill: bool,
    automatic_kill: bool, reason_code: Optional[str], updated_by: str,
    updated_at: datetime,
) -> bool:
    if session is None:
        return False
    from sqlalchemy import update
    Control, _, _ = _models()
    result = await session.execute(
        update(Control).where(
            Control.id == "global", Control.version == expected_version,
        ).values(
            manual_kill=manual_kill, automatic_kill=automatic_kill,
            reason_code=reason_code, version=expected_version + 1,
            updated_by=updated_by, updated_at=updated_at,
        ).execution_options(synchronize_session=False)
    )
    await session.flush()
    return result.rowcount == 1


async def purge_expired_terminal(session, cutoff: datetime) -> List[str]:
    """Sole retention deletion path; active jobs are never eligible."""
    if session is None:
        return []
    from sqlalchemy import delete, select
    _, Job, Transition = _models()
    Cancellation = _cancellation_model()
    terminal = ("succeeded", "failed", "timed_out", "cancelled")
    result = await session.execute(
        select(Job.id).where(
            Job.status.in_(terminal), Job.retention_until < cutoff,
        ).order_by(Job.id)
    )
    ids = [row[0] for row in result.fetchall()]
    if not ids:
        return []
    await session.execute(delete(Cancellation).where(Cancellation.job_id.in_(ids)))
    await session.execute(delete(Transition).where(Transition.job_id.in_(ids)))
    await session.execute(delete(Job).where(Job.id.in_(ids)))
    await session.flush()
    return ids


async def operator_metrics(session, now: datetime) -> dict:
    """Aggregate-only operational metrics; returns no job or owner identifiers."""
    if session is None:
        return {
            "status_counts": {}, "estimated_cost_usd": 0.0,
            "actual_cost_usd": 0.0, "expired_active_leases": 0,
            "job_count": 0, "transition_count": 0,
            "cancellation_counts": {}, "unacknowledged_cancellations": 0,
        }
    from sqlalchemy import and_, case, func, select
    _, Job, Transition = _models()
    status_rows = await session.execute(
        select(Job.status, func.count(Job.id)).group_by(Job.status)
    )
    costs = (
        await session.execute(select(
            func.coalesce(func.sum(Job.estimated_cost_usd), 0.0),
            func.coalesce(func.sum(Job.actual_cost_usd), 0.0),
            func.count(Job.id),
            func.coalesce(func.sum(case(
                (
                    (Job.status == "running")
                    & (Job.lease_expires_at < now), 1
                ), else_=0,
            )), 0),
        ))
    ).one()
    transition_count = (
        await session.execute(select(func.count(Transition.id)))
    ).scalar_one()
    Cancellation = _cancellation_model()
    cancellation_rows = await session.execute(
        select(Cancellation.outcome, func.count(Cancellation.id))
        .group_by(Cancellation.outcome)
    )
    cancellation_counts = {
        row[0]: int(row[1]) for row in cancellation_rows.fetchall()
    }
    latest_attempts = (
        select(
            Cancellation.job_id.label("job_id"),
            Cancellation.fence_token.label("fence_token"),
            func.max(Cancellation.attempt_number).label("attempt_number"),
        )
        .group_by(Cancellation.job_id, Cancellation.fence_token)
        .subquery()
    )
    unacknowledged = (
        await session.execute(
            select(func.count(Cancellation.id)).join(
                latest_attempts,
                and_(
                    Cancellation.job_id == latest_attempts.c.job_id,
                    Cancellation.fence_token == latest_attempts.c.fence_token,
                    Cancellation.attempt_number == latest_attempts.c.attempt_number,
                ),
            ).where(Cancellation.outcome != "acknowledged")
        )
    ).scalar_one()
    return {
        "status_counts": {row[0]: int(row[1]) for row in status_rows.fetchall()},
        "estimated_cost_usd": float(costs[0] or 0),
        "actual_cost_usd": float(costs[1] or 0),
        "job_count": int(costs[2] or 0),
        "expired_active_leases": int(costs[3] or 0),
        "transition_count": int(transition_count or 0),
        "cancellation_counts": cancellation_counts,
        "unacknowledged_cancellations": int(unacknowledged or 0),
    }


async def all_job_ids(session) -> Sequence[str]:
    if session is None:
        return ()
    from sqlalchemy import select
    _, Job, _ = _models()
    result = await session.execute(select(Job.id).order_by(Job.id))
    return tuple(row[0] for row in result.fetchall())
