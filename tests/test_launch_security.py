"""
Sprint 0 — public-launch security tests.

Covers the launch blockers:
  * environment-driven CORS allowlist (no wildcard+credentials in production)
  * request size / question-length caps
  * per-IP and per-user rate limits (strictest on /ask)
  * per-user daily quota on /ask
  * /ask auth enforcement + safe local bypass
  * entitlement denial on /ask when enforced
  * /events/ingest and /usage/stats lockdown

These tests drive the real settings + the real security module; they never make
network calls and do not enable Stripe / delivery / rollout flags.
"""
from __future__ import annotations

import importlib

import pytest
from fastapi import HTTPException


# ─────────────────────────────────────────────────────────────────────────────
# CORS allowlist
# ─────────────────────────────────────────────────────────────────────────────

def _cors_options(app):
    """Return the kwargs the CORSMiddleware was constructed with."""
    from starlette.middleware.cors import CORSMiddleware
    for mw in app.user_middleware:
        if mw.cls is CORSMiddleware:
            # starlette exposes constructor kwargs as .kwargs (newer) or .options
            return getattr(mw, "kwargs", None) or getattr(mw, "options", {})
    raise AssertionError("CORSMiddleware not installed")


class TestCORSAllowlist:
    def test_dev_defaults_localhost_with_credentials(self, monkeypatch):
        from app import config, main
        monkeypatch.setattr(config.settings, "app_env", "development", raising=False)
        monkeypatch.setattr(
            config.settings, "cors_allow_origins",
            "http://localhost:3000,http://localhost:5173", raising=False,
        )
        monkeypatch.setattr(config.settings, "cors_allow_credentials", True, raising=False)
        app = main.create_app()
        opts = _cors_options(app)
        assert "http://localhost:3000" in opts["allow_origins"]
        assert "*" not in opts["allow_origins"]
        assert opts["allow_credentials"] is True

    def test_production_strips_wildcard_origin(self, monkeypatch):
        from app import config, main
        monkeypatch.setattr(config.settings, "app_env", "production", raising=False)
        monkeypatch.setattr(
            config.settings, "cors_allow_origins",
            "*,https://app.clearsignal.example", raising=False,
        )
        monkeypatch.setattr(config.settings, "cors_allow_credentials", True, raising=False)
        app = main.create_app()
        opts = _cors_options(app)
        assert "*" not in opts["allow_origins"]
        assert "https://app.clearsignal.example" in opts["allow_origins"]

    def test_wildcard_with_credentials_disables_credentials(self, monkeypatch):
        from app import config, main
        monkeypatch.setattr(config.settings, "app_env", "development", raising=False)
        monkeypatch.setattr(config.settings, "cors_allow_origins", "*", raising=False)
        monkeypatch.setattr(config.settings, "cors_allow_credentials", True, raising=False)
        app = main.create_app()
        opts = _cors_options(app)
        # '*' + credentials is invalid; credentials must be turned off.
        assert opts["allow_credentials"] is False


# ─────────────────────────────────────────────────────────────────────────────
# Config helpers / safe defaults
# ─────────────────────────────────────────────────────────────────────────────

class TestSecurityConfigDefaults:
    def test_safe_defaults(self):
        from app.config import settings
        assert settings.rate_limit_enabled is True
        assert settings.rate_limit_per_user_per_min >= 1
        assert settings.rate_limit_expensive_per_ip_per_min >= 1
        assert settings.rate_limit_expensive_per_user_per_min >= 1
        assert settings.rate_limit_admin_per_user_per_min >= 1
        assert settings.rate_limit_trusted_proxy_hops >= 0
        assert settings.ask_daily_quota >= 1
        assert settings.ask_question_max_length >= 100
        assert settings.max_request_body_bytes >= 1024
        assert settings.events_ingest_enabled is False
        assert settings.usage_stats_admin_only is True
        # Rollout / billing flags remain OFF (must not be flipped by this milestone).
        assert settings.stripe_enabled is False
        assert settings.auth_enabled is False
        assert settings.entitlements_enforced is False

    def test_origin_list_parsing(self, monkeypatch):
        from app.config import settings
        monkeypatch.setattr(settings, "cors_allow_origins", " a , ,b ,", raising=False)
        assert settings.cors_allow_origins_list == ["a", "b"]


