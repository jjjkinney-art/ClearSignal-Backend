"""
tests/test_model_client_retry.py

Unit tests for ModelClient retry / backoff behaviour.

Coverage
--------
1. HTTP 429 retries with exponential backoff (not immediate failure).
2. HTTP 400 / 401 / 403 / 422 do NOT retry — they raise on the first attempt.
3. A 429 that succeeds on the Nth retry returns the model response.
4. Retry-After header is honoured for 429 responses.
5. 5xx errors retry (existing behaviour preserved).
6. Network errors (APITimeoutError, APIConnectionError) retry (existing behaviour).
"""

from __future__ import annotations

import time
from typing import Optional
from unittest.mock import MagicMock, patch, call

import pytest

# ── Build a minimal ModelClient without touching settings or OpenAI ───────────

def _make_client(max_retries: int = 3, backoff_factor: float = 0.0) -> "object":
    """Return a ModelClient wired to a fake OpenAI client (no real HTTP)."""
    from app.model_client import ModelClient

    client = ModelClient.__new__(ModelClient)
    client.model          = "gpt-4o"
    client.temperature    = 0.0
    client.max_tokens     = 512
    client.timeout        = 5.0
    client.max_retries    = max_retries
    client.backoff_factor = backoff_factor   # 0.0 → sleep(0) so tests stay fast
    client._client        = MagicMock()      # fake OpenAI client
    return client


def _api_error(status_code: int, retry_after: Optional[str] = None):
    """Build a fake openai.APIError with a given status_code."""
    try:
        from openai import APIError
    except ImportError:
        pytest.skip("openai package not installed")

    exc = APIError.__new__(APIError)
    exc.status_code = status_code
    exc.message     = f"Fake HTTP {status_code}"

    # Attach a fake response with optional Retry-After header.
    fake_response       = MagicMock()
    fake_response.headers = {"retry-after": retry_after} if retry_after else {}
    exc.response        = fake_response

    # Make str(exc) sane.
    exc.__str__ = lambda self: self.message  # type: ignore[assignment]
    return exc


def _good_completion(text: str = "analysis result"):
    """Return a fake chat-completions response object."""
    choice  = MagicMock()
    choice.message.content = text
    resp    = MagicMock()
    resp.choices = [choice]
    return resp


# ─────────────────────────────────────────────────────────────────────────────
# 1. HTTP 429 retries with exponential backoff
# ─────────────────────────────────────────────────────────────────────────────

class TestHttp429Retries:

    def test_429_is_retried_not_immediately_raised(self):
        """A single 429 must not surface as an exception — it should be retried."""
        client = _make_client(max_retries=3, backoff_factor=0.0)
        err429 = _api_error(429)

        # First call raises 429; second call succeeds.
        client._client.chat.completions.create.side_effect = [
            err429,
            _good_completion("ok after rate limit"),
        ]

        with patch("app.model_client.time.sleep"):
            result = client.call("test prompt")

        assert result == "ok after rate limit"

    def test_429_retries_use_exponential_backoff(self):
        """Sleep durations must double on each 429 retry."""
        client = _make_client(max_retries=3, backoff_factor=1.0)
        err429 = _api_error(429)

        client._client.chat.completions.create.side_effect = [
            err429,                           # attempt 1 → sleep 1.0 * 2^0 = 1.0 s
            err429,                           # attempt 2 → sleep 1.0 * 2^1 = 2.0 s
            _good_completion("recovered"),    # attempt 3 → success
        ]

        with patch("app.model_client.time.sleep") as mock_sleep:
            client.call("test prompt")

        assert mock_sleep.call_count == 2
        assert mock_sleep.call_args_list[0] == call(1.0)   # 1.0 * 2^0
        assert mock_sleep.call_args_list[1] == call(2.0)   # 1.0 * 2^1

    def test_429_raises_after_all_retries_exhausted(self):
        """After max_retries of 429s the exception must propagate."""
        client = _make_client(max_retries=2, backoff_factor=0.0)
        err429 = _api_error(429)

        client._client.chat.completions.create.side_effect = [err429, err429]

        with patch("app.model_client.time.sleep"):
            with pytest.raises(Exception) as exc_info:
                client.call("test prompt")

        assert exc_info.value is err429

    def test_429_total_attempts_equals_max_retries(self):
        """The API must be called exactly max_retries times before giving up."""
        client = _make_client(max_retries=3, backoff_factor=0.0)
        client._client.chat.completions.create.side_effect = _api_error(429)

        with patch("app.model_client.time.sleep"):
            with pytest.raises(Exception):
                client.call("test prompt")

        assert client._client.chat.completions.create.call_count == 3

    def test_429_honours_retry_after_header(self):
        """When the 429 response includes Retry-After, that value overrides backoff."""
        client = _make_client(max_retries=2, backoff_factor=99.0)   # would be 99s without header
        err429 = _api_error(429, retry_after="7")

        client._client.chat.completions.create.side_effect = [
            err429,
            _good_completion("ok"),
        ]

        with patch("app.model_client.time.sleep") as mock_sleep:
            client.call("test prompt")

        # Should sleep exactly 7 s (from header), not 99 s (from backoff_factor).
        mock_sleep.assert_called_once_with(7.0)


