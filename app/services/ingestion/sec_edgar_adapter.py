"""
SEC EDGAR Ingestion Adapter.

Fetches recent SEC filings from the public EDGAR REST API:
  https://data.sec.gov/submissions/CIK{padded}.json
  https://efts.sec.gov/LATEST/search-index?q=...&dateRange=custom&...

Supported filing types:
  10-K  — Annual report (high reliability, high materiality)
  10-Q  — Quarterly report
  8-K   — Material event disclosure (earnings, leadership changes, M&A)
  DEF14A — Proxy (governance)
  S-1   — IPO registration
  SC 13G / SC 13D — Large institutional ownership filings

Design:
- fetch_latest() uses the EDGAR full-text search API for recent 8-Ks
  (most market-moving), then optionally fetches by CIK for annual/quarterly.
- All HTTP calls wrapped with retry (3 attempts, exponential backoff).
- Returns empty list (never raises) on any network failure.
- Rate limit: EDGAR enforces 10 req/sec — we sleep between batches.
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import List, Optional
from urllib.request import Request, urlopen
from urllib.error import URLError
import json

from .base import EventIngestionAdapter
from .normalized_event import EventCategory, NormalizedEvent, SourceReliability

logger = logging.getLogger(__name__)

# EDGAR base URLs
_EDGAR_SEARCH_URL = (
    "https://efts.sec.gov/LATEST/search-index"
    "?q=%228-K%22&dateRange=custom&startdt={start}&enddt={end}"
    "&category=form-type&hits.hits._source=period_of_report,entity_name,"
    "file_date,form_type,accession_no"
)
_EDGAR_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"

_HEADERS = {"User-Agent": "ClearSignal research@clearsignal.io"}

# Filing type → materiality mapping
_FILING_MATERIALITY: dict[str, float] = {
    "8-K":    0.85,
    "10-K":   0.70,
    "10-Q":   0.60,
    "DEF14A": 0.30,
    "S-1":    0.50,
    "SC 13G": 0.40,
    "SC 13D": 0.55,
}

_HIGH_MATERIALITY_ITEMS = frozenset([
    "Item 2.02",  # Results of Operations (earnings)
    "Item 5.02",  # Director/Officer departure/appointment
    "Item 1.01",  # Material agreement
    "Item 8.01",  # Other events
])


def _fetch_with_retry(url: str, max_retries: int = 3, timeout: int = 8) -> Optional[dict]:
    """Synchronous GET with retry. Returns parsed JSON or None."""
    delay = 1.0
    for attempt in range(max_retries):
        try:
            req = Request(url, headers=_HEADERS)
            with urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except URLError as exc:
            logger.warning("EDGAR fetch attempt %d failed: %s", attempt + 1, exc)
            time.sleep(delay)
            delay *= 2.0
        except Exception as exc:
            logger.warning("EDGAR fetch unexpected error: %s", exc)
            return None
    return None


def _filing_category(form_type: str) -> EventCategory:
    if form_type in ("10-K", "10-Q"):
        return EventCategory.REGULATORY
    if form_type == "8-K":
        return EventCategory.EARNINGS  # 8-K can be earnings or regulatory; default to earnings
    return EventCategory.REGULATORY


def _parse_filing_to_event(filing: dict, form_type: str = "8-K") -> Optional[NormalizedEvent]:
    """Convert a raw EDGAR filing record to a NormalizedEvent."""
    try:
        entity_name = filing.get("entity_name", filing.get("entityName", "Unknown Entity"))
        ticker = filing.get("ticker", None)  # May not be in EDGAR response
        file_date = filing.get("file_date", filing.get("filedAt", ""))[:10]
        accession = filing.get("accession_no", filing.get("accessionNo", ""))

        headline = f"{entity_name} filed {form_type}"
        if accession:
            headline += f" (Accession: {accession[:20]})"

        # Derive timestamp from file_date
        event_ts = f"{file_date}T00:00:00+00:00" if file_date else datetime.now(timezone.utc).isoformat()
        ingestion_ts = datetime.now(timezone.utc).isoformat()

        materiality = _FILING_MATERIALITY.get(form_type, 0.4)
        is_market_moving = form_type in ("8-K", "10-K")

        tags = ["sec_filing"]
        if form_type == "8-K":
            tags.append("regulatory")
        if form_type in ("10-K",):
            tags.append("annual_report")

        return NormalizedEvent(
            ticker=ticker,
            category=_filing_category(form_type),
            headline=headline,
            body=f"SEC {form_type} filing by {entity_name}. Filed: {file_date}.",
            source="sec_edgar",
            source_reliability=SourceReliability.HIGH,
            event_timestamp=event_ts,
            ingestion_timestamp=ingestion_ts,
            raw_payload=filing,
            is_market_moving=is_market_moving,
            magnitude=materiality,
            tags=tags,
        )
    except Exception as exc:
        logger.warning("_parse_filing_to_event failed: %s", exc)
        return None


class SECEdgarAdapter(EventIngestionAdapter):
    """
    Ingestion adapter for SEC EDGAR public filings.

    In production, this adapter would call the live EDGAR API.
    For development/testing, it provides synthetic high-fidelity events
    that mirror real EDGAR filing patterns when the API is unavailable.
    """

    source_name = "sec_edgar"
    source_reliability = "high"

    def __init__(self, use_live_api: bool = False) -> None:
        """
        Parameters
        ----------
        use_live_api:
            Set True to call the live EDGAR API. Defaults to False
            (synthetic mode) so the system works without internet access.
        """
        self._use_live_api = use_live_api

    async def fetch_latest(
        self,
        tickers: Optional[List[str]] = None,
        since: Optional[str] = None,
    ) -> List[NormalizedEvent]:
        """Fetch recent SEC filings. Returns normalized events."""
        try:
            if self._use_live_api:
                return await self._fetch_live(tickers, since)
            else:
                return self._synthetic_events(tickers)
        except Exception as exc:
            logger.warning("SECEdgarAdapter.fetch_latest failed: %s", exc)
            return []

    async def health_check(self) -> bool:
        """Check EDGAR API reachability."""
        try:
            if not self._use_live_api:
                return True  # Synthetic mode always healthy
            result = _fetch_with_retry("https://data.sec.gov/submissions/CIK0000320193.json", timeout=5)
            return result is not None
        except Exception:
            return False

    # ── Live API path ──────────────────────────────────────────────────────

    async def _fetch_live(
        self,
        tickers: Optional[List[str]],
        since: Optional[str],
    ) -> List[NormalizedEvent]:
        """Call the real EDGAR API in a thread pool."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._fetch_live_sync, tickers, since)

    def _fetch_live_sync(
        self,
        tickers: Optional[List[str]],
        since: Optional[str],
    ) -> List[NormalizedEvent]:
        events: List[NormalizedEvent] = []
        # Respect EDGAR rate limit
        time.sleep(0.1)
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        start = since[:10] if since else today
        url = _EDGAR_SEARCH_URL.format(start=start, end=today)
        data = _fetch_with_retry(url)
        if not data:
            return []
        hits = data.get("hits", {}).get("hits", [])
        for hit in hits[:20]:
            src = hit.get("_source", {})
            form_type = src.get("form_type", "8-K")
            ev = _parse_filing_to_event(src, form_type)
            if ev:
                events.append(ev)
        return events

    # ── Synthetic events (dev/test mode) ──────────────────────────────────

    def _synthetic_events(self, tickers: Optional[List[str]]) -> List[NormalizedEvent]:
        """
        Generate realistic synthetic EDGAR filing events for development.

        Mirrors real filing patterns without requiring network access.
        Useful for testing the full pipeline end-to-end.
        """
        now = datetime.now(timezone.utc)
        today = now.strftime("%Y-%m-%d")
        ts = now.isoformat()

        filings = [
            {
                "entity_name": "Apple Inc.",
                "ticker": "AAPL",
                "form_type": "8-K",
                "date": today,
                "summary": "Apple Inc. filed Form 8-K disclosing Q1 2025 results.",
                "tags": ["beat", "sec_filing"],
            },
            {
                "entity_name": "Microsoft Corporation",
                "ticker": "MSFT",
                "form_type": "10-K",
                "date": today,
                "summary": "Microsoft annual report filing for fiscal year 2024.",
                "tags": ["sec_filing", "annual_report"],
            },
            {
                "entity_name": "NVIDIA Corporation",
                "ticker": "NVDA",
                "form_type": "8-K",
                "date": today,
                "summary": "NVIDIA filed 8-K disclosing material agreement for AI infrastructure.",
                "tags": ["announced", "sec_filing"],
            },
        ]

        events: List[NormalizedEvent] = []
        for f in filings:
            t = f["ticker"]
            if tickers and t.upper() not in [tk.upper() for tk in tickers]:
                continue
            events.append(
                NormalizedEvent(
                    ticker=t,
                    category=_filing_category(f["form_type"]),
                    headline=f"{f['entity_name']} filed {f['form_type']} — {f['date']}",
                    body=f["summary"],
                    source="sec_edgar_synthetic",
                    source_reliability=SourceReliability.HIGH,
                    event_timestamp=f"{f['date']}T00:00:00+00:00",
                    ingestion_timestamp=ts,
                    is_market_moving=f["form_type"] == "8-K",
                    magnitude=_FILING_MATERIALITY.get(f["form_type"], 0.5),
                    tags=list(f["tags"]),
                    raw_payload=f,
                )
            )
        return events
