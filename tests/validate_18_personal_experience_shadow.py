#!/usr/bin/env python3
"""
Phase 18 Shadow Validation Script — Personal Experience Layer

Validates that the Phase 18 Personal Experience system is fully inert in
shadow mode: no user-visible delivery, no truth-table mutation, no
recommendation/conviction language, all safety invariants holding.

Exit 0 on full pass.  Exit 1 on any failure.

Usage:
    python tests/validate_18_personal_experience_shadow.py
"""

from __future__ import annotations

import ast
import importlib
import os
import sys
from typing import List, Tuple

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

PASS = "\033[32mPASS\033[0m"
FAIL = "\033[31mFAIL\033[0m"

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
    section("1. DB schema: table count >= 56")
    try:
        from app.db.models import Base
        tables = Base.metadata.tables
        check("db_table_count >= 56", len(tables) >= 56,
              f"found {len(tables)} tables")
    except Exception as exc:
        check("db_table_count >= 56", False, str(exc))


# ---------------------------------------------------------------------------
# 2. Personal Experience tables exist
# ---------------------------------------------------------------------------

def check_experience_tables() -> None:
    section("2. Personal Experience tables present in metadata")
    try:
        from app.db.models import Base
        tables = set(Base.metadata.tables.keys())
        for t in (
            "personal_experience_cursor",
            "personal_experience_event",
            "personal_brief_snapshot",
        ):
            check(f"table '{t}' exists", t in tables)
    except Exception as exc:
        check("experience_tables", False, str(exc))


# ---------------------------------------------------------------------------
# 3. All Phase 18 services import
# ---------------------------------------------------------------------------

_EXPERIENCE_SERVICES = [
    "app.services.personal_experience_change_service",
    "app.services.personal_experience_attention_service",
    "app.services.personal_experience_composer_service",
    "app.services.personal_experience_memory_service",
    "app.services.personal_experience_brief_service",
    "app.services.personal_experience_shadow_service",
    "app.services.personal_experience_calibration_service",
    "app.services.personal_experience_observability_service",
]


def check_services_import() -> None:
    section("3. All Phase 18 services importable")
    for mod_name in _EXPERIENCE_SERVICES:
        try:
            importlib.import_module(mod_name)
            check(f"import {mod_name}", True)
        except Exception as exc:
            check(f"import {mod_name}", False, str(exc))


# ---------------------------------------------------------------------------
# 4. All Phase 18 flags at safe defaults
# ---------------------------------------------------------------------------

def check_flags_safe() -> None:
    section("4. All Phase 18 flags at safe defaults")
    try:
        from app.config import settings
        checks = [
            ("experience_change_detection_enabled", False),
            ("experience_attention_enabled", False),
            ("experience_composer_enabled", False),
            ("experience_memory_enabled", False),
            ("experience_shadow", True),
            ("experience_brief_enabled", False),
        ]
        for flag_name, expected in checks:
            actual = getattr(settings, flag_name, "MISSING")
            ok = actual == expected
            check(f"{flag_name} == {expected!r}", ok,
                  f"actual={actual!r}")
    except Exception as exc:
        check("flags_safe", False, str(exc))


# ---------------------------------------------------------------------------
# 5. No forbidden imports in Phase 18 services
# ---------------------------------------------------------------------------

_BANNED_IMPORTS = [
    "forecast_repo",
    "decision_repo",
    "scenario_repo",
    "similarity_repo",
    "conviction",
    "order",
    "execution",
    "stance",
]


def check_no_forbidden_imports() -> None:
    section("5. No forbidden imports in Phase 18 services")
    for mod_name in _EXPERIENCE_SERVICES:
        try:
            mod = importlib.import_module(mod_name)
            src_path = getattr(mod, "__file__", None)
            if not src_path or not os.path.isfile(src_path):
                check(f"{mod_name}: source readable", False, "file not found")
                continue
            with open(src_path) as f:
                source = f.read()
            tree = ast.parse(source)
            violations = []
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module:
                    for banned in _BANNED_IMPORTS:
                        if banned in node.module:
                            violations.append(f"{node.module} (contains '{banned}')")
            check(f"{mod_name}: no forbidden imports",
                  len(violations) == 0,
                  "; ".join(violations))
        except Exception as exc:
            check(f"{mod_name}: no forbidden imports", False, str(exc))


