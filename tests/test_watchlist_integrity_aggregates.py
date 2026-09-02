"""Section 0.8 — watchlist integrity aggregates and import-preview counting.

Two things are pinned here:

  1. The aggregate-only integrity fields on the loop/watchlist observability
     snapshot. These exist so duplicate CONTAINMENT (see
     tests/test_watchlist_idempotency.py) cannot silently absorb corruption:
     the numbers stay visible without exposing any identity.

  2. ``_count_system_tickers``, which drives ``GET /auth/import/preview``.
     It must report the DISTINCT starter tickers an import can create, not
     the number of duplicated system rows.

Every assertion below is on counts only. No test asserts on a user id, row
id or email, and the aggregates themselves must not carry any.

Terminology: a "membership group" is (user_id, ticker) over ACTIVE rows with
a non-null owner; a "legacy group" is ticker alone over ACTIVE rows whose
owner is NULL. Excess is COUNT(*) - 1 per duplicated group.

Python 3.9 compatible; does not import the FastAPI app.
"""
from __future__ import annotations

import asyncio
import uuid

import pytest

OWNER_1 = "11111111-1111-1111-1111-111111111111"
OWNER_2 = "22222222-2222-2222-2222-222222222222"
SYSTEM = "00000000-0000-0000-0000-000000000001"

AGG_KEYS = (
    "active_row_count",
    "distinct_ticker_count",
    "active_owner_count",
    "duplicate_membership_groups",
    "duplicate_membership_excess_rows",
    "duplicate_legacy_groups",
    "duplicate_legacy_excess_rows",
    "orphan_owner_count",
    "orphan_active_row_count",
)

LEGACY_KEYS = (
    "active_ticker_count",
    "active_tickers",
    "scan_jobs_total",
    "duplicate_job_combos",
    "drift_skip_count",
)


async def _make_session():
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
    from app.db.models import Base

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


def _run(body):
    async def _outer():
        engine, maker = await _make_session()
        try:
            async with maker() as db:
                await body(db)
        finally:
            await engine.dispose()

    asyncio.run(_outer())


async def _add_row(db, user_id, ticker, active=True):
    from app.db.models import WatchedTicker

    db.add(WatchedTicker(
        id=uuid.uuid4().hex, user_id=user_id, ticker=ticker,
        company_name=ticker, active=active,
    ))
    await db.flush()


async def _add_user(db, user_id, email):
    from app.db.models import User

    db.add(User(id=user_id, email=email))
    await db.flush()


async def _section(db):
    from app.services.loop_observability import _watchlist_section

    out = await _watchlist_section(db)
    assert "db_error" not in out, "aggregate query failed: %s" % out.get("db_error")
    return out


# ===========================================================================
# § SHAPE AND COMPATIBILITY
# ===========================================================================

def test_all_aggregate_keys_present_on_empty_table():
    async def body(db):
        s = await _section(db)
        for k in AGG_KEYS:
            assert k in s, "missing aggregate key %s" % k
            assert s[k] == 0, "%s should be 0 on an empty table, got %r" % (k, s[k])

    _run(body)


def test_legacy_fields_preserved_and_unchanged():
    async def body(db):
        await _add_row(db, OWNER_1, "AAPL")
        await _add_row(db, OWNER_2, "AAPL")
        s = await _section(db)
        for k in LEGACY_KEYS:
            assert k in s, "legacy field %s was dropped" % k
        # active_ticker_count is HISTORICAL: it counts rows, not securities.
        assert s["active_ticker_count"] == 2
        assert s["active_row_count"] == 2
        assert s["distinct_ticker_count"] == 1
        assert s["active_tickers"] == ["AAPL", "AAPL"]

    _run(body)


def test_aggregates_contain_no_identifying_values():
    async def body(db):
        await _add_user(db, OWNER_1, "a@example.test")
        await _add_row(db, OWNER_1, "AAPL")
        await _add_row(db, OWNER_1, "AAPL")
        s = await _section(db)
        for k in AGG_KEYS:
            assert isinstance(s[k], int), "%s must be a plain count" % k
        blob = repr(s)
        assert OWNER_1 not in blob
        assert OWNER_2 not in blob
        assert "example.test" not in blob

    _run(body)


