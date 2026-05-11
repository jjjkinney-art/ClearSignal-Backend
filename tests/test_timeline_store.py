"""
Tests for app.services.timeline_store.

Classes under test
------------------
TimelineEntry   — Pydantic domain model for a single timestamped snapshot
JsonFileTimelineStore — flat-file implementation of TimelineStore

All tests use pytest's built-in tmp_path fixture so they never touch the real
filesystem or the default `.clearSignal_timeline/` directory.

No network calls, no LLM calls.
"""

from __future__ import annotations

import time

import pytest
from app.services.timeline_store import JsonFileTimelineStore, TimelineEntry


# ---------------------------------------------------------------------------
# Convenience factory
# ---------------------------------------------------------------------------

def _make_store(tmp_path) -> JsonFileTimelineStore:
    return JsonFileTimelineStore(str(tmp_path))


def _entry(
    ticker: str = "AAPL",
    entry_type: str = "thesis",
    data: dict | None = None,
    metadata: dict | None = None,
    timestamp: str = "",
) -> TimelineEntry:
    kwargs: dict = {"ticker": ticker, "entry_type": entry_type}
    if data is not None:
        kwargs["data"] = data
    if metadata is not None:
        kwargs["metadata"] = metadata
    if timestamp:
        kwargs["timestamp"] = timestamp
    return TimelineEntry(**kwargs)


# ---------------------------------------------------------------------------
# TestTimelineEntry
# ---------------------------------------------------------------------------

class TestTimelineEntry:
    """Unit tests for the TimelineEntry domain model."""

    def test_entry_id_auto_generated_when_not_provided(self):
        e = TimelineEntry(ticker="AAPL", entry_type="thesis")
        assert isinstance(e.entry_id, str)
        assert len(e.entry_id) > 0

    def test_entry_id_is_unique_across_instances(self):
        e1 = TimelineEntry(ticker="AAPL", entry_type="thesis")
        e2 = TimelineEntry(ticker="AAPL", entry_type="thesis")
        assert e1.entry_id != e2.entry_id

    def test_explicit_entry_id_is_preserved(self):
        e = TimelineEntry(ticker="AAPL", entry_type="thesis", entry_id="my-id-123")
        assert e.entry_id == "my-id-123"

    def test_timestamp_defaults_to_empty_string(self):
        # The TimelineEntry model sets timestamp="" by default;
        # the store fills it in during save().
        e = TimelineEntry(ticker="AAPL", entry_type="thesis")
        assert e.timestamp == ""

    def test_data_defaults_to_empty_dict(self):
        e = TimelineEntry(ticker="AAPL", entry_type="thesis")
        assert e.data == {}

    def test_metadata_defaults_to_empty_dict(self):
        e = TimelineEntry(ticker="AAPL", entry_type="thesis")
        assert e.metadata == {}

    def test_data_is_preserved(self):
        payload = {"bull_thesis": "strong growth", "bear_thesis": "competition risk"}
        e = TimelineEntry(ticker="AAPL", entry_type="thesis", data=payload)
        assert e.data == payload

    def test_metadata_is_preserved(self):
        meta = {"source": "analysis_service", "version": "2"}
        e = TimelineEntry(ticker="AAPL", entry_type="thesis", metadata=meta)
        assert e.metadata == meta

    def test_ticker_and_entry_type_are_required(self):
        with pytest.raises(Exception):
            TimelineEntry()  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# TestJsonFileTimelineStoreSave
# ---------------------------------------------------------------------------

class TestJsonFileTimelineStoreSave:
    """Tests for JsonFileTimelineStore.save()."""

    def test_save_returns_non_empty_string(self, tmp_path):
        store = _make_store(tmp_path)
        entry_id = store.save(_entry())
        assert isinstance(entry_id, str)
        assert len(entry_id) > 0

    def test_save_returns_entry_id_matching_entry_field(self, tmp_path):
        store = _make_store(tmp_path)
        e = _entry(ticker="AAPL", entry_type="thesis")
        entry_id = store.save(e)
        assert entry_id == e.entry_id

    def test_saving_two_entries_for_same_ticker_both_stored(self, tmp_path):
        store = _make_store(tmp_path)
        store.save(_entry(ticker="NVDA", data={"note": "first"}))
        store.save(_entry(ticker="NVDA", data={"note": "second"}))
        entries = store.load("NVDA")
        assert len(entries) == 2

    def test_save_creates_data_directory_if_not_exists(self, tmp_path):
        subdir = tmp_path / "nested" / "dir"
        store = JsonFileTimelineStore(str(subdir))
        store.save(_entry())
        assert subdir.exists()

    def test_save_creates_json_file_for_ticker(self, tmp_path):
        store = _make_store(tmp_path)
        store.save(_entry(ticker="MSFT"))
        assert (tmp_path / "MSFT.json").exists()

    def test_save_auto_stamps_timestamp_when_empty(self, tmp_path):
        store = _make_store(tmp_path)
        e = _entry(ticker="AAPL", timestamp="")
        store.save(e)
        entries = store.load("AAPL")
        assert len(entries) == 1
        assert entries[0].timestamp != ""

    def test_save_preserves_explicit_timestamp(self, tmp_path):
        store = _make_store(tmp_path)
        ts = "2025-01-15T12:00:00+00:00"
        e = _entry(ticker="AAPL", timestamp=ts)
        store.save(e)
        entries = store.load("AAPL")
        assert entries[0].timestamp == ts

    def test_multiple_tickers_stored_independently(self, tmp_path):
        store = _make_store(tmp_path)
        store.save(_entry(ticker="AAPL"))
        store.save(_entry(ticker="NVDA"))
        assert len(store.load("AAPL")) == 1
        assert len(store.load("NVDA")) == 1


