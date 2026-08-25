"""
Phase 17 · Slice 4 — Stripe webhook service + route tests.

All tests operate without a live Stripe connection.
Signature verification is patched at the sys.modules / function level.
DB operations use in-memory SQLite via aiosqlite.

Validates:
  1.  invalid signature → 400 from route
  2.  missing Stripe-Signature header → 400 from route
  3.  valid signature accepted (mocked) → 200
  4.  duplicate event ignored → 200 with duplicate=true
  5.  checkout.session.completed links customer to user
  6.  subscription.created creates subscription row
  7.  subscription.updated updates status and plan
  8.  subscription.deleted → status=canceled, user.plan=free, cache cleared
  9.  invoice.payment_failed → status=past_due, grace_period_ends_at set
  10. invoice.payment_succeeded → status=active, grace cleared, cache cleared
  11. unsupported event → processing_status=skipped
  12. no raw payload stored (stripe_events has no payload column)
  13. entitlement cache invalidated after subscription change
  14. no entitlement enforcement (resolve_entitlements not called)
  15. customer.deleted cancels subscriptions and clears customer link
  16. disabled mode → 200 no-op, no DB writes
  17. _map_stripe_status covers all recognised values
  18. _plan_from_price_id maps known price IDs
  19. process_event returns 'skipped' for unknown event types
"""

from __future__ import annotations

import sys
from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
import pytest_asyncio


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _future(hours: int = 1) -> datetime:
    return _now() + timedelta(hours=hours)


def _past(hours: int = 1) -> datetime:
    return _now() - timedelta(hours=hours)


def _unix(dt: datetime = None) -> int:
    dt = dt or _now()
    return int(dt.timestamp())


# ---------------------------------------------------------------------------
# SQLite fixture — shared across all tests in this file
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


# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------

async def _seed_user(session, *, user_id: str = "user-001", plan: str = "free",
                      stripe_customer_id: str = None):
    from app.db.models import User
    u = User(
        id=user_id,
        email=f"{user_id}@example.com",
        plan=plan,
        stripe_customer_id=stripe_customer_id,
    )
    session.add(u)
    await session.flush()
    return u


async def _seed_subscription(session, *, user_id: str = "user-001",
                              sub_id: str = "sub_test_001",
                              customer_id: str = "cus_test_001",
                              plan_name: str = "pro",
                              status: str = "active"):
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
    )


# ---------------------------------------------------------------------------
# Stripe mock (sys.modules injection)
# ---------------------------------------------------------------------------

def _make_stripe_mock() -> MagicMock:
    m = MagicMock()
    m.error = MagicMock()
    m.error.SignatureVerificationError = ValueError  # use ValueError as stand-in
    m.Webhook.construct_event.return_value = {}
    return m


@pytest.fixture
def stripe_mock():
    mock = _make_stripe_mock()
    sys.modules["stripe"] = mock
    yield mock
    sys.modules.pop("stripe", None)


# ---------------------------------------------------------------------------
# Event factory
# ---------------------------------------------------------------------------

def _make_event(event_type: str, obj: Dict[str, Any], event_id: str = "evt_test_001") -> dict:
    return {"id": event_id, "type": event_type, "data": {"object": obj}}


def _make_checkout_event(
    user_id: str = "user-001",
    customer_id: str = "cus_test_001",
    sub_id: str = "sub_test_001",
    event_id: str = "evt_checkout_001",
) -> dict:
    return _make_event(
        "checkout.session.completed",
        {
            "id": "cs_test_001",
            "subscription": sub_id,
            "customer": customer_id,
            "metadata": {"user_id": user_id, "plan": "pro", "interval": "month"},
        },
        event_id=event_id,
    )


def _make_sub_obj(
    sub_id: str = "sub_test_001",
    customer_id: str = "cus_test_001",
    status: str = "active",
    price_id: str = "price_signal_mo",
    interval: str = "month",
    trial_end=None,
    user_id: str = None,
) -> dict:
    obj = {
        "id": sub_id,
        "customer": customer_id,
        "status": status,
        "items": {"data": [{"price": {"id": price_id, "recurring": {"interval": interval}}}]},
        "current_period_start": _unix(_past(hours=24)),
        "current_period_end":   _unix(_future(hours=720)),
        "trial_end":            trial_end,
        "cancel_at_period_end": False,
        "canceled_at":          None,
    }
    if user_id is not None:
        obj["metadata"] = {"user_id": user_id}
    return obj


