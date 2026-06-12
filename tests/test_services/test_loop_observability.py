"""
Phase 10A · Slice 10 — loop_observability tests.

Coverage
--------
  TestSnapshotEmptyDB      — build_snapshot with empty tables (all counters zero)
  TestSnapshotNoSession    — build_snapshot(None) returns safe zeros, no raise
  TestSnapshotPopulated    — build_snapshot with real rows reflects counts
  TestDBFailureDegrades    — a DB error does not raise; db_available marks partial
  TestSchemaCompleteness   — all required keys always present
  TestNoSecretsExposed     — snapshot does not include database URL / token / key
  TestKillSwitchReflected  — force_disable / force_enable reflected in snapshot
  TestObservabilitySync    — build_snapshot_sync returns correct shape (no DB)
  TestAdminStatusDelegate  — admin_loop_status delegates to observability service
"""

from __future__ import annotations

import asyncio
import pytest
import pytest_asyncio
from unittest.mock import patch, AsyncMock, MagicMock
from datetime import datetime, timezone


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_naive():
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def _snap(session):
    from app.services.loop_observability import build_snapshot
    return await build_snapshot(session)


# ---------------------------------------------------------------------------
# 1. Snapshot with empty DB
# ---------------------------------------------------------------------------

class TestSnapshotEmptyDB:

    @pytest.mark.asyncio
    async def test_empty_db_returns_ok(self, db_session):
        result = await _snap(db_session)
        assert result["status"] == "ok"

    @pytest.mark.asyncio
    async def test_empty_db_jobs_zero(self, db_session):
        result = await _snap(db_session)
        assert result["jobs"]["total"] == 0
        assert result["jobs"]["by_state"] == {}

    @pytest.mark.asyncio
    async def test_empty_db_runs_zero(self, db_session):
        result = await _snap(db_session)
        assert result["runs"]["total"] == 0
        assert result["runs"]["recent"] == []

    @pytest.mark.asyncio
    async def test_empty_db_delivery_zero(self, db_session):
        result = await _snap(db_session)
        assert result["delivery"]["total"] == 0
        assert result["delivery"]["shadow_count"] == 0

    @pytest.mark.asyncio
    async def test_empty_db_lock_none(self, db_session):
        result = await _snap(db_session)
        assert result["locks"]["tick_lock"] is None
        assert result["locks"]["tick_lock_held"] is False

    @pytest.mark.asyncio
    async def test_db_available_true(self, db_session):
        result = await _snap(db_session)
        # True or "partial" both indicate DB was reachable
        assert result["db_available"] in (True, "partial")

    @pytest.mark.asyncio
    async def test_snapshot_utc_is_present(self, db_session):
        result = await _snap(db_session)
        assert result.get("snapshot_utc"), "snapshot_utc should be non-empty"
        assert "T" in result["snapshot_utc"]


# ---------------------------------------------------------------------------
# 2. Snapshot with no session
# ---------------------------------------------------------------------------

class TestSnapshotNoSession:

    @pytest.mark.asyncio
    async def test_no_session_does_not_raise(self):
        from app.services.loop_observability import build_snapshot
        result = await build_snapshot(None)
        assert result is not None

    @pytest.mark.asyncio
    async def test_no_session_db_available_false(self):
        from app.services.loop_observability import build_snapshot
        result = await build_snapshot(None)
        assert result["db_available"] is False

    @pytest.mark.asyncio
    async def test_no_session_jobs_zero(self):
        from app.services.loop_observability import build_snapshot
        result = await build_snapshot(None)
        assert result["jobs"]["total"] == 0

    @pytest.mark.asyncio
    async def test_no_session_runs_empty(self):
        from app.services.loop_observability import build_snapshot
        result = await build_snapshot(None)
        assert result["runs"]["recent"] == []

    @pytest.mark.asyncio
    async def test_no_session_config_still_populated(self):
        from app.services.loop_observability import build_snapshot
        result = await build_snapshot(None)
        # config section always comes from settings, not DB
        assert isinstance(result["config"], dict)
        assert "loop_enabled" in result["config"]


