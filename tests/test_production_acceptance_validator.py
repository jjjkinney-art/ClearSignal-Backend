"""Deterministic tests for the production acceptance validator."""
from __future__ import annotations

from tests.validate_production_acceptance import run_acceptance


class FakeClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def request(self, method, path, *, payload=None, token=None):
        self.calls.append((method, path, payload, token))
        return self.responses.pop(0)


HEALTH = {
    "status": "ok",
    "environment": "production",
    "build_commit": "f512bb90ed43",
}


def test_public_gate_passes_then_blocks_without_token():
    client = FakeClient([(200, HEALTH), (401, {"detail": "Authentication required"})])
    results, blocked = run_acceptance(
        client, token=None, expected_commit="f512bb90ed4351db"
    )

    assert blocked is True
    assert all(result.passed for result in results)
    assert [call[1] for call in client.calls] == ["/health", "/ask"]


def test_expected_commit_fails_when_health_omits_build_commit():
    health_without_commit = {"status": "ok", "environment": "production"}
    client = FakeClient([
        (200, health_without_commit),
        (401, {"detail": "Authentication required"}),
    ])

    results, blocked = run_acceptance(
        client, token=None, expected_commit="f512bb90ed43"
    )

    assert blocked is True
    assert any(
        result.name == "expected_build_commit" and not result.passed
        for result in results
    )


def test_authenticated_gate_covers_identity_billing_and_deterministic_ask():
    client = FakeClient([
        (200, HEALTH),
        (401, {"detail": "Authentication required"}),
        (200, {
            "session_active": True,
            "is_authenticated": True,
            "auth_enabled": True,
            "bypass_mode": False,
        }),
        (200, {
            "user_id": "real-user",
            "is_authenticated": True,
            "bypass_mode": False,
        }),
        (200, {"plan": "pro", "entitlements": {"watchlist_limit": 50}}),
        (200, {"routing": {
            "pipeline": "comparative_ranking",
            "detected_tickers": ["NVDA", "AMD"],
        }}),
    ])

    results, blocked = run_acceptance(client, token="secret-token")

    assert blocked is False
    assert all(result.passed for result in results)
    assert [call[1] for call in client.calls] == [
        "/health", "/ask", "/auth/session", "/auth/me", "/billing/status", "/ask"
    ]
    assert all("secret-token" not in result.detail for result in results)


def test_invalid_authenticated_session_fails_closed():
    client = FakeClient([
        (200, HEALTH),
        (401, {}),
        (200, {
            "session_active": True,
            "is_authenticated": False,
            "auth_enabled": True,
            "bypass_mode": False,
        }),
        (401, {}),
        (401, {}),
        (401, {}),
    ])

    results, blocked = run_acceptance(client, token="expired")

    assert blocked is False
    assert any(r.name == "authenticated_session" and not r.passed for r in results)
    assert sum(not r.passed for r in results) >= 4


def test_deep_analysis_is_explicitly_opt_in():
    client = FakeClient([
        (200, HEALTH),
        (401, {}),
        (200, {
            "session_active": True,
            "is_authenticated": True,
            "auth_enabled": True,
            "bypass_mode": False,
        }),
        (200, {
            "user_id": "real-user",
            "is_authenticated": True,
            "bypass_mode": False,
        }),
        (200, {"plan": "free", "entitlements": {}}),
        (200, {"routing": {
            "pipeline": "comparative_ranking",
            "detected_tickers": ["NVDA", "AMD"],
        }}),
        (200, {"company": "Apple Inc.", "investment_thesis": {}}),
    ])

    results, _ = run_acceptance(
        client, token="valid", include_analysis=True
    )

    assert all(result.passed for result in results)
    assert client.calls[-1][1] == "/analyze"
