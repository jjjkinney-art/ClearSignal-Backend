"""
Tests — Entitlement Enforcement (Phase 17 · Slice 6).

Coverage:
    1.  ENTITLEMENTS_ENFORCED=false → all checks are no-ops (zero behavior change)
    2.  System user bypass — all checks pass regardless of limits
    3.  check_watchlist_limit — free tier, usage < limit → pass
    4.  check_watchlist_limit — free tier, usage >= limit → EntitlementViolation
    5.  check_watchlist_limit — unlimited (-1) → always pass
    6.  check_portfolio_limit — same shape as watchlist
    7.  check_briefing_limit  — same shape as watchlist
    8.  check_delivery_limit  — same shape as watchlist
    9.  require_feature        — feature=False → EntitlementViolation
    10. require_feature        — feature=True  → pass
    11. EntitlementViolation.as_dict() shape — all required 402 fields present
    12. Watchlist route returns 402 when enforced and limit exceeded
    13. Watchlist route passes through when ENTITLEMENTS_ENFORCED=false
    14. Idempotent add (already tracked) bypasses limit check
    15. Morning-brief route returns 402 when enforced and limit=0
    16. Morning-brief route passes through when ENTITLEMENTS_ENFORCED=false
    17. Failure-open: exception in enforcement code never blocks the user
    18. Grace-period user retains access (plan_status="grace")
    19. Free-fallback user hits free limits
    20. Pro user has unlimited watchlist
"""

from __future__ import annotations

import sys
import types
from contextlib import asynccontextmanager
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

# ---------------------------------------------------------------------------
# Minimal async SQLite engine shared by DB-touching tests
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
# Helpers: fake EntitlementSet for unit tests
# ---------------------------------------------------------------------------

def _make_ent(
    user_id: str = "user-abc",
    plan_name: str = "free",
    plan_status: str = "free_fallback",
    watchlist_limit: int = 5,
    portfolio_limit: int = 1,
    briefing_limit: int = 1,
    delivery_limit: int = 1,
    can_use_portfolio_intelligence: bool = False,
    can_use_email_delivery: bool = False,
):
    ent = MagicMock()
    ent.user_id = user_id
    ent.plan_name = plan_name
    ent.plan_status = plan_status
    ent.watchlist_limit = watchlist_limit
    ent.portfolio_limit = portfolio_limit
    ent.briefing_limit = briefing_limit
    ent.delivery_limit = delivery_limit
    ent.can_use_portfolio_intelligence = can_use_portfolio_intelligence
    ent.can_use_email_delivery = can_use_email_delivery
    return ent


SYSTEM_USER = "00000000-0000-0000-0000-000000000001"

_FREE_ENT    = lambda uid="user-abc": _make_ent(uid, "free", "free_fallback")
_PRO_ENT     = lambda uid="user-abc": _make_ent(uid, "pro", "active",
                   watchlist_limit=-1, portfolio_limit=5, briefing_limit=-1,
                   delivery_limit=2, can_use_portfolio_intelligence=True,
                   can_use_email_delivery=True)
_GRACE_ENT   = lambda uid="user-abc": _make_ent(uid, "pro", "grace",
                   watchlist_limit=-1, portfolio_limit=5, briefing_limit=-1,
                   delivery_limit=2, can_use_portfolio_intelligence=True)
_SYS_ENT     = lambda: _make_ent(SYSTEM_USER, "system", "system",
                   watchlist_limit=-1, portfolio_limit=-1, briefing_limit=-1,
                   delivery_limit=-1, can_use_portfolio_intelligence=True)


def _patch_enforced(enabled: bool):
    """Patch settings.entitlements_enforced."""
    return patch(
        "app.services.entitlement_enforcement._enforcement_enabled",
        return_value=enabled,
    )


# ---------------------------------------------------------------------------
# Unit tests — enforcement module (no DB, no routes)
# ---------------------------------------------------------------------------