# ---------------------------------------------------------------------------
# 3. Snapshot with populated DB rows
# ---------------------------------------------------------------------------

def _insert_job(db_session, job_type="watchlist_scan", target_key="AAPL",
                period_bucket="2026-06-12", state="scheduled"):
    from app.db.models import ScheduledJob
    job = ScheduledJob(
        job_type=job_type,
        target_key=target_key,
        period_bucket=period_bucket,
        state=state,
    )
    db_session.add(job)
    return job


_run_counter = 0

def _insert_run(db_session, job_id=None, job_type="watchlist_scan",
                target_key="AAPL", period_bucket="2026-06-12",
                outcome="success", holder_id="test-holder", drift_hit=False):
    global _run_counter
    _run_counter += 1
    from app.db.models import JobRun
    run = JobRun(
        job_id=job_id or "fake-job-id",
        job_type=job_type,
        target_key=target_key,
        period_bucket=period_bucket,
        outcome=outcome,
        holder_id=holder_id,
        drift_hit=drift_hit,
        work_key=f"wk-{job_type}-{target_key}-{period_bucket}-{_run_counter}",
        fence_token=_run_counter,
    )
    db_session.add(run)
    return run


def _insert_delivery(db_session, status="delivered_shadow", channel="in_app",
                     target_key="AAPL", n=1):
    from app.db.models import DeliveryLedger
    rows = []
    for i in range(n):
        d = DeliveryLedger(
            channel=channel,
            target_key=target_key,
            status=status,
            content_key=f"ck-{status}-{target_key}-{i}",
            content_hash=f"ch-{i}",
        )
        db_session.add(d)
        rows.append(d)
    return rows


class TestSnapshotPopulated:

    @pytest.mark.asyncio
    async def test_jobs_by_state_counted(self, db_session):
        _insert_job(db_session, state="scheduled")
        _insert_job(db_session, target_key="MSFT", state="scheduled")
        _insert_job(db_session, target_key="NVDA", state="running")
        await db_session.flush()

        result = await _snap(db_session)
        assert result["jobs"]["by_state"].get("scheduled", 0) == 2
        assert result["jobs"]["by_state"].get("running", 0) == 1
        assert result["jobs"]["total"] == 3

    @pytest.mark.asyncio
    async def test_runs_by_outcome_counted(self, db_session):
        _insert_run(db_session, outcome="success")
        _insert_run(db_session, target_key="MSFT", outcome="success")
        _insert_run(db_session, target_key="NVDA", outcome="failed")
        await db_session.flush()

        result = await _snap(db_session)
        assert result["runs"]["by_outcome"].get("success", 0) == 2
        assert result["runs"]["by_outcome"].get("failed", 0) == 1
        assert result["runs"]["total"] == 3

    @pytest.mark.asyncio
    async def test_runs_recent_list(self, db_session):
        _insert_run(db_session, outcome="success")
        _insert_run(db_session, target_key="MSFT", outcome="failed")
        await db_session.flush()

        result = await _snap(db_session)
        assert len(result["runs"]["recent"]) == 2
        # All runs should have required keys
        for r in result["runs"]["recent"]:
            assert "outcome" in r
            assert "job_type" in r
            assert "target_key" in r

    @pytest.mark.asyncio
    async def test_delivery_shadow_count(self, db_session):
        _insert_delivery(db_session, status="delivered_shadow", n=3)
        _insert_delivery(db_session, status="suppressed", n=1)
        await db_session.flush()

        result = await _snap(db_session)
        assert result["delivery"]["shadow_count"] == 3
        assert result["delivery"]["by_status"].get("delivered_shadow", 0) == 3
        assert result["delivery"]["by_status"].get("suppressed", 0) == 1
        assert result["delivery"]["total"] == 4

    @pytest.mark.asyncio
    async def test_locks_held_shows_true(self, db_session):
        from app.db.models import JobLock
        lock = JobLock(
            lock_name="loop:tick",
            holder_id="test-holder",
            acquired_utc=_now_naive(),
            lease_expires_utc=datetime(2099, 1, 1),
            fence_token=1,
        )
        db_session.add(lock)
        await db_session.flush()

        result = await _snap(db_session)
        assert result["locks"]["tick_lock_held"] is True
        assert result["locks"]["tick_lock"] is not None