# ─────────────────────────────────────────────────────────────────────────────
# Rate limiter primitive
# ─────────────────────────────────────────────────────────────────────────────

class TestRateLimiter:
    def test_allows_up_to_limit_then_blocks(self):
        from app.security.rate_limit import RateLimiter
        rl = RateLimiter()
        base = 1000.0
        for i in range(3):
            allowed, retry = rl.check("k", limit=3, window_s=60, now=base + i)
            assert allowed is True
        allowed, retry = rl.check("k", limit=3, window_s=60, now=base + 3)
        assert allowed is False
        assert retry > 0

    def test_window_resets(self):
        from app.security.rate_limit import RateLimiter
        rl = RateLimiter()
        assert rl.check("k", 1, 60, now=0)[0] is True
        assert rl.check("k", 1, 60, now=1)[0] is False
        # after the window elapses the counter resets
        assert rl.check("k", 1, 60, now=61)[0] is True

    def test_zero_limit_disables(self):
        from app.security.rate_limit import RateLimiter
        rl = RateLimiter()
        for _ in range(100):
            assert rl.check("k", 0, 60)[0] is True

    def test_keys_are_isolated(self):
        from app.security.rate_limit import RateLimiter
        rl = RateLimiter()
        assert rl.check("a", 1, 60, now=0)[0] is True
        assert rl.check("b", 1, 60, now=0)[0] is True   # different key, own budget
        assert rl.check("a", 1, 60, now=0)[0] is False

    def test_client_ip_uses_rightmost_trusted_hop(self):
        from types import SimpleNamespace
        from app.security.rate_limit import client_ip
        req = SimpleNamespace(
            headers={"x-forwarded-for": "198.51.100.99, 203.0.113.7"},
            client=SimpleNamespace(host="10.0.0.1"),
        )
        assert client_ip(req) == "203.0.113.7"

    def test_client_ip_ignores_forwarded_header_when_no_proxy_is_trusted(self):
        from types import SimpleNamespace
        from app.security.rate_limit import client_ip
        req = SimpleNamespace(
            headers={
                "x-forwarded-for": "198.51.100.99",
                "x-real-ip": "198.51.100.98",
            },
            client=SimpleNamespace(host="203.0.113.8"),
        )
        assert client_ip(req, trusted_proxy_hops=0) == "203.0.113.8"


# ─────────────────────────────────────────────────────────────────────────────
# Per-user daily quota primitive
# ─────────────────────────────────────────────────────────────────────────────

class TestDailyQuota:
    def test_counts_and_enforces_per_user(self):
        from app.services.usage_tracking import UsageTracker
        ut = UsageTracker()
        assert ut.within_daily_quota("userA", limit=2) is True
        ut.incr_daily("userA")
        ut.incr_daily("userA")
        assert ut.daily_count("userA") == 2
        assert ut.within_daily_quota("userA", limit=2) is False

    def test_quota_isolated_per_user(self):
        from app.services.usage_tracking import UsageTracker
        ut = UsageTracker()
        ut.incr_daily("userA")
        ut.incr_daily("userA")
        assert ut.within_daily_quota("userA", limit=2) is False
        # userB has its own budget
        assert ut.within_daily_quota("userB", limit=2) is True

    def test_negative_limit_is_unlimited(self):
        from app.services.usage_tracking import UsageTracker
        ut = UsageTracker()
        for _ in range(100):
            ut.incr_daily("sys")
        assert ut.within_daily_quota("sys", limit=-1) is True


# ─────────────────────────────────────────────────────────────────────────────
# /ask pre-flight guard (unit)
# ─────────────────────────────────────────────────────────────────────────────

from types import SimpleNamespace  # noqa: E402

_SYS = "00000000-0000-0000-0000-000000000001"
_REAL_A = "11111111-1111-1111-1111-111111111111"
_REAL_B = "22222222-2222-2222-2222-222222222222"


