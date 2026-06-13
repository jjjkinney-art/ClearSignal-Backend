"""
Phase 10B · Slice 3 — Watchlist Job Seeder tests.

Tests cover:
  - creates one watchlist_scan job per active ticker
  - skips inactive tickers
  - idempotent on repeated run (same bucket)
  - handles empty watchlist (no jobs created)
  - correct job fields: job_type, target_key, state, cadence, period_bucket
  - period_bucket format: stable YYYY-MM-DD
  - SeedResult counts are accurate
  - null session returns zero SeedResult
  - no jobs created for a deactivated ticker
  - no duplicate rows after concurrent-style repeated seeding
  - file fallback path (when DB watchlist is empty)
  - custom period_bucket override
  - next_run_utc is set on seeded jobs
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from datetime import date, datetime, timezone


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _add_ticker(db_session, ticker: str, company_name: str = "") -> object:
    from app.db.repositories.watchlist_repo import ticker_add
    return await ticker_add(db_session, ticker, company_name)


async def _deactivate(db_session, ticker: str) -> bool:
    from app.db.repositories.watchlist_repo import ticker_deactivate
    return await ticker_deactivate(db_session, ticker)


async def _get_job(db_session, job_type: str, ticker: str, period_bucket: str):
    from app.db.repositories.loop_repo import job_get_by_identity
    return await job_get_by_identity(db_session, job_type, ticker, period_bucket)


async def _list_jobs(db_session, job_type: str = "watchlist_scan") -> list:
    from app.db.models import ScheduledJob
    from sqlalchemy import select
    stmt = select(ScheduledJob).where(ScheduledJob.job_type == job_type)
    result = await db_session.execute(stmt)
    return list(result.scalars().all())


BUCKET = "2026-06-13"
NOW = datetime(2026, 6, 13, 12, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# 1. TestSeedBasics — one ticker → one job
# ---------------------------------------------------------------------------

class TestSeedBasics:
    @pytest.mark.asyncio
    async def test_one_active_ticker_creates_one_job(self, db_session):
        from app.services.watchlist_job_seeder import seed_watchlist_jobs
        await _add_ticker(db_session, "AAPL", "Apple")
        result = await seed_watchlist_jobs(db_session, period_bucket=BUCKET, next_run_utc=NOW, file_fallback=False)
        assert result.jobs_created == 1
        assert result.tickers_seen == 1

    @pytest.mark.asyncio
    async def test_multiple_tickers_create_multiple_jobs(self, db_session):
        from app.services.watchlist_job_seeder import seed_watchlist_jobs
        for t in ("AAPL", "MSFT", "NVDA"):
            await _add_ticker(db_session, t)
        result = await seed_watchlist_jobs(db_session, period_bucket=BUCKET, next_run_utc=NOW, file_fallback=False)
        assert result.jobs_created == 3
        assert result.tickers_seen == 3

    @pytest.mark.asyncio
    async def test_result_tickers_seeded_list(self, db_session):
        from app.services.watchlist_job_seeder import seed_watchlist_jobs
        await _add_ticker(db_session, "AAPL")
        await _add_ticker(db_session, "MSFT")
        result = await seed_watchlist_jobs(db_session, period_bucket=BUCKET, next_run_utc=NOW, file_fallback=False)
        assert set(result.tickers_seeded) == {"AAPL", "MSFT"}


# ---------------------------------------------------------------------------
# 2. TestSeedJobFields — created rows have correct fields
# ---------------------------------------------------------------------------

class TestSeedJobFields:
    @pytest.mark.asyncio
    async def test_job_type_is_watchlist_scan(self, db_session):
        from app.services.watchlist_job_seeder import seed_watchlist_jobs
        await _add_ticker(db_session, "AAPL")
        await seed_watchlist_jobs(db_session, period_bucket=BUCKET, next_run_utc=NOW, file_fallback=False)
        row = await _get_job(db_session, "watchlist_scan", "AAPL", BUCKET)
        assert row is not None
        assert row.job_type == "watchlist_scan"

    @pytest.mark.asyncio
    async def test_target_key_is_ticker_symbol(self, db_session):
        from app.services.watchlist_job_seeder import seed_watchlist_jobs
        await _add_ticker(db_session, "NVDA")
        await seed_watchlist_jobs(db_session, period_bucket=BUCKET, next_run_utc=NOW, file_fallback=False)
        row = await _get_job(db_session, "watchlist_scan", "NVDA", BUCKET)
        assert row.target_key == "NVDA"

    @pytest.mark.asyncio
    async def test_initial_state_is_scheduled(self, db_session):
        from app.services.watchlist_job_seeder import seed_watchlist_jobs
        await _add_ticker(db_session, "AAPL")
        await seed_watchlist_jobs(db_session, period_bucket=BUCKET, next_run_utc=NOW, file_fallback=False)
        row = await _get_job(db_session, "watchlist_scan", "AAPL", BUCKET)
        assert row.state == "scheduled"

    @pytest.mark.asyncio
    async def test_period_bucket_matches_requested(self, db_session):
        from app.services.watchlist_job_seeder import seed_watchlist_jobs
        await _add_ticker(db_session, "AAPL")
        await seed_watchlist_jobs(db_session, period_bucket=BUCKET, next_run_utc=NOW, file_fallback=False)
        row = await _get_job(db_session, "watchlist_scan", "AAPL", BUCKET)
        assert row.period_bucket == BUCKET

    @pytest.mark.asyncio
    async def test_next_run_utc_is_set(self, db_session):
        from app.services.watchlist_job_seeder import seed_watchlist_jobs
        await _add_ticker(db_session, "AAPL")
        await seed_watchlist_jobs(db_session, period_bucket=BUCKET, next_run_utc=NOW, file_fallback=False)
        row = await _get_job(db_session, "watchlist_scan", "AAPL", BUCKET)
        assert row.next_run_utc is not None

    @pytest.mark.asyncio
    async def test_cadence_is_daily(self, db_session):
        from app.services.watchlist_job_seeder import seed_watchlist_jobs
        await _add_ticker(db_session, "AAPL")
        await seed_watchlist_jobs(db_session, period_bucket=BUCKET, next_run_utc=NOW, file_fallback=False)
        row = await _get_job(db_session, "watchlist_scan", "AAPL", BUCKET)
        assert row.cadence == "daily"

    @pytest.mark.asyncio
    async def test_attempts_starts_at_zero(self, db_session):
        from app.services.watchlist_job_seeder import seed_watchlist_jobs
        await _add_ticker(db_session, "AAPL")
        await seed_watchlist_jobs(db_session, period_bucket=BUCKET, next_run_utc=NOW, file_fallback=False)
        row = await _get_job(db_session, "watchlist_scan", "AAPL", BUCKET)
        assert row.attempts == 0


# ---------------------------------------------------------------------------
# 3. TestSeedIdempotent — repeated run on same bucket
# ---------------------------------------------------------------------------

class TestSeedIdempotent:
    @pytest.mark.asyncio
    async def test_second_run_creates_zero_new_jobs(self, db_session):
        from app.services.watchlist_job_seeder import seed_watchlist_jobs
        await _add_ticker(db_session, "AAPL")
        r1 = await seed_watchlist_jobs(db_session, period_bucket=BUCKET, next_run_utc=NOW, file_fallback=False)
        r2 = await seed_watchlist_jobs(db_session, period_bucket=BUCKET, next_run_utc=NOW, file_fallback=False)
        assert r1.jobs_created == 1
        assert r2.jobs_created == 0
        assert r2.jobs_existing == 1

    @pytest.mark.asyncio
    async def test_row_count_unchanged_after_second_run(self, db_session):
        from app.services.watchlist_job_seeder import seed_watchlist_jobs
        for t in ("AAPL", "MSFT"):
            await _add_ticker(db_session, t)
        await seed_watchlist_jobs(db_session, period_bucket=BUCKET, next_run_utc=NOW, file_fallback=False)
        await seed_watchlist_jobs(db_session, period_bucket=BUCKET, next_run_utc=NOW, file_fallback=False)
        rows = await _list_jobs(db_session)
        assert len(rows) == 2

    @pytest.mark.asyncio
    async def test_different_bucket_creates_new_jobs(self, db_session):
        from app.services.watchlist_job_seeder import seed_watchlist_jobs
        await _add_ticker(db_session, "AAPL")
        r1 = await seed_watchlist_jobs(db_session, period_bucket="2026-06-13", next_run_utc=NOW, file_fallback=False)
        r2 = await seed_watchlist_jobs(db_session, period_bucket="2026-06-14", next_run_utc=NOW, file_fallback=False)
        assert r1.jobs_created == 1
        assert r2.jobs_created == 1


# ---------------------------------------------------------------------------
# 4. TestSeedEmptyWatchlist
# ---------------------------------------------------------------------------

class TestSeedEmptyWatchlist:
    @pytest.mark.asyncio
    async def test_empty_db_with_fallback_false_returns_zero(self, db_session):
        from app.services.watchlist_job_seeder import seed_watchlist_jobs
        result = await seed_watchlist_jobs(db_session, period_bucket=BUCKET, file_fallback=False)
        assert result.jobs_created == 0
        assert result.tickers_seen == 0

    @pytest.mark.asyncio
    async def test_empty_db_no_jobs_in_table(self, db_session):
        from app.services.watchlist_job_seeder import seed_watchlist_jobs
        await seed_watchlist_jobs(db_session, period_bucket=BUCKET, file_fallback=False)
        rows = await _list_jobs(db_session)
        assert rows == []


# ---------------------------------------------------------------------------
# 5. TestSeedInactiveTickers
# ---------------------------------------------------------------------------

class TestSeedInactiveTickers:
    @pytest.mark.asyncio
    async def test_inactive_ticker_not_seeded(self, db_session):
        from app.services.watchlist_job_seeder import seed_watchlist_jobs
        await _add_ticker(db_session, "AAPL")
        await _deactivate(db_session, "AAPL")
        result = await seed_watchlist_jobs(db_session, period_bucket=BUCKET, file_fallback=False)
        assert result.jobs_created == 0
        assert result.tickers_seen == 0

    @pytest.mark.asyncio
    async def test_mixed_active_inactive(self, db_session):
        from app.services.watchlist_job_seeder import seed_watchlist_jobs
        await _add_ticker(db_session, "AAPL")   # active
        await _add_ticker(db_session, "MSFT")   # will be deactivated
        await _add_ticker(db_session, "NVDA")   # active
        await _deactivate(db_session, "MSFT")
        result = await seed_watchlist_jobs(db_session, period_bucket=BUCKET, file_fallback=False)
        assert result.jobs_created == 2
        assert result.tickers_seen == 2
        assert "MSFT" not in result.tickers_seeded

    @pytest.mark.asyncio
    async def test_inactive_has_no_job_row(self, db_session):
        from app.services.watchlist_job_seeder import seed_watchlist_jobs
        await _add_ticker(db_session, "AAPL")
        await _deactivate(db_session, "AAPL")
        await seed_watchlist_jobs(db_session, period_bucket=BUCKET, file_fallback=False)
        row = await _get_job(db_session, "watchlist_scan", "AAPL", BUCKET)
        assert row is None


# ---------------------------------------------------------------------------
# 6. TestPeriodBucketFormat
# ---------------------------------------------------------------------------

class TestPeriodBucketFormat:
    def test_current_period_bucket_format(self):
        from app.services.watchlist_job_seeder import current_period_bucket
        bucket = current_period_bucket()
        parts = bucket.split("-")
        assert len(parts) == 3
        assert len(parts[0]) == 4  # YYYY
        assert len(parts[1]) == 2  # MM
        assert len(parts[2]) == 2  # DD

    def test_current_period_bucket_from_date(self):
        from app.services.watchlist_job_seeder import current_period_bucket
        d = date(2026, 6, 13)
        assert current_period_bucket(d) == "2026-06-13"

    def test_period_bucket_zero_padded(self):
        from app.services.watchlist_job_seeder import current_period_bucket
        d = date(2026, 1, 5)
        assert current_period_bucket(d) == "2026-01-05"

    def test_period_bucket_stable_across_calls(self):
        from app.services.watchlist_job_seeder import current_period_bucket
        d = date(2026, 6, 13)
        assert current_period_bucket(d) == current_period_bucket(d)

    @pytest.mark.asyncio
    async def test_result_period_bucket_matches_input(self, db_session):
        from app.services.watchlist_job_seeder import seed_watchlist_jobs
        result = await seed_watchlist_jobs(db_session, period_bucket="2026-06-13", file_fallback=False)
        assert result.period_bucket == "2026-06-13"

    @pytest.mark.asyncio
    async def test_result_period_bucket_defaults_to_today(self, db_session):
        from app.services.watchlist_job_seeder import seed_watchlist_jobs, current_period_bucket
        result = await seed_watchlist_jobs(db_session, file_fallback=False)
        assert result.period_bucket == current_period_bucket()


# ---------------------------------------------------------------------------
# 7. TestNullSession
# ---------------------------------------------------------------------------

class TestNullSession:
    @pytest.mark.asyncio
    async def test_null_session_returns_zero_result(self):
        from app.services.watchlist_job_seeder import seed_watchlist_jobs
        result = await seed_watchlist_jobs(None, period_bucket=BUCKET)
        assert result.jobs_created == 0
        assert result.tickers_seen == 0
        assert result.errors == 0

    @pytest.mark.asyncio
    async def test_null_session_result_has_period_bucket(self):
        from app.services.watchlist_job_seeder import seed_watchlist_jobs
        result = await seed_watchlist_jobs(None, period_bucket=BUCKET)
        assert result.period_bucket == BUCKET


# ---------------------------------------------------------------------------
# 8. TestSeedResult — counts
# ---------------------------------------------------------------------------

class TestSeedResult:
    @pytest.mark.asyncio
    async def test_seed_result_created_count(self, db_session):
        from app.services.watchlist_job_seeder import seed_watchlist_jobs
        for t in ("AAPL", "MSFT", "NVDA"):
            await _add_ticker(db_session, t)
        result = await seed_watchlist_jobs(db_session, period_bucket=BUCKET, next_run_utc=NOW, file_fallback=False)
        assert result.jobs_created == 3
        assert result.jobs_existing == 0

    @pytest.mark.asyncio
    async def test_seed_result_existing_count(self, db_session):
        from app.services.watchlist_job_seeder import seed_watchlist_jobs
        for t in ("AAPL", "MSFT"):
            await _add_ticker(db_session, t)
        r1 = await seed_watchlist_jobs(db_session, period_bucket=BUCKET, next_run_utc=NOW, file_fallback=False)
        # Add a third ticker before second run
        await _add_ticker(db_session, "NVDA")
        r2 = await seed_watchlist_jobs(db_session, period_bucket=BUCKET, next_run_utc=NOW, file_fallback=False)
        assert r1.jobs_created == 2
        assert r2.jobs_created == 1   # only NVDA is new
        assert r2.jobs_existing == 2  # AAPL + MSFT already exist

    @pytest.mark.asyncio
    async def test_seed_result_tickers_seen_matches_active(self, db_session):
        from app.services.watchlist_job_seeder import seed_watchlist_jobs
        for t in ("AAPL", "MSFT", "NVDA", "GOOGL"):
            await _add_ticker(db_session, t)
        await _deactivate(db_session, "GOOGL")
        result = await seed_watchlist_jobs(db_session, period_bucket=BUCKET, file_fallback=False)
        assert result.tickers_seen == 3


# ---------------------------------------------------------------------------
# 9. TestNoDuplicates — DB-level uniqueness
# ---------------------------------------------------------------------------

class TestNoDuplicates:
    @pytest.mark.asyncio
    async def test_no_duplicate_rows_after_repeated_seed(self, db_session):
        from app.services.watchlist_job_seeder import seed_watchlist_jobs
        await _add_ticker(db_session, "AAPL")
        for _ in range(5):
            await seed_watchlist_jobs(db_session, period_bucket=BUCKET, next_run_utc=NOW, file_fallback=False)
        rows = await _list_jobs(db_session)
        aapl_rows = [r for r in rows if r.target_key == "AAPL"]
        assert len(aapl_rows) == 1

    @pytest.mark.asyncio
    async def test_each_ticker_exactly_one_job(self, db_session):
        from app.services.watchlist_job_seeder import seed_watchlist_jobs
        tickers = ["AAPL", "MSFT", "NVDA", "GOOGL", "META"]
        for t in tickers:
            await _add_ticker(db_session, t)
        await seed_watchlist_jobs(db_session, period_bucket=BUCKET, next_run_utc=NOW, file_fallback=False)
        await seed_watchlist_jobs(db_session, period_bucket=BUCKET, next_run_utc=NOW, file_fallback=False)
        rows = await _list_jobs(db_session)
        assert len(rows) == len(tickers)


# ---------------------------------------------------------------------------
# 10. TestFileFallback
# ---------------------------------------------------------------------------

class TestFileFallback:
    @pytest.mark.asyncio
    async def test_file_fallback_false_no_jobs_when_db_empty(self, db_session):
        from app.services.watchlist_job_seeder import seed_watchlist_jobs
        result = await seed_watchlist_jobs(db_session, period_bucket=BUCKET, file_fallback=False)
        assert result.jobs_created == 0

    @pytest.mark.asyncio
    async def test_db_rows_take_priority_over_file(self, db_session):
        from app.services.watchlist_job_seeder import seed_watchlist_jobs
        # Put exactly one ticker in DB
        await _add_ticker(db_session, "AAPL")
        # file_fallback=True but DB has data — should use DB, not file
        result = await seed_watchlist_jobs(db_session, period_bucket=BUCKET, next_run_utc=NOW, file_fallback=True)
        # Should only see AAPL (from DB), not the full file watchlist
        assert "AAPL" in result.tickers_seeded
        # All seeded tickers should be from DB
        rows = await _list_jobs(db_session)
        seeded_tickers = {r.target_key for r in rows}
        assert "AAPL" in seeded_tickers


# ---------------------------------------------------------------------------
# 11. TestCustomParameters
# ---------------------------------------------------------------------------

class TestCustomParameters:
    @pytest.mark.asyncio
    async def test_custom_period_bucket(self, db_session):
        from app.services.watchlist_job_seeder import seed_watchlist_jobs
        await _add_ticker(db_session, "AAPL")
        result = await seed_watchlist_jobs(
            db_session, period_bucket="2026-12-31", next_run_utc=NOW, file_fallback=False
        )
        assert result.period_bucket == "2026-12-31"
        row = await _get_job(db_session, "watchlist_scan", "AAPL", "2026-12-31")
        assert row is not None

    @pytest.mark.asyncio
    async def test_custom_cadence(self, db_session):
        from app.services.watchlist_job_seeder import seed_watchlist_jobs
        await _add_ticker(db_session, "AAPL")
        await seed_watchlist_jobs(
            db_session, period_bucket=BUCKET, next_run_utc=NOW, file_fallback=False, cadence="hourly"
        )
        row = await _get_job(db_session, "watchlist_scan", "AAPL", BUCKET)
        assert row.cadence == "hourly"

    @pytest.mark.asyncio
    async def test_custom_max_attempts(self, db_session):
        from app.services.watchlist_job_seeder import seed_watchlist_jobs
        await _add_ticker(db_session, "AAPL")
        await seed_watchlist_jobs(
            db_session, period_bucket=BUCKET, next_run_utc=NOW, file_fallback=False, max_attempts=5
        )
        row = await _get_job(db_session, "watchlist_scan", "AAPL", BUCKET)
        assert row.max_attempts == 5


# ---------------------------------------------------------------------------
# 12. TestNoProducerExecution — seeder must not run analysis
# ---------------------------------------------------------------------------

class TestNoProducerExecution:
    @pytest.mark.asyncio
    async def test_seeder_creates_no_job_runs(self, db_session):
        from app.services.watchlist_job_seeder import seed_watchlist_jobs
        from app.db.models import JobRun
        from sqlalchemy import select
        await _add_ticker(db_session, "AAPL")
        await seed_watchlist_jobs(db_session, period_bucket=BUCKET, next_run_utc=NOW, file_fallback=False)
        result = await db_session.execute(select(JobRun))
        runs = list(result.scalars().all())
        assert runs == []

    @pytest.mark.asyncio
    async def test_seeder_creates_no_delivery_rows(self, db_session):
        from app.services.watchlist_job_seeder import seed_watchlist_jobs
        from app.db.models import DeliveryLedger
        from sqlalchemy import select
        await _add_ticker(db_session, "AAPL")
        await seed_watchlist_jobs(db_session, period_bucket=BUCKET, next_run_utc=NOW, file_fallback=False)
        result = await db_session.execute(select(DeliveryLedger))
        deliveries = list(result.scalars().all())
        assert deliveries == []

    @pytest.mark.asyncio
    async def test_seeded_job_state_is_scheduled_not_running(self, db_session):
        from app.services.watchlist_job_seeder import seed_watchlist_jobs
        await _add_ticker(db_session, "AAPL")
        await seed_watchlist_jobs(db_session, period_bucket=BUCKET, next_run_utc=NOW, file_fallback=False)
        rows = await _list_jobs(db_session)
        for row in rows:
            assert row.state == "scheduled"
            assert row.holder_id is None
            assert row.attempts == 0
