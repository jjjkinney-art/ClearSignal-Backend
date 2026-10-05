"""Contract tests for the account-scoped production write smoke."""

from __future__ import annotations

import json

from scripts import launch_research_memory_write_smoke as smoke


def test_write_recall_and_cleanup_pass_without_exposing_token(monkeypatch):
    conversation_id = "private-conversation"
    marker = "cs-write-smoke-test"
    deleted = False

    def fake_request(url: str, *, token: str, method="GET", json_body=None, timeout=20.0):
        nonlocal deleted
        del token, timeout
        if url.endswith("/research/conversations") and method == "POST":
            return 201, {"id": conversation_id}
        if url.endswith("/messages") and method == "POST":
            return 201, {"role": "user", "text": json_body["text"]}
        if url.endswith(f"/{conversation_id}") and method == "DELETE":
            deleted = True
            return 200, {"deleted": True, "conversation_id": conversation_id}
        if url.endswith(f"/{conversation_id}"):
            if deleted:
                return 404, None
            return 200, {"id": conversation_id, "messages": [{"text": f"Private memory verification marker {marker}"}]}
        if url.endswith("/research/recall"):
            candidates = [] if deleted else [{"conversation": {"id": conversation_id}}]
            return 200, {"status": "matched" if candidates else "unavailable", "candidates": candidates}
        raise AssertionError(url)

    monkeypatch.setattr(smoke, "_request", fake_request)
    result = smoke.run_smoke(
        backend_url="https://backend.example",
        token="secret.jwt.value",
        marker=marker,
    )
    assert result["passed"] is True
    assert result["check_count"] == 7
    assert result["failed_count"] == 0
    assert result["cleanup_succeeded"] is True
    assert result["shared_ticker_writes"] is False
    assert "secret.jwt.value" not in json.dumps(result)


def test_cleanup_runs_when_recall_verification_fails(monkeypatch):
    calls: list[tuple[str, str]] = []

    def fake_request(url: str, *, token: str, method="GET", json_body=None, timeout=20.0):
        del token, json_body, timeout
        calls.append((method, url))
        if url.endswith("/research/conversations") and method == "POST":
            return 201, {"id": "conv"}
        if url.endswith("/messages"):
            return 201, {"role": "user", "text": "Private memory verification marker marker"}
        if url.endswith("/conv") and method == "GET":
            return 200, {"id": "conv", "messages": [{"text": "Private memory verification marker marker"}]}
        if url.endswith("/research/recall"):
            return 200, {"status": "unavailable", "candidates": []}
        if url.endswith("/conv") and method == "DELETE":
            return 200, {"deleted": True}
        raise AssertionError(url)

    monkeypatch.setattr(smoke, "_request", fake_request)
    result = smoke.run_smoke(
        backend_url="https://backend.example", token="token", marker="marker"
    )
    assert result["passed"] is False
    assert result["cleanup_attempted"] is True
    assert ("DELETE", "https://backend.example/research/conversations/conv") in calls


def test_create_failure_never_attempts_cleanup_without_an_id(monkeypatch):
    monkeypatch.setattr(smoke, "_request", lambda *args, **kwargs: (401, None))
    result = smoke.run_smoke(
        backend_url="https://backend.example", token="expired", marker="marker"
    )
    assert result["passed"] is False
    assert result["cleanup_attempted"] is False
    assert result["check_count"] == 1
