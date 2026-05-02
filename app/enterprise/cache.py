"""
Lightweight in-process TTL cache with hit/miss observability.

No Redis or external dependencies required.  The default implementation
is thread-safe, bounded, and expiry-aware.  An optional Redis interface
is stubbed for future plug-in without breaking the default path.

Usage::

    result = response_cache.get("fmp:profile:AAPL")
    if result is None:
        result = get_company_profile("AAPL")
        response_cache.set("fmp:profile:AAPL", result, ttl_s=300)

Cache instances
---------------
response_cache  : provider API responses (short TTL)
history_cache   : history query results (medium TTL)
"""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ── Cache entry ────────────────────────────────────────────────────────────

@dataclass
class CacheEntry:
    """Single cached value with expiry tracking.

    Attributes
    ----------
    key         : cache key
    value       : cached payload (any picklable object)
    expires_at  : wall-clock time when this entry expires
    created_at  : wall-clock creation time
    hits        : number of times this entry has been read
    source_tags : metadata tags for invalidation grouping
    """
    key:         str
    value:       Any
    expires_at:  float
    created_at:  float = field(default_factory=time.time)
    hits:        int   = 0
    source_tags: List[str] = field(default_factory=list)

    def is_expired(self) -> bool:
        return time.time() > self.expires_at

    def touch(self) -> None:
        self.hits += 1


# ── InProcessCache ─────────────────────────────────────────────────────────

class InProcessCache:
    """Thread-safe in-process LRU-like cache with TTL and observability.

    Attributes
    ----------
    name        : human-readable cache name for logging
    default_ttl : default TTL in seconds
    max_entries : maximum number of entries before eviction
    """

    def __init__(
        self,
        name:        str   = "cache",
        default_ttl: float = 300.0,
        max_entries: int   = 1000,
    ) -> None:
        self.name        = name
        self.default_ttl = default_ttl
        self.max_entries = max_entries
        self._store:     Dict[str, CacheEntry] = {}
        self._lock       = threading.Lock()
        # Observability counters
        self._hits   = 0
        self._misses = 0
        self._sets   = 0
        self._evictions = 0

    # ── Core operations ───────────────────────────────────────────────────

    def get(self, key: str) -> Optional[Any]:
        """Return the cached value for ``key``, or None if missing/expired."""
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                self._misses += 1
                return None
            if entry.is_expired():
                del self._store[key]
                self._misses += 1
                return None
            entry.touch()
            self._hits += 1
            return entry.value

    def set(
        self,
        key:         str,
        value:       Any,
        ttl_s:       Optional[float] = None,
        source_tags: Optional[List[str]] = None,
    ) -> None:
        """Store ``value`` under ``key`` with the given TTL."""
        ttl = ttl_s if ttl_s is not None else self.default_ttl
        entry = CacheEntry(
            key         = key,
            value       = value,
            expires_at  = time.time() + ttl,
            source_tags = source_tags or [],
        )
        with self._lock:
            self._store[key] = entry
            self._sets += 1
            self._evict_if_needed()

    def delete(self, key: str) -> bool:
        """Remove a key.  Returns True if the key existed."""
        with self._lock:
            if key in self._store:
                del self._store[key]
                return True
            return False

    def invalidate_by_tag(self, tag: str) -> int:
        """Remove all entries with the given source_tag.  Returns count removed."""
        with self._lock:
            to_remove = [k for k, e in self._store.items() if tag in e.source_tags]
            for k in to_remove:
                del self._store[k]
            return len(to_remove)

    def clear(self) -> None:
        """Remove all entries."""
        with self._lock:
            self._store.clear()

    # ── Eviction ─────────────────────────────────────────────────────────

    def _evict_if_needed(self) -> None:
        """Evict expired entries first, then oldest if still over limit."""
        # Remove expired first
        expired = [k for k, e in self._store.items() if e.is_expired()]
        for k in expired:
            del self._store[k]
            self._evictions += 1
        # If still over limit, remove least-recently-used (fewest hits + oldest)
        if len(self._store) > self.max_entries:
            sorted_keys = sorted(
                self._store.keys(),
                key=lambda k: (self._store[k].hits, self._store[k].created_at),
            )
            overflow = len(self._store) - self.max_entries
            for k in sorted_keys[:overflow]:
                del self._store[k]
                self._evictions += 1

    # ── Observability ─────────────────────────────────────────────────────

    def stats(self) -> Dict[str, Any]:
        with self._lock:
            active  = sum(1 for e in self._store.values() if not e.is_expired())
            expired = len(self._store) - active
        hit_rate = self._hits / max(1, self._hits + self._misses)
        return {
            "name":       self.name,
            "active":     active,
            "expired":    expired,
            "hits":       self._hits,
            "misses":     self._misses,
            "sets":       self._sets,
            "evictions":  self._evictions,
            "hit_rate":   round(hit_rate, 3),
        }

    def log_stats(self) -> None:
        logger.info(json.dumps({"event": "cache_stats", **self.stats()}))


# ── Convenience key builders ──────────────────────────────────────────────

def provider_cache_key(provider: str, operation: str, identifier: str) -> str:
    """Build a canonical cache key for a provider call."""
    return f"{provider}:{operation}:{identifier}"


def history_cache_key(domain: str, ticker: str, days: Optional[int] = None) -> str:
    """Build a canonical cache key for a history query."""
    return f"history:{domain}:{ticker}:{days or 'all'}"


# ── Default cache instances ───────────────────────────────────────────────

response_cache = InProcessCache(
    name        = "response_cache",
    default_ttl = 300.0,    # 5 minutes for provider API responses
    max_entries = 500,
)

history_cache = InProcessCache(
    name        = "history_cache",
    default_ttl = 120.0,    # 2 minutes for history queries
    max_entries = 200,
)
