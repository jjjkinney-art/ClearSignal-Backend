from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor

import pytest

from scripts import benchmark_shadow_safety
from validation.intelligence_benchmark import BenchmarkContractError
from validation.shadow_safety import (
    AdmissionStatus, JobStatus, ShadowJobRequest, ShadowSafetyControlPlane,
    ShadowSafetyPolicy, evaluate_payload,
)


NOW = "2026-09-30T00:00:00Z"


def _policy(**overrides):
    value = {
        "enabled": True, "dry_run": False,
        "maximum_daily_cost_usd": 10, "maximum_job_cost_usd": 4,
        "maximum_daily_jobs": 5, "maximum_account_daily_jobs": 3,
        "maximum_issuer_daily_jobs": 3, "maximum_concurrent_jobs": 2,
        "maximum_account_concurrent_jobs": 1, "job_timeout_seconds": 60,
        "allowed_capabilities": ["frozen_research"],
    }
    value.update(overrides)
    return ShadowSafetyPolicy.from_dict(value)


def _request(identifier="one", account="synthetic:a", issuer="AAPL", cost=1):
    return ShadowJobRequest.from_dict({
        "request_id": identifier, "account_ref": account,
        "issuer_id": issuer, "capability": "frozen_research",
        "estimated_cost_usd": cost,
    })


def test_default_policy_is_inert_and_costless():
    plane = ShadowSafetyControlPlane(ShadowSafetyPolicy())
    result = plane.admit(_request(), now=NOW)
    assert result.status == AdmissionStatus.DENIED
    snapshot = plane.operator_snapshot(now=NOW)
    assert snapshot.enabled is False
    assert snapshot.active_jobs == 0
    assert snapshot.reserved_cost_usd == 0
    assert snapshot.safe_state is True


def test_dry_run_reports_eligibility_without_reservation():
    plane = ShadowSafetyControlPlane(_policy(dry_run=True))
    result = plane.admit(_request(), now=NOW)
    assert result.status == AdmissionStatus.DRY_RUN
    assert result.reservation_id is None
    snapshot = plane.operator_snapshot(now=NOW)
    assert snapshot.active_jobs == 0
    assert snapshot.admitted_today == 0
    assert snapshot.dry_run_decisions == 1


def test_capability_and_per_job_cost_fail_closed():
    plane = ShadowSafetyControlPlane(_policy())
    unknown = ShadowJobRequest.from_dict({
        "request_id": "unknown", "account_ref": "synthetic:a",
        "issuer_id": "AAPL", "capability": "live_research",
        "estimated_cost_usd": 1,
    })
    assert plane.admit(unknown, now=NOW).reason == "capability is not allowlisted"
    assert plane.admit(_request("cost", cost=5), now=NOW).reason == "job cost ceiling exceeded"


def test_reservation_is_idempotent_and_conflicts_are_rejected():
    plane = ShadowSafetyControlPlane(_policy())
    first = plane.admit(_request(), now=NOW)
    duplicate = plane.admit(_request(), now="2026-09-30T00:00:01Z")
    assert first.status == AdmissionStatus.RESERVED
    assert duplicate.reservation_id == first.reservation_id
    assert duplicate.duplicate is True
    with pytest.raises(BenchmarkContractError, match="different payload"):
        plane.admit(_request(issuer="MSFT"), now=NOW)


def test_account_concurrency_is_isolated_and_global_limit_holds():
    plane = ShadowSafetyControlPlane(_policy())
    assert plane.admit(_request("a1", "synthetic:a", "AAPL"), now=NOW).status == AdmissionStatus.RESERVED
    assert plane.admit(_request("a2", "synthetic:a", "MSFT"), now=NOW).reason == "account concurrency limit reached"
    assert plane.admit(_request("b1", "synthetic:b", "MSFT"), now=NOW).status == AdmissionStatus.RESERVED
    assert plane.admit(_request("c1", "synthetic:c", "NVDA"), now=NOW).reason == "global concurrency limit reached"


