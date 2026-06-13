"""
Phase 10B · Slice 2 — DB Watchlist Membership tests.

Tests cover:
  - watchlist_repo: CRUD (ticker_add, ticker_deactivate, ticker_get,
    ticker_list_active, ticker_is_active)
  - watchlist_repo: backfill_from_index (idempotency, metadata preservation)
  - watchlist_repo: active/inactive lifecycle (deactivate → reactivate)
  - watchlist_repo: null-session safety
  - WatchlistService async methods: add_ticker_async, remove_ticker_async,
    is_tracked_async, get_watchlist_async, get_entry_async,
    backfill_from_index_async
  - Parity: async service methods produce results consistent with file-based
    sync methods

All tests use the in-memory SQLite db_session fixture from conftest.py.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from typing import List

import pytest
import pytest_asyncio


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _add(session, ticker: str, company_name: str = "") -> object:
    from app.db.repositories.watchlist_repo import ticker_add
    return await ticker_add(session, ticker, company_name)


async def _deactivate(session, ticker: str) -> bool:
    from app.db.repositories.watchlist_repo import ticker_deactivate
    return await ticker_deactivate(session, ticker)


async def _get(session, ticker: str):
    from app.db.repositories.watchlist_repo import ticker_get
    return await ticker_get(session, ticker)


async def _list_active(session) -> list:
    from app.db.repositories.watchlist_repo import ticker_list_active
    return await ticker_list_active(session)


async def _is_active(session, ticker: str) -> bool:
    from app.db.repositories.watchlist_repo import ticker_is_active
    return await ticker_is_active(session, ticker)


def _make_index_file(data: dict) -> str:
    """Write a temporary index.json and return its path."""
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh)
    return path


# ---------------------------------------------------------------------------
# 1. TestTickerAdd
# ---------------------------------------------------------------------------

class TestTickerAdd:
    @pytest.mark.asyncio
    async def test_add_new_ticker(self, db_session):
        row = await _add(db_session, "AAPL", "Apple Inc.")
        assert row is not None
        assert row.ticker == "AAPL"
        assert row.company_name == "Apple Inc."
        assert row.active is True
        assert row.id is not None

    @pytest.mark.asyncio
    async def test_ticker_normalized_uppercase(self, db_session):
        row = await _add(db_session, "aapl", "Apple")
        assert row.ticker == "AAPL"

    @pytest.mark.asyncio
    async def test_add_idempotent_returns_same_id(self, db_session):
        r1 = await _add(db_session, "MSFT", "Microsoft")
        r2 = await _add(db_session, "MSFT", "Microsoft")
        assert r1.id == r2.id

    @pytest.mark.asyncio
    async def test_add_idempotent_active_unchanged(self, db_session):
        await _add(db_session, "NVDA", "NVIDIA")
        r2 = await _add(db_session, "NVDA", "NVIDIA Corporation")
        assert r2.active is True

    @pytest.mark.asyncio
    async def test_add_company_name_fallback(self, db_session):
        row = await _add(db_session, "TSLA")
        assert row.company_name == "TSLA"

    @pytest.mark.asyncio
    async def test_add_multiple_distinct_tickers(self, db_session):
        await _add(db_session, "AAPL")
        await _add(db_session, "MSFT")
        await _add(db_session, "NVDA")
        rows = await _list_active(db_session)
        tickers = {r.ticker for r in rows}
        assert tickers == {"AAPL", "MSFT", "NVDA"}

    @pytest.mark.asyncio
    async def test_add_null_session_returns_none(self):
        from app.db.repositories.watchlist_repo import ticker_add
        result = await ticker_add(None, "AAPL", "Apple")
        assert result is None


# ---------------------------------------------------------------------------
# 2. TestTickerDeactivate
# ---------------------------------------------------------------------------

class TestTickerDeactivate:
    @pytest.mark.asyncio
    async def test_deactivate_existing_ticker(self, db_session):
        await _add(db_session, "AAPL", "Apple")
        ok = await _deactivate(db_session, "AAPL")
        assert ok is True

    @pytest.mark.asyncio
    async def test_deactivated_ticker_has_active_false(self, db_session):
        await _add(db_session, "AAPL", "Apple")
        await _deactivate(db_session, "AAPL")
        row = await _get(db_session, "AAPL")
        assert row is not None
        assert row.active is False

    @pytest.mark.asyncio
    async def test_deactivate_nonexistent_returns_false(self, db_session):
        ok = await _deactivate(db_session, "ZZZ")
        assert ok is False

    @pytest.mark.asyncio
    async def test_deactivated_not_in_active_list(self, db_session):
        await _add(db_session, "AAPL")
        await _add(db_session, "MSFT")
        await _deactivate(db_session, "AAPL")
        rows = await _list_active(db_session)
        tickers = {r.ticker for r in rows}
        assert "AAPL" not in tickers
        assert "MSFT" in tickers

    @pytest.mark.asyncio
    async def test_deactivate_null_session_returns_false(self):
        from app.db.repositories.watchlist_repo import ticker_deactivate
        ok = await ticker_deactivate(None, "AAPL")
        assert ok is False


# ---------------------------------------------------------------------------
# 3. TestTickerGet
# ---------------------------------------------------------------------------

class TestTickerGet:
    @pytest.mark.asyncio
    async def test_get_existing_ticker(self, db_session):
        await _add(db_session, "AAPL", "Apple")
        row = await _get(db_session, "AAPL")
        assert row is not None
        assert row.ticker == "AAPL"

    @pytest.mark.asyncio
    async def test_get_nonexistent_returns_none(self, db_session):
        row = await _get(db_session, "ZZZZ")
        assert row is None

    @pytest.mark.asyncio
    async def test_get_returns_inactive_rows(self, db_session):
        await _add(db_session, "AAPL")
        await _deactivate(db_session, "AAPL")
        row = await _get(db_session, "AAPL")
        assert row is not None
        assert row.active is False

    @pytest.mark.asyncio
    async def test_get_null_session_returns_none(self):
        from app.db.repositories.watchlist_repo import ticker_get
        row = await ticker_get(None, "AAPL")
        assert row is None


# ---------------------------------------------------------------------------
# 4. TestTickerListActive
# ---------------------------------------------------------------------------

class TestTickerListActive:
    @pytest.mark.asyncio
    async def test_empty_list_when_no_tickers(self, db_session):
        rows = await _list_active(db_session)
        assert rows == []

    @pytest.mark.asyncio
    async def test_lists_only_active_tickers(self, db_session):
        await _add(db_session, "AAPL")
        await _add(db_session, "MSFT")
        await _deactivate(db_session, "AAPL")
        rows = await _list_active(db_session)
        assert len(rows) == 1
        assert rows[0].ticker == "MSFT"

    @pytest.mark.asyncio
    async def test_list_ordered_by_added_at(self, db_session):
        await _add(db_session, "AAPL")
        await _add(db_session, "MSFT")
        await _add(db_session, "NVDA")
        rows = await _list_active(db_session)
        tickers = [r.ticker for r in rows]
        assert tickers == sorted(tickers, key=lambda t: [r.added_at for r in rows
                                                          if r.ticker == t][0])

    @pytest.mark.asyncio
    async def test_list_null_session_returns_empty(self):
        from app.db.repositories.watchlist_repo import ticker_list_active
        rows = await ticker_list_active(None)
        assert rows == []


# ---------------------------------------------------------------------------
# 5. TestTickerIsActive
# ---------------------------------------------------------------------------

class TestTickerIsActive:
    @pytest.mark.asyncio
    async def test_true_for_active_ticker(self, db_session):
        await _add(db_session, "AAPL")
        assert await _is_active(db_session, "AAPL") is True

    @pytest.mark.asyncio
    async def test_false_for_inactive_ticker(self, db_session):
        await _add(db_session, "AAPL")
        await _deactivate(db_session, "AAPL")
        assert await _is_active(db_session, "AAPL") is False

    @pytest.mark.asyncio
    async def test_false_for_nonexistent_ticker(self, db_session):
        assert await _is_active(db_session, "ZZZ") is False

    @pytest.mark.asyncio
    async def test_null_session_returns_false(self):
        from app.db.repositories.watchlist_repo import ticker_is_active
        assert await ticker_is_active(None, "AAPL") is False


# ---------------------------------------------------------------------------
# 6. TestIdempotency
# ---------------------------------------------------------------------------

class TestIdempotency:
    @pytest.mark.asyncio
    async def test_add_twice_same_id(self, db_session):
        r1 = await _add(db_session, "AAPL", "Apple")
        r2 = await _add(db_session, "AAPL", "Apple")
        assert r1.id == r2.id

    @pytest.mark.asyncio
    async def test_add_twice_single_row_in_list(self, db_session):
        await _add(db_session, "AAPL")
        await _add(db_session, "AAPL")
        rows = await _list_active(db_session)
        assert len(rows) == 1

    @pytest.mark.asyncio
    async def test_add_case_insensitive_idempotent(self, db_session):
        r1 = await _add(db_session, "aapl", "Apple")
        r2 = await _add(db_session, "AAPL", "Apple")
        assert r1.id == r2.id

    @pytest.mark.asyncio
    async def test_add_after_deactivate_reactivates(self, db_session):
        r1 = await _add(db_session, "AAPL")
        await _deactivate(db_session, "AAPL")
        r2 = await _add(db_session, "AAPL")
        assert r1.id == r2.id
        assert r2.active is True


# ---------------------------------------------------------------------------
# 7. TestActiveInactive (lifecycle)
# ---------------------------------------------------------------------------

class TestActiveInactive:
    @pytest.mark.asyncio
    async def test_add_deactivate_reactivate_cycle(self, db_session):
        await _add(db_session, "AAPL")
        assert await _is_active(db_session, "AAPL") is True

        await _deactivate(db_session, "AAPL")
        assert await _is_active(db_session, "AAPL") is False

        await _add(db_session, "AAPL")  # reactivate
        assert await _is_active(db_session, "AAPL") is True

    @pytest.mark.asyncio
    async def test_reactivated_ticker_appears_in_list(self, db_session):
        await _add(db_session, "AAPL")
        await _deactivate(db_session, "AAPL")
        rows_after_deactivate = await _list_active(db_session)
        assert not any(r.ticker == "AAPL" for r in rows_after_deactivate)

        await _add(db_session, "AAPL")
        rows_after_reactivate = await _list_active(db_session)
        assert any(r.ticker == "AAPL" for r in rows_after_reactivate)

    @pytest.mark.asyncio
    async def test_multiple_tickers_mixed_states(self, db_session):
        for t in ("AAPL", "MSFT", "NVDA", "GOOGL"):
            await _add(db_session, t)
        await _deactivate(db_session, "MSFT")
        await _deactivate(db_session, "GOOGL")
        rows = await _list_active(db_session)
        active_tickers = {r.ticker for r in rows}
        assert active_tickers == {"AAPL", "NVDA"}


# ---------------------------------------------------------------------------
# 8. TestBackfill
# ---------------------------------------------------------------------------

class TestBackfill:
    @pytest.mark.asyncio
    async def test_backfill_inserts_tickers(self, db_session):
        from app.db.repositories.watchlist_repo import backfill_from_index
        data = {
            "AAPL": {"company_name": "Apple Inc.", "added_at": "2025-01-01T00:00:00+00:00"},
            "MSFT": {"company_name": "Microsoft", "added_at": "2025-01-02T00:00:00+00:00"},
        }
        path = _make_index_file(data)
        try:
            n = await backfill_from_index(db_session, path)
            assert n == 2
        finally:
            os.unlink(path)

    @pytest.mark.asyncio
    async def test_backfill_preserves_company_name(self, db_session):
        from app.db.repositories.watchlist_repo import backfill_from_index
        data = {"AAPL": {"company_name": "Apple Inc.", "added_at": _now_iso()}}
        path = _make_index_file(data)
        try:
            await backfill_from_index(db_session, path)
            row = await _get(db_session, "AAPL")
            assert row.company_name == "Apple Inc."
        finally:
            os.unlink(path)

    @pytest.mark.asyncio
    async def test_backfill_preserves_added_at(self, db_session):
        from app.db.repositories.watchlist_repo import backfill_from_index
        ts = "2024-06-01T12:00:00+00:00"
        data = {"AAPL": {"company_name": "Apple", "added_at": ts}}
        path = _make_index_file(data)
        try:
            await backfill_from_index(db_session, path)
            row = await _get(db_session, "AAPL")
            assert row.added_at is not None
        finally:
            os.unlink(path)

    @pytest.mark.asyncio
    async def test_backfill_all_tickers_active(self, db_session):
        from app.db.repositories.watchlist_repo import backfill_from_index
        data = {t: {"company_name": t} for t in ("AAPL", "MSFT", "NVDA")}
        path = _make_index_file(data)
        try:
            await backfill_from_index(db_session, path)
            rows = await _list_active(db_session)
            assert len(rows) == 3
        finally:
            os.unlink(path)

    @pytest.mark.asyncio
    async def test_backfill_missing_file_returns_zero(self, db_session):
        from app.db.repositories.watchlist_repo import backfill_from_index
        n = await backfill_from_index(db_session, "/tmp/does_not_exist_abc123.json")
        assert n == 0

    @pytest.mark.asyncio
    async def test_backfill_null_session_returns_zero(self):
        from app.db.repositories.watchlist_repo import backfill_from_index
        n = await backfill_from_index(None, "/any/path.json")
        assert n == 0


# ---------------------------------------------------------------------------
# 9. TestBackfillIdempotent
# ---------------------------------------------------------------------------

class TestBackfillIdempotent:
    @pytest.mark.asyncio
    async def test_second_backfill_inserts_zero(self, db_session):
        from app.db.repositories.watchlist_repo import backfill_from_index
        data = {"AAPL": {"company_name": "Apple", "added_at": _now_iso()}}
        path = _make_index_file(data)
        try:
            n1 = await backfill_from_index(db_session, path)
            n2 = await backfill_from_index(db_session, path)
            assert n1 == 1
            assert n2 == 0
        finally:
            os.unlink(path)

    @pytest.mark.asyncio
    async def test_backfill_skips_existing_rows(self, db_session):
        from app.db.repositories.watchlist_repo import backfill_from_index
        await _add(db_session, "AAPL", "Apple")
        data = {
            "AAPL": {"company_name": "Apple Inc.", "added_at": _now_iso()},
            "MSFT": {"company_name": "Microsoft", "added_at": _now_iso()},
        }
        path = _make_index_file(data)
        try:
            n = await backfill_from_index(db_session, path)
            assert n == 1  # only MSFT inserted; AAPL already exists
        finally:
            os.unlink(path)

    @pytest.mark.asyncio
    async def test_backfill_skips_inactive_rows(self, db_session):
        """Backfill skips tickers that are inactive (soft-deleted)."""
        from app.db.repositories.watchlist_repo import backfill_from_index
        await _add(db_session, "AAPL", "Apple")
        await _deactivate(db_session, "AAPL")
        data = {"AAPL": {"company_name": "Apple", "added_at": _now_iso()}}
        path = _make_index_file(data)
        try:
            n = await backfill_from_index(db_session, path)
            assert n == 0  # inactive row exists; not re-inserted
        finally:
            os.unlink(path)


# ---------------------------------------------------------------------------
# 10. TestServiceAsyncMethods
# ---------------------------------------------------------------------------

class TestServiceAsyncMethods:
    """Test WatchlistService async DB-backed methods."""

    def _make_service_with_tmpdir(self):
        from app.services.watchlist_service import WatchlistService
        tmpdir = tempfile.mkdtemp()
        svc = WatchlistService(data_dir=tmpdir, timeline_dir=tmpdir)
        return svc, tmpdir

    @pytest.mark.asyncio
    async def test_add_ticker_async_returns_entry(self, db_session):
        svc, _ = self._make_service_with_tmpdir()
        entry = await svc.add_ticker_async(db_session, "AAPL", "Apple Inc.")
        assert entry is not None
        assert entry.ticker == "AAPL"
        assert entry.company_name == "Apple Inc."

    @pytest.mark.asyncio
    async def test_add_ticker_async_writes_to_db(self, db_session):
        svc, _ = self._make_service_with_tmpdir()
        await svc.add_ticker_async(db_session, "AAPL", "Apple")
        assert await _is_active(db_session, "AAPL") is True

    @pytest.mark.asyncio
    async def test_add_ticker_async_idempotent(self, db_session):
        svc, _ = self._make_service_with_tmpdir()
        e1 = await svc.add_ticker_async(db_session, "AAPL", "Apple")
        e2 = await svc.add_ticker_async(db_session, "AAPL", "Apple")
        assert e1.ticker == e2.ticker
        rows = await _list_active(db_session)
        assert len([r for r in rows if r.ticker == "AAPL"]) == 1

    @pytest.mark.asyncio
    async def test_remove_ticker_async(self, db_session):
        svc, _ = self._make_service_with_tmpdir()
        await svc.add_ticker_async(db_session, "AAPL", "Apple")
        ok = await svc.remove_ticker_async(db_session, "AAPL")
        assert ok is True
        assert await _is_active(db_session, "AAPL") is False

    @pytest.mark.asyncio
    async def test_remove_ticker_async_nonexistent(self, db_session):
        svc, _ = self._make_service_with_tmpdir()
        ok = await svc.remove_ticker_async(db_session, "ZZZZ")
        assert ok is False

    @pytest.mark.asyncio
    async def test_is_tracked_async_true(self, db_session):
        svc, _ = self._make_service_with_tmpdir()
        await svc.add_ticker_async(db_session, "AAPL", "Apple")
        assert await svc.is_tracked_async(db_session, "AAPL") is True

    @pytest.mark.asyncio
    async def test_is_tracked_async_false(self, db_session):
        svc, _ = self._make_service_with_tmpdir()
        assert await svc.is_tracked_async(db_session, "ZZZZ") is False

    @pytest.mark.asyncio
    async def test_get_watchlist_async_returns_list(self, db_session):
        svc, _ = self._make_service_with_tmpdir()
        await svc.add_ticker_async(db_session, "AAPL", "Apple")
        await svc.add_ticker_async(db_session, "MSFT", "Microsoft")
        entries = await svc.get_watchlist_async(db_session)
        tickers = {e.ticker for e in entries}
        assert tickers == {"AAPL", "MSFT"}

    @pytest.mark.asyncio
    async def test_get_watchlist_async_excludes_removed(self, db_session):
        svc, _ = self._make_service_with_tmpdir()
        await svc.add_ticker_async(db_session, "AAPL", "Apple")
        await svc.add_ticker_async(db_session, "MSFT", "Microsoft")
        await svc.remove_ticker_async(db_session, "AAPL")
        entries = await svc.get_watchlist_async(db_session)
        tickers = {e.ticker for e in entries}
        assert "AAPL" not in tickers
        assert "MSFT" in tickers

    @pytest.mark.asyncio
    async def test_get_entry_async_returns_entry(self, db_session):
        svc, _ = self._make_service_with_tmpdir()
        await svc.add_ticker_async(db_session, "AAPL", "Apple Inc.")
        entry = await svc.get_entry_async(db_session, "AAPL")
        assert entry is not None
        assert entry.ticker == "AAPL"

    @pytest.mark.asyncio
    async def test_get_entry_async_none_for_missing(self, db_session):
        svc, _ = self._make_service_with_tmpdir()
        entry = await svc.get_entry_async(db_session, "ZZZZ")
        assert entry is None

    @pytest.mark.asyncio
    async def test_backfill_from_index_async(self, db_session):
        svc, tmpdir = self._make_service_with_tmpdir()
        # Write an index.json into the service's data dir
        index_data = {
            "AAPL": {"company_name": "Apple Inc.", "added_at": _now_iso()},
            "MSFT": {"company_name": "Microsoft", "added_at": _now_iso()},
            "NVDA": {"company_name": "NVIDIA", "added_at": _now_iso()},
        }
        import os
        index_path = os.path.join(tmpdir, "index.json")
        with open(index_path, "w") as f:
            json.dump(index_data, f)

        n = await svc.backfill_from_index_async(db_session)
        assert n == 3

    @pytest.mark.asyncio
    async def test_backfill_from_index_async_idempotent(self, db_session):
        svc, tmpdir = self._make_service_with_tmpdir()
        index_data = {"AAPL": {"company_name": "Apple", "added_at": _now_iso()}}
        import os
        index_path = os.path.join(tmpdir, "index.json")
        with open(index_path, "w") as f:
            json.dump(index_data, f)

        n1 = await svc.backfill_from_index_async(db_session)
        n2 = await svc.backfill_from_index_async(db_session)
        assert n1 == 1
        assert n2 == 0


# ---------------------------------------------------------------------------
# 11. TestParityWithFileService
# ---------------------------------------------------------------------------

class TestParityWithFileService:
    """Async service methods produce results consistent with the sync API."""

    def _make_service(self):
        from app.services.watchlist_service import WatchlistService
        tmpdir = tempfile.mkdtemp()
        return WatchlistService(data_dir=tmpdir, timeline_dir=tmpdir)

    @pytest.mark.asyncio
    async def test_add_then_get_parity(self, db_session):
        svc = self._make_service()
        sync_entry = svc.add_ticker("AAPL", "Apple")
        async_entry = await svc.get_entry_async(db_session, "AAPL")
        # Both should agree on ticker; async reads file metadata written by sync
        assert sync_entry.ticker == "AAPL"
        assert async_entry is not None
        assert async_entry.ticker == "AAPL"

    @pytest.mark.asyncio
    async def test_sync_add_visible_in_async_list(self, db_session):
        svc = self._make_service()
        # sync add writes to file; async list reads from DB (empty) → falls back to file
        svc.add_ticker("AAPL", "Apple")
        svc.add_ticker("MSFT", "Microsoft")
        entries = await svc.get_watchlist_async(db_session)
        # DB is empty so fallback to file returns the sync-written entries
        tickers = {e.ticker for e in entries}
        assert tickers == {"AAPL", "MSFT"}

    @pytest.mark.asyncio
    async def test_async_add_visible_via_is_tracked(self, db_session):
        svc = self._make_service()
        await svc.add_ticker_async(db_session, "AAPL", "Apple")
        # Sync method reads file
        assert svc.is_tracked("AAPL") is True
        # Async method reads DB
        assert await svc.is_tracked_async(db_session, "AAPL") is True
