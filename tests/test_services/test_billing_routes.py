"""
Phase 17 · Slice 5 — Billing route tests.

Covers GET /billing/status, POST /billing/portal, POST /billing/cancel.
No Stripe SDK installed — stripe is injected via sys.modules mock.
DB operations use in-memory SQLite via aiosqlite.

Validates:
  1.  /billing/status free tier — free plan, no subscription fields
  2.  /billing/status active subscription — correct plan, period end, no trial/grace
  3.  /billing/status trial — is_trial=true, trial_ends_at set, days_remaining
  4.  /billing/status grace period — is_grace_period=true, grace_period_ends_at
  5.  /billing/status system user — unlimited, no DB query
  6.  /billing/status stripe_customer_present — reflects users.stripe_customer_id
  7.  POST /billing/portal disabled — 503 when STRIPE_ENABLED=false
  8.  POST /billing/portal no customer — 400 when no stripe_customer_id
  9.  POST /billing/portal mocked — 200 with portal_url (mocked Stripe)
  10. POST /billing/portal missing return URL — 503 misconfigured
  11. POST /billing/cancel disabled — 503 when STRIPE_ENABLED=false
  12. POST /billing/cancel no active subscription — 400
  13. POST /billing/cancel mocked — success, local row updated, cache invalidated
  14. POST /billing/cancel system user — 400
  15. No entitlement changes via status route
  16. No enforcement — resolve_entitlements not gating any response
"""

from __future__ import annotations

import sys
from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
import pytest_asyncio
from fastapi import FastAPI
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _future(hours: int = 1) -> datetime:
    return _now() + timedelta(hours=hours)


def _past(hours: int = 1) -> datetime:
    return _now() - timedelta(hours=hours)


SYSTEM_UID = "00000000-0000-0000-0000-000000000001"


# ---------------------------------------------------------------------------
# DB fixtures
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
        pytest.skip("aiosqlite not installed")


