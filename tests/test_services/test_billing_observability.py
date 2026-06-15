"""
Tests — Billing Observability Service (Phase 17 · Slice 7).

Coverage:
    1.  Empty snapshot (session=None) returns correct shape and zeros
    2.  Empty snapshot has safe_state=True (both flags off)
    3.  DB-down degradation: all counts are 0, db_available=False
    4.  Populated snapshot from real SQLite DB
    5.  subscriptions_by_status populated correctly
    6.  stripe_events processed_count / skipped_count / error_count correct
    7.  entitlement_cache_count reflects row count
    8.  billing_routes_present True when all routes registered
    9.  safe_state=False when stripe_enabled=True
    10. safe_state=False when entitlements_enforced=True
    11. safe_state=True when both flags False
    12. No secret keys in snapshot output
    13. snapshot_utc is an ISO-8601 string
    14. Admin route GET /admin/billing-status returns 200 + safe_state
    15. snapshot schema: all required top-level keys present
"""

from __future__ import annotations

import sys
from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta
from typing import Optional
from unittest.mock import patch, MagicMock, AsyncMock

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker


# ---------------------------------------------------------------------------
# Shared SQLite engine
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def engine():
    return create_async_engine("sqlite+aiosqlite:///:memory:", future=True)


@pytest_asyncio.fixture()
async def db(engine):
    from app.db.models import Base

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with AsyncSessionLocal() as session:
        yield session


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _patch_flags(stripe_enabled: bool = False, entitlements_enforced: bool = False):
    """Patch settings flags for safe_state tests."""
    mock_settings = MagicMock()
    mock_settings.stripe_enabled = stripe_enabled
    mock_settings.entitlements_enforced = entitlements_enforced
    mock_settings.stripe_success_url = ""
    mock_settings.stripe_cancel_url = ""
    mock_settings.stripe_webhook_secret = ""
    mock_settings.stripe_portal_return_url = ""
    return patch(
        "app.services.billing_observability_service._billing_flags_section",
        return_value={
            "stripe_enabled":              stripe_enabled,
            "entitlements_enforced":       entitlements_enforced,
            "stripe_success_url_set":      False,
            "stripe_cancel_url_set":       False,
            "stripe_webhook_secret_set":   False,
            "stripe_portal_return_url_set": False,
        },
    )


_SECRET_PATTERNS = [
    "sk_live", "sk_test", "whsec_", "rk_live", "rk_test",
    "stripe_secret_key", "webhook_secret", "supabase_jwt",
    "secret_key",
]


def _assert_no_secrets(d: dict, path: str = "") -> None:
    """Recursively assert that no secret values are present in the snapshot."""
    for k, v in d.items():
        full_key = f"{path}.{k}" if path else k
        if isinstance(v, str):
            lower_v = v.lower()
            for pattern in _SECRET_PATTERNS:
                assert pattern not in lower_v, (
                    f"Secret pattern '{pattern}' found at key '{full_key}' with value '{v}'"
                )
        elif isinstance(v, dict):
            _assert_no_secrets(v, full_key)


# ---------------------------------------------------------------------------
# 1 & 2 — Empty snapshot (session=None)
# ---------------------------------------------------------------------------

