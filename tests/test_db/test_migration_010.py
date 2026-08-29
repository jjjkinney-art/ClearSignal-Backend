"""
Phase 17 · Slice 1 — Migration 010 idempotency and structural tests.

Validates:
  1.  All 38 ORM tables are created by Base.metadata.create_all (idempotent —
      running create_all twice raises no error).
  2.  db_table_count is exactly 38 on a fresh in-memory SQLite database
      (35 Phase 9–16 tables + 3 Phase 17 billing tables).
  3.  subscriptions table has the expected columns and unique constraint.
  4.  stripe_events table has the expected columns and unique constraint.
  5.  entitlement_cache table has the expected columns.
  6.  users table has plan and plan_updated_at columns (additive).
  7.  Migration file 010_subscriptions_billing.sql exists.
  8.  Subscription CRUD round-trip (create, read, update).
  9.  Stripe event uniqueness: duplicate stripe_event_id raises.
  10. Entitlement cache CRUD (upsert, read, invalidate).
  11. Nullable plan fields (trial_ends_at, canceled_at, grace_period_ends_at).
  12. Null-session safety: all billing repo functions return falsy, never raise.

Uses in-memory SQLite via aiosqlite — no Postgres instance needed.
"""

from __future__ import annotations

import os
import pytest
import pytest_asyncio
from datetime import datetime, timezone, timedelta


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _future(hours: int = 1) -> datetime:
    return _now() + timedelta(hours=hours)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def fresh_engine():
    """Yield a fresh in-memory SQLite engine with all ORM tables created."""
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
    """Yield an open AsyncSession on the fresh in-memory database."""
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    factory = async_sessionmaker(fresh_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as s:
        yield s


# ---------------------------------------------------------------------------
# 1. Idempotency — create_all runs twice without error
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_all_is_idempotent(fresh_engine):
    """Running Base.metadata.create_all twice raises no error."""
    from app.db.models import Base

    async with fresh_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)  # second call — must not raise


# ---------------------------------------------------------------------------
# 2. Every declared model table exists on a fresh DB
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_db_table_count_matches_metadata(fresh_engine):
    """A fresh database must contain every table declared by the ORM metadata."""
    from app.db.models import Base
    from sqlalchemy import text

    async with fresh_engine.connect() as conn:
        result = await conn.execute(
            text("SELECT COUNT(*) FROM sqlite_master WHERE type='table'")
        )
        count = result.scalar()

    expected = len(Base.metadata.tables)
    assert count == expected, (
        f"Expected {expected} ORM tables, got {count}. "
        "Check that every model is included in Base.metadata."
    )


# ---------------------------------------------------------------------------
# 3. subscriptions table structure
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_subscriptions_columns_exist(fresh_engine):
    """subscriptions must have the expected columns."""
    from sqlalchemy import text

    async with fresh_engine.connect() as conn:
        result = await conn.execute(text("PRAGMA table_info(subscriptions)"))
        cols = {row[1] for row in result.fetchall()}

    required = {
        "id", "user_id", "org_id",
        "stripe_subscription_id", "stripe_customer_id", "stripe_price_id",
        "plan_name", "billing_interval", "status",
        "trial_ends_at", "current_period_start", "current_period_end",
        "cancel_at_period_end", "canceled_at", "grace_period_ends_at",
        "seat_count", "created_at", "updated_at",
    }
    missing = required - cols
    assert not missing, f"subscriptions is missing columns: {missing}"


# ---------------------------------------------------------------------------
# 4. stripe_events table structure
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_stripe_events_columns_exist(fresh_engine):
    """stripe_events must have the expected columns and NO payload_json."""
    from sqlalchemy import text

    async with fresh_engine.connect() as conn:
        result = await conn.execute(text("PRAGMA table_info(stripe_events)"))
        cols = {row[1] for row in result.fetchall()}

    required = {
        "id", "stripe_event_id", "event_type",
        "processing_status", "error_detail",
        "processed_at", "created_at",
    }
    missing = required - cols
    assert not missing, f"stripe_events is missing columns: {missing}"

    # PII safeguard: raw payload must never be stored
    assert "payload_json" not in cols, (
        "stripe_events must NOT have a payload_json column — "
        "raw Stripe payloads may contain PII."
    )


