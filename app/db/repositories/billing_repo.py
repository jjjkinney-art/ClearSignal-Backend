"""
Billing repository — Phase 17 · Slice 1.

CRUD for subscriptions, stripe_events, and entitlement_cache.
All functions accept an AsyncSession as the first positional argument.
Passing None is safe: every function returns an empty/falsy/None value
rather than raising.  This mirrors the null-session contract used throughout
the loop, portfolio, and account repos.

No Stripe SDK calls.  No entitlement logic.  Pure DB access.
STRIPE_ENABLED is not consulted here; flag checks belong in the service layer.
"""

from __future__ import annotations

import logging
import uuid as _uuid_mod
from datetime import datetime, timezone
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

SYSTEM_DEFAULT_USER_ID: str = "00000000-0000-0000-0000-000000000001"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _new_id() -> str:
    return str(_uuid_mod.uuid4())


# ---------------------------------------------------------------------------
# § SUBSCRIPTIONS
# ---------------------------------------------------------------------------

async def create_subscription(
    session,
    *,
    user_id: str,
    stripe_subscription_id: str,
    stripe_customer_id: str,
    stripe_price_id: str,
    plan_name: str,
    status: str,
    current_period_start: datetime,
    current_period_end: datetime,
    billing_interval: str = "month",
    org_id: Optional[str] = None,
    trial_ends_at: Optional[datetime] = None,
    cancel_at_period_end: bool = False,
    canceled_at: Optional[datetime] = None,
    grace_period_ends_at: Optional[datetime] = None,
    seat_count: int = 1,
    subscription_id: Optional[str] = None,
) -> Optional[object]:
    """Insert a new Subscription row and return it.

    Returns None when session is None.
    Raises on DB constraint violations (e.g. duplicate stripe_subscription_id).
    """
    if session is None:
        return None

    from app.db.models import Subscription

    row = Subscription(
        id=subscription_id or _new_id(),
        user_id=user_id,
        org_id=org_id,
        stripe_subscription_id=stripe_subscription_id,
        stripe_customer_id=stripe_customer_id,
        stripe_price_id=stripe_price_id,
        plan_name=plan_name,
        billing_interval=billing_interval,
        status=status,
        trial_ends_at=trial_ends_at,
        current_period_start=current_period_start,
        current_period_end=current_period_end,
        cancel_at_period_end=cancel_at_period_end,
        canceled_at=canceled_at,
        grace_period_ends_at=grace_period_ends_at,
        seat_count=seat_count,
    )
    session.add(row)
    await session.flush()
    return row


async def get_subscription(
    session,
    subscription_id: str,
) -> Optional[object]:
    """Return a Subscription row by primary key, or None."""
    if session is None:
        return None

    from app.db.models import Subscription
    from sqlalchemy import select

    result = await session.execute(
        select(Subscription).where(Subscription.id == subscription_id)
    )
    return result.scalar_one_or_none()


async def get_subscription_by_stripe_id(
    session,
    stripe_subscription_id: str,
) -> Optional[object]:
    """Return the Subscription row matching stripe_subscription_id, or None."""
    if session is None:
        return None

    from app.db.models import Subscription
    from sqlalchemy import select

    result = await session.execute(
        select(Subscription).where(
            Subscription.stripe_subscription_id == stripe_subscription_id
        )
    )
    return result.scalar_one_or_none()


