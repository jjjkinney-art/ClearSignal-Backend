"""Section 0.8 — watchlist membership idempotency and loop-selection keys.

Two distinct concerns are covered here, and they must not be conflated:

  1. MEMBERSHIP IDEMPOTENCY — repeated adds, remove/re-add, repeated starter
     import, and normalization must never grow the row count for one owner.

  2. DUPLICATE TOLERANCE — ``watched_tickers`` has no unique constraint (see
     the repository module docstring: NULL != NULL makes a plain unique index
     unreliable for the global watchlist). The check-then-insert in
     ``ticker_add`` is therefore not atomic, and a duplicate pair is
     reachable. These tests assert the repository DEGRADES GRACEFULLY when
     that state exists.

     They deliberately do NOT claim the race is closed. Only a unique index
     can do that, and that needs a migration. What is asserted is that a
     duplicate does not become an unrecoverable ticker for the user.

Also pins the loop-selection keys so a later change cannot silently make
scheduled work per-user (it is per-ticker by design) or defeat the
enqueue-idempotency constraint.

Python 3.9 compatible; does not import the FastAPI app.
"""
from __future__ import annotations

import asyncio
import uuid

import pytest

USER_A = "aaaaaaaa-0000-0000-0000-00000000000a"
USER_B = "bbbbbbbb-0000-0000-0000-00000000000b"
SYSTEM = "00000000-0000-0000-0000-000000000001"


async def _make_session():
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
    from app.db.models import Base

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


async def _active(db, user_id):
    from app.db.repositories.watchlist_repo import ticker_list_active

    return [r.ticker for r in await ticker_list_active(db, user_id=user_id)]


async def _all_rows(db, user_id, ticker):
    from sqlalchemy import select
    from app.db.models import WatchedTicker

    r = await db.execute(
        select(WatchedTicker)
        .where(WatchedTicker.user_id == user_id)
        .where(WatchedTicker.ticker == ticker)
    )
    return list(r.scalars().all())


def _run(body):
    """Run one async body without disturbing the ambient event loop.

    Deliberately NOT asyncio.run(): on Python 3.9 that sets the current event
    loop to None on exit, which breaks sibling modules that legitimately use
    asyncio.get_event_loop().run_until_complete(...). This saves and restores
    whatever loop policy state was in place.
    """
    async def _outer():
        engine, maker = await _make_session()
        try:
            async with maker() as db:
                await body(db)
        finally:
            await engine.dispose()

    try:
        prev = asyncio.get_event_loop()
    except RuntimeError:
        prev = None
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        loop.run_until_complete(_outer())
    finally:
        loop.close()
        asyncio.set_event_loop(prev)


# ===========================================================================
# § MEMBERSHIP IDEMPOTENCY
# ===========================================================================

def test_repeated_add_by_same_user_creates_one_row():
    async def body(db):
        from app.db.repositories.watchlist_repo import ticker_add

        for _ in range(5):
            await ticker_add(db, "NVDA", "NVIDIA", user_id=USER_A)
        await db.flush()
        assert len(await _all_rows(db, USER_A, "NVDA")) == 1
        assert await _active(db, USER_A) == ["NVDA"]

    _run(body)


def test_remove_then_readd_reactivates_in_place():
    async def body(db):
        from app.db.repositories.watchlist_repo import (
            ticker_add, ticker_deactivate,
        )

        row = await ticker_add(db, "NVDA", "NVIDIA", user_id=USER_A)
        await db.flush()
        original_id, original_added = row.id, row.added_at

        assert await ticker_deactivate(db, "NVDA", user_id=USER_A) is True
        await db.flush()
        assert await _active(db, USER_A) == []

        again = await ticker_add(db, "NVDA", "NVIDIA", user_id=USER_A)
        await db.flush()
        assert again.id == original_id, "must reactivate, not insert a new row"
        # Compare tz-naive: SQLite drops tzinfo on round-trip, so an aware
        # value written in this process reads back naive. The instant is what
        # matters here, not the tzinfo carried by the in-memory object.
        assert (again.added_at.replace(tzinfo=None)
                == original_added.replace(tzinfo=None)), "added_at preserved"
        assert again.active is True
        assert len(await _all_rows(db, USER_A, "NVDA")) == 1

    _run(body)


