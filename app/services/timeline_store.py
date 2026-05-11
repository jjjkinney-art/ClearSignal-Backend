"""
Timeline persistence store.

Stores timestamped snapshots of investment analyses, theses, and evidence
so callers can track how a thesis evolves over time.  The abstract base
class (TimelineStore) defines the interface; JsonFileTimelineStore is the
default implementation that writes one JSON file per ticker under a
configurable data directory.

Swapping to a database backend requires only a new subclass — the public
API (save / load / latest / all_tickers) stays identical.

Usage
-----
    from app.services.timeline_store import JsonFileTimelineStore
    store = JsonFileTimelineStore()                 # default: .clearSignal_timeline/
    store = JsonFileTimelineStore("/tmp/tl")        # custom directory

    entry_id = store.save(TimelineEntry(
        ticker="AAPL",
        entry_type="thesis",
        data={"bull_thesis": "...", "bear_thesis": "..."},
    ))

    entries = store.load("AAPL")
    latest  = store.latest("AAPL")
    tickers = store.all_tickers()
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

    The directory is created on first use.  Each file is named
    ``{TICKER}.json`` and contains a JSON array of serialised
    TimelineEntry objects.

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
    # Helpers
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
    # TimelineStore interface
    # ------------------------------------------------------------------

    def save(self, entry: TimelineEntry) -> str:
        """Append *entry* to the ticker file, auto-stamping timestamp if empty."""
        try:
            if not entry.timestamp:
                entry = entry.model_copy(update={"timestamp": self._now_iso()})

            records = self._read_raw(entry.ticker)
            records.append(entry.model_dump())
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
        """Load entries for *ticker*, sorted ascending by timestamp."""
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
        """Return tickers with stored data (filenames without .json suffix)."""
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
