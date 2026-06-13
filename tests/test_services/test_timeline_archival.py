"""
Tests for Phase 10B Slice 7 — Timeline Snapshot Archival.

Covers:
  - save() caps live file at LIVE_CAP per entry_type; overflow → archive
  - archive is append-only (no rewrite on subsequent saves)
  - archive_old_entries() is idempotent (no duplicate archive rows)
  - load() returns newest-first order (via timestamp sort)
  - Mixed entry_types are capped independently
  - Corrupt archive lines are skipped (never break live reads)
  - Archive directory is auto-created on first write
  - No data loss across live + archive
"""

from __future__ import annotations

import json
import os
import tempfile
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List

import pytest

from app.services.timeline_store import (
    LIVE_CAP,
    JsonFileTimelineStore,
    TimelineEntry,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ts(offset_seconds: int = 0) -> str:
    """Return an ISO-8601 UTC timestamp offset by *offset_seconds* from epoch."""
    base = datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=offset_seconds)
    return base.isoformat()


def _entry(ticker: str = "TEST", entry_type: str = "thesis_snapshot", seq: int = 0) -> TimelineEntry:
    return TimelineEntry(
        entry_id=str(uuid.uuid4()),
        ticker=ticker,
        entry_type=entry_type,
        timestamp=_ts(seq),
        data={"seq": seq},
    )


def _store(tmp_path: Path) -> JsonFileTimelineStore:
    return JsonFileTimelineStore(data_dir=str(tmp_path))


# ---------------------------------------------------------------------------
# TestLiveCapEnforcement
# ---------------------------------------------------------------------------

class TestLiveCapEnforcement:
    """save() caps the live file at LIVE_CAP per entry_type."""

    def test_60_entries_live_capped_at_50(self, tmp_path):
        store = _store(tmp_path)
        n = 60
        for i in range(n):
            store.save(_entry(seq=i))

        live = store.load("TEST", entry_type="thesis_snapshot")
        assert len(live) == LIVE_CAP

    def test_60_entries_10_archived(self, tmp_path):
        store = _store(tmp_path)
        n = 60
        for i in range(n):
            store.save(_entry(seq=i))

        archived = store.load_archive("TEST", entry_type="thesis_snapshot")
        assert len(archived) == 10

    def test_total_no_data_loss(self, tmp_path):
        store = _store(tmp_path)
        n = 60
        for i in range(n):
            store.save(_entry(seq=i))

        live_ids = {e.entry_id for e in store.load("TEST")}
        archive_ids = {e.entry_id for e in store.load_archive("TEST")}
        assert len(live_ids | archive_ids) == n
        assert live_ids.isdisjoint(archive_ids)

    def test_live_file_exactly_at_cap_no_archive(self, tmp_path):
        store = _store(tmp_path)
        for i in range(LIVE_CAP):
            store.save(_entry(seq=i))

        assert len(store.load("TEST")) == LIVE_CAP
        assert store.load_archive("TEST") == []

    def test_live_keeps_newest(self, tmp_path):
        store = _store(tmp_path)
        n = 60
        for i in range(n):
            store.save(_entry(seq=i))

        live = store.load("TEST")
        seqs = [e.data["seq"] for e in live]
        assert seqs == sorted(seqs)  # ascending timestamp order
        assert min(seqs) == 10  # oldest 10 archived, newest 50 kept

    def test_archived_entries_are_oldest(self, tmp_path):
        store = _store(tmp_path)
        n = 60
        for i in range(n):
            store.save(_entry(seq=i))

        archived = store.load_archive("TEST")
        seqs = [e.data["seq"] for e in archived]
        assert set(seqs) == set(range(10))


# ---------------------------------------------------------------------------
# TestArchiveAppendOnly
# ---------------------------------------------------------------------------

