"""Auth scoping / multi-tenancy tests — beta milestone 5.

Verifies that the product routers resolve identity through the hardened
`require_user_id` dependency so that:
  * user A never sees user B's data (portfolio, watchlist, notifications),
  * an unauthenticated request under enforcement mode is rejected (401),
  * bypass mode / no-middleware still resolves to the system user (dev/local).

The AuthMiddleware output is simulated by attaching a `.state.user_id` to a
lightweight request object — the same contract the real middleware fulfils
(bypass user when AUTH_ENABLED=false, JWT `sub` when a valid token is present,
None when AUTH_ENABLED=true and no/invalid token).

Runs on Python 3.9 (temp-file SQLite; no full app server needed).
"""

from __future__ import annotations

import asyncio
import os
import tempfile
from types import SimpleNamespace

import pytest

from app.routers import portfolio as pr
from app.routers import notifications as nr
from app.routers import billing as br
from app.routers import delivery_preferences as dpr

_SYS = "00000000-0000-0000-0000-000000000001"
_USER_A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
_USER_B = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"


def _req(user_id):
    """A minimal stand-in for a post-middleware Request."""
    return SimpleNamespace(state=SimpleNamespace(
        user_id=user_id, auth_subject=user_id, is_authenticated=user_id is not None))


async def _with_db(fn):
    from app.db.connection import init_db, close_db
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        await init_db(f"sqlite+aiosqlite:///{path}")
        from conftest import create_test_schema
        await create_test_schema(f"sqlite+aiosqlite:///{path}")
        return await fn()
    finally:
        await close_db()
        try:
            os.unlink(path)
        except OSError:
            pass


def _run(fn):
    asyncio.run(_with_db(fn))


# ---------------------------------------------------------------------------
# Portfolio — user isolation
# ---------------------------------------------------------------------------

def test_portfolio_user_a_cannot_see_user_b():
    async def scenario():
        await pr.add_position(pr.PositionRequest(ticker="NVDA", membership_class="owned"),
                              request=_req(_USER_A))
        await pr.add_position(pr.PositionRequest(ticker="MSFT", membership_class="owned"),
                              request=_req(_USER_B))

        a_tickers = {p["ticker"] for p in await pr.list_positions(request=_req(_USER_A))}
        b_tickers = {p["ticker"] for p in await pr.list_positions(request=_req(_USER_B))}

        assert a_tickers == {"NVDA"}, a_tickers
        assert b_tickers == {"MSFT"}, b_tickers
        assert "MSFT" not in a_tickers and "NVDA" not in b_tickers
    _run(scenario)


def test_portfolio_scoped_by_user_metadata():
    async def scenario():
        await pr.add_position(pr.PositionRequest(ticker="AAPL"), request=_req(_USER_A))
        meta_a = await pr.get_portfolio(request=_req(_USER_A))
        meta_b = await pr.get_portfolio(request=_req(_USER_B))
        assert meta_a["position_count"] == 1
        assert meta_b["position_count"] == 0
        assert meta_a["portfolio_id"] != meta_b["portfolio_id"]
    _run(scenario)


# ---------------------------------------------------------------------------
# Watchlist — user isolation (DB-backed membership path)
# ---------------------------------------------------------------------------

def test_watchlist_scoped_by_user():
    async def scenario():
        from app.db.connection import get_session
        from app.services.watchlist_service import watchlist_service
        async with get_session() as db:
            await watchlist_service.add_ticker_async(db, "NVDA", "NVIDIA", user_id=_USER_A)
            await watchlist_service.add_ticker_async(db, "TSLA", "Tesla", user_id=_USER_B)
            await db.commit()
        async with get_session() as db:
            a = {e.ticker for e in await watchlist_service.get_watchlist_async(db, user_id=_USER_A)}
            b = {e.ticker for e in await watchlist_service.get_watchlist_async(db, user_id=_USER_B)}
        assert "NVDA" in a and "TSLA" not in a
        assert "TSLA" in b and "NVDA" not in b
    _run(scenario)


def test_empty_account_watchlist_never_inherits_legacy_membership(tmp_path):
    """A new authenticated account must see an authoritative empty list."""
    async def scenario():
        from app.db.connection import get_session
        from app.services.watchlist_service import WatchlistService

        service = WatchlistService(
            data_dir=str(tmp_path / "watchlist"),
            timeline_dir=str(tmp_path / "timeline"),
        )
        service._add_ticker_file("SPGI", "S&P Global")

        async with get_session() as db:
            assert await service.get_watchlist_async(db, user_id=_USER_A) == []
            assert await service.get_entry_async(db, "SPGI", user_id=_USER_A) is None
            assert not await service.is_tracked_async(db, "SPGI", user_id=_USER_A)
    _run(scenario)


def test_account_watchlist_writes_never_mutate_shared_legacy_index(tmp_path):
    """User B cannot remove User A's row or shared file metadata."""
    async def scenario():
        from app.db.connection import get_session
        from app.services.watchlist_service import WatchlistService

        service = WatchlistService(
            data_dir=str(tmp_path / "watchlist"),
            timeline_dir=str(tmp_path / "timeline"),
        )
        service._add_ticker_file("SPGI", "S&P Global")

        async with get_session() as db:
            await service.add_ticker_async(db, "NVDA", "NVIDIA", user_id=_USER_A)
            await db.commit()

            assert "NVDA" not in service._load_index()
            assert await service.remove_ticker_async(db, "NVDA", user_id=_USER_B) is False
            assert await service.is_tracked_async(db, "NVDA", user_id=_USER_A) is True
            assert "SPGI" in service._load_index()
    _run(scenario)


