"""
Phase 11 Similarity Engine Shadow Validation Script.

Verifies that the Phase 11 similarity subsystem (schema, builders, T4
scorer, invalidation, read service, delivery journaling, observability) is
correctly deployed and in safe shadow mode — no public exposure, no
forecasting/conviction coupling, no live notifications, all flags inert by
default.

Usage:
    python tests/validate_11_similarity_shadow.py          # local SQLite
    DATABASE_URL=<postgres_url> python tests/validate_11_similarity_shadow.py

Exit codes:
    0  — all checks passed
    1  — one or more checks failed

Checks:
    1.  db_table_count >= 40
    2.  similarity_feature_vector table exists
    3.  similarity_edge table exists
    4.  all similarity services importable
    5.  all 4 similarity flags default to their inert values
    6.  no forecast imports in any similarity_* / dossier_similarity_* module
    7.  no conviction/recommendation imports in those modules
    8.  no public (non-/admin) route path contains "similarity"
    9.  /admin/similarity-status and /admin/similarity/{ticker} are declared
    10. safe_state == True (DB-down and DB-up snapshot)
    11. no Notification rows with kind="similarity"
    12. any delivery_ledger rows for channel="similarity_shadow" never escalate
        to status="delivered" (shadow_escalated_count == 0)
    13. edge explainability invariant: every floor_passed edge has
        non-empty contributions and a non-empty disanalogy
    14. no source-table mutation during this validation probe
"""

from __future__ import annotations

import asyncio
import importlib
import inspect
import ast
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


_SIMILARITY_MODULES = [
    "app.db.repositories.similarity_repo",
    "app.services.similarity_feature_builder",
    "app.services.similarity_scorer",
    "app.services.similarity_invalidation_service",
    "app.services.similarity_read_service",
    "app.services.similarity_delivery_service",
    "app.services.dossier_similarity_enrichment",
    "app.services.similarity_observability_service",
]

_FORBIDDEN_IMPORT_TERMS = ["forecast", "conviction_engine", "recommendation", "notification_service"]


# ---------------------------------------------------------------------------
# Checks 1-3 — DB schema
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
        if count >= 40:
            _pass("db_table_count", f"found {count} tables (>= 40)")
        else:
            _fail("db_table_count", f"found {count} tables, expected >= 40")

        for table in ("similarity_feature_vector", "similarity_edge"):
            if table in tables:
                _pass(f"table_exists_{table}")
            else:
                _fail(f"table_exists_{table}", "missing")
    except Exception as exc:
        _fail("db_table_count", f"exception: {exc}")
        _fail("table_exists_similarity_feature_vector", "skipped due to DB error")
        _fail("table_exists_similarity_edge", "skipped due to DB error")


# ---------------------------------------------------------------------------
# Check 4 — service imports
# ---------------------------------------------------------------------------

def _check_service_imports():
    for module_path in _SIMILARITY_MODULES:
        try:
            importlib.import_module(module_path)
            _pass(f"import_{module_path.split('.')[-1]}")
        except Exception as exc:
            _fail(f"import_{module_path.split('.')[-1]}", str(exc))


# ---------------------------------------------------------------------------
# Check 5 — flags default inert
# ---------------------------------------------------------------------------

