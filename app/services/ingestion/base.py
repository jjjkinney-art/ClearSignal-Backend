"""Abstract base class for all event ingestion adapters."""
from __future__ import annotations
from abc import ABC, abstractmethod
from typing import AsyncIterator, List, Optional
from .normalized_event import NormalizedEvent

class EventIngestionAdapter(ABC):
    """
    Base class for all market data ingestion adapters.

    Each adapter connects to one data source (earnings API, news feed, etc.)
    and normalizes events to NormalizedEvent format.

    Implementation contract:
    - Never raise exceptions to callers; log and return empty list on failure
    - Always populate event_timestamp from source data
    - Always set source_reliability based on source type
    - Tags should include actionable keywords: "beat", "miss", "raised", "lowered", "announced"
    """

    source_name: str = "unknown"        # override in subclass
    source_reliability: str = "medium"  # override in subclass

    @abstractmethod
    async def fetch_latest(
        self,
        tickers: Optional[List[str]] = None,  # None = fetch all available
        since: Optional[str] = None,           # ISO-8601 cutoff
    ) -> List[NormalizedEvent]:
        """Fetch latest events and return normalized."""

    @abstractmethod
    async def health_check(self) -> bool:
        """Return True if the data source is reachable."""

    def normalize(self, raw: dict) -> Optional[NormalizedEvent]:
        """
        Convert a raw provider payload to NormalizedEvent.
        Return None if the event should be skipped (not market-relevant).
        Override in subclasses.
        """
        return None

    def _tag_event(self, headline: str, body: str) -> list[str]:
        """Extract actionable tags from text."""
        text = f"{headline} {body}".lower()
        tags = []
        keyword_map = {
            "beat": ["beat", "exceeded", "topped", "surpassed"],
            "miss": ["missed", "fell short", "below estimates", "disappointed"],
            "raised": ["raised guidance", "increased outlook", "raised forecast"],
            "lowered": ["lowered guidance", "cut outlook", "reduced forecast"],
            "announced": ["announced", "unveiled", "launched"],
            "merger": ["acquisition", "merger", "takeover", "deal"],
            "regulatory": ["sec", "ftc", "doj", "investigation", "fine", "penalty"],
        }
        for tag, keywords in keyword_map.items():
            if any(kw in text for kw in keywords):
                tags.append(tag)
        return tags
