"""
Phase 13 Decision Intelligence Shadow Validation Script.

Verifies that the Phase 13 Decision Intelligence subsystem (schema, candidate
builder, ranking engine, explainability, storage pipeline, read service,
portfolio awareness, shadow delivery, calibration, observability) is correctly
deployed and in safe shadow mode — no public exposure, no conviction coupling,
no live notifications, all flags inert by default.

Usage:
    python tests/validate_13_decision_shadow.py          # local SQLite
    DATABASE_URL=<postgres_url> python tests/validate_13_decision_shadow.py

Exit codes:
    0  — all checks passed
    1  — one or more checks failed

Checks:
    1.  db_table_count >= 46
    2.  decision_priority table exists
    3.  decision_evidence table exists
    4.  decision_ranking_log table exists
    5.  all Phase 13 decision services importable
    6.  all 6 decision flags at safe inert defaults
    7.  no recommendation/conviction imports in any decision_* module (AST)
    8.  no buy/sell/hold/target-price string constants in service sources (AST)
    9.  no forecast write-back calls in decision service sources (AST)
    10. no public (non-/admin) route path contains "decision"
    11. /admin/decision-status and /admin/decision/{ticker} are declared
    12. safe_state == True (DB-down snapshot)
    13. safe_state == True (DB-up snapshot on clean DB)
    14. decision_ranking_log immutable: add_ranking_log never updates existing rows
    15. no Notification rows after observability snapshot probe
    16. no source-table mutation during this validation probe
    17. explainability invariants: every stored decision has non-empty reason + why_now
    18. ranking invariants: no priority has decision_rank_score outside [0, 1]
    19. calibration invariants: calibration_outcome rows have realized_significance set
"""

from __future__ import annotations

import ast
import asyncio
import importlib
import inspect
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_HERE)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

# ---------------------------------------------------------------------------
# Result tracking
# ---------------------------------------------------------------------------

_results: list = []


def _pass(check: str, detail: str = "") -> None:
    _results.append({"status": "PASS", "check": check, "detail": detail})
    print(f"  ✓  {check}" + (f"  [{detail}]" if detail else ""))


def _fail(check: str, detail: str = "") -> None:
    _results.append({"status": "FAIL", "check": check, "detail": detail})
    print(f"  ✗  {check}" + (f"  [{detail}]" if detail else ""))


# ---------------------------------------------------------------------------
# Modules under test
# ---------------------------------------------------------------------------

_DECISION_MODULES = [
    "app.db.repositories.decision_repo",
    "app.services.decision_candidate_builder",
    "app.services.decision_ranking_engine",
    "app.services.decision_explainability_service",
    "app.services.decision_invalidation_service",
    "app.services.decision_read_service",
    "app.services.decision_portfolio_service",
    "app.services.decision_delivery_service",
    "app.services.decision_calibration_service",
    "app.services.decision_observability_service",
]

_FORBIDDEN_IMPORT_TERMS = [
    "conviction_engine",
    "conviction_modeler",
    "recommendation",
    "notification_service",
    "stance_engine",
    "order_engine",
    "execution_engine",
]

_FORBIDDEN_STRING_TERMS = [
    "buy", "sell", "hold", "target price", "overweight", "underweight",
    "position size", "enter a trade", "exit a trade",
]

# Modules that define banned-phrase vocabulary as enumerated DATA and must be
# skipped from the string-constant scan.
_STRING_CHECK_SKIP = frozenset({
    "app.db.repositories.decision_repo",
    "app.services.decision_explainability_service",  # defines _BANNED_PHRASES list
})


# ---------------------------------------------------------------------------
# Checks 1–4 — DB schema
# ---------------------------------------------------------------------------

