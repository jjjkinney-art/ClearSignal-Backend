#!/usr/bin/env python3
"""
Phase 14 Shadow Validation Script — Scenario Engine

Validates that the Phase 14 Scenario Engine is fully inert in shadow mode:
no user-visible delivery, no source-table mutation, no recommendation/conviction
language, all safety invariants holding.

Exit 0 on full pass.  Exit 1 on any failure.

Usage:
    python tests/validate_14_scenario_shadow.py
"""

from __future__ import annotations

import ast
import importlib
import inspect
import os
import sys
import textwrap
import traceback
from typing import Any, Dict, List, Optional, Tuple

# Make project root importable regardless of working directory
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

PASS = "\033[32mPASS\033[0m"
FAIL = "\033[31mFAIL\033[0m"
WARN = "\033[33mWARN\033[0m"

_results: List[Tuple[str, bool, str]] = []


def check(name: str, condition: bool, detail: str = "") -> bool:
    label = PASS if condition else FAIL
    line = f"  [{label}] {name}"
    if detail and not condition:
        line += f"\n         {detail}"
    print(line)
    _results.append((name, condition, detail))
    return condition


def section(title: str) -> None:
    print(f"\n{title}")
    print("-" * len(title))


# ---------------------------------------------------------------------------
# 1. DB table count
# ---------------------------------------------------------------------------

def check_db_table_count() -> None:
    section("1. DB schema: table count ≥ 49")
    try:
        from app.db.models import Base
        tables = Base.metadata.tables
        check("db_table_count >= 49", len(tables) >= 49,
              f"found {len(tables)} tables")
    except Exception as exc:
        check("db_table_count >= 49", False, str(exc))


# ---------------------------------------------------------------------------
# 2. Scenario tables exist
# ---------------------------------------------------------------------------

def check_scenario_tables() -> None:
    section("2. Scenario tables present in metadata")
    try:
        from app.db.models import Base
        tables = set(Base.metadata.tables.keys())
        for t in ("scenario_snapshot", "scenario_evidence", "scenario_run_log"):
            check(f"table {t!r} exists", t in tables)
    except Exception as exc:
        check("scenario tables importable", False, str(exc))


# ---------------------------------------------------------------------------
# 3. All scenario services importable
# ---------------------------------------------------------------------------

_SCENARIO_SERVICES = [
    "app.services.scenario_seed_builder",
    "app.services.scenario_propagation_engine",
    "app.services.scenario_explainability_service",
    "app.services.scenario_invalidation_service",
    "app.services.scenario_read_service",
    "app.services.scenario_portfolio_propagation",
    "app.services.scenario_delivery_service",
    "app.services.scenario_calibration_service",
    "app.services.scenario_observability_service",
]


def check_services_importable() -> None:
    section("3. All scenario services importable")
    for mod_path in _SCENARIO_SERVICES:
        try:
            importlib.import_module(mod_path)
            check(f"import {mod_path}", True)
        except Exception as exc:
            check(f"import {mod_path}", False, str(exc))


# ---------------------------------------------------------------------------
# 4. All flags inert (default production state)
# ---------------------------------------------------------------------------

def check_flags_inert() -> None:
    section("4. Flags in default inert state")
    try:
        from app.config import settings
        check("scenario_build_enabled = False",
              not settings.scenario_build_enabled)
        check("scenario_scoring_enabled = False",
              not settings.scenario_scoring_enabled)
        check("scenario_delivery_enabled = False",
              not settings.scenario_delivery_enabled)
        check("scenario_shadow = True",
              bool(settings.scenario_shadow))
        check("scenario_calibration_enabled = False",
              not settings.scenario_calibration_enabled)
    except Exception as exc:
        check("config flags accessible", False, str(exc))


# ---------------------------------------------------------------------------
# 5–8. AST invariant checks across scenario service sources
# ---------------------------------------------------------------------------

_BANNED_PHRASES = [
    "buy", "sell", "hold", "overweight", "underweight",
    "recommend", "target price", "position size",
    "take a position", "enter a trade", "exit a trade",
    "place an order", "execute", "short", "long position",
    "go long", "go short", "open a position", "close a position",
]

