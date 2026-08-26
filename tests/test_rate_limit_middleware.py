"""Sprint 4B identity-aware and expensive-route rate-limit regressions."""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from starlette.requests import Request
from starlette.responses import Response

from app.middleware.auth_middleware import AuthMiddleware
from app.security.rate_limit import rate_limiter


def _request(path="/analyze", method="POST", ip="203.0.113.7") -> Request:
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
        "headers": [(b"x-forwarded-for", ip.encode())],
        "client": ("10.0.0.1", 1234),
        "server": ("test", 443),
    }
    return Request(scope, receive)


async def _ok(_request):
    return Response("ok")


@pytest.fixture(autouse=True)
def _limits(monkeypatch):
    from app.config import settings

    rate_limiter.reset()
    monkeypatch.setattr(settings, "rate_limit_enabled", True, raising=False)
    monkeypatch.setattr(settings, "rate_limit_window_s", 60, raising=False)
    monkeypatch.setattr(settings, "rate_limit_per_user_per_min", 100, raising=False)
    monkeypatch.setattr(settings, "rate_limit_expensive_per_ip_per_min", 1, raising=False)
    monkeypatch.setattr(settings, "rate_limit_expensive_per_user_per_min", 100, raising=False)
    monkeypatch.setattr(settings, "rate_limit_trusted_proxy_hops", 1, raising=False)
    yield settings
    rate_limiter.reset()


async def _dispatch(monkeypatch, request, user_id="user-a"):
    async def identity(_request):
        return user_id, user_id, True

    monkeypatch.setattr("app.middleware.auth_middleware._resolve_identity", identity)
    async def local_identity(_request):
        return user_id

    monkeypatch.setattr(
        "app.middleware.auth_middleware._resolve_local_user_id", local_identity
    )
    middleware = AuthMiddleware(app=SimpleNamespace())
    return await middleware.dispatch(request, _ok)


class TestIdentityAwareLimits:
    async def test_expensive_ip_limit_returns_429_and_retry_after(self, monkeypatch):
        assert (await _dispatch(monkeypatch, _request(), "user-a")).status_code == 200
        response = await _dispatch(monkeypatch, _request(), "user-b")
        assert response.status_code == 429
        assert int(response.headers["Retry-After"]) >= 1

    async def test_caller_prepended_forwarded_ip_cannot_bypass(self, monkeypatch):
        first = _request(ip="198.51.100.1, 203.0.113.7")
        second = _request(ip="198.51.100.2, 203.0.113.7")
        assert (await _dispatch(monkeypatch, first, "user-a")).status_code == 200
        assert (await _dispatch(monkeypatch, second, "user-b")).status_code == 429

    async def test_expensive_user_limit_spans_ips(self, monkeypatch, _limits):
        _limits.rate_limit_expensive_per_ip_per_min = 100
        _limits.rate_limit_expensive_per_user_per_min = 1
        assert (await _dispatch(monkeypatch, _request(ip="203.0.113.1"))).status_code == 200
        assert (await _dispatch(monkeypatch, _request(ip="203.0.113.2"))).status_code == 429

    async def test_non_expensive_route_uses_global_user_budget(self, monkeypatch, _limits):
        _limits.rate_limit_per_user_per_min = 1
        request = _request(path="/watchlist", method="GET")
        assert (await _dispatch(monkeypatch, request)).status_code == 200
        assert (await _dispatch(monkeypatch, _request(path="/watchlist", method="GET"))).status_code == 429

    @pytest.mark.parametrize("path", ["/health", "/billing/webhook"])
    async def test_operational_routes_are_exempt(self, monkeypatch, path):
        for _ in range(3):
            response = await _dispatch(monkeypatch, _request(path=path))
            assert response.status_code == 200

    async def test_options_is_exempt(self, monkeypatch):
        for _ in range(3):
            response = await _dispatch(monkeypatch, _request(method="OPTIONS"))
            assert response.status_code == 200

    async def test_disabled_limits_do_not_consume_or_block(self, monkeypatch, _limits):
        _limits.rate_limit_enabled = False
        for _ in range(3):
            assert (await _dispatch(monkeypatch, _request())).status_code == 200
