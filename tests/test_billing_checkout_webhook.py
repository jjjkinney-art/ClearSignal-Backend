"""Billing checkout + webhook tests — beta milestone 6.

Covers the two scenarios the existing billing suites did not:
  * router-level /billing/checkout: blocked for the system user, creates a
    session for an authenticated user (Stripe SDK mocked),
  * /billing/webhook: verified event updates subscription state, and a duplicate
    delivery of the same event is idempotent.

No real Stripe keys are used.  Only the crypto boundary is mocked
(verify_stripe_signature) and the checkout-session creation
(create_checkout_session); the real process_event + billing_repo run against a
temp-file SQLite DB via the real app.db.get_session, so persistence and the
stripe_events idempotency constraint are genuinely exercised.

No secrets, webhook payloads, or key material are logged or asserted on.
Runs on Python 3.9.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import tempfile
import time
from types import SimpleNamespace
from unittest.mock import patch

import pytest

SYSTEM_UID = "00000000-0000-0000-0000-000000000001"
_USER = "user-chk-1"
_CUSTOMER = "cus_test_1"


# ---------------------------------------------------------------------------
# Harness
# ---------------------------------------------------------------------------

class _FakeRequest:
    def __init__(self, *, user_id=None, body: bytes = b"{}", sig: str = "sig_test"):
        self.state = SimpleNamespace(user_id=user_id)
        self.headers = {"stripe-signature": sig}
        self._body = body

    async def body(self) -> bytes:
        return self._body


@contextlib.contextmanager
def _settings(**overrides):
    from app.config import settings
    saved = {k: getattr(settings, k) for k in overrides}
    for k, v in overrides.items():
        object.__setattr__(settings, k, v)
    try:
        yield
    finally:
        for k, v in saved.items():
            object.__setattr__(settings, k, v)


async def _with_db(fn):
    from app.db.connection import init_db, close_db
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        await init_db(f"sqlite+aiosqlite:///{path}")
        return await fn()
    finally:
        await close_db()
        try:
            os.unlink(path)
        except OSError:
            pass


def _run(fn):
    asyncio.run(_with_db(fn))


async def _seed_user_with_customer(user_id: str = _USER, customer_id: str = _CUSTOMER):
    from app.db.connection import get_session
    from app.db.models import User
    async with get_session() as db:
        db.add(User(id=user_id, email=f"{user_id}@t.co", plan="free",
                    stripe_customer_id=customer_id))


def _sub_event(evt_id: str, sub_id: str = "sub_test_1"):
    now = int(time.time())
    return {
        "id": evt_id,
        "type": "customer.subscription.created",
        "data": {"object": {
            "id": sub_id,
            "customer": _CUSTOMER,
            "status": "active",
            "items": {"data": [{"price": {"id": "price_signal_mo",
                                          "recurring": {"interval": "month"}}}]},
            "current_period_start": now,
            "current_period_end": now + 30 * 24 * 3600,
        }},
    }


# ═══════════════════════════════════════════════════════════════════════════
# Checkout
# ═══════════════════════════════════════════════════════════════════════════

def test_checkout_disabled_returns_503():
    from app.routers.billing import billing_checkout, CheckoutRequest
    from fastapi.responses import JSONResponse

    async def scenario():
        with _settings(stripe_enabled=False):
            resp = await billing_checkout(
                CheckoutRequest(plan="pro", interval="month"),
                _FakeRequest(user_id=_USER),
            )
        assert isinstance(resp, JSONResponse) and resp.status_code == 503
    asyncio.run(scenario())


def test_checkout_blocked_for_system_user():
    from app.routers.billing import billing_checkout, CheckoutRequest
    from fastapi import HTTPException

    async def scenario():
        with _settings(stripe_enabled=True):
            with pytest.raises(HTTPException) as ei:
                await billing_checkout(
                    CheckoutRequest(plan="pro", interval="month"),
                    _FakeRequest(user_id=SYSTEM_UID),
                )
        assert ei.value.status_code == 400
    asyncio.run(scenario())


def test_checkout_requires_authentication():
    from app.routers.billing import billing_checkout, CheckoutRequest
    from fastapi import HTTPException

    async def scenario():
        with _settings(stripe_enabled=True):
            with pytest.raises(HTTPException) as ei:
                await billing_checkout(
                    CheckoutRequest(plan="pro", interval="month"),
                    _FakeRequest(user_id=None),
                )
        assert ei.value.status_code == 401
    asyncio.run(scenario())


def test_checkout_authenticated_creates_session():
    from app.routers.billing import billing_checkout, CheckoutRequest

    async def scenario():
        fake_result = {"disabled": False,
                       "checkout_url": "https://checkout.stripe.com/c/test",
                       "session_id": "cs_test_123"}
        with _settings(stripe_enabled=True):
            with patch("app.services.stripe_service.create_checkout_session",
                       return_value=fake_result) as m:
                result = await billing_checkout(
                    CheckoutRequest(plan="pro", interval="month"),
                    _FakeRequest(user_id=_USER),
                )
        assert result["checkout_url"] == "https://checkout.stripe.com/c/test"
        assert result["session_id"] == "cs_test_123"
        # the router passed through the authenticated user, never the system user
        assert m.call_args.kwargs.get("user_id") == _USER
    asyncio.run(scenario())


# ═══════════════════════════════════════════════════════════════════════════
# Webhook — state update + idempotency
# ═══════════════════════════════════════════════════════════════════════════

def test_webhook_disabled_is_noop():
    from app.routers.billing import billing_webhook
    from fastapi.responses import JSONResponse

    async def scenario():
        with _settings(stripe_enabled=False):
            resp = await billing_webhook(_FakeRequest())
        assert isinstance(resp, JSONResponse) and resp.status_code == 200
    asyncio.run(scenario())


def test_webhook_updates_subscription_state():
    from app.routers.billing import billing_webhook
    from app.db.connection import get_session
    from app.db.repositories.billing_repo import get_subscription_by_stripe_id

    async def scenario():
        await _seed_user_with_customer()
        event = _sub_event("evt_state_1", "sub_state_1")
        with _settings(stripe_enabled=True, stripe_webhook_secret="whsec_test"):
            with patch("app.services.webhook_service.verify_stripe_signature",
                       return_value=event):
                resp = await billing_webhook(_FakeRequest())
        assert resp.status_code == 200
        # a subscription row now exists for the event's subscription id
        async with get_session() as db:
            sub = await get_subscription_by_stripe_id(db, "sub_state_1")
        assert sub is not None
        assert sub.user_id == _USER
        assert sub.status == "active"

    _run(scenario)


def test_webhook_duplicate_is_idempotent():
    from app.routers.billing import billing_webhook
    from app.db.connection import get_session
    from app.db.repositories.billing_repo import list_subscriptions_by_user

    async def scenario():
        await _seed_user_with_customer()
        event = _sub_event("evt_dup_1", "sub_dup_1")
        with _settings(stripe_enabled=True, stripe_webhook_secret="whsec_test"):
            with patch("app.services.webhook_service.verify_stripe_signature",
                       return_value=event):
                first = await billing_webhook(_FakeRequest())
                second = await billing_webhook(_FakeRequest())

        import json
        first_body = json.loads(bytes(first.body).decode())
        second_body = json.loads(bytes(second.body).decode())
        assert first.status_code == 200 and second.status_code == 200
        assert first_body.get("duplicate") is not True
        assert second_body.get("duplicate") is True

        # exactly one subscription row despite two deliveries
        async with get_session() as db:
            subs = await list_subscriptions_by_user(db, _USER)
        assert len([s for s in subs if s.stripe_subscription_id == "sub_dup_1"]) == 1

    _run(scenario)


def test_webhook_missing_signature_returns_400():
    from app.routers.billing import billing_webhook
    from fastapi import HTTPException

    async def scenario():
        with _settings(stripe_enabled=True, stripe_webhook_secret="whsec_test"):
            with pytest.raises(HTTPException) as ei:
                await billing_webhook(_FakeRequest(sig=""))
        assert ei.value.status_code == 400
    asyncio.run(scenario())