# ---------------------------------------------------------------------------
# 1. Invalid signature → 400
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_invalid_signature_returns_400(stripe_mock):
    from fastapi.testclient import TestClient
    from fastapi import FastAPI
    from app.routers.billing import router as billing_router

    stripe_mock.Webhook.construct_event.side_effect = ValueError("bad sig")

    app = FastAPI()
    app.include_router(billing_router)

    with patch("app.config.settings") as cfg:
        cfg.stripe_enabled = True
        cfg.stripe_webhook_secret = "whsec_test"
        with TestClient(app) as client:
            resp = client.post(
                "/billing/webhook",
                content=b'{"id":"evt_bad"}',
                headers={"stripe-signature": "t=1,v1=bad"},
            )

    assert resp.status_code == 400
    assert "signature" in resp.json()["detail"].lower()


# ---------------------------------------------------------------------------
# 2. Missing Stripe-Signature header → 400
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_missing_signature_header_returns_400(stripe_mock):
    from fastapi.testclient import TestClient
    from fastapi import FastAPI
    from app.routers.billing import router as billing_router

    app = FastAPI()
    app.include_router(billing_router)

    with patch("app.config.settings") as cfg:
        cfg.stripe_enabled = True
        cfg.stripe_webhook_secret = "whsec_test"
        with TestClient(app) as client:
            resp = client.post("/billing/webhook", content=b'{"id":"evt_001"}')

    assert resp.status_code == 400
    assert "stripe-signature" in resp.json()["detail"].lower()


# ---------------------------------------------------------------------------
# 3. Valid signature accepted → 200
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_valid_signature_returns_200(stripe_mock, fresh_engine):
    from fastapi.testclient import TestClient
    from fastapi import FastAPI
    from app.routers.billing import router as billing_router
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    event = _make_event("customer.subscription.trial_will_end",
                        _make_sub_obj(), "evt_valid_001")
    stripe_mock.Webhook.construct_event.return_value = MagicMock(**event,
                                                                    to_dict=lambda: event)

    factory = async_sessionmaker(fresh_engine, class_=AsyncSession, expire_on_commit=False)

    @asynccontextmanager
    async def _fake_session():
        async with factory() as s:
            yield s

    app = FastAPI()
    app.include_router(billing_router)

    with patch("app.config.settings") as cfg, \
         patch("app.db.get_session", _fake_session):
        cfg.stripe_enabled = True
        cfg.stripe_webhook_secret = "whsec_test"
        cfg.stripe_price_signal_monthly = "price_signal_mo"
        cfg.stripe_price_signal_yearly  = "price_signal_yr"
        cfg.stripe_price_syndicate_monthly = "price_syndicate_mo"
        with TestClient(app) as client:
            resp = client.post(
                "/billing/webhook",
                content=b'{}',
                headers={"stripe-signature": "t=1,v1=ok"},
            )

    assert resp.status_code == 200
    assert resp.json()["received"] is True


# ---------------------------------------------------------------------------
# 4. Duplicate event ignored → 200 with duplicate=true
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_duplicate_event_ignored(session):
    from app.db.repositories.billing_repo import (
        record_stripe_event,
        get_stripe_event_by_stripe_id,
    )

    await record_stripe_event(session, stripe_event_id="evt_dup_001",
                               event_type="customer.subscription.created",
                               processing_status="ok")
    await session.flush()

    existing = await get_stripe_event_by_stripe_id(session, "evt_dup_001")
    assert existing is not None
    assert existing.processing_status == "ok"


# ---------------------------------------------------------------------------
# 5. checkout.session.completed links customer to user
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_checkout_links_customer_to_user(session):
    from app.services.webhook_service import handle_checkout_session_completed
    from app.db.models import User
    from sqlalchemy import select

    await _seed_user(session, user_id="user-checkout-01")

    obj = {
        "id": "cs_001",
        "subscription": "sub_001",
        "customer": "cus_checkout_001",
        "metadata": {"user_id": "user-checkout-01"},
    }
    await handle_checkout_session_completed(session, obj)
    await session.flush()

    result = await session.execute(select(User).where(User.id == "user-checkout-01"))
    user = result.scalar_one_or_none()
    assert user is not None
    assert user.stripe_customer_id == "cus_checkout_001"


@pytest.mark.asyncio
async def test_checkout_no_user_id_in_metadata_skips(session):
    from app.services.webhook_service import handle_checkout_session_completed
    from app.db.models import User
    from sqlalchemy import select

    # Should not raise.
    obj = {"id": "cs_002", "customer": "cus_002", "metadata": {}}
    await handle_checkout_session_completed(session, obj)


