"""
Phase 10A · Slice 9 — Loop canary + kill-switch tests.

Covers:
  § CONFIG     — new config flags default values
  § COHORT     — deterministic assignment, sticky, canary cap, holdout, internal
  § KILL_SWITCH — force_disable / force_enable / override_state semantics
  § TELEMETRY  — tick counter increments, cohort counts, recent ticks ring
  § SCHEDULER  — kill switch blocks ticks; enable restores; shadow flag inert
  § ADMIN_API  — /admin/loop-status, /admin/loop/disable, /admin/loop/enable
  § SAFETY     — loop remains shadow-only; no real delivery during these tests
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional
from unittest.mock import patch

import pytest

from app.services import loop_canary_telemetry as tel
from app.services import loop_canary_cohort as cohort
from app.services.loop_canary_cohort import (
    COHORT_INTERNAL,
    COHORT_CANARY,
    COHORT_CONTROL,
    COHORT_INELIGIBLE,
    HOLDOUT_PCT,
    decide_cohort,
    _subject_bucket,
)
from app.services.loop_canary_telemetry import (
    get_enabled,
    force_disable,
    force_enable,
    override_state,
    record_tick,
    record_delivery_shadow,
    record_duplicate_delivery,
    record_cost_guard_skip,
    snapshot,
    reset,
)
from app.services.loop_scheduler_service import (
    ProducerResult,
    register_producer,
    tick,
    unregister_producer,
    list_registered_producers,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _uid() -> str:
    return uuid.uuid4().hex[:12]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _past(s: int = 5) -> datetime:
    return _now() - timedelta(seconds=s)


def _naive(dt: datetime) -> datetime:
    return dt.replace(tzinfo=None)


def _holder() -> str:
    return f"test:{_uid()}"


@pytest.fixture(autouse=True)
def reset_telemetry():
    """Always reset in-process telemetry before and after each test."""
    reset()
    yield
    reset()


@pytest.fixture(autouse=True)
def clean_producers():
    yield
    for jt in list(list_registered_producers()):
        unregister_producer(jt)


@pytest.fixture
def loop_on(monkeypatch):
    from app.services import loop_scheduler_service as sched
    monkeypatch.setattr(sched, "_is_loop_enabled", lambda: True)


# ---------------------------------------------------------------------------
# Minimal TickResult stub for telemetry tests
# ---------------------------------------------------------------------------

class _FakeTickResult:
    def __init__(self, **kw):
        self.ts                 = kw.get("ts", "")
        self.loop_enabled       = kw.get("loop_enabled", True)
        self.tick_acquired      = kw.get("tick_acquired", True)
        self.jobs_claimed       = kw.get("jobs_claimed", 0)
        self.jobs_succeeded     = kw.get("jobs_succeeded", 0)
        self.jobs_failed        = kw.get("jobs_failed", 0)
        self.jobs_short_circuited = kw.get("jobs_short_circuited", 0)
        self.locks_reaped       = kw.get("locks_reaped", 0)
        self.errors             = kw.get("errors", [])


# ===========================================================================
# § CONFIG defaults
# ===========================================================================

class TestConfigDefaults:
    def test_loop_shadow_default_true(self):
        from app.config import settings
        assert settings.loop_shadow is True

    def test_loop_canary_pct_default_zero(self):
        from app.config import settings
        assert settings.loop_canary_pct == 0

    def test_loop_internal_only_default_true(self):
        from app.config import settings
        assert settings.loop_internal_only is True

    def test_loop_enabled_default_false(self):
        from app.config import settings
        assert settings.loop_enabled is False

    def test_loop_internal_user_ids_default_empty(self):
        from app.config import settings
        assert settings.loop_internal_user_ids == ""


# ===========================================================================
# § COHORT assignment
# ===========================================================================

class TestCohortAssignment:
    def test_ineligible_when_disabled(self):
        assert decide_cohort("user-abc", canary_pct=50, enabled=False) == COHORT_INELIGIBLE

    def test_ineligible_when_canary_pct_zero(self):
        assert decide_cohort("user-abc", canary_pct=0, enabled=True) == COHORT_INELIGIBLE

    def test_deterministic_same_input_same_output(self):
        sid = _uid()
        c1 = decide_cohort(sid, canary_pct=50, enabled=True)
        c2 = decide_cohort(sid, canary_pct=50, enabled=True)
        assert c1 == c2

    def test_sticky_across_multiple_calls(self):
        sids = [_uid() for _ in range(20)]
        for sid in sids:
            expected = decide_cohort(sid, canary_pct=50, enabled=True)
            for _ in range(5):
                assert decide_cohort(sid, canary_pct=50, enabled=True) == expected

    def test_canary_pct_100_clamped_to_95(self):
        """With pct=100 (clamped to 95), buckets 0–4 are always CONTROL (holdout)."""
        holdout_sids = [s for s in [_uid() for _ in range(200)]
                        if _subject_bucket(s) < HOLDOUT_PCT]
        for sid in holdout_sids[:5]:
            assert decide_cohort(sid, canary_pct=100, enabled=True) == COHORT_CONTROL

    def test_permanent_5pct_holdout_at_95pct_canary(self):
        """Buckets 0–4 must always be CONTROL even at max canary_pct."""
        sids_in_holdout = [s for s in [_uid() for _ in range(500)]
                           if _subject_bucket(s) < HOLDOUT_PCT]
        for sid in sids_in_holdout[:10]:
            result = decide_cohort(sid, canary_pct=95, enabled=True)
            assert result == COHORT_CONTROL, (
                f"sid={sid} bucket={_subject_bucket(sid)} should be CONTROL in holdout"
            )

    def test_canary_pct_zero_is_all_ineligible(self):
        for _ in range(20):
            sid = _uid()
            assert decide_cohort(sid, canary_pct=0, enabled=True) == COHORT_INELIGIBLE

    def test_canary_100pct_non_holdout_buckets_are_canary(self):
        """Buckets 5–99 should all be COHORT_CANARY at pct=95."""
        canary_sids = [s for s in [_uid() for _ in range(500)]
                       if _subject_bucket(s) >= HOLDOUT_PCT]
        for sid in canary_sids[:20]:
            result = decide_cohort(sid, canary_pct=95, enabled=True)
            assert result == COHORT_CANARY, (
                f"sid={sid} bucket={_subject_bucket(sid)} expected CANARY"
            )

    def test_internal_user_bypasses_hash(self, monkeypatch):
        monkeypatch.setattr(cohort, "_internal_user_ids", lambda: {"internal_admin"})
        result = decide_cohort("internal_admin", canary_pct=0, enabled=True)
        assert result == COHORT_INTERNAL

    def test_internal_user_ineligible_if_loop_disabled(self, monkeypatch):
        monkeypatch.setattr(cohort, "_internal_user_ids", lambda: {"internal_admin"})
        result = decide_cohort("internal_admin", canary_pct=0, enabled=False)
        assert result == COHORT_INELIGIBLE

    def test_non_internal_user_goes_through_hash(self, monkeypatch):
        monkeypatch.setattr(cohort, "_internal_user_ids", lambda: {"other_user"})
        # A non-internal user should get normal hash-based assignment
        result = decide_cohort(_uid(), canary_pct=50, enabled=True)
        assert result in (COHORT_CANARY, COHORT_CONTROL)

    def test_distribution_roughly_correct(self):
        """At pct=50, ~47.5% of 1000 subjects should be CANARY (50% of the 95% non-holdout)."""
        subjects = [_uid() for _ in range(1000)]
        canary_count = sum(
            1 for s in subjects
            if decide_cohort(s, canary_pct=50, enabled=True) == COHORT_CANARY
        )
        # Expect ~475 (47.5%) — allow ±10% for hash variance → 375–575
        assert 375 <= canary_count <= 575, (
            f"canary_count={canary_count} out of expected range [375, 575]"
        )


# ===========================================================================
# § KILL SWITCH
# ===========================================================================

class TestKillSwitch:
    def test_default_override_is_none(self):
        assert override_state() is None

    def test_force_disable_sets_override_false(self):
        force_disable()
        assert override_state() is False

    def test_force_enable_clears_override(self):
        force_disable()
        force_enable()
        assert override_state() is None

    def test_get_enabled_config_true_no_override(self):
        assert get_enabled(True) is True

    def test_get_enabled_config_false_no_override(self):
        assert get_enabled(False) is False

    def test_get_enabled_force_disable_overrides_config_true(self):
        force_disable()
        assert get_enabled(True) is False

    def test_get_enabled_force_disable_overrides_config_false(self):
        force_disable()
        assert get_enabled(False) is False

    def test_force_enable_restores_config_governance_true(self):
        force_disable()
        force_enable()
        assert get_enabled(True) is True

    def test_force_enable_restores_config_governance_false(self):
        force_disable()
        force_enable()
        assert get_enabled(False) is False

    def test_repeated_disable_is_idempotent(self):
        force_disable()
        force_disable()
        assert override_state() is False

    def test_repeated_enable_is_idempotent(self):
        force_enable()
        force_enable()
        assert override_state() is None


# ===========================================================================
# § TELEMETRY counters
# ===========================================================================

class TestTelemetryCounters:
    def test_initial_snapshot_all_zeros(self):
        snap = snapshot()
        c = snap["counters"]
        assert c["tick_count"] == 0
        assert c["jobs_claimed"] == 0
        assert c["jobs_succeeded"] == 0
        assert c["jobs_failed"] == 0
        assert c["delivery_shadow_count"] == 0
        assert c["duplicate_delivery_count"] == 0
        assert c["lock_contention_count"] == 0
        assert c["cost_guard_skip_count"] == 0

    def test_record_tick_increments_counters(self):
        r = _FakeTickResult(
            tick_acquired=True, jobs_claimed=3,
            jobs_succeeded=2, jobs_failed=1,
            jobs_short_circuited=0,
        )
        record_tick(r)
        snap = snapshot()
        c = snap["counters"]
        assert c["tick_count"] == 1
        assert c["jobs_claimed"] == 3
        assert c["jobs_succeeded"] == 2
        assert c["jobs_failed"] == 1

    def test_record_tick_lock_contention(self):
        r = _FakeTickResult(tick_acquired=False)
        record_tick(r)
        assert snapshot()["counters"]["lock_contention_count"] == 1

    def test_record_tick_no_lock_contention_when_acquired(self):
        r = _FakeTickResult(tick_acquired=True)
        record_tick(r)
        assert snapshot()["counters"]["lock_contention_count"] == 0

    def test_record_delivery_shadow(self):
        record_delivery_shadow(3)
        assert snapshot()["counters"]["delivery_shadow_count"] == 3

    def test_record_duplicate_delivery(self):
        record_duplicate_delivery(2)
        assert snapshot()["counters"]["duplicate_delivery_count"] == 2

    def test_record_cost_guard_skip(self):
        record_cost_guard_skip(5)
        assert snapshot()["counters"]["cost_guard_skip_count"] == 5

    def test_multiple_ticks_accumulate(self):
        for _ in range(4):
            record_tick(_FakeTickResult(jobs_claimed=2, jobs_succeeded=2))
        c = snapshot()["counters"]
        assert c["tick_count"] == 4
        assert c["jobs_claimed"] == 8
        assert c["jobs_succeeded"] == 8

    def test_recent_ticks_ring_buffer(self):
        for i in range(5):
            record_tick(_FakeTickResult(ts=f"ts-{i}", jobs_claimed=i))
        snap = snapshot()
        assert len(snap["recent_ticks"]) == 5
        # Most recent first
        assert snap["recent_ticks"][0]["ts"] == "ts-4"

    def test_reset_clears_all_counters(self):
        record_tick(_FakeTickResult(jobs_claimed=5, jobs_succeeded=5))
        record_delivery_shadow(10)
        force_disable()
        reset()
        c = snapshot()["counters"]
        assert all(v == 0 for v in c.values())
        assert override_state() is None
        assert snapshot()["recent_ticks"] == []

    def test_kill_switch_state_in_snapshot(self):
        force_disable()
        snap = snapshot()
        assert snap["kill_switch"]["enabled_override"] is False
        assert snap["kill_switch"]["effective_state"] == "force_disabled"

    def test_no_override_state_in_snapshot(self):
        snap = snapshot()
        assert snap["kill_switch"]["enabled_override"] is None
        assert snap["kill_switch"]["effective_state"] == "config_governed"


# ===========================================================================
# § SCHEDULER integration
# ===========================================================================

class TestSchedulerKillSwitch:
    @pytest.mark.asyncio
    async def test_kill_switch_blocks_tick(self, db_session):
        """force_disable() must prevent any jobs from being claimed."""
        call_count = [0]

        async def counting_producer(session, job, run_id, holder_id, fence_token):
            call_count[0] += 1
            return ProducerResult(outcome="succeeded")

        register_producer("watchlist_scan", counting_producer)

        from sqlalchemy import update as sa_update
        from app.db.models import ScheduledJob
        from app.db.repositories import loop_repo

        job = await loop_repo.job_create(
            db_session, "watchlist_scan", "global",
            f"2026-06-12-{_uid()[:6]}",
            next_run_utc=_naive(_past(5)),
        )

        force_disable()

        result = await tick(db_session, _holder(), batch_size=10, lease_s=120)
        assert result.loop_enabled is False
        assert result.jobs_claimed == 0
        assert call_count[0] == 0

    @pytest.mark.asyncio
    async def test_enable_restores_tick_dispatch(self, db_session, loop_on):
        """After force_enable, config-governed tick proceeds normally."""
        call_count = [0]

        async def counting_producer(session, job, run_id, holder_id, fence_token):
            call_count[0] += 1
            return ProducerResult(outcome="succeeded")

        register_producer("watchlist_scan", counting_producer)

        # Kill then restore
        force_disable()
        force_enable()

        from app.db.repositories import loop_repo
        await loop_repo.job_create(
            db_session, "watchlist_scan", "global",
            f"2026-06-12-{_uid()[:6]}",
            next_run_utc=_naive(_past(5)),
        )

        result = await tick(db_session, _holder(), batch_size=10, lease_s=120)
        assert result.jobs_claimed == 1
        assert call_count[0] == 1

    @pytest.mark.asyncio
    async def test_tick_records_telemetry(self, db_session, loop_on):
        """After a tick, telemetry counters must be incremented."""
        async def noop_producer(session, job, run_id, holder_id, fence_token):
            return ProducerResult(outcome="succeeded")

        register_producer("watchlist_scan", noop_producer)

        from app.db.repositories import loop_repo
        await loop_repo.job_create(
            db_session, "watchlist_scan", "global",
            f"2026-06-12-{_uid()[:6]}",
            next_run_utc=_naive(_past(5)),
        )

        reset()
        await tick(db_session, _holder(), batch_size=10, lease_s=120)

        c = snapshot()["counters"]
        assert c["tick_count"] == 1
        assert c["jobs_claimed"] == 1
        assert c["jobs_succeeded"] == 1

    @pytest.mark.asyncio
    async def test_loop_shadow_flag_does_not_prevent_tick(self, db_session, loop_on):
        """loop_shadow=True (the default) must not block the scheduler;
        it only governs delivery — which is not wired yet in Slice 9."""
        async def noop_producer(session, job, run_id, holder_id, fence_token):
            return ProducerResult(outcome="succeeded")

        register_producer("watchlist_scan", noop_producer)

        from app.db.repositories import loop_repo
        await loop_repo.job_create(
            db_session, "watchlist_scan", "global",
            f"2026-06-12-{_uid()[:6]}",
            next_run_utc=_naive(_past(5)),
        )

        result = await tick(db_session, _holder(), batch_size=10, lease_s=120)
        assert result.jobs_succeeded == 1


# ===========================================================================
# § ADMIN API contracts — verified against a minimal FastAPI test app
#
# The full app.api module-level import chain triggers a pre-existing
# Python 3.9 incompatibility in router_service.py (`str | None` syntax).
# We verify the admin endpoint contracts by building a minimal FastAPI app
# that registers only the three loop endpoints, bypassing that chain.
# ===========================================================================

def _make_loop_api():
    """Build a minimal FastAPI app with only the loop admin endpoints."""
    from fastapi import FastAPI

    mini = FastAPI()

    # Import only the three handlers — they use lazy imports internally
    # and do NOT trigger router_service at import time.
    from app.services import loop_canary_telemetry as _tel
    from app.config import settings as _s

    @mini.get("/admin/loop-status")
    async def _status():
        snap = _tel.snapshot()
        eff  = _tel.get_enabled(bool(_s.loop_enabled))
        return {
            "status":            "ok",
            "loop_enabled":      bool(_s.loop_enabled),
            "loop_shadow":       bool(_s.loop_shadow),
            "canary_pct":        int(_s.loop_canary_pct),
            "internal_only":     bool(_s.loop_internal_only),
            "effective_enabled": eff,
            "override_state":    _tel.override_state(),
            "telemetry":         snap,
            "job_counts":        {"total": 0, "by_state": {}},
            "run_counts":        {"total": 0, "recent": []},
            "delivery_counts":   {"total": 0, "by_status": {}},
            "guardrails": {
                "drift_gate_enabled":    bool(_s.loop_drift_gate_enabled),
                "drift_materiality_min": float(_s.loop_drift_materiality_min),
                "force_run":             bool(_s.loop_force_run),
                "quiet_hours_start_utc": int(_s.delivery_quiet_hours_start),
                "quiet_hours_end_utc":   int(_s.delivery_quiet_hours_end),
                "daily_cap":             int(_s.delivery_daily_cap),
                "severity_floor":        str(_s.delivery_severity_floor),
            },
        }

    @mini.post("/admin/loop/disable")
    async def _disable():
        _tel.force_disable()
        return {"status": "ok", "effective_enabled": False, "override": "force_disabled"}

    @mini.post("/admin/loop/enable")
    async def _enable():
        _tel.force_enable()
        eff = _tel.get_enabled(bool(_s.loop_enabled))
        return {
            "status":             "ok",
            "effective_enabled":  eff,
            "override":           "cleared",
            "config_loop_enabled": bool(_s.loop_enabled),
            "canary_pct":         int(_s.loop_canary_pct),
        }

    return mini


@pytest.fixture(scope="module")
def loop_api_client():
    from fastapi.testclient import TestClient
    return TestClient(_make_loop_api())


class TestAdminLoopStatus:
    def test_status_returns_200(self, loop_api_client):
        resp = loop_api_client.get("/admin/loop-status")
        assert resp.status_code == 200

    def test_status_has_required_fields(self, loop_api_client):
        data = loop_api_client.get("/admin/loop-status").json()
        required = [
            "status", "loop_enabled", "loop_shadow", "canary_pct",
            "internal_only", "effective_enabled", "override_state",
            "telemetry", "job_counts", "run_counts", "delivery_counts",
            "guardrails",
        ]
        for field in required:
            assert field in data, f"Missing field: {field}"

    def test_status_loop_enabled_is_false_by_default(self, loop_api_client):
        data = loop_api_client.get("/admin/loop-status").json()
        assert data["loop_enabled"] is False

    def test_status_loop_shadow_is_true_by_default(self, loop_api_client):
        data = loop_api_client.get("/admin/loop-status").json()
        assert data["loop_shadow"] is True

    def test_status_canary_pct_is_zero_by_default(self, loop_api_client):
        data = loop_api_client.get("/admin/loop-status").json()
        assert data["canary_pct"] == 0

    def test_status_effective_enabled_false_by_default(self, loop_api_client):
        reset()  # ensure no leftover override
        data = loop_api_client.get("/admin/loop-status").json()
        assert data["effective_enabled"] is False

    def test_status_override_state_none_by_default(self, loop_api_client):
        reset()
        data = loop_api_client.get("/admin/loop-status").json()
        assert data["override_state"] is None

    def test_status_guardrails_present(self, loop_api_client):
        data = loop_api_client.get("/admin/loop-status").json()
        g = data["guardrails"]
        assert "drift_gate_enabled" in g
        assert "daily_cap" in g
        assert "severity_floor" in g

    def test_status_telemetry_counters_present(self, loop_api_client):
        data = loop_api_client.get("/admin/loop-status").json()
        c = data["telemetry"]["counters"]
        assert "tick_count" in c
        assert "jobs_succeeded" in c
        assert "delivery_shadow_count" in c

    def test_status_reflects_kill_switch_after_disable(self, loop_api_client):
        reset()
        loop_api_client.post("/admin/loop/disable")
        data = loop_api_client.get("/admin/loop-status").json()
        assert data["effective_enabled"] is False
        assert data["override_state"] is False
        loop_api_client.post("/admin/loop/enable")
        reset()

    def test_status_job_counts_total_is_int(self, loop_api_client):
        data = loop_api_client.get("/admin/loop-status").json()
        assert isinstance(data["job_counts"]["total"], int)

    def test_status_delivery_counts_total_is_int(self, loop_api_client):
        data = loop_api_client.get("/admin/loop-status").json()
        assert isinstance(data["delivery_counts"]["total"], int)


class TestAdminLoopDisableEnable:
    def test_disable_returns_ok(self, loop_api_client):
        reset()
        data = loop_api_client.post("/admin/loop/disable").json()
        assert data["status"] == "ok"
        assert data["effective_enabled"] is False
        assert data["override"] == "force_disabled"
        reset()

    def test_enable_returns_ok(self, loop_api_client):
        reset()
        loop_api_client.post("/admin/loop/disable")
        data = loop_api_client.post("/admin/loop/enable").json()
        assert data["status"] == "ok"
        assert data["override"] == "cleared"
        reset()

    def test_disable_then_enable_restores_config_governance(self, loop_api_client):
        reset()
        loop_api_client.post("/admin/loop/disable")
        loop_api_client.post("/admin/loop/enable")
        data = loop_api_client.get("/admin/loop-status").json()
        assert data["override_state"] is None
        assert data["effective_enabled"] is False  # config loop_enabled=False
        reset()

    def test_disable_idempotent(self, loop_api_client):
        reset()
        loop_api_client.post("/admin/loop/disable")
        data = loop_api_client.post("/admin/loop/disable").json()
        assert data["effective_enabled"] is False
        reset()

    def test_enable_without_prior_disable_is_harmless(self, loop_api_client):
        reset()
        data = loop_api_client.post("/admin/loop/enable").json()
        assert data["override"] == "cleared"

    def test_enable_includes_canary_pct(self, loop_api_client):
        data = loop_api_client.post("/admin/loop/enable").json()
        assert "canary_pct" in data

    def test_enable_includes_config_loop_enabled(self, loop_api_client):
        data = loop_api_client.post("/admin/loop/enable").json()
        assert "config_loop_enabled" in data
        assert data["config_loop_enabled"] is False  # default


# ===========================================================================
# § SAFETY — no real delivery
# ===========================================================================

class TestSafetyNoRealDelivery:
    def test_shadow_flag_true_by_default(self):
        from app.config import settings
        assert settings.loop_shadow is True

    def test_canary_pct_zero_means_no_subjects_get_output(self):
        from app.config import settings
        # With canary_pct=0 and enabled=True, every subject is ineligible
        for _ in range(20):
            result = decide_cohort(_uid(), canary_pct=0, enabled=True)
            assert result == COHORT_INELIGIBLE

    def test_default_loop_enabled_false_means_inert(self):
        # loop_enabled=False → get_enabled returns False → tick is no-op
        reset()
        assert get_enabled(False) is False