# ---------------------------------------------------------------------------
# 6. No upstream writes (no .update/.delete in services)
# ---------------------------------------------------------------------------

def check_no_upstream_writes() -> None:
    section("6. No upstream writes in Phase 18 services")
    for mod_name in _EXPERIENCE_SERVICES:
        try:
            mod = importlib.import_module(mod_name)
            src_path = getattr(mod, "__file__", None)
            if not src_path or not os.path.isfile(src_path):
                check(f"{mod_name}: source readable", False)
                continue
            with open(src_path) as f:
                source = f.read()
            patterns = [".update(", ".delete(", "DELETE FROM", "UPDATE "]
            found = [p for p in patterns if p in source]
            check(f"{mod_name}: no mutation patterns",
                  len(found) == 0,
                  f"found: {found}")
        except Exception as exc:
            check(f"{mod_name}: no mutation patterns", False, str(exc))


# ---------------------------------------------------------------------------
# 7. No recommendation language in services
# ---------------------------------------------------------------------------

_BANNED_PHRASES = [
    "buy", "sell",
    "overweight", "underweight", "recommend",
    "target price", "position size",
    "take a position", "enter a trade", "exit a trade",
    "place an order", "execute",
    "short", "long position",
    "go long", "go short",
    "open a position", "close a position",
]


def check_no_recommendation_language() -> None:
    section("7. No recommendation language in Phase 18 services")
    for mod_name in _EXPERIENCE_SERVICES:
        try:
            mod = importlib.import_module(mod_name)
            src_path = getattr(mod, "__file__", None)
            if not src_path or not os.path.isfile(src_path):
                check(f"{mod_name}: source readable", False)
                continue
            with open(src_path) as f:
                source = f.read()
            tree = ast.parse(source)

            docstring_ids: set = set()
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                                     ast.ClassDef, ast.Module)):
                    body = getattr(node, "body", [])
                    if (body and isinstance(body[0], ast.Expr)
                            and isinstance(body[0].value, ast.Constant)):
                        docstring_ids.add(id(body[0].value))

            violations = []
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and isinstance(node.value, str):
                    if id(node) in docstring_ids:
                        continue
                    val = node.value.lower()
                    for phrase in _BANNED_PHRASES:
                        if phrase in val:
                            violations.append(
                                f"line {getattr(node, 'lineno', '?')}: '{phrase}'"
                            )
            check(f"{mod_name}: no banned phrases",
                  len(violations) == 0,
                  "; ".join(violations[:5]))
        except Exception as exc:
            check(f"{mod_name}: no banned phrases", False, str(exc))


# ---------------------------------------------------------------------------
# 8. Explainability gate present in composer
# ---------------------------------------------------------------------------

def check_explainability_gate() -> None:
    section("8. Explainability gate present in composer")
    try:
        from app.services.personal_experience_composer_service import (
            validate_experience_item,
        )
        check("validate_experience_item callable", callable(validate_experience_item))

        ok, reason = validate_experience_item({})
        check("empty item fails gate", ok is False, reason)

        ok2, reason2 = validate_experience_item({
            "why_am_i_seeing_this": "test",
            "why_now": "test",
            "what_changed": "test",
            "supporting_evidence": ["ref"],
        })
        check("complete item passes gate", ok2 is True)
    except Exception as exc:
        check("explainability_gate", False, str(exc))


# ---------------------------------------------------------------------------
# 9. Shadow-only behavior
# ---------------------------------------------------------------------------

