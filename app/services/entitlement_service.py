"""
Entitlement Service — Phase 17 · Slice 2.

Resolves the effective access tier for a user and returns an EntitlementSet.
No Stripe SDK.  No enforcement.  No checkout.  No webhooks.
This slice computes entitlements only — nothing consumes them yet.

Resolution chain (per spec §3.2):
    cache check
        ↓ miss
    subscriptions query (get_active_subscription)
        ↓ not found
    free fallback

Special bypass:
    SYSTEM_DEFAULT_USER_ID always resolves to unlimited tier (no DB query).

Failure-open contract:
    Any exception in resolution returns the free-tier EntitlementSet rather
    than propagating.  Callers should never crash due to entitlement failures.

Null-session safety:
    All primary functions return the free EntitlementSet (or None for
    get_cached_entitlements) when session is None.

STRIPE_ENABLED is not consulted here — the entitlement layer is deliberately
decoupled from the Stripe flag.  It reads the subscriptions table that was
written by Stripe webhooks (Slice 4).  With no webhooks yet, every user has
no subscription row and resolves to free.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, asdict
from datetime import datetime, timezone, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SYSTEM_DEFAULT_USER_ID = "00000000-0000-0000-0000-000000000001"
ENTITLEMENT_CACHE_TTL_S = 3600  # 1 hour

# plan_name → tier name (for display and EntitlementSet.tier_name)
_TIER_NAMES = {
    "free":          "Spark",
    "pro":           "Signal",
    "teams":         "Syndicate",
    "institutional": "Edge",
    "system":        "System",
}


# ---------------------------------------------------------------------------
# § EntitlementSet
# ---------------------------------------------------------------------------

@dataclass
class EntitlementSet:
    """Resolved access rights for one user at one point in time.

    All callers receive this object.  No external mutations after construction.

    Limits:
        -1 = unlimited
         0 = blocked / no access
        >0 = the hard cap

    plan_status values:
        "active"        — paid subscription in good standing
        "trialing"      — within trial window (Signal-level access)
        "grace"         — payment failed but within grace period (retains access)
        "free_fallback" — no active subscription (or expired / lapsed)
        "system"        — system user, always unlimited
    """

    user_id:              str
    tier_name:            str   # Spark | Signal | Syndicate | Edge | System
    plan_name:            str   # free | pro | teams | institutional | system
    plan_status:          str   # active | trialing | grace | free_fallback | system

    trial_days_remaining: Optional[int]   # None when not trialing
    show_upgrade_cta:     bool

    # Resource limits (-1 = unlimited)
    watchlist_limit:       int   # 5 / -1 / -1 / -1
    portfolio_limit:       int   # 1 / 5 / -1 / -1
    position_limit:        int   # 10 / -1 / -1 / -1
    dossier_monthly_limit: int   # 3 / -1 / -1 / -1
    briefing_limit:        int   # max briefings / week: 1 / -1 / -1 / -1
    delivery_limit:        int   # max delivery channels: 1 / 2 / 3 / 3

    # Feature flags
    can_use_portfolio_intelligence: bool
    can_use_email_delivery:         bool
    can_use_push_delivery:          bool
    can_set_briefing_time:          bool
    can_use_custom_quiet_hours:     bool
    can_export_data:                bool
    can_use_api:                    bool
    can_use_org_features:           bool
    has_unlimited_inbox:            bool

    computed_at:      str   # ISO-8601 UTC
    cache_expires_at: str   # ISO-8601 UTC


# ---------------------------------------------------------------------------
# § Tier definitions
# ---------------------------------------------------------------------------

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _build_entitlement_set(
    user_id: str,
    plan_name: str,
    plan_status: str,
    trial_days_remaining: Optional[int] = None,
) -> EntitlementSet:
    """Construct an EntitlementSet from a resolved plan name and status."""
    now = _now()
    expires_at = now + timedelta(seconds=ENTITLEMENT_CACHE_TTL_S)

    tier_name = _TIER_NAMES.get(plan_name, "Spark")

    # Limits and flags keyed by plan_name
    if plan_name == "system":
        return EntitlementSet(
            user_id=user_id,
            tier_name="System",
            plan_name="system",
            plan_status="system",
            trial_days_remaining=None,
            show_upgrade_cta=False,
            watchlist_limit=-1,
            portfolio_limit=-1,
            position_limit=-1,
            dossier_monthly_limit=-1,
            briefing_limit=-1,
            delivery_limit=-1,
            can_use_portfolio_intelligence=True,
            can_use_email_delivery=True,
            can_use_push_delivery=True,
            can_set_briefing_time=True,
            can_use_custom_quiet_hours=True,
            can_export_data=True,
            can_use_api=True,
            can_use_org_features=True,
            has_unlimited_inbox=True,
            computed_at=now.isoformat(),
            cache_expires_at=expires_at.isoformat(),
        )

    if plan_name in ("pro",):
        # Signal — full individual toolkit
        return EntitlementSet(
            user_id=user_id,
            tier_name=tier_name,
            plan_name=plan_name,
            plan_status=plan_status,
            trial_days_remaining=trial_days_remaining,
            show_upgrade_cta=(plan_status == "trialing"),
            watchlist_limit=-1,
            portfolio_limit=5,
            position_limit=-1,
            dossier_monthly_limit=-1,
            briefing_limit=-1,
            delivery_limit=2,
            can_use_portfolio_intelligence=True,
            can_use_email_delivery=True,
            can_use_push_delivery=False,
            can_set_briefing_time=True,
            can_use_custom_quiet_hours=True,
            can_export_data=True,
            can_use_api=False,
            can_use_org_features=False,
            has_unlimited_inbox=True,
            computed_at=now.isoformat(),
            cache_expires_at=expires_at.isoformat(),
        )

    if plan_name == "teams":
        # Syndicate — small funds / clubs
        return EntitlementSet(
            user_id=user_id,
            tier_name=tier_name,
            plan_name=plan_name,
            plan_status=plan_status,
            trial_days_remaining=None,
            show_upgrade_cta=False,
            watchlist_limit=-1,
            portfolio_limit=-1,
            position_limit=-1,
            dossier_monthly_limit=-1,
            briefing_limit=-1,
            delivery_limit=3,
            can_use_portfolio_intelligence=True,
            can_use_email_delivery=True,
            can_use_push_delivery=True,
            can_set_briefing_time=True,
            can_use_custom_quiet_hours=True,
            can_export_data=True,
            can_use_api=True,
            can_use_org_features=True,
            has_unlimited_inbox=True,
            computed_at=now.isoformat(),
            cache_expires_at=expires_at.isoformat(),
        )

    if plan_name == "institutional":
        # Edge — RIAs, hedge funds, family offices
        return EntitlementSet(
            user_id=user_id,
            tier_name=tier_name,
            plan_name=plan_name,
            plan_status=plan_status,
            trial_days_remaining=None,
            show_upgrade_cta=False,
            watchlist_limit=-1,
            portfolio_limit=-1,
            position_limit=-1,
            dossier_monthly_limit=-1,
            briefing_limit=-1,
            delivery_limit=3,
            can_use_portfolio_intelligence=True,
            can_use_email_delivery=True,
            can_use_push_delivery=True,
            can_set_briefing_time=True,
            can_use_custom_quiet_hours=True,
            can_export_data=True,
            can_use_api=True,
            can_use_org_features=True,
            has_unlimited_inbox=True,
            computed_at=now.isoformat(),
            cache_expires_at=expires_at.isoformat(),
        )

    # Default: Spark (free) — also the fallback for any unknown plan_name.
    return EntitlementSet(
        user_id=user_id,
        tier_name="Spark",
        plan_name="free",
        plan_status=plan_status,
        trial_days_remaining=None,
        show_upgrade_cta=True,
        watchlist_limit=5,
        portfolio_limit=1,
        position_limit=10,
        dossier_monthly_limit=3,
        briefing_limit=1,
        delivery_limit=1,
        can_use_portfolio_intelligence=False,
        can_use_email_delivery=False,
        can_use_push_delivery=False,
        can_set_briefing_time=False,
        can_use_custom_quiet_hours=False,
        can_export_data=False,
        can_use_api=False,
        can_use_org_features=False,
        has_unlimited_inbox=False,
        computed_at=now.isoformat(),
        cache_expires_at=expires_at.isoformat(),
    )


def _free_fallback(user_id: str) -> EntitlementSet:
    return _build_entitlement_set(user_id, "free", "free_fallback")


def _system_entitlements(user_id: str) -> EntitlementSet:
    return _build_entitlement_set(user_id, "system", "system")


# ---------------------------------------------------------------------------
# § Cache serialisation helpers
# ---------------------------------------------------------------------------

_FEATURE_FLAGS = [
    "can_use_portfolio_intelligence",
    "can_use_email_delivery",
    "can_use_push_delivery",
    "can_set_briefing_time",
    "can_use_custom_quiet_hours",
    "can_export_data",
    "can_use_api",
    "can_use_org_features",
    "has_unlimited_inbox",
    "show_upgrade_cta",
]

_EXTRA_LIMITS = ["briefing_limit", "delivery_limit"]


def _entitlement_set_to_cache_row(ent: EntitlementSet) -> dict:
    """Convert an EntitlementSet to the column values needed for upsert_entitlement_cache."""
    features: dict = {f: getattr(ent, f) for f in _FEATURE_FLAGS}
    for lim in _EXTRA_LIMITS:
        features[lim] = getattr(ent, lim)
    features["tier_name"] = ent.tier_name
    features["cache_expires_at"] = ent.cache_expires_at

    return {
        "plan_name":             ent.plan_name,
        "plan_status":           ent.plan_status,
        "watchlist_limit":       ent.watchlist_limit,
        "portfolio_limit":       ent.portfolio_limit,
        "position_limit":        ent.position_limit,
        "dossier_monthly_limit": ent.dossier_monthly_limit,
        "features_json":         json.dumps(features),
        "trial_days_remaining":  ent.trial_days_remaining,
        "expires_at":            _now() + timedelta(seconds=ENTITLEMENT_CACHE_TTL_S),
    }


def _cache_row_to_entitlement_set(user_id: str, row) -> Optional[EntitlementSet]:
    """Reconstruct an EntitlementSet from an EntitlementCache ORM row.

    Returns None if the row is missing or the data is malformed.
    """
    try:
        features = json.loads(row.features_json or "{}")

        def _bool(key: str, default: bool = False) -> bool:
            return bool(features.get(key, default))

        def _int(key: str, default: int = 0) -> int:
            val = features.get(key)
            return int(val) if val is not None else default

        tier_name = features.get("tier_name") or _TIER_NAMES.get(row.plan_name, "Spark")
        cache_expires_at = features.get("cache_expires_at") or row.expires_at.isoformat()

        return EntitlementSet(
            user_id=user_id,
            tier_name=tier_name,
            plan_name=row.plan_name,
            plan_status=row.plan_status,
            trial_days_remaining=row.trial_days_remaining,
            show_upgrade_cta=_bool("show_upgrade_cta"),
            watchlist_limit=row.watchlist_limit,
            portfolio_limit=row.portfolio_limit,
            position_limit=row.position_limit,
            dossier_monthly_limit=row.dossier_monthly_limit,
            briefing_limit=_int("briefing_limit", 1),
            delivery_limit=_int("delivery_limit", 1),
            can_use_portfolio_intelligence=_bool("can_use_portfolio_intelligence"),
            can_use_email_delivery=_bool("can_use_email_delivery"),
            can_use_push_delivery=_bool("can_use_push_delivery"),
            can_set_briefing_time=_bool("can_set_briefing_time"),
            can_use_custom_quiet_hours=_bool("can_use_custom_quiet_hours"),
            can_export_data=_bool("can_export_data"),
            can_use_api=_bool("can_use_api"),
            can_use_org_features=_bool("can_use_org_features"),
            has_unlimited_inbox=_bool("has_unlimited_inbox"),
            computed_at=row.computed_at.isoformat() if row.computed_at else _now().isoformat(),
            cache_expires_at=cache_expires_at,
        )
    except Exception as exc:
        logger.debug("[entitlement] cache deserialise failed (non-fatal): %r", exc)
        return None


# ---------------------------------------------------------------------------
# § Subscription → plan resolution
# ---------------------------------------------------------------------------

def _resolve_plan_from_subscription(sub) -> tuple[str, str, Optional[int]]:
    """Inspect an active subscription ORM row and return (plan_name, plan_status, trial_days_remaining).

    Grace period rules (spec §3.2):
        past_due + grace_period_ends_at > now  →  keeps subscription access, status="grace"
        past_due + grace_period_ends_at <= now →  free fallback, status="free_fallback"
        trialing  + trial_ends_at > now        →  pro access,  status="trialing"
        trialing  + trial_ends_at <= now       →  free fallback (Stripe should have fired; local fallback)
        active                                 →  use plan_name, status="active"
    """
    now = _now()
    status = (sub.status or "").lower()

    if status == "past_due":
        grace = sub.grace_period_ends_at
        if grace and _tz_aware(grace) > now:
            return sub.plan_name, "grace", None
        return "free", "free_fallback", None

    if status == "trialing":
        trial_end = sub.trial_ends_at
        if trial_end and _tz_aware(trial_end) > now:
            days_left = max(0, (_tz_aware(trial_end) - now).days)
            return "pro", "trialing", days_left
        # Expired trial — Stripe webhook should have fired; apply local fallback.
        return "free", "free_fallback", None

    if status in ("active", "paused"):
        return sub.plan_name, "active", None

    # Any other non-terminal status → free fallback.
    return "free", "free_fallback", None


def _tz_aware(dt: datetime) -> datetime:
    """Ensure a datetime is timezone-aware (assume UTC if naive)."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