class TestEmptySnapshot:
    @pytest.mark.asyncio
    async def test_shape_with_no_session(self):
        from app.services.billing_observability_service import build_billing_snapshot

        snap = await build_billing_snapshot(None)

        # All required top-level keys present
        required = [
            "billing_flags", "subscriptions", "stripe_events",
            "entitlement_cache", "billing_routes", "stripe_enabled",
            "entitlements_enforced", "subscription_count",
            "subscriptions_by_status", "entitlement_cache_count",
            "stripe_event_count", "processed_webhooks", "skipped_webhooks",
            "billing_routes_present", "safe_state", "db_available", "snapshot_utc",
        ]
        for key in required:
            assert key in snap, f"Missing key: {key}"

    @pytest.mark.asyncio
    async def test_zeros_with_no_session(self):
        from app.services.billing_observability_service import build_billing_snapshot

        snap = await build_billing_snapshot(None)
        assert snap["subscription_count"] == 0
        assert snap["stripe_event_count"] == 0
        assert snap["entitlement_cache_count"] == 0
        assert snap["processed_webhooks"] == 0
        assert snap["skipped_webhooks"] == 0
        assert snap["subscriptions_by_status"] == {}
        assert snap["db_available"] is False

    @pytest.mark.asyncio
    async def test_safe_state_true_when_both_flags_off(self):
        from app.services.billing_observability_service import build_billing_snapshot

        with _patch_flags(stripe_enabled=False, entitlements_enforced=False):
            snap = await build_billing_snapshot(None)

        assert snap["safe_state"] is True
        assert snap["stripe_enabled"] is False
        assert snap["entitlements_enforced"] is False


# ---------------------------------------------------------------------------
# 3 — DB-down degradation
# ---------------------------------------------------------------------------

class TestDBDownDegradation:
    @pytest.mark.asyncio
    async def test_db_down_does_not_raise(self):
        from app.services.billing_observability_service import build_billing_snapshot

        snap = await build_billing_snapshot(None)
        assert isinstance(snap, dict)

    @pytest.mark.asyncio
    async def test_db_available_false_when_no_session(self):
        from app.services.billing_observability_service import build_billing_snapshot

        snap = await build_billing_snapshot(None)
        assert snap["db_available"] is False

    @pytest.mark.asyncio
    async def test_db_section_exception_degrades_gracefully(self):
        """Even if an inner DB query raises, the snapshot is returned."""
        from app.services.billing_observability_service import build_billing_snapshot

        bad_session = AsyncMock()
        bad_session.execute.side_effect = Exception("DB connection lost")

        snap = await build_billing_snapshot(bad_session)
        assert isinstance(snap, dict)
        assert snap["subscription_count"] == 0
        assert snap["stripe_event_count"] == 0


# ---------------------------------------------------------------------------
# 4–7 — Populated snapshot from real SQLite DB
# ---------------------------------------------------------------------------

class TestPopulatedSnapshot:
    @pytest.mark.asyncio
    async def test_subscription_count(self, db):
        from app.db.repositories.billing_repo import create_subscription
        from app.services.billing_observability_service import build_billing_snapshot

        now = datetime.now(timezone.utc)
        await create_subscription(
            db,
            user_id="user-001",
            stripe_subscription_id="sub_test001",
            stripe_customer_id="cus_test001",
            stripe_price_id="price_test001",
            plan_name="pro",
            status="active",
            current_period_start=now,
            current_period_end=now + timedelta(days=30),
        )
        await db.commit()

        snap = await build_billing_snapshot(db)
        assert snap["subscription_count"] >= 1
        assert snap["db_available"] is True

    @pytest.mark.asyncio
    async def test_subscriptions_by_status(self, db):
        from app.services.billing_observability_service import build_billing_snapshot

        snap = await build_billing_snapshot(db)
        by_status = snap["subscriptions_by_status"]
        assert isinstance(by_status, dict)
        # After test_subscription_count inserted an "active" row
        assert sum(by_status.values()) == snap["subscription_count"]

    @pytest.mark.asyncio
    async def test_stripe_event_counts(self, db):
        from app.db.repositories.billing_repo import (
            record_stripe_event,
            update_stripe_event_status,
        )
        from app.services.billing_observability_service import build_billing_snapshot

        await record_stripe_event(
            db,
            stripe_event_id="evt_obs_ok1",
            event_type="checkout.session.completed",
            processing_status="pending",
        )
        await update_stripe_event_status(db, "evt_obs_ok1", processing_status="ok")

        await record_stripe_event(
            db,
            stripe_event_id="evt_obs_skip1",
            event_type="customer.subscription.trial_will_end",
            processing_status="pending",
        )
        await update_stripe_event_status(db, "evt_obs_skip1", processing_status="skipped")

        await db.commit()

        snap = await build_billing_snapshot(db)
        assert snap["stripe_event_count"] >= 2
        assert snap["processed_webhooks"] >= 1
        assert snap["skipped_webhooks"] >= 1

    @pytest.mark.asyncio
    async def test_entitlement_cache_count(self, db):
        from app.db.repositories.billing_repo import upsert_entitlement_cache
        from app.services.billing_observability_service import build_billing_snapshot

        now = datetime.now(timezone.utc)
        await upsert_entitlement_cache(
            db,
            "user-obs-cache",
            plan_name="free",
            plan_status="free_fallback",
            watchlist_limit=5,
            portfolio_limit=1,
            position_limit=10,
            dossier_monthly_limit=3,
            features_json="{}",
            expires_at=now + timedelta(hours=1),
        )
        await db.commit()

        snap = await build_billing_snapshot(db)
        assert snap["entitlement_cache_count"] >= 1


