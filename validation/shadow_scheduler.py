"""Deterministic, inert scheduling for synthetic benchmark dry runs.

This module computes which synthetic benchmark requests *would* be admitted at
one caller-supplied instant.  It has no clock loop, database, provider, research,
memory, delivery, or notification dependency.  It refuses any policy that could
reserve work, making its output an auditable plan rather than an execution path.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from math import isfinite
from typing import Any, Dict, Mapping, Tuple

from .intelligence_benchmark import BenchmarkContractError, content_hash
from .shadow_safety import (
    AdmissionStatus,
    ShadowJobRequest,
    ShadowSafetyControlPlane,
    ShadowSafetyPolicy,
)


def _text(value: Any, field: str) -> str:
    result = str(value or "").strip()
    if not result:
        raise BenchmarkContractError(f"{field} is required")
    return result


def _positive_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise BenchmarkContractError(f"{field} must be a positive integer")
    return value


def _instant(value: Any, field: str) -> datetime:
    if isinstance(value, datetime):
        result = value
    else:
        try:
            result = datetime.fromisoformat(
                _text(value, field).replace("Z", "+00:00")
            )
        except ValueError as exc:
            raise BenchmarkContractError(f"{field} must be ISO-8601") from exc
    if result.tzinfo is None or result.utcoffset() is None:
        raise BenchmarkContractError(f"{field} must include a timezone")
    return result.astimezone(timezone.utc)


def _cost(value: Any) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise BenchmarkContractError("estimated_cost_usd must be numeric") from exc
    if not isfinite(result) or result < 0:
        raise BenchmarkContractError(
            "estimated_cost_usd must be finite and non-negative"
        )
    return result


@dataclass(frozen=True)
class ScheduledSyntheticJob:
    schedule_id: str
    account_ref: str
    issuer_id: str
    capability: str
    estimated_cost_usd: float
    starts_at: datetime
    interval_seconds: int

    @staticmethod
    def from_dict(value: Mapping[str, Any]) -> "ScheduledSyntheticJob":
        account_ref = _text(value.get("account_ref"), "account_ref")
        if not account_ref.startswith("synthetic:"):
            raise BenchmarkContractError(
                "dry-run schedules require a synthetic account_ref"
            )
        interval = _positive_int(value.get("interval_seconds"), "interval_seconds")
        if interval < 300:
            raise BenchmarkContractError("interval_seconds must be at least 300")
        return ScheduledSyntheticJob(
            schedule_id=_text(value.get("schedule_id"), "schedule_id"),
            account_ref=account_ref,
            issuer_id=_text(value.get("issuer_id"), "issuer_id").upper(),
            capability=_text(value.get("capability"), "capability"),
            estimated_cost_usd=_cost(value.get("estimated_cost_usd")),
            starts_at=_instant(value.get("starts_at"), "starts_at"),
            interval_seconds=interval,
        )

    def due_slots(self, *, now: datetime, maximum_catchup_slots: int) -> Tuple[datetime, ...]:
        if now < self.starts_at:
            return ()
        elapsed = int((now - self.starts_at).total_seconds())
        latest_index = elapsed // self.interval_seconds
        first_index = max(0, latest_index - maximum_catchup_slots + 1)
        return tuple(
            self.starts_at + timedelta(seconds=index * self.interval_seconds)
            for index in range(first_index, latest_index + 1)
        )


@dataclass(frozen=True)
class DryRunSchedulePolicy:
    enabled: bool = False
    maximum_jobs_per_tick: int = 1
    maximum_catchup_slots: int = 1

    @staticmethod
    def from_dict(value: Mapping[str, Any]) -> "DryRunSchedulePolicy":
        enabled = value.get("enabled", False)
        if not isinstance(enabled, bool):
            raise BenchmarkContractError("schedule enabled must be boolean")
        return DryRunSchedulePolicy(
            enabled=enabled,
            maximum_jobs_per_tick=_positive_int(
                value.get("maximum_jobs_per_tick", 1), "maximum_jobs_per_tick"
            ),
            maximum_catchup_slots=_positive_int(
                value.get("maximum_catchup_slots", 1), "maximum_catchup_slots"
            ),
        )


def _request(schedule: ScheduledSyntheticJob, slot: datetime) -> ShadowJobRequest:
    identity = {
        "schedule_id": schedule.schedule_id,
        "slot": slot.isoformat(),
        "account_ref": schedule.account_ref,
        "issuer_id": schedule.issuer_id,
        "capability": schedule.capability,
    }
    return ShadowJobRequest.from_dict({
        "request_id": f"dry-{content_hash(identity)[:32]}",
        "account_ref": schedule.account_ref,
        "issuer_id": schedule.issuer_id,
        "capability": schedule.capability,
        "estimated_cost_usd": schedule.estimated_cost_usd,
    })


def evaluate_schedule_tick(payload: Mapping[str, Any]) -> Dict[str, Any]:
    """Evaluate one deterministic tick and return a content-free audit plan."""
    now = _instant(payload.get("evaluated_at"), "evaluated_at")
    schedule_policy = DryRunSchedulePolicy.from_dict(
        payload.get("schedule_policy", {})
    )
    safety_policy = ShadowSafetyPolicy.from_dict(payload.get("safety_policy", {}))
    if not safety_policy.dry_run:
        raise BenchmarkContractError(
            "inert scheduler requires safety_policy.dry_run=true"
        )

    schedules = tuple(
        ScheduledSyntheticJob.from_dict(item)
        for item in payload.get("schedules", ())
    )
    schedule_ids = [item.schedule_id for item in schedules]
    if len(schedule_ids) != len(set(schedule_ids)):
        raise BenchmarkContractError("schedule_id must be unique")

    due = []
    for schedule in schedules:
        for slot in schedule.due_slots(
            now=now,
            maximum_catchup_slots=schedule_policy.maximum_catchup_slots,
        ):
            due.append((slot, schedule.schedule_id, schedule))
    due.sort(key=lambda item: (item[0], item[1]))

    selected = due[:schedule_policy.maximum_jobs_per_tick]
    deferred = len(due) - len(selected)
    plane = ShadowSafetyControlPlane(safety_policy)
    decisions = []
    if schedule_policy.enabled:
        for slot, _, schedule in selected:
            request = _request(schedule, slot)
            decision = plane.admit(request, now=now)
            if decision.status == AdmissionStatus.RESERVED:
                raise BenchmarkContractError(
                    "inert scheduler cannot create a reservation"
                )
            decisions.append({
                **asdict(decision),
                "schedule_id": schedule.schedule_id,
                "slot": slot.isoformat(),
                "account_ref": schedule.account_ref,
                "issuer_id": schedule.issuer_id,
                "capability": schedule.capability,
                "estimated_cost_usd": schedule.estimated_cost_usd,
            })

    return {
        "schema_version": 1,
        "evaluated_at": now.isoformat(),
        "schedule_enabled": schedule_policy.enabled,
        "inert": True,
        "due_count": len(due),
        "evaluated_count": len(decisions),
        "deferred_count": deferred if schedule_policy.enabled else len(due),
        "decisions": decisions,
        "operator_snapshot": plane.operator_snapshot(now=now).to_dict(),
    }