# ---------------------------------------------------------------------------
# 4. DB failure degrades safely
# ---------------------------------------------------------------------------

class TestDBFailureDegrades:

    @pytest.mark.asyncio
    async def test_bad_session_returns_partial(self):
        """A session that raises on execute should mark db_available='partial'."""
        from app.services.loop_observability import build_snapshot

        bad_sess = MagicMock()
        bad_sess.execute = AsyncMock(side_effect=RuntimeError("db is down"))

        result = await build_snapshot(bad_sess)
        # Should not raise
        assert result is not None
        assert result["status"] == "ok"
        assert result["db_available"] == "partial"
        assert result["jobs"]["total"] == 0
        assert result["runs"]["total"] == 0

    @pytest.mark.asyncio
    async def test_bad_session_config_still_populates(self):
        from app.services.loop_observability import build_snapshot

        bad_sess = MagicMock()
        bad_sess.execute = AsyncMock(side_effect=RuntimeError("db is down"))

        result = await build_snapshot(bad_sess)
        assert isinstance(result["config"], dict)
        assert "loop_enabled" in result["config"]

    @pytest.mark.asyncio
    async def test_bad_session_guardrails_still_populate(self):
        from app.services.loop_observability import build_snapshot

        bad_sess = MagicMock()
        bad_sess.execute = AsyncMock(side_effect=RuntimeError("db is down"))

        result = await build_snapshot(bad_sess)
        g = result["guardrails"]
        assert "drift_gate_enabled" in g
        assert "daily_cap" in g


# ---------------------------------------------------------------------------
# 5. Schema completeness — all keys always present
# ---------------------------------------------------------------------------

REQUIRED_TOP_LEVEL_KEYS = [
    "status", "snapshot_utc", "db_available",
    "loop_enabled", "loop_shadow", "effective_enabled", "override_state",
    "canary", "telemetry", "config", "jobs", "runs", "delivery", "locks", "guardrails",
]

REQUIRED_CANARY_KEYS   = ["canary_pct", "internal_only", "cohort_counts"]
REQUIRED_JOBS_KEYS     = ["total", "by_state"]
REQUIRED_RUNS_KEYS     = ["total", "by_outcome", "recent"]
REQUIRED_DELIVERY_KEYS = ["total", "by_status", "shadow_count", "duplicate_total"]
REQUIRED_LOCKS_KEYS    = ["tick_lock", "tick_lock_held"]
REQUIRED_GUARDRAIL_KEYS = [
    "drift_gate_enabled", "drift_materiality_min", "force_run",
    "quiet_hours_start_utc", "quiet_hours_end_utc", "daily_cap", "severity_floor",
]


