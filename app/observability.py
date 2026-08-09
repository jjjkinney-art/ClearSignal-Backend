"""Request-scoped observability for the /ask pipeline (Sprint 3A).

Sprint 2D closed the last correctness finding, so the open question is no
longer "is the answer right" but "where do the 20-67 seconds go".  This module
is the measurement layer for that question.  It records, per request:

  * stage timings   — routing, retrieval, each agent, synthesis, integrity, ...
  * model calls     — model, duration, token usage, retries, failure class
  * provider calls  — SEC/FMP/news/FRED/..., duration, result count, cache state

Three properties matter more than completeness here:

1. **It never changes behavior.**  Every entry point swallows its own
   exceptions.  A bug in instrumentation must never fail a request, and timing
   must never alter control flow.
2. **It never leaks.**  Prompts, completions, hidden reasoning, API keys and
   evidence bodies are not recordable — ``_scrub`` drops any key that looks
   like content or a credential, so a careless call site cannot leak through.
3. **It survives threads.**  The pipeline runs ``route_question`` in an
   executor and fans evidence out across a ThreadPoolExecutor; ``bind()``
   carries the active trace across those boundaries, since contextvars do not
   propagate into ``run_in_executor``/``submit`` on their own.

The trace is reached through a ContextVar rather than threaded through call
signatures, so instrumenting a stage does not mean editing the business
function's parameters.
"""
from __future__ import annotations

import hmac
import json
import logging
import os
import threading
import time
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterator, List, Optional

logger = logging.getLogger("clearsignal.observability")

# Stage status vocabulary. `skipped` is deliberately distinct from a
# zero-duration `ok`: "this stage did not run" and "this stage ran instantly"
# are different diagnoses.
STATUS_OK = "ok"
STATUS_ERROR = "error"
STATUS_TIMEOUT = "timeout"
STATUS_SKIPPED = "skipped"

# ── Redaction ────────────────────────────────────────────────────────────────
# Substrings that mark a detail key as content or credential material. Matching
# is on the key name, so a call site cannot smuggle a prompt through by naming
# the field something plausible.
_UNSAFE_KEY_MARKERS = (
    "prompt", "completion", "content", "message", "text", "body", "payload",
    "reasoning", "thought", "chain_of_thought", "answer", "response_text",
    "api_key", "apikey", "key", "secret", "token_value", "password",
    "authorization", "auth", "credential", "bearer", "cookie", "evidence",
)
# Keys that contain an unsafe marker but are legitimate metadata.
_SAFE_KEY_EXCEPTIONS = frozenset({
    "input_tokens", "output_tokens", "total_tokens", "token_count",
    "content_length", "message_count", "evidence_count", "result_count",
})
_MAX_DETAIL_STR = 200


def _is_safe_key(key: str) -> bool:
    lowered = str(key).lower()
    if lowered in _SAFE_KEY_EXCEPTIONS:
        return True
    # Sprint 3A.1: a singular "token" is a credential, a plural "tokens" is a
    # usage count. Splitting on that distinction keeps `total_tokens` reportable
    # while `profile_token` / `auth_token` can never be recorded.
    if lowered == "token" or lowered.endswith("_token") or "token=" in lowered:
        return False
    return not any(marker in lowered for marker in _UNSAFE_KEY_MARKERS)