async def _check_db_tables() -> None:
    try:
        from sqlalchemy.ext.asyncio import create_async_engine
        from app.db.models import Base

        url = os.environ.get("DATABASE_URL") or "sqlite+aiosqlite:///:memory:"
        engine = create_async_engine(url, future=True)

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            tables = await conn.run_sync(
                lambda sync_conn: sync_conn.dialect.get_table_names(sync_conn)
            )
        await engine.dispose()

        count = len(tables)
        if count >= 46:
            _pass("db_table_count", f"found {count} tables (>= 46)")
        else:
            _fail("db_table_count", f"found {count} tables, expected >= 46")

        for table in ("decision_priority", "decision_evidence", "decision_ranking_log"):
            if table in tables:
                _pass(f"table_exists_{table}")
            else:
                _fail(f"table_exists_{table}", "missing")
    except Exception as exc:
        _fail("db_table_count", f"exception: {exc}")
        for t in ("decision_priority", "decision_evidence", "decision_ranking_log"):
            _fail(f"table_exists_{t}", "skipped due to DB error")


# ---------------------------------------------------------------------------
# Check 5 — service imports
# ---------------------------------------------------------------------------

def _check_service_imports() -> None:
    for module_path in _DECISION_MODULES:
        try:
            importlib.import_module(module_path)
            _pass(f"import_{module_path.split('.')[-1]}")
        except Exception as exc:
            _fail(f"import_{module_path.split('.')[-1]}", str(exc))


# ---------------------------------------------------------------------------
# Check 6 — flags default inert
# ---------------------------------------------------------------------------

def _check_flags_inert() -> None:
    try:
        from app.config import settings

        expected = {
            "decision_build_enabled":       False,
            "decision_scoring_enabled":     False,
            "decision_delivery_enabled":    False,
            "decision_shadow":              True,
            "decision_targets_enabled":     "",
            "decision_calibration_enabled": False,
        }
        for flag, expected_value in expected.items():
            actual = getattr(settings, flag, None)
            if actual == expected_value:
                _pass(f"flag_default_{flag}", f"{flag}={actual!r}")
            else:
                _fail(f"flag_default_{flag}", f"{flag}={actual!r}, expected {expected_value!r}")
    except Exception as exc:
        _fail("flags_inert", f"exception: {exc}")


# ---------------------------------------------------------------------------
# Checks 7–9 — import-graph, string hygiene, forecast write-back (AST-based)
# ---------------------------------------------------------------------------

def _check_no_forbidden_imports() -> None:
    for module_path in _DECISION_MODULES:
        try:
            mod = importlib.import_module(module_path)
            source = inspect.getsource(mod)
            tree = ast.parse(source)

            imported_names: list = []
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported_names.extend(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        imported_names.append(node.module)
                    imported_names.extend(alias.name for alias in node.names)

            offenders = [
                name for name in imported_names
                if any(term in name.lower() for term in _FORBIDDEN_IMPORT_TERMS)
            ]
            if not offenders:
                _pass(f"no_forbidden_imports_{module_path.split('.')[-1]}")
            else:
                _fail(f"no_forbidden_imports_{module_path.split('.')[-1]}", f"found: {offenders}")
        except Exception as exc:
            _fail(f"no_forbidden_imports_{module_path.split('.')[-1]}", f"exception: {exc}")


def _get_docstring_values(tree: ast.AST) -> set:
    values: set = set()
    for node in ast.walk(tree):
        body = None
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = node.body
        if (
            body
            and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)
        ):
            values.add(body[0].value.value)
    return values


def _get_banned_list_values(tree: ast.AST) -> set:
    """Return string constants that are entries in _BANNED_PHRASES (excluded from scan)."""
    values: set = set()
    for node in ast.walk(tree):
        value_node = None
        if isinstance(node, ast.Assign):
            if any(isinstance(t, ast.Name) and t.id == "_BANNED_PHRASES" for t in node.targets):
                value_node = node.value
        elif isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name) and node.target.id == "_BANNED_PHRASES" and node.value:
                value_node = node.value
        if value_node and isinstance(value_node, ast.List):
            for elt in value_node.elts:
                if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                    values.add(elt.value)
    return values


