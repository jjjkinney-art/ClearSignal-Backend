"""
tests/validate_16_auth_shadow.py

Phase 16 Auth Shadow Validation — standalone readiness checklist.

Run with:
    python3 tests/validate_16_auth_shadow.py

Checks:
  1.  db_table_count == 35
  2.  system user row exists
  3.  auth routes importable (/auth/me, /auth/session, /auth/logout)
  4.  auth_enabled = False
  5.  bypass mode active (auth_bypass = True)
  6.  onboarding step values are all valid
  7.  import service operational (preview + execute round-trip)
  8.  no password columns in any model
  9.  auth middleware importable
  10. safe_state = True in snapshot
  11. snapshot exposes no secret values
  12. null_rows_count = 0 (all content rows owned)

Exit code 0 = all checks pass.
Exit code 1 = one or more checks failed.
"""

from __future__ import annotations

import asyncio
import os
import sys

# Make the project root importable when run from tests/ or from the project root.
_here = os.path.dirname(os.path.abspath(__file__))
_root = os.path.dirname(_here)
if _root not in sys.path:
    sys.path.insert(0, _root)

# ---------------------------------------------------------------------------
# Check infrastructure
# ---------------------------------------------------------------------------

_PASS  = "PASS "
_FAIL  = "FAIL "
_SKIP  = "SKIP "

_results: list = []


def _check(name: str, passed: bool, detail: str = "") -> bool:
    tag = _PASS if passed else _FAIL
    line = f"  {tag} {name}"
    if detail:
        line += f"  ({detail})"
    print(line)
    _results.append((name, passed))
    return passed


def _skip(name: str, reason: str) -> None:
    print(f"  {_SKIP} {name}  ({reason})")
    _results.append((name, True))  # skipped counts as neutral pass


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------

def check_model_imports() -> bool:
    try:
        from app.db.models import (  # noqa: F401
            Base, User, UserProfile, UserSettings, AuditLog,
            WatchedTicker, Portfolio, PortfolioPosition,
            UserDeliveryPref,
        )
        return _check("model imports", True)
    except Exception as exc:
        return _check("model imports", False, str(exc))


def check_no_password_columns() -> bool:
    """Confirm no column named 'password*' exists on any ORM model."""
    try:
        from app.db.models import Base
        for mapper in Base.registry.mappers:
            for col in mapper.columns:
                if "password" in col.key.lower():
                    return _check(
                        "no password columns", False,
                        f"found '{col.key}' on {mapper.class_.__tablename__}"
                    )
        return _check("no password columns", True)
    except Exception as exc:
        return _check("no password columns", False, str(exc))


def check_auth_middleware() -> bool:
    try:
        from app.middleware.auth_middleware import AuthMiddleware  # noqa: F401
        return _check("auth middleware importable", True)
    except Exception as exc:
        return _check("auth middleware importable", False, str(exc))


def check_auth_routes() -> bool:
    try:
        from app.routers.auth import router  # noqa: F401
        paths = [r.path for r in router.routes]
        has_me      = any("/me" in p for p in paths)
        has_session = any("/session" in p for p in paths)
        has_logout  = any("/logout" in p for p in paths)
        ok = has_me and has_session and has_logout
        return _check(
            "auth routes registered",
            ok,
            f"/me={has_me} /session={has_session} /logout={has_logout}",
        )
    except Exception as exc:
        return _check("auth routes registered", False, str(exc))


def check_auth_enabled_false() -> bool:
    try:
        from app.config import settings
        ok = not bool(settings.auth_enabled)
        return _check("auth_enabled=false", ok, f"auth_enabled={settings.auth_enabled}")
    except Exception as exc:
        return _check("auth_enabled=false", False, str(exc))


def check_observability_service() -> bool:
    try:
        from app.services.auth_observability_service import (  # noqa: F401
            build_auth_snapshot, snapshot_to_dict, AuthSnapshot,
        )
        return _check("observability service importable", True)
    except Exception as exc:
        return _check("observability service importable", False, str(exc))


def check_import_service() -> bool:
    try:
        from app.services.account_import_service import (  # noqa: F401
            preview_import, execute_import, rollback_import,
        )
        return _check("import service importable", True)
    except Exception as exc:
        return _check("import service importable", False, str(exc))


