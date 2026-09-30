"""Fail-closed admission control for Intelligence Benchmark shadow work.

This module owns no scheduler and invokes no research or delivery code.  It is
the safety boundary a future scheduler must pass before starting a shadow job.
The default policy is inert; dry-run decisions never reserve capacity or cost.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
from math import isfinite
from threading import RLock
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

from .intelligence_benchmark import BenchmarkContractError, content_hash


def _text(value: Any, field: str) -> str:
    result = str(value or "").strip()
    if not result:
        raise BenchmarkContractError(f"{field} is required")
    return result


def _positive_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise BenchmarkContractError(f"{field} must be a positive integer")
    return value


def _nonnegative_number(value: Any, field: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise BenchmarkContractError(f"{field} must be numeric") from exc
    if not isfinite(result) or result < 0:
        raise BenchmarkContractError(f"{field} must be finite and non-negative")
    return result


def _instant(value: Any, field: str) -> datetime:
    if isinstance(value, datetime):
        result = value
    else:
        try:
            result = datetime.fromisoformat(_text(value, field).replace("Z", "+00:00"))
        except ValueError as exc:
            raise BenchmarkContractError(f"{field} must be ISO-8601") from exc
    if result.tzinfo is None or result.utcoffset() is None:
        raise BenchmarkContractError(f"{field} must include a timezone")
    return result.astimezone(timezone.utc)


class AdmissionStatus(str, Enum):
    DENIED = "denied"
    DRY_RUN = "dry_run"
    RESERVED = "reserved"


class JobStatus(str, Enum):
    RESERVED = "reserved"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    CANCELLED = "cancelled"


TERMINAL_STATUSES = frozenset({
    JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.TIMED_OUT,
    JobStatus.CANCELLED,
})


@dataclass(frozen=True)
class ShadowSafetyPolicy:
    enabled: bool = False
    dry_run: bool = True
    maximum_daily_cost_usd: float = 0.0
    maximum_job_cost_usd: float = 0.0
    maximum_daily_jobs: int = 1
    maximum_account_daily_jobs: int = 1
    maximum_issuer_daily_jobs: int = 1
    maximum_concurrent_jobs: int = 1
    maximum_account_concurrent_jobs: int = 1
    job_timeout_seconds: int = 60
    allowed_capabilities: Tuple[str, ...] = ()

    @staticmethod
    def from_dict(value: Mapping[str, Any]) -> "ShadowSafetyPolicy":
        enabled = value.get("enabled", False)
        dry_run = value.get("dry_run", True)
        if not isinstance(enabled, bool) or not isinstance(dry_run, bool):
            raise BenchmarkContractError("enabled and dry_run must be boolean")
        raw_capabilities = value.get("allowed_capabilities", ())
        if not isinstance(raw_capabilities, (list, tuple)):
            raise BenchmarkContractError("allowed_capabilities must be a list")
        capabilities = tuple(sorted(
            _text(item, "allowed_capabilities") for item in raw_capabilities
        ))
        if len(set(capabilities)) != len(capabilities):
            raise BenchmarkContractError("allowed_capabilities must be unique")
        return ShadowSafetyPolicy(
            enabled=enabled,
            dry_run=dry_run,
            maximum_daily_cost_usd=_nonnegative_number(
                value.get("maximum_daily_cost_usd", 0), "maximum_daily_cost_usd"
            ),
            maximum_job_cost_usd=_nonnegative_number(
                value.get("maximum_job_cost_usd", 0), "maximum_job_cost_usd"
            ),
            maximum_daily_jobs=_positive_int(
                value.get("maximum_daily_jobs", 1), "maximum_daily_jobs"
            ),
            maximum_account_daily_jobs=_positive_int(
                value.get("maximum_account_daily_jobs", 1),
                "maximum_account_daily_jobs",
            ),
            maximum_issuer_daily_jobs=_positive_int(
                value.get("maximum_issuer_daily_jobs", 1),
                "maximum_issuer_daily_jobs",
            ),
            maximum_concurrent_jobs=_positive_int(
                value.get("maximum_concurrent_jobs", 1),
                "maximum_concurrent_jobs",
            ),
            maximum_account_concurrent_jobs=_positive_int(
                value.get("maximum_account_concurrent_jobs", 1),
                "maximum_account_concurrent_jobs",
            ),
            job_timeout_seconds=_positive_int(
                value.get("job_timeout_seconds", 60), "job_timeout_seconds"
            ),
            allowed_capabilities=capabilities,
        )


@dataclass(frozen=True)
class ShadowJobRequest:
    request_id: str
    account_ref: str
    issuer_id: str
    capability: str
    estimated_cost_usd: float

    @staticmethod
    def from_dict(value: Mapping[str, Any]) -> "ShadowJobRequest":
        account_ref = _text(value.get("account_ref"), "account_ref")
        if not account_ref.startswith("synthetic:"):
            raise BenchmarkContractError(
                "shadow benchmark jobs require a synthetic account_ref"
            )
        return ShadowJobRequest(
            request_id=_text(value.get("request_id"), "request_id"),
            account_ref=account_ref,
            issuer_id=_text(value.get("issuer_id"), "issuer_id").upper(),
            capability=_text(value.get("capability"), "capability"),
            estimated_cost_usd=_nonnegative_number(
                value.get("estimated_cost_usd"), "estimated_cost_usd"
            ),
        )

    @property
    def fingerprint(self) -> str:
        return content_hash(self)


@dataclass(frozen=True)
class AdmissionDecision:
    request_id: str
    status: AdmissionStatus
    reason: str
    evaluated_at: str
    reservation_id: Optional[str] = None
    duplicate: bool = False


@dataclass
class ShadowJob:
    reservation_id: str
    request: ShadowJobRequest
    request_fingerprint: str
    status: JobStatus
    reserved_at: datetime
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    actual_cost_usd: Optional[float] = None
    failure_code: Optional[str] = None

    @property
    def active(self) -> bool:
        return self.status in {JobStatus.RESERVED, JobStatus.RUNNING}


@dataclass(frozen=True)
class OperatorSnapshot:
    enabled: bool
    dry_run: bool
    manual_kill_switch: bool
    automatic_kill_switch: bool
    automatic_kill_reason: Optional[str]
    safe_state: bool
    active_jobs: int
    reserved_cost_usd: float
    completed_cost_usd: float
    admitted_today: int
    denied_decisions: int
    dry_run_decisions: int
    timed_out_jobs: int
    failed_jobs: int
    cancelled_jobs: int

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class ShadowSafetyControlPlane:
    """Thread-safe, in-memory safety contract for a future shadow scheduler."""

    def __init__(self, policy: ShadowSafetyPolicy):
        self.policy = policy
        self._lock = RLock()
        self._manual_kill_switch = False
        self._automatic_kill_switch = False
        self._automatic_kill_reason: Optional[str] = None
        self._jobs: Dict[str, ShadowJob] = {}
        self._decisions: Dict[str, AdmissionDecision] = {}
        self._fingerprints: Dict[str, str] = {}

    def _day(self, instant: datetime) -> str:
        return instant.astimezone(timezone.utc).date().isoformat()

    def _jobs_on_day(self, instant: datetime) -> Sequence[ShadowJob]:
        day = self._day(instant)
        return tuple(job for job in self._jobs.values() if self._day(job.reserved_at) == day)

    def _active(self) -> Sequence[ShadowJob]:
        return tuple(job for job in self._jobs.values() if job.active)

    def _costs_on_day(self, instant: datetime) -> Tuple[float, float]:
        reserved = completed = 0.0
        for job in self._jobs_on_day(instant):
            if job.active:
                reserved += job.request.estimated_cost_usd
            elif job.actual_cost_usd is not None:
                completed += job.actual_cost_usd
        return reserved, completed

    def _record_decision(
        self, request: ShadowJobRequest, status: AdmissionStatus, reason: str,
        now: datetime, reservation_id: Optional[str] = None,
    ) -> AdmissionDecision:
        decision = AdmissionDecision(
            request_id=request.request_id, status=status, reason=reason,
            evaluated_at=now.isoformat(), reservation_id=reservation_id,
        )
        self._decisions[request.request_id] = decision
        self._fingerprints[request.request_id] = request.fingerprint
        return decision

    def admit(self, request: ShadowJobRequest, *, now: Any) -> AdmissionDecision:
        instant = _instant(now, "now")
        with self._lock:
            existing = self._decisions.get(request.request_id)
            if existing is not None:
                if self._fingerprints[request.request_id] != request.fingerprint:
                    raise BenchmarkContractError(
                        "request_id was reused with a different payload"
                    )
                return AdmissionDecision(
                    request_id=existing.request_id, status=existing.status,
                    reason=existing.reason, evaluated_at=existing.evaluated_at,
                    reservation_id=existing.reservation_id, duplicate=True,
                )

            if not self.policy.enabled:
                return self._record_decision(
                    request, AdmissionStatus.DENIED, "control plane disabled", instant
                )
            if self._manual_kill_switch or self._automatic_kill_switch:
                return self._record_decision(
                    request, AdmissionStatus.DENIED, "kill switch engaged", instant
                )
            if request.capability not in self.policy.allowed_capabilities:
                return self._record_decision(
                    request, AdmissionStatus.DENIED,
                    "capability is not allowlisted", instant,
                )
            if request.estimated_cost_usd > self.policy.maximum_job_cost_usd:
                return self._record_decision(
                    request, AdmissionStatus.DENIED, "job cost ceiling exceeded", instant
                )

            today = self._jobs_on_day(instant)
            account_today = [
                job for job in today if job.request.account_ref == request.account_ref
            ]
            issuer_today = [
                job for job in today if job.request.issuer_id == request.issuer_id
            ]
            active = self._active()
            account_active = [
                job for job in active if job.request.account_ref == request.account_ref
            ]
            reserved, completed = self._costs_on_day(instant)
            reason = None
            if len(today) >= self.policy.maximum_daily_jobs:
                reason = "daily job quota exhausted"
            elif len(account_today) >= self.policy.maximum_account_daily_jobs:
                reason = "account daily job quota exhausted"
            elif len(issuer_today) >= self.policy.maximum_issuer_daily_jobs:
                reason = "issuer daily job quota exhausted"
            elif len(active) >= self.policy.maximum_concurrent_jobs:
                reason = "global concurrency limit reached"
            elif len(account_active) >= self.policy.maximum_account_concurrent_jobs:
                reason = "account concurrency limit reached"
            elif (
                reserved + completed + request.estimated_cost_usd
                > self.policy.maximum_daily_cost_usd + 1e-12
            ):
                reason = "daily cost budget exhausted"
            if reason:
                return self._record_decision(
                    request, AdmissionStatus.DENIED, reason, instant
                )
            if self.policy.dry_run:
                return self._record_decision(
                    request, AdmissionStatus.DRY_RUN,
                    "eligible; dry-run policy reserves no work", instant,
                )

            reservation_id = f"shadow-{request.request_id}"
            self._jobs[reservation_id] = ShadowJob(
                reservation_id=reservation_id, request=request,
                request_fingerprint=request.fingerprint,
                status=JobStatus.RESERVED, reserved_at=instant,
            )
            return self._record_decision(
                request, AdmissionStatus.RESERVED, "admitted", instant,
                reservation_id,
            )

    def start(self, reservation_id: str, *, now: Any) -> ShadowJob:
        instant = _instant(now, "now")
        with self._lock:
            job = self._jobs.get(reservation_id)
            if job is None:
                raise BenchmarkContractError("unknown reservation_id")
            if self._manual_kill_switch or self._automatic_kill_switch:
                raise BenchmarkContractError("kill switch engaged")
            if job.status == JobStatus.RUNNING:
                return job
            if job.status != JobStatus.RESERVED:
                raise BenchmarkContractError("only reserved jobs may start")
            job.status = JobStatus.RUNNING
            job.started_at = instant
            return job

    def complete(
        self, reservation_id: str, *, now: Any, actual_cost_usd: Any,
        succeeded: bool, failure_code: Optional[str] = None,
    ) -> ShadowJob:
        instant = _instant(now, "now")
        actual_cost = _nonnegative_number(actual_cost_usd, "actual_cost_usd")
        with self._lock:
            job = self._jobs.get(reservation_id)
            if job is None:
                raise BenchmarkContractError("unknown reservation_id")
            if job.status in TERMINAL_STATUSES:
                if (
                    job.actual_cost_usd == actual_cost
                    and job.status == (
                        JobStatus.SUCCEEDED if succeeded else JobStatus.FAILED
                    )
                ):
                    return job
                raise BenchmarkContractError("terminal job completion cannot change")
            if job.status != JobStatus.RUNNING:
                raise BenchmarkContractError("only running jobs may complete")
            if not succeeded and not str(failure_code or "").strip():
                raise BenchmarkContractError("failed jobs require failure_code")
            job.status = JobStatus.SUCCEEDED if succeeded else JobStatus.FAILED
            job.finished_at = instant
            job.actual_cost_usd = actual_cost
            job.failure_code = None if succeeded else str(failure_code).strip()
            _, completed = self._costs_on_day(job.reserved_at)
            if actual_cost > self.policy.maximum_job_cost_usd + 1e-12:
                self._automatic_kill_switch = True
                self._automatic_kill_reason = "actual job cost exceeded ceiling"
            elif completed > self.policy.maximum_daily_cost_usd + 1e-12:
                self._automatic_kill_switch = True
                self._automatic_kill_reason = "actual daily cost exceeded budget"
            return job

    def reap_timeouts(self, *, now: Any) -> Tuple[str, ...]:
        instant = _instant(now, "now")
        timed_out = []
        with self._lock:
            for job in self._jobs.values():
                anchor = job.started_at or job.reserved_at
                if job.active and (instant - anchor).total_seconds() > self.policy.job_timeout_seconds:
                    job.status = JobStatus.TIMED_OUT
                    job.finished_at = instant
                    # The provider's final charge is unknown. Keep the full
                    # reservation charged until a durable reconciler exists.
                    job.actual_cost_usd = job.request.estimated_cost_usd
                    job.failure_code = "timeout"
                    timed_out.append(job.reservation_id)
        return tuple(sorted(timed_out))

    def engage_kill_switch(self, *, now: Any) -> Tuple[str, ...]:
        instant = _instant(now, "now")
        cancelled = []
        with self._lock:
            self._manual_kill_switch = True
            for job in self._jobs.values():
                if job.active:
                    job.status = JobStatus.CANCELLED
                    job.finished_at = instant
                    # Cancellation is not proof that upstream work was free.
                    job.actual_cost_usd = job.request.estimated_cost_usd
                    job.failure_code = "manual_kill_switch"
                    cancelled.append(job.reservation_id)
        return tuple(sorted(cancelled))

    def release_kill_switch(self) -> None:
        with self._lock:
            self._manual_kill_switch = False

    def account_jobs(self, account_ref: str) -> Tuple[ShadowJob, ...]:
        account = _text(account_ref, "account_ref")
        with self._lock:
            return tuple(
                job for job in sorted(self._jobs.values(), key=lambda item: item.reservation_id)
                if job.request.account_ref == account
            )

    def operator_snapshot(self, *, now: Any) -> OperatorSnapshot:
        instant = _instant(now, "now")
        with self._lock:
            active = self._active()
            reserved, completed = self._costs_on_day(instant)
            terminal = tuple(self._jobs.values())
            active_by_account: Dict[str, int] = {}
            for job in active:
                account_ref = job.request.account_ref
                active_by_account[account_ref] = active_by_account.get(account_ref, 0) + 1
            return OperatorSnapshot(
                enabled=self.policy.enabled, dry_run=self.policy.dry_run,
                manual_kill_switch=self._manual_kill_switch,
                automatic_kill_switch=self._automatic_kill_switch,
                automatic_kill_reason=self._automatic_kill_reason,
                safe_state=(
                    not self.policy.enabled or self.policy.dry_run
                    or self._manual_kill_switch or self._automatic_kill_switch
                    or (
                        len(active) <= self.policy.maximum_concurrent_jobs
                        and all(
                            count <= self.policy.maximum_account_concurrent_jobs
                            for count in active_by_account.values()
                        )
                        and reserved + completed
                        <= self.policy.maximum_daily_cost_usd + 1e-12
                    )
                ),
                active_jobs=len(active), reserved_cost_usd=reserved,
                completed_cost_usd=completed,
                admitted_today=len(self._jobs_on_day(instant)),
                denied_decisions=sum(
                    item.status == AdmissionStatus.DENIED
                    for item in self._decisions.values()
                ),
                dry_run_decisions=sum(
                    item.status == AdmissionStatus.DRY_RUN
                    for item in self._decisions.values()
                ),
                timed_out_jobs=sum(
                    item.status == JobStatus.TIMED_OUT for item in terminal
                ),
                failed_jobs=sum(item.status == JobStatus.FAILED for item in terminal),
                cancelled_jobs=sum(
                    item.status == JobStatus.CANCELLED for item in terminal
                ),
            )


def evaluate_payload(payload: Mapping[str, Any]) -> Dict[str, Any]:
    """Evaluate admissions deterministically without starting any job."""
    policy = ShadowSafetyPolicy.from_dict(payload.get("policy", {}))
    plane = ShadowSafetyControlPlane(policy)
    now = payload.get("evaluated_at")
    decisions = [
        asdict(plane.admit(ShadowJobRequest.from_dict(item), now=now))
        for item in payload.get("requests", ())
    ]
    return {
        "decisions": decisions,
        "operator_snapshot": plane.operator_snapshot(now=now).to_dict(),
    }