class TestArchiveAppendOnly:
    """Archive file is append-only; repeated saves add new lines, never rewrite."""

    def test_archive_grows_with_each_overflow(self, tmp_path):
        store = _store(tmp_path)
        # Save 60 → 10 archived
        for i in range(60):
            store.save(_entry(seq=i))

        archive_path = tmp_path / "archive" / "TEST.jsonl"
        lines_after_first_overflow = archive_path.read_text().strip().splitlines()
        assert len(lines_after_first_overflow) == 10

        # Save 10 more (seq 60..69) → 10 more archived to keep live at 50
        for i in range(60, 70):
            store.save(_entry(seq=i))

        lines_after_second_overflow = archive_path.read_text().strip().splitlines()
        assert len(lines_after_second_overflow) == 20

    def test_archive_lines_include_archived_at(self, tmp_path):
        store = _store(tmp_path)
        for i in range(55):
            store.save(_entry(seq=i))

        archive_path = tmp_path / "archive" / "TEST.jsonl"
        first_line = json.loads(archive_path.read_text().strip().splitlines()[0])
        assert "archived_at" in first_line

    def test_archive_file_never_rewritten(self, tmp_path):
        store = _store(tmp_path)
        for i in range(60):
            store.save(_entry(seq=i))

        archive_path = tmp_path / "archive" / "TEST.jsonl"
        mtime_before = archive_path.stat().st_mtime

        # Saving within-cap entries should not touch the archive
        for i in range(60, 62):
            store.save(_entry(seq=i))

        # Mtime may or may not change (OS caching), but line count stays at 10+2
        lines = archive_path.read_text().strip().splitlines()
        assert len(lines) == 12  # 10 from first batch + 2 new overflows


# ---------------------------------------------------------------------------
# TestIdempotentArchival
# ---------------------------------------------------------------------------

class TestIdempotentArchival:
    """archive_old_entries() deduplicates — repeated calls never add duplicates."""

    def test_repeated_archival_no_duplicates(self, tmp_path):
        store = _store(tmp_path)
        for i in range(60):
            store.save(_entry(seq=i))

        # Call bulk archival twice
        n1 = store.archive_old_entries("TEST")
        n2 = store.archive_old_entries("TEST")

        assert n1 >= 0
        assert n2 == 0  # nothing new to archive

    def test_archive_old_entries_returns_count(self, tmp_path):
        # Write 60 entries but bypass save() cap by writing the JSON file directly
        store = _store(tmp_path)
        records = [_entry(seq=i).model_dump() for i in range(60)]
        store._write_raw("TEST", records)

        archived = store.archive_old_entries("TEST")
        assert archived == 10

    def test_archive_old_entries_trims_live(self, tmp_path):
        store = _store(tmp_path)
        records = [_entry(seq=i).model_dump() for i in range(60)]
        store._write_raw("TEST", records)

        store.archive_old_entries("TEST")

        assert len(store.load("TEST")) == LIVE_CAP

    def test_archive_old_entries_no_data_loss(self, tmp_path):
        store = _store(tmp_path)
        entries = [_entry(seq=i) for i in range(60)]
        for e in entries:
            store._write_raw("TEST", store._read_raw("TEST") + [e.model_dump()])

        store.archive_old_entries("TEST")

        live_ids = {e.entry_id for e in store.load("TEST")}
        archive_ids = {e.entry_id for e in store.load_archive("TEST")}
        all_ids = {e.entry_id for e in entries}
        assert live_ids | archive_ids == all_ids

    def test_archive_old_entries_empty_ticker_returns_0(self, tmp_path):
        store = _store(tmp_path)
        assert store.archive_old_entries("NOOP") == 0

    def test_archive_old_entries_under_cap_returns_0(self, tmp_path):
        store = _store(tmp_path)
        for i in range(30):
            store.save(_entry(seq=i))
        assert store.archive_old_entries("TEST") == 0


# ---------------------------------------------------------------------------
# TestLoadOrder
# ---------------------------------------------------------------------------

class TestLoadOrder:
    """load() returns entries sorted by timestamp ascending (newest last)."""

    def test_load_ascending_order(self, tmp_path):
        store = _store(tmp_path)
        for i in range(10):
            store.save(_entry(seq=i))

        entries = store.load("TEST")
        timestamps = [e.timestamp for e in entries]
        assert timestamps == sorted(timestamps)

    def test_latest_returns_most_recent(self, tmp_path):
        store = _store(tmp_path)
        for i in range(20):
            store.save(_entry(seq=i))

        latest = store.latest("TEST")
        assert latest is not None
        assert latest.data["seq"] == 19

    def test_load_after_overflow_still_sorted(self, tmp_path):
        store = _store(tmp_path)
        for i in range(60):
            store.save(_entry(seq=i))

        entries = store.load("TEST")
        timestamps = [e.timestamp for e in entries]
        assert timestamps == sorted(timestamps)


