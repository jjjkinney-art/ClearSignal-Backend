"""
Billing Observability Service — Phase 17 · Slice 7.

Produces a single consistent, null-safe, DB-down-safe snapshot of the
Phase 17 billing subsystem.  Intended callers:

  - GET /admin/billing-status        (production admin endpoint)
  - tests/validate_17_billing_shadow.py  (deployment validation script)
  - integration tests

Design principles (mirrors delivery_observability_service.py)
--------------------------------------------------------------
  - Never raises.  All DB calls wrapped in try/except; degraded to 0/null.
  - No secrets.  STRIPE_SECRET_KEY, webhook secret, JWT — never appear.
  - Fast.  Lightweight aggregate queries only; no full-table scans.
  - Deterministic schema.  All keys always present; missing data → 0/null/{}.

Snapshot structure
------------------
  billing_flags      — stripe_enabled, entitlements_enforced from settings
  subscriptions      — total count, breakdown by status
  stripe_events      — total, by processing_status, error count
  entitlement_cache  — row count, indicates cache population
  billing_routes     — which /billing/* routes are registered
  safe_state         — True when stripe_enabled=False OR shadow conditions met
  db_available       — False if DB was unreachable this call
  snapshot_utc       — ISO-8601 timestamp
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _safe_int(val: Any, default: int = 0) -> int:
    try:
        return int(val)
    except Exception:
        return default


def _safe_bool(val: Any, default: bool = False) -> bool:
    try:
        return bool(val)
    except Exception:
        return default


def _safe_str(val: Any, default: str = "") -> str:
    try:
        return str(val) if val is not None else default
    except Exception:
        return default


# ---------------------------------------------------------------------------
# Config section — billing flags only; no secret values
# ---------------------------------------------------------------------------

def _billing_flags_section() -> Dict[str, Any]:
    try:
        from app.config import settings as _s
        flags = {
            "stripe_enabled":          _safe_bool(_s.stripe_enabled),
            "entitlements_enforced":   _safe_bool(_s.entitlements_enforced),
            "stripe_secret_key_set":   bool(_s.stripe_secret_key),
            "stripe_signal_monthly_price_set": bool(_s.stripe_price_signal_monthly),
            "stripe_signal_yearly_price_set": bool(_s.stripe_price_signal_yearly),
            "stripe_syndicate_monthly_price_set": bool(_s.stripe_price_syndicate_monthly),
            "stripe_success_url_set":  bool(_s.stripe_success_url),
            "stripe_cancel_url_set":   bool(_s.stripe_cancel_url),
            "stripe_webhook_secret_set": bool(_s.stripe_webhook_secret),
            "stripe_portal_return_url_set": bool(_s.stripe_portal_return_url),
        }
        flags["stripe_config_ready"] = all(
            flags[key]
            for key in (
                "stripe_secret_key_set",
                "stripe_signal_monthly_price_set",
                "stripe_signal_yearly_price_set",
                "stripe_syndicate_monthly_price_set",
                "stripe_success_url_set",
                "stripe_cancel_url_set",
                "stripe_webhook_secret_set",
                "stripe_portal_return_url_set",
            )
        )
        return flags
    except Exception as exc:
        logger.debug("[billing_obs] flags section failed: %r", exc)
        return {
            "stripe_enabled":              False,
            "entitlements_enforced":       False,
            "stripe_secret_key_set":       False,
            "stripe_signal_monthly_price_set": False,
            "stripe_signal_yearly_price_set": False,
            "stripe_syndicate_monthly_price_set": False,
            "stripe_success_url_set":      False,
            "stripe_cancel_url_set":       False,
            "stripe_webhook_secret_set":   False,
            "stripe_portal_return_url_set": False,
            "stripe_config_ready":         False,
        }


# ---------------------------------------------------------------------------
# DB sections — each degrades independently
# ---------------------------------------------------------------------------

async def _subscriptions_section(session) -> Dict[str, Any]:
    base: Dict[str, Any] = {
        "total":       0,
        "by_status":   {},
        "active_count":    0,
        "trialing_count":  0,
        "grace_count":     0,
        "canceled_count":  0,
    }
    if session is None:
        return base
    try:
        from app.db.repositories.billing_repo import count_subscriptions_by_status
        by_status = await count_subscriptions_by_status(session)
        total = sum(by_status.values())
        base["by_status"]     = dict(by_status)
        base["total"]         = total
        base["active_count"]  = _safe_int(by_status.get("active", 0))
        base["trialing_count"] = _safe_int(by_status.get("trialing", 0))
        base["grace_count"]   = _safe_int(by_status.get("past_due", 0))
        base["canceled_count"] = _safe_int(by_status.get("canceled", 0))
    except Exception as exc:
        logger.debug("[billing_obs] subscriptions section failed: %r", exc)
    return base


async def _stripe_events_section(session) -> Dict[str, Any]:
    base: Dict[str, Any] = {
        "total":             0,
        "by_status":         {},
        "processed_count":   0,
        "skipped_count":     0,
        "error_count":       0,
        "pending_count":     0,
    }
    if session is None:
        return base
    try:
        from app.db.models import StripeEvent
        from sqlalchemy import select, func

        result = await session.execute(
            select(
                StripeEvent.processing_status,
                func.count(StripeEvent.id).label("n"),
            ).group_by(StripeEvent.processing_status)
        )
        by_status: Dict[str, int] = {}
        for row in result.all():
            by_status[row.processing_status] = int(row.n)

        total = sum(by_status.values())
        base["total"]           = total
        base["by_status"]       = dict(by_status)
        base["processed_count"] = _safe_int(by_status.get("ok", 0))
        base["skipped_count"]   = _safe_int(by_status.get("skipped", 0))
        base["error_count"]     = _safe_int(by_status.get("error", 0))
        base["pending_count"]   = _safe_int(by_status.get("pending", 0))
    except Exception as exc:
        logger.debug("[billing_obs] stripe_events section failed: %r", exc)
    return base


async def _entitlement_cache_section(session) -> Dict[str, Any]:
    base: Dict[str, Any] = {"total": 0}
    if session is None:
        return base
    try:
        from app.db.models import EntitlementCache
        from sqlalchemy import select, func

        result = await session.execute(
            select(func.count(EntitlementCache.user_id))
        )
        base["total"] = _safe_int(result.scalar_one())
    except Exception as exc:
        logger.debug("[billing_obs] entitlement_cache section failed: %r", exc)
    return base


# ---------------------------------------------------------------------------
# Routes section — which billing endpoints are registered
# ---------------------------------------------------------------------------

def _billing_routes_section() -> Dict[str, bool]:
    routes = {
        "checkout": False,
        "webhook":  False,
        "status":   False,
        "portal":   False,
        "cancel":   False,
    }
    try:
        from app.routers.billing import router as _billing_router
        paths = {r.path for r in _billing_router.routes}
        routes["checkout"] = "/billing/checkout" in paths
        routes["webhook"]  = "/billing/webhook"  in paths
        routes["status"]   = "/billing/status"   in paths
        routes["portal"]   = "/billing/portal"   in paths
        routes["cancel"]   = "/billing/cancel"   in paths
    except Exception as exc:
        logger.debug("[billing_obs] routes section failed: %r", exc)
    return routes


# ---------------------------------------------------------------------------
# Safe-state computation
# ---------------------------------------------------------------------------

def _compute_safe_state(flags: Dict[str, Any]) -> bool:
    """safe_state = True when the system cannot accidentally charge or gate users.

    Conditions that make it safe:
      - stripe_enabled=False  (no Stripe calls possible)
      - entitlements_enforced=False  (no users blocked)
    """
    stripe_off        = not _safe_bool(flags.get("stripe_enabled"))
    enforcement_off   = not _safe_bool(flags.get("entitlements_enforced"))
    return stripe_off and enforcement_off


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def build_billing_snapshot(session) -> Dict[str, Any]:
    """Build and return the full billing observability snapshot.

    Never raises.  Session may be None (all DB sections degrade to 0).
    """
    db_available = session is not None

    flags         = _billing_flags_section()
    subscriptions = await _subscriptions_section(session)
    stripe_events = await _stripe_events_section(session)
    ent_cache     = await _entitlement_cache_section(session)
    routes        = _billing_routes_section()
    safe_state    = _compute_safe_state(flags)

    return {
        "billing_flags": flags,
        "subscriptions": subscriptions,
        "stripe_events": stripe_events,
        "entitlement_cache": ent_cache,
        "billing_routes": routes,
        # Top-level convenience aliases for quick validation
        "stripe_enabled":          flags["stripe_enabled"],
        "stripe_config_ready":     _safe_bool(flags.get("stripe_config_ready")),
        "entitlements_enforced":   flags["entitlements_enforced"],
        "subscription_count":      subscriptions["total"],
        "subscriptions_by_status": subscriptions["by_status"],
        "entitlement_cache_count": ent_cache["total"],
        "stripe_event_count":      stripe_events["total"],
        "processed_webhooks":      stripe_events["processed_count"],
        "skipped_webhooks":        stripe_events["skipped_count"],
        "billing_routes_present":  all(routes.values()),
        "safe_state":              safe_state,
        "db_available":            db_available,
        "snapshot_utc":            _now_iso(),
    }
