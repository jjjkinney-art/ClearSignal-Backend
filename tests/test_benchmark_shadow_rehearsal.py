from __future__ import annotations

import ast
import json

import pytest

from scripts import benchmark_shadow_rehearsal
from validation import shadow_rehearsal
from validation.intelligence_benchmark import BenchmarkContractError


NOW = "2026-10-01T00:01:00Z"


def _copy_manifest(tmp_path):
    value = shadow_rehearsal.load_schedule()
    path = tmp_path / "schedule.json"
    path.write_text(json.dumps(value))
    return value, path


def test_frozen_schedule_rehearsal_passes_with_zero_side_effects():
    result = shadow_rehearsal.run_rehearsal(evaluated_at=NOW)
    assert result["passed"] is True
    assert result["issuer_count"] == 13
    assert result["sector_count"] == 8
    assert result["market_cap_counts"] == {
        "mega_large": 7,
        "mid": 3,
        "small_micro": 3,
    }
    assert result["known_coverage_gaps"] == ["mid_cap", "small_micro"]
    assert all(result["checks"].values())
    assert result["tick"]["evaluated_count"] == 13
    assert result["tick"]["operator_snapshot"]["active_jobs"] == 0


def test_rehearsal_is_reproducible_and_manifest_addressed():
    first = shadow_rehearsal.run_rehearsal(evaluated_at=NOW)
    second = shadow_rehearsal.run_rehearsal(evaluated_at=NOW)
    assert first == second
    assert len(first["manifest_sha256"]) == 64


def test_registry_version_and_hash_are_pinned(tmp_path):
    value, path = _copy_manifest(tmp_path)
    value["registry_sha256"] = "0" * 64
    path.write_text(json.dumps(value))
    with pytest.raises(BenchmarkContractError, match="registry_sha256 mismatch"):
        shadow_rehearsal.run_rehearsal(
            evaluated_at=NOW, schedule_path=path,
        )


def test_coverage_gaps_cannot_be_hidden(tmp_path):
    value, path = _copy_manifest(tmp_path)
    value["known_coverage_gaps"] = []
    path.write_text(json.dumps(value))
    with pytest.raises(BenchmarkContractError, match="coverage gaps"):
        shadow_rehearsal.run_rehearsal(
            evaluated_at=NOW, schedule_path=path,
        )


@pytest.mark.parametrize("ticker", ["UNKNOWN", "", "private-company"])
def test_unregistered_issuers_are_rejected(tmp_path, ticker):
    value, path = _copy_manifest(tmp_path)
    value["schedules"][0]["issuer_id"] = ticker
    path.write_text(json.dumps(value))
    with pytest.raises(BenchmarkContractError, match="not in the frozen registry"):
        shadow_rehearsal.run_rehearsal(
            evaluated_at=NOW, schedule_path=path,
        )


def test_diversity_floor_is_enforced(tmp_path):
    value, path = _copy_manifest(tmp_path)
    value["schedules"] = value["schedules"][:5]
    value["schedule_policy"]["maximum_jobs_per_tick"] = 5
    path.write_text(json.dumps(value))
    with pytest.raises(BenchmarkContractError, match="at least six issuers"):
        shadow_rehearsal.run_rehearsal(
            evaluated_at=NOW, schedule_path=path,
        )


@pytest.mark.parametrize("tier", ["mid", "small_micro"])
def test_cap_tier_floor_is_enforced(tmp_path, tier):
    value, path = _copy_manifest(tmp_path)
    registry = shadow_rehearsal.load_registry()
    selected = [
        item for item in value["schedules"]
        if registry.by_ticker()[item["issuer_id"]].market_cap_tier.value != tier
    ]
    value["schedules"] = selected
    value["schedule_policy"]["maximum_jobs_per_tick"] = len(selected)
    value["safety_policy"]["maximum_daily_jobs"] = len(selected)
    path.write_text(json.dumps(value))
    with pytest.raises(BenchmarkContractError, match=tier):
        shadow_rehearsal.run_rehearsal(evaluated_at=NOW, schedule_path=path)


def test_cli_returns_success_only_for_passing_rehearsal(capsys):
    assert benchmark_shadow_rehearsal.main(["--at", NOW]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["passed"] is True
    assert output["checks"]["zero_provider_calls"] is True


def test_rehearsal_import_boundary_excludes_side_effect_subsystems():
    tree = ast.parse(open(shadow_rehearsal.__file__, encoding="utf-8").read())
    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.append(node.module or "")
    forbidden = ("app", "provider", "research", "memory", "delivery", "notification")
    assert not any(token in module for module in imports for token in forbidden)