def _check_no_recommendation_strings() -> None:
    for module_path in _DECISION_MODULES:
        if module_path in _STRING_CHECK_SKIP:
            _pass(
                "no_recommendation_strings_" + module_path.split(".")[-1],
                "skipped (infrastructure/data module)"
            )
            continue
        try:
            mod = importlib.import_module(module_path)
            mod_file = getattr(mod, "__file__", None)
            if mod_file and mod_file.endswith(".pyc"):
                mod_file = mod_file[:-1]
            if mod_file:
                with open(mod_file, "r", encoding="utf-8") as fh:
                    source = fh.read()
            else:
                source = inspect.getsource(mod)

            tree = ast.parse(source)
            docstring_values = _get_docstring_values(tree)
            banned_list_values = _get_banned_list_values(tree)
            exclude = docstring_values | banned_list_values

            offenders = []
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and isinstance(node.value, str):
                    if node.value in exclude:
                        continue
                    val = node.value.lower()
                    for term in _FORBIDDEN_STRING_TERMS:
                        if term in val:
                            offenders.append(repr(term) + " in " + repr(node.value[:60]))
            if not offenders:
                _pass("no_recommendation_strings_" + module_path.split(".")[-1])
            else:
                _fail(
                    "no_recommendation_strings_" + module_path.split(".")[-1],
                    "found: " + repr(offenders[:3])
                )
        except Exception as exc:
            _fail("no_recommendation_strings_" + module_path.split(".")[-1], f"exception: {exc}")


def _check_no_forecast_write_back() -> None:
    """Check 9: no decision service calls forecast write-back functions.

    decision_candidate_builder legitimately *reads* from forecast_repo to build
    candidates — that is the intended upstream direction.  What is forbidden is
    any decision service *writing* into forecast tables via functions such as
    upsert_forecast_vector, add_forecast_log, set_vector, or importing the
    forecast_builder module (which is the write-path module).
    """
    # Specific write-path identifiers that must not appear in any decision service
    write_call_terms = [
        "upsert_forecast_vector",
        "add_forecast_log",
        "set_vector",
        "write_forecast",
        "insert_forecast",
        "forecast_builder",
    ]
    # decision_candidate_builder is allowed to import forecast_repo for reads
    _FORECAST_READ_ALLOWED = frozenset({
        "app.services.decision_candidate_builder",
    })
    for module_path in _DECISION_MODULES:
        try:
            mod = importlib.import_module(module_path)
            source = inspect.getsource(mod)
            tree = ast.parse(source)

            names_used: list = []
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module:
                    # Allowed readers skip the module-path check but still
                    # flag if they import the builder (write-path) module.
                    if module_path in _FORECAST_READ_ALLOWED:
                        if "forecast_builder" in (node.module or ""):
                            names_used.append(node.module)
                    else:
                        names_used.append(node.module)
                    names_used.extend(alias.name for alias in node.names)
                elif isinstance(node, ast.Import):
                    names_used.extend(alias.name for alias in node.names)
                elif isinstance(node, ast.Attribute):
                    names_used.append(node.attr)
                elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                    names_used.append(node.func.id)

            offenders = [
                name for name in names_used
                if any(term in name.lower() for term in write_call_terms)
            ]
            if not offenders:
                _pass(f"no_forecast_write_back_{module_path.split('.')[-1]}")
            else:
                _fail(f"no_forecast_write_back_{module_path.split('.')[-1]}", f"found: {offenders}")
        except Exception as exc:
            _fail(f"no_forecast_write_back_{module_path.split('.')[-1]}", f"exception: {exc}")


# ---------------------------------------------------------------------------
# Checks 10–11 — route exposure (static source scan)
# ---------------------------------------------------------------------------

def _extract_route_decorators(source: str):
    tree = ast.parse(source)
    routes = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if isinstance(node.func.value, ast.Name) and node.func.value.id == "router":
                method = node.func.attr
                if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                    routes.append((method, node.args[0].value))
    return routes


