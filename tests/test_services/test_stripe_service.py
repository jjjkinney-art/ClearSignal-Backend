"""
Phase 17 · Slice 3 — Stripe service + checkout route tests.

All tests operate with STRIPE_ENABLED=false (default) or patch stripe at the
sys.modules level so the real SDK is never required.  No outbound network
calls.  No Stripe test keys needed.

Validates:
  1.  Disabled mode — no Stripe calls, returns disabled indicator
  2.  Invalid plan rejected by resolve_price_id
  3.  Invalid interval rejected by resolve_price_id
  4.  Valid plan+interval resolves correctly (mocked config)
  5.  Teams plan has no yearly price (raises InvalidPlanError)
  6.  Customer creation is idempotent (search before create)
  7.  Checkout session creation (full mocked Stripe path)
  8.  System user rejected by create_checkout_session
  9.  System user rejected by checkout route (400)
  10. Missing success URL raises StripeMisconfiguredError
  11. Missing cancel URL raises StripeMisconfiguredError
  12. No entitlement changes from checkout
  13. No webhook behavior in this module
  14. POST /billing/checkout returns 503 when STRIPE_ENABLED=false
  15. POST /billing/checkout rejects unknown plan with 422
  16. POST /billing/checkout rejects unknown interval with 422
  17. StripeDisabledError raised when create_checkout_session called while disabled
"""

from __future__ import annotations

import sys
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
import pytest


# ---------------------------------------------------------------------------
# Stripe mock — injected into sys.modules so lazy `import stripe` in the
# service resolves to our mock without installing the real package.
# ---------------------------------------------------------------------------

def _make_stripe_mock() -> MagicMock:
    """Build a minimal stripe module mock."""
    m = MagicMock()

    # stripe.Customer.search() returns empty list by default.
    m.Customer.search.return_value = MagicMock(data=[])

    # stripe.Customer.create() returns a mock customer.
    _cus = MagicMock()
    _cus.id = "cus_test_mock_001"
    m.Customer.create.return_value = _cus

    # stripe.checkout.Session.create() returns a mock session.
    _sess = MagicMock()
    _sess.id  = "cs_test_mock_001"
    _sess.url = "https://checkout.stripe.com/pay/cs_test_mock_001"
    m.checkout.Session.create.return_value = _sess

    return m


@pytest.fixture()
def stripe_mock():
    """Inject a mock stripe module and remove it after the test."""
    mock = _make_stripe_mock()
    sys.modules["stripe"] = mock
    yield mock
    sys.modules.pop("stripe", None)


# ---------------------------------------------------------------------------
# Settings patches
# ---------------------------------------------------------------------------

_DISABLED_SETTINGS = {
    "stripe_enabled":                False,
    "stripe_secret_key":             "",
    "stripe_price_signal_monthly":   "",
    "stripe_price_signal_yearly":    "",
    "stripe_price_syndicate_monthly": "",
    "stripe_success_url":            "",
    "stripe_cancel_url":             "",
}

_ENABLED_SETTINGS = {
    "stripe_enabled":                True,
    "stripe_secret_key":             "sk_test_dummy_key",
    "stripe_price_signal_monthly":   "price_signal_mo_test",
    "stripe_price_signal_yearly":    "price_signal_yr_test",
    "stripe_price_syndicate_monthly": "price_syndicate_mo_test",
    "stripe_success_url":            "https://example.com/billing/success",
    "stripe_cancel_url":             "https://example.com/billing/cancel",
}


def _patch_settings(overrides: dict):
    """Return a context manager that patches app.services.stripe_service._settings."""
    mock_cfg = MagicMock()
    for k, v in overrides.items():
        setattr(mock_cfg, k, v)
    return patch("app.services.stripe_service._settings", return_value=mock_cfg)