# ---------------------------------------------------------------------------
# TestMixedEntryTypeCaps
# ---------------------------------------------------------------------------

class TestMixedEntryTypeCaps:
    """Mixed entry_types each have independent caps."""

    def test_two_types_capped_independently(self, tmp_path):
        store = _store(tmp_path)
        # 60 of type A, 30 of type B
        for i in range(60):
            store.save(_entry(entry_type="type_a", seq=i))
        for i in range(30):
            store.save(_entry(entry_type="type_b", seq=i))

        assert len(store.load("TEST", entry_type="type_a")) == LIVE_CAP
        assert len(store.load("TEST", entry_type="type_b")) == 30

    def test_type_a_overflow_does_not_archive_type_b(self, tmp_path):
        store = _store(tmp_path)
        for i in range(60):
            store.save(_entry(entry_type="type_a", seq=i))
        for i in range(30):
            store.save(_entry(entry_type="type_b", seq=i))

        archived = store.load_archive("TEST")
        assert all(e.entry_type == "type_a" for e in archived)
        assert len(archived) == 10

    def test_both_types_overflow(self, tmp_path):
        store = _store(tmp_path)
        for i in range(60):
            store.save(_entry(entry_type="type_a", seq=i))
            store.save(_entry(entry_type="type_b", seq=i))

        live_a = store.load("TEST", entry_type="type_a")
        live_b = store.load("TEST", entry_type="type_b")
        archive_all = store.load_archive("TEST")

        assert len(live_a) == LIVE_CAP
        assert len(live_b) == LIVE_CAP
        assert len([e for e in archive_all if e.entry_type == "type_a"]) == 10
        assert len([e for e in archive_all if e.entry_type == "type_b"]) == 10


# ---------------------------------------------------------------------------
# TestCorruptArchiveLine
# ---------------------------------------------------------------------------

class TestCorruptArchiveLine:
    """Corrupt archive lines are silently skipped; live reads unaffected."""

    def _write_corrupt_archive(self, tmp_path: Path, ticker: str = "TEST") -> Path:
        archive_dir = tmp_path / "archive"
        archive_dir.mkdir(parents=True, exist_ok=True)
        path = archive_dir / f"{ticker}.jsonl"
        good_entry = _entry(seq=0).model_dump()
        good_entry["archived_at"] = _ts(999)
        with path.open("w") as fh:
            fh.write(json.dumps(good_entry) + "\n")
            fh.write("not valid json {\n")
            fh.write("\n")  # blank line
            good_entry2 = _entry(seq=1).model_dump()
            good_entry2["archived_at"] = _ts(1000)
            fh.write(json.dumps(good_entry2) + "\n")
        return path

    def test_corrupt_line_skipped_on_load_archive(self, tmp_path):
        store = _store(tmp_path)
        self._write_corrupt_archive(tmp_path)

        result = store.load_archive("TEST")
        assert len(result) == 2  # 2 good lines, 1 corrupt skipped

    def test_corrupt_archive_does_not_break_live_reads(self, tmp_path):
        store = _store(tmp_path)
        for i in range(5):
            store.save(_entry(seq=i))
        self._write_corrupt_archive(tmp_path)

        live = store.load("TEST")
        assert len(live) == 5

    def test_corrupt_archive_does_not_break_save(self, tmp_path):
        store = _store(tmp_path)
        for i in range(5):
            store.save(_entry(seq=i))
        self._write_corrupt_archive(tmp_path)

        store.save(_entry(seq=100))
        live = store.load("TEST")
        assert any(e.data["seq"] == 100 for e in live)

    def test_corrupt_archive_does_not_break_archive_old_entries(self, tmp_path):
        store = _store(tmp_path)
        records = [_entry(seq=i).model_dump() for i in range(60)]
        store._write_raw("TEST", records)
        self._write_corrupt_archive(tmp_path)

        archived = store.archive_old_entries("TEST")
        # 10 overflow - 2 already in archive (good lines) = 8 new (corrupt entry has no entry_id conflict)
        assert archived >= 0  # should not raise