def _req(user_id, ip="203.0.113.9"):
    return SimpleNamespace(
        state=SimpleNamespace(user_id=user_id),
        headers={"x-forwarded-for": ip},
        client=SimpleNamespace(host=ip),
    )


def _reset():
    from app.security.rate_limit import rate_limiter
    from app.services.usage_tracking import usage_tracker
    rate_limiter.reset()
    usage_tracker._daily.clear()


@pytest.fixture
def relax(monkeypatch):
    """Relax all limits/enforcement so a single check is about the tested axis."""
    from app.config import settings
    monkeypatch.setattr(settings, "rate_limit_enabled", True, raising=False)
    monkeypatch.setattr(settings, "rate_limit_ask_per_ip_per_min", 1000, raising=False)
    monkeypatch.setattr(settings, "rate_limit_ask_per_user_per_min", 1000, raising=False)
    monkeypatch.setattr(settings, "ask_daily_quota", 1000, raising=False)
    monkeypatch.setattr(settings, "ask_question_max_length", 4000, raising=False)
    monkeypatch.setattr(settings, "entitlements_enforced", False, raising=False)
    _reset()
    yield settings
    _reset()


class TestAskGuardUnit:
    async def test_bypass_user_allowed_when_auth_disabled(self, relax):
        from app.security.ask_guard import enforce_ask_preflight
        uid = await enforce_ask_preflight(_req(_SYS), "hello")
        assert uid == _SYS

    async def test_unauthenticated_raises_401(self, relax):
        from app.security.ask_guard import enforce_ask_preflight
        with pytest.raises(HTTPException) as ei:
            await enforce_ask_preflight(_req(None), "hello")
        assert ei.value.status_code == 401

    async def test_oversized_question_413(self, relax):
        from app.security.ask_guard import enforce_ask_preflight
        relax.ask_question_max_length = 10
        with pytest.raises(HTTPException) as ei:
            await enforce_ask_preflight(_req(_REAL_A), "x" * 50)
        assert ei.value.status_code == 413

    async def test_per_user_rate_limit_429(self, relax):
        from app.security.ask_guard import enforce_ask_preflight
        relax.rate_limit_ask_per_user_per_min = 2
        await enforce_ask_preflight(_req(_REAL_A), "q")
        await enforce_ask_preflight(_req(_REAL_A), "q")
        with pytest.raises(HTTPException) as ei:
            await enforce_ask_preflight(_req(_REAL_A), "q")
        assert ei.value.status_code == 429

    async def test_per_ip_rate_limit_429_across_users(self, relax):
        from app.security.ask_guard import enforce_ask_preflight
        relax.rate_limit_ask_per_ip_per_min = 1
        relax.rate_limit_ask_per_user_per_min = 1000
        await enforce_ask_preflight(_req(_REAL_A, ip="9.9.9.9"), "q")
        # different user, SAME ip → per-IP budget already spent
        with pytest.raises(HTTPException) as ei:
            await enforce_ask_preflight(_req(_REAL_B, ip="9.9.9.9"), "q")
        assert ei.value.status_code == 429

    async def test_daily_quota_429_and_user_isolation(self, relax):
        from app.security.ask_guard import enforce_ask_preflight
        relax.ask_daily_quota = 2
        await enforce_ask_preflight(_req(_REAL_A), "q")
        await enforce_ask_preflight(_req(_REAL_A), "q")
        with pytest.raises(HTTPException) as ei:
            await enforce_ask_preflight(_req(_REAL_A), "q")
        assert ei.value.status_code == 429
        # userB has an independent quota
        assert await enforce_ask_preflight(_req(_REAL_B), "q") == _REAL_B

    async def test_entitlement_fail_closed_when_enforced_and_unverifiable(self, relax, monkeypatch):
        from app.security.ask_guard import enforce_ask_preflight
        relax.entitlements_enforced = True
        # get_session yields None (persistence disabled) → cannot verify → 403.
        import contextlib
        @contextlib.asynccontextmanager
        async def _null_session():
            yield None
        monkeypatch.setattr("app.db.get_session", _null_session, raising=False)
        with pytest.raises(HTTPException) as ei:
            await enforce_ask_preflight(_req(_REAL_A), "q")
        assert ei.value.status_code == 403

    async def test_entitlement_system_user_ok_when_enforced(self, relax):
        from app.security.ask_guard import enforce_ask_preflight
        relax.entitlements_enforced = True
        assert await enforce_ask_preflight(_req(_SYS), "q") == _SYS

    async def test_entitlement_allow_when_serviceable(self, relax, monkeypatch):
        from app.security.ask_guard import enforce_ask_preflight
        relax.entitlements_enforced = True
        import contextlib
        @contextlib.asynccontextmanager
        async def _sess():
            yield object()
        async def _resolve(db, uid):
            return SimpleNamespace(plan_status="active")
        monkeypatch.setattr("app.db.get_session", _sess, raising=False)
        monkeypatch.setattr(
            "app.services.entitlement_service.resolve_entitlements", _resolve, raising=False
        )
        assert await enforce_ask_preflight(_req(_REAL_A), "q") == _REAL_A