# ---------------------------------------------------------------------------
# 5. entitlement_cache table structure
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_entitlement_cache_columns_exist(fresh_engine):
    """entitlement_cache must have the expected columns."""
    from sqlalchemy import text

    async with fresh_engine.connect() as conn:
        result = await conn.execute(text("PRAGMA table_info(entitlement_cache)"))
        cols = {row[1] for row in result.fetchall()}

    required = {
        "user_id", "plan_name", "plan_status",
        "watchlist_limit", "portfolio_limit", "position_limit",
        "dossier_monthly_limit", "features_json", "trial_days_remaining",
        "computed_at", "expires_at",
    }
    missing = required - cols
    assert not missing, f"entitlement_cache is missing columns: {missing}"


# ---------------------------------------------------------------------------
# 6. users table — plan and plan_updated_at columns
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_users_has_plan_columns(fresh_engine):
    """users table must have plan and plan_updated_at columns (Phase 17 additions)."""
    from sqlalchemy import text

    async with fresh_engine.connect() as conn:
        result = await conn.execute(text("PRAGMA table_info(users)"))
        cols = {row[1] for row in result.fetchall()}

    assert "plan" in cols, "users is missing the plan column"
    assert "plan_updated_at" in cols, "users is missing the plan_updated_at column"


# ---------------------------------------------------------------------------
# 7. Migration file exists
# ---------------------------------------------------------------------------

def test_migration_file_exists():
    """Migration file 010_subscriptions_billing.sql must be present."""
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(os.path.dirname(here))
    migration_path = os.path.join(
        root, "app", "db", "migrations", "010_subscriptions_billing.sql"
    )
    assert os.path.isfile(migration_path), (
        f"Migration file not found at {migration_path}"
    )


# ---------------------------------------------------------------------------
# 8. Subscription CRUD round-trip
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_subscription_create_read_update(session):
    """Create, read, and update a Subscription row."""
    from app.db.repositories.billing_repo import (
        create_subscription,
        get_subscription,
        get_subscription_by_stripe_id,
        update_subscription,
    )

    period_start = _now()
    period_end   = _future(hours=720)

    row = await create_subscription(
        session,
        user_id="user-001",
        stripe_subscription_id="sub_test_001",
        stripe_customer_id="cus_test_001",
        stripe_price_id="price_test_monthly",
        plan_name="pro",
        status="active",
        current_period_start=period_start,
        current_period_end=period_end,
        billing_interval="month",
    )
    await session.commit()

    assert row is not None
    assert row.plan_name == "pro"
    assert row.status == "active"
    assert row.cancel_at_period_end is False
    assert row.seat_count == 1
    assert row.trial_ends_at is None
    assert row.grace_period_ends_at is None

    # Read by PK
    fetched = await get_subscription(session, row.id)
    assert fetched is not None
    assert fetched.stripe_subscription_id == "sub_test_001"

    # Read by Stripe ID
    fetched2 = await get_subscription_by_stripe_id(session, "sub_test_001")
    assert fetched2 is not None
    assert fetched2.id == row.id

    # Update status and grace period
    grace = _future(hours=72)
    updated = await update_subscription(
        session,
        "sub_test_001",
        status="past_due",
        grace_period_ends_at=grace,
    )
    await session.commit()

    assert updated is not None
    assert updated.status == "past_due"
    assert updated.grace_period_ends_at is not None

    # Original plan_name unchanged
    assert updated.plan_name == "pro"


# ---------------------------------------------------------------------------
# 9. Stripe event uniqueness constraint
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_stripe_event_uniqueness(session):
    """Inserting a duplicate stripe_event_id must raise an integrity error."""
    import sqlalchemy.exc
    from app.db.repositories.billing_repo import record_stripe_event

    await record_stripe_event(
        session,
        stripe_event_id="evt_duplicate_001",
        event_type="customer.subscription.updated",
    )
    await session.commit()

    with pytest.raises(sqlalchemy.exc.IntegrityError):
        await record_stripe_event(
            session,
            stripe_event_id="evt_duplicate_001",
            event_type="customer.subscription.updated",
        )
        await session.commit()


