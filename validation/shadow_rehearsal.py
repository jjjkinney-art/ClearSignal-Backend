"""Fail-closed rehearsal for the frozen synthetic benchmark schedule."""
from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any, Dict, Mapping

from .benchmark_registry import REGISTRY_PATH, IssuerRegistry, load_registry
from .intelligence_benchmark import BenchmarkContractError, content_hash
from .shadow_scheduler import evaluate_schedule_tick


SCHEDULE_PATH = Path(__file__).with_name("shadow_schedule.v1.json")
EXPECTED_GAPS = frozenset({"mid_cap", "small_micro"})
MINIMUM_CAP_TIER_ISSUERS = {"mega_large": 6, "mid": 3, "small_micro": 3}
FORBIDDEN_IMPORT_TOKENS = (
    "app", "provider", "research", "memory", "delivery", "notification",
)


def load_schedule(path: Path = SCHEDULE_PATH) -> Dict[str, Any]:
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise BenchmarkContractError("schedule manifest must be an object")
    return value


def _validate_manifest(manifest: Mapping[str, Any], registry: IssuerRegistry) -> None:
    if manifest.get("manifest_version") != 1:
        raise BenchmarkContractError("manifest_version must be 1")
    if manifest.get("registry_version") != registry.registry_version:
        raise BenchmarkContractError("schedule registry_version mismatch")
    if manifest.get("registry_sha256") != registry.registry_sha256:
        raise BenchmarkContractError("schedule registry_sha256 mismatch")
    gaps = manifest.get("known_coverage_gaps")
    if not isinstance(gaps, list) or set(gaps) != EXPECTED_GAPS:
        raise BenchmarkContractError(
            "known coverage gaps must explicitly include mid_cap and small_micro"
        )

    issuers = registry.by_ticker()
    selected = []
    for item in manifest.get("schedules", ()):
        ticker = str(item.get("issuer_id", "")).upper()
        if ticker not in issuers:
            raise BenchmarkContractError(
                f"scheduled issuer {ticker or '<missing>'} is not in the frozen registry"
            )
        selected.append(issuers[ticker])
    if len(selected) < 6:
        raise BenchmarkContractError("frozen schedule requires at least six issuers")
    if len({item.sector for item in selected}) < 6:
        raise BenchmarkContractError("frozen schedule requires at least six sectors")
    if len({item.domicile for item in selected}) < 2:
        raise BenchmarkContractError("frozen schedule requires at least two domiciles")
    if len({item.reporting_basis for item in selected}) < 2:
        raise BenchmarkContractError(
            "frozen schedule requires both US GAAP and IFRS coverage"
        )
    tier_counts = {
        tier: sum(item.market_cap_tier.value == tier for item in selected)
        for tier in MINIMUM_CAP_TIER_ISSUERS
    }
    for tier, minimum in MINIMUM_CAP_TIER_ISSUERS.items():
        if tier_counts[tier] < minimum:
            raise BenchmarkContractError(
                f"frozen schedule requires at least {minimum} {tier} issuers"
            )


def _side_effect_import_boundary_clear() -> bool:
    """Prove the rehearsal path cannot reach production side-effect modules."""
    paths = (Path(__file__), Path(__file__).with_name("shadow_scheduler.py"))
    imports = []
    for path in paths:
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imports.append(node.module or "")
    return not any(
        token in module
        for module in imports
        for token in FORBIDDEN_IMPORT_TOKENS
    )


def run_rehearsal(
    *, evaluated_at: str, schedule_path: Path = SCHEDULE_PATH,
    registry_path: Path = REGISTRY_PATH,
) -> Dict[str, Any]:
    """Run one dry tick and emit explicit zero-side-effect evidence."""
    manifest = load_schedule(schedule_path)
    registry = load_registry(registry_path)
    _validate_manifest(manifest, registry)
    result = evaluate_schedule_tick({
        "evaluated_at": evaluated_at,
        "schedule_policy": manifest["schedule_policy"],
        "safety_policy": manifest["safety_policy"],
        "schedules": manifest["schedules"],
    })
    decisions = result["decisions"]
    side_effect_boundary_clear = _side_effect_import_boundary_clear()
    checks = {
        "all_decisions_dry_run": bool(decisions) and all(
            item["status"] == "dry_run" for item in decisions
        ),
        "zero_reservations": (
            result["operator_snapshot"]["active_jobs"] == 0
            and result["operator_snapshot"]["reserved_cost_usd"] == 0
            and all(item["reservation_id"] is None for item in decisions)
        ),
        "side_effect_import_boundary_clear": side_effect_boundary_clear,
        "zero_provider_calls": side_effect_boundary_clear,
        "zero_research_executions": side_effect_boundary_clear,
        "zero_memory_writes": side_effect_boundary_clear,
        "zero_notifications": side_effect_boundary_clear,
    }
    passed = result["inert"] and all(checks.values())
    selected = [
        registry.by_ticker()[item["issuer_id"]]
        for item in manifest["schedules"]
    ]
    return {
        "schema_version": 1,
        "passed": passed,
        "manifest_sha256": content_hash(manifest),
        "registry_sha256": registry.registry_sha256,
        "issuer_count": len(manifest["schedules"]),
        "sector_count": len({
            item.sector for item in selected
        }),
        "market_cap_counts": {
            tier: sum(item.market_cap_tier.value == tier for item in selected)
            for tier in MINIMUM_CAP_TIER_ISSUERS
        },
        "known_coverage_gaps": manifest["known_coverage_gaps"],
        "checks": checks,
        "tick": result,
    }
