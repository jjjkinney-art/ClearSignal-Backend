"""
Phase 12 Forecasting Engine Shadow Validation Script.

Verifies that the Phase 12 forecasting subsystem (schema, builders,
probability engine, explainability, invalidation, read service, shadow
delivery, calibration, observability) is correctly deployed and in safe
shadow mode — no public exposure, no conviction coupling, no live
notifications, all flags inert by default.

Usage:
    python tests/validate_12_forecasting_shadow.py          # local SQLite
    DATABASE_URL=<postgres_url> python tests/validate_12_forecasting_shadow.py

Exit codes:
    0  — all checks passed
    1  — one or more checks failed

Checks:
    1.  db_table_count >= 43
    2.  forecast_vector table exists
    3.  forecast_evidence table exists
    4.  forecast_calibration_log table exists
    5.  all Phase 12 forecast services importable
    6.  all 6 forecast flags at safe inert defaults
    7.  no recommendation/conviction imports in any forecast_* module (AST)
    8.  no buy/sell/hold/target-price string constants in service sources (AST)
    9.  no public (non-/admin) route path contains "forecast"
    10. /admin/forecast-status and /admin/forecast/{ticker} are declared
    11. safe_state == True (DB-down snapshot)
    12. safe_state == True (DB-up snapshot on clean DB)
    13. forecast_calibration_log immutable: add_calibration_log never updates
    14. no Notification rows with kind="forecast"
    15. no source-table mutation during this validation probe
    16. explanation invariants: every stored explanation has non-empty why + invalidators
    17. probability invariants: no vector has p_positive+p_negative+p_neutral outside [0.99, 1.01]
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

_FORECAST_MODULES = [
    "app.db.repositories.forecast_repo",
    "app.services.forecast_constants",
    "app.services.forecast_feature_builder",
    "app.services.forecast_probability_engine",
    "app.services.forecast_explainability_service",
    "app.services.forecast_invalidation_service",
    "app.services.forecast_read_service",
    "app.services.forecast_delivery_service",
    "app.services.forecast_calibration_service",
    "app.services.forecast_observability_service",
]

_FORBIDDEN_IMPORT_TERMS = [
    "conviction_engine",
    "recommendation",
    "notification_service",
    "stance_engine",
]

_FORBIDDEN_STRING_TERMS = ["buy", "sell", "hold", "target price", "overweight", "underweight"]


# ---------------------------------------------------------------------------
# Checks 1–4 — DB schema
# ---------------------------------------------------------------------------

async def _check_db_tables():
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
        if count >= 43:
            _pass("db_table_count", f"found {count} tables (>= 43)")
        else:
            _fail("db_table_count", f"found {count} tables, expected >= 43")

        for table in ("forecast_vector", "forecast_evidence", "forecast_calibration_log"):
            if table in tables:
                _pass(f"table_exists_{table}")
            else:
                _fail(f"table_exists_{table}", "missing")
    except Exception as exc:
        _fail("db_table_count", f"exception: {exc}")
        for t in ("forecast_vector", "forecast_evidence", "forecast_calibration_log"):
            _fail(f"table_exists_{t}", "skipped due to DB error")


# ---------------------------------------------------------------------------
# Check 5 — service imports
# ---------------------------------------------------------------------------

def _check_service_imports():
    for module_path in _FORECAST_MODULES:
        try:
            importlib.import_module(module_path)
            _pass(f"import_{module_path.split('.')[-1]}")
        except Exception as exc:
            _fail(f"import_{module_path.split('.')[-1]}", str(exc))


# ---------------------------------------------------------------------------
# Check 6 — flags default inert
# ---------------------------------------------------------------------------

def _check_flags_inert():
    try:
        from app.config import settings

        expected = {
            "forecast_build_enabled":      False,
            "forecast_scoring_enabled":    False,
            "forecast_delivery_enabled":   False,
            "forecast_shadow":             True,
            "forecast_targets_enabled":    "",
            "forecast_calibration_enabled": False,
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
# Checks 7–8 — import-graph + string hygiene (AST-based)
# ---------------------------------------------------------------------------

def _check_no_forbidden_imports():
    for module_path in _FORECAST_MODULES:
        try:
            mod = importlib.import_module(module_path)
            source = inspect.getsource(mod)
            tree = ast.parse(source)

            imported_names: list[str] = []
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
    """Return the string values of all module/function/class docstrings."""
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


# Modules excluded from the string scan because they legitimately contain
# banned-phrase vocabulary as enumerated DATA, not as output.
#   forecast_constants.py  — defines BANNED_ADVICE_PHRASES / MANDATORY_DISCLAIMER
#   forecast_repo.py       — infrastructure with no business-logic string constants
_STRING_CHECK_SKIP = frozenset({
    "app.db.repositories.forecast_repo",
    "app.services.forecast_constants",
})


def _check_no_recommendation_strings():
    for module_path in _FORECAST_MODULES:
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

            offenders = []
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and isinstance(node.value, str):
                    if node.value in docstring_values:
                        continue
                    val = node.value.lower()
                    for term in _FORBIDDEN_STRING_TERMS:
                        if term in val:
                            snippet = node.value[:60]
                            offenders.append(repr(term) + " in " + repr(snippet))
            if not offenders:
                _pass("no_recommendation_strings_" + module_path.split(".")[-1])
            else:
                _fail(
                    "no_recommendation_strings_" + module_path.split(".")[-1],
                    "found: " + repr(offenders[:3])
                )
        except Exception as exc:
            _fail("no_recommendation_strings_" + module_path.split(".")[-1], "exception: " + str(exc))


# ---------------------------------------------------------------------------
# Checks 9–10 — route exposure (static source scan)
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


def _check_route_exposure():
    api_path = os.path.join(_PROJECT_ROOT, "app", "api.py")
    try:
        with open(api_path, "r", encoding="utf-8") as f:
            source = f.read()
        routes = _extract_route_decorators(source)

        forecast_routes = [(m, p) for m, p in routes if "forecast" in p.lower()]
        non_admin = [(m, p) for m, p in forecast_routes if not p.startswith("/admin/")]
        if not non_admin:
            _pass(
                "no_public_forecast_routes",
                f"{len(forecast_routes)} forecast route(s), all under /admin/"
            )
        else:
            _fail("no_public_forecast_routes", f"non-admin forecast routes found: {non_admin}")

        expected_admin_routes = [
            ("get", "/admin/forecast-status"),
            ("get", "/admin/forecast/{ticker}"),
        ]
        missing = [r for r in expected_admin_routes if r not in routes]
        if not missing:
            _pass("admin_forecast_routes_registered", str(expected_admin_routes))
        else:
            _fail("admin_forecast_routes_registered", f"missing: {missing}")
    except Exception as exc:
        _fail("route_exposure", f"exception: {exc}")


# ---------------------------------------------------------------------------
# Check 13 — calibration_log immutability (AST on repo source)
# ---------------------------------------------------------------------------

def _check_calibration_log_immutable():
    repo_path = os.path.join(_PROJECT_ROOT, "app", "db", "repositories", "forecast_repo.py")
    try:
        with open(repo_path, "r", encoding="utf-8") as f:
            source = f.read()
        tree = ast.parse(source)

        for node in ast.walk(tree):
            if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)):
                if node.name == "add_calibration_log":
                    func_src = ast.unparse(node)
                    found_issues = []
                    if "session.merge(" in func_src:
                        found_issues.append("session.merge()")
                    if "session.delete(" in func_src:
                        found_issues.append("session.delete()")
                    # UPDATE statement check — must not have bulk update
                    if ".update(" in func_src and "stmt" in func_src:
                        found_issues.append("UPDATE statement")
                    if not found_issues:
                        _pass("calibration_log_immutable", "add_calibration_log has no UPDATE/DELETE/merge")
                    else:
                        _fail("calibration_log_immutable", f"found: {found_issues}")
                    return

        _fail("calibration_log_immutable", "add_calibration_log function not found in repo")
    except Exception as exc:
        _fail("calibration_log_immutable", f"exception: {exc}")


# ---------------------------------------------------------------------------
# Checks 11-17 — runtime snapshot + invariants + no-write-back
# ---------------------------------------------------------------------------

async def _check_runtime():
    try:
        from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
        from sqlalchemy.orm import sessionmaker
        from app.db.models import (
            Base, ForecastVector, ForecastEvidence,
            ForecastCalibrationLog, Notification, DeliveryLedger,
        )
        from app.services.forecast_observability_service import build_forecast_observability_snapshot

        # Check 11 — safe_state with no DB at all
        snapshot_no_db = await build_forecast_observability_snapshot(None)
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

            # Snapshot before
            before_vectors = (await session.execute(select(ForecastVector))).scalars().all()
            before_evidence = (await session.execute(select(ForecastEvidence))).scalars().all()
            before_notifs = (await session.execute(select(Notification))).scalars().all()
            before_calib = (await session.execute(select(ForecastCalibrationLog))).scalars().all()

            # Check 12 — safe_state with real DB
            snapshot = await build_forecast_observability_snapshot(session)
            if snapshot.get("safe_state") is True:
                _pass("safe_state_db_up", "safe_state=True on a clean DB")
            else:
                _fail("safe_state_db_up", f"safe_state={snapshot.get('safe_state')!r}")

            # Snapshot after — no source-table mutation (Check 15)
            after_vectors = (await session.execute(select(ForecastVector))).scalars().all()
            after_evidence = (await session.execute(select(ForecastEvidence))).scalars().all()
            after_notifs = (await session.execute(select(Notification))).scalars().all()
            after_calib = (await session.execute(select(ForecastCalibrationLog))).scalars().all()

            if (
                len(before_vectors) == len(after_vectors)
                and len(before_evidence) == len(after_evidence)
                and len(before_notifs) == len(after_notifs)
                and len(before_calib) == len(after_calib)
            ):
                _pass(
                    "no_source_table_mutation",
                    "forecast_vector, forecast_evidence, notifications, calibration_log unchanged by snapshot"
                )
            else:
                _fail("no_source_table_mutation", "snapshot call mutated a source table")

            # Check 14 — no Notification rows with kind="forecast"
            forecast_notifs = (
                await session.execute(
                    select(Notification).where(Notification.kind == "forecast")
                )
            ).scalars().all()
            if len(forecast_notifs) == 0:
                _pass("no_forecast_notifications", "0 Notification rows with kind='forecast'")
            else:
                _fail("no_forecast_notifications", f"found {len(forecast_notifs)}")

            # Check that shadow_escalated_count in snapshot is 0
            shadow_esc = snapshot.get("shadow_escalated_count", -1)
            if shadow_esc == 0:
                _pass("shadow_delivery_channel_clean", "shadow_escalated_count=0")
            else:
                _fail("shadow_delivery_channel_clean", f"shadow_escalated_count={shadow_esc}")

            # Check 16 — explanation invariants on stored forecast_vectors
            vectors = before_vectors  # same as after (no mutation)
            bad_explanations = [
                v for v in vectors
                if not (getattr(v, "why", None) or "").strip()
                or not (getattr(v, "invalidators", None) or [])
            ]
            _pass(
                "explanation_invariant",
                f"{len(vectors)} vector(s) checked, {len(bad_explanations)} with empty why/invalidators"
            ) if not bad_explanations else _fail(
                "explanation_invariant",
                f"{len(bad_explanations)} vector(s) have empty why or invalidators"
            )

            # Check 17 — probability invariants on stored vectors
            prob_violators = []
            for v in vectors:
                p_pos = float(getattr(v, "p_positive", 0) or 0)
                p_neg = float(getattr(v, "p_negative", 0) or 0)
                p_neu = float(getattr(v, "p_neutral", 0) or 0)
                total = p_pos + p_neg + p_neu
                if not (0.99 <= total <= 1.01):
                    prob_violators.append(f"{getattr(v, 'id', '?')[:8]}: sum={total:.4f}")
            if not prob_violators:
                _pass(
                    "probability_sum_invariant",
                    f"{len(vectors)} vector(s) checked, all p-sums in [0.99, 1.01]"
                )
            else:
                _fail("probability_sum_invariant", f"violators: {prob_violators[:3]}")

        await engine.dispose()
    except Exception as exc:
        _fail("runtime_checks", f"exception: {exc}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def _run_async_checks():
    await _check_db_tables()
    await _check_runtime()


def main() -> int:
    print("\n" + "=" * 65)
    print("  Phase 12 Forecasting Engine Shadow Validation")
    print("=" * 65 + "\n")

    _check_service_imports()
    _check_flags_inert()
    _check_no_forbidden_imports()
    _check_no_recommendation_strings()
    _check_route_exposure()
    _check_calibration_log_immutable()

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
    else:
        print(
            "All checks passed. "
            "Phase 12 forecasting shadow mode is correctly configured.\n"
        )
        return 0


if __name__ == "__main__":
    sys.exit(main())
