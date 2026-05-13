"""
Watchlist service — persistent ticker tracking with thesis snapshot history.

Architecture
------------
* Ticker index  : JSON file at ``{data_dir}/index.json``.
                  Contains a dict of {TICKER: WatchlistEntry} records.
* Snapshot store: reuses ``JsonFileTimelineStore`` (entry_type="thesis_snapshot").
* Change log    : reuses ``JsonFileTimelineStore`` (entry_type="material_change").

All public functions are safe to call when no data exists (they return
empty lists / None / False rather than raising).  The service never
calls the language model; all intelligence comes from
``thesis_memory_service`` which is called before saving here.

Primary integration point
-------------------------
    from app.services.watchlist_service import watchlist_service
    from app.services.thesis_memory_service import snapshot_from_thesis

    # After generating a new InvestmentThesis:
    event = watchlist_service.process_new_thesis(thesis)
    # event is a MaterialChangeEvent if something material happened, else None.

Ticker management
-----------------
    watchlist_service.add_ticker("AAPL", "Apple Inc.")
    watchlist_service.remove_ticker("AAPL")
    entries = watchlist_service.get_watchlist()
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from ..schemas import (
    InvestmentThesis,
    MaterialChangeEvent,
    ThesisDiff,
    ThesisSnapshot,
    WatchlistEntry,
)
from .thesis_memory_service import (
    compare_thesis_snapshots,
    detect_material_change,
    snapshot_from_thesis,
)
from .timeline_store import JsonFileTimelineStore, TimelineEntry

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Storage constants
# ---------------------------------------------------------------------------

_DEFAULT_DATA_DIR = ".clearSignal_watchlist"
_INDEX_FILE       = "index.json"
_TIMELINE_DIR     = ".clearSignal_timeline"   # reuse existing timeline store dir


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ticker_upper(ticker: str) -> str:
    return ticker.strip().upper()


# ---------------------------------------------------------------------------
# WatchlistService
# ---------------------------------------------------------------------------

class WatchlistService:
    """Persistent watchlist with snapshot history and material change tracking.

    Thread-safety
    -------------
    Single-process use only (JSON file I/O, no file locking).  Suitable for
    development and single-worker deployments.  The API wraps each operation
    individually; callers should not rely on atomicity across operations.
    """

    def __init__(
        self,
        data_dir:     str = _DEFAULT_DATA_DIR,
        timeline_dir: str = _TIMELINE_DIR,
    ) -> None:
        self._data_dir = Path(data_dir)
        self._index_path = self._data_dir / _INDEX_FILE

        # Snapshot store (entry_type="thesis_snapshot" per ticker)
        self._snapshot_store = JsonFileTimelineStore(timeline_dir)

        # Material-change log (entry_type="material_change")
        # Stored under a synthetic "watchlist_events" ticker key
        self._change_store   = JsonFileTimelineStore(timeline_dir)

        try:
            self._data_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            logger.warning("WatchlistService: could not create data dir: %s", exc)

    # ------------------------------------------------------------------
    # Index I/O helpers
    # ------------------------------------------------------------------

    def _load_index(self) -> Dict[str, dict]:
        """Load the watchlist index from disk.  Returns {} on failure."""
        try:
            if not self._index_path.exists():
                return {}
            raw = self._index_path.read_text(encoding="utf-8")
            data = json.loads(raw)
            if isinstance(data, dict):
                return data
        except Exception as exc:
            logger.warning("WatchlistService._load_index failed: %s", exc)
        return {}

    def _save_index(self, index: Dict[str, dict]) -> None:
        """Persist the watchlist index to disk."""
        try:
            self._index_path.write_text(
                json.dumps(index, indent=2, default=str),
                encoding="utf-8",
            )
        except Exception as exc:
            logger.warning("WatchlistService._save_index failed: %s", exc)

    def _entry_to_dict(self, entry: WatchlistEntry) -> dict:
        return entry.model_dump()

    def _entry_from_dict(self, data: dict) -> Optional[WatchlistEntry]:
        try:
            return WatchlistEntry.model_validate(data)
        except Exception as exc:
            logger.warning("WatchlistService: bad entry record: %s", exc)
            return None

    # ------------------------------------------------------------------
    # Ticker management (Phase 1)
    # ------------------------------------------------------------------

    def add_ticker(
        self,
        ticker:       str,
        company_name: str = "",
    ) -> WatchlistEntry:
        """Add a ticker to the watchlist.

        Idempotent: if the ticker is already tracked, returns the existing
        entry unchanged.
        """
        t = _ticker_upper(ticker)
        index = self._load_index()

        if t in index:
            existing = self._entry_from_dict(index[t])
            return existing or WatchlistEntry(ticker=t, company_name=company_name, added_at=_now_iso())

        entry = WatchlistEntry(
            ticker       = t,
            company_name = company_name or t,
            added_at     = _now_iso(),
        )
        index[t] = self._entry_to_dict(entry)
        self._save_index(index)
        logger.info("WatchlistService: added %s", t)
        return entry

    def remove_ticker(self, ticker: str) -> bool:
        """Remove a ticker from the watchlist.

        Returns True if the ticker was present and removed, False if it
        was not found.  Does NOT delete snapshot history.
        """
        t = _ticker_upper(ticker)
        index = self._load_index()
        if t not in index:
            return False
        del index[t]
        self._save_index(index)
        logger.info("WatchlistService: removed %s", t)
        return True

    def is_tracked(self, ticker: str) -> bool:
        """Return True when the ticker is currently in the watchlist."""
        t = _ticker_upper(ticker)
        return t in self._load_index()

    # ------------------------------------------------------------------
    # Watchlist retrieval
    # ------------------------------------------------------------------

    def get_watchlist(self) -> List[WatchlistEntry]:
        """Return all watchlist entries sorted by added_at descending."""
        index = self._load_index()
        entries = []
        for data in index.values():
            e = self._entry_from_dict(data)
            if e:
                entries.append(e)
        entries.sort(key=lambda e: e.added_at or "", reverse=True)
        return entries

    def get_entry(self, ticker: str) -> Optional[WatchlistEntry]:
        """Return the watchlist entry for a ticker, or None."""
        t = _ticker_upper(ticker)
        index = self._load_index()
        data  = index.get(t)
        if data is None:
            return None
        return self._entry_from_dict(data)

    # ------------------------------------------------------------------
    # Snapshot persistence (Phase 1)
    # ------------------------------------------------------------------

    def save_snapshot(self, snapshot: ThesisSnapshot) -> str:
        """Persist a ThesisSnapshot and update the watchlist entry metadata.

        Returns the snapshot_id.
        """
        t = _ticker_upper(snapshot.ticker)

        # Persist via timeline store
        entry = TimelineEntry(
            ticker     = t,
            entry_type = "thesis_snapshot",
            timestamp  = snapshot.timestamp or _now_iso(),
            data       = snapshot.model_dump(),
            metadata   = {"snapshot_id": snapshot.snapshot_id},
        )
        self._snapshot_store.save(entry)

        # Update index entry
        index = self._load_index()
        if t not in index:
            index[t] = self._entry_to_dict(
                WatchlistEntry(ticker=t, company_name=snapshot.company_name, added_at=_now_iso())
            )

        rec = index[t]
        rec["last_updated"]          = snapshot.timestamp or _now_iso()
        rec["snapshot_count"]        = rec.get("snapshot_count", 0) + 1
        rec["latest_thesis_trend"]   = snapshot.thesis_trend or "unclear"
        rec["latest_confidence"]     = snapshot.confidence_score
        rec["latest_one_sentence"]   = snapshot.one_sentence_thesis or ""
        rec["company_name"]          = snapshot.company_name or rec.get("company_name", t)

        # Dominant signal / risk — use Signal.signal (canonical text field)
        if snapshot.top_signals:
            sig = snapshot.top_signals[0]
            rec["dominant_signal"] = (
                getattr(sig, "signal", "")
                or getattr(sig, "label", "")
                or getattr(sig, "description", "")
                or ""
            )[:80]
        if snapshot.top_risks:
            rsk = snapshot.top_risks[0]
            rec["dominant_risk"] = (
                getattr(rsk, "signal", "")
                or getattr(rsk, "label", "")
                or getattr(rsk, "description", "")
                or ""
            )[:80]

        index[t] = rec
        self._save_index(index)
        return snapshot.snapshot_id

    def get_snapshots(
        self,
        ticker: str,
        limit:  int = 50,
    ) -> List[ThesisSnapshot]:
        """Return snapshot history for a ticker, sorted newest-first."""
        t = _ticker_upper(ticker)
        raw_entries = self._snapshot_store.load(t, entry_type="thesis_snapshot")

        snapshots: List[ThesisSnapshot] = []
        for entry in raw_entries:
            try:
                snap = ThesisSnapshot.model_validate(entry.data)
                snapshots.append(snap)
            except Exception as exc:
                logger.warning("WatchlistService.get_snapshots: bad snapshot: %s", exc)

        # Newest first
        snapshots.sort(key=lambda s: s.timestamp or "", reverse=True)
        return snapshots[:limit]

    def get_latest_snapshot(self, ticker: str) -> Optional[ThesisSnapshot]:
        """Return the most recent snapshot for a ticker, or None."""
        snaps = self.get_snapshots(ticker, limit=1)
        return snaps[0] if snaps else None

    def get_previous_snapshot(self, ticker: str) -> Optional[ThesisSnapshot]:
        """Return the second-most-recent snapshot for a ticker, or None."""
        snaps = self.get_snapshots(ticker, limit=2)
        return snaps[1] if len(snaps) >= 2 else None

    # ------------------------------------------------------------------
    # Material change log
    # ------------------------------------------------------------------

    def save_material_change(self, event: MaterialChangeEvent) -> str:
        """Persist a MaterialChangeEvent and flag the watchlist entry.

        Returns the event_id.
        """
        entry = TimelineEntry(
            ticker     = event.ticker.upper(),
            entry_type = "material_change",
            timestamp  = event.timestamp,
            data       = event.model_dump(),
            metadata   = {
                "event_id":    event.event_id,
                "severity":    event.severity,
                "change_type": event.change_type,
            },
        )
        self._change_store.save(entry)

        # Flag the watchlist entry
        index = self._load_index()
        t = event.ticker.upper()
        if t in index:
            index[t]["has_material_change"] = True
            self._save_index(index)

        return event.event_id

    def get_material_changes(
        self,
        ticker: Optional[str] = None,
        limit:  int = 100,
    ) -> List[MaterialChangeEvent]:
        """Return material change events, optionally filtered by ticker.

        Results are sorted newest-first.
        """
        events: List[MaterialChangeEvent] = []

        if ticker is not None:
            # Load for specific ticker
            tickers_to_check = [_ticker_upper(ticker)]
        else:
            # Load for all watchlisted tickers
            tickers_to_check = list(self._load_index().keys())

        for t in tickers_to_check:
            raw_entries = self._change_store.load(t, entry_type="material_change")
            for entry in raw_entries:
                try:
                    ev = MaterialChangeEvent.model_validate(entry.data)
                    events.append(ev)
                except Exception as exc:
                    logger.warning("WatchlistService.get_material_changes: bad event: %s", exc)

        events.sort(key=lambda e: e.timestamp or "", reverse=True)
        return events[:limit]

    def clear_material_change_flag(self, ticker: str) -> None:
        """Clear the has_material_change flag after the user has reviewed."""
        t = _ticker_upper(ticker)
        index = self._load_index()
        if t in index:
            index[t]["has_material_change"] = False
            self._save_index(index)

    # ------------------------------------------------------------------
    # Primary integration point (Phase 5)
    # ------------------------------------------------------------------

    def process_new_thesis(
        self,
        thesis: InvestmentThesis,
    ) -> Optional[MaterialChangeEvent]:
        """Auto-add ticker, save snapshot, diff, emit MaterialChangeEvent if material.

        Call this immediately after generating a new InvestmentThesis.
        Returns a MaterialChangeEvent when a material change was detected,
        otherwise None.

        Side-effects:
            - Adds ticker to watchlist if not already tracked.
            - Saves snapshot to timeline store.
            - Saves MaterialChangeEvent to timeline store if material.
            - Updates watchlist entry metadata.
        """
        ticker = _ticker_upper(thesis.ticker)

        # Ensure ticker is tracked
        if not self.is_tracked(ticker):
            self.add_ticker(ticker, thesis.company_name or ticker)

        # Convert to snapshot
        current_snap = snapshot_from_thesis(thesis)

        # Load previous snapshot for diff
        previous_snap = self.get_latest_snapshot(ticker)

        # Save the new snapshot
        self.save_snapshot(current_snap)

        if previous_snap is None:
            # First snapshot — no diff possible
            logger.info("WatchlistService.process_new_thesis: first snapshot for %s", ticker)
            return None

        # Compute diff
        diff = compare_thesis_snapshots(previous_snap, current_snap)

        # Detect material change
        event = detect_material_change(diff, ticker, previous_snap, current_snap)
        if event is not None:
            self.save_material_change(event)
            logger.info(
                "WatchlistService: material change for %s — %s (%s)",
                ticker, event.change_type, event.severity,
            )

        return event

    # ------------------------------------------------------------------
    # Diff access (Phase 5 / Phase 8 timeline)
    # ------------------------------------------------------------------

    def get_latest_diff(self, ticker: str) -> Optional[ThesisDiff]:
        """Return the diff between the two most recent snapshots, or None."""
        snaps = self.get_snapshots(ticker, limit=2)
        if len(snaps) < 2:
            return None
        # snaps[0] = newest, snaps[1] = previous
        return compare_thesis_snapshots(snaps[1], snaps[0])


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

watchlist_service: WatchlistService = WatchlistService()