def test_case_and_whitespace_normalize_to_one_row():
    async def body(db):
        from app.db.repositories.watchlist_repo import ticker_add

        for raw in ("nvda", "  NVDA  ", "Nvda", "nVdA\t", " nvda"):
            await ticker_add(db, raw, "NVIDIA", user_id=USER_A)
        await db.flush()
        rows = await _all_rows(db, USER_A, "NVDA")
        assert len(rows) == 1, "normalization must collapse to one row"
        assert await _active(db, USER_A) == ["NVDA"]

    _run(body)


def test_same_ticker_across_two_users_is_two_independent_rows():
    """Not a duplicate: per-account ownership is the validated model."""
    async def body(db):
        from app.db.repositories.watchlist_repo import (
            ticker_add, ticker_deactivate,
        )

        await ticker_add(db, "AAPL", "Apple", user_id=USER_A)
        await ticker_add(db, "AAPL", "Apple", user_id=USER_B)
        await db.flush()
        assert len(await _all_rows(db, USER_A, "AAPL")) == 1
        assert len(await _all_rows(db, USER_B, "AAPL")) == 1

        # Removing A's must not touch B's.
        await ticker_deactivate(db, "AAPL", user_id=USER_A)
        await db.flush()
        assert await _active(db, USER_A) == []
        assert await _active(db, USER_B) == ["AAPL"], "cross-account mutation"

    _run(body)


def test_starter_import_run_twice_does_not_duplicate():
    async def body(db):
        from app.db.repositories.watchlist_repo import ticker_add
        from app.services.account_import_service import execute_import

        for t in ("AAPL", "MSFT", "NVDA"):
            await ticker_add(db, t, t, user_id=SYSTEM)
        await db.flush()

        first = await execute_import(db, USER_A)
        await db.flush()
        second = await execute_import(db, USER_A)
        await db.flush()

        assert sorted(await _active(db, USER_A)) == ["AAPL", "MSFT", "NVDA"]
        for t in ("AAPL", "MSFT", "NVDA"):
            assert len(await _all_rows(db, USER_A, t)) == 1
        assert second.already_imported or second.watchlist_copied == 0, (
            "second import must be a no-op, not a second copy"
        )
        assert first is not None

    _run(body)


def test_import_after_manual_add_does_not_duplicate():
    async def body(db):
        from app.db.repositories.watchlist_repo import ticker_add
        from app.services.account_import_service import execute_import

        await ticker_add(db, "AAPL", "Apple", user_id=SYSTEM)
        await ticker_add(db, "AAPL", "Apple", user_id=USER_A)  # user already has it
        await db.flush()

        await execute_import(db, USER_A)
        await db.flush()
        assert len(await _all_rows(db, USER_A, "AAPL")) == 1

    _run(body)


# ===========================================================================
# § DUPLICATE TOLERANCE (the race OUTCOME, not the race itself)
# ===========================================================================

async def _force_duplicate(db, user_id, ticker):
    """Create the state a lost race would leave behind.

    Inserts directly, bypassing ticker_add, because ticker_add is exactly the
    guard being bypassed. The DB accepts this — there is no unique constraint.
    """
    from app.db.models import WatchedTicker

    for _ in range(2):
        db.add(WatchedTicker(
            id=uuid.uuid4().hex, user_id=user_id, ticker=ticker,
            company_name=ticker, active=True,
        ))
    await db.flush()


def test_schema_still_permits_duplicates_so_tolerance_is_required():
    """Guard the premise. If this ever fails, a constraint was added and the
    tolerance below can be revisited."""
    async def body(db):
        await _force_duplicate(db, USER_A, "AAPL")
        assert len(await _all_rows(db, USER_A, "AAPL")) == 2

    _run(body)