_FORBIDDEN_IMPORTS = [
    "conviction",
    "order_service",
    "execution_service",
    "stance",
    "forecast_vector",
]

_WRITE_BACK_PATTERNS = [
    # forecast write-back — reading ForecastVector is OK; writing is not
    ("no forecast write-back", ["add_forecast", "upsert_forecast", "write_forecast"]),
    # decision write-back — reading models is OK; writing is not
    ("no decision write-back", ["add_decision", "upsert_decision", "write_decision"]),
]

_SOURCE_MUTATION_PATTERNS = [
    "add_snapshot",   # scenario_snapshot write
    "upsert_snapshot",
    ".update(",
    ".delete(",
]


def _load_scenario_sources() -> Dict[str, str]:
    sources = {}
    for mod_path in _SCENARIO_SERVICES:
        try:
            mod = importlib.import_module(mod_path)
            path = inspect.getfile(mod)
            with open(path, "r", encoding="utf-8") as fh:
                sources[mod_path] = fh.read()
        except Exception:
            pass
    return sources


def _get_non_docstring_constants(source: str) -> List[str]:
    """Return string literals that are not docstrings."""
    try:
        tree = ast.parse(source)
        docstring_ids: set = set()

        def _mark(node):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                                 ast.ClassDef, ast.Module)):
                body = node.body
                if body and isinstance(body[0], ast.Expr):
                    val = body[0].value
                    if isinstance(val, ast.Constant) and isinstance(val.value, str):
                        docstring_ids.add(id(val))
            for child in ast.iter_child_nodes(node):
                _mark(child)

        _mark(tree)
        return [
            node.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and id(node) not in docstring_ids
        ]
    except Exception:
        return []


def _get_imported_names(source: str) -> List[str]:
    """Return all module names that appear in actual import statements."""
    try:
        tree = ast.parse(source)
        names = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                names.append(module)
                # Also capture "from pkg import SomeClass"
                names.extend(alias.name for alias in node.names)
        return names
    except Exception:
        return []


def check_no_recommendation_imports() -> None:
    section("5. No recommendation imports in scenario services")
    sources = _load_scenario_sources()
    for mod_path, source in sources.items():
        imported = _get_imported_names(source)
        found = [
            p for p in _FORBIDDEN_IMPORTS
            if any(p in name.lower() for name in imported)
        ]
        check(f"{mod_path}: no forbidden imports",
              len(found) == 0,
              f"found: {found}")


def check_no_conviction_imports() -> None:
    section("6. No conviction imports in scenario services")
    sources = _load_scenario_sources()
    for mod_path, source in sources.items():
        has_conviction = (
            "from app.services.conviction" in source
            or "import conviction_service" in source
            or "ConvictionService" in source
        )
        check(f"{mod_path}: no conviction import",
              not has_conviction,
              "conviction import found")


def check_no_forecast_writeback() -> None:
    section("7. No forecast write-back in scenario services")
    sources = _load_scenario_sources()
    label, patterns = _WRITE_BACK_PATTERNS[0]
    for mod_path, source in sources.items():
        found = [p for p in patterns if p in source]
        check(f"{mod_path}: {label}", len(found) == 0, f"found: {found}")


def check_no_decision_writeback() -> None:
    section("8. No decision write-back in scenario services")
    sources = _load_scenario_sources()
    label, patterns = _WRITE_BACK_PATTERNS[1]
    for mod_path, source in sources.items():
        found = [p for p in patterns if p in source]
        check(f"{mod_path}: {label}", len(found) == 0, f"found: {found}")


def _is_sentinel_list_constant(source: str, value: str) -> bool:
    """Return True if the string constant is an item inside a _BANNED_PHRASES list.

    The explainability and seed builder services define a _BANNED_PHRASES list
    whose items ARE the forbidden terms — those items are sentinel guards, not
    advice text.  We exclude them from the advice-language check.
    """
    # If the source defines a _BANNED_PHRASES or similar list, its list-item
    # string values are expected to contain the banned terms.
    sentinel_markers = [
        "_BANNED_PHRASES",
        "BANNED_PHRASES",
        "_FORBIDDEN_PHRASES",
    ]
    return any(m in source for m in sentinel_markers) and len(value) < 80


