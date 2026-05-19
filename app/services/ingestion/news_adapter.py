"""
News ingestion adapter.

Prepares interface for news providers (Bloomberg wire, Reuters, Financial Times).
Stub implementation — replace _fetch_from_provider() with real API calls.
"""
from __future__ import annotations
import logging
from datetime import datetime, timezone
from typing import List, Optional

from .base import EventIngestionAdapter
from .normalized_event import EventCategory, NormalizedEvent, SourceReliability

logger = logging.getLogger(__name__)

class NewsIngestionAdapter(EventIngestionAdapter):
    source_name = "news_wire"
    source_reliability = "medium"

    def __init__(self, api_key: Optional[str] = None, provider: str = "stub"):
        self._api_key = api_key
        self._provider = provider

    async def fetch_latest(self, tickers=None, since=None) -> List[NormalizedEvent]:
        try:
            return await self._fetch_from_provider(tickers, since)
        except Exception as exc:
            logger.warning("NewsIngestionAdapter.fetch_latest failed: %s", exc)
            return []

    async def _fetch_from_provider(self, tickers, since) -> List[NormalizedEvent]:
        return []

    async def health_check(self) -> bool:
        return self._provider == "stub"

    def normalize(self, raw: dict) -> Optional[NormalizedEvent]:
        """Normalize a raw news article. Expected: title, body, source, published_at, tickers"""
        try:
            headline = raw.get("title", "")
            if not headline:
                return None
            body = raw.get("body", raw.get("summary", ""))
            tickers_list = raw.get("tickers", [])
            ticker = tickers_list[0].upper() if tickers_list else None

            tags = self._tag_event(headline, body)

            # Estimate market-moving potential
            high_impact_keywords = ["earnings", "guidance", "acquisition", "sec", "ftc", "ceo", "bankruptcy"]
            is_market_moving = any(kw in f"{headline} {body}".lower() for kw in high_impact_keywords)

            return NormalizedEvent(
                ticker=ticker,
                category=EventCategory.NEWS,
                headline=headline,
                body=body[:500],
                source=raw.get("source", "news_wire"),
                source_reliability=SourceReliability.MEDIUM,
                event_timestamp=raw.get("published_at", datetime.now(timezone.utc).isoformat()),
                ingestion_timestamp=datetime.now(timezone.utc).isoformat(),
                raw_payload=raw,
                is_market_moving=is_market_moving,
                tags=tags,
            )
        except Exception as exc:
            logger.warning("NewsIngestionAdapter.normalize failed: %s", exc)
            return None
