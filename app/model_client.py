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

    def call(self, prompt: str, system_prompt: str = "", request_id: Optional[str] = None) -> str:
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
                "OpenAI client is not available. "
                "Ensure openai>=1.0 is installed and OPENAI_API_KEY is set."
            )

        messages: List[Dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        for attempt in range(1, self.max_retries + 1):
            try:
                start_time = time.time()
                response = self._client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=self.temperature,
                    max_tokens=self.max_tokens,
                )
                duration = time.time() - start_time
                content = response.choices[0].message.content or ""
                logger.info(
                    json.dumps({
                        "event": "model_call_success",
                        "request_id": request_id,
                        "attempt": attempt,
                        "duration_ms": int(duration * 1000),
                    })
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
                # Retry on server-side API errors (5xx); raise immediately on client errors (4xx)
                if hasattr(exc, "status_code") and exc.status_code is not None and exc.status_code < 500:
                    logger.error(
                        json.dumps({
                            "event": "model_call_client_error",
                            "request_id": request_id,
                            "attempt": attempt,
                            "status_code": exc.status_code,
                            "error": str(exc),
                        })
                    )
                    raise
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


# Instantiate a default client using environment settings.  This instance
# can be imported throughout the codebase.
model_client = ModelClient(
    api_key=settings.openai_api_key,
    model=settings.openai_model,
    temperature=settings.temperature,
    max_tokens=settings.max_tokens,
    timeout=settings.model_timeout,
    max_retries=settings.model_max_retries,
    backoff_factor=settings.model_backoff_factor,
)
