"""Durable, fenced state machine for synthetic benchmark shadow jobs.

This service persists reservations and lifecycle evidence. It cannot schedule,
execute, or deliver work. All caller identities are operational worker/operator
identifiers; benchmark account references must remain synthetic.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from math import isfinite
from typing import Any, Dict, Optional, Sequence, Tuple

from app.db.repositories import benchmark_shadow_repo as repo


class ShadowStateError(ValueError):
    pass


TERMINAL = frozenset({"succeeded", "failed", "timed_out", "cancelled"})


def _text(value: Any, field: str, maximum: int = 200) -> str:
    result = str(value or "").strip()
    if not result:
        raise ShadowStateError(f"{field} is required")
    if len(result) > maximum:
        raise ShadowStateError(f"{field} exceeds {maximum} characters")
    return result


def _instant(value: Any, field: str) -> datetime:
    if not isinstance(value, datetime):
        raise ShadowStateError(f"{field} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ShadowStateError(f"{field} must include a timezone")
    return value.astimezone(timezone.utc)


def _cost(value: Any, field: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ShadowStateError(f"{field} must be numeric") from exc
    if not isfinite(result) or result < 0:
        raise ShadowStateError(f"{field} must be finite and non-negative")
    return result


def _hash(value: Dict[str, Any]) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode()).hexdigest()


@dataclass(frozen=True)
class Reservation:
    request_id: str
    request_fingerprint: str
    account_ref: str
    issuer_id: str
    capability: str
    estimated_cost_usd: float

    @staticmethod
    def build(
        *, request_id: str, account_ref: str, issuer_id: str,
        capability: str, estimated_cost_usd: Any,
    ) -> "Reservation":
        account = _text(account_ref, "account_ref")
        if not account.startswith("synthetic:"):
            raise ShadowStateError("account_ref must be synthetic")
        normalized = {
            "request_id": _text(request_id, "request_id", 128),
            "account_ref": account,
            "issuer_id": _text(issuer_id, "issuer_id", 80).upper(),
            "capability": _text(capability, "capability", 80),
            "estimated_cost_usd": _cost(estimated_cost_usd, "estimated_cost_usd"),
        }
        return Reservation(
            request_fingerprint=_hash(normalized), **normalized,
        )


def _transition_payload(
    *, job_id: str, sequence: int, from_status: Optional[str], to_status: str,
    actor_id: str, reason_code: str, occurred_at: datetime, fence_token: int,
    cost_usd: Optional[float], previous_event_hash: Optional[str],
) -> Dict[str, Any]:
    return {
        "job_id": job_id, "sequence": sequence, "from_status": from_status,
        "to_status": to_status, "actor_id": actor_id,
        "reason_code": reason_code, "occurred_at": occurred_at.isoformat(),
        "fence_token": fence_token, "cost_usd": cost_usd,
        "previous_event_hash": previous_event_hash,
    }


async def _append_transition(
    session, *, job_id: str, from_status: Optional[str], to_status: str,
    actor_id: str, reason_code: str, occurred_at: datetime, fence_token: int,
    cost_usd: Optional[float] = None,
):
    previous = await repo.latest_transition(session, job_id)
    sequence = previous.sequence + 1 if previous else 1
    previous_hash = previous.event_hash if previous else None
    payload = _transition_payload(
        job_id=job_id, sequence=sequence, from_status=from_status,
        to_status=to_status, actor_id=actor_id, reason_code=reason_code,
        occurred_at=occurred_at, fence_token=fence_token, cost_usd=cost_usd,
        previous_event_hash=previous_hash,
    )
    row = await repo.insert_transition(
        session, id=str(uuid.uuid4()), job_id=job_id, sequence=sequence,
        from_status=from_status, to_status=to_status, actor_id=actor_id,
        reason_code=reason_code, occurred_at=occurred_at,
        fence_token=fence_token, cost_usd=cost_usd,
        previous_event_hash=previous_hash, event_hash=_hash(payload),
    )
    if row is None:
        raise ShadowStateError("transition append conflict")
    return row


async def reserve(
    session, reservation: Reservation, *, now: datetime,
    retention_days: int = 90, actor_id: str = "shadow-admission",
):
    if session is None:
        return None
    instant = _instant(now, "now")
    if isinstance(retention_days, bool) or not isinstance(retention_days, int) or retention_days < 1:
        raise ShadowStateError("retention_days must be a positive integer")
    existing = await repo.job_by_request(session, reservation.request_id)
    if existing is not None:
        if existing.request_fingerprint != reservation.request_fingerprint:
            raise ShadowStateError("request_id reused with different payload")
        return existing
    row = await repo.insert_job(
        session, id=str(uuid.uuid4()), request_id=reservation.request_id,
        request_fingerprint=reservation.request_fingerprint,
        account_ref=reservation.account_ref, issuer_id=reservation.issuer_id,
        capability=reservation.capability,
        estimated_cost_usd=reservation.estimated_cost_usd,
        actual_cost_usd=None, status="reserved", holder_id=None,
        lease_expires_at=None, fence_token=0, failure_code=None,
        reserved_at=instant, started_at=None, finished_at=None,
        retention_until=instant + timedelta(days=retention_days),
        created_at=instant, updated_at=instant,
    )
    if row is None:
        existing = await repo.job_by_request(session, reservation.request_id)
        if existing is None or existing.request_fingerprint != reservation.request_fingerprint:
            raise ShadowStateError("reservation conflict")
        return existing
    await _append_transition(
        session, job_id=row.id, from_status=None, to_status="reserved",
        actor_id=_text(actor_id, "actor_id"), reason_code="admitted",
        occurred_at=instant, fence_token=0,
    )
    return row


async def claim(
    session, job_id: str, *, holder_id: str, now: datetime,
    lease_seconds: int = 120,
):
    if session is None:
        return None
    instant = _instant(now, "now")
    holder = _text(holder_id, "holder_id")
    if isinstance(lease_seconds, bool) or not isinstance(lease_seconds, int) or lease_seconds < 1:
        raise ShadowStateError("lease_seconds must be a positive integer")
    if await is_killed(session):
        return None
    job = await repo.job_by_id(session, _text(job_id, "job_id"))
    if job is None or job.status != "reserved":
        return None
    old_token = job.fence_token
    claimed = await repo.claim_job_cas(
        session, job_id=job.id, expected_token=old_token, holder_id=holder,
        lease_expires_at=instant + timedelta(seconds=lease_seconds),
        started_at=instant,
    )
    if not claimed:
        return None
    await _append_transition(
        session, job_id=job.id, from_status="reserved", to_status="running",
        actor_id=holder, reason_code="lease_claimed", occurred_at=instant,
        fence_token=old_token + 1,
    )
    return await repo.job_by_id(session, job.id)


async def renew(
    session, job_id: str, *, holder_id: str, fence_token: int,
    now: datetime, lease_seconds: int = 120,
) -> bool:
    if session is None:
        return False
    instant = _instant(now, "now")
    if await is_killed(session):
        return False
    return await repo.renew_lease_cas(
        session, job_id=_text(job_id, "job_id"),
        holder_id=_text(holder_id, "holder_id"), fence_token=fence_token,
        lease_expires_at=instant + timedelta(seconds=lease_seconds),
        updated_at=instant,
    )


async def finish(
    session, job_id: str, *, holder_id: str, fence_token: int,
    now: datetime, succeeded: bool, actual_cost_usd: Any,
    failure_code: Optional[str] = None,
):
    if session is None:
        return None
    instant = _instant(now, "now")
    cost = _cost(actual_cost_usd, "actual_cost_usd")
    failure = None if succeeded else _text(failure_code, "failure_code", 100)
    status = "succeeded" if succeeded else "failed"
    job = await repo.job_by_id(session, _text(job_id, "job_id"))
    if job is None:
        return None
    if job.status in TERMINAL:
        if job.status == status and job.actual_cost_usd == cost:
            return job
        raise ShadowStateError("terminal job cannot change")
    changed = await repo.finish_job_cas(
        session, job_id=job.id, holder_id=_text(holder_id, "holder_id"),
        fence_token=fence_token, status=status, finished_at=instant,
        actual_cost_usd=cost, failure_code=failure,
    )
    if not changed:
        return None
    await _append_transition(
        session, job_id=job.id, from_status="running", to_status=status,
        actor_id=holder_id, reason_code="completed" if succeeded else failure,
        occurred_at=instant, fence_token=fence_token, cost_usd=cost,
    )
    return await repo.job_by_id(session, job.id)


async def recover_expired(session, *, now: datetime, actor_id: str = "shadow-recovery") -> Tuple[str, ...]:
    if session is None:
        return ()
    instant = _instant(now, "now")
    recovered = []
    for job in await repo.expired_running_jobs(session, instant):
        if await repo.timeout_job_cas(
            session, job_id=job.id, holder_id=job.holder_id,
            fence_token=job.fence_token, finished_at=instant,
            conservative_cost_usd=job.estimated_cost_usd,
        ):
            await _append_transition(
                session, job_id=job.id, from_status="running",
                to_status="timed_out", actor_id=actor_id,
                reason_code="lease_expired", occurred_at=instant,
                fence_token=job.fence_token, cost_usd=job.estimated_cost_usd,
            )
            recovered.append(job.id)
    return tuple(sorted(recovered))


async def control_state(session, *, actor_id: str = "shadow-bootstrap", now: Optional[datetime] = None):
    if session is None:
        return None
    row = await repo.control_read(session)
    if row is not None:
        return row
    instant = _instant(now or datetime.now(timezone.utc), "now")
    row = await repo.control_insert(session, updated_by=actor_id, updated_at=instant)
    return row or await repo.control_read(session)


async def is_killed(session) -> bool:
    state = await repo.control_read(session)
    return True if state is None else bool(state.manual_kill or state.automatic_kill)


async def set_kill_state(
    session, *, expected_version: int, manual_kill: bool,
    automatic_kill: bool, reason_code: Optional[str], actor_id: str,
    now: datetime,
) -> bool:
    if session is None:
        return False
    instant = _instant(now, "now")
    if not isinstance(manual_kill, bool) or not isinstance(automatic_kill, bool):
        raise ShadowStateError("kill states must be boolean")
    reason = None
    if manual_kill or automatic_kill:
        reason = _text(reason_code, "reason_code", 100)
    return await repo.control_update_cas(
        session, expected_version=expected_version,
        manual_kill=manual_kill, automatic_kill=automatic_kill,
        reason_code=reason, updated_by=_text(actor_id, "actor_id"),
        updated_at=instant,
    )


async def verify_transition_chain(session, job_id: str) -> Tuple[str, ...]:
    errors = []
    previous = None
    expected_sequence = 1
    for row in await repo.transitions_for_job(session, job_id):
        payload = _transition_payload(
            job_id=row.job_id, sequence=row.sequence,
            from_status=row.from_status, to_status=row.to_status,
            actor_id=row.actor_id, reason_code=row.reason_code,
            occurred_at=_instant(row.occurred_at.replace(tzinfo=timezone.utc) if row.occurred_at.tzinfo is None else row.occurred_at, "occurred_at"),
            fence_token=row.fence_token, cost_usd=row.cost_usd,
            previous_event_hash=row.previous_event_hash,
        )
        if row.sequence != expected_sequence:
            errors.append(f"sequence gap at {row.sequence}")
        if row.previous_event_hash != previous:
            errors.append(f"previous hash mismatch at {row.sequence}")
        if row.event_hash != _hash(payload):
            errors.append(f"event hash mismatch at {row.sequence}")
        previous = row.event_hash
        expected_sequence += 1
    if expected_sequence == 1:
        errors.append("transition chain is empty")
    return tuple(errors)


async def purge_retained(session, *, now: datetime) -> Tuple[str, ...]:
    return tuple(await repo.purge_expired_terminal(session, _instant(now, "now")))


async def append_operator_audit(
    session, *, actor_id: str, action: str, occurred_at: datetime,
    ip_address: Optional[str] = None, user_agent: Optional[str] = None,
) -> str:
    """Append the mandatory security audit for a kill-state mutation."""
    if session is None:
        raise ShadowStateError("database unavailable")
    from app.db.models import AuditLog
    identifier = str(uuid.uuid4())
    session.add(AuditLog(
        id=identifier, user_id=_text(actor_id, "actor_id"),
        resource="benchmark_shadow_control", resource_id="global",
        action=_text(action, "action", 40),
        ip_address=str(ip_address)[:45] if ip_address else None,
        user_agent=str(user_agent)[:500] if user_agent else None,
        created_at=_instant(occurred_at, "occurred_at"),
    ))
    await session.flush()
    return identifier


async def build_operator_snapshot(session, *, now: datetime) -> Dict[str, Any]:
    """Return aggregate, identity-free state for the authenticated admin API."""
    instant = _instant(now, "now")
    if session is None:
        return {
            "db_available": False, "control_initialized": False,
            "manual_kill": True, "automatic_kill": True,
            "effective_killed": True, "control_version": None,
            "reason_code": "database_unavailable", "status_counts": {},
            "job_count": 0, "transition_count": 0,
            "estimated_cost_usd": 0.0, "actual_cost_usd": 0.0,
            "expired_active_leases": 0, "integrity_error_count": 0,
            "transition_integrity": False, "scheduler_present": False,
            "execution_enabled": False, "safe_state": True,
        }
    control = await repo.control_read(session)
    metrics = await repo.operator_metrics(session, instant)
    integrity_errors = 0
    for job_id in await repo.all_job_ids(session):
        integrity_errors += len(await verify_transition_chain(session, job_id))
    initialized = control is not None
    manual = True if control is None else bool(control.manual_kill)
    automatic = True if control is None else bool(control.automatic_kill)
    integrity_ok = integrity_errors == 0
    return {
        "db_available": True, "control_initialized": initialized,
        "manual_kill": manual, "automatic_kill": automatic,
        "effective_killed": manual or automatic,
        "control_version": None if control is None else control.version,
        "reason_code": (
            "control_uninitialized" if control is None else control.reason_code
        ),
        **metrics,
        "integrity_error_count": integrity_errors,
        "transition_integrity": integrity_ok,
        # Structural truth for this slice: there is no scheduler import/path.
        "scheduler_present": False, "execution_enabled": False,
        "safe_state": bool(
            integrity_ok
            and metrics["expired_active_leases"] == 0
        ),
    }
