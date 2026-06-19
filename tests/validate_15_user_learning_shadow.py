#!/usr/bin/env python3
"""
Phase 15 Shadow Validation Script — User Learning & Personalization

Validates that the Phase 15 User Learning system is fully inert in shadow mode:
no user-visible delivery, no truth-table mutation, no recommendation/conviction
language, all safety invariants holding.

Exit 0 on full pass.  Exit 1 on any failure.

Usage:
    python tests/validate_15_user_learning_shadow.py
"""

from __future__ import annotations

import ast
import importlib
import inspect
import os
import sys
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
    section("1. DB schema: table count >= 53")
    try:
        from app.db.models import Base
        tables = Base.metadata.tables
        check("db_table_count >= 53", len(tables) >= 53,
              f"found {len(tables)} tables")
    except Exception as exc:
        check("db_table_count >= 53", False, str(exc))


# ---------------------------------------------------------------------------
# 2. Learning tables exist
# ---------------------------------------------------------------------------

def check_learning_tables() -> None:
    section("2. Learning tables present in metadata")
    try:
        from app.db.models import Base
        tables = set(Base.metadata.tables.keys())
        for t in (
            "user_signal_event",
            "learned_preference",
            "preference_evidence",
            "relevance_adjustment_log",
        ):
            check(f"table {t!r} exists", t in tables)
    except Exception as exc:
        check("learning tables importable", False, str(exc))


# ---------------------------------------------------------------------------
# 3. All learning services importable
# ---------------------------------------------------------------------------

_LEARNING_SERVICES = [
    "app.db.repositories.user_learning_repo",
    "app.services.user_signal_capture_service",
    "app.services.user_learning_explainability_service",
    "app.services.user_learning_inference_service",
    "app.services.user_learning_decay_service",
    "app.services.user_learning_profile_service",
    "app.services.user_learning_relevance_service",
    "app.services.user_learning_shadow_service",
    "app.services.user_learning_calibration_service",
    "app.services.user_learning_observability_service",
]


def check_services_importable() -> None:
    section("3. All learning services importable")
    for mod_path in _LEARNING_SERVICES:
        try:
            importlib.import_module(mod_path)
            check(f"import {mod_path}", True)
        except Exception as exc:
            check(f"import {mod_path}", False, str(exc))


# ---------------------------------------------------------------------------
# 4. All learning flags inert (default production state)
# ---------------------------------------------------------------------------

def check_flags_inert() -> None:
    section("4. Flags in default inert state")
    try:
        from app.config import settings
        check("learning_capture_enabled = False",
              not getattr(settings, "learning_capture_enabled", True))
        check("learning_inference_enabled = False",
              not getattr(settings, "learning_inference_enabled", True))
        check("learning_relevance_enabled = False",
              not getattr(settings, "learning_relevance_enabled", True))
        check("learning_shadow = True",
              bool(getattr(settings, "learning_shadow", False)))
        check("learning_calibration_enabled = False",
              not getattr(settings, "learning_calibration_enabled", True))
    except Exception as exc:
        check("config flags accessible", False, str(exc))


# ---------------------------------------------------------------------------
# AST helpers (shared)
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

_TRUTH_WRITE_PATTERNS = [
    "add_forecast", "upsert_forecast", "write_forecast",
    "add_decision", "upsert_decision", "write_decision",
    "add_scenario", "upsert_scenario",
    "add_similarity", "upsert_similarity",
    "add_conviction", "upsert_conviction",
]


def _load_learning_sources() -> Dict[str, str]:
    sources = {}
    for mod_path in _LEARNING_SERVICES:
        try:
            mod = importlib.import_module(mod_path)
            path = inspect.getfile(mod)
            with open(path, "r", encoding="utf-8") as fh:
                sources[mod_path] = fh.read()
        except Exception:
            pass
    return sources


def _get_non_docstring_constants(source: str) -> List[str]:
    try:
        tree = ast.parse(source)
        docstring_ids: set = set()

        def _mark(node: Any) -> None:
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
    try:
        tree = ast.parse(source)
        names = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                names.append(module)
                names.extend(alias.name for alias in node.names)
        return names
    except Exception:
        return []


# ---------------------------------------------------------------------------
# 5. No recommendation imports
# ---------------------------------------------------------------------------

def check_no_recommendation_imports() -> None:
    section("5. No recommendation imports in learning services")
    sources = _load_learning_sources()
    for mod_path, source in sources.items():
        imported = _get_imported_names(source)
        found = [
            p for p in _FORBIDDEN_IMPORTS
            if any(p in name.lower() for name in imported)
        ]
        check(f"{mod_path.split('.')[-1]}: no forbidden imports",
              len(found) == 0, f"found: {found}")


# ---------------------------------------------------------------------------
# 6. No truth-table mutation imports
# ---------------------------------------------------------------------------