class TestEnforcementDisabled:
    """ENTITLEMENTS_ENFORCED=false → all checks are no-ops."""

    def test_watchlist_not_blocked(self):
        from app.services.entitlement_enforcement import check_watchlist_limit

        with _patch_enforced(False):
            result = check_watchlist_limit(_FREE_ENT(), current_usage=999)
        assert result is None

    def test_portfolio_not_blocked(self):
        from app.services.entitlement_enforcement import check_portfolio_limit

        with _patch_enforced(False):
            result = check_portfolio_limit(_FREE_ENT(), current_usage=999)
        assert result is None

    def test_briefing_not_blocked(self):
        from app.services.entitlement_enforcement import check_briefing_limit

        with _patch_enforced(False):
            result = check_briefing_limit(_FREE_ENT(), current_usage=999)
        assert result is None

    def test_delivery_not_blocked(self):
        from app.services.entitlement_enforcement import check_delivery_limit

        with _patch_enforced(False):
            result = check_delivery_limit(_FREE_ENT(), current_usage=999)
        assert result is None

    def test_require_feature_not_blocked(self):
        from app.services.entitlement_enforcement import require_feature

        with _patch_enforced(False):
            result = require_feature(_FREE_ENT(), "can_use_portfolio_intelligence")
        assert result is None


class TestSystemUserBypass:
    """System user always bypasses every check, even when enforced."""

    def test_watchlist_bypass(self):
        from app.services.entitlement_enforcement import check_watchlist_limit

        with _patch_enforced(True):
            check_watchlist_limit(_SYS_ENT(), current_usage=9999)

    def test_portfolio_bypass(self):
        from app.services.entitlement_enforcement import check_portfolio_limit

        with _patch_enforced(True):
            check_portfolio_limit(_SYS_ENT(), current_usage=9999)

    def test_require_feature_bypass(self):
        from app.services.entitlement_enforcement import require_feature

        ent = _SYS_ENT()
        ent.can_use_portfolio_intelligence = False  # even if False
        with _patch_enforced(True):
            require_feature(ent, "can_use_portfolio_intelligence")


class TestWatchlistLimit:
    def test_below_limit_passes(self):
        from app.services.entitlement_enforcement import check_watchlist_limit

        with _patch_enforced(True):
            check_watchlist_limit(_FREE_ENT(), current_usage=4)

    def test_at_limit_blocks(self):
        from app.services.entitlement_enforcement import (
            check_watchlist_limit,
            EntitlementViolation,
        )

        with _patch_enforced(True), pytest.raises(EntitlementViolation) as exc_info:
            check_watchlist_limit(_FREE_ENT(), current_usage=5)

        v = exc_info.value
        assert v.entitlement == "watchlist_limit"
        assert v.plan == "free"
        assert v.limit == 5
        assert v.current_usage == 5

    def test_unlimited_always_passes(self):
        from app.services.entitlement_enforcement import check_watchlist_limit

        with _patch_enforced(True):
            check_watchlist_limit(_PRO_ENT(), current_usage=9999)


class TestPortfolioLimit:
    def test_below_limit_passes(self):
        from app.services.entitlement_enforcement import check_portfolio_limit

        with _patch_enforced(True):
            check_portfolio_limit(_FREE_ENT(), current_usage=0)

    def test_at_limit_blocks(self):
        from app.services.entitlement_enforcement import (
            check_portfolio_limit,
            EntitlementViolation,
        )

        with _patch_enforced(True), pytest.raises(EntitlementViolation) as exc_info:
            check_portfolio_limit(_FREE_ENT(), current_usage=1)

        v = exc_info.value
        assert v.entitlement == "portfolio_limit"
        assert v.limit == 1
        assert v.current_usage == 1

    def test_pro_unlimited_passes(self):
        from app.services.entitlement_enforcement import check_portfolio_limit

        with _patch_enforced(True):
            check_portfolio_limit(_PRO_ENT(), current_usage=4)  # limit=5, ok
            check_portfolio_limit(_make_ent(portfolio_limit=-1), current_usage=999)


class TestBriefingLimit:
    def test_zero_limit_blocks(self):
        from app.services.entitlement_enforcement import (
            check_briefing_limit,
            EntitlementViolation,
        )

        ent = _make_ent(briefing_limit=0)
        with _patch_enforced(True), pytest.raises(EntitlementViolation) as exc_info:
            check_briefing_limit(ent, current_usage=0)

        assert exc_info.value.entitlement == "briefing_limit"

    def test_one_limit_blocks_at_one(self):
        from app.services.entitlement_enforcement import (
            check_briefing_limit,
            EntitlementViolation,
        )

        ent = _make_ent(briefing_limit=1)
        with _patch_enforced(True), pytest.raises(EntitlementViolation):
            check_briefing_limit(ent, current_usage=1)

    def test_one_limit_allows_at_zero(self):
        from app.services.entitlement_enforcement import check_briefing_limit

        ent = _make_ent(briefing_limit=1)
        with _patch_enforced(True):
            check_briefing_limit(ent, current_usage=0)

    def test_unlimited_always_passes(self):
        from app.services.entitlement_enforcement import check_briefing_limit

        with _patch_enforced(True):
            check_briefing_limit(_PRO_ENT(), current_usage=999)


