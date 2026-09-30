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
    terminal = ("succeeded", "failed", "timed_out", "cancelled")
    result = await session.execute(
        select(Job.id).where(
            Job.status.in_(terminal), Job.retention_until < cutoff,
        ).order_by(Job.id)
    )
    ids = [row[0] for row in result.fetchall()]
    if not ids:
        return []
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
        }
    from sqlalchemy import case, func, select
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
    return {
        "status_counts": {row[0]: int(row[1]) for row in status_rows.fetchall()},
        "estimated_cost_usd": float(costs[0] or 0),
        "actual_cost_usd": float(costs[1] or 0),
        "job_count": int(costs[2] or 0),
        "expired_active_leases": int(costs[3] or 0),
        "transition_count": int(transition_count or 0),
    }


async def all_job_ids(session) -> Sequence[str]:
    if session is None:
        return ()
    from sqlalchemy import select
    _, Job, _ = _models()
    result = await session.execute(select(Job.id).order_by(Job.id))
    return tuple(row[0] for row in result.fetchall())