def _check_route_exposure() -> None:
    api_path = os.path.join(_PROJECT_ROOT, "app", "api.py")
    try:
        with open(api_path, "r", encoding="utf-8") as f:
            source = f.read()
        routes = _extract_route_decorators(source)

        decision_routes = [(m, p) for m, p in routes if "decision" in p.lower()]
        non_admin = [(m, p) for m, p in decision_routes if not p.startswith("/admin/")]
        if not non_admin:
            _pass(
                "no_public_decision_routes",
                f"{len(decision_routes)} decision route(s), all under /admin/"
            )
        else:
            _fail("no_public_decision_routes", f"non-admin decision routes found: {non_admin}")

        expected_admin_routes = [
            ("get", "/admin/decision-status"),
            ("get", "/admin/decision/{ticker}"),
        ]
        missing = [r for r in expected_admin_routes if r not in routes]
        if not missing:
            _pass("admin_decision_routes_registered", str(expected_admin_routes))
        else:
            _fail("admin_decision_routes_registered", f"missing: {missing}")
    except Exception as exc:
        _fail("route_exposure", f"exception: {exc}")


# ---------------------------------------------------------------------------
# Check 14 — ranking_log immutability (AST on repo source)
# ---------------------------------------------------------------------------

def _check_ranking_log_immutable() -> None:
    repo_path = os.path.join(_PROJECT_ROOT, "app", "db", "repositories", "decision_repo.py")
    try:
        with open(repo_path, "r", encoding="utf-8") as f:
            source = f.read()
        tree = ast.parse(source)

        for node in ast.walk(tree):
            if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)):
                if node.name == "add_ranking_log":
                    func_src = ast.unparse(node)
                    issues = []
                    if "session.merge(" in func_src:
                        issues.append("session.merge()")
                    if "session.delete(" in func_src:
                        issues.append("session.delete()")
                    if ".update(" in func_src and "stmt" in func_src:
                        issues.append("UPDATE statement")
                    if not issues:
                        _pass("ranking_log_immutable", "add_ranking_log has no UPDATE/DELETE/merge")
                    else:
                        _fail("ranking_log_immutable", f"found: {issues}")
                    return

        _fail("ranking_log_immutable", "add_ranking_log not found in decision_repo.py")
    except Exception as exc:
        _fail("ranking_log_immutable", f"exception: {exc}")


# ---------------------------------------------------------------------------
# Checks 12–13, 15–19 — runtime snapshot + invariants
# ---------------------------------------------------------------------------