def _scrub(detail: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Keep only JSON-safe, non-sensitive metadata.

    Unsafe keys are dropped rather than masked — a masked key still advertises
    that the value existed, and there is no diagnostic value in that here.
    """
    out: Dict[str, Any] = {}
    if not detail:
        return out
    for key, value in detail.items():
        if not _is_safe_key(key):
            continue
        if value is None or isinstance(value, (bool, int, float)):
            out[str(key)] = value
        elif isinstance(value, str):
            out[str(key)] = value[:_MAX_DETAIL_STR]
        elif isinstance(value, (list, tuple)):
            out[str(key)] = len(value)          # record shape, never contents
        elif isinstance(value, dict):
            out[str(key)] = len(value)
        else:
            out[str(key)] = str(value)[:_MAX_DETAIL_STR]
    return out


# ── Build identity ───────────────────────────────────────────────────────────

def build_identity() -> Dict[str, str]:
    """Backend version / commit / environment, read from the deployment env.

    Reuses the same environment variables the /health endpoint already reports
    (RENDER_GIT_COMMIT first, GIT_COMMIT as a local fallback) so a request and
    a health check can never disagree about which commit is serving. Never
    shells out to git — that would be a subprocess on the request path.
    """
    commit = (
        os.environ.get("RENDER_GIT_COMMIT", "")[:12]
        or os.environ.get("GIT_COMMIT", "")[:12]
        or "unknown"
    )
    environment = (
        "production" if os.environ.get("RENDER_SERVICE_ID")
        else "development" if os.environ.get("NODE_ENV") != "production"
        else "unknown"
    )
    try:
        from .services.conviction_modeler import CONVICTION_SCHEMA_VERSION
        version = str(CONVICTION_SCHEMA_VERSION)
    except Exception:
        version = "unknown"
    return {
        "backend_version": version,
        "build_commit": commit,
        "environment": environment,
    }


# ── Secure profiling authorization (Sprint 3A.1) ─────────────────────────────
# Sprint 3A gated stage detail on environment alone, so production responses
# never carried it — correct for ordinary users, but it also blinded the
# validation harness the instrumentation was built for (the sprint3a-asml run
# came back with an empty stage table and `unknown` bottlenecks).
#
# Detail is now unlocked by an explicitly authorized request instead: the
# caller asks for it AND proves it holds the shared secret. Both headers are
# required, the secret is compared in constant time, and an unconfigured
# deployment refuses regardless of what is sent.
DETAIL_REQUEST_HEADER = "X-ClearSignal-Observability-Detail"
DETAIL_TOKEN_HEADER = "X-ClearSignal-Observability-Token"
# Sprint 3B.1 — selects an experimental synthesis prompt for an A/B run. Gated
# by the SAME authorization as detail: an unauthorized caller always gets the
# production prompt regardless of what it sends.
PROMPT_VARIANT_HEADER = "X-ClearSignal-Synthesis-Variant"

_TRUTHY = frozenset({"1", "true", "yes", "on"})


def _configured_profile_token() -> str:
    try:
        from .config import settings
        return str(getattr(settings, "observability_profile_token", "") or "")
    except Exception:  # pragma: no cover - config must never break a request
        return ""


def profiling_authorized(
    detail_requested: Optional[str], supplied_token: Optional[str],
) -> bool:
    """True only for an explicit, correctly authorized request for detail.

    Fails closed on every ambiguity: no configured secret, absent or
    non-affirmative opt-in header, absent token, or any mismatch. The
    comparison is constant-time so a wrong token cannot be discovered by
    timing the response.
    """
    expected = _configured_profile_token()
    if not expected:
        return False                     # feature disabled unless deployed with a secret
    if str(detail_requested or "").strip().lower() not in _TRUTHY:
        return False                     # opt-in must be explicit
    supplied = str(supplied_token or "").strip()
    if not supplied:
        return False
    return hmac.compare_digest(supplied, expected)


def should_include_detail(
    *, is_production: bool, detail_requested: Optional[str] = None,
    supplied_token: Optional[str] = None,
) -> bool:
    """Decide whether a response carries detailed observability.

    Outside production, detail stays on as it was in Sprint 3A — local and
    development debugging is unchanged. In production it requires an
    authorized profiling request.
    """
    if not is_production:
        return True
    return profiling_authorized(detail_requested, supplied_token)


# ── Records ──────────────────────────────────────────────────────────────────

@dataclass
class StageRecord:
    stage: str
    status: str = STATUS_OK
    duration_ms: Optional[float] = None
    started_offset_ms: float = 0.0
    error_class: Optional[str] = None
    detail: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {
            "stage": self.stage,
            "status": self.status,
            "duration_ms": self.duration_ms,
            "started_offset_ms": round(self.started_offset_ms, 2),
        }
        if self.error_class:
            out["error_class"] = self.error_class
        if self.detail:
            out["detail"] = self.detail
        return out


class RequestTrace:
    """All observability records for a single /ask request.

    Thread-safe: the evidence fan-out writes provider records from up to seven
    worker threads at once.
    """

    def __init__(self, request_id: Optional[str] = None, *,
                 ticker: str = "", route: str = "") -> None:
        self.request_id = request_id or uuid.uuid4().hex[:8]
        self.ticker = ticker
        self.route = route
        self._start = time.monotonic()
        self._lock = threading.Lock()
        self.stages: List[StageRecord] = []
        self.model_calls: List[Dict[str, Any]] = []
        self.provider_calls: List[Dict[str, Any]] = []

    # -- timing ------------------------------------------------------------
    def _offset_ms(self) -> float:
        return (time.monotonic() - self._start) * 1000.0

    def total_duration_ms(self) -> float:
        return round(self._offset_ms(), 2)

    @contextmanager
    def stage(self, name: str, **detail: Any) -> Iterator[StageRecord]:
        """Time a stage. Records duration whether it succeeds, raises, or times
        out, then re-raises unchanged so control flow is untouched."""
        record = StageRecord(stage=name, started_offset_ms=self._offset_ms(),
                             detail=_scrub(detail))
        began = time.monotonic()
        try:
            yield record
        except BaseException as exc:  # noqa: BLE001 - re-raised below
            record.duration_ms = round((time.monotonic() - began) * 1000.0, 2)
            name_of = type(exc).__name__
            record.error_class = name_of
            record.status = (
                STATUS_TIMEOUT if "timeout" in name_of.lower() else STATUS_ERROR
            )
            self._append_stage(record)
            raise
        else:
            record.duration_ms = round((time.monotonic() - began) * 1000.0, 2)
            if record.status == STATUS_OK:
                pass  # a call site may already have marked it skipped/timeout
            self._append_stage(record)

    def skip(self, name: str, reason: str = "") -> None:
        """Record that a stage did not run at all."""
        record = StageRecord(
            stage=name, status=STATUS_SKIPPED, duration_ms=None,
            started_offset_ms=self._offset_ms(),
            detail=_scrub({"reason": reason} if reason else None),
        )
        self._append_stage(record)

    def _append_stage(self, record: StageRecord) -> None:
        with self._lock:
            self.stages.append(record)
        _emit_log("stage_complete", self, **record.to_dict())

    # -- model / provider --------------------------------------------------
    def record_model_call(
        self, *, stage: str, model: str, duration_ms: float,
        input_tokens: Optional[int] = None, output_tokens: Optional[int] = None,
        total_tokens: Optional[int] = None, retry_count: int = 0,
        status: str = STATUS_OK, error_class: Optional[str] = None,
        **detail: Any,
    ) -> None:
        """Record one LLM call. Token counts stay ``None`` when the provider
        did not report them — an unknown count is recorded as unknown, never
        inferred or zero-filled."""
        entry = {
            "stage": stage, "model": model,
            "duration_ms": round(float(duration_ms), 2),
            "input_tokens": input_tokens, "output_tokens": output_tokens,
            "total_tokens": total_tokens, "retry_count": int(retry_count),
            "status": status, "error_class": error_class,
        }
        entry.update(_scrub(detail))
        with self._lock:
            self.model_calls.append(entry)
        _emit_log("model_call", self, **entry)

    def record_provider_call(
        self, *, provider: str, stage: str, duration_ms: float,
        result_count: Optional[int] = None, status: str = STATUS_OK,
        cache: Optional[str] = None, retry_count: int = 0,
        error_class: Optional[str] = None, **detail: Any,
    ) -> None:
        """Record one external-provider call (SEC, FMP, news, FRED, ...)."""
        entry = {
            "provider": provider, "stage": stage,
            "duration_ms": round(float(duration_ms), 2),
            "result_count": result_count, "status": status,
            "cache": cache, "retry_count": int(retry_count),
            "error_class": error_class,
        }
        entry.update(_scrub(detail))
        with self._lock:
            self.provider_calls.append(entry)
        _emit_log("provider_call", self, **entry)

    # -- aggregation -------------------------------------------------------
    def token_totals(self) -> Dict[str, Optional[int]]:
        """Sum token usage across model calls. Returns ``None`` for a field when
        NO call reported it, so 'nothing reported' stays distinct from 'zero'."""
        totals: Dict[str, Optional[int]] = {}
        for key in ("input_tokens", "output_tokens", "total_tokens"):
            values = [c.get(key) for c in self.model_calls
                      if isinstance(c.get(key), int)]
            totals[key] = sum(values) if values else None
        return totals

    def to_dict(self, *, include_stages: bool = True) -> Dict[str, Any]:
        """The additive ``_observability`` response block."""
        payload: Dict[str, Any] = {
            "request_id": self.request_id,
            "total_duration_ms": self.total_duration_ms(),
        }
        payload.update(build_identity())
        if include_stages:
            with self._lock:
                payload["stages"] = [s.to_dict() for s in self.stages]
                payload["model_calls"] = list(self.model_calls)
                payload["provider_calls"] = list(self.provider_calls)
            payload["token_totals"] = self.token_totals()
        return payload


# ── Context propagation ──────────────────────────────────────────────────────

_TRACE: ContextVar[Optional[RequestTrace]] = ContextVar(
    "clearsignal_request_trace", default=None,
)


def start_trace(request_id: Optional[str] = None, *, ticker: str = "",
                route: str = "") -> RequestTrace:
    """Begin a trace and install it as the active one for this context."""
    trace = RequestTrace(request_id, ticker=ticker, route=route)
    _TRACE.set(trace)
    return trace


def current_trace() -> Optional[RequestTrace]:
    try:
        return _TRACE.get()
    except LookupError:  # pragma: no cover - default makes this unreachable
        return None


def set_trace(trace: Optional[RequestTrace]) -> None:
    _TRACE.set(trace)


# Sprint 3B.1 — active synthesis-prompt variant for this request. Carried
# alongside the trace so it crosses the executor boundary with it.
_PROMPT_VARIANT: ContextVar[str] = ContextVar(
    "clearsignal_prompt_variant", default="control",
)


def set_prompt_variant(variant: str) -> None:
    _PROMPT_VARIANT.set(variant or "control")


def current_prompt_variant() -> str:
    try:
        return _PROMPT_VARIANT.get() or "control"
    except LookupError:  # pragma: no cover - default makes this unreachable
        return "control"


def bind(fn: Callable[..., Any], trace: Optional[RequestTrace] = None) -> Callable[..., Any]:
    """Wrap ``fn`` so it sees ``trace`` as the active trace when it runs.

    Needed because ``loop.run_in_executor`` and ``ThreadPoolExecutor.submit``
    do not carry contextvars into the worker thread. The wrapper only sets a
    contextvar — it changes no arguments and no return value.
    """
    bound = trace if trace is not None else current_trace()

    bound_variant = current_prompt_variant()

    def _wrapped(*args: Any, **kwargs: Any) -> Any:
        set_trace(bound)
        set_prompt_variant(bound_variant)
        return fn(*args, **kwargs)

    return _wrapped


# ── Module-level convenience wrappers (no-ops without an active trace) ───────

@contextmanager
def stage(name: str, **detail: Any) -> Iterator[Optional[StageRecord]]:
    """Time a stage on the active trace, or do nothing if none is active.

    Instrumentation must never be the reason a request fails, so a missing
    trace is silently tolerated — that is the normal state in unit tests and
    background jobs.
    """
    trace = current_trace()
    if trace is None:
        yield None
        return
    with trace.stage(name, **detail) as record:
        yield record


def record_stage(name: str, duration_ms: float, *, status: str = STATUS_OK,
                 error_class: Optional[str] = None, **detail: Any) -> None:
    """Append an already-measured stage.

    Used where the work ran in a worker thread (agents, provider fan-out) and
    the caller timed it itself, so a context manager on the parent thread would
    measure the wrong span.
    """
    trace = current_trace()
    if trace is None:
        return
    try:
        record = StageRecord(
            stage=name, status=status,
            duration_ms=round(float(duration_ms), 2),
            started_offset_ms=max(trace._offset_ms() - float(duration_ms), 0.0),
            error_class=error_class, detail=_scrub(detail),
        )
        trace._append_stage(record)
    except Exception:  # pragma: no cover - defensive
        pass


def skip_stage(name: str, reason: str = "") -> None:
    trace = current_trace()
    if trace is not None:
        try:
            trace.skip(name, reason)
        except Exception:  # pragma: no cover - defensive
            pass


def record_model_call(**kwargs: Any) -> None:
    trace = current_trace()
    if trace is not None:
        try:
            trace.record_model_call(**kwargs)
        except Exception:  # pragma: no cover - defensive
            pass


def record_provider_call(**kwargs: Any) -> None:
    trace = current_trace()
    if trace is not None:
        try:
            trace.record_provider_call(**kwargs)
        except Exception:  # pragma: no cover - defensive
            pass


# ── Structured logging ───────────────────────────────────────────────────────

def _emit_log(event: str, trace: Optional[RequestTrace], **fields: Any) -> None:
    """Emit one JSON line. Render captures stdout/stderr per line, so one
    self-contained object per event is what makes these greppable there."""
    try:
        payload: Dict[str, Any] = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "event": event,
        }
        if trace is not None:
            payload["request_id"] = trace.request_id
            if trace.ticker:
                payload["ticker"] = trace.ticker
            if trace.route:
                payload["route"] = trace.route
        payload.update(build_identity())
        for key, value in fields.items():
            if key == "detail" and isinstance(value, dict):
                payload.update(_scrub(value))
            elif _is_safe_key(key):
                payload[key] = value
        logger.info(json.dumps(payload, default=str))
    except Exception:  # pragma: no cover - logging must never raise
        pass


def log_event(event: str, **fields: Any) -> None:
    """Emit a structured event against the active trace."""
    _emit_log(event, current_trace(), **fields)
