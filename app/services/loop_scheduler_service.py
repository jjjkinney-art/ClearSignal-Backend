"""
Phase 10A · Slice 4 — Continuous Intelligence Loop scheduler.

This module owns the tick() function — the unit of work for one loop
iteration — and the producer registry that maps job_type strings to
async producer callables.

Architecture
------------
tick() is a pure async function: it takes a session and a holder_id,
does exactly one pass of the loop, and returns a TickResult.  It does
NOT start background tasks, does NOT sleep, and does NOT schedule the
next tick.  The background runner (wired in startup.py during Slice 5)
calls tick() in a periodic asyncio task.

Loop execution order per tick (spec §2.2):
  1. Check loop_enabled gate — return inert result if False.
  2. Acquire the tick lock ("loop:tick") — skip if held by another worker.
  3. Reap expired job locks (crash recovery).
  4. Claim up to `batch_size` due ScheduledJob rows (CAS, fence_token++).
  5. For each claimed job:
       a. Idempotency check: if a succeeded JobRun exists for work_key → skip.
       b. Append a 'running' JobRun audit row.
       c. Transition the job to state='running'.
       d. Dispatch to the registered producer (or stub if none registered).
       e. Record the terminal outcome on the run row.
       f. Transition the job: succeeded → mark_success;
          failed+retryable → mark_failure (reschedule);
          failed+exhausted  → mark_dead_letter.
  6. Release tick lock.
  7. Return TickResult with per-tick counters for telemetry.

Producer registry
-----------------
Producers are registered globally via:

    loop_scheduler_service.register_producer("daily_brief", my_producer_fn)

A producer has signature:
    async def producer(session, job, run_id, holder_id, fence_token) -> ProducerResult

ProducerResult fields:
    outcome         : str   — "succeeded" | "failed" | "skipped_stale"
    spent_llm_calls : int   — LLM calls consumed
    drift_hit       : bool  — true if signal was stale / below threshold
    error           : Optional[str]

Unregistered job_types return a ProducerResult(outcome="failed",
error="no_producer") and increment the job's attempt counter.  The
job will eventually dead-letter after max_attempts.

Null-object safety
------------------
session=None → TickResult with jobs_claimed=0 (no-op, no exception).

Spec references
---------------
§2   — The tick loop
§3   — Idempotency (work_key short-circuit)
§4   — Locking (tick lock, fence tokens)
§5   — State machine transitions
§5.3 — Drift coalescing (period_bucket)
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional

from app.db.repositories import loop_repo
from app.services import loop_lock_service
from app.services.loop_idempotency_service import build_work_key
from app.services import loop_drift_service

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tick-lock name
# ---------------------------------------------------------------------------

_TICK_LOCK = "loop:tick"


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _expires(lease_s: int) -> datetime:
    return _now() + timedelta(seconds=lease_s)


# Work-key computation is canonically owned by loop_idempotency_service.
# The local alias keeps internal call sites unchanged and avoids a circular
# import between the service modules.
_compute_work_key = build_work_key


def _is_loop_enabled() -> bool:
    """Read the master loop gate, applying the kill-switch override if set."""
    try:
        from app.config import settings
        from app.services import loop_canary_telemetry as _tel
        return _tel.get_enabled(bool(settings.loop_enabled))
    except Exception:
        return False


def _tick_config() -> tuple[int, int, int]:
    """Return (batch_size, lease_s, retry_backoff_s) from settings."""
    try:
        from app.config import settings
        return (
            settings.loop_tick_batch_size,
            settings.loop_lock_lease_s,
            settings.loop_retry_backoff_s,
        )
    except Exception:
        return (10, 120, 300)


# ===========================================================================
# Public data types
# ===========================================================================

@dataclass
class ProducerResult:
    """Return value from a registered producer callable."""
    outcome: str = "succeeded"          # succeeded | failed | skipped_stale
    spent_llm_calls: int = 0
    drift_hit: bool = False
    error: Optional[str] = None
    # Slice 6: extended result fields for producer payloads
    items_emitted: int = 0
    payload_json: Optional[dict] = None
    content_key_candidates: List[str] = field(default_factory=list)


@dataclass
class TickResult:
    """Summary of one tick() invocation.  Returned even on early-exit paths."""
    ts: str = ""
    loop_enabled: bool = False
    tick_acquired: bool = False         # False → another worker held the tick lock
    jobs_claimed: int = 0
    jobs_succeeded: int = 0
    jobs_failed: int = 0
    jobs_dead_lettered: int = 0
    jobs_short_circuited: int = 0       # idempotency skips
    locks_reaped: int = 0
    errors: List[str] = field(default_factory=list)


# ===========================================================================
# Producer registry
# ===========================================================================

_PRODUCERS: Dict[str, Callable] = {}


def register_producer(job_type: str, fn: Callable) -> None:
    """
    Register a producer callable for *job_type*.

    The callable must have signature:
        async def fn(session, job, run_id, holder_id, fence_token) -> ProducerResult

    Overwrites any previously registered producer for the same job_type.
    Call this during application startup (before the loop is enabled).
    """
    _PRODUCERS[job_type] = fn
    logger.info("[scheduler] registered producer for job_type=%r", job_type)


def unregister_producer(job_type: str) -> None:
    """Remove the producer for *job_type* (primarily for test teardown)."""
    _PRODUCERS.pop(job_type, None)


def list_registered_producers() -> List[str]:
    """Return the currently registered job_type keys."""
    return list(_PRODUCERS.keys())


# ===========================================================================
# Internal dispatch
# ===========================================================================

async def _dispatch(
    session,
    job: Any,
    run_id: str,
    holder_id: str,
    fence_token: int,
) -> ProducerResult:
    """
    Route *job* to its registered producer.

    Returns ProducerResult(outcome="failed", error="no_producer") if no
    producer is registered for job.job_type — the job will be retried or
    dead-lettered by the caller.
    """
    fn = _PRODUCERS.get(job.job_type)
    if fn is None:
        logger.warning(
            "[scheduler] no producer registered for job_type=%r (job %s)",
            job.job_type, job.id,
        )
        return ProducerResult(outcome="failed", error=f"no_producer:{job.job_type}")
    try:
        result = await fn(session, job, run_id, holder_id, fence_token)
        if not isinstance(result, ProducerResult):
            logger.warning(
                "[scheduler] producer for %r returned %r (expected ProducerResult) — "
                "wrapping as succeeded",
                job.job_type, type(result).__name__,
            )
            result = ProducerResult(outcome="succeeded")
        return result
    except Exception as exc:
        logger.exception(
            "[scheduler] producer for %r raised: %r", job.job_type, exc
        )
        return ProducerResult(outcome="failed", error=repr(exc))


# ---------------------------------------------------------------------------
# Drift gate helpers
# ---------------------------------------------------------------------------

def _is_force_run(job: Any) -> bool:
    """Return True if this job should bypass the drift gate."""
    try:
        from app.config import settings
        if settings.loop_force_run:
            return True
    except Exception:
        pass
    payload = getattr(job, "payload_json", {}) or {}
    return bool(payload.get("force_run", False))


# ---------------------------------------------------------------------------
# Drift error encoding
# ---------------------------------------------------------------------------

def _encode_drift_error(drift: Any) -> str:
    """Encode a DriftSignal as a 'drift_gate:…' prefixed JSON string.

    Format: ``"drift_gate:" + json.dumps({reason, score, signals, latest_signal_at})``

    Preserves backward-compat with ``error.startswith("drift_gate:")`` while
    making the full signal source available for tests and observability queries.
    """
    try:
        payload = {
            "reason": getattr(drift, "reason", ""),
            "score": round(float(getattr(drift, "materiality_score", 0.0)), 3),
            "signals": list(getattr(drift, "signals", []))[:5],
            "latest_signal_at": getattr(drift, "latest_signal_at", None),
        }
        return "drift_gate:" + json.dumps(payload)
    except Exception:
        return f"drift_gate:{getattr(drift, 'reason', 'unknown')}"


# ===========================================================================
# Job handling pipeline
# ===========================================================================

async def _handle_job(
    session,
    job: Any,
    holder_id: str,
    lease_s: int,
    retry_backoff_s: int,
) -> str:
    """
    Execute the full pipeline for one claimed job.

    Returns one of: "succeeded" | "failed" | "dead_letter" | "short_circuited" | "error"
    """
    work_key = _compute_work_key(job.job_type, job.target_key, job.period_bucket)

    # ── Idempotency short-circuit ─────────────────────────────────────────────
    existing = await loop_repo.run_lookup_by_work_key(
        session, work_key, outcome="succeeded"
    )
    if existing is not None:
        logger.info(
            "[scheduler] short-circuit job %s (%s/%s/%s) — succeeded run %s exists",
            job.id, job.job_type, job.target_key, job.period_bucket, existing.id,
        )
        # Append an audit run so every claim has a traceable outcome row.
        # outcome='short_circuited' signals "work already done; dispatch skipped".
        sc_run = await loop_repo.run_append(
            session,
            job_id=job.id,
            work_key=work_key,
            job_type=job.job_type,
            target_key=job.target_key,
            period_bucket=job.period_bucket,
            holder_id=holder_id,
            fence_token=job.fence_token,
        )
        if sc_run is not None:
            await loop_repo.run_finish(session, sc_run.id, "short_circuited")
        await loop_repo.job_update_state(
            session, job.id, "skipped_stale", expected_state="claimed"
        )
        return "short_circuited"

    # ── Drift gate ────────────────────────────────────────────────────────────
    drift = await loop_drift_service.should_run_job(
        session,
        job.job_type,
        job.target_key,
        job.period_bucket,
        getattr(job, "last_generated_at", None),
        force_run=_is_force_run(job),
    )
    if not drift.should_run:
        logger.info(
            "[scheduler] drift gate skipped job %s (%s/%s) — %s (score=%.2f)",
            job.id, job.job_type, job.target_key, drift.reason, drift.materiality_score,
        )
        # Append audit run so every claim has a traceable row.
        dg_run = await loop_repo.run_append(
            session,
            job_id=job.id,
            work_key=work_key,
            job_type=job.job_type,
            target_key=job.target_key,
            period_bucket=job.period_bucket,
            holder_id=holder_id,
            fence_token=job.fence_token,
        )
        if dg_run is not None:
            await loop_repo.run_finish(
                session, dg_run.id, "skipped_stale",
                drift_hit=True,
                error=_encode_drift_error(drift),
            )
        await loop_repo.job_update_state(
            session, job.id, "skipped_stale", expected_state="claimed"
        )
        return "short_circuited"

    # ── Append run audit row ──────────────────────────────────────────────────
    run = await loop_repo.run_append(
        session,
        job_id=job.id,
        work_key=work_key,
        job_type=job.job_type,
        target_key=job.target_key,
        period_bucket=job.period_bucket,
        holder_id=holder_id,
        fence_token=job.fence_token,
    )
    if run is None:
        logger.error("[scheduler] run_append failed for job %s — skipping", job.id)
        await loop_repo.job_mark_failure(
            session, job.id, holder_id, job.fence_token,
            error="run_append_failed",
            next_run_utc=_now() + timedelta(seconds=retry_backoff_s),
        )
        return "error"

    # ── Transition job → running ──────────────────────────────────────────────
    await loop_repo.job_update_state(
        session, job.id, "running", expected_state="claimed"
    )

    # ── Dispatch to producer ──────────────────────────────────────────────────
    result = await _dispatch(session, job, run.id, holder_id, job.fence_token)

    # ── Record terminal outcome on run row ────────────────────────────────────
    await loop_repo.run_finish(
        session, run.id, result.outcome,
        spent_llm_calls=result.spent_llm_calls,
        drift_hit=result.drift_hit,
        error=result.error,
    )

    # ── Transition job to terminal / retry state ──────────────────────────────
    if result.outcome == "succeeded":
        await loop_repo.job_mark_success(
            session, job.id, holder_id, job.fence_token,
            last_generated_at=_now(),
        )
        logger.info(
            "[scheduler] job %s (%s/%s) succeeded (llm_calls=%d drift=%s)",
            job.id, job.job_type, job.target_key,
            result.spent_llm_calls, result.drift_hit,
        )
        return "succeeded"

    if result.outcome == "skipped_stale":
        await loop_repo.job_update_state(
            session, job.id, "skipped_stale", expected_state="running"
        )
        return "short_circuited"

    # Failed path — check if exhausted
    if job.attempts >= job.max_attempts:
        await loop_repo.job_mark_dead_letter(
            session, job.id, holder_id, job.fence_token
        )
        logger.warning(
            "[scheduler] job %s dead-lettered after %d/%d attempts: %s",
            job.id, job.attempts, job.max_attempts, result.error,
        )
        return "dead_letter"

    # Retryable failure — reschedule
    next_run = _now() + timedelta(seconds=retry_backoff_s)
    await loop_repo.job_mark_failure(
        session, job.id, holder_id, job.fence_token,
        error=result.error,
        next_run_utc=next_run,
    )
    logger.info(
        "[scheduler] job %s failed (attempt %d/%d) — retry at %s: %s",
        job.id, job.attempts, job.max_attempts,
        next_run.strftime("%H:%MZ"), result.error,
    )
    return "failed"


# ===========================================================================
# Public API
# ===========================================================================

async def tick(
    session,
    holder_id: str,
    *,
    batch_size: Optional[int] = None,
    lease_s: Optional[int] = None,
    retry_backoff_s: Optional[int] = None,
) -> TickResult:
    """
    Execute one iteration of the Continuous Intelligence Loop.

    Parameters
    ----------
    session       : AsyncSession or None — null-safe; returns inert TickResult.
    holder_id     : Stable worker identity string (e.g. ``"{host}:{pid}:{uuid}"``)
    batch_size    : Override `loop_tick_batch_size` from settings.
    lease_s       : Override `loop_lock_lease_s` from settings.
    retry_backoff_s : Override `loop_retry_backoff_s` from settings.

    Returns
    -------
    TickResult with per-tick counters; never raises.
    """
    ts = _now().strftime("%Y-%m-%dT%H:%M:%SZ")
    result = TickResult(ts=ts)

    # ── Null session ──────────────────────────────────────────────────────────
    if session is None:
        return result

    # ── Loop gate ─────────────────────────────────────────────────────────────
    enabled = _is_loop_enabled()
    result.loop_enabled = enabled
    if not enabled:
        logger.debug("[scheduler] tick skipped — loop_enabled=False")
        return result

    # ── Config resolution ─────────────────────────────────────────────────────
    cfg_batch, cfg_lease, cfg_backoff = _tick_config()
    _batch  = batch_size      if batch_size      is not None else cfg_batch
    _lease  = lease_s         if lease_s         is not None else cfg_lease
    _retry  = retry_backoff_s if retry_backoff_s is not None else cfg_backoff

    # ── Acquire tick lock ─────────────────────────────────────────────────────
    tick_token = await loop_lock_service.acquire_lock(
        session, _TICK_LOCK, holder_id, lease_s=_lease
    )
    if tick_token is None:
        logger.debug("[scheduler] tick skipped — tick lock held by another worker")
        return result
    result.tick_acquired = True

    try:
        # ── Reap expired locks ────────────────────────────────────────────────
        reaped = await loop_lock_service.reap_expired_locks(session)
        result.locks_reaped = len(reaped)

        # ── Claim due jobs ────────────────────────────────────────────────────
        now = _now()
        lease_exp = _expires(_lease)
        claimed_jobs = await loop_repo.job_claim_due(
            session, now, holder_id, lease_exp, batch_size=_batch
        )
        result.jobs_claimed = len(claimed_jobs)

        if not claimed_jobs:
            logger.debug("[scheduler] tick complete — no due jobs")
            return result

        # ── Handle each job ───────────────────────────────────────────────────
        for job in claimed_jobs:
            try:
                outcome = await _handle_job(session, job, holder_id, _lease, _retry)
            except Exception as exc:
                logger.exception(
                    "[scheduler] _handle_job raised for job %s: %r", job.id, exc
                )
                outcome = "error"
                result.errors.append(f"{job.id}:{exc!r}")

            if outcome == "succeeded":
                result.jobs_succeeded += 1
            elif outcome in ("failed", "error"):
                result.jobs_failed += 1
            elif outcome == "dead_letter":
                result.jobs_dead_lettered += 1
            elif outcome == "short_circuited":
                result.jobs_short_circuited += 1

    finally:
        # ── Release tick lock (always — even if a job handler raised) ─────────
        await loop_lock_service.release_lock(
            session, _TICK_LOCK, holder_id, tick_token
        )

    logger.info(
        "[scheduler] tick done — claimed=%d succeeded=%d failed=%d "
        "dead=%d skipped=%d reaped=%d",
        result.jobs_claimed, result.jobs_succeeded, result.jobs_failed,
        result.jobs_dead_lettered, result.jobs_short_circuited, result.locks_reaped,
    )
    try:
        from app.services import loop_canary_telemetry as _tel
        _tel.record_tick(result)
    except Exception:
        pass
    return result


async def tick_is_locked(session) -> bool:
    """Return True if the tick lock is currently held (another worker is ticking)."""
    return not await loop_lock_service.is_lock_free(session, _TICK_LOCK)