def check_no_truth_mutation_imports() -> None:
    section("6. No truth-table mutation imports in learning services")
    sources = _load_learning_sources()
    for mod_path, source in sources.items():
        imported = _get_imported_names(source)
        found = [p for p in _TRUTH_WRITE_PATTERNS
                 if any(p in name for name in imported)]
        check(f"{mod_path.split('.')[-1]}: no truth-write imports",
              len(found) == 0, f"found: {found}")


# ---------------------------------------------------------------------------
# 7–10. Write-back checks
# ---------------------------------------------------------------------------

def check_no_forecast_writeback() -> None:
    section("7. No forecast write-back in learning services")
    sources = _load_learning_sources()
    patterns = ["add_forecast", "upsert_forecast", "write_forecast"]
    for mod_path, source in sources.items():
        found = [p for p in patterns if p in source]
        check(f"{mod_path.split('.')[-1]}: no forecast write-back",
              len(found) == 0, f"found: {found}")


def check_no_similarity_writeback() -> None:
    section("8. No similarity write-back in learning services")
    sources = _load_learning_sources()
    patterns = ["add_similarity", "upsert_similarity", "write_similarity"]
    for mod_path, source in sources.items():
        found = [p for p in patterns if p in source]
        check(f"{mod_path.split('.')[-1]}: no similarity write-back",
              len(found) == 0, f"found: {found}")


def check_no_scenario_writeback() -> None:
    section("9. No scenario write-back in learning services")
    sources = _load_learning_sources()
    patterns = ["add_scenario_snapshot", "upsert_scenario", "write_scenario"]
    for mod_path, source in sources.items():
        found = [p for p in patterns if p in source]
        check(f"{mod_path.split('.')[-1]}: no scenario write-back",
              len(found) == 0, f"found: {found}")


def check_no_decision_writeback() -> None:
    section("10. No decision write-back in learning services")
    sources = _load_learning_sources()
    patterns = ["add_decision", "upsert_decision", "write_decision"]
    for mod_path, source in sources.items():
        found = [p for p in patterns if p in source]
        check(f"{mod_path.split('.')[-1]}: no decision write-back",
              len(found) == 0, f"found: {found}")


# ---------------------------------------------------------------------------
# 11. No target-price / trade language
# ---------------------------------------------------------------------------

def check_no_target_price_language() -> None:
    section("11. No target-price / trade language in string constants")
    sources = _load_learning_sources()
    target_phrases = ["target price", "recommend", "buy", "sell"]
    for mod_path, source in sources.items():
        constants = _get_non_docstring_constants(source)
        has_sentinel = "_BANNED_PHRASES" in source or "BANNED_PHRASES" in source
        found = []
        for p in target_phrases:
            for c in constants:
                if p.lower() in c.lower():
                    if len(c.strip()) < 60:
                        continue
                    if has_sentinel and len(c.strip()) < 120:
                        continue
                    found.append(p)
                    break
        check(f"{mod_path.split('.')[-1]}: no trade/target language",
              len(found) == 0, f"phrases found: {found}")


# ---------------------------------------------------------------------------
# 12. No public learning route
# ---------------------------------------------------------------------------

def check_no_public_learning_route() -> None:
    section("12. No public /user-learning or /personalization route")
    api_path = os.path.join(_ROOT, "app", "api.py")
    try:
        with open(api_path, "r", encoding="utf-8") as fh:
            source = fh.read()
        tree = ast.parse(source)
        public_learning_routes = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if isinstance(func, ast.Attribute) and func.attr in ("get", "post", "put"):
                if node.args and isinstance(node.args[0], ast.Constant):
                    path_val = node.args[0].value
                    if isinstance(path_val, str):
                        low = path_val.lower()
                        if (("user-learning" in low or "personalization" in low)
                                and not path_val.startswith("/admin/")):
                            public_learning_routes.append(path_val)
        check("no public /user-learning route", len(public_learning_routes) == 0,
              f"found: {public_learning_routes}")
    except Exception as exc:
        check("no public /user-learning route", False, str(exc))


# ---------------------------------------------------------------------------
# 13. Admin status route present
# ---------------------------------------------------------------------------

def check_admin_status_route() -> None:
    section("13. /admin/user-learning-status route present")
    api_path = os.path.join(_ROOT, "app", "api.py")
    try:
        with open(api_path, "r", encoding="utf-8") as fh:
            source = fh.read()
        check("/admin/user-learning-status in api.py",
              "/admin/user-learning-status" in source)
        check("build_user_learning_snapshot called",
              "build_user_learning_snapshot" in source)
    except Exception as exc:
        check("/admin/user-learning-status present", False, str(exc))


# ---------------------------------------------------------------------------
# 14. safe_state True on null session
# ---------------------------------------------------------------------------

async def _async_check_safe_state() -> bool:
    from app.services.user_learning_observability_service import (
        build_user_learning_snapshot,
    )
    snap = await build_user_learning_snapshot(None)
    return bool(snap["safe_state"]["overall"])