# ─────────────────────────────────────────────────────────────────────────────
# /ask endpoint wiring (integration via TestClient)
# ─────────────────────────────────────────────────────────────────────────────

class TestAskEndpointWiring:
    def _client(self):
        from fastapi.testclient import TestClient
        from app.main import app
        return TestClient(app)

    def test_anonymous_ask_rejected_when_auth_enabled(self, monkeypatch):
        from app.config import settings
        monkeypatch.setattr(settings, "auth_enabled", True, raising=False)
        c = self._client()
        r = c.post("/ask", json={"company_name": "NVDA", "question": "hi"})
        assert r.status_code == 401

    def test_oversized_question_returns_413(self, monkeypatch):
        from app.config import settings
        monkeypatch.setattr(settings, "auth_enabled", False, raising=False)
        monkeypatch.setattr(settings, "ask_question_max_length", 50, raising=False)
        c = self._client()
        r = c.post("/ask", json={"company_name": "NVDA", "question": "x" * 200})
        assert r.status_code == 413

    def test_valid_ask_passes_gate_in_bypass_mode(self, monkeypatch):
        # Prove the guard lets a valid, in-quota request through to the pipeline
        # (stubbed) — the streaming response is 200 once the gate is cleared.
        from app.config import settings
        monkeypatch.setattr(settings, "auth_enabled", False, raising=False)

        def _stub_route_question(req):
            r = SimpleNamespace(company="NVDA", routing={"detected_ticker": "NVDA"})
            r.model_dump = lambda: {"answer": {"text": "stub"}}
            return r

        monkeypatch.setattr("app.api.route_question", _stub_route_question, raising=False)
        c = self._client()
        r = c.post("/ask", json={"company_name": "NVDA", "question": "is the thesis ok?"})
        assert r.status_code == 200


# ─────────────────────────────────────────────────────────────────────────────
# Admin authorization helper
# ─────────────────────────────────────────────────────────────────────────────

class TestAuthz:
    def test_system_user_is_admin(self):
        from app.security.authz import is_admin
        assert is_admin(_SYS) is True

    def test_real_user_not_admin_by_default(self, monkeypatch):
        from app.config import settings
        from app.security.authz import is_admin
        monkeypatch.setattr(settings, "admin_user_ids", "", raising=False)
        assert is_admin(_REAL_A) is False

    def test_real_user_admin_when_listed(self, monkeypatch):
        from app.config import settings
        from app.security.authz import is_admin
        monkeypatch.setattr(settings, "admin_user_ids", _REAL_A, raising=False)
        assert is_admin(_REAL_A) is True

    def test_require_admin_401_then_403(self, monkeypatch):
        from app.config import settings
        from app.security.authz import require_admin
        monkeypatch.setattr(settings, "admin_user_ids", "", raising=False)
        # unauthenticated → 401
        with pytest.raises(HTTPException) as ei:
            require_admin(_req(None))
        assert ei.value.status_code == 401
        # authenticated non-admin → 403
        with pytest.raises(HTTPException) as ei:
            require_admin(_req(_REAL_A))
        assert ei.value.status_code == 403


