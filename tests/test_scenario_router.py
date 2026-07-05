"""Integration tests for the scenario router (beta milestone 3).

Drives the real router endpoint functions against the real persistence layer
(app.db.connection on a temp-file SQLite DB), seeding a valid scenario snapshot
via scenario_repo so the read path is exercised end to end:
endpoint -> get_session -> scenario_read_service -> scenario_repo.

A temp file (not :memory:) is used because init_db does not pin an in-memory
SQLite to a single connection.  Everything runs in one event loop per test.

Runs on Python 3.9 (imports the routers module, not the full FastAPI app build).
"""

from __future__ import annotations

import asyncio
import os
import tempfile

import pytest

from app.routers import scenario as sr

_USER = "00000000-0000-0000-0000-000000000001"   # bypass user (what request=None resolves to)


async def _seed_valid_scenario(db, ticker: str = "NVDA"):
    """Seed one snapshot that passes the read-layer validity filter
    (future expiry + what_changed + evidence + transmission_path)."""
    from app.db.repositories.scenario_repo import upsert_scenario_snapshot
    await upsert_scenario_snapshot(
        db,
        scenario_type="macro_scenario",   # must be in scenario_read_service._SUPPORTED_TYPES
        entity_type="company",
        entity_key=ticker,
        scenario_key="rate_shock",
        condition="Fed hikes 100bps beyond consensus",
        transmission_path=["rates", "equity_multiple", ticker],
        scenario_impact="negative",
        plausibility_band="plausible",
        confidence_score=0.7,
        what_changed="Policy rate rises 100bps above the forward curve",
        why_it_matters="Long-duration, high-multiple equities de-rate first",
        evidence_summary=["2s10s re-inversion", "hot CPI print"],
        invalidators=["Fed pauses", "inflation < 3%"],
        user_id=_USER,
        ttl_hours=168,   # 7 days — required so expires_at is in the future
    )


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


# ---------------------------------------------------------------------------
# Seeded read paths
# ---------------------------------------------------------------------------

def test_scenarios_for_ticker_returns_seeded():
    async def scenario():
        from app.db.connection import get_session
        async with get_session() as db:
            await _seed_valid_scenario(db, "NVDA")
        payload = await sr.scenarios_for_ticker("nvda", request=None)
        assert payload["ticker"] == "NVDA"
        assert payload["has_scenarios"] is True
        assert payload["count"] >= 1
        assert isinstance(payload["scenarios"], list)
    _with_db_run(scenario)


def test_scenario_facet_returns_summary():
    async def scenario():
        from app.db.connection import get_session
        async with get_session() as db:
            await _seed_valid_scenario(db, "NVDA")
        facet = await sr.scenario_facet("NVDA", request=None)
        assert facet["ticker"] == "NVDA"
        assert facet["has_scenarios"] is True
        # facet-level summary fields present
        assert "top_plausibility" in facet
        assert "top_confidence" in facet
        assert "type_counts" in facet
    _with_db_run(scenario)


def test_list_scenarios_top_shape():
    async def scenario():
        from app.db.connection import get_session
        async with get_session() as db:
            await _seed_valid_scenario(db, "NVDA")
        payload = await sr.list_scenarios(request=None)
        assert isinstance(payload, dict)
        assert "scenarios" in payload
    _with_db_run(scenario)


# ---------------------------------------------------------------------------
# Empty + degradation paths
# ---------------------------------------------------------------------------

def test_unknown_ticker_returns_empty():
    async def scenario():
        payload = await sr.scenarios_for_ticker("ZZZZ", request=None)
        assert payload["ticker"] == "ZZZZ"
        assert payload["has_scenarios"] is False
        assert payload["count"] == 0
    _with_db_run(scenario)


def test_endpoints_degrade_when_persistence_disabled():
    async def scenario():
        from app.db.connection import close_db
        await close_db()   # ensure disabled
        f = await sr.scenario_facet("NVDA", request=None)
        assert f["has_scenarios"] is False
        t = await sr.scenarios_for_ticker("NVDA", request=None)
        assert t["count"] == 0
    asyncio.run(scenario())


# ---------------------------------------------------------------------------
# helper
# ---------------------------------------------------------------------------

def _with_db_run(coro_fn):
    asyncio.run(_with_db(coro_fn))
