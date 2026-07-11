"""Sprint 0 — CI workflow syntax + local-command parity guard.

Ensures .github/workflows/ci.yml stays valid, triggers on PR + push to main,
pins Python 3.11, and actually gates on the launch-critical suites (so nobody
can silently drop a required check).  Does not require network or GitHub.
"""
from __future__ import annotations

from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
_CI = _ROOT / ".github" / "workflows" / "ci.yml"


@pytest.fixture(scope="module")
def workflow():
    assert _CI.exists(), ".github/workflows/ci.yml is missing"
    try:
        import yaml  # PyYAML ships with pytest envs / setup-python
    except Exception:
        pytest.skip("PyYAML not available")
    return yaml.safe_load(_CI.read_text())


def test_triggers_on_pr_and_push_to_main(workflow):
    # PyYAML parses the bare key `on:` as boolean True in YAML 1.1.
    on = workflow.get("on", workflow.get(True))
    assert on, "workflow has no triggers"
    assert "pull_request" in on and "push" in on
    assert "main" in on["pull_request"]["branches"]
    assert "main" in on["push"]["branches"]


def test_pins_python_311(workflow):
    text = _CI.read_text()
    assert "3.11" in text
    assert "cache: pip" in text  # deps cached; no secrets/db cached


def test_gates_on_launch_critical_suites(workflow):
    text = _CI.read_text()
    for needle in (
        "--collect-only",                       # collection determinism
        "test_launch_security.py",              # launch-security
        "test_dependency_pinning.py",           # reproducibility
        "test_portfolio_router.py",             # production routers
        "test_auth_routes.py",                  # auth
        "test_billing_routes.py",               # billing
        "test_conviction_integration.py",       # validation V1/V6
    ):
        assert needle in text, f"CI does not gate on {needle}"


def test_no_secrets_referenced(workflow):
    # This suite must run with zero secrets (flags default off, LLM stubbed).
    text = _CI.read_text().lower()
    assert "secrets." not in text, "CI must not depend on secrets for the test gate"
