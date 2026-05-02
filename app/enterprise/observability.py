"""
Observability module — structured tracing across the full request lifecycle.

Provides lightweight, zero-dependency request tracing that makes it possible
to reconstruct:

    request → routing → provider selection → evidence build
    → agent calls → synthesis → monitoring/alerts

Design principles:
    - No external dependencies (works without OpenTelemetry installed)
    - Thread-safe span accumulation per request
    - Structured JSON-serializable output
    - Optional integration with real tracing backends via the emit hook
    - All spans carry request_id, trace_id, stage, timing, and status

Usage::

    trace = get_tracer(request_id="req-123")
    with start_span(trace, "evidence_build") as span:
        span.set_tag("sources", ["fmp", "sec"])
        result = build_evidence(...)
        span.set_tag("record_count", len(result))
    trace.finish()
    print(trace.to_dict())
"""

from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Generator, List, Optional

logger = logging.getLogger(__name__)

# Optional emit hook: set to a callable(dict) to forward spans to an
# external system (e.g. OpenTelemetry, Datadog, CloudWatch).
_EMIT_HOOK: Optional[Callable[[Dict[str, Any]], None]] = None


def set_emit_hook(hook: Callable[[Dict[str, Any]], None]) -> None:
    """Register a callable that will receive every finished span dict."""
    global _EMIT_HOOK
    _EMIT_HOOK = hook


# ── Error category taxonomy ────────────────────────────────────────────────

class ErrorCategory:
    PROVIDER_TIMEOUT      = "provider_timeout"
    PROVIDER_AUTH         = "provider_auth"
    PROVIDER_RATE_LIMIT   = "provider_rate_limit"
    PROVIDER_UNAVAILABLE  = "provider_unavailable"
    EVIDENCE_BUILD        = "evidence_build"
    AGENT_CALL            = "agent_call"
    ROUTING               = "routing"
    STORAGE               = "storage"
    UNKNOWN               = "unknown"

    @staticmethod
    def categorize(exc: Exception) -> str:
        msg = str(exc).lower()
        if "timeout" in msg:
            return ErrorCategory.PROVIDER_TIMEOUT
        if "rate limit" in msg or "429" in msg:
            return ErrorCategory.PROVIDER_RATE_LIMIT
        if "unauthorized" in msg or "403" in msg or "401" in msg:
            return ErrorCategory.PROVIDER_AUTH
        if "unavailable" in msg or "503" in msg or "502" in msg:
            return ErrorCategory.PROVIDER_UNAVAILABLE
        return ErrorCategory.UNKNOWN


# ── Span ───────────────────────────────────────────────────────────────────

@dataclass
class Span:
    """A single timed stage in the request lifecycle.

    Attributes
    ----------
    span_id     : unique ID for this span
    request_id  : parent request ID
    trace_id    : trace this span belongs to
    stage       : name of the processing stage
    start_time  : wall-clock start (seconds since epoch)
    end_time    : wall-clock end, set when span finishes
    duration_ms : elapsed milliseconds (set on finish)
    status      : "ok" | "error" | "partial"
    error       : error message if status != "ok"
    error_category : categorized error type
    tags        : arbitrary key-value metadata
    """
    span_id:        str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    request_id:     str = ""
    trace_id:       str = ""
    stage:          str = ""
    start_time:     float = field(default_factory=time.time)
    end_time:       Optional[float] = None
    duration_ms:    Optional[float] = None
    status:         str = "ok"
    error:          Optional[str] = None
    error_category: Optional[str] = None
    tags:           Dict[str, Any] = field(default_factory=dict)

    def set_tag(self, key: str, value: Any) -> None:
        self.tags[key] = value

    def finish(self, status: str = "ok", error: Optional[Exception] = None) -> None:
        self.end_time   = time.time()
        self.duration_ms = (self.end_time - self.start_time) * 1000
        self.status     = status
        if error is not None:
            self.error          = str(error)
            self.error_category = ErrorCategory.categorize(error)
            self.status         = "error"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "span_id":        self.span_id,
            "request_id":     self.request_id,
            "trace_id":       self.trace_id,
            "stage":          self.stage,
            "start_time":     self.start_time,
            "end_time":       self.end_time,
            "duration_ms":    self.duration_ms,
            "status":         self.status,
            "error":          self.error,
            "error_category": self.error_category,
            "tags":           self.tags,
        }


# ── RequestTrace ───────────────────────────────────────────────────────────

