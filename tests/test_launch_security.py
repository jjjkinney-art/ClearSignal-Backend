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

    def test_client_ip_prefers_forwarded_for(self):
        from types import SimpleNamespace
        from app.security.rate_limit import client_ip
        req = SimpleNamespace(
            headers={"x-forwarded-for": "203.0.113.7, 10.0.0.1"},
            client=SimpleNamespace(host="10.0.0.1"),
        )
        assert client_ip(req) == "203.0.113.7"


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