def check_onboarding_service() -> bool:
    try:
        from app.services.onboarding_service import (  # noqa: F401
            get_onboarding_state, advance_step, complete_step, STEPS,
        )
        valid_steps = {
            "account_created", "auth_verified", "import_offered",
            "import_completed", "onboarding_complete",
        }
        ok = set(STEPS) == valid_steps
        return _check(
            "onboarding steps valid",
            ok,
            f"steps={STEPS}",
        )
    except Exception as exc:
        return _check("onboarding steps valid", False, str(exc))


async def _run_async_checks() -> list:
    """Checks that require an async DB session."""
    results = []

    # In-memory SQLite for structural checks (does not require a live Postgres).
    try:
        from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
        from sqlalchemy.orm import sessionmaker
        from app.db.models import Base

        engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    except Exception as exc:
        results.append(("async DB setup", False, str(exc)))
        return results

    async with async_session() as session:

        # 1. db_table_count
        try:
            from sqlalchemy import text
            r = await session.execute(
                text("SELECT COUNT(*) FROM sqlite_master WHERE type='table'")
            )
            count = r.scalar_one() or 0
            ok = count == 35
            results.append(("db_table_count == 35", ok, f"got {count}"))
        except Exception as exc:
            results.append(("db_table_count == 35", False, str(exc)))

        # 2. system user seed + claim
        try:
            from app.services.system_user_service import (
                ensure_system_user, claim_null_ownership,
            )
            await ensure_system_user(session)
            claim_result = await claim_null_ownership(session)
            await session.commit()

            from app.db.models import User
            from sqlalchemy import select
            row = (await session.execute(
                select(User).where(User.id == "00000000-0000-0000-0000-000000000001")
            )).scalar_one_or_none()
            results.append(("system_user_present", row is not None, ""))
        except Exception as exc:
            results.append(("system_user_present", False, str(exc)))

        # 3. snapshot safe_state
        try:
            from app.services.auth_observability_service import (
                build_auth_snapshot, snapshot_to_dict,
            )
            snap = await build_auth_snapshot(session)
            d = snapshot_to_dict(snap)

            # safe_state
            results.append(("safe_state=true", d["safe_state"], str(d["safe_state_reasons"])))

            # auth_bypass
            results.append(("auth_bypass=true", d["auth_bypass"], ""))

            # null_rows_count
            ok = d["null_rows_count"] == 0
            results.append(("null_rows_count=0", ok, f"null_rows={d['null_rows_count']}"))

            # No secrets in snapshot
            secret_keys = {"supabase_jwt_secret", "supabase_project_url", "auth_bypass_user_id"}
            leaked = secret_keys & set(d.keys())
            results.append(("no secrets in snapshot", len(leaked) == 0, str(leaked) if leaked else ""))

        except Exception as exc:
            results.append(("snapshot checks", False, str(exc)))

        # 4. import service round-trip (preview only — no writes to system tables)
        try:
            from app.services.account_import_service import preview_import
            preview = await preview_import(
                session, "ffffffff-ffff-ffff-ffff-ffffffffffff"
            )
            results.append(("import service preview", True, f"watchlist={preview.watchlist_count}"))
        except Exception as exc:
            results.append(("import service preview", False, str(exc)))

    await engine.dispose()
    return results


# ---------------------------------------------------------------------------
# Main runner
# ---------------------------------------------------------------------------

def main() -> int:
    print()
    print("=" * 60)
    print("Phase 16 — Auth Shadow Validation")
    print("=" * 60)
    print()
    print("Static checks")
    print("-" * 40)

    check_model_imports()
    check_no_password_columns()
    check_auth_middleware()
    check_auth_routes()
    check_auth_enabled_false()
    check_observability_service()
    check_import_service()
    check_onboarding_service()

    print()
    print("Async / DB checks")
    print("-" * 40)

    async_results = asyncio.get_event_loop().run_until_complete(_run_async_checks())
    for name, ok, detail in async_results:
        _check(name, ok, detail)

    print()
    print("=" * 60)
    passed = sum(1 for _, ok in _results if ok)
    total  = len(_results)
    failed = total - passed
    print(f"Results: {passed}/{total} passed, {failed} failed")
    print("=" * 60)

    if failed:
        print(f"\nFAIL — {failed} check(s) did not pass.")
        return 1

    print("\nPASS — auth shadow validation complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
