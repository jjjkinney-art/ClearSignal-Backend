"""
Reliability and failover module.

Lightweight, zero-dependency enterprise reliability patterns for
provider calls.  No external infra required.

Patterns implemented
--------------------
RetryPolicy     : configurable retry with exponential backoff and jitter
CircuitBreaker  : half-open circuit breaker per provider
ProviderHealth  : in-process source health tracker
call_with_reliability : combined wrapper that applies all patterns

Usage::

    result = call_with_reliability(
        provider_name = "fmp",
        fn            = lambda: get_company_profile(ticker),
        policy        = RetryPolicy(max_retries=2, backoff_factor=0.5),
        fallback_fn   = lambda: get_profile_from_cache(ticker),
    )
"""

from __future__ import annotations

import logging
import random
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


# ── Exception taxonomy ─────────────────────────────────────────────────────

class ProviderError(Exception):
    """Base class for all provider-related errors."""


class ProviderTimeoutError(ProviderError):
    """Provider call exceeded the timeout threshold."""


class ProviderRateLimitError(ProviderError):
    """Provider rejected the call due to rate limiting."""


class ProviderUnavailableError(ProviderError):
    """Provider is unreachable or returning 5xx errors."""


class ProviderAuthError(ProviderError):
    """Provider rejected the call due to auth failure."""


class CircuitOpenError(ProviderError):
    """Circuit breaker is open; call not attempted."""


def _classify_exception(exc: Exception) -> type:
    """Map a generic exception to a ProviderError subclass."""
    msg = str(exc).lower()
    if "timeout" in msg:
        return ProviderTimeoutError
    if "rate limit" in msg or "429" in msg:
        return ProviderRateLimitError
    if "unauthorized" in msg or "403" in msg or "401" in msg:
        return ProviderAuthError
    if "unavailable" in msg or "503" in msg or "502" in msg:
        return ProviderUnavailableError
    return ProviderError


# ── RetryPolicy ────────────────────────────────────────────────────────────

@dataclass
class RetryPolicy:
    """Configurable retry policy with exponential backoff and optional jitter.

    Attributes
    ----------
    max_retries     : maximum number of retry attempts (total calls = max_retries + 1)
    backoff_factor  : base for exponential backoff delay
    max_delay_s     : maximum delay between retries in seconds
    jitter          : add ±25% random jitter to delay when True
    retryable_errors: exception types that should trigger a retry
    """
    max_retries:     int   = 2
    backoff_factor:  float = 0.5
    max_delay_s:     float = 10.0
    jitter:          bool  = True
    retryable_errors: tuple = (ProviderTimeoutError, ProviderUnavailableError, ProviderRateLimitError)

    def delay(self, attempt: int) -> float:
        """Return the delay in seconds before attempt number ``attempt``."""
        delay = min(self.backoff_factor * (2 ** (attempt - 1)), self.max_delay_s)
        if self.jitter:
            delay *= (0.75 + random.random() * 0.5)  # ±25%
        return delay

    def should_retry(self, exc: Exception) -> bool:
        exc_type = _classify_exception(exc)
        return exc_type in self.retryable_errors


# ── CircuitBreaker ─────────────────────────────────────────────────────────

class CircuitState:
    CLOSED   = "closed"    # normal operation
    OPEN     = "open"      # failing; calls blocked
    HALF_OPEN = "half_open" # testing recovery


class CircuitBreaker:
    """Lightweight per-provider circuit breaker.

    States:
        CLOSED    → normal; failures accumulate
        OPEN      → too many failures; calls raise CircuitOpenError
        HALF_OPEN → one probe call allowed after cooldown_s
    """

    def __init__(
        self,
        failure_threshold: int   = 5,
        cooldown_s:        float = 60.0,
    ) -> None:
        self._threshold     = failure_threshold
        self._cooldown_s    = cooldown_s
        self._failures      = 0
        self._state         = CircuitState.CLOSED
        self._last_opened:  Optional[float] = None
        self._lock          = threading.Lock()

    @property
    def state(self) -> str:
        with self._lock:
            return self._get_state()

    def _get_state(self) -> str:
        if self._state == CircuitState.OPEN and self._last_opened is not None:
            if time.time() - self._last_opened >= self._cooldown_s:
                self._state = CircuitState.HALF_OPEN
        return self._state

    def call_allowed(self) -> bool:
        with self._lock:
            s = self._get_state()
            return s in (CircuitState.CLOSED, CircuitState.HALF_OPEN)

    def record_success(self) -> None:
        with self._lock:
            self._failures = 0
            self._state    = CircuitState.CLOSED

    def record_failure(self) -> None:
        with self._lock:
            self._failures += 1
            if self._failures >= self._threshold:
                self._state       = CircuitState.OPEN
                self._last_opened = time.time()
                logger.warning(f"CircuitBreaker: opened after {self._failures} failures")

    def to_dict(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "state":    self._get_state(),
                "failures": self._failures,
                "threshold": self._threshold,
            }