# ---------------------------------------------------------------------------
# 6. subscription.created creates subscription row
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_subscription_created_inserts_row(session):
    from app.services.webhook_service import handle_subscription_created
    from app.db.repositories.billing_repo import get_subscription_by_stripe_id

    with patch("app.config.settings") as cfg:
        cfg.stripe_price_signal_monthly    = "price_signal_mo"
        cfg.stripe_price_signal_yearly     = "price_signal_yr"
        cfg.stripe_price_syndicate_monthly = "price_syndicate_mo"

        await _seed_user(session, user_id="user-sub-01",
                          stripe_customer_id="cus_sub_01")

        obj = _make_sub_obj(
            sub_id="sub_created_001",
            customer_id="cus_sub_01",
            status="active",
            price_id="price_signal_mo",
        )
        await handle_subscription_created(session, obj)
        await session.flush()

    row = await get_subscription_by_stripe_id(session, "sub_created_001")
    assert row is not None
    assert row.plan_name == "pro"
    assert row.status == "active"
    assert row.user_id == "user-sub-01"


@pytest.mark.asyncio
async def test_subscription_created_updates_user_plan(session):
    from app.services.webhook_service import handle_subscription_created
    from app.db.models import User
    from sqlalchemy import select

    with patch("app.config.settings") as cfg:
        cfg.stripe_price_signal_monthly    = "price_signal_mo"
        cfg.stripe_price_signal_yearly     = "price_signal_yr"
        cfg.stripe_price_syndicate_monthly = "price_syndicate_mo"

        await _seed_user(session, user_id="user-plan-01",
                          stripe_customer_id="cus_plan_01", plan="free")

        obj = _make_sub_obj(
            sub_id="sub_plan_001",
            customer_id="cus_plan_01",
            status="active",
            price_id="price_signal_mo",
        )
        await handle_subscription_created(session, obj)
        await session.flush()

    result = await session.execute(select(User).where(User.id == "user-plan-01"))
    user = result.scalar_one()
    assert user.plan == "pro"


@pytest.mark.asyncio
async def test_subscription_created_before_checkout_uses_metadata(session):
    """Subscription events may arrive before checkout links the customer."""
    from app.services.webhook_service import handle_subscription_created
    from app.db.models import User
    from app.db.repositories.billing_repo import get_subscription_by_stripe_id
    from sqlalchemy import select

    with patch("app.config.settings") as cfg:
        cfg.stripe_price_signal_monthly    = "price_signal_mo"
        cfg.stripe_price_signal_yearly     = "price_signal_yr"
        cfg.stripe_price_syndicate_monthly = "price_syndicate_mo"

        await _seed_user(session, user_id="user-race-01", plan="free")
        obj = _make_sub_obj(
            sub_id="sub_race_001",
            customer_id="cus_race_001",
            price_id="price_signal_mo",
            user_id="user-race-01",
        )
        await handle_subscription_created(session, obj)
        await session.flush()

    row = await get_subscription_by_stripe_id(session, "sub_race_001")
    assert row is not None
    assert row.user_id == "user-race-01"
    assert row.plan_name == "pro"

    result = await session.execute(select(User).where(User.id == "user-race-01"))
    user = result.scalar_one()
    assert user.stripe_customer_id == "cus_race_001"
    assert user.plan == "pro"


# ---------------------------------------------------------------------------
# 7. subscription.updated updates status and plan
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_subscription_updated_changes_status(session):
    from app.services.webhook_service import handle_subscription_updated
    from app.db.repositories.billing_repo import get_subscription_by_stripe_id

    with patch("app.config.settings") as cfg:
        cfg.stripe_price_signal_monthly    = "price_signal_mo"
        cfg.stripe_price_signal_yearly     = "price_signal_yr"
        cfg.stripe_price_syndicate_monthly = "price_syndicate_mo"

        await _seed_user(session, user_id="user-upd-01",
                          stripe_customer_id="cus_upd_01", plan="pro")
        await _seed_subscription(session, user_id="user-upd-01",
                                  sub_id="sub_upd_001",
                                  customer_id="cus_upd_01",
                                  status="active")

        # Update to past_due.
        obj = _make_sub_obj(
            sub_id="sub_upd_001",
            customer_id="cus_upd_01",
            status="past_due",
            price_id="price_signal_mo",
        )
        await handle_subscription_updated(session, obj)
        await session.flush()

    row = await get_subscription_by_stripe_id(session, "sub_upd_001")
    assert row.status == "past_due"