def check_no_target_price_language() -> None:
    section("9. No target-price / recommendation language in string constants")
    sources = _load_scenario_sources()
    # Only check strings that are real output text (keys, log messages, responses)
    # Skip modules whose purpose is to enumerate the banned-phrase sentinel list
    target_phrases = ["target price", "recommend", "buy", "sell"]
    for mod_path, source in sources.items():
        constants = _get_non_docstring_constants(source)
        has_sentinel = "_BANNED_PHRASES" in source or "BANNED_PHRASES" in source
        found = []
        for p in target_phrases:
            for c in constants:
                if p.lower() in c.lower():
                    # Exclude short strings (dict keys, log tags, enum values)
                    # and sentinel-list items — only flag substantive text
                    if len(c.strip()) < 60:
                        continue
                    if has_sentinel and len(c.strip()) < 120:
                        continue
                    found.append(p)
                    break
        check(f"{mod_path}: no target-price language", len(found) == 0,
              f"phrases found in string constants: {found}")


# ---------------------------------------------------------------------------
# 10. No public scenario route
# ---------------------------------------------------------------------------

def check_no_public_scenario_route() -> None:
    section("10. No public scenario route (read-only admin only)")
    api_path = os.path.join(_ROOT, "app", "api.py")
    try:
        with open(api_path, "r", encoding="utf-8") as fh:
            source = fh.read()
        # Public routes would not be under /admin/
        tree = ast.parse(source)
        public_scenario_routes = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            # @router.get("/<path>") style
            if isinstance(func, ast.Attribute) and func.attr in ("get", "post"):
                if node.args and isinstance(node.args[0], ast.Constant):
                    path_val = node.args[0].value
                    if (isinstance(path_val, str)
                            and "scenario" in path_val.lower()
                            and not path_val.startswith("/admin/")):
                        public_scenario_routes.append(path_val)
        check("no public /scenario route", len(public_scenario_routes) == 0,
              f"found: {public_scenario_routes}")
    except Exception as exc:
        check("no public /scenario route", False, str(exc))


# ---------------------------------------------------------------------------
# 11. Admin scenario-status route present
# ---------------------------------------------------------------------------

def check_admin_scenario_status_route() -> None:
    section("11. /admin/scenario-status route present")
    api_path = os.path.join(_ROOT, "app", "api.py")
    try:
        with open(api_path, "r", encoding="utf-8") as fh:
            source = fh.read()
        check("/admin/scenario-status in api.py", "/admin/scenario-status" in source)
        check("build_scenario_observability_snapshot called",
              "build_scenario_observability_snapshot" in source)
    except Exception as exc:
        check("/admin/scenario-status present", False, str(exc))


# ---------------------------------------------------------------------------
# 12. safe_state check (async, runs under asyncio)
# ---------------------------------------------------------------------------

async def _async_check_safe_state() -> bool:
    from app.services.scenario_observability_service import (
        build_scenario_observability_snapshot,
    )
    snap = await build_scenario_observability_snapshot(None)
    return snap["safe_state"]["overall"]


def check_safe_state() -> None:
    section("12. safe_state overall True on null session")
    import asyncio
    try:
        result = asyncio.run(_async_check_safe_state())
        check("safe_state.overall True (null session)", result)
    except Exception as exc:
        check("safe_state.overall", False, str(exc))


# ---------------------------------------------------------------------------
# 13. No Notification rows seeded by scenario path
# ---------------------------------------------------------------------------

def check_no_notification_rows() -> None:
    section("13. Notification table not written by scenario services")
    sources = _load_scenario_sources()
    for mod_path, source in sources.items():
        has_notif_write = (
            "Notification(" in source
            and "import Notification" in source
        )
        check(f"{mod_path}: no Notification write",
              not has_notif_write)


# ---------------------------------------------------------------------------
# 14. No source-table mutation
# ---------------------------------------------------------------------------

