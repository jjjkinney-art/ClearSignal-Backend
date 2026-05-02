"""
Historical data operations layer.

Provides typed, reusable query methods over the raw storage layer.
All history access should go through this module — not via raw
``query_records`` calls scattered across services.

Capabilities
------------
- Typed return wrappers (HistoryWindow) per domain
- Recent-window and comparison-window queries
- Efficient per-ticker filtering
- Archival / retention hooks (stub for future GC)
- In-process query cache integration

Usage::

    ops     = history_ops   # default singleton
    prices  = ops.price_window("AAPL", days=30)
    signals = ops.signal_window(days=7)
    events  = ops.event_window("AAPL", event_type="earnings", days=90)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ── HistoryWindow ─────────────────────────────────────────────────────────

@dataclass
class HistoryWindow:
    """A typed slice of historical records for a domain.

    Attributes
    ----------
    domain      : "price" | "financial" | "event" | "signal"
    ticker      : ticker symbol or empty if multi-company
    records     : list of raw record dicts
    start_ts    : window start datetime (UTC)
    end_ts      : window end datetime (UTC)
    record_count: number of records in window
    has_data    : whether any records were found
    notes       : any metadata about the window
    """
    domain:       str
    ticker:       str = ""
    records:      List[Dict[str, Any]] = field(default_factory=list)
    start_ts:     Optional[datetime] = None
    end_ts:       Optional[datetime] = None
    record_count: int = 0
    has_data:     bool = False
    notes:        str = ""

    def __post_init__(self) -> None:
        self.record_count = len(self.records)
        self.has_data     = self.record_count > 0

    def values(self, field_name: str) -> List[float]:
        """Extract float values for a named field from all records."""
        out: List[float] = []
        for rec in self.records:
            v = rec.get(field_name)
            if v is not None:
                try:
                    out.append(float(v))
                except (TypeError, ValueError):
                    pass
        return out

    def timestamps(self) -> List[datetime]:
        """Extract and parse timestamps from records."""
        out: List[datetime] = []
        for rec in self.records:
            ts = rec.get("timestamp") or rec.get("ts") or rec.get("time")
            if ts:
                try:
                    dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    out.append(dt)
                except Exception:
                    pass
        return out

    def filter_by_type(self, event_type: str) -> "HistoryWindow":
        """Return a new window containing only records matching event_type."""
        filtered = [r for r in self.records if r.get("event_type") == event_type]
        return HistoryWindow(
            domain=self.domain, ticker=self.ticker,
            records=filtered, start_ts=self.start_ts, end_ts=self.end_ts,
        )


# ── HistoryOps ────────────────────────────────────────────────────────────

class HistoryOps:
    """Typed query interface over the storage layer.

    All methods return HistoryWindow objects rather than raw dicts.
    Queries are filtered by time window when timestamps are available.
    """

    def __init__(self, db_path: Optional[str] = None) -> None:
        self._db_path = db_path

    def _query(self, table: str, limit: int = 200) -> List[Dict[str, Any]]:
        try:
            from ..data_pipeline.storage import query_records  # type: ignore
            return query_records(table, limit=limit, db_path=self._db_path)
        except Exception as exc:
            logger.warning(f"HistoryOps._query({table}): {exc}")
            return []

    def fallback_query(self, table: str, limit: int = 200) -> List[Dict[str, Any]]:
        """Single authorized direct-storage access point for services.

        When history_ops' typed window methods are unavailable (e.g. enterprise
        layer misconfigured), services may call this method instead of
        importing ``query_records`` directly.  This keeps the storage-access
        surface isolated to one module.

        Services should prefer ``price_window``, ``financial_window``,
        ``event_window``, and ``signal_window``.  ``fallback_query`` is a
        last-resort escape hatch with the same return shape.
        """
        return self._query(table=table, limit=limit)

    def _filter_by_window(
        self, records: List[Dict[str, Any]], days: Optional[int]
    ) -> List[Dict[str, Any]]:
        if not days or not records:
            return records
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        out: List[Dict[str, Any]] = []
        for rec in records:
            ts = rec.get("timestamp") or rec.get("ts") or rec.get("time")
            if not ts:
                out.append(rec)   # include records without timestamps
                continue
            try:
                dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                if dt >= cutoff:
                    out.append(rec)
            except Exception:
                out.append(rec)
        return out

    def _filter_by_ticker(
        self, records: List[Dict[str, Any]], ticker: str
    ) -> List[Dict[str, Any]]:
        if not ticker:
            return records
        # Include records that either match the ticker exactly OR have no ticker
        # field set (global/unkeyed records that apply to all tickers).
        return [
            r for r in records
            if not r.get("ticker") or r.get("ticker", "").upper() == ticker.upper()
        ]

    def _make_window(
        self,
        domain: str,
        records: List[Dict[str, Any]],
        ticker: str = "",
        days: Optional[int] = None,
    ) -> HistoryWindow:
        end   = datetime.now(timezone.utc)
        start = end - timedelta(days=days) if days else None
        return HistoryWindow(
            domain=domain, ticker=ticker, records=records,
            start_ts=start, end_ts=end,
        )

    # ── Domain query methods ──────────────────────────────────────────────

    def price_window(
        self, ticker: str = "", days: Optional[int] = None, limit: int = 200
    ) -> HistoryWindow:
        """Retrieve price history, optionally filtered by ticker and time window."""
        records = self._query("price_history", limit=limit)
        records = self._filter_by_ticker(records, ticker)
        records = self._filter_by_window(records, days)
        return self._make_window("price", records, ticker, days)

    def financial_window(
        self,
        ticker: str = "",
        metric_name: Optional[str] = None,
        days: Optional[int] = None,
        limit: int = 200,
    ) -> HistoryWindow:
        """Retrieve financial history, optionally filtered by ticker and metric."""
        records = self._query("financial_history", limit=limit)
        records = self._filter_by_ticker(records, ticker)
        if metric_name:
            records = [r for r in records if r.get("metric_name") == metric_name]
        records = self._filter_by_window(records, days)
        return self._make_window("financial", records, ticker, days)

    def event_window(
        self,
        ticker: str = "",
        event_type: Optional[str] = None,
        days: Optional[int] = None,
        limit: int = 200,
    ) -> HistoryWindow:
        """Retrieve event history, optionally filtered by type."""
        records = self._query("event_history", limit=limit)
        records = self._filter_by_ticker(records, ticker)
        if event_type:
            records = [r for r in records if r.get("event_type") == event_type]
        records = self._filter_by_window(records, days)
        return self._make_window("event", records, ticker, days)

    def signal_window(
        self, days: Optional[int] = None, limit: int = 200
    ) -> HistoryWindow:
        """Retrieve signal history (signals are not per-ticker)."""
        records = self._query("signal_history", limit=limit)
        records = self._filter_by_window(records, days)
        return self._make_window("signal", records, days=days)

    def comparison_windows(
        self,
        domain: str,
        ticker: str = "",
        total_days: int = 60,
        limit: int = 200,
    ) -> tuple[HistoryWindow, HistoryWindow]:
        """Return two equal-length consecutive windows for comparison.

        Returns (older_window, recent_window).  Useful for detecting
        trend changes by comparing activity across two periods.
        """
        half = total_days // 2
        # recent half
        recent_records = self._query(f"{domain}_history", limit=limit)
        recent_records = self._filter_by_ticker(recent_records, ticker)
        recent_records = self._filter_by_window(recent_records, half)
        # older half (between total_days and half days ago)
        all_records    = self._query(f"{domain}_history", limit=limit)
        all_records    = self._filter_by_ticker(all_records, ticker)
        all_in_total   = self._filter_by_window(all_records, total_days)
        recent_ids     = {id(r) for r in recent_records}
        older_records  = [r for r in all_in_total if id(r) not in recent_ids]

        end_ts      = datetime.now(timezone.utc)
        recent_w = HistoryWindow(
            domain=domain, ticker=ticker, records=recent_records,
            start_ts=end_ts - timedelta(days=half), end_ts=end_ts,
        )
        older_w = HistoryWindow(
            domain=domain, ticker=ticker, records=older_records,
            start_ts=end_ts - timedelta(days=total_days),
            end_ts=end_ts - timedelta(days=half),
        )
        return older_w, recent_w

    # ── Retention / archival hooks ────────────────────────────────────────

    def retention_summary(self) -> Dict[str, int]:
        """Return record counts per domain for retention monitoring."""
        summary: Dict[str, int] = {}
        for domain in ("price", "financial", "event", "signal"):
            table = f"{domain}_history"
            records = self._query(table, limit=10_000)
            summary[domain] = len(records)
        return summary

    def archive_before(self, domain: str, cutoff_days: int) -> int:
        """Stub: mark records older than cutoff_days for archival.

        Returns count of records that would be archived.
        In a production system this would move records to cold storage.
        """
        table   = f"{domain}_history"
        records = self._query(table, limit=10_000)
        cutoff  = datetime.now(timezone.utc) - timedelta(days=cutoff_days)
        count   = 0
        for rec in records:
            ts = rec.get("timestamp") or rec.get("ts")
            if ts:
                try:
                    dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    if dt < cutoff:
                        count += 1
                except Exception:
                    pass
        logger.info(f"archive_before: {count} records in {domain} older than {cutoff_days} days")
        return count

    # ── Semantic history methods (services must use THESE, not fallback_query) ──
    #
    # These methods return domain-specific summaries suitable for monitoring,
    # alerts, and learning.  They encapsulate the legacy storage/fallback paths
    # so services never need to reach into raw storage.

    def get_signal_history_summary(
        self, days: Optional[int] = None, limit: int = 500,
    ) -> Dict[str, Any]:
        """Summarised signal history for learning/monitoring consumption.

        Returns a dict with:
            records          : raw records (for downstream aggregation)
            count            : number of records
            weighted_scores  : list of float scores (if present)
            baseline_avg     : mean of weighted_scores (or None)
        """
        window  = self.signal_window(days=days, limit=limit)
        scores  = [
            float(r["weighted_score"]) for r in window.records
            if r.get("weighted_score") is not None
        ]
        return {
            "records":         window.records,
            "count":           window.record_count,
            "weighted_scores": scores,
            "baseline_avg":    (sum(scores) / len(scores)) if scores else None,
        }

    def get_event_history_summary(
        self,
        ticker: str = "",
        event_type: Optional[str] = None,
        days: Optional[int] = None,
        limit: int = 200,
    ) -> Dict[str, Any]:
        """Summarised event history: counts by type plus raw records."""
        window = self.event_window(
            ticker=ticker, event_type=event_type, days=days, limit=limit,
        )
        type_counts: Dict[str, int] = {}
        for rec in window.records:
            et = rec.get("event_type")
            if et:
                type_counts[et] = type_counts.get(et, 0) + 1
        return {
            "records":     window.records,
            "count":       window.record_count,
            "type_counts": type_counts,
        }

    def get_price_history_summary(
        self, ticker: str = "", days: Optional[int] = None, limit: int = 200,
    ) -> Dict[str, Any]:
        """Summarised price history: records plus price-value list."""
        window = self.price_window(ticker=ticker, days=days, limit=limit)
        return {
            "records": window.records,
            "count":   window.record_count,
            "prices":  window.values("price"),
        }

    def get_financial_history_summary(
        self,
        ticker: str = "",
        metric_name: Optional[str] = None,
        days: Optional[int] = None,
        limit: int = 200,
    ) -> Dict[str, Any]:
        """Summarised financial history keyed by metric."""
        window = self.financial_window(
            ticker=ticker, metric_name=metric_name, days=days, limit=limit,
        )
        by_metric: Dict[str, list] = {}
        for rec in window.records:
            name = rec.get("metric_name")
            val  = rec.get("value")
            if name is not None and val is not None:
                try:
                    by_metric.setdefault(name, []).append(float(val))
                except (TypeError, ValueError):
                    pass
        return {
            "records":   window.records,
            "count":     window.record_count,
            "by_metric": by_metric,
        }

    def get_signal_outcome_profile(self, signal: str) -> Dict[str, Any]:
        """Find how often a given signal appears in history.

        This is the learning-layer semantic method: returns observation
        count for a named signal string, suitable for signal-weight computation.
        """
        key = signal.strip().lower()
        summary = self.get_signal_history_summary(limit=500)
        count = sum(
            1 for r in summary["records"]
            if (r.get("signal") or "").strip().lower() == key
        )
        return {
            "signal":            signal,
            "observation_count": count,
        }

    def get_monitoring_history_context(
        self, days: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Combined signal + event history summary for monitoring decisions."""
        return {
            "signals": self.get_signal_history_summary(days=days, limit=100),
            "events":  self.get_event_history_summary(days=days, limit=200),
        }

    def get_alert_pattern_history(
        self,
        component_keyword: str,
        days: int = 30,
    ) -> Dict[str, Any]:
        """Pattern summary for an alert component — days-window signal matches.

        The alert layer uses this to count how many signals in the window
        mention the given component keyword.
        """
        from datetime import datetime as _dt
        summary = self.get_signal_history_summary(limit=200)
        kw = component_keyword.lower()
        now = datetime.now(timezone.utc)
        recent_count = 0
        for rec in summary["records"]:
            if kw in (rec.get("signal") or "").lower():
                ts = rec.get("timestamp")
                if ts:
                    try:
                        dt = _dt.fromisoformat(str(ts).replace("Z", "+00:00"))
                        if dt.tzinfo is None:
                            dt = dt.replace(tzinfo=timezone.utc)
                        if (now - dt).days <= days:
                            recent_count += 1
                    except Exception:
                        pass
        return {
            "component_keyword":   component_keyword,
            "days_window":         days,
            "recent_signal_count": recent_count,
        }


# ── Default singleton ─────────────────────────────────────────────────────

history_ops = HistoryOps()
