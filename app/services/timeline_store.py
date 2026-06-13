"""
Timeline persistence store.

Stores timestamped snapshots of investment analyses, theses, and evidence
so callers can track how a thesis evolves over time.  The abstract base
class (TimelineStore) defines the interface; JsonFileTimelineStore is the
default implementation that writes one JSON file per ticker under a
configurable data directory.

Phase 10B · Slice 7 — Timeline cap-and-archive
-----------------------------------------------
JsonFileTimelineStore now enforces a per-entry_type cap on the live file
(default: 50 entries).  When a save() would push an entry_type above the
cap, the oldest overflow entries are immediately moved to an append-only
JSONL archive:

    .clearSignal_timeline/archive/{TICKER}.jsonl

Archive properties
------------------
  * JSONL (one JSON object per line)
  * append-only; never rewritten
  * each line preserves the original TimelineEntry payload plus an
    ``archived_at`` ISO-8601 UTC timestamp field
  * corrupt archive lines are silently skipped on read
  * archive directory is auto-created on first write

Explicit bulk archival
----------------------
    store.archive_old_entries("AAPL")

Idempotent: reads existing entry_ids from the archive before appending;
entries already in the archive are never duplicated.  Use this to
migrate existing large files (e.g. AAPL with 475 entries).

Read paths
----------
  * load() / latest()  — fast, reads only the live file (bounded ≤ cap)
  * load_archive()     — reads from the JSONL archive; optional entry_type
                         filter and pagination via ``limit``

Swapping to a database backend requires only a new subclass — the public
API (save / load / latest / all_tickers) stays identical.

Usage
-----
    from app.services.timeline_store import JsonFileTimelineStore
    store = JsonFileTimelineStore()                 # default: .clearSignal_timeline/
    store = JsonFileTimelineStore("/tmp/tl")        # custom directory

    entry_id = store.save(TimelineEntry(
        ticker="AAPL",
        entry_type="thesis_snapshot",
        data={"bull_thesis": "...", "bear_thesis": "..."},
    ))

    entries       = store.load("AAPL")
    latest        = store.latest("AAPL")
    tickers       = store.all_tickers()
    archived      = store.load_archive("AAPL", entry_type="thesis_snapshot", limit=100)
    archived_n    = store.archive_old_entries("AAPL")  # bulk migrate
"""

from __future__ import annotations

import json
import logging
import uuid
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# Live-file cap: maximum entries per ticker per entry_type retained in the
# JSON live file.  Entries beyond this limit are moved to the JSONL archive.
LIVE_CAP: int = 50
# Subdirectory inside data_dir that holds all JSONL archive files.
ARCHIVE_SUBDIR: str = "archive"


# ---------------------------------------------------------------------------
# Domain model
# ---------------------------------------------------------------------------


class TimelineEntry(BaseModel):
    """A single timestamped snapshot stored in the timeline."""

    entry_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    ticker: str
    entry_type: str  # "thesis" | "evidence_snapshot" | "analysis" | "alert"
    timestamp: str = Field(
        default="",
        description="ISO-8601 UTC timestamp; auto-set to now if empty on save.",
    )
    data: Dict[str, Any] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Abstract interface
# ---------------------------------------------------------------------------


class TimelineStore(ABC):
    """Interface contract for timeline persistence backends."""

    @abstractmethod
    def save(self, entry: TimelineEntry) -> str:
        """Persist *entry* and return its entry_id."""

    @abstractmethod
    def load(
        self,
        ticker: str,
        entry_type: Optional[str] = None,
    ) -> List[TimelineEntry]:
        """Return all entries for *ticker*, optionally filtered by *entry_type*.

        Entries are sorted by timestamp ascending.  Returns [] when no data
        exists for the ticker.
        """

    @abstractmethod
    def latest(
        self,
        ticker: str,
        entry_type: Optional[str] = None,
    ) -> Optional[TimelineEntry]:
        """Return the most recent entry for *ticker* (optionally by type).

        Returns None when no matching entry exists.
        """

    @abstractmethod
    def all_tickers(self) -> List[str]:
        """Return the list of tickers that have at least one stored entry."""


# ---------------------------------------------------------------------------
# JSON-file implementation
# ---------------------------------------------------------------------------