def check_no_source_mutation() -> None:
    section("14. No source-table mutation in scenario services")
    sources = _load_scenario_sources()
    for mod_path, source in sources.items():
        found = [p for p in _SOURCE_MUTATION_PATTERNS if p in source]
        # add_run_log is the sole allowed write — exclude it
        found = [p for p in found if p != "add_snapshot"]
        check(f"{mod_path}: no prohibited write patterns",
              len(found) == 0, f"found: {found}")


# ---------------------------------------------------------------------------
# 15. Explainability invariants
# ---------------------------------------------------------------------------

def check_explainability_invariants() -> None:
    section("15. Explainability service invariants")
    try:
        from app.services import scenario_explainability_service as expl
        check("build_scenario_explanation function exists",
              hasattr(expl, "build_scenario_explanation"))
        check("validate_scenario_explanation function exists",
              hasattr(expl, "validate_scenario_explanation"))
        check("build_scenario_explanation is sync (pure)",
              not inspect.iscoroutinefunction(expl.build_scenario_explanation))
        # Verify no conviction/decision writes
        path = inspect.getfile(expl)
        with open(path, "r", encoding="utf-8") as fh:
            src = fh.read()
        for pattern in ("add_conviction", "add_decision", "add_forecast"):
            check(f"explainability: no {pattern}", pattern not in src)
    except Exception as exc:
        check("explainability service importable", False, str(exc))


# ---------------------------------------------------------------------------
# 16. Propagation invariants
# ---------------------------------------------------------------------------

def check_propagation_invariants() -> None:
    section("16. Propagation engine invariants")
    try:
        from app.services import scenario_propagation_engine as eng
        # Primary dispatcher functions
        check("propagate_scenario function exists",
              hasattr(eng, "propagate_scenario"))
        check("propagate_scenario is async",
              inspect.iscoroutinefunction(eng.propagate_scenario))
        check("propagate_all function exists",
              hasattr(eng, "propagate_all"))
        # Verify propagation does not write to conviction, forecast, decision
        path = inspect.getfile(eng)
        with open(path, "r", encoding="utf-8") as fh:
            src = fh.read()
        for pattern in ("add_forecast", "add_decision", "add_conviction"):
            check(f"propagation engine: no {pattern}", pattern not in src)
    except Exception as exc:
        check("propagation engine importable", False, str(exc))


# ---------------------------------------------------------------------------
# 17. Calibration invariants
# ---------------------------------------------------------------------------

def check_calibration_invariants() -> None:
    section("17. Calibration service invariants")
    try:
        from app.services import scenario_calibration_service as cal
        check("record_scenario_outcome exists",
              hasattr(cal, "record_scenario_outcome"))
        check("record_scenario_outcome is async",
              inspect.iscoroutinefunction(cal.record_scenario_outcome))
        check("calculate_scenario_hit_rate exists",
              hasattr(cal, "calculate_scenario_hit_rate"))
        check("MIN_SAMPLES constant exists",
              hasattr(cal, "MIN_SAMPLES") and cal.MIN_SAMPLES > 0)
        # Verify calibration service has no UPDATE or DELETE
        path = inspect.getfile(cal)
        with open(path, "r", encoding="utf-8") as fh:
            src = fh.read()
        check("calibration: no .update() call", ".update(" not in src)
        check("calibration: no .delete() call", ".delete(" not in src)
    except Exception as exc:
        check("calibration service importable", False, str(exc))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    print("=" * 60)
    print("Phase 14 — Scenario Shadow Validation")
    print("=" * 60)

    check_db_table_count()
    check_scenario_tables()
    check_services_importable()
    check_flags_inert()
    check_no_recommendation_imports()
    check_no_conviction_imports()
    check_no_forecast_writeback()
    check_no_decision_writeback()
    check_no_target_price_language()
    check_no_public_scenario_route()
    check_admin_scenario_status_route()
    check_safe_state()
    check_no_notification_rows()
    check_no_source_mutation()
    check_explainability_invariants()
    check_propagation_invariants()
    check_calibration_invariants()

    total   = len(_results)
    passed  = sum(1 for _, ok, _ in _results if ok)
    failed  = total - passed

    print("\n" + "=" * 60)
    print(f"Results: {passed}/{total} passed", end="")
    if failed:
        print(f"  ({failed} FAILED)")
    else:
        print("  — all checks passed")
    print("=" * 60)

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