def test_daily_account_issuer_and_cost_quotas_survive_completion():
    plane = ShadowSafetyControlPlane(_policy(maximum_concurrent_jobs=5, maximum_account_concurrent_jobs=5, maximum_account_daily_jobs=1, maximum_issuer_daily_jobs=1))
    decision = plane.admit(_request("first", "synthetic:a", "AAPL", 4), now=NOW)
    plane.start(decision.reservation_id, now=NOW)
    plane.complete(decision.reservation_id, now=NOW, actual_cost_usd=4, succeeded=True)
    assert plane.admit(_request("account", "synthetic:a", "MSFT"), now=NOW).reason == "account daily job quota exhausted"
    assert plane.admit(_request("issuer", "synthetic:b", "AAPL"), now=NOW).reason == "issuer daily job quota exhausted"
    assert plane.admit(_request("budget", "synthetic:b", "MSFT", 7), now=NOW).reason == "job cost ceiling exceeded"


def test_daily_cost_budget_counts_completed_and_reserved_work():
    plane = ShadowSafetyControlPlane(_policy(maximum_daily_cost_usd=5, maximum_job_cost_usd=5, maximum_concurrent_jobs=5, maximum_account_concurrent_jobs=5))
    first = plane.admit(_request("first", "synthetic:a", "AAPL", 3), now=NOW)
    plane.start(first.reservation_id, now=NOW)
    plane.complete(first.reservation_id, now=NOW, actual_cost_usd=3, succeeded=True)
    assert plane.admit(_request("second", "synthetic:b", "MSFT", 3), now=NOW).reason == "daily cost budget exhausted"


def test_kill_switch_cancels_active_work_and_blocks_restart():
    plane = ShadowSafetyControlPlane(_policy())
    decision = plane.admit(_request(), now=NOW)
    plane.start(decision.reservation_id, now=NOW)
    assert plane.engage_kill_switch(now="2026-09-30T00:00:05Z") == (decision.reservation_id,)
    assert plane.account_jobs("synthetic:a")[0].status == JobStatus.CANCELLED
    assert plane.admit(_request("two", "synthetic:b"), now=NOW).reason == "kill switch engaged"
    plane.release_kill_switch()
    assert plane.admit(_request("three", "synthetic:b"), now=NOW).status == AdmissionStatus.RESERVED


def test_timeout_releases_capacity_and_is_visible():
    plane = ShadowSafetyControlPlane(_policy(maximum_concurrent_jobs=1))
    decision = plane.admit(_request(), now=NOW)
    plane.start(decision.reservation_id, now=NOW)
    assert plane.reap_timeouts(now="2026-09-30T00:01:01Z") == (decision.reservation_id,)
    assert plane.admit(_request("two", "synthetic:b"), now="2026-09-30T00:01:02Z").status == AdmissionStatus.RESERVED
    snapshot = plane.operator_snapshot(now=NOW)
    assert snapshot.timed_out_jobs == 1
    assert snapshot.completed_cost_usd == 1


def test_actual_cost_overrun_engages_automatic_kill_switch():
    plane = ShadowSafetyControlPlane(_policy(maximum_daily_cost_usd=2, maximum_job_cost_usd=2))
    decision = plane.admit(_request(cost=2), now=NOW)
    plane.start(decision.reservation_id, now=NOW)
    plane.complete(decision.reservation_id, now=NOW, actual_cost_usd=3, succeeded=True)
    snapshot = plane.operator_snapshot(now=NOW)
    assert snapshot.automatic_kill_switch is True
    assert snapshot.safe_state is True
    assert plane.admit(_request("two", "synthetic:b"), now=NOW).reason == "kill switch engaged"


def test_per_job_actual_cost_overrun_halts_even_below_daily_budget():
    plane = ShadowSafetyControlPlane(_policy(maximum_daily_cost_usd=100, maximum_job_cost_usd=2))
    decision = plane.admit(_request(cost=2), now=NOW)
    plane.start(decision.reservation_id, now=NOW)
    plane.complete(decision.reservation_id, now="2026-10-01T00:00:00Z", actual_cost_usd=3, succeeded=True)
    snapshot = plane.operator_snapshot(now="2026-10-01T00:00:00Z")
    assert snapshot.automatic_kill_switch is True
    assert snapshot.automatic_kill_reason == "actual job cost exceeded ceiling"