class JsonFileTimelineStore(TimelineStore):
    """Flat-file timeline store: one JSON array file per ticker.

    The live directory is created on first use.  Each live file is named
    ``{TICKER}.json`` and contains a JSON array of ≤ LIVE_CAP serialised
    TimelineEntry objects per entry_type.  Older entries are automatically
    moved to ``{data_dir}/archive/{TICKER}.jsonl``.

    This implementation is intentionally simple and suitable for
    development, testing, and single-process deployments.  Replace with a
    database-backed subclass for production multi-process use.
    """

    def __init__(self, data_dir: str = ".clearSignal_timeline") -> None:
        self._data_dir = Path(data_dir)
        try:
            self._data_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            logger.warning(
                "JsonFileTimelineStore: could not create data directory %s: %s",
                self._data_dir,
                exc,
            )

    # ------------------------------------------------------------------
    # Live-file helpers
    # ------------------------------------------------------------------

    def _ticker_path(self, ticker: str) -> Path:
        return self._data_dir / f"{ticker.upper()}.json"

    def _read_raw(self, ticker: str) -> List[Dict[str, Any]]:
        """Read and deserialise the raw JSON array for *ticker*.

        Returns an empty list if the file does not exist or is malformed.
        """
        path = self._ticker_path(ticker)
        try:
            if not path.exists():
                return []
            with path.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
            if not isinstance(data, list):
                logger.warning(
                    "JsonFileTimelineStore: %s has unexpected format (not a list)",
                    path,
                )
                return []
            return data
        except Exception as exc:
            logger.warning(
                "JsonFileTimelineStore: error reading %s: %s", path, exc
            )
            return []

    def _write_raw(self, ticker: str, records: List[Dict[str, Any]]) -> None:
        path = self._ticker_path(ticker)
        try:
            with path.open("w", encoding="utf-8") as fh:
                json.dump(records, fh, indent=2, default=str)
        except Exception as exc:
            logger.warning(
                "JsonFileTimelineStore: error writing %s: %s", path, exc
            )

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    # ------------------------------------------------------------------
    # Archive helpers
    # ------------------------------------------------------------------

    def _archive_dir(self) -> Path:
        return self._data_dir / ARCHIVE_SUBDIR

    def _archive_path(self, ticker: str) -> Path:
        return self._archive_dir() / f"{ticker.upper()}.jsonl"

    def _ensure_archive_dir(self) -> None:
        try:
            self._archive_dir().mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            logger.warning(
                "JsonFileTimelineStore: could not create archive dir %s: %s",
                self._archive_dir(), exc,
            )

    def _read_archived_entry_ids(self, ticker: str) -> set:
        """Return the set of entry_ids already in the archive.

        Corrupt archive lines are silently skipped — they never break reads.
        """
        path = self._archive_path(ticker)
        ids: set = set()
        if not path.exists():
            return ids
        try:
            with path.open("r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                        eid = rec.get("entry_id")
                        if eid:
                            ids.add(eid)
                    except Exception:
                        pass  # corrupt line — skip
        except Exception as exc:
            logger.warning(
                "JsonFileTimelineStore: error reading archive for %s: %s", ticker, exc
            )
        return ids

    def _append_archive(
        self, ticker: str, records: List[Dict[str, Any]], archived_at: Optional[str] = None
    ) -> int:
        """Append *records* to the JSONL archive file.

        Each line gains an ``archived_at`` field.  Returns the number of
        lines actually written.
        """
        if not records:
            return 0
        self._ensure_archive_dir()
        path = self._archive_path(ticker)
        ts = archived_at or self._now_iso()
        written = 0
        try:
            with path.open("a", encoding="utf-8") as fh:
                for rec in records:
                    r = dict(rec)
                    r["archived_at"] = ts
                    fh.write(json.dumps(r, default=str) + "\n")
                    written += 1
        except Exception as exc:
            logger.warning(
                "JsonFileTimelineStore: archive append failed for %s: %s", ticker, exc
            )
        return written

    # ------------------------------------------------------------------
    # Inline cap enforcement (called from save)
    # ------------------------------------------------------------------

    def _apply_cap(
        self, ticker: str, records: List[Dict[str, Any]], cap: int = LIVE_CAP
    ) -> List[Dict[str, Any]]:
        """Enforce *cap* per entry_type on *records*.

        Overflow entries (oldest beyond cap) are immediately archived.
        Returns the trimmed list for writing to the live file.

        This is called inline from save() so the live file never grows past
        cap + 1 before being trimmed.  It does NOT dedup against the archive
        — crash-recovery idempotency is the responsibility of archive_old_entries().
        """
        # Fast path: no entry_type exceeds cap
        by_type: Dict[str, int] = {}
        for rec in records:
            et = rec.get("entry_type", "")
            by_type[et] = by_type.get(et, 0) + 1
        if all(count <= cap for count in by_type.values()):
            return records

        # Slow path: group, sort, split
        by_type_lists: Dict[str, List[Dict]] = {}
        for rec in records:
            et = rec.get("entry_type", "")
            by_type_lists.setdefault(et, []).append(rec)

        to_keep: List[Dict] = []
        to_archive: List[Dict] = []

        for et, recs in by_type_lists.items():
            recs.sort(key=lambda r: r.get("timestamp", ""))
            if len(recs) <= cap:
                to_keep.extend(recs)
            else:
                to_archive.extend(recs[:-cap])
                to_keep.extend(recs[-cap:])

        if to_archive:
            self._append_archive(ticker, to_archive)
            logger.info(
                "JsonFileTimelineStore: archived %d entries for %s (live cap=%d)",
                len(to_archive), ticker, cap,
            )

        to_keep.sort(key=lambda r: r.get("timestamp", ""))
        return to_keep

    # ------------------------------------------------------------------
    # Public bulk archival (idempotent)
    # ------------------------------------------------------------------

    def archive_old_entries(self, ticker: str, cap: int = LIVE_CAP) -> int:
        """Archive entries beyond *cap* per entry_type for *ticker*.

        Idempotent: reads existing entry_ids from the JSONL archive before
        appending — entries already archived are never duplicated.

        Returns the number of entries newly archived (0 if nothing to do).

        Use this for one-time migration of large existing live files, or as
        a scheduled maintenance task.
        """
        records = self._read_raw(ticker)
        if not records:
            return 0

        by_type_lists: Dict[str, List[Dict]] = {}
        for rec in records:
            et = rec.get("entry_type", "")
            by_type_lists.setdefault(et, []).append(rec)

        to_keep: List[Dict] = []
        candidates: List[Dict] = []

        for et, recs in by_type_lists.items():
            recs.sort(key=lambda r: r.get("timestamp", ""))
            if len(recs) <= cap:
                to_keep.extend(recs)
            else:
                candidates.extend(recs[:-cap])
                to_keep.extend(recs[-cap:])

        if not candidates:
            return 0

        # Dedup: skip entries already in archive
        existing_ids = self._read_archived_entry_ids(ticker)
        new_records = [r for r in candidates if r.get("entry_id") not in existing_ids]

        written = self._append_archive(ticker, new_records)

        if written > 0 or candidates:
            to_keep.sort(key=lambda r: r.get("timestamp", ""))
            self._write_raw(ticker, to_keep)
            logger.info(
                "JsonFileTimelineStore.archive_old_entries: %s — "
                "archived=%d already_archived=%d live=%d",
                ticker, written, len(candidates) - written, len(to_keep),
            )

        return written

    # ------------------------------------------------------------------
    # Archive read (optional / paginated)
    # ------------------------------------------------------------------

    def load_archive(
        self,
        ticker: str,
        entry_type: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> List[TimelineEntry]:
        """Read entries from the JSONL archive.

        Corrupt lines are silently skipped — they never break reads.
        Returns entries in archive order (append / oldest-archived first).
        Optionally filtered by *entry_type*; optionally limited.
        """
        path = self._archive_path(ticker)
        if not path.exists():
            return []
        results: List[TimelineEntry] = []
        try:
            with path.open("r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                        # Strip the extra archived_at field before validating
                        entry = TimelineEntry.model_validate(
                            {k: v for k, v in rec.items() if k != "archived_at"}
                        )
                        if entry_type is None or entry.entry_type == entry_type:
                            results.append(entry)
                            if limit is not None and len(results) >= limit:
                                break
                    except Exception:
                        pass  # corrupt line — skip silently
        except Exception as exc:
            logger.warning(
                "JsonFileTimelineStore.load_archive failed for %s: %s", ticker, exc
            )
        return results

    # ------------------------------------------------------------------
    # TimelineStore interface
    # ------------------------------------------------------------------

    def save(self, entry: TimelineEntry) -> str:
        """Append *entry* to the ticker file; archive overflow per entry_type."""
        try:
            if not entry.timestamp:
                entry = entry.model_copy(update={"timestamp": self._now_iso()})

            records = self._read_raw(entry.ticker)
            records.append(entry.model_dump())
            records = self._apply_cap(entry.ticker, records)
            self._write_raw(entry.ticker, records)
            return entry.entry_id
        except Exception as exc:
            logger.warning("JsonFileTimelineStore.save failed: %s", exc)
            return entry.entry_id

    def load(
        self,
        ticker: str,
        entry_type: Optional[str] = None,
    ) -> List[TimelineEntry]:
        """Load entries for *ticker* from the live file, sorted ascending by timestamp."""
        try:
            records = self._read_raw(ticker)
            entries: List[TimelineEntry] = []
            for rec in records:
                try:
                    entries.append(TimelineEntry.model_validate(rec))
                except Exception as parse_exc:
                    logger.warning(
                        "JsonFileTimelineStore: skipping malformed entry: %s",
                        parse_exc,
                    )

            if entry_type is not None:
                entries = [e for e in entries if e.entry_type == entry_type]

            entries.sort(key=lambda e: e.timestamp)
            return entries
        except Exception as exc:
            logger.warning("JsonFileTimelineStore.load failed: %s", exc)
            return []

    def latest(
        self,
        ticker: str,
        entry_type: Optional[str] = None,
    ) -> Optional[TimelineEntry]:
        """Return the most recent entry, optionally filtered by *entry_type*."""
        try:
            entries = self.load(ticker, entry_type=entry_type)
            if not entries:
                return None
            return entries[-1]
        except Exception as exc:
            logger.warning("JsonFileTimelineStore.latest failed: %s", exc)
            return None

    def all_tickers(self) -> List[str]:
        """Return tickers with stored data in the live directory (filenames without .json)."""
        try:
            return sorted(
                p.stem for p in self._data_dir.glob("*.json") if p.is_file()
            )
        except Exception as exc:
            logger.warning("JsonFileTimelineStore.all_tickers failed: %s", exc)
            return []


# ---------------------------------------------------------------------------
# Module-level default instance
# ---------------------------------------------------------------------------

default_store: JsonFileTimelineStore = JsonFileTimelineStore()