# ---------------------------------------------------------------------------
# § Public API
# ---------------------------------------------------------------------------

async def get_cached_entitlements(session, user_id: str) -> Optional[EntitlementSet]:
    """Return a valid cached EntitlementSet, or None on miss/expiry/error.

    Does NOT fall back to the subscription table.  Use resolve_entitlements()
    for the full resolution chain.
    """
    if session is None or not user_id:
        return None
    try:
        from app.db.repositories.billing_repo import get_entitlement_cache

        row = await get_entitlement_cache(session, user_id)
        if row is None:
            return None

        # Stale check: expires_at must be in the future.
        expires = _tz_aware(row.expires_at) if row.expires_at else None
        if expires is None or expires <= _now():
            return None

        return _cache_row_to_entitlement_set(user_id, row)
    except Exception as exc:
        logger.debug("[entitlement] get_cached_entitlements failed (non-fatal): %r", exc)
        return None


async def resolve_entitlements(session, user_id: str) -> EntitlementSet:
    """Resolve entitlements for user_id via the full chain.

    Resolution order:
        1. System user bypass (no DB query)
        2. Cache hit (valid, unexpired)
        3. Active subscription lookup
        4. Free fallback

    On any exception, returns the free EntitlementSet.
    Never raises.
    """
    # 1. System user — always unlimited, skip all DB work.
    if user_id == SYSTEM_DEFAULT_USER_ID:
        return _system_entitlements(user_id)

    if session is None or not user_id:
        return _free_fallback(user_id or "")

    try:
        # 2. Cache check.
        cached = await get_cached_entitlements(session, user_id)
        if cached is not None:
            logger.debug("[entitlement] cache hit for %s (plan=%s)", user_id[:8], cached.plan_name)
            return cached

        # 3. Subscription lookup.
        from app.db.repositories.billing_repo import (
            get_active_subscription,
            upsert_entitlement_cache,
        )

        sub = await get_active_subscription(session, user_id)
        if sub is not None:
            plan_name, plan_status, trial_days = _resolve_plan_from_subscription(sub)
        else:
            plan_name, plan_status, trial_days = "free", "free_fallback", None

        ent = _build_entitlement_set(user_id, plan_name, plan_status, trial_days)

        # 4. Write to cache (non-fatal on failure).
        try:
            cache_row = _entitlement_set_to_cache_row(ent)
            await upsert_entitlement_cache(
                session,
                user_id,
                **cache_row,
            )
        except Exception as cache_exc:
            logger.debug("[entitlement] cache write failed (non-fatal): %r", cache_exc)

        logger.debug(
            "[entitlement] resolved %s → plan=%s status=%s",
            user_id[:8], plan_name, plan_status,
        )
        return ent

    except Exception as exc:
        logger.warning("[entitlement] resolve_entitlements failed (fail-open): %r", exc)
        return _free_fallback(user_id)


async def refresh_entitlements(session, user_id: str) -> EntitlementSet:
    """Force-invalidate the cache and re-resolve from the subscription table.

    Used by webhook handlers (Slice 4) after subscription state changes.
    Never raises.
    """
    if user_id == SYSTEM_DEFAULT_USER_ID:
        return _system_entitlements(user_id)

    if session is None or not user_id:
        return _free_fallback(user_id or "")

    try:
        from app.db.repositories.billing_repo import invalidate_entitlement_cache

        await invalidate_entitlement_cache(session, user_id)
        logger.debug("[entitlement] cache invalidated for %s", user_id[:8])
    except Exception as exc:
        logger.debug("[entitlement] cache invalidation failed (non-fatal): %r", exc)

    # Re-resolve without cache (cache was just deleted).
    return await resolve_entitlements(session, user_id)


async def resolve_plan(session, user_id: str) -> str:
    """Return only the plan name string for user_id.

    Convenience wrapper for callers that need the plan name without the
    full EntitlementSet overhead.  Falls back to "free" on any error.
    """
    ent = await resolve_entitlements(session, user_id)
    return ent.plan_name