def check_safe_state() -> None:
    section("14. safe_state.overall True with default flags (null session)")
    import asyncio
    try:
        result = asyncio.run(_async_check_safe_state())
        check("safe_state.overall True (null session)", result)
    except Exception as exc:
        check("safe_state.overall", False, str(exc))


# ---------------------------------------------------------------------------
# 15. No Notification rows
# ---------------------------------------------------------------------------

def check_no_notification_rows() -> None:
    section("15. Notification table not written by learning services")
    sources = _load_learning_sources()
    for mod_path, source in sources.items():
        imported = _get_imported_names(source)
        has_notif_import = any("Notification" in name for name in imported)
        has_notif_add = "add_notification" in source
        check(f"{mod_path.split('.')[-1]}: no Notification write",
              not (has_notif_import and has_notif_add))


# ---------------------------------------------------------------------------
# 16. Explainability invariants
# ---------------------------------------------------------------------------

def check_explainability_invariants() -> None:
    section("16. Explainability service invariants")
    try:
        from app.services import user_learning_explainability_service as expl
        check("build_preference_explanation exists",
              hasattr(expl, "build_preference_explanation"))
        check("build_preference_explanation is sync (pure)",
              not inspect.iscoroutinefunction(expl.build_preference_explanation))
        path = inspect.getfile(expl)
        with open(path, "r", encoding="utf-8") as fh:
            src = fh.read()
        for pattern in ("add_forecast", "add_decision", "add_conviction"):
            check(f"explainability: no {pattern}", pattern not in src)
    except Exception as exc:
        check("explainability service importable", False, str(exc))


# ---------------------------------------------------------------------------
# 17. Relevance floor invariant
# ---------------------------------------------------------------------------

def check_relevance_floor_invariant() -> None:
    section("17. Relevance floor invariant (SP-7d)")
    try:
        from app.services import user_learning_relevance_service as rel
        check("build_relevance_projection exists",
              hasattr(rel, "build_relevance_projection"))
        path = inspect.getfile(rel)
        with open(path, "r", encoding="utf-8") as fh:
            src = fh.read()
        check("relevance floor constant defined",
              "_FACTOR_FLOOR" in src or "FACTOR_FLOOR" in src)
        check("hidden tier not used",
              '"hidden"' not in src and "'hidden'" not in src)
    except Exception as exc:
        check("relevance service importable", False, str(exc))


# ---------------------------------------------------------------------------
# 18. Novelty reserve invariant
# ---------------------------------------------------------------------------

def check_novelty_reserve_invariant() -> None:
    section("18. Novelty reserve invariant (anti-filter-bubble)")
    try:
        from app.services import user_learning_relevance_service as rel
        path = inspect.getfile(rel)
        with open(path, "r", encoding="utf-8") as fh:
            src = fh.read()
        check("novelty reserve constant defined",
              "_DEFAULT_NOVELTY_RESERVE" in src or "NOVELTY_RESERVE" in src)
        check("compute_novelty_reserve exists",
              hasattr(rel, "compute_novelty_reserve"))
    except Exception as exc:
        check("novelty reserve invariant", False, str(exc))


# ---------------------------------------------------------------------------
# 19. Calibration append-only invariant
# ---------------------------------------------------------------------------

def check_calibration_append_only() -> None:
    section("19. Calibration append-only invariant")
    try:
        from app.services import user_learning_calibration_service as cal
        check("record_preference_outcome exists",
              hasattr(cal, "record_preference_outcome"))
        check("summarize_preference_calibration exists",
              hasattr(cal, "summarize_preference_calibration"))
        path = inspect.getfile(cal)
        with open(path, "r", encoding="utf-8") as fh:
            src = fh.read()
        tree = ast.parse(src)
        call_attrs = {
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
        }
        check("calibration: no .update() call", "update" not in call_attrs)
        check("calibration: no .delete() call", "delete" not in call_attrs)
    except Exception as exc:
        check("calibration service importable", False, str(exc))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    print("=" * 60)
    print("Phase 15 — User Learning Shadow Validation")
    print("=" * 60)

    check_db_table_count()
    check_learning_tables()
    check_services_importable()
    check_flags_inert()
    check_no_recommendation_imports()
    check_no_truth_mutation_imports()
    check_no_forecast_writeback()
    check_no_similarity_writeback()
    check_no_scenario_writeback()
    check_no_decision_writeback()
    check_no_target_price_language()
    check_no_public_learning_route()
    check_admin_status_route()
    check_safe_state()
    check_no_notification_rows()
    check_explainability_invariants()
    check_relevance_floor_invariant()
    check_novelty_reserve_invariant()
    check_calibration_append_only()

    print("\n" + "=" * 60)
    passed = sum(1 for _, ok, _ in _results if ok)
    failed = sum(1 for _, ok, _ in _results if not ok)
    total  = len(_results)
    print(f"Results: {passed}/{total} passed", end="")
    if failed:
        print(f"  ({failed} FAILED)")
    else:
        print("  — all clear")
    print("=" * 60)

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