# ── ProviderHealth ─────────────────────────────────────────────────────────

class ProviderHealth:
    """In-process health tracker for all providers.

    Maintains per-provider CircuitBreakers and aggregates success/failure
    counts for health reporting.
    """

    def __init__(
        self,
        failure_threshold: int   = 5,
        cooldown_s:        float = 60.0,
    ) -> None:
        self._breakers:   Dict[str, CircuitBreaker] = {}
        self._successes:  Dict[str, int] = {}
        self._failures:   Dict[str, int] = {}
        self._lock        = threading.Lock()
        self._threshold   = failure_threshold
        self._cooldown    = cooldown_s

    def _get_breaker(self, provider: str) -> CircuitBreaker:
        with self._lock:
            if provider not in self._breakers:
                self._breakers[provider] = CircuitBreaker(
                    failure_threshold=self._threshold,
                    cooldown_s=self._cooldown,
                )
            return self._breakers[provider]

    def is_available(self, provider: str) -> bool:
        return self._get_breaker(provider).call_allowed()

    def record_success(self, provider: str) -> None:
        self._get_breaker(provider).record_success()
        with self._lock:
            self._successes[provider] = self._successes.get(provider, 0) + 1

    def record_failure(self, provider: str) -> None:
        self._get_breaker(provider).record_failure()
        with self._lock:
            self._failures[provider] = self._failures.get(provider, 0) + 1

    def health_report(self) -> Dict[str, Any]:
        with self._lock:
            report: Dict[str, Any] = {}
            for p in set(list(self._breakers.keys()) + list(self._successes.keys())):
                cb = self._breakers.get(p)
                report[p] = {
                    "state":    cb.to_dict()["state"] if cb else "unknown",
                    "successes": self._successes.get(p, 0),
                    "failures":  self._failures.get(p, 0),
                }
            return report


# ── Default health tracker ────────────────────────────────────────────────

provider_health = ProviderHealth()


# ── Combined reliability wrapper ──────────────────────────────────────────

def call_with_reliability(
    provider_name: str,
    fn:            Callable[[], T],
    policy:        Optional[RetryPolicy] = None,
    fallback_fn:   Optional[Callable[[], T]] = None,
    timeout_s:     Optional[float] = None,
) -> T:
    """Call ``fn`` with retry, circuit-breaker, and optional fallback.

    Parameters
    ----------
    provider_name : name used for health tracking and logging
    fn            : the provider call to execute
    policy        : RetryPolicy (uses default if None)
    fallback_fn   : called when all retries fail and circuit is open
    timeout_s     : (informational) expected timeout — actual enforcement
                    must be done inside ``fn``

    Returns
    -------
    T
        Result of ``fn`` or ``fallback_fn``.

    Raises
    ------
    Exception
        If fn fails after all retries and no fallback is provided.
    """
    pol = policy or RetryPolicy()

    # Circuit breaker check
    if not provider_health.is_available(provider_name):
        logger.warning(f"Circuit open for '{provider_name}'; skipping call")
        if fallback_fn is not None:
            try:
                return fallback_fn()
            except Exception:
                pass
        raise CircuitOpenError(f"Provider '{provider_name}' circuit is open")

    last_exc: Optional[Exception] = None
    for attempt in range(1, pol.max_retries + 2):  # +2: initial call + retries
        try:
            result = fn()
            provider_health.record_success(provider_name)
            return result
        except Exception as exc:
            provider_health.record_failure(provider_name)
            last_exc = exc
            logger.warning(
                f"Provider '{provider_name}' call failed (attempt {attempt}): {exc}"
            )
            if attempt <= pol.max_retries and pol.should_retry(exc):
                delay = pol.delay(attempt)
                logger.debug(f"Retrying '{provider_name}' in {delay:.2f}s")
                time.sleep(delay)
            else:
                break

    # All retries exhausted
    if fallback_fn is not None:
        logger.info(f"Provider '{provider_name}' exhausted; using fallback")
        try:
            return fallback_fn()
        except Exception as fb_exc:
            logger.warning(f"Fallback for '{provider_name}' also failed: {fb_exc}")

    raise last_exc or RuntimeError(f"Provider '{provider_name}' failed")