# ---------------------------------------------------------------------------
# TestJsonFileTimelineStoreLoad
# ---------------------------------------------------------------------------

class TestJsonFileTimelineStoreLoad:
    """Tests for JsonFileTimelineStore.load()."""

    def test_load_returns_empty_list_for_unknown_ticker(self, tmp_path):
        store = _make_store(tmp_path)
        result = store.load("UNKNOWN")
        assert result == []

    def test_load_returns_empty_list_when_file_does_not_exist(self, tmp_path):
        store = _make_store(tmp_path)
        result = store.load("ZZZZ")
        assert result == []

    def test_load_returns_saved_entries(self, tmp_path):
        store = _make_store(tmp_path)
        store.save(_entry(ticker="AAPL", data={"note": "hello"}))
        entries = store.load("AAPL")
        assert len(entries) == 1
        assert entries[0].data == {"note": "hello"}

    def test_load_returns_all_entries_without_filter(self, tmp_path):
        store = _make_store(tmp_path)
        store.save(_entry(ticker="AAPL", entry_type="thesis"))
        store.save(_entry(ticker="AAPL", entry_type="evidence_snapshot"))
        store.save(_entry(ticker="AAPL", entry_type="analysis"))
        entries = store.load("AAPL")
        assert len(entries) == 3

    def test_load_with_entry_type_filter_returns_only_matching(self, tmp_path):
        store = _make_store(tmp_path)
        store.save(_entry(ticker="AAPL", entry_type="thesis"))
        store.save(_entry(ticker="AAPL", entry_type="evidence_snapshot"))
        store.save(_entry(ticker="AAPL", entry_type="thesis"))
        entries = store.load("AAPL", entry_type="thesis")
        assert len(entries) == 2
        assert all(e.entry_type == "thesis" for e in entries)

    def test_load_with_entry_type_filter_excludes_other_types(self, tmp_path):
        store = _make_store(tmp_path)
        store.save(_entry(ticker="AAPL", entry_type="thesis"))
        store.save(_entry(ticker="AAPL", entry_type="alert"))
        entries = store.load("AAPL", entry_type="thesis")
        assert all(e.entry_type != "alert" for e in entries)

    def test_load_returns_entries_sorted_ascending_by_timestamp(self, tmp_path):
        store = _make_store(tmp_path)
        store.save(_entry(ticker="AAPL", timestamp="2025-01-01T00:00:00+00:00"))
        store.save(_entry(ticker="AAPL", timestamp="2025-03-01T00:00:00+00:00"))
        store.save(_entry(ticker="AAPL", timestamp="2025-02-01T00:00:00+00:00"))
        entries = store.load("AAPL")
        timestamps = [e.timestamp for e in entries]
        assert timestamps == sorted(timestamps)

    def test_load_returns_timeline_entry_instances(self, tmp_path):
        store = _make_store(tmp_path)
        store.save(_entry(ticker="AAPL"))
        entries = store.load("AAPL")
        assert all(isinstance(e, TimelineEntry) for e in entries)

    def test_load_preserves_data_payload(self, tmp_path):
        store = _make_store(tmp_path)
        payload = {"bull": "strong AI tailwind", "confidence": 0.85}
        store.save(_entry(ticker="NVDA", data=payload))
        entries = store.load("NVDA")
        assert entries[0].data == payload

    def test_load_preserves_ticker_field(self, tmp_path):
        store = _make_store(tmp_path)
        store.save(_entry(ticker="MSFT"))
        entries = store.load("MSFT")
        assert entries[0].ticker == "MSFT"


# ---------------------------------------------------------------------------
# TestJsonFileTimelineStoreLatest
# ---------------------------------------------------------------------------