def test_failed_completion_requires_code_and_is_idempotent():
    plane = ShadowSafetyControlPlane(_policy())
    decision = plane.admit(_request(), now=NOW)
    plane.start(decision.reservation_id, now=NOW)
    with pytest.raises(BenchmarkContractError, match="failure_code"):
        plane.complete(decision.reservation_id, now=NOW, actual_cost_usd=1, succeeded=False)
    result = plane.complete(decision.reservation_id, now=NOW, actual_cost_usd=1, succeeded=False, failure_code="provider_error")
    assert result.status == JobStatus.FAILED
    assert plane.complete(decision.reservation_id, now=NOW, actual_cost_usd=1, succeeded=False, failure_code="provider_error") is result


def test_account_views_cannot_cross_owner_boundary():
    plane = ShadowSafetyControlPlane(_policy(maximum_account_concurrent_jobs=2))
    plane.admit(_request("a", "synthetic:a"), now=NOW)
    plane.admit(_request("b", "synthetic:b", "MSFT"), now=NOW)
    assert [job.request.account_ref for job in plane.account_jobs("synthetic:a")] == ["synthetic:a"]
    assert [job.request.account_ref for job in plane.account_jobs("synthetic:b")] == ["synthetic:b"]


def test_concurrent_admission_cannot_oversubscribe_capacity():
    plane = ShadowSafetyControlPlane(_policy(maximum_concurrent_jobs=1, maximum_account_concurrent_jobs=1))
    requests = [_request(f"job-{index}", f"synthetic:{index}", f"ISS{index}") for index in range(20)]
    with ThreadPoolExecutor(max_workers=20) as executor:
        decisions = list(executor.map(lambda item: plane.admit(item, now=NOW), requests))
    assert sum(item.status == AdmissionStatus.RESERVED for item in decisions) == 1
    assert plane.operator_snapshot(now=NOW).active_jobs == 1


@pytest.mark.parametrize("account_ref", ["user-123", "account:real", ""])
def test_real_or_unscoped_accounts_are_rejected(account_ref):
    with pytest.raises(BenchmarkContractError, match="synthetic account_ref|account_ref is required"):
        ShadowJobRequest.from_dict({
            "request_id": "x", "account_ref": account_ref, "issuer_id": "AAPL",
            "capability": "frozen_research", "estimated_cost_usd": 1,
        })


def test_cli_requires_inert_policy(tmp_path, capsys):
    payload = {
        "evaluated_at": NOW,
        "policy": {**as_policy(_policy(dry_run=True))},
        "requests": [as_request(_request())],
    }
    path = tmp_path / "shadow.json"
    path.write_text(json.dumps(payload))
    assert benchmark_shadow_safety.main([str(path), "--require-inert"]) == 0
    assert '"dry_run": true' in capsys.readouterr().out
    payload["policy"]["dry_run"] = False
    path.write_text(json.dumps(payload))
    assert benchmark_shadow_safety.main([str(path), "--require-inert"]) == 2


def test_payload_evaluator_never_starts_jobs():
    result = evaluate_payload({
        "evaluated_at": NOW, "policy": as_policy(_policy()),
        "requests": [as_request(_request())],
    })
    assert result["decisions"][0]["status"] == AdmissionStatus.RESERVED
    assert result["operator_snapshot"]["active_jobs"] == 1
    assert result["operator_snapshot"]["completed_cost_usd"] == 0


def as_policy(item):
    return {
        "enabled": item.enabled, "dry_run": item.dry_run,
        "maximum_daily_cost_usd": item.maximum_daily_cost_usd,
        "maximum_job_cost_usd": item.maximum_job_cost_usd,
        "maximum_daily_jobs": item.maximum_daily_jobs,
        "maximum_account_daily_jobs": item.maximum_account_daily_jobs,
        "maximum_issuer_daily_jobs": item.maximum_issuer_daily_jobs,
        "maximum_concurrent_jobs": item.maximum_concurrent_jobs,
        "maximum_account_concurrent_jobs": item.maximum_account_concurrent_jobs,
        "job_timeout_seconds": item.job_timeout_seconds,
        "allowed_capabilities": list(item.allowed_capabilities),
    }


def as_request(item):
    return {
        "request_id": item.request_id, "account_ref": item.account_ref,
        "issuer_id": item.issuer_id, "capability": item.capability,
        "estimated_cost_usd": item.estimated_cost_usd,
    }