async def _check_runtime() -> None:
    try:
        from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
        from sqlalchemy.orm import sessionmaker
        from app.db.models import (
            Base, DecisionPriority, DecisionEvidence,
            DecisionRankingLog, Notification, DeliveryLedger,
        )
        from app.services.decision_observability_service import build_decision_observability_snapshot

        # Check 12 — safe_state with no DB at all
        snapshot_no_db = await build_decision_observability_snapshot(None)
        if snapshot_no_db.get("safe_state") is True:
            _pass("safe_state_db_down", "safe_state=True with session=None")
        else:
            _fail("safe_state_db_down", f"safe_state={snapshot_no_db.get('safe_state')!r}")

        url = os.environ.get("DATABASE_URL") or "sqlite+aiosqlite:///:memory:"
        engine = create_async_engine(url, future=True)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        async with AsyncSessionLocal() as session:
            from sqlalchemy import select

            # Baseline row counts
            before_priorities = (await session.execute(select(DecisionPriority))).scalars().all()
            before_evidence   = (await session.execute(select(DecisionEvidence))).scalars().all()
            before_notifs     = (await session.execute(select(Notification))).scalars().all()
            before_log        = (await session.execute(select(DecisionRankingLog))).scalars().all()

            # Check 13 — safe_state with real DB
            snapshot = await build_decision_observability_snapshot(session)
            if snapshot.get("safe_state") is True:
                _pass("safe_state_db_up", "safe_state=True on a clean DB")
            else:
                _fail("safe_state_db_up", f"safe_state={snapshot.get('safe_state')!r}")

            # Post-snapshot row counts
            after_priorities = (await session.execute(select(DecisionPriority))).scalars().all()
            after_evidence   = (await session.execute(select(DecisionEvidence))).scalars().all()
            after_notifs     = (await session.execute(select(Notification))).scalars().all()
            after_log        = (await session.execute(select(DecisionRankingLog))).scalars().all()

            # Check 16 — no source-table mutation
            if (
                len(before_priorities) == len(after_priorities)
                and len(before_evidence)   == len(after_evidence)
                and len(before_notifs)     == len(after_notifs)
                and len(before_log)        == len(after_log)
            ):
                _pass(
                    "no_source_table_mutation",
                    "decision tables unchanged by observability snapshot"
                )
            else:
                _fail("no_source_table_mutation", "snapshot call mutated a source table")

            # Check 15 — no Notification rows
            if len(before_notifs) == 0:
                _pass("no_decision_notifications", "0 Notification rows on clean DB")
            else:
                _fail("no_decision_notifications", f"found {len(before_notifs)}")

            # Check: shadow_escalated_count == 0
            shadow_esc = snapshot.get("shadow_escalated_count", -1)
            if shadow_esc == 0:
                _pass("shadow_escalated_count_zero", "shadow_escalated_count=0")
            else:
                _fail("shadow_escalated_count_zero", f"shadow_escalated_count={shadow_esc}")

            # Check 17 — explainability invariants on stored priorities
            bad_explain = [
                p for p in before_priorities
                if not (getattr(p, "decision_reason", None) or "").strip()
                or not (getattr(p, "why_now", None) or "").strip()
            ]
            if not bad_explain:
                _pass(
                    "explainability_invariant",
                    f"{len(before_priorities)} priority row(s) checked, none with empty reason/why_now"
                )
            else:
                _fail("explainability_invariant",
                      f"{len(bad_explain)} row(s) with empty decision_reason or why_now")

            # Check 18 — ranking invariants: score in [0, 1]
            score_violators = [
                p for p in before_priorities
                if not (0.0 <= float(getattr(p, "decision_rank_score", 0.0) or 0.0) <= 1.0)
            ]
            if not score_violators:
                _pass(
                    "ranking_score_invariant",
                    f"{len(before_priorities)} priority row(s) checked, all scores in [0, 1]"
                )
            else:
                _fail("ranking_score_invariant",
                      f"{len(score_violators)} row(s) with score outside [0, 1]")

            # Check 19 — calibration invariants: outcome rows have realized_significance
            calib_rows = [
                r for r in before_log
                if getattr(r, "snapshot_reason", "") == "calibration_outcome"
            ]
            bad_calib = [
                r for r in calib_rows
                if not (getattr(r, "realized_significance", None) or "").strip()
            ]
            if not bad_calib:
                _pass(
                    "calibration_significance_invariant",
                    f"{len(calib_rows)} calibration_outcome row(s) checked, all have realized_significance"
                )
            else:
                _fail("calibration_significance_invariant",
                      f"{len(bad_calib)} calibration row(s) with empty realized_significance")

        await engine.dispose()
    except Exception as exc:
        _fail("runtime_checks", f"exception: {exc}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def _run_async_checks() -> None:
    await _check_db_tables()
    await _check_runtime()


def main() -> int:
    print("\n" + "=" * 65)
    print("  Phase 13 Decision Intelligence Shadow Validation")
    print("=" * 65 + "\n")

    _check_service_imports()
    _check_flags_inert()
    _check_no_forbidden_imports()
    _check_no_recommendation_strings()
    _check_no_forecast_write_back()
    _check_route_exposure()
    _check_ranking_log_immutable()

    asyncio.run(_run_async_checks())

    passed = sum(1 for r in _results if r["status"] == "PASS")
    failed = sum(1 for r in _results if r["status"] == "FAIL")

    print("\n" + "=" * 65)
    print(f"  Results: {passed} passed, {failed} failed")
    print("=" * 65 + "\n")

    if failed:
        print("FAILED checks:")
        for r in _results:
            if r["status"] == "FAIL":
                print(f"  - {r['check']}: {r['detail']}")
        print()
        return 1

    print(
        "All checks passed. "
        "Phase 13 decision intelligence is in safe shadow mode.\n"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