class RequestTrace:
    """Accumulates all spans for a single request.

    Thread-safe: multiple threads may add spans concurrently.
    """

    def __init__(self, request_id: str, trace_id: Optional[str] = None) -> None:
        self.request_id  = request_id
        self.trace_id    = trace_id or str(uuid.uuid4())[:16]
        self.start_time  = time.time()
        self.end_time:   Optional[float] = None
        self.total_ms:   Optional[float] = None
        self._spans:     List[Span] = []
        self._lock       = threading.Lock()
        self._metadata:  Dict[str, Any] = {}

    def add_span(self, span: Span) -> None:
        span.request_id = self.request_id
        span.trace_id   = self.trace_id
        with self._lock:
            self._spans.append(span)
        if _EMIT_HOOK is not None:
            try:
                _EMIT_HOOK(span.to_dict())
            except Exception:
                pass

    def set_metadata(self, key: str, value: Any) -> None:
        self._metadata[key] = value

    def finish(self) -> None:
        self.end_time = time.time()
        self.total_ms = (self.end_time - self.start_time) * 1000

    @property
    def spans(self) -> List[Span]:
        with self._lock:
            return list(self._spans)

    def get_stage_timing(self, stage: str) -> Optional[float]:
        """Return duration_ms for the first span matching stage."""
        for s in self.spans:
            if s.stage == stage and s.duration_ms is not None:
                return s.duration_ms
        return None

    def has_errors(self) -> bool:
        return any(s.status == "error" for s in self.spans)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "request_id":  self.request_id,
            "trace_id":    self.trace_id,
            "start_time":  self.start_time,
            "end_time":    self.end_time,
            "total_ms":    self.total_ms,
            "span_count":  len(self._spans),
            "has_errors":  self.has_errors(),
            "metadata":    self._metadata,
            "spans":       [s.to_dict() for s in self.spans],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), default=str)

    def log_summary(self) -> None:
        """Emit a structured summary log at INFO level."""
        summary = {
            "event":       "trace_summary",
            "request_id":  self.request_id,
            "trace_id":    self.trace_id,
            "total_ms":    self.total_ms,
            "span_count":  len(self._spans),
            "has_errors":  self.has_errors(),
            "stage_timings": {
                s.stage: s.duration_ms for s in self.spans if s.duration_ms
            },
        }
        logger.info(json.dumps(summary, default=str))


# ── Per-request trace registry ─────────────────────────────────────────────
# Simple thread-local store so traces can be retrieved within a request.

_trace_store: Dict[str, RequestTrace] = {}
_store_lock = threading.Lock()


def get_tracer(request_id: str, trace_id: Optional[str] = None) -> RequestTrace:
    """Create and register a RequestTrace for the given request_id."""
    trace = RequestTrace(request_id=request_id, trace_id=trace_id)
    with _store_lock:
        _trace_store[request_id] = trace
    return trace


def get_existing_trace(request_id: str) -> Optional[RequestTrace]:
    """Retrieve an existing trace by request_id, or None if not found."""
    with _store_lock:
        return _trace_store.get(request_id)


def finish_trace(request_id: str) -> Optional[RequestTrace]:
    """Finish and remove a trace from the store, returning it."""
    with _store_lock:
        trace = _trace_store.pop(request_id, None)
    if trace is not None:
        trace.finish()
        trace.log_summary()
    return trace


# ── Context-manager span helper ────────────────────────────────────────────

@contextmanager
def start_span(
    trace: RequestTrace,
    stage: str,
    tags: Optional[Dict[str, Any]] = None,
) -> Generator[Span, None, None]:
    """Context manager that creates, runs, and finishes a Span.

    Usage::

        with start_span(trace, "provider_call", {"provider": "fmp"}) as span:
            result = call_provider(...)
            span.set_tag("records", len(result))
    """
    span = Span(stage=stage, tags=tags or {})
    span.request_id = trace.request_id
    span.trace_id   = trace.trace_id
    try:
        yield span
        span.finish(status="ok")
    except Exception as exc:
        span.finish(error=exc)
        raise
    finally:
        trace.add_span(span)


# ── Standalone span logger (no trace context required) ─────────────────────

def log_event(
    event: str,
    request_id: str = "",
    **kwargs: Any,
) -> None:
    """Emit a single structured log event without a full trace context."""
    payload: Dict[str, Any] = {"event": event, "request_id": request_id}
    payload.update(kwargs)
    logger.info(json.dumps(payload, default=str))
