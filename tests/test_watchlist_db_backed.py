"""Watchlist DB-backed membership path (Phase 10B · Slice 2 activation).

Verifies the async DB path that the /watchlist endpoints route through when
``watchlist_db_backed`` is enabled: add -> list -> is_tracked -> remove, scoped
by user_id, against an in-memory SQLite database.  This is the exact code path
promoted from shadow in the beta activation; the endpoints call these same
`watchlist_service.*_async` methods.

Runs on Python 3.9 (does not import the FastAPI app / router_service).
"""

from __future__ import annotations

import asyncio

import pytest

from app.services.watchlist_service import watchlist_service

_USER = "00000000-0000-0000-0000-000000000001"   # SYSTEM_DEFAULT_USER_ID / bypass user


async def _make_session():
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
    from app.db.models import Base
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    return engine, maker


def test_db_backed_add_list_remove_roundtrip():
    async def _run():
        engine, maker = await _make_session()
        try:
            async with maker() as db:
                # Add two tickers under the bypass user.
                e1 = await watchlist_service.add_ticker_async(db, "NVDA", "NVIDIA", user_id=_USER)
                e2 = await watchlist_service.add_ticker_async(db, "msft", "Microsoft", user_id=_USER)
                await db.commit()
                assert e1.ticker == "NVDA"
                assert e2.ticker == "MSFT"          # normalised upper-case

                # List returns both, DB-backed.
                entries = await watchlist_service.get_watchlist_async(db, user_id=_USER)
                tickers = {e.ticker for e in entries}
                assert {"NVDA", "MSFT"} <= tickers

                # is_tracked reflects membership.
                assert await watchlist_service.is_tracked_async(db, "NVDA", user_id=_USER) is True
                assert await watchlist_service.is_tracked_async(db, "AAPL", user_id=_USER) is False

                # Remove one; membership updates.
                removed = await watchlist_service.remove_ticker_async(db, "NVDA", user_id=_USER)
                await db.commit()
                assert removed is True
                assert await watchlist_service.is_tracked_async(db, "NVDA", user_id=_USER) is False
        finally:
            await engine.dispose()

    asyncio.run(_run())


def test_add_is_idempotent():
    async def _run():
        engine, maker = await _make_session()
        try:
            async with maker() as db:
                await watchlist_service.add_ticker_async(db, "TSLA", "Tesla", user_id=_USER)
                await watchlist_service.add_ticker_async(db, "TSLA", "Tesla", user_id=_USER)
                await db.commit()
                entries = await watchlist_service.get_watchlist_async(db, user_id=_USER)
                tsla = [e for e in entries if e.ticker == "TSLA"]
                assert len(tsla) == 1, "duplicate add must be idempotent"
        finally:
            await engine.dispose()

    asyncio.run(_run())


def test_flag_default_is_off():
    """The activation flag must default to False so existing deployments keep
    the JSON-file behaviour until explicitly opted in."""
    from app.config import settings
    assert settings.watchlist_db_backed is False