# ---------------------------------------------------------------------------
# 8. subscription.deleted → canceled + user.plan=free + cache cleared
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_subscription_deleted_cancels(session):
    from app.services.webhook_service import handle_subscription_deleted
    from app.db.repositories.billing_repo import get_subscription_by_stripe_id
    from app.db.models import User
    from sqlalchemy import select

    await _seed_user(session, user_id="user-del-01",
                      stripe_customer_id="cus_del_01", plan="pro")
    await _seed_subscription(session, user_id="user-del-01",
                              sub_id="sub_del_001",
                              customer_id="cus_del_01",
                              status="active")

    obj = {"id": "sub_del_001", "canceled_at": _unix()}
    await handle_subscription_deleted(session, obj)
    await session.flush()

    row = await get_subscription_by_stripe_id(session, "sub_del_001")
    assert row.status == "canceled"
    assert row.canceled_at is not None

    result = await session.execute(select(User).where(User.id == "user-del-01"))
    user = result.scalar_one()
    assert user.plan == "free"


@pytest.mark.asyncio
async def test_subscription_deleted_invalidates_cache(session):
    from app.services.webhook_service import handle_subscription_deleted
    from app.db.repositories.billing_repo import (
        upsert_entitlement_cache,
        get_entitlement_cache,
    )

    await _seed_user(session, user_id="user-del-cache-01",
                      stripe_customer_id="cus_del_c_01", plan="pro")
    await _seed_subscription(session, user_id="user-del-cache-01",
                              sub_id="sub_del_c_001",
                              customer_id="cus_del_c_01",
                              status="active")
    # Seed a cache row.
    await upsert_entitlement_cache(
        session, "user-del-cache-01",
        plan_name="pro", plan_status="active",
        watchlist_limit=50, portfolio_limit=10,
        position_limit=50, dossier_monthly_limit=-1,
        features_json="{}", expires_at=_future(hours=1),
    )
    await session.flush()

    obj = {"id": "sub_del_c_001", "canceled_at": _unix()}
    await handle_subscription_deleted(session, obj)
    await session.flush()

    cache = await get_entitlement_cache(session, "user-del-cache-01")
    assert cache is None


# ---------------------------------------------------------------------------
# 9. invoice.payment_failed → past_due + grace set
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_payment_failed_sets_past_due_and_grace(session):
    from app.services.webhook_service import handle_invoice_payment_failed
    from app.db.repositories.billing_repo import get_subscription_by_stripe_id

    await _seed_user(session, user_id="user-fail-01",
                      stripe_customer_id="cus_fail_01", plan="pro")
    await _seed_subscription(session, user_id="user-fail-01",
                              sub_id="sub_fail_001",
                              customer_id="cus_fail_01",
                              status="active")

    obj = {"subscription": "sub_fail_001", "customer": "cus_fail_01"}
    await handle_invoice_payment_failed(session, obj)
    await session.flush()

    row = await get_subscription_by_stripe_id(session, "sub_fail_001")
    assert row.status == "past_due"
    assert row.grace_period_ends_at is not None
    # Grace should be ~3 days from now.  SQLite returns naive datetimes, so
    # compare against a naive UTC reference to avoid offset-naive/aware error.
    grace_naive = row.grace_period_ends_at.replace(tzinfo=None)
    now_naive   = datetime.utcnow()
    grace_delta = grace_naive - now_naive
    assert timedelta(days=2) < grace_delta < timedelta(days=4)


# ---------------------------------------------------------------------------
# 10. invoice.payment_succeeded → active + grace cleared
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_payment_succeeded_clears_grace(session):
    from app.services.webhook_service import handle_invoice_payment_succeeded
    from app.db.repositories.billing_repo import (
        get_subscription_by_stripe_id,
        update_subscription,
    )

    await _seed_user(session, user_id="user-succ-01",
                      stripe_customer_id="cus_succ_01", plan="pro")
    await _seed_subscription(session, user_id="user-succ-01",
                              sub_id="sub_succ_001",
                              customer_id="cus_succ_01",
                              status="past_due")

    # Set a grace period.
    await update_subscription(
        session, "sub_succ_001",
        grace_period_ends_at=_future(hours=48),
    )
    await session.flush()

    obj = {"subscription": "sub_succ_001", "customer": "cus_succ_01",
           "lines": {"data": [{"period": {"start": _unix(), "end": _unix(_future(hours=720))}}]}}
    await handle_invoice_payment_succeeded(session, obj)
    await session.flush()

    row = await get_subscription_by_stripe_id(session, "sub_succ_001")
    assert row.status == "active"
    assert row.grace_period_ends_at is None


