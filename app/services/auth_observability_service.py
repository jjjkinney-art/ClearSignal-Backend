"""
Auth Observability Service — Phase 16 · Slice 8.

Builds a point-in-time snapshot of auth / identity readiness without exposing
any credentials or secrets.  All DB queries degrade safely to zero-counts on
failure — the snapshot is always returned even when the database is unavailable.

Public API
----------
  build_auth_snapshot(session) → AuthSnapshot
  snapshot_to_dict(snapshot)   → Dict[str, Any]   (JSON-serialisable)

Safe-state definition
---------------------
  safe_state = True when ALL of:
    1. auth_enabled = False  (bypass mode; no JWT enforcement risk)
    2. system_user_present   (seed row exists; ownership claims land correctly)
    3. null_rows_count == 0  (no orphan rows; all content has an owner)
    4. db_available          (DB is reachable; counts are accurate)

Secret exposure policy
----------------------
  NEVER expose: supabase_jwt_secret, supabase_project_url, auth_bypass_user_id
  values.  Only boolean presence flags are returned.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

SYSTEM_DEFAULT_USER_ID: str = "00000000-0000-0000-0000-000000000001"

# Core user-content tables checked for ownership health.
# Excludes analysis/dossier tables (system-owned by design) and tables
# that inherit ownership via FK (portfolio_positions, portfolio_insights).
_OWNERSHIP_TABLES = (
    "watched_tickers",
    "portfolios",
    "user_delivery_prefs",
    "digest_batches",
)


# ---------------------------------------------------------------------------
# Snapshot dataclass
# ---------------------------------------------------------------------------

@dataclass
class AuthSnapshot:
    """Point-in-time auth + identity readiness snapshot."""

    # -- Config flags (no secret values) --
    auth_enabled:                 bool
    auth_bypass:                  bool        # True when auth_enabled=False
    jwt_verification_enabled:     bool        # True only when auth_enabled AND a secret/URL is configured
    supabase_project_configured:  bool        # project URL present (not the URL itself)
    supabase_secret_configured:   bool        # JWT secret present (not the secret itself)

    # -- DB availability --
    db_available:                 bool

    # -- Identity / user state --
    system_user_present:          bool
    user_count:                   int         # all users including system
    real_user_count:              int         # account_type != 'system'
    profile_count:                int
    settings_count:               int

    # -- Onboarding --
    onboarding_by_step:           Dict[str, int]
    imported_users_count:         int         # users with import_run audit entry

    # -- Data ownership health --
    claimed_rows_count:           int         # user_id = SYSTEM_DEFAULT_USER_ID (core tables)
    null_rows_count:              int         # user_id IS NULL (should be 0 post-claim)

    # -- Route / middleware presence --
    auth_routes_registered:       bool
    auth_middleware_present:      bool

    # -- Safe-state verdict --
    safe_state:                   bool
    safe_state_reasons:           List[str]   # one line per factor; prefix PASS/FAIL

    # -- Meta --
    generated_at:                 str         # ISO-8601 UTC


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _bool_present(value: str) -> bool:
    return bool(value and value.strip())


async def _count_users(session) -> tuple:
    """Return (total_count, real_count).  Raises on DB error (caller handles)."""
    from app.db.models import User
    from sqlalchemy import select, func

    result = await session.execute(
        select(User.account_type, func.count(User.id).label("n"))
        .group_by(User.account_type)
    )
    by_type: Dict[str, int] = {row.account_type: row.n for row in result.all()}
    total = sum(by_type.values())
    system_count = by_type.get("system", 0)
    return total, total - system_count


async def _check_system_user(session) -> bool:
    """Return True if the system user row exists.  Raises on DB error (caller handles)."""
    from app.db.models import User
    from sqlalchemy import select

    result = await session.execute(
        select(User.id).where(User.id == SYSTEM_DEFAULT_USER_ID).limit(1)
    )
    return result.scalar_one_or_none() is not None


async def _count_profiles_settings(session) -> tuple:
    """Return (profile_count, settings_count).  Raises on DB error (caller handles)."""
    from app.db.models import UserProfile, UserSettings
    from sqlalchemy import select, func

    p_result = await session.execute(select(func.count(UserProfile.user_id)))
    s_result = await session.execute(select(func.count(UserSettings.user_id)))
    return (p_result.scalar_one() or 0), (s_result.scalar_one() or 0)


async def _onboarding_by_step(session) -> Dict[str, int]:
    """Return step → count map.  Raises on DB error (caller handles)."""
    from app.db.models import UserProfile
    from sqlalchemy import select, func

    result = await session.execute(
        select(UserProfile.onboarding_step, func.count(UserProfile.user_id).label("n"))
        .group_by(UserProfile.onboarding_step)
    )
    return {row.onboarding_step: row.n for row in result.all()}


async def _count_imported_users(session) -> int:
    """Return number of distinct users with an import_run audit entry.  Raises on DB error."""
    from app.db.models import AuditLog
    from sqlalchemy import select, func, distinct

    result = await session.execute(
        select(func.count(distinct(AuditLog.user_id)))
        .where(AuditLog.action == "import")
        .where(AuditLog.resource == "import_run")
    )
    return result.scalar_one() or 0


async def _ownership_counts(session) -> tuple:
    """Return (claimed_count, null_count) across _OWNERSHIP_TABLES.  Raises on DB error."""
    claimed = 0
    null_ct = 0
    from sqlalchemy import text

    for table in _OWNERSHIP_TABLES:
        r1 = await session.execute(
            text(f"SELECT COUNT(*) FROM {table} WHERE user_id = :uid"),
            {"uid": SYSTEM_DEFAULT_USER_ID},
        )
        claimed += (r1.scalar_one() or 0)

        r2 = await session.execute(
            text(f"SELECT COUNT(*) FROM {table} WHERE user_id IS NULL")
        )
        null_ct += (r2.scalar_one() or 0)

    return claimed, null_ct


def _check_auth_routes() -> bool:
    try:
        from app.routers.auth import router as _r  # noqa: F401
        return True
    except Exception:
        return False


def _check_auth_middleware() -> bool:
    try:
        from app.middleware.auth_middleware import AuthMiddleware  # noqa: F401
        return True
    except Exception:
        return False


def _compute_safe_state(snap: dict) -> tuple:
    """Return (safe_state: bool, reasons: List[str])."""
    reasons: List[str] = []
    safe = True

    if not snap["auth_bypass"]:
        reasons.append("FAIL  auth_enabled=true — enforcement active; not in shadow mode")
        safe = False
    else:
        reasons.append("PASS  auth_bypass=true — JWT enforcement not active")

    if snap["system_user_present"]:
        reasons.append("PASS  system_user_present — ownership anchor exists")
    else:
        reasons.append("FAIL  system_user_present=false — seed row missing; run Slice 2 startup")
        safe = False

    if snap["null_rows_count"] == 0:
        reasons.append("PASS  null_rows_count=0 — all core-table rows have an owner")
    else:
        reasons.append(
            f"FAIL  null_rows_count={snap['null_rows_count']} — "
            "orphan rows present; run claim_null_ownership"
        )
        safe = False

    if snap["db_available"]:
        reasons.append("PASS  db_available — database reachable")
    else:
        reasons.append("FAIL  db_available=false — snapshot counts may be stale")
        safe = False

    return safe, reasons


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def build_auth_snapshot(session) -> AuthSnapshot:
    """Build and return an AuthSnapshot.

    All DB queries are wrapped in try/except; failures set db_available=False
    and zero-out the affected counters rather than propagating exceptions.
    Never returns credentials, secret values, or internal UUIDs.
    """
    from app.config import settings

    auth_enabled = bool(settings.auth_enabled)
    supabase_project_configured = _bool_present(getattr(settings, "supabase_project_url", ""))
    supabase_secret_configured  = _bool_present(getattr(settings, "supabase_jwt_secret", ""))
    jwt_verification_enabled    = auth_enabled and (
        supabase_project_configured or supabase_secret_configured
    )

    db_available = session is not None
    system_user_present = False
    user_count = 0
    real_user_count = 0
    profile_count = 0
    settings_count = 0
    onboarding = {}
    imported_count = 0
    claimed = 0
    null_ct = 0

    if session is not None:
        try:
            system_user_present = await _check_system_user(session)
            user_count, real_user_count = await _count_users(session)
            profile_count, settings_count = await _count_profiles_settings(session)
            onboarding = await _onboarding_by_step(session)
            imported_count = await _count_imported_users(session)
            claimed, null_ct = await _ownership_counts(session)
        except Exception as exc:
            logger.warning("[obs] build_auth_snapshot DB queries failed: %r", exc)
            db_available = False

    auth_routes = _check_auth_routes()
    auth_middleware = _check_auth_middleware()

    # Compute safe_state using the raw values (before wrapping in dataclass).
    raw = {
        "auth_bypass": not auth_enabled,
        "system_user_present": system_user_present,
        "null_rows_count": null_ct,
        "db_available": db_available,
    }
    safe_state, reasons = _compute_safe_state(raw)

    return AuthSnapshot(
        auth_enabled=auth_enabled,
        auth_bypass=not auth_enabled,
        jwt_verification_enabled=jwt_verification_enabled,
        supabase_project_configured=supabase_project_configured,
        supabase_secret_configured=supabase_secret_configured,
        db_available=db_available,
        system_user_present=system_user_present,
        user_count=user_count,
        real_user_count=real_user_count,
        profile_count=profile_count,
        settings_count=settings_count,
        onboarding_by_step=onboarding,
        imported_users_count=imported_count,
        claimed_rows_count=claimed,
        null_rows_count=null_ct,
        auth_routes_registered=auth_routes,
        auth_middleware_present=auth_middleware,
        safe_state=safe_state,
        safe_state_reasons=reasons,
        generated_at=_now_iso(),
    )


def snapshot_to_dict(snap: AuthSnapshot) -> Dict[str, Any]:
    """Convert AuthSnapshot to a JSON-serialisable dict.

    Never includes secret values.  Omits internal UUID constants.
    """
    return {
        "auth_enabled":                snap.auth_enabled,
        "auth_bypass":                 snap.auth_bypass,
        "jwt_verification_enabled":    snap.jwt_verification_enabled,
        "supabase_project_configured": snap.supabase_project_configured,
        "supabase_secret_configured":  snap.supabase_secret_configured,
        "db_available":                snap.db_available,
        "system_user_present":         snap.system_user_present,
        "user_count":                  snap.user_count,
        "real_user_count":             snap.real_user_count,
        "profile_count":               snap.profile_count,
        "settings_count":              snap.settings_count,
        "onboarding_by_step":          snap.onboarding_by_step,
        "imported_users_count":        snap.imported_users_count,
        "claimed_rows_count":          snap.claimed_rows_count,
        "null_rows_count":             snap.null_rows_count,
        "auth_routes_registered":      snap.auth_routes_registered,
        "auth_middleware_present":     snap.auth_middleware_present,
        "safe_state":                  snap.safe_state,
        "safe_state_reasons":          snap.safe_state_reasons,
        "generated_at":                snap.generated_at,
    }