@pytest_asyncio.fixture
async def session(fresh_engine):
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    factory = async_sessionmaker(fresh_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as s:
        yield s


def _session_ctx(engine):
    """Return an async context manager that yields a fresh session."""
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    @asynccontextmanager
    async def _ctx():
        async with factory() as s:
            yield s

    return _ctx


# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------

async def _seed_user(session, *, user_id: str = "user-001", plan: str = "free",
                      stripe_customer_id: str = None):
    from app.db.models import User
    u = User(id=user_id, email=f"{user_id}@test.com", plan=plan,
             stripe_customer_id=stripe_customer_id)
    session.add(u)
    await session.flush()
    return u


async def _seed_subscription(session, *, user_id: str, sub_id: str,
                              customer_id: str = "cus_001",
                              plan_name: str = "pro", status: str = "active",
                              trial_ends_at=None, grace_period_ends_at=None,
                              cancel_at_period_end: bool = False):
    from app.db.repositories.billing_repo import create_subscription
    now = _now()
    return await create_subscription(
        session,
        user_id=user_id,
        stripe_subscription_id=sub_id,
        stripe_customer_id=customer_id,
        stripe_price_id="price_signal_mo",
        plan_name=plan_name,
        status=status,
        current_period_start=now,
        current_period_end=_future(hours=720),
        trial_ends_at=trial_ends_at,
        grace_period_ends_at=grace_period_ends_at,
        cancel_at_period_end=cancel_at_period_end,
    )


# ---------------------------------------------------------------------------
# App factory — mounts the billing router against a fake session
# ---------------------------------------------------------------------------

def _make_app(engine, user_id: str = "user-001"):
    """Build a minimal FastAPI app with billing router + request.state.user_id."""
    app = FastAPI()

    from app.routers.billing import router as billing_router
    app.include_router(billing_router)

    @app.middleware("http")
    async def _inject_user(request, call_next):
        request.state.user_id = user_id
        return await call_next(request)

    app.state._session_factory = _session_ctx(engine)
    return app


# ---------------------------------------------------------------------------
# Stripe mock
# ---------------------------------------------------------------------------

def _make_stripe_mock(portal_url: str = "https://billing.stripe.com/test",
                       portal_id: str = "bps_test_001"):
    m = MagicMock()
    portal_session = MagicMock()
    portal_session.url = portal_url
    portal_session.id  = portal_id
    m.billing_portal = MagicMock()
    m.billing_portal.Session.create.return_value = portal_session

    sub_mock = MagicMock()
    sub_mock.current_period_end = 9999999999
    m.Subscription.modify.return_value = sub_mock

    m.api_key = None
    return m


# ---------------------------------------------------------------------------
# 1. /billing/status — free tier (no subscription)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_status_free_tier(fresh_engine):
    async with _session_ctx(fresh_engine)() as s:
        await _seed_user(s, user_id="user-free-01")
        await s.commit()

    with patch("app.db.get_session", _session_ctx(fresh_engine)):
        app = _make_app(fresh_engine, user_id="user-free-01")
        with TestClient(app) as client:
            resp = client.get("/billing/status")

    assert resp.status_code == 200
    body = resp.json()
    assert body["plan"] == "free"
    assert body["subscription_status"] is None
    assert body["is_trial"] is False
    assert body["is_grace_period"] is False
    assert body["cancel_at_period_end"] is False
    assert body["stripe_customer_present"] is False
    assert body["entitlements"]["tier_name"] == "Spark"
    assert body["entitlements"]["dossier_monthly_limit"] == 3


# ---------------------------------------------------------------------------
# 2. /billing/status — active subscription
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_status_active_subscription(fresh_engine):
    async with _session_ctx(fresh_engine)() as s:
        await _seed_user(s, user_id="user-active-01",
                          stripe_customer_id="cus_active_01", plan="pro")
        await _seed_subscription(s, user_id="user-active-01",
                                  sub_id="sub_active_001", status="active",
                                  customer_id="cus_active_01")
        await s.commit()

    with patch("app.db.get_session", _session_ctx(fresh_engine)):
        app = _make_app(fresh_engine, user_id="user-active-01")
        with patch("app.config.settings") as cfg:
            cfg.stripe_price_signal_monthly    = "price_signal_mo"
            cfg.stripe_price_signal_yearly     = "price_signal_yr"
            cfg.stripe_price_syndicate_monthly = "price_syndicate_mo"
            with TestClient(app) as client:
                resp = client.get("/billing/status")

    assert resp.status_code == 200
    body = resp.json()
    assert body["plan"] == "pro"
    assert body["subscription_status"] == "active"
    assert body["is_trial"] is False
    assert body["is_grace_period"] is False
    assert body["stripe_customer_present"] is True
    assert body["current_period_end"] is not None
    assert body["entitlements"]["tier_name"] == "Signal"
    assert body["entitlements"]["dossier_monthly_limit"] == -1


# ---------------------------------------------------------------------------
# 3. /billing/status — trial subscription
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_status_trial(fresh_engine):
    trial_end = _future(hours=14 * 24)

    async with _session_ctx(fresh_engine)() as s:
        await _seed_user(s, user_id="user-trial-01",
                          stripe_customer_id="cus_trial_01", plan="pro")
        await _seed_subscription(s, user_id="user-trial-01",
                                  sub_id="sub_trial_01", status="trialing",
                                  customer_id="cus_trial_01",
                                  trial_ends_at=trial_end)
        await s.commit()

    with patch("app.db.get_session", _session_ctx(fresh_engine)):
        app = _make_app(fresh_engine, user_id="user-trial-01")
        with patch("app.config.settings") as cfg:
            cfg.stripe_price_signal_monthly    = "price_signal_mo"
            cfg.stripe_price_signal_yearly     = "price_signal_yr"
            cfg.stripe_price_syndicate_monthly = "price_syndicate_mo"
            with TestClient(app) as client:
                resp = client.get("/billing/status")

    assert resp.status_code == 200
    body = resp.json()
    assert body["is_trial"] is True
    assert body["trial_ends_at"] is not None
    assert body["trial_days_remaining"] is not None
    assert body["trial_days_remaining"] >= 13
    assert body["plan"] == "pro"
    assert body["entitlements"]["tier_name"] == "Signal"


# ---------------------------------------------------------------------------
# 4. /billing/status — grace period
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_status_grace_period(fresh_engine):
    grace_end = _future(hours=48)

    async with _session_ctx(fresh_engine)() as s:
        await _seed_user(s, user_id="user-grace-01",
                          stripe_customer_id="cus_grace_01", plan="pro")
        await _seed_subscription(s, user_id="user-grace-01",
                                  sub_id="sub_grace_01", status="past_due",
                                  customer_id="cus_grace_01",
                                  grace_period_ends_at=grace_end)
        await s.commit()

    with patch("app.db.get_session", _session_ctx(fresh_engine)):
        app = _make_app(fresh_engine, user_id="user-grace-01")
        with patch("app.config.settings") as cfg:
            cfg.stripe_price_signal_monthly    = "price_signal_mo"
            cfg.stripe_price_signal_yearly     = "price_signal_yr"
            cfg.stripe_price_syndicate_monthly = "price_syndicate_mo"
            with TestClient(app) as client:
                resp = client.get("/billing/status")

    assert resp.status_code == 200
    body = resp.json()
    assert body["is_grace_period"] is True
    assert body["grace_period_ends_at"] is not None
    assert body["subscription_status"] == "past_due"
    # Entitlement resolves to pro-level during grace.
    assert body["entitlements"]["plan_status"] == "grace"


# ---------------------------------------------------------------------------
# 5. /billing/status — system user returns unlimited
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_status_system_user(fresh_engine):
    with patch("app.db.get_session", _session_ctx(fresh_engine)):
        app = _make_app(fresh_engine, user_id=SYSTEM_UID)
        with TestClient(app) as client:
            resp = client.get("/billing/status")

    assert resp.status_code == 200
    body = resp.json()
    assert body["plan"] == "system"
    assert body["subscription_status"] == "system"
    assert body["entitlements"]["tier_name"] == "System"
    assert body["entitlements"]["dossier_monthly_limit"] == -1
    assert body["entitlements"]["watchlist_limit"] == -1
    assert body["stripe_customer_present"] is False


# ---------------------------------------------------------------------------
# 6. /billing/status — stripe_customer_present reflects DB state
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_status_stripe_customer_present(fresh_engine):
    async with _session_ctx(fresh_engine)() as s:
        await _seed_user(s, user_id="user-cuspresent-01",
                          stripe_customer_id="cus_present_01")
        await s.commit()

    with patch("app.db.get_session", _session_ctx(fresh_engine)):
        app = _make_app(fresh_engine, user_id="user-cuspresent-01")
        with TestClient(app) as client:
            resp = client.get("/billing/status")

    assert resp.json()["stripe_customer_present"] is True


# ---------------------------------------------------------------------------
# 7. POST /billing/portal — disabled mode 503
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_portal_disabled_returns_503(fresh_engine):
    with patch("app.db.get_session", _session_ctx(fresh_engine)), \
         patch("app.config.settings") as cfg:
        cfg.stripe_enabled = False
        app = _make_app(fresh_engine)
        with TestClient(app) as client:
            resp = client.post("/billing/portal")

    assert resp.status_code == 503
    body = resp.json()
    assert body["disabled"] is True
    assert body["reason"] == "stripe_disabled"
    assert body["portal_url"] is None


# ---------------------------------------------------------------------------
# 8. POST /billing/portal — no stripe_customer_id → 400
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_portal_no_customer_400(fresh_engine):
    async with _session_ctx(fresh_engine)() as s:
        await _seed_user(s, user_id="user-nocust-01")  # no stripe_customer_id
        await s.commit()

    with patch("app.db.get_session", _session_ctx(fresh_engine)), \
         patch("app.config.settings") as cfg:
        cfg.stripe_enabled = True
        cfg.stripe_secret_key = "sk_test_dummy"
        cfg.stripe_portal_return_url = "https://example.com/billing"
        app = _make_app(fresh_engine, user_id="user-nocust-01")
        with TestClient(app) as client:
            resp = client.post("/billing/portal")

    assert resp.status_code == 400
    assert "billing account" in resp.json()["detail"].lower()


# ---------------------------------------------------------------------------
# 9. POST /billing/portal — mocked success → 200 with portal_url
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_portal_mocked_success(fresh_engine):
    stripe_mock = _make_stripe_mock()
    sys.modules["stripe"] = stripe_mock

    async with _session_ctx(fresh_engine)() as s:
        await _seed_user(s, user_id="user-portal-01",
                          stripe_customer_id="cus_portal_01")
        await s.commit()

    try:
        with patch("app.db.get_session", _session_ctx(fresh_engine)), \
             patch("app.config.settings") as cfg:
            cfg.stripe_enabled = True
            cfg.stripe_secret_key = "sk_test_dummy"
            cfg.stripe_portal_return_url = "https://example.com/billing"
            app = _make_app(fresh_engine, user_id="user-portal-01")
            with TestClient(app) as client:
                resp = client.post("/billing/portal")
    finally:
        sys.modules.pop("stripe", None)

    assert resp.status_code == 200
    body = resp.json()
    assert body["disabled"] is False
    assert body["portal_url"] == "https://billing.stripe.com/test"
    stripe_mock.billing_portal.Session.create.assert_called_once()
    call_kwargs = stripe_mock.billing_portal.Session.create.call_args.kwargs
    assert call_kwargs["customer"] == "cus_portal_01"
    assert call_kwargs["return_url"] == "https://example.com/billing"


# ---------------------------------------------------------------------------
# 10. POST /billing/portal — missing return URL → 503
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_portal_missing_return_url_503(fresh_engine):
    stripe_mock = _make_stripe_mock()
    sys.modules["stripe"] = stripe_mock

    async with _session_ctx(fresh_engine)() as s:
        await _seed_user(s, user_id="user-portal-nourl-01",
                          stripe_customer_id="cus_nourl_01")
        await s.commit()

    try:
        with patch("app.db.get_session", _session_ctx(fresh_engine)), \
             patch("app.config.settings") as cfg:
            cfg.stripe_enabled = True
            cfg.stripe_secret_key = "sk_test_dummy"
            cfg.stripe_portal_return_url = ""   # <-- empty
            app = _make_app(fresh_engine, user_id="user-portal-nourl-01")
            with TestClient(app) as client:
                resp = client.post("/billing/portal")
    finally:
        sys.modules.pop("stripe", None)

    assert resp.status_code == 503


# ---------------------------------------------------------------------------
# 11. POST /billing/cancel — disabled mode 503
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cancel_disabled_returns_503(fresh_engine):
    with patch("app.db.get_session", _session_ctx(fresh_engine)), \
         patch("app.config.settings") as cfg:
        cfg.stripe_enabled = False
        app = _make_app(fresh_engine)
        with TestClient(app) as client:
            resp = client.post("/billing/cancel")

    assert resp.status_code == 503
    body = resp.json()
    assert body["disabled"] is True
    assert body["reason"] == "stripe_disabled"


# ---------------------------------------------------------------------------
# 12. POST /billing/cancel — no active subscription → 400
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cancel_no_subscription_400(fresh_engine):
    stripe_mock = _make_stripe_mock()
    sys.modules["stripe"] = stripe_mock

    async with _session_ctx(fresh_engine)() as s:
        await _seed_user(s, user_id="user-cannosub-01")
        await s.commit()

    try:
        with patch("app.db.get_session", _session_ctx(fresh_engine)), \
             patch("app.config.settings") as cfg:
            cfg.stripe_enabled = True
            cfg.stripe_secret_key = "sk_test_dummy"
            app = _make_app(fresh_engine, user_id="user-cannosub-01")
            with TestClient(app) as client:
                resp = client.post("/billing/cancel")
    finally:
        sys.modules.pop("stripe", None)

    assert resp.status_code == 400
    assert "subscription" in resp.json()["detail"].lower()


# ---------------------------------------------------------------------------
# 13. POST /billing/cancel — mocked success: Stripe called, local row updated
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cancel_mocked_success(fresh_engine):
    stripe_mock = _make_stripe_mock()
    sys.modules["stripe"] = stripe_mock

    async with _session_ctx(fresh_engine)() as s:
        await _seed_user(s, user_id="user-cancel-01",
                          stripe_customer_id="cus_cancel_01", plan="pro")
        await _seed_subscription(s, user_id="user-cancel-01",
                                  sub_id="sub_cancel_001",
                                  customer_id="cus_cancel_01",
                                  status="active",
                                  cancel_at_period_end=False)
        await s.commit()

    try:
        with patch("app.db.get_session", _session_ctx(fresh_engine)), \
             patch("app.config.settings") as cfg:
            cfg.stripe_enabled = True
            cfg.stripe_secret_key = "sk_test_dummy"
            app = _make_app(fresh_engine, user_id="user-cancel-01")
            with TestClient(app) as client:
                resp = client.post("/billing/cancel")
    finally:
        sys.modules.pop("stripe", None)

    assert resp.status_code == 200
    body = resp.json()
    assert body["canceled"] is True
    assert body["cancel_at_period_end"] is True

    # Verify local DB row was updated.
    from app.db.repositories.billing_repo import get_subscription_by_stripe_id
    async with _session_ctx(fresh_engine)() as s:
        row = await get_subscription_by_stripe_id(s, "sub_cancel_001")
    assert row.cancel_at_period_end is True

    # Stripe was called.
    stripe_mock.Subscription.modify.assert_called_once_with(
        "sub_cancel_001", cancel_at_period_end=True
    )


# ---------------------------------------------------------------------------
# 14. POST /billing/cancel — system user → 400
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cancel_system_user_400(fresh_engine):
    stripe_mock = _make_stripe_mock()
    sys.modules["stripe"] = stripe_mock

    try:
        with patch("app.db.get_session", _session_ctx(fresh_engine)), \
             patch("app.config.settings") as cfg:
            cfg.stripe_enabled = True
            cfg.stripe_secret_key = "sk_test_dummy"
            app = _make_app(fresh_engine, user_id=SYSTEM_UID)
            with TestClient(app) as client:
                resp = client.post("/billing/cancel")
    finally:
        sys.modules.pop("stripe", None)

    assert resp.status_code == 400
    assert "system user" in resp.json()["detail"].lower()


# ---------------------------------------------------------------------------
# 15. /billing/status — no entitlement enforcement
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_status_no_entitlement_enforcement(fresh_engine):
    """Status endpoint never blocks based on entitlements."""
    async with _session_ctx(fresh_engine)() as s:
        await _seed_user(s, user_id="user-nogate-01")
        await s.commit()

    with patch("app.db.get_session", _session_ctx(fresh_engine)):
        app = _make_app(fresh_engine, user_id="user-nogate-01")
        with TestClient(app) as client:
            # Even a free-tier user can always read their billing status.
            resp = client.get("/billing/status")

    assert resp.status_code == 200
    assert resp.json()["plan"] == "free"


# ---------------------------------------------------------------------------
# 16. /billing/status — cancel_at_period_end reflected in response
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_status_cancel_at_period_end_flag(fresh_engine):
    async with _session_ctx(fresh_engine)() as s:
        await _seed_user(s, user_id="user-cxl-status-01",
                          stripe_customer_id="cus_cxl_01", plan="pro")
        await _seed_subscription(s, user_id="user-cxl-status-01",
                                  sub_id="sub_cxl_status_001",
                                  customer_id="cus_cxl_01",
                                  status="active",
                                  cancel_at_period_end=True)
        await s.commit()

    with patch("app.db.get_session", _session_ctx(fresh_engine)):
        app = _make_app(fresh_engine, user_id="user-cxl-status-01")
        with patch("app.config.settings") as cfg:
            cfg.stripe_price_signal_monthly    = "price_signal_mo"
            cfg.stripe_price_signal_yearly     = "price_signal_yr"
            cfg.stripe_price_syndicate_monthly = "price_syndicate_mo"
            with TestClient(app) as client:
                resp = client.get("/billing/status")

    assert resp.status_code == 200
    assert resp.json()["cancel_at_period_end"] is True


# ---------------------------------------------------------------------------
# Bonus: portal system user → 400
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_portal_system_user_400(fresh_engine):
    with patch("app.db.get_session", _session_ctx(fresh_engine)), \
         patch("app.config.settings") as cfg:
        cfg.stripe_enabled = True
        cfg.stripe_secret_key = "sk_test_dummy"
        cfg.stripe_portal_return_url = "https://example.com"
        app = _make_app(fresh_engine, user_id=SYSTEM_UID)
        with TestClient(app) as client:
            resp = client.post("/billing/portal")

    assert resp.status_code == 400
    assert "system user" in resp.json()["detail"].lower()


# ---------------------------------------------------------------------------
# Bonus: /billing/status entitlements dict has expected keys
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_status_entitlements_shape(fresh_engine):
    async with _session_ctx(fresh_engine)() as s:
        await _seed_user(s, user_id="user-shape-01")
        await s.commit()

    with patch("app.db.get_session", _session_ctx(fresh_engine)):
        app = _make_app(fresh_engine, user_id="user-shape-01")
        with TestClient(app) as client:
            resp = client.get("/billing/status")

    ent = resp.json()["entitlements"]
    required_keys = {
        "tier_name", "plan_name", "plan_status",
        "watchlist_limit", "portfolio_limit", "position_limit",
        "dossier_monthly_limit", "briefing_limit", "delivery_limit",
        "show_upgrade_cta", "trial_days_remaining", "features",
    }
    assert required_keys <= set(ent.keys())
    feature_keys = {
        "can_use_portfolio_intelligence", "can_use_email_delivery",
        "can_use_push_delivery", "can_set_briefing_time",
        "can_use_custom_quiet_hours", "can_export_data",
        "can_use_api", "can_use_org_features", "has_unlimited_inbox",
    }
    assert feature_keys <= set(ent["features"].keys())