def test_duplicate_does_not_break_add():
    async def body(db):
        from app.db.repositories.watchlist_repo import ticker_add

        await _force_duplicate(db, USER_A, "AAPL")
        row = await ticker_add(db, "AAPL", "Apple", user_id=USER_A)
        assert row is not None, "add must not raise on a duplicate pair"
        assert len(await _all_rows(db, USER_A, "AAPL")) == 2, (
            "add must not make the problem worse"
        )

    _run(body)


def test_duplicate_does_not_break_remove_and_removes_every_row():
    async def body(db):
        from app.db.repositories.watchlist_repo import ticker_deactivate

        await _force_duplicate(db, USER_A, "AAPL")
        assert await ticker_deactivate(db, "AAPL", user_id=USER_A) is True
        await db.flush()
        assert await _active(db, USER_A) == [], (
            "removing must clear the ticker even when duplicated; leaving one "
            "active row would show a ticker the user just deleted"
        )

    _run(body)


def test_duplicate_does_not_break_get_and_resolves_deterministically():
    async def body(db):
        from app.db.repositories.watchlist_repo import ticker_get

        await _force_duplicate(db, USER_A, "AAPL")
        first = await ticker_get(db, "AAPL", user_id=USER_A)
        second = await ticker_get(db, "AAPL", user_id=USER_A)
        assert first is not None
        assert first.id == second.id, "resolution must be stable across calls"

    _run(body)


def test_duplicate_warning_carries_no_identifying_data(caplog):
    """Containment must stay observable without leaking identity."""
    import logging

    records = []

    async def body(db):
        from app.db.repositories.watchlist_repo import ticker_add, ticker_deactivate

        await _force_duplicate(db, USER_A, "AAPL")
        with caplog.at_level(logging.WARNING,
                             logger="app.db.repositories.watchlist_repo"):
            await ticker_add(db, "AAPL", "Apple", user_id=USER_A)
            await ticker_deactivate(db, "AAPL", user_id=USER_A)
        records.extend(r.getMessage() for r in caplog.records)

    _run(body)

    assert records, "duplicates must emit a warning, not pass silently"
    joined = " ".join(records)
    assert "AAPL" in joined, "public ticker is expected"
    assert "2" in joined, "the duplicate count is expected"
    # Nothing identifying.
    assert USER_A not in joined
    assert USER_B not in joined
    assert "@" not in joined
    for r in records:
        assert "scoped=True" in r or "scoped=" in r, (
            "ownership must be reported as a boolean, never as an id"
        )


def test_duplicate_containment_does_not_silently_absorb(caplog):
    """A duplicate must remain visible to operators via the aggregates."""
    import logging

    async def body(db):
        from app.db.repositories.watchlist_repo import ticker_get
        from app.services.loop_observability import _watchlist_section

        await _force_duplicate(db, USER_A, "AAPL")
        with caplog.at_level(logging.WARNING,
                             logger="app.db.repositories.watchlist_repo"):
            await ticker_get(db, "AAPL", user_id=USER_A)

        section = await _watchlist_section(db)
        assert section["duplicate_membership_groups"] == 1, (
            "containment must not hide the corruption it absorbs"
        )
        assert section["duplicate_membership_excess_rows"] == 1

    _run(body)


def test_duplicate_in_one_account_does_not_affect_another():
    async def body(db):
        from app.db.repositories.watchlist_repo import ticker_add, ticker_deactivate

        await _force_duplicate(db, USER_A, "AAPL")
        await ticker_add(db, "AAPL", "Apple", user_id=USER_B)
        await db.flush()

        await ticker_deactivate(db, "AAPL", user_id=USER_A)
        await db.flush()
        assert await _active(db, USER_B) == ["AAPL"]
        assert len(await _all_rows(db, USER_B, "AAPL")) == 1

    _run(body)


# ===========================================================================
# § LOOP / SCHEDULED-WORK SELECTION KEYS
# ===========================================================================

def test_scheduled_jobs_have_a_unique_enqueue_key():
    """Enqueue idempotency is DB-enforced; watchlist membership is not."""
    from app.db.models import Base

    jobs = Base.metadata.tables["scheduled_jobs"]
    uniques = {
        tuple(c.name for c in con.columns)
        for con in jobs.constraints
        if con.__class__.__name__ == "UniqueConstraint"
    }
    assert ("job_type", "target_key", "period_bucket") in uniques