def test_authenticated_watchlist_db_failure_fails_closed(monkeypatch):
    """A persistence outage must not expose the shared file fallback."""
    async def scenario():
        from fastapi import HTTPException
        from app import api

        async def fail_db(*args, **kwargs):
            raise RuntimeError("database unavailable")

        def forbidden_file_fallback():
            raise AssertionError("authenticated request reached shared file fallback")

        monkeypatch.setattr(api.watchlist_service, "get_watchlist_async", fail_db)
        monkeypatch.setattr(api.watchlist_service, "get_watchlist", forbidden_file_fallback)

        with pytest.raises(HTTPException) as exc:
            await api.get_watchlist(request=_req(_USER_A))
        assert exc.value.status_code == 503
    _run(scenario)


# ---------------------------------------------------------------------------
# Notifications — read-state scoped by user
# ---------------------------------------------------------------------------

def test_notification_read_state_scoped_by_user():
    async def scenario():
        from app.db.connection import get_session
        from app.db.models import DeliveryLedger
        async with get_session() as db:
            row = DeliveryLedger(
                content_key="ck-shared", target_key="NVDA", content_hash="h",
                channel="in_app", status="delivered_shadow",
                canonical_severity="high", severity_rank=4,
            )
            db.add(row)
            await db.flush()
            did = row.id

        # User A marks it read; user B does not.
        await nr.mark_notifications_read(nr.MarkReadRequest(delivery_id=did), request=_req(_USER_A))

        unread_a = await nr.unread_notifications(request=_req(_USER_A))
        unread_b = await nr.unread_notifications(request=_req(_USER_B))
        assert unread_a["count"] == 0, "A marked it read"
        assert unread_b["count"] == 1, "B's read-state is independent"
    _run(scenario)


# ---------------------------------------------------------------------------
# Preferences — user isolation and IDOR protection
# ---------------------------------------------------------------------------

def test_delivery_preferences_are_scoped_and_cross_user_override_is_forbidden():
    async def scenario():
        from fastapi import HTTPException

        changed = await dpr.patch_delivery_preferences(
            _req(_USER_A),
            dpr.DeliveryPrefsPatch(enabled=False, daily_cap=7),
            channel="in_app",
            user_id=None,
        )
        other = await dpr.get_delivery_preferences(
            _req(_USER_B), channel="in_app", user_id=None,
        )

        assert changed.user_id == _USER_A
        assert changed.enabled is False and changed.daily_cap == 7
        assert other.user_id == _USER_B
        assert other.row_exists is False and other.enabled is True

        with pytest.raises(HTTPException) as exc:
            await dpr.get_delivery_preferences(
                _req(_USER_A), channel="in_app", user_id=_USER_B,
            )
        assert exc.value.status_code == 403
    _run(scenario)


# ---------------------------------------------------------------------------
# Billing — user isolation and fail-closed authentication
# ---------------------------------------------------------------------------

def test_billing_status_is_scoped_to_the_authenticated_user():
    async def scenario():
        from app.db.connection import get_session
        from app.db.models import User

        async with get_session() as db:
            db.add_all([
                User(id=_USER_A, email="a@example.test", plan="free"),
                User(
                    id=_USER_B,
                    email="b@example.test",
                    plan="free",
                    stripe_customer_id="cus_user_b",
                ),
            ])
            await db.commit()

        status_a = await br.billing_status(_req(_USER_A))
        status_b = await br.billing_status(_req(_USER_B))

        assert status_a["user_id"] == _USER_A
        assert status_b["user_id"] == _USER_B
        assert status_a["stripe_customer_present"] is False
        assert status_b["stripe_customer_present"] is True
    _run(scenario)


def test_billing_status_rejects_missing_authenticated_identity():
    from fastapi import HTTPException

    async def scenario():
        with pytest.raises(HTTPException) as exc:
            await br.billing_status(_req(None))
        assert exc.value.status_code == 401
    _run(scenario)


# ---------------------------------------------------------------------------
# Auth-mode behavior: unauthenticated 401 + disabled/bypass fallback
# ---------------------------------------------------------------------------

def test_unauthenticated_enforcement_is_rejected():
    """user_id=None on the request state models AUTH_ENABLED=true with no valid
    JWT; require_user_id must raise 401 rather than fall back to the bypass user."""
    from fastapi import HTTPException

    async def scenario():
        with pytest.raises(HTTPException) as ei:
            await pr.list_positions(request=_req(None))
        assert ei.value.status_code == 401
    _run(scenario)


def test_bypass_user_when_state_present():
    """AUTH_ENABLED=false: middleware stamps the bypass user; endpoints serve it."""
    async def scenario():
        await pr.add_position(pr.PositionRequest(ticker="KO"), request=_req(_SYS))
        tickers = {p["ticker"] for p in await pr.list_positions(request=_req(_SYS))}
        assert tickers == {"KO"}
    _run(scenario)


def test_no_middleware_falls_back_to_system_user():
    """request=None (no middleware, e.g. a direct-call unit test) resolves to the
    system user so local/dev testability is preserved."""
    from app.dependencies.auth import require_user_id
    assert require_user_id(None) == _SYS


def test_require_user_id_raises_on_none_state_user():
    from app.dependencies.auth import require_user_id
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as ei:
        require_user_id(_req(None))
    assert ei.value.status_code == 401