class TestJsonFileTimelineStoreLatest:
    """Tests for JsonFileTimelineStore.latest()."""

    def test_latest_returns_none_for_unknown_ticker(self, tmp_path):
        store = _make_store(tmp_path)
        assert store.latest("NOTHERE") is None

    def test_latest_returns_most_recent_entry(self, tmp_path):
        store = _make_store(tmp_path)
        store.save(_entry(ticker="AAPL", timestamp="2025-01-01T00:00:00+00:00", data={"v": 1}))
        store.save(_entry(ticker="AAPL", timestamp="2025-06-01T00:00:00+00:00", data={"v": 2}))
        store.save(_entry(ticker="AAPL", timestamp="2025-03-01T00:00:00+00:00", data={"v": 3}))
        latest = store.latest("AAPL")
        assert latest is not None
        assert latest.data == {"v": 2}

    def test_latest_with_entry_type_returns_latest_of_that_type(self, tmp_path):
        store = _make_store(tmp_path)
        store.save(_entry(ticker="AAPL", entry_type="thesis",
                          timestamp="2025-01-01T00:00:00+00:00", data={"note": "old thesis"}))
        store.save(_entry(ticker="AAPL", entry_type="alert",
                          timestamp="2025-09-01T00:00:00+00:00", data={"note": "newest alert"}))
        store.save(_entry(ticker="AAPL", entry_type="thesis",
                          timestamp="2025-06-01T00:00:00+00:00", data={"note": "new thesis"}))
        latest_thesis = store.latest("AAPL", entry_type="thesis")
        assert latest_thesis is not None
        assert latest_thesis.data == {"note": "new thesis"}

    def test_latest_with_type_filter_excludes_other_types(self, tmp_path):
        store = _make_store(tmp_path)
        store.save(_entry(ticker="AAPL", entry_type="alert",
                          timestamp="2025-12-01T00:00:00+00:00"))
        latest_thesis = store.latest("AAPL", entry_type="thesis")
        assert latest_thesis is None

    def test_latest_when_two_entries_same_type_returns_newer(self, tmp_path):
        store = _make_store(tmp_path)
        store.save(_entry(ticker="AAPL", entry_type="thesis",
                          timestamp="2025-01-01T00:00:00+00:00", data={"round": 1}))
        store.save(_entry(ticker="AAPL", entry_type="thesis",
                          timestamp="2025-07-01T00:00:00+00:00", data={"round": 2}))
        latest = store.latest("AAPL", entry_type="thesis")
        assert latest is not None
        assert latest.data == {"round": 2}

    def test_latest_returns_timeline_entry_instance(self, tmp_path):
        store = _make_store(tmp_path)
        store.save(_entry(ticker="AAPL"))
        latest = store.latest("AAPL")
        assert isinstance(latest, TimelineEntry)

    def test_latest_single_entry_returns_that_entry(self, tmp_path):
        store = _make_store(tmp_path)
        e = _entry(ticker="AAPL", data={"only": "entry"})
        store.save(e)
        latest = store.latest("AAPL")
        assert latest is not None
        assert latest.entry_id == e.entry_id


# ---------------------------------------------------------------------------
# TestJsonFileTimelineStoreAllTickers
# ---------------------------------------------------------------------------

class TestJsonFileTimelineStoreAllTickers:
    """Tests for JsonFileTimelineStore.all_tickers()."""

    def test_all_tickers_returns_empty_list_for_empty_store(self, tmp_path):
        store = _make_store(tmp_path)
        assert store.all_tickers() == []

    def test_all_tickers_returns_saved_tickers(self, tmp_path):
        store = _make_store(tmp_path)
        store.save(_entry(ticker="AAPL"))
        store.save(_entry(ticker="NVDA"))
        tickers = store.all_tickers()
        assert "AAPL" in tickers
        assert "NVDA" in tickers

    def test_all_tickers_does_not_include_json_extension(self, tmp_path):
        store = _make_store(tmp_path)
        store.save(_entry(ticker="MSFT"))
        tickers = store.all_tickers()
        assert all(".json" not in t for t in tickers)

    def test_all_tickers_deduplicates_same_ticker(self, tmp_path):
        store = _make_store(tmp_path)
        store.save(_entry(ticker="AAPL", data={"n": 1}))
        store.save(_entry(ticker="AAPL", data={"n": 2}))
        tickers = store.all_tickers()
        # Only one file per ticker, so ticker appears once
        assert tickers.count("AAPL") == 1

    def test_all_tickers_returns_sorted_list(self, tmp_path):
        store = _make_store(tmp_path)
        for ticker in ("TSLA", "AAPL", "NVDA", "MSFT"):
            store.save(_entry(ticker=ticker))
        tickers = store.all_tickers()
        assert tickers == sorted(tickers)

    def test_all_tickers_contains_correct_count(self, tmp_path):
        store = _make_store(tmp_path)
        for ticker in ("AAPL", "NVDA", "MSFT"):
            store.save(_entry(ticker=ticker))
        assert len(store.all_tickers()) == 3


