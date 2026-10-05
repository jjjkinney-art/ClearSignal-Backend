"""Tests for the non-mutating production launch smoke harness."""

from __future__ import annotations

import json

from scripts import launch_read_smoke as smoke


def _successful_request(
    url: str,
    *,
    token: str | None = None,
    method: str = "GET",
    json_body=None,
    timeout: float = 20.0,
):
    del method, json_body, timeout
    if url.endswith("/health"):
        return 200, {}, {"status": "ok", "service": "clearsignal-backend"}
    if url.endswith("/readyz"):
        return 200, {}, {"ready": True, "db": "connected"}
    if url.endswith("/version"):
        return 200, {}, {"schema_version": "6-matrix", "build_commit": "abc123"}
    if "/intelligence" in url or "/history" in url:
        return 200, {"content-type": "text/html"}, None
    if token is None:
        return 401, {}, None
    if url.endswith("/auth/session"):
        return 200, {}, {
            "session_active": True,
            "is_authenticated": True,
            "auth_enabled": True,
            "bypass_mode": False,
        }
    if url.endswith("/auth/me"):
        return 200, {}, {
            "is_authenticated": True,
            "user_id": "private-user",
            "bypass_mode": False,
        }
    if "/research/conversations" in url or "/research/notices" in url:
        return 200, {}, []
    if url.endswith("/research/personalization"):
        return 200, {}, {"enabled": True}
    if url.endswith("/research/recall"):
        return 200, {}, {"status": "unavailable", "candidates": []}
    if url.endswith("/research/export"):
        return 200, {
            "cache-control": "private, no-store",
            "content-disposition": (
                'attachment; filename="clearsignal-research-memory.json"'
            ),
        }, {"conversation_count": 0}
    raise AssertionError(f"Unexpected smoke URL: {url}")


def test_full_smoke_contract_passes_without_exposing_token(monkeypatch):
    token = "secret.jwt.value"
    monkeypatch.setattr(smoke, "_request", _successful_request)

    result = smoke.run_smoke(
        backend_url="https://backend.example",
        frontend_url="https://frontend.example",
        token=token,
    )

    assert result["passed"] is True
    assert result["non_mutating"] is True
    assert result["check_count"] == 16
    assert result["passed_count"] == 16
    assert result["failed_count"] == 0
    assert token not in json.dumps(result)


def test_missing_token_fails_closed_but_public_checks_still_run(monkeypatch):
    monkeypatch.setattr(smoke, "_request", _successful_request)

    result = smoke.run_smoke(
        backend_url="https://backend.example",
        frontend_url="https://frontend.example",
        token=None,
    )

    assert result["passed"] is False
    assert result["check_count"] == 10
    assert result["passed_count"] == 9
    assert result["checks"][-1]["name"] == "authenticated_token_present"
    assert result["checks"][-1]["detail"] == (
        "CLEARSIGNAL_SMOKE_ACCESS_TOKEN_missing"
    )


def test_public_only_mode_never_requests_authenticated_surfaces(monkeypatch):
    calls: list[tuple[str, str | None]] = []

    def recording_request(url: str, **kwargs):
        calls.append((url, kwargs.get("token")))
        return _successful_request(url, **kwargs)

    monkeypatch.setattr(smoke, "_request", recording_request)
    result = smoke.run_smoke(
        backend_url="https://backend.example/",
        frontend_url="https://frontend.example/",
        token="must-not-be-used",
        include_authenticated=False,
    )

    assert result["passed"] is True
    assert result["check_count"] == 9
    assert all(token is None for _url, token in calls)


def test_export_without_private_no_store_fails(monkeypatch):
    def unsafe_export(url: str, **kwargs):
        status, headers, payload = _successful_request(url, **kwargs)
        if url.endswith("/research/export") and kwargs.get("token"):
            headers = {"content-disposition": 'attachment; filename="x.json"'}
        return status, headers, payload

    monkeypatch.setattr(smoke, "_request", unsafe_export)
    result = smoke.run_smoke(
        backend_url="https://backend.example",
        frontend_url="https://frontend.example",
        token="secret.jwt.value",
    )

    assert result["passed"] is False
    failed = [check for check in result["checks"] if not check["passed"]]
    assert failed == [{
        "name": "private_export_read",
        "passed": False,
        "status": 200,
        "detail": "private_export_contract_mismatch",
    }]
