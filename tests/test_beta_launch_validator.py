"""Deterministic tests for the controlled-beta launch gate."""
from __future__ import annotations

from tests.validate_beta_launch import run_beta_readiness


class FakeClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def request(self, method, path, *, payload=None, token=None):
        self.calls.append((method, path, payload, token))
        return self.responses.pop(0)


HEALTH = {"status": "ok", "environment": "production", "build_commit": "abc123"}
SESSION = {
    "session_active": True,
    "is_authenticated": True,
    "auth_enabled": True,
    "bypass_mode": False,
}
ME = {"user_id": "beta-user", "is_authenticated": True, "bypass_mode": False}
ASK = {"routing": {"pipeline": "comparative_ranking", "detected_tickers": ["NVDA", "AMD"]}}


def _base_responses():
    return [
        (200, HEALTH),
        (401, {}),
        (200, SESSION),
        (200, ME),
        (200, {"plan": "free", "entitlements": {}}),
        (200, ASK),
    ]


def test_free_shadow_beta_passes():
    client = FakeClient(_base_responses() + [
        (200, {"safe_state": True, "billing_live_ready": False}),
        (200, {
            "status": "ok",
            "db_available": True,
            "effective_enabled": False,
            "loop_shadow": True,
            "delivery": {"duplicate_total": 0},
        }),
    ])

    results, blocked = run_beta_readiness(
        client, token="beta-secret", admin_token="admin-secret"
    )

    assert blocked is False
    assert all(result.passed for result in results)
    assert [call[1] for call in client.calls[-2:]] == [
        "/admin/billing-status", "/admin/loop/status"
    ]
    assert all("secret" not in result.detail for result in results)
    assert [call[3] for call in client.calls[-2:]] == [
        "admin-secret", "admin-secret"
    ]
    assert all(call[3] == "beta-secret" for call in client.calls[2:-2])


def test_paid_beta_requires_live_billing():
    client = FakeClient(_base_responses() + [
        (200, {"safe_state": True, "billing_live_ready": False}),
        (200, {
            "status": "ok", "db_available": True,
            "effective_enabled": False, "loop_shadow": True,
            "delivery": {"duplicate_total": 0},
        }),
    ])

    results, _ = run_beta_readiness(
        client,
        token="beta-secret",
        admin_token="admin-secret",
        paid_beta=True,
    )

    assert any(r.name == "billing_mode" and not r.passed for r in results)


def test_duplicate_delivery_is_stop_ship():
    client = FakeClient(_base_responses() + [
        (200, {"safe_state": True}),
        (200, {
            "status": "ok", "db_available": True,
            "effective_enabled": True, "loop_shadow": False,
            "delivery": {"duplicate_total": 1},
        }),
    ])

    results, _ = run_beta_readiness(
        client,
        token="beta-secret",
        admin_token="admin-secret",
        allow_live_delivery=True,
    )

    assert any(
        r.name == "zero_duplicate_delivery" and not r.passed for r in results
    )


def test_missing_token_stops_before_admin_snapshots():
    client = FakeClient([(200, HEALTH), (401, {})])

    results, blocked = run_beta_readiness(client, token=None)

    assert blocked is True
    assert all(result.passed for result in results)
    assert [call[1] for call in client.calls] == ["/health", "/ask"]


def test_missing_admin_token_stops_after_product_acceptance():
    client = FakeClient(_base_responses())

    results, blocked = run_beta_readiness(
        client, token="beta-secret", admin_token=None
    )

    assert blocked is True
    assert all(result.passed for result in results)
    assert [call[1] for call in client.calls] == [
        "/health", "/ask", "/auth/session", "/auth/me",
        "/billing/status", "/ask",
    ]
    assert all(not call[1].startswith("/admin/") for call in client.calls)
