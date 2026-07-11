"""
Usage tracking service.

Tracks API usage per user/session for rate limiting and analytics.
Currently in-memory with no persistence — replace with Redis or DB
for production multi-process deployments.

Hooks (register callbacks for external analytics):
    usage_tracker.register_hook(lambda event: send_to_posthog(event))
"""
from __future__ import annotations

import time
import logging
from collections import defaultdict, deque
from typing import Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


class UsageEvent:
    __slots__ = ("user_id", "event_type", "ticker", "timestamp", "metadata")

    def __init__(
        self,
        user_id: str,
        event_type: str,
        ticker: str = "",
        metadata: Optional[dict] = None,
    ):
        self.user_id = user_id
        self.event_type = event_type  # "analysis" | "watchlist_add" | "brief_view" | "alert_view"
        self.ticker = ticker
        self.timestamp = time.time()
        self.metadata = metadata or {}


class UsageTracker:
    """
    Tracks usage events and enforces rate limits.

    Rate limits are per user_id and per event_type, using a sliding window.
    """

    def __init__(self, window_seconds: int = 60):
        self._window = window_seconds
        self._events: Dict[str, deque] = defaultdict(deque)  # user_id → deque of timestamps
        self._hooks: List[Callable[[UsageEvent], None]] = []
        self._totals: Dict[str, int] = defaultdict(int)  # event_type → total count
        # Per-user, per-UTC-day counters for daily quotas.
        # key = f"{event_type}:{user_id}:{YYYY-MM-DD}" → count
        self._daily: Dict[str, int] = defaultdict(int)

    def track(self, event: UsageEvent) -> None:
        """Record a usage event and fire registered hooks."""
        key = f"{event.user_id}:{event.event_type}"
        self._events[key].append(event.timestamp)
        self._totals[event.event_type] += 1

        # Fire hooks (never raise)
        for hook in self._hooks:
            try:
                hook(event)
            except Exception as exc:
                logger.debug("Usage hook failed: %s", exc)

    def check_rate_limit(
        self,
        user_id: str,
        event_type: str,
        max_per_window: int,
    ) -> bool:
        """Return True if within rate limit, False if exceeded."""
        now = time.time()
        key = f"{user_id}:{event_type}"
        dq = self._events[key]

        # Prune events outside window
        while dq and dq[0] < now - self._window:
            dq.popleft()

        return len(dq) < max_per_window

    def register_hook(self, hook: Callable[[UsageEvent], None]) -> None:
        """Register a callback for every usage event (for external analytics)."""
        self._hooks.append(hook)

    def get_user_count(self, user_id: str, event_type: str) -> int:
        """Count events in the current window for a user."""
        now = time.time()
        key = f"{user_id}:{event_type}"
        dq = self._events[key]
        while dq and dq[0] < now - self._window:
            dq.popleft()
        return len(dq)

    def get_totals(self) -> Dict[str, int]:
        """Return aggregate event totals since startup."""
        return dict(self._totals)

    # ── Per-user daily quota (Sprint 0) ──────────────────────────────────────
    @staticmethod
    def _utc_day(ts: Optional[float] = None) -> str:
        from datetime import datetime, timezone
        dt = (
            datetime.fromtimestamp(ts, timezone.utc)
            if ts is not None
            else datetime.now(timezone.utc)
        )
        return dt.strftime("%Y-%m-%d")

    def _daily_key(self, user_id: str, event_type: str, day: Optional[str]) -> str:
        return f"{event_type}:{user_id}:{day or self._utc_day()}"

    def daily_count(
        self, user_id: str, event_type: str = "ask", day: Optional[str] = None
    ) -> int:
        """Return today's (UTC) count for a user/event_type."""
        return self._daily.get(self._daily_key(user_id, event_type, day), 0)

    def incr_daily(
        self, user_id: str, event_type: str = "ask", day: Optional[str] = None
    ) -> int:
        """Increment and return today's (UTC) count for a user/event_type."""
        key = self._daily_key(user_id, event_type, day)
        self._daily[key] += 1
        return self._daily[key]

    def within_daily_quota(
        self, user_id: str, limit: int, event_type: str = "ask"
    ) -> bool:
        """True if the user is still under *limit* today.  ``limit < 0`` = unlimited."""
        if limit < 0:
            return True
        return self.daily_count(user_id, event_type) < limit


# Module-level singleton
usage_tracker = UsageTracker(window_seconds=60)
