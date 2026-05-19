"""
Earnings ingestion adapter.

Prepares the interface for earnings data providers (e.g., FMP, Alpha Vantage,
Earnings Whispers). Currently returns stub data for architecture validation.
Replace _fetch_from_provider() with real API calls when provider is configured.
"""
from __future__ import annotations
import logging
from datetime import datetime, timezone
from typing import List, Optional

from .base import EventIngestionAdapter
from .normalized_event import EventCategory, NormalizedEvent, SourceReliability

logger = logging.getLogger(__name__)

class EarningsIngestionAdapter(EventIngestionAdapter):
    source_name = "earnings_api"
    source_reliability = "high"

    def __init__(self, api_key: Optional[str] = None, provider: str = "stub"):
        self._api_key = api_key
        self._provider = provider

    async def fetch_latest(self, tickers=None, since=None) -> List[NormalizedEvent]:
        try:
            return await self._fetch_from_provider(tickers, since)
        except Exception as exc:
            logger.warning("EarningsIngestionAdapter.fetch_latest failed: %s", exc)
            return []

    async def _fetch_from_provider(self, tickers, since) -> List[NormalizedEvent]:
        # STUB: Replace with real provider call
        # When implementing: call FMP /earnings or similar endpoint,
        # iterate results, call self.normalize(raw) for each
        return []

    async def health_check(self) -> bool:
        # Replace with actual connectivity check
        return self._provider == "stub"

    def normalize(self, raw: dict) -> Optional[NormalizedEvent]:
        """
        Normalize a raw earnings record.
        Expected raw fields: ticker, period, actual_eps, estimated_eps,
                             actual_revenue, estimated_revenue, date
        """
        try:
            ticker = raw.get("ticker", "").upper()
            if not ticker:
                return None

            actual_eps = raw.get("actual_eps")
            est_eps = raw.get("estimated_eps")
            beat = actual_eps and est_eps and actual_eps > est_eps
            miss = actual_eps and est_eps and actual_eps < est_eps

            headline = f"{ticker} Q{raw.get('period', '')} earnings: "
            if beat:
                headline += f"EPS beat (${actual_eps:.2f} vs ${est_eps:.2f} est)"
            elif miss:
                headline += f"EPS miss (${actual_eps:.2f} vs ${est_eps:.2f} est)"
            else:
                headline += f"EPS in-line (${actual_eps:.2f})"

            tags = ["beat"] if beat else (["miss"] if miss else [])

            return NormalizedEvent(
                ticker=ticker,
                category=EventCategory.EARNINGS,
                headline=headline,
                source="earnings_release",
                source_reliability=SourceReliability.HIGH,
                event_timestamp=raw.get("date", datetime.now(timezone.utc).isoformat()),
                ingestion_timestamp=datetime.now(timezone.utc).isoformat(),
                raw_payload=raw,
                is_market_moving=True,
                tags=tags,
            )
        except Exception as exc:
            logger.warning("EarningsIngestionAdapter.normalize failed: %s", exc)
            return None
