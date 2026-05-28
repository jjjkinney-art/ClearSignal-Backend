"""
tests/test_health_head.py

Regression suite for HEAD support on health endpoints.

Background:
  UptimeRobot free plan sends HEAD requests (not GET) to check uptime.
  FastAPI / Starlette 0.49+ does NOT automatically support HEAD on GET routes —
  HEAD must be registered explicitly via add_api_route(methods=["GET", "HEAD"]).

  Before fix: HEAD / → 405, HEAD /health → 405, HEAD /healthz → 405
  After fix:  HEAD / → 200, HEAD /health → 200, HEAD /healthz → 200

Run:
    python3 -m pytest tests/test_health_head.py -v
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app

# ── Shared client ─────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(app, raise_server_exceptions=False)


# ── HEAD support (UptimeRobot) ────────────────────────────────────────────────

class TestHeadRequests:
    """HEAD must return 200 on all three health paths (UptimeRobot regression)."""

    @pytest.mark.parametrize("path", ["/", "/health", "/healthz"])
    def test_head_returns_200(self, client: TestClient, path: str):
        res = client.head(path)
        assert res.status_code == 200, (
            f"HEAD {path} returned {res.status_code}. "
            "UptimeRobot free plan uses HEAD — 405 means the backend is always "
            "reported as down. Fix: register routes with methods=['GET', 'HEAD']."
        )

    @pytest.mark.parametrize("path", ["/", "/health", "/healthz"])
    def test_head_response_body_is_empty(self, client: TestClient, path: str):
        """HEAD response must have no body (HTTP spec §9.4)."""
        res = client.head(path)
        assert res.content == b"", (
            f"HEAD {path} returned non-empty body: {res.content!r}. "
            "HEAD responses must not include a message body per RFC 9110 §9.3.2."
        )

    @pytest.mark.parametrize("path", ["/", "/health", "/healthz"])
    def test_head_returns_content_type_header(self, client: TestClient, path: str):
        """HEAD response should include Content-Type even without a body."""
        res = client.head(path)
        assert res.status_code == 200
        ct = res.headers.get("content-type", "")
        assert "application/json" in ct, (
            f"HEAD {path} missing application/json Content-Type header: {ct!r}. "
            "Content-Type is expected by some uptime monitors for validation."
        )


# ── GET still works after refactor ───────────────────────────────────────────

class TestGetRequestsUnchanged:
    """GET behavior must be identical after switching from stacked decorators
    to add_api_route(methods=['GET', 'HEAD'])."""

    @pytest.mark.parametrize("path", ["/", "/health", "/healthz"])
    def test_get_returns_200(self, client: TestClient, path: str):
        res = client.get(path)
        assert res.status_code == 200

    @pytest.mark.parametrize("path", ["/", "/health", "/healthz"])
    def test_get_returns_status_ok(self, client: TestClient, path: str):
        res = client.get(path)
        data = res.json()
        assert data.get("status") == "ok", (
            f"GET {path} → status={data.get('status')!r}, expected 'ok'"
        )

    @pytest.mark.parametrize("path", ["/", "/health", "/healthz"])
    def test_get_returns_service_name(self, client: TestClient, path: str):
        res = client.get(path)
        data = res.json()
        assert data.get("service") == "clearsignal-backend", (
            f"GET {path} → service={data.get('service')!r}, expected 'clearsignal-backend'"
        )

    @pytest.mark.parametrize("path", ["/", "/health", "/healthz"])
    def test_get_returns_all_required_fields(self, client: TestClient, path: str):
        """GET health response must include all Phase 5 metadata fields."""
        res = client.get(path)
        data = res.json()
        required = {"status", "service", "version", "timestamp", "environment", "build_commit"}
        missing = required - set(data.keys())
        assert not missing, (
            f"GET {path} missing fields: {missing}. "
            f"Got: {list(data.keys())}"
        )

    @pytest.mark.parametrize("path", ["/", "/health", "/healthz"])
    def test_get_timestamp_is_iso8601(self, client: TestClient, path: str):
        """timestamp field must be a valid ISO-8601 UTC string."""
        import re
        res = client.get(path)
        ts = res.json().get("timestamp", "")
        assert re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$", ts), (
            f"GET {path} → timestamp={ts!r} is not ISO-8601 UTC (YYYY-MM-DDTHH:MM:SSZ)"
        )


# ── All three paths return identical payloads ─────────────────────────────────

class TestHealthPathEquivalence:
    """/, /health, and /healthz must all return the same schema."""

    def test_all_paths_have_same_keys(self, client: TestClient):
        responses = {p: client.get(p).json() for p in ("/", "/health", "/healthz")}
        key_sets = {p: frozenset(r.keys()) for p, r in responses.items()}
        assert key_sets["/"] == key_sets["/health"] == key_sets["/healthz"], (
            f"Health paths return different key sets: {key_sets}"
        )

    def test_all_paths_have_same_static_fields(self, client: TestClient):
        """status, service, environment, build_commit should match across paths."""
        responses = {p: client.get(p).json() for p in ("/", "/health", "/healthz")}
        for field in ("status", "service", "environment", "build_commit"):
            values = {p: r.get(field) for p, r in responses.items()}
            unique = set(values.values())
            assert len(unique) == 1, (
                f"Field {field!r} differs across health paths: {values}"
            )


# ── Other methods still rejected ─────────────────────────────────────────────

class TestUnsupportedMethods:
    """POST/PUT/DELETE on health endpoints must still return 405."""

    @pytest.mark.parametrize("path", ["/health", "/healthz"])
    def test_post_returns_405(self, client: TestClient, path: str):
        res = client.post(path, json={})
        assert res.status_code == 405, (
            f"POST {path} returned {res.status_code}, expected 405"
        )

    @pytest.mark.parametrize("path", ["/health", "/healthz"])
    def test_delete_returns_405(self, client: TestClient, path: str):
        res = client.delete(path)
        assert res.status_code == 405, (
            f"DELETE {path} returned {res.status_code}, expected 405"
        )