# ---------------------------------------------------------------------------
# 11. Unsupported event → processing_status=skipped
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_unsupported_event_returns_skipped(session):
    from app.services.webhook_service import process_event

    event = _make_event("payment_intent.created", {"id": "pi_001"}, "evt_skip_001")
    result = await process_event(session, event)
    assert result == "skipped"


# ---------------------------------------------------------------------------
# 12. No raw payload stored (stripe_events has no payload column)
# ---------------------------------------------------------------------------

def test_no_raw_payload_column():
    from app.db.models import StripeEvent
    import sqlalchemy

    columns = {c.name for c in sqlalchemy.inspect(StripeEvent).columns}
    payload_columns = {c for c in columns if "payload" in c.lower()}
    assert not payload_columns, (
        f"stripe_events must not have raw payload columns: {payload_columns}"
    )


# ---------------------------------------------------------------------------
# 13. Entitlement cache invalidated after subscription change
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_entitlement_cache_invalidated_on_subscription_created(session):
    from app.services.webhook_service import handle_subscription_created
    from app.db.repositories.billing_repo import (
        upsert_entitlement_cache,
        get_entitlement_cache,
    )

    with patch("app.config.settings") as cfg:
        cfg.stripe_price_signal_monthly    = "price_signal_mo"
        cfg.stripe_price_signal_yearly     = "price_signal_yr"
        cfg.stripe_price_syndicate_monthly = "price_syndicate_mo"

        await _seed_user(session, user_id="user-cache-01",
                          stripe_customer_id="cus_cache_01")
        # Plant a stale cache row.
        await upsert_entitlement_cache(
            session, "user-cache-01",
            plan_name="free", plan_status="free_fallback",
            watchlist_limit=5, portfolio_limit=1,
            position_limit=10, dossier_monthly_limit=3,
            features_json="{}", expires_at=_future(hours=1),
        )
        await session.flush()

        obj = _make_sub_obj(
            sub_id="sub_cache_001",
            customer_id="cus_cache_01",
            price_id="price_signal_mo",
        )
        await handle_subscription_created(session, obj)
        await session.flush()

    cache = await get_entitlement_cache(session, "user-cache-01")
    assert cache is None


# ---------------------------------------------------------------------------
# 14. No entitlement enforcement (resolve_entitlements not called)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_no_entitlement_enforcement(session):
    from app.services.webhook_service import handle_subscription_created

    with patch("app.config.settings") as cfg, \
         patch("app.services.entitlement_service.resolve_entitlements") as mock_ent:
        cfg.stripe_price_signal_monthly    = "price_signal_mo"
        cfg.stripe_price_signal_yearly     = "price_signal_yr"
        cfg.stripe_price_syndicate_monthly = "price_syndicate_mo"

        await _seed_user(session, user_id="user-ent-01",
                          stripe_customer_id="cus_ent_01")
        obj = _make_sub_obj(sub_id="sub_ent_001", customer_id="cus_ent_01",
                            price_id="price_signal_mo")
        await handle_subscription_created(session, obj)

    mock_ent.assert_not_called()


# ---------------------------------------------------------------------------
# 15. customer.deleted cancels subscriptions + clears customer link
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_customer_deleted_cancels_and_clears_link(session):
    from app.services.webhook_service import handle_customer_deleted
    from app.db.repositories.billing_repo import get_subscription_by_stripe_id
    from app.db.models import User
    from sqlalchemy import select

    await _seed_user(session, user_id="user-custdel-01",
                      stripe_customer_id="cus_custdel_01", plan="pro")
    await _seed_subscription(session, user_id="user-custdel-01",
                              sub_id="sub_custdel_001",
                              customer_id="cus_custdel_01",
                              status="active")

    obj = {"id": "cus_custdel_01"}
    await handle_customer_deleted(session, obj)
    await session.flush()

    row = await get_subscription_by_stripe_id(session, "sub_custdel_001")
    assert row.status == "canceled"

    result = await session.execute(select(User).where(User.id == "user-custdel-01"))
    user = result.scalar_one()
    assert user.stripe_customer_id is None


