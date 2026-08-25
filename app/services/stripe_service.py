"""
Stripe Service — Phase 17 · Slice 3.

Wraps Stripe API calls behind the STRIPE_ENABLED flag.  When the flag is
False (the default throughout all Phase 17 build slices), every function
returns a disabled indicator and makes zero outbound calls.

No webhook handling.  No billing portal.  No subscription activation.
No entitlement enforcement.  Those belong in later slices.

Stripe SDK is imported lazily inside functions — it is never imported at
module level.  This means:
  * Tests can patch stripe without installing the real SDK.
  * STRIPE_ENABLED=false processes never pull stripe into memory.
  * Import errors are raised at call time with a clear message, not at
    startup — a missing SDK key does not prevent the server from booting.

Plan → Price mapping (from config):
  pro   + month → STRIPE_PRICE_SIGNAL_MONTHLY
  pro   + year  → STRIPE_PRICE_SIGNAL_YEARLY
  teams + month → STRIPE_PRICE_SYNDICATE_MONTHLY

SYSTEM_DEFAULT_USER_ID is exempt: calling create_checkout_session for the
system user raises ValueError (system user has no billing identity).
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

SYSTEM_DEFAULT_USER_ID = "00000000-0000-0000-0000-000000000001"

# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class StripeDisabledError(Exception):
    """Raised when a Stripe function is called while STRIPE_ENABLED=false."""


class StripeMisconfiguredError(Exception):
    """Raised when required Stripe config values are empty at call time."""


class InvalidPlanError(ValueError):
    """Raised when the plan+interval combination has no price mapping."""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _settings():
    from app.config import settings
    return settings


def _require_stripe():
    """Return the configured stripe module, or raise.

    Raises StripeDisabledError when STRIPE_ENABLED=false.
    Raises StripeMisconfiguredError when STRIPE_SECRET_KEY is empty.
    Raises ImportError when the stripe package is not installed.
    """
    cfg = _settings()
    if not cfg.stripe_enabled:
        raise StripeDisabledError(
            "STRIPE_ENABLED=false — no outbound Stripe calls allowed."
        )
    import stripe as _stripe   # noqa: PLC0415  (intentionally late import)
    secret = cfg.stripe_secret_key
    if not secret:
        raise StripeMisconfiguredError(
            "STRIPE_SECRET_KEY is empty. Set it in the Render environment "
            "before enabling STRIPE_ENABLED=true."
        )
    _stripe.api_key = secret
    return _stripe


# ---------------------------------------------------------------------------
# Plan → Price ID mapping
# ---------------------------------------------------------------------------

# Supported (plan_name, billing_interval) pairs and their config attribute.
_PRICE_CONFIG_ATTR: Dict[tuple, str] = {
    ("pro",   "month"): "stripe_price_signal_monthly",
    ("pro",   "year"):  "stripe_price_signal_yearly",
    ("teams", "month"): "stripe_price_syndicate_monthly",
}

VALID_PLANS = {"pro", "teams"}
VALID_INTERVALS = {"month", "year"}


def resolve_price_id(plan: str, interval: str) -> str:
    """Return the Stripe Price ID for a given plan + interval.

    Raises InvalidPlanError when the combination is not supported.
    Raises StripeMisconfiguredError when the price ID env var is empty.
    """
    if plan not in VALID_PLANS:
        raise InvalidPlanError(
            f"Unknown plan {plan!r}. Supported: {sorted(VALID_PLANS)}"
        )
    if interval not in VALID_INTERVALS:
        raise InvalidPlanError(
            f"Unknown interval {interval!r}. Supported: {sorted(VALID_INTERVALS)}"
        )
    key = (plan, interval)
    attr = _PRICE_CONFIG_ATTR.get(key)
    if attr is None:
        raise InvalidPlanError(
            f"No price mapping for plan={plan!r} interval={interval!r}. "
            f"Supported combinations: {sorted(_PRICE_CONFIG_ATTR)}"
        )
    cfg = _settings()
    price_id: str = getattr(cfg, attr, "")
    if not price_id:
        raise StripeMisconfiguredError(
            f"{attr.upper()} is empty. Set it in the Render environment "
            "before enabling STRIPE_ENABLED=true."
        )
    return price_id


async def retrieve_active_subscription_for_customer(
    customer_id: str,
) -> Optional[Dict[str, Any]]:
    """Return the newest entitlement-bearing Stripe subscription for a customer.

    This is a recovery read used when checkout linked ``users.stripe_customer_id``
    but a delayed, reordered, or previously acknowledged webhook did not create
    the local subscription row.  Stripe remains the source of truth; callers can
    feed the returned snapshot through the normal idempotent webhook upsert.
    """
    if not customer_id:
        return None

    stripe = _require_stripe()
    response = stripe.Subscription.list(
        customer=customer_id,
        status="all",
        limit=10,
    )
    entitlement_statuses = {"active", "trialing", "past_due", "paused"}
    for subscription in response.data:
        if getattr(subscription, "status", None) not in entitlement_statuses:
            continue
        if hasattr(subscription, "to_dict_recursive"):
            return subscription.to_dict_recursive()
        if hasattr(subscription, "to_dict"):
            return subscription.to_dict()
        return dict(subscription)
    return None


# ---------------------------------------------------------------------------
# § create_or_get_customer
# ---------------------------------------------------------------------------

async def create_or_get_customer(
    user_id: str,
    email: Optional[str] = None,
) -> Optional[str]:
    """Return the Stripe Customer ID for user_id, creating one if needed.

    When STRIPE_ENABLED=false: returns None immediately (no-op).
    When the system user is passed: returns None (system user has no billing).

    Idempotent: searches existing customers by metadata.user_id before
    creating.  This prevents duplicate customer records on retries.

    Returns:
        Stripe Customer ID string (e.g. "cus_..."), or None when disabled.
    Raises:
        StripeDisabledError   — when called while disabled (caller should check)
        StripeMisconfiguredError — when STRIPE_SECRET_KEY is missing
        stripe.error.StripeError — on Stripe API errors (propagated)
    """
    cfg = _settings()
    if not cfg.stripe_enabled:
        return None

    if user_id == SYSTEM_DEFAULT_USER_ID:
        logger.debug("[stripe] create_or_get_customer: system user skipped")
        return None

    stripe = _require_stripe()

    # Search by metadata — idempotency key for customer creation.
    try:
        existing = stripe.Customer.search(
            query=f'metadata["user_id"]:"{user_id}"',
            limit=1,
        )
        if existing.data:
            cus_id: str = existing.data[0].id
            logger.debug("[stripe] existing customer %s for user %s", cus_id[:10], user_id[:8])
            return cus_id
    except Exception as exc:
        logger.warning("[stripe] customer search failed (non-fatal): %r", exc)

    # Create new customer.
    params: Dict[str, Any] = {
        "metadata": {"user_id": user_id},
    }
    if email:
        params["email"] = email

    customer = stripe.Customer.create(**params)
    cus_id = customer.id
    logger.info("[stripe] created customer %s for user %s", cus_id[:10], user_id[:8])
    return cus_id


# ---------------------------------------------------------------------------
# § create_checkout_session
# ---------------------------------------------------------------------------

async def create_checkout_session(
    user_id: str,
    plan: str,
    interval: str,
    email: Optional[str] = None,
    trial_days: Optional[int] = None,
) -> Dict[str, Any]:
    """Create a Stripe Checkout Session for user_id subscribing to plan/interval.

    When STRIPE_ENABLED=false:
        Returns {"disabled": True, "checkout_url": None, "reason": "stripe_disabled"}
        No outbound calls are made.

    When STRIPE_ENABLED=true:
        1. Validates plan + interval (raises InvalidPlanError on bad input).
        2. Validates config (raises StripeMisconfiguredError on missing values).
        3. Resolves Stripe Price ID from config.
        4. Creates or retrieves the Stripe Customer for user_id.
        5. Creates a Checkout Session in "subscription" mode.
        6. Returns {"disabled": False, "checkout_url": "<session.url>", "session_id": "<id>"}.

    Args:
        user_id:   The ClearSignal user UUID.  Must not be SYSTEM_DEFAULT_USER_ID.
        plan:      "pro" | "teams"
        interval:  "month" | "year"
        email:     Optional email for Stripe Customer prefill.
        trial_days: Optional trial period in days.

    Raises:
        ValueError          — when user_id is the system user
        InvalidPlanError    — when plan or interval is not supported
        StripeMisconfiguredError — when required config values are empty
        stripe.error.StripeError — on Stripe API errors (propagated to caller)
    """
    cfg = _settings()

    if not cfg.stripe_enabled:
        logger.debug("[stripe] checkout disabled (STRIPE_ENABLED=false)")
        return {
            "disabled":    True,
            "checkout_url": None,
            "reason":       "stripe_disabled",
        }

    if user_id == SYSTEM_DEFAULT_USER_ID:
        raise ValueError("System user cannot initiate a checkout session.")

    # Validate plan/interval and resolve price ID before touching Stripe.
    price_id = resolve_price_id(plan, interval)

    success_url = cfg.stripe_success_url
    cancel_url  = cfg.stripe_cancel_url
    if not success_url:
        raise StripeMisconfiguredError("STRIPE_SUCCESS_URL is empty.")
    if not cancel_url:
        raise StripeMisconfiguredError("STRIPE_CANCEL_URL is empty.")

    stripe = _require_stripe()

    # Get or create customer (best-effort; checkout can proceed without it).
    customer_id: Optional[str] = None
    try:
        customer_id = await create_or_get_customer(user_id, email=email)
    except Exception as exc:
        logger.warning("[stripe] customer lookup failed, proceeding without: %r", exc)

    session_params: Dict[str, Any] = {
        "mode":               "subscription",
        "line_items":         [{"price": price_id, "quantity": 1}],
        "success_url":        success_url,
        "cancel_url":         cancel_url,
        "metadata":           {"user_id": user_id, "plan": plan, "interval": interval},
        "subscription_data":  {"metadata": {"user_id": user_id}},
    }
    if customer_id:
        session_params["customer"] = customer_id
    elif email:
        session_params["customer_email"] = email

    if trial_days and trial_days > 0:
        session_params["subscription_data"]["trial_period_days"] = trial_days

    session = stripe.checkout.Session.create(**session_params)

    logger.info(
        "[stripe] checkout session %s created for user %s plan=%s/%s",
        session.id[:12], user_id[:8], plan, interval,
    )
    return {
        "disabled":    False,
        "checkout_url": session.url,
        "session_id":  session.id,
    }


# ---------------------------------------------------------------------------
# § create_portal_session
# ---------------------------------------------------------------------------

async def create_portal_session(
    customer_id: str,
    return_url: str,
) -> Dict[str, Any]:
    """Create a Stripe billing portal session for an existing customer.

    When STRIPE_ENABLED=false:
        Returns {"disabled": True, "portal_url": None, "reason": "stripe_disabled"}.

    When STRIPE_ENABLED=true:
        Opens a Stripe-hosted self-service portal session and returns the URL.

    Args:
        customer_id: The Stripe Customer ID (cus_...).
        return_url:  URL Stripe sends the user to after leaving the portal.

    Raises:
        StripeDisabledError          — when STRIPE_ENABLED=false
        StripeMisconfiguredError     — when return_url or secret key is empty
        ValueError                   — when customer_id is empty
        stripe.error.StripeError     — on Stripe API errors
    """
    cfg = _settings()

    if not cfg.stripe_enabled:
        return {
            "disabled":   True,
            "portal_url": None,
            "reason":     "stripe_disabled",
        }

    if not customer_id:
        raise ValueError("Cannot create portal session: no Stripe customer ID.")

    if not return_url:
        raise StripeMisconfiguredError(
            "STRIPE_PORTAL_RETURN_URL is empty.  Set it in the Render environment."
        )

    stripe = _require_stripe()

    session = stripe.billing_portal.Session.create(
        customer=customer_id,
        return_url=return_url,
    )
    logger.info(
        "[stripe] billing portal session created for customer %s", customer_id[:12]
    )
    return {
        "disabled":   False,
        "portal_url": session.url,
        "session_id": session.id,
    }


# ---------------------------------------------------------------------------
# § cancel_subscription_at_period_end
# ---------------------------------------------------------------------------

async def cancel_subscription_at_period_end(
    stripe_subscription_id: str,
) -> Dict[str, Any]:
    """Mark a Stripe subscription to cancel at the end of the current period.

    No immediate deletion.  The subscription remains active until the billing
    period ends, then Stripe fires customer.subscription.deleted.

    When STRIPE_ENABLED=false:
        Returns {"disabled": True, "reason": "stripe_disabled"}.

    Returns:
        {"disabled": False, "canceled": True, "cancel_at_period_end": True,
         "current_period_end": <unix_ts>}

    Raises:
        StripeDisabledError       — when STRIPE_ENABLED=false
        StripeMisconfiguredError  — when secret key is empty
        ValueError                — when stripe_subscription_id is empty
        stripe.error.StripeError  — on Stripe API errors
    """
    cfg = _settings()

    if not cfg.stripe_enabled:
        return {
            "disabled": True,
            "reason":   "stripe_disabled",
        }

    if not stripe_subscription_id:
        raise ValueError("stripe_subscription_id is required.")

    stripe = _require_stripe()

    sub = stripe.Subscription.modify(
        stripe_subscription_id,
        cancel_at_period_end=True,
    )
    logger.info(
        "[stripe] subscription %s marked cancel_at_period_end",
        stripe_subscription_id[:12],
    )
    return {
        "disabled":             False,
        "canceled":             True,
        "cancel_at_period_end": True,
        "current_period_end":   getattr(sub, "current_period_end", None),
    }