def _check_flags_inert():
    try:
        from app.config import settings

        expected = {
            "similarity_build_enabled": False,
            "similarity_scoring_enabled": False,
            "similarity_targets_enabled": "",
            "similarity_shadow": True,
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
# Checks 6-7 — import-graph hygiene (AST-based, not substring-in-docstring)
# ---------------------------------------------------------------------------

def _check_no_forbidden_imports():
    for module_path in _SIMILARITY_MODULES:
        try:
            mod = importlib.import_module(module_path)
            source = inspect.getsource(mod)
            tree = ast.parse(source)

            imported_names = []
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


# ---------------------------------------------------------------------------
# Checks 8-9 — route exposure (static source scan; app.api may not import
# cleanly on this Python version due to an unrelated pre-existing issue in
# router_service.py, so we scan the source text rather than import it)
# ---------------------------------------------------------------------------

def _extract_route_decorators(source: str):
    """Return list of (method, path) tuples for every @router.<verb>(...) call."""
    tree = ast.parse(source)
    routes = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if isinstance(node.func.value, ast.Name) and node.func.value.id == "router":
                method = node.func.attr  # get/post/put/delete/patch
                if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                    routes.append((method, node.args[0].value))
    return routes


def _check_route_exposure():
    api_path = os.path.join(_PROJECT_ROOT, "app", "api.py")
    try:
        with open(api_path, "r", encoding="utf-8") as f:
            source = f.read()
        routes = _extract_route_decorators(source)

        similarity_routes = [(m, p) for m, p in routes if "similarity" in p.lower()]
        non_admin = [(m, p) for m, p in similarity_routes if not p.startswith("/admin/")]
        if not non_admin:
            _pass("no_public_similarity_routes", f"{len(similarity_routes)} similarity route(s), all under /admin/")
        else:
            _fail("no_public_similarity_routes", f"non-admin similarity routes found: {non_admin}")

        expected_admin_routes = [("get", "/admin/similarity-status"), ("get", "/admin/similarity/{ticker}")]
        missing = [r for r in expected_admin_routes if r not in routes]
        if not missing:
            _pass("admin_similarity_routes_registered", f"{expected_admin_routes}")
        else:
            _fail("admin_similarity_routes_registered", f"missing: {missing}")
    except Exception as exc:
        _fail("route_exposure", f"exception: {exc}")


# ---------------------------------------------------------------------------
# Checks 10-13 — runtime snapshot + explainability invariant + no-write-back
# ---------------------------------------------------------------------------

async def _check_runtime():
    try:
        from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
        from sqlalchemy.orm import sessionmaker
        from app.db.models import Base, SimilarityEdge, Notification, DeliveryLedger
        from app.services.similarity_observability_service import build_similarity_observability_snapshot

        # safe_state with no DB at all
        snapshot_no_db = await build_similarity_observability_snapshot(None)
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

            before_edges = sorted(
                tuple(getattr(r, c.name) for c in SimilarityEdge.__table__.columns)
                for r in (await session.execute(select(SimilarityEdge))).scalars().all()
            )
            before_notifs = sorted(
                tuple(getattr(r, c.name) for c in Notification.__table__.columns)
                for r in (await session.execute(select(Notification))).scalars().all()
            )

            snapshot = await build_similarity_observability_snapshot(session)

            after_edges = sorted(
                tuple(getattr(r, c.name) for c in SimilarityEdge.__table__.columns)
                for r in (await session.execute(select(SimilarityEdge))).scalars().all()
            )
            after_notifs = sorted(
                tuple(getattr(r, c.name) for c in Notification.__table__.columns)
                for r in (await session.execute(select(Notification))).scalars().all()
            )

            if before_edges == after_edges and before_notifs == after_notifs:
                _pass("no_source_table_mutation", "similarity_edge and notifications unchanged by snapshot read")
            else:
                _fail("no_source_table_mutation", "snapshot call mutated a table it should only read")

            if snapshot.get("safe_state") is True:
                _pass("safe_state_db_up", "safe_state=True on a clean DB")
            else:
                _fail("safe_state_db_up", f"safe_state={snapshot.get('safe_state')!r}")

            live_notif_count = (
                await session.execute(
                    select(Notification).where(Notification.kind == "similarity")
                )
            ).scalars().all()
            if len(live_notif_count) == 0:
                _pass("no_similarity_notifications", "0 Notification rows with kind='similarity'")
            else:
                _fail("no_similarity_notifications", f"found {len(live_notif_count)}")

            shadow_rows = (
                await session.execute(
                    select(DeliveryLedger).where(DeliveryLedger.channel == "similarity_shadow")
                )
            ).scalars().all()
            escalated = [r for r in shadow_rows if r.status == "delivered"]
            if not escalated:
                _pass(
                    "shadow_delivery_channel_clean",
                    f"{len(shadow_rows)} similarity_shadow row(s), 0 escalated to delivered",
                )
            else:
                _fail("shadow_delivery_channel_clean", f"{len(escalated)} row(s) escalated to delivered")

            # Explainability invariant on whatever floor_passed edges exist
            floor_passed_edges = [r for r in (
                await session.execute(select(SimilarityEdge).where(SimilarityEdge.floor_passed.is_(True)))
            ).scalars().all()]
            orphans = [r for r in floor_passed_edges if not r.contributions or not r.disanalogy]
            if not orphans:
                _pass(
                    "edge_explainability_invariant",
                    f"{len(floor_passed_edges)} floor_passed edge(s), 0 missing contributions/disanalogy",
                )
            else:
                _fail("edge_explainability_invariant", f"{len(orphans)} orphan floor_passed edge(s) found")

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
    print("\n" + "═" * 65)
    print("  Phase 11 Similarity Engine Shadow Validation")
    print("═" * 65 + "\n")

    _check_service_imports()
    _check_flags_inert()
    _check_no_forbidden_imports()
    _check_route_exposure()

    asyncio.run(_run_async_checks())

    passed = sum(1 for r in _results if r["status"] == "PASS")
    failed = sum(1 for r in _results if r["status"] == "FAIL")

    print("\n" + "═" * 65)
    print(f"  Results: {passed} passed, {failed} failed")
    print("═" * 65 + "\n")

    if failed:
        print("FAILED checks:")
        for r in _results:
            if r["status"] == "FAIL":
                print(f"  - {r['check']}: {r['detail']}")
        print()
        return 1
    else:
        print("All checks passed. Phase 11 similarity shadow mode is correctly configured.\n")
        return 0


if __name__ == "__main__":
    sys.exit(main())