# ---------------------------------------------------------------------------
# 1. Disabled mode — create_checkout_session returns disabled dict, no Stripe call
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_disabled_mode_no_stripe_calls(stripe_mock):
    from app.services.stripe_service import create_checkout_session

    with _patch_settings(_DISABLED_SETTINGS):
        result = await create_checkout_session("user-001", "pro", "month")

    assert result["disabled"] is True
    assert result["checkout_url"] is None
    assert result["reason"] == "stripe_disabled"

    # Stripe SDK must not have been touched at all.
    stripe_mock.Customer.search.assert_not_called()
    stripe_mock.Customer.create.assert_not_called()
    stripe_mock.checkout.Session.create.assert_not_called()


# ---------------------------------------------------------------------------
# 2. Invalid plan rejected
# ---------------------------------------------------------------------------

def test_invalid_plan_rejected():
    from app.services.stripe_service import resolve_price_id, InvalidPlanError

    with _patch_settings(_ENABLED_SETTINGS):
        with pytest.raises(InvalidPlanError, match="Unknown plan"):
            resolve_price_id("enterprise", "month")


# ---------------------------------------------------------------------------
# 3. Invalid interval rejected
# ---------------------------------------------------------------------------

def test_invalid_interval_rejected():
    from app.services.stripe_service import resolve_price_id, InvalidPlanError

    with _patch_settings(_ENABLED_SETTINGS):
        with pytest.raises(InvalidPlanError, match="Unknown interval"):
            resolve_price_id("pro", "week")


# ---------------------------------------------------------------------------
# 4. Valid plan+interval resolves correctly
# ---------------------------------------------------------------------------

def test_valid_plan_interval_resolves():
    from app.services.stripe_service import resolve_price_id

    with _patch_settings(_ENABLED_SETTINGS):
        assert resolve_price_id("pro",   "month") == "price_signal_mo_test"
        assert resolve_price_id("pro",   "year")  == "price_signal_yr_test"
        assert resolve_price_id("teams", "month") == "price_syndicate_mo_test"


# ---------------------------------------------------------------------------
# 5. Teams + year has no mapping
# ---------------------------------------------------------------------------

def test_teams_yearly_not_supported():
    from app.services.stripe_service import resolve_price_id, InvalidPlanError

    with _patch_settings(_ENABLED_SETTINGS):
        with pytest.raises(InvalidPlanError, match="No price mapping"):
            resolve_price_id("teams", "year")


# ---------------------------------------------------------------------------
# 6. Customer creation is idempotent — search before create
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_customer_creation_idempotent_existing(stripe_mock):
    """When a customer already exists in Stripe, create is NOT called."""
    from app.services.stripe_service import create_or_get_customer

    # Simulate an existing customer found by search.
    existing = MagicMock()
    existing.id = "cus_existing_001"
    stripe_mock.Customer.search.return_value = MagicMock(data=[existing])

    with _patch_settings(_ENABLED_SETTINGS):
        cus_id = await create_or_get_customer("user-idem-001")

    assert cus_id == "cus_existing_001"
    stripe_mock.Customer.create.assert_not_called()


@pytest.mark.asyncio
async def test_customer_creation_new_when_not_found(stripe_mock):
    """When no existing customer, Customer.create is called."""
    from app.services.stripe_service import create_or_get_customer

    stripe_mock.Customer.search.return_value = MagicMock(data=[])

    with _patch_settings(_ENABLED_SETTINGS):
        cus_id = await create_or_get_customer("user-new-001", email="test@example.com")

    assert cus_id == "cus_test_mock_001"
    stripe_mock.Customer.create.assert_called_once()
    call_kwargs = stripe_mock.Customer.create.call_args.kwargs
    assert call_kwargs["metadata"]["user_id"] == "user-new-001"
    assert call_kwargs["email"] == "test@example.com"