def test_watchlist_scan_target_key_is_ticker_not_user():
    """Scheduled scan work is shared per ticker, never multiplied per user."""
    async def body(db):
        from app.db.repositories.watchlist_repo import ticker_add
        from app.services.watchlist_job_seeder import seed_watchlist_jobs
        from sqlalchemy import select
        from app.db.models import ScheduledJob

        # Global (user_id IS NULL) rows are what the seeder reads.
        await ticker_add(db, "NVDA", "NVIDIA", user_id=None)
        await ticker_add(db, "AAPL", "Apple", user_id=None)
        # Per-user rows for the same tickers must NOT add scheduled work.
        await ticker_add(db, "NVDA", "NVIDIA", user_id=USER_A)
        await ticker_add(db, "NVDA", "NVIDIA", user_id=USER_B)
        await ticker_add(db, "AAPL", "Apple", user_id=USER_A)
        await db.flush()

        result = await seed_watchlist_jobs(db, file_fallback=False)
        await db.flush()

        rows = (await db.execute(select(ScheduledJob))).scalars().all()
        assert {r.target_key for r in rows} == {"NVDA", "AAPL"}
        assert len(rows) == 2, (
            "one job per (ticker, bucket) regardless of how many accounts "
            "watch it; got %d" % len(rows)
        )
        assert result.jobs_created == 2

    _run(body)


def test_reseeding_is_idempotent_for_the_same_bucket():
    async def body(db):
        from app.db.repositories.watchlist_repo import ticker_add
        from app.services.watchlist_job_seeder import seed_watchlist_jobs
        from sqlalchemy import select
        from app.db.models import ScheduledJob

        await ticker_add(db, "NVDA", "NVIDIA", user_id=None)
        await db.flush()

        first = await seed_watchlist_jobs(db, file_fallback=False)
        second = await seed_watchlist_jobs(db, file_fallback=False)
        await db.flush()

        rows = (await db.execute(select(ScheduledJob))).scalars().all()
        assert len(rows) == 1, "re-seeding must not duplicate jobs"
        assert first.jobs_created == 1
        assert second.jobs_created == 0
        assert second.jobs_existing == 1

    _run(body)


def test_duplicate_membership_rows_do_not_amplify_scheduled_jobs():
    async def body(db):
        from app.services.watchlist_job_seeder import seed_watchlist_jobs
        from sqlalchemy import select
        from app.db.models import ScheduledJob

        await _force_duplicate(db, None, "NVDA")   # duplicated global rows
        result = await seed_watchlist_jobs(db, file_fallback=False)
        await db.flush()

        rows = (await db.execute(select(ScheduledJob))).scalars().all()
        assert len(rows) == 1, (
            "even duplicated membership rows must collapse to one job via the "
            "unique enqueue key"
        )
        assert result.tickers_seen == 2   # the seeder saw both rows
        assert result.jobs_created == 1   # the DB constraint deduplicated

    _run(body)


# ===========================================================================
# § DELIVERY
# ===========================================================================

def test_delivery_ledger_content_key_is_unique():
    """Duplicate delivery is prevented by a DB constraint, per user."""
    from app.db.models import Base

    dl = Base.metadata.tables["delivery_ledger"]
    unique_cols = {
        tuple(c.name for c in con.columns)
        for con in dl.constraints
        if con.__class__.__name__ == "UniqueConstraint"
    }
    unique_cols |= {
        tuple(c.name for c in idx.columns) for idx in dl.indexes if idx.unique
    }
    assert ("content_key",) in unique_cols


def test_delivery_content_key_is_scoped_per_user():
    """Two users receiving the same content must NOT be deduplicated."""
    from app.services.loop_idempotency_service import build_content_key

    a = build_content_key(USER_A, "in_app", "NVDA", "hash123")
    b = build_content_key(USER_B, "in_app", "NVDA", "hash123")
    assert a != b, "per-user delivery must remain per-user"
    assert a == build_content_key(USER_A, "in_app", "NVDA", "hash123")