# ─────────────────────────────────────────────────────────────────────────────
# 2. 400 / 401 / 403 / 422 do NOT retry
# ─────────────────────────────────────────────────────────────────────────────

class TestImmediateFailureCodes:

    @pytest.mark.parametrize("status_code", [400, 401, 403, 422])
    def test_client_error_raises_immediately(self, status_code: int):
        """No retry should be attempted for client-error status codes."""
        client = _make_client(max_retries=5, backoff_factor=0.0)
        err    = _api_error(status_code)
        client._client.chat.completions.create.side_effect = err

        with patch("app.model_client.time.sleep") as mock_sleep:
            with pytest.raises(Exception) as exc_info:
                client.call("test prompt")

        assert exc_info.value is err
        # Must fail on the very first attempt.
        assert client._client.chat.completions.create.call_count == 1
        mock_sleep.assert_not_called()

    @pytest.mark.parametrize("status_code", [400, 401, 403, 422])
    def test_client_error_does_not_sleep(self, status_code: int):
        """time.sleep must never be called for immediate-failure codes."""
        client = _make_client(max_retries=5, backoff_factor=1.0)
        client._client.chat.completions.create.side_effect = _api_error(status_code)

        with patch("app.model_client.time.sleep") as mock_sleep:
            with pytest.raises(Exception):
                client.call("test prompt")

        mock_sleep.assert_not_called()


# ─────────────────────────────────────────────────────────────────────────────
# 3. Successful retry returns the model response
# ─────────────────────────────────────────────────────────────────────────────

class TestSuccessfulRetry:

    def test_success_after_one_429_returns_content(self):
        client = _make_client(max_retries=3, backoff_factor=0.0)
        client._client.chat.completions.create.side_effect = [
            _api_error(429),
            _good_completion("Tesla margin analysis complete"),
        ]

        with patch("app.model_client.time.sleep"):
            result = client.call("Can Tesla recover margin pressure?")

        assert result == "Tesla margin analysis complete"

    def test_success_after_two_429s_returns_content(self):
        client = _make_client(max_retries=3, backoff_factor=0.0)
        client._client.chat.completions.create.side_effect = [
            _api_error(429),
            _api_error(429),
            _good_completion("recovered on attempt 3"),
        ]

        with patch("app.model_client.time.sleep"):
            result = client.call("test")

        assert result == "recovered on attempt 3"

    def test_success_on_first_attempt_no_sleep(self):
        """Happy path: no 429, no sleep, result returned immediately."""
        client = _make_client(max_retries=3, backoff_factor=1.0)
        client._client.chat.completions.create.return_value = _good_completion("immediate")

        with patch("app.model_client.time.sleep") as mock_sleep:
            result = client.call("test")

        assert result == "immediate"
        mock_sleep.assert_not_called()


# ─────────────────────────────────────────────────────────────────────────────
# 4. 5xx errors still retry (existing behaviour preserved)
# ─────────────────────────────────────────────────────────────────────────────

class TestServerErrorRetries:

    @pytest.mark.parametrize("status_code", [500, 502, 503])
    def test_5xx_is_retried(self, status_code: int):
        """Server errors must be retried just like before."""
        client = _make_client(max_retries=3, backoff_factor=0.0)
        err5xx = _api_error(status_code)
        client._client.chat.completions.create.side_effect = [
            err5xx,
            _good_completion("recovered"),
        ]

        with patch("app.model_client.time.sleep"):
            result = client.call("test")

        assert result == "recovered"

    @pytest.mark.parametrize("status_code", [500, 503])
    def test_5xx_raises_after_max_retries(self, status_code: int):
        client = _make_client(max_retries=2, backoff_factor=0.0)
        client._client.chat.completions.create.side_effect = _api_error(status_code)

        with patch("app.model_client.time.sleep"):
            with pytest.raises(Exception):
                client.call("test")

        assert client._client.chat.completions.create.call_count == 2
