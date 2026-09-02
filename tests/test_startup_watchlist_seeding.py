"""Section 0.8B — the Phase 10B startup seed must be idempotent across boots.

These tests drive the REAL ``app.main.lifespan`` startup path against a
disposable in-memory database, with ``app.db.get_session`` patched to hand the
startup hooks that database. They are not a re-implementation of the startup
logic: removing the explicit ``user_id`` argument from the Phase 10B call site
makes them fail.

The bug they pin (Section 0.8B):

    ``ticker_add`` deduplicates within ONE ownership namespace. The Phase 10B
    seed used to insert with ``user_id`` unset (NULL). The Phase 16.2 hook
    later in the same startup runs
    ``UPDATE ... SET user_id = SYSTEM_DEFAULT_USER_ID WHERE user_id IS NULL``.
    So the next boot searched the NULL namespace, found it empty, and
    re-inserted every ticker — one duplicate row per index.json ticker, per
    boot, forever.

Seeding directly into the system-owner namespace makes the dedup lookup run
where the rows permanently live.

Scope note: this does NOT close the concurrent-insert race. Two simultaneous
inserts can still both miss. Only a database unique index closes that, and
that migration is deliberately not part of this change.

Python 3.9 compatible.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

import pytest

from app.services.system_user_service import SYSTEM_DEFAULT_USER_ID

REAL_USER = "cccccccc-0000-0000-0000-00000000000c"


class _Entry:
    """Minimal stand-in for a WatchlistEntry as get_watchlist() returns it."""

    def __init__(self, ticker: str, company_name: str = ""):
        self.ticker = ticker
        self.company_name = company_name or ticker


async def _make_engine():
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
    from app.db.models import Base

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


async def _boot(monkeypatch, maker, tickers):
    """Run the real startup lifespan once against `maker`'s database."""
    import app.db as _db
    import app.main as _main
    from app.services.watchlist_service import watchlist_service

    session = maker()

    @asynccontextmanager
    async def _fake_get_session():
        yield session

    monkeypatch.setattr(_db, "get_session", _fake_get_session, raising=True)
    monkeypatch.setattr(
        watchlist_service, "get_watchlist",
        lambda *a, **k: [_Entry(t) for t in tickers], raising=True,
    )
    try:
        async with _main.lifespan(None):
            pass
    finally:
        await session.commit()
        await session.close()


async def _counts(maker):
    from sqlalchemy import select, func
    from app.db.models import WatchedTicker

    async with maker() as db:
        active_sys = (await db.execute(
            select(func.count()).select_from(WatchedTicker)
            .where(WatchedTicker.active.is_(True))
            .where(WatchedTicker.user_id == SYSTEM_DEFAULT_USER_ID)
        )).scalar()
        active_null = (await db.execute(
            select(func.count()).select_from(WatchedTicker)
            .where(WatchedTicker.active.is_(True))
            .where(WatchedTicker.user_id.is_(None))
        )).scalar()
        total = (await db.execute(
            select(func.count()).select_from(WatchedTicker)
        )).scalar()
        sub = (
            select(func.count().label("c")).select_from(WatchedTicker)
            .where(WatchedTicker.active.is_(True))
            .where(WatchedTicker.user_id.isnot(None))
            .group_by(WatchedTicker.user_id, WatchedTicker.ticker)
            .having(func.count() > 1).subquery()
        )
        groups, excess = (await db.execute(
            select(func.count(), func.coalesce(func.sum(sub.c.c - 1), 0))
            .select_from(sub)
        )).one()
        sys_tickers = sorted(t for (t,) in (await db.execute(
            select(WatchedTicker.ticker)
            .where(WatchedTicker.active.is_(True))
            .where(WatchedTicker.user_id == SYSTEM_DEFAULT_USER_ID)
        )).all())
    return {
        "active_system": active_sys, "active_null": active_null,
        "total_rows": total, "dup_groups": int(groups),
        "dup_excess": int(excess), "system_tickers": sys_tickers,
    }


def _run(coro_factory):
    """Run without disturbing the ambient event loop (see Section 0.8)."""
    try:
        prev = asyncio.get_event_loop()
    except RuntimeError:
        prev = None
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        loop.run_until_complete(coro_factory())
    finally:
        loop.close()
        asyncio.set_event_loop(prev)


# ===========================================================================


def test_two_startups_leave_exactly_n_rows(monkeypatch):
    """A — two boots must not double the seeded set."""
    tickers = ["T%02d" % i for i in range(5)]

    async def body():
        engine, maker = await _make_engine()
        try:
            for _ in range(2):
                await _boot(monkeypatch, maker, tickers)
            c = await _counts(maker)
            assert c["active_system"] == len(tickers), (
                "expected %d seeded rows after two boots, got %d"
                % (len(tickers), c["active_system"])
            )
            assert c["dup_groups"] == 0
            assert c["dup_excess"] == 0
        finally:
            await engine.dispose()

    _run(body)


