"""In-process fixed-window rate limiter (Sprint 0).

Fixed-window counters keyed by an arbitrary string (per-IP, per-user, per-route).
In-memory and per-process — sufficient for a single-worker beta.  For multi-
worker / multi-replica production, swap the backend for Redis; the public
``check()`` signature is backend-agnostic so callers do not change.

No prompts, tokens, or user data are stored — only opaque keys and counts.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Dict, Optional, Tuple

from starlette.requests import Request

logger = logging.getLogger(__name__)

# Probes and Stripe's signed delivery channel must not share customer traffic
# budgets.  OPTIONS is handled separately because every route may receive it.
EXEMPT_PATHS = frozenset(
    {"/", "/health", "/healthz", "/readyz", "/version", "/billing/webhook"}
)

# Routes that can trigger provider, model, or portfolio-wide computation.  /ask
# keeps its existing dedicated preflight limits so it is not charged twice.
EXPENSIVE_ROUTES = frozenset(
    {
        ("POST", "/analyze"),
        ("POST", "/pipeline/run"),
        ("POST", "/events/process"),
        ("POST", "/portfolio/insights/refresh"),
    }
)


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


def client_ip(request: Request, trusted_proxy_hops: int = 1) -> str:
    """Best-effort client IP.

    Render/nginx append hops to ``X-Forwarded-For``.  Select from the right-hand
    trusted edge instead of the caller-controlled first value, then fall back
    to ``X-Real-IP`` or the socket peer.  Used only as a rate-limit bucket key.
    """
    xff = request.headers.get("x-forwarded-for", "")
    hops = [part.strip() for part in xff.split(",") if part.strip()]
    if hops and trusted_proxy_hops > 0:
        index = max(0, len(hops) - trusted_proxy_hops)
        return hops[index]
    real = request.headers.get("x-real-ip", "")
    if real and trusted_proxy_hops > 0:
        return real.strip()
    client = getattr(request, "client", None)
    return getattr(client, "host", "") or "unknown"


def is_exempt(request: Request) -> bool:
    return request.method.upper() == "OPTIONS" or request.url.path in EXEMPT_PATHS


def is_expensive(request: Request) -> bool:
    return (request.method.upper(), request.url.path.rstrip("/") or "/") in EXPENSIVE_ROUTES


def log_denial(*, scope: str, request: Request, retry_after: int) -> None:
    """Log only routing metadata; never tokens, bodies, tickers, or user data."""
    request_id = getattr(request.state, "request_id", "")
    logger.warning(
        "rate_limit_denied scope=%s method=%s path=%s retry_after=%s req=%s",
        scope,
        request.method,
        request.url.path,
        retry_after,
        request_id,
    )


# Module-level singleton shared across the app.
rate_limiter = RateLimiter()