# ===========================================================================
# § MEMBERSHIP GROUPS
# ===========================================================================

def test_clean_rows_across_multiple_owners_are_not_duplicates():
    async def body(db):
        for owner in (OWNER_1, OWNER_2):
            for t in ("AAPL", "MSFT"):
                await _add_row(db, owner, t)
        s = await _section(db)
        assert s["active_row_count"] == 4
        assert s["distinct_ticker_count"] == 2
        assert s["active_owner_count"] == 2
        assert s["duplicate_membership_groups"] == 0
        assert s["duplicate_membership_excess_rows"] == 0

    _run(body)


def test_same_ticker_across_different_owners_is_not_a_duplicate_group():
    """The central false-positive guard."""
    async def body(db):
        for owner in (OWNER_1, OWNER_2, SYSTEM):
            await _add_row(db, owner, "AAPL")
        s = await _section(db)
        assert s["duplicate_membership_groups"] == 0
        assert s["duplicate_membership_excess_rows"] == 0
        assert s["active_owner_count"] == 3

    _run(body)


def test_duplicate_rows_for_one_owner_are_one_group():
    async def body(db):
        for _ in range(3):
            await _add_row(db, OWNER_1, "AAPL")
        s = await _section(db)
        assert s["duplicate_membership_groups"] == 1
        assert s["duplicate_membership_excess_rows"] == 2, "excess is count - 1"
        assert s["active_owner_count"] == 1

    _run(body)


def test_duplicates_across_multiple_owners_count_as_separate_groups():
    async def body(db):
        for _ in range(2):
            await _add_row(db, OWNER_1, "AAPL")
        for _ in range(4):
            await _add_row(db, OWNER_2, "MSFT")
        await _add_row(db, OWNER_2, "AAPL")   # clean, not a group
        s = await _section(db)
        assert s["duplicate_membership_groups"] == 2
        assert s["duplicate_membership_excess_rows"] == 1 + 3

    _run(body)


def test_inactive_rows_are_excluded_from_membership_groups():
    async def body(db):
        await _add_row(db, OWNER_1, "AAPL", active=True)
        await _add_row(db, OWNER_1, "AAPL", active=False)
        await _add_row(db, OWNER_1, "AAPL", active=False)
        s = await _section(db)
        assert s["duplicate_membership_groups"] == 0, (
            "soft-deleted history must not count as duplication"
        )
        assert s["duplicate_membership_excess_rows"] == 0
        assert s["active_row_count"] == 1

    _run(body)


# ===========================================================================
# § LEGACY (NULL-OWNER) GROUPS
# ===========================================================================

def test_null_owner_duplicates_form_a_legacy_group():
    async def body(db):
        await _add_row(db, None, "AAPL")
        await _add_row(db, None, "AAPL")
        await _add_row(db, None, "MSFT")
        s = await _section(db)
        assert s["duplicate_legacy_groups"] == 1
        assert s["duplicate_legacy_excess_rows"] == 1
        # Null owners are not counted as owners.
        assert s["active_owner_count"] == 0
        # And they are not membership duplicates.
        assert s["duplicate_membership_groups"] == 0

    _run(body)


def test_legacy_and_membership_namespaces_are_independent():
    async def body(db):
        await _add_row(db, None, "AAPL")
        await _add_row(db, None, "AAPL")
        await _add_row(db, OWNER_1, "AAPL")
        await _add_row(db, OWNER_1, "AAPL")
        s = await _section(db)
        assert s["duplicate_legacy_groups"] == 1
        assert s["duplicate_legacy_excess_rows"] == 1
        assert s["duplicate_membership_groups"] == 1
        assert s["duplicate_membership_excess_rows"] == 1

    _run(body)


def test_inactive_null_owner_rows_excluded():
    async def body(db):
        await _add_row(db, None, "AAPL", active=True)
        await _add_row(db, None, "AAPL", active=False)
        s = await _section(db)
        assert s["duplicate_legacy_groups"] == 0
        assert s["duplicate_legacy_excess_rows"] == 0

    _run(body)


