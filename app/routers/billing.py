"""
Billing routes — Phase 17 · Slices 3–5.

Endpoints
---------
    POST /billing/checkout  — create a Stripe Checkout Session (Slice 3)
    POST /billing/webhook   — Stripe webhook receiver (Slice 4)
    GET  /billing/status    — current billing state + entitlements (Slice 5)
    POST /billing/portal    — create Stripe billing portal session (Slice 5)
    POST /billing/cancel    — mark subscription cancel_at_period_end (Slice 5)

Design
------
* When STRIPE_ENABLED=false the checkout, portal, and cancel endpoints return
  503 disabled bodies.  The webhook endpoint returns 200 no-op.
  The status endpoint always works (read-only, no Stripe calls).
* No entitlement enforcement.  No plan gating.
* subscription activation happens only via webhook (Slice 4).
* All Stripe-mutating routes reject SYSTEM_DEFAULT_USER_ID with 400.
  GET /billing/status returns the system unlimited plan for the system user.
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, field_validator

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/billing", tags=["billing"])

VALID_PLANS     = {"pro", "teams"}
VALID_INTERVALS = {"month", "year"}

SYSTEM_DEFAULT_USER_ID = "00000000-0000-0000-0000-000000000001"


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class CheckoutRequest(BaseModel):
    plan:     str
    interval: str
    email:    Optional[str] = None

    @field_validator("plan")
    @classmethod
    def _validate_plan(cls, v: str) -> str:
        v = v.lower().strip()
        if v not in VALID_PLANS:
            raise ValueError(
                f"Invalid plan {v!r}. Supported: {sorted(VALID_PLANS)}"
            )
        return v

    @field_validator("interval")
    @classmethod
    def _validate_interval(cls, v: str) -> str:
        v = v.lower().strip()
        if v not in VALID_INTERVALS:
            raise ValueError(
                f"Invalid interval {v!r}. Supported: {sorted(VALID_INTERVALS)}"
            )
        return v


# ---------------------------------------------------------------------------
# POST /billing/checkout
# ---------------------------------------------------------------------------

@router.post(
    "/checkout",
    summary="Create a Stripe Checkout Session",
)
async def billing_checkout(body: CheckoutRequest, request: Request):
    """Create a Stripe Checkout Session and return the redirect URL.

    When STRIPE_ENABLED=false:
        Returns 503 with {"disabled": true, "reason": "stripe_disabled"}.
        No outbound Stripe calls are made.

    When STRIPE_ENABLED=true:
        Creates a Checkout Session and returns the Stripe-hosted URL.

    Auth: user_id is read from request.state (auth middleware / bypass).
    System user (AUTH_ENABLED=false bypass) is rejected with 400.

    Request body:
        {"plan": "pro", "interval": "month"}
        {"plan": "pro", "interval": "year"}
        {"plan": "teams", "interval": "month"}

    Successful response:
        {"disabled": false, "checkout_url": "https://checkout.stripe.com/...", "session_id": "cs_..."}

    Disabled response (STRIPE_ENABLED=false):
        HTTP 503 — {"disabled": true, "reason": "stripe_disabled", "checkout_url": null}
    """
    from app.services.stripe_service import (   # noqa: PLC0415
        create_checkout_session,
        InvalidPlanError,
        StripeMisconfiguredError,
        StripeDisabledError,
    )
    from app.config import settings as cfg

    # Disabled fast-path — check flag before doing anything else.
    if not cfg.stripe_enabled:
        return JSONResponse(
            status_code=503,
            content={
                "disabled":    True,
                "reason":      "stripe_disabled",
                "checkout_url": None,
            },
        )

    # Resolve user identity.
    user_id: Optional[str] = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required.")
    if user_id == SYSTEM_DEFAULT_USER_ID:
        raise HTTPException(
            status_code=400,
            detail="System user cannot initiate a checkout session.",
        )

    try:
        result = await create_checkout_session(
            user_id=user_id,
            plan=body.plan,
            interval=body.interval,
            email=body.email,
        )
    except InvalidPlanError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except StripeMisconfiguredError as exc:
        logger.error("[billing] Stripe misconfigured: %r", exc)
        raise HTTPException(status_code=503, detail="Billing service misconfigured.") from exc
    except StripeDisabledError:
        return JSONResponse(
            status_code=503,
            content={"disabled": True, "reason": "stripe_disabled", "checkout_url": None},
        )
    except Exception as exc:
        logger.error("[billing] checkout session creation failed: %r", exc)
        raise HTTPException(status_code=502, detail="Billing service unavailable.") from exc

    return result


# ---------------------------------------------------------------------------
# POST /billing/webhook  (Phase 17 · Slice 4)
# ---------------------------------------------------------------------------

@router.post(
    "/webhook",
    summary="Stripe webhook receiver",
)
async def billing_webhook(request: Request):
    """Receive and process Stripe webhook events.

    Security:
        Raw request body is read before any parsing.
        Stripe-Signature header is verified against STRIPE_WEBHOOK_SECRET
        before the payload is trusted.

    Idempotency:
        stripe_event_id (evt_*) is stored in stripe_events with a UNIQUE
        constraint.  A duplicate delivery returns 200 immediately without
        re-processing.

    Return codes:
        200 — event received (processed, skipped, or duplicate)
        400 — missing or invalid Stripe-Signature header
        400 — STRIPE_WEBHOOK_SECRET not configured
        200 — STRIPE_ENABLED=false (webhook is inactive; safe no-op)

    Note:
        After a valid signature the route ALWAYS returns 200, even if the
        processing handler raises — we write processing_status='error' to
        stripe_events and log, but never return 5xx.  Returning 5xx would
        cause Stripe to retry an event whose side effects may have partially
        applied, risking duplicate subscription rows or double plan changes.
    """
    from app.config import settings as cfg
    from app.services.stripe_service import StripeDisabledError, StripeMisconfiguredError
    from app.services.webhook_service import verify_stripe_signature, process_event
    from app.db.repositories.billing_repo import (
        get_stripe_event_by_stripe_id,
        get_subscription_by_stripe_id,
        record_stripe_event,
        update_stripe_event_status,
    )
    from app.db import get_session as _get_session

    # Disabled fast-path — no outbound calls, no signature check needed.
    if not cfg.stripe_enabled:
        return JSONResponse(
            status_code=200,
            content={"received": True, "disabled": True},
        )

    # Read raw body BEFORE FastAPI parses anything — signature requires bytes.
    payload_bytes: bytes = await request.body()

    sig_header: str = request.headers.get("stripe-signature", "")
    if not sig_header:
        raise HTTPException(status_code=400, detail="Missing Stripe-Signature header.")

    # Signature verification — 400 on failure so Stripe does not retry.
    try:
        event = verify_stripe_signature(payload_bytes, sig_header, cfg.stripe_webhook_secret)
    except StripeMisconfiguredError as exc:
        logger.error("[webhook] misconfigured: %r", exc)
        raise HTTPException(status_code=400, detail="Webhook secret not configured.") from exc
    except StripeDisabledError:
        return JSONResponse(status_code=200, content={"received": True, "disabled": True})
    except Exception as exc:
        # Covers stripe.error.SignatureVerificationError and ImportError.
        logger.warning("[webhook] signature verification failed: %r", exc)
        raise HTTPException(status_code=400, detail="Invalid Stripe signature.") from exc

    stripe_event_id: str = event.get("id", "")
    event_type:      str = event.get("type", "unknown")

    async with _get_session() as db:
        # Idempotency pre-check.  A historical subscription event may have
        # been acknowledged before checkout linked its customer to a user.
        # Such an event was marked ``ok`` even though no subscription row was
        # created.  Permit that specific delivery to be replayed; the
        # subscription handler itself is an idempotent upsert.
        existing = await get_stripe_event_by_stripe_id(db, stripe_event_id)
        if existing is not None:
            replayable = existing.processing_status == "error"
            if event_type in {
                "customer.subscription.created",
                "customer.subscription.updated",
            }:
                sub_obj = event.get("data", {}).get("object", {})
                sub_id = sub_obj.get("id", "") or ""
                if sub_id and await get_subscription_by_stripe_id(db, sub_id) is None:
                    replayable = True

            if not replayable:
                logger.debug("[webhook] duplicate event %s — skipping", stripe_event_id)
                return JSONResponse(
                    status_code=200,
                    content={"received": True, "duplicate": True, "event_id": stripe_event_id},
                )

            logger.info("[webhook] replaying incomplete event %s", stripe_event_id)
            await update_stripe_event_status(
                db,
                stripe_event_id,
                processing_status="pending",
            )

        else:
            # Record event as pending before processing begins.
            await record_stripe_event(
                db,
                stripe_event_id=stripe_event_id,
                event_type=event_type,
                processing_status="pending",
            )

        # Process — errors are caught and recorded; 200 is always returned.
        try:
            outcome = await process_event(db, event)
            await update_stripe_event_status(db, stripe_event_id, processing_status=outcome)
            await db.commit()
        except Exception as exc:
            logger.error("[webhook] handler error for %s %s: %r", event_type, stripe_event_id, exc)
            try:
                await update_stripe_event_status(
                    db,
                    stripe_event_id,
                    processing_status="error",
                    error_detail=str(exc)[:500],
                )
                await db.commit()
            except Exception:
                pass

    return JSONResponse(
        status_code=200,
        content={"received": True, "event_id": stripe_event_id},
    )


# ---------------------------------------------------------------------------
# Internal helpers (Slice 5)
# ---------------------------------------------------------------------------

def _iso(dt) -> Optional[str]:
    """Return ISO-8601 string for a datetime (naive or aware), or None."""
    if dt is None:
        return None
    if hasattr(dt, "isoformat"):
        return dt.isoformat()
    return str(dt)


def _entitlements_dict(ent) -> dict:
    """Serialise an EntitlementSet for the /billing/status response."""
    from dataclasses import asdict
    d = asdict(ent)
    features = {
        k: d[k] for k in (
            "can_use_portfolio_intelligence",
            "can_use_email_delivery",
            "can_use_push_delivery",
            "can_set_briefing_time",
            "can_use_custom_quiet_hours",
            "can_export_data",
            "can_use_api",
            "can_use_org_features",
            "has_unlimited_inbox",
        )
    }
    return {
        "tier_name":            d["tier_name"],
        "plan_name":            d["plan_name"],
        "plan_status":          d["plan_status"],
        "watchlist_limit":      d["watchlist_limit"],
        "portfolio_limit":      d["portfolio_limit"],
        "position_limit":       d["position_limit"],
        "dossier_monthly_limit": d["dossier_monthly_limit"],
        "briefing_limit":       d["briefing_limit"],
        "delivery_limit":       d["delivery_limit"],
        "show_upgrade_cta":     d["show_upgrade_cta"],
        "trial_days_remaining": d["trial_days_remaining"],
        "features":             features,
    }


# ---------------------------------------------------------------------------
# GET /billing/status  (Phase 17 · Slice 5)
# ---------------------------------------------------------------------------

@router.get(
    "/status",
    summary="Current billing state",
)
async def billing_status(request: Request):
    """Return the current user's billing state and entitlement summary.

    Always succeeds (read-only, no Stripe calls).
    System user returns unlimited/system entitlements without a DB query.

    Response fields:
        plan                   — "free" | "pro" | "teams" | "institutional" | "system"
        subscription_status    — Stripe subscription status, or null
        is_trial               — true when plan_status is "trialing"
        trial_ends_at          — ISO timestamp or null
        trial_days_remaining   — int or null
        is_grace_period        — true when plan_status is "grace"
        grace_period_ends_at   — ISO timestamp or null
        current_period_end     — ISO timestamp or null
        cancel_at_period_end   — bool
        stripe_customer_present — bool (has a Stripe Customer ID on file)
        entitlements           — resolved access limits and feature flags
    """
    from app.services.entitlement_service import (
        resolve_entitlements,
        SYSTEM_DEFAULT_USER_ID as _SYS,
        _system_entitlements,
    )
    from app.db import get_session as _get_session

    from app.dependencies.auth import require_user_id

    user_id: str = require_user_id(request)

    # System user fast-path — no DB query.
    if user_id == _SYS:
        ent = _system_entitlements(user_id)
        return {
            "user_id":               user_id,
            "plan":                  "system",
            "subscription_status":   "system",
            "is_trial":              False,
            "trial_ends_at":         None,
            "trial_days_remaining":  None,
            "is_grace_period":       False,
            "grace_period_ends_at":  None,
            "current_period_end":    None,
            "cancel_at_period_end":  False,
            "stripe_customer_present": False,
            "entitlements":          _entitlements_dict(ent),
        }

    async with _get_session() as db:
        from app.db.models import User
        from app.db.repositories.billing_repo import get_active_subscription
        from sqlalchemy import select

        result = await db.execute(select(User).where(User.id == user_id))
        user_row = result.scalar_one_or_none()

        stripe_customer_present = bool(user_row and user_row.stripe_customer_id)

        sub = await get_active_subscription(db, user_id)

        # Recovery path for a checkout whose customer link committed but whose
        # subscription webhook was acknowledged before the local row existed.
        # Reuse the normal idempotent webhook upsert so reconciliation follows
        # exactly the same plan mapping, cache invalidation, and user-plan rules.
        if sub is None and stripe_customer_present:
            from app.config import settings as cfg
            from app.services.stripe_service import (
                retrieve_active_subscription_for_customer,
            )
            from app.services.webhook_service import handle_subscription_created

            if cfg.stripe_enabled:
                try:
                    stripe_sub = await retrieve_active_subscription_for_customer(
                        user_row.stripe_customer_id
                    )
                    if stripe_sub is not None:
                        await handle_subscription_created(db, stripe_sub)
                        await db.commit()
                        sub = await get_active_subscription(db, user_id)
                        logger.info(
                            "[billing] reconciled missing subscription for user %s",
                            user_id[:8],
                        )
                except Exception as exc:
                    await db.rollback()
                    logger.warning(
                        "[billing] subscription reconciliation failed for user %s: %r",
                        user_id[:8],
                        exc,
                    )

        ent = await resolve_entitlements(db, user_id)

    is_trial  = ent.plan_status == "trialing"
    is_grace  = ent.plan_status == "grace"

    return {
        "user_id":               user_id,
        "plan":                  ent.plan_name,
        "subscription_status":   sub.status if sub else None,
        "is_trial":              is_trial,
        "trial_ends_at":         _iso(sub.trial_ends_at) if sub else None,
        "trial_days_remaining":  ent.trial_days_remaining,
        "is_grace_period":       is_grace,
        "grace_period_ends_at":  _iso(sub.grace_period_ends_at) if sub else None,
        "current_period_end":    _iso(sub.current_period_end) if sub else None,
        "cancel_at_period_end":  bool(sub.cancel_at_period_end) if sub else False,
        "stripe_customer_present": stripe_customer_present,
        "entitlements":          _entitlements_dict(ent),
    }


# ---------------------------------------------------------------------------
# POST /billing/portal  (Phase 17 · Slice 5)
# ---------------------------------------------------------------------------

@router.post(
    "/portal",
    summary="Create Stripe billing portal session",
)
async def billing_portal(request: Request):
    """Create a Stripe billing portal session and return the redirect URL.

    When STRIPE_ENABLED=false:
        Returns 503 {"disabled": true, "reason": "stripe_disabled", "portal_url": null}.

    When STRIPE_ENABLED=true:
        Requires the user to have an existing Stripe customer ID.
        Returns {"disabled": false, "portal_url": "https://billing.stripe.com/..."}.

    System user is rejected with 400.
    """
    from app.config import settings as cfg
    from app.services.stripe_service import (
        create_portal_session,
        StripeDisabledError,
        StripeMisconfiguredError,
    )
    from app.db import get_session as _get_session

    if not cfg.stripe_enabled:
        return JSONResponse(
            status_code=503,
            content={"disabled": True, "reason": "stripe_disabled", "portal_url": None},
        )

    user_id: Optional[str] = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required.")
    if user_id == SYSTEM_DEFAULT_USER_ID:
        raise HTTPException(status_code=400,
                            detail="System user cannot access the billing portal.")

    # Look up Stripe customer ID.
    async with _get_session() as db:
        from app.db.models import User
        from sqlalchemy import select

        result = await db.execute(select(User).where(User.id == user_id))
        user_row = result.scalar_one_or_none()

    customer_id: str = (user_row.stripe_customer_id or "") if user_row else ""
    if not customer_id:
        raise HTTPException(
            status_code=400,
            detail="No billing account found.  Complete a checkout first.",
        )

    try:
        result = await create_portal_session(
            customer_id=customer_id,
            return_url=cfg.stripe_portal_return_url,
        )
    except StripeMisconfiguredError as exc:
        logger.error("[billing] portal misconfigured: %r", exc)
        raise HTTPException(status_code=503, detail="Billing service misconfigured.") from exc
    except StripeDisabledError:
        return JSONResponse(
            status_code=503,
            content={"disabled": True, "reason": "stripe_disabled", "portal_url": None},
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("[billing] portal session creation failed: %r", exc)
        raise HTTPException(status_code=502, detail="Billing service unavailable.") from exc

    return result


# ---------------------------------------------------------------------------
# POST /billing/cancel  (Phase 17 · Slice 5)
# ---------------------------------------------------------------------------

@router.post(
    "/cancel",
    summary="Cancel subscription at period end",
)
async def billing_cancel(request: Request):
    """Mark the user's active subscription to cancel at the end of the current period.

    No immediate deletion.  Access continues until current_period_end,
    then Stripe fires customer.subscription.deleted (handled by Slice 4 webhook).

    When STRIPE_ENABLED=false:
        Returns 503 {"disabled": true, "reason": "stripe_disabled"}.

    Successful response:
        {"disabled": false, "canceled": true, "cancel_at_period_end": true,
         "current_period_end": <unix_ts>}

    System user is rejected with 400.
    No active subscription returns 400.
    """
    from app.config import settings as cfg
    from app.services.stripe_service import (
        cancel_subscription_at_period_end,
        StripeDisabledError,
        StripeMisconfiguredError,
    )
    from app.db import get_session as _get_session

    if not cfg.stripe_enabled:
        return JSONResponse(
            status_code=503,
            content={"disabled": True, "reason": "stripe_disabled"},
        )

    user_id: Optional[str] = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required.")
    if user_id == SYSTEM_DEFAULT_USER_ID:
        raise HTTPException(status_code=400,
                            detail="System user cannot cancel a subscription.")

    async with _get_session() as db:
        from app.db.repositories.billing_repo import (
            get_active_subscription,
            update_subscription,
            invalidate_entitlement_cache,
        )

        sub = await get_active_subscription(db, user_id)
        if sub is None:
            raise HTTPException(
                status_code=400,
                detail="No active subscription found.",
            )

        stripe_sub_id = sub.stripe_subscription_id

        try:
            stripe_result = await cancel_subscription_at_period_end(stripe_sub_id)
        except StripeDisabledError:
            return JSONResponse(
                status_code=503,
                content={"disabled": True, "reason": "stripe_disabled"},
            )
        except StripeMisconfiguredError as exc:
            logger.error("[billing] cancel misconfigured: %r", exc)
            raise HTTPException(
                status_code=503, detail="Billing service misconfigured."
            ) from exc
        except Exception as exc:
            logger.error("[billing] cancel failed: %r", exc)
            raise HTTPException(
                status_code=502, detail="Billing service unavailable."
            ) from exc

        # Mirror state locally so UI is consistent before the webhook arrives.
        await update_subscription(db, stripe_sub_id, cancel_at_period_end=True)
        await invalidate_entitlement_cache(db, user_id)
        await db.commit()

    return stripe_result