@pytest.mark.asyncio
async def test_retrieve_active_subscription_for_customer(stripe_mock):
    from app.services.stripe_service import retrieve_active_subscription_for_customer

    canceled = MagicMock(status="canceled")
    active = MagicMock(status="active")
    active.to_dict_recursive.return_value = {
        "id": "sub_active_001",
        "customer": "cus_existing_001",
        "status": "active",
    }
    stripe_mock.Subscription.list.return_value = MagicMock(
        data=[canceled, active]
    )

    with _patch_settings(_ENABLED_SETTINGS):
        result = await retrieve_active_subscription_for_customer(
            "cus_existing_001"
        )

    assert result["id"] == "sub_active_001"
    stripe_mock.Subscription.list.assert_called_once_with(
        customer="cus_existing_001",
        status="all",
        limit=10,
    )


# ---------------------------------------------------------------------------
# 7. Checkout session creation (full mocked Stripe path)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_checkout_session_created(stripe_mock):
    """create_checkout_session returns checkout_url and session_id."""
    from app.services.stripe_service import create_checkout_session

    stripe_mock.Customer.search.return_value = MagicMock(data=[])

    with _patch_settings(_ENABLED_SETTINGS):
        result = await create_checkout_session("user-chk-001", "pro", "month")

    assert result["disabled"] is False
    assert result["checkout_url"] == "https://checkout.stripe.com/pay/cs_test_mock_001"
    assert result["session_id"] == "cs_test_mock_001"

    # Verify Session.create was called with correct price and URLs.
    stripe_mock.checkout.Session.create.assert_called_once()
    call_kwargs = stripe_mock.checkout.Session.create.call_args.kwargs
    assert call_kwargs["mode"] == "subscription"
    assert call_kwargs["line_items"][0]["price"] == "price_signal_mo_test"
    assert call_kwargs["success_url"] == "https://example.com/billing/success"
    assert call_kwargs["cancel_url"]  == "https://example.com/billing/cancel"
    assert call_kwargs["metadata"]["user_id"] == "user-chk-001"
    assert call_kwargs["metadata"]["plan"]     == "pro"
    assert call_kwargs["metadata"]["interval"] == "month"


@pytest.mark.asyncio
async def test_checkout_session_yearly(stripe_mock):
    """Yearly plan resolves to the annual price ID."""
    from app.services.stripe_service import create_checkout_session

    stripe_mock.Customer.search.return_value = MagicMock(data=[])

    with _patch_settings(_ENABLED_SETTINGS):
        result = await create_checkout_session("user-yr-001", "pro", "year")

    call_kwargs = stripe_mock.checkout.Session.create.call_args.kwargs
    assert call_kwargs["line_items"][0]["price"] == "price_signal_yr_test"
    assert result["disabled"] is False


# ---------------------------------------------------------------------------
# 8. System user rejected by create_checkout_session
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_system_user_rejected_by_service(stripe_mock):
    from app.services.stripe_service import (
        create_checkout_session,
        SYSTEM_DEFAULT_USER_ID,
    )

    with _patch_settings(_ENABLED_SETTINGS):
        with pytest.raises(ValueError, match="System user"):
            await create_checkout_session(SYSTEM_DEFAULT_USER_ID, "pro", "month")

    stripe_mock.checkout.Session.create.assert_not_called()


# ---------------------------------------------------------------------------
# 9. System user rejected by create_or_get_customer (returns None)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_system_user_customer_skipped(stripe_mock):
    from app.services.stripe_service import (
        create_or_get_customer,
        SYSTEM_DEFAULT_USER_ID,
    )

    with _patch_settings(_ENABLED_SETTINGS):
        result = await create_or_get_customer(SYSTEM_DEFAULT_USER_ID)

    assert result is None
    stripe_mock.Customer.search.assert_not_called()
    stripe_mock.Customer.create.assert_not_called()


# ---------------------------------------------------------------------------
# 10. Missing success URL raises StripeMisconfiguredError
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_missing_success_url_raises(stripe_mock):
    from app.services.stripe_service import (
        create_checkout_session,
        StripeMisconfiguredError,
    )

    settings = {**_ENABLED_SETTINGS, "stripe_success_url": ""}

    with _patch_settings(settings):
        with pytest.raises(StripeMisconfiguredError, match="STRIPE_SUCCESS_URL"):
            await create_checkout_session("user-url-001", "pro", "month")

    stripe_mock.checkout.Session.create.assert_not_called()


