"""
Phase 17 · Slice 2 — Entitlement service tests.

Validates:
  1.  Free fallback — no subscription row → Spark tier
  2.  Cache hit — valid cache row returned without subscription query
  3.  Subscription hit — active subscription → correct plan
  4.  System user — always unlimited, no DB query required
  5.  Expired subscription — past_due + grace expired → free fallback
  6.  Grace period state — past_due + grace active → retains access
  7.  Cache refresh — force-invalidates and re-resolves
  8.  Null-session safety — all functions return safe defaults on None session
  9.  Trialing → pro access with trial_days_remaining set
  10. Expired trial → free fallback
  11. EntitlementSet fields — correct limits and flags per tier
  12. resolve_plan — convenience wrapper returns correct plan name string
  13. Cache round-trip — serialise → write → read → deserialise → same values
  14. Teams tier — correct unlimited + push + org flags
  15. Institutional tier — all flags enabled
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from datetime import datetime, timezone, timedelta
from typing import Optional


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _future(days: int = 0, hours: int = 0) -> datetime:
    return _now() + timedelta(days=days, hours=hours)


def _past(days: int = 0, hours: int = 0) -> datetime:
    return _now() - timedelta(days=days, hours=hours)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def fresh_engine():
    try:
        from sqlalchemy.ext.asyncio import create_async_engine
        from app.db.models import Base

        engine = create_async_engine(
            "sqlite+aiosqlite:///:memory:",
            echo=False,
            connect_args={"check_same_thread": False},
        )
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        yield engine
        await engine.dispose()
    except ImportError:
        pytest.skip("aiosqlite or sqlalchemy not installed")


@pytest_asyncio.fixture
async def session(fresh_engine):
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    factory = async_sessionmaker(fresh_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as s:
        yield s


# Shorthand for creating a subscription row via billing_repo
async def _make_sub(session, *, user_id, plan_name, status,
                    period_start=None, period_end=None,
                    trial_ends_at=None, grace_period_ends_at=None,
                    stripe_sub_id=None):
    from app.db.repositories.billing_repo import create_subscription
    import uuid
    row = await create_subscription(
        session,
        user_id=user_id,
        stripe_subscription_id=stripe_sub_id or f"sub_{uuid.uuid4().hex[:12]}",
        stripe_customer_id=f"cus_{uuid.uuid4().hex[:12]}",
        stripe_price_id="price_test",
        plan_name=plan_name,
        status=status,
        current_period_start=period_start or _past(days=30),
        current_period_end=period_end or _future(days=1),
        trial_ends_at=trial_ends_at,
        grace_period_ends_at=grace_period_ends_at,
    )
    await session.commit()
    return row


# ---------------------------------------------------------------------------
# 1. Free fallback — no subscription
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_free_fallback_no_subscription(session):
    """User with no subscription row resolves to Spark/free."""
    from app.services.entitlement_service import resolve_entitlements

    ent = await resolve_entitlements(session, "user-no-sub-001")

    assert ent.plan_name  == "free"
    assert ent.tier_name  == "Spark"
    assert ent.plan_status == "free_fallback"
    assert ent.show_upgrade_cta is True
    assert ent.watchlist_limit       == 5
    assert ent.portfolio_limit       == 1
    assert ent.position_limit        == 10
    assert ent.dossier_monthly_limit == 3
    assert ent.briefing_limit        == 1
    assert ent.delivery_limit        == 1
    assert ent.can_use_portfolio_intelligence is False
    assert ent.can_use_email_delivery         is False
    assert ent.can_use_push_delivery          is False
    assert ent.has_unlimited_inbox            is False


# ---------------------------------------------------------------------------
# 2. Cache hit
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cache_hit_returned_without_subscription_query(session):
    """A valid cache row is returned directly without touching subscriptions."""
    from app.db.repositories.billing_repo import upsert_entitlement_cache
    from app.services.entitlement_service import resolve_entitlements

    # Write a cache row that says the user is pro.
    import json
    features = {
        "can_use_portfolio_intelligence": True,
        "can_use_email_delivery": True,
        "can_use_push_delivery": False,
        "can_set_briefing_time": True,
        "can_use_custom_quiet_hours": True,
        "can_export_data": True,
        "can_use_api": False,
        "can_use_org_features": False,
        "has_unlimited_inbox": True,
        "show_upgrade_cta": False,
        "briefing_limit": -1,
        "delivery_limit": 2,
        "tier_name": "Signal",
        "cache_expires_at": _future(hours=1).isoformat(),
    }
    await upsert_entitlement_cache(
        session,
        "user-cache-hit-001",
        plan_name="pro",
        plan_status="active",
        watchlist_limit=-1,
        portfolio_limit=5,
        position_limit=-1,
        dossier_monthly_limit=-1,
        features_json=json.dumps(features),
        expires_at=_future(hours=1),
    )
    await session.commit()

    ent = await resolve_entitlements(session, "user-cache-hit-001")

    assert ent.plan_name  == "pro"
    assert ent.tier_name  == "Signal"
    assert ent.plan_status == "active"
    assert ent.watchlist_limit == -1
    assert ent.portfolio_limit == 5
    assert ent.can_use_portfolio_intelligence is True
    assert ent.can_use_email_delivery         is True
    assert ent.briefing_limit                 == -1
    assert ent.delivery_limit                 == 2


# ---------------------------------------------------------------------------
# 3. Subscription hit — active pro
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_active_subscription_resolves_to_pro(session):
    """Active pro subscription → Signal tier."""
    from app.services.entitlement_service import resolve_entitlements

    await _make_sub(session, user_id="user-pro-001", plan_name="pro", status="active")

    ent = await resolve_entitlements(session, "user-pro-001")

    assert ent.plan_name   == "pro"
    assert ent.tier_name   == "Signal"
    assert ent.plan_status == "active"
    assert ent.watchlist_limit       == -1
    assert ent.portfolio_limit       == 5
    assert ent.position_limit        == -1
    assert ent.dossier_monthly_limit == -1
    assert ent.can_use_portfolio_intelligence is True
    assert ent.can_use_email_delivery         is True
    assert ent.can_use_push_delivery          is False
    assert ent.has_unlimited_inbox            is True
    assert ent.show_upgrade_cta               is False


# ---------------------------------------------------------------------------
# 4. System user — always unlimited
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_system_user_always_unlimited(session):
    """SYSTEM_DEFAULT_USER_ID resolves to unlimited regardless of DB state."""
    from app.services.entitlement_service import (
        resolve_entitlements,
        SYSTEM_DEFAULT_USER_ID,
    )

    ent = await resolve_entitlements(session, SYSTEM_DEFAULT_USER_ID)

    assert ent.plan_name   == "system"
    assert ent.plan_status == "system"
    assert ent.watchlist_limit       == -1
    assert ent.portfolio_limit       == -1
    assert ent.position_limit        == -1
    assert ent.dossier_monthly_limit == -1
    assert ent.briefing_limit        == -1
    assert ent.delivery_limit        == -1
    assert ent.can_use_portfolio_intelligence is True
    assert ent.can_use_api                    is True
    assert ent.can_use_org_features           is True
    assert ent.show_upgrade_cta               is False


@pytest.mark.asyncio
async def test_system_user_unlimited_with_none_session():
    """System user bypass must work even when session is None."""
    from app.services.entitlement_service import (
        resolve_entitlements,
        SYSTEM_DEFAULT_USER_ID,
    )

    ent = await resolve_entitlements(None, SYSTEM_DEFAULT_USER_ID)

    assert ent.plan_name == "system"
    assert ent.watchlist_limit == -1


# ---------------------------------------------------------------------------
# 5. Expired subscription — past_due, grace expired
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_past_due_grace_expired_falls_back_to_free(session):
    """past_due + grace_period_ends_at in the past → Spark/free."""
    from app.services.entitlement_service import resolve_entitlements

    await _make_sub(
        session,
        user_id="user-grace-exp-001",
        plan_name="pro",
        status="past_due",
        grace_period_ends_at=_past(days=1),   # grace window has closed
    )

    ent = await resolve_entitlements(session, "user-grace-exp-001")

    assert ent.plan_name   == "free"
    assert ent.plan_status == "free_fallback"
    assert ent.watchlist_limit == 5
    assert ent.can_use_portfolio_intelligence is False


# ---------------------------------------------------------------------------
# 6. Grace period state — past_due but within grace window
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_past_due_within_grace_retains_access(session):
    """past_due + grace_period_ends_at in the future → retains subscription access."""
    from app.services.entitlement_service import resolve_entitlements

    await _make_sub(
        session,
        user_id="user-grace-active-001",
        plan_name="pro",
        status="past_due",
        grace_period_ends_at=_future(days=2),  # still within grace
    )

    ent = await resolve_entitlements(session, "user-grace-active-001")

    assert ent.plan_status == "grace"
    assert ent.plan_name   == "pro"
    assert ent.can_use_portfolio_intelligence is True
    assert ent.watchlist_limit == -1


# ---------------------------------------------------------------------------
# 7. Cache refresh — force re-resolve
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_refresh_entitlements_bypasses_stale_cache(session):
    """refresh_entitlements invalidates the cache and re-resolves from subscription."""
    from app.db.repositories.billing_repo import upsert_entitlement_cache
    from app.services.entitlement_service import resolve_entitlements, refresh_entitlements
    import json

    uid = "user-refresh-001"

    # Pre-populate cache with an incorrect (stale) 'pro' entry.
    features = {
        "can_use_portfolio_intelligence": True,
        "can_use_email_delivery": True,
        "can_use_push_delivery": False,
        "can_set_briefing_time": True,
        "can_use_custom_quiet_hours": True,
        "can_export_data": True,
        "can_use_api": False,
        "can_use_org_features": False,
        "has_unlimited_inbox": True,
        "show_upgrade_cta": False,
        "briefing_limit": -1,
        "delivery_limit": 2,
        "tier_name": "Signal",
        "cache_expires_at": _future(hours=1).isoformat(),
    }
    await upsert_entitlement_cache(
        session, uid,
        plan_name="pro",
        plan_status="active",
        watchlist_limit=-1,
        portfolio_limit=5,
        position_limit=-1,
        dossier_monthly_limit=-1,
        features_json=json.dumps(features),
        expires_at=_future(hours=1),
    )
    await session.commit()

    # Cache says pro — but no subscription exists.
    cached = await resolve_entitlements(session, uid)
    assert cached.plan_name == "pro"

    # After refresh, should fall back to free (no real subscription).
    refreshed = await refresh_entitlements(session, uid)
    assert refreshed.plan_name == "free"
    assert refreshed.plan_status == "free_fallback"


# ---------------------------------------------------------------------------
# 8. Null-session safety
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_null_session_safety():
    """All public functions return safe defaults when session is None."""
    from app.services.entitlement_service import (
        resolve_entitlements,
        get_cached_entitlements,
        refresh_entitlements,
        resolve_plan,
        SYSTEM_DEFAULT_USER_ID,
    )

    uid = "user-null-sess-001"

    # resolve_entitlements → free fallback
    ent = await resolve_entitlements(None, uid)
    assert ent.plan_name == "free"
    assert ent.plan_status == "free_fallback"

    # get_cached_entitlements → None
    cached = await get_cached_entitlements(None, uid)
    assert cached is None

    # refresh_entitlements → free fallback
    refreshed = await refresh_entitlements(None, uid)
    assert refreshed.plan_name == "free"

    # resolve_plan → "free"
    plan = await resolve_plan(None, uid)
    assert plan == "free"

    # System user still gets unlimited even with None session
    sys_ent = await resolve_entitlements(None, SYSTEM_DEFAULT_USER_ID)
    assert sys_ent.plan_name == "system"


# ---------------------------------------------------------------------------
# 9. Trialing → pro access with trial_days_remaining
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_trialing_resolves_to_pro(session):
    """Trialing subscription → Signal tier with trial_days_remaining set."""
    from app.services.entitlement_service import resolve_entitlements

    await _make_sub(
        session,
        user_id="user-trial-001",
        plan_name="pro",
        status="trialing",
        trial_ends_at=_future(days=7),
    )

    ent = await resolve_entitlements(session, "user-trial-001")

    assert ent.plan_name   == "pro"
    assert ent.plan_status == "trialing"
    assert ent.trial_days_remaining is not None
    assert ent.trial_days_remaining >= 6   # 7 days ahead, delta may be 6 at boundary
    assert ent.show_upgrade_cta is True    # nudge to convert
    assert ent.can_use_portfolio_intelligence is True
    assert ent.watchlist_limit == -1


# ---------------------------------------------------------------------------
# 10. Expired trial → free fallback
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_expired_trial_falls_back_to_free(session):
    """Trialing subscription with trial_ends_at in past → free fallback."""
    from app.services.entitlement_service import resolve_entitlements

    await _make_sub(
        session,
        user_id="user-trial-expired-001",
        plan_name="pro",
        status="trialing",
        trial_ends_at=_past(days=1),   # trial ended yesterday
    )

    ent = await resolve_entitlements(session, "user-trial-expired-001")

    assert ent.plan_name   == "free"
    assert ent.plan_status == "free_fallback"
    assert ent.can_use_portfolio_intelligence is False


# ---------------------------------------------------------------------------
# 11. EntitlementSet field correctness per tier
# ---------------------------------------------------------------------------

def test_free_tier_fields():
    """Spark (free) tier must match the spec feature gate matrix."""
    from app.services.entitlement_service import _build_entitlement_set

    ent = _build_entitlement_set("u", "free", "free_fallback")

    assert ent.tier_name              == "Spark"
    assert ent.watchlist_limit        == 5
    assert ent.portfolio_limit        == 1
    assert ent.position_limit         == 10
    assert ent.dossier_monthly_limit  == 3
    assert ent.briefing_limit         == 1
    assert ent.delivery_limit         == 1
    assert ent.show_upgrade_cta       is True
    assert ent.can_use_portfolio_intelligence is False
    assert ent.can_use_email_delivery         is False
    assert ent.can_use_push_delivery          is False
    assert ent.can_set_briefing_time          is False
    assert ent.can_use_custom_quiet_hours     is False
    assert ent.can_export_data                is False
    assert ent.can_use_api                    is False
    assert ent.can_use_org_features           is False
    assert ent.has_unlimited_inbox            is False


def test_signal_tier_fields():
    """Signal (pro) tier must match the spec feature gate matrix."""
    from app.services.entitlement_service import _build_entitlement_set

    ent = _build_entitlement_set("u", "pro", "active")

    assert ent.tier_name              == "Signal"
    assert ent.watchlist_limit        == -1
    assert ent.portfolio_limit        == 5
    assert ent.position_limit         == -1
    assert ent.dossier_monthly_limit  == -1
    assert ent.briefing_limit         == -1
    assert ent.delivery_limit         == 2
    assert ent.show_upgrade_cta       is False
    assert ent.can_use_portfolio_intelligence is True
    assert ent.can_use_email_delivery         is True
    assert ent.can_use_push_delivery          is False
    assert ent.can_set_briefing_time          is True
    assert ent.can_use_custom_quiet_hours     is True
    assert ent.can_export_data                is True
    assert ent.can_use_api                    is False
    assert ent.can_use_org_features           is False
    assert ent.has_unlimited_inbox            is True


# ---------------------------------------------------------------------------
# 12. resolve_plan convenience wrapper
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_resolve_plan_returns_plan_name(session):
    """resolve_plan returns the plan name string, not an EntitlementSet."""
    from app.services.entitlement_service import resolve_plan

    # No subscription → free
    plan = await resolve_plan(session, "user-rp-001")
    assert plan == "free"

    # Add active subscription
    await _make_sub(session, user_id="user-rp-002", plan_name="pro", status="active")
    plan = await resolve_plan(session, "user-rp-002")
    assert plan == "pro"


# ---------------------------------------------------------------------------
# 13. Cache round-trip
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cache_round_trip(session):
    """EntitlementSet → cache row → deserialised → same field values."""
    from app.services.entitlement_service import (
        _build_entitlement_set,
        _entitlement_set_to_cache_row,
        _cache_row_to_entitlement_set,
    )
    from app.db.repositories.billing_repo import (
        upsert_entitlement_cache,
        get_entitlement_cache,
    )

    uid = "user-roundtrip-001"
    original = _build_entitlement_set(uid, "pro", "active")
    cache_row = _entitlement_set_to_cache_row(original)

    await upsert_entitlement_cache(session, uid, **cache_row)
    await session.commit()

    row = await get_entitlement_cache(session, uid)
    assert row is not None

    restored = _cache_row_to_entitlement_set(uid, row)
    assert restored is not None
    assert restored.plan_name              == original.plan_name
    assert restored.tier_name             == original.tier_name
    assert restored.plan_status           == original.plan_status
    assert restored.watchlist_limit       == original.watchlist_limit
    assert restored.portfolio_limit       == original.portfolio_limit
    assert restored.position_limit        == original.position_limit
    assert restored.dossier_monthly_limit == original.dossier_monthly_limit
    assert restored.briefing_limit        == original.briefing_limit
    assert restored.delivery_limit        == original.delivery_limit
    assert restored.can_use_portfolio_intelligence == original.can_use_portfolio_intelligence
    assert restored.can_use_email_delivery         == original.can_use_email_delivery
    assert restored.can_use_push_delivery          == original.can_use_push_delivery
    assert restored.has_unlimited_inbox            == original.has_unlimited_inbox
    assert restored.show_upgrade_cta               == original.show_upgrade_cta


# ---------------------------------------------------------------------------
# 14. Teams tier
# ---------------------------------------------------------------------------

def test_teams_tier_fields():
    """Syndicate (teams) tier must match the spec feature gate matrix."""
    from app.services.entitlement_service import _build_entitlement_set

    ent = _build_entitlement_set("u", "teams", "active")

    assert ent.tier_name              == "Syndicate"
    assert ent.watchlist_limit        == -1
    assert ent.portfolio_limit        == -1
    assert ent.position_limit         == -1
    assert ent.dossier_monthly_limit  == -1
    assert ent.delivery_limit         == 3
    assert ent.can_use_push_delivery          is True
    assert ent.can_use_org_features           is True
    assert ent.can_use_api                    is True
    assert ent.show_upgrade_cta               is False


# ---------------------------------------------------------------------------
# 15. Institutional tier
# ---------------------------------------------------------------------------

def test_institutional_tier_fields():
    """Edge (institutional) tier must have all flags enabled."""
    from app.services.entitlement_service import _build_entitlement_set

    ent = _build_entitlement_set("u", "institutional", "active")

    assert ent.tier_name              == "Edge"
    assert ent.watchlist_limit        == -1
    assert ent.portfolio_limit        == -1
    assert ent.dossier_monthly_limit  == -1
    assert ent.delivery_limit         == 3
    assert ent.can_use_portfolio_intelligence is True
    assert ent.can_use_email_delivery         is True
    assert ent.can_use_push_delivery          is True
    assert ent.can_use_api                    is True
    assert ent.can_use_org_features           is True
    assert ent.can_export_data                is True
    assert ent.has_unlimited_inbox            is True
    assert ent.show_upgrade_cta               is False


# ---------------------------------------------------------------------------
# 16. Stale cache is not returned
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_stale_cache_not_returned(session):
    """get_cached_entitlements returns None when expires_at is in the past."""
    from app.db.repositories.billing_repo import upsert_entitlement_cache
    from app.services.entitlement_service import get_cached_entitlements
    import json

    uid = "user-stale-cache-001"
    features = {
        "can_use_portfolio_intelligence": True,
        "tier_name": "Signal",
        "cache_expires_at": _past(hours=2).isoformat(),
        "briefing_limit": -1, "delivery_limit": 2,
        "show_upgrade_cta": False,
        "can_use_email_delivery": True, "can_use_push_delivery": False,
        "can_set_briefing_time": True, "can_use_custom_quiet_hours": True,
        "can_export_data": True, "can_use_api": False,
        "can_use_org_features": False, "has_unlimited_inbox": True,
    }
    await upsert_entitlement_cache(
        session, uid,
        plan_name="pro",
        plan_status="active",
        watchlist_limit=-1,
        portfolio_limit=5,
        position_limit=-1,
        dossier_monthly_limit=-1,
        features_json=json.dumps(features),
        expires_at=_past(hours=2),   # already expired
    )
    await session.commit()

    result = await get_cached_entitlements(session, uid)
    assert result is None   # expired → cache miss


# ---------------------------------------------------------------------------
# 17. No Stripe dependency
# ---------------------------------------------------------------------------

def test_no_stripe_import():
    """entitlement_service must not import stripe or stripe-related modules."""
    import importlib, sys

    # Reload from source to check imports without polluting test state.
    mod_name = "app.services.entitlement_service"
    if mod_name in sys.modules:
        del sys.modules[mod_name]

    import app.services.entitlement_service as svc

    # No stripe module should be pulled in.
    stripe_mods = [k for k in sys.modules if "stripe" in k.lower()]
    assert not stripe_mods, f"stripe module imported: {stripe_mods}"