# ===========================================================================
# § ORPHAN OWNERS (unenforced — there is no FK on this column)
# ===========================================================================

def test_orphan_owner_counted_when_no_users_row_exists():
    async def body(db):
        await _add_row(db, OWNER_1, "AAPL")
        await _add_row(db, OWNER_1, "MSFT")
        s = await _section(db)
        assert s["orphan_owner_count"] == 1
        assert s["orphan_active_row_count"] == 2

    _run(body)


def test_owner_present_in_users_is_not_orphaned():
    async def body(db):
        await _add_user(db, OWNER_1, "a@example.test")
        await _add_row(db, OWNER_1, "AAPL")
        s = await _section(db)
        assert s["orphan_owner_count"] == 0
        assert s["orphan_active_row_count"] == 0

    _run(body)


def test_system_owner_is_not_orphaned_when_present_in_users():
    async def body(db):
        await _add_user(db, SYSTEM, "system@example.test")
        for _ in range(3):
            await _add_row(db, SYSTEM, "AAPL")
        s = await _section(db)
        assert s["orphan_owner_count"] == 0
        assert s["orphan_active_row_count"] == 0
        # ... and it is an ordinary owner for duplication purposes.
        assert s["duplicate_membership_groups"] == 1
        assert s["duplicate_membership_excess_rows"] == 2

    _run(body)


def test_null_owner_rows_are_never_orphans():
    async def body(db):
        await _add_row(db, None, "AAPL")
        s = await _section(db)
        assert s["orphan_owner_count"] == 0
        assert s["orphan_active_row_count"] == 0

    _run(body)


def test_inactive_orphan_rows_excluded():
    async def body(db):
        await _add_row(db, OWNER_1, "AAPL", active=False)
        s = await _section(db)
        assert s["orphan_owner_count"] == 0
        assert s["orphan_active_row_count"] == 0

    _run(body)


# ===========================================================================
# § IMPORT PREVIEW COUNT
# ===========================================================================

def test_forty_duplicate_system_rows_contribute_one_to_preview():
    async def body(db):
        from app.services.account_import_service import _count_system_tickers

        for _ in range(40):
            await _add_row(db, SYSTEM, "AAPL")
        assert await _count_system_tickers(db) == 1

    _run(body)


def test_preview_counts_each_distinct_starter_ticker_once():
    async def body(db):
        from app.services.account_import_service import _count_system_tickers

        for t in ("AAPL", "MSFT", "NVDA"):
            for _ in range(5):
                await _add_row(db, SYSTEM, t)
        assert await _count_system_tickers(db) == 3

    _run(body)


def test_preview_excludes_inactive_duplicates():
    async def body(db):
        from app.services.account_import_service import _count_system_tickers

        await _add_row(db, SYSTEM, "AAPL", active=True)
        for _ in range(4):
            await _add_row(db, SYSTEM, "AAPL", active=False)
        await _add_row(db, SYSTEM, "MSFT", active=False)
        assert await _count_system_tickers(db) == 1

    _run(body)


def test_preview_excludes_other_owners_rows():
    async def body(db):
        from app.services.account_import_service import _count_system_tickers

        await _add_row(db, SYSTEM, "AAPL")
        await _add_row(db, OWNER_1, "MSFT")
        assert await _count_system_tickers(db) == 1

    _run(body)


def test_preview_estimate_matches_rows_import_actually_creates():
    """The contract: preview must equal the maximum distinct actions."""
    async def body(db):
        from sqlalchemy import select
        from app.db.models import WatchedTicker
        from app.services.account_import_service import (
            _count_system_tickers, execute_import,
        )

        for t in ("AAPL", "MSFT", "NVDA"):
            for _ in range(7):
                await _add_row(db, SYSTEM, t)

        predicted = await _count_system_tickers(db)
        result = await execute_import(db, OWNER_1)
        await db.flush()

        created = len((await db.execute(
            select(WatchedTicker)
            .where(WatchedTicker.user_id == OWNER_1)
        )).scalars().all())

        assert predicted == 3
        assert created == 3, "import creates one row per distinct ticker"
        assert result.watchlist_copied == created
        assert predicted == created, "preview must match reality"

    _run(body)