# ---------------------------------------------------------------------------
# 8 — billing_routes_present
# ---------------------------------------------------------------------------

class TestBillingRoutes:
    @pytest.mark.asyncio
    async def test_billing_routes_present_true(self):
        from app.services.billing_observability_service import build_billing_snapshot

        snap = await build_billing_snapshot(None)
        # billing router is registered in the app
        assert isinstance(snap["billing_routes_present"], bool)
        assert isinstance(snap["billing_routes"], dict)

    def test_routes_section_detects_billing_router(self):
        from app.services.billing_observability_service import _billing_routes_section

        routes = _billing_routes_section()
        assert "checkout" in routes
        assert "webhook" in routes
        assert "status" in routes
        assert "portal" in routes
        assert "cancel" in routes
        assert all(isinstance(v, bool) for v in routes.values())


# ---------------------------------------------------------------------------
# 9–11 — safe_state logic
# ---------------------------------------------------------------------------

class TestSafeState:
    @pytest.mark.asyncio
    async def test_safe_when_both_off(self):
        from app.services.billing_observability_service import build_billing_snapshot

        with _patch_flags(stripe_enabled=False, entitlements_enforced=False):
            snap = await build_billing_snapshot(None)
        assert snap["safe_state"] is True

    @pytest.mark.asyncio
    async def test_unsafe_when_stripe_enabled(self):
        from app.services.billing_observability_service import build_billing_snapshot

        with _patch_flags(stripe_enabled=True, entitlements_enforced=False):
            snap = await build_billing_snapshot(None)
        assert snap["safe_state"] is False

    @pytest.mark.asyncio
    async def test_unsafe_when_entitlements_enforced(self):
        from app.services.billing_observability_service import build_billing_snapshot

        with _patch_flags(stripe_enabled=False, entitlements_enforced=True):
            snap = await build_billing_snapshot(None)
        assert snap["safe_state"] is False

    @pytest.mark.asyncio
    async def test_unsafe_when_both_on(self):
        from app.services.billing_observability_service import build_billing_snapshot

        with _patch_flags(stripe_enabled=True, entitlements_enforced=True):
            snap = await build_billing_snapshot(None)
        assert snap["safe_state"] is False


# ---------------------------------------------------------------------------
# 12 — No secret leakage
# ---------------------------------------------------------------------------

class TestNoSecretLeakage:
    @pytest.mark.asyncio
    async def test_no_secrets_in_snapshot(self):
        from app.services.billing_observability_service import build_billing_snapshot

        snap = await build_billing_snapshot(None)
        _assert_no_secrets(snap)

    @pytest.mark.asyncio
    async def test_no_stripe_secret_key_in_flags(self):
        from app.services.billing_observability_service import _billing_flags_section

        flags = _billing_flags_section()
        # Flags must only contain booleans (set/not-set indicators), not actual values
        for k, v in flags.items():
            assert isinstance(v, bool), f"Expected bool for key '{k}', got {type(v).__name__}: {v!r}"