def check_shadow_only() -> None:
    section("9. Shadow-only behavior")
    try:
        from app.services.personal_experience_shadow_service import (
            record_experience_events,
        )
        check("record_experience_events callable", callable(record_experience_events))
    except Exception as exc:
        check("shadow_service", False, str(exc))

    try:
        from app.services.personal_experience_brief_service import (
            build_daily_brief,
        )
        check("build_daily_brief callable", callable(build_daily_brief))
    except Exception as exc:
        check("brief_service", False, str(exc))


# ---------------------------------------------------------------------------
# 10. Calibration append-only
# ---------------------------------------------------------------------------

def check_calibration_append_only() -> None:
    section("10. Calibration service append-only")
    try:
        mod = importlib.import_module(
            "app.services.personal_experience_calibration_service")
        src_path = getattr(mod, "__file__", None)
        if not src_path:
            check("calibration_source", False, "file not found")
            return
        with open(src_path) as f:
            source = f.read()
        patterns = [".update(", ".delete(", "DELETE FROM", "UPDATE "]
        found = [p for p in patterns if p in source]
        check("calibration: no mutation patterns",
              len(found) == 0, f"found: {found}")
        check("calibration: uses add_experience_event",
              "add_experience_event" in source)
    except Exception as exc:
        check("calibration_append_only", False, str(exc))


# ---------------------------------------------------------------------------
# 11. safe_state overall true
# ---------------------------------------------------------------------------

def check_safe_state() -> None:
    section("11. safe_state overall true (observability snapshot)")
    try:
        import asyncio
        from app.services.personal_experience_observability_service import (
            build_personal_experience_snapshot,
        )
        snapshot = asyncio.get_event_loop().run_until_complete(
            build_personal_experience_snapshot(None)
        )
        safe = snapshot.get("safe_state", {})
        check("safe_state.shadow_only", safe.get("shadow_only", False) is True)
        check("safe_state.no_live_delivery", safe.get("no_live_delivery", False) is True)
        check("safe_state.no_truth_mutation", safe.get("no_truth_mutation", False) is True)
        check("safe_state.no_advisory_generation",
              safe.get("no_advisory_generation", False) is True)
        check("safe_state.no_upstream_mutation",
              safe.get("no_upstream_mutation", False) is True)
        check("safe_state.explainability_gate_active",
              safe.get("explainability_gate_active", False) is True)
        check("safe_state.overall", safe.get("overall", False) is True)

        check("schema_version == 1", snapshot.get("schema_version") == 1)
        check("disclaimer present", bool(snapshot.get("disclaimer")))
    except Exception as exc:
        check("safe_state_overall", False, str(exc))


# ---------------------------------------------------------------------------
# 12. Repository: append-only for events
# ---------------------------------------------------------------------------

def check_repo_append_only() -> None:
    section("12. Repository: events append-only")
    try:
        mod = importlib.import_module(
            "app.db.repositories.personal_experience_repo")
        src_path = getattr(mod, "__file__", None)
        if not src_path:
            check("repo_source", False, "file not found")
            return
        with open(src_path) as f:
            source = f.read()
        check("repo: no DELETE FROM", "DELETE FROM" not in source)
        check("repo: has add_experience_event", "add_experience_event" in source)
    except Exception as exc:
        check("repo_append_only", False, str(exc))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    print("=" * 60)
    print("Phase 18 · Personal Experience Shadow Validation")
    print("=" * 60)

    check_db_table_count()
    check_experience_tables()
    check_services_import()
    check_flags_safe()
    check_no_forbidden_imports()
    check_no_upstream_writes()
    check_no_recommendation_language()
    check_explainability_gate()
    check_shadow_only()
    check_calibration_append_only()
    check_safe_state()
    check_repo_append_only()

    total = len(_results)
    passed = sum(1 for _, ok, _ in _results if ok)
    failed = total - passed

    print(f"\n{'=' * 60}")
    print(f"Results: {passed}/{total} passed, {failed} failed")
    print(f"{'=' * 60}")

    if failed:
        print(f"\n{FAIL} Phase 18 shadow validation FAILED")
        sys.exit(1)
    else:
        print(f"\n{PASS} Phase 18 shadow validation PASSED")
        sys.exit(0)


if __name__ == "__main__":
    main()
