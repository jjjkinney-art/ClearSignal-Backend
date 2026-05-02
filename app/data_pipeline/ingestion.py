"""
Data ingestion utilities.

This module defines functions to ingest raw data from external
providers (FMP, SEC, retrieval) and normalise it into structured
records defined in ``data_pipeline.schemas``.  Ingested records are
immediately persisted via the storage layer.  Functions are designed
to be idempotent and handle provider failures gracefully by
skipping failed sources without raising exceptions.

Phase 1 focuses on batch ingestion of historical data.  In later
phases, these functions may be invoked by streaming loops for
continuous updates.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Iterable, List

from ..providers import (
    get_market_snapshot,
    get_financial_context,
    get_recent_filings,
    get_public_context,
)
from ..services.event_categorization import categorize_events
from ..services.signal_scoring import score_signals
from .schemas import PriceRecord, FinancialRecord, EventRecord, SignalRecord
from .storage import (
    insert_price_records,
    insert_financial_records,
    insert_event_records,
    insert_signal_records,
)
from ..config import settings

logger = logging.getLogger(__name__)


def ingest_price_history(symbol: str) -> None:
    """Ingest the current price snapshot as a historical record.

    Parameters
    ----------
    symbol : str
        Ticker symbol to ingest price history for.
    """
    api_key = getattr(settings, "fmp_api_key", "")
    try:
        snapshot = get_market_snapshot(symbol, api_key=api_key)
        if snapshot and "price" in snapshot:
            # Use timezone‑aware timestamp to avoid deprecated utcnow and ensure consistent
            # handling across modules.  datetime.utcnow() returns a naive datetime and
            # issues a deprecation warning in Python 3.12+, so switch to
            # datetime.now(timezone.utc).
            record = PriceRecord(
                ticker=symbol,
                timestamp=datetime.now(timezone.utc),
                price=float(snapshot["price"]),
                volume=int(snapshot.get("volume", 0)) if snapshot.get("volume") is not None else None,
            )
            insert_price_records([record])
    except Exception as exc:
        logger.warning(f"Price ingestion failed for {symbol}: {exc}")


def ingest_financial_history(symbol: str) -> None:
    """Ingest basic financial metrics as historical records."""
    api_key = getattr(settings, "fmp_api_key", "")
    try:
        fin = get_financial_context(symbol, api_key=api_key)
        if fin:
            records: List[FinancialRecord] = []
            # Use timezone‑aware timestamps for financial history
            ts = datetime.now(timezone.utc)
            for k, v in fin.items():
                try:
                    value = float(v)
                except Exception:
                    continue
                records.append(FinancialRecord(ticker=symbol, timestamp=ts, metric_name=k, value=value))
            if records:
                insert_financial_records(records)
    except Exception as exc:
        logger.warning(f"Financial ingestion failed for {symbol}: {exc}")


def ingest_events(company: str, symbol: str) -> None:
    """Ingest recent events from SEC and public news sources."""
    # Recent filings
    user_agent = getattr(settings, "sec_user_agent", "ai-analyst-bot/0.1")
    events: List[EventRecord] = []
    # Use timezone‑aware timestamp for events
    now = datetime.now(timezone.utc)
    try:
        filings = get_recent_filings(company, ticker=symbol, user_agent=user_agent, count=5)
        for item in filings or []:
            description = f"{item.get('title', '')} on {item.get('filing_date', '')}"
            events.append(EventRecord(
                ticker=symbol,
                timestamp=now,
                event_type="filing",
                description=description,
                source="SEC",
            ))
    except Exception as exc:
        logger.warning(f"Filings ingestion failed for {symbol}: {exc}")
    # Public news
    try:
        news = get_public_context(symbol, limit=5)
        for headline in news or []:
            events.append(EventRecord(
                ticker=symbol,
                timestamp=now,
                event_type="news",
                description=headline,
                source="news",
            ))
    except Exception as exc:
        logger.warning(f"News ingestion failed for {symbol}: {exc}")
    # Categorise events and insert
    if events:
        # Optionally categorise events by type (earnings/regulatory/macro/product)
        # Here we simply assign the event_type based on categorisation for demonstration.
        types = categorize_events([ev.description for ev in events])
        for ev, cat in zip(events, types):
            ev.event_type = cat
        # Persist events to storage
        insert_event_records(events)
        # Process events through monitoring to update learning and signal history
        try:
            from ..services.monitoring_service import process_events
            process_events(events)
        except Exception:
            # Ignore monitoring errors; ingestion should not fail
            pass


def ingest_signals(signals: Iterable[str], timestamp: datetime | None = None) -> None:
    """Ingest a collection of intelligence signals with scoring.

    Parameters
    ----------
    signals : Iterable[str]
        Raw signal descriptions.
    timestamp : datetime, optional
        Timestamp to use for all signals; defaults to now.
    """
    # Use timezone‑aware timestamp for signal ingestion
    ts = timestamp or datetime.now(timezone.utc)
    # Score signals using existing scoring utilities
    scored = score_signals(list(signals))
    records: List[SignalRecord] = []
    for entry in scored:
        records.append(SignalRecord(
            timestamp=ts,
            signal=entry["signal"],
            importance_score=entry["importance_score"],
            impact_type=entry["impact_type"],
            time_horizon=entry["time_horizon"],
            confidence_score=entry["confidence_score"],
            weighted_score=entry["weighted_score"],
        ))
    if records:
        insert_signal_records(records)