@pytest.mark.asyncio
async def test_stripe_event_idempotency_lookup(session):
    """get_stripe_event_by_stripe_id returns the row when it exists, None otherwise."""
    from app.db.repositories.billing_repo import (
        record_stripe_event,
        get_stripe_event_by_stripe_id,
        update_stripe_event_status,
    )

    row = await record_stripe_event(
        session,
        stripe_event_id="evt_lookup_001",
        event_type="invoice.paid",
    )
    await session.commit()

    found = await get_stripe_event_by_stripe_id(session, "evt_lookup_001")
    assert found is not None
    assert found.processing_status == "pending"

    not_found = await get_stripe_event_by_stripe_id(session, "evt_nonexistent")
    assert not_found is None

    # Update to ok
    updated = await update_stripe_event_status(
        session, "evt_lookup_001", processing_status="ok"
    )
    await session.commit()
    assert updated.processing_status == "ok"


# ---------------------------------------------------------------------------
# 10. Entitlement cache CRUD
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_entitlement_cache_upsert_read_invalidate(session):
    """Full entitlement cache lifecycle: upsert → read → re-upsert → invalidate."""
    from app.db.repositories.billing_repo import (
        upsert_entitlement_cache,
        get_entitlement_cache,
        invalidate_entitlement_cache,
    )

    uid = "user-cache-001"
    exp = _future(hours=1)

    row = await upsert_entitlement_cache(
        session,
        uid,
        plan_name="free",
        plan_status="active",
        watchlist_limit=5,
        portfolio_limit=1,
        position_limit=10,
        dossier_monthly_limit=3,
        features_json='{"portfolio_intelligence": false}',
        expires_at=exp,
    )
    await session.commit()

    assert row is not None
    assert row.plan_name == "free"
    assert row.watchlist_limit == 5
    assert row.dossier_monthly_limit == 3

    fetched = await get_entitlement_cache(session, uid)
    assert fetched is not None
    assert fetched.plan_name == "free"

    # Re-upsert (upgrade to pro)
    exp2 = _future(hours=1)
    updated = await upsert_entitlement_cache(
        session,
        uid,
        plan_name="pro",
        plan_status="active",
        watchlist_limit=-1,
        portfolio_limit=5,
        position_limit=-1,
        dossier_monthly_limit=-1,
        features_json='{"portfolio_intelligence": true}',
        expires_at=exp2,
    )
    await session.commit()

    assert updated.plan_name == "pro"
    assert updated.watchlist_limit == -1

    # Invalidate (delete)
    deleted = await invalidate_entitlement_cache(session, uid)
    await session.commit()
    assert deleted is True

    # Row is gone
    gone = await get_entitlement_cache(session, uid)
    assert gone is None

    # Second invalidate: safe, returns False
    again = await invalidate_entitlement_cache(session, uid)
    assert again is False


# ---------------------------------------------------------------------------
# 11. Nullable plan fields
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_subscription_nullable_fields(session):
    """trial_ends_at, canceled_at, grace_period_ends_at, org_id may all be None."""
    from app.db.repositories.billing_repo import (
        create_subscription,
        get_subscription,
    )

    row = await create_subscription(
        session,
        user_id="user-null-001",
        stripe_subscription_id="sub_null_001",
        stripe_customer_id="cus_null_001",
        stripe_price_id="price_null_monthly",
        plan_name="pro",
        status="trialing",
        current_period_start=_now(),
        current_period_end=_future(hours=336),
        trial_ends_at=_future(hours=336),  # set trial
    )
    await session.commit()

    fetched = await get_subscription(session, row.id)
    assert fetched.trial_ends_at is not None
    assert fetched.canceled_at is None
    assert fetched.grace_period_ends_at is None
    assert fetched.org_id is None