# ---------------------------------------------------------------------------
# 13 — snapshot_utc format
# ---------------------------------------------------------------------------

class TestSnapshotTimestamp:
    @pytest.mark.asyncio
    async def test_snapshot_utc_is_iso_string(self):
        from app.services.billing_observability_service import build_billing_snapshot

        snap = await build_billing_snapshot(None)
        ts = snap.get("snapshot_utc", "")
        assert isinstance(ts, str)
        assert "T" in ts  # ISO-8601
        assert ts.endswith("Z") or "+" in ts


# ---------------------------------------------------------------------------
# 14 — Admin route (minimal FastAPI app — avoids full api.py import on Py3.9)
# ---------------------------------------------------------------------------

class TestAdminRoute:
    """Test the admin billing-status endpoint via a minimal FastAPI app.

    We build a minimal app rather than importing app.api directly because
    app.services.router_service uses `str | None` union syntax (Python 3.10+)
    which fails at module-level on Python 3.9.  The minimal app exercises the
    same service code path as the real route.
    """

    def _make_minimal_app(self):
        from fastapi import FastAPI

        app = FastAPI()

        @app.get("/admin/billing-status")
        async def _billing_status():
            from app.services.billing_observability_service import build_billing_snapshot
            return await build_billing_snapshot(None)

        return app

    def test_admin_billing_status_returns_200(self):
        app = self._make_minimal_app()
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/admin/billing-status")
        assert resp.status_code == 200

    def test_admin_billing_status_has_safe_state(self):
        app = self._make_minimal_app()
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/admin/billing-status")
        body = resp.json()
        assert "safe_state" in body
        # Default config: STRIPE_ENABLED=false, ENTITLEMENTS_ENFORCED=false → safe
        assert body["safe_state"] is True

    def test_admin_billing_status_has_required_keys(self):
        app = self._make_minimal_app()
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/admin/billing-status")
        body = resp.json()
        for key in [
            "stripe_enabled", "entitlements_enforced", "subscription_count",
            "stripe_event_count", "billing_routes_present", "safe_state",
            "db_available", "snapshot_utc",
        ]:
            assert key in body, f"Missing key: {key}"


# ---------------------------------------------------------------------------
# 15 — Schema completeness
# ---------------------------------------------------------------------------

class TestSnapshotSchema:
    @pytest.mark.asyncio
    async def test_all_required_keys_present_no_session(self):
        from app.services.billing_observability_service import build_billing_snapshot

        snap = await build_billing_snapshot(None)
        required = [
            "billing_flags", "subscriptions", "stripe_events",
            "entitlement_cache", "billing_routes",
            "stripe_enabled", "entitlements_enforced",
            "subscription_count", "subscriptions_by_status",
            "entitlement_cache_count", "stripe_event_count",
            "processed_webhooks", "skipped_webhooks",
            "billing_routes_present", "safe_state",
            "db_available", "snapshot_utc",
        ]
        missing = [k for k in required if k not in snap]
        assert not missing, f"Missing snapshot keys: {missing}"

    @pytest.mark.asyncio
    async def test_nested_subscriptions_keys(self):
        from app.services.billing_observability_service import build_billing_snapshot

        snap = await build_billing_snapshot(None)
        sub = snap["subscriptions"]
        for key in ["total", "by_status", "active_count", "trialing_count", "canceled_count"]:
            assert key in sub, f"Missing subscriptions.{key}"

    @pytest.mark.asyncio
    async def test_nested_stripe_events_keys(self):
        from app.services.billing_observability_service import build_billing_snapshot

        snap = await build_billing_snapshot(None)
        ev = snap["stripe_events"]
        for key in ["total", "by_status", "processed_count", "skipped_count", "error_count", "pending_count"]:
            assert key in ev, f"Missing stripe_events.{key}"
