from __future__ import annotations

import ast
import json

import pytest

from scripts import benchmark_shadow_scheduler
from validation import shadow_scheduler
from validation.intelligence_benchmark import BenchmarkContractError


NOW = "2026-10-01T00:10:00Z"


def _payload(**schedule_policy):
    return {
        "evaluated_at": NOW,
        "schedule_policy": {
            "enabled": True,
            "maximum_jobs_per_tick": 2,
            "maximum_catchup_slots": 1,
            **schedule_policy,
        },
        "safety_policy": {
            "enabled": True,
            "dry_run": True,
            "maximum_daily_cost_usd": 10,
            "maximum_job_cost_usd": 2,
            "maximum_daily_jobs": 10,
            "maximum_account_daily_jobs": 10,
            "maximum_issuer_daily_jobs": 10,
            "maximum_concurrent_jobs": 2,
            "maximum_account_concurrent_jobs": 1,
            "job_timeout_seconds": 60,
            "allowed_capabilities": ["frozen_research"],
        },
        "schedules": [
            {
                "schedule_id": "large-cap-hourly",
                "account_ref": "synthetic:benchmark-a",
                "issuer_id": "AAPL",
                "capability": "frozen_research",
                "estimated_cost_usd": 1,
                "starts_at": "2026-10-01T00:00:00Z",
                "interval_seconds": 3600,
            }
        ],
    }


def test_tick_only_emits_dry_run_decisions_and_reserves_nothing():
    result = shadow_scheduler.evaluate_schedule_tick(_payload())
    assert result["inert"] is True
    assert result["due_count"] == 1
    assert result["decisions"][0]["status"] == "dry_run"
    assert result["decisions"][0]["reservation_id"] is None
    assert result["operator_snapshot"]["active_jobs"] == 0
    assert result["operator_snapshot"]["reserved_cost_usd"] == 0


def test_disabled_schedule_reports_due_work_without_evaluating_it():
    result = shadow_scheduler.evaluate_schedule_tick(_payload(enabled=False))
    assert result["due_count"] == 1
    assert result["evaluated_count"] == 0
    assert result["deferred_count"] == 1
    assert result["decisions"] == []


def test_request_identity_is_deterministic_for_same_schedule_slot():
    first = shadow_scheduler.evaluate_schedule_tick(_payload())
    second = shadow_scheduler.evaluate_schedule_tick(_payload())
    assert first == second
    assert first["decisions"][0]["request_id"].startswith("dry-")


def test_tick_limit_and_catchup_are_bounded_and_ordered():
    payload = _payload(maximum_jobs_per_tick=2, maximum_catchup_slots=2)
    payload["evaluated_at"] = "2026-10-01T03:10:00Z"
    payload["schedules"].append({
        **payload["schedules"][0],
        "schedule_id": "small-cap-hourly",
        "account_ref": "synthetic:benchmark-b",
        "issuer_id": "SMALL",
    })
    result = shadow_scheduler.evaluate_schedule_tick(payload)
    assert result["due_count"] == 4
    assert result["evaluated_count"] == 2
    assert result["deferred_count"] == 2
    assert [item["slot"] for item in result["decisions"]] == [
        "2026-10-01T02:00:00+00:00",
        "2026-10-01T02:00:00+00:00",
    ]
    assert [item["schedule_id"] for item in result["decisions"]] == [
        "large-cap-hourly", "small-cap-hourly",
    ]


def test_non_dry_run_policy_is_rejected_before_any_admission():
    payload = _payload()
    payload["safety_policy"]["dry_run"] = False
    with pytest.raises(BenchmarkContractError, match="dry_run=true"):
        shadow_scheduler.evaluate_schedule_tick(payload)


@pytest.mark.parametrize("account_ref", ["account:real", "user-123", ""])
def test_only_synthetic_accounts_are_accepted(account_ref):
    payload = _payload()
    payload["schedules"][0]["account_ref"] = account_ref
    with pytest.raises(BenchmarkContractError, match="synthetic|account_ref"):
        shadow_scheduler.evaluate_schedule_tick(payload)


def test_duplicate_schedule_ids_and_high_frequency_are_rejected():
    payload = _payload()
    payload["schedules"].append(dict(payload["schedules"][0]))
    with pytest.raises(BenchmarkContractError, match="schedule_id must be unique"):
        shadow_scheduler.evaluate_schedule_tick(payload)
    payload = _payload()
    payload["schedules"][0]["interval_seconds"] = 60
    with pytest.raises(BenchmarkContractError, match="at least 300"):
        shadow_scheduler.evaluate_schedule_tick(payload)


@pytest.mark.parametrize("cost", [None, "unknown", -1, float("inf")])
def test_invalid_costs_fail_closed(cost):
    payload = _payload()
    payload["schedules"][0]["estimated_cost_usd"] = cost
    with pytest.raises(BenchmarkContractError, match="estimated_cost_usd"):
        shadow_scheduler.evaluate_schedule_tick(payload)


def test_cli_proves_inert_tick(tmp_path, capsys):
    path = tmp_path / "schedule.json"
    path.write_text(json.dumps(_payload()))
    assert benchmark_shadow_scheduler.main([
        str(path), "--require-inert",
    ]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["inert"] is True
    assert output["operator_snapshot"]["active_jobs"] == 0


def test_scheduler_boundary_has_no_execution_or_private_data_imports():
    tree = ast.parse(open(shadow_scheduler.__file__, encoding="utf-8").read())
    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.append(node.module or "")
    forbidden = ("app", "provider", "research", "memory", "delivery", "notification")
    assert not any(token in module for module in imports for token in forbidden)