# ─────────────────────────────────────────────────────────────────────────────
# Sensitive endpoint lockdown (integration)
# ─────────────────────────────────────────────────────────────────────────────

class TestSensitiveEndpoints:
    def _client(self):
        from fastapi.testclient import TestClient
        from app.main import app
        return TestClient(app)

    def test_usage_stats_ok_for_operator_in_bypass(self, monkeypatch):
        from app.config import settings
        monkeypatch.setattr(settings, "auth_enabled", False, raising=False)
        r = self._client().get("/usage/stats")
        assert r.status_code == 200
        assert isinstance(r.json(), dict)

    def test_usage_stats_401_when_auth_enabled_no_token(self, monkeypatch):
        from app.config import settings
        monkeypatch.setattr(settings, "auth_enabled", True, raising=False)
        monkeypatch.setattr(settings, "usage_stats_admin_only", True, raising=False)
        r = self._client().get("/usage/stats")
        assert r.status_code == 401

    def test_events_ingest_disabled_by_default_403(self, monkeypatch):
        from app.config import settings
        monkeypatch.setattr(settings, "events_ingest_enabled", False, raising=False)
        r = self._client().post("/events/ingest", json={"ticker": "NVDA"})
        assert r.status_code == 403

    def test_events_ingest_oversized_payload_413(self, monkeypatch):
        from app.config import settings
        monkeypatch.setattr(settings, "auth_enabled", False, raising=False)
        monkeypatch.setattr(settings, "events_ingest_enabled", True, raising=False)
        monkeypatch.setattr(settings, "max_event_payload_bytes", 2048, raising=False)
        # ~5 KB payload: under the 64 KB global body cap, over the 2 KB event cap.
        big = {"ticker": "NVDA", "blob": "x" * 5000}
        r = self._client().post("/events/ingest", json=big)
        assert r.status_code == 413


class TestRequestBodyLimitMiddleware:
    """The hard cap must count streamed bytes, not trust Content-Length."""

    @staticmethod
    async def _run(messages, *, limit):
        from app.security.request_body_limit import RequestBodyLimitMiddleware

        received = {}
        sent = []
        pending = iter(messages)

        async def receive():
            try:
                return next(pending)
            except StopIteration:
                return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message):
            sent.append(message)

        async def downstream(scope, downstream_receive, downstream_send):
            chunks = []
            while True:
                message = await downstream_receive()
                chunks.append(message.get("body", b""))
                if not message.get("more_body", False):
                    break
            received["body"] = b"".join(chunks)
            await downstream_send(
                {"type": "http.response.start", "status": 204, "headers": []}
            )
            await downstream_send({"type": "http.response.body", "body": b""})

        app = RequestBodyLimitMiddleware(downstream, max_body_bytes=limit)
        await app(
            {
                "type": "http",
                "method": "POST",
                "path": "/ask",
                "headers": [(b"content-length", b"1")],
            },
            receive,
            send,
        )
        return received, sent

    def test_rejects_chunked_body_over_limit_even_with_false_header(self):
        import asyncio

        received, sent = asyncio.run(
            self._run(
                [
                    {"type": "http.request", "body": b"abcd", "more_body": True},
                    {"type": "http.request", "body": b"efgh", "more_body": False},
                ],
                limit=7,
            )
        )

        assert received == {}
        assert sent[0]["type"] == "http.response.start"
        assert sent[0]["status"] == 413
        assert sent[1]["body"] == b'{"detail":"Request body too large."}'

    def test_replays_body_at_exact_limit_without_mutation(self):
        import asyncio

        received, sent = asyncio.run(
            self._run(
                [
                    {"type": "http.request", "body": b"abcd", "more_body": True},
                    {"type": "http.request", "body": b"efgh", "more_body": False},
                ],
                limit=8,
            )
        )

        assert received["body"] == b"abcdefgh"
        assert sent[0]["status"] == 204
