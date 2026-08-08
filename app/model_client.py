"""
Centralized client for making OpenAI model calls with retry and timeout handling.

This module encapsulates all interactions with the OpenAI API using the v1+
client interface.  It provides a clean interface for sending messages and
receiving text responses, handling API key configuration, request metadata,
timeouts, retries with exponential backoff, and error normalization.

By routing all model calls through this client, the rest of the codebase
remains free of direct OpenAI dependencies and can be more easily
tested or swapped out for a different provider.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Any, List, Dict, Optional

try:
    from openai import OpenAI, APITimeoutError, APIConnectionError, APIError
    _OPENAI_AVAILABLE = True
except ImportError:
    OpenAI = None  # type: ignore
    APITimeoutError = Exception  # type: ignore
    APIConnectionError = Exception  # type: ignore
    APIError = Exception  # type: ignore
    _OPENAI_AVAILABLE = False


def _observe_model_call(**kwargs: Any) -> None:
    """Forward a model-call observation to the active request trace.

    Imported lazily and failure-tolerant: this module is imported at process
    start by code paths that have no request context, and instrumentation must
    never be the reason a model call fails.
    """
    try:
        from .observability import record_model_call
        record_model_call(**kwargs)
    except Exception:  # pragma: no cover - defensive
        pass

from .config import settings

logger = logging.getLogger(__name__)


class ModelClient:
    """Wrapper around the OpenAI chat completions API with retries and logging."""

    def __init__(
        self,
        api_key: str,
        model: str,
        temperature: float,
        max_tokens: int,
        timeout: float = 30.0,
        max_retries: int = 3,
        backoff_factor: float = 0.5,
    ) -> None:
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff_factor = backoff_factor
        self._client: Optional[Any] = None
        if _OPENAI_AVAILABLE and api_key:
            self._client = OpenAI(api_key=api_key, timeout=timeout)
        else:
            if not _OPENAI_AVAILABLE:
                print(
                    "[MODEL_CLIENT] WARNING: openai package is not installed — "
                    "ModelClient._client=None; all LLM calls will fail."
                )
                logger.warning("openai package not installed — ModelClient unavailable")
            else:
                # openai is installed but no key was supplied at construction time.
                # The most likely cause is OPENAI_API_KEY not set in the environment.
                print(
                    "[MODEL_CLIENT] CRITICAL: OPENAI_API_KEY is not set or empty — "
                    "ModelClient._client=None.  Every call to /api/ask will raise "
                    "RuntimeError until OPENAI_API_KEY is added to the environment."
                )
                logger.warning(
                    "OPENAI_API_KEY is empty — ModelClient._client is None; "
                    "all LLM calls will raise RuntimeError"
                )

    @staticmethod
    def _usage(response: Any) -> Dict[str, Optional[int]]:
        """Token usage from a provider response, or all-None when the provider
        did not report it (Sprint 3A).  Never fabricates a count — an unknown
        usage figure is more useful than a wrong one."""
        usage = getattr(response, "usage", None)
        if usage is None:
            return {"input_tokens": None, "output_tokens": None, "total_tokens": None}

        def _int(*names: str) -> Optional[int]:
            for name in names:
                value = getattr(usage, name, None)
                if isinstance(value, int):
                    return value
            return None

        return {
            "input_tokens": _int("prompt_tokens", "input_tokens"),
            "output_tokens": _int("completion_tokens", "output_tokens"),
            "total_tokens": _int("total_tokens"),
        }

    def call(self, prompt: str, system_prompt: str = "", request_id: Optional[str] = None,
             stage: str = "") -> str:
        """Call the model, recording a failure observation if it raises.

        Sprint 3A wrapper around :meth:`_call_impl`.  Success is recorded inside
        the retry loop where token usage is available; this only has to catch
        the terminal failure, and it re-raises untouched so retry and error
        semantics are exactly as before.
        """
        started = time.monotonic()
        try:
            return self._call_impl(prompt, system_prompt, request_id, stage)
        except BaseException as exc:  # noqa: BLE001 - re-raised immediately
            name = type(exc).__name__
            _observe_model_call(
                stage=stage or "model_call", model=self.model,
                duration_ms=(time.monotonic() - started) * 1000.0,
                retry_count=max(self.max_retries - 1, 0),
                status="timeout" if "timeout" in name.lower() else "error",
                error_class=name,
                input_tokens=None, output_tokens=None, total_tokens=None,
            )
            raise

    def _call_impl(self, prompt: str, system_prompt: str = "",
                   request_id: Optional[str] = None, stage: str = "") -> str:
        """Call the OpenAI chat completions API and return the response text.

        Parameters
        ----------
        prompt : str
            The user prompt to send to the model.
        system_prompt : str, optional
            An optional system-level prompt to prefix the conversation.
        request_id : str, optional
            Identifier for logging correlation.  If not provided, a new
            UUID will be generated.

        Returns
        -------
        str
            The content of the first choice returned by the API.

        Raises
        ------
        RuntimeError
            If the openai package is not installed or no API key was provided.
        Exception
            If the API call fails after all retries.
        """
        if request_id is None:
            request_id = str(uuid.uuid4())

        if self._client is None:
            raise RuntimeError(
                "OPENAI_API_KEY IS MISSING OR EMPTY — cannot make model call. "
                "Set OPENAI_API_KEY in the environment or .env file and restart "
                "the server.  Check [STARTUP] and [MODEL_CLIENT] log lines for "
                "the key-presence status recorded at startup."
            )

        messages: List[Dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        for attempt in range(1, self.max_retries + 1):
            try:
                # Monotonic: wall-clock jumps (NTP, DST) must not corrupt a
                # latency measurement (Sprint 3A).
                start_time = time.monotonic()
                response = self._client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=self.temperature,
                    max_tokens=self.max_tokens,
                )
                duration = time.monotonic() - start_time
                content = response.choices[0].message.content or ""
                usage = self._usage(response)
                logger.info(
                    json.dumps({
                        "event": "model_call_success",
                        "request_id": request_id,
                        "attempt": attempt,
                        "duration_ms": int(duration * 1000),
                    })
                )
                _observe_model_call(
                    stage=stage or "model_call", model=self.model,
                    duration_ms=duration * 1000.0, retry_count=attempt - 1,
                    status="ok", **usage,
                )
                return content
            except (APITimeoutError, APIConnectionError) as exc:
                logger.warning(
                    json.dumps({
                        "event": "model_call_retry",
                        "request_id": request_id,
                        "attempt": attempt,
                        "error": str(exc),
                    })
                )
                if attempt == self.max_retries:
                    raise
                time.sleep(self.backoff_factor * (2 ** (attempt - 1)))
            except APIError as exc:
                status_code = getattr(exc, "status_code", None)

                # ── HTTP 429 — rate-limited: retry with exponential backoff ──────
                # 429 is a transient server-side signal ("slow down"), not a
                # permanent client misconfiguration.  Honour Retry-After when
                # the response includes it; otherwise use the standard backoff.
                if status_code == 429:
                    # Extract Retry-After seconds if the header is present.
                    retry_after: Optional[float] = None
                    _headers = getattr(exc, "response", None)
                    if _headers is not None:
                        _ra = getattr(_headers, "headers", {}).get("retry-after")
                        if _ra is not None:
                            try:
                                retry_after = float(_ra)
                            except (ValueError, TypeError):
                                pass

                    sleep_secs = (
                        retry_after
                        if retry_after is not None
                        else self.backoff_factor * (2 ** (attempt - 1))
                    )
                    logger.warning(
                        json.dumps({
                            "event": "model_call_rate_limited",
                            "request_id": request_id,
                            "attempt": attempt,
                            "retry_after_secs": sleep_secs,
                            "error": str(exc),
                        })
                    )
                    if attempt == self.max_retries:
                        raise
                    time.sleep(sleep_secs)
                    continue

                # ── True client/config errors: fail immediately, no retry ────────
                # 400 Bad Request, 401 Unauthorized, 403 Forbidden, 422 Unprocessable.
                # Retrying these wastes quota and time — the request itself is wrong.
                _NO_RETRY_CODES = {400, 401, 403, 422}
                if status_code is not None and status_code in _NO_RETRY_CODES:
                    logger.error(
                        json.dumps({
                            "event": "model_call_client_error",
                            "request_id": request_id,
                            "attempt": attempt,
                            "status_code": status_code,
                            "error": str(exc),
                        })
                    )
                    raise

                # ── All other APIErrors (5xx, unknown): retry with backoff ────────
                logger.warning(
                    json.dumps({
                        "event": "model_call_retry",
                        "request_id": request_id,
                        "attempt": attempt,
                        "status_code": status_code,
                        "error": str(exc),
                    })
                )
                if attempt == self.max_retries:
                    raise
                time.sleep(self.backoff_factor * (2 ** (attempt - 1)))
            except Exception as exc:
                logger.error(
                    json.dumps({
                        "event": "model_call_failure",
                        "request_id": request_id,
                        "attempt": attempt,
                        "error": str(exc),
                    })
                )
                raise


# Instantiate the specialist-agent client.  This instance is shared by the 5
# parallel investment agents (valuation, macro, risk, market, quality) and the
# Q-First question-answerer agent.  Uses:
#   agent_model   (default: gpt-4o-mini)  — faster than gpt-4o; keeps wall-time low
#   agent_timeout (default: 15 s)         — investment agents generate compact
#                                           structured outputs (~200-500 tokens);
#                                           gpt-4o-mini finishes in 2-15 s under
#                                           normal load.  A 15 s cap guarantees
#                                           agent wall time never exceeds 15 s.
#   agent_max_retries (default: 1)        — no retry; retrying at 15 s pushes
#                                           total pipeline over Render's 61 s
#                                           Nginx ceiling.  Timeout → safe default.
# Pipeline budget: evidence(10s) + agents(15s) + synthesis(30s) + post(3s) = 58s.
model_client = ModelClient(
    api_key=settings.openai_api_key,
    model=settings.agent_model,
    temperature=settings.temperature,
    max_tokens=settings.max_tokens,
    timeout=getattr(settings, "agent_timeout", 15.0),
    max_retries=getattr(settings, "agent_max_retries", 1),
    backoff_factor=settings.model_backoff_factor,
)

# Dedicated client for the thesis synthesiser.  Uses settings.synthesis_model
# (default: gpt-4o-mini; override via SYNTHESIS_MODEL env var).
# synthesis_timeout=55s: on Render Starter (120s proxy_read_timeout), synthesis
# can safely run up to 55s.  1536 tokens × 45 tok/s (typical) = 42s — fits well.
# synthesis_max_tokens=1536: full field budget; all 22+ InvestmentThesis fields.
# synthesis_max_retries=1: a retry adds 55s — on timeout return fallback instead.
# Python-side wall cap (_SYNTHESIS_WALL_CAP_S=56) fires 1s after httpx timeout.
synthesis_client = ModelClient(
    api_key=settings.openai_api_key,
    model=settings.synthesis_model,
    temperature=settings.temperature,
    max_tokens=settings.synthesis_max_tokens,
    timeout=settings.synthesis_timeout,
    max_retries=settings.synthesis_max_retries,
    backoff_factor=settings.model_backoff_factor,
)
