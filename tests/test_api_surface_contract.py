"""Section 0 — public API surface contract.

Freezes the route inventory of the deployed release so that a later roadmap
change cannot silently remove or rename an endpoint that clients depend on.

Contract semantics: FLOOR, not exact match.

  * Every (method, path) recorded in tests/contracts/api_surface_v1.json must
    continue to exist.
  * Adding new routes is allowed and does NOT fail this test — the 9/10
    roadmap is expected to add surface area.
  * Removing or renaming a route fails here, forcing the change to be a
    deliberate, reviewed edit of the fixture rather than an accident.

HEAD and OPTIONS are excluded: HEAD is registered separately for uptime
monitors and is deliberately kept out of the OpenAPI schema, and OPTIONS is
supplied by CORS middleware rather than the application.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

FIXTURE = Path(__file__).parent / "contracts" / "api_surface_v1.json"


def _fixture() -> dict:
    return json.loads(FIXTURE.read_text())


def _live_surface() -> set[tuple[str, str]]:
    from app.main import app

    live: set[tuple[str, str]] = set()
    for route in app.routes:
        path = getattr(route, "path", None)
        methods = getattr(route, "methods", None)
        if not path or not methods:
            continue
        for method in methods:
            if method in ("HEAD", "OPTIONS"):
                continue
            live.add((method, path))
    return live


def test_fixture_is_present_and_well_formed():
    doc = _fixture()
    assert doc["routes"], "frozen route contract must not be empty"
    assert doc["_release_commit"].startswith("a63f151"), (
        "the recorded baseline commit should match the release this contract "
        "was captured from"
    )
    for entry in doc["routes"]:
        assert len(entry) == 2, f"malformed contract entry: {entry!r}"
        method, path = entry
        assert method.isupper(), f"method should be upper-case: {method!r}"
        assert path.startswith("/"), f"path should be absolute: {path!r}"


def test_no_recorded_route_has_been_removed():
    """The core regression guard: endpoints may be added, never dropped."""
    live = _live_surface()
    recorded = {(m, p) for m, p in _fixture()["routes"]}
    missing = sorted(recorded - live)
    assert not missing, (
        "%d endpoint(s) present in the recorded release are missing from the "
        "current app. Removing or renaming a route is a breaking change; if it "
        "is intended, update tests/contracts/api_surface_v1.json in the same "
        "commit.\n  %s"
        % (len(missing), "\n  ".join("%s %s" % mp for mp in missing))
    )


def test_added_routes_are_reported_but_do_not_fail(capsys):
    """Additions are informational — the roadmap is expected to add surface."""
    live = _live_surface()
    recorded = {(m, p) for m, p in _fixture()["routes"]}
    added = sorted(live - recorded)
    if added:
        print("routes added since the recorded baseline: %d" % len(added))
        for m, p in added:
            print("  + %s %s" % (m, p))
    assert True  # never fails; presence of additions is not a regression


@pytest.mark.parametrize(
    "method,path",
    [
        ("GET", "/health"),
        ("POST", "/ask"),
        ("GET", "/watchlist"),
        ("POST", "/watchlist/{ticker}"),
        ("DELETE", "/watchlist/{ticker}"),
        ("GET", "/portfolio/positions"),
        ("POST", "/portfolio/positions"),
        ("DELETE", "/portfolio/positions/{ticker}"),
        ("GET", "/notifications"),
        ("GET", "/billing/status"),
        ("GET", "/auth/session"),
        ("GET", "/auth/me"),
        ("POST", "/auth/import"),
        ("GET", "/admin/loop-status"),
        ("POST", "/admin/loop/disable"),
        ("POST", "/admin/loop/enable"),
        ("GET", "/admin/billing-status"),
    ],
)
def test_launch_critical_endpoints_exist(method, path):
    """Endpoints the beta launch gate and runbook depend on by name.

    These are called out explicitly (in addition to the frozen fixture) because
    docs/BETA_LAUNCH_RUNBOOK.md, tests/validate_beta_launch.py and
    tests/validate_production_acceptance.py reference them directly. Losing one
    breaks the release gate itself, so it should fail loudly and by name.
    """
    assert (method, path) in _live_surface(), (
        "%s %s is required by the beta launch gate / runbook" % (method, path)
    )