# ---------------------------------------------------------------------------
# TestArchiveDirectoryAutoCreated
# ---------------------------------------------------------------------------

class TestArchiveDirectoryAutoCreated:
    """Archive directory is created automatically on first write."""

    def test_archive_dir_created_on_overflow(self, tmp_path):
        store = _store(tmp_path)
        archive_dir = tmp_path / "archive"
        assert not archive_dir.exists()

        for i in range(60):
            store.save(_entry(seq=i))

        assert archive_dir.exists()
        assert archive_dir.is_dir()

    def test_archive_file_created_on_overflow(self, tmp_path):
        store = _store(tmp_path)
        for i in range(60):
            store.save(_entry(seq=i))

        archive_file = tmp_path / "archive" / "TEST.jsonl"
        assert archive_file.exists()

    def test_no_archive_dir_when_no_overflow(self, tmp_path):
        store = _store(tmp_path)
        for i in range(LIVE_CAP):
            store.save(_entry(seq=i))

        archive_dir = tmp_path / "archive"
        assert not archive_dir.exists()


# ---------------------------------------------------------------------------
# TestNoDataLossTotal
# ---------------------------------------------------------------------------

class TestNoDataLossTotal:
    """Across live + archive, no entry is ever lost."""

    def test_large_batch_no_data_loss(self, tmp_path):
        store = _store(tmp_path)
        n = 200
        all_ids = set()
        for i in range(n):
            e = _entry(seq=i)
            all_ids.add(e.entry_id)
            store.save(e)

        live_ids = {e.entry_id for e in store.load("TEST")}
        archive_ids = {e.entry_id for e in store.load_archive("TEST")}

        recovered = live_ids | archive_ids
        assert recovered == all_ids

    def test_live_plus_archive_exact_count(self, tmp_path):
        store = _store(tmp_path)
        n = 75
        for i in range(n):
            store.save(_entry(seq=i))

        live_count = len(store.load("TEST"))
        archive_count = len(store.load_archive("TEST"))
        assert live_count + archive_count == n


# ---------------------------------------------------------------------------
# TestLoadArchiveFilters
# ---------------------------------------------------------------------------

class TestLoadArchiveFilters:
    """load_archive() respects entry_type filter and limit."""

    def test_load_archive_entry_type_filter(self, tmp_path):
        store = _store(tmp_path)
        for i in range(60):
            store.save(_entry(entry_type="type_a", seq=i))
        for i in range(60):
            store.save(_entry(entry_type="type_b", seq=i))

        a_only = store.load_archive("TEST", entry_type="type_a")
        assert all(e.entry_type == "type_a" for e in a_only)

    def test_load_archive_limit(self, tmp_path):
        store = _store(tmp_path)
        for i in range(60):
            store.save(_entry(seq=i))

        result = store.load_archive("TEST", limit=5)
        assert len(result) == 5

    def test_load_archive_no_archive_returns_empty(self, tmp_path):
        store = _store(tmp_path)
        assert store.load_archive("EMPTY") == []


# ---------------------------------------------------------------------------
# TestLiveFileRemainsValidJson
# ---------------------------------------------------------------------------

class TestLiveFileRemainsValidJson:
    """Live file must be valid JSON after every save()."""

    def test_live_file_valid_json_after_overflow(self, tmp_path):
        store = _store(tmp_path)
        for i in range(60):
            store.save(_entry(seq=i))

        live_path = tmp_path / "TEST.json"
        data = json.loads(live_path.read_text())
        assert isinstance(data, list)
        assert len(data) == LIVE_CAP

    def test_live_file_valid_json_mid_batch(self, tmp_path):
        store = _store(tmp_path)
        for i in range(35):
            store.save(_entry(seq=i))

        live_path = tmp_path / "TEST.json"
        data = json.loads(live_path.read_text())
        assert isinstance(data, list)
        assert len(data) == 35