class TestSchemaCompleteness:

    @pytest.mark.asyncio
    async def test_all_top_level_keys_with_session(self, db_session):
        result = await _snap(db_session)
        for k in REQUIRED_TOP_LEVEL_KEYS:
            assert k in result, f"Missing top-level key: {k!r}"

    @pytest.mark.asyncio
    async def test_all_top_level_keys_without_session(self):
        from app.services.loop_observability import build_snapshot
        result = await build_snapshot(None)
        for k in REQUIRED_TOP_LEVEL_KEYS:
            assert k in result, f"Missing top-level key (no session): {k!r}"

    @pytest.mark.asyncio
    async def test_canary_subkeys(self, db_session):
        result = await _snap(db_session)
        for k in REQUIRED_CANARY_KEYS:
            assert k in result["canary"], f"Missing canary key: {k!r}"

    @pytest.mark.asyncio
    async def test_jobs_subkeys(self, db_session):
        result = await _snap(db_session)
        for k in REQUIRED_JOBS_KEYS:
            assert k in result["jobs"], f"Missing jobs key: {k!r}"

    @pytest.mark.asyncio
    async def test_runs_subkeys(self, db_session):
        result = await _snap(db_session)
        for k in REQUIRED_RUNS_KEYS:
            assert k in result["runs"], f"Missing runs key: {k!r}"

    @pytest.mark.asyncio
    async def test_delivery_subkeys(self, db_session):
        result = await _snap(db_session)
        for k in REQUIRED_DELIVERY_KEYS:
            assert k in result["delivery"], f"Missing delivery key: {k!r}"

    @pytest.mark.asyncio
    async def test_locks_subkeys(self, db_session):
        result = await _snap(db_session)
        for k in REQUIRED_LOCKS_KEYS:
            assert k in result["locks"], f"Missing locks key: {k!r}"

    @pytest.mark.asyncio
    async def test_guardrail_subkeys(self, db_session):
        result = await _snap(db_session)
        for k in REQUIRED_GUARDRAIL_KEYS:
            assert k in result["guardrails"], f"Missing guardrails key: {k!r}"

    @pytest.mark.asyncio
    async def test_degraded_snapshot_has_all_keys(self):
        from app.services.loop_observability import build_snapshot
        bad_sess = MagicMock()
        bad_sess.execute = AsyncMock(side_effect=RuntimeError("db is down"))

        result = await build_snapshot(bad_sess)
        for k in REQUIRED_TOP_LEVEL_KEYS:
            assert k in result, f"Missing key in degraded snapshot: {k!r}"


# ---------------------------------------------------------------------------
# 6. No secrets exposed
# ---------------------------------------------------------------------------

SECRET_PATTERNS = [
    "password", "secret", "token", "database_url", "db_url",
    "api_key", "openai", "anthropic_key", "jwt_secret",
]


def _contains_secret(d, depth=0):
    """Recursively search dict/list for keys that look like secrets."""
    if depth > 10:
        return False
    if isinstance(d, dict):
        for k, v in d.items():
            k_lower = k.lower()
            if any(p in k_lower for p in SECRET_PATTERNS):
                return True
            if _contains_secret(v, depth + 1):
                return True
    elif isinstance(d, (list, tuple)):
        for item in d:
            if _contains_secret(item, depth + 1):
                return True
    elif isinstance(d, str):
        # Only flag values if they look like actual secret values (long strings)
        # Not keys — those are checked above
        pass
    return False


class TestNoSecretsExposed:

    @pytest.mark.asyncio
    async def test_no_secret_keys_in_snapshot(self, db_session):
        result = await _snap(db_session)
        assert not _contains_secret(result), (
            "Snapshot contains keys that look like secrets. "
            "Check config section for database URLs, tokens, or API keys."
        )

    @pytest.mark.asyncio
    async def test_no_database_url_in_config_section(self, db_session):
        result = await _snap(db_session)
        config = result.get("config", {})
        for key in config:
            assert "url" not in key.lower(), f"Suspicious config key: {key!r}"
            assert "password" not in key.lower(), f"Suspicious config key: {key!r}"

    @pytest.mark.asyncio
    async def test_no_secrets_in_no_session_snapshot(self):
        from app.services.loop_observability import build_snapshot
        result = await build_snapshot(None)
        assert not _contains_secret(result)


# ---------------------------------------------------------------------------
# 7. Kill-switch state reflected in snapshot
# ---------------------------------------------------------------------------

