"""
Stripe Webhook Service — Phase 17 · Slice 4.

Signature verification + event routing + subscription state sync.

No entitlement enforcement.  No billing portal.  No cancellation UI.
No raw Stripe payloads stored (stripe_events table has no payload column).

Supported events:
  checkout.session.completed          → link customer to user
  customer.subscription.created       → create subscription row
  customer.subscription.updated       → update subscription row
  customer.subscription.deleted       → cancel subscription
  invoice.payment_succeeded           → renew period, clear grace
  invoice.payment_failed              → set past_due + grace (3 days)
  customer.subscription.trial_will_end → log only
  customer.deleted                    → cancel subscription, clear customer link

All other events are recorded with processing_status='skipped'.

Handler errors update the stripe_events row to 'error' but never propagate
to the route — the route always returns 200 so Stripe does not retry partially
applied events.  The idempotency pre-check (stripe_event_id UNIQUE) is the
backstop for any race.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

SYSTEM_DEFAULT_USER_ID: str = "00000000-0000-0000-0000-000000000001"
_GRACE_DAYS: int = 3


def _settings():
    from app.config import settings
    return settings


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _ts(unix: Any) -> datetime:
    """Convert a Stripe Unix timestamp to a tz-aware UTC datetime."""
    return datetime.fromtimestamp(int(unix), tz=timezone.utc)


# ---------------------------------------------------------------------------
# Signature verification
# ---------------------------------------------------------------------------

def verify_stripe_signature(
    payload_bytes: bytes,
    sig_header: str,
    secret: str,
) -> Dict[str, Any]:
    """Verify the Stripe-Signature header and return the parsed event dict.

    Raises:
        app.services.stripe_service.StripeDisabledError  — when STRIPE_ENABLED=false
        app.services.stripe_service.StripeMisconfiguredError — when secret is empty
        stripe.error.SignatureVerificationError — when signature is invalid
        ImportError — when stripe package is not installed
    """
    from app.services.stripe_service import StripeDisabledError, StripeMisconfiguredError

    cfg = _settings()
    if not cfg.stripe_enabled:
        raise StripeDisabledError(
            "STRIPE_ENABLED=false — webhook verification not active."
        )
    if not secret:
        raise StripeMisconfiguredError(
            "STRIPE_WEBHOOK_SECRET is empty.  Set it in the Render environment."
        )

    import stripe as _stripe   # noqa: PLC0415
    event = _stripe.Webhook.construct_event(payload_bytes, sig_header, secret)
    if hasattr(event, "to_dict"):
        return event.to_dict()
    return dict(event)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_STRIPE_STATUS_MAP: Dict[str, str] = {
    "active":             "active",
    "trialing":           "trialing",
    "past_due":           "past_due",
    "canceled":           "canceled",
    "incomplete":         "incomplete",
    "incomplete_expired": "canceled",
    "unpaid":             "unpaid",
    "paused":             "paused",
}


def _map_stripe_status(stripe_status: str) -> str:
    return _STRIPE_STATUS_MAP.get(stripe_status, "canceled")


def _billing_interval_from_stripe(interval: str) -> str:
    if interval in ("month", "year"):
        return interval
    return "custom"


def _plan_from_price_id(price_id: str) -> str:
    """Reverse-lookup price_id → plan_name using config.

    Falls back to 'pro' for unknown price IDs — the entitlement service is
    the authoritative source for capabilities; 'pro' is the safer default.
    """
    cfg = _settings()
    if price_id and price_id == cfg.stripe_price_signal_monthly:
        return "pro"
    if price_id and price_id == cfg.stripe_price_signal_yearly:
        return "pro"
    if price_id and price_id == cfg.stripe_price_syndicate_monthly:
        return "teams"
    if price_id:
        logger.warning(
            "[webhook] unknown price_id %.20r — defaulting plan to 'pro'", price_id
        )
    return "pro"


def _extract_subscription_price(sub_obj: dict):
    """Return (price_id, billing_interval) from a Stripe subscription object."""
    try:
        items_data = sub_obj.get("items", {}).get("data", [])
        if items_data:
            price = items_data[0].get("price", {})
            price_id = price.get("id", "")
            interval = price.get("recurring", {}).get("interval", "month")
            return price_id, _billing_interval_from_stripe(interval)
    except Exception:
        pass
    return "", "month"


async def _find_user_id(session, customer_id: str) -> Optional[str]:
    """Look up user_id by stripe_customer_id via billing_repo."""
    if not customer_id:
        return None
    from app.db.repositories.billing_repo import find_user_id_by_stripe_customer_id
    return await find_user_id_by_stripe_customer_id(session, customer_id)


async def _resolve_subscription_user_id(
    session,
    customer_id: str,
    sub_obj: dict,
) -> Optional[str]:
    """Resolve a subscription event to a user despite Stripe event ordering.

    Stripe can deliver ``customer.subscription.*`` before
    ``checkout.session.completed``.  Checkout creation copies ``user_id`` into
    subscription metadata, so use that signed metadata to establish the
    customer link when the checkout event has not done so yet.
    """
    user_id = await _find_user_id(session, customer_id)
    if user_id:
        return user_id

    metadata = sub_obj.get("metadata") or {}
    metadata_user_id = metadata.get("user_id", "") or ""
    if not metadata_user_id or metadata_user_id == SYSTEM_DEFAULT_USER_ID:
        return None

    from app.db.repositories.billing_repo import set_user_stripe_customer_id
    await set_user_stripe_customer_id(
        session,
        metadata_user_id,
        customer_id,
    )

    # Resolve through the persisted customer link so nonexistent or invalid
    # metadata user IDs cannot create orphaned subscription rows.
    return await _find_user_id(session, customer_id)


async def _after_subscription_change(
    session,
    user_id: str,
    plan_name: str,
) -> None:
    """Update users.plan and invalidate entitlement cache for user_id."""
    from app.db.repositories.billing_repo import (
        update_user_plan,
        invalidate_entitlement_cache,
    )
    await update_user_plan(session, user_id, plan_name)
    await invalidate_entitlement_cache(session, user_id)


# ---------------------------------------------------------------------------
# Event handlers
# ---------------------------------------------------------------------------

async def handle_checkout_session_completed(session, obj: dict) -> None:
    """checkout.session.completed — link stripe_customer_id to user.

    Uses metadata.user_id set during checkout creation.
    Subscription row is created by the subsequent customer.subscription.created.
    """
    customer_id = obj.get("customer", "") or ""
    sub_id      = obj.get("subscription", "") or ""
    metadata    = obj.get("metadata") or {}
    user_id     = metadata.get("user_id", "") or ""

    if not customer_id:
        logger.warning("[webhook] checkout.session.completed: no customer_id")
        return

    if not user_id:
        logger.warning(
            "[webhook] checkout.session.completed: no metadata.user_id for customer %s",
            customer_id[:12],
        )
        return

    if user_id == SYSTEM_DEFAULT_USER_ID:
        logger.warning("[webhook] checkout.session.completed: system user blocked")
        return

    from app.db.repositories.billing_repo import set_user_stripe_customer_id
    updated = await set_user_stripe_customer_id(session, user_id, customer_id)
    logger.info(
        "[webhook] checkout.session.completed: customer=%s user=%s sub=%s updated_link=%s",
        customer_id[:12], user_id[:8], sub_id[:12], updated,
    )


async def handle_subscription_created(session, obj: dict) -> None:
    """customer.subscription.created — create or upsert subscription row."""
    sub_id      = obj.get("id", "")
    customer_id = obj.get("customer", "") or ""

    user_id = await _resolve_subscription_user_id(session, customer_id, obj)
    if not user_id:
        logger.warning(
            "[webhook] subscription.created: no user for customer %s — skipping",
            customer_id[:12],
        )
        return

    price_id, interval = _extract_subscription_price(obj)
    plan_name = _plan_from_price_id(price_id)
    status    = _map_stripe_status(obj.get("status", "active"))

    trial_end_ts    = obj.get("trial_end")
    canceled_at_ts  = obj.get("canceled_at")
    period_start_ts = obj.get("current_period_start")
    period_end_ts   = obj.get("current_period_end")

    from app.db.repositories.billing_repo import (
        get_subscription_by_stripe_id,
        create_subscription,
        update_subscription,
    )

    existing = await get_subscription_by_stripe_id(session, sub_id)
    if existing is not None:
        await update_subscription(
            session,
            sub_id,
            status=status,
            stripe_price_id=price_id or None,
            trial_ends_at=_ts(trial_end_ts) if trial_end_ts else None,
            current_period_end=_ts(period_end_ts) if period_end_ts else existing.current_period_end,
        )
    else:
        now = _now()
        await create_subscription(
            session,
            user_id=user_id,
            stripe_subscription_id=sub_id,
            stripe_customer_id=customer_id,
            stripe_price_id=price_id,
            plan_name=plan_name,
            status=status,
            billing_interval=interval,
            current_period_start=_ts(period_start_ts) if period_start_ts else now,
            current_period_end=_ts(period_end_ts) if period_end_ts else now,
            trial_ends_at=_ts(trial_end_ts) if trial_end_ts else None,
            cancel_at_period_end=bool(obj.get("cancel_at_period_end", False)),
            canceled_at=_ts(canceled_at_ts) if canceled_at_ts else None,
        )

    await _after_subscription_change(session, user_id, plan_name)
    logger.info(
        "[webhook] subscription.created: sub=%s user=%s plan=%s status=%s",
        sub_id[:12], user_id[:8], plan_name, status,
    )


async def handle_subscription_updated(session, obj: dict) -> None:
    """customer.subscription.updated — update subscription row fields."""
    sub_id      = obj.get("id", "")
    customer_id = obj.get("customer", "") or ""

    price_id, interval = _extract_subscription_price(obj)
    plan_name = _plan_from_price_id(price_id)
    status    = _map_stripe_status(obj.get("status", "active"))

    trial_end_ts   = obj.get("trial_end")
    canceled_at_ts = obj.get("canceled_at")
    period_end_ts  = obj.get("current_period_end")

    from app.db.repositories.billing_repo import (
        get_subscription_by_stripe_id,
        create_subscription,
        update_subscription,
    )

    existing = await get_subscription_by_stripe_id(session, sub_id)
    if existing is None:
        # Event arrived before subscription.created — upsert.
        user_id = await _resolve_subscription_user_id(session, customer_id, obj)
        if not user_id:
            logger.warning(
                "[webhook] subscription.updated: no user for customer %s", customer_id[:12]
            )
            return
        now = _now()
        await create_subscription(
            session,
            user_id=user_id,
            stripe_subscription_id=sub_id,
            stripe_customer_id=customer_id,
            stripe_price_id=price_id,
            plan_name=plan_name,
            status=status,
            billing_interval=interval,
            current_period_start=now,
            current_period_end=_ts(period_end_ts) if period_end_ts else now,
            trial_ends_at=_ts(trial_end_ts) if trial_end_ts else None,
            cancel_at_period_end=bool(obj.get("cancel_at_period_end", False)),
            canceled_at=_ts(canceled_at_ts) if canceled_at_ts else None,
        )
        user_id_for_cache = user_id
    else:
        await update_subscription(
            session,
            sub_id,
            plan_name=plan_name,
            status=status,
            stripe_price_id=price_id or None,
            current_period_end=_ts(period_end_ts) if period_end_ts else None,
            cancel_at_period_end=bool(obj.get("cancel_at_period_end", False)),
            canceled_at=_ts(canceled_at_ts) if canceled_at_ts else None,
            trial_ends_at=_ts(trial_end_ts) if trial_end_ts else None,
        )
        user_id_for_cache = existing.user_id

    await _after_subscription_change(session, user_id_for_cache, plan_name)
    logger.info(
        "[webhook] subscription.updated: sub=%s plan=%s status=%s",
        sub_id[:12], plan_name, status,
    )


async def handle_subscription_deleted(session, obj: dict) -> None:
    """customer.subscription.deleted — cancel subscription, revert user to free."""
    sub_id         = obj.get("id", "")
    canceled_at_ts = obj.get("canceled_at")

    from app.db.repositories.billing_repo import (
        get_subscription_by_stripe_id,
        update_subscription,
    )

    existing = await get_subscription_by_stripe_id(session, sub_id)
    if existing is None:
        logger.info("[webhook] subscription.deleted: sub %s not found — skipping", sub_id[:12])
        return

    await update_subscription(
        session,
        sub_id,
        status="canceled",
        cancel_at_period_end=False,
        canceled_at=_ts(canceled_at_ts) if canceled_at_ts else _now(),
    )
    user_id = existing.user_id
    await _after_subscription_change(session, user_id, "free")
    logger.info(
        "[webhook] subscription.deleted: sub=%s user=%s → free",
        sub_id[:12], user_id[:8],
    )


async def handle_invoice_payment_succeeded(session, obj: dict) -> None:
    """invoice.payment_succeeded — renew period, clear grace."""
    sub_id = obj.get("subscription", "") or ""
    if not sub_id:
        return

    from app.db.repositories.billing_repo import (
        get_subscription_by_stripe_id,
        invalidate_entitlement_cache,
    )

    existing = await get_subscription_by_stripe_id(session, sub_id)
    if existing is None:
        return

    # Extract new period end from invoice lines when available.
    period_end = None
    try:
        lines = obj.get("lines", {}).get("data", [])
        if lines:
            period_end = lines[0].get("period", {}).get("end")
    except Exception:
        pass

    new_status = "active" if existing.status in ("past_due", "incomplete") else existing.status

    # Directly set fields so we can explicitly clear grace_period_ends_at=None.
    # (update_subscription skips None kwargs and cannot clear a column to NULL.)
    existing.status              = new_status
    existing.grace_period_ends_at = None
    if period_end is not None:
        existing.current_period_end = _ts(period_end)
    existing.updated_at = _now()
    await session.flush()

    await invalidate_entitlement_cache(session, existing.user_id)
    logger.info(
        "[webhook] invoice.payment_succeeded: sub=%s user=%s status=%s",
        sub_id[:12], existing.user_id[:8], new_status,
    )


async def handle_invoice_payment_failed(session, obj: dict) -> None:
    """invoice.payment_failed — set past_due + 3-day grace period."""
    sub_id = obj.get("subscription", "") or ""
    if not sub_id:
        return

    from app.db.repositories.billing_repo import (
        get_subscription_by_stripe_id,
        update_subscription,
        invalidate_entitlement_cache,
    )

    existing = await get_subscription_by_stripe_id(session, sub_id)
    if existing is None:
        return

    grace_end = _now() + timedelta(days=_GRACE_DAYS)
    await update_subscription(
        session,
        sub_id,
        status="past_due",
        grace_period_ends_at=grace_end,
    )
    await invalidate_entitlement_cache(session, existing.user_id)
    logger.info(
        "[webhook] invoice.payment_failed: sub=%s user=%s grace_until=%s",
        sub_id[:12], existing.user_id[:8], grace_end.isoformat(),
    )


async def handle_trial_will_end(session, obj: dict) -> None:
    """customer.subscription.trial_will_end — log only, no state change."""
    sub_id = obj.get("id", "")
    logger.info("[webhook] trial_will_end: sub=%s — no action required", sub_id[:12])


async def handle_customer_deleted(session, obj: dict) -> None:
    """customer.deleted — cancel subscriptions and clear customer link."""
    customer_id = obj.get("id", "") or ""
    if not customer_id:
        return

    user_id = await _find_user_id(session, customer_id)
    if not user_id:
        logger.info("[webhook] customer.deleted: no user for customer %s", customer_id[:12])
        return

    from app.db.repositories.billing_repo import (
        list_subscriptions_by_user,
        update_subscription,
        invalidate_entitlement_cache,
    )
    from app.db.models import User
    from sqlalchemy import select

    subs = await list_subscriptions_by_user(session, user_id)
    active_statuses = {"active", "trialing", "past_due", "paused", "incomplete"}
    for sub in subs:
        if sub.status in active_statuses:
            await update_subscription(
                session,
                sub.stripe_subscription_id,
                status="canceled",
                canceled_at=_now(),
            )

    result = await session.execute(select(User).where(User.id == user_id))
    user_row = result.scalar_one_or_none()
    if user_row:
        user_row.stripe_customer_id = None
        await session.flush()

    await invalidate_entitlement_cache(session, user_id)
    logger.info("[webhook] customer.deleted: user=%s subscriptions canceled", user_id[:8])


# ---------------------------------------------------------------------------
# Event router
# ---------------------------------------------------------------------------

_HANDLERS = {
    "checkout.session.completed":          handle_checkout_session_completed,
    "customer.subscription.created":       handle_subscription_created,
    "customer.subscription.updated":       handle_subscription_updated,
    "customer.subscription.deleted":       handle_subscription_deleted,
    "invoice.payment_succeeded":           handle_invoice_payment_succeeded,
    "invoice.payment_failed":              handle_invoice_payment_failed,
    "customer.subscription.trial_will_end": handle_trial_will_end,
    "customer.deleted":                    handle_customer_deleted,
}


async def process_event(session, event: Dict[str, Any]) -> str:
    """Route a verified Stripe event dict to its handler.

    Returns:
        "ok"      — event was handled successfully
        "skipped" — event type is not supported (safely ignored)

    Raises:
        Any exception from the handler (caller should catch and record error).
    """
    event_type = event.get("type", "")
    obj        = event.get("data", {}).get("object", {})

    handler = _HANDLERS.get(event_type)
    if handler is None:
        logger.debug("[webhook] unsupported event type %r — skipping", event_type)
        return "skipped"

    await handler(session, obj)
    return "ok"
