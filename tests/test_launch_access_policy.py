"""Sprint 4C production access-boundary regressions."""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from starlette.requests import Request
from starlette.responses import Response

from app.middleware.auth_middleware import AuthMiddleware
from app.security.rate_limit import rate_limiter


SYSTEM_USER = "00000000-0000-0000-0000-000000000001"
ADMIN_USER = "11111111-1111-1111-1111-111111111111"
MEMBER_USER = "22222222-2222-2222-2222-222222222222"


def _request(path: str, method: str = "GET") -> Request:
    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": method,
        "scheme": "https",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "headers": [(b"x-forwarded-for", b"203.0.113.7")],
        "client": ("10.0.0.1", 1234),
        "server": ("test", 443),
    }
    return Request(scope, receive)


async def _ok(_request):
    return Response("ok")


async def _dispatch(monkeypatch, request, user_id, authenticated=True):
    async def identity(_request):
        if user_id is None:
            return None, None, False
        return user_id, user_id, authenticated

    async def local_identity(_request):
        return user_id

    monkeypatch.setattr("app.middleware.auth_middleware._resolve_identity", identity)
    monkeypatch.setattr(
        "app.middleware.auth_middleware._resolve_local_user_id", local_identity
    )
    middleware = AuthMiddleware(app=SimpleNamespace())
    return await middleware.dispatch(request, _ok)


@pytest.fixture(autouse=True)
def _policy_settings(monkeypatch):
    from app.config import settings

    rate_limiter.reset()
    monkeypatch.setattr(settings, "auth_enabled", True, raising=False)
    monkeypatch.setattr(settings, "admin_user_ids", ADMIN_USER, raising=False)
    monkeypatch.setattr(settings, "rate_limit_enabled", True, raising=False)
    monkeypatch.setattr(settings, "rate_limit_per_user_per_min", 1000, raising=False)
    monkeypatch.setattr(settings, "rate_limit_expensive_per_ip_per_min", 1000, raising=False)
    monkeypatch.setattr(settings, "rate_limit_expensive_per_user_per_min", 1000, raising=False)
    monkeypatch.setattr(settings, "rate_limit_admin_per_user_per_min", 1000, raising=False)
    yield settings
    rate_limiter.reset()


@pytest.mark.parametrize("path", ["/admin/auth-status", "/admin/loop/disable"])
async def test_admin_namespace_rejects_unauthenticated(monkeypatch, path):
    response = await _dispatch(monkeypatch, _request(path), None)
    assert response.status_code == 401


@pytest.mark.parametrize(
    ("path", "method"),
    [
        ("/admin/auth-status", "GET"),
        ("/admin/loop/disable", "POST"),
        ("/pipeline/run", "POST"),
        ("/events/process", "POST"),
        ("/events/ingest", "POST"),
    ],
)
async def test_member_cannot_reach_operator_surface(monkeypatch, path, method):
    response = await _dispatch(monkeypatch, _request(path, method), MEMBER_USER)
    assert response.status_code == 403


@pytest.mark.parametrize(
    ("path", "method"),
    [
        ("/admin/auth-status", "GET"),
        ("/admin/loop/disable", "POST"),
        ("/pipeline/run", "POST"),
        ("/events/process", "POST"),
    ],
)
async def test_admin_can_reach_operator_surface(monkeypatch, path, method):
    response = await _dispatch(monkeypatch, _request(path, method), ADMIN_USER)
    assert response.status_code == 200


async def test_analyze_requires_authenticated_user(monkeypatch):
    response = await _dispatch(monkeypatch, _request("/analyze", "POST"), None)
    assert response.status_code == 401


async def test_authenticated_member_can_analyze(monkeypatch):
    response = await _dispatch(monkeypatch, _request("/analyze", "POST"), MEMBER_USER)
    assert response.status_code == 200


@pytest.mark.parametrize(
    "path",
    [
        "/alerts",
        "/history",
        "/material-changes",
        "/timeline-events/AAPL",
        "/watchlist/AAPL/snapshots",
        "/ticker/AAPL/evolution",
        "/market/resolve",
    ],
)
async def test_legacy_product_routes_are_not_anonymous(monkeypatch, path):
    response = await _dispatch(monkeypatch, _request(path), None)
    assert response.status_code == 401


@pytest.mark.parametrize(
    ("path", "method"),
    [
        ("/health", "GET"),
        ("/openapi.json", "GET"),
        ("/auth/session", "GET"),
        ("/billing/webhook", "POST"),
        ("/analyze", "OPTIONS"),
    ],
)
async def test_deliberate_public_surface_remains_reachable(monkeypatch, path, method):
    response = await _dispatch(monkeypatch, _request(path, method), None)
    assert response.status_code == 200


async def test_bypass_system_operator_remains_available_locally(monkeypatch, _policy_settings):
    _policy_settings.auth_enabled = False
    response = await _dispatch(
        monkeypatch,
        _request("/admin/auth-status"),
        SYSTEM_USER,
        authenticated=False,
    )
    assert response.status_code == 200


async def test_admin_rate_limit_returns_retry_after(monkeypatch, _policy_settings):
    _policy_settings.rate_limit_admin_per_user_per_min = 1
    first = await _dispatch(monkeypatch, _request("/admin/auth-status"), ADMIN_USER)
    second = await _dispatch(monkeypatch, _request("/admin/auth-status"), ADMIN_USER)
    assert first.status_code == 200
    assert second.status_code == 429
    assert int(second.headers["Retry-After"]) >= 1
