"""Integration tests for the portfolio router (beta milestone 2).

Drives the real router endpoint functions against the real persistence layer
(app.db.connection initialised on a temp-file SQLite DB) so every hop is
exercised: endpoint -> get_session -> portfolio_repo / portfolio services.

A temp file (not :memory:) is used because init_db does not pin an in-memory
SQLite to a single connection, so file-backed storage is what shares state
across the multiple get_session() calls a request makes.  Everything runs in
one event loop per test to avoid async cross-loop issues.

Runs on Python 3.9 (imports the routers module, not the full FastAPI app build).
"""

from __future__ import annotations

import asyncio
import os
import tempfile

import pytest

from app.routers import portfolio as pr


def _run(coro):
    return asyncio.run(coro)


async def _with_db(fn):
    """init a temp-file DB, run fn(), always close_db + unlink."""
    from app.db.connection import init_db, close_db
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    url = f"sqlite+aiosqlite:///{path}"
    try:
        await init_db(url)
        from conftest import create_test_schema
        await create_test_schema(url)
        return await fn()
    finally:
        await close_db()
        try:
            os.unlink(path)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Positions CRUD
# ---------------------------------------------------------------------------

def test_add_list_remove_positions_roundtrip():
    async def scenario():
        # Empty to start.
        assert await pr.list_positions(request=None) == []

        # Add two positions.
        b1 = pr.PositionRequest(ticker="nvda", membership_class="owned", weight=0.3)
        b2 = pr.PositionRequest(ticker="MSFT", membership_class="watchlist")
        r1 = await pr.add_position(b1, request=None)
        r2 = await pr.add_position(b2, request=None)
        assert r1["ticker"] == "NVDA" and r1["membership_class"] == "owned"
        assert r1["weight"] == 0.3
        assert r2["ticker"] == "MSFT"

        # List reflects both.
        listed = await pr.list_positions(request=None)
        tickers = {p["ticker"] for p in listed}
        assert {"NVDA", "MSFT"} <= tickers

        # Metadata endpoint counts them.
        meta = await pr.get_portfolio(request=None)
        assert meta["position_count"] == 2
        assert meta["portfolio_id"]

        # Remove one.
        rm = await pr.remove_position("NVDA", request=None)
        assert rm == {"ticker": "NVDA", "removed": True}
        remaining = {p["ticker"] for p in await pr.list_positions(request=None)}
        assert "NVDA" not in remaining and "MSFT" in remaining

    _run(_with_db(scenario))


def test_add_position_is_idempotent():
    async def scenario():
        b = pr.PositionRequest(ticker="AAPL", membership_class="owned")
        await pr.add_position(b, request=None)
        await pr.add_position(b, request=None)
        listed = [p for p in await pr.list_positions(request=None) if p["ticker"] == "AAPL"]
        assert len(listed) == 1
    _run(_with_db(scenario))


def test_remove_nonexistent_returns_false():
    async def scenario():
        rm = await pr.remove_position("ZZZZ", request=None)
        assert rm == {"ticker": "ZZZZ", "removed": False}
    _run(_with_db(scenario))


# ---------------------------------------------------------------------------
# Health / exposure / insights
# ---------------------------------------------------------------------------

def test_health_report_shape():
    async def scenario():
        for tk in ("NVDA", "AVGO", "TSM"):
            await pr.add_position(pr.PositionRequest(ticker=tk, membership_class="owned"), request=None)
        report = await pr.portfolio_health(request=None)
        # Real PortfolioHealthReport serialised to a dict.
        assert "concentration" in report
        assert "diversification" in report
        assert "warnings" in report
        assert "hhi" in report["concentration"]
        assert report["concentration"]["position_count"] == 3
    _run(_with_db(scenario))


def test_exposure_report_shape():
    async def scenario():
        await pr.add_position(pr.PositionRequest(ticker="NVDA", membership_class="owned"), request=None)
        projection = await pr.portfolio_exposure(request=None)
        assert isinstance(projection, dict)
        # PortfolioExposureProjection dataclass fields present.
        assert any(k in projection for k in ("shared_clusters", "exposure_pairs",
                                             "failure_clusters", "portfolio_id"))
    _run(_with_db(scenario))


def test_insights_empty_by_default():
    async def scenario():
        insights = await pr.portfolio_insights(request=None)
        assert insights == []          # none generated yet — read path returns []
    _run(_with_db(scenario))


# ---------------------------------------------------------------------------
# Validation + graceful degradation
# ---------------------------------------------------------------------------

def test_position_request_rejects_bad_membership():
    with pytest.raises(ValueError):
        pr.PositionRequest(ticker="NVDA", membership_class="core_holding")


def test_position_request_requires_ticker():
    with pytest.raises(ValueError):
        pr.PositionRequest(ticker="   ", membership_class="owned")


def test_endpoints_degrade_when_persistence_disabled():
    """With no DB initialised, get_session yields None and reads must not raise."""
    async def scenario():
        from app.db.connection import close_db
        await close_db()   # ensure disabled
        assert await pr.list_positions(request=None) == []
        assert await pr.portfolio_insights(request=None) == []
        meta = await pr.get_portfolio(request=None)
        assert meta["position_count"] == 0
        # health still returns a valid (empty) report, never raises
        report = await pr.portfolio_health(request=None)
        assert "concentration" in report
    _run(scenario())
