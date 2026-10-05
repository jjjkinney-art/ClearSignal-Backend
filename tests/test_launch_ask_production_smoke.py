"""Contract tests for the provider-backed authenticated /ask smoke."""

from __future__ import annotations

import json

from scripts import launch_ask_production_smoke as smoke


def _response():
    return {
        "company": "AAPL",
        "answer": {"investment_thesis": {"direct_answer": "Risk"}},
        "routing": {
            "detected_ticker": "AAPL",
            "evidence_references": [{"id": "E1"}],
        },
    }


def test_full_ask_persistence_recall_history_and_cleanup(monkeypatch):
    marker = "cs-ask-smoke-test"
    conversation_id = "conversation-1"
    thesis_id = "thesis-1"
    question = (
        "Using the latest available public filings, what is Apple's largest "
        "operating risk to services growth over the next 12 months? "
        f"[ClearSignal smoke marker: {marker}]"
    )
    deleted_conversation = False
    deleted_thesis = False
    ask_response = _response()

    def fake_request(url, *, token, method="GET", json_body=None, timeout=30.0):
        nonlocal deleted_conversation, deleted_thesis
        del token, timeout
        if "/research/history?" in url:
            rows = [] if deleted_thesis else (
                [{"id": thesis_id, "question": question}]
                if any(call == "ask" for call in calls) else []
            )
            return 200, rows
        if url.endswith("/research/conversations") and method == "POST":
            return 201, {"id": conversation_id}
        if url.endswith("/ask"):
            calls.append("ask")
            assert json_body["research_conversation_id"] == conversation_id
            return 200, ask_response
        if url.endswith(f"/research/conversations/{conversation_id}") and method == "GET":
            return 200, {
                "id": conversation_id,
                "messages": [
                    {
                        "role": "user", "text": question,
                        "request_ref": marker,
                    },
                    {
                        "role": "assistant", "request_ref": marker,
                        "displayed_snapshot": {
                            "response_version": 1,
                            "response": ask_response,
                        },
                    },
                ],
            }
        if url.endswith("/research/recall"):
            return 200, {
                "candidates": [{"conversation": {"id": conversation_id}}],
            }
        if url.endswith(f"/research/conversations/{conversation_id}") and method == "DELETE":
            deleted_conversation = True
            return 200, {"deleted": True}
        if url.endswith(f"/research/history/{thesis_id}") and method == "DELETE":
            deleted_thesis = True
            return 200, {"deleted": True}
        raise AssertionError((method, url))

    calls = []
    monkeypatch.setattr(smoke, "_request", fake_request)
    result = smoke.run_smoke(
        backend_url="https://backend.example",
        token="secret.jwt.value",
        marker=marker,
    )
    assert result["passed"] is True
    assert result["failed_count"] == 0
    assert result["provider_calls"] is True
    assert result["provider_call_limit"] == 1
    assert result["shared_ticker_writes"] is False
    assert result["conversation_cleanup_succeeded"] is True
    assert result["history_cleanup_succeeded"] is True
    assert deleted_conversation and deleted_thesis
    assert "secret.jwt.value" not in json.dumps(result)


def test_cleanup_runs_after_invalid_ask_response(monkeypatch):
    marker = "cleanup-test"
    conversation_id = "conversation-1"
    thesis_id = "thesis-1"
    calls = []
    asked = False
    question = (
        "Using the latest available public filings, what is Apple's largest "
        "operating risk to services growth over the next 12 months? "
        f"[ClearSignal smoke marker: {marker}]"
    )

    def fake_request(url, *, token, method="GET", json_body=None, timeout=30.0):
        nonlocal asked
        del token, json_body, timeout
        calls.append((method, url))
        if "/research/history?" in url:
            return 200, ([{"id": thesis_id, "question": question}] if asked else [])
        if url.endswith("/research/conversations") and method == "POST":
            return 201, {"id": conversation_id}
        if url.endswith("/ask"):
            asked = True
            return 200, {"error": "failed"}
        if url.endswith(f"/research/conversations/{conversation_id}") and method == "GET":
            return 200, {"messages": []}
        if url.endswith("/research/recall"):
            return 200, {"candidates": []}
        if url.endswith(f"/research/conversations/{conversation_id}") and method == "DELETE":
            return 200, {"deleted": True}
        if url.endswith(f"/research/history/{thesis_id}") and method == "DELETE":
            return 200, {"deleted": True}
        raise AssertionError((method, url))

    monkeypatch.setattr(smoke, "_request", fake_request)
    result = smoke.run_smoke(
        backend_url="https://backend.example", token="token", marker=marker
    )
    assert result["passed"] is False
    assert ("DELETE", f"https://backend.example/research/conversations/{conversation_id}") in calls
    assert ("DELETE", f"https://backend.example/research/history/{thesis_id}") in calls
    assert result["conversation_cleanup_succeeded"] is True
    assert result["history_cleanup_succeeded"] is True


def test_confirmation_constant_is_explicit():
    assert smoke.CONFIRMATION == "RUN_ONE_REAL_ASK_SMOKE"
