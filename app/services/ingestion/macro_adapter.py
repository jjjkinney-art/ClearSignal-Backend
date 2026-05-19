"""
Macro data ingestion adapter.

Handles: Fed meeting outcomes, CPI/PPI/PCE prints, jobs reports, GDP.
Stub implementation — replace _fetch_from_provider() with real API.
"""
from __future__ import annotations
import logging
from datetime import datetime, timezone
from typing import List, Optional

from .base import EventIngestionAdapter
from .normalized_event import EventCategory, NormalizedEvent, SourceReliability

logger = logging.getLogger(__name__)

_MACRO_MARKET_MOVING = {
    "fomc", "fed funds", "cpi", "ppi", "pce", "nonfarm payroll",
    "gdp", "unemployment", "inflation", "rate decision",
}

class MacroIngestionAdapter(EventIngestionAdapter):
    source_name = "macro_feed"
    source_reliability = "high"  # macro data is from official government releases

    def __init__(self, api_key: Optional[str] = None, provider: str = "stub"):
        self._api_key = api_key
        self._provider = provider

    async def fetch_latest(self, tickers=None, since=None) -> List[NormalizedEvent]:
        try:
            return await self._fetch_from_provider(tickers, since)
        except Exception as exc:
            logger.warning("MacroIngestionAdapter.fetch_latest failed: %s", exc)
            return []

    async def _fetch_from_provider(self, tickers, since) -> List[NormalizedEvent]:
        return []

    async def health_check(self) -> bool:
        return self._provider == "stub"

    def normalize(self, raw: dict) -> Optional[NormalizedEvent]:
        """Normalize a raw macro event. Expected: name, actual, estimate, previous, date"""
        try:
            name = raw.get("name", "")
            if not name:
                return None

            actual = raw.get("actual")
            estimate = raw.get("estimate")
            prev = raw.get("previous")

            parts = [f"{name}:"]
            if actual is not None:
                parts.append(f"actual {actual}")
            if estimate is not None:
                parts.append(f"vs {estimate} est")
            if prev is not None:
                parts.append(f"(prior: {prev})")

            headline = " ".join(parts)
            text_lower = name.lower()
            is_market_moving = any(kw in text_lower for kw in _MACRO_MARKET_MOVING)

            tags = self._tag_event(headline, "")
            if actual and estimate:
                if float(actual) > float(estimate):
                    tags.append("beat")
                elif float(actual) < float(estimate):
                    tags.append("miss")

            return NormalizedEvent(
                ticker=None,  # macro events are not ticker-specific
                category=EventCategory.MACRO,
                headline=headline,
                source="macro_release",
                source_reliability=SourceReliability.HIGH,
                event_timestamp=raw.get("date", datetime.now(timezone.utc).isoformat()),
                ingestion_timestamp=datetime.now(timezone.utc).isoformat(),
                raw_payload=raw,
                is_market_moving=is_market_moving,
                tags=tags,
            )
        except Exception as exc:
            logger.warning("MacroIngestionAdapter.normalize failed: %s", exc)
            return None