# ---------------------------------------------------------------------------
# TestTimelineEntryTypes
# ---------------------------------------------------------------------------

class TestTimelineEntryTypes:
    """Verify all documented entry_type values round-trip through the store."""

    @pytest.mark.parametrize("entry_type", [
        "thesis",
        "evidence_snapshot",
        "analysis",
        "alert",
    ])
    def test_entry_type_saved_and_loaded(self, tmp_path, entry_type):
        store = _make_store(tmp_path)
        store.save(_entry(ticker="AAPL", entry_type=entry_type))
        entries = store.load("AAPL", entry_type=entry_type)
        assert len(entries) == 1
        assert entries[0].entry_type == entry_type

    def test_thesis_type_isolated_by_filter(self, tmp_path):
        store = _make_store(tmp_path)
        store.save(_entry(ticker="AAPL", entry_type="thesis"))
        store.save(_entry(ticker="AAPL", entry_type="analysis"))
        entries = store.load("AAPL", entry_type="thesis")
        assert len(entries) == 1
        assert entries[0].entry_type == "thesis"

    def test_alert_type_isolated_by_filter(self, tmp_path):
        store = _make_store(tmp_path)
        store.save(_entry(ticker="AAPL", entry_type="thesis"))
        store.save(_entry(ticker="AAPL", entry_type="alert"))
        entries = store.load("AAPL", entry_type="alert")
        assert len(entries) == 1
        assert entries[0].entry_type == "alert"

    def test_evidence_snapshot_type_isolated_by_filter(self, tmp_path):
        store = _make_store(tmp_path)
        store.save(_entry(ticker="NVDA", entry_type="evidence_snapshot"))
        store.save(_entry(ticker="NVDA", entry_type="thesis"))
        entries = store.load("NVDA", entry_type="evidence_snapshot")
        assert len(entries) == 1
        assert entries[0].entry_type == "evidence_snapshot"


# ---------------------------------------------------------------------------
# TestPersistence
# ---------------------------------------------------------------------------

class TestPersistence:
    """Data written by one store instance is visible to a second instance
    pointing at the same directory."""

    def test_new_instance_reads_data_saved_by_first_instance(self, tmp_path):
        store1 = JsonFileTimelineStore(str(tmp_path))
        payload = {"bull_thesis": "AI platform dominance", "confidence": 0.9}
        store1.save(_entry(ticker="NVDA", data=payload))

        # Create a completely new store instance, same directory
        store2 = JsonFileTimelineStore(str(tmp_path))
        entries = store2.load("NVDA")
        assert len(entries) == 1
        assert entries[0].data == payload

    def test_new_instance_sees_all_tickers(self, tmp_path):
        store1 = JsonFileTimelineStore(str(tmp_path))
        for ticker in ("AAPL", "MSFT", "NVDA"):
            store1.save(_entry(ticker=ticker))

        store2 = JsonFileTimelineStore(str(tmp_path))
        tickers = store2.all_tickers()
        assert "AAPL" in tickers
        assert "MSFT" in tickers
        assert "NVDA" in tickers

    def test_new_instance_latest_agrees_with_original_instance(self, tmp_path):
        store1 = JsonFileTimelineStore(str(tmp_path))
        store1.save(_entry(ticker="AAPL", timestamp="2025-01-01T00:00:00+00:00",
                           data={"v": 1}))
        store1.save(_entry(ticker="AAPL", timestamp="2025-12-01T00:00:00+00:00",
                           data={"v": 2}))

        store2 = JsonFileTimelineStore(str(tmp_path))
        latest = store2.latest("AAPL")
        assert latest is not None
        assert latest.data == {"v": 2}

    def test_appending_via_second_instance(self, tmp_path):
        store1 = JsonFileTimelineStore(str(tmp_path))
        store1.save(_entry(ticker="AAPL", data={"seq": 1}))

        store2 = JsonFileTimelineStore(str(tmp_path))
        store2.save(_entry(ticker="AAPL", data={"seq": 2}))

        # A third instance should see both
        store3 = JsonFileTimelineStore(str(tmp_path))
        entries = store3.load("AAPL")
        assert len(entries) == 2

    def test_entry_id_survives_persistence(self, tmp_path):
        store1 = JsonFileTimelineStore(str(tmp_path))
        e = _entry(ticker="AAPL")
        original_id = e.entry_id
        store1.save(e)

        store2 = JsonFileTimelineStore(str(tmp_path))
        entries = store2.load("AAPL")
        assert entries[0].entry_id == original_id
