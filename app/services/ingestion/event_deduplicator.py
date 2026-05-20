"""
Event deduplication — prevents the same market event from being processed
multiple times when ingested from overlapping sources.

Deduplication strategy:
1. Content hash: SHA-256 of (ticker + category + headline + date-truncated timestamp)
2. In-memory seen-set with configurable max size (LRU eviction)
3. Persisted seen-set written to the timeline store for cross-process dedup

All methods are synchronous and never raise.
"""
from __future__ import annotations

import hashlib
import logging
from collections import OrderedDict
from typing import List, Optional

from .normalized_event import NormalizedEvent

logger = logging.getLogger(__name__)

# Maximum entries kept in the in-memory seen-set before LRU eviction
_DEFAULT_MAX_SIZE = 10_000


def _content_hash(event: NormalizedEvent) -> str:
    """
    Deterministic hash of the event's identity fields.

    Truncates timestamp to the date portion so minor ingestion-time
    differences don't cause duplicates for the same real-world event.
    """
    try:
        ticker_part = (event.ticker or "").upper().strip()
        category_part = event.category.value if event.category else ""
        headline_part = (event.headline or "").lower().strip()
        # Use date portion only (first 10 chars of ISO-8601)
        date_part = (event.event_timestamp or "")[:10]
        raw = f"{ticker_part}|{category_part}|{headline_part}|{date_part}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]
    except Exception as exc:
        logger.warning("_content_hash failed: %s", exc)
        return event.event_id  # fall back to event_id (never dedup)


class EventDeduplicator:
    """
    Lightweight LRU-backed deduplication for NormalizedEvent streams.

    Usage:
        dedup = EventDeduplicator()
        unique = dedup.filter(events)

    The deduplicator is intentionally stateless across restarts unless
    a snapshot is loaded via load_seen_hashes(). For production durability,
    persist via persist_seen_hashes() after each ingestion batch.
    """

    def __init__(self, max_size: int = _DEFAULT_MAX_SIZE) -> None:
        self._seen: OrderedDict[str, None] = OrderedDict()
        self._max_size = max_size
        self._total_seen = 0
        self._total_deduped = 0

    # ── Public API ─────────────────────────────────────────────────────────

    def is_duplicate(self, event: NormalizedEvent) -> bool:
        """Return True if this event has already been seen."""
        h = _content_hash(event)
        if h in self._seen:
            self._total_deduped += 1
            return True
        return False

    def mark_seen(self, event: NormalizedEvent) -> str:
        """Record the event as seen. Returns the content hash."""
        h = _content_hash(event)
        if h not in self._seen:
            self._seen[h] = None
            self._total_seen += 1
            # LRU eviction when at capacity
            if len(self._seen) > self._max_size:
                self._seen.popitem(last=False)
        return h

    def filter(self, events: List[NormalizedEvent]) -> List[NormalizedEvent]:
        """
        Return only events not yet seen. Marks all returned events as seen.
        Preserves input order.
        """
        unique: List[NormalizedEvent] = []
        for ev in events:
            if not self.is_duplicate(ev):
                self.mark_seen(ev)
                unique.append(ev)
        logger.debug(
            "EventDeduplicator.filter: %d in → %d unique (%d deduped this batch)",
            len(events),
            len(unique),
            len(events) - len(unique),
        )
        return unique

    def load_seen_hashes(self, hashes: List[str]) -> None:
        """Warm the seen-set from a persisted list of content hashes."""
        for h in hashes:
            if h not in self._seen:
                self._seen[h] = None
                if len(self._seen) > self._max_size:
                    self._seen.popitem(last=False)

    def persist_seen_hashes(self) -> List[str]:
        """Return current seen-hashes for persistence."""
        return list(self._seen.keys())

    @property
    def stats(self) -> dict:
        return {
            "total_seen": self._total_seen,
            "total_deduped": self._total_deduped,
            "in_memory_size": len(self._seen),
        }


# Module-level singleton for the default ingestion pipeline
_default_deduplicator: Optional[EventDeduplicator] = None


def get_default_deduplicator() -> EventDeduplicator:
    global _default_deduplicator
    if _default_deduplicator is None:
        _default_deduplicator = EventDeduplicator()
    return _default_deduplicator