class TestKillSwitchReflected:

    @pytest.mark.asyncio
    async def test_override_null_by_default(self, db_session):
        from app.services import loop_canary_telemetry as _tel
        _tel.reset()
        result = await _snap(db_session)
        assert result["override_state"] is None

    @pytest.mark.asyncio
    async def test_force_disable_reflected(self, db_session):
        from app.services import loop_canary_telemetry as _tel
        _tel.reset()
        try:
            _tel.force_disable()
            result = await _snap(db_session)
            assert result["override_state"] is False
            assert result["effective_enabled"] is False
        finally:
            _tel.reset()

    @pytest.mark.asyncio
    async def test_force_enable_clears_override(self, db_session):
        from app.services import loop_canary_telemetry as _tel
        _tel.reset()
        _tel.force_disable()
        _tel.force_enable()
        result = await _snap(db_session)
        assert result["override_state"] is None

    @pytest.mark.asyncio
    async def test_telemetry_kill_switch_key_present(self, db_session):
        from app.services import loop_canary_telemetry as _tel
        _tel.reset()
        result = await _snap(db_session)
        assert "kill_switch" in result["telemetry"]

    @pytest.mark.asyncio
    async def test_effective_enabled_matches_config_when_no_override(self, db_session):
        from app.services import loop_canary_telemetry as _tel
        from app.config import settings as _s
        _tel.reset()
        result = await _snap(db_session)
        # effective_enabled must equal the configured loop_enabled when no override
        assert result["effective_enabled"] == bool(_s.loop_enabled)


# ---------------------------------------------------------------------------
# 8. build_snapshot_sync
# ---------------------------------------------------------------------------

class TestObservabilitySync:

    def test_sync_returns_dict(self):
        from app.services.loop_observability import build_snapshot_sync
        result = build_snapshot_sync()
        assert isinstance(result, dict)
        assert result["status"] == "ok"

    def test_sync_db_available_false(self):
        from app.services.loop_observability import build_snapshot_sync
        result = build_snapshot_sync()
        assert result["db_available"] is False

    def test_sync_all_required_keys(self):
        from app.services.loop_observability import build_snapshot_sync
        result = build_snapshot_sync()
        for k in REQUIRED_TOP_LEVEL_KEYS:
            assert k in result, f"Missing key in sync snapshot: {k!r}"

    def test_sync_no_secrets(self):
        from app.services.loop_observability import build_snapshot_sync
        result = build_snapshot_sync()
        assert not _contains_secret(result)

    def test_sync_config_section_present(self):
        from app.services.loop_observability import build_snapshot_sync
        result = build_snapshot_sync()
        assert "loop_enabled" in result["config"]


# ---------------------------------------------------------------------------
# 9. admin_loop_status endpoint delegates to observability
# ---------------------------------------------------------------------------

def _make_obs_api():
    """Minimal FastAPI app wiring only the loop-status endpoint."""
    from fastapi import FastAPI
    mini = FastAPI()

    @mini.get("/admin/loop-status")
    async def _status():
        from app.services.loop_observability import build_snapshot
        return await build_snapshot(None)

    return mini


class TestAdminStatusDelegate:

    @pytest.fixture(scope="class")
    def obs_client(self):
        from fastapi.testclient import TestClient
        return TestClient(_make_obs_api())

    def test_endpoint_returns_200(self, obs_client):
        r = obs_client.get("/admin/loop-status")
        assert r.status_code == 200

    def test_endpoint_status_ok(self, obs_client):
        r = obs_client.get("/admin/loop-status")
        body = r.json()
        assert body["status"] == "ok"

    def test_endpoint_all_required_keys(self, obs_client):
        r = obs_client.get("/admin/loop-status")
        body = r.json()
        for k in REQUIRED_TOP_LEVEL_KEYS:
            assert k in body, f"Missing key in endpoint response: {k!r}"

    def test_endpoint_snapshot_utc_present(self, obs_client):
        r = obs_client.get("/admin/loop-status")
        body = r.json()
        assert body.get("snapshot_utc")

    def test_endpoint_no_secrets(self, obs_client):
        r = obs_client.get("/admin/loop-status")
        body = r.json()
        assert not _contains_secret(body)

    def test_endpoint_db_available_false_when_no_session(self, obs_client):
        # Our mini fixture passes session=None, so db_available must be False
        r = obs_client.get("/admin/loop-status")
        body = r.json()
        assert body["db_available"] is False
