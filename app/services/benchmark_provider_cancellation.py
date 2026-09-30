"""Fail-closed cancellation boundary for synthetic benchmark provider work.

This module does not import a provider or scheduler. Callers must first commit
``request_cancellation`` so the local fence is durable before they invoke
``complete_provider_cancellation`` with an injected adapter.
"""
from __future__ import annotations

import asyncio
import hashlib
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from math import isfinite
from typing import Optional, Protocol

from app.db.repositories import benchmark_shadow_repo as repo
from app.services import benchmark_shadow_state_service as state


class ProviderCanceller(Protocol):
    async def cancel(self, operation_reference: str) -> "ProviderCancellationResult": ...


@dataclass(frozen=True)
class ProviderCancellationResult:
    acknowledged: bool
    code: str


@dataclass(frozen=True)
class CancellationOutcome:
    cancellation_id: str
    outcome: str
    automatic_kill: bool


def _operation_hash(value: str) -> str:
    reference = state._text(value, "operation_reference", 500)
    return hashlib.sha256(reference.encode()).hexdigest()


async def _automatic_kill_is_engaged(session) -> bool:
    control = await repo.control_read(session)
    return True if control is None else bool(control.automatic_kill)


async def request_cancellation(
    session, *, job_id: str, fence_token: int, provider_name: str,
    operation_reference: str, reason_code: str, actor_id: str,
    now: datetime,
):
    """Fence the local job and append a pending attempt in one transaction.

    The caller must commit this transaction before contacting the provider.
    """
    if session is None:
        raise state.ShadowStateError("database unavailable")
    instant = state._instant(now, "now")
    job = await repo.job_by_id(session, state._text(job_id, "job_id"))
    if job is None or job.fence_token != fence_token:
        raise state.ShadowStateError("running fence no longer owns job")
    latest = await repo.latest_cancellation(session, job.id, fence_token)
    initial = job.status == "running" and latest is None
    retry = (
        job.status == "cancelled" and latest is not None
        and latest.outcome in {"rejected", "timed_out", "error"}
    )
    if not initial and not retry:
        raise state.ShadowStateError("cancellation is not retryable")
    attempt_number = await repo.cancellation_attempt_count(
        session, job.id, fence_token
    ) + 1
    async with session.begin_nested():
        cancellation = await repo.insert_cancellation(
            session, id=str(uuid.uuid4()), job_id=job.id,
            fence_token=fence_token,
            provider_name=state._text(provider_name, "provider_name", 80),
            operation_ref_hash=_operation_hash(operation_reference),
            attempt_number=attempt_number, outcome="pending",
            reason_code=state._text(reason_code, "reason_code", 100),
            attempted_by=state._text(actor_id, "actor_id"),
            requested_at=instant, completed_at=None, failure_code=None,
            call_token=None, call_deadline=None,
        )
        if cancellation is None:
            raise state.ShadowStateError("cancellation attempt conflict")
        if initial:
            changed = await repo.cancel_job_cas(
                session, job_id=job.id, fence_token=fence_token,
                finished_at=instant, conservative_cost_usd=job.estimated_cost_usd,
                failure_code="provider_cancellation_requested",
            )
            if not changed:
                raise state.ShadowStateError("cancellation fence conflict")
            await state._append_transition(
                session, job_id=job.id, from_status="running", to_status="cancelled",
                actor_id=actor_id, reason_code=reason_code, occurred_at=instant,
                fence_token=fence_token, cost_usd=job.estimated_cost_usd,
            )
    return cancellation


async def _engage_automatic_kill(
    session, *, actor_id: str, reason_code: str, now: datetime,
) -> bool:
    """Preserve manual state while monotonically engaging the automatic stop."""
    await state.control_state(session, actor_id=actor_id, now=now)
    return await repo.engage_automatic_kill(
        session, reason_code=reason_code, updated_by=actor_id,
        updated_at=now,
    )


async def complete_provider_cancellation(
    session, *, cancellation_id: str, operation_reference: str,
    canceller: ProviderCanceller, timeout_seconds: float, now: datetime,
    actor_id: str = "shadow-cancellation",
) -> CancellationOutcome:
    """Call an injected adapter with a deadline and persist its acknowledgement."""
    if session is None:
        raise state.ShadowStateError("database unavailable")
    if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float)):
        raise state.ShadowStateError("timeout_seconds must be numeric")
    if not isfinite(float(timeout_seconds)) or timeout_seconds <= 0 or timeout_seconds > 30:
        raise state.ShadowStateError("timeout_seconds must be in (0, 30]")
    instant = state._instant(now, "now")
    attempt = await repo.cancellation_by_id(
        session, state._text(cancellation_id, "cancellation_id")
    )
    if attempt is None:
        raise state.ShadowStateError("cancellation attempt not found")
    if attempt.operation_ref_hash != _operation_hash(operation_reference):
        raise state.ShadowStateError("operation reference mismatch")
    if attempt.outcome not in {"pending", "calling"}:
        return CancellationOutcome(
            cancellation_id=attempt.id, outcome=attempt.outcome,
            automatic_kill=await _automatic_kill_is_engaged(session),
        )

    call_token = str(uuid.uuid4())
    if not await repo.claim_cancellation_call_cas(
        session, cancellation_id=attempt.id, call_token=call_token,
        call_deadline=instant + timedelta(seconds=float(timeout_seconds)),
        now=instant,
    ):
        refreshed = await repo.cancellation_by_id(session, attempt.id)
        if refreshed is None:
            raise state.ShadowStateError("cancellation call claim conflict")
        return CancellationOutcome(
            cancellation_id=refreshed.id, outcome=refreshed.outcome,
            automatic_kill=await _automatic_kill_is_engaged(session),
        )

    outcome = "error"
    failure_code: Optional[str] = "adapter_error"
    try:
        result = await asyncio.wait_for(
            canceller.cancel(operation_reference), timeout=float(timeout_seconds)
        )
        if not isinstance(result, ProviderCancellationResult):
            raise TypeError("invalid cancellation result")
        outcome = "acknowledged" if result.acknowledged else "rejected"
        failure_code = None if result.acknowledged else state._text(
            result.code, "provider_code", 100
        )
    except asyncio.TimeoutError:
        outcome, failure_code = "timed_out", "provider_timeout"
    except Exception:
        outcome, failure_code = "error", "adapter_error"

    if not await repo.complete_cancellation_cas(
        session, cancellation_id=attempt.id, outcome=outcome,
        call_token=call_token, completed_at=instant, failure_code=failure_code,
    ):
        refreshed = await repo.cancellation_by_id(session, attempt.id)
        if refreshed is None:
            raise state.ShadowStateError("cancellation outcome conflict")
        return CancellationOutcome(
            cancellation_id=refreshed.id, outcome=refreshed.outcome,
            automatic_kill=await _automatic_kill_is_engaged(session),
        )

    automatic = False
    if outcome != "acknowledged":
        automatic = await _engage_automatic_kill(
            session, actor_id=actor_id,
            reason_code="provider_cancellation_unconfirmed", now=instant,
        )
        if not automatic:
            raise state.ShadowStateError("unable to engage automatic kill")
    return CancellationOutcome(
        cancellation_id=attempt.id, outcome=outcome,
        automatic_kill=automatic,
    )
