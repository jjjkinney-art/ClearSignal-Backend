"""Section 0 — real /admin/loop kill-switch route handlers.

tests/test_services/test_loop_canary_slice9.py covers the kill-switch service
functions thoroughly, but its ADMIN_API section exercises a `mini` FastAPI app
that re-implements the handlers inline. That means the *actual* handlers in
app/api.py — admin_loop_disable / admin_loop_enable — have no direct coverage,
so a change to them would not fail any test.

The kill switch is a Tier-0 safety control: docs/BETA_LAUNCH_RUNBOOK.md
rollback step 2 depends on POST /admin/loop/disable actually disabling the
loop, and entry criterion 6 depends on the operator being able to verify it.

The invariant that matters most is that /admin/loop/enable *clears* the
override rather than force-enabling: the module keeps `_enabled_override` as
None | False only, and force_enable() restores config governance. If a future
edit made "enable" mean "turn the loop on", it would start live delivery in
production while config still said loop_enabled=False.

These tests call the handler coroutines directly. That deliberately bypasses
the /admin authorization boundary, which is covered separately by
tests/test_launch_access_policy.py; the concern here is handler semantics.
"""
from __future__ import annotations

import asyncio

import pytest


def _api():
    """Lazy import — module-scope import of app.api can shadow test symbols."""
    import app.api as api

    return api


def _tel():
    from app.services import loop_canary_telemetry as tel

    return tel


@pytest.fixture(autouse=True)
def restore_override():
    """Kill-switch state is a module global; never leak it between tests."""
    tel = _tel()
    before = tel.override_state()
    yield
    if before is None:
        tel.force_enable()
    else:
        tel.force_disable()


def test_disable_handler_engages_the_override():
    api, tel = _api(), _tel()
    tel.force_enable()  # start from config governance
    assert tel.override_state() is None

    result = asyncio.run(api.admin_loop_disable())

    assert result["status"] == "ok"
    assert result["effective_enabled"] is False
    assert result["override"] == "force_disabled"
    assert tel.override_state() is False


def test_disable_is_idempotent():
    api, tel = _api(), _tel()
    asyncio.run(api.admin_loop_disable())
    asyncio.run(api.admin_loop_disable())
    assert tel.override_state() is False


def test_enable_handler_clears_the_override():
    api, tel = _api(), _tel()
    asyncio.run(api.admin_loop_disable())
    assert tel.override_state() is False

    result = asyncio.run(api.admin_loop_enable())

    assert result["status"] == "ok"
    assert result["override"] == "cleared"
    assert tel.override_state() is None, (
        "enable must clear the override to None (config governance), not set a "
        "value of its own"
    )


def test_enable_does_not_force_enable_when_config_disabled(monkeypatch):
    """The production-critical invariant.

    With loop_enabled=False in config — the deployed beta configuration —
    clearing the kill switch must leave the loop OFF.
    """
    api, tel = _api(), _tel()
    from app.config import settings

    monkeypatch.setattr(settings, "loop_enabled", False, raising=False)
    asyncio.run(api.admin_loop_disable())

    result = asyncio.run(api.admin_loop_enable())

    assert result["effective_enabled"] is False, (
        "clearing the kill switch must not start the loop while config says "
        "loop_enabled=False"
    )
    assert result["config_loop_enabled"] is False
    assert tel.get_enabled(False) is False


def test_enable_restores_config_governance_when_config_enabled(monkeypatch):
    """Mirror case: enable must not pin the loop off either — config governs."""
    api, tel = _api(), _tel()
    from app.config import settings

    monkeypatch.setattr(settings, "loop_enabled", True, raising=False)
    asyncio.run(api.admin_loop_disable())
    assert tel.get_enabled(True) is False  # override wins while engaged

    result = asyncio.run(api.admin_loop_enable())

    assert result["effective_enabled"] is True
    assert result["config_loop_enabled"] is True
    assert tel.override_state() is None


def test_override_is_only_ever_none_or_false():
    """Pin the two-state design the whole safety argument rests on."""
    api, tel = _api(), _tel()
    seen = set()
    for _ in range(2):
        asyncio.run(api.admin_loop_disable())
        seen.add(tel.override_state())
        asyncio.run(api.admin_loop_enable())
        seen.add(tel.override_state())
    assert seen == {None, False}, (
        "the kill-switch override must never take the value True; a True "
        "override would enable the loop regardless of configuration"
    )


def test_enable_reports_canary_pct_without_changing_it():
    api = _api()
    from app.config import settings

    before = int(settings.loop_canary_pct)
    result = asyncio.run(api.admin_loop_enable())
    assert result["canary_pct"] == before
    assert int(settings.loop_canary_pct) == before, (
        "the kill-switch endpoints must not mutate canary configuration"
    )
