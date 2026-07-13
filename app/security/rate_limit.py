"""In-process fixed-window rate limiter (Sprint 0).

Fixed-window counters keyed by an arbitrary string (per-IP, per-user, per-route).
In-memory and per-process — sufficient for a single-worker beta.  For multi-
worker / multi-replica production, swap the backend for Redis; the public
``check()`` signature is backend-agnostic so callers do not change.

No prompts, tokens, or user data are stored — only opaque keys and counts.
"""
from __future__ import annotations

import threading
import time
from typing import Dict, Optional, Tuple

from starlette.requests import Request


class RateLimiter:
    """Thread-safe fixed-window counter."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # key -> (window_start_epoch, count)
        self._buckets: Dict[str, Tuple[float, int]] = {}

    def check(
        self,
        key: str,
        limit: int,
        window_s: int,
        *,
        now: Optional[float] = None,
    ) -> Tuple[bool, int]:
        """Consume one unit against *key*.

        Returns ``(allowed, retry_after_seconds)``.  ``limit <= 0`` disables the
        limit (always allowed).  When the window has elapsed the counter resets.
        """
        if limit <= 0:
            return True, 0
        t = time.time() if now is None else now
        with self._lock:
            start, count = self._buckets.get(key, (t, 0))
            if t - start >= window_s:
                start, count = t, 0
            if count >= limit:
                retry_after = max(1, int(window_s - (t - start)))
                return False, retry_after
            self._buckets[key] = (start, count + 1)
            return True, 0

    def peek(self, key: str, window_s: int, *, now: Optional[float] = None) -> int:
        """Current count in the active window without consuming."""
        t = time.time() if now is None else now
        with self._lock:
            start, count = self._buckets.get(key, (t, 0))
            if t - start >= window_s:
                return 0
            return count

    def reset(self) -> None:
        with self._lock:
            self._buckets.clear()


def client_ip(request: Request) -> str:
    """Best-effort client IP.

    Honours the first hop of ``X-Forwarded-For`` (set by Render / nginx) and
    falls back to the socket peer.  Used only as a rate-limit bucket key.
    """
    xff = request.headers.get("x-forwarded-for", "")
    if xff:
        return xff.split(",")[0].strip()
    real = request.headers.get("x-real-ip", "")
    if real:
        return real.strip()
    client = getattr(request, "client", None)
    return getattr(client, "host", "") or "unknown"


# Module-level singleton shared across the app.
rate_limiter = RateLimiter()
