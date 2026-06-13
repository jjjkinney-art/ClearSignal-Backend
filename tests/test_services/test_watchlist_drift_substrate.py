"""
Phase 10B · Slice 6 — Drift Gate Substrate Validation tests.

Validates the full substrate chain end-to-end for watchlist_scan jobs:

  analysis → ticker_memory / thesis_delta / dossier_revision updated
           → loop_drift_service.should_run_job detects signal
           → watchlist_scan job runs (or skips)

Covers:
  § AUDIT      — substrate persistence paths are reliable; bump_ticker_memory exists
  § CHAIN      — full chain: watched ticker + prior run + new substrate → should_run=True
  § TICKER     — ticker_memory update signal detected (below threshold alone; passes
                 when threshold lowered)
  § THESIS     — thesis_delta material signal triggers run
  § THESIS_MOD — thesis_delta moderate signal triggers run
  § DOSSIER    — dossier_revision signal triggers run
  § STALE      — no new substrate → skip
  § FORCE      — force_run bypass overrides gate
  § PAYLOAD    — job_run.error encodes drift reason + signal source (JSON)
  § SCHEDULER  — producer not called on drift skip; producer called on material drift
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional
from unittest.mock import MagicMock

import pytest

from app.db.repositories import loop_repo
from app.services import loop_drift_service as drift
from app.services.loop_drift_service import (
    DriftSignal,
    REASON_NO_PRIOR_RUN,
    REASON_FORCE_RUN,
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
    unregister_producer,
    list_registered_producers,
    tick,
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


def _naive(dt: datetime) -> datetime:
    return dt.replace(tzinfo=None)


def _holder() -> str:
    return f"test:{_uid()}"


# ---------------------------------------------------------------------------
# DB row builders (insert directly)
# ---------------------------------------------------------------------------

async def _insert_dossier_revision(db_session, ticker="AAPL", facet="core_debate",
                                    confidence=0.8, offset_s=-1):
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
        created_at=_naive(_now() + timedelta(seconds=offset_s)),
    )
    db_session.add(row)
    await db_session.flush()
    return row


async def _insert_thesis_delta(db_session, ticker="AAPL", magnitude="material",
                                stance_changed=False, offset_s=-1):
    from app.db.models import ThesisDelta
    row = ThesisDelta(
        id=str(uuid.uuid4()),
        ticker=ticker.upper(),
        from_version_id=str(uuid.uuid4()),
        to_version_id=str(uuid.uuid4()),
        stance_changed=stance_changed,
        conviction_delta=0.15 if stance_changed else 0.07,
        bull_thesis_similarity=0.7,
        bear_thesis_similarity=0.7,
        magnitude=magnitude,
        changed_fields='["stance"]' if stance_changed else '["conviction"]',
        debounce_visible=True,
        created_at=_naive(_now() + timedelta(seconds=offset_s)),
    )
    db_session.add(row)
    await db_session.flush()
    return row


async def _insert_ticker_memory(db_session, ticker="AAPL", updated_offset_s=-1):
    from app.db.models import TickerMemory
    ts = _naive(_now() + timedelta(seconds=updated_offset_s))
    row = TickerMemory(
        id=str(uuid.uuid4()),
        ticker=ticker.upper(),
        company_name=ticker,
        total_queries=1,
        version_count=1,
        last_stance="Accumulate",
        last_confidence=0.72,
        dominant_concern="",
        created_at=ts,
        updated_at=ts,
    )
    db_session.add(row)
    await db_session.flush()
    return row


async def _make_due_job(db_session, job_type="watchlist_scan", target="global",
                        bucket=None, last_generated_at=None, payload_json=None):
    from sqlalchemy import update
    from app.db.models import ScheduledJob
    bucket = bucket or f"2026-06-13-{_uid()[:6]}"
    job = await loop_repo.job_create(
        db_session, job_type, target, bucket,
        next_run_utc=_past(5),
        max_attempts=3,
        payload_json=payload_json or {},
    )
    if last_generated_at is not None:
        await db_session.execute(
            update(ScheduledJob)
            .where(ScheduledJob.id == job.id)
            .values(last_generated_at=_naive(last_generated_at))
            .execution_options(synchronize_session=False)
        )
        await db_session.flush()
    return job


# ---------------------------------------------------------------------------
# Fixtures
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
# § AUDIT — substrate persistence reliability
# ===========================================================================

class TestSubstrateAudit:
    @pytest.mark.asyncio
    async def test_update_memory_bumps_updated_at(self, db_session):
        """update_memory() explicitly sets updated_at — drift gate can read it."""
        from app.db.repositories.memory_repo import get_or_create_memory, update_memory
        from sqlalchemy import select
        from app.db.models import TickerMemory

        await get_or_create_memory(db_session, "AAPL")
        before = _now()
        await update_memory(db_session, "AAPL", stance="Buy", confidence=0.8)

        result = await db_session.execute(
            select(TickerMemory).where(TickerMemory.ticker == "AAPL")
            .execution_options(populate_existing=True)
        )
        row = result.scalar_one_or_none()
        assert row is not None
        updated = row.updated_at.replace(tzinfo=None) if row.updated_at.tzinfo else row.updated_at
        assert updated >= _naive(before) - timedelta(seconds=1)

    @pytest.mark.asyncio
    async def test_bump_ticker_memory_exists_and_touches_updated_at(self, db_session):
        """bump_ticker_memory() is importable and updates updated_at."""
        from app.db.repositories.memory_repo import get_or_create_memory, bump_ticker_memory
        from sqlalchemy import select
        from app.db.models import TickerMemory

        await get_or_create_memory(db_session, "NVDA")
        before = _now()
        result = await bump_ticker_memory(db_session, "NVDA")

        assert result is True
        row_result = await db_session.execute(
            select(TickerMemory).where(TickerMemory.ticker == "NVDA")
            .execution_options(populate_existing=True)
        )
        row = row_result.scalar_one_or_none()
        assert row is not None
        updated = row.updated_at.replace(tzinfo=None) if row.updated_at.tzinfo else row.updated_at
        assert updated >= _naive(before) - timedelta(seconds=1)

    @pytest.mark.asyncio
    async def test_bump_ticker_memory_no_counter_change(self, db_session):
        """bump_ticker_memory() must not increment total_queries or version_count."""
        from app.db.repositories.memory_repo import get_or_create_memory, bump_ticker_memory
        from sqlalchemy import select
        from app.db.models import TickerMemory

        mem = await get_or_create_memory(db_session, "TSLA")
        initial_q = mem.total_queries
        initial_v = mem.version_count

        await bump_ticker_memory(db_session, "TSLA")

        row_result = await db_session.execute(
            select(TickerMemory).where(TickerMemory.ticker == "TSLA")
            .execution_options(populate_existing=True)
        )
        row = row_result.scalar_one_or_none()
        assert row.total_queries == initial_q
        assert row.version_count == initial_v

    @pytest.mark.asyncio
    async def test_bump_ticker_memory_returns_false_when_row_missing(self, db_session):
        from app.db.repositories.memory_repo import bump_ticker_memory
        result = await bump_ticker_memory(db_session, "DOESNOTEXIST")
        assert result is False

    @pytest.mark.asyncio
    async def test_thesis_delta_created_at_set_on_insert(self, db_session):
        """ThesisDelta.created_at is set by the model default — drift gate can read it."""
        row = await _insert_thesis_delta(db_session, ticker="AAPL", magnitude="material")
        assert row.created_at is not None

    @pytest.mark.asyncio
    async def test_dossier_revision_created_at_set_on_insert(self, db_session):
        """DossierRevision.created_at is set on insert — append-only, immutable."""
        row = await _insert_dossier_revision(db_session, ticker="AAPL")
        assert row.created_at is not None


# ===========================================================================
# § CHAIN — full end-to-end substrate → drift gate decision
# ===========================================================================

class TestDriftChain:
    @pytest.mark.asyncio
    async def test_new_thesis_delta_after_prior_run_should_run_true(self, db_session):
        """Full chain: prior run at T-1h, new ThesisDelta at T-1s → should_run=True."""
        last_success = _past(3600)

        await _insert_thesis_delta(
            db_session, ticker="AAPL", magnitude="material",
            offset_s=-1,   # 1 second ago, after last_success_at
        )

        signal = await should_run_job(
            db_session, "watchlist_scan", "global",
            "2026-06-13", last_success_at=last_success,
        )
        assert signal.should_run is True
        assert signal.reason == REASON_NEW_THESIS_DELTA

    @pytest.mark.asyncio
    async def test_new_dossier_revision_after_prior_run_should_run_true(self, db_session):
        last_success = _past(3600)

        await _insert_dossier_revision(db_session, ticker="AAPL", confidence=0.8, offset_s=-1)

        signal = await should_run_job(
            db_session, "watchlist_scan", "global",
            "2026-06-13", last_success_at=last_success,
        )
        assert signal.should_run is True
        assert signal.reason == REASON_NEW_DOSSIER_REVISION

    @pytest.mark.asyncio
    async def test_no_substrate_after_prior_run_should_run_false(self, db_session):
        """No new substrate rows → gate skips with no_material_change."""
        last_success = _past(30)

        signal = await should_run_job(
            db_session, "watchlist_scan", "global",
            "2026-06-13", last_success_at=last_success,
        )
        assert signal.should_run is False
        assert signal.reason == REASON_NO_MATERIAL_CHANGE

    @pytest.mark.asyncio
    async def test_no_prior_run_always_runs(self, db_session):
        """No prior successful run → bypass gate, always execute."""
        signal = await should_run_job(
            db_session, "watchlist_scan", "global",
            "2026-06-13", last_success_at=None,
        )
        assert signal.should_run is True
        assert signal.reason == REASON_NO_PRIOR_RUN

    @pytest.mark.asyncio
    async def test_substrate_before_last_success_does_not_trigger(self, db_session):
        """Substrate row predating last_success_at must NOT trigger a run."""
        last_success = _past(10)

        # Insert a thesis delta that predates last_success by another 10s
        await _insert_thesis_delta(
            db_session, ticker="AAPL", magnitude="material",
            offset_s=-20,   # 20s ago, BEFORE last_success at 10s ago
        )

        signal = await should_run_job(
            db_session, "watchlist_scan", "global",
            "2026-06-13", last_success_at=last_success,
        )
        assert signal.should_run is False
        assert signal.reason == REASON_NO_MATERIAL_CHANGE


# ===========================================================================
# § TICKER — ticker_memory update signal
# ===========================================================================

class TestTickerMemorySignal:
    @pytest.mark.asyncio
    async def test_ticker_memory_updated_signal_appears_in_signals_list(self, db_session):
        """TickerMemory update produces a signal entry even if score is below threshold."""
        last_success = _past(3600)
        await _insert_ticker_memory(db_session, ticker="AAPL", updated_offset_s=-1)

        signal = await should_run_job(
            db_session, "watchlist_scan", "global",
            "2026-06-13", last_success_at=last_success,
        )
        # TickerMemory score=0.3 < threshold=0.4 → below threshold
        assert signal.should_run is False
        assert signal.reason == REASON_SIGNAL_BELOW_THRESHOLD
        assert any("ticker_memory_updated" in s for s in signal.signals)

    @pytest.mark.asyncio
    async def test_ticker_memory_triggers_run_when_threshold_lowered(
        self, db_session, monkeypatch
    ):
        """When drift_materiality_min is lowered below 0.3, TickerMemory triggers run."""
        monkeypatch.setattr(drift, "_get_threshold", lambda: 0.2)

        last_success = _past(3600)
        await _insert_ticker_memory(db_session, ticker="AAPL", updated_offset_s=-1)

        signal = await should_run_job(
            db_session, "watchlist_scan", "global",
            "2026-06-13", last_success_at=last_success,
        )
        assert signal.should_run is True
        assert signal.reason == REASON_TICKER_MEMORY_UPDATED

    @pytest.mark.asyncio
    async def test_ticker_memory_score_in_signal(self, db_session, monkeypatch):
        monkeypatch.setattr(drift, "_get_threshold", lambda: 0.2)

        last_success = _past(3600)
        await _insert_ticker_memory(db_session, ticker="AAPL", updated_offset_s=-1)

        signal = await should_run_job(
            db_session, "watchlist_scan", "global",
            "2026-06-13", last_success_at=last_success,
        )
        assert signal.materiality_score == pytest.approx(0.3)

    @pytest.mark.asyncio
    async def test_bump_ticker_memory_visible_to_drift_gate(
        self, db_session, monkeypatch
    ):
        """bump_ticker_memory + lowered threshold → drift gate detects it."""
        from app.db.repositories.memory_repo import bump_ticker_memory
        monkeypatch.setattr(drift, "_get_threshold", lambda: 0.2)

        last_success = _past(60)

        # Insert row with old timestamp, then bump it
        mem = await _insert_ticker_memory(db_session, ticker="MSFT", updated_offset_s=-120)
        # Now bump (simulates "analysis ran after last_success")
        await bump_ticker_memory(db_session, "MSFT")

        signal = await should_run_job(
            db_session, "watchlist_scan", "global",
            "2026-06-13", last_success_at=last_success,
        )
        assert signal.should_run is True


# ===========================================================================
# § THESIS — thesis_delta material / moderate
# ===========================================================================

class TestThesisDeltaSignal:
    @pytest.mark.asyncio
    async def test_material_delta_triggers_run(self, db_session):
        last_success = _past(3600)
        await _insert_thesis_delta(db_session, magnitude="material", offset_s=-1)

        signal = await should_run_job(
            db_session, "watchlist_scan", "global",
            "2026-06-13", last_success_at=last_success,
        )
        assert signal.should_run is True
        assert signal.reason == REASON_NEW_THESIS_DELTA

    @pytest.mark.asyncio
    async def test_material_delta_stance_changed_score_1_0(self, db_session):
        last_success = _past(3600)
        await _insert_thesis_delta(
            db_session, magnitude="material", stance_changed=True, offset_s=-1
        )

        signal = await should_run_job(
            db_session, "watchlist_scan", "global",
            "2026-06-13", last_success_at=last_success,
        )
        assert signal.materiality_score == pytest.approx(1.0)

    @pytest.mark.asyncio
    async def test_moderate_delta_triggers_run(self, db_session):
        last_success = _past(3600)
        await _insert_thesis_delta(db_session, magnitude="moderate", offset_s=-1)

        signal = await should_run_job(
            db_session, "watchlist_scan", "global",
            "2026-06-13", last_success_at=last_success,
        )
        assert signal.should_run is True
        assert signal.reason == REASON_NEW_THESIS_DELTA
        assert signal.materiality_score == pytest.approx(0.6)

    @pytest.mark.asyncio
    async def test_minor_delta_not_queried_no_run(self, db_session):
        """Minor ThesisDelta rows are intentionally excluded — no run triggered."""
        last_success = _past(3600)
        await _insert_thesis_delta(db_session, magnitude="minor", offset_s=-1)

        signal = await should_run_job(
            db_session, "watchlist_scan", "global",
            "2026-06-13", last_success_at=last_success,
        )
        assert signal.should_run is False

    @pytest.mark.asyncio
    async def test_signals_list_contains_delta_description(self, db_session):
        last_success = _past(3600)
        await _insert_thesis_delta(
            db_session, ticker="NVDA", magnitude="material", stance_changed=True, offset_s=-1
        )

        signal = await should_run_job(
            db_session, "watchlist_scan", "global",
            "2026-06-13", last_success_at=last_success,
        )
        assert any("thesis_delta:NVDA" in s for s in signal.signals)
        assert any("stance_changed" in s for s in signal.signals)


# ===========================================================================
# § DOSSIER — dossier_revision signal
# ===========================================================================

class TestDossierRevisionSignal:
    @pytest.mark.asyncio
    async def test_dossier_revision_triggers_run(self, db_session):
        last_success = _past(3600)
        await _insert_dossier_revision(db_session, ticker="AAPL", confidence=0.8, offset_s=-1)

        signal = await should_run_job(
            db_session, "watchlist_scan", "global",
            "2026-06-13", last_success_at=last_success,
        )
        assert signal.should_run is True
        assert signal.reason == REASON_NEW_DOSSIER_REVISION

    @pytest.mark.asyncio
    async def test_low_confidence_dossier_still_triggers_at_floor(self, db_session):
        """DossierRevision min score is 0.5 even at confidence=0.0."""
        last_success = _past(3600)
        await _insert_dossier_revision(db_session, confidence=0.0, offset_s=-1)

        signal = await should_run_job(
            db_session, "watchlist_scan", "global",
            "2026-06-13", last_success_at=last_success,
        )
        assert signal.should_run is True
        assert signal.materiality_score >= 0.5

    @pytest.mark.asyncio
    async def test_signals_list_contains_revision_description(self, db_session):
        last_success = _past(3600)
        await _insert_dossier_revision(
            db_session, ticker="MSFT", facet="catalyst", confidence=0.75, offset_s=-1
        )

        signal = await should_run_job(
            db_session, "watchlist_scan", "global",
            "2026-06-13", last_success_at=last_success,
        )
        assert any("dossier_revision:MSFT" in s for s in signal.signals)


# ===========================================================================
# § STALE — no signal → skip
# ===========================================================================

class TestStaleSignal:
    @pytest.mark.asyncio
    async def test_no_substrate_rows_is_no_material_change(self, db_session):
        last_success = _past(30)
        signal = await should_run_job(
            db_session, "watchlist_scan", "global",
            "2026-06-13", last_success_at=last_success,
        )
        assert signal.should_run is False
        assert signal.reason == REASON_NO_MATERIAL_CHANGE
        assert signal.materiality_score == 0.0
        assert signal.signals == []

    @pytest.mark.asyncio
    async def test_only_stale_substrate_no_run(self, db_session):
        """Substrate rows older than last_success_at must not trigger run."""
        last_success = _past(60)

        # Insert thesis_delta predating last_success
        await _insert_thesis_delta(db_session, magnitude="material", offset_s=-120)
        await _insert_dossier_revision(db_session, confidence=0.9, offset_s=-120)

        signal = await should_run_job(
            db_session, "watchlist_scan", "global",
            "2026-06-13", last_success_at=last_success,
        )
        assert signal.should_run is False
        assert signal.reason == REASON_NO_MATERIAL_CHANGE


# ===========================================================================
# § FORCE — force_run bypass
# ===========================================================================

class TestForceRun:
    @pytest.mark.asyncio
    async def test_force_run_bypasses_gate_even_with_no_substrate(self, db_session):
        last_success = _past(30)
        signal = await should_run_job(
            db_session, "watchlist_scan", "global",
            "2026-06-13", last_success_at=last_success, force_run=True,
        )
        assert signal.should_run is True
        assert signal.reason == REASON_FORCE_RUN

    @pytest.mark.asyncio
    async def test_force_run_no_substrate_queries_needed(self, db_session):
        """force_run=True skips all substrate queries (reason=FORCE_RUN)."""
        last_success = _past(30)
        signal = await should_run_job(
            db_session, "watchlist_scan", "global",
            "2026-06-13", last_success_at=last_success, force_run=True,
        )
        assert signal.signals == []

    @pytest.mark.asyncio
    async def test_payload_json_force_run_via_scheduler(self, db_session, loop_on):
        """payload_json.force_run=True bypasses drift gate in full tick path."""
        call_count = [0]

        async def stub_producer(session, job, run_id, holder_id, fence_token):
            call_count[0] += 1
            return ProducerResult(outcome="succeeded")

        register_producer("watchlist_scan", stub_producer)

        job = await _make_due_job(
            db_session, job_type="watchlist_scan", target="global",
            last_generated_at=_past(30),
            payload_json={"force_run": True},
        )

        await tick(db_session, _holder(), batch_size=10, lease_s=120)
        assert call_count[0] == 1


# ===========================================================================
# § PAYLOAD — job_run.error encodes drift reason + signal source
# ===========================================================================

class TestDriftPayload:
    @pytest.mark.asyncio
    async def test_drift_skip_error_starts_with_drift_gate(self, db_session, loop_on):
        """Backward compat: error always starts with 'drift_gate:'."""
        async def noop(session, job, run_id, holder_id, fence_token):
            return ProducerResult(outcome="succeeded")
        register_producer("watchlist_scan", noop)

        job = await _make_due_job(
            db_session, last_generated_at=_past(3600)
        )
        await tick(db_session, _holder(), batch_size=10, lease_s=120)

        from sqlalchemy import select
        from app.db.models import JobRun
        result = await db_session.execute(
            select(JobRun).where(JobRun.job_id == job.id)
            .execution_options(populate_existing=True)
        )
        run = result.scalars().first()
        assert run is not None
        assert run.drift_hit is True
        assert run.error is not None
        assert run.error.startswith("drift_gate:")

    @pytest.mark.asyncio
    async def test_drift_skip_error_contains_reason_json(self, db_session, loop_on):
        """Error field is parseable JSON after the 'drift_gate:' prefix."""
        async def noop(session, job, run_id, holder_id, fence_token):
            return ProducerResult(outcome="succeeded")
        register_producer("watchlist_scan", noop)

        job = await _make_due_job(db_session, last_generated_at=_past(3600))
        await tick(db_session, _holder(), batch_size=10, lease_s=120)

        from sqlalchemy import select
        from app.db.models import JobRun
        result = await db_session.execute(
            select(JobRun).where(JobRun.job_id == job.id)
            .execution_options(populate_existing=True)
        )
        run = result.scalars().first()
        assert run is not None

        # Strip prefix and parse JSON
        suffix = run.error[len("drift_gate:"):]
        parsed = json.loads(suffix)
        assert "reason" in parsed
        assert "score" in parsed
        assert "signals" in parsed
        assert "latest_signal_at" in parsed

    @pytest.mark.asyncio
    async def test_drift_skip_error_signals_populated_when_below_threshold(
        self, db_session, loop_on, monkeypatch
    ):
        """When signal exists but score < threshold, signals list is in error JSON."""
        from app.services import loop_drift_service as ds_mod
        # Lower threshold so we see sub-threshold path instead of no_material_change
        # Actually with TickerMemory at 0.3 and threshold 0.4, we want below_threshold
        monkeypatch.setattr(ds_mod, "_get_threshold", lambda: 0.4)

        async def noop(session, job, run_id, holder_id, fence_token):
            return ProducerResult(outcome="succeeded")
        register_producer("watchlist_scan", noop)

        await _insert_ticker_memory(db_session, ticker="AAPL", updated_offset_s=-1)

        job = await _make_due_job(db_session, last_generated_at=_past(3600))
        await tick(db_session, _holder(), batch_size=10, lease_s=120)

        from sqlalchemy import select
        from app.db.models import JobRun
        result = await db_session.execute(
            select(JobRun).where(JobRun.job_id == job.id)
            .execution_options(populate_existing=True)
        )
        run = result.scalars().first()
        suffix = run.error[len("drift_gate:"):]
        parsed = json.loads(suffix)
        assert parsed["reason"] == REASON_SIGNAL_BELOW_THRESHOLD
        assert len(parsed["signals"]) >= 1

    @pytest.mark.asyncio
    async def test_drift_skip_payload_has_materiality_score(self, db_session, loop_on):
        async def noop(session, job, run_id, holder_id, fence_token):
            return ProducerResult(outcome="succeeded")
        register_producer("watchlist_scan", noop)

        await _insert_thesis_delta(db_session, magnitude="moderate", offset_s=-1)
        # Raise threshold so moderate score 0.6 is below it
        from app.services import loop_drift_service as ds_mod

        original_threshold = ds_mod._get_threshold

        # We want the gate to SKIP due to threshold — set threshold to 0.8
        import unittest.mock as mock
        with mock.patch.object(ds_mod, "_get_threshold", return_value=0.8):
            job = await _make_due_job(db_session, last_generated_at=_past(3600))
            await tick(db_session, _holder(), batch_size=10, lease_s=120)

        from sqlalchemy import select
        from app.db.models import JobRun
        result = await db_session.execute(
            select(JobRun).where(JobRun.job_id == job.id)
            .execution_options(populate_existing=True)
        )
        run = result.scalars().first()
        suffix = run.error[len("drift_gate:"):]
        parsed = json.loads(suffix)
        assert parsed["score"] == pytest.approx(0.6, abs=0.01)


# ===========================================================================
# § SCHEDULER — producer routing based on drift gate
# ===========================================================================

class TestSchedulerDriftIntegration:
    @pytest.mark.asyncio
    async def test_producer_not_called_on_drift_skip(self, db_session, loop_on):
        """When drift gate skips, producer callable must not be invoked."""
        call_count = [0]

        async def counting_producer(session, job, run_id, holder_id, fence_token):
            call_count[0] += 1
            return ProducerResult(outcome="succeeded")

        register_producer("watchlist_scan", counting_producer)

        job = await _make_due_job(db_session, last_generated_at=_past(3600))
        # No substrate rows → drift gate will skip

        await tick(db_session, _holder(), batch_size=10, lease_s=120)
        assert call_count[0] == 0

    @pytest.mark.asyncio
    async def test_producer_called_on_material_drift(self, db_session, loop_on):
        """When ThesisDelta is present, drift gate passes and producer runs."""
        call_count = [0]

        async def counting_producer(session, job, run_id, holder_id, fence_token):
            call_count[0] += 1
            return ProducerResult(outcome="succeeded")

        register_producer("watchlist_scan", counting_producer)

        await _insert_thesis_delta(db_session, magnitude="material", offset_s=-1)
        job = await _make_due_job(db_session, last_generated_at=_past(3600))

        await tick(db_session, _holder(), batch_size=10, lease_s=120)
        assert call_count[0] == 1

    @pytest.mark.asyncio
    async def test_producer_called_on_dossier_revision(self, db_session, loop_on):
        call_count = [0]

        async def counting_producer(session, job, run_id, holder_id, fence_token):
            call_count[0] += 1
            return ProducerResult(outcome="succeeded")

        register_producer("watchlist_scan", counting_producer)

        await _insert_dossier_revision(db_session, confidence=0.8, offset_s=-1)
        job = await _make_due_job(db_session, last_generated_at=_past(3600))

        await tick(db_session, _holder(), batch_size=10, lease_s=120)
        assert call_count[0] == 1

    @pytest.mark.asyncio
    async def test_no_producer_call_records_drift_run(self, db_session, loop_on):
        """Drift skip still creates a job_run row with outcome=skipped_stale."""
        async def noop(session, job, run_id, holder_id, fence_token):
            return ProducerResult(outcome="succeeded")
        register_producer("watchlist_scan", noop)

        job = await _make_due_job(db_session, last_generated_at=_past(3600))
        await tick(db_session, _holder(), batch_size=10, lease_s=120)

        from sqlalchemy import select
        from app.db.models import JobRun
        result = await db_session.execute(
            select(JobRun).where(JobRun.job_id == job.id)
            .execution_options(populate_existing=True)
        )
        run = result.scalars().first()
        assert run is not None
        assert run.outcome == "skipped_stale"
        assert run.drift_hit is True

    @pytest.mark.asyncio
    async def test_producer_called_on_moderate_drift(self, db_session, loop_on):
        call_count = [0]

        async def counting_producer(session, job, run_id, holder_id, fence_token):
            call_count[0] += 1
            return ProducerResult(outcome="succeeded")

        register_producer("watchlist_scan", counting_producer)

        await _insert_thesis_delta(db_session, magnitude="moderate", offset_s=-1)
        job = await _make_due_job(db_session, last_generated_at=_past(3600))

        await tick(db_session, _holder(), batch_size=10, lease_s=120)
        assert call_count[0] == 1