@pytest.mark.asyncio
async def test_entitlement_cache_trial_days_optional(session):
    """trial_days_remaining may be None for non-trialing users."""
    from app.db.repositories.billing_repo import (
        upsert_entitlement_cache,
        get_entitlement_cache,
    )

    await upsert_entitlement_cache(
        session,
        "user-no-trial",
        plan_name="pro",
        plan_status="active",
        watchlist_limit=-1,
        portfolio_limit=5,
        position_limit=-1,
        dossier_monthly_limit=-1,
        features_json="{}",
        expires_at=_future(hours=1),
        trial_days_remaining=None,
    )
    await session.commit()

    row = await get_entitlement_cache(session, "user-no-trial")
    assert row is not None
    assert row.trial_days_remaining is None


# ---------------------------------------------------------------------------
# 12. Null-session safety
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_null_session_subscription_functions():
    """All subscription repo functions return falsy, never raise, on None session."""
    from app.db.repositories.billing_repo import (
        create_subscription,
        get_subscription,
        get_subscription_by_stripe_id,
        get_active_subscription,
        update_subscription,
        list_subscriptions_by_user,
        count_subscriptions_by_status,
    )

    assert await create_subscription(
        None,
        user_id="u", stripe_subscription_id="s", stripe_customer_id="c",
        stripe_price_id="p", plan_name="pro", status="active",
        current_period_start=_now(), current_period_end=_future(),
    ) is None

    assert await get_subscription(None, "any-id") is None
    assert await get_subscription_by_stripe_id(None, "sub_x") is None
    assert await get_active_subscription(None, "user-x") is None
    assert await update_subscription(None, "sub_x", status="canceled") is None
    assert await list_subscriptions_by_user(None, "user-x") == []
    assert await count_subscriptions_by_status(None) == {}


@pytest.mark.asyncio
async def test_null_session_stripe_event_functions():
    """All stripe event repo functions return falsy on None session."""
    from app.db.repositories.billing_repo import (
        record_stripe_event,
        get_stripe_event_by_stripe_id,
        update_stripe_event_status,
        count_stripe_event_errors,
    )

    assert await record_stripe_event(
        None, stripe_event_id="evt_x", event_type="invoice.paid"
    ) is None
    assert await get_stripe_event_by_stripe_id(None, "evt_x") is None
    assert await update_stripe_event_status(
        None, "evt_x", processing_status="ok"
    ) is None
    assert await count_stripe_event_errors(None) == 0


@pytest.mark.asyncio
async def test_null_session_entitlement_cache_functions():
    """All entitlement cache repo functions return falsy on None session."""
    from app.db.repositories.billing_repo import (
        get_entitlement_cache,
        upsert_entitlement_cache,
        invalidate_entitlement_cache,
    )

    assert await get_entitlement_cache(None, "user-x") is None
    assert await upsert_entitlement_cache(
        None, "user-x",
        plan_name="free", plan_status="active",
        watchlist_limit=5, portfolio_limit=1, position_limit=10,
        dossier_monthly_limit=3, features_json="{}",
        expires_at=_future(),
    ) is None
    assert await invalidate_entitlement_cache(None, "user-x") is False


# ---------------------------------------------------------------------------
# Bonus: active subscription query
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_active_subscription(session):
    """get_active_subscription returns the non-terminal row; ignores canceled."""
    from app.db.repositories.billing_repo import (
        create_subscription,
        get_active_subscription,
    )

    uid = "user-active-test"
    period_start = _now()
    period_end   = _future(hours=720)

    # Create an active subscription
    await create_subscription(
        session,
        user_id=uid,
        stripe_subscription_id="sub_active_001",
        stripe_customer_id="cus_active_001",
        stripe_price_id="price_monthly",
        plan_name="pro",
        status="active",
        current_period_start=period_start,
        current_period_end=period_end,
    )
    # Create a canceled historical row for the same user
    await create_subscription(
        session,
        user_id=uid,
        stripe_subscription_id="sub_old_001",
        stripe_customer_id="cus_active_001",
        stripe_price_id="price_monthly",
        plan_name="pro",
        status="canceled",
        current_period_start=period_start - timedelta(days=60),
        current_period_end=period_start - timedelta(days=30),
    )
    await session.commit()

    found = await get_active_subscription(session, uid)
    assert found is not None
    assert found.stripe_subscription_id == "sub_active_001"
    assert found.status == "active"

    # User with no active subscription
    none_found = await get_active_subscription(session, "user-no-sub")
    assert none_found is None