async def get_active_subscription(
    session,
    user_id: str,
) -> Optional[object]:
    """Return the most-recent non-terminal Subscription for user_id, or None.

    Non-terminal statuses: active, trialing, past_due, paused.
    Ordered by created_at DESC so the latest row wins.
    """
    if session is None:
        return None

    from app.db.models import Subscription
    from sqlalchemy import select

    result = await session.execute(
        select(Subscription)
        .where(Subscription.user_id == user_id)
        .where(Subscription.status.in_(["active", "trialing", "past_due", "paused"]))
        .order_by(Subscription.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def update_subscription(
    session,
    stripe_subscription_id: str,
    *,
    plan_name: Optional[str] = None,
    status: Optional[str] = None,
    current_period_end: Optional[datetime] = None,
    cancel_at_period_end: Optional[bool] = None,
    canceled_at: Optional[datetime] = None,
    grace_period_ends_at: Optional[datetime] = None,
    trial_ends_at: Optional[datetime] = None,
    stripe_price_id: Optional[str] = None,
    seat_count: Optional[int] = None,
) -> Optional[object]:
    """Apply non-None keyword fields to the Subscription row and flush.

    Looks up by stripe_subscription_id (the idempotency key used by webhooks).
    Returns the updated row, or None if not found or session is None.
    """
    if session is None:
        return None

    row = await get_subscription_by_stripe_id(session, stripe_subscription_id)
    if row is None:
        return None

    if plan_name is not None:
        row.plan_name = plan_name
    if status is not None:
        row.status = status
    if current_period_end is not None:
        row.current_period_end = current_period_end
    if cancel_at_period_end is not None:
        row.cancel_at_period_end = cancel_at_period_end
    if canceled_at is not None:
        row.canceled_at = canceled_at
    if grace_period_ends_at is not None:
        row.grace_period_ends_at = grace_period_ends_at
    if trial_ends_at is not None:
        row.trial_ends_at = trial_ends_at
    if stripe_price_id is not None:
        row.stripe_price_id = stripe_price_id
    if seat_count is not None:
        row.seat_count = seat_count

    row.updated_at = _now()
    await session.flush()
    return row


async def list_subscriptions_by_user(
    session,
    user_id: str,
    *,
    limit: int = 20,
) -> List:
    """Return all Subscription rows for user_id, newest first."""
    if session is None:
        return []

    from app.db.models import Subscription
    from sqlalchemy import select

    result = await session.execute(
        select(Subscription)
        .where(Subscription.user_id == user_id)
        .order_by(Subscription.created_at.desc())
        .limit(limit)
    )
    return list(result.scalars().all())


async def count_subscriptions_by_status(session) -> Dict[str, int]:
    """Return status → count across all subscriptions.

    Used by billing observability snapshot.  Returns {} when session is None.
    """
    if session is None:
        return {}

    from app.db.models import Subscription
    from sqlalchemy import select, func

    result = await session.execute(
        select(Subscription.status, func.count(Subscription.id).label("n"))
        .group_by(Subscription.status)
    )
    return {row.status: row.n for row in result.all()}


# ---------------------------------------------------------------------------
# § STRIPE EVENTS
# ---------------------------------------------------------------------------

async def record_stripe_event(
    session,
    *,
    stripe_event_id: str,
    event_type: str,
    processing_status: str = "pending",
    event_id: Optional[str] = None,
) -> Optional[object]:
    """Insert a new StripeEvent row and return it.

    Raises on duplicate stripe_event_id (the caller's idempotency check
    should have prevented this — the DB constraint is the backstop).
    Returns None when session is None.
    """
    if session is None:
        return None

    from app.db.models import StripeEvent

    row = StripeEvent(
        id=event_id or _new_id(),
        stripe_event_id=stripe_event_id,
        event_type=event_type,
        processing_status=processing_status,
    )
    session.add(row)
    await session.flush()
    return row


async def get_stripe_event_by_stripe_id(
    session,
    stripe_event_id: str,
) -> Optional[object]:
    """Return the StripeEvent row for stripe_event_id, or None.

    Used by the webhook handler for idempotency pre-check.
    """
    if session is None:
        return None

    from app.db.models import StripeEvent
    from sqlalchemy import select

    result = await session.execute(
        select(StripeEvent).where(StripeEvent.stripe_event_id == stripe_event_id)
    )
    return result.scalar_one_or_none()


async def update_stripe_event_status(
    session,
    stripe_event_id: str,
    *,
    processing_status: str,
    error_detail: Optional[str] = None,
) -> Optional[object]:
    """Update the processing_status (and optional error_detail) for an event.

    Returns the updated row, or None if not found or session is None.
    """
    if session is None:
        return None

    row = await get_stripe_event_by_stripe_id(session, stripe_event_id)
    if row is None:
        return None

    row.processing_status = processing_status
    if error_detail is not None:
        row.error_detail = error_detail
    row.processed_at = _now()
    await session.flush()
    return row


async def count_stripe_event_errors(
    session,
    *,
    since: Optional[datetime] = None,
) -> int:
    """Count StripeEvent rows with processing_status='error'.

    `since` optionally restricts to events created after a datetime.
    Used by the billing observability snapshot.
    """
    if session is None:
        return 0

    from app.db.models import StripeEvent
    from sqlalchemy import select, func

    stmt = (
        select(func.count(StripeEvent.id))
        .where(StripeEvent.processing_status == "error")
    )
    if since is not None:
        stmt = stmt.where(StripeEvent.created_at >= since)

    result = await session.execute(stmt)
    return result.scalar_one() or 0


# ---------------------------------------------------------------------------
# § ENTITLEMENT CACHE
# ---------------------------------------------------------------------------

async def get_entitlement_cache(
    session,
    user_id: str,
) -> Optional[object]:
    """Return the EntitlementCache row for user_id, or None.

    Callers must check `row.expires_at > now()` before trusting the values.
    A stale row (expires_at in the past) is treated as a cache miss.
    """
    if session is None:
        return None

    from app.db.models import EntitlementCache
    from sqlalchemy import select

    result = await session.execute(
        select(EntitlementCache).where(EntitlementCache.user_id == user_id)
    )
    return result.scalar_one_or_none()


async def upsert_entitlement_cache(
    session,
    user_id: str,
    *,
    plan_name: str,
    plan_status: str,
    watchlist_limit: int,
    portfolio_limit: int,
    position_limit: int,
    dossier_monthly_limit: int,
    features_json: str,
    expires_at: datetime,
    trial_days_remaining: Optional[int] = None,
    computed_at: Optional[datetime] = None,
) -> Optional[object]:
    """Create or replace the EntitlementCache row for user_id.

    Always overwrites — the cache is write-invalidate, not write-through.
    Returns None when session is None.
    """
    if session is None:
        return None

    from app.db.models import EntitlementCache
    from sqlalchemy import select

    result = await session.execute(
        select(EntitlementCache).where(EntitlementCache.user_id == user_id)
    )
    row = result.scalar_one_or_none()

    ts_now = computed_at or _now()

    if row is None:
        row = EntitlementCache(
            user_id=user_id,
            plan_name=plan_name,
            plan_status=plan_status,
            watchlist_limit=watchlist_limit,
            portfolio_limit=portfolio_limit,
            position_limit=position_limit,
            dossier_monthly_limit=dossier_monthly_limit,
            features_json=features_json,
            trial_days_remaining=trial_days_remaining,
            computed_at=ts_now,
            expires_at=expires_at,
        )
        session.add(row)
    else:
        row.plan_name             = plan_name
        row.plan_status           = plan_status
        row.watchlist_limit       = watchlist_limit
        row.portfolio_limit       = portfolio_limit
        row.position_limit        = position_limit
        row.dossier_monthly_limit = dossier_monthly_limit
        row.features_json         = features_json
        row.trial_days_remaining  = trial_days_remaining
        row.computed_at           = ts_now
        row.expires_at            = expires_at

    await session.flush()
    return row


# ---------------------------------------------------------------------------
# § USERS — billing fields
# ---------------------------------------------------------------------------

async def find_user_id_by_stripe_customer_id(
    session,
    stripe_customer_id: str,
) -> Optional[str]:
    """Return the user_id whose stripe_customer_id matches, or None.

    Used by webhook handlers to resolve customer → user before updating
    subscription rows and entitlement cache.
    Returns None when session is None or no match found.
    """
    if session is None:
        return None

    from app.db.models import User
    from sqlalchemy import select

    result = await session.execute(
        select(User.id).where(User.stripe_customer_id == stripe_customer_id)
    )
    row = result.first()
    return row[0] if row else None


async def set_user_stripe_customer_id(
    session,
    user_id: str,
    stripe_customer_id: str,
) -> bool:
    """Write stripe_customer_id to the users row, if not already set.

    Idempotent — if the value is already the same, this is a no-op.
    Returns True if the row was updated, False otherwise.
    Returns False when session is None.
    """
    if session is None:
        return False

    from app.db.models import User
    from sqlalchemy import select

    result = await session.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        return False
    if user.stripe_customer_id == stripe_customer_id:
        return False
    user.stripe_customer_id = stripe_customer_id
    user.updated_at = _now()
    await session.flush()
    return True


async def update_user_plan(
    session,
    user_id: str,
    plan_name: str,
) -> bool:
    """Update users.plan and plan_updated_at for the given user.

    Returns True if updated, False if user not found or session is None.
    Called by webhook handlers after subscription state changes.
    """
    if session is None:
        return False

    from app.db.models import User
    from sqlalchemy import select

    result = await session.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        return False

    user.plan = plan_name
    user.plan_updated_at = _now()
    user.updated_at = _now()
    await session.flush()
    return True


async def invalidate_entitlement_cache(
    session,
    user_id: str,
) -> bool:
    """Delete the EntitlementCache row for user_id.

    Returns True if a row was found and deleted, False otherwise.
    Safe to call when no cache row exists.
    Returns False when session is None.
    """
    if session is None:
        return False

    from app.db.models import EntitlementCache
    from sqlalchemy import delete

    result = await session.execute(
        delete(EntitlementCache).where(EntitlementCache.user_id == user_id)
    )
    await session.flush()
    return (result.rowcount or 0) > 0