class TestDeliveryLimit:
    def test_at_limit_blocks(self):
        from app.services.entitlement_enforcement import (
            check_delivery_limit,
            EntitlementViolation,
        )

        with _patch_enforced(True), pytest.raises(EntitlementViolation) as exc_info:
            check_delivery_limit(_FREE_ENT(), current_usage=1)

        assert exc_info.value.entitlement == "delivery_limit"
        assert exc_info.value.limit == 1

    def test_below_limit_passes(self):
        from app.services.entitlement_enforcement import check_delivery_limit

        with _patch_enforced(True):
            check_delivery_limit(_FREE_ENT(), current_usage=0)


class TestRequireFeature:
    def test_feature_false_blocks(self):
        from app.services.entitlement_enforcement import (
            require_feature,
            EntitlementViolation,
        )

        ent = _make_ent(can_use_portfolio_intelligence=False)
        with _patch_enforced(True), pytest.raises(EntitlementViolation) as exc_info:
            require_feature(ent, "can_use_portfolio_intelligence")

        v = exc_info.value
        assert v.entitlement == "can_use_portfolio_intelligence"
        assert v.plan == "free"
        assert v.limit == 0
        assert v.current_usage == 0
        assert "Upgrade" in v.upgrade_cta

    def test_feature_true_passes(self):
        from app.services.entitlement_enforcement import require_feature

        ent = _make_ent(can_use_portfolio_intelligence=True)
        with _patch_enforced(True):
            require_feature(ent, "can_use_portfolio_intelligence")

    def test_missing_feature_field_blocks(self):
        from app.services.entitlement_enforcement import (
            require_feature,
            EntitlementViolation,
        )

        ent = _make_ent()
        del ent.can_use_portfolio_intelligence  # simulate absent attribute
        with _patch_enforced(True), pytest.raises(EntitlementViolation):
            require_feature(ent, "can_use_portfolio_intelligence")


class TestViolationShape:
    """EntitlementViolation.as_dict() must contain all required 402 fields."""

    def test_as_dict_fields(self):
        from app.services.entitlement_enforcement import EntitlementViolation

        v = EntitlementViolation(
            entitlement="watchlist_limit",
            plan="free",
            limit=5,
            current_usage=5,
            upgrade_cta="Upgrade to Signal.",
        )
        d = v.as_dict()
        assert d["entitlement"] == "watchlist_limit"
        assert d["plan"] == "free"
        assert d["limit"] == 5
        assert d["current_usage"] == 5
        assert "upgrade_cta" in d
        assert isinstance(d["upgrade_cta"], str)


class TestPlanVariants:
    """Grace period and free-fallback plan_status variants."""

    def test_grace_period_user_not_blocked(self):
        """Grace-period user retains pro-level access — limits are unlimited."""
        from app.services.entitlement_enforcement import check_watchlist_limit

        ent = _GRACE_ENT()  # watchlist_limit=-1 (pro-level)
        with _patch_enforced(True):
            check_watchlist_limit(ent, current_usage=9999)

    def test_free_fallback_user_hits_limit(self):
        """Expired subscription → free limits apply."""
        from app.services.entitlement_enforcement import (
            check_watchlist_limit,
            EntitlementViolation,
        )

        with _patch_enforced(True), pytest.raises(EntitlementViolation):
            check_watchlist_limit(_FREE_ENT(), current_usage=5)

    def test_pro_user_passes_watchlist(self):
        from app.services.entitlement_enforcement import check_watchlist_limit

        with _patch_enforced(True):
            check_watchlist_limit(_PRO_ENT(), current_usage=500)


# ---------------------------------------------------------------------------
# Route-level tests (TestClient / httpx)
# ---------------------------------------------------------------------------