def test_four_startups_still_leave_exactly_n_rows(monkeypatch):
    """B — the property must hold across repeated deploys."""
    tickers = ["T%02d" % i for i in range(5)]

    async def body():
        engine, maker = await _make_engine()
        try:
            for _ in range(4):
                await _boot(monkeypatch, maker, tickers)
            c = await _counts(maker)
            assert c["active_system"] == len(tickers)
            assert c["dup_groups"] == 0
            assert c["dup_excess"] == 0
            assert c["total_rows"] == len(tickers), (
                "no extra rows may accumulate in any state"
            )
        finally:
            await engine.dispose()

    _run(body)


def test_seeded_rows_are_system_owned_with_no_null_residue(monkeypatch):
    """C — ownership namespace and absence of NULL residue after each boot."""
    tickers = ["AAA", "BBB", "CCC"]

    async def body():
        engine, maker = await _make_engine()
        try:
            for boot_no in (1, 2, 3):
                await _boot(monkeypatch, maker, tickers)
                c = await _counts(maker)
                assert c["active_system"] == len(tickers), "boot %d" % boot_no
                assert c["active_null"] == 0, (
                    "boot %d left NULL-owner residue" % boot_no
                )
                assert c["dup_groups"] == 0, "boot %d created duplicates" % boot_no
        finally:
            await engine.dispose()

    _run(body)


def test_preexisting_duplicates_do_not_grow(monkeypatch):
    """D — startup must not widen damage that already exists."""
    import uuid
    from app.db.models import WatchedTicker

    tickers = ["AAA", "BBB"]

    async def body():
        engine, maker = await _make_engine()
        try:
            async with maker() as db:
                for _ in range(3):
                    db.add(WatchedTicker(
                        id=uuid.uuid4().hex, user_id=SYSTEM_DEFAULT_USER_ID,
                        ticker="AAA", company_name="AAA", active=True,
                    ))
                await db.commit()
            before = await _counts(maker)
            assert before["dup_excess"] == 2

            await _boot(monkeypatch, maker, tickers)
            after = await _counts(maker)
            assert after["dup_excess"] == before["dup_excess"], (
                "startup must not add rows to an already-duplicated group"
            )
            assert after["dup_groups"] == 1
        finally:
            await engine.dispose()

    _run(body)


def test_real_user_rows_are_untouched(monkeypatch):
    """E — a real account's membership must survive startup unchanged."""
    import uuid
    from sqlalchemy import select
    from app.db.models import WatchedTicker

    tickers = ["AAA", "BBB"]

    async def body():
        engine, maker = await _make_engine()
        try:
            async with maker() as db:
                db.add(WatchedTicker(
                    id=uuid.uuid4().hex, user_id=REAL_USER, ticker="AAA",
                    company_name="Real user's own", active=True,
                ))
                db.add(WatchedTicker(
                    id=uuid.uuid4().hex, user_id=REAL_USER, ticker="ZZZ",
                    company_name="Only the user has this", active=True,
                ))
                await db.commit()

            for _ in range(3):
                await _boot(monkeypatch, maker, tickers)

            async with maker() as db:
                rows = (await db.execute(
                    select(WatchedTicker)
                    .where(WatchedTicker.user_id == REAL_USER)
                )).scalars().all()
            assert len(rows) == 2, "real-user rows were duplicated or removed"
            assert all(r.active for r in rows), "real-user rows were deactivated"
            assert sorted(r.ticker for r in rows) == ["AAA", "ZZZ"]
            assert all(r.user_id == REAL_USER for r in rows), (
                "real-user rows were claimed into another namespace"
            )
        finally:
            await engine.dispose()

    _run(body)


def test_newly_added_index_ticker_is_seeded_on_next_startup(monkeypatch):
    """F — proves this is not the rejected "skip if any rows exist" shortcut."""
    async def body():
        engine, maker = await _make_engine()
        try:
            await _boot(monkeypatch, maker, ["AAA", "BBB"])
            first = await _counts(maker)
            assert first["system_tickers"] == ["AAA", "BBB"]

            # A new ticker is added to index.json, then the app redeploys.
            await _boot(monkeypatch, maker, ["AAA", "BBB", "CCC"])
            second = await _counts(maker)

            assert second["system_tickers"] == ["AAA", "BBB", "CCC"], (
                "a newly added index ticker must still be seeded"
            )
            assert second["active_system"] == first["active_system"] + 1, (
                "exactly one row should have been added"
            )
            assert second["dup_groups"] == 0
        finally:
            await engine.dispose()

    _run(body)


def test_seed_uses_the_canonical_system_owner_constant():
    """No second constant or literal may be introduced for the owner."""
    from pathlib import Path

    src = Path("app/main.py").read_text()
    assert "SYSTEM_DEFAULT_USER_ID as _SYSTEM_OWNER" in src, (
        "the seed must import the canonical constant"
    )
    assert "user_id=_SYSTEM_OWNER" in src, (
        "the Phase 10B seed must pass the owner explicitly"
    )
    assert '"00000000-0000-0000-0000-000000000001"' not in src, (
        "app/main.py must not hard-code the system owner literal"
    )
