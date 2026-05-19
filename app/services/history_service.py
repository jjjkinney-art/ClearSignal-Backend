"""
Analysis history service.

Aggregates stored ThesisSnapshot and MaterialChangeEvent records across all
tickers to produce a unified analysis history view. Used by the /history API
endpoint to let users revisit prior analyses.

All functions are safe to call when no data exists — they return empty lists
rather than raising.
"""
from __future__ import annotations

import logging
from typing import List, Optional
from pydantic import BaseModel, Field
import uuid

from .timeline_store import JsonFileTimelineStore, default_store

logger = logging.getLogger(__name__)


class HistoryEntry(BaseModel):
    """A single entry in the unified analysis history view."""
    entry_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    ticker: str
    company_name: str = Field(default="")
    timestamp: str
    entry_type: str   # "thesis_snapshot" | "material_change" | "alert"
    one_sentence_thesis: str = Field(default="")
    core_takeaway: str = Field(default="")
    dominant_driver: str = Field(default="")
    drift_state: str = Field(default="")
    confidence_score: float = Field(default=0.0)
    change_summary: str = Field(default="")  # what changed vs prior
    core_debate: str = Field(default="")
    # references
    snapshot_id: Optional[str] = Field(default=None)
    change_id: Optional[str] = Field(default=None)


def get_analysis_history(
    ticker: Optional[str] = None,
    limit: int = 100,
    entry_types: Optional[List[str]] = None,
) -> List[HistoryEntry]:
    """
    Return analysis history entries sorted by timestamp descending (most recent first).

    If ticker is None, returns history across all tracked tickers.
    entry_types filters by type (default: all types).
    """
    try:
        store = default_store

        if ticker is not None:
            tickers_to_check = [ticker.upper().strip()]
        else:
            try:
                tickers_to_check = store.all_tickers()
            except Exception as exc:
                logger.warning("history_service: all_tickers failed: %s", exc)
                tickers_to_check = []

        results: List[HistoryEntry] = []

        for t in tickers_to_check:
            try:
                entries = store.load(t, entry_type="thesis_snapshot")
                for entry in entries:
                    try:
                        data = entry.data or {}
                        he = HistoryEntry(
                            entry_id=entry.entry_id,
                            ticker=t,
                            company_name=data.get("company_name", ""),
                            timestamp=entry.timestamp or "",
                            entry_type="thesis_snapshot",
                            one_sentence_thesis=data.get("one_sentence_thesis", ""),
                            core_takeaway=data.get("core_takeaway", ""),
                            dominant_driver=data.get("dominant_driver", ""),
                            drift_state=data.get("drift_state", ""),
                            confidence_score=float(data.get("confidence_score", 0.0) or 0.0),
                            change_summary=data.get("what_changed_summary", ""),
                            core_debate=data.get("core_debate", ""),
                            snapshot_id=data.get("snapshot_id"),
                        )
                        if entry_types is None or he.entry_type in entry_types:
                            results.append(he)
                    except Exception as exc:
                        logger.warning("history_service: bad snapshot entry for %s: %s", t, exc)
            except Exception as exc:
                logger.warning("history_service: load failed for %s: %s", t, exc)

        results.sort(key=lambda e: e.timestamp, reverse=True)
        return results[:limit]

    except Exception as exc:
        logger.warning("get_analysis_history failed: %s", exc)
        return []


def get_recent_tickers(limit: int = 10) -> List[str]:
    """Return tickers with the most recent activity, sorted by last update time."""
    try:
        store = default_store
        tickers = store.all_tickers()

        ticker_latest: List[tuple] = []
        for t in tickers:
            try:
                latest = store.latest(t)
                ts = latest.timestamp if latest else ""
                ticker_latest.append((ts, t))
            except Exception:
                ticker_latest.append(("", t))

        ticker_latest.sort(key=lambda x: x[0], reverse=True)
        return [t for _, t in ticker_latest[:limit]]

    except Exception as exc:
        logger.warning("get_recent_tickers failed: %s", exc)
        return []


def get_ticker_history(ticker: str, limit: int = 20) -> List[HistoryEntry]:
    """Return full history for a single ticker."""
    try:
        return get_analysis_history(ticker=ticker, limit=limit)
    except Exception as exc:
        logger.warning("get_ticker_history failed for %s: %s", ticker, exc)
        return []


def get_history_summary() -> dict:
    """Return a summary: total tickers tracked, total analyses, date range."""
    try:
        store = default_store
        tickers = store.all_tickers()
        total_tickers = len(tickers)
        total_entries = 0
        oldest_ts = ""
        newest_ts = ""

        for t in tickers:
            try:
                entries = store.load(t)
                total_entries += len(entries)
                for e in entries:
                    ts = e.timestamp or ""
                    if ts:
                        if not oldest_ts or ts < oldest_ts:
                            oldest_ts = ts
                        if not newest_ts or ts > newest_ts:
                            newest_ts = ts
            except Exception:
                pass

        return {
            "total_tickers": total_tickers,
            "total_entries": total_entries,
            "oldest_timestamp": oldest_ts,
            "newest_timestamp": newest_ts,
            "tickers": tickers,
        }

    except Exception as exc:
        logger.warning("get_history_summary failed: %s", exc)
        return {
            "total_tickers": 0,
            "total_entries": 0,
            "oldest_timestamp": "",
            "newest_timestamp": "",
            "tickers": [],
        }