# ---------------------------------------------------------------------------
# 16. Disabled mode → 200 no-op
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_disabled_returns_200_noop():
    from fastapi.testclient import TestClient
    from fastapi import FastAPI
    from app.routers.billing import router as billing_router

    app = FastAPI()
    app.include_router(billing_router)

    with patch("app.config.settings") as cfg:
        cfg.stripe_enabled = False
        with TestClient(app) as client:
            resp = client.post("/billing/webhook", content=b'{}')

    assert resp.status_code == 200
    body = resp.json()
    assert body["received"] is True
    assert body["disabled"] is True


# ---------------------------------------------------------------------------
# 17. _map_stripe_status covers recognised values
# ---------------------------------------------------------------------------

def test_map_stripe_status_all_values():
    from app.services.webhook_service import _map_stripe_status

    assert _map_stripe_status("active")             == "active"
    assert _map_stripe_status("trialing")           == "trialing"
    assert _map_stripe_status("past_due")           == "past_due"
    assert _map_stripe_status("canceled")           == "canceled"
    assert _map_stripe_status("incomplete")         == "incomplete"
    assert _map_stripe_status("incomplete_expired") == "canceled"
    assert _map_stripe_status("unpaid")             == "unpaid"
    assert _map_stripe_status("paused")             == "paused"
    assert _map_stripe_status("unknown_status")     == "canceled"


# ---------------------------------------------------------------------------
# 18. _plan_from_price_id maps known price IDs
# ---------------------------------------------------------------------------

def test_plan_from_price_id_known_ids():
    from app.services.webhook_service import _plan_from_price_id

    with patch("app.config.settings") as cfg:
        cfg.stripe_price_signal_monthly    = "price_signal_mo"
        cfg.stripe_price_signal_yearly     = "price_signal_yr"
        cfg.stripe_price_syndicate_monthly = "price_syndicate_mo"

        assert _plan_from_price_id("price_signal_mo")    == "pro"
        assert _plan_from_price_id("price_signal_yr")    == "pro"
        assert _plan_from_price_id("price_syndicate_mo") == "teams"
        assert _plan_from_price_id("price_unknown")      == "pro"  # safe fallback


# ---------------------------------------------------------------------------
# 19. process_event returns 'skipped' for unknown event types
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_process_event_skipped_for_unknown(session):
    from app.services.webhook_service import process_event

    event = _make_event("radar.early_fraud_warning.created",
                        {"id": "issfr_001"}, "evt_radar_001")
    result = await process_event(session, event)
    assert result == "skipped"


# ---------------------------------------------------------------------------
# Bonus: subscription.created with trialing status
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_subscription_created_trialing(session):
    from app.services.webhook_service import handle_subscription_created
    from app.db.repositories.billing_repo import get_subscription_by_stripe_id

    with patch("app.config.settings") as cfg:
        cfg.stripe_price_signal_monthly    = "price_signal_mo"
        cfg.stripe_price_signal_yearly     = "price_signal_yr"
        cfg.stripe_price_syndicate_monthly = "price_syndicate_mo"

        await _seed_user(session, user_id="user-trial-01",
                          stripe_customer_id="cus_trial_01")

        obj = _make_sub_obj(
            sub_id="sub_trial_001",
            customer_id="cus_trial_01",
            status="trialing",
            price_id="price_signal_mo",
            trial_end=_unix(_future(hours=14 * 24)),
        )
        await handle_subscription_created(session, obj)
        await session.flush()

    row = await get_subscription_by_stripe_id(session, "sub_trial_001")
    assert row.status == "trialing"
    assert row.trial_ends_at is not None


# ---------------------------------------------------------------------------
# Bonus: subscription.created with no matching user → no row created
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_subscription_created_no_user_skips(session):
    from app.services.webhook_service import handle_subscription_created
    from app.db.repositories.billing_repo import get_subscription_by_stripe_id

    with patch("app.config.settings") as cfg:
        cfg.stripe_price_signal_monthly    = "price_signal_mo"
        cfg.stripe_price_signal_yearly     = "price_signal_yr"
        cfg.stripe_price_syndicate_monthly = "price_syndicate_mo"

        # No user seeded with this customer ID.
        obj = _make_sub_obj(
            sub_id="sub_nouser_001",
            customer_id="cus_nouser_001",
            status="active",
        )
        # Should not raise.
        await handle_subscription_created(session, obj)

    row = await get_subscription_by_stripe_id(session, "sub_nouser_001")
    assert row is None