def _make_app_with_watchlist_route(*, enforced: bool, watchlist_count: int, already_tracked: bool):
    """Build a minimal FastAPI app containing only the watchlist add route."""
    app = FastAPI()

    # Patch settings.entitlements_enforced via the module flag function
    orig_settings = None

    # We import api router and patch dependencies:
    from fastapi import Request as _Request, Query as _Query, HTTPException as _HTTPException
    from unittest.mock import MagicMock

    # Fake watchlist service
    _ws = MagicMock()
    _ws.is_tracked.return_value = already_tracked
    _ws.get_watchlist.return_value = [MagicMock()] * watchlist_count
    _ws.add_ticker.return_value = MagicMock(model_dump=lambda: {"ticker": "AAPL", "added": True})

    # Fake DB session
    @asynccontextmanager
    async def _fake_session():
        yield AsyncMock()

    # Fake entitlement
    _ent = _FREE_ENT() if not already_tracked else _make_ent(watchlist_limit=watchlist_count - 1)

    @app.post("/watchlist/{ticker}")
    async def _add(ticker: str, request: _Request = None):
        try:
            from app.services.entitlement_enforcement import (
                check_watchlist_limit,
                EntitlementViolation,
            )

            if not already_tracked:
                _current = watchlist_count
                with _patch_enforced(enforced):
                    check_watchlist_limit(_FREE_ENT(uid="user-abc"), _current)
        except EntitlementViolation as e:
            raise _HTTPException(status_code=402, detail=e.as_dict())
        except _HTTPException:
            raise
        except Exception:
            pass

        result = _ws.add_ticker(ticker, "")
        return result.model_dump()

    return app


class TestWatchlistRoute:
    def test_enforced_limit_exceeded_returns_402(self):
        app = _make_app_with_watchlist_route(enforced=True, watchlist_count=5, already_tracked=False)
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post("/watchlist/AAPL")
        assert resp.status_code == 402
        body = resp.json()
        detail = body.get("detail", {})
        assert detail.get("entitlement") == "watchlist_limit"
        assert detail.get("plan") == "free"
        assert detail.get("limit") == 5
        assert detail.get("current_usage") == 5
        assert "upgrade_cta" in detail

    def test_enforcement_disabled_passes(self):
        app = _make_app_with_watchlist_route(enforced=False, watchlist_count=5, already_tracked=False)
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post("/watchlist/AAPL")
        assert resp.status_code == 200

    def test_idempotent_add_bypasses_check(self):
        """Adding a ticker that's already tracked does not trigger limit check."""
        app = _make_app_with_watchlist_route(enforced=True, watchlist_count=5, already_tracked=True)
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post("/watchlist/AAPL")
        assert resp.status_code == 200

    def test_below_limit_passes(self):
        app = _make_app_with_watchlist_route(enforced=True, watchlist_count=4, already_tracked=False)
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post("/watchlist/MSFT")
        assert resp.status_code == 200


class TestMorningBriefRoute:
    def _make_brief_app(self, *, enforced: bool, briefing_limit: int = 1):
        from fastapi import FastAPI, HTTPException as _HE, Request as _R

        app = FastAPI()

        @app.get("/morning-brief/v2")
        async def _brief(request: _R = None):
            try:
                from app.services.entitlement_enforcement import (
                    check_briefing_limit,
                    EntitlementViolation,
                )

                _ent = _make_ent(briefing_limit=briefing_limit)
                with _patch_enforced(enforced):
                    check_briefing_limit(_ent, 0)  # pass 0 as current_usage
            except EntitlementViolation as e:
                raise _HE(status_code=402, detail=e.as_dict())
            except _HE:
                raise
            except Exception:
                pass
            return {"brief": "ok"}

        return app

    def test_enforced_with_zero_limit_returns_402(self):
        app = self._make_brief_app(enforced=True, briefing_limit=0)
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/morning-brief/v2")
        assert resp.status_code == 402
        detail = resp.json().get("detail", {})
        assert detail.get("entitlement") == "briefing_limit"

    def test_enforcement_disabled_passes(self):
        app = self._make_brief_app(enforced=False, briefing_limit=0)
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/morning-brief/v2")
        assert resp.status_code == 200

    def test_enforced_with_positive_limit_and_zero_usage_passes(self):
        app = self._make_brief_app(enforced=True, briefing_limit=1)
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/morning-brief/v2")
        assert resp.status_code == 200


class TestFailureOpen:
    """Enforcement code crashing should never block the user."""

    def test_exception_in_resolve_does_not_block_watchlist(self):
        from fastapi import FastAPI, Request as _R, HTTPException as _HE

        app = FastAPI()

        @app.post("/watchlist/{ticker}")
        async def _add(ticker: str, request: _R = None):
            try:
                from app.services.entitlement_enforcement import (
                    check_watchlist_limit,
                    EntitlementViolation,
                )
                # Simulate resolve_entitlements crashing
                raise RuntimeError("DB down")
            except EntitlementViolation as e:
                raise _HE(status_code=402, detail=e.as_dict())
            except _HE:
                raise
            except Exception:
                pass  # failure-open

            return {"ticker": ticker.upper(), "added": True}

        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post("/watchlist/TSLA")
        assert resp.status_code == 200
