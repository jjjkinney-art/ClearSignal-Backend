"""
Watchlist Job Seeder — Phase 10B · Slice 3.

Creates ``scheduled_jobs`` rows for every active ticker in ``watched_tickers``
so the loop scheduler can claim and execute them on the next tick.

Design decisions
----------------
* One job per (ticker, period_bucket): ``job_type="watchlist_scan"``,
  ``target_key=ticker``, ``period_bucket=YYYY-MM-DD`` (UTC date).
* ``next_run_utc`` defaults to *now* so the job is immediately claimable.
* Idempotent: ``job_create`` uses a UNIQUE-constraint savepoint; calling
  ``seed_watchlist_jobs`` twice on the same day is safe and records the
  pre-existing count in ``SeedResult.jobs_existing``.
* No loop execution: this function does NOT enable the loop, start the
  scheduler, or trigger any producer.  ``LOOP_ENABLED`` stays False.
* File fallback: when ``watched_tickers`` is empty or DB is disabled, the
  seeder reads tickers from the flat-file index.json (migration convenience,
  controlled by ``file_fallback=True``).

Usage
-----
Callable manually via the admin endpoint or from future seeding hooks:

    from app.services.watchlist_job_seeder import seed_watchlist_jobs
    result = await seed_watchlist_jobs(session)

Or via the standalone helper that opens its own session:

    from app.services.watchlist_job_seeder import run_seed
    result = await run_seed()
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

JOB_TYPE: str = "watchlist_scan"
DEFAULT_CADENCE: str = "daily"
DEFAULT_MAX_ATTEMPTS: int = 3


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass
class SeedResult:
    """Summary of one seeder invocation.

    Attributes
    ----------
    tickers_seen:  active tickers found (DB or file fallback)
    jobs_created:  new scheduled_jobs rows inserted
    jobs_existing: rows that already existed (idempotent skip)
    errors:        per-ticker failure count
    period_bucket: the YYYY-MM-DD bucket used for this run
    tickers_seeded: list of ticker symbols that got new jobs
    """
    tickers_seen: int = 0
    jobs_created: int = 0
    jobs_existing: int = 0
    errors: int = 0
    period_bucket: str = ""
    tickers_seeded: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Period-bucket helpers
# ---------------------------------------------------------------------------

def current_period_bucket(utc_date: Optional[date] = None) -> str:
    """Return the period_bucket string for a given UTC date (default: today).

    Format: ``YYYY-MM-DD``.  Stable across calls on the same day so that
    the UNIQUE(job_type, target_key, period_bucket) constraint deduplicates
    repeated seeder runs within the same calendar day.
    """
    d = utc_date or datetime.now(timezone.utc).date()
    return d.strftime("%Y-%m-%d")


# ---------------------------------------------------------------------------
# Core seeder
# ---------------------------------------------------------------------------

async def seed_watchlist_jobs(
    session,
    *,
    period_bucket: Optional[str] = None,
    next_run_utc: Optional[datetime] = None,
    file_fallback: bool = True,
    cadence: str = DEFAULT_CADENCE,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
) -> SeedResult:
    """Create one ``watchlist_scan`` scheduled_job per active ticker.

    Parameters
    ----------
    session:
        AsyncSession (or None).  Passing None returns a zero SeedResult.
    period_bucket:
        Override the YYYY-MM-DD bucket.  Defaults to today's UTC date.
    next_run_utc:
        When the job first becomes claimable.  Defaults to *now* (immediate).
    file_fallback:
        When True and DB has no active tickers (e.g. backfill not yet run),
        fall back to the flat-file watchlist.  Set False to restrict to DB.
    cadence:
        Scheduling cadence string stored on the row (informational; the
        scheduler uses next_run_utc for its first claim).
    max_attempts:
        How many times the scheduler may retry a failed job.

    Returns
    -------
    SeedResult with per-run counts.
    """
    result = SeedResult(period_bucket=period_bucket or current_period_bucket())

    if session is None:
        return result

    tickers = await _resolve_tickers(session, file_fallback)
    result.tickers_seen = len(tickers)

    if not tickers:
        logger.info("[seeder] no active tickers — nothing to seed")
        return result

    now = next_run_utc or datetime.now(timezone.utc)

    for ticker in tickers:
        try:
            created = await _seed_one(
                session,
                ticker=ticker,
                period_bucket=result.period_bucket,
                next_run_utc=now,
                cadence=cadence,
                max_attempts=max_attempts,
            )
            if created:
                result.jobs_created += 1
                result.tickers_seeded.append(ticker)
            else:
                result.jobs_existing += 1
        except Exception as exc:
            logger.warning("[seeder] error seeding %s: %r", ticker, exc)
            result.errors += 1

    logger.info(
        "[seeder] seed complete — tickers=%d created=%d existing=%d errors=%d bucket=%s",
        result.tickers_seen,
        result.jobs_created,
        result.jobs_existing,
        result.errors,
        result.period_bucket,
    )
    return result


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

async def _resolve_tickers(session, file_fallback: bool) -> List[str]:
    """Return the list of active ticker symbols to seed.

    Tries DB first; falls back to file when DB has no rows and
    file_fallback=True.
    """
    from app.db.repositories.watchlist_repo import ticker_list_active

    db_rows = await ticker_list_active(session)
    if db_rows:
        return [row.ticker for row in db_rows]

    if not file_fallback:
        return []

    try:
        from app.services.watchlist_service import watchlist_service
        entries = watchlist_service.get_watchlist()
        return [e.ticker for e in entries if e.ticker]
    except Exception as exc:
        logger.warning("[seeder] file fallback failed: %r", exc)
        return []


async def _seed_one(
    session,
    ticker: str,
    period_bucket: str,
    next_run_utc: datetime,
    cadence: str,
    max_attempts: int,
) -> bool:
    """Seed one ticker.  Returns True if a new row was created, False if existing."""
    from app.db.repositories.loop_repo import job_get_by_identity, job_create

    existing = await job_get_by_identity(session, JOB_TYPE, ticker, period_bucket)
    if existing is not None:
        return False

    row = await job_create(
        session,
        job_type=JOB_TYPE,
        target_key=ticker,
        period_bucket=period_bucket,
        next_run_utc=next_run_utc,
        cadence=cadence,
        max_attempts=max_attempts,
    )
    return row is not None


# ---------------------------------------------------------------------------
# Standalone helper (opens its own session)
# ---------------------------------------------------------------------------

async def run_seed(
    *,
    period_bucket: Optional[str] = None,
    file_fallback: bool = True,
) -> SeedResult:
    """Open a DB session and run the seeder.  Convenience for admin usage.

    Usage::

        import asyncio
        from app.services.watchlist_job_seeder import run_seed
        result = asyncio.run(run_seed())
    """
    from app.db.connection import get_session

    async with get_session() as session:
        return await seed_watchlist_jobs(
            session,
            period_bucket=period_bucket,
            file_fallback=file_fallback,
        )