# ---------------------------------------------------------------------------
# 11. Missing cancel URL raises StripeMisconfiguredError
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_missing_cancel_url_raises(stripe_mock):
    from app.services.stripe_service import (
        create_checkout_session,
        StripeMisconfiguredError,
    )

    settings = {**_ENABLED_SETTINGS, "stripe_cancel_url": ""}

    with _patch_settings(settings):
        with pytest.raises(StripeMisconfiguredError, match="STRIPE_CANCEL_URL"):
            await create_checkout_session("user-url-002", "pro", "month")

    stripe_mock.checkout.Session.create.assert_not_called()


# ---------------------------------------------------------------------------
# 12. No entitlement changes from checkout (entitlement_service not touched)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_no_entitlement_changes(stripe_mock):
    """create_checkout_session must not import or call entitlement_service."""
    from app.services.stripe_service import create_checkout_session

    # Patch entitlement_service to detect any accidental call.
    with patch("app.services.entitlement_service.resolve_entitlements") as mock_ent:
        with _patch_settings(_DISABLED_SETTINGS):
            await create_checkout_session("user-ent-001", "pro", "month")

    mock_ent.assert_not_called()


# ---------------------------------------------------------------------------
# 13. No webhook behavior in stripe_service module
# ---------------------------------------------------------------------------

def test_no_webhook_handling_in_module():
    """stripe_service must not define any webhook handler functions."""
    import app.services.stripe_service as svc
    import inspect

    webhook_names = [
        name for name, _ in inspect.getmembers(svc, inspect.isfunction)
        if "webhook" in name.lower() or "event" in name.lower()
    ]
    assert not webhook_names, (
        f"Unexpected webhook/event functions in stripe_service: {webhook_names}"
    )


# ---------------------------------------------------------------------------
# 14. POST /billing/checkout → 503 when STRIPE_ENABLED=false
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_checkout_route_disabled():
    """When STRIPE_ENABLED=false the route returns 503 without touching Stripe."""
    from fastapi.testclient import TestClient
    from fastapi import FastAPI
    from app.routers.billing import router as billing_router

    app = FastAPI()
    app.include_router(billing_router)

    with patch("app.config.settings") as mock_cfg:
        mock_cfg.stripe_enabled = False
        with TestClient(app) as client:
            resp = client.post(
                "/billing/checkout",
                json={"plan": "pro", "interval": "month"},
            )

    assert resp.status_code == 503
    body = resp.json()
    assert body["disabled"] is True
    assert body["reason"] == "stripe_disabled"
    assert body["checkout_url"] is None


# ---------------------------------------------------------------------------
# 15. POST /billing/checkout → 422 on invalid plan
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_checkout_route_invalid_plan():
    from fastapi.testclient import TestClient
    from fastapi import FastAPI
    from app.routers.billing import router as billing_router

    app = FastAPI()
    app.include_router(billing_router)

    with TestClient(app) as client:
        resp = client.post(
            "/billing/checkout",
            json={"plan": "enterprise", "interval": "month"},
        )

    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# 16. POST /billing/checkout → 422 on invalid interval
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_checkout_route_invalid_interval():
    from fastapi.testclient import TestClient
    from fastapi import FastAPI
    from app.routers.billing import router as billing_router

    app = FastAPI()
    app.include_router(billing_router)

    with TestClient(app) as client:
        resp = client.post(
            "/billing/checkout",
            json={"plan": "pro", "interval": "weekly"},
        )

    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# 17. StripeDisabledError raised when calling create_checkout_session while disabled
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_stripe_disabled_error_raised_directly():
    """_require_stripe raises StripeDisabledError when stripe_enabled=False."""
    from app.services.stripe_service import _require_stripe, StripeDisabledError

    with _patch_settings(_DISABLED_SETTINGS):
        with pytest.raises(StripeDisabledError):
            _require_stripe()
