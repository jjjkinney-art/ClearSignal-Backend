"""
Phase 10A · Slice 7 — Drift signal reader and materiality gate tests.

Covers:
  § SIGNAL     — DriftSignal shape and reason constants
  § BYPASS     — no prior run, force_run, gate disabled, no session
  § SUBSTRATE  — DossierRevision, ThesisDelta, TickerMemory queries
  § GATE       — no change → skipped; sub-threshold signal → skipped; material → runs
  § SCHEDULER  — drift gate wired into tick(); audit run recorded; force_run override
  § IDEMPOTENCY — idempotency still fires before drift gate
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional
from unittest.mock import AsyncMock, patch

import pytest

from app.db.repositories import loop_repo
from app.services import loop_drift_service as drift
from app.services.loop_drift_service import (
    DriftSignal,
    REASON_NO_PRIOR_RUN,
    REASON_FORCE_RUN,
    REASON_GATE_DISABLED,
    REASON_NO_SESSION,
    REASON_NEW_DOSSIER_REVISION,
    REASON_NEW_THESIS_DELTA,
    REASON_TICKER_MEMORY_UPDATED,
    REASON_NO_MATERIAL_CHANGE,
    REASON_SIGNAL_BELOW_THRESHOLD,
    should_run_job,
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
    return uuid.uuid4().hex[:10]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _past(s: int = 5) -> datetime:
    return _now() - timedelta(seconds=s)


def _future(s: int = 5) -> datetime:
    return _now() + timedelta(seconds=s)


def _naive(dt: datetime) -> datetime:
    return dt.replace(tzinfo=None)


def _holder() -> str:
    return f"test:{_uid()}"


async def _make_due_job(db_session, job_type="watchlist_scan",
                        target="global", bucket=None, max_attempts=3,
                        payload_json=None):
    bucket = bucket or f"2026-06-12-{_uid()[:6]}"
    return await loop_repo.job_create(
        db_session, job_type, target, bucket,
        next_run_utc=_past(5),
        max_attempts=max_attempts,
        payload_json=payload_json or {},
    )


# ---------------------------------------------------------------------------
# Substrate row builders (insert directly into db_session)
# ---------------------------------------------------------------------------

async def _insert_dossier_revision(db_session, ticker="AAPL", facet="core_debate",
                                   confidence=0.8, created_offset_s=-1):
    """Insert a DossierRevision row created `created_offset_s` seconds ago."""
    from app.db.models import DossierRevision
    row = DossierRevision(
        id=str(uuid.uuid4()),
        ticker=ticker.upper(),
        facet=facet,
        new_version=1,
        change_summary="test revision",
        diff_json={},
        confidence=confidence,
        source_version_id=None,
        session_id=_uid(),
        user_id=None,
        created_at=_naive(_now() + timedelta(seconds=created_offset_s)),
    )
    db_session.add(row)
    await db_session.flush()
    return row


async def _insert_thesis_delta(db_session, ticker="AAPL", magnitude="material",
                                stance_changed=False, created_offset_s=-1):
    """Insert a ThesisDelta row."""
    from app.db.models import ThesisDelta
    fv_id = str(uuid.uuid4())
    tv_id = str(uuid.uuid4())
    row = ThesisDelta(
        id=str(uuid.uuid4()),
        ticker=ticker.upper(),
        from_version_id=fv_id,
        to_version_id=tv_id,
        stance_changed=stance_changed,
        conviction_delta=0.1 if stance_changed else 0.05,
        bull_thesis_similarity=0.7,
        bear_thesis_similarity=0.7,
        magnitude=magnitude,
        changed_fields='["stance"]' if stance_changed else '["conviction"]',
        debounce_visible=True,
        created_at=_naive(_now() + timedelta(seconds=created_offset_s)),
    )
    db_session.add(row)
    await db_session.flush()
    return row


async def _insert_ticker_memory(db_session, ticker="AAPL", updated_offset_s=-1):
    """Insert a TickerMemory row with updated_at in the past."""
    from app.db.models import TickerMemory
    ts = _naive(_now() + timedelta(seconds=updated_offset_s))
    row = TickerMemory(
        id=str(uuid.uuid4()),
        ticker=ticker.upper(),
        company_name=ticker,
        total_queries=1,
        version_count=1,
        last_stance="Accumulate",
        last_confidence=0.7,
        dominant_concern="",
        created_at=ts,
        updated_at=ts,
    )
    db_session.add(row)
    await db_session.flush()
    return row


# ---------------------------------------------------------------------------
# Auto-clean producers
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def clean_producers():
    yield
    for jt in list(list_registered_producers()):
        unregister_producer(jt)


@pytest.fixture
def loop_on(monkeypatch):
    from app.services import loop_scheduler_service as sched
    monkeypatch.setattr(sched, "_is_loop_enabled", lambda: True)


# ===========================================================================
# § SIGNAL shape
# ===========================================================================

class TestDriftSignalShape:
    def test_should_run_true_fields(self):
        s = DriftSignal(should_run=True, reason=REASON_NO_PRIOR_RUN)
        assert s.should_run is True
        assert s.reason == REASON_NO_PRIOR_RUN
        assert s.signals == []
        assert s.latest_signal_at is None
        assert s.materiality_score == 0.0

    def test_should_run_false_fields(self):
        s = DriftSignal(
            should_run=False,
            reason=REASON_NO_MATERIAL_CHANGE,
            signals=[],
            latest_signal_at=None,
            materiality_score=0.0,
        )
        assert s.should_run is False

    def test_all_reason_constants_are_strings(self):
        for const in [
            REASON_NO_PRIOR_RUN, REASON_FORCE_RUN, REASON_GATE_DISABLED,
            REASON_NO_SESSION, REASON_NEW_DOSSIER_REVISION, REASON_NEW_THESIS_DELTA,
            REASON_TICKER_MEMORY_UPDATED, REASON_NO_MATERIAL_CHANGE,
            REASON_SIGNAL_BELOW_THRESHOLD,
        ]:
            assert isinstance(const, str) and const


# ===========================================================================
# § BYPASS cases
# ===========================================================================

class TestDriftGateBypass:
    @pytest.mark.asyncio
    async def test_no_prior_run_always_runs(self, db_session):
        signal = await should_run_job(db_session, "watchlist_scan", "global", "2026-06-12", None)
        assert signal.should_run is True
        assert signal.reason == REASON_NO_PRIOR_RUN

    @pytest.mark.asyncio
    async def test_no_session_bypasses(self):
        signal = await should_run_job(None, "watchlist_scan", "global", "2026-06-12", _past(3600))
        assert signal.should_run is True
        assert signal.reason == REASON_NO_SESSION

    @pytest.mark.asyncio
    async def test_force_run_bypasses_gate(self, db_session):
        # No substrate changes — but force_run=True should override
        last = _past(3600)
        signal = await should_run_job(db_session, "watchlist_scan", "global", "2026-06-12",
                                      last, force_run=True)
        assert signal.should_run is True
        assert signal.reason == REASON_FORCE_RUN

    @pytest.mark.asyncio
    async def test_gate_disabled_bypasses(self, db_session, monkeypatch):
        monkeypatch.setattr(drift, "_gate_enabled", lambda: False)
        last = _past(3600)
        signal = await should_run_job(db_session, "watchlist_scan", "global", "2026-06-12", last)
        assert signal.should_run is True
        assert signal.reason == REASON_GATE_DISABLED

    @pytest.mark.asyncio
    async def test_force_run_bypasses_even_with_no_signals(self, db_session):
        last = _past(10)  # Recent last_success — nothing new
        # Don't insert any substrate rows
        signal = await should_run_job(db_session, "watchlist_scan", "global", "2026-06-12",
                                      last, force_run=True)
        assert signal.should_run is True
        assert signal.reason == REASON_FORCE_RUN


# ===========================================================================
# § SUBSTRATE signals
# ===========================================================================

class TestSubstrateSignals:
    @pytest.mark.asyncio
    async def test_no_substrate_change_skips(self, db_session):
        last = _past(10)
        # No substrate rows inserted after last
        signal = await should_run_job(db_session, "watchlist_scan", "global", "2026-06-12", last)
        assert signal.should_run is False
        assert signal.reason == REASON_NO_MATERIAL_CHANGE

    @pytest.mark.asyncio
    async def test_new_dossier_revision_triggers_run(self, db_session):
        last = _past(3600)
        # Insert a DossierRevision created 1s ago (after last_success)
        await _insert_dossier_revision(db_session, ticker="AAPL", confidence=0.8,
                                       created_offset_s=-1)
        signal = await should_run_job(db_session, "watchlist_scan", "global", "2026-06-12", last)
        assert signal.should_run is True
        assert signal.reason == REASON_NEW_DOSSIER_REVISION
        assert signal.materiality_score >= 0.5
        assert any("dossier_revision" in s for s in signal.signals)

    @pytest.mark.asyncio
    async def test_new_material_thesis_delta_triggers_run(self, db_session):
        last = _past(3600)
        await _insert_thesis_delta(db_session, ticker="NVDA", magnitude="material",
                                   stance_changed=False, created_offset_s=-1)
        signal = await should_run_job(db_session, "watchlist_scan", "global", "2026-06-12", last)
        assert signal.should_run is True
        assert signal.reason == REASON_NEW_THESIS_DELTA
        assert signal.materiality_score >= 0.9
        assert any("thesis_delta" in s for s in signal.signals)

    @pytest.mark.asyncio
    async def test_stance_changed_thesis_delta_max_score(self, db_session):
        last = _past(3600)
        await _insert_thesis_delta(db_session, ticker="NVDA", magnitude="material",
                                   stance_changed=True, created_offset_s=-1)
        signal = await should_run_job(db_session, "watchlist_scan", "global", "2026-06-12", last)
        assert signal.should_run is True
        assert signal.materiality_score == 1.0
        assert any("stance_changed" in s for s in signal.signals)

    @pytest.mark.asyncio
    async def test_moderate_thesis_delta_triggers_run(self, db_session):
        last = _past(3600)
        await _insert_thesis_delta(db_session, ticker="JPM", magnitude="moderate",
                                   created_offset_s=-1)
        signal = await should_run_job(db_session, "watchlist_scan", "global", "2026-06-12", last)
        assert signal.should_run is True
        assert signal.materiality_score == pytest.approx(0.6)

    @pytest.mark.asyncio
    async def test_ticker_memory_only_is_sub_threshold(self, db_session):
        """TickerMemory update alone (score=0.3) should NOT trigger execution."""
        last = _past(3600)
        await _insert_ticker_memory(db_session, ticker="MSFT", updated_offset_s=-1)
        signal = await should_run_job(db_session, "watchlist_scan", "global", "2026-06-12", last)
        assert signal.should_run is False
        assert signal.reason == REASON_SIGNAL_BELOW_THRESHOLD
        assert signal.materiality_score == pytest.approx(0.3)

    @pytest.mark.asyncio
    async def test_old_substrate_rows_do_not_trigger(self, db_session):
        """Substrate rows created BEFORE last_success_at must not be counted."""
        # last_success is 30 minutes ago; substrate row is 2 hours old
        last = _past(1800)  # 30 min ago
        await _insert_dossier_revision(db_session, ticker="TSLA", confidence=0.9,
                                       created_offset_s=-7200)  # 2 hours ago
        signal = await should_run_job(db_session, "watchlist_scan", "global", "2026-06-12", last)
        assert signal.should_run is False
        assert signal.reason == REASON_NO_MATERIAL_CHANGE

    @pytest.mark.asyncio
    async def test_ticker_specific_ignores_other_tickers(self, db_session):
        """A ticker-specific job (e.g. timeline_rollup for AAPL) should NOT
        trigger from a DossierRevision for NVDA."""
        last = _past(3600)
        await _insert_dossier_revision(db_session, ticker="NVDA", confidence=0.9,
                                       created_offset_s=-1)
        signal = await should_run_job(db_session, "timeline_rollup", "AAPL", "2026-06-12", last)
        assert signal.should_run is False

    @pytest.mark.asyncio
    async def test_ticker_specific_matches_own_ticker(self, db_session):
        last = _past(3600)
        await _insert_dossier_revision(db_session, ticker="AAPL", confidence=0.9,
                                       created_offset_s=-1)
        signal = await should_run_job(db_session, "timeline_rollup", "AAPL", "2026-06-12", last)
        assert signal.should_run is True

    @pytest.mark.asyncio
    async def test_latest_signal_at_is_populated(self, db_session):
        last = _past(3600)
        await _insert_dossier_revision(db_session, ticker="AAPL", confidence=0.8,
                                       created_offset_s=-1)
        signal = await should_run_job(db_session, "watchlist_scan", "global", "2026-06-12", last)
        assert signal.should_run is True
        assert signal.latest_signal_at is not None

    @pytest.mark.asyncio
    async def test_dossier_revision_low_confidence_floor(self, db_session):
        """DossierRevision with confidence=0.0 still scores at the 0.5 floor."""
        last = _past(3600)
        await _insert_dossier_revision(db_session, ticker="GS", confidence=0.0,
                                       created_offset_s=-1)
        signal = await should_run_job(db_session, "watchlist_scan", "global", "2026-06-12", last)
        assert signal.should_run is True
        assert signal.materiality_score == pytest.approx(0.5)

    @pytest.mark.asyncio
    async def test_multiple_signals_max_score(self, db_session):
        """When both DossierRevision and ThesisDelta present, score = max."""
        last = _past(3600)
        await _insert_dossier_revision(db_session, ticker="AAPL", confidence=0.6,
                                       created_offset_s=-2)
        await _insert_thesis_delta(db_session, ticker="AAPL", magnitude="material",
                                   stance_changed=True, created_offset_s=-1)
        signal = await should_run_job(db_session, "watchlist_scan", "global", "2026-06-12", last)
        assert signal.should_run is True
        assert signal.materiality_score == pytest.approx(1.0)
        assert len(signal.signals) >= 2


# ===========================================================================
# § SCHEDULER integration
# ===========================================================================

class TestSchedulerDriftIntegration:
    @pytest.mark.asyncio
    async def test_drift_gate_skips_producer_call(self, db_session, loop_on):
        """
        When drift gate returns should_run=False, the producer must not be called.
        """
        call_count = [0]

        async def counting_producer(session, job, run_id, holder_id, fence_token):
            call_count[0] += 1
            return ProducerResult(outcome="succeeded")

        register_producer("watchlist_scan", counting_producer)
        job = await _make_due_job(db_session, job_type="watchlist_scan", target="global")

        # Manually set last_generated_at to recent, so gate evaluates
        # No substrate rows → drift gate skips
        from sqlalchemy import update as sa_update
        from app.db.models import ScheduledJob
        await db_session.execute(
            sa_update(ScheduledJob)
            .where(ScheduledJob.id == job.id)
            .values(last_generated_at=_naive(_past(3600)))
            .execution_options(synchronize_session=False)
        )

        result = await tick(db_session, _holder(), batch_size=10, lease_s=120)
        assert result.jobs_short_circuited == 1
        assert call_count[0] == 0  # Producer NOT called

    @pytest.mark.asyncio
    async def test_drift_gate_allows_producer_when_dossier_revision_present(
        self, db_session, loop_on
    ):
        """Drift gate passes when a new DossierRevision exists since last run."""
        call_count = [0]

        async def counting_producer(session, job, run_id, holder_id, fence_token):
            call_count[0] += 1
            return ProducerResult(outcome="succeeded")

        register_producer("watchlist_scan", counting_producer)

        # Set last_generated_at to 1 hour ago, then insert a recent revision
        last_ts = _naive(_past(3600))
        await _insert_dossier_revision(db_session, ticker="AAPL", confidence=0.8,
                                       created_offset_s=-1)

        job = await _make_due_job(db_session, job_type="watchlist_scan", target="global")
        from sqlalchemy import update as sa_update
        from app.db.models import ScheduledJob
        await db_session.execute(
            sa_update(ScheduledJob)
            .where(ScheduledJob.id == job.id)
            .values(last_generated_at=last_ts)
            .execution_options(synchronize_session=False)
        )

        result = await tick(db_session, _holder(), batch_size=10, lease_s=120)
        assert result.jobs_succeeded == 1
        assert call_count[0] == 1  # Producer WAS called

    @pytest.mark.asyncio
    async def test_drift_gate_audit_run_records_reason(self, db_session, loop_on):
        """When drift gate skips, a JobRun with outcome=skipped_stale and drift_hit=True
        must be appended, with error starting with 'drift_gate:'."""
        async def noop_producer(session, job, run_id, holder_id, fence_token):
            return ProducerResult(outcome="succeeded")

        register_producer("watchlist_scan", noop_producer)

        from sqlalchemy import update as sa_update
        from app.db.models import ScheduledJob, JobRun
        from sqlalchemy import select

        job = await _make_due_job(db_session, job_type="watchlist_scan", target="global")
        await db_session.execute(
            sa_update(ScheduledJob)
            .where(ScheduledJob.id == job.id)
            .values(last_generated_at=_naive(_past(3600)))
            .execution_options(synchronize_session=False)
        )

        # No substrate rows → drift gate skips
        await tick(db_session, _holder(), batch_size=10, lease_s=120)

        # Verify audit run
        result = await db_session.execute(
            select(JobRun).where(JobRun.job_id == job.id)
            .execution_options(populate_existing=True)
        )
        runs = result.scalars().all()
        assert len(runs) >= 1
        drift_run = next((r for r in runs if r.outcome == "skipped_stale"), None)
        assert drift_run is not None
        assert drift_run.drift_hit is True
        assert drift_run.error is not None
        assert drift_run.error.startswith("drift_gate:")

    @pytest.mark.asyncio
    async def test_force_run_via_payload_json_bypasses_gate(self, db_session, loop_on):
        """payload_json.force_run=True should cause the producer to be called
        even with no substrate changes."""
        call_count = [0]

        async def counting_producer(session, job, run_id, holder_id, fence_token):
            call_count[0] += 1
            return ProducerResult(outcome="succeeded")

        register_producer("watchlist_scan", counting_producer)

        # No substrate rows; last_generated_at = 1 hour ago; force_run in payload
        job = await _make_due_job(db_session, job_type="watchlist_scan", target="global",
                                  payload_json={"force_run": True})
        from sqlalchemy import update as sa_update
        from app.db.models import ScheduledJob
        await db_session.execute(
            sa_update(ScheduledJob)
            .where(ScheduledJob.id == job.id)
            .values(last_generated_at=_naive(_past(3600)))
            .execution_options(synchronize_session=False)
        )

        result = await tick(db_session, _holder(), batch_size=10, lease_s=120)
        assert result.jobs_succeeded == 1
        assert call_count[0] == 1  # Producer called despite no substrate changes

    @pytest.mark.asyncio
    async def test_no_prior_run_dispatches_without_substrate(self, db_session, loop_on):
        """First-ever run (last_generated_at=None) dispatches regardless of substrate."""
        call_count = [0]

        async def counting_producer(session, job, run_id, holder_id, fence_token):
            call_count[0] += 1
            return ProducerResult(outcome="succeeded")

        register_producer("watchlist_scan", counting_producer)
        job = await _make_due_job(db_session, job_type="watchlist_scan", target="global")
        # last_generated_at is already NULL (default)

        result = await tick(db_session, _holder(), batch_size=10, lease_s=120)
        assert result.jobs_succeeded == 1
        assert call_count[0] == 1

    @pytest.mark.asyncio
    async def test_idempotency_fires_before_drift_gate(self, db_session, loop_on):
        """
        Idempotency check (work_key already succeeded) must short-circuit BEFORE
        the drift gate is evaluated.  Producer must never be called.
        """
        call_count = [0]
        drift_call_count = [0]

        async def counting_producer(session, job, run_id, holder_id, fence_token):
            call_count[0] += 1
            return ProducerResult(outcome="succeeded")

        # Patch drift gate to count calls
        original_should_run = drift.should_run_job

        async def spy_should_run(*args, **kwargs):
            drift_call_count[0] += 1
            return await original_should_run(*args, **kwargs)

        register_producer("watchlist_scan", counting_producer)
        job = await _make_due_job(db_session, job_type="watchlist_scan",
                                  target="user_idem_01", bucket="2026-06-12")

        # Tick 1 — succeeds
        with patch.object(drift, "should_run_job", side_effect=spy_should_run):
            r1 = await tick(db_session, _holder(), batch_size=10, lease_s=120)
        assert r1.jobs_succeeded == 1
        drift_calls_after_tick1 = drift_call_count[0]

        # Reset to scheduled + backdate next_run_utc
        from sqlalchemy import update as sa_update
        from app.db.models import ScheduledJob
        await loop_repo.job_update_state(db_session, job.id, "scheduled")
        await db_session.execute(
            sa_update(ScheduledJob)
            .where(ScheduledJob.id == job.id)
            .values(next_run_utc=_naive(_past(10)))
            .execution_options(synchronize_session=False)
        )

        # Tick 2 — idempotency fires, drift gate NOT evaluated
        with patch.object(drift, "should_run_job", side_effect=spy_should_run):
            r2 = await tick(db_session, _holder(), batch_size=10, lease_s=120)
        assert r2.jobs_short_circuited == 1
        # Drift gate was NOT called in tick 2 (idempotency short-circuited first)
        drift_calls_after_tick2 = drift_call_count[0]
        assert drift_calls_after_tick2 == drift_calls_after_tick1

    @pytest.mark.asyncio
    async def test_loop_force_run_config_bypasses_gate(self, db_session, loop_on, monkeypatch):
        """settings.loop_force_run=True bypasses the gate for all jobs."""
        call_count = [0]

        async def counting_producer(session, job, run_id, holder_id, fence_token):
            call_count[0] += 1
            return ProducerResult(outcome="succeeded")

        register_producer("watchlist_scan", counting_producer)

        from app.services import loop_scheduler_service as sched
        monkeypatch.setattr(sched, "_is_force_run", lambda job: True)

        job = await _make_due_job(db_session, job_type="watchlist_scan", target="global")
        from sqlalchemy import update as sa_update
        from app.db.models import ScheduledJob
        await db_session.execute(
            sa_update(ScheduledJob)
            .where(ScheduledJob.id == job.id)
            .values(last_generated_at=_naive(_past(3600)))
            .execution_options(synchronize_session=False)
        )

        result = await tick(db_session, _holder(), batch_size=10, lease_s=120)
        assert result.jobs_succeeded == 1
        assert call_count[0] == 1